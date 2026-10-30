"""Optional smoke test against the real data packs.

The packs may not be committed (see README); each server is tested only when its
``packs/<server>/ships.json`` exists. Both WG and Lesta go through the same
pipeline and the 12-column renderer.
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

PACKS_ROOT = Path(__file__).resolve().parents[1] / "packs"
SERVERS = ("wg", "lesta")


def _make_smoke_test(server: str) -> type[unittest.TestCase]:
    data_dir = PACKS_ROOT / server

    @unittest.skipUnless((data_dir / "ships.json").exists(), f"{server} data pack not present")
    class RealDataSmokeTest(unittest.TestCase):
        def test_start_guess_status_end(self) -> None:
            data = load_data(data_dir)
            manifest_path = data_dir / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["server"], server)
                self.assertEqual(len(data.ships), manifest["shipCount"])
            else:
                self.assertGreater(len(data.ships), 0)
            self.assertIn("standard", data.pools)

            # 两套池子的基础不变量：答案在船表里、groupOf 覆盖全库
            for key, pool in data.pools.items():
                self.assertTrue(pool.answers, f"{key} 答案池为空")
                for index in pool.answers:
                    self.assertIn(index, data.by_index)
                self.assertEqual(
                    set(pool.group_of),
                    set(data.by_index),
                    f"{key} 的 groupOf 没有覆盖全部舰船",
                )

            # 挑一个船名在船表里唯一的答案当猜测输入，避免别名/同名船触发澄清
            name_counts: dict[str, int] = {}
            for ship in data.ships:
                if ship.name_zh:
                    name_counts[ship.name_zh] = name_counts.get(ship.name_zh, 0) + 1
            guess_text = ""
            for index in data.pools["standard"].answers:
                ship = data.by_index[index]
                if ship.name_zh and name_counts.get(ship.name_zh) == 1:
                    guess_text = ship.name_zh
                    break
            self.assertTrue(guess_text, "答案池里找不到唯一中文名")

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

                guess = app.handle(message(f"/{guess_text}", "real-2"))
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

    RealDataSmokeTest.__qualname__ = f"RealDataSmokeTest_{server}"
    RealDataSmokeTest.__name__ = f"RealDataSmokeTest_{server}"
    return RealDataSmokeTest


for _server in SERVERS:
    globals()[f"RealDataSmokeTest_{_server}"] = _make_smoke_test(_server)


if __name__ == "__main__":
    unittest.main()
