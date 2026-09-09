"""Canonical club names from openfootball/clubs alias lists.

openfootball's match files are not consistent about club names across
seasons ("Liverpool" one year, "Liverpool FC" the next). Elo needs one
identity per club, so every name is mapped through the alias tables
openfootball maintains alongside the data:

    Manchester City FC, 1880, @ Etihad Stadium, Manchester
      | Man City | Manchester City | Man. City | Manchester C.

The first comma-separated field of a header line is the canonical name;
indented "|" lines list aliases.
"""

from __future__ import annotations

import re
import unicodedata


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace(".", "")  # "Real Madrid C.F." == "Real Madrid CF"
    return re.sub(r"\s+", " ", s).strip().casefold()


_ALIAS_TAG = re.compile(r"\s*\[[a-z]{2}\]\s*$")  # "Ath Madrid [en]"
_SUBENTRY = re.compile(r"^(?:i{1,3}|iv|v)\)\s*")   # "ii) Atlético Madrid B"
_LIFESPAN = re.compile(r"\s*\(\d{4}-\d{4}\)\s*$")   # "AC Cesena (1940-2018)"

# Club-form tokens that openfootball adds or drops between seasons. Only used
# as a second-chance match for names the alias tables don't list verbatim.
_GENERIC = {
    "fc", "afc", "cf", "ac", "as", "sc", "ss", "ssc", "us", "ca", "cd", "sd",
    "ud", "rc", "rcd", "sv", "ev", "club", "calcio", "de", "di", "da",
}


def _strip_generic(key: str) -> str:
    words = [w for w in key.split() if w not in _GENERIC]
    return " ".join(words) or key


class ClubIndex:
    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._loose: dict[str, str] = {}
        self.unknown: set[str] = set()

    def load(self, text: str) -> None:
        canonical: str | None = None
        for raw in text.splitlines():
            line = raw.split("##")[0].rstrip()
            if not line.strip() or line.lstrip().startswith(("#", "=")):
                continue
            if line.lstrip().startswith("|"):
                if canonical is None:
                    continue
                for alias in line.split("#")[0].split("|"):
                    alias = _ALIAS_TAG.sub("", alias).strip()
                    if alias:
                        self._add(alias, canonical)
                continue
            head = _SUBENTRY.sub("", line.strip())
            canonical = _LIFESPAN.sub("", head.split(",")[0].split("#")[0]).strip()
            if canonical:
                self._add(canonical, canonical)

    def _add(self, name: str, canonical: str) -> None:
        key = _norm(name)
        self._map.setdefault(key, canonical)
        self._loose.setdefault(_strip_generic(key), canonical)

    def canonical(self, name: str) -> str:
        key = _norm(name)
        hit = self._map.get(key) or self._loose.get(_strip_generic(key))
        if hit is None:
            # Not in any alias table: adopt this spelling as canonical so
            # later variants ("X" vs "X FC") still resolve to one club.
            hit = name.strip()
            self._add(hit, hit)
            self.unknown.add(hit)
        return hit
