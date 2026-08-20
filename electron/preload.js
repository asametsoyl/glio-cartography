// =============================================================
// GLIO-CARTOGRAPHY — Preload Script (IPC Bridge)
// =============================================================
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('glioAPI', {
  // License — Machine ID ASLA renderer'a açılmıyor
  validateCachedLicense: () => ipcRenderer.invoke('validate-cached-license'),
  activateLicenseOnline: (key) => ipcRenderer.invoke('activate-license-online', key),
  saveApiToken: (token) => ipcRenderer.invoke('save-api-token', token),

  // File system
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  selectFile: (filters) => ipcRenderer.invoke('select-file', filters),
  selectOutputFolder: () => ipcRenderer.invoke('select-output-folder'),
  openOutputFolder: (path) => ipcRenderer.invoke('open-output-folder', path),
  readJsonFile: (path) => ipcRenderer.invoke('read-json-file', path),
  fileExists: (path) => ipcRenderer.invoke('file-exists', path),

  // Backend
  backendRequest: (endpoint, method, body) => ipcRenderer.invoke('backend-request', endpoint, method, body),
  getBackendUrl: () => 'http://127.0.0.1:8765',
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  selectPythonPath: () => ipcRenderer.invoke('select-python-path'),
  saveCustomPythonPath: (path) => ipcRenderer.invoke('save-custom-python-path', path),
  getCustomPythonPath: () => ipcRenderer.invoke('get-custom-python-path'),
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  downloadRuntime: () => ipcRenderer.invoke('download-runtime'),
  openLogFile: () => ipcRenderer.invoke('open-log-file'),
  getBackendState: () => ipcRenderer.invoke('get-backend-state'),

  // Son kullanılan yollar (cross-session persistence)
  getLastPaths: () => ipcRenderer.invoke('get-last-paths'),
  saveLastPaths: (paths) => ipcRenderer.invoke('save-last-paths', paths),

  // Veri Seti Profilleri
  getProfiles: () => ipcRenderer.invoke('get-profiles'),
  saveProfile: (profile) => ipcRenderer.invoke('save-profile', profile),
  deleteProfile: (id) => ipcRenderer.invoke('delete-profile', id),

  onBackendReady: (cb) => {
    // Remove any previous once() listener before adding a new one.
    // This is necessary when the user manually restarts the backend:
    // the renderer re-calls onBackendReady(), and without removeAllListeners
    // the old once() would still be queued and consume the event first.
    ipcRenderer.removeAllListeners('backend-ready');
    ipcRenderer.once('backend-ready', (_, val) => cb(val));
  },
  onBackendLog: (cb) => {
    // Recurring: replace previous handler cleanly using a named reference.
    ipcRenderer.removeAllListeners('backend-log');
    ipcRenderer.on('backend-log', (_, msg) => cb(msg));
  },
  onDownloadProgress: (cb) => {
    ipcRenderer.removeAllListeners('download-progress');
    ipcRenderer.on('download-progress', (_, data) => cb(data));
  },
  onUpdateAvailable: (cb) => {
    // One-shot: show update banner once per session.
    ipcRenderer.once('update-available', (_, info) => cb(info));
  },
  startUpdateDownload: (version) => ipcRenderer.invoke('start-update-download', version),
  onUpdateDownloadProgress: (cb) => {
    ipcRenderer.removeAllListeners('update-download-progress');
    ipcRenderer.on('update-download-progress', (_, data) => cb(data));
  },
  onRuntimeMissing: (cb) => {
    // One-shot: only shown once on startup.
    ipcRenderer.once('runtime-missing', (_) => cb());
  },
  focusWindow: () => ipcRenderer.invoke('focus-window'),
  showNotification: (title, body) => ipcRenderer.send('show-notification', { title, body }),

  // [FAZ B] Sistem Tanılama
  getEnvDiagnostics: () => ipcRenderer.invoke('get-env-diagnostics'),
  repairDependencies: (packages) => ipcRenderer.invoke('repair-dependencies', packages),
  onEnvDiagnosticsReady: (cb) => {
    ipcRenderer.removeAllListeners('env-diagnostics-ready');
    ipcRenderer.on('env-diagnostics-ready', (_, report) => cb(report));
  },
  onRepairDependencyProgress: (cb) => {
    ipcRenderer.removeAllListeners('repair-dependency-progress');
    ipcRenderer.on('repair-dependency-progress', (_, data) => cb(data));
  },

  // [FAZ C] i18n Dil Yönetimi
  getLanguage: () => ipcRenderer.invoke('get-language'),
  setLanguage: (lang) => ipcRenderer.invoke('set-language', lang),
  getLocale: (lang) => ipcRenderer.invoke('get-locale-data', lang),
  isLanguageLocked: () => ipcRenderer.invoke('is-language-locked'),
  setLanguageLocked: (locked) => ipcRenderer.invoke('set-language-locked', locked),
  printReportToPDF: (htmlContent) => ipcRenderer.invoke('print-report-to-pdf', htmlContent),
  toLocalUrl: (filePath) => {
    if (!filePath) return '';
    let normalized = filePath.replace(/\\/g, '/');
    let url;
    if (process.platform === 'win32' || (normalized.length >= 2 && normalized.charCodeAt(1) === 58)) {
      url = `local:///${normalized}`;
    } else {
      url = `local://${normalized.startsWith('/') ? '' : '/'}${normalized}`;
    }
    return encodeURI(url);
  },

  // Cleanup helper: renderer pages should call this on unmount
  // to avoid handler accumulation between hot-reloads in dev mode.
  removeAllListeners: (channel) => {
    ipcRenderer.removeAllListeners(channel);
  },
});
