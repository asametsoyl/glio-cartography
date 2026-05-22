# 🗺️ Glio-Cartography: Gelecek Yol Haritası ve Geliştirme Planı (Roadmap)

Bu plan, Glio-Cartography'nin ana amacı olan **Mekansal Tümör Mikroçevresi (TME) Analizi ve Karar Destek Sistemi** odağını kaybetmeden, platformun bilimsel derinliğini, simülasyon yeteneklerini ve arayüz performansını artırmayı hedefler.

---

## 🧬 1. Biyolojik ve Algoritmik Geliştirmeler (Model Depth)

### 1.1 Gelişmiş GNN Mimarileri ve Ayrıntılı Hücresel İletişim
*   **Graph Attention Networks (GATv2) Entegrasyonu:** Mevcut 5-head GNN modelini dinamik dikkat ağırlıklarına sahip GATv2 mimarisine yükselterek, tümör-immün sınırlarındaki hücreler arası sinyal yolaklarının yönünü ve gücünü daha hassas tahmin etmek.
*   **Parakrin Etki Modellemesi:** Bir spotta simüle edilen ilaç etkisinin (örneğin ligand baskılanmasının), GNN komşuluk matrisi kullanılarak çevre spotlardaki hücrelerin transkriptomik durumlarına olan kausal yayılım etkisini simüle etmek.
*   **Veri Tabanı Genişletmesi:** Ligand-reseptör eşleşme veri tabanına **CellChat v2** ve **Omnipath** entegrasyonu sağlayarak kemokin, sitokin ve hücre dışı matris (ECM) etkileşim havuzunu genişletmek.

### 1.2 Klinik ve Prognostik Doğrulama Kohortları
*   **Çoklu Dış Kohort Desteği:** Mevcut TCGA tabanlı Cox orantılı risk modeline **CGGA (Chinese Glioma Genome Atlas)** ve **Ivy GAP (Anatomic Transcriptional Atlas of the Glioblastoma)** kohortlarını eklemek.
*   **Zon-Spesifik Risk Skoru:** Tüm dokunun ortalama skoru yerine, sadece mikrovasküler proliferasyon (MVP) veya nekroz çeperindeki (PAN) spotların risk ağırlıklarını hesaplayarak daha lokalize prognostik öngörüler sunmak.

---

## 🖥️ 2. Arayüz ve Görselleştirme Atlası (UI/UX & Performance)

### 2.1 Büyük Veri Setleri İçin WebGL Rendering
*   **10,000+ Spot Performansı:** Mevcut HTML5 Canvas2D yapısını **Three.js / WebGL** tabanlı nokta bulutu (point cloud) çizim motoruna taşımak. Bu sayede 10X daha büyük spatial transkriptomik kesitlerin sıfır kasma ile akıcı şekilde yaklaştırılıp kaydırılmasını (pan/zoom) sağlamak.
*   **H&E Doku Altlığı Piramit Görüntüleme:** Yüksek çözünürlüklü histopatoloji (H&E) görüntülerinin (tiff/svs formatları) yavaş yüklenmesini engellemek için **DeepZoom / Tile-based** piramit yükleme yapısına geçmek.

### 2.2 Karşılaştırmalı Analiz (Side-by-Side Mode)
*   **Primer vs. Nüks Karşılaştırması:** Aynı hastanın farklı zamanlardaki veya farklı bölgelerinden alınan iki ayrı doku kesitini yan yana senkronize pan/zoom ile inceleme modu.
*   **Tedavi Öncesi / Sonrası Simülasyonu:** Sol ekranda orijinal dokuyu, sağ ekranda ise birden fazla ilacın kombine simülasyon etkisini (örneğin Bevacizumab + Temozolomide) eş zamanlı izleyebilme.

---

## 🛠️ 3. Yazılım Altyapısı ve Dağıtım (Software & DevOps)

### 3.1 Lisans ve Güncelleme Sunucu Entegrasyonu
*   **Çevrimiçi (Online) Hızlı Aktivasyon:** İstemci tarafındaki simetrik anahtar doğrulamasını korurken, kullanıcının lisansı tek tıkla internet üzerinden aktif edebilmesi için hafif bir lisans sunucusu (Licensing API) entegrasyonu.
*   **Otomatik Yamalama (Delta Updates):** Büyük backend paketleri yerine sadece değişen Python betiklerini ve Electron kodlarını güncelleyen akıllı güncelleme (auto-updater) mekanizması.

### 3.2 Gelişmiş Raporlama ve Dışa Aktarım
*   **Klinik PDF Rapor v3.0:** Rapor tasarımlarına dinamik mini SVG haritaları ve interaktif grafik köprüleri eklemek.
*   **Seurat/Squidpy Uyumlu Export:** Kullanıcının görselleştirdiği analiz sonuçlarını doğrudan `.h5ad` (AnnData) veya Seurat nesnesi formatında indirip kendi R kodlarında çalışabilmesini sağlamak.
