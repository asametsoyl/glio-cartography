#!/usr/bin/env python3
"""Stage 5: Research-use report generation."""
import os, sys, json, base64
from pathlib import Path
from datetime import datetime
import traceback

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

OUTPUT_DIR = Path(os.environ["GLIO_OUTPUT_DIR"])
PATIENT_ID = os.environ.get("GLIO_PATIENT_ID", "Patient_A")
GLIO_LANG = os.environ.get("GLIO_LANG", "tr")
is_english = (GLIO_LANG == "en")

from loguru import logger
import locale_logger
import html as html_module
from jinja2 import Template

try:
    import numpy as np
except ImportError:
    np = None

try:
    import anndata as ad
except ImportError:
    ad = None

def exit_with_error(message):
    logger.error(message)
    print(json.dumps({"stage": "report", "status": "error", "message": message}))
    sys.exit(1)

def global_exception_handler(exctype, value, tb):
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    exit_with_error(f"Rapor aşamasında beklenmeyen hata: {value}\n{error_msg}")

sys.excepthook = global_exception_handler

# ── Safe Helper Functions ──────────────────────────────────
def escape_html(val):
    if val is None:
        return ""
    return html_module.escape(str(val))

def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Dosya bulunamadı: {path}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse hatası ({path}): {e}")
    except Exception as e:
        logger.error(f"Dosya okuma hatası ({path}): {e}")
    return {}

def interpolate_color(color1, color2, t):
    c1 = color1.lstrip('#')
    c2 = color2.lstrip('#')
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"

def generate_pubmed_references(dominant_lr, pathways):
    """
    ÖNEMLİ (bilimsel dürüstlük notu): Bu fonksiyon GERÇEK makale başlıkları
    döndürmez — `url` alanı her zaman bir PubMed ARAMA sorgusudur, belirli
    bir makaleye link değildir. Önceki sürüm, şablon metninden üretilen
    cümleleri tırnak içinde "title" olarak sunuyordu; bu, gerçek bir
    literatür alıntısıyla karıştırılabilirdi (bkz. denetim raporu bulgusu
    A-14). Bu yüzden dönen alan artık `search_query` — arama önerisi olarak
    açıkça etiketlenir, gerçek bir makale başlığı gibi tırnaklanmaz.
    """
    refs = []
    if dominant_lr and dominant_lr != "N/A":
        refs.append({
            "topic": f"L-R Axis: {dominant_lr}" if is_english else f"L-R Ekseni: {dominant_lr}",
            "search_query": f"{dominant_lr} glioblastoma signaling",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/?term={dominant_lr.replace('-', '+')}+glioblastoma"
        })
    for p in pathways:
        refs.append({
            "topic": f"Pathway: {p}" if is_english else f"Yolak: {p}",
            "search_query": f"{p} signaling pathway glioblastoma",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/?term={p.replace('_', '+')}+glioblastoma"
        })
    return refs

def img_to_b64(path):
    try:
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode()
    except Exception as e:
        logger.warning(f"Resim base64'e dönüştürülemedi ({path}): {e}")
        return ""

# ── Analiz Güvenilirlik / Veri Kalitesi Özeti [GELİŞTİRME] ──
# Bu oturumda eklenen birçok dürüstlük sinyali (fallback_used,
# cross_method_agreement, cell_marker_source,
# ivy_gap_validation.is_independent_validation vb.) önceden yalnızca
# JSON dosyalarında/loglarda dağınık duruyordu. Bu fonksiyon bunları TEK
# bir görünür panelde toplar, böylece rapor okuyan kişi hangi
# bulguların ne kadar güvenilir olduğunu ayrı ayrı JSON dosyalarını
# kazmadan görebilir.
def compute_data_quality_summary(gnn_sum, deconv_sum):
    items = []
    level_rank = {"high": 2, "medium": 1, "low": 0}
    overall = "high"

    def downgrade(to):
        nonlocal overall
        if level_rank[to] < level_rank[overall]:
            overall = to

    level_label = {
        "high": ("Yüksek", "Good") if not is_english else ("High", "Good"),
        "medium": ("Orta", "Warning") if not is_english else ("Medium", "Warning"),
        "low": ("Düşük", "Warning") if not is_english else ("Low", "Warning"),
    }
    level_color = {"high": "var(--success)", "medium": "#F4A261", "low": "var(--danger)"}

    # 1) Dekonvolüsyon yöntemi / fallback durumu
    fallback_used = bool(deconv_sum.get("fallback_used", False))
    requested = deconv_sum.get("requested_method", "?")
    actual = deconv_sum.get("deconv_method", "?")
    dm_level = "low" if fallback_used else "high"
    downgrade(dm_level)
    items.append({
        "label": "Dekonvolüsyon Yöntemi" if not is_english else "Deconvolution Method",
        "value": actual.upper() if actual else "N/A",
        "note": (
            f"İstenen '{requested.upper()}' başarısız oldu, basit skor-tabanlı fallback kullanıldı."
            if fallback_used else
            f"İstenen yöntem ('{requested.upper()}') başarıyla çalıştı."
        ) if not is_english else (
            f"Requested '{requested.upper()}' failed; a simple score-based fallback was used."
            if fallback_used else
            f"Requested method ('{requested.upper()}') ran successfully."
        ),
        "level": dm_level,
    })

    # 2) Çapraz-yöntem örtüşmesi (varsa)
    cma = deconv_sum.get("cross_method_agreement", None)
    if cma is not None:
        cma_level = "high" if cma >= 0.5 else ("medium" if cma >= 0.2 else "low")
        downgrade(cma_level)
        items.append({
            "label": "Çapraz-Yöntem Örtüşmesi" if not is_english else "Cross-Method Agreement",
            "value": f"r={cma:.2f}",
            "note": (
                "Ana yöntem, bağımsız NNLS tahminiyle karşılaştırıldı (korelasyon)."
                if not is_english else
                "Primary method compared against an independent NNLS estimate (correlation)."
            ),
            "level": cma_level,
        })

    # 3) Hücre-tipi marker paneli kaynağı
    marker_source = deconv_sum.get("cell_marker_source", "")
    n_marker_types = deconv_sum.get("n_cell_marker_types", None)
    is_fallback_panel = "hardcoded_fallback" in str(marker_source)
    ms_level = "low" if is_fallback_panel else "high"
    downgrade(ms_level)
    items.append({
        "label": "Hücre-Tipi Marker Paneli" if not is_english else "Cell-Type Marker Panel",
        "value": (f"{n_marker_types} types" if is_english else f"{n_marker_types} tip") if n_marker_types is not None else "N/A",
        "note": (
            "config.yaml doğrulanamadı, sabit kodlanmış 8 tiplik acil durum paneline düşüldü."
            if is_fallback_panel else
            "config.yaml'daki tam küratörlü marker paneli kullanıldı."
        ) if not is_english else (
            "config.yaml could not be validated; fell back to the hardcoded 8-type emergency panel."
            if is_fallback_panel else
            "The full curated marker panel from config.yaml was used."
        ),
        "level": ms_level,
    })

    # 4) Ortalama dekonvolüsyon güveni
    avg_conf = deconv_sum.get("avg_confidence", None)
    if avg_conf is not None:
        ac_level = "high" if avg_conf >= 0.6 else ("medium" if avg_conf >= 0.4 else "low")
        downgrade(ac_level)
        items.append({
            "label": "Ortalama Dekonvolüsyon Güveni" if not is_english else "Mean Deconvolution Confidence",
            "value": f"%{avg_conf*100:.1f}",
            "note": "" ,
            "level": ac_level,
        })

    # 5) GNN iç-tutarlılık kontrolü (bağımsız doğrulama DEĞİL)
    ivy = gnn_sum.get("ivy_gap_validation", {})
    if ivy:
        items.append({
            "label": "IVY GAP Tutarlılık Kontrolü" if not is_english else "IVY GAP Consistency Check",
            "value": f"%{ivy.get('accuracy', 0)*100:.1f}",
            "note": (
                "Bu, modelin KENDİ eğitim hedefiyle tutarlılığıdır — bağımsız histoloji doğrulaması DEĞİLDİR."
                if not is_english else
                "This is consistency with the model's OWN training target — NOT an independent histology validation."
            ),
            "level": "medium",
        })

    # 5b) GERÇEK Ivy GAP ISH referansına karşı BAĞIMSIZ doğrulama [GELİŞTİRME]
    real_ivy = gnn_sum.get("real_ivy_gap_validation", {})
    if real_ivy and real_ivy.get("diagonal_mean_correlation") is not None:
        diag_r = real_ivy["diagonal_mean_correlation"]
        top1 = real_ivy.get("top1_match_accuracy")
        riv_level = "high" if diag_r >= 0.4 else ("medium" if diag_r >= 0.15 else "low")
        downgrade(riv_level)
        items.append({
            "label": "Gerçek Ivy GAP Doğrulaması (Bağımsız)" if not is_english else "Real Ivy GAP Validation (Independent)",
            "value": f"r={diag_r:.2f}" + (f", top1=%{top1*100:.0f}" if top1 is not None else ""),
            "note": (
                f"Allen Institute Ivy GAP hasta kohortundan GERÇEK, bağımsız ISH verisine karşı "
                f"({real_ivy.get('n_reference_genes', 0)} referans gen) — modelin kendi hedefine "
                f"karşı değil, farklı hastalar/farklı teknoloji."
                if not is_english else
                f"Against REAL, independent ISH data from the Allen Institute Ivy GAP patient "
                f"cohort ({real_ivy.get('n_reference_genes', 0)} reference genes) — not the "
                f"model's own target; different patients, different technology."
            ),
            "level": riv_level,
        })

    overall_label, _ = level_label[overall]
    return {
        "overall_level": overall,
        "overall_label": overall_label,
        "overall_color": level_color[overall],
        "items": items,
    }


# ── Cell composition summary ────────────────────────────────
def compute_composition_summary(deconv_sum):
    """Mean tumor / myeloid / T-cell fractions from the deconvolution summary.

    Descriptive only: expression and deconvolution data cannot establish WHO
    grade, IDH mutation, MGMT status or a treatment recommendation, so none
    of those are produced here.
    """
    mean_props = deconv_sum.get("mean_proportions", {})
    def _sum_fraction(needles, exclude=()):
        return float(sum(v for k, v in mean_props.items()
                         if any(n in k.lower() for n in needles)
                         and not any(x in k.lower() for x in exclude)))
    return {
        "tumor_frac": _sum_fraction(("tumor", "malignant", "gbm"), exclude=("macrophage", "tam")),
        "myeloid_frac": _sum_fraction(("myeloid", "microglia", "macrophage", "monocyte")),
        "tcell_frac": _sum_fraction(("t_cell", "t-cell", "treg", "lymph")),
    }


def main() -> None:
    reports_out = OUTPUT_DIR / "reports"
    reports_out.mkdir(parents=True, exist_ok=True)

    # ── Load summaries safely ───────────────────────────────────
    gnn_summary   = load_json(OUTPUT_DIR / "gnn" / "gnn_summary.json")
    deconv_summary= load_json(OUTPUT_DIR / "deconvolution" / "deconvolution_summary.json")
    prep_summary  = load_json(OUTPUT_DIR / "preprocessing" / "preprocessing_summary.json")

    ZONE_NAMES = gnn_summary.get("zones", [])
    CT_NAMES   = gnn_summary.get("ct_names", [])
    test_mse   = gnn_summary.get("test_mse", 0)
    n_spots    = gnn_summary.get("n_spots", 0)

    # ── Safe Defaults to Prevent NameError ─────────────────────
    spots_data = []
    zonal_contrast = {}
    pathways = ['PI3K_AKT_mTOR', 'MAPK_ERK', 'JAK_STAT', 'NFkB']
    pathway_avgs = {p: 0.0 for p in pathways}
    spatial_summary = "Özet verisi yüklenemedi." if not is_english else "Summary data could not be loaded."
    top_pathway = "N/A"
    top_lr = [('SPP1-CD44', 0.0)]
    myeloid_avg = 0.0
    stats_calc = {
        'n_spots': 0,
        'myeloid_avg': myeloid_avg,
        'pathway_avgs': pathway_avgs,
        'top_lr': top_lr
    }
    dominant_lr_val = 'SPP1-CD44'

    # ── Load data.json safely ──────────────────────────────────
    data_json_path = OUTPUT_DIR / "gnn" / "data.json"
    if data_json_path.exists():
        try:
            file_size = data_json_path.stat().st_size
            if file_size > 300 * 1024 * 1024:
                logger.warning(f"data.json çok büyük ({file_size / (1024*1024):.1f} MB), özet istatistikler hesaplanamayabilir.")
            
            with open(data_json_path, encoding='utf-8') as f:
                data_json = json.load(f)
            spots_data = data_json.get("spots", [])
            zonal_contrast = data_json.get("zonal_contrast", {})

            # Normalize pathway keys to fall back on core IDs if KEGG database is active
            PATHWAY_MAP = {
                'PI3K_AKT_mTOR': 'hsa04151',
                'MAPK_ERK': 'hsa04010',
                'JAK_STAT': 'hsa04630',
                'NFkB': 'hsa04064'
            }
            for s in spots_data:
                spot_pathways = s.get('pathways', {})
                for core_k, kegg_k in PATHWAY_MAP.items():
                    if kegg_k in spot_pathways:
                        spot_pathways[core_k] = spot_pathways[kegg_k]

            if zonal_contrast and 'pathways' in zonal_contrast:
                for z in list(zonal_contrast['pathways'].keys()):
                    for core_k, kegg_k in PATHWAY_MAP.items():
                        if kegg_k in zonal_contrast['pathways'][z]:
                            zonal_contrast['pathways'][z][core_k] = zonal_contrast['pathways'][z][kegg_k]
            
            # Calculate pathway averages
            pathway_totals = {p: 0.0 for p in pathways}
            pathway_counts = {p: 0 for p in pathways}
            for s in spots_data:
                spot_pathways = s.get("pathways", {})
                for p in pathways:
                    if p in spot_pathways:
                        pathway_totals[p] += float(spot_pathways[p])
                        pathway_counts[p] += 1
            
            for p in pathways:
                if pathway_counts[p] > 0:
                    pathway_avgs[p] = pathway_totals[p] / pathway_counts[p]
                else:
                    pathway_avgs[p] = 0.0
                    
            # Mean myeloid (microglia/macrophage/monocyte) fraction across spots.
            myeloid_total = 0.0
            lr_totals = {}
            _MYELOID_KEYWORDS = ("microglia", "macrophage", "myeloid", "monocyte")
            for s_ in spots_data:
                ct = s_.get('ct', {})
                myeloid_total += sum(
                    float(v) for k, v in ct.items()
                    if any(kw in k.lower() for kw in _MYELOID_KEYWORDS)
                )
                for lr_key, val in s_.get('lr', {}).items():
                    lr_totals[lr_key] = lr_totals.get(lr_key, 0.0) + float(val)

            myeloid_avg = (myeloid_total / len(spots_data)) * 100 if spots_data else 0

            top_lr = sorted(
                [(k, v / len(spots_data)) for k, v in lr_totals.items()],
                key=lambda x: x[1], reverse=True
            )[:4]
            
            stats_calc = {
                'n_spots': len(spots_data),
                'myeloid_avg': myeloid_avg,
                'pathway_avgs': pathway_avgs,
                'top_lr': top_lr
            }
            
            # Now generate synthesis
            top_pathway = max(pathway_avgs, key=pathway_avgs.get) if pathway_avgs else "PI3K_AKT_mTOR"
            dominant_lr_val = top_lr[0][0] if top_lr else "SPP1-CD44"
            top_pathway_safe = escape_html(top_pathway)
            dominant_lr_safe = escape_html(dominant_lr_val)
            if is_english:
                spatial_summary = (
                    f"The spatial transcriptomic analysis covered {stats_calc['n_spots']:,} spots. "
                    f"The mean estimated myeloid fraction was {stats_calc['myeloid_avg']:.1f}%. "
                    f"Among the tested ligand-receptor pairs, '{dominant_lr_safe}' had the highest mean score; "
                    f"this is a candidate signaling interaction, not evidence of an active interaction. "
                    f"The pathway signature with the highest mean activity was '{top_pathway_safe}'. "
                    "These are exploratory research outputs and require independent experimental validation."
                )
            else:
                spatial_summary = (
                    f"Uzamsal transkriptomik analiz {stats_calc['n_spots']:,} spotu kapsadı. "
                    f"Tahmin edilen ortalama miyeloid oranı %{stats_calc['myeloid_avg']:.1f} idi. "
                    f"Test edilen ligand-reseptör çiftleri arasında en yüksek ortalama skoru '{dominant_lr_safe}' aldı; "
                    f"bu, aktif bir etkileşimin kanıtı değil, aday bir sinyal etkileşimidir. "
                    f"Ortalama aktivitesi en yüksek yolak imzası '{top_pathway_safe}' idi. "
                    "Bunlar keşifsel araştırma çıktılarıdır ve bağımsız deneysel doğrulama gerektirir."
                )
        except Exception as e:
            logger.warning(f"data.json okunurken/sentezlenirken hata oluştu: {e}")

    # ── Downstream Pathway Enrichment Analysis (Rapor İçin) ─────
    enrichment_rows = ""
    try:
        spatial_path = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
        if spatial_path.exists():
            import anndata as ad
            from pathway_mapper import calculate_pathway_enrichment
            
            parts = dominant_lr_val.split('-')
            if len(parts) == 2:
                ligand_g, receptor_g = parts[0], parts[1]
                adata_sp = ad.read_h5ad(spatial_path)
                enrich_results = calculate_pathway_enrichment(adata_sp, ligand_g, receptor_g)
                
                # Render top 5 enriched pathways table
                for path in enrich_results[:5]:
                    enrichment_rows += f"""<tr>
                        <td><strong>{escape_html(path['id'])}</strong></td>
                        <td>{escape_html(path['name'])}</td>
                        <td><span style="background:rgba(0,212,255,0.12); color:#00d4ff; padding:2px 6px; border-radius:4px; font-size:0.7rem; font-weight:bold;">{escape_html(path['type'])}</span></td>
                        <td>{path['overlap_count']} / {path['pathway_count']}</td>
                        <td>{path['pvalue']:.2e}</td>
                        <td>{path['fdr_qvalue']:.2e}</td>
                    </tr>"""
                
    except Exception as e_enrich:
        logger.warning(f"Rapor yolak zenginleştirme hesaplama hatası: {e_enrich}")

    if not enrichment_rows:
        fallback_enrich = "No enriched downstream pathways detected." if is_english else "Zenginleştirilmiş downstream yolak saptanamadı."
        enrichment_rows = f"<tr><td colspan='6' style='text-align:center; color:#999;'>{fallback_enrich}</td></tr>"
    # Cell composition summary
    composition = compute_composition_summary(deconv_summary)

    # Analiz güvenilirlik / veri kalitesi özeti [GELİŞTİRME]
    data_quality = compute_data_quality_summary(gnn_summary, deconv_summary)

    fig_dirs = [
        OUTPUT_DIR / "publication_figures",
        OUTPUT_DIR / "deconvolution",
        OUTPUT_DIR / "gnn",
    ]
    figures = []
    for d in fig_dirs:
        if d.exists():
            for f in sorted(d.glob("*.png")):
                figures.append(f)

    # Generate Figures HTML
    fig_html = ""
    for fig_path in figures[:12]:  # max 12 figures
        b64 = img_to_b64(fig_path)
        if b64:
            fig_html += f"""
            <div class="figure-card">
                <img src="data:image/png;base64,{b64}" alt="{escape_html(fig_path.stem)}">
                <p class="fig-caption">{escape_html(fig_path.stem.replace('_', ' ').title())}</p>
            </div>"""

    corr_rows = ""
    for ct, vals in gnn_summary.get("correlations", {}).items():
        pr = vals.get("pearson_r", 0)
        sr = vals.get("spearman_r", 0)
        sig = "✅" if abs(pr) > 0.5 else "⚠️"
        corr_rows += f"<tr><td>{escape_html(ct)}</td><td>{pr:.4f}</td><td>{sr:.4f}</td><td>{sig}</td></tr>"

    report_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Executive Summary Calculations (Using Safe Escaping)
    dominant_lr_val_safe = escape_html(dominant_lr_val)

    if is_english:
        exec_summary = (
            f"This research analysis estimated a mean <strong>{myeloid_avg:.1f}% myeloid</strong> "
            f"fraction across the tissue. <strong>{dominant_lr_val_safe}</strong> was the highest-scoring tested interaction axis. "
            "These are computational hypotheses, not diagnostic, prognostic, or treatment findings."
        )
    else:
        exec_summary = (
            f"Bu araştırma analizinde doku genelinde ortalama <strong>%{myeloid_avg:.1f} miyeloid</strong> "
            f"oranı tahmin edildi. Test edilen etkileşimler içinde <strong>{dominant_lr_val_safe}</strong> en yüksek skoru aldı. "
            "Bunlar tanı, prognoz veya tedavi sonucu değil, doğrulanması gereken hesapsal hipotezlerdir."
        )

    # PubMed References
    pubmed_refs = generate_pubmed_references(dominant_lr_val, pathways)
    half = len(pubmed_refs) // 2
    
    show_in_pubmed_text = "🔍 Search PubMed &rarr;" if is_english else "🔍 PubMed'de Ara &rarr;"
    search_lbl = "Search" if is_english else "Arama"

    ref_html_left = "".join(f"""
        <div style="margin: 12px 0; font-size: 0.85rem; line-height: 1.5; border-bottom: 1px dashed var(--border); padding-bottom: 8px;">
            <span style="font-weight: bold; color: var(--accent);">{escape_html(r['topic'])}:</span><br>
            <span style="color: #ccc; font-size: 0.8rem;">{search_lbl}: {escape_html(r['search_query'])}</span><br>
            <a href="{escape_html(r['url'])}" target="_blank" style="color: var(--accent); text-decoration: none; font-size: 0.78rem; font-weight: 600;">{show_in_pubmed_text}</a>
        </div>
    """ for r in pubmed_refs[:half])

    ref_html_right = "".join(f"""
        <div style="margin: 12px 0; font-size: 0.85rem; line-height: 1.5; border-bottom: 1px dashed var(--border); padding-bottom: 8px;">
            <span style="font-weight: bold; color: var(--accent);">{escape_html(r['topic'])}:</span><br>
            <span style="color: #ccc; font-size: 0.8rem;">{search_lbl}: {escape_html(r['search_query'])}</span><br>
            <a href="{escape_html(r['url'])}" target="_blank" style="color: var(--accent); text-decoration: none; font-size: 0.78rem; font-weight: 600;">{show_in_pubmed_text}</a>
        </div>
    """ for r in pubmed_refs[half:])

    version_stamp = "Glio-Cartography v3.0 [Research Use Only]"

    # Safe HTML Template construction
    patient_id_safe = escape_html(PATIENT_ID)
    version_stamp_safe = escape_html(version_stamp)
    report_date_safe = escape_html(report_date)
    top_pathway_safe = escape_html(top_pathway)

    # Localized UI elements
    T_HTML_LANG = "en" if is_english else "tr"
    T_TITLE = f"Glio-Cartography — Research Report: {patient_id_safe}" if is_english else f"Glio-Cartography — Araştırma Raporu: {patient_id_safe}"
    T_TME_ATLAS = "Spatial Tumor Microenvironment Atlas" if is_english else "Spatial Tümör Mikroçevre Atlası"
    T_PATIENT = f"Patient: {patient_id_safe}" if is_english else f"Hasta: {patient_id_safe}"
    T_DOWNLOAD_PDF = "📥 Download PDF" if is_english else "📥 PDF Olarak İndir"
    T_SUMMARY_TITLE = "📋 Research Summary &amp; Spatial Model Index" if is_english else "📋 Araştırma Özeti &amp; Uzamsal Model İndeksi"
    T_EXEC_SUMMARY = "📋 Executive Summary" if is_english else "📋 Yönetici Özeti"
    
    T_GENERAL_METRICS = "📊 General Metrics" if is_english else "📊 Genel Metrikler"
    T_SPOTS_ANALYZED = "Spots Analyzed" if is_english else "Analiz Edilen Spot"
    T_CELL_TYPES = "Cell Types" if is_english else "Hücre Tipi"
    T_DECONV_CONFIDENCE = "Deconvolution Confidence" if is_english else "Dekonvolüsyon Güveni"
    T_GNN_TEST_MSE = "GNN Test MSE" if is_english else "GNN Test MSE"

    T_DATA_QUALITY_TITLE = "🔎 Analysis Reliability Summary" if is_english else "🔎 Analiz Güvenilirlik Özeti"
    T_DATA_QUALITY_DESC = (
        "This panel aggregates the pipeline's own internal confidence signals for THIS run "
        "(method fallbacks, cross-method agreement, marker panel coverage, proxy-metric confidence). "
        "It reflects computational reliability, not clinical certainty."
    ) if is_english else (
        "Bu panel, bu çalıştırma için pipeline'ın kendi iç güven sinyallerini "
        "(yöntem fallback'leri, çapraz-yöntem örtüşmesi, marker paneli kapsamı, vekil-metrik güveni) "
        "tek yerde toplar. Hesapsal güvenilirliği yansıtır, klinik kesinliği DEĞİL."
    )
    T_OVERALL_LEVEL = "Genel Değerlendirme" if not is_english else "Overall Assessment"

    T_RUO_WARNING = "⚠️ These evaluations are computational predictions. Histopathology and molecular testing are required for clinical validation." if is_english else "⚠️ Bu değerlendirmeler hesapsal tahmindir. Klinik onay için histopatoloji ve moleküler testler gereklidir."
    
    T_COMPOSITION_TITLE = "Estimated Cell Composition" if is_english else "Tahmini Hücre Kompozisyonu"
    T_TUMOR_LBL = "Tumor Fraction:" if is_english else "Tümör Fraksiyon:"
    T_MYELOID_LBL = "Myeloid:" if is_english else "Miyeloid:"
    T_TCELL_LBL = "T-Cell:" if is_english else "T-Hücre:"

    T_SUMMARY_FINDINGS_TITLE = "📋 Summary of Spatial Findings" if is_english else "📋 Uzamsal Bulguların Özeti"
    T_DOWNSTREAM_PATHWAY_TITLE = "🧬 Downstream Pathway Activation" if is_english else "🧬 Downstream Yolak Aktivasyonu"
    T_AVG_PATHWAY_SCORES = "Average Downstream Pathway Scores" if is_english else "Ortalama Downstream Yolak Skorları"
    T_DOMINANT_PATHWAY = "Dominant Downstream Pathway" if is_english else "Baskın Downstream Yolak"
    T_DOMINANT_PATHWAY_DESC = "The pathway signature with the highest mean activity across the tissue (a descriptive score, not evidence of causal pathway activation)." if is_english else "Doku genelinde ortalama aktivitesi en yüksek yolak imzası (betimleyici bir skordur, nedensel yolak aktivasyonunun kanıtı değildir)."
    
    T_ENRICHED_PATHWAYS_TITLE = f"🧬 L-R Downstream Enriched Pathways ({dominant_lr_val_safe})" if is_english else f"🧬 L-R Downstream Zenginleştirilmiş Yolaklar ({dominant_lr_val_safe})"
    T_ENRICHED_PATHWAYS_DESC = f"Significant downstream pathways induced by the dominant {dominant_lr_val_safe} signaling axis:" if is_english else f"Baskın {dominant_lr_val_safe} sinyalleşme ekseninin uyardığı anlamlı downstream yolaklar:"
    T_PATHWAY_ID = "Pathway ID" if is_english else "Yolak ID"
    T_PATHWAY_NAME = "Pathway Name" if is_english else "Yolak Adı"
    T_TYPE = "Type" if is_english else "Tip"
    T_OVERLAP = "Overlap / Pathway" if is_english else "Overlap / Yolak"
    T_PVALUE = "p-Value" if is_english else "p-Değeri"
    T_FDR = "FDR q-Value" if is_english else "FDR q-Değeri"
    
    T_ZONAL_TITLE = "📊 Zonal Pathway Contrast Analysis" if is_english else "📊 Zonal Yolak Kontrast Analizi"
    T_PATHOLOGICAL_ZONE = "Pathological Zone" if is_english else "Patolojik Zon"
    
    T_CELLTYPE_CORR_TITLE = "🔬 Cell Type Correlations (GNN)" if is_english else "🔬 Hücre Tipi Korelasyonları (GNN)"
    T_CELL_TYPE = "Cell Type" if is_english else "Hücre Tipi"
    T_SIGNIFICANCE = "Significance" if is_english else "Anlamlılık"
    
    T_VISUALIZATIONS = "🗺️ Visualizations" if is_english else "🗺️ Görselleştirmeler"
    T_PIPELINE_SUMMARY = "📋 Pipeline Summary" if is_english else "📋 Pipeline Özeti"
    T_PREPROCESSING = "Preprocessing" if is_english else "Ön İşleme"
    T_DECONVOLUTION = "Deconvolution" if is_english else "Dekonvolüsyon"
    T_CELLS_LABEL = "scRNA Cells" if is_english else "scRNA Hücre"
    T_SPOTS_LABEL = "Spatial Spots" if is_english else "Spatial Spot"
    T_CLUSTERS_LABEL = "Leiden Clusters" if is_english else "Leiden Küme"
    T_CELL_TYPES_COUNT = "Cell Types" if is_english else "Hücre Tipi"
    T_METHOD_LABEL = "Method" if is_english else "Yöntem"
    
    T_PUBMED_REFS = "📚 Literature Search Suggestions (PubMed)" if is_english else "📚 Literatür Arama Önerileri (PubMed)"
    T_PUBMED_DESC = "PubMed search suggestions for the ligand-receptor axis and pathways mentioned in this report:" if is_english else "Raporda geçen ligand-reseptör ekseni ve yolaklar için PubMed arama önerileri:"
    T_AUTO_GENERATED = "This report was generated automatically for research use only. It is not a diagnostic or clinical document." if is_english else "Bu rapor yalnızca araştırma amacıyla otomatik olarak oluşturulmuştur. Tanısal veya klinik bir belge değildir."
    T_LICENSED = "Licensed Use" if is_english else "Lisanslı Kullanım"

    # ── Jinja2 Template rendering separation ──────────────────
    css_path = BACKEND_DIR / "templates" / "report.css"
    if not css_path.exists():
        css_path = PROJECT_ROOT / "desktop_app" / "python_backend" / "templates" / "report.css"
        
    html_path_template = BACKEND_DIR / "templates" / "report.html"
    if not html_path_template.exists():
        html_path_template = PROJECT_ROOT / "desktop_app" / "python_backend" / "templates" / "report.html"

    try:
        css_content = css_path.read_text(encoding='utf-8')
    except Exception as e:
        logger.warning(f"Could not load report.css ({e}), using empty style.")
        css_content = ""

    try:
        html_template = html_path_template.read_text(encoding='utf-8')
    except Exception as e:
        exit_with_error(f"Could not load report.html template: {e}")

    pathway_avgs_formatted = {p: f"{pathway_avgs.get(p, 0.0):.4f}" for p in pathways}

    zonal_rows = "".join(
        f"<tr>"
        f"<td><strong>{escape_html(zone)}</strong></td>"
        f"<td>{zonal_contrast.get('pathways', {}).get(zone, {}).get('PI3K_AKT_mTOR', 0.0):.4f}</td>"
        f"<td>{zonal_contrast.get('pathways', {}).get(zone, {}).get('MAPK_ERK', 0.0):.4f}</td>"
        f"<td>{zonal_contrast.get('pathways', {}).get(zone, {}).get('JAK_STAT', 0.0):.4f}</td>"
        f"<td>{zonal_contrast.get('pathways', {}).get(zone, {}).get('NFkB', 0.0):.4f}</td>"
        f"</tr>"
        for zone in ZONE_NAMES if zone in zonal_contrast.get('pathways', {})
    )

    context = {
        "T_HTML_LANG": T_HTML_LANG,
        "T_TITLE": T_TITLE,
        "css_content": css_content,
        "T_TME_ATLAS": T_TME_ATLAS,
        "T_PATIENT": T_PATIENT,
        "version_stamp_safe": version_stamp_safe,
        "report_date_safe": report_date_safe,
        "T_DOWNLOAD_PDF": T_DOWNLOAD_PDF,
        "T_SUMMARY_TITLE": T_SUMMARY_TITLE,
        "T_EXEC_SUMMARY": T_EXEC_SUMMARY,
        "exec_summary": exec_summary,
        "T_GENERAL_METRICS": T_GENERAL_METRICS,
        "n_spots": f"{n_spots:,}",
        "cell_types_count": len(CT_NAMES),
        "test_mse": f"{test_mse:.5f}",
        "deconv_confidence": f"%{deconv_summary.get('avg_confidence', 0)*100:.1f}",
        "T_SPOTS_ANALYZED": T_SPOTS_ANALYZED,
        "T_CELL_TYPES": T_CELL_TYPES,
        "T_DECONV_CONFIDENCE": T_DECONV_CONFIDENCE,
        "T_GNN_TEST_MSE": T_GNN_TEST_MSE,
        "T_DATA_QUALITY_TITLE": T_DATA_QUALITY_TITLE,
        "T_DATA_QUALITY_DESC": T_DATA_QUALITY_DESC,
        "T_OVERALL_LEVEL": T_OVERALL_LEVEL,
        "dq_overall_label": data_quality["overall_label"],
        "dq_overall_color": data_quality["overall_color"],
        "dq_items": data_quality["items"],
        "T_RUO_WARNING": T_RUO_WARNING,
        "T_TUMOR_LBL": T_TUMOR_LBL,
        "tumor_fraction_pct": f"%{composition['tumor_frac']*100:.1f}",
        "T_MYELOID_LBL": T_MYELOID_LBL,
        "myeloid_fraction_pct": f"%{composition['myeloid_frac']*100:.1f}",
        "T_TCELL_LBL": T_TCELL_LBL,
        "tcell_fraction_pct": f"%{composition['tcell_frac']*100:.1f}",
        "T_SUMMARY_FINDINGS_TITLE": T_SUMMARY_FINDINGS_TITLE,
        "spatial_summary": spatial_summary,
        "T_COMPOSITION_TITLE": T_COMPOSITION_TITLE,
        "T_DOWNSTREAM_PATHWAY_TITLE": T_DOWNSTREAM_PATHWAY_TITLE,
        "T_AVG_PATHWAY_SCORES": T_AVG_PATHWAY_SCORES,
        "pathways": pathways,
        "pathway_avgs": pathway_avgs_formatted,
        "T_DOMINANT_PATHWAY": T_DOMINANT_PATHWAY,
        "top_pathway_safe": top_pathway_safe,
        "T_DOMINANT_PATHWAY_DESC": T_DOMINANT_PATHWAY_DESC,
        "T_ENRICHED_PATHWAYS_TITLE": T_ENRICHED_PATHWAYS_TITLE,
        "T_ENRICHED_PATHWAYS_DESC": T_ENRICHED_PATHWAYS_DESC,
        "T_PATHWAY_ID": T_PATHWAY_ID,
        "T_PATHWAY_NAME": T_PATHWAY_NAME,
        "T_TYPE": T_TYPE,
        "T_OVERLAP": T_OVERLAP,
        "T_PVALUE": T_PVALUE,
        "T_FDR": T_FDR,
        "enrichment_rows": enrichment_rows,
        "T_ZONAL_TITLE": T_ZONAL_TITLE,
        "T_PATH_ZONE_LBL": T_PATHOLOGICAL_ZONE,
        "zonal_rows": zonal_rows,
        "T_CELLTYPE_CORR_TITLE": T_CELLTYPE_CORR_TITLE,
        "T_CELL_TYPE": T_CELL_TYPE,
        "T_SIGNIFICANCE": T_SIGNIFICANCE,
        "corr_rows": corr_rows,
        "T_VISUALIZATIONS": T_VISUALIZATIONS,
        "fig_html": fig_html,
        "T_PIPELINE_SUMMARY": T_PIPELINE_SUMMARY,
        "T_PREPROCESSING": T_PREPROCESSING,
        "T_CELLS_LABEL": T_CELLS_LABEL,
        "prep_summary_cells": escape_html(prep_summary.get('scrna_cells', 'N/A')),
        "T_SPOTS_LABEL": T_SPOTS_LABEL,
        "prep_summary_spots": escape_html(prep_summary.get('spatial_spots', 'N/A')),
        "T_CLUSTERS_LABEL": T_CLUSTERS_LABEL,
        "prep_summary_clusters": escape_html(prep_summary.get('scrna_clusters', 'N/A')),
        "T_DECONVOLUTION": T_DECONVOLUTION,
        "T_CELL_TYPES_COUNT": T_CELL_TYPES_COUNT,
        "deconv_summary_cell_types": escape_html(deconv_summary.get('n_cell_types', 'N/A')),
        "T_METHOD_LABEL": T_METHOD_LABEL,
        "T_PUBMED_REFS": T_PUBMED_REFS,
        "T_PUBMED_DESC": T_PUBMED_DESC,
        "ref_html_left": ref_html_left,
        "ref_html_right": ref_html_right,
        "T_LICENSED": T_LICENSED,
        "T_AUTO_GENERATED": T_AUTO_GENERATED,
    }

    try:
        template = Template(html_template)
        html = template.render(**context)
    except Exception as e:
        exit_with_error(f"Jinja2 template rendering failed: {e}")

    html_path = reports_out / f"Rapor_{PATIENT_ID}.html"
    html_path.write_text(html, encoding='utf-8')
    logger.info(f"   ✅ HTML rapor: {html_path}")

    # ── PDF Report (User's v2.0 Gold Standard) ────────────────────
    logger.info("📄 Araştırma PDF raporu oluşturuluyor...")
    try:
        import subprocess
        pdf_script = Path(__file__).parent.parent / "generate_pdf_report.py"
        pdf_out_path = reports_out / f"Rapor_{PATIENT_ID}.pdf"
        
        if getattr(sys, 'frozen', False):
            cmd = [
                sys.executable, "--stage", "report_pdf",
                str(OUTPUT_DIR / "gnn" / "data.json"),
                str(pdf_out_path),
                PATIENT_ID
            ]
        else:
            if not pdf_script.exists():
                logger.error(f"PDF scripti bulunamadı: {pdf_script}")
                raise FileNotFoundError(f"PDF scripti bulunamadı: {pdf_script}")
            cmd = [
                sys.executable, str(pdf_script),
                str(OUTPUT_DIR / "gnn" / "data.json"),
                str(pdf_out_path),
                PATIENT_ID
            ]
            
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Not: sadece returncode==0'a güvenmek yeterli değil — dosyanın
        # gerçekten diskte olduğunu da doğrula (bkz. denetim bulgusu A-07).
        pdf_generated = (result.returncode == 0) and pdf_out_path.exists()
        if pdf_generated:
            logger.info(f"   ✅ PDF rapor: {pdf_out_path}")
        else:
            logger.error(f"PDF rapor üretimi başarısız oldu (returncode={result.returncode}):\n{result.stderr}")
    except Exception as e:
        pdf_generated = False
        logger.warning(f"   PDF oluşturma hatası: {e}")

    logger.info("✅ Stage 5 tamamlandı" + ("" if pdf_generated else " (PDF rapor üretilemedi — yalnızca HTML rapor mevcut)"))
    print(json.dumps({
        "stage": "report", "status": "done",
        "html_report": str(html_path),
        "pdf_report": str(pdf_out_path) if pdf_generated else None,
        "pdf_generated": pdf_generated,
    }))

if __name__ == "__main__":
    main()
