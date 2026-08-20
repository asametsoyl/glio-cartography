// =============================================================
// GLIO-CARTOGRAPHY — Auto-Update Checker (GitHub Releases)
// =============================================================
// v3.1 
// =============================================================
'use strict';

const https = require('https');
const crypto = require('crypto');
const { promisify } = require('util');
const { app, shell } = require('electron');
const { spawn,
  execFile } = require('child_process');
const path = require('path');
const fs = require('fs');
const { downloadWithRedirects } = require('./runtime-manager');

const execFileAsync = promisify(execFile);
const GITHUB_REPO = 'asametsoyl/glio-cartography';
const UPDATE_MANIFEST_URL = process.env.GLIO_UPDATE_MANIFEST_URL || null;
let _lastCheckMs = 0;
const CHECK_INTERVAL_MS = 60 * 60 * 1000; // saatte bir

// ─────────────────────────────────────────────────────────────────────────────
// Yardımcılar
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Null/destroyed pencere guard ile güvenli IPC gönderimi.
 * @param {BrowserWindow|null} win
 * @param {string} channel
 * @param  {...any} args
 */
function safeSend(win, channel, ...args) {
  if (win && !win.isDestroyed()) {
    win.webContents.send(channel, ...args);
  }
}

function semverGt(a, b) {
  const parseVer = (v) => {
    const clean = v.replace(/^v/i, '');
    const [main, pre = ''] = clean.split('-');
    const nums = main.split('.').map(s => Math.max(0, parseInt(s, 10) || 0));
    while (nums.length < 3) nums.push(0);
    return { nums, pre };
  };

  const av = parseVer(a);
  const bv = parseVer(b);

  for (let i = 0; i < 3; i++) {
    if (av.nums[i] !== bv.nums[i]) return av.nums[i] > bv.nums[i];
  }

  // Aynı versiyon — pre-release karşılaştırması
  // Kararlı (pre='') her zaman pre-release'ten büyüktür
  if (!av.pre && bv.pre) return true;   // 1.0.0 > 1.0.0-beta
  if (av.pre && !bv.pre) return false;  // 1.0.0-beta < 1.0.0
  return av.pre > bv.pre;               // leksikografik (beta.2 > beta.1)
}

// ─────────────────────────────────────────────────────────────────────────────
// Güncelleme Kontrolü
// ─────────────────────────────────────────────────────────────────────────────

/**
 * GitHub Releases API'sini sorgular ve yeni sürüm varsa event gönderir.
 * @param {BrowserWindow|null} mainWindow
 * @param {boolean}            silent      — true ise sadece güncelleme varsa event
 * @param {boolean}            forceCheck  — rate-limit'i bypass et
 */
function checkForUpdates(mainWindow, silent = false, forceCheck = false) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    console.log('[Updater] Güncelleme kontrolü atlandı — pencere kapalı.');
    return;
  }

  const now = Date.now();
  if (!forceCheck && now - _lastCheckMs < CHECK_INTERVAL_MS) {
    console.log('[Updater] Rate-limit: son kontrolden bu yana yeterli süre geçmedi.');
    return;
  }
  _lastCheckMs = now;

  const currentVersion = `v${app.getVersion()}`;
  const options = _buildApiOptions(`/repos/${GITHUB_REPO}/releases/latest`);

  const req = https.get(options, (res) => {
    let data = '';
    res.on('data', chunk => data += chunk);
    res.on('end', () => {
      if (!mainWindow || mainWindow.isDestroyed()) return;
      try {
        if (res.statusCode === 403) {
          console.warn('[Updater] GitHub API rate-limit aşıldı (HTTP 403).');
          return;
        }
        const release = JSON.parse(data);
        const latestVersion = release.tag_name || '';
        const releaseUrl = release.html_url || `https://github.com/${GITHUB_REPO}/releases`;
        // Unicode güvenli slice (emoji/Türkçe karakter kesmez)
        const releaseNotes = Array.from(release.body || '').slice(0, 400).join('');

        if (!latestVersion) {
          if (!silent) console.log('[Updater] GitHub API yanıtı boş.');
          return;
        }

        console.log(`[Updater] Mevcut: ${currentVersion} | En son: ${latestVersion}`);

        if (semverGt(latestVersion, currentVersion)) {
          console.log(`[Updater] Yeni sürüm mevcut: ${latestVersion}`);
          safeSend(mainWindow, 'update-available', {
            current: currentVersion,
            latest: latestVersion,
            url: releaseUrl,
            notes: releaseNotes,
          });
        } else if (!silent) {
          // Naming fix: ayrı event (update-available'da upToDate: true yerine)
          safeSend(mainWindow, 'update-not-available', { current: currentVersion });
        }
      } catch (e) {
        console.warn('[Updater] Yanıt parse hatası:', e.message);
      }
    });
  });

  req.on('error', (e) => console.warn('[Updater] Ağ hatası:', e.message));
  req.on('timeout', () => { req.destroy(); console.warn('[Updater] Timeout'); });
}

// ─────────────────────────────────────────────────────────────────────────────
// SHA-256 Doğrulama
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Dosyanın SHA-256 hash'ini hesaplar.
 * @param {string} filePath
 * @returns {Promise<string>}  lowercase hex
 */
function computeFileHash(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', chunk => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}


async function extractExpectedHash(assets, assetName, releaseBody) {
  // 1) İmzalı manifest (daha güvenli — DNSSEC korumalı CDN vb.)
  if (UPDATE_MANIFEST_URL) {
    try {
      const manifest = await _fetchJson(UPDATE_MANIFEST_URL);
      const entry = manifest[assetName] || manifest[assetName.replace(/^v/, '')];
      if (entry && /^[0-9a-fA-F]{64}$/.test(entry)) {
        console.log('[Updater] Hash imzalı manifest\'ten alındı.');
        return entry.toLowerCase();
      }
    } catch (e) {
      console.warn('[Updater] İmzalı manifest alınamadı:', e.message);
    }
  }

  // 2) .sha256 asset
  const shaAsset = assets.find(
    (a) => a.name === `${assetName}.sha256` || a.name === `${assetName}.SHA256`
  );
  if (shaAsset) {
    let tempPath = null;
    try {
      tempPath = path.join(app.getPath('temp'), `${assetName}.sha256.tmp`);
      await downloadWithRedirects(shaAsset.browser_download_url, tempPath, () => { });
      const raw = fs.readFileSync(tempPath, 'utf8');
      // BOM temizliği + ilk token
      const content = raw.replace(/^\uFEFF/, '').trim().split(/\s+/)[0];
      if (/^[0-9a-fA-F]{64}$/.test(content)) {
        return content.toLowerCase();
      }
    } catch (e) {
      console.warn('[Updater] .sha256 asset indirilemedi:', e.message);
    } finally {
      // Her durumda temp dosyayı sil
      if (tempPath) {
        try { fs.unlinkSync(tempPath); } catch { /* yoksay */ }
      }
    }
  }

  // 3) Release body
  if (releaseBody) {
    const match = releaseBody.match(/sha256[:\s]+([0-9a-fA-F]{64})/i);
    if (match) return match[1].toLowerCase();
  }

  console.warn('[Updater] SHA-256 hash bulunamadı — doğrulama atlanacak.');
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Yedekleme
// ─────────────────────────────────────────────────────────────────────────────

/**
 * macOS'ta .app bundle kökünü döner; diğer platformlarda execPath.
 */
function _getBackupSource() {
  if (process.platform === 'darwin') {
    // /Applications/Glio.app/Contents/MacOS/Glio → /Applications/Glio.app
    const contentsDir = path.dirname(path.dirname(process.execPath)); // Contents/
    const bundleDir = path.dirname(contentsDir);                   // .app/
    if (bundleDir.endsWith('.app')) return bundleDir;
  }
  return process.execPath;
}

/**
 * Mevcut binary / .app bundle'ı userData/backup/ dizinine yedekler.
 * @returns {string|null}  yedek yolu; hata olursa null
 */
function backupCurrentBinary() {
  try {
    const src = _getBackupSource();
    const backupDir = path.join(app.getPath('userData'), 'backup');
    fs.mkdirSync(backupDir, { recursive: true });

    const ext = path.extname(src) || '';
    const backupName = `glio-cartography-backup-${app.getVersion()}${ext || '-bundle'}`;
    const backupPath = path.join(backupDir, backupName);

    if (fs.existsSync(backupPath)) {
      console.log(`[Updater] Yedek zaten mevcut: ${backupPath}`);
      return backupPath;
    }

    const stat = fs.statSync(src);
    if (stat.isDirectory()) {
      // macOS .app bundle — Node 16.7+ fs.cpSync
      if (typeof fs.cpSync === 'function') {
        fs.cpSync(src, backupPath, { recursive: true });
      } else {
        // Eski Node — sync execFile mümkün değil, execFileSync kullan
        const { execFileSync } = require('child_process');
        execFileSync('cp', ['-Rf', src, backupPath], { timeout: 60000 });
      }
    } else {
      fs.copyFileSync(src, backupPath);
    }

    console.log(`[Updater] Yedek oluşturuldu: ${backupPath}`);
    return backupPath;
  } catch (e) {
    console.warn('[Updater] Yedekleme başarısız:', e.message);
    return null;
  }
}

/**
 * Harici helper script aracılığıyla rollback yapar.
 * Uygulama kapatıldıktan sonra script çalışır.
 *
 * Güvenlik notu: execPath üzerine çalışırken kopyalama SIP'i ihlal edebilir.
 * Rollback sadece uygulama kapalıyken güvenlidir; bu nedenle script tabanlı.
 *
 * @param {string} backupPath
 * @returns {boolean}
 */
function rollback(backupPath) {
  if (!backupPath || !fs.existsSync(backupPath)) {
    console.error('[Updater] Rollback yedek dosyası bulunamadı:', backupPath);
    return false;
  }
  try {
    const dest = _getBackupSource();

    if (process.platform === 'win32') {
      // Windows: batch script — uygulama kapandıktan sonra çalışır
      const scriptPath = path.join(app.getPath('temp'), 'glio_rollback.bat');
      fs.writeFileSync(scriptPath,
        `@echo off\r\n` +
        `timeout /t 2 /nobreak >nul\r\n` +
        `copy /y "${backupPath}" "${dest}"\r\n` +
        `start "" "${dest}"\r\n`
      );
      spawn('cmd.exe', ['/c', scriptPath], { detached: true, stdio: 'ignore' }).unref();

    } else {
      // macOS / Linux: bash one-liner
      const scriptPath = path.join(app.getPath('temp'), 'glio_rollback.sh');
      const isBundleBackup = fs.statSync(backupPath).isDirectory();
      const cpCmd = isBundleBackup
        ? `cp -Rf "${backupPath}" "${dest}"`
        : `cp -f "${backupPath}" "${dest}" && chmod +x "${dest}"`;

      fs.writeFileSync(scriptPath,
        `#!/bin/bash\n` +
        `sleep 2\n` +
        `${cpCmd}\n` +
        `open "${dest}" 2>/dev/null || "${dest}" &\n`
      );
      fs.chmodSync(scriptPath, '755');
      spawn('/bin/bash', [scriptPath], { detached: true, stdio: 'ignore' }).unref();
    }

    console.log('[Updater] Rollback scripti zamanlandı — uygulama kapanıyor.');
    return true;
  } catch (e) {
    console.error('[Updater] Rollback scripti oluşturulamadı:', e.message);
    return false;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Platform Kurulum Akışları — Async, execFile ile (UI thread bloklanmaz)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * macOS: DMG'yi hdiutil ile asenkron mount eder, .app'i Applications'a kopyalar,
 * ayırır. execSync yerine execFileAsync kullanılır — UI thread bloklanmaz.
 *
 * Güvenlik: Tüm argümanlar dizi olarak geçirilir (command injection yok).
 *
 * @param {string} dmgPath
 * @param {string} [appName]
 */
async function installDmgMacOS(dmgPath, appName = 'Glio-Cartography.app') {
  const mountPoint = path.join(app.getPath('temp'), 'glio_update_mount');
  let mounted = false;

  const detachSafe = async () => {
    if (!mounted) return;
    try {
      await execFileAsync('hdiutil', ['detach', mountPoint, '-quiet', '-force'],
        { timeout: 10000 });
    } catch { /* yoksay */ }
    mounted = false;
  };

  try {
    // Mount — argümanlar dizi, injection yok
    console.log(`[Updater] macOS DMG mount ediliyor: ${dmgPath}`);
    await execFileAsync('hdiutil',
      ['attach', dmgPath, '-mountpoint', mountPoint, '-nobrowse', '-quiet'],
      { timeout: 30000 });
    mounted = true;

    // .app bul
    const appSrc = path.join(mountPoint, appName);
    const appsDest = `/Applications/${appName}`;
    // Temp/backup paths live next to appsDest (same volume) so the final
    // step is a fast, atomic rename rather than a cross-volume copy.
    const tempDest = `${appsDest}.new`;
    const oldDest = `${appsDest}.old`;

    if (!fs.existsSync(appSrc)) {
      console.warn(`[Updater] DMG içinde ${appName} bulunamadı — kullanıcıya bırakılıyor.`);
      await detachSafe();
      await shell.openPath(dmgPath);
      return;
    }

    // Yeni bundle'ı Applications altında geçici bir konuma kopyala.
    // Doğrudan appsDest üzerine yazmak, uygulamanın kendi çalışan binary'sinin
    // üzerine yazmak anlamına gelir ("Text file busy" riski) — bunun yerine
    // installAppImageLinux'taki gibi atomic rename ile takas yapılır.
    try {
      try { await execFileAsync('rm', ['-rf', tempDest], { timeout: 30000 }); } catch { /* yoksay */ }
      await execFileAsync('cp', ['-Rf', appSrc, tempDest], { timeout: 60000 });
      console.log('[Updater] macOS: Yeni sürüm geçici konuma kopyalandı.');
    } catch (cpErr) {
      console.warn('[Updater] macOS: cp başarısız (sudo gerekebilir) — DMG açılıyor.', cpErr.message);
      try { await execFileAsync('rm', ['-rf', tempDest], { timeout: 30000 }); } catch { /* yoksay */ }
      await detachSafe();
      await shell.openPath(dmgPath);
      return;
    }

    // Atomic takas: mevcut bundle'ı kenara al, yenisini yerine koy.
    try {
      try { fs.rmSync(oldDest, { recursive: true, force: true }); } catch { /* yoksay */ }
      if (fs.existsSync(appsDest)) {
        fs.renameSync(appsDest, oldDest);
      }
      fs.renameSync(tempDest, appsDest);
      try { fs.rmSync(oldDest, { recursive: true, force: true }); } catch { /* yoksay */ }
      console.log('[Updater] macOS: Applications klasörüne atomic olarak takas edildi.');
    } catch (swapErr) {
      // Takas başarısız — eski bundle'ı geri getirmeyi dene
      try {
        if (!fs.existsSync(appsDest) && fs.existsSync(oldDest)) {
          fs.renameSync(oldDest, appsDest);
        }
      } catch { /* yoksay */ }
      try { fs.rmSync(tempDest, { recursive: true, force: true }); } catch { /* yoksay */ }
      console.warn('[Updater] macOS: Atomic takas başarısız (sudo gerekebilir) — DMG açılıyor.', swapErr.message);
      await detachSafe();
      await shell.openPath(dmgPath);
      return;
    }

    // Ayır
    await detachSafe();
    console.log('[Updater] macOS: DMG ayırıldı. Uygulama kapatılıyor.');
    app.quit();

  } catch (e) {
    await detachSafe();
    throw e;
  }
}

/**
 * Linux: AppImage'ı yeni bir dosyaya kaydeder, mevcut binary'yi
 * .old olarak adlandırır, yeni binary'yi yerine geçirir, sonra yeniden başlatır.
 * (Çalışan binary üzerine doğrudan yazmak yerine rename kullanılır.)
 *
 * @param {string} appImagePath  indirilen AppImage
 * @param {string|null} backupPath  rollback yolu
 */
function installAppImageLinux(appImagePath, backupPath) {
  if (!backupPath) {
    throw new Error('Yedekleme başarısız oldu — güvenli kurulum yapılamıyor.');
  }

  const currentExe = process.execPath;
  const oldPath = `${currentExe}.old`;

  try {
    fs.chmodSync(appImagePath, '755');

    // Mevcut binary'yi yeniden adlandır (rename atomic — overwrite değil)
    try { fs.unlinkSync(oldPath); } catch { /* yoksay */ }
    fs.renameSync(currentExe, oldPath);

    // Yeni binary'yi yerine koy
    fs.copyFileSync(appImagePath, currentExe);
    fs.chmodSync(currentExe, '755');

    console.log('[Updater] Linux AppImage kuruldu. Yeniden başlatılıyor...');
    // Kısa bekleme — yeni process başlamaya hazır olsun
    setTimeout(() => {
      spawn(currentExe, [], { detached: true, stdio: 'ignore' }).unref();
      app.quit();
    }, 500);

  } catch (e) {
    // Başarısız olursa .old'u geri taşımayı dene
    if (fs.existsSync(oldPath)) {
      try { fs.renameSync(oldPath, currentExe); } catch { /* yoksay */ }
    }
    throw new Error(`Linux AppImage kurulum hatası: ${e.message}`);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Ana İndirme + Kurulum Fonksiyonu
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Verilen sürümü indirir, SHA-256 doğrular, yedekler ve kurar.
 * Hata durumunda rollback() çağrılır ve reject ile bildirilir.
 *
 * @param {BrowserWindow} mainWindow
 * @param {string}        version
 * @returns {Promise<void>}
 */
function startUpdateDownload(mainWindow, version) {
  return new Promise((resolve, reject) => {
    if (!version) {
      return reject(new Error('Sürüm bilgisi belirtilmedi.'));
    }

    const tag = version.startsWith('v') ? version : `v${version}`;
    const options = _buildApiOptions(`/repos/${GITHUB_REPO}/releases/tags/${tag}`);

    const req = https.get(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', async () => {
        // Tüm async işlem tek bir try/catch içinde → hata yönetimi tutarlı
        try {
          if (res.statusCode === 403) throw new Error('GitHub API rate-limit aşıldı.');
          if (res.statusCode !== 200)
            throw new Error(`GitHub Release API hatası: HTTP ${res.statusCode}`);

          const release = JSON.parse(data);
          const assets = release.assets || [];
          const releaseBody = release.body || '';

          const extension = _getPlatformExtension();
          const asset = assets.find(a => a.name.endsWith(extension));
          if (!asset) {
            throw new Error(`Bu sürüm için uygun kurulum dosyası (${extension}) bulunamadı.`);
          }

          const url = asset.browser_download_url;
          const savePath = path.join(app.getPath('temp'), asset.name);

          // Hash'i erken al (API response'u elden bırakmadan)
          const expectedHash = await extractExpectedHash(assets, asset.name, releaseBody);

          // Eski indirme varsa sil
          try { if (fs.existsSync(savePath)) fs.unlinkSync(savePath); } catch { /* yoksay */ }

          safeSend(mainWindow, 'update-download-progress', {
            status: 'downloading', percent: 0, received: '0.0', total: '0.0', speed: '0.0',
          });

          // ── İndirme ──────────────────────────────────────────────────────────
          const startTime = Date.now();
          console.log(`[Updater] İndirme başlıyor: ${asset.name}`);

          try {
            await downloadWithRedirects(url, savePath, (received, total) => {
              const elapsed = Math.max(0.01, (Date.now() - startTime) / 1000);
              const speed = (received / 1024 / 1024) / elapsed;
              const percent = total > 0 ? Math.round((received / total) * 100) : 0;
              safeSend(mainWindow, 'update-download-progress', {
                status: 'downloading', percent,
                received: (received / 1024 / 1024).toFixed(1),
                total: (total / 1024 / 1024).toFixed(1),
                speed: speed.toFixed(1),
              });
            });
          } catch (dlErr) {
            // İndirme başarısız → temp temizle
            try { fs.unlinkSync(savePath); } catch { /* yoksay */ }
            throw dlErr;
          }

          // ── SHA-256 Doğrulama ─────────────────────────────────────────────
          if (expectedHash) {
            safeSend(mainWindow, 'update-download-progress', { status: 'verifying', percent: 100 });
            const actualHash = await computeFileHash(savePath);
            console.log(`[Updater] Beklenen: ${expectedHash}`);
            console.log(`[Updater] Hesaplanan: ${actualHash}`);
            if (actualHash !== expectedHash) {
              try { fs.unlinkSync(savePath); } catch { /* yoksay */ }
              throw new Error(
                `SHA-256 doğrulama başarısız!\n` +
                `Beklenen  : ${expectedHash}\n` +
                `Hesaplanan: ${actualHash}\n` +
                `İndirilen dosya silindi — lütfen tekrar deneyin.`
              );
            }
            console.log('[Updater] SHA-256 doğrulama başarılı.');
          }

          // ── Yedekleme ─────────────────────────────────────────────────────
          const backupPath = backupCurrentBinary();
          // Linux kurulumu için backup zorunlu — kontrol installAppImageLinux'ta

          safeSend(mainWindow, 'update-download-progress', { status: 'installing', percent: 100 });

          // ── Platform Kurulumu ─────────────────────────────────────────────
          try {
            if (process.platform === 'win32') {
              // Windows: Installer türüne göre argüman belirsizliği var.
              // Argümansız çalıştırılıyor — GUI akışına bırakılıyor.
              // NSIS gerekiyorsa env GLIO_WIN_INSTALLER_ARGS="['/S']" kullan.
              const extraArgs = process.env.GLIO_WIN_INSTALLER_ARGS
                ? JSON.parse(process.env.GLIO_WIN_INSTALLER_ARGS)
                : [];
              spawn(savePath, extraArgs, { detached: true, stdio: 'ignore' }).unref();
              safeSend(mainWindow, 'update-download-progress', { status: 'completed', percent: 100 });
              resolve();
              app.quit();

            } else if (process.platform === 'darwin') {
              await installDmgMacOS(savePath);
              safeSend(mainWindow, 'update-download-progress', { status: 'completed', percent: 100 });
              resolve();
              // installDmgMacOS içinde app.quit() çağrılıyor

            } else if (process.platform === 'linux') {
              installAppImageLinux(savePath, backupPath);
              safeSend(mainWindow, 'update-download-progress', { status: 'completed', percent: 100 });
              resolve();
              // installAppImageLinux içinde setTimeout ile app.quit() çağrılıyor

            } else {
              throw new Error(`Desteklenmeyen platform: ${process.platform}`);
            }

          } catch (installErr) {
            // Kurulum hatası → rollback
            console.error('[Updater] Kurulum hatası — rollback deneniyor:', installErr.message);
            if (backupPath) rollback(backupPath);
            safeSend(mainWindow, 'update-download-progress', {
              status: 'failed',
              error: `Kurulum hatası: ${installErr.message}`,
            });
            return reject(installErr);
          }

        } catch (e) {
          console.error('[Updater] İşlem hatası:', e.message);
          safeSend(mainWindow, 'update-download-progress', { status: 'failed', error: e.message });
          return reject(e);
        }
      });
    });

    req.on('error', (e) => {
      console.error('[Updater] Ağ bağlantı hatası:', e);
      safeSend(mainWindow, 'update-download-progress', { status: 'failed', error: e.message });
      reject(e);
    });

    req.on('timeout', () => {
      req.destroy();
      const err = new Error('GitHub API bağlantı zaman aşımı.');
      safeSend(mainWindow, 'update-download-progress', { status: 'failed', error: err.message });
      reject(err);
    });
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Özel Yardımcılar
// ─────────────────────────────────────────────────────────────────────────────

/** GitHub API istek ayarlarını döner (ETag + rate-limit başlıkları dahil). */
function _buildApiOptions(apiPath) {
  const headers = {
    'User-Agent': 'Glio-Cartography-Updater',
    'Accept': 'application/vnd.github.v3+json',
  };
  // Opsiyonel PAT token (rate-limit bypass)
  if (process.env.GLIO_GITHUB_TOKEN) {
    headers['Authorization'] = `token ${process.env.GLIO_GITHUB_TOKEN}`;
  }
  return { hostname: 'api.github.com', path: apiPath, headers, timeout: 10000 };
}

/** Platform bağımlı installer uzantısını döner. */
function _getPlatformExtension() {
  if (process.platform === 'win32') return '.exe';
  if (process.platform === 'darwin') return '.dmg';
  if (process.platform === 'linux') return '.AppImage';
  throw new Error(`Desteklenmeyen platform: ${process.platform}`);
}

/** JSON endpoint'i fetch eder. */
function _fetchJson(url) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : require('http');
    const req = mod.get(url, { timeout: 10000 }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Manifest fetch timeout')); });
  });
}

// ─────────────────────────────────────────────────────────────────────────────
module.exports = {
  checkForUpdates,
  semverGt,
  GITHUB_REPO,
  startUpdateDownload,
  computeFileHash,
  extractExpectedHash,
  backupCurrentBinary,
  rollback,
};
