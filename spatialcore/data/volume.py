"""Multi-section data model. A single section is a VolumeSet with n_sections == 1 (no separate code path).

Z rule (docs/ZBRIDGE_DESIGN.md D.2):  z_um(k) = sum_{r<k} (thickness_r + gap_r), in *physical* order.
If any contributing term is unknown, ``z_um`` is NaN and ``z_um_assumed`` is filled from ``ZAssumptions``;
``z_source`` says which one a consumer got. Assumed values must be labelled as assumed in every output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
import scipy.sparse as sp

from spatialcore.config import ZAssumptions

Source = Literal["measured", "nominal", "unknown"]
_KNOWN: tuple[str, ...] = ("measured", "nominal")
SECTION_COLUMNS = (
    "section_id", "sample_id", "order", "thickness_um", "thickness_source", "gap_um", "gap_source",
    "orientation_flip", "platform", "spot_diameter_um", "spot_pitch_um", "qc_status", "checksum_sha256",
)
OBS_REQUIRED = ("section_id", "x_raw", "y_raw")
# Section identity must never enter a feature matrix (docs/ZBRIDGE_DESIGN.md E.7).
FORBIDDEN_OBSM_NAMES = ("section", "batch", "z_um", "order")


class VolumeValidationError(ValueError):
    """The VolumeSet is internally inconsistent; the message says which invariant failed."""


@dataclass(frozen=True)
class SectionMeta:
    section_id: str
    order: int
    sample_id: str = "sample"
    thickness_um: float | None = None
    thickness_source: Source = "unknown"
    gap_um: float | None = None
    gap_source: Source = "unknown"
    orientation_flip: bool = False
    platform: str = "visium"
    spot_diameter_um: float = 55.0
    spot_pitch_um: float = 100.0
    qc_status: Literal["PASS", "WARNING", "FAIL", "UNCHECKED"] = "UNCHECKED"
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        for name in ("thickness", "gap"):
            val, src = getattr(self, f"{name}_um"), getattr(self, f"{name}_source")
            if (val is None) != (src == "unknown"):
                raise VolumeValidationError(
                    f"{self.section_id}: {name}_um is {val!r} but {name}_source is {src!r}; "
                    "unknown <-> None must agree"
                )
            if val is not None and val < 0:
                raise VolumeValidationError(f"{self.section_id}: {name}_um must be >= 0")


def compute_z(sections: pd.DataFrame, assume: ZAssumptions | None = None) -> pd.DataFrame:
    """Return per-section z columns indexed like ``sections`` (sorted by physical ``order``).

    Columns: ``z_um`` (NaN unless every term below is measured/nominal), ``z_um_assumed`` (always finite),
    ``z_source`` in {"measured","assumed"}. The last section's own thickness/gap do not enter any z.
    """
    assume = assume or ZAssumptions()
    s = sections.sort_values("order")
    t_known = s["thickness_source"].isin(_KNOWN).to_numpy()
    g_known = s["gap_source"].isin(_KNOWN).to_numpy()
    t = np.where(t_known, s["thickness_um"].astype(float).fillna(0.0), assume.assumed_thickness_um)
    g = np.where(g_known, s["gap_um"].astype(float).fillna(0.0), assume.assumed_gap_um)
    step = t + g
    z_assumed = np.concatenate([[0.0], np.cumsum(step)[:-1]])
    all_known = (t_known & g_known)
    known_prefix = np.concatenate([[True], np.cumprod(all_known)[:-1].astype(bool)])
    z = np.where(known_prefix, z_assumed, np.nan)
    out = pd.DataFrame(
        {"z_um": z, "z_um_assumed": z_assumed, "z_source": np.where(known_prefix, "measured", "assumed")},
        index=s.index,
    )
    return out.loc[sections.index]


@dataclass
class VolumeSet:
    """Counts + per-spot table + per-section table (+ optional registrations). Row order of X == obs."""

    X: sp.csr_matrix
    obs: pd.DataFrame
    var_names: list[str]
    sections: pd.DataFrame
    registrations: dict[tuple[str, str], dict] = field(default_factory=dict)
    obsm: dict[str, np.ndarray] = field(default_factory=dict)
    uns: dict = field(default_factory=dict)

    # ---- construction -------------------------------------------------------------------
    @classmethod
    def from_parts(
        cls, X, obs: pd.DataFrame, var_names, metas: list[SectionMeta],
        assume: ZAssumptions | None = None, obsm: dict[str, np.ndarray] | None = None, uns: dict | None = None,
    ) -> "VolumeSet":
        sections = pd.DataFrame([m.__dict__ for m in metas]).set_index("section_id", drop=False)
        sections = sections[list(SECTION_COLUMNS)]
        z = compute_z(sections, assume)
        sections = sections.join(z)
        obs = obs.copy()
        if not isinstance(X, sp.csr_matrix):
            X = sp.csr_matrix(X)
        vs = cls(X=X, obs=obs, var_names=list(var_names), sections=sections,
                 obsm=dict(obsm or {}), uns=dict(uns or {}))
        vs.refresh_z()
        vs.validate()
        return vs

    def refresh_z(self) -> None:
        """Copy section z into the per-spot table (z_um is spot-level, constant within a section)."""
        zs = self.sections.loc[self.obs["section_id"]]
        use = zs["z_um"].where(zs["z_source"] == "measured", zs["z_um_assumed"])
        self.obs["z_um"] = use.to_numpy()
        self.obs["z_is_assumed"] = (zs["z_source"] != "measured").to_numpy()

    # ---- views -------------------------------------------------------------------------
    @property
    def n_sections(self) -> int:
        return len(self.sections)

    @property
    def ordered_section_ids(self) -> list[str]:
        return list(self.sections.sort_values("order").index)

    def rows(self, section_id: str) -> np.ndarray:
        return np.flatnonzero((self.obs["section_id"] == section_id).to_numpy())

    def neighbours(self, section_id: str) -> tuple[str | None, str | None]:
        """(upper, lower) physically adjacent *present* sections; missing sections are skipped."""
        ids = self.ordered_section_ids
        i = ids.index(section_id)
        return (ids[i - 1] if i > 0 else None, ids[i + 1] if i + 1 < len(ids) else None)

    def delta_z(self, a: str, b: str) -> float:
        z = self.obs.groupby("section_id")["z_um"].first()
        return float(abs(z[b] - z[a]))

    # ---- invariants --------------------------------------------------------------------
    def validate(self) -> None:
        if self.X.shape != (len(self.obs), len(self.var_names)):
            raise VolumeValidationError(f"X shape {self.X.shape} != (n_obs, n_vars)=({len(self.obs)}, {len(self.var_names)})")
        if len(set(self.var_names)) != len(self.var_names):
            raise VolumeValidationError("duplicate gene names")
        if self.obs.index.has_duplicates:
            raise VolumeValidationError("duplicate spot ids")
        missing = [c for c in OBS_REQUIRED if c not in self.obs]
        if missing:
            raise VolumeValidationError(f"obs missing columns: {missing}")
        if self.sections.index.has_duplicates or self.sections["order"].duplicated().any():
            raise VolumeValidationError("section ids and physical orders must be unique")
        unknown = set(self.obs["section_id"]) - set(self.sections.index)
        if unknown:
            raise VolumeValidationError(f"spots reference unknown sections: {sorted(unknown)}")
        empty = set(self.sections.index) - set(self.obs["section_id"])
        if empty:
            raise VolumeValidationError(f"sections without spots: {sorted(empty)}")
        for k, v in self.obsm.items():
            if len(v) != len(self.obs):
                raise VolumeValidationError(f"obsm[{k!r}] has {len(v)} rows, expected {len(self.obs)}")
            if any(f in k.lower() for f in FORBIDDEN_OBSM_NAMES):
                raise VolumeValidationError(f"obsm[{k!r}]: section identity must not be a feature matrix")
        if not np.isfinite(self.obs[["x_raw", "y_raw"]].to_numpy()).all():
            raise VolumeValidationError("non-finite spot coordinates")
        z = self.sections.sort_values("order")["z_um_assumed"].to_numpy()
        if np.any(np.diff(z) < 0):
            raise VolumeValidationError("z is not monotone in physical order")

    # ---- interop -----------------------------------------------------------------------
    def to_anndata(self):
        import anndata as ad

        a = ad.AnnData(X=self.X.copy(), obs=self.obs.copy(), var=pd.DataFrame(index=self.var_names))
        a.obsm["spatial_raw"] = self.obs[["x_raw", "y_raw"]].to_numpy()
        for k, v in self.obsm.items():
            a.obsm[k] = v
        a.uns["sections"] = self.sections.reset_index(drop=True).to_dict(orient="list")
        return a
