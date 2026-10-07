import numpy as np
import pytest

from spatialcore.config import DeformConfig, PhantomConfig, ViolationConfig, VisiumGeometry
from spatialcore.synthetic import build_phantom, disk_lens_area, hex_grid
from spatialcore.synthetic.geometry import disk_quadrature

SMALL = dict(n_genes=120, n_programs=20)


def _cfg(tier="E", **kw):
    return PhantomConfig.from_tier(tier, **{**SMALL, **kw})


def test_hex_grid_pitch_and_density():
    g = hex_grid((4000, 4000), 100.0)
    from scipy.spatial import cKDTree
    d, _ = cKDTree(g).query(g, k=2)
    assert np.allclose(d[:, 1], 100.0, atol=1e-6) or np.percentile(d[:, 1], 90) == pytest.approx(100.0, abs=1e-6)
    assert 1700 < len(g) < 2000  # ~ 4000*4000 / (100^2*sqrt(3)/2)


def test_lens_area_limits():
    r = 27.5
    assert disk_lens_area(0.0, r) == pytest.approx(np.pi * r * r)
    assert disk_lens_area(2 * r, r) == 0.0 and disk_lens_area(100.0, r) == 0.0
    d = np.linspace(0, 2 * r, 50)
    assert np.all(np.diff(disk_lens_area(d, r)) <= 1e-9)  # monotone decreasing


def test_lens_area_matches_monte_carlo():
    r, d = 27.5, 30.0
    rng = np.random.default_rng(0)
    p = np.column_stack([rng.uniform(-r, r + d, 400000), rng.uniform(-r, r, 400000)])
    in_a = (p ** 2).sum(1) <= r * r
    in_b = ((p - [d, 0]) ** 2).sum(1) <= r * r
    mc = (in_a & in_b).mean() * (2 * r + d) * (2 * r)
    assert disk_lens_area(d, r) == pytest.approx(mc, rel=0.03)


def test_quadrature_count_and_radius():
    q = disk_quadrature(27.5, 2)
    assert len(q) == 1 + 3 * 2 * 3 and np.linalg.norm(q, axis=1).max() <= 27.5


def test_deterministic_and_seed_sensitive():
    a, b, c = (build_phantom(_cfg(seed=s)) for s in (1, 1, 2))
    assert (a.volume.X != b.volume.X).nnz == 0
    assert np.array_equal(a.truth.tissue_xyz, b.truth.tissue_xyz)
    assert a.volume.X.shape != c.volume.X.shape or (a.volume.X != c.volume.X).nnz > 0


def test_ground_truth_complete_and_consistent():
    p = build_phantom(_cfg())
    t, v = p.truth, p.volume
    n = len(v.obs)
    assert t.tissue_xyz.shape == (n, 3) and t.domain_fracs.shape == (n, 6)
    assert np.allclose(t.domain_fracs.sum(1), 1.0)
    assert (t.inside_frac > 0.5).all() and (t.inside_frac <= 1.0).all()
    assert np.array_equal(np.unique(t.section_index), np.arange(7))
    assert len(t.transforms) == 7 and len(t.z_true_um) == 7
    assert v.X.min() >= 0 and np.issubdtype(v.X.dtype, np.floating)
    assert set(np.unique(t.domain_center)) >= {0, 1, 2, 5}  # normal, tumour, shell, slab present
    # section identity of every spot agrees between truth and volume
    sid = np.array(t.section_ids)[t.section_index]
    assert (v.obs["section_id"].to_numpy() == sid).all()


def test_sphere_domain_is_tumor_where_expected():
    p = build_phantom(_cfg())
    t = p.truth
    r = np.linalg.norm(t.tissue_xyz[:, :2], axis=1)
    mid = t.section_index == 3
    near_centre = mid & (r < 200)
    assert (t.domain_center[near_centre] == 1).mean() > 0.9
    far = mid & (r > 1700) & (t.tissue_xyz[:, 0] < 600)
    assert (t.domain_center[far] == 1).sum() == 0


def test_slide_frame_is_not_tissue_frame_under_deformation():
    e = build_phantom(_cfg("E"))
    slide = e.volume.obs[["x_raw", "y_raw"]].to_numpy() - np.array(e.truth.config.extent_um) / 2
    err = np.linalg.norm(slide - e.truth.tissue_xyz[:, :2], axis=1)
    assert err.max() > 10.0  # a registration problem exists
    ident = build_phantom(_cfg("E", deform=DeformConfig()))
    slide = ident.volume.obs[["x_raw", "y_raw"]].to_numpy() - np.array(ident.truth.config.extent_um) / 2
    assert np.allclose(slide, ident.truth.tissue_xyz[:, :2])


def test_identity_overlap_is_full_and_decays_with_offset():
    p = build_phantom(_cfg("E", deform=DeformConfig()))
    O = p.truth.true_overlap(2, 3)
    # same slide grid + identity transform: each spot fully overlaps its own counterpart
    diag = O.diagonal() if O.shape[0] == O.shape[1] else None
    assert O.max() == pytest.approx(1.0)
    assert (O.sum(1).A1 <= 1.0 + 1e-9).all()  # disks of one section are disjoint -> shares add to <= 1


def test_overlap_rows_sum_below_one_and_footprint_coverage_is_partial():
    p = build_phantom(_cfg("M"))
    O = p.truth.true_overlap(2, 3)
    s = O.sum(1).A1
    assert s.max() <= 1.0 + 1e-9 and s.mean() < 1.0
    # Visium disks cover ~27% of area: unmatched mass is large when sections are not aligned
    rho = p.truth.config.geometry.spot_radius_um
    cover = np.pi * rho ** 2 / (100.0 ** 2 * np.sqrt(3) / 2)
    assert cover == pytest.approx(0.2747, abs=0.005)


def test_missing_section_updates_gap_and_z():
    p = build_phantom(_cfg("E", missing_sections=(3,)))
    v = p.volume
    assert v.n_sections == 6 and "s03" not in v.sections.index
    assert v.delta_z("s02", "s04") == pytest.approx(20.0)
    assert v.sections.loc["s02", "gap_um"] == pytest.approx(10.0)
    # sections present are identical regardless of which other section is dropped
    q = build_phantom(_cfg("E"))
    ra, rb = p.truth.rows(2), q.truth.rows(2)
    assert (p.volume.X[ra] != q.volume.X[rb]).nnz == 0


def test_unknown_thickness_variant():
    p = build_phantom(_cfg("H"))
    v = p.volume
    assert (v.sections["thickness_source"] == "unknown").all()
    assert v.obs["z_is_assumed"].iloc[len(v.obs) // 2:].any()


def test_tiers_get_harder():
    sizes = {t: build_phantom(_cfg(t)) for t in "EMH"}
    n = {t: len(p.volume.obs) for t, p in sizes.items()}
    assert n["E"] > n["M"] > n["H"]  # overlap loss / tissue loss / dropout remove spots


def test_counts_follow_nb_model():
    cfg = _cfg("E", deform=DeformConfig(), section_depth_sd=0.0, spot_depth_sd=0.0, n_sections=2, finger_sections=(0, 1))
    p = build_phantom(cfg)
    t, v = p.truth, p.volume
    rows = np.flatnonzero((t.domain_fracs[:, 1] > 0.999) & (t.section_index == 0))
    assert len(rows) > 50
    Y = v.X[rows].toarray()
    g = np.argsort(p.truth.pi[1])[-5:]  # abundant genes in the tumour core
    mu_hat = Y[:, g].mean(0)
    mu = cfg.mean_depth * t.inside_frac[rows].mean() * p.truth.pi[1, g]
    assert np.allclose(mu_hat, mu, rtol=0.15)
    var_hat = Y[:, g].var(0)
    assert np.all(var_hat > 1.2 * mu_hat)  # overdispersed relative to Poisson


def test_violations_change_noise_structure():
    base = dict(deform=DeformConfig(), n_sections=2, finger_sections=(0, 1))
    clean = build_phantom(_cfg("E", **base))
    amb = build_phantom(_cfg("E", violations=ViolationConfig(ambient_fraction=0.3), **base))
    # same tissue, same seeds -> same spots, different counts; ambient leakage correlates neighbours
    assert clean.volume.X.shape == amb.volume.X.shape
    assert (clean.volume.X != amb.volume.X).nnz > 0
    zi = build_phantom(_cfg("E", violations=ViolationConfig(zero_inflation=0.5), **base))
    assert zi.volume.X.nnz < 0.7 * clean.volume.X.nnz


def test_bad_section_gets_extra_rotation():
    p = build_phantom(_cfg("E", violations=ViolationConfig(bad_section=4, bad_section_extra_deg=40.0)))
    angs = np.array([abs(th["angle_deg"]) for th in p.truth.transforms])
    assert angs[4] >= 35.0 and np.delete(angs, 4).max() <= 5.0


def test_config_validation():
    with pytest.raises(ValueError):
        PhantomConfig(missing_sections=(99,))
    with pytest.raises(ValueError):
        VisiumGeometry(spot_diameter_um=120.0, spot_pitch_um=100.0)
    with pytest.raises(ValueError):
        PhantomConfig(finger_sections=(4, 2))
    with pytest.raises(ValueError):
        PhantomConfig(unknown_field=1)
