#!/usr/bin/env python3
"""
GLIO-CARTOGRAPHY — Desktop App Backend
FastAPI server that orchestrates the full pipeline
"""

import gc
import html
import json
import logging
import os
import sys
import tempfile
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

# Force UTF-8 encoding on standard streams to prevent UnicodeEncodeError on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass  # Older Python versions

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import asyncio
import argparse

# FastAPI
try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    import uvicorn
    from pydantic import BaseModel
except ImportError:
    print("FastAPI not installed. Run: pip install fastapi uvicorn pydantic", file=sys.stderr)
    sys.exit(1)

# ── Pipeline runner ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from pipeline_runner import PipelineRunner, PipelineStatus

# =============================================================
# Logging
# =============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("server")

# =============================================================
# Security helpers
# =============================================================
# Trusted roots — output_dir must live under one of these
_ALLOWED_ROOTS = [Path.home().resolve(), Path(tempfile.gettempdir()).resolve()]


def validate_output_dir(raw: str) -> Path:
    """
    Resolve *raw* to an absolute path and verify it sits inside an allowed
    root directory.  Raises HTTPException(400) on any path traversal attempt.
    """
    try:
        p = Path(raw).expanduser().resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Geçersiz output_dir: {exc}") from exc

    if not any(p == root or root in p.parents for root in _ALLOWED_ROOTS):
        raise HTTPException(
            status_code=400,
            detail="output_dir erişim kısıtlaması: izin verilen köklerin dışında bir konum.",
        )
    return p


def sanitize_str(value: str) -> str:
    """Escape HTML special characters to prevent XSS in any downstream HTML use."""
    return html.escape(str(value), quote=True)


# =============================================================
# Async helpers
# =============================================================
async def _read_json_async(path: Path) -> dict:
    """Read and parse a JSON file off the event loop thread."""
    def _read() -> dict:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    try:
        return await asyncio.to_thread(_read)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Dosya bulunamadı: {path}") from exc
    except json.JSONDecodeError as exc:
        logger.error("JSON parse hatası (%s): %s", path, exc)
        raise HTTPException(status_code=500, detail=f"JSON parse hatası: {path}") from exc
    except Exception as exc:
        logger.error("Dosya okuma hatası (%s): %s", path, exc)
        raise HTTPException(status_code=500, detail=f"Dosya okuma hatası: {exc}") from exc


# =============================================================
# Lifespan / App state
# =============================================================
class AppState:
    """Holds mutable server state; accessed only under `pipeline_lock`."""

    def __init__(self) -> None:
        self.runner: Optional[PipelineRunner] = None
        self.pipeline_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(application: "FastAPI"):
    """Initialize shared state on startup; clean up on shutdown."""
    application.state.app_state = AppState()
    logger.info("Glio-Cartography backend başlatıldı.")
    
    # Yerel Cytoscape.js varlığını kontrol et/indir
    try:
        from pathway_mapper import download_frontend_assets
        download_frontend_assets()
    except Exception as e_asset:
        logger.error("Açılışta frontend assetleri indirilemedi: %s", e_asset)

    try:
        yield
    finally:
        state: AppState = application.state.app_state
        if state.runner and state.runner.status == PipelineStatus.RUNNING:
            state.runner.cancel()
            logger.info("Kapatma sırasında çalışan pipeline iptal edildi.")
        gc.collect()
        logger.info("Glio-Cartography backend kapatıldı.")


# =============================================================
# FastAPI App
# =============================================================
app = FastAPI(
    title="Glio-Cartography Desktop API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)


# =============================================================
# Request Models
# =============================================================
class PipelineStartRequest(BaseModel):
    spatial_dir: str
    scrna_path: str
    output_dir: str
    patient_id: Optional[str] = "Patient_A"
    run_optuna: Optional[bool] = False
    optuna_trials: Optional[int] = 5
    gnn_epochs: Optional[int] = 100
    deconv_method: Optional[str] = "tangram"  # tangram | cell2location | stereoscope
    # ── Klinik Metadata (FAZ 1 — Race Condition Önleme: env yerine JSON payload) ──
    clinical_age: Optional[int] = None          # Hasta yaşı (yıl); None → imputation
    clinical_mgmt: Optional[float] = None       # MGMT metilasyon skoru [0.0–1.0]; None → imputation
    clinical_idh: Optional[float] = None        # IDH mutasyon skoru [0.0–1.0]; None → imputation
    clinical_kps: Optional[int] = None          # Karnofsky Performance Score [0–100]; None → imputation
    imputation_mode: Optional[str] = "worst"    # "worst" | "median"


class LicenseCheckRequest(BaseModel):
    license_key: str
    machine_id: str


# =============================================================
# Routes
# =============================================================
@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "timestamp": datetime.now().isoformat()}


@app.get("/pipeline/status")
async def get_status():
    state: AppState = app.state.app_state
    async with state.pipeline_lock:
        if state.runner is None:
            return {"stage": "idle", "progress": 0, "logs": [], "status": "idle"}
        return state.runner.get_status()


@app.post("/pipeline/start")
async def start_pipeline(req: PipelineStartRequest):
    state: AppState = app.state.app_state

    # Validate and resolve paths
    spatial_dir = await asyncio.to_thread(lambda: Path(req.spatial_dir).resolve())
    scrna_path = await asyncio.to_thread(lambda: Path(req.scrna_path).resolve())
    output_dir = validate_output_dir(req.output_dir)
    patient_id = sanitize_str(req.patient_id or "Patient_A")

    if not spatial_dir.exists():
        raise HTTPException(status_code=400, detail=f"Spatial klasör bulunamadı: {spatial_dir}")
    if not scrna_path.exists():
        raise HTTPException(status_code=400, detail=f"scRNA dosyası bulunamadı: {scrna_path}")

    async with state.pipeline_lock:
        if state.runner and state.runner.status == PipelineStatus.RUNNING:
            raise HTTPException(status_code=409, detail="Pipeline zaten çalışıyor")

        # Create output dir safely (off event loop)
        await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)

        state.runner = PipelineRunner(
            spatial_dir=str(spatial_dir),
            scrna_path=str(scrna_path),
            output_dir=str(output_dir),
            patient_id=patient_id,
            run_optuna=req.run_optuna,
            optuna_trials=req.optuna_trials,
            gnn_epochs=req.gnn_epochs,
            deconv_method=req.deconv_method or "tangram",
            # Klinik metadata — JSON payload ile güvenli iletim (env race condition yok)
            clinical_age=req.clinical_age,
            clinical_mgmt=req.clinical_mgmt,
            clinical_idh=req.clinical_idh,
            clinical_kps=req.clinical_kps,
            imputation_mode=req.imputation_mode or "worst",
        )

    # Start pipeline task; store reference to prevent GC
    task = asyncio.create_task(state.runner.run(), name="pipeline_run")
    app.state.pipeline_task = task  # prevent garbage collection

    return {"message": "Pipeline başlatıldı", "output_dir": str(output_dir)}


@app.post("/pipeline/cancel")
async def cancel_pipeline():
    state: AppState = app.state.app_state
    async with state.pipeline_lock:
        if state.runner:
            state.runner.cancel()
            return {"message": "İptal edildi"}
    return {"message": "Aktif pipeline yok"}


@app.get("/pipeline/logs")
async def get_logs(since: int = 0):
    state: AppState = app.state.app_state
    async with state.pipeline_lock:
        if state.runner is None:
            return {"logs": []}
        return {"logs": state.runner.logs[since:]}


@app.get("/results/data")
async def get_results_data(output_dir: str):
    out = validate_output_dir(output_dir)
    data_path = out / "gnn" / "data.json"
    if not data_path.exists():
        raise HTTPException(status_code=404, detail="Sonuç verisi henüz hazır değil")
    data = await _read_json_async(data_path)
    return JSONResponse(content=data)


@app.get("/results/summary")
async def get_results_summary(output_dir: str):
    out = validate_output_dir(output_dir)

    summaries: dict = {}
    tasks = {
        "gnn": out / "gnn" / "gnn_summary.json",
        "deconvolution": out / "deconvolution" / "deconvolution_summary.json",
        "kaplan_meier": out / "gnn" / "kaplan_meier_summary.json",
    }

    for name, p in tasks.items():
        if p.exists():
            try:
                summaries[name] = await _read_json_async(p)
            except HTTPException:
                logger.warning("Özet dosyası okunamadı: %s", p)

    return summaries


@app.get("/results/lr-detailed")
async def get_lr_detailed(output_dir: str):
    out = validate_output_dir(output_dir)
    p = out / "gnn" / "lr_detailed_summary.json"
    if p.exists():
        return await _read_json_async(p)

    # Dynamic fallback calculation if data.json is present
    data_json_path = out / "gnn" / "data.json"
    if not data_json_path.exists():
        raise HTTPException(
            status_code=404,
            detail="L-R detaylı veri kataloğu henüz hazır değil ve GNN çıktısı (data.json) bulunamadı."
        )

    try:
        with open(data_json_path, 'r', encoding='utf-8') as f:
            data_json = json.load(f)
        
        spots = data_json.get("spots", [])
        zonal_contrast = data_json.get("zonal_contrast", {})
        lr_zonal_contrasts = zonal_contrast.get("lr_pairs", {})
        
        # Calculate zone weight sums (sum of probabilities across all spots)
        zone_weights = {}
        for spot in spots:
            for zone, prob in spot.get("zones", {}).items():
                zone_weights[zone] = zone_weights.get(zone, 0.0) + float(prob)
                
        total_weight = sum(zone_weights.values()) or 1.0
        
        # Compute global mean intensity for each L-R pair
        lr_means = {}
        for zone, lr_vals in lr_zonal_contrasts.items():
            w = zone_weights.get(zone, 0.0)
            for lr_key, val in lr_vals.items():
                lr_means[lr_key] = lr_means.get(lr_key, 0.0) + (float(val) * w)
                
        for lr_key in lr_means:
            lr_means[lr_key] /= total_weight
            
        # Load offline drug catalog
        catalog_path = Path(__file__).parent / "drug_catalog" / "drug_catalog.json"
        catalog_data = {}
        if catalog_path.exists():
            try:
                with open(catalog_path, 'r', encoding='utf-8') as f:
                    catalog_data = json.load(f).get("catalog", {})
            except Exception:
                pass
                
        # Import LR_PAIRS to get biological categories
        backend_dir = str(Path(__file__).parent)
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        try:
            from train_gnn import LR_PAIRS
        except ImportError:
            LR_PAIRS = []
            
        lr_categories = {}
        for lig, rec, cat in LR_PAIRS:
            lr_categories[f"{lig.upper()}-{rec.upper()}"] = cat
            
        lr_detailed = []
        for lr_key, mean_val in lr_means.items():
            parts = lr_key.split('-')
            lig = parts[0] if len(parts) > 0 else ""
            rec = parts[1] if len(parts) > 1 else ""
            
            cat = lr_categories.get(lr_key, "General").capitalize()
            
            drug_entry = catalog_data.get(lr_key, None)
            drug_name = drug_entry['drug'] if drug_entry else "Yok / Araştırma Safhası"
            drug_mech = drug_entry['mechanism'] if drug_entry else "—"
            
            lr_detailed.append({
                "pair": lr_key,
                "ligand": lig,
                "receptor": rec,
                "category": cat,
                "mean_intensity": mean_val,
                "drug": drug_name,
                "drug_mechanism": drug_mech
            })
            
        lr_detailed.sort(key=lambda x: x["mean_intensity"], reverse=True)
        
        # Save cache to disk
        try:
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(lr_detailed, f, ensure_ascii=False, indent=2)
            logger.info("Dynamic L-R detailed summary cached successfully: %s", p)
        except Exception as e_write:
            logger.warning("Dynamic L-R detailed summary diske yazılırken hata oluştu: %s", e_write)
            
        return lr_detailed
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Dinamik L-R kataloğu oluşturulamadı: {e}"
        )


@app.get("/results/simulate-knockout")
async def simulate_knockout(
    output_dir: str,
    knockout_type: str,
    simulation_mode: str = "cell",
    regulation_type: str = "knockdown",
):
    """
    Sanal müdahale (counterfactual GNN simulation) modülü.
    Hücre tipi susturma, hedefli L-R blokajı veya gen regülasyonunu GNN üzerinden tahmin eder.
    """
    try:
        import torch
        import numpy as np
        import anndata as ad
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"Bağımlılık eksik: {exc}") from exc

    out = validate_output_dir(output_dir)
    ko_type_safe = sanitize_str(knockout_type)

    backend_dir = str(Path(__file__).parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    try:
        from train_gnn import (
            GlioCartographyGNN,
            build_graph_data,
            ZONE_NAMES,
            LR_PAIRS,
            counterfactual_knockout,
            counterfactual_lr_blockade,
            counterfactual_gene_regulation,
        )
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"GNN modülü yüklenemedi: {exc}") from exc

    spatial_path = out / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    model_path: Optional[Path] = None
    for mp in [out / "models" / "glio_gnn_v3.pt", out / "gnn" / "glio_gnn_v3.pt", out / "glio_gnn_v3.pt"]:
        if mp.exists():
            model_path = mp
            break

    if not spatial_path.exists():
        raise HTTPException(status_code=404, detail=f"Spatial deconvolved veri bulunamadı: {spatial_path}")
    if model_path is None:
        raise HTTPException(status_code=404, detail="Eğitilmiş GNN model ağırlıkları bulunamadı")

    # Heavy I/O + compute off the event loop
    def _run_simulation():
        adata = ad.read_h5ad(spatial_path)
        data = build_graph_data(adata, k_neighbors=6)
        ct_names = data.ct_names

        in_ch = data.x.shape[1]
        edge_dim = data.edge_attr.shape[1]
        model = GlioCartographyGNN(in_ch=in_ch, edge_dim=edge_dim, n_ct=len(ct_names), n_zones=len(ZONE_NAMES))
        model.load_state_dict(torch.load(model_path, map_location="cpu"))
        model.eval()

        if simulation_mode == "cell":
            ko_query = ko_type_safe
            if ko_type_safe == "TAM":
                for term in ["macrophage", "tam", "microglia", "myeloid"]:
                    if any(term in cn.lower() for cn in ct_names):
                        ko_query = term
                        break
            elif ko_type_safe == "T_Cell":
                for term in ["t_cell", "t cell", "tcell", "lymphocyte"]:
                    if any(term in cn.lower() for cn in ct_names):
                        ko_query = term
                        break
            elif ko_type_safe == "Tumor_MES":
                for term in ["malignant", "mes", "stem_cell", "tumor"]:
                    if any(term in cn.lower() for cn in ct_names):
                        ko_query = term
                        break
            delta = counterfactual_knockout(model, data, ct_names, ko_query)
            if delta is None:
                raise ValueError(f"Hücre tipi eşleşmedi: {ko_type_safe}")

        elif simulation_mode == "lr":
            lr_names = [f"{l}-{r}" for l, r, _ in LR_PAIRS]
            delta = counterfactual_lr_blockade(model, data, lr_names, ko_type_safe, inhibition_rate=1.0)
            if delta is None:
                raise ValueError(f"Ligand-reseptör ekseni bulunamadı: {ko_type_safe}")

        elif simulation_mode == "gene":
            lr_names = [f"{l}-{r}" for l, r, _ in LR_PAIRS]
            delta = counterfactual_gene_regulation(model, data, lr_names, LR_PAIRS, ko_type_safe, reg_type=regulation_type, rate=1.0)
            if delta is None:
                raise ValueError(f"Gen L-R kütüphanesinde bulunamadı: {ko_type_safe}")

        else:
            raise ValueError(f"Bilinmeyen simülasyon modu: {simulation_mode}")

        mean_shifts = {zn: float(delta[:, z_idx].mean()) for z_idx, zn in enumerate(ZONE_NAMES)}
        magnitudes = [float(np.clip(val, 0.0, 1.0)) for val in np.abs(delta).sum(axis=1)]
        return mean_shifts, magnitudes

    try:
        mean_shifts, magnitudes = await asyncio.to_thread(_run_simulation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Knockout simülasyon hatası")
        raise HTTPException(status_code=500, detail=f"Simülasyon hatası: {exc}") from exc

    return {
        "knockout_type": ko_type_safe,
        "mean_shifts": mean_shifts,
        "magnitudes": magnitudes,
        "affected_spots": len(magnitudes),
    }


@app.get("/results/figures")
async def list_figures(output_dir: str):
    out = validate_output_dir(output_dir)

    search_dirs = [
        out / "deconvolution",
        out / "gnn" / "plots",
        out / "gnn",
        out / "publication_figures",
        out / "reports",
    ]

    def _collect():
        figures = []
        for d in search_dirs:
            if d.exists():
                for f in sorted(d.glob("*.png")):
                    figures.append({"path": str(f), "name": f.stem, "category": d.name})
        return figures

    figures = await asyncio.to_thread(_collect)
    return {"figures": figures}


@app.get("/results/deconv-quality")
async def get_deconv_quality(output_dir: str):
    """Dekonvolüsyon kalite metrikleri — entropy dağılımı ve confidence istatistikleri."""
    out = validate_output_dir(output_dir)
    summary_path = out / "deconvolution" / "deconvolution_summary.json"

    summary = await _read_json_async(summary_path)

    avg_conf    = summary.get("avg_confidence", 0)
    avg_entropy = summary.get("avg_entropy", 1.0)
    n_types     = summary.get("n_cell_types", 1)
    ct_names    = summary.get("cell_type_names", [])
    mean_props  = summary.get("mean_proportions", {})
    dom_freq    = summary.get("dominant_frequencies", {})

    # Quality grade (A–D)
    if avg_conf >= 0.70 and avg_entropy <= 0.40:
        quality_grade, quality_label, quality_color = "A", "Mükemmel", "#10b981"
    elif avg_conf >= 0.55 and avg_entropy <= 0.60:
        quality_grade, quality_label, quality_color = "B", "İyi", "#3b82f6"
    elif avg_conf >= 0.40 and avg_entropy <= 0.75:
        quality_grade, quality_label, quality_color = "C", "Orta", "#f59e0b"
    else:
        quality_grade, quality_label, quality_color = "D", "Düşük", "#ef4444"

    ct_table = [
        {"name": ct, "mean_prop": round(mean_props.get(ct, 0) * 100, 2), "dominant_spots": dom_freq.get(ct, 0)}
        for ct in ct_names
    ]
    ct_table.sort(key=lambda x: x["mean_prop"], reverse=True)

    return {
        "avg_confidence":  round(avg_conf * 100, 1),
        "avg_entropy":     round(avg_entropy, 4),
        "n_cell_types":    n_types,
        "quality_grade":   quality_grade,
        "quality_label":   quality_label,
        "quality_color":   quality_color,
        "cell_type_table": ct_table,
        "interpretation": {
            "confidence": "Her spotun en baskın hücre tipine atanma güveni",
            "entropy":    "0=kesin atanma, 1=belirsiz (eşit dağılım)",
            "grade":      f"{quality_grade} — {quality_label} dekonvolüsyon kalitesi",
        },
    }


@app.get("/results/gnn-model")
async def get_gnn_model_info(output_dir: str):
    """GNN model versiyonu, konfigürasyonu ve eğitim metrikleri."""
    out = validate_output_dir(output_dir)
    summary_path = out / "gnn" / "gnn_summary.json"
    model_path   = out / "gnn" / "glio_gnn_v3.pt"

    summary = await _read_json_async(summary_path)
    cfg = summary.get("cfg", {})

    model_size_mb = None
    if model_path.exists():
        model_size_mb = round(model_path.stat().st_size / 1024 / 1024, 2)

    return {
        "model_file":    "glio_gnn_v3.pt",
        "model_size_mb": model_size_mb,
        "architecture": {
            "hidden_dim":      cfg.get("hidden", 128),
            "attention_heads": cfg.get("heads", 4),
            "dropout":         cfg.get("drop", 0.3),
            "gat_layers":      cfg.get("n_gat", 2),
            "sage_layers":     cfg.get("n_sage", 1),
            "learning_rate":   cfg.get("lr", 1e-3),
        },
        "training": {
            "epochs_requested": cfg.get("epochs", 100),
            "epochs_trained":   summary.get("n_epochs_trained", 0),
            "patience":         cfg.get("patience", 30),
            "best_val_loss":    round(summary.get("best_val_loss", 0), 6),
            "test_mse":         round(summary.get("test_mse", 0), 6),
            "optuna_used":      cfg.get("hidden") != 128 or cfg.get("heads") != 4,
        },
        "output": {
            "n_spots":  summary.get("n_spots", 0),
            "zones":    summary.get("zones", []),
            "ct_names": summary.get("ct_names", []),
        },
        "correlations": summary.get("correlations", {}),
    }


# =============================================================
# Export helpers (CPU-bound → asyncio.to_thread)
# =============================================================
def _do_export_h5ad(out: Path, patient_id: str) -> Path:
    import anndata as ad
    import numpy as np
    import pandas as pd

    adata_sp_path  = out / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    data_json_path = out / "gnn" / "data.json"

    if not adata_sp_path.exists():
        raise FileNotFoundError("Orijinal spatial AnnData nesnesi bulunamadı.")
    if not data_json_path.exists():
        raise FileNotFoundError("Analiz sonuç verisi bulunamadı.")

    adata = ad.read_h5ad(adata_sp_path)
    with open(data_json_path, encoding="utf-8") as fh:
        data_json = json.load(fh)

    spots = data_json.get("spots", [])
    if spots:
        all_cts   = list(spots[0].get("ct", {}).keys())
        all_zones = list(spots[0].get("zones", {}).keys())
        ct_data   = {ct: [] for ct in all_cts}
        z_data    = {z: [] for z in all_zones}
        dom_zones, tcga_risks = [], []

        for s in spots:
            z_dict = s.get("zones", {})
            dom_zones.append(max(z_dict, key=z_dict.get) if z_dict else "N/A")
            tcga_risks.append(s.get("tcga_risk", 0.0))
            for ct in all_cts:
                ct_data[ct].append(s.get("ct", {}).get(ct, 0.0))
            for z in all_zones:
                z_data[z].append(z_dict.get(z, 0.0))

        adata.obs["dominant_zone"] = pd.Categorical(dom_zones)
        adata.obs["tcga_risk"]     = np.array(tcga_risks, dtype=np.float32)
        for ct, vals in ct_data.items():
            adata.obs[f"ct_{ct}"] = np.array(vals, dtype=np.float32)
        for z, vals in z_data.items():
            adata.obs[f"zone_{z.replace(' ', '_')}"] = np.array(vals, dtype=np.float32)

    exports_dir = out / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    h5ad_out = exports_dir / f"Klinik_Rapor_{patient_id}_analiz.h5ad"
    adata.write_h5ad(h5ad_out)
    return h5ad_out


def _do_export_csv(out: Path, patient_id: str) -> Path:
    import pandas as pd

    data_json_path = out / "gnn" / "data.json"
    if not data_json_path.exists():
        raise FileNotFoundError("Analiz sonuç verisi bulunamadı.")

    with open(data_json_path, encoding="utf-8") as fh:
        data_json = json.load(fh)

    rows = []
    spots = data_json.get("spots", [])
    for idx, s in enumerate(spots):
        z_dict = s.get("zones", {})
        row = {
            "spot_id":         s.get("barcode", f"spot_{idx}"),
            "x_coord":         s.get("x", 0.0),
            "y_coord":         s.get("y", 0.0),
            "dominant_zone":   max(z_dict, key=z_dict.get) if z_dict else "N/A",
            "tcga_risk_score": s.get("tcga_risk", 0.0),
        }
        for z_name, z_val in z_dict.items():
            row[f"zone_{z_name.replace(' ', '_')}_score"] = z_val
        for ct_name, ct_val in s.get("ct", {}).items():
            row[f"ct_{ct_name}_proportion"] = ct_val
        rows.append(row)

    df = pd.DataFrame(rows)
    exports_dir = out / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    csv_out = exports_dir / f"Klinik_Rapor_{patient_id}_spot_koordinatlari.csv"
    df.to_csv(csv_out, index=False)
    return csv_out


def _do_export_zip(out: Path, patient_id: str) -> Path:
    search_dirs = [
        out / "deconvolution",
        out / "gnn" / "plots",
        out / "gnn",
        out / "publication_figures",
        out / "reports",
    ]
    exports_dir = out / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    zip_out = exports_dir / f"Klinik_Rapor_{patient_id}_figur_paketi.zip"

    with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as zf:
        added: set = set()
        for d in search_dirs:
            if d.exists():
                for f in sorted(d.glob("*.png")):
                    if f.name not in added:
                        zf.write(f, arcname=f.name)
                        added.add(f.name)
    return zip_out


@app.get("/results/export-h5ad")
async def export_h5ad_endpoint(output_dir: str, patient_id: str = "Patient_A"):
    out = validate_output_dir(output_dir)
    pid = sanitize_str(patient_id)
    try:
        h5ad_path = await asyncio.to_thread(_do_export_h5ad, out, pid)
        return {"status": "ok", "path": str(h5ad_path), "filename": h5ad_path.name}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("h5ad export hatası")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/results/export-csv")
async def export_csv_endpoint(output_dir: str, patient_id: str = "Patient_A"):
    out = validate_output_dir(output_dir)
    pid = sanitize_str(patient_id)
    try:
        csv_path = await asyncio.to_thread(_do_export_csv, out, pid)
        return {"status": "ok", "path": str(csv_path), "filename": csv_path.name}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CSV export hatası")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/results/export-zip")
async def export_zip_endpoint(output_dir: str, patient_id: str = "Patient_A"):
    out = validate_output_dir(output_dir)
    pid = sanitize_str(patient_id)
    try:
        zip_path = await asyncio.to_thread(_do_export_zip, out, pid)
        return {"status": "ok", "path": str(zip_path), "filename": zip_path.name}
    except Exception as exc:
        logger.exception("ZIP export hatası")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# =============================================================
# Drug Catalog Endpoints
# =============================================================
_drug_catalog_refresh_state = {
    "current": 0,
    "total": 0,
    "message": "Idle",
    "status": "idle"
}


@app.get("/drug-catalog")
async def get_drug_catalog():
    """Yerel drug_catalog.json döner (offline-safe)."""
    catalog_path = Path(__file__).parent / "drug_catalog" / "drug_catalog.json"
    return await _read_json_async(catalog_path)


@app.get("/drug-catalog/refresh-status")
async def get_drug_catalog_refresh_status():
    """Katalog güncelleme durumunu döner."""
    return _drug_catalog_refresh_state


@app.post("/drug-catalog/refresh")
async def refresh_drug_catalog_endpoint():
    """
    ChEMBL'den asenkron çekip JSON günceller.
    Arka planda çalışır, durum /drug-catalog/refresh-status adresinden sorgulanır.
    """
    global _drug_catalog_refresh_state
    if _drug_catalog_refresh_state["status"] == "running":
        return {"status": "already_running", "message": "Güncelleme zaten devam ediyor."}

    from drug_catalog.drug_catalog_builder import refresh_catalog

    _drug_catalog_refresh_state["status"] = "running"
    _drug_catalog_refresh_state["current"] = 0
    _drug_catalog_refresh_state["total"] = 27
    _drug_catalog_refresh_state["message"] = "Güncelleme başlatılıyor..."

    def run_in_background():
        global _drug_catalog_refresh_state
        catalog_path = Path(__file__).parent / "drug_catalog" / "drug_catalog.json"

        def progress_cb(current, total, msg):
            _drug_catalog_refresh_state["current"] = current
            _drug_catalog_refresh_state["total"] = total
            _drug_catalog_refresh_state["message"] = msg

        try:
            success = refresh_catalog(catalog_path, progress_cb)
            if success:
                _drug_catalog_refresh_state["status"] = "success"
                _drug_catalog_refresh_state["message"] = "Katalog başarıyla güncellendi."
            else:
                _drug_catalog_refresh_state["status"] = "error"
                _drug_catalog_refresh_state["message"] = "Katalog güncellenirken hata oluştu."
        except Exception as e:
            logger.exception("Katalog güncelleme hatası")
            _drug_catalog_refresh_state["status"] = "error"
            _drug_catalog_refresh_state["message"] = f"Beklenmeyen hata: {e}"

    asyncio.create_task(asyncio.to_thread(run_in_background))
    return {"status": "started", "message": "Güncelleme arka planda başlatıldı."}


# =============================================================
# Pathway Enrichment Endpoints
# =============================================================
@app.get("/results/pathway-enrichment")
async def get_pathway_enrichment(
    output_dir: str, ligand: str, receptor: str,
    zone: Optional[str] = None  # IVY GAP zone: Leading_Edge, PN_Necrosis vb. (None=global)
):
    """L-R çifti için Welch's t-test + Fisher zenginleştirme analizi yapar.
    
    zone parametresi verilirse GNN'nin data.json zone tahminleriyle
    zone-stratified analiz yapılır (GNN + Pathway entegrasyonu).
    """
    import anndata as ad
    from pathway_mapper import calculate_zonal_pathway_enrichment

    out = validate_output_dir(output_dir)
    spatial_path = out / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    
    if not spatial_path.exists():
        raise HTTPException(status_code=404, detail="Spatial deconvolved veri seti bulunamadı. Lütfen önce analizi çalıştırın.")

    # GNN data.json yolu (zone-stratified analiz için)
    data_json_path = out / "gnn" / "data.json"

    def run_analysis():
        adata = ad.read_h5ad(spatial_path)
        return calculate_zonal_pathway_enrichment(
            adata, ligand, receptor,
            data_json_path=data_json_path if data_json_path.exists() else None,
            zone_name=zone
        )

    try:
        results = await asyncio.to_thread(run_analysis)
        return results
    except Exception as e:
        logger.exception("Pathway zenginleştirme analizi sırasında hata oluştu")
        raise HTTPException(status_code=500, detail=f"Analiz hatası: {e}")


@app.get("/results/pathway-image")
async def get_pathway_image(
    output_dir: str, pathway_id: str, ligand: str, receptor: str,
    zone: Optional[str] = None
):
    """Highlight edilmiş KEGG PNG haritası döner (zonal ve GNN attention uyumlu)."""
    import anndata as ad
    from fastapi.responses import FileResponse
    from pathway_mapper import find_lr_degs, find_lr_degs_zonal, generate_highlighted_kegg_image

    out = validate_output_dir(output_dir)
    spatial_path = out / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    data_json_path = out / "gnn" / "data.json"
    
    if not spatial_path.exists():
        raise HTTPException(status_code=404, detail="Spatial deconvolved veri seti bulunamadı.")

    def run_highlight():
        adata = ad.read_h5ad(spatial_path)
        if zone and zone.lower() not in ("", "all", "tüm_tümör", "global"):
            degs = find_lr_degs_zonal(
                adata, ligand, receptor,
                data_json_path=data_json_path,
                zone_name=zone
            )
        else:
            degs = find_lr_degs(
                adata, ligand, receptor,
                data_json_path=data_json_path if data_json_path.exists() else None
            )
        return generate_highlighted_kegg_image(pathway_id, ligand, receptor, degs, out)

    try:
        img_file_path = await asyncio.to_thread(run_highlight)
        if img_file_path and img_file_path.exists():
            return FileResponse(str(img_file_path), media_type="image/png")
        else:
            raise HTTPException(status_code=404, detail="Yolak haritası üretilemedi.")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Harita overlay üretimi sırasında hata oluştu")
        raise HTTPException(status_code=500, detail=f"Harita üretim hatası: {e}")


# =============================================================
# Main / Stage routing
# =============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Glio-Cartography backend server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stage", type=str, default=None,
                        choices=["preprocessing", "deconvolution", "gnn", "visualization", "report", "report_pdf"])
    args, _unknown = parser.parse_known_args()

    if args.stage:
        backend_dir = Path(__file__).resolve().parent
        stages_dir  = backend_dir / "stages"

        for p in [str(backend_dir), str(stages_dir)]:
            if p not in sys.path:
                sys.path.insert(0, p)

        stage_map = {
            "preprocessing":  ("stages.stage1_preprocessing",  "main"),
            "deconvolution":  ("stages.stage2_deconvolution",  "main"),
            "gnn":            ("stages.stage3_gnn",            "main"),
            "visualization":  ("stages.stage4_visualization",  "main"),
            "report":         ("stages.stage5_report",         "main"),
        }

        if args.stage == "report_pdf":
            # Forward remaining argv to generate_pdf_report (drop --stage report_pdf tokens)
            remaining = [a for a in sys.argv[1:] if a not in ("--stage", "report_pdf")]
            sys.argv = [sys.argv[0]] + remaining
            import generate_pdf_report  # noqa: F401  (module executes on import)
        elif args.stage in stage_map:
            module_name, func_name = stage_map[args.stage]
            import importlib
            mod = importlib.import_module(module_name)
            getattr(mod, func_name)()
        else:
            logger.error("Bilinmeyen aşama: %s", args.stage)
            sys.exit(1)

        sys.exit(0)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="info",
        loop="asyncio",
    )
