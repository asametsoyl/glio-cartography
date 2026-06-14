// =============================================================
// GLIO-CARTOGRAPHY — Auto-Update Checker (GitHub Releases)
// =============================================================
// Fixes:
//  - semverGt now handles pre-release labels (v1.2.3-beta.1)
//    and 2-segment versions (v1.2) without NaN comparisons.
//  - checkForUpdates accepts mainWindow parameter and guards
//    against null / destroyed window before sending IPC.
// =============================================================
'use strict';

const https = require('https');
const { app, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const { downloadWithRedirects } = require('./runtime-manager');

const GITHUB_REPO = 'asametsoyl/glio-cartography';

/**
 * Returns true if semver string `a` is greater than `b`.
 * Strips pre-release labels (e.g. -beta.1) before comparing.
 * Pads missing segments with 0 (e.g. "v1.2" → [1, 2, 0]).
 */
function semverGt(a, b) {
  const parse = (v) =>
    v.replace(/^v/, '')
      .split('-')[0]              // strip pre-release label
      .split('.')
      .map(s => parseInt(s, 10) || 0);

  const av = parse(a);
  const bv = parse(b);
  const len = Math.max(av.length, bv.length);

  for (let i = 0; i < len; i++) {
    const ai = av[i] || 0;
    const bi = bv[i] || 0;
    if (ai !== bi) return ai > bi;
  }
  return false;
}

/**
 * Checks GitHub Releases for a newer version.
 * @param {BrowserWindow|null} mainWindow  — Must be checked for null/destroyed before send.
 * @param {boolean}            silent      — If true, only sends event when update is found.
 */
function checkForUpdates(mainWindow, silent = false) {
  // Guard: window may have been closed before the 30-second timer fires
  if (!mainWindow || mainWindow.isDestroyed()) {
    console.log('[Updater] Skipping update check — window is gone.');
    return;
  }

  const currentVersion = `v${app.getVersion()}`;
  const options = {
    hostname: 'api.github.com',
    path: `/repos/${GITHUB_REPO}/releases/latest`,
    headers: {
      'User-Agent': 'Glio-Cartography-Updater',
      'Accept': 'application/vnd.github.v3+json'
    },
    timeout: 10000
  };

  const req = https.get(options, (res) => {
    let data = '';
    res.on('data', chunk => data += chunk);
    res.on('end', () => {
      // Re-check window after async I/O
      if (!mainWindow || mainWindow.isDestroyed()) return;
      try {
        const release = JSON.parse(data);
        const latestVersion = release.tag_name || '';
        const releaseUrl = release.html_url || `https://github.com/${GITHUB_REPO}/releases`;
        const releaseNotes = release.body || '';

        if (!latestVersion) {
          if (!silent) console.log('[Updater] GitHub API yanıtı boş (repo herkese açık değil olabilir)');
          return;
        }

        console.log(`[Updater] Mevcut: ${currentVersion} | En son: ${latestVersion}`);

        if (semverGt(latestVersion, currentVersion)) {
          console.log(`[Updater] Yeni sürüm mevcut: ${latestVersion}`);
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-available', {
              current: currentVersion,
              latest: latestVersion,
              url: releaseUrl,
              notes: releaseNotes.slice(0, 400)
            });
          }
        } else if (!silent) {
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-available', {
              upToDate: true,
              current: currentVersion
            });
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

/**
 * Downloads and installs the given version.
 * @param {BrowserWindow} mainWindow
 * @param {string} version
 */
function startUpdateDownload(mainWindow, version) {
  return new Promise((resolve, reject) => {
    if (!version) {
      return reject(new Error('Sürüm bilgisi belirtilmedi.'));
    }
    const tag = version.startsWith('v') ? version : `v${version}`;
    
    const options = {
      hostname: 'api.github.com',
      path: `/repos/${GITHUB_REPO}/releases/tags/${tag}`,
      headers: {
        'User-Agent': 'Glio-Cartography-Updater',
        'Accept': 'application/vnd.github.v3+json'
      },
      timeout: 10000
    };

    const req = https.get(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          if (res.statusCode !== 200) {
            throw new Error(`GitHub Release API hatası: HTTP ${res.statusCode}`);
          }
          const release = JSON.parse(data);
          const assets = release.assets || [];
          
          let extension = '';
          if (process.platform === 'win32') {
            extension = '.exe';
          } else if (process.platform === 'darwin') {
            extension = '.dmg';
          } else {
            throw new Error(`Uygulama içi güncelleme bu platformda desteklenmiyor: ${process.platform}`);
          }
          
          const asset = assets.find(a => a.name.endsWith(extension));
          if (!asset) {
            throw new Error(`Bu sürüm için uygun kurulum dosyası (${extension}) bulunamadı.`);
          }
          
          const url = asset.browser_download_url;
          const tempDir = app.getPath('temp');
          const savePath = path.join(tempDir, asset.name);
          
          console.log(`[Updater] Indirme basliyor: ${asset.name} -> ${savePath}`);
          
          // clean up old download if exists
          if (fs.existsSync(savePath)) {
            try { fs.unlinkSync(savePath); } catch (e) { }
          }
          
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-download-progress', {
              status: 'downloading',
              percent: 0,
              received: '0.0',
              total: '0.0',
              speed: '0.0'
            });
          }
          
          const startTime = Date.now();
          downloadWithRedirects(url, savePath, (received, total) => {
            const now = Date.now();
            const elapsed = (now - startTime) / 1000;
            const speed = elapsed > 0.1 ? ((received / 1024 / 1024) / elapsed) : 0;
            const percent = Math.round((received / total) * 100);
            
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.webContents.send('update-download-progress', {
                status: 'downloading',
                percent,
                received: (received / 1024 / 1024).toFixed(1),
                total: (total / 1024 / 1024).toFixed(1),
                speed: speed.toFixed(1)
              });
            }
          }).then(() => {
            console.log('[Updater] Indirme tamamlandi. Kurulum tetikleniyor...');
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.webContents.send('update-download-progress', {
                status: 'completed',
                percent: 100
              });
            }
            
            setTimeout(() => {
              if (process.platform === 'win32') {
                spawn(savePath, [], { detached: true, stdio: 'ignore' }).unref();
                app.quit();
              } else if (process.platform === 'darwin') {
                shell.openPath(savePath).then(() => {
                  app.quit();
                }).catch(err => {
                  console.error('macOS DMG acilamadi:', err);
                  app.quit();
                });
              }
            }, 1000);
            
            resolve();
          }).catch(err => {
            console.error('[Updater] Indirme hatasi:', err);
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.webContents.send('update-download-progress', {
                status: 'failed',
                error: err.message
              });
            }
            reject(err);
          });
          
        } catch (e) {
          console.error('[Updater] Isleme hatasi:', e);
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('update-download-progress', {
              status: 'failed',
              error: e.message
            });
          }
          reject(e);
        }
      });
    });
    
    req.on('error', (e) => {
      console.error('[Updater] GitHub API baglanti hatasi:', e);
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('update-download-progress', {
          status: 'failed',
          error: e.message
        });
      }
      reject(e);
    });
    
    req.on('timeout', () => {
      req.destroy();
      const err = new Error('GitHub API bağlantı zaman aşımı.');
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('update-download-progress', {
          status: 'failed',
          error: err.message
        });
      }
      reject(err);
    });
  });
}

module.exports = { checkForUpdates, semverGt, GITHUB_REPO, startUpdateDownload };
