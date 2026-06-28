/**
 * Glio-Cartography — i18n Singleton Motoru
 * FAZ C — renderer/i18n.js
 *
 * Kullanım:
 *   import { i18n } from './i18n.js';
 *   await i18n.init();            // Uygulama başlangıcında çağrılır
 *   i18n.t('pipeline.start')      // "Analizi Başlat" veya "Start Analysis"
 *   i18n.applyToDOM()             // data-i18n attribute'lü tüm elementleri günceller
 *   await i18n.setLang('en')      // Dil değiştir + DOM güncelle
 *
 * HTML:
 *   <span data-i18n="pipeline.start"></span>
 *   <input data-i18n-placeholder="pipeline.patient_id" />
 *   <button data-i18n-title="common.save"></button>
 */

let SUPPORTED_LANGS = ['tr', 'en'];
let DEFAULT_LANG    = 'tr';
let FALLBACK_LANG   = 'tr';

/** @type {Record<string, Record<string, any>>} */
const _cache = {};

/** @type {string} */
let _lang = DEFAULT_LANG;

/** @type {boolean} */
let _initialized = false;

/** @type {boolean} */
let _locked = false;  // aktif analiz sırasında dil değişimine kilit

// ─────────────────────────────────────────────────────────────────────────────
// Yardımcı: HTML-escape
// ─────────────────────────────────────────────────────────────────────────────
function _escapeHTML(str) {
  if (str == null) return '';
  const s = String(str);
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// ─────────────────────────────────────────────────────────────────────────────
// Yardımcı: düz anahtar → iç içe nesne değeri (Prototype Pollution Korumalı)
// ─────────────────────────────────────────────────────────────────────────────
function _resolveDotPath(obj, dotPath) {
  if (!dotPath) return undefined;
  const parts = dotPath.split('.');
  let cur = obj;
  for (const part of parts) {
    if (cur == null || typeof cur !== 'object') return undefined;
    // Prototype pollution guard
    if (part === '__proto__' || part === 'constructor' || part === 'prototype') {
      return undefined;
    }
    if (!Object.prototype.hasOwnProperty.call(cur, part)) {
      return undefined;
    }
    cur = cur[part];
  }
  return cur;
}

// ─────────────────────────────────────────────────────────────────────────────
// Locale dosyasını yükle (önbellekli, IPC öncelikli, 5sn timeout'lu fetch fallback)
// ─────────────────────────────────────────────────────────────────────────────
async function _loadLocale(lang) {
  if (_cache[lang]) return _cache[lang];
  try {
    const api = window.glioAPI;
    
    // 1) Electron ortamı: IPC üzerinden oku
    if (api && api.getLocale) {
      const data = await api.getLocale(lang);
      if (data && Object.keys(data).length > 0) {
        _cache[lang] = data;
        return data;
      }
    }

    // 2) Web ortamı / Geliştirme modu fallback
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    const url = `./locales/${lang}.json`;
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(timeoutId);
    
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _cache[lang] = data;
    return data;
  } catch (e) {
    console.error(`[i18n] '${lang}' locale yüklenemedi:`, e.message);
    window.dispatchEvent(new CustomEvent('i18n:error', { detail: { lang, message: e.message } }));
    return {};
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Singleton API
// ─────────────────────────────────────────────────────────────────────────────
const i18n = {
  // Dil değişim dinleyicileri
  _listeners: new Set(),

  /**
   * i18n motorunu başlatır.
   * İlk çalışmada store'dan kaydedilmiş dili okur.
   * @param {object} [options]
   * @param {string[]} [options.supportedLangs]
   * @param {string} [options.defaultLang]
   * @param {string} [options.fallbackLang]
   * @param {string|null} [options.initialLang] — opsiyonel başlangıç dili (store'u override eder)
   */
  async init(options = {}) {
    if (_initialized) return;

    // Dinamik opsiyonlar
    if (Array.isArray(options.supportedLangs)) {
      SUPPORTED_LANGS = options.supportedLangs;
    }
    if (options.defaultLang && SUPPORTED_LANGS.includes(options.defaultLang)) {
      DEFAULT_LANG = options.defaultLang;
    }
    if (options.fallbackLang && SUPPORTED_LANGS.includes(options.fallbackLang)) {
      FALLBACK_LANG = options.fallbackLang;
    }

    const initialLang = options.initialLang || null;

    // 1) Electron main process'ten kaydedilmiş dili oku
    let storeLang = DEFAULT_LANG;
    try {
      const api = window.glioAPI;
      if (api && api.getLanguage) {
        storeLang = (await api.getLanguage()) || DEFAULT_LANG;
      }
    } catch {
      // Web ortamı veya test — localStorage'a düş
      try {
        storeLang = localStorage.getItem('appLanguage') || DEFAULT_LANG;
      } catch {
        storeLang = DEFAULT_LANG;
      }
    }

    // Öncelik: 1. storeLang, 2. initialLang, 3. DEFAULT_LANG
    _lang = SUPPORTED_LANGS.includes(storeLang)   ? storeLang
          : SUPPORTED_LANGS.includes(initialLang) ? initialLang
          : DEFAULT_LANG;

    // Hem aktif dili hem fallback'i önceden yükle
    await Promise.all([_loadLocale(_lang), _loadLocale(FALLBACK_LANG)]);
    _initialized = true;
    console.log(`[i18n] Başlatıldı — dil: ${_lang}`);
  },

  /**
   * Çeviri anahtarını çözer.
   * Anahtar bulunamazsa önce fallback dile, sonra anahtarın kendisine düşer.
   * Interpolasyon değişkenleri XSS'e karşı HTML-escape edilir.
   * @param {string} key       — nokta-yolu ('pipeline.start')
   * @param {Record<string,string>} [vars] — {{name}} şablonlarını değiştirir
   */
  t(key, vars = {}, visited = new Set()) {
    if (visited.has(key)) {
      console.warn(`[i18n] Döngüsel alias tespiti: "${key}"`);
      return key;
    }
    visited.add(key);

    let text = _resolveDotPath(_cache[_lang], key);

    // Fallback
    if (text == null && _lang !== FALLBACK_LANG) {
      text = _resolveDotPath(_cache[FALLBACK_LANG], key);
    }

    // Son çare: anahtarın kendisi
    if (text == null) {
      console.warn(`[i18n] Eksik anahtar: "${key}" (dil: ${_lang})`);
      return key;
    }

    // Alias çözme (ör. @common.cancel)
    if (typeof text === 'string' && text.startsWith('@')) {
      return this.t(text.slice(1), vars, visited);
    }

    // Değişken interpolasyonu: {{varName}} (XSS safe escaping)
    return String(text).replace(/\{\{(\w+)\}\}/g, (_, k) =>
      vars[k] != null ? _escapeHTML(vars[k]) : `{{${k}}}`
    );
  },

  /**
   * Mevcut dili döndürür.
   */
  get lang() { return _lang; },

  /**
   * Desteklenen dilleri döndürür.
   */
  get supportedLangs() { return SUPPORTED_LANGS; },

  /**
   * Dil değişim dinleyicisi ekle/kaldır
   */
  onLangChange(cb) {
    if (typeof cb === 'function') {
      this._listeners.add(cb);
    }
  },

  offLangChange(cb) {
    this._listeners.delete(cb);
  },

  /**
   * Aktif analiz sırasında dil değişimini kilitler/açar (Main process senkronize).
   */
  lock() {
    const api = window.glioAPI;
    if (api && api.setLanguageLocked) {
      api.setLanguageLocked(true).then((val) => { _locked = val; }).catch(() => { _locked = true; });
    } else {
      _locked = true;
    }
  },

  unlock() {
    const api = window.glioAPI;
    if (api && api.setLanguageLocked) {
      api.setLanguageLocked(false).then((val) => { _locked = val; }).catch(() => { _locked = false; });
    } else {
      _locked = false;
    }
  },

  async isLocked() {
    const api = window.glioAPI;
    if (api && api.isLanguageLocked) {
      try {
        _locked = await api.isLanguageLocked();
      } catch {
        // fail-safe fallback
      }
    }
    return _locked;
  },

  /**
   * Locale cache'ini boşaltır (bellek yönetimi için).
   * @param {string} lang — boşaltılacak dil kodu
   * @returns {boolean} — silindiyse true
   */
  unloadLocale(lang) {
    if (lang !== FALLBACK_LANG && lang !== _lang) {
      delete _cache[lang];
      return true;
    }
    return false;
  },

  /**
   * Dili değiştirir, locale'i yükler, DOM'u günceller.
   * @param {string} lang — 'tr' veya 'en'
   * @returns {Promise<boolean>} — başarılı ise true
   */
  async setLang(lang) {
    const locked = await this.isLocked();
    if (locked) {
      console.warn('[i18n] Aktif analiz sırasında dil değiştirilemez.');
      return false;
    }
    if (!SUPPORTED_LANGS.includes(lang)) {
      console.warn(`[i18n] Desteklenmeyen dil: ${lang}`);
      return false;
    }

    await _loadLocale(lang);
    _lang = lang;

    // Store'a kaydet
    try {
      const api = window.glioAPI;
      if (api && api.setLanguage) {
        const res = await api.setLanguage(lang);
        if (res && res.ok === false) {
          throw new Error(res.error || window.i18n.t('settings.save_failed'));
        }
      } else {
        localStorage.setItem('appLanguage', lang);
      }
    } catch (e) {
      console.error('[i18n] Dil ayarı kaydedilemedi:', e.message);
      window.dispatchEvent(new CustomEvent('i18n:error', { detail: { lang, message: `${window.i18n.t('settings.save_error')}: ${e.message}` } }));
    }

    this.applyToDOM();
    document.documentElement.lang = lang;

    // Dil değişim olayı yayınla
    this._listeners.forEach((cb) => {
      try { cb(lang); } catch (e) { console.error('[i18n] Listener hatası:', e.message); }
    });

    window.dispatchEvent(new CustomEvent('i18n:langchange', { detail: { lang } }));
    console.log(`[i18n] Dil değiştirildi: ${lang}`);
    return true;
  },

  /**
   * data-i18n attribute'lü tüm DOM elementlerini tek geçişte (optimizasyonlu) günceller.
   * @param {HTMLElement} [root=document.body]
   */
  applyToDOM(root = document.body) {
    if (!root) return;

    // 5 ayrı querySelectorAll yerine tek bir sorgu ile DOM tarama optimizasyonu
    const elements = root.querySelectorAll('[data-i18n], [data-i18n-placeholder], [data-i18n-title], [data-i18n-label]');
    elements.forEach((el) => {
      // 1) textContent
      if (el.hasAttribute('data-i18n')) {
        const key = el.getAttribute('data-i18n');
        if (key) el.textContent = this.t(key);
      }
      // 2) placeholder
      if (el.hasAttribute('data-i18n-placeholder')) {
        const key = el.getAttribute('data-i18n-placeholder');
        if (key) el.placeholder = this.t(key);
      }
      // 3) title (tooltip)
      if (el.hasAttribute('data-i18n-title')) {
        const key = el.getAttribute('data-i18n-title');
        if (key) el.title = this.t(key);
      }
      // 4) aria-label
      if (el.hasAttribute('data-i18n-label')) {
        const key = el.getAttribute('data-i18n-label');
        if (key) el.setAttribute('aria-label', this.t(key));
      }
    });
  },

  /**
   * Yüklü locale'nin anahtar sayısını döndürür (test amaçlı).
   */
  _keyCount(lang = _lang) {
    const locale = _cache[lang];
    if (!locale) return 0;
    const count = (obj, prefix = '') =>
      Object.entries(obj).reduce((acc, [k, v]) => {
        if (k.startsWith('_')) return acc;
        return typeof v === 'object' && v !== null
          ? acc + count(v, `${prefix}${k}.`)
          : acc + 1;
      }, 0);
    return count(locale);
  },
};

// Dev/test yardımları: non-enumerable ve prod-safety korumalı
Object.defineProperty(i18n, '_checkParity', {
  value: function() {
    if (typeof process !== 'undefined' && process.env && process.env.NODE_ENV === 'production') {
      return { missing_in_en: [], missing_in_tr: [] };
    }
    const flatten = (obj, prefix = '') =>
      Object.entries(obj).flatMap(([k, v]) => {
        if (k.startsWith('_')) return [];
        const full = prefix ? `${prefix}.${k}` : k;
        return typeof v === 'object' && v !== null ? flatten(v, full) : [full];
      });

    const trKeys = new Set(flatten(_cache['tr'] || {}));
    const enKeys = new Set(flatten(_cache['en'] || {}));

    return {
      missing_in_en: [...trKeys].filter((k) => !enKeys.has(k)),
      missing_in_tr: [...enKeys].filter((k) => !trKeys.has(k)),
    };
  },
  enumerable: false,
  writable: true,
  configurable: true
});

// İnit otomatik tetikle (ilk import'ta)
if (typeof window !== 'undefined') {
  // DOM hazır olduğunda başlat
  const _doInit = () => i18n.init().then(() => i18n.applyToDOM());
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _doInit);
  } else {
    _doInit();
  }

  // Global namespace kirliliğini önlemek için read-only / non-configurable Symbol ve window.i18n tanımı
  const globalKey = Symbol.for('app.i18n');
  Object.defineProperty(window, globalKey, {
    value: i18n,
    writable: false,
    configurable: false,
    enumerable: true
  });
  
  if (!window.i18n) {
    Object.defineProperty(window, 'i18n', {
      value: i18n,
      writable: false,
      configurable: false,
      enumerable: true
    });
  }
}

// CommonJS + ES module uyumlu export
if (typeof module !== 'undefined' && module.exports) {
  module.exports = i18n;
  module.exports.i18n = i18n;
} else if (typeof define === 'function' && define.amd) {
  define([], function() { return i18n; });
}
