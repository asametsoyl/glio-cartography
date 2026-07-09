// =============================================================
// GLIO-CARTOGRAPHY — License System (RSA-SHA256) v2
// =============================================================
// 3 Doğrulama Modu:
//   1. Lokal cache (önceki online aktivasyondan kaydedilen RSA token)
//   2. portable.gcart dosyası (USB/CD kurulumlar için)
//   3. Online aktivasyon (sunucuya machine_id + lisans anahtarı gönderilir)
//
// Payload formatı (offline token): machineId:expiryTs:GLIO-CARTOGRAPHY-v1
// Portable payload: PORTABLE:{licenseId}:{expHex}:{instB64}:GLIO-CARTOGRAPHY-v1
// =============================================================
'use strict';

const crypto = require('crypto');
const path = require('path');
const fs = require('fs');
const { getMachineId } = require('./machine-id');

// Public key — only used to VERIFY signatures, never to create them.
const PUBLIC_KEY = `
-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAoDcLlvRHWfQascN/z4V9
h3chyjUkRwV5Rtwv/Ek84nL2Kh9GDmzfYihwHUsBNw5eJ75ZD+BXsxqdKsaw6Wgy
jNhgcH0sdviFt+oN/eQLRyGGKNYhpZM3bzTdzb1hj42BPrAgC4iK7H0kO4qDl/+M
fpjtJusd1zOL5LUOiq8Sshz97PlLrh67+CbI9eAgiBAj4cXdY2l0zGfWbwYhNPSZ
bCgsEA2nIwrHv4PzQxfq/+beiv1qFeJOjYMGGsDZNT5Lt/OHgsvN4T9ks7SNXzAa
MbDH4vidGMCEdq1wXbxkJAjTY1zHeYgVGe8KOKRMMvVzaEVf5767DAlKkXqPG8IG
795k6il0UMdICQ/imse4vjj6GZb/gab3hY/i4gaPt6P+PaUZJMvUs2JJk/O/B+6w
GaJPy+9vM2WKJaD62VRzl6sBX1mE/wSlo4V6qjeNuQMZjk+G3q9tyIjNhgqse48D
UWukySWgAiCr2CWQDo+tuGJrTlEoA3dSmSMdjT2g+YJRSzN5lDsE5SrGHGU/6nH6
DqBPX3POOznTlZspPtjlLer/7B/+rE7fl/h/M1FCe+7ObAq8Q9QsvAZ89zXiZM8j
/sgqb4V4+lnVB0accLKYZxju6NuVyVEEic91OT9M/gTE0W43CX7CR8D1ZnpJtyBj
FGlLbe3tDoMNvhxZJGdGKfECAwEAAQ==
-----END PUBLIC KEY-----
`;

const CACHE_SECRET = 'GLIO-CARTOGRAPHY-SECURE-CACHE-SALT-2026';
const PORTABLE_FILENAME = 'portable.gcart';

let _store = null;

function setStore(store) {
  _store = store;
}

// ── Yardımcı: RSA imzası doğrula ────────────────────────────────────────
function rsaVerify(payload, sigStr) {
  try {
    let sigBuffer;
    const hexBuf = Buffer.from(sigStr, 'hex');
    if (hexBuf.length * 2 === sigStr.length && /^[0-9a-fA-F]+$/.test(sigStr)) {
      sigBuffer = hexBuf;
    } else {
      sigBuffer = Buffer.from(sigStr, 'base64');
    }
    const verifier = crypto.createVerify('RSA-SHA256');
    verifier.update(payload);
    return verifier.verify(PUBLIC_KEY, sigBuffer);
  } catch (e) {
    console.error('[rsaVerify] Error:', e.message);
    return false;
  }
}

// ── MOD 1: Lokal cache'den doğrulama ────────────────────────────────────
// Önceki online aktivasyondan gelen imzalı token yerel dosyaya kaydedilmiş.
function validateFromCache() {
  const saved = _store ? _store.get('license') : null;
  if (!saved || !saved.token) return null;

  // Basit expiry kontrolü
  if (saved.expiryDate && new Date(saved.expiryDate) <= new Date()) {
    return { valid: false, reason: 'Lisans süresi dolmuş' };
  }

  // Token formatı: GCARTO-{EXP_HEX}-{SIG}
  const parts = saved.token.split('-');
  if (parts.length < 3 || parts[0] !== 'GCARTO') return null;

  const expiryTs = parseInt(parts[1], 16);
  if (isNaN(expiryTs) || new Date(expiryTs * 1000) <= new Date()) {
    return { valid: false, reason: 'Lisans süresi dolmuş' };
  }

  const machineId = getMachineId();
  const sigStr = parts.slice(2).join('');
  const payload = `${machineId}:${expiryTs}:GLIO-CARTOGRAPHY-v1`;

  if (rsaVerify(payload, sigStr)) {
    return {
      valid: true,
      expiryDate: new Date(expiryTs * 1000).toISOString().split('T')[0],
      mode: 'cached',
      institution: saved.institution || null,
    };
  }
  return null; // Cache geçersiz, diğer modlara düş
}

// ── MOD 2: portable.gcart dosyasından doğrulama ──────────────────────────
// Uygulama klasöründeki portable.gcart dosyasını ara ve RSA imzasını doğrula.
function validatePortableLicense(appPath) {
  const candidates = [
    path.join(appPath, PORTABLE_FILENAME),                    // <app klasörü>/portable.gcart
    path.join(process.execPath, '..', PORTABLE_FILENAME),    // executable yanındaki klasör
    path.join(__dirname, '..', '..', PORTABLE_FILENAME),     // proje kökü
  ];

  let portableData = null;
  let foundPath = null;

  for (const candidate of candidates) {
    try {
      if (fs.existsSync(candidate)) {
        const raw = fs.readFileSync(candidate, 'utf8');
        portableData = JSON.parse(raw);
        foundPath = candidate;
        break;
      }
    } catch (e) {
      console.warn('[Portable] Failed to read candidate:', candidate, e.message);
    }
  }

  if (!portableData) return null;

  // Yapı kontrolü
  if (
    portableData.version !== 1 ||
    portableData.type !== 'PORTABLE' ||
    !portableData.expiry_hex ||
    !portableData.sig ||
    !portableData.institution ||
    !portableData.license_id
  ) {
    console.warn('[Portable] Invalid structure in', foundPath);
    return null;
  }

  // Süre kontrolü
  const expiryTs = parseInt(portableData.expiry_hex, 16);
  if (isNaN(expiryTs) || new Date(expiryTs * 1000) <= new Date()) {
    console.warn('[Portable] License expired:', new Date(expiryTs * 1000).toISOString());
    return { valid: false, reason: `Taşınabilir lisans süresi dolmuş (${portableData.institution})` };
  }

  // RSA imza doğrulaması
  const instB64 = Buffer.from(portableData.institution, 'utf8').toString('base64');
  const payload = `PORTABLE:${portableData.license_id}:${portableData.expiry_hex}:${instB64}:GLIO-CARTOGRAPHY-v1`;

  if (!rsaVerify(payload, portableData.sig)) {
    console.error('[Portable] RSA signature invalid for', foundPath);
    return null;
  }

  const expiryDate = new Date(expiryTs * 1000).toISOString().split('T')[0];
  console.log('[Portable] Valid portable license found:', portableData.institution, 'expires:', expiryDate);

  // Portable lisansı cache'e yaz (sonraki açılışlarda daha hızlı)
  if (_store) {
    _store.set('portable_license', {
      institution: portableData.institution,
      expiryDate,
      license_id: portableData.license_id,
    });
  }

  return {
    valid: true,
    expiryDate,
    mode: 'portable',
    institution: portableData.institution,
  };
}

// ── Ana Doğrulama Fonksiyonu ─────────────────────────────────────────────
// Öncelik: cache → portable → null (lisans ekranı göster)
function validateLicense(appPath) {
  // 1. Cache
  const cached = validateFromCache();
  if (cached) return cached;

  // 2. portable.gcart
  const portable = validatePortableLicense(appPath || process.cwd());
  if (portable) return portable;

  // 3. Hiçbiri geçerli değil → lisans ekranı
  return { valid: false, reason: 'Lisans bulunamadı.' };
}

// ── Online Token Kaydetme ─────────────────────────────────────────────────
// Sunucudan gelen offline_token ve bilgileri yerel store'a yaz.
function saveOnlineActivation({ offlineToken, expiryDate, institution }) {
  if (!_store) return false;
  _store.set('license', {
    token: offlineToken,
    expiryDate,
    institution: institution || null,
    activatedAt: new Date().toISOString(),
  });
  return true;
}

module.exports = { validateLicense, saveOnlineActivation, setStore, PUBLIC_KEY };
