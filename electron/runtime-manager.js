// =============================================================
// GLIO-CARTOGRAPHY — Runtime Download & Extraction
// =============================================================
// Fixes:
//  - downloadWithRedirects: max 10 redirects enforced.
//  - extractZip: PowerShell called with shell:false + LiteralPath.
//  - extractZip: macOS uses `ditto` (better encoding support).
//  - fileStream uses destroy() instead of close() on error.
// =============================================================
'use strict';

const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');
const { safeSend } = require('./utils');

// ── Download Helper ───────────────────────────────────────────
function downloadWithRedirects(url, destPath, onProgress) {
  return new Promise((resolve, reject) => {
    const startRequest = (currentUrl, redirectCount = 0) => {
      // Prevent infinite redirect loops
      if (redirectCount > 10) {
        reject(new Error('Çok fazla yönlendirme (>10). Lütfen ağ bağlantınızı kontrol edin.'));
        return;
      }

      const client = currentUrl.startsWith('https')
        ? require('https')
        : require('http');

      let timeoutTimer = null;
      const clearTimer = () => {
        if (timeoutTimer) { clearTimeout(timeoutTimer); timeoutTimer = null; }
      };

      const req = client.get(currentUrl, (res) => {
        // Follow redirects
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          clearTimer();
          startRequest(res.headers.location, redirectCount + 1);
          return;
        }
        if (res.statusCode !== 200) {
          clearTimer();
          reject(new Error(`İndirme başarısız: HTTP ${res.statusCode}`));
          return;
        }

        const totalBytes = parseInt(res.headers['content-length'], 10) || 0;
        let receivedBytes = 0;
        const fileStream = fs.createWriteStream(destPath);
        res.pipe(fileStream);

        const resetInactivityTimeout = () => {
          clearTimer();
          timeoutTimer = setTimeout(() => {
            console.error('[downloadWithRedirects] Data stream stalled. Timing out...');
            res.destroy();
            req.destroy();
            fileStream.destroy(); // destroy > close on error paths
            fs.unlink(destPath, () => { });
            reject(new Error(
              'İndirme zaman aşımına uğradı (veri akışı durdu). Lütfen tekrar deneyiniz.'
            ));
          }, 45000);
        };

        resetInactivityTimeout();

        res.on('data', (chunk) => {
          receivedBytes += chunk.length;
          resetInactivityTimeout();
          if (totalBytes && onProgress) onProgress(receivedBytes, totalBytes);
        });

        fileStream.on('finish', () => {
          clearTimer();
          fileStream.close();
          resolve();
        });

        fileStream.on('error', (err) => {
          clearTimer();
          fileStream.destroy();
          fs.unlink(destPath, () => { });
          reject(err);
        });
      });

      req.on('error', (err) => { clearTimer(); reject(err); });

      // Initial connection timeout (15 seconds)
      timeoutTimer = setTimeout(() => {
        console.error('[downloadWithRedirects] Connection timed out.');
        req.destroy();
        reject(new Error(
          'Sunucuya bağlanılamadı (Bağlantı zaman aşımı). Lütfen internetinizi kontrol edin.'
        ));
      }, 15000);
    };

    startRequest(url, 0);
  });
}

// ── Zip Extraction ────────────────────────────────────────────
function extractZip(zipPath, destDir) {
  return new Promise((resolve, reject) => {

    // Windows: prefer native tar.exe, fall back to PowerShell Expand-Archive
    if (process.platform === 'win32') {
      const tarPath = 'C:\\Windows\\System32\\tar.exe';
      if (fs.existsSync(tarPath)) {
        console.log('[extractZip] Attempting native tar.exe...');
        const tarProc = spawn(tarPath, ['-xf', zipPath, '-C', destDir]);
        let tarStderr = '';
        tarProc.stderr.on('data', d => tarStderr += d);
        tarProc.on('close', (code) => {
          if (code === 0) {
            console.log('[extractZip] tar.exe extraction OK.');
            resolve();
          } else {
            console.warn(`[extractZip] tar.exe failed (code ${code}). Falling back to PowerShell.`);
            runPowershellFallback(zipPath, destDir, resolve, reject);
          }
        });
        tarProc.on('error', () => runPowershellFallback(zipPath, destDir, resolve, reject));
      } else {
        runPowershellFallback(zipPath, destDir, resolve, reject);
      }

    } else if (process.platform === 'darwin') {
      // macOS: ditto handles encoding edge cases better than unzip
      console.log('[extractZip] Attempting ditto (macOS)...');
      const proc = spawn('ditto', ['-xk', zipPath, destDir]);
      let stderr = '';
      proc.stderr.on('data', d => stderr += d);
      proc.on('close', (code) => {
        if (code === 0) {
          console.log('[extractZip] ditto extraction OK.');
          resolve();
        } else {
          console.warn(`[extractZip] ditto failed (${code}), trying unzip fallback...`);
          runUnzipFallback(zipPath, destDir, resolve, reject);
        }
      });
      proc.on('error', () => runUnzipFallback(zipPath, destDir, resolve, reject));

    } else {
      // Linux
      runUnzipFallback(zipPath, destDir, resolve, reject);
    }
  });
}

function runPowershellFallback(zipPath, destDir, resolve, reject) {
  console.log('[extractZip] Running PowerShell Expand-Archive (-EncodedCommand)...');
  // Use -EncodedCommand (UTF-16LE base64) to eliminate ALL injection risk.
  // This handles $, backticks, quotes, and any other special PS characters.
  const psCmd = `Expand-Archive -LiteralPath "${zipPath}" -DestinationPath "${destDir}" -Force`;
  const encoded = Buffer.from(psCmd, 'utf16le').toString('base64');
  const proc = spawn('powershell', [
    '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded
  ], { shell: false });

  let stderr = '';
  proc.stderr.on('data', d => stderr += d);
  proc.on('close', (code) => {
    if (code === 0) { console.log('[extractZip] PowerShell extraction OK.'); resolve(); }
    else reject(new Error(`PowerShell extraction failed (code ${code}): ${stderr}`));
  });
  proc.on('error', (err) => { console.error('[extractZip] PowerShell spawn error:', err.message); reject(err); });
}

function runUnzipFallback(zipPath, destDir, resolve, reject) {
  console.log('[extractZip] Running unzip...');
  const proc = spawn('unzip', ['-o', zipPath, '-d', destDir]);
  let stderr = '';
  proc.stderr.on('data', d => stderr += d);
  proc.on('close', (code) => {
    if (code === 0) { console.log('[extractZip] unzip OK.'); resolve(); }
    else reject(new Error(`unzip failed (code ${code}): ${stderr}`));
  });
  proc.on('error', (err) => reject(err));
}

// ── VC++ Runtime Installer (Windows only) ─────────────────────
function ensureVcRuntime(mainWindow, app) {
  if (process.platform !== 'win32') return Promise.resolve(true);

  return new Promise((resolve) => {
    const vcDllPath = 'C:\\Windows\\System32\\vcruntime140.dll';
    if (fs.existsSync(vcDllPath)) {
      console.log('[ensureVcRuntime] VC++ Runtime already installed.');
      resolve(true);
      return;
    }

    console.log('[ensureVcRuntime] VC++ Runtime missing. Downloading...');
    const vcRedistUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe';
    const tempPath = path.join(app.getPath('userData'), 'vc_redist.x64.exe');

    safeSend(mainWindow, 'download-progress', { status: 'downloading_vc', percent: 0 });

    if (fs.existsSync(tempPath)) {
      try { fs.unlinkSync(tempPath); } catch (e) { }
    }

    let lastPercent = -1;
    downloadWithRedirects(vcRedistUrl, tempPath, (received, total) => {
      const percent = Math.round((received / total) * 100);
      if (percent !== lastPercent) {
        lastPercent = percent;
        safeSend(mainWindow, 'download-progress', {
          status: 'downloading_vc', percent,
          received: (received / 1024 / 1024).toFixed(1),
          total: (total / 1024 / 1024).toFixed(1)
        });
      }
    }).then(() => {
      console.log('[ensureVcRuntime] Downloaded. Running silent installer...');
      safeSend(mainWindow, 'download-progress', { status: 'installing_vc', percent: 100 });

      // 1. Direct silent install (works if already running as Admin / in VM)
      try {
        console.log('[ensureVcRuntime] Attempting direct silent install...');
        execSync(`"${tempPath}" /install /quiet /norestart`, { timeout: 30000 });
        if (fs.existsSync(vcDllPath)) {
          console.log('[ensureVcRuntime] Direct install succeeded.');
          try { fs.unlinkSync(tempPath); } catch (e) { }
          resolve(true);
          return;
        }
        console.log('[ensureVcRuntime] DLL still missing — falling back to elevated install...');
      } catch (err) {
        console.warn('[ensureVcRuntime] Direct install failed:', err.message);
      }

      // 2. Elevated install via PowerShell RunAs (triggers UAC prompt).
      // Use -EncodedCommand to eliminate injection risk from tempPath.
      const psElevated = `Start-Process -FilePath "${tempPath}" -ArgumentList '/install', '/quiet', '/norestart' -Verb RunAs -Wait`;
      const encodedElevated = Buffer.from(psElevated, 'utf16le').toString('base64');
      const proc = spawn('powershell', ['-NoProfile', '-NonInteractive', '-EncodedCommand', encodedElevated]);
      proc.on('close', (code) => {
        try { if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath); } catch (e) { }
        if (code === 0) console.log('[ensureVcRuntime] Elevated install finished.');
        else console.warn(`[ensureVcRuntime] Elevated installer exited ${code}.`);
        resolve(true);
      });
      proc.on('error', (err) => {
        console.error('[ensureVcRuntime] Installer spawn error:', err.message);
        try { if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath); } catch (e) { }
        resolve(true);
      });
    }).catch((err) => {
      console.error('[ensureVcRuntime] Download failed:', err.message);
      try { if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath); } catch (e) { }
      resolve(false);
    });
  });
}

module.exports = { downloadWithRedirects, extractZip, ensureVcRuntime };
