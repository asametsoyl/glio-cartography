"""Weighted Procrustes M-step (rotation + translation, optional isotropic scale). Column convention y = A x + t."""
from __future__ import annotations

import numpy as np


def rigid_fit(Syx: np.ndarray, Sxx: np.ndarray, mu_x: np.ndarray, mu_y: np.ndarray, with_scale: bool = False):
    U, S, Vt = np.linalg.svd(Syx)
    C = np.diag([1.0, np.sign(np.linalg.det(U @ Vt)) or 1.0])
    R = U @ C @ Vt
    s = float(np.trace(np.diag(S) @ C) / np.trace(Sxx)) if with_scale else 1.0
    A = s * R
    return A, mu_y - A @ mu_x
