#!/usr/bin/env python3
"""Tests for the live alert feed (data/live/alerts.json).

The feed is produced by scripts/build_alerts.py from the committed snapshots.
These tests run with no network and no credentials: they validate the committed
feed's shape and honesty, and prove the swing rule itself on synthetic data.

Rule under test (mirrors scripts/build_alerts.py and data/alert_rules.json):
  * an alert is a consecutive pair of last-traded-price observations for one
    market whose absolute change is >= $0.10, in either direction;
  * cause_link is null on every alert (no official cause source is collected);
  * the high_roi feed is a subset of the all_events feed.

Run: python3 scripts/tests/test_alerts.py
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "data" / "live"
EPS = 1e-9


def fires(delta: float, threshold: float = 0.10) -> bool:
    return abs(delta) + EPS >= threshold


class SwingRuleTests(unittest.TestCase):
    def test_exactly_at_threshold_fires(self):
        self.assertTrue(fires(0.10))

    def test_just_below_threshold_does_not_fire(self):
        self.assertFalse(fires(0.0999))

    def test_both_directions_fire(self):
        self.assertTrue(fires(0.10))
        self.assertTrue(fires(-0.10))

    def test_floating_point_boundary(self):
        # 0.30 - 0.20 == 0.0999... in float; the rule must still fire.
        self.assertTrue(fires(0.30 - 0.20))


class FeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (LIVE / "alerts.json").exists():
            raise unittest.SkipTest("no committed alerts.json to test against")
        cls.feed = json.loads((LIVE / "alerts.json").read_text())
        markets = json.loads((LIVE / "markets.json").read_text())
        cls.tickers = {r["ticker"] for r in markets["open_markets"] + markets["settled_markets"]}
        hist_path = LIVE / "price_history.json"
        cls.history_tickers = set()
        if hist_path.exists():
            cls.history_tickers = set(json.loads(hist_path.read_text()).get("series") or {})

    def test_schema_and_threshold(self):
        self.assertEqual(self.feed.get("schema"), 1)
        self.assertAlmostEqual(float(self.feed.get("threshold_dollars")), 0.10)

    def test_has_both_feeds(self):
        self.assertIsInstance(self.feed.get("all_events"), list)
        self.assertIsInstance(self.feed.get("high_roi"), list)

    def test_every_alert_meets_threshold(self):
        for a in self.feed["all_events"]:
            self.assertGreaterEqual(abs(float(a["delta"])), 0.10 - EPS,
                                    f"{a.get('ticker')} delta {a.get('delta')} below threshold")

    def test_direction_values(self):
        for a in self.feed["all_events"]:
            self.assertIn(a["direction"], ("up", "down"))

    def test_cause_is_blank_and_flagged(self):
        for a in self.feed["all_events"]:
            self.assertIsNone(a.get("cause_link"), f"{a.get('ticker')} cause_link must be null")
            self.assertIn("unverified", str(a.get("cause_status", "")))

    def test_every_alert_has_verifiable_market_source(self):
        for a in self.feed["all_events"]:
            self.assertTrue(str(a.get("market_source", "")).startswith("https://"))
            self.assertIn("/markets/", a["market_source"])

    def test_alerts_reference_real_tickers(self):
        """Every alert must reference a real market — but "real" must respect the
        archive's documented design (T12, request R-1): the archive exists precisely
        so an alert survives its market leaving the collector's snapshot, and
        validate_alerts counts those as "archive-only". Requiring the ticker to sit
        in the CURRENT snapshot contradicted that design and made the scheduled
        collector fail on main once an hourly market (KXDEMOFUTHOURLY-*) rotated
        out — runs 44799627492 / 44800299801 / 44800908243; found and fixed by
        session arena-da07bb44 (T19, COORDINATION.md).

        The invariant now, per alert in all_events:
          1. it must be an exact archive entry (ticker, from_time, to_time) —
             nothing may appear in the feed that the detector did not record;
          2. if its ticker is still in the snapshot, the alert's own market_source
             must point at that ticker (no misattributed source);
          3. if its ticker is gone from the snapshot, it is counted as an
             archive-only survivor — visible, not silently waved through.
        """
        archive_path = LIVE / "alerts_archive.json"
        if not archive_path.exists():
            self.skipTest("no committed alerts_archive.json to check against")
        archive_keys = {
            (a["ticker"], a["from_time"], a["to_time"])
            for a in json.loads(archive_path.read_text()).get("alerts", [])
        }
        archive_only = 0
        for a in self.feed["all_events"]:
            key = (a["ticker"], a["from_time"], a["to_time"])
            self.assertIn(key, archive_keys,
                          f"{a.get('ticker')}@{a.get('to_time')} is not an archived detection")
            if a["ticker"] in self.tickers:
                self.assertIn(a["ticker"], a["market_source"],
                              f"{a['ticker']} market_source does not name the market")
            else:
                archive_only += 1
        if archive_only:
            print(f"note: {archive_only} archive-only alert(s) whose market has left the "
                  "snapshot — allowed by design (T12), counted by validate_alerts.py")

    def test_high_roi_is_subset_of_all_events(self):
        all_keys = {(a["ticker"], a["to_time"]) for a in self.feed["all_events"]}
        for a in self.feed["high_roi"]:
            self.assertIn((a["ticker"], a["to_time"]), all_keys)

    def test_disclaimers_present(self):
        self.assertTrue(self.feed.get("disclaimers"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
