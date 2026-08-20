#!/usr/bin/env python3
"""Stage 2: Cell-type deconvolution — Tangram / Cell2Location / Stereoscope"""
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd
import traceback
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Project Path & PyInstaller Support ───────────────────────
PROJECT_ROOT = Path(os.environ.get(
    "GLIO_PROJECT_ROOT",
    sys._MEIPASS if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent.parent.parent
))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── BACKEND_DIR: multi-candidate PyInstaller resolution ──────
if getattr(sys, 'frozen', False):
    _marker = "server.py"                         # marker file to detect correct dir
    _candidates = [
        Path(sys._MEIPASS) / "desktop_app" / "python_backend",
        Path(sys._MEIPASS) / "python_backend",
        Path(sys._MEIPASS),
    ]
    BACKEND_DIR = next((c for c in _candidates if (c / _marker).exists()),
                       Path(sys._MEIPASS))
else:
    BACKEND_DIR = Path(__file__).resolve().parent.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scanpy as sc
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Matplotlib colormaps — compat: 3.5+ uses colormaps, older uses cm
try:
    from matplotlib import colormaps as _cmaps
    def _get_cmap(name): return _cmaps[name]
except (ImportError, AttributeError):
    from matplotlib import cm as _fallback_cm
    def _get_cmap(name): return _fallback_cm.get_cmap(name)

from loguru import logger
import locale_logger
import yaml
from pydantic import BaseModel, Field
from typing import Dict, List

# Pydantic validation schema
class GlobalDeconvConfig(BaseModel):
    cell_markers: Dict[str, List[str]] = Field(default_factory=dict)

# Verbosity = 1: only warnings — keeps stdout clean for JSON progress stream
sc.settings.verbosity = 1

# ── Deconvolution method validation ──────────────────────────
DECONV_METHOD = os.environ.get("GLIO_DECONV_METHOD", "tangram").lower().strip()
_VALID_METHODS = ("tangram", "cell2location", "stereoscope")


def exit_with_error(message):
    logger.error(message)
    print(json.dumps({"stage": "deconvolution", "status": "error", "message": message}), flush=True)
    sys.exit(1)


def report_progress(percent, msg=""):
    payload = {"stage": "deconvolution", "status": "running", "progress": percent}
    if msg:
        payload["message"] = msg
    print(json.dumps(payload), flush=True)


def _stable_softmax(arr_2d: np.ndarray, clip: float = 5.0) -> np.ndarray:
    """Numerically stable row-wise softmax with pre-clipping to prevent extreme dominance."""
    arr = np.clip(arr_2d.astype(float), -clip, clip)
    arr -= arr.max(axis=1, keepdims=True)
    exp = np.exp(arr)
    row_sums = exp.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return exp / row_sums


def compute_morans_i(adata, genes, k_neighbors=6):
    """Moran's I with symmetric, row-normalised weight matrix.
    Vectorised construction — avoids Python loops over spots.
    """
    if "spatial" not in adata.obsm:
        return {g: 0.0 for g in genes}

    from scipy.spatial import cKDTree
    import scipy.sparse as sp

    coords  = adata.obsm["spatial"]
    n_spots = adata.n_obs
    tree    = cKDTree(coords)
    _, idxs = tree.query(coords, k=k_neighbors + 1)   # idxs[:,0] == self

    # Vectorised edge construction (both directions for symmetry)
    i_idx = np.repeat(np.arange(n_spots), k_neighbors)
    j_idx = idxs[:, 1:].flatten()                     # exclude self (col 0)
    rows  = np.concatenate([i_idx, j_idx])
    cols  = np.concatenate([j_idx, i_idx])
    data  = np.full(len(rows), 1.0 / k_neighbors)

    W = sp.csr_matrix((data, (rows, cols)), shape=(n_spots, n_spots))
    row_sums = np.array(W.sum(axis=1)).flatten()
    row_sums[row_sums == 0] = 1.0
    W = sp.diags(1.0 / row_sums) @ W

    moran_dict = {}
    for g in genes:
        if g not in adata.var_names:
            continue
        try:
            col_idx = adata.var_names.get_loc(g)
            e = adata.X[:, col_idx]
        except Exception:
            e = adata[:, g].X
        e = e.toarray().flatten() if hasattr(e, 'toarray') else np.asarray(e).flatten()
        z = e - e.mean()
        denom = float(np.dot(z, z))
        if denom < 1e-12:
            moran_dict[g] = 0.0
        else:
            val = float(np.dot(z, W.dot(z))) / denom
            moran_dict[g] = val if np.isfinite(val) else 0.0
    return moran_dict


# ══════════════════════════════════════════════════════════════
# DECONVOLUTION METHODS
# ══════════════════════════════════════════════════════════════

def _run_tangram(adata_sc, adata_sp, marker_genes, CELL_MARKERS):
    """Tangram — clusters mode. verbose=False prevents epoch logs polluting JSON stream."""
    try:
        import tangram as tg
    except ImportError as e:
        logger.error(f"Tangram bulunamadı: {e}")
        raise   # propagate to main try-except → fallback

    # Work on a copy so tg.pp_adatas doesn't pollute adata_sc.uns for fallback path
    adata_sc_tg = adata_sc.copy()

    logger.info("   Tangram pp_adatas çalıştırılıyor...")
    tg.pp_adatas(adata_sc_tg, adata_sp, genes=marker_genes)
    report_progress(65, "Tangram eşleme başlatıldı...")

    logger.info("   Tangram model eğitimi (num_epochs=500, verbose=False)...")
    ad_map = tg.map_cells_to_space(
        adata_sc_tg, adata_sp,
        mode="clusters",
        cluster_label="cell_type",
        # "uniform" her spot'ta aynı hücre yoğunluğunu varsayar — Visium gibi
        # spot-tabanlı (tek-hücre çözünürlüğünde olmayan) platformlarda
        # Tangram'ın kendi önerisi "rna_count_based"tir; bu, spot başına
        # toplam RNA sayısını yoğunluk vekili olarak kullanır. "uniform"
        # kullanmak, GBM'de klinik olarak en önemli düşük-hücrelilik
        # bölgelerinde (nekrotik/hipoksik çekirdek) hücre-tipi oranlarını
        # sistematik olarak çarpıtır (bkz. denetim raporu bulgusu B-09).
        density_prior="rna_count_based",
        num_epochs=500,
        device="cpu",
        verbose=False,          # prevent epoch logs from polluting progress JSON stream
    )
    logger.info("   Tangram mapping tamamlandı. Projeksiyon yapılıyor...")
    tg.project_cell_annotations(ad_map, adata_sp, annotation="cell_type")
    report_progress(80, "Tangram projeksiyonu tamamlandı")

    if "tangram_ct_pred" not in adata_sp.obsm:
        raise ValueError("tangram_ct_pred adata_sp.obsm içinde bulunamadı — projeksiyon başarısız.")

    ct_prop_raw = adata_sp.obsm["tangram_ct_pred"]
    ct_types    = sorted(adata_sc.obs['cell_type'].unique())

    if not isinstance(ct_prop_raw, pd.DataFrame):
        n_cols = ct_prop_raw.shape[1]
        if len(ct_types) != n_cols:
            logger.warning(f"   Tangram sütun sayısı uyuşmuyor: {n_cols} vs {len(ct_types)}")
            if len(ct_types) > n_cols:
                ct_types = ct_types[:n_cols]
            else:
                ct_types = ct_types + [f"unknown_{i}" for i in range(n_cols - len(ct_types))]
        ct_prop_df = pd.DataFrame(ct_prop_raw, index=adata_sp.obs_names, columns=ct_types)
    else:
        ct_prop_df = ct_prop_raw

    del adata_sc_tg
    return ct_prop_df


def _safe_train_model(model, max_epochs, batch_size=None, train_size=None):
    """
    Safe training helper for scvi-tools (cell2location/stereoscope).
    Adapts device arguments based on scvi-tools/Lightning version support.
    """
    import torch
    # NOT: PyTorch Lightning'de accelerator="gpu" YALNIZCA CUDA anlamına
    # gelir — Apple Silicon'daki MPS backend'i için ayrı ve doğru değer
    # "mps"'dir. Önceki sürüm MPS'i de "gpu" olarak işaretliyordu; bu,
    # Lightning'in MisconfigurationException fırlatmasına (TypeError
    # DEĞİL, bu yüzden aşağıdaki except TypeError bloğu yakalamıyordu)
    # ve Mac'te Cell2Location/Stereoscope eğitiminin sessizce
    # score-based fallback'e düşmesine yol açıyordu (bkz. A-06/D-03).
    has_cuda = torch.cuda.is_available()
    has_mps  = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()
    if has_cuda:
        accelerator = "gpu"
    elif has_mps:
        accelerator = "mps"
    else:
        accelerator = "cpu"

    kwargs = {}
    if batch_size is not None:
        kwargs['batch_size'] = batch_size
    if train_size is not None:
        kwargs['train_size'] = train_size

    try:
        if accelerator in ("gpu", "mps"):
            model.train(max_epochs=max_epochs, accelerator=accelerator, devices=1, **kwargs)
        else:
            model.train(max_epochs=max_epochs, accelerator="cpu", **kwargs)
        return
    except TypeError:
        pass
    except Exception as e_accel:
        # Lightning bazı sürümlerde "mps" için MisconfigurationException
        # fırlatabilir (TypeError değil) — CPU'ya güvenli şekilde düş.
        logger.warning(
            f"   '{accelerator}' hızlandırıcısıyla eğitim başarısız oldu ({e_accel}); CPU'ya düşülüyor."
        )
        try:
            model.train(max_epochs=max_epochs, accelerator="cpu", **kwargs)
            return
        except TypeError:
            pass

    try:
        model.train(max_epochs=max_epochs, use_gpu=has_cuda, **kwargs)
        return
    except TypeError:
        pass

    model.train(max_epochs=max_epochs, **kwargs)


def _safe_export_posterior(model, adata, sample_kwargs):
    """
    Safe posterior export for Cell2Location.
    Adapts sample_kwargs parameters to prevent TypeError on newer versions.
    """
    import torch
    device = "gpu" if torch.cuda.is_available() or (hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()) else "cpu"
    
    try:
        kwargs = sample_kwargs.copy()
        return model.export_posterior(adata, sample_kwargs=kwargs)
    except TypeError as e:
        if 'use_gpu' in str(e) or 'unexpected keyword argument' in str(e):
            kwargs = sample_kwargs.copy()
            kwargs.pop('use_gpu', None)
            try:
                if device == "gpu":
                    kwargs['accelerator'] = 'gpu'
                else:
                    kwargs['accelerator'] = 'cpu'
                return model.export_posterior(adata, sample_kwargs=kwargs)
            except TypeError:
                kwargs.pop('accelerator', None)
                return model.export_posterior(adata, sample_kwargs=kwargs)
        raise e


def _run_cell2location(adata_sc, adata_sp, CELL_MARKERS):
    """Cell2Location Bayesian deconvolution (scvi-tools / cell2location v0.1.x)."""
    try:
        import cell2location
        from cell2location.models import RegressionModel, Cell2location
    except ImportError as e:
        logger.error(f"cell2location bulunamadı: {e}")
        raise   # propagate → fallback in main

    # ── 1. Reference Regression Model ────────────────────────
    logger.info("   Cell2Location: referans model hazırlanıyor...")
    sc_c2l = adata_sc.copy()

    # Ensure raw integer counts exist for NB likelihood
    if sc_c2l.raw is not None:
        sc_c2l.layers['counts'] = sc_c2l.raw.X.copy()
    else:
        sc_c2l.layers['counts'] = sc_c2l.X.copy()

    # Remove mitochondrial genes (recommended in official tutorial)
    mito_mask = sc_c2l.var_names.str.upper().str.startswith("MT-")
    if mito_mask.sum() > 0:
        sc_c2l = sc_c2l[:, ~mito_mask].copy()
        logger.info(f"   {mito_mask.sum()} mitokondriyal gen kaldırıldı.")

    report_progress(55, "Cell2Location referans model eğitimi...")
    RegressionModel.setup_anndata(sc_c2l, layer='counts', labels_key='cell_type', batch_key=None)
    mod_ref = RegressionModel(sc_c2l)
    _safe_train_model(mod_ref, max_epochs=200, batch_size=2500)

    # Export posterior — results stored in sc_c2l.varm
    sc_c2l = _safe_export_posterior(
        mod_ref,
        sc_c2l,
        sample_kwargs={'num_samples': 1000, 'batch_size': 2500, 'use_gpu': False}
    )

    # Gene signature matrix: shape (n_genes, n_cell_types)
    # Official key is 'means_per_cluster_matmul_gene_obsmvar' in .varm
    if 'means_per_cluster_matmul_gene_obsmvar' not in sc_c2l.varm:
        raise KeyError(
            f"Cell2Location referans çıktısı .varm içinde bulunamadı. "
            f"Mevcut anahtarlar: {list(sc_c2l.varm.keys())}"
        )
    inf_aver = sc_c2l.varm['means_per_cluster_matmul_gene_obsmvar'].copy()
    # inf_aver: (n_genes, n_cell_types) — this is the correct cell_state_df format

    # ── 2. Spatial Model ──────────────────────────────────────
    report_progress(65, "Cell2Location mekansal model eğitimi...")
    logger.info("   Cell2Location: mekansal model eğitimi (max_epochs=3000)...")

    # Intersect genes
    common = sorted(set(sc_c2l.var_names) & set(adata_sp.var_names))
    if len(common) < 50:
        raise ValueError(f"Cell2Location için yeterli ortak gen yok: {len(common)}")

    adata_sp_c2l = adata_sp[:, common].copy()
    inf_aver_filtered = inf_aver.loc[common, :]   # align to common genes

    Cell2location.setup_anndata(adata_sp_c2l, batch_key=None)
    mod_sp = Cell2location(
        adata_sp_c2l,
        cell_state_df=inf_aver_filtered,           # (n_genes, n_cell_types) ← correct
        N_cells_per_location=10,
        detection_alpha=20,
    )
    # max_epochs reduced: 3000 is sufficient in practice (default 30000 takes hours)
    _safe_train_model(mod_sp, max_epochs=3000, batch_size=None, train_size=1)
    adata_sp_c2l = _safe_export_posterior(
        mod_sp,
        adata_sp_c2l,
        sample_kwargs={'num_samples': 1000, 'batch_size': adata_sp_c2l.n_obs, 'use_gpu': False}
    )
    report_progress(80, "Cell2Location tamamlandı")

    # Dynamic key lookup: 'q05_cell_abundance_w_sf' may differ across versions
    abund_key = next(
        (k for k in adata_sp_c2l.obsm if 'q05' in k and ('abundance' in k or 'spot' in k)),
        None
    )
    if abund_key is None:
        raise KeyError(
            f"Cell2Location q05 çıktısı obsm içinde bulunamadı. "
            f"Mevcut anahtarlar: {list(adata_sp_c2l.obsm.keys())}"
        )
    abund = adata_sp_c2l.obsm[abund_key]
    abund_arr = abund.values if hasattr(abund, 'values') else np.asarray(abund)

    # Column alignment: model output columns may differ from sorted ct_types
    if hasattr(abund, 'columns'):
        ct_cols = list(abund.columns)
    else:
        ct_types = sorted(adata_sc.obs['cell_type'].unique())
        ct_cols  = ct_types[:abund_arr.shape[1]]
        if len(ct_types) != abund_arr.shape[1]:
            logger.warning(
                f"   Cell2Location sütun sayısı uyuşmuyor ({abund_arr.shape[1]} vs {len(ct_types)}). "
                f"Sütun etiketleri hatalı eşleşebilir."
            )

    ct_prop_df = pd.DataFrame(abund_arr, index=adata_sp.obs_names, columns=ct_cols)

    # ── Posterior belirsizlik (BEDAVA — ek hesaplama gerektirmez) ────────
    # Cell2Location zaten Bayesyen bir posterior örnekliyor ve nokta tahmini
    # olarak q05 (5. persentil, temkinli) kullanıyor — burada zaten üretilmiş
    # olan q95 (95. persentil) karşılığını da okuyup aradaki farkı (kredibilite
    # aralığı genişliği) belirsizlik vekili olarak dışa aktarıyoruz. Tangram/
    # Stereoscope/NNLS'nin aksine bu yöntemler doğası gereği bir posterior
    # üretmez — bu yüzden onlar için belirsizlik yalnızca opsiyonel bootstrap
    # ile (main()'de, GLIO_DECONV_UNCERTAINTY=1) hesaplanabilir.
    uncertainty_df = None
    q95_key = abund_key.replace('q05', 'q95')
    if q95_key in adata_sp_c2l.obsm:
        upper = adata_sp_c2l.obsm[q95_key]
        upper_arr = upper.values if hasattr(upper, 'values') else np.asarray(upper)
        if upper_arr.shape == abund_arr.shape:
            width_arr = np.clip(upper_arr - abund_arr, 0, None)
            uncertainty_df = pd.DataFrame(width_arr, index=adata_sp.obs_names, columns=ct_cols)
        else:
            logger.warning(
                f"   Cell2Location q95 şekli q05 ile uyuşmuyor ({upper_arr.shape} vs {abund_arr.shape}), "
                f"belirsizlik hesaplanamadı."
            )
    else:
        logger.info(f"   Cell2Location q95 anahtarı bulunamadı ('{q95_key}') — belirsizlik hesaplanamadı.")

    # Explicitly clear GPU memory when cell2location completes
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("   CUDA cache cleared.")
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            torch.mps.empty_cache()
            logger.info("   MPS cache cleared.")
    except Exception as gpu_err:
        logger.warning(f"Could not clear PyTorch GPU cache: {gpu_err}")

    return ct_prop_df, uncertainty_df


def _run_stereoscope(adata_sc, adata_sp, CELL_MARKERS):
    """Stereoscope (scvi-tools DESTVI) — NB likelihood based."""
    try:
        from scvi.external import RNAStereoscope, SpatialStereoscope
    except ImportError as e:
        logger.error(f"scvi-tools (Stereoscope) bulunamadı: {e}")
        raise   # propagate → fallback in main

    logger.info("   Stereoscope: scRNA referans modeli eğitimi (max_epochs=300)...")
    report_progress(55, "Stereoscope scRNA model eğitimi...")

    sc_st = adata_sc.copy()
    # Ensure raw counts for NB model
    if sc_st.raw is not None:
        sc_st.X = sc_st.raw.X.copy()

    RNAStereoscope.setup_anndata(sc_st, labels_key='cell_type')
    sc_model = RNAStereoscope(sc_st)
    _safe_train_model(sc_model, max_epochs=300)

    report_progress(65, "Stereoscope mekansal model eğitimi...")
    logger.info("   Stereoscope: mekansal model eğitimi (max_epochs=1500)...")

    common  = sorted(set(adata_sc.var_names) & set(adata_sp.var_names))
    sp_st   = adata_sp[:, common].copy()

    SpatialStereoscope.setup_anndata(sp_st)
    sp_model = SpatialStereoscope.from_rna_model(sp_st, sc_model)
    _safe_train_model(sp_model, max_epochs=1500)    # reduced from 3000

    # get_proportions() may return DataFrame or np.ndarray depending on scvi version
    proportions = sp_model.get_proportions()
    if hasattr(proportions, 'values'):
        prop_arr = proportions.values
        prop_cols = list(proportions.columns) if hasattr(proportions, 'columns') else None
    elif isinstance(proportions, np.ndarray):
        prop_arr = proportions
        prop_cols = None
    else:
        raise ValueError(f"Beklenmeyen get_proportions() tipi: {type(proportions)}")

    report_progress(80, "Stereoscope tamamlandı")

    ct_types = sorted(adata_sc.obs['cell_type'].unique())
    if prop_cols is not None:
        ct_cols = prop_cols
    else:
        ct_cols = ct_types[:prop_arr.shape[1]]
        if len(ct_types) != prop_arr.shape[1]:
            logger.warning(
                f"   Stereoscope sütun sayısı uyuşmuyor ({prop_arr.shape[1]} vs {len(ct_types)}). "
                f"Sütun etiketleri hatalı eşleşebilir."
            )

    ct_prop_df = pd.DataFrame(prop_arr, index=adata_sp.obs_names, columns=ct_cols)
    return ct_prop_df


def _score_based_fallback(adata_sc, adata_sp, CELL_MARKERS):
    """Fallback: Non-Negative Least Squares (NNLS) deconvolution using reference cell profiles.

    NOT: Gen eşleştirmesi büyük/küçük harfe DUYARSIZ yapılır. Gerçek Visium
    verisiyle canlı testte keşfedildi: kaynağa/pipeline'a bağlı olarak
    spatial ve scRNA veri kümeleri farklı gen sembolü büyük/küçük harf
    kurallarıyla gelebiliyor (ör. scRNA'da 'EGFR', spatial'de 'egfr').
    Eski kod tam-eşleşme (`in adata.var_names`) kullanıyordu — bu durumda
    SIFIR ortak gen bulunup, bu SON ÇARE fallback bile başarısız olup
    tüm pipeline'ı `exit_with_error` ile çökertebiliyordu.
    """
    logger.warning("   Fallback: NNLS dekonvolüsyon başlatılıyor...")
    from scipy.optimize import nnls
    import scipy.sparse as sp

    sc_upper_map = {g.upper(): g for g in adata_sc.var_names}
    sp_upper_map = {g.upper(): g for g in adata_sp.var_names}

    # 1. Identify valid marker genes present in both scRNA and Spatial datasets
    all_markers = set()
    for ct, markers in CELL_MARKERS.items():
        all_markers.update(markers)

    # valid_genes: kanonik (config.yaml'daki) büyük harfli isim; ayrıca her
    # veri kümesindeki GERÇEK (orijinal büyük/küçük harfli) karşılığını da
    # tutuyoruz çünkü sc ve sp'nin kendi casing'i farklı olabilir.
    valid_genes = [g for g in all_markers if g.upper() in sc_upper_map and g.upper() in sp_upper_map]
    valid_genes_sc = [sc_upper_map[g.upper()] for g in valid_genes]
    valid_genes_sp = [sp_upper_map[g.upper()] for g in valid_genes]

    if len(valid_genes) < 5:
        logger.warning("   NNLS için yeterli ortak marker gen bulunamadı, basit score-based fallback uygulanıyor...")
        ct_proportions = {}
        for cell_type, markers in CELL_MARKERS.items():
            valid = [sp_upper_map[m.upper()] for m in markers if m.upper() in sp_upper_map]
            if len(valid) >= 1:
                sc.tl.score_genes(adata_sp, valid, score_name=f"score_{cell_type}")
                ct_proportions[cell_type] = adata_sp.obs[f"score_{cell_type}"].values
        if not ct_proportions:
            exit_with_error("Yeterli marker gen bulunamadı.")
        scored_cols = list(ct_proportions.keys())
        raw_arr = np.column_stack([ct_proportions[c] for c in scored_cols])
        softmax_arr = _stable_softmax(raw_arr, clip=5.0)
        return pd.DataFrame(softmax_arr, columns=scored_cols, index=adata_sp.obs_names)

    # 2. Build the signature matrix B (Genes x CellTypes)
    ct_names = list(CELL_MARKERS.keys())

    if "cell_type" not in adata_sc.obs.columns:
        cell_type_scores = {}
        for cell_type, markers in CELL_MARKERS.items():
            valid_markers = [sc_upper_map[m.upper()] for m in markers if m.upper() in sc_upper_map]
            if len(valid_markers) >= 3:
                sc.tl.score_genes(adata_sc, valid_markers, score_name=f"score_{cell_type}")
                cell_type_scores[cell_type] = f"score_{cell_type}"
        score_cols = list(cell_type_scores.values())
        if score_cols:
            score_array = adata_sc.obs[score_cols].values
            max_indices = score_array.argmax(axis=1)
            adata_sc.obs["cell_type"] = [ct_names[i] for i in max_indices]
        else:
            adata_sc.obs["cell_type"] = "unknown"

    B_list = []
    active_cts = []

    X_ref = adata_sc[:, valid_genes_sc].X
    if sp.issparse(X_ref):
        X_ref = X_ref.toarray()
    else:
        X_ref = np.asarray(X_ref)

    valid_genes_upper = [g.upper() for g in valid_genes]
    for ct in ct_names:
        mask = (adata_sc.obs["cell_type"] == ct)
        if mask.sum() > 0:
            avg_profile = X_ref[mask].mean(axis=0)
            B_list.append(avg_profile)
            active_cts.append(ct)
        else:
            avg_profile = np.zeros(len(valid_genes))
            ct_markers_upper = {m.upper() for m in CELL_MARKERS.get(ct, [])}
            for i, g_upper in enumerate(valid_genes_upper):
                if g_upper in ct_markers_upper:
                    avg_profile[i] = 1.0
            B_list.append(avg_profile)
            active_cts.append(ct)

    B = np.column_stack(B_list)

    # 3. Solve NNLS for each spot in spatial data
    X_sp = adata_sp[:, valid_genes_sp].X
    if sp.issparse(X_sp):
        X_sp = X_sp.toarray()
    else:
        X_sp = np.asarray(X_sp)
        
    n_spots = X_sp.shape[0]
    prop_arr = np.zeros((n_spots, len(active_cts)))
    
    for i in range(n_spots):
        y = X_sp[i]
        coefs, _ = nnls(B, y)
        coef_sum = coefs.sum()
        if coef_sum > 0:
            prop_arr[i] = coefs / coef_sum
        else:
            prop_arr[i] = 1.0 / len(active_cts)
            
    return pd.DataFrame(prop_arr, columns=active_cts, index=adata_sp.obs_names)




class DeconvolverRegistry:
    def __init__(self):
        self._methods = {}

    def register(self, name, handler):
        self._methods[name.lower()] = handler

    def run(self, name, *args, **kwargs):
        name_lower = name.lower()
        if name_lower not in self._methods:
            raise ValueError(f"Deconvolution method '{name}' is not registered.")
        return self._methods[name_lower](*args, **kwargs)

deconv_registry = DeconvolverRegistry()
deconv_registry.register('tangram', lambda adata_sc, adata_sp, marker_genes, CELL_MARKERS: _run_tangram(adata_sc, adata_sp, marker_genes, CELL_MARKERS))
deconv_registry.register('cell2location', lambda adata_sc, adata_sp, marker_genes, CELL_MARKERS: _run_cell2location(adata_sc, adata_sp, CELL_MARKERS))
# _run_cell2location (ct_prop_df, uncertainty_df) tuple'ı döner — diğer üç
# yöntem yalnızca ct_prop_df döner; main() bunu isinstance kontrolüyle ayırt eder.
deconv_registry.register('stereoscope', lambda adata_sc, adata_sp, marker_genes, CELL_MARKERS: _run_stereoscope(adata_sc, adata_sp, CELL_MARKERS))


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
    # `DECONV_METHOD` bir fallback tetiklenirse aşağıda güncellenir
    # (bkz. A-06 düzeltmesi) — bu yüzden modül-seviyesi global'e
    # açıkça bağlanıyoruz.
    global DECONV_METHOD
    # ── Validate method ──────────────────────────────────────
    if DECONV_METHOD not in _VALID_METHODS:
        exit_with_error(
            f"Geçersiz GLIO_DECONV_METHOD='{DECONV_METHOD}'. "
            f"Geçerli değerler: {', '.join(_VALID_METHODS)}"
        )

    try:
        OUTPUT_DIR = Path(os.environ["GLIO_OUTPUT_DIR"])
    except KeyError as ke:
        exit_with_error(f"Eksik çevre değişkeni: {ke}")

    PATIENT_ID = os.environ.get("GLIO_PATIENT_ID", "Patient_A")
    report_progress(5)

    # ── Load config markers ─────────────────────────────────
    import argparse
    parser = argparse.ArgumentParser(description="Stage 2: Deconvolution")
    parser.add_argument("--config_path", type=str, default=None, help="Path to config.yaml")
    args, unknown = parser.parse_known_args()

    config_path_str = args.config_path or os.environ.get("GLIO_CONFIG_PATH")
    if config_path_str:
        config_path = Path(config_path_str)
    else:
        # Fallback search paths
        candidates = [
            PROJECT_ROOT / "configs" / "config.yaml",
            PROJECT_ROOT / "desktop_app" / "configs" / "config.yaml",
            Path("configs/config.yaml"),
            Path("desktop_app/configs/config.yaml")
        ]
        config_path = next((c for c in candidates if c.exists()), None)

    CELL_MARKERS = {}
    config = GlobalDeconvConfig()
    _cell_marker_source = "hardcoded_fallback"
    if config_path and config_path.exists():
        raw_cfg = None
        try:
            with open(config_path) as f:
                raw_cfg = yaml.safe_load(f) or {}
        except Exception as e_yaml:
            logger.error(f"   config.yaml PARSE EDİLEMEDİ ({e_yaml}) — cell_markers dahil TÜM config bölümleri "
                         f"kullanılamıyor, sabit kodlanmış 8 hücre-tipi fallback panele düşülüyor.")

        if raw_cfg is not None:
            # cell_markers'ı, dosyanın geri kalanındaki (preprocessing, QC vb.)
            # alakasız bir yazım hatasının tüm marker panelini sessizce
            # düşürmesini önlemek için AYRI olarak doğrula (bkz. A-08).
            raw_markers = raw_cfg.get("cell_markers")
            if raw_markers:
                try:
                    config = GlobalDeconvConfig(cell_markers=raw_markers)
                    CELL_MARKERS = config.cell_markers
                    _cell_marker_source = str(config_path)
                    logger.info(f"   cell_markers config.yaml'dan yüklendi ve doğrulandı: {config_path} "
                                f"({len(CELL_MARKERS)} hücre tipi)")
                except Exception as e_cm:
                    logger.error(f"   config.yaml içindeki cell_markers bölümü doğrulanamadı ({e_cm}) — "
                                 f"sabit kodlanmış 8 hücre-tipi fallback panele düşülüyor.")
            else:
                logger.warning("   config.yaml'da 'cell_markers' bölümü bulunamadı — "
                                "sabit kodlanmış 8 hücre-tipi fallback panele düşülüyor.")
    else:
        logger.warning(f"   Config dosyası bulunamadı ({config_path}), sabit kodlanmış 8 hücre-tipi fallback panele düşülüyor.")

    if not CELL_MARKERS:
        CELL_MARKERS = {
            "Tumor_MES": ["CHI3L1", "CD44", "VIM"],
            "Tumor_OPC": ["PDGFRA", "OLIG1", "OLIG2"],
            "Tumor_AC":  ["GFAP", "ALDOC", "S100B"],
            "TAM_Macrophage": ["CD68", "CD163", "AIF1", "CD14"],
            "TAM_Microglia":  ["CX3CR1", "P2RY12", "TMEM119"],
            "T_Cell":         ["CD3D", "CD3E", "CD8A", "CD4"],
            "Endothelial":    ["PECAM1", "VWF", "CD34"],
            "Oligodendrocyte":["MBP", "PLP1", "MAG"]
        }
        _cell_marker_source = "hardcoded_fallback"

    # ── Output dir ───────────────────────────────────────────
    deconv_out = OUTPUT_DIR / "deconvolution"
    deconv_out.mkdir(parents=True, exist_ok=True)

    # ── Load preprocessed data ───────────────────────────────
    scrna_path   = OUTPUT_DIR / "preprocessing" / "scRNA"   / "scrna_preprocessed.h5ad"
    spatial_path = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_preprocessed.h5ad"

    logger.info("📂 Veri yükleniyor...")
    try:
        adata_sc = sc.read_h5ad(scrna_path)
        adata_sp = sc.read_h5ad(spatial_path)
    except Exception as e_load:
        exit_with_error(f"Ön işlenmiş veriler yüklenemedi: {e_load}")

    logger.info(f"   scRNA: {adata_sc.shape}, Spatial: {adata_sp.shape}")
    report_progress(15)

    # ── Cell type annotation (scRNA) ─────────────────────────
    # DÜZELTME (2026-08-20): `m in adata_sc.var_names` büyük/küçük harfe
    # duyarlıydı — `_score_based_fallback`'te canlı hasta verisiyle bulunan
    # ve düzeltilen AYNI hata sınıfı burada da vardı. config.yaml'daki
    # markerlar (ör. "CLEC9A") ile scRNA referansının kendi casing'i
    # farklıysa marker sessizce "eksik" sayılıp o hücre tipi tamamen
    # atlanıyordu — özellikle az sayıda markeri olan ince alt-tipler
    # (cDC1/cDC2/pDC/moDC, Treg, NK) bu yüzden neredeyse hiç tanınmıyordu.
    logger.info("🏷️ Hücre tipi anotasyonu...")
    _sc_upper_map_ct = {g.upper(): g for g in adata_sc.var_names}
    cell_type_scores = {}
    for cell_type, markers in CELL_MARKERS.items():
        valid_markers = [_sc_upper_map_ct[m.upper()] for m in markers if m.upper() in _sc_upper_map_ct]
        if len(valid_markers) < 3:          # Hard threshold
            logger.warning(f"   {cell_type}: insufficient markers ({len(valid_markers)}), skipping.")
            continue
        sc.tl.score_genes(adata_sc, valid_markers, score_name=f"score_{cell_type}")
        cell_type_scores[cell_type] = f"score_{cell_type}"

    score_cols = list(cell_type_scores.values())
    ct_names   = list(cell_type_scores.keys())

    if score_cols:
        score_array   = adata_sc.obs[score_cols].values
        max_indices   = score_array.argmax(axis=1)
        all_zero_mask = (score_array == 0).all(axis=1)     # detect cells with no signal

        assignments = [ct_names[i] for i in max_indices]
        adata_sc.obs["cell_type"] = [
            "unknown" if all_zero_mask[k] else assignments[k]
            for k in range(len(assignments))
        ]

        zero_count = int(all_zero_mask.sum())
        if zero_count > 0:
            logger.warning(f"   {zero_count} hücre hiçbir markera skor alamadı → 'unknown'.")
    else:
        adata_sc.obs["cell_type"] = "unknown"

    logger.info(f"   Hücre tipleri: {adata_sc.obs['cell_type'].value_counts().to_dict()}")
    report_progress(25)

    # ── Marker Gene Extraction ───────────────────────────────
    logger.info("🔬 Marker gen çıkarımı (rank_genes_groups)...")
    adata_sc_copy = adata_sc.copy()

    if adata_sc_copy.raw is None:
        logger.info("   raw layer bulunamadı, normalleştirme uygulanıyor (copy)...")
        sc.pp.normalize_total(adata_sc_copy, target_sum=1e4)
        sc.pp.log1p(adata_sc_copy)
        adata_sc_copy.layers['log1p_counts'] = adata_sc_copy.X.copy()

    sc.tl.rank_genes_groups(adata_sc_copy, groupby='cell_type', method='wilcoxon', use_raw=False)

    marker_genes = set()
    for ct in adata_sc_copy.obs['cell_type'].unique():
        if ct == "unknown":
            continue
        try:
            genes_df = sc.get.rank_genes_groups_df(adata_sc_copy, group=ct, key='rank_genes_groups')
            genes_df = genes_df[
                (genes_df['logfoldchanges'] > 0.5) &
                (genes_df['pvals_adj'] < 0.05)
            ]
            marker_genes.update(genes_df.head(80)['names'].tolist())
        except Exception as exc:
            logger.warning(f"   Marker gen çıkarımı başarısız (grup={ct}): {exc}")

    del adata_sc_copy   # free RAM before heavy deconvolution runs

    if len(marker_genes) < 100 and 'highly_variable' in adata_sc.var.columns:
        hvg = set(adata_sc.var_names[adata_sc.var['highly_variable']])
        marker_genes = sorted(list(set(marker_genes) | hvg))[:500]

    # Enforce clinical marker gene inclusion
    clinical_markers = set()
    for ct_markers in CELL_MARKERS.values():
        for marker in ct_markers:
            for name in [marker, marker.upper(), marker.lower(), marker.capitalize()]:
                if name in adata_sc.var_names and name in adata_sp.var_names:
                    clinical_markers.add(name)
                    break

    logger.info(f"   Klinik markerlar (her iki veri kümesinde): {len(clinical_markers)}")
    marker_genes = sorted(list(set(marker_genes) | clinical_markers))
    marker_genes = [g for g in marker_genes if g in adata_sc.var_names and g in adata_sp.var_names]
    report_progress(45)

    # ── Moran's I Spatial Autocorrelation Filter ─────────────
    logger.info(f"   {len(marker_genes)} gen için Moran's I hesaplanıyor (vektörize)...")
    try:
        moran_scores = compute_morans_i(adata_sp, marker_genes, k_neighbors=6)
        marker_genes = [g for g, s in moran_scores.items() if s >= 0.1 or g in clinical_markers]
        logger.info(f"   Moran's I filtresi: {len(marker_genes)} gen korundu.")
    except Exception as e_moran:
        logger.warning(f"   Moran's I başarısız ({e_moran}), tüm markerlar kullanılacak.")

    logger.info(f"   Final marker gen sayısı: {len(marker_genes)}")
    if len(marker_genes) < 10:
        exit_with_error(f"Dekonvolüsyon için yeterli ortak gen yok (mevcut: {len(marker_genes)}).")

    report_progress(60)

    # ── RUN SELECTED DECONVOLUTION METHOD ────────────────────
    logger.info(f"🔬 Dekonvolüsyon yöntemi: {DECONV_METHOD.upper()}")
    
    _requested_method = DECONV_METHOD
    _fallback_used = False
    uncertainty_df = None   # yalnızca cell2location (bedava) veya bootstrap (opt-in) ile dolar
    try:
        result = deconv_registry.run(DECONV_METHOD, adata_sc, adata_sp, marker_genes, CELL_MARKERS)
        if isinstance(result, tuple):
            ct_prop_df, uncertainty_df = result
        else:
            ct_prop_df = result
    except Exception as e:
        logger.warning(f"   {DECONV_METHOD.upper()} yöntemi başarısız oldu ({e}). NNLS/Score-based fallback devrede...")
        ct_prop_df = _score_based_fallback(adata_sc, adata_sp, CELL_MARKERS)
        _fallback_used = True
        # DECONV_METHOD burada BİLEREK güncelleniyor — aşağıdaki summary
        # JSON'u ve dolayısıyla klinik rapor, gerçekte hangi yöntemin
        # kullanıldığını (Tangram DEĞİL, basit skor-tabanlı bir fallback)
        # doğru şekilde yansıtmalı (bkz. denetim raporu bulgusu A-06).
        DECONV_METHOD = "score_based_fallback"

    # Guarantee ct_prop_df is always a proper DataFrame
    if not isinstance(ct_prop_df, pd.DataFrame):
        ct_prop_df = pd.DataFrame(
            ct_prop_df if hasattr(ct_prop_df, '__array__') else np.asarray(ct_prop_df),
            index=adata_sp.obs_names
        )

    # ── [GELİŞTİRME] Bootstrap-tabanlı belirsizlik (opt-in) ──────────────
    # Cell2location dışındaki yöntemler (Tangram/Stereoscope/NNLS) doğası
    # gereği tek bir nokta tahmini üretir, bir posterior sağlamaz. Marker gen
    # panelinin rastgele bir alt-kümesiyle N kez yeniden çalıştırıp sonuçlar
    # arasındaki varyansı bir belirsizlik vekili olarak kullanabiliriz — ama
    # bu N kat ekstra hesaplama maliyeti demektir (özellikle Tangram için).
    # Bu yüzden VARSAYILAN OLARAK KAPALI; kullanıcı açıkça isterse devreye
    # girer (GLIO_DECONV_UNCERTAINTY=1). Fallback zaten kullanıldıysa veya
    # cell2location zaten bedava bir posterior verdiyse atlanır.
    _uncertainty_enabled = os.environ.get("GLIO_DECONV_UNCERTAINTY", "0") == "1"
    if _uncertainty_enabled and not _fallback_used and uncertainty_df is None:
        _boot_n = int(os.environ.get("GLIO_DECONV_BOOTSTRAP_N", "5"))
        logger.info(f"   Bootstrap belirsizlik tahmini başlatılıyor ({_boot_n} tekrar, marker geninin ~%85'i)...")
        rng = np.random.default_rng(42)
        boot_runs = []
        for _b in range(_boot_n):
            n_sub = max(10, int(len(marker_genes) * 0.85))
            sub_genes = list(rng.choice(marker_genes, size=n_sub, replace=False))
            try:
                boot_result = deconv_registry.run(DECONV_METHOD, adata_sc, adata_sp, sub_genes, CELL_MARKERS)
                boot_df = boot_result[0] if isinstance(boot_result, tuple) else boot_result
                boot_df = boot_df.clip(lower=0)
                boot_sums = boot_df.sum(axis=1).replace(0, np.nan)
                boot_df = boot_df.div(boot_sums, axis=0).fillna(0)
                boot_runs.append(boot_df.reindex(index=adata_sp.obs_names, columns=ct_prop_df.columns, fill_value=0))
            except Exception as e_boot:
                logger.warning(f"   Bootstrap tekrarı {_b+1}/{_boot_n} başarısız oldu, atlanıyor: {e_boot}")
        if len(boot_runs) >= 2:
            stacked = np.stack([df.values for df in boot_runs], axis=0)   # (N, spots, celltypes)
            uncertainty_df = pd.DataFrame(stacked.std(axis=0), index=adata_sp.obs_names, columns=ct_prop_df.columns)
            logger.info(f"   Bootstrap belirsizlik tahmini tamamlandı ({len(boot_runs)}/{_boot_n} tekrar başarılı).")
        else:
            logger.warning("   Bootstrap belirsizlik tahmini için yeterli başarılı tekrar yok, atlanıyor.")

    # ── Normalize & Clip Proportions ─────────────────────────
    ct_prop_df = ct_prop_df.clip(lower=0)
    row_sums   = ct_prop_df.sum(axis=1).replace(0, np.nan)
    # Dekonvolüsyonun tamamen başarısız olduğu (tüm oranlar sıfır) spot'ları
    # işaretle — bunlar aşağıda `idxmax` ile keyfi bir "baskın hücre tipi"
    # almak yerine "Undetermined" olarak işaretlenecek (bkz. C-06).
    _degenerate_spot_mask = row_sums.isna().values
    ct_prop_df = ct_prop_df.div(row_sums, axis=0).fillna(0)

    adata_sp.obsm["celltype_proportions"] = ct_prop_df
    report_progress(85)

    # [GELİŞTİRME] Çapraz-yöntem güven kontrolü. Sofistike yöntem (Tangram/
    # Cell2location/Stereoscope) başarılı olduğunda, sonucunu hızlı ve
    # BAĞIMSIZ bir ikinci tahminle (NNLS skor-tabanlı) karşılaştırıyoruz.
    # Bu bir "doğrulama" değil, iki farklı yaklaşımın ne kadar örtüştüğünü
    # gösteren ucuz bir güvenilirlik sinyalidir — düşük örtüşme, sonuçların
    # daha temkinli yorumlanması gerektiğine işaret eder. Fallback zaten
    # NNLS kullandıysa (kendisiyle karşılaştırma anlamsız olur) atlanır.
    cross_method_agreement = None
    _sc_upper_set = {g.upper() for g in adata_sc.var_names}
    _sp_upper_set = {g.upper() for g in adata_sp.var_names}
    _cross_check_genes = {g for markers in CELL_MARKERS.values() for g in markers}
    # Büyük/küçük harfe duyarsız eşleşme — bkz. _score_based_fallback'teki not.
    _cross_check_genes = [g for g in _cross_check_genes if g.upper() in _sc_upper_set and g.upper() in _sp_upper_set]
    if not _fallback_used and len(_cross_check_genes) >= 5:
        try:
            secondary_df = _score_based_fallback(adata_sc.copy(), adata_sp.copy(), CELL_MARKERS)
            secondary_df = secondary_df.clip(lower=0)
            _sec_sums = secondary_df.sum(axis=1).replace(0, np.nan)
            secondary_df = secondary_df.div(_sec_sums, axis=0).fillna(0)
            common_cols = [c for c in ct_prop_df.columns if c in secondary_df.columns]
            if len(common_cols) >= 2:
                corrs = []
                for c in common_cols:
                    a = ct_prop_df[c].values
                    b = secondary_df.reindex(ct_prop_df.index)[c].values
                    if np.std(a) > 1e-8 and np.std(b) > 1e-8:
                        corrs.append(float(np.corrcoef(a, b)[0, 1]))
                if corrs:
                    cross_method_agreement = round(float(np.mean(corrs)), 4)
                    logger.info(f"   Çapraz-yöntem güven kontrolü ({DECONV_METHOD.upper()} vs NNLS): "
                                f"ortalama korelasyon={cross_method_agreement:.3f} ({len(corrs)} ortak hücre tipi)")
        except SystemExit:
            # `_score_based_fallback` normalde SON ÇARE bir yöntem olduğu için
            # yetersiz ortak marker geni bulduğunda `exit_with_error()` ile
            # tüm işlemi sonlandırır (sys.exit). Burada onu yalnızca İKİNCİL,
            # opsiyonel bir çapraz-kontrol olarak çağırıyoruz — bu asla ana
            # pipeline'ı öldürmemeli, sadece kontrolü atlamalı.
            logger.warning("   Çapraz-yöntem güven kontrolü atlandı (fallback yöntemi için yeterli ortak gen yok).")
        except Exception as e_cross:
            logger.warning(f"   Çapraz-yöntem güven kontrolü hesaplanamadı: {e_cross}")

    # ── Hoyer Sparsity ────────────────────────────────────────
    N_types = ct_prop_df.shape[1]
    if N_types > 1:
        props    = ct_prop_df.values
        l1       = props.sum(axis=1)
        l2       = np.sqrt((props ** 2).sum(axis=1))
        l2_safe  = np.clip(l2, 1e-10, None)
        sparsity = np.clip((np.sqrt(N_types) - l1 / l2_safe) / (np.sqrt(N_types) - 1), 0.0, 1.0)
    else:
        sparsity = np.zeros(ct_prop_df.shape[0])

    adata_sp.obs['deconv_sparsity'] = sparsity
    logger.info(f"   Hoyer Sparsity — Mean: {sparsity.mean():.3f}")

    # ── Normalized Entropy ────────────────────────────────────
    n_types    = ct_prop_df.shape[1]
    safe_props = ct_prop_df.where(ct_prop_df > 0)
    raw_entropy = -(safe_props * np.log2(safe_props)).fillna(0).sum(axis=1)
    max_entropy = np.log2(n_types) if n_types > 1 else 1.0
    entropy     = raw_entropy / max_entropy

    adata_sp.obs['deconv_entropy']    = entropy.values
    adata_sp.obs['deconv_confidence'] = ct_prop_df.max(axis=1).values

    # ── Dekonvolüsyon belirsizliği (varsa) ────────────────────
    # Cell2location için bedava (q95-q05 kredibilite aralığı genişliği);
    # diğer yöntemler için yalnızca GLIO_DECONV_UNCERTAINTY=1 ile bootstrap
    # üzerinden hesaplanır. İkisi de yoksa bu alan tamamen atlanır — sahte
    # bir belirsizlik değeri (ör. sabit 0) üretmek yerine.
    avg_deconv_uncertainty = None
    per_celltype_uncertainty = None
    if uncertainty_df is not None:
        uncertainty_df = uncertainty_df.reindex(columns=ct_prop_df.columns, fill_value=0.0)
        adata_sp.obs['deconv_uncertainty'] = uncertainty_df.mean(axis=1).values
        avg_deconv_uncertainty = float(uncertainty_df.values.mean())
        per_celltype_uncertainty = {ct: float(uncertainty_df[ct].mean()) for ct in uncertainty_df.columns}
        logger.info(f"   Dekonvolüsyon belirsizliği — Ortalama: {avg_deconv_uncertainty:.4f}")

    logger.info(f"   Dekonvolüsyon tamamlandı — Mean Entropy: {entropy.mean():.3f}")
    report_progress(90)

    # ── Save ─────────────────────────────────────────────────
    deconv_h5ad = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    adata_sp.write_h5ad(deconv_h5ad)
    logger.info(f"   ✅ Kaydedildi: {deconv_h5ad}")

    # ── Figures ──────────────────────────────────────────────
    logger.info("🎨 Figürler oluşturuluyor...")
    dom_ct = ct_prop_df.idxmax(axis=1).astype(object)
    if _degenerate_spot_mask.any():
        n_deg = int(_degenerate_spot_mask.sum())
        logger.warning(f"   {n_deg} spot'ta dekonvolüsyon tüm hücre tiplerinde sıfır oran üretti "
                        f"— bu spot'lar keyfi bir baskın hücre tipi yerine 'Undetermined' olarak işaretlendi.")
        dom_ct.values[_degenerate_spot_mask] = "Undetermined"
    adata_sp.obs["dominant_celltype"] = dom_ct.values

    if "spatial" in adata_sp.obsm:
        coords     = adata_sp.obsm["spatial"]
        unique_cts = dom_ct.unique()

        # tab20 safe: if >20 cell types, use tab20b as extension
        n_colors = max(len(unique_cts), 1)
        if n_colors <= 20:
            cmap   = _get_cmap('tab20')
            colors = cmap(np.linspace(0, 1, n_colors))
        else:
            cmap1  = _get_cmap('tab20')
            cmap2  = _get_cmap('tab20b')
            colors = np.vstack([
                cmap1(np.linspace(0, 1, 20)),
                cmap2(np.linspace(0, 1, n_colors - 20))
            ])

        ct_color = {ct: colors[i] for i, ct in enumerate(unique_cts)}

        fig, ax = plt.subplots(figsize=(12, 8), facecolor='#0d1117')
        for ct in unique_cts:
            mask = dom_ct == ct
            ax.scatter(coords[mask, 0], coords[mask, 1], c=[ct_color[ct]], label=ct, s=35, alpha=0.8)
        ax.set_title(f"Dominant Hücre Tipi — {PATIENT_ID} [{DECONV_METHOD.upper()}]",
                     color='white', fontsize=14)
        ax.set_facecolor('#0d1117')
        ax.tick_params(colors='white')
        ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), fontsize=8,
                  facecolor='#1a1a2e', labelcolor='white', markerscale=1.5, ncol=1)
        plt.tight_layout()
        fig.savefig(deconv_out / "fig2_dominant_celltype_map.png", dpi=150,
                    bbox_inches='tight', facecolor='#0d1117')
        plt.close()

        # Coarse TME composition bar chart
        coarse_groups = {"Tumor": [], "Myeloid": [], "T_Cell": [], "Stromal": []}
        for ct in ct_prop_df.columns:
            ct_lower = ct.lower()
            if any(k in ct_lower for k in ["tumor", "opc", "_ac", "_mes", "tumor_mes", "tumor_ac"]):
                coarse_groups["Tumor"].append(ct)
            elif any(k in ct_lower for k in ["tam", "macrophage", "microglia", "myeloid"]):
                coarse_groups["Myeloid"].append(ct)
            elif any(k in ct_lower for k in ["t_cell", "tcell", "lymphocyte", "cd3", "cd8", "cd4"]):
                coarse_groups["T_Cell"].append(ct)
            else:
                coarse_groups["Stromal"].append(ct)

        coarse_means = {g: ct_prop_df[cols].sum(axis=1).mean() if cols else 0.0
                        for g, cols in coarse_groups.items()}
        bar_colors = _get_cmap('Set2')(np.linspace(0, 1, len(coarse_groups)))

        fig, ax = plt.subplots(figsize=(8, 5), facecolor='#0d1117')
        ax.bar(coarse_means.keys(), coarse_means.values(), color=bar_colors)
        ax.set_title(f"TME Kompozisyon — {PATIENT_ID}", color='white')
        ax.set_facecolor('#0d1117')
        ax.tick_params(colors='white')
        ax.set_ylabel("Ortalama Oran", color='white')
        plt.tight_layout()
        fig.savefig(deconv_out / "fig3_tme_composition.png", dpi=150,
                    bbox_inches='tight', facecolor='#0d1117')
        plt.close()

    report_progress(95)

    # ── Summary JSON ─────────────────────────────────────────
    ct_mean_props = {ct: float(ct_prop_df[ct].mean()) for ct in ct_prop_df.columns}
    summary = {
        "deconv_method":    DECONV_METHOD,
        "requested_method": _requested_method,
        "fallback_used":    _fallback_used,
        "cell_marker_source": _cell_marker_source,
        "cross_method_agreement": cross_method_agreement,
        "n_cell_marker_types": len(CELL_MARKERS),
        "n_spots":          int(adata_sp.n_obs),
        "n_cell_types":     len(ct_prop_df.columns),
        "cell_type_names":  list(ct_prop_df.columns),
        "mean_proportions": ct_mean_props,
        "avg_confidence":   float(adata_sp.obs['deconv_confidence'].mean()),
        "avg_entropy":      float(adata_sp.obs['deconv_entropy'].mean()),
        "avg_sparsity":     float(adata_sp.obs['deconv_sparsity'].mean()),
        "avg_deconv_uncertainty": avg_deconv_uncertainty,
        "deconv_uncertainty_source": (
            "cell2location_posterior" if (DECONV_METHOD == "cell2location" and avg_deconv_uncertainty is not None)
            else "bootstrap" if avg_deconv_uncertainty is not None
            else None
        ),
        "per_celltype_uncertainty": per_celltype_uncertainty,
        "dominant_frequencies": {str(k): int(v) for k, v in dom_ct.value_counts().items()},
        "patient_id": PATIENT_ID,
        "status": "success"
    }

    (deconv_out / "deconvolution_summary.json").write_text(
        json.dumps(summary, indent=2), encoding='utf-8'
    )
    logger.info(f"✅ Stage 2 tamamlandı ({DECONV_METHOD.upper()})")
    report_progress(100)
    print(json.dumps({"stage": "deconvolution", "status": "done", "method": DECONV_METHOD}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        exit_with_error(f"Beklenmeyen hata: {str(e)}\n{traceback.format_exc()}")
