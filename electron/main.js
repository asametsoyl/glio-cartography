// =============================================================
// GLIO-CARTOGRAPHY — Electron Main Process (Entry Point)
// =============================================================
// This file is intentionally slim. All business logic has been
// extracted into focused modules:
//
//   utils.js           – Logging, execSyncWithRetry, safeSend
//   store.js           – RobustJSONStore (in-memory cache)
//   machine-id.js      – Hardware fingerprinting
//   license.js         – RSA-SHA256 license validation
//   backend-manager.js – Python process lifecycle + findPython
//   runtime-manager.js – Download, extraction, VC++ setup
//   protocol-handler.js– local:// with path traversal protection
//   ipc-handlers.js    – All ipcMain.handle() registrations
//   updater.js         – GitHub Releases update checker
// =============================================================
'use strict';

const { app, BrowserWindow, protocol } = require('electron');
const path = require('path');
const os = require('os');
const fs = require('fs');

// ── Bootstrap logging BEFORE app.whenReady() ─────────────────
// logPath starts in tmpdir; updated to documents dir once app is ready.
const { logToFile, setLogPath, getLogPath } = require('./utils');

const _origLog   = console.log;
const _origError = console.error;
const _origWarn  = console.warn;

console.log = (...args) => {
  _origLog.apply(console, args);
  logToFile(`[INFO] ${args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')}`);
};
console.error = (...args) => {
  _origError.apply(console, args);
  logToFile(`[ERROR] ${args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')}`);
};
console.warn = (...args) => {
  _origWarn.apply(console, args);
  logToFile(`[WARN] ${args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')}`);
};

process.on('uncaughtException', (err) => {
  console.error('[UNCAUGHT EXCEPTION]', err ? (err.stack || err.message || err) : 'Bilinmeyen hata');
});
process.on('unhandledRejection', (reason) => {
  console.error('[UNHANDLED REJECTION]', reason ? (reason.stack || reason.message || reason) : 'Bilinmeyen rejection');
});

console.log(
  `GLIO-CARTOGRAPHY STARTUP: Platform: ${process.platform}, ` +
  `OS: ${os.type()} ${os.release()}, Arch: ${process.arch}, Node: ${process.version}`
);

// Register local:// scheme as privileged BEFORE app ready (Electron requirement)
protocol.registerSchemesAsPrivileged([{
  scheme: 'local',
  privileges: { secure: true, standard: true, supportFetchAPI: true, corsEnabled: true, bypassCSP: false }
}]);

// ── Module imports (after scheme registration) ────────────────
const { initStore }                                  = require('./store');
const { setStore: setLicenseStore }                  = require('./license');
const { registerLocalProtocol }                      = require('./protocol-handler');
const { registerIpcHandlers, setStore: setIpcStore,
        setMainWindow }                              = require('./ipc-handlers');
const { startBackend, waitForBackend, killBackend,
        killProcessOnPort, setBackendState,
        findPython, BACKEND_PORT }                   = require('./backend-manager');
const { ensureVcRuntime }                            = require('./runtime-manager');
const { checkForUpdates }                            = require('./updater');

const isDev = process.argv.includes('--dev');

let mainWindow = null;
let store      = null;

// =============================================================
// WINDOW CREATION
// =============================================================
function createWindow() {
  const winOptions = {
    width: 1440,
    height: 900,
    minWidth: 1200,
    minHeight: 750,
    backgroundColor: '#0a0f1e',
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true
    },
    show: false
  };

  // macOS-only window chrome options
  if (process.platform === 'darwin') {
    winOptions.titleBarStyle = 'hiddenInset';
    winOptions.vibrancy = 'dark';
  }

  mainWindow = new BrowserWindow(winOptions);
  setMainWindow(mainWindow); // propagate to ipc-handlers

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  if (isDev) mainWindow.webContents.openDevTools({ mode: 'detach' });

  mainWindow.webContents.on('console-message', (_event, _level, message, line) => {
    console.log(`[Renderer L${line}]: ${message}`);
  });

  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
    console.error(`[Main Error] Main frame failed to load: ${validatedURL} (${errorDescription}, Code: ${errorCode})`);
  });

  mainWindow.webContents.on('did-fail-provisional-load', (event, errorCode, errorDescription, validatedURL) => {
    console.error(`[Main Error] Subresource failed to load: ${validatedURL} (${errorDescription}, Code: ${errorCode})`);
  });
}

// APP LIFECYCLE
// =============================================================
app.whenReady().then(async () => {
  if (process.platform === 'win32' || process.platform === 'darwin') {
    app.setAppUserModelId('com.gliocartography.desktop');
  }

  // ── 1. Upgrade log path from tmpdir → documents ────────────
  try {
    const docsPath = app.getPath('documents');
    const glioDocsDir = path.join(docsPath, 'Glio-Cartography');
    if (!fs.existsSync(glioDocsDir)) fs.mkdirSync(glioDocsDir, { recursive: true });
    setLogPath(path.join(glioDocsDir, 'diagnostic.log'));
    console.log(`[Main] Log file: ${getLogPath()}`);
  } catch (e) {
    try {
      setLogPath(path.join(app.getPath('userData'), 'diagnostic.log'));
    } catch {
      // Keep tmpdir fallback set during module init
    }
  }

  // ── 2. Register local:// protocol ─────────────────────────
  registerLocalProtocol(protocol, app);

  // ── 3. Initialize persistent store ────────────────────────
  try {
    store = await initStore();
  } catch (err) {
    console.error('CRITICAL: Failed to initialize store:', err);
    // Fallback mock — settings won't persist but app won't crash
    store = { get: (key, fallback) => fallback, set: () => { }, delete: () => { } };
  }
  setLicenseStore(store);
  setIpcStore(store);

  // ── 4. Register all IPC handlers ──────────────────────────
  registerIpcHandlers();

  // ── 5. Create main window ─────────────────────────────────
  createWindow();

  // ── 6. Start backend after window is rendered ─────────────
  mainWindow.once('ready-to-show', async () => {
    console.log('[Main] Window ready. Starting Python backend...');
    setBackendState('starting', null);

    try {
      // Skip startup if backend is already running (e.g. external dev server)
      const alreadyUp = await waitForBackend(3);
      if (alreadyUp) {
        console.log('[Main] Backend already running.');
        setBackendState('ready');
        if (!mainWindow.isDestroyed()) mainWindow.webContents.send('backend-ready', true);
        return;
      }

      // Clean up any zombie process occupying the port
      killProcessOnPort(BACKEND_PORT);

      // Windows: ensure VC++ redistributable is present
      if (process.platform === 'win32') {
        const vcDllPath = 'C:\\Windows\\System32\\vcruntime140.dll';
        if (!fs.existsSync(vcDllPath)) {
          console.log('[Main] VC++ Runtime missing. Installing...');
          setBackendState('downloading_vc');
          const vcInstalled = await ensureVcRuntime(mainWindow, app);
          if (!vcInstalled) {
            console.error('[Main] VC++ installation failed.');
            setBackendState('failed', 'Gerekli C++ sistem bileşeni (VC++ Redistributable) yüklenemedi.');
            if (!mainWindow.isDestroyed()) mainWindow.webContents.send('backend-ready', false);
            return;
          }
        }
      }

      // Check for a suitable Python runtime
      const pythonInfo = findPython(store, app);
      if (!pythonInfo || !pythonInfo.bin) {
        console.warn('[Main] No suitable Python runtime found.');
        setBackendState('runtime-missing');
        if (!mainWindow.isDestroyed()) mainWindow.webContents.send('runtime-missing');
        return;
      }

      setBackendState('starting');
      await startBackend(mainWindow, store, app);
      const ready = await waitForBackend(30);
      console.log(`[Main] Backend ready: ${ready}`);

      if (ready) setBackendState('ready');
      else setBackendState('failed', 'Glio-Cartography analiz bileşenleri başlatıldı ancak bağlantı kurulamadı. Lütfen sistem tanılama kayıtlarını kontrol edin.');

      if (!mainWindow.isDestroyed()) mainWindow.webContents.send('backend-ready', ready);

      // Silent update check 30s after backend is ready
      // mainWindow reference is captured here; checkForUpdates guards against null/destroyed.
      setTimeout(() => checkForUpdates(mainWindow, true), 30_000);

    } catch (e) {
      console.error('[Main] Backend start failed:', e);
      setBackendState('failed', e.message);
      if (!mainWindow.isDestroyed()) mainWindow.webContents.send('backend-ready', false);
    }
  });
});

// ── App event handlers ────────────────────────────────────────
app.on('window-all-closed', () => {
  // Do NOT call killBackend here — before-quit is the authoritative hook.
  // Calling it here would attempt a double-kill after before-quit already ran.
  if (process.platform !== 'darwin') app.quit();
});

// Single kill point for the backend process
app.on('before-quit', () => {
  killBackend();
});

// Note: will-quit does NOT call killBackend — before-quit is sufficient.
// Duplicate calls caused harmless-but-confusing log noise.

app.on('activate', async () => {
  // macOS: user clicked the dock icon after closing all windows
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
    // The new window's ready-to-show will handle backend startup.
    return;
  }

  // Window already exists — check if the backend is still alive.
  // It may have died while the app was backgrounded; restart it silently.
  try {
    const alive = await waitForBackend(2);
    if (!alive) {
      console.log('[activate] Backend appears dead — attempting restart...');
      setBackendState('starting', null);
      killProcessOnPort(BACKEND_PORT);
      await startBackend(mainWindow, store, app);
      const ready = await waitForBackend(30);
      setBackendState(ready ? 'ready' : 'failed', ready ? null : 'Backend yeniden başlatılamadı.');
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('backend-ready', ready);
      }
    }
  } catch (e) {
    console.error('[activate] Backend restart failed:', e.message);
  }
});
