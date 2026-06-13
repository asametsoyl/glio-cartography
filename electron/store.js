// =============================================================
// GLIO-CARTOGRAPHY — Robust JSON Store
// =============================================================
// Fix: get/set/delete now read from in-memory cache only.
// load() is called once in the constructor, not on every access.
// =============================================================
'use strict';

const fs = require('fs');
const path = require('path');
const { app } = require('electron');

class RobustJSONStore {
  constructor() {
    const userData = app.getPath('userData');
    this.filePath = path.join(userData, 'glio-cartography-config.json');
    this.data = {};
    this.load(); // Single disk read at startup
  }

  _readWithRetry(filePath) {
    const maxRetries = 10;
    for (let i = 0; i < maxRetries; i++) {
      try {
        return fs.readFileSync(filePath, 'utf8');
      } catch (e) {
        const isEintr =
          e.code === 'EINTR' ||
          e.errno === 'EINTR' ||
          (e.message && e.message.includes('EINTR'));
        if (isEintr && i < maxRetries - 1) {
          console.warn(
            `[RobustJSONStore] Read EINTR, retrying (${i + 1}/${maxRetries}): ${filePath}`
          );
          const start = Date.now();
          while (Date.now() - start < 20) {}
          continue;
        }
        throw e;
      }
    }
  }

  _writeWithRetry(filePath, data) {
    const maxRetries = 10;
    for (let i = 0; i < maxRetries; i++) {
      try {
        return fs.writeFileSync(filePath, data, 'utf8');
      } catch (e) {
        const isEintr =
          e.code === 'EINTR' ||
          e.errno === 'EINTR' ||
          (e.message && e.message.includes('EINTR'));
        if (isEintr && i < maxRetries - 1) {
          console.warn(
            `[RobustJSONStore] Write EINTR, retrying (${i + 1}/${maxRetries}): ${filePath}`
          );
          const start = Date.now();
          while (Date.now() - start < 20) {}
          continue;
        }
        throw e;
      }
    }
  }

  load() {
    try {
      if (fs.existsSync(this.filePath)) {
        const content = this._readWithRetry(this.filePath);
        this.data = JSON.parse(content || '{}');
      }
    } catch (e) {
      console.error('[RobustJSONStore] Failed to load config:', e);
      this.data = {};
    }
  }

  save() {
    try {
      const content = JSON.stringify(this.data, null, 2);
      const tmp = this.filePath + '.tmp';

      this._writeWithRetry(tmp, content);

      // Atomic rename
      fs.renameSync(tmp, this.filePath);
    } catch (e) {
      console.error('[RobustJSONStore] Failed to save config:', e);
      // Temizle tmp dosyası
      try { fs.unlinkSync(this.filePath + '.tmp'); } catch {}
    }
  }

  // All three accessors read from memory — no disk I/O
  get(key, fallback) {
    return this.data[key] !== undefined ? this.data[key] : fallback;
  }

  set(key, value) {
    this.data[key] = value;
    this.save();
  }

  delete(key) {
    delete this.data[key];
    this.save();
  }
}

async function initStore() {
  return new RobustJSONStore();
}

module.exports = { RobustJSONStore, initStore };
