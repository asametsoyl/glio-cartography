"""Weighted least-squares affine M-step. Column convention y = B x + t."""
from __future__ import annotations

import numpy as np


def affine_fit(Syx: np.ndarray, Sxx: np.ndarray, mu_x: np.ndarray, mu_y: np.ndarray):
    B = Syx @ np.linalg.inv(Sxx)
    return B, mu_y - B @ mu_x
