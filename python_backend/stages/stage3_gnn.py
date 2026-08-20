#!/usr/bin/env python3
"""Stage 3: GNN training and evaluation — GlioCartographyGNN"""
import os, sys, json, shutil, traceback, threading
from pathlib import Path

# ── Import matplotlib first and configure headless mode ───────────────────────
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Project Path & PyInstaller Support ───────────────────────
PROJECT_ROOT = Path(os.environ.get(
    "GLIO_PROJECT_ROOT",
    sys._MEIPASS if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent.parent.parent
))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if getattr(sys, 'frozen', False):
    BACKEND_DIR = Path(sys._MEIPASS) / "desktop_app" / "python_backend"
else:
    BACKEND_DIR = Path(__file__).resolve().parent.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

OUTPUT_DIR    = Path(os.environ["GLIO_OUTPUT_DIR"])
GNN_EPOCHS    = int(os.environ.get("GLIO_GNN_EPOCHS", "100"))
RUN_OPTUNA    = os.environ.get("GLIO_RUN_OPTUNA", "0") == "1"
OPTUNA_TRIALS = int(os.environ.get("GLIO_OPTUNA_TRIALS", "5"))

GLIO_LANG = os.environ.get("GLIO_LANG", "tr").lower()
is_english = (GLIO_LANG == "en")

from loguru import logger
import locale_logger
import anndata as ad
import numpy as np
import torch
import torch.nn.functional as F
from scipy.stats import pearsonr, spearmanr
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns

# Import GNN from train_gnn.py
from train_gnn import (
    build_graph_data, GlioCartographyGNN, train_model,
    export_attention_to_json, mc_dropout_zone_uncertainty,
    ZONE_NAMES, LR_PAIRS
)

def exit_with_error(message):
    logger.error(message)
    print(json.dumps({"stage": "gnn_training", "status": "error", "message": message}))
    sys.exit(1)

def report_progress(percent):
    print(json.dumps({"stage": "gnn_training", "status": "running", "progress": percent}))

class OptunaProgressTracker:
    def __init__(self, total_trials):
        self.total_trials = total_trials
        self.current_trial = 0
        self.lock = threading.Lock()

    def get_callback(self):
        def optuna_epoch_callback(ep, total_eps):
            with self.lock:
                t_idx = self.current_trial
            trial_weight = 35.0 / self.total_trials
            trial_start = 15.0 + t_idx * trial_weight
            pct = trial_start + trial_weight * (ep / total_eps)
            report_progress(int(pct))
        return optuna_epoch_callback

    def increment(self):
        with self.lock:
            self.current_trial += 1

def main():
    # ── Reproducibility seeds ─────────────────────────────────────
    torch.manual_seed(42)
    np.random.seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)

    report_progress(5)
    
    # OUTPUT_DIR is required to be writable
    gnn_out = OUTPUT_DIR / "gnn"
    try:
        gnn_out.mkdir(parents=True, exist_ok=True)
    except Exception as e_mkdir:
        raise RuntimeError(f"GNN çıktı dizini oluşturulamadı ({gnn_out}): {e_mkdir}")

    # ── Load deconvolved data ─────────────────────────────────────
    spatial_path = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
    logger.info(f"📂 Veri yükleniyor: {spatial_path}")
    try:
        adata = ad.read_h5ad(spatial_path)
    except Exception as e_load:
        raise RuntimeError(f"Ön işlenmiş dekonvolüsyon verisi yüklenemedi: {e_load}")

    report_progress(10)

    # ── Build graph ──────────────────────────────────────────────
    logger.info("🔗 Graf oluşturuluyor...")
    try:
        data = build_graph_data(adata, k_neighbors=6)
    except Exception as e_graph:
        raise RuntimeError(f"Graf oluşturulurken hata: {e_graph}")
    
    ct_names = data.ct_names
    report_progress(15)

    # ── Train ────────────────────────────────────────────────────
    logger.info(f"🧠 GNN eğitimi ({GNN_EPOCHS} epoch)...")

    def make_progress_callback(start_pct, end_pct):
        def callback(ep, total_eps):
            pct = start_pct + (end_pct - start_pct) * (ep / total_eps)
            report_progress(int(pct))
        return callback

    if RUN_OPTUNA:
        import optuna
        from train_gnn import objective
        logger.info(f"   Optuna ({OPTUNA_TRIALS} trial)...")
        study = optuna.create_study(direction='minimize',
                                    pruner=optuna.pruners.MedianPruner(n_startup_trials=3))
        
        tracker = OptunaProgressTracker(OPTUNA_TRIALS)

        def wrapped_objective(t):
            val = objective(t, data, epoch_callback=tracker.get_callback())
            tracker.increment()
            return val

        study.optimize(wrapped_objective, n_trials=OPTUNA_TRIALS)
        cfg = {**study.best_params, 'epochs': GNN_EPOCHS, 'patience': 30}
        logger.info(f"   Best val: {study.best_value:.4f}")
        final_callback = make_progress_callback(50.0, 90.0)
    else:
        cfg = {'hidden': 128, 'heads': 4, 'drop': 0.3, 'lr': 1e-3,
               'n_gat': 2, 'n_sage': 1, 'epochs': GNN_EPOCHS, 'patience': 30}
        final_callback = make_progress_callback(15.0, 90.0)

    try:
        model, hist, best_val = train_model(data, cfg=cfg, epoch_callback=final_callback)
    except Exception as e_train:
        raise RuntimeError(f"GNN eğitimi sırasında hata: {e_train}")
        
    report_progress(90)

    # ── Evaluate ─────────────────────────────────────────────────
    model.eval()
    with torch.no_grad():
        ct_pred, zone_pred, surv_pred, drug_pred, emb, _ = model(data)

    zone_np = F.softmax(zone_pred, dim=-1).cpu().numpy()
    surv_np = surv_pred.cpu().numpy()
    drug_np = drug_pred.cpu().numpy()

    # MC-Dropout belirsizlik tahmini [GELİŞTİRME] — spot detay panelinde
    # "modelin bu tahmine ne kadar güvendiğini" göstermek için. Maliyeti
    # düşük tutmak için sabit bir örnek sayısı kullanılıyor; env değişkeniyle
    # ayarlanabilir.
    try:
        _mc_n = int(os.environ.get("GLIO_MC_DROPOUT_SAMPLES", "20"))
        _, zone_uncertainty_np = mc_dropout_zone_uncertainty(model, data, n_samples=_mc_n)
        logger.info(f"   MC-Dropout belirsizlik tahmini tamamlandı ({_mc_n} örnek).")
    except Exception as e_mc:
        logger.warning(f"   MC-Dropout belirsizlik tahmini hesaplanamadı: {e_mc}")
        zone_uncertainty_np = None

    # ── Verify test mask and compute MSE ─────────────────────────
    has_test_mask = 'test_mask' in data['spot'] and data['spot'].test_mask is not None and data['spot'].test_mask.sum().item() > 0
    if not has_test_mask:
        logger.warning("   Test maskesi boş veya tanımlanmamış — MSE ve korelasyonlar hesaplanamadı.")
        test_mse = float('nan')
    else:
        test_mask = data['spot'].test_mask
        pred_test = ct_pred[test_mask]
        y_test = data['spot'].y[test_mask]
        if pred_test.shape != y_test.shape:
            raise ValueError(f"Şekil uyuşmazlığı: GNN hücre tipi tahmini {pred_test.shape} ve gerçek dekonvolüsyon değerleri {y_test.shape} uyuşmuyor!")
        test_mse = F.mse_loss(pred_test, y_test).item()
        logger.info(f"   Test CT MSE: {test_mse:.6f}")

    # ── Save model ─────────────────────────────────────────────────
    try:
        try:
            from safetensors.torch import save_file
            save_file(model.state_dict(), gnn_out / "glio_gnn_v3.safetensors")
            logger.info("   Model saved in safetensors format.")
        except ImportError:
            pass
        torch.save(model.state_dict(), gnn_out / "glio_gnn_v3.pt")
    except Exception as e_save:
        raise RuntimeError(f"Model kaydedilemedi: {e_save}")

    # ── JSON export ──────────────────────────────────────────────
    # NOT: export_attention_to_json, `drug_np`/`surv_np` ham (eğitilmemiş
    # drug_head çıktısı / hasta-seviyesi tek skaler survival_head çıktısı)
    # değerleri kendi içinde gerçek veriden türetilmiş, mekansal olarak
    # anlamlı (drug_scores_real, risk_arr_real) dizilere dönüştürür ve
    # bunları döndürür — .npy dosyalarını da bu dönüş değerleriyle
    # kaydediyoruz ki data.json ile survival_predictions.npy/drug_scores.npy
    # arasında tutarsızlık olmasın (bkz. denetim raporu bulgusu A-01/A-03).
    try:
        drug_scores_real, risk_arr_real = export_attention_to_json(
            model, data, adata, ct_names,
            zone_preds=zone_np, drug_scores=drug_np, survival_preds=surv_np,
            out_path=str(gnn_out / "data.json"),
            ct_preds=ct_pred.cpu().numpy(),
            zone_uncertainty=zone_uncertainty_np,
        )
    except Exception as e_json:
        raise RuntimeError(f"Attention verileri JSON'a aktarılamadı: {e_json}")

    if drug_scores_real is None or risk_arr_real is None:
        # Attention layer bulunamadıysa (ör. tek-katmanlı model), export
        # fonksiyonu erken çıkar ve ham dizileri korumamız gerekir.
        drug_scores_real, risk_arr_real = drug_np, surv_np

    # ── numpy dizilerini kaydet (data.json ile aynı, düzeltilmiş değerler) ──
    try:
        np.save(gnn_out / "zone_predictions.npy",     zone_np)
        np.save(gnn_out / "celltype_predictions.npy", ct_pred.cpu().numpy())
        np.save(gnn_out / "survival_predictions.npy", risk_arr_real)
        np.save(gnn_out / "drug_scores.npy",           drug_scores_real)
        np.save(gnn_out / "spatial_embeddings.npy",   emb.cpu().numpy())
    except Exception as e_save:
        raise RuntimeError(f"Numpy dizileri kaydedilemedi: {e_save}")

    # ── Summary & Correlations ───────────────────────────────────
    corrs = {}
    if has_test_mask:
        test_mask = data['spot'].test_mask
        ct_p = ct_pred[test_mask].cpu().numpy()
        ct_t = data['spot'].y[test_mask].cpu().numpy()
        for i, ct in enumerate(ct_names):
            try:
                # Check for zero variance to avoid pearsonr/spearmanr exceptions
                if np.std(ct_p[:, i]) < 1e-8 or np.std(ct_t[:, i]) < 1e-8:
                    logger.warning(f"   Korelasyon hesaplanamadı ({ct}): Sıfır/sabit varyans.")
                    continue
                r, _ = pearsonr(ct_p[:, i], ct_t[:, i])
                rs, _= spearmanr(ct_p[:, i], ct_t[:, i])
                if np.isfinite(r) and np.isfinite(rs):
                    corrs[ct] = {"pearson_r": round(float(r), 4), "spearman_r": round(float(rs), 4)}
            except Exception as exc:
                logger.warning(f"   Korelasyon hesaplanamadı ({ct}): {exc}")

    device_str = "cuda" if torch.cuda.is_available() else "cpu"
    deconv_method = adata.uns.get("deconv_method", "unknown")

    summary = {
        "test_mse": test_mse,
        "best_val_loss": float(best_val),
        "correlations": corrs,
        "zones": ZONE_NAMES,
        "ct_names": ct_names,
        "n_spots": int(data['spot'].x.shape[0]),
        "n_epochs_trained": len(hist.get("train", [])),
        "cfg_epochs": cfg.get("epochs", GNN_EPOCHS),
        "cfg": cfg,
        "deconv_method": deconv_method,
        "device": device_str,
        "loss_scale_factors": model.loss_scale_factors.detach().cpu().tolist() if hasattr(model, 'loss_scale_factors') and model.loss_scale_factors is not None else None
    }
    try:
        (gnn_out / "gnn_summary.json").write_text(json.dumps(summary, indent=2), encoding='utf-8')
    except Exception as e_sum:
        raise RuntimeError(f"Özet JSON dosyası yazılamadı: {e_sum}")

    # ── Training plot ─────────────────────────────────────────────
    try:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5), facecolor='#0d1117')
        axes[0].plot(hist.get('train', []), color='#E63946', label='Train' if is_english else 'Eğitim')
        axes[0].plot(hist.get('val', []),   color='#457B9D', label='Val' if is_english else 'Doğrulama')
        axes[0].set_title('Train vs Val Loss' if is_english else 'Eğitim vs Doğrulama Kaybı', color='white')
        axes[0].set_facecolor('#1a1a2e')
        axes[0].tick_params(colors='white')
        axes[0].legend(facecolor='#1a1a2e', labelcolor='white')
        
        comp_map = [('ct','#E63946'),('zone','#2A9D8F'),('contr','#F4A261'),('smooth','#457B9D')]
        for key, clr in comp_map:
            # Safe dict lookup to prevent KeyError
            comp_values = [c.get(key, 0.0) for c in hist.get('comp', []) if isinstance(c, dict)]
            if comp_values:
                axes[1].plot(comp_values, label=key.upper(), color=clr)
        
        axes[1].set_title('Loss Components' if is_english else 'Kaybın Bileşenleri', color='white')
        axes[1].set_facecolor('#1a1a2e')
        axes[1].tick_params(colors='white')
        axes[1].legend(facecolor='#1a1a2e', labelcolor='white')
        
        fig.patch.set_facecolor('#0d1117')
        plt.tight_layout()
        
        plot_dpi = int(os.environ.get("GLIO_PLOT_DPI", "150"))
        fig.savefig(gnn_out / "training_history_v3.png", dpi=plot_dpi, facecolor='#0d1117', bbox_inches='tight')
        plt.close()
    except Exception as e_plot:
        logger.warning(f"Eğitim grafiği çizilemedi: {e_plot}")

    # ── IVY GAP Marker-Tabanlı Eğitim Hedefi — Tutarlılık Kontrolü ────
    # ÖNEMLİ (bilimsel dürüstlük notu): Aşağıdaki karşılaştırma, modelin
    # bağımsız/gerçek IVY GAP histoloji etiketlerine karşı DEĞİL, kendi
    # eğitim hedefini (zone_y — train_gnn.py::build_graph_data içinde AYNI
    # ZONE_SIGNATURES marker listesinden z-score/softmax ile üretilir)
    # ne kadar yeniden ürettiğine karşı yapılır. Yani bu bir dış doğrulama
    # değil, bir optimizasyon/tutarlılık kontrolüdür — yüksek "accuracy"
    # modelin gerçek patolojiye genellediğini değil, kendi hedefine
    # yakınsadığını gösterir. Bu ayrım aşağıdaki JSON çıktısında da
    # (`is_independent_validation`, `disclaimer`) açıkça belirtilir.
    logger.info("GNN Tahmini vs IVY GAP Marker Tabanlı Eğitim Hedefi (iç tutarlılık kontrolü, bağımsız doğrulama DEĞİLDİR)...")

    # NOT: Bu sözlük train_gnn.py::ZONE_SIGNATURES ile TAM AYNI olmalı —
    # aksi halde bu "tutarlılık kontrolü" kendi eğitim hedefinden bile
    # sapar. Import yerine burada kopya tutulmasının nedeni tarihseldir;
    # değiştirirken iki dosyayı birlikte güncelleyin (bkz. B-10 düzeltmesi).
    from train_gnn import ZONE_SIGNATURES

    # Verify signature keys match ZONE_NAMES
    missing_zones = set(ZONE_SIGNATURES.keys()) - set(ZONE_NAMES)
    if missing_zones:
        logger.warning(f"ZONE_SIGNATURES'ta bulunup ZONE_NAMES listesinde tanımlı olmayan bölge(ler) var: {missing_zones}")

    def get_gene_safe(adata, gene: str):
        candidates = [gene, gene.upper(), gene.lower(), gene.capitalize(), gene.title()]
        for name in candidates:
            if name in adata.var_names:
                try:
                    col_idx = adata.var_names.get_loc(name)
                    e = adata.X[:, col_idx]
                except Exception:
                    e = adata[:, name].X
                arr = e.toarray().flatten() if hasattr(e, 'toarray') else np.asarray(e).flatten()
                arr = arr.astype(np.float32)
                if np.std(arr) < 1e-8:  # zero or near-zero variance
                    continue
                return arr
        return None

    zone_scores = np.zeros((adata.n_obs, len(ZONE_NAMES)), dtype=np.float32)
    total_valid_genes_found = 0

    for z_idx, zone in enumerate(ZONE_NAMES):
        valid_genes = []
        for g in ZONE_SIGNATURES.get(zone, []):
            arr = get_gene_safe(adata, g)
            if arr is not None:
                valid_genes.append(arr)
        if valid_genes:
            total_valid_genes_found += len(valid_genes)
            valid_arr = np.stack(valid_genes)
            zscored = (valid_arr - valid_arr.mean(axis=1, keepdims=True)) / (valid_arr.std(axis=1, keepdims=True) + 1e-8)
            zone_scores[:, z_idx] = zscored.mean(axis=0)

        else:
            zone_scores[:, z_idx] = -1e6  # very low probability logit

    if total_valid_genes_found == 0:
        logger.warning("⚠️ IVY GAP zone genlerinin hiçbiri veri setinde bulunamadı! Zone karşılaştırma analizi atlanıyor.")
    else:
        zone_exp = np.exp(zone_scores - zone_scores.max(axis=1, keepdims=True))
        row_sums = zone_exp.sum(axis=1, keepdims=True)
        # Safe division without dummy noise
        y_true_probs = zone_exp / np.clip(row_sums, 1e-12, None)
        
        y_true = np.argmax(y_true_probs, axis=1)
        y_pred = np.argmax(zone_np, axis=1)

        max_probs = y_true_probs.max(axis=1)
        core_mask = np.zeros(len(y_true), dtype=bool)

        min_core_spots = int(os.environ.get("GLIO_MIN_CORE_SPOTS", "10"))

        for z_idx, zone in enumerate(ZONE_NAMES):
            zone_mask = y_true == z_idx
            if zone_mask.sum() == 0:
                continue
                
            threshold = float(np.percentile(max_probs[zone_mask], 75))
            zone_core = zone_mask & (max_probs >= threshold)
            
            if zone_core.sum() < min_core_spots:
                threshold_relaxed = float(np.median(max_probs[zone_mask]))
                zone_core = zone_mask & (max_probs >= threshold_relaxed)
                
            core_mask |= zone_core

        if core_mask.sum() > 0:
            y_true_core = y_true[core_mask]
            y_pred_core = y_pred[core_mask]
            
            labels = list(range(len(ZONE_NAMES)))
            rep = classification_report(y_true_core, y_pred_core, target_names=ZONE_NAMES, labels=labels, output_dict=True, zero_division=0)
            acc = rep.get('accuracy', 0.0)
            macro_f1 = rep.get('macro avg', {}).get('f1-score', 0.0)
            weighted_f1 = rep.get('weighted avg', {}).get('f1-score', 0.0)
            
            # Enrich summary json with classification metrics
            summary["ivy_gap_validation"] = {
                "core_spots_count": int(core_mask.sum()),
                "accuracy": acc,
                "macro_f1": macro_f1,
                "weighted_f1": weighted_f1,
                "classification_report": rep,
                # Bilimsel dürüstlük: bu bağımsız bir doğrulama değildir —
                # bkz. denetim raporu bulgusu A-05.
                "is_independent_validation": False,
                "disclaimer": (
                    "Bu metrikler modelin GERÇEK/bağımsız IVY GAP histoloji "
                    "etiketlerine karşı değil, kendi eğitim hedefine (aynı "
                    "marker geni imzalarından üretilen pseudo-etiket) karşı "
                    "ölçülmüştür. Yüksek doğruluk, modelin gerçek patolojiye "
                    "genellediğini kanıtlamaz; yalnızca eğitim hedefine "
                    "yakınsadığını gösterir."
                    if not is_english else
                    "These metrics are measured against the model's own "
                    "training target (a pseudo-label derived from the same "
                    "marker-gene signatures), NOT against real/independent "
                    "IVY GAP histology annotations. High accuracy does not "
                    "demonstrate generalization to real pathology — only "
                    "convergence to the training target."
                ),
            }
            # Re-write summary with validation results
            try:
                (gnn_out / "gnn_summary.json").write_text(json.dumps(summary, indent=2), encoding='utf-8')
            except Exception as e_sum_val:
                logger.warning(f"Validation sonrası özet JSON güncellenemedi: {e_sum_val}")

            cm = confusion_matrix(y_true_core, y_pred_core, labels=labels)
            row_sums_cm = cm.sum(axis=1, keepdims=True).astype(float)
            cm_perc = np.divide(cm.astype(float) * 100, row_sums_cm, out=np.zeros_like(cm, dtype=float), where=row_sums_cm > 0)

            zone_label_mapping = {
                "Pseudopalisading Necrosis": "Pseudopalisading Necrosis" if is_english else "Yalancı Palisadlı Nekroz",
                "Microvascular Proliferation": "Microvascular Proliferation" if is_english else "Mikrovasküler Proliferasyon",
                "Cellular Tumor": "Cellular Tumor" if is_english else "Hücresel Tümör",
                "Leading Edge": "Leading Edge" if is_english else "Tümör Sınırı",
                "Infiltrating Tumor": "Infiltrating Tumor" if is_english else "İnfiltratif Tümör"
            }
            mapped_zones = [zone_label_mapping.get(z, z) for z in ZONE_NAMES]
            
            try:
                fig, axes = plt.subplots(1, 2, figsize=(20, 8), facecolor='#0d1117')
                sns.heatmap(cm_perc, annot=True, fmt='.1f', cmap='viridis', xticklabels=[z.replace(' ', '\n') for z in mapped_zones], yticklabels=mapped_zones, ax=axes[0])
                consistency_lbl = "Eğitim Hedefi Tutarlılığı" if not is_english else "Training-Target Consistency"
                axes[0].set_title(f"{consistency_lbl}: %{acc*100:.1f} | Macro F1: {macro_f1:.3f} | Weighted F1: {weighted_f1:.3f}\n" +
                                   ("(Bağımsız doğrulama değildir — bkz. metodoloji notu)" if not is_english
                                    else "(Not an independent validation — see methodology note)"),
                                   color='white', fontsize=11)
                axes[0].tick_params(colors='white')
                
                sns.heatmap(cm, annot=True, fmt='d', cmap='plasma', xticklabels=[z.replace(' ', '\n') for z in mapped_zones], yticklabels=mapped_zones, ax=axes[1])
                axes[1].set_title("Absolute Spot Counts (Core Spots)" if is_english else "Mutlak Spot Sayıları (Core Spotlar)", color='white')
                axes[1].tick_params(colors='white')
                
                plt.tight_layout()
                plot_dpi = int(os.environ.get("GLIO_PLOT_DPI", "150"))
                fig.savefig(gnn_out / "GNN_confusion_matrix.png", dpi=plot_dpi, facecolor='#0d1117', bbox_inches='tight')
                plt.close()
            except Exception as e_val_plot:
                logger.warning(f"IVY GAP karşılaştırma grafikleri çizilemedi: {e_val_plot}")
        else:
            logger.warning("IVY GAP core spot maskesi boş çıktı, karşılaştırma metrikleri hesaplanamadı.")

    # ── GERÇEK Ivy GAP ISH referansıyla BAĞIMSIZ doğrulama [GELİŞTİRME] ──
    # Yukarıdaki blok (ivy_gap_validation) modelin KENDİ eğitim hedefine
    # karşı ölçüm yapıyor — dairesel olduğu açıkça belirtiliyor. Burada
    # gerçekten bağımsız bir referans kullanıyoruz: Allen Institute'ün
    # Ivy Glioblastoma Atlas Project'inden (Puchalski ve ark. 2018,
    # Science) — farklı hastalar, farklı teknoloji (ISH), bu uygulamanın
    # eğitiminde/pseudo-etiketlemesinde HİÇ kullanılmayan gerçek veri.
    # Referans dosyası (python_backend/reference_data/ivygap_real_reference.json)
    # önceden indirilip repoya gömüldü — çalışma zamanında internet
    # gerektirmez (offline çalışma ilkesiyle tutarlı).
    logger.info("Gerçek Ivy GAP ISH referans verisiyle BAĞIMSIZ doğrulama...")
    try:
        ref_path = BACKEND_DIR / "reference_data" / "ivygap_real_reference.json"
        if not ref_path.exists():
            ref_path = PROJECT_ROOT / "desktop_app" / "python_backend" / "reference_data" / "ivygap_real_reference.json"

        if not ref_path.exists():
            logger.warning("   ivygap_real_reference.json bulunamadı, gerçek doğrulama atlandı.")
        else:
            with open(ref_path, encoding='utf-8') as f:
                ivygap_ref = json.load(f)
            ref_genes = list(ivygap_ref["genes"].keys())
            zone_to_structure = ivygap_ref["_meta"]["zone_to_structure"]
            struct_to_zone = {v: k for k, v in zone_to_structure.items()}
            structures = ["le", "it", "ct", "ctpan", "ctmvp"]

            y_pred_dom = np.argmax(zone_np, axis=1)

            # Bizim modelimizin her zon için (o zona atanmış spot'lar
            # üzerinden) referans genlerinin ortalama ekspresyonu.
            our_zone_expr = {}
            for zi, zn in enumerate(ZONE_NAMES):
                spot_mask = (y_pred_dom == zi)
                if spot_mask.sum() < 5:
                    our_zone_expr[zn] = None
                    continue
                gene_means = {}
                for g in ref_genes:
                    arr = get_gene_safe(adata, g)
                    if arr is not None:
                        gene_means[g] = float(arr[spot_mask].mean())
                our_zone_expr[zn] = gene_means

            # Her iki veri kümesinde de tam kapsamlı genler
            common_genes_final = [
                g for g in ref_genes
                if all(ivygap_ref["genes"][g].get(s) is not None for s in structures)
            ]

            ref_matrix = np.array([
                [ivygap_ref["genes"][g][s] for g in common_genes_final] for s in structures
            ])
            ref_matrix_z = (ref_matrix - ref_matrix.mean(axis=0, keepdims=True)) / (
                ref_matrix.std(axis=0, keepdims=True) + 1e-8)

            our_matrix = []
            for s in structures:
                zn = struct_to_zone.get(s)
                expr = our_zone_expr.get(zn) if zn else None
                if not expr:
                    our_matrix.append([np.nan] * len(common_genes_final))
                else:
                    our_matrix.append([expr.get(g, np.nan) for g in common_genes_final])
            our_matrix = np.array(our_matrix, dtype=np.float64)
            our_matrix_z = (our_matrix - np.nanmean(our_matrix, axis=0, keepdims=True)) / (
                np.nanstd(our_matrix, axis=0, keepdims=True) + 1e-8)

            n_s = len(structures)
            corr_matrix = np.full((n_s, n_s), np.nan)
            for i in range(n_s):
                for j in range(n_s):
                    a, b = our_matrix_z[i], ref_matrix_z[j]
                    mask = ~np.isnan(a) & ~np.isnan(b)
                    if mask.sum() >= 4:
                        corr_matrix[i, j] = float(np.corrcoef(a[mask], b[mask])[0, 1])

            diag = [corr_matrix[i, i] for i in range(n_s) if not np.isnan(corr_matrix[i, i])]
            top1_matches, top1_total = 0, 0
            for i in range(n_s):
                row = corr_matrix[i]
                if np.all(np.isnan(row)):
                    continue
                top1_total += 1
                if np.nanargmax(row) == i:
                    top1_matches += 1

            zone_labels = [struct_to_zone.get(s, s) for s in structures]
            real_validation = {
                "is_independent_validation": True,
                "source": ivygap_ref["_meta"]["citation"],
                "n_reference_genes": len(common_genes_final),
                "reference_genes": common_genes_final,
                "zones": zone_labels,
                "correlation_matrix": [[(None if np.isnan(v) else round(float(v), 4)) for v in row] for row in corr_matrix],
                "diagonal_mean_correlation": round(float(np.mean(diag)), 4) if diag else None,
                "top1_match_accuracy": round(top1_matches / top1_total, 4) if top1_total else None,
                "disclaimer": (
                    "Bu doğrulama GERÇEK, bağımsız bir hasta kohortundan (Ivy Glioblastoma "
                    "Atlas Project, Puchalski ve ark. 2018, Science) elde edilen ISH gen "
                    "ekspresyon verisine karşı yapılır — modelin kendi eğitim hedefine karşı "
                    "DEĞİLDİR. Farklı hastalar, farklı teknoloji (ISH vs. spatial "
                    f"transkriptomik). Küçük referans gen paneli (n={len(common_genes_final)} "
                    "gen) nedeniyle istatistiksel gücü sınırlıdır; kesin bir klinik doğrulama "
                    "değil, ek bir güvenilirlik sinyali olarak yorumlanmalıdır."
                    if not is_english else
                    "This validation is against REAL, independent patient-cohort ISH gene "
                    "expression data (Ivy Glioblastoma Atlas Project, Puchalski et al. 2018, "
                    "Science) — NOT against the model's own training target. Different "
                    "patients, different technology (ISH vs. spatial transcriptomics). "
                    f"Statistical power is limited by the small reference gene panel "
                    f"(n={len(common_genes_final)} genes); interpret as an additional "
                    "reliability signal, not a definitive clinical validation."
                ),
            }
            summary["real_ivy_gap_validation"] = real_validation
            try:
                (gnn_out / "gnn_summary.json").write_text(json.dumps(summary, indent=2), encoding='utf-8')
            except Exception as e_sum_val2:
                logger.warning(f"Gerçek Ivy GAP doğrulaması sonrası özet JSON güncellenemedi: {e_sum_val2}")

            logger.info(
                f"   Gerçek Ivy GAP doğrulaması: diagonal ort. korelasyon="
                f"{real_validation['diagonal_mean_correlation']}, "
                f"top1_eşleşme={real_validation['top1_match_accuracy']} "
                f"({len(common_genes_final)} referans gen)"
            )
    except Exception as e_real_val:
        logger.warning(f"   Gerçek Ivy GAP doğrulaması hesaplanamadı: {e_real_val}")

    logger.info("✅ Stage 3 tamamlandı")
    report_progress(100)
    print(json.dumps({"stage": "gnn_training", "status": "done", "test_mse": test_mse}))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        exit_with_error(f"GNN aşamasında beklenmeyen hata: {str(e)}\n{traceback.format_exc()}")
