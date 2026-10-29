"""Ship-name search for the bot.

Ported from ``packages/shared/src/search.ts``. The client dropdown uses the
simpler ``matchShips``; this stricter index is what the bot uses to decide
between an exact match, a safe typo, and a candidate list.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from .models import Ship

MAX_SHIP_QUERY_LENGTH = 40
MIN_CANDIDATE_SCORE = 0.5

ShipSearchKey = str  # nameZh | pinyin | pinyinInitials | name | index
ShipSearchPosition = str  # whole | prefix | suffix | middle

KEY_PRIORITY = {
    "nameZh": 5,
    "pinyin": 4,
    "pinyinInitials": 3,
    "name": 2,
    "index": 1,
}
KEY_WEIGHT = {
    "nameZh": 1.0,
    "pinyin": 0.98,
    "pinyinInitials": 0.92,
    "name": 0.95,
    "index": 0.7,
}

_HAN_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x30000, 0x3134F),
)


def _is_han(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in _HAN_RANGES)


def _has_han(text: str) -> bool:
    return any(_is_han(char) for char in text)


def normalize_ship_query(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("M"):
            continue
        if char.isspace() or category[0] in {"P", "S"}:
            continue
        kept.append(char)
    return "".join(kept)


@dataclass(frozen=True)
class ShipSearchHit:
    ship: Ship
    key: ShipSearchKey
    score: float
    exact: bool
    query_length: int
    key_length: int
    window_length: int
    position: ShipSearchPosition
    distance: int | None


@dataclass
class ShipSearchResult:
    exact: list[ShipSearchHit]
    fuzzy: list[ShipSearchHit]


@dataclass
class ShipSearchIndex:
    ships: list[Ship]
    exact: dict[str, list[ShipSearchHit]]
    entries: list[tuple[Ship, ShipSearchKey, str]]


def damerau_levenshtein(a: str, b: str, max_distance: int | None = None) -> int:
    """Optimal-string-alignment distance with adjacent transposition."""
    if a == b:
        return 0
    ac = list(a)
    bc = list(b)
    max_value = max_distance if max_distance is not None else 10**9
    if abs(len(ac) - len(bc)) > max_value:
        return max_value + 1

    n = len(bc)
    prev2: list[int] | None = None
    prev = list(range(n + 1))
    for i in range(1, len(ac) + 1):
        cur = [0] * (n + 1)
        cur[0] = i
        row_min = i
        for j in range(1, n + 1):
            cost = 0 if ac[i - 1] == bc[j - 1] else 1
            value = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (
                prev2 is not None
                and i > 1
                and j > 1
                and ac[i - 1] == bc[j - 2]
                and ac[i - 2] == bc[j - 1]
            ):
                value = min(value, prev2[j - 2] + 1)
            cur[j] = value
            if value < row_min:
                row_min = value
        if row_min > max_value:
            return max_value + 1
        prev2 = prev
        prev = cur
    return prev[n]


def _keys_of(ship: Ship) -> Iterable[tuple[ShipSearchKey, str]]:
    if ship.name_zh:
        yield "nameZh", ship.name_zh
    if ship.pinyin:
        yield "pinyin", ship.pinyin
    if ship.pinyin_initials:
        yield "pinyinInitials", ship.pinyin_initials
    if ship.name:
        yield "name", ship.name
    if ship.index:
        yield "index", ship.index


def build_ship_search_index(ships: list[Ship]) -> ShipSearchIndex:
    exact: dict[str, list[ShipSearchHit]] = {}
    entries: list[tuple[Ship, ShipSearchKey, str]] = []

    for ship in ships:
        for key, raw in _keys_of(ship):
            value = normalize_ship_query(raw)
            if not value:
                continue
            entries.append((ship, key, value))
            length = len(value)
            hit = ShipSearchHit(
                ship=ship,
                key=key,
                score=1.0,
                exact=True,
                query_length=length,
                key_length=length,
                window_length=length,
                position="whole",
                distance=0,
            )
            exact.setdefault(value, []).append(hit)

    return ShipSearchIndex(ships=ships, exact=exact, entries=entries)


def _name_of(ship: Ship) -> str:
    return ship.name_zh or ship.name


def _dedupe_exact(hits: list[ShipSearchHit]) -> list[ShipSearchHit]:
    best: dict[str, ShipSearchHit] = {}
    for hit in hits:
        previous = best.get(hit.ship.index)
        if previous is None or KEY_PRIORITY[hit.key] > KEY_PRIORITY[previous.key]:
            best[hit.ship.index] = hit
    return sorted(
        best.values(),
        key=lambda hit: (
            -KEY_PRIORITY[hit.key],
            _name_of(hit.ship).casefold(),
        ),
    )


def _is_subsequence(query: str, key: str) -> bool:
    q = list(query)
    if len(q) > len(key):
        return False
    position = 0
    for char in key:
        if position < len(q) and char == q[position]:
            position += 1
        if position == len(q):
            return True
    return len(q) == 0


@dataclass(frozen=True)
class _WindowMatch:
    distance: int
    window_length: int
    position: ShipSearchPosition
    similarity: float


def _better_window(candidate: _WindowMatch, best: _WindowMatch, query_length: int) -> bool:
    if candidate.similarity != best.similarity:
        return candidate.similarity > best.similarity
    candidate_diff = abs(candidate.window_length - query_length)
    best_diff = abs(best.window_length - query_length)
    if candidate_diff != best_diff:
        return candidate_diff < best_diff
    if candidate.distance != best.distance:
        return candidate.distance < best.distance
    if candidate.position == "middle" and best.position != "middle":
        return False
    return best.position == "middle" and candidate.position != "middle"


def _best_window_match(
    query: str,
    key: str,
    query_length: int,
    key_length: int,
) -> _WindowMatch | None:
    if query_length < 2 or key_length < 2:
        return None

    key_chars = list(key)
    allow_middle = query_length >= 4
    best: _WindowMatch | None = None

    for window_length in {query_length - 1, query_length, query_length + 1}:
        if window_length < 2 or window_length > key_length:
            continue

        starts = {0, key_length - window_length}
        if allow_middle and window_length < key_length:
            starts.update(range(1, key_length - window_length))

        for start in starts:
            end = start + window_length
            window = "".join(key_chars[start:end])
            distance = damerau_levenshtein(query, window, 2)
            if distance > 2:
                continue

            if start == 0 and end == key_length:
                position = "whole"
            elif start == 0:
                position = "prefix"
            elif end == key_length:
                position = "suffix"
            else:
                position = "middle"

            base = 1 - distance / max(query_length, window_length)
            length_penalty = 0.05 * abs(query_length - window_length)
            edge_bonus = (0.02 if start == 0 else 0) + (0.02 if end == key_length else 0)
            mid_penalty = 0.03 if position == "middle" else 0
            similarity = max(0.0, min(1.0, base - length_penalty + edge_bonus - mid_penalty))

            candidate = _WindowMatch(
                distance=distance,
                window_length=window_length,
                position=position,
                similarity=similarity,
            )
            if best is None or _better_window(candidate, best, query_length):
                best = candidate

    return best


def _score_entry(
    query: str,
    query_length: int,
    entry: tuple[Ship, ShipSearchKey, str],
    allow_reverse_contains: bool,
) -> ShipSearchHit | None:
    ship, key, value = entry
    key_length = len(value)
    window = _best_window_match(query, value, query_length, key_length)
    similarity = window.similarity if window else 0.0
    distance = window.distance if window else None
    window_length = window.window_length if window else key_length
    position = window.position if window else "whole"

    def fallback(value_score: float) -> None:
        nonlocal similarity, distance, window_length, position
        if value_score <= similarity:
            return
        similarity = value_score
        distance = None
        window_length = key_length
        position = "whole"

    if value.startswith(query):
        fallback(0.85)
    if query in value or (allow_reverse_contains and value in query):
        fallback(0.6)
    if query_length >= 2 and _is_subsequence(query, value):
        fallback(0.45 + 0.2 * (query_length / max(query_length, key_length)))

    if similarity <= 0:
        return None
    score = similarity * KEY_WEIGHT[key]
    if score < MIN_CANDIDATE_SCORE:
        return None

    return ShipSearchHit(
        ship=ship,
        key=key,
        score=score,
        exact=False,
        query_length=query_length,
        key_length=key_length,
        window_length=window_length,
        position=position,
        distance=distance,
    )


def search_ships(index: ShipSearchIndex, query: str, limit: int = 5) -> ShipSearchResult:
    q = normalize_ship_query(query)
    if not q or len(q) > MAX_SHIP_QUERY_LENGTH:
        return ShipSearchResult(exact=[], fuzzy=[])

    exact = _dedupe_exact(index.exact.get(q, []))[:limit]
    query_length = len(q)
    has_han = _has_han(q)
    # Pure numbers are candidate indices, not ship names; ASCII+digits are
    # usually indices. Chinese+digits still allow a Chinese-name prefix.
    if query_length < 2 or q.isdigit() or (not has_han and re.search(r"\d", q)):
        return ShipSearchResult(exact=exact, fuzzy=[])

    allowed = {"nameZh"} if has_han else {"pinyin"}
    best: dict[str, ShipSearchHit] = {}
    for entry in index.entries:
        if entry[1] not in allowed:
            continue
        hit = _score_entry(q, query_length, entry, has_han)
        if hit is None:
            continue
        previous = best.get(hit.ship.index)
        if (
            previous is None
            or hit.score > previous.score
            or (hit.score == previous.score and KEY_PRIORITY[hit.key] > KEY_PRIORITY[previous.key])
        ):
            best[hit.ship.index] = hit

    exact_indexes = {hit.ship.index for hit in exact}
    fuzzy = sorted(
        (hit for hit in best.values() if hit.ship.index not in exact_indexes),
        key=lambda hit: (
            -hit.score,
            -KEY_PRIORITY[hit.key],
            _name_of(hit.ship).casefold(),
        ),
    )[:limit]
    return ShipSearchResult(exact=exact, fuzzy=fuzzy)
