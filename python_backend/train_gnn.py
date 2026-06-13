#!/usr/bin/env python3
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import sys
import gc
import json
from pathlib import Path
import numpy as np
import pandas as pd
import anndata as ad
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.data import Data
from torch_geometric.nn import GATv2Conv, SAGEConv, TransformerConv, BatchNorm
from scipy.spatial import cKDTree
from scipy.stats import pearsonr, spearmanr
from loguru import logger
try:
    import optuna
    from optuna.trial import Trial
except ImportError:
    optuna = None
    Trial = None
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

GLIO_OUTPUT_DIR = os.environ.get("GLIO_OUTPUT_DIR", "outputs")
OUT_DIR = os.path.join(GLIO_OUTPUT_DIR, "gnn")

# SPATIAL_PATH fallback checking
default_spatial = os.path.join(GLIO_OUTPUT_DIR, "preprocessing", "spatial", "spatial_deconvolved.h5ad")
if not os.path.exists(default_spatial):
    default_spatial = "data/processed/spatial_deconvolved.h5ad"
SPATIAL_PATH = os.environ.get("GLIO_SPATIAL_PATH", default_spatial)

def exit_with_error(message: str) -> None:
    logger.error(message)
    print(json.dumps({"stage": "gnn_training", "status": "error", "message": message}))
    sys.exit(1)


# ============================================================
# L-R KATALOG (lowercase)
# [BIO-1] NLGN3-NRXN1 → NLGN3-EGFR (GBM'de shedding→PI3K/mTOR ekseni)
# [BIO-2] FASLG-FAS kategorisi immunosuppression (tümör T-cell öldürme)
# [BIO-3] SPP1-ITGAV eklendi (ECM remodeling / invasion)
# ============================================================
LR_PAIRS = [
    # ── ANGIOGENESIS & VASCULAR ──────────────────────────────────
    ('vegfa',  'kdr',     'angiogenesis'),
    ('vegfa',  'flt1',    'angiogenesis'),
    ('vegfb',  'flt1',    'angiogenesis'),
    ('pgf',    'flt1',    'angiogenesis'),
    ('angpt1', 'tek',     'angiogenesis'),
    ('angpt2', 'tek',     'angiogenesis'),
    ('pdgfa',  'pdgfra',  'angiogenesis'),
    ('pdgfb',  'pdgfrb',  'angiogenesis'),
    ('pdgfc',  'pdgfra',  'angiogenesis'),
    ('fgf2',   'fgfr1',   'angiogenesis'),
    ('fgf2',   'fgfr2',   'angiogenesis'),
    ('dll4',   'notch1',  'angiogenesis'),
    ('dll4',   'notch4',  'angiogenesis'),
    ('jag1',   'notch1',  'angiogenesis'),

    # ── IMMUNOSUPPRESSION & CHECKPOINTS ─────────────────────────
    ('cd274',  'pdcd1',   'immunosuppression'),
    ('pdcd1lg2','pdcd1',  'immunosuppression'),
    ('cd80',   'cd28',    'immunosuppression'),
    ('cd80',   'ctla4',   'immunosuppression'),
    ('cd86',   'ctla4',   'immunosuppression'),
    ('cd86',   'cd28',    'immunosuppression'),
    ('lgals9', 'havcr2',  'immunosuppression'),
    ('lgals9', 'ptprc',   'immunosuppression'),  # CD45 is PTPRC
    ('fgl1',   'lag3',    'immunosuppression'),
    ('tgfb1',  'tgfbr1',  'immunosuppression'),
    ('tgfb1',  'tgfbr2',  'immunosuppression'),
    ('tgfb2',  'tgfbr1',  'immunosuppression'),
    ('tgfb2',  'tgfbr2',  'immunosuppression'),
    ('spp1',   'cd44',    'immunosuppression'),
    ('csf1',   'csf1r',   'immunosuppression'),
    ('il10',   'il10ra',  'immunosuppression'),
    ('cd47',   'sirpa',   'immunosuppression'),
    ('cd47',   'thbs1',   'immunosuppression'),
    ('mif',    'cd74',    'immunosuppression'),
    ('mif',    'cxcr4',   'immunosuppression'),
    ('mif',    'ackr3',   'immunosuppression'),
    ('ccl2',   'ccr2',    'immunosuppression'),
    ('ccl5',   'ccr5',    'immunosuppression'),
    ('anxa1',  'fpr1',    'immunosuppression'),
    ('anxa1',  'fpr2',    'immunosuppression'),

    # ── INVASION & EMT & MIGRATION ──────────────────────────────
    ('hgf',    'met',     'invasion'),
    ('egf',    'egfr',    'invasion'),
    ('areg',   'egfr',    'invasion'),
    ('tgfa',   'egfr',    'invasion'),
    ('nrg1',   'erbb3',   'invasion'),
    ('nrg1',   'erbb4',   'invasion'),
    ('ptn',    'ptprz1',  'invasion'),
    ('ptn',    'sdc1',    'invasion'),
    ('ptn',    'sdc4',    'invasion'),
    ('mdk',    'ptprz1',  'invasion'),
    ('mdk',    'sdc1',    'invasion'),
    ('mdk',    'sdc4',    'invasion'),
    ('gas6',   'axl',     'invasion'),
    ('pros1',  'tyro3',   'invasion'),
    ('sema4d', 'plxnb1',  'invasion'),
    ('sema4d', 'plxnb2',  'invasion'),
    ('slit2',  'robo1',   'invasion'),
    ('slit2',  'robo2',   'invasion'),
    ('postn',  'itgav',   'invasion'),
    ('postn',  'itgb3',   'invasion'),

    # ── CHEMOKINES & CYTOKINES (OmniPath) ─────────────────────────
    ('cxcl12', 'cxcr4',   'chemokine'),
    ('cxcl12', 'ackr3',   'chemokine'),
    ('cxcl8',  'cxcr1',   'chemokine'),
    ('cxcl8',  'cxcr2',   'chemokine'),
    ('cxcl1',  'cxcr2',   'chemokine'),
    ('cxcl2',  'cxcr2',   'chemokine'),
    ('cxcl3',  'cxcr2',   'chemokine'),
    ('cxcl5',  'cxcr2',   'chemokine'),
    ('cxcl6',  'cxcr2',   'chemokine'),
    ('cxcl9',  'cxcr3',   'chemokine'),
    ('cxcl10', 'cxcr3',   'chemokine'),
    ('cxcl11', 'cxcr3',   'chemokine'),
    ('cxcl16', 'cxcr6',   'chemokine'),
    ('ccl2',   'ccr2',    'chemokine'),
    ('ccl3',   'ccr1',    'chemokine'),
    ('ccl3',   'ccr5',    'chemokine'),
    ('ccl4',   'ccr5',    'chemokine'),
    ('ccl5',   'ccr1',    'chemokine'),
    ('ccl5',   'ccr3',    'chemokine'),
    ('ccl5',   'ccr5',    'chemokine'),
    ('ccl7',   'ccr2',    'chemokine'),
    ('ccl8',   'ccr2',    'chemokine'),
    ('ccl20',  'ccr6',    'chemokine'),
    ('ccl22',  'ccr4',    'chemokine'),
    ('ccl28',  'ccr10',   'chemokine'),
    ('cx3cl1', 'cx3cr1',  'chemokine'),
    ('il1a',   'il1r1',   'chemokine'),
    ('il1b',   'il1r1',   'chemokine'),
    ('il6',    'il6r',    'chemokine'),
    ('il6',    'il6st',   'chemokine'),  # GP130 is IL6ST
    ('tnf',    'tnfrsf1a','chemokine'),
    ('tnf',    'tnfrsf1b','chemokine'),

    # ── ECM & INTEGRIN & ADHESION (OmniPath) ──────────────────────
    ('fn1',    'itga5',   'ecm_integrin'),
    ('fn1',    'itgav',   'ecm_integrin'),
    ('fn1',    'itgb1',   'ecm_integrin'),
    ('fn1',    'itga8',   'ecm_integrin'),
    ('fn1',    'itgb6',   'ecm_integrin'),
    ('col1a1', 'itga1',   'ecm_integrin'),
    ('col1a1', 'itga2',   'ecm_integrin'),
    ('col1a1', 'itgb1',   'ecm_integrin'),
    ('col4a1', 'itga1',   'ecm_integrin'),
    ('col4a1', 'itga2',   'ecm_integrin'),
    ('col4a1', 'itgb1',   'ecm_integrin'),
    ('lama1',  'itga3',   'ecm_integrin'),
    ('lama1',  'itga6',   'ecm_integrin'),
    ('lama1',  'itgb1',   'ecm_integrin'),
    ('lamb1',  'itga3',   'ecm_integrin'),
    ('lamb1',  'itga6',   'ecm_integrin'),
    ('lamb1',  'itgb1',   'ecm_integrin'),
    ('lamc1',  'itga3',   'ecm_integrin'),
    ('lamc1',  'itga6',   'ecm_integrin'),
    ('lamc1',  'itgb1',   'ecm_integrin'),
    ('vcan',   'cd44',    'ecm_integrin'),
    ('vcan',   'itgb1',   'ecm_integrin'),
    ('tnc',    'itgav',   'ecm_integrin'),
    ('tnc',    'itgb1',   'ecm_integrin'),
    ('tnc',    'itga9',   'ecm_integrin'),
    ('spp1',   'itgav',   'ecm_integrin'),
    ('spp1',   'itga5',   'ecm_integrin'),
    ('spp1',   'itgb1',   'ecm_integrin'),
    ('spp1',   'itgb3',   'ecm_integrin'),
    ('spp1',   'itgb5',   'ecm_integrin'),
    ('thbs1',  'itgav',   'ecm_integrin'),
    ('thbs1',  'itgb1',   'ecm_integrin'),
    ('thbs1',  'cd47',    'ecm_integrin'),
    ('thbs1',  'cd36',    'ecm_integrin'),
    ('cd44',   'itgb1',   'ecm_integrin'),
    ('hsp90aa1','itgae',  'ecm_integrin'),
    ('vtn',    'itgav',   'ecm_integrin'),
    ('vtn',    'itgb3',   'ecm_integrin'),

    # ── NEURO-GLIOMA SYNAPTIC CROSSTALK ──────────────────────────
    ('nlgn3',  'nrxn1',   'neuro_synaptic'),
    ('nlgn3',  'nrxn3',   'neuro_synaptic'),
    ('nlgn3',  'egfr',    'neuro_synaptic'),
    ('bdnf',   'ntrk2',   'neuro_synaptic'),
    ('bdnf',   'ngfr',    'neuro_synaptic'),
    ('ntf3',   'ntrk3',   'neuro_synaptic'),
    ('ntf3',   'ntrk2',   'neuro_synaptic'),
    ('gdnf',   'gfra1',   'neuro_synaptic'),
    ('gdnf',   'ret',     'neuro_synaptic'),
    ('cntf',   'cntfr',   'neuro_synaptic'),
    ('lgi1',   'adam22',  'neuro_synaptic'),
    ('lgi1',   'adam23',  'neuro_synaptic'),

    # ── STEMNESS & WNT & NOTCH ──────────────────────────────────
    ('dll1',   'notch1',  'stemness_wnt_notch'),
    ('dll3',   'notch1',  'stemness_wnt_notch'),
    ('dll4',   'notch2',  'stemness_wnt_notch'),
    ('jag1',   'notch2',  'stemness_wnt_notch'),
    ('jag1',   'notch3',  'stemness_wnt_notch'),
    ('wnt5a',  'fzd2',    'stemness_wnt_notch'),
    ('wnt5a',  'fzd4',    'stemness_wnt_notch'),
    ('wnt5a',  'ror2',    'stemness_wnt_notch'),
    ('wnt3a',  'fzd1',    'stemness_wnt_notch'),
    ('wnt3a',  'lrp5',    'stemness_wnt_notch'),
    ('dkk1',   'lrp6',    'stemness_wnt_notch'),
    ('postn',  'itgav',   'stemness_wnt_notch')
]

# ============================================================
# ZONE SİGNATÜRLERİ
# [BIO-4] Eksik GBM markerleri eklendi
# ============================================================
ZONE_SIGNATURES = {
    'Pseudopalisading Necrosis': [
        'hif1a', 'ca9', 'vegfa', 'slc2a1', 'bnip3', 'ddit4',
        # [BIO-4] Hipoksi metabolizması
        'ldha', 'pdk1',
    ],
    'Microvascular Proliferation': [
        'vegfa', 'angpt2', 'pdgfrb', 'pecam1', 'kdr', 'tek',
    ],
    'Cellular Tumor': [
        'mki67', 'top2a', 'egfr', 'olig2', 'sox2',
        # [BIO-4] Hücre döngüsü markerleri
        'pcna', 'cdk4', 'cdkn2a',
    ],
    'Leading Edge': [
        'vim', 'fn1', 'met', 'cd44', 'cxcr4', 'mmp2',
        # [BIO-4] EMT markerleri
        'mmp9', 'twist1', 'zeb1',
    ],
    'Infiltrating Tumor': [
        'gfap', 'vim', 'cd44', 'cxcr4', 'ptn', 'ptprz1',
        # [BIO-4] ECM remodeling
        'timp1', 'mmp9',
    ],
}
ZONE_NAMES = list(ZONE_SIGNATURES.keys())

# ── Pathway signatures: dinamik olarak pathway_db.json'dan yükle ───────────────
# GNN, data.json'a her spot için pathway skoru yazar.
# pathway_db.json bulunursa 42 KEGG/GO pathway yüklenir;
# bulunamazsa 4 temel GBM pathway kullanılır.
_PATHWAY_DB_PATH = Path(__file__).parent / "pathway_db.json"
_FALLBACK_SIGNATURES = {
    'PI3K_AKT_mTOR': ['akt1', 'akt2', 'pik3ca', 'mtor', 'pten', 'rps6kb1'],
    'MAPK_ERK': ['mapk1', 'mapk3', 'map2k1', 'raf1', 'fos', 'jun'],
    'JAK_STAT': ['jak1', 'jak2', 'stat1', 'stat3', 'stat5a', 'stat5b'],
    'NFkB': ['nfkb1', 'nfkb2', 'rela', 'relb', 'chuk', 'ikbkb']
}

def _load_pathway_signatures() -> dict:
    """Load pathway gene signatures from pathway_db.json (lowercase gene names)."""
    if _PATHWAY_DB_PATH.exists():
        try:
            import json as _json
            with open(_PATHWAY_DB_PATH, "r", encoding="utf-8") as _f:
                _db = _json.load(_f)
            _sigs = {}
            for _p in _db.get("pathways", []):
                # key: pathway ID (e.g. hsa04370, GO:0001525)
                _sigs[_p["id"]] = [g.lower() for g in _p.get("genes", [])]
            if _sigs:
                return _sigs
        except Exception as _e:
            pass  # Fallback aşağıda
    return _FALLBACK_SIGNATURES

PATHWAY_SIGNATURES = _load_pathway_signatures()


# Coarse hücre kategorileri
COARSE_COLS = ['Tumor', 'Myeloid', 'T_Cell', 'Stromal']

# [BUG-1] CT_TO_COARSE_IDX — build_graph_data içinde dinamik doldurulacak
CT_TO_COARSE_IDX: dict[str, int] = {}

# Drug → L-R eşleşmesi (lokal DB, frontend ile senkron)
GBM_DRUG_DB = {
    # L-R Pairs
    "CD274-PDCD1":   {"drug": "Pembrolizumab", "mechanism": "Anti-PD-1 Checkpoint İnhibitörü"},
    "PDCD1LG2-PDCD1":{"drug": "Pembrolizumab", "mechanism": "Anti-PD-1 Checkpoint İnhibitörü"},
    "SPP1-CD44":     {"drug": "RG7356",        "mechanism": "Anti-CD44 Monoklonal Antikor"},
    "VEGFA-KDR":     {"drug": "Bevacizumab",   "mechanism": "Anti-VEGF Monoklonal Antikor"},
    "VEGFA-FLT1":    {"drug": "Bevacizumab",   "mechanism": "Anti-VEGF Monoklonal Antikor"},
    "MIF-CD74":      {"drug": "Ibudilast",     "mechanism": "MIF/CD74 Eksen İnhibitörü"},
    "TGFB1-TGFBR1":  {"drug": "Galunisertib",  "mechanism": "TGFβRI Kinaz İnhibitörü"},
    "TGFB1-TGFBR2":  {"drug": "Galunisertib",  "mechanism": "TGFβRI/II Kinaz İnhibitörü"},
    "AREG-EGFR":     {"drug": "Erlotinib",     "mechanism": "EGFR TKI — Amphiregulin-driven"},
    "EGF-EGFR":      {"drug": "Erlotinib",     "mechanism": "EGFR TKI"},
    "NLGN3-EGFR":    {"drug": "Erlotinib",     "mechanism": "EGFR TKI — Nörogliomal Eksen"},
    "HGF-MET":       {"drug": "Crizotinib",    "mechanism": "MET/ALK Reseptör İnhibitörü"},
    "CXCL12-CXCR4":  {"drug": "AMD3100",       "mechanism": "CXCR4 Antagonisti (Plerixafor)"},
    "CSF1-CSF1R":    {"drug": "Pexidartinib",  "mechanism": "CSF1R Kinaz İnhibitörü"},
    "IL34-CSF1R":    {"drug": "Pexidartinib",  "mechanism": "CSF1R Kinaz İnhibitörü"},
    "CCL2-CCR2":     {"drug": "Carlumab",      "mechanism": "Anti-CCL2 Kemokin Antikoru"},
    "CCL5-CCR5":     {"drug": "Maraviroc",     "mechanism": "CCR5 Antagonisti"},
    "CD47-SIRPA":    {"drug": "Magrolimab",    "mechanism": "Anti-CD47 'Beni Yeme' Sinyal İnhibitörü"},
    "CD80-CTLA4":    {"drug": "Ipilimumab",    "mechanism": "Anti-CTLA-4 Checkpoint İnhibitörü"},
    "CD86-CTLA4":    {"drug": "Ipilimumab",    "mechanism": "Anti-CTLA-4 Checkpoint İnhibitörü"},
    "PDGFB-PDGFRB":  {"drug": "Imatinib",      "mechanism": "PDGFR/c-Kit Tirozin Kinaz İnhibitörü"},
    "SPP1-ITGAV":    {"drug": "Cilengitide",   "mechanism": "Integrin αvβ3/αvβ5 İnhibitörü (ECM Remodeling)"},
    "SPP1-ITGB1":    {"drug": "Cilengitide",   "mechanism": "Integrin β1 İnhibitörü (İnvazyon Bloke Edici)"},
    "TNC-ITGAV":     {"drug": "Cilengitide",   "mechanism": "Integrin αv Sinyalleşme İnhibitörü"},
    "FN1-ITGA5":     {"drug": "Volociximab",   "mechanism": "Anti-Integrin α5β1 Monoklonal Antikor"},
    "CXCL8-CXCR2":   {"drug": "Reparixin",     "mechanism": "CXCR1/CXCR2 Alseptör İnhibitörü (Kemotaksi Bloke)"},
    "IL6-IL6R":      {"drug": "Tocilizumab",   "mechanism": "Anti-IL-6R Monoklonal Antikor (Anti-Enflamatuar)"},
    "TNF-TNFRSF1A":  {"drug": "Infliximab",    "mechanism": "Anti-TNFα Antikoru (NFkB Baskılayıcı)"},
    # Single target fallback keys
    "EGFR":          {"drug": "Erlotinib",     "mechanism": "EGFR Reseptör Tirozin Kinaz İnhibitörü"},
    "MET":           {"drug": "Crizotinib",    "mechanism": "MET Reseptör Tirozin Kinaz İnhibitörü"},
    "CSF1R":         {"drug": "Pexidartinib",  "mechanism": "CSF1R Reseptör Tirozin Kinaz İnhibitörü"},
}


# ============================================================
# GRAPH VERİSİ OLUŞTURMA
# ============================================================
def build_graph_data(adata, k_neighbors: int = 6) -> Data:
    """
    Graph verisi oluşturur.

    Düzeltmeler:
      [BUG-1] CT_TO_COARSE_IDX dolduruldu
      [BUG-2] coarse_props adata.obsm'dan alınıyor
      [BUG-6] Çift yönlü (reciprocal) kenarlar eklendi
      [BIO-4] Zone signature'ları genişletildi
    """
    logger.info("Graph verisi oluşturuluyor...")
    n_spots = adata.n_obs

    # --- Gene expression cache ---
    var_names_lower = {g.lower(): g for g in adata.var_names}
    gene_cache: dict[str, np.ndarray | None] = {}

    def get_gene(name: str) -> np.ndarray | None:
        name_lower = name.lower()
        if name_lower not in gene_cache:
            exact_name = var_names_lower.get(name_lower)
            if exact_name is not None:
                try:
                    col_idx = adata.var_names.get_loc(exact_name)
                    e = adata.X[:, col_idx]
                except Exception:
                    e = adata[:, exact_name].X
                e = e.toarray().flatten() if hasattr(e, 'toarray') else np.asarray(e).flatten()
                gene_cache[name_lower] = e.astype(np.float32)
            else:
                gene_cache[name_lower] = None
        return gene_cache[name_lower]

    # ============ NODE FEATURES ============
    # (A) PCA — z-score
    if 'X_pca' not in adata.obsm:
        raise KeyError("adata.obsm['X_pca'] bulunamadı. Stage 1 (preprocessing) tamamlanmış mı?")
    pca_dim = min(50, adata.obsm['X_pca'].shape[1])
    pca = adata.obsm['X_pca'][:, :pca_dim].copy().astype(np.float32)
    pca = (pca - pca.mean(axis=0)) / (pca.std(axis=0) + 1e-8)

    # (B) Cell type proportions
    ct_df = adata.obsm['celltype_proportions']
    ct_prop = ct_df.values.copy().astype(np.float32)
    ct_names = list(ct_df.columns)

    # Helper to map cell types to coarse categories
    def get_coarse_group(ct_name: str) -> str | None:
        ct_lower = ct_name.lower()
        if any(x in ct_lower for x in ['tumor', 'glioma', 'ac', 'mes', 'opc']):
            return 'Tumor'
        if any(x in ct_lower for x in ['myeloid', 'tam', 'macrophage', 'microglia', 'mono']):
            return 'Myeloid'
        if any(x in ct_lower for x in ['t_cell', 'tcell', 't-cell', 'lymphocyte', 'cd3', 'cd8', 'cd4']):
            return 'T_Cell'
        if any(x in ct_lower for x in ['stromal', 'endothelial', 'oligodendrocyte', 'astrocyte', 'fibroblast']):
            return 'Stromal'
        return None

    # [BUG-1] ct_to_coarse_idx doldur (local dictionary for thread safety)
    ct_to_coarse_idx = {}
    coarse_map = {'Tumor': 0, 'Myeloid': 1, 'T_Cell': 2, 'Stromal': 3}
    for i, ct in enumerate(ct_names):
        group = get_coarse_group(ct)
        if group is not None:
            ct_to_coarse_idx[ct] = coarse_map[group]

    # (C) Pathway/Niche scores — z-score
    niche_cols = ['hypoxia_score', 'myeloid_suppression_score',
                  'tcell_exhaustion_score', 'angiogenesis_score']
    niche = np.zeros((n_spots, len(niche_cols)), dtype=np.float32)
    for i, col in enumerate(niche_cols):
        if col in adata.obs.columns:
            v = adata.obs[col].values.astype(float)
            niche[:, i] = (v - v.mean()) / (v.std() + 1e-8)

    x = np.hstack([pca, ct_prop, niche]).astype(np.float32)
    logger.info(f"   Node features: {x.shape} "
                f"(PCA:{pca_dim} + CT:{ct_prop.shape[1]} + Niche:{niche.shape[1]})")

    # ============ COARSE PROPORTIONS ============
    # [BUG-2] FIX: adata.obsm'dan al, sütun topla
    coarse_props = np.zeros((n_spots, 4), dtype=np.float32)
    for i, ct in enumerate(ct_names):
        group = get_coarse_group(ct)
        if group is not None:
            coarse_idx = coarse_map[group]
            coarse_props[:, coarse_idx] += ct_df[ct].values

    tumor_indices  = [i for i, n in enumerate(ct_names) if get_coarse_group(n) == 'Tumor']
    myeloid_indices= [i for i, n in enumerate(ct_names) if get_coarse_group(n) == 'Myeloid']

    # ============ EDGE INDEX (kNN spatial + reciprocal) ============
    # [BUG-6] Her kenar için ters yönü de oluştur (L-R yönlülük)
    coords = adata.obsm['spatial'].astype(np.float32)
    tree = cKDTree(coords)
    dists, idxs = tree.query(coords, k=k_neighbors + 1)

    src_list, dst_list, dist_list = [], [], []
    seen = set()
    for i in range(n_spots):
        for j in range(1, k_neighbors + 1):
            nb = idxs[i, j]
            d  = dists[i, j]
            # İleri kenar
            if (i, nb) not in seen:
                src_list.append(i);  dst_list.append(nb); dist_list.append(d)
                seen.add((i, nb))
            # [BUG-6] Geri kenar (reciprocal)
            if (nb, i) not in seen:
                src_list.append(nb); dst_list.append(i);  dist_list.append(d)
                seen.add((nb, i))

    src = np.array(src_list, dtype=np.int64)
    dst = np.array(dst_list, dtype=np.int64)
    edge_index = torch.tensor([src, dst], dtype=torch.long)
    spatial_dist = np.array(dist_list, dtype=np.float32)
    n_edges = len(src_list)
    logger.info(f"   Edges: {n_edges} (k={k_neighbors}, bidirectional)")

    med = np.median(spatial_dist) + 1e-8
    spatial_prox = np.exp(-spatial_dist / med).reshape(-1, 1)

    # ============ EDGE ATTRIBUTES — L-R ============
    lr_raw = np.zeros((n_edges, len(LR_PAIRS)), dtype=np.float32)
    lr_found = 0
    for p_idx, (lig, rec, _) in enumerate(LR_PAIRS):
        le, re = get_gene(lig), get_gene(rec)
        if le is not None and re is not None:
            lr_found += 1
            lr_raw[:, p_idx] = le[src] * re[dst]

    lr_scores = np.log1p(lr_raw)
    lr_mean = lr_scores.mean(axis=0, keepdims=True)
    lr_std  = lr_scores.std(axis=0, keepdims=True) + 1e-8
    lr_scores = (lr_scores - lr_mean) / lr_std
    logger.info(f"   L-R pairs: {lr_found}/{len(LR_PAIRS)} found")

    # Hücre-tip uyumsuzluğu (heterojenlik)
    cell_compat = np.zeros((n_edges, 1), dtype=np.float32)
    for e_idx in range(n_edges):
        pi = coarse_props[src[e_idx]]
        pj = coarse_props[dst[e_idx]]
        cos = np.dot(pi, pj) / (np.linalg.norm(pi) * np.linalg.norm(pj) + 1e-8)
        cell_compat[e_idx] = 1.0 - cos

    edge_attr = np.hstack([spatial_prox, lr_scores, cell_compat]).astype(np.float32)
    logger.info(f"   Edge attr: {edge_attr.shape}")

    # ============ LABELS ============
    y = ct_prop.astype(np.float32)

    # Zone pseudo-labels (z-score per gene, then softmax)
    zone_scores = np.zeros((n_spots, len(ZONE_NAMES)), dtype=np.float32)
    for z_idx, zone in enumerate(ZONE_NAMES):
        sig_genes = ZONE_SIGNATURES[zone]
        valid = [get_gene(g) for g in sig_genes if get_gene(g) is not None]
        if valid:
            zscored = [(g - g.mean()) / (g.std() + 1e-8) for g in valid]
            zone_scores[:, z_idx] = np.mean(zscored, axis=0)

    zone_exp  = np.exp(zone_scores - zone_scores.max(axis=1, keepdims=True))
    zone_probs = zone_exp / (zone_exp.sum(axis=1, keepdims=True) + 1e-8)

    # TCGA survival (varsa)
    survival_months = np.zeros(n_spots, dtype=np.float32)
    tcga_risk       = np.zeros(n_spots, dtype=np.float32)
    if 'survival_months' in adata.obs.columns:
        survival_months = adata.obs['survival_months'].values.astype(np.float32)
    if 'tcga_risk' in adata.obs.columns:
        tcga_risk = adata.obs['tcga_risk'].values.astype(np.float32)

    # Pseudotime / velocity (scVelo opsiyonel)
    pseudotime = np.zeros(n_spots, dtype=np.float32)
    vec_x = np.zeros(n_spots, dtype=np.float32)
    vec_y = np.zeros(n_spots, dtype=np.float32)
    if 'velocity_pseudotime' in adata.obs.columns:
        pt = adata.obs['velocity_pseudotime'].values.astype(np.float32)
        pt = (pt - pt.min()) / (pt.max() - pt.min() + 1e-8)
        pseudotime = pt
    if 'X_velocity_umap' in adata.obsm:
        vel = adata.obsm['X_velocity_umap'].astype(np.float32)
        vec_x = vel[:, 0]
        vec_y = vel[:, 1] if vel.shape[1] > 1 else np.zeros(n_spots, dtype=np.float32)

    # ============ SPLIT ============
    rng = np.random.RandomState(42)
    idx = rng.permutation(n_spots)
    n_tr, n_va = int(0.7 * n_spots), int(0.15 * n_spots)
    train_mask = torch.zeros(n_spots, dtype=torch.bool)
    val_mask   = torch.zeros(n_spots, dtype=torch.bool)
    test_mask  = torch.zeros(n_spots, dtype=torch.bool)
    train_mask[idx[:n_tr]]           = True
    val_mask[idx[n_tr:n_tr + n_va]]  = True
    test_mask[idx[n_tr + n_va:]]     = True
    logger.info(f"   Split: Train={train_mask.sum()}, Val={val_mask.sum()}, Test={test_mask.sum()}")

    data = Data(
        x              = torch.tensor(x),
        edge_index     = edge_index,
        edge_attr      = torch.tensor(edge_attr),
        y              = torch.tensor(y),
        zone_y         = torch.tensor(zone_probs),
        coarse_y       = torch.tensor(coarse_props),   # [BUG-2] artık doğru kaynak
        survival_y     = torch.tensor(survival_months),
        tcga_risk_y    = torch.tensor(tcga_risk),
        pseudotime     = torch.tensor(pseudotime),
        vec_x          = torch.tensor(vec_x),
        vec_y          = torch.tensor(vec_y),
        pos            = torch.tensor(coords),
        train_mask     = train_mask,
        val_mask       = val_mask,
        test_mask      = test_mask,
    )
    data.ct_names       = ct_names
    data.ct_to_coarse_idx = ct_to_coarse_idx
    data.tumor_indices  = tumor_indices
    data.myeloid_indices= myeloid_indices
    data.pca_dim        = pca_dim           # [BUG-5] counterfactual için
    data.src_arr        = src               # JSON export için
    data.dst_arr        = dst

    logger.info(f"   ✅ {data}")
    return data


# ============================================================
# MODEL v3
# ============================================================
class GlioCartographyGNN(nn.Module):
    """
    Multi-task GNN:
      - Cell-type proportion prediction (MSE)
      - Zone classification (KL-div)
      - Survival regression (MSE) [FEAT-2]
      - Drug score (L-R aktivite bazlı MLP) [FEAT-1]
      - Contrastive embedding (InfoNCE)
    """
    def __init__(self, in_ch: int, edge_dim: int, n_ct: int, n_zones: int,
                 hidden: int = 128, heads: int = 4, drop: float = 0.3,
                 n_gat: int = 2, n_sage: int = 1, use_transformer: bool = False):
        super().__init__()
        self.drop = drop
        self.use_transformer = use_transformer
        
        # Save variables for backward-compatible dynamic GATv1 re-initialization
        self.gats_in_dim = hidden
        self.gats_out_dim = hidden // heads
        self.gats_heads = heads
        self.gats_edge_dim = hidden

        self.node_enc = nn.Sequential(
            nn.Linear(in_ch, hidden), nn.ELU(), nn.Dropout(drop))
        self.edge_enc = nn.Sequential(
            nn.Linear(edge_dim, 64), nn.ELU(), nn.Dropout(drop),
            nn.Linear(64, hidden))

        # GAT layers
        self.gats      = nn.ModuleList()
        self.gat_norms = nn.ModuleList()
        for _ in range(n_gat):
            self.gats.append(GATv2Conv(
                hidden, hidden // heads, heads=heads,
                edge_dim=hidden, dropout=drop,
                concat=True, add_self_loops=True))
            self.gat_norms.append(BatchNorm(hidden))

        # SAGE layers
        self.sages      = nn.ModuleList()
        self.sage_norms = nn.ModuleList()
        for _ in range(n_sage):
            self.sages.append(SAGEConv(hidden, hidden))
            self.sage_norms.append(BatchNorm(hidden))

        # Opsiyonel long-range
        if use_transformer:
            self.trans      = TransformerConv(hidden, hidden // 2, heads=2, concat=True)
            self.trans_norm = BatchNorm(hidden)

        # Task heads
        self.ct_head = nn.Sequential(
            nn.Linear(hidden, 64), nn.ELU(), nn.Dropout(drop),
            nn.Linear(64, n_ct))

        self.zone_head = nn.Sequential(
            nn.Linear(hidden, 64), nn.ELU(), nn.Dropout(drop),
            nn.Linear(64, n_zones))

        # [FEAT-2] Survival regression head
        self.survival_head = nn.Sequential(
            nn.Linear(hidden, 32), nn.ELU(), nn.Dropout(drop),
            nn.Linear(32, 1))

        # [FEAT-1] Drug score head (0–1 çıktı için Sigmoid)
        self.drug_head = nn.Sequential(
            nn.Linear(hidden, 32), nn.ELU(), nn.Dropout(drop),
            nn.Linear(32, 1), nn.Sigmoid())

        self.proj = nn.Linear(hidden, 32)   # Contrastive projection

    def forward(self, data: Data, return_attention: bool = False):
        x       = self.node_enc(data.x)
        edge_emb= self.edge_enc(data.edge_attr)
        ei      = data.edge_index

        attn_weights_per_layer = []

        for gat, norm in zip(self.gats, self.gat_norms):
            res = x
            if return_attention:
                x, (attn_ei, aw) = gat(x, ei, edge_attr=edge_emb,
                                        return_attention_weights=True)
                attn_weights_per_layer.append((attn_ei, aw))
            else:
                x = gat(x, ei, edge_attr=edge_emb)
            x = norm(x)
            x = F.elu(x)
            x = F.dropout(x, self.drop, self.training)
            x = x + res

        for sage, norm in zip(self.sages, self.sage_norms):
            res = x
            x   = sage(x, ei)
            x   = norm(x)
            x   = F.elu(x)
            x   = F.dropout(x, self.drop, self.training)
            x   = x + res

        if self.use_transformer:
            res = x
            x   = self.trans(x, ei)
            x   = self.trans_norm(x)
            x   = F.elu(x)
            x   = F.dropout(x, self.drop, self.training)
            x   = x + res

        ct       = F.softmax(self.ct_head(x), dim=-1)
        zone     = self.zone_head(x)
        survival = self.survival_head(x).squeeze(-1)
        drug_sc  = self.drug_head(x).squeeze(-1)
        emb      = self.proj(x)

        if return_attention:
            return ct, zone, survival, drug_sc, emb, attn_weights_per_layer
        return ct, zone, survival, drug_sc, emb

    def load_state_dict(self, state_dict, strict=True):
        has_gatv1 = False
        for key in state_dict.keys():
            if "gats" in key and ("lin_src" in key or "lin_dst" in key or "att_src" in key or "att_dst" in key):
                has_gatv1 = True
                break
                
        if has_gatv1:
            logger.info("⚠️ Eski GATConv (v1) checkpoint'i tespit edildi. Model GATConv layer'ları ile re-initialize ediliyor...")
            from torch_geometric.nn import GATConv
            self.gats = nn.ModuleList()
            for _ in range(len(self.gat_norms)):
                self.gats.append(GATConv(
                    self.gats_in_dim, self.gats_out_dim, heads=self.gats_heads,
                    edge_dim=self.gats_edge_dim, dropout=self.drop,
                    concat=True, add_self_loops=True
                ))
                
        return super().load_state_dict(state_dict, strict=strict)


# ============================================================
# LOSS v3 — InfoNCE diyagonal fix dahil
# ============================================================
def compute_loss(ct_pred, ct_true,
                 zone_logits, zone_true,
                 survival_pred, survival_true,
                 emb, coarse_y, mask, edge_index,
                 lam_ct: float = 1.0, lam_zone: float = 0.5,
                 lam_contr: float = 0.3, lam_smooth: float = 0.2,
                 lam_surv: float = 0.3,
                 survival_mean: float = 0.0, survival_std: float = 1.0):

    m = mask

    # L1: Cell-type MSE
    loss_ct = F.mse_loss(ct_pred[m], ct_true[m])

    # L2: Zone KL-divergence
    loss_zone = F.kl_div(
        F.log_softmax(zone_logits[m], dim=-1),
        zone_true[m], reduction='batchmean')

    # L3: Survival MSE [FEAT-2]
    if survival_true[m].abs().sum() > 0:
        surv_norm = (survival_true[m] - survival_mean) / (survival_std + 1e-8)
        loss_surv = F.mse_loss(survival_pred[m], surv_norm)
    else:
        loss_surv = torch.tensor(0.0, device=ct_pred.device)

    # L4: InfoNCE contrastive — [BUG-3] diyagonal çıkarıldı
    loss_contr = torch.tensor(0.0, device=ct_pred.device)
    if m.sum().item() > 20:
        tumor_frac   = coarse_y[m, 0]
        myeloid_frac = coarse_y[m, 1]
        hotspot = tumor_frac * myeloid_frac
        is_hot  = hotspot > hotspot.median()

        if is_hot.sum() > 5 and (~is_hot).sum() > 5:
            e   = F.normalize(emb[m], dim=1)
            sim = torch.mm(e, e.t())          # (N, N)
            temp = 0.1

            labels   = is_hot.float()
            pos_mask = (labels.unsqueeze(1) == labels.unsqueeze(0)).float()
            # [BUG-3] FIX: öz-benzerliği dışla
            eye      = torch.eye(len(e), device=e.device)
            pos_mask = pos_mask - eye
            pos_mask = pos_mask.clamp(min=0)
            neg_mask = 1.0 - pos_mask - eye

            exp_sim  = torch.exp(sim / temp)
            pos_sum  = (exp_sim * pos_mask).sum(dim=1)
            neg_sum  = (exp_sim * neg_mask).sum(dim=1)
            
            # Guard against pos_sum = 0
            valid_mask = pos_sum > 1e-8
            if valid_mask.any():
                loss_contr = -torch.log(pos_sum[valid_mask] / (pos_sum[valid_mask] + neg_sum[valid_mask] + 1e-8)).mean()
            else:
                loss_contr = torch.tensor(0.0, device=ct_pred.device)

    # L5: Spatial smoothness
    s_idx, d_idx = edge_index
    diff         = emb[s_idx] - emb[d_idx]
    loss_smooth  = (diff ** 2).mean()

    total = (lam_ct    * loss_ct    +
             lam_zone  * loss_zone  +
             lam_contr * loss_contr +
             lam_smooth* loss_smooth+
             lam_surv  * loss_surv)

    return total, {
        'ct': loss_ct.item(), 'zone': loss_zone.item(),
        'contr': loss_contr.item(), 'smooth': loss_smooth.item(),
        'surv': loss_surv.item(), 'total': total.item()}


# ============================================================
# TRAINING
# ============================================================
def train_model(data: Data, trial=None, cfg: dict | None = None, epoch_callback=None):
    if cfg is None:
        cfg = {}

    hidden      = cfg.get('hidden', 128)
    heads       = cfg.get('heads', 4)
    drop        = cfg.get('drop', 0.3)
    lr          = cfg.get('lr', 1e-3)
    n_gat       = cfg.get('n_gat', 2)
    n_sage      = cfg.get('n_sage', 1)
    use_trans   = cfg.get('use_transformer', False)
    epochs      = cfg.get('epochs', 300)
    lam_ct      = cfg.get('lam_ct', 1.0)
    lam_zone    = cfg.get('lam_zone', 0.5)
    lam_contr   = cfg.get('lam_contr', 0.3)
    lam_smooth  = cfg.get('lam_smooth', 0.2)
    lam_surv    = cfg.get('lam_surv', 0.3)
    wd          = cfg.get('wd', 1e-4)
    patience    = cfg.get('patience', 40)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Training on device: {device}")
    
    n_ct   = data.y.shape[1]
    n_zones= data.zone_y.shape[1]

    # Pre-calculate global survival mean/std on train mask to prevent target drift
    train_surv = data.survival_y[data.train_mask]
    if train_surv.abs().sum() > 0:
        survival_mean = float(train_surv.mean().item())
        survival_std = float(train_surv.std().item())
    else:
        survival_mean = 0.0
        survival_std = 1.0

    model = GlioCartographyGNN(
        data.x.shape[1], data.edge_attr.shape[1],
        n_ct, n_zones, hidden, heads, drop, n_gat, n_sage, use_trans
    ).to(device)
    data = data.to(device)

    opt   = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=1e-6)

    best_val, best_state = float('inf'), None
    hist = {'train': [], 'val': [], 'comp': []}
    pat_cnt = 0

    for ep in range(1, epochs + 1):
        model.train()
        opt.zero_grad()
        ct_p, zone_p, surv_p, _, emb = model(data)
        loss, comp = compute_loss(
            ct_p, data.y, zone_p, data.zone_y, surv_p, data.survival_y,
            emb, data.coarse_y, data.train_mask, data.edge_index,
            lam_ct, lam_zone, lam_contr, lam_smooth, lam_surv,
            survival_mean=survival_mean, survival_std=survival_std)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step()

        model.eval()
        with torch.no_grad():
            ct_v, zone_v, surv_v, _, emb_v = model(data)
            vloss, _ = compute_loss(
                ct_v, data.y, zone_v, data.zone_y, surv_v, data.survival_y,
                emb_v, data.coarse_y, data.val_mask, data.edge_index,
                lam_ct, lam_zone, lam_contr, lam_smooth, lam_surv,
                survival_mean=survival_mean, survival_std=survival_std)

        hist['train'].append(comp['total'])
        hist['val'].append(vloss.item())
        hist['comp'].append(comp)

        if vloss.item() < best_val:
            best_val  = vloss.item()
            best_state= {k: v.cpu().clone() for k, v in model.state_dict().items()}
            pat_cnt   = 0
        else:
            pat_cnt += 1

        if ep % 50 == 0 or ep == 1:
            logger.info(
                f"   Ep {ep:3d}/{epochs}: T={comp['total']:.4f} "
                f"(CT={comp['ct']:.4f} Z={comp['zone']:.4f} "
                f"C={comp['contr']:.4f} S={comp['smooth']:.4f} "
                f"Surv={comp['surv']:.4f}) | V={vloss.item():.4f}")

        if epoch_callback and (ep % 10 == 0 or ep == 1 or ep == epochs):
            epoch_callback(ep, epochs)

        if pat_cnt >= patience:
            logger.info(f"   ⏹ Early stop @ ep {ep}")
            if epoch_callback:
                epoch_callback(epochs, epochs)  # Send completion on early stop
            break

        if trial:
            trial.report(vloss.item(), ep)
            if trial.should_prune():
                raise optuna.TrialPruned()

    if best_state:
        model.load_state_dict(best_state)
        
    gc.collect()
    return model, hist, best_val


# ============================================================
# OPTUNA
# ============================================================
def objective(trial, data: Data, epoch_callback=None) -> float:
    cfg = {
        'hidden':         trial.suggest_categorical('hidden', [64, 128, 256]),
        'heads':          trial.suggest_categorical('heads', [2, 4]),
        'drop':           trial.suggest_float('drop', 0.1, 0.5),
        'lr':             trial.suggest_float('lr', 5e-4, 1e-2, log=True),
        'n_gat':          trial.suggest_int('n_gat', 1, 3),
        'n_sage':         trial.suggest_int('n_sage', 0, 2),
        'use_transformer':trial.suggest_categorical('use_transformer', [False, True]),
        'lam_ct':         trial.suggest_float('lam_ct', 0.5, 2.0),
        'lam_zone':       trial.suggest_float('lam_zone', 0.1, 1.0),
        'lam_contr':      trial.suggest_float('lam_contr', 0.1, 0.5),
        'lam_smooth':     trial.suggest_float('lam_smooth', 0.05, 0.5),
        'lam_surv':       trial.suggest_float('lam_surv', 0.1, 0.5),
        'wd':             trial.suggest_float('wd', 1e-5, 1e-3, log=True),
        'epochs': 200, 'patience': 30,
    }
    _, _, bv = train_model(data, trial=trial, cfg=cfg, epoch_callback=epoch_callback)
    return bv


# ============================================================
# COUNTERFACTUAL — [BUG-5] ct_start dinamik
# ============================================================
def counterfactual_knockout(model: nn.Module, data: Data,
                             ct_names: list[str], knockout_type: str) -> np.ndarray | None:
    """
    Belirli hücre tipini lokal olarak sıfırlayıp komşuluk ilişkileri (parakrin) boyunca yayılımını simüle et.
    """
    model.eval()
    data_mod = data.clone()
    n_spots = data.x.shape[0]

    # Dinamik offset
    ct_start = data.pca_dim
    ko_indices = [i for i, n in enumerate(ct_names) if knockout_type in n]

    if not ko_indices:
        logger.warning(f"   '{knockout_type}' ct_names içinde bulunamadı")
        return None

    # Hedef hücrelerin yoğun olduğu spotları (lokal müdahale alanı) seç
    # Use adaptive threshold: pick top 5% or top 50 spots, whichever is smaller, but at least 1 spot
    ko_sum = data.x[:, [ct_start + idx for idx in ko_indices]].sum(dim=1)
    min_spots = max(1, min(50, int(0.05 * n_spots)))
    q_val = 1.0 - (min_spots / n_spots)
    q_val = max(0.0, min(1.0, q_val))
    threshold = torch.quantile(ko_sum, q_val)
    mask_abundant = ko_sum >= threshold

    target_spots = torch.where(mask_abundant)[0]
    n_targets = len(target_spots)
    logger.info(f"   Simulating localized intervention on {n_targets} spots for '{knockout_type}'...")

    # Orijinal forward pass
    with torch.no_grad():
        _, zone_orig, _, _, _ = model(data)
        zone_orig = F.softmax(zone_orig, dim=-1)

    # Müdahale: Sadece hedef spotlarda hücre oranlarını sıfırla
    data_mod.x = data_mod.x.clone()
    for idx in ko_indices:
        col = ct_start + idx
        if col < data_mod.x.shape[1]:
            data_mod.x[target_spots, col] = 0.0
        else:
            logger.warning(f"   Knockout index {col} feature dim {data_mod.x.shape[1]} dışında")

    # Ko-müdahale forward pass (GNN message passing parakrin yayılımı yapar)
    with torch.no_grad():
        _, zone_ko, _, _, _ = model(data_mod)
        zone_ko = F.softmax(zone_ko, dim=-1)

    # Parakrin etki analizi (komşuluk analizi)
    edge_index = data.edge_index
    src, dst = edge_index[0], edge_index[1]
    
    src_arr = src.cpu().numpy()
    dst_arr = dst.cpu().numpy()
    target_arr = target_spots.cpu().numpy()
    
    src_in_target = np.isin(src_arr, target_arr)
    dst_in_target = np.isin(dst_arr, target_arr)
    
    # 1-hop komşular: target'tan çıkan ama target olmayan düğümler
    one_hop_arr = np.unique(dst_arr[src_in_target & ~dst_in_target])
    
    # 2-hop komşular: 1-hop'tan çıkan ama target veya 1-hop olmayan düğümler
    if len(one_hop_arr) > 0:
        src_in_one_hop = np.isin(src_arr, one_hop_arr)
        dst_in_one_hop = np.isin(dst_arr, one_hop_arr)
        two_hop_arr = np.unique(dst_arr[src_in_one_hop & ~dst_in_target & ~dst_in_one_hop])
    else:
        two_hop_arr = np.array([], dtype=np.int64)

    delta_zone = zone_ko - zone_orig
    delta_np = delta_zone.cpu().numpy()
    abs_delta = np.abs(delta_np)
    
    target_effect = abs_delta[target_arr].mean() if len(target_arr) > 0 else 0.0
    one_hop_effect = abs_delta[one_hop_arr].mean() if len(one_hop_arr) > 0 else 0.0
    two_hop_effect = abs_delta[two_hop_arr].mean() if len(two_hop_arr) > 0 else 0.0
    
    logger.info(f"   Paracrine propagation effect (Mean Absolute ΔZone):")
    logger.info(f"     Target spots    : {target_effect:.6f} (Direct Intervention)")
    logger.info(f"     1-hop Neighbors : {one_hop_effect:.6f} (Paracrine Hop 1)")
    logger.info(f"     2-hop Neighbors : {two_hop_effect:.6f} (Paracrine Hop 2)")

    return delta_np


# ============================================================
# L-R & GENE REGULATION COUNTERFACTUAL SIMULATORS
# ============================================================
def counterfactual_lr_blockade(model: nn.Module, data: Data,
                              lr_names: list[str], lr_target: str,
                              inhibition_rate: float = 1.0) -> np.ndarray | None:
    """
    Simulate target L-R ligand-receptor pair blockade on the GNN graph.
    Modifies edge_attr columns representing the target pair and evaluates predicted zone delta.
    """
    model.eval()
    data_mod = data.clone()
    
    # 1. Find the index of the target L-R pair
    lr_idx = -1
    # Check both case-sensitive and case-insensitive
    target_clean = lr_target.replace('-', '_').lower()
    for i, name in enumerate(lr_names):
        name_clean = name.replace('-', '_').lower()
        if name_clean == target_clean:
            lr_idx = i
            break
            
    if lr_idx == -1:
        logger.warning(f"   '{lr_target}' lr_names içinde bulunamadı")
        return None
            
    # 2. Modify edge_attr column corresponding to this L-R pair
    # In build_graph_data: edge_attr = np.hstack([spatial_prox, lr_scores, cell_compat])
    # The L-R scores start at index 1 and span len(LR_PAIRS) columns.
    col_idx = 1 + lr_idx
    
    if col_idx >= data_mod.edge_attr.shape[1]:
        logger.warning(f"   L-R index {col_idx} edge_attr dim {data_mod.edge_attr.shape[1]} dışında")
        return None
        
    # Original forward pass
    with torch.no_grad():
        _, zone_orig, _, _, _ = model(data)
        zone_orig = F.softmax(zone_orig, dim=-1)
        
    # Perform blockade: set expression of target L-R pair to its minimum value across all edges
    # (representing total block) or reduce it proportionally
    current_col = data_mod.edge_attr[:, col_idx].clone()
    min_val = float(torch.min(current_col))
    
    # Apply inhibition
    data_mod.edge_attr = data_mod.edge_attr.clone()
    data_mod.edge_attr[:, col_idx] = current_col * (1.0 - inhibition_rate) + min_val * inhibition_rate
    
    # Counterfactual forward pass
    with torch.no_grad():
        _, zone_ko, _, _, _ = model(data_mod)
        zone_ko = F.softmax(zone_ko, dim=-1)
        
    delta_zone = zone_ko - zone_orig
    return delta_zone.cpu().numpy()


def counterfactual_gene_regulation(model: nn.Module, data: Data,
                                  lr_names: list[str], lr_pairs: list[tuple[str, str, str]],
                                  gene_target: str, reg_type: str = 'knockdown',
                                  rate: float = 1.0) -> np.ndarray | None:
    """
    Simulate target gene regulation (knockdown or overexpression) on the GNN graph.
    Modifies edge_attr columns representing all L-R pairs containing the target gene.
    """
    model.eval()
    data_mod = data.clone()
    
    # 1. Find all L-R pairs containing the target gene
    affected_indices = []
    gene_target_lower = gene_target.lower()
    for i, (lig, rec, _) in enumerate(lr_pairs):
        if lig.lower() == gene_target_lower or rec.lower() == gene_target_lower:
            affected_indices.append(i)
            
    if not affected_indices:
        logger.warning(f"   Gene '{gene_target}' L-R kataloğunda bulunamadı")
        return None
        
    logger.info(f"   Simulating {reg_type} of '{gene_target}' on {len(affected_indices)} affected L-R axes...")
        
    # Original forward pass
    with torch.no_grad():
        _, zone_orig, _, _, _ = model(data)
        zone_orig = F.softmax(zone_orig, dim=-1)
        
    # 2. Modify edge_attr columns for all affected L-R pairs
    data_mod.edge_attr = data_mod.edge_attr.clone()
    for lr_idx in affected_indices:
        col_idx = 1 + lr_idx
        if col_idx < data_mod.edge_attr.shape[1]:
            current_col = data_mod.edge_attr[:, col_idx].clone()
            if reg_type == 'knockdown':
                min_val = float(torch.min(current_col))
                # Push values toward the minimum representing suppression
                data_mod.edge_attr[:, col_idx] = current_col * (1.0 - rate) + min_val * rate
            else: # overexpression
                max_val = float(torch.max(current_col))
                # Push values toward the maximum representing activation
                data_mod.edge_attr[:, col_idx] = current_col * (1.0 - rate) + max_val * rate
                
    # Counterfactual forward pass
    with torch.no_grad():
        _, zone_ko, _, _, _ = model(data_mod)
        zone_ko = F.softmax(zone_ko, dim=-1)
        
    delta_zone = zone_ko - zone_orig
    return delta_zone.cpu().numpy()


# ============================================================
# PATHWAY SCORING
# ============================================================
def compute_pathway_scores(adata) -> dict[str, np.ndarray]:
    var_names_lower = {g.lower(): g for g in adata.var_names}
    gene_cache = {}
    def get_gene(name: str):
        name_lower = name.lower()
        if name_lower not in gene_cache:
            exact_name = var_names_lower.get(name_lower)
            if exact_name is not None:
                try:
                    col_idx = adata.var_names.get_loc(exact_name)
                    e = adata.X[:, col_idx]
                except Exception:
                    e = adata[:, exact_name].X
                e = e.toarray().flatten() if hasattr(e, 'toarray') else np.asarray(e).flatten()
                gene_cache[name_lower] = e.astype(np.float32)
            else:
                gene_cache[name_lower] = None
        return gene_cache[name_lower]
    
    pathway_scores = {}
    for path_name, genes in PATHWAY_SIGNATURES.items():
        valid_genes = [get_gene(g) for g in genes if get_gene(g) is not None]
        if valid_genes:
            pathway_scores[path_name] = np.mean(valid_genes, axis=0)
        else:
            pathway_scores[path_name] = np.zeros(adata.n_obs, dtype=np.float32)
    return pathway_scores


# ============================================================
# ATTENTION EXPORT — [BUG-4]
# ============================================================
def export_attention_to_json(model: nn.Module, data: Data, adata,
                              ct_names: list[str],
                              zone_preds: np.ndarray,
                              drug_scores: np.ndarray,
                              survival_preds: np.ndarray,
                              out_path: str,
                              ct_preds: np.ndarray | None = None) -> None:
    """
    [BUG-4] FIX: GATv2 attention weight'lerini hesapla, her spot için
    en yüksek 10 komşuyu JSON'a yaz.
    Frontend spot.edges = {dstId: weight} biçimini bekliyor.
    """
    logger.info("Attention weight'ler export ediliyor...")
    model.eval()

    with torch.no_grad():
        _, _, _, _, _, attn_layers = model(data, return_attention=True)

    # Son GAT katmanının attention weight'lerini kullan
    if not attn_layers:
        logger.warning("   Attention layer bulunamadı")
        return

    attn_ei, aw = attn_layers[-1]
    # aw shape: (n_edges, n_heads) — head ortalaması al
    attn_mean = aw.mean(dim=-1).cpu().numpy()   # (n_edges,)
    attn_src  = attn_ei[0].cpu().numpy()
    attn_dst  = attn_ei[1].cpu().numpy()

    # Spot başına en yüksek 10 bağlantıyı topla
    n_spots    = data.x.shape[0]
    spot_edges: list[dict] = [{} for _ in range(n_spots)]

    for e_idx in range(len(attn_src)):
        si  = int(attn_src[e_idx])
        di  = int(attn_dst[e_idx])
        w   = float(attn_mean[e_idx])
        if di not in spot_edges[si] or spot_edges[si][di] < w:
            spot_edges[si][di] = w

    # En yüksek 10'a kırp
    for si in range(n_spots):
        top10 = dict(sorted(spot_edges[si].items(),
                            key=lambda kv: kv[1], reverse=True)[:10])
        spot_edges[si] = top10

    # Dominant zone, drug tahmini
    zone_argmax = zone_preds.argmax(axis=1)

    # Drug → L-R eşleşmesi (en yüksek L-R bazlı)
    lr_cols_start = 1  # edge_attr: [spatial_prox, lr_scores..., cell_compat]
    lr_cols_end   = 1 + len(LR_PAIRS)

    # Her spot için toplam L-R aktivitesini hesapla (gelen kenar ortalaması)
    spot_lr_sum = np.zeros((n_spots, len(LR_PAIRS)), dtype=np.float32)
    spot_lr_cnt = np.zeros(n_spots, dtype=np.int32)
    ea = data.edge_attr.cpu().numpy()
    edge_index_np = data.edge_index.cpu().numpy()
    for e_idx in range(ea.shape[0]):
        di = int(edge_index_np[1, e_idx])
        spot_lr_sum[di] += ea[e_idx, lr_cols_start:lr_cols_end]
        spot_lr_cnt[di] += 1
    spot_lr_avg = spot_lr_sum / (spot_lr_cnt[:, None] + 1e-8)

    # Pathway scores
    pathway_scores = compute_pathway_scores(adata)

    # Build attention map to get GNN weights on edges
    attn_map = {}
    for e_idx in range(len(attn_src)):
        si = int(attn_src[e_idx])
        di = int(attn_dst[e_idx])
        w = float(attn_mean[e_idx])
        if (si, di) not in attn_map or attn_map[(si, di)] < w:
            attn_map[(si, di)] = w

    # Calculate global cell-cell communication
    cell_cell_communication = {}
    n_ct = len(ct_names)
    src_nodes = data.src_arr if hasattr(data, 'src_arr') else data.edge_index[0].cpu().numpy()
    dst_nodes = data.dst_arr if hasattr(data, 'dst_arr') else data.edge_index[1].cpu().numpy()
    W_edges = np.array([attn_map.get((u, v), 0.0) for u, v in zip(src_nodes, dst_nodes)], dtype=np.float32)
    
    if ct_preds is not None:
        y_np = ct_preds
    else:
        y_np = data.y.cpu().numpy() if isinstance(data.y, torch.Tensor) else data.y

    # Helper function to load genes dynamically in export
    var_names_lower = {g.lower(): g for g in adata.var_names}
    gene_cache = {}
    def get_gene(name: str):
        name_lower = name.lower()
        if name_lower not in gene_cache:
            exact_name = var_names_lower.get(name_lower)
            if exact_name is not None:
                try:
                    col_idx = adata.var_names.get_loc(exact_name)
                    e = adata.X[:, col_idx]
                except Exception:
                    e = adata[:, exact_name].X
                e = e.toarray().flatten() if hasattr(e, 'toarray') else np.asarray(e).flatten()
                gene_cache[name_lower] = e.astype(np.float32)
            else:
                gene_cache[name_lower] = None
        return gene_cache[name_lower]

    for p_idx, (lig, rec, _) in enumerate(LR_PAIRS):
        lr_key = f"{lig.upper()}-{rec.upper()}"
        le = get_gene(lig)
        re = get_gene(rec)
        if le is not None and re is not None:
            lr_edges = np.log1p(le[src_nodes] * re[dst_nodes])
            weight_e = W_edges * lr_edges
            
            try:
                sender_ct = y_np[src_nodes]
                receiver_ct = y_np[dst_nodes]
                comm_matrix = np.einsum('ei,ej,e->ij', sender_ct, receiver_ct, weight_e)
            except Exception as e_einsum:
                comm_matrix = np.zeros((n_ct, n_ct), dtype=np.float32)
                for A_idx in range(n_ct):
                    for B_idx in range(n_ct):
                        val = np.sum(y_np[src_nodes, A_idx] * y_np[dst_nodes, B_idx] * weight_e)
                        comm_matrix[A_idx, B_idx] = float(val)
            
            cell_cell_communication[lr_key] = {
                f"{ct_names[A]}->{ct_names[B]}": float(comm_matrix[A, B])
                for A in range(n_ct) for B in range(n_ct)
            }

    # Zonal contrast
    zonal_contrast = {
        "pathways": {},
        "lr_pairs": {}
    }
    zone_weight_sums = zone_preds.sum(axis=0)  # (n_zones,)
    for z_idx, zone_name in enumerate(ZONE_NAMES):
        w_sum = zone_weight_sums[z_idx] + 1e-8
        
        # Pathway scores
        zonal_contrast["pathways"][zone_name] = {}
        for path_name, p_scores in pathway_scores.items():
            weighted_val = np.sum(zone_preds[:, z_idx] * p_scores) / w_sum
            zonal_contrast["pathways"][zone_name][path_name] = float(weighted_val)
            
        # L-R activities
        zonal_contrast["lr_pairs"][zone_name] = {}
        for p_idx, (lig, rec, _) in enumerate(LR_PAIRS):
            lr_key = f"{lig.upper()}-{rec.upper()}"
            weighted_val = np.sum(zone_preds[:, z_idx] * spot_lr_avg[:, p_idx]) / w_sum
            zonal_contrast["lr_pairs"][zone_name][lr_key] = float(weighted_val)

    coords = data.pos.cpu().numpy()

    spots_out = []
    for si in range(n_spots):
        # Dominant L-R
        top_lr_idx  = int(spot_lr_avg[si].argmax())
        top_lr_pair = LR_PAIRS[top_lr_idx]
        lr_key      = f"{top_lr_pair[0].upper()}-{top_lr_pair[1].upper()}"

        # Drug mapping
        drug_entry = GBM_DRUG_DB.get(lr_key, None)
        drug_name  = drug_entry['drug'] if drug_entry else "N/A"
        drug_mech  = drug_entry['mechanism'] if drug_entry else "N/A"

        # L-R dict (üst 5)
        lr_dict = {}
        top5_idx = spot_lr_avg[si].argsort()[::-1][:5]
        for p_idx in top5_idx:
            pair  = LR_PAIRS[p_idx]
            k     = f"{pair[0].upper()}-{pair[1].upper()}"
            lr_dict[k] = float(np.clip(spot_lr_avg[si, p_idx], 0, None))

        # CT dict
        ct_pred_row = {}
        if hasattr(data, 'ct_names'):
            for ci, cn in enumerate(data.ct_names):
                ct_pred_row[cn] = float(y_np[si, ci]) if y_np is not None else 0.0

        # Zone dict
        zone_dict = {}
        for zi, zn in enumerate(ZONE_NAMES):
            zone_dict[zn] = float(zone_preds[si, zi])

        spot_record = {
            "id": si,
            "x": float(coords[si, 0]),
            "y": float(coords[si, 1]),
            "ct": ct_pred_row,
            "zones": zone_dict,
            "lr": lr_dict,
            "pathways": {path_name: float(pathway_scores[path_name][si]) for path_name in pathway_scores},
            "drug": drug_name,
            "drug_score": float(drug_scores[si]),
            "drug_target": lr_key,
            "drug_lr_basis": lr_key,
            "drug_status": "Klinik Aşama",
            "tcga_risk": float(np.clip(survival_preds[si], 0, 1)),
            "survival_months": float(max(0.0, survival_preds[si] * 20)),
            "pseudotime": float(data.pseudotime[si]) if hasattr(data, 'pseudotime') else 0.0,
            "vec_x": float(data.vec_x[si]) if hasattr(data, 'vec_x') else 0.0,
            "vec_y": float(data.vec_y[si]) if hasattr(data, 'vec_y') else 0.0,
            "edges": {str(k): round(float(v), 5)
                      for k, v in spot_edges[si].items()},   # [BUG-4]
            "simulated": False,
        }
        spots_out.append(spot_record)

    out = {
        "metadata": {
            "version": "3.0",
            "n_spots": n_spots,
            "zones": ZONE_NAMES,
            "ct_names": ct_names,
            "lr_pairs": [f"{l}-{r}" for l, r, _ in LR_PAIRS],
        },
        "spots": spots_out,
        "cell_cell_communication": cell_cell_communication,
        "zonal_contrast": zonal_contrast
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

    logger.info(f"   ✅ JSON export: {out_path} ({n_spots} spot)")

    # ── Write lr_detailed_summary.json ──
    try:
        mean_intensities = spot_lr_avg.mean(axis=0)
        lr_detailed = []
        for p_idx, (lig, rec, cat) in enumerate(LR_PAIRS):
            lr_key = f"{lig.upper()}-{rec.upper()}"
            drug_entry = GBM_DRUG_DB.get(lr_key, None)
            drug_name = drug_entry['drug'] if drug_entry else "Yok / Araştırma Safhası"
            drug_mech = drug_entry['mechanism'] if drug_entry else "—"
            lr_detailed.append({
                "pair": lr_key,
                "ligand": lig.upper(),
                "receptor": rec.upper(),
                "category": cat.capitalize(),
                "mean_intensity": float(np.clip(mean_intensities[p_idx], 0, None)),
                "drug": drug_name,
                "drug_mechanism": drug_mech
            })
        
        # Sort by mean_intensity descending
        lr_detailed.sort(key=lambda x: x["mean_intensity"], reverse=True)
        
        lr_summary_path = Path(out_path).parent / "lr_detailed_summary.json"
        with open(lr_summary_path, 'w', encoding='utf-8') as f:
            json.dump(lr_detailed, f, ensure_ascii=False, indent=2)
        logger.info(f"   ✅ L-R detailed summary export: {lr_summary_path}")
    except Exception as e_lr_sum:
        logger.warning(f"   L-R detailed summary oluşturulamadı: {e_lr_sum}")


# ============================================================
# MAIN
# ============================================================
def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    logger.info("=" * 70)
    logger.info("GLIO-CARTOGRAPHY — GNN Training Pipeline v3.0")
    logger.info("=" * 70)

    # ── Reproducibility seeds ─────────────────────────────────────
    torch.manual_seed(42)
    np.random.seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Running main on device: {device}")

    logger.info("1. Veri yükleniyor...")
    if not os.path.exists(SPATIAL_PATH):
        exit_with_error(f"Spatial deconvolution data not found at: {SPATIAL_PATH}. Stage 2 tamamlandı mı?")
    adata = ad.read_h5ad(SPATIAL_PATH)

    logger.info("2. Graph oluşturuluyor...")
    data    = build_graph_data(adata, k_neighbors=6)
    ct_names= data.ct_names

    # ── Optuna ──────────────────────────────────────────────
    logger.info("3. Optuna hiperparametre araması (2 trial)...")
    if optuna is None:
        exit_with_error("Optuna kütüphanesi yüklü değil! Lütfen 'pip install optuna' ile kurun.")
        
    study = optuna.create_study(
        direction='minimize', study_name='glio_gnn_v3',
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=30))
    study.optimize(lambda t: objective(t, data),
                   n_trials=2, show_progress_bar=True)

    bp = study.best_params
    logger.info(f"\n   ✅ Optuna best val: {study.best_value:.4f}")
    for k, v in bp.items():
        logger.info(f"     {k}: {v}")

    # ── Final Eğitim ────────────────────────────────────────
    logger.info("\n4. Final model eğitimi (500 epoch)...")
    final_cfg          = {**bp, 'epochs': 500, 'patience': 50}
    model, hist, _     = train_model(data, cfg=final_cfg)

    # ── Test ────────────────────────────────────────────────
    logger.info("\n5. Test değerlendirmesi...")
    model = model.to(device)
    data = data.to(device)
    model.eval()
    with torch.no_grad():
        ct_pred, zone_pred, surv_pred, drug_pred, emb = model(data)

    test_mse = F.mse_loss(ct_pred[data.test_mask],
                          data.y[data.test_mask]).item()
    logger.info(f"   Test CT MSE: {test_mse:.6f}")

    ct_p_np = ct_pred[data.test_mask].cpu().numpy()
    ct_t_np = data.y[data.test_mask].cpu().numpy()
    corrs   = {}
    logger.info("   Per-celltype korelasyonlar:")
    for i, ct in enumerate(ct_names):
        pred_vec = ct_p_np[:, i]
        true_vec = ct_t_np[:, i]
        # Guard against zero-variance to prevent Pearson/Spearman correlation exceptions
        if np.std(pred_vec) < 1e-8 or np.std(true_vec) < 1e-8:
            logger.warning(f"     {ct:25s}: Pearson/Spearman hesaplanamadı — sıfır/sabit varyans.")
            corrs[ct] = {'pearson_r': 0.0, 'spearman_r': 0.0}
            continue

        try:
            r,  p  = pearsonr(pred_vec, true_vec)
            rs, ps = spearmanr(pred_vec, true_vec)
            r = r if np.isfinite(r) else 0.0
            rs = rs if np.isfinite(rs) else 0.0
            p = p if np.isfinite(p) else 1.0
            corrs[ct] = {'pearson_r': round(float(r), 4),
                         'spearman_r': round(float(rs), 4)}
            sig = "✅" if p < 0.05 else "⚠️"
            logger.info(f"     {ct:25s}: Pearson r={r:.4f} | Spearman ρ={rs:.4f} {sig}")
        except Exception as e_corr:
            logger.warning(f"     {ct:25s}: Korelasyon hatası ({e_corr})")
            corrs[ct] = {'pearson_r': 0.0, 'spearman_r': 0.0}

    # ── Counterfactual ───────────────────────────────────────
    logger.info("\n6. Counterfactual simülasyonlar...")
    for ko_type in ['TAM', 'Tumor_MES', 'T_Cell']:
        delta = counterfactual_knockout(model, data, ct_names, ko_type)
        if delta is not None:
            logger.info(f"   {ko_type} kaldırıldığında zone değişimleri:")
            for z_idx, zn in enumerate(ZONE_NAMES):
                logger.info(f"     {zn:35s}: Δ = {delta[:, z_idx].mean():+.4f}")

    # ── Additional Counterfactual blockade and regulation simulations ──
    logger.info("\n6b. L-R blockade ve Gen Regülasyonu simülasyonları...")
    lr_names = [f"{l}-{r}" for l, r, _ in LR_PAIRS]
    delta_lr = counterfactual_lr_blockade(model, data, lr_names, "VEGFA-KDR", inhibition_rate=1.0)
    if delta_lr is not None:
        logger.info("   VEGFA-KDR bloke edildiğinde ortalama zone değişimleri:")
        for z_idx, zn in enumerate(ZONE_NAMES):
            logger.info(f"     {zn:35s}: Δ = {delta_lr[:, z_idx].mean():+.4f}")
            
    delta_gene = counterfactual_gene_regulation(model, data, lr_names, LR_PAIRS, "EGFR", reg_type="knockdown", rate=1.0)
    if delta_gene is not None:
        logger.info("   EGFR susturulduğunda (knockdown) ortalama zone değişimleri:")
        for z_idx, zn in enumerate(ZONE_NAMES):
            logger.info(f"     {zn:35s}: Δ = {delta_gene[:, z_idx].mean():+.4f}")

    # ── Kayıt ───────────────────────────────────────────────
    logger.info("\n7. Kayıt...")
    zone_np  = F.softmax(zone_pred, dim=-1).cpu().numpy()
    surv_np  = surv_pred.cpu().numpy()
    drug_np  = drug_pred.cpu().numpy()

    torch.save(model.state_dict(), f'{OUT_DIR}/glio_gnn_v3.pt')
    np.save(f'{OUT_DIR}/spatial_embeddings.npy',  emb.cpu().numpy())
    np.save(f'{OUT_DIR}/zone_predictions.npy',    zone_np)
    np.save(f'{OUT_DIR}/celltype_predictions.npy',ct_pred.cpu().numpy())
    np.save(f'{OUT_DIR}/survival_predictions.npy',surv_np)
    np.save(f'{OUT_DIR}/drug_scores.npy',         drug_np)

    # [BUG-4] Attention + full JSON export
    export_attention_to_json(
        model, data, adata, ct_names,
        zone_preds      = zone_np,
        drug_scores     = drug_np,
        survival_preds  = surv_np,
        out_path        = f'{OUT_DIR}/data.json',
        ct_preds        = ct_pred.cpu().numpy()
    )

    summary_info = {
        "best_params": bp,
        "correlations": corrs,
        "test_mse": test_mse,
        "best_val_loss": study.best_value,
        "zones": ZONE_NAMES,
        "ct_names": ct_names,
        "node_dim": data.x.shape[1],
        "edge_dim": data.edge_attr.shape[1]
    }
    with open(f'{OUT_DIR}/gnn_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary_info, f, ensure_ascii=False, indent=2)

    # ── Grafikler ───────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle('GNN Eğitim — v3.0', fontsize=14, fontweight='bold', color='white')

    axes[0].plot(hist['train'], label='Train', color='#E63946', alpha=0.8)
    axes[0].plot(hist['val'],   label='Val',   color='#457B9D', alpha=0.8)
    axes[0].set_xlabel('Epoch', color='white')
    axes[0].set_ylabel('Loss', color='white')
    axes[0].legend(facecolor='#1a1a2e', labelcolor='white')
    axes[0].set_title('Train vs Val Loss', color='white')
    axes[0].set_facecolor('#1a1a2e')
    axes[0].tick_params(colors='white')

    comp_map = [('ct','#E63946'), ('zone','#2A9D8F'),
                ('contr','#F4A261'), ('smooth','#457B9D'), ('surv','#E9C46A')]
    for key, clr in comp_map:
        axes[1].plot([c[key] for c in hist['comp']],
                     label=key.upper(), color=clr, alpha=0.8)
    axes[1].set_xlabel('Epoch', color='white')
    axes[1].set_ylabel('Component', color='white')
    axes[1].legend(facecolor='#1a1a2e', labelcolor='white')
    axes[1].set_title('Loss Bileşenleri', color='white')
    axes[1].set_facecolor('#1a1a2e')
    axes[1].tick_params(colors='white')

    fig.patch.set_facecolor('#0d1117')
    plt.tight_layout()
    fig.savefig(f'{OUT_DIR}/training_history_v3.png',
                dpi=200, facecolor='#0d1117', bbox_inches='tight')
    plt.close()

    logger.info(f"\n✅ GNN v3.0 tamamlandı!")
    logger.info(f"   Model  : {OUT_DIR}/glio_gnn_v3.pt")
    logger.info(f"   JSON   : {OUT_DIR}/data.json")
    logger.info(f"   Özet   : {OUT_DIR}/gnn_summary.json")


if __name__ == "__main__":
    main()