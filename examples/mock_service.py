"""Tiny mock of the wowsguess-coop HTTP service (remote mode).

This is only for plugin development: it echoes commands and can return a 1x1
PNG, so you can verify AstrBot installation, event mapping and image sending
without the real game service. The default local mode does not use this mock.

    py examples/mock_service.py --port 8787 --token change-me

Then configure the plugin with:

    service_url: http://127.0.0.1:8787
    auth_token: change-me
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# 1x1 transparent PNG. Good enough to exercise the image path.
PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)


class MockHandler(BaseHTTPRequestHandler):
    token = os.environ.get("AUTH_TOKEN", "")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not self.token:
            return True
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
            {
                "ok": True,
                "protocol": 1,
                "service": "wowsguess-mock",
                "service_version": "0.1.0",
                "data_version": "mock",
                "ships": 0,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/v1/events":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            return

        length = int(self.headers.get("content-length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        event = payload.get("event") or {}
        message = event.get("message") or {}
        text = str(message.get("text") or "")
        request_id = payload.get("request_id")

        if text.startswith("/图") or text.startswith("/image"):
            reply = {
                "type": "image",
                "image": {"mime": "image/png", "base64": PNG_1X1},
                "caption": "mock 图片",
                "fallback_text": "mock 图片（发送失败时的文本）",
            }
        elif text in {"/", "/帮助", "/help"}:
            reply = {
                "type": "text",
                "text": (
                    "【mock · 窝一把】\n"
                    "@机器人 /窝一把 [n|h] [5-8]\n"
                    "@机器人 /状态\n"
                    "@机器人 /结束\n"
                    "@机器人 /帮助\n"
                    "@机器人 /秋月\n"
                    "发 /图 可以测试图片回复。"
                ),
            }
        elif text.startswith("/窝一把") or text.startswith("/ccb"):
            reply = {
                "type": "text",
                "text": f"mock：已收到开局命令 {text}（真实服务会返回开局图）",
            }
        else:
            reply = {"type": "text", "text": f"mock 收到：{text or '（空消息，相当于只 @ 机器人）'}"}

        self._send_json(
            200,
            {
                "protocol": 1,
                "request_id": request_id,
                "reply": reply,
            },
        )

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[mock] {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="wowsguess-coop mock service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--token",
        default=os.environ.get("AUTH_TOKEN", ""),
        help="Bearer token; empty disables auth",
    )
    args = parser.parse_args()

    MockHandler.token = args.token
    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(f"[mock] listening on http://{args.host}:{args.port}")
    print(f"[mock] auth: {'enabled' if args.token else 'disabled'}")
    print(
        "[mock] try: curl -H "
        f"'Authorization: Bearer {args.token or 'none'}' "
        f"http://{args.host}:{args.port}/v1/health",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
