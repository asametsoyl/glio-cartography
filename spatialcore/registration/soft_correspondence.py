"""CPD-style EM registration with a joint coordinate x expression likelihood.

Moving points x_i (features g_i) are mapped by T(x) = A x + t onto fixed points y_j (features f_j).
For each fixed point the posterior over moving points (plus a 'no counterpart' component) is

    p_ij = k_ij / (sum_i' k_i'j + c),   k_ij = exp(-|y_j - T x_i|^2 / 2 sigma^2 + lambda_e * cos(f_j, g_i)),
    c    = w/(1-w) * 2 pi sigma^2 * M / V

The expression factor is a likelihood *ratio*: exp(lambda cos) is divided by Z_i = mean_j exp(lambda cos(f_j, g_i)),
the average over all fixed spots, so that q(f|g_i) is a proper density. Without this, a very broad sigma collects the
unnormalised factor from every same-type spot and the optimum degenerates (observed on partially overlapping sections).

(V = bounding-box area of the fixed points). The M-step is closed-form (rigid Procrustes or weighted affine).
Everything is accumulated block-wise so memory is O(block x M); the posterior itself is never stored.
The posterior is a by-product that later seeds the Z-correspondence graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from spatialcore.config import RegistrationConfig
from .affine import affine_fit
from .rigid import rigid_fit
from .transform import Transform

_LOG_FLOOR = 1e-300


@dataclass
class EMResult:
    transform: Transform
    sigma2: float
    loglik: float
    n_iter: int
    converged: bool
    model: str
    cov_unit: np.ndarray                  # (3, 3): sigma^2 * H^-1 for x~=[x, y, 1]; position var / coord = x~' cov x~
    n_eff: float                          # sum of posterior mass (effective matched points)
    flipped: bool = False
    history: list[float] = field(default_factory=list, repr=False)


def _bbox_area(Y: np.ndarray) -> float:
    span = Y.max(0) - Y.min(0)
    return float(max(span[0] * span[1], 1.0))


def log_expression_norm(FX, FY, lam: float, block: int) -> np.ndarray:
    """log Z_i = log mean_j exp(lam * <g_i, f_j>)  (features are unit vectors)."""
    if not lam:
        return np.zeros(len(FX))
    N = len(FY)
    acc = np.full(len(FX), -np.inf)
    for s in range(0, N, block):
        z = lam * (FY[s:s + block] @ FX.T)  # (b, M)
        zmax = z.max(0)
        acc = np.logaddexp(acc, zmax + np.log(np.exp(z - zmax).sum(0)))
    return acc - np.log(N)


def _stats(X, Y, FX, FY, logZ, T: Transform, sigma2: float, w: float, lam: float, V: float, block: int):
    """One E-step pass -> sufficient statistics for the M-step and the log-likelihood."""
    M, N = len(X), len(Y)
    TX = T.apply(X)
    c = w / (1.0 - w) * 2.0 * np.pi * sigma2 * M / V
    P1 = np.zeros(M)           # sum_j p_ij
    PT1 = np.zeros(N)          # sum_i p_ij
    PX = np.zeros((N, 2))      # sum_i p_ij x_i
    ll = 0.0
    tx2 = (TX ** 2).sum(1)
    for s in range(0, N, block):
        yb = Y[s:s + block]
        d2 = (yb ** 2).sum(1)[:, None] + tx2[None, :] - 2.0 * yb @ TX.T
        e = -np.maximum(d2, 0.0) / (2.0 * sigma2)
        if lam:
            e = e + lam * (FY[s:s + block] @ FX.T) - logZ[None, :]
        k = np.exp(e)
        den = k.sum(1) + c
        P = k / den[:, None]
        P1 += P.sum(0)
        PT1[s:s + block] = P.sum(1)
        PX[s:s + block] = P @ X
        ll += float(np.log(np.maximum(den, _LOG_FLOOR)).sum())
    ll -= N * np.log(2.0 * np.pi * sigma2 * M / (1.0 - w))
    return P1, PT1, PX, ll


def _m_step(X, Y, P1, PT1, PX, model: str, sigma_min2: float):
    Np = P1.sum()
    mu_x = P1 @ X / Np
    mu_y = PT1 @ Y / Np
    Sxx = (X * P1[:, None]).T @ X - Np * np.outer(mu_x, mu_x)
    Syx = Y.T @ PX - Np * np.outer(mu_y, mu_x)
    tr_yy = float(PT1 @ (Y ** 2).sum(1) - Np * mu_y @ mu_y)
    if model in ("rigid", "similarity"):
        A, t = rigid_fit(Syx, Sxx, mu_x, mu_y, with_scale=model == "similarity")
    else:
        A, t = affine_fit(Syx, Sxx, mu_x, mu_y)
    sigma2 = (tr_yy - 2.0 * np.trace(A.T @ Syx) + np.trace(A.T @ A @ Sxx)) / (2.0 * Np)
    return Transform(A, t), max(float(sigma2), sigma_min2), float(Np)


def _cov_unit(X, P1, sigma2):
    Xh = np.column_stack([X, np.ones(len(X))])
    H = (Xh * P1[:, None]).T @ Xh
    return sigma2 * np.linalg.inv(H + 1e-9 * np.eye(3))


def _init_sigma2(X, Y, T: Transform) -> float:
    TX = T.apply(X)
    d2 = ((Y[:, None, :] - TX[None, :, :]) ** 2).sum(-1) if len(X) * len(Y) <= 4_000_000 else None
    if d2 is None:  # mean squared distance via moments, no big matrix
        return float(((Y ** 2).sum(1).mean() + (TX ** 2).sum(1).mean() - 2 * Y.mean(0) @ TX.mean(0)) / 2.0)
    return float(d2.mean() / 2.0)


def em_register(X, Y, FX, FY, T0: Transform, cfg: RegistrationConfig, model: str, max_iter: int | None = None,
                sigma_init_um: float | None = None) -> EMResult:
    w, lam = cfg.outlier_weight, cfg.expression_weight
    V = _bbox_area(Y)
    logZ = log_expression_norm(FX, FY, lam, cfg.block)
    smin2 = cfg.sigma_min_um ** 2
    T = T0
    sigma2 = max(_init_sigma2(X, Y, T) if sigma_init_um is None else sigma_init_um ** 2, smin2)
    prev = -np.inf
    hist: list[float] = []
    n_iter, ok = 0, False
    P1 = None
    for it in range(max_iter or cfg.max_iter):
        P1, PT1, PX, ll = _stats(X, Y, FX, FY, logZ, T, sigma2, w, lam, V, cfg.block)
        hist.append(ll)
        T, sigma2, Np = _m_step(X, Y, P1, PT1, PX, model, smin2)
        n_iter = it + 1
        if abs(ll - prev) < cfg.tol * max(abs(ll), 1.0):
            ok = True
            break
        prev = ll
    P1, PT1, PX, ll = _stats(X, Y, FX, FY, logZ, T, sigma2, w, lam, V, cfg.block)
    return EMResult(T, sigma2, ll, n_iter, ok, model, _cov_unit(X, P1, sigma2), float(P1.sum()), history=hist)


def register_points(X, Y, FX, FY, cfg: RegistrationConfig) -> EMResult:
    """Multi-start rigid search on subsamples, rigid refinement on all points, then optional affine."""
    rng = np.random.default_rng(cfg.seed)
    X, Y = np.asarray(X, float), np.asarray(Y, float)
    flips = [False, True] if cfg.allow_flip else [False]
    best: list[tuple[float, Transform, bool]] = []
    for flip in flips:
        Xf = X * np.array([-1.0, 1.0]) if flip else X
        sx = rng.choice(len(X), min(cfg.coarse_points, len(X)), replace=False)
        sy = rng.choice(len(Y), min(cfg.coarse_points, len(Y)), replace=False)
        cx, cy = Xf.mean(0), Y.mean(0)
        for k in range(cfg.n_starts):
            R = Transform.rotation(360.0 * k / cfg.n_starts, about=cx)
            T0 = Transform(R.A, R.t + (cy - cx))
            r = em_register(Xf[sx], Y[sy], FX[sx], FY[sy], T0, cfg, "rigid", cfg.coarse_iter)
            best.append((r.loglik, r.transform, flip))
    best.sort(key=lambda b: -b[0])
    sx = rng.choice(len(X), min(cfg.refine_points, len(X)), replace=False)
    sy = rng.choice(len(Y), min(cfg.refine_points, len(Y)), replace=False)
    finals = []
    for _, T0, flip in best[: cfg.refine_top]:  # refine on a subsample, compare on the same subsample
        Xf = X * np.array([-1.0, 1.0]) if flip else X
        r = em_register(Xf[sx], Y[sy], FX[sx], FY[sy], T0, cfg, "rigid")
        finals.append((r, flip))
    r0, flip = max(finals, key=lambda p: p[0].loglik)
    Xf = X * np.array([-1.0, 1.0]) if flip else X
    # polish on all points (a few EM steps from the converged subsample solution; sigma restarts from a tight value)
    r = em_register(Xf, Y, FX, FY, r0.transform, cfg, "rigid", cfg.polish_iter, sigma_init_um=float(np.sqrt(r0.sigma2)))
    r.flipped = flip
    if cfg.model != "rigid":
        ra = em_register(Xf, Y, FX, FY, r.transform, cfg, cfg.model, cfg.polish_iter, sigma_init_um=float(np.sqrt(r.sigma2)))
        ra.flipped = flip
        r = ra
    if r.flipped:  # fold the reflection into A so callers see one transform on the *original* coordinates
        F = Transform(np.diag([-1.0, 1.0]), np.zeros(2))
        r.transform = r.transform.compose(F)
    return r


def row_posterior(Y, X, FY, FX, sigma2: float, cfg: RegistrationConfig, lam: float | None = None):
    """Per-point posterior summary for every row point y_j against the point set X (already in Y's frame).

    Returns ``(p_null, agreement)``: ``p_null_j`` is the posterior mass of 'no counterpart' and ``agreement_j``
    the posterior-weighted cosine between f_j and the candidates (0 when no candidate carries mass).
    ``lam=0`` gives the geometry-only reference used by QC.
    """
    lam = cfg.expression_weight if lam is None else lam
    w, block = cfg.outlier_weight, cfg.block
    M, N = len(X), len(Y)
    V = _bbox_area(Y)
    c = w / (1.0 - w) * 2.0 * np.pi * sigma2 * M / V
    logZ = log_expression_norm(FX, FY, lam, block)
    x2 = (X ** 2).sum(1)
    p_null = np.empty(N)
    agree = np.zeros(N)
    for s in range(0, N, block):
        yb = Y[s:s + block]
        d2 = (yb ** 2).sum(1)[:, None] + x2[None, :] - 2.0 * yb @ X.T
        S = FY[s:s + block] @ FX.T
        k = np.exp(-np.maximum(d2, 0.0) / (2.0 * sigma2) + (lam * S - logZ[None, :] if lam else 0.0))
        ks = k.sum(1)
        p_null[s:s + block] = c / (ks + c)
        with np.errstate(invalid="ignore", divide="ignore"):
            agree[s:s + block] = np.where(ks > 0, (k * S).sum(1) / ks, 0.0)
    return p_null, agree
