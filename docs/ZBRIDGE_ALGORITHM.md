# Z-BRIDGE v2 — Rakip Çözümlemesi ve Yeni Algoritma

> Durum: **TASARIM. Kod yok.** Bu belge `ZBRIDGE_DESIGN.md` içindeki §E (yöntem) bölümünün
> **yerini alır / daraltır**; mimari, veri modeli, test planı ve risk kaydı orada geçerli kalır (§9).
>
> **Kanıt sınırı (okumadan önce):** Bu ortamda Springer, Nature, PMC, bioRxiv, arXiv ve ReadTheDocs
> tam metinlerine **erişilemedi** (ağ geçidi engelledi). Rakip algoritmaların ayrıntıları; web arama
> özetleri, GitHub README'leri ve özet metinlerinden çıkarıldı. Denklem düzeyinde ayrıntı gereken yerde
> bu belirtildi. **"Literatürde yok" iddiası bu belgede KANITLANMIŞ değildir**; yalnızca hedefli
> aramalarda doğrudan örtüşme bulunamadığını söyler. Bu iddia, §8'deki tarama protokolü tamamlanana
> kadar yayın/ürün iddiası olarak kullanılmamalıdır.

---

## 1. Özet

- 3B seri-kesit yöntemlerinin hepsi, kesitler arası bilgiyi **hizalama sonrası sabit bir graf** olarak ya da
  **ifade benzerliği** olarak kuruyor; hizalama belirsizliği aşağı akıştaki alan/sınır çıkarımına
  taşınmıyor, sınırlar için **kimlik atanabilir (identifiable) bir sinyal** yok, kesitler birbirinin
  **replikası** olarak kullanılmıyor.
- Önerilen çekirdek fikir: **"kesit = replika"**. Komşu kesitler aynı dokunun (küçük Δz farkıyla) bağımsız
  gürültülü iki gözlemidir. Bu, tek kesitte **yoktur** ve şunları verir: (i) **ampirik gürültü tabanı**,
  (ii) bundan türeyen **kalibre sınır testi** ve **kayıt güveni**, (iii) kapıları etiketsiz öğreten **held-out
  tahmin riski**.
- Ayrıca: **Visium spot ayak izi (footprint) çakışmasından** türeyen fiziksel Z çekirdeği ve **dönüşüm-
  (transform) düzeyinde** (spot düzeyinde değil) hizalama belirsizliği yayılımı; belirsizlik **karşılıklı
  bilgi** ile kayıt-kaynaklı / biyolojik olarak ayrışır.

---

## 2. Rakip algoritmaların çözümlemesi

Doğruladığım şey ile doğrulayamadığım şey ayrı işaretli. ✔ = kaynakta okundu (özet/README/arama özeti),
○ = tam metin okunamadı, ayrıntı çıkarım.

### 2.1 Hizalama ağırlıklı yöntemler

| Yöntem | Çekirdek algoritma | Kesit-arası bilgi | Belirsizlik | Not |
|---|---|---|---|---|
| **PASTE** | Fused Gromov–Wasserstein optimal taşıma (ifade + uzamsal mesafe); ikili hizalama, "center slice" ile entegrasyon ✔ | taşıma planı π (yumuşak) ✔ | π var, **dönüşüm belirsizliği yok** | varsayım: **tam örtüşme**, aynı teknoloji ✔; BSD-3 ✔ |
| **PASTE2** | **Kısmi** FGW; örtüşme oranı `s` parametresi, histoloji destekli seçenek ✔ | kısmi π; z değerleri yığma için atanır ✔ | yok | BSD-3 ✔; `s` kullanıcı/aralık seçimi |
| **SPACEL / Scube** | iki komşu kesitin spotları arasında **MNN grafı** + **differential evolution** ile çeviri/dönme araması (rigid) ✔ | yalnız koordinat dönüşümü | yok | lisans README'de **belirtilmemiş** ✔ |
| **Graspot** | GAT + **dengesiz OT (UOT)**; olasılıksal eşleme **ağırlıklı ICP**'yi yönlendirir ✔ | olasılıksal eşleme → dönüşüm | eşleme olasılığı var, **dönüşüm posterior'u yok** (○) | hizalama + entegrasyon |
| **STalign / CODA** | LDDMM (difeomorfik) ± önce global affine ✔ | histoloji/ifade görüntüsü | yok | non-rigid için güçlü |
| **GPSA** | **derin Gauss süreci** ile uzamsal koordinat eğrisi; varyasyonel posterior ✔ | ortak koordinat sistemi | **posterior belirsizlik VAR** ✔ | MIT ✔; alan/sınır GNN'i yok |
| **stvgp** (varyasyonel uzaysal GP) | çok-modlu çok-kesitli GP ile 3B manzara ✔ (özet) | GP | ○ | alan/sınır yok (○) |
| **JADE** (NeurIPS 2025) | hizalama ↔ gömme **dönüşümlü** (roundtrip), gömme boyutları üzerinde attention ✔ | spot-bazlı hizalama + ortak gömme | **belirsizlik tanıtılmamış** (özette) | DLPFC + Stereo-seq |
| **STAIR** | **heterojen graf**: kesit içi kenar = uzamsal komşuluk; **kesitler arası kenar = ifade benzerliği ağırlıklı**; **spot-düzeyi + kesit-düzeyi attention**; kesit arası mesafe matrisi + **MST** ile göreli z sırası; sıralı 2B hizalama ✔ | **ifade benzerliği** (fiziksel mesafe bilinmiyor varsayımı) ✔ | yok | Genome Biology 2025 |

### 2.2 Entegrasyon / 3B alan tespiti

| Yöntem | Çekirdek | Z bilgisi nasıl giriyor | Zayıflık |
|---|---|---|---|
| **STitch3D** (MIT) | kesitleri **ICP veya PASTE** ile hizalar, **global 3B komşuluk grafı** kurar; **graf attention otokodlayıcı**; slice/spot- ve slice/gene-özgül etkilerle batch modeli; **scRNA referansıyla** ortak dekonvolüsyon ✔ | **sert** (hizalama sonrası yarıçap/komşuluk) | hizalama doğru varsayılır; scRNA referansı şart ✔ |
| **SPACEL / Splane** | **GCN + adversarial** öğrenme ile kesitler arası tutarlı alanlar ✔ | alan düzeyinde entegrasyon; Z kenarı yok (○) | sınır sinyali yok |
| **SpaBatch** | kesit içi + komşu kesitler arası **birleşik komşuluk ağı** (hizalanmış koordinat + yarıçap) ✔ | sert yarıçap | aynı |
| **STGAT** | komşu kesit hizalama + **graf kontrastif** öğrenme ✔ (özet) | ifade benzerliğiyle hizalama | |
| **STAGATE** (3B kullanımı) | GAT otokodlayıcı; kesitler arası kenar eklenebilir; GAT **sınır spotlarını** iyileştirmeyi hedefler ✔ | sert | sınır için özel öğretici sinyal yok |
| **SpaCross, PRECAST, GraphST** | çok-kesitli entegrasyon / olasılıksal gömme (2B ağırlıklı) ✔ | – | |

### 2.3 Hacim yeniden-yapılandırma / interpolasyon (farklı problem)

SINTER3D (örtük sinirsel temsil ile sürekli 3B gen alanı), UniST, C2-STi (eksik ara kesit üretimi),
3B-güdümlü flow-matching (seri histolojiden hacimsel ST), ST-DAI. Bunlar **eksik kesit üretir**; alan/sınır
çıkarımında Z kenarlarının güvenini modellemezler (○). Z-BRIDGE ile rakip değil, **tamamlayıcıdır**.

### 2.4 Fikir olarak yakın ama yayınlanmış yöntem DEĞİL

Arama sonuçlarında "Borrowing Evidence Across Serial Sections…" başlıklı bir **hipotez sayfası**
(Lacuna sitesi; sayfaya erişilemedi) kesitler arası "öğrenilmiş, kapılı bağlantılar" ve "kapının hizalama
iyiliği ve doku benzerliğine bakması" fikrini içeriyor. Hakemli/implemente bir yöntem olduğuna dair kanıt
**görmedim**; yine de **"hizalama güveniyle kapılı Z bağlantısı"nın tek başına yenilik olmadığı** sonucuna
götürür. Bu yüzden aşağıda **kapının kendisini iddia etmiyoruz**; kapıyı **nasıl eğittiğimizi** iddia ediyoruz.

---

## 3. Ortak varsayımlar → boşluklar

| # | Rakiplerin ortak davranışı | Sonuç / boşluk |
|---|---|---|
| **G1** | Hizalama bir **ön işlem**; nokta tahmini (STitch3D, SpaBatch, SPACEL…) ya da alternasyonla nokta tahmini (JADE). Posterior veren yöntemler (GPSA, stvgp) **alan/sınır GNN'i içermiyor**. | Hizalama belirsizliğinin **alan etiketine yayıldığı** ve **ölçüldüğü** bir ST yöntemi bulamadım. (Tıbbi görüntülemede "registration → segmentation uncertainty" var; ST'ye aktarılmamış görünüyor.) |
| **G2** | Z kenarı **sert yarıçap** (STitch3D, SpaBatch) ya da **ifade benzerliği** (STAIR). | **Fiziksel** bir yazışma modeli yok: iki Visium spotunun **paylaştığı doku sütunu** (disk çakışması) ve "boşlukta kalan/ gözlenmeyen" kütle açıkça modellenmiyor. |
| **G3** | Sınır = attention ya da kümeleme çıktısı; sınır olasılığı için **kimlik atanabilir sinyal yok**. | Etiketsiz öğrenilen sınır kapısı **tanımsız** (kayıp "her şeyi kes" ile kendini çözer). |
| **G4** | Kesitler **replika olarak** kullanılmıyor (yalnız enterpolasyon/ortalama). | **Ampirik gürültü tabanı** ve ondan gelen **kalibre testler** yok. |
| **G5** | Kayıt kalitesi hizalama kaybı veya görsel; **yerel, veriden doğrulanan** güven yok. | Yerel yanlış kayıt ile gerçek 3B değişim **ayrıştırılmıyor**. |
| **G6** | Belirsizlik tek kalem (veya hiç). | **Kayıt-kaynaklı** ile **biyolojik** belirsizlik ayrışmıyor. |

---

## 4. Yeni algoritma: Z-BRIDGE (v2 çekirdeği)

**Organize edici ilke — "kesit = replika":** Komşu kesitler aynı gizli ifade alanı `u` nın, **bağımsız sayım
gürültüsüyle** (ve hizalama hatası + küçük Δz değişimiyle) iki gözlemidir. Tek kesitte bu bilgi yoktur.

### 4.1 Gösterim

Spot `s=(k,j)`; sayım `y_s ∈ N^G`; kitaplık büyüklüğü `ℓ_s`. Gürültü-normalize profil `r_s ∈ R^p`
(Pearson artıkları; negatif-binom modeli altında birim varyans beklenir, bkz. §4.6 kalibrasyon).
İki spot arasında **gürültüye-normalize ayrışma**:

```
D_ab = ‖ r_a − r_b ‖² / (2p)          # aynı gizli ifade ⇒ E[D] ≈ 1 (kalibre edilir, bkz. 4.6)
```

### 4.2 M1 — Replika Gürültü Tabanı (RNF) ve kalibre sınır / kayıt istatistikleri

1. **Replika çiftleri:** komşu kesitlerde fiziksel çakışması yüksek (`ω_ij` büyük, §4.3) spot çiftleri.
   `D_rep` dağılımı = **ampirik boş (null) dağılım** `f0`: gürültü + hizalama hatası + küçük Δz değişimi
   içerir → **muhafazakâr** (gerçek gürültü tabanının üst sınırı).
   Kitaplık-büyüklüğü sepetlerine göre **koşullu** (`f0(· | ℓ_a, ℓ_b)`): gürültü derinliğe bağlı.
2. **Sınır olasılığı (XY kenarı):** kesit-içi kenarların `D_ij` dağılımı `f` ile `f0`'dan **yerel yanlış keşif
   oranı** (Efron, ampirik null):

   ```
   lfdr_ij = π0 · f0(D_ij) / f(D_ij)        b_ij = 1 − lfdr_ij
   ```

   Yani "bu komşu çifti, replikalar arasındaki gürültü+hata tabanından **anlamlı biçimde** farklı mı?"
   Etiket gerektirmez; ifade farkı **gürültü tabanıyla kalibre** edildiği için yoğun/seyrek bölgeler
   sistematik "sınır" sayılmaz. (Spesifikasyondaki "yalnız ifade farkından oluşmasın" için `b_ij` ayrıca
   morfoloji/kompozisyon kanalları ile birleşebilir; çekirdek istatistik budur.)
3. **Yerel kayıt güveni (veriden):** her spot için Z çiftlerindeki **fazla ayrışma**
   `e_i = Σ_j ω_ij · max(0, D_ij − q_{0.5}(f0)) / Σ_j ω_ij`, uzamsal düzgünleştirilmiş. Yüksek `e_i` ⇒ yerel
   yanlış kayıt **veya** gerçek 3B değişim.
4. **Replika üçgen testi (3 ardışık kesit k−1, k, k+1):** aynı spotlar için
   `D(k−1,k)` ve `D(k,k+1)` yüksek **fakat** `D(k−1,k+1)` düşükse, sorun **k kesitindedir** (yerel yanlış
   kayıt/artefakt) — gerçek monoton bir 3B değişim `D(k−1,k+1) ≈ D(k−1,k)+D(k,k+1)` verirdi.
   Böylece **yanlış kayıt ile gerçek yapı değişimi ayrışır** (G5).
   *Not:* ≥3 farklı Δz mevcutsa `D(Δz)=nugget+slope·Δz^α` uydurulur; **nugget** gürültü tabanıdır
   (geostatistik; "kesit≠replika" itirazının nicel cevabı).

### 4.3 M2 — Fiziksel ayak izi (footprint) çekirdeği ve "gözlenmeyen kütle"

Visium spotu çapı ≈ 55 µm bir **disk** olarak gözlenir (yarıçap `ρ`). Hizalanmış iki spot `i` (kesit k) ve
`j` (komşu kesit) merkez uzaklığı `d` ise **paylaşılan doku sütunu** disk-disk çakışma alanıdır:

```
A(d) = 2ρ² · arccos(d / 2ρ) − (d/2) · sqrt(4ρ² − d²)      (d < 2ρ, aksi halde 0)
ω_ij = E_{ε ~ N(0, Σ_reg)} [ A(‖d_ij + ε‖) ] / (πρ²)        ∈ [0,1]    # kayıt hatası üzerinden beklenen çakışma
```

`E[·]` bir arama tablosuyla (`d/ρ`, `σ/ρ` ızgarası) hesaplanır; `Σ_reg` M3'ten gelir. `ω_ij` **ön-ağırlık değil,
fiziksel bir büyüklüktür** ("i'nin ayak izinin ne kadarı j ile aynı dokuyu görüyor"). Doğrudan toplam:

```
ω_i^null = 1 − min(1, Σ_j ω_ij)     # gözlenmeyen kütle: komşu kesitte doku yok VEYA yakalama boşluğunda
```

(Visium'da disklerin kapsama oranı düşüktür; merkez aralığı 100 µm, çap 55 µm ⇒ yaklaşık %27 alan
kapsanır — **bu yüzden "null" burada çoğu zaman "gözlem yok"tur, "eşleşme yok" değil**; ikisi
`overlap` ve `tissue_mask`'tan ayrılır.) Platforma göre `ρ` ayarlıdır.

Fiziksel Z çekirdeği: `w^{Z}_{ij} = ω_ij · κ(Δz)`, `κ(Δz)` ya sabit bir önsel (parametrik, "varsayım" etiketli)
ya da M1'in `D(Δz)` uyduğundan **veriden** gelir.

### 4.4 M3 — Dönüşüm-posterior marjinalizasyonu (hizalama hatasının ilişkili doğası)

**Gözlem:** hizalama hatası **uzamsal olarak ilişkilidir**; bir kesite uygulanan global dönüşüm hatası
tüm spotlarını **birlikte** kaydırır. Spot-bazlı "yumuşak eşleşme olasılıkları" (PASTE π, Graspot, bizim `p`)
bu ilişkiyi **bilmez** ve alan belirsizliğini **düşük tahmin eder**.

**Yöntem:** kayıt, düşük boyutlu dönüşüm parametreleri `θ_k` için bir **posterior** `q(θ_k)` üretir
(EM hedefinin Laplace yaklaşımı, kovaryans `Σ_θ`; **replika testleriyle kalibre edilen** şişirme katsayısı).
`S` (varsayılan 8) dönüşüm örneği çekilir; **zincirleme** (`θ_k^{(s)} = θ_{k,k−1}^{(s)} ∘ … `) birikmiş ve
ilişkili hatayı doğal verir. Her örnek bir **Z grafı** `G^{(s)}` kurar (4.3). Eğitim ve çıkarımda:

```
p(d_i | veri) = (1/S) Σ_s p(d_i | G^{(s)})                              # marjinal olasılık
H[p̄]  =  E_s H[p^{(s)}]   +   I(d_i ; θ | veri)                        # toplam = biyolojik + kayıt-kaynaklı
```

`I(d_i; θ)` = **kayıt-kaynaklı belirsizlik** (örnekler arası uyuşmazlık, BALD tipi karşılıklı bilgi);
`E_s H[p^{(s)}]` = **biyolojik/sınıflandırma belirsizliği**. İkisi **ayrı raporlanır** (spesifikasyon §11).

### 4.5 M4 — Replika-risk kapılı mesaj geçişi (kapıları etiketsiz öğretmek)

Mesaj-geçişi katmanı, `ZBRIDGE_DESIGN.md` §E.5'teki yapıyı korur (ayrı `W_XY, W_Zup, W_Zdown`, kapılar
`g^{up/down}`, sınır kapısı `(1−b_ij)`), **iki değişiklikle**:

1. **Z attention'ı** `β_ij = softmax_j( a_Z(h_i,h_j,e_ij) + log w^Z_ij )` — fiziksel çekirdek (4.3) log-önsel
   (çift sayım yok).
2. **Eğitim hedefi = held-out sayım tahmin riski (kör nokta / J-değişmez):**
   spot `s`'in **kendi ölçümü gizlenir**; embedding `h_s^{(−s)}` yalnız komşu spotlardan (XY + Z)
   hesaplanır; NB dekoder `μ_s = Dec(h_s^{(−s)})` ile

   ```
   L_rep = − (1/|S|) Σ_s  log  (1/S) Σ_{s'}  NB( y_s ; ℓ_s · μ_s^{(s')} , r )        # dönüşüm örnekleri üzerinden karışım
   ```

   **Neden bu kimlik atanabilir (iddia, test edilecek):** komşu kesit sayımlarının gürültüsü, hedef spotunkinden
   **bağımsızdır** (replika). Dolayısıyla beklenen held-out NLL, doğru gizli alan altında **minimumdur** ve
   **gate/sınır** yalnızca tahmini iyileştirdiği ölçüde açık olur: sınır boyunca birleştirme yanlılık (bias)
   ekler → kapı kapanır; bilgisiz komşu varyans ekler → kapı kapanır. Etiket yok, sezgisel eşik yok.
   Sınır ile "bilgisizlik" ayrımı M1'in **gürültü-tabanlı** `b_ij`'si ile (kapının bir ön-bilgisi) yapılır.
   Kimlik atanabilirlik varsayımı: gürültü **koşullu bağımsız** (komşu spotlar arası ambient RNA/difüzyon
   korelasyonu bunu bozar → hedef çevresindeki halka maskelenir; yarıçap `r_amb` config'te).

### 4.6 Kalibrasyon ve doğrulama (algoritmanın parçası)

- `D` ölçeği: NB aşırı dağılım (`r`) tahmin hataları nedeniyle `E[D]=1` yaklaşık; **replika çiftlerinin
  medyanıyla yeniden ölçeklenir** (bozulma ölçüsü olarak raporlanır).
- Tüm eşik/ağırlık/`S`/`r_amb`/`τ` **config + manifest**'e yazılır; "varsayım" etiketi.
- Sentetik fantomda (ground truth: dönüşüm, sınır, alan) ve gerçek veride **ablasyon** (§6).

### 4.7 Sözde-kod

```
Input: VolumeSet (sections, counts, coords, optional histology), tissue pack
1. QC per section; normalize (Pearson residuals), PCA
2. Registration (rigid→affine) with soft correspondences → q(θ_k) (Laplace), calibrated; chain → q(θ_{1..K})
3. Draw S transform samples; for each: footprint kernel ω_ij, w^Z_ij (4.3); build typed graph G^(s)
4. RNF: replicate pairs (high ω) → f0 conditional on library size; XY edges → lfdr → b_ij; local excess e_i; triangle test
5. Train ZBridge encoder by L_rep (blind-spot, mixture over S), gates learned; b_ij as prior input
6. Inference: for each s' embedding h^(s'); p̄(d_i), H split (bio vs registration), boundary b_ij, states
7. Outputs + manifest (all params, seeds, versions, calibration diagnostics)
```

Karmaşıklık: M1 `O(E)`; M2 arama tablosu `O(E_Z)`; M3 `S×` ileri geçiş (S≈8; CPU'da dakikalar,
bütçe ölçülecek); M4 mevcut GNN maliyeti.

---

## 5. Önceden eğitilmiş gövde ile birleştirme — **sonuç**

Hazır model (stFormer/Nicheformer/…) düğüm özelliği olarak girerse **M4'ün kör nokta kuralı bozulur**:
FM gömmesi spotun **kendi sayımlarından** hesaplanır ve hedefe sızar. Kural: dış kodlayıcı **yalnızca
maskelenmemiş gen alt kümesinde** çalışır; held-out hedef = **maskelenmiş gen bölümü** (gen-bölümü
J-değişmezliği; genler koşullu bağımsız varsayımı). Bu `ExpressionEncoder` arayüzünün **şartıdır**
(bkz. `ZBRIDGE_DESIGN.md` Ek J).

---

## 6. Falsifiye edilebilir hipotezler ve "öldürme" ölçütleri

Fantomda (bilinen dönüşüm/sınır/alan) ve en az bir halka açık çok-kesitli sette:

| H | Hipotez | Ölçüt | Başarısızsa |
|---|---|---|---|
| **H1** | RNF-kalibre `b_ij`, gradyan-tabanlı sınırdan **daha iyi** AUC verir; hatalı kayıt altında **daha az** yanlış sınır | sınır AUC / FPR, enjekte edilmiş kayma ile | M1'in sınır kullanımını bırak |
| **H2** | `e_i` ve üçgen testi, **gerçek yerel kayıt hatasıyla** ilişkili (Spearman) ve gerçek 3B değişimden ayırır | doğru-pozitif oranı | yerel kayıt güveni için sezgisele dön |
| **H3** | Dönüşüm-düzeyi örnekleme, spot-düzeyi yumuşak eşleşmeden **daha iyi kalibre** alan belirsizliği verir | ECE, kapsama eğrisi | M3'ü bırak; spot-düzeyi kalsın |
| **H4** | `I(d;θ)` enjekte edilen yanlış kayıt miktarıyla **monoton artar**; biyolojik kısım sabit kalır | duyarlılık eğrisi | belirsizlik ayrıştırmasını geri çek |
| **H5** | L_rep ile öğrenilen kapılar, ground-truth sınır boyunca **mesaj ağırlığını düşürür** | kapı–sınır AUC | M4 kapı eğitimini bırak; M1 deterministik kalsın |
| **H6** | Fiziksel `ω_ij` çekirdeği, `exp(−d/τ)`'ye göre aynı/daha iyi alan doğruluğu **ve** daha az ayarlanan parametre | ARI/Dice, parametre sayısı | basit çekirdeğe dön |
| **H7** | Z kenarları (herhangi biri) XY-only'ye göre **sınır doğruluğunu** artırır | ablasyon | 3B değer önermesini yeniden düşün |

**Ablasyon (hepsi aynı fantom + gerçek veride):** `A0` XY-only · `A1` naif 3B yarıçap (STitch3D tarzı) ·
`A2` STAIR tarzı ifade-benzerliği Z kenarı · `A3` +fiziksel çekirdek · `A4` +dönüşüm örnekleme ·
`A5` +RNF sınır · `A6` +L_rep kapı eğitimi · `A7` tam. **Rakip kıyası:** `A1/A2` kendi uygulamamız;
mümkünse STitch3D/STAIR/SpaBatch çıktıları aynı verilerde (lisanslar uygun: STitch3D MIT, PASTE/PASTE2 BSD-3).

---

## 7. Yenilik durumu (dürüst tablo)

| Mekanizma | En yakın önceki çalışma | Fark | Aramada doğrudan örtüşme | Güven |
|---|---|---|---|---|
| **M1** replika gürültü tabanı + lfdr sınır + üçgen testi | tıbbi görüntülemede *Neighboring Slice Noise2Noise* (denoising); ST'de `SpatialDE` (gürültü/uzamsal varyans ayrıştırma), `SpNeigh`, `trendsceek` (sınır/yerel bağlam testleri) | komşu kesitlerden **ampirik null** ile **sınır anlamlılığı + kayıt güveni** | bulunamadı | orta-yüksek |
| **M2** footprint-çakışma çekirdeği + gözlenmeyen kütle | STitch3D/SpaBatch (sert yarıçap), STAIR (ifade benzerliği) | fiziksel paylaşılan-sütun modeli | bulunamadı | orta (mühendislik katkısı küçük, ama yöntemsel olarak temiz) |
| **M3** dönüşüm-posterior marjinalizasyonu + MI ile belirsizlik ayrıştırma | tıpta *"From Registration Uncertainty to Segmentation Uncertainty"*; ST'de GPSA/stvgp (posterior, alan yok), SPOmiAlign (belirsizlik-farkında eşleme) | ST alan/sınır GNN'ine **yayılım** + ilişkili hata + ayrışma | bulunamadı | orta (aktarım + yeni bağlam) |
| **M4** replika-risk (kör nokta) ile kapı eğitimi | Noise2Self/Noise2Noise (görüntü), STAGATE (öğrenilmiş attention) | **kesitler arası bağımsızlık** ile kapıların held-out riskle etiketsiz öğrenilmesi | bulunamadı | orta |
| Kapının hizalama güvenine bağlanması | STAIR (kesit-düzeyi attention), Lacuna hipotez sayfası | **tek başına yenilik değil** | VAR (yakın) | — |

**Dürüst sonuç:** Tek bir mekanizma "çığır açıcı" değil; **birleşim** — özellikle **M1 + M3 + M4'ün aynı
"kesit=replika" ilkesine bağlanması** — savunulabilir yenilik adayıdır. Hakem karşı argümanı: *"kesitler gerçek
replika değil (Δz, deformasyon)"*. Cevap: null **muhafazakâr** (üst sınır), nugget/üçgen testi gerçek
değişimi ayırır; ve bunu H1–H4 ile **ölçeriz**.

---

## 8. Yenilik doğrulama protokolü (yayın iddiasından ÖNCE zorunlu)

1. Google Scholar / bioRxiv / PubMed / Europe PMC'de aşağıdaki sorgu setini **elle** çalıştır (bu ortamda yapılamadı):
   "serial section" ∧ ("replicate" ∨ "noise floor" ∨ "empirical null") ∧ "spatial transcriptomics";
   "registration uncertainty" ∧ ("domain" ∨ "cluster") ∧ "spatial transcriptomics";
   "blind-spot" ∨ "Noise2Self" ∧ "spatial transcriptomics" ∧ "adjacent section";
   "footprint" ∨ "disk overlap" ∧ "Visium" ∧ "serial section".
2. **İleri atıf taraması:** STAIR, STitch3D, SPACEL, PASTE2, GPSA, JADE, SpaBatch makalelerini **atıflayan**
   2025–2026 çalışmalar.
3. Danışman/alan uzmanı incelemesi. Bulunursa: ilgili mekanizma "bilinen bileşen" olarak yeniden
   konumlandırılır, kalan birleşim yeniden değerlendirilir.
4. Bu belgenin §2'deki rakip ayrıntıları **tam metinden** teyit edilir (Springer/Nature/PMC erişimi olan
   ortamda).

---

## 9. `ZBRIDGE_DESIGN.md` ile ilişki ve değişiklikler

- **Geçerli kalır:** §A (denetim), §B (taşıma haritası), §C (depo yapısı), §D (veri modeli, kenar şeması,
  manifest), §G (test planı), §H (risk kaydı), Ek J (hazır gövde).
- **Değişir:** §E (yöntem) → bu belgenin §4'ü. Özellikle: `b_ij` artık **RNF/lfdr** (deterministik+kalibre),
  Z çekirdeği **footprint**, hizalama **posterior + S örnek**, eğitim **L_rep**.
- **Hata düzeltmesi (ZBRIDGE_DESIGN.md E.1 ve H#14):** orada "PASTE GPL-3 olabilir" demiştim; PASTE ve PASTE2
  README/lisans sayfalarında **BSD-3-Clause** görünüyor. PASTE/PASTE2 bağımlılık olarak **kullanılabilir**
  (BSD-3; lisans metni korunur). STitch3D, GPSA MIT; SPACEL lisansı belirsiz (kullanmadan teyit).
- **Yeni modüller:** `analysis/replicate/noise_floor.py` (M1), `graph/footprint_kernel.py` (M2),
  `registration/posterior.py` (M3), `model/replicate_risk.py` (M4), `model/uncertainty.py` (MI ayrıştırma).
- **Faz değişikliği:** Faz 2b (fantom) **ve** "RNF kalibrasyon" Faz 3'ten önce; Faz 3'e `posterior.py` eklenir;
  Faz 5'e footprint çekirdeği; Faz 6–8 L_rep ile birleşir; ablasyon `A0–A7`.

## 10. Riskler (yeni mekanizmalara özgü)

| Risk | Azaltma |
|---|---|
| Kesit≠replika (Δz, kıvrım) null'ı şişirir/çarpıtır | muhafazakâr null; nugget/üçgen testi; H1–H2 |
| Gürültü bağımsızlığı ihlali (ambient RNA, difüzyon) | halka maskesi `r_amb`; Xenium/MERFISH için ayrı doğrulama |
| `D` ölçeğinin NB aşırı dağılımı yanlışlığı | replika-medyanı yeniden ölçekleme; teşhis çıktısı |
| `S` örnekli eğitim maliyeti | `S` küçük (8); CPU bütçesi ölçümü; gerekirse S=1 + sonradan MC |
| Laplace posterior'ın düşük kalitesi | replika-kalibre şişirme; fantomda kapsama testi (H3) |
| L_rep kapıyı "bilgisizlik" yüzünden kapatır (sınır sanılır) | M1 `b` ön-bilgisi; bias/varyans ayrımı için komşu sayısına koşullu raporlama |
| Aşırı mühendislik | her mekanizma için H-testi; başarısızsa çıkar (§6 "öldürme" ölçütleri) |
