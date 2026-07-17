"""Elo + Poisson match predictor.

Given the two teams' Elo ratings, a league's home-advantage bonus, and
the fitted (mu_total, beta) calibration, produces:

  * expected goals per side (xg_home, xg_away)
  * outcome probabilities (home / draw / away)
  * a scoreline grid p[i][j] = P(home scores i, away scores j)

Independent-Poisson score model with a home/away expected-goals split
from a linear Elo calibration — the standard approach used by football
Elo sites (clubelo.com, fivethirtyeight's SPI in its Poisson layer). Not
state of the art (real teams' scoring rates are slightly overdispersed
and mildly correlated), but very close to optimal for the H/D/A output
we ultimately serve.

Mirrored in docs/js/poisson.js — keep the two in sync.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_GRID = 10  # score grid capped at 10-10 (P(>10 goals for one side) < 1e-6)


@dataclass(frozen=True)
class Calibration:
    """Per-league fit.

    mu_total: expected total goals per match (both teams combined)
    beta:     Elo-diff (post home advantage) → expected goal-difference
              slope, per 400 Elo. Interpretation: a 400-Elo edge over the
              opponent implies +beta expected-goal-difference before
              clamping to non-negative xg per side.
    """
    mu_total: float
    beta: float

    def as_dict(self) -> dict:
        return {"mu_total": round(self.mu_total, 4), "beta": round(self.beta, 4)}


def expected_goals(
    elo_home: float, elo_away: float, home_adv: float, cal: Calibration
) -> tuple[float, float]:
    """Return (xg_home, xg_away), both non-negative."""
    d = (elo_home + home_adv - elo_away) / 400.0
    expected_gd = cal.beta * d
    xg_home = max(0.05, cal.mu_total / 2.0 + expected_gd / 2.0)
    xg_away = max(0.05, cal.mu_total / 2.0 - expected_gd / 2.0)
    return xg_home, xg_away


def _poisson_pmf_row(mu: float, n: int) -> list[float]:
    """[P(X=0), P(X=1), ..., P(X=n)] for X~Poisson(mu)."""
    p = math.exp(-mu)
    out = [p]
    for k in range(1, n + 1):
        p = p * mu / k
        out.append(p)
    return out


def predict(
    elo_home: float, elo_away: float, home_adv: float, cal: Calibration,
    *, max_goals: int = MAX_GRID,
) -> dict:
    """Full prediction bundle for one match."""
    xg_h, xg_a = expected_goals(elo_home, elo_away, home_adv, cal)
    ph = _poisson_pmf_row(xg_h, max_goals)
    pa = _poisson_pmf_row(xg_a, max_goals)

    grid = [[ph[i] * pa[j] for j in range(max_goals + 1)] for i in range(max_goals + 1)]

    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            v = grid[i][j]
            if i > j:
                p_home += v
            elif i == j:
                p_draw += v
            else:
                p_away += v

    total = p_home + p_draw + p_away  # ~1 minus the >max_goals tail
    p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

    return {
        "xg_home": xg_h,
        "xg_away": xg_a,
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "grid": grid,
    }
