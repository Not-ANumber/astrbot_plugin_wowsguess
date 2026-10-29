"""Attribute comparison and ship-name search.

Ported one-for-one from ``packages/shared/src/engine.ts``. The epsilon values
and the direction semantics are intentional: do not replace them with
``math.isclose`` or a "better is higher/lower" arrow.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence

from .models import (
    MAX_TIER,
    MIN_ANSWER_TIER,
    MIN_TIER,
    AttributeDef,
    Feedback,
    Pool,
    Ship,
    TierRange,
)

ABS_EPSILON_FACTOR = 1e-9
REL_EPSILON = 1e-12

_RARITY_LABELS: dict[str, str] = {
    "Common": "普通",
    "Uncommon": "精良",
    "Rare": "稀有",
    "Epic": "史诗",
    "Legendary": "传奇",
}


def is_close(guess: float, answer: float, definition: AttributeDef) -> bool:
    close = definition.close
    if close is None:
        return False
    # 0 代表「没有这项能力」，0 与非 0 不是「接近」，而是「有没有」。
    # 双方都为 0 时 compare_one_attribute 的相等分支已经返回 exact。
    if guess == 0 or answer == 0:
        return False

    diff = abs(guess - answer)
    epsilon = ABS_EPSILON_FACTOR * max(1.0, abs(guess), abs(answer))

    if close.bands:
        # 用较大的值选段，避免「127 对 140」只在某一个方向判黄。
        reference = max(abs(guess), abs(answer))
        band = next(
            (
                item
                for item in close.bands
                if item.up_to is None or reference <= item.up_to
            ),
            close.bands[-1],
        )
        return diff <= band.absolute + epsilon

    if close.absolute is not None and diff <= close.absolute + epsilon:
        return True
    if close.relative is not None and answer != 0:
        return diff / abs(answer) <= close.relative + REL_EPSILON
    return False


def _better_direction(guess: float, answer: float) -> str:
    return "up" if answer > guess else "down"


def compare_one_attribute(
    guess: Ship,
    answer: Ship,
    definition: AttributeDef,
) -> Feedback:
    guess_value = guess.attrs.get(definition.key)
    answer_value = answer.attrs.get(definition.key)

    if definition.kind == "discrete":
        return Feedback(
            key=definition.key,
            state="exact" if guess_value == answer_value else "far",
            direction=None,
            guess_value=guess_value if guess_value is not None else "",
        )

    g = _as_number(guess_value)
    a = _as_number(answer_value)

    if g is None or a is None:
        return Feedback(
            key=definition.key,
            state="far",
            direction=None,
            guess_value=guess_value if guess_value is not None else "",
        )

    if g == a:
        return Feedback(
            key=definition.key,
            state="exact",
            direction=None,
            guess_value=g,
            delta=0.0,
        )

    return Feedback(
        key=definition.key,
        state="close" if is_close(g, a, definition) else "far",
        direction=_better_direction(g, a),
        guess_value=g,
        delta=a - g,
    )


def compare_attributes(
    guess: Ship,
    answer: Ship,
    keys: Sequence[str],
    defs: Mapping[str, AttributeDef],
) -> tuple[Feedback, ...]:
    feedback: list[Feedback] = []
    for key in keys:
        definition = defs.get(key)
        if definition is None:
            raise ValueError(f"未知属性「{key}」，请检查 attributes.json 与 difficulties.json")
        feedback.append(compare_one_attribute(guess, answer, definition))
    return tuple(feedback)


def is_correct_guess(
    guess_index: str,
    answer_index: str,
    pool: Pool | None = None,
) -> bool:
    if guess_index == answer_index:
        return True
    if pool is None:
        return False
    guess_group = pool.group_of.get(guess_index)
    answer_group = pool.group_of.get(answer_index)
    return (
        guess_group is not None
        and answer_group is not None
        and guess_group == answer_group
    )


def display_name(ship: Ship, locale: str = "zh") -> str:
    if locale == "en":
        return ship.name
    return ship.name_zh or ship.name


def rarity_label(rarity: str, locale: str = "zh") -> str:
    if locale == "en":
        return rarity
    return _RARITY_LABELS.get(rarity, rarity)


def attr_label(definition: AttributeDef, locale: str = "zh") -> str:
    if locale == "en":
        return definition.label_en or definition.key.replace("_", " ")
    return definition.label


def attr_unit(definition: AttributeDef, locale: str = "zh") -> str:
    if locale == "en":
        return definition.unit_en if definition.unit_en is not None else definition.unit
    return definition.unit


def attr_head_unit(definition: AttributeDef, locale: str = "zh") -> str:
    if definition.hide_unit:
        return ""
    return attr_unit(definition, locale)


def attr_value_label(
    definition: AttributeDef,
    value: object,
    locale: str = "zh",
) -> str:
    key = str(value)
    if locale == "en":
        return key.replace("_", " ")
    return definition.labels.get(key, key)


def format_number(value: float, decimals: int = 0) -> str:
    if not math.isfinite(value):
        return str(value)
    return f"{value:,.{max(0, decimals)}f}"


def format_attr_value(
    definition: AttributeDef,
    value: object,
    locale: str = "zh",
) -> str:
    if definition.kind == "discrete":
        return attr_value_label(definition, value, locale)
    number = _as_number(value)
    if number is None:
        return str(value)
    text = format_number(number, definition.decimals)
    unit = attr_unit(definition, locale)
    return f"{text} {unit}" if unit else text


def format_cell_value(
    definition: AttributeDef,
    value: object,
    locale: str = "zh",
) -> str:
    if definition.kind == "discrete":
        return attr_value_label(definition, value, locale)
    number = _as_number(value)
    if number is None:
        return str(value)
    return format_number(number, definition.decimals)


def normalize_query(value: str) -> str:
    return re.sub(r"[_\-\s]+", "", (value or "").strip().lower())


def match_ships(ships: Sequence[Ship], query: str, limit: int = 8) -> list[Ship]:
    q = normalize_query(query)
    if not q:
        return []

    scored: list[tuple[float, Ship]] = []
    for ship in ships:
        score = score_ship(ship, q)
        if score > 0:
            scored.append((score, ship))
    scored.sort(key=lambda item: (-item[0], display_name(item[1]).casefold()))
    return [ship for _, ship in scored[:limit]]


def score_ship(ship: Ship, q: str) -> int:
    zh = normalize_query(ship.name_zh or "")
    en = normalize_query(ship.name)
    idx = normalize_query(ship.index)
    alias = normalize_query(ship.alias_zh or "")

    py = normalize_query(ship.pinyin or "")
    py_words = [word for word in (ship.pinyin or "").lower().split() if word]
    py_init = normalize_query(ship.pinyin_initials or "")
    py_init_words = [
        word for word in (ship.pinyin_initials or "").lower().split() if word
    ]
    alias_py = normalize_query(ship.alias_pinyin or "")
    alias_py_words = [
        word for word in (ship.alias_pinyin or "").lower().split() if word
    ]

    if zh == q:
        return 100
    if en == q:
        return 95
    if py and py == q:
        return 92
    if alias and alias == q:
        return 90
    if alias_py and alias_py == q:
        return 89
    if py_init and py_init == q:
        return 86
    if zh.startswith(q):
        return 80
    if py and py.startswith(q):
        return 78
    if any(word.startswith(q) for word in py_words):
        return 76
    if en.startswith(q):
        return 75
    if any(word.startswith(q) for word in py_init_words):
        return 73
    if py_init.startswith(q):
        return 72
    if alias and alias.startswith(q):
        return 70
    if alias_py and alias_py.startswith(q):
        return 69
    if any(word.startswith(q) for word in alias_py_words):
        return 68
    if zh and q in zh:
        return 60
    if en and q in en:
        return 55
    if idx == q:
        return 50
    if alias and q in alias:
        return 45
    if idx and q in idx:
        return 30
    return 0


def normalize_tier_range(
    tier_range: TierRange | Mapping[str, object] | None,
) -> TierRange | None:
    if tier_range is None:
        return None
    if isinstance(tier_range, TierRange):
        raw_min: object = tier_range.min
        raw_max: object = tier_range.max
    elif isinstance(tier_range, Mapping):
        raw_min = tier_range.get("min")
        raw_max = tier_range.get("max")
    else:
        return None

    def clamp(value: object) -> int | None:
        try:
            number = math.floor(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number):
            return None
        return min(MAX_TIER, max(MIN_TIER, number))

    low = clamp(raw_min)
    high = clamp(raw_max)
    if low is None or high is None:
        return None
    return TierRange(min=low, max=high) if low <= high else TierRange(min=high, max=low)


def filter_answers_by_tier(
    answers: Sequence[str],
    level_of: Callable[[str], int | None],
    tier_range: TierRange | None,
) -> list[str]:
    if tier_range is None:
        return list(answers)
    filtered = [
        index
        for index in answers
        if (level := level_of(index)) is not None
        and tier_range.min <= level <= tier_range.max
    ]
    return filtered if filtered else list(answers)


def normalize_pool_tier_range(
    tier_range: TierRange | Mapping[str, object] | None,
) -> TierRange | None:
    normalized = normalize_tier_range(tier_range)
    if normalized is None:
        return None
    low = max(normalized.min, MIN_ANSWER_TIER)
    if low > normalized.max:
        return None
    return TierRange(min=low, max=normalized.max)


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None
