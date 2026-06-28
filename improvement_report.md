# Glio-Cartography Desktop — Tüm Scriptler İçin İyileştirme Önerileri

> **Kapsam:** `electron/`, `renderer/`, `python_backend/` ve `build_app.sh`  
> **Kural:** Kod yazılmadı / değiştirilmedi — salt analiz ve öneri.

---

## 1. Genel Mimari ve Yapısal Öneriler

### 1.1 Config Dosyası Eksikliği (Kritik)
**Konum:** `python_backend/stages/stage1_preprocessing.py:312`, `stage2_deconvolution.py:448`  
**Sorun:** `configs/config.yaml` referans ediliyor ama proje kökünde `configs/` dizini yok. Spatial QC parametreleri, cell marker'lar ve dekonvolüsyon ayarları hardcoded fallback'e düşüyor.  
**Öneri:**
- Proje köküne `configs/config.yaml` (veya `config.json`) oluştur.
- Tüm hardcoded parametreleri (min_counts, min_genes, max_counts, cell cycle gen listesi, dekonvolüsyon method varsayılanları) buraya taşı.
- Stage'lerde `config_path` CLI argümanı ekle; yoksa sensible default'lar kullan.
- Config şeması için Pydantic `BaseModel` kullanarak validasyon ekle.

### 1.2 Modülerleştirme (Büyük Dosyalar)
**Konum:** `renderer/app-visualization.js` (2562 satır), `python_backend/train_gnn.py` (1969 satır), `renderer/index.html` (1299 satır)  
**Öneri:**
| Dosya | Mevcut Satır | Öneri |
|---|---|---|
| `app-visualization.js` | 2562 | `visualization/webgl.js`, `visualization/canvas2d.js`, `visualization/utils.js` |
| `train_gnn.py` | 1969 | `models/gnn.py`, `losses.py`, `trainer.py`, `data_utils.py` |
| `index.html` | 1299 | `templates/*.html` partials (setup, results, signaling, profiles, compare) |
| `app.js` | 872 | `navigation.js`, `dom-utils.js`, `event-delegation.js` |
| `app-signaling.js` | 1542 | `signaling/chord.js`, `signaling/heatmap.js`, `signaling/catalog.js`, `signaling/pathway.js` |
| `generate_pdf_report.py` | 1074 | `pdf/page1.py`, `pdf/page2.py`, `pdf/page3.py`, `pdf/synthesis.py` |

### 1.3 Template Engine Kullanımı
**Konum:** `python_backend/stages/stage5_report.py` (1121 satır inline HTML/CSS)  
**Öneri:** Jinja2 template engine kullan. `templates/report.html` ve `templates/report.css` ayrı dosyalar olarak tutulsun. Python sadece context dictionary'si ile doldursun.

### 1.4 Build Script Darwin-Only
**Konum:** `build_app.sh`  
**Sorun:** Sadece `osx-arm64` için Micromamba indiriyor. Intel Mac veya Linux geliştiriciler için script yok.  
**Öneri:**
- `build-scripts/build-mac.sh`, `build-scripts/build-win.ps1`, `build-scripts/build-linux.sh` olarak ayrıl.
- `uname -m` ile mimari algılama ekle.
- `build_app.sh` cross-platform wrapper olsun.

---

## 2. Python Backend (`python_backend/`)

### 2.1 `server.py` (1347 satır)
**Öneriler:**
- **Router modülerleştirme:** Tüm endpoint'ler tek `server.py` içinde. `routers/pipeline.py`, `routers/results.py`, `routers/drug_catalog.py`, `routers/cohort.py`, `routers/omnipath.py` olarak ayır.
- **Pydantic modeller:** `POST /pipeline/start` için `PipelineStartRequest` modeli var ama diğer endpoint'ler query param'lerle çalışıyor. `GET /results/summary` gibi endpoint'ler için de Pydantic response modeli ekle.
- **Exception handler:** `try/except` blokları tekrar ediyor. Global `ExceptionHandler` middleware ekle (FastAPI `@app.exception_handler`).
- **Dependency injection:** `output_dir` validasyonu her endpoint'te tekrarlanıyor. `Depends(validate_output_dir)` kullan.
- **Counterfactual knockout async:** `asyncio.to_thread()` iyi ama `torch.load` + inference hafıza yoğun. `ProcessPoolExecutor` veya ayrı worker queue düşünülebilir.
- **Cache TTL:** OmniPath cache 90 gün. `clear_omnipath_cache` endpoint'i authentication gerektirmiyor (localhost için kabul edilebilir ama production düşünülüyorsa API key ekle).

### 2.2 `pipeline_runner.py`
**Öneriler:**
- **Base class pattern:** Her stage `main()` fonksiyonuyla çalışıyor. `StageBase` abstract class oluştur:
  ```python
  class StageBase(ABC):
      @abstractmethod
      def run(self, args: StageArgs) -> StageResult: ...
  ```
- **Kod tekrarı:** `PROJECT_ROOT`, `BACKEND_DIR`, `exit_with_error` her stage'de tekrarlanıyor. `stage_utils.py` modülüne taşı.
- **Progress streaming:** Şu an stdout JSON parse ediliyor. Daha robust çözüm: `multiprocessing.Queue` veya `asyncio.Queue` ile IPC.
- **Stage dependency graph:** Şu an sıralı 5 stage. `networkx` veya basit bir DAG ile paralel stage'ler (örn. Stage 1 → Stage 2 & Stage 4 paralel) desteklenebilir.

### 2.3 `stages/stage1_preprocessing.py`
**Öneriler:**
- **Cell cycle gen listesi:** 97 gen hardcoded (`S_PHASE_GENES`, `G2M_PHASE_GENES`). JSON config'a taşı.
- **Mouse verisi:** `case-insensitive` eşleşme var ama `Mcm5` vs `MCM5` gibi farklı organizmalar için `species` parametresi ekle.
- **Sparse matrix:** `float32` CSR dönüşümü iyi, ama `chunked CSV` okuma daha generic `scanpy.read_10x_h5` ile değiştirilebilir.
- **Memory leak:** `del chunk_list`, `gc.collect()` kullanılmış ama `anndata` objeleri `copy()` yapılmadan. `inplace=True` parametrelerini kullan.
- **Logging:** `print()` yerine `logging` veya `loguru` kullan (diğer stage'lerle tutarlı).

### 2.4 `stages/stage2_deconvolution.py`
**Öneriler:**
- **Method dispatch:** `if method == 'tangram': ... elif method == 'cell2location': ...` uzun. `Deconvolver` registry pattern:
  ```python
  _DECONV_METHODS = {
      'tangram': TangramDeconvolver(),
      'cell2location': Cell2locationDeconvolver(),
      ...
  }
  ```
- **Fallback dekonvolüsyon:** `score_based_fallback()` iyi ama normalize edilmiş skorlar. `scipy.optimize.nnls` düşünülebilir.
- **GPU memory:** `cell2location` GPU kullanıyorsa `torch.cuda.empty_cache()` ekle.

### 2.5 `stages/stage3_gnn.py`
**Öneriler:**
- **Zone scores hesaplama:** Her zone için z-score O(N×Z). `numpy` vectorized ops ile optimize edilebilir.
- **Model kaydetme:** `torch.save` yerine `safetensors` (Hugging Face) düşünülebilir — daha hızlı, daha güvenli.
- **Hyperparameter:** `HIDDEN_DIM`, `NUM_LAYERS` gibi değerler CLI argümanından alsın, hardcoded olmasın.
- **Reproducibility:** `torch.manual_seed`, `numpy.random.seed`, `random.seed` set edilsin ama `torch.use_deterministic_algorithms` opsiyonel olsun (performans etkisi).

### 2.6 `stages/stage4_visualization.py`
**Öneriler:**
- **Permütasyon:** `permute_communication_score` 50 permütasyon — çok pahalı. `numba` JIT veya `numpy` vectorized hale getirilebilir.
- **OmniPath timeout:** `fetch_dynamic_lr_pairs()` 3 saniyelik timeout. Offline çalışma için `try/except` yerine `asyncio.gather` + timeout.
- **Data.json boyutu:** 150MB+ limit var. `orjson` veya `ujson` kullanarak parse hızlandırılabilir.
- **Figure DPI:** `dpi=150` hardcoded. Config'den alınabilir.

### 2.7 `stages/stage5_report.py`
**Öneriler:**
- **Inline HTML:** 1121 satır inline HTML. Jinja2 template engine kullan.
- **CSS ayrılması:** `style` attribute'ları çok. Ayrı `report.css` dosyası.
- **PDF export:** HTML'den PDF'e dönüşüm için `weasyprint` veya `pdfkit` düşünülebilir (şu an tarayıcı print'e güveniyor).

### 2.8 `train_gnn.py`
**Öneriler:**
- **Dosya bölme:** `models/gnn.py`, `losses.py`, `trainer.py`, `data_utils.py`.
- **Type hints:** `PyTorch` kodunda `torch.Tensor` type hints ekle.
- **Mixed precision:** `torch.cuda.amp` kullanılabilir (GPU varsa).
- **Gradient clipping:** `torch.nn.utils.clip_grad_norm_` eklenebilir (instability önlemek için).
- **Checkpointing:** `torch.save` yerine `safetensors`.

### 2.9 `pathway_mapper.py`
**Öneriler:**
- **SSL bypass:** `ssl._create_default_https_context = ssl._create_unverified_context` — güvenlik açığı. Sertifika doğrulaması opsiyonel yapılabilir ama default aktif kalmalı.
- **KEGG cache:** Her çalışmada KEGG'den indiriyor. `pathway_db.json` güncellemesi için TTL cache.
- **Fisher exact test:** `scipy.stats.fisher_exact` kullanılıyor — `statsmodels` ile `multiple_testing` correction (Benjamini-Hochberg) eklenebilir.

### 2.10 `check_env.py`
**Öneriler:**
- **Port kontrolü:** `socket.bind(('127.0.0.1', port))` — `SO_REUSEADDR` flag'i eklenebilir.
- **RAM kontrolü:** `psutil` opsiyonel. `psutil` yoksa `sys.maxsize` veya `os.sysconf` ile fallback.
- **Version parse:** `_parse_version` fonksiyonu `packaging.version` yerine custom. `packaging` zaten import ediliyor, custom parser'a gerek yok.

### 2.11 `generate_pdf_report.py`
**Öneriler:**
- **Matplotlib backend:** `PdfPages` kullanılıyor. `reportlab` veya `fpdf2` (zaten `requirements_server.txt`'te) daha hafif ve hızlı olabilir.
- **Font embedding:** Türkçe karakter desteği için font embedding kontrolü.
- **Image compression:** `dpi=150` ile büyük PDF'ler oluşabilir. `optimize=True` flag'i.

---

## 3. Electron Ana Süreç (`electron/`)

### 3.1 `main.js`
**Öneriler:**
- **Single Responsibility:** `main.js` 400+ satır. App lifecycle, window yönetimi, backend başlatma bir arada. `app-lifecycle.js`, `window-manager.js` olarak ayır.
- **Backend başlatma retry:** `waitForBackend()` 30 deneme, 1sn aralık. Exponential backoff eklenebilir.
- **App quit cleanup:** `app.on('before-quit', ...)` backend'i graceful kill ediyor ama `SIGTERM` vs `SIGKILL` ayrımı yok. `try { kill } catch { kill('SIGKILL') }` pattern'i.
- **Protocol kaydı:** `registerSchemesAsPrivileged` `bypassCSP: true` — XSS varsa riskli. `bypassCSP: false` düşünülebilir (yerel dosyalar için CSP zaten izinli olmalı).

### 3.2 `ipc-handlers.js`
**Öneriler:**
- **Handler kaydı:** `handlers.forEach(...)` dinamik ama `channel` isimleri string. `const CHANNELS = { ... }` enum olarak tanımla — typo hatalarını önler.
- **Path validation:** `isPathAllowed()` iyi ama `path.resolve` + `startsWith` kontrolü yerine `path.isAbsolute` + `realpath` daha güvenli.
- **Error handling:** `invoke('backend-request')` 120s timeout. `AbortController` ile cancel desteği eklenebilir.

### 3.3 `backend-manager.js`
**Öneriler:**
- **Python bulma:** `findPython()` 5 adımlı. `which-python` npm paketi veya `python3 -c "import sys; print(sys.executable)"` ile basitleştirilebilir.
- **Port kontrolü:** `killProcessOnPort()` Windows'ta `netstat -ano | findstr` regex'i `^.*:8765.*$` — birden fazla port eşleşebilir (18765 gibi). Regex düzeltmeli: `:8765\b`.
- **Process spawn:** `spawn(python, args, { stdio: 'pipe', windowsHide: true })` — `detached: true` eklenebilir (Electron crash anında Python process orphan kalmaması için).

### 3.4 `license.js`
**Öneriler:**
- **RSA public key:** `verifyLicense()` `publicKey` hardcoded. Environment variable veya config'den alınabilir (farklı deploy ortamları için).
- **Cache HMAC:** `createHmac('sha256', 'glio-cache')` — secret hardcoded. Daha güçlü secret veya rotasyon mekanizması.
- **Machine ID:** `machineId` CPU+MAC+BIOS hash'i. Virtual machine'lerde MAC değişebilir. `machine-uuid` veya `system-uuid` eklenebilir.

### 3.5 `runtime-manager.js`
**Öneriler:**
- **Download progress:** `downloadWithRedirects()` `https` modülü kullanıyor. `electron.net` (Chromium net stack) daha hızlı ve proxy-aware olabilir.
- **VC++ kontrolü:** Windows'ta PowerShell `-EncodedCommand` iyi ama `chcp 65001` (UTF-8) ekleme — Türkçe karakter sorunları önlemek için.
- **Extraction:** `7z` veya `unzip` bağımlılığı. `adm-zip` (pure JS) veya `node-stream-zip` ile dependency azaltılabilir.

### 3.6 `updater.js`
**Öneriler:**
- **Semver karşılaştırma:** `semverGt` custom implementation. `semver` npm paketi kullanılabilir (daha robust, edge case'ler için test edilmiş).
- **Rollback:** `rollback()` script tabanlı iyi ama macOS'ta `open "${dest}"` — SIP korumalı dizinlerde başarısız olabilir. Kullanıcıya bildirim.
- **DMG install:** `installDmgMacOS()` `cp -Rf` kullanıyor. `ditto` (macOS native) daha hızlı ve metadata koruyucu.

### 3.7 `store.js`
**Öneriler:**
- **Race condition:** `readStore()` ve `writeStore()` async ama aynı anda çalışırsa race condition. `async-mutex` veya `p-lock` ile serialize et.
- **Backup:** JSON store bozulursa recovery yok. `.store.json.bak` periyodik backup.

### 3.8 `utils.js`
**Öneriler:**
- **Log rotation:** `MAX_LOG_SIZE = 5 * 1024 * 1024` ama `fs.statSync` her log yazımında çağrılıyor. Performans için `bytesWritten` sayacı tut.
- **ANSI escape:** `stripAnsi` regex'i. `strip-ansi` npm paketi daha robust.

---

## 4. Renderer İşleyici Süreç (`renderer/`)

### 4.1 `app.js`
**Öneriler:**
- **Event delegation:** 872 satır event listener kaydı. `data-action` attribute pattern'i ile dinamik delegation:
  ```js
  document.body.addEventListener('click', e => {
    const action = e.target.closest('[data-action]')?.dataset.action;
    if (action) actionHandlers[action](e);
  });
  ```
- **DOMContentLoaded:** `setupNavButtons()` ve `setupAppButtons()` ayrık. Tek bir init fonksiyonu.
- **Global state:** `window.state` kullanılıyor. Daha encapsulated `StateManager` class.

### 4.2 `app-state.js`
**Öneriler:**
- **State management:** Global obje pattern'i. `Proxy` veya `EventEmitter` ile reactivity eklenebilir.
- **Toast sistemi:** `showToast` fonksiyonu DOM'a append/remove yapıyor. Toast queue eklenebilir (çakışan toast'lar için).
- **Memory leak:** `setTimeout` ile toast kaldırma — `clearTimeout` eklenmemiş (overlap durumunda). Toast ID'yi takip et.

### 4.3 `app-startup.js`
**Öneriler:**
- **Lisans kontrolü:** 10 deneme, 1sn aralık. Exponential backoff.
- **Backend senkronizasyon:** `api.getBackendStatus()` polling. `EventSource` veya WebSocket düşünülebilir (Long polling yerine).
- **Download progress:** `Math.round((received / total) * 100)` — `total` 0 ise division by zero. Guard ekle.

### 4.4 `app-pipeline.js`
**Öneriler:**
- **Progress animation:** `requestAnimationFrame` ile smooth progress bar. Şu an `setTimeout` ile 150ms delay.
- **Cancel race:** `cancelPipeline()` API çağrısı yapıyor ama UI hemen resetleniyor. Backend onayı beklenebilir.
- **Log streaming:** `api.onBackendLog` kullanılıyor. `ReadableStream` ile backend log'ları anlık akabilir.

### 4.5 `app-visualization.js` (2562 satır)
**Öneriler:**
- **WebGL/Canvas2D ayrımı:** İki motor aynı dosyada. Ayrı modüllere böl.
- **Buffer management:** `BufferGeometry` güncelleme — `dispose()` ile memory leak önleme (geçişlerde).
- **LOD (Level of Detail):** 10k+ spot için LOD. Uzak noktalarda azaltılmış geometri.
- **WebGL fallback:** `isWebGLSupported()` var ama `webgl2` kontrolü yok. WebGL 2 özellikleri kullanılıyorsa fallback netleştirilmeli.

### 4.6 `app-signaling.js` (1542 satır)
**Öneriler:**
- **Chord diagram:** SVG oluşturma çok detaylı. `d3-chord` veya `d3-ribbon` kullanılabilir (mevcut vanilla JS yerine).
- **Heatmap:** Canvas 2D kullanılıyor. `d3-heatmap` veya pure canvas — mevcut çözüm iyi ama modülerleştirilebilir.
- **L-R catalog filter:** `normalizeForFilter()` Türkçe karakter dönüşümü. `Intl.Collator` veya `localeCompare` ile daha generic.
- **XSS:** `escapeHtml()` kullanılıyor — iyi. Ama `innerHTML` bazı yerlerde hala var (örn. `drawContrastChart`). `textContent` veya `document.createElement` ile oluşturma daha güvenli.

### 4.7 `app-analytics.js` (857 satır)
**Öneriler:**
- **Export locks:** `exportLocks` Map kullanılıyor — iyi. Ama `Set` daha uygun (boolean değil, sadece varlık kontrolü).
- **PDF export:** `iframe.contentDocument` ile clone. `html2canvas` + `jsPDF` ile daha robust PDF export.
- **Multi-patient comparison:** HTML string interpolation. `DocumentFragment` kullanımı daha güvenli.
- **KM cohort:** `setKmCohort()` fade transition iyi ama `transitionend` event'i dinlenmiyor. `setTimeout` yerine promise-based transition.

### 4.8 `app-profiles.js` (738 satır)
**Öneriler:**
- **Custom prompt/confirm:** `customPrompt` ve `customConfirm` iyi. Ama `dialog` element (HTML5 native) kullanılabilir — daha erişilebilir (a11y).
- **Settings persistence:** `saveCurrentSettings()` 18 alan tek fonksiyon. `Settings` class ile serialize/deserialize.
- **Compare data loading:** `fetch` + `api.readJsonFile` fallback. `api.readJsonFile` her zaman çağrılsın (tek kaynak).
- **Background image timeout:** 5 saniye timeout. `AbortController` ile `Image.src` iptal edilebilir.

### 4.9 `drug-catalog.js`
**Öneriler:**
- **Polling:** `setInterval` ile 1sn polling. `EventSource` veya WebSocket daha efficient.
- **Error state:** `refresh()` reject ediyor ama UI'da retry mekanizması yok. Exponential backoff ile retry.

### 4.10 `i18n.js`
**Öneriler:**
- **Key fallback:** `missingKey` fallback'i var. `Intl.NumberFormat`, `Intl.DateTimeFormat` ile tarih/sayı formatlama.
- **Interpolation:** `{count}` gibi placeholder'lar. `Intl.PluralRules` ile çoğul desteği.
- **Language detection:** `navigator.language` kullanılıyor. `Accept-Language` header'ı veya kullanıcı preference'ı.

### 4.11 `index.html` (1299 satır)
**Öneriler:**
- **HTML partials:** `template` elementleri veya Jinja2 benzeri. Build-time HTML split.
- **Lazy loading:** `<img loading="lazy">` iyi ama `<iframe>` lazy loading de eklenebilir.
- **Accessibility:** `aria-label`, `role` attribute'ları eksik. Ekran okuyucu desteği.
- **CSS:** `style.css` 3000+ satır olabilir. CSS custom properties (variables) kullanılıyor ama utility class'lar `tailwind` benzeri düşünülebilir.

---

## 5. Güvenlik İyileştirmeleri

### 5.1 `local://` Protokolü
**Konum:** `electron/protocol-handler.js`  
**Sorun:** `registerSchemesAsPrivileged` ile `bypassCSP: true`  
**Öneri:** CSP bypass sadece `local://` için gerekli. `bypassCSP: false` yap, yerel dosyalar için CSP zaten `default-src 'self'` ile izinli.

### 5.2 SSL Bypass
**Konum:** `python_backend/pathway_mapper.py:8-11`  
**Sorun:** `ssl._create_default_https_context = ssl._create_unverified_context`  
**Öneri:** Opsiyonel yap. `--insecure` flag'i veya `GLIO_INSECURE_SSL=true` env değişkeni. Default'ta güvenli kalsın.

### 5.3 Path Traversal
**Konum:** `renderer/app-profiles.js:23`, `renderer/app-analytics.js:8-16`  
**Sorun:** `isPathSafe()` renderer'da tekrarlanıyor. `preload.js` zaten `isPathAllowed` sunuyor. Tekrar implementasyon.
**Öneri:** Tek `isPathAllowed` fonksiyonu — `preload.js` veya shared module.

### 5.4 Prototype Pollution
**Konum:** `electron/ipc-handlers.js:61-78`  
**Durum:** Mevcutta `__proto__`, `constructor`, `prototype` engelleme var. İyi.  
**Öneri:** `Object.freeze()` veya `deepFreeze()` ile store objesi immutable yapılabilir.

---

## 6. Performans İyileştirmeleri

### 6.1 Python
- **Data loading:** `json.load()` yerine `orjson` veya `ujson` (3-5x hızlı).
- **Pandas:** `chunked CSV` okuma. `pyarrow` backend (`pandas>=2.0` ile `dtype_backend="pyarrow"`).
- **NumPy:** `zone_scores` hesaplama vectorized.
- **Matplotlib:** `fig.savefig()` `bbox_inches='tight'` pahalı. `tight_layout()` önceden.
- **PyTorch:** `torch.compile()` (PyTorch 2.0+) kullanılabilir — model inference hızlandırma.

### 6.2 Electron/Renderer
- **Image loading:** `local://` ile 150MB+ data.json. `Stream` API ile chunked okuma.
- **WebGL:** `BufferGeometry` dispose, `Texture` dispose — memory leak önleme.
- **CSS:** `will-change: transform` animasyon elemanlarında GPU acceleration.
- **DOM:** Virtual scrolling (10k+ spot listesi için). `IntersectionObserver` ile lazy render.

---

## 7. Test ve Kalite Güvencesi

### 7.1 Eksik Testler
**Durum:** Proje genelinde test dosyası görülmedi.  
**Öneri:**
| Katman | Test Framework | Kapsam |
|---|---|---|
| Python | `pytest` + `pytest-asyncio` | Unit test (her stage), integration test (pipeline), API test (FastAPI `TestClient`) |
| Python | `pytest-cov` | Coverage hedefi: %80+ |
| Electron | `vitest` veya `jest` | IPC handler unit test, store logic test |
| Renderer | `playwright` | E2E test (UI flow, pipeline start/cancel) |
| Build | `pytest` | Build script test (CI/CD) |

### 7.2 Statik Analiz
**Öneri:**
- Python: `mypy`, `pylint`, `black`, `isort`, `ruff`
- JavaScript: `eslint`, `prettier`, `typescript` (migration)
- GitHub Actions: `pre-commit` hooks ile CI pipeline'a entegre et

### 7.3 TypeScript Migration
**Öneri:** Electron ve renderer JS dosyaları `TypeScript`'e migrate edilebilir. Tip güvenliği, refactor kolaylığı, IDE autocomplete avantajları.

---

## 8. Özet ve Önceliklendirme

| Öncelik | Konu | Dosya(lar) | Etki |
|---|---|---|---|
| 🔴 **Kritik** | Config dosyası ekle | `configs/config.yaml`, `stage1_preprocessing.py`, `stage2_deconvolution.py` | Spatial QC parametreleri düzgün çalışsın |
| 🔴 **Kritik** | Test suite oluştur | Tüm `python_backend/`, `electron/`, `renderer/` | Regresyon önleme |
| 🟡 **Yüksek** | Modülerleştirme | `app-visualization.js`, `train_gnn.py`, `index.html`, `app-signaling.js` | Bakım kolaylığı |
| 🟡 **Yüksek** | FastAPI router ayrımı | `server.py` | Kod okunabilirliği, test edilebilirlik |
| 🟡 **Yüksek** | Jinja2 template | `stage5_report.py` | HTML/CSS ayrımı |
| 🟢 **Orta** | SSL bypass opsiyonel | `pathway_mapper.py` | Güvenlik |
| 🟢 **Orta** | Semver npm paketi | `updater.js` | Robust version compare |
| 🟢 **Orta** | `orjson` kullanımı | `server.py`, `stage3_gnn.py`, `stage4_visualization.py` | Performans |
| 🟢 **Düşük** | TypeScript migration | `electron/`, `renderer/` | Gelecekte bakım |
| 🟢 **Düşük** | `safetensors` | `train_gnn.py` | Model kayıt hızı |

> **Not:** Tüm iyileştirmeler mevcut kodun işlevselliğini bozmadan, iteratif olarak uygulanabilir. Önce test suite ve config dosyası eklenmeli, sonra modülerleştirme yapılmalıdır.
