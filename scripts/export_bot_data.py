"""Export a slim, bot-only data pack from the main wowsguess data directory.

The bot does not show descriptions, ship images, radar charts or pinyin search
metadata beyond the fields kept here. The output is a self-contained pack:
``ships.json``, ``attributes.json``, ``difficulties.json``, ``pools/`` and a
``manifest.json`` with server/source/version and per-file checksums.

Usage:
    py scripts/export_bot_data.py --source /path/to/main/data --server wg
    py scripts/export_bot_data.py --source /path/to/main/data --out packs/wg --server wg
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_SERVER_LABELS = {
    "wg": "WG 官服",
    "lesta": "Lesta 服",
}


def _read(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))


def slim_ship(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": raw["index"],
        "name": raw.get("name"),
        "nameZh": raw.get("nameZh"),
        "aliasZh": raw.get("aliasZh"),
        "pinyin": raw.get("pinyin"),
        "pinyinInitials": raw.get("pinyinInitials"),
        "aliasPinyin": raw.get("aliasPinyin"),
        "rarity": raw.get("rarity") or "",
        "attrs": raw.get("attrs") or {},
    }


def slim_attribute(raw: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "key",
        "label",
        "labelEn",
        "class",
        "kind",
        "betterIs",
        "close",
        "unit",
        "unitEn",
        "hideUnit",
        "decimals",
        "options",
        "labels",
    )
    return {key: raw[key] for key in keep if key in raw}


def slim_pool(raw: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "difficulty",
        "label",
        "attributeKeys",
        "answers",
        "groupOf",
        "representative",
    )
    return {key: raw[key] for key in keep if key in raw}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="main data/ directory")
    parser.add_argument(
        "--server",
        choices=tuple(_SERVER_LABELS),
        default="wg",
        help="data server this pack belongs to",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output directory; default packs/<server> next to the plugin",
    )
    parser.add_argument("--label", default=None, help="human-readable pack label")
    parser.add_argument(
        "--source-name",
        default=None,
        help="source name for the manifest; default iwarship when present",
    )
    args = parser.parse_args()

    source = Path(args.source)
    out = Path(args.out) if args.out else Path(__file__).resolve().parents[1] / "packs" / args.server

    ships_doc = _read(source / "ships.json")
    attributes_doc = _read(source / "attributes.json")
    difficulties_doc = _read(source / "difficulties.json")

    ships = [slim_ship(raw) for raw in ships_doc.get("ships") or []]
    attributes = [
        slim_attribute(raw) for raw in attributes_doc.get("attributes") or []
    ]
    difficulties = difficulties_doc.get("difficulties") or []

    if not ships or not attributes or not difficulties:
        raise SystemExit("source data is incomplete")

    _write(
        out / "ships.json",
        {
            "schemaVersion": 1,
            "generatedAt": ships_doc.get("generatedAt"),
            "attributeKeys": ships_doc.get("attributeKeys") or [],
            "ships": ships,
        },
    )
    _write(
        out / "attributes.json",
        {
            "version": attributes_doc.get("version", 1),
            "attributes": attributes,
        },
    )
    _write(
        out / "difficulties.json",
        {
            "version": difficulties_doc.get("version", 1),
            "difficulties": difficulties,
        },
    )

    wanted_pools = {f"{difficulty['key']}.json" for difficulty in difficulties}
    pools_dir = out / "pools"
    if pools_dir.is_dir():
        for stale in pools_dir.glob("*.json"):
            if stale.name not in wanted_pools:
                stale.unlink()

    for difficulty in difficulties:
        key = difficulty["key"]
        pool = _read(source / "pools" / f"{key}.json")
        _write(out / "pools" / f"{key}.json", slim_pool(pool))

    source_info = ships_doc.get("source") or {}
    iwarship = source_info.get("iwarship") if isinstance(source_info, dict) else None
    source_name = args.source_name or ("iwarship" if isinstance(iwarship, dict) else "unknown")
    source_version_id = iwarship.get("versionId") if isinstance(iwarship, dict) else None

    files: dict[str, dict[str, Any]] = {}
    for path in sorted(out.rglob("*.json")):
        if path.name == "manifest.json":
            continue
        raw = path.read_bytes()
        files[path.relative_to(out).as_posix()] = {
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    _write(
        out / "manifest.json",
        {
            "schemaVersion": 1,
            "server": args.server,
            "label": args.label or _SERVER_LABELS[args.server],
            "source": source_name,
            "sourceVersionId": source_version_id,
            "generatedAt": ships_doc.get("generatedAt"),
            "shipCount": len(ships),
            "attributeCount": len(attributes),
            "files": files,
        },
    )

    total = sum(path.stat().st_size for path in out.rglob("*.json"))
    print(
        f"exported {len(ships)} ships, {len(attributes)} attributes, "
        f"{len(difficulties)} difficulties"
    )
    print(f"output: {out} ({total / 1024 / 1024:.2f} MiB)")


if __name__ == "__main__":
    main()
