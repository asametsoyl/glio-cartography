/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — Analytics & Reports (renderer)
   ══════════════════════════════════════════════════════════ */

/* global state, api, showWarningToast, showErrorToast, showExportSuccessToast, isPathSafe */

// Local helper to ensure path safety check is always available
function isPathSafeLocal(p) {
  if (typeof isPathSafe === 'function') {
    return isPathSafe(p);
  }
  if (typeof p !== 'string' || p.trim() === '') return false;
  // Deny relative path traversal sequences
  if (p.includes('..') || p.includes('./') || p.includes('.\\')) return false;
  return true;
}

// ══════════════════════════════════════════════════════════════
// 4.2 — COHORT SURVIVAL INTERACTION (TCGA / CGGA / COMBINED)
// ══════════════════════════════════════════════════════════════
async function setKmCohort(cohort) {
  // Update button classes
  document.querySelectorAll('.btn-cohort').forEach(btn => btn.classList.remove('active'));
  const activeBtn = document.getElementById(`btn-cohort-${cohort}`);
  if (activeBtn) activeBtn.classList.add('active');
  
  if (!state.kmData) return;
  let cData = null;
  if (state.kmData[cohort]) {
    cData = state.kmData[cohort];
  } else if (state.kmData.estimated_median_os_high_months !== undefined) {
    cData = state.kmData;
  } else {
    return;
  }
  
  // Transition fade effect on elements
  const elementsToFade = ['km-plot-img', 'km-stat-high-os', 'km-stat-low-os', 'km-stat-delta', 'km-stat-ref', 'km-stat-high-spots', 'km-stat-low-spots'];
  elementsToFade.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.transition = 'all 0.15s cubic-bezier(0.16, 1, 0.3, 1)';
      el.style.opacity = '0.3';
      el.style.transform = 'translateY(2px)';
    }
  });

  setTimeout(async () => {
    // Update texts safely
    const kmHighOs = document.getElementById('km-stat-high-os');
    if (kmHighOs) {
      kmHighOs.textContent = cData.estimated_median_os_high_months !== undefined
        ? `${cData.estimated_median_os_high_months.toFixed(1)} ay`
        : 'N/A';
    }
    
    const kmLowOs = document.getElementById('km-stat-low-os');
    if (kmLowOs) {
      kmLowOs.textContent = cData.estimated_median_os_low_months !== undefined
        ? `${cData.estimated_median_os_low_months.toFixed(1)} ay`
        : 'N/A';
    }
    
    const kmDelta = document.getElementById('km-stat-delta');
    if (kmDelta) {
      if (cData.estimated_median_os_low_months !== undefined && cData.estimated_median_os_high_months !== undefined) {
        const delta = cData.estimated_median_os_low_months - cData.estimated_median_os_high_months;
        kmDelta.textContent = `+${delta.toFixed(1)} ay`;
      } else {
        kmDelta.textContent = 'N/A';
      }
    }
    
    const kmRef = document.getElementById('km-stat-ref');
    if (kmRef) {
      kmRef.textContent = cData.reference || '—';
    }
    
    const kmHighSpots = document.getElementById('km-stat-high-spots');
    if (kmHighSpots) {
      kmHighSpots.textContent = window.i18n.t('results.high_risk_spots_summary', { count: cData.n_high_risk_spots ?? 0, avg: (cData.mean_risk_score_high ?? 0).toFixed(2) });
    }
    
    const kmLowSpots = document.getElementById('km-stat-low-spots');
    if (kmLowSpots) {
      kmLowSpots.textContent = window.i18n.t('results.low_risk_spots_summary', { count: cData.n_low_risk_spots ?? 0, avg: (cData.mean_risk_score_low ?? 0).toFixed(2) });
    }
    
    let imgPath = `${state.outputDir}/publication_figures/fig_kaplan_meier_${cohort}.png`;
    if (isPathSafeLocal(imgPath)) {
      let exists = await api.fileExists(imgPath);
      if (!exists) {
        imgPath = `${state.outputDir}/publication_figures/fig_kaplan_meier.png`;
        exists = await api.fileExists(imgPath);
      }
      
      const imgEl = document.getElementById('km-plot-img');
      if (imgEl) {
        if (exists && isPathSafeLocal(imgPath)) {
          imgEl.src = `local://${encodeURI(imgPath)}?t=${Date.now()}`;
        } else {
          imgEl.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
        }
      }
    }

    elementsToFade.forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.style.transition = 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)';
        el.style.opacity = '1';
        el.style.transform = 'translateY(0)';
      }
    });
  }, 150);
}

async function zoomKmPlot() {
  if (!state.outputDir) return;
  const activeBtn = document.querySelector('.btn-cohort.active');
  const cohort = activeBtn ? activeBtn.id.replace('btn-cohort-', '') : 'combined';
  let imgPath = `${state.outputDir}/publication_figures/fig_kaplan_meier_${cohort}.png`;
  
  if (!isPathSafeLocal(imgPath)) {
    showWarningToast(window.i18n.t('pipeline.warn_unsafe_paths'));
    return;
  }
  
  const hasSpecific = await api.fileExists(imgPath);
  if (!hasSpecific) {
    imgPath = `${state.outputDir}/publication_figures/fig_kaplan_meier.png`;
    if (!isPathSafeLocal(imgPath)) {
      showWarningToast(window.i18n.t('pipeline.warn_unsafe_paths'));
      return;
    }
  }
  
  api.openOutputFolder(imgPath);
}

async function loadFigures() {
  if (!state.outputDir) { showWarningToast(window.i18n.t('results.warn_run_analysis_first')); return; }

  // Load KM summary and set default view
  try {
    const summary = await api.backendRequest(`/results/summary?output_dir=${encodeURIComponent(state.outputDir)}`, 'GET', {});
    if (summary && summary.kaplan_meier) {
      state.kmData = summary.kaplan_meier;
      const card = document.getElementById('km-calibration-card');
      if (card) card.classList.remove('hidden');
      await setKmCohort('combined');
    }
  } catch (e) {
    console.error("Kaplan-Meier özeti yüklenemedi:", e);
  }

  // Load figures gallery
  try {
    const res = await api.backendRequest(`/results/figures?output_dir=${encodeURIComponent(state.outputDir)}`, 'GET', {});
    const gallery = document.getElementById('figures-gallery');
    if (!gallery) return;
    gallery.innerHTML = '';

    if (!res || !res.figures || res.figures.length === 0) {
      const placeholder = document.createElement('div');
      placeholder.className = 'gallery-placeholder';
      const p = document.createElement('p');
      p.textContent = window.i18n.t('figures.no_figures_found');
      placeholder.appendChild(p);
      gallery.appendChild(placeholder);
      return;
    }

  // İnsan okunabilir figür isimleri
  const FIGURE_LABELS = {
    'fig2_dominant_celltype_map':   window.i18n.t('figures.dominant_celltype_map'),
    'fig2_volcano_necrosis_vs_edge':window.i18n.t('figures.volcano_necrosis_vs_edge'),
    'fig3_tme_composition':         window.i18n.t('figures.tme_composition'),
    'GNN_confusion_matrix':         window.i18n.t('figures.gnn_confusion_matrix'),
    'training_history_v3':          window.i18n.t('figures.gnn_training_history'),
    'fig1_zone_stacked_bars':       window.i18n.t('figures.zone_stacked_bars'),
    'fig3_bipartite_network':       window.i18n.t('figures.bipartite_network'),
    'fig_drug_score_map':           window.i18n.t('figures.drug_score_map'),
    'fig_kaplan_meier':             window.i18n.t('figures.kaplan_meier'),
    'fig_lr_communication':         window.i18n.t('figures.lr_communication'),
    'fig_risk_map':                 window.i18n.t('figures.risk_map'),
    'fig_spatial_zone_map':         window.i18n.t('figures.spatial_zone_map')
  };

  const FIGURE_ICONS = {
    'fig2_dominant_celltype_map':    '🧬',
    'fig2_volcano_necrosis_vs_edge': '🌋',
    'fig3_tme_composition':          '🥧',
    'GNN_confusion_matrix':          '🤖',
    'training_history_v3':           '📈',
    'fig1_zone_stacked_bars':        '📊',
    'fig3_bipartite_network':        '🕸️',
    'fig_drug_score_map':            '💊',
    'fig_kaplan_meier':              '⏳',
    'fig_lr_communication':          '📡',
    'fig_risk_map':                  '⚠️',
    'fig_spatial_zone_map':          '🗺️',
  };

  const PLACEHOLDER_SVG = `data:image/svg+xml,${encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="200" height="130" viewBox="0 0 200 130">
      <rect width="200" height="130" fill="%230d1117"/>
      <text x="100" y="55" text-anchor="middle" fill="%23334155" font-size="28">🖼️</text>
      <text x="100" y="82" text-anchor="middle" fill="%23475569" font-size="11" font-family="sans-serif">Analiz tamamlandığında</text>
      <text x="100" y="96" text-anchor="middle" fill="%23475569" font-size="11" font-family="sans-serif">görüntü yüklenir</text>
    </svg>
  `)}`;

    const fragment = document.createDocumentFragment();
    res.figures.forEach(fig => {
      // Hide cohort-specific figures from listing in the general gallery
      if (fig.name.startsWith('fig_kaplan_meier_')) return;
      
      const item = document.createElement('div');
      item.className = 'fig-item';
      item.title = FIGURE_LABELS[fig.name] || fig.name.replace(/_/g, ' ');
      
      const img = document.createElement('img');
      // Don't set src immediately — check existence first to avoid ERR_FILE_NOT_FOUND
      img.alt = fig.name;
      img.loading = 'lazy';
      img.style.background = 'rgba(0,0,0,0.3)';
      // Graceful error fallback — no console error spam
      img.onerror = () => {
        img.onerror = null; // prevent infinite loop
        img.src = PLACEHOLDER_SVG;
        img.style.opacity = '0.5';
        item.style.cursor = 'default';
        item.title = `${item.title} (${window.i18n.t('figures.analysis_incomplete')})`;
      };
      // Set src after binding onerror
      img.src = `local://${encodeURI(fig.path)}?t=${Date.now()}`;

      const icon = FIGURE_ICONS[fig.name] || '📄';
      const label = FIGURE_LABELS[fig.name] || fig.name.replace(/_/g, ' ');
      
      const nameEl = document.createElement('div');
      nameEl.className = 'fig-item-name';
      nameEl.innerHTML = `<span style="margin-right:5px;">${icon}</span>${label}`;
      
      item.appendChild(img);
      item.appendChild(nameEl);
      
      item.addEventListener('click', () => {
        if (isPathSafeLocal(fig.path)) {
          api.openOutputFolder(fig.path);
        } else {
          showWarningToast(window.i18n.t('pipeline.warn_unsafe_paths'));
        }
      });
      
      fragment.appendChild(item);
    });
    gallery.appendChild(fragment);
  } catch (e) {
    console.error("Figürler yüklenemedi:", e);
    showErrorToast(`Figürler yüklenemedi: ${e.message || e}`);
  }
}

async function loadReport() {
  if (!state.outputDir) { showWarningToast(window.i18n.t('results.warn_run_analysis_first')); return; }

  const patientIdInput = document.getElementById('patient-id');
  const patientId = patientIdInput ? patientIdInput.value.trim() : 'Patient_A';
  const safePatientId = patientId.replace(/[^a-zA-Z0-9_\-]/g, '_');
  
  const htmlPath = `${state.outputDir}/reports/Klinik_Rapor_${safePatientId}.html`;
  
  if (!isPathSafeLocal(htmlPath)) {
    showWarningToast(window.i18n.t('pipeline.warn_unsafe_paths'));
    return;
  }

  const exists = await api.fileExists(htmlPath);
  const wrapper = document.getElementById('report-frame-wrapper');
  if (!wrapper) return;

  if (!exists) {
    wrapper.innerHTML = '';
    const placeholder = document.createElement('div');
    placeholder.className = 'gallery-placeholder';
    const p = document.createElement('p');
    p.textContent = window.i18n.t('report.not_generated');
    placeholder.appendChild(p);
    wrapper.appendChild(placeholder);
    return;
  }

  wrapper.innerHTML = '';
  const iframe = document.createElement('iframe');
  iframe.src = `local://${encodeURI(htmlPath)}?t=${Date.now()}`;
  iframe.title = 'Klinik Rapor';
  iframe.sandbox = 'allow-same-origin allow-scripts';
  wrapper.appendChild(iframe);
}

async function openReport() {
  if (!state.outputDir) { showWarningToast(window.i18n.t('results.warn_run_analysis_first')); return; }

  const patientIdInput = document.getElementById('patient-id');
  const patientId = patientIdInput ? patientIdInput.value.trim() : 'Patient_A';
  const safePatientId = patientId.replace(/[^a-zA-Z0-9_\-]/g, '_');

  const pdfPath  = `${state.outputDir}/reports/Klinik_Rapor_${safePatientId}.pdf`;
  const htmlPath = `${state.outputDir}/reports/Klinik_Rapor_${safePatientId}.html`;

  if (!isPathSafeLocal(pdfPath) || !isPathSafeLocal(htmlPath)) {
    showWarningToast(window.i18n.t('pipeline.warn_unsafe_paths'));
    return;
  }

  const hasPDF  = await api.fileExists(pdfPath);
  const hasHTML = await api.fileExists(htmlPath);

  if (hasPDF) {
    api.openOutputFolder(pdfPath);
  } else if (hasHTML) {
    api.openOutputFolder(htmlPath);
  } else {
    showWarningToast(window.i18n.t('report.not_found'));
  }
}

async function exportReportPDF() {
  const wrapper = document.getElementById('report-frame-wrapper');
  if (!wrapper) return;
  const iframe = wrapper.querySelector('iframe');
  if (!iframe) {
    showWarningToast(window.i18n.t('report.not_found'));
    return;
  }

  try {
    const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
    if (!iframeDoc) {
      showErrorToast("Rapor içeriğine erişilemedi.");
      return;
    }

    // 1. Clone DOM
    const clone = iframeDoc.documentElement.cloneNode(true);

    // 2. Read notes from textarea outside
    const notesArea = document.getElementById('report-physician-notes');
    const notesValue = notesArea ? notesArea.value.trim() : '';

    if (notesValue) {
      // Find a suitable place to append notes
      const notesContainer = iframeDoc.createElement('div');
      notesContainer.className = 'physician-notes-print-block';
      notesContainer.setAttribute('style', 'margin-top: 40px; padding: 15px; border: 1.5px solid #a5b4fc; border-radius: 6px; background-color: rgba(255,255,255,0.01); page-break-inside: avoid;');
      
      const title = iframeDoc.createElement('h3');
      title.setAttribute('style', 'margin-top: 0; color: #a5b4fc; font-size: 16px; border-bottom: 1px solid #1f2937; padding-bottom: 6px;');
      title.textContent = window.i18n.t('report.physician_notes') || 'Hekim Klinik Notları';
      
      const body = iframeDoc.createElement('p');
      body.setAttribute('style', 'white-space: pre-wrap; font-size: 13px; color: #f3f4f6; margin-bottom: 0; line-height: 1.5;');
      body.textContent = notesValue;

      notesContainer.appendChild(title);
      notesContainer.appendChild(body);

      const cloneBody = clone.querySelector('body');
      if (cloneBody) {
        cloneBody.appendChild(notesContainer);
      }
    }

    // Remove buttons or print-avoiding elements inside report
    const noPrint = clone.querySelectorAll('.no-print, button, input[type="button"]');
    noPrint.forEach(el => el.remove());

    // 3. Replace any textareas inside the clone with static content
    const textareas = clone.querySelectorAll('textarea');
    textareas.forEach(ta => {
      const div = iframeDoc.createElement('div');
      div.setAttribute('style', 'white-space: pre-wrap; font-family: inherit; font-size: 13px; color: #f3f4f6; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px;');
      div.textContent = ta.value;
      ta.parentNode.replaceChild(div, ta);
    });

    // 4. Inline CSS variables for print fidelity
    const cssVarMap = {
      '--bg-deep': '#020509',
      '--bg-dark': '#0b1120',
      '--text': '#f3f4f6',
      '--text-muted': '#9ca3af',
      '--main': '#00ffcc',
      '--border': '#1f2937',
      '--accent': '#7c3aed'
    };
    const elements = clone.querySelectorAll('*');
    elements.forEach(el => {
      let styleAttr = el.getAttribute('style');
      if (styleAttr) {
        Object.entries(cssVarMap).forEach(([vName, vVal]) => {
          styleAttr = styleAttr.replace(new RegExp(`var\\(${vName}\\)`, 'g'), vVal);
        });
        el.setAttribute('style', styleAttr);
      }
    });

    // 5. Serialize
    const htmlContent = '<!DOCTYPE html>\n' + clone.outerHTML;

    showInfoToast(window.i18n.t('report.generate_pdf') || "PDF oluşturuluyor...");
    const res = await api.printReportToPDF(htmlContent);
    if (res && res.success) {
      showExportSuccessToast(window.i18n.t('state.export_success') || "✅ Rapor PDF olarak başarıyla kaydedildi!");
    } else if (res && res.canceled) {
      showInfoToast(window.i18n.t('state.export_canceled') || "PDF kaydetme iptal edildi.");
    }
  } catch (e) {
    console.error("PDF export failed:", e);
    showErrorToast(`PDF Dışa Aktarma Başarısız: ${e.message || e}`);
  }
}

async function openOutputFolder() {
  if (!state.outputDir) return;
  if (!isPathSafeLocal(state.outputDir)) {
    showWarningToast(window.i18n.t('pipeline.warn_unsafe_paths'));
    return;
  }
  api.openOutputFolder(state.outputDir);
}

// ══════════════════════════════════════════════════════════════
// 4.4 — DEKONVOLÜSYON KALİTE PANELİ
// ══════════════════════════════════════════════════════════════
async function loadDeconvQuality() {
  if (!state.outputDir) { showWarningToast(window.i18n.t('results.warn_run_analysis_first')); return; }

  try {
    const q = await api.backendRequest(
      `/results/deconv-quality?output_dir=${encodeURIComponent(state.outputDir)}`, 'GET', {}
    );

    const placeholder = document.getElementById('quality-placeholder');
    if (placeholder) placeholder.classList.add('hidden');
    
    const content = document.getElementById('quality-content');
    if (content) content.classList.remove('hidden');

    // Grade card styling & verification
    const colorRegex = /^#[0-9A-Fa-f]{3,8}$/;
    const safeColor = colorRegex.test(q.quality_color) ? q.quality_color : 'var(--accent)';

    const circle = document.getElementById('grade-circle');
    if (circle) {
      circle.textContent = q.quality_grade || '—';
      circle.style.background = `conic-gradient(${safeColor} 0%, ${safeColor}33 100%)`;
      circle.style.color = safeColor;
      circle.style.borderColor = safeColor;
      circle.style.boxShadow = `0 0 20px ${safeColor}55`;
    }

    const gradeLabel = document.getElementById('grade-label');
    if (gradeLabel) {
      gradeLabel.textContent = q.quality_label || '—';
      gradeLabel.style.color = safeColor;
    }

    const confidence = document.getElementById('qm-confidence');
    if (confidence) {
      confidence.textContent = q.avg_confidence !== undefined ? `%${q.avg_confidence}` : '—';
    }

    const entropy = document.getElementById('qm-entropy');
    if (entropy) {
      entropy.textContent = q.avg_entropy !== undefined ? q.avg_entropy.toFixed(4) : '—';
    }

    const types = document.getElementById('qm-types');
    if (types) {
      types.textContent = q.n_cell_types !== undefined ? q.n_cell_types.toString() : '—';
    }

    // Cell type table with safe DOM APIs
    const tbody = document.getElementById('ct-quality-tbody');
    if (tbody) {
      tbody.innerHTML = '';
      if (q.cell_type_table && q.cell_type_table.length > 0) {
        const fragment = document.createDocumentFragment();
        const maxProp = Math.max(...q.cell_type_table.map(r => r.mean_prop || 0), 1);
        
        q.cell_type_table.forEach((row, idx) => {
          const tr = document.createElement('tr');

          const nameTd = document.createElement('td');
          nameTd.textContent = row.name || '—';
          tr.appendChild(nameTd);

          const propTd = document.createElement('td');
          propTd.style.fontFamily = 'var(--mono)';
          propTd.textContent = `${(row.mean_prop || 0).toFixed(2)}%`;
          tr.appendChild(propTd);

          const domTd = document.createElement('td');
          domTd.style.fontFamily = 'var(--mono)';
          domTd.textContent = row.dominant_spots?.toString() || '0';
          tr.appendChild(domTd);

          const barTd = document.createElement('td');
          const barContainer = document.createElement('div');
          barContainer.style.background = 'var(--bg-raised)';
          barContainer.style.borderRadius = '4px';
          barContainer.style.height = '8px';
          barContainer.style.width = '120px';

          const barFill = document.createElement('div');
          const barW = Math.round(((row.mean_prop || 0) / maxProp) * 100);
          const hue = Math.round((idx * 137) % 360);
          barFill.style.background = `hsl(${hue},70%,55%)`;
          barFill.style.height = '100%';
          barFill.style.borderRadius = '4px';
          barFill.style.width = `${barW}%`;
          barFill.style.transition = 'width 0.5s';

          barContainer.appendChild(barFill);
          barTd.appendChild(barContainer);
          tr.appendChild(barTd);

          fragment.appendChild(tr);
        });
        tbody.appendChild(fragment);
      }
    }
  } catch (e) {
    showErrorToast(`Kalite verisi yüklenemedi: ${e.message || e}`);
  }
}

// ══════════════════════════════════════════════════════════════
// 4.9 — GNN MODEL BİLGİSİ PANELİ
// ══════════════════════════════════════════════════════════════
function appendRow(tbody, label, value) {
  const tr = document.createElement('tr');
  
  const labelTd = document.createElement('td');
  labelTd.style.color = 'var(--text-muted)';
  labelTd.style.padding = '6px 12px';
  labelTd.textContent = label;
  
  const valueTd = document.createElement('td');
  valueTd.style.fontFamily = 'var(--mono)';
  valueTd.style.fontWeight = '600';
  valueTd.style.padding = '6px 12px';
  valueTd.textContent = value;
  
  tr.appendChild(labelTd);
  tr.appendChild(valueTd);
  tbody.appendChild(tr);
}

async function loadGnnModel() {
  if (!state.outputDir) { showWarningToast(window.i18n.t('results.warn_run_analysis_first')); return; }

  try {
    const m = await api.backendRequest(
      `/results/gnn-model?output_dir=${encodeURIComponent(state.outputDir)}`, 'GET', {}
    );

    const placeholder = document.getElementById('model-placeholder');
    if (placeholder) placeholder.classList.add('hidden');
    
    const content = document.getElementById('model-content');
    if (content) content.classList.remove('hidden');

    // File info
    const fileTbody = document.getElementById('model-file-tbody');
    if (fileTbody) {
      fileTbody.innerHTML = '';
      appendRow(fileTbody, 'Dosya', m.model_file || '—');
      appendRow(fileTbody, 'Boyut', m.model_size_mb ? `${m.model_size_mb} MB` : 'N/A');
      appendRow(fileTbody, window.i18n.t('model.spots_count'), m.output?.n_spots !== undefined ? m.output.n_spots.toLocaleString() : '0');
      appendRow(fileTbody, window.i18n.t('model.zones_count'), m.output?.zones !== undefined ? m.output.zones.length.toString() : '0');
      appendRow(fileTbody, window.i18n.t('model.cell_types_count'), m.output?.ct_names !== undefined ? m.output.ct_names.length.toString() : '0');
    }

    // Architecture
    const arch = m.architecture;
    const archTbody = document.getElementById('model-arch-tbody');
    if (arch && archTbody) {
      archTbody.innerHTML = '';
      
      const lr = arch.learning_rate;
      const lrDisplay = (typeof lr === 'number') ? (lr < 0.001 ? lr.toExponential(3) : lr.toString()) : 'N/A';
      
      appendRow(archTbody, 'Hidden Dim', arch.hidden_dim !== undefined ? arch.hidden_dim.toString() : '—');
      appendRow(archTbody, 'Attention Heads', arch.attention_heads !== undefined ? arch.attention_heads.toString() : '—');
      appendRow(archTbody, window.i18n.t('model.gat_layers'), arch.gat_layers !== undefined ? arch.gat_layers.toString() : '—');
      appendRow(archTbody, window.i18n.t('model.sage_layers'), arch.sage_layers !== undefined ? arch.sage_layers.toString() : '—');
      appendRow(archTbody, 'Dropout', arch.dropout !== undefined ? arch.dropout.toString() : '—');
      appendRow(archTbody, 'Learning Rate', lrDisplay);
    }

    // Training
    const trData = m.training;
    const trainTbody = document.getElementById('model-train-tbody');
    if (trData && trainTbody) {
      trainTbody.innerHTML = '';
      appendRow(trainTbody, window.i18n.t('model.epochs_requested'), trData.epochs_requested !== undefined ? trData.epochs_requested.toString() : '—');
      appendRow(trainTbody, window.i18n.t('model.epochs_trained'), trData.epochs_trained !== undefined ? trData.epochs_trained.toString() : '—');
      appendRow(trainTbody, 'Patience', trData.patience !== undefined ? trData.patience.toString() : '—');
      appendRow(trainTbody, window.i18n.t('model.best_val_loss'), trData.best_val_loss !== undefined ? trData.best_val_loss.toFixed(6) : '—');
      appendRow(trainTbody, 'Test MSE', trData.test_mse !== undefined ? trData.test_mse.toFixed(6) : '—');
      appendRow(trainTbody, 'Optuna', trData.optuna_used ? '✅ ' + window.i18n.t('model.optuna_used') : '⬜ ' + window.i18n.t('model.optuna_unused'));
    }

    // Correlations
    const ctbody = document.getElementById('model-corr-tbody');
    if (ctbody && m.correlations) {
      ctbody.innerHTML = '';
      const fragment = document.createDocumentFragment();
      for (const [ct, vals] of Object.entries(m.correlations)) {
        const pr = vals.pearson_r;
        const sig = Math.abs(pr) > 0.7 ? '🟢 ' + window.i18n.t('model.sig_strong') : Math.abs(pr) > 0.5 ? '🟡 ' + window.i18n.t('model.sig_medium') : '🔴 ' + window.i18n.t('model.sig_weak');
        
        const tr = document.createElement('tr');
        
        const ctTd = document.createElement('td');
        ctTd.textContent = ct;
        tr.appendChild(ctTd);
        
        const prTd = document.createElement('td');
        prTd.style.fontFamily = 'var(--mono)';
        prTd.textContent = pr !== undefined ? pr.toFixed(4) : '—';
        tr.appendChild(prTd);
        
        const srTd = document.createElement('td');
        srTd.style.fontFamily = 'var(--mono)';
        srTd.textContent = vals.spearman_r !== undefined ? vals.spearman_r.toFixed(4) : '—';
        tr.appendChild(srTd);
        
        const sigTd = document.createElement('td');
        sigTd.textContent = sig;
        tr.appendChild(sigTd);
        
        fragment.appendChild(tr);
      }
      ctbody.appendChild(fragment);
    }
  } catch (e) {
    showErrorToast(window.i18n.t('profiles.load_error') + ': ' + (e.message || e));
  }
}

// ══════════════════════════════════════════════════════════════
// 4.10 — KLİNİK VERİ DIŞA AKTARMA (H5AD, CSV, ZIP)
// ══════════════════════════════════════════════════════════════

// Local helper to avoid repetitive button-loading states and lock concurrent clicks
const exportLocks = new Map();

async function runExport(type, endpoint, buttonOrEl, loadingText) {
  if (!state.outputDir) {
    showWarningToast('Önce bir analiz çalıştırın.');
    return;
  }
  if (!isPathSafeLocal(state.outputDir)) {
    showWarningToast('Güvenli olmayan çıktı klasör yolu.');
    return;
  }

  // Prevent duplicate concurrent exports
  if (exportLocks.get(type)) return;
  exportLocks.set(type, true);

  const btn = (typeof buttonOrEl === 'string') ? document.querySelector(buttonOrEl) : buttonOrEl;
  const originalText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.innerHTML = loadingText;
    btn.disabled = true;
  }

  const patientIdInput = document.getElementById('patient-id');
  const patientId = patientIdInput ? patientIdInput.value.trim() : 'Patient_A';
  const safePatientId = patientId.replace(/[^a-zA-Z0-9_\-]/g, '_');

  try {
    const res = await api.backendRequest(
      `/results/${endpoint}?output_dir=${encodeURIComponent(state.outputDir)}&patient_id=${encodeURIComponent(safePatientId)}`,
      'GET',
      {}
    );
    if (res && res.status === 'ok') {
      showExportSuccessToast(res.filename || 'Dosya başarıyla dışa aktarıldı');
      if (res.path && isPathSafeLocal(res.path)) {
        api.openOutputFolder(res.path);
      }
    } else {
      showErrorToast(`${type.toUpperCase()} dışa aktarma başarısız oldu.`);
    }
  } catch (e) {
    showErrorToast(window.i18n.t('common.export') + ' ' + window.i18n.t('common.error').toLowerCase() + ': ' + (e.message || e));
  } finally {
    if (btn) {
      btn.innerHTML = originalText;
      btn.disabled = false;
    }
    exportLocks.set(type, false);
  }
}

async function exportH5ad(btnEl) {
  await runExport('h5ad', 'export-h5ad', btnEl || '#btn-export-h5ad', '🧬 &nbsp; Aktarılıyor...');
}

async function exportSpotsCSV(btnEl) {
  await runExport('csv', 'export-csv', btnEl || '#btn-export-csv', '📊 &nbsp; Aktarılıyor...');
}

async function exportFiguresZIP(btnEl) {
  await runExport('zip', 'export-zip', btnEl || '#btn-export-zip', '🖼️ &nbsp; Paketleniyor...');
}

async function browseMultipatientDir(side) {
  const path = await api.selectFolder();
  if (path) {
    const input = document.getElementById(`mp-dir-${side}`);
    if (input) input.value = path;
  }
}

async function comparePatients() {
  const dirA = (document.getElementById('mp-dir-a')?.value || '').trim();
  const dirB = (document.getElementById('mp-dir-b')?.value || '').trim();
  const resultEl = document.getElementById('mp-compare-result');

  if (!dirA || !dirB) {
    showWarningToast('Lütfen karşılaştırmak için iki hasta dizinini de seçin.');
    return;
  }

  if (resultEl) {
    resultEl.innerHTML = '<div style="text-align:center; padding: 20px; color: var(--accent);">⏳ Analizler karşılaştırılıyor...</div>';
  }

  try {
    const deconvAPath = `${dirA}/deconvolution/deconvolution_summary.json`;
    const deconvBPath = `${dirB}/deconvolution/deconvolution_summary.json`;
    const gnnAPath = `${dirA}/gnn/gnn_summary.json`;
    const gnnBPath = `${dirB}/gnn/gnn_summary.json`;

    const existsDeconvA = await api.fileExists(deconvAPath);
    const existsDeconvB = await api.fileExists(deconvBPath);
    const existsGnnA = await api.fileExists(gnnAPath);
    const existsGnnB = await api.fileExists(gnnBPath);

    if (!existsDeconvA || !existsGnnA) {
      showErrorToast('Hasta A dizininde geçerli analiz sonuçları bulunamadı.');
      resultEl.innerHTML = '<div class="license-error">Hasta A dizininde geçerli analiz sonuçları bulunamadı. Lütfen analizlerin tamamlandığından emin olun.</div>';
      return;
    }
    if (!existsDeconvB || !existsGnnB) {
      showErrorToast('Hasta B dizininde geçerli analiz sonuçları bulunamadı.');
      resultEl.innerHTML = '<div class="license-error">Hasta B dizininde geçerli analiz sonuçları bulunamadı. Lütfen analizlerin tamamlandığından emin olun.</div>';
      return;
    }

    const deconvA = await api.readJsonFile(deconvAPath);
    const deconvB = await api.readJsonFile(deconvBPath);
    const gnnA = await api.readJsonFile(gnnAPath);
    const gnnB = await api.readJsonFile(gnnBPath);

    const patientA = deconvA.patient_id || 'Hasta A';
    const patientB = deconvB.patient_id || 'Hasta B';

    const getRowHtml = (label, valA, valB, formatFn = x => x) => {
      return `
        <tr>
          <td style="color:var(--text-muted); font-weight:500;">${label}</td>
          <td style="font-family:var(--mono); text-align:center;">${formatFn(valA)}</td>
          <td style="font-family:var(--mono); text-align:center;">${formatFn(valB)}</td>
        </tr>
      `;
    };

    const formatPct = val => val ? (val * 100).toFixed(1) + '%' : 'N/A';
    const formatDec = val => val ? val.toFixed(3) : 'N/A';

    let cellTypesHtml = '';
    const allCellTypes = Array.from(new Set([
      ...Object.keys(deconvA.mean_proportions || {}),
      ...Object.keys(deconvB.mean_proportions || {})
    ])).sort();

    allCellTypes.forEach(ct => {
      const propA = deconvA.mean_proportions?.[ct] || 0;
      const propB = deconvB.mean_proportions?.[ct] || 0;
      cellTypesHtml += getRowHtml(ct, propA, propB, formatPct);
    });

    const topLrA = gnnA.top_lr?.[0]?.[0] || 'N/A';
    const topLrAScore = gnnA.top_lr?.[0]?.[1] || 0;
    const topLrB = gnnB.top_lr?.[0]?.[0] || 'N/A';
    const topLrBScore = gnnB.top_lr?.[0]?.[1] || 0;

    const html = `
      <div class="setup-card" style="margin-top:20px; border-color:var(--border-bright);">
        <h4 style="color:var(--accent); font-size:1.1rem; margin-bottom:15px; border-bottom:1px solid var(--border); padding-bottom:8px;">👥 Karşılaştırma Sonuçları: ${patientA} ↔ ${patientB}</h4>
        
        <table class="data-table" style="margin-bottom:20px;">
          <thead>
            <tr>
              <th style="width:40%;">Metrik</th>
              <th style="text-align:center; width:30%;">${patientA}</th>
              <th style="text-align:center; width:30%;">${patientB}</th>
            </tr>
          </thead>
          <tbody>
            ${getRowHtml('Uzamsal Spot Sayısı', deconvA.n_spots, deconvB.n_spots)}
            ${getRowHtml('Dekonvolüsyon Yöntemi', deconvA.deconv_method?.toUpperCase(), deconvB.deconv_method?.toUpperCase())}
            ${getRowHtml('Ortalama Güven Skoru', deconvA.avg_confidence, deconvB.avg_confidence, formatDec)}
            ${getRowHtml('Ortalama Entropi', deconvA.avg_entropy, deconvB.avg_entropy, formatDec)}
            ${getRowHtml('GNN Test MSE', gnnA.test_mse, gnnB.test_mse, formatDec)}
            ${getRowHtml('GNN En İyi Doğrulama Kaybı', gnnA.best_val_loss, gnnB.best_val_loss, formatDec)}
            ${getRowHtml('Dominant Yolak Aktivitesi', gnnA.top_pathway, gnnB.top_pathway)}
            ${getRowHtml('Baskın L-R Etkileşimi', `${topLrA} (${topLrAScore.toFixed(2)})`, `${topLrB} (${topLrBScore.toFixed(2)})`)}
          </tbody>
        </table>

        <h4 style="color:var(--text-dim); font-size:0.95rem; margin-bottom:10px; margin-top:20px;">🧬 Hücre Tipi Kompozisyonları (Ortalama Oranlar)</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th style="width:40%;">Hücre Tipi</th>
              <th style="text-align:center; width:30%;">${patientA}</th>
              <th style="text-align:center; width:30%;">${patientB}</th>
            </tr>
          </thead>
          <tbody>
            ${cellTypesHtml}
          </tbody>
        </table>
      </div>
    `;

    if (resultEl) resultEl.innerHTML = html;
    showToast('Karşılaştırma başarıyla oluşturuldu!', 'success');

  } catch (err) {
    console.error('Multi-patient comparison error:', err);
    showErrorToast(window.i18n.t('cohort.compare_error') + ': ' + err.message);
    if (resultEl) resultEl.innerHTML = `<div class="license-error">${window.i18n.t('cohort.compare_failed')}: ${err.message}</div>`;
  }
}


