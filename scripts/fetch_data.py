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
    client: httpx.Client, league: League, start_year: int, *, refresh: bool,
    retries: int = 3,
) -> bool:
    """Return True if a fetch happened, False if we used the cache."""
    dest = local_path(league, start_year)
    is_current = start_year == current_season_start()

    if dest.exists() and not refresh and not is_current:
        return False

    url = season_url(league, start_year)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = client.get(url, follow_redirects=True, timeout=30)
            if r.status_code == 404:
                print(f"  [skip] {league.code} {start_year}: 404 (no data yet)")
                return False
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = 2 ** (attempt + 1)
                print(f"  [retry] {league.code} {start_year}: {r.status_code}, waiting {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            break
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < retries:
                wait = 2 ** (attempt + 1)
                print(f"  [retry] {league.code} {start_year}: {e}, waiting {wait}s")
                time.sleep(wait)
            else:
                raise
    else:
        if last_exc:
            raise last_exc

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    print(f"  [ok]   {league.code} {start_year}: {len(r.content):>7} bytes")
    return True


MAX_CONSECUTIVE_FAILURES = 3


def fetch_league(league: League, *, refresh: bool) -> None:
    print(f"Fetching {league.name} ({league.code})")
    end = current_season_start()
    failures = 0
    with httpx.Client(headers={"User-Agent": "forcast/0 (github.com/akinolu52/forcast)"}) as client:
        for start_year in range(league.first_season, end + 1):
            try:
                if fetch_season(client, league, start_year, refresh=refresh):
                    failures = 0
                    time.sleep(0.2)  # be polite to football-data.co.uk
            except httpx.HTTPError as e:
                print(f"  [err]  {league.code} {start_year}: {e}", file=sys.stderr)
                failures += 1
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    print(
                        f"  [abort] {league.code}: {failures} consecutive failures, "
                        f"source looks down — keeping cached seasons",
                        file=sys.stderr,
                    )
                    return


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
