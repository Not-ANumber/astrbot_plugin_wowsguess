from __future__ import annotations

import unittest

from wowsguess.models import Ship
from wowsguess.resolve import ResolveCandidates, ResolveMatch, resolve_ship
from wowsguess.search import (
    build_ship_search_index,
    damerau_levenshtein,
    normalize_ship_query,
    search_ships,
)


def ship(
    index: str,
    name: str,
    name_zh: str | None = None,
    pinyin: str | None = None,
    initials: str | None = None,
) -> Ship:
    return Ship(
        index=index,
        name=name,
        name_zh=name_zh,
        alias_zh=None,
        pinyin=pinyin,
        pinyin_initials=initials,
        alias_pinyin=None,
        rarity="Common",
        attrs={},
    )


SHIPS = [
    ship("PJSB018", "Yamato 1944", "大和", "dahe", "dh"),
    ship("PJSB710", "FBO Yamato", "大和·魁", "dahe kui", "dh k"),
    ship("PASB017", "Montana 1945", "蒙大拿", "meng da na", "mdn"),
    ship("PASC020", "Des Moines 1948", "得梅因", "de mei yin", "dmy"),
    ship("PJSD003", "Isokaze", "矶风", "jifeng", "jf"),
    ship("PJSD510", "Hayate", "疾风", "jifeng", "jf"),
    ship("PGSB719", "Friedrich Carl", "弗里德里希·卡尔", "fulidelixi kaer", "fldlx ke"),
    ship(
        "PGSB506",
        "Prinz Eithel Friedrich",
        "艾特尔·弗里德里希亲王",
        "aiteer fulidelixi qinwang",
        "ate fldlx qw",
    ),
    ship(
        "PGSC506",
        "Admiral Graf Spee",
        "海军上将施佩伯爵",
        "haijunshangjiang shipei bojue",
        "hjsjspbj",
    ),
]
INDEX = build_ship_search_index(SHIPS)


class SearchTests(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_ship_query(" 大和 · 魁 "), "大和魁")
        self.assertEqual(normalize_ship_query("ＤＡＨＥ"), "dahe")
        self.assertEqual(normalize_ship_query("PASD506-A"), "pasd506a")
        self.assertEqual(normalize_ship_query("Myōkō"), "myoko")

    def test_damerau(self) -> None:
        self.assertEqual(damerau_levenshtein("蒙大娜", "蒙大拿"), 1)
        self.assertEqual(damerau_levenshtein("ab", "ba"), 1)
        self.assertEqual(damerau_levenshtein("dahe", "dahe"), 0)
        self.assertEqual(damerau_levenshtein("abc", "abcd", 0), 1)

    def test_exact(self) -> None:
        self.assertEqual(search_ships(INDEX, "大和魁").exact[0].ship.name_zh, "大和·魁")
        self.assertEqual(search_ships(INDEX, "dahe").exact[0].ship.name_zh, "大和")
        self.assertEqual(search_ships(INDEX, "dhk").exact[0].ship.name_zh, "大和·魁")

    def test_typo_window(self) -> None:
        result = search_ships(INDEX, "蒙大娜")
        hit = result.fuzzy[0]
        self.assertEqual(hit.ship.name_zh, "蒙大拿")
        self.assertEqual(hit.distance, 1)
        self.assertEqual(hit.query_length, hit.key_length)
        self.assertEqual(hit.window_length, 3)
        self.assertEqual(hit.position, "whole")

    def test_prefix_and_suffix_windows(self) -> None:
        result = search_ships(INDEX, "弗雷德里希")
        hit = result.fuzzy[0]
        self.assertEqual(hit.ship.name_zh, "弗里德里希·卡尔")
        self.assertEqual(hit.position, "prefix")
        self.assertEqual(hit.window_length, 5)
        self.assertEqual(hit.distance, 1)

        result = search_ships(INDEX, "斯佩伯爵")
        hit = result.fuzzy[0]
        self.assertEqual(hit.ship.name_zh, "海军上将施佩伯爵")
        self.assertEqual(hit.position, "suffix")
        self.assertEqual(hit.window_length, 4)
        self.assertEqual(hit.distance, 1)

    def test_pinyin_conflict_and_pure_number(self) -> None:
        result = search_ships(INDEX, "jifeng")
        self.assertIn("矶风", [hit.ship.name_zh for hit in result.exact])
        self.assertIn("疾风", [hit.ship.name_zh for hit in result.exact])
        self.assertEqual(search_ships(INDEX, "1").exact, [])
        self.assertEqual(search_ships(INDEX, "1").fuzzy, [])

    def test_resolve_auto_typo(self) -> None:
        result = resolve_ship(SHIPS, "蒙大娜")
        self.assertIsInstance(result, ResolveMatch)
        self.assertEqual(result.ship.name_zh, "蒙大拿")
        self.assertEqual(result.reason, "typo")

    def test_resolve_candidates(self) -> None:
        result = resolve_ship(SHIPS, "蒙大")
        self.assertIsInstance(result, ResolveCandidates)
        self.assertIn("蒙大拿", [ship.name_zh for ship in result.candidates])

        prefix = resolve_ship(SHIPS, "弗里德里希")
        self.assertIsInstance(prefix, ResolveCandidates)

        conflict = resolve_ship(SHIPS, "jifeng")
        self.assertIsInstance(conflict, ResolveCandidates)
        self.assertEqual(len(conflict.candidates), 2)

    def test_resolve_none(self) -> None:
        self.assertIsNone(resolve_ship(SHIPS, "zzzz"))
        self.assertIsNone(resolve_ship(SHIPS, "1"))


if __name__ == "__main__":
    unittest.main()
