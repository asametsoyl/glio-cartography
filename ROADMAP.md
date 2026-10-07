# Yol Haritası: Glio-Cartography → Genel Spatial Transkriptomik Platformu

Durum: Ürünleşme öncesi teknik ve ticari yol haritası
Başlangıç sürümü: `v3.2.12`
Geçiş etiketi: `v3.2.12-gbm-legacy`
Yeni ürün hattı: `SpatialCore` çalışma adı
Ana hedef: Tek kişilik geliştirme kapasitesiyle 6 ay içinde araştırma laboratuvarlarına ücretli analiz/pilot sunabilecek, dokudan bağımsız ve doğrulanabilir bir spatial transkriptomik analiz platformu geliştirmek.

## 0. Ürün vizyonu

### 0.1 Problem

Spatial transkriptomik verilerinin analizi şu anda:

* çok sayıda farklı araç gerektiriyor,
* ciddi biyoinformatik uzmanlığı istiyor,
* platformdan platforma değişen veri formatları içeriyor,
* sonuçların yeniden üretilebilirliği zayıf olabiliyor,
* laboratuvarların büyük bölümü analiz pipeline'ını kendileri kurmak zorunda kalıyor,
* sonuçların biyolojik yorumlanması ayrı bir uzmanlık gerektiriyor.

Platformun amacı: Ham veya işlenmiş spatial transkriptomik verisini alıp standartlaştırılmış QC, mekânsal analiz, hücresel kompozisyon, niş analizi, hücre-hücre iletişimi ve raporlama süreçlerini tek bir yeniden üretilebilir pipeline içinde çalıştırmak.

## 1. Ürün sınırı

### Platform ne yapacak?

Çekirdek fonksiyonlar

1. Veri içe aktarma
2. Kalite kontrol
3. Normalizasyon
4. Boyut indirgeme
5. Spatial neighborhood graph oluşturma
6. Spatial domain/region analizi
7. Hücre tipi anotasyonu veya deconvolution
8. Spatial variable gene analizi
9. Niş analizi
10. Ligand–receptor analizi
11. Pathway enrichment
12. Kesitler arası hizalama
13. 3B rekonstrüksiyon
14. Etkileşimli görselleştirme
15. Otomatik raporlama
16. Analiz provenance kaydı

### Platform ne yapmayacak?

İlk ürün sürümünde:

* hastalık prognozu,
* hasta sağkalım tahmini,
* ilaç önerisi,
* tedavi seçimi,
* klinik karar desteği,
* klinik tanı,
* hastaya özgü risk skoru,
* sanal knockout sonucu,
* nedensellik iddiası

bulunmayacaktır.

Ürün: **Research Use Only — RUO** olarak konumlandırılacaktır.

## 2. Mimari hedef

```
┌───────────────────────────────────────────────────────────────┐
│                       USER INTERFACES                         │
│                                                               │
│ Desktop App        CLI               Python API               │
│ Electron/Tauri     spatialcore       import spatialcore       │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                      SPATIALCORE ENGINE                       │
│                                                               │
│ io/                                                           │
│ qc/                                                           │
│ preprocessing/                                                │
│ graph/                                                        │
│ model/                                                        │
│ annotation/                                                   │
│ analysis/                                                     │
│ registration/                                                 │
│ visualization/                                                │
│ report/                                                       │
│ provenance/                                                   │
│ plugins/                                                      │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                        TISSUE PACKAGES                        │
│                                                               │
│ gbm/                                                          │
│ brain/                                                        │
│ breast/                                                       │
│ lung/                                                         │
│ custom/                                                       │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                         DATA LAYER                            │
│                                                               │
│ AnnData / SpatialData                                         │
│ Zarr                                                          │
│ Parquet                                                       │
│ HDF5                                                          │
└───────────────────────────────────────────────────────────────┘
```

## 3. Motorun modüler yapısı

### 3.1 `io/`

Amaç: Farklı spatial platformlarından gelen verileri tek ortak veri modeline dönüştürmek.

İlk destek:

Faz 1
* 10x Visium
* 10x Visium HD

Faz 2
* Xenium
* MERFISH/MERSCOPE
* CosMx

Faz 3
* Slide-seq
* Stereo-seq
* seqFISH
* custom AnnData

Her importer sonunda ortak format `SpatialSample` üretmeli.

```
SpatialSample
 ├── expression_matrix
 ├── genes
 ├── spatial_coordinates
 ├── tissue_image
 ├── metadata
 ├── platform
 ├── segmentation
 ├── morphology_features
 └── provenance
```

## 4. Veri standardizasyonu

Platformun en kritik mimari kararlarından biri: Tüm platform verilerini mümkün olduğunca erken ortak veri modeline çevirmek.

Önerilen temel format:

* AnnData
* SpatialData

Büyük datasetlerde: Zarr

Bu sayede Visium, Xenium veya CosMx arasında analiz katmanının tamamen yeniden yazılması önlenir.

## 5. Kalite kontrol sistemi

QC sadece grafik üretmemeli. Her analizde `QC PASS`, `QC WARNING`, `QC FAIL` seviyesi oluşturulmalı.

Genel
* toplam spot/cell
* median UMI
* median gene count
* mitochondrial fraction
* zero-expression ratio
* library complexity

Spatial
* tissue coverage
* edge artifacts
* outlier regions
* spatial density
* segmentation consistency

Imaging (varsa)
* blur
* tissue folds
* background
* staining artifacts

## 6. QC raporu

```
Sample QC

Cells/spots                 84,341
Median genes                2,184
Median UMIs                 7,832
Median mitochondrial %      4.1

Spatial coverage            PASS
Library complexity          PASS
Segmentation                WARNING
Outlier regions             3 detected
```

QC sonuçları daha sonraki analizlerin güvenilirlik seviyesine bağlanmalı.

## 7. Ön işleme

```
Raw data → QC → Filtering → Normalization → Feature selection
→ Dimensionality reduction → Spatial graph
```

İki çalışma modu:

* **Standard Mode:** Platform parametreleri otomatik seçer.
* **Expert Mode:** Kullanıcı normalization, neighbors, HVG, graph radius, clustering resolution gibi parametreleri değiştirebilir.

## 8. Spatial graph

```
Node = spot/cell
Edge = spatial neighborhood
Feature = gene expression + optional morphology
```

Yöntemler: k-nearest neighbor, radius graph, Delaunay triangulation. Dataset tipine göre otomatik seçim yapılabilir.

## 9. GNN mimarisi

Eski sistem: Her hasta için yeni GNN. Yeni:

```
Pretrained backbone → dataset embedding → lightweight task heads
```

## 10. Pretrained spatial encoder

Amaç: Spot veya hücre için genel spatial embedding üretmek.

```
Gene expression + Spatial coordinates + Neighborhood context
      ↓
Spatial Encoder
      ↓
128-dimensional embedding
```

Backbone adayları: GraphSAGE, GATv2, Graph Transformer. İlk sürüm için GraphSAGE baseline + GATv2 benchmark önerilir.

## 11. Backbone görevleri

Backbone tek bir etiket için eğitilmemeli. Self-supervised görevler:

* **Masked gene prediction:** Bir grup gen maskelenir, model komşu hücrelerden tahmin eder.
* **Graph contrastive learning:** Yakın spatial bölgeler positive pair, uzak bölgeler negative pair.
* **Neighbor prediction:** Model "bu iki hücre spatial olarak komşu mu?" sorusunu öğrenir.

## 12. Task heads

Backbone sabit kalabilir. Üzerine küçük başlıklar eklenebilir: Region classification head, Cell-state head, Niche head, Boundary detection head.

Bu yaklaşım hızlı, düşük GPU gereksinimli ve yeni dokuya adapte edilebilir olur.

## 13. Doku paketleri

Doku bilgisi model koduna gömülmeyecek.

```
tissues/
    gbm/
        tissue.yaml
        regions.yaml
        markers.yaml
        pathways.yaml
        citations.yaml
        report.yaml
```

## 14. Tissue Package şeması

`tissue.yaml`

```
name: Glioblastoma
version: 1.0

species:
  - human

regions:
  - CT
  - LE
  - IT
  - MVP
```

`markers.yaml`

```
cell_types:

  tumor:
    markers:
      - EGFR
      - SOX2
      - OLIG2

  astrocyte:
    markers:
      - GFAP
      - AQP4
```

`citations.yaml` — her imza için:

```
source:
  title:
  doi:
  dataset:
  license:
```

Platform "bu marker nereden geldi?" sorusuna cevap verebilmelidir.

## 15. Kaynak ve lisans sistemi

Her external reference için Source, Version, License, DOI, URL, Retrieved date saklanmalı. Bu provenance raporunun parçası olmalıdır.

## 16. Hücre tipi analizi

* **Imaging-based platformlar** (Xenium/CosMx): `cell → cell type`
* **Spot-based platformlar** (Visium): `spot → cell composition`

```
Tumor       45%
Astrocyte   28%
Microglia   18%
T cell       9%
```

## 17. Annotation confidence

Her anotasyon `label`, `confidence`, `method`, `reference` ile tutulmalı.

```
Cell type: Microglia
Confidence: 0.89
Method: reference mapping
```

## 18. Spatial domain discovery

* **Unsupervised:** Model kendi spatial domainlerini bulur (Domain 1, 2, 3).
* **Reference-guided:** Tissue package kullanılır. GBM örneği: Leading edge, Cellular tumor, Microvascular proliferation.

## 19. Patolog anotasyonu

Ürünün bilimsel güvenilirliği için kritik. Patolog histoloji görüntüsünde bölge işaretler. Platform model region prediction ile pathologist annotation'ı karşılaştırır.

Metrikler: Dice coefficient, IoU, Precision, Recall, F1, AUROC.

## 20. Kör değerlendirme

Training / Validation / Test samples tamamen ayrılmalıdır. Test örneklerinin patolog anotasyonu eğitim sırasında görülmemelidir.

## 21. Cross-dataset validation

Sadece aynı dataset içinde validation yeterli değil.

```
Train: Dataset A, Dataset B
Test:  Dataset C
```

Bu generalizasyon testi ürün açısından çok daha değerlidir.

## 22. Platformlar arası doğrulama

İleri aşamada Visium, Xenium, CosMx arasında ortak biyolojik sinyaller karşılaştırılabilir. Bu 6 aylık MVP şartı değildir.

## 23. Niş analizi

Niş: belirli hücrelerin belirli spatial komşuluk içinde birlikte bulunması.

```
Niche 1  Tumor + macrophage
Niche 2  Endothelial + pericyte
Niche 3  T cell enriched
```

## 24. Niş istatistikleri

Her niş için: hücre kompozisyonu, marker genes, pathway enrichment, spatial localization, sample frequency.

## 25. Ligand–receptor analizi

Amaç: potansiyel hücre-hücre iletişimlerini göstermek.

Çıktı: Sender, Receiver, Ligand, Receptor, Expression, Spatial proximity, Statistical score.

Önemli: L-R skoru biyolojik etkileşim kanıtı olarak sunulmamalı. Rapor dili: "putative interaction" veya "candidate signaling interaction".

## 26. Spatially constrained L-R

İki hücre popülasyonu spatial olarak yakın değilse skor düşürülmeli.

```
LR_score = expression_score × spatial_proximity
```

Bu platform için değerli bir farklılaştırıcı özellik olabilir.

## 27. Pathway enrichment

Desteklenebilecek kaynaklar: GO, KEGG, Reactome, MSigDB.

```
Region → Differential genes → Pathway enrichment
```

## 28. Spatial differential expression

Normal DE analizinden ayrı olmalı: Region A vs Region B, veya Niche A vs Niche B.

## 29. Spatially variable genes

Platform "hangi genlerin ekspresyonu spatial pattern gösteriyor?" sorusuna cevap vermeli. Sonuç: Gene, Spatial score, FDR, Pattern.

## 30. Spatial boundaries

İleri özellik: Spatial domainler arasındaki sınırlar analiz edilebilir.

```
Tumor core → transition zone → normal tissue
```

Bu bölgelerde differential genes, ligand receptor, pathway analizi yapılabilir.

## 31. 3B modülü

MVP sonrası.

```
Section 1..4 → registration → aligned sections → graph construction → 3D spatial graph
```

## 32. Kesit hizalama

Aşamalı yaklaşım: Stage 1 Rigid, Stage 2 Affine, Stage 3 Non-rigid registration. Histoloji görüntüsü ve spatial expression birlikte kullanılabilir.

## 33. 3B koordinatlar

Her hücre x, y, z koordinatına sahip olur. `z = section index × section thickness` olarak başlanabilir.

## 34. 3B grafik

Node: cell/spot. Edge: intra-section + inter-section.

## 35. 3B görselleştirme

Kullanıcı döndürme, zoom, region filtreleme, cell type filtreleme, gene expression, niche, interaction görebilmeli. Teknik seçenekler: Plotly, PyVista, VTK.

## 36. Görselleştirme standardı

Tüm analizler aynı görsel dili kullanmalı. Her plot: Title, Description, Method, Sample, Parameters, Export içermeli.

## 37. Tek tıklama rapor

Analiz sonunda `Generate Report` butonu. Çıktılar: HTML (interaktif), PDF (paylaşılabilir), Analysis archive (`.zip`).

## 38. Rapor yapısı

1. Executive Summary
2. Dataset
3. Quality Control
4. Spatial Domains
5. Cell Types
6. Spatially Variable Genes
7. Niches
8. Ligand–Receptor Analysis
9. Pathways
10. Validation
11. Methods
12. Provenance

## 39. Provenance

Her analiz için kayıt: Software version, Model version, Tissue package version, Parameters, Input checksum, Reference databases, Date.

```
SpatialCore 0.8.3
GBM package 1.2
Model spatial-encoder-v4
Reactome 2026-09
```

## 40. Reproducibility

Her analiz unique ID almalı (`SC-2026-000184`) ve `analysis_manifest.json` oluşturulmalı.

## 41. Desktop dağıtım

İlk hedef: Desktop application. Spatial transcriptomics verileri çok büyük; birçok laboratuvar veriyi buluta yüklemek istemez, hasta kaynaklı veri kullanabilir, internet hızından etkilenmek istemez. Bu nedenle **local-first architecture**.

## 42. UI teknolojisi

* **Electron:** olgun ekosistem, hızlı geliştirme; eksisi yüksek RAM.
* **Tauri:** daha hafif, düşük RAM; eksisi entegrasyon biraz daha karmaşık.

İlk prototip: Electron kabul edilebilir.

## 43. Python worker

Desktop UI: Electron. Backend: Python spatialcore. İletişim: local REST API veya IPC.

## 44. CLI

Akademik kullanıcı için mutlaka CLI olmalı.

```
spatialcore analyze sample/
spatialcore analyze sample/ --tissue gbm --report
```

## 45. Python API

```
import spatialcore as sc

sample = sc.read_visium("sample/")
result = sc.analyze(sample)

result.plot_domains()
```

Bu akademik benimsenmeyi ciddi artırabilir.

## 46. Plugin sistemi

Uzun vadede plugin architecture eklenmeli (cellchat/, squidpy/, tangram/). Plugin sistemi MVP'ye dahil edilmemeli.

## 47. Benchmark sistemi

Her önemli analiz için benchmark olmalı. Örnek: Spatial domain detection — SpatialCore vs BayesSpace vs SpaGCN vs GraphST. Metrikler: ARI, NMI, spatial coherence, runtime, memory.

## 48. Benchmark datasetleri

İlk paket: Brain (DLPFC), Cancer (GBM), Cancer 2 (Breast cancer). Amaç: modelin tek dokuya bağımlı olmadığını göstermek.

## 49. Runtime benchmark

Her sürümde otomatik test: 10k, 50k, 100k, 500k nodes. Memory ve runtime kaydedilmeli.

## 50. Test sistemi

```
tests/
  unit/
  integration/
  regression/
  benchmark/
```

## 51. Regression test

Yeni sürüm çıktıları eski sürümle karşılaştırılmalı (`expected clusters = 7 ± 1`, `ARI > 0.85`).

## 52. Synthetic test data

Gerçek verinin yanında küçük sentetik dataset: CI pipeline, UI testing, demo için.

## 53. Demo dataset

Uygulamaya `Try Demo Dataset` butonu. Kullanıcı veri indirmeden ürünü görebilmeli.

## 54. Kullanıcı deneyimi

```
New Analysis → Import Dataset → Platform detected → QC
→ Choose analysis → Run → Results → Report
```

## 55. Kullanıcıya analiz parametresi yükü bindirmeme

Default: `Standard Analysis`, tek tuş. Expert seçenekleri `Advanced Settings` altında.

## 56. Hata mesajları

Kötü: `ValueError: dimension mismatch`

İyi:

```
Expression matrix and spatial coordinate table contain different numbers of observations.

Expression matrix: 4,992 spots
Spatial coordinates: 4,987 spots

5 observations could not be matched.
```

## 57. Proje dosyası

```
project/
   input/
   qc/
   results/
   figures/
   report/
   manifest.json
```

## 58. Otomatik checkpoint

Uzun analizler "QC completed / Preprocessing completed / Graph completed" şeklinde checkpoint oluşturmalı. Analiz çökerse baştan başlamamalı.

## 59. Donanım profili

Başlangıçta CPU, RAM, GPU, VRAM, Disk kontrol edilmeli; Recommended mode (CPU / GPU) seçilmeli.

## 60. Model cache

Pretrained modeller `~/.spatialcore/models/` altında, versiyonlu (`spatial-encoder-v1`, `v2`).

## 61. Ticari ürün yapısı

İlk ürün doğrudan SaaS olmamalı.

**Faz 1 — Analysis Service:** Müşteri dataset verir, sen analiz + rapor verirsin. Avantaj: müşteri ihtiyacını öğrenirsin, UI kusurları sorun olmaz, erken gelir.

## 62. Faz 2 — Desktop License

Laboratuvar yazılımı kendi çalıştırır.

## 63. Faz 3 — Institutional license

Üniversite/lab yıllık lisans.

## 64. Faz 4 — Opsiyonel Cloud compute

Büyük analiz: `Send to compute queue`.

## 65. İlk müşteri profili

1. Spatial transkriptomik verisi üretmiş ama analiz kapasitesi sınırlı laboratuvar.
2. Patoloji/onkoloji araştırma grupları.
3. Core facility.
4. Biyoteknoloji şirketleri.

## 66. İlk müşteri görüşmelerinde sorulacaklar

Kod göstermeden önce:

1. Hangi platformu kullanıyorsunuz?
2. Veriyi kim analiz ediyor?
3. Analiz ne kadar sürüyor?
4. En zor adım ne?
5. Hangi çıktıları görmek istiyorsunuz?
6. Hangi araçları kullanıyorsunuz?
7. Hangi aşamada dışarıdan destek alıyorsunuz?
8. Veri paylaşımı konusunda kısıtınız var mı?
9. En çok hangi raporu hazırlamak zaman alıyor?
10. Böyle bir analiz hizmetine bütçe ayırıyor musunuz?

## 67. Ürün metriği

İlk 6 ay için minimum KPI: 20 müşteri görüşmesi, 10 gerçek dataset, 5 aktif tester, 3 pilot proje, 1 ücretli pilot.

İdeal: 30+ müşteri görüşmesi, 15+ gerçek dataset, 5 pilot, 2–3 ücretli müşteri.

## 68. Bilimsel metrikler

Cross-dataset ARI, Domain reproducibility, Annotation accuracy, Runtime, Memory, Failure rate.

## 69. Software telemetry

RUO üründe opsiyonel. Kullanıcının onayıyla anonim metrikler (analysis success/failure, runtime, platform). Gen ekspresyon verisi gönderilmez.

## 70. Güvenlik

Local-first ürün için **No upload by default**. Her network işlemi açıkça gösterilmeli.

## 71. Versiyonlama

Motor `spatialcore 0.1`, UI `spatialdesk 0.1`, Tissue package `gbm-pack 1.0`, Model `encoder-v1` ayrı versiyonlanmalı.

## 72. Legacy sistem

Mevcut Teknofest sistemi `git tag v3.2.12-gbm-legacy` olarak saklanmalı. Yeni branch: `spatialcore-main`.

## 73. Teknik borç temizliği

Silinecek: knockout modülü, drug scoring, TCGA survival/risk, agresif bölge tahmini, tedavi önerisi, GBM hard-coded logic.

Ayrılacak: UI, analysis, model, dataset handling, reporting.

## 74. GBM'nin yeni rolü

GBM artık ürün değil, referans tissue package olacak. `SpatialCore + GBM package` bir GBM analizi yapar; `SpatialCore + Breast package` meme kanseri analizi yapabilir.

## 75. İlk üç doku paketi

* GBM: mevcut bilgi birikimi.
* DLPFC: iyi benchmark ve annotation datasetleri.
* Breast cancer: tümör mikroçevresi açısından güçlü kullanım örneği.

## 76. Altı aylık geliştirme planı

### AY 1 — Motoru ayır
* Hafta 1: legacy tag, repo temizliği, paket mimarisi, test altyapısı
* Hafta 2: Visium importer, ortak data model, AnnData standardizasyonu
* Hafta 3: QC, preprocessing, graph builder
* Hafta 4: CLI prototype

Milestone: Visium dataset → QC → graph → basic clustering → report çalışıyor.

### AY 2 — Temel analiz motoru
* Hafta 5: Spatial domains
* Hafta 6: Cell type annotation
* Hafta 7: Spatially variable genes
* Hafta 8: Pathway enrichment

Milestone: İlk tam uçtan uca genel spatial analiz.

### AY 3 — Niş + L-R + rapor
* Hafta 9: Niche detection
* Hafta 10: Ligand–receptor
* Hafta 11: HTML report
* Hafta 12: PDF report + provenance

Milestone: Müşteriye verilebilir ilk analiz raporu.

### AY 4 — Pretrained encoder
* Hafta 13: Self-supervised dataset hazırlama
* Hafta 14: GraphSAGE baseline
* Hafta 15: GATv2 benchmark
* Hafta 16: Cross-dataset validation

Milestone: Genel spatial embedding modeli.

### AY 5 — Desktop ürün
* Hafta 17: Electron/Tauri shell
* Hafta 18: Dataset import UI
* Hafta 19: Analysis UI
* Hafta 20: Results viewer

Milestone: Non-technical kullanıcı dataset analiz edebiliyor.

### AY 6 — Pilot
* Hafta 21: Tester onboarding
* Hafta 22: Bug fixing
* Hafta 23: Pilot analizler
* Hafta 24: İlk ücretli pilot

## 77. Paralel müşteri geliştirme takvimi

Koddan bağımsız devam etmeli.

* Ay 1: 10 görüşme
* Ay 2: 5 yeni görüşme
* Ay 3: 2–3 gerçek dataset
* Ay 4: beta tester
* Ay 5: pilot teklifleri
* Ay 6: ücretli analiz

## 78. En önemli MVP

6 ay sonunda başarılı ürünün tanımı: Kullanıcı Visium dataset seçer. Platform QC → spatial domains → cell composition → spatial genes → niches → ligand-receptor → pathways çalıştırır. Sonra interactive results + PDF/HTML report üretir. Tüm analiz reproducible, traceable, versioned olur.

## 79. MVP dışı bırakılacaklar

İlk 6 ay için: foundation model, 10+ platform desteği, cloud SaaS, multi-user collaboration, clinical interpretation, AI chatbot, digital twin, drug response, survival prediction, virtual knockout, multi-omics integration, full 3D pathology AI.

## 80. Sonraki ürün hattı

MVP başarılı olursa SpatialCore 1.0 sonrası:

* 1.1 3B reconstruction
* 1.2 Xenium/CosMx
* 1.3 Multi-section graph learning
* 1.4 Spatial proteomics
* 1.5 Multi-omics
* 2.0 Foundation spatial encoder

## 81. Ürünün ana farklılaştırıcıları

1. **Platform bağımsızlık:** Visium / Xenium / CosMx → tek analiz motoru
2. **Local-first:** Veri laboratuvardan çıkmaz.
3. **Reproducibility:** Her sonuç model, parameter, database, version ile kayıtlı.
4. **Tissue packages:** Genel motor + uzman doku bilgisi.

## 82. Uzun vadeli mimari vizyon

```
                    SpatialCore
                        │
        ┌───────────────┼───────────────┐
       GBM           Breast           Brain
        ↓               ↓               ↓
   tissue pack     tissue pack     tissue pack
        └───────────────┬───────────────┘
                 spatial encoder
                        ↓
                  analysis engine
                        ↓
                    reporting
```

Yeni bir doku eklemek yeni yazılım yazmak yerine yeni tissue package hazırlamak haline gelir.

## 83. Ana ürün prensibi

"Model mümkün olduğunca genel, biyolojik bilgi mümkün olduğunca modüler olmalı." Doku bilgisi configuration, reference, signature, annotation katmanlarında tutulmalıdır.

## 84. Ürün başarı kriteri

Üç şey aynı anda doğru olmalı:

* **Bilimsel:** Bağımsız dataset üzerinde doğrulanabilir sonuç.
* **Teknik:** Bir araştırmacı geliştirici yardımı olmadan analiz çalıştırabiliyor.
* **Ticari:** Bir laboratuvar analiz için para ödemeye hazır.

Yalnızca biri sağlanıyorsa henüz ürün oluşmamıştır.

## 85. İlk kritik kararlar

Uygulamaya başlamadan önce netleştirilecek:

* Ana veri modeli: AnnData + SpatialData
* İlk desteklenen platform: Visium
* İkinci platform: Visium HD veya Xenium
* İlk pretrained backbone: GraphSAGE
* Desktop framework: Electron veya Tauri
* İlk üç tissue package
* Patolog anotasyon kaynağı
* İlk benchmark datasetleri
* Pilot fiyatlandırması
* Ürün adı

## 86. Kesin geliştirme sırası

```
1. Legacy sistemi dondur
2. Python motorunu UI'dan ayır
3. Ortak spatial veri modelini oluştur
4. Visium importer
5. QC
6. preprocessing
7. graph engine
8. spatial domain
9. cell annotation
10. spatial genes
11. pathway analysis
12. niches
13. ligand–receptor
14. report
15. validation
16. pretrained GNN
17. desktop UI
18. pilot
19. 3B
20. diğer platformlar
```

3B ve büyük AI özellikleri ancak çekirdek analiz motoru doğrulandıktan sonra başlamalıdır.
