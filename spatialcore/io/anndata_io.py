"""AnnData (.h5ad) -> VolumeSet. One AnnData per section; physical order and z terms are supplied by the caller."""
from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp

from spatialcore.config import VisiumGeometry, ZAssumptions
from scipy.spatial import cKDTree

from spatialcore.data.volume import SectionMeta, VolumeSet, VolumeValidationError

_PITCH_TOLERANCE = 0.1  # estimated pitch must be within 10 % of the nominal one, else the layout is not Visium-like


def estimate_um_per_unit(xy: np.ndarray, pitch_um: float = 100.0) -> float:
    """Micrometres per coordinate unit from the median nearest-neighbour spot distance == lattice pitch.

    Only valid for an in-tissue, mostly contiguous Visium-like lattice; callers should prefer an explicit
    scale from the platform metadata when it exists. Raises if the lattice looks non-regular
    (nearest-neighbour distances too spread out for the median to be the pitch).
    """
    xy = np.asarray(xy, float)[:, :2]
    d = cKDTree(xy).query(xy, k=2)[0][:, 1]
    med = float(np.median(d))
    if med <= 0 or np.percentile(d, 75) > (1 + _PITCH_TOLERANCE) * med:
        raise VolumeValidationError("nearest-neighbour distances are not lattice-like; pass um_per_unit explicitly")
    return pitch_um / med


def volume_from_anndata(
    adatas: dict[str, "object"], order: list[str], sample_id: str = "sample",
    spatial_key: str = "spatial", um_per_unit: float | None = None, geometry: VisiumGeometry | None = None,
    thickness_um: float | None = None, thickness_source: str = "unknown",
    gap_um: float | None = None, gap_source: str = "unknown", assume: ZAssumptions | None = None,
) -> VolumeSet:
    """``order`` is the physical top-to-bottom section order and is NOT inferred from dict/file order.

    Genes are intersected across sections (an error if the intersection is empty). ``um_per_unit`` converts
    the stored coordinates to micrometres; when None it is estimated per section from the lattice pitch
    (``estimate_um_per_unit``) and recorded in ``uns['um_per_unit']`` so the choice is auditable.
    """
    geometry = geometry or VisiumGeometry()
    scales: dict[str, float] = {}
    if sorted(order) != sorted(adatas):
        raise VolumeValidationError("`order` must list exactly the provided sections")
    genes = None
    for a in adatas.values():
        if genes is None:
            genes = list(a.var_names)
        else:
            present = set(a.var_names)
            genes = [g for g in genes if g in present]  # keeps the first section's gene order
    if not genes:
        raise VolumeValidationError("sections share no genes")
    Xs, obs_parts, metas = [], [], []
    for k, sid in enumerate(order):
        a = adatas[sid]
        if spatial_key not in a.obsm:
            raise VolumeValidationError(f"{sid}: obsm[{spatial_key!r}] missing")
        X = a.X if list(a.var_names) == genes else a.X[:, a.var_names.get_indexer(genes)]
        Xs.append(sp.csr_matrix(X))
        raw = np.asarray(a.obsm[spatial_key], float)[:, :2]
        scales[sid] = um_per_unit if um_per_unit is not None else estimate_um_per_unit(raw, geometry.spot_pitch_um)
        xy = raw * scales[sid]
        obs_parts.append(pd.DataFrame(
            {"section_id": sid, "sample_id": sample_id, "x_raw": xy[:, 0], "y_raw": xy[:, 1]},
            index=[f"{sid}:{n}" for n in a.obs_names],
        ))
        metas.append(SectionMeta(
            section_id=sid, order=k, sample_id=sample_id, thickness_um=thickness_um,
            thickness_source=thickness_source, gap_um=gap_um, gap_source=gap_source,
            spot_diameter_um=geometry.spot_diameter_um, spot_pitch_um=geometry.spot_pitch_um,
        ))
    return VolumeSet.from_parts(sp.vstack(Xs).tocsr(), pd.concat(obs_parts), genes, metas, assume=assume,
                                uns={"um_per_unit": scales})
