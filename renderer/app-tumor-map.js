/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY — Tümör Mikroçevre Haritası (app-tumor-map.js)

   Bağımlılıklar:
     - state      (app-state.js → Proxy, handleStateChange hook eklendi)
     - showPanel  (app.js)

   Namespace  : window.GlioCarto.tumorMap
   Tetikleyici: handleStateChange içinde currentPanel === 'tumor-map'
   ══════════════════════════════════════════════════════════ */

/* global state, showPanel */
'use strict';

(function () {

  // ══════════════════════════════════════════════════════════════════════
  // NAMESPACE & EXPORTS & STATE GUARD
  // ══════════════════════════════════════════════════════════════════════
  window.GlioCarto = window.GlioCarto || {};
  window.GlioCarto.tumorMap = {
    draw: drawTumorMap
  };

  // Geriye dönük uyumluluk — eski window.drawTumorMap referansları için
  window.drawTumorMap = drawTumorMap;

  // Eşzamanlılık kilidi (Panel geçişleri ve yenilemelerin çakışmasını önler)
  let _isLoading = false;

  // ── Butonları bağla ───────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', _bindButtons);
  if (document.readyState !== 'loading') _bindButtons();

  function _bindButtons() {
    const exportBtn   = document.getElementById('btn-tumor-map-export');
    const refreshBtn  = document.getElementById('btn-tumor-map-refresh');
    if (exportBtn)  exportBtn.addEventListener('click', _exportSVG);
    if (refreshBtn) refreshBtn.addEventListener('click', drawTumorMap);

    // Dil değiştiğinde haritayı ve tabloları otomatik yeniden çiz
    window.addEventListener('i18n:langchange', () => {
      if (typeof state !== 'undefined' && state.currentPanel === 'tumor-map') {
        drawTumorMap();
      }
    });
  }

  function _exportSVG() {
    const svg = document.getElementById('tumor-map-svg');
    if (!svg) return;
    const data = new XMLSerializer().serializeToString(svg);
    const blob = new Blob([data], { type: 'image/svg+xml' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    const sampleId = (typeof state !== 'undefined' && state.gnnData && state.gnnData.sample_id)
      ? `_${state.gnnData.sample_id}` : '';
    a.download = `tumor-map${sampleId}_${ts}.svg`;
    a.click();
  }

  // ══════════════════════════════════════════════════════════════════════
  // ANA FONKSİYON — drawTumorMap()
  // ══════════════════════════════════════════════════════════════════════
  async function drawTumorMap() {
    if (_isLoading) return;
    _isLoading = true;

    try {
      const svg = document.getElementById('tumor-map-svg');
      if (!svg) return;

      let hasData = typeof state !== 'undefined' && state.gnnData &&
                      state.gnnData.spots && state.gnnData.spots.length > 0;

      const noData  = document.getElementById('tumor-map-no-data');
      const content = document.getElementById('tumor-map-content');

      // Otomatik yükleme asenkron tetikleyici
      if (!hasData && typeof state !== 'undefined' && state.outputDir) {
        const isTr = (window.i18n && window.i18n.lang === 'tr');
        if (noData) {
          const descEl = noData.querySelector('p:nth-of-type(2)');
          if (descEl) {
            descEl.textContent = isTr
              ? 'Analiz verisi arka planda yükleniyor, lütfen bekleyin...'
              : 'Analysis data is loading in the background, please wait...';
          }
        }
        try {
          if (typeof loadResults === 'function') {
            await loadResults();
            hasData = typeof state !== 'undefined' && state.gnnData &&
                      state.gnnData.spots && state.gnnData.spots.length > 0;
          }
        } catch (err) {
          console.error("Otomatik sonuç yükleme başarısız:", err);
        } finally {
          // Eski açıklamayı geri getir
          if (noData) {
            const descEl = noData.querySelector('p:nth-of-type(2)');
            if (descEl) {
              descEl.textContent = isTr
                ? 'Tümör mikroçevre haritası, pipeline analizi tamamlandıktan sonra gerçek veri ile dinamik olarak oluşturulacak.'
                : 'Tumor microenvironment map will be dynamically generated with real data after pipeline analysis is completed.';
            }
          }
        }
      }

      if (!hasData) {
        svg.replaceChildren();
        if (noData)  noData.style.display  = 'flex';
        if (content) content.style.display = 'none';
        return;
      }

      if (noData)  noData.style.display  = 'none';
      if (content) content.style.display = 'block';
      _drawFromData(svg, state.gnnData);
    } finally {
      _isLoading = false;
    }
  }



  // ── Gerçek veriyle çizim ──────────────────────────────────────────────
  function _drawFromData(svg, gnnData) {
    const ns = 'http://www.w3.org/2000/svg';
    const W = 900, H = 540;
    const spots = gnnData.spots || [];
    if (!spots.length) { drawTumorMap(); return; }

    // En boy oranını korumak için 2D bounding box normalizasyonu
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    spots.forEach(s => {
      const x = s.x ?? s.col ?? 0;
      const y = s.y ?? s.row ?? 0;
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
    });
    const rangeX = (maxX - minX) || 1;
    const rangeY = (maxY - minY) || 1;

    const padding = 50;
    const boxW = W - padding * 2;
    const boxH = H - padding * 2;

    // En boy oranını koruyan ölçek katsayısı
    const k = Math.min(boxW / rangeX, boxH / rangeY);
    const offsetX = padding + (boxW - rangeX * k) / 2;
    const offsetY = padding + (boxH - rangeY * k) / 2;

    const enriched = spots.map(s => {
      const x = s.x ?? s.col ?? 0;
      const y = s.y ?? s.row ?? 0;
      const px = offsetX + (x - minX) * k;
      const py = offsetY + (y - minY) * k;
      const nx = (x - minX) / rangeX;
      const ny = (y - minY) / rangeY;

      const type = _inferCellType(s);
      const region = _inferRegion(s, nx);

      return { px, py, nx, ny, type, region, raw: s };
    });

    const boundaries = _calculateDataDrivenBoundaries(enriched, W, H);
    _renderSVG(svg, ns, W, H, enriched, boundaries, gnnData);
    _updateStats(enriched, spots.length);
    _updateRecsTable(gnnData, enriched);
  }

  // ── GNN Tabanlı Bölge Sınıflandırması ─────────────────────────────────
  // [Kritik 1] Statik X eksenine dayanmak yerine spot.zones (dominant olasılık) kullanır.
  function _inferRegion(spot, nx) {
    if (spot && spot.zones) {
      let maxVal = -1;
      let domZone = '';
      for (const [zone, val] of Object.entries(spot.zones)) {
        if (val > maxVal) {
          maxVal = val;
          domZone = zone;
        }
      }
      if (domZone === 'Pseudopalisading Necrosis' || domZone === 'Cellular Tumor') {
        return 'core';
      } else if (domZone === 'Microvascular Proliferation' || domZone === 'Infiltrating Tumor') {
        return 'invasion';
      } else if (domZone === 'Leading Edge') {
        return 'healthy';
      }
    }
    // Fallback (e.g. coordinates only)
    return nx < 0.32 ? 'core' : nx < 0.58 ? 'invasion' : 'healthy';
  }

  // ── Hücre Tipi Sınıflandırma Yardımcısı ───────────────────────────────
  // [Kritik 2] 18+ alt tipi 9 ana fenotip sınıfına eşler.
  // [Kritik 1] tumor_associated_macrophage gibi adların hatalı olarak GBM olmasını
  // engellemek amacıyla TAM/Myeloid öncelikli olarak kontrol edilir.
  // Sınıflandırılamayan hücreler güvenli şekilde "Unknown" kategorisine alınır.
  function _classifyCellTypeName(name) {
    const ctName = (name || '').toLowerCase().trim();
    if (!ctName) return 'Unknown';

    // 1. TAM / Myeloid öncelikli (tumor_associated_macrophage "tumor" içerdiği için en üstte olmalı!)
    if (ctName.includes('macrophage') || ctName.includes('myeloid') || ctName.includes('tam')) {
      return 'TAM / Myeloid';
    }
    // 2. Microglia
    if (ctName.includes('microglia') || ctName.includes('microg')) {
      return 'Microglia';
    }
    // 3. T-cell / Lymphocyte / Treg
    if (ctName.includes('t_cell') || ctName.includes('t-cell') || ctName.includes('treg') || ctName.includes('lymph') || ctName.includes('cd4') || ctName.includes('cd8')) {
      return 'T-cell';
    }
    // 4. NK-cell
    if (ctName.includes('nk_cell') || ctName.includes('nk-cell') || ctName.includes('nk')) {
      return 'NK-cell';
    }
    // 5. Dendritic Cell (DC)
    if (ctName.includes('dc') || ctName.includes('dendritic') || ctName.includes('cdc') || ctName.includes('modc')) {
      return 'Dendritic Cell';
    }
    // 6. Oligodendrocyte
    if (ctName.includes('oligodendrocyte') || ctName.includes('oligo')) {
      return 'Oligodendrocyte';
    }
    // 7. Astrocyte
    if (ctName.includes('astrocyte') || ctName.includes('astro')) {
      return 'Astrocyte';
    }
    // 8. Vascular / Mural
    if (ctName.includes('endothelial') || ctName.includes('pericyte') || ctName.includes('mural') || ctName.includes('vascular') || ctName.includes('endo') || ctName.includes('peri')) {
      return 'Vascular / Mural';
    }
    // 9. GBM / Malignant (Bütün bağışıklık/myeloid spesifik hücreler elendikten sonra en son tumor)
    if (ctName.includes('gbm') || ctName.includes('malignant') || ctName.includes('tumor') || ctName.includes('glio')) {
      return 'GBM / Malignant';
    }

    return 'Unknown';
  }

  // ── GNN Hücre Tipi Çıkarımı ───────────────────────────────────────────
  function _inferCellType(spot) {
    if (spot.ct) {
      let maxFraction = -1;
      let domCt = '';
      for (const [ct, fraction] of Object.entries(spot.ct)) {
        if (fraction > maxFraction) {
          maxFraction = fraction;
          domCt = ct;
        }
      }

      if (domCt && maxFraction > 0.01) {
        return _classifyCellTypeName(domCt);
      }
    }

    // Fallback standard fields
    const ct = spot.cell_type || spot.cellType || spot.deconv_type || '';
    return _classifyCellTypeName(ct);
  }

  // ── Veri Güdümlü Dinamik Sınır Hesaplama (Fraktal Jitter — 10 Level) ──
  // 10 seviye + deterministik sinüs jitter → organik, lobüler tümör sınırları
  function _calculateDataDrivenBoundaries(enriched, W, H) {
    const numLevels = 10;
    const pointsCore = [];
    const pointsInv = [];

    let minSpotX = Infinity;
    let maxSpotX = -Infinity;
    enriched.forEach(s => {
      if (s.px < minSpotX) minSpotX = s.px;
      if (s.px > maxSpotX) maxSpotX = s.px;
    });
    if (minSpotX === Infinity) { minSpotX = 50; maxSpotX = W - 50; }
    const tissueWidth = maxSpotX - minSpotX;

    let lastCoreX = null;
    let lastInvX  = null;

    for (let j = 0; j < numLevels; j++) {
      const levelY = (j / (numLevels - 1)) * H;
      const windowHeight = 1.3 * (H / (numLevels - 1));
      const levelSpots = enriched.filter(s => Math.abs(s.py - levelY) <= windowHeight);

      let localCoreX = null;
      let localInvX  = null;

      if (levelSpots.length > 0) {
        const coreSpots = levelSpots.filter(s => s.region === 'core');
        const invSpots  = levelSpots.filter(s => s.region === 'invasion');

        if (coreSpots.length > 0) {
          const sortedCore = coreSpots.map(s => s.px).sort((a, b) => a - b);
          const idx = Math.min(Math.floor(sortedCore.length * 0.9), sortedCore.length - 1);
          localCoreX = sortedCore[idx];
        }
        if (invSpots.length > 0) {
          const sortedInv = invSpots.map(s => s.px).sort((a, b) => a - b);
          const idx = Math.min(Math.floor(sortedInv.length * 0.9), sortedInv.length - 1);
          localInvX = sortedInv[idx];
        }
      }

      if (localCoreX === null) localCoreX = (lastCoreX !== null) ? lastCoreX : (minSpotX + 0.30 * tissueWidth);
      if (localInvX  === null) localInvX  = (lastInvX  !== null) ? lastInvX  : (localCoreX + 0.10 * tissueWidth);

      // Deterministik fraktal jitter — GBM tümör sınırlarının pürüzlü/lobüler yapısını simüle eder
      const jCore = Math.sin(j * 2.31 + 1.13) * 0.038 * W;
      const jInv  = Math.sin(j * 1.77 + 3.51) * 0.028 * W;
      localCoreX += jCore;
      localInvX  += jInv;

      localCoreX = Math.max(minSpotX + 0.05 * tissueWidth, Math.min(localCoreX, maxSpotX - 0.15 * tissueWidth));
      localInvX  = Math.max(localCoreX + 0.08 * W, Math.min(localInvX, maxSpotX - 0.05 * tissueWidth));

      lastCoreX = localCoreX;
      lastInvX  = localInvX;

      pointsCore.push({ x: localCoreX, y: levelY });
      pointsInv.push({ x: localInvX, y: levelY });
    }

    function makeSmoothPath(points) {
      let d = `M ${points[0].x},0`;
      for (let i = 1; i < points.length; i++) {
        const pPrev = points[i - 1];
        const pCurr = points[i];
        const cy1 = (pPrev.y + pCurr.y) / 2;
        const cy2 = cy1;
        d += ` C ${pPrev.x},${cy1} ${pCurr.x},${cy2} ${pCurr.x},${pCurr.y}`;
      }
      return d;
    }

    const corePathD = makeSmoothPath(pointsCore);
    const invPathD  = makeSmoothPath(pointsInv);

    // Sağlıklı doku sınırı
    const pointsHlt = pointsInv.map(p => ({ x: Math.min(p.x * 1.35, W * 0.92), y: p.y }));
    const hltPathD  = makeSmoothPath(pointsHlt);

    // Poligon alanlarını kapat
    const corePolyD = corePathD + ` L 0,${H} L 0,0 Z`;

    let invPolyD = invPathD;
    invPolyD += ` L ${pointsCore[pointsCore.length - 1].x},${H}`;
    for (let i = pointsCore.length - 1; i > 0; i--) {
      const pPrev = pointsCore[i];
      const pCurr = pointsCore[i - 1];
      const cy1 = (pPrev.y + pCurr.y) / 2;
      const cy2 = cy1;
      invPolyD += ` C ${pPrev.x},${cy1} ${pCurr.x},${cy2} ${pCurr.x},${pCurr.y}`;
    }
    invPolyD += ` L ${pointsInv[0].x},0 Z`;

    return {
      corePathD,
      invPathD,
      hltPathD,
      corePolyD,
      invPolyD,
      pointsCore,
      pointsInv,
      pointsHlt
    };
  }

  // ══════════════════════════════════════════════════════════════════════
  // SVG ÇİZİM MOTORU (Renk Körlüğü Dostu, Interaktif ve getBBox Destekli)
  // ══════════════════════════════════════════════════════════════════════
  function _renderSVG(svg, ns, W, H, spots, bounds, gnnData) {
    svg.replaceChildren();

    // Erişilebilirlik
    const isTr = (window.i18n && window.i18n.lang === 'tr');
    const titleEl = document.createElementNS(ns, 'title');
    titleEl.textContent = isTr 
      ? 'Tümör Mikroçevre Haritası — Gerçek Analiz Verisi' 
      : 'Tumor Microenvironment Map — Real Analysis Data';
    svg.appendChild(titleEl);
    svg.setAttribute('aria-label', titleEl.textContent);
    svg.setAttribute('role', 'img');

    function el(tag, attrs, parent) {
      const e = document.createElementNS(ns, tag);
      Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
      if (parent) parent.appendChild(e);
      return e;
    }

    const { corePathD, invPathD, hltPathD, corePolyD, invPolyD, pointsCore, pointsInv, pointsHlt } = bounds;

    // ── Defs ─────────────────────────────────────────────────────────────
    const defs = el('defs', {}, svg);

    // H&E histoloji doku dokusu
    const fTex = el('filter', {
      id: 'tm-tex', x: '0%', y: '0%', width: '100%', height: '100%',
      'color-interpolation-filters': 'sRGB'
    }, defs);
    el('feTurbulence', { type: 'fractalNoise', baseFrequency: '1.5 1.0', numOctaves: '4', seed: '19', result: 'n' }, fTex);
    el('feColorMatrix', {
      type: 'matrix',
      values: '0.38 0 0 0 0.08  0.08 0.12 0 0 0.01  0.28 0 0.15 0 0.05  0 0 0 0.13 0',
      in: 'n', result: 'c'
    }, fTex);
    el('feBlend', { in: 'SourceGraphic', in2: 'c', mode: 'multiply' }, fTex);

    const fGlow = el('filter', { id: 'tm-glow', x: '-30%', y: '-30%', width: '160%', height: '160%' }, defs);
    el('feGaussianBlur', { stdDeviation: '2.8', result: 'b' }, fGlow);
    const fm = el('feMerge', {}, fGlow);
    el('feMergeNode', { in: 'b' }, fm);
    el('feMergeNode', { in: 'SourceGraphic' }, fm);

    // Nekrotik alan yumuşatma filtresi
    const fNekro = el('filter', { id: 'tm-nekro-blur', x: '-40%', y: '-40%', width: '180%', height: '180%' }, defs);
    el('feGaussianBlur', { stdDeviation: '10' }, fNekro);


    function mkArrow(id, clr) {
      const m = el('marker', { id, markerWidth: '7', markerHeight: '7', refX: '5', refY: '3.5', orient: 'auto' }, defs);
      el('path', { d: 'M0,0 L0,7 L7,3.5 z', fill: clr }, m);
    }
    mkArrow('tm-arr-red',  'hsl(12,90%,60%)');
    mkArrow('tm-arr-gray', '#7a7a9d');

    function lg(id, stops) {
      const g = el('linearGradient', { id, x1: '0%', y1: '0%', x2: '100%', y2: '0%' }, defs);
      stops.forEach(([o, c]) => el('stop', { offset: o, 'stop-color': c }, g));
    }
    // H&E renkleri: koyu mor-gri çekirdek / muted pembe infiltrasyon / sıcak bej sağlıklı beyin
    lg('tm-gCore',     [['0%', 'hsl(248, 35%, 10%)'], ['100%', 'hsl(252, 28%, 18%)']]);
    lg('tm-gInvasion', [['0%', 'hsl(330, 22%, 26%)'], ['100%', 'hsl(335, 18%, 42%)']]);
    lg('tm-gHealthy',  [['0%', 'hsl(35,  24%, 60%)'], ['100%', 'hsl(30,  20%, 74%)']]);

    // Zemin
    el('rect', { x: 0, y: 0, width: W, height: H, fill: 'url(#tm-gHealthy)' }, svg);

    // Organik Bolge Sekilleri
    el('path', { d: corePolyD, fill: 'url(#tm-gCore)', filter: 'url(#tm-tex)' }, svg);
    el('path', { d: invPolyD, fill: 'url(#tm-gInvasion)', opacity: '0.84', filter: 'url(#tm-tex)' }, svg);
    el('rect', { x: 0, y: 0, width: W, height: H, fill: 'transparent', filter: 'url(#tm-tex)', opacity: '0.42' }, svg);

    // Kapiller / Mikro-Damar Network
    // Translucent kirmizi kapiller cizgiler - gercek beyin doku kesitlerindeki vaskuler agi yansitir
    {
      const vascularSpots = spots.filter(s => s.type === 'Vascular / Mural');
      const sourceSpots = vascularSpots.length >= 3 ? vascularSpots : spots.filter(s => s.type !== 'Unknown');
      
      let _cs = 23;
      const crng = () => { _cs = Math.sin(_cs + 1.732) * 99991; return Math.abs(_cs - Math.floor(_cs)); };

      if (sourceSpots.length > 2) {
        // Find close neighbors to draw interconnected capillary networks
        const findCloseNeighbor = (fromSpot, candidates, minDist, maxDist) => {
          let best = null;
          let bestDist = Infinity;
          const sampleSize = Math.min(40, candidates.length);
          const startIdx = Math.floor(crng() * candidates.length);
          for (let i = 0; i < sampleSize; i++) {
            const candidate = candidates[(startIdx + i) % candidates.length];
            if (candidate === fromSpot) continue;
            const dx = candidate.px - fromSpot.px;
            const dy = candidate.py - fromSpot.py;
            const d = Math.sqrt(dx*dx + dy*dy);
            if (d >= minDist && d <= maxDist && d < bestDist) {
              best = candidate;
              bestDist = d;
            }
          }
          return best;
        };

        // Draw 10 capillary trees that branch and flow along the tissue spots
        for (let tree = 0; tree < 10; tree++) {
          let current = sourceSpots[Math.floor(crng() * sourceSpots.length)];
          if (!current) continue;

          let pathD = `M ${current.px.toFixed(1)},${current.py.toFixed(1)}`;
          let temp = current;
          let segments = 2 + Math.floor(crng() * 3); // 2 to 4 segments

          for (let seg = 0; seg < segments; seg++) {
            const next = findCloseNeighbor(temp, sourceSpots, 25, 95);
            if (!next) break;

            const midX = (temp.px + next.px) / 2;
            const midY = (temp.py + next.py) / 2;
            const jitterX = (crng() - 0.5) * 30;
            const jitterY = (crng() - 0.5) * 30;

            pathD += ` Q ${(midX + jitterX).toFixed(1)},${(midY + jitterY).toFixed(1)} ${next.px.toFixed(1)},${next.py.toFixed(1)}`;
            temp = next;
          }

          const opacity = (0.09 + crng() * 0.11).toFixed(2);
          const sw      = (0.8 + crng() * 1.4).toFixed(1);
          el('path', {
            d: pathD,
            fill: 'none', stroke: 'hsl(356, 68%, 38%)',
            'stroke-width': sw, opacity, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'
          }, svg);
        }
      }
    }

    // Nekrotik Alan (Psodopalizat Nekroz - Tumor Cekirdegi Merkezi)
    // Gercek GBM histolojisinde tumor cekirdeginin merkezinde nekrotik alan gorulur
    const coreSpots = spots.filter(s => s.region === 'core');
    let nekroCX = W * 0.22;
    let nekroCY = H * 0.50;
    let nekroRx = 40;
    let nekroRy = 30;

    if (coreSpots.length > 0) {
      nekroCX = coreSpots.reduce((sum, s) => sum + s.px, 0) / coreSpots.length;
      nekroCY = coreSpots.reduce((sum, s) => sum + s.py, 0) / coreSpots.length;
      const xs = coreSpots.map(s => s.px);
      const ys = coreSpots.map(s => s.py);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      nekroRx = Math.max(30, (maxX - minX) * 0.20);
      nekroRy = Math.max(25, (maxY - minY) * 0.18);
    }

    el('ellipse', {
      cx: nekroCX.toFixed(1), cy: nekroCY.toFixed(1),
      rx: nekroRx.toFixed(1), ry: nekroRy.toFixed(1),
      fill: 'hsl(230, 18%, 7%)', opacity: '0.72',
      filter: 'url(#tm-nekro-blur)'
    }, svg);
    el('ellipse', {
      cx: nekroCX.toFixed(1), cy: nekroCY.toFixed(1),
      rx: (nekroRx * 1.10).toFixed(1), ry: (nekroRy * 1.10).toFixed(1),
      fill: 'none', stroke: 'hsl(260, 26%, 30%)', 'stroke-width': '1.5', opacity: '0.40'
    }, svg);

    // Sinir Cizgileri (H&E uyumlu)
    el('path', { d: corePathD, fill: 'none', stroke: 'hsl(255, 48%, 42%)', 'stroke-width': '3', 'stroke-linecap': 'round' }, svg);
    el('path', { d: invPathD, fill: 'none', stroke: 'hsl(340, 42%, 54%)', 'stroke-width': '2', 'stroke-dasharray': '10,5', 'stroke-linecap': 'round' }, svg);
    el('path', { d: hltPathD, fill: 'none', stroke: 'hsl(34, 38%, 46%)', 'stroke-width': '1.5', 'stroke-dasharray': '7,6', 'stroke-linecap': 'round' }, svg);

    // H&E Histoloji Benzeri Renk Paleti
    // Hematoxylin-Eosin boyamasina yakin, renk korldugu test edilmis tonlar
    const CELL_COLORS = {
      'GBM / Malignant':  'hsl(252, 52%, 44%)',
      'T-cell':           'hsl(208, 68%, 50%)',
      'NK-cell':          'hsl(186, 60%, 44%)',
      'TAM / Myeloid':    'hsl(34,  62%, 52%)',
      'Microglia':        'hsl(222, 38%, 56%)',
      'Dendritic Cell':   'hsl(168, 50%, 42%)',
      'Oligodendrocyte':  'hsl(278, 44%, 54%)',
      'Astrocyte':        'hsl(350, 48%, 60%)',
      'Vascular / Mural': 'hsl(356, 65%, 40%)',
      'Unknown':          'hsl(0,   0%,  60%)',
    };




    // ── Interaktif Tooltip Hazırla ────────────────────────────────────────
    let tooltip = document.getElementById('tumor-map-tooltip');
    if (!tooltip) {
      tooltip = document.createElement('div');
      tooltip.id = 'tumor-map-tooltip';
      tooltip.className = 'spot-tooltip hidden';
      tooltip.style.position = 'absolute';
      tooltip.style.pointerEvents = 'none';
      tooltip.style.zIndex = '1000';
      tooltip.style.background = 'rgba(10, 15, 30, 0.95)';
      tooltip.style.border = '1px solid hsl(220, 20%, 25%)';
      tooltip.style.padding = '8px 12px';
      tooltip.style.borderRadius = '6px';
      tooltip.style.fontSize = '0.78rem';
      tooltip.style.color = '#fff';
      tooltip.style.boxShadow = '0 6px 16px rgba(0,0,0,0.6)';
      tooltip.style.backdropFilter = 'blur(4px)';
      const p = document.getElementById('panel-tumor-map');
      if (p) p.appendChild(tooltip);
    }

    // ── Spot / Hücre Noktaları ────────────────────────────────────────────
    // Expression-scaled spot boyutu: dominant CT skoru veya expression alanına göre yarıçap değişir
    function _spotRadius(spot, base) {
      let score = 0.5;
      if (spot.raw) {
        if (typeof spot.raw.expression === 'number') {
          score = Math.min(1, Math.max(0, spot.raw.expression));
        } else if (spot.raw.ct && typeof spot.raw.ct === 'object') {
          const vals = Object.values(spot.raw.ct);
          if (vals.length) score = Math.min(1, Math.max(...vals) * 1.6);
        }
      }
      return Math.max(2.0, Math.min(6.5, base * (0.62 + 0.72 * score)));
    }

    // Nekrotik bölgedeki spot seyreltme seed'i (deterministik)
    let _nsk = 5;
    const nekroRng = () => { _nsk = Math.sin(_nsk + 2.71) * 99991; return Math.abs(_nsk - Math.floor(_nsk)); };

    spots.forEach(s => {
      const px = s.px;
      const py = s.py;

      // Nekrotik alan içindeki spotları %78 ihtimalle atla (seyrek görünüm = gerçek nekroz)
      const dxN = px - nekroCX;
      const dyN = py - nekroCY;
      if ((dxN * dxN) / (nekroRx * nekroRx) + (dyN * dyN) / (nekroRy * nekroRy) < 1.0) {
        if (nekroRng() < 0.78) return;
      }

      const clr = CELL_COLORS[s.type] || '#888';
      const useGlow = s.type === 'GBM / Malignant';

      let shapeEl;

      switch (s.type) {
        case 'Microglia': {
          const sz = _spotRadius(s, 5.2);
          const pts = `${px},${py - sz} ${px - sz * 0.87},${py + sz * 0.5} ${px + sz * 0.87},${py + sz * 0.5}`;
          shapeEl = el('polygon', { points: pts, fill: clr, opacity: '0.88', cursor: 'pointer' }, svg);
          break;
        }
        case 'Astrocyte': {
          const sz = _spotRadius(s, 3.8);
          shapeEl = el('rect', {
            x: (px - sz).toFixed(1), y: (py - sz).toFixed(1),
            width: (sz * 2).toFixed(1), height: (sz * 2).toFixed(1),
            fill: clr, opacity: '0.82', cursor: 'pointer'
          }, svg);
          break;
        }
        case 'Vascular / Mural': {
          const sz = _spotRadius(s, 4.0);
          const pts = `${px},${py - sz} ${px + sz},${py} ${px},${py + sz} ${px - sz},${py}`;
          shapeEl = el('polygon', { points: pts, fill: clr, opacity: '0.88', cursor: 'pointer' }, svg);
          break;
        }
        case 'Unknown':
          shapeEl = el('circle', {
            cx: px.toFixed(1), cy: py.toFixed(1),
            r: '2.2', fill: clr, opacity: '0.35', cursor: 'pointer'
          }, svg);
          break;
        default: {
          const r = _spotRadius(s, s.type === 'GBM / Malignant' ? 4.0 : 3.4);
          shapeEl = el('circle', {
            cx: px.toFixed(1), cy: py.toFixed(1),
            r: r.toFixed(1),
            fill: clr, opacity: '0.90', cursor: 'pointer',
            ...(useGlow ? { filter: 'url(#tm-glow)' } : {})
          }, svg);
        }
      }

      // Interaktivite (Hover Tooltip)
      if (shapeEl) {
        shapeEl.addEventListener('mouseenter', (evt) => {
          tooltip.classList.remove('hidden');
          
          let ctHtml = '';
          if (s.raw && s.raw.ct) {
            const sortedCt = Object.entries(s.raw.ct)
              .filter(([_, val]) => val > 0.01)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3);
            if (sortedCt.length > 0) {
              ctHtml = `<div style="margin-top:6px; padding-top:4px; border-top:1px solid rgba(255,255,255,0.1); opacity:0.8; font-size:0.72rem;">` + 
                sortedCt.map(([name, val]) => `• ${name.replace(/_/g, ' ')}: ${(val*100).toFixed(1)}%`).join('<br>') +
                '</div>';
            }
          }

          const isTr = (window.i18n && window.i18n.lang === 'tr');
          const cellNames = {
            'GBM / Malignant':   isTr ? 'GBM / Malign Hücre' : 'GBM / Malignant Cell',
            'T-cell':            isTr ? 'T-Hücresi' : 'T-Cell',
            'NK-cell':           isTr ? 'NK Hücresi' : 'NK Cell',
            'TAM / Myeloid':     isTr ? 'TAM / Myeloid Hücre' : 'TAM / Myeloid Cell',
            'Microglia':         isTr ? 'Mikroglia' : 'Microglia',
            'Dendritic Cell':    isTr ? 'Dendritik Hücre' : 'Dendritic Cell',
            'Oligodendrocyte':   isTr ? 'Oligodendrosit' : 'Oligodendrocyte',
            'Astrocyte':         isTr ? 'Astrosit' : 'Astrocyte',
            'Vascular / Mural':  isTr ? 'Vasküler / Mural Hücre' : 'Vascular / Mural Cell',
            'Unknown':           isTr ? 'Belirsiz / Bilinmeyen' : 'Unknown / Unclassified'
          };
          const displayType = cellNames[s.type] || s.type;

          let segTitle, segVal;
          if (isTr) {
            segTitle = 'Segmentasyon (GNN)';
            segVal = s.region === 'core' ? 'Tümör Çekirdeği' : s.region === 'invasion' ? 'İstilacı Sınır' : 'Sağlıklı Doku';
          } else {
            segTitle = 'Segmentation (GNN)';
            segVal = s.region === 'core' ? 'Tumor Core' : s.region === 'invasion' ? 'Invasive Border' : 'Healthy Tissue';
          }

          const zoneInfo = s.raw && s.raw.zones ? `<br><strong>${segTitle}:</strong> ${segVal}` : '';

          tooltip.innerHTML = `
            <strong>${isTr ? 'Fenotip' : 'Phenotype'}:</strong> ${displayType}<br>
            <strong>${isTr ? 'Konum' : 'Position'}:</strong> X: ${Math.round(s.px)}, Y: ${Math.round(s.py)}
            ${zoneInfo}
            ${ctHtml}
          `;
        });

        shapeEl.addEventListener('mousemove', (evt) => {
          const parentRect = svg.parentElement.getBoundingClientRect();
          const x = evt.clientX - parentRect.left + 15;
          const y = evt.clientY - parentRect.top + 15;
          tooltip.style.left = `${x}px`;
          tooltip.style.top = `${y}px`;
        });

        shapeEl.addEventListener('mouseleave', () => {
          tooltip.classList.add('hidden');
        });
      }
    });








    // ── Etiket fonksiyonları — getBBox ile dinamik boyutlandırma ──────────
    function pill(x, y, txt, bg, fg = '#fff', fs = 11) {
      const g = el('g', { transform: `translate(${x},${y})` }, svg);
      const PAD = 10;
      const rect = el('rect', { x: '0', y: '-12', width: '60', height: '22', rx: '5', fill: bg, opacity: '0.90' }, g);
      const t = el('text', {
        x: '0', y: '5', fill: fg,
        'font-size': String(fs), 'font-family': 'Inter, system-ui, sans-serif',
        'font-weight': '600', 'text-anchor': 'middle'
      }, g);
      t.textContent = txt;
      try {
        const bw = t.getBBox().width;
        const rw = bw + PAD * 2;
        rect.setAttribute('x',     String(-(rw / 2)));
        rect.setAttribute('width', String(rw));
      } catch (_) { }
    }

    function sigLabel(x, y, txt, clr) {
      const g = el('g', { transform: `translate(${x},${y})` }, svg);
      const PAD = 8;
      const rect = el('rect', { x: '0', y: '-8', width: '80', height: '18', rx: '3', fill: 'hsl(222,30%,8%)', opacity: '0.80' }, g);
      const t = el('text', {
        x: '0', y: '5', fill: clr,
        'font-size': '10', 'font-family': 'Inter, system-ui, sans-serif',
        'font-weight': '700', 'text-anchor': 'start'
      }, g);
      t.textContent = txt;
      try {
        const bw = t.getBBox().width;
        rect.setAttribute('width', String(bw + PAD * 2));
        t.setAttribute('x', String(PAD));
      } catch (_) { }
    }

    // Bölge etiketleri için konumları veri centroidlerine göre dinamik hesapla
    const coreSpotsForLabels = spots.filter(s => s.region === 'core');
    const invSpotsForLabels  = spots.filter(s => s.region === 'invasion');
    const hltSpotsForLabels  = spots.filter(s => s.region === 'healthy');

    let lblCoreX = W * 0.20, lblCoreY = H * 0.20;
    let lblInvX  = W * 0.50, lblInvY  = H * 0.15;
    let lblHltX  = W * 0.80, lblHltY  = H * 0.12;

    if (coreSpotsForLabels.length > 0) {
      lblCoreX = coreSpotsForLabels.reduce((sum, s) => sum + s.px, 0) / coreSpotsForLabels.length;
      const avgY = coreSpotsForLabels.reduce((sum, s) => sum + s.py, 0) / coreSpotsForLabels.length;
      lblCoreY = Math.min(H * 0.82, Math.max(H * 0.12, avgY - 45));
    }
    if (invSpotsForLabels.length > 0) {
      lblInvX = invSpotsForLabels.reduce((sum, s) => sum + s.px, 0) / invSpotsForLabels.length;
      const avgY = invSpotsForLabels.reduce((sum, s) => sum + s.py, 0) / invSpotsForLabels.length;
      lblInvY = Math.min(H * 0.82, Math.max(H * 0.12, avgY - 45));
    }
    if (hltSpotsForLabels.length > 0) {
      lblHltX = hltSpotsForLabels.reduce((sum, s) => sum + s.px, 0) / hltSpotsForLabels.length;
      const avgY = hltSpotsForLabels.reduce((sum, s) => sum + s.py, 0) / hltSpotsForLabels.length;
      lblHltY = Math.min(H * 0.82, Math.max(H * 0.12, avgY - 45));
    }

    pill(lblCoreX, lblCoreY, 'Tümör Çekirdeği', 'hsl(265,55%,22%)');
    pill(lblInvX, lblInvY, 'İstilacı Bölge', 'hsl(330,45%,35%)');
    pill(lblHltX, lblHltY, 'Sağlıklı Doku', 'hsl(145,50%,25%)');

    // Helper: Fine-grained hücre adını görsel sınıfına eşleştir
    function mapFineGrainedToBroad(name) {
      return _classifyCellTypeName(name);
    }

    // [Dinamik 1] En aktif 2 Ligand-Reseptör çiftini bul ve çiz
    let topPairs = [];
    if (gnnData && gnnData.cell_cell_communication) {
      const pairList = [];
      for (const [pair, cellComm] of Object.entries(gnnData.cell_cell_communication)) {
        let sum = 0;
        for (const val of Object.values(cellComm)) {
          sum += val;
        }
        pairList.push({ pair, sum, cellComm });
      }
      pairList.sort((a, b) => b.sum - a.sum);
      topPairs = pairList.slice(0, 2);
    }

    // Fallback pairs for demo mode or empty cases
    if (topPairs.length === 0) {
      topPairs = [
        {
          pair: 'PTN-PTPRZ1',
          cellComm: { 'astrocyte->gbm_stem_cell': 100 }
        },
        {
          pair: 'SPP1-CD44',
          cellComm: { 'tumor_associated_macrophage->malignant_tumor': 80 }
        }
      ];
    }

    const midIdx = Math.floor(pointsCore.length / 2);

    topPairs.forEach((pInfo, idx) => {
      const lastHyphen = pInfo.pair.lastIndexOf('-');
      const pairName = lastHyphen !== -1
        ? pInfo.pair.substring(0, lastHyphen) + ' → ' + pInfo.pair.substring(lastHyphen + 1)
        : pInfo.pair;
      
      // En güçlü iletişim kuran hücre çiftini bul
      let maxScore = -1;
      let bestCellPair = '';
      for (const [cellPair, score] of Object.entries(pInfo.cellComm)) {
        if (score > maxScore) {
          maxScore = score;
          bestCellPair = cellPair;
        }
      }

      let drawArrow = false;
      let startPt = null;
      let endPt = null;

      if (bestCellPair) {
        const parts = bestCellPair.split('->');
        const senderBroad = mapFineGrainedToBroad(parts[0]);
        const receiverBroad = mapFineGrainedToBroad(parts[1]);

        // Hücre tiplerinin dokudaki merkezlerini bul (centroid)
        const senders = spots.filter(s => s.type === senderBroad);
        const receivers = spots.filter(s => s.type === receiverBroad);

        if (senders.length > 0 && receivers.length > 0) {
          const sX = senders.reduce((sum, s) => sum + s.px, 0) / senders.length;
          const sY = senders.reduce((sum, s) => sum + s.py, 0) / senders.length;
          const rX = receivers.reduce((sum, s) => sum + s.px, 0) / receivers.length;
          const rY = receivers.reduce((sum, s) => sum + s.py, 0) / receivers.length;
          
          startPt = { x: sX, y: sY };
          endPt = { x: rX, y: rY };
          drawArrow = true;
        }
      }

      // Merkez hesaplanamazsa organik yerleşime düş (Fallback)
      if (!drawArrow) {
        const fallbackX = pointsCore[midIdx].x * 0.7;
        if (idx === 0) {
          startPt = { x: fallbackX, y: H * 0.35 };
          endPt = { x: fallbackX + 110, y: H * 0.38 };
        } else {
          startPt = { x: fallbackX * 0.6, y: H * 0.60 };
          endPt = { x: fallbackX, y: H * 0.58 };
        }
      }

      const dx = endPt.x - startPt.x;
      const dy = endPt.y - startPt.y;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      
      // Organik yay/kıvrım kontrol noktası
      const mx = (startPt.x + endPt.x) / 2;
      const my = (startPt.y + endPt.y) / 2;
      const orthX = -dy / len;
      const orthY = dx / len;
      const offsetAmt = idx === 0 ? -30 : 30;
      const ctrlX = mx + orthX * offsetAmt;
      const ctrlY = my + orthY * offsetAmt;

      // Ok ucunu merkezin biraz gerisinde bitir
      const shortenAmt = 16;
      const endX_short = endPt.x - (dx / len) * shortenAmt;
      const endY_short = endPt.y - (dy / len) * shortenAmt;

      const pathD = `M ${startPt.x},${startPt.y} Q ${ctrlX},${ctrlY} ${endX_short},${endY_short}`;
      
      const arrowColor = idx === 0 ? 'hsl(12, 90%, 60%)' : 'hsl(215, 60%, 65%)';
      const markerId = idx === 0 ? 'tm-arr-red' : 'tm-arr-gray';

      el('path', {
        d: pathD,
        fill: 'none',
        stroke: arrowColor,
        'stroke-width': idx === 0 ? '2.4' : '1.8',
        'marker-end': `url(#${markerId})`,
        ...(idx === 0 ? { filter: 'url(#tm-glow)' } : {})
      }, svg);

      // Etiketi yay ortasına yerleştir
      const lblX = 0.25 * startPt.x + 0.5 * ctrlX + 0.25 * endPt.x;
      const lblY = 0.25 * startPt.y + 0.5 * ctrlY + 0.25 * endPt.y - 12;

      sigLabel(lblX - 35, lblY, pairName, idx === 0 ? 'hsl(12,90%,75%)' : '#cce');
    });




    // ── Dinamik Reseptör Kalkanı ──────────────────────────────────────────
    // [Dinamik 2] Kalkan etiketini en aktif reseptör adına göre değiştirir
    let shieldLabel = 'PD-1';
    let shX = pointsInv[midIdx].x * 0.82;
    let shY = H * 0.38;

    if (topPairs.length > 0) {
      const lastHyphen = topPairs[0].pair.lastIndexOf('-');
      if (lastHyphen !== -1) {
        shieldLabel = topPairs[0].pair.substring(lastHyphen + 1);
      }
      
      const bestCellPair = Object.entries(topPairs[0].cellComm).sort((a,b)=>b[1]-a[1])[0]?.[0];
      if (bestCellPair) {
        const receiverType = mapFineGrainedToBroad(bestCellPair.split('->')[1]);
        const receivers = spots.filter(s => s.type === receiverType);
        if (receivers.length > 0) {
          shX = receivers.reduce((sum, s) => sum + s.px, 0) / receivers.length;
          shY = receivers.reduce((sum, s) => sum + s.py, 0) / receivers.length;
          
          // Biraz sağa/yukarı kaydırarak hücrelerin üstünü kapatmasını önle
          shX += 20;
          shY -= 20;
        }
      }
    }

    // Canvas sınırları dışına taşmayı önle
    shX = Math.max(40, Math.min(shX, W - 40));
    shY = Math.max(40, Math.min(shY, H - 40));

    const shield = el('g', { transform: `translate(${shX},${shY})`, filter: 'url(#tm-glow)' }, svg);
    el('path', {
      d: 'M0,-22 L20,-12 L20,7 C20,18 0,26 0,26 C0,26 -20,18 -20,7 L-20,-12 Z',
      fill: 'hsl(210,80%,40%)', opacity: '0.80'
    }, shield);
    el('path', {
      d: 'M0,-22 L20,-12 L20,7 C20,18 0,26 0,26 C0,26 -20,18 -20,7 L-20,-12 Z',
      fill: 'none', stroke: 'hsl(210,80%,68%)', 'stroke-width': '1.5'
    }, shield);
    const st = el('text', {
      x: '0', y: '8', fill: '#fff',
      'font-size': '9', 'font-family': 'Inter, system-ui, sans-serif',
      'font-weight': '800', 'text-anchor': 'middle'
    }, shield);
    st.textContent = shieldLabel;

    // Reseptör metninin genişliğine göre kalkan görselini yatayda ölçekle
    try {
      const tw = st.getBBox().width;
      if (tw > 26) {
        const scaleX = (tw + 14) / 40;
        shield.querySelectorAll('path').forEach(p => {
          p.setAttribute('transform', `scale(${scaleX.toFixed(2)}, 1)`);
        });
      }
    } catch (_) {}
  }

  // ── İstatistikleri güncelle ───────────────────────────────────────────
  function _updateStats(spots, totalSpots) {
    const counts  = {
      'GBM / Malignant': 0,
      'T-cell': 0,
      'NK-cell': 0,
      'TAM / Myeloid': 0,
      'Microglia': 0,
      'Dendritic Cell': 0,
      'Oligodendrocyte': 0,
      'Astrocyte': 0,
      'Vascular / Mural': 0,
      'Unknown': 0
    };
    const regions = { core: 0, invasion: 0, healthy: 0 };
    spots.forEach(s => {
      if (counts[s.type]   !== undefined) counts[s.type]++;
      if (regions[s.region] !== undefined) regions[s.region]++;
    });

    function set(id, v) {
      const e = document.getElementById(id);
      if (e) e.textContent = v;
    }

    // Legend ve istatistik kartlarını doldur
    set('tm-count-gbm',     counts['GBM / Malignant']);
    set('tm-count-tcell',   counts['T-cell'] + counts['NK-cell']); // T/NK hücre toplamı
    set('tm-count-micro',   counts['Microglia'] + counts['TAM / Myeloid']); // Myeloid grubu
    set('tm-count-astro',   counts['Astrocyte'] + counts['Oligodendrocyte']); // Glial grubu
    set('tm-count-unknown', counts['Unknown'] + counts['Vascular / Mural'] + counts['Dendritic Cell']);
    set('tm-total-spots',   totalSpots);

    const total = spots.length || 1;
    const pCore = Math.round(regions.core    / total * 100);
    const pInv  = Math.round(regions.invasion / total * 100);
    const pHlt  = 100 - pCore - pInv;
    set('tm-pct-core',    pCore + '%');
    set('tm-pct-inv',     pInv  + '%');
    set('tm-pct-healthy', Math.max(0, pHlt) + '%');
  }

  // ══════════════════════════════════════════════════════════════════════
  // TERAPÖTİK ÖNERİ TABLOSU (Klinik olarak zenginleştirilmiş ve veriye duyarlı)
  // ══════════════════════════════════════════════════════════════════════
  const ALL_RECS = [
    {
      target: 'GBM DNA Replication',
      drug: 'Temozolomid (TMZ)',
      cls_tr: 'Standart Alkilleyici Kemoterapi',
      cls_en: 'Standard Alkylating Chemotherapy',
      evidence_tr: 'En Güçlü (Birinci Basamak)',
      evidence_en: 'Strongest (First Line)',
      evidenceClass: 'ev-high',
      status_tr: 'FDA Onaylı',
      status_en: 'FDA Approved',
      statusClass: 'st-approved',
      targetClass: 'tgt-gbm',
      minGbmPct: 0.0,
      comment_tr: 'Stupp Protokolü: Standart birinci basamak tedavi (NCCN Kılavuzları).',
      comment_en: 'Stupp Protocol: Standard first-line treatment (NCCN Guidelines).'
    },
    {
      target: 'Tumor Mitosis / TTFields',
      drug: 'Optune (TTFields)',
      cls_tr: 'Tümör Tedavi Alanları (Cihaz)',
      cls_en: 'Tumor Treating Fields (Device)',
      evidence_tr: 'Güçlü (Kategori 1)',
      evidence_en: 'Strong (Category 1)',
      evidenceClass: 'ev-high',
      status_tr: 'FDA Onaylı (Nüks/Yeni tanı)',
      status_en: 'FDA Approved (Recurrent/Newly diag.)',
      statusClass: 'st-approved',
      targetClass: 'tgt-optune',
      minGbmPct: 0.30,
      comment_tr: 'EF-14 Faz III Çalışması: Tümör yükü yüksek (%30+) olgularda genel sağkalım (OS) avantajı sunar.',
      comment_en: 'EF-14 Phase III Trial: Offers overall survival (OS) advantage in high tumor burden (30%+) cases.'
    },
    {
      target: 'VEGF / Neo-Angiogenesis',
      drug: 'Bevacizumab (Avastin)',
      cls_tr: 'Anti-VEGF Monoklonal Antikor',
      cls_en: 'Anti-VEGF Monoclonal Antibody',
      evidence_tr: 'Güçlü (Ödem ve Nüks Kontrolü)',
      evidence_en: 'Strong (Edema & Recurrence Control)',
      evidenceClass: 'ev-high',
      status_tr: 'FDA Onaylı (Refrakter)',
      status_en: 'FDA Approved (Refractory)',
      statusClass: 'st-approved',
      targetClass: 'tgt-vegi',
      minVascularPct: 0.04,
      comment_tr: 'AVAGLIO Çalışması: Anjiyogenez yoğun (%4+ Vascular) olan tümörlerde ödem ve PFS kontrolü sağlar.',
      comment_en: 'AVAGLIO Trial: Provides edema and PFS control in angiogenesis-intense (4%+ Vascular) tumors.'
    },
    {
      target: 'DNA Alkylation / Repair Resistance',
      drug: 'Lomustin (CCNU)',
      cls_tr: 'Alkilleyici Nitrozüre Kemoterapi',
      cls_en: 'Alkylating Nitrosourea Chemotherapy',
      evidence_tr: 'Orta',
      evidence_en: 'Intermediate',
      evidenceClass: 'ev-med',
      status_tr: 'FDA Onaylı (Nüks/İkinci Basamak)',
      status_en: 'FDA Approved (Recurrent/Second Line)',
      statusClass: 'st-approved',
      targetClass: 'tgt-ccnu',
      minGbmPct: 0.15,
      maxTcellPct: 0.08,
      comment_tr: 'CeTeG/NOA-09 Çalışması: İmmün infiltrasyonun düşük (%8- T-cell) olduğu dirençli vakalarda tercih edilir.',
      comment_en: 'CeTeG/NOA-09 Trial: Preferred in resistant cases with low immune infiltration (8%- T-cell).'
    },
    {
      target: 'PD-L1 / PD-1 Axis',
      drug: 'Pembrolizumab (Keytruda)',
      cls_tr: 'Anti-PD-1 İmmün Kontrol Noktası İnh.',
      cls_en: 'Anti-PD-1 Immune Checkpoint Inhibitor',
      evidence_tr: 'Orta (Yüksek Mutasyon Yükü)',
      evidence_en: 'Intermediate (High Mutation Burden)',
      evidenceClass: 'ev-med',
      status_tr: 'Klinik Çalışma (Nüks)',
      status_en: 'Clinical Trial (Recurrent)',
      statusClass: 'st-trial',
      targetClass: 'tgt-pdl1',
      minTcellPct: 0.06,
      comment_tr: 'KEYNOTE Çalışmaları: T/NK lenfosit infiltrasyonu (%6+) gösteren TME profilinde immünoterapi adayıdır.',
      comment_en: 'KEYNOTE Trials: Candidate for immunotherapy in TME profiles with T/NK lymphocyte infiltration (6%+).'
    },
    {
      target: 'CSF1R / TAM Suppression',
      drug: 'PLX5622 / Pexidartinib',
      cls_tr: 'CSF1R Tirozin Kinaz İnhibitörü',
      cls_en: 'CSF1R Tyrosine Kinase Inhibitor',
      evidence_tr: 'Düşük (TME Yeniden Modelleme)',
      evidence_en: 'Low (TME Remodeling)',
      evidenceClass: 'ev-low',
      status_tr: 'Preklinik Araştırma',
      status_en: 'Preclinical Research',
      statusClass: 'st-research',
      targetClass: 'tgt-micro',
      minTamPct: 0.08,
      comment_tr: 'TAM hedeflenmesi: Baskılayıcı myeloid infiltrasyonu (%8+) olan soğuk tümörleri sıcaklaştırma amaçlı araştırma.',
      comment_en: 'TAM targeting: Research for warming cold tumors with suppressive myeloid infiltration (8%+).'
    }
  ];

  function _updateRecsTable(gnnData, enrichedSpots) {
    const tbody = document.getElementById('tm-recs-body');
    if (!tbody) return;

    const isTr = (window.i18n && window.i18n.lang === 'tr');

    let recs = ALL_RECS;

    if (enrichedSpots && enrichedSpots.length > 0) {
      const total = enrichedSpots.length;
      const pct = {
        GBM:       enrichedSpots.filter(s => s.type === 'GBM / Malignant').length  / total,
        tcell:     enrichedSpots.filter(s => s.type === 'T-cell' || s.type === 'NK-cell').length / total,
        tam:       enrichedSpots.filter(s => s.type === 'TAM / Myeloid').length    / total,
        vascular:  enrichedSpots.filter(s => s.type === 'Vascular / Mural').length / total,
      };

      recs = ALL_RECS.filter(r => {
        if (r.minTcellPct    !== undefined && pct.tcell    < r.minTcellPct)    return false;
        if (r.minGbmPct      !== undefined && pct.GBM      < r.minGbmPct)      return false;
        if (r.minTamPct      !== undefined && pct.tam      < r.minTamPct)      return false;
        if (r.minVascularPct !== undefined && pct.vascular < r.minVascularPct) return false;
        if (r.maxTcellPct    !== undefined && pct.tcell    > r.maxTcellPct)    return false;
        return true;
      });

      if (pct.tcell > 0.12) {
        recs = [
          ...recs.filter(r => r.targetClass === 'tgt-pdl1'),
          ...recs.filter(r => r.targetClass !== 'tgt-pdl1'),
        ];
      }
    }

    tbody.replaceChildren();

    if (recs.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.setAttribute('colspan', '5');
      td.style.textAlign = 'center';
      td.style.opacity = '0.6';
      td.style.padding = '16px';
      td.textContent = isTr
        ? 'Bu örnek için eşik değerlerini karşılayan öneri bulunamadı.'
        : 'No recommendations matching threshold values found for this sample.';
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    recs.forEach(r => {
      const tr = document.createElement('tr');

      const tdTgt = document.createElement('td');
      const spanTgt = document.createElement('span');
      spanTgt.className = `tm-tgt ${r.targetClass}`;
      spanTgt.textContent = r.target;
      tdTgt.appendChild(spanTgt);

      const tdDrug = document.createElement('td');
      const strongDrug = document.createElement('strong');
      strongDrug.textContent = r.drug;
      tdDrug.appendChild(strongDrug);

      const tdCls = document.createElement('td');
      tdCls.textContent = isTr ? r.cls_tr : r.cls_en;

      const tdEv = document.createElement('td');
      const spanEv = document.createElement('span');
      spanEv.className = `tm-ev ${r.evidenceClass}`;
      spanEv.textContent = isTr ? r.evidence_tr : r.evidence_en;
      tdEv.appendChild(spanEv);

      const tdSt = document.createElement('td');
      const spanSt = document.createElement('span');
      spanSt.className = `tm-st ${r.statusClass}`;
      spanSt.textContent = isTr ? r.status_tr : r.status_en;
      tdSt.appendChild(spanSt);

      tr.appendChild(tdTgt);
      tr.appendChild(tdDrug);
      tr.appendChild(tdCls);
      tr.appendChild(tdEv);
      tr.appendChild(tdSt);

      tbody.appendChild(tr);
    });
  }

})();
