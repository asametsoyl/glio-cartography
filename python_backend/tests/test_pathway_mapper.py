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
