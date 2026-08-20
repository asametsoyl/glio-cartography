"""
check_env.py — macOS RAM fallback yolu regresyon testleri.

C-02 bulgusu iki kusur içeriyordu: (1) sayfa boyutu 4096 olarak sabit
kodlanmıştı (Apple Silicon'da gerçek değer 16384 — 4x hata), (2) `vm_stat`
çıktısının sayısal olmayan başlık satırı ayrıştırılmaya çalışılınca tüm
fallback fonksiyonu istisna ile çöküyordu. Bu testler ikisini de gerçek
`vm_stat`/`sysctl` çıktı biçimini taklit ederek doğrular.
"""
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import check_env  # noqa: E402


REAL_VM_STAT_OUTPUT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                     4618.
Pages active:                                 110444.
Pages inactive:                               100056.
Pages speculative:                              9499.
Pages throttled:                                   0.
Pages wired down:                             126379.
Pages purgeable:                                1685.
"Translation faults":                      129158603.
Pages copy-on-write:                         1627059.
Pages zero filled:                          61860098.
Pages reactivated:                          46805013.
Pages purged:                                6994196.
"""


def _fake_check_output(cmd, *args, **kwargs):
    if cmd[:2] == ["sysctl", "-n"] and cmd[2] == "hw.memsize":
        return b"8589934592"  # 8 GB
    if cmd[:2] == ["sysctl", "-n"] and cmd[2] == "hw.pagesize":
        return b"16384"
    if cmd[0] == "vm_stat":
        return REAL_VM_STAT_OUTPUT.encode("utf-8")
    raise AssertionError(f"unexpected subprocess call: {cmd}")


def _block_psutil_import():
    """check_ram() önce psutil'i dener — bu test özellikle psutil YOKKEN
    devreye giren vm_stat/sysctl fallback yolunu hedeflediği için,
    psutil'in (bu ortamda kurulu olsa bile) geçici olarak
    bulunamıyormuş gibi davranmasını sağlar."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("psutil intentionally blocked for this test")
        return real_import(name, *args, **kwargs)

    return mock.patch("builtins.__import__", side_effect=fake_import)


@pytest.mark.skipif(sys.platform != "darwin", reason="check_ram'in darwin dalı yalnızca macOS'ta")
def test_macos_ram_fallback_does_not_crash_on_header_line():
    """
    `vm_stat`'ın ilk satırı ("Mach Virtual Memory Statistics: (page size
    of 16384 bytes)") sayısal olmayan bir değer içerir. Eski kod bu
    satırı ayrıştırmaya çalışırken ValueError ile çöküyordu.
    """
    with _block_psutil_import(), \
         mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output):
        result = check_env.check_ram()
    assert result.get("available_gb") is not None


@pytest.mark.skipif(sys.platform != "darwin", reason="check_ram'in darwin dalı yalnızca macOS'ta")
def test_macos_ram_fallback_uses_real_page_size_not_hardcoded_4096():
    """
    free_pages=4618, inactive_pages=100056 -> toplam 104674 sayfa.
    Doğru (16384) sayfa boyutuyla ~1.59 GB; eski hatalı sabit (4096)
    ile ~0.40 GB çıkardı (tam 4x fark) — bu test doğru değeri bekler.
    """
    with _block_psutil_import(), \
         mock.patch.object(subprocess, "check_output", side_effect=_fake_check_output):
        result = check_env.check_ram()
    expected_gb = (4618 + 100056) * 16384 / 1024**3
    assert result["available_gb"] == pytest.approx(expected_gb, rel=0.01)
    # Eski (yanlış) 4096 sayfa boyutuyla üretilecek değerden belirgin şekilde farklı olmalı
    wrong_gb_with_old_bug = (4618 + 100056) * 4096 / 1024**3
    assert result["available_gb"] > wrong_gb_with_old_bug * 3
