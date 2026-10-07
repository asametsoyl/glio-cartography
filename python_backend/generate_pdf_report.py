#!/usr/bin/env python3
"""
GLIO-CARTOGRAPHY — Araştırma PDF Rapor Üreticisi (v3.0)

Düzeltmeler (v3.0):
- Downstream pathway activation scores (PI3K/AKT/mTOR, MAPK/ERK, JAK/STAT, NFkB)
- Zonal contrast (grouped bar chart comparing pathways across anatomical zones)
- Research-use only: no drug, risk, survival or treatment output
- Fully local and secure, offline execution
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
import textwrap
from loguru import logger

# ============================================================
# YOLLAR VE AYARLAR
# ============================================================
# CLI argument parsing
JSON_PATH = sys.argv[1] if len(sys.argv) > 1 else "visualizer/data.json.gz"
PDF_PATH  = sys.argv[2] if len(sys.argv) > 2 else "outputs/Rapor_Hasta_A.pdf"
PATIENT_LABEL = sys.argv[3] if len(sys.argv) > 3 else "HASTA A (Referans)"

# Language configuration
GLIO_LANG = os.environ.get("GLIO_LANG", "tr")
is_english = (GLIO_LANG == "en")

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

MAIN_LOCALE = {
    "tr": {
        "title": "ARAŞTIRMA PDF RAPOR ÜRETİCİSİ v3.0",
        "json_not_found": "❌ JSON verisi bulunamadı: {}",
        "run_export": "Önce export_for_web.py çalıştırın.",
        "loading": "Veri yükleniyor: {}",
        "load_failed": "❌ Veri yüklenemedi: {}",
        "spots_empty": "❌ Spot verisi boş!",
        "zones_not_found": "Zone isimleri bulunamadı — spot zone anahtarlarından çıkarılıyor",
        "aggregating": "{:,} spot agregasyonu hesaplanıyor...",
        "agg_error": "❌ Agregasyon hatası: {}",
        "generating_pdf": "PDF dokümanı oluşturuluyor (2 sayfa)...",
        "page1_added": "  ✅ Sayfa 1 (Global Özet) eklendi",
        "page2_added": "  ✅ Sayfa 2 (Detay Analiz) eklendi",
        "pdf_error": "❌ PDF oluşturma hatası: {}",
        "pdf_success": "✅ Araştırma PDF Raporu hazırlandı: {}",
        "page_count": "   Sayfa sayısı  : 2",
        "spot_count": "   Spot sayısı   : {:,}",
        "pdf_title": "Glio-Cartography Araştırma Raporu v3.0",
        "pdf_author": "Glio-Cartography GNN v3.0",
        "pdf_subject": "Uzamsal Transkriptomik Analizi — RUO",
        "pdf_keywords": "Spatial, GNN, Tangram, Pathways, Zonal Contrast"
    },
    "en": {
        "title": "RESEARCH PDF REPORT GENERATOR v3.0",
        "json_not_found": "❌ JSON data not found: {}",
        "run_export": "Run export_for_web.py first.",
        "loading": "Loading data: {}",
        "load_failed": "❌ Failed to load data: {}",
        "spots_empty": "❌ Spot data is empty!",
        "zones_not_found": "Zone names not found — extracting from spot zone keys",
        "aggregating": "Calculating aggregation for {:,} spots...",
        "agg_error": "❌ Aggregation error: {}",
        "generating_pdf": "Generating PDF document (2 pages)...",
        "page1_added": "  ✅ Page 1 (Global Summary) added",
        "page2_added": "  ✅ Page 2 (Detailed Analysis) added",
        "pdf_error": "❌ PDF generation error: {}",
        "pdf_success": "✅ Research PDF Report generated: {}",
        "page_count": "   Page count   : 2",
        "spot_count": "   Spot count   : {:,}",
        "pdf_title": "Glio-Cartography Research Report v3.0",
        "pdf_author": "Glio-Cartography GNN v3.0",
        "pdf_subject": "Spatial Transcriptomics Analysis — RUO",
        "pdf_keywords": "Spatial, GNN, Tangram, Pathways, Zonal Contrast"
    }
}

main_loc = MAIN_LOCALE[GLIO_LANG]

# ============================================================
# VERİ YÜKLEME
# ============================================================

def load_data(json_path):
    """gzip veya düz JSON yükler."""
    if json_path.endswith('.gz'):
        with gzip.open(json_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
    else:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

    # Normalize pathway keys to fall back on core IDs if KEGG database is active
    PATHWAY_MAP = {
        'PI3K_AKT_mTOR': 'hsa04151',
        'MAPK_ERK': 'hsa04010',
        'JAK_STAT': 'hsa04630',
        'NFkB': 'hsa04064'
    }

    # 1. Normalize spots pathways
    for s in data.get('spots', []):
        spot_pathways = s.get('pathways', {})
        for core_k, kegg_k in PATHWAY_MAP.items():
            if kegg_k in spot_pathways:
                spot_pathways[core_k] = spot_pathways[kegg_k]

    # 2. Normalize zonal_contrast pathways
    zonal_contrast = data.get('zonal_contrast', {})
    if zonal_contrast and 'pathways' in zonal_contrast:
        for z in list(zonal_contrast['pathways'].keys()):
            for core_k, kegg_k in PATHWAY_MAP.items():
                if kegg_k in zonal_contrast['pathways'][z]:
                    zonal_contrast['pathways'][z][core_k] = zonal_contrast['pathways'][z][kegg_k]

    return data


# ============================================================
# VERİ AGREGASYONU
# ============================================================

def aggregate_data(spots, zone_names, zonal_contrast_data=None):
    """Tüm spotlardan global istatistikler üretir."""
    n_spots = len(spots)
    if n_spots == 0:
        raise ValueError("Veri boş — spot sayısı 0!")

    zone_counts  = {z: 0 for z in zone_names}
    myeloid_total = 0.0
    lr_totals    = {}
    
    # Pathway scoring totals
    pathways = ['PI3K_AKT_mTOR', 'MAPK_ERK', 'JAK_STAT', 'NFkB']
    pathway_totals = {p: 0.0 for p in pathways}

    for s in spots:
        # Dominant zon
        z_dict    = s.get('zones', {})
        if z_dict:
            best_zone = max(z_dict, key=z_dict.get)
            if best_zone in zone_counts:
                zone_counts[best_zone] += 1

        # Hücre tipleri
        ct = s.get('ct', {})
        myeloid_total += sum(
            float(v) for k, v in ct.items()
            if any(kw in k.lower() for kw in ('microglia', 'macrophage', 'myeloid', 'monocyte'))
        )

        # L-R sinyalleri
        for lr_key, val in s.get('lr', {}).items():
            lr_totals[lr_key] = lr_totals.get(lr_key, 0.0) + float(val)

        # Pathways
        spot_pathways = s.get('pathways', {})
        for p in pathways:
            pathway_totals[p] += float(spot_pathways.get(p, 0.0))

    # Yüzdeler
    zone_percs = {k: (v / n_spots) * 100 for k, v in zone_counts.items()}
    myeloid_avg = (myeloid_total / n_spots) * 100
    pathway_avgs = {p: v / n_spots for p, v in pathway_totals.items()}

    # Top L-R (ortalama aktivite)
    top_lr = sorted(
        [(k, v / n_spots) for k, v in lr_totals.items()],
        key=lambda x: x[1], reverse=True
    )[:4]

    # Zonal contrast processing (if not provided, calculate it)
    zonal_contrast = zonal_contrast_data
    if not zonal_contrast or not zonal_contrast.get('pathways'):
        zonal_contrast = {
            "pathways": {z: {p: 0.0 for p in pathways} for z in zone_names},
            "lr_pairs": {z: {lr: 0.0 for lr in lr_totals.keys()} for z in zone_names}
        }
        zone_sums = {z: 1e-8 for z in zone_names}
        for s in spots:
            z_dict = s.get('zones', {})
            for z, w in z_dict.items():
                zone_sums[z] = zone_sums.get(z, 0.0) + float(w)
                
            spot_pathways = s.get('pathways', {})
            lrs = s.get('lr', {})
            
            for z, w in z_dict.items():
                w = float(w)
                for p, v in spot_pathways.items():
                    if p in pathways:
                        zonal_contrast["pathways"][z][p] = zonal_contrast["pathways"][z].get(p, 0.0) + w * float(v)
                for lr, v in lrs.items():
                    zonal_contrast["lr_pairs"][z][lr] = zonal_contrast["lr_pairs"][z].get(lr, 0.0) + w * float(v)
                    
        for z in zone_names:
            zs = zone_sums.get(z, 1e-8)
            for p in zonal_contrast["pathways"][z]:
                zonal_contrast["pathways"][z][p] /= zs
            for lr in zonal_contrast["lr_pairs"][z]:
                zonal_contrast["lr_pairs"][z][lr] /= zs

    return {
        'n_spots':         n_spots,
        'zone_percs':      zone_percs,
        'myeloid_avg':     myeloid_avg,
        'top_lr':          top_lr,
        'pathway_avgs':    pathway_avgs,
        'zonal_contrast':  zonal_contrast,
    }


def draw_page1(fig, stats, zone_names, patient_label="HASTA A"):
    """Ana özet sayfası."""
    fig.patch.set_facecolor(COLORS['bg_dark'])
    gs = GridSpec(3, 2, figure=fig,
                  left=0.08, right=0.95,
                  top=0.88, bottom=0.12,
                  hspace=0.5, wspace=0.4)

    # ── Başlık ──────────────────────────────────────────────
    fig.text(0.5, 0.95,
             "GLIO-CARTOGRAPHY  |  RESEARCH ANALYSIS SUMMARY" if is_english else "GLIO-CARTOGRAPHY  |  ARAŞTIRMA ANALİZİ ÖZETİ",
             ha='center', va='top', fontsize=16, weight='bold',
             color=COLORS['accent'], fontfamily='monospace')

    analysis_lbl = f"Analysis: {stats['n_spots']:,} Visium Spots" if is_english else f"Analiz: {stats['n_spots']:,} Visium Spotu"
    fig.text(0.5, 0.915,
             f"{patient_label}  |  {stats['tissue_name']} research sample (diagnosis not inferred)  |  "
             f"{analysis_lbl}",
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
        fallback_txt = "Zone data\nnot found" if is_english else "Zon verisi\nbulunamadı"
        ax1.text(0.5, 0.5, fallback_txt,
                 ha='center', va='center', color='white', fontsize=10,
                 transform=ax1.transAxes)

    ax1.set_title("Tumor Architecture (GNN Zone)" if is_english else "Tümör Mimarisi (GNN Zon)", color='white',
                  fontsize=10, weight='bold', pad=8)

    # ── Panel 2: Tahmini hücre kompozisyonu ──────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.axis('off')
    ax2.set_facecolor(COLORS['bg_panel'])

    ax2.text(0.05, 0.95, "ESTIMATED CELL COMPOSITION" if is_english else "TAHMİNİ HÜCRE KOMPOZİSYONU",
             transform=ax2.transAxes, color=COLORS['accent'],
             fontsize=9, weight='bold', va='top')

    myeloid_lbl = "Myeloid (mean over spots)" if is_english else "Miyeloid (spotlar ortalaması)"
    ax2.text(0.05, 0.70, myeloid_lbl, transform=ax2.transAxes,
             color='#cccccc', fontsize=9)
    ax2.text(0.05, 0.55,
             f"{stats['myeloid_avg']:.1f}%" if is_english else f"%{stats['myeloid_avg']:.1f}",
             transform=ax2.transAxes, color='white',
             fontsize=14, weight='bold')

    ax2.add_patch(mpatches.FancyBboxPatch(
        (0.0, 0.0), 1.0, 1.0,
        boxstyle="round,pad=0.02",
        facecolor=COLORS['bg_panel'],
        edgecolor=COLORS['accent'], linewidth=1.5,
        transform=ax2.transAxes, clip_on=False
    ))

    # ── Panel 3: Downstream Yolak Aktivasyon Bar Chart ────────
    ax3 = fig.add_subplot(gs[1, :])
    ax3.set_facecolor(COLORS['bg_panel'])

    p_labels = list(stats['pathway_avgs'].keys())
    p_vals   = list(stats['pathway_avgs'].values())
    p_colors = [COLORS['accent'], '#F4A261', COLORS['tumor'], '#9f86c0']
    bars = ax3.barh(p_labels, p_vals,
                    color=p_colors[:len(p_labels)],
                    edgecolor=COLORS['bg_dark'], linewidth=0.5, height=0.5)

    ax3.set_xlabel("Mean Activity Score" if is_english else "Ortalama Aktivite Skoru", color='#cccccc', fontsize=9)
    ax3.set_title("Downstream Pathway Activation (Visium Mean)" if is_english else "Downstream Yolak Aktivasyonu (Visium Ortalama)",
                  color='white', fontsize=10, weight='bold', pad=8)
    ax3.tick_params(colors='white', labelsize=8)
    ax3.spines['bottom'].set_color('#444')
    ax3.spines['left'].set_color('#444')
    ax3.spines['top'].set_visible(False)
    ax3.spines['right'].set_visible(False)
    ax3.invert_yaxis()

    max_val = max(p_vals) if p_vals else 1
    for bar, val in zip(bars, p_vals):
        ax3.text(val + max_val * 0.01,
                 bar.get_y() + bar.get_height() / 2,
                 f"{val:.4f}",
                 va='center', color='white',
                 fontsize=8, weight='bold')

    # ── Panel 4: Analiz özeti ────────────────────────────────
    ax4 = fig.add_subplot(gs[2, 0])
    ax4.axis('off')
    ax4.set_facecolor(COLORS['bg_panel'])

    ax4.text(0.05, 0.95, "Run Summary" if is_english else "Analiz Özeti",
             transform=ax4.transAxes, color=COLORS['accent'],
             fontsize=10, weight='bold', va='top')
    ax4.text(0.05, 0.68,
             f"Spots: {stats['n_spots']:,}" if is_english else f"Spot sayısı: {stats['n_spots']:,}",
             transform=ax4.transAxes, color='white', fontsize=11, weight='bold')
    n_zones_present = sum(1 for v in stats['zone_percs'].values() if v > 0.5)
    ax4.text(0.05, 0.46,
             f"Zones detected (>0.5%): {n_zones_present}" if is_english else f"Saptanan zon (>%0,5): {n_zones_present}",
             transform=ax4.transAxes, color='#cccccc', fontsize=9)
    ax4.text(0.05, 0.14,
             "Exploratory research output" if is_english else "Keşifsel araştırma çıktısı",
             transform=ax4.transAxes, color='#888888', fontsize=7, style='italic')

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

    ax5.text(0.05, 0.95, "🧬  Dominant L-R Signaling Axes" if is_english else "🧬  Baskın L-R Sinyal Kanalları",
             transform=ax5.transAxes, color='#F4A261',
             fontsize=10, weight='bold', va='top')

    for i, (lr_key, avg_val) in enumerate(stats['top_lr']):
        y = 0.75 - i * 0.20
        ax5.text(0.05, y, f"• {lr_key}",
                 transform=ax5.transAxes, color='white', fontsize=9)
        
        act_lbl = f"  Mean Activity: {avg_val:.4f}" if is_english else f"  Ort. Aktivite: {avg_val:.4f}"
        ax5.text(0.05, y - 0.10,
                 act_lbl,
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
    disclaimer_text = (
        "⚠️  RESEARCH USE ONLY — No diagnosis, prognosis, survival estimate, prescription, or treatment recommendation.  |  Glio-Cartography GNN v3.0"
        if is_english else
        "⚠️  YALNIZCA ARAŞTIRMA — Tanı, prognoz, sağkalım tahmini, reçete veya tedavi önerisi üretmez.  |  Glio-Cartography GNN v3.0"
    )
    fig.text(
        0.5, 0.04,
        disclaimer_text,
        ha='center', va='center', fontsize=8,
        color=COLORS['warning'],
        bbox=dict(boxstyle='round,pad=0.4',
                  facecolor='#1a0a00',
                  edgecolor=COLORS['warning'],
                  alpha=0.85)
    )


# ============================================================
# SAYFA 2 — DETAY: ZON DAĞILIM TABLOSU + ZONAL KONTRAST
# ============================================================

def draw_page2(fig, stats, zone_names, patient_label="HASTA A"):
    """Detay sayfası — zon dağılım tablosu ve zonal kontrast analizi."""
    fig.patch.set_facecolor(COLORS['bg_dark'])
    gs = GridSpec(2, 1, figure=fig,
                  left=0.1, right=0.92,
                  top=0.88, bottom=0.12,
                  hspace=0.45)

    comp_title = f"GLIO-CARTOGRAPHY  |  Anatomical Comparison  |  {patient_label}" if is_english else f"GLIO-CARTOGRAPHY  |  Anatomik Karşılaştırma  |  {patient_label}"
    fig.text(0.5, 0.94,
             comp_title,
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
                       linewidth=0.5, width=0.4)
        ax1.set_xticks(range(len(zn_labels)))
        ax1.set_xticklabels(zn_labels, rotation=15, ha='right',
                             color='white', fontsize=8)
        ax1.set_ylabel("Proportion (%)" if is_english else "Oran (%)", color='#cccccc', fontsize=9)
        ax1.set_title("Anatomical Zone Distribution (GNN Predicted)" if is_english else "Anatomik Zon Dağılımı (GNN Tahmini)",
                      color='white', fontsize=11, weight='bold', pad=8)
        ax1.tick_params(colors='white')
        ax1.spines['bottom'].set_color('#444')
        ax1.spines['left'].set_color('#444')
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)

        for bar, val in zip(bars, zn_vals):
            label_format = f"{val:.1f}%" if is_english else f"%{val:.1f}"
            ax1.text(bar.get_x() + bar.get_width() / 2,
                     val + 0.3,
                     label_format,
                     ha='center', va='bottom',
                     color='white', fontsize=8, weight='bold')

    # ── Zonal Kontrast Yolak Bar Chart ───────────────────────
    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor(COLORS['bg_panel'])

    pathways = ['PI3K_AKT_mTOR', 'MAPK_ERK', 'JAK_STAT', 'NFkB']
    z_contr = stats.get('zonal_contrast', {})

    if z_contr and 'pathways' in z_contr:
        x = np.arange(len(pathways))
        width = 0.14
        
        valid_zone_names = [z for z in zone_names if stats['zone_percs'].get(z, 0) > 0]
        if not valid_zone_names:
            valid_zone_names = zone_names

        for i, zone in enumerate(valid_zone_names):
            z_vals = [z_contr.get('pathways', {}).get(zone, {}).get(p, 0.0) for p in pathways]
            offset = (i - len(valid_zone_names)/2.0 + 0.5) * width
            ax2.bar(x + offset, z_vals, width, label=zone, color=ZONE_COLORS[i % len(ZONE_COLORS)])

        ax2.set_xticks(x)
        ax2.set_xticklabels(pathways, color='white', fontsize=9)
        ax2.set_ylabel("Activation Score" if is_english else "Aktivasyon Skoru", color='#cccccc', fontsize=9)
        ax2.set_title("Zonal Pathway Contrast Analysis (Anatomical Comparison)" if is_english else "Zonal Yolak Kontrast Analizi (Anatomik Karşılaştırma)",
                      color='white', fontsize=11, weight='bold', pad=8)
        ax2.tick_params(colors='white')
        ax2.spines['bottom'].set_color('#444')
        ax2.spines['left'].set_color('#444')
        ax2.spines['top'].set_visible(False)
        ax2.spines['right'].set_visible(False)
        ax2.legend(facecolor='#1a1a2e', labelcolor='white', fontsize=7, loc='upper right')
    else:
        fallback_txt = "Zonal contrast data not found" if is_english else "Zonal kontrast verisi bulunamadı"
        ax2.text(0.5, 0.5, fallback_txt,
                 ha='center', va='center', color='white', fontsize=10)

    # Disclaimer
    disclaimer_text = (
        "⚠️  FOR RESEARCH USE ONLY (RUO)  |  Glio-Cartography GNN v3.0"
        if is_english else
        "⚠️  ARAŞTIRMA KULLANIMI İÇİN (RUO)  |  Glio-Cartography GNN v3.0"
    )
    fig.text(
        0.5, 0.04,
        disclaimer_text,
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
    """PDF raporu üretir. Başarıda True, herhangi bir hata durumunda False döner.

    Çağıranlar (server.py, stage5_report.py) dönüş değerini kontrol etmeden
    bu adımı "başarılı" saymamalı — bkz. denetim raporu bulgusu A-07.
    """
    logger.info("=" * 60)
    logger.info(main_loc["title"])
    logger.info("=" * 60)

    # Dosya kontrolü
    if not os.path.exists(JSON_PATH):
        logger.error(main_loc["json_not_found"].format(JSON_PATH))
        logger.error(main_loc["run_export"])
        return False

    # Veri yükle
    logger.info(main_loc["loading"].format(JSON_PATH))
    try:
        data = load_data(JSON_PATH)
    except Exception as e:
        logger.error(main_loc["load_failed"].format(e))
        return False

    spots      = data.get('spots', [])
    zone_names = data.get('metadata', {}).get('zones', [])
    zonal_contrast_data = data.get('zonal_contrast', {})

    if not spots:
        logger.error(main_loc["spots_empty"])
        return False
    if not zone_names:
        logger.warning(main_loc["zones_not_found"])
        zone_names = list(spots[0].get('zones', {}).keys()) if spots else []

    # Agregasyon
    logger.info(main_loc["aggregating"].format(len(spots)))
    try:
        stats = aggregate_data(spots, zone_names, zonal_contrast_data)
        stats['tissue_name'] = (data.get('metadata', {}).get('tissue_pack') or {}).get('name', 'Tissue')
    except ValueError as e:
        logger.error(main_loc["agg_error"].format(e))
        return False

    # Çıktı dizini
    out_dir = os.path.dirname(PDF_PATH) or "."
    os.makedirs(out_dir, exist_ok=True)

    # PDF oluştur
    logger.info(main_loc["generating_pdf"])
    plt.style.use('dark_background')

    try:
        with PdfPages(PDF_PATH) as pdf:

            # Sayfa 1 — Global Özet
            fig1 = plt.figure(figsize=(8.27, 11.69))  # A4
            draw_page1(fig1, stats, zone_names, patient_label=PATIENT_LABEL)
            pdf.savefig(fig1, facecolor=fig1.get_facecolor())
            plt.close(fig1)
            logger.info(main_loc["page1_added"])

            # Sayfa 2 — Detay Analiz
            fig2 = plt.figure(figsize=(8.27, 11.69))  # A4
            draw_page2(fig2, stats, zone_names, patient_label=PATIENT_LABEL)
            pdf.savefig(fig2, facecolor=fig2.get_facecolor())
            plt.close(fig2)
            logger.info(main_loc["page2_added"])

            # PDF Metadata
            d = pdf.infodict()
            d['Title']   = main_loc["pdf_title"]
            d['Author']  = main_loc["pdf_author"]
            d['Subject'] = main_loc["pdf_subject"]
            d['Keywords']= main_loc["pdf_keywords"]

    except Exception as e:
        logger.error(main_loc["pdf_error"].format(e))
        return False

    if not os.path.exists(PDF_PATH):
        logger.error(f"PDF dosyası beklenen konumda bulunamadı: {PDF_PATH}")
        return False

    logger.info("=" * 60)
    logger.info(main_loc["pdf_success"].format(PDF_PATH))
    logger.info(main_loc["page_count"])
    logger.info(main_loc["spot_count"].format(stats['n_spots']))
    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    _ok = main()
    sys.exit(0 if _ok else 1)
