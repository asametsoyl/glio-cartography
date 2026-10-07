import json

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from spatialcore.data import VolumeValidationError
from spatialcore.io import load_visium_section, volume_from_anndata
from spatialcore.provenance import build_manifest


def _write_outs(root, n=6, genes=5, seed=0, with_new_csv=True):
    rng = np.random.default_rng(seed)
    root.mkdir(parents=True)
    (root / "spatial").mkdir()
    counts = sp.csc_matrix(rng.poisson(2, (genes, n)))
    with h5py.File(root / "filtered_feature_bc_matrix.h5", "w") as f:
        m = f.create_group("matrix")
        m["data"], m["indices"], m["indptr"] = counts.data, counts.indices, counts.indptr
        m["shape"] = np.array(counts.shape)
        m["barcodes"] = np.array([f"BC{i}-1".encode() for i in range(n)])
        ft = m.create_group("features")
        ft["name"] = np.array([f"G{i}".encode() for i in range(genes)])
        ft["feature_type"] = np.array([b"Gene Expression"] * genes)
    rows = [(f"BC{i}-1", int(i < n - 1), i, i, 1000 + 10 * i, 2000 + 20 * i) for i in range(n)]
    df = pd.DataFrame(rows, columns=["barcode", "in_tissue", "array_row", "array_col", "pxl_row_in_fullres", "pxl_col_in_fullres"])
    if with_new_csv:
        df.to_csv(root / "spatial" / "tissue_positions.csv", index=False)
    else:
        df.to_csv(root / "spatial" / "tissue_positions_list.csv", index=False, header=False)
    (root / "spatial" / "scalefactors_json.json").write_text(json.dumps({"spot_diameter_fullres": 110.0}))


@pytest.mark.parametrize("new_csv", [True, False])
def test_load_visium_section(tmp_path, new_csv):
    _write_outs(tmp_path / "s1", with_new_csv=new_csv)
    X, obs, genes, meta = load_visium_section(tmp_path / "s1", "s1", 0)
    assert X.shape == (5, 5) and genes[0] == "G0" and len(obs) == 5  # one spot out of tissue dropped
    # 55 um disk == 110 px  ->  0.5 um/px
    assert obs["y_raw"].iloc[1] == pytest.approx((1000 + 10) * 0.5)
    assert obs["x_raw"].iloc[1] == pytest.approx((2000 + 20) * 0.5)
    assert meta.thickness_source == "unknown" and len(meta.checksum_sha256) == 64


def test_missing_position_is_an_error(tmp_path):
    _write_outs(tmp_path / "s", n=4)
    p = tmp_path / "s" / "spatial" / "tissue_positions.csv"
    df = pd.read_csv(p).iloc[:-1]
    df.to_csv(p, index=False)
    with pytest.raises(VolumeValidationError, match="no tissue position"):
        load_visium_section(tmp_path / "s", "s", 0)


def _adata(n, genes, seed):
    rng = np.random.default_rng(seed)
    a = ad.AnnData(sp.csr_matrix(rng.poisson(2, (n, len(genes))).astype(np.float32)))
    a.var_names = genes
    a.obs_names = [f"c{i}" for i in range(n)]
    a.obsm["spatial"] = rng.uniform(0, 1000, (n, 2))
    return a


def test_volume_from_anndata_intersects_genes_and_uses_given_order():
    adatas = {"b": _adata(4, ["g1", "g2", "g3"], 0), "a": _adata(5, ["g2", "g3", "g4"], 1)}
    vs = volume_from_anndata(adatas, order=["a", "b"], um_per_unit=1.0, thickness_um=10.0, thickness_source="nominal",
                             gap_um=0.0, gap_source="nominal")
    assert vs.var_names == ["g2", "g3"] and vs.ordered_section_ids == ["a", "b"]
    assert vs.delta_z("a", "b") == 10.0
    with pytest.raises(VolumeValidationError):
        volume_from_anndata(adatas, order=["a"], um_per_unit=1.0)


def test_manifest_labels_assumed_z():
    adatas = {"a": _adata(3, ["g1", "g2"], 0), "b": _adata(3, ["g1", "g2"], 1)}
    vs = volume_from_anndata(adatas, order=["a", "b"], um_per_unit=1.0)
    m = build_manifest(vs, config={"x": 1}, seed=3)
    assert m["z"]["mode"] == "mixed" and m["intended_use"] == "research use only"
    assert m["registration"] is None and m["seed"] == 3


def test_estimate_um_per_unit_recovers_scale():
    from spatialcore.io import estimate_um_per_unit
    from spatialcore.synthetic import hex_grid

    g = hex_grid((3000, 3000), 100.0)
    assert estimate_um_per_unit(g * 1.37 + 5.0) == pytest.approx(1 / 1.37, rel=1e-6)
    with pytest.raises(VolumeValidationError):
        estimate_um_per_unit(np.random.default_rng(0).uniform(0, 1000, (300, 2)))


def test_anndata_scale_estimated_and_recorded():
    from spatialcore.synthetic import hex_grid

    g = hex_grid((1500, 1500), 100.0)
    a = ad.AnnData(sp.csr_matrix(np.ones((len(g), 2), np.float32)))
    a.var_names = ["g1", "g2"]
    a.obsm["spatial"] = g / 0.73
    vs = volume_from_anndata({"a": a}, order=["a"])
    assert vs.uns["um_per_unit"]["a"] == pytest.approx(0.73, rel=1e-6)
    assert vs.obs["x_raw"].max() - vs.obs["x_raw"].min() == pytest.approx(np.ptp(g[:, 0]), rel=1e-6)
