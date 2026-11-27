#!/usr/bin/env python3
"""Bounded official lookups for alerted markets after they drop out of the ranked lists."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from track_lifecycle import track
import validate_live

BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
TICKER = "KXAAAGASD-26NOV21-3.6600"
PATH = f"/markets/{TICKER}"
TIME = "2026-11-27T19:00:00Z"
MARKET = {"ticker": TICKER, "status": "finalized", "result": "no",
          "settlement_ts": "2026-11-21T13:11:17.960569Z", "settlement_value_dollars": "0.0000"}
TARGET = {"ticker": TICKER, "category_id": "gas", "series_categories": ["Economics"],
          "series_categories_source": BASE + "/series/KXAAAGASD"}


def miss(path):
    err = RuntimeError("HTTP 404")
    err.__cause__ = HTTPError(BASE + path, 404, "Not Found", None, None)
    return err


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.get = Mock()
        self.snapshot = {"base_url": BASE, "collected_at": TIME, "open_markets": [], "settled_markets": []}

    def run_track(self, *, targets=(TARGET,), prior=None, positions=(), budget=16):
        doc = track(self.snapshot, list(targets), list(positions), prior or {}, self.get, lambda: TIME, limit=budget)
        validate_live.errors.clear()
        validate_live.check_alert_lifecycle({"alert_lifecycle": doc})
        self.assertEqual(validate_live.errors, [])
        return doc

    def test_posts_ranked_result_beyond_ranked_window_without_requery(self):
        self.snapshot["settled_markets"] = [dict(MARKET, source=BASE + PATH)]
        first = self.run_track()
        self.snapshot["settled_markets"] = []
        later = self.run_track(prior=first)
        self.get.assert_not_called()
        self.assertEqual(first, later)
        self.assertEqual(first["rows"][0]["result"], "no")

    def test_confirm_outcome_in_historical_partition_only_on_live_404(self):
        historical = "/historical" + PATH
        self.get.side_effect = [miss(PATH), ({"market": MARKET}, BASE + historical)]
        doc = self.run_track()
        self.assertEqual(self.get.call_args_list, [call(PATH, retries=1), call(historical, retries=1)])
        row = doc["rows"][0]
        self.assertEqual(row["source"], BASE + historical)
        self.assertEqual((row["status"], row["result"], row["observed_at"]), ("finalized", "no", TIME))

    def test_retry_deferred_history_without_exceeding_request_budget(self):
        self.get.side_effect = [miss(PATH), ({"market": MARKET}, BASE + "/historical" + PATH)]
        first = self.run_track(budget=1)
        self.assertIsNone(first["rows"][0]["result"])
        self.assertEqual(first["rows"][0]["reason"], "historical lookup deferred")
        self.assertEqual(self.run_track(prior=first, budget=1)["rows"][0]["result"], "no")

    def test_unknown_or_wrong_ticker_stays_blank(self):
        self.get.return_value = {"market": dict(MARKET, ticker="wrong")}, BASE + PATH
        row = self.run_track()["rows"][0]
        self.assertIsNone(row["status"])
        self.assertIsNone(row["result"])
        self.assertIsNone(row["settlement_value_dollars"])
        self.assertEqual(row["source"], BASE + PATH)

    def test_outage_keeps_unknown_values_and_does_not_burst(self):
        second = dict(TARGET, ticker=TICKER + "-X")
        self.get.side_effect = RuntimeError("HTTP 429")
        rows = self.run_track(targets=(TARGET, second))["rows"]
        self.get.assert_called_once_with(PATH, retries=1)
        self.assertEqual([r["reason"] for r in rows], ["lookup unavailable", "lookup deferred"])
        self.assertTrue(all(r["status"] is None and r["result"] is None for r in rows))

    def test_current_official_category_conflict_is_not_queried(self):
        self.snapshot["series_index"] = {"KXAAAGASD": {"categories": ["Test"]}}
        self.assertEqual(self.run_track()["rows"], [])
        self.get.assert_not_called()

    def test_open_paper_position_is_followed_after_its_alert_is_trimmed(self):
        self.get.return_value = {"market": MARKET}, BASE + PATH
        self.assertEqual(self.run_track(targets=(), positions=(TARGET,))["rows"][0]["result"], "no")

    def test_nonfinal_results_are_refreshed_not_cached_as_settled(self):
        self.get.side_effect = [({"market": dict(MARKET, status="determined", result="yes")}, BASE + PATH),
                                ({"market": MARKET}, BASE + PATH)]
        first = self.run_track()
        self.assertEqual(first["rows"][0]["status"], "determined")
        self.assertEqual(self.run_track(prior=first)["rows"][0]["result"], "no")
        self.assertEqual(self.get.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
