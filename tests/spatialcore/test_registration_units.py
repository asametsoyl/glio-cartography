import numpy as np
import pytest

from spatialcore.config import QCConfig, RegistrationConfig
from spatialcore.qc import pairwise_qc
from spatialcore.registration import IsotonicCalibrator, Transform, auc, expected_calibration_error, raw_confidence
from spatialcore.registration.affine import affine_fit
from spatialcore.registration.chain import PairResult, chain_poses
from spatialcore.registration.rigid import rigid_fit
from spatialcore.registration.soft_correspondence import em_register, log_expression_norm, row_posterior


def _moments(X, Y):
    mx, my = X.mean(0), Y.mean(0)
    Xc, Yc = X - mx, Y - my
    return Yc.T @ Xc, Xc.T @ Xc, mx, my


def test_transform_algebra():
    T = Transform.rotation(30, about=np.array([5.0, -2.0]))
    x = np.random.default_rng(0).normal(size=(10, 2))
    assert np.allclose(T.inverse().apply(T.apply(x)), x)
    S = Transform(np.array([[1.1, 0.0], [0.0, 1.1]]), np.array([3.0, 1.0]))
    assert np.allclose(S.compose(T).apply(x), S.apply(T.apply(x)))
    d = T.decompose()
    assert d["angle_deg"] == pytest.approx(30.0) and d["scale"] == pytest.approx(1.0) and d["shear"] == pytest.approx(0.0, abs=1e-12)


def test_decompose_matches_phantom_convention():
    ang, sc, sh = 17.0, 1.04, 0.03
    a = np.deg2rad(ang)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    A = R @ np.array([[1.0, sh], [0.0, 1.0]]) * sc
    d = Transform(A, np.zeros(2)).decompose()
    assert (d["angle_deg"], d["scale"], d["shear"]) == pytest.approx((ang, sc, sh))


def test_rigid_and_affine_m_steps_recover_exact_transform():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(200, 2)) * 50
    T = Transform.rotation(22, about=np.array([1.0, 2.0]))
    Y = T.apply(X)
    A, t = rigid_fit(*_moments(X, Y))
    assert np.allclose(A, T.A) and np.allclose(t, T.t)
    B = np.array([[1.05, 0.1], [-0.02, 0.97]])
    Y2 = X @ B.T + np.array([4.0, -3.0])
    B2, t2 = affine_fit(*_moments(X, Y2))
    assert np.allclose(B2, B) and np.allclose(t2, [4.0, -3.0])


def test_rigid_never_returns_reflection():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(100, 2)) * 30
    Y = X * np.array([-1.0, 1.0])  # a mirror image
    A, _ = rigid_fit(*_moments(X, Y))
    assert np.linalg.det(A) > 0


def test_em_recovers_rigid_transform_on_clean_points():
    rng = np.random.default_rng(3)
    X = rng.uniform(-500, 500, (400, 2))
    T = Transform.rotation(12, about=np.array([0.0, 0.0]))
    T = Transform(T.A, np.array([30.0, -20.0]))
    Y = T.apply(X) + rng.normal(0, 3, X.shape)
    F = np.zeros((400, 2))
    cfg = RegistrationConfig(expression_weight=0.0, sigma_min_um=5.0)
    r = em_register(X, Y, F, F, Transform.identity(), cfg, "rigid", sigma_init_um=100.0)
    assert r.transform.decompose()["angle_deg"] == pytest.approx(12.0, abs=0.3)
    assert np.allclose(r.transform.t, T.t, atol=3.0)


def test_expression_norm_is_log_mean_exp():
    rng = np.random.default_rng(4)
    FX = rng.normal(size=(5, 4)); FX /= np.linalg.norm(FX, axis=1, keepdims=True)
    FY = rng.normal(size=(30, 4)); FY /= np.linalg.norm(FY, axis=1, keepdims=True)
    got = log_expression_norm(FX, FY, 7.0, block=8)
    want = np.log(np.exp(7.0 * FY @ FX.T).mean(0))
    assert np.allclose(got, want)
    assert np.all(log_expression_norm(FX, FY, 0.0, 8) == 0.0)


def test_row_posterior_far_points_are_null():
    cfg = RegistrationConfig(expression_weight=0.0)
    Y = np.array([[0.0, 0.0], [5000.0, 5000.0]])
    X = np.array([[1.0, 1.0], [2.0, -1.0]])
    F = np.ones((2, 1))
    pn, _ = row_posterior(Y, X, F[:, :1], F[:, :1], 50.0 ** 2, cfg)
    assert pn[0] < 0.2 and pn[1] > 0.999


def test_pava_calibrator_monotone_and_ece():
    rng = np.random.default_rng(5)
    raw = rng.uniform(0, 1, 5000)
    good = rng.uniform(0, 1, 5000) < raw ** 2
    cal = IsotonicCalibrator.fit(raw, good, fitted_on="unit-test")
    p = cal(np.linspace(0, 1, 50))
    assert np.all(np.diff(p) >= -1e-12)
    assert expected_calibration_error(cal(raw), good) < 0.03
    assert expected_calibration_error(raw, good) > expected_calibration_error(cal(raw), good)


def test_auc_known_values():
    assert auc(np.array([0.1, 0.4, 0.35, 0.8]), np.array([0, 0, 1, 1])) == pytest.approx(0.75)
    assert auc(np.array([1.0, 1.0, 1.0, 1.0]), np.array([0, 1, 0, 1])) == pytest.approx(0.5)
    assert np.isnan(auc(np.array([1.0, 2.0]), np.array([1, 1])))


def test_raw_confidence_bounds():
    c = raw_confidence(np.array([0.0, 1.0, 0.5]), np.array([1.0, 1.0, -0.4]))
    assert list(c) == [1.0, 0.0, 0.0]


def _qc(overlap, gain, T=None):
    n = 100
    pn = np.ones(n)
    pn[: int(round(overlap * n))] = 0.0  # a share `overlap` of spots has a counterpart
    ag = np.full(n, gain)
    return pairwise_qc(T or Transform.identity(), pn, ag, np.zeros(n), QCConfig())


def test_qc_levels_and_reasons():
    assert _qc(0.9, 0.3).status == "PASS"
    w = _qc(0.2, 0.3)
    assert w.status == "WARNING" and any("overlap" in r for r in w.reasons)
    assert _qc(0.9, 0.0).status == "FAIL"
    bad = Transform(np.array([[1.4, 0], [0, 1.4]]), np.zeros(2))
    assert _qc(0.9, 0.3, bad).status == "FAIL"


def test_chain_composes_and_accumulates_variance():
    class _EM:  # only fields chain_poses touches via PairResult
        pass

    def pair(u, l, T, s):
        return PairResult(u, l, T, _EM(), None, s, 0.0, None, None, None, None)

    T1, T2 = Transform.rotation(10), Transform(np.eye(2), np.array([5.0, 0.0]))
    poses, sig = chain_poses([pair("a", "b", T1, 3.0), pair("b", "c", T2, 4.0)], ["a", "b", "c"])
    x = np.array([[1.0, 2.0]])
    assert np.allclose(poses["c"].apply(x), T1.apply(T2.apply(x)))
    assert sig["a"] == 0.0 and sig["b"] == pytest.approx(3.0) and sig["c"] == pytest.approx(5.0)
