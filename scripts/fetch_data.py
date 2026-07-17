"""Download historical results from football-data.co.uk.

CSV layout: https://www.football-data.co.uk/mmz4281/{season_tag}/{fd_code}.csv
Older seasons never change, so we cache them once. The current season is
always re-fetched (its file grows week to week).

Usage:
    python scripts/fetch_data.py                # all leagues, all seasons
    python scripts/fetch_data.py --league EPL   # just EPL
    python scripts/fetch_data.py --refresh      # re-download every season
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys
import time

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from leagues import LEAGUES, League, season_tag  # noqa: E402

BASE = "https://www.football-data.co.uk/mmz4281"
DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


def current_season_start() -> int:
    """European season starts in August. Everything before August belongs
    to the season that started the previous calendar year."""
    today = dt.date.today()
    return today.year if today.month >= 8 else today.year - 1


def season_url(league: League, start_year: int) -> str:
    return f"{BASE}/{season_tag(start_year)}/{league.fd_code}.csv"


def local_path(league: League, start_year: int) -> pathlib.Path:
    return DATA_DIR / league.code / f"{start_year}.csv"


def fetch_season(
    client: httpx.Client, league: League, start_year: int, *, refresh: bool
) -> bool:
    """Return True if a fetch happened, False if we used the cache."""
    dest = local_path(league, start_year)
    is_current = start_year == current_season_start()

    if dest.exists() and not refresh and not is_current:
        return False

    url = season_url(league, start_year)
    r = client.get(url, follow_redirects=True, timeout=30)
    if r.status_code == 404:
        print(f"  [skip] {league.code} {start_year}: 404 (no data yet)")
        return False
    r.raise_for_status()

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    print(f"  [ok]   {league.code} {start_year}: {len(r.content):>7} bytes")
    return True


def fetch_league(league: League, *, refresh: bool) -> None:
    print(f"Fetching {league.name} ({league.code})")
    end = current_season_start()
    with httpx.Client(headers={"User-Agent": "forcast/0 (github.com/akinolu52/forcast)"}) as client:
        for start_year in range(league.first_season, end + 1):
            try:
                if fetch_season(client, league, start_year, refresh=refresh):
                    time.sleep(0.2)  # be polite to football-data.co.uk
            except httpx.HTTPError as e:
                print(f"  [err]  {league.code} {start_year}: {e}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=list(LEAGUES) + ["all"], default="all")
    ap.add_argument("--refresh", action="store_true", help="re-download even cached seasons")
    args = ap.parse_args()

    codes = [args.league] if args.league != "all" else list(LEAGUES)
    for code in codes:
        fetch_league(LEAGUES[code], refresh=args.refresh)


if __name__ == "__main__":
    main()
