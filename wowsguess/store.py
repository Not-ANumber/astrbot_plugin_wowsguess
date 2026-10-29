"""SQLite persistence for sessions, stats, recent answers and dedup.

Schema matches the current Node bot, including ``coop_stats``,
``coop_player_stats``, ``coop_recent_answer`` and ``stats_finalized`` so an
existing ``bot.sqlite`` can be opened without a separate migration tool.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import (
    CoopStats,
    CoopStatsLeader,
    Guess,
    Session,
    TierRange,
)

LEASE_ID = "main"
LEASE_TTL_MS = 30_000


class BotStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._tx_depth = 0
        self._db = sqlite3.connect(
            self.path,
            isolation_level=None,
            check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS coop_session (
              platform     TEXT NOT NULL,
              group_id     TEXT NOT NULL,
              session_id   TEXT NOT NULL,
              status       TEXT NOT NULL,
              answer_index TEXT NOT NULL,
              difficulty   TEXT NOT NULL,
              tier_range   TEXT,
              guesses      TEXT NOT NULL,
              muted        TEXT NOT NULL DEFAULT '[]',
              host_id      TEXT NOT NULL,
              host_name    TEXT NOT NULL,
              data_version TEXT NOT NULL,
              created_at   INTEGER NOT NULL,
              updated_at   INTEGER NOT NULL,
              stats_finalized INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (platform, group_id)
            );

            CREATE TABLE IF NOT EXISTS coop_stats (
              platform         TEXT NOT NULL,
              group_id         TEXT NOT NULL,
              games            INTEGER NOT NULL DEFAULT 0,
              wins             INTEGER NOT NULL DEFAULT 0,
              losses           INTEGER NOT NULL DEFAULT 0,
              aborted          INTEGER NOT NULL DEFAULT 0,
              total_guesses    INTEGER NOT NULL DEFAULT 0,
              best_attempts    INTEGER,
              current_streak   INTEGER NOT NULL DEFAULT 0,
              best_streak      INTEGER NOT NULL DEFAULT 0,
              last_status      TEXT,
              last_difficulty  TEXT,
              last_attempts    INTEGER,
              last_ended_at    INTEGER,
              updated_at       INTEGER NOT NULL,
              PRIMARY KEY (platform, group_id)
            );

            CREATE TABLE IF NOT EXISTS coop_player_stats (
              platform   TEXT NOT NULL,
              group_id   TEXT NOT NULL,
              user_id    TEXT NOT NULL,
              nickname   TEXT NOT NULL,
              guesses    INTEGER NOT NULL DEFAULT 0,
              wins       INTEGER NOT NULL DEFAULT 0,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY (platform, group_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS coop_recent_answer (
              platform   TEXT NOT NULL,
              group_id   TEXT NOT NULL,
              answers    TEXT NOT NULL,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY (platform, group_id)
            );

            CREATE TABLE IF NOT EXISTS bot_seen_message (
              platform   TEXT NOT NULL,
              message_id TEXT NOT NULL,
              seen_at    INTEGER NOT NULL,
              PRIMARY KEY (platform, message_id)
            );

            CREATE TABLE IF NOT EXISTS bot_lease (
              id           TEXT PRIMARY KEY,
              holder       TEXT NOT NULL,
              heartbeat_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meta (
              key   TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        self._db.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '2')",
        )
        columns = {
            row["name"]
            for row in self._db.execute("PRAGMA table_info(coop_session)").fetchall()
        }
        if "stats_finalized" not in columns:
            self._db.execute(
                "ALTER TABLE coop_session ADD COLUMN stats_finalized INTEGER NOT NULL DEFAULT 0",
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            if self._tx_depth > 0:
                yield
                return
            self._db.execute("BEGIN IMMEDIATE")
            self._tx_depth += 1
            try:
                yield
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            finally:
                self._tx_depth -= 1

    def get_session(self, platform: str, group_id: str) -> Session | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM coop_session WHERE platform = ? AND group_id = ?",
                (platform, group_id),
            ).fetchone()
        return self._session_from_row(row) if row is not None else None

    def get_recent_answers(self, platform: str, group_id: str) -> list[str]:
        with self._lock:
            row = self._db.execute(
                "SELECT answers FROM coop_recent_answer WHERE platform = ? AND group_id = ?",
                (platform, group_id),
            ).fetchone()
        if row is None:
            return []
        try:
            parsed = json.loads(row["answers"])
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, str)]

    def remember_answer(
        self,
        platform: str,
        group_id: str,
        answer_index: str,
        keep: int,
        at: int,
    ) -> None:
        with self.transaction():
            previous = self.get_recent_answers(platform, group_id)
            answers = [answer_index, *[item for item in previous if item != answer_index]]
            answers = answers[: max(1, keep)]
            self._db.execute(
                """
                INSERT INTO coop_recent_answer (platform, group_id, answers, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(platform, group_id) DO UPDATE SET
                  answers = excluded.answers,
                  updated_at = excluded.updated_at
                """,
                (platform, group_id, json.dumps(answers, ensure_ascii=False), at),
            )

    def get_stats(self, platform: str, group_id: str) -> CoopStats:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM coop_stats WHERE platform = ? AND group_id = ?",
                (platform, group_id),
            ).fetchone()
            guesser_rows = self._db.execute(
                """
                SELECT nickname, guesses AS count
                  FROM coop_player_stats
                 WHERE platform = ? AND group_id = ?
                 ORDER BY guesses DESC, updated_at DESC
                 LIMIT 3
                """,
                (platform, group_id),
            ).fetchall()
            winner_rows = self._db.execute(
                """
                SELECT nickname, wins AS count
                  FROM coop_player_stats
                 WHERE platform = ? AND group_id = ? AND wins > 0
                 ORDER BY wins DESC, updated_at DESC
                 LIMIT 3
                """,
                (platform, group_id),
            ).fetchall()

        if row is None:
            return CoopStats()
        return CoopStats(
            games=int(row["games"]),
            wins=int(row["wins"]),
            losses=int(row["losses"]),
            aborted=int(row["aborted"]),
            total_guesses=int(row["total_guesses"]),
            best_attempts=(
                None if row["best_attempts"] is None else int(row["best_attempts"])
            ),
            current_streak=int(row["current_streak"]),
            best_streak=int(row["best_streak"]),
            last_status=row["last_status"],
            last_difficulty=row["last_difficulty"],
            last_attempts=(
                None if row["last_attempts"] is None else int(row["last_attempts"])
            ),
            last_ended_at=(
                None if row["last_ended_at"] is None else int(row["last_ended_at"])
            ),
            top_guessers=tuple(
                CoopStatsLeader(nickname=leader["nickname"], count=int(leader["count"]))
                for leader in guesser_rows
            ),
            top_winners=tuple(
                CoopStatsLeader(nickname=leader["nickname"], count=int(leader["count"]))
                for leader in winner_rows
            ),
        )

    def save_session(self, session: Session) -> None:
        guesses = json.dumps(
            [_guess_to_json(guess) for guess in session.guesses],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        tier_range = (
            json.dumps(session.tier_range.to_dict(), separators=(",", ":"))
            if session.tier_range
            else None
        )
        with self.transaction():
            existing = self._db.execute(
                "SELECT * FROM coop_session WHERE platform = ? AND group_id = ?",
                (session.platform, session.group_id),
            ).fetchone()
            is_new_session = (
                existing is None or existing["session_id"] != session.session_id
            )
            if (
                existing is not None
                and is_new_session
                and existing["status"] != "active"
            ):
                self._finalize_stats_from_row(existing, int(existing["updated_at"]))

            self._db.execute(
                """
                INSERT INTO coop_session
                  (platform, group_id, session_id, status, answer_index, difficulty,
                   tier_range, guesses, muted, host_id, host_name, data_version,
                   created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?)
                ON CONFLICT(platform, group_id) DO UPDATE SET
                  session_id = excluded.session_id,
                  status = excluded.status,
                  answer_index = excluded.answer_index,
                  difficulty = excluded.difficulty,
                  tier_range = excluded.tier_range,
                  guesses = excluded.guesses,
                  muted = '[]',
                  host_id = excluded.host_id,
                  host_name = excluded.host_name,
                  data_version = excluded.data_version,
                  created_at = excluded.created_at,
                  updated_at = excluded.updated_at
                """,
                (
                    session.platform,
                    session.group_id,
                    session.session_id,
                    session.status,
                    session.answer_index,
                    session.difficulty,
                    tier_range,
                    guesses,
                    session.host_id,
                    session.host_name,
                    session.data_version,
                    session.created_at,
                    session.updated_at,
                ),
            )

            if is_new_session or session.status == "active":
                self._db.execute(
                    """
                    UPDATE coop_session
                       SET stats_finalized = 0
                     WHERE platform = ? AND group_id = ? AND session_id = ?
                    """,
                    (session.platform, session.group_id, session.session_id),
                )

            if session.status != "active":
                self._finalize_stats_from_session(session, session.updated_at)

    def _session_from_row(self, row: sqlite3.Row) -> Session:
        guesses = [
            _guess_from_json(item)
            for item in json.loads(row["guesses"] or "[]")
        ]
        tier_raw = json.loads(row["tier_range"]) if row["tier_range"] else None
        return Session(
            platform=row["platform"],
            group_id=row["group_id"],
            session_id=row["session_id"],
            status=row["status"],
            answer_index=row["answer_index"],
            difficulty=row["difficulty"],
            tier_range=TierRange.from_json(tier_raw),
            guesses=guesses,
            host_id=row["host_id"],
            host_name=row["host_name"],
            data_version=row["data_version"],
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    def _finalize_stats_from_row(
        self,
        row: sqlite3.Row,
        ended_at: int,
        status_override: str | None = None,
    ) -> bool:
        status = status_override or row["status"]
        if status == "active" or int(row["stats_finalized"] or 0) == 1:
            return False
        session = self._session_from_row(row)
        session.status = status
        self._record_stats(session, ended_at)
        self._db.execute(
            """
            UPDATE coop_session
               SET stats_finalized = 1
             WHERE platform = ? AND group_id = ? AND session_id = ?
            """,
            (row["platform"], row["group_id"], row["session_id"]),
        )
        return True

    def _finalize_stats_from_session(self, session: Session, ended_at: int) -> bool:
        if session.status == "active":
            return False
        row = self._db.execute(
            """
            SELECT stats_finalized
              FROM coop_session
             WHERE platform = ? AND group_id = ? AND session_id = ?
            """,
            (session.platform, session.group_id, session.session_id),
        ).fetchone()
        if row is None or int(row["stats_finalized"] or 0) == 1:
            return False
        self._record_stats(session, ended_at)
        self._db.execute(
            """
            UPDATE coop_session
               SET stats_finalized = 1
             WHERE platform = ? AND group_id = ? AND session_id = ?
            """,
            (session.platform, session.group_id, session.session_id),
        )
        return True

    def _record_stats(self, session: Session, ended_at: int) -> None:
        won = session.status == "won"
        aborted = session.status == "aborted"
        attempts = len(session.guesses)
        previous = self._db.execute(
            "SELECT * FROM coop_stats WHERE platform = ? AND group_id = ?",
            (session.platform, session.group_id),
        ).fetchone()

        games = int(previous["games"] if previous else 0) + 1
        wins = int(previous["wins"] if previous else 0) + (1 if won else 0)
        losses = int(previous["losses"] if previous else 0) + (0 if won else 1)
        aborted_count = int(previous["aborted"] if previous else 0) + (1 if aborted else 0)
        total_guesses = int(previous["total_guesses"] if previous else 0) + attempts
        previous_best = (
            None
            if previous is None or previous["best_attempts"] is None
            else int(previous["best_attempts"])
        )
        best_attempts = (
            attempts
            if won and attempts > 0 and previous_best is None
            else min(previous_best, attempts)
            if won and attempts > 0 and previous_best is not None
            else previous_best
        )
        current_streak = int(previous["current_streak"] if previous else 0) + 1 if won else 0
        best_streak = max(int(previous["best_streak"] if previous else 0), current_streak)

        self._db.execute(
            """
            INSERT INTO coop_stats
              (platform, group_id, games, wins, losses, aborted, total_guesses,
               best_attempts, current_streak, best_streak,
               last_status, last_difficulty, last_attempts, last_ended_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, group_id) DO UPDATE SET
              games = excluded.games,
              wins = excluded.wins,
              losses = excluded.losses,
              aborted = excluded.aborted,
              total_guesses = excluded.total_guesses,
              best_attempts = excluded.best_attempts,
              current_streak = excluded.current_streak,
              best_streak = excluded.best_streak,
              last_status = excluded.last_status,
              last_difficulty = excluded.last_difficulty,
              last_attempts = excluded.last_attempts,
              last_ended_at = excluded.last_ended_at,
              updated_at = excluded.updated_at
            """,
            (
                session.platform,
                session.group_id,
                games,
                wins,
                losses,
                aborted_count,
                total_guesses,
                best_attempts,
                current_streak,
                best_streak,
                session.status,
                session.difficulty,
                attempts,
                ended_at,
                ended_at,
            ),
        )

        players: dict[str, dict[str, Any]] = {}
        for guess in session.guesses:
            player = players.setdefault(
                guess.user_id,
                {"nickname": guess.nickname, "guesses": 0, "wins": 0},
            )
            player["nickname"] = guess.nickname
            player["guesses"] += 1
        if won and session.guesses:
            winner = session.guesses[-1]
            player = players.get(winner.user_id)
            if player is not None:
                player["wins"] += 1

        for user_id, player in players.items():
            self._db.execute(
                """
                INSERT INTO coop_player_stats
                  (platform, group_id, user_id, nickname, guesses, wins, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, group_id, user_id) DO UPDATE SET
                  nickname = excluded.nickname,
                  guesses = guesses + excluded.guesses,
                  wins = wins + excluded.wins,
                  updated_at = excluded.updated_at
                """,
                (
                    session.platform,
                    session.group_id,
                    user_id,
                    player["nickname"],
                    player["guesses"],
                    player["wins"],
                    ended_at,
                ),
            )

    def seen_message(self, platform: str, message_id: str, now: int) -> bool:
        """Return True for a new message, False for a duplicate."""
        with self.transaction():
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO bot_seen_message (platform, message_id, seen_at) VALUES (?, ?, ?)",
                (platform, message_id, now),
            )
            return cursor.rowcount > 0

    def prune_seen(self, before: int) -> None:
        with self.transaction():
            self._db.execute(
                "DELETE FROM bot_seen_message WHERE seen_at < ?",
                (before,),
            )

    def abort_sessions_with_other_version(
        self,
        data_version: str,
        now: int | None = None,
    ) -> int:
        ended_at = now if now is not None else int(time.time() * 1000)
        with self.transaction():
            rows = self._db.execute(
                """
                SELECT * FROM coop_session
                 WHERE status = 'active' AND data_version <> ?
                """,
                (data_version,),
            ).fetchall()
            for row in rows:
                self._finalize_stats_from_row(row, ended_at, "aborted")
                self._db.execute(
                    """
                    UPDATE coop_session
                       SET status = 'aborted'
                     WHERE platform = ? AND group_id = ? AND session_id = ?
                    """,
                    (row["platform"], row["group_id"], row["session_id"]),
                )
            return len(rows)

    def mark_expired(self, now: int, ttl_ms: int) -> int:
        with self.transaction():
            rows = self._db.execute(
                """
                SELECT * FROM coop_session
                 WHERE status = 'active' AND updated_at < ?
                """,
                (now - ttl_ms,),
            ).fetchall()
            for row in rows:
                self._finalize_stats_from_row(row, now, "aborted")
                self._db.execute(
                    """
                    UPDATE coop_session
                       SET status = 'aborted'
                     WHERE platform = ? AND group_id = ? AND session_id = ?
                    """,
                    (row["platform"], row["group_id"], row["session_id"]),
                )
            return len(rows)

    def acquire_lease(self, holder: str, now: int) -> bool:
        with self.transaction():
            row = self._db.execute(
                "SELECT holder, heartbeat_at FROM bot_lease WHERE id = ?",
                (LEASE_ID,),
            ).fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO bot_lease (id, holder, heartbeat_at) VALUES (?, ?, ?)",
                    (LEASE_ID, holder, now),
                )
                return True
            if row["holder"] == holder or now - int(row["heartbeat_at"]) > LEASE_TTL_MS:
                self._db.execute(
                    "UPDATE bot_lease SET holder = ?, heartbeat_at = ? WHERE id = ?",
                    (holder, now, LEASE_ID),
                )
                return True
            return False

    def heartbeat(self, holder: str, now: int) -> bool:
        with self.transaction():
            cursor = self._db.execute(
                "UPDATE bot_lease SET heartbeat_at = ? WHERE id = ? AND holder = ?",
                (now, LEASE_ID, holder),
            )
            return cursor.rowcount > 0

    def release_lease(self, holder: str) -> None:
        with self.transaction():
            self._db.execute(
                "DELETE FROM bot_lease WHERE id = ? AND holder = ?",
                (LEASE_ID, holder),
            )


def _guess_to_json(guess: Guess) -> dict[str, Any]:
    return {
        "shipIndex": guess.ship_index,
        "userId": guess.user_id,
        "nickname": guess.nickname,
        "at": guess.at,
    }


def _guess_from_json(raw: dict[str, Any]) -> Guess:
    return Guess(
        ship_index=str(raw.get("shipIndex", raw.get("ship_index", ""))),
        user_id=str(raw.get("userId", raw.get("user_id", ""))),
        nickname=str(raw.get("nickname", "")),
        at=int(raw.get("at", 0)),
    )
