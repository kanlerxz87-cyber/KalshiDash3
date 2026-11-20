#!/usr/bin/env python3
"""Tests for the swing-alert engine (scripts/alerts.py).

Runs with no network and no credentials. Two kinds of test:
  * synthetic cases that prove the rule and the ROI model behave as documented, and
  * a test against the real committed snapshots that proves every emitted alert
    refers to a real market and carries a verifiable source URL.

Run: python3 scripts/tests/test_alerts.py
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "data" / "live"
sys.path.insert(0, str(ROOT / "scripts"))

import alerts  # noqa: E402


def market(ticker, **kw):
    row = {"ticker": ticker, "title": f"Test {ticker}", "category_id": "crypto",
           "category_basis": "seed", "source": f"https://external-api.demo.kalshi.co/trade-api/v2/markets/{ticker}"}
    row.update(kw)
    return row


def series(*obs):
    return {"observations": [{"t": t, "last": v} for t, v in obs]}


class SwingRuleTests(unittest.TestCase):
    def test_up_move_at_threshold_fires(self):
        rows = [market("T-UP")]
        alerts_out, meta = alerts.compute_alerts(rows, [], {"T-UP": series(("t1", 0.20), ("t2", 0.30))})
        self.assertEqual(len(alerts_out), 1)
        a = alerts_out[0]
        self.assertEqual(a["direction"], "up")
        self.assertAlmostEqual(a["delta"], 0.10)
        self.assertTrue(a["high_roi"])  # 0.10 / 0.20 = 0.5 >= 0.40

    def test_down_move_at_threshold_fires(self):
        rows = [market("T-DN")]
        out, _ = alerts.compute_alerts(rows, [], {"T-DN": series(("t1", 0.80), ("t2", 0.70))})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["direction"], "down")
        self.assertAlmostEqual(out[0]["delta"], -0.10)
        # entry on the NO side = 1 - 0.80 = 0.20 -> roi 0.5
        self.assertAlmostEqual(out[0]["swing_roi"], 0.5)
        self.assertTrue(out[0]["high_roi"])

    def test_move_below_threshold_is_not_an_alert(self):
        rows = [market("T-SMALL")]
        out, _ = alerts.compute_alerts(rows, [], {"T-SMALL": series(("t1", 0.20), ("t2", 0.25))})
        self.assertEqual(out, [])

    def test_move_just_below_threshold_is_not_an_alert(self):
        rows = [market("T-EDGE")]
        out, _ = alerts.compute_alerts(rows, [], {"T-EDGE": series(("t1", 0.20), ("t2", 0.2999))})
        self.assertEqual(out, [])

    def test_roi_threshold_filters(self):
        rows = [market("T-ROI")]
        # move 0.10 on entry 0.50 -> roi 0.20, below the 0.40 default
        out, _ = alerts.compute_alerts(rows, [], {"T-ROI": series(("t1", 0.50), ("t2", 0.60))})
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0]["high_roi"])
        # same move, lower threshold -> high roi
        out2, _ = alerts.compute_alerts(rows, [], {"T-ROI": series(("t1", 0.50), ("t2", 0.60))},
                                        roi_threshold=0.15)
        self.assertTrue(out2[0]["high_roi"])

    def test_multiple_swings_all_reported_newest_first(self):
        rows = [market("T-MANY")]
        # diffs: +0.15 (fire), 0.00 (no), +0.15 (fire) -> 2 alerts, newest last
        hist = {"T-MANY": series(("t1", 0.10), ("t2", 0.25), ("t3", 0.25), ("t4", 0.40))}
        out, _ = alerts.compute_alerts(rows, [], hist)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["observed_at"], "t4")
        self.assertEqual(out[1]["observed_at"], "t2")

    def test_missing_prices_are_skipped(self):
        rows = [market("T-NAN")]
        hist = {"T-NAN": series(("t1", None), ("t2", 0.5), ("t3", 0.7))}
        out, _ = alerts.compute_alerts(rows, [], hist)
        # t2->t3 is a valid 0.20 move; t1->t2 has a null prior and is skipped
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["observed_at"], "t3")

    def test_observation_without_market_row_is_skipped(self):
        out, _ = alerts.compute_alerts([], [], {"T-ORPHAN": series(("t1", 0.1), ("t2", 0.5))})
        self.assertEqual(out, [])

    def test_event_source_url_derived_from_market_source(self):
        rows = [market("T-EV", event_ticker="EV-1")]
        out, _ = alerts.compute_alerts(rows, [], {"T-EV": series(("t1", 0.1), ("t2", 0.5))})
        self.assertEqual(
            out[0]["event_source"],
            "https://external-api.demo.kalshi.co/trade-api/v2/events/EV-1",
        )

    def test_cause_is_blank_and_flagged(self):
        rows = [market("T-CO")]
        out, _ = alerts.compute_alerts(rows, [], {"T-CO": series(("t1", 0.1), ("t2", 0.5))})
        self.assertIsNone(out[0]["cause"])
        self.assertIn("blank", out[0]["cause_flag"])


class RealSnapshotTests(unittest.TestCase):
    """Runs against the actual committed snapshots — no network."""

    @classmethod
    def setUpClass(cls):
        if not (LIVE / "markets.json").exists() or not (LIVE / "price_history.json").exists():
            raise unittest.SkipTest("no committed live snapshot to test against")
        cls.markets = json.loads((LIVE / "markets.json").read_text())
        cls.history = json.loads((LIVE / "price_history.json").read_text())
        cls.out, cls.meta = alerts.compute_alerts(
            cls.markets.get("open_markets"), cls.markets.get("settled_markets"),
            cls.history.get("series"),
        )

    def test_every_alert_refers_to_a_real_ticker(self):
        tickers = {r["ticker"] for r in self.markets["open_markets"] + self.markets["settled_markets"]}
        for a in self.out:
            self.assertIn(a["ticker"], tickers)

    def test_every_alert_carries_a_verifiable_source_url(self):
        for a in self.out:
            self.assertTrue(str(a["source"]).startswith("https://"))
            self.assertIn("/markets/", a["source"])

    def test_all_alerts_meet_the_threshold(self):
        for a in self.out:
            self.assertGreaterEqual(a["swing_cents"], 10.0)

    def test_categories_are_in_scope(self):
        allowed = {"gas", "elections", "culture", "crypto", "golf"}
        for a in self.out:
            self.assertIn(a["category_id"], allowed)

    def test_model_metadata_present(self):
        self.assertEqual(self.meta["schema"], 1)
        self.assertAlmostEqual(self.meta["swing_threshold_dollars"], 0.10)
        self.assertIn("model_note", self.meta)

    def test_alerts_sorted_newest_first(self):
        times = [a.get("observed_at") or "" for a in self.out]
        self.assertEqual(times, sorted(times, reverse=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
