"""Space Ranger output -> (counts, obs, var_names, SectionMeta). Coordinates are converted to micrometres."""
from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import scipy.sparse as sp

from spatialcore.config import VisiumGeometry
from spatialcore.data.checksums import sha256_file
from spatialcore.data.volume import SectionMeta, VolumeValidationError

_POS_COLUMNS = ["barcode", "in_tissue", "array_row", "array_col", "pxl_row_in_fullres", "pxl_col_in_fullres"]


def _read_h5_matrix(path: Path) -> tuple[sp.csr_matrix, list[str], list[str]]:
    with h5py.File(path, "r") as f:
        m = f["matrix"]
        data, indices, indptr = m["data"][:], m["indices"][:], m["indptr"][:]
        shape = tuple(int(v) for v in m["shape"][:])  # (genes, barcodes)
        barcodes = [b.decode() for b in m["barcodes"][:]]
        feats = m["features"]
        names = [n.decode() for n in feats["name"][:]]
        if "feature_type" in feats:
            keep = np.array([t.decode() == "Gene Expression" for t in feats["feature_type"][:]])
        else:
            keep = np.ones(len(names), dtype=bool)
    csc = sp.csc_matrix((data, indices, indptr), shape=shape)  # genes x barcodes
    X = csc.T.tocsr()[:, np.flatnonzero(keep)]
    return X, barcodes, [n for n, k in zip(names, keep) if k]


def _read_positions(spatial_dir: Path) -> pd.DataFrame:
    new, old = spatial_dir / "tissue_positions.csv", spatial_dir / "tissue_positions_list.csv"
    if new.exists():
        df = pd.read_csv(new)
        df.columns = _POS_COLUMNS
    elif old.exists():
        df = pd.read_csv(old, header=None, names=_POS_COLUMNS)
    else:
        raise FileNotFoundError(f"no tissue_positions(.csv|_list.csv) in {spatial_dir}")
    return df.set_index("barcode")


def load_visium_section(
    outs_dir: str | Path, section_id: str, order: int, sample_id: str = "sample",
    geometry: VisiumGeometry | None = None, thickness_um: float | None = None,
    thickness_source: str = "unknown", gap_um: float | None = None, gap_source: str = "unknown",
    in_tissue_only: bool = True,
):
    """Load one Space Ranger ``outs`` directory. Returns ``(X, obs, var_names, SectionMeta)``.

    Pixel -> micrometre uses the Visium disk: ``spot_diameter_fullres`` pixels == ``spot_diameter_um``.
    """
    geometry = geometry or VisiumGeometry()
    outs = Path(outs_dir)
    h5 = outs / "filtered_feature_bc_matrix.h5"
    if not h5.exists():
        raise FileNotFoundError(h5)
    X, barcodes, genes = _read_h5_matrix(h5)
    pos = _read_positions(outs / "spatial")
    scale = json.loads((outs / "spatial" / "scalefactors_json.json").read_text())
    um_per_px = geometry.spot_diameter_um / float(scale["spot_diameter_fullres"])

    missing = [b for b in barcodes if b not in pos.index]
    if missing:
        raise VolumeValidationError(f"{len(missing)} barcodes have no tissue position (first: {missing[0]})")
    pos = pos.loc[barcodes]
    obs = pd.DataFrame(
        {
            "section_id": section_id,
            "sample_id": sample_id,
            "x_raw": pos["pxl_col_in_fullres"].to_numpy(float) * um_per_px,
            "y_raw": pos["pxl_row_in_fullres"].to_numpy(float) * um_per_px,
            "in_tissue": pos["in_tissue"].to_numpy() == 1,
            "n_counts": np.asarray(X.sum(1)).ravel(),
            "n_genes": np.asarray((X > 0).sum(1)).ravel(),
        },
        index=[f"{section_id}:{b}" for b in barcodes],
    )
    if in_tissue_only:
        keep = obs["in_tissue"].to_numpy()
        X, obs = X[keep], obs[keep]
    meta = SectionMeta(
        section_id=section_id, order=order, sample_id=sample_id, thickness_um=thickness_um,
        thickness_source=thickness_source, gap_um=gap_um, gap_source=gap_source, platform="visium",
        spot_diameter_um=geometry.spot_diameter_um, spot_pitch_um=geometry.spot_pitch_um,
        checksum_sha256=sha256_file(h5),
    )
    return X, obs, genes, meta
