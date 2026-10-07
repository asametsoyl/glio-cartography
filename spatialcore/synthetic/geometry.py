"""Visium-like geometry helpers shared by the phantom and (later) the footprint kernel."""
from __future__ import annotations

import numpy as np


def hex_grid(extent_um: tuple[float, float], pitch_um: float) -> np.ndarray:
    """Hexagonal lattice (rows offset by half a pitch, row spacing pitch*sqrt(3)/2), centred on the origin."""
    w, h = extent_um
    dy = pitch_um * np.sqrt(3.0) / 2.0
    n_rows = int(h // dy) + 1
    n_cols = int(w // pitch_um) + 1
    pts = []
    for r in range(n_rows):
        xs = (np.arange(n_cols) + (0.5 if r % 2 else 0.0)) * pitch_um
        pts.append(np.column_stack([xs, np.full(n_cols, r * dy)]))
    p = np.vstack(pts)
    p = p[(p[:, 0] <= w) & (p[:, 1] <= h)]
    return p - np.array([w / 2.0, h / 2.0])


def disk_quadrature(radius_um: float, rings: int) -> np.ndarray:
    """Equal-weight points in a disk: centre + ring j has 6j points at radius j/(rings+0.5)*radius.

    Point density is uniform in area (count per ring grows with radius), so a plain mean over the points
    approximates the area average of a field over the capture disk. Count = 1 + 3*rings*(rings+1).
    """
    pts = [np.zeros((1, 2))]
    for j in range(1, rings + 1):
        ang = np.arange(6 * j) * (2 * np.pi / (6 * j)) + (j % 2) * np.pi / (6 * j)
        pts.append(np.column_stack([np.cos(ang), np.sin(ang)]) * (radius_um * j / (rings + 0.5)))
    return np.vstack(pts)


def disk_lens_area(d: np.ndarray | float, radius_um: float) -> np.ndarray:
    """Overlap area of two equal disks at centre distance d: 2r^2 acos(d/2r) - (d/2) sqrt(4r^2 - d^2)."""
    d = np.asarray(d, float)
    r = radius_um
    x = np.clip(d / (2 * r), 0.0, 1.0)
    area = 2 * r * r * np.arccos(x) - (d / 2.0) * np.sqrt(np.maximum(4 * r * r - d * d, 0.0))
    return np.where(d >= 2 * r, 0.0, area)
