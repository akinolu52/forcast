"""Generate a demo EPL dataset with realistic club names and Elo values.

Purpose: give the live site something to show before M4's CI cron
starts publishing real football-data.co.uk numbers. The Elo pipeline
+ predictor + Monte Carlo all run on this file exactly the same way
they will on real data — only the underlying match results are
synthesized here.

The synthetic season is generated with realistic Poisson goal rates
biased by a hidden "true strength" per team (Man City strongest,
promoted sides weakest), so the ratings the pipeline recovers should
look plausible relative to how these clubs are actually seen.

The output is marked with `"demo": true` and a `demo_note` so the UI
banner surfaces the caveat.

Usage:
    python scripts/make_demo.py [--played-fraction 0.6]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import build_elo  # noqa: E402
from leagues import LEAGUES  # noqa: E402


# 2024/25 EPL clubs, roughly ordered strongest → weakest based on
# widely-agreed pre-season expectations. Only used to seed the
# synthetic goal-generating process; the pipeline recomputes Elo
# from scratch off the resulting matches.
CURRENT_EPL = [
    "Man City", "Arsenal", "Liverpool", "Chelsea", "Tottenham",
    "Man United", "Newcastle", "Aston Villa", "Brighton", "West Ham",
    "Crystal Palace", "Fulham", "Brentford", "Wolves", "Everton",
    "Bournemouth", "Nottingham Forest", "Leicester", "Ipswich", "Southampton",
]

# A prior season with 3 different promoted sides (Luton, Sheffield United, Burnley
# were the 2023/24 promoted set — realistic to include for the rollover step).
PREV_EPL = [
    "Man City", "Arsenal", "Liverpool", "Chelsea", "Tottenham",
    "Man United", "Newcastle", "Aston Villa", "Brighton", "West Ham",
    "Crystal Palace", "Fulham", "Brentford", "Wolves", "Everton",
    "Bournemouth", "Nottingham Forest",
    "Luton", "Sheffield United", "Burnley",  # relegated at end of 2023/24
]


def generate_matches(
    teams: list[str],
    year: int,
    seed: int,
    played_fraction: float = 1.0,
) -> list[dict]:
    """Synthetic full double round-robin with realistic scoring.

    True per-team scoring rate scales linearly from ~2.1 (strongest) to
    ~0.9 (weakest). Home team gets a modest xg bump; away team is
    dampened slightly. Scores drawn from a Poisson.
    """
    rng = random.Random(seed)
    matches: list[dict] = []
    n = len(teams)

    def strength(idx: int) -> float:
        return 2.1 - 1.2 * (idx / (n - 1))

    fixtures: list[tuple[int, int]] = []
    for i in range(n):
        for j in range(n):
            if i != j:
                fixtures.append((i, j))
    rng.shuffle(fixtures)

    total = int(len(fixtures) * played_fraction)
    day = dt.date(year, 8, 17)

    for k, (i, j) in enumerate(fixtures[:total]):
        xg_h = strength(i) * 1.15 + 0.15
        xg_a = strength(j) * 0.90
        hg = _poisson_sample(rng, xg_h)
        ag = _poisson_sample(rng, xg_a)
        matches.append({
            "Date": day.strftime("%d/%m/%Y"),
            "HomeTeam": teams[i],
            "AwayTeam": teams[j],
            "FTHG": hg,
            "FTAG": ag,
        })
        # Space matches out over ~9 months
        day += dt.timedelta(days=max(1, int(275 / max(total, 1))))
    return matches


def _poisson_sample(rng: random.Random, mu: float) -> int:
    """Knuth's Poisson sampler — plenty fast for hundreds of matches."""
    L = pow(2.71828182845905, -mu)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--played-fraction", type=float, default=0.6,
                    help="portion of the current season already played")
    ap.add_argument("--seed", type=int, default=20250817)
    args = ap.parse_args()

    tmp = pathlib.Path(build_elo.DATA_DIR)
    tmp.mkdir(parents=True, exist_ok=True)

    write_csv(tmp / "EPL" / "2023.csv", generate_matches(PREV_EPL, 2023, args.seed))
    write_csv(tmp / "EPL" / "2024.csv", generate_matches(CURRENT_EPL, 2024, args.seed + 1,
                                                        played_fraction=args.played_fraction))

    league = LEAGUES["EPL"]
    payload = build_elo.build_league(league)
    payload["demo"] = True
    payload["demo_note"] = (
        "Demo dataset — synthetic matches with real EPL club names, so the "
        "predictor and simulator have something to work on. Real match "
        "results will replace this once the CI cron runs."
    )
    out = build_elo.write_output(league, payload)
    print(f"wrote {out}")
    print(f"  {len(payload['teams'])} teams, {len(payload['played'])} played, "
          f"{len(payload['fixtures'])} scheduled fixtures")
    print(f"  home advantage: {payload['home_advantage_elo']} elo")
    print(f"  calibration: mu_total={payload['calibration']['mu_total']} "
          f"beta={payload['calibration']['beta']}")
    print(f"  top of table: {payload['table'][0]['name']} "
          f"({payload['table'][0]['pts']} pts)")
    print(f"  Elo leader:  {payload['teams'][0]['name']} "
          f"({payload['teams'][0]['elo']})")


if __name__ == "__main__":
    main()
