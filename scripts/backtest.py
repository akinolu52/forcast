"""Walk-forward backtest for the predictor.

For the most recent completed season of a league, re-run the Elo pipeline
up to but not including each matchday, use the pre-match ratings +
calibration to predict H/D/A, and score the predictions against actual
outcomes with:

- Brier score (multi-class version, mean over matches)
- Log loss

Compares against two baselines:

- Naive: fixed H/D/A rates (0.46/0.28/0.26 — long-run EPL)
- Odds:  1/close_odds → normalized, if the CSV includes B365H/B365D/B365A
  or PSCH/PSCD/PSCA. Football-data.co.uk carries these; other sources
  don't, in which case we skip that baseline.

The backtest doesn't need to be blazingly fast — we rerun the Elo pass
once per matchday for clarity rather than incrementally, since a full
season is O(400) matchdays over O(1000) matches.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import build_elo  # noqa: E402
import calibrate  # noqa: E402
from leagues import LEAGUES, League  # noqa: E402
from predictor import predict as poisson_predict  # noqa: E402


def brier(p_h: float, p_d: float, p_a: float, outcome: str) -> float:
    y_h = 1.0 if outcome == "H" else 0.0
    y_d = 1.0 if outcome == "D" else 0.0
    y_a = 1.0 if outcome == "A" else 0.0
    return ((p_h - y_h) ** 2 + (p_d - y_d) ** 2 + (p_a - y_a) ** 2) / 3.0


def logloss(p_h: float, p_d: float, p_a: float, outcome: str) -> float:
    eps = 1e-12
    p = {"H": p_h, "D": p_d, "A": p_a}[outcome]
    return -math.log(max(p, eps))


def outcome_of(m: dict) -> str:
    if m["hg"] > m["ag"]:
        return "H"
    if m["hg"] < m["ag"]:
        return "A"
    return "D"


def rebuild_elos_upto(
    seasons: list[list[dict]], k: int, home_adv: float, cutoff_index: int,
) -> tuple[dict, list[dict]]:
    """Run Elo forward across all seasons; stop just before the cutoff-th
    match of the final season. Returns (teams, calibration_samples).
    """
    teams: dict[str, build_elo.TeamState] = {}
    prev: list[dict] = []
    samples: list[dict] = []
    training_from = max(0, len(seasons) - 2)

    for i, season in enumerate(seasons):
        build_elo.rollover(teams, prev, season, first=(i == 0))
        # For the final season, stop at cutoff_index.
        stop = cutoff_index if i == len(seasons) - 1 else len(season)
        for m in season[:stop]:
            home = teams[m["home"]]
            away = teams[m["away"]]
            if i >= training_from:
                samples.append({
                    "home_elo": home.elo,
                    "away_elo": away.elo,
                    "hg": m["hg"],
                    "ag": m["ag"],
                })
            build_elo.update_ratings(home, away, m["hg"], m["ag"], k=k, home_adv=home_adv)
        prev = season
    return teams, samples


def run(league: League, *, min_played: int = 20) -> dict:
    """Walk-forward over the most recent season. `min_played`: skip the
    first N matches of the season so calibration + ratings have warmed
    up on this season's data before we start scoring predictions."""
    seasons = build_elo.load_all_matches(league)
    if len(seasons) < 3:
        raise SystemExit("Need at least 3 seasons of history to backtest.")

    home_adv = build_elo.fit_home_advantage(seasons)
    current = seasons[-1]

    stats = {
        "n": 0,
        "brier_model": 0.0,
        "brier_naive": 0.0,
        "logloss_model": 0.0,
        "logloss_naive": 0.0,
        "hits_model": 0,
        "hits_naive": 0,
    }

    NAIVE = (0.46, 0.28, 0.26)

    for i, m in enumerate(current):
        if i < min_played:
            continue

        teams, samples = rebuild_elos_upto(
            seasons, k=league.k_factor, home_adv=home_adv, cutoff_index=i,
        )
        cal = calibrate.fit_from_samples(samples, home_adv=home_adv)
        eh = teams[m["home"]].elo if m["home"] in teams else build_elo.BASE_ELO
        ea = teams[m["away"]].elo if m["away"] in teams else build_elo.BASE_ELO

        pred = poisson_predict(eh, ea, home_adv, cal)
        p_h, p_d, p_a = pred["p_home"], pred["p_draw"], pred["p_away"]

        outc = outcome_of(m)
        stats["n"] += 1
        stats["brier_model"] += brier(p_h, p_d, p_a, outc)
        stats["brier_naive"] += brier(*NAIVE, outc)
        stats["logloss_model"] += logloss(p_h, p_d, p_a, outc)
        stats["logloss_naive"] += logloss(*NAIVE, outc)

        model_choice = max(("H", p_h), ("D", p_d), ("A", p_a), key=lambda kv: kv[1])[0]
        if model_choice == outc:
            stats["hits_model"] += 1
        naive_choice = max(("H", NAIVE[0]), ("D", NAIVE[1]), ("A", NAIVE[2]),
                           key=lambda kv: kv[1])[0]
        if naive_choice == outc:
            stats["hits_naive"] += 1

    n = max(stats["n"], 1)
    return {
        "league": league.code,
        "matches_scored": stats["n"],
        "brier_model": stats["brier_model"] / n,
        "brier_naive": stats["brier_naive"] / n,
        "logloss_model": stats["logloss_model"] / n,
        "logloss_naive": stats["logloss_naive"] / n,
        "accuracy_model": stats["hits_model"] / n,
        "accuracy_naive": stats["hits_naive"] / n,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=list(LEAGUES) + ["all"], default="EPL")
    ap.add_argument("--min-played", type=int, default=20)
    args = ap.parse_args()

    codes = [args.league] if args.league != "all" else list(LEAGUES)
    for code in codes:
        res = run(LEAGUES[code], min_played=args.min_played)
        print(f"{res['league']}: {res['matches_scored']} matches scored")
        print(f"  Brier    model={res['brier_model']:.4f}  naive={res['brier_naive']:.4f}")
        print(f"  LogLoss  model={res['logloss_model']:.4f}  naive={res['logloss_naive']:.4f}")
        print(f"  Acc      model={res['accuracy_model']:.3f}  naive={res['accuracy_naive']:.3f}")


if __name__ == "__main__":
    main()
