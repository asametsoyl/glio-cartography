# Z-BRIDGE — Mevcut Kod Denetimi ve v0.1 Tasarımı

> Durum: **TASARIM / ONAY BEKLİYOR. Z-BRIDGE için henüz kod yazılmadı.**
> Taban: `v3.2.12-gbm-legacy` + bu dalda yapılan temizlik (spekülatif çıktıların silinmesi,
> doku paketi, CI). Bu belge `ROADMAP.md`'yi **3B bölümü için** günceller (bkz. §I).
> Okuma notu: sayılar ve dosya adları depoyu bu dalda okuyarak çıkarıldı; "doğrulanmalı"
> işaretli şeyler dış bilgidir ve kullanılmadan önce kaynağından teyit edilmelidir.

---

## 0. Kısa görüş

**Yön doğru ve ayırt edici.** Piyasadaki araçların çoğu seri kesitleri ya tek tek analiz eder
ya da hizalayıp bir "3B görüntü" üretir; hizalama belirsizliğini modelin içine sokan,
XY ve Z bilgi akışını ayrı parametrelerle öğrenen bir motor ürün ve yayın açısından anlamlı.
"Önce görselleştirme, sonra analiz" yerine "önce graf, sonra model" tespitin de doğru.

**Ama şu sekiz konuda spesifikasyonu bilerek değiştirmeyi öneriyorum** (ayrıntı §E ve §I):

1. **Visium geometrisi sezgiyi tersine çeviriyor.** Spot çapı ≈ 55 µm, merkezler arası ≈ 100 µm,
   kesit kalınlığı tipik olarak ≈ 10 µm (doğrulanmalı: kullanılan protokol). Yani ardışık
   kesitlerde "en yakın 3B komşu" neredeyse hep **üstteki/alttaki aynı doku sütunu**dur;
   saf 3B kNN grafı Z kenarlarının egemenliğindedir. Z kenarları bu yüzden ayrı tipli ve ayrı
   kernelli kurulmalı (spesifikasyonun zaten istediği gibi) — ve Z komşusu "aynı hücre" değil,
   "örtüşen doku sütunu" anlamına gelir.
2. **Registration hatası spot aralığıyla aynı mertebede** (onlarca–yüzlerce µm). Bu yüzden
   correspondence tek-nokta değil geniş bir olasılık kütlesi olmalı ve **"eşleşme yok" (null)
   seçeneği** içermeli. Null kütlesi, `c_ij` ve `g_i` için doğal, kalibre edilebilir güven kaynağı olur.
3. **`b_ij` (boundary) ilk sürümde öğrenilmemeli.** Etiketsiz öğrenilen sınır olasılığı
   tanımlanamaz (kayıp `b→1` ile kendini "çözer"). v0.1'de `b_ij` deterministik, çok kanallı bir
   özelliktir; öğrenilen artık ancak ablasyon fayda gösterirse eklenir.
4. **Formül 41'de `c_ij` ve `β_ij` çift sayılıyor.** Correspondence'ı attention logit'ine
   (log-prior) koyup `g_i`'yi kenar bazında değil özet istatistiklerden üretmek hem daha
   savunulabilir hem ablasyonu temizdir.
5. **Section kimliği ve batch etkisi** en büyük sessiz risk: model "hangi kesitteyim"i
   ezberleyip Z kenarlarını anlamsızlaştırabilir. Bunun için baştan bir **probe testi** (§G)
   ve kesit-başı normalizasyon koyuyoruz.
6. **Doğrulama verisi kıt.** Gerçek, etiketli, çok-kesitli Visium çok az. Bu yüzden önce
   **sentetik 3B doku fantomu** (gerçek kanıt değil, mühendislik doğrulaması) ve halka açık
   birkaç çok-kesitli veri; ilk bulgu "Z-BRIDGE X'ten iyi" değil "XY-only'ye karşı ablasyon"
   olmalı.
7. **Sıralama.** Fantom + veri modeli registration'dan ÖNCE gelir; her şey ground truth ister.
8. **Kapasite.** Tek kişi için Faz 1–9 (MVP) gerçekçi; Faz 10–14 ayrı bir ürün dilimi.

Önceki `ROADMAP.md`'deki "önce tek kesitli genel motor, 3B MVP sonrası" sırası bu belgeyle
**değişiyor**: 3B artık çekirdek yenilik. Tek kesitli motor, Z kenarı olmayan özel durum olarak
kalıyor (§E.10), ayrı sistem olarak değil.

---

## A. Mevcut Mimari Denetimi

### A.1 Klasör yapısı (bu dal)

```
glio-cartography/
├─ electron/            masaüstü kabuğu: main, preload, IPC, backend yöneticisi, lisans, güncelleme (~3.9k satır)
├─ renderer/            arayüz (vanilla JS, ~9k satır uygulama kodu) + three.js
│   ├─ app-visualization.js (2547)  2B canvas/WebGL harita, split/compare, tooltip
│   ├─ app-signaling.js (1416)      L-R, yolak, katalog
│   ├─ app-tumor-map.js (960)       GBM'ye özel "tümör mikroçevre haritası" (SVG)
│   └─ app-spatial-3d.js (270)      3B görünüm (bkz. A.5)
├─ python_backend/
│   ├─ server.py (1135)             FastAPI, ~20 endpoint
│   ├─ pipeline_runner.py (298)     5 aşamayı alt süreç olarak çalıştırır
│   ├─ stages/stage1..5_*.py        ön işleme → dekonvolüsyon → GNN → figürler → rapor
│   ├─ train_gnn.py (1653)          graf kurma + model + eğitim + dışa aktarım (monolit)
│   ├─ tissue_pack.py + tissue_packs/gbm/   (bu dalda eklendi)
│   ├─ pathway_mapper.py (633)      yolak zenginleştirme, KEGG haritaları
│   ├─ generate_pdf_report.py, templates/   rapor
│   └─ tests/ (46 test)             birim + sentetik uçtan uca GNN smoke testi
├─ configs/config.yaml (681)        parametreler + GBM hücre marker'ları
├─ tests/*.test.{js,py}             i18n, protokol, küçük matematik testleri
└─ .github/workflows/               build.yml (paketleme), test.yml (bu dalda eklendi)
```

### A.2 Ana pipeline

`Electron (IPC) → FastAPI (/pipeline/start) → PipelineRunner → 5 alt süreç`.
Aşamalar arası iletişim **ortam değişkenleri** (`GLIO_*`) ve **stdout'a JSON satırları**; veri
aşamalar arasında **dosya** olarak akar:

| Aşama | Girdi | Çıktı |
|---|---|---|
| 1 ön işleme | Visium klasörü/.h5 + scRNA .h5ad | `preprocessing/{spatial,scrna}/*.h5ad` |
| 2 dekonvolüsyon | yukarıdakiler | `spatial_deconvolved.h5ad` (`obsm['celltype_proportions']`) |
| 3 GNN | `spatial_deconvolved.h5ad` | `gnn/data.json` (≤150 MB tek JSON), `.pt`, `.npy`, `gnn_summary.json` |
| 4 görselleştirme | `data.json` + h5ad | `publication_figures/*.png` |
| 5 rapor | özet JSON'lar | `reports/Rapor_*.html/.pdf` |

### A.3 Veri modeli (bugün)

- **Tek kesit = tek AnnData.** `obsm['spatial']` (x,y), `obsm['X_pca']`, `obsm['celltype_proportions']`
  (DataFrame), bazı `obs` skorları (`hypoxia_score`…), `obsp['connectivities']`.
- **Z, kesit kimliği, kalınlık, registration, histoloji embedding'i, güven alanları: yok.**
- Sonuçlar tek bir `data.json` içinde spot listesi olarak (arayüzün doğrudan okuduğu biçim).
- Doku bilgisi artık `tissue_packs/gbm/` altında (bölgeler, renk, etiket, atıf); hücre
  marker'ları, L-R listesi ve bazı eşikler hâlâ motor/config içinde.

### A.4 GNN (bugün)

`GlioCartographyGNN` (`train_gnn.py`): düğümler `spot`; özellik = PCA(≤50) + hücre tipi oranları + 4 niş skoru.
İki **kenar tipi** zaten var:

- `contacts`: mesafe ≤ 1,25 × medyan en-yakın-komşu mesafesi; kenar özelliği = RBF mesafe kodu
  (K=8/16/24) + 150 L-R çiftinin kenar aktivitesi + mesafe; **GATv2** ile işlenir.
- `diffuses`: ≤ 5 × medyan; **SAGE** ile işlenir.

Çok görevli kafalar (hücre tipi oranı, bölge) + öz-denetimli kayıplar (EMA-DGI, düzgünlük,
"L-R-önsel dikkat düzenlemesi"), Kendall ağırlıklandırma, PCGrad, MC-dropout belirsizliği.
**Hedefler çembersel:** bölge hedefi (`zone_y`) pakettten gelen imzalardan türetilir; hücre
tipi hedefi Tangram çıktısıdır. Held-out MSE iç tutarlılıktır, doğruluk değildir.
Bu bilgi `VALIDATION_*.md` ve raporda zaten dürüstçe belirtiliyor.

Yani "heterojen kenar tipli GNN" iskeleti mevcut; **Z kenarları, güven, kapı ve sınır eksik**.

### A.5 Mevcut "3B" gerçekte ne?

`app-spatial-3d.js`: `loadData(spots)` **tek kesitin spotlarını üç kez** (`spots.length * 3`)
üst üste dizer; "hizalama" elle kaydırıcılarla (θ, tx, ty, aralık varsayılan 50 µm). Seri kesit
girdisi, registration, Z kenarı, 3B analiz yok. Bu bir **demo görünümü**; spesifikasyonun
"yapma" dediği tam olarak bu. Z-BRIDGE ile **değiştirilecek, genişletilmeyecek**.

### A.6 Hâlâ GBM'ye gömülü parçalar (Faz 1 işi)

| Yer | Ne gömülü |
|---|---|
| `train_gnn.py::LR_PAIRS` | 150 çiftlik liste ve GBM-temalı kategoriler (angiogenesis, immunosuppression…) |
| `train_gnn.py::build_graph_data` | `get_coarse_group` (tumor/myeloid/T/stromal anahtar kelimeleri), `niche_cols` (hipoksi, miyeloid baskılama, T hücre tükenmesi, anjiyogenez) |
| `configs/config.yaml` | GBM hücre marker'ları, hücre durumları |
| `stage4_visualization.py` | bipartite ağda `edge_defs` (TAM, Tumor_MES, Microglia…), L-R figürü |
| `stage5_report.py` | 4 sabit yolak (PI3K_AKT_mTOR, MAPK_ERK, JAK_STAT, NFkB), PubMed önerileri (artık pakete bağlı) |
| `pathway_db.json`, `pathway_mapper.py` | KEGG/GO; KEGG ticari lisans sorunu |
| `renderer/app-tumor-map.js` | "tümör çekirdeği / invazyon / sağlıklı" sezgisel SVG (bölge adlarına bağlı) |
| env/dizin adları | `GLIO_*`, `glio_gnn_v3.pt`, uygulama adı |

(Bölge adları/imzaları/renkleri/atıf bu dalda doku paketine taşındı; testle korunuyor.)

### A.7 Yeniden kullanılabilir parçalar

`GeneExpressionCache`; XY graf mantığı (adaptif K, medyan-NN ölçeği, RBF kodlama); MC-dropout;
kayıp parçaları (focal, EMA-DGI) ve PCGrad (ablasyonla tutulup tutulmayacağına karar verilir);
stage 1 QC fonksiyonları; stage 2 dekonvolüsyon yöntem seçimi; lisans/güncelleme/Electron altyapısı;
`tissue_pack.py`; CI + sentetik smoke test iskeleti; L-R permütasyon skoru (`stage4`).

### A.8 Teknik borç

1. **Monolit stage betikleri**, ortam değişkeniyle parametre ve stdout-JSON protokolü: test
   edilemez, tekrar kullanılamaz. Modül yükleme yan etkileri (`sys.exit` at import, import anında
   argparse/yolak yükleme).
2. **`data.json` tek dosya** (≤150 MB sınırı): 3B ve çok-kesitte ölçeklenmez, tipli kenar saklayamaz.
3. **Provenance yok:** sürüm/parametre/girdi checksum'ı/zaman damgası kaydı yok; yalnız tohumlar sabit.
4. **Dekonvolüsyon scRNA referansı şart** (Tangram); çoğu müşteride yok.
5. **Frozen/PyInstaller yol hileleri** birçok dosyada kopya.
6. **Tek kesit varsayımı** her yerde (`obsm['spatial']` 2B, tek `X_pca`).
7. **Renderer devasa dosyalar** (2,5k satırlık `app-visualization.js`), testsiz; yalnız bu dalda eklenen
   headless smoke kontrolü var (CI'ya henüz alınmadı).
8. **Lisans:** KEGG; Ivy GAP kullanım şartları (`needs_review`); bağımlılık lisans taraması yok.
9. **Numerik/bağımlılık kırılganlığı:** pandas 3 uyumsuzluğu bu dalda bir kez düzeltildi; sürüm
   pin'leri yok (`requirements_server.txt`).
10. **Doğrulama çembersel** (A.4); bağımsız etiketli doğrulama altyapısı yok.

---

## B. Z-BRIDGE Taşıma Haritası

Karar anahtarı: **KEEP** olduğu gibi · **REFACTOR** davranış korunarak yeniden düzenle ·
**REPLACE** yeni bileşenle değiştir (parite/üstünlük kanıtından sonra) · **REMOVE** · **NEW**.

### Python

| Mevcut | Karar | Not |
|---|---|---|
| `tissue_pack.py`, `tissue_packs/gbm/` | **KEEP** → `tissues/` + `spatialcore/tissues/loader.py` | yalnız konum değişir; `reference_validation` korunur |
| `server.py` | **REFACTOR** | router'lara böl; `/volume/*`, `/runs/*` ekle; `output_dir` doğrulaması tek yerde |
| `pipeline_runner.py` | **REFACTOR** | alt süreç + env yerine `spatialcore` CLI/kütüphane çağrısı; `manifest.json` yazar |
| `stages/stage1_preprocessing.py` | **REFACTOR** | → `io/`, `qc/`, `preprocessing/`; **kesit-başı** QC; çok-kesitli girdi |
| `stages/stage2_deconvolution.py` | **REFACTOR** | yöntem kayıt defteri; scRNA'sız yol (bkz. ROADMAP Faz 1) |
| `train_gnn.py::GeneExpressionCache` | **KEEP** → `data/` | |
| `train_gnn.py::build_graph_data` | **REFACTOR** | → `graph/xy_graph.py` (mantık korunur, GBM kovaları ve niş sütunları pakete/config'e) |
| `train_gnn.py::GlioCartographyGNN` + `train_model` | **KEEP (legacy 2D)** → sonra **REPLACE** | `ZBridgeModel` Z-kenarsız modda **parite veya üstünlük** kanıtlayana kadar silinmez |
| `train_gnn.py` kayıplar (focal, EMA-DGI, PCGrad, Kendall) | **REFACTOR** | ayrı modüller; ablasyonla tutulacaklar belirlenir |
| `train_gnn.py::mc_dropout_zone_uncertainty` | **REFACTOR** → `model/uncertainty.py` | |
| `train_gnn.py::LR_PAIRS` | **REFACTOR** | → L-R referansı (kaynak/lisans/sürümle), paketten seçilebilir |
| `train_gnn.py::export_attention_to_json` | **REPLACE** | proje dizini + Parquet/Zarr; arayüz için ince bir JSON dilimi |
| `stages/stage3_gnn.py` | **REPLACE** | `spatialcore.analysis.domains` ve `zbridge` eğitim girişi |
| `stages/stage4_visualization.py` | **REFACTOR** | saf analiz fonksiyonları `analysis/` altına; GBM'ye özel şekiller pakete |
| `stages/stage5_report.py`, `generate_pdf_report.py`, `templates/` | **REFACTOR → REPLACE** | tek rapor motoru, provenance bölümü, 2B/3B bölümleri |
| `pathway_mapper.py`, `pathway_db.json` | **REFACTOR** | KEGG çıkar; lisansı temiz kaynak; zone eşleştirme düzeltmesi korunur |
| `check_env.py` | **KEEP** | |
| `stages/locale_logger.py` | **REMOVE** | metin-çeviri hilesi yerine yapılandırılmış log + mesaj kodları |
| `reference_data/ivygap_real_reference.json` | **KEEP** → GBM paketi | lisans durumu `needs_review` |
| `tests/*` (46) | **KEEP** + genişlet | smoke test → `tests/integration` |
| `configs/config.yaml` | **REFACTOR** | motor parametreleri / paket marker'ları ayrılır |

### Renderer / Electron

| Mevcut | Karar |
|---|---|
| `app-spatial-3d.js` | **REPLACE** → `viewer_3d` (gerçek hacim, filtreler, kesit gizleme) |
| `app-tumor-map.js` | **REMOVE** (GBM sezgiseli) → ihtiyaç olursa paket-güdümlü görünüm |
| `app-visualization.js` | **REFACTOR** (2B görüntüleyici modüllere; tek/çok-kesit ortak) |
| `app-signaling.js`, `app-analytics.js`, `app-pipeline.js`, `app-profiles.js` | **REFACTOR** (kesit seti seçimi, run manifest) |
| `i18n`, `app-state`, `app-startup` | **KEEP** |
| `electron/*` | **KEEP** (backend-manager yalnız yeni giriş noktası için küçük **REFACTOR**) |
| `.github/workflows/test.yml` | **KEEP** + renderer headless smoke ekle |

### NEW

`spatialcore/data` (VolumeSet), `registration/`, `graph/{z_graph,correspondence,typed_graph}.py`,
`model/{zbridge,boundary,gates,histology}.py`, `analysis/{domains,niches,boundaries,ligand_receptor}`,
`provenance/`, `synthetic/` (3B doku fantomu), `benchmarks/` (ablasyon koşucusu), `report/` (provenance bölümü).

---

## C. Önerilen Depo Yapısı

Strangler yaklaşımı: `spatialcore/` kök dizinde bağımsız, `pip install -e .` ile kurulabilen paket;
`python_backend/` zamanla ince bir adaptöre (FastAPI + eski stage'ler) iner. Eski akış, yeni motor
parite sağlayana kadar çalışır durumda kalır.

```
glio-cartography/                  (ürün adı kararı bekliyor; paket adı: spatialcore)
├─ pyproject.toml
├─ spatialcore/
│  ├─ __init__.py                  __version__, public API
│  ├─ config/
│  │   ├─ schema.py                pydantic şemaları (tüm parametreler tipli)
│  │   └─ defaults/{zbridge,graph,registration,qc}.yaml
│  ├─ io/                          visium.py, anndata_io.py, volume_io.py  → VolumeSet üretir
│  ├─ data/                        volume.py (VolumeSet), sections.py, schema.py, checksums.py
│  ├─ qc/                          per_section.py, pairwise.py (PASS/WARNING/FAIL), thresholds.yaml
│  ├─ preprocessing/               normalize.py (kesit-başı), features.py (PCA/HVG), composition.py
│  ├─ registration/
│  │   ├─ rigid.py  affine.py  nonrigid.py          (nonrigid Faz 13)
│  │   ├─ soft_correspondence.py                    EM/CPD tipi, posterior = Z olasılığı tohumu
│  │   ├─ confidence.py                             registration_confidence + kalibrasyon
│  │   ├─ histology_align.py                        (arayüz; Faz 7+ isteğe bağlı)
│  │   └─ chain.py                                  ardışık çiftlerden global poz + birikmiş belirsizlik
│  ├─ graph/
│  │   ├─ xy_graph.py                               mevcut contacts/diffuses mantığı
│  │   ├─ correspondence.py                         p_corr, null kütlesi, Δz bozunumu
│  │   ├─ z_graph.py                                Zup/Zdown kenarları, eksik kesit atlama
│  │   ├─ boundary_features.py                      b_ij (deterministik, çok kanallı)
│  │   └─ typed_graph.py                            TypedGraph ↔ PyG HeteroData, Parquet I/O
│  ├─ model/
│  │   ├─ zbridge.py                                ZBridgeLayer, ZBridgeEncoder
│  │   ├─ gates.py                                  Z kapıları g_up/g_down
│  │   ├─ boundary.py                               sınır kapısı (+ v0.2 öğrenilen artık)
│  │   ├─ heads.py                                  domain / reconstruction
│  │   ├─ losses.py                                 reconstruction, inter-section consistency, (opsiyonel) DGI
│  │   ├─ uncertainty.py                            entropi, MC-dropout, kalibrasyon (ECE)
│  │   ├─ histology_encoder.py                      HistologyEncoder arayüzü + "none" uygulaması
│  │   └─ trainer.py                                tohum, checkpoint, erken durdurma
│  ├─ analysis/
│  │   ├─ domains/ (embedding_clustering.py, probabilities.py, transition.py)
│  │   ├─ niches/            (Faz 11)
│  │   ├─ ligand_receptor/   (Faz 12: 3B mesafe çekirdeği)
│  │   ├─ pathways/
│  │   └─ boundaries/        (Faz 14: yüzey, signed distance, geçiş programları)
│  ├─ tissues/loader.py                               (tissue_pack.py buraya taşınır)
│  ├─ provenance/                                     manifest.py, checksums, environment.py
│  ├─ report/                                         html.py, pdf.py, sections/ (qc, domains, provenance…)
│  ├─ visualization/
│  │   ├─ viewer_2d/  (matplotlib dışa aktarım)
│  │   └─ viewer_3d/  (veri sözleşmesi: tipli, hafif "view bundle")
│  ├─ synthetic/                                      phantom.py (küre/kabuk/kanal), deform.py, sectioning.py
│  └─ cli.py                                          spatialcore run|qc|register|train|report
├─ tissues/                                           gbm/  brain/  breast/  custom/  (YAML paketleri)
├─ python_backend/                                    FastAPI adaptörü + legacy 2D stage'ler (azalır)
├─ electron/  renderer/                               kabuk + arayüz
├─ benchmarks/                                        ablation_runner.py, datasets.yaml, results/ (git dışı)
├─ docs/                                              ZBRIDGE_DESIGN.md, DATA_MODEL.md, METHODS.md
└─ tests/
   ├─ unit/  integration/  regression/
   ├─ registration/  graph/  model/
   └─ data/ (küçük sabit fixture'lar; büyük veri yok)
```

Proje çıktı dizini (her analiz) §D.5'te.

---

## D. Veri Modeli

### D.1 Kavramlar

`VolumeSet` = bir örneğe ait sıralı kesitler + birleşik gözlem tablosu + kesitler arası kayıt (registration)
tablosu. Tek kesit, `n_sections = 1` olan bir `VolumeSet`'tir (**ayrı kod yolu yok**).

### D.2 `sections` tablosu (kesit başına bir satır)

| Alan | Tür | Not |
|---|---|---|
| `section_id` | str | benzersiz |
| `sample_id` | str | hasta/örnek |
| `order` | int | **fiziksel sıra** (dosya sırası değil; kullanıcı onaylar) |
| `thickness_um` | float \| null | ölçülmüş/nominal; bilinmiyorsa `null` |
| `thickness_source` | enum | `measured` \| `nominal` \| `unknown` |
| `gap_um` | float \| null | bu kesit ile bir sonraki arasındaki atılan doku (bilinmiyorsa null) |
| `gap_source` | enum | `measured` \| `nominal` \| `unknown` |
| `orientation_flip` | bool | ayna/çevirme düzeltmesi gerekli mi |
| `platform`, `spot_diameter_um`, `spot_pitch_um` | | ölçek ve kernel genişliği için |
| `image_path`, `image_scale_um_per_px` | | histoloji (isteğe bağlı) |
| `qc_status` | enum | PASS/WARNING/FAIL |
| `checksum_sha256` | str | girdi bütünlüğü |

**Z kuralı** (spesifikasyon §3): `z_um(k) = Σ_{r<k} (thickness_r + gap_r)`.
Terimlerden biri `unknown` ise iki kolon tutulur: `z_um` (yalnız ölçülmüş/nominal toplamdan, aksi halde `NaN`)
ve `z_um_assumed` + `z_source = "assumed"`. Model, config'teki `assumed_pitch_um` ile çalışabilir ama
**her çıktı ve raporda "varsayılan" olarak etiketlenir**; tahmin ölçüm gibi gösterilmez.

### D.3 `observations` tablosu (AnnData `obs`; spot başına)

| Alan | Tür | Not |
|---|---|---|
| `spot_id` (index), `sample_id`, `section_id` | str | |
| `x_raw`, `y_raw` | float | platform koordinatı (µm'ye çevrilmiş; ölçek `sections`'ta) |
| `x_registered`, `y_registered` | float | ortak çerçevede |
| `z_um` , `z_is_assumed` | float, bool | |
| `registration_confidence` | float [0,1] | spot-başına, ham (kalibre edilmiş ayrı kolon: `…_calibrated`) |
| `overlap_up`, `overlap_down` | float [0,1] | komşu kesitte doku karşılığı olasılığı (null kütlesinin tümleyeni) |
| `in_tissue` | bool | |
| `n_counts`, `n_genes`, `pct_mt` | | QC |
| `histology_embedding_key` | str\|null | `obsm['X_hist']` varsa |

`X` (ham sayım), `layers['norm']`, `obsm['X_pca']`, `obsm['X_hist']`, `obsm['celltype_proportions']`,
`obsm['spatial_raw']`, `obsm['spatial_registered']` (x,y), `obs['z_um']`.
**Section kimliği hiçbir `obsm` özellik matrisine girmez** (bkz. §E.7).

### D.4 Kenar şeması (tipli graf)

Tek graf, üç ilişki tipi (kaynak → hedef; Z yönleri **hedefin perspektifinden**: `zup` = hedef düğümün
üst kesitindeki kaynaklar). Her ilişki ayrı Parquet tablosu + PyG `HeteroData` karşılığı.

| Sütun | XY | Zup | Zdown | Not |
|---|---|---|---|---|
| `source`, `target`, `edge_type` | ✓ | ✓ | ✓ | `edge_type ∈ {xy, zup, zdown}` |
| `distance_xy`, `distance_z`, `distance_3d` (µm) | ✓ | ✓ | ✓ | `distance_z` Z kenarlarında `Δz` |
| `expression_similarity` | ✓ | ✓ | ✓ | PCA kosinüs veya korelasyon (config) |
| `morphology_similarity` | – | ✓ | ✓ | histoloji yoksa `NaN` + maske |
| `registration_confidence` | – | ✓ | ✓ | kesit çifti + yerel (`C_reg`) |
| `correspondence_probability` | – | ✓ | ✓ | `p_corr(i→j)`; null kütlesi ayrı alanda |
| `null_probability` | – | ✓ | ✓ | düğüm düzeyi (aynı değer o düğümün Z satırlarında tekrarlanır) |
| `boundary_probability` | ✓ | ✓ | ✓ | `b_ij` (v0.1: deterministik) |
| `boundary_channels` | ✓ | ✓ | ✓ | `b`'yi oluşturan kanallar (yorumlanabilirlik) |
| `final_edge_weight` | ✓ | ✓ | ✓ | modele girmeden önceki ön-ağırlık |

Her kenar tablosu bir `graph_params` karması taşır (§D.6). Eksik kesit durumunda kenar,
fiziksel olarak en yakın **mevcut** kesite kurulur ve `distance_z` gerçek Δz'dir.

### D.5 Proje çıktı dizini

```
project/
├─ input/            kaynak dosya referansları + checksum (veri kopyalanmaz)
├─ registration/     transform.json (kesit çifti başına parametre + metrik), warp alanı (varsa), qc.json
├─ graph/            xy.parquet, zup.parquet, zdown.parquet, graph_params.json
├─ embeddings/       embeddings.parquet|zarr, model.pt, training_log.json
├─ domains/          domains.parquet (domain_id, domain_probability, boundary_probability, transition_score, uncertainty_*)
├─ niches/  interactions/  boundaries/      (Faz 11–14)
├─ figures/
├─ report/
└─ manifest.json
```

### D.6 `manifest.json` (provenance; spesifikasyon §26)

```json
{
  "run_id": "SC-2026-000184",
  "timestamp_utc": "...",
  "software": {"spatialcore": "0.1.0", "git_commit": "...", "python": "...", "torch": "...", "pyg": "..."},
  "tissue_package": {"id": "gbm", "version": "1.0.0", "unreviewed_licenses": ["ivygap_2018"]},
  "model": {"name": "zbridge", "version": "0.1.0", "config_sha256": "...", "seed": 0, "checkpoint_sha256": "..."},
  "inputs": [{"section_id": "s01", "path": "...", "sha256": "..."}],
  "z": {"mode": "measured|assumed|mixed", "assumed_pitch_um": null},
  "registration": {"method": "rigid+affine/soft-correspondence", "params_sha256": "...", "pair_metrics": "registration/qc.json"},
  "graph": {"xy": {...}, "z": {...}, "params_sha256": "..."},
  "reference_databases": [{"name": "...", "version": "...", "license": "...", "sha256": "..."}],
  "determinism": {"torch_deterministic": true, "notes": "..."}
}
```

---

## E. Z-BRIDGE v0.1 Teknik Tasarımı

Notasyon: spot `i`, kesit `k(i)`, özellik `h_i ∈ R^d`. Tüm sabitler `config/defaults/*.yaml`'dadır
(tipli şema ile doğrulanır); kodda sihirli sayı yok. Her varsayılan **"varsayım"** olarak işaretlenir ve
manifest'e yazılır.

### E.1 Registration (Faz 3; non-rigid Faz 13)

Girdi: komşu kesit çifti `(k, k+1)`: spot koordinatları, `X_pca` (kesit-başı normalize), isteğe bağlı histoloji.

1. **Rigid + affine, yumuşak eşleşmeli.** Gauss-karışım/EM tipi (CPD benzeri) hizalama: her `i` için
   komşu kesitteki adaylar üzerinde posterior `P(j|i)`; olasılığı **expression benzerliği ile ağırlıklı**
   (koordinat + ifade ortak olabilirlik). Böylece registration'ın yan ürünü olarak **soft correspondence**
   elde edilir (E.2'nin tohumu).
   - Aşamalar: (i) merkez/ölçek ön-uyum, (ii) rigid (R,t), (iii) affine (ölçek, kayma).
   - **Lisans notu:** PASTE (GPL-3, doğrulanmalı) bağımlılık olarak eklenmez; EM/OT'yi kendimiz yazarız
     (OT için POT, MIT, isteğe bağlı bağımlılık). PASTE yalnız **kıyas** için ayrı süreçte çalıştırılabilir.
2. **Histoloji (opsiyonel, Faz 7+):** `registration/histology_align.py` arayüzü; ilk sürümde yok.
   Varsa kaba rigid için görüntü tabanlı başlangıç; sonuç yine EM ile ince ayar.
3. **Zincirleme:** çiftlerden global poz; **belirsizlik birikir** (`chain.py`): `σ_reg(k)² = Σ σ_pair²`
   (bağımsız hata varsayımı — ilk yaklaşım, ölçülüp doğrulanır).
4. **Registration güveni** (`registration_confidence`), spot başına, şu sinyallerden:
   posterior entropisi/null kütlesi, hizalama sonrası ifade uyumu (komşu kesitte kosinüs),
   örtüşme oranı, uygulanan deformasyon büyüklüğü. Ham skor sentetik ground truth üzerinde
   **kalibre edilir** (güvenilirlik diyagramı); kalibre edilmiş kolon ayrı tutulur.
5. **Çıktı:** `x_registered, y_registered, z_um`, `registration_confidence`, çift-başına `transform.json`.

### E.2 Olasılıksal Z-correspondence (Faz 5)

Spot `i` (kesit k) için komşu kesit `k' ∈ {k−1, k+1}` aday kümesi `C(i)` (yarıçap + top-M).

```
logit(i→j) = − d_xy(i,j)² / (2 σ_ij²)  +  λ_e · S_expr(i,j)  +  λ_h · S_hist(i,j)      (λ_h = 0 histoloji yoksa)
σ_ij² = σ_reg(k,k')² + σ_spot²                       # registration belirsizliği + spot boyu
p(i→j) = softmax over {C(i) ∪ null}                  # null logit'i: b0 (config), tissue kaybı/örtüşme dışı
p_null(i) = softmax kütlesinin null payı;   c_i^{k'} = 1 − p_null(i)
```

- **Kenar güveni** `c_ij = C_reg(k,k') · p(i→j)/max_j p(i→j)` yerine daha basit ve açıklanabilir:
  Z kenar ağırlığı **`w_ij = p(i→j) · C_reg(i) · exp(−Δz/τ)`** (spesifikasyondaki
  `f(d3D, S_expr, S_hist, C_reg, Δz)`'nin v0.1 deterministik hali). `τ` parametrik, "biyolojik gerçek" değil.
- **Eksik kesit:** `k'` yerine "k yönündeki en yakın mevcut kesit"; `Δz` gerçek mesafe → `exp(−Δz/τ)` otomatik küçülür;
  `Δz > Δz_max` ise Z kenarı kurulmaz (null).
- Her `i` için en çok `M_z` (varsayılan 6, varsayım) Z komşusu; olasılıklar yeniden normalize edilmez
  (null kütlesi bilgidir). `p`'ler ayrıca kaydedilir (yorumlanabilirlik, D.4).
- **Yönsellik:** `zup(i)` ve `zdown(j)` ayrı tablolar; simetri zorlanmaz (kesit sınırlarında farklı).

### E.3 XY graf (Faz 4)

Mevcut `contacts`/`diffuses` mantığı korunur (adaptif K, medyan-NN ölçeği, RBF mesafe kodu) fakat
**kesit-başına** kurulur ve µm cinsinden ifade edilir. Aynı kesitte `distance_z = 0`.
v0.1'de çok-ölçekli (`local/microenv/extended`) yok; tek `local` graf. Çok-ölçek, ablasyon fayda
gösterirse `graph/multiscale.py` olarak eklenir.

### E.4 Sınır olasılığı `b_ij` (v0.1: deterministik, çok kanallı)

Her kenar için, kenarın **kendi uç noktalarından bağımsız** (model çıktısına bağlı olmayan) kanallar:

| Kanal | Tanım |
|---|---|
| `expr_gradient` | `‖z_i − z_j‖ / s_i` — `z` kesit-başı normalize PCA, `s_i` düğümün yerel ölçeği (komşu mesafelerinin medyanı); **yerel ölçeğe bölünür**, böylece gürültülü bölgeler sistematik sınır sayılmaz |
| `composition_change` | hücre tipi oranı vektörleri arası Jensen–Shannon |
| `morphology_change` | histoloji varsa, yoksa maske |
| `neighborhood_disagreement` | `i` ve `j`'nin komşuluk **kompozisyon** (komşu ortalamaları) farkı |
| `spatial_consistency` | kenarın bulunduğu yerel doku içinde tutarlılık: sınır komşu kenarlarda da yüksekse (çizgisel süreklilik) artar, izole tekil yüksek gradyan (gürültü) azalır |

`b_ij = σ( Σ_c w_c · normalize(channel_c) + bias )`, `w_c` config'te (varsayım), sonra
**sentetik fantom ve (varsa) etiketli veride kalibre** edilir. Bu, spesifikasyonun "yalnız ekspresyon
farkından oluşmasın" şartını karşılar. Öğrenilen artık (`b̃_ij = b_ij + MLP(·)`) **v0.2** ve yalnız
ablasyon (G, A.4) fayda gösterirse; kollaps önlemi: `b`'ye **stop-gradient** konsistensi kaybında,
`b` ortalamasına **bütçe** regülarizasyonu.

### E.5 Mesaj geçişi (Faz 6–8)

Tek katman (`ZBridgeLayer`), ilişki başına **ayrı** `W` (en azından `W_XY ≠ W_Zup ≠ W_Zdown`; `tie_z: true`
seçeneği ablasyon içindir):

```
m_i^XY   = Σ_{j∈N_XY(i)}  α_ij · (1 − b_ij) · W_XY h_j
m_i^up   = Σ_{j∈N_Zup(i)} β_ij^up · (1 − b_ij) · W_Zup h_j
m_i^down = Σ_{j∈N_Zdown(i)} β_ij^down · (1 − b_ij) · W_Zdown h_j
h_i^{l+1} = LayerNorm( h_i + σ( W_0 h_i + m_i^XY + g_i^up · m_i^up + g_i^down · m_i^down ) )
```

Spesifikasyon §41'den **farklar** (gerekçe §0/§I):

- `α_ij = softmax_j( a_XY(h_i, h_j, e_ij) )` (GATv2 tarzı).
- `β_ij = softmax_j( a_Z(h_i, h_j, e_ij) + log w_ij^{prior} )`, `w^{prior}` = E.2 ağırlığı → correspondence
  **Bayesçi önsel** olarak attention'a girer; ayrıca `c_ij` çarpanı **yok** (çift sayım yok).
  Null kütlesi doğal olarak `g_i`'ye akar.
- Artık bağlantı + LayerNorm (aşırı pürüzsüzleşme, §H).
- Katman sayısı küçük (2, config); `W_0` kendi bilgisini korur.
- Z mesajı yalnız **Z kenarı olan düğümlerde** hesaplanır; yoksa terim tam sıfır (bkz. E.10).

**Z kapısı** `g_i^{up/down} ∈ [0,1]`: **kenar başına değil düğüm başına özet** girdilerinden:

```
g_i^dir = σ( MLP([ c̄_i^dir, p_null,i^dir, overlap_i^dir, C_reg,i^dir,
                   cos(h_i, ĥ_i^dir) (içerik tutarlılığı), entropy(β_i^dir), expr_consistency_i^dir ]) )
```

`ĥ_i^dir` = o yöndeki Z komşularının β-ağırlıklı ortalaması. Girdilerde **section_id/order yok** (E.7).
"upper 0.93 / lower 0.21" örneği: `g^up` yüksek, `g^down` düşük — bu **test edilir** (G, model/).

### E.6 Belirsizlik (ayrı ayrı)

| Tür | Kaynak | Çıktı |
|---|---|---|
| **registration uncertainty** | `1 − registration_confidence`, `p_null`, Z `β` entropisi | `unc_registration` |
| **classification uncertainty** | domain olasılığı entropisi (+ MC-dropout varyansı) | `unc_domain` |
| **boundary uncertainty** | `b` kanalları arası uyumsuzluk + komşu `b` varyansı | `unc_boundary` |

`transition_score_i` = `b` ortalaması (düğüm çevresi) ile **ikinci en olası domain olasılığı** birleşimi
(iki domain birbirine yakınsa ve çevre sınırlıysa yüksek). Etiketler: `stable` / `transition` /
`boundary` / `uncertain` — **eşikler config'te, kalibrasyon verisinden** seçilir; sihirli sayı değil.
Kalibrasyon hatası (ECE) rapora yazılır.

### E.7 Düğüm özellikleri ve sızıntı önleme

Özellik = kesit-başı normalize PCA(ifade) ⊕ (varsa) histoloji embedding ⊕ hücre tipi oranları ⊕ yerel yoğunluk.
**Section kimliği/sırası/`z_um` özellik OLARAK GİRMEZ.** (`z` yalnız kenar özelliği `Δz` olarak girer.)
Önlemler: kesit-başı kütüphane büyüklüğü/log normalizasyonu; isteğe bağlı kesit-ortalaması çıkarma
(Harmony tarzı **tam** harmonizasyon uygulanmaz — gerçek Z varyasyonunu silebilir); **probe testi**:
embedding'den section kimliğini tahmin eden doğrusal sınıflandırıcı, uzamsal olarak anlamlı olandan fazlasını
tahmin edememeli (G.model).

### E.8 Eğitim hedefleri (ablasyonlu, minimal)

```
L = λ_rec · L_rec  +  λ_cons · L_cons   (v0.1)
    + λ_dom · L_dom                     (paket imzalarından zayıf denetim, isteğe bağlı)
L_rec  = maskelenmiş gen/PCA yeniden kurma (düğümün kendisi gizlenir; komşulardan tahmin → mesaj geçişini zorunlu kılar)
L_cons = Σ_{(i,j)∈E_z} w_ij · (1 − sg(b_ij)) · ‖h_i − h_j‖²           (sg = stop-gradient)
```

DGI/contrastive/neighbor-prediction ve PCGrad/Kendall **ilk sürümde yok**; ablasyon koşucusu (G) ile tek tek
eklenir. Domain çıkarımı: gömme üzerinde kümeleme (GMM → olasılık) **eğitim hedefinden ayrı**; böylece
"etiketle eğit, etiketle test et" çembersizliği azalır.

### E.9 Çıktılar

`embeddings.parquet` (`h_i`, boyut config), `domains.parquet`:
`domain_id`, `domain_probability` (vektör), `boundary_probability` (düğüm), `transition_score`,
`unc_registration/unc_domain/unc_boundary`, `state ∈ {stable,transition,boundary,uncertain}`;
kenar düzeyinde `b_ij`, `β_ij`, `g_i` dökümü (yorumlanabilirlik: "bu spot neden üst kesite güvendi?").

### E.10 Tek kesit geriye uyumluluğu

`n_sections = 1` ⇒ `E_zup = E_zdown = ∅` ⇒ `m^up = m^down = 0` **tam sıfır** (maskeli toplama), kapılar
hesaplanmaz. Model, aynı sınıf, aynı kod: **"Z-edge'siz özel durum"**. Bu şu testle korunur: aynı ağırlıklarla
Z'li modelin Z kenarı boş girdideki çıktısı XY-only modelin çıktısına **bit-bit** eşit (G.model).
Arayüzde "2B Analiz / 3B Çok-kesit" iki mod görünür; backend tek motor.

### E.11 Hesaplama bütçesi (kaba)

5 kesit × ~4 000 spot = 20 000 düğüm; XY ≈ 8 komşu → ~160 k kenar; Z ≈ 2 yön × 6 → ~240 k kenar;
hidden 64, 2 katman: CPU'da dakikalar mertebesi, <2 GB RAM (ölçülecek). Visium HD / hücre-çözünürlüklü
veride düğüm sayısı katlanır → **mini-batch alt-graf örnekleme** ve bin'leme Faz 9+ riski (§H).

---

## F. Uygulama Sırası (dosya dosya)

Yeşil = bu dalda zaten yapıldı. Her adım: **(1) mevcut koda bak → (2) bağımlılık → (3) küçük değişiklik
→ (4) test → (5) uygula → (6) sentetikte çalıştır → (7) gerçekte doğrula → (8) regresyon.**

**Faz 0 ✓ (yapıldı)** spekülatif çıktıların silinmesi, doku paketi (`tissue_pack.py`, `tissue_packs/gbm`),
sentetik GNN smoke testi, CI, TLS/pandas düzeltmeleri.

**Faz 1 — GBM'yi ayırma ve paket iskeleti** (spesifikasyon Faz 1)
1. `pyproject.toml`, `spatialcore/__init__.py`, `config/schema.py` (pydantic), `config/defaults/*.yaml`.
2. `tissue_pack.py` → `spatialcore/tissues/loader.py` (+ `tissues/gbm`); eski yol için ince uyumluluk köprüsü.
3. `LR_PAIRS` ve `get_coarse_group`/`niche_cols` → paket/config (`tissues/gbm/interactions.yaml`, `markers.yaml`).
4. `locale_logger` kaldırma planı (yapılandırılmış log).
   *Test:* mevcut 46 test + GBM imza snapshot; paket doğrulama testleri.

**Faz 2 — Çok-kesitli veri modeli**
5. `data/schema.py`, `data/sections.py`, `data/volume.py` (`VolumeSet`, `z_um` kuralı, `thickness_source`).
6. `data/checksums.py`, `provenance/manifest.py` (manifest iskeleti).
7. `io/visium.py`, `io/volume_io.py`: tek kesit ve N kesit yükleme; mevcut stage1 mantığı çağrılır.
   *Test:* 1/2/10 kesit; bilinmeyen kalınlık; fiziksel sıra ≠ dosya sırası; `z_um` birim testleri.

**Faz 2b — Sentetik 3B fantom (registration'dan ÖNCE)**
8. `synthetic/phantom.py` (tümör küresi + bağışıklık kabuğu + damar kanalı; ifade profilleri),
   `synthetic/deform.py` (döndürme, öteleme, ölçek, kayma, esnek bükülme, kısmi örtüşme, doku kaybı),
   `synthetic/sectioning.py` (Visium benzeri örgü, kalınlık/boşluk, kesit eksikliği).
   *Test:* ground truth (dönüşüm, kesit-spot yazışması, domain/sınır etiketi) tam çıkar.

**Faz 3 — Rigid + affine registration**
9. `registration/soft_correspondence.py`, `rigid.py`, `affine.py`, `confidence.py`, `chain.py`.
10. `qc/pairwise.py` (PASS/WARNING/FAIL).
    *Test:* fantomda dönme <1°, öteleme <0,25×spot aralığı, ölçek hatası <%2 (eşikler config);
    güven kalibrasyonu; kısmi örtüşmede null kütlesi artar; bozuk kesit FAIL.

**Faz 4 — XY graf**
11. `graph/xy_graph.py` (`build_graph_data`'dan çıkarma), `graph/typed_graph.py` (Parquet + HeteroData).
    *Test:* eski grafla **eşdeğerlik** (aynı kenar kümesi), kesit-başı bağımsızlık.

**Faz 5 — Olasılıksal Z grafı**
12. `graph/correspondence.py`, `graph/z_graph.py`, `graph/boundary_features.py`.
    *Test:* olasılıklar ≤1 ve null ile toplam=1; `Δz` arttıkça ağırlık monoton azalır; eksik kesit
    atlama; "tüm kenarlar aynı sütuna gider" dejenerelik kontrolü; `b` kanalları fantom sınırında yüksek.

**Faz 6 — Z-BRIDGE mesaj geçişi**
13. `model/zbridge.py`, `model/heads.py`, `model/losses.py`, `model/trainer.py` (tohum/determinizm).
    *Test:* şekil/permütasyon eşdeğerliği; Z-boş girdi = XY-only (bit-bit); gradyan akışı; 2 adım overfit.

**Faz 7 — Registration-güven kapısı**
14. `model/gates.py`. *Test:* `C_reg` yüksek/düşük sentetik durumda `g^up`>`g^down`.

**Faz 8 — Sınır kapısı**
15. `model/boundary.py` (+ konsistens kaybında stop-gradient). *Test:* fantomda sınırlar boyunca mesaj
    ağırlığı düşer; `L_cons` `b→1` ile kollabe olmaz.

**Faz 9 — 3B domain tespiti + belirsizlik**
16. `analysis/domains/*`, `model/uncertainty.py`, `benchmarks/ablation_runner.py` (§G'deki 7 konfigürasyon).
    *Test:* fantomda ARI/NMI/Dice/sınır doğruluğu ve **ablasyon sırası** (XY-only < +Z < +güven < +kapı < +sınır);
    ECE; section-probe.
17. **Gerçek veri doğrulaması:** halka açık çok-kesitli Visium (aday: spatialLIBD/DLPFC — her denekte yan yana
    kesit çiftleri ve daha uzak çiftler, katman etiketleri; **kesit aralıklarını yayından doğrula**);
    hasta etiketi eğitime girmez.

**→ MVP kapısı (spesifikasyon §38):** 3 seri Visium kesiti → içe aktar → QC → registration → 3B koordinat →
XY+Z kenarları → Z-BRIDGE → 3B embedding → 3B domain → etkileşimli görünüm.

**Faz 10 — 3B görselleştirme** `visualization/viewer_3d` (veri sözleşmesi: tipli "view bundle"),
`renderer`: `app-spatial-3d.js` değiştirilir (kesit gizleme, domain/ifade/belirsizlik, kenar katmanı).
**Faz 11 — 3B niş** `analysis/niches` (3B komşuluk kompozisyonu; kesit-aşırı).
**Faz 12 — 3B L-R** `analysis/ligand_receptor` (`E(L_i)·E(R_j)·K(d_3D)·C_ij`; permütasyon null; "aday etkileşim" dili).
**Faz 13 — Non-rigid** `registration/nonrigid.py` (düzgünlük düzenlemeli yer değiştirme alanı; folding/tearing için maske).
**Faz 14 — Geçiş/sınır biyolojisi** `analysis/boundaries` (yüzey, signed distance, geçiş gen programları, 3B nesne takibi).

Her fazın sonunda: CLI komutu + `manifest.json` + küçük rapor bölümü (böylece "çalışan dilim" her an var).

---

## G. Test Planı

**Genel ilke:** sentetik veri **yalnızca mühendislik/algoritma doğrulaması**dır; biyolojik kanıt olarak
sunulmaz (raporlarda da). Her faz, bir önceki fazın tüm testleri geçerken biter. Sayısal eşikler başlangıç
hedefidir, `config`'te ve fantom kalibrasyonuyla netleşir.

| Katman | Test | Geçme ölçütü |
|---|---|---|
| **unit/data** | `z_um` kuralı; bilinmeyen kalınlık; sıra ≠ dosya sırası | `z_um = Σ(thickness+gap)`; `unknown` → `NaN` + `z_is_assumed` |
| **unit/data** | checksum, manifest tekrar üretimi | aynı girdi + tohum → aynı `manifest` (zaman damgası hariç) |
| **registration** | döndürme/öteleme/ölçek/kayma | <1° / <0,25 spot aralığı / <%2 / <%3 |
| **registration** | kısmi örtüşme, doku kaybı, hasarlı kesit | `p_null` artar; çift `WARNING/FAIL`; çökme yok |
| **registration** | non-rigid (Faz 13) | yerel hata < spot aralığı; katlanma maskesi |
| **registration** | güven kalibrasyonu | güvenilirlik diyagramı eğimi ≈ 1 (ECE ≤ eşik) |
| **graph** | XY eşdeğerliği | eski `build_graph_data` ile aynı kenar kümesi |
| **graph** | Z olasılıkları | satır toplamı (null dahil)=1; `Δz`↑ ⇒ ağırlık↓ monoton |
| **graph** | eksik kesit / eşit olmayan kalınlık | Z kenarı gerçek Δz ile; `Δz>Δz_max` ⇒ kenar yok |
| **graph** | 1 / 2 / 10 kesit | 1 kesit ⇒ Z kenarı 0; 2 kesit ⇒ tek yönlü uçlar doğru; 10 ⇒ ölçek |
| **graph** | sınır özellikleri | fantom sınırında `b` yüksek, iç bölgede düşük (AUC ≥ eşik) |
| **model** | tek kesit parite | Z-boş girdi çıktısı XY-only ile **bit-bit** aynı |
| **model** | yapı | `W_XY, W_Zup, W_Zdown` bağımsız parametre; `tie_z` ablasyonu |
| **model** | kapı davranışı | `C_reg` yüksek/düşük ⇒ `g^up>g^down` |
| **model** | sınır kapısı | sınır kenarlarında efektif mesaj ağırlığı düşer; `L_cons` kollabe olmaz |
| **model** | section-probe | embedding'den section tahmini ≤ (uzamsal tabanlı) + marj |
| **model** | determinizm | aynı tohum ⇒ aynı gömme (CPU) |
| **integration** | 3 kesit fantom uçtan uca | domain ARI/Dice/sınır doğruluğu eşiği; manifest tam |
| **integration** | eksik kesit / 10 kesit | çökmeden; sonuçlar beklenen yönde bozulur |
| **regression** | GBM 2B çıktısı | imza snapshot + sentetik smoke (mevcut) + 2B Z-BRIDGE ≥ legacy |
| **benchmark** | **ablasyon (7 konfigürasyon)** | 2B XY-only · 3B naif bitişiklik · XY+Z · +kayıt güveni · +uyarlanır Z kapısı · +sınır kapısı · tam Z-BRIDGE; her biri için ARI, NMI, Dice, IoU, F1, uzamsal tutarlılık, kesit-arası tutarlılık, sınır doğruluğu, kalibrasyon hatası, süre/bellek |
| **UI/CI** | headless smoke (mevcut betik CI'ya) | tüm paneller/modlar konsol hatasız |

**Gerçek veri doğrulama kuralı:** bağımsız anotasyon (histolojik/anatomik katman) eğitimde görülmez;
bölme hasta/denek düzeyinde; sonuç ablasyon tablosu olarak raporlanır, tek sayı olarak değil.

---

## H. Risk Kaydı

Olasılık/etki: D=düşük, O=orta, Y=yüksek.

| # | Risk | O | E | Azaltma | Tespit |
|---|---|---|---|---|---|
| 1 | **Registration hatası** (yanlış hizalama Z kenarlarını anlamsızlaştırır) | Y | Y | soft correspondence + null; güven; kalibrasyon; çift başına QC FAIL ⇒ Z kapalı | `registration/qc.json`, güvenilirlik diyagramı |
| 2 | **Yanlış Z eşleşmesi** (bitişik ama biyolojik olarak farklı doku) | Y | Y | `b` kapısı; ifade/histoloji terimi; `β` entropisi; `g` | fantomda yanlış eşleşme oranı; `L_cons` yüksek |
| 3 | **Batch etkisi / kesit-arası teknik fark** | Y | Y | kesit-başı normalizasyon; **tam** harmonizasyon yok; section-probe | probe skoru, kesit-ortalaması farkı |
| 4 | **Kesit artefaktları** (kıvrım, yırtık, boya, kenar) | O | O | `qc/per_section`; maske; non-rigid'de katlanma tespiti | QC raporu, `warp_magnitude` |
| 5 | **Aşırı pürüzsüzleştirme** (3B komşuluk daha fazla ortalama) | Y | Y | artık bağlantı, 2 katman, `b` kapısı, `L_cons` bütçesi; ablasyon | embedding uzaklık dağılımı, sınır keskinliği metriği |
| 6 | **Section kimliği ezberi** | O | Y | kimlik özelliği yok; probe; kenar-özelliği olarak yalnız `Δz` | probe |
| 7 | **`b` kollapsı / tanımsızlık** | O | Y | v0.1 deterministik; stop-gradient; bütçe regülarizasyonu | `mean(b)` izleme |
| 8 | **Seyrek veri / düşük UMI** | Y | O | PCA/HVG; kesit-başı QC eşiği; `unc_*`'a yansır | `n_counts` dağılımı, QC |
| 9 | **Doku deformasyonu** (rigid/affine yetmez) | Y | O | Faz 13 non-rigid; o zamana kadar güven düşer ve belirsizlik artar | kalıntı hata haritası |
| 10 | **Bilinmeyen kalınlık/aralık** | Y | O | `unknown` açık kayıt; `assumed` etiketi; `τ` duyarlılık analizi | manifest `z.mode` |
| 11 | **GPU/RAM sınırı** (Visium HD, hücre çözünürlüğü) | O | Y | alt-graf örnekleme, bin'leme, CPU yolu; bütçe testi | bellek benchmark'ı |
| 12 | **Doğrulama verisi yetersizliği** | Y | Y | fantom (kanıt değil) + halka açık çok-kesitli set(ler) + ablasyon; iddiaları buna göre sınırla | benchmark kapsamı |
| 13 | **Aşırı mühendislik / kapsam şişmesi** | Y | Y | her modül için "hangi problemi çözüyor?" ablasyonu; fayda yoksa çıkar | ablasyon tablosu |
| 14 | **Lisans** (PASTE GPL, KEGG, Ivy, görüntü kodlayıcı ağırlıkları) | O | Y | bağımlılık taraması; kendi EM; `needs_review` bayrağı manifestte | lisans tarama çıktısı |
| 15 | **Tek kişi kapasitesi** | Y | Y | MVP = Faz 1–9; 10–14 sonra; haftalık dilim | takvim sapması |
| 16 | **Yoruma aşırı güven** (3B görsel "ikna edici") | O | Y | RUO; belirsizlik katmanı varsayılan açık; "aday etkileşim" dili | rapor incelemesi |

---

## I. Spesifikasyondan Sapmalar ve Açık Kararlar

**Bilerek farklı yaptıklarım** (hepsi geri alınabilir; gerekçe yukarıda):

| Spesifikasyon | v0.1'de | Neden |
|---|---|---|
| `b_ij` öğrenilir (§9) | deterministik çok-kanallı; öğrenilen artık v0.2 | etiketsiz öğrenmede tanımsız/kollaps (E.4) |
| `c_ij` ve `β_ij` birlikte (§41) | `β`'nin logit'ine log-prior | çift sayım; ablasyon temizliği |
| Gate: "çok sinyal" (§8) | düğüm-başı özet istatistikler | kenar-başı kapı pahalı ve aşırı serbest |
| Histoloji encoder (§15) | arayüz + "none"; gerçek kodlayıcı Faz 7+ | önce histolojisiz ablasyon; bağımlılık/lisans |
| Multi-scale (§13) | yok (tek `local`) | spesifikasyonun kendisi MVP'yi karmaşıklaştırma diyor |
| L-R / niş / sınır yüzeyi / geçiş programları (§17–20) | Faz 10 sonrası | MVP kapısı §38 |
| Tüm kayıplar (§31) | `L_rec + L_cons` (+ isteğe bağlı `L_dom`) | ablasyonla eklenir |

**Önceki yol haritasıyla çatışmalar** (kararın senin):
1. `ROADMAP.md` "3B MVP sonrası" diyordu; artık 3B çekirdek. **Önerim:** ROADMAP'i bu belgeye göre güncelle.
2. ROADMAP "tek önceden eğitilmiş GNN" diyordu. Z-BRIDGE v0.1 **örnek-başına küçük eğitim**dir
   (kendi öz-denetimli hedefiyle). Önceden eğitme, Z-BRIDGE ablasyonunda değer kanıtlandıktan sonra.
3. Ürün adı/paket adı: `spatialcore` kullandım; "Z-BRIDGE" algoritma adıdır, ürün adı değil.

**Senden gereken kararlar (kod öncesi):**
1. Paket konumu: kök `spatialcore/` + `python_backend/` adaptör (öneri) — onay?
2. Halka açık çok-kesitli doğrulama veri seti(leri): hangileri? (kesit aralıklarını yayından birlikte doğrularız.)
   Elinde senin/laboratuvar çok-kesitli Visium var mı?
3. Histoloji: v0.1'de yok mu (öneri), yoksa en baştan zorunlu mu?
4. Fantom için hedef sertlik (deformasyon büyüklüğü, doku kaybı oranı) — başlangıç değerlerini ben önereyim mi?
5. Z-BRIDGE yayın hedefi var mı? (varsa benchmark/ablasyon protokolünü hakem gözüyle baştan sabitleriz)
6. Faz 1'e (GBM ayırma + paket iskeleti) hemen başlayayım mı? (Z kodu yazmadan, sadece iskelet/veri modeli.)
