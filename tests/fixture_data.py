"""Synthetic data for tests. No real ship data is needed or committed."""

from __future__ import annotations

import json
from pathlib import Path

from wowsguess.models import (
    Actor,
    AttributeDef,
    CloseThreshold,
    DifficultyDef,
    GameData,
    IncomingMessage,
    Pool,
    Ship,
)


def _ship(
    index: str,
    name: str,
    name_zh: str,
    level: int,
    nation: str,
    species: str,
    health: int,
    speed: int,
    reload: float,
    conceal: float,
    gun_barrels: int,
    *,
    alias_zh: str | None = None,
    pinyin: str | None = None,
    pinyin_initials: str | None = None,
    rarity: str = "Common",
) -> Ship:
    return Ship(
        index=index,
        name=name,
        name_zh=name_zh,
        alias_zh=alias_zh,
        pinyin=pinyin,
        pinyin_initials=pinyin_initials,
        alias_pinyin=None,
        rarity=rarity,
        attrs={
            "level": level,
            "nation": nation,
            "species": species,
            "health": health,
            "speed": speed,
            "reload": reload,
            "conceal": conceal,
            "gunBarrels": gun_barrels,
        },
    )


def make_data() -> GameData:
    attributes = [
        AttributeDef(
            key="level",
            label="等级",
            kind="ordered",
            close=CloseThreshold(absolute=1),
            unit="级",
            hide_unit=True,
        ),
        AttributeDef(
            key="nation",
            label="国家",
            kind="discrete",
            labels={"Japan": "日本", "USA": "美国"},
            options=("Japan", "USA"),
        ),
        AttributeDef(
            key="species",
            label="舰种",
            kind="discrete",
            labels={"Destroyer": "驱逐舰", "Cruiser": "巡洋舰"},
            options=("Destroyer", "Cruiser"),
        ),
        AttributeDef(
            key="health",
            label="血量",
            kind="numeric",
            close=CloseThreshold(relative=0.15),
            decimals=0,
        ),
        AttributeDef(
            key="speed",
            label="最大航速",
            kind="numeric",
            close=CloseThreshold(absolute=2),
            unit="节",
            decimals=0,
        ),
        AttributeDef(
            key="reload",
            label="装填时间",
            kind="numeric",
            close=CloseThreshold(absolute=0.5),
            unit="秒",
            decimals=1,
            better_is="lower",
        ),
        AttributeDef(
            key="conceal",
            label="水面隐蔽",
            kind="numeric",
            close=CloseThreshold(absolute=1),
            unit="km",
            decimals=1,
            better_is="lower",
        ),
        AttributeDef(
            key="gunBarrels",
            label="主炮数",
            kind="numeric",
            close=CloseThreshold(absolute=1),
            unit="门",
            decimals=0,
        ),
    ]
    defs = {definition.key: definition for definition in attributes}
    attribute_keys = tuple(defs)

    ships = [
        _ship(
            "P1", "Alpha", "阿尔法", 10, "Japan", "Destroyer",
            20000, 35, 5.0, 7.0, 6,
            pinyin="a er fa", pinyin_initials="aef",
        ),
        _ship(
            "P2", "Beta", "贝塔", 9, "USA", "Cruiser",
            30000, 32, 6.0, 8.0, 8,
            pinyin="bei ta", pinyin_initials="bt",
        ),
        _ship(
            "P3", "Gamma", "伽马", 10, "Japan", "Destroyer",
            21000, 35, 5.1, 7.1, 6,
            pinyin="jia ma", pinyin_initials="jm",
        ),
        _ship(
            "P4", "Delta", "德尔塔", 8, "USA", "Cruiser",
            31000, 31, 6.2, 8.2, 8,
            pinyin="de er ta", pinyin_initials="det",
        ),
        # Same signature group as P1: guessing either should count as correct.
        _ship(
            "P5", "Alpha Sister", "阿尔法姐妹", 10, "Japan", "Destroyer",
            20000, 35, 5.0, 7.0, 6,
            pinyin="a er fa jie mei", pinyin_initials="aefjm",
        ),
        _ship(
            "P6", "Zeta", "泽塔", 5, "Japan", "Cruiser",
            15000, 30, 7.0, 9.0, 4,
            pinyin="ze ta", pinyin_initials="zt",
            alias_zh="泽塔别名",
        ),
        _ship("P7", "Eta", "伊塔", 7, "USA", "Destroyer", 18000, 36, 4.5, 6.5, 5),
        _ship("P8", "Theta", "西塔", 8, "Japan", "Cruiser", 25000, 33, 6.5, 8.5, 10),
        _ship("P9", "Iota", "约塔", 9, "USA", "Destroyer", 19000, 37, 4.2, 6.2, 6),
        _ship("P10", "Kappa", "卡帕", 6, "Japan", "Cruiser", 22000, 31, 7.2, 9.2, 8),
        _ship("P11", "Lambda", "兰姆达", 10, "USA", "Cruiser", 28000, 34, 5.8, 7.8, 9),
        _ship("P12", "Mu", "缪", 7, "Japan", "Destroyer", 17000, 38, 4.0, 6.0, 5),
    ]
    by_index = {ship.index: ship for ship in ships}
    group_of = {
        "P1": 1, "P5": 1,
        "P2": 2, "P3": 3, "P4": 4, "P6": 5,
        "P7": 6, "P8": 7, "P9": 8, "P10": 9, "P11": 10, "P12": 11,
    }
    representative = {
        "1": "P1", "2": "P2", "3": "P3", "4": "P4", "5": "P6",
        "6": "P7", "7": "P8", "8": "P9", "9": "P10", "10": "P11", "11": "P12",
    }
    answers = ("P1", "P2", "P3", "P4", "P6", "P7", "P8", "P9", "P10", "P11", "P12")
    pool = Pool(
        difficulty="standard",
        label="普通",
        attribute_keys=attribute_keys,
        answers=answers,
        group_of=group_of,
        representative=representative,
    )
    hard_pool = Pool(
        difficulty="hard",
        label="困难",
        attribute_keys=attribute_keys,
        answers=answers,
        group_of=group_of,
        representative=representative,
    )
    difficulty = DifficultyDef(
        key="standard",
        label="普通",
        label_en="Standard",
        attribute_keys=attribute_keys,
    )
    hard = DifficultyDef(
        key="hard",
        label="困难",
        label_en="Hard",
        attribute_keys=attribute_keys,
    )
    return GameData(
        ships=ships,
        by_index=by_index,
        attributes=attributes,
        defs=defs,
        difficulties=[difficulty, hard],
        default_difficulty=difficulty,
        pools={"standard": pool, "hard": hard_pool},
        data_version="fixture-1",
    )


def make_actor(
    user_id: str = "u1",
    nickname: str = "A",
    role: str = "owner",
    group_id: str = "g1",
    platform: str = "test:bot",
) -> Actor:
    return Actor(
        platform=platform,
        group_id=group_id,
        user_id=user_id,
        nickname=nickname,
        role=role,
    )


def make_message(
    text: str,
    *,
    directed: bool = True,
    user_id: str = "u1",
    nickname: str = "A",
    role: str = "owner",
    group_id: str = "g1",
    platform: str = "test:bot",
    message_id: str = "m1",
) -> IncomingMessage:
    return IncomingMessage(
        platform=platform,
        group_id=group_id,
        user_id=user_id,
        nickname=nickname,
        role=role,
        message_id=message_id,
        text=text,
        directed=directed,
    )


def write_data_dir(root: str | Path, data: GameData | None = None) -> Path:
    """Write the synthetic dataset in the on-disk slim format."""
    data = data or make_data()
    root = Path(root)
    (root / "pools").mkdir(parents=True, exist_ok=True)

    ships = []
    for ship in data.ships:
        ships.append(
            {
                "index": ship.index,
                "name": ship.name,
                "nameZh": ship.name_zh,
                "aliasZh": ship.alias_zh,
                "pinyin": ship.pinyin,
                "pinyinInitials": ship.pinyin_initials,
                "aliasPinyin": ship.alias_pinyin,
                "rarity": ship.rarity,
                "attrs": dict(ship.attrs),
            },
        )

    attributes = []
    for definition in data.attributes:
        raw = {
            "key": definition.key,
            "label": definition.label,
            "class": definition.attr_class,
            "kind": definition.kind,
            "betterIs": definition.better_is,
            "unit": definition.unit,
            "hideUnit": definition.hide_unit,
            "decimals": definition.decimals,
            "options": list(definition.options),
            "labels": dict(definition.labels),
        }
        if definition.label_en is not None:
            raw["labelEn"] = definition.label_en
        if definition.unit_en is not None:
            raw["unitEn"] = definition.unit_en
        if definition.close is not None:
            close = {
                key: value
                for key, value in (
                    ("abs", definition.close.absolute),
                    ("rel", definition.close.relative),
                )
                if value is not None
            }
            if definition.close.bands:
                close["bands"] = [
                    {"upTo": band.up_to, "abs": band.absolute}
                    for band in definition.close.bands
                ]
            raw["close"] = close
        attributes.append(raw)

    difficulties = [
        {
            "key": difficulty.key,
            "label": difficulty.label,
            "labelEn": difficulty.label_en,
            "attributeKeys": list(difficulty.attribute_keys),
        }
        for difficulty in data.difficulties
    ]

    def dump(path: Path, payload) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    dump(
        root / "ships.json",
        {
            "schemaVersion": 1,
            "generatedAt": data.data_version,
            "attributeKeys": [definition.key for definition in data.attributes],
            "ships": ships,
        },
    )
    dump(root / "attributes.json", {"version": 1, "attributes": attributes})
    dump(root / "difficulties.json", {"version": 1, "difficulties": difficulties})

    for key, pool in data.pools.items():
        dump(
            root / "pools" / f"{key}.json",
            {
                "difficulty": pool.difficulty,
                "label": pool.label,
                "attributeKeys": list(pool.attribute_keys),
                "answers": list(pool.answers),
                "groupOf": dict(pool.group_of),
                "representative": dict(pool.representative),
            },
        )
    return root
