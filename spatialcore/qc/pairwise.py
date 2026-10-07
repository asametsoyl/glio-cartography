"""Pairwise registration QC -> PASS / WARNING / FAIL with the metrics that decided it (thresholds: QCConfig)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from spatialcore.config import QCConfig

if TYPE_CHECKING:  # avoid a runtime cycle: registration.chain imports this module
    from spatialcore.registration.transform import Transform

_NULL_THRESHOLD = 0.5  # a spot counts as having a counterpart when p_null < this


@dataclass(frozen=True)
class PairQC:
    status: str
    overlap: float
    expr_gain: float
    scale_dev: float
    shear: float
    coherence: float
    deformation_um: float
    angle_deg: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {**self.__dict__, "reasons": list(self.reasons)}


def spatial_coherence(xy: np.ndarray, F: np.ndarray, k: int, seed: int = 0) -> float:
    """Mean cosine to the k nearest spatial neighbours minus mean cosine to random spots (unit-norm features).

    ~0 for a section whose spots carry no spatial structure (scrambled barcodes, wrong matrix order); clearly
    positive for tissue. It is a property of one section, independent of any registration.
    """
    from scipy.spatial import cKDTree

    k = min(k, len(xy) - 1)
    idx = cKDTree(xy).query(xy, k=k + 1)[1][:, 1:]
    near = np.einsum("nd,nkd->nk", F, F[idx]).mean()
    rnd = np.random.default_rng(seed).integers(len(F), size=(len(F), k))
    far = np.einsum("nd,nkd->nk", F, F[rnd]).mean()
    return float(near - far)


def pairwise_qc(transform: Transform, p_null: np.ndarray, agreement: np.ndarray, agreement_geom: np.ndarray,
                cfg: QCConfig, coherence: float = 1.0, deformation_um: float = 0.0) -> PairQC:
    """``expr_gain`` = mean(agreement - geometry-only agreement) over spots that have a counterpart.

    It is ~0 when expression carries no information about which spot matches which, i.e. when only geometry
    holds the alignment together; that is the signature of a section from another tissue or with scrambled spots.
    """
    d = transform.decompose()
    has = p_null < _NULL_THRESHOLD
    overlap = float(np.mean(1.0 - p_null))
    gain = float(np.mean((agreement - agreement_geom)[has])) if has.any() else 0.0
    scale_dev, shear = abs(d["scale"] - 1.0), abs(d["shear"])
    reasons, level = [], 0
    for name, val, warn, fail, low_bad in [
        ("overlap", overlap, cfg.min_overlap_warn, cfg.min_overlap_fail, True),
        ("expr_gain", gain, cfg.min_expr_gain_warn, cfg.min_expr_gain_fail, True),
        ("coherence", coherence, cfg.min_coherence_warn, cfg.min_coherence_fail, True),
        ("deformation_um", deformation_um, cfg.max_deformation_warn_um, cfg.max_deformation_fail_um, False),
        ("scale_dev", scale_dev, cfg.max_scale_dev_warn, cfg.max_scale_dev_fail, False),
        ("shear", shear, cfg.max_shear_warn, cfg.max_shear_fail, False),
    ]:
        bad_fail = val < fail if low_bad else val > fail
        bad_warn = val < warn if low_bad else val > warn
        if bad_fail:
            level = max(level, 2)
            reasons.append(f"{name}={val:.3f} beyond FAIL limit {fail}")
        elif bad_warn:
            level = max(level, 1)
            reasons.append(f"{name}={val:.3f} beyond WARNING limit {warn}")
    return PairQC(("PASS", "WARNING", "FAIL")[level], overlap, gain, scale_dev, shear, coherence, deformation_um, d["angle_deg"], tuple(reasons))
