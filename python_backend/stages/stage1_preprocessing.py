#!/usr/bin/env python3
"""Stage 1: scRNA-seq + Spatial preprocessing"""
import os, sys, json
from pathlib import Path
import numpy as np
import scipy.stats as stats
import scipy.sparse as sp
import yaml
import shutil
import traceback
from pydantic import BaseModel, Field
from typing import List, Optional, Dict

# ── Project Path & PyInstaller Support ───────────────────────
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
import locale_logger
import scanpy as sc
import squidpy as sq

# Pydantic Config Validation Schemas
class ScrnaPreprocessingConfig(BaseModel):
    min_genes: int = 200
    min_cells: int = 3
    max_genes: int = 8000
    max_mito_pct: float = 20.0
    n_top_genes: int = 3000
    n_pcs: int = 50
    n_neighbors: int = 15
    leiden_resolution: float = 0.8

class SpatialPreprocessingConfig(BaseModel):
    min_counts: int = 1000
    min_genes: int = 300
    max_counts: int = 40000
    max_mito_pct: float = 25.0
    n_top_genes: int = 3000

class PreprocessingConfig(BaseModel):
    scrna: ScrnaPreprocessingConfig = Field(default_factory=ScrnaPreprocessingConfig)
    spatial: SpatialPreprocessingConfig = Field(default_factory=SpatialPreprocessingConfig)

class CellCycleConfig(BaseModel):
    s_genes: List[str] = Field(default_factory=list)
    g2m_genes: List[str] = Field(default_factory=list)

class GlobalConfig(BaseModel):
    preprocessing: PreprocessingConfig = Field(default_factory=PreprocessingConfig)
    cell_cycle: CellCycleConfig = Field(default_factory=CellCycleConfig)
    cell_markers: Dict[str, List[str]] = Field(default_factory=dict)

# Use verbosity 2 for detailed Scanpy logging (warnings and info)
sc.settings.verbosity = 2

def exit_with_error(message):
    logger.error(message)
    print(json.dumps({"stage": "preprocessing", "status": "error", "message": message}))
    sys.exit(1)

def report_progress(percent):
    print(json.dumps({"stage": "preprocessing", "status": "running", "progress": percent}))

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 1: Preprocessing")
    parser.add_argument("--config_path", type=str, default=None, help="Path to config.yaml")
    parser.add_argument("--species", type=str, default="human", help="Species (e.g. human or mouse)")
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

    # Load and validate config
    config = GlobalConfig()
    if config_path and config_path.exists():
        try:
            with open(config_path) as f:
                raw_cfg = yaml.safe_load(f) or {}
            config = GlobalConfig(**raw_cfg)
            logger.info(f"   Config loaded and validated via Pydantic: {config_path}")
        except Exception as e:
            logger.warning(f"   Config validation failed ({e}), using default parameters.")
    else:
        logger.warning(f"   Config file not found, using default parameters.")

    try:
        SCRNA_PATH  = Path(os.environ["GLIO_SCRNA_PATH"])
        SPATIAL_DIR = Path(os.environ["GLIO_SPATIAL_DIR"])
        OUTPUT_DIR  = Path(os.environ["GLIO_OUTPUT_DIR"])
    except KeyError as ke:
        exit_with_error(f"Eksik çevre değişkeni: {ke}")

    PATIENT_ID  = os.environ.get("GLIO_PATIENT_ID", "Patient_A")
    report_progress(5)

    # ── Output dirs ─────────────────────────────────────────────
    (OUTPUT_DIR / "preprocessing" / "scRNA").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "preprocessing" / "spatial").mkdir(parents=True, exist_ok=True)

    # Görüntü ve scale faktörleri frontend için kopyala (Symlink ile disk alanı optimizasyonu)
    spatial_img_dir = SPATIAL_DIR / "spatial"
    out_img_dir = OUTPUT_DIR / "spatial_data"
    if spatial_img_dir.exists() and spatial_img_dir.is_dir():
        try:
            if not out_img_dir.exists():
                os.symlink(spatial_img_dir, out_img_dir)
                logger.info("   Background imajı symlink ile bağlandı.")
            else:
                logger.info("   Background imajı zaten mevcut.")
        except Exception as sym_err:
            logger.warning(f"   Symlink başarısız ({sym_err}), kopyalama deneniyor...")
            shutil.copytree(spatial_img_dir, out_img_dir, dirs_exist_ok=True)
            logger.info("   Background imajı kopyalandı.")

    logger.info(f"🔬 scRNA-seq yükleniyor: {SCRNA_PATH}")

    # ── Load scRNA ───────────────────────────────────────────────
    ext = SCRNA_PATH.suffix.lower()
    if ext in ['.h5ad']:
        adata_sc = sc.read_h5ad(SCRNA_PATH)
    elif ext in ['.h5']:
        logger.info("   10X HDF5 (.h5) formatı tespit edildi, sc.read_10x_h5 ile yükleniyor...")
        try:
            adata_sc = sc.read_10x_h5(SCRNA_PATH, genome=None)
        except Exception as e_genome:
            logger.warning(f"   genome=None başarısız ({e_genome}), fallback deneniyor...")
            try:
                adata_sc = sc.read_10x_h5(SCRNA_PATH)
            except Exception as e2:
                exit_with_error(f"   10X HDF5 (.h5) okuma başarısız! Dosya 10X formatında değil veya bozuk: {e2}")
        adata_sc.var_names_make_unique()
        # Bellek optimizasyonu: float32 CSR'a dönüştür
        if not sp.issparse(adata_sc.X):
            adata_sc.X = sp.csr_matrix(adata_sc.X.astype(np.float32))
        else:
            if adata_sc.X.dtype != np.float32:
                adata_sc.X = adata_sc.X.astype(np.float32)
        logger.info(f"   ✅ 10X .h5 yüklendi: {adata_sc.shape[0]} hücre, {adata_sc.shape[1]} gen")
    elif ext in ['.loom']:
        adata_sc = sc.read_loom(SCRNA_PATH)
    elif ext in ['.csv', '.tsv']:
        sep = '\t' if ext == '.tsv' else ','
        import pandas as pd
        logger.info("   Bellek dostu parça parça (chunked) okuma başlatılıyor...")
        
        chunk_list = []
        try:
            for chunk in pd.read_csv(SCRNA_PATH, sep=sep, index_col=0, chunksize=2000):
                dropped_cols = chunk.select_dtypes(exclude=[np.number]).columns.tolist()
                if dropped_cols:
                    logger.warning(f"Sayısal olmayan kolonlar elendi: {dropped_cols}")
                numeric_chunk = chunk.select_dtypes(include=[np.number]).astype(np.float32)
                chunk_list.append(numeric_chunk)
                
            logger.info("   Tüm parçalar birleştiriliyor...")
            df = pd.concat(chunk_list, axis=0)
            del chunk_list

            # ── Yön (orientation) doğrulama ────────────────────────
            # Bu kod satırları/dizin (index) = gen, sütunlar = hücre olduğunu
            # VARSAYAR (`df.T` ile AnnData'ya çevrilir). Bu varsayım
            # tutmuyorsa (kullanıcı standart hücre×gen yönünde bir CSV
            # verirse), matris sessizce yanlış transpoze edilip tüm analiz
            # boyunca gen/hücre eksenleri yer değiştirebilir — şekil hâlâ
            # geçerli olduğu için hata fırlamaz (bkz. denetim raporu C-05).
            # Kesin bir otomatik düzeltme yapmak yerine (yanlış pozitif
            # riski var), gen-sembolü benzeri bir sezgisel ile yönü kontrol
            # edip şüpheli durumda YÜKSEK SESLE uyarıyoruz.
            def _gene_symbol_likeness(labels, sample_n=200):
                import re
                labels = list(labels)[:sample_n]
                if not labels:
                    return 0.0
                gene_like = re.compile(r'^[A-Za-z][A-Za-z0-9\-\.]{0,14}$')
                barcode_like = re.compile(r'^[ACGTacgt]{10,}(-\d+)?$')
                n_gene_like = sum(
                    1 for l in labels
                    if gene_like.match(str(l)) and not barcode_like.match(str(l))
                )
                return n_gene_like / len(labels)

            index_gene_score = _gene_symbol_likeness(df.index)
            col_gene_score = _gene_symbol_likeness(df.columns)
            if col_gene_score - index_gene_score > 0.4:
                logger.warning(
                    "⚠️ CSV YÖNÜ ŞÜPHELİ: Sütun etiketleri (şu an 'hücre' olarak "
                    f"varsayılıyor, gen-benzerlik skoru={col_gene_score:.2f}) satır "
                    f"etiketlerinden (şu an 'gen' olarak varsayılıyor, skor="
                    f"{index_gene_score:.2f}) belirgin şekilde daha çok gen sembolüne "
                    "benziyor. Dosyanız hücre×gen (satır=hücre, sütun=gen) yönünde "
                    "olabilir — bu durumda gen ve hücre eksenleri ters dönmüş "
                    "olacaktır. Beklenen format: gen×hücre (satır=gen, sütun=hücre)."
                )

            logger.info("   AnnData objesi oluşturuluyor ve seyreltik (sparse CSR) matrise dönüştürülüyor...")
            adata_sc = sc.AnnData(df.T)
            del df
            adata_sc.X = sp.csr_matrix(adata_sc.X)
            
        except Exception as e:
            if 'chunk_list' in locals(): del chunk_list
            if 'df' in locals(): del df
            exit_with_error(f"CSV/TSV okuma sırasında hata oluştu: {e}")
    else:
        exit_with_error(f"Desteklenmeyen format: {ext}")

    logger.info(f"   scRNA shape: {adata_sc.shape}")
    report_progress(15)

    # ── scRNA QC (Biyolojik Düzeltmeler) ──────────────────────
    adata_sc.var_names_make_unique()

    # Gen Filtresi: %1'den küçük görünmeyen genleri at
    min_cells_cfg = config.preprocessing.scrna.min_cells
    min_cells_threshold = max(min_cells_cfg, int(adata_sc.n_obs * 0.01))
    sc.pp.filter_genes(adata_sc, min_cells=min_cells_threshold)

    # Hücre Filtresi: Probe kalitesi
    sc.pp.filter_cells(adata_sc, min_genes=config.preprocessing.scrna.min_genes)

    # MT, Ribo, ve Hemoglobin
    adata_sc.var["mt"] = adata_sc.var_names.str.upper().str.startswith("MT-")
    adata_sc.var["ribo"] = adata_sc.var_names.str.upper().str.startswith(("RPS", "RPL"))
    adata_sc.var["hb"] = adata_sc.var_names.str.upper().str.startswith(("HBA", "HBB", "HBM"))
    sc.pp.calculate_qc_metrics(adata_sc, qc_vars=["mt", "ribo", "hb"], percent_top=None, log1p=False, inplace=True)

    # Adaptif Doublet (MAD) Filtresi (gen sayısına dayalı basit filtre)
    median_genes = np.median(adata_sc.obs['n_genes_by_counts'])
    mad_genes = stats.median_abs_deviation(adata_sc.obs['n_genes_by_counts'])
    max_genes_limit = config.preprocessing.scrna.max_genes
    max_genes = min(max_genes_limit, median_genes + 3 * mad_genes)
    logger.info(f"   Doublet filtering using MAD: max_genes={max_genes:.2f} (median={median_genes:.2f}, MAD={mad_genes:.2f})")
    logger.warning("   [QC Uyarı] Doublet tespiti yalnızca gen sayı sınırına dayanmaktadır. Büyük/hiperaktif hücreler etkilenebilir.")
    adata_sc = adata_sc[adata_sc.obs['n_genes_by_counts'] < max_genes, :].copy()

    # Adaptif Mitochondrial Filtresi (MAD bazlı, 5% - 15% arası clamp edilmiş)
    median_mt = np.median(adata_sc.obs['pct_counts_mt'])
    mad_mt = stats.median_abs_deviation(adata_sc.obs['pct_counts_mt'])
    max_mito_pct_cfg = config.preprocessing.scrna.max_mito_pct
    max_mt = np.clip(median_mt + 3 * mad_mt, 5.0, max_mito_pct_cfg)
    logger.info(f"   scRNA MT filtering threshold: {max_mt:.2f}% (median={median_mt:.2f}%, MAD={mad_mt:.2f}%)")
    adata_sc = adata_sc[adata_sc.obs.pct_counts_mt < max_mt].copy()

    logger.info(f"   QC sonrası: {adata_sc.shape}")
    if adata_sc.n_obs < 2:
        exit_with_error("Hücre sayısı kalite kontrolü sonrasında yetersiz (< 2). Kümeleme yapılamaz.")
    report_progress(20)

    # ── Normalization + HVG ─────────────────────────────────────
    counts_per_cell = np.asarray(adata_sc.X.sum(axis=1)).flatten()
    
    # 1. Sparse matrix optimized is_log check (data.max() is faster)
    if sp.issparse(adata_sc.X):
        is_log = (adata_sc.X.data.max() < 25) if len(adata_sc.X.data) > 0 else True
    else:
        is_log = (adata_sc.X.max() < 25)

    # 2. Heuristic check: are all cell counts almost identical?
    is_normalized = np.allclose(counts_per_cell, counts_per_cell[0], rtol=1e-2) if len(counts_per_cell) > 0 else True

    # 3. Check if values represent integers (raw counts)
    # NOT: Önceki sürüm yalnızca matrisin İLK 100 seyrek değerini (CSR
    # sırasına göre pratikte ilk birkaç hücre) ya da İLK 10×10 köşesini
    # örnekliyordu — bu, temsili olmayan bir örnek olabilir (ör. veri
    # setinin başındaki hücreler tesadüfen sıfır/tam sayı olmayan bir alt
    # kümeyse yanlış karar verilebilir). Artık tüm matristen RASTGELE bir
    # örnek alınıyor (bkz. denetim raporu C-04).
    is_integer = np.issubdtype(adata_sc.X.dtype, np.integer)
    if not is_integer:
        _rng = np.random.default_rng(42)
        if sp.issparse(adata_sc.X):
            _data = adata_sc.X.data
            if len(_data) > 0:
                _sample_n = min(5000, len(_data))
                _sample = _rng.choice(_data, size=_sample_n, replace=False)
                is_integer = np.all(np.equal(np.mod(_sample, 1), 0))
            else:
                is_integer = True
        else:
            _flat = np.asarray(adata_sc.X).flatten()
            if len(_flat) > 0:
                _sample_n = min(5000, len(_flat))
                _sample = _rng.choice(_flat, size=_sample_n, replace=False)
                is_integer = np.all(np.equal(np.mod(_sample, 1), 0))
            else:
                is_integer = True

    if not is_log and not is_normalized and is_integer:
        logger.info("   Verinin raw count olduğu tespit edildi, normalize_total uygulanıyor.")
        zero_count_cells = (counts_per_cell == 0)
        if zero_count_cells.any():
            logger.warning(f"   Sıfır count içeren {zero_count_cells.sum()} hücre eleniyor.")
            adata_sc = adata_sc[~zero_count_cells].copy()
        sc.pp.normalize_total(adata_sc, target_sum=1e4)
    else:
        logger.info("   Veri halihazırda normalize/TPM veya log-transforme edilmiş görünüyor, normalize_total atlandı.")

    # Biyolojik Doğruluk: Log dönüşümü (log1p) öncesinde ham sayıları saklayın
    adata_sc.raw = adata_sc.copy()

    sc.pp.log1p(adata_sc)

    batch_key = 'batch' if 'batch' in adata_sc.obs.columns else None
    _n_top_genes_sc = config.preprocessing.scrna.n_top_genes
    try:
        sc.pp.highly_variable_genes(adata_sc, flavor="seurat", n_top_genes=_n_top_genes_sc, batch_key=batch_key)
    except Exception as e_hvg_seurat:
        try:
            sc.pp.highly_variable_genes(adata_sc, flavor="cell_ranger", n_top_genes=_n_top_genes_sc, batch_key=batch_key)
        except Exception as e_hvg_cr:
            logger.warning(f"Highly variable genes calculation with batch failed. Trying without batch_key...")
            try:
                sc.pp.highly_variable_genes(adata_sc, flavor="seurat", n_top_genes=_n_top_genes_sc)
            except Exception as e_final_seurat:
                try:
                    sc.pp.highly_variable_genes(adata_sc, flavor="cell_ranger", n_top_genes=_n_top_genes_sc)
                except Exception as e_final_cr:
                    exit_with_error(
                        f"Highly variable genes methods failed completely. Details:\n"
                        f"- Seurat (batch): {e_hvg_seurat}\n"
                        f"- Cell Ranger (batch): {e_hvg_cr}\n"
                        f"- Seurat (no batch): {e_final_seurat}\n"
                        f"- Cell Ranger (no batch): {e_final_cr}"
                    )

    adata_sc_hvg = adata_sc[:, adata_sc.var.highly_variable].copy()

    # Cell Cycle Scoring and Regression
    s_genes = config.cell_cycle.s_genes or ['MCM5', 'PCNA', 'TYMS', 'FEN1', 'MCM2', 'MCM4', 'RRM1', 'UNG', 'GINS2', 'MCM6', 'CDCA7', 'DTL', 'PRIM1', 'UHRF1', 'HELLS', 'RFC2', 'RPA2', 'NASP', 'RAD51AP1', 'GMNN', 'WDR76', 'SLBP', 'CCNE2', 'UBR7', 'POLD3', 'MSH2', 'ATAD2', 'RAD51', 'RRM2', 'CDC45', 'CDC6', 'EXO1', 'TIPIN', 'DSCC1', 'BLM', 'CASP8AP2', 'USP1', 'CLSPN', 'POLA1', 'CHAF1B', 'BRIP1', 'E2F8']
    g2m_genes = config.cell_cycle.g2m_genes or ['HMGB2', 'CDK1', 'NUSAP1', 'UBE2C', 'BIRC5', 'TPX2', 'TOP2A', 'NDC80', 'CKS2', 'NUF2', 'CKS1B', 'MKI67', 'TMPO', 'CENPF', 'TACC3', 'SMC4', 'CCNB2', 'CENPE', 'AURKB', 'CCNB1', 'ECT2', 'CENPA', 'CDC20', 'TTK', 'CDC25C', 'KIF20B', 'PLK1', 'CEP55', 'PRC1', 'KIF2C', 'KIF11', 'KIF23', 'SMC2', 'DIAPH3', 'HMMR', 'KIF15', 'LBR', 'SFPQ', 'ANLN', 'ANP32E', 'G2E3', 'GAS2L3', 'NCAPD2', 'NCAPH', 'NCAPG']

    # Case-insensitive matching so it works with 'Mcm5' (mouse) and 'MCM5' (human)
    var_names_upper = {g.upper(): g for g in adata_sc.var_names}
    s_genes_valid = [var_names_upper[s.upper()] for s in s_genes if s.upper() in var_names_upper]
    g2m_genes_valid = [var_names_upper[g.upper()] for g in g2m_genes if g.upper() in var_names_upper]

    if s_genes_valid and g2m_genes_valid:
        logger.info("   Cell cycle scoring running on full dataset...")
        sc.tl.score_genes_cell_cycle(adata_sc, s_genes=s_genes_valid, g2m_genes=g2m_genes_valid)
        adata_sc_hvg.obs['S_score'] = adata_sc.obs['S_score']
        adata_sc_hvg.obs['G2M_score'] = adata_sc.obs['G2M_score']
        logger.info("   Regressing out cell cycle effects (S_score, G2M_score) on HVGs...")
        sc.pp.regress_out(adata_sc_hvg, keys=['S_score', 'G2M_score'])
    else:
        logger.warning("   Insufficient cell cycle genes found in dataset. Skipping cell cycle regression.")

    report_progress(30)

    # ── PCA + Clustering ────────────────────────────────────────
    sc.pp.scale(adata_sc_hvg, max_value=10)

    n_comps_actual = min(config.preprocessing.scrna.n_pcs, adata_sc_hvg.n_obs - 1, adata_sc_hvg.n_vars - 1)
    sc.tl.pca(adata_sc_hvg, svd_solver='arpack', n_comps=n_comps_actual)

    # Index alignment validation before setting PCA back to main object
    assert np.all(adata_sc.obs_names == adata_sc_hvg.obs_names), "HVG ve scRNA hücre sıralaması uyuşmuyor!"
    adata_sc.obsm['X_pca'] = adata_sc_hvg.obsm['X_pca'].copy()

    n_pcs_actual = adata_sc.obsm['X_pca'].shape[1]
    sc.pp.neighbors(adata_sc, n_pcs=n_pcs_actual, n_neighbors=config.preprocessing.scrna.n_neighbors)
    report_progress(40)

    sc.tl.umap(adata_sc)
    sc.tl.leiden(adata_sc, resolution=config.preprocessing.scrna.leiden_resolution)
    logger.info(f"   Leiden clusters: {adata_sc.obs['leiden'].nunique()}")
    report_progress(45)

    # ── Save scRNA ───────────────────────────────────────────
    scrna_out = OUTPUT_DIR / "preprocessing" / "scRNA" / "scrna_preprocessed.h5ad"
    logger.info(f"   scRNA diske yazılıyor ({adata_sc.n_obs} hücre, {adata_sc.n_vars} gen)...")
    adata_sc.write_h5ad(scrna_out)
    logger.info(f"   ✅ scRNA kaydedildi: {scrna_out}")
    report_progress(50)

    # ── Load Spatial ─────────────────────────────────────────────
    logger.info(f"📍 Spatial veri yükleniyor: {SPATIAL_DIR}")

    try:
        adata_sp = sq.read.visium(SPATIAL_DIR)
        logger.info("   Visium formatı tanındı")
    except Exception as e_vis:
        try:
            h5_files = list(SPATIAL_DIR.glob("*.h5"))
            if h5_files:
                adata_sp = sq.read.visium(SPATIAL_DIR, counts_file=h5_files[0].name)
                logger.info(f"   Visium formatı tanındı ({h5_files[0].name})")
            else:
                raise ValueError("Klasörde .h5 dosyası bulunamadı.")
        except Exception as e_vis_h5:
            h5ad_files = list(SPATIAL_DIR.glob("*.h5ad"))
            if h5ad_files:
                adata_sp = sc.read_h5ad(h5ad_files[0])
                logger.info(f"   H5AD yüklendi: {h5ad_files[0].name}")
            else:
                exit_with_error(
                    f"Spatial veri formatı tanınamadı! Klasör geçerli bir 10X Visium yapısı "
                    f"veya .h5ad dosyası içermiyor. Hata detayları:\n"
                    f"- Visium yükleme hatası: {e_vis}\n"
                    f"- H5 arama hatası: {e_vis_h5}"
                )

    report_progress(60)

    # Format kontrolü: Eğer mekansal koordinat yoksa uyar
    if "spatial" not in adata_sp.obsm:
        logger.warning(
            "⚠️ DİKKAT: Spatial koordinatlar (obsm['spatial']) bulunamadı! "
            "UMAP koordinatlarına başvuruluyor. Bu işlem sadece görselleştirme amaçlıdır, "
            "gerçek mekansal analizler (örneğin GNN veya niş analizi) için doğru sonuçlar vermez!"
        )
        if "X_umap" not in adata_sp.obsm:
            sc.pp.pca(adata_sp)
            sc.pp.neighbors(adata_sp)
            sc.tl.umap(adata_sp)
        adata_sp.obsm["spatial"] = adata_sp.obsm["X_umap"].copy()

    logger.info(f"   Spatial shape: {adata_sp.shape}")

    # ── Spatial QC (v5.1) ───────────────────────────────────────
    min_counts = config.preprocessing.spatial.min_counts
    min_genes = config.preprocessing.spatial.min_genes
    max_counts = config.preprocessing.spatial.max_counts
    max_mito_pct = config.preprocessing.spatial.max_mito_pct
    logger.info(f"   Loaded spatial QC config: min_counts={min_counts}, min_genes={min_genes}, max_counts={max_counts}, max_mito_pct={max_mito_pct}")

    adata_sp.var_names_make_unique()

    adata_sp.var["mt"] = adata_sp.var_names.str.upper().str.startswith("MT-")
    adata_sp.var["ribo"] = adata_sp.var_names.str.upper().str.startswith(("RPS", "RPL"))
    adata_sp.var["hb"] = adata_sp.var_names.str.upper().str.startswith(("HBA", "HBB", "HBM"))
    sc.pp.calculate_qc_metrics(adata_sp, qc_vars=["mt", "ribo", "hb"], percent_top=None, log1p=False, inplace=True)

    sc.pp.filter_genes(adata_sp, min_cells=10)
    sc.pp.filter_cells(adata_sp, min_counts=min_counts)
    sc.pp.filter_cells(adata_sp, max_counts=max_counts)
    adata_sp = adata_sp[adata_sp.obs.n_genes_by_counts >= min_genes, :].copy()
    
    # Filter spatial cells by mitochondrial percentage from config
    adata_sp = adata_sp[adata_sp.obs.pct_counts_mt < max_mito_pct, :].copy()
    report_progress(70)

    # ── Normalize Spatial ────────────────────────────────────────
    sc.pp.normalize_total(adata_sp, target_sum=1e4)

    # Biyolojik Doğruluk: Log dönüşümü (log1p) öncesinde ham sayıları saklayın
    adata_sp.raw = adata_sp.copy()

    sc.pp.log1p(adata_sp)

    sc.pp.highly_variable_genes(adata_sp, flavor="seurat", n_top_genes=config.preprocessing.spatial.n_top_genes)

    adata_sp_hvg = adata_sp[:, adata_sp.var.highly_variable].copy()
    sc.pp.scale(adata_sp_hvg, max_value=10)

    n_comps = min(config.preprocessing.scrna.n_pcs, adata_sp_hvg.n_obs - 1, adata_sp_hvg.n_vars - 1)
    sc.tl.pca(adata_sp_hvg, svd_solver="arpack", n_comps=n_comps)

    # Index alignment validation for spatial PCA
    assert np.all(adata_sp.obs_names == adata_sp_hvg.obs_names), "HVG ve Spatial spot sıralaması uyuşmuyor!"
    adata_sp.obsm['X_pca'] = adata_sp_hvg.obsm['X_pca'].copy()
    adata_sp.obsm['X_features'] = adata_sp.obsm['X_pca'].copy()

    n_pcs_spatial = adata_sp.obsm['X_pca'].shape[1]
    logger.info(f"   Spatial neighbors hesaplanıyor ({n_pcs_spatial} PC, 15 komşu)...")
    sc.pp.neighbors(adata_sp, n_pcs=n_pcs_spatial, n_neighbors=15)
    report_progress(80)

    logger.info("   Spatial UMAP hesaplanıyor...")
    sc.tl.umap(adata_sp)
    logger.info("   Spatial Leiden kümeleniyor...")
    sc.tl.leiden(adata_sp, resolution=0.8)
    logger.info(f"   Spatial Leiden clusters: {adata_sp.obs['leiden'].nunique()}")
    report_progress(90)

    def smooth_spatial_expression(adata, genes, alpha=0.3):
        """Distance-weighted neighborhood smoothing to denoise Visium spatial data."""
        if 'connectivities' not in adata.obsp:
            logger.warning("   Spatial connectivities not found in adata.obsp. Skipping smoothing.")
            return
        W = adata.obsp['connectivities']
        row_sums = np.array(W.sum(axis=1)).flatten()
        row_sums = np.where(row_sums == 0, 1.0, row_sums)
        D_inv = sp.diags(1.0 / row_sums)
        W_norm = D_inv @ W
        
        valid_genes = [g for g in genes if g in adata.var_names]
        if not valid_genes:
            return
            
        logger.info(f"   Denoising {len(valid_genes)} niche genes using spatial neighbor-weights (alpha={alpha})...")
        idxs = [adata.var_names.get_loc(g) for g in valid_genes]
        
        E = adata.X[:, idxs]
        if sp.issparse(E):
            E = E.toarray()
        else:
            E = np.asarray(E)
            
        E_smoothed = (1.0 - alpha) * E + alpha * (W_norm @ E)
        
        if sp.issparse(adata.X):
            # Convert to lil matrix for memory-efficient assignment to avoid converting entire matrix to dense
            X_lil = adata.X.tolil()
            for i, idx in enumerate(idxs):
                X_lil[:, idx] = E_smoothed[:, i].reshape(-1, 1)
            adata.X = X_lil.tocsr()
        else:
            adata.X[:, idxs] = E_smoothed

    # M1 (anti-tümör) markerleri — config.yaml m1_macrophage ile aynı.
    # tam_polarization_score'un GERÇEK bir M1↔M2 karşıtlığı ölçebilmesi
    # için gerekli (bkz. denetim raporu bulgusu B-08).
    M1_MACROPHAGE_GENES = ['CD80', 'CD86', 'CXCL10', 'NOS2', 'IL12A', 'TNF', 'HLA-DRA']

    # Smooth niche-related expression patterns before scoring
    niche_genes = set(
        ['HIF1A', 'CA9', 'SLC2A1', 'LDHA', 'BNIP3'] +
        ['IL10', 'TGFB1', 'CD274', 'VSIG4', 'MRC1'] +
        M1_MACROPHAGE_GENES +
        ['HAVCR2', 'LAG3', 'PDCD1', 'CTLA4', 'TOX'] +
        ['VEGFA', 'ANGPT2', 'FLT1', 'KDR', 'PECAM1', 'ESM1'] +
        ['PROM1', 'NES', 'SOX2', 'OLIG2', 'NANOG', 'POU5F1', 'MYC', 'ALDH1A3'] +
        ['HK2', 'GPI', 'PFKP', 'ALDOA', 'GAPDH', 'PGK1', 'PKM', 'LDHA', 'SLC2A1']
    )
    smooth_spatial_expression(adata_sp, list(niche_genes), alpha=0.3)

    # TME Niche Scoring
    def score_niche(adata, gene_list, score_name):
        valid_genes = [g for g in gene_list if g in adata.var_names]
        if len(valid_genes) < 5:
            logger.warning(f"   Only {len(valid_genes)} valid genes found for {score_name}. Control group selection may be unreliable.")
        if valid_genes:
            sc.tl.score_genes(adata, gene_list=valid_genes, score_name=score_name)
        else:
            # NaN kullanılıyor (0.0 DEĞİL) — 0.0 "gerçekten düşük/yok"
            # anlamına gelen bir klinik iddiadır, oysa burada skor aslında
            # HİÇ hesaplanamadı (marker geni bulunamadı). Bu ayrımı
            # kaybetmek yanlış bir "hipoksi/immünsüpresyon yok" izlenimi
            # verebilir (bkz. denetim raporu bulgusu A-09).
            logger.warning(f"No valid genes found for {score_name}, marking as NaN (not computable).")
            adata.obs[score_name] = np.nan

    score_niche(adata_sp, ['HIF1A', 'CA9', 'SLC2A1', 'LDHA', 'BNIP3'], 'hypoxia_score')
    # `tam_polarization_score` eskiden `myeloid_suppression_score` ile
    # birebir aynı gen listesinden (sadece M2/immünsüpresif markerler)
    # hesaplanıyordu — tanım gereği "polarizasyon" M1 vs. M2 karşıtlığı
    # ölçmelidir. Burada M2 skorundan M1 skoru çıkarılarak gerçek bir
    # polarizasyon ekseni (pozitif = M2/pro-tümör ağırlıklı) üretilir
    # (bkz. denetim raporu bulgusu B-08).
    score_niche(adata_sp, ['IL10', 'TGFB1', 'CD274', 'VSIG4', 'MRC1'], 'myeloid_suppression_score')
    score_niche(adata_sp, M1_MACROPHAGE_GENES, '_m1_macrophage_score_tmp')
    if '_m1_macrophage_score_tmp' in adata_sp.obs and 'myeloid_suppression_score' in adata_sp.obs:
        adata_sp.obs['tam_polarization_score'] = (
            adata_sp.obs['myeloid_suppression_score'] - adata_sp.obs['_m1_macrophage_score_tmp']
        )
        del adata_sp.obs['_m1_macrophage_score_tmp']
    else:
        adata_sp.obs['tam_polarization_score'] = adata_sp.obs.get('myeloid_suppression_score', 0.0)
    score_niche(adata_sp, ['HAVCR2', 'LAG3', 'PDCD1', 'CTLA4', 'TOX'], 'tcell_exhaustion_score')
    score_niche(adata_sp, ['VEGFA', 'ANGPT2', 'FLT1', 'KDR', 'PECAM1', 'ESM1'], 'angiogenesis_score')

    score_niche(adata_sp, ['PROM1', 'NES', 'SOX2', 'OLIG2', 'NANOG', 'POU5F1', 'MYC', 'ALDH1A3'], 'stemness_score')
    score_niche(adata_sp, ['HK2', 'GPI', 'PFKP', 'ALDOA', 'GAPDH', 'PGK1', 'PKM', 'LDHA', 'SLC2A1'], 'glycolysis_score')
    report_progress(98)

    # ── Save Spatial ───────────────────────────────────────────
    spatial_out = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_preprocessed.h5ad"
    logger.info(f"   Spatial veri diske yazılıyor ({adata_sp.n_obs} spot, {adata_sp.n_vars} gen)...")
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

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        exit_with_error(f"Beklenmeyen hata: {str(e)}\n{traceback.format_exc()}")
