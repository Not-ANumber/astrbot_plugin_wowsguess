from __future__ import annotations

import unittest

from tests.fixture_data import make_data
from wowsguess.engine import (
    attr_head_unit,
    compare_attributes,
    display_name,
    filter_answers_by_tier,
    format_attr_value,
    format_cell_value,
    is_close,
    is_correct_guess,
    match_ships,
    normalize_pool_tier_range,
    normalize_tier_range,
)
from wowsguess.models import (
    AttributeDef,
    CloseBand,
    CloseThreshold,
    TierRange,
)
from wowsguess.resolve import resolve_ship


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = make_data()
        cls.defs = cls.data.defs

    def compare(self, guess: str, answer: str):
        return {
            item.key: item
            for item in compare_attributes(
                self.data.by_index[guess],
                self.data.by_index[answer],
                self.data.pools["standard"].attribute_keys,
                self.defs,
            )
        }

    def test_exact_close_and_far(self) -> None:
        result = self.compare("P1", "P3")
        self.assertEqual(result["level"].state, "exact")
        self.assertEqual(result["nation"].state, "exact")
        self.assertEqual(result["species"].state, "exact")
        self.assertEqual(result["health"].state, "close")  # 5% <= 15%
        self.assertEqual(result["speed"].state, "exact")
        self.assertEqual(result["reload"].state, "close")  # 0.1 <= 0.5
        self.assertEqual(result["conceal"].state, "close")  # 0.1 <= 1
        self.assertEqual(result["gunBarrels"].state, "exact")

    def test_banded_close_thresholds(self) -> None:
        definition = AttributeDef(
            key="caliber",
            label="主炮口径",
            kind="numeric",
            close=CloseThreshold(
                bands=(
                    CloseBand(up_to=152, absolute=20),
                    CloseBand(up_to=299, absolute=25),
                    CloseBand(up_to=None, absolute=30),
                )
            ),
        )

        # 140 落在第一段：差 13 <= 20
        self.assertTrue(is_close(140, 127, definition))
        self.assertTrue(is_close(127, 140, definition))  # 交换猜测/答案后结果一致
        # 152 仍是第一段（闭区间），差 19 <= 20
        self.assertTrue(is_close(152, 133, definition))
        # 153 进入第二段，差 23 <= 25；若错用第一段会判 false
        self.assertTrue(is_close(153, 130, definition))
        # 300 进入最后一段，差 20 <= 30
        self.assertTrue(is_close(300, 280, definition))
        # 同一段内差 40 > 30
        self.assertFalse(is_close(300, 260, definition))
        self.assertFalse(is_close(260, 300, definition))

    def test_zero_is_never_close(self) -> None:
        definition = AttributeDef(
            key="torpTubes",
            label="鱼雷管数",
            kind="numeric",
            close=CloseThreshold(absolute=20),
        )
        self.assertFalse(is_close(0, 5, definition))
        self.assertFalse(is_close(5, 0, definition))
        self.assertFalse(is_close(0, 0, definition))

    def test_banded_threshold_parses_from_json(self) -> None:
        definition = AttributeDef.from_json(
            {
                "key": "caliber",
                "close": {
                    "bands": [
                        {"upTo": 152, "abs": 20},
                        {"upTo": None, "abs": 30},
                    ]
                },
            }
        )
        self.assertEqual(
            definition.close.bands,
            (CloseBand(up_to=152, absolute=20), CloseBand(up_to=None, absolute=30)),
        )
        self.assertTrue(is_close(300, 280, definition))
        self.assertFalse(is_close(300, 260, definition))

    def test_discrete_and_numeric_directions(self) -> None:
        result = self.compare("P1", "P2")
        self.assertEqual(result["nation"].state, "far")
        self.assertIsNone(result["nation"].direction)
        self.assertEqual(result["species"].state, "far")
        self.assertIsNone(result["species"].direction)

        self.assertEqual(result["health"].state, "far")
        self.assertEqual(result["health"].direction, "up")  # answer 30000 > guess 20000
        self.assertEqual(result["speed"].direction, "down")  # answer 32 < guess 35
        self.assertEqual(result["reload"].direction, "up")  # numeric direction, not "better"
        self.assertEqual(result["conceal"].state, "close")
        self.assertEqual(result["conceal"].direction, "up")
        self.assertEqual(result["level"].state, "close")
        self.assertEqual(result["level"].direction, "down")

    def test_same_signature_group_is_correct(self) -> None:
        self.assertTrue(is_correct_guess("P1", "P5", self.data.pools["standard"]))
        self.assertTrue(is_correct_guess("P1", "P1", self.data.pools["standard"]))
        self.assertFalse(is_correct_guess("P1", "P3", self.data.pools["standard"]))

    def test_display_and_formatting(self) -> None:
        ship = self.data.by_index["P1"]
        self.assertEqual(display_name(ship), "阿尔法")
        self.assertEqual(display_name(ship, "en"), "Alpha")
        self.assertEqual(format_cell_value(self.defs["health"], 20000), "20,000")
        self.assertEqual(format_cell_value(self.defs["conceal"], 7.0), "7.0")
        self.assertEqual(format_cell_value(self.defs["reload"], 5.0), "5.0")
        self.assertEqual(format_attr_value(self.defs["health"], 20000), "20,000")
        self.assertEqual(format_attr_value(self.defs["conceal"], 7.0), "7.0 km")
        self.assertEqual(attr_head_unit(self.defs["level"]), "")
        self.assertEqual(attr_head_unit(self.defs["speed"]), "节")

    def test_tier_normalization(self) -> None:
        self.assertEqual(normalize_tier_range({"min": 0, "max": 20}), TierRange(1, 11))
        self.assertEqual(normalize_tier_range({"min": 9, "max": 6}), TierRange(6, 9))
        self.assertIsNone(normalize_pool_tier_range({"min": 1, "max": 3}))
        self.assertEqual(normalize_pool_tier_range({"min": 1, "max": 8}), TierRange(5, 8))

    def test_filter_answers_by_tier(self) -> None:
        answers = list(self.data.pools["standard"].answers)

        def level_of(index: str) -> int | None:
            value = self.data.by_index[index].attrs.get("level")
            return int(value) if isinstance(value, (int, float)) else None

        high = filter_answers_by_tier(answers, level_of, TierRange(9, 11))
        self.assertTrue(high)
        self.assertTrue(all(level_of(index) >= 9 for index in high))

        empty = filter_answers_by_tier(answers, level_of, TierRange(1, 1))
        self.assertEqual(empty, answers)  # empty filter falls back to the whole pool

    def test_match_and_resolve(self) -> None:
        ships = self.data.ships
        self.assertEqual(match_ships(ships, "阿尔法")[0].index, "P1")
        self.assertEqual(match_ships(ships, "Alpha")[0].index, "P1")
        self.assertEqual(match_ships(ships, "P1")[0].index, "P1")
        self.assertEqual(match_ships(ships, "aef")[0].index, "P1")
        self.assertEqual(match_ships(ships, "泽塔别名")[0].index, "P6")

        from wowsguess.resolve import ResolveCandidates, ResolveMatch

        exact = resolve_ship(ships, "阿尔法")
        self.assertIsInstance(exact, ResolveMatch)
        self.assertEqual(exact.ship.index, "P1")

        prefix = resolve_ship(ships, "阿尔")
        self.assertIsInstance(prefix, ResolveCandidates)
        self.assertIn("P1", [ship.index for ship in prefix.candidates])

        self.assertIsNone(resolve_ship(ships, "zzzz-not-a-ship"))


if __name__ == "__main__":
    unittest.main()
