"""Layout and colour constants copied from the canvas renderer."""

from __future__ import annotations

W = 1080
PAD = 40
TABLE_W = W - PAD * 2
SHIP_W = 148
CELL_W = (TABLE_W - SHIP_W) / 12
HEADER_H = 118
WARNING_H = 38
REVEAL_H = 84
TABLE_HEAD_H = 62
ROW_H = 58
FOOTER_H = 88

BG = "#0f1319"
PANEL = "#151b24"
PANEL_ALT = "#121821"
TEXT = "#e8edf5"
FAINT = "#66708a"
BORDER = "#262f3d"
ACCENT = "#5b9dff"
WARN_BG = "#3a2f12"
WARN_TEXT = "#ffe9a8"
REVEAL_BG = "#153a2b"

CELL = {
    "exact": {"bg": "#21734c", "fg": "#c9ffe3"},
    "close": {"bg": "#7d6413", "fg": "#ffe9a8"},
    "far": {"bg": "#242d3b", "fg": "#93a1b8"},
}

SHORT_LABEL = {
    "level": "等级",
    "nation": "国家",
    "health": "血量",
    "conceal": "隐蔽",
    "speed": "航速",
    "gunBarrels": "主炮",
    "caliber": "口径",
    "reload": "装填",
    "torpTubes": "鱼雷",
    "sonarRange": "水听",
    "radarRange": "雷达",
    "smokeDuration": "烟幕",
    "fireChance": "点火",
    "sigma": "散布",
}
