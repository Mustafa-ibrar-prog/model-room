"""Joint probability of a parlay under a Gaussian copula (TEST, Moose 2026-11-27). Python twin of src/lib/parlay/joint.ts;
the backtest uses this file, the site uses the TypeScript one, and tests check they agree on the same inputs.

A leg is an event on one latent variable: side * Z_var > threshold, threshold = Phi^-1(1 - p). Several legs can sit on
the same variable (points 20+ and points 25+, or a spread and a moneyline: both are the home margin). Variables are
joined by the correlation matrix from the historical table. Two legs on two variables: exact (Genz's bivariate
normal). Otherwise: Genz's seeded separation-of-variables integration, so every number reproduces.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_N = NormalDist()
phi = _N.cdf
inv_phi = _N.inv_cdf


def _vec_normal():
    """Vectorised normal CDF / inverse: scipy's when installed (offline backtests), else the standard library's."""
    try:
        from scipy.special import ndtr, ndtri
        return ndtr, lambda q: ndtri(np.clip(q, 1e-15, 1 - 1e-15))
    except ImportError:  # pragma: no cover
        return np.vectorize(phi), np.vectorize(lambda q: inv_phi(min(max(q, 1e-15), 1 - 1e-15)))


def bvnu(h: float, k: float, r: float) -> float:
    """P(X > h, Y > k) for standard bivariate normal with correlation r (Genz, 'Numerical computation of rectangular
    bivariate and trivariate normal and t probabilities', 2004)."""
    if h == math.inf or k == math.inf:
        return 0.0
    if h == -math.inf:
        return 1.0 if k == -math.inf else phi(-k)
    if k == -math.inf:
        return phi(-h)
    if r == 0:
        return phi(-h) * phi(-k)
    if abs(r) < 0.3:
        w = [0.1713244923791705, 0.3607615730481384, 0.4679139345726904]
        x = [0.9324695142031522, 0.6612093864662647, 0.2386191860831970]
    elif abs(r) < 0.75:
        w = [0.04717533638651177, 0.1069393259953183, 0.1600783285433464, 0.2031674267230659, 0.2334925365383547, 0.2491470458134029]
        x = [0.9815606342467191, 0.9041172563704750, 0.7699026741943050, 0.5873179542866171, 0.3678314989981802, 0.1252334085114692]
    else:
        w = [0.01761400713915212, 0.04060142980038694, 0.06267204833410906, 0.08327674157670475, 0.1019301198172404,
             0.1181945319615184, 0.1316886384491766, 0.1420961093183821, 0.1491729864726037, 0.1527533871307259]
        x = [0.9931285991850949, 0.9639719272779138, 0.9122344282513259, 0.8391169718222188, 0.7463319064601508,
             0.6360536807265150, 0.5108670019508271, 0.3737060887154196, 0.2277858511416451, 0.07652652113349733]
    W = np.array(w + w)
    X = np.array([1 - v for v in x] + [1 + v for v in x])
    tp = 2 * math.pi
    hk = h * k
    if abs(r) < 0.925:
        hs = (h * h + k * k) / 2
        asr = math.asin(r) / 2
        sn = np.sin(asr * X)
        bvn = float(np.sum(np.exp((sn * hk - hs) / (1 - sn * sn)) * W))
        bvn = bvn * asr / tp + phi(-h) * phi(-k)
    else:
        if r < 0:
            k, hk = -k, -hk
        bvn = 0.0
        if abs(r) < 1:
            as_ = 1 - r * r
            a = math.sqrt(as_)
            bs = (h - k) ** 2
            asr = -(bs / as_ + hk) / 2
            c = (4 - hk) / 8
            d = (12 - hk) / 80
            if asr > -100:
                bvn = a * math.exp(asr) * (1 - c * (bs - as_) * (1 - d * bs) / 3 + c * d * as_ * as_)
            if hk > -100:
                b = math.sqrt(bs)
                sp = math.sqrt(tp) * phi(-b / a)
                bvn -= math.exp(-hk / 2) * sp * b * (1 - c * bs * (1 - d * bs) / 3)
            a /= 2
            xs = (a * X) ** 2
            asr_v = -(bs / xs + hk) / 2
            ix = asr_v > -100
            xs, Wi = xs[ix], W[ix]
            sp = 1 + c * xs * (1 + 5 * d * xs)
            rs = np.sqrt(1 - xs)
            ep = np.exp(-(hk / 2) * xs / (1 + rs) ** 2) / rs
            bvn = (a * float(np.sum(np.exp(asr_v[ix]) * (sp - ep) * Wi)) - bvn) / tp
        if r > 0:
            bvn += phi(-max(h, k))
        elif h >= k:
            bvn = -bvn
        else:
            L = phi(k) - phi(h) if h < 0 else phi(-h) - phi(-k)
            bvn = L - bvn
    return max(0.0, min(1.0, bvn))


def nearest_corr(R: np.ndarray) -> np.ndarray:
    """Clip negative eigenvalues and rescale to a unit diagonal (pooled pairwise coefficients need not be jointly valid)."""
    R = (R + R.T) / 2
    w, V = np.linalg.eigh(R)
    if w.min() >= 1e-8:
        return R
    w = np.maximum(w, 1e-6)
    S = V @ np.diag(w) @ V.T
    d = np.sqrt(np.diag(S))
    return S / np.outer(d, d)


def joint(legs: list[dict], R: np.ndarray, sims: int = 20_000, seed: int = 20261127) -> dict:
    """legs: [{"var": int, "side": +1|-1, "p": float}], R: correlation matrix over the variables.
    Returns {"p", "se", "method"}. A leg with p of 0 or 1 is handled exactly."""
    if any(l["p"] <= 0 for l in legs):
        return {"p": 0.0, "se": 0.0, "method": "exact"}
    legs = [l for l in legs if l["p"] < 1]
    if not legs:
        return {"p": 1.0, "se": 0.0, "method": "exact"}
    # Per variable: the interval of the latent value that satisfies every leg on it.
    lo: dict[int, float] = {}
    hi: dict[int, float] = {}
    for l in legs:
        t = inv_phi(1 - l["p"])
        v = l["var"]
        if l["side"] > 0:          # Z > t
            lo[v] = max(lo.get(v, -math.inf), t)
        else:                      # -Z > t  <=>  Z < -t
            hi[v] = min(hi.get(v, math.inf), -t)
    vars_ = sorted(set(lo) | set(hi))
    L = np.array([lo.get(v, -math.inf) for v in vars_])
    H = np.array([hi.get(v, math.inf) for v in vars_])
    if np.any(L >= H):
        return {"p": 0.0, "se": 0.0, "method": "exact"}
    if len(vars_) == 1:
        return {"p": max(0.0, phi(H[0]) - phi(L[0])), "se": 0.0, "method": "exact"}
    sub = R[np.ix_(vars_, vars_)]
    one_sided = all((L[i] == -math.inf) != (H[i] == math.inf) for i in range(len(vars_)))
    if len(vars_) == 2 and one_sided:
        # orient both as upper tails
        s = [1 if L[i] > -math.inf else -1 for i in range(2)]
        t = [L[i] if s[i] > 0 else -H[i] for i in range(2)]
        return {"p": bvnu(t[0], t[1], s[0] * s[1] * float(sub[0, 1])), "se": 0.0, "method": "exact"}
    return genz(L, H, nearest_corr(sub), sims, seed)


def genz(L: np.ndarray, H: np.ndarray, R: np.ndarray, sims: int = 50_000, seed: int = 20261127) -> dict:
    """P(L < Z < H) for Z ~ N(0, R): Genz's separation-of-variables estimator (far lower variance than counting
    hits). Seeded, so it reproduces. Variables are ordered by narrowest interval first, as Genz recommends."""
    width = np.array([phi(h) - phi(l) for l, h in zip(L, H)])
    order = np.argsort(width)
    L, H, R = L[order], H[order], R[np.ix_(order, order)]
    C = np.linalg.cholesky(R)
    n = len(L)
    rng = np.random.default_rng(seed)
    w = rng.random((sims, max(n - 1, 1)))
    cdf, icdf = _vec_normal()
    y = np.zeros((sims, n))
    d = np.full(sims, phi(L[0] / C[0, 0]))
    e = np.full(sims, phi(H[0] / C[0, 0]))
    f = e - d
    for i in range(1, n):
        y[:, i - 1] = icdf(d + w[:, i - 1] * (e - d))
        s = y[:, :i] @ C[i, :i]
        d = cdf((L[i] - s) / C[i, i])
        e = cdf((H[i] - s) / C[i, i])
        f = f * (e - d)
    p = float(f.mean())
    return {"p": max(0.0, min(1.0, p)), "se": float(f.std(ddof=1) / math.sqrt(sims)), "method": f"genz_{sims}"}


def frechet(ps: list[float]) -> tuple[float, float]:
    """Bounds on P(all) that hold whatever the dependence."""
    return max(0.0, sum(ps) - (len(ps) - 1)), min(ps)


def fair_american(p: float) -> int | None:
    if not 0 < p < 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)
