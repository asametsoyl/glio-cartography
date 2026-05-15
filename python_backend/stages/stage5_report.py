#!/usr/bin/env python3
"""Stage 5: Clinical PDF report generation"""
import os, sys, json, base64
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = Path(os.environ["GLIO_OUTPUT_DIR"])
PATIENT_ID = os.environ.get("GLIO_PATIENT_ID", "Patient_A")

from loguru import logger

reports_out = OUTPUT_DIR / "reports"
reports_out.mkdir(parents=True, exist_ok=True)

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False
    logger.warning("fpdf2 yüklü değil, HTML rapor oluşturuluyor")

# ── Load summaries ───────────────────────────────────────────
def load_json(path):
    try:
        with open(path) as f: return json.load(f)
    except: return {}

gnn_summary   = load_json(OUTPUT_DIR / "gnn" / "gnn_summary.json")
deconv_summary= load_json(OUTPUT_DIR / "deconvolution" / "deconvolution_summary.json")
prep_summary  = load_json(OUTPUT_DIR / "preprocessing" / "preprocessing_summary.json")

ZONE_NAMES = gnn_summary.get("zones", [])
CT_NAMES   = gnn_summary.get("ct_names", [])
test_mse   = gnn_summary.get("test_mse", 0)
n_spots    = gnn_summary.get("n_spots", 0)

# ── Dynamic Clinical Profile Engine ─────────────────────────
def compute_clinical_profile(gnn_sum, deconv_sum, prep_sum):
    """
    Analiz çıktılarından klinik profil çıkar. 
    Önemli: Bu tahminler hesapsal öngörüler olup klinik onay gerektirir.
    """
    profile = {}

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
    # GBM (Grade 4) kriterleri: yüksek tümör fraksiyon + düşük dekonv güveni
    # veya GNN MSE < 0.02 (iyi ayrışım = agresif fenotip)
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
    # IDH-wildtype göstergesi: yüksek tümör fraksiyon + düşük T-cell infiltrasyon
    # IDH-mutant: daha iyi immün infiltrasyon, daha düşük tümör fraksiyon
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
    # Proxy: Yüksek tümör heterojenliği (entropy) unmethylated fenotip göstergesi
    # Düşük entropy = daha homojen tümör = metile olmuş olasılığı artıyor
    if avg_entropy < 0.45:
        profile["mgmt_status"]       = "Metile (Methylated) — TMZ'ye Yanıt Beklenir"
        profile["mgmt_status_short"] = "Methylated"
        profile["mgmt_color"]        = "var(--success)"
        mgmt_methylated = True
    elif avg_entropy > 0.70:
        profile["mgmt_status"]       = "Metile Değil (Unmethylated) — TMZ Direnci Beklenir"
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
        # Standart GBM — Stupp Protokolü
        protocols.append("🔬 <strong>Temozolomide (TMZ)</strong>: Radyoterapi ile eş zamanlı 75 mg/m²/gün × 6 hafta")
        protocols.append("💊 İdame: TMZ 150–200 mg/m²/gün × 5 gün, 28 günde 1 (6 kür)")
        rationale.append("Stupp protokolü (2005) — GBM için standart bakım")

        if mgmt_methylated is False:
            # MGMT unmethylated → TMZ direnci → Bevacizumab / CCNU ekle
            protocols.append("🩸 <strong>Bevacizumab (Anti-VEGF)</strong>: 10 mg/kg IV, 14 günde 1")
            protocols.append("⚕️ <strong>CCNU (Lomustine)</strong>: 90 mg/m² (MGMT unmethylated protokolü)")
            rationale.append("MGMT-unmethylated: Bevacizumab + CCNU (BELOB trial)")
        elif mgmt_methylated is True:
            protocols.append("✅ MGMT metilasyonu → TMZ'ye yanıt bekleniyor")
            rationale.append("MGMT-methylated: TMZ mono tercih edilir")
        else:
            protocols.append("⚠️ MGMT durumu belirsiz: Geniş spektrum tedavi önerilir")

        if myeloid_frac > 0.30:
            protocols.append("🛡️ <strong>Anti-PD-1 Düşünülebilir</strong>: Yüksek TAM infiltrasyonu (%{:.0f})  immün kontrol noktası komb. için uygun olabilir".format(myeloid_frac*100))
            rationale.append("Yüksek myeloid/TAM → immün terapi araştırması")

    elif profile["who_grade"] == "Grade 3":
        protocols.append("🔬 <strong>Temozolomide (TMZ)</strong>: 150–200 mg/m²/gün × 5 gün, 28 günde 1")
        protocols.append("📡 Radyoterapi: 54–60 Gy fraksiyonel")
        rationale.append("Grade 3 Glioma — WHO 2021 kılavuzu")
    else:
        protocols.append("🔬 Standart Stupp Protokolü değerlendirin")
        rationale.append("Profil tamamlanmadı — klinik değerlendirme gerekli")

    profile["protocols"]  = protocols
    profile["rationale"]  = rationale
    profile["tumor_frac"] = tumor_frac
    profile["myeloid_frac"] = myeloid_frac
    profile["tcell_frac"]   = tcell_frac
    return profile

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

# ─────────────────────────────────────────────────────────────
# HTML Report (always generated)
# ─────────────────────────────────────────────────────────────
logger.info("📄 HTML rapor oluşturuluyor...")

def img_to_b64(path):
    try:
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode()
    except: return ""

fig_html = ""
for fig_path in figures[:12]:  # max 12 figures
    b64 = img_to_b64(fig_path)
    if b64:
        fig_html += f"""
        <div class="figure-card">
            <img src="data:image/png;base64,{b64}" alt="{fig_path.stem}">
            <p class="fig-caption">{fig_path.stem.replace('_', ' ').title()}</p>
        </div>"""

corr_rows = ""
for ct, vals in gnn_summary.get("correlations", {}).items():
    pr = vals.get("pearson_r", 0)
    sr = vals.get("spearman_r", 0)
    sig = "✅" if abs(pr) > 0.5 else "⚠️"
    corr_rows += f"<tr><td>{ct}</td><td>{pr:.4f}</td><td>{sr:.4f}</td><td>{sig}</td></tr>"

report_date = datetime.now().strftime("%Y-%m-%d %H:%M")

html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>Glio-Cartography — Klinik Rapor: {PATIENT_ID}</title>
<style>
  :root {{
    --bg: #0a0f1e; --card: #0d1b2a; --accent: #00d4ff; --text: #e0e0e0;
    --border: #1e3a5f; --success: #2A9D8F; --danger: #E63946;
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
    <p style="color:var(--accent); margin-top:8px; font-size:1.1rem;"><strong>Hasta: {PATIENT_ID}</strong></p>
  </div>
  <div style="text-align:right">
    <span class="badge">v1.0 · Klinik Rapor</span>
    <p style="color:#666; font-size:0.8rem; margin-top:8px;">{report_date}</p>
    <button class="print-btn" style="margin-top: 16px;" onclick="window.print()">📥 PDF Olarak İndir</button>
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
      <tr><td style="color:#999; border:none; padding:5px 0;">Tanı:</td><td style="border:none; font-weight:bold;">{clinical['diagnosis']}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">WHO Grade:</td><td style="border:none; font-weight:bold; color:{clinical['who_grade_color']};">{clinical['who_grade']}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">IDH Durumu:</td><td style="border:none; font-weight:bold;">{clinical['idh_status']} {clinical['idh_note']}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">MGMT Promotör:</td><td style="border:none; font-weight:bold; color:{clinical['mgmt_color']};">{clinical['mgmt_status_short']}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">Tümör Fraksiyon:</td><td style="border:none;">%{clinical['tumor_frac']*100:.1f}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">Myeloid/TAM:</td><td style="border:none;">%{clinical['myeloid_frac']*100:.1f}</td></tr>
      <tr><td style="color:#999; border:none; padding:5px 0;">T-Hücre İnfiltrasyonu:</td><td style="border:none;">%{clinical['tcell_frac']*100:.1f}</td></tr>
    </table>
  </div>
  <div class="card" style="border-left: 4px solid var(--success);">
    <h3 style="margin-top:0; color:var(--text);">Önerilen Tedavi Protokolü</h3>
    <p style="font-size:0.8rem; color:#aaa; margin-top:6px; margin-bottom:10px;">GNN + Spatial mikroçevre analizine dayal\u0131:</p>
    {''.join(f"<div style='margin:8px 0; font-size:0.88rem; line-height:1.5;'>{p}</div>" for p in clinical['protocols'])}
    <hr style="border-color:#1e3a5f; margin:12px 0;">
    <p style="font-size:0.75rem; color:#777;"><strong>Kaynaklar:</strong> {'  ·  '.join(clinical['rationale']) or 'N/A'}</p>
    <p style="font-size:0.72rem; color:#555; margin-top:6px;">* {clinical['mgmt_status']}</p>
  </div>
</div>

<h2>🔬 Hücre Tipi Korelasyonları (GNN)</h2>
<table>
  <thead><tr><th>Hücre Tipi</th><th>Pearson r</th><th>Spearman ρ</th><th>Anlamlılık</th></tr></thead>
  <tbody>{corr_rows}</tbody>
</table>

<h2>🗺️ Görselleştirmeler</h2>
<div class="figures-grid">{fig_html}</div>

<h2>📋 Pipeline Özeti</h2>
<div class="grid-2">
  <div class="card">
    <h3>Ön İşleme</h3>
    <p>scRNA Hücre: <strong>{prep_summary.get('scrna_cells', 'N/A')}</strong></p>
    <p>Spatial Spot: <strong>{prep_summary.get('spatial_spots', 'N/A')}</strong></p>
    <p>Leiden Küme: <strong>{prep_summary.get('scrna_clusters', 'N/A')}</strong></p>
  </div>
  <div class="card">
    <h3>Dekonvolüsyon</h3>
    <p>Hücre Tipi: <strong>{deconv_summary.get('n_cell_types', 'N/A')}</strong></p>
    <p>Yöntem: <strong>Tangram / Score-based</strong></p>
  </div>
</div>

<div class="footer">
  <p>Glio-Cartography v1.0 · Lisanslı Kullanım · {report_date}</p>
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
    pdf_script = PROJECT_ROOT / "data" / "generate_pdf_report.py"
    pdf_out_path = reports_out / f"Klinik_Rapor_{PATIENT_ID}.pdf"
    
    # generate_pdf_report.py takes: [1] json_path, [2] pdf_path, [3] patient_label
    result = subprocess.run([
        sys.executable, str(pdf_script),
        str(OUTPUT_DIR / "gnn" / "data.json"),
        str(pdf_out_path),
        PATIENT_ID
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        logger.info(f"   ✅ PDF rapor: {pdf_out_path}")
    else:
        logger.error(f"PDF script hatası:\n{result.stderr}")
except Exception as e:
    logger.warning(f"   PDF oluşturma hatası: {e}")

logger.info("✅ Stage 5 tamamlandı")
print(json.dumps({"stage": "report", "status": "done",
                  "html_report": str(html_path)}))
