"""
train_gnn.py — zon sabitleri ve gen imzaları için yapısal sağlık kontrolleri.

Tam bir forward-pass/eğitim testi değildir (HeteroData + eğitilmiş model
fixture'ı gerektirir, bu paketin kapsamı dışında) — burada, bu oturumda
düzeltilen/gerçek veriyle revize edilen SABİT VERİ yapılarının bozulmadan
kaldığını doğrularız.
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="module")
def train_gnn_module():
    import train_gnn
    return train_gnn


def test_zone_risk_weight_covers_every_zone(train_gnn_module):
    for zone in train_gnn_module.ZONE_NAMES:
        assert zone in train_gnn_module.ZONE_RISK_WEIGHT, f"{zone} için ZONE_RISK_WEIGHT tanımlı değil"


def test_zone_risk_weight_values_are_modest_modulation():
    """
    ZONE_RISK_WEIGHT, hasta-seviyesi tahmini domine ETMEMELİ — yalnızca
    gerçek zon kimliğine dayalı hafif bir mekansal doku eklemeli
    (bkz. A-03 düzeltmesi notu: "±%15 ile sınırlıdır").
    """
    import train_gnn
    for zone, weight in train_gnn.ZONE_RISK_WEIGHT.items():
        assert 0.7 <= weight <= 1.3, f"{zone}: ağırlık {weight} çok agresif, hasta-seviyesi tahmini domine edebilir"


def test_cdkn2a_not_used_as_positive_cellular_tumor_marker(train_gnn_module):
    """
    B-10 düzeltmesi: CDKN2A, GBM'de sıklıkla homozigot delesyona uğrar —
    pozitif bir "Cellular Tumor" markeri olarak kullanmak skoru
    istenenin tersine çalıştırabilir. Bu regresyonun geri gelmediğini
    doğrular.
    """
    ct_genes = {g.upper() for g in train_gnn_module.ZONE_SIGNATURES["Cellular Tumor"]}
    assert "CDKN2A" not in ct_genes


def test_leading_edge_and_infiltrating_tumor_signatures_are_distinct(train_gnn_module):
    """
    B-10 düzeltmesi öncesinde Leading Edge ve Infiltrating Tumor neredeyse
    aynı EMT imzasını paylaşıyordu. Artık anlamlı ölçüde farklı olmalı
    (tam ayrık olması gerekmez — örn. ortak bir gen kalabilir — ama
    büyük örtüşme olmamalı).
    """
    le = {g.upper() for g in train_gnn_module.ZONE_SIGNATURES["Leading Edge"]}
    it = {g.upper() for g in train_gnn_module.ZONE_SIGNATURES["Infiltrating Tumor"]}
    overlap = le & it
    assert len(overlap) <= 1, f"Leading Edge / Infiltrating Tumor imzaları hâlâ büyük ölçüde örtüşüyor: {overlap}"


def test_zone_signatures_are_non_empty_for_every_zone(train_gnn_module):
    for zone, genes in train_gnn_module.ZONE_SIGNATURES.items():
        assert len(genes) >= 3, f"{zone}: çok az marker geni ({len(genes)})"


def test_mc_dropout_uncertainty_function_exists_with_expected_signature(train_gnn_module):
    import inspect
    fn = train_gnn_module.mc_dropout_zone_uncertainty
    params = list(inspect.signature(fn).parameters)
    assert params[:2] == ["model", "data"]
    assert "n_samples" in params
