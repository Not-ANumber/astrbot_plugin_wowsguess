"""Framework-agnostic helpers for the wowsguess AstrBot plugin.

This module intentionally has no AstrBot imports, so it can be unit-tested with
a plain Python interpreter. The plugin's ``main.py`` is the only AstrBot-aware
part.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterable
from typing import Any

PROTOCOL_VERSION = 1
PLUGIN_VERSION = "0.5.0"

# Prefixes accepted in chat. The service itself expects "/" commands; the
# plugin normalises "#" / "!" variants before sending.
SUPPORTED_PREFIXES = ("/", "／", "#", "＃", "！", "!")

# "/help" and friends belong to AstrBot's own command system. They are left
# untouched so the plugin does not shadow framework commands.
DEFAULT_RESERVED_COMMANDS = frozenset(
    {
        "help",
        "model",
        "new",
        "reset",
        "stop",
        "sid",
        "persona",
        "provider",
        "plugin",
        "tool",
        "mcp",
        "status",
    },
)

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 12 * 1024 * 1024


class ServiceError(RuntimeError):
    """The wowsguess service returned an error or an invalid response."""


def normalize_game_text(
    raw: str,
    reserved: Iterable[str] = DEFAULT_RESERVED_COMMANDS,
) -> str | None:
    """Turn a chat message into the service's ``/...`` command form.

    Returns:
        - ``""`` for an empty directed message (the service replies with its
          command menu),
        - a string beginning with ``"/"`` for a game command,
        - ``None`` when the message is not a game command and should be left to
          the AI bot.
    """
    text = (raw or "").strip()
    if not text:
        return ""

    prefix = next((p for p in SUPPORTED_PREFIXES if text.startswith(p)), None)
    if prefix is None:
        return None

    body = text[len(prefix) :].strip()
    if not body:
        return "/"

    if prefix in ("/", "／"):
        reserved_set = {str(item).strip().lower() for item in reserved if str(item).strip()}
        head = body.split(maxsplit=1)[0].lower()
        if head in reserved_set:
            return None

    return "/" + body


def build_event_payload(
    *,
    platform: str,
    account_id: str,
    group_id: str,
    sender_id: str,
    sender_name: str,
    role: str,
    message_id: str,
    text: str,
    mentions: Iterable[str] = (),
    reply_to: str | None = None,
    received_at: int | None = None,
) -> dict[str, Any]:
    """Build the ``POST /v1/events`` request body."""
    role_value = role if role in {"owner", "admin", "member"} else "member"
    timestamp = int(received_at) if received_at is not None else int(time.time() * 1000)
    return {
        "protocol": PROTOCOL_VERSION,
        "request_id": uuid.uuid4().hex,
        "event": {
            "platform": str(platform),
            "account_id": str(account_id),
            "channel": {"type": "group", "id": str(group_id)},
            "sender": {
                "id": str(sender_id),
                "name": str(sender_name)[:64],
                "role": role_value,
            },
            "message": {
                "id": str(message_id) if message_id else uuid.uuid4().hex,
                "text": str(text),
                "mentions": [str(item) for item in mentions],
                "reply_to": str(reply_to) if reply_to else None,
                "directed": True,
            },
            "received_at": timestamp,
        },
    }


def clean_base64_image(value: str) -> str:
    """Validate an image payload and return whitespace-free base64."""
    if not isinstance(value, str) or not value.strip():
        raise ServiceError("图片回复缺少 base64 数据")

    clean = "".join(value.split())
    try:
        raw = base64.b64decode(clean, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ServiceError("图片 base64 数据无效") from exc

    if len(raw) > MAX_IMAGE_BYTES:
        raise ServiceError(
            f"图片超过 {MAX_IMAGE_BYTES // (1024 * 1024)}MB 上限",
        )
    return clean


def validate_reply(data: Any) -> dict[str, Any]:
    """Validate a service response and return its ``reply`` object."""
    if not isinstance(data, dict):
        raise ServiceError("游戏服务返回的不是 JSON 对象")

    protocol = data.get("protocol")
    if protocol != PROTOCOL_VERSION:
        raise ServiceError(
            f"协议版本不匹配：服务端 {protocol!r}，插件 {PROTOCOL_VERSION}",
        )

    reply = data.get("reply")
    if not isinstance(reply, dict):
        raise ServiceError("游戏服务响应缺少 reply")

    reply_type = reply.get("type")
    if reply_type not in {"text", "image", "none"}:
        raise ServiceError(f"未知的回复类型：{reply_type!r}")

    if reply_type == "text" and not isinstance(reply.get("text"), str):
        raise ServiceError("text 回复缺少 text 字段")

    if reply_type == "image":
        image = reply.get("image")
        if not isinstance(image, dict) or not isinstance(image.get("base64"), str):
            raise ServiceError("image 回复缺少 image.base64")

    return reply


class CoopClient:
    """Small blocking HTTP client executed in a worker thread.

    Using ``urllib`` keeps the plugin dependency-free: AstrBot already owns the
    Python environment, and we do not need to add another HTTP stack.
    """

    def __init__(self, base_url: str, token: str = "", timeout: float = 15.0) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()
        self.timeout = max(1.0, float(timeout))

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._request_json, "GET", "/v1/health", None)

    async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = await asyncio.to_thread(
            self._request_json,
            "POST",
            "/v1/events",
            payload,
        )
        return validate_reply(data)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> Any:
        if not self.base_url:
            raise ServiceError("未配置游戏服务地址")

        url = f"{self.base_url}{path}"
        headers = {
            "accept": "application/json",
            "user-agent": f"wowsguess-astrbot-plugin/{PLUGIN_VERSION}",
        }
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["content-type"] = "application/json"
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES)
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", "replace").strip()
            suffix = f"：{detail}" if detail else ""
            raise ServiceError(f"游戏服务返回 HTTP {exc.code}{suffix}") from exc
        except urllib.error.URLError as exc:
            raise ServiceError(f"无法连接游戏服务 {self.base_url}：{exc.reason}") from exc
        except TimeoutError as exc:
            raise ServiceError(f"游戏服务请求超时（{self.timeout:.0f}s）") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServiceError("游戏服务返回了非 JSON 响应") from exc


__all__ = [
    "DEFAULT_RESERVED_COMMANDS",
    "MAX_IMAGE_BYTES",
    "PLUGIN_VERSION",
    "PROTOCOL_VERSION",
    "SUPPORTED_PREFIXES",
    "CoopClient",
    "ServiceError",
    "build_event_payload",
    "clean_base64_image",
    "normalize_game_text",
    "validate_reply",
]
