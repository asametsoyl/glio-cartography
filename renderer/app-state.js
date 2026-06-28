/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — State and Configuration (renderer)
   ══════════════════════════════════════════════════════════ */

const api = window.glioAPI;

// ── State ────────────────────────────────────────────────────
const rawState = {
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

  // Compare mode and newly initialized properties
  compareDataLeft: null,
  compareDataRight: null,
  bgImageLeft: null,
  bgImageRight: null,
  bgLoadedLeft: false,
  bgLoadedRight: false,
  spatialScaleLeft: 1.0,
  spatialScaleRight: 1.0,
  compareTransform: { x: 0, y: 0, k: 1 },
  compareProfileLeft: null,
  compareProfileRight: null,
  koMagnitudes: null,
  koShifts: null,
  koText: null,
  paracrineActive: false,
  paracrineSpot: null,
  paracrineAffected: new Map(),
  viewTransform: { x: 0, y: 0, k: 1 },
  _medianRisk: null,
};

// Global state change handler for reactive side effects
function handleStateChange(prop, value, oldValue) {
  // 1. Panel/Navigation shifts
  if (prop === 'currentPanel') {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    
    const targetPanel = document.getElementById(`panel-${value}`);
    if (targetPanel) {
      targetPanel.classList.add('active');
    } else {
      console.warn(`Panel panel-${value} not found!`);
    }
    
    const targetNav = document.querySelector(`[data-panel="${value}"]`);
    if (targetNav) {
      targetNav.classList.add('active');
    }
    
    if (value === 'monitor') {
      const cancelBtn = document.getElementById('cancel-btn');
      const returnSetupBtn = document.getElementById('return-setup-btn');
      if (rawState.pipelineRunning) {
        if (cancelBtn) cancelBtn.style.display = 'inline-flex';
        if (returnSetupBtn) returnSetupBtn.style.display = 'none';
      } else {
        if (cancelBtn) cancelBtn.style.display = 'none';
        if (returnSetupBtn) returnSetupBtn.style.display = 'inline-flex';
      }
    }

    if (value === 'compare' && typeof reloadCompareSelects === 'function') {
      reloadCompareSelects();
    }
  }

  // 2. Monitor panel controls on running state changes
  if (prop === 'pipelineRunning') {
    if (rawState.currentPanel === 'monitor') {
      const cancelBtn = document.getElementById('cancel-btn');
      const returnSetupBtn = document.getElementById('return-setup-btn');
      if (value) {
        if (cancelBtn) cancelBtn.style.display = 'inline-flex';
        if (returnSetupBtn) returnSetupBtn.style.display = 'none';
      } else {
        if (cancelBtn) cancelBtn.style.display = 'none';
        if (returnSetupBtn) returnSetupBtn.style.display = 'inline-flex';
      }
    }
  }

  // 3. Launch state triggers
  const launchKeys = ['licenseValid', 'backendReady', 'manualLicenseView', 'backendStartupFailed', 'bootCompleted', 'downloading'];
  if (launchKeys.includes(prop)) {
    if (typeof evaluateLaunchState === 'function') {
      evaluateLaunchState();
    }
  }
}

// Proxied state manager
const state = new Proxy(rawState, {
  set(target, prop, value) {
    const oldValue = target[prop];
    if (oldValue === value) return true;
    target[prop] = value;
    handleStateChange(prop, value, oldValue);
    return true;
  },
  get(target, prop) {
    return target[prop];
  }
});


// ── ZONE CONFIG ───────────────────────────────────────────────
const ZONE_COLORS = {
  'Pseudopalisading Necrosis': '#E63946',
  'Microvascular Proliferation': '#F4A261',
  'Cellular Tumor': '#2A9D8F',
  'Leading Edge': '#457B9D',
  'Infiltrating Tumor': '#9B5DE5',
};

// ── Global Logger and Updates ─────────────────────────────────
// Declared with const since it is mutated in-place (lastBackendLogs.length = 0) in app-startup.js
const lastBackendLogs = [];
// Declared with let because it is reassigned in app.js upon update notification
let _updateUrl = '';

// Check if running in development mode (app.asar path check)
const isDev = !window.location.pathname.includes('app.asar');

// HTML Sanitizer to prevent XSS in toasts
function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ── Centralized Premium Notification System ────────────────────
const _toastCooldowns = new Map();
const _toastQueue = [];

function showToast(message, type = 'success') {
  // Rate limiting / Deduplication (5s cooldown per identical message)
  const cooldownKey = `${type}:${message}`;
  if (_toastCooldowns.has(cooldownKey)) return;
  _toastCooldowns.set(cooldownKey, true);
  setTimeout(() => _toastCooldowns.delete(cooldownKey), 5000);

  // Queue if document.body is not yet loaded (early boot)
  if (!document.body) {
    console.warn(`[Notification Early Boot - ${type}]: ${message}`);
    _toastQueue.push({ message, type });
    return;
  }
  
  // Ensure the toast container exists
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  // Accessibility
  if (type === 'error') {
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
  } else {
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
  }
  
  let icon = '✅';
  if (type === 'error') {
    icon = '❌';
  } else if (type === 'warning') {
    icon = '⚠️';
  } else if (type === 'info') {
    icon = 'ℹ️';
  }
  
  toast.innerHTML = `<span>${icon}</span><span style="letter-spacing: 0.3px;">${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  
  // Animation frames for smooth slide-in
  requestAnimationFrame(() => {
    toast.classList.add('show');
  });
  
  // Auto remove with transitionend event
  setTimeout(() => {
    toast.classList.remove('show');
    toast.style.transform = 'translateY(-20px)';
    
    toast.addEventListener('transitionend', function handler(e) {
      if (e.propertyName === 'opacity') {
        toast.remove();
        toast.removeEventListener('transitionend', handler);
      }
    });
  }, 4000);
}

// Flush any messages queued before DOMContentLoaded
function flushToastQueue() {
  while (_toastQueue.length > 0) {
    const { message, type } = _toastQueue.shift();
    showToast(message, type);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', flushToastQueue);
} else {
  flushToastQueue();
}

// Global helper wrappers
function showErrorToast(msg) {
  showToast(msg, 'error');
}

function showWarningToast(msg) {
  showToast(msg, 'warning');
}

function showInfoToast(msg) {
  showToast(msg, 'info');
}

// Compatibility wrapper for old references
function showExportSuccessToast(msg) {
  showToast(msg, 'success');
}

// ── Global Uncaught Exception Listeners ─────────────────
window.addEventListener('error', (event) => {
  console.error('[Unhandled Global Error]', event.error);
  // Avoid double warnings for standard three.js context losses
  if (event.message && event.message.includes('WebGL')) {
    showToast(`${window.i18n.t('state.webgl_warning')}: ${event.message}`, 'warning');
  } else {
    showToast(`${window.i18n.t('state.system_error')}: ${event.message || window.i18n.t('state.unknown_runtime_error')}`, 'error');
  }
});

window.addEventListener('unhandledrejection', (event) => {
  event.preventDefault(); // Prevent double logging/default handler trigger in Electron
  console.error('[Unhandled Promise Rejection]', event.reason);
  
  const msg = event.reason && (event.reason.message || event.reason.toString());
  
  // If it's a request timeout or connection issue
  if (msg && (msg.includes('timeout') || msg.includes('Failed to fetch') || msg.includes('NetworkError'))) {
    showToast(window.i18n.t('state.connection_timeout'), 'error');
  } else {
    // Show generic error message in production, details in development mode
    showToast(
      isDev 
        ? `${window.i18n.t('state.process_error')}: ${msg || window.i18n.t('state.unexpected_error')}` 
        : window.i18n.t('state.unexpected_error_retry'),
      'error'
    );
  }
});
