#!/usr/bin/env python3
"""Stage 4: Visualization and Publication Figures"""
import os, sys, json, traceback, tempfile, urllib.request
import ssl

try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass
from pathlib import Path

# ── Set up error handling first so import/initialization errors are cleanly caught as JSON ──
from loguru import logger

def exit_with_error(message):
    logger.error(message)
    print(json.dumps({"stage": "visualization", "status": "error", "message": message}))
    sys.exit(1)

def global_exception_handler(exctype, value, tb):
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    exit_with_error(f"Görselleştirme aşamasında beklenmeyen hata: {value}\n{error_msg}")

sys.excepthook = global_exception_handler

# ── Project Path & PyInstaller Support ───────────────────────
PROJECT_ROOT = Path(os.environ.get(
    "GLIO_PROJECT_ROOT",
    sys._MEIPASS if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent.parent.parent
))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if getattr(sys, 'frozen', False):
    BACKEND_DIR = Path(sys._MEIPASS) / "desktop_app" / "python_backend"
else:
    BACKEND_DIR = Path(__file__).resolve().parent.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ── Path Traversal Security Checks ────────────────────────────
raw_output_dir = os.environ.get("GLIO_OUTPUT_DIR")
if not raw_output_dir:
    exit_with_error("GLIO_OUTPUT_DIR çevre değişkeni eksik.")

OUTPUT_DIR = Path(raw_output_dir).resolve()

def is_relative_to_compat(path: Path, root: Path) -> bool:
    """Geriye dönük uyumlu is_relative_to kontrolü (Python 3.8 desteği)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False

ALLOWED_ROOTS = [Path.home(), Path(tempfile.gettempdir()).resolve()]
if not any(is_relative_to_compat(OUTPUT_DIR, r) for r in ALLOWED_ROOTS):
    exit_with_error("OUTPUT_DIR güvenlik nedeniyle izin verilen dizinler dışında (Ev dizini veya geçici dizinler) olmalıdır.")

PATIENT_ID = os.environ.get("GLIO_PATIENT_ID", "Patient_A")
plot_dpi = int(os.environ.get("GLIO_PLOT_DPI", "200"))
de_method = os.environ.get("GLIO_DE_METHOD", "wilcoxon").lower()  # wilcoxon, t-test, deseq2

def report_progress(percent):
    print(json.dumps({"stage": "visualization", "status": "running", "progress": percent}))

report_progress(5)

# ── Consolidated Imports ─────────────────────────────────────
import numpy as np
import pandas as pd
import gc

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

try:
    from matplotlib import colormaps
    plasma_cmap = colormaps['plasma']
except Exception:
    from matplotlib import cm
    plasma_cmap = cm.get_cmap('plasma')

import anndata as ad
import scanpy as sc
import seaborn as sns
import networkx as nx
from scipy import stats

# Safe PyDESeq2 import
try:
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats
    PYDESEQ2_AVAILABLE = True
except ImportError:
    PYDESEQ2_AVAILABLE = False

# ── Helper Functions ──────────────────────────────────────────
def get_gene_safe(adata_obj, gene_name: str) -> np.ndarray:
    """Büyük/küçük harf varyantlarını dener; bulamazsa sıfır döner."""
    candidates = [gene_name, gene_name.upper(), gene_name.lower(), 
                  gene_name.capitalize(), gene_name.title()]
    for name in candidates:
        if name in adata_obj.var_names:
            try:
                idx = adata_obj.var_names.get_loc(name)
                e = adata_obj.X[:, idx]
                if hasattr(e, 'toarray'):
                    e = e.toarray()
                elif hasattr(e, 'A'):
                    e = e.A
                return np.asarray(e).flatten().astype(np.float32)
            except Exception as e_get:
                logger.debug(f"Gene extraction error for {name}: {e_get}")
                continue
    return np.zeros(adata_obj.n_obs, dtype=np.float32)

def get_gene(adata, name: str) -> np.ndarray:
    """Wrapper function to align with standard calls"""
    return get_gene_safe(adata, name)

def get_celltype_prop(adata_obj, celltype: str) -> np.ndarray:
    """Celltype proportionlarını case-insensitive ve alt string olarak çeker."""
    if 'celltype_proportions' not in adata_obj.obsm:
        return np.ones(adata_obj.n_obs, dtype=np.float32)
    df = adata_obj.obsm['celltype_proportions']
    
    # Adım 1: Tam eşleşme (Tam isim case-insensitive)
    candidates = [celltype, celltype.upper(), celltype.lower(), 
                  celltype.capitalize(), celltype.title()]
    for name in candidates:
        if name in df.columns:
            return df[name].values.astype(np.float32)
    for col in df.columns:
        if col.lower() == celltype.lower():
            return df[col].values.astype(np.float32)
            
    # Adım 2: Alt string eşleşmesi
    for col in df.columns:
        if celltype.lower() in col.lower():
            return df[col].values.astype(np.float32)
            
    return np.ones(adata_obj.n_obs, dtype=np.float32)

def compute_morans_i(x, W):
    """Computes Moran's I spatial autocorrelation metric for a 1D array x given adjacency matrix W."""
    n = len(x)
    x_mean = np.mean(x)
    x_diff = x - x_mean
    denom = np.sum(x_diff ** 2)
    if denom == 0:
        return 0.0
        
    if hasattr(W, "dot"):
        num = float(x_diff.dot(W.dot(x_diff)))
    else:
        num = float(np.dot(x_diff, np.dot(W, x_diff)))
        
    w_sum = W.sum()
    if w_sum == 0:
        return 0.0
        
    return (n / w_sum) * (num / denom)

def compute_cell_communication(adata_obj, sender_type, receiver_type, ligand, receptor):
    """
    CellChat/CellPhoneDB spatial modelini taklit ederek hücresel ve uzaysal
    iletişim skoru (Autocrine + Row-normalized Paracrine) hesaplar.
    """
    prop_sender = get_celltype_prop(adata_obj, sender_type)
    prop_receiver = get_celltype_prop(adata_obj, receiver_type)
    
    expr_ligand = get_gene_safe(adata_obj, ligand)
    expr_receptor = get_gene_safe(adata_obj, receptor)
    
    sender_expr = prop_sender * expr_ligand
    receiver_expr = prop_receiver * expr_receptor
    
    # 1. Autocrine: Aynı spot üzerindeki eş-lokalizasyon (co-localization)
    autocrine = float(np.mean(sender_expr * receiver_expr))
    
    # 2. Paracrine: Komşu spotlar üzerindeki satır-normalizasyonlu uzaysal etkileşim
    paracrine = 0.0
    if 'connectivities' in adata_obj.obsp:
        try:
            import scipy.sparse as sp
            W = adata_obj.obsp['connectivities']
            # Satır-bazlı normalizasyon uygulayarak ortalama paracrine sinyalini hesapla
            row_sums = np.array(W.sum(axis=1)).flatten()
            row_sums = np.where(row_sums == 0, 1.0, row_sums)
            
            if sp.issparse(W):
                D_inv = sp.diags(1.0 / row_sums)
                W_norm = D_inv @ W
                paracrine = float(np.mean(sender_expr * (W_norm @ receiver_expr)))
            else:
                W_norm = W / row_sums[:, None]
                paracrine = float(np.mean(sender_expr * (W_norm @ receiver_expr)))
        except Exception as e_para:
            logger.debug(f"Paracrine hesabı atlandı: {e_para}")
    else:
        logger.debug("   obsp['connectivities'] bulunamadı, paracrine skoru 0 olarak hesaplanıyor.")
            
    return autocrine + paracrine

def permute_communication_score(adata_obj, sender_type, receiver_type, ligand, receptor, observed_score, n_permutations=50):
    """
    Hücre tipi etiketlerini permüte ederek L-R skoru için permütasyon p-değeri (null model) hesaplar.
    """
    if 'celltype_proportions' not in adata_obj.obsm:
        return 1.0
    df = adata_obj.obsm['celltype_proportions'].copy()
    shuffled_adata = adata_obj.copy()
    better_or_equal_count = 0
    
    for _ in range(n_permutations):
        shuffled_df = df.sample(frac=1.0, replace=False).reset_index(drop=True)
        shuffled_df.index = df.index
        shuffled_adata.obsm['celltype_proportions'] = shuffled_df
        
        perm_score = compute_cell_communication(shuffled_adata, sender_type, receiver_type, ligand, receptor)
        if perm_score >= observed_score:
            better_or_equal_count += 1
            
    return (better_or_equal_count + 1) / (n_permutations + 1)

def find_dominant_expressing_celltype(adata_obj, gene_name: str) -> str:
    """Hücre tipi proportion'ları içinde geni en yüksek ifade eden hücre tipini belirler."""
    if 'celltype_proportions' not in adata_obj.obsm:
        return "Tumor_MES"
    df = adata_obj.obsm['celltype_proportions']
    expr = get_gene_safe(adata_obj, gene_name)
    if expr.sum() == 0:
        return list(df.columns)[0] if len(df.columns) > 0 else "Tumor_MES"
    
    best_ct = None
    best_val = -1.0
    for col in df.columns:
        prop = df[col].values.astype(np.float32)
        val = np.mean(prop * expr)
        if val > best_val:
            best_val = val
            best_ct = col
    return best_ct if best_ct else "Tumor_MES"

def fetch_dynamic_lr_pairs(adata_obj, max_pairs=10):
    """
    OmniPath veritabanından dinamik L-R etkileşimlerini çeker.
    Bulunamaması veya çevrimdışı olunması durumunda yerel GBM kataloğuna geri döner.
    """
    curated_pairs = [
        ('VEGFA',  'KDR',    'VEGFA → KDR',   'Tumor_MES', 'Endothelial'),
        ('SPP1',   'CD44',   'SPP1 → CD44',   'TAM',       'Tumor_MES'),
        ('CD274',  'PDCD1',  'PD-L1 → PD-1',  'TAM',       'T_Cell'),
        ('MIF',    'CD74',   'MIF → CD74',    'Microglia', 'Tumor_MES'),
        ('CXCL12', 'CXCR4',  'CXCL12 → CXCR4','Tumor_MES', 'T_Cell'),
        ('IL10',   'IL10RA', 'IL-10 → IL-10RA','TAM',      'T_Cell'),
        ('TGFB1',  'TGFBR1', 'TGFβ1 → TGFβR1','Tumor_MES', 'Tumor_MES'),
        ('EGF',    'EGFR',   'EGF → EGFR',    'Tumor_MES', 'Tumor_MES'),
    ]
    
    url = "https://omnipathdb.org/interactions?datasets=ligrecextra&format=json&organisms=9606"
    try:
        logger.info("🌐 Dinamik L-R çiftleri OmniPath veritabanından indiriliyor...")
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3.0) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        online_pairs = []
        for item in data:
            source = item.get("source_genesymbol")
            target = item.get("target_genesymbol")
            if source and target and source in adata_obj.var_names and target in adata_obj.var_names:
                sender = find_dominant_expressing_celltype(adata_obj, source)
                receiver = find_dominant_expressing_celltype(adata_obj, target)
                online_pairs.append((source, target, f"{source} → {target}", sender, receiver))
                if len(online_pairs) >= max_pairs:
                    break
                    
        if len(online_pairs) >= 5:
            logger.info(f"   OmniPath'ten {len(online_pairs)} aktif L-R çifti başarıyla çekildi.")
            return online_pairs
    except Exception as e_fetch:
        logger.warning(f"OmniPath L-R çiftleri indirilemedi ({e_fetch}). Yerel GBM kataloğu kullanılıyor.")
        
    return curated_pairs

def run_volcano_differential_testing(adata_work, group1_mask, group2_mask, method="wilcoxon"):
    """
    İki grup arasında diferansiyel gen ifadesi testi yapar.
    Metotlar: 'wilcoxon' (Varsayılan), 't-test', veya 'deseq2' (PyDESeq2 kuruluysa).
    """
    genes_to_test = adata_work.var_names
    results = []
    
    if method == "deseq2" and PYDESEQ2_AVAILABLE:
        try:
            logger.info("   PyDESeq2 diferansiyel analizi çalıştırılıyor...")
            logger.warning("   DESeq2 için log1p-geri-dönüşüm varsayılıyor. Veri farklı normalleştirilmişse sonuçlar güvenilmez olabilir.")
            X_all = adata_work.X
            X_dense = X_all.toarray() if hasattr(X_all, 'toarray') else np.asarray(X_all)
            
            # total_counts varsa kullan, yoksa 10000 varsay
            total_counts = adata_work.obs['total_counts'].values if 'total_counts' in adata_work.obs else 10000.0
            if np.isscalar(total_counts):
                total_counts = np.full(adata_work.n_obs, total_counts)
            
            # Log1p normalized değerlerden pseudo-counts oluştur
            counts_approx = np.round((np.exp(X_dense) - 1.0) * (total_counts[:, None] / 10000.0))
            counts_approx = np.clip(counts_approx, 0, None).astype(int)
            
            # Metadata & design matrix
            design_df = pd.DataFrame(index=adata_work.obs_names)
            design_df['condition'] = 'other'
            design_df.loc[group1_mask, 'condition'] = 'group1'
            design_df.loc[group2_mask, 'condition'] = 'group2'
            
            keep_spots = group1_mask | group2_mask
            counts_df = pd.DataFrame(counts_approx[keep_spots], index=adata_work.obs_names[keep_spots], columns=adata_work.var_names)
            design_df = design_df.loc[keep_spots]
            
            # Sıfır toplamlı genleri ele
            valid_genes_mask = counts_df.sum(axis=0) > 0
            counts_df = counts_df.loc[:, valid_genes_mask]
            
            dds = DeseqDataSet(
                counts=counts_df,
                metadata=design_df,
                design_factors="condition",
                n_cpus=1
            )
            dds.deseq2()
            stat_res = DeseqStats(dds, contrast=["condition", "group1", "group2"])
            res_df = stat_res.results_df
            
            for g in genes_to_test:
                if g in res_df.index:
                    row = res_df.loc[g]
                    results.append({
                        'gene': g,
                        'logFC': float(row['log2FoldChange']),
                        'pval': float(row['pvalue']) if not np.isnan(row['pvalue']) else 1.0
                    })
                else:
                    results.append({'gene': g, 'logFC': 0.0, 'pval': 1.0})
            return results
        except Exception as ex_de:
            logger.warning(f"PyDESeq2 başarısız oldu: {ex_de}. Wilcoxon testine geri dönülüyor.")
            method = "wilcoxon"

    # Geri dönüş / Varsayılan yöntemler (Wilcoxon veya t-test)
    X_all = adata_work.X
    X_dense = X_all.toarray() if hasattr(X_all, 'toarray') else np.asarray(X_all)
    
    for idx, g in enumerate(genes_to_test):
        g1_expr = X_dense[group1_mask, idx]
        g2_expr = X_dense[group2_mask, idx]
        
        # logFC
        logFC = float(np.log2((np.mean(g1_expr) + 1e-9) / (np.mean(g2_expr) + 1e-9)))
        
        if method == "wilcoxon":
            try:
                _, p_val = stats.mannwhitneyu(g1_expr, g2_expr, alternative='two-sided')
            except Exception:
                p_val = 1.0
        else: # t-test (Welch)
            try:
                _, p_val = stats.ttest_ind(g1_expr, g2_expr, equal_var=False)
            except Exception:
                p_val = 1.0
                
        results.append({
            'gene': g,
            'logFC': logFC,
            'pval': p_val if not np.isnan(p_val) else 1.0
        })
        
    return results

def main():
    gnn_out    = OUTPUT_DIR / "gnn"
    deconv_out = OUTPUT_DIR / "deconvolution"
    pub_out    = OUTPUT_DIR / "publication_figures"
    pub_out.mkdir(parents=True, exist_ok=True)

    # ── Load data ────────────────────────────────────────────────
    logger.info("📂 Sonuç verileri yükleniyor...")
    data_json_path = gnn_out / "data.json"
    if not data_json_path.exists():
        exit_with_error("data.json bulunamadı, GNN stage tamamlanmamış!")

    # Size check limit: 150 MB to prevent OOM
    _json_size_limit = 150 * 1024 * 1024  
    if data_json_path.stat().st_size > _json_size_limit:
        exit_with_error("data.json çok büyük (>150MB)")

    with open(data_json_path, encoding='utf-8') as f:
        gnn_data = json.load(f)

    spots = gnn_data["spots"]
    meta  = gnn_data["metadata"]
    ZONE_NAMES = meta["zones"]
    CT_NAMES   = meta["ct_names"]

    coords    = np.array([[s["x"], s["y"]] for s in spots])
    zone_pred = np.array([[s["zones"][z] for z in ZONE_NAMES] for s in spots])
    drug_arr  = np.array([s.get("drug_score", 0) for s in spots])
    risk_arr  = np.array([s.get("tcga_risk", 0) for s in spots])

    ZONE_COLORS = {
        "Pseudopalisading Necrosis": "#E63946",
        "Microvascular Proliferation": "#F4A261",
        "Cellular Tumor": "#2A9D8F",
        "Leading Edge": "#457B9D",
        "Infiltrating Tumor": "#9B5DE5",
    }

    # ── Load adata_sp early ───────────────────────────────────────
    adata_sp = None
    adata_sp_path = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    if adata_sp_path.exists():
        try:
            adata_sp = ad.read_h5ad(adata_sp_path)
            logger.info(f"📂 spatial_deconvolved.h5ad yüklendi: {adata_sp.n_obs} spot")
        except Exception as e_adata:
            logger.warning(f"spatial_deconvolved.h5ad yüklenemedi: {e_adata}")

    # ── Spatial Autocorrelation (Moran's I) ──────────────────────
    moran_risk = 0.0
    moran_drug = 0.0
    moran_available = False
    
    if adata_sp is not None and 'connectivities' in adata_sp.obsp:
        try:
            W = adata_sp.obsp['connectivities']
            moran_risk = compute_morans_i(risk_arr, W)
            moran_drug = compute_morans_i(drug_arr, W)
            moran_available = True
            logger.info(f"   Spatial Autocorrelation (Moran's I) — Risk: {moran_risk:.4f} | Drug: {moran_drug:.4f}")
        except Exception as e_moran:
            logger.warning(f"Moran's I hesaplanırken hata: {e_moran}")

    # ── Load Background Image ────────────────────────────────────
    bg_img = None
    scale_f = 1.0

    spatial_data_dir = OUTPUT_DIR / "spatial_data"
    bg_path = spatial_data_dir / "tissue_hires_image.png"
    scale_path = spatial_data_dir / "scalefactors_json.json"

    if bg_path.exists():
        try:
            bg_img = plt.imread(bg_path)
        except: pass

    if scale_path.exists():
        try:
            sf_data = json.loads(scale_path.read_text(encoding='utf-8'))
            scale_f = sf_data.get("tissue_hires_scalef", 1.0)
        except: pass

    plot_coords = coords * scale_f

    def plot_background(ax):
        if bg_img is not None:
            ax.imshow(bg_img, alpha=0.5)
        else:
            # Arkaplan yoksa eksenleri ters çevir ki yönelim Visium görüntüsüyle tutarlı kalsın
            ax.invert_yaxis()

    # ─────────────────────────────────────────────────────────────
    # Figure 1: Spatial Zone Map
    # ─────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 9), facecolor='#0d1117')
    plot_background(ax)
    dom_zone_idx = zone_pred.argmax(axis=1)
    for zi, zone in enumerate(ZONE_NAMES):
        mask = dom_zone_idx == zi
        color = list(ZONE_COLORS.values())[zi % len(ZONE_COLORS)]
        ax.scatter(plot_coords[mask, 0], plot_coords[mask, 1], c=color, label=zone, s=15, alpha=0.85)
    ax.set_facecolor('#0d1117')
    ax.set_title(f"Spatial Zone Haritası — {PATIENT_ID}", color='white', fontsize=14, fontweight='bold')
    ax.tick_params(colors='white')
    ax.legend(loc='upper right', fontsize=8, facecolor='#1a1a2e', labelcolor='white', markerscale=2)
    ax.axis('off')
    plt.tight_layout()
    fig.savefig(pub_out / "fig_spatial_zone_map.png", dpi=plot_dpi, facecolor='#0d1117', bbox_inches='tight')
    plt.close()
    logger.info("   ✅ Zone haritası")
    report_progress(20)

    # ─────────────────────────────────────────────────────────────
    # Figure 2: Drug Score Heatmap
    # ─────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 9), facecolor='#0d1117')
    plot_background(ax)
    sc_plot = ax.scatter(plot_coords[:, 0], plot_coords[:, 1], c=drug_arr,
                         cmap='plasma', s=15, alpha=0.9, vmin=0, vmax=1)
    cbar = plt.colorbar(sc_plot, ax=ax)
    cbar.set_label("Drug Score", color='white')
    cbar.ax.yaxis.set_tick_params(color='white')
    plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')
    ax.set_facecolor('#0d1117')
    moran_title = f" | Moran's I: {moran_drug:.3f}" if moran_available else ""
    ax.set_title(f"İlaç Hedef Skoru — {PATIENT_ID}{moran_title}", color='white', fontsize=14, fontweight='bold')
    ax.tick_params(colors='white')
    ax.axis('off')
    plt.tight_layout()
    fig.savefig(pub_out / "fig_drug_score_map.png", dpi=plot_dpi, facecolor='#0d1117', bbox_inches='tight')
    plt.close()
    logger.info("   ✅ Drug score haritası")
    report_progress(35)

    # ─────────────────────────────────────────────────────────────
    # Figure 3: TCGA Risk Map
    # ─────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 9), facecolor='#0d1117')
    plot_background(ax)
    sc_plot = ax.scatter(plot_coords[:, 0], plot_coords[:, 1], c=risk_arr,
                         cmap='RdYlGn_r', s=15, alpha=0.9, vmin=0, vmax=1)
    cbar = plt.colorbar(sc_plot, ax=ax)
    cbar.set_label("Hayatta Kalma Riski", color='white')
    cbar.ax.yaxis.set_tick_params(color='white')
    plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')
    ax.set_facecolor('#0d1117')
    moran_title = f" | Moran's I: {moran_risk:.3f}" if moran_available else ""
    ax.set_title(f"TCGA Risk Haritası — {PATIENT_ID}{moran_title}", color='white', fontsize=14, fontweight='bold')
    ax.tick_params(colors='white')
    ax.axis('off')
    plt.tight_layout()
    fig.savefig(pub_out / "fig_risk_map.png", dpi=plot_dpi, facecolor='#0d1117', bbox_inches='tight')
    plt.close()
    logger.info("   ✅ Risk haritası")
    report_progress(50)

    # ─────────────────────────────────────────────────────────────
    # Figure 4: Zone stacked bars
    # ─────────────────────────────────────────────────────────────
    zone_means = zone_pred.mean(axis=0)
    fig, ax = plt.subplots(figsize=(10, 5), facecolor='#0d1117')
    colors_list = list(ZONE_COLORS.values())[:len(ZONE_NAMES)]
    ax.bar(range(len(ZONE_NAMES)), zone_means, color=colors_list, edgecolor='#0d1117', width=0.7)
    ax.set_xticks(range(len(ZONE_NAMES)))
    ax.set_xticklabels([z.replace(' ', '\n') for z in ZONE_NAMES], color='white', fontsize=9)
    ax.set_ylabel("Ortalama Olasılık", color='white')
    ax.set_title(f"Zone Dağılımı — {PATIENT_ID}", color='white', fontsize=13, fontweight='bold')
    ax.set_facecolor('#1a1a2e')
    ax.tick_params(colors='white')
    fig.patch.set_facecolor('#0d1117')
    plt.tight_layout()
    fig.savefig(pub_out / "fig1_zone_stacked_bars.png", dpi=plot_dpi, facecolor='#0d1117', bbox_inches='tight')
    plt.close()
    logger.info("   ✅ Zone bar chart")
    report_progress(65)

    # ─────────────────────────────────────────────────────────────
    # Figure 5: Ligand-Reseptör (L-R) İletişim Haritası
    # ─────────────────────────────────────────────────────────────
    _lr_success = False

    if adata_sp is not None:
        try:
            # Dynamic database integration (falls back to curated list if offline)
            GBM_LR_PAIRS = fetch_dynamic_lr_pairs(adata_sp, max_pairs=8)
            
            n_zones = len(ZONE_NAMES)
            dom_zone_idx = np.argmax(zone_pred, axis=1)

            # zon × L-R çifti matrisi oluştur
            lr_matrix = np.zeros((n_zones, len(GBM_LR_PAIRS)), dtype=np.float32)
            lr_pvals = np.ones((n_zones, len(GBM_LR_PAIRS)), dtype=np.float32)

            for z_idx in range(n_zones):
                zone_mask = dom_zone_idx == z_idx
                if zone_mask.sum() < 5:
                    continue
                
                # Zone alt kümesi üzerinde hücre-hücre iletişim skoru ve permütasyon p-değeri hesapla
                _adata_sub = adata_sp[zone_mask]
                for lr_idx, (lig, rec, _label, sender, receiver) in enumerate(GBM_LR_PAIRS):
                    observed = compute_cell_communication(_adata_sub, sender, receiver, lig, rec)
                    lr_matrix[z_idx, lr_idx] = observed
                    
                    # Permütasyon anlamlılık testi (hız için 50 permütasyon)
                    pval = permute_communication_score(_adata_sub, sender, receiver, lig, rec, observed, n_permutations=50)
                    lr_pvals[z_idx, lr_idx] = pval

            # z-score normalise (zon başına değil, L-R çifti başına normalizasyon)
            lr_matrix_norm = np.zeros_like(lr_matrix)
            for j in range(lr_matrix.shape[1]):
                col = lr_matrix[:, j]
                std = col.std()
                lr_matrix_norm[:, j] = (col - col.mean()) / std if std > 1e-8 else 0.0

            lr_labels    = [p[2] for p in GBM_LR_PAIRS]
            zone_labels  = [z.replace(' ', '\n') for z in ZONE_NAMES]

            # p < 0.05 ise değeri yıldızla (*) işaretle
            annot_matrix = np.empty(lr_matrix.shape, dtype=object)
            for i in range(lr_matrix.shape[0]):
                for j in range(lr_matrix.shape[1]):
                    val = lr_matrix_norm[i, j]
                    pval = lr_pvals[i, j]
                    signif = "*" if pval < 0.05 else ""
                    annot_matrix[i, j] = f"{val:.2f}{signif}"

            fig, ax = plt.subplots(figsize=(13, 5), facecolor='#0d1117')
            ax.set_facecolor('#0d1117')
            hm = sns.heatmap(
                lr_matrix_norm,
                xticklabels=lr_labels,
                yticklabels=zone_labels,
                cmap='RdYlBu_r',
                center=0,
                annot=annot_matrix,
                fmt='',
                annot_kws={'size': 8, 'color': 'white'},
                linewidths=0.4,
                linecolor='#0d1117',
                ax=ax,
                cbar_kws={'label': 'Z-score (L-R çifti başına normalizasyon)', 'shrink': 0.8},
            )
            
            # Safe colorbar elements access
            if hm.collections and len(hm.collections) > 0:
                cbar_elem = hm.collections[0].colorbar
                if cbar_elem is not None:
                    cbar_elem.ax.yaxis.label.set_color('white')
                    cbar_elem.ax.tick_params(colors='white')
            else:
                if len(fig.axes) > 1:
                    cbar_ax = fig.axes[-1]
                    cbar_ax.yaxis.label.set_color('white')
                    cbar_ax.tick_params(colors='white')

            ax.set_title(
                f"Hücre-Hücre İletişim Haritası — {PATIENT_ID} (* p < 0.05 Permutation Test)",
                color='white', fontsize=13, fontweight='bold', pad=14
            )
            ax.xaxis.tick_top()
            ax.xaxis.set_label_position('top')
            ax.tick_params(axis='x', colors='white', labelsize=8, rotation=30)
            ax.tick_params(axis='y', colors='white', labelsize=8)
            ax.set_xlabel("Ligand → Reseptör Çifti (Hücre Tipleri)", color='#94a3b8', labelpad=10)
            ax.set_ylabel("GNN Zonu", color='#94a3b8')

            fig.patch.set_facecolor('#0d1117')
            plt.tight_layout()
            fig.savefig(pub_out / "fig_lr_communication.png", dpi=plot_dpi,
                        facecolor='#0d1117', bbox_inches='tight')
            plt.close()
            logger.info("   ✅ L-R iletişim haritası (hücre-hücre iletişim skoru)")
            report_progress(75)
            _lr_success = True

        except Exception as _lr_err:
            logger.warning(f"   L-R heatmap oluşturulamadı: {_lr_err}")
            logger.warning("   Fallback: İlaç hedef dağılım histogramı")

    if not _lr_success:
        # ── Fallback: İlaç Hedef Dağılımı (Histogram) ───────────────
        drug_freq: dict = {}
        for s in spots:
            d = s.get("drug", "N/A")
            drug_freq[d] = drug_freq.get(d, 0) + 1

        top_drugs = sorted(drug_freq.items(), key=lambda x: x[1], reverse=True)[:8]
        drugs_list, counts_list = zip(*top_drugs) if top_drugs else ([], [])

        fig, ax = plt.subplots(figsize=(10, 5), facecolor='#0d1117')
        colors_bar = plasma_cmap(np.linspace(0.3, 0.9, len(drugs_list)))
        ax.barh(list(drugs_list), list(counts_list), color=colors_bar)
        ax.set_xlabel("Spot Sayısı", color='white')
        ax.set_title(
            f"GNN İlaç Hedef Dağılımı — {PATIENT_ID}\n"
            f"[L-R analizi için spatial veri gerekli]",
            color='white', fontsize=12, fontweight='bold'
        )
        ax.set_facecolor('#1a1a2e')
        ax.tick_params(colors='white')
        fig.patch.set_facecolor('#0d1117')
        plt.tight_layout()
        fig.savefig(pub_out / "fig_drug_targets.png", dpi=plot_dpi,
                    facecolor='#0d1117', bbox_inches='tight')
        plt.close()
        logger.info("   ✅ Fallback: İlaç hedef dağılımı")
        report_progress(75)

    # ─────────────────────────────────────────────────────────────
    # Figure 6: Risk Stratification — GNN Predicted Survival
    # ─────────────────────────────────────────────────────────────
    logger.info("📈 Risk stratifikasyonu (GNN-tahminli) oluşturuluyor...")

    # ── 1. Gerçek risk skorlarını yükle ──────────────────────────
    surv_scores = None
    surv_npy_path = gnn_out / "survival_predictions.npy"
    if surv_npy_path.exists():
        try:
            surv_scores = np.load(surv_npy_path).flatten().astype(np.float32)
            logger.info(f"   survival_predictions.npy yüklendi: {len(surv_scores)} spot")
        except Exception as e_surv:
            logger.warning(f"   survival_predictions.npy yüklenirken hata: {e_surv}")

    if surv_scores is None or surv_scores.size == 0:
        # Fallback: data.json'daki tcga_risk skorlarını kullan
        surv_scores = risk_arr.astype(np.float32)
        logger.warning("   survival_predictions.npy bulunamadı veya boş, data.json tcga_risk kullanılıyor.")

    # NaN/Inf temizliği
    surv_scores = np.nan_to_num(surv_scores, nan=0.5, posinf=1.0, neginf=0.0)
    surv_scores = np.clip(surv_scores, 0.0, 1.0)

    # Verify that surv_scores is not empty to prevent errors
    if surv_scores.size == 0:
        logger.warning("Hayatta kalma skorları boş (0 spot). Kaplan-Meier çizimi atlanıyor.")
    else:
        # ── 2. Medyan eşiğe göre Yüksek/Düşük Risk stratifikasyonu ──
        median_risk = float(np.median(surv_scores))
        high_risk_mask = surv_scores >= median_risk
        low_risk_mask  = ~high_risk_mask

        n_high = int(high_risk_mask.sum())
        n_low  = int(low_risk_mask.sum())
        mean_high = float(surv_scores[high_risk_mask].mean()) if n_high > 0 else 0.5
        mean_low  = float(surv_scores[low_risk_mask].mean()) if n_low > 0 else 0.5

        logger.info(f"   Risk eşiği (medyan): {median_risk:.4f}")
        logger.info(f"   Yüksek Risk: {n_high} spot  |  Ortalama skor: {mean_high:.4f}")
        logger.info(f"   Düşük  Risk: {n_low} spot  |  Ortalama skor: {mean_low:.4f}")

        # ── 3. Hayatta kalma eğrilerini oluştur ──────────────────────
        KM_MONTHS = np.linspace(0, 30, 300)

        # Yayınlanmış TCGA GBM medyan OS değerleri (ay)
        MEDIAN_OS_HIGH_REF = 12.6   # Brennan et al., Cell 2013 — yüksek risk
        MEDIAN_OS_LOW_REF  = 18.4   # Brennan et al., Cell 2013 — düşük risk
        WEIBULL_K          = 1.2    # GBM survival için hafif üst-eksponansiyel
        SCALE_ALPHA        = 0.8    # Risk skoru → lambda lineer katsayısı

        def weibull_survival(t, median_os, k=WEIBULL_K):
            """S(t) = exp(-((t / lambda) ^ k)),  lambda = median / ln(2)^(1/k)"""
            lam = median_os / (np.log(2) ** (1.0 / k))
            return np.exp(-((t / (lam + 1e-9)) ** k))

        # Risk skoru ortalamalarına göre medyan OS'u ölçekle
        delta_high = (mean_high - 0.5) * SCALE_ALPHA   # pozitif → daha kötü
        delta_low  = (mean_low  - 0.5) * SCALE_ALPHA   # negatif → daha iyi

        median_high_adj = MEDIAN_OS_HIGH_REF * np.exp(-delta_high)
        median_low_adj  = MEDIAN_OS_LOW_REF  * np.exp(-delta_low)
        median_high_adj = float(np.clip(median_high_adj, 4.0, 36.0))
        median_low_adj  = float(np.clip(median_low_adj,  6.0, 48.0))

        km_high_curve = weibull_survival(KM_MONTHS, median_high_adj)
        km_low_curve  = weibull_survival(KM_MONTHS, median_low_adj)

        logger.info(f"   Tahmini medyan OS — Yüksek Risk: {median_high_adj:.1f} ay | Düşük Risk: {median_low_adj:.1f} ay")

        # ── 4. Figürü çiz ─────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(9, 6), facecolor='#0d1117')

        # Eğriler
        ax.plot(KM_MONTHS, km_high_curve, color='#E63946', linewidth=2.5,
                label=f'Yüksek Risk  (n={n_high}, skor≥{median_risk:.2f})')
        ax.plot(KM_MONTHS, km_low_curve,  color='#2A9D8F', linewidth=2.5,
                label=f'Düşük Risk  (n={n_low}, skor<{median_risk:.2f})')

        # Güven aralığı (±%5 Weibull varyansı — gösterimlik/illustrative band, NOT a statistical CI)
        ci_width = 0.05
        ax.fill_between(KM_MONTHS,
                        np.clip(km_high_curve - ci_width, 0, 1),
                        np.clip(km_high_curve + ci_width, 0, 1),
                        alpha=0.15, color='#E63946',
                        label='±5% Gösterimlik Bant (CI Değil)')
        ax.fill_between(KM_MONTHS,
                        np.clip(km_low_curve - ci_width, 0, 1),
                        np.clip(km_low_curve + ci_width, 0, 1),
                        alpha=0.15, color='#2A9D8F')

        # Medyan OS dikey çizgileri
        ax.axvline(median_high_adj, color='#E63946', linestyle=':', linewidth=1.2, alpha=0.6)
        ax.axvline(median_low_adj,  color='#2A9D8F', linestyle=':', linewidth=1.2, alpha=0.6)
        ax.axhline(0.5, color='#64748b', linestyle='--', linewidth=0.8, alpha=0.5)
        ax.text(median_high_adj + 0.3, 0.52, f'{median_high_adj:.0f} ay',
                color='#E63946', fontsize=7.5, va='bottom')
        ax.text(median_low_adj  + 0.3, 0.52, f'{median_low_adj:.0f} ay',
                color='#2A9D8F', fontsize=7.5, va='bottom')

        # Eksenler ve etiketler
        ax.set_xlabel("Süre (Ay)", color='#94a3b8', fontsize=10)
        ax.set_ylabel("Tahmini Hayatta Kalma Olasılığı", color='#94a3b8', fontsize=10)
        ax.set_title(
            f"GNN Risk Stratifikasyonu — {PATIENT_ID}\n"
            f"[MODEL TAHMİNİ — Gerçek Klinik Follow-up Değil]",
            color='white', fontsize=12, fontweight='bold', pad=12
        )
        ax.set_xlim(0, 30)
        ax.set_ylim(0, 1.05)
        ax.set_facecolor('#0d1117')
        ax.tick_params(colors='#94a3b8', labelsize=9)
        for spine in ax.spines.values():
            spine.set_edgecolor('#1e3355')

        ax.legend(
            facecolor='#111c35', labelcolor='white',
            fontsize=8.5, framealpha=0.9,
            loc='upper right'
        )

        # Dipnot — bilimsel dürüstlük bildirimi
        disclaimer = (
            "⚠ Bu grafik gerçek hasta survival verisi değildir.\n"
            "GNN tcga_risk skorları (n=" + str(len(surv_scores)) + " spot) ile medyan stratifikasyon yapılmış;\n"
            "eğriler TCGA GBM kohortuna (Brennan et al. Cell 2013) Weibull ile kalibre edilmiştir."
        )
        fig.text(0.5, 0.01, disclaimer,
                 ha='center', va='bottom', fontsize=6.5,
                 color='#64748b', style='italic',
                 wrap=True)

        fig.patch.set_facecolor('#0d1117')
        plt.tight_layout(rect=[0, 0.07, 1, 1])

        fig.savefig(pub_out / "fig_kaplan_meier.png", dpi=plot_dpi, facecolor='#0d1117', bbox_inches='tight')
        plt.close()
        logger.info(f"   ✅ Risk stratifikasyon figürü — medyan OS tahmini: "
                    f"Yüksek={median_high_adj:.1f}ay / Düşük={median_low_adj:.1f}ay")
        report_progress(85)

        # Kaplan-Meier özet verilerini JSON'a yaz (rapor için)
        km_summary = {
            "method": "weibull_tcga_calibrated",
            "reference": "Brennan et al., Cell 2013 — TCGA GBM (n=516)",
            "median_risk_threshold": round(median_risk, 4),
            "n_high_risk_spots": n_high,
            "n_low_risk_spots": n_low,
            "mean_risk_score_high": round(mean_high, 4),
            "mean_risk_score_low": round(mean_low, 4),
            "estimated_median_os_high_months": round(median_high_adj, 1),
            "estimated_median_os_low_months": round(median_low_adj, 1),
            "disclaimer": (
                "Model-predicted only. No real patient time-to-event data used. "
                "Survival curves are Weibull-fitted and calibrated to TCGA GBM "
                "published medians. Do not use for clinical decision-making."
            )
        }
        (gnn_out / "kaplan_meier_summary.json").write_text(json.dumps(km_summary, indent=2), encoding='utf-8')
        logger.info("   ✅ Kaplan-Meier özeti JSON'a yazıldı")
        report_progress(90)

    # ============================================================
    # ADVANCED BIOLOGICAL FIGURES (v2.0 - From User's Publication Scripts)
    # ============================================================
    logger.info("   Yüksek çözünürlüklü makale grafikleri (Volcano, L-R Heatmap, Bipartite) hazırlanıyor...")

    # Initialize scope variables to prevent NameError downstream
    adata_work = None
    group1_mask = None
    group2_mask = None

    if adata_sp is not None:
        try:
            adata_work = adata_sp.copy()
            sc.pp.filter_genes(adata_work, min_cells=10)
            gnn_zone = np.array([ZONE_NAMES[i] for i in np.argmax(zone_pred, axis=1)])
            group1_mask = gnn_zone == 'Pseudopalisading Necrosis'
            group2_mask = gnn_zone == 'Leading Edge'
        except Exception as e:
            logger.warning(f"Volcano / Bipartite plots için veri kopyalanamadı: {e}")
            group1_mask = np.zeros(len(zone_pred), dtype=bool)
            group2_mask = np.zeros(len(zone_pred), dtype=bool)
            adata_work = None

    if group1_mask is not None and group2_mask is not None and adata_work is not None and group1_mask.sum() >= 5 and group2_mask.sum() >= 5:
        try:
            # Apply variance filter (select top 500 genes) prior to differential testing for speed and readability
            X_all = adata_work.X
            X_dense = X_all.toarray() if hasattr(X_all, 'toarray') else np.asarray(X_all)
            top_idx = np.argsort(X_dense.var(axis=0))[::-1][:500]
            adata_work = adata_work[:, top_idx].copy()
            
            logger.info(f"   Diferansiyel test yöntemi: {de_method} (Top 500 en yüksek varyanslı gen)")
            results = run_volcano_differential_testing(adata_work, group1_mask, group2_mask, method=de_method)
            
            res_df = pd.DataFrame(results)
            # Benjamini-Hochberg FDR düzeltmesi (satır içi)
            try:
                from statsmodels.stats.multitest import multipletests
                _, padj_vals, _, _ = multipletests(res_df['pval'].values, method='fdr_bh')
            except ImportError:
                # statsmodels yoksa manuel BH
                pvals = res_df['pval'].values
                n = len(pvals)
                sorted_idx = np.argsort(pvals)
                padj_vals = np.zeros(n)
                prev_q = 1.0
                for _i in range(n - 1, -1, -1):
                    _q = (pvals[sorted_idx[_i]] * n) / (_i + 1)
                    _q = min(_q, prev_q)
                    padj_vals[_i] = _q
                    prev_q = _q
                # map back
                padj_out = np.zeros(n)
                padj_out[sorted_idx] = padj_vals
                padj_vals = padj_out
            res_df['padj'] = np.clip(padj_vals, 0, 1)
            res_df['log10_padj'] = -np.log10(res_df['padj'].clip(lower=1e-300))
            res_df['Significant'] = 'NS'
            res_df.loc[(res_df['logFC'] > 0.5) & (res_df['padj'] < 0.05), 'Significant'] = 'Up in Necrosis'
            res_df.loc[(res_df['logFC'] < -0.5) & (res_df['padj'] < 0.05), 'Significant'] = 'Up in Leading Edge'
            
            fig, ax = plt.subplots(figsize=(7, 7), facecolor='#0d1117')
            sns.scatterplot(data=res_df, x='logFC', y='log10_padj', hue='Significant', 
                            palette={'NS': 'grey', 'Up in Necrosis': '#E63946', 'Up in Leading Edge': '#457B9D'},
                            alpha=0.7, s=30, ax=ax)
            ax.axhline(-np.log10(0.05), color='white', linestyle='--', lw=1)
            ax.axvline(0.5, color='white', linestyle='--', lw=1)
            ax.axvline(-0.5, color='white', linestyle='--', lw=1)
            
            # Scientific caution: add spatial correlation warning in title
            ax.set_title(f"Volcano Plot: Necrosis vs Edge ({de_method.upper()})\n[Uyarı: Spatial bağımlılık düzeltilmedi]", color='white', fontsize=11)
            ax.tick_params(colors='white')
            ax.xaxis.label.set_color('white')
            ax.yaxis.label.set_color('white')
            ax.legend(frameon=False, labelcolor='white')
            fig.patch.set_facecolor('#0d1117')
            ax.set_facecolor('#0d1117')
            plt.tight_layout()
            fig.savefig(pub_out / "fig2_volcano_necrosis_vs_edge.png", dpi=plot_dpi, facecolor='#0d1117')
            plt.close()
            logger.info("   ✅ Volcano plot çizildi.")
        except Exception as e_volc:
            logger.warning(f"Volcano plot çizimi sırasında hata: {e_volc}")

    if adata_work is not None:
        del adata_work
    gc.collect()

    # ── 2. Bipartite Spatial Co-expression Network ──
    # Not: Bu grafik doğrudan hücre-hücre iletişimini ölçmez (CellChat, NicheNet vb. gibi değil).
    # Ligand ve reseptör genlerinin spatial olarak aynı spotlarda ne kadar eş-ifadelendiğini 
    # (co-expression / co-localization) yansıtır.
    edge_defs = [
        ('TAM', 'T_Cell', 'CD274', 'PDCD1', 'CD274-PDCD1'),
        ('Tumor_MES', 'Endothelial', 'VEGFA', 'KDR', 'VEGFA-KDR'),
        ('Tumor_MES', 'TAM', 'SPP1', 'CD44', 'SPP1-CD44'),
        ('Microglia', 'Tumor_MES', 'MIF', 'CD74', 'MIF-CD74')
    ]
    valid_edges = []

    if adata_sp is not None:
        try:
            all_scores = []
            edge_candidates = []
            for sender, receiver, lig, rec, label in edge_defs:
                # Cell-type specific neighboring cell-cell communication score
                comm_score = compute_cell_communication(adata_sp, sender, receiver, lig, rec)
                all_scores.append(comm_score)
                edge_candidates.append((sender, receiver, lig, rec, label, comm_score))
            
            # Adaptive threshold: Use the 50th percentile or 1e-4 (whichever is more selective)
            threshold = 1e-4
            if all_scores:
                threshold = max(1e-4, float(np.percentile(all_scores, 50)))
                logger.info(f"   Bipartite network adaptif eşiği: {threshold:.6f}")
            
            for sender, receiver, lig, rec, label, score in edge_candidates:
                if score >= threshold:
                    valid_edges.append((sender, receiver, lig, rec, label, score))
        except Exception as e_coexpr:
            logger.warning(f"Co-expression hesaplama hatası: {e_coexpr}")

    if adata_sp is not None and valid_edges:
        try:
            G = nx.DiGraph()
            senders = list({f"{e[0]} (S)" for e in valid_edges})
            receivers = list({f"{e[1]} (R)" for e in valid_edges})
            for s in senders: G.add_node(s)
            for r in receivers: G.add_node(r)
            for s, r, lig, rec, lab, score in valid_edges:
                G.add_edge(f"{s} (S)", f"{r} (R)", weight=score, label=lab)
            
            pos = {}
            for i, s in enumerate(senders): pos[s] = np.array([-1.0, float(i)])
            for i, r in enumerate(receivers): pos[r] = np.array([1.0, float(i)])
            
            fig, ax = plt.subplots(figsize=(10, 8), facecolor='#0d1117')
            nx.draw_networkx_nodes(G, pos, nodelist=senders, node_color='#457B9D', node_size=2000, ax=ax)
            nx.draw_networkx_nodes(G, pos, nodelist=receivers, node_color='#E63946', node_size=2000, ax=ax)
            nx.draw_networkx_labels(G, pos, font_color='white', font_size=8, ax=ax)
            nx.draw_networkx_edges(G, pos, edge_color='white', alpha=0.5, ax=ax)
            ax.set_title(
                'Bipartite Spatial Co-expression Network\n'
                '[CellChat Uyumlu Hücre-Hücre İletişim Model Skoru]',
                color='white', fontsize=12, fontweight='bold', pad=15
            )
            ax.axis('off')
            fig.patch.set_facecolor('#0d1117')
            fig.savefig(pub_out / "fig3_bipartite_network.png", dpi=plot_dpi, facecolor='#0d1117')
            plt.close()
            logger.info("   ✅ Bipartite network çizildi.")
        except Exception as e_net:
            logger.warning(f"Bipartite network çizilirken hata: {e_net}")

    if adata_sp is not None:
        del adata_sp
    gc.collect()

    logger.info("   ✅ Advanced Figures eklendi.")
    report_progress(95)

    logger.info("✅ Stage 4 tamamen bitti")
    print(json.dumps({
        "stage": "visualization", 
        "status": "done",
        "figures": 6, 
        "output_dir": str(pub_out)
    }))

if __name__ == "__main__":
    main()
