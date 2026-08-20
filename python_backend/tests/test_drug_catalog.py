"""
drug_catalog.json yapısal bütünlüğü.

ChEMBL/PubMed API'lerine karşı canlı doğrulama (A-16 düzeltmesinde
yapıldı) ağ erişimi gerektirdiği için burada TEKRARLANMAZ — bu testler
yalnızca dosyanın yapısal olarak tutarlı kaldığını (gelecekte biri
elle düzenlerken kazara bozmadığını) garanti eder.
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG_PATH = REPO_ROOT / "python_backend" / "drug_catalog" / "drug_catalog.json"

CHEMBL_ID_RE = re.compile(r"^CHEMBL\d+$")
PMID_RE = re.compile(r"^\d+$")
REQUIRED_FIELDS = {
    "drug", "aliases", "drugClass", "mechanism", "target",
    "primaryZone", "phase", "fdaStatus", "evidenceScore", "chemblId", "pmids",
}


@pytest.fixture(scope="module")
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_is_valid_json_with_meta_and_entries(catalog):
    assert "_meta" in catalog
    assert "catalog" in catalog
    assert len(catalog["catalog"]) > 0


def test_every_entry_has_required_fields(catalog):
    for lr_key, entry in catalog["catalog"].items():
        missing = REQUIRED_FIELDS - set(entry.keys())
        assert not missing, f"{lr_key}: eksik alanlar {missing}"


def test_lr_key_format_matches_ligand_dash_receptor(catalog):
    for lr_key in catalog["catalog"]:
        assert "-" in lr_key, f"{lr_key}: LR anahtarı 'LIGAND-RECEPTOR' biçiminde olmalı"
        assert lr_key == lr_key.upper(), f"{lr_key}: LR anahtarı büyük harf olmalı"


def test_chembl_ids_are_well_formed_when_present(catalog):
    for lr_key, entry in catalog["catalog"].items():
        cid = entry.get("chemblId")
        if cid is not None:
            assert CHEMBL_ID_RE.match(cid), f"{lr_key}: geçersiz chemblId formatı {cid!r}"


def test_pmids_are_numeric_strings(catalog):
    for lr_key, entry in catalog["catalog"].items():
        for pmid in entry.get("pmids", []):
            assert PMID_RE.match(str(pmid)), f"{lr_key}: geçersiz PMID {pmid!r}"


def test_evidence_score_in_valid_range(catalog):
    for lr_key, entry in catalog["catalog"].items():
        score = entry.get("evidenceScore")
        assert 0.0 <= score <= 1.0, f"{lr_key}: evidenceScore [0,1] aralığında değil: {score}"


def test_no_drug_is_listed_as_its_own_alias(catalog):
    """
    A-16 düzeltmesinde bulunan bir hata deseni: bir ilacın 'aliases'
    listesi kendi adını tekrar içeriyordu. Bunun geri gelmediğini kontrol
    eder (tam bir "aliases gerçekten aynı ilaç mı" doğrulaması ChEMBL API
    gerektirir, burada yapılmaz).
    """
    for lr_key, entry in catalog["catalog"].items():
        drug_name = (entry.get("drug") or "").strip().lower()
        aliases_lower = {a.strip().lower() for a in entry.get("aliases", [])}
        assert drug_name not in aliases_lower, f"{lr_key}: '{entry['drug']}' kendi alias listesinde"
