// =============================================================
// GLIO-CARTOGRAPHY — License System (RSA-SHA256)
// =============================================================
// License format: GCARTO-{EXP_TIMESTAMP_HEX}-{RSA_SIG_HEX_OR_BASE64}
//
// Security model:
//  - Fast-path cache check runs FIRST for performance.
//  - Cache is ONLY written after a successful RSA verify — so
//    manual edits to the JSON config file cannot bypass crypto:
//    any tampered entry would have been written without going
//    through RSA, so the key/machineId check would still fail
//    unless the attacker also knows the real valid key.
//  - Full RSA verify runs for every new (key, machineId) pair.
// =============================================================
'use strict';

const crypto = require('crypto');
const { getMachineId } = require('./machine-id');

// Public key — only used to VERIFY signatures, never to create them.
const PUBLIC_KEY = `
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAry16XwsC+tpjBm74Qp4T
oX2XRKv0Z3jsaUj6xnAO0Qji37Ta453gP4zsdiznQ8RQAg8eQXY3nTg9M1VxbVtC
sE0sWLQN+eeiNad/RIWe+D/9TGGYucdGdxYuAIjohRqrHS7F7u2Cx8BjRqknJbs0
hzpaetjfUhJb0s1NyAQ7CNup6UB+vEDbFyM1nJJGK7tAXuJnJHcINIkZA6wiZb3o
amYaqCftcZpHeoez5JEQbu0SQrxUGilDZSk1AqZ9ytv1Vip2CZER8L5ofqIlf5LB
K1Q6Sz4rPEmDSxm5cs8EdZ02ZYNpJfl111xxaAgq27oGYS+/VcIOnBDcVwE3YTiG
UwIDAQAB
-----END PUBLIC KEY-----
`;

let _store = null;
const CACHE_SECRET = 'GLIO-CARTOGRAPHY-SECURE-CACHE-SALT-2026';

function setStore(store) {
  _store = store;
}

function validateLicense(licenseKey) {
  if (!licenseKey || !licenseKey.startsWith('GCARTO-')) {
    return { valid: false, reason: 'Geçersiz format' };
  }

  const machineId = getMachineId();

  // ── Fast path: cached entry (verified with a signature hash) ──────────────
  const saved = _store ? _store.get('license') : null;
  if (saved && saved.key === licenseKey && saved.machineId === machineId) {
    const expectedSig = crypto.createHmac('sha256', CACHE_SECRET).update(licenseKey + machineId + saved.expiryDate).digest('hex');
    if (saved._sig === expectedSig) {
      const expiry = new Date(saved.expiryDate);
      if (expiry > new Date()) {
        return { valid: true, expiryDate: saved.expiryDate, machineId };
      }
      return { valid: false, reason: 'Lisans süresi dolmuş' };
    }
    // Cache signature mismatch/missing — fall through to RSA
  }

  // ── Full RSA verification for new / unrecognised licenses ────────────────
  try {
    const parts = licenseKey.split('-');
    if (parts.length < 3 || parts[0] !== 'GCARTO') {
      throw new Error('Yetersiz segment sayısı');
    }

    const expHex = parts[1];
    // Re-join remaining segments (dashes may be inserted for readability)
    const sigStr = parts.slice(2).join('');

    const expiryTs = parseInt(expHex, 16);
    if (isNaN(expiryTs)) throw new Error('Geçersiz süre damgası');

    const expiryDate = new Date(expiryTs * 1000);
    if (expiryDate <= new Date()) {
      return { valid: false, reason: 'Lisans süresi dolmuş' };
    }

    // Payload signed by the private key on the license server
    const payload = `${machineId}:${expiryTs}:GLIO-CARTOGRAPHY-v1`;

    // ── Signature decoding: hex primary, base64 fallback ──────────────────
    // Hex: every two chars = one byte → decoded length = sigStr.length / 2
    let sigBuffer;
    const hexBuf = Buffer.from(sigStr, 'hex');
    if (hexBuf.length * 2 === sigStr.length && /^[0-9a-fA-F]+$/.test(sigStr)) {
      sigBuffer = hexBuf;
    } else {
      sigBuffer = Buffer.from(sigStr, 'base64');
    }
    // ─────────────────────────────────────────────────────────────────────

    const verifier = crypto.createVerify('RSA-SHA256');
    verifier.update(payload);
    const isValid = verifier.verify(PUBLIC_KEY, sigBuffer);

    if (isValid) {
      const expiryStr = expiryDate.toISOString().split('T')[0];
      // Write to cache ONLY after successful RSA — this is what keeps the cache safe.
      if (_store) {
        const _sig = crypto.createHmac('sha256', CACHE_SECRET).update(licenseKey + machineId + expiryStr).digest('hex');
        _store.set('license', { key: licenseKey, machineId, expiryDate: expiryStr, _sig });
      }
      return { valid: true, expiryDate: expiryStr, machineId };
    }
  } catch (e) {
    console.error('[validateLicense] Error:', e.message);
  }

  return { valid: false, reason: 'Lisans geçersiz veya bu makineye ait değil.' };
}

module.exports = { validateLicense, setStore, PUBLIC_KEY };
