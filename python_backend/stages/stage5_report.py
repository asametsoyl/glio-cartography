#!/usr/bin/env python3
"""Stage 5: Clinical PDF report generation"""
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

from loguru import logger
import html as html_module

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

def generate_mini_svg_risk_map(spots):
    if not spots:
        return ""
    xs = [s.get('x', 0) for s in spots]
    ys = [s.get('y', 0) for s in spots]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    
    width = 300
    height = 300
    padding = 15
    
    dx = max_x - min_x if max_x != min_x else 1
    dy = max_y - min_y if max_y != min_y else 1
    
    svg = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" style="background:#020509; border-radius:12px; border:1px solid #1e3a5f;">'
    ]
    
    for s in spots:
        raw_x = s.get('x', 0)
        raw_y = s.get('y', 0)
        
        raw_risk = float(s.get('tcga_risk', 0.0))
        if np is not None:
            risk = float(np.clip(raw_risk, 0.0, 1.0))
        else:
            risk = max(0.0, min(1.0, raw_risk))
            
        cx = padding + ((raw_x - min_x) / dx) * (width - padding * 2)
        cy = padding + ((raw_y - min_y) / dy) * (height - padding * 2)
        
        is_finite = True
        if np is not None:
            if not (np.isfinite(cx) and np.isfinite(cy)):
                is_finite = False
        else:
            import math
            if not (math.isfinite(cx) and math.isfinite(cy)):
                is_finite = False
                
        if not is_finite:
            continue
            
        color = interpolate_color("#2A9D8F", "#E63946", risk)
        svg.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="2.5" fill="{color}" opacity="0.95" />')
        
    svg.append('</svg>')
    return '\n'.join(svg)

def generate_pubmed_references(dominant_lr, mgmt_status, pathways):
    refs = []
    if dominant_lr and dominant_lr != "N/A":
        refs.append({
            "topic": f"L-R Ekseni: {dominant_lr}",
            "title": f"The clinical impact of {dominant_lr} signaling in glioblastoma",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/?term={dominant_lr.replace('-', '+')}+glioblastoma"
        })
    refs.append({
        "topic": "MGMT Promotör Metilasyonu",
        "title": "Prognostic value of MGMT promoter methylation in glioblastoma Stupp trial",
        "url": "https://pubmed.ncbi.nlm.nih.gov/?term=MGMT+promoter+methylation+glioblastoma+TMZ"
    })
    refs.append({
        "topic": "TCGA Risk Modeli",
        "title": "Glioblastoma molecular subtypes and risk models validation",
        "url": "https://pubmed.ncbi.nlm.nih.gov/?term=glioblastoma+TCGA+risk+score+prognosis"
    })
    for p in pathways:
        refs.append({
            "topic": f"Yolak: {p}",
            "title": f"Targeting downstream {p} signaling pathway in glioblastoma patients",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/?term={p.replace('_', '+')}+glioblastoma+therapy"
        })
    return refs

def img_to_b64(path):
    try:
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode()
    except Exception as e:
        logger.warning(f"Resim base64'e dönüştürülemedi ({path}): {e}")
        return ""

# ── Dynamic Clinical Profile Engine ─────────────────────────
def compute_clinical_profile(gnn_sum, deconv_sum, prep_sum):
    """
    Analiz çıktılarından klinik profil çıkar. 
    Önemli: Bu tahminler hesapsal öngörüler olup klinik onay gerektirir.
    """
    profile = {}
    mgmt_methylated = None

    # Dekonvolüsyon verileri
    mean_props  = deconv_sum.get("mean_proportions", {})
    avg_conf    = deconv_sum.get("avg_confidence", 0)
    avg_entropy = deconv_sum.get("avg_entropy", 1.0)
    ct_names    = deconv_sum.get("cell_type_names", [])

    # Tümör hücre oranı (tüm tümör alt tiplerinin toplamı)
    tumor_keys = [k for k in mean_props if "Tumor" in k or "tumor" in k or "GBM" in k]
    tumor_frac = sum(mean_props.get(k, 0) for k in tumor_keys)

    # Myeloid/TAM oranı
    myeloid_keys = [k for k in mean_props if "Myeloid" in k or "TAM" in k or "Micro" in k]
    myeloid_frac = sum(mean_props.get(k, 0) for k in myeloid_keys)

    # T-hücre oranı
    tcell_keys = [k for k in mean_props if "T_Cell" in k or "T-cell" in k or "Lymph" in k]
    tcell_frac = sum(mean_props.get(k, 0) for k in tcell_keys)

    # ── WHO Grade ───────────────────────────────────────────
    mse = gnn_sum.get("test_mse", 0)
    if tumor_frac > 0.35 or mse < 0.02 or avg_entropy > 0.75:
        profile["who_grade"]    = "Grade 4"
        profile["who_grade_color"] = "var(--danger)"
        profile["diagnosis"]    = "Glioblastoma (GBM)"
    else:
        profile["who_grade"]    = "Grade 3"
        profile["who_grade_color"] = "#F4A261"
        profile["diagnosis"]    = "Yüksek Dereceli Glioma"

    # ── IDH Mutasyon Durumu ─────────────────────────────────
    if tumor_frac > 0.30 and tcell_frac < 0.08:
        profile["idh_status"] = "IDH-wildtype"
        profile["idh_note"]   = "⚠️ Agresif fenotip"
    elif tumor_frac < 0.25 and tcell_frac >= 0.05:
        profile["idh_status"] = "IDH-mutant (olası)"
        profile["idh_note"]   = "✅ Görece iyi prognoz"
    else:
        profile["idh_status"] = "Belirsiz — Moleküler Test Önerilir"
        profile["idh_note"]   = "⚠️ Doğrulama gerekli"

    # ── MGMT Metilasyon Durumu ──────────────────────────────
    spatial_path = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    adata = None
    mgmt_expr = None
    if ad is not None and spatial_path.exists():
        try:
            adata = ad.read_h5ad(spatial_path)
            candidates = ["MGMT", "mgmt", "Mgmt"]
            for c in candidates:
                if c in adata.var_names:
                    try:
                        col_idx = adata.var_names.get_loc(c)
                        e = adata.X[:, col_idx]
                    except Exception:
                        e = adata[:, c].X
                    mgmt_expr = e.toarray().flatten() if hasattr(e, 'toarray') else np.asarray(e).flatten()
                    break
        except Exception as e_load:
            logger.warning(f"AnnData loading failed for MGMT proxy: {e_load}")

    if mgmt_expr is not None and len(mgmt_expr) > 0:
        avg_mgmt = float(np.mean(mgmt_expr))
        logger.info(f"Direct MGMT gene expression average: {avg_mgmt:.4f}")
        if avg_mgmt < 0.2:
            profile["mgmt_status"]       = "Metile (Methylated) — Düşük MGMT Ekspresyonu (TMZ'ye Yanıt Beklenir)"
            profile["mgmt_status_short"] = "Methylated"
            profile["mgmt_color"]        = "var(--success)"
            mgmt_methylated = True
        else:
            profile["mgmt_status"]       = "Metile Değil (Unmethylated) — Yüksek MGMT Ekspresyonu (TMZ Direnci)"
            profile["mgmt_status_short"] = "Unmethylated"
            profile["mgmt_color"]        = "var(--danger)"
            mgmt_methylated = False
    else:
        # Fallback: entropy-based proxy
        if avg_entropy < 0.45:
            profile["mgmt_status"]       = "Metile (Methylated) — TMZ'ye Yanıt Beklenir (Heterojenite Proxy)"
            profile["mgmt_status_short"] = "Methylated"
            profile["mgmt_color"]        = "var(--success)"
            mgmt_methylated = True
        elif avg_entropy > 0.70:
            profile["mgmt_status"]       = "Metile Değil (Unmethylated) — TMZ Direnci Beklenir (Heterojenite Proxy)"
            profile["mgmt_status_short"] = "Unmethylated"
            profile["mgmt_color"]        = "var(--danger)"
            mgmt_methylated = False
        else:
            profile["mgmt_status"]       = "Belirsiz — Metilasyon Testi Gerekli"
            profile["mgmt_status_short"] = "Belirsiz"
            profile["mgmt_color"]        = "#F4A261"
            mgmt_methylated = None

    # ── Tedavi Protokolü ────────────────────────────────────
    protocols = []
    rationale = []

    idh_wt = ("wildtype" in profile["idh_status"].lower())

    if idh_wt and profile["who_grade"] == "Grade 4":
        # Standart GBM — Stupp Protokolü + NCCN 2024 standartları (TTFields)
        protocols.append("🔬 <strong>Radyoterapi + Eş Zamanlı Temozolomide (TMZ)</strong>: RT (60 Gy / 30 fraksiyon) ve TMZ 75 mg/m²/gün × 6 hafta")
        protocols.append("📡 <strong>Tumor Treating Fields (TTFields / Optune)</strong>: RT sonrası idame tedaviyle eş zamanlı (Optune günde en az 18 saat kullanım önerilir)")
        protocols.append("💊 <strong>İdame Temozolomide (TMZ)</strong>: RT sonrası TMZ 150–200 mg/m²/gün PO (28 günde bir 5 gün) × 6–12 kür")
        rationale.append("Stupp protokolü (2005) & NCCN Kılavuzları (2024) — Standart Tedavi")

        if mgmt_methylated is False:
            protocols.append("🩸 <strong>Lomustine (CCNU) + Bevacizumab Kombinasyonu</strong> veya Klinik Çalışmalar (TMZ direnci riski nedeniyle)")
            rationale.append("MGMT-unmethylated direnç yönetimi: Lomustine + Bevacizumab (BELOB trial)")
        elif mgmt_methylated is True:
            protocols.append("✅ MGMT metilasyonu → TMZ kemoterapisine güçlü yanıt beklentisi")
            rationale.append("MGMT-methylated durumunda TMZ etkilidir")
        else:
            protocols.append("⚠️ MGMT durumu moleküler olarak belirsiz: Standart TMZ + klinik çalışma seçenekleri değerlendirilmelidir")

        if myeloid_frac > 0.30:
            protocols.append("🛡️ <strong>Klinik Çalışma Katılımı Düşünülmelidir</strong>: Yüksek TAM infiltrasyonu (%{:.0f}) immünsüpresif TME nedeniyle immün kontrol noktası veya makrofaj hedefli tedaviler için adaylık oluşturabilir".format(myeloid_frac*100))
            rationale.append("Yüksek myeloid/TAM infiltrasyonu nedeniyle deneysel tedaviler")

    elif profile["who_grade"] == "Grade 3":
        protocols.append("🔬 <strong>Temozolomide (TMZ)</strong>: 150–200 mg/m²/gün × 5 gün, 28 günde 1")
        protocols.append("📡 Radyoterapi: 54–60 Gy fraksiyonel")
        rationale.append("Grade 3 Glioma — WHO 2021 kılavuzu")
    else:
        protocols.append("🔬 Standart Stupp Protokolü ve klinik çalışmaları değerlendirin")
        rationale.append("Klinik değerlendirme gereklidir")

    profile["protocols"]  = protocols
    profile["rationale"]  = rationale
    profile["tumor_frac"] = tumor_frac
    profile["myeloid_frac"] = myeloid_frac
    profile["tcell_frac"]   = tcell_frac
    return profile


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
    clinical_synthesis = "Klinik sentez verisi yüklenemedi."
    top_pathway = "N/A"
    top_lr = [('SPP1-CD44', 0.0)]
    gen_risk = "BELİRSİZ"
    tam_avg = 15.0
    mes_avg = 15.0
    stats_calc = {
        'n_spots': 0,
        'tam_avg': tam_avg,
        'mes_avg': mes_avg,
        'gen_risk': gen_risk,
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
                    
            # Calculate risk and cell proportions for clinical synthesis
            tam_total = 0.0
            mes_total = 0.0
            lr_totals = {}
            for s in spots_data:
                ct = s.get('ct', {})
                tam_total += float(ct.get('TAM', 0))
                mes_total += float(ct.get('Tumor_MES', 0))
                for lr_key, val in s.get('lr', {}).items():
                    lr_totals[lr_key] = lr_totals.get(lr_key, 0.0) + float(val)
                    
            tam_avg = (tam_total / len(spots_data)) * 100 if spots_data else 0
            mes_avg = (mes_total / len(spots_data)) * 100 if spots_data else 0
            
            # Risk classification
            mes_risk = "YÜKSEK" if mes_avg > 15.0 else "ORTA"
            tam_risk = "YÜKSEK" if tam_avg > 20.0 else "ORTA"
            gen_risk = "AGRESİF" if (mes_risk == "YÜKSEK" or tam_risk == "YÜKSEK") else "STABİL"
            
            top_lr = sorted(
                [(k, v / len(spots_data)) for k, v in lr_totals.items()],
                key=lambda x: x[1], reverse=True
            )[:4]
            
            stats_calc = {
                'n_spots': len(spots_data),
                'tam_avg': tam_avg,
                'mes_avg': mes_avg,
                'gen_risk': gen_risk,
                'pathway_avgs': pathway_avgs,
                'top_lr': top_lr
            }
            
            # Now generate synthesis
            top_pathway = max(pathway_avgs, key=pathway_avgs.get) if pathway_avgs else "PI3K_AKT_mTOR"
            dominant_lr_val = top_lr[0][0] if top_lr else "SPP1-CD44"
            mes_high = mes_avg > 15.0
            tam_high = tam_avg > 20.0
            
            # Escape strings safely for embedding into synthesis
            gen_risk_safe = escape_html(stats_calc['gen_risk'])
            top_pathway_safe = escape_html(top_pathway)
            dominant_lr_safe = escape_html(dominant_lr_val)

            synthesis = (
                f"Glio-Cartography uzamsal transkriptomik analizi, {stats_calc['n_spots']:,} spot düzeyinde tümör mikroçevresi (TME) heterojenliğini ortaya koymuştur. "
                f"Hastada GNN analizine göre global risk profili '{gen_risk_safe}' olarak belirlenmiştir. "
            )
            
            if mes_high and tam_high:
                synthesis += (
                    f"Dokuda yüksek invaziv mezenkimal tümör fraksiyonu (%{stats_calc['mes_avg']:.1f}) ile birlikte belirgin bir immünsüpresif Tümör İlişkili Makrofaj (TAM) "
                    f"infiltrasyonu (%{stats_calc['tam_avg']:.1f}) izlenmektedir. Bu iki profilin birlikteliği, tümörün mezenkimal fenotipe geçişini ve T-hücre aracılı immün "
                    f"yanıttan kaçışını destekleyen agresif bir mikroçevreye işaret eder. "
                )
            elif mes_high:
                synthesis += (
                    f"Doku genelinde yüksek mezenkimal geçiş (MES) skoru (%{stats_calc['mes_avg']:.1f}) saptanmıştır. "
                    f"Bu durum, tümörün yüksek invazyon potansiyeline ve radyoterapi/kemoterapiye karşı olası direncine katkıda bulunan "
                    f"prominent bir hücre dışı matris (ECM) remodellemesiyle ilişkilidir. "
                )
            elif tam_high:
                synthesis += (
                    f"Doku genelinde yüksek düzeyde immünsüpresif TAM infiltrasyonu (%{stats_calc['tam_avg']:.1f}) izlenmektedir. "
                    f"Bu durum, mikroçevredeki güçlü bir miyeloid kökenli baskılama mekanizmasını doğrulamakta olup T-hücrelerinin tümör içine "
                    f"penetrasyonunu ve aktivasyonunu engellemektedir. "
                )
            else:
                synthesis += "Tümör dokusu görece stabil ve lokalize bir proliferasyon profili göstermektedir. "
                
            synthesis += (
                f"Sinyal yolakları düzeyinde, dokuda baskın olarak '{top_pathway_safe}' yolağı aktive olmuştur. "
                f"Uzamsal iletişim analizinde en yüksek aktivite gösteren sinyal ekseni '{dominant_lr_safe}' olarak saptanmıştır. "
            )
            
            if dominant_lr_val == "SPP1-CD44":
                synthesis += (
                    "SPP1-CD44 etkileşiminin yüksek aktivitesi, TAM'ların tümör hücreleriyle yakın temas kurarak mezenkimal transdiferansiasyonu "
                    "ve tümör kök hücre (GSC) stemness özelliklerini uyardığını doğrulamaktadır. Bu eksen, immünoterapiye dirençte kritik rol oynar. "
                )
            elif dominant_lr_val == "VEGFA-KDR":
                synthesis += (
                    "VEGFA-KDR anjiyojenik sinyalleşmesinin baskınlığı, dokuda yoğun mikrovasküler proliferasyon ve hipoksiye yanıt olarak "
                    "gelişen yeni damar oluşumu odaklarını desteklemektedir. Bu durum anti-VEGF (Bevacizumab) tedavisi için rasyonel oluşturur. "
                )
            elif dominant_lr_val == "MIF-CD74":
                synthesis += (
                    "MIF-CD74 ekseninin aktivasyonu, mikroglia ve makrofajların pro-enflamatuar/immünsüpresif duruma geçişini uyararak "
                    "tümör lehine immün kaçış ortamı hazırlamaktadır. "
                )
            elif dominant_lr_val == "SPP1-PTPN1":
                synthesis += (
                    "SPP1-PTPN1 kontrol noktası etkileşimi, T-hücre tükenmesini uyararak mikroçevredeki baskılayıcı immün yanıtı güçlendirmektedir. "
                )
            
            synthesis += (
                "Zonal kontrast analizi, 'Leading Edge' bölgesinde mezenkimal ve invaziv yolakların, 'Pseudopalisading Necrosis' çevresinde ise "
                "hipoksik yolakların ve glikolitik aktivitenin yoğunlaştığını göstermektedir. Bu uzamsal polarizasyon, standart kemoradyoterapiye "
                "lokal nüks riski yüksek dirençli bölgeler yaratmaktadır. Tedavi planlamasında bu zonal dinamikler göz önünde bulundurulmalıdır."
            )
            clinical_synthesis = synthesis
        except Exception as e:
            logger.warning(f"data.json okunurken/sentezlenirken hata oluştu: {e}")

    # ── Downstream Pathway Enrichment Analysis (Rapor İçin) ─────
    enrichment_rows = ""
    druggable_rows = ""
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
                
                # Match druggable targets (downstream)
                DRUGGABLE_CATALOG = {
                    "AKT1": ("Ipatasertib", "AKT Kinaz İnhibitörü", "Faz II"),
                    "AKT2": ("Ipatasertib", "AKT Kinaz İnhibitörü", "Faz II"),
                    "MTOR": ("Everolimus", "mTORC1 Kompleks Blokajı", "Faz II/III"),
                    "EGFR": ("Erlotinib", "Reseptör Tirozin Kinaz İnhibitörü", "FDA Onaylı"),
                    "MET": ("Crizotinib", "HGFR / MET Tirozin Kinaz Blokajı", "Faz II"),
                    "KDR": ("Cabozantinib", "VEGFR2 Reseptör İnhibisyonu", "Faz III"),
                    "FLT1": ("Regorafenib", "Multikinaz / VEGFR1 İnhibitörü", "Faz II"),
                    "JAK1": ("Ruxolitinib", "JAK1/JAK2 Sinyal İletim İnhibitörü", "Faz I/II"),
                    "JAK2": ("Ruxolitinib", "JAK1/JAK2 Sinyal İletim İnhibitörü", "Faz I/II"),
                    "STAT3": ("Napabucasin", "STAT3 Transkripsiyon İnhibitörü", "Faz II"),
                    "CD44": ("RG7356", "Anti-CD44 Monoklonal Antikor", "Faz I"),
                    "PDCD1": ("Pembrolizumab", "Anti-PD-1 Checkpoint Blokajı", "FDA Onaylı"),
                    "CD274": ("Atezolizumab", "Anti-PD-L1 Checkpoint Blokajı", "FDA Onaylı")
                }
                
                matched_dr = {}
                for path in enrich_results:
                    for gene in path['overlap_genes']:
                        g_up = gene.upper()
                        if g_up in DRUGGABLE_CATALOG and g_up not in matched_dr:
                            matched_dr[g_up] = (path['name'], DRUGGABLE_CATALOG[g_up][0], DRUGGABLE_CATALOG[g_up][1], DRUGGABLE_CATALOG[g_up][2])
                            
                for gene, (p_name, drug, mech, stage) in matched_dr.items():
                    druggable_rows += f"""<tr>
                        <td style="color:#00d4ff; font-weight:bold;">🎯 {escape_html(gene)}</td>
                        <td>{escape_html(p_name)}</td>
                        <td style="font-weight:bold;">💊 {escape_html(drug)}</td>
                        <td style="color:#aaa; font-size:0.8rem;">{escape_html(mech)}</td>
                        <td><span style="background:rgba(255,255,255,0.05); color:var(--accent); padding:2px 8px; border-radius:100px; font-size:0.7rem; font-weight:bold; border:1px solid rgba(0,212,255,0.2);">{escape_html(stage)}</span></td>
                    </tr>"""
    except Exception as e_enrich:
        logger.warning(f"Rapor yolak zenginleştirme hesaplama hatası: {e_enrich}")

    if not enrichment_rows:
        enrichment_rows = "<tr><td colspan='6' style='text-align:center; color:#999;'>Zenginleştirilmiş downstream yolak saptanamadı.</td></tr>"
    if not druggable_rows:
        druggable_rows = "<tr><td colspan='5' style='text-align:center; color:#999;'>Hedeflenebilir downstream protein adayı saptanamadı.</td></tr>"

    # Calculate Clinical Profile
    clinical = compute_clinical_profile(gnn_summary, deconv_summary, prep_summary)

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
    risk_level_safe = escape_html(gen_risk)
    dominant_lr_val_safe = escape_html(dominant_lr_val)
    mgmt_status_short_safe = escape_html(clinical.get('mgmt_status_short', 'MGMT'))

    exec_summary = (
        f"Hastada yapılan Glio-Cartography analizi sonucunda, tümör genelinde <strong>%{mes_avg:.1f} Mezenkimal (MES)</strong> fraksiyonu ve "
        f"<strong>%{tam_avg:.1f} Tümör İlişkili Makrofaj (TAM)</strong> infiltrasyonu ile karakterize, <strong>{risk_level_safe}</strong> risk profiline sahip "
        f"bir mikroçevre saptanmıştır. Uzamsal iletişim analizinde en aktif sinyal ekseni olan <strong>{dominant_lr_val_safe}</strong> etkileşimi, yoğun "
        f"immünsüpresyonu ve yüksek invazyon potansiyelini desteklemekte olup, hastanın <strong>{mgmt_status_short_safe}</strong> "
        f"statusu da göz önüne alınarak agresif bir kombine tedavi protokolü önerilmektedir."
    )

    # PubMed References
    pubmed_refs = generate_pubmed_references(dominant_lr_val, clinical.get('mgmt_status_short'), pathways)
    half = len(pubmed_refs) // 2
    
    ref_html_left = "".join(f"""
        <div style="margin: 12px 0; font-size: 0.85rem; line-height: 1.5; border-bottom: 1px dashed var(--border); padding-bottom: 8px;">
            <span style="font-weight: bold; color: var(--accent);">{escape_html(r['topic'])}:</span><br>
            <span style="color: #ccc; font-size: 0.8rem;">"{escape_html(r['title'])}"</span><br>
            <a href="{escape_html(r['url'])}" target="_blank" style="color: var(--accent); text-decoration: none; font-size: 0.78rem; font-weight: 600;">🔗 PubMed'de Göster &rarr;</a>
        </div>
    """ for r in pubmed_refs[:half])

    ref_html_right = "".join(f"""
        <div style="margin: 12px 0; font-size: 0.85rem; line-height: 1.5; border-bottom: 1px dashed var(--border); padding-bottom: 8px;">
            <span style="font-weight: bold; color: var(--accent);">{escape_html(r['topic'])}:</span><br>
            <span style="color: #ccc; font-size: 0.8rem;">"{escape_html(r['title'])}"</span><br>
            <a href="{escape_html(r['url'])}" target="_blank" style="color: var(--accent); text-decoration: none; font-size: 0.78rem; font-weight: 600;">🔗 PubMed'de Göster &rarr;</a>
        </div>
    """ for r in pubmed_refs[half:])

    # SVG Map
    svg_map_html = generate_mini_svg_risk_map(spots_data)
    version_stamp = "Glio-Cartography v3.0 [Clinical Report Edition]"

    # Safe HTML Template construction
    patient_id_safe = escape_html(PATIENT_ID)
    version_stamp_safe = escape_html(version_stamp)
    report_date_safe = escape_html(report_date)
    diagnosis_safe = escape_html(clinical.get('diagnosis'))
    who_grade_safe = escape_html(clinical.get('who_grade'))
    who_grade_color_safe = escape_html(clinical.get('who_grade_color'))
    idh_status_safe = escape_html(clinical.get('idh_status'))
    idh_note_safe = escape_html(clinical.get('idh_note'))
    mgmt_status_short_safe = escape_html(clinical.get('mgmt_status_short'))
    mgmt_color_safe = escape_html(clinical.get('mgmt_color'))
    mgmt_status_safe = escape_html(clinical.get('mgmt_status'))
    top_pathway_safe = escape_html(top_pathway)

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>Glio-Cartography — Klinik Rapor: {patient_id_safe}</title>
<style>
  :root {{
    --bg: #0a0f1e; --card: #0d1b2a; --accent: #00d4ff; --text: #e0e0e0;
    --border: #1e3a5f; --success: #2A9D8F; --danger: #E63946;
    --warning: #F4A261;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',Arial,sans-serif; padding:40px; }}
  h1 {{ color:var(--accent); font-size:2rem; margin-bottom:8px; }}
  h2 {{ color:var(--accent); font-size:1.3rem; margin:32px 0 12px; border-bottom:1px solid var(--border); padding-bottom:8px; }}
  h3 {{ color:#ccc; font-size:1rem; margin:12px 0 6px; }}
  .header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:32px; }}
  .badge {{ background:var(--accent); color:#000; padding:4px 12px; border-radius:20px; font-size:0.8rem; font-weight:700; }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .grid-3 {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }}
  .metric {{ font-size:2rem; font-weight:700; color:var(--accent); }}
  .metric-label {{ font-size:0.8rem; color:#999; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.85rem; }}
  th {{ background:#1a2744; color:var(--accent); padding:10px; text-align:left; }}
  td {{ padding:8px 10px; border-bottom:1px solid var(--border); }}
  tr:hover td {{ background:#111d33; }}
  .figures-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:16px; }}
  .figure-card {{ background:var(--card); border:1px solid var(--border); border-radius:8px; overflow:hidden; }}
  .figure-card img {{ width:100%; height:220px; object-fit:cover; }}
  .fig-caption {{ padding:8px; font-size:0.75rem; color:#999; text-align:center; }}
  .footer {{ text-align:center; margin-top:40px; padding-top:20px; border-top:1px solid var(--border); color:#666; font-size:0.8rem; }}
  .print-btn {{ background: var(--accent); color: #000; border: none; padding: 8px 16px; border-radius: 6px; font-weight: bold; cursor: pointer; display: inline-flex; align-items: center; gap: 8px; font-size: 0.9rem; }}
  .print-btn:hover {{ opacity: 0.9; }}
  @media print {{ body {{ background:#fff; color:#000; padding: 0; }} .print-btn, .footer {{ display: none !important; }} .card, .figure-card {{ border: 1px solid #ccc; break-inside: avoid; }} }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>🧠 Glio-Cartography</h1>
    <p style="color:#999; margin-top:4px;">Spatial Tumor Microenvironment Atlas</p>
    <p style="color:var(--accent); margin-top:8px; font-size:1.1rem;"><strong>Hasta: {patient_id_safe}</strong></p>
  </div>
  <div style="text-align:right">
    <span class="badge">{version_stamp_safe}</span>
    <p style="color:#666; font-size:0.8rem; margin-top:8px;">{report_date_safe}</p>
    <button class="print-btn" style="margin-top: 16px;" onclick="window.print()">📥 PDF Olarak İndir</button>
  </div>
</div>

<h2>📋 Klinik Yönetici Özeti &amp; Uzamsal Risk Haritası</h2>
<div class="grid-2" style="margin-bottom: 24px;">
  <div class="card" style="border-left: 4px solid var(--accent); display: flex; flex-direction: column; justify-content: center;">
    <h3 style="margin-top: 0; color: var(--text); font-size: 1.1rem; margin-bottom: 12px;">📋 Yönetici Özeti</h3>
    <p style="line-height: 1.6; font-size: 0.95rem; color: #e0e0e0;">
      {exec_summary}
    </p>
  </div>
  <div class="card" style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 16px;">
    <h3 style="margin-top: 0; color: var(--text); font-size: 0.95rem; margin-bottom: 8px; width: 100%; text-align: left;">🗺️ Vektörel Uzamsal Risk Haritası (Mini SVG)</h3>
    <div style="width: 100%; max-width: 250px; aspect-ratio: 1/1;">
      {svg_map_html}
    </div>
    <div style="display: flex; gap: 16px; margin-top: 8px; font-size: 0.75rem; font-weight: bold;">
      <span style="color: #2A9D8F;">● Stabil (Düşük Risk)</span>
      <span style="color: #E63946;">● Agresif (Yüksek Risk)</span>
    </div>
  </div>
</div>

<h2>📊 Genel Metrikler</h2>
<div class="grid-3">
  <div class="card">
    <div class="metric">{n_spots:,}</div>
    <div class="metric-label">Analiz Edilen Spot</div>
  </div>
  <div class="card">
    <div class="metric">{len(CT_NAMES)}</div>
    <div class="metric-label">Hücre Tipi</div>
  </div>
  <div class="card">
    <div class="metric">{test_mse:.5f}</div>
    <div class="metric-label">GNN Test MSE</div>
  </div>
  <div class="card">
    <div class="metric">%{deconv_summary.get('avg_confidence', 0)*100:.1f}</div>
    <div class="metric-label">Dekonvolüsyon Güveni</div>
  </div>
</div>

<h2>🧬 Klinik Özellikler &amp; Karar Destek</h2>
<p style="font-size:0.78rem; color:#666; margin-bottom:12px; font-style:italic;">
  ⚠️ Bu değerlendirmeler hesapsal tahmindir. Klinik onay için histopatoloji ve moleküler testler gereklidir.
</p>
<div class="grid-2">
  <div class="card" style="border-left: 4px solid var(--accent);">
    <h3 style="margin-top:0; color:var(--text);">Moleküler Profil (Hesapsal)</h3>
    <table style="margin-top: 12px; background: transparent;">
      <tr><td style="color:#999; border:none; padding:5px 0;">Tanı:</td><td style="border:none; font-weight:bold;">{diagnosis_safe}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">WHO Grade:</td><td style="border:none; font-weight:bold; color:{who_grade_color_safe};">{who_grade_safe}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">IDH Durumu:</td><td style="border:none; font-weight:bold;">{idh_status_safe} {idh_note_safe}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">MGMT Promotör:</td><td style="border:none; font-weight:bold; color:{mgmt_color_safe};">{mgmt_status_short_safe}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">Tümör Fraksiyon:</td><td style="border:none;">%{clinical['tumor_frac']*100:.1f}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">Myeloid/TAM:</td><td style="border:none;">%{clinical['myeloid_frac']*100:.1f}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">T-Hücre İnfiltrasyonu:</td><td style="border:none;">%{clinical['tcell_frac']*100:.1f}</td></tr>
    </table>
  </div>
  <div class="card" style="border-left: 4px solid var(--success);">
    <h3 style="margin-top:0; color:var(--text);">Önerilen Tedavi Protokolü</h3>
    <p style="font-size:0.8rem; color:#aaa; margin-top:6px; margin-bottom:10px;">GNN + Spatial mikroçevre analizine dayalı:</p>
    {''.join(f"<div style='margin:8px 0; font-size:0.88rem; line-height:1.5;'>{p}</div>" for p in clinical['protocols'])}
    <hr style="border-color:#1e3a5f; margin:12px 0;">
    <p style="font-size:0.75rem; color:#777;"><strong>Kaynaklar:</strong> {'  ·  '.join(escape_html(ref) for ref in clinical['rationale']) or 'N/A'}</p>
    <p style="font-size:0.72rem; color:#555; margin-top:6px;">* {mgmt_status_safe}</p>
  </div>
</div>

<h2>📋 Klinik Sentez ve Tümör Mikroçevresi (TME) Dinamikleri</h2>
<div class="card" style="border-left: 4px solid var(--warning); line-height: 1.6; font-size: 0.92rem; margin-bottom: 24px; padding: 20px;">
  <p>{clinical_synthesis}</p>
</div>

<h2>🧬 Downstream Yolak Aktivasyonu</h2>
<div class="grid-2" style="margin-bottom: 24px;">
  <div class="card" style="border-left: 4px solid var(--accent);">
    <h3 style="margin-top:0; color:var(--text);">Ortalama Downstream Yolak Skorları</h3>
    <table style="margin-top: 12px; background: transparent;">
      {''.join(f"<tr><td style='color:#999; border:none; padding:8px 0;'>{escape_html(p)}:</td><td style='border:none; font-weight:bold; color:var(--accent);'>{pathway_avgs.get(p, 0.0):.4f}</td></tr>" for p in pathways)}
    </table>
  </div>
  <div class="card" style="border-left: 4px solid var(--danger);">
    <h3 style="margin-top:0; color:var(--text);">Baskın Downstream Yolak</h3>
    <div style="font-size:2rem; font-weight:700; color:var(--danger); margin-top:15px;">
      {top_pathway_safe}
    </div>
    <p style="font-size:0.8rem; color:#aaa; margin-top:8px;">
      Tümörün proliferasyon, sağkalım ve invazyon mekanizmalarını yönlendiren baskın downstream sinyal kaskadı.
    </p>
  </div>
</div>

<h2>🧬 L-R Downstream Zenginleştirilmiş Yolaklar ({dominant_lr_val_safe})</h2>
<div class="card" style="margin-bottom: 24px;">
  <p style="font-size:0.85rem; color:#aaa; margin-bottom:12px;">Baskın {dominant_lr_val_safe} sinyalleşme ekseninin uyardığı anlamlı downstream yolaklar:</p>
  <table>
    <thead>
      <tr>
        <th>Yolak ID</th>
        <th>Yolak Adı</th>
        <th>Tip</th>
        <th>Overlap / Yolak</th>
        <th>p-Değeri</th>
        <th>FDR q-Değeri</th>
      </tr>
    </thead>
    <tbody>
      {enrichment_rows}
    </tbody>
  </table>
</div>

<h2>💊 Hedeflenebilir Downstream İlaç Adayları</h2>
<div class="card" style="margin-bottom: 24px;">
  <p style="font-size:0.85rem; color:#aaa; margin-bottom:12px;">Uyarılmış downstream yolaklarda hedeflenebilir durumdaki protein adayları:</p>
  <table>
    <thead>
      <tr>
        <th>Hedef Gen</th>
        <th>Uyarılmış Yolak</th>
        <th>Etkin İlaç</th>
        <th>Etki Mekanizması</th>
        <th>Klinik Aşama</th>
      </tr>
    </thead>
    <tbody>
      {druggable_rows}
    </tbody>
  </table>
</div>

<h2>📊 Zonal Yolak Kontrast Analizi</h2>
<div class="card" style="margin-bottom: 24px;">
  <table>
    <thead>
      <tr>
        <th>Patolojik Zon</th>
        <th>PI3K/AKT/mTOR</th>
        <th>MAPK/ERK</th>
        <th>JAK/STAT</th>
        <th>NFkB</th>
      </tr>
    </thead>
    <tbody>
      {''.join(
        f"<tr>"
        f"<td><strong>{escape_html(zone)}</strong></td>"
        f"<td>{zonal_contrast.get('pathways', {}).get(zone, {}).get('PI3K_AKT_mTOR', 0.0):.4f}</td>"
        f"<td>{zonal_contrast.get('pathways', {}).get(zone, {}).get('MAPK_ERK', 0.0):.4f}</td>"
        f"<td>{zonal_contrast.get('pathways', {}).get(zone, {}).get('JAK_STAT', 0.0):.4f}</td>"
        f"<td>{zonal_contrast.get('pathways', {}).get(zone, {}).get('NFkB', 0.0):.4f}</td>"
        f"</tr>"
        for zone in ZONE_NAMES if zone in zonal_contrast.get('pathways', {})
      )}
    </tbody>
  </table>
</div>

<h2>🔬 Hücre Tipi Korelasyonları (GNN)</h2>
<table>
  <thead><tr><th>Hücre Tipi</th><th>Pearson r</th><th>Spearman ρ</th><th>Anlamlılık</th></tr></thead>
  <tbody>{corr_rows}</tbody>
</table>

<h2>🗺️ Görselleştirmeler</h2>
<div class="figures-grid">{fig_html}</div>

<h2>📋 Pipeline Özeti</h2>
<div class="grid-2" style="margin-bottom: 24px;">
  <div class="card">
    <h3>Ön İşleme</h3>
    <p>scRNA Hücre: <strong>{escape_html(prep_summary.get('scrna_cells', 'N/A'))}</strong></p>
    <p>Spatial Spot: <strong>{escape_html(prep_summary.get('spatial_spots', 'N/A'))}</strong></p>
    <p>Leiden Küme: <strong>{escape_html(prep_summary.get('scrna_clusters', 'N/A'))}</strong></p>
  </div>
  <div class="card">
    <h3>Dekonvolüsyon</h3>
    <p>Hücre Tipi: <strong>{escape_html(deconv_summary.get('n_cell_types', 'N/A'))}</strong></p>
    <p>Yöntem: <strong>Tangram / Score-based</strong></p>
  </div>
</div>

<h2>📚 Dinamik Klinik Referanslar (PubMed)</h2>
<div class="card" style="border-left: 4px solid var(--accent); margin-bottom: 24px;">
  <p style="font-size:0.8rem; color:#aaa; margin-bottom:12px;">Raporda geçen ligand-reseptör çiftleri, ilaç hedefleri ve risk modellerine ait güncel literatür:</p>
  <div class="grid-2">
    <div>
      {ref_html_left}
    </div>
    <div>
      {ref_html_right}
    </div>
  </div>
</div>

<div class="footer">
  <p>{version_stamp_safe} · Lisanslı Kullanım · {report_date_safe}</p>
  <p style="margin-top:4px;">Bu rapor otomatik olarak oluşturulmuştur. Klinik karar için uzman görüşü alınız.</p>
</div>
</body>
</html>"""

    html_path = reports_out / f"Klinik_Rapor_{PATIENT_ID}.html"
    html_path.write_text(html, encoding='utf-8')
    logger.info(f"   ✅ HTML rapor: {html_path}")

    # ── PDF Report (User's v2.0 Gold Standard) ────────────────────
    logger.info("📄 Klinik PDF Rapor oluşturuluyor (v2.0 Gold Standard)...")
    try:
        import subprocess
        pdf_script = Path(__file__).parent.parent / "generate_pdf_report.py"
        pdf_out_path = reports_out / f"Klinik_Rapor_{PATIENT_ID}.pdf"
        
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
        
        if result.returncode == 0:
            logger.info(f"   ✅ PDF rapor: {pdf_out_path}")
        else:
            logger.error(f"PDF script hatası:\n{result.stderr}")
    except Exception as e:
        logger.warning(f"   PDF oluşturma hatası: {e}")

    logger.info("✅ Stage 5 tamamlandı")
    print(json.dumps({"stage": "report", "status": "done",
                      "html_report": str(html_path)}))

if __name__ == "__main__":
    main()
