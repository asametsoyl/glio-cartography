/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — Startup and Licensing (renderer)
   ══════════════════════════════════════════════════════════ */

/* global state, lastBackendLogs, api, isDev, showWarningToast, showErrorToast */

// ── DOM Cache Object ──────────────────────────────────────────
const DOM = {
  logPreview: null,
  backendDot: null,
  backendStatus: null,
  licenseInput: null,
  licenseError: null,
  licenseOverlay: null,
  licenseOverlayClose: null,
  licenseFormContainer: null,
  licenseCheckingState: null,
  checkingMsg: null,
  checkingSubmsg: null,
  premiumLoader: null,
  connectionErrorContainer: null,
  customPythonPathDisplay: null,
  selectedPythonPathText: null,
  btnDownloadRuntime: null,
  downloadProgressContainer: null,
  downloadProgressStatus: null,
  downloadProgressPercent: null,
  downloadProgressBarFill: null,
  downloadProgressInfo: null,
  btnSelectPython: null,
  btnRetryConnection: null,
  machineIdDisplay: null,
  btnCopy: null,
};

// Populate element cache
function cacheDOM() {
  DOM.logPreview = document.getElementById('connection-log-preview');
  DOM.backendDot = document.getElementById('backend-dot');
  DOM.backendStatus = document.getElementById('backend-status');
  DOM.licenseInput = document.getElementById('license-input');
  DOM.licenseError = document.getElementById('license-error');
  DOM.licenseOverlay = document.getElementById('license-overlay');
  DOM.licenseOverlayClose = document.getElementById('license-overlay-close');
  DOM.licenseFormContainer = document.getElementById('license-form-container');
  DOM.licenseCheckingState = document.getElementById('license-checking-state');
  DOM.checkingMsg = document.getElementById('checking-msg');
  DOM.checkingSubmsg = document.getElementById('checking-submsg');
  DOM.premiumLoader = document.getElementById('premium-loader-el');
  DOM.connectionErrorContainer = document.getElementById('connection-error-container');
  DOM.customPythonPathDisplay = document.getElementById('custom-python-path-display');
  DOM.selectedPythonPathText = document.getElementById('selected-python-path-text');
  DOM.btnDownloadRuntime = document.getElementById('btn-download-runtime');
  DOM.downloadProgressContainer = document.getElementById('download-progress-container');
  DOM.downloadProgressStatus = document.getElementById('download-progress-status');
  DOM.downloadProgressPercent = document.getElementById('download-progress-percent');
  DOM.downloadProgressBarFill = document.getElementById('download-progress-bar-fill');
  DOM.downloadProgressInfo = document.getElementById('download-progress-info');
  DOM.btnSelectPython = document.getElementById('btn-select-python');
  DOM.btnRetryConnection = document.getElementById('btn-retry-connection');
  DOM.machineIdDisplay = document.getElementById('machine-id-display');
  DOM.btnCopy = document.querySelector('.btn-copy');
}

// Initialise caching
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', cacheDOM);
} else {
  cacheDOM();
}

// ── Shared UI Utilities ───────────────────────────────────────
function toggleElement(el, show) {
  if (el) el.classList.toggle('hidden', !show);
}

function setText(el, text) {
  if (el) el.textContent = text;
}

// Validate backend state structure (Anti-malformed-state checking)
function isValidBackendState(obj) {
  return obj && typeof obj === 'object' && 
         typeof obj.status === 'string' &&
         ['ready', 'failed', 'runtime-missing', 'downloading', 
          'extracting', 'configuring', 'downloading_vc', 
          'installing_vc', 'completed', 'starting'].includes(obj.status);
}

// ── Startup & License Logic ──────────────────────────────────
function handleBackendLog(msg) {
  lastBackendLogs.push(msg);
  if (lastBackendLogs.length > 80) lastBackendLogs.shift();
  
  if (DOM.logPreview) {
    DOM.logPreview.textContent = lastBackendLogs.join('\n');
    DOM.logPreview.scrollTop = DOM.logPreview.scrollHeight;
  }
}

async function checkBackendHealth() {
  // Skip polling during active setup download
  if (state.downloading) return;
  
  try {
    const stateObj = await api.getBackendState();
    if (!isValidBackendState(stateObj)) return;
    if (stateObj.status === 'runtime-missing' || stateObj.status === 'starting') return;

    const res = await api.backendRequest('/health', 'GET', {});
    setBackendStatus(res && res.status === 'ok');
  } catch (e) {
    // Only disconnect if we were once connected
    if (state.backendReady) {
      setBackendStatus(false);
    }
  }
}

function setBackendStatus(ready) {
  state.backendReady = ready;
  if (ready) {
    state.backendStartupFailed = false;
    state.bootCompleted = true; // Flag indicating the application successfully finished early boot
  } else {
    state.backendStartupFailed = true;
  }
  
  if (DOM.backendDot) {
    DOM.backendDot.className = ready ? 'status-dot connected' : 'status-dot error';
  }
  if (DOM.backendStatus) {
    DOM.backendStatus.textContent = ready ? window.i18n.t('diagnostics.connected') : window.i18n.t('diagnostics.connection_failed');
  }

  if (ready) {
    hideConnectionError();
  } else {
    // If the application has already fully booted, show a non-intrusive warning instead of blocking UI
    if (state.bootCompleted) {
      showWarningToast(window.i18n.t('diagnostics.connection_lost'));
    } else {
      showConnectionError();
    }
  }
  evaluateLaunchState();
}

// ══════════════════════════════════════════════════════════════
// LICENSE
// ══════════════════════════════════════════════════════════════
async function activateLicense() {
  try {
    const key = DOM.licenseInput ? DOM.licenseInput.value.trim().toUpperCase() : '';
    if (DOM.licenseError) DOM.licenseError.classList.add('hidden');

    if (!key) { 
      showLicenseError(window.i18n.t('license.enter_key')); 
      return; 
    }

    // Basic format validator
    if (!key.startsWith('GCARTO-')) {
      showLicenseError(window.i18n.t('license.invalid_format'));
      return;
    }

    const result = await api.validateLicense(key);
    if (result.valid) {
      await api.saveLicense(key);
      state.licenseValid = true;
      
      const stateObj = await api.getBackendState();
      if (isValidBackendState(stateObj) && stateObj.status === 'runtime-missing') {
        triggerAutoDownload();
      } else {
        if (state.backendReady) {
          hideLicense();
        } else {
          showLicenseWaitingState();
        }
      }
    } else {
      showLicenseError(result.reason || window.i18n.t('license.invalid_key'));
    }
  } catch (err) {
    console.error('[License] Activation error:', err);
    showErrorToast(
      isDev 
        ? `${window.i18n.t('license.validation_error')}: ${err.message}` 
        : window.i18n.t('license.validation_failed_retry')
    );
  }
}

function showLicenseError(msg) {
  if (DOM.licenseError) {
    DOM.licenseError.textContent = '❌ ' + msg;
    DOM.licenseError.classList.remove('hidden');
  }
}

function hideLicense() {
  state.manualLicenseView = false;
  if (DOM.licenseOverlay) DOM.licenseOverlay.classList.remove('active');
  if (DOM.licenseOverlayClose) DOM.licenseOverlayClose.classList.add('hidden');
}

function showLicenseInfo() {
  state.manualLicenseView = true;
  showLicenseFormState();
  if (DOM.licenseOverlayClose) {
    DOM.licenseOverlayClose.classList.toggle('hidden', !state.licenseValid);
  }
  if (DOM.licenseOverlay) DOM.licenseOverlay.classList.add('active');
}

function closeLicenseOverlay() {
  state.manualLicenseView = false;
  hideLicense();
}

function showLicenseWaitingState() {
  toggleElement(DOM.licenseFormContainer, false);
  toggleElement(DOM.licenseCheckingState, true);
  
  if (state.licenseValid && state.backendStartupFailed) {
    showConnectionError();
  } else {
    if (DOM.checkingMsg) DOM.checkingMsg.textContent = window.i18n.t('license.recognized_wait');
    if (DOM.checkingSubmsg) DOM.checkingSubmsg.textContent = window.i18n.t('license.connecting_server');
    
    if (DOM.premiumLoader) DOM.premiumLoader.style.display = '';
    toggleElement(DOM.connectionErrorContainer, false);
  }
}

function showLicenseFormState() {
  toggleElement(DOM.licenseCheckingState, false);
  toggleElement(DOM.licenseFormContainer, true);
}

function evaluateLaunchState() {
  if (state.downloading) return; // Prevent interference during installation
  
  if (state.licenseValid && state.backendReady && !state.manualLicenseView) {
    hideLicense();
  } else if (state.licenseValid && state.backendStartupFailed && !state.bootCompleted) {
    showConnectionError();
  }
}

function showConnectionError() {
  if (state.downloading) {
    return; // Don't interrupt active download/installation
  }

  if (DOM.licenseOverlay) DOM.licenseOverlay.classList.add('active');
  toggleElement(DOM.licenseCheckingState, true);
  toggleElement(DOM.licenseFormContainer, false);

  if (DOM.checkingMsg) DOM.checkingMsg.textContent = window.i18n.t('diagnostics.component_connection_error');
  
  // Safe DOM construction to prevent innerHTML XSS vulnerabilities
  if (DOM.checkingSubmsg) {
    DOM.checkingSubmsg.textContent = '';
    DOM.checkingSubmsg.appendChild(document.createTextNode(window.i18n.t('diagnostics.components_failed_to_start')));
    DOM.checkingSubmsg.appendChild(document.createElement('br'));
    DOM.checkingSubmsg.appendChild(document.createTextNode(window.i18n.t('diagnostics.components_install_or_internet_check')));
  }
  
  // Hide loading ring
  if (DOM.premiumLoader) DOM.premiumLoader.style.display = 'none';

  // Show error container
  toggleElement(DOM.connectionErrorContainer, true);
  
  updateCustomPathDisplay().catch(err => {
    console.error('[Startup] Failed to update custom path display:', err);
  });

  // Populate log preview
  if (DOM.logPreview) {
    DOM.logPreview.textContent = lastBackendLogs.length > 0 
      ? lastBackendLogs.join('\n') 
      : window.i18n.t('diagnostics.waiting_for_connection_no_log');
    DOM.logPreview.scrollTop = DOM.logPreview.scrollHeight;
  }
}

async function updateCustomPathDisplay() {
  try {
    const savedPath = await api.getCustomPythonPath();
    if (savedPath) {
      if (DOM.selectedPythonPathText) DOM.selectedPythonPathText.textContent = savedPath;
      toggleElement(DOM.customPythonPathDisplay, true);
    } else {
      toggleElement(DOM.customPythonPathDisplay, false);
    }
  } catch (e) {
    console.error('Failed to get custom python path:', e);
  }
}

function hideConnectionError() {
  if (DOM.premiumLoader) DOM.premiumLoader.style.display = '';
  toggleElement(DOM.connectionErrorContainer, false);

  if (state.licenseValid && state.backendStartupFailed) {
    // Keep error message
  } else {
    if (DOM.checkingMsg) DOM.checkingMsg.textContent = window.i18n.t('license.initializing');
    if (DOM.checkingSubmsg) DOM.checkingSubmsg.textContent = window.i18n.t('license.connecting_server');
  }
}

async function selectCustomPython() {
  try {
    const selected = await api.selectPythonPath();
    if (selected) {
      console.log('User selected Python path:', selected);
      await api.saveCustomPythonPath(selected);
      updateCustomPathDisplay().catch(() => {});
      
      // Attempt restart automatically
      await retryBackendConnection();
    }
  } catch (err) {
    console.error('[Python path selection] Error:', err);
    showErrorToast(
      isDev 
        ? `${window.i18n.t('diagnostics.component_selection_error')}: ${err.message}` 
        : window.i18n.t('diagnostics.component_selection_failed')
    );
  }
}

async function retryBackendConnection() {
  try {
    toggleElement(DOM.connectionErrorContainer, false);
    if (DOM.premiumLoader) DOM.premiumLoader.style.display = '';
    
    if (DOM.checkingMsg) DOM.checkingMsg.textContent = window.i18n.t('common.restarting');
    if (DOM.checkingSubmsg) DOM.checkingSubmsg.textContent = window.i18n.t('diagnostics.components_starting');
    
    // Add separator to keep log context instead of wiping entirely
    lastBackendLogs.push('────────────────────────────────────────');
    lastBackendLogs.push(window.i18n.t('diagnostics.reconnection_attempt'));
    if (DOM.logPreview) {
      DOM.logPreview.textContent = lastBackendLogs.join('\n');
      DOM.logPreview.scrollTop = DOM.logPreview.scrollHeight;
    }

    const ok = await api.restartBackend();
    setBackendStatus(!!ok);
  } catch (err) {
    console.error('Restart backend error:', err);
    setBackendStatus(false);
  }
}

async function syncBackendState() {
  try {
    const stateObj = await api.getBackendState();
    console.log('[Sync] Received backend state:', stateObj);
    if (!isValidBackendState(stateObj)) return;

    if (stateObj.status === 'ready') {
      setBackendStatus(true);
    } else if (stateObj.status === 'failed') {
      setBackendStatus(false);
      if (stateObj.error && DOM.downloadProgressStatus) {
        DOM.downloadProgressStatus.textContent = '❌ Hata: ' + stateObj.error;
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
    downloadRuntime().catch(() => {});
  }
}

// Concurrency lock to prevent parallel runtime downloads
let downloadLock = null;

async function downloadRuntime() {
  if (state.downloading) {
    return downloadLock;
  }

  downloadLock = (async () => {
    try {
      state.downloading = true;
      if (DOM.btnDownloadRuntime) DOM.btnDownloadRuntime.disabled = true;

      // Show progress bar immediately
      showLicenseWaitingState();
      toggleElement(DOM.downloadProgressContainer, true);
      
      if (DOM.downloadProgressStatus) DOM.downloadProgressStatus.textContent = window.i18n.t('diagnostics.connecting_server_plug');
      if (DOM.checkingMsg) DOM.checkingMsg.textContent = window.i18n.t('diagnostics.components_installing');
      if (DOM.checkingSubmsg) DOM.checkingSubmsg.textContent = window.i18n.t('diagnostics.downloading_wait');
      
      const ok = await api.downloadRuntime();
      if (ok && ok.success) {
        console.log('Download success: Python saved at', ok.pythonPath);
      }
    } catch (err) {
      console.error('Download error:', err);
      state.downloading = false;
      state.downloadAttempted = false; // Allow retry

      // Show friendly error
      if (DOM.checkingMsg) DOM.checkingMsg.textContent = window.i18n.t('update.download_failed');
      if (DOM.checkingSubmsg) {
        DOM.checkingSubmsg.textContent = isDev 
          ? `${window.i18n.t('diagnostics.components_download_error')}: ${err.message}` 
          : window.i18n.t('diagnostics.components_download_failed_retry')
      }
      
      toggleElement(DOM.downloadProgressContainer, false);
      toggleElement(DOM.connectionErrorContainer, true);
      if (DOM.premiumLoader) DOM.premiumLoader.style.display = 'none';
    } finally {
      downloadLock = null;
    }
  })();

  return downloadLock;
}

function openLogFile() {
  api.openLogFile();
}

function handleDownloadProgress(data) {
  // Ensure we are in the waiting state view
  showLicenseWaitingState();

  if (DOM.downloadProgressContainer) DOM.downloadProgressContainer.classList.remove('hidden');

  const isFinished = (data.status === 'completed' || data.status === 'failed');
  state.downloading = !isFinished;

  // Disable buttons while actively download/configuring
  if (!isFinished) {
    if (DOM.btnDownloadRuntime) DOM.btnDownloadRuntime.disabled = true;
    if (DOM.btnSelectPython) DOM.btnSelectPython.disabled = true;
    if (DOM.btnRetryConnection) DOM.btnRetryConnection.disabled = true;
    
    // Hide error container and loader while setup runs
    toggleElement(DOM.connectionErrorContainer, false);
    if (DOM.premiumLoader) DOM.premiumLoader.style.display = 'none';

    if (DOM.checkingMsg) DOM.checkingMsg.textContent = window.i18n.t('diagnostics.components_installing');
    if (DOM.checkingSubmsg) DOM.checkingSubmsg.textContent = window.i18n.t('diagnostics.components_auto_configuring');
  } else {
    // Keep them disabled if completed, to prevent race conditions before auto-retry
    if (data.status !== 'completed') {
      if (DOM.btnDownloadRuntime) DOM.btnDownloadRuntime.disabled = false;
      if (DOM.btnSelectPython) DOM.btnSelectPython.disabled = false;
      if (DOM.btnRetryConnection) DOM.btnRetryConnection.disabled = false;
    }
  }

  // Update layout values
  if (data.status === 'downloading_vc') {
    if (DOM.downloadProgressStatus) DOM.downloadProgressStatus.textContent = window.i18n.t('diagnostics.downloading_system_components');
    if (DOM.downloadProgressPercent) DOM.downloadProgressPercent.textContent = `${data.percent}%`;
    if (DOM.downloadProgressBarFill) DOM.downloadProgressBarFill.style.width = `${data.percent}%`;
    if (DOM.downloadProgressInfo) DOM.downloadProgressInfo.textContent = `${data.received} MB / ${data.total} MB`;
  } else if (data.status === 'installing_vc') {
    if (DOM.downloadProgressStatus) DOM.downloadProgressStatus.textContent = window.i18n.t('diagnostics.installing_system_components');
    if (DOM.downloadProgressPercent) DOM.downloadProgressPercent.textContent = '50%';
    if (DOM.downloadProgressBarFill) {
      DOM.downloadProgressBarFill.style.width = '50%';
      DOM.downloadProgressBarFill.style.background = 'linear-gradient(90deg, #7c3aed, #00d4ff)';
    }
    if (DOM.downloadProgressInfo) DOM.downloadProgressInfo.textContent = window.i18n.t('diagnostics.admin_permission_request');
  } else if (data.status === 'downloading') {
    if (DOM.downloadProgressStatus) DOM.downloadProgressStatus.textContent = window.i18n.t('diagnostics.downloading_components');
    if (DOM.downloadProgressPercent) DOM.downloadProgressPercent.textContent = `${data.percent}%`;
    if (DOM.downloadProgressBarFill) {
      DOM.downloadProgressBarFill.style.width = `${data.percent}%`;
      DOM.downloadProgressBarFill.style.background = '';
    }
    if (DOM.downloadProgressInfo) DOM.downloadProgressInfo.textContent = `${data.received} MB / ${data.total} MB`;
  } else if (data.status === 'extracting') {
    if (DOM.downloadProgressStatus) DOM.downloadProgressStatus.textContent = window.i18n.t('diagnostics.extracting_components');
    if (DOM.downloadProgressPercent) DOM.downloadProgressPercent.textContent = '100%';
    if (DOM.downloadProgressBarFill) {
      DOM.downloadProgressBarFill.style.width = '100%';
      DOM.downloadProgressBarFill.style.background = 'linear-gradient(90deg, #7c3aed, #00d4ff)';
    }
    if (DOM.downloadProgressInfo) DOM.downloadProgressInfo.textContent = window.i18n.t('diagnostics.this_may_take_minutes');
  } else if (data.status === 'configuring') {
    if (DOM.downloadProgressStatus) DOM.downloadProgressStatus.textContent = window.i18n.t('diagnostics.configuring_components');
    if (DOM.downloadProgressPercent) DOM.downloadProgressPercent.textContent = '100%';
    if (DOM.downloadProgressInfo) DOM.downloadProgressInfo.textContent = window.i18n.t('diagnostics.configuring_completing');
  } else if (data.status === 'completed') {
    if (DOM.downloadProgressStatus) DOM.downloadProgressStatus.textContent = window.i18n.t('diagnostics.install_success');
    if (DOM.downloadProgressPercent) DOM.downloadProgressPercent.textContent = '100%';
    if (DOM.downloadProgressBarFill) {
      DOM.downloadProgressBarFill.style.width = '100%';
      DOM.downloadProgressBarFill.style.background = 'linear-gradient(90deg, #10b981, #059669)';
    }
    if (DOM.downloadProgressInfo) DOM.downloadProgressInfo.textContent = window.i18n.t('diagnostics.components_starting');
    
    // Explicitly lock retry button to avoid double-clicking
    if (DOM.btnRetryConnection) DOM.btnRetryConnection.disabled = true;

    setTimeout(() => {
      if (DOM.downloadProgressContainer) DOM.downloadProgressContainer.classList.add('hidden');
      retryBackendConnection().catch(() => {});
    }, 2000);
  } else if (data.status === 'failed') {
    if (DOM.downloadProgressStatus) DOM.downloadProgressStatus.textContent = window.i18n.t('diagnostics.install_failed');
    if (DOM.downloadProgressPercent) DOM.downloadProgressPercent.textContent = '-';
    if (DOM.downloadProgressBarFill) DOM.downloadProgressBarFill.style.width = '0%';
    if (DOM.downloadProgressInfo) DOM.downloadProgressInfo.textContent = data.error || window.i18n.t('common.unknown_error');
    
    showConnectionError();
  }
}

async function copyMachineId(btn) {
  try {
    const targetBtn = btn || DOM.btnCopy || document.querySelector('.btn-copy');
    const id = DOM.machineIdDisplay ? DOM.machineIdDisplay.textContent : '';
    if (!id) return;
    
    await navigator.clipboard.writeText(id);
    if (targetBtn) {
      targetBtn.textContent = '✅ ' + window.i18n.t('common.copied');
      setTimeout(() => { targetBtn.textContent = '📋 ' + window.i18n.t('common.copy'); }, 2000);
    }
  } catch (err) {
    console.error('[MachineID] Clipboard copy failed:', err);
    showErrorToast(window.i18n.t('license.copy_failed'));
  }
}
