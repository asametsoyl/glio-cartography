"""Phantom-based registration checks (E = easy tier). Thresholds follow docs/ZBRIDGE_DESIGN.md Faz 3:
rotation < 1 deg, translation < 0.25 x spot pitch, scale error < 2 %."""
import numpy as np
import pytest

from spatialcore.config import PhantomConfig, QCConfig, RegistrationConfig
from spatialcore.qc import spatial_coherence
from spatialcore.registration import Transform, register_pair, register_volume
from spatialcore.synthetic import build_phantom

N_GENES = 500
CFG = RegistrationConfig(n_starts=12)
PITCH = 100.0


def _true_pair(truth, kf, km):
    c = np.array(truth.config.extent_um) / 2
    f, m = truth.transforms[kf], truth.transforms[km]
    return (Transform(np.eye(2), c).compose(Transform(f["A"], f["t"]))
            .compose(Transform(m["A"], m["t"]).inverse()).compose(Transform(np.eye(2), -c)))


@pytest.fixture(scope="module")
def easy():
    p = build_phantom(PhantomConfig.from_tier("E", n_genes=N_GENES, seed=21))
    rep = register_volume(p.volume, CFG)
    return p, rep


def test_pairwise_accuracy_meets_design_thresholds(easy):
    p, rep = easy
    xy = p.volume.obs[["x_raw", "y_raw"]].to_numpy()
    t = p.truth
    for pr in rep.pairs:
        kf, km = int(pr.upper[1:]), int(pr.lower[1:])
        true = _true_pair(t, kf, km)
        rows = p.volume.rows(pr.lower)
        d, dt = pr.transform.decompose(), true.decompose()
        assert abs(d["angle_deg"] - dt["angle_deg"]) < 1.0
        assert abs(d["scale"] / dt["scale"] - 1) < 0.02
        err = np.linalg.norm(pr.transform.apply(xy[rows]) - true.apply(xy[rows]), axis=1)
        assert np.median(err) < 0.25 * PITCH


def test_chained_section_error_stays_below_half_pitch(easy):
    p, _ = easy
    v, t = p.volume, p.truth
    err = np.linalg.norm(v.obs[["x_registered", "y_registered"]].to_numpy() - t.reference_xy(), axis=1)
    assert err.max() < 3 * PITCH and np.median(err) < 0.5 * PITCH
    for k in range(7):
        assert np.median(err[t.section_index == k]) < 0.5 * PITCH


def test_outputs_written_to_volume(easy):
    p, rep = easy
    v = p.volume
    for col in ("x_registered", "y_registered", "registration_confidence", "overlap_up", "overlap_down"):
        assert col in v.obs
    assert v.obs["overlap_up"].iloc[v.rows("s00")].isna().all()          # top section has no upper neighbour
    assert v.obs["overlap_down"].iloc[v.rows("s06")].isna().all()
    assert len(v.registrations) == 6 and v.obsm["spatial_registered"].shape == (len(v.obs), 2)
    s = list(rep.sigma_reg_um.values())
    assert s[0] == 0.0 and np.all(np.diff(s) >= 0)                        # uncertainty only accumulates
    assert set(v.sections["qc_status"]) <= {"PASS", "WARNING", "FAIL"}


def test_easy_pairs_pass_qc(easy):
    _, rep = easy
    assert all(pr.qc.status == "PASS" for pr in rep.pairs), [pr.qc.reasons for pr in rep.pairs]


def test_registration_is_deterministic():
    p = build_phantom(PhantomConfig.from_tier("E", n_genes=200, seed=3, n_sections=2, finger_sections=(0, 1)))
    a = register_volume(build_phantom(p.truth.config).volume, CFG).pairs[0].transform
    b = register_volume(build_phantom(p.truth.config).volume, CFG).pairs[0].transform
    assert np.array_equal(a.A, b.A) and np.array_equal(a.t, b.t)


def test_partial_overlap_raises_null_mass():
    e = build_phantom(PhantomConfig.from_tier("E", n_genes=N_GENES, seed=22, n_sections=3, finger_sections=(0, 2)))
    m = build_phantom(PhantomConfig.from_tier("M", n_genes=N_GENES, seed=22, n_sections=3, finger_sections=(0, 2)))
    oe = np.nanmean(register_volume(e.volume, CFG).pairs[0].qc.overlap)
    om = np.nanmean(register_volume(m.volume, CFG).pairs[0].qc.overlap)
    assert oe > 0.95 and om < oe - 0.05


def test_presence_posterior_tracks_true_tissue_presence():
    from scipy.spatial import cKDTree

    p = build_phantom(PhantomConfig.from_tier("M", n_genes=N_GENES, seed=23, n_sections=3, finger_sections=(0, 2)))
    register_volume(p.volume, CFG)
    v, t = p.volume, p.truth
    up = v.obs["overlap_up"].to_numpy()[t.rows(1)]
    dnn = cKDTree(t.tissue_xyz[t.rows(0), :2]).query(t.tissue_xyz[t.rows(1), :2])[0]
    present = dnn < 0.8 * PITCH
    from spatialcore.registration import auc

    assert 0.1 < present.mean() < 0.95        # the test is only meaningful if both cases occur
    assert auc(up, present) > 0.9


def test_qc_flags_broken_sections():
    qc = QCConfig()
    p = build_phantom(PhantomConfig.from_tier("E", n_genes=N_GENES, seed=24, n_sections=2, finger_sections=(0, 1)))
    other = build_phantom(PhantomConfig.from_tier("E", n_genes=N_GENES, seed=124, n_sections=2, finger_sections=(0, 1)))
    v, w = p.volume, other.volume
    xy, xyw = v.obs[["x_raw", "y_raw"]].to_numpy(), w.obs[["x_raw", "y_raw"]].to_numpy()
    ra, rb = v.rows("s00"), v.rows("s01")
    good = register_pair(v.X[ra], v.X[rb], xy[ra], xy[rb], CFG, qc, ("a", "b"))
    perm = np.random.default_rng(0).permutation(len(rb))
    scrambled = register_pair(v.X[ra], v.X[rb][perm], xy[ra], xy[rb], CFG, qc, ("a", "b"))
    wrong = register_pair(v.X[ra], w.X[w.rows("s01")], xy[ra], xyw[w.rows("s01")], CFG, qc, ("a", "b"))
    assert good.qc.status == "PASS"
    assert scrambled.qc.status == "FAIL" and any("coherence" in r for r in scrambled.qc.reasons)
    assert wrong.qc.status == "FAIL" and any("expr_gain" in r for r in wrong.qc.reasons)


def test_single_section_and_missing_section():
    single = build_phantom(PhantomConfig.from_tier("E", n_genes=100, seed=5, n_sections=1, finger_sections=(0, 0)))
    rep = register_volume(single.volume, CFG)
    assert rep.pairs == [] and rep.sigma_reg_um == {"s00": 0.0}
    assert np.allclose(single.volume.obs[["x_registered", "y_registered"]].to_numpy(),
                       single.volume.obs[["x_raw", "y_raw"]].to_numpy())
    gap = build_phantom(PhantomConfig.from_tier("E", n_genes=N_GENES, seed=25, n_sections=4,
                                                 finger_sections=(0, 3), missing_sections=(1,)))
    rep = register_volume(gap.volume, CFG)
    assert [(p.upper, p.lower) for p in rep.pairs] == [("s00", "s02"), ("s02", "s03")]
    assert gap.volume.delta_z("s00", "s02") == pytest.approx(20.0)
    err = np.linalg.norm(gap.volume.obs[["x_registered", "y_registered"]].to_numpy() - gap.truth.reference_xy(), axis=1)
    assert np.median(err) < 0.5 * PITCH


def test_spatial_coherence_separates_structure_from_noise():
    rng = np.random.default_rng(0)
    xy = np.column_stack([np.repeat(np.arange(30), 30), np.tile(np.arange(30), 30)]) * 100.0
    smooth = np.column_stack([np.sin(xy[:, 0] / 600), np.cos(xy[:, 1] / 600), np.ones(len(xy)) * 0.3])
    smooth /= np.linalg.norm(smooth, axis=1, keepdims=True)
    noise = rng.normal(size=smooth.shape)
    noise /= np.linalg.norm(noise, axis=1, keepdims=True)
    assert spatial_coherence(xy, smooth, 6) > 0.05 and abs(spatial_coherence(xy, noise, 6)) < 0.05
