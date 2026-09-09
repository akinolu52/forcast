"""Parser for openfootball's plain-text match files.

openfootball (github.com/openfootball) publishes results for every major
league as human-readable text, one file per season. Two match-line layouts
occur across eras and both are handled:

    15:00  Charlton Athletic        4-0 (2-0)  Manchester City      # pre-2020
    20:00  Arsenal FC               v Coventry City FC   3-0 (2-0) # 2020+

Unplayed fixtures are the second form without a score. Date lines carry an
explicit year only on the first date of a section; the rest are inferred by
watching the month roll over. Goal-scorer blocks, matchday headers and
comments are ignored.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

_DOW = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

_DATE_RE = re.compile(rf"^\s*{_DOW}\s+([A-Z][a-z]{{2}})\s+(\d{{1,2}})(?:\s+(\d{{4}}))?\s*$")
_TIME = r"(?:\d{1,2}[:.]\d{2}\s+)?"
_SCORE = r"(\d+)-(\d+)(?:\s*\(\d+-\d+\))?"
_STATUS = r"(?:\s+\[(\w+)\]|\s+(postponed|cancelled|canceled|abandoned|awarded))?"
# "A v B  H-A (h-a)" or "A v B" (fixture), optionally followed by a status tag.
_V_RE = re.compile(rf"^\s*{_TIME}(.+?)\s+v\s+(.+?)(?:\s+{_SCORE})?{_STATUS}\s*$")
# "A  H-A (h-a)  B"
_INLINE_RE = re.compile(rf"^\s*{_TIME}(.+?)\s+{_SCORE}\s+(.+?){_STATUS}\s*$")
_SKIP_STATUS = {"cancelled", "canceled", "abandoned", "void"}
_MINUTE_MARK = re.compile(r"\d'")  # goal-scorer lines: "Harry KANE 64', 74'"


def _resolve_date(mon: int, day: int, explicit_year: int | None,
                  season_start: int, last: dt.date | None) -> dt.date | None:
    """Files are ordered by matchday, not date, so the year can't be inferred
    from month roll-over. Sep-Dec belong to the season's first year, Jan-Jun
    to the second. Jul/Aug is normally the season start, but the COVID
    seasons finished in July/August: postponements only ever move a match
    later, so if we've already passed New Year it must be the season end."""
    if explicit_year:
        year = explicit_year
    elif mon >= 9:
        year = season_start
    elif mon <= 6:
        year = season_start + 1
    elif last is not None and last.year > season_start:
        year = season_start + 1
    else:
        year = season_start
    try:
        return dt.date(year, mon, day)
    except ValueError:
        return None


@dataclass
class Match:
    date: dt.date
    home: str
    away: str
    hg: int | None  # None → unplayed fixture
    ag: int | None


def parse_season(text: str, season_start: int) -> list[Match]:
    matches: list[Match] = []
    date: dt.date | None = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith(("#", "=", "▪", "»", "(")):
            continue

        m = _DATE_RE.match(line)
        if m:
            mon = _MONTHS.get(m.group(1))
            if mon is None:
                continue
            explicit = int(m.group(3)) if m.group(3) else None
            date = _resolve_date(mon, int(m.group(2)), explicit, season_start, date)
            continue

        if date is None or _MINUTE_MARK.search(line):
            continue

        m = _V_RE.match(line)
        if m:
            home, away, hg, ag, bracket_tag, word_tag = m.groups()
            tag = (bracket_tag or word_tag or "").lower()
            if tag in _SKIP_STATUS:
                continue
            matches.append(Match(
                date, home.strip(), away.strip(),
                int(hg) if hg is not None else None,
                int(ag) if ag is not None else None,
            ))
            continue

        m = _INLINE_RE.match(line)
        if m:
            home, hg, ag, away, bracket_tag, word_tag = m.groups()
            if (bracket_tag or word_tag or "").lower() in _SKIP_STATUS:
                continue
            matches.append(Match(date, home.strip(), away.strip(), int(hg), int(ag)))

    return matches
