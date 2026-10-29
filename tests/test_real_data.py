"""Optional smoke test against the real WG pack.

The real data is not committed (see README); when ``packs/wg/ships.json``
exists this test exercises the full pipeline and 12-column renderer.
"""

from __future__ import annotations

import json
import random
import unittest
from pathlib import Path

from wowsguess.app import GameApp
from wowsguess.data import load_data
from wowsguess.models import CoopConfig, IncomingMessage
from wowsguess.render.board import BoardRenderer
from wowsguess.store import BotStore

DATA_DIR = Path(__file__).resolve().parents[1] / "packs" / "wg"


@unittest.skipUnless((DATA_DIR / "ships.json").exists(), "WG data pack not present")
class RealDataSmokeTest(unittest.TestCase):
    def test_start_guess_status_end(self) -> None:
        data = load_data(DATA_DIR)
        manifest = DATA_DIR / "manifest.json"
        if manifest.exists():
            self.assertEqual(
                len(data.ships),
                json.loads(manifest.read_text(encoding="utf-8"))["shipCount"],
            )
        else:
            self.assertGreater(len(data.ships), 0)
        self.assertIn("standard", data.pools)

        store = BotStore(":memory:")
        app = GameApp(
            data,
            store,
            CoopConfig(),
            BoardRenderer(),
            rng=random.Random(1),
        )

        def message(text: str, message_id: str) -> IncomingMessage:
            return IncomingMessage(
                platform="test:bot",
                group_id="real-group",
                user_id="u1",
                nickname="测试玩家",
                role="owner",
                message_id=message_id,
                text=text,
                directed=True,
            )

        try:
            start = app.handle(message("/窝一把", "real-1"))
            self.assertEqual(start.kind, "image")
            self.assertTrue(start.png.startswith(bytes([0x89]) + b"PNG"))

            guess = app.handle(message("/秋月", "real-2"))
            self.assertEqual(guess.kind, "image")

            status = app.handle(message("/状态", "real-3"))
            self.assertEqual(status.kind, "image")

            end = app.handle(message("/结束", "real-4"))
            self.assertEqual(end.kind, "image")
            self.assertEqual(
                store.get_session("test:bot", "real-group").status,
                "aborted",
            )

            stats = app.handle(message("/统计", "real-5"))
            self.assertEqual(stats.kind, "text")
            self.assertIn("总局数 1", stats.text)

            restart = app.handle(message("/再来一局", "real-6"))
            self.assertEqual(restart.kind, "image")
            self.assertEqual(
                store.get_session("test:bot", "real-group").status,
                "active",
            )
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
