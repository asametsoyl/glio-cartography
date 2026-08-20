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


def test_pathway_mapper_has_its_own_scoped_unverified_context():
    import pathway_mapper
    assert hasattr(pathway_mapper, "_UNVERIFIED_SSL_CONTEXT")
    assert isinstance(pathway_mapper._UNVERIFIED_SSL_CONTEXT, ssl.SSLContext)
    assert pathway_mapper._UNVERIFIED_SSL_CONTEXT.verify_mode == ssl.CERT_NONE
