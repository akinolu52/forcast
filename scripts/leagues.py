"""Static config for every league we forecast.

Kept minimal — anything computed (home advantage, calibration coefficients)
is fitted from the data by `build_elo.py`, not hardcoded here.

Match data comes from openfootball (github.com/openfootball): one text file
per season per league, plus per-country club alias tables so a club keeps
one identity even when the source spells its name differently year to year.
`first_season` is the earliest season the source covers for that league.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    code: str            # our internal code, also the filename stem
    name: str            # display name
    source: str          # openfootball repository name
    path: str            # season file inside the repo; {season} → "2026-27"
    clubs: tuple[str, ...]  # alias tables under openfootball/clubs/europe
    first_season: int    # first 4-digit start year we ingest (2000 → 2000/01)
    k_factor: int        # base K for domestic league matches
    n_teams: int         # league size (used for table sanity checks)
    relegation_slots: int
    ucl_slots: int       # top-N qualify for UCL (approximate; ignores cup routes)


LEAGUES: dict[str, League] = {
    "EPL": League(
        code="EPL",
        name="English Premier League",
        source="england",
        path="{season}/1-premierleague.txt",
        clubs=("england/eng.clubs.txt", "wales/wal.clubs.txt"),
        first_season=2000,
        k_factor=32,
        n_teams=20,
        relegation_slots=3,
        ucl_slots=4,
    ),
    "LaLiga": League(
        code="LaLiga",
        name="Spanish La Liga",
        source="espana",
        path="{season}/1-liga.txt",
        clubs=("spain/es.clubs.txt",),
        first_season=2012,
        k_factor=32,
        n_teams=20,
        relegation_slots=3,
        ucl_slots=4,
    ),
    "SerieA": League(
        code="SerieA",
        name="Italian Serie A",
        source="italy",
        path="{season}/1-seriea.txt",
        clubs=("italy/it.clubs.txt",),
        first_season=2013,
        k_factor=32,
        n_teams=20,
        relegation_slots=3,
        ucl_slots=4,
    ),
    "Bundesliga": League(
        code="Bundesliga",
        name="German Bundesliga",
        source="deutschland",
        path="{season}/1-bundesliga.txt",
        clubs=("germany/de.clubs.txt",),
        first_season=2010,
        k_factor=32,
        n_teams=18,
        relegation_slots=2,   # 16 stays + 2 down + 1 playoff — approximation
        ucl_slots=4,
    ),
    "Ligue1": League(
        code="Ligue1",
        name="French Ligue 1",
        source="france",
        path="france/{season}_fr1.txt",
        clubs=("france/fr.clubs.txt", "monaco/mc.clubs.txt"),
        first_season=2014,
        k_factor=32,
        n_teams=18,          # since 2023/24; historical seasons had 20
        relegation_slots=2,
        ucl_slots=3,
    ),
}


def season_dir(start_year: int) -> str:
    """2026 → '2026-27' (openfootball directory scheme)."""
    return f"{start_year}-{(start_year + 1) % 100:02d}"
