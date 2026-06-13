/* ══════════════════════════════════════════════════════════
   GLIO-CARTOGRAPHY DESKTOP — State and Configuration (renderer)
   ══════════════════════════════════════════════════════════ */

const api = window.glioAPI;

// ── State ────────────────────────────────────────────────────
const state = {
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
    showToast(`WebGL Uyarısı: ${event.message}`, 'warning');
  } else {
    showToast(`Sistem Hatası: ${event.message || 'Bilinmeyen bir çalışma zamanı hatası oluştu.'}`, 'error');
  }
});

window.addEventListener('unhandledrejection', (event) => {
  event.preventDefault(); // Prevent double logging/default handler trigger in Electron
  console.error('[Unhandled Promise Rejection]', event.reason);
  
  const msg = event.reason && (event.reason.message || event.reason.toString());
  
  // If it's a request timeout or connection issue
  if (msg && (msg.includes('timeout') || msg.includes('Failed to fetch') || msg.includes('NetworkError'))) {
    showToast(`Bağlantı Hatası: Sunucu zaman aşımına uğradı veya ağ bağlantısı koptu.`, 'error');
  } else {
    // Show generic error message in production, details in development mode
    showToast(
      isDev 
        ? `İşlem Hatası: ${msg || 'Beklenmeyen bir hata oluştu.'}` 
        : 'Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.',
      'error'
    );
  }
});
