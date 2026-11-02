"""Weighted ridge regression toward a prior (generic math, no league logic)."""
from __future__ import annotations

import numpy as np


def ridge_to_prior(
    X: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    prior: np.ndarray,
    penalty: np.ndarray,
) -> np.ndarray:
    """Solve  argmin_b  Σ w_i (y_i − X_i b)² + Σ_j penalty_j (b_j − prior_j)².

    Closed form: (Xᵀ W X + P) b = Xᵀ W y + P prior, with P = diag(penalty).
    With no observations the answer is exactly the prior.
    """
    if X.shape[0] == 0:
        return prior.astype(float).copy()
    Xw = X * w[:, None]
    lhs = X.T @ Xw + np.diag(penalty)
    rhs = Xw.T @ y + penalty * prior
    return np.linalg.solve(lhs, rhs)
