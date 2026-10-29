"""Random helpers for answer selection."""

from __future__ import annotations

from collections.abc import Callable, Iterable


def pick_avoiding_recent(
    pool: Iterable[str],
    recent: set[str],
    pick_index: Callable[[int], int],
) -> str | None:
    values = list(pool)
    if not values:
        return None
    fresh = [item for item in values if item not in recent]
    # A narrow tier range may cover the whole recent window; repeating one
    # answer is better than failing to start a game.
    source = fresh if fresh else values
    return source[pick_index(len(source))]
