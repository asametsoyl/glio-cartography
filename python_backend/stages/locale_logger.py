import os
import re
import logging
from loguru import logger

GLIO_LANG = os.environ.get("GLIO_LANG", "tr").lower()
is_english = (GLIO_LANG == "en")

if is_english:
    LOG_MAP = {
        "Background imajı symlink ile bağlandı.": "Background image linked via symlink.",
        "Background imajı zaten mevcut.": "Background image already exists.",
        "Symlink başarısız": "Symlink failed",
        "Background imajı kopyalandı.": "Background image copied.",
        "scRNA-seq yükleniyor:": "Loading scRNA-seq:",
        "10X HDF5 (.h5) formatı tespit edildi, sc.read_10x_h5 ile yükleniyor...": "10X HDF5 (.h5) format detected, loading with sc.read_10x_h5...",
        "10X .h5 yüklendi:": "10X .h5 loaded:",
        "QC Uyarı": "QC Warning",
        "Doublet tespiti yalnızca gen sayı sınırına dayanmaktadır. Büyük/hiperaktif hücreler etkilenebilir.": "Doublet detection is only based on gene count threshold. Large/hyperactive cells may be affected.",
        "scRNA MT filtering threshold": "scRNA MT filtering threshold",
        "QC sonrası": "Post-QC shape",
        "Verinin raw count olduğu tespit edildi, normalize_total uygulanıyor.": "Data detected as raw counts, applying normalize_total.",
        "scRNA diske yazılıyor": "Writing scRNA to disk",
        "scRNA kaydedildi": "scRNA saved",
        "Spatial veri yükleniyor:": "Loading spatial data:",
        "Spatial neighbors hesaplanıyor": "Calculating spatial neighbors",
        "Spatial UMAP hesaplanıyor...": "Spatial UMAP calculating...",
        "Spatial Leiden kümeleniyor...": "Spatial Leiden clustering...",
        "Spatial veri diske yazılıyor": "Writing spatial data to disk",
        "Spatial kaydedildi": "Spatial saved",
        "Stage 1 tamamlandı": "Stage 1 completed",
        "Veri yükleniyor...": "Loading data...",
        "Hücre tipi anotasyonu...": "Cell type annotation...",
        "insufficient markers": "insufficient markers",
        "skipping": "skipping",
        "Hücre tipleri:": "Cell types:",
        "Marker gen çıkarımı (rank_genes_groups)...": "Marker gene extraction (rank_genes_groups)...",
        "Klinik markerlar (her iki veri kümesinde):": "Clinical markers (in both datasets):",
        "gen için Moran's I hesaplanıyor (vektörize)...": "genes calculating Moran's I (vectorized)...",
        "Moran's I filtresi:": "Moran's I filter:",
        "Final marker gen sayısı:": "Final marker gene count:",
        "Dekonvolüsyon yöntemi:": "Deconvolution method:",
        "Tangram pp_adatas çalıştırılıyor...": "Running Tangram pp_adatas...",
        "Tangram mapping tamamlandı": "Tangram mapping completed",
        "Projeksiyon yapılıyor...": "Projecting...",
        "Dekonvolüsyon tamamlandı": "Deconvolution completed",
        "Kaydedildi:": "Saved:",
        "Figürler oluşturuluyor...": "Generating figures...",
        "Stage 2 tamamlandı": "Stage 2 completed",
        "Graf oluşturuluyor...": "Building graph...",
        "Graph verisi (HeteroData) oluşturuluyor...": "Building graph data (HeteroData)...",
        "GNN eğitimi (100 epoch)...": "GNN training (100 epochs)...",
        "Jüri Özel: GNN Tahmini vs IVY GAP Pseudo Ground Truth Karşılaştırması...": "Jury Special: GNN Prediction vs IVY GAP Pseudo Ground Truth Comparison...",
        "Stage 3 tamamlandı": "Stage 3 completed",
        "Sonuç verileri yükleniyor...": "Loading results data...",
        "yüklendi:": "loaded:",
        "Yüksek Risk:": "High Risk:",
        "Düşük Risk:": "Low Risk:",
        "Ortalama skor:": "Mean score:",
        "Yüksek çözünürlüklü makale grafikleri": "High-resolution publication figures",
        "Diferansiyel test yöntemi:": "Differential testing method:",
        "Volcano plot çizildi": "Volcano plot plotted",
        "Bipartite network": "Bipartite network",
        "Stage 4 tamamen bitti": "Stage 4 completed",
        "Stage 5 tamamlandı": "Stage 5 completed",
        "Veri yükleniyor:": "Loading data:",
        "Optuna (": "Optuna (",
        "Best val:": "Best val:",
        "Test maskesi boş veya tanımlanmamış — MSE ve korelasyonlar hesaplanamadı.": "Test mask empty or undefined — MSE and correlations could not be calculated.",
        "Test CT MSE:": "Test CT MSE:",
        "Korelasyon hesaplanamadı": "Correlation could not be calculated",
        "Eğitim grafiği çizilemedi:": "Training plot could not be drawn:",
        "ZONE_SIGNATURES'ta bulunup ZONE_NAMES listesinde tanımlı olmayan bölge(ler) var:": "Zone(s) found in ZONE_SIGNATURES but not defined in ZONE_NAMES list:",
        "⚠️ IVY GAP zone genlerinin hiçbiri veri setinde bulunamadı! Zone karşılaştırma analizi atlanıyor.": "⚠️ None of the IVY GAP zone genes found in the dataset! Zone comparison analysis is skipped.",
        "⚠️ IVY GAP core spot maskesi boş çıktı, karşılaştırma metrikleri hesaplanamadı.": "⚠️ IVY GAP core spot mask is empty, comparison metrics could not be calculated.",
        "Validation sonrası özet JSON güncellenemedi:": "Summary JSON could not be updated after validation:",
        "IVY GAP karşılaştırma grafikleri çizilemedi:": "IVY GAP comparison plots could not be drawn:",
        "IVY GAP core spot maskesi boş çıktı, karşılaştırma metrikleri hesaplanamadı.": "IVY GAP core spot mask is empty, comparison metrics could not be calculated.",
        "Tangram bulunamadı:": "Tangram not found:",
        "Tangram model eğitimi (num_epochs=500, verbose=False)...": "Tangram model training (num_epochs=500, verbose=False)...",
        "Tangram sütun sayısı uyuşmuyor:": "Tangram column count mismatch:",
        "cell2location bulunamadı:": "cell2location not found:",
        "Cell2Location: referans model hazırlanıyor...": "Cell2Location: preparing reference model...",
        "mitokondriyal gen kaldırıldı.": "mitochondrial genes removed.",
        "Cell2Location: mekansal model eğitimi (max_epochs=3000)...": "Cell2Location: spatial model training (max_epochs=3000)...",
        "scvi-tools (Stereoscope) bulunamadı:": "scvi-tools (Stereoscope) not found:",
        "Stereoscope: scRNA referans modeli eğitimi (max_epochs=300)...": "Stereoscope: scRNA reference model training (max_epochs=300)...",
        "Stereoscope: mekansal model eğitimi (max_epochs=1500)...": "Stereoscope: spatial model training (max_epochs=1500)...",
        "Fallback: score_genes bazlı softmax dekonvolüsyon...": "Fallback: score_genes based softmax deconvolution...",
        "Config yüklendi:": "Config loaded:",
        "Config yüklenemedi": "Config load failed",
        "hücre hiçbir markera skor alamadı": "cells got no score for any marker",
        "raw layer bulunamadı, normalleştirme uygulanıyor": "raw layer not found, applying normalization",
        "Moran's I filtresi:": "Moran's I filter:",
        "Moran's I başarısız": "Moran's I failed",
        "Cell2Location başarısız": "Cell2Location failed",
        "Stereoscope başarısız": "Stereoscope failed",
        "Tangram başarısız": "Tangram failed",
        "Hoyer Sparsity — Mean:": "Hoyer Sparsity — Mean:",
        "Mean Entropy:": "Mean Entropy:",
        "Bipartite network çizildi.": "Bipartite network plotted.",
        "Volcano plot çizildi.": "Volcano plot plotted.",
        "Bipartite network adaptif eşiği:": "Bipartite network adaptive threshold:",
        "Kaplan-Meier özeti": "Kaplan-Meier summary",
        "Zone haritası": "Zone map",
        "Drug score haritası": "Drug score map",
        "Risk haritası": "Risk map",
        "Zone bar chart": "Zone bar chart",
        "Dinamik L-R çiftleri": "Dynamic L-R pairs",
        "L-R iletişim haritası": "L-R communication map",
        "Risk stratifikasyonu": "Risk stratification",
        "survival_predictions.npy yüklendi": "survival_predictions.npy loaded",
        "Risk eşiği (medyan):": "Risk threshold (median):",
        "Kaplan-Meier özeti JSON'a yazıldı": "Kaplan-Meier summary written to JSON",
        "Doku Zon Değişimleri (Canlı Çıkarım):": "Tissue Zone Shifts (Live Inference):",
        "GNN Hücre Baskılama başarıyla simüle edildi": "GNN Cell Knockout successfully simulated",
        "Hacim": "Volume",
        "Güç": "Intensity",
        
        # New additions for user's logs
        "Advanced Figures eklendi.": "Advanced Figures added.",
        "başarısız": "failed",
        "fallback deneniyor...": "trying fallback...",
        "yüklendi": "loaded",
        "kaydedildi": "saved",
        "hesaplanıyor": "calculating",
        "kümeleniyor": "clustering",
        "korundu.": "kept.",
        "eklendi.": "added.",
        "Yüksek Risk": "High Risk",
        "Düşük Risk": "Low Risk",
        "Ortalama skor": "Mean score",
        "Yüksek=": "High=",
        "Düşük=": "Low=",
        "Yüksek çözünürlüklü makale grafikleri (Volcano, L-R Heatmap, Bipartite) hazırlanıyor...": "Preparing high-resolution publication figures (Volcano, L-R Heatmap, Bipartite)...",
        "🌐 Dinamik L-R çiftleri OmniPath veritabanından indiriliyor...": "🌐 Downloading dynamic L-R pairs from OmniPath database...",
        "aktif L-R çifti başarıyla çekildi.": "active L-R pairs successfully fetched.",
        "OmniPath L-R çiftleri indirilemedi": "Could not download OmniPath L-R pairs",
        "Yerel GBM kataloğu kullanılıyor.": "Using local GBM catalog.",
        "L-R iletişim haritası (hücre-hücre iletişim skoru)": "L-R communication map (cell-cell communication score)",
        "Risk stratifikasyonu (GNN-tahminli) oluşturuluyor...": "Risk stratification (GNN-predicted) generating...",
        "Tahmini medyan OS": "Predicted median OS",
        "Risk stratifikasyon figürü — medyan OS tahmini:": "Risk stratification figure — median OS prediction:",
        
        # pathway_mapper additions
        "🌐 Cytoscape.js indiriliyor:": "🌐 Downloading Cytoscape.js:",
        "yerel olarak kaydedildi:": "saved locally:",
        "indirilemedi:": "could not be downloaded:",
        "Yolak veritabanı okunamadı:": "Pathway database could not be read:",
        "data.json okunamadı (zone maskeleri):": "data.json could not be read (zone masks):",
        "data.json attention weights okunamadı:": "data.json attention weights could not be read:",
        "dataset içinde bulunamadı.": "not found in the dataset.",
        "hesaplandı (": "calculated (",
        "bulunamadı. Global analiz yapılıyor.": "not found. Performing global analysis.",
        "spot kullanılıyor.": "spots are used.",
        "KEGG koordinatları indirilemedi": "Could not download KEGG coordinates",
        "🌐 KEGG haritası indiriliyor:": "🌐 Downloading KEGG map:",
        "KEGG haritası indirilemedi:": "Could not download KEGG map:",
        "Harita koordinatları bulunamadı:": "Map coordinates not found:",
        "Harita overlay çizim hatası:": "Map overlay drawing error:",
    }

    def translation_patcher(record):
        msg = record["message"]
        # Apply standard mappings
        for key, val in LOG_MAP.items():
            if key in msg:
                msg = msg.replace(key, val)
        
        # Apply regex rules for units and counts
        msg = re.sub(r'\bgenler\b', 'genes', msg)
        msg = re.sub(r'\bgeni\b', 'gene', msg)
        msg = re.sub(r'\bgen\b', 'genes', msg)
        msg = re.sub(r'\bhücreler\b', 'cells', msg)
        msg = re.sub(r'\bhücresi\b', 'cell', msg)
        msg = re.sub(r'\bhücre\b', 'cells', msg)
        msg = re.sub(r'\bspotlar\b', 'spots', msg)
        msg = re.sub(r'\bspot\b', 'spots', msg)
        msg = re.sub(r'\bkomşu\b', 'neighbors', msg)
        msg = re.sub(r'(\d+(?:\.\d+)?)\s*ay\b', r'\1 months', msg)
        
        record["message"] = msg

    logger.configure(patcher=translation_patcher)

    # Intercept standard library logging messages
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame, depth = logging.currentframe(), 2
            while frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    # Set the handler on the root logging logger
    root_log = logging.getLogger()
    # Remove existing handlers to prevent duplicate formatting or loops
    for h in list(root_log.handlers):
        root_log.removeHandler(h)
    root_log.addHandler(InterceptHandler())
    root_log.setLevel(logging.INFO)


