# Yol Haritası: Glio-Cartography → Genel Spatial Transkriptomik Platformu

> Durum: **TASLAK, onay bekliyor.** Bu dosya düzeltildikten sonra uygulamaya başlanacak.
> Düzeltmek için: satırları doğrudan değiştir, `[?]` işaretli yerler açık sorulardır.
> Başlangıç noktası: `v3.2.12` (GBM'ye özel, Teknofest sonrası hali).

---

## 0. Hedef ve ilkeler

**Hedef:** Tek kişilik ekiple, 6 ay içinde ilk ücretli pilotları alabilecek, dokudan bağımsız bir spatial transkriptomik analiz ürünü.

**İlkeler**
1. **Doğrulanamayan iddia yok.** Simülasyon, risk skoru, ilaç önerisi gibi kısımlar çıkar. Her çıktı ölçülebilir bir doğrulamaya bağlı olsun.
2. **Research Use Only.** Teşhis, prognoz ve tedavi önerisi iddiası yok.
3. **Önce motor, sonra özellik.** GBM "referans doku paketi" olur, ürünün kendisi olmaz.
4. **Bağımsız değerlendirme.** Eğitimde kullanılan etiketle test etme (şu anki çembersellik).
5. **Müşteri görüşmesi koddan önce gelir.** Hafta 2'den itibaren sürekli.

---

## 1. Karar özeti

| Konu | Karar | Durum |
|---|---|---|
| GBM'ye özel teori (knockout, TCGA risk, agresif bölge, ilaç skoru) | **Sil.** Önce `v3.2.12-gbm-legacy` etiketi | Onaylandı |
| İlaç hedefleme sekmesi | **Tamamen sil** (açıklayıcı liste de kalmasın) | Onaylandı |
| Model | Her örnek için eğitim yerine **tek önceden eğitilmiş GNN** + hafif başlıklar | Onaylandı |
| 3B | **Ardışık kesit hizalama + 3B grafik + 3B görselleştirme** | Onaylandı, v1'den sonra |
| Doğrulama etiketi | **Patolog anotasyonu** | Planlanıyor |
| Gelir modeli | Önce hizmet (analiz + rapor), sonra lisans/abonelik | Öneri `[?]` |
| Dağıtım | Masaüstü (veri yerelde), sonra opsiyonel bulut kuyruğu | Öneri `[?]` |

---

## 2. Mimari hedef

```
┌────────────────────────────────────────────────────────────┐
│  Arayüz kabukları:  Masaüstü (Electron)  |  CLI  |  (bulut) │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  Motor (Python paketi, UI'dan bağımsız, testli)             │
│   io/        Visium, Visium HD, Xenium, MERSCOPE, CosMx...  │
│   qc/        kalite kontrol, ön işleme                      │
│   model/     Tek GNN: gövde (pretrained) + başlıklar        │
│   register/  Kesit hizalama (2B → 3B)                       │
│   analysis/  L-R iletişimi, yolak zenginleştirme, niş       │
│   report/    HTML/PDF raporu, provenance                    │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  Doku paketleri (YAML/JSON, kodsuz):                        │
│   gbm/  (Ivy GAP imzaları, hücre marker'ları, rapor metni)  │
│   dlpfc/, meme/, ...  kullanıcı kendi paketini yükleyebilir │
└────────────────────────────────────────────────────────────┘
```

**Doku paketi şeması (taslak)**
- `regions`: ad, açıklama, imza genleri, renk
- `cell_types`: ad, marker listesi
- `reference` (opsiyonel): scRNA referans yolu
- `report`: şablon ve dil dosyaları
- `version`, `license`, `source` (imza kaynakları ve lisansları)

---

## 3. Fazlar

### Faz 0 — Temizlik ve temel (Hafta 1)

**Amaç:** Kod tabanını küçült, GBM bağımlılıklarını doku paketine ayır, hukuki riskleri kapat.

- [ ] `git tag v3.2.12-gbm-legacy`
- [ ] **Sil:** `counterfactual_knockout`, `counterfactual_lr_blockade`, `counterfactual_gene_regulation` (`train_gnn.py`)
- [ ] **Sil:** `/results/simulate-knockout` ve ilgili arayüz
- [ ] **Sil:** `rankcox_loss`, `ZONE_RISK_WEIGHT`, "agresif bölge" mantığı, TCGA risk görünümü
- [ ] **Sil:** `drug_catalog/`, `/drug-catalog*` endpoint'leri, `drug-catalog.js`, ilaç hedefleri sekmesi, drug score görünümü
- [ ] **Sil:** `/cohort/features`, `/cohort/compute` ve ilgili arayüz `[?]` (kohort modülü bir şeye bağlı mı? Kontrol edilecek.)
- [ ] **Kaldır:** `ssl._create_unverified_context` (`pathway_mapper.py`)
- [ ] **Değiştir:** KEGG → lisansı temiz kaynak (Reactome / GO / MSigDB hallmark). `[?]` hangi biri?
- [ ] `ZONE_SIGNATURES` ve `ZONE_NAMES` → `tissue_packs/gbm/` dosyasına
- [ ] `configs/config.yaml` içindeki GBM marker'ları → doku paketine
- [ ] Sürüm tek kaynaktan (`package.json`) okunsun, README rozeti güncel kalsın
- [ ] Mevcut testler temizlik sonrası geçmeli. Ayrıca GBM çıktısının (bölge atamaları) regresyon testi eklenmeli.

**Çıkış kriteri:** GBM örneği (GSE331374) hala uçtan uca çalışıyor, silinen özellikler arayüzde ve API'de yok, lisans riski taşıyan kaynak yok.

### Faz 1 — Motoru genelleştir (Hafta 2–3)

- [ ] `GLIO_*` ortam değişkenleri → genel adlar (geriye dönük uyumluluk için kısa süre alias)
- [ ] `GlioCartographyGNN` ve `glio*` adlandırmaları genelleştirilir
- [ ] Ürün adı kararı `[?]` (marka, alan adı, ticari marka taraması)
- [ ] Motor, UI'dan ayrı çalıştırılabilir: `python -m <motor> run --input ... --pack gbm`
- [ ] Giriş katmanı: `spatialdata` / `squidpy` IO ile Visium + Visium HD. Xenium ve MERSCOPE sonraya.
- [ ] **Referanssız yol:** scRNA referansı olmadan marker/atlas tabanlı skorlama ve niş keşfi. Tangram opsiyonel kalite katmanı olur.
- [ ] Gerçek bir GBM dışı veri setinde (DLPFC, spatialLIBD) mevcut pipeline'ı çalıştır, **baseline** metrik al.
- [ ] Provenance: veri, sürüm, parametre, tohum her raporda yazılı.

**Çıkış kriteri:** DLPFC kesiti, GBM'ye özgü hiçbir şey düzenlemeden, CLI ile baştan sona çalışıyor.

### Faz 2 — Tek, önceden eğitilmiş GNN (Hafta 4–7)

**Tasarım**
- **Gövde:** kendi kendine öğrenen (maskelenmiş gen/spot yeniden kurma + komşu kontrastif). Etiket gerekmez.
- **Gen girdisi:** sabit ortak gen sözlüğü, eksik genler sıfır. Alternatif: gen embedding'leri `[?]`
- **Başlıklar:** bölge/niş sınıflandırma, hücre tipi bileşimi, belirsizlik. Yeni dokuda dakikalar içinde eğitilir veya sıfır-atış.
- **Kullanıcı eğitim yapmaz.** Normal akış ileri geçiştir.

**İşler**
- [ ] Halka açık veri envanteri ve lisans kontrolü (HEST-1k, STimage-1K4M, spatialLIBD, 10x örnekleri, GEO)
- [ ] Veri indirme ve standartlaştırma hattı (ortak gen sözlüğü, QC)
- [ ] Ön eğitim betiği ve GPU kiralama planı `[?]` bütçe
- [ ] Başlık eğitimi ve değerlendirme betikleri
- [ ] Referanslarla kıyas: BANKSY, SpaGCN, BayesSpace/Squidpy tabanlı yöntemler (aynı veride, aynı metrik)
- [ ] Mevcut MC dropout belirsizliği yeni modele taşınır, kalibrasyon ölçülür
- [ ] Model kartı: eğitim verisi, sınırlar, bilinen hatalar

**Ölçütler (ground truth ile)**
- DLPFC: ARI/NMI (katman etiketleri), donörler arası genelleme (bir donörü dışarıda bırak)
- Patolog verisi: bölge başına F1, uzman uyumu (kappa) ile birlikte raporlanır
- Çıkarım süresi: bir kesit için hedef süre `[?]` (örn. CPU'da < X dk)

**Çıkış kriteri:** Eğitimsiz çalışan model, en az bir baseline'a karşı DLPFC'de anlamlı olarak aynı veya daha iyi, sonuçlar tekrarlanabilir.

### Faz 3 — Patolog anotasyonu (Hafta 1'de başlar, Faz 2 ile paralel)

- [ ] Taksonomi dokümanı: bölge sınıfları, tanımlar, sınır kuralları (GBM için başlangıç: Ivy GAP benzeri sınıflar)
- [ ] Anotasyon aracı seçimi (QuPath, vb.) ve çıktı formatı (poligon → spot etiketi)
- [ ] Mümkünse 2 patolog, çakışan alt küme üzerinde uyum (kappa)
- [ ] **Anotasyon yalnızca değerlendirme için** (eğitimin parçası değil). Eğitim/test ayrımı örnek veya hasta düzeyinde.
- [ ] Hedef örnek sayısı `[?]` (öneri: ≥ 20–30 kesit, birden çok hasta)
- [ ] Veri sahipliği, etik kurul ve paylaşım izni yazılı `[?]`

### Faz 4 — 3B rekonstrüksiyon (Hafta 8–11)

- [ ] Hizalama: H&E ile kaba hizalama, ardından ifade tabanlı ince ayar (PASTE/PASTE2 veya STalign) `[?]`
- [ ] Kesit kalınlığı ve aralığı kullanıcı girdisi (varsayılan yok, ardışık değilse uyarı)
- [ ] 3B komşuluk grafiği (kesit içi + kesitler arası kenarlar), tek GNN bunu kullanır
- [ ] 3B görselleştirme (`app-spatial-3d.js` genişletilir): nokta bulutu, dilimleme, bölge yüzeyi
- [ ] Doğrulama: DLPFC ardışık çiftlerinde hizalama hatası, katman sürekliliği, etiket tutarlılığı
- [ ] Hizalama kalitesi göstergesi ve başarısızlık uyarıları (kötü hizalamayı sessizce geçme)

**Çıkış kriteri:** En az 3 ardışık kesitten hizalanmış 3B model, ölçülebilir hizalama doğruluğu ve arayüzde gezilebilir görünüm.

### Faz 5 — Ürünleşme (Hafta 12+)

- [ ] 2–3 ücretli pilot (analiz + rapor), fiyat hipotezi test edilir
- [ ] Kurulum deneyimi: ortam indirmesi, hata raporlama (izinli), güncelleme
- [ ] Test kapsamı: motor, API, kritik arayüz akışları, CI
- [ ] Lisans sistemi gözden geçirme (mevcut RSA yapısı kalabilir)
- [ ] Şirket kuruluşu, IP devri/sahiplik belgesi, ticari marka
- [ ] Destek programları başvuruları (TÜBİTAK 1812, KOSGEB, Teknokent, BiGG) `[?]` güncel şartlar doğrulanacak
- [ ] Bulut seçeneği (GPU gerektiren işler için) ve KVKK/veri gizliliği tasarımı

---

## 4. Paralel iş akışları (her hafta)

| Akış | Haftalık hedef |
|---|---|
| Müşteri görüşmeleri | 3–5 görüşme (core facility, wet-lab, CRO, ilaç Ar-Ge) |
| Hukuk/IP | Lisans envanteri, IP belgesi, ticari marka |
| Dokümantasyon | Değişiklik günlüğü, model kartı, doğrulama raporu |

---

## 5. Riskler

| Risk | Etki | Önlem |
|---|---|---|
| Ön eğitim tek kişi için ağır (veri, GPU, süre) | Faz 2 uzar | Küçük başla (Visium), erken küçük bir model ile uçtan uca kanıtla |
| Tek GNN yeni dokuda kötü genelleme yapar | Ürün çalışmaz | Faz 1'de baseline, Faz 2'de donör dışı test. Başarısızsa doku başına hafif ince ayar |
| Referanssız yol Tangram'dan zayıf | Kalite düşüşü | İkisini de sun, kalite göstergesiyle |
| Patolog verisi gecikir | Doğrulama kayar | Önce DLPFC (hazır ground truth), patolog verisi ek katman |
| 3B hizalama yanlış sonuç verir | Güven kaybı | Kalite göstergesi, kullanıcıya açık uyarı |
| Veri/model lisansı ticari kullanıma izin vermez | Hukuki | Faz 0'da envanter, belirsizse kullanma |
| Tükenmişlik (tek kişi, 12 saat/gün) | Proje durur | Haftalık tek hedef, her faz sonunda küçük bir "gösterilebilir" çıktı |
| Yanlış müşteriye yanlış ürün | Boşa emek | 2. haftadan itibaren görüşmeler, fazlar buna göre güncellenir |

---

## 6. Başarı ölçütleri

- **Teknik:** Genel dokuda (GBM dışı) eğitimsiz çalışma, referanslara karşı ölçülmüş performans, 3B hizalama hatası raporlanmış.
- **Ürün:** Yeni kullanıcı, belgesiz, ilk analizi kurulumdan itibaren X dakikada bitirebiliyor `[?]`.
- **İş:** 3 ücretli pilot, 1 referans müşteri, kurulmuş şirket.

---

## 7. Açık sorular (senin kararın)

1. Ürün adı ne olacak? Mevcut ad "Glio-Cartography" GBM'ye işaret ediyor.
2. Pretraining için GPU bütçesi ne kadar? (Faz 2 kapsamını belirler.)
3. KEGG yerine hangi yolak kaynağı? (Reactome / MSigDB hallmark / GO)
4. Kohort modülü (`/cohort/*`) tamamen silinsin mi, yoksa sadeleştirilip kalsın mı?
5. İlk kullanıcı kitlesi kim? (core facility, wet-lab, CRO, ilaç Ar-Ge) Bu, fiyat ve dağıtımı belirler.
6. Patolog anotasyonu için hedef kesit sayısı ve etik/veri paylaşım izni durumu?
7. Masaüstü kalıcı mı, yoksa 6 ay içinde bulut mu hedefleniyor?
8. Kullanıcı arayüzü dili: TR + EN mi, ağırlıklı EN mi? (Uluslararası satış için EN öncelikli olabilir.)

---

## 8. Hafta 1 görev listesi (onay sonrası ilk iş)

1. `git tag v3.2.12-gbm-legacy`
2. Teori kısımlarını sil (backend + endpoint + arayüz), testleri çalıştır
3. `ssl` bypass ve KEGG kaldır, yerine seçilen kaynağı koy
4. `ZONE_SIGNATURES` → `tissue_packs/gbm/`
5. GBM regresyon testi (bölge atamaları sabit kalmalı)
6. Anotasyon taksonomisi taslağı (Faz 3)
7. İlk 3 müşteri görüşmesini ayarla
