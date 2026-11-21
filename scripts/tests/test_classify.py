#!/usr/bin/env python3
"""Tests for category classification (scripts/collect.py classify()).

Category membership is the whole point of this site: five topics, kept separate. The rules are
  * seed    — the series ticker appears VERBATIM in the official fee schedule (data/categories.json
              records the description it was confirmed against), and
  * keyword — a word-boundary heuristic on the market's OWN text, always labelled as a guess.

Regression record (2026-11-21): the keyword test used to look only at the market's title, which
is where it lost most of the in-scope universe. The 2028 presidential field is titled "Who will
win the next presidential election?" with the candidate in yes_sub_title, so the demo snapshot
published 36 empty "Van Hollen backers" rows and no KXPRESPERSON market at all, while
KXPRESPERSON-28-RPAU (790,337 contracts; 61,177 in 24h) was trading. Both directions are pinned
below, plus the word-boundary trap that once put "yes Vegas,yes Tie" into Gas Prices.

Run: python3 scripts/tests/test_classify.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from collect import classify  # noqa: E402

CATS = json.loads((ROOT / "data" / "categories.json").read_text())


def cat(ticker, hay=""):
    return classify(CATS, ticker, "", "", hay)


class SeedTests(unittest.TestCase):
    def test_every_seed_series_classifies_as_seed(self):
        for c in CATS["categories"]:
            for s in c["seed_series"]:
                with self.subTest(ticker=s["ticker"]):
                    self.assertEqual(cat(s["ticker"]), (c["id"], "seed"))

    def test_a_seed_series_is_confirmed_even_with_a_contradicting_title(self):
        # The fee schedule decides, not the text: a fee-schedule series stays confirmed.
        self.assertEqual(cat("KXAAAGASM", "bitcoin price"), ("gas", "seed"))


class KeywordTests(unittest.TestCase):
    def test_presidential_field_is_found_through_the_sub_title(self):
        # The exact text returned by GET /markets?series_ticker=KXPRESPERSON, 2026-11-21.
        self.assertEqual(
            cat("KXPRESPERSON-28-RPAU", "Who will win the next presidential election? Rand Paul"),
            ("elections", "keyword"),
        )

    def test_nominee_market_is_found_through_the_sub_title(self):
        self.assertEqual(
            cat("KXPRESNOMD-28-AOC", "Who will be the Democratic nominee for President in 2028? Alexandria Ocasio-Cortez"),
            ("elections", "keyword"),
        )

    def test_word_boundaries_still_exclude_the_vegas_trap(self):
        # F-12: "vegas" contains "gas"; a substring test put a sports combo into Gas Prices.
        self.assertEqual(cat("KXMVESPORTS-XX", "yes Vegas,yes Tie"), (None, None))

    def test_unrelated_market_is_not_absorbed(self):
        self.assertEqual(cat("KXMARMAD-27-OSU", "March Madness: Which team will win the 2027 NCAA championship? Ohio State"), (None, None))

    def test_each_topic_stays_separate(self):
        ids = {cat(t, t)[0] for t in ("gas price", "election", "grammy album", "bitcoin", "pga golf")}
        self.assertEqual(ids, {"gas", "elections", "culture", "crypto", "golf"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
