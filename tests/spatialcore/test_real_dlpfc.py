"""Real-data smoke test; skipped unless the DLPFC mirror was fetched (benchmarks/fetch_data.py)."""
import os
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(os.environ.get("SPATIALCORE_DLPFC_DIR", Path(__file__).resolve().parents[2] / "benchmarks/data/dlpfc_maynard2021/1_DLPFC"))
pytestmark = pytest.mark.skipif(not (ROOT / "151673.h5ad").exists(), reason="DLPFC data not fetched")


def test_load_donor_as_volume_with_documented_geometry():
    import anndata as ad

    from spatialcore.io import volume_from_anndata

    ids = ["151673", "151674", "151675", "151676"]
    vs = volume_from_anndata({i: ad.read_h5ad(ROOT / f"{i}.h5ad") for i in ids}, order=ids,
                             thickness_um=10.0, thickness_source="nominal")
    assert vs.n_sections == 4 and vs.X.shape[0] == len(vs.obs)
    scales = vs.uns["um_per_unit"].values()
    assert all(0.6 < s < 0.9 for s in scales)           # ~0.73 um per fullres pixel
    assert vs.sections["z_source"].eq("assumed").iloc[1:].all()  # gaps unknown -> flagged, never silent
