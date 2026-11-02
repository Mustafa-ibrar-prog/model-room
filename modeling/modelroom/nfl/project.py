"""Expected EPA -> points -> margin, total, spread, win probability. Deterministic."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from modelroom.common.metrics import normal_cdf

from .config import PointsModel


def _team_rows(p: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Design matrices for home and away points: [1, exp_off, rest_adv, indoor, is_home]."""
    qh = p["qb_adj_home"].astype(float).fillna(0.0)
    qa = p["qb_adj_away"].astype(float).fillna(0.0)
    home_flag = np.where(p["neutral"], 0.0, 1.0)
    H = np.column_stack([np.ones(len(p)), p["exp_off_home"] + qh, p["rest_adv"], p["indoor"], home_flag])
    A = np.column_stack([np.ones(len(p)), p["exp_off_away"] + qa, -p["rest_adv"], p["indoor"], np.zeros(len(p))])
    return H, A


def fit(train: pd.DataFrame, replacement: float) -> PointsModel:
    t = train[train["actual_margin"].notna()]
    H, A = _team_rows(t)
    X = np.vstack([H, A])
    y = np.concatenate([t["home_score"].to_numpy(float), t["away_score"].to_numpy(float)])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pm = PointsModel(*[round(float(c), 4) for c in coef], qb_replacement_epa=round(replacement, 4))
    q = apply(t, pm)
    m_res = t["actual_margin"] - q["proj_margin"]
    t_res = t["actual_total"] - q["proj_total"]
    return replace(pm, margin_sigma=round(float(np.std(m_res)), 4), total_sigma=round(float(np.std(t_res)), 4))


def apply(p: pd.DataFrame, pm: PointsModel) -> pd.DataFrame:
    H, A = _team_rows(p)
    b = np.array([pm.intercept, pm.epa_coef, pm.rest_coef, pm.indoor_coef, pm.home_coef])
    out = p.copy()
    out["proj_home_score"] = H @ b
    out["proj_away_score"] = A @ b
    out["proj_margin"] = out["proj_home_score"] - out["proj_away_score"]
    out["proj_total"] = out["proj_home_score"] + out["proj_away_score"]
    out["model_spread"] = -out["proj_margin"]
    out["home_win_prob"] = normal_cdf(out["proj_margin"].to_numpy() / pm.margin_sigma)
    # Points attributed to the QB adjustment (home perspective), for display.
    qh = out["qb_adj_home"].astype(float)
    qa = out["qb_adj_away"].astype(float)
    out["qb_points"] = pm.epa_coef * (qh.fillna(0.0) - qa.fillna(0.0))
    out.loc[qh.isna() & qa.isna(), "qb_points"] = np.nan
    return out
