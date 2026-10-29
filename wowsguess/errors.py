"""Game-level errors.

The service raises these; the adapter turns them into chat replies. Codes stay
stable so tests and adapters do not depend on message text.
"""

from __future__ import annotations


class CoopError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message
