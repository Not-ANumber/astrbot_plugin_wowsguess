from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.fixture_data import write_data_dir
from wowsguess.packs import (
    PackError,
    describe_pack,
    normalize_server,
    read_manifest,
    resolve_pack_dir,
)


class PackTests(unittest.TestCase):
    def test_normalize_server(self) -> None:
        self.assertEqual(normalize_server("WG"), "wg")
        self.assertEqual(normalize_server(" lesta "), "lesta")
        self.assertEqual(normalize_server(None), "wg")
        with self.assertRaises(PackError):
            normalize_server("na")

    def test_resolve_wg_pack_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "packs"
            pack = write_data_dir(root / "wg")
            manifest = {
                "schemaVersion": 1,
                "server": "wg",
                "label": "WG 官服",
                "generatedAt": "fixture-1",
                "shipCount": 12,
            }
            (pack / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )

            resolved = resolve_pack_dir(root, "wg")
            self.assertEqual(resolved, pack)
            self.assertEqual(read_manifest(pack)["server"], "wg")
            self.assertIn("WG 官服", describe_pack(pack, "wg"))
            self.assertIn("12 艘", describe_pack(pack, "wg"))

    def test_missing_lesta_pack_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "packs"
            root.mkdir()
            with self.assertRaises(PackError) as ctx:
                resolve_pack_dir(root, "lesta")
            self.assertIn("Lesta", str(ctx.exception))
            self.assertIn("ships.json", str(ctx.exception))

    def test_manifest_server_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "packs"
            pack = write_data_dir(root / "wg")
            (pack / "manifest.json").write_text(
                json.dumps({"server": "lesta"}),
                encoding="utf-8",
            )
            with self.assertRaises(PackError):
                resolve_pack_dir(root, "wg")

    def test_data_dir_override_and_handmade_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = write_data_dir(Path(tmp) / "my-pack")
            resolved = resolve_pack_dir(Path(tmp) / "packs", "wg", pack)
            self.assertEqual(resolved, pack)
            self.assertIsNone(read_manifest(pack))

    def test_malformed_manifest_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = write_data_dir(Path(tmp) / "wg")
            (pack / "manifest.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(PackError):
                read_manifest(pack)


if __name__ == "__main__":
    unittest.main()
