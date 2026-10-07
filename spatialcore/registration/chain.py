"""Pairwise registrations -> global poses with accumulated uncertainty, and the VolumeSet-level driver.

Convention: for each physically adjacent pair (upper a, lower b) the transform maps b's coordinates into a's frame.
The first section (physical order 0) is the reference frame. Pose of section k = pose(k-1) o T(k->k-1).
Accumulated position variance is the plain sum of per-pair variances (independent-error assumption, spec E.1);
``tests`` measure how well that holds on the phantom, and it is reported, not assumed correct.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from spatialcore.config import QCConfig, RegistrationConfig
from spatialcore.data.volume import VolumeSet
from spatialcore.preprocessing import joint_pca_features
from spatialcore.qc import PairQC, pairwise_qc, spatial_coherence
from .confidence import raw_confidence
from .soft_correspondence import EMResult, em_register, register_points, row_posterior
from .transform import Transform

_STATUS_RANK = {"PASS": 0, "WARNING": 1, "FAIL": 2}


@dataclass
class PairResult:
    upper: str
    lower: str
    transform: Transform              # lower -> upper frame
    em: EMResult
    qc: PairQC
    sigma_pos_um: float               # rms position uncertainty (per coordinate): statistical + deformation term
    deformation_um: float             # rms displacement between the rigid and the affine fit (model-misfit diagnostic)
    conf_lower: np.ndarray            # raw confidence per lower-section spot
    conf_upper: np.ndarray            # raw confidence per upper-section spot
    p_null_lower: np.ndarray
    p_null_upper: np.ndarray

    def to_dict(self) -> dict:
        return {"upper": self.upper, "lower": self.lower, "transform": self.transform.to_dict(),
                "sigma_match_um": float(np.sqrt(self.em.sigma2)), "sigma_pos_um": self.sigma_pos_um,
                "deformation_um": self.deformation_um,
                "n_eff": self.em.n_eff, "converged": self.em.converged, "n_iter": self.em.n_iter,
                "model": self.em.model, "qc": self.qc.to_dict()}


def position_variance(em: EMResult, x: np.ndarray) -> np.ndarray:
    """Per-coordinate variance of T(x) implied by the M-step covariance (Laplace-style, effective-N optimistic)."""
    xh = np.column_stack([x, np.ones(len(x))])
    return np.einsum("ni,ij,nj->n", xh, em.cov_unit, xh)


def register_pair(Xu, Xl, xy_u, xy_l, cfg: RegistrationConfig, qc_cfg: QCConfig, names: tuple[str, str] = ("u", "l")) -> PairResult:
    Fu, Fl = joint_pca_features(Xu, Xl, cfg.n_pcs, cfg.n_hvg)
    em = register_points(xy_l, xy_u, Fl, Fu, cfg)
    T = em.transform
    reg_l = T.apply(xy_l)
    # row_posterior needs both point sets in one frame: lower spots are compared in the upper frame
    # confidence/QC use a match scale of at least ~half a pitch: at the fitted sigma (floor = lattice quantisation)
    # only the nearest spot has mass and 'expression gain' would be zero by construction
    s2 = max(em.sigma2, qc_cfg.eval_sigma_um ** 2)
    pn_l, ag_l = row_posterior(reg_l, xy_u, Fl, Fu, s2, cfg)
    _, ag0_l = row_posterior(reg_l, xy_u, Fl, Fu, s2, cfg, lam=0.0)
    pn_u, ag_u = row_posterior(xy_u, reg_l, Fu, Fl, s2, cfg)
    coh = min(spatial_coherence(xy_u, Fu, qc_cfg.coherence_k), spatial_coherence(xy_l, Fl, qc_cfg.coherence_k))
    # statistical (Laplace-style) variance is only valid if the transform model holds; the rigid-vs-affine
    # disagreement measures how far it does not (phantom: Spearman 0.83 with the true error), so it is added
    aff = em_register(xy_l, xy_u, Fl, Fu, T, cfg, "affine", cfg.polish_iter) if em.model != "affine" else em
    deform = float(np.sqrt(((T.apply(xy_l) - aff.transform.apply(xy_l)) ** 2).sum(1).mean()))
    qc = pairwise_qc(T, pn_l, ag_l, ag0_l, qc_cfg, coh, deform)
    sig = float(np.sqrt(np.mean(position_variance(em, xy_l)) + (cfg.deformation_kappa * deform) ** 2))
    return PairResult(names[0], names[1], T, em, qc, sig, deform, raw_confidence(pn_l, ag_l), raw_confidence(pn_u, ag_u), pn_l, pn_u)


@dataclass
class RegistrationReport:
    pairs: list[PairResult]
    poses: dict[str, Transform]
    sigma_reg_um: dict[str, float]      # accumulated rms position uncertainty per section (reference = 0)
    status: dict[str, str]              # worst adjacent-pair QC status per section
    config: dict = field(default_factory=dict)


def chain_poses(pairs: list[PairResult], order: list[str]) -> tuple[dict[str, Transform], dict[str, float]]:
    poses = {order[0]: Transform.identity()}
    var = {order[0]: 0.0}
    by_lower = {p.lower: p for p in pairs}
    for k in range(1, len(order)):
        p = by_lower[order[k]]
        poses[order[k]] = poses[p.upper].compose(p.transform)
        var[order[k]] = var[p.upper] + p.sigma_pos_um ** 2
    return poses, {k: float(np.sqrt(v)) for k, v in var.items()}


def register_volume(vs: VolumeSet, cfg: RegistrationConfig | None = None, qc_cfg: QCConfig | None = None) -> RegistrationReport:
    """Register every physically adjacent pair, chain to the first section, and write results into ``vs``.

    Adds to ``vs.obs``: x_registered, y_registered, registration_confidence (min over adjacent pairs, raw),
    overlap_up / overlap_down (1 - p_null towards the upper / lower neighbour; NaN at the series ends).
    ``vs.registrations[(upper, lower)]`` holds the serialisable pair record; ``vs.sections`` gets sigma_reg_um and qc_status.
    """
    cfg, qc_cfg = cfg or RegistrationConfig(), qc_cfg or QCConfig()
    order = vs.ordered_section_ids
    xy = vs.obs[["x_raw", "y_raw"]].to_numpy()
    pairs = []
    for a, b in zip(order[:-1], order[1:]):
        ra, rb = vs.rows(a), vs.rows(b)
        pairs.append(register_pair(vs.X[ra], vs.X[rb], xy[ra], xy[rb], cfg, qc_cfg, (a, b)))
    poses, sigma = chain_poses(pairs, order) if pairs else ({order[0]: Transform.identity()}, {order[0]: 0.0})

    reg = np.empty_like(xy)
    conf = np.full(len(xy), np.nan)
    up, down = np.full(len(xy), np.nan), np.full(len(xy), np.nan)
    for sid in order:
        r = vs.rows(sid)
        reg[r] = poses[sid].apply(xy[r])
    for p in pairs:
        ru, rl = vs.rows(p.upper), vs.rows(p.lower)
        conf[rl] = np.fmin(conf[rl], p.conf_lower)
        conf[ru] = np.fmin(conf[ru], p.conf_upper)
        up[rl] = 1.0 - p.p_null_lower
        down[ru] = 1.0 - p.p_null_upper
        vs.registrations[(p.upper, p.lower)] = p.to_dict()
    vs.obs["x_registered"], vs.obs["y_registered"] = reg[:, 0], reg[:, 1]
    vs.obs["registration_confidence"] = conf
    vs.obs["overlap_up"], vs.obs["overlap_down"] = up, down
    vs.obsm["spatial_registered"] = reg

    status = {sid: "PASS" for sid in order}
    for p in pairs:
        for sid in (p.upper, p.lower):
            if _STATUS_RANK[p.qc.status] > _STATUS_RANK[status[sid]]:
                status[sid] = p.qc.status
    vs.sections["sigma_reg_um"] = pd_series(sigma, vs.sections.index)
    vs.sections["qc_status"] = pd_series(status, vs.sections.index)
    return RegistrationReport(pairs, poses, sigma, status, {"registration": cfg.model_dump(), "qc": qc_cfg.model_dump()})


def pd_series(d: dict, index):
    import pandas as pd

    return pd.Series(d).reindex(index)
