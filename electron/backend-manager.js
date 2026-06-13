// =============================================================
// GLIO-CARTOGRAPHY — Backend Process Manager
// =============================================================
// Fixes:
//  - killBackend: SIGTERM → 5s → SIGKILL graceful shutdown.
//  - killBackend sets backendProcess=null immediately to
//    prevent double-kill across multiple event handlers.
//  - killProcessOnPort: uses /R regex on Windows to avoid
//    matching :58765 when targeting :8765.
//  - startBackend: uses app.isPackaged to find server.py.
// =============================================================
'use strict';

const path = require('path');
const { spawn, execSync } = require('child_process');
const http = require('http');
const fs = require('fs');
const os = require('os');
const { execSyncWithRetry, execFileSyncWithRetry, safeSend } = require('./utils');

const BACKEND_PORT = 8765;
const BACKEND_HOST = '127.0.0.1';

let backendProcess = null;
let backendState = { status: 'starting', error: null };

function getBackendPort() { return BACKEND_PORT; }
function getBackendHost() { return BACKEND_HOST; }
function getBackendState() { return backendState; }
function setBackendState(status, error = null) {
  backendState.status = status;
  backendState.error = error;
}

// ── Python Environment Helpers ────────────────────────────────
function getExtendedPath(pythonPath) {
  const pythonBinDir = path.dirname(pythonPath);
  const sep = process.platform === 'win32' ? ';' : ':';

  if (process.platform === 'win32') {
    let envRoot = pythonBinDir;
    const baseName = path.basename(pythonBinDir).toLowerCase();
    if (baseName === 'scripts' || baseName === 'bin') envRoot = path.dirname(pythonBinDir);

    const candidates = [
      pythonBinDir,
      path.join(envRoot, 'Scripts'),
      envRoot,
      path.join(envRoot, 'Library', 'bin'),
      path.join(envRoot, 'Library', 'usr', 'bin'),
      path.join(envRoot, 'Library', 'mingw-w64', 'bin'),
      path.join(envRoot, 'DLLs'),
      path.join(envRoot, 'Lib', 'site-packages', 'torch', 'lib')
    ];
    const unique = [...new Set(candidates)].filter(p => {
      try { return p && fs.existsSync(p); } catch { return false; }
    });
    return process.env.PATH ? `${unique.join(sep)}${sep}${process.env.PATH}` : unique.join(sep);
  } else {
    const candidates = [
      pythonBinDir,
      '/opt/homebrew/Caskroom/miniforge/base/bin',
      '/opt/homebrew/bin',
      '/usr/local/bin'
    ];
    const unique = [...new Set(candidates)].filter(p => {
      try { return p && fs.existsSync(p); } catch { return false; }
    });
    return process.env.PATH ? `${unique.join(sep)}${sep}${process.env.PATH}` : unique.join(sep);
  }
}

function verifyPython(pythonPath) {
  try {
    const extraPath = getExtendedPath(pythonPath);
    console.log(`[verifyPython] Testing: ${pythonPath}`);
    execFileSyncWithRetry(pythonPath, ['-V'], {
      stdio: 'pipe',
      timeout: 10000,
      env: { ...process.env, PATH: extraPath, KMP_DUPLICATE_LIB_OK: 'TRUE' }
    });
    console.log(`[verifyPython] OK: ${pythonPath}`);
    return true;
  } catch (e) {
    const stderrStr = e.stderr ? e.stderr.toString() : '';
    console.error(`[verifyPython] FAILED for ${pythonPath}: ${e.message}\n${stderrStr}`);
    return false;
  }
}

function findExtractedPython(envDir) {
  const scanDirs = [envDir];
  try {
    if (fs.existsSync(envDir)) {
      for (const f of fs.readdirSync(envDir)) {
        try {
          const fullPath = path.join(envDir, f);
          if (fs.statSync(fullPath).isDirectory()) {
            scanDirs.push(fullPath);
          }
        } catch { }
      }
    }
  } catch (e) {
    console.warn('[findExtractedPython] Error reading envDir:', e.message);
  }

  for (const dir of scanDirs) {
    const candidates = process.platform === 'win32'
      ? [path.join(dir, 'python.exe'), path.join(dir, 'Scripts', 'python.exe')]
      : [path.join(dir, 'bin', 'python3'), path.join(dir, 'bin', 'python'), path.join(dir, 'python')];

    for (const c of candidates) {
      try {
        const stat = fs.statSync(c);
        if (stat.isFile() && (process.platform !== 'win32' || stat.size > 10240)) return c;
      } catch { }
    }
  }
  return null;
}

function findPython(store, app) {
  const resources = process.resourcesPath || __dirname;

  // 0. User-selected custom path
  const customPath = store ? store.get('customPythonPath') : null;
  if (customPath && fs.existsSync(customPath)) {
    if (verifyPython(customPath)) return { bin: customPath, compiled: false };
  }

  // 1. PyInstaller compiled executable
  const pyinstallerMac = path.join(resources, 'python_env', 'server');
  const pyinstallerWin = path.join(resources, 'python_env', 'server.exe');
  if (fs.existsSync(pyinstallerMac)) return { bin: pyinstallerMac, compiled: true };
  if (fs.existsSync(pyinstallerWin)) return { bin: pyinstallerWin, compiled: true };

  // 2. Bundled venv / conda-pack environments
  const userData = app.getPath('userData');
  const venvs = [
    path.join(userData, 'python_env', 'python.exe'),
    path.join(userData, 'python_env', 'Scripts', 'python.exe'),
    path.join(userData, 'python_env', 'bin', 'python3'),
    path.join(userData, 'python_env', 'bin', 'python'),
    path.join(resources, 'python_env', 'bin', 'python3'),
    path.join(resources, 'python_env', 'bin', 'python'),
    path.join(resources, 'python_env', 'Scripts', 'python.exe'),
    path.join(resources, 'python_env', 'python.exe'),
    path.join(__dirname, '..', 'python_env', 'bin', 'python3'),
    path.join(__dirname, '..', 'python_env', 'bin', 'python'),
    path.join(__dirname, '..', 'python_env', 'Scripts', 'python.exe'),
    path.join(__dirname, '..', 'python_env', 'python.exe'),
    path.join(__dirname, '..', '..', 'python_env', 'bin', 'python3'),
    path.join(__dirname, '..', '..', 'python_env', 'Scripts', 'python.exe')
  ];

  for (const venvPath of venvs) {
    if (fs.existsSync(venvPath)) {
      console.log(`[findPython] Candidate: ${venvPath}`);
      if (verifyPython(venvPath)) return { bin: venvPath, compiled: false };
      else console.warn(`[findPython] Verification failed: ${venvPath}`);
    }
  }

  // 3. Platform-specific system / Anaconda / Miniconda candidates
  if (process.platform === 'win32') {
    const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
    const programData = process.env.PROGRAMDATA || 'C:\\ProgramData';
    const winCandidates = [
      path.join(os.homedir(), 'anaconda3', 'python.exe'),
      path.join(os.homedir(), 'miniconda3', 'python.exe'),
      path.join(os.homedir(), 'Anaconda3', 'python.exe'),
      path.join(os.homedir(), 'Miniconda3', 'python.exe'),
      path.join(programData, 'anaconda3', 'python.exe'),
      path.join(programData, 'miniconda3', 'python.exe'),
      path.join(programData, 'Anaconda3', 'python.exe'),
      path.join(programData, 'Miniconda3', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python313', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python312', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python311', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python310', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python39', 'python.exe'),
      'C:\\Python313\\python.exe', 'C:\\Python312\\python.exe',
      'C:\\Python311\\python.exe', 'C:\\Python310\\python.exe', 'C:\\Python39\\python.exe'
    ];
    for (const p of winCandidates) {
      if (!fs.existsSync(p)) continue;
      try {
        const stat = fs.statSync(p); // read once
        if (!stat.isFile() || stat.size < 10240) continue;
      } catch { continue; }
      if (verifyPython(p)) return { bin: p, compiled: false };
    }
  } else {
    const macCandidates = [
      '/opt/homebrew/Caskroom/miniforge/base/envs/gliocarto/bin/python3',
      '/opt/homebrew/Caskroom/miniforge/base/bin/python3',
      '/opt/homebrew/opt/python@3.12/bin/python3',
      '/opt/homebrew/opt/python@3.11/bin/python3',
      '/opt/homebrew/bin/python3',
      '/usr/local/bin/python3',
      '/usr/bin/python3'
    ];
    for (const p of macCandidates) {
      if (!fs.existsSync(p)) continue;
      if (verifyPython(p)) return { bin: p, compiled: false };
    }
  }

  // Last resort: ask the shell
  let shellPythons = [];
  try {
    const cmd = process.platform === 'win32' ? 'where python' : 'which python3';
    const output = execSyncWithRetry(cmd, { shell: true, timeout: 1500 }).toString().trim();
    shellPythons = output.split('\r').join('').split('\n').map(p => p.trim()).filter(Boolean);
    for (const fallback of shellPythons) {
      try {
        const stat = fs.statSync(fallback);
        if (stat.isFile() && (process.platform !== 'win32' || stat.size > 10240)) {
          if (verifyPython(fallback)) return { bin: fallback, compiled: false };
        }
      } catch { }
    }
  } catch { }

  if (process.platform === 'win32') {
    let hasRealPython = false;
    for (const p of shellPythons) {
      try {
        const stat = fs.statSync(p);
        if (stat.isFile() && stat.size > 10240) {
          hasRealPython = true;
          break;
        }
      } catch { }
    }
    if (!hasRealPython) {
      console.warn('[findPython] No valid python on PATH (only Store aliases or nothing).');
      return { bin: null, compiled: false };
    }
  }

  console.warn('[findPython] No verified Python found.');
  return { bin: null, compiled: false };
}

// ── Port Cleanup ──────────────────────────────────────────────
function killProcessOnPort(port) {
  try {
    if (process.platform === 'win32') {
      // Use /R with a regex pattern that includes a trailing space to prevent
      // matching port 58765 when looking for port 8765.
      const output = execSync(`netstat -ano | findstr /R ":${port} "`, { timeout: 3000 })
        .toString();
      for (const line of output.split('\n')) {
        if (line.includes('LISTENING')) {
          const parts = line.trim().split(/\s+/);
          const pid = parts[parts.length - 1];
          if (pid && pid !== '0') {
            console.log(`[Port Cleanup] Killing process ${pid} on port ${port}`);
            execSync(`taskkill /F /PID ${pid}`, { timeout: 3000 });
          }
        }
      }
    } else {
      try {
        const pid = execSync(`lsof -t -i:${port}`, { timeout: 3000 }).toString().trim();
        if (pid) {
          console.log(`[Port Cleanup] Killing process ${pid} on port ${port}`);
          execSync(`kill -9 ${pid}`, { timeout: 3000 });
        }
      } catch { }
    }
  } catch { /* Port not in use or command not available — normal */ }
}

// ── Backend Spawn ─────────────────────────────────────────────
function startBackend(mainWindow, store, app) {
  return new Promise((resolve, reject) => {
    const pythonInfo = findPython(store, app);
    if (!pythonInfo.bin) {
      const err = new Error(
        'Glio-Cartography için gerekli analiz bileşenleri bulunamadı. Lütfen bileşenlerin otomatik kurulumunu başlatın.'
      );
      console.error('[startBackend] ' + err.message);
      safeSend(mainWindow, 'backend-log', `[KRİTİK HATA] ${err.message}`);
      reject(err);
      return;
    }

    console.log(`[startBackend] Spawning: ${pythonInfo.bin} (compiled: ${pythonInfo.compiled})`);

    // Use app.getAppPath() in packaged app to find server.py (which is in files, not extraResources)
    const serverScript = app.isPackaged
      ? path.join(app.getAppPath(), 'python_backend', 'server.py')
      : path.join(__dirname, '..', 'python_backend', 'server.py');

    const extraPath = getExtendedPath(pythonInfo.bin);
    const spawnArgs = ['--port', BACKEND_PORT.toString()];
    if (!pythonInfo.compiled) spawnArgs.unshift(serverScript);

    let hasExited = false;
    let resolved = false;

    backendProcess = spawn(pythonInfo.bin, spawnArgs, {
      cwd: app.isPackaged ? process.resourcesPath : path.join(__dirname, '..', '..'),
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
        PATH: extraPath,
        KMP_DUPLICATE_LIB_OK: 'TRUE'
      }
    });

    const fallbackTimeout = setTimeout(() => {
      if (!hasExited && !resolved) {
        console.log('[startBackend] Startup timeout fallback triggered.');
        resolved = true;
        resolve();
      }
    }, 8000);

    const checkStartup = (msg) => {
      if (msg.includes('Application startup complete') || msg.includes('Uvicorn running')) {
        if (!resolved) {
          console.log('[startBackend] Backend confirmed running.');
          clearTimeout(fallbackTimeout);
          resolved = true;
          resolve();
        }
      }
    };

    backendProcess.stdout.on('data', (data) => {
      const msg = data.toString();
      console.log('[Python STDOUT]:', msg);
      safeSend(mainWindow, 'backend-log', msg);
      checkStartup(msg);
    });

    backendProcess.stderr.on('data', (data) => {
      const msg = data.toString();
      console.log('[Python STDERR]:', msg);
      safeSend(mainWindow, 'backend-log', '[ERR] ' + msg);
      checkStartup(msg);
    });

    backendProcess.on('error', (err) => {
      console.error('[startBackend] Spawn error:', err);
      clearTimeout(fallbackTimeout);
      safeSend(mainWindow, 'backend-log', `[KRİTİK HATA] Backend başlatılamadı: ${err.message}`);
      if (!resolved) { resolved = true; reject(err); }
    });

    backendProcess.on('exit', (code, signal) => {
      hasExited = true;
      clearTimeout(fallbackTimeout);
      console.error(`[startBackend] Backend exited — code: ${code}, signal: ${signal}`);
      safeSend(mainWindow, 'backend-log', `[KRİTİK HATA] Backend kapandı (kod: ${code}, sinyal: ${signal})`);
      if (!resolved) { resolved = true; reject(new Error(`Backend sonlandı (Kod: ${code})`)); }
    });
  });
}

// ── Health Check ──────────────────────────────────────────────
function waitForBackend(maxTries = 30) {
  return new Promise((resolve) => {
    let tries = 0;
    const check = () => {
      tries++;
      let completed = false;
      const done = (val) => { if (!completed) { completed = true; resolve(val); } };
      const next = () => {
        if (!completed) {
          completed = true;
          if (tries < maxTries) setTimeout(check, 1000);
          else resolve(false);
        }
      };

      const req = http.get(
        { hostname: BACKEND_HOST, port: BACKEND_PORT, path: '/health', timeout: 2000 },
        (res) => {
          res.resume(); // consume body so the socket is freed immediately
          if (res.statusCode === 200) done(true); else next();
        }
      );
      req.on('timeout', () => {
        console.warn(`[waitForBackend] Timeout (attempt ${tries}/${maxTries})`);
        req.destroy();
        next();
      });
      req.on('error', () => next());
    };
    check();
  });
}

// ── Backend Shutdown ──────────────────────────────────────────
function killBackend() {
  if (!backendProcess) return;

  const proc = backendProcess;
  backendProcess = null; // Clear reference immediately — prevents double-kill from multiple event handlers

  try {
    if (process.platform === 'win32') {
      // Windows: kill entire process tree to include uvicorn workers
      console.log(`[Backend Cleanup] Killing process tree PID ${proc.pid}`);
      execSync(`taskkill /F /T /PID ${proc.pid}`, { timeout: 5000 });
    } else {
      // Unix: graceful SIGTERM first, then SIGKILL after 5 seconds
      console.log(`[Backend Cleanup] Sending SIGTERM to PID ${proc.pid}`);
      proc.kill('SIGTERM');
      setTimeout(() => {
        if (!proc.killed) {
          console.log(`[Backend Cleanup] SIGTERM timed out — sending SIGKILL to PID ${proc.pid}`);
          try { proc.kill('SIGKILL'); } catch { /* already exited */ }
        }
      }, 5000);
    }
  } catch (e) {
    console.warn(`[Backend Cleanup] Failed to kill backend:`, e.message);
  }
}

module.exports = {
  startBackend,
  waitForBackend,
  killBackend,
  findPython,
  findExtractedPython,
  verifyPython,
  getExtendedPath,
  killProcessOnPort,
  getBackendPort,
  getBackendHost,
  getBackendState,
  setBackendState,
  BACKEND_PORT,
  BACKEND_HOST
};
