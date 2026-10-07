"""Expression features used by registration. Section identity is removed, never encoded."""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

_CP = 1e4


def _log_norm(X: sp.csr_matrix) -> sp.csr_matrix:
    X = sp.csr_matrix(X, dtype=np.float64)
    tot = np.maximum(np.asarray(X.sum(1)).ravel(), 1.0)
    X = sp.diags(_CP / tot) @ X
    X.data = np.log1p(X.data)
    return X.tocsr()


def joint_pca_features(Xa: sp.csr_matrix, Xb: sp.csr_matrix, n_pcs: int, n_hvg: int,
                       center: str = "joint") -> tuple[np.ndarray, np.ndarray]:
    """Joint PCA of two sections -> L2-normalised scores (rows), so a dot product is a cosine similarity.

    Counts are depth-normalised and log1p'd per spot; genes are chosen by variance on the union; each section is
    centred on the union mean (``center='joint'``) or separately (``center='section'``). Per-section centring
    removes a batch offset but also removes real composition differences between partially overlapping sections,
    which breaks cross-section similarity of the *same* tissue type; hence the joint default. PCA is fitted on
    the union. Needs only the two sections being registered, so it never leaks information across the series.
    """
    A, B = _log_norm(Xa), _log_norm(Xb)
    stack = sp.vstack([A, B]).tocsr()
    mean = np.asarray(stack.mean(0)).ravel()
    var = np.asarray(stack.multiply(stack).mean(0)).ravel() - mean ** 2
    keep = np.argsort(var)[::-1][: min(n_hvg, A.shape[1])]
    Ad, Bd = A[:, keep].toarray(), B[:, keep].toarray()
    if center == "section":
        Ad -= Ad.mean(0)
        Bd -= Bd.mean(0)
    elif center == "joint":
        mu = np.vstack([Ad, Bd]).mean(0)
        Ad -= mu
        Bd -= mu
    else:
        raise ValueError("center must be 'joint' or 'section'")
    Z = np.vstack([Ad, Bd])
    _, _, Vt = np.linalg.svd(Z, full_matrices=False)
    k = min(n_pcs, Vt.shape[0])
    P = Vt[:k].T
    Fa, Fb = Ad @ P, Bd @ P

    def unit(F):
        n = np.linalg.norm(F, axis=1, keepdims=True)
        return F / np.maximum(n, 1e-12)

    return unit(Fa), unit(Fb)
