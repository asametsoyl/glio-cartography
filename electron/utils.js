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

// ── Whitelist base directories ────────────────────────────────
function getAllowedBaseDirs() {
  const { app } = require('electron');
  const path = require('path');
  const os = require('os');
  return [
    app.getPath('userData'),
    app.getPath('documents'),
    app.getPath('desktop'),
    app.getPath('home'),
    app.getPath('temp'),
    os.tmpdir()
  ].map(d => path.resolve(d));
}

/**
 * Checks if a resolved path is within the allowed whitelisted base directories,
 * using case-insensitive checks on macOS/Windows and Unicode NFC normalization.
 */
function isPathAllowed(filePath) {
  if (!filePath) return false;
  let resolvedPath;
  try {
    resolvedPath = fs.realpathSync(filePath);
  } catch (err) {
    try {
      resolvedPath = path.resolve(filePath);
    } catch {
      resolvedPath = filePath;
    }
  }

  const normResolved = resolvedPath.normalize('NFC');
  const allowedDirs = getAllowedBaseDirs();

  return allowedDirs.some(baseDir => {
    let rPath = normResolved;
    let bDir = baseDir.normalize('NFC');
    if (process.platform === 'darwin' || process.platform === 'win32') {
      rPath = rPath.toLowerCase();
      bDir = bDir.toLowerCase();
    }
    return rPath === bDir || rPath.startsWith(bDir + path.sep);
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

module.exports = { logToFile, setLogPath, getLogPath, execSyncWithRetry, execFileSyncWithRetry, getAllowedBaseDirs, isPathAllowed, safeSend };
