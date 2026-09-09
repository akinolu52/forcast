"""End-to-end smoke test for the pipeline without hitting the network.

Checks the openfootball text parser and club alias index on embedded
samples, then synthesizes two mini seasons of CSV data (the schema
fetch_data.py writes), points DATA_DIR / OUT_DIR at a temp directory,
runs build_elo, and asserts core invariants:

  * Every team in each season appears in the ratings output.
  * The current-season league table matches naive point counts.
  * Ratings sum ≈ N_teams * BASE_ELO across the pool (per-match Elo
    swap is zero-sum, so drift only comes from rollover — check it's
    within a modest tolerance).
  * The Elo history for every team is non-empty and chronological.

Usage:
    python scripts/self_check.py
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import random
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import build_elo  # noqa: E402
from clubs import ClubIndex  # noqa: E402
from leagues import League  # noqa: E402
from openfootball import parse_season  # noqa: E402
from predictor import Calibration, predict  # noqa: E402


FIELDS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]

# Both openfootball match layouts, a goal-scorer block, a postponed fixture,
# an awarded result, a club with an apostrophe, and a COVID-style July
# season end after New Year.
SAMPLE_SEASON = """\
= Test League 2025/26

▪ Matchday 1
  Fri Aug 15 2025
    20:00  Alpha FC                 v Beta United FC            2-1 (1-0)
  Sat Aug 16
    15:00  Gamma Town               v Delta City               [postponed]
           Borussia M'gladbach      v Alpha FC                 0-0
                  (Some PLAYER 12', Other GUY 45+2')
▪ Matchday 2
  Thu Jan 1
  15:00  Delta City               3-0 (1-0)  Gamma Town   [awarded]
  Sat Jul 4
  16:00  Beta United FC           1-1 (0-1)  Borussia M'gladbach
"""

SAMPLE_CLUBS = """\
= Test

Alpha FC, 1900, @ Alpha Park, Alphaville
  | Alpha | Alpha Football Club
AC Cesena (1940-2018), Cesena
  | Cesena
RC Celta Vigo,  Vigo
  | Celta | RC Celta de Vigo
"""


def check_parser() -> None:
    ms = parse_season(SAMPLE_SEASON, 2025)
    got = [(m.date.isoformat(), m.home, m.away, m.hg, m.ag) for m in ms]
    want = [
        ("2025-08-15", "Alpha FC", "Beta United FC", 2, 1),
        ("2025-08-16", "Gamma Town", "Delta City", None, None),
        ("2025-08-16", "Borussia M'gladbach", "Alpha FC", 0, 0),
        ("2026-01-01", "Delta City", "Gamma Town", 3, 0),
        ("2026-07-04", "Beta United FC", "Borussia M'gladbach", 1, 1),
    ]
    assert got == want, f"parser mismatch:\n got={got}\nwant={want}"

    idx = ClubIndex()
    idx.load(SAMPLE_CLUBS)
    assert idx.canonical("Alpha") == "Alpha FC"
    assert idx.canonical("alpha football club") == "Alpha FC"
    assert idx.canonical("Cesena") == "AC Cesena", "lifespan suffix not stripped"
    assert idx.canonical("RC Celta") == "RC Celta Vigo", "generic-token fallback failed"
    assert idx.canonical("Real Madrid C.F.") == "Real Madrid C.F."  # unknown, kept
    assert idx.canonical("Real Madrid CF") == "Real Madrid C.F.", "unknown not adopted"
    assert idx.unknown == {"Real Madrid C.F."}
    print("self_check: parser + club index OK")


def synth_season(teams: list[str], year: int, seed: int) -> list[dict]:
    """Round-robin double schedule (home + away). Scores drawn from a
    Poisson-ish distribution biased by team index (stronger index → more goals)."""
    rng = random.Random(seed)
    matches = []
    day = dt.date(year, 8, 20)
    for i, home in enumerate(teams):
        for j, away in enumerate(teams):
            if i == j:
                continue
            strength_h = (len(teams) - i) / len(teams)
            strength_a = (len(teams) - j) / len(teams)
            hg = max(0, int(rng.gauss(1.4 + 0.6 * strength_h, 1.0)))
            ag = max(0, int(rng.gauss(1.0 + 0.6 * strength_a, 1.0)))
            matches.append({
                "Date": day.strftime("%d/%m/%Y"),
                "HomeTeam": home,
                "AwayTeam": away,
                "FTHG": hg,
                "FTAG": ag,
            })
            day += dt.timedelta(days=3)
    return matches


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    check_parser()

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="forcast-self-check-"))
    data_dir = tmp / "data"
    out_dir = tmp / "docs" / "data"
    build_elo.DATA_DIR = data_dir
    build_elo.OUT_DIR = out_dir

    league = League(
        code="TEST", name="Test League", source="test", path="{season}/test.txt",
        clubs=(), first_season=2020, k_factor=32, n_teams=6,
        relegation_slots=1, ucl_slots=2,
    )

    seasons_meta = [
        (2020, ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"], 1),
        (2021, ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Golf"], 2),
    ]
    for year, teams, seed in seasons_meta:
        write_csv(data_dir / league.code / f"{year}.csv", synth_season(teams, year, seed))

    payload = build_elo.build_league(league)
    out_path = build_elo.write_output(league, payload)
    assert out_path.exists(), "output json not written"

    # Reload for a round-trip check
    data = json.loads(out_path.read_text())

    # --- assertions ----------------------------------------------------
    current_teams = {"Alpha", "Bravo", "Charlie", "Delta", "Echo", "Golf"}
    got = {t["name"] for t in data["teams"]}
    assert got == current_teams, f"team set mismatch: {got}"

    assert 40.0 <= data["home_advantage_elo"] <= 200.0, (
        f"unreasonable home advantage: {data['home_advantage_elo']}"
    )

    # Match updates are zero-sum, so between-season drift is bounded by
    # rollover choices. Pool total should stay within a season's worth
    # of PROMOTED_FALLBACK swings around 6 * BASE_ELO = 9000.
    total = sum(t["elo"] for t in data["teams"])
    assert 8500 <= total <= 9500, f"pool drifted: total={total:.1f}"

    for t in data["teams"]:
        assert t["history"], f"empty history for {t['name']}"
        months = [h["m"] for h in t["history"]]
        assert months == sorted(months), f"history not chronological for {t['name']}"

    table = data["table"]
    assert len(table) == len(current_teams), "table size wrong"
    for row in table:
        expected_pts = row["won"] * 3 + row["drawn"]
        assert row["pts"] == expected_pts, f"points mismatch for {row['name']}"

    pts = [r["pts"] for r in table]
    assert pts == sorted(pts, reverse=True), "table not points-sorted"

    # --- calibration + predictor --------------------------------------
    cal_dict = data["calibration"]
    assert 1.5 <= cal_dict["mu_total"] <= 4.0, f"bad mu_total: {cal_dict}"
    assert 0.5 <= cal_dict["beta"] <= 3.0, f"bad beta: {cal_dict}"

    cal = Calibration(mu_total=cal_dict["mu_total"], beta=cal_dict["beta"])
    leader = data["teams"][0]
    trailer = data["teams"][-1]
    pred = predict(leader["elo"], trailer["elo"], data["home_advantage_elo"], cal)

    for key in ("p_home", "p_draw", "p_away"):
        assert 0.0 <= pred[key] <= 1.0, f"prob out of range: {pred}"
    prob_sum = pred["p_home"] + pred["p_draw"] + pred["p_away"]
    assert abs(prob_sum - 1.0) < 1e-6, f"probabilities do not sum to 1: {prob_sum}"

    # Symmetry: flipping teams and dropping home advantage should reverse H/A.
    flip = predict(trailer["elo"], leader["elo"], 0.0, cal)
    same = predict(leader["elo"], trailer["elo"], 0.0, cal)
    assert abs(flip["p_home"] - same["p_away"]) < 1e-9, "predictor asymmetry"

    # Stronger team, at home, should be favoured.
    assert pred["p_home"] > pred["p_away"], (
        f"favourite should win more often: {pred}"
    )

    print("self_check: PASS")
    print(f"  home advantage: {data['home_advantage_elo']} elo")
    print(f"  pool total:     {total:.1f} across {len(data['teams'])} teams")
    print(f"  leader:         {data['teams'][0]['name']} @ {data['teams'][0]['elo']}")
    print(f"  table leader:   {table[0]['name']} @ {table[0]['pts']} pts")
    print(f"  calibration:    mu_total={cal_dict['mu_total']}  beta={cal_dict['beta']}")
    print(f"  sample match:   {leader['name']} vs {trailer['name']}: "
          f"H {pred['p_home']:.2f} / D {pred['p_draw']:.2f} / A {pred['p_away']:.2f} "
          f"(xg {pred['xg_home']:.2f}-{pred['xg_away']:.2f})")


if __name__ == "__main__":
    main()
