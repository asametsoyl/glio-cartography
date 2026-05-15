// =============================================================
// GLIO-CARTOGRAPHY — Preload Script (IPC Bridge)
// =============================================================
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('glioAPI', {
  // License
  getMachineId: () => ipcRenderer.invoke('get-machine-id'),
  validateLicense: (key) => ipcRenderer.invoke('validate-license', key),
  saveLicense: (key, expiry) => ipcRenderer.invoke('save-license', key, expiry),
  getStoredLicense: () => ipcRenderer.invoke('get-stored-license'),

  // File system
  selectFolder: () => ipcRenderer.invoke('select-folder'),
  selectFile: (filters) => ipcRenderer.invoke('select-file', filters),
  selectOutputFolder: () => ipcRenderer.invoke('select-output-folder'),
  openOutputFolder: (path) => ipcRenderer.invoke('open-output-folder', path),
  readJsonFile: (path) => ipcRenderer.invoke('read-json-file', path),
  fileExists: (path) => ipcRenderer.invoke('file-exists', path),

  // Backend
  backendRequest: (endpoint, method, body) => ipcRenderer.invoke('backend-request', endpoint, method, body),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // Son kullanılan yollar (cross-session persistence)
  getLastPaths: () => ipcRenderer.invoke('get-last-paths'),
  saveLastPaths: (paths) => ipcRenderer.invoke('save-last-paths', paths),

  // Events
  // NOT: ipcRenderer.on() her çağrıda yeni listener ekler.
  // Pencere yeniden yüklenirse listener'lar birikir (memory leak).
  // removeAllListeners() ile her kayıt öncesinde eski listener'lar temizlenir.
  // Bu pattern ipcRenderer.once()'a tercih edilir çünkü birden fazla
  // event tetiklendiğinde de doğru çalışır.
  onBackendReady: (cb) => {
    ipcRenderer.removeAllListeners('backend-ready');
    ipcRenderer.on('backend-ready', (_, val) => cb(val));
  },
  onBackendLog: (cb) => {
    ipcRenderer.removeAllListeners('backend-log');
    ipcRenderer.on('backend-log', (_, msg) => cb(msg));
  },
  onPipelineProgress: (cb) => {
    ipcRenderer.removeAllListeners('pipeline-progress');
    ipcRenderer.on('pipeline-progress', (_, data) => cb(data));
  },
  onUpdateAvailable: (cb) => {
    ipcRenderer.removeAllListeners('update-available');
    ipcRenderer.on('update-available', (_, info) => cb(info));
  },
});
