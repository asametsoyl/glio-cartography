import os
import re
import json
import urllib.request
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import fisher_exact, t
from PIL import Image, ImageDraw
import logging

logger = logging.getLogger("pathway_mapper")

# ============================================================
# UTILS & DOWNLOADERS
# ============================================================

def download_frontend_assets():
    """Downloads cytoscape.min.js to renderer/ if missing (offline fallback)."""
    renderer_dir = Path(__file__).parent.parent / "renderer"
    path = renderer_dir / "cytoscape.min.js"
    if not path.exists():
        url = "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.26.0/cytoscape.min.js"
        try:
            logger.info("🌐 Cytoscape.js indiriliyor: %s", url)
            os.makedirs(renderer_dir, exist_ok=True)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10.0) as response:
                path.write_bytes(response.read())
            logger.info("   ✅ Cytoscape.js yerel olarak kaydedildi: %s", path)
        except Exception as e:
            logger.error("   ❌ Cytoscape.js indirilemedi: %s", e)

# ============================================================
# PATHWAY DATABASE LOADER
# ============================================================

def load_pathway_db() -> dict:
    """Loads the pathway_db.json file containing pathways and GO terms."""
    db_path = Path(__file__).parent / "pathway_db.json"
    if db_path.exists():
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Yolak veritabanı okunamadı: %s", e)
    return {"pathways": []}

# ============================================================
# DIFFERENTIAL EXPRESSION (DEG) FINDER
# ============================================================

def load_gnn_attention_weights(data_json_path: Path, n_spots: int) -> list[dict]:
    """
    GNN data.json'dan gelen attention kenarlarını yükler.
    Döner: list[di] = {si: weight} -> di spotuna gelen kenarlar ve ağırlıkları.
    """
    incoming_edges = [{} for _ in range(n_spots)]
    try:
        with open(data_json_path, "r", encoding="utf-8") as f:
            gnn_data = json.load(f)
        spots = gnn_data.get("spots", [])
        for si_idx, spot in enumerate(spots):
            edges = spot.get("edges", {})
            for di_str, weight in edges.items():
                di_idx = int(di_str)
                if 0 <= di_idx < n_spots:
                    if si_idx not in incoming_edges[di_idx] or incoming_edges[di_idx][si_idx] < weight:
                        incoming_edges[di_idx][si_idx] = float(weight)
        return incoming_edges
    except Exception as e:
        logger.warning("data.json attention weights okunamadı: %s", e)
        return None


def compute_lr_activity(adata, ligand: str, receptor: str, data_json_path = None) -> np.ndarray:
    """
    L-R genlerinin ifadesine göre ligand-reseptör aktivitesini hesaplar.
    data_json_path verilmişse ve geçerliyse GNN attention ağırlıklarıyla çarpılarak paracrine hesaplama yapılır.
    """
    lig_gene = None
    rec_gene = None
    for g in adata.var_names:
        if g.upper() == ligand.upper():
            lig_gene = g
        if g.upper() == receptor.upper():
            rec_gene = g

    if not lig_gene or not rec_gene:
        logger.warning("Ligand '%s' veya reseptör '%s' dataset içinde bulunamadı.", ligand, receptor)
        return None

    # Get expressions
    X_lig = adata[:, lig_gene].X
    X_rec = adata[:, rec_gene].X
    expr_lig = X_lig.toarray().flatten() if hasattr(X_lig, "toarray") else np.asarray(X_lig).flatten()
    expr_rec = X_rec.toarray().flatten() if hasattr(X_rec, "toarray") else np.asarray(X_rec).flatten()

    activity = None
    if data_json_path is not None:
        p = Path(data_json_path)
        if p.exists():
            incoming_edges = load_gnn_attention_weights(p, adata.n_obs)
            if incoming_edges is not None:
                activity = np.zeros(adata.n_obs, dtype=np.float32)
                for di in range(adata.n_obs):
                    edges = incoming_edges[di]
                    if edges:
                        # sum_si (w_si_di * expr_ligand[si]) * expr_receptor[di]
                        activity[di] = sum(w * expr_lig[si] for si, w in edges.items()) * expr_rec[di]
                    else:
                        activity[di] = 0.0
                logger.info("   ✅ GNN attention-weighted L-R activity hesaplandı (n_obs=%d).", adata.n_obs)

    if activity is None:
        activity = expr_lig * expr_rec

    return activity


def find_lr_degs(adata, ligand: str, receptor: str, data_json_path = None, activity = None) -> list[str]:
    """
    Finds genes upregulated downstream of the L-R pair using Welch's t-test.
    Compares top 30% of spots (high L-R activity) vs bottom 50% of spots (low activity).
    """
    if activity is None:
        activity = compute_lr_activity(adata, ligand, receptor, data_json_path)
        if activity is None:
            return []

    n_spots = len(activity)
    if n_spots < 10 or activity.max() <= 0:
        return []

    # Gating thresholds
    high_thresh = np.percentile(activity, 70)
    low_thresh = np.percentile(activity, 50)

    # Fallback if thresholds are zero due to sparsity
    if high_thresh <= 0:
        high_thresh = activity.max() * 0.1
        low_thresh = 0.0

    high_mask = activity >= high_thresh
    low_mask = activity <= low_thresh

    # Ensure groups have enough spots
    if high_mask.sum() < 3 or low_mask.sum() < 3:
        return []

    # Vectorized Welch's t-test
    degs = []
    # Load entire expression matrix for testing
    X_dense = adata.X.toarray() if hasattr(adata.X, "toarray") else np.asarray(adata.X)
    
    # Calculate group stats
    n1 = high_mask.sum()
    n2 = low_mask.sum()

    m1 = X_dense[high_mask].mean(axis=0)
    m2 = X_dense[low_mask].mean(axis=0)

    s1 = X_dense[high_mask].var(axis=0, ddof=1) + 1e-9
    s2 = X_dense[low_mask].var(axis=0, ddof=1) + 1e-9

    # Welch's t-statistic
    t_stat = (m1 - m2) / np.sqrt(s1 / n1 + s2 / n2)
    # Satterthwaite degrees of freedom
    df = (s1 / n1 + s2 / n2)**2 / ((s1 / n1)**2 / (n1 - 1) + (s2 / n2)**2 / (n2 - 1) + 1e-9)

    # p-values
    p_vals = t.sf(np.abs(t_stat), df) * 2
    # Log Fold Change (Log2 FC)
    log_fc = np.log2(m1 + 1e-5) - np.log2(m2 + 1e-5)

    for idx, gene in enumerate(adata.var_names):
        # We only look for upregulated genes (log_fc > 0) with p < 0.05
        if p_vals[idx] < 0.05 and log_fc[idx] > 0.05:
            degs.append(gene)

    return degs

# ============================================================
# FISHER ENRICHMENT ANALYZER
# ============================================================

def calculate_pathway_enrichment(adata, ligand: str, receptor: str) -> list[dict]:
    """
    Performs Fisher's exact test enrichment on KEGG & GO pathways.
    Returns sorted pathways by significance.
    """
    degs = find_lr_degs(adata, ligand, receptor)
    if not degs:
        return []

    db = load_pathway_db()
    results = []

    universe_genes = set(adata.var_names)
    deg_set = set(degs)

    M = len(universe_genes) # Total universe size
    N = len(deg_set)       # Total study/DEGs size

    for path in db.get("pathways", []):
        path_genes = set(path["genes"])
        
        # Genes in pathway that are present in our dataset
        K_genes = path_genes.intersection(universe_genes)
        K = len(K_genes)

        # Overlapping DEGs in this pathway
        overlap_genes = deg_set.intersection(K_genes)
        x = len(overlap_genes)

        if x == 0:
            continue

        # Contingency table:
        #            In Pathway   Not In Pathway
        # In DEGs       x            N - x
        # Not In DEGs  K - x         M - K - (N - x)
        table = [
            [x, N - x],
            [K - x, M - K - (N - x)]
        ]
        
        oddsratio, pval = fisher_exact(table, alternative='greater')

        results.append({
            "id": path["id"],
            "name": path["name"],
            "type": path["type"],
            "category": path["category"],
            "overlap_count": x,
            "pathway_count": len(path_genes),
            "overlap_genes": sorted(list(overlap_genes)),
            "pvalue": float(pval),
            "odds_ratio": float(oddsratio) if np.isfinite(oddsratio) else 999.0
        })

    # Benjamini-Hochberg FDR correction
    if results:
        df_res = pd.DataFrame(results)
        pvals = df_res["pvalue"].values
        
        # Manual Benjamini-Hochberg FDR
        n = len(pvals)
        sorted_indices = np.argsort(pvals)
        sorted_pvals = pvals[sorted_indices]
        
        qvals = np.zeros(n)
        prev_q = 1.0
        for i in range(n - 1, -1, -1):
            q = (sorted_pvals[i] * n) / (i + 1)
            q = min(q, prev_q)
            qvals[i] = q
            prev_q = q
            
        fdr_adjusted = np.zeros(n)
        fdr_adjusted[sorted_indices] = qvals
        
        df_res["fdr_qvalue"] = fdr_adjusted
        results = df_res.sort_values("pvalue").to_dict(orient="records")

    return results

# ============================================================
# ZONE-STRATIFIED PATHWAY ENRICHMENT (GNN Entegrasyonu)
# ============================================================

def load_gnn_zone_masks(data_json_path: Path) -> dict[str, np.ndarray] | None:
    """
    GNN çıktısı data.json'dan her IVY GAP zonu için spot maske dizisi yükler.
    Dönen dict: {'Leading_Edge': np.array([True, False, ...]), ...}
    """
    if not data_json_path or not Path(data_json_path).exists():
        return None
    try:
        with open(data_json_path, "r", encoding="utf-8") as f:
            gnn_data = json.load(f)
        spots = gnn_data.get("spots", [])
        if not spots:
            return None
        # Mevcut zone isimlerini bul
        sample_zones = spots[0].get("zones", {})
        zone_names = list(sample_zones.keys())
        n_spots = len(spots)
        masks = {}
        for zone_name in zone_names:
            zone_scores = np.array([
                float(s.get("zones", {}).get(zone_name, 0.0))
                for s in spots
            ], dtype=np.float32)
            masks[zone_name] = zone_scores
        return masks
    except Exception as e:
        logger.warning("data.json okunamadı (zone maskeleri): %s", e)
        return None


def find_lr_degs_zonal(
    adata,
    ligand: str,
    receptor: str,
    data_json_path,
    zone_name: str,
    zone_threshold: float = 0.4
) -> list[str]:
    """
    GNN'nin spatial zone tahminlerini kullanarak zona özgü DEG analizi yapar.
    
    Parameterler:
        adata: Spatial AnnData nesnesi
        ligand, receptor: L-R çifti gen isimleri
        data_json_path: GNN çıktısı data.json dosyasının yolu
        zone_name: IVY GAP zone adı (örn. 'Leading_Edge', 'PN_Necrosis')
        zone_threshold: Minimum zone skoru (default 0.4)
    
    Döner: Upregulated DEG gen listesi (zone-filtered)
    """
    # 1. Zone maskesi yükle
    masks = load_gnn_zone_masks(Path(data_json_path))
    if masks is None or zone_name not in masks:
        logger.warning("Zone '%s' bulunamadı. Global analiz yapılıyor.", zone_name)
        return find_lr_degs(adata, ligand, receptor, data_json_path=data_json_path)
    
    zone_scores = masks[zone_name]
    
    # 2. AnnData spot sayısıyla eşleşiyor mu kontrol et
    if len(zone_scores) != adata.n_obs:
        logger.warning(
            "GNN spot sayısı (%d) ile AnnData obs sayısı (%d) eşleşmiyor. "
            "Global analiz yapılıyor.", len(zone_scores), adata.n_obs
        )
        return find_lr_degs(adata, ligand, receptor, data_json_path=data_json_path)
    
    # 3. Zone maskesini uygula
    zone_mask = zone_scores >= zone_threshold
    if zone_mask.sum() < 10:
        logger.warning(
            "Zone '%s' için yeterli spot bulunamadı (n=%d). "
            "Zone eşik değeri düşürülüyor.", zone_name, zone_mask.sum()
        )
        zone_threshold_relaxed = zone_threshold * 0.5
        zone_mask = zone_scores >= zone_threshold_relaxed
        if zone_mask.sum() < 5:
            return []
    
    logger.info("Zone '%s': %d / %d spot kullanılıyor.", zone_name, zone_mask.sum(), adata.n_obs)
    
    # 4. GNN attention-weighted L-R aktivitesini küresel olarak hesapla ve ardından filtrele
    activity_global = compute_lr_activity(adata, ligand, receptor, data_json_path)
    if activity_global is None:
        return []
    
    activity_zone = activity_global[zone_mask]
    adata_zone = adata[zone_mask].copy()
    return find_lr_degs(adata_zone, ligand, receptor, activity=activity_zone)


def calculate_zonal_pathway_enrichment(
    adata,
    ligand: str,
    receptor: str,
    data_json_path,
    zone_name: str | None = None,
    zone_threshold: float = 0.4
) -> list[dict]:
    """
    Zone-aware pathway enrichment. zone_name verilirse o zona özgü analiz,
    None verilirse global analiz yapar. GNN+Pathway birlikte kullanım noktası.
    """
    if zone_name and zone_name.lower() not in ("", "all", "tüm_tümör", "global"):
        degs = find_lr_degs_zonal(adata, ligand, receptor, data_json_path, zone_name, zone_threshold)
    else:
        degs = find_lr_degs(adata, ligand, receptor, data_json_path=data_json_path)
    
    if not degs:
        return []

    db = load_pathway_db()
    results = []
    universe_genes = set(adata.var_names)
    deg_set = set(degs)
    M = len(universe_genes)
    N = len(deg_set)

    for path in db.get("pathways", []):
        path_genes = set(path["genes"])
        K_genes = path_genes.intersection(universe_genes)
        K = len(K_genes)
        overlap_genes = deg_set.intersection(K_genes)
        x = len(overlap_genes)
        if x == 0:
            continue
        table = [[x, N - x], [K - x, M - K - (N - x)]]
        oddsratio, pval = fisher_exact(table, alternative='greater')
        results.append({
            "id": path["id"],
            "name": path["name"],
            "type": path["type"],
            "category": path["category"],
            "zone": zone_name or "Global",
            "overlap_count": x,
            "pathway_count": len(path_genes),
            "overlap_genes": sorted(list(overlap_genes)),
            "pvalue": float(pval),
            "odds_ratio": float(oddsratio) if np.isfinite(oddsratio) else 999.0
        })

    # BH FDR düzeltmesi
    if results:
        df_res = pd.DataFrame(results)
        pvals = df_res["pvalue"].values
        n = len(pvals)
        sorted_indices = np.argsort(pvals)
        sorted_pvals = pvals[sorted_indices]
        qvals = np.zeros(n)
        prev_q = 1.0
        for i in range(n - 1, -1, -1):
            q = (sorted_pvals[i] * n) / (i + 1)
            q = min(q, prev_q)
            qvals[i] = q
            prev_q = q
        fdr_adjusted = np.zeros(n)
        fdr_adjusted[sorted_indices] = qvals
        df_res["fdr_qvalue"] = fdr_adjusted
        results = df_res.sort_values("pvalue").to_dict(orient="records")

    return results


# ============================================================

def fetch_dynamic_kegg_coords(pathway_id: str) -> dict:
    """Fetches coordinates dynamically from KEGG REST API as a fallback."""
    url = f"https://rest.kegg.jp/get/{pathway_id}/image"
    coords_map = {}
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5.0) as response:
            html = response.read().decode('utf-8')
        
        # Match coords="x1,y1,x2,y2" href="..." title="GENE1, GENE2..."
        matches = re.findall(r'coords="(\d+),(\d+),(\d+),(\d+)".*?title="([^"]+)"', html)
        for x1, y1, x2, y2, title in matches:
            genes_part = title.split(' (')[0] # Remove hsa: details
            genes = [g.strip() for g in genes_part.split(',')]
            for gene in genes:
                coords_map[gene.upper()] = [int(x1), int(y1), int(x2), int(y2)]
    except Exception as e:
        logger.warning("KEGG koordinatları indirilemedi (%s): %s", pathway_id, e)
    return coords_map

def generate_highlighted_kegg_image(pathway_id: str, ligand: str, receptor: str, degs: list[str], output_dir: Path) -> Path | None:
    """
    Downloads KEGG PNG map, highlights ligand-receptor in Red, and downstream DEGs in Blue.
    Returns path to the temporary highlighted PNG image file.
    """
    kegg_cache_dir = output_dir / "kegg_cache"
    os.makedirs(kegg_cache_dir, exist_ok=True)

    img_path = kegg_cache_dir / f"{pathway_id}.png"
    
    # 1. Download KEGG PNG map if not cached
    if not img_path.exists():
        url = f"https://rest.kegg.jp/get/{pathway_id}/image"
        try:
            logger.info("🌐 KEGG haritası indiriliyor: %s", url)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10.0) as response:
                img_path.write_bytes(response.read())
        except Exception as e:
            logger.error("KEGG haritası indirilemedi: %s", e)
            return None

    # 2. Get coords map
    db = load_pathway_db()
    path_data = None
    for p in db.get("pathways", []):
        if p["id"] == pathway_id:
            path_data = p
            break

    coords_map = {}
    if path_data and "offline_coords" in path_data:
        coords_map = path_data["offline_coords"]
    
    # If offline coords are empty or gene is missing, try fetching dynamically
    if not coords_map:
        coords_map = fetch_dynamic_kegg_coords(pathway_id)

    if not coords_map:
        logger.warning("Harita koordinatları bulunamadı: %s", pathway_id)
        return img_path # Return raw map if no coords available

    # 3. Open image and highlight
    try:
        with Image.open(img_path) as img:
            rgba_img = img.convert("RGBA")
            
            # Make overlays
            overlay = Image.new("RGBA", rgba_img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Highlighting variables
            deg_set = set(g.upper() for g in degs)
            lig_upper = ligand.upper()
            rec_upper = receptor.upper()

            for gene, box in coords_map.items():
                gene_upper = gene.upper()
                x1, y1, x2, y2 = box

                # Red overlay for ligand / receptor
                if gene_upper == lig_upper or gene_upper == rec_upper:
                    draw.rectangle([x1, y1, x2, y2], fill=(239, 68, 68, 120)) # #ef4444
                # Blue overlay for upregulated DEGs in pathway
                elif gene_upper in deg_set:
                    draw.rectangle([x1, y1, x2, y2], fill=(59, 130, 246, 100)) # #3b82f6

            # Combine original and overlay
            highlighted_img = Image.alpha_composite(rgba_img, overlay)
            
            # Save highlighted file
            out_file = kegg_cache_dir / f"{pathway_id}_{lig_upper}_{rec_upper}_highlighted.png"
            highlighted_img.save(out_file, "PNG")
            return out_file
    except Exception as e:
        logger.error("Harita overlay çizim hatası: %s", e)
        return img_path
