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
import yaml

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
        density_prior="uniform",
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
    device = "gpu" if torch.cuda.is_available() or (hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()) else "cpu"
    
    kwargs = {}
    if batch_size is not None:
        kwargs['batch_size'] = batch_size
    if train_size is not None:
        kwargs['train_size'] = train_size
        
    try:
        if device == "gpu":
            model.train(max_epochs=max_epochs, accelerator="gpu", devices=1, **kwargs)
        else:
            model.train(max_epochs=max_epochs, accelerator="cpu", **kwargs)
        return
    except TypeError:
        pass

    try:
        model.train(max_epochs=max_epochs, use_gpu=(device == "gpu"), **kwargs)
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
    return ct_prop_df


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


def _score_based_fallback(adata_sp, CELL_MARKERS):
    """Fallback: stable softmax (with pre-clip) over sc.tl.score_genes scores."""
    logger.warning("   Fallback: score_genes bazlı softmax dekonvolüsyon...")
    ct_proportions = {}
    for cell_type, markers in CELL_MARKERS.items():
        valid = [m for m in markers if m in adata_sp.var_names]
        if len(valid) < 3:
            logger.warning(f"   {cell_type}: insufficient markers ({len(valid)}), skipping.")
            continue
        sc.tl.score_genes(adata_sp, valid, score_name=f"score_{cell_type}")
        ct_proportions[cell_type] = adata_sp.obs[f"score_{cell_type}"].values

    if not ct_proportions:
        exit_with_error("Fallback dekonvolüsyon için yeterli marker gen bulunamadı.")

    scored_cols = list(ct_proportions.keys())
    raw_arr     = np.column_stack([ct_proportions[c] for c in scored_cols])
    softmax_arr = _stable_softmax(raw_arr, clip=5.0)
    return pd.DataFrame(softmax_arr, columns=scored_cols, index=adata_sp.obs_names)


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
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
    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    CELL_MARKERS = {}
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        CELL_MARKERS = cfg.get("cell_markers", {})
        logger.info(f"   Config yüklendi: {config_path}")
    except Exception as e:
        logger.warning(f"   Config yüklenemedi ({e}). Varsayılan markerlar kullanılacak.")
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
    logger.info("🏷️ Hücre tipi anotasyonu...")
    cell_type_scores = {}
    for cell_type, markers in CELL_MARKERS.items():
        valid_markers = [m for m in markers if m in adata_sc.var_names]
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
    ct_prop_df = None

    if DECONV_METHOD == "cell2location":
        try:
            ct_prop_df = _run_cell2location(adata_sc, adata_sp, CELL_MARKERS)
        except Exception as e:
            logger.warning(f"   Cell2Location başarısız ({e}). Score-based fallback devrede...")
            ct_prop_df = _score_based_fallback(adata_sp, CELL_MARKERS)

    elif DECONV_METHOD == "stereoscope":
        try:
            ct_prop_df = _run_stereoscope(adata_sc, adata_sp, CELL_MARKERS)
        except Exception as e:
            logger.warning(f"   Stereoscope başarısız ({e}). Score-based fallback devrede...")
            ct_prop_df = _score_based_fallback(adata_sp, CELL_MARKERS)

    else:  # tangram (default)
        try:
            ct_prop_df = _run_tangram(adata_sc, adata_sp, marker_genes, CELL_MARKERS)
        except Exception as e:
            logger.warning(f"   Tangram başarısız ({e}). Score-based fallback devrede...")
            ct_prop_df = _score_based_fallback(adata_sp, CELL_MARKERS)

    # Guarantee ct_prop_df is always a proper DataFrame
    if not isinstance(ct_prop_df, pd.DataFrame):
        ct_prop_df = pd.DataFrame(
            ct_prop_df if hasattr(ct_prop_df, '__array__') else np.asarray(ct_prop_df),
            index=adata_sp.obs_names
        )

    # ── Normalize & Clip Proportions ─────────────────────────
    ct_prop_df = ct_prop_df.clip(lower=0)
    row_sums   = ct_prop_df.sum(axis=1).replace(0, np.nan)
    ct_prop_df = ct_prop_df.div(row_sums, axis=0).fillna(0)

    adata_sp.obsm["celltype_proportions"] = ct_prop_df
    report_progress(85)

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
    logger.info(f"   Dekonvolüsyon tamamlandı — Mean Entropy: {entropy.mean():.3f}")
    report_progress(90)

    # ── Save ─────────────────────────────────────────────────
    deconv_h5ad = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    adata_sp.write_h5ad(deconv_h5ad)
    logger.info(f"   ✅ Kaydedildi: {deconv_h5ad}")

    # ── Figures ──────────────────────────────────────────────
    logger.info("🎨 Figürler oluşturuluyor...")
    dom_ct = ct_prop_df.idxmax(axis=1)
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
        "n_spots":          int(adata_sp.n_obs),
        "n_cell_types":     len(ct_prop_df.columns),
        "cell_type_names":  list(ct_prop_df.columns),
        "mean_proportions": ct_mean_props,
        "avg_confidence":   float(adata_sp.obs['deconv_confidence'].mean()),
        "avg_entropy":      float(adata_sp.obs['deconv_entropy'].mean()),
        "avg_sparsity":     float(adata_sp.obs['deconv_sparsity'].mean()),
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
