"""Build the UCL JSON payload from domestic Elo ratings.

The UCL doesn't use football-data.co.uk. Instead, we pull each
participant's Elo from the domestic league JSONs (already built by
build_elo.py) and generate a UCL-specific payload with:

- 36 teams (league phase participants) with their domestic Elo
- League phase fixtures (8 matches per team, pre-drawn)
- League phase results (played so far)
- Knockout bracket structure

The 2024/25+ format: 36 teams play 8 matches each in a single league
table (Swiss-style draw). Top 8 go to R16, 9-24 play two-leg playoffs
for the remaining 8 R16 spots, 25-36 are eliminated. QF onward is
single-leg at neutral venue.

Usage:
    python scripts/ucl.py                    # build from domestic JSONs
    python scripts/ucl.py --demo             # generate demo UCL data
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from predictor import Calibration  # noqa: E402

DOCS_DATA = pathlib.Path(__file__).parent.parent / "docs" / "data"

UCL_TEAMS_2024 = [
    ("Real Madrid", "LaLiga"),
    ("Man City", "EPL"),
    ("Bayern Munich", "Bundesliga"),
    ("Paris SG", "Ligue1"),
    ("Inter", "SerieA"),
    ("Barcelona", "LaLiga"),
    ("Dortmund", "Bundesliga"),
    ("RB Leipzig", "Bundesliga"),
    ("Liverpool", "EPL"),
    ("Leverkusen", "Bundesliga"),
    ("Ath Madrid", "LaLiga"),
    ("Atalanta", "SerieA"),
    ("Juventus", "SerieA"),
    ("Benfica", "other"),
    ("Arsenal", "EPL"),
    ("Club Brugge", "other"),
    ("Shakhtar", "other"),
    ("AC Milan", "SerieA"),
    ("Feyenoord", "other"),
    ("Sporting", "other"),
    ("PSV", "other"),
    ("Celtic", "other"),
    ("Monaco", "Ligue1"),
    ("Aston Villa", "EPL"),
    ("Bologna", "SerieA"),
    ("Girona", "LaLiga"),
    ("Stuttgart", "Bundesliga"),
    ("Sturm Graz", "other"),
    ("Brest", "Ligue1"),
    ("Red Star", "other"),
    ("Salzburg", "other"),
    ("Lille", "Ligue1"),
    ("Dinamo Zagreb", "other"),
    ("Young Boys", "other"),
    ("Slovan Bratislava", "other"),
    ("Sparta Prague", "other"),
]

FALLBACK_ELOS = {
    "Benfica": 1580, "Club Brugge": 1480, "Shakhtar": 1470,
    "Feyenoord": 1500, "Sporting": 1530, "PSV": 1510,
    "Celtic": 1460, "Sturm Graz": 1380, "Red Star": 1390,
    "Salzburg": 1430, "Dinamo Zagreb": 1400, "Young Boys": 1380,
    "Slovan Bratislava": 1350, "Sparta Prague": 1410,
}

UCL_HOME_ADV = 45.0
UCL_K = 40


def load_domestic_elos() -> dict[str, float]:
    """Read each domestic league JSON and extract current Elo per team."""
    elos: dict[str, float] = {}
    for path in DOCS_DATA.glob("*.json"):
        if path.stem == "ucl":
            continue
        try:
            data = json.loads(path.read_text())
            for t in data.get("teams", []):
                elos[t["name"]] = t["elo"]
        except (json.JSONDecodeError, KeyError):
            continue
    return elos


def resolve_elos(teams: list[tuple[str, str]]) -> dict[str, float]:
    """Get Elo for each UCL team from domestic data or fallbacks."""
    domestic = load_domestic_elos()
    result: dict[str, float] = {}
    for name, league in teams:
        if name in domestic:
            result[name] = domestic[name]
        elif name in FALLBACK_ELOS:
            result[name] = FALLBACK_ELOS[name]
        else:
            result[name] = 1450.0
    return result


def generate_league_phase_fixtures(
    teams: list[str], seed: int = 42
) -> list[dict]:
    """Generate 8 matches per team (Swiss-style).

    Each team plays 4 home and 4 away. We use a simple round-robin
    sampling that gives each team exactly 8 opponents.
    """
    rng = random.Random(seed)
    n = len(teams)
    home_counts: dict[str, int] = {t: 0 for t in teams}
    away_counts: dict[str, int] = {t: 0 for t in teams}
    match_counts: dict[str, int] = {t: 0 for t in teams}
    seen_pairs: set[tuple[str, str]] = set()
    fixtures: list[dict] = []

    indices = list(range(n))
    rng.shuffle(indices)

    for i in indices:
        if match_counts[teams[i]] >= 8:
            continue
        candidates = [
            j for j in range(n)
            if j != i
            and match_counts[teams[j]] < 8
            and (teams[i], teams[j]) not in seen_pairs
            and (teams[j], teams[i]) not in seen_pairs
        ]
        rng.shuffle(candidates)
        for j in candidates:
            if match_counts[teams[i]] >= 8:
                break
            ti, tj = teams[i], teams[j]
            if home_counts[ti] < 4 and away_counts[tj] < 4:
                home, away = ti, tj
            elif home_counts[tj] < 4 and away_counts[ti] < 4:
                home, away = tj, ti
            else:
                continue
            fixtures.append({"home": home, "away": away})
            seen_pairs.add((home, away))
            home_counts[home] += 1
            away_counts[away] += 1
            match_counts[ti] += 1
            match_counts[tj] += 1

    return fixtures


def _poisson_sample(rng: random.Random, mu: float) -> int:
    import math
    L = math.exp(-mu)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def generate_demo_results(
    fixtures: list[dict],
    elos: dict[str, float],
    played_fraction: float = 0.75,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Split fixtures into played (with scores) and remaining."""
    rng = random.Random(seed)
    n_played = int(len(fixtures) * played_fraction)
    shuffled = list(range(len(fixtures)))
    rng.shuffle(shuffled)

    played_indices = set(shuffled[:n_played])
    played: list[dict] = []
    remaining: list[dict] = []

    base_date = dt.date(2024, 9, 17)
    for idx, f in enumerate(fixtures):
        if idx in played_indices:
            eh = elos.get(f["home"], 1500)
            ea = elos.get(f["away"], 1500)
            d = (eh + UCL_HOME_ADV - ea) / 400
            xg_h = max(0.3, 1.35 + 0.8 * d)
            xg_a = max(0.3, 1.35 - 0.8 * d)
            hg = _poisson_sample(rng, xg_h)
            ag = _poisson_sample(rng, xg_a)
            day = base_date + dt.timedelta(days=idx * 2)
            played.append({
                "date": day.isoformat(),
                "home": f["home"],
                "away": f["away"],
                "hg": hg,
                "ag": ag,
            })
        else:
            remaining.append(f)

    return played, remaining


def build_table(played: list[dict], team_names: list[str]) -> list[dict]:
    """Build UCL league phase table from results."""
    from collections import defaultdict
    stats: dict[str, dict] = {
        t: {"played": 0, "won": 0, "drawn": 0, "lost": 0,
            "gf": 0, "ga": 0, "pts": 0}
        for t in team_names
    }
    for m in played:
        h, a = m["home"], m["away"]
        hg, ag = m["hg"], m["ag"]
        if h not in stats or a not in stats:
            continue
        for name, gf, ga in ((h, hg, ag), (a, ag, hg)):
            stats[name]["played"] += 1
            stats[name]["gf"] += gf
            stats[name]["ga"] += ga
        if hg > ag:
            stats[h]["won"] += 1
            stats[h]["pts"] += 3
            stats[a]["lost"] += 1
        elif hg < ag:
            stats[a]["won"] += 1
            stats[a]["pts"] += 3
            stats[h]["lost"] += 1
        else:
            stats[h]["drawn"] += 1
            stats[a]["drawn"] += 1
            stats[h]["pts"] += 1
            stats[a]["pts"] += 1

    rows = [{"name": t, **s, "gd": s["gf"] - s["ga"]} for t, s in stats.items()]
    rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["name"]))
    return rows


def build_ucl_payload(*, demo: bool = False) -> dict:
    teams = UCL_TEAMS_2024
    team_names = [t[0] for t in teams]
    elos = resolve_elos(teams)

    fixtures = generate_league_phase_fixtures(team_names)

    if demo:
        played, remaining = generate_demo_results(fixtures, elos)
    else:
        played = []
        remaining = fixtures

    table = build_table(played, team_names)

    team_list = []
    for name, league in teams:
        team_list.append({
            "name": name,
            "elo": round(elos.get(name, 1500), 2),
            "league": league,
        })
    team_list.sort(key=lambda t: -t["elo"])

    cal_mu = 2.7
    cal_beta = 1.4

    payload = {
        "league": "UCL",
        "name": "UEFA Champions League",
        "generated": dt.datetime.now(dt.timezone.utc).replace(
            microsecond=0).isoformat().replace("+00:00", "Z"),
        "season_start": 2024,
        "format": "swiss",
        "home_advantage_elo": UCL_HOME_ADV,
        "calibration": {"mu_total": cal_mu, "beta": cal_beta},
        "teams": team_list,
        "table": table,
        "played": played,
        "fixtures": remaining,
        "knockout": {
            "auto_qualify": 8,
            "playoff_spots": 16,
            "eliminated_below": 24,
        },
    }

    if demo:
        payload["demo"] = True
        payload["demo_note"] = (
            "Demo dataset — synthetic UCL league phase results. "
            "Real results will replace this once a UCL data source is integrated."
        )

    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="generate demo UCL data with synthetic results")
    args = ap.parse_args()

    payload = build_ucl_payload(demo=args.demo)
    out = DOCS_DATA / "ucl.json"
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"UCL: wrote {out}")
    print(f"  {len(payload['teams'])} teams, {len(payload['played'])} played, "
          f"{len(payload['fixtures'])} remaining fixtures")
    if payload["table"]:
        print(f"  Table leader: {payload['table'][0]['name']} "
              f"({payload['table'][0]['pts']} pts)")
    print(f"  Elo leader: {payload['teams'][0]['name']} "
          f"({payload['teams'][0]['elo']})")


if __name__ == "__main__":
    main()
