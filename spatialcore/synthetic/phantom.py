"""Synthetic serial-section phantom with an explicit forward model and complete ground truth.

Forward model (docs/ZBRIDGE_PHANTOM_AND_DATA.md 1):
    tissue (6 analytic domains) --slide transform + non-rigid--> Visium grid
    spot expectation = depth * sum_d frac_d * pi_d,  frac_d = share of the disk x thickness volume in domain d
    counts ~ NB(mu, r) with independent noise per section.
Family-A phantoms satisfy the algorithm's assumptions; ``ViolationConfig`` breaks them on purpose (family B).
A phantom is an engineering check, never evidence of biological performance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.spatial import cKDTree

from spatialcore.config import PhantomConfig
from spatialcore.data.volume import SectionMeta, VolumeSet
from .geometry import disk_lens_area, disk_quadrature, hex_grid

DOMAIN_NAMES = ("normal", "tumor_core", "immune_shell", "vessel", "finger", "slab")
_TUMOR_TILT_RAD = np.deg2rad(15.0)
_VESSEL_XY0 = (-600.0, 300.0)
_FINGER_Y0, _FINGER_X0, _FINGER_X1 = -400.0, 900.0, 1700.0
_PROGRAMS_PER_DOMAIN = 3
_BASE_LOG_SD = 1.2
_MIN_INSIDE_FRAC = 0.5
_AREA_MC_POINTS = 20000


def _rot(deg: float) -> np.ndarray:
    a = np.deg2rad(deg)
    return np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])


@dataclass
class PhantomTruth:
    config: PhantomConfig
    domain_names: tuple[str, ...]
    section_ids: list[str]             # present sections, physical order
    section_index: np.ndarray          # per spot: physical index k in [0, n_sections)
    z_true_um: np.ndarray              # per physical index (also for missing sections)
    transforms: list[dict]             # per physical index: A (2x2), t (2,), nonrigid params, angle_deg
    tissue_xyz: np.ndarray             # per spot: true (x, y, z) in the tissue frame, um
    domain_center: np.ndarray          # per spot: domain label at the disk centre
    domain_fracs: np.ndarray           # per spot: (n, D) fraction of tissue volume in the footprint per domain
    inside_frac: np.ndarray            # per spot: share of footprint volume that contains tissue
    is_boundary: np.ndarray            # per spot: dominant domain share < 0.9
    base_log_mean: np.ndarray         # (G,) per-gene baseline log expression, kept for audit
    pi: np.ndarray                     # (D, G) domain expression proportions
    _row_slices: dict[int, slice] = field(default_factory=dict, repr=False)

    def rows(self, k: int) -> np.ndarray:
        return np.flatnonzero(self.section_index == k)

    def true_overlap(self, k_a: int, k_b: int) -> sp.csr_matrix:
        """Footprint overlap (share of one disk's area) between spots of two sections, from true tissue positions.

        Uses the equal-disk lens area at the tissue-frame distance (ignores scale/shear distortion of the
        footprint, which is <= a few percent in the supported tiers). Rows index spots of k_a, columns of k_b.
        """
        ra, rb = self.rows(k_a), self.rows(k_b)
        rho = self.config.geometry.spot_radius_um
        pa, pb = self.tissue_xyz[ra, :2], self.tissue_xyz[rb, :2]
        tree = cKDTree(pb)
        pairs = tree.query_ball_point(pa, r=2 * rho)
        data, ri, ci = [], [], []
        for i, js in enumerate(pairs):
            if not js:
                continue
            d = np.linalg.norm(pb[js] - pa[i], axis=1)
            w = disk_lens_area(d, rho) / (np.pi * rho * rho)
            data.extend(w), ri.extend([i] * len(js)), ci.extend(js)
        return sp.csr_matrix((data, (ri, ci)), shape=(len(ra), len(rb)))

    def reference_xy(self, ref_k: int | None = None) -> np.ndarray:
        """Where each spot *should* land in the slide frame (um, same origin as ``x_raw``) of reference section ``ref_k``
        (default: the first present section). Uses the reference section's affine part; its non-rigid field is ignored."""
        k = int(self.section_index.min()) if ref_k is None else ref_k
        th = self.transforms[k]
        return self.tissue_xyz[:, :2] @ th["A"].T + th["t"] + np.array(self.config.extent_um) / 2.0

    def true_registration_error(self, k: int, est_slide_to_tissue_xy: np.ndarray) -> np.ndarray:
        """Per-spot error (um) of an estimated slide->tissue xy map evaluated at that section's spots."""
        return np.linalg.norm(est_slide_to_tissue_xy - self.tissue_xyz[self.rows(k), :2], axis=1)


@dataclass
class Phantom:
    volume: VolumeSet
    truth: PhantomTruth


class _Domains:
    """Analytic domain labels in the tissue frame (points are (n, 3) in um, centred)."""

    def __init__(self, cfg: PhantomConfig, z_pitch: float, boundary_mult: float):
        self.cfg, self.zp, self.mult = cfg, z_pitch, boundary_mult
        self.R = _rot(np.rad2deg(_TUMOR_TILT_RAD))

    def labels(self, p: np.ndarray) -> np.ndarray:
        c = self.cfg
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        k = z / self.zp if self.zp > 0 else np.zeros_like(z)  # continuous section index (relative)
        a, b, cz = c.tumor_semi_axes_um
        xr, yr = (self.R.T @ p[:, :2].T)
        core = (xr / a) ** 2 + (yr / b) ** 2 + (z / cz) ** 2 <= 1.0
        s, sz = c.immune_shell_um, c.immune_shell_z_um
        outer = (xr / (a + s)) ** 2 + (yr / (b + s)) ** 2 + (z / (cz + sz)) ** 2 <= 1.0
        edge = c.slab_x_um - c.slab_slide_um_per_section * self.mult * k
        lab = np.zeros(len(p), int)
        lab[x > edge] = 5
        lab[outer] = 2
        lab[core] = 1
        vx = _VESSEL_XY0[0] + c.vessel_shift_um_per_section * k
        lab[(x - vx) ** 2 + (y - _VESSEL_XY0[1]) ** 2 <= c.vessel_radius_um ** 2] = 3
        k0, k1 = c.finger_sections
        zlo, zhi = (k0 - 0.5) * self.zp - self._zc(), (k1 + 0.5) * self.zp - self._zc()
        in_finger = (
            (x >= _FINGER_X0) & (x <= _FINGER_X1) & (np.abs(y - _FINGER_Y0) <= c.finger_width_um / 2)
            & (z >= zlo) & (z <= zhi)
        )
        lab[in_finger] = 4
        return lab

    def _zc(self) -> float:
        return (self.cfg.n_sections - 1) / 2.0 * self.zp


def _present(p_xy: np.ndarray, tissue_ab, crop, blob, tear) -> np.ndarray:
    a, b = tissue_ab
    ok = (p_xy[:, 0] / a) ** 2 + (p_xy[:, 1] / b) ** 2 <= 1.0
    if crop is not None:
        u, thr = crop
        ok &= p_xy @ u <= thr
    if blob is not None:
        c, r = blob
        ok &= np.linalg.norm(p_xy - c, axis=1) > r
    if tear is not None:
        u, c0, w = tear
        ok &= np.abs(p_xy @ u - c0) > w / 2
    return ok


def _draw_transform(rng, cfg: PhantomConfig, extra_deg: float) -> dict:
    d, pitch = cfg.deform, cfg.geometry.spot_pitch_um
    ang = rng.uniform(-d.rotation_deg, d.rotation_deg) + extra_deg
    sc = 1.0 + rng.uniform(-d.scale_dev, d.scale_dev)
    sh = rng.uniform(-d.shear, d.shear)
    t = rng.uniform(-d.translation_pitch, d.translation_pitch, 2) * pitch
    A = _rot(ang) @ np.array([[1.0, sh], [0.0, 1.0]]) * sc
    nr = None
    if d.nonrigid_amp_um > 0:
        m = 24
        nr = {
            "w": rng.normal(0.0, 1.0 / d.nonrigid_length_um, (m, 2)),
            "phi": rng.uniform(0, 2 * np.pi, m),
            "coef": rng.normal(0.0, d.nonrigid_amp_um * np.sqrt(2.0 / m), (m, 2)),
        }
    return {"angle_deg": float(ang), "scale": float(sc), "shear": float(sh), "t": t, "A": A, "nonrigid": nr}


def _slide_to_tissue(th: dict, s: np.ndarray) -> np.ndarray:
    x = (s - th["t"]) @ np.linalg.inv(th["A"]).T
    nr = th["nonrigid"]
    if nr is not None:
        x = x + np.cos(x @ nr["w"].T + nr["phi"]) @ nr["coef"]
    return x


def build_phantom(cfg: PhantomConfig) -> Phantom:
    cfg_seq = np.random.SeedSequence(cfg.seed)
    prog_ss, *sec_ss = cfg_seq.spawn(1 + cfg.n_sections)
    K, G, D, rho = cfg.n_sections, cfg.n_genes, len(DOMAIN_NAMES), cfg.geometry.spot_radius_um

    # --- expression structure (shared by all sections) -----------------------------------------------
    prng = np.random.default_rng(prog_ss)
    base = prng.normal(0.0, _BASE_LOG_SD, G)
    n_up = max(1, int(round(cfg.program_fraction * G)))
    member = np.zeros((cfg.n_programs, G))
    for p in range(cfg.n_programs):
        member[p, prng.choice(G, n_up, replace=False)] = 1.0
    W = np.zeros((D, cfg.n_programs))
    for d in range(D):
        ids = [(_PROGRAMS_PER_DOMAIN * d + j) % cfg.n_programs for j in range(_PROGRAMS_PER_DOMAIN)]
        W[d, ids] = prng.dirichlet(np.ones(_PROGRAMS_PER_DOMAIN))
    logits = base + cfg.program_logfc * (W @ member)
    pi = np.exp(logits - logits.max(1, keepdims=True))
    pi /= pi.sum(1, keepdims=True)

    # smooth within-domain programs: slowly varying in x, y and (more slowly) z, shared by neighbouring sections
    S = cfg.smooth_programs
    smooth = None
    if S > 0 and cfg.smooth_amp > 0:
        m_rff = 32
        smember = np.zeros((S, G))
        for q in range(S):
            smember[q, prng.choice(G, n_up, replace=False)] = 1.0
        scale = np.array([cfg.smooth_length_um, cfg.smooth_length_um, cfg.smooth_length_z_um])
        smooth = {
            "w": prng.normal(0.0, 1.0, (m_rff, 3)) / scale,
            "phi": prng.uniform(0, 2 * np.pi, m_rff),
            "coef": prng.normal(0.0, cfg.smooth_amp * np.sqrt(2.0 / m_rff), (m_rff, S)),
            "member": smember,
        }

    z_pitch = cfg.thickness_um + cfg.gap_um
    z_true = (np.arange(K) - (K - 1) / 2.0) * z_pitch
    doms = _Domains(cfg, z_pitch, cfg.violations.boundary_slide_multiplier)
    slide = hex_grid(cfg.extent_um, cfg.geometry.spot_pitch_um)
    quad = disk_quadrature(rho, cfg.quad_disk_rings)
    zq = (np.linspace(-0.5, 0.5, cfg.quad_z + 2)[1:-1] * cfg.thickness_um) if cfg.quad_z > 1 else np.zeros(1)
    nq, nz = len(quad), len(zq)
    tissue_ab = cfg.tissue_semi_axes_um
    area_pts = np.random.default_rng(0).uniform(-1, 1, (_AREA_MC_POINTS, 2)) * np.array(tissue_ab)
    area_pts = area_pts[(area_pts[:, 0] / tissue_ab[0]) ** 2 + (area_pts[:, 1] / tissue_ab[1]) ** 2 <= 1]

    present_ids = [k for k in range(K) if k not in set(cfg.missing_sections)]
    Xs, obs_parts = [], []
    tr = {n: [] for n in ("sec", "xyz", "dom", "fr", "inside", "bnd")}
    transforms: list[dict] = []
    for k in range(K):
        srng = np.random.default_rng(sec_ss[k])
        r_def, r_cnt, r_drop, r_geo = [np.random.default_rng(s) for s in sec_ss[k].spawn(4)]
        extra = 0.0
        if cfg.violations.bad_section == k:
            extra = cfg.violations.bad_section_extra_deg * (1 if r_def.random() < 0.5 else -1)
        th = _draw_transform(r_def, cfg, extra)
        transforms.append(th)
        d = cfg.deform
        crop = blob = tear = None
        if d.overlap_fraction < 1.0:
            ang = r_geo.uniform(0, 2 * np.pi)
            u = np.array([np.cos(ang), np.sin(ang)])
            crop = (u, float(np.quantile(area_pts @ u, d.overlap_fraction)))
        if d.tissue_loss_fraction > 0:
            c = area_pts[r_geo.integers(len(area_pts))]
            blob = (c, float(np.sqrt(d.tissue_loss_fraction * tissue_ab[0] * tissue_ab[1])))
        if d.tear:
            ang = r_geo.uniform(0, np.pi)
            u = np.array([np.cos(ang), np.sin(ang)])
            tear = (u, float(r_geo.uniform(-0.3, 0.3) * tissue_ab[1]), d.tear_width_um)
        if k not in present_ids:
            continue

        n = len(slide)
        ctr = _slide_to_tissue(th, slide)
        qpts = (slide[:, None, :] + quad[None, :, :]).reshape(-1, 2)
        qt = _slide_to_tissue(th, qpts).reshape(n, nq, 2)
        p3 = np.empty((n, nq, nz, 3))
        p3[..., :2] = qt[:, :, None, :]
        p3[..., 2] = (z_true[k] + zq)[None, None, :]
        flat = p3.reshape(-1, 3)
        lab = doms.labels(flat).reshape(n, nq * nz)
        pres = _present(flat[:, :2], tissue_ab, crop, blob, tear).reshape(n, nq * nz)
        fr = np.stack([((lab == j) & pres).mean(1) for j in range(D)], axis=1)
        inside = fr.sum(1)
        ctr3 = np.column_stack([ctr, np.full(n, z_true[k])])
        dom_c = doms.labels(ctr3)
        keep = _present(ctr, tissue_ab, crop, blob, tear) & (inside > _MIN_INSIDE_FRAC)
        if d.spot_dropout > 0:
            keep &= r_drop.random(n) >= d.spot_dropout
        idx = np.flatnonzero(keep)
        m = len(idx)
        frk = fr[idx]
        dom_share = frk.max(1) / np.maximum(inside[idx], 1e-12)

        sec_depth = np.exp(srng.normal(-cfg.section_depth_sd ** 2 / 2, cfg.section_depth_sd))
        depth = cfg.mean_depth * sec_depth * np.exp(r_cnt.normal(-cfg.spot_depth_sd ** 2 / 2, cfg.spot_depth_sd, m))
        prof = frk @ pi
        if smooth is not None:
            f = np.cos(ctr3[idx] @ smooth["w"].T + smooth["phi"]) @ smooth["coef"]  # (m, S)
            tot0 = prof.sum(1, keepdims=True)
            prof = prof * np.exp(f @ smooth["member"])
            prof *= tot0 / np.maximum(prof.sum(1, keepdims=True), 1e-300)
        if cfg.violations.batch_gene_sd > 0:
            prof = prof * np.exp(srng.normal(0, cfg.violations.batch_gene_sd, G))[None, :]
        mu = depth[:, None] * prof
        r = cfg.nb_dispersion
        lam = r_cnt.gamma(r, mu / r + 1e-12)
        Y = r_cnt.poisson(lam).astype(np.float64)
        if cfg.violations.ambient_fraction > 0:
            a = cfg.violations.ambient_fraction
            tree = cKDTree(slide[idx])
            nb = tree.query_ball_point(slide[idx], r=1.6 * cfg.geometry.spot_pitch_um)
            amb = np.vstack([Y[[j for j in js if j != i]].mean(0) if len(js) > 1 else np.zeros(G)
                             for i, js in enumerate(nb)])
            Y = r_cnt.binomial(Y.astype(int), 1 - a) + r_cnt.poisson(a * amb)
        if cfg.violations.zero_inflation > 0:
            Y = Y * (r_cnt.random(Y.shape) >= cfg.violations.zero_inflation)
        Xs.append(sp.csr_matrix(Y))

        sid = f"s{k:02d}"
        xy = slide[idx] + np.array(cfg.extent_um) / 2.0
        obs_parts.append(pd.DataFrame(
            {"section_id": sid, "sample_id": "phantom", "x_raw": xy[:, 0], "y_raw": xy[:, 1],
             "in_tissue": True, "n_counts": Y.sum(1), "n_genes": (Y > 0).sum(1)},
            index=[f"{sid}:{i}" for i in idx],
        ))
        tr["sec"].append(np.full(m, k)), tr["xyz"].append(ctr3[idx]), tr["dom"].append(dom_c[idx])
        tr["fr"].append(frk / np.maximum(inside[idx], 1e-12)[:, None]), tr["inside"].append(inside[idx])
        tr["bnd"].append(dom_share < 0.9)

    metas = []
    for pos, k in enumerate(present_ids):
        nxt = present_ids[pos + 1] if pos + 1 < len(present_ids) else K
        skipped = nxt - k - 1
        known = cfg.thickness_known
        gap = cfg.gap_um + skipped * z_pitch
        metas.append(SectionMeta(
            section_id=f"s{k:02d}", order=pos, sample_id="phantom",
            thickness_um=cfg.thickness_um if known else None, thickness_source="nominal" if known else "unknown",
            gap_um=gap if known else None, gap_source="nominal" if known else "unknown",
            spot_diameter_um=cfg.geometry.spot_diameter_um, spot_pitch_um=cfg.geometry.spot_pitch_um,
        ))
    names = [f"g{i:04d}" for i in range(G)]
    vol = VolumeSet.from_parts(sp.vstack(Xs).tocsr(), pd.concat(obs_parts), names, metas)
    cat = lambda key: np.concatenate(tr[key]) if key != "xyz" and key != "fr" else np.vstack(tr[key])
    truth = PhantomTruth(
        config=cfg, domain_names=DOMAIN_NAMES, section_ids=[m.section_id for m in metas],
        section_index=cat("sec"), z_true_um=z_true, transforms=transforms, tissue_xyz=cat("xyz"),
        domain_center=cat("dom"), domain_fracs=cat("fr"), inside_frac=cat("inside"), is_boundary=cat("bnd"),
        base_log_mean=base, pi=pi,
    )
    return Phantom(volume=vol, truth=truth)
