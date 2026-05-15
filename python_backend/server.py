#!/usr/bin/env python3
"""
GLIO-CARTOGRAPHY — Desktop App Backend
FastAPI server that orchestrates the full pipeline
"""

import os
import sys
import json
import asyncio
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

# FastAPI
try:
    from fastapi import FastAPI, BackgroundTasks, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    import uvicorn
    from pydantic import BaseModel
except ImportError:
    print("FastAPI not installed. Run: pip install fastapi uvicorn pydantic")
    sys.exit(1)

# ── Pipeline runner ──────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from pipeline_runner import PipelineRunner, PipelineStatus

# =============================================================
# FastAPI App
# =============================================================
app = FastAPI(title="Glio-Cartography Desktop API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global state ─────────────────────────────────────────────
runner: Optional[PipelineRunner] = None
pipeline_task: Optional[asyncio.Task] = None

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
    if runner is None:
        return {"stage": "idle", "progress": 0, "logs": [], "status": "idle"}
    return runner.get_status()

@app.post("/pipeline/start")
async def start_pipeline(req: PipelineStartRequest, background_tasks: BackgroundTasks):
    global runner, pipeline_task
    
    if runner and runner.status == PipelineStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Pipeline zaten çalışıyor")

    # Validate paths
    if not Path(req.spatial_dir).exists():
        raise HTTPException(status_code=400, detail=f"Spatial klasör bulunamadı: {req.spatial_dir}")
    if not Path(req.scrna_path).exists():
        raise HTTPException(status_code=400, detail=f"scRNA dosyası bulunamadı: {req.scrna_path}")

    # Create output dir
    Path(req.output_dir).mkdir(parents=True, exist_ok=True)

    # Init runner
    runner = PipelineRunner(
        spatial_dir=req.spatial_dir,
        scrna_path=req.scrna_path,
        output_dir=req.output_dir,
        patient_id=req.patient_id,
        run_optuna=req.run_optuna,
        optuna_trials=req.optuna_trials,
        gnn_epochs=req.gnn_epochs
    )

    import threading
    import asyncio
    
    def _run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.run())
        loop.close()

    threading.Thread(target=_run_in_thread, daemon=True).start()
    
    return {"message": "Pipeline başlatıldı", "output_dir": req.output_dir}

@app.post("/pipeline/cancel")
async def cancel_pipeline():
    global runner
    if runner:
        runner.cancel()
        return {"message": "İptal edildi"}
    return {"message": "Aktif pipeline yok"}

@app.get("/pipeline/logs")
async def get_logs(since: int = 0):
    if runner is None:
        return {"logs": []}
    return {"logs": runner.logs[since:]}

@app.get("/results/data")
async def get_results_data(output_dir: str):
    data_path = Path(output_dir) / "gnn" / "data.json"
    if not data_path.exists():
        raise HTTPException(status_code=404, detail="Sonuç verisi henüz hazır değil")
    with open(data_path, 'r') as f:
        return JSONResponse(content=json.load(f))

@app.get("/results/summary")
async def get_results_summary(output_dir: str):
    summaries = {}
    out = Path(output_dir)
    
    for name, p in [
        ("gnn", out / "gnn" / "gnn_summary.json"),
        ("deconvolution", out / "deconvolution" / "deconvolution_summary.json"),
        ("kaplan_meier", out / "gnn" / "kaplan_meier_summary.json"),
    ]:
        if p.exists():
            with open(p) as f:
                summaries[name] = json.load(f)

    return summaries

@app.get("/results/figures")
async def list_figures(output_dir: str):
    figures = []
    out = Path(output_dir)
    
    search_dirs = [
        out / "deconvolution",
        out / "gnn" / "plots",
        out / "gnn",
        out / "publication_figures",
        out / "reports"
    ]
    
    for d in search_dirs:
        if d.exists():
            for f in sorted(d.glob("*.png")):
                figures.append({
                    "path": str(f),
                    "name": f.stem,
                    "category": d.name
                })
    return {"figures": figures}

@app.get("/results/deconv-quality")
async def get_deconv_quality(output_dir: str):
    """Dekonvolüsyon kalite metrikleri — entropy dağılımı ve confidence istatistikleri."""
    import numpy as np
    out = Path(output_dir)
    summary_path = out / "deconvolution" / "deconvolution_summary.json"
    
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="Dekonvolüsyon özeti henüz hazır değil")
    
    with open(summary_path) as f:
        summary = json.load(f)
    
    avg_conf    = summary.get("avg_confidence", 0)
    avg_entropy = summary.get("avg_entropy", 1.0)
    n_types     = summary.get("n_cell_types", 1)
    ct_names    = summary.get("cell_type_names", [])
    mean_props  = summary.get("mean_proportions", {})
    dom_freq    = summary.get("dominant_frequencies", {})
    
    # Kalite notu (A-D): düşük entropi + yüksek confidence = iyi
    if avg_conf >= 0.70 and avg_entropy <= 0.40:
        quality_grade = "A"
        quality_label = "Mükemmel"
        quality_color = "#10b981"
    elif avg_conf >= 0.55 and avg_entropy <= 0.60:
        quality_grade = "B"
        quality_label = "İyi"
        quality_color = "#3b82f6"
    elif avg_conf >= 0.40 and avg_entropy <= 0.75:
        quality_grade = "C"
        quality_label = "Orta"
        quality_color = "#f59e0b"
    else:
        quality_grade = "D"
        quality_label = "Düşük"
        quality_color = "#ef4444"
    
    # Prop tablosu
    ct_table = [
        {"name": ct, "mean_prop": round(mean_props.get(ct, 0) * 100, 2),
         "dominant_spots": dom_freq.get(ct, 0)}
        for ct in ct_names
    ]
    ct_table.sort(key=lambda x: x["mean_prop"], reverse=True)
    
    return {
        "avg_confidence":    round(avg_conf * 100, 1),
        "avg_entropy":       round(avg_entropy, 4),
        "n_cell_types":      n_types,
        "quality_grade":     quality_grade,
        "quality_label":     quality_label,
        "quality_color":     quality_color,
        "cell_type_table":   ct_table,
        "interpretation": {
            "confidence": "Her spotun en baskın hücre tipine atanma güveni",
            "entropy":    "0=kesin atanma, 1=belirsiz (eşit dağılım)",
            "grade":      f"{quality_grade} — {quality_label} dekonvolüsyon kalitesi"
        }
    }

@app.get("/results/gnn-model")
async def get_gnn_model_info(output_dir: str):
    """GNN model versiyonu, konfigürasyonu ve eğitim metrikleri."""
    out = Path(output_dir)
    summary_path = out / "gnn" / "gnn_summary.json"
    model_path   = out / "gnn" / "glio_gnn_v3.pt"
    
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="GNN özeti henüz hazır değil")
    
    with open(summary_path) as f:
        summary = json.load(f)
    
    cfg = summary.get("cfg", {})
    model_size_mb = round(model_path.stat().st_size / 1024 / 1024, 2) if model_path.exists() else None
    
    return {
        "model_file":        "glio_gnn_v3.pt",
        "model_size_mb":     model_size_mb,
        "architecture": {
            "hidden_dim":    cfg.get("hidden", 128),
            "attention_heads": cfg.get("heads", 4),
            "dropout":       cfg.get("drop", 0.3),
            "gat_layers":    cfg.get("n_gat", 2),
            "sage_layers":   cfg.get("n_sage", 1),
            "learning_rate": cfg.get("lr", 1e-3),
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
            "n_spots":    summary.get("n_spots", 0),
            "zones":      summary.get("zones", []),
            "ct_names":   summary.get("ct_names", []),
        },
        "correlations": summary.get("correlations", {})
    }

# =============================================================
# Main
# =============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
