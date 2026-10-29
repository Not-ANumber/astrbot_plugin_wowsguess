from __future__ import annotations

import random
import unittest

from tests.fixture_data import make_data, make_message
from tests.test_service import FakeRenderer
from wowsguess.app import GameApp
from wowsguess.models import CoopConfig
from wowsguess.store import BotStore


class AppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = make_data()
        self.store = BotStore(":memory:")
        self.clock = [1_000_000]
        self.renderer = FakeRenderer()
        self.app = GameApp(
            self.data,
            self.store,
            CoopConfig(),
            self.renderer,
            now=lambda: self.clock[0],
            rng=random.Random(0),
        )

    def tearDown(self) -> None:
        self.store.close()

    def test_ignores_non_directed_messages(self) -> None:
        self.assertIsNone(self.app.handle(make_message("/窝一把", directed=False)))

    def test_start_and_dedup(self) -> None:
        reply = self.app.handle(make_message("/窝一把", message_id="m-start"))
        self.assertEqual(reply.kind, "image")

        duplicate = self.app.handle(make_message("/窝一把", message_id="m-start"))
        self.assertIsNone(duplicate)

        session = self.store.get_session("test:bot", "g1")
        self.assertEqual(session.status, "active")
        session.answer_index = "P1"
        self.store.save_session(session)

    def test_guess_status_and_menu(self) -> None:
        self.app.handle(make_message("/窝一把", message_id="m-start"))

        menu = self.app.handle(make_message("", message_id="m-menu"))
        self.assertEqual(menu.kind, "image")
        self.assertEqual(self.renderer.guides[-1].kind, "menu")

        reply = self.app.handle(make_message("/贝塔", message_id="m-guess"))
        self.assertEqual(reply.kind, "image")
        self.assertEqual(len(self.store.get_session("test:bot", "g1").guesses), 1)

        status = self.app.handle(make_message("/状态", message_id="m-status"))
        self.assertEqual(status.kind, "image")

        help_reply = self.app.handle(make_message("/帮助", message_id="m-help"))
        self.assertEqual(help_reply.kind, "image")

    def test_unknown_slash_text_returns_unknown_ship(self) -> None:
        self.app.handle(make_message("/窝一把", message_id="m-start"))
        reply = self.app.handle(make_message("/zzzz-not-a-ship", message_id="m-unknown"))
        self.assertEqual(reply.kind, "text")
        self.assertIn("没找到", reply.text)

    def test_end_by_host(self) -> None:
        self.app.handle(make_message("/窝一把", message_id="m-start"))
        reply = self.app.handle(make_message("/结束", message_id="m-end"))
        self.assertEqual(reply.kind, "image")
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "aborted")

    def test_member_cannot_end(self) -> None:
        self.app.handle(make_message("/窝一把", message_id="m-start"))
        reply = self.app.handle(
            make_message(
                "/结束",
                message_id="m-end",
                user_id="u2",
                nickname="B",
                role="member",
            ),
        )
        self.assertEqual(reply.kind, "text")
        self.assertIn("房主", reply.text)

    def test_stats_restart_and_candidates(self) -> None:
        self.app.handle(make_message("/窝一把", message_id="m-start"))
        session = self.store.get_session("test:bot", "g1")
        session.answer_index = "P2"
        self.store.save_session(session)

        suggestion = self.app.handle(make_message("/阿尔", message_id="m-suggest"))
        self.assertEqual(suggestion.kind, "text")
        self.assertIn("可能是", suggestion.text)

        confirmed = self.app.handle(make_message("/1", message_id="m-confirm"))
        self.assertEqual(confirmed.kind, "image")
        self.assertEqual(len(self.store.get_session("test:bot", "g1").guesses), 1)

        ended = self.app.handle(make_message("/结束", message_id="m-end"))
        self.assertEqual(ended.kind, "image")
        self.assertIsNotNone(ended.follow_up)

        stats = self.app.handle(make_message("/统计", message_id="m-stats"))
        self.assertEqual(stats.kind, "text")
        self.assertIn("总局数 1", stats.text)

        restarted = self.app.handle(make_message("/再来一局", message_id="m-restart"))
        self.assertEqual(restarted.kind, "image")
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "active")

    def test_cancel_candidate(self) -> None:
        self.app.handle(make_message("/窝一把", message_id="m-start"))
        session = self.store.get_session("test:bot", "g1")
        session.answer_index = "P2"
        self.store.save_session(session)
        self.app.handle(make_message("/阿尔", message_id="m-suggest"))
        cancelled = self.app.handle(make_message("/取消", message_id="m-cancel"))
        self.assertEqual(cancelled.kind, "text")
        self.assertIn("已取消", cancelled.text)


if __name__ == "__main__":
    unittest.main()
