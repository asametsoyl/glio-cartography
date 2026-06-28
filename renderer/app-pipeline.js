/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — Pipeline Runner (renderer)
   ══════════════════════════════════════════════════════════ */

/* global state, api, showWarningToast, showErrorToast, showToast, customConfirm, showPanel, loadResults, loadFigures, loadReport, loadDeconvQuality, loadGnnModel, isPathSafe */

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
// PIPELINE
// ══════════════════════════════════════════════════════════════
async function startPipeline() {
  const spatialDir = (document.getElementById('spatial-path')?.value || '').trim();
  const scrnaPath  = (document.getElementById('scrna-path')?.value || '').trim();
  const outputDir  = (document.getElementById('output-path')?.value || '').trim();
  const patientId  = (document.getElementById('patient-id')?.value || 'Patient_A').trim();
  const epochs     = parseInt(document.getElementById('gnn-epochs')?.value) || 100;
  const runOptuna  = document.getElementById('run-optuna')?.checked || false;
  const optunaT    = parseInt(document.getElementById('optuna-trials')?.value) || 10;
  const deconvMethod = document.getElementById('deconv-method')?.value || 'tangram';

  // ── Klinik Metadata (FAZ 1 — JSON payload, env race condition yok) ──
  const clinicalAgeRaw  = document.getElementById('clinical-age')?.value?.trim();
  const clinicalMgmtRaw = document.getElementById('clinical-mgmt')?.value?.trim();
  const clinicalIdhRaw  = document.getElementById('clinical-idh')?.value?.trim();
  const clinicalKpsRaw  = document.getElementById('clinical-kps')?.value?.trim();
  const imputationMode  = document.getElementById('imputation-mode')?.value || 'worst';

  // Boş alanlar null iletilir → backend imputation stratejisine devredilir
  const clinicalAge  = clinicalAgeRaw  ? parseInt(clinicalAgeRaw)   : null;
  const clinicalMgmt = clinicalMgmtRaw ? parseFloat(clinicalMgmtRaw) : null;
  const clinicalIdh  = clinicalIdhRaw  ? parseFloat(clinicalIdhRaw)  : null;
  const clinicalKps  = clinicalKpsRaw  ? parseInt(clinicalKpsRaw)   : null;

  // Validasyon: klinik alanlar girilmişse geçerlilik kontrolü
  if (clinicalAge !== null && (clinicalAge < 0 || clinicalAge > 120)) {
    showWarningToast(window.i18n.t('pipeline.warn_age')); return;
  }
  if (clinicalMgmt !== null && (clinicalMgmt < 0 || clinicalMgmt > 1)) {
    showWarningToast(window.i18n.t('pipeline.warn_mgmt')); return;
  }
  if (clinicalIdh !== null && (clinicalIdh < 0 || clinicalIdh > 1)) {
    showWarningToast(window.i18n.t('pipeline.warn_idh')); return;
  }
  if (clinicalKps !== null && (clinicalKps < 0 || clinicalKps > 100)) {
    showWarningToast(window.i18n.t('pipeline.warn_kps')); return;
  }

  if (!spatialDir) { showWarningToast(window.i18n.t('pipeline.warn_spatial')); return; }
  if (!scrnaPath)  { showWarningToast(window.i18n.t('pipeline.warn_scrna')); return; }
  if (!outputDir)  { showWarningToast(window.i18n.t('pipeline.warn_output')); return; }

  if (!isPathSafeLocal(spatialDir) || !isPathSafeLocal(scrnaPath) || !isPathSafeLocal(outputDir)) {
    showWarningToast(window.i18n.t('pipeline.warn_unsafe_paths'));
    return;
  }

  if (!state.backendReady) {
    showWarningToast(window.i18n.t('pipeline.warn_backend_not_ready'));
    return;
  }

  // Request notification permission if default
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  // Sanitize patientId to prevent path traversal
  const safePatientId = patientId.replace(/[^a-zA-Z0-9_\-]/g, '_').slice(0, 64);

  // Seçilen yolları ve ayarları electron-store'a kaydet (sonraki oturum için)
  try {
    await api.saveLastPaths({
      spatial:        spatialDir,
      scrna:          scrnaPath,
      output:         outputDir,
      patientId:      safePatientId,
      epochs:         epochs,
      runOptuna:      runOptuna,
      optunaTrials:   optunaT,
      deconvMethod:   deconvMethod,
      // Klinik verileri de kaydet (null → boş bırakılmış demek)
      clinicalAge:    clinicalAge,
      clinicalMgmt:   clinicalMgmt,
      clinicalIdh:    clinicalIdh,
      clinicalKps:    clinicalKps,
      imputationMode: imputationMode,
    });
  } catch (_) { /* kayıt hatası kritik değil */ }

  // Switch to monitor
  showPanel('monitor');

  // Reset stages
  resetStages();
  clearLog();
  appendLog(window.i18n.t('pipeline.log_starting'));

  // Klinik meta log
  if (clinicalAge || clinicalMgmt || clinicalIdh || clinicalKps) {
    appendLog(window.i18n.t('pipeline.log_clinical_data', { age: clinicalAge ?? 'auto', mgmt: clinicalMgmt ?? 'auto', idh: clinicalIdh ?? 'auto', kps: clinicalKps ?? 'auto', mode: imputationMode }));
  } else {
    appendLog(window.i18n.t('pipeline.log_clinical_imputation', { strategy: imputationMode === 'median' ? window.i18n.t('clinical.imputation_median') : window.i18n.t('clinical.imputation_worst') }));
  }

  state.pipelineRunning = true;
  state.startTime = Date.now();
  state.outputDir = outputDir;

  const startBtn = document.getElementById('start-btn');
  if (startBtn) startBtn.disabled = true;
  
  const cancelBtn = document.getElementById('cancel-btn');
  if (cancelBtn) cancelBtn.style.display = 'inline-flex';
  
  const returnSetupBtn = document.getElementById('return-setup-btn');
  if (returnSetupBtn) returnSetupBtn.style.display = 'none';

  // Start elapsed timer (clear existing first)
  if (state.elapsedInterval) {
    clearInterval(state.elapsedInterval);
  }
  state.elapsedInterval = setInterval(() => {
    const sec = Math.floor((Date.now() - state.startTime) / 1000);
    const m = String(Math.floor(sec / 60)).padStart(2,'0');
    const s = String(sec % 60).padStart(2,'0');
    const elapsedEl = document.getElementById('elapsed-time');
    if (elapsedEl) elapsedEl.textContent = `⏱ ${m}:${s}`;
  }, 1000);

  // Call backend
  try {
    const res = await api.backendRequest('/pipeline/start', 'POST', {
      spatial_dir:     spatialDir,
      scrna_path:      scrnaPath,
      output_dir:      outputDir,
      patient_id:      safePatientId,
      run_optuna:      runOptuna,
      optuna_trials:   optunaT,
      gnn_epochs:      epochs,
      deconv_method:   deconvMethod,
      // Klinik metadata JSON payload (env yerine — FAZ 1 güvenlik gereksinimi)
      clinical_age:    clinicalAge,
      clinical_mgmt:   clinicalMgmt,
      clinical_idh:    clinicalIdh,
      clinical_kps:    clinicalKps,
      imputation_mode: imputationMode,
      lang:            (window.i18n && window.i18n.lang) || 'tr',
    });
    appendLog(`ℹ️ ${res.message || window.i18n.t('pipeline.log_started_status')}`);
    startPolling();
  } catch (e) {
    appendLog(`❌ ${window.i18n.t('pipeline.log_backend_error')}: ${e.message}`);
    pipelineDone(false);
  }
}


async function cancelPipeline() {
  const isTr = (window.i18n && window.i18n.lang === 'tr');
  const ok = await customConfirm(
    window.i18n.t('pipeline.confirm_cancel_title'),
    window.i18n.t('pipeline.confirm_cancel_desc'),
    isTr ? 'Evet, İptal Et' : 'Yes, Cancel',
    window.i18n.t('common.cancel')
  );
  if (!ok) return;
  
  try {
    await api.backendRequest('/pipeline/cancel', 'POST', {});
    appendLog(window.i18n.t('pipeline.log_cancel_sent'));
  } catch (e) {
    appendLog(`❌ ${window.i18n.t('pipeline.log_cancel_error')}: ${e.message}`);
  }
  pipelineDone(false);
}

let pollErrorCount = 0;
let isPollingActive = false;

function startPolling() {
  // Clear any existing polling intervals first
  if (state.pollInterval) {
    clearInterval(state.pollInterval);
  }
  
  pollErrorCount = 0;
  isPollingActive = false;

  state.pollInterval = setInterval(async () => {
    if (isPollingActive) return; // Prevent concurrent polling calls
    isPollingActive = true;

    try {
      const status = await api.backendRequest(`/pipeline/status`, 'GET', {});
      pollErrorCount = 0; // Reset consecutive error count on success
      
      updateMonitor(status);
      
      if (status.status === 'done') {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
        
        pipelineDone(true);
        // Show summary info
        showPipelineSummary();
        
        // Wait for results to be fully loaded before switching panels to results
        try {
          if (typeof loadResults === 'function') {
            await loadResults();
          }
        } catch (err) {
          console.error("Results load failed:", err);
        }
        
        showPanel('results');
        
        // Load other components in background
        if (typeof loadFigures === 'function') loadFigures();
        if (typeof loadReport === 'function') loadReport();
        if (typeof loadDeconvQuality === 'function') loadDeconvQuality();
        if (typeof loadGnnModel === 'function') loadGnnModel();
        
      } else if (status.status === 'error' || status.status === 'cancelled') {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
        pipelineDone(false);
      }
    } catch (e) {
      pollErrorCount++;
      if (pollErrorCount >= 10) {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
        appendLog(window.i18n.t('pipeline.log_connection_error'));
        showErrorToast(window.i18n.t('pipeline.toast_connection_lost'));
        pipelineDone(false);
      }
    } finally {
      isPollingActive = false;
    }
  }, 1500);
}

async function showPipelineSummary() {
  if (!state.outputDir) return;
  try {
    const summaryPath = `${state.outputDir}/preprocessing/preprocessing_summary.json`;
    const exists = await api.fileExists(summaryPath);
    if (!exists) return;
    const summary = await api.readJsonFile(summaryPath);
    if (!summary) return;

    // Build a compact summary string for the monitor
    const cells   = summary.scrna_cells   ? window.i18n.t('pipeline.summary_cells', { count: summary.scrna_cells.toLocaleString() }) : '';
    const genes   = summary.scrna_genes   ? window.i18n.t('pipeline.summary_genes', { count: summary.scrna_genes.toLocaleString() }) : '';
    const clusters= summary.scrna_clusters? window.i18n.t('pipeline.summary_clusters', { count: summary.scrna_clusters }) : '';
    const spots   = summary.spatial_spots ? window.i18n.t('pipeline.summary_spots', { count: summary.spatial_spots.toLocaleString() }) : '';

    const parts = [cells, genes, clusters, spots].filter(Boolean);
    if (parts.length === 0) return;

    // Inject into the stage-preprocessing status element for a non-intrusive display
    const el = document.getElementById('stage-preprocessing');
    if (el) {
      const statusEl = el.querySelector('.stage-status');
      if (statusEl) statusEl.textContent = `✅ ${parts.join(' · ')}`;
    }
    appendLog(window.i18n.t('pipeline.log_preprocessing_summary', { cells, genes, clusters, spots }));
  } catch (_) { /* özet gösterme hatası kritik değil */ }
}

function findLogOverlap(renderedLines, newLines) {
  if (renderedLines.length === 0 || newLines.length === 0) return null;
  const lastRendered = renderedLines[renderedLines.length - 1];
  let searchIdx = newLines.length - 1;
  
  while (searchIdx >= 0) {
    searchIdx = newLines.lastIndexOf(lastRendered, searchIdx);
    if (searchIdx === -1) break;
    
    let match = true;
    const checkLength = Math.min(renderedLines.length, searchIdx + 1);
    for (let i = 0; i < checkLength; i++) {
      if (renderedLines[renderedLines.length - 1 - i] !== newLines[searchIdx - i]) {
        match = false;
        break;
      }
    }
    if (match) {
      return searchIdx;
    }
    searchIdx--;
  }
  return null;
}

function updateLogs(logs) {
  const body = document.getElementById('log-body');
  if (!body) return;

  const logsToRender = logs.slice(-300);
  const lastLineText = logsToRender.length > 0 ? logsToRender[logsToRender.length - 1] : '';
  const currentLastLine = body.lastChild ? body.lastChild.textContent : '';

  if (logsToRender.length === body.children.length && lastLineText === currentLastLine) {
    return;
  }

  const renderedLines = Array.from(body.children).map(child => child.textContent);
  const overlapIdx = findLogOverlap(renderedLines, logsToRender);

  if (overlapIdx !== null) {
    const linesToKeep = overlapIdx + 1;
    const linesToRemove = renderedLines.length - linesToKeep;
    for (let i = 0; i < linesToRemove; i++) {
      if (body.firstChild) {
        body.removeChild(body.firstChild);
      }
    }

    const newLines = logsToRender.slice(overlapIdx + 1);
    if (newLines.length > 0) {
      const fragment = document.createDocumentFragment();
      newLines.forEach(l => {
        const div = document.createElement('div');
        div.className = 'log-line' +
          (l.includes('❌') || l.includes('[ERR]') ? ' error' :
           l.includes('⚠') ? ' warn' :
           l.includes('✅') ? ' info' : '');
        div.textContent = l;
        fragment.appendChild(div);
      });
      body.appendChild(fragment);
      body.scrollTop = body.scrollHeight;
    }
  } else {
    body.innerHTML = '';
    const fragment = document.createDocumentFragment();
    logsToRender.forEach(l => {
      const div = document.createElement('div');
      div.className = 'log-line' +
        (l.includes('❌') || l.includes('[ERR]') ? ' error' :
         l.includes('⚠') ? ' warn' :
         l.includes('✅') ? ' info' : '');
      div.textContent = l;
      fragment.appendChild(div);
    });
    body.appendChild(fragment);
    body.scrollTop = body.scrollHeight;
  }
}

function updateMonitor(status) {
  // Progress bar
  const pct = status.progress || 0;
  
  const progressBar = document.getElementById('progress-bar');
  if (progressBar) progressBar.style.width = pct + '%';
  
  const progressPct = document.getElementById('progress-pct');
  if (progressPct) progressPct.textContent = pct + '%';

  // Render logs incrementally
  updateLogs(status.logs || []);

  // Stage indicators — detect active stage first so we can i18n the progress label
  const stageMapping = {
    preprocessing: ['Ön İşleme', 'preprocessing', 'preprocess', 'ön'],
    deconvolution: ['Dekonvolüsyon', 'deconvolution', 'deconv', 'dekonvolüsyon'],
    gnn: ['GNN Eğitimi', 'GNN Training', 'gnn', 'eğitim'],
    viz: ['Görselleştirme', 'Görsel', 'Visualization', 'viz'],
    report: ['Rapor', 'Klinik Rapor', 'Report', 'rapor']
  };
  
  const cur = (status.stage || '').toLowerCase().trim();
  let activeStageId = null;
  
  for (const [id, aliases] of Object.entries(stageMapping)) {
    if (aliases.some(alias => cur.includes(alias.toLowerCase()))) {
      activeStageId = id;
      break;
    }
  }

  // Update progress-stage-label with the i18n-translated stage name
  // (avoids showing the Python backend's raw language string in the UI)
  const progressStageLabel = document.getElementById('progress-stage-label');
  if (progressStageLabel) {
    const stageI18nKeys = {
      preprocessing: 'pipeline.stage_preprocessing',
      deconvolution: 'pipeline.stage_deconvolution',
      gnn: 'pipeline.stage_gnn',
      viz: 'pipeline.stage_viz',
      report: 'pipeline.stage_report'
    };
    progressStageLabel.textContent = activeStageId && stageI18nKeys[activeStageId]
      ? window.i18n.t(stageI18nKeys[activeStageId])
      : (status.stage || '');
  }

  let foundActive = false;
  const stages = ['preprocessing', 'deconvolution', 'gnn', 'viz', 'report'];
  
  stages.forEach(id => {
    const el = document.getElementById(`stage-${id}`);
    if (!el) return;
    
    const statusEl = el.querySelector('.stage-status');
    
    if (id === activeStageId) {
      foundActive = true;
      el.className = 'stage-item active';
      if (statusEl) statusEl.textContent = window.i18n.t('pipeline.running');
    } else if (!foundActive) {
      el.className = 'stage-item done';
      if (statusEl) statusEl.textContent = window.i18n.t('pipeline.completed_log');
    } else {
      el.className = 'stage-item';
      if (statusEl) statusEl.textContent = window.i18n.t('diagnostics.waiting');
    }
  });
}

function pipelineDone(success) {
  if (state.pollInterval) {
    clearInterval(state.pollInterval);
    state.pollInterval = null;
  }
  if (state.elapsedInterval) {
    clearInterval(state.elapsedInterval);
    state.elapsedInterval = null;
  }
  
  state.pipelineRunning = false;
  
  const startBtn = document.getElementById('start-btn');
  if (startBtn) startBtn.disabled = false;
  
  const cancelBtn = document.getElementById('cancel-btn');
  if (cancelBtn) cancelBtn.style.display = 'none';
  
  const returnSetupBtn = document.getElementById('return-setup-btn');
  if (returnSetupBtn) returnSetupBtn.style.display = 'inline-flex';
  
  const progressBar = document.getElementById('progress-bar');
  if (progressBar) {
    progressBar.style.width = success ? '100%' : progressBar.style.width;
  }

  if (success) {
    appendLog(window.i18n.t('pipeline.log_all_stages_completed'));
    appendLog(window.i18n.t('pipeline.log_outputs_path', { path: state.outputDir }));
    // Mark all stages done
    ['preprocessing','deconvolution','gnn','viz','report'].forEach(id => {
      const el = document.getElementById(`stage-${id}`);
      if (el) {
        el.className = 'stage-item done';
        const statusEl = el.querySelector('.stage-status');
        if (statusEl) statusEl.textContent = window.i18n.t('pipeline.completed_log');
      }
    });
    
    const progressPct = document.getElementById('progress-pct');
    if (progressPct) progressPct.textContent = '100%';
    
    const progressStageLabel = document.getElementById('progress-stage-label');
    if (progressStageLabel) progressStageLabel.textContent = window.i18n.t('pipeline.completed_log');

    // Premium Toast success notification instead of confirm popup block
    showToast(window.i18n.t('pipeline.toast_analysis_success'), 'success');
  }

  console.log(`[Glio] pipelineDone called. success=${success}, document.hidden=${document.hidden}, hasFocus=${document.hasFocus()}`);

  // Trigger system notification
  if (success) {
    sendSystemNotification('Glio-Cartography', window.i18n.t('pipeline.notify_success'));
  } else {
    sendSystemNotification('Glio-Cartography', window.i18n.t('pipeline.notify_error'));
  }
}

function resetStages() {
  ['preprocessing','deconvolution','gnn','viz','report'].forEach(id => {
    const el = document.getElementById(`stage-${id}`);
    if (el) {
      el.className = 'stage-item';
      const statusEl = el.querySelector('.stage-status');
      if (statusEl) statusEl.textContent = window.i18n.t('diagnostics.waiting');
    }
  });
  
  const progressBar = document.getElementById('progress-bar');
  if (progressBar) progressBar.style.width = '0%';
  
  const progressPct = document.getElementById('progress-pct');
  if (progressPct) progressPct.textContent = '0%';
  
  const progressStageLabel = document.getElementById('progress-stage-label');
  if (progressStageLabel) progressStageLabel.textContent = window.i18n.t('pipeline.idle');
  
  const elapsedTime = document.getElementById('elapsed-time');
  if (elapsedTime) elapsedTime.textContent = '';
}

// ══════════════════════════════════════════════════════════════
// LOG
// ══════════════════════════════════════════════════════════════
function appendLog(msg) {
  const body = document.getElementById('log-body');
  if (!body) return;
  const div = document.createElement('div');
  div.className = 'log-line' + (msg.includes('❌') ? ' error' : msg.includes('✅') ? ' info' : '');
  div.textContent = msg;
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
}

function clearLog() {
  const body = document.getElementById('log-body');
  if (body) body.innerHTML = '';
}

// ══════════════════════════════════════════════════════════════
// DECONVOLUTION METHOD SELECTOR
// ══════════════════════════════════════════════════════════════
function selectDeconvMethod(method) {
  const validMethods = ['tangram', 'cell2location', 'stereoscope'];
  if (!validMethods.includes(method)) return;

  // Update hidden input value
  const hidden = document.getElementById('deconv-method');
  if (hidden) hidden.value = method;

  // Toggle active class on buttons with micro-animation
  validMethods.forEach(m => {
    const btn = document.getElementById(`btn-method-${m}`);
    if (!btn) return;
    if (m === method) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // Log label for readability
  const labels = { tangram: 'Tangram', cell2location: 'Cell2Location', stereoscope: 'Stereoscope' };
  console.log(`[Glio] Yöntem seçildi: ${labels[method]}`);

  // Save changes immediately
  if (typeof saveCurrentSettings === 'function') {
    saveCurrentSettings();
  }
}

// Centralized System Notification Helper (OS-level)
function sendSystemNotification(title, body) {
  if (window.glioAPI && typeof window.glioAPI.showNotification === 'function') {
    window.glioAPI.showNotification(title, body);
  } else {
    console.warn('[System Notification] IPC bridge is missing, fallback to console:', title, body);
  }
}
