"""Load a bot data pack.

The loader accepts both the full main-repo ``data/`` snapshot and the slimmer
``packs/<server>/`` export; unknown fields are ignored. It validates the
invariants the game relies on so a broken pack fails at startup instead of
mid-game.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from .engine import filter_answers_by_tier, normalize_pool_tier_range
from .models import (
    AttributeDef,
    DifficultyDef,
    GameData,
    Pool,
    Ship,
    TierRange,
)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_data(data_dir: str | Path) -> GameData:
    root = Path(data_dir)
    ships_doc = _read_json(root / "ships.json")
    attr_doc = _read_json(root / "attributes.json")
    diff_doc = _read_json(root / "difficulties.json")

    ships = [Ship.from_json(raw) for raw in ships_doc.get("ships") or []]
    if not ships:
        raise ValueError(f"{root / 'ships.json'} 里没有任何舰船")

    attributes = [
        AttributeDef.from_json(raw) for raw in attr_doc.get("attributes") or []
    ]
    if not attributes:
        raise ValueError(f"{root / 'attributes.json'} 里没有任何属性")

    difficulties = [
        DifficultyDef.from_json(raw) for raw in diff_doc.get("difficulties") or []
    ]
    if not difficulties:
        raise ValueError(f"{root / 'difficulties.json'} 里没有任何难度")

    pools: dict[str, Pool] = {}
    pool_dir = root / "pools"
    for difficulty in difficulties:
        path = pool_dir / f"{difficulty.key}.json"
        if not path.exists():
            raise ValueError(f"缺少难度「{difficulty.key}」的答案池：{path}")
        pools[difficulty.key] = Pool.from_json(_read_json(path))

    by_index = {ship.index: ship for ship in ships}
    if len(by_index) != len(ships):
        raise ValueError("ships.json 存在重复的 index")
    defs = {definition.key: definition for definition in attributes}

    for key, pool in pools.items():
        if not pool.answers:
            raise ValueError(f"难度「{key}」的答案池是空的")
        for index in pool.answers:
            if index not in by_index:
                raise ValueError(f"难度「{key}」的答案 {index} 不在船表里")
        for attr_key in pool.attribute_keys:
            if attr_key not in defs:
                raise ValueError(f"难度「{key}」引用了未定义属性 {attr_key}")
        for index in pool.group_of:
            if index not in by_index:
                raise ValueError(f"难度「{key}」的 groupOf 引用了不存在的船 {index}")

    data_version = str(
        ships_doc.get("generatedAt")
        or ships_doc.get("generated_at")
        or ships_doc.get("version")
        or "unknown",
    )

    return GameData(
        ships=ships,
        by_index=by_index,
        attributes=attributes,
        defs=defs,
        difficulties=difficulties,
        default_difficulty=difficulties[0],
        pools=pools,
        data_version=data_version,
    )


def resolve_difficulty(data: GameData, key: str | None) -> DifficultyDef:
    if key and key in data.pools:
        for difficulty in data.difficulties:
            if difficulty.key == key:
                return difficulty
    return data.default_difficulty


def pool_for(data: GameData, difficulty_key: str) -> Pool:
    return data.pools.get(difficulty_key) or data.pools[data.default_difficulty.key]


def answers_for(
    data: GameData,
    difficulty_key: str,
    tier_range: TierRange | None,
) -> list[str]:
    pool = pool_for(data, difficulty_key)

    def level_of(index: str) -> int | None:
        ship = data.by_index.get(index)
        if not ship:
            return None
        level = ship.attrs.get("level")
        if isinstance(level, bool):
            return None
        if isinstance(level, (int, float)):
            return int(level)
        return None

    return filter_answers_by_tier(
        list(pool.answers),
        level_of,
        normalize_pool_tier_range(tier_range),
    )


def pick_coop_answer(
    data: GameData,
    difficulty_key: str,
    tier_range: TierRange | None,
    rng: random.Random | random.SystemRandom | None = None,
) -> str:
    answers = answers_for(data, difficulty_key, tier_range)
    if not answers:
        raise ValueError("答案池为空，先检查数据包")
    return (rng or random.SystemRandom()).choice(answers)


def difficulty_label(data: GameData, key: str) -> str:
    for difficulty in data.difficulties:
        if difficulty.key == key:
            return difficulty.label
    return key


def tier_label(tier_range: TierRange | None) -> str:
    if not tier_range:
        return "全等级"
    return f"T{tier_range.min}–T{tier_range.max}"
