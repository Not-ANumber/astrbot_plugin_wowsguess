"""Official-platform Markdown quick-start menu."""

from __future__ import annotations

from ..about import BILI_ID, QQ_GROUP, SITE_URL
from ..models import HelpRenderInput


def _status_line(input: HelpRenderInput) -> str:
    if input.active:
        return f"当前有进行中的局，剩余 {input.remaining} 次。"
    return "当前没有进行中的局。"


def render_menu_markdown(input: HelpRenderInput) -> str:
    return "\n".join(
        [
            "# 窝一把 · 快速上手",
            f"> {_status_line(input)}",
            "> 下方按钮可查看棋盘和战绩。"
            if input.active
            else "> 下方按钮可直接开局，或查看本群战绩。",
            "",
            "- `/窝一把` 或 `/ccb` — 开一局",
            "- 开局可加 `n/h`（普通/困难）和等级 `9-11`",
            "- `/秋月` — 猜船（支持拼音/错字）",
            "- `/状态` — 当前棋盘",
            "- `/统计` — 本群战绩",
            "- `/结束` — 房主/群管理结束",
            "- `/再来一局` — 沿用上一局配置",
            "- `/帮助` — 完整说明",
            "",
            "## 关于",
            f"- 网站：[{SITE_URL.removeprefix('https://').removeprefix('http://')}]({SITE_URL})",
            f"- B站：`{BILI_ID}`",
            f"- QQ群：{QQ_GROUP}",
            "",
            "> 先 @机器人",
        ],
    )
