"""Command parsing and message classification.

``parse_command`` strips the leading slash; ``classify_message`` is the single
place that decides whether a directed message is a command, a ship guess, the
menu, or something the host's LLM should handle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .engine import normalize_pool_tier_range
from .errors import CoopError
from .models import (
    MAX_TIER,
    MIN_ANSWER_TIER,
    GameData,
    IncomingMessage,
    TierRange,
)

CommandName = Literal["start", "restart", "stats", "status", "end", "help", "unknown"]


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    name: CommandName
    arg: str


@dataclass(frozen=True, slots=True)
class StartOptions:
    difficulty_key: str
    tier_range: TierRange | None


ALIASES: dict[str, CommandName] = {
    "窝一把": "start",
    "ccb": "start",
    "再来一局": "restart",
    "再开一局": "restart",
    "重开": "restart",
    "restart": "restart",
    "统计": "stats",
    "战绩": "stats",
    "stats": "stats",
    "状态": "status",
    "棋盘": "status",
    "board": "status",
    "结束": "end",
    "end": "end",
    "帮助": "help",
    "说明": "help",
    "help": "help",
}

_TIER_PATTERN = re.compile(r"^[Tt]?(\d{1,2})(?:\s*[-~–—]\s*[Tt]?(\d{1,2}))?$")


def parse_command(raw: str) -> ParsedCommand | None:
    text = (raw or "").strip()
    text = re.sub(r"^[/／]+", "", text).strip()
    if not text:
        return None

    match = re.match(r"^(\S+)(?:\s+([\s\S]*))?$", text)
    if not match:
        return None
    head = match.group(1)
    tail = (match.group(2) or "").strip()

    exact = ALIASES.get(head) or ALIASES.get(head.lower())
    if exact:
        return ParsedCommand(name=exact, arg=tail)
    return ParsedCommand(name="unknown", arg=text)


def parse_start_options(arg: str, data: GameData) -> StartOptions:
    difficulty_key = data.default_difficulty.key
    tier_range = TierRange(min=MIN_ANSWER_TIER, max=MAX_TIER)

    for token in [part for part in (arg or "").split() if part]:
        lower = token.lower()

        if lower in {"普通", "standard", "normal", "n"}:
            if "standard" not in data.pools:
                raise CoopError("BAD_DIFFICULTY", "当前数据没有普通档")
            difficulty_key = "standard"
            continue
        if lower in {"困难", "hard", "h"}:
            if "hard" not in data.pools:
                raise CoopError("BAD_DIFFICULTY", "当前数据没有困难档")
            difficulty_key = "hard"
            continue

        match = _TIER_PATTERN.fullmatch(token)
        if match:
            low = int(match.group(1))
            high = int(match.group(2)) if match.group(2) is not None else low
            normalized = normalize_pool_tier_range(
                TierRange(min=low, max=high),
            )
            if normalized is None:
                raise CoopError("BAD_TIER", "等级范围要写成 5-8 或 8（T 可省略）")
            tier_range = normalized
            continue

        raise CoopError(
            "BAD_OPTION",
            f"没看懂「{token}」。用法：/窝一把 或 /ccb [n|h] [5-8]",
        )

    return StartOptions(difficulty_key=difficulty_key, tier_range=tier_range)


def clean_ship_text(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r'^["\'“”‘’《》「」『』【】]+', "", cleaned)
    cleaned = re.sub(r'["\'“”‘’《》「」『』【】。！？!?，,；;：:]+$', "", cleaned)
    return cleaned.strip()


@dataclass(frozen=True, slots=True)
class CommandAction:
    command: ParsedCommand


@dataclass(frozen=True, slots=True)
class ShipAction:
    query: str


@dataclass(frozen=True, slots=True)
class MenuAction:
    pass


IncomingAction = CommandAction | ShipAction | MenuAction


def classify_message(
    message: IncomingMessage,
    data: GameData,
    is_active: bool,
) -> IncomingAction | None:
    if not message.directed:
        return None

    text = (message.text or "").strip()
    if not text:
        return MenuAction()

    command = parse_command(text)
    if command is not None and command.name != "unknown":
        return CommandAction(command=command)

    slash_query = re.match(r"^[/／]\s*(.+)$", text, re.DOTALL)
    if slash_query and is_active:
        # Candidate resolution and /1 confirmation belong to the service;
        # classification must not drop /1 or a fuzzy candidate here.
        return ShipAction(query=clean_ship_text(slash_query.group(1)))

    return MenuAction()
