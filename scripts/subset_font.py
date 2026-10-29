"""Regenerate the bundled Noto Sans CJK SC subset.

Usage:
    py scripts/subset_font.py --source /path/to/NotoSansCJKsc-Regular.otf
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def collect_glyphs(data_dir: Path) -> str:
    import json

    chars: set[str] = set()

    ships_path = data_dir / "ships.json"
    if ships_path.exists():
        ships = json.loads(ships_path.read_text(encoding="utf-8")).get("ships") or []
        for ship in ships:
            for key in ("name", "nameZh", "aliasZh"):
                value = ship.get(key)
                if isinstance(value, str):
                    chars.update(value)

    attributes_path = data_dir / "attributes.json"
    if attributes_path.exists():
        attributes = json.loads(attributes_path.read_text(encoding="utf-8")).get(
            "attributes",
        ) or []
        for attribute in attributes:
            for key in ("label", "unit"):
                value = attribute.get(key)
                if isinstance(value, str):
                    chars.update(value)
            for value in (attribute.get("labels") or {}).values():
                chars.update(str(value))

    for path in (PLUGIN_ROOT / "wowsguess").rglob("*.py"):
        chars.update(path.read_text(encoding="utf-8"))
    chars.update((PLUGIN_ROOT / "main.py").read_text(encoding="utf-8"))

    chars.update("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    chars.update(" .,:;!?()[]{}<>+-*/=%#@&|~^_\\\"'`")
    chars.update("，。！？；：、（）【】《》“”‘’·…–—⚠↑↓")
    chars.discard("\n")
    chars.discard("\r")
    chars.discard("\t")
    return "".join(sorted(chars))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="NotoSansCJKsc-Regular.otf")
    parser.add_argument("--data", default=str(PLUGIN_ROOT / "data"))
    parser.add_argument(
        "--out",
        default=str(PLUGIN_ROOT / "assets" / "fonts" / "NotoSansSC-subset.otf"),
    )
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"font not found: {source}")

    glyphs = collect_glyphs(Path(args.data))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as handle:
        handle.write(glyphs)
        glyph_file = handle.name

    command = [
        sys.executable,
        "-m",
        "fontTools.subset",
        str(source),
        f"--text-file={glyph_file}",
        f"--output-file={args.out}",
        "--layout-features=*",
        "--no-hinting",
        "--desubroutinize",
    ]
    print(" ".join(command))
    subprocess.run(command, check=True)
    print(f"subset: {args.out} ({Path(args.out).stat().st_size / 1024:.0f} KiB, {len(glyphs)} chars)")


if __name__ == "__main__":
    main()
