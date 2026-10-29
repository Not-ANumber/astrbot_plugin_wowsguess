"""Tests for main.py using lightweight AstrBot API stubs.

These stubs are deliberately minimal: they verify our own mapping and filter
logic without installing the whole AstrBot runtime. The real API shapes are
taken from AstrBot's astr_message_event.py / components.py.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.fixture_data import make_message, write_data_dir

# ---------------------------------------------------------------------------
# Stub astrbot.api.* before importing main.py
# ---------------------------------------------------------------------------

astrbot = types.ModuleType("astrbot")
astrbot.__path__ = []  # mark as package
sys.modules.setdefault("astrbot", astrbot)

api = types.ModuleType("astrbot.api")


class AstrBotConfig(dict):
    pass


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


api.AstrBotConfig = AstrBotConfig
api.logger = _Logger()
sys.modules["astrbot.api"] = api
setattr(astrbot, "api", api)

components = types.ModuleType("astrbot.api.message_components")


class Plain:
    def __init__(self, text: str = "") -> None:
        self.text = text


class At:
    def __init__(self, qq: str = "") -> None:
        self.qq = qq


class Reply:
    def __init__(self, id: str = "", sender_id: str = "") -> None:
        self.id = id
        self.sender_id = sender_id


components.Plain = Plain
components.At = At
components.Reply = Reply
sys.modules["astrbot.api.message_components"] = components
setattr(api, "message_components", components)

event_filter = types.ModuleType("astrbot.api.event.filter")


class CustomFilter:
    def __init__(self, raise_error: bool = True, **kwargs) -> None:
        self.raise_error = raise_error

    def filter(self, event, cfg) -> bool:
        raise NotImplementedError


class EventMessageType:
    GROUP_MESSAGE = "group"
    PRIVATE_MESSAGE = "private"


def _identity_decorator(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


event_filter.CustomFilter = CustomFilter
event_filter.EventMessageType = EventMessageType
event_filter.custom_filter = _identity_decorator
event_filter.event_message_type = _identity_decorator
sys.modules["astrbot.api.event.filter"] = event_filter


class AstrMessageEvent:
    pass


event_mod = types.ModuleType("astrbot.api.event")
event_mod.AstrMessageEvent = AstrMessageEvent
event_mod.filter = event_filter
sys.modules["astrbot.api.event"] = event_mod
setattr(api, "event", event_mod)

star_mod = types.ModuleType("astrbot.api.star")


class Context:
    pass


class Star:
    def __init__(self, context: Context, config=None) -> None:
        self.context = context


def register(*args, **kwargs):
    def decorator(cls):
        return cls

    return decorator


star_mod.Context = Context
star_mod.Star = Star
star_mod.register = register
sys.modules["astrbot.api.star"] = star_mod
setattr(api, "star", star_mod)

import main  # noqa: E402  (import after stubbing)


# ---------------------------------------------------------------------------
# Fakes for event objects
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self) -> None:
        self.text = ""
        self.image = ""
        self.markdown = False

    def message(self, text: str) -> "FakeResult":
        self.text += text
        return self

    def base64_image(self, value: str) -> "FakeResult":
        self.image = value
        return self

    def use_markdown(self, use: bool = True) -> "FakeResult":
        self.markdown = use
        return self


class FakeEvent(AstrMessageEvent):
    def __init__(
        self,
        *,
        messages=None,
        group_id: str = "group-1",
        self_id: str = "bot-1",
        sender_id: str = "user-1",
        platform_name: str = "aiocqhttp",
        wake: bool = False,
        role: str = "member",
        raw_message=None,
        message_id: str = "msg-1",
    ) -> None:
        self._messages = messages or []
        self._group_id = group_id
        self._self_id = self_id
        self._sender_id = sender_id
        self._platform_name = platform_name
        self._wake = wake
        self.role = role
        self.message_obj = SimpleNamespace(
            message_id=message_id,
            timestamp=1760000000,
            raw_message=raw_message,
        )
        self.message_str = ""
        self.stopped = False

    def get_messages(self):
        return self._messages

    def get_group_id(self) -> str:
        return self._group_id

    def get_self_id(self) -> str:
        return self._self_id

    def get_sender_id(self) -> str:
        return self._sender_id

    def get_sender_name(self) -> str:
        return "tester"

    def get_platform_name(self) -> str:
        return self._platform_name

    def is_wake_up(self) -> bool:
        return self._wake

    def stop_event(self) -> None:
        self.stopped = True

    def plain_result(self, text: str):
        return ("text", text)

    def make_result(self):
        return FakeResult()


class FilterTests(unittest.TestCase):
    def test_at_bot_plus_command_matches(self) -> None:
        event = FakeEvent(messages=[At("bot-1"), Plain("/秋月")])
        self.assertTrue(main.DirectedGameFilter().filter(event, AstrBotConfig()))

    def test_hash_command_requires_at(self) -> None:
        event = FakeEvent(messages=[Plain("#秋月")])
        self.assertFalse(main.DirectedGameFilter().filter(event, AstrBotConfig()))

        directed = FakeEvent(messages=[At("bot-1"), Plain("#秋月")])
        self.assertTrue(main.DirectedGameFilter().filter(directed, AstrBotConfig()))

    def test_slash_command_without_at_matches(self) -> None:
        event = FakeEvent(messages=[Plain("/状态")])
        self.assertTrue(main.DirectedGameFilter().filter(event, AstrBotConfig()))

    def test_slash_command_with_other_at_does_not_match(self) -> None:
        event = FakeEvent(messages=[At("someone-else"), Plain("/状态")])
        self.assertFalse(main.DirectedGameFilter().filter(event, AstrBotConfig()))

    def test_plain_chat_does_not_match(self) -> None:
        event = FakeEvent(messages=[At("bot-1"), Plain("你好")])
        self.assertFalse(main.DirectedGameFilter().filter(event, AstrBotConfig()))

    def test_empty_at_bot_opens_menu(self) -> None:
        event = FakeEvent(messages=[At("bot-1")])
        self.assertTrue(main.DirectedGameFilter().filter(event, AstrBotConfig()))

    def test_private_chat_is_ignored(self) -> None:
        event = FakeEvent(messages=[At("bot-1"), Plain("/秋月")], group_id="")
        self.assertFalse(main.DirectedGameFilter().filter(event, AstrBotConfig()))

    def test_official_platform_without_at_component_uses_wake(self) -> None:
        event = FakeEvent(
            messages=[Plain("/秋月")],
            platform_name="qq_official",
            wake=True,
        )
        self.assertTrue(main.DirectedGameFilter().filter(event, AstrBotConfig()))


class MappingTests(unittest.TestCase):
    def test_plain_text_only_joins_plain_components(self) -> None:
        event = FakeEvent(
            messages=[At("bot-1"), Plain("/秋"), Plain("月"), Reply("r", "x")],
        )
        self.assertEqual(main._plain_text(event), "/秋月")

    def test_raw_role_from_onebot_sender(self) -> None:
        event = FakeEvent(raw_message={"sender": {"role": "admin"}})
        self.assertEqual(main._role_from_raw(event), "admin")

    def test_raw_role_from_official_member_role(self) -> None:
        event = FakeEvent(raw_message={"author": {"member_role": "owner"}})
        self.assertEqual(main._role_from_raw(event), "owner")

    def test_build_payload_uses_stable_platform_key(self) -> None:
        event = FakeEvent(messages=[At("bot-1"), Plain("/秋月")])
        plugin = main.WowsguessPlugin(
            Context(),
            AstrBotConfig(
                mode="remote",
                service_url="http://127.0.0.1:8787",
                auth_token="token",
                request_timeout=5,
                reserved_commands="",
                notify_errors=False,
            ),
        )
        payload = plugin._build_payload(event, "/秋月", "member")

        self.assertEqual(payload["event"]["platform"], "aiocqhttp:bot-1")
        self.assertEqual(payload["event"]["account_id"], "bot-1")
        self.assertEqual(payload["event"]["channel"], {"type": "group", "id": "group-1"})
        self.assertEqual(payload["event"]["sender"]["id"], "user-1")
        self.assertEqual(payload["event"]["message"]["text"], "/秋月")
        self.assertTrue(payload["event"]["message"]["directed"])

    def test_image_reply_uses_caption_and_base64(self) -> None:
        event = FakeEvent(messages=[At("bot-1"), Plain("/秋月")])
        plugin = main.WowsguessPlugin(
            Context(),
            AstrBotConfig(mode="remote", service_url="http://127.0.0.1:1", auth_token=""),
        )
        result = plugin._build_result(
            event,
            {
                "type": "image",
                "image": {"mime": "image/png", "base64": "aGVsbG8="},
                "caption": "剩余 5 次",
                "fallback_text": "文本棋盘",
            },
        )
        self.assertEqual(result.text, "剩余 5 次\n")
        self.assertEqual(result.image, "aGVsbG8=")

    def test_invalid_image_falls_back_to_text(self) -> None:
        event = FakeEvent(messages=[At("bot-1"), Plain("/秋月")])
        plugin = main.WowsguessPlugin(
            Context(),
            AstrBotConfig(mode="remote", service_url="http://127.0.0.1:1", auth_token=""),
        )
        result = plugin._build_result(
            event,
            {
                "type": "image",
                "image": {"mime": "image/png", "base64": "not base64!!!"},
                "fallback_text": "文本棋盘",
            },
        )
        self.assertEqual(result, ("text", "文本棋盘"))

    def test_none_reply_returns_no_result(self) -> None:
        event = FakeEvent(messages=[At("bot-1"), Plain("/秋月")])
        plugin = main.WowsguessPlugin(
            Context(),
            AstrBotConfig(mode="remote", service_url="http://127.0.0.1:1", auth_token=""),
        )
        self.assertIsNone(plugin._build_result(event, {"type": "none"}))


async def collect(generator):
    results = []
    async for item in generator:
        results.append(item)
    return results


class LocalModeTests(unittest.TestCase):
    def test_local_mode_initializes_and_starts_game(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_data_dir(root / "data")
            plugin = main.WowsguessPlugin(
                Context(),
                AstrBotConfig(
                    mode="local",
                    data_dir=str(root / "data"),
                    db_path=str(root / "bot.sqlite"),
                    reserved_commands="",
                    notify_errors=False,
                ),
            )
            try:
                self.assertIsNotNone(plugin.local_app)

                reply = plugin.local_app.handle(make_message("/窝一把"))
                self.assertEqual(reply.kind, "image")
                self.assertTrue(reply.png.startswith(bytes([0x89]) + b"PNG"))

                start_event = FakeEvent(
                    messages=[At("bot-1"), Plain("/窝一把")],
                    message_id="m-local-start",
                )
                start_results = asyncio.run(
                    plugin._handle_local(start_event, "/窝一把", "group-1"),
                )
                self.assertIsInstance(start_results, list)
                self.assertIsInstance(start_results[0], FakeResult)
                self.assertTrue(start_results[0].image)

                status_event = FakeEvent(
                    messages=[At("bot-1"), Plain("/状态")],
                    message_id="m-local-status",
                )
                status_results = asyncio.run(
                    plugin._handle_local(status_event, "/状态", "group-1"),
                )
                self.assertIsInstance(status_results, list)
                self.assertIsInstance(status_results[0], FakeResult)
                self.assertTrue(status_results[0].image)
            finally:
                plugin.local_app.close()

    def test_missing_local_data_returns_actionable_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = main.WowsguessPlugin(
                Context(),
                AstrBotConfig(
                    mode="local",
                    data_dir=str(Path(tmp) / "missing"),
                    db_path=str(Path(tmp) / "bot.sqlite"),
                ),
            )
            self.assertIsNone(plugin.local_app)
            self.assertIn("本地模式不可用", plugin.local_error)

    def test_pack_selection_uses_server_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_data_dir(root / "packs" / "wg")
            plugin = main.WowsguessPlugin(
                Context(),
                AstrBotConfig(
                    mode="local",
                    server="wg",
                    packs_dir=str(root / "packs"),
                    db_path=str(root / "bot-wg.sqlite"),
                    reserved_commands="",
                ),
            )
            try:
                self.assertEqual(plugin.server, "wg")
                self.assertIsNotNone(plugin.local_app)
            finally:
                plugin.local_app.close()

    def test_missing_lesta_pack_reports_its_own_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_data_dir(root / "packs" / "wg")
            plugin = main.WowsguessPlugin(
                Context(),
                AstrBotConfig(
                    mode="local",
                    server="lesta",
                    packs_dir=str(root / "packs"),
                    db_path=str(root / "bot-lesta.sqlite"),
                ),
            )
            self.assertEqual(plugin.server, "lesta")
            self.assertIsNone(plugin.local_app)
            self.assertIn("Lesta", plugin.local_error)
            self.assertIn("ships.json", plugin.local_error)

    def test_legacy_database_is_copied_with_sqlite_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "bot.sqlite"
            target = root / "bot-wg.sqlite"

            import sqlite3

            src = sqlite3.connect(legacy)
            src.execute("CREATE TABLE sample (value TEXT)")
            src.execute("INSERT INTO sample VALUES ('kept')")
            src.commit()
            src.close()

            self.assertTrue(main.WowsguessPlugin._copy_legacy_db(legacy, target))
            dst = sqlite3.connect(target)
            try:
                row = dst.execute("SELECT value FROM sample").fetchone()
            finally:
                dst.close()
            self.assertEqual(row, ("kept",))

    def test_manual_lesta_pack_can_be_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_data_dir(root / "lesta-pack")
            plugin = main.WowsguessPlugin(
                Context(),
                AstrBotConfig(
                    mode="local",
                    server="lesta",
                    data_dir=str(root / "lesta-pack"),
                    db_path=str(root / "bot-lesta.sqlite"),
                    reserved_commands="",
                ),
            )
            try:
                self.assertEqual(plugin.server, "lesta")
                self.assertIsNotNone(plugin.local_app)
            finally:
                plugin.local_app.close()

    def test_official_markdown_and_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_data_dir(root / "data")
            plugin = main.WowsguessPlugin(
                Context(),
                AstrBotConfig(
                    mode="local",
                    data_dir=str(root / "data"),
                    db_path=str(root / "bot.sqlite"),
                    reserved_commands="",
                ),
            )
            try:
                start_event = FakeEvent(
                    messages=[At("bot-1"), Plain("/窝一把")],
                    message_id="official-start",
                    platform_name="qq_official",
                )
                start_results = asyncio.run(
                    plugin._handle_local(start_event, "/窝一把", "group-1"),
                )
                self.assertIsInstance(start_results[0], FakeResult)

                end_event = FakeEvent(
                    messages=[At("bot-1"), Plain("/结束")],
                    message_id="official-end",
                    platform_name="qq_official",
                )
                end_results = asyncio.run(
                    plugin._handle_local(end_event, "/结束", "group-1"),
                )
                self.assertGreaterEqual(len(end_results), 2)
                self.assertTrue(end_results[1].markdown)
            finally:
                plugin.local_app.close()

    def test_group_allowlist_blocks_other_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_data_dir(root / "data")
            plugin = main.WowsguessPlugin(
                Context(),
                AstrBotConfig(
                    mode="local",
                    data_dir=str(root / "data"),
                    db_path=str(root / "bot.sqlite"),
                    reserved_commands="",
                    allowed_groups="other-group",
                ),
            )
            try:
                event = FakeEvent(
                    messages=[At("bot-1"), Plain("/窝一把")],
                    message_id="m-blocked",
                    group_id="group-1",
                )
                results = asyncio.run(collect(plugin.on_group_message(event)))
                self.assertEqual(results, [])
            finally:
                plugin.local_app.close()


if __name__ == "__main__":
    unittest.main()
