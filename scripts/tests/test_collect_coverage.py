#!/usr/bin/env python3
"""Offline tests for scripts/collect.py coverage, topic-fair settlement, and alert history retention.

Covers three defects measured on main (2026-11-21):
  1. Topic starvation in settled_markets (198/200 crypto, 0 gas/elections/golf)
  2. scan_markets() omitting documented mve_filter=exclude
  3. price_history.json pruning archived-alert tickers when they leave open_markets

Run: python3 scripts/tests/test_collect_coverage.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402


class CollectCoverageTests(unittest.TestCase):
    def test_select_settled_prevents_crypto_starvation(self):
        # Reproduce the real shape: 400 recent 15m crypto rows + 5 rows in each slower topic.
        rows = []
        for i in range(400):
            rows.append({
                "ticker": f"KXBTC15M-{i:04d}",
                "category_id": "crypto",
                "settlement_ts": f"2026-11-21T{10 + (i // 60):02d}:{i % 60:02d}:00Z",
            })
        for cat in ("gas", "elections", "culture", "golf"):
            for j in range(5):
                rows.append({
                    "ticker": f"TEST-{cat.upper()}-{j}",
                    "category_id": cat,
                    "settlement_ts": f"2026-11-18T0{j}:00:00Z",
                })

        order = ["gas", "elections", "culture", "crypto", "golf"]
        chosen, by_cat = collect.select_settled(rows, cap=200, category_order=order)

        self.assertEqual(len(chosen), 200)
        self.assertEqual(len({r["ticker"] for r in chosen}), 200)
        # Every slower topic keeps ALL 5 of its rows; crypto takes exact leftover (180).
        for cat in ("gas", "elections", "culture", "golf"):
            self.assertEqual(by_cat[cat], 5, f"{cat} lost rows to crypto starvation")
        self.assertEqual(by_cat["crypto"], 180)
        # Published list remains sorted newest-first by settlement_ts.
        ts = [r["settlement_ts"] for r in chosen]
        self.assertEqual(ts, sorted(ts, reverse=True))
        # The 180 crypto rows kept are the 180 NEWEST crypto rows (indices 220..399).
        kept_crypto = {r["ticker"] for r in chosen if r["category_id"] == "crypto"}
        self.assertIn("KXBTC15M-0399", kept_crypto)
        self.assertNotIn("KXBTC15M-0000", kept_crypto)

    def test_select_settled_deduplicates_and_handles_absent_topics(self):
        rows = [
            {"ticker": "A-1", "category_id": "gas", "settlement_ts": "2026-11-20T01:00:00Z"},
            {"ticker": "A-1", "category_id": "gas", "settlement_ts": "2026-11-20T01:00:00Z"},
            {"ticker": "B-1", "category_id": "golf", "settlement_ts": "2026-11-20T02:00:00Z"},
        ]
        chosen, by_cat = collect.select_settled(
            rows, cap=10, category_order=["gas", "elections", "culture", "crypto", "golf"]
        )
        self.assertEqual([r["ticker"] for r in chosen], ["B-1", "A-1"])
        self.assertEqual(by_cat, {"gas": 1, "elections": 0, "culture": 0, "crypto": 0, "golf": 1})

    def test_scan_markets_passes_mve_filter_exclude(self):
        calls = []

        def fake_get(path, params=None, retries=3):
            calls.append((path, dict(params or {})))
            status = (params or {}).get("status")
            return ({"markets": [{"ticker": f"M-{status}-1"}], "cursor": ""}, "https://example.test/markets")

        with mock.patch.object(collect, "get", side_effect=fake_get):
            res = collect.scan_markets()

        self.assertEqual(len(calls), 2)
        for path, params in calls:
            self.assertEqual(path, "/markets")
            self.assertEqual(params.get("mve_filter"), "exclude")
            self.assertEqual(params.get("limit"), 1000)
        self.assertFalse(res["_truncated"]["open"])
        self.assertFalse(res["_truncated"]["settled"])

    def test_archived_alert_tickers_survive_history_prune(self):
        with tempfile.TemporaryDirectory() as td:
            live = Path(td)
            (live / "alerts_archive.json").write_text(json.dumps({
                "alerts": [
                    {"ticker": "KXDEMOFUTHOURLY-26NOV20H20-UP"},
                    {"ticker": "KXPGATOUR-THRC26-BHAR"},
                ]
            }))
            (live / "price_history.json").write_text(json.dumps({
                "series": {
                    "KXDEMOFUTHOURLY-26NOV20H20-UP": {"observations": [{"t": "2026-11-20T19:48:00Z", "last": 0.65}]},
                    "UNRELATED-EXPIRED": {"observations": [{"t": "2026-11-20T00:00:00Z", "last": 0.50}]},
                }
            }))

            def fake_get(path, params=None, retries=3):
                if path == "/series":
                    return {"series": []}, "https://example.test/series"
                if path == "/markets":
                    st = (params or {}).get("status")
                    if (params or {}).get("series_ticker"):
                        return {"markets": [], "cursor": ""}, "https://example.test/markets"
                    if st == "open":
                        return {
                            "markets": [{
                                "ticker": "KXAAAGASM-26NOV30-3.90",
                                "title": "US gas price above 3.90",
                                "status": "active",
                                "last_price_dollars": "0.7500",
                                "volume_fp": "100.00",
                            }],
                            "cursor": "",
                        }, "https://example.test/markets"
                    return {"markets": [], "cursor": ""}, "https://example.test/markets"
                if "/orderbook" in path:
                    return {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}, "https://example.test/ob"
                raise AssertionError(f"unexpected get({path})")

            with mock.patch.object(collect, "LIVE", live), mock.patch.object(collect, "get", side_effect=fake_get):
                collect.build(include_orderbooks=1)

            ph = json.loads((live / "price_history.json").read_text())["series"]
            self.assertIn("KXAAAGASM-26NOV30-3.90", ph)
            self.assertIn("KXDEMOFUTHOURLY-26NOV20H20-UP", ph)
            self.assertNotIn("UNRELATED-EXPIRED", ph)


if __name__ == "__main__":
    unittest.main(verbosity=2)
