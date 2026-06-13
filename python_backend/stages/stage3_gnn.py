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

from loguru import logger
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
    export_attention_to_json,
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
        ct_pred, zone_pred, surv_pred, drug_pred, emb = model(data)

    zone_np = F.softmax(zone_pred, dim=-1).cpu().numpy()
    surv_np = surv_pred.cpu().numpy()
    drug_np = drug_pred.cpu().numpy()

    # ── Verify test mask and compute MSE ─────────────────────────
    if not hasattr(data, 'test_mask') or data.test_mask is None or data.test_mask.sum().item() == 0:
        logger.warning("   Test maskesi boş veya tanımlanmamış — MSE ve korelasyonlar hesaplanamadı.")
        test_mse = float('nan')
    else:
        pred_test = ct_pred[data.test_mask]
        y_test = data.y[data.test_mask]
        if pred_test.shape != y_test.shape:
            raise ValueError(f"Şekil uyuşmazlığı: GNN hücre tipi tahmini {pred_test.shape} ve gerçek dekonvolüsyon değerleri {y_test.shape} uyuşmuyor!")
        test_mse = F.mse_loss(pred_test, y_test).item()
        logger.info(f"   Test CT MSE: {test_mse:.6f}")

    # ── Save model + arrays ──────────────────────────────────────
    try:
        torch.save(model.state_dict(), gnn_out / "glio_gnn_v3.pt")
        np.save(gnn_out / "zone_predictions.npy",    zone_np)
        np.save(gnn_out / "celltype_predictions.npy", ct_pred.cpu().numpy())
        np.save(gnn_out / "survival_predictions.npy", surv_np)
        np.save(gnn_out / "drug_scores.npy",          drug_np)
        np.save(gnn_out / "spatial_embeddings.npy",   emb.cpu().numpy())
    except Exception as e_save:
        raise RuntimeError(f"Model ve numpy dizileri kaydedilemedi: {e_save}")

    # ── JSON export ──────────────────────────────────────────────
    try:
        export_attention_to_json(
            model, data, adata, ct_names,
            zone_preds=zone_np, drug_scores=drug_np, survival_preds=surv_np,
            out_path=str(gnn_out / "data.json"),
            ct_preds=ct_pred.cpu().numpy()
        )
    except Exception as e_json:
        raise RuntimeError(f"Attention verileri JSON'a aktarılamadı: {e_json}")

    # ── Summary & Correlations ───────────────────────────────────
    corrs = {}
    if hasattr(data, 'test_mask') and data.test_mask is not None and data.test_mask.sum().item() > 0:
        ct_p = ct_pred[data.test_mask].cpu().numpy()
        ct_t = data.y[data.test_mask].cpu().numpy()
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
        "n_spots": int(data.x.shape[0]),
        "n_epochs_trained": len(hist.get("train", [])),
        "cfg_epochs": cfg.get("epochs", GNN_EPOCHS),
        "cfg": cfg,
        "deconv_method": deconv_method,
        "device": device_str
    }
    try:
        (gnn_out / "gnn_summary.json").write_text(json.dumps(summary, indent=2), encoding='utf-8')
    except Exception as e_sum:
        raise RuntimeError(f"Özet JSON dosyası yazılamadı: {e_sum}")

    # ── Training plot ─────────────────────────────────────────────
    try:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5), facecolor='#0d1117')
        axes[0].plot(hist.get('train', []), color='#E63946', label='Train')
        axes[0].plot(hist.get('val', []),   color='#457B9D', label='Val')
        axes[0].set_title('Train vs Val Loss', color='white')
        axes[0].set_facecolor('#1a1a2e')
        axes[0].tick_params(colors='white')
        axes[0].legend(facecolor='#1a1a2e', labelcolor='white')
        
        comp_map = [('ct','#E63946'),('zone','#2A9D8F'),('contr','#F4A261'),('smooth','#457B9D')]
        for key, clr in comp_map:
            # Safe dict lookup to prevent KeyError
            comp_values = [c.get(key, 0.0) for c in hist.get('comp', []) if isinstance(c, dict)]
            if comp_values:
                axes[1].plot(comp_values, label=key.upper(), color=clr)
        
        axes[1].set_title('Loss Bileşenleri', color='white')
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

    # ── IVY GAP Pseudo Ground Truth Validation (v2.0) ─────────────────
    logger.info("Jüri Özel: GNN Tahmini vs IVY GAP Pseudo Ground Truth Karşılaştırması...")

    ZONE_SIGNATURES = {
        'Pseudopalisading Necrosis': ['hif1a', 'ca9', 'vegfa', 'slc2a1', 'bnip3', 'ddit4', 'ldha', 'pdk1'],
        'Microvascular Proliferation': ['vegfa', 'angpt2', 'pdgfrb', 'pecam1', 'kdr', 'tek'],
        'Cellular Tumor': ['mki67', 'top2a', 'egfr', 'olig2', 'sox2', 'pcna', 'cdk4', 'cdkn2a'],
        'Leading Edge': ['vim', 'fn1', 'met', 'cd44', 'cxcr4', 'mmp2', 'mmp9', 'twist1', 'zeb1'],
        'Infiltrating Tumor': ['gfap', 'vim', 'cd44', 'cxcr4', 'ptn', 'ptprz1', 'timp1', 'mmp9'],
    }

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
            zscored = np.stack([(g - g.mean()) / (g.std() + 1e-8) for g in valid_genes])
            zone_scores[:, z_idx] = np.mean(zscored, axis=0)
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
                "classification_report": rep
            }
            # Re-write summary with validation results
            try:
                (gnn_out / "gnn_summary.json").write_text(json.dumps(summary, indent=2), encoding='utf-8')
            except Exception as e_sum_val:
                logger.warning(f"Validation sonrası özet JSON güncellenemedi: {e_sum_val}")

            cm = confusion_matrix(y_true_core, y_pred_core, labels=labels)
            row_sums_cm = cm.sum(axis=1, keepdims=True).astype(float)
            cm_perc = np.divide(cm.astype(float) * 100, row_sums_cm, out=np.zeros_like(cm, dtype=float), where=row_sums_cm > 0)
            
            try:
                fig, axes = plt.subplots(1, 2, figsize=(20, 8), facecolor='#0d1117')
                sns.heatmap(cm_perc, annot=True, fmt='.1f', cmap='viridis', xticklabels=[z.replace(' ', '\n') for z in ZONE_NAMES], yticklabels=ZONE_NAMES, ax=axes[0])
                axes[0].set_title(f"Accuracy: %{acc*100:.1f} | Macro F1: {macro_f1:.3f} | Weighted F1: {weighted_f1:.3f}", color='white')
                axes[0].tick_params(colors='white')
                
                sns.heatmap(cm, annot=True, fmt='d', cmap='plasma', xticklabels=[z.replace(' ', '\n') for z in ZONE_NAMES], yticklabels=ZONE_NAMES, ax=axes[1])
                axes[1].set_title("Mutlak Spot Sayıları (Core Spotlar)", color='white')
                axes[1].tick_params(colors='white')
                
                plt.tight_layout()
                plot_dpi = int(os.environ.get("GLIO_PLOT_DPI", "150"))
                fig.savefig(gnn_out / "GNN_confusion_matrix.png", dpi=plot_dpi, facecolor='#0d1117', bbox_inches='tight')
                plt.close()
            except Exception as e_val_plot:
                logger.warning(f"IVY GAP karşılaştırma grafikleri çizilemedi: {e_val_plot}")
        else:
            logger.warning("IVY GAP core spot maskesi boş çıktı, karşılaştırma metrikleri hesaplanamadı.")

    logger.info("✅ Stage 3 tamamlandı")
    report_progress(100)
    print(json.dumps({"stage": "gnn_training", "status": "done", "test_mse": test_mse}))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        exit_with_error(f"GNN aşamasında beklenmeyen hata: {str(e)}\n{traceback.format_exc()}")
