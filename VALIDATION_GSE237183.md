# GSE237183 bağımsız Visium doğrulaması

Tarih: 15 Eylül 2026

## Amaç ve kapsam

Bu çalışma, Glio-Cartography analiz hattının geliştirme örneklerinden bağımsız bir açık Visium kohortunda teknik olarak uçtan uca çalışabildiğini sınar. GSE237183'ten iki hastanın eşlenmiş infiltrasyon ve T1-kontrastlanan tümör bölgeleri seçildi. sc/snRNA-seq referansı, aynı çalışmadan değil, bağımsız GSE331374 primer glioblastoma çekirdek verisinden alındı.

Bu test klinik geçerlilik, tanı doğruluğu, tedavi yanıtı veya hasta sonucu doğrulaması değildir. Zon çıktıları patolog anotasyonu değil, Ivy GAP esinli transkripsiyonel hipotezlerdir.

## Veri ve protokol

- Visium kohortu: NCBI GEO GSE237183 (19 kesitlik kohorttan dört anonim örnek)
- sc/snRNA-seq referansı: GSE331374 primer tümör örneği; QC sonrası 1.644 çekirdek ve 15.161 gen
- Dekonvolüsyon: Tangram; her örnekte NNLS ile yöntemler arası uyum kontrolü
- GNN: hızlı bağımsız veri doğrulaması için 20 epoch; sonuçlar performans üst sınırı olarak yorumlanmamalıdır
- Dış atlas kontrolü: 25 genlik Ivy GAP ISH paneli; teknoloji ve hasta eşleşmesi yoktur

## Sonuçlar

| GEO örneği | Bölge | QC sonrası spot | Gen | Tangram fallback | Tangram–NNLS uyumu | Held-out CT MSE | Ivy diagonal korelasyon | Ivy top-1 |
|---|---|---:|---:|---|---:|---:|---:|---:|
| GSM7596588 | ZH881 infiltrating | 1.074 | 13.097 | Hayır | 0,3362 | 0,01730 | 0,2042 | 0,40 |
| GSM7596589 | ZH881 T1 contrast-enhancing | 2.781 | 16.680 | Hayır | 0,3711 | 0,00922 | 0,3930 | 0,60 |
| GSM7596591 | ZH916 infiltrating | 1.101 | 14.068 | Hayır | 0,2743 | 0,01982 | -0,0930 | 0,20 |
| GSM7596592 | ZH916 T1 contrast-enhancing | 2.491 | 17.154 | Hayır | 0,2887 | 0,00876 | 0,3550 | 0,60 |

Toplam 7.447 spot işlendi ve dört örneğin tamamında beş aşama (ön işleme, dekonvolüsyon, GNN, görselleştirme ve araştırma raporu) tamamlandı. Tangram hiçbir örnekte fallback yöntemine düşmedi. Ortalama yöntemler arası uyum 0,3176; ortalama held-out CT MSE 0,01378'dir.

## Dürüst yorum

Teknik genellenebilirlik sinyali olumludur: iki farklı hastanın hem infiltrasyon hem kontrastlanan bölgesi aynı bağımsız sc/snRNA referansıyla eksiksiz işlendi. Bununla birlikte biyolojik zon karşılığı örnekler arasında değişkendir. Özellikle GSM7596591'de Ivy diagonal korelasyonu -0,093 ve top-1 eşleşme 0,20'dir. Bu olumsuz sonuç saklanmamalı; küçük panel, eşleşmemiş hasta/teknoloji ve kısa eğitim koşullarıyla birlikte raporlanmalıdır. Dört örneğin ortalama Ivy diagonal korelasyonu 0,2148, top-1 eşleşmesi 0,45'tir.

Bu sonuçlar “klinik olarak doğrulandı” iddiasını desteklemez. Desteklediği daha dar iddia şudur: uygulama, bağımsız ve heterojen açık Visium kesitlerini farklı bir çalışmadan alınan sc/snRNA referansıyla uçtan uca işleyebilmekte; belirsiz ve başarısız biyolojik eşleşmeleri de görünür biçimde raporlamaktadır.

## Tekrarlanabilirlik notları

- GSE237183 kaynak görüntü, pozisyon ve filtrelenmiş matris dosyaları NCBI GEO eklerinden indirildi.
- Çalışma çıktıları geçici çalışma alanında `/tmp/glio-public-validation/GSE237183/outputs/` altında tutuldu.
- Dört araştırma PDF'i `output/pdf/` altında arşivlendi.
- Gerçek takip verisi bulunmadığından Kaplan–Meier ve medyan sağkalım üretimi otomatik olarak atlandı.
