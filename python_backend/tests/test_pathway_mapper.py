"""
pathway_mapper.py — D-20 (global SSL bypass) regresyon testi.

Önceki sürüm modül import edilir edilmez
`ssl._create_default_https_context = ssl._create_unverified_context`
çalıştırıyordu — bu, AYNI süreçte çalışan başka HER HTTPS isteğini
(ilgisiz modüller dahil) sertifika doğrulamasız bırakıyordu. Düzeltme,
doğrulamayı yalnızca bu modülün kendi `urlopen()` çağrılarına
`context=` ile veriyor. Bu test, modülü import etmenin global `ssl`
varsayılanını DEĞİŞTİRMEDİĞİNİ doğrular.
"""
import importlib
import os
import ssl
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_importing_pathway_mapper_does_not_touch_global_ssl_default():
    original_default_factory = ssl._create_default_https_context
    try:
        import pathway_mapper  # noqa: F401
        assert ssl._create_default_https_context is original_default_factory, (
            "pathway_mapper import edilince global ssl._create_default_https_context "
            "değişti — bu, aynı süreçteki BAŞKA HTTPS isteklerini de doğrulamasız "
            "bırakır (bkz. denetim raporu D-20)."
        )
    finally:
        ssl._create_default_https_context = original_default_factory


def test_pathway_mapper_verifies_certificates_by_default():
    os.environ.pop("GLIO_ALLOW_INSECURE_SSL", None)
    import pathway_mapper
    importlib.reload(pathway_mapper)
    assert hasattr(pathway_mapper, "_UNVERIFIED_SSL_CONTEXT")
    assert isinstance(pathway_mapper._UNVERIFIED_SSL_CONTEXT, ssl.SSLContext)
    assert pathway_mapper._UNVERIFIED_SSL_CONTEXT.verify_mode == ssl.CERT_REQUIRED, (
        "Varsayılan olarak sertifika doğrulaması AÇIK olmalı — atlamak yalnızca "
        "GLIO_ALLOW_INSECURE_SSL=1 ile açıkça istenmeli."
    )


def test_pathway_mapper_allows_opt_in_insecure_ssl():
    os.environ["GLIO_ALLOW_INSECURE_SSL"] = "1"
    try:
        import pathway_mapper
        importlib.reload(pathway_mapper)
        assert pathway_mapper._UNVERIFIED_SSL_CONTEXT.verify_mode == ssl.CERT_NONE
    finally:
        os.environ.pop("GLIO_ALLOW_INSECURE_SSL", None)
        import pathway_mapper
        importlib.reload(pathway_mapper)


def test_resolve_zone_key_accepts_id_style_and_display_names():
    import pathway_mapper as pm
    keys = ["Pseudopalisading Necrosis", "Leading Edge", "Cellular Tumor"]
    assert pm.resolve_zone_key("Leading Edge", keys) == "Leading Edge"
    assert pm.resolve_zone_key("Leading_Edge", keys) == "Leading Edge"
    assert pm.resolve_zone_key("leading-edge", keys) == "Leading Edge"
    assert pm.resolve_zone_key("pseudopalisading_necrosis", keys) == "Pseudopalisading Necrosis"
    assert pm.resolve_zone_key("Unknown Zone", keys) is None


def test_zonal_degs_do_not_silently_fall_back_to_global_for_id_style_zone(tmp_path, monkeypatch):
    """UI sends 'Leading_Edge' while data.json keys are 'Leading Edge'."""
    import json
    import numpy as np
    import pytest
    anndata = pytest.importorskip("anndata")
    import pathway_mapper as pm

    n = 30
    data = {"spots": [{"zones": {"Leading Edge": 1.0 if i < 15 else 0.0, "Cellular Tumor": 0.0 if i < 15 else 1.0}}
                      for i in range(n)]}
    data_path = tmp_path / "data.json"
    data_path.write_text(json.dumps(data), encoding="utf-8")
    adata = anndata.AnnData(X=np.random.default_rng(0).poisson(2.0, (n, 12)).astype(np.float32))

    called = {}
    monkeypatch.setattr(pm, "find_lr_degs", lambda *a, **k: called.setdefault("global", True) and [])
    pm.find_lr_degs_zonal(adata, "A", "B", data_path, "Leading_Edge", zone_threshold=0.4)
    assert "global" not in called, "id-style zone name fell back to the global analysis"
