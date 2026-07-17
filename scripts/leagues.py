"""Static config for every league we forecast.

Kept minimal — anything computed (home advantage, calibration coefficients)
is fitted from the data by `build_elo.py`, not hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    code: str          # our internal code, also the filename stem
    name: str          # display name
    fd_code: str       # football-data.co.uk file code (E0, SP1, ...)
    first_season: int  # first 4-digit start year we ingest (1993 → 1993/94)
    k_factor: int      # base K for domestic league matches
    n_teams: int       # league size (used for table sanity checks)
    relegation_slots: int
    ucl_slots: int     # top-N qualify for UCL (approximate; ignores cup routes)


LEAGUES: dict[str, League] = {
    "EPL": League(
        code="EPL",
        name="English Premier League",
        fd_code="E0",
        first_season=1995,
        k_factor=32,
        n_teams=20,
        relegation_slots=3,
        ucl_slots=4,
    ),
    "LaLiga": League(
        code="LaLiga",
        name="Spanish La Liga",
        fd_code="SP1",
        first_season=1995,
        k_factor=32,
        n_teams=20,
        relegation_slots=3,
        ucl_slots=4,
    ),
    "SerieA": League(
        code="SerieA",
        name="Italian Serie A",
        fd_code="I1",
        first_season=1995,
        k_factor=32,
        n_teams=20,
        relegation_slots=3,
        ucl_slots=4,
    ),
    "Bundesliga": League(
        code="Bundesliga",
        name="German Bundesliga",
        fd_code="D1",
        first_season=1995,
        k_factor=32,
        n_teams=18,
        relegation_slots=2,   # 16 stays + 2 down + 1 playoff — approximation
        ucl_slots=4,
    ),
    "Ligue1": League(
        code="Ligue1",
        name="French Ligue 1",
        fd_code="F1",
        first_season=1995,
        k_factor=32,
        n_teams=18,          # since 2023/24; historical seasons had 20
        relegation_slots=2,
        ucl_slots=3,
    ),
}


def season_tag(start_year: int) -> str:
    """1995 → '9596', 2024 → '2425' (football-data.co.uk directory scheme)."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
