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
GLIO_LANG = os.environ.get("GLIO_LANG", "tr")
is_english = (GLIO_LANG == "en")

T_HIGH = "HIGH" if is_english else "YÜKSEK"
T_MEDIUM = "MEDIUM" if is_english else "ORTA"
T_AGGRESSIVE = "AGGRESSIVE" if is_english else "AGRESİF"
T_STABLE = "STABLE" if is_english else "STABİL"
T_INDETERMINATE = "INDETERMINATE" if is_english else "BELİRSİZ"

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
    refs.append({
        "topic": "MGMT Promoter Methylation" if is_english else "MGMT Promotör Metilasyonu",
        "search_query": "MGMT promoter methylation glioblastoma TMZ",
        "url": "https://pubmed.ncbi.nlm.nih.gov/?term=MGMT+promoter+methylation+glioblastoma+TMZ"
    })
    refs.append({
        "topic": "TCGA Risk Model" if is_english else "TCGA Risk Modeli",
        "search_query": "glioblastoma TCGA risk score prognosis",
        "url": "https://pubmed.ncbi.nlm.nih.gov/?term=glioblastoma+TCGA+risk+score+prognosis"
    })
    for p in pathways:
        refs.append({
            "topic": f"Pathway: {p}" if is_english else f"Yolak: {p}",
            "search_query": f"{p} signaling pathway glioblastoma therapy",
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

# ── Analiz Güvenilirlik / Veri Kalitesi Özeti [GELİŞTİRME] ──
# Bu oturumda eklenen birçok dürüstlük sinyali (fallback_used,
# cross_method_agreement, cell_marker_source, mgmt_confidence,
# ivy_gap_validation.is_independent_validation vb.) önceden yalnızca
# JSON dosyalarında/loglarda dağınık duruyordu. Bu fonksiyon bunları TEK
# bir görünür panelde toplar, böylece rapor okuyan kişi hangi
# bulguların ne kadar güvenilir olduğunu ayrı ayrı JSON dosyalarını
# kazmadan görebilir.
def compute_data_quality_summary(gnn_sum, deconv_sum, clinical_profile):
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

    # 6) MGMT tahmin güveni (compute_clinical_profile'dan)
    mgmt_conf = clinical_profile.get("mgmt_confidence")
    if mgmt_conf:
        mc_level = {"low": "medium", "very_low": "low"}.get(mgmt_conf, "medium")
        downgrade(mc_level)
        items.append({
            "label": "MGMT Tahmini Güveni" if not is_english else "MGMT Prediction Confidence",
            "value": ("Düşük" if mgmt_conf == "low" else "Çok Düşük") if not is_english else ("Low" if mgmt_conf == "low" else "Very Low"),
            "note": (
                "MGMT durumu gerçek metilasyon testi (pirosekanslama) DEĞİL, hesaplamalı bir vekildir."
                if not is_english else
                "MGMT status is a computational proxy, NOT a real methylation assay (pyrosequencing)."
            ),
            "level": mc_level,
        })

    overall_label, _ = level_label[overall]
    return {
        "overall_level": overall,
        "overall_label": overall_label,
        "overall_color": level_color[overall],
        "items": items,
    }


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

    # DÜZELTME (2026-08-20, ikinci sentetik hasta profiliyle canlı test sırasında
    # bulundu): Aşağıdaki anahtar-kelime eşleşmeleri eskiden büyük/küçük harfe
    # duyarlıydı ve configs/config.yaml::cell_markers'daki GERÇEK (küçük harfli,
    # alt-çizgili: "t_cell", "microglia", "gbm_stem_cell" vb.) hücre-tipi
    # isimleriyle eşleşmiyordu — yalnızca sabit kodlanmış 8-tipli acil-durum
    # fallback panelindeki ("T_Cell" gibi) isimlerle eşleşiyordu. Sonuç: gerçek
    # config.yaml paneli kullanıldığında (yani her zaman, config dosyası mevcut
    # olduğu sürece) tcell_frac HER ZAMAN 0 çıkıyordu — bu da IDH-mutant (olası)
    # dalını asla ulaşılamaz kılıyor ve rapordaki "T-hücre oranı" değerini
    # her hastada yanlışlıkla %0 gösteriyordu. Ayrıca "tumor_associated_macrophage"
    # (miyeloid bir popülasyon, malign değil) "tumor" alt-dizesini içerdiği için
    # yanlışlıkla tumor_frac'e dahil ediliyordu ve "gbm_stem_cell" (gerçek bir
    # tümör alt-popülasyonu) büyük/küçük harf uyuşmazlığı nedeniyle HİÇ
    # sayılmıyordu. Aşağıdaki eşleştirme artık büyük/küçük harfe duyarsız ve
    # miyeloid/tümör ayrımını doğru yapıyor.
    def _frac_keys(keys_available, include, exclude=()):
        out = []
        for k in keys_available:
            kl = k.lower()
            if any(x in kl for x in exclude):
                continue
            if any(inc in kl for inc in include):
                out.append(k)
        return out

    # Tümör hücre oranı (malign/neoplastik alt tiplerin toplamı — TAM/mikroglia
    # gibi tümör-ilişkili ama malign OLMAYAN miyeloid popülasyonlar hariç)
    tumor_keys = _frac_keys(mean_props, include=("tumor", "malignant", "gbm"),
                             exclude=("associated_macrophage", "tam"))
    tumor_frac = sum(mean_props.get(k, 0) for k in tumor_keys)

    # Miyeloid/TAM oranı (mikroglia, makrofaj alt tipleri, TAM)
    myeloid_keys = _frac_keys(mean_props, include=("myeloid", "microglia", "macrophage", "monocyte"))
    myeloid_frac = sum(mean_props.get(k, 0) for k in myeloid_keys)

    # T-hücre oranı (t_cell, exhausted_t_cell, cd8_t_cell, treg vb. — hepsi
    # "t_cell" alt-dizesiyle biter; treg ve lenfosit ayrıca kapsanır)
    tcell_keys = _frac_keys(mean_props, include=("t_cell", "t-cell", "treg", "lymph"))
    tcell_frac = sum(mean_props.get(k, 0) for k in tcell_keys)

    # ── WHO Grade ───────────────────────────────────────────
    # NOT: `test_mse` (GNN'in kendi hücre-oranı regresyon testindeki hatası)
    # KASITLI OLARAK bu koşuldan çıkarıldı — bu bir MODEL PERFORMANS metriği,
    # hastanın biyolojisiyle hiçbir ilgisi yok. İyi eğitilmiş (düşük MSE'li)
    # bir model, bu terim varken her hastayı yanlışlıkla Grade 4'e itiyordu
    # (bkz. denetim raporu bulgusu B-01).
    if tumor_frac > 0.35 or avg_entropy > 0.75:
        profile["who_grade"]    = "Grade 4"
        profile["who_grade_color"] = "var(--danger)"
        profile["diagnosis"]    = "Glioblastoma (GBM)"
    else:
        profile["who_grade"]    = "Grade 3"
        profile["who_grade_color"] = "#F4A261"
        profile["diagnosis"]    = "High-Grade Glioma" if is_english else "Yüksek Dereceli Glioma"

    # ── IDH Mutasyon Durumu ─────────────────────────────────
    # ÖNEMLİ (bilimsel dürüstlük notu): IDH1/2 mutasyon durumu yalnızca
    # dizileme veya IHC (R132H antikoru) ile güvenilir şekilde saptanabilir.
    # Buradaki tahmin, dekonvolüsyondan gelen tümör/T-hücre oranlarına
    # dayanan HESAPLAMALI BİR VEKİLDİR — gerçek bir moleküler ölçüm değildir.
    # Önceki sürümde "IDH-wildtype" hedge'siz/kesin dille yazılıyordu, oysa
    # karşı dal "olası" diye yumuşatılıyordu — bu asimetri wildtype
    # çağrısına sahte bir otorite kazandırıyordu (bkz. denetim raporu B-02).
    # Her iki dal da artık aynı şekilde "olası/muhtemel" ile hedge'lenir.
    if tumor_frac > 0.30 and tcell_frac < 0.08:
        profile["idh_status"] = "IDH-wildtype (likely)" if is_english else "IDH-wildtype (olası)"
        profile["idh_note"]   = "⚠️ Aggressive phenotype — molecular confirmation required" if is_english else "⚠️ Agresif fenotip — moleküler doğrulama gerekli"
    elif tumor_frac < 0.25 and tcell_frac >= 0.05:
        profile["idh_status"] = "IDH-mutant (likely)" if is_english else "IDH-mutant (olası)"
        profile["idh_note"]   = "✅ Relatively favorable prognosis — molecular confirmation required" if is_english else "✅ Görece iyi prognoz — moleküler doğrulama gerekli"
    else:
        profile["idh_status"] = "Indeterminate — Molecular Test Recommended" if is_english else "Belirsiz — Moleküler Test Önerilir"
        profile["idh_note"]   = "⚠️ Verification required" if is_english else "⚠️ Doğrulama gerekli"

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

    # ÖNEMLİ (bilimsel dürüstlük notu): MGMT promotör METİLASYONU pirosekanslama
    # veya metilasyona-özgü PCR ile ölçülür — burada kullanılan mRNA
    # ekspresyon seviyesi (ya da onun da yoksa dekonvolüsyon belirsizliği)
    # metilasyonun DOLAYLI ve kalibre edilmemiş bir vekilidir, gerçek bir
    # metilasyon ölçümü değildir (bkz. denetim raporu bulgusu B-03/B-04).
    # Fallback (entropy-tabanlı) yol özellikle düşük güvenilirliklidir —
    # dekonvolüsyon belirsizliğinin metilasyonla doğrudan bir biyolojik
    # ilişkisi yoktur, yalnızca kaba bir ikincil sezgiseldir.
    if mgmt_expr is not None and len(mgmt_expr) > 0:
        avg_mgmt = float(np.mean(mgmt_expr))
        logger.info(f"Direct MGMT gene expression average: {avg_mgmt:.4f}")
        if avg_mgmt < 0.2:
            profile["mgmt_status"]       = "Methylated (proxy, low confidence) — Low MGMT mRNA Expression" if is_english else "Metile (Methylated) (vekil, düşük güven) — Düşük MGMT mRNA Ekspresyonu"
            profile["mgmt_status_short"] = "Methylated"
            profile["mgmt_color"]        = "var(--success)"
            mgmt_methylated = True
        else:
            profile["mgmt_status"]       = "Unmethylated (proxy, low confidence) — High MGMT mRNA Expression" if is_english else "Metile Değil (Unmethylated) (vekil, düşük güven) — Yüksek MGMT mRNA Ekspresyonu"
            profile["mgmt_status_short"] = "Unmethylated"
            profile["mgmt_color"]        = "var(--danger)"
            mgmt_methylated = False
        profile["mgmt_confidence"] = "low"
    else:
        # Fallback: entropy-based proxy — mRNA ölçümü de mevcut değilse
        # kullanılan İKİNCİL, çok daha zayıf bir sezgisel. Metilasyonla
        # dolaylı bile olsa doğrudan bir ilişkisi yoktur.
        if avg_entropy < 0.45:
            profile["mgmt_status"]       = "Methylated (very low confidence heuristic — heterogeneity proxy, no direct biological link)" if is_english else "Metile (Methylated) (çok düşük güven, sezgisel — heterojenite vekili, doğrudan biyolojik ilişki yok)"
            profile["mgmt_status_short"] = "Methylated"
            profile["mgmt_color"]        = "var(--success)"
            mgmt_methylated = True
        elif avg_entropy > 0.70:
            profile["mgmt_status"]       = "Unmethylated (very low confidence heuristic — heterogeneity proxy, no direct biological link)" if is_english else "Metile Değil (Unmethylated) (çok düşük güven, sezgisel — heterojenite vekili, doğrudan biyolojik ilişki yok)"
            profile["mgmt_status_short"] = "Unmethylated"
            profile["mgmt_color"]        = "var(--danger)"
            mgmt_methylated = False
        else:
            profile["mgmt_status"]       = "Indeterminate — Methylation Test Required" if is_english else "Belirsiz — Metilasyon Testi Gerekli"
            profile["mgmt_status_short"] = "Indeterminate" if is_english else "Belirsiz"
            profile["mgmt_color"]        = "#F4A261"
            mgmt_methylated = None
        profile["mgmt_confidence"] = "very_low"

    # ── Tedavi Protokolü ────────────────────────────────────
    protocols = []
    rationale = []

    idh_wt = ("wildtype" in profile["idh_status"].lower())

    if idh_wt and profile["who_grade"] == "Grade 4":
        # Standart GBM — Stupp Protokolü + NCCN 2024 standartları (TTFields)
        if is_english:
            protocols.append("🔬 <strong>Radiotherapy + Concomitant Temozolomide (TMZ)</strong>: RT (60 Gy / 30 fractions) and TMZ 75 mg/m²/day × 6 weeks")
            protocols.append("📡 <strong>Tumor Treating Fields (TTFields / Optune)</strong>: Concomitant with maintenance therapy post-RT (Optune usage of at least 18 hours/day recommended)")
            protocols.append("💊 <strong>Maintenance Temozolomide (TMZ)</strong>: Post-RT TMZ 150–200 mg/m²/day PO (5 days every 28 days) × 6–12 cycles")
            rationale.append("Stupp protocol (2005) & NCCN Guidelines (2024) — Standard of Care")
        else:
            protocols.append("🔬 <strong>Radyoterapi + Eş Zamanlı Temozolomide (TMZ)</strong>: RT (60 Gy / 30 fraksiyon) ve TMZ 75 mg/m²/gün × 6 hafta")
            protocols.append("📡 <strong>Tumor Treating Fields (TTFields / Optune)</strong>: RT sonrası idame tedaviyle eş zamanlı (Optune günde en az 18 saat kullanım önerilir)")
            protocols.append("💊 <strong>İdame Temozolomide (TMZ)</strong>: RT sonrası TMZ 150–200 mg/m²/gün PO (28 günde bir 5 gün) × 6–12 kür")
            rationale.append("Stupp protokolü (2005) & NCCN Kılavuzları (2024) — Standart Tedavi")

        if mgmt_methylated is False:
            # ÖNEMLİ (klinik doğruluk notu): BELOB çalışması NÜKS glioblastom
            # popülasyonunda yapılmıştır — yeni tanı, MGMT-unmethylated
            # hastalar için birinci basamak KILAVUZ ÖNERİSİ Lomustine+
            # Bevacizumab DEĞİL, hâlâ standart RT+eşzamanlı/idame TMZ'dir
            # (NCCN/EORTC). MGMT durumu TMZ'nin beklenen fayda büyüklüğünü
            # etkiler, birinci basamak rejimi nüks-hastalık rejimiyle
            # değiştirmez (bkz. denetim raporu bulgusu B-05).
            if is_english:
                protocols.append("⚠️ MGMT-unmethylated: standard RT + TMZ (Stupp) still recommended as first-line per NCCN/EORTC — lower expected TMZ benefit, so clinical trial enrollment should be prioritized at diagnosis")
                protocols.append("🩸 <strong>Lomustine (CCNU) + Bevacizumab</strong> is evidence-based for RECURRENT disease (BELOB trial) — not a newly-diagnosed first-line substitute")
                rationale.append("MGMT-unmethylated: first-line remains Stupp protocol (NCCN/EORTC); Lomustine+Bevacizumab (BELOB) applies at recurrence, not at diagnosis")
            else:
                protocols.append("⚠️ MGMT-unmethylated: NCCN/EORTC kılavuzlarına göre birinci basamakta hâlâ standart RT + TMZ (Stupp) önerilir — beklenen TMZ faydası daha düşük olduğundan tanı anında klinik çalışmaya yönlendirme önceliklendirilmelidir")
                protocols.append("🩸 <strong>Lomustine (CCNU) + Bevacizumab</strong> kanıtı NÜKS hastalık içindir (BELOB trial) — yeni tanıda birinci basamak rejim yerine geçmez")
                rationale.append("MGMT-unmethylated: birinci basamak hâlâ Stupp protokolü (NCCN/EORTC); Lomustine+Bevacizumab (BELOB) nükste geçerlidir, tanı anında değil")
        elif mgmt_methylated is True:
            if is_english:
                protocols.append("✅ MGMT methylation → strong response expectation to TMZ chemotherapy")
                rationale.append("TMZ is effective in MGMT-methylated status")
            else:
                protocols.append("✅ MGMT metilasyonu → TMZ kemoterapisine güçlü yanıt beklentisi")
                rationale.append("MGMT-methylated durumunda TMZ etkilidir")
        else:
            if is_english:
                protocols.append("⚠️ MGMT status molecularly indeterminate: Standard TMZ + clinical trial options should be considered")
                rationale.append("Clinical evaluation required")
            else:
                protocols.append("⚠️ MGMT durumu moleküler olarak belirsiz: Standart TMZ + klinik çalışma seçenekleri değerlendirilmelidir")
                rationale.append("Klinik değerlendirme gereklidir")

        if myeloid_frac > 0.30:
            if is_english:
                protocols.append("🛡️ <strong>Clinical Trial Enrollment Recommended</strong>: High TAM infiltration ({:.0f}%) may warrant eligibility for immune checkpoint or macrophage-targeted therapies due to immunosuppressive TME".format(myeloid_frac*100))
                rationale.append("Experimental therapies due to high myeloid/TAM infiltration")
            else:
                protocols.append("🛡️ <strong>Klinik Çalışma Katılımı Düşünülmelidir</strong>: Yüksek TAM infiltrasyonu (%{:.0f}) immünsüpresif TME nedeniyle immün kontrol noktası veya makrofaj hedefli tedaviler için adaylık oluşturabilir".format(myeloid_frac*100))
                rationale.append("Yüksek myeloid/TAM infiltrasyonu nedeniyle deneysel tedaviler")

    elif profile["who_grade"] == "Grade 3":
        if is_english:
            protocols.append("🔬 <strong>Temozolomide (TMZ)</strong>: 150–200 mg/m²/day × 5 days, 1 in 28 days")
            protocols.append("📡 Radiotherapy: 54–60 Gy fractional")
            rationale.append("Grade 3 Glioma — WHO 2021 guidelines")
        else:
            protocols.append("🔬 <strong>Temozolomide (TMZ)</strong>: 150–200 mg/m²/gün × 5 gün, 28 günde 1")
            protocols.append("📡 Radyoterapi: 54–60 Gy fraksiyonel")
            rationale.append("Grade 3 Glioma — WHO 2021 kılavuzu")
    else:
        if is_english:
            protocols.append("🔬 Evaluate Standard Stupp Protocol and clinical trials")
            rationale.append("Clinical evaluation required")
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
                    
            # DÜZELTME (2026-08-20, ikinci sentetik hasta profiliyle canlı test
            # sırasında bulundu): `ct.get('TAM', 0)` ve `ct.get('Tumor_MES', 0)`
            # yalnızca kaldırılmış, sabit-kodlanmış 8-tipli eski fallback panelin
            # ("TAM_Macrophage"/"TAM_Microglia" birleşimi 'TAM', "Tumor_MES" gibi)
            # anahtar isimleriyle eşleşiyordu. Gerçek üretimde kullanılan
            # configs/config.yaml tabanlı 12-tipli panel bu anahtarları hiç
            # üretmiyor (tumor_associated_macrophage/microglia/m1_macrophage/
            # m2_macrophage gibi ayrık isimler kullanıyor) — bu yüzden tam_total
            # SESSİZCE her zaman 0 çıkıyor ve "Klinik Sentez"/"Özet" bölümleri
            # her hastada yanlışlıkla "%0.0 TAM, STABİL risk" diye yazıyordu.
            # Mezenkimal (MES) alt-tip fraksiyonu ise pipeline'ın HİÇBİR yerinde
            # (config.yaml'daki 'gbm_states' gen seti dahi kullanılmıyor) gerçekten
            # hesaplanmıyor — bu yüzden mes_total'ı "düzeltmek" yerine, veri
            # gerçekten mevcut değilse bunu dürüstçe "ölçülmedi" olarak işaretliyoruz
            # (aşağıda mes_data_available), sahte bir %0.0 değeri sunmak yerine.
            tam_total = 0.0
            mes_total = 0.0
            mes_data_available = False
            lr_totals = {}
            _MYELOID_KEYWORDS = ("microglia", "macrophage", "myeloid", "monocyte")
            for s in spots_data:
                ct = s.get('ct', {})
                if 'TAM' in ct:
                    tam_total += float(ct.get('TAM', 0))
                else:
                    tam_total += sum(
                        float(v) for k, v in ct.items()
                        if any(kw in k.lower() for kw in _MYELOID_KEYWORDS)
                    )
                if 'Tumor_MES' in ct:
                    mes_total += float(ct.get('Tumor_MES', 0))
                    mes_data_available = True
                for lr_key, val in s.get('lr', {}).items():
                    lr_totals[lr_key] = lr_totals.get(lr_key, 0.0) + float(val)

            tam_avg = (tam_total / len(spots_data)) * 100 if spots_data else 0
            mes_avg = (mes_total / len(spots_data)) * 100 if (spots_data and mes_data_available) else None

            # Risk classification
            mes_risk = T_HIGH if (mes_avg is not None and mes_avg > 15.0) else T_MEDIUM
            tam_risk = T_HIGH if tam_avg > 20.0 else T_MEDIUM
            gen_risk = T_AGGRESSIVE if (mes_risk == T_HIGH or tam_risk == T_HIGH) else T_STABLE
            
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
            mes_high = mes_avg is not None and mes_avg > 15.0
            tam_high = tam_avg > 20.0
            
            # Escape strings safely for embedding into synthesis
            gen_risk_safe = escape_html(stats_calc['gen_risk'])
            top_pathway_safe = escape_html(top_pathway)
            dominant_lr_safe = escape_html(dominant_lr_val)
            if is_english:
                synthesis = (
                    f"Glio-Cartography spatial transcriptomic analysis revealed tumor microenvironment (TME) heterogeneity at {stats_calc['n_spots']:,} spot resolution. "
                    f"According to GNN analysis, the global risk profile of the patient is identified as '{gen_risk_safe}'. "
                )
                
                if mes_high and tam_high:
                    synthesis += (
                        f"The tissue shows a high invasive mesenchymal tumor fraction ({stats_calc['mes_avg']:.1f}%) accompanied by prominent immunosuppressive Tumor-Associated Macrophage (TAM) "
                        f"infiltration ({stats_calc['tam_avg']:.1f}%). The co-occurrence of these two profiles points to an aggressive microenvironment that supports the mesenchymal transition of the tumor and its evasion of T-cell mediated immune response. "
                    )
                elif mes_high:
                    synthesis += (
                        f"A high mesenchymal transition (MES) score ({stats_calc['mes_avg']:.1f}%) is detected across the tissue. "
                        f"This is associated with prominent extracellular matrix (ECM) remodeling, contributing to the tumor's high invasion potential and potential resistance to radiotherapy/chemotherapy. "
                    )
                elif tam_high:
                    synthesis += (
                        f"A high level of immunosuppressive TAM infiltration ({stats_calc['tam_avg']:.1f}%) is observed across the tissue. "
                        f"This confirms a strong myeloid-derived suppression mechanism in the microenvironment, inhibiting the penetration and activation of T-cells inside the tumor. "
                    )
                else:
                    synthesis += "The tumor tissue shows a relatively stable and localized proliferation profile. "
                    
                synthesis += (
                    f"At the signaling pathway level, the '{top_pathway_safe}' pathway is dominantly activated in the tissue. "
                    f"The signaling axis showing the highest activity in the spatial communication analysis is identified as '{dominant_lr_safe}'. "
                )
                
                if dominant_lr_val == "SPP1-CD44":
                    synthesis += (
                        "The high activity of SPP1-CD44 interaction confirms that TAMs establish close contact with tumor cells to stimulate mesenchymal transdifferentiation "
                        "and tumor stem cell (GSC) stemness properties. This axis plays a critical role in resistance to immunotherapy. "
                    )
                elif dominant_lr_val == "VEGFA-KDR":
                    synthesis += (
                        "The dominance of VEGFA-KDR angiogenic signaling supports intense microvascular proliferation and neovascularization niches in response to hypoxia. "
                        "This creates a rationale for anti-VEGF (Bevacizumab) therapy. "
                    )
                elif dominant_lr_val == "MIF-CD74":
                    synthesis += (
                        "Activation of the MIF-CD74 axis stimulates the transition of microglia and macrophages to a pro-inflammatory/immunosuppressive state, "
                        "establishing an immune-evasion environment in favor of the tumor. "
                    )
                elif dominant_lr_val == "SPP1-PTPN1":
                    synthesis += (
                        "SPP1-PTPN1 checkpoint interaction reinforces the suppressive immune response in the microenvironment by inducing T-cell exhaustion. "
                    )
                
                synthesis += (
                    "Zonal contrast analysis shows that mesenchymal and invasive pathways are concentrated in the 'Leading Edge' region, while hypoxic pathways and glycolytic activity "
                    "are concentrated around 'Pseudopalisading Necrosis'. This spatial polarization creates resistant regions with a high risk of local recurrence against standard chemoradiotherapy. "
                    "These zonal dynamics should be considered in treatment planning."
                )
            else:
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
                # NOT: "FDA Approved/Onaylı" etiketi, bu ilaçların GLİOBLASTOM
                # için değil, BAŞKA endikasyonlar için onaylı olduğu
                # durumlarda açıkça belirtilir. Erlotinib NSCLC/pankreas
                # kanserinde onaylı — GBM'de EGFR-TKI çalışmaları tutarlı
                # şekilde başarısız oldu. Pembrolizumab/Atezolizumab genel
                # checkpoint blokajında onaylı ama seçilmemiş GBM'de değil
                # (CheckMate-548 dahil, GBM'de checkpoint blokajı beklenen
                # faydayı göstermedi). Endikasyon farkını belirtmeden
                # "FDA Onaylı" göstermek yanıltıcıdır (bkz. B-06).
                if is_english:
                    DRUGGABLE_CATALOG = {
                        "AKT1": ("Ipatasertib", "AKT Kinase Inhibitor", "Phase II"),
                        "AKT2": ("Ipatasertib", "AKT Kinase Inhibitor", "Phase II"),
                        "MTOR": ("Everolimus", "mTORC1 Complex Blockade", "Phase II/III"),
                        "EGFR": ("Erlotinib", "Receptor Tyrosine Kinase Inhibitor", "FDA Approved (NSCLC/pancreatic — NOT GBM; EGFR-TKIs failed in GBM trials)"),
                        "MET": ("Crizotinib", "HGFR / MET Tyrosine Kinase Blockade", "Phase II"),
                        "KDR": ("Cabozantinib", "VEGFR2 Receptor Inhibition", "Phase III"),
                        "FLT1": ("Regorafenib", "Multikinase / VEGFR1 Inhibitor", "Phase II"),
                        "JAK1": ("Ruxolitinib", "JAK1/JAK2 Signaling Inhibitor", "Phase I/II"),
                        "JAK2": ("Ruxolitinib", "JAK1/JAK2 Signaling Inhibitor", "Phase I/II"),
                        "STAT3": ("Napabucasin", "STAT3 Transcription Inhibitor", "Phase III"),
                        "CD44": ("RG7356", "Anti-CD44 Monoclonal Antibody", "Phase I"),
                        "PDCD1": ("Pembrolizumab", "Anti-PD-1 Checkpoint Blockade", "FDA Approved (other cancers — NOT GBM; underperformed in GBM trials incl. CheckMate-548)"),
                        "CD274": ("Atezolizumab", "Anti-PD-L1 Checkpoint Blockade", "FDA Approved (other cancers — NOT GBM)")
                    }
                else:
                    DRUGGABLE_CATALOG = {
                        "AKT1": ("Ipatasertib", "AKT Kinaz İnhibitörü", "Faz II"),
                        "AKT2": ("Ipatasertib", "AKT Kinaz İnhibitörü", "Faz II"),
                        "MTOR": ("Everolimus", "mTORC1 Kompleks Blokajı", "Faz II/III"),
                        "EGFR": ("Erlotinib", "Reseptör Tirozin Kinaz İnhibitörü", "FDA Onaylı (NSCLC/pankreas — GBM DEĞİL; EGFR-TKI'ler GBM çalışmalarında başarısız oldu)"),
                        "MET": ("Crizotinib", "HGFR / MET Tirozin Kinaz Blokajı", "Faz II"),
                        "KDR": ("Cabozantinib", "VEGFR2 Reseptör İnhibisyonu", "Faz III"),
                        "FLT1": ("Regorafenib", "Multikinaz / VEGFR1 İnhibitörü", "Faz II"),
                        "JAK1": ("Ruxolitinib", "JAK1/JAK2 Sinyal İletim İnhibitörü", "Faz I/II"),
                        "JAK2": ("Ruxolitinib", "JAK1/JAK2 Sinyal İletim İnhibitörü", "Faz I/II"),
                        "STAT3": ("Napabucasin", "STAT3 Transkripsiyon İnhibitörü", "Faz II"),
                        "CD44": ("RG7356", "Anti-CD44 Monoklonal Antikor", "Faz I"),
                        "PDCD1": ("Pembrolizumab", "Anti-PD-1 Checkpoint Blokajı", "FDA Onaylı (diğer kanserler — GBM DEĞİL; CheckMate-548 dahil GBM çalışmalarında beklenen faydayı göstermedi)"),
                        "CD274": ("Atezolizumab", "Anti-PD-L1 Checkpoint Blokajı", "FDA Onaylı (diğer kanserler — GBM DEĞİL)")
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
        fallback_enrich = "No enriched downstream pathways detected." if is_english else "Zenginleştirilmiş downstream yolak saptanamadı."
        enrichment_rows = f"<tr><td colspan='6' style='text-align:center; color:#999;'>{fallback_enrich}</td></tr>"
    if not druggable_rows:
        fallback_drug = "No targetable downstream protein candidates detected." if is_english else "Hedeflenebilir downstream protein adayı saptanamadı."
        druggable_rows = f"<tr><td colspan='5' style='text-align:center; color:#999;'>{fallback_drug}</td></tr>"

    # Calculate Clinical Profile
    clinical = compute_clinical_profile(gnn_summary, deconv_summary, prep_summary)

    # Analiz güvenilirlik / veri kalitesi özeti [GELİŞTİRME]
    data_quality = compute_data_quality_summary(gnn_summary, deconv_summary, clinical)

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

    # DÜZELTME (2026-08-20): mes_avg artık gerçek veri yoksa None olabilir
    # (bkz. yukarıdaki mes_data_available notu) — pipeline'da mezenkimal
    # alt-tip fraksiyonu şu an hiçbir yerde gerçekten hesaplanmadığı için,
    # sahte bir yüzde sunmak yerine bu cümle koşullu kuruluyor.
    if is_english:
        mes_clause = f"a <strong>{mes_avg:.1f}% Mesenchymal (MES)</strong> fraction and a " if mes_avg is not None else ""
        exec_summary = (
            f"Glio-Cartography analysis of the patient revealed a microenvironment characterized by {mes_clause}"
            f"<strong>{tam_avg:.1f}% Tumor-Associated Macrophage (TAM)</strong> infiltration across the tumor, presenting a <strong>{risk_level_safe}</strong> risk profile. "
            f"The <strong>{dominant_lr_val_safe}</strong> interaction, identified as the most active signaling axis in the spatial communication analysis, supports intense "
            f"immunosuppression and high invasive potential. Considering the patient's <strong>{mgmt_status_short_safe}</strong> status, an aggressive combined treatment protocol is recommended."
        )
    else:
        mes_clause = f"<strong>%{mes_avg:.1f} Mezenkimal (MES)</strong> fraksiyonu ve " if mes_avg is not None else ""
        exec_summary = (
            f"Hastada yapılan Glio-Cartography analizi sonucunda, tümör genelinde {mes_clause}"
            f"<strong>%{tam_avg:.1f} Tümör İlişkili Makrofaj (TAM)</strong> infiltrasyonu ile karakterize, <strong>{risk_level_safe}</strong> risk profiline sahip "
            f"bir mikroçevre saptanmıştır. Uzamsal iletişim analizinde en aktif sinyal ekseni olan <strong>{dominant_lr_val_safe}</strong> etkileşimi, yoğun "
            f"immünsüpresyonu ve yüksek invazyon potansiyelini desteklemekte olup, hastanın <strong>{mgmt_status_short_safe}</strong> "
            f"statusu da göz önüne alınarak agresif bir kombine tedavi protokolü önerilmektedir."
        )

    # PubMed References
    pubmed_refs = generate_pubmed_references(dominant_lr_val, clinical.get('mgmt_status_short'), pathways)
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

    # Localized UI elements
    T_HTML_LANG = "en" if is_english else "tr"
    T_TITLE = f"Glio-Cartography — Clinical Report: {patient_id_safe}" if is_english else f"Glio-Cartography — Klinik Rapor: {patient_id_safe}"
    T_TME_ATLAS = "Spatial Tumor Microenvironment Atlas" if is_english else "Spatial Tümör Mikroçevre Atlası"
    T_PATIENT = f"Patient: {patient_id_safe}" if is_english else f"Hasta: {patient_id_safe}"
    T_DOWNLOAD_PDF = "📥 Download PDF" if is_english else "📥 PDF Olarak İndir"
    T_SUMMARY_TITLE = "📋 Clinical Executive Summary &amp; Spatial Risk Map" if is_english else "📋 Klinik Yönetici Özeti &amp; Uzamsal Risk Haritası"
    T_EXEC_SUMMARY = "📋 Executive Summary" if is_english else "📋 Yönetici Özeti"
    T_SVG_MAP_TITLE = "🗺️ Vectorial Spatial Risk Map (Mini SVG)" if is_english else "🗺️ Vektörel Uzamsal Risk Haritası (Mini SVG)"
    T_STABLE_LABEL = "● Stable (Low Risk)" if is_english else "● Stabil (Düşük Risk)"
    T_AGGRESSIVE_LABEL = "● Aggressive (High Risk)" if is_english else "● Agresif (Yüksek Risk)"
    
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

    T_CLINICAL_DECISION = "🧬 Clinical Profile &amp; Decision Support" if is_english else "🧬 Klinik Özellikler &amp; Karar Destek"
    T_RUO_WARNING = "⚠️ These evaluations are computational predictions. Histopathology and molecular testing are required for clinical validation." if is_english else "⚠️ Bu değerlendirmeler hesapsal tahmindir. Klinik onay için histopatoloji ve moleküler testler gereklidir."
    T_MOLECULAR_PROFILE = "Molecular Profile (Computational)" if is_english else "Moleküler Profil (Hesapsal)"
    T_RECOMMENDED_PROTOCOL = "Recommended Treatment Protocol" if is_english else "Önerilen Tedavi Protokolü"
    T_PROTOCOL_DESC = "Based on GNN + Spatial microenvironment analysis:" if is_english else "GNN + Spatial mikroçevre analizine dayalı:"
    T_SOURCES = "Sources" if is_english else "Kaynaklar"
    
    T_DIAGNOSIS_LBL = "Diagnosis:" if is_english else "Tanı:"
    T_WHO_GRADE_LBL = "WHO Grade:" if is_english else "WHO Grade:"
    T_IDH_LBL = "IDH Status:" if is_english else "IDH Durumu:"
    T_MGMT_LBL = "MGMT Promoter:" if is_english else "MGMT Promotör:"
    T_TUMOR_LBL = "Tumor Fraction:" if is_english else "Tümör Fraksiyon:"
    T_MYELOID_LBL = "Myeloid/TAM:" if is_english else "Myeloid/TAM:"
    T_TCELL_LBL = "T-Cell Infiltration:" if is_english else "T-Hücre İnfiltrasyonu:"

    T_CLINICAL_SYNTHESIS_TITLE = "📋 Clinical Synthesis and Tumor Microenvironment (TME) Dynamics" if is_english else "📋 Klinik Sentez ve Tümör Mikroçevresi (TME) Dinamikleri"
    T_DOWNSTREAM_PATHWAY_TITLE = "🧬 Downstream Pathway Activation" if is_english else "🧬 Downstream Yolak Aktivasyonu"
    T_AVG_PATHWAY_SCORES = "Average Downstream Pathway Scores" if is_english else "Ortalama Downstream Yolak Skorları"
    T_DOMINANT_PATHWAY = "Dominant Downstream Pathway" if is_english else "Baskın Downstream Yolak"
    T_DOMINANT_PATHWAY_DESC = "The dominant downstream signaling cascade driving tumor proliferation, survival, and invasion mechanisms." if is_english else "Tümörün proliferasyon, sağkalım ve invazyon mekanizmalarını yönlendiren baskın downstream sinyal kaskadı."
    
    T_ENRICHED_PATHWAYS_TITLE = f"🧬 L-R Downstream Enriched Pathways ({dominant_lr_val_safe})" if is_english else f"🧬 L-R Downstream Zenginleştirilmiş Yolaklar ({dominant_lr_val_safe})"
    T_ENRICHED_PATHWAYS_DESC = f"Significant downstream pathways induced by the dominant {dominant_lr_val_safe} signaling axis:" if is_english else f"Baskın {dominant_lr_val_safe} sinyalleşme ekseninin uyardığı anlamlı downstream yolaklar:"
    T_PATHWAY_ID = "Pathway ID" if is_english else "Yolak ID"
    T_PATHWAY_NAME = "Pathway Name" if is_english else "Yolak Adı"
    T_TYPE = "Type" if is_english else "Tip"
    T_OVERLAP = "Overlap / Pathway" if is_english else "Overlap / Yolak"
    T_PVALUE = "p-Value" if is_english else "p-Değeri"
    T_FDR = "FDR q-Value" if is_english else "FDR q-Değeri"
    
    T_DRUGGABLE_TITLE = "💊 Targetable Downstream Drug Candidates" if is_english else "💊 Hedeflenebilir Downstream İlaç Adayları"
    T_DRUGGABLE_DESC = "Targetable protein candidates in induced downstream pathways:" if is_english else "Uyarılmış downstream yolaklarda hedeflenebilir durumdaki protein adayları:"
    T_TARGET_GENE = "Target Gene" if is_english else "Hedef Gen"
    T_INDUCED_PATHWAY = "Induced Pathway" if is_english else "Uyarılmış Yolak"
    T_ACTIVE_DRUG = "Active Drug" if is_english else "Etkin İlaç"
    T_MECHANISM = "Mechanism of Action" if is_english else "Etki Mekanizması"
    T_CLINICAL_STAGE = "Clinical Stage" if is_english else "Klinik Aşama"
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
    
    T_PUBMED_REFS = "📚 Dynamic Clinical References (PubMed)" if is_english else "📚 Dinamik Klinik Referanslar (PubMed)"
    T_PUBMED_DESC = "Recent literature on ligand-receptor pairs, drug targets, and risk models mentioned in this report:" if is_english else "Raporda geçen ligand-reseptör çiftleri, ilaç hedefleri ve risk modellerine ait güncel literatür:"
    T_AUTO_GENERATED = "This report was generated automatically. Please consult an expert for clinical decisions." if is_english else "Bu rapor otomatik olarak oluşturulmuştur. Klinik karar için uzman görüşü alınız."
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
        "T_SVG_MAP_TITLE": T_SVG_MAP_TITLE,
        "svg_map_html": svg_map_html,
        "T_STABLE_LABEL": T_STABLE_LABEL,
        "T_AGGRESSIVE_LABEL": T_AGGRESSIVE_LABEL,
        "T_GENERAL_METRICS": T_GENERAL_METRICS,
        "n_spots": f"{n_spots:,}",
        "cell_types_count": len(CT_NAMES),
        "test_mse": f"{test_mse:.5f}",
        "deconv_confidence": f"%{deconv_summary.get('avg_confidence', 0)*100:.1f}",
        "T_CELL_TYPES": T_CELL_TYPES,
        "T_DECONV_CONFIDENCE": T_DECONV_CONFIDENCE,
        "T_GNN_TEST_MSE": T_GNN_TEST_MSE,
        "T_DATA_QUALITY_TITLE": T_DATA_QUALITY_TITLE,
        "T_DATA_QUALITY_DESC": T_DATA_QUALITY_DESC,
        "T_OVERALL_LEVEL": T_OVERALL_LEVEL,
        "dq_overall_label": data_quality["overall_label"],
        "dq_overall_color": data_quality["overall_color"],
        "dq_items": data_quality["items"],
        "T_CLINICAL_DECISION": T_CLINICAL_DECISION,
        "T_RUO_WARNING": T_RUO_WARNING,
        "T_MOLECULAR_PROFILE": T_MOLECULAR_PROFILE,
        "T_DIAGNOSIS_LBL": T_DIAGNOSIS_LBL,
        "diagnosis_safe": diagnosis_safe,
        "T_WHO_GRADE_LBL": T_WHO_GRADE_LBL,
        "who_grade_color_safe": who_grade_color_safe,
        "who_grade_safe": who_grade_safe,
        "T_IDH_LBL": T_IDH_LBL,
        "idh_status_safe": idh_status_safe,
        "idh_note_safe": idh_note_safe,
        "T_MGMT_LBL": T_MGMT_LBL,
        "mgmt_color_safe": mgmt_color_safe,
        "mgmt_status_short_safe": mgmt_status_short_safe,
        "T_TUMOR_LBL": T_TUMOR_LBL,
        "tumor_fraction_pct": f"%{clinical['tumor_frac']*100:.1f}",
        "T_MYELOID_LBL": T_MYELOID_LBL,
        "myeloid_fraction_pct": f"%{clinical['myeloid_frac']*100:.1f}",
        "T_TCELL_LBL": T_TCELL_LBL,
        "tcell_fraction_pct": f"%{clinical['tcell_frac']*100:.1f}",
        "T_RECOMMENDED_PROTOCOL": T_RECOMMENDED_PROTOCOL,
        "T_PROTOCOL_DESC": T_PROTOCOL_DESC,
        "protocols": clinical['protocols'],
        "T_SOURCES": T_SOURCES,
        "rationale_safe": '  ·  '.join(escape_html(ref) for ref in clinical['rationale']) or 'N/A',
        "mgmt_status_safe": mgmt_status_safe,
        "T_CLINICAL_SYNTHESIS_TITLE": T_CLINICAL_SYNTHESIS_TITLE,
        "clinical_synthesis": clinical_synthesis,
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
        "T_DRUGGABLE_TITLE": T_DRUGGABLE_TITLE,
        "T_DRUGGABLE_DESC": T_DRUGGABLE_DESC,
        "T_TARGET_GENE": T_TARGET_GENE,
        "T_INDUCED_PATHWAY": T_INDUCED_PATHWAY,
        "T_ACTIVE_DRUG": T_ACTIVE_DRUG,
        "T_MECHANISM": T_MECHANISM,
        "T_CLINICAL_STAGE": T_CLINICAL_STAGE,
        "druggable_rows": druggable_rows,
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
