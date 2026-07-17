"""Generate demo datasets for all leagues with realistic club names and Elo values.

Purpose: give the live site something to show before the CI cron
starts publishing real football-data.co.uk numbers. The Elo pipeline
+ predictor + Monte Carlo all run on these files exactly the same way
they will on real data — only the underlying match results are
synthesized here.

Each synthetic season is generated with realistic Poisson goal rates
biased by a hidden "true strength" per team (strongest clubs first,
promoted sides weakest), so the ratings the pipeline recovers should
look plausible.

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


LEAGUE_CLUBS: dict[str, dict] = {
    "EPL": {
        "current": [
            "Man City", "Arsenal", "Liverpool", "Chelsea", "Tottenham",
            "Man United", "Newcastle", "Aston Villa", "Brighton", "West Ham",
            "Crystal Palace", "Fulham", "Brentford", "Wolves", "Everton",
            "Bournemouth", "Nottingham Forest", "Leicester", "Ipswich", "Southampton",
        ],
        "prev": [
            "Man City", "Arsenal", "Liverpool", "Chelsea", "Tottenham",
            "Man United", "Newcastle", "Aston Villa", "Brighton", "West Ham",
            "Crystal Palace", "Fulham", "Brentford", "Wolves", "Everton",
            "Bournemouth", "Nottingham Forest",
            "Luton", "Sheffield United", "Burnley",
        ],
    },
    "LaLiga": {
        "current": [
            "Real Madrid", "Barcelona", "Ath Madrid", "Athletic Club", "Real Sociedad",
            "Real Betis", "Villarreal", "Girona", "Osasuna", "Celta",
            "Sevilla", "Getafe", "Mallorca", "Rayo Vallecano", "Las Palmas",
            "Alaves", "Leganes", "Valladolid", "Espanyol", "Valencia",
        ],
        "prev": [
            "Real Madrid", "Barcelona", "Ath Madrid", "Athletic Club", "Real Sociedad",
            "Real Betis", "Villarreal", "Girona", "Osasuna", "Celta",
            "Sevilla", "Getafe", "Mallorca", "Rayo Vallecano", "Las Palmas",
            "Alaves", "Valencia",
            "Cadiz", "Almeria", "Granada",
        ],
    },
    "SerieA": {
        "current": [
            "Inter", "Napoli", "Atalanta", "Juventus", "AC Milan",
            "Lazio", "Roma", "Fiorentina", "Bologna", "Torino",
            "Udinese", "Genoa", "Cagliari", "Empoli", "Parma",
            "Verona", "Como", "Monza", "Lecce", "Venezia",
        ],
        "prev": [
            "Inter", "Napoli", "Atalanta", "Juventus", "AC Milan",
            "Lazio", "Roma", "Fiorentina", "Bologna", "Torino",
            "Udinese", "Genoa", "Cagliari", "Empoli", "Verona",
            "Monza", "Lecce",
            "Sassuolo", "Frosinone", "Salernitana",
        ],
    },
    "Bundesliga": {
        "current": [
            "Bayern Munich", "Leverkusen", "Dortmund", "RB Leipzig", "Stuttgart",
            "Ein Frankfurt", "Freiburg", "Wolfsburg", "M'gladbach", "Mainz",
            "Werder Bremen", "Hoffenheim", "Augsburg", "Union Berlin", "Bochum",
            "St Pauli", "Holstein Kiel", "Heidenheim",
        ],
        "prev": [
            "Bayern Munich", "Leverkusen", "Dortmund", "RB Leipzig", "Stuttgart",
            "Ein Frankfurt", "Freiburg", "Wolfsburg", "M'gladbach", "Mainz",
            "Werder Bremen", "Hoffenheim", "Augsburg", "Union Berlin", "Bochum",
            "Heidenheim",
            "Darmstadt", "Koln",
        ],
    },
    "Ligue1": {
        "current": [
            "Paris SG", "Marseille", "Monaco", "Lille", "Lyon",
            "Nice", "Lens", "Rennes", "Strasbourg", "Toulouse",
            "Nantes", "Reims", "Montpellier", "Brest", "Auxerre",
            "Angers", "St Etienne", "Le Havre",
        ],
        "prev": [
            "Paris SG", "Marseille", "Monaco", "Lille", "Lyon",
            "Nice", "Lens", "Rennes", "Strasbourg", "Toulouse",
            "Nantes", "Reims", "Montpellier", "Brest",
            "Clermont", "Lorient", "Metz",
            "Auxerre",
        ],
    },
}


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


def build_one(code: str, played_fraction: float, base_seed: int) -> None:
    league = LEAGUES[code]
    clubs = LEAGUE_CLUBS[code]

    tmp = pathlib.Path(build_elo.DATA_DIR)
    seed = base_seed + hash(code) % 10000

    write_csv(tmp / code / "2023.csv",
              generate_matches(clubs["prev"], 2023, seed))
    write_csv(tmp / code / "2024.csv",
              generate_matches(clubs["current"], 2024, seed + 1,
                               played_fraction=played_fraction))

    payload = build_elo.build_league(league)
    payload["demo"] = True
    payload["demo_note"] = (
        f"Demo dataset — synthetic matches with real {league.name} club names. "
        "Real match results will replace this once the CI cron runs."
    )
    out = build_elo.write_output(league, payload)
    print(f"{code}: wrote {out}")
    print(f"  {len(payload['teams'])} teams, {len(payload['played'])} played, "
          f"{len(payload['fixtures'])} scheduled fixtures")
    print(f"  Elo leader: {payload['teams'][0]['name']} "
          f"({payload['teams'][0]['elo']})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--played-fraction", type=float, default=0.6,
                    help="portion of the current season already played")
    ap.add_argument("--seed", type=int, default=20250817)
    ap.add_argument("--league", choices=list(LEAGUES) + ["all"], default="all")
    args = ap.parse_args()

    pathlib.Path(build_elo.DATA_DIR).mkdir(parents=True, exist_ok=True)

    codes = [args.league] if args.league != "all" else list(LEAGUE_CLUBS)
    for code in codes:
        build_one(code, args.played_fraction, args.seed)


if __name__ == "__main__":
    main()
