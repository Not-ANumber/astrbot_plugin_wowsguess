from __future__ import annotations

import unittest

from wowsguess.models import Guess, Session, TierRange
from wowsguess.store import BotStore


def make_session(**overrides):
    base = dict(
        platform="test:bot",
        group_id="g1",
        session_id="s1",
        status="active",
        answer_index="P1",
        difficulty="standard",
        tier_range=TierRange(5, 11),
        guesses=[Guess("P2", "u2", "B", 1000)],
        host_id="u1",
        host_name="A",
        data_version="fixture-1",
        created_at=1000,
        updated_at=1000,
    )
    base.update(overrides)
    return Session(**base)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = BotStore(":memory:")

    def tearDown(self) -> None:
        self.store.close()

    def test_session_round_trip(self) -> None:
        session = make_session()
        self.store.save_session(session)
        loaded = self.store.get_session("test:bot", "g1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_id, "s1")
        self.assertEqual(loaded.tier_range, TierRange(5, 11))
        self.assertEqual(len(loaded.guesses), 1)
        self.assertEqual(loaded.guesses[0].ship_index, "P2")
        self.assertEqual(loaded.guesses[0].user_id, "u2")

    def test_seen_message_dedup(self) -> None:
        self.assertTrue(self.store.seen_message("test:bot", "m1", 1000))
        self.assertFalse(self.store.seen_message("test:bot", "m1", 1001))
        self.assertTrue(self.store.seen_message("test:bot", "m2", 1002))
        self.store.prune_seen(2000)
        self.assertTrue(self.store.seen_message("test:bot", "m1", 2001))

    def test_abort_other_version(self) -> None:
        self.store.save_session(make_session(data_version="old"))
        self.store.save_session(make_session(group_id="g2", data_version="old", session_id="s2"))
        changed = self.store.abort_sessions_with_other_version("new")
        self.assertEqual(changed, 2)
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "aborted")
        self.assertEqual(self.store.get_session("test:bot", "g2").status, "aborted")

    def test_mark_expired(self) -> None:
        self.store.save_session(make_session(updated_at=1000))
        self.assertEqual(self.store.mark_expired(2999, 2000), 0)
        self.assertEqual(self.store.mark_expired(3001, 2000), 1)
        self.assertEqual(self.store.get_session("test:bot", "g1").status, "aborted")

    def test_lease(self) -> None:
        self.assertTrue(self.store.acquire_lease("holder-a", 1000))
        self.assertFalse(self.store.acquire_lease("holder-b", 1000))
        self.assertTrue(self.store.heartbeat("holder-a", 2000))
        self.assertFalse(self.store.heartbeat("holder-b", 2000))
        self.store.release_lease("holder-a")
        self.assertTrue(self.store.acquire_lease("holder-b", 3000))

    def test_stats_finalized_once(self) -> None:
        session = make_session(status="active", guesses=[Guess("P1", "u1", "A", 1000)])
        self.store.save_session(session)
        session.status = "won"
        session.updated_at = 2000
        self.store.save_session(session)
        self.store.save_session(session)
        stats = self.store.get_stats("test:bot", "g1")
        self.assertEqual(stats.games, 1)
        self.assertEqual(stats.wins, 1)
        self.assertEqual(stats.total_guesses, 1)
        self.assertEqual(stats.best_attempts, 1)
        self.assertEqual(stats.top_winners[0].nickname, "A")

    def test_new_session_finalizes_previous(self) -> None:
        first = make_session(status="won", guesses=[Guess("P1", "u1", "A", 1000)])
        self.store.save_session(first)
        second = make_session(
            session_id="s2",
            status="active",
            answer_index="P2",
            guesses=[],
        )
        self.store.save_session(second)
        stats = self.store.get_stats("test:bot", "g1")
        self.assertEqual(stats.games, 1)
        self.assertEqual(stats.wins, 1)
        self.assertEqual(self.store.get_session("test:bot", "g1").session_id, "s2")

    def test_abort_and_expire_finalize_stats(self) -> None:
        session = make_session(status="active")
        self.store.save_session(session)
        self.assertEqual(self.store.abort_sessions_with_other_version("new", now=5000), 1)
        stats = self.store.get_stats("test:bot", "g1")
        self.assertEqual(stats.games, 1)
        self.assertEqual(stats.losses, 1)
        self.assertEqual(stats.aborted, 1)

        session2 = make_session(session_id="s2", status="active", answer_index="P2")
        self.store.save_session(session2)
        self.assertEqual(self.store.mark_expired(10_000, 1_000), 1)
        stats = self.store.get_stats("test:bot", "g1")
        self.assertEqual(stats.games, 2)
        self.assertEqual(stats.aborted, 2)

    def test_recent_answers(self) -> None:
        self.store.remember_answer("test:bot", "g1", "P1", 3, 1000)
        self.store.remember_answer("test:bot", "g1", "P2", 3, 2000)
        self.store.remember_answer("test:bot", "g1", "P1", 3, 3000)
        self.assertEqual(self.store.get_recent_answers("test:bot", "g1"), ["P1", "P2"])


if __name__ == "__main__":
    unittest.main()
