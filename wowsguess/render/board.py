"""Pillow port of the canvas board/start/help cards.

The layout constants and colour names are copied from the TypeScript renderer.
The bundled font is preferred; system fonts are a development fallback.
"""

from __future__ import annotations

import functools
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..about import BILI_ID, QQ_GROUP, SITE_URL
from ..engine import (
    attr_head_unit,
    attr_label,
    attr_value_label,
    display_name,
    format_cell_value,
    rarity_label,
)
from ..models import (
    BoardRenderInput,
    BoardRow,
    HelpRenderInput,
    Ship,
    StartRenderInput,
)
from .theme import (
    ACCENT,
    BG,
    BORDER,
    CELL,
    CELL_W,
    FAINT,
    FOOTER_H,
    HEADER_H,
    PAD,
    PANEL,
    PANEL_ALT,
    REVEAL_BG,
    REVEAL_H,
    ROW_H,
    SHIP_W,
    SHORT_LABEL,
    TABLE_HEAD_H,
    TABLE_W,
    TEXT,
    W,
    WARN_BG,
    WARN_TEXT,
    WARNING_H,
)

logger = logging.getLogger(__name__)

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_FONT_CANDIDATES = [
    os.environ.get("WOWSGUESS_FONT_PATH"),
    _PLUGIN_ROOT / "assets" / "fonts" / "NotoSansSC-subset.otf",
    _PLUGIN_ROOT / "assets" / "fonts" / "NotoSansSC-Regular.otf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.otf",
]
_BOLD_CANDIDATES = [
    os.environ.get("WOWSGUESS_FONT_BOLD_PATH"),
    _PLUGIN_ROOT / "assets" / "fonts" / "NotoSansSC-Bold.otf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def _font_config() -> tuple[str | None, str | None]:
    regular = None
    bold = None
    for candidate in _FONT_CANDIDATES:
        if candidate and Path(candidate).exists():
            regular = str(candidate)
            break
    for candidate in _BOLD_CANDIDATES:
        if candidate and Path(candidate).exists():
            bold = str(candidate)
            break
    if regular is None:
        logger.warning(
            "[render] 没有找到中文字体，图片里的中文可能显示为方框。"
            "请把 NotoSansSC 放进 assets/fonts/ 或设置 WOWSGUESS_FONT_PATH。",
        )
    else:
        logger.info("[render] 中文字体：%s", regular)
    return regular, bold


def _serialized(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class BoardRenderer:
    def __init__(self, font_path: str | None = None, bold_font_path: str | None = None) -> None:
        detected_regular, detected_bold = _font_config()
        self._regular_path = font_path or detected_regular
        self._bold_path = bold_font_path or detected_bold or self._regular_path
        self._fonts: dict[tuple[int, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
        self._probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self._cache: OrderedDict[tuple, bytes] = OrderedDict()
        self._cache_max = 16
        self._lock = threading.RLock()

    def _font(self, size: int, weight: int = 400):
        key = (int(size), 600 if weight >= 600 else 400)
        cached = self._fonts.get(key)
        if cached is not None:
            return cached
        path = self._bold_path if weight >= 600 else self._regular_path
        if path:
            try:
                font = ImageFont.truetype(path, int(size))
            except OSError as exc:
                logger.warning("[render] 字体加载失败 %s：%s", path, exc)
                font = ImageFont.load_default()
        else:
            font = ImageFont.load_default()
        self._fonts[key] = font
        return font

    def _measure(self, text: str, size: int, weight: int = 400) -> float:
        return float(self._probe.textlength(text, font=self._font(size, weight)))

    def _fit_text(
        self,
        text: str,
        max_width: float,
        size: int,
        weight: int = 400,
        min_size: int = 11,
    ) -> str:
        if not text:
            return ""
        current = size
        while current > min_size and self._measure(text, current, weight) > max_width:
            current -= 1
        if self._measure(text, current, weight) <= max_width:
            return text
        cut = text
        while len(cut) > 1 and self._measure(f"{cut}…", current, weight) > max_width:
            cut = cut[:-1]
        return f"{cut}…"

    def _text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        x: float,
        y: float,
        size: int,
        color: str,
        weight: int = 400,
        align: str = "left",
    ) -> None:
        anchor = {"left": "lm", "start": "lm", "right": "rm", "end": "rm", "center": "mm"}.get(
            align,
            "lm",
        )
        draw.text((x, y), text, font=self._font(size, weight), fill=color, anchor=anchor)

    @staticmethod
    def _round(
        draw: ImageDraw.ImageDraw,
        x: float,
        y: float,
        width: float,
        height: float,
        radius: float,
        fill: str,
        stroke: str | None = None,
    ) -> None:
        if width <= 0 or height <= 0:
            return
        draw.rounded_rectangle(
            [x, y, x + width - 1, y + height - 1],
            radius=radius,
            fill=fill,
            outline=stroke,
            width=1,
        )

    def _gradient(self, draw: ImageDraw.ImageDraw, x: float, y: float, width: float, height: float) -> None:
        start = Image.new("RGB", (1, 1), ACCENT).getpixel((0, 0))
        end = Image.new("RGB", (1, 1), BG).getpixel((0, 0))
        steps = max(1, int(width))
        for index in range(steps):
            ratio = index / steps
            color = tuple(
                int(start[channel] + (end[channel] - start[channel]) * ratio)
                for channel in range(3)
            )
            draw.rectangle([x + index, y, x + index + 1, y + height], fill=color)

    @staticmethod
    def _arrow(
        draw: ImageDraw.ImageDraw,
        x: float,
        y: float,
        direction: str,
        color: str,
    ) -> None:
        if direction == "up":
            points = [(x, y - 6), (x + 6, y + 4), (x - 6, y + 4)]
        else:
            points = [(x, y + 6), (x + 6, y - 4), (x - 6, y - 4)]
        draw.polygon(points, fill=color)

    def _ship_subtitle(self, ship: Ship, input: BoardRenderInput) -> str:
        parts: list[str] = []
        level = ship.attrs.get("level")
        if isinstance(level, (int, float)) and not isinstance(level, bool):
            parts.append(f"T{int(level)}")
        nation = input.defs.get("nation")
        if nation is not None and ship.attrs.get("nation") is not None:
            parts.append(attr_value_label(nation, ship.attrs["nation"]))
        species = input.defs.get("species")
        if species is not None and ship.attrs.get("species") is not None:
            parts.append(attr_value_label(species, ship.attrs["species"]))
        parts.append(rarity_label(ship.rarity))
        return " · ".join(part for part in parts if part)

    @staticmethod
    def _status_pill(status: str) -> tuple[str, str]:
        if status == "won":
            return "已获胜", "#79e0a5"
        if status == "lost":
            return "机会用尽", "#ff9f9f"
        if status == "aborted":
            return "已结束", "#ffcf7a"
        return "进行中", ACCENT

    @staticmethod
    def _warning(remaining: int) -> str | None:
        if remaining == 2:
            return "⚠ 只剩 2 次机会，请先讨论再猜"
        if remaining == 1:
            return "⚠ 最后 1 次机会"
        return None

    @staticmethod
    def _attr_short(definition) -> str:
        return SHORT_LABEL.get(definition.key, attr_label(definition))

    @staticmethod
    def _state_text(state: str) -> str:
        if state == "exact":
            return "相同"
        if state == "close":
            return "接近"
        return "差得远"

    @_serialized
    def board(self, input: BoardRenderInput) -> bytes:
        key = self._board_key(input)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        warning = input.session.status == "active" and self._warning(input.remaining) is not None
        header_h = HEADER_H + (WARNING_H if warning else 0)
        reveal_h = REVEAL_H if input.answer else 0
        table_top = header_h + reveal_h
        footer_top = table_top + TABLE_HEAD_H + max(1, len(input.rows)) * ROW_H
        height = footer_top + FOOTER_H

        image = Image.new("RGB", (W, height), BG)
        draw = ImageDraw.Draw(image)
        self._gradient(draw, PAD, 18, TABLE_W, 2)

        after_header = self._draw_header(draw, input)
        after_reveal = self._draw_reveal(draw, input, after_header)
        self._draw_table_header(draw, input, after_reveal)

        if not input.rows:
            self._text(
                draw,
                "还没有人猜。发送「猜 船名」开始本局。",
                W / 2,
                after_reveal + TABLE_HEAD_H + ROW_H / 2,
                18,
                FAINT,
                align="center",
            )
        else:
            for index, row in enumerate(input.rows):
                self._draw_row(
                    draw,
                    input,
                    row,
                    after_reveal + TABLE_HEAD_H + index * ROW_H,
                    index == len(input.rows) - 1,
                )

        self._draw_footer(draw, input, footer_top + 24)
        buffer = _save_png(image)
        self._cache[key] = buffer
        if len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        return buffer

    @_serialized
    def start(self, input: StartRenderInput) -> bytes:
        image = Image.new("RGB", (W, 640), BG)
        draw = ImageDraw.Draw(image)
        self._gradient(draw, PAD, 22, W - PAD * 2, 3)

        self._text(draw, "窝一把 · 合作模式", PAD, 86, 46, TEXT, 700)
        self._text(draw, f"全群一盘棋，共用 {input.max_attempts} 次机会", PAD, 132, 22, FAINT)

        self._round(draw, PAD, 176, W - PAD * 2, 104, 12, PANEL)
        stats = [
            ("难度", input.difficulty_label),
            ("题库", input.tier_label),
            ("机会", f"{input.max_attempts} 次"),
            ("房主", input.host_name),
        ]
        stat_width = (W - PAD * 2 - 60) / 4 - 20
        for index, (label, value) in enumerate(stats):
            x = PAD + 30 + index * ((W - PAD * 2 - 60) / 4)
            self._text(draw, label, x, 206, 15, FAINT)
            fitted = self._fit_text(value, stat_width, 24, 700, 14)
            self._text(draw, fitted, x, 244, 24, TEXT, 700)

        self._round(draw, PAD, 306, W - PAD * 2, 152, 12, PANEL_ALT, BORDER)
        self._text(draw, "怎么玩", PAD + 24, 338, 18, ACCENT, 700)
        self._text(
            draw,
            "1. 先 @机器人 /窝一把 或 /ccb 开局；猜船用 /秋月 这种写法。",
            PAD + 24,
            376,
            18,
            TEXT,
        )
        self._text(
            draw,
            "2. 每猜一次都会发一张棋盘图，绿色=相同，黄色=接近，灰色=差得远。",
            PAD + 24,
            408,
            18,
            TEXT,
        )
        self._text(
            draw,
            f"3. 猜中即胜；{input.max_attempts} 次用尽即负。答案只在结束时揭晓。",
            PAD + 24,
            440,
            18,
            TEXT,
        )

        self._round(draw, PAD, 484, W - PAD * 2, 92, 12, "#10243f")
        self._text(
            draw,
            "先 @机器人 再发「/秋月」；「@机器人 /状态」看棋盘；房主/管理可「@机器人 /结束」。",
            PAD + 24,
            516,
            18,
            "#cfe2ff",
        )
        self._text(draw, "只剩 2 次和最后 1 次时，图片会给出醒目提示。", PAD + 24, 548, 16, "#9fb8d8")

        self._text(draw, "答案只在结束时揭晓 · 请不要剧透", PAD, 612, 14, FAINT)
        self._text(draw, "合作模式", W - PAD, 612, 14, FAINT, align="right")
        return _save_png(image)

    @_serialized
    def guide(self, input: HelpRenderInput) -> bytes:
        is_help = input.kind == "help"
        height = 1180 if is_help else 860
        image = Image.new("RGB", (W, height), BG)
        draw = ImageDraw.Draw(image)
        self._gradient(draw, PAD, 22, W - PAD * 2, 3)

        self._text(
            draw,
            "窝一把 · 帮助" if is_help else "窝一把 · 快速上手",
            PAD,
            78,
            42,
            TEXT,
            700,
        )
        self._text(
            draw,
            f"当前有进行中的局，剩余 {input.remaining} 次"
            if input.active
            else "当前没有进行中的局",
            PAD,
            122,
            20,
            FAINT,
        )
        self._text(draw, "合作模式", W - PAD, 78, 18, ACCENT, 700, align="right")

        commands_top = 280 if is_help else 160
        if is_help:
            self._round(draw, PAD, 160, W - PAD * 2, 92, 12, PANEL)
            self._text(
                draw,
                f"全群共用 {input.max_attempts} 次机会 · 猜中即胜 · 用尽即负",
                PAD + 24,
                206,
                20,
                TEXT,
                600,
            )

        commands = list(HELP_COMMANDS)
        if not is_help:
            commands.append(("@机器人 /统计", "看本群战绩"))
        commands_height = 352 + max(0, len(commands) - 6) * 50
        self._round(
            draw,
            PAD,
            commands_top,
            W - PAD * 2,
            commands_height,
            12,
            PANEL,
            BORDER,
        )
        self._text(draw, "命令", PAD + 30, commands_top + 32, 18, FAINT, 700)
        for index, (command, description) in enumerate(commands):
            self._draw_command_row(
                draw,
                commands_top + 76 + index * 50,
                command,
                description,
            )

        if is_help:
            self._round(draw, PAD, 660, W - PAD * 2, 250, 12, PANEL_ALT, BORDER)
            self._text(draw, "怎么玩", PAD + 30, 694, 18, ACCENT, 700)
            rules = [
                "1. 先 @机器人，命令和猜船都以 / 开头。",
                "2. n=普通，h=困难；等级 9-11 与 T9-T11 等价。",
                "3. 重复船、未知船、冷却中、候选提示都不消耗次数。",
                "4. 候选 /1 确认；答案只在结束时揭晓；结束后发 /再来一局 重开。",
                "5. 发 /统计 查看本群战绩。",
            ]
            for index, rule in enumerate(rules):
                self._text(draw, rule, PAD + 30, 736 + index * 34, 17, TEXT)

            self._round(draw, PAD, 938, W - PAD * 2, 160, 12, PANEL_ALT, BORDER)
            self._text(draw, "关于", PAD + 30, 968, 18, ACCENT, 700)
            self._text(
                draw,
                f"单人模式 / 多人房间：请访问网页版 {SITE_URL.removeprefix('https://')}",
                PAD + 30,
                1004,
                17,
                TEXT,
            )
            self._text(draw, f"B站：{BILI_ID}", PAD + 30, 1034, 17, TEXT)
            self._text(draw, f"QQ群：{QQ_GROUP}", PAD + 30, 1064, 17, TEXT)
        else:
            self._text(
                draw,
                "n=普通，h=困难；等级 9-11 与 T9-T11 等价",
                PAD + 30,
                590,
                16,
                FAINT,
            )
            self._round(draw, PAD, 620, W - PAD * 2, 140, 12, PANEL_ALT, BORDER)
            self._text(draw, "关于", PAD + 30, 650, 18, ACCENT, 700)
            self._text(
                draw,
                f"网站：{SITE_URL.removeprefix('https://')}",
                PAD + 30,
                686,
                17,
                TEXT,
            )
            self._text(draw, f"B站：{BILI_ID}", PAD + 30, 716, 17, TEXT)
            self._text(draw, f"QQ群：{QQ_GROUP}", PAD + 30, 746, 17, TEXT)

        self._text(
            draw,
            "所有操作先 @机器人 · 猜船用 /船名 · 答案只在结束时揭晓",
            PAD,
            height - 48,
            15,
            FAINT,
        )
        return _save_png(image)

    def _draw_header(self, draw: ImageDraw.ImageDraw, input: BoardRenderInput) -> int:
        session = input.session
        self._text(draw, "窝一把 · 合作模式", PAD, 44, 34, TEXT, 700)
        self._text(
            draw,
            f"{input.difficulty_label} · {input.tier_label} · "
            f"{len(session.guesses)}/{input.remaining + len(input.rows)} 猜",
            PAD,
            82,
            18,
            FAINT,
        )

        pill_text, pill_color = self._status_pill(session.status)
        self._text(draw, pill_text, W - PAD, 44, 20, pill_color, 700, align="right")
        self._text(
            draw,
            f"剩余 {input.remaining} 次" if session.status == "active" else f"共 {len(session.guesses)} 猜",
            W - PAD,
            82,
            17,
            FAINT,
            align="right",
        )

        y = HEADER_H
        warning = self._warning(input.remaining) if session.status == "active" else None
        if warning:
            self._round(draw, PAD, y - 10, TABLE_W, WARNING_H - 8, 8, WARN_BG)
            self._text(draw, warning, PAD + 14, y + 11, 18, WARN_TEXT, 700)
            y += WARNING_H
        return y

    def _draw_reveal(self, draw: ImageDraw.ImageDraw, input: BoardRenderInput, top: int) -> int:
        answer = input.answer
        if answer is None:
            return top
        self._round(draw, PAD, top + 6, TABLE_W, REVEAL_H - 12, 10, REVEAL_BG)
        self._text(draw, f"答案：{display_name(answer)}", PAD + 18, top + 34, 27, "#c9ffe3", 700)
        self._text(draw, self._ship_subtitle(answer, input), PAD + 18, top + 62, 17, "#9fd8b8")
        self._text(draw, "本局已结束", W - PAD - 18, top + 34, 17, "#9fd8b8", align="right")
        return top + REVEAL_H

    def _draw_table_header(self, draw: ImageDraw.ImageDraw, input: BoardRenderInput, top: int) -> None:
        self._round(draw, PAD, top, TABLE_W, TABLE_HEAD_H, 10, PANEL)
        self._text(draw, "舰船", PAD + 14, top + 31, 17, FAINT, 700)
        draw.line(
            [(PAD + SHIP_W, top + 10), (PAD + SHIP_W, top + TABLE_HEAD_H - 10)],
            fill=BORDER,
            width=1,
        )
        for index, key in enumerate(input.attribute_keys):
            definition = input.defs.get(key)
            if definition is None:
                continue
            x = PAD + SHIP_W + index * CELL_W + CELL_W / 2
            self._text(draw, self._attr_short(definition), x, top + 22, 15, TEXT, 700, align="center")
            unit = attr_head_unit(definition)
            if unit:
                self._text(draw, unit, x, top + 44, 12, FAINT, align="center")

    def _draw_row(
        self,
        draw: ImageDraw.ImageDraw,
        input: BoardRenderInput,
        row: BoardRow,
        top: int,
        latest: bool,
    ) -> None:
        if latest:
            self._round(draw, PAD, top, TABLE_W, ROW_H, 8, "#1b2634")
            draw.rectangle([PAD, top + 8, PAD + 2, top + ROW_H - 8], fill=ACCENT)
        else:
            draw.rectangle([PAD, top, PAD + TABLE_W, top + ROW_H], fill=BG)

        draw.line(
            [(PAD, top + ROW_H), (PAD + TABLE_W, top + ROW_H)],
            fill=BORDER,
            width=1,
        )

        ship_label = self._fit_text(display_name(row.ship), SHIP_W - 28, 18, 700, 12)
        self._text(draw, ship_label, PAD + 12, top + 21, 18, TEXT, 700)
        nick_label = self._fit_text(row.nickname, SHIP_W - 28, 12, 400, 10)
        self._text(draw, nick_label, PAD + 12, top + 40, 12, FAINT)

        for index, feedback in enumerate(row.feedback):
            x = PAD + SHIP_W + index * CELL_W
            cell_x = x + 3
            cell_y = top + 5
            cell_w = CELL_W - 6
            cell_h = ROW_H - 10
            palette = CELL.get(feedback.state, CELL["far"])
            self._round(draw, cell_x, cell_y, cell_w, cell_h, 6, palette["bg"])

            arrow_space = 13 if feedback.direction else 0
            value_x = cell_x + (cell_w - arrow_space) / 2
            definition = input.defs.get(feedback.key)
            value_label = (
                format_cell_value(definition, feedback.guess_value)
                if definition is not None
                else str(feedback.guess_value)
            )
            fitted = self._fit_text(value_label, cell_w - 14 - arrow_space, 16, 600, 11)
            self._text(draw, fitted, value_x, cell_y + cell_h / 2, 16, palette["fg"], 600, align="center")

            if feedback.direction:
                self._arrow(
                    draw,
                    cell_x + cell_w - 9,
                    cell_y + cell_h / 2,
                    feedback.direction,
                    palette["fg"],
                )

    def _draw_footer(self, draw: ImageDraw.ImageDraw, input: BoardRenderInput, top: int) -> None:
        x = PAD
        for state in ("exact", "close", "far"):
            palette = CELL[state]
            self._round(draw, x, top, 14, 14, 3, palette["bg"])
            self._text(draw, self._state_text(state), x + 22, top + 7, 14, FAINT)
            x += 88
        self._text(draw, "箭头 = 答案数值更大/更小", x, top + 7, 14, FAINT)
        self._text(draw, "最新一行高亮", W - PAD, top + 7, 14, FAINT, align="right")
        self._text(
            draw,
            "本局已结束，答案仅在此揭晓。" if input.answer else "答案只在结束时揭晓。",
            PAD,
            top + 36,
            14,
            FAINT,
        )

    def _draw_command_row(
        self,
        draw: ImageDraw.ImageDraw,
        y: int,
        command: str,
        description: str,
    ) -> None:
        command_text = self._fit_text(command, 590, 20, 600, 13)
        self._text(draw, command_text, PAD + 30, y, 20, ACCENT, 600)
        description_text = self._fit_text(description, 330, 16, 400, 11)
        self._text(draw, description_text, W - PAD - 30, y, 16, FAINT, align="right")
        draw.line(
            [(PAD + 30, y + 25), (W - PAD - 30, y + 25)],
            fill=BORDER,
            width=1,
        )

    def _board_key(self, input: BoardRenderInput) -> tuple:
        rows_key = tuple(
            (
                row.ship.index,
                tuple(
                    (feedback.key, feedback.state, feedback.direction, str(feedback.guess_value))
                    for feedback in row.feedback
                ),
            )
            for row in input.rows
        )
        return (
            input.session.session_id,
            input.session.status,
            input.answer.index if input.answer else "",
            input.remaining,
            input.difficulty_label,
            input.tier_label,
            input.attribute_keys,
            rows_key,
        )


HELP_COMMANDS = [
    ("@机器人 /窝一把 或 /ccb", "开一局（默认普通 · 5–11）"),
    ("@机器人 /窝一把 h 9-11", "困难 + 等级范围"),
    ("@机器人 /秋月", "猜船（支持拼音/错字）"),
    ("@机器人 /状态", "看当前棋盘"),
    ("@机器人 /结束", "房主/群管理提前结束"),
    ("@机器人 /帮助", "完整说明"),
]


def _save_png(image: Image.Image) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


_default_renderer: BoardRenderer | None = None


def default_renderer() -> BoardRenderer:
    global _default_renderer
    if _default_renderer is None:
        _default_renderer = BoardRenderer()
    return _default_renderer
