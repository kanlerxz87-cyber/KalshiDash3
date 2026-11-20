#!/usr/bin/env python3
"""Unit tests for the official cause-candidate layer of scripts/build_alerts.py.

Fixtures are synthetic and live only in a temporary directory. Nothing is
written under data/, so no invented market value reaches the site.

What these tests pin down:
  * an alert only carries settlement sources that the official event reference
    actually lists, and only when that reference is present;
  * every alert states that the cause is unverified - the builder must never
    produce a "verified cause" claim;
  * the alert facts (ticker, times, prices, delta) are never rewritten when the
    cause fields are refreshed, so the archive stays append-only;
  * a cause candidate that is not an official settlement source of its event is
    rejected by the validator (scripts/tests/validate_live.py).

Official references
  Get Event ....... https://docs.kalshi.com/api-reference/events/get-event
  Get Events ...... https://docs.kalshi.com/api-reference/events/get-events

Run: python3 scripts/tests/test_alert_causes.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
BASE = "https://external-api.demo.kalshi.co/trade-api/v2"

T1 = "2026-11-20T11:30:00Z"
T2 = "2026-11-20T11:40:00Z"
TICKER = "KXDEMOFUTHOURLY-26NOV20H14-UP"
EVENT = "KXDEMOFUTHOURLY-26NOV20H14"
COINBASE = {"name": "Coinbase", "url": "https://www.coinbase.com/price"}


def build_alerts(history: Path, markets: Path, refs: Path | None, archive: Path, feed: Path) -> int:
    cmd = [
        sys.executable, str(SCRIPTS / "build_alerts.py"),
        "--history", str(history), "--markets", str(markets),
        "--archive", str(archive), "--feed", str(feed),
    ]
    if refs is not None:
        cmd += ["--event-refs", str(refs)]
    return subprocess.run(cmd, capture_output=True, text=True).returncode


class CauseCandidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.history = self.dir / "price_history.json"
        self.markets = self.dir / "markets.json"
        self.refs = self.dir / "event_refs.json"
        self.archive = self.dir / "alerts_archive.json"
        self.feed = self.dir / "alerts.json"

        self.history.write_text(json.dumps({
            "schema": 1,
            "series": {TICKER: {"observations": [
                {"t": T1, "last": 0.35, "bid": 0.34, "ask": 0.36},
                {"t": T2, "last": 0.55, "bid": 0.54, "ask": 0.56},
            ]}},
        }))
        self.markets.write_text(json.dumps({
            "schema": 1, "collected_at": T2,
            "open_markets": [{
                "ticker": TICKER, "event_ticker": EVENT, "series_ticker": "KXDEMOFUTHOURLY",
                "title": "Demo BTC at or above 61498.92 USD", "category_id": "crypto",
                "category_basis": "keyword", "status": "active", "result": "",
                "last_price_dollars": 0.55, "volume_fp": 100.0, "volume_24h_fp": 4485.0,
                "open_interest_fp": 10.0, "dollars_traded_estimate": 500.0,
                "source": f"{BASE}/markets/{TICKER}",
            }],
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def write_refs(self, sources, status="ok"):
        self.refs.write_text(json.dumps({
            "schema": 1, "generated_at": T2, "environment": "demo",
            "events": [{
                "event_ticker": EVENT, "series_ticker": "KXDEMOFUTHOURLY",
                "title": "Demo BTC at or above 61498.92 USD", "status": status,
                "settlement_sources": sources,
                "kalshi_public_url": None, "kalshi_public_http_status": None,
                "source": f"{BASE}/events?series_ticker=KXDEMOFUTHOURLY&limit=200",
                "event_source": f"{BASE}/events/{EVENT}",
            }],
            "disclaimers": ["synthetic fixture"],
        }))

    def alert(self):
        doc = json.loads(self.archive.read_text())
        self.assertEqual(len(doc["alerts"]), 1)
        return doc["alerts"][0]

    def test_candidates_come_from_the_official_event_reference(self):
        self.write_refs([COINBASE])
        self.assertEqual(build_alerts(self.history, self.markets, self.refs, self.archive, self.feed), 0)
        a = self.alert()
        self.assertEqual(a["cause_candidates"], [COINBASE])
        self.assertEqual(a["cause_link"], f"{BASE}/events/{EVENT}")
        self.assertEqual(a["cause_kind"], "official_settlement_source")
        # The label must say the cause is unverified.
        self.assertIn("unverified", a["cause_status"].lower())
        self.assertIn("not a confirmed cause", a["cause_status"].lower())

    def test_without_an_event_reference_no_cause_is_invented(self):
        self.assertEqual(build_alerts(self.history, self.markets, None, self.archive, self.feed), 0)
        a = self.alert()
        self.assertIsNone(a["cause_link"])
        self.assertEqual(a["cause_candidates"], [])
        self.assertIn("unverified", a["cause_status"].lower())

    def test_unavailable_event_reference_is_not_used(self):
        self.write_refs([COINBASE], status="unavailable")
        self.assertEqual(build_alerts(self.history, self.markets, self.refs, self.archive, self.feed), 0)
        a = self.alert()
        self.assertIsNone(a["cause_link"])
        self.assertEqual(a["cause_candidates"], [])

    def test_refresh_updates_only_the_cause_fields(self):
        self.write_refs([])
        self.assertEqual(build_alerts(self.history, self.markets, self.refs, self.archive, self.feed), 0)
        before = dict(self.alert())
        self.assertEqual(before["cause_candidates"], [])

        # A later run with a richer reference file adds the candidate but must
        # not touch the alert facts.
        self.write_refs([COINBASE])
        self.assertEqual(build_alerts(self.history, self.markets, self.refs, self.archive, self.feed), 0)
        after = self.alert()
        for field in ("ticker", "from_time", "to_time", "from_price", "to_price", "delta", "direction"):
            self.assertEqual(before[field], after[field], field)
        self.assertEqual(after["cause_candidates"], [COINBASE])
        self.assertEqual(len(json.loads(self.archive.read_text())["alerts"]), 1)

    def test_the_archive_keeps_every_alert_it_already_had(self):
        self.write_refs([COINBASE])
        self.assertEqual(build_alerts(self.history, self.markets, self.refs, self.archive, self.feed), 0)
        first = self.alert()
        # A second market that no longer moves must not remove the first alert.
        self.history.write_text(json.dumps({
            "schema": 1,
            "series": {TICKER: {"observations": [
                {"t": T1, "last": 0.35, "bid": 0.34, "ask": 0.36},
                {"t": T2, "last": 0.36, "bid": 0.35, "ask": 0.37},
            ]}},
        }))
        self.assertEqual(build_alerts(self.history, self.markets, self.refs, self.archive, self.feed), 0)
        doc = json.loads(self.archive.read_text())
        self.assertEqual(len(doc["alerts"]), 1)
        self.assertEqual(doc["alerts"][0]["ticker"], first["ticker"])

    def test_the_feed_carries_the_same_candidates(self):
        self.write_refs([COINBASE])
        self.assertEqual(build_alerts(self.history, self.markets, self.refs, self.archive, self.feed), 0)
        feed = json.loads(self.feed.read_text())
        self.assertEqual(len(feed["all_events"]), 1)
        self.assertEqual(feed["all_events"][0]["cause_candidates"], [COINBASE])
        self.assertEqual(feed["counts"]["alerts_with_cause_candidates"], 1)
        self.assertTrue(any("unverified" in d for d in feed["disclaimers"]))


class ValidatorRejectsInventedCauseTest(unittest.TestCase):
    """The validator must refuse a candidate that the event does not list."""

    def test_invented_candidate_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            live = tmpdir / "data" / "live"
            live.mkdir(parents=True)
            (live / "event_refs.json").write_text(json.dumps({
                "schema": 1, "generated_at": T2, "disclaimers": ["synthetic"],
                "events": [{
                    "event_ticker": EVENT, "status": "ok",
                    "settlement_sources": [COINBASE],
                    "source": f"{BASE}/events/{EVENT}", "event_source": f"{BASE}/events/{EVENT}",
                }],
            }))
            (live / "alerts_archive.json").write_text(json.dumps({
                "schema": 1, "alerts": [{
                    "ticker": TICKER, "event_ticker": EVENT, "from_time": T1, "to_time": T2,
                    "from_price": 0.35, "to_price": 0.55, "delta": 0.2,
                    "cause_link": f"{BASE}/events/{EVENT}",
                    "cause_status": "unverified: candidate",
                    "cause_candidates": [{"name": "Some Blog", "url": "https://example.com/news"}],
                }],
            }))
            (live / "markets.json").write_text(json.dumps({
                "schema": 1, "environment": "demo", "collected_at": T2,
                "sources": {"get_markets": f"{BASE}/markets"}, "disclaimers": ["synthetic"],
                "open_markets": [], "settled_markets": [], "liquidity": [],
            }))
            spec = importlib.util.spec_from_file_location(
                "validate_live", ROOT / "scripts" / "tests" / "validate_live.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.LIVE = live  # point the checks at the fixture, not at data/live
            mod.check_event_refs()
            mod.check_alert_causes()
            self.assertTrue(mod.errors, "an invented cause candidate must be rejected")
            self.assertTrue(any("not an official settlement source" in e for e in mod.errors), mod.errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
