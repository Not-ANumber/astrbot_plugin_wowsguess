from __future__ import annotations

import base64
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from wowsguess.remote import (
    DEFAULT_RESERVED_COMMANDS,
    CoopClient,
    ServiceError,
    build_event_payload,
    clean_base64_image,
    normalize_game_text,
    validate_reply,
)


class CommandNormalizationTests(unittest.TestCase):
    def test_slash_commands_are_passed_through(self) -> None:
        self.assertEqual(
            normalize_game_text("/窝一把 n 5-8", DEFAULT_RESERVED_COMMANDS),
            "/窝一把 n 5-8",
        )
        self.assertEqual(
            normalize_game_text("/秋月", DEFAULT_RESERVED_COMMANDS),
            "/秋月",
        )

    def test_hash_and_bang_prefixes_are_translated(self) -> None:
        self.assertEqual(normalize_game_text("#秋月"), "/秋月")
        self.assertEqual(normalize_game_text("＃状态"), "/状态")
        self.assertEqual(normalize_game_text("！ccb h"), "/ccb h")
        self.assertEqual(normalize_game_text("!窝一把"), "/窝一把")
        self.assertEqual(normalize_game_text("／状态"), "/状态")

    def test_empty_message_means_menu(self) -> None:
        self.assertEqual(normalize_game_text(""), "")
        self.assertEqual(normalize_game_text("   "), "")

    def test_plain_chat_is_not_a_game_message(self) -> None:
        self.assertIsNone(normalize_game_text("你好"))
        self.assertIsNone(normalize_game_text("今天秋月真好看"))
        self.assertIsNone(normalize_game_text("@秋月"))

    def test_reserved_slash_commands_are_left_to_astrbot(self) -> None:
        self.assertIsNone(normalize_game_text("/help", DEFAULT_RESERVED_COMMANDS))
        self.assertIsNone(normalize_game_text("/model", DEFAULT_RESERVED_COMMANDS))
        # "#" is the game's own namespace, so #help is game help.
        self.assertEqual(normalize_game_text("#help", DEFAULT_RESERVED_COMMANDS), "/help")

    def test_bare_prefix_becomes_help(self) -> None:
        self.assertEqual(normalize_game_text("/"), "/")
        self.assertEqual(normalize_game_text("#"), "/")


class PayloadTests(unittest.TestCase):
    def test_payload_shape(self) -> None:
        payload = build_event_payload(
            platform="aiocqhttp:default",
            account_id="123",
            group_id="456",
            sender_id="789",
            sender_name="舰长",
            role="captain",
            message_id="msg-1",
            text="/秋月",
            mentions=["111", "all"],
            reply_to=None,
            received_at=1760000000000,
        )

        self.assertEqual(payload["protocol"], 1)
        self.assertTrue(payload["request_id"])
        event = payload["event"]
        self.assertEqual(event["platform"], "aiocqhttp:default")
        self.assertEqual(event["channel"], {"type": "group", "id": "456"})
        self.assertEqual(event["sender"]["role"], "member")
        self.assertEqual(event["message"]["text"], "/秋月")
        self.assertEqual(event["message"]["mentions"], ["111", "all"])
        self.assertTrue(event["message"]["directed"])
        self.assertEqual(event["received_at"], 1760000000000)

    def test_missing_message_id_gets_a_fallback(self) -> None:
        payload = build_event_payload(
            platform="p",
            account_id="a",
            group_id="g",
            sender_id="s",
            sender_name="n",
            role="member",
            message_id="",
            text="",
        )
        self.assertTrue(payload["event"]["message"]["id"])


class ReplyValidationTests(unittest.TestCase):
    def test_clean_base64_image(self) -> None:
        encoded = base64.b64encode(b"png-bytes").decode("ascii")
        self.assertEqual(clean_base64_image(encoded), encoded)
        self.assertEqual(clean_base64_image(encoded[:4] + "\n" + encoded[4:]), encoded)

        with self.assertRaises(ServiceError):
            clean_base64_image("")
        with self.assertRaises(ServiceError):
            clean_base64_image("not base64!!!")

    def test_validate_text_reply(self) -> None:
        reply = validate_reply(
            {
                "protocol": 1,
                "request_id": "r",
                "reply": {"type": "text", "text": "hello"},
            },
        )
        self.assertEqual(reply["text"], "hello")

    def test_validate_none_reply(self) -> None:
        reply = validate_reply(
            {"protocol": 1, "request_id": "r", "reply": {"type": "none"}},
        )
        self.assertEqual(reply["type"], "none")

    def test_validate_image_reply(self) -> None:
        reply = validate_reply(
            {
                "protocol": 1,
                "request_id": "r",
                "reply": {
                    "type": "image",
                    "image": {"mime": "image/png", "base64": "aGVsbG8="},
                    "caption": "ok",
                    "fallback_text": "text",
                },
            },
        )
        self.assertEqual(reply["caption"], "ok")

    def test_protocol_mismatch_is_rejected(self) -> None:
        with self.assertRaises(ServiceError):
            validate_reply({"protocol": 2, "reply": {"type": "none"}})

    def test_image_without_base64_is_rejected(self) -> None:
        with self.assertRaises(ServiceError):
            validate_reply(
                {
                    "protocol": 1,
                    "reply": {"type": "image", "image": {"mime": "image/png"}},
                },
            )


class _EchoHandler(BaseHTTPRequestHandler):
    token = "test-token"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.headers.get("authorization") == f"Bearer {self.token}":
            return True
        self._send_json(401, {"error": "unauthorized"})
        return False

    def do_GET(self) -> None:
        if self.path != "/v1/health":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            return
        self._send_json(
            200,
            {"ok": True, "protocol": 1, "service": "test", "data_version": "test"},
        )

    def do_POST(self) -> None:
        if self.path != "/v1/events":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            return

        length = int(self.headers.get("content-length", "0") or "0")
        payload = json.loads(self.rfile.read(length) or b"{}")
        text = payload["event"]["message"]["text"]
        self._send_json(
            200,
            {
                "protocol": 1,
                "request_id": payload.get("request_id"),
                "reply": {"type": "text", "text": f"echo:{text}"},
            },
        )

    def log_message(self, *args) -> None:
        pass


class ClientTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _client(self, token: str = "test-token") -> CoopClient:
        return CoopClient(f"http://127.0.0.1:{self.port}", token=token, timeout=5)

    async def test_dispatch_round_trip(self) -> None:
        payload = build_event_payload(
            platform="test:default",
            account_id="bot",
            group_id="group",
            sender_id="user",
            sender_name="tester",
            role="member",
            message_id="msg-1",
            text="/秋月",
        )
        reply = await self._client().dispatch(payload)
        self.assertEqual(reply, {"type": "text", "text": "echo:/秋月"})

    async def test_health(self) -> None:
        health = await self._client().health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["protocol"], 1)

    async def test_auth_failure_is_an_error(self) -> None:
        payload = build_event_payload(
            platform="test:default",
            account_id="bot",
            group_id="group",
            sender_id="user",
            sender_name="tester",
            role="member",
            message_id="msg-2",
            text="/状态",
        )
        with self.assertRaises(ServiceError) as ctx:
            await self._client(token="wrong").dispatch(payload)
        self.assertIn("401", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
