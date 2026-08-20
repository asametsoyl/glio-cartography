"""
renderer/locales/{tr,en}.json anahtar bütünlüğü.

Bu oturumda birkaç kez elle doğrulanan "iki dosyanın anahtar kümeleri
birebir eşleşiyor mu" ve "{{placeholder}} söz dizimi doğru mu" kontrollerini
kalıcı bir regresyon testine çeviriyor (bkz. C-09, i18n eklemeleri).
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TR_PATH = REPO_ROOT / "renderer" / "locales" / "tr.json"
EN_PATH = REPO_ROOT / "renderer" / "locales" / "en.json"


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


@pytest.fixture(scope="module")
def tr_flat():
    return _flatten(json.loads(TR_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def en_flat():
    return _flatten(json.loads(EN_PATH.read_text(encoding="utf-8")))


def test_locale_files_are_valid_json():
    json.loads(TR_PATH.read_text(encoding="utf-8"))
    json.loads(EN_PATH.read_text(encoding="utf-8"))


def test_locale_key_sets_match_exactly(tr_flat, en_flat):
    missing_in_en = set(tr_flat) - set(en_flat)
    missing_in_tr = set(en_flat) - set(tr_flat)
    assert not missing_in_en, f"TR'de olup EN'de eksik anahtarlar: {sorted(missing_in_en)}"
    assert not missing_in_tr, f"EN'de olup TR'de eksik anahtarlar: {sorted(missing_in_tr)}"


_SINGLE_BRACE_RE = re.compile(r"(?<!\{)\{[a-zA-Z][a-zA-Z0-9_]*\}(?!\})")


def test_no_single_brace_placeholders(tr_flat, en_flat):
    """
    i18n motoru yalnızca {{ad}} (çift süslü parantez) tanır — bkz. app/i18n.js.
    Tek süslü parantezli bir yer tutucu ({ad}) sessizce hiç doldurulmaz
    (bkz. denetim raporu bulgusu C-09). Bu test o regresyonun geri
    gelmediğini doğrular.
    """
    for label, flat in (("tr.json", tr_flat), ("en.json", en_flat)):
        offenders = {k: v for k, v in flat.items() if isinstance(v, str) and _SINGLE_BRACE_RE.search(v)}
        assert not offenders, f"{label} içinde tek süslü parantezli placeholder(lar): {offenders}"


def test_double_brace_placeholders_balanced(tr_flat, en_flat):
    """Her {{ için bir }} olmalı — temel bir söz dizimi bütünlüğü kontrolü."""
    for label, flat in (("tr.json", tr_flat), ("en.json", en_flat)):
        for k, v in flat.items():
            if not isinstance(v, str):
                continue
            assert v.count("{{") == v.count("}}"), f"{label}:{k} içinde dengesiz {{{{ }}}}: {v!r}"
