"""Co-op mode state machine.

Ported from the current ``packages/bot/src/coop/service.ts``: candidate
confirmation, fuzzy typo handling, stats, rematch, Markdown replies and
follow-up prompts. The service is synchronous; the adapter runs it in a thread.
"""

from __future__ import annotations

import logging
import math
import random
import time
import unicodedata
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from .about import BILI_ID, QQ_GROUP, SITE_URL
from .data import (
    answers_for,
    difficulty_label,
    pool_for,
    tier_label,
)
from .engine import (
    compare_attributes,
    display_name,
    is_correct_guess,
    normalize_pool_tier_range,
)
from .errors import CoopError
from .models import (
    MAX_TIER,
    MIN_ANSWER_TIER,
    Actor,
    BoardRenderInput,
    BoardRow,
    CommandButton,
    CoopConfig,
    Feedback,
    GameData,
    Guess,
    HelpRenderInput,
    ImageReply,
    MarkdownReply,
    Reply,
    Session,
    Ship,
    StartRenderInput,
    TextReply,
    TierRange,
)
from .random import pick_avoiding_recent
from .render.markdown import render_menu_markdown
from .render.text import render_board_text, render_start_text, ship_subtitle
from .resolve import ResolveCandidates, ResolveMatch, resolve_ship
from .store import BotStore

logger = logging.getLogger(__name__)

MAX_PENDING = 1024
RECENT_ANSWER_KEEP = 10


class CoopRenderer(Protocol):
    def start(self, input: StartRenderInput) -> bytes: ...

    def board(self, input: BoardRenderInput) -> bytes: ...

    def guide(self, input: HelpRenderInput) -> bytes: ...


@dataclass
class PendingSuggestion:
    session_id: str
    candidates: list[str]
    at: int


def is_official_platform(platform: str) -> bool:
    return platform == "official" or platform.startswith("qq_official")


def _is_cancel_query(query: str) -> bool:
    text = unicodedata.normalize("NFKC", query).strip().lower()
    return text in {"取消", "cancel"}


def _numeric_choice(query: str) -> int | None:
    text = unicodedata.normalize("NFKC", query).strip()
    if not text.isdigit():
        return None
    return int(text)


def _truncate_query(query: str) -> str:
    text = " ".join(query.split()).strip()
    return f"{text[:30]}…" if len(text) > 30 else text


def _truncate_button_label(text: str) -> str:
    compact = " ".join(text.split()).strip()
    return f"{compact[:11]}…" if len(compact) > 12 else compact


def _format_relative(ended_at: int, now: int) -> str:
    delta = max(0, now - ended_at)
    if delta < 60_000:
        return "刚刚"
    if delta < 60 * 60_000:
        return f"{delta // 60_000} 分钟前"
    if delta < 24 * 60 * 60_000:
        return f"{delta // (60 * 60_000)} 小时前"
    return f"{delta // (24 * 60 * 60_000)} 天前"


def _format_leaders(label: str, leaders, unit: str) -> str | None:
    if not leaders:
        return None
    return f"{label}：" + " · ".join(
        f"{leader.nickname} {leader.count} {unit}" for leader in leaders
    )


class CoopService:
    def __init__(
        self,
        data: GameData,
        store: BotStore,
        cfg: CoopConfig | None = None,
        renderer: CoopRenderer | None = None,
        now: Callable[[], int] | None = None,
        rng: random.Random | random.SystemRandom | None = None,
    ) -> None:
        self.data = data
        self.store = store
        self.cfg = cfg or CoopConfig()
        self.renderer = renderer
        self.now = now or (lambda: int(time.time() * 1000))
        self.rng = rng or random.SystemRandom()
        self.pending: dict[str, PendingSuggestion] = {}

    def menu(self, actor: Actor) -> Reply:
        session = self.load(actor)
        active = bool(session and session.status == "active")
        remaining = self.remaining(session) if active and session else 0
        input = HelpRenderInput(
            kind="menu",
            active=active,
            remaining=remaining,
            max_attempts=self.cfg.max_attempts,
        )
        fallback = "\n".join(
            [
                "【窝一把 · 快速上手】",
                f"当前有进行中的局，剩余 {remaining} 次。" if active else "当前没有进行中的局。",
                "",
                "@机器人 /窝一把 或 /ccb — 开一局",
                "  难度 n=普通，h=困难；等级 9-11",
                "@机器人 /秋月 — 猜船",
                "@机器人 /状态 — 当前棋盘",
                "@机器人 /统计 — 本群战绩",
                "@机器人 /结束 — 房主/群管理结束",
                "@机器人 /再来一局 — 沿用上一局配置",
                "@机器人 /帮助 — 完整说明",
                "",
                "关于：",
                f"网站：{SITE_URL}",
                f"B站：{BILI_ID}",
                f"QQ群：{QQ_GROUP}",
            ],
        )
        if is_official_platform(actor.platform):
            return MarkdownReply(
                content=render_menu_markdown(input),
                keyboard=tuple(self._quick_action_buttons(active)),
                fallback_text=fallback,
            )
        return self._image_or_text(lambda: self._render_guide(input), fallback)

    def help(self, actor: Actor | None = None) -> Reply:
        session = self.load(actor) if actor else None
        active = bool(session and session.status == "active")
        remaining = self.remaining(session) if active and session else 0
        input = HelpRenderInput(
            kind="help",
            active=active,
            remaining=remaining,
            max_attempts=self.cfg.max_attempts,
        )
        fallback = "\n".join(
            [
                "【窝一把 · 合作模式】",
                f"全群共用 {self.cfg.max_attempts} 次机会，猜中即胜，用尽即负。",
                "",
                "开局：",
                "@机器人 /窝一把 或 /ccb [n|h|普通|困难] [9-11]",
                "  默认普通 · T5–T11；n=普通，h=困难",
                "  等级 9-11 与 T9-T11 等价",
                "",
                "查看与结束：",
                "@机器人 /状态 — 看当前棋盘图",
                "@机器人 /统计 — 看本群战绩",
                "@机器人 /结束 — 房主/群管理提前结束",
                "@机器人 /再来一局 — 结束后沿用上一局配置",
                "",
                "猜船：",
                "@机器人 /秋月 — 猜一次",
                "  支持拼音和错字；近似船名会先列候选",
                "  候选回复 /1 确认，/取消 放弃",
                "  重复船、未知船、冷却中的猜测不消耗次数",
                "",
                "关于：",
                f"单人模式 / 多人房间：请访问网页版 {SITE_URL.removeprefix('https://').removeprefix('http://')}",
                f"B站：{BILI_ID}",
                f"QQ群：{QQ_GROUP}",
            ],
        )
        return self._image_or_text(lambda: self._render_guide(input), fallback)

    def stats(self, actor: Actor) -> Reply:
        stats = self.store.get_stats(actor.platform, actor.group_id)
        if stats.games == 0:
            return TextReply("本群还没有已完成的战绩。发送「/窝一把」开一局。")

        loss_line = (
            f"负 {stats.losses}（含中止 {stats.aborted}）"
            if stats.aborted > 0
            else f"负 {stats.losses}"
        )
        average = f"{stats.total_guesses / stats.games:.1f}"
        lines = [
            "窝一把 · 本群战绩",
            f"总局数 {stats.games} · 胜 {stats.wins} · {loss_line}",
            f"胜率 {(stats.wins / stats.games) * 100:.1f}%",
            f"平均 {average} 猜"
            + (f" · 最快 {stats.best_attempts} 猜" if stats.best_attempts is not None else ""),
            f"当前连胜 {stats.current_streak} · 最长连胜 {stats.best_streak}",
        ]

        guessers = _format_leaders("猜得最多", stats.top_guessers, "次")
        if guessers:
            lines.append(guessers)
        winners = _format_leaders("猜中最多", stats.top_winners, "次")
        if winners:
            lines.append(winners)

        if stats.last_status and stats.last_ended_at is not None:
            status = (
                "胜"
                if stats.last_status == "won"
                else "负"
                if stats.last_status == "lost"
                else "中止（计负）"
            )
            difficulty = (
                difficulty_label(self.data, stats.last_difficulty)
                if stats.last_difficulty
                else "未知难度"
            )
            lines.append(
                f"最近一局：{status} · {difficulty} · {stats.last_attempts or 0} 猜 · "
                f"{_format_relative(stats.last_ended_at, self.now())}",
            )

        text = "\n".join(lines)
        if is_official_platform(actor.platform):
            return MarkdownReply(
                content="\n".join(
                    ["## 窝一把 · 本群战绩", "", *[f"- {line}" for line in lines[1:]]],
                ),
                fallback_text=text,
            )
        return TextReply(text)

    def _quick_action_buttons(self, active: bool) -> list[CommandButton]:
        stats = CommandButton(label="本群战绩", data="/统计")
        if active:
            return [CommandButton(label="查看当前棋盘", data="/状态"), stats]
        return [
            CommandButton(label="普通开局", data="/窝一把"),
            CommandButton(label="困难开局", data="/窝一把 h"),
            stats,
        ]

    def start(self, actor: Actor, options: "StartOptionsLike") -> Reply:
        return self._begin(actor, options, False)

    def restart(self, actor: Actor) -> Reply:
        previous = self.load(actor)
        if previous is None:
            raise CoopError("NO_SESSION", "本群还没有上一局，发送「/窝一把」开一局。")
        return self._begin(
            actor,
            _SimpleStartOptions(previous.difficulty, previous.tier_range),
            True,
        )

    def _begin(
        self,
        actor: Actor,
        options: "StartOptionsLike",
        skip_cooldown: bool,
    ) -> Reply:
        now = self.now()
        existing = self.load(actor)
        if existing is not None and existing.status == "active":
            raise CoopError(
                "ALREADY_ACTIVE",
                f"本群已有一局进行中，剩余 {self.remaining(existing)} 次。发送「/状态」查看棋盘。",
            )
        if (
            not skip_cooldown
            and existing is not None
            and now - existing.updated_at < self.cfg.start_cooldown_ms
        ):
            wait = math.ceil(
                (self.cfg.start_cooldown_ms - (now - existing.updated_at)) / 1000,
            )
            raise CoopError("START_COOLDOWN", f"上一局刚结束，{wait} 秒后再开新局。")
        if options.difficulty_key not in self.data.pools:
            raise CoopError(
                "BAD_DIFFICULTY",
                f"没有「{options.difficulty_key}」这一档难度。",
            )

        tier_range = normalize_pool_tier_range(options.tier_range) or TierRange(
            min=MIN_ANSWER_TIER,
            max=MAX_TIER,
        )
        answers = answers_for(self.data, options.difficulty_key, tier_range)
        if not answers:
            raise CoopError("EMPTY_POOL", "这个等级范围里没有可用的答案。")
        if existing is not None:
            self._clear_session_pending(existing.session_id)

        recent = set(self.store.get_recent_answers(actor.platform, actor.group_id))
        answer_index = pick_avoiding_recent(
            answers,
            recent,
            lambda length: self.rng.randrange(length),
        )
        if answer_index is None:
            raise CoopError("EMPTY_POOL", "这个等级范围里没有可用的答案。")
        self.store.remember_answer(
            actor.platform,
            actor.group_id,
            answer_index,
            RECENT_ANSWER_KEEP,
            now,
        )

        session = Session(
            platform=actor.platform,
            group_id=actor.group_id,
            session_id=str(uuid.uuid4()),
            status="active",
            answer_index=answer_index,
            difficulty=options.difficulty_key,
            tier_range=tier_range,
            guesses=[],
            host_id=actor.user_id,
            host_name=actor.nickname,
            data_version=self.data.data_version,
            created_at=now,
            updated_at=now,
        )
        self.store.save_session(session)

        input = StartRenderInput(
            host_name=actor.nickname,
            difficulty_label=difficulty_label(self.data, options.difficulty_key),
            tier_label=tier_label(tier_range),
            max_attempts=self.cfg.max_attempts,
        )
        return self._image_or_text(
            lambda: self._render_start(input),
            render_start_text(input),
        )

    def has_active_game(self, actor: Actor) -> bool:
        session = self.load(actor)
        return bool(session and session.status == "active")

    def guess(self, actor: Actor, query: str) -> Reply:
        now = self.now()
        session = self.load(actor)
        pending_key = self._pending_key(actor)
        if session is None:
            self.pending.pop(pending_key, None)
            raise CoopError("NO_SESSION", "本群还没有合作局。发送「/窝一把」开一局。")
        if session.status != "active":
            self.pending.pop(pending_key, None)
            raise CoopError("SESSION_ENDED", "本局已经结束了，发送「/窝一把」开新局。")
        if len(session.guesses) >= self.cfg.max_attempts:
            self.pending.pop(pending_key, None)
            raise CoopError("NO_ATTEMPTS", "本局次数已经用完了，发送「/窝一把」开新局。")

        self._prune_pending(now)
        pending = self.pending.get(pending_key)
        if pending is not None and (
            pending.session_id != session.session_id
            or now - pending.at > self.cfg.suggest_ttl_ms
        ):
            self.pending.pop(pending_key, None)
            pending = None

        text = query.strip()
        ship: Ship
        reason = "exact"

        if pending is not None and _is_cancel_query(text):
            self.pending.pop(pending_key, None)
            return TextReply("已取消本次候选确认。")

        choice = _numeric_choice(text) if pending is not None else None
        if pending is not None and choice is not None:
            if choice < 1 or choice > len(pending.candidates):
                return TextReply(f"只能选择 1–{len(pending.candidates)}，或回复 /取消。")
            candidate_index = pending.candidates[choice - 1]
            candidate = self.data.by_index.get(candidate_index)
            if candidate is None:
                self.pending.pop(pending_key, None)
                return TextReply("候选已失效，请重新输入船名。")
            ship = candidate
            reason = "pending"
        else:
            if pending is not None:
                self.pending.pop(pending_key, None)

            if _numeric_choice(text) is not None:
                raise CoopError("NO_PENDING", "没有待确认的候选。请直接发送 /船名。")
            if _is_cancel_query(text):
                return TextReply("当前没有待确认的候选。")

            resolved = resolve_ship(
                self.data.ships,
                text,
                mode=self.cfg.fuzzy_mode,
                max_candidates=self.cfg.suggest_max,
            )
            if resolved is None:
                raise CoopError("UNKNOWN_SHIP", "没找到这艘船，试试完整舰名或拼音。")
            if isinstance(resolved, ResolveCandidates):
                self._remember_suggestion(actor, session, list(resolved.candidates), now)
                return self._suggestion_reply(actor, text, list(resolved.candidates))
            assert isinstance(resolved, ResolveMatch)
            ship = resolved.ship
            reason = resolved.reason

        for index, previous in enumerate(session.guesses, start=1):
            if previous.ship_index == ship.index:
                raise CoopError(
                    "DUPLICATE_GUESS",
                    f"「{display_name(ship)}」在第 {index} 猜已经猜过了，剩余 {self.remaining(session)} 次不变。",
                )

        last = session.guesses[-1] if session.guesses else None
        if last is not None and now - last.at < self.cfg.global_cooldown_ms:
            wait = math.ceil((self.cfg.global_cooldown_ms - (now - last.at)) / 1000)
            raise CoopError(
                "GLOBAL_COOLDOWN",
                f"刚有人猜过，先看清上一张图，{wait} 秒后再猜。剩余 {self.remaining(session)} 次不变。",
            )
        last_user = next(
            (guess for guess in reversed(session.guesses) if guess.user_id == actor.user_id),
            None,
        )
        if last_user is not None and now - last_user.at < self.cfg.user_cooldown_ms:
            wait = math.ceil((self.cfg.user_cooldown_ms - (now - last_user.at)) / 1000)
            raise CoopError(
                "USER_COOLDOWN",
                f"你猜得太快了，{wait} 秒后再试。剩余 {self.remaining(session)} 次不变。",
            )

        pool = pool_for(self.data, session.difficulty)
        answer = self.data.by_index.get(session.answer_index)
        if answer is None:
            self.pending.pop(pending_key, None)
            session.status = "aborted"
            session.updated_at = now
            self.store.save_session(session)
            raise CoopError("DATA_MISMATCH", "答案数据已变化，本局已中止，请开新局。")

        feedback = compare_attributes(
            ship,
            answer,
            pool.attribute_keys,
            self.data.defs,
        )
        solved = is_correct_guess(ship.index, answer.index, pool)

        session.guesses.append(
            Guess(
                ship_index=ship.index,
                user_id=actor.user_id,
                nickname=actor.nickname,
                at=now,
            ),
        )
        if solved:
            session.status = "won"
        elif len(session.guesses) >= self.cfg.max_attempts:
            session.status = "lost"
        else:
            session.status = "active"
        session.updated_at = now
        self.store.save_session(session)
        self.pending.pop(pending_key, None)
        self._clear_session_pending(session.session_id)

        input = self._board_input(session, answer, pool.attribute_keys, feedback, ship)
        fallback = render_board_text(input)
        correction = (
            f"（已按「{display_name(ship)}」纠正「{_truncate_query(text)}」）"
            if reason == "typo"
            else ""
        )
        if solved:
            caption = (
                f"猜中了！第 {len(session.guesses)} 猜 · {display_name(ship)}{correction}；"
                f"答案：{display_name(answer)}"
            )
        elif session.status == "lost":
            caption = f"{self.cfg.max_attempts} 次机会用完了；答案：{display_name(answer)}"
        else:
            caption = (
                f"第 {len(session.guesses)} 猜 · {display_name(ship)}{correction} · "
                f"剩余 {self.remaining(session)} 次"
            )

        reply = self._image_or_text(
            lambda: self._render_board(input),
            fallback,
            caption,
        )
        return reply if session.status == "active" else self._with_restart_prompt(actor, session, reply)

    def status(self, actor: Actor) -> Reply:
        session = self.load(actor)
        if session is None:
            return TextReply("本群还没有合作局。发送「/窝一把」开一局。")
        pool = pool_for(self.data, session.difficulty)
        answer = self.data.by_index.get(session.answer_index)
        if answer is None:
            return TextReply("本局答案数据已失效，请发送「/窝一把」开新局。")
        input = self._board_input(session, answer, pool.attribute_keys)
        fallback = render_board_text(input)
        caption = (
            f"合作模式 · 剩余 {self.remaining(session)} 次"
            if session.status == "active"
            else f"合作模式 · 已结束 · 答案：{display_name(answer)}"
        )
        reply = self._image_or_text(
            lambda: self._render_board(input),
            fallback,
            caption,
        )
        return reply if session.status == "active" else self._with_restart_prompt(actor, session, reply)

    def end(self, actor: Actor) -> Reply:
        session = self.load(actor)
        if session is None:
            raise CoopError("NO_SESSION", "本群还没有合作局。")
        if session.status != "active":
            raise CoopError("SESSION_ENDED", "本局已经结束了，发送「/窝一把」开新局。")
        if not self._can_moderate(session, actor):
            raise CoopError("NOT_ALLOWED", "只有房主或群管理可以提前结束。")

        session.status = "aborted"
        session.updated_at = self.now()
        self.store.save_session(session)

        pool = pool_for(self.data, session.difficulty)
        answer = self.data.by_index.get(session.answer_index)
        if answer is None:
            return self._with_restart_prompt(actor, session, TextReply("本局已结束。"))
        input = self._board_input(session, answer, pool.attribute_keys)
        fallback = f"本局已由 {actor.nickname} 提前结束。\n{render_board_text(input)}"
        reply = self._image_or_text(
            lambda: self._render_board(input),
            fallback,
            f"本局已由 {actor.nickname} 提前结束；答案：{display_name(answer)}",
        )
        return self._with_restart_prompt(actor, session, reply)

    def _with_restart_prompt(self, actor: Actor, session: Session, reply: Reply) -> Reply:
        follow_up = self._restart_prompt(actor, session)
        return replace(reply, follow_up=follow_up)

    def _restart_prompt(self, actor: Actor, session: Session) -> Reply:
        tier_range = session.tier_range or TierRange(
            min=MIN_ANSWER_TIER,
            max=MAX_TIER,
        )
        difficulty = difficulty_label(self.data, session.difficulty)
        tier = tier_label(tier_range)
        text = f"本局结束。发送「@机器人 /再来一局」按 {difficulty} · {tier} 快速重开。"
        if is_official_platform(actor.platform):
            return MarkdownReply(
                content="\n".join(
                    [
                        "## 本局结束",
                        f"点击下方按钮，按 **{difficulty} · {tier}** 再来一局。",
                    ],
                ),
                keyboard=(CommandButton(label="再来一局", data="/再来一局"),),
                fallback_text=text,
            )
        return TextReply(text)

    def _pending_key(self, actor: Actor) -> str:
        return f"{actor.platform}:{actor.group_id}:{actor.user_id}"

    def _clear_session_pending(self, session_id: str) -> None:
        for key, pending in list(self.pending.items()):
            if pending.session_id == session_id:
                self.pending.pop(key, None)

    def _prune_pending(self, now: int) -> None:
        for key, pending in list(self.pending.items()):
            if now - pending.at > self.cfg.suggest_ttl_ms:
                self.pending.pop(key, None)
        if len(self.pending) <= MAX_PENDING:
            return
        oldest = sorted(self.pending.items(), key=lambda item: item[1].at)
        for key, _ in oldest[: len(self.pending) - MAX_PENDING]:
            self.pending.pop(key, None)

    def _remember_suggestion(
        self,
        actor: Actor,
        session: Session,
        candidates: list[Ship],
        now: int,
    ) -> None:
        self.pending[self._pending_key(actor)] = PendingSuggestion(
            session_id=session.session_id,
            candidates=[
                ship.index for ship in candidates[: self.cfg.suggest_max]
            ],
            at=now,
        )

    def _suggestion_text(self, query: str, candidates: list[Ship]) -> str:
        return "\n".join(
            [
                "未找到对应船名。",
                f"「{_truncate_query(query)}」可能是：",
                *[
                    f"{index + 1}. {display_name(ship)}"
                    f"（{ship_subtitle(ship, self.data.defs, False)}）"
                    for index, ship in enumerate(candidates)
                ],
            ],
        )

    def _suggestion_reply(
        self,
        actor: Actor,
        query: str,
        candidates: list[Ship],
    ) -> Reply:
        fallback = self._suggestion_text(query, candidates)
        if not is_official_platform(actor.platform):
            return TextReply(fallback)

        lines = [
            "### 未找到对应船名",
            f"「{_truncate_query(query)}」可能是：",
            "",
            *[
                f"{index + 1}. {display_name(ship)}"
                f"（{ship_subtitle(ship, self.data.defs, False)}）"
                for index, ship in enumerate(candidates)
            ],
        ]
        return MarkdownReply(
            content="\n".join(lines),
            keyboard=tuple(
                CommandButton(
                    label=f"{index + 1}. {_truncate_button_label(display_name(ship))}",
                    data=f"/{display_name(ship)}",
                    enter=False,
                )
                for index, ship in enumerate(candidates)
            ),
            fallback_text=fallback,
        )

    def _load(self, actor: Actor) -> Session | None:
        session = self.store.get_session(actor.platform, actor.group_id)
        if session is None:
            return None
        now = self.now()
        if session.status == "active" and session.data_version != self.data.data_version:
            session.status = "aborted"
            self.store.save_session(session)
        elif session.status == "active" and now - session.updated_at > self.cfg.ttl_ms:
            session.status = "aborted"
            self.store.save_session(session)
        return session

    load = _load

    def _board_input(
        self,
        session: Session,
        answer: Ship,
        attribute_keys: tuple[str, ...],
        extra_feedback: tuple[Feedback, ...] | None = None,
        extra_ship: Ship | None = None,
    ) -> BoardRenderInput:
        rows: list[BoardRow] = []
        for index, guess in enumerate(session.guesses):
            ship = self.data.by_index.get(guess.ship_index)
            if ship is None:
                raise ValueError(f"猜测的船 {guess.ship_index} 不在船表里")
            feedback = (
                extra_feedback
                if extra_ship is not None
                and extra_feedback is not None
                and index == len(session.guesses) - 1
                else compare_attributes(ship, answer, attribute_keys, self.data.defs)
            )
            rows.append(
                BoardRow(
                    attempt=index + 1,
                    nickname=guess.nickname,
                    ship=ship,
                    feedback=feedback,
                ),
            )

        return BoardRenderInput(
            session=session,
            rows=tuple(rows),
            answer=None if session.status == "active" else answer,
            remaining=self.remaining(session),
            difficulty_label=difficulty_label(self.data, session.difficulty),
            tier_label=tier_label(session.tier_range),
            attribute_keys=attribute_keys,
            defs=self.data.defs,
        )

    def remaining(self, session: Session) -> int:
        return max(0, self.cfg.max_attempts - len(session.guesses))

    def _can_moderate(self, session: Session, actor: Actor) -> bool:
        return (
            actor.user_id == session.host_id
            or actor.role == "owner"
            or actor.role == "admin"
        )

    def _render_start(self, input: StartRenderInput) -> bytes:
        if self.renderer is None:
            raise RuntimeError("no renderer configured")
        return self.renderer.start(input)

    def _render_board(self, input: BoardRenderInput) -> bytes:
        if self.renderer is None:
            raise RuntimeError("no renderer configured")
        return self.renderer.board(input)

    def _render_guide(self, input: HelpRenderInput) -> bytes:
        if self.renderer is None:
            raise RuntimeError("no renderer configured")
        return self.renderer.guide(input)

    def _image_or_text(
        self,
        render: Callable[[], bytes],
        fallback_text: str,
        caption: str | None = None,
    ) -> Reply:
        try:
            return ImageReply(
                png=render(),
                caption=caption,
                fallback_text=fallback_text,
            )
        except Exception as exc:  # noqa: BLE001 - rendering must never kill a game
            logger.warning("[wowsguess] 图片渲染失败，回退文本：%s", exc)
            return TextReply(fallback_text)


class StartOptionsLike(Protocol):
    difficulty_key: str
    tier_range: TierRange | None


@dataclass(frozen=True)
class _SimpleStartOptions:
    difficulty_key: str
    tier_range: TierRange | None
