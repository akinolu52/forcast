"""Fit the (mu_total, beta) predictor calibration from per-match Elo samples.

`build_elo.py` collects a `calibration_samples` list during its pass —
one entry per training match with the pre-match Elo of each side and
the final score. Fitting from those samples avoids the coarse
per-month Elo-lookup approximation.

This is intentionally a two-parameter fit — not because a richer model
wouldn't help, but because we're calibrating a downstream Poisson layer
whose main job is to translate a scalar rating advantage into a
scoreline distribution. Overfitting here is worse than a slight
misspecification.
"""

from __future__ import annotations

from predictor import Calibration


def fit_from_samples(
    samples: list[dict],
    *,
    home_adv: float,
) -> Calibration:
    """
    Each sample: {home_elo, away_elo, hg, ag}

    mu_total: mean(hg + ag) over samples
    beta:     OLS slope of (hg - ag) on ((home_elo + home_adv - away_elo) / 400)
    """
    if not samples:
        # Sensible fallback that won't blow up the browser — matches
        # long-run EPL averages.
        return Calibration(mu_total=2.7, beta=1.6)

    xs: list[float] = []
    ys: list[float] = []
    total_goals = 0

    for s in samples:
        x = (s["home_elo"] + home_adv - s["away_elo"]) / 400.0
        y = s["hg"] - s["ag"]
        xs.append(x)
        ys.append(y)
        total_goals += s["hg"] + s["ag"]

    n = len(xs)
    mu_total = total_goals / n

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    beta = num / den if den > 0 else 1.6

    # Clamp to keep the browser layer well-behaved.
    beta = max(0.5, min(beta, 3.0))
    mu_total = max(1.5, min(mu_total, 4.0))
    return Calibration(mu_total=mu_total, beta=beta)
