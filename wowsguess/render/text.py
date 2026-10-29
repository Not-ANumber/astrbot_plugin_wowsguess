"""Text fallback for image rendering.

Images are the default; this module is both the fallback when Pillow fails and
the source of truth used by parity tests.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..engine import (
    attr_label,
    attr_value_label,
    display_name,
    format_attr_value,
    rarity_label,
)
from ..models import (
    AttributeDef,
    BoardRenderInput,
    BoardRow,
    Feedback,
    Ship,
    StartRenderInput,
)


def _value_of(ship: Ship, key: str) -> object | None:
    return ship.attrs.get(key)


def ship_subtitle(
    ship: Ship,
    defs: Mapping[str, AttributeDef],
    include_rarity: bool = True,
) -> str:
    parts: list[str] = []
    level = ship.attrs.get("level")
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        parts.append(f"T{int(level)}")
    nation = defs.get("nation")
    if nation is not None and ship.attrs.get("nation") is not None:
        parts.append(attr_value_label(nation, ship.attrs["nation"]))
    species = defs.get("species")
    if species is not None and ship.attrs.get("species") is not None:
        parts.append(attr_value_label(species, ship.attrs["species"]))
    if include_rarity:
        parts.append(rarity_label(ship.rarity))
    return " · ".join(part for part in parts if part)


def _arrow(direction: str | None) -> str:
    if direction == "up":
        return "↑"
    if direction == "down":
        return "↓"
    return ""


def _icon(state: str) -> str:
    if state == "exact":
        return "✅"
    if state == "close":
        return "🟨"
    return "⬜"


def _feedback_lines(row: BoardRow, defs: Mapping[str, AttributeDef]) -> list[str]:
    parts: list[str] = []
    for feedback in row.feedback:
        definition = defs.get(feedback.key)
        if definition is None:
            parts.append(f"{feedback.key} {feedback.guess_value}")
            continue
        parts.append(
            f"{attr_label(definition)} {format_attr_value(definition, feedback.guess_value)}"
            f"{_icon(feedback.state)}{_arrow(feedback.direction)}",
        )
    return [" ｜ ".join(parts[index : index + 3]) for index in range(0, len(parts), 3)]


def _summary(row: BoardRow) -> str:
    exact = sum(1 for feedback in row.feedback if feedback.state == "exact")
    close = sum(1 for feedback in row.feedback if feedback.state == "close")
    far = sum(1 for feedback in row.feedback if feedback.state == "far")
    return f"{exact}✓ {close}≈ {far}⬜"


def _warning(remaining: int) -> str | None:
    if remaining == 2:
        return "⚠️ 只剩 2 次机会，请先讨论再猜。"
    if remaining == 1:
        return "⚠️ 最后 1 次机会。"
    return None


def render_start_text(input: StartRenderInput) -> str:
    return "\n".join(
        [
            "【窝一把 · 合作模式】",
            f"难度 {input.difficulty_label} · {input.tier_label} · {input.max_attempts} 次机会全群共用",
            "先 @机器人 /窝一把 或 /ccb 开局；猜船用 /秋月（支持拼音/错字）；@机器人 /状态 看棋盘；@机器人 /结束 由房主/管理提前结束。",
            f"本局由 {input.host_name} 发起。",
        ],
    )


def render_answer_line(answer: Ship, defs: Mapping[str, AttributeDef]) -> str:
    return f"答案：{display_name(answer)}（{ship_subtitle(answer, defs)}）"


def render_board_text(input: BoardRenderInput) -> str:
    session = input.session
    rows = list(input.rows)
    title = (
        "合作模式 · 进行中"
        if session.status == "active"
        else f"合作模式 · {_status_label(session.status)}"
    )
    progress = (
        f"剩余 {input.remaining}/{input.remaining + len(rows)}"
        if session.status == "active"
        else f"共 {len(rows)} 猜"
    )
    lines = [f"【{title}】{input.difficulty_label} · {input.tier_label} · {progress}"]

    if session.status == "active":
        warning = _warning(input.remaining)
        if warning:
            lines.append(warning)

    if input.answer is not None:
        lines.append(render_answer_line(input.answer, input.defs))

    for row in rows:
        lines.append(
            f"{row.attempt}. {row.nickname} · {display_name(row.ship)} — {_summary(row)}",
        )

    if rows:
        latest = rows[-1]
        lines.append(
            f"最近一猜：{latest.nickname} · {display_name(latest.ship)}（第 {latest.attempt} 猜）",
        )
        lines.extend(_feedback_lines(latest, input.defs))

    lines.append("✅ 相同 · 🟨 接近 · ⬜ 差得远 · 箭头 = 答案数值更大/更小")
    return "\n".join(lines)


def render_guess_text(input: BoardRenderInput) -> str:
    return render_board_text(input)


def _status_label(status: str) -> str:
    if status == "won":
        return "已获胜"
    if status == "lost":
        return "机会用尽"
    if status == "aborted":
        return "已结束"
    return "进行中"


def render_ship_line(ship: Ship) -> str:
    return display_name(ship)


def attr_value_for_text(definition: AttributeDef, ship: Ship) -> str:
    value = _value_of(ship, definition.key)
    return "—" if value is None else format_attr_value(definition, value)
