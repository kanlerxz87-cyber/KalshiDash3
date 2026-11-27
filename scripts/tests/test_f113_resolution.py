#!/usr/bin/env python3
"""Pin F-113's lifecycle closure to an official demo market record and the collector output.

This is an offline regression: the observation fixture is a verbatim, date-labelled
transcription from Kalshi's official demo Get Market response, and the collected sidecar
must preserve its ticker-specific source and finalized YES/NO result.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TICKER = "KXPGATOUR-THRC26-BHAR"
BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
SOURCE = f"{BASE}/markets/{TICKER}"


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class F113ResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observation = read_json("data/audit/f113_resolution_observation.json")
        cls.expected = cls.observation["market"]
        cls.markets = read_json("data/live/markets.json")
        cls.archive = read_json("data/live/alerts_archive.json")["alerts"]
        cls.finding = next(
            row for row in read_json("data/findings.json")["flagged"]
            if row.get("id") == "F-113"
        )

    def test_observation_uses_exact_official_demo_market_and_documents_its_basis(self):
        self.assertEqual(self.observation["source"], SOURCE)
        self.assertEqual(self.expected["ticker"], TICKER)
        self.assertEqual(self.observation["verified_date_utc"], "2026-11-27")
        self.assertIn("https://docs.kalshi.com/api-reference/market/get-market",
                      self.observation["documentation_sources"])
        self.assertIn("https://docs.kalshi.com/getting_started/market_lifecycle",
                      self.observation["documentation_sources"])

    def test_archived_alert_is_followed_outside_ranked_market_rows(self):
        alert = next((row for row in self.archive if row.get("ticker") == TICKER), None)
        self.assertIsNotNone(alert, "the alert archive must retain the reviewed golf contract")
        self.assertEqual(alert.get("category_id"), "golf")
        self.assertEqual(alert.get("market_source"), SOURCE)
        self.assertEqual(alert.get("event_ticker"), self.expected["event_ticker"])
        self.assertEqual(alert.get("title"), self.expected["title"])
        self.assertGreaterEqual(abs(float(alert.get("delta", 0))), 0.10)
        ranked = self.markets["open_markets"] + self.markets["settled_markets"]
        self.assertNotIn(TICKER, {row.get("ticker") for row in ranked},
                         "fixture must cover the out-of-window lifecycle path")

    def test_collector_sidecar_matches_the_official_finalized_no_record(self):
        rows = self.markets.get("alert_lifecycle", {}).get("rows", [])
        followed = next((row for row in rows if row.get("ticker") == TICKER), None)
        self.assertIsNotNone(followed, "F-113 ticker must be present in alert_lifecycle")
        self.assertEqual(followed.get("source"), SOURCE)
        for field in ("ticker", "status", "result", "settlement_ts", "settlement_value_dollars"):
            with self.subTest(field=field):
                self.assertEqual(followed.get(field), self.expected.get(field))
        self.assertTrue(followed.get("observed_at"), "the sidecar must say when Kalshi was read")
        self.assertIsNone(followed.get("reason"), "a verified finalized result is not an unknown lookup")

    def test_flagged_record_closes_the_stale_claim_without_overpromising(self):
        action = self.finding.get("action", "")
        self.assertRegex(action, r"(?i)resolved|closed")
        self.assertIn(TICKER, action)
        self.assertIn("alert_lifecycle", action)
        self.assertIn(SOURCE, self.finding.get("sources", []))
        self.assertNotIn("Keep this item open", action)
        self.assertIn("newly detected alerts", action.lower(),
                      "disclose that the collector follows a new swing on its next pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
