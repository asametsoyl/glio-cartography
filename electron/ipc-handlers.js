// =============================================================
// GLIO-CARTOGRAPHY — IPC Handler Registration
// =============================================================
// Fixes:
//  - save-license validates GCARTO- format before storing.
//  - backend-request timeout raised to 120s for GNN analyses.
//  - All mainWindow accesses use safeSend.
// =============================================================
'use strict';

const { ipcMain, dialog, shell, app, Notification } = require('electron');
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const { validateLicense } = require('./license');
const { getMachineId } = require('./machine-id');
const { getLogPath, isPathAllowed, safeSend: safeSendUtil } = require('./utils');
const {
  startBackend, waitForBackend, killBackend, killProcessOnPort,
  findExtractedPython,
  setBackendState, getBackendState,
  BACKEND_PORT, BACKEND_HOST
} = require('./backend-manager');
const { downloadWithRedirects, extractZip, ensureVcRuntime } = require('./runtime-manager');
const { checkForUpdates } = require('./updater');

let _store = null;
let _mainWindow = null;

function setStore(store) { _store = store; }
function setMainWindow(win) { _mainWindow = win; }

// Local shorthand that captures _mainWindow at call time
function safeSend(channel, ...args) {
  safeSendUtil(_mainWindow, channel, ...args);
}

// ── Register all IPC handlers ─────────────────────────────────
function registerIpcHandlers() {

  // ── Diagnostics ─────────────────────────────────────────────
  ipcMain.handle('open-log-file', () => {
    shell.openPath(getLogPath());
    return true;
  });

  ipcMain.handle('get-backend-state', () => getBackendState());

  // ── Runtime Download ─────────────────────────────────────────
  ipcMain.handle('download-runtime', async () => {
    console.log('[Runtime Downloader] Starting runtime download process...');
    setBackendState('starting', null);

    if (process.platform === 'win32') {
      try {
        const vcDllPath = 'C:\\Windows\\System32\\vcruntime140.dll';
        if (!fs.existsSync(vcDllPath)) {
          setBackendState('downloading_vc');
          const vcOk = await ensureVcRuntime(_mainWindow, app);
          if (!vcOk) {
            const msg = 'Gerekli C++ sistem bileşeni (VC++ Redistributable) yüklenemedi.';
            setBackendState('failed', msg);
            throw new Error(msg);
          }
        }
      } catch (e) {
        console.error('[Runtime Downloader] VC++ error:', e.message);
        setBackendState('failed', e.message);
        throw e;
      }
    }

    const envDir = path.join(app.getPath('userData'), 'python_env');
    const zipPath = path.join(app.getPath('userData'), 'python_env.zip');

    let url = '';
    if (process.platform === 'win32') {
      url = 'https://github.com/asametsoyl/glio-cartography/releases/download/v1.1.0/python_env_windows.zip';
    } else if (process.platform === 'darwin') {
      url = 'https://github.com/asametsoyl/glio-cartography/releases/download/v1.1.0/python_env_macos.zip';
    } else {
      const err = new Error(
        `Otomatik yükleme sadece Windows ve macOS için desteklenmektedir. Platformunuz: ${process.platform}`
      );
      setBackendState('failed', err.message);
      throw err;
    }

    try {
      if (fs.existsSync(zipPath)) { try { fs.unlinkSync(zipPath); } catch { } }
      if (fs.existsSync(envDir)) { try { fs.rmSync(envDir, { recursive: true, force: true }); } catch { } }

      setBackendState('downloading');
      safeSend('download-progress', { status: 'downloading', percent: 0 });

      let lastPercent = -1;
      await downloadWithRedirects(url, zipPath, (received, total) => {
        const percent = Math.round((received / total) * 100);
        if (percent !== lastPercent) {
          lastPercent = percent;
          safeSend('download-progress', {
            status: 'downloading', percent,
            received: (received / 1024 / 1024).toFixed(1),
            total: (total / 1024 / 1024).toFixed(1)
          });
        }
      });

      setBackendState('extracting');
      safeSend('download-progress', { status: 'extracting', percent: 100 });

      if (!fs.existsSync(envDir)) fs.mkdirSync(envDir, { recursive: true });
      await extractZip(zipPath, envDir);

      setBackendState('configuring');
      safeSend('download-progress', { status: 'configuring', percent: 100 });

      const pyBin = findExtractedPython(envDir);
      if (!pyBin) {
        const err = new Error('Kurulan paket içerisinde gerekli analiz bileşenleri bulunamadı.');
        setBackendState('failed', err.message);
        throw err;
      }

      if (_store) _store.set('customPythonPath', pyBin);

      try { if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath); } catch { }

      setBackendState('completed');
      safeSend('download-progress', { status: 'completed', percent: 100 });

      return { success: true, pythonPath: pyBin };
    } catch (err) {
      console.error('[Runtime Downloader] Error:', err.message);
      setBackendState('failed', err.message);
      safeSend('download-progress', { status: 'failed', error: err.message });
      throw err;
    }
  });

  // ── License ──────────────────────────────────────────────────
  ipcMain.handle('get-machine-id', () => getMachineId());
  ipcMain.handle('validate-license', (_, key) => validateLicense(key));

  ipcMain.handle('save-license', (_, key) => {
    const result = validateLicense(key); // RSA ve imza kontrolü burada çalışır
    return result.valid;
  });

  ipcMain.handle('get-stored-license', () => _store ? _store.get('license') : null);

  // ── Python Path ──────────────────────────────────────────────
  ipcMain.handle('save-custom-python-path', (_, pythonPath) => {
    if (_store) _store.set('customPythonPath', pythonPath);
    return true;
  });

  ipcMain.handle('get-custom-python-path', () =>
    _store ? _store.get('customPythonPath', null) : null
  );

  ipcMain.handle('select-python-path', async () => {
    const filters = process.platform === 'win32'
      ? [{ name: 'Python Executable', extensions: ['exe'] }]
      : [];
    const result = await dialog.showOpenDialog(_mainWindow, {
      properties: ['openFile'],
      title: 'Analiz Bileşeni Çalıştırıcısını Seçin',
      filters
    });
    return result.canceled ? null : result.filePaths[0];
  });

  // ── Backend Control ──────────────────────────────────────────
  ipcMain.handle('restart-backend', async () => {
    console.log('[IPC] restart-backend triggered');
    setBackendState('starting', null);
    try {
      killBackend();
      killProcessOnPort(BACKEND_PORT);
      await startBackend(_mainWindow, _store, app);
      const ready = await waitForBackend(30);
      console.log(`[IPC] restart-backend result: ${ready}`);
      if (ready) setBackendState('ready');
      else setBackendState('failed', 'Analiz bileşenleri başlatıldı ancak bağlantı kurulamadı. Lütfen sistem tanılama kayıtlarını kontrol edin.');
      safeSend('backend-ready', ready);
      return ready;
    } catch (err) {
      console.error('[IPC] restart-backend failed:', err);
      setBackendState('failed', err.message);
      safeSend('backend-ready', false);
      return false;
    }
  });

  // ── File / Folder Dialogs ────────────────────────────────────
  ipcMain.handle('select-folder', async () => {
    const result = await dialog.showOpenDialog(_mainWindow, {
      properties: ['openDirectory'],
      title: 'Spatial Veri Klasörünü Seçin'
    });
    return result.canceled ? null : result.filePaths[0];
  });

  ipcMain.handle('select-file', async (_, filters) => {
    const result = await dialog.showOpenDialog(_mainWindow, {
      properties: ['openFile'],
      title: 'scRNA-seq Veri Dosyasını Seçin',
      filters: filters || [{ name: 'scRNA Data', extensions: ['h5ad', 'h5', 'loom', 'csv', 'tsv'] }]
    });
    return result.canceled ? null : result.filePaths[0];
  });

  ipcMain.handle('select-output-folder', async () => {
    const result = await dialog.showOpenDialog(_mainWindow, {
      properties: ['openDirectory', 'createDirectory'],
      title: 'Çıktı Klasörünü Seçin'
    });
    return result.canceled ? null : result.filePaths[0];
  });

  ipcMain.handle('open-output-folder', (_, folderPath) => shell.openPath(folderPath));

  // ── Backend HTTP Proxy ───────────────────────────────────────
  ipcMain.handle('backend-request', async (_, endpoint, method, body) => {
    return new Promise((resolve, reject) => {
      const isGet = !method || method === 'GET';
      const postData = (!isGet && body) ? JSON.stringify(body) : '';
      const headers = { 'Content-Type': 'application/json' };
      if (!isGet) headers['Content-Length'] = Buffer.byteLength(postData);

      const options = {
        hostname: BACKEND_HOST,
        port: BACKEND_PORT,
        path: endpoint,
        method: method || 'GET',
        headers,
        // Raised from 30s to 120s — GNN graph analyses can exceed 30s on large datasets
        timeout: 120000
      };

      let completed = false;
      const req = http.request(options, (res) => {
        let data = '';
        res.setTimeout(120000, () => {
          data = '';
          res.destroy();
        });
        res.on('data', chunk => {
          data += chunk;
        });
        res.on('end', () => {
          if (completed) return;
          completed = true;
          try { resolve(data ? JSON.parse(data) : { raw: '' }); }
          catch { resolve({ raw: data }); }
        });
      });

      req.on('timeout', () => {
        if (completed) return;
        completed = true;
        console.warn(`[backend-request] Request to ${endpoint} timed out after 120s`);
        req.destroy();
        reject(new Error('İstek zaman aşımına uğradı'));
      });

      req.on('error', (err) => {
        if (completed) return;
        completed = true;
        reject(err);
      });

      if (!isGet && postData) req.write(postData);
      req.end();
    });
  });

  // ── File Utilities ───────────────────────────────────────────
  ipcMain.handle('read-json-file', (_, filePath) => {
    let resolvedPath;
    try {
      resolvedPath = fs.realpathSync(filePath);
    } catch {
      try { resolvedPath = path.resolve(filePath); }
      catch { return null; }
    }

    if (!isPathAllowed(resolvedPath)) {
      console.warn('[read-json-file] Access denied — path outside allowed dirs:', resolvedPath);
      return null;
    }

    try { return JSON.parse(fs.readFileSync(resolvedPath, 'utf8')); }
    catch (e) { console.error('[read-json-file] Error:', e.message); return null; }
  });

  ipcMain.handle('file-exists', (_, filePath) => {
    let resolvedPath;
    try {
      resolvedPath = fs.realpathSync(filePath);
    } catch {
      try { resolvedPath = path.resolve(filePath); }
      catch { return false; }
    }

    if (!isPathAllowed(resolvedPath)) {
      console.warn('[file-exists] Access denied — path outside allowed dirs:', resolvedPath);
      return false;
    }
    return fs.existsSync(resolvedPath);
  });

  ipcMain.handle('get-app-version', () => app.getVersion());

  // ── User Preferences ─────────────────────────────────────────
  ipcMain.handle('get-last-paths', () => _store ? _store.get('lastPaths', null) : null);
  ipcMain.handle('save-last-paths', (_, paths) => {
    if (_store) _store.set('lastPaths', paths);
    return true;
  });

  // ── Dataset Profiles ─────────────────────────────────────────
  ipcMain.handle('get-profiles', () => _store ? _store.get('datasetProfiles', []) : []);

  ipcMain.handle('save-profile', (_, profile) => {
    if (!_store) return false;
    // Whitelist-only approach: only known keys are written to the store.
    // Prevents prototype pollution (__proto__, constructor) and extra field injection.
    const ALLOWED_KEYS = ['name', 'spatialPath', 'scrnaPath', 'outputPath'];
    const MAX_LENS = { name: 100 }; // shorter limit for display name
    const safe = Object.fromEntries(
      ALLOWED_KEYS.map(k => [k, String(profile[k] || '').slice(0, MAX_LENS[k] || 1000)])
    );
    const profiles = _store.get('datasetProfiles', []);
    const id = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36);
    profiles.push({ id, ...safe, createdAt: new Date().toISOString() });
    _store.set('datasetProfiles', profiles);
    return id;
  });

  ipcMain.handle('delete-profile', (_, id) => {
    if (!_store) return false;
    const profiles = _store.get('datasetProfiles', []).filter(p => p.id !== id);
    _store.set('datasetProfiles', profiles);
    return true;
  });

  // ── Misc ─────────────────────────────────────────────────────
  ipcMain.handle('check-for-updates', () => checkForUpdates(_mainWindow, false));
  ipcMain.handle('open-external', (_, url) => {
    const allowedHosts = ['github.com', 'glio-cartography.com'];
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol)) {
        console.warn('[open-external] Blocked non-http(s) URL:', url);
        return false;
      }
      const isAllowedHost = allowedHosts.some(h => 
        parsed.hostname === h || parsed.hostname.endsWith('.' + h)
      );
      if (!isAllowedHost) {
        console.warn('[open-external] Blocked unknown host:', parsed.hostname);
        return false;
      }
      return shell.openExternal(url);
    } catch {
      return false;
    }
  });

  ipcMain.handle('focus-window', () => {
    if (_mainWindow) {
      if (_mainWindow.isMinimized()) _mainWindow.restore();
      _mainWindow.focus();
      return true;
    }
    return false;
  });

  ipcMain.on('show-notification', (event, { title, body }) => {
    console.log(`[IPC Handlers] Received show-notification: "${title}" - "${body}"`);
    try {
      if (!Notification.isSupported()) {
        console.warn('[IPC Handlers] Native notifications are not supported!');
        return;
      }
      const notif = new Notification({
        title: title,
        body: body,
        icon: path.join(__dirname, '..', 'assets', 'icon.png')
      });
      notif.on('click', () => {
        console.log('[IPC Handlers] Notification clicked!');
        if (_mainWindow) {
          if (_mainWindow.isMinimized()) _mainWindow.restore();
          _mainWindow.focus();
        }
      });
      notif.show();
      console.log('[IPC Handlers] Notification shown.');
    } catch (err) {
      console.error('[IPC Handlers] Failed to show native notification:', err);
    }
  });
}

module.exports = { registerIpcHandlers, setStore, setMainWindow };
