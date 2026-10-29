from __future__ import annotations

import unittest

from tests.fixture_data import make_data, make_message
from wowsguess.commands import (
    CommandAction,
    MenuAction,
    ShipAction,
    clean_ship_text,
    classify_message,
    parse_command,
    parse_start_options,
)
from wowsguess.errors import CoopError
from wowsguess.models import TierRange


class CommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = make_data()

    def test_parse_command(self) -> None:
        self.assertEqual(parse_command("/窝一把").name, "start")
        self.assertEqual(parse_command("/ccb h 5-8").arg, "h 5-8")
        self.assertEqual(parse_command("/CCB n").name, "start")
        self.assertEqual(parse_command("窝一把").name, "start")
        self.assertEqual(parse_command("/状态").name, "status")
        self.assertEqual(parse_command("/帮助").name, "help")
        self.assertEqual(parse_command("/统计").name, "stats")
        self.assertEqual(parse_command("/战绩").name, "stats")
        self.assertEqual(parse_command("/再来一局").name, "restart")
        self.assertEqual(parse_command("/重开").name, "restart")
        self.assertEqual(parse_command("/秋月").name, "unknown")
        self.assertEqual(parse_command("/秋月").arg, "秋月")
        self.assertEqual(parse_command("今天吃什么").name, "unknown")

    def test_parse_start_options(self) -> None:
        self.assertEqual(self.data.default_difficulty.key, "standard")
        options = parse_start_options("", self.data)
        self.assertEqual(options.difficulty_key, "standard")
        self.assertEqual(options.tier_range, TierRange(5, 11))

        options = parse_start_options("困难", self.data)
        self.assertEqual(options.difficulty_key, "hard")

        options = parse_start_options("n 5-8", self.data)
        self.assertEqual(options.tier_range, TierRange(5, 8))

        options = parse_start_options("T8", self.data)
        self.assertEqual(options.tier_range, TierRange(8, 8))

        with self.assertRaises(CoopError):
            parse_start_options("究极", self.data)
        with self.assertRaises(CoopError):
            parse_start_options("T1-T3", self.data)

    def test_clean_ship_text(self) -> None:
        self.assertEqual(clean_ship_text("“阿尔法”！"), "阿尔法")
        self.assertEqual(clean_ship_text("《阿尔法》。"), "阿尔法")

    def test_classify(self) -> None:
        self.assertIsNone(classify_message(make_message("阿尔法", directed=False), self.data, True))

        action = classify_message(make_message("/阿尔法"), self.data, True)
        self.assertIsInstance(action, ShipAction)
        self.assertEqual(action.query, "阿尔法")

        action = classify_message(make_message("阿尔法"), self.data, True)
        self.assertIsInstance(action, MenuAction)

        action = classify_message(make_message("/阿尔法"), self.data, False)
        self.assertIsInstance(action, MenuAction)

        action = classify_message(make_message("今天阿尔法真好看"), self.data, True)
        self.assertIsInstance(action, MenuAction)

        action = classify_message(make_message("/窝一把"), self.data, False)
        self.assertIsInstance(action, CommandAction)
        self.assertEqual(action.command.name, "start")

        action = classify_message(make_message("/状态"), self.data, True)
        self.assertIsInstance(action, CommandAction)
        self.assertEqual(action.command.name, "status")

        action = classify_message(make_message(""), self.data, False)
        self.assertIsInstance(action, MenuAction)

        for text in ("/1", "/取消"):
            action = classify_message(make_message(text), self.data, True)
            self.assertIsInstance(action, ShipAction)
            self.assertEqual(action.query, text[1:])

        action = classify_message(make_message("/统计"), self.data, False)
        self.assertIsInstance(action, CommandAction)
        self.assertEqual(action.command.name, "stats")


if __name__ == "__main__":
    unittest.main()
