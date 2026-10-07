"""
Tissue packs (python_backend/tissue_packs/*): loader, validation and the
guarantee that the engine is region-agnostic (not hard-wired to GBM).
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import tissue_pack as tp  # noqa: E402

# The GBM signatures exactly as they were hard-coded in train_gnn.py (v3.2.12).
LEGACY_GBM_SIGNATURES = {
    'Pseudopalisading Necrosis': ['hif1a', 'ca9', 'vegfa', 'bnip3', 'ldha', 'hk2', 'serpine1', 'ccl2'],
    'Microvascular Proliferation': ['plvap', 'acvrl1', 'vegfa', 'kdr', 'tgfbr2', 'itga5'],
    'Cellular Tumor': ['pdgfra', 'egfr', 'olig2', 'sox2', 'gja1', 'nusap1', 'mki67'],
    'Leading Edge': ['l1cam', 'ccnd2', 'gfap', 'akt1', 'stat3'],
    'Infiltrating Tumor': ['bcan', 'snap25', 'ddr1', 'cd44', 'vim', 'cxcr4'],
}


def _write_pack(root: Path, regions=None, tissue=None, citations=None, comparisons=None):
    root.mkdir(parents=True, exist_ok=True)
    tissue = tissue or {"id": "toy", "name": "Toy tissue", "version": "0.1.0"}
    (root / "tissue.yaml").write_text(yaml.safe_dump(tissue), encoding="utf-8")
    regions = regions if regions is not None else [
        {"name": "Alpha", "color": "#112233", "genes": ["g1", "g2", "g3"], "citation": "src"},
        {"name": "Beta", "color": "#445566", "genes": ["g4", "g5", "g6"], "citation": "src"},
    ]
    doc = {"regions": regions}
    if comparisons is not None:
        doc["comparisons"] = comparisons
    (root / "regions.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    citations = citations if citations is not None else {"src": {"title": "Toy", "license_status": "ok"}}
    (root / "citations.yaml").write_text(yaml.safe_dump({"citations": citations}), encoding="utf-8")
    return root


def test_gbm_pack_matches_the_previously_hardcoded_signatures():
    pack = tp.load_tissue_pack("gbm")
    assert pack.id == "gbm" and pack.version
    assert list(pack.signatures().items()) == list(LEGACY_GBM_SIGNATURES.items())


def test_gbm_pack_is_fully_specified():
    pack = tp.load_tissue_pack("gbm")
    assert len(pack.regions) == 5
    for r in pack.regions:
        assert r.citation in pack.citations, f"{r.name} has no citation"
        assert r.label_en and r.label_tr
        assert r.color.startswith("#") and len(r.color) == 7
    for a, b in pack.comparisons:
        assert a in pack.region_names and b in pack.region_names


def test_provenance_flags_unreviewed_licenses():
    prov = tp.load_tissue_pack("gbm").provenance()
    assert prov["id"] == "gbm"
    assert "ivygap_2018" in prov["citations"]
    assert "ivygap_2018" in prov["unreviewed_licenses"]


def test_pack_is_selected_by_environment_variable(tmp_path, monkeypatch):
    toy = _write_pack(tmp_path / "toy")
    monkeypatch.setenv("GLIO_TISSUE_PACK", str(toy))
    assert tp.load_tissue_pack().id == "toy"
    monkeypatch.setenv("GLIO_TISSUE_PACK", "gbm")
    assert tp.load_tissue_pack().id == "gbm"


def test_pack_found_via_packs_dir(tmp_path, monkeypatch):
    _write_pack(tmp_path / "mypack")
    monkeypatch.setenv("GLIO_TISSUE_PACKS_DIR", str(tmp_path))
    assert tp.load_tissue_pack("mypack").name == "Toy tissue"


def test_unknown_pack_error_lists_searched_locations(monkeypatch):
    monkeypatch.delenv("GLIO_TISSUE_PACKS_DIR", raising=False)
    with pytest.raises(tp.TissuePackError, match="not found"):
        tp.load_tissue_pack("does-not-exist")


@pytest.mark.parametrize("regions, message", [
    ([{"name": "A", "color": "#112233", "genes": ["a", "b", "c"]}], "at least 2 regions"),
    ([{"name": "A", "color": "#112233", "genes": ["a", "b", "c"]},
      {"name": "A", "color": "#445566", "genes": ["d", "e", "f"]}], "duplicate region name"),
    ([{"name": "A", "color": "red", "genes": ["a", "b", "c"]},
      {"name": "B", "color": "#445566", "genes": ["d", "e", "f"]}], "#RRGGBB"),
    ([{"name": "A", "color": "#112233", "genes": ["a", "b"]},
      {"name": "B", "color": "#445566", "genes": ["d", "e", "f"]}], "at least 3 signature genes"),
    ([{"name": "A", "color": "#112233", "genes": ["a", "b", "c"], "citation": "missing"},
      {"name": "B", "color": "#445566", "genes": ["d", "e", "f"]}], "not defined in citations.yaml"),
])
def test_invalid_regions_are_rejected_with_actionable_messages(tmp_path, regions, message):
    pack = _write_pack(tmp_path / "bad", regions=regions)
    with pytest.raises(tp.TissuePackError, match=message):
        tp.load_tissue_pack(str(pack))


def test_unknown_comparison_region_is_rejected(tmp_path):
    pack = _write_pack(tmp_path / "bad", comparisons=[["Alpha", "Gamma"]])
    with pytest.raises(tp.TissuePackError, match="unknown region 'Gamma'"):
        tp.load_tissue_pack(str(pack))


def test_missing_required_tissue_key_is_rejected(tmp_path):
    pack = _write_pack(tmp_path / "bad", tissue={"id": "x", "name": "X"})
    with pytest.raises(tp.TissuePackError, match="missing required key 'version'"):
        tp.load_tissue_pack(str(pack))


def test_unsupported_schema_version_is_rejected(tmp_path):
    pack = _write_pack(tmp_path / "bad", tissue={"id": "x", "name": "X", "version": "1", "schema_version": 99})
    with pytest.raises(tp.TissuePackError, match="schema_version"):
        tp.load_tissue_pack(str(pack))


def test_genes_are_lowercased_and_deduplicated(tmp_path):
    pack = _write_pack(tmp_path / "p", regions=[
        {"name": "A", "color": "#112233", "genes": ["EGFR", "egfr", " Sox2 ", "OLIG2"]},
        {"name": "B", "color": "#445566", "genes": ["a", "b", "c"]},
    ], citations={"src": {}})
    assert tp.load_tissue_pack(str(pack)).signatures()["A"] == ["egfr", "sox2", "olig2"]


def test_engine_is_not_hard_wired_to_gbm(tmp_path):
    """Run graph -> train -> export with a non-GBM pack in a fresh interpreter."""
    pytest.importorskip("torch")
    pytest.importorskip("torch_geometric")
    pytest.importorskip("anndata")
    toy = _write_pack(tmp_path / "cortex", tissue={"id": "cortex", "name": "Toy cortex", "version": "0.0.1"},
                      regions=[
                          {"name": "Layer 1", "color": "#AA0000", "genes": ["reln", "aqp4", "gfap"], "citation": "src"},
                          {"name": "Layer 2/3", "color": "#00AA00", "genes": ["cux2", "rorb", "satb2"], "citation": "src"},
                          {"name": "White Matter", "color": "#0000AA", "genes": ["mbp", "plp1", "mog"], "citation": "src"},
                      ], comparisons=[["Layer 1", "White Matter"]])
    out = tmp_path / "data.json"
    script = textwrap.dedent(f"""
        import sys, json
        sys.path.insert(0, {str(BACKEND_DIR)!r}); sys.path.insert(0, {str(BACKEND_DIR / "tests")!r})
        import numpy as np, torch
        import torch.nn.functional as F
        import train_gnn
        from test_gnn_smoke import _synthetic_adata
        assert train_gnn.ZONE_NAMES == ["Layer 1", "Layer 2/3", "White Matter"], train_gnn.ZONE_NAMES
        adata = _synthetic_adata(n_side=10)
        data = train_gnn.build_graph_data(adata, k_neighbors=6)
        assert data["spot"].zone_y.shape[1] == 3
        torch.manual_seed(0)
        model, hist, _ = train_gnn.train_model(data, cfg={{"hidden": 16, "heads": 2, "epochs": 2, "patience": 5, "n_gat": 1, "n_sage": 1}})
        model.eval()
        with torch.no_grad():
            ct, zone, _, _ = model(data)
        assert zone.shape[1] == 3
        train_gnn.export_attention_to_json(model, data, adata, list(data.ct_names),
            zone_preds=F.softmax(zone, dim=-1).numpy(), out_path={str(out)!r}, ct_preds=ct.numpy())
    """)
    env = {**__import__("os").environ, "GLIO_TISSUE_PACK": str(toy), "GLIO_OUTPUT_DIR": str(tmp_path / "o")}
    res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr[-2000:]
    meta = json.loads(out.read_text(encoding="utf-8"))["metadata"]
    assert meta["zones"] == ["Layer 1", "Layer 2/3", "White Matter"]
    assert meta["zone_colors"]["White Matter"] == "#0000AA"
    assert meta["comparisons"] == [["Layer 1", "White Matter"]]
    assert meta["tissue_pack"]["id"] == "cortex"
