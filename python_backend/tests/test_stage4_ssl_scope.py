"""
stage4_visualization.py — D-20 (global SSL bypass) regresyon testi.

Aynı anti-pattern pathway_mapper.py ile pathway_mapper.py'den BAĞIMSIZ
olarak bu dosyada da vardı (OmniPath L-R indirmesi için) — ayrı ayrı
düzeltildi, bu yüzden ayrı test ediliyor.

NOT: stage4_visualization.py import edilirken `GLIO_OUTPUT_DIR` çevre
değişkenini kontrol edip yoksa `sys.exit(1)` çağırıyor (modül seviyesinde
bir güvenlik kontrolü) — bu yüzden import öncesi geçici bir dizin
ayarlanması gerekiyor.
"""
import importlib
import os
import ssl
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
for p in (str(BACKEND_DIR), str(BACKEND_DIR / "stages")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _import_stage4(monkeypatch, tmp_path):
    # stage4_visualization modül-seviyesinde GLIO_OUTPUT_DIR'ı ev dizini
    # veya sistem geçici dizini altında olmaya zorluyor (path traversal
    # koruması) — testin kendi tmp_path'i genelde /private/var/folders
    # altında olur ve bu kontrolü geçer (tempfile.gettempdir() ile aynı kök).
    monkeypatch.setenv("GLIO_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("GLIO_PATIENT_ID", "TestPatient")
    sys.modules.pop("stage4_visualization", None)
    return importlib.import_module("stage4_visualization")


def test_importing_stage4_does_not_touch_global_ssl_default(monkeypatch, tmp_path):
    original_default_factory = ssl._create_default_https_context
    try:
        _import_stage4(monkeypatch, tmp_path)
        assert ssl._create_default_https_context is original_default_factory, (
            "stage4_visualization import edilince global ssl._create_default_https_context "
            "değişti (bkz. denetim raporu D-20)."
        )
    finally:
        ssl._create_default_https_context = original_default_factory
        sys.modules.pop("stage4_visualization", None)


def test_stage4_has_its_own_scoped_unverified_context(monkeypatch, tmp_path):
    mod = _import_stage4(monkeypatch, tmp_path)
    try:
        assert hasattr(mod, "_UNVERIFIED_SSL_CONTEXT")
        assert isinstance(mod._UNVERIFIED_SSL_CONTEXT, ssl.SSLContext)
        assert mod._UNVERIFIED_SSL_CONTEXT.verify_mode == ssl.CERT_NONE
    finally:
        sys.modules.pop("stage4_visualization", None)
