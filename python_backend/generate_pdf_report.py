#!/usr/bin/env python3
"""
GLIO-CARTOGRAPHY — Klinik PDF Rapor Üreticisi (v2.0 - Gold Standard)

Düzeltmeler (v2.0):
- İndentasyon tamamen düzeltildi
- ax3.text(..., int(yval)) → f"{int(yval):,}" (TypeError düzeltildi)
- os.path.dirname boş string güvenliği eklendi
- n_spots == 0 ZeroDivisionError koruması
- Risk eşiği ayrı MES/TAM thresholdlarına ayrıldı (keyfi toplam kaldırıldı)
- Pasta grafiği sıfır dilim filtresi
- "None"/"N/A" ilaçlar bar chart'tan filtrelendi
- TCGA survival özet paneli eklendi
- L-R sinyal kanalları özeti eklendi
- RUO disclaimer görünür ve renkli yapıldı
- try/except hata yönetimi eklendi
- İki sayfalı rapor: Sayfa 1 = Global özet, Sayfa 2 = Detay
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import gzip
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.gridspec import GridSpec
import sys
from loguru import logger

# ============================================================
# YOLLAR VE AYARLAR
# ============================================================
# CLI argument parsing
JSON_PATH = sys.argv[1] if len(sys.argv) > 1 else "visualizer/data.json.gz"
PDF_PATH  = sys.argv[2] if len(sys.argv) > 2 else "outputs/Klinik_Rapor_Hasta_A.pdf"
PATIENT_LABEL = sys.argv[3] if len(sys.argv) > 3 else "HASTA A (Referans)"

# Biyolojik risk eşikleri (literatür tabanlı)
MES_HIGH_THRESHOLD = 15.0   # %15 üzeri Tumor_MES → yüksek invazyon riski
TAM_HIGH_THRESHOLD = 20.0   # %20 üzeri TAM → yüksek immünsüpresyon
TCGA_MEDIAN_OS     = 14.0   # TCGA IDH-wildtype GBM medyan OS (ay)

# Renk paleti (web atlasıyla tutarlı)
COLORS = {
    'accent':   '#00FFCC',
    'danger':   '#FF3366',
    'warning':  '#FF8C00',
    'tumor':    '#E63946',
    'immune':   '#457B9D',
    'muted':    '#888888',
    'bg_dark':  '#0d1117',
    'bg_panel': '#1a1a2e',
}

ZONE_COLORS = [
    '#E63946', '#F4A261', '#E9C46A', '#2A9D8F', '#264653',
    '#9f86c0', '#5e548e', '#c77dff'
]


# ============================================================
# VERİ YÜKLEME
# ============================================================

def load_data(json_path):
    """gzip veya düz JSON yükler."""
    if json_path.endswith('.gz'):
        with gzip.open(json_path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    else:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)


# ============================================================
# VERİ AGREGASYonu
# ============================================================

def aggregate_data(spots, zone_names):
    """Tüm spotlardan global istatistikler üretir."""
    n_spots = len(spots)
    if n_spots == 0:
        raise ValueError("Veri boş — spot sayısı 0!")

    zone_counts  = {z: 0 for z in zone_names}
    tam_total    = 0.0
    mes_total    = 0.0
    drugs        = {}
    lr_totals    = {}
    survival_vals = []
    risk_vals    = []

    for s in spots:
        # Dominant zon
        z_dict    = s.get('zones', {})
        if z_dict:
            best_zone = max(z_dict, key=z_dict.get)
            if best_zone in zone_counts:
                zone_counts[best_zone] += 1

        # Hücre tipleri
        ct = s.get('ct', {})
        tam_total += float(ct.get('TAM', 0))
        mes_total += float(ct.get('Tumor_MES', 0))

        # İlaçlar — None/N/A filtrele
        drg = s.get('drug', 'None')
        if drg and drg not in ('None', 'N/A', ''):
            drugs[drg] = drugs.get(drg, 0) + 1

        # L-R sinyalleri
        for lr_key, val in s.get('lr', {}).items():
            lr_totals[lr_key] = lr_totals.get(lr_key, 0.0) + float(val)

        # Survival
        sv = s.get('survival_months', None)
        if sv and float(sv) > 0:
            survival_vals.append(float(sv))

        # Risk skoru
        rv = s.get('tcga_risk', None)
        if rv is not None:
            risk_vals.append(float(rv))

    # Yüzdeler
    zone_percs = {k: (v / n_spots) * 100 for k, v in zone_counts.items()}
    tam_avg    = (tam_total / n_spots) * 100
    mes_avg    = (mes_total / n_spots) * 100

    # Top ilaçlar (None filtreli)
    if drugs:
        top_drugs = sorted(drugs.items(), key=lambda x: x[1], reverse=True)[:4]
    else:
        top_drugs = [("Standart Bakım (Temozolomide)", n_spots)]

    # Top L-R (ortalama aktivite)
    top_lr = sorted(
        [(k, v / n_spots) for k, v in lr_totals.items()],
        key=lambda x: x[1], reverse=True
    )[:4]

    # Survival
    median_survival = float(np.median(survival_vals)) if survival_vals else TCGA_MEDIAN_OS
    mean_risk       = float(np.mean(risk_vals)) if risk_vals else 0.5

    # Risk sınıflandırması
    mes_risk = "YÜKSEK" if mes_avg > MES_HIGH_THRESHOLD else "ORTA"
    tam_risk = "YÜKSEK" if tam_avg > TAM_HIGH_THRESHOLD else "ORTA"
    gen_risk = "AGRESİF" if (mes_risk == "YÜKSEK" or tam_risk == "YÜKSEK") \
               else "STABİL"

    return {
        'n_spots':         n_spots,
        'zone_percs':      zone_percs,
        'tam_avg':         tam_avg,
        'mes_avg':         mes_avg,
        'mes_risk':        mes_risk,
        'tam_risk':        tam_risk,
        'gen_risk':        gen_risk,
        'top_drugs':       top_drugs,
        'top_lr':          top_lr,
        'median_survival': median_survival,
        'mean_risk':       mean_risk,
        'survival_delta':  median_survival - TCGA_MEDIAN_OS,
    }


# ============================================================
# SAYFA 1 — GLOBAL ÖZET
# ============================================================

def draw_page1(fig, stats, zone_names, patient_label="HASTA A"):
    """Ana klinik özet sayfası."""
    fig.patch.set_facecolor(COLORS['bg_dark'])
    gs = GridSpec(3, 2, figure=fig,
                  left=0.08, right=0.95,
                  top=0.88, bottom=0.12,
                  hspace=0.5, wspace=0.4)

    # ── Başlık ──────────────────────────────────────────────
    fig.text(0.5, 0.95,
             "GLIO-CARTOGRAPHY  |  KLİNİK ONKOLOJİ ÖZET RAPORU",
             ha='center', va='top', fontsize=16, weight='bold',
             color=COLORS['accent'], fontfamily='monospace')

    fig.text(0.5, 0.915,
             f"{patient_label}  |  Glioblastoma Multiforme (IDH-wildtype)  |  "
             f"Analiz: {stats['n_spots']:,} Visium Spotu",
             ha='center', va='top', fontsize=10,
             color='#cccccc')

    # ── Panel 1: Tümör Mimarisi Pasta ───────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor(COLORS['bg_panel'])

    filtered_zones = [(z, stats['zone_percs'][z])
                      for z in zone_names
                      if stats['zone_percs'].get(z, 0) > 0.5]

    if filtered_zones:
        labels_f = [z[0].replace(' ', '\n') for z in filtered_zones]
        sizes_f  = [z[1] for z in filtered_zones]
        clrs_f   = ZONE_COLORS[:len(filtered_zones)]
        wedges, texts, autotexts = ax1.pie(
            sizes_f, labels=labels_f, autopct='%1.1f%%',
            startangle=90, colors=clrs_f,
            textprops={'color': 'white', 'fontsize': 7},
            wedgeprops={'edgecolor': COLORS['bg_dark'], 'linewidth': 1.5}
        )
        for at in autotexts:
            at.set_fontsize(7)
            at.set_fontweight('bold')
    else:
        ax1.text(0.5, 0.5, "Zon verisi\nbulunamadı",
                 ha='center', va='center', color='white', fontsize=10,
                 transform=ax1.transAxes)

    ax1.set_title("Tümör Mimarisi (GNN Zon)", color='white',
                  fontsize=10, weight='bold', pad=8)

    # ── Panel 2: Risk Analizi ────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.axis('off')
    ax2.set_facecolor(COLORS['bg_panel'])

    risk_color = COLORS['danger'] if stats['gen_risk'] == "AGRESİF" \
                 else COLORS['accent']

    ax2.text(0.05, 0.95, "🔴  GLOBAL RİSK PROFİLİ",
             transform=ax2.transAxes, color=COLORS['danger'],
             fontsize=11, weight='bold', va='top')

    rows = [
        ("İnvaziv Mezenkimal (MES)", f"%{stats['mes_avg']:.1f}", stats['mes_risk']),
        ("İmmünsüpresif TAM Yükü",   f"%{stats['tam_avg']:.1f}", stats['tam_risk']),
    ]
    for i, (label, val, risk) in enumerate(rows):
        y = 0.78 - i * 0.22
        ax2.text(0.05, y, label, transform=ax2.transAxes,
                 color='#cccccc', fontsize=9)
        rc = COLORS['danger'] if risk == "YÜKSEK" else COLORS['warning']
        ax2.text(0.05, y - 0.10, f"{val}  [{risk}]",
                 transform=ax2.transAxes, color=rc,
                 fontsize=10, weight='bold')

    ax2.text(0.05, 0.28,
             f"GNN Genel Skor:  {stats['gen_risk']}",
             transform=ax2.transAxes, color=risk_color,
             fontsize=12, weight='bold')

    ax2.add_patch(mpatches.FancyBboxPatch(
        (0.0, 0.0), 1.0, 1.0,
        boxstyle="round,pad=0.02",
        facecolor=COLORS['bg_panel'],
        edgecolor=risk_color, linewidth=1.5,
        transform=ax2.transAxes, clip_on=False
    ))

    # ── Panel 3: İlaç Bar Chart ──────────────────────────────
    ax3 = fig.add_subplot(gs[1, :])
    ax3.set_facecolor(COLORS['bg_panel'])

    d_labels = [d[0] for d in stats['top_drugs']]
    d_vals   = [d[1] for d in stats['top_drugs']]
    bar_colors = [COLORS['accent'], '#F4A261', COLORS['tumor'], '#9f86c0']
    bars = ax3.barh(d_labels, d_vals,
                    color=bar_colors[:len(d_labels)],
                    edgecolor=COLORS['bg_dark'], linewidth=0.5, height=0.5)

    ax3.set_xlabel("Önerilen Spot Sayısı", color='#cccccc', fontsize=9)
    ax3.set_title("Hedefe Yönelik İlaç Önerileri — Spot Dağılımı",
                  color='white', fontsize=10, weight='bold', pad=8)
    ax3.tick_params(colors='white', labelsize=8)
    ax3.spines['bottom'].set_color('#444')
    ax3.spines['left'].set_color('#444')
    ax3.spines['top'].set_visible(False)
    ax3.spines['right'].set_visible(False)
    ax3.invert_yaxis()

    max_val = max(d_vals) if d_vals else 1
    for bar, val in zip(bars, d_vals):
        ax3.text(val + max_val * 0.01,
                 bar.get_y() + bar.get_height() / 2,
                 f"{int(val):,} spot",          # ✅ string — TypeError önlendi
                 va='center', color='white',
                 fontsize=8, weight='bold')

    # ── Panel 4: TCGA Survival ───────────────────────────────
    ax4 = fig.add_subplot(gs[2, 0])
    ax4.axis('off')
    ax4.set_facecolor(COLORS['bg_panel'])

    delta      = stats['survival_delta']
    delta_col  = COLORS['accent'] if delta >= 0 else COLORS['danger']
    delta_sign = "+" if delta >= 0 else ""

    ax4.text(0.05, 0.95, "📊  TCGA Survival Profili",
             transform=ax4.transAxes, color=COLORS['accent'],
             fontsize=10, weight='bold', va='top')
    ax4.text(0.05, 0.72,
             f"Tahmini Medyan OS:  {stats['median_survival']:.1f} Ay",
             transform=ax4.transAxes, color='white',
             fontsize=12, weight='bold')
    ax4.text(0.05, 0.52,
             f"TCGA Referans:  {TCGA_MEDIAN_OS:.1f} Ay",
             transform=ax4.transAxes, color='#aaaaaa', fontsize=9)
    ax4.text(0.05, 0.34,
             f"Profil Farkı:  {delta_sign}{delta:.1f} Ay",
             transform=ax4.transAxes, color=delta_col,
             fontsize=11, weight='bold')
    ax4.text(0.05, 0.14,
             "⚠️ Simülatif — klinik karar aracı değil",
             transform=ax4.transAxes, color='#888888',
             fontsize=7, style='italic')

    ax4.add_patch(mpatches.FancyBboxPatch(
        (0.0, 0.0), 1.0, 1.0,
        boxstyle="round,pad=0.02",
        facecolor=COLORS['bg_panel'],
        edgecolor=COLORS['accent'], linewidth=1.0,
        transform=ax4.transAxes, clip_on=False
    ))

    # ── Panel 5: L-R Sinyal Kanalları ───────────────────────
    ax5 = fig.add_subplot(gs[2, 1])
    ax5.axis('off')
    ax5.set_facecolor(COLORS['bg_panel'])

    ax5.text(0.05, 0.95, "🧬  Baskın L-R Sinyal Kanalları",
             transform=ax5.transAxes, color='#F4A261',
             fontsize=10, weight='bold', va='top')

    for i, (lr_key, avg_val) in enumerate(stats['top_lr']):
        y = 0.75 - i * 0.20
        ax5.text(0.05, y, f"• {lr_key}",
                 transform=ax5.transAxes, color='white', fontsize=9)
        ax5.text(0.05, y - 0.10,
                 f"  Ort. Aktivite: {avg_val:.4f}",
                 transform=ax5.transAxes, color='#F4A261',
                 fontsize=8)

    ax5.add_patch(mpatches.FancyBboxPatch(
        (0.0, 0.0), 1.0, 1.0,
        boxstyle="round,pad=0.02",
        facecolor=COLORS['bg_panel'],
        edgecolor='#F4A261', linewidth=1.0,
        transform=ax5.transAxes, clip_on=False
    ))

    # ── Disclaimer ───────────────────────────────────────────
    fig.text(
        0.5, 0.04,
        "⚠️  ARAŞTIRMA KULLANIMI İÇİN (RUO) — Klinik karar verme aracı değildir. "
        "Uzman onkolog denetimi gerektirir.  |  Glio-Cartography GNN v2.0",
        ha='center', va='center', fontsize=8,
        color=COLORS['warning'],
        bbox=dict(boxstyle='round,pad=0.4',
                  facecolor='#1a0a00',
                  edgecolor=COLORS['warning'],
                  alpha=0.85)
    )


# ============================================================
# SAYFA 2 — DETAY: ZON DAĞILIM TABLOSU + L-R BARCHART
# ============================================================

def draw_page2(fig, stats, zone_names, patient_label="HASTA A"):
    """Detay sayfası — zon dağılım tablosu ve L-R karşılaştırma."""
    fig.patch.set_facecolor(COLORS['bg_dark'])
    gs = GridSpec(2, 1, figure=fig,
                  left=0.1, right=0.92,
                  top=0.88, bottom=0.12,
                  hspace=0.5)

    fig.text(0.5, 0.94,
             f"GLIO-CARTOGRAPHY  |  Detay Analiz  |  {patient_label}",
             ha='center', fontsize=14, weight='bold',
             color=COLORS['accent'])

    # ── Zon Dağılım Bar Chart ────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    ax1.set_facecolor(COLORS['bg_panel'])

    valid_zones = [(z, stats['zone_percs'][z])
                   for z in zone_names
                   if stats['zone_percs'].get(z, 0) > 0]
    if valid_zones:
        zn_labels = [z[0] for z in valid_zones]
        zn_vals   = [z[1] for z in valid_zones]
        clrs      = ZONE_COLORS[:len(valid_zones)]

        bars = ax1.bar(range(len(zn_labels)), zn_vals,
                       color=clrs, edgecolor=COLORS['bg_dark'],
                       linewidth=0.5)
        ax1.set_xticks(range(len(zn_labels)))
        ax1.set_xticklabels(zn_labels, rotation=25, ha='right',
                             color='white', fontsize=8)
        ax1.set_ylabel("Oran (%)", color='#cccccc', fontsize=9)
        ax1.set_title("Anatomik Zon Dağılımı (GNN Tahmini)",
                      color='white', fontsize=11, weight='bold', pad=8)
        ax1.tick_params(colors='white')
        ax1.spines['bottom'].set_color('#444')
        ax1.spines['left'].set_color('#444')
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)

        for bar, val in zip(bars, zn_vals):
            ax1.text(bar.get_x() + bar.get_width() / 2,
                     val + 0.3,
                     f"%{val:.1f}",
                     ha='center', va='bottom',
                     color='white', fontsize=8, weight='bold')

    # ── L-R Aktivite Detay ───────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor(COLORS['bg_panel'])

    if stats['top_lr']:
        lr_labels = [lr[0] for lr in stats['top_lr']]
        lr_vals   = [lr[1] for lr in stats['top_lr']]
        lr_colors = ['#F4A261', '#E63946', '#2A9D8F', '#9f86c0']

        bars2 = ax2.bar(range(len(lr_labels)), lr_vals,
                        color=lr_colors[:len(lr_labels)],
                        edgecolor=COLORS['bg_dark'], linewidth=0.5)
        ax2.set_xticks(range(len(lr_labels)))
        ax2.set_xticklabels(lr_labels, rotation=15, ha='right',
                             color='white', fontsize=9)
        ax2.set_ylabel("Ortalama Aktivite (L×R)", color='#cccccc', fontsize=9)
        ax2.set_title("En Aktif Ligand-Reseptör Sinyal Kanalları",
                      color='white', fontsize=11, weight='bold', pad=8)
        ax2.tick_params(colors='white')
        ax2.spines['bottom'].set_color('#444')
        ax2.spines['left'].set_color('#444')
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)

        for bar, val in zip(bars2, lr_vals):
            ax2.text(bar.get_x() + bar.get_width() / 2,
                     val + max(lr_vals) * 0.01,
                     f"{val:.4f}",
                     ha='center', va='bottom',
                     color='white', fontsize=8, weight='bold')

    # Disclaimer
    fig.text(
        0.5, 0.04,
        "⚠️  ARAŞTIRMA KULLANIMI İÇİN (RUO)  |  Glio-Cartography GNN v2.0",
        ha='center', fontsize=8, color=COLORS['warning'],
        bbox=dict(boxstyle='round,pad=0.3',
                  facecolor='#1a0a00',
                  edgecolor=COLORS['warning'],
                  alpha=0.8)
    )


# ============================================================
# ANA AKIŞ
# ============================================================

def main():
    logger.info("=" * 60)
    logger.info("KLİNİK PDF RAPOR ÜRETİCİSİ v2.0")
    logger.info("=" * 60)

    # Dosya kontrolü
    if not os.path.exists(JSON_PATH):
        logger.error(f"❌ JSON verisi bulunamadı: {JSON_PATH}")
        logger.error("Önce export_for_web.py çalıştırın.")
        return

    # Veri yükle
    logger.info(f"Veri yükleniyor: {JSON_PATH}")
    try:
        data = load_data(JSON_PATH)
    except Exception as e:
        logger.error(f"❌ Veri yüklenemedi: {e}")
        return

    spots      = data.get('spots', [])
    zone_names = data.get('metadata', {}).get('zones', [])

    if not spots:
        logger.error("❌ Spot verisi boş!")
        return
    if not zone_names:
        logger.warning("Zone isimleri bulunamadı — spot zone anahtarlarından çıkarılıyor")
        zone_names = list(spots[0].get('zones', {}).keys()) if spots else []

    # Agregasyon
    logger.info(f"{len(spots):,} spot agregasyonu hesaplanıyor...")
    try:
        stats = aggregate_data(spots, zone_names)
    except ValueError as e:
        logger.error(f"❌ Agregasyon hatası: {e}")
        return

    logger.info(f"Risk profili: {stats['gen_risk']}")
    logger.info(f"Medyan tahmini OS: {stats['median_survival']:.1f} Ay")
    logger.info(f"Top ilaçlar: {[d[0] for d in stats['top_drugs']]}")

    # Çıktı dizini
    out_dir = os.path.dirname(PDF_PATH) or "."
    os.makedirs(out_dir, exist_ok=True)

    # PDF oluştur
    logger.info("PDF dokümanı oluşturuluyor (2 sayfa)...")
    plt.style.use('dark_background')

    try:
        with PdfPages(PDF_PATH) as pdf:

            # Sayfa 1 — Global Özet
            fig1 = plt.figure(figsize=(8.27, 11.69))  # A4
            draw_page1(fig1, stats, zone_names, patient_label=PATIENT_LABEL)
            pdf.savefig(fig1, facecolor=fig1.get_facecolor())
            plt.close(fig1)
            logger.info("  ✅ Sayfa 1 (Global Özet) eklendi")

            # Sayfa 2 — Detay Analiz
            fig2 = plt.figure(figsize=(8.27, 11.69))  # A4
            draw_page2(fig2, stats, zone_names, patient_label=PATIENT_LABEL)
            pdf.savefig(fig2, facecolor=fig2.get_facecolor())
            plt.close(fig2)
            logger.info("  ✅ Sayfa 2 (Detay Analiz) eklendi")

            # PDF Metadata
            d = pdf.infodict()
            d['Title']   = 'Glio-Cartography Klinik Onkoloji Raporu'
            d['Author']  = 'Glio-Cartography GNN v2.0'
            d['Subject'] = 'GBM Spatial Transcriptomics Analizi — RUO'
            d['Keywords']= 'GBM, Spatial, GNN, Tangram, TCGA'

    except Exception as e:
        logger.error(f"❌ PDF oluşturma hatası: {e}")
        return

    logger.info("=" * 60)
    logger.info(f"✅ Klinik PDF Raporu hazırlandı: {PDF_PATH}")
    logger.info(f"   Sayfa sayısı  : 2")
    logger.info(f"   Spot sayısı   : {stats['n_spots']:,}")
    logger.info(f"   Risk profili  : {stats['gen_risk']}")
    logger.info(f"   Medyan OS     : {stats['median_survival']:.1f} Ay")
    logger.info(f"   Top ilaç      : {stats['top_drugs'][0][0] if stats['top_drugs'] else 'N/A'}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()