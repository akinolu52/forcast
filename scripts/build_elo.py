"""Compute club Elo ratings from cached football-data.co.uk CSVs and emit
a static JSON payload per league for the browser to consume.

Adapted from vishalmysore/webForecast's `scripts/build_elo.py` (MIT).
Key differences from the upstream (which rates national teams):

- One persistent club pool. Ratings survive across seasons.
- Home advantage is fitted per league from the historical home-win rate
  and applied as an additive Elo bonus, matching the World Football Elo
  convention.
- Promoted teams inherit the ratings vacated by relegated teams instead of
  spawning at 1500. This preserves total Elo across the promotion boundary
  and avoids artificial inflation for the previously relegated set.
- Per-round K stays a scalar for domestic league play in M1; UCL knockout
  bonuses land in M6 when European matches join the pool.

Output JSON schema (docs/data/{code}.json):
{
  "league": "EPL",
  "generated": "2026-01-15T09:22:00Z",
  "season": 2025,
  "home_advantage_elo": 65.4,
  "teams": [
    { "name": "Man City", "elo": 1912.3, "last_match": "2026-01-14",
      "history": [{"m": "2020-08", "elo": 1834.1}, ...] }
  ],
  "table": [
    { "name": "Liverpool", "played": 22, "won": 15, "drawn": 4, "lost": 3,
      "gf": 48, "ga": 20, "pts": 49 }
  ],
  "played": [ {"date":"2025-08-16","home":"...","away":"...","hg":2,"ag":1}, ... ],
  "fixtures": [ {"date":"2026-01-20","home":"...","away":"..."}, ... ]
}
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import sys
from collections import defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from leagues import LEAGUES, League  # noqa: E402
import calibrate  # noqa: E402

DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
OUT_DIR = pathlib.Path(__file__).parent.parent / "docs" / "data"

BASE_ELO = 1500.0
PROMOTED_FALLBACK = 1400.0  # used only in the very first ingested season


@dataclass
class TeamState:
    name: str
    elo: float = BASE_ELO
    last_match: str | None = None
    # monthly series: {"2020-08": 1834.1}
    monthly: dict[str, float] = field(default_factory=dict)

    def snapshot(self, when: dt.date) -> None:
        self.monthly[f"{when.year:04d}-{when.month:02d}"] = self.elo


# --- reading -----------------------------------------------------------------

def parse_date(s: str) -> dt.date | None:
    """football-data.co.uk uses DD/MM/YY or DD/MM/YYYY. Return None on empty."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def read_season_csv(path: pathlib.Path) -> list[dict]:
    """Yield played matches for one season, chronologically."""
    matches: list[dict] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = parse_date(row.get("Date", ""))
            home = (row.get("HomeTeam") or "").strip()
            away = (row.get("AwayTeam") or "").strip()
            hg = row.get("FTHG", "")
            ag = row.get("FTAG", "")
            if not (date and home and away):
                continue
            if hg == "" or ag == "":
                continue
            try:
                matches.append({
                    "date": date,
                    "home": home,
                    "away": away,
                    "hg": int(hg),
                    "ag": int(ag),
                })
            except ValueError:
                continue
    matches.sort(key=lambda m: m["date"])
    return matches


def load_all_matches(league: League) -> list[list[dict]]:
    """Return one list per season (in chronological season order)."""
    league_dir = DATA_DIR / league.code
    seasons: list[list[dict]] = []
    if not league_dir.exists():
        return seasons
    for csv_path in sorted(league_dir.glob("*.csv")):
        matches = read_season_csv(csv_path)
        if matches:
            seasons.append(matches)
    return seasons


# --- Elo core ----------------------------------------------------------------

def goal_diff_multiplier(dg: int) -> float:
    """webForecast / World Football Elo goal-difference weighting."""
    a = abs(dg)
    if a <= 1:
        return 1.0
    if a == 2:
        return 1.5
    return (11 + a) / 8.0  # 3→1.75, 4→1.875, 5→2.0, ...


def expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + math.pow(10.0, (rating_b - rating_a) / 400.0))


def update_ratings(
    home: TeamState, away: TeamState, hg: int, ag: int,
    *, k: float, home_adv: float,
) -> None:
    dg = hg - ag
    if dg > 0:
        w_home, w_away = 1.0, 0.0
    elif dg < 0:
        w_home, w_away = 0.0, 1.0
    else:
        w_home, w_away = 0.5, 0.5

    exp_home = expected(home.elo + home_adv, away.elo)
    g = goal_diff_multiplier(dg)
    change = k * g * (w_home - exp_home)
    home.elo += change
    away.elo -= change


def fit_home_advantage(seasons: list[list[dict]]) -> float:
    """Solve for the Elo home-advantage that reproduces the observed
    home-win rate, ignoring draws (matches the World Football Elo
    convention of treating draws as split points)."""
    home_pts = 0.0
    total = 0
    for season in seasons:
        for m in season:
            total += 1
            if m["hg"] > m["ag"]:
                home_pts += 1.0
            elif m["hg"] == m["ag"]:
                home_pts += 0.5
    if total == 0:
        return 0.0
    p_home = home_pts / total
    # p_home = 1 / (1 + 10^(-H/400)) → H = 400 * log10(p / (1-p))
    p_home = min(max(p_home, 0.5001), 0.6999)  # clamp for stability
    return 400.0 * math.log10(p_home / (1.0 - p_home))


# --- between-season handoff --------------------------------------------------

def rollover(
    teams: dict[str, TeamState], prev_season: list[dict],
    new_season: list[dict], *, first: bool,
) -> None:
    """Handle promotion/relegation between two consecutive seasons.

    prev_season_teams = teams in the just-finished season
    new_season_teams  = teams in the season we're about to run

    Departures (relegated set) forfeit their ratings; arrivals (promoted set)
    inherit the mean of the departures. This keeps league mean Elo stable
    across the promotion boundary — a standard club-Elo convention."""
    prev_teams = _teams_in(prev_season) if prev_season else set()
    new_teams = _teams_in(new_season)

    departures = prev_teams - new_teams
    arrivals = new_teams - prev_teams

    if first:
        for name in arrivals:
            teams.setdefault(name, TeamState(name=name, elo=BASE_ELO))
        return

    if not departures:
        for name in arrivals:
            teams.setdefault(name, TeamState(name=name, elo=PROMOTED_FALLBACK))
        return

    dep_mean = sum(teams[n].elo for n in departures) / max(len(departures), 1)
    for name in arrivals:
        teams.setdefault(name, TeamState(name=name, elo=dep_mean))


def _teams_in(matches: list[dict]) -> set[str]:
    s: set[str] = set()
    for m in matches:
        s.add(m["home"])
        s.add(m["away"])
    return s


# --- table + fixtures --------------------------------------------------------

def build_table(matches: list[dict]) -> list[dict]:
    stats: dict[str, dict] = defaultdict(
        lambda: {"played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "pts": 0}
    )
    for m in matches:
        h, a, hg, ag = m["home"], m["away"], m["hg"], m["ag"]
        for name, gf, ga in ((h, hg, ag), (a, ag, hg)):
            r = stats[name]
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
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

    rows = []
    for name, r in stats.items():
        rows.append({"name": name, **r, "gd": r["gf"] - r["ga"]})
    rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["name"]))
    return rows


def collect_fixtures(latest_csv: pathlib.Path) -> list[dict]:
    """Rows with a date but no score are the remaining fixtures. Rare in
    football-data.co.uk (they typically omit unplayed rows), but harmless
    to look for."""
    if not latest_csv.exists():
        return []
    out: list[dict] = []
    with latest_csv.open(newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            date = parse_date(row.get("Date", ""))
            home = (row.get("HomeTeam") or "").strip()
            away = (row.get("AwayTeam") or "").strip()
            if not (date and home and away):
                continue
            if (row.get("FTHG") or "").strip() == "":
                out.append({
                    "date": date.isoformat(),
                    "home": home,
                    "away": away,
                })
    return out


# --- driver ------------------------------------------------------------------

def build_league(league: League) -> dict:
    seasons = load_all_matches(league)
    if not seasons:
        raise SystemExit(
            f"No data for {league.code}. Run `python scripts/fetch_data.py "
            f"--league {league.code}` first."
        )

    home_adv = fit_home_advantage(seasons)

    teams: dict[str, TeamState] = {}
    prev_matches: list[dict] = []
    calibration_samples: list[dict] = []
    calibration_from = max(0, len(seasons) - 2)  # last two seasons
    for i, season_matches in enumerate(seasons):
        rollover(teams, prev_matches, season_matches, first=(i == 0))
        for m in season_matches:
            home = teams[m["home"]]
            away = teams[m["away"]]
            if i >= calibration_from:
                calibration_samples.append({
                    "home_elo": home.elo,
                    "away_elo": away.elo,
                    "hg": m["hg"],
                    "ag": m["ag"],
                })
            update_ratings(
                home, away, m["hg"], m["ag"],
                k=league.k_factor, home_adv=home_adv,
            )
            iso = m["date"].isoformat()
            home.last_match = iso
            away.last_match = iso
            home.snapshot(m["date"])
            away.snapshot(m["date"])
        prev_matches = season_matches

    current = seasons[-1]
    latest_csv = sorted((DATA_DIR / league.code).glob("*.csv"))[-1]
    serialized_teams = _serialize_teams(teams, current)

    # Calibrate (mu_total, beta) from the pre-match Elo snapshots captured
    # during the last two seasons of the pass.
    cal = calibrate.fit_from_samples(calibration_samples, home_adv=home_adv)

    payload = {
        "league": league.code,
        "name": league.name,
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "season_start": int(latest_csv.stem),
        "home_advantage_elo": round(home_adv, 2),
        "calibration": cal.as_dict(),
        "teams": serialized_teams,
        "table": build_table(current),
        "played": [
            {"date": m["date"].isoformat(), "home": m["home"], "away": m["away"], "hg": m["hg"], "ag": m["ag"]}
            for m in current
        ],
        "fixtures": collect_fixtures(latest_csv),
    }
    return payload


def _serialize_teams(teams: dict[str, TeamState], current: list[dict]) -> list[dict]:
    current_names = _teams_in(current)
    out = []
    for name in sorted(current_names):
        t = teams[name]
        history = [{"m": m, "elo": round(v, 1)} for m, v in sorted(t.monthly.items())]
        out.append({
            "name": name,
            "elo": round(t.elo, 2),
            "last_match": t.last_match,
            "history": history,
        })
    out.sort(key=lambda r: -r["elo"])
    return out


def write_output(league: League, payload: dict) -> pathlib.Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{league.code.lower()}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=list(LEAGUES) + ["all"], default="all")
    ap.add_argument("--print-top", type=int, default=10,
                    help="print the top-N teams by Elo after each build")
    args = ap.parse_args()

    codes = [args.league] if args.league != "all" else list(LEAGUES)
    for code in codes:
        league = LEAGUES[code]
        payload = build_league(league)
        path = write_output(league, payload)
        print(f"{league.code}: wrote {path} ({len(payload['teams'])} teams, "
              f"home_adv={payload['home_advantage_elo']} elo)")
        for row in payload["teams"][: args.print_top]:
            print(f"  {row['elo']:7.1f}  {row['name']}")


if __name__ == "__main__":
    main()
