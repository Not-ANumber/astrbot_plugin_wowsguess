"""Framework-agnostic wowsguess co-op game core.

The package has no AstrBot imports. ``main.py`` is the only adapter.
"""

from .models import (
    Actor,
    AttributeDef,
    BoardRenderInput,
    BoardRow,
    CommandButton,
    CoopConfig,
    CoopStats,
    CoopStatsLeader,
    DifficultyDef,
    Feedback,
    GameData,
    Guess,
    HelpRenderInput,
    ImageReply,
    IncomingMessage,
    MarkdownReply,
    Pool,
    Session,
    Ship,
    StartRenderInput,
    TextReply,
    TierRange,
)
from .errors import CoopError

__all__ = [
    "Actor",
    "AttributeDef",
    "BoardRenderInput",
    "BoardRow",
    "CommandButton",
    "CoopConfig",
    "CoopStats",
    "CoopStatsLeader",
    "CoopError",
    "DifficultyDef",
    "Feedback",
    "GameData",
    "Guess",
    "HelpRenderInput",
    "ImageReply",
    "IncomingMessage",
    "MarkdownReply",
    "Pool",
    "Session",
    "Ship",
    "StartRenderInput",
    "TextReply",
    "TierRange",
]
