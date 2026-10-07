"""Registration confidence: a raw score from the posterior, and a calibration against known error.

raw_i = (1 - p_null_i) * clip(agreement_i, 0, 1)
    p_null_i   posterior mass of 'no counterpart in the neighbouring section' (tissue loss / non-overlap)
    agreement  posterior-weighted cosine between the spot and its candidate counterparts after alignment

The raw score is NOT a probability. ``IsotonicCalibrator`` maps it to P(error < threshold) using a set of spots whose
true error is known (the synthetic phantom). A calibrator fitted on a phantom says nothing about real data until it
is checked there; the manifest records which data a calibrator was fitted on.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def raw_confidence(p_null: np.ndarray, agreement: np.ndarray) -> np.ndarray:
    return (1.0 - np.asarray(p_null)) * np.clip(np.asarray(agreement), 0.0, 1.0)


def _pava(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Pool-adjacent-violators for a non-decreasing fit."""
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y, w):
        vals.append(yi), wts.append(wi), cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / (wts[-2] + wts[-1])
            wt, c = wts[-2] + wts[-1], cnt[-2] + cnt[-1]
            vals[-2:], wts[-2:], cnt[-2:] = [v], [wt], [c]
    return np.repeat(vals, cnt)


@dataclass
class IsotonicCalibrator:
    x: np.ndarray
    y: np.ndarray
    fitted_on: str = "unspecified"

    @classmethod
    def fit(cls, raw: np.ndarray, good: np.ndarray, fitted_on: str = "unspecified") -> "IsotonicCalibrator":
        raw, good = np.asarray(raw, float), np.asarray(good, float)
        o = np.argsort(raw)
        fit = _pava(good[o], np.ones(len(o)))
        return cls(raw[o], fit, fitted_on)

    def __call__(self, raw: np.ndarray) -> np.ndarray:
        return np.interp(np.asarray(raw, float), self.x, self.y)


def expected_calibration_error(prob: np.ndarray, good: np.ndarray, n_bins: int = 10) -> float:
    prob, good = np.asarray(prob, float), np.asarray(good, float)
    bins = np.minimum((prob * n_bins).astype(int), n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        m = bins == b
        if m.any():
            ece += m.mean() * abs(prob[m].mean() - good[m].mean())
    return float(ece)


def auc(score: np.ndarray, positive: np.ndarray) -> float:
    """Rank-based AUC (Mann-Whitney); ties get average rank."""
    score, positive = np.asarray(score, float), np.asarray(positive, bool)
    n1, n0 = positive.sum(), (~positive).sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score))
    sorted_scores = score[order]
    i = 0
    while i < len(score):
        j = i
        while j + 1 < len(score) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[positive].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))
