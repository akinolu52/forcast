"""Download match results from openfootball and normalise them to CSV.

Source: https://github.com/openfootball — one plain-text file per league
per season, served from raw.githubusercontent.com, plus club alias tables
under openfootball/clubs. Each season is parsed and written as
data/{league}/{year}.csv with columns Date,HomeTeam,AwayTeam,FTHG,FTAG
(unplayed fixtures have empty scores), which is what build_elo.py reads.

Finished seasons never change, so they are cached once. The current
season is always re-fetched (results are appended week to week).

Usage:
    python scripts/fetch_data.py                # all leagues, all seasons
    python scripts/fetch_data.py --league EPL   # just EPL
    python scripts/fetch_data.py --refresh      # re-download every season
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import sys
import time

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from clubs import ClubIndex  # noqa: E402
from leagues import LEAGUES, League, season_dir  # noqa: E402
from openfootball import Match, parse_season  # noqa: E402

BASE = "https://raw.githubusercontent.com/openfootball"
CLUBS_BASE = f"{BASE}/clubs/master/europe"
DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
FIELDS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]

MAX_CONSECUTIVE_FAILURES = 2


class SourceDown(Exception):
    """Every file lives on the same host, so once a couple of fetches in a
    row have failed (each already retried with backoff) there is no point
    asking for the next one either."""


def current_season_start() -> int:
    """European season starts in August. Everything before August belongs
    to the season that started the previous calendar year."""
    today = dt.date.today()
    return today.year if today.month >= 8 else today.year - 1


def season_url(league: League, start_year: int) -> str:
    return f"{BASE}/{league.source}/master/{league.path.format(season=season_dir(start_year))}"


def local_path(league: League, start_year: int) -> pathlib.Path:
    return DATA_DIR / league.code / f"{start_year}.csv"


def get(client: httpx.Client, url: str, label: str, retries: int = 3) -> httpx.Response | None:
    """GET with exponential backoff on transient errors. None on 404."""
    for attempt in range(retries + 1):
        try:
            r = client.get(url, follow_redirects=True, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = 2 ** (attempt + 1)
                print(f"  [retry] {label}: {r.status_code}, waiting {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:
            if attempt >= retries:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  [retry] {label}: {e}, waiting {wait}s")
            time.sleep(wait)
    raise AssertionError("unreachable")


def load_club_index(client: httpx.Client, league: League) -> ClubIndex:
    """Alias tables are tiny and change rarely: always try the live copy,
    fall back to the cached one if the fetch fails."""
    index = ClubIndex()
    for rel in league.clubs:
        cache = DATA_DIR / "clubs" / rel
        try:
            r = get(client, f"{CLUBS_BASE}/{rel}", f"clubs {rel}")
            if r is None:
                raise httpx.HTTPError(f"404 for clubs/{rel}")
            text = r.text
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
        except httpx.HTTPError:
            if not cache.exists():
                raise
            print(f"  [cache] clubs {rel}: using cached copy", file=sys.stderr)
            text = cache.read_text(encoding="utf-8")
        index.load(text)
    return index


def write_csv(path: pathlib.Path, matches: list[Match]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for m in sorted(matches, key=lambda m: m.date):
            w.writerow([
                m.date.isoformat(), m.home, m.away,
                "" if m.hg is None else m.hg,
                "" if m.ag is None else m.ag,
            ])


def fetch_season(
    client: httpx.Client, league: League, index: ClubIndex, start_year: int,
    *, refresh: bool,
) -> bool:
    """Return True if a fetch happened, False if we used the cache."""
    dest = local_path(league, start_year)
    is_current = start_year == current_season_start()
    if dest.exists() and not refresh and not is_current:
        return False

    label = f"{league.code} {start_year}"
    r = get(client, season_url(league, start_year), label)
    if r is None:
        print(f"  [skip] {label}: 404 (no data yet)")
        return False

    matches = parse_season(r.text, start_year)
    if not matches:
        print(f"  [warn] {label}: fetched but no matches parsed", file=sys.stderr)
        return False
    for m in matches:
        m.home = index.canonical(m.home)
        m.away = index.canonical(m.away)

    write_csv(dest, matches)
    played = sum(1 for m in matches if m.hg is not None)
    print(f"  [ok]   {label}: {played:3d} results, {len(matches) - played:3d} fixtures")
    return True


def fetch_league(league: League, *, refresh: bool, failures: int = 0) -> int:
    """Return the running count of consecutive failed fetches so the caller
    can carry it across leagues."""
    print(f"Fetching {league.name} ({league.code})")
    end = current_season_start()
    with httpx.Client(headers={"User-Agent": "forcast/0 (github.com/akinolu52/forcast)"}) as client:
        try:
            index = load_club_index(client, league)
        except httpx.HTTPError as e:
            print(f"  [err]  {league.code} clubs: {e}", file=sys.stderr)
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                raise SourceDown(f"{failures} consecutive fetches failed (last: {league.code} clubs)") from e
            return failures

        for start_year in range(league.first_season, end + 1):
            try:
                if fetch_season(client, league, index, start_year, refresh=refresh):
                    failures = 0
                    time.sleep(0.2)
            except httpx.HTTPError as e:
                print(f"  [err]  {league.code} {start_year}: {e}", file=sys.stderr)
                failures += 1
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    raise SourceDown(
                        f"{failures} consecutive fetches failed (last: {league.code} {start_year})"
                    ) from e

    if index.unknown:
        names = sorted(index.unknown)
        print(f"  [note] {len(names)} club name(s) not in alias tables, kept as-is: "
              f"{', '.join(names[:8])}{' …' if len(names) > 8 else ''}")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=list(LEAGUES) + ["all"], default="all")
    ap.add_argument("--refresh", action="store_true", help="re-download even cached seasons")
    args = ap.parse_args()

    codes = [args.league] if args.league != "all" else list(LEAGUES)
    failures = 0
    for code in codes:
        try:
            failures = fetch_league(LEAGUES[code], refresh=args.refresh, failures=failures)
        except SourceDown as e:
            print(f"[abort] {e}; giving up on openfootball for this run — "
                  f"building from cached seasons", file=sys.stderr)
            break


if __name__ == "__main__":
    main()
