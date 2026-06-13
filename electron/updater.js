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
const { app } = require('electron');

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

module.exports = { checkForUpdates, semverGt, GITHUB_REPO };
