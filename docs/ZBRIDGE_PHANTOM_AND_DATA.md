# Z-BRIDGE — Sentetik Fantom Spesifikasyonu ve Veri Kaynakları

> Durum: fantom `spatialcore/synthetic/` içinde uygulandı (Faz 2b); DLPFC indirildi ve doğrulandı (§4). §2–§3 tarihsel kayıttır.
> Fantom **gerçek biyoloji kanıtı değildir**; yalnız algoritma/mühendislik doğrulaması içindir.

## 1. Fantom: ileri model (forward model)

**Önemli ilke:** fantom, Z-BRIDGE'in varsayımlarını *sağlayan* bir dünyadan üretilirse "kendi kendini doğrular".
Bu yüzden **iki aile** üretilir: (A) varsayımlar **sağlanır**, (B) varsayımlar **bilerek ihlal edilir**.

### 1.1 Hacim ve yapılar (µm)

- Hacim: 4000 × 4000 × 1200; `K = 7` kesit, nominal kalınlık 10, aralık 0 (varyantlarda 8–12 ve eksik kesit).
- **Tümör küresi** (R=1000, hafif eğik elipsoid), **bağışıklık kabuğu** (kalınlık 150), **damar kanalı**
  (yarıçap 80, z eksenine **eğik** giden silindir → kesitlerde kayan daire), **infiltratif parmak**
  (genişlik 120, yalnız 3 ardışık kesitte görünür → Z sürekliliği testi), **kayan sınır** (bir domain sınırı kesit
  başına 40 µm ilerler → gerçek 3B değişim), ve düz **normal doku** zemini.
- Domain etiketi her voksel için bilinir; sınır yüzeyleri ve imzalı mesafe analitik/rasterize.

### 1.2 İfade üretimi

- `G = 2000` gen, 20 program; domain başına program karışımı → gizli alan `u(x,y,z)` (gen başına log-ortalama).
- Spot gözlemi (fiziksel tutarlı): **Visium ızgarası** (altıgen, merkez aralığı 100, disk çapı 55), spot ifadesi =
  `u`'nun **disk × kesit kalınlığı** üzerindeki hacim integrali (M2'nin varsayımı sağlanır).
- Sayım: `y ~ NB(ℓ_s · μ_s, r)`, `ℓ_s` log-normal (kesit başına ortalama farkı), gen başına aşırı dağılım.
- **Her kesit için bağımsız gürültü** (A ailesi).

### 1.3 Zorluk katmanları (her biri 20 tohum)

| Katman | Dönme | Öteleme | Ölçek/kayma | Non-rigid (GP) | Kısmi örtüşme / doku kaybı | Diğer |
|---|---|---|---|---|---|---|
| **Kolay (E)** | ±5° | ±0,5 aralık | yok | yok | tam | – |
| **Orta (M)** | ±15° | ±1,5 aralık | ölçek 0,97–1,03; kayma 0,02 | genlik 20 µm, uzunluk 500 µm | %80 örtüşme; %5 spot düşmesi | kesit başına kitaplık 2× fark |
| **Zor (H)** | ±30° | ±3 aralık | ölçek 0,95–1,05; kayma 0,05 | genlik 60 µm | %25 doku kaybı; **yırtık** (100 µm boşluk çizgisi); **katlanma** (yerel çift) | gen-bazlı çarpımsal batch; **1/7 kesit eksik**; kalınlık 8–12 (bilinmiyor bayraklı); ağır seyreklik |

### 1.4 Varsayım-ihlal ailesi (B) — H1–H5'in sınandığı yer

| İhlal | Ne bozulur | Beklenen davranış |
|---|---|---|
| **Ambient RNA / komşu spot difüzyonu** (gürültü korelasyonu) | M4 bağımsızlık varsayımı | `r_amb` maskesi olmadan kapı sapmalı; olunca düzelmeli |
| **Güçlü gerçek z-değişimi** (kayan sınır hızı ×4) | M1 null'ı | üçgen testi gerçek değişimi "yanlış kayıt" saymamalı |
| **Tek kesit bozuk** (yalnız k kesiti kaymış) | G5 | üçgen testi sorunu k'ya atfetmeli |
| **Yanlış aşırı dağılım** (sıfır-şişkin sayım) | `D` ölçeği | replika-medyanı yeniden ölçek; teşhis uyarısı |
| **Gerçek batch** (kesit-ortalaması kayması) | section sızıntısı | section-probe eşiği |

### 1.5 Ground truth çıktıları (her koşuda saklanır)

Kesit dönüşümleri `θ_k` (ve non-rigid alan), spot→voksel etiketi, **gerçek correspondence** (disk çakışması),
spot başına **gerçek kayıt hatası**, sınır yüzeyleri, domain etiketi, hangi spotların "gözlenmeyen" olduğu.

### 1.6 Ölçülecekler (özet; ayrıntı `ZBRIDGE_ALGORITHM.md` §6)

H1 sınır AUC/FPR · H2 kayıt-hatası ilişkisi ve üçgen testi · H3 ECE/kapsama · H4 `I(d;θ)` duyarlılık eğrisi ·
H5 kapı–sınır AUC · H6 çekirdek karşılaştırması · H7 Z'nin sınır doğruluğuna katkısı. Her tohum için ablasyon `A0–A7`.

## 2. Halka açık veri adayları (arama sonucu; HİÇBİRİ indirilmedi/doğrulanmadı)

| Veri | Ne | Neden uygun | Uyarı |
|---|---|---|---|
| **DLPFC (spatialLIBD, LIBD)** | insan, 3 donör; her donörde **ardışık/yan yana kesitler** (arama sonuçları: dört kesit, iki ardışık çift, çiftler ≈300 µm arayla; **yayından teyit et**), manuel katman etiketleri | etiketli, çok kullanılan, hem yakın hem uzak Δz | **ön-eğitim derlemlerinde olma ihtimali** (stFormer/Nicheformer) → sızıntı kontrolü; kesit aralıkları çelişkili anlatılıyor |
| **spatialDLPFC (LIBD GitHub)** | 30 Visium + SPG + snRNA | daha büyük, daha yeni | seri kesit yapısı doğrulanmalı |
| **10x Mouse Brain Serial Section 1/2** (sagital ön/arka) | 10x Genomics halka açık veri | seri kesit, kurulum kolay | etiket yok; yalnız tutarlılık/kayıt testi |
| **Glioblastoma atlası (SNU, gbmvisium.snu.ac.kr)** | 32 kesit, ~116 bin spot, çok-omik, genotip | GBM paketi için | **seri değil** olabilir (çok-bölgeli) |
| **Çok-bölgeli IDH-wt GBM atlası** | 12 hasta, 97 Visium kesiti, histopatolojik anotasyon | GBM bölge etiketleri | seri kesit değil; Z için değil, GBM paketi doğrulaması için |
| **Benchmark çalışmaları** (Genome Biology 2025: 12 yöntem, 19 veri seti, yedi kaynak; STAIR kendi veri setleri) | veri listeleri ve protokoller | **kıyas protokolünü** hazır alırız | hangi setlerin indirilebilir olduğu teyit edilecek |

**Kural:** seçilen her gerçek set için (i) kesit aralığı/kalınlık yayından, (ii) ön-eğitim derlemleriyle örtüşme,
(iii) lisans/kullanım şartı **kayda geçirilir** (manifest `reference_databases`).

## 3. Neden bu ortamda indirme/tam-metin taraması yapılamadı (yetki değil, ağ)

Ağ geçidi çoğu bilimsel ve veri sitesini reddediyor (403 / `EGRESS_BLOCKED`): Springer, Nature, PMC, bioRxiv,
arXiv, Europe PMC, OpenAlex, Semantic Scholar, Zenodo, LIBD ve diğerleri. Yalnızca **web arama özetleri** ve
**GitHub** çalışıyor. İzin değiştirilebilir: *oturum başlığındaki bulut ortamı menüsü → Edit → Network access*
(daha geniş erişim düzeyi **veya** "Allowed domains"e ana makineler; paket yöneticileri kutusu işaretli kalsın).
Önerilen alan adları: `api.openalex.org`, `api.semanticscholar.org`, `eutils.ncbi.nlm.nih.gov`,
`www.ncbi.nlm.nih.gov`, `pmc.ncbi.nlm.nih.gov`, `europepmc.org`, `www.biorxiv.org`, `arxiv.org`,
`link.springer.com`, `www.nature.com`, `zenodo.org`, `figshare.com`, `ndownloader.figshare.com`,
`cf.10xgenomics.com`, `www.10xgenomics.com`, `research.libd.org`, `gbmvisium.snu.ac.kr`.
Adımlar: https://code.claude.com/docs/en/cloud-environments#network-access


## 4. Uygulama durumu (2026-10-07)

### 4.1 Fantom (`spatialcore/synthetic/`, testler `tests/spatialcore/test_phantom.py`)

Uygulananlar: analitik 6 domain (normal, tümör çekirdeği, bağışıklık kabuğu, damar, parmak, kayan levha),
altıgen Visium ızgarası (100 µm / 55 µm disk), disk × kalınlık kuadratürü ile domain payları, NB sayımlar,
kesit-başı bağımsız gürültü ve derinlik, rigid + ölçek + kayma + GP-benzeri non-rigid, kısmi örtüşme (düz kesim),
doku kaybı (blob), yırtık, spot düşmesi, eksik kesit (kalan kesitlerin `gap_um`'u günceller),
bilinmeyen kalınlık, E/M/H katmanları, B ailesi: ambient sızıntı, sıfır-şişkinlik, gen-bazlı batch,
tek bozuk kesit, kayan sınır hız çarpanı. Tam ground truth: dönüşümler, spot→doku konumu, domain payları,
sınır bayrağı, gerçek footprint örtüşmesi (`true_overlap`).

Belgeden **sapmalar / yapılmayanlar** (gizlenmedi):
- **Katlanma (fold)** uygulanmadı; H katmanında yalnız yırtık var.
- Tümör z yarı-ekseni 60 µm (7×10 µm kesit aralığında kapakların görünmesi için); bu bir varsayımdır.
- `true_overlap` eş-disk mercek alanını kullanır; ölçek/kayma kaynaklı elips bozulmasını yok sayar.
- Domain içi yumuşak ifade değişimi yok: kesitler arası fark yalnız gürültü + sınır/domain değişiminden gelir.
  Bu M1 gürültü tabanı testini kolaylaştırır; gerçek veride daha zor olacaktır.
- 1/7 eksik kesit H katmanında sabit `missing_sections=(3,)`.

### 4.2 Gerçek veri: DLPFC (`benchmarks/datasets.yaml`, `benchmarks/fetch_data.py`)

İndirilen: Zenodo 10.5281/zenodo.22043830 `10xVisium_DLPFC.zip` (CC-BY-4.0; md5 Zenodo'nun bildirdiğiyle eşleşti),
12 h5ad (3 donör × 4 kesit), katman etiketi `obs['Truth']` (Layer_1–6, WM; birkaç NaN).
**Birincil makaleden (Maynard 2021, PMC8095368) doğrulandı:** her donörde iki *doğrudan komşu* 10 µm kesit çifti;
ikinci çift birincisinin **300 µm posteriorunda**. Yazarlar komşu çiftleri "spatial replicates" olarak adlandırıp
istatistikte blok faktörü yaptı — bu bir analiz tercihi, algoritma değil (yenilik iddiamızı değiştirmez ama bilinmeli).
Koordinatlar tam çözünürlüklü piksel; medyan en yakın komşu mesafesi ≈137 px = 100 µm ⇒ ≈0,73 µm/px
(metadata'dan değil, ızgaradan **tahmin**; `uns['um_per_unit']` içinde kayıtlı).

Açık: çift içinde hangi kesitin "üst" olduğu dosyalardan bilinmiyor (listelenen sıra varsayım); ön-eğitim
derlemleriyle örtüşme **doğrulanmadı** (stFormer/Nicheformer kullanılmadan önce zorunlu kontrol).
`10xVisium_MouseBrain.zip` yalnız **tek** kesit içeriyor; 10x "Serial Section 1/2" bu ortamdan erişilemedi (CDN 403).
Katman-pseudobulk korelasyonu (komşu çift ≈0,968 vs uzak ≈0,964) ayırt edici değil — gen ortalaması baskın; bu
ölçüt replika gürültü tabanı için **kullanılmamalı**, M1 spot düzeyinde kayıttan sonra ölçülmeli.
