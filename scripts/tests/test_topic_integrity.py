#!/usr/bin/env python3
"""Topic integrity: a series' own official record must not contradict the topic it is in (F-97).

Why this suite exists
  F-38 (2026-11-21) found natural-gas futures published inside *Gas Prices* and excluded the
  15-minute series `KXNATGAS15M`. The same underlying reached the site again through a
  different door: Kalshi files the DAILY contract `KXNATGASD` under categories ["Entertainment"]
  with tags ["Oil & Gas"], so the collector's official-category discovery
  (`GET /series?category=Entertainment` -> Culture) published 20 natural-gas rows inside the
  **Culture** topic in the 2026-11-25T13:16:43Z snapshot, while the title keyword "gas" would
  have said Gas Prices. The category-only rule could not see it: "Entertainment" is a Culture
  category, so the row looked compatible.

  Two rules are pinned here:
    1. `KXNATGASD` is excluded from every topic, with a reason that quotes the official
       series record (the same treatment its 15-minute sibling already has).
    2. A series whose official TAGS name a different topic's domain is refused and counted,
       whatever category the exchange files it under. The tag is the narrower statement:
       KXNATGASD is categories ["Entertainment"] + tags ["Oil & Gas"].

What is asserted
  1. The exclusion list names KXNATGASD and its reason cites the official series URL.
  2. The classifier returns no topic for a KXNATGASD market (whatever the title says).
  3. `category_conflict` refuses culture+["Oil & Gas"], culture+["Crypto"], gas+["Crypto"],
     golf+["Crypto"] and accepts gas+["Oil & Gas"], crypto+["Crypto"], golf+["Golf"],
     culture+["Entertainment"], and every topic with unknown (absent) tags.
  4. The COMMITTED snapshot contains no published row whose series' official tags contradict
     its topic, except rows whose series the collector's own exclusion list names (those are
     removed by the next collector pass, which is the only writer of data/live).

Run: python3 scripts/tests/test_topic_integrity.py     (exit 0 pass, 1 fail)
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "data" / "live"


def load_collect():
    spec = importlib.util.spec_from_file_location("collect_under_test", ROOT / "scripts" / "collect.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ExclusionListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collect = load_collect()

    def test_the_daily_natural_gas_series_is_excluded_with_an_official_source(self):
        reasons = self.collect.EXCLUDE_KEYWORD_SERIES
        self.assertIn("KXNATGASD", reasons,
                      "the daily natural-gas series must be excluded from every topic")
        reason = reasons["KXNATGASD"]
        self.assertIn("https://external-api.demo.kalshi.co/trade-api/v2/series/KXNATGASD", reason,
                      "the exclusion reason must cite the official series record")
        self.assertIn("Natural Gas", reason)

    def test_the_sibling_15_minute_series_is_still_excluded(self):
        self.assertIn("KXNATGAS15M", self.collect.EXCLUDE_KEYWORD_SERIES)

    def test_no_topic_is_returned_for_an_excluded_series(self):
        cats = json.loads((ROOT / "data" / "categories.json").read_text())
        for title in ("Will the natural gas close price be above 3.295 USD/MMBtu on November 24, 2026 at 5:00 PM EST?",
                      "Natural Gas Daily",
                      "Will average **gas prices** be above $3.90?"):
            got = self.collect.classify(cats, "KXNATGASD", "Natural Gas Daily",
                                        "Entertainment", title)
            self.assertEqual(got, (None, None),
                             f"an excluded series must not be classified into a topic: {title!r}")

    def test_a_normal_series_is_still_classified(self):
        cats = json.loads((ROOT / "data" / "categories.json").read_text())
        got = self.collect.classify(cats, "KXAAAGASM", "US gas price", "Economics",
                                    "Will average **gas prices** be above $3.90?")
        self.assertEqual(got, ("gas", "seed"),
                         "the retail gasoline series must stay in the gas topic")


class TagConflictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collect = load_collect()

    def test_a_tag_from_another_topic_is_a_conflict(self):
        c = self.collect.category_conflict
        self.assertIsNotNone(c("culture", ["Entertainment"], "keyword", ["Oil & Gas"]),
                             "natural gas tagged 'Oil & Gas' cannot be a Culture market")
        self.assertIsNotNone(c("culture", ["Entertainment"], "seed", ["Crypto"]))
        self.assertIsNotNone(c("gas", ["Economics"], "keyword", ["Crypto"]))
        self.assertIsNotNone(c("golf", ["Sports"], "seed", ["Crypto"]))
        self.assertIsNotNone(c("elections", ["Elections"], "seed", ["Golf"]))

    def test_the_owning_topic_and_unknown_tags_are_never_a_conflict(self):
        c = self.collect.category_conflict
        self.assertIsNone(c("gas", ["Economics"], "keyword", ["Oil & Gas"]),
                          "a retail gasoline series is tagged 'Oil & Gas' and stays in gas")
        self.assertIsNone(c("crypto", ["Crypto"], "seed", ["Crypto", "Hourly"]))
        self.assertIsNone(c("golf", ["Sports"], "seed", ["Golf"]))
        self.assertIsNone(c("culture", ["Entertainment"], "keyword", ["Emmys", "Awards"]))
        self.assertIsNone(c("culture", ["Entertainment"], "keyword", None),
                          "an absent tags list is unknown, never a contradiction")
        self.assertIsNone(c("culture", ["Entertainment"], "keyword", []))
        self.assertIsNone(c("culture", ["Entertainment"], "keyword", ["Econ Daily"]),
                          "a tag that names no topic's domain never excludes a row")

    def test_a_non_domain_tag_never_names_a_topic(self):
        for tag in ("Econ Daily", "15 min", "Hourly", "Markets", "Hourly temperature", "Metals"):
            self.assertNotIn(tag, self.collect.TAG_DOMAIN_TOPIC,
                             f"{tag!r} is not a domain tag of one of the five topics")


class CommittedSnapshotTests(unittest.TestCase):
    """The published rows must not contradict their own series record."""

    @classmethod
    def setUpClass(cls):
        cls.collect = load_collect()
        cls.snapshot = json.loads((LIVE / "markets.json").read_text())
        cls.series_index = cls.snapshot.get("series_index") or {}

    def rows(self):
        return list(self.snapshot.get("open_markets") or []) + list(self.snapshot.get("settled_markets") or [])

    def test_no_published_row_contradicts_its_series_record(self):
        excluded = set(self.collect.EXCLUDE_KEYWORD_SERIES)
        offenders = []
        for r in self.rows():
            series = r.get("series_ticker")
            tags = (self.series_index.get(series) or {}).get("tags") or []
            conflict = self.collect.category_conflict(r.get("category_id"), [], "keyword", tags)
            if conflict and series not in excluded:
                offenders.append((series, r.get("category_id"), tags, conflict))
        self.assertEqual(offenders, [],
                         "published rows whose own official tags contradict their topic: %r" % (offenders[:5],))

    def test_every_known_offender_is_named_by_the_exclusion_list(self):
        """The rows that are still published must be ones the collector is about to remove."""
        excluded = set(self.collect.EXCLUDE_KEYWORD_SERIES)
        for r in self.rows():
            series = r.get("series_ticker")
            tags = (self.series_index.get(series) or {}).get("tags") or []
            conflict = self.collect.category_conflict(r.get("category_id"), [], "keyword", tags)
            if conflict:
                self.assertIn(series, excluded,
                              f"{series} contradicts {r.get('category_id')} but is not excluded")

    def test_the_snapshot_publishes_the_exclusion_reasons(self):
        reasons = self.snapshot.get("counts", {}).get("excluded_series_reasons") or {}
        self.assertIn("KXNATGAS15M", reasons)
        # The new exclusion appears with the next collector pass, which is the only writer
        # of data/live; until then the snapshot carries the previous pass's list.
        if "KXNATGASD" in reasons:
            self.assertIn("/series/KXNATGASD", reasons["KXNATGASD"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
