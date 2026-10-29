"""Resolve a typed ship name to a match, a candidate list, or nothing.

Ported from the current bot ``resolve.ts``: exact hits are auto-submitted only
when unique, safe one-character typos in Chinese/pinyin are auto-corrected,
and everything else becomes a candidate list for ``/1`` confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import Ship
from .search import (
    MAX_SHIP_QUERY_LENGTH,
    ShipSearchHit,
    ShipSearchIndex,
    build_ship_search_index,
    normalize_ship_query,
    search_ships,
)

FuzzyMode = Literal["auto", "suggest", "off"]

MAX_FUZZY_CANDIDATES = 2
CANDIDATE_SCORE_GAP = 0.15


@dataclass(frozen=True)
class ResolveMatch:
    ship: Ship
    reason: Literal["exact", "typo"]


@dataclass(frozen=True)
class ResolveCandidates:
    candidates: tuple[Ship, ...]


ResolveResult = ResolveMatch | ResolveCandidates | None

_INDEX_CACHE: dict[int, tuple[list[Ship], ShipSearchIndex]] = {}


def _index_for(ships: list[Ship]) -> ShipSearchIndex:
    cached = _INDEX_CACHE.get(id(ships))
    if cached is not None and cached[0] is ships:
        return cached[1]
    index = build_ship_search_index(ships)
    _INDEX_CACHE[id(ships)] = (ships, index)
    return index


def _choose_candidates(
    exact: list[ShipSearchHit],
    fuzzy: list[ShipSearchHit],
    limit: int,
) -> list[Ship]:
    if exact:
        return [hit.ship for hit in exact[:limit]]
    if not fuzzy:
        return []
    top = fuzzy[0]
    return [
        hit.ship
        for hit in fuzzy
        if top.score - hit.score <= CANDIDATE_SCORE_GAP
    ][: min(MAX_FUZZY_CANDIDATES, limit)]


def _exact_auto_allowed(hit: ShipSearchHit, query_length: int) -> bool:
    return not (hit.key == "pinyinInitials" and query_length < 3)


def _is_safe_typo(
    hit: ShipSearchHit,
    second: ShipSearchHit | None,
    query_length: int,
) -> bool:
    if hit.key not in {"nameZh", "pinyin"}:
        return False
    if hit.distance != 1 or hit.query_length != hit.key_length:
        return False
    if hit.window_length != hit.key_length:
        return False
    if hit.score < 0.65:
        return False
    if hit.score - (second.score if second else 0) < 0.15:
        return False
    return query_length >= 3 if hit.key == "nameZh" else query_length >= 4


def resolve_ship(
    ships: list[Ship],
    query: str,
    mode: FuzzyMode = "auto",
    max_candidates: int = 3,
) -> ResolveResult:
    limit = max(1, max_candidates)
    normalized = normalize_ship_query(query)
    if not normalized or len(normalized) > MAX_SHIP_QUERY_LENGTH:
        return None

    query_length = len(normalized)
    result = search_ships(
        _index_for(ships),
        normalized,
        max(limit + 2, 5),
    )
    candidates = _choose_candidates(result.exact, result.fuzzy, limit)

    if result.exact:
        if len(result.exact) == 1 and _exact_auto_allowed(result.exact[0], query_length):
            return ResolveMatch(ship=result.exact[0].ship, reason="exact")
        return ResolveCandidates(candidates=tuple(candidates)) if candidates else None

    if mode == "off" or not result.fuzzy:
        return None

    top = result.fuzzy[0]
    if mode == "auto" and _is_safe_typo(top, result.fuzzy[1] if len(result.fuzzy) > 1 else None, query_length):
        return ResolveMatch(ship=top.ship, reason="typo")

    return ResolveCandidates(candidates=tuple(candidates)) if candidates else None
