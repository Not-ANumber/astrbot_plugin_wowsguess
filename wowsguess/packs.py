"""Data pack discovery and manifest handling.

A pack is a self-contained directory with ``ships.json``, ``attributes.json``,
``difficulties.json`` and ``pools/``. An optional ``manifest.json`` records the
server, source version and per-file checksums; it is used for logs and for
guarding against a pack being copied into the wrong server directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SERVER = "wg"
SUPPORTED_SERVERS = ("wg", "lesta")

_SERVER_LABELS = {
    "wg": "WG 官服",
    "lesta": "Lesta 服",
}


class PackError(RuntimeError):
    """A data pack is missing, malformed or belongs to another server."""


def normalize_server(value: str | None) -> str:
    raw = value if isinstance(value, str) else ""
    server = (raw or DEFAULT_SERVER).strip().lower()
    if server not in SUPPORTED_SERVERS:
        raise PackError(
            f"未知的数据服 {value!r}；可选：{', '.join(SUPPORTED_SERVERS)}",
        )
    return server


def server_label(server: str) -> str:
    return _SERVER_LABELS.get(server, server)


def read_manifest(pack_dir: str | Path) -> dict[str, Any] | None:
    """Read ``manifest.json`` if present; ``None`` for hand-made packs."""
    path = Path(pack_dir) / "manifest.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackError(f"数据包清单读取失败：{path}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise PackError(f"数据包清单必须是 JSON 对象：{path}")
    return raw


def resolve_pack_dir(
    packs_root: str | Path,
    server: str,
    data_dir: str | Path | None = None,
) -> Path:
    """Resolve the directory for ``server``; ``data_dir`` overrides the root."""
    if data_dir:
        path = Path(data_dir).expanduser()
    else:
        path = Path(packs_root).expanduser() / server

    if not (path / "ships.json").is_file():
        hint = ""
        if server == "lesta" and not data_dir:
            hint = (
                "；Lesta 数据包随插件分发，若缺失请重装插件或检查 packs/lesta/，"
                "也可以用 data_dir 手动指定；临时可先用 server=wg"
            )
        raise PackError(
            f"数据包「{server_label(server)}」未找到：{path} 缺少 ships.json{hint}",
        )

    manifest = read_manifest(path)
    if manifest is not None:
        manifest_server = manifest.get("server")
        if isinstance(manifest_server, str) and manifest_server.strip().lower() != server:
            raise PackError(
                "数据包目录与清单不一致："
                f"期望 {server}，清单是 {manifest_server}（{path}）",
            )
    return path


def describe_pack(pack_dir: str | Path, server: str) -> str:
    """Human-readable pack label for startup logs."""
    manifest = read_manifest(pack_dir)
    label = server_label(server)
    if manifest is None:
        return f"{label}（无清单）"
    sample = manifest.get("label")
    if isinstance(sample, str) and sample.strip():
        label = sample.strip()
    parts = [label]
    count = manifest.get("shipCount")
    if isinstance(count, int):
        parts.append(f"{count} 艘")
    generated_at = manifest.get("generatedAt")
    if isinstance(generated_at, str) and generated_at:
        parts.append(generated_at)
    return " · ".join(parts)
