"""Typed models shared by the core, renderer and adapters.

Internal names are snake_case. JSON parsing happens at the boundary in
``data.py``; attribute keys inside ``Ship.attrs`` stay exactly as the data
pipeline emitted them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

AttrValue = int | float | str
CoopStatus = str  # active | won | lost | aborted
Role = str  # owner | admin | member | ""


MIN_TIER = 1
MAX_TIER = 11
MIN_ANSWER_TIER = 5


@dataclass(frozen=True, slots=True)
class CloseBand:
    """One segment of a banded absolute close threshold.

    ``up_to`` is inclusive; ``None`` means the last, open-ended segment.
    """

    up_to: float | None
    absolute: float


@dataclass(frozen=True, slots=True)
class CloseThreshold:
    absolute: float | None = None
    relative: float | None = None
    #: 分段绝对阈值；与 absolute/relative 互斥（数据校验保证）
    bands: tuple[CloseBand, ...] = ()


@dataclass(frozen=True, slots=True)
class AttributeDef:
    key: str
    label: str
    label_en: str | None = None
    attr_class: str = "A"
    kind: str = "numeric"  # discrete | ordered | numeric
    better_is: str | None = None  # higher | lower | None
    close: CloseThreshold | None = None
    unit: str = ""
    unit_en: str | None = None
    hide_unit: bool = False
    decimals: int = 0
    options: tuple[str, ...] = ()
    labels: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "AttributeDef":
        close_raw = raw.get("close")
        close = None
        if isinstance(close_raw, Mapping):
            close = CloseThreshold(
                absolute=_as_float_or_none(close_raw.get("abs")),
                relative=_as_float_or_none(close_raw.get("rel")),
                bands=_parse_close_bands(close_raw.get("bands")),
            )
        options = raw.get("options") or ()
        labels = raw.get("labels") or {}
        return cls(
            key=str(raw["key"]),
            label=str(raw.get("label") or raw["key"]),
            label_en=_as_str_or_none(raw.get("labelEn")),
            attr_class=str(raw.get("class") or "A"),
            kind=str(raw.get("kind") or "numeric"),
            better_is=_as_str_or_none(raw.get("betterIs")),
            close=close,
            unit=str(raw.get("unit") or ""),
            unit_en=_as_str_or_none(raw.get("unitEn")),
            hide_unit=bool(raw.get("hideUnit") or False),
            decimals=int(raw.get("decimals") or 0),
            options=tuple(str(item) for item in options),
            labels={str(k): str(v) for k, v in labels.items()},
        )


@dataclass(frozen=True, slots=True)
class Ship:
    index: str
    name: str
    name_zh: str | None
    alias_zh: str | None
    pinyin: str | None
    pinyin_initials: str | None
    alias_pinyin: str | None
    rarity: str
    attrs: Mapping[str, AttrValue]

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "Ship":
        return cls(
            index=str(raw["index"]),
            name=str(raw.get("name") or raw["index"]),
            name_zh=_as_str_or_none(raw.get("nameZh")),
            alias_zh=_as_str_or_none(raw.get("aliasZh")),
            pinyin=_as_str_or_none(raw.get("pinyin")),
            pinyin_initials=_as_str_or_none(raw.get("pinyinInitials")),
            alias_pinyin=_as_str_or_none(raw.get("aliasPinyin")),
            rarity=str(raw.get("rarity") or ""),
            attrs=dict(raw.get("attrs") or {}),
        )

    def display_name(self) -> str:
        return self.name_zh or self.name


@dataclass(frozen=True, slots=True)
class DifficultyDef:
    key: str
    label: str
    label_en: str | None
    attribute_keys: tuple[str, ...]

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "DifficultyDef":
        return cls(
            key=str(raw["key"]),
            label=str(raw.get("label") or raw["key"]),
            label_en=_as_str_or_none(raw.get("labelEn")),
            attribute_keys=tuple(str(k) for k in raw.get("attributeKeys") or ()),
        )


@dataclass(frozen=True, slots=True)
class Pool:
    difficulty: str
    label: str
    attribute_keys: tuple[str, ...]
    answers: tuple[str, ...]
    group_of: Mapping[str, int]
    representative: Mapping[str, str]

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "Pool":
        group_of_raw = raw.get("groupOf") or {}
        representative_raw = raw.get("representative") or {}
        return cls(
            difficulty=str(raw.get("difficulty") or ""),
            label=str(raw.get("label") or ""),
            attribute_keys=tuple(str(k) for k in raw.get("attributeKeys") or ()),
            answers=tuple(str(idx) for idx in raw.get("answers") or ()),
            group_of={str(k): int(v) for k, v in group_of_raw.items()},
            representative={str(k): str(v) for k, v in representative_raw.items()},
        )


@dataclass(frozen=True, slots=True)
class TierRange:
    min: int
    max: int

    def to_dict(self) -> dict[str, int]:
        return {"min": self.min, "max": self.max}

    @classmethod
    def from_json(cls, raw: Mapping[str, Any] | None) -> "TierRange | None":
        if not isinstance(raw, Mapping):
            return None
        try:
            return cls(min=int(raw["min"]), max=int(raw["max"]))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class GameData:
    ships: list[Ship]
    by_index: dict[str, Ship]
    attributes: list[AttributeDef]
    defs: dict[str, AttributeDef]
    difficulties: list[DifficultyDef]
    default_difficulty: DifficultyDef
    pools: dict[str, Pool]
    data_version: str


@dataclass(frozen=True, slots=True)
class CommandButton:
    label: str
    data: str
    enter: bool = True


@dataclass(frozen=True, slots=True)
class CoopStatsLeader:
    nickname: str
    count: int


@dataclass(frozen=True, slots=True)
class CoopStats:
    games: int = 0
    wins: int = 0
    losses: int = 0
    aborted: int = 0
    total_guesses: int = 0
    best_attempts: int | None = None
    current_streak: int = 0
    best_streak: int = 0
    last_status: str | None = None
    last_difficulty: str | None = None
    last_attempts: int | None = None
    last_ended_at: int | None = None
    top_guessers: tuple[CoopStatsLeader, ...] = ()
    top_winners: tuple[CoopStatsLeader, ...] = ()


@dataclass(frozen=True, slots=True)
class Guess:
    ship_index: str
    user_id: str
    nickname: str
    at: int


@dataclass
class Session:
    platform: str
    group_id: str
    session_id: str
    status: CoopStatus
    answer_index: str
    difficulty: str
    tier_range: TierRange | None
    guesses: list[Guess]
    host_id: str
    host_name: str
    data_version: str
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class Actor:
    platform: str
    group_id: str
    user_id: str
    nickname: str
    role: Role = "member"


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    platform: str
    group_id: str
    user_id: str
    nickname: str
    role: Role
    message_id: str
    text: str
    directed: bool


@dataclass(frozen=True, slots=True)
class Feedback:
    key: str
    state: str  # exact | close | far
    direction: str | None  # up | down | None
    guess_value: AttrValue
    delta: float | None = None


@dataclass(frozen=True, slots=True)
class BoardRow:
    attempt: int
    nickname: str
    ship: Ship
    feedback: tuple[Feedback, ...]


@dataclass(frozen=True, slots=True)
class StartRenderInput:
    host_name: str
    difficulty_label: str
    tier_label: str
    max_attempts: int


@dataclass(frozen=True, slots=True)
class HelpRenderInput:
    kind: str  # menu | help
    active: bool
    remaining: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class BoardRenderInput:
    session: Session
    rows: tuple[BoardRow, ...]
    answer: Ship | None
    remaining: int
    difficulty_label: str
    tier_label: str
    attribute_keys: tuple[str, ...]
    defs: Mapping[str, AttributeDef]


@dataclass(frozen=True, slots=True)
class TextReply:
    text: str
    follow_up: "Reply | None" = None
    kind: str = "text"


@dataclass(frozen=True, slots=True)
class ImageReply:
    png: bytes
    fallback_text: str
    caption: str | None = None
    follow_up: "Reply | None" = None
    kind: str = "image"


@dataclass(frozen=True, slots=True)
class MarkdownReply:
    content: str
    fallback_text: str
    keyboard: tuple[CommandButton, ...] = ()
    follow_up: "Reply | None" = None
    kind: str = "markdown"


Reply = TextReply | ImageReply | MarkdownReply


@dataclass(frozen=True, slots=True)
class CoopConfig:
    max_attempts: int = 8
    global_cooldown_ms: int = 3_000
    user_cooldown_ms: int = 5_000
    ttl_ms: int = 2 * 60 * 60 * 1000
    start_cooldown_ms: int = 60_000
    fuzzy_mode: str = "auto"  # auto | suggest | off
    suggest_ttl_ms: int = 60_000
    suggest_max: int = 3


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_close_bands(value: Any) -> tuple[CloseBand, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    bands: list[CloseBand] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        absolute = _as_float_or_none(item.get("abs"))
        if absolute is None:
            continue
        bands.append(CloseBand(up_to=_as_float_or_none(item.get("upTo")), absolute=absolute))
    return tuple(bands)
