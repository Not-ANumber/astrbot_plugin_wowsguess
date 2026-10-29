"""Framework-neutral façade used by adapters.

Adapters only need to build an ``IncomingMessage`` and send the returned
``Reply``. Classification, parsing, dedup and dispatch all live here.
"""

from __future__ import annotations

import time
from typing import Callable

from .commands import (
    CommandAction,
    MenuAction,
    ShipAction,
    classify_message,
    parse_start_options,
)
from .errors import CoopError
from .models import Actor, CoopConfig, GameData, IncomingMessage, Reply, TextReply
from .service import CoopRenderer, CoopService
from .store import BotStore


class GameApp:
    def __init__(
        self,
        data: GameData,
        store: BotStore,
        cfg: CoopConfig | None = None,
        renderer: CoopRenderer | None = None,
        now: Callable[[], int] | None = None,
        rng=None,
    ) -> None:
        self.data = data
        self.store = store
        self.now = now or (lambda: int(time.time() * 1000))
        self.service = CoopService(
            data=data,
            store=store,
            cfg=cfg,
            renderer=renderer,
            now=self.now,
            rng=rng,
        )

    def handle(self, message: IncomingMessage) -> Reply | None:
        actor = Actor(
            platform=message.platform,
            group_id=message.group_id,
            user_id=message.user_id,
            nickname=message.nickname,
            role=message.role,
        )
        action = classify_message(
            message,
            self.data,
            self.service.has_active_game(actor),
        )
        if action is None:
            return None

        if message.message_id and not self.store.seen_message(
            message.platform,
            message.message_id,
            self.now(),
        ):
            return None

        try:
            return self._dispatch(actor, action)
        except CoopError as exc:
            # A ship guess may race with an end/timeout; staying silent is
            # better than interrupting the group with an error.
            if isinstance(action, ShipAction) and exc.code in {"NO_SESSION", "SESSION_ENDED"}:
                return None
            return TextReply(exc.message)

    def _dispatch(self, actor: Actor, action) -> Reply:
        if isinstance(action, MenuAction):
            return self.service.menu(actor)

        if isinstance(action, ShipAction):
            return self.service.guess(actor, action.query)

        assert isinstance(action, CommandAction)
        command = action.command
        if command.name == "start":
            return self.service.start(actor, parse_start_options(command.arg, self.data))
        if command.name == "restart":
            return self.service.restart(actor)
        if command.name == "stats":
            return self.service.stats(actor)
        if command.name == "status":
            return self.service.status(actor)
        if command.name == "end":
            return self.service.end(actor)
        if command.name == "help":
            return self.service.help(actor)
        return self.service.menu(actor)

    def close(self) -> None:
        self.store.close()
