#!/usr/bin/env python3
"""Stage 2: Cell-type deconvolution via Tangram"""
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = Path(os.environ["GLIO_OUTPUT_DIR"])
PATIENT_ID = os.environ.get("GLIO_PATIENT_ID", "Patient_A")

import scanpy as sc
import tangram as tg
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from loguru import logger
import yaml

# ── Load config markers ─────────────────────────────────────
config_path = PROJECT_ROOT / "configs" / "config.yaml"
CELL_MARKERS = {}
try:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    CELL_MARKERS = cfg.get("cell_markers", {})
except FileNotFoundError:
    logger.warning(f"   Config dosyası bulunamadı ({config_path}). Varsayılan marker genler kullanılacak.")
    CELL_MARKERS = {
        "Tumor_MES": ["CHI3L1", "CD44", "VIM"],
        "Tumor_OPC": ["PDGFRA", "OLIG1", "OLIG2"],
        "Tumor_AC": ["GFAP", "ALDOC", "S100B"],
        "TAM_Macrophage": ["CD68", "CD163", "AIF1", "CD14"],
        "TAM_Microglia": ["CX3CR1", "P2RY12", "TMEM119"],
        "T_Cell": ["CD3D", "CD3E", "CD8A", "CD4"],
        "Endothelial": ["PECAM1", "VWF", "CD34"],
        "Oligodendrocyte": ["MBP", "PLP1", "MAG"]
    }


# ── Output dir ───────────────────────────────────────────────
deconv_out = OUTPUT_DIR / "deconvolution"
deconv_out.mkdir(parents=True, exist_ok=True)

# ── Load preprocessed data ───────────────────────────────────
scrna_path   = OUTPUT_DIR / "preprocessing" / "scRNA" / "scrna_preprocessed.h5ad"
spatial_path = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_preprocessed.h5ad"

logger.info("📂 Veri yükleniyor...")
adata_sc = sc.read_h5ad(scrna_path)
adata_sp = sc.read_h5ad(spatial_path)
logger.info(f"   scRNA: {adata_sc.shape}, Spatial: {adata_sp.shape}")

# ── Cell type annotation ─────────────────────────────────────
logger.info("🏷️ Hücre tipi anotasyonu...")

# Score cells for each type
cell_type_scores = {}
for cell_type, markers in CELL_MARKERS.items():
    valid_markers = [m for m in markers if m in adata_sc.var_names]
    if valid_markers:
        sc.tl.score_genes(adata_sc, valid_markers, score_name=f"score_{cell_type}")
        cell_type_scores[cell_type] = f"score_{cell_type}"

# Assign dominant cell type per cluster
score_cols = list(cell_type_scores.values())
ct_names   = list(cell_type_scores.keys())

if score_cols:
    score_df = adata_sc.obs[score_cols].copy()
    adata_sc.obs["cell_type"] = [ct_names[i] for i in score_df.values.argmax(axis=1)]
else:
    adata_sc.obs["cell_type"] = "unknown"

logger.info(f"   Hücre tipleri: {adata_sc.obs['cell_type'].value_counts().to_dict()}")

# ── Tangram Deconvolution (v2.1 Mode) ─────────────────────────
logger.info("🔬 Tangram dekonvolüsyonu başlatılıyor (mode='cells')...")

# 1. Marker Gen Çıkarımı (rank_genes_groups)
adata_sc_copy = adata_sc.copy()
if adata_sc_copy.raw is None:
    sc.pp.normalize_total(adata_sc_copy, target_sum=1e4)
    sc.pp.log1p(adata_sc_copy)

sc.tl.rank_genes_groups(adata_sc_copy, groupby='cell_type', method='wilcoxon', use_raw=False)

marker_genes = set()
for ct in adata_sc_copy.obs['cell_type'].unique():
    try:
        genes_df = sc.get.rank_genes_groups_df(adata_sc_copy, group=ct, key='rank_genes_groups')
        genes_df = genes_df[genes_df['logfoldchanges'] > 0.5]
        marker_genes.update(genes_df.head(50)['names'].tolist())
    except: pass

marker_genes = sorted(list(marker_genes))
if len(marker_genes) < 100 and 'highly_variable' in adata_sc.var.columns:
    hvg = set(adata_sc.var_names[adata_sc.var['highly_variable']])
    marker_genes = sorted(list(set(marker_genes) | hvg))[:500]

logger.info(f"   Tangram marker genleri: {len(marker_genes)}")

# Tangram mapping
tg.pp_adatas(adata_sc, adata_sp, genes=marker_genes)

try:
    # mode='clusters': Hücre tiplerini spotlara kümeler halinde eşler.
    # Büyük scRNA verisinde bellek açısından verimli ve 'cells' moduna göre daha stabildir.
    # density_prior='uniform' seçimi, spot/hücre total RNA dağılımının güvenilir olmadığı
    # TSV formatlarında daha doğru dekonvolüsyon yapılmasını sağlar.
    ad_map = tg.map_cells_to_space(
        adata_sc, adata_sp,
        mode="clusters",
        cluster_label="cell_type",
        density_prior="uniform",
        num_epochs=500,
        device="cpu",
        verbose=False
    )
    tg.project_cell_annotations(ad_map, adata_sp, annotation="cell_type")
    
    if "tangram_ct_pred" in adata_sp.obsm:
        ct_prop_df = adata_sp.obsm["tangram_ct_pred"]
        if not isinstance(ct_prop_df, pd.DataFrame):
            ct_types = sorted(adata_sc.obs['cell_type'].unique())
            ct_prop_df = pd.DataFrame(ct_prop_df, index=adata_sp.obs_names, columns=ct_types[:ct_prop_df.shape[1]])
    else:
        raise ValueError("Tangram output not found")
except Exception as e:
    logger.warning(f"   Tangram hata: {e}, fallback kullanılıyor...")
    # Fallback: score-based deconvolution
    ct_proportions = {}
    for cell_type, markers in CELL_MARKERS.items():
        valid = [m for m in markers if m in adata_sp.var_names]
        if valid:
            sc.tl.score_genes(adata_sp, valid, score_name=f"prop_{cell_type}")
            ct_proportions[cell_type] = adata_sp.obs[f"prop_{cell_type}"].values
    
    ct_prop_df = pd.DataFrame(ct_proportions, index=adata_sp.obs_names)

# Temizle ve Normalize et
ct_prop_df = ct_prop_df.clip(lower=0)
row_sums = ct_prop_df.sum(axis=1).replace(0, np.nan)
ct_prop_df = ct_prop_df.div(row_sums, axis=0).fillna(0)

adata_sp.obsm["celltype_proportions"] = ct_prop_df

# Kalite Kontrol: Normalize Entropy (0=kesin, 1=belirsiz)
n_types = ct_prop_df.shape[1]
epsilon = 1e-10
raw_entropy = -(ct_prop_df * np.log2(ct_prop_df + epsilon)).sum(axis=1)
max_entropy = np.log2(n_types) if n_types > 1 else 1.0
entropy = raw_entropy / max_entropy
adata_sp.obs['deconv_entropy'] = entropy.values
adata_sp.obs['deconv_confidence'] = ct_prop_df.max(axis=1).values

logger.info(f"   Dekonvolüsyon tamamlandı. Mean Entropy: {entropy.mean():.3f}")

# Niche Skorları stage 1'de entegre edildiği için burada atlandı.

# ── Save ─────────────────────────────────────────────────────
deconv_h5ad = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
adata_sp.write_h5ad(deconv_h5ad)
logger.info(f"   ✅ Dekonvolüsyon kaydedildi: {deconv_h5ad}")

# ── Figures ──────────────────────────────────────────────────
logger.info("🎨 Figürler oluşturuluyor...")

# Dominant cell type map
dom_ct = ct_prop_df.idxmax(axis=1)
adata_sp.obs["dominant_celltype"] = dom_ct.values

if "spatial" in adata_sp.obsm:
    coords = adata_sp.obsm["spatial"]
    fig, ax = plt.subplots(figsize=(10, 8), facecolor='#0d1117')
    import matplotlib.cm as cm
    unique_cts = dom_ct.unique()
    colors = cm.tab20(np.linspace(0, 1, len(unique_cts)))
    ct_color = {ct: colors[i] for i, ct in enumerate(unique_cts)}
    for ct in unique_cts:
        mask = dom_ct == ct
        ax.scatter(coords[mask, 0], coords[mask, 1],
                   c=[ct_color[ct]], label=ct, s=5, alpha=0.8)
    ax.set_title(f"Dominant Hücre Tipi — {PATIENT_ID}", color='white', fontsize=14)
    ax.set_facecolor('#0d1117')
    ax.tick_params(colors='white')
    ax.legend(loc='upper right', fontsize=7, facecolor='#1a1a2e', labelcolor='white',
              markerscale=2, ncol=2)
    plt.tight_layout()
    fig.savefig(deconv_out / "fig2_dominant_celltype_map.png", dpi=150,
                bbox_inches='tight', facecolor='#0d1117')
    plt.close()

    # Coarse proportions bar
    coarse_groups = {"Tumor": [], "Myeloid": [], "T_Cell": [], "Stromal": []}
    for ct in ct_prop_df.columns:
        for grp in coarse_groups:
            if grp in ct:
                coarse_groups[grp].append(ct)
                break
    coarse_means = {g: ct_prop_df[cols].sum(axis=1).mean() if cols else 0
                    for g, cols in coarse_groups.items()}
    
    fig, ax = plt.subplots(figsize=(8, 5), facecolor='#0d1117')
    ax.bar(coarse_means.keys(), coarse_means.values(),
           color=['#E63946', '#2A9D8F', '#457B9D', '#F4A261'])
    ax.set_title(f"TME Kompozisyon — {PATIENT_ID}", color='white')
    ax.set_facecolor('#0d1117')
    ax.tick_params(colors='white')
    ax.set_ylabel("Ortalama Oran", color='white')
    plt.tight_layout()
    fig.savefig(deconv_out / "fig3_tme_composition.png", dpi=150,
                bbox_inches='tight', facecolor='#0d1117')
    plt.close()

# ── Summary ──────────────────────────────────────────────────
ct_mean_props = {ct: float(ct_prop_df[ct].mean()) for ct in ct_prop_df.columns}
summary = {
    "n_spots": int(adata_sp.n_obs),
    "n_cell_types": len(ct_prop_df.columns),
    "cell_type_names": list(ct_prop_df.columns),
    "mean_proportions": ct_mean_props,
    "avg_confidence": float(adata_sp.obs['deconv_confidence'].mean()) if 'deconv_confidence' in adata_sp.obs else 0.0,
    "avg_entropy": float(adata_sp.obs['deconv_entropy'].mean()) if 'deconv_entropy' in adata_sp.obs else 0.0,
    "dominant_frequencies": {str(k): int(v) for k, v in dom_ct.value_counts().items()},
    "patient_id": PATIENT_ID,
    "status": "success"
}
(deconv_out / "deconvolution_summary.json").write_text(json.dumps(summary, indent=2))
logger.info("✅ Stage 2 tamamlandı")
print(json.dumps({"stage": "deconvolution", "status": "done"}))
