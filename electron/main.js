// =============================================================
// GLIO-CARTOGRAPHY — Electron Main Process
// =============================================================
const { app, BrowserWindow, ipcMain, dialog, shell, protocol } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const http = require('http');
const fs = require('fs');
const crypto = require('crypto');
const os = require('os');

// ── Store (electron-store) ──────────────────────────────────
let Store;
let store;
async function initStore() {
  const mod = await import('electron-store');
  Store = mod.default;
  store = new Store({ name: 'glio-cartography-config' });
}

// ── Dev Mode ───────────────────────────────────────────────
const isDev = process.argv.includes('--dev');

// ── Backend process ─────────────────────────────────────────
let backendProcess = null;
let mainWindow = null;
const BACKEND_PORT = 8765;
const BACKEND_HOST = '127.0.0.1';

// =============================================================
// LICENSE SYSTEM
// =============================================================
// License secret is loaded from environment or a separate config
// file that is NOT committed to source control.
const LICENSE_SECRET = process.env.GCARTO_LICENSE_SECRET || (() => {
  try {
    const cfgPath = require('path').join(require('electron').app.getPath('userData'), '.lcfg');
    return require('fs').readFileSync(cfgPath, 'utf8').trim();
  } catch { return ''; }
})();

let _cachedMachineId = null;
function getMachineId() {
  if (_cachedMachineId) return _cachedMachineId;
  try {
    if (process.platform === 'darwin') {
      _cachedMachineId = execSync("system_profiler SPHardwareDataType | awk '/Hardware UUID/ {print $3}'").toString().trim();
    } else if (process.platform === 'win32') {
      _cachedMachineId = execSync('wmic csproduct get uuid').toString().trim().split('\n').pop().trim();
    } else {
      _cachedMachineId = os.hostname();
    }
  } catch (e) {
    _cachedMachineId = os.hostname() + '-' + os.cpus()[0].model.replace(/\s/g, '').slice(0, 8);
  }
  return _cachedMachineId;
}

function validateLicense(licenseKey) {
  if (!licenseKey || !licenseKey.startsWith('GCARTO-')) return { valid: false, reason: 'Geçersiz format' };
  
  const machineId = getMachineId();

  // Check stored validation first
  const savedLicense = store ? store.get('license') : null;
  if (savedLicense && savedLicense.key === licenseKey && savedLicense.machineId === machineId) {
    const expiry = new Date(savedLicense.expiryDate);
    if (expiry > new Date()) {
      return { valid: true, expiryDate: savedLicense.expiryDate, machineId };
    } else {
      return { valid: false, reason: 'Lisans süresi dolmuş' };
    }
  }

  // License Format: GCARTO-{EXP_TIMESTAMP_HEX}-{SIGNATURE}
  try {
    const parts = licenseKey.split('-');
    if (parts.length >= 3 && parts[0] === 'GCARTO') {
      const expHex = parts[1];
      const sigProvided = parts.slice(2).join('-');
      
      const expTimestamp = parseInt(expHex, 16);
      if (!isNaN(expTimestamp)) {
        const expiryDateObj = new Date(expTimestamp * 1000);
        const expiryStr = expiryDateObj.toISOString().split('T')[0];
        
        const payload = `${machineId}:${expiryStr}:GLIO-CARTOGRAPHY-v1`;
        const sigExpected = crypto.createHmac('sha256', LICENSE_SECRET)
                                  .update(payload).digest('hex')
                                  .toUpperCase().slice(0, 16);
        
        const formattedExpectedSig = sigExpected.match(/.{1,4}/g).join('-');
        
        if (sigProvided === formattedExpectedSig) {
          if (expiryDateObj > new Date()) {
            if (store) store.set('license', { key: licenseKey, machineId, expiryDate: expiryStr });
            return { valid: true, expiryDate: expiryStr, machineId };
          } else {
            return { valid: false, reason: 'Lisans süresi dolmuş' };
          }
        }
      }
    }
  } catch (e) {}

  return { valid: false, reason: 'Lisans bu makine için geçerli değil veya hatalı format.' };
}

// =============================================================
// BACKEND MANAGEMENT
// =============================================================
function findPython() {
  const resources = process.resourcesPath || __dirname;
  
  // 1. PyInstaller Compiled Executable (Standalone)
  const pyinstallerMac = path.join(resources, 'python_env', 'server');
  const pyinstallerWin = path.join(resources, 'python_env', 'server.exe');
  if (fs.existsSync(pyinstallerMac)) return { bin: pyinstallerMac, compiled: true };
  if (fs.existsSync(pyinstallerWin)) return { bin: pyinstallerWin, compiled: true };

  // 2. Conda-pack bundled environment
  const condaBin = path.join(resources, 'python_env', 'bin', 'python3');
  const condaWinBin = path.join(resources, 'python_env', 'python.exe');
  if (fs.existsSync(condaBin)) return { bin: condaBin, compiled: false };
  if (fs.existsSync(condaWinBin)) return { bin: condaWinBin, compiled: false };

  // 3. Fallback to Local Environment Candidates
  const candidates = [
    '/opt/homebrew/Caskroom/miniforge/base/envs/gliocarto/bin/python3',
    '/opt/homebrew/Caskroom/miniforge/base/bin/python3',
    '/opt/homebrew/opt/python@3.12/bin/python3',
    '/opt/homebrew/opt/python@3.11/bin/python3',
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    '/usr/bin/python3',
    'python3',
    'python'
  ];
  for (const p of candidates) {
    try {
      execSync(`"${p}" -c "import scanpy, fastapi"`, { stdio: 'ignore', shell: true });
      return { bin: p, compiled: false };
    } catch {}
  }
  // Last resort: ask the shell
  try {
    const fallback = execSync('which python3', { shell: true }).toString().trim();
    if (fallback) return { bin: fallback, compiled: false };
  } catch {}
  return { bin: 'python3', compiled: false };
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const pythonInfo = findPython();
    const serverScript = path.join(__dirname, '..', 'python_backend', 'server.py');
    const miniforgeBin = '/opt/homebrew/Caskroom/miniforge/base/bin';
    const extraPath = `${miniforgeBin}:/opt/homebrew/bin:/usr/local/bin:${process.env.PATH || ''}`;

    let spawnBin = pythonInfo.bin;
    let spawnArgs = ['--port', BACKEND_PORT.toString()];
    
    if (!pythonInfo.compiled) {
      spawnArgs.unshift(serverScript); // run script via python
    }

    backendProcess = spawn(spawnBin, spawnArgs, {
      cwd: path.join(__dirname, '..', '..'), // project root
      env: { ...process.env, PYTHONUNBUFFERED: '1', PATH: extraPath }
    });

    backendProcess.stdout.on('data', (data) => {
      const msg = data.toString();
      console.log('[Python STDOUT]:', msg);
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('backend-log', msg);
      if (msg.includes('Application startup complete')) resolve();
    });

    backendProcess.stderr.on('data', (data) => {
      const msg = data.toString();
      console.log('[Python STDERR]:', msg);
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('backend-log', '[ERR] ' + msg);
      if (msg.includes('Application startup complete') || msg.includes('Uvicorn running')) resolve();
    });

    backendProcess.on('error', (err) => {
      console.error('Backend process error:', err);
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('backend-log', `[KRİTİK HATA] Backend başlatılamadı: ${err.message}`);
      }
      reject(err);
    });
    
    // Fallback: assume ready after 8 seconds
    setTimeout(resolve, 8000);
  });
}

function waitForBackend(maxTries = 30) {
  return new Promise((resolve) => {
    let tries = 0;
    const check = () => {
      tries++;
      const req = http.get(`http://${BACKEND_HOST}:${BACKEND_PORT}/health`, (res) => {
        if (res.statusCode === 200) resolve(true);
        else if (tries < maxTries) setTimeout(check, 1000);
        else resolve(false);
      });
      req.on('error', () => {
        if (tries < maxTries) setTimeout(check, 1000);
        else resolve(false);
      });
    };
    check();
  });
}

// =============================================================
// WINDOW CREATION
// =============================================================
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1200,
    minHeight: 750,
    titleBarStyle: 'hiddenInset',
    vibrancy: 'dark',
    backgroundColor: '#0a0f1e',
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true // 'local://' protokolü ile güvenli hale getirildi
    },
    show: false
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  if (isDev) mainWindow.webContents.openDevTools({ mode: 'detach' });

  // Renderer console loglarını terminale yönlendir
  mainWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
    console.log(`[Renderer ${line}]: ${message}`);
  });
}

// =============================================================
// AUTO-UPDATE CHECKER (GitHub Releases)
// =============================================================
const GITHUB_REPO = 'sametsoysal/glio-cartography';
const https = require('https');

function semverGt(a, b) {
  // a > b ise true döndür ("v1.2.0" > "v1.1.0")
  const parse = (v) => v.replace(/^v/, '').split('.').map(Number);
  const [a0,a1,a2] = parse(a), [b0,b1,b2] = parse(b);
  if (a0 !== b0) return a0 > b0;
  if (a1 !== b1) return a1 > b1;
  return a2 > b2;
}

function checkForUpdates(silent = false) {
  const currentVersion = `v${app.getVersion()}`;
  const options = {
    hostname: 'api.github.com',
    path: `/repos/${GITHUB_REPO}/releases/latest`,
    headers: { 'User-Agent': 'Glio-Cartography-Updater', 'Accept': 'application/vnd.github.v3+json' },
    timeout: 10000
  };

  const req = https.get(options, (res) => {
    let data = '';
    res.on('data', chunk => data += chunk);
    res.on('end', () => {
      try {
        const release = JSON.parse(data);
        const latestVersion = release.tag_name || '';
        const releaseUrl    = release.html_url || `https://github.com/${GITHUB_REPO}/releases`;
        const releaseNotes  = release.body || '';

        if (!latestVersion) {
          if (!silent) console.log('[Updater] GitHub API yanıtı boş (repo herkese açık değil olabilir)');
          return;
        }

        console.log(`[Updater] Mevcut: ${currentVersion} | En son: ${latestVersion}`);

        if (semverGt(latestVersion, currentVersion)) {
          console.log(`[Updater] Yeni sürüm mevcut: ${latestVersion}`);
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-available', {
              current: currentVersion,
              latest: latestVersion,
              url: releaseUrl,
              notes: releaseNotes.slice(0, 400)
            });
          }
        } else if (!silent) {
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-available', { upToDate: true, current: currentVersion });
          }
        }
      } catch (e) {
        console.warn('[Updater] Parse hatası:', e.message);
      }
    });
  });
  req.on('error', (e) => console.warn('[Updater] Ağ hatası:', e.message));
  req.on('timeout', () => { req.destroy(); console.warn('[Updater] Timeout'); });
}

// =============================================================
// IPC HANDLERS
// =============================================================
ipcMain.handle('get-machine-id', () => getMachineId());
ipcMain.handle('validate-license', (_, key) => validateLicense(key));
ipcMain.handle('save-license', (_, key, expiry) => {
  if (store) store.set('license', { key, machineId: getMachineId(), expiryDate: expiry });
  return true;
});
ipcMain.handle('get-stored-license', () => store ? store.get('license') : null);

ipcMain.handle('select-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Spatial Veri Klasörünü Seçin'
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('select-file', async (_, filters) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    title: 'scRNA-seq Veri Dosyasını Seçin',
    filters: filters || [
      { name: 'scRNA Data', extensions: ['h5ad', 'h5', 'loom', 'csv', 'tsv'] }
    ]
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('select-output-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory'],
    title: 'Çıktı Klasörünü Seçin'
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('open-output-folder', (_, folderPath) => {
  shell.openPath(folderPath);
});

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
      headers
    };
    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch { resolve({ raw: data }); }
      });
    });
    req.on('error', reject);
    if (!isGet && postData) req.write(postData);
    req.end();
  });
});

ipcMain.handle('read-json-file', (_, filePath) => {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (e) {
    return null;
  }
});

ipcMain.handle('file-exists', (_, filePath) => {
  return fs.existsSync(filePath);
});

ipcMain.handle('get-app-version', () => app.getVersion());

// ── Son Kullanılan Yollar ────────────────────────────────────
// Kullanıcı her analizde seçtiği yolları electron-store'da saklar.
// Uygulama yeniden açıldığında bu yollar otomatik yüklenir.
ipcMain.handle('get-last-paths', () => {
  return store ? store.get('lastPaths', null) : null;
});
ipcMain.handle('save-last-paths', (_, paths) => {
  if (store) store.set('lastPaths', paths);
  return true;
});

// Güncelleme kontrolü — renderer'dan manuel tetikleme
ipcMain.handle('check-for-updates', () => checkForUpdates(false));

// Harici URL açma (shell.openExternal)
ipcMain.handle('open-external', (_, url) => {
  const { shell } = require('electron');
  return shell.openExternal(url);
});

// =============================================================
// APP LIFECYCLE
// =============================================================
app.whenReady().then(async () => {
  // Local dosya erişimi için güvenli protokol kaydı
  protocol.registerFileProtocol('local', (request, callback) => {
    const pathname = decodeURI(request.url.replace('local://', ''));
    callback(pathname);
  });

  await initStore();
  createWindow();

  // Wait for window to be shown before sending events
  mainWindow.once('ready-to-show', async () => {
    console.log('Starting Python backend...');
    try {
      // Check if backend is already running (e.g. started externally)
      const alreadyUp = await waitForBackend(3);
      if (alreadyUp) {
        console.log('Backend already running');
        mainWindow.webContents.send('backend-ready', true);
        return;
      }
      await startBackend();
      const ready = await waitForBackend(30);
      console.log(`Backend ready: ${ready}`);
      mainWindow.webContents.send('backend-ready', ready);
      // Backend hazır olduktan 30 sn sonra sessizce güncelleme kontrol et
      setTimeout(() => checkForUpdates(true), 30_000);
    } catch (e) {
      console.error('Backend start failed:', e);
      mainWindow.webContents.send('backend-ready', false);
    }
  });
});

function killBackend() {
  if (backendProcess) {
    try {
      // SIGKILL ensures the process dies immediately, freeing port 8765
      backendProcess.kill('SIGKILL');
    } catch (e) {}
    backendProcess = null;
  }
}

app.on('window-all-closed', () => {
  killBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  killBackend();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
