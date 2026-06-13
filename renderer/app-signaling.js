/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — Signaling & Contrast (renderer)
   ══════════════════════════════════════════════════════════ */

/* global state, api, ZONE_COLORS, showWarningToast, showExportSuccessToast */

// HTML Sanitizer to prevent XSS in tooltips and contrast charts
function escapeHtml(str) {
  if (typeof str !== 'string') return String(str || '');
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Generate valid and safe element IDs for SVG gradients and selectors
function safeSvgId(str) {
  if (!str) return 'id-' + Math.random().toString(36).substring(2, 7);
  return 'id-' + str.replace(/[^a-zA-Z0-9-]/g, '_');
}

// Normalize strings for filter comparisons (Turkish/Unicode character-safe)
function normalizeForFilter(str) {
  if (!str) return '';
  return str.toLowerCase()
    .normalize('NFD') // Decompose accents
    .replace(/[\u0300-\u036f]/g, '') // Remove accent modifiers
    .replace(/ı/g, 'i')
    .replace(/ş/g, 's')
    .replace(/ğ/g, 'g')
    .replace(/ç/g, 'c')
    .replace(/ö/g, 'o')
    .replace(/ü/g, 'u')
    .replace(/[^a-z0-9]/g, ''); // Strip remaining non-alphanumeric chars
}

function pathwayPlasmaColor(t) {
  const stops = [
    [0.00,  15,  23,  42],   // #0f172a - Koyu Slate
    [0.30,  99, 102, 241],   // #6366f1 - İndigo
    [0.60, 236,  72, 153],   // #ec4899 - Pembe
    [0.85, 249, 115,  22],   // #f97316 - Turuncu
    [1.00, 234, 179,   8]    // #eab308 - Sarı
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, r0, g0, b0] = stops[i];
    const [t1, r1, g1, b1] = stops[i + 1];
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0);
      return `rgb(${Math.round(r0+(r1-r0)*f)},${Math.round(g0+(g1-g0)*f)},${Math.round(b0+(b1-b0)*f)})`;
    }
  }
  return 'rgb(234, 179, 8)';
}

function setupNewFeatures() {
  const data = state.gnnData;
  if (!data) return;

  // 1. Populate L-R Select in Signaling Panel safely
  const commData = data.cell_cell_communication || {};
  const lrSelect = document.getElementById('signaling-lr-select');
  if (lrSelect) {
    const lrKeys = Object.keys(commData);
    if (lrKeys.length > 0) {
      lrSelect.innerHTML = '';
      lrKeys.forEach(k => {
        const opt = document.createElement('option');
        opt.value = k;
        opt.textContent = k;
        lrSelect.appendChild(opt);
      });
      toggleElement(document.getElementById('signaling-placeholder'), false);
      toggleElement(document.getElementById('signaling-container'), true);
    } else {
      toggleElement(document.getElementById('signaling-placeholder'), true);
      toggleElement(document.getElementById('signaling-container'), false);
    }
  }

  // 2. Populate Cell Type checkboxes in Signaling Panel safely without innerHTML templates
  const ctList = (data.metadata && (data.metadata.cell_types || data.metadata.ct_names)) || [];
  if (ctList.length === 0) {
    showWarningToast('Hücre tipi listesi alınamadı. Sinyalleşme analizi devre dışı.');
  }

  const ctContainer = document.getElementById('signaling-ct-checkboxes');
  if (ctContainer) {
    ctContainer.innerHTML = '';
    ctList.forEach(ct => {
      const label = document.createElement('label');
      label.className = 'checkbox-item';
      
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = ct;
      input.checked = true;
      input.style.accentColor = 'var(--accent)';
      input.addEventListener('change', renderSignalingDiagram);
      
      const span = document.createElement('span');
      span.textContent = ct;
      
      label.appendChild(input);
      label.appendChild(span);
      ctContainer.appendChild(label);
    });
  }

  // Initialize view mode state
  state.signalingViewMode = state.signalingViewMode || 'chord';

  const btnChord = document.getElementById('btn-sig-view-chord');
  const btnHeatmap = document.getElementById('btn-sig-view-heatmap');

  if (btnChord && btnHeatmap) {
    btnChord.onclick = () => {
      btnChord.classList.add('active');
      btnHeatmap.classList.remove('active');
      state.signalingViewMode = 'chord';
      renderSignalingDiagram();
    };

    btnHeatmap.onclick = () => {
      btnHeatmap.classList.add('active');
      btnChord.classList.remove('active');
      state.signalingViewMode = 'heatmap';
      renderSignalingDiagram();
    };
  }

  // Export to CSV button listener
  const btnExport = document.getElementById('btn-export-sig-csv');
  if (btnExport) {
    btnExport.onclick = () => {
      exportSignalingToCSV();
    };
  }

  // 3. Render Signaling Diagram
  renderSignalingDiagram();

  // 4. Render Zonal Contrast Charts
  const contrastData = data.zonal_contrast || {};
  const pathwaysContrastGrid = document.getElementById('pathways-contrast-grid');
  const lrContrastGrid = document.getElementById('lr-contrast-grid');
  
  if (pathwaysContrastGrid && contrastData.pathways) {
    toggleElement(document.getElementById('contrast-placeholder'), false);
    toggleElement(document.getElementById('contrast-container'), true);
    
    // Group pathway scores across zones
    const pathways = {};
    Object.entries(contrastData.pathways).forEach(([zone, pData]) => {
      Object.entries(pData).forEach(([pName, val]) => {
        if (!pathways[pName]) pathways[pName] = {};
        pathways[pName][zone] = val;
      });
    });
    
    pathwaysContrastGrid.innerHTML = Object.entries(pathways).map(([pName, pData]) => {
      const displayName = pName.replace(/_/g, '/');
      return drawContrastChart(`chart-pathway-${pName}`, displayName, pData);
    }).join('');
  }

  if (lrContrastGrid && contrastData.lr_pairs) {
    // Group L-R scores across zones
    const lrPairs = {};
    Object.entries(contrastData.lr_pairs).forEach(([zone, lrData]) => {
      Object.entries(lrData).forEach(([lrName, val]) => {
        if (!lrPairs[lrName]) lrPairs[lrName] = {};
        lrPairs[lrName][zone] = val;
      });
    });
    
    // Sort L-R pairs by max activity across any zone to show the most relevant ones.
    const sortedLRPairs = Object.entries(lrPairs).sort((a, b) => {
      const maxA = Math.max(...Object.values(a[1]));
      const maxB = Math.max(...Object.values(b[1]));
      return maxB - maxA;
    });
    
    lrContrastGrid.innerHTML = sortedLRPairs.map(([lrName, lrData]) => {
      return drawContrastChart(`chart-lr-${lrName}`, lrName, lrData);
    }).join('');
  }
}

function renderSignalingDiagram() {
  const svg = document.getElementById('chord-svg');
  if (!svg || !state.gnnData) return;
  
  // Clear SVG and recreate spec-compliant <defs> tag for gradients
  svg.innerHTML = '';
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  svg.appendChild(defs);
  
  const commData = state.gnnData.cell_cell_communication || {};
  const lrSelect = document.getElementById('signaling-lr-select');
  if (!lrSelect) {
    svg.innerHTML = `<text x="0" y="0" text-anchor="middle" fill="var(--text-muted)">L-R seçimi için gerekli bileşen bulunamadı.</text>`;
    return;
  }
  
  const lrPair = lrSelect.value;
  if (!lrPair || !commData[lrPair]) {
    svg.innerHTML = `<text x="0" y="0" text-anchor="middle" fill="var(--text-muted)">Seçili L-R çifti için veri bulunamadı.</text>`;
    return;
  }
  
  const pairData = commData[lrPair];
  
  // Get active cell types from checkboxes safely
  const checkboxes = document.querySelectorAll('#signaling-ct-checkboxes input[type="checkbox"]');
  const activeCTs = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);
  
  if (activeCTs.length < 2) {
    svg.innerHTML = `<text x="0" y="0" text-anchor="middle" fill="var(--text-muted)">Lütfen en az 2 hücre tipi seçin.</text>`;
    return;
  }
  
  // Compute total weights for active cell types
  const W = {}; 
  activeCTs.forEach(a => {
    W[a] = {};
    activeCTs.forEach(b => {
      const key1 = `${a}->${b}`;
      const key2 = `${b}->${a}`;
      const w1 = pairData[key1] || 0;
      const w2 = pairData[key2] || 0;
      W[a][b] = w1 + w2;
    });
  });
  
  // Cell type colors map
  const ctColors = {};
  const allCTs = (state.gnnData.metadata && (state.gnnData.metadata.cell_types || state.gnnData.metadata.ct_names)) || [];
  const fixedColors = {
    'AC-like': '#4ECDC4',
    'MES-like': '#FF6B6B',
    'NPC-like': '#FFE66D',
    'OPC-like': '#A593E0',
    'Endothelial': '#45B6FE',
    'Microglia': '#34A853',
    'Oligodendrocyte': '#F2C94C',
    'Myeloid': '#9B51E0',
    'Stromal': '#A8B2C1'
  };
  
  allCTs.forEach((ct, idx) => {
    if (fixedColors[ct]) {
      ctColors[ct] = fixedColors[ct];
    } else {
      const hue = (idx * 137) % 360;
      ctColors[ct] = `hsl(${hue}, 70%, 60%)`;
    }
  });
  
  // Total weight per cell type
  const ctTotals = {};
  activeCTs.forEach(a => {
    let sum = 0;
    activeCTs.forEach(b => {
      sum += W[a][b];
    });
    ctTotals[a] = sum;
  });
  
  // Total communication weight
  const totalComm = Object.values(ctTotals).reduce((sum, val) => sum + val, 0);
  
  // Layout math
  const r = 180; // Inner radius
  const r_out = 195; // Outer radius
  const gap = 0.06; // Gap between sectors in radians
  const N = activeCTs.length;
  
  // Sector angles
  const minAngle = 0.12; 
  const totalGapAngle = N * gap;
  const remainingAngle = 2 * Math.PI - totalGapAngle;
  
  // Determine sector angle for each cell type
  const sectorAngles = {};
  if (totalComm > 0) {
    let sumAngles = 0;
    activeCTs.forEach(ct => {
      const ratio = ctTotals[ct] / totalComm;
      const angle = minAngle + (remainingAngle - N * minAngle) * ratio;
      sectorAngles[ct] = angle;
      sumAngles += angle;
    });
  } else {
    const angle = remainingAngle / N;
    activeCTs.forEach(ct => {
      sectorAngles[ct] = angle;
    });
  }
  
  // Assign start/end angles to each cell type sector
  const sectors = {};
  let currentAngle = -Math.PI / 2; 
  activeCTs.forEach(ct => {
    const start = currentAngle;
    const end = start + sectorAngles[ct];
    sectors[ct] = { start, end, mid: (start + end)/2 };
    currentAngle = end + gap;
  });
  
  // Draw outer sectors (arcs)
  const sectorsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  sectorsGroup.setAttribute('class', 'sectors-group');
  
  activeCTs.forEach(ct => {
    const { start, end, mid } = sectors[ct];
    const color = ctColors[ct];
    
    const x1_in = r * Math.cos(start), y1_in = r * Math.sin(start);
    const x2_in = r * Math.cos(end), y2_in = r * Math.sin(end);
    const x1_out = r_out * Math.cos(start), y1_out = r_out * Math.sin(start);
    const x2_out = r_out * Math.cos(end), y2_out = r_out * Math.sin(end);
    
    const largeArcFlag = (end - start) > Math.PI ? 1 : 0;
    
    const pathData = `
      M ${x1_in} ${y1_in}
      L ${x1_out} ${y1_out}
      A ${r_out} ${r_out} 0 ${largeArcFlag} 1 ${x2_out} ${y2_out}
      L ${x2_in} ${y2_in}
      A ${r} ${r} 0 ${largeArcFlag} 0 ${x1_in} ${y1_in}
      Z
    `;
    
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', pathData);
    path.setAttribute('fill', color);
    path.setAttribute('stroke', '#020509');
    path.setAttribute('stroke-width', '1.5');
    path.setAttribute('cursor', 'pointer');
    path.setAttribute('class', `sector sector-${ct.replace(/\s+/g, '-')}`);
    
    // Hover event for sector safely escaped
    path.addEventListener('mouseover', (e) => {
      highlightSector(ct);
      showChordTooltip(e, `<strong>${escapeHtml(ct)}</strong><br>Toplam Etkileşim Gücü: ${ctTotals[ct].toFixed(3)}`);
    });
    path.addEventListener('mousemove', (e) => {
      moveChordTooltip(e);
    });
    path.addEventListener('mouseout', () => {
      resetChordHighlight();
      hideChordTooltip();
    });
    
    sectorsGroup.appendChild(path);
    
    // Label text
    const labelDist = r_out + 12;
    const lx = labelDist * Math.cos(mid);
    const ly = labelDist * Math.sin(mid);
    
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', lx.toString());
    text.setAttribute('y', ly.toString());
    
    let textAnchor = 'middle';
    const deg = (mid * 180 / Math.PI) % 360;
    const normalizedDeg = deg < 0 ? deg + 360 : deg;
    if (normalizedDeg > 80 && normalizedDeg < 280) {
      textAnchor = 'end';
    } else if (normalizedDeg < 80 || normalizedDeg > 280) {
      textAnchor = 'start';
    }
    
    text.setAttribute('text-anchor', textAnchor);
    text.setAttribute('fill', 'var(--text)');
    text.setAttribute('font-size', '11px');
    text.setAttribute('font-weight', '600');
    text.setAttribute('alignment-baseline', 'middle');
    text.textContent = ct;
    
    sectorsGroup.appendChild(text);
  });
  
  svg.appendChild(sectorsGroup);
  
  // Allocate positions for chords inside each sector
  const chordPositions = {};
  activeCTs.forEach(ct => {
    chordPositions[ct] = { currentAngle: sectors[ct].start };
  });
  
  // Draw Chords
  const chordsGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  chordsGroup.setAttribute('class', 'chords-group');
  
  const renderedPairs = new Set();
  
  activeCTs.forEach(a => {
    activeCTs.forEach(b => {
      const chordId = [a, b].sort().join('::');
      if (renderedPairs.has(chordId)) return;
      renderedPairs.add(chordId);
      
      const w = W[a][b];
      if (w <= 0) return; 
      
      // Calculate angle width on sector a
      const sumA = ctTotals[a] || 1;
      const angleWidthA = sectorAngles[a] * (w / sumA);
      const startA = chordPositions[a].currentAngle;
      const endA = startA + angleWidthA;
      chordPositions[a].currentAngle = endA;
      
      // Calculate angle width on sector b
      const sumB = ctTotals[b] || 1;
      const angleWidthB = sectorAngles[b] * (w / sumB);
      const startB = chordPositions[b].currentAngle;
      const endB = startB + angleWidthB;
      chordPositions[b].currentAngle = endB;
      
      const x1_a = r * Math.cos(startA), y1_a = r * Math.sin(startA);
      const x2_a = r * Math.cos(endA), y2_a = r * Math.sin(endA);
      const x1_b = r * Math.cos(startB), y1_b = r * Math.sin(startB);
      const x2_b = r * Math.cos(endB), y2_b = r * Math.sin(endB);
      
      let pathData = '';
      if (a === b) {
        // Self loop
        const midAngle = (startA + endA) / 2;
        const ctrlDist = r * 0.7;
        const cx = ctrlDist * Math.cos(midAngle);
        const cy = ctrlDist * Math.sin(midAngle);
        pathData = `
          M ${x1_a} ${y1_a}
          A ${r} ${r} 0 0 1 ${x2_a} ${y2_a}
          Q ${cx} ${cy} ${x1_a} ${y1_a}
          Z
        `;
      } else {
        pathData = `
          M ${x1_a} ${y1_a}
          A ${r} ${r} 0 0 1 ${x2_a} ${y2_a}
          Q 0 0 ${x1_b} ${y1_b}
          A ${r} ${r} 0 0 1 ${x2_b} ${y2_b}
          Q 0 0 ${x1_a} ${y1_a}
          Z
        `;
      }
      
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', pathData);
      
      const gradId = `grad-${safeSvgId(a)}-${safeSvgId(b)}`;
      let grad = document.getElementById(gradId);
      if (!grad) {
        grad = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');
        grad.setAttribute('id', gradId);
        grad.setAttribute('x1', (x1_a / r / 2 + 0.5).toString());
        grad.setAttribute('y1', (y1_a / r / 2 + 0.5).toString());
        grad.setAttribute('x2', (x1_b / r / 2 + 0.5).toString());
        grad.setAttribute('y2', (y1_b / r / 2 + 0.5).toString());
        
        const stop1 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        stop1.setAttribute('offset', '0%');
        stop1.setAttribute('stop-color', ctColors[a]);
        stop1.setAttribute('stop-opacity', '0.65');
        
        const stop2 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        stop2.setAttribute('offset', '100%');
        stop2.setAttribute('stop-color', ctColors[b]);
        stop2.setAttribute('stop-opacity', '0.65');
        
        grad.appendChild(stop1);
        grad.appendChild(stop2);
        defs.appendChild(grad);
      }
      
      path.setAttribute('fill', `url(#${gradId})`);
      path.setAttribute('stroke', `url(#${gradId})`);
      path.setAttribute('stroke-width', '0.5');
      path.setAttribute('opacity', '0.6');
      path.setAttribute('cursor', 'pointer');
      path.setAttribute('class', `chord chord-${a.replace(/\s+/g, '-')} chord-${b.replace(/\s+/g, '-')}`);
      
      const ab_val = pairData[`${a}->${b}`] || 0;
      const ba_val = pairData[`${b}->${a}`] || 0;
      
      let tooltipContent = '';
      if (a === b) {
        tooltipContent = `
          <strong>${escapeHtml(a)} (Kendi Kendine)</strong><br>
          Etkileşim Gücü: ${ab_val.toFixed(4)}
        `;
      } else {
        tooltipContent = `
          <strong>${escapeHtml(a)} ⇄ ${escapeHtml(b)} İletişimi</strong><br>
          <span style="color:#00d4ff">${escapeHtml(a)} → ${escapeHtml(b)}:</span> ${ab_val.toFixed(4)}<br>
          <span style="color:#ff6b6b">${escapeHtml(b)} → ${escapeHtml(a)}:</span> ${ba_val.toFixed(4)}<br>
          <strong>Toplam Güç:</strong> ${w.toFixed(4)}
        `;
      }
      
      path.addEventListener('mouseover', (e) => {
        highlightChord(path, a, b);
        showChordTooltip(e, tooltipContent);
      });
      path.addEventListener('mousemove', (e) => {
        moveChordTooltip(e);
      });
      path.addEventListener('mouseout', () => {
        resetChordHighlight();
        hideChordTooltip();
      });
      
      chordsGroup.appendChild(path);
    });
  });
  
  svg.appendChild(chordsGroup);

  // Always update Heatmap and Stats Table
  renderSignalingHeatmap(activeCTs, pairData, ctColors);
  populateSignalingStatsTable(pairData, activeCTs);

  // Handle visibility based on view mode
  const chordWrapper = document.getElementById('chord-diagram-wrapper');
  const heatmapWrapper = document.getElementById('signaling-heatmap-wrapper');

  if (state.signalingViewMode === 'heatmap') {
    if (chordWrapper) chordWrapper.classList.add('hidden');
    if (heatmapWrapper) heatmapWrapper.classList.remove('hidden');
  } else {
    if (chordWrapper) chordWrapper.classList.remove('hidden');
    if (heatmapWrapper) heatmapWrapper.classList.add('hidden');
  }
}

function highlightSector(ct) {
  const safeCt = ct.replace(/\s+/g, '-');
  document.querySelectorAll('.chord').forEach(ch => {
    if (ch.classList.contains(`chord-${safeCt}`)) {
      ch.setAttribute('opacity', '0.9');
    } else {
      ch.setAttribute('opacity', '0.05');
    }
  });
}

function highlightChord(el, a, b) {
  document.querySelectorAll('.chord').forEach(ch => {
    if (ch === el) {
      ch.setAttribute('opacity', '0.95');
      ch.setAttribute('stroke-width', '1.5');
    } else {
      ch.setAttribute('opacity', '0.05');
    }
  });
}

function resetChordHighlight() {
  document.querySelectorAll('.chord').forEach(ch => {
    ch.setAttribute('opacity', '0.6');
    ch.setAttribute('stroke-width', '0.5');
  });
}

function showChordTooltip(e, content) {
  const tt = document.getElementById('chord-tooltip');
  if (!tt) return;
  tt.innerHTML = content; // content constructed using safe escapeHtml() function call
  tt.classList.remove('hidden');
  moveChordTooltip(e);
}

function moveChordTooltip(e) {
  const tt = document.getElementById('chord-tooltip');
  if (!tt) return;
  const wrapper = document.getElementById('chord-diagram-wrapper');
  if (!wrapper) return;
  const rect = wrapper.getBoundingClientRect();
  const x = e.clientX - rect.left + 15;
  const y = e.clientY - rect.top + 10;
  tt.style.left = `${x}px`;
  tt.style.top = `${y}px`;
}

function hideChordTooltip() {
  const tt = document.getElementById('chord-tooltip');
  if (tt) tt.classList.add('hidden');
}

function switchContrastTab(tab) {
  document.querySelectorAll('.contrast-tabs .btn-tab').forEach(btn => {
    btn.classList.remove('active');
  });
  
  const activeBtn = document.getElementById(`btn-tab-${tab}`);
  if (activeBtn) {
    activeBtn.classList.add('active');
  }
  
  document.querySelectorAll('.contrast-tab-panel').forEach(panel => {
    panel.classList.add('hidden');
  });
  
  const targetPanel = document.getElementById(`contrast-${tab}-panel`);
  if (targetPanel) {
    targetPanel.classList.remove('hidden');
  }
}

function drawContrastChart(containerId, title, data) {
  const entries = Object.entries(data);
  const maxVal = Math.max(...entries.map(e => e[1])) || 1.0;
  
  let rowsHtml = '';
  entries.forEach(([zone, val], idx) => {
    const color = ZONE_COLORS[zone] || '#888';
    const y = idx * 30 + 10;
    const barMaxWidth = 250;
    const width = maxVal > 0 ? Math.max(0, (val / maxVal) * barMaxWidth) : 0;
    
    rowsHtml += `
      <g class="bar-row">
        <text x="10" y="${y + 10}" fill="var(--text-muted)" font-size="11px" font-weight="600">${escapeHtml(zone)}</text>
        <rect x="10" y="${y + 16}" width="${barMaxWidth}" height="8" rx="4" fill="#1e293b" opacity="0.5" />
        <rect x="10" y="${y + 16}" width="${width}" height="8" rx="4" fill="${color}">
          <animate attributeName="width" from="0" to="${width}" dur="0.8s" fill="freeze" />
        </rect>
        <text x="${Math.max(10 + width + 8, 10 + barMaxWidth - 40)}" y="${y + 23}" fill="var(--text)" font-size="11px" font-weight="bold" font-family="monospace">${val.toFixed(3)}</text>
      </g>
    `;
  });
  
  return `
    <div class="card" style="background:var(--card); border:1px solid var(--border); padding:16px; border-radius:12px; display:flex; flex-direction:column; gap:12px;">
      <h3 style="margin:0; font-size:0.95rem; color:var(--text); border-bottom:1px solid var(--border); padding-bottom:8px;">
        <span>📊 ${escapeHtml(title)}</span>
      </h3>
      <svg width="100%" height="165" style="overflow:visible;">
        ${rowsHtml}
      </svg>
    </div>
  `;
}

// ══════════════════════════════════════════════════════════════
// 4.3 — INTERACTIVE L-R CATALOG OVERLAY MODAL LOGIC
// ══════════════════════════════════════════════════════════════
async function openLrCatalogModal() {
  if (!state.outputDir) { showWarningToast('Önce bir analiz çalıştırın.'); return; }
  
  const modal = document.getElementById('lr-catalog-modal');
  if (!modal) return;
  
  // Show loading state in table
  const tbody = document.getElementById('lr-catalog-tbody');
  tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:32px; color:var(--text-muted);">🧬 L-R Kataloğu yükleniyor...</td></tr>`;
  modal.classList.remove('hidden');
  
  try {
    const res = await api.backendRequest(`/results/lr-detailed?output_dir=${encodeURIComponent(state.outputDir)}`, 'GET', {});
    // Persist list in standard app state context rather than global window kirliliği
    state.lrCatalogData = res;
    
    populateLrCatalogTable(state.lrCatalogData);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:32px; color:var(--danger);">❌ Katalog yüklenemedi: ${escapeHtml(e.message || e)}</td></tr>`;
  }
}

function closeLrCatalogModal() {
  const modal = document.getElementById('lr-catalog-modal');
  if (modal) modal.classList.add('hidden');
}

function populateLrCatalogTable(data) {
  const tbody = document.getElementById('lr-catalog-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  
  if (!data || data.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.setAttribute('colspan', '5');
    td.style.cssText = 'text-align:center; padding:32px; color:var(--text-muted);';
    td.textContent = 'Hiçbir etkileşim bulunamadı.';
    tr.appendChild(td);
    tbody.appendChild(tr);
    
    const counter = document.getElementById('lr-catalog-counter');
    if (counter) counter.textContent = 'Toplam: 0 etkileşim gösteriliyor';
    return;
  }
  
  const fragment = document.createDocumentFragment();
  
  data.forEach(item => {
    const tr = document.createElement('tr');
    tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.03); transition:background 0.2s;';
    
    // Non-inline event listeners for mouseover / mouseout background changes
    tr.addEventListener('mouseover', () => {
      tr.style.background = 'rgba(255,255,255,0.02)';
    });
    tr.addEventListener('mouseout', () => {
      tr.style.background = 'transparent';
    });
    
    // 1. Pair
    const tdPair = document.createElement('td');
    tdPair.style.cssText = 'padding:14px 16px; font-weight:700; color:var(--text); font-family:var(--mono);';
    tdPair.textContent = item.pair || '';
    tr.appendChild(tdPair);
    
    // 2. Category
    const tdCat = document.createElement('td');
    tdCat.style.cssText = 'padding:14px 16px;';
    
    let catBg = 'rgba(255,255,255,0.05)';
    let catCol = 'var(--text-dim)';
    const catName = item.category || '';
    if (catName.includes('Angiogenesis')) { catBg = 'rgba(230,57,70,0.12)'; catCol = '#ef4444'; }
    else if (catName.includes('Immunosuppression')) { catBg = 'rgba(124,58,237,0.12)'; catCol = '#a78bfa'; }
    else if (catName.includes('Invasion')) { catBg = 'rgba(245,158,11,0.12)'; catCol = '#fbbf24'; }
    else if (catName.includes('Chemokine')) { catBg = 'rgba(16,185,129,0.12)'; catCol = '#34d399'; }
    else if (catName.includes('Ecm')) { catBg = 'rgba(0,212,255,0.12)'; catCol = '#22d3ee'; }
    else if (catName.includes('Neuro')) { catBg = 'rgba(236,72,153,0.12)'; catCol = '#f472b6'; }
    else if (catName.includes('Stemness')) { catBg = 'rgba(255,255,255,0.1)'; catCol = '#e2e8f0'; }
    
    const catSpan = document.createElement('span');
    catSpan.style.cssText = `background:${catBg}; color:${catCol}; padding:4px 8px; border-radius:100px; font-size:0.75rem; font-weight:600; display:inline-block;`;
    catSpan.textContent = catName;
    tdCat.appendChild(catSpan);
    tr.appendChild(tdCat);
    
    // 3. Intensity
    const tdIntensity = document.createElement('td');
    tdIntensity.style.cssText = 'padding:14px 16px; text-align:right; font-family:var(--mono); font-weight:700; color:var(--accent);';
    tdIntensity.textContent = (item.mean_intensity || 0).toFixed(4);
    tr.appendChild(tdIntensity);
    
    // 4. Drug
    const tdDrug = document.createElement('td');
    tdDrug.style.cssText = 'padding:14px 16px; line-height:1.3;';
    
    const isTargeted = item.drug && item.drug !== 'Yok / Araştırma Safhası';
    if (isTargeted) {
      const drugSpan = document.createElement('span');
      drugSpan.style.cssText = 'color:#00d4ff; font-weight:700;';
      drugSpan.textContent = `💊 ${item.drug}`;
      tdDrug.appendChild(drugSpan);
      
      const mechSpan = document.createElement('span');
      mechSpan.style.cssText = 'font-size:0.75rem; color:var(--text-muted); display:block;';
      mechSpan.textContent = `(${item.drug_mechanism || ''})`;
      tdDrug.appendChild(mechSpan);
    } else {
      const emptySpan = document.createElement('span');
      emptySpan.style.cssText = 'color:var(--text-muted); font-size:0.8rem;';
      emptySpan.textContent = '—';
      tdDrug.appendChild(emptySpan);
    }
    tr.appendChild(tdDrug);
    
    // 5. Action
    const tdAction = document.createElement('td');
    tdAction.style.cssText = 'padding:14px 16px; text-align:center; display:flex; gap:6px; justify-content:center;';
    
    const btn = document.createElement('button');
    btn.className = 'btn-secondary';
    btn.style.cssText = 'padding:5px 10px; font-size:0.75rem; font-weight:700; border-radius:6px; border-color:var(--accent); color:var(--accent); cursor:pointer;';
    btn.textContent = '🎯 Seç & Çiz';
    
    const key = `${item.ligand}-${item.receptor}`;
    btn.addEventListener('click', () => {
      selectLrFromCatalog(key);
    });
    
    const btnPathway = document.createElement('button');
    btnPathway.className = 'btn-primary';
    btnPathway.style.cssText = 'padding:5px 10px; font-size:0.75rem; font-weight:700; border-radius:6px; cursor:pointer;';
    btnPathway.textContent = '🧬 Yol Yolağı';
    btnPathway.addEventListener('click', () => {
      openPathwayEnrichmentModal(item.ligand, item.receptor);
    });

    tdAction.appendChild(btn);
    tdAction.appendChild(btnPathway);
    tr.appendChild(tdAction);
    
    fragment.appendChild(tr);
  });
  
  tbody.appendChild(fragment);
  
  const counter = document.getElementById('lr-catalog-counter');
  if (counter) counter.textContent = `Toplam: ${data.length} etkileşim gösteriliyor`;
}

function filterLrCatalog() {
  const searchInput = document.getElementById('lr-catalog-search');
  const catFilter = document.getElementById('lr-catalog-cat-filter');
  if (!searchInput || !catFilter || !state.lrCatalogData) return;

  const query = searchInput.value.toLowerCase().trim();
  const cat = catFilter.value;
  
  const filtered = state.lrCatalogData.filter(item => {
    // 1. Filter by category
    if (cat !== 'all') {
      const matchCat = normalizeForFilter(item.category);
      const filterCat = normalizeForFilter(cat);
      if (!matchCat.includes(filterCat)) return false;
    }
    
    // 2. Filter by search query
    if (query !== '') {
      const inLigand = (item.ligand || '').toLowerCase().includes(query);
      const inReceptor = (item.receptor || '').toLowerCase().includes(query);
      const inCategory = (item.category || '').toLowerCase().includes(query);
      const inDrug = (item.drug || '').toLowerCase().includes(query);
      if (!inLigand && !inReceptor && !inCategory && !inDrug) return false;
    }
    
    return true;
  });
  
  populateLrCatalogTable(filtered);
}

function selectLrFromCatalog(lrKey) {
  const lrSelect = document.getElementById('signaling-lr-select');
  if (lrSelect) {
    const hasOption = Array.from(lrSelect.options).some(opt => opt.value === lrKey);
    if (!hasOption) {
      const opt = document.createElement('option');
      opt.value = lrKey;
      opt.textContent = lrKey;
      lrSelect.appendChild(opt);
    }
    
    lrSelect.value = lrKey;
    renderSignalingDiagram();
  }
  closeLrCatalogModal();
  showExportSuccessToast(`${lrKey} seçildi ve uzamsal diyagram çizildi!`);
}

// ══════════════════════════════════════════════════════════════
// 4.4 — DOWNSTREAM PATHWAY ENRICHMENT MODAL LOGIC
// ══════════════════════════════════════════════════════════════

async function openPathwayEnrichmentModal(ligand, receptor) {
  if (!state.outputDir) { showWarningToast('Önce bir analiz çalıştırın.'); return; }
  
  const modal = document.getElementById('pathway-enrichment-modal');
  if (!modal) return;

  const pairText = `${ligand} → ${receptor}`;
  document.getElementById('pathway-selected-pair').textContent = pairText;
  state.currentPathwayPair = `${ligand}-${receptor}`;
  
  // Reset tabs and contents
  initPathwayTabs();
  
  // Show loading in table
  const tbody = document.getElementById('pathway-enrichment-tbody');
  tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--text-muted);">🧬 Yolaklar analiz ediliyor (Welch's t-test + Fisher)...</td></tr>`;
  
  modal.classList.remove('hidden');

  try {
    const zoneEl = document.getElementById('pathway-zone-select');
    const zoneParam = zoneEl ? zoneEl.value : '';
    let url = `/results/pathway-enrichment?output_dir=${encodeURIComponent(state.outputDir)}&ligand=${encodeURIComponent(ligand)}&receptor=${encodeURIComponent(receptor)}`;
    if (zoneParam) url += `&zone=${encodeURIComponent(zoneParam)}`;
    
    const res = await api.backendRequest(url, 'GET', {});
    state.pathwayData = res;
    renderPathwayTable(res, ligand, receptor);
    populatePathwayDrugs(res);

    // Zone badge güncelle
    const badge = document.getElementById('pathway-zone-badge');
    if (badge) {
      if (zoneParam) {
        const zoneLabels = {
          'Leading_Edge': '🔴 Leading Edge',
          'Infiltrating_Tumor': '🟠 Infiltrating Tumor',
          'Cellular_Tumor': '🟡 Cellular Tumor',
          'Pseudopalisading_Necrosis': '⚫ PN Necrosis',
          'Microvascular_Proliferation': '🔵 MVP'
        };
        badge.textContent = `✓ Zone-Stratified: ${zoneLabels[zoneParam] || zoneParam} | ${res.length} yolak`;
        badge.style.display = 'inline';
        badge.style.color = '#00d4ff';
      } else {
        badge.textContent = `✓ Global Analiz | ${res.length} yolak`;
        badge.style.display = 'inline';
        badge.style.color = 'var(--text-muted)';
      }
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--danger);">❌ Analiz başarısız oldu: ${escapeHtml(e.message || e)}</td></tr>`;
  }
}

async function rerunPathwayEnrichment() {
  if (!state.currentPathwayPair) return;
  const [lig, rec] = state.currentPathwayPair.split('-');
  const tbody = document.getElementById('pathway-enrichment-tbody');
  if (tbody) {
    const zoneEl = document.getElementById('pathway-zone-select');
    const zoneLabel = zoneEl ? (zoneEl.options[zoneEl.selectedIndex]?.text || '') : '';
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--text-muted);">🧬 ${zoneLabel || 'Tüm Tümör'} için yeniden analiz ediliyor...</td></tr>`;
  }
  await openPathwayEnrichmentModal(lig, rec);
}


function closePathwayEnrichmentModal() {
  const modal = document.getElementById('pathway-enrichment-modal');
  if (modal) modal.classList.add('hidden');
}

function initPathwayTabs() {
  const tabs = document.querySelectorAll('.pathway-tab');
  const panels = document.querySelectorAll('.pathway-tab-content');
  
  // Default to first tab
  tabs.forEach((tab, idx) => {
    if (idx === 0) tab.classList.add('active');
    else tab.classList.remove('active');
  });
  panels.forEach((panel, idx) => {
    if (idx === 0) panel.classList.remove('hidden');
    else panel.classList.add('hidden');
  });

  tabs.forEach(tab => {
    // Avoid double event binding
    const newTab = tab.cloneNode(true);
    tab.parentNode.replaceChild(newTab, tab);
    
    newTab.addEventListener('click', () => {
      const targetTabId = newTab.getAttribute('data-tab');
      
      document.querySelectorAll('.pathway-tab').forEach(t => t.classList.remove('active'));
      newTab.classList.add('active');
      
      document.querySelectorAll('.pathway-tab-content').forEach(p => p.classList.add('hidden'));
      const activePanel = document.getElementById(targetTabId);
      if (activePanel) activePanel.classList.remove('hidden');
      
      // Trigger rendering when specific tab is active
      if (targetTabId === 'pathway-network-tab') {
        const selectElement = document.getElementById('kegg-pathway-select');
        if (selectElement && selectElement.value) {
          renderPathwayNetwork(selectElement.value);
        } else if (state.pathwayData && state.pathwayData.length > 0) {
          renderPathwayNetwork(state.pathwayData[0].id);
        }
      } else if (targetTabId === 'pathway-map-tab') {
        const selectElement = document.getElementById('kegg-pathway-select');
        if (selectElement && selectElement.value) {
          const [lig, rec] = state.currentPathwayPair.split('-');
          renderPathwayMap(selectElement.value, lig, rec);
        }
      }
    });
  });
}

function renderPathwayTable(results, ligand, receptor) {
  const tbody = document.getElementById('pathway-enrichment-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  
  const selectElement = document.getElementById('kegg-pathway-select');
  if (selectElement) selectElement.innerHTML = '';

  if (!results || results.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--text-muted);">Anlamlı şekilde zenginleşmiş yolak bulunamadı.</td></tr>`;
    return;
  }

  results.forEach(path => {
    // Populate select dropdown for KEGG pathways
    if (path.type === 'KEGG' && selectElement) {
      const opt = document.createElement('option');
      opt.value = path.id;
      opt.textContent = `${path.name} (${path.id})`;
      selectElement.appendChild(opt);
    }

    const tr = document.createElement('tr');
    tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.03);';
    
    // Odds ratio width calculation
    const logOdds = Math.max(0, Math.min(10, Math.log1p(path.odds_ratio)));
    const percentage = (logOdds / 10) * 100;
    
    tr.innerHTML = `
      <td style="padding:12px 16px; font-weight:700; font-family:var(--mono);">${escapeHtml(path.id)}</td>
      <td style="padding:12px 16px; font-weight:600; color:var(--text);">${escapeHtml(path.name)}</td>
      <td style="padding:12px 16px;"><span style="background:${path.type === 'KEGG' ? 'rgba(0,212,255,0.12)' : 'rgba(124,58,237,0.12)'}; color:${path.type === 'KEGG' ? '#00d4ff' : '#a78bfa'}; padding:2px 6px; border-radius:4px; font-size:0.7rem; font-weight:bold;">${path.type}</span></td>
      <td style="padding:12px 16px; color:var(--text-muted); font-size:0.8rem;">${escapeHtml(path.category || 'N/A')}</td>
      <td style="padding:12px 16px; text-align:right; font-family:var(--mono); font-size:0.85rem;">${path.overlap_count} / ${path.pathway_count}</td>
      <td style="padding:12px 16px; text-align:right; font-family:var(--mono); font-size:0.85rem; color:${path.pvalue < 0.01 ? '#10b981' : 'var(--text-dim)'};">${path.pvalue.toExponential(3)}</td>
      <td style="padding:12px 16px; text-align:right; font-family:var(--mono); font-size:0.85rem; color:${path.fdr_qvalue < 0.05 ? '#00d4ff' : 'var(--text-dim)'}; font-weight:${path.fdr_qvalue < 0.05 ? '700' : 'normal'};">${path.fdr_qvalue.toExponential(3)}</td>
      <td style="padding:12px 16px; text-align:center;">
        <button class="btn-secondary" style="padding:4px 8px; font-size:0.7rem; font-weight:700; border-radius:4px;" onclick="visualizeSpecificPathway('${path.id}')">🔍 İncele</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  // Setup select change listener
  if (selectElement) {
    selectElement.addEventListener('change', () => {
      const activeTabBtn = document.querySelector('.pathway-tab.active');
      const activeTabId = activeTabBtn ? activeTabBtn.getAttribute('data-tab') : '';
      
      if (activeTabId === 'pathway-network-tab') {
        renderPathwayNetwork(selectElement.value);
      } else if (activeTabId === 'pathway-map-tab') {
        const [lig, rec] = state.currentPathwayPair.split('-');
        renderPathwayMap(selectElement.value, lig, rec);
      }
    });
  }
}

function visualizeSpecificPathway(pathwayId) {
  const path = state.pathwayData.find(p => p.id === pathwayId);
  if (!path) return;

  const selectElement = document.getElementById('kegg-pathway-select');
  if (selectElement) {
    // Check if pathwayId is in options, if not add it dynamically
    const hasOption = Array.from(selectElement.options).some(opt => opt.value === pathwayId);
    if (!hasOption) {
      const opt = document.createElement('option');
      opt.value = pathwayId;
      opt.textContent = `${path.name} (${pathwayId})`;
      selectElement.appendChild(opt);
    }
    selectElement.value = pathwayId;
  }

  // Switch to Network or Map depending on type
  if (path.type === 'KEGG') {
    // Open Map tab
    document.querySelector('.pathway-tab[data-tab="pathway-map-tab"]').click();
  } else {
    // Open Network tab
    document.querySelector('.pathway-tab[data-tab="pathway-network-tab"]').click();
  }
}

function renderPathwayNetwork(pathwayId) {
  const pathway = state.pathwayData.find(p => p.id === pathwayId);
  if (!pathway) return;

  const cyContainer = document.getElementById('cy');
  if (!cyContainer) return;
  cyContainer.innerHTML = '';

  const nodes = [];
  const edges = [];
  const [lig, rec] = state.currentPathwayPair.split('-');
  
  // Add source nodes
  nodes.push({ data: { id: lig, label: lig, type: 'lr' } });
  nodes.push({ data: { id: rec, label: rec, type: 'lr' } });
  edges.push({ data: { source: lig, target: rec, label: 'Binds' } });

  // Add overlap DEG nodes
  pathway.overlap_genes.forEach(gene => {
    const gUpper = gene.toUpperCase();
    if (gUpper !== lig.toUpperCase() && gUpper !== rec.toUpperCase()) {
      nodes.push({ data: { id: gUpper, label: gUpper, type: 'deg' } });
      edges.push({ data: { source: rec, target: gUpper, label: 'Downstream' } });
    }
  });

  // Add structural pathway context nodes
  const addedSet = new Set(nodes.map(n => n.data.id));
  let structuralCount = 0;
  pathway.overlap_genes.forEach(deg => {
    // Mock connections between DEGs and downstream elements if it creates a richer graph
    const downstreamPartners = {
      'VEGFA': ['KDR', 'FLT1'],
      'EGFR': ['AKT1', 'MAPK1'],
      'KDR': ['PLCG1', 'PRKCA'],
      'PIK3CA': ['AKT1', 'MTOR'],
      'CD44': ['AKT1', 'RELA']
    };
    const partners = downstreamPartners[deg] || [];
    partners.forEach(partner => {
      if (!addedSet.has(partner) && structuralCount < 4) {
        nodes.push({ data: { id: partner, label: partner, type: 'pathway' } });
        edges.push({ data: { source: deg, target: partner, label: 'Signaling' } });
        addedSet.add(partner);
        structuralCount++;
      }
    });
  });

  try {
    const cy = cytoscape({
      container: cyContainer,
      elements: [...nodes, ...edges],
      style: [
        {
          selector: 'node',
          style: {
            'label': 'data(label)',
            'color': '#ffffff',
            'font-family': 'var(--font)',
            'font-size': '10px',
            'font-weight': 'bold',
            'text-valign': 'center',
            'text-halign': 'center',
            'background-color': '#475569',
            'width': '38px',
            'height': '38px',
            'border-width': '2px',
            'border-color': 'rgba(255,255,255,0.15)',
            'box-shadow': '0 4px 6px rgba(0,0,0,0.3)'
          }
        },
        {
          selector: 'node[type="lr"]',
          style: {
            'background-color': '#ef4444',
            'border-color': '#f87171',
            'width': '44px',
            'height': '44px'
          }
        },
        {
          selector: 'node[type="deg"]',
          style: {
            'background-color': '#3b82f6',
            'border-color': '#60a5fa',
            'width': '42px',
            'height': '42px'
          }
        },
        {
          selector: 'node[type="pathway"]',
          style: {
            'background-color': '#334155',
            'border-color': '#475569',
            'width': '34px',
            'height': '34px',
            'color': '#94a3b8'
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': 'rgba(255,255,255,0.12)',
            'target-arrow-color': 'rgba(255,255,255,0.12)',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'label': 'data(label)',
            'font-size': '8px',
            'color': '#64748b',
            'text-rotation': 'autorotate'
          }
        }
      ],
      layout: {
        name: 'cose',
        animate: true,
        fit: true,
        padding: 30
      }
    });

    setTimeout(() => { cy.resize(); cy.fit(); }, 200);
  } catch (err) {
    console.error('Cytoscape error:', err);
    cyContainer.innerHTML = `<p style="padding: 24px; text-align:center; color:var(--text-muted);">Etkileşimli network yüklenemedi: ${err.message || err}</p>`;
  }
}

function renderPathwayMap(pathwayId, ligand, receptor) {
  const img = document.getElementById('kegg-map-img');
  const loader = document.getElementById('kegg-map-loading');
  if (!img || !loader) return;

  img.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  
  if (pathwayId && pathwayId.startsWith('GO:')) {
    loader.innerHTML = 'ℹ️ Gene Ontology (GO) terimleri için görsel KEGG haritası bulunmamaktadır. Lütfen "Etkileşimli Network" sekmesini kullanın.';
    loader.classList.remove('hidden');
    return;
  }

  loader.innerHTML = '⏳ Biyolojik harita yükleniyor...';
  loader.classList.remove('hidden');

  const zoneEl = document.getElementById('pathway-zone-select');
  const zoneParam = zoneEl ? zoneEl.value : '';

  const url = `/results/pathway-image?output_dir=${encodeURIComponent(state.outputDir)}&pathway_id=${encodeURIComponent(pathwayId)}&ligand=${encodeURIComponent(ligand)}&receptor=${encodeURIComponent(receptor)}&zone=${encodeURIComponent(zoneParam)}`;
  
  img.src = api.getBackendUrl() + url;
  
  img.onload = () => {
    loader.classList.add('hidden');
    initPathwayMapZoomPan();
  };
  
  img.onerror = () => {
    loader.innerHTML = '❌ Biyolojik harita overlay oluşturulamadı';
  };
}

function initPathwayMapZoomPan() {
  const img = document.getElementById('kegg-map-img');
  const wrapper = document.getElementById('kegg-map-wrapper');
  if (!img || !wrapper) return;

  // Set defaults
  let scale = 1.0;
  let isDragging = false;
  let startX = 0, startY = 0;
  let scrollLeft = 0, scrollTop = 0;

  img.style.transform = `scale(${scale})`;
  img.style.cursor = 'grab';

  // Double click reset
  img.ondblclick = () => {
    scale = scale === 1.0 ? 1.4 : 1.0;
    img.style.transform = `scale(${scale})`;
  };

  // Mouse wheel zoom
  wrapper.onwheel = (e) => {
    e.preventDefault();
    const zoomFactor = 0.08;
    if (e.deltaY < 0) {
      scale = Math.min(2.5, scale + zoomFactor);
    } else {
      scale = Math.max(0.6, scale - zoomFactor);
    }
    img.style.transform = `scale(${scale})`;
  };

  // Drag and Scroll
  img.onmousedown = (e) => {
    isDragging = true;
    img.style.cursor = 'grabbing';
    startX = e.pageX - wrapper.offsetLeft;
    startY = e.pageY - wrapper.offsetTop;
    scrollLeft = wrapper.scrollLeft;
    scrollTop = wrapper.scrollTop;
  };

  window.onmouseup = () => {
    isDragging = false;
    img.style.cursor = 'grab';
  };

  img.onmousemove = (e) => {
    if (!isDragging) return;
    e.preventDefault();
    const x = e.pageX - wrapper.offsetLeft;
    const y = e.pageY - wrapper.offsetTop;
    const walkX = (x - startX) * 1.5;
    const walkY = (y - startY) * 1.5;
    wrapper.scrollLeft = scrollLeft - walkX;
    wrapper.scrollTop = scrollTop - walkY;
  };
}

function populatePathwayDrugs(results) {
  const tbody = document.getElementById('pathway-drugs-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (!results || results.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">Druggable downstream gen bulunamadı.</td></tr>`;
    return;
  }

  // Predefined list of druggable genes in glioblastoma pathways
  const DRUGGABLE_DOWNSTREAM_CATALOG = {
    "AKT1": { "drug": "Ipatasertib", "mechanism": "AKT Kinaz İnhibitörü", "status": "Klinik Deneme (Faz II)" },
    "AKT2": { "drug": "Ipatasertib", "mechanism": "AKT Kinaz İnhibitörü", "status": "Klinik Deneme (Faz II)" },
    "MTOR": { "drug": "Everolimus / Temsirolimus", "mechanism": "mTORC1 Kompleks Blokajı", "status": "Klinik Deneme (Faz II/III)" },
    "EGFR": { "drug": "Erlotinib / Lapatinib", "mechanism": "Reseptör Tirozin Kinaz İnhibitörü", "status": "FDA Onaylı (Çeşitli Kanserler)" },
    "MET": { "drug": "Crizotinib / Cabozantinib", "mechanism": "HGFR / MET Tirozin Kinaz Blokajı", "status": "Klinik Deneme (Faz II)" },
    "KDR": { "drug": "Cabozantinib / Regorafenib", "mechanism": "VEGFR2 Reseptör İnhibisyonu", "status": "Klinik Deneme (Faz III)" },
    "FLT1": { "drug": "Regorafenib", "mechanism": "Multikinaz / VEGFR1 İnhibitörü", "status": "Klinik Deneme (Faz II)" },
    "JAK1": { "drug": "Ruxolitinib", "mechanism": "JAK1/JAK2 Sinyal İletim İnhibitörü", "status": "Klinik Deneme (Faz I/II)" },
    "JAK2": { "drug": "Ruxolitinib", "mechanism": "JAK1/JAK2 Sinyal İletim İnhibitörü", "status": "Klinik Deneme (Faz I/II)" },
    "STAT3": { "drug": "Napabucasin", "mechanism": "STAT3 Transkripsiyon İnhibitörü", "status": "Klinik Deneme (Faz II)" },
    "PTEN": { "drug": "VO-Ohpic", "mechanism": "PTEN Aktivatörü / Pro-apoptotik", "status": "Araştırma Aşaması" },
    "PDCD1": { "drug": "Pembrolizumab", "mechanism": "Anti-PD-1 Checkpoint Blokajı", "status": "FDA Onaylı" },
    "CD274": { "drug": "Atezolizumab", "mechanism": "Anti-PD-L1 Checkpoint Blokajı", "status": "FDA Onaylı" },
    "CD44": { "drug": "RG7356", "mechanism": "Anti-CD44 Monoklonal Antikor", "status": "Klinik Deneme (Faz I)" },
    "MMP2": { "drug": "Marimastat", "mechanism": "Geniş Spektrumlu MMP İnhibitörü", "status": "Tarihsel Referans" },
    "MMP9": { "drug": "Marimastat", "mechanism": "Geniş Spektrumlu MMP İnhibitörü", "status": "Tarihsel Referans" }
  };

  const matchedTargets = [];

  results.forEach(path => {
    path.overlap_genes.forEach(gene => {
      const gUpper = gene.toUpperCase();
      if (DRUGGABLE_DOWNSTREAM_CATALOG[gUpper]) {
        // Avoid duplicate listings of the same gene-drug pair
        const isListed = matchedTargets.some(m => m.gene === gUpper);
        if (!isListed) {
          const match = DRUGGABLE_DOWNSTREAM_CATALOG[gUpper];
          matchedTargets.push({
            gene: gUpper,
            pathway: path.name,
            drug: match.drug,
            mechanism: match.mechanism,
            status: match.status
          });
        }
      }
    });
  });

  if (matchedTargets.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">Yolaklarda druggable downstream hedef eşleşmesi bulunamadı.</td></tr>`;
    return;
  }

  matchedTargets.forEach(target => {
    const tr = document.createElement('tr');
    tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.03);';
    tr.innerHTML = `
      <td style="padding:12px 16px; font-weight:700; color:#00d4ff;">🎯 ${escapeHtml(target.gene)}</td>
      <td style="padding:12px 16px; color:var(--text-muted); font-size:0.85rem;">${escapeHtml(target.pathway)}</td>
      <td style="padding:12px 16px; font-weight:700; color:var(--text);">💊 ${escapeHtml(target.drug)}</td>
      <td style="padding:12px 16px; font-size:0.8rem; color:var(--text-dim);">${escapeHtml(target.mechanism)}</td>
      <td style="padding:12px 16px;"><span style="background:rgba(255,255,255,0.05); color:var(--accent); padding:2px 8px; border-radius:100px; font-size:0.7rem; font-weight:bold; border:1px solid rgba(0,212,255,0.2);">${escapeHtml(target.status)}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

// ── NEW PROFESSIONAL CELL-CELL SIGNALING FUNCTIONS ──

function renderSignalingHeatmap(activeCTs, pairData, ctColors) {
  const wrapper = document.getElementById('signaling-heatmap-wrapper');
  if (!wrapper) return;
  wrapper.innerHTML = '';

  const table = document.createElement('table');
  table.className = 'sig-heatmap-table';

  // Find max value for color scaling
  let maxVal = 0.0001;
  activeCTs.forEach(a => {
    activeCTs.forEach(b => {
      const val = pairData[`${a}->${b}`] || 0;
      if (val > maxVal) maxVal = val;
    });
  });

  // Create Header Row (Columns = Receivers)
  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  
  // Top-left corner cell
  const cornerCell = document.createElement('th');
  cornerCell.className = 'sig-heatmap-corner';
  cornerCell.innerHTML = 'Sender (Ligand) ➔<br>▼ Receiver (Receptor)';
  cornerCell.style.writingMode = 'horizontal-tb';
  cornerCell.style.transform = 'none';
  headerRow.appendChild(cornerCell);

  activeCTs.forEach(ct => {
    const th = document.createElement('th');
    th.className = 'sig-heatmap-label-y';
    th.textContent = ct;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  // Create Body Rows (Rows = Senders)
  const tbody = document.createElement('tbody');
  activeCTs.forEach(sender => {
    const tr = document.createElement('tr');
    
    // Row Label (Sender)
    const labelTd = document.createElement('td');
    labelTd.className = 'sig-heatmap-label-x';
    labelTd.textContent = sender;
    labelTd.style.borderLeft = `4px solid ${ctColors[sender] || 'var(--border)'}`;
    tr.appendChild(labelTd);

    // Cells
    activeCTs.forEach(receiver => {
      const td = document.createElement('td');
      td.className = 'sig-heatmap-cell';
      const val = pairData[`${sender}->${receiver}`] || 0;
      td.textContent = val > 0 ? val.toFixed(3) : '0';

      // Color intensity based on value
      const intensity = val / maxVal;
      // Beautiful dark mode gradient
      td.style.backgroundColor = val > 0 
        ? `rgba(0, 212, 255, ${0.05 + intensity * 0.75})` 
        : 'rgba(255, 255, 255, 0.01)';
      td.style.color = intensity > 0.5 ? '#020509' : 'var(--text)';
      if (val > 0 && intensity > 0.5) {
        td.style.fontWeight = 'bold';
      }

      // Tooltip listener
      td.addEventListener('mouseover', (e) => {
        showChordTooltip(e, `
          <strong>Gönderici (Sender):</strong> ${escapeHtml(sender)}<br>
          <strong>Alıcı (Receiver):</strong> ${escapeHtml(receiver)}<br>
          <strong>İletişim Skoru:</strong> ${val.toFixed(5)}
        `);
      });
      td.addEventListener('mousemove', (e) => {
        moveChordTooltip(e);
      });
      td.addEventListener('mouseout', () => {
        hideChordTooltip();
      });

      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrapper.appendChild(table);
}

function populateSignalingStatsTable(pairData, activeCTs) {
  const tbody = document.getElementById('signaling-stats-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  const interactions = [];
  activeCTs.forEach(a => {
    activeCTs.forEach(b => {
      const val = pairData[`${a}->${b}`] || 0;
      if (val > 0) {
        interactions.push({ sender: a, receiver: b, score: val });
      }
    });
  });

  // Sort descending
  interactions.sort((a, b) => b.score - a.score);

  if (interactions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">Seçilen hücre tipleri arasında aktif iletişim skoru bulunamadı.</td></tr>`;
    return;
  }

  // Find max value to assign star markers
  const maxScore = interactions[0].score;

  interactions.forEach(inter => {
    const tr = document.createElement('tr');
    tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.015);';

    // Significance star representation
    let stars = '';
    if (inter.score > maxScore * 0.75) {
      stars = '<span style="color:#f2c94c; font-weight:bold;">★★★</span> <span style="font-size:0.75rem; color:#f2c94c;">(Kritik)</span>';
    } else if (inter.score > maxScore * 0.4) {
      stars = '<span style="color:#00d4ff; font-weight:bold;">★★</span> <span style="font-size:0.75rem; color:#00d4ff;">(Yüksek)</span>';
    } else if (inter.score > maxScore * 0.1) {
      stars = '<span style="color:#a78bfa; font-weight:bold;">★</span> <span style="font-size:0.75rem; color:#a78bfa;">(Orta)</span>';
    } else {
      stars = '<span style="color:var(--text-muted); font-size:0.75rem;">Zayıf</span>';
    }

    tr.innerHTML = `
      <td style="padding:10px 16px; font-weight:600;">${escapeHtml(inter.sender)}</td>
      <td style="padding:10px 4px; text-align:center;" class="sig-arrow">➔</td>
      <td style="padding:10px 16px; font-weight:600; color:var(--text-dim);">${escapeHtml(inter.receiver)}</td>
      <td style="padding:10px 16px; text-align:right; font-family:var(--mono); font-weight:700; color:#00d4ff;">${inter.score.toFixed(5)}</td>
      <td style="padding:10px 16px; text-align:center;">${stars}</td>
    `;
    tbody.appendChild(tr);
  });
}

function exportSignalingToCSV() {
  const data = state.gnnData;
  if (!data) return;

  const commData = data.cell_cell_communication || {};
  const lrSelect = document.getElementById('signaling-lr-select');
  if (!lrSelect) return;
  
  const lrPair = lrSelect.value;
  if (!lrPair || !commData[lrPair]) return;

  const pairData = commData[lrPair];
  const checkboxes = document.querySelectorAll('#signaling-ct-checkboxes input[type="checkbox"]');
  const activeCTs = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);

  const csvRows = [['Sender', 'Receiver', 'CommunicationScore']];

  activeCTs.forEach(a => {
    activeCTs.forEach(b => {
      const val = pairData[`${a}->${b}`] || 0;
      csvRows.push([a, b, val.toString()]);
    });
  });

  const csvContent = csvRows.map(e => e.map(val => `"${val.replace(/"/g, '""')}"`).join(",")).join("\n");
  
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute("download", `glio_signaling_strength_${lrPair}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

