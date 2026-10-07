import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from spatialcore.config import ZAssumptions
from spatialcore.data import SectionMeta, VolumeSet, VolumeValidationError, compute_z


def _vs(metas, per_section=3, obsm=None):
    obs = pd.concat([
        pd.DataFrame({"section_id": m.section_id, "x_raw": np.arange(per_section) * 100.0,
                      "y_raw": 0.0}, index=[f"{m.section_id}:{i}" for i in range(per_section)])
        for m in metas
    ])
    X = sp.csr_matrix(np.ones((len(obs), 4)))
    return VolumeSet.from_parts(X, obs, list("abcd"), metas, obsm=obsm)


def _m(sid, order, t=10.0, g=0.0, src="measured"):
    unk = src == "unknown"
    return SectionMeta(sid, order, thickness_um=None if unk else t, thickness_source=src,
                       gap_um=None if unk else g, gap_source=src)


def test_single_section_is_a_volume():
    vs = _vs([_m("a", 0)])
    assert vs.n_sections == 1 and vs.neighbours("a") == (None, None)
    assert vs.obs["z_um"].eq(0.0).all()


def test_z_rule_measured():
    s = pd.DataFrame([m.__dict__ for m in [_m("a", 0, 10, 5), _m("b", 1, 12, 3), _m("c", 2, 8, 0)]]).set_index("section_id")
    z = compute_z(s)
    assert list(z["z_um"]) == [0.0, 15.0, 30.0]  # last section's own terms never enter
    assert (z["z_source"] == "measured").all()


def test_physical_order_not_file_order():
    metas = [_m("late", 2), _m("early", 0), _m("mid", 1)]
    vs = _vs(metas)
    assert vs.ordered_section_ids == ["early", "mid", "late"]
    assert vs.neighbours("mid") == ("early", "late")
    z = vs.obs.groupby("section_id")["z_um"].first()
    assert z["early"] < z["mid"] < z["late"]


def test_unknown_thickness_is_assumed_and_flagged():
    metas = [_m("a", 0, src="unknown"), _m("b", 1, src="unknown"), _m("c", 2, src="unknown")]
    vs = _vs(metas)
    assert vs.sections.loc["b", "z_source"] == "assumed" and np.isnan(vs.sections.loc["b", "z_um"])
    assert vs.obs["z_is_assumed"].iloc[3:].all()
    assert vs.delta_z("a", "c") == pytest.approx(2 * ZAssumptions().assumed_thickness_um)


def test_unknown_term_poisons_only_later_sections():
    metas = [_m("a", 0), _m("b", 1, src="unknown"), _m("c", 2)]
    z = _vs(metas).sections
    assert z.loc["a", "z_source"] == "measured" and z.loc["b", "z_source"] == "measured"
    assert z.loc["c", "z_source"] == "assumed"


def test_none_and_unknown_must_agree():
    with pytest.raises(VolumeValidationError):
        SectionMeta("a", 0, thickness_um=None, thickness_source="measured")


def test_invariants_fail_loudly():
    with pytest.raises(VolumeValidationError, match="unique"):
        _vs([_m("a", 0), _m("b", 0)])
    with pytest.raises(VolumeValidationError, match="section identity"):
        _vs([_m("a", 0)], obsm={"X_batch": np.zeros((3, 2))})
    with pytest.raises(VolumeValidationError, match="rows"):
        _vs([_m("a", 0)], obsm={"X_pca": np.zeros((2, 2))})


def test_to_anndata_roundtrip_shape():
    vs = _vs([_m("a", 0), _m("b", 1)])
    a = vs.to_anndata()
    assert a.shape == vs.X.shape and "spatial_raw" in a.obsm
