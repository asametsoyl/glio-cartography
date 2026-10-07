# Faz 3 — Registration: ne yapıldı, ne ölçüldü, ne çalışmıyor

Kod: `spatialcore/registration/` (`soft_correspondence.py` EM, `rigid.py`, `affine.py`, `confidence.py`, `chain.py`),
`spatialcore/qc/pairwise.py`, `spatialcore/preprocessing/features.py`. Testler: `tests/spatialcore/test_registration_*.py`.
Betikler: `benchmarks/phantom_registration_eval.py`, `benchmarks/dlpfc_registration_check.py`.

## Yöntem (kısa)
CPD benzeri EM; olabilirlik = Gauss(koordinat) × expression oranı `exp(λ cos)/Z_i` (Z_i komşu kesit üzerinden ortalama,
yani gerçek bir yoğunluk; normalize edilmediğinde kısmi örtüşmede çözüm dejenere oluyordu) + "karşılığı yok" bileşeni.
Çok-başlangıçlı (24 dönüş) kaba arama → rigid ince ayar → cilalama. Varsayılan model **rigid**; `similarity`/`affine`
istek üzerine. Posterior'un yan ürünü: spot başına `p_null` (komşu kesitte doku yok) → `overlap_up/down`.

## Fantomda ölçülenler (tohum 1–12; eşikler `ZBRIDGE_DESIGN.md` Faz 3)
| Katman | çift düzeyi spot hatası (medyan) | not |
|---|---|---|
| **E** | **≈4 µm** (dönme medyan 0,3°, en kötü ≈1,3°; ölçek hatası ~0) | tasarım eşikleri (<1°, <0,25 aralık=25 µm, <%2 ölçek) **testte sağlanıyor** |
| M | ≈30–40 µm | ölçek ±3 %, kayma, non-rigid 20 µm, %80 örtüşme: rigid model bunları modellemiyor |
| H | ≈60–90 µm | yırtık/doku kaybı/gen-batch; **eşikler sağlanmıyor** |

Zincir (E, 6 çift): bölüm başına medyan hata ≤ 22 µm; `sigma_reg` yalnız birikir (test).

Önemli bulgular (taramalarla):
- **σ tabanı**: `sigma_min_um` 20→60 µm, hatayı 9–14 µm'den ≈4 µm'ye indirdi — küçük σ'da uyum Visium ızgarasına yapışıyor.
- **Fantomun dokusu**: domain-içi pürüzsüz ifade olmadan (6 parçalı-sabit domain) kısmi örtüşmede rotasyon belirsiz kalıyordu;
  fantoma `smooth_programs` eklendi. Bu bir fantom düzeltmesidir, algoritma değil.
- **Affine**, gerçek model rigid iken daha kötü (bias); varsayılan rigid.

## Güven ve belirsizlik: dürüst durum
- `overlap_*` (= 1 − p_null): komşu kesitte doku var mı? AUC **0,96–0,98** (M, H; fantom gerçeğine karşı). Sağlam.
- `registration_confidence` (ham): **konum hatasını** spot düzeyinde zayıf ayırt eder (AUC 0,58–0,62), çünkü hata
  çoğunlukla çift düzeyindedir. Kalibratör (`IsotonicCalibrator`) hazır ama bu skor için kullanışlı bir hedef yok;
  konum belirsizliği için çift düzeyi `sigma_pos_um` kullanılmalıdır.
- `sigma_pos_um` = Laplace-tipi istatistiksel varyans ⊕ (κ · rigid↔affine uyuşmazlığı). Yalnız istatistiksel kısım
  M'de hatayı ~6,5× düşük tahmin ediyordu (model yanlış belirtimi); uyuşmazlık terimi ile (κ=0,8, tohum 5–8'de ayarlı)
  **bağımsız tohum 9–12'de** tahmin/gerçek: E medyan oranı 0,4 (aşırı örtme), M 0,8, H 0,6 (p90 ≤ 1,3 → hata ≤ tahmin).
  κ fantomda ayarlıdır; gerçek veride doğrulanmadı.

## QC (`PairQC`)
Metrikler: `overlap`, `expr_gain`, `coherence` (bir kesitin kendi uzamsal tutarlılığı), `deformation_um`, ölçek, kayma.
Eşikler fantomdan başlangıç değerleridir (`QCConfig`). Fantomda: iyi çift PASS; **karıştırılmış spotlar** (coherence≈0)
FAIL; **başka doku** (expr_gain≈0,005 vs iyi 0,03–0,04) FAIL. Not: karıştırılmış spotlarda `expr_gain` **yükseliyor**
(seçim yanlılığı) — tek başına güvenilmez, bu yüzden `coherence` eklendi.

## Gerçek veri: DLPFC (etiket kullanılmadı, yalnız skorlamada)
`registered komşu en-yakın spot katman uyumu` vs 500 µm kaydırılmış null:
| Çift | uyum | null | QC |
|---|---|---|---|
| Br8100 673→674 (10 µm) | 0,86 | 0,58 | PASS |
| Br8100 674→675 (~300 µm) | 0,85 | 0,51 | WARNING (deformasyon 78 µm) |
| Br8100 675→676 (10 µm) | 0,84 | 0,58 | PASS |
| Br5292 507→508 (10 µm) | 0,82 | 0,82 | PASS (null ayırt edici değil: katmanlar x yönünde şeritli) |
| **Br5292 508→509 (~300 µm)** | **0,56** | 0,73 | **FAIL** (deformasyon 577 µm) |
| Br5292 509→510 (10 µm) | 0,86 | 0,80 | PASS |

**Çalışmayan:** Br5292 508→509 hiçbir ayarda (rigid/similarity, 48 başlangıç, λ=20, w=0,4, yansıma izni) çözülmedi;
QC bunu doğru biçimde FAIL işaretliyor. Nedenini bilmiyorum (dokunun gerçekten farklı olması mı, non-rigid mi);
Faz 13 (non-rigid) ve histoloji ile yeniden bakılmalı. Br5292 507→508 için null zayıf olduğundan bu çiftin doğruluğu
bu ölçütle kanıtlanmış değildir.

## Bilinen eksikler
- Hız: 3,6k spotluk DLPFC çiftleri ≈ 30–50 s/çift (yoğun N×M blokları, `refine_points` alt örnekleme ile); büyük
  veri için aday-yarıçap (seyrek) E-adımı gerekir.
- Posterior örnekleme/ M3 (`registration/posterior.py`) yapılmadı; `cov_unit` + `deformation` yalnız yaklaşık Laplace.
- Histoloji tabanlı ilklendirme yok; tek-kesit-bozuk (üçgen testi, M1) henüz yok.
- Yansıma (`allow_flip`) uygulandı, fantomda sınanmadı.
