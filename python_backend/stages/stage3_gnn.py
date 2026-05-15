#!/usr/bin/env python3
"""Stage 3: GNN Training — mevcut train_gnn.py'yi output path ile çalıştırır"""
import os, sys, json, shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

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

# Import GNN from models/train_gnn.py
sys.path.insert(0, str(PROJECT_ROOT / "models"))
from train_gnn import (
    build_graph_data, GlioCartographyGNN, train_model,
    export_attention_to_json, counterfactual_knockout,
    ZONE_NAMES, LR_PAIRS
)

gnn_out = OUTPUT_DIR / "gnn"
gnn_out.mkdir(parents=True, exist_ok=True)

# ── Load deconvolved data ─────────────────────────────────────
spatial_path = OUTPUT_DIR / "preprocessing" / "spatial" / "spatial_deconvolved.h5ad"
logger.info(f"📂 Veri yükleniyor: {spatial_path}")
adata = ad.read_h5ad(spatial_path)

# ── Build graph ──────────────────────────────────────────────
logger.info("🔗 Graf oluşturuluyor...")
data     = build_graph_data(adata, k_neighbors=6)
ct_names = data.ct_names

# ── Train ────────────────────────────────────────────────────
logger.info(f"🧠 GNN eğitimi ({GNN_EPOCHS} epoch)...")

if RUN_OPTUNA:
    import optuna
    from train_gnn import objective
    logger.info(f"   Optuna ({OPTUNA_TRIALS} trial)...")
    study = optuna.create_study(direction='minimize',
                                pruner=optuna.pruners.MedianPruner(n_startup_trials=3))
    study.optimize(lambda t: objective(t, data), n_trials=OPTUNA_TRIALS)
    cfg = {**study.best_params, 'epochs': GNN_EPOCHS, 'patience': 30}
    logger.info(f"   Best val: {study.best_value:.4f}")
else:
    cfg = {'hidden': 128, 'heads': 4, 'drop': 0.3, 'lr': 1e-3,
           'n_gat': 2, 'n_sage': 1, 'epochs': GNN_EPOCHS, 'patience': 30}

model, hist, best_val = train_model(data, cfg=cfg)

# ── Evaluate ─────────────────────────────────────────────────
model.eval()
with torch.no_grad():
    ct_pred, zone_pred, surv_pred, drug_pred, emb = model(data)

zone_np = F.softmax(zone_pred, dim=-1).cpu().numpy()
surv_np = surv_pred.cpu().numpy()
drug_np = drug_pred.cpu().numpy()

test_mse = F.mse_loss(ct_pred[data.test_mask], data.y[data.test_mask]).item()
logger.info(f"   Test CT MSE: {test_mse:.6f}")

# ── Save model + arrays ──────────────────────────────────────
torch.save(model.state_dict(), gnn_out / "glio_gnn_v3.pt")
np.save(gnn_out / "zone_predictions.npy",    zone_np)
np.save(gnn_out / "celltype_predictions.npy", ct_pred.cpu().numpy())
np.save(gnn_out / "survival_predictions.npy", surv_np)
np.save(gnn_out / "drug_scores.npy",          drug_np)
np.save(gnn_out / "spatial_embeddings.npy",   emb.cpu().numpy())

# ── JSON export ──────────────────────────────────────────────
export_attention_to_json(
    model, data, ct_names,
    zone_preds=zone_np, drug_scores=drug_np, survival_preds=surv_np,
    out_path=str(gnn_out / "data.json")
)

# ── Summary ──────────────────────────────────────────────────
corrs = {}
ct_p = ct_pred[data.test_mask].cpu().numpy()
ct_t = data.y[data.test_mask].cpu().numpy()
for i, ct in enumerate(ct_names):
    try:
        r, _ = pearsonr(ct_p[:, i], ct_t[:, i])
        rs, _= spearmanr(ct_p[:, i], ct_t[:, i])
        corrs[ct] = {"pearson_r": round(float(r), 4), "spearman_r": round(float(rs), 4)}
    except: pass

summary = {
    "test_mse": test_mse,
    "best_val_loss": float(best_val),
    "correlations": corrs,
    "zones": ZONE_NAMES,
    "ct_names": ct_names,
    "n_spots": int(data.x.shape[0]),
    "n_epochs_trained": len(hist["train"]),
    "cfg": cfg
}
(gnn_out / "gnn_summary.json").write_text(json.dumps(summary, indent=2))

# ── Training plot ─────────────────────────────────────────────
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(14, 5), facecolor='#0d1117')
axes[0].plot(hist['train'], color='#E63946', label='Train')
axes[0].plot(hist['val'],   color='#457B9D', label='Val')
axes[0].set_title('Train vs Val Loss', color='white')
axes[0].set_facecolor('#1a1a2e'); axes[0].tick_params(colors='white')
axes[0].legend(facecolor='#1a1a2e', labelcolor='white')
comp_map = [('ct','#E63946'),('zone','#2A9D8F'),('contr','#F4A261'),('smooth','#457B9D')]
for key, clr in comp_map:
    axes[1].plot([c[key] for c in hist['comp']], label=key.upper(), color=clr)
axes[1].set_title('Loss Bileşenleri', color='white')
axes[1].set_facecolor('#1a1a2e'); axes[1].tick_params(colors='white')
axes[1].legend(facecolor='#1a1a2e', labelcolor='white')
fig.patch.set_facecolor('#0d1117')
plt.tight_layout()
fig.savefig(gnn_out / "training_history_v3.png", dpi=150, facecolor='#0d1117', bbox_inches='tight')
plt.close()

# ── IVY GAP Pseudo Ground Truth Validation (v2.0) ─────────────────
logger.info("Jüri Özel: GNN Tahmini vs IVY GAP Pseudo Ground Truth Karşılaştırması...")

ZONE_SIGNATURES = {
    'Pseudopalisading Necrosis': ['hif1a', 'ca9', 'vegfa', 'slc2a1', 'bnip3', 'ddit4', 'ldha', 'pdk1'],
    'Microvascular Proliferation': ['vegfa', 'angpt2', 'pdgfrb', 'pecam1', 'kdr', 'tek'],
    'Cellular Tumor': ['mki67', 'top2a', 'egfr', 'olig2', 'sox2', 'pcna', 'cdk4', 'cdkn2a'],
    'Leading Edge': ['vim', 'fn1', 'met', 'cd44', 'cxcr4', 'mmp2', 'mmp9', 'twist1', 'zeb1'],
    'Infiltrating Tumor': ['gfap', 'vim', 'cd44', 'cxcr4', 'ptn', 'ptprz1', 'timp1', 'mmp9'],
}

# ZONE_CORE_THRESHOLDS kaldırıldı — dinamik persentil hesaplaması kullanılıyor

def get_gene_safe(adata, gene: str):
    for name in [gene, gene.upper(), gene.lower(), gene.capitalize()]:
        if name in adata.var_names:
            e = adata[:, name].X
            return e.toarray().flatten().astype(np.float32) if hasattr(e, 'toarray') else np.asarray(e).flatten().astype(np.float32)
    return None

zone_scores = np.zeros((adata.n_obs, len(ZONE_NAMES)), dtype=np.float32)
for z_idx, zone in enumerate(ZONE_NAMES):
    valid_genes = []
    for g in ZONE_SIGNATURES.get(zone, []):
        arr = get_gene_safe(adata, g)
        if arr is not None: valid_genes.append(arr)
    if valid_genes:
        zscored = [(g - g.mean()) / (g.std() + 1e-8) for g in valid_genes]
        zone_scores[:, z_idx] = np.mean(zscored, axis=0)

zone_exp = np.exp(zone_scores - zone_scores.max(axis=1, keepdims=True))
y_true_probs = zone_exp / (zone_exp.sum(axis=1, keepdims=True) + 1e-8)
y_true = np.argmax(y_true_probs, axis=1)
y_pred = np.argmax(zone_np, axis=1)

max_probs = y_true_probs.max(axis=1)
core_mask = np.zeros(len(y_true), dtype=bool)

for z_idx, zone in enumerate(ZONE_NAMES):
    zone_mask = y_true == z_idx
    if zone_mask.sum() == 0:
        continue
        
    # Veriye dayalı (data-driven) dinamik eşik: o zon için tahmin olasılıklarının 75. yüzdeliği
    # Bu yöntem, keyfi hardcoded değerlerin aksine farklı datasetlerde stabil çalışır.
    threshold = float(np.percentile(max_probs[zone_mask], 75))
    
    zone_core = zone_mask & (max_probs >= threshold)
    
    # Eğer çok az hücre seçildiyse eşiği medyan değere düşür (relaxed)
    if zone_core.sum() < 10:
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
    
    cm = confusion_matrix(y_true_core, y_pred_core, labels=labels)
    row_sums = cm.sum(axis=1, keepdims=True).astype(float)
    cm_perc = np.divide(cm.astype(float) * 100, row_sums, out=np.zeros_like(cm, dtype=float), where=row_sums > 0)
    
    fig, axes = plt.subplots(1, 2, figsize=(20, 8), facecolor='#0d1117')
    sns.heatmap(cm_perc, annot=True, fmt='.1f', cmap='viridis', xticklabels=[z.replace(' ', '\n') for z in ZONE_NAMES], yticklabels=ZONE_NAMES, ax=axes[0])
    axes[0].set_title(f"Accuracy: %{acc*100:.1f} | Macro F1: {macro_f1:.3f}", color='white')
    axes[0].tick_params(colors='white')
    
    sns.heatmap(cm, annot=True, fmt='d', cmap='plasma', xticklabels=[z.replace(' ', '\n') for z in ZONE_NAMES], yticklabels=ZONE_NAMES, ax=axes[1])
    axes[1].set_title("Mutlak Spot Sayıları (Core Spotlar)", color='white')
    axes[1].tick_params(colors='white')
    
    plt.tight_layout()
    fig.savefig(gnn_out / "GNN_confusion_matrix.png", dpi=300, facecolor='#0d1117', bbox_inches='tight')
    plt.close()

logger.info("✅ Stage 3 tamamlandı")
print(json.dumps({"stage": "gnn_training", "status": "done", "test_mse": test_mse}))
