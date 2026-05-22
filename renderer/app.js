/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — App Logic (renderer)
   ══════════════════════════════════════════════════════════ */

const api = window.glioAPI;

// ── State ────────────────────────────────────────────────────
let state = {
  backendReady: false,
  backendStartupFailed: false,
  licenseValid: false,
  licenseChecked: false,
  manualLicenseView: false,
  pipelineRunning: false,
  currentPanel: 'setup',
  outputDir: null,
  gnnData: null,
  spatialScale: 1.0,
  bgLoaded: false,
  bgImage: null,
  startTime: null,
  pollInterval: null,
  elapsedInterval: null,
  downloadAttempted: false,
  downloading: false,
};

// ── ZONE CONFIG ───────────────────────────────────────────────
const ZONE_COLORS = {
  'Pseudopalisading Necrosis': '#E63946',
  'Microvascular Proliferation': '#F4A261',
  'Cellular Tumor': '#2A9D8F',
  'Leading Edge': '#457B9D',
  'Infiltrating Tumor': '#9B5DE5',
};

// ══════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', async () => {
  // App version
  const ver = await api.getAppVersion();
  document.getElementById('app-version').textContent = `v${ver}`;

  // Machine ID
  const mid = await api.getMachineId();
  document.getElementById('machine-id-display').textContent = mid;

  // Check stored license
  const stored = await api.getStoredLicense();
  if (stored) {
    const result = await api.validateLicense(stored.key);
    if (result.valid) {
      state.licenseValid = true;
      showLicenseWaitingState();
    } else {
      state.licenseValid = false;
      showLicenseFormState();
    }
  } else {
    state.licenseValid = false;
    showLicenseFormState();
  }
  state.licenseChecked = true;
  evaluateLaunchState();

  // Optuna toggle
  document.getElementById('run-optuna').addEventListener('change', (e) => {
    document.getElementById('optuna-trials-row').style.display = e.target.checked ? 'flex' : 'none';
  });

  // Backend events — listen before polling so we don't miss it
  api.onBackendReady((ready) => setBackendStatus(ready));
  api.onBackendLog((msg) => handleBackendLog(msg));
  if (api.onDownloadProgress) {
    api.onDownloadProgress((data) => handleDownloadProgress(data));
  }
  if (api.onRuntimeMissing) {
    api.onRuntimeMissing(() => {
      console.log('[Runtime] Runtime missing event triggered. Checking auto-download...');
      triggerAutoDownload();
    });
  }

  // Sync backend state now to avoid race conditions
  await syncBackendState();

  // Güncelleme bildirimi dinle
  api.onUpdateAvailable((info) => {
    if (info.upToDate) {
      // Manuel kontrol istedi, güncel mesajı
      const banner = document.getElementById('update-banner');
      document.getElementById('update-banner-text').textContent =
        `✅ Güncel! Mevcut sürüm: ${info.current}`;
      document.getElementById('update-banner-link').style.display = 'none';
      banner.style.background = 'rgba(16,185,129,0.15)';
      banner.style.borderColor = 'rgba(16,185,129,0.4)';
      banner.classList.remove('hidden');
      setTimeout(() => banner.classList.add('hidden'), 4000);
      return;
    }
    _updateUrl = info.url || '';
    document.getElementById('update-banner-text').textContent =
      `🆕 Yeni sürüm: ${info.latest} (Mevcut: ${info.current})`;
    const link = document.getElementById('update-banner-link');
    link.style.display = '';
    const banner = document.getElementById('update-banner');
    banner.style.background = '';
    banner.style.borderColor = '';
    banner.classList.remove('hidden');
  });

  // Also poll backend health every 2s in case event was missed
  checkBackendHealth();
  setInterval(checkBackendHealth, 3000);

  // Son oturumda kullanılan yolları yükle
  await restoreLastPaths();
});

// ══════════════════════════════════════════════════════════════
// SON KULLANILAN YOLLAR (cross-session)
// ══════════════════════════════════════════════════════════════
async function restoreLastPaths() {
  try {
    const last = await api.getLastPaths();
    if (!last) return;  // ilk çalıştırma — kayıtlı yol yok

    if (last.spatial) {
      document.getElementById('spatial-path').value = last.spatial;
      const ok = await api.fileExists(last.spatial);
      setIndicator(
        'spatial-indicator',
        ok ? '✅ Son kullanılan klasör yüklendi' : '⚠️ Klasör artık bulunamıyor',
        ok ? 'ok' : 'err'
      );
    }

    if (last.scrna) {
      document.getElementById('scrna-path').value = last.scrna;
      const ok = await api.fileExists(last.scrna);
      setIndicator(
        'scrna-indicator',
        ok ? '✅ Son kullanılan dosya yüklendi' : '⚠️ Dosya artık bulunamıyor',
        ok ? 'ok' : 'err'
      );
    }

    if (last.output) {
      document.getElementById('output-path').value = last.output;
      state.outputDir = last.output;
      setIndicator('output-indicator', '✅ Son kullanılan çıktı klasörü', 'ok');
    }

    if (last.patientId)
      document.getElementById('patient-id').value = last.patientId;

  } catch (e) {
    // İlk çalıştırma veya store bozuk — sessizce geç
    console.warn('restoreLastPaths:', e);
  }
}

let lastBackendLogs = [];
function handleBackendLog(msg) {
  lastBackendLogs.push(msg);
  if (lastBackendLogs.length > 80) lastBackendLogs.shift();
  
  const logEl = document.getElementById('connection-log-preview');
  if (logEl) {
    logEl.textContent = lastBackendLogs.join('\n');
    logEl.scrollTop = logEl.scrollHeight;
  }
}

async function checkBackendHealth() {
  // Skip noisy polling when we know backend isn't running yet
  if (state.downloading) return;
  
  try {
    const stateObj = await api.getBackendState();
    // Don't poll HTTP if main process says runtime is missing or still starting
    if (stateObj && (stateObj.status === 'runtime-missing' || stateObj.status === 'starting')) return;

    const res = await api.backendRequest('/health', 'GET', {});
    if (res && res.status === 'ok') {
      setBackendStatus(true);
    } else {
      setBackendStatus(false);
    }
  } catch (e) {
    // Only set status to false if we were already connected before
    if (state.backendReady) {
      setBackendStatus(false);
    }
  }
}

function setBackendStatus(ready) {
  state.backendReady = ready;
  if (ready) {
    state.backendStartupFailed = false;
  } else {
    state.backendStartupFailed = true;
  }
  const dot = document.getElementById('backend-dot');
  const txt = document.getElementById('backend-status');
  if (ready) {
    dot.className = 'status-dot connected';
    txt.textContent = 'Bileşenler bağlandı';
    hideConnectionError();
  } else {
    dot.className = 'status-dot error';
    txt.textContent = 'Bileşenler bağlanamadı';
    showConnectionError();
  }
  evaluateLaunchState();
}

// ══════════════════════════════════════════════════════════════
// LICENSE
// ══════════════════════════════════════════════════════════════
async function activateLicense() {
  try {
    const key = document.getElementById('license-input').value.trim().toUpperCase();
    const errEl = document.getElementById('license-error');
    errEl.classList.add('hidden');

    if (!key) { showLicenseError('Lisans anahtarı girin.'); return; }

    const result = await api.validateLicense(key);
    if (result.valid) {
      await api.saveLicense(key, result.expiryDate);
      state.licenseValid = true;
      
      const stateObj = await api.getBackendState();
      if (stateObj && stateObj.status === 'runtime-missing') {
        triggerAutoDownload();
      } else {
        if (state.backendReady) {
          hideLicense();
        } else {
          showLicenseWaitingState();
        }
      }
    } else {
      showLicenseError(result.reason || 'Geçersiz lisans');
    }
  } catch (err) {
    alert("Hata oluştu: " + err.message + "\nLütfen geliştiriciye bildirin.");
  }
}

function showLicenseError(msg) {
  const el = document.getElementById('license-error');
  el.textContent = '❌ ' + msg;
  el.classList.remove('hidden');
}

function hideLicense() {
  state.manualLicenseView = false;
  document.getElementById('license-overlay').classList.remove('active');
  document.getElementById('license-overlay-close').classList.add('hidden');
}

function showLicenseInfo() {
  state.manualLicenseView = true;
  showLicenseFormState();
  if (state.licenseValid) {
    document.getElementById('license-overlay-close').classList.remove('hidden');
  } else {
    document.getElementById('license-overlay-close').classList.add('hidden');
  }
  document.getElementById('license-overlay').classList.add('active');
}

function closeLicenseOverlay() {
  state.manualLicenseView = false;
  hideLicense();
}

function showLicenseWaitingState() {
  document.getElementById('license-form-container').classList.add('hidden');
  document.getElementById('license-checking-state').classList.remove('hidden');
  
  if (state.licenseValid && state.backendStartupFailed) {
    showConnectionError();
  } else {
    document.getElementById('checking-msg').textContent = 'Lisans tanındı, lütfen bekleyiniz...';
    document.getElementById('checking-submsg').textContent = 'Uygulama sunucusuna bağlanılıyor...';
    // Ensure premium loader is visible
    const loader = document.getElementById('premium-loader-el');
    if (loader) loader.style.display = '';
    const container = document.getElementById('connection-error-container');
    if (container) container.classList.add('hidden');
  }
}

function showLicenseFormState() {
  document.getElementById('license-checking-state').classList.add('hidden');
  document.getElementById('license-form-container').classList.remove('hidden');
}

function evaluateLaunchState() {
  if (state.licenseValid && state.backendReady && !state.manualLicenseView) {
    hideLicense();
  } else if (state.licenseValid && state.backendStartupFailed) {
    showConnectionError();
  }
}

function showConnectionError() {
  if (state.downloading) {
    return; // Don't interrupt active download/installation
  }

  const overlay = document.getElementById('license-overlay');
  if (overlay) overlay.classList.add('active');

  const checkingState = document.getElementById('license-checking-state');
  if (checkingState) checkingState.classList.remove('hidden');

  const formContainer = document.getElementById('license-form-container');
  if (formContainer) formContainer.classList.add('hidden');

  document.getElementById('checking-msg').textContent = '⚠️ Bileşen Bağlantı Hatası';
  document.getElementById('checking-submsg').innerHTML = 'Glio-Cartography Bileşenleri başlatılamadı veya yanıt vermiyor.<br>Lütfen uygulamanın gerekli bileşenleri kurmasına izin verin veya internet bağlantınızı kontrol edin.';
  
  // Hide loading ring
  const loader = document.getElementById('premium-loader-el');
  if (loader) loader.style.display = 'none';

  // Show error container
  const container = document.getElementById('connection-error-container');
  if (container) container.classList.remove('hidden');
  
  updateCustomPathDisplay();

  // Populate log preview
  const logEl = document.getElementById('connection-log-preview');
  if (logEl) {
    logEl.textContent = lastBackendLogs.length > 0 
      ? lastBackendLogs.join('\n') 
      : 'Bağlantı bekleniyor... Log kaydı bulunamadı.';
    logEl.scrollTop = logEl.scrollHeight;
  }
}

async function updateCustomPathDisplay() {
  try {
    const savedPath = await api.getCustomPythonPath();
    const displayContainer = document.getElementById('custom-python-path-display');
    const displaySpan = document.getElementById('selected-python-path-text');
    if (savedPath) {
      if (displaySpan) displaySpan.textContent = savedPath;
      if (displayContainer) displayContainer.classList.remove('hidden');
    } else {
      if (displayContainer) displayContainer.classList.add('hidden');
    }
  } catch (e) {
    console.error('Failed to get custom python path:', e);
  }
}

function hideConnectionError() {
  const loader = document.getElementById('premium-loader-el');
  if (loader) loader.style.display = '';

  const container = document.getElementById('connection-error-container');
  if (container) container.classList.add('hidden');

  if (state.licenseValid && state.backendStartupFailed) {
    // keep error message
  } else {
    document.getElementById('checking-msg').textContent = 'Sistem başlatılıyor...';
    document.getElementById('checking-submsg').textContent = 'Uygulama sunucusuna bağlanılıyor...';
  }
}

async function selectCustomPython() {
  try {
    const selected = await api.selectPythonPath();
    if (selected) {
      console.log('User selected Python path:', selected);
      await api.saveCustomPythonPath(selected);
      updateCustomPathDisplay();
      
      // Attempt restart automatically
      await retryBackendConnection();
    }
  } catch (err) {
    alert('Bileşen seçimi sırasında hata oluştu: ' + err.message);
  }
}

async function retryBackendConnection() {
  try {
    // Show loading state again
    const container = document.getElementById('connection-error-container');
    if (container) container.classList.add('hidden');
    
    const loader = document.getElementById('premium-loader-el');
    if (loader) loader.style.display = '';
    
    document.getElementById('checking-msg').textContent = 'Yeniden başlatılıyor...';
    document.getElementById('checking-submsg').textContent = 'Glio-Cartography bileşenleri başlatılıyor...';
    
    // Clear logs
    lastBackendLogs = [];
    const logEl = document.getElementById('connection-log-preview');
    if (logEl) logEl.textContent = 'Glio-Cartography bileşenleri başlatılıyor...';

    const ok = await api.restartBackend();
    if (ok) {
      setBackendStatus(true);
    } else {
      setBackendStatus(false);
    }
  } catch (err) {
    console.error('Restart backend error:', err);
    setBackendStatus(false);
  }
}

async function syncBackendState() {
  try {
    const stateObj = await api.getBackendState();
    console.log('[Sync] Received backend state:', stateObj);
    if (!stateObj) return;

    if (stateObj.status === 'ready') {
      setBackendStatus(true);
    } else if (stateObj.status === 'failed') {
      setBackendStatus(false);
      if (stateObj.error) {
        const statusEl = document.getElementById('download-progress-status');
        if (statusEl) statusEl.textContent = '❌ Hata: ' + stateObj.error;
      }
    } else if (stateObj.status === 'runtime-missing') {
      console.log('[Runtime] Sync state shows runtime missing. Checking auto-download...');
      triggerAutoDownload();
    } else if (['downloading', 'extracting', 'configuring', 'downloading_vc', 'installing_vc', 'completed'].includes(stateObj.status)) {
      handleDownloadProgress(stateObj);
    }
  } catch (e) {
    console.error('[Sync] Failed to sync backend state:', e);
  }
}

function triggerAutoDownload() {
  if (state.licenseValid && !state.downloadAttempted) {
    state.downloadAttempted = true;
    console.log('[Runtime] Starting automatic background download...');
    downloadRuntime();
  }
}

async function downloadRuntime() {
  try {
    state.downloading = true;
    const btnDownload = document.getElementById('btn-download-runtime');
    if (btnDownload) btnDownload.disabled = true;

    // Show progress bar immediately so user sees activity
    showLicenseWaitingState();
    const container = document.getElementById('download-progress-container');
    if (container) container.classList.remove('hidden');
    const statusEl = document.getElementById('download-progress-status');
    if (statusEl) statusEl.textContent = '🔌 Sunucuya bağlanılıyor...';
    document.getElementById('checking-msg').textContent = 'Bileşenler Kuruluyor...';
    document.getElementById('checking-submsg').textContent = 'Glio-Cartography için gerekli bileşenler indiriliyor. Lütfen bekleyiniz...';
    
    const ok = await api.downloadRuntime();
    if (ok && ok.success) {
      console.log('Download success: Python saved at', ok.pythonPath);
    }
  } catch (err) {
    console.error('Download error:', err);
    state.downloading = false;
    state.downloadAttempted = false; // Allow retry

    // Show friendly error
    document.getElementById('checking-msg').textContent = '❌ İndirme Başarısız';
    document.getElementById('checking-submsg').textContent = 'Bileşenler indirilemedi. Lütfen internet bağlantınızı kontrol edin ve tekrar deneyin.';
    const container = document.getElementById('download-progress-container');
    if (container) container.classList.add('hidden');
    const errContainer = document.getElementById('connection-error-container');
    if (errContainer) errContainer.classList.remove('hidden');
    const loader = document.getElementById('premium-loader-el');
    if (loader) loader.style.display = 'none';
  }
}

function openLogFile() {
  api.openLogFile();
}

function handleDownloadProgress(data) {
  // Ensure we are in the waiting state view
  showLicenseWaitingState();

  const container = document.getElementById('download-progress-container');
  const statusEl = document.getElementById('download-progress-status');
  const percentEl = document.getElementById('download-progress-percent');
  const fillEl = document.getElementById('download-progress-bar-fill');
  const infoEl = document.getElementById('download-progress-info');
  const btnDownload = document.getElementById('btn-download-runtime');
  const btnSelect = document.getElementById('btn-select-python');
  const btnRetry = document.getElementById('btn-retry-connection');
  const errContainer = document.getElementById('connection-error-container');
  const loader = document.getElementById('premium-loader-el');

  if (container) container.classList.remove('hidden');

  const isFinished = (data.status === 'completed' || data.status === 'failed');

  if (isFinished) {
    state.downloading = false;
  } else {
    state.downloading = true;
  }

  if (!isFinished) {
    if (btnDownload) btnDownload.disabled = true;
    if (btnSelect) btnSelect.disabled = true;
    if (btnRetry) btnRetry.disabled = true;
    
    // Hide error container and premium loader ring while setup is actively running
    if (errContainer) errContainer.classList.add('hidden');
    if (loader) loader.style.display = 'none';

    // Update main checking messages to be clinician-friendly
    document.getElementById('checking-msg').textContent = 'Bileşenler Kuruluyor...';
    document.getElementById('checking-submsg').textContent = 'Glio-Cartography için gerekli bileşenler otomatik olarak yapılandırılıyor.';
  } else {
    if (btnDownload) btnDownload.disabled = false;
    if (btnSelect) btnSelect.disabled = false;
    if (btnRetry) btnRetry.disabled = false;
  }

  if (data.status === 'downloading_vc') {
    statusEl.textContent = '📥 Glio-Cartography sistem bileşenleri indiriliyor...';
    percentEl.textContent = `${data.percent}%`;
    if (fillEl) fillEl.style.width = `${data.percent}%`;
    if (infoEl) infoEl.textContent = `${data.received} MB / ${data.total} MB`;
  } else if (data.status === 'installing_vc') {
    statusEl.textContent = '⚙️ Glio-Cartography sistem bileşenleri kuruluyor (Lütfen bekleyiniz)...';
    percentEl.textContent = '50%';
    if (fillEl) {
      fillEl.style.width = '50%';
      fillEl.style.background = 'linear-gradient(90deg, #7c3aed, #00d4ff)';
    }
    if (infoEl) infoEl.textContent = 'Yönetici izni penceresi açılabilir, lütfen onaylayın.';
  } else if (data.status === 'downloading') {
    statusEl.textContent = '📥 Glio-Cartography bileşenleri indiriliyor...';
    percentEl.textContent = `${data.percent}%`;
    if (fillEl) {
      fillEl.style.width = `${data.percent}%`;
      fillEl.style.background = '';
    }
    if (infoEl) infoEl.textContent = `${data.received} MB / ${data.total} MB`;
  } else if (data.status === 'extracting') {
    statusEl.textContent = '📦 Glio-Cartography bileşenleri kuruluyor (Arşiv açılıyor)...';
    percentEl.textContent = '100%';
    if (fillEl) {
      fillEl.style.width = '100%';
      fillEl.style.background = 'linear-gradient(90deg, #7c3aed, #00d4ff)';
    }
    if (infoEl) infoEl.textContent = 'Bu işlem 1-2 dakika sürebilir...';
  } else if (data.status === 'configuring') {
    statusEl.textContent = '⚙️ Glio-Cartography bileşenleri yapılandırılıyor...';
    percentEl.textContent = '100%';
    if (infoEl) infoEl.textContent = 'Yapılandırma tamamlanıyor...';
  } else if (data.status === 'completed') {
    statusEl.textContent = '✅ Kurulum başarıyla tamamlandı!';
    percentEl.textContent = '100%';
    if (fillEl) {
      fillEl.style.width = '100%';
      fillEl.style.background = 'linear-gradient(90deg, #10b981, #059669)';
    }
    if (infoEl) infoEl.textContent = 'Glio-Cartography bileşenleri başlatılıyor...';
    setTimeout(() => {
      if (container) container.classList.add('hidden');
      retryBackendConnection();
    }, 2000);
  } else if (data.status === 'failed') {
    statusEl.textContent = '❌ Kurulum başarısız oldu.';
    percentEl.textContent = '-';
    if (fillEl) fillEl.style.width = '0%';
    if (infoEl) infoEl.textContent = data.error || 'Bilinmeyen hata';
    
    // Show error UI and fill log preview
    showConnectionError();
  }
}

function copyMachineId() {
  const id = document.getElementById('machine-id-display').textContent;
  navigator.clipboard.writeText(id).then(() => {
    const btn = document.querySelector('.btn-copy');
    btn.textContent = '✅ Kopyalandı';
    setTimeout(() => btn.textContent = '📋 Kopyala', 2000);
  });
}

// ══════════════════════════════════════════════════════════════
// NAVIGATION
// ══════════════════════════════════════════════════════════════
function showPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById(`panel-${name}`).classList.add('active');
  document.querySelector(`[data-panel="${name}"]`).classList.add('active');
  state.currentPanel = name;
}

// ══════════════════════════════════════════════════════════════
// FILE SELECTION
// ══════════════════════════════════════════════════════════════
async function browseSpatial() {
  const path = await api.selectFolder();
  if (path) {
    document.getElementById('spatial-path').value = path;
    setIndicator('spatial-indicator', '✅ Klasör seçildi', 'ok');
  }
}

async function browseScrna() {
  const path = await api.selectFile([
    { name: 'scRNA Data', extensions: ['h5ad','h5','loom','csv','tsv'] }
  ]);
  if (path) {
    document.getElementById('scrna-path').value = path;
    setIndicator('scrna-indicator', '✅ Dosya seçildi', 'ok');
  }
}

async function browseOutput() {
  const path = await api.selectOutputFolder();
  if (path) {
    document.getElementById('output-path').value = path;
    state.outputDir = path;
    setIndicator('output-indicator', '✅ Çıktı klasörü seçildi', 'ok');
  }
}

function setIndicator(id, msg, cls) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = `path-indicator ${cls}`;
}

// ══════════════════════════════════════════════════════════════
// PIPELINE
// ══════════════════════════════════════════════════════════════
async function startPipeline() {
  const spatialDir = document.getElementById('spatial-path').value;
  const scrnaPath  = document.getElementById('scrna-path').value;
  const outputDir  = document.getElementById('output-path').value;
  const patientId  = document.getElementById('patient-id').value || 'Patient_A';
  const epochs     = parseInt(document.getElementById('gnn-epochs').value) || 100;
  const runOptuna  = document.getElementById('run-optuna').checked;
  const optunaT    = parseInt(document.getElementById('optuna-trials').value) || 10;

  if (!spatialDir) { alert('Spatial veri klasörü seçin!'); return; }
  if (!scrnaPath)  { alert('scRNA-seq dosyası seçin!'); return; }
  if (!outputDir)  { alert('Çıktı klasörü seçin!'); return; }

  if (!state.backendReady) {
    alert('Glio-Cartography bileşenleri henüz hazır değil, lütfen bekleyin.'); return;
  }

  // Seçilen yolları electron-store'a kaydet (sonraki oturum için)
  try {
    await api.saveLastPaths({
      spatial:   spatialDir,
      scrna:     scrnaPath,
      output:    outputDir,
      patientId: patientId,
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

  document.getElementById('start-btn').disabled = true;
  document.getElementById('cancel-btn').style.display = 'inline-flex';

  // Start elapsed timer
  state.elapsedInterval = setInterval(() => {
    const sec = Math.floor((Date.now() - state.startTime) / 1000);
    const m = String(Math.floor(sec / 60)).padStart(2,'0');
    const s = String(sec % 60).padStart(2,'0');
    document.getElementById('elapsed-time').textContent = `⏱ ${m}:${s}`;
  }, 1000);

  // Call backend
  try {
    const res = await api.backendRequest('/pipeline/start', 'POST', {
      spatial_dir: spatialDir,
      scrna_path: scrnaPath,
      output_dir: outputDir,
      patient_id: patientId,
      run_optuna: runOptuna,
      optuna_trials: optunaT,
      gnn_epochs: epochs
    });
    appendLog(`ℹ️ ${res.message || 'Başlatıldı'}`);
    startPolling();
  } catch (e) {
    appendLog(`❌ Backend hatası: ${e.message}`);
    pipelineDone(false);
  }
}

async function cancelPipeline() {
  if (!confirm('Analiz iptal edilsin mi?')) return;
  await api.backendRequest('/pipeline/cancel', 'POST', {});
  appendLog('⛔ İptal isteği gönderildi');
  pipelineDone(false);
}

function startPolling() {
  state.pollInterval = setInterval(async () => {
    try {
      const status = await api.backendRequest(`/pipeline/status`, 'GET', {});
      updateMonitor(status);
      if (status.status === 'done') {
        pipelineDone(true);
        // Otomatik yükleme
        loadResults();
        loadFigures();
        loadReport();
        loadDeconvQuality();
        loadGnnModel();
        showPanel('results');
      } else if (status.status === 'error' || status.status === 'cancelled') {
        pipelineDone(false);
      }
    } catch (e) { /* ignore transient errors */ }
  }, 1500);
}

function updateMonitor(status) {
  // Progress bar
  const pct = status.progress || 0;
  document.getElementById('progress-bar').style.width = pct + '%';
  document.getElementById('progress-pct').textContent = pct + '%';
  document.getElementById('progress-stage-label').textContent = status.stage || '';

  // Logs
  const logs = status.logs || [];
  const body = document.getElementById('log-body');
  body.innerHTML = '';
  logs.slice(-200).forEach(l => {
    const div = document.createElement('div');
    div.className = 'log-line' +
      (l.includes('❌') || l.includes('[ERR]') ? ' error' :
       l.includes('⚠') ? ' warn' :
       l.includes('✅') ? ' info' : '');
    div.textContent = l;
    body.appendChild(div);
  });
  body.scrollTop = body.scrollHeight;

  // Stage indicators
  const stageMap = {
    'Ön İşleme': 'preprocessing',
    'Dekonvolüsyon': 'deconvolution',
    'GNN Eğitimi': 'gnn',
    'Görselleştirme': 'viz',
    'Rapor': 'report'
  };
  const cur = status.stage || '';
  let found = false;
  for (const [label, id] of Object.entries(stageMap)) {
    const el = document.getElementById(`stage-${id}`);
    if (!el) continue;
    if (!found && cur.includes(label.split(' ')[0])) {
      found = true;
      el.className = 'stage-item active';
      el.querySelector('.stage-status').textContent = 'Çalışıyor...';
    } else if (!found) {
      if (pct > 0) {
        el.className = 'stage-item done';
        el.querySelector('.stage-status').textContent = '✅ Tamamlandı';
      }
    }
  }
}

function pipelineDone(success) {
  clearInterval(state.pollInterval);
  clearInterval(state.elapsedInterval);
  state.pipelineRunning = false;
  document.getElementById('start-btn').disabled = false;
  document.getElementById('cancel-btn').style.display = 'none';
  document.getElementById('progress-bar').style.width = success ? '100%' : document.getElementById('progress-bar').style.width;

  if (success) {
    appendLog('\n✅ TÜM AŞAMALAR TAMAMLANDI!');
    appendLog(`📂 Çıktılar: ${state.outputDir}`);
    // Mark all stages done
    ['preprocessing','deconvolution','gnn','viz','report'].forEach(id => {
      const el = document.getElementById(`stage-${id}`);
      if (el) { el.className = 'stage-item done'; el.querySelector('.stage-status').textContent = '✅ Tamamlandı'; }
    });
    document.getElementById('progress-pct').textContent = '100%';
    document.getElementById('progress-stage-label').textContent = '✅ Tamamlandı';

    // Show results notification
    setTimeout(() => {
      if (confirm('Analiz tamamlandı! Sonuçları görüntülemek ister misiniz?')) {
        showPanel('results');
        loadResults();
      }
    }, 500);
  }
}

function resetStages() {
  ['preprocessing','deconvolution','gnn','viz','report'].forEach(id => {
    const el = document.getElementById(`stage-${id}`);
    if (el) { el.className = 'stage-item'; el.querySelector('.stage-status').textContent = 'Bekliyor'; }
  });
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-pct').textContent = '0%';
  document.getElementById('progress-stage-label').textContent = 'Hazır';
  document.getElementById('elapsed-time').textContent = '';
}

// ══════════════════════════════════════════════════════════════
// LOG
// ══════════════════════════════════════════════════════════════
function appendLog(msg) {
  const body = document.getElementById('log-body');
  const div = document.createElement('div');
  div.className = 'log-line' + (msg.includes('❌') ? ' error' : msg.includes('✅') ? ' info' : '');
  div.textContent = msg;
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
}

function clearLog() {
  document.getElementById('log-body').innerHTML = '';
}

// ══════════════════════════════════════════════════════════════
// RESULTS VIEWER
// ══════════════════════════════════════════════════════════════
async function loadResults() {
  if (!state.outputDir) { alert('Önce bir analiz çalıştırın.'); return; }

  const dataPath = `${state.outputDir}/gnn/data.json`;
  const exists = await api.fileExists(dataPath);
  if (!exists) { alert('GNN çıktı verisi henüz mevcut değil. Pipeline\'ın tamamlanmasını bekleyin.'); return; }

  document.getElementById('results-placeholder').classList.add('hidden');
  document.getElementById('results-viewer').classList.remove('hidden');

  const btnNodes = document.querySelectorAll('button[onclick="loadResults()"]');
  btnNodes.forEach(btn => { btn.dataset.orig = btn.textContent; btn.textContent = '⏳ Yükleniyor...'; btn.disabled = true; });

  // Browser'ın "Yükleniyor" metnini çizmesine izin ver
  await new Promise(r => setTimeout(r, 50));

  try {
    const res = await fetch(`local://${encodeURI(dataPath)}`);
    if (!res.ok) throw new Error('Fetch failed');
    state.gnnData = await res.json();
  } catch (e) {
    console.warn("Native fetch başarısız, IPC okumasına dönülüyor:", e);
    state.gnnData = await api.readJsonFile(dataPath);
  }

  // Post-processing of gnnData: convert lr dictionary to lr_pairs array if needed!
  if (state.gnnData && state.gnnData.spots) {
    state.gnnData.spots.forEach(spot => {
      if (spot.lr && !spot.lr_pairs) {
        spot.lr_pairs = Object.entries(spot.lr).map(([key, val]) => {
          const parts = key.split('-');
          return {
            ligand: parts[0] || '',
            receptor: parts[1] || '',
            score: val
          };
        });
      }
    });
  }

  btnNodes.forEach(btn => { btn.textContent = btn.dataset.orig; btn.disabled = false; });

  // Arkaplan resmi ve scale ayarı
  state.bgImage = new Image();
  state.bgLoaded = false;
  state.spatialScale = 1.0;

  const scalePath = `${state.outputDir}/spatial_data/scalefactors_json.json`;
  const scaleExists = await api.fileExists(scalePath);
  if (scaleExists) {
    const scales = await api.readJsonFile(scalePath);
    if (scales && scales.tissue_hires_scalef) {
      state.spatialScale = scales.tissue_hires_scalef;
    }
  }

  const bgPath = `${state.outputDir}/spatial_data/tissue_hires_image.png`;
  const bgExists = await api.fileExists(bgPath);
  if (bgExists) {
    state.bgImage.onload = () => { state.bgLoaded = true; renderSpatialCanvas(); setupNewFeatures(); };
    state.bgImage.onerror = () => { state.bgLoaded = false; renderSpatialCanvas(); setupNewFeatures(); };
    state.bgImage.src = `local://${encodeURI(bgPath)}`;
  } else {
    renderSpatialCanvas();
    setupNewFeatures();
  }
}

function updateViewMode() {
  const mode = document.getElementById('view-mode').value;
  const filterRisk = document.getElementById('filter-risk');
  const filterPathway = document.getElementById('filter-pathway');
  
  if (mode === 'risk') {
    filterRisk.classList.remove('hidden');
  } else {
    filterRisk.classList.add('hidden');
  }
  
  if (mode === 'pathway') {
    filterPathway.classList.remove('hidden');
  } else {
    filterPathway.classList.add('hidden');
  }
  
  renderSpatialCanvas();
}

function updateLegend(mode, data) {
  const lg = document.getElementById('spatial-legend');
  if (!data || !data.spots) { lg.classList.add('hidden'); return; }
  
  lg.innerHTML = '';
  lg.classList.remove('hidden');
  
  if (mode === 'zone') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">Tümör Zonları</div>';
    Object.entries(ZONE_COLORS).forEach(([z, c]) => {
      lg.innerHTML += `<div class="legend-item"><div class="legend-color" style="background:${c}"></div><span>${z}</span></div>`;
    });
  } else if (mode === 'celltype') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">Baskın Hücre Tipleri</div>';
    lg.innerHTML += `<div class="legend-item"><span style="font-size:0.75rem;">(Hücre tipine özgü otomatik renk)</span></div>`;
  } else if (mode === 'lr') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">Ligand-Reseptör Etkileşimi</div>';
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #4f46e5, #06b6d4, #10b981, #f97316, #ef4444);"></div>
      <div class="legend-gradient-labels"><span>0.00</span><span>${(state._lrMax||1).toFixed(2)}</span></div>
    `;
  } else if (mode === 'drug') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">İlaç Hedef Uyumu</div>';
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #1a1a2e, #ff6b6b);"></div>
      <div class="legend-gradient-labels"><span>Düşük</span><span>Yüksek</span></div>
    `;
  } else if (mode === 'risk') {
    lg.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">TCGA Risk Skoru</div>';
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #2A9D8F, #E63946);"></div>
      <div class="legend-gradient-labels"><span>Düşük Risk</span><span>Yüksek Risk</span></div>
    `;
  } else if (mode === 'pathway') {
    const activePathway = document.getElementById('filter-pathway').value;
    const displayName = activePathway.replace(/_/g, '/');
    lg.innerHTML = `<div style="font-weight:bold;margin-bottom:4px;color:var(--text);">${displayName}</div>`;
    lg.innerHTML += `
      <div class="legend-gradient" style="background: linear-gradient(to right, #0f172a, #6366f1, #ec4899, #f97316, #eab308);"></div>
      <div class="legend-gradient-labels"><span>${(state._pathwayMin||0).toFixed(2)}</span><span>${(state._pathwayMax||1).toFixed(2)}</span></div>
    `;
  }
}

function renderSpatialCanvas() {
  const data = state.gnnData;
  if (!data) return;

  const canvas = document.getElementById('spatial-canvas');
  const ctx = canvas.getContext('2d');
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width  = rect.width  || 900;
  canvas.height = rect.height || 520;
  console.log(`[SpatialMap] Canvas rendering with size: ${canvas.width}x${canvas.height}`);

  if (!state.viewTransform) state.viewTransform = { x: 0, y: 0, k: 1 };
  const t = state.viewTransform;

  const spots = data.spots;
  const ZONES = (data.metadata && data.metadata.zones) || [];
  const mode  = document.getElementById('view-mode').value;

  // LR modunda normalize edebilmek için dataset genelindeki maks skoru önceden hesapla
  if (mode === 'lr') {
    state._lrMax = 0;
    spots.forEach(s => {
      const pairs = s.lr_pairs || [];
      if (pairs.length > 0) {
        const mx = Math.max(...pairs.map(p => p.score || 0));
        if (mx > state._lrMax) state._lrMax = mx;
      }
    });
    if (state._lrMax === 0) state._lrMax = 1; // sıfır bölme önlemi
  }

  // Pathway modunda normalize edebilmek için dataset genelindeki min ve maks skoru önceden hesapla
  if (mode === 'pathway') {
    const activePathway = document.getElementById('filter-pathway').value;
    state._pathwayMin = Infinity;
    state._pathwayMax = -Infinity;
    spots.forEach(s => {
      const val = (s.pathways && s.pathways[activePathway]) || 0;
      if (val < state._pathwayMin) state._pathwayMin = val;
      if (val > state._pathwayMax) state._pathwayMax = val;
    });
    if (state._pathwayMin === state._pathwayMax) {
      state._pathwayMin = 0;
      state._pathwayMax = 1;
    }
  }

  const xs = spots.map(s => s.x * state.spatialScale);
  const ys = spots.map(s => s.y * state.spatialScale);

  ctx.fillStyle = '#020509';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  let offsetX = 0, offsetY = 0, scale = 1.0;

  if (state.bgLoaded && state.bgImage.width > 0) {
    scale = Math.min(canvas.width / state.bgImage.width, canvas.height / state.bgImage.height) * 0.95;
    offsetX = (canvas.width - state.bgImage.width * scale) / 2;
    offsetY = (canvas.height - state.bgImage.height * scale) / 2;
  } else {
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const pad = 30;
    const W = canvas.width - pad*2, H = canvas.height - pad*2;
    scale = Math.min(W / (maxX - minX + 1e-8), H / (maxY - minY + 1e-8));
    offsetX = pad - minX * scale;
    offsetY = pad - minY * scale;
  }

  const toCanvas = (x, y) => {
    const lx = offsetX + (x * state.spatialScale) * scale;
    const ly = offsetY + (y * state.spatialScale) * scale;
    return {
      cx: lx * t.k + t.x,
      cy: ly * t.k + t.y
    };
  };

  // Save rendering params for tooltips/clicks
  state._offsetX = offsetX;
  state._offsetY = offsetY;
  state._renderScale = scale;

  if (state.bgLoaded && state.bgImage.width > 0) {
    ctx.globalAlpha = 0.5;
    ctx.drawImage(state.bgImage, 
                  offsetX * t.k + t.x, 
                  offsetY * t.k + t.y, 
                  state.bgImage.width * scale * t.k, 
                  state.bgImage.height * scale * t.k);
    ctx.globalAlpha = 1.0;
  }

  const r = Math.max(2, Math.min(5, 3000 / spots.length)) * (scale > 1 ? scale * 0.5 : 1) * t.k;

  // TCGA Risk Median (for filtering)
  if (!state._medianRisk && spots.length > 0) {
    const sorted = [...spots].map(s => s.tcga_risk || 0).sort((a,b)=>a-b);
    state._medianRisk = sorted[Math.floor(sorted.length / 2)];
  }

  spots.forEach(spot => {
    const {cx, cy} = toCanvas(spot.x, spot.y);
    let color = '#888';
    let alpha = 0.85;

    if (mode === 'zone') {
      const zoneIdx  = ZONES.map(z => spot.zones[z] || 0);
      const domZone  = ZONES[zoneIdx.indexOf(Math.max(...zoneIdx))];
      const zColors  = Object.values(ZONE_COLORS);
      color = zColors[ZONES.indexOf(domZone) % zColors.length] || '#888';
    } else if (mode === 'drug') {
      const ds = spot.drug_score || 0;
      color = interpolateColor('#1a1a2e', '#ff6b6b', ds);
    } else if (mode === 'risk') {
      const rs = spot.tcga_risk || 0;
      const fRisk = document.getElementById('filter-risk').value;
      if (fRisk === 'high' && rs < state._medianRisk) alpha = 0.05;
      if (fRisk === 'low' && rs >= state._medianRisk) alpha = 0.05;
      color = interpolateColor('#2A9D8F', '#E63946', rs);
    } else if (mode === 'celltype') {
      const ct = spot.ct || {};
      const dom = Object.entries(ct).sort((a,b)=>b[1]-a[1])[0];
      const ctNames = Object.keys(ct);
      const idx = dom ? ctNames.indexOf(dom[0]) : 0;
      const hue = (idx * 137) % 360;
      color = `hsl(${hue},70%,60%)`;
    } else if (mode === 'lr') {
      // Ligand-Reseptör modu: Plasma renk haritasi (siyah → mor → magenta → turuncu → sarı)
      const lrPairs = spot.lr_pairs || [];
      const rawLR = lrPairs.length > 0
        ? Math.max(...lrPairs.map(p => p.score || 0))
        : 0;
      // Normalize against dataset max (computed once per render at top of spots loop)
      const t = state._lrMax > 0 ? Math.min(rawLR / state._lrMax, 1) : 0;
      color = lrPlasmaColor(t);
    } else if (mode === 'pathway') {
      const activePathway = document.getElementById('filter-pathway').value;
      const rawVal = (spot.pathways && spot.pathways[activePathway]) || 0;
      const denom = (state._pathwayMax - state._pathwayMin) || 1;
      const t = Math.min(Math.max((rawVal - state._pathwayMin) / denom, 0), 1);
      color = pathwayPlasmaColor(t);
    }

    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.globalAlpha = alpha;
    ctx.fill();
    ctx.globalAlpha = 1.0;
  });

  // Stats
  updateViewerStats(spots, ZONES);
  
  // Legend
  updateLegend(mode, data);

  // Zoom / Pan Events & Tooltip Handler
  if (!canvas.dataset.panZoomSet) {
    canvas.dataset.panZoomSet = "1";
    let isDragging = false;
    let isMoved = false;
    let startX, startY;

    // Tooltip listeners
    canvas.addEventListener('mousemove', (e) => {
      if (isDragging || !state.gnnData) return;
      showSpotTooltip(e, canvas, state.gnnData.spots, (state.gnnData.metadata && state.gnnData.metadata.zones) || [], (x, y) => {
        const lx = (state._offsetX || 0) + (x * state.spatialScale) * (state._renderScale || 1);
        const ly = (state._offsetY || 0) + (y * state.spatialScale) * (state._renderScale || 1);
        return {
          x: lx * state.viewTransform.k + state.viewTransform.x,
          y: ly * state.viewTransform.k + state.viewTransform.y
        };
      }, 5 * state.viewTransform.k * (state._renderScale || 1));
    });
    canvas.addEventListener('mouseleave', () => document.getElementById('spot-tooltip').classList.add('hidden'));
    
    canvas.addEventListener('mousedown', e => {
      isDragging = true;
      isMoved = false;
      startX = e.clientX - state.viewTransform.x;
      startY = e.clientY - state.viewTransform.y;
      canvas.style.cursor = 'grabbing';
    });
    
    window.addEventListener('mousemove', e => {
      if (!isDragging) return;
      isMoved = true;
      state.viewTransform.x = e.clientX - startX;
      state.viewTransform.y = e.clientY - startY;
      requestAnimationFrame(renderSpatialCanvas);
    });
    
    window.addEventListener('mouseup', e => {
      if (isDragging && !isMoved && state.gnnData && e.target === canvas) {
        handleSpotClick(e, canvas, state.gnnData.spots, (x, y) => {
          const lx = (state._offsetX || 0) + (x * state.spatialScale) * (state._renderScale || 1);
          const ly = (state._offsetY || 0) + (y * state.spatialScale) * (state._renderScale || 1);
          return {
            x: lx * state.viewTransform.k + state.viewTransform.x,
            y: ly * state.viewTransform.k + state.viewTransform.y
          };
        }, 5 * state.viewTransform.k * (state._renderScale || 1));
      }
      isDragging = false;
      canvas.style.cursor = 'grab';
    });
    
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      const newK = Math.max(0.5, Math.min(state.viewTransform.k * zoomFactor, 10));
      const ratio = newK / state.viewTransform.k;
      
      state.viewTransform.x = mouseX - (mouseX - state.viewTransform.x) * ratio;
      state.viewTransform.y = mouseY - (mouseY - state.viewTransform.y) * ratio;
      state.viewTransform.k = newK;
      
      updateZoomBadge();
      requestAnimationFrame(renderSpatialCanvas);
    }, { passive: false });
  }
}

function updateZoomBadge() {
  const badge = document.getElementById('zoom-level-badge');
  if (badge && state.viewTransform) {
    badge.textContent = Math.round(state.viewTransform.k * 100) + '%';
  }
}

function resetView() {
  state.viewTransform = { x: 0, y: 0, k: 1 };
  updateZoomBadge();
  renderSpatialCanvas();
}

function zoomIn() {
  if (!state.viewTransform) state.viewTransform = { x: 0, y: 0, k: 1 };
  const canvas = document.getElementById('spatial-canvas');
  const cx = canvas.width / 2, cy = canvas.height / 2;
  const newK = Math.min(state.viewTransform.k * 1.25, 10);
  const ratio = newK / state.viewTransform.k;
  state.viewTransform.x = cx - (cx - state.viewTransform.x) * ratio;
  state.viewTransform.y = cy - (cy - state.viewTransform.y) * ratio;
  state.viewTransform.k = newK;
  updateZoomBadge();
  renderSpatialCanvas();
}

function zoomOut() {
  if (!state.viewTransform) state.viewTransform = { x: 0, y: 0, k: 1 };
  const canvas = document.getElementById('spatial-canvas');
  const cx = canvas.width / 2, cy = canvas.height / 2;
  const newK = Math.max(state.viewTransform.k * 0.8, 0.5);
  const ratio = newK / state.viewTransform.k;
  state.viewTransform.x = cx - (cx - state.viewTransform.x) * ratio;
  state.viewTransform.y = cy - (cy - state.viewTransform.y) * ratio;
  state.viewTransform.k = newK;
  updateZoomBadge();
  renderSpatialCanvas();
}

function interpolateColor(c1, c2, t) {
  const p = (hex) => parseInt(hex.slice(1), 16);
  const r1 = (p(c1) >> 16) & 0xff, g1 = (p(c1) >> 8) & 0xff, b1 = p(c1) & 0xff;
  const r2 = (p(c2) >> 16) & 0xff, g2 = (p(c2) >> 8) & 0xff, b2 = p(c2) & 0xff;
  const r = Math.round(r1 + (r2-r1)*t), g = Math.round(g1 + (g2-g1)*t), b = Math.round(b1 + (b2-b1)*t);
  return `rgb(${r},${g},${b})`;
}

// Jet/Rainbow benzeri yüksek kontrastlı 5-duraklı LR renk haritası
// 0.00 → İndigo/Mavi (#4f46e5), 0.25 → Turkuaz (#06b6d4), 0.50 → Yeşil (#10b981)
// 0.75 → Turuncu (#f97316), 1.00 → Kırmızı (#ef4444)
function lrPlasmaColor(t) {
  // [stop, r, g, b]
  const stops = [
    [0.00,  79,  70, 229],   // #4f46e5 — İndigo/Mavi (Düşük)
    [0.25,   6, 182, 212],   // #06b6d4 — Turkuaz
    [0.50,  16, 185, 129],   // #10b981 — Zümrüt Yeşili
    [0.75, 249, 115,  22],   // #f97316 — Parlak Turuncu
    [1.00, 239,  68,  68]    // #ef4444 — Kırmızı (Yüksek)
  ];
  // İki duraklı arası lineer interpolasyon
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, r0, g0, b0] = stops[i];
    const [t1, r1, g1, b1] = stops[i + 1];
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0);
      return `rgb(${Math.round(r0+(r1-r0)*f)},${Math.round(g0+(g1-g0)*f)},${Math.round(b0+(b1-b0)*f)})`;
    }
  }
  return 'rgb(239, 68, 68)';
}

function updateViewerStats(spots, ZONES) {
  const el = document.getElementById('viewer-stats');
  const domZoneCounts = {};
  spots.forEach(s => {
    const zi = ZONES.map(z => s.zones[z]||0);
    const dz = ZONES[zi.indexOf(Math.max(...zi))];
    domZoneCounts[dz] = (domZoneCounts[dz]||0)+1;
  });
  const topZone = Object.entries(domZoneCounts).sort((a,b)=>b[1]-a[1])[0];
  const avgDrug = (spots.reduce((a,s)=>a+(s.drug_score||0),0)/spots.length).toFixed(3);
  const avgRisk = (spots.reduce((a,s)=>a+(s.tcga_risk||0),0)/spots.length).toFixed(3);
  const avgConf = (spots.reduce((a,s)=>a+(s.deconv_confidence||0),0)/spots.length).toFixed(3);
  el.innerHTML = `
    <span class="stat-badge">🎯 ${spots.length} spot</span>
    <span class="stat-badge">🗺️ ${topZone ? topZone[0] : 'N/A'}</span>
    <span class="stat-badge">💊 Drug: ${avgDrug}</span>
    <span class="stat-badge">✅ Deconv Conf: ${avgConf}</span>`;
}

function closeSpotDetails() {
  document.getElementById('spot-details-card').classList.add('hidden');
}

function handleSpotClick(e, canvas, spots, toCanvasFunc, r) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const mouseX = (e.clientX - rect.left) * scaleX;
  const mouseY = (e.clientY - rect.top) * scaleY;

  let clickedSpot = null;
  // tersten tara (üstte çizileni almak için)
  for (let i = spots.length - 1; i >= 0; i--) {
    const s = spots[i];
    const {x: cx, y: cy} = toCanvasFunc(s.x, s.y);
    const dist = Math.hypot(mouseX - cx, mouseY - cy);
    if (dist <= r) {
      clickedSpot = s;
      break;
    }
  }

  if (!clickedSpot) return;

  const card = document.getElementById('spot-details-card');
  document.getElementById('sd-title').textContent = `Spot #${clickedSpot.id || '?'} Detayları`;

  // CT List
  const ctObj = clickedSpot.ct || {};
  const sortedCT = Object.entries(ctObj).sort((a,b)=>b[1]-a[1]).slice(0, 4);
  document.getElementById('sd-celltypes').innerHTML = sortedCT.map(([c, v]) => 
    `<li><span>${c}</span> <span style="font-family:var(--mono)">%${(v*100).toFixed(1)}</span></li>`
  ).join('');

  // LR List
  const lrArr = clickedSpot.lr_pairs || [];
  const sortedLR = [...lrArr].sort((a,b)=>(b.score||0)-(a.score||0)).slice(0, 5);
  document.getElementById('sd-lr').innerHTML = sortedLR.length ? sortedLR.map(lr => 
    `<li><span>${lr.ligand} → ${lr.receptor}</span> <span style="font-family:var(--mono); color:var(--accent)">${(lr.score||0).toFixed(2)}</span></li>`
  ).join('') : '<li>Veri yok</li>';

  // Drug
  if (clickedSpot.drug && clickedSpot.drug !== 'N/A') {
    document.getElementById('sd-drug').innerHTML = `
      <div style="font-weight:bold; color:#F4A261">${clickedSpot.drug}</div>
      <div style="color:var(--text-muted); margin-top:4px;">Hedef: ${clickedSpot.drug_target}</div>
      <div style="color:var(--text-muted);">Uyum Skoru: ${(clickedSpot.drug_score||0).toFixed(2)}</div>
    `;
  } else {
    document.getElementById('sd-drug').innerHTML = '<div style="color:var(--text-muted)">Öne çıkan hedef yok</div>';
  }

  card.classList.remove('hidden');
}

function showSpotTooltip(e, canvas, spots, ZONES, toCanvasFunc, r) {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const cx_ = mx * scaleX, cy_ = my * scaleY;

  let closest = null, minD = Infinity;
  spots.forEach(s => {
    const {x: cx, y: cy} = toCanvasFunc(s.x, s.y);
    const d = Math.hypot(cx - cx_, cy - cy_);
    if (d < minD) { minD = d; closest = s; }
  });

  const tt = document.getElementById('spot-tooltip');
  if (!closest || minD > 20) { tt.classList.add('hidden'); return; }

  const zi = ZONES.map(z => closest.zones[z]||0);
  const domZone = ZONES[zi.indexOf(Math.max(...zi))];
  const ct = closest.ct || {};
  const domCT = Object.entries(ct).sort((a,b)=>b[1]-a[1]).slice(0,3);

  // Ligand-Reseptör kısmı
  const lrPairs = closest.lr_pairs || [];
  const topLR = lrPairs.sort((a,b)=>(b.score||0)-(a.score||0)).slice(0,3);
  const lrHtml = topLR.length > 0
    ? `<div class="tt-zone" style="color:#00d4ff;margin-top:8px;">🔗 Ligand-Reseptör</div>
       ${topLR.map(p => `<div class="tt-row"><span>${p.ligand||'?'} → ${p.receptor||'?'}</span><span class="tt-val">${((p.score||0)).toFixed(3)}</span></div>`).join('')}`
    : '';

  tt.innerHTML = `
    <div class="tt-zone">🗺️ ${domZone}</div>
    ${domCT.map(([k,v])=>`<div class="tt-row"><span>${k}</span><span class="tt-val">${(v*100).toFixed(1)}%</span></div>`).join('')}
    <div class="tt-row"><span>💊 Drug</span><span class="tt-val">${closest.drug||'N/A'}</span></div>
    <div class="tt-row"><span>✅ Confidence</span><span class="tt-val">${((closest.deconv_confidence||0)*100).toFixed(1)}%</span></div>
    <div class="tt-row"><span>📊 Entropy</span><span class="tt-val">${(closest.deconv_entropy||0).toFixed(2)}</span></div>
    ${lrHtml}`;

  tt.style.left = (mx + 14) + 'px';
  tt.style.top  = (my - 10) + 'px';
  tt.classList.remove('hidden');
}

// ══════════════════════════════════════════════════════════════
// FIGURES
// ══════════════════════════════════════════════════════════════
async function loadFigures() {
  if (!state.outputDir) { alert('Önce bir analiz çalıştırın.'); return; }

  const res = await api.backendRequest(`/results/figures?output_dir=${encodeURIComponent(state.outputDir)}`, 'GET', {});
  const gallery = document.getElementById('figures-gallery');
  gallery.innerHTML = '';

  if (!res.figures || res.figures.length === 0) {
    gallery.innerHTML = '<div class="gallery-placeholder"><p>Henüz figür bulunamadı.</p></div>';
    return;
  }

  res.figures.forEach(fig => {
    const item = document.createElement('div');
    item.className = 'fig-item';
    item.innerHTML = `
      <img src="local://${encodeURI(fig.path)}" alt="${fig.name}" loading="lazy">
      <div class="fig-item-name">${fig.name.replace(/_/g,' ')}</div>`;
    item.onclick = () => api.openOutputFolder(fig.path);
    gallery.appendChild(item);
  });
}

// ══════════════════════════════════════════════════════════════
// REPORT
// ══════════════════════════════════════════════════════════════
async function loadReport() {
  if (!state.outputDir) { alert('Önce bir analiz çalıştırın.'); return; }

  const patientId = document.getElementById('patient-id').value || 'Patient_A';
  const htmlPath  = `${state.outputDir}/reports/Klinik_Rapor_${patientId}.html`;
  const exists    = await api.fileExists(htmlPath);

  const wrapper = document.getElementById('report-frame-wrapper');
  if (!exists) {
    wrapper.innerHTML = '<div class="gallery-placeholder"><p>Rapor henüz oluşturulmadı.</p></div>';
    return;
  }

  wrapper.innerHTML = `<iframe src="local://${encodeURI(htmlPath)}" title="Klinik Rapor"></iframe>`;
}

async function openReport() {
  const patientId = document.getElementById('patient-id').value || 'Patient_A';
  if (!state.outputDir) { alert('Önce bir analiz çalıştırın.'); return; }

  const pdfPath  = `${state.outputDir}/reports/Klinik_Rapor_${patientId}.pdf`;
  const htmlPath = `${state.outputDir}/reports/Klinik_Rapor_${patientId}.html`;

  const hasPDF  = await api.fileExists(pdfPath);
  const hasHTML = await api.fileExists(htmlPath);

  if (hasPDF)       api.openOutputFolder(pdfPath);
  else if (hasHTML) api.openOutputFolder(htmlPath);
  else alert('Rapor bulunamadı, önce analizi tamamlayın.');
}

async function openOutputFolder() {
  if (!state.outputDir) return;
  api.openOutputFolder(state.outputDir);
}

// ══════════════════════════════════════════════════════════════
// AUTO-UPDATE UI
// ══════════════════════════════════════════════════════════════
let _updateUrl = '';

function openUpdateUrl() {
  if (_updateUrl) {
    api.openExternal(_updateUrl);
  }
}

async function manualUpdateCheck() {
  const btn = document.querySelector('.btn-update-check');
  if (btn) { btn.textContent = '⏳'; btn.disabled = true; }
  await api.checkForUpdates();
  setTimeout(() => {
    if (btn) { btn.textContent = '🔄'; btn.disabled = false; }
  }, 3000);
}


// ══════════════════════════════════════════════════════════════
// HELPERS
// ══════════════════════════════════════════════════════════════
function makeRow(label, value) {
  return `<tr><td style="color:var(--text-muted); width:55%">${label}</td><td style="font-family:var(--mono); font-weight:600;">${value}</td></tr>`;
}

// ══════════════════════════════════════════════════════════════
// 4.4 — DEKONVOLÜSYON KALİTE PANELİ
// ══════════════════════════════════════════════════════════════
async function loadDeconvQuality() {
  if (!state.outputDir) { alert('Önce bir analiz çalıştırın.'); return; }

  try {
    const q = await api.backendRequest(
      `/results/deconv-quality?output_dir=${encodeURIComponent(state.outputDir)}`, 'GET', {}
    );

    document.getElementById('quality-placeholder').classList.add('hidden');
    document.getElementById('quality-content').classList.remove('hidden');

    // Grade card
    const circle = document.getElementById('grade-circle');
    circle.textContent = q.quality_grade;
    circle.style.background = `conic-gradient(${q.quality_color} 0%, ${q.quality_color}33 100%)`;
    circle.style.color = q.quality_color;
    circle.style.borderColor = q.quality_color;
    circle.style.boxShadow = `0 0 20px ${q.quality_color}55`;
    document.getElementById('grade-label').textContent = q.quality_label;
    document.getElementById('grade-label').style.color = q.quality_color;
    document.getElementById('qm-confidence').textContent = `%${q.avg_confidence}`;
    document.getElementById('qm-entropy').textContent    = q.avg_entropy.toFixed(4);
    document.getElementById('qm-types').textContent      = q.n_cell_types;

    // Cell type table
    const tbody = document.getElementById('ct-quality-tbody');
    tbody.innerHTML = '';
    const maxProp = Math.max(...q.cell_type_table.map(r => r.mean_prop), 1);
    q.cell_type_table.forEach(row => {
      const barW = Math.round((row.mean_prop / maxProp) * 100);
      const hue  = Math.round((q.cell_type_table.indexOf(row) * 137) % 360);
      tbody.innerHTML += `
        <tr>
          <td>${row.name}</td>
          <td style="font-family:var(--mono);">${row.mean_prop.toFixed(2)}%</td>
          <td style="font-family:var(--mono);">${row.dominant_spots}</td>
          <td>
            <div style="background:var(--bg-raised);border-radius:4px;height:8px;width:120px;">
              <div style="background:hsl(${hue},70%,55%);height:100%;border-radius:4px;width:${barW}%;transition:width 0.5s;"></div>
            </div>
          </td>
        </tr>`;
    });
  } catch (e) {
    alert(`Kalite verisi yüklenemedi: ${e.message || e}`);
  }
}

// ══════════════════════════════════════════════════════════════
// 4.9 — GNN MODEL BİLGİSİ PANELİ
// ══════════════════════════════════════════════════════════════
async function loadGnnModel() {
  if (!state.outputDir) { alert('Önce bir analiz çalıştırın.'); return; }

  try {
    const m = await api.backendRequest(
      `/results/gnn-model?output_dir=${encodeURIComponent(state.outputDir)}`, 'GET', {}
    );

    document.getElementById('model-placeholder').classList.add('hidden');
    document.getElementById('model-content').classList.remove('hidden');

    // File info
    document.getElementById('model-file-tbody').innerHTML =
      makeRow('Dosya', m.model_file) +
      makeRow('Boyut', m.model_size_mb ? `${m.model_size_mb} MB` : 'N/A') +
      makeRow('Spot Sayısı', m.output.n_spots.toLocaleString()) +
      makeRow('Zone Sayısı', m.output.zones.length) +
      makeRow('Hücre Tipi', m.output.ct_names.length);

    // Architecture
    const arch = m.architecture;
    document.getElementById('model-arch-tbody').innerHTML =
      makeRow('Hidden Dim', arch.hidden_dim) +
      makeRow('Attention Heads', arch.attention_heads) +
      makeRow('GAT Katmanları', arch.gat_layers) +
      makeRow('SAGE Katmanları', arch.sage_layers) +
      makeRow('Dropout', arch.dropout) +
      makeRow('Learning Rate', arch.learning_rate < 0.001 ? Number(arch.learning_rate).toExponential(3) : arch.learning_rate);

    // Training
    const tr = m.training;
    document.getElementById('model-train-tbody').innerHTML =
      makeRow('İstenen Epoch', tr.epochs_requested) +
      makeRow('Eğitilen Epoch', tr.epochs_trained) +
      makeRow('Patience', tr.patience) +
      makeRow('En İyi Val Loss', tr.best_val_loss.toFixed(6)) +
      makeRow('Test MSE', tr.test_mse.toFixed(6)) +
      makeRow('Optuna', tr.optuna_used ? '✅ Kullanıldı' : '⬜ Kullanılmadı');

    // Correlations
    const ctbody = document.getElementById('model-corr-tbody');
    ctbody.innerHTML = '';
    for (const [ct, vals] of Object.entries(m.correlations)) {
      const pr  = vals.pearson_r;
      const sig = Math.abs(pr) > 0.7 ? '🟢 Güçlü' : Math.abs(pr) > 0.5 ? '🟡 Orta' : '🔴 Zayıf';
      ctbody.innerHTML += `<tr>
        <td>${ct}</td>
        <td style="font-family:var(--mono);">${pr.toFixed(4)}</td>
        <td style="font-family:var(--mono);">${vals.spearman_r.toFixed(4)}</td>
        <td>${sig}</td>
      </tr>`;
    }
  } catch (e) {
    alert(`Model bilgisi yüklenemedi: ${e.message || e}`);
  }
}

// ══════════════════════════════════════════════════════════════
// 4.5 — MULTI-HASTA KARŞILAŞTIRMA
// ══════════════════════════════════════════════════════════════
async function browseMultipatientDir(which) {
  const path = await api.selectFolder();
  if (path) {
    document.getElementById(`mp-dir-${which}`).value = path;
  }
}

async function comparePatients() {
  const dirA = document.getElementById('mp-dir-a').value;
  const dirB = document.getElementById('mp-dir-b').value;
  if (!dirA || !dirB) { alert('Her iki hasta klasörünü de seçin.'); return; }

  const result = document.getElementById('mp-compare-result');
  result.innerHTML = '<p style="color:var(--text-muted)">Yükleniyor...</p>';

  try {
    // Load both summaries via backend
    const [sumA, sumB] = await Promise.all([
      api.backendRequest(`/results/summary?output_dir=${encodeURIComponent(dirA)}`, 'GET', {}),
      api.backendRequest(`/results/summary?output_dir=${encodeURIComponent(dirB)}`, 'GET', {})
    ]);

    const dA = sumA.deconvolution || {};
    const dB = sumB.deconvolution || {};
    const gA = sumA.gnn || {};
    const gB = sumB.gnn || {};

    const patA = dA.patient_id || 'Hasta A';
    const patB = dB.patient_id || 'Hasta B';

    // Build comparison table
    const metrics = [
      ['Dekonv. Güven', `%${((dA.avg_confidence||0)*100).toFixed(1)}`, `%${((dB.avg_confidence||0)*100).toFixed(1)}`],
      ['Dekonv. Entropi', (dA.avg_entropy||0).toFixed(4), (dB.avg_entropy||0).toFixed(4)],
      ['Hücre Tipi Sayısı', dA.n_cell_types||'N/A', dB.n_cell_types||'N/A'],
      ['GNN Test MSE', (gA.test_mse||0).toFixed(6), (gB.test_mse||0).toFixed(6)],
      ['GNN Val Loss', (gA.best_val_loss||0).toFixed(6), (gB.best_val_loss||0).toFixed(6)],
    ];

    // Cell type comparison
    const allCT = new Set([
      ...Object.keys(dA.mean_proportions||{}),
      ...Object.keys(dB.mean_proportions||{})
    ]);
    const ctRows = [...allCT].map(ct => {
      const pA = ((dA.mean_proportions||{})[ct]||0)*100;
      const pB = ((dB.mean_proportions||{})[ct]||0)*100;
      const diff = pB - pA;
      const arrow = diff > 1 ? '⬆️' : diff < -1 ? '⬇️' : '➡️';
      return `<tr>
        <td>${ct}</td>
        <td style="font-family:var(--mono);">${pA.toFixed(1)}%</td>
        <td style="font-family:var(--mono);">${pB.toFixed(1)}%</td>
        <td style="font-family:var(--mono);">${arrow} ${diff>0?'+':''}${diff.toFixed(1)}%</td>
      </tr>`;
    }).join('');

    result.innerHTML = `
      <h3 style="margin-bottom:16px;">${patA} vs ${patB}</h3>
      <table class="data-table" style="margin-bottom:24px;">
        <thead><tr><th>Metrik</th><th>${patA}</th><th>${patB}</th></tr></thead>
        <tbody>${metrics.map(([l,a,b])=>`<tr><td>${l}</td><td style="font-family:var(--mono);">${a}</td><td style="font-family:var(--mono);">${b}</td></tr>`).join('')}</tbody>
      </table>
      <h3 style="margin-bottom:12px;">TME Kompozisyon Farkı</h3>
      <table class="data-table">
        <thead><tr><th>Hücre Tipi</th><th>${patA}</th><th>${patB}</th><th>Δ</th></tr></thead>
        <tbody>${ctRows}</tbody>
      </table>`;
  } catch (e) {
    result.innerHTML = `<p style="color:var(--danger)">❌ Karşılaştırma hatası: ${e.message || e}</p>`;
  }
}

// ══════════════════════════════════════════════════════════════
// NEXT-GEN CLINICAL DECISION SUPPORT FEATURES
// ══════════════════════════════════════════════════════════════

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

  // 1. Populate L-R Select in Signaling Panel
  const commData = data.cell_cell_communication || {};
  const lrSelect = document.getElementById('signaling-lr-select');
  if (lrSelect) {
    const lrKeys = Object.keys(commData);
    if (lrKeys.length > 0) {
      lrSelect.innerHTML = lrKeys.map(k => `<option value="${k}">${k}</option>`).join('');
      document.getElementById('signaling-placeholder').classList.add('hidden');
      document.getElementById('signaling-container').classList.remove('hidden');
    } else {
      document.getElementById('signaling-placeholder').classList.remove('hidden');
      document.getElementById('signaling-container').classList.add('hidden');
    }
  }

  // 2. Populate Cell Type checkboxes in Signaling Panel
  const ctList = (data.metadata && (data.metadata.cell_types || data.metadata.ct_names)) || [];
  const ctContainer = document.getElementById('signaling-ct-checkboxes');
  if (ctContainer) {
    ctContainer.innerHTML = ctList.map(ct => `
      <label class="checkbox-item">
        <input type="checkbox" value="${ct}" checked onchange="renderSignalingDiagram()" style="accent-color:var(--accent);">
        <span>${ct}</span>
      </label>
    `).join('');
  }

  // 3. Render Signaling Diagram
  renderSignalingDiagram();

  // 4. Render Zonal Contrast Charts
  const contrastData = data.zonal_contrast || {};
  const pathwaysContrastGrid = document.getElementById('pathways-contrast-grid');
  const lrContrastGrid = document.getElementById('lr-contrast-grid');
  
  if (pathwaysContrastGrid && contrastData.pathways) {
    document.getElementById('contrast-placeholder').classList.add('hidden');
    document.getElementById('contrast-container').classList.remove('hidden');
    
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
  
  // Clear SVG and existing gradients
  svg.innerHTML = '';
  
  const commData = state.gnnData.cell_cell_communication || {};
  const lrPair = document.getElementById('signaling-lr-select').value;
  if (!lrPair || !commData[lrPair]) {
    svg.innerHTML = `<text x="0" y="0" text-anchor="middle" fill="var(--text-muted)">Seçili L-R çifti için veri bulunamadı.</text>`;
    return;
  }
  
  const pairData = commData[lrPair];
  
  // Get active cell types from checkboxes
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
    
    // Hover event for sector
    path.addEventListener('mouseover', (e) => {
      highlightSector(ct);
      showChordTooltip(e, `<strong>${ct}</strong><br>Toplam İletişim Gücü: ${ctTotals[ct].toFixed(3)}`);
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
      
      const gradId = `grad-${a.replace(/\s+/g, '')}-${b.replace(/\s+/g, '')}`;
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
        svg.appendChild(grad);
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
          <strong>${a} (Kendi Kendine)</strong><br>
          Etkileşim Gücü: ${ab_val.toFixed(4)}
        `;
      } else {
        tooltipContent = `
          <strong>${a} ⇄ ${b} İletişimi</strong><br>
          <span style="color:#00d4ff">${a} → ${b}:</span> ${ab_val.toFixed(4)}<br>
          <span style="color:#ff6b6b">${b} → ${a}:</span> ${ba_val.toFixed(4)}<br>
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
  tt.innerHTML = content;
  tt.classList.remove('hidden');
  moveChordTooltip(e);
}

function moveChordTooltip(e) {
  const tt = document.getElementById('chord-tooltip');
  if (!tt) return;
  const wrapper = document.getElementById('chord-diagram-wrapper');
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
    btn.style.borderBottomColor = 'transparent';
    btn.style.color = 'var(--text-muted)';
  });
  
  const activeBtn = document.getElementById(`btn-tab-${tab}`);
  if (activeBtn) {
    activeBtn.classList.add('active');
    activeBtn.style.borderBottomColor = 'var(--accent)';
    activeBtn.style.color = 'var(--text)';
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
    const width = maxVal > 0 ? (val / maxVal) * barMaxWidth : 0;
    
    rowsHtml += `
      <g class="bar-row">
        <text x="10" y="${y + 10}" fill="var(--text-muted)" font-size="11px" font-weight="600">${zone}</text>
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
        <span>📊 ${title}</span>
      </h3>
      <svg width="100%" height="165" style="overflow:visible;">
        ${rowsHtml}
      </svg>
    </div>
  `;
}

// ══════════════════════════════════════════════════════════════
// EOF
// ══════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════
// EOF
// ══════════════════════════════════════════════════════════════
