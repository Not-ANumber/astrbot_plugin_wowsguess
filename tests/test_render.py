from __future__ import annotations

import unittest
from io import BytesIO

from PIL import Image

from tests.fixture_data import make_data
from wowsguess.engine import compare_attributes
from wowsguess.models import (
    BoardRenderInput,
    BoardRow,
    HelpRenderInput,
    Session,
    StartRenderInput,
    TierRange,
)
from wowsguess.render.board import BoardRenderer
from wowsguess.render.text import render_board_text

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = make_data()
        cls.answer = cls.data.by_index["P1"]
        cls.guess = cls.data.by_index["P2"]
        cls.session = Session(
            platform="test:bot",
            group_id="g1",
            session_id="render-test",
            status="active",
            answer_index="P1",
            difficulty="standard",
            tier_range=TierRange(5, 11),
            guesses=[],
            host_id="u1",
            host_name="A",
            data_version="fixture-1",
            created_at=1,
            updated_at=1,
        )
        cls.renderer = BoardRenderer()

    def board_input(self, *, status: str = "active", with_answer: bool = False):
        feedback = compare_attributes(
            self.guess,
            self.answer,
            self.data.pools["standard"].attribute_keys,
            self.data.defs,
        )
        session = Session(
            platform=self.session.platform,
            group_id=self.session.group_id,
            session_id=f"render-{status}-{with_answer}",
            status=status,
            answer_index="P1",
            difficulty="standard",
            tier_range=TierRange(5, 11),
            guesses=[],
            host_id="u1",
            host_name="A",
            data_version="fixture-1",
            created_at=1,
            updated_at=1,
        )
        return BoardRenderInput(
            session=session,
            rows=(
                BoardRow(
                    attempt=1,
                    nickname="B",
                    ship=self.guess,
                    feedback=feedback,
                ),
            ),
            answer=self.answer if with_answer else None,
            remaining=7,
            difficulty_label="普通",
            tier_label="T5–T11",
            attribute_keys=self.data.pools["standard"].attribute_keys,
            defs=self.data.defs,
        )

    def test_board_is_1080_wide_png(self) -> None:
        png = self.renderer.board(self.board_input())
        self.assertTrue(png.startswith(PNG_SIGNATURE))
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.width, 1080)
            self.assertGreater(image.height, 200)
            self.assertEqual(image.format, "PNG")

    def test_board_cache_returns_same_bytes(self) -> None:
        input = self.board_input()
        self.assertIs(self.renderer.board(input), self.renderer.board(input))

    def test_start_and_help_cards(self) -> None:
        start = self.renderer.start(
            StartRenderInput(
                host_name="A",
                difficulty_label="普通",
                tier_label="T5–T11",
                max_attempts=8,
            ),
        )
        self.assertTrue(start.startswith(PNG_SIGNATURE))
        with Image.open(BytesIO(start)) as image:
            self.assertEqual(image.width, 1080)

        for kind in ("menu", "help"):
            png = self.renderer.guide(
                HelpRenderInput(kind=kind, active=False, remaining=8, max_attempts=8),
            )
            self.assertTrue(png.startswith(PNG_SIGNATURE))
            with Image.open(BytesIO(png)) as image:
                self.assertEqual(image.width, 1080)
                self.assertGreater(image.height, 500)

    def test_text_hides_answer_until_reveal(self) -> None:
        active = render_board_text(self.board_input())
        self.assertNotIn("阿尔法", active)

        revealed = render_board_text(self.board_input(status="won", with_answer=True))
        self.assertIn("阿尔法", revealed)


if __name__ == "__main__":
    unittest.main()
