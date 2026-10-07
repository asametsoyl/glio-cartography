"""2D affine transform  y = A x + t  with the quantities QC and the chain need."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Transform:
    A: np.ndarray  # (2, 2)
    t: np.ndarray  # (2,)

    @staticmethod
    def identity() -> "Transform":
        return Transform(np.eye(2), np.zeros(2))

    @staticmethod
    def rotation(deg: float, about: np.ndarray | None = None) -> "Transform":
        a = np.deg2rad(deg)
        R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        c = np.zeros(2) if about is None else np.asarray(about, float)
        return Transform(R, c - R @ c)

    def apply(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(x, float) @ self.A.T + self.t

    def compose(self, inner: "Transform") -> "Transform":
        """self o inner: x -> self(inner(x))."""
        return Transform(self.A @ inner.A, self.A @ inner.t + self.t)

    def inverse(self) -> "Transform":
        Ai = np.linalg.inv(self.A)
        return Transform(Ai, -Ai @ self.t)

    # --- decomposition A = R(angle) * [[1, h], [0, 1]] * s  (the phantom's convention) -----------------------
    def decompose(self) -> dict[str, float]:
        a = self.A
        s = float(np.sqrt(abs(np.linalg.det(a))))
        q, r = np.linalg.qr(a)
        sgn = np.sign(np.diag(r))
        q, r = q * sgn, (r.T * sgn).T  # make diag(r) positive
        angle = float(np.degrees(np.arctan2(q[1, 0], q[0, 0])))
        shear = float(r[0, 1] / r[0, 0]) if r[0, 0] != 0 else 0.0
        return {"angle_deg": angle, "scale": s, "shear": shear, "det": float(np.linalg.det(a))}

    def to_dict(self) -> dict:
        return {"A": self.A.tolist(), "t": self.t.tolist(), **self.decompose()}
