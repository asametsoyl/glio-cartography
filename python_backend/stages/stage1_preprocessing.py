#!/usr/bin/env python3
"""Stage 1: scRNA-seq + Spatial preprocessing"""
import os, sys, json
from pathlib import Path
import numpy as np
import scipy.stats as stats

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SCRNA_PATH  = Path(os.environ["GLIO_SCRNA_PATH"])
SPATIAL_DIR = Path(os.environ["GLIO_SPATIAL_DIR"])
OUTPUT_DIR  = Path(os.environ["GLIO_OUTPUT_DIR"])
PATIENT_ID  = os.environ.get("GLIO_PATIENT_ID", "Patient_A")

import scanpy as sc
import squidpy as sq
from loguru import logger

sc.settings.verbosity = 1

import shutil

# ── Output dirs ─────────────────────────────────────────────
(OUTPUT_DIR / "preprocessing" / "scRNA").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "preprocessing" / "spatial").mkdir(parents=True, exist_ok=True)

# Görüntü ve scale faktörleri frontend için kopyala
spatial_img_dir = SPATIAL_DIR / "spatial"
out_img_dir = OUTPUT_DIR / "spatial_data"
if spatial_img_dir.exists() and spatial_img_dir.is_dir():
    shutil.copytree(spatial_img_dir, out_img_dir, dirs_exist_ok=True)
    logger.info("   Background imajı kopyalandı.")

logger.info(f"🔬 scRNA-seq yükleniyor: {SCRNA_PATH}")

# ── Load scRNA ───────────────────────────────────────────────
ext = SCRNA_PATH.suffix.lower()
if ext in ['.h5ad']:
    adata_sc = sc.read_h5ad(SCRNA_PATH)
elif ext in ['.h5']:
    adata_sc = sc.read_10x_h5(SCRNA_PATH)
elif ext in ['.loom']:
    adata_sc = sc.read_loom(SCRNA_PATH)
elif ext in ['.csv', '.tsv']:
    sep = '\t' if ext == '.tsv' else ','
    import pandas as pd
    logger.info("   Pandas ile okunuyor (büyük dosyalar için zaman alabilir)...")
    # Dosya çok büyük, bellek hatası vermemesi için okurken string hücreleri ayıklayalım
    df = pd.read_csv(SCRNA_PATH, sep=sep, index_col=0)
    numeric_df = df.select_dtypes(include=[np.number])
    
    if numeric_df.shape[1] < df.shape[1]:
        logger.warning(f"   {df.shape[1] - numeric_df.shape[1]} adet metin/kategorik sütun yoksayıldı.")
    
    adata_sc = sc.AnnData(numeric_df.T)
else:
    logger.error(f"Desteklenmeyen format: {ext}")
    sys.exit(1)

logger.info(f"   scRNA shape: {adata_sc.shape}")

# ── scRNA QC (v3.1 Biyolojik Düzeltmeler) ──────────────────────
adata_sc.var_names_make_unique()

# Gen Filtresi: %1'den küçük görünmeyen genleri at
min_cells_threshold = max(10, int(adata_sc.n_obs * 0.01))
sc.pp.filter_genes(adata_sc, min_cells=min_cells_threshold)

# Hücre Filtresi: Probe kalitesi
sc.pp.filter_cells(adata_sc, min_genes=200)

# MT, Ribo, ve Hemoglobin
adata_sc.var["mt"] = adata_sc.var_names.str.upper().str.startswith("MT-")
adata_sc.var["ribo"] = adata_sc.var_names.str.upper().str.startswith(("RPS", "RPL"))
adata_sc.var["hb"] = adata_sc.var_names.str.upper().str.startswith(("HBA", "HBB", "HBM"))
sc.pp.calculate_qc_metrics(adata_sc, qc_vars=["mt", "ribo", "hb"], percent_top=None, log1p=False, inplace=True)

# Adaptif Doublet (MAD) Filtresi
median_genes = np.median(adata_sc.obs['n_genes_by_counts'])
mad_genes = stats.median_abs_deviation(adata_sc.obs['n_genes_by_counts'])
max_genes = median_genes + 3 * mad_genes
adata_sc = adata_sc[adata_sc.obs['n_genes_by_counts'] < max_genes, :].copy()

# MT Filtresi (%15)
adata_sc = adata_sc[adata_sc.obs.pct_counts_mt < 15.0].copy()

logger.info(f"   QC sonrası: {adata_sc.shape}")

# ── Normalization + HVG ─────────────────────────────────────
# Verinin raw count mu yoksa normalize (TPM vs) mi olduğunu tespit et
counts_per_cell = np.asarray(adata_sc.X.sum(axis=1)).flatten()
if counts_per_cell.max() - counts_per_cell.min() > 1000:
    logger.info("   Verinin raw count olduğu tespit edildi, normalize_total uygulanıyor.")
    sc.pp.normalize_total(adata_sc, target_sum=1e4)
else:
    logger.info("   Veri halihazırda normalize/TPM gibi görünüyor, normalize_total atlandı.")

sc.pp.log1p(adata_sc)

adata_sc.raw = adata_sc.copy()

try:
    sc.pp.highly_variable_genes(adata_sc, flavor="seurat", n_top_genes=3000)
except Exception:
    sc.pp.highly_variable_genes(adata_sc, flavor="cell_ranger", n_top_genes=3000)

adata_sc_hvg = adata_sc[:, adata_sc.var.highly_variable].copy()

# ── PCA + Clustering ────────────────────────────────────────
sc.pp.scale(adata_sc_hvg, max_value=10)

n_comps_actual = min(50, adata_sc_hvg.n_obs - 1, adata_sc_hvg.n_vars - 1)
sc.tl.pca(adata_sc_hvg, svd_solver='arpack', n_comps=n_comps_actual)
adata_sc.obsm['X_pca'] = adata_sc_hvg.obsm['X_pca']

n_pcs_actual = adata_sc.obsm['X_pca'].shape[1]
sc.pp.neighbors(adata_sc, n_pcs=n_pcs_actual, n_neighbors=15)
sc.tl.umap(adata_sc)
sc.tl.leiden(adata_sc, resolution=0.8)
logger.info(f"   Leiden clusters: {adata_sc.obs['leiden'].nunique()}")

# ── Save scRNA ───────────────────────────────────────────────
scrna_out = OUTPUT_DIR / "preprocessing" / "scRNA" / "scrna_preprocessed.h5ad"
adata_sc.write_h5ad(scrna_out)
logger.info(f"   ✅ scRNA kaydedildi: {scrna_out}")

# ── Load Spatial ─────────────────────────────────────────────
logger.info(f"📍 Spatial veri yükleniyor: {SPATIAL_DIR}")

# Try Visium format first
try:
    adata_sp = sq.read.visium(SPATIAL_DIR)
    logger.info("   Visium formatı tanındı")
except Exception:
    try:
        # Belki adı 'filtered_feature_bc_matrix.h5' değildir, klasördeki ilk .h5 dosyasını dene
        h5_files = list(SPATIAL_DIR.glob("*.h5"))
        if h5_files:
            adata_sp = sq.read.visium(SPATIAL_DIR, counts_file=h5_files[0].name)
            logger.info(f"   Visium formatı tanındı ({h5_files[0].name})")
        else:
            raise ValueError("H5 dosyası yok")
    except Exception:
        # Try h5ad files
        h5ad_files = list(SPATIAL_DIR.glob("*.h5ad"))
        if h5ad_files:
            adata_sp = sc.read_h5ad(h5ad_files[0])
            logger.info(f"   H5AD yüklendi: {h5ad_files[0].name}")
        else:
            logger.error("Spatial veri formatı tanınamadı!")
            sys.exit(1)

# Format kontrolü: Eğer mekansal koordinat yoksa uyar
if "spatial" not in adata_sp.obsm:
    logger.warning("Spatial koordinatlar (obsm['spatial']) bulunamadı! UMAP koordinatlarına başvuruluyor.")
    if "X_umap" not in adata_sp.obsm:
        sc.pp.pca(adata_sp)
        sc.pp.neighbors(adata_sp)
        sc.tl.umap(adata_sp)
    adata_sp.obsm["spatial"] = adata_sp.obsm["X_umap"].copy()

logger.info(f"   Spatial shape: {adata_sp.shape}")

# ── Spatial QC (v5.1) ───────────────────────────────────────
adata_sp.var_names_make_unique()

adata_sp.var["mt"] = adata_sp.var_names.str.upper().str.startswith("MT-")
adata_sp.var["ribo"] = adata_sp.var_names.str.upper().str.startswith(("RPS", "RPL"))
adata_sp.var["hb"] = adata_sp.var_names.str.upper().str.startswith(("HBA", "HBB", "HBM"))
sc.pp.calculate_qc_metrics(adata_sp, qc_vars=["mt", "ribo", "hb"], percent_top=None, log1p=False, inplace=True)

sc.pp.filter_genes(adata_sp, min_cells=10)
sc.pp.filter_cells(adata_sp, min_counts=1000)
sc.pp.filter_cells(adata_sp, max_counts=40000)
adata_sp = adata_sp[adata_sp.obs.n_genes_by_counts >= 200].copy()

# ── Normalize Spatial ────────────────────────────────────────
sc.pp.normalize_total(adata_sp, target_sum=1e4)
sc.pp.log1p(adata_sp)

adata_sp.raw = adata_sp.copy()

sc.pp.highly_variable_genes(adata_sp, flavor="seurat", n_top_genes=3000)

adata_sp_hvg = adata_sp[:, adata_sp.var.highly_variable].copy()
sc.pp.scale(adata_sp_hvg, max_value=10)

n_comps = min(50, adata_sp_hvg.n_obs - 1, adata_sp_hvg.n_vars - 1)
sc.tl.pca(adata_sp_hvg, svd_solver="arpack", n_comps=n_comps)
adata_sp.obsm['X_pca'] = adata_sp_hvg.obsm['X_pca']
adata_sp.obsm['X_features'] = adata_sp.obsm['X_pca']

# Spatial veri için PCA sonrası komşuluk ağını (neighbors) ve leiden kümelerini hesapla
# (Dekonvolüsyon ve spatial niş analizi için kritiktir)
n_pcs_spatial = adata_sp.obsm['X_pca'].shape[1]
sc.pp.neighbors(adata_sp, n_pcs=n_pcs_spatial, n_neighbors=15)
sc.tl.umap(adata_sp)
sc.tl.leiden(adata_sp, resolution=0.8)
logger.info(f"   Spatial Leiden clusters: {adata_sp.obs['leiden'].nunique()}")

# TME Niche Scoring (Kullanıcı Algoritması)
def score_niche(adata, gene_list, score_name):
    valid_genes = [g for g in gene_list if g in adata.var_names]
    if valid_genes:
        sc.tl.score_genes(adata, gene_list=valid_genes, score_name=score_name)
score_niche(adata_sp, ['HIF1A', 'CA9', 'SLC2A1', 'LDHA', 'BNIP3'], 'hypoxia_score')
score_niche(adata_sp, ['IL10', 'TGFB1', 'CD274', 'VSIG4', 'MRC1'], 'tam_polarization_score')
score_niche(adata_sp, ['HAVCR2', 'LAG3', 'PDCD1', 'CTLA4', 'TOX'], 'tcell_exhaustion_score')
score_niche(adata_sp, ['VEGFA', 'ANGPT2', 'FLT1', 'KDR', 'PECAM1', 'ESM1'], 'angiogenesis_score')

# ── Save Spatial ─────────────────────────────────────────────
spatial_out = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_preprocessed.h5ad"
adata_sp.write_h5ad(spatial_out)
logger.info(f"   ✅ Spatial kaydedildi: {spatial_out}")

# ── Summary ──────────────────────────────────────────────────
summary = {
    "scrna_cells": int(adata_sc.n_obs),
    "scrna_genes": int(adata_sc.n_vars),
    "scrna_clusters": int(adata_sc.obs['leiden'].nunique()),
    "spatial_spots": int(adata_sp.n_obs),
    "spatial_genes": int(adata_sp.n_vars),
    "patient_id": PATIENT_ID,
    "status": "success"
}
(OUTPUT_DIR / "preprocessing" / "preprocessing_summary.json").write_text(
    json.dumps(summary, indent=2))
logger.info("✅ Stage 1 tamamlandı")
print(json.dumps({"stage": "preprocessing", "status": "done", **summary}))
