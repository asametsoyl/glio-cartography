"""
Uçtan uca küçük (sentetik veri) GNN smoke testi.

Gerçek veri veya Tangram gerektirmez: küçük bir Visium-benzeri ızgara + rastgele
sayımlar üretir, grafı kurar, birkaç epoch eğitir, MC-dropout belirsizliğini
hesaplar ve data.json'u dışa aktarır. Amaç, model/kayıp/dışa aktarma zincirinin
çalışmaya devam ettiğini (ve kaldırılan risk/ilaç/sağkalım çıktılarının geri
gelmediğini) doğrulamaktır; biyolojik doğruluk testi DEĞİLDİR.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torch_geometric")
anndata = pytest.importorskip("anndata")
pd = pytest.importorskip("pandas")

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

CT_NAMES = ["malignant_tumor", "microglia", "t_cell", "endothelial", "astrocyte"]


def _synthetic_adata(n_side=14, n_genes=120, seed=0):
    rng = np.random.default_rng(seed)
    xs, ys = np.meshgrid(np.arange(n_side), np.arange(n_side))
    coords = np.column_stack([xs.ravel(), ys.ravel()]).astype(np.float32) * 100.0
    n = coords.shape[0]

    import train_gnn
    sig_genes = sorted({g for genes in train_gnn.ZONE_SIGNATURES.values() for g in genes})
    lr_genes = sorted({g.lower() for l, r, _ in train_gnn.LR_PAIRS for g in (l, r)})
    base = [g.upper() for g in (sig_genes + lr_genes)][: n_genes // 2]
    filler = [f"GENE{i}" for i in range(n_genes - len(base))]
    var_names = list(dict.fromkeys(base + filler))

    X = rng.poisson(2.0, size=(n, len(var_names))).astype(np.float32)
    adata = anndata.AnnData(X=X)
    adata.var_names = var_names
    adata.obs_names = [f"spot{i}" for i in range(n)]
    adata.obsm["spatial"] = coords
    adata.obsm["X_pca"] = rng.normal(size=(n, 20)).astype(np.float32)
    props = rng.dirichlet(np.ones(len(CT_NAMES)), size=n).astype(np.float32)
    adata.obsm["celltype_proportions"] = pd.DataFrame(props, columns=CT_NAMES, index=adata.obs_names)
    return adata


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    import train_gnn
    adata = _synthetic_adata()
    data = train_gnn.build_graph_data(adata, k_neighbors=6)
    torch.manual_seed(0)
    model, hist, best_val = train_gnn.train_model(
        data, cfg={"hidden": 32, "heads": 2, "epochs": 4, "patience": 10, "n_gat": 1, "n_sage": 1}
    )
    return train_gnn, adata, data, model, hist, best_val


def test_graph_has_no_patient_level_survival_fields(trained):
    _, _, data, _, _, _ = trained
    for field in ("survival_y", "tcga_risk_y", "clinical_x"):
        assert not hasattr(data, field), f"{field} kaldırılmış olmalıydı"


def test_model_forward_returns_four_outputs_without_survival_or_drug_heads(trained):
    _, _, data, model, _, _ = trained
    assert not hasattr(model, "survival_head")
    assert not hasattr(model, "drug_head")
    assert model.loss_scale_factors.shape == (5,)

    model.eval()
    with torch.no_grad():
        out = model(data)
    assert len(out) == 4
    ct, zone, emb, h = out
    n = data["spot"].x.shape[0]
    assert ct.shape[0] == zone.shape[0] == emb.shape[0] == h.shape[0] == n
    # hücre tipi oranları olasılık dağılımı olmalı
    assert torch.allclose(ct.sum(dim=-1), torch.ones(n), atol=1e-4)


def test_training_loss_history_has_no_survival_component(trained):
    *_, hist, best_val = trained
    assert np.isfinite(best_val)
    assert len(hist["comp"]) >= 1
    assert "surv" not in hist["comp"][0]
    assert {"ct", "zone", "dgi", "smooth", "attn_reg", "total"} <= set(hist["comp"][0])


def test_mc_dropout_uncertainty_shapes(trained):
    train_gnn, _, data, model, _, _ = trained
    mean_p, std_p = train_gnn.mc_dropout_zone_uncertainty(model, data, n_samples=3)
    n_zones = len(train_gnn.ZONE_NAMES)
    assert mean_p.shape == std_p.shape == (data["spot"].x.shape[0], n_zones)
    assert (std_p >= 0).all()


def test_export_attention_json_has_no_risk_or_drug_fields(trained, tmp_path):
    import torch.nn.functional as F
    train_gnn, adata, data, model, _, _ = trained
    model.eval()
    with torch.no_grad():
        ct, zone, _, _ = model(data)
    out_path = tmp_path / "data.json"
    ret = train_gnn.export_attention_to_json(
        model, data, adata, list(data.ct_names),
        zone_preds=F.softmax(zone, dim=-1).numpy(),
        out_path=str(out_path),
        ct_preds=ct.numpy(),
    )
    assert ret is None
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["n_spots"] == data["spot"].x.shape[0]
    spot = payload["spots"][0]
    for banned in ("drug", "drug_score", "drug_perturbation_score", "drug_target",
                   "drug_lr_basis", "drug_status", "tcga_risk", "model_risk_index"):
        assert banned not in spot, f"{banned} kaldırılmış olmalıydı"
    for kept in ("ct", "zones", "lr", "pathways", "edges", "why_zone"):
        assert kept in spot
    assert (tmp_path / "lr_detailed_summary.json").exists()
    summary = json.loads((tmp_path / "lr_detailed_summary.json").read_text(encoding="utf-8"))
    assert summary and "drug" not in summary[0] and "drug_mechanism" not in summary[0]
