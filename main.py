"""AstrBot adapter for the wowsguess co-op guessing game.

Default ``local`` mode runs the Python game core, SQLite store and Pillow
renderer inside the AstrBot process. Optional ``remote`` mode maps events to
the standalone wowsguess-coop HTTP service instead.
"""

from __future__ import annotations

import asyncio
import base64
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain, Reply
from astrbot.api.star import Context, Star, register

try:
    from .wowsguess.models import (
        CoopConfig,
        ImageReply,
        IncomingMessage as GameIncomingMessage,
        MarkdownReply,
        TextReply,
    )
except ImportError:  # loaded as a top-level module by some AstrBot versions
    from wowsguess.models import (
        CoopConfig,
        ImageReply,
        IncomingMessage as GameIncomingMessage,
        MarkdownReply,
        TextReply,
    )

try:
    from .wowsguess.remote import (
        DEFAULT_RESERVED_COMMANDS,
        PLUGIN_VERSION,
        SUPPORTED_PREFIXES,
        CoopClient,
        ServiceError,
        build_event_payload,
        clean_base64_image,
        normalize_game_text,
    )
except ImportError:  # loaded as a top-level module by some AstrBot versions
    from wowsguess.remote import (
        DEFAULT_RESERVED_COMMANDS,
        PLUGIN_VERSION,
        SUPPORTED_PREFIXES,
        CoopClient,
        ServiceError,
        build_event_payload,
        clean_base64_image,
        normalize_game_text,
    )


try:
    from .wowsguess.packs import (
        PackError,
        describe_pack,
        normalize_server,
        resolve_pack_dir,
    )
except ImportError:  # loaded as a top-level module by some AstrBot versions
    from wowsguess.packs import (
        PackError,
        describe_pack,
        normalize_server,
        resolve_pack_dir,
    )


def _plain_text(event: AstrMessageEvent) -> str:
    """Concatenate text components.

    ``event.message_str`` has the wake prefix stripped by AstrBot, so it cannot
    tell ``/秋月`` from ``秋月``. The component chain still contains the
    original text.
    """
    return "".join(
        component.text
        for component in event.get_messages()
        if isinstance(component, Plain)
    ).strip()


def _is_directed(event: AstrMessageEvent) -> bool:
    """Whether this message explicitly targets the bot."""
    self_id = str(event.get_self_id() or "")
    for component in event.get_messages():
        if isinstance(component, At):
            qq = str(getattr(component, "qq", "") or "")
            if self_id and qq == self_id:
                return True
        elif isinstance(component, Reply):
            sender_id = str(getattr(component, "sender_id", "") or "")
            if self_id and sender_id == self_id:
                return True

    platform_name = str(event.get_platform_name() or "").lower()
    if platform_name.startswith("qq_official"):
        # Official group events are only delivered when the bot is @'d unless
        # the group owner enables full-message mode. is_wake_up covers the
        # normal case; full-message mode still needs a prefix below.
        return bool(event.is_wake_up())
    return False


def _role_from_event(event: AstrMessageEvent) -> str:
    role = str(getattr(event, "role", "") or "").lower()
    return role if role in {"owner", "admin", "member"} else "member"


def _role_from_raw(event: AstrMessageEvent) -> str:
    """Best-effort group role extraction from the platform's raw event.

    AstrBot's OneBot adapter does not copy ``sender.role`` onto the event, and
    official QQ puts ``member_role`` in the raw payload. Reading the raw event
    keeps group-admin moderation working without a fast path in the framework.
    """
    raw = getattr(event.message_obj, "raw_message", None)
    candidates: list[Any] = []

    if isinstance(raw, dict):
        candidates.append(raw.get("member_role"))
        author = raw.get("author")
        if isinstance(author, dict):
            candidates.append(author.get("member_role"))
        sender = raw.get("sender")
        if isinstance(sender, dict):
            candidates.append(sender.get("role"))
    elif raw is not None:
        candidates.append(getattr(raw, "member_role", None))
        author = getattr(raw, "author", None)
        if author is not None:
            candidates.append(getattr(author, "member_role", None))
        sender = getattr(raw, "sender", None)
        if sender is not None:
            if isinstance(sender, dict):
                candidates.append(sender.get("role"))
            else:
                candidates.append(getattr(sender, "role", None))

    for value in candidates:
        role = str(value or "").lower()
        if role in {"owner", "admin", "member"}:
            return role
    return ""


def _reserved_commands(value: Any) -> set[str]:
    if isinstance(value, str):
        items = [item.strip().lower() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip().lower() for item in value]
    else:
        items = []
    return set(DEFAULT_RESERVED_COMMANDS) | {item for item in items if item}


class DirectedGameFilter(filter.CustomFilter):
    """Only activate on group messages that look like game commands."""

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        if not event.get_group_id():
            return False

        text = _plain_text(event)
        if not text:
            return _is_directed(event)

        if not text.startswith(SUPPORTED_PREFIXES):
            return False

        if _is_directed(event):
            return True

        # AstrBot treats "/" and "／" as its default wake prefix. Accept those
        # as an explicit game command so a forgotten @ does not fall through to
        # the LLM. Other prefixes ("#", "!") still require an @.
        at_components = [
            component
            for component in event.get_messages()
            if isinstance(component, At)
        ]
        if at_components:
            return False
        return text[0] in ("/", "／")


@register(
    "astrbot_plugin_wowsguess",
    "wowsguess",
    "窝一把：QQ 群舰船合作猜谜（默认本地零部署，可切远程服务）",
    PLUGIN_VERSION,
)
class WowsguessPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.mode = str(config.get("mode", "local") or "local").strip().lower()
        if self.mode not in {"local", "remote"}:
            logger.warning("[wowsguess] 未知 mode=%r，按 local 处理", self.mode)
            self.mode = "local"
        try:
            self.server = normalize_server(config.get("server", "wg"))
        except PackError as exc:
            logger.warning("[wowsguess] %s；按 wg 处理", exc)
            self.server = "wg"
        self.reserved = _reserved_commands(config.get("reserved_commands", ""))
        self.notify_errors = bool(config.get("notify_errors", False))
        raw_groups = str(config.get("allowed_groups", "") or "")
        self.allowed_groups = {
            item.strip() for item in raw_groups.split(",") if item.strip()
        }
        self._error_sent_at: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.local_app = None
        self.local_error = ""
        self.client: CoopClient | None = None

        if self.mode == "local":
            self._init_local(config)
        else:
            self.client = CoopClient(
                base_url=str(config.get("service_url", "http://127.0.0.1:8787")),
                token=str(config.get("auth_token", "")),
                timeout=float(config.get("request_timeout", 15)),
            )
            logger.info(f"[wowsguess] remote 模式：{self.client.base_url}")

    def _init_local(self, config: AstrBotConfig) -> None:
        data_dir: Path | None = None
        store = None
        try:
            try:
                from .wowsguess.app import GameApp
                from .wowsguess.data import load_data
                from .wowsguess.render.board import BoardRenderer
                from .wowsguess.store import BotStore
            except ImportError:  # top-level module loading
                from wowsguess.app import GameApp
                from wowsguess.data import load_data
                from wowsguess.render.board import BoardRenderer
                from wowsguess.store import BotStore

            data_dir = self._resolve_data_dir(config)
            pack_label = describe_pack(data_dir, self.server)
            data = load_data(data_dir)
            db_path = self._resolve_db_path(config)
            store = BotStore(db_path)
            aborted = store.abort_sessions_with_other_version(data.data_version)
            store.prune_seen(int(time.time() * 1000) - 24 * 60 * 60 * 1000)
            font_path = str(config.get("font_path", "") or "").strip()
            self.local_app = GameApp(
                data,
                store,
                CoopConfig(),
                BoardRenderer(font_path=font_path or None),
            )
            logger.info(
                "[wowsguess] local 模式：%s · %s 艘船，数据版本 %s，数据库 %s",
                pack_label,
                len(data.ships),
                data.data_version,
                db_path,
            )
            if aborted:
                logger.info("[wowsguess] %s 个进行中会话因数据版本变化已中止", aborted)
        except Exception as exc:  # noqa: BLE001 - surface a clear chat message
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
            logger.error("[wowsguess] local 初始化失败：%s", exc)
            where = f"数据目录 {data_dir}" if data_dir else "数据目录"
            self.local_error = (
                f"本地模式不可用：{where} 没有准备好（{exc}）。"
                f"请在 packs/{self.server}/ 放入数据，"
                "或把插件配置改成 mode=remote 并填写服务地址。"
            )

    @staticmethod
    def _plugin_data_dir() -> Path:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

            return Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_wowsguess"
        except Exception:  # noqa: BLE001 - tests and older AstrBot versions
            return Path(__file__).resolve().parent / "bot-data"

    def _packs_root(self, config: AstrBotConfig) -> Path:
        raw = str(config.get("packs_dir", "") or "").strip()
        if raw:
            root = Path(raw).expanduser()
            return root if root.is_absolute() else Path(__file__).resolve().parent / root

        # 优先 AstrBot 的 plugin_data：插件更新替换代码目录时不会丢数据。
        # 本地开发没有 AstrBot 时回退到插件目录下的 packs/。
        root = self._plugin_data_dir() / "packs"
        if (root / self.server / "ships.json").is_file():
            return root
        legacy = Path(__file__).resolve().parent / "packs"
        if (legacy / self.server / "ships.json").is_file():
            return legacy
        return root

    def _resolve_data_dir(self, config: AstrBotConfig) -> Path:
        raw = str(config.get("data_dir", "") or "").strip()
        if raw:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = Path(__file__).resolve().parent / path
            return resolve_pack_dir(self._packs_root(config), self.server, path)
        return resolve_pack_dir(self._packs_root(config), self.server)

    def _resolve_db_path(self, config: AstrBotConfig) -> Path:
        raw = str(config.get("db_path", "") or "").strip()
        if raw:
            path = Path(raw).expanduser()
            return path if path.is_absolute() else Path(__file__).resolve().parent / path
        base = self._plugin_data_dir()

        target = base / f"bot-{self.server}.sqlite"
        # 0.3.x 只有一个 bot.sqlite；升级后先复制成 server 专属库，保留统计和进行中的局。
        # 用 SQLite backup API 而不是文件复制：WAL 里可能还有未 checkpoint 的事务。
        if self.server == "wg" and not target.exists():
            legacy = base / "bot.sqlite"
            if legacy.exists():
                if self._copy_legacy_db(legacy, target):
                    logger.info("[wowsguess] 已把旧数据库复制到 %s", target)
                else:
                    logger.warning("[wowsguess] 旧数据库迁移失败，继续使用 %s", legacy)
                    return legacy
        return target

    @staticmethod
    def _copy_legacy_db(source: Path, target: Path) -> bool:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
            dst = sqlite3.connect(target)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            return True
        except (sqlite3.Error, OSError) as exc:
            logger.warning("[wowsguess] 复制旧数据库失败：%s", exc)
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.custom_filter(DirectedGameFilter)
    async def on_group_message(self, event: AstrMessageEvent):
        text = _plain_text(event)
        normalized = normalize_game_text(text, self.reserved)
        if normalized is None:
            return

        group_id = str(event.get_group_id() or "")
        if not group_id:
            return
        if self.allowed_groups and group_id not in self.allowed_groups:
            event.stop_event()
            return

        if self.mode == "local":
            results = await self._handle_local(event, normalized, group_id)
            for result in results:
                yield result
            # A game-prefixed message must not fall through to the LLM, even
            # when it was a duplicate or a race with the end of a game.
            event.stop_event()
            return

        if self.client is None:
            return

        try:
            role = await self._role_for(event, normalized)
            payload = self._build_payload(event, normalized, role)
            reply = await self.client.dispatch(payload)
            result = self._build_result(event, reply)
        except ServiceError as exc:
            logger.warning(f"[wowsguess] 调用游戏服务失败：{exc}")
            error_result = self._error_result(event)
            if error_result is not None:
                yield error_result
            event.stop_event()
            return

        if result is None:
            # The service explicitly ignored the message. Stop here so the
            # LLM does not answer a game-prefixed command.
            event.stop_event()
            return

        yield result
        event.stop_event()

    async def _handle_local(self, event: AstrMessageEvent, text: str, group_id: str):
        if self.local_app is None:
            return [event.plain_result(self.local_error or "本地游戏数据未就绪。")]

        role = await self._role_for(event, text)
        self_id = str(event.get_self_id() or "")
        platform_name = str(event.get_platform_name() or "unknown")
        message = GameIncomingMessage(
            platform=f"{platform_name}:{self_id or 'unknown'}",
            group_id=group_id,
            user_id=str(event.get_sender_id() or ""),
            nickname=str(event.get_sender_name() or f"QQ{event.get_sender_id() or ''}"),
            role=role,
            message_id=str(
                getattr(event.message_obj, "message_id", "") or uuid.uuid4().hex,
            ),
            text=text,
            directed=True,
        )

        lock = self._locks.setdefault(group_id, asyncio.Lock())
        try:
            async with lock:
                reply = await asyncio.to_thread(self.local_app.handle, message)
        except Exception as exc:  # noqa: BLE001 - never take down the host bot
            logger.error("[wowsguess] 本地处理失败：%s", exc)
            return [event.plain_result("窝一把出错了，请稍后再试。")]

        if reply is None:
            return []
        return self._results_for_reply(event, reply)

    def _results_for_reply(self, event: AstrMessageEvent, reply) -> list[Any]:
        results: list[Any] = []
        if isinstance(reply, TextReply):
            results.append(event.plain_result(reply.text))
        elif isinstance(reply, ImageReply):
            result = event.make_result()
            if reply.caption:
                result.message(reply.caption + "\n")
            result.base64_image(base64.b64encode(reply.png).decode("ascii"))
            results.append(result)
        elif isinstance(reply, MarkdownReply):
            if self._is_official_event(event):
                result = event.make_result()
                content = reply.content
                if reply.keyboard:
                    # AstrBot's public message chain has no keyboard component;
                    # rewrite button-only wording and expose the commands.
                    content = content.replace(
                        "点击下方按钮，按",
                        "发送 `/再来一局`，按",
                    )
                    content = content.replace(
                        "> 下方按钮可查看棋盘和战绩。",
                        "> 发送 `/状态` 查看棋盘，`/统计` 查看战绩。",
                    )
                    content = content.replace(
                        "> 下方按钮可直接开局，或查看本群战绩。",
                        "> 发送 `/窝一把` 直接开局，或 `/统计` 查看本群战绩。",
                    )
                    commands = " ".join(button.data for button in reply.keyboard)
                    content += f"\n\n也可以直接发送：{commands}"
                result.message(content)
                result.use_markdown(True)
                results.append(result)
            else:
                results.append(event.plain_result(reply.fallback_text))
        else:
            results.append(event.plain_result("窝一把返回了未知结果。"))

        if reply.follow_up is not None:
            results.extend(self._results_for_reply(event, reply.follow_up))
        return results

    @staticmethod
    def _is_official_event(event: AstrMessageEvent) -> bool:
        platform = str(event.get_platform_name() or "").lower()
        return platform.startswith("qq_official")

    async def _role_for(self, event: AstrMessageEvent, normalized: str) -> str:
        event_role = _role_from_event(event)
        if event_role in {"owner", "admin"}:
            return event_role

        raw_role = _role_from_raw(event)
        if raw_role:
            return raw_role

        # Only resolve group metadata for moderation commands: event.get_group()
        # is a platform API call and should not run for every guess.
        head = normalized.lstrip("/").split(maxsplit=1)[0].lower()
        if head in {"结束", "end"}:
            resolved = await self._resolve_group_role(event)
            if resolved:
                return resolved
        return "member"

    async def _resolve_group_role(self, event: AstrMessageEvent) -> str:
        try:
            group = await event.get_group()
        except Exception as exc:  # noqa: BLE001 - platform metadata is optional
            logger.debug(f"[wowsguess] 读取群信息失败：{exc}")
            return ""

        if group is None:
            return ""
        sender_id = str(event.get_sender_id() or "")
        if str(getattr(group, "group_owner", "") or "") == sender_id:
            return "owner"
        admins = getattr(group, "group_admins", None) or []
        if sender_id in {str(item) for item in admins}:
            return "admin"
        return ""

    def _build_payload(
        self,
        event: AstrMessageEvent,
        text: str,
        role: str,
    ) -> dict[str, Any]:
        self_id = str(event.get_self_id() or "")
        sender_id = str(event.get_sender_id() or "")
        group_id = str(event.get_group_id() or "")

        mentions = [
            str(component.qq)
            for component in event.get_messages()
            if isinstance(component, At)
            and str(getattr(component, "qq", "") or "") not in {self_id, "all", ""}
        ]
        reply_to = ""
        for component in event.get_messages():
            if isinstance(component, Reply):
                reply_to = str(getattr(component, "id", "") or "")
                break

        platform_name = str(event.get_platform_name() or "unknown")
        timestamp = getattr(event.message_obj, "timestamp", None)
        received_at = None
        if isinstance(timestamp, (int, float)) and 0 < float(timestamp) < 10**12:
            received_at = int(float(timestamp) * 1000)

        return build_event_payload(
            # self_id is stable across restarts; platform_id may be an
            # instance UUID. Using it keeps sessions isolated per bot account.
            platform=f"{platform_name}:{self_id or 'unknown'}",
            account_id=self_id,
            group_id=group_id,
            sender_id=sender_id,
            sender_name=str(event.get_sender_name() or f"QQ{sender_id}"),
            role=role,
            message_id=str(
                getattr(event.message_obj, "message_id", "") or uuid.uuid4().hex,
            ),
            text=text,
            mentions=mentions,
            reply_to=reply_to or None,
            received_at=received_at,
        )

    def _build_result(self, event: AstrMessageEvent, reply: dict[str, Any]):
        reply_type = reply.get("type")

        if reply_type == "none":
            return None

        if reply_type == "text":
            return event.plain_result(str(reply.get("text") or ""))

        try:
            image = reply.get("image") or {}
            base64_data = clean_base64_image(str(image.get("base64") or ""))
            result = event.make_result()
            caption = reply.get("caption")
            if isinstance(caption, str) and caption.strip():
                result.message(caption.strip() + "\n")
            result.base64_image(base64_data)
            return result
        except Exception as exc:  # noqa: BLE001 - image transport fallback
            fallback = reply.get("fallback_text")
            if isinstance(fallback, str) and fallback.strip():
                return event.plain_result(fallback.strip())
            raise ServiceError(f"图片回复处理失败：{exc}") from exc

    def _error_result(self, event: AstrMessageEvent):
        if not self.notify_errors:
            return None
        group_id = str(event.get_group_id() or "")
        now = time.monotonic()
        if now - self._error_sent_at.get(group_id, 0.0) < 60:
            return None
        self._error_sent_at[group_id] = now
        return event.plain_result("窝一把：游戏服务暂时不可用，请稍后再试。")

    async def terminate(self):
        """Close the local SQLite connection when the plugin is unloaded."""
        app = self.local_app
        self.local_app = None
        if app is not None:
            try:
                app.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[wowsguess] 关闭本地数据库失败：%s", exc)
        self._locks.clear()
        return None
