from __future__ import annotations

import random
import unittest

from tests.fixture_data import make_actor, make_data
from wowsguess.commands import StartOptions
from wowsguess.errors import CoopError
from wowsguess.models import CoopConfig, Guess, MarkdownReply, TextReply
from wowsguess.service import CoopService
from wowsguess.store import BotStore


class FakeRenderer:
    def __init__(self) -> None:
        self.starts = []
        self.boards = []
        self.guides = []

    def start(self, input):
        self.starts.append(input)
        return b"start-image"

    def board(self, input):
        self.boards.append(input)
        return b"board-image"

    def guide(self, input):
        self.guides.append(input)
        return b"guide-image"


class FailingRenderer(FakeRenderer):
    def start(self, input):
        raise RuntimeError("no font")

    def board(self, input):
        raise RuntimeError("no font")

    def guide(self, input):
        raise RuntimeError("no font")


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = make_data()
        self.store = BotStore(":memory:")
        self.clock = [1_000_000]
        self.renderer = FakeRenderer()
        self.cfg = CoopConfig()
        self.service = CoopService(
            self.data,
            self.store,
            self.cfg,
            self.renderer,
            now=lambda: self.clock[0],
            rng=random.Random(0),
        )
        self.host = make_actor("u1", "A", "owner")
        self.member = make_actor("u2", "B", "member")

    def tearDown(self) -> None:
        self.store.close()

    def start_game(self, answer: str = "P1"):
        self.service.start(self.host, StartOptions("standard", None))
        session = self.store.get_session("test:bot", "g1")
        self.assertIsNotNone(session)
        session.answer_index = answer
        self.store.save_session(session)
        return session

    def wrong_ship(self, answer: str = "P1", used: set[str] | None = None):
        used = used or set()
        pool = self.data.pools["standard"]
        answer_group = pool.group_of.get(answer)
        for ship in self.data.ships:
            if ship.index == answer or ship.index in used:
                continue
            if pool.group_of.get(ship.index) != answer_group:
                return ship
        raise AssertionError("找不到不同的船")

    def fill_guesses(self, count: int, answer: str = "P1") -> set[str]:
        session = self.store.get_session("test:bot", "g1")
        used: set[str] = set()
        for index in range(count):
            ship = self.wrong_ship(answer, used)
            used.add(ship.index)
            session.guesses.append(
                Guess(
                    ship_index=ship.index,
                    user_id=f"u{index + 2}",
                    nickname=f"P{index + 2}",
                    at=self.clock[0] - 100_000 + index,
                ),
            )
        session.updated_at = self.clock[0]
        self.store.save_session(session)
        return used

    def test_start_creates_active_session_and_image(self) -> None:
        reply = self.service.start(self.host, StartOptions("standard", None))
        self.assertEqual(reply.kind, "image")
        session = self.store.get_session("test:bot", "g1")
        self.assertEqual(session.status, "active")
        self.assertEqual(session.host_id, "u1")
        self.assertEqual(session.guesses, [])
        self.assertEqual(session.tier_range.min, 5)
        self.assertEqual(session.tier_range.max, 11)

    def test_menu_and_help(self) -> None:
        menu = self.service.menu(self.host)
        self.assertEqual(menu.kind, "image")
        self.assertEqual(self.renderer.guides[-1].kind, "menu")
        self.assertFalse(self.renderer.guides[-1].active)

        self.start_game()
        help_reply = self.service.help(self.host)
        self.assertEqual(help_reply.kind, "image")
        self.assertEqual(self.renderer.guides[-1].kind, "help")
        self.assertTrue(self.renderer.guides[-1].active)
        self.assertEqual(self.renderer.guides[-1].remaining, 8)

    def test_renderer_failure_falls_back_to_text(self) -> None:
        service = CoopService(
            self.data,
            self.store,
            self.cfg,
            FailingRenderer(),
            now=lambda: self.clock[0],
            rng=random.Random(0),
        )
        reply = service.start(self.host, StartOptions("standard", None))
        self.assertEqual(reply.kind, "text")
        self.assertIn("窝一把", reply.text)

    def test_cannot_start_twice(self) -> None:
        self.start_game()
        with self.assertRaises(CoopError) as ctx:
            self.service.start(self.member, StartOptions("standard", None))
        self.assertEqual(ctx.exception.code, "ALREADY_ACTIVE")

    def test_duplicate_guess_does_not_consume_attempt(self) -> None:
        session = self.start_game()
        ship = self.wrong_ship(session.answer_index)
        self.service.guess(self.host, ship.index)
        self.clock[0] += 6_000
        with self.assertRaises(CoopError) as ctx:
            self.service.guess(self.host, ship.index)
        self.assertEqual(ctx.exception.code, "DUPLICATE_GUESS")
        self.assertEqual(len(self.store.get_session("test:bot", "g1").guesses), 1)

    def test_global_cooldown_does_not_consume_attempt(self) -> None:
        session = self.start_game()
        first = self.wrong_ship(session.answer_index)
        self.service.guess(self.host, first.index)
        self.clock[0] += 1_000
        second = self.wrong_ship(session.answer_index, {first.index})
        with self.assertRaises(CoopError) as ctx:
            self.service.guess(self.member, second.index)
        self.assertEqual(ctx.exception.code, "GLOBAL_COOLDOWN")
        self.assertEqual(len(self.store.get_session("test:bot", "g1").guesses), 1)

    def test_user_cooldown(self) -> None:
        session = self.start_game()
        first = self.wrong_ship(session.answer_index)
        self.service.guess(self.host, first.index)
        self.clock[0] += 3_100
        second = self.wrong_ship(session.answer_index, {first.index})
        with self.assertRaises(CoopError) as ctx:
            self.service.guess(self.host, second.index)
        self.assertEqual(ctx.exception.code, "USER_COOLDOWN")

    def test_eighth_correct_guess_wins(self) -> None:
        session = self.start_game()
        self.fill_guesses(7)
        answer = self.data.by_index[session.answer_index]
        reply = self.service.guess(self.host, answer.index)
        after = self.store.get_session("test:bot", "g1")
        self.assertEqual(after.status, "won")
        self.assertEqual(len(after.guesses), 8)
        self.assertEqual(reply.kind, "image")
        self.assertIn("猜中了", reply.caption)
        self.assertEqual(self.renderer.boards[-1].answer.index, answer.index)

    def test_eighth_wrong_guess_loses(self) -> None:
        session = self.start_game()
        used = self.fill_guesses(7)
        wrong = self.wrong_ship(session.answer_index, used)
        reply = self.service.guess(self.host, wrong.index)
        after = self.store.get_session("test:bot", "g1")
        self.assertEqual(after.status, "lost")
        self.assertEqual(len(after.guesses), 8)
        self.assertIn("用完了", reply.caption)

    def test_active_board_hides_answer(self) -> None:
        session = self.start_game()
        self.service.guess(self.host, self.wrong_ship(session.answer_index).index)
        self.assertIsNone(self.renderer.boards[-1].answer)
        self.clock[0] += 6_000
        self.service.status(self.host)
        self.assertIsNone(self.renderer.boards[-1].answer)

    def test_same_group_counts_as_correct(self) -> None:
        session = self.start_game()
        session.answer_index = "P1"
        self.store.save_session(session)
        self.service.guess(self.host, "P5")
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "won")

    def test_only_host_or_admin_can_end(self) -> None:
        self.start_game()
        with self.assertRaises(CoopError) as ctx:
            self.service.end(self.member)
        self.assertEqual(ctx.exception.code, "NOT_ALLOWED")

    def test_host_can_end_and_reveal(self) -> None:
        session = self.start_game()
        self.service.guess(self.host, self.wrong_ship(session.answer_index).index)
        reply = self.service.end(self.host)
        self.assertEqual(reply.kind, "image")
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "aborted")
        self.assertIsNotNone(self.renderer.boards[-1].answer)

    def test_start_cooldown_after_end(self) -> None:
        self.start_game()
        self.service.end(self.host)
        self.clock[0] += 1_000
        with self.assertRaises(CoopError) as ctx:
            self.service.start(self.host, StartOptions("standard", None))
        self.assertEqual(ctx.exception.code, "START_COOLDOWN")
        self.clock[0] += self.cfg.start_cooldown_ms
        reply = self.service.start(self.host, StartOptions("standard", None))
        self.assertEqual(reply.kind, "image")

    def test_timeout_blocks_guesses_and_reveals_on_status(self) -> None:
        self.start_game()
        self.clock[0] += self.cfg.ttl_ms + 1
        with self.assertRaises(CoopError) as ctx:
            self.service.guess(self.host, "P2")
        self.assertEqual(ctx.exception.code, "SESSION_ENDED")
        self.service.status(self.host)
        self.assertIsNotNone(self.renderer.boards[-1].answer)

    def test_timeout_allows_new_game_without_start_cooldown(self) -> None:
        self.start_game()
        self.clock[0] += self.cfg.ttl_ms + 1
        reply = self.service.start(self.host, StartOptions("standard", None))
        self.assertEqual(reply.kind, "image")
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "active")

    def test_data_version_change_aborts_active_session(self) -> None:
        session = self.start_game()
        self.data.data_version = "changed"
        with self.assertRaises(CoopError) as ctx:
            self.service.guess(self.host, self.wrong_ship(session.answer_index).index)
        self.assertEqual(ctx.exception.code, "SESSION_ENDED")
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "aborted")

    def test_candidate_confirm_and_cancel(self) -> None:
        session = self.start_game(answer="P2")
        suggestion = self.service.guess(self.host, "阿尔")
        self.assertEqual(suggestion.kind, "text")
        self.assertIn("可能是", suggestion.text)
        self.assertEqual(len(self.store.get_session("test:bot", "g1").guesses), 0)

        confirmed = self.service.guess(self.host, "1")
        self.assertEqual(confirmed.kind, "image")
        after = self.store.get_session("test:bot", "g1")
        self.assertEqual(len(after.guesses), 1)
        self.assertIn(after.guesses[0].ship_index, {"P1", "P5"})

    def test_cancel_without_pending(self) -> None:
        self.start_game()
        reply = self.service.guess(self.host, "取消")
        self.assertEqual(reply.kind, "text")
        self.assertIn("没有待确认", reply.text)

    def test_candidate_ttl_and_numeric_without_pending(self) -> None:
        self.start_game(answer="P2")
        self.service.guess(self.host, "阿尔")
        self.clock[0] += self.cfg.suggest_ttl_ms + 1
        with self.assertRaises(CoopError) as ctx:
            self.service.guess(self.host, "1")
        self.assertEqual(ctx.exception.code, "NO_PENDING")

        with self.assertRaises(CoopError) as ctx:
            self.service.guess(self.host, "1")
        self.assertEqual(ctx.exception.code, "NO_PENDING")

    def test_stats_after_win_and_restart_skips_cooldown(self) -> None:
        session = self.start_game(answer="P1")
        self.service.guess(self.host, "P1")
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "won")

        stats = self.service.stats(self.host)
        self.assertEqual(stats.kind, "text")
        self.assertIn("总局数 1", stats.text)
        self.assertIn("胜 1", stats.text)
        self.assertIn("胜率 100.0%", stats.text)

        restarted = self.service.restart(self.host)
        self.assertEqual(restarted.kind, "image")
        after = self.store.get_session("test:bot", "g1")
        self.assertEqual(after.status, "active")
        self.assertEqual(after.difficulty, session.difficulty)
        self.assertEqual(after.tier_range, session.tier_range)

    def test_official_menu_stats_and_restart_prompt_are_markdown(self) -> None:
        official = make_actor("u1", "A", "owner", platform="qq_official:bot")
        menu = self.service.menu(official)
        self.assertIsInstance(menu, MarkdownReply)
        self.assertIn("快速上手", menu.content)
        self.assertTrue(menu.keyboard)

        self.service.start(official, StartOptions("standard", None))
        session = self.store.get_session("qq_official:bot", "g1")
        session.answer_index = "P1"
        self.store.save_session(session)
        self.service.guess(official, "P1")
        stats = self.service.stats(official)
        self.assertIsInstance(stats, MarkdownReply)
        self.assertIn("本群战绩", stats.content)

        ended = self.service.status(official)
        self.assertEqual(ended.kind, "image")
        self.assertIsInstance(ended.follow_up, MarkdownReply)
        self.assertTrue(ended.follow_up.keyboard)

    def test_official_suggestion_has_markdown_buttons(self) -> None:
        official = make_actor("u1", "A", "owner", platform="qq_official:bot")
        self.service.start(official, StartOptions("standard", None))
        session = self.store.get_session("qq_official:bot", "g1")
        session.answer_index = "P2"
        self.store.save_session(session)

        reply = self.service.guess(official, "阿尔")
        self.assertIsInstance(reply, MarkdownReply)
        self.assertTrue(reply.keyboard)
        self.assertFalse(reply.keyboard[0].enter)

    def test_non_official_end_has_text_follow_up(self) -> None:
        self.start_game()
        reply = self.service.end(self.host)
        self.assertEqual(reply.kind, "image")
        self.assertIsInstance(reply.follow_up, TextReply)
        self.assertIn("再来一局", reply.follow_up.text)


if __name__ == "__main__":
    unittest.main()
