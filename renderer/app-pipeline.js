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

  if (!spatialDir) { showWarningToast('Spatial veri klasörü seçin!'); return; }
  if (!scrnaPath)  { showWarningToast('scRNA-seq dosyası seçin!'); return; }
  if (!outputDir)  { showWarningToast('Çıktı klasörü seçin!'); return; }

  if (!isPathSafeLocal(spatialDir) || !isPathSafeLocal(scrnaPath) || !isPathSafeLocal(outputDir)) {
    showWarningToast('Seçilen yollar geçersiz veya güvenli olmayan karakterler içeriyor.');
    return;
  }

  if (!state.backendReady) {
    showWarningToast('Glio-Cartography bileşenleri henüz hazır değil, lütfen bekleyin.');
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
      spatial:      spatialDir,
      scrna:        scrnaPath,
      output:       outputDir,
      patientId:    safePatientId,
      epochs:       epochs,
      runOptuna:    runOptuna,
      optunaTrials: optunaT,
      deconvMethod: deconvMethod
    });
  } catch (_) { /* kayıt hatası kritik değil */ }

  // Switch to monitor
  showPanel('monitor');

  // Reset stages
  resetStages();
  clearLog();
  appendLog('🚀 Pipeline başlatılıyor...');

  state.pipelineRunning = true;
  state.startTime = Date.now();
  state.outputDir = outputDir;

  const startBtn = document.getElementById('start-btn');
  if (startBtn) startBtn.disabled = true;
  
  const cancelBtn = document.getElementById('cancel-btn');
  if (cancelBtn) cancelBtn.style.display = 'inline-flex';

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
      spatial_dir: spatialDir,
      scrna_path: scrnaPath,
      output_dir: outputDir,
      patient_id: safePatientId,
      run_optuna: runOptuna,
      optuna_trials: optunaT,
      gnn_epochs: epochs,
      deconv_method: deconvMethod
    });
    appendLog(`ℹ️ ${res.message || 'Başlatıldı'}`);
    startPolling();
  } catch (e) {
    appendLog(`❌ Backend başlatma hatası: ${e.message}`);
    pipelineDone(false);
  }
}

async function cancelPipeline() {
  const ok = await customConfirm('⚠️ Analizi İptal Et', 'Analiz iptal edilsin mi?');
  if (!ok) return;
  
  try {
    await api.backendRequest('/pipeline/cancel', 'POST', {});
    appendLog('⛔ İptal isteği gönderildi');
  } catch (e) {
    appendLog(`❌ İptal hatası: ${e.message}`);
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
        appendLog(`❌ Bağlantı hatası: Sunucudan yanıt alınamadığı için izleme durduruldu.`);
        showErrorToast('Sunucu bağlantısı koptu.');
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
    const cells   = summary.scrna_cells   ? `${summary.scrna_cells.toLocaleString()} hücre` : '';
    const genes   = summary.scrna_genes   ? `${summary.scrna_genes.toLocaleString()} gen` : '';
    const clusters= summary.scrna_clusters? `${summary.scrna_clusters} küme` : '';
    const spots   = summary.spatial_spots ? `${summary.spatial_spots.toLocaleString()} spot` : '';

    const parts = [cells, genes, clusters, spots].filter(Boolean);
    if (parts.length === 0) return;

    // Inject into the stage-preprocessing status element for a non-intrusive display
    const el = document.getElementById('stage-preprocessing');
    if (el) {
      const statusEl = el.querySelector('.stage-status');
      if (statusEl) statusEl.textContent = `✅ ${parts.join(' · ')}`;
    }
    appendLog(`📊 Ön İşleme Özeti: scRNA: ${cells} ${genes} ${clusters} | Spatial: ${spots}`);
  } catch (_) { /* özet gösterme hatası kritik değil */ }
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

function updateMonitor(status) {
  // Progress bar
  const pct = status.progress || 0;
  
  const progressBar = document.getElementById('progress-bar');
  if (progressBar) progressBar.style.width = pct + '%';
  
  const progressPct = document.getElementById('progress-pct');
  if (progressPct) progressPct.textContent = pct + '%';
  
  const progressStageLabel = document.getElementById('progress-stage-label');
  if (progressStageLabel) progressStageLabel.textContent = status.stage || '';

  // Render logs incrementally
  updateLogs(status.logs || []);

  // Stage indicators
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

  let foundActive = false;
  const stages = ['preprocessing', 'deconvolution', 'gnn', 'viz', 'report'];
  
  stages.forEach(id => {
    const el = document.getElementById(`stage-${id}`);
    if (!el) return;
    
    const statusEl = el.querySelector('.stage-status');
    
    if (id === activeStageId) {
      foundActive = true;
      el.className = 'stage-item active';
      if (statusEl) statusEl.textContent = 'Çalışıyor...';
    } else if (!foundActive) {
      el.className = 'stage-item done';
      if (statusEl) statusEl.textContent = '✅ Tamamlandı';
    } else {
      el.className = 'stage-item';
      if (statusEl) statusEl.textContent = 'Bekliyor';
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
  
  const progressBar = document.getElementById('progress-bar');
  if (progressBar) {
    progressBar.style.width = success ? '100%' : progressBar.style.width;
  }

  if (success) {
    appendLog('\n✅ TÜM AŞAMALAR TAMAMLANDI!');
    appendLog(`📂 Çıktılar: ${state.outputDir}`);
    // Mark all stages done
    ['preprocessing','deconvolution','gnn','viz','report'].forEach(id => {
      const el = document.getElementById(`stage-${id}`);
      if (el) {
        el.className = 'stage-item done';
        const statusEl = el.querySelector('.stage-status');
        if (statusEl) statusEl.textContent = '✅ Tamamlandı';
      }
    });
    
    const progressPct = document.getElementById('progress-pct');
    if (progressPct) progressPct.textContent = '100%';
    
    const progressStageLabel = document.getElementById('progress-stage-label');
    if (progressStageLabel) progressStageLabel.textContent = '✅ Tamamlandı';

    // Premium Toast success notification instead of confirm popup block
    showToast('Analiz başarıyla tamamlandı!', 'success');
  }

  console.log(`[Glio] pipelineDone called. success=${success}, document.hidden=${document.hidden}, hasFocus=${document.hasFocus()}`);

  // Trigger system notification
  if (success) {
    sendSystemNotification('Glio-Cartography', 'Analiz başarıyla tamamlandı! Çıktılar ve klinik rapor hazır.');
  } else {
    sendSystemNotification('Glio-Cartography', 'Analiz sırasında bir hata oluştu veya işlem durduruldu.');
  }
}

function resetStages() {
  ['preprocessing','deconvolution','gnn','viz','report'].forEach(id => {
    const el = document.getElementById(`stage-${id}`);
    if (el) {
      el.className = 'stage-item';
      const statusEl = el.querySelector('.stage-status');
      if (statusEl) statusEl.textContent = 'Bekliyor';
    }
  });
  
  const progressBar = document.getElementById('progress-bar');
  if (progressBar) progressBar.style.width = '0%';
  
  const progressPct = document.getElementById('progress-pct');
  if (progressPct) progressPct.textContent = '0%';
  
  const progressStageLabel = document.getElementById('progress-stage-label');
  if (progressStageLabel) progressStageLabel.textContent = 'Hazır';
  
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
}

// Centralized System Notification Helper (OS-level)
function sendSystemNotification(title, body) {
  if (window.glioAPI && typeof window.glioAPI.showNotification === 'function') {
    window.glioAPI.showNotification(title, body);
  } else {
    console.warn('[System Notification] IPC bridge is missing, fallback to console:', title, body);
  }
}
