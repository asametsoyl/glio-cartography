"""Typed configuration. Every numeric default here is an *assumption*; none is hidden in code."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VisiumGeometry(_Frozen):
    """10x Visium (v1/v2) capture geometry. Disk 55 um, centre pitch 100 um."""

    spot_diameter_um: float = Field(55.0, gt=0)
    spot_pitch_um: float = Field(100.0, gt=0)

    @model_validator(mode="after")
    def _pitch_covers_disk(self) -> "VisiumGeometry":
        if self.spot_pitch_um < self.spot_diameter_um:
            raise ValueError("spot_pitch_um must be >= spot_diameter_um (disks may not overlap)")
        return self

    @property
    def spot_radius_um(self) -> float:
        return self.spot_diameter_um / 2.0


class ZAssumptions(_Frozen):
    """Values used ONLY when thickness/gap is unknown; any use is flagged as assumed in outputs."""

    assumed_thickness_um: float = Field(10.0, gt=0)
    assumed_gap_um: float = Field(0.0, ge=0)


class DeformConfig(_Frozen):
    """Per-section slide-frame deformation of the tissue. Magnitudes are maxima of a uniform draw."""

    rotation_deg: float = Field(0.0, ge=0)
    translation_pitch: float = Field(0.0, ge=0, description="max |shift| in units of spot pitch")
    scale_dev: float = Field(0.0, ge=0, lt=0.5, description="isotropic scale in [1-dev, 1+dev]")
    shear: float = Field(0.0, ge=0, lt=0.5)
    nonrigid_amp_um: float = Field(0.0, ge=0)
    nonrigid_length_um: float = Field(500.0, gt=0)
    overlap_fraction: float = Field(1.0, gt=0, le=1.0, description="fraction of tissue kept by a straight cut")
    tissue_loss_fraction: float = Field(0.0, ge=0, lt=1.0, description="area share removed as a random blob")
    spot_dropout: float = Field(0.0, ge=0, lt=1.0)
    tear: bool = False
    tear_width_um: float = Field(100.0, gt=0)


class ViolationConfig(_Frozen):
    """Family B: assumptions of the algorithm deliberately broken (see docs/ZBRIDGE_PHANTOM_AND_DATA.md 1.4)."""

    ambient_fraction: float = Field(0.0, ge=0, lt=1.0, description="share of counts leaked from neighbouring spots")
    zero_inflation: float = Field(0.0, ge=0, lt=1.0)
    batch_gene_sd: float = Field(0.0, ge=0, description="per-section lognormal sd of gene-wise multiplicative shift")
    bad_section: int | None = Field(None, ge=0, description="index of one section given an extra large rigid error")
    bad_section_extra_deg: float = Field(25.0, ge=0)
    boundary_slide_multiplier: float = Field(1.0, gt=0)


class PhantomConfig(_Frozen):
    """Synthetic serial-section volume with an explicit forward model (tissue -> disk x thickness -> NB counts)."""

    schema_version: Literal[1] = 1
    seed: int = 0
    n_sections: int = Field(7, ge=1)
    thickness_um: float = Field(10.0, gt=0)
    gap_um: float = Field(0.0, ge=0)
    missing_sections: tuple[int, ...] = ()
    thickness_known: bool = True
    n_genes: int = Field(2000, ge=20)
    n_programs: int = Field(20, ge=2)
    program_fraction: float = Field(0.08, gt=0, lt=1, description="share of genes upregulated by one program")
    program_logfc: float = Field(1.5, gt=0)
    mean_depth: float = Field(4000.0, gt=0, description="mean counts per spot")
    section_depth_sd: float = Field(0.2, ge=0, description="lognormal sd of per-section depth")
    spot_depth_sd: float = Field(0.3, ge=0)
    nb_dispersion: float = Field(10.0, gt=0, description="NB size r (variance = mu + mu^2/r)")
    extent_um: tuple[float, float] = (4000.0, 4000.0)
    tissue_semi_axes_um: tuple[float, float] = (1800.0, 1500.0)
    tumor_semi_axes_um: tuple[float, float, float] = (1000.0, 900.0, 60.0)
    immune_shell_um: float = Field(150.0, gt=0)
    immune_shell_z_um: float = Field(30.0, gt=0)
    vessel_radius_um: float = Field(80.0, gt=0)
    vessel_shift_um_per_section: float = Field(40.0, ge=0)
    finger_width_um: float = Field(120.0, gt=0)
    finger_sections: tuple[int, int] = (2, 4)
    slab_x_um: float = 700.0
    slab_slide_um_per_section: float = Field(40.0, ge=0)
    geometry: VisiumGeometry = VisiumGeometry()
    deform: DeformConfig = DeformConfig()
    violations: ViolationConfig = ViolationConfig()
    smooth_programs: int = Field(8, ge=0, description="within-domain smooth expression programs (0 = piecewise constant)")
    smooth_amp: float = Field(0.7, ge=0, description="sd of the smooth log-field")
    smooth_length_um: float = Field(400.0, gt=0)
    smooth_length_z_um: float = Field(300.0, gt=0)
    quad_disk_rings: int = Field(2, ge=1, description="rings of the disk quadrature (1+3r(r+1) points)")
    quad_z: int = Field(3, ge=1)

    @model_validator(mode="after")
    def _check(self) -> "PhantomConfig":
        if any(not 0 <= m < self.n_sections for m in self.missing_sections):
            raise ValueError("missing_sections must index existing sections")
        if len(set(self.missing_sections)) >= self.n_sections:
            raise ValueError("cannot drop every section")
        a, b = self.finger_sections
        if not 0 <= a <= b < self.n_sections:
            raise ValueError("finger_sections must be an ordered pair of valid section indices")
        if self.violations.bad_section is not None and self.violations.bad_section >= self.n_sections:
            raise ValueError("violations.bad_section out of range")
        return self

    @classmethod
    def from_tier(cls, tier: Literal["E", "M", "H"], seed: int = 0, **overrides) -> "PhantomConfig":
        """Difficulty tiers from docs/ZBRIDGE_PHANTOM_AND_DATA.md 1.3. The tiers are assumptions, not data."""
        d = {
            "E": DeformConfig(rotation_deg=5, translation_pitch=0.5),
            "M": DeformConfig(
                rotation_deg=15, translation_pitch=1.5, scale_dev=0.03, shear=0.02,
                nonrigid_amp_um=20, nonrigid_length_um=500, overlap_fraction=0.8, spot_dropout=0.05,
            ),
            "H": DeformConfig(
                rotation_deg=30, translation_pitch=3.0, scale_dev=0.05, shear=0.05,
                nonrigid_amp_um=60, nonrigid_length_um=500, overlap_fraction=0.75,
                tissue_loss_fraction=0.25, spot_dropout=0.05, tear=True,
            ),
        }[tier]
        base = dict(seed=seed, deform=d)
        if tier == "M":
            base["section_depth_sd"] = 0.35  # ~2x depth range between sections
        if tier == "H":
            base.update(section_depth_sd=0.35, missing_sections=(3,), thickness_known=False)
            base["violations"] = ViolationConfig(batch_gene_sd=0.2)
        base.update(overrides)
        return cls(**base)


class RegistrationConfig(_Frozen):
    """Soft-correspondence (CPD-like, coordinate x expression) registration. All values are assumptions."""

    model: Literal["rigid", "similarity", "affine"] = "rigid"
    n_pcs: int = Field(20, ge=2)
    n_hvg: int = Field(1000, ge=10)
    expression_weight: float = Field(10.0, ge=0, description="lambda_e: weight of cosine similarity in the joint likelihood")
    outlier_weight: float = Field(0.2, gt=0, lt=1, description="w: prior mass of 'no counterpart'")
    n_starts: int = Field(24, ge=1, description="initial rotations, evenly spaced over 360 degrees")
    allow_flip: bool = False
    coarse_points: int = Field(600, ge=50)
    refine_top: int = Field(3, ge=1)
    coarse_iter: int = Field(40, ge=1)
    max_iter: int = Field(150, ge=1)
    tol: float = Field(1e-5, gt=0)
    sigma_min_um: float = Field(20.0, gt=0, description="floor on the match scale (lattice quantisation)")
    block: int = Field(1024, ge=16)
    seed: int = 0


class QCConfig(_Frozen):
    """Pairwise registration QC thresholds (WARNING / FAIL). Starting values, to be calibrated on data."""

    min_overlap_warn: float = 0.30
    min_overlap_fail: float = 0.10
    max_scale_dev_warn: float = 0.10
    max_scale_dev_fail: float = 0.25
    max_shear_warn: float = 0.15
    max_shear_fail: float = 0.35
    min_expr_gain_warn: float = 0.10
    min_expr_gain_fail: float = 0.03
    eval_sigma_um: float = Field(50.0, gt=0, description="floor on the match scale used for confidence/QC posteriors (~half a pitch)")
    good_error_pitch: float = Field(0.5, gt=0, description="a spot counts as correctly registered below this error / pitch")
