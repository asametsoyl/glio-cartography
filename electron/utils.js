// =============================================================
// GLIO-CARTOGRAPHY — Shared Utilities
// =============================================================
'use strict';

const fs = require('fs');
const { execSync } = require('child_process');
const path = require('path');
const os = require('os');

// ── Diagnostic File Logging ───────────────────────────────────
// Default to tmpdir so logging works before app.whenReady().
// Call setLogPath() inside app.whenReady() to move to documents dir.
let _logPath = path.join(os.tmpdir(), 'glio-diagnostic.log');

const MAX_LOG_SIZE = 5 * 1024 * 1024; // 5 MB — rotate after this

function setLogPath(newPath) {
  _logPath = newPath;
}

function getLogPath() {
  return _logPath;
}

function logToFile(msg) {
  const timestamp = new Date().toISOString();
  // Strip ANSI escape codes
  const cleanMsg = String(msg).replace(
    /[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g,
    ''
  );
  try {
    // Log rotation: rename old file so no log data is lost.
    // diagnostic.log.old is kept as a backup of the previous session.
    try {
      const stat = fs.statSync(_logPath);
      if (stat.size > MAX_LOG_SIZE) {
        try { fs.renameSync(_logPath, _logPath + '.1'); } catch { }
      }
    } catch (e) { /* ignore — file may not exist yet */ }
    fs.appendFileSync(_logPath, `[${timestamp}] ${cleanMsg}\n`);
  } catch (err) {
    process.stderr.write(`Failed to write to log file: ${err.message}\n`);
  }
}

// ── execSync with EINTR retry ─────────────────────────────────
function execSyncWithRetry(command, options = {}, retries = 3) {
  const mergedOptions = { timeout: 2500, ...options };
  for (let i = 0; i < retries; i++) {
    try {
      return execSync(command, mergedOptions);
    } catch (e) {
      const isEintr =
        e.code === 'EINTR' ||
        e.errno === 'EINTR' ||
        (e.message && e.message.includes('EINTR'));
      if (isEintr && i < retries - 1) {
        console.warn(
          `[execSync] Interrupted by EINTR, retrying (${i + 1}/${retries}): ${command}`
        );
        // Safe synchronous micro-delay for main thread context.
        // Atomics.wait is forbidden on the main thread in Electron and will throw.
        const start = Date.now();
        while (Date.now() - start < 20) { /* spin */ }
        continue;
      }
      throw e;
    }
  }
}

// ── execFileSync with EINTR retry ─────────────────────────────
function execFileSyncWithRetry(file, args = [], options = {}, retries = 3) {
  const { execFileSync } = require('child_process');
  const mergedOptions = { timeout: 2500, ...options };
  for (let i = 0; i < retries; i++) {
    try {
      return execFileSync(file, args, mergedOptions);
    } catch (e) {
      const isEintr =
        e.code === 'EINTR' ||
        e.errno === 'EINTR' ||
        (e.message && e.message.includes('EINTR'));
      if (isEintr && i < retries - 1) {
        console.warn(
          `[execFileSync] Interrupted by EINTR, retrying (${i + 1}/${retries}): ${file}`
        );
        const start = Date.now();
        while (Date.now() - start < 20) { /* spin */ }
        continue;
      }
      throw e;
    }
  }
}

let _store = null;
const _customAllowedDirs = new Set();

function setStore(store) {
  _store = store;
}

/**
 * Dynamically whitelists a user-chosen file or directory path for the current session.
 * @param {string} dirOrFilePath
 */
function addAllowedPath(dirOrFilePath) {
  if (!dirOrFilePath || typeof dirOrFilePath !== 'string') return;
  try {
    const clean = path.resolve(dirOrFilePath).replace(/^\\\\\?\\/, '');
    if (fs.existsSync(clean) && !fs.statSync(clean).isDirectory()) {
      _customAllowedDirs.add(path.dirname(clean));
    } else {
      _customAllowedDirs.add(clean);
    }
  } catch {
    // If path does not exist yet (e.g. pending output dir), add its resolved directory
    try {
      _customAllowedDirs.add(path.resolve(dirOrFilePath).replace(/^\\\\\?\\/, ''));
    } catch {}
  }
}

// ── Whitelist base directories ────────────────────────────────
function getAllowedBaseDirs() {
  const path = require('path');
  const os = require('os');

  const dirs = [os.tmpdir()];

  try {
    if (process.versions && process.versions.electron) {
      const electron = require('electron');
      const app = electron && electron.app;
      if (app && typeof app.getPath === 'function') {
        try { dirs.push(app.getPath('userData')); } catch {}
        try { dirs.push(app.getPath('documents')); } catch {}
        try { dirs.push(app.getPath('desktop')); } catch {}
        try { dirs.push(app.getPath('home')); } catch {}
        try { dirs.push(app.getPath('temp')); } catch {}
        try { dirs.push(app.getPath('downloads')); } catch {}
      }
    }
  } catch {}

  // Include user paths saved in config store
  if (_store) {
    try {
      const lastPaths = _store.get('lastPaths', null);
      if (lastPaths && typeof lastPaths === 'object') {
        if (lastPaths.output) dirs.push(lastPaths.output);
        if (lastPaths.spatial) dirs.push(lastPaths.spatial);
        if (lastPaths.scrna) dirs.push(path.dirname(lastPaths.scrna));
      }
      const profiles = _store.get('profiles', []);
      if (Array.isArray(profiles)) {
        for (const p of profiles) {
          if (p && typeof p === 'object') {
            if (p.output) dirs.push(p.output);
            if (p.spatial) dirs.push(p.spatial);
            if (p.scrna) dirs.push(path.dirname(p.scrna));
          }
        }
      }
    } catch {}
  }

  // Include dynamically whitelisted session paths
  for (const cd of _customAllowedDirs) {
    dirs.push(cd);
  }

  return dirs
    .filter(Boolean)
    .map(d => path.resolve(d).replace(/^\\\\\?\\/, ''));
}

/**
 * Checks if a resolved path is within the allowed whitelisted base directories,
 * using case-insensitive checks on macOS/Windows, Unicode NFC normalization,
 * and stripping the Windows \\?\ extended-length path prefix.
 */
function isPathAllowed(filePath) {
  if (!filePath || typeof filePath !== 'string') return false;

  // Strip Windows extended path prefix if present in input
  const cleanInput = filePath.replace(/^\\\\\?\\/, '');

  let resolvedPath;
  try {
    resolvedPath = fs.realpathSync(cleanInput);
  } catch (err) {
    try {
      resolvedPath = path.resolve(cleanInput);
    } catch {
      resolvedPath = cleanInput;
    }
  }

  // Strip Windows extended path prefix if added by fs.realpathSync
  resolvedPath = resolvedPath.replace(/^\\\\\?\\/, '');

  const normResolved = resolvedPath.normalize('NFC');
  const allowedDirs = getAllowedBaseDirs();

  return allowedDirs.some(baseDir => {
    let cleanBaseDir = (baseDir || '').replace(/^\\\\\?\\/, '');
    let rPath = normResolved;
    let bDir = cleanBaseDir.normalize('NFC');
    if (process.platform === 'darwin' || process.platform === 'win32') {
      rPath = rPath.toLowerCase();
      bDir = bDir.toLowerCase();
    }
    const bDirWithSep = bDir.endsWith(path.sep) ? bDir : bDir + path.sep;
    return rPath === bDir || rPath.startsWith(bDirWithSep);
  });
}

// ── Safe IPC Send ─────────────────────────────────────────────
/**
 * Sends an IPC message to mainWindow only if it exists and is not destroyed.
 * Avoids the common null.isDestroyed() crash pattern.
 */
function safeSend(mainWindow, channel, ...args) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, ...args);
  }
}

module.exports = {
  logToFile,
  setLogPath,
  getLogPath,
  execSyncWithRetry,
  execFileSyncWithRetry,
  getAllowedBaseDirs,
  isPathAllowed,
  safeSend,
  setStore,
  addAllowedPath
};
