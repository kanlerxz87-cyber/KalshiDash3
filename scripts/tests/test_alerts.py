#!/usr/bin/env python3
"""Tests for the live alert feed (data/live/alerts.json).

The feed is produced by scripts/build_alerts.py from the committed snapshots.
These tests run with no network and no credentials: they validate the committed
feed's shape and honesty, and prove the swing rule itself on synthetic data.

Rule under test (mirrors scripts/build_alerts.py and data/alert_rules.json):
  * an alert is a consecutive pair of last-traded-price observations for one
    market whose absolute change is >= $0.10, in either direction;
  * cause_link is null on every alert (no official cause source is collected);
  * the high_roi feed is a subset of the all_events feed;
  * high_roi is frozen at detection time and is verified against the inputs stored with
    each alert, never against a later snapshot (HighRoiFreezeTests).

Run: python3 scripts/tests/test_alerts.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "data" / "live"
sys.path.insert(0, str(ROOT / "scripts"))
import build_alerts  # noqa: E402
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


class CategoryIntegrityTests(unittest.TestCase):
    """F-65: an archived swing whose series is officially a Test/demo instrument, or officially
    filed under a category the topic cannot contain, must not be served in the live chats.

    The bug this pins, found on the deployed site 2026-11-21: KXDEMOFUTHOURLY is officially
    `categories: ["Test"]` (GET /trade-api/v2/series/KXDEMOFUTHOURLY) yet 8 of the 23 archived
    >= $0.10 swings were that series, shown inside Crypto. The first version of the guard that
    was written here read the snapshot's open_markets — which is backwards, because the
    collector DROPS the conflicting row, so a row-membership check would have kept exactly the
    alerts it was meant to remove. The guard therefore reads the published series_index ledger.
    """

    TICKER = "KXDEMOFUTHOURLY-26NOV21H16-UP"

    def _run(self, ledger_categories, category_id="crypto"):
        snap = {
            "collected_at": "2026-11-21T15:21:23Z",
            "base_url": "https://external-api.demo.kalshi.co/trade-api/v2",
            # The conflicting row is NOT in open_markets: that is what the fixed collector does.
            "open_markets": [],
            "series_index": {
                "KXDEMOFUTHOURLY": {
                    "categories": ledger_categories,
                    "title": "Demo hourly event contract futures",
                    "source": "https://external-api.demo.kalshi.co/trade-api/v2/series/KXDEMOFUTHOURLY",
                }
            },
        }
        hist = {"series": {self.TICKER: {"observations": [
            {"t": "2026-11-21T15:16:38Z", "last": 0.65},
            {"t": "2026-11-21T15:21:23Z", "last": 0.45},
        ]}}}
        archive = {"schema": 1, "alerts": [{
            "ticker": self.TICKER, "event_ticker": "KXDEMOFUTHOURLY-26NOV21H16",
            "title": "Demo BTC at or above 60237.37 USD", "category_id": category_id,
            "category_basis": "keyword" if category_id else None, "status": "active" if category_id else None,
            "from_time": "2026-11-21T15:16:38Z", "to_time": "2026-11-21T15:21:23Z",
            "from_price": 0.65, "to_price": 0.45, "delta": -0.2, "direction": "down",
            "volume_24h_fp": 2236.0, "market_source": "https://external-api.demo.kalshi.co/trade-api/v2/markets/" + self.TICKER,
            "to_yes_bid": 0.01, "to_yes_ask": 1.0,
            "cause_link": None, "cause_status": "unverified: no official cause source collected",
            "first_seen_at": "2026-11-21T15:21:23Z", "high_roi": False,
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_live = Path(tmp)
            mf, hf = tmp_live / "markets.json", tmp_live / "price_history.json"
            af = tmp_live / "alerts_archive.json"
            mf.write_text(json.dumps(snap), encoding="utf-8")
            hf.write_text(json.dumps(hist), encoding="utf-8")
            af.write_text(json.dumps(archive), encoding="utf-8")
            with mock.patch.object(build_alerts, "LIVE", tmp_live), \
                 mock.patch.object(sys, "argv", ["build_alerts.py", "--markets", str(mf), "--history", str(hf)]):
                self.assertEqual(build_alerts.main(), 0)
            return json.loads((tmp_live / "alerts.json").read_text()), \
                json.loads(af.read_text())

    def test_test_series_alert_is_withheld_from_both_feeds(self):
        feed, archive = self._run(["Test"])
        self.assertEqual(feed["all_events"], [], "a Test-series swing must not be served")
        self.assertEqual(feed["high_roi"], [])
        # F-76: a Test/Demo series is out of scope by the exchange's own record, so it is counted
        # under withheld_out_of_scope (the category-conflict counter is for topic contradictions).
        self.assertEqual(feed["counts"]["withheld_category_conflict"], 0)
        self.assertEqual(feed["counts"]["withheld_out_of_scope"], 1)
        self.assertEqual(feed["counts"]["archive_total"], 1,
                         "history is never rewritten: the alert stays in the archive")
        self.assertEqual(len(archive["alerts"]), 1)

    def test_unassigned_test_series_candle_alert_is_withheld(self):
        # F-76: F-72 candle backfill creates archive rows with category_id=None for closed
        # tickers. Official ["Test"] categories still have zero overlap with the five project
        # topics and must be withheld as out of scope rather than slipping past the guard.
        feed, archive = self._run(["Test"], category_id=None)
        self.assertEqual(feed["all_events"], [], "an unassigned Test-series swing must not be served")
        self.assertEqual(feed["high_roi"], [])
        self.assertEqual(feed["counts"]["withheld_out_of_scope"], 1)
        self.assertEqual(feed["counts"]["withheld_category_conflict"], 0)
        self.assertEqual(len(archive["alerts"]), 1)

    def test_unassigned_in_scope_series_candle_alert_is_served(self):
        feed, _ = self._run(["Crypto"], category_id=None)
        self.assertEqual(len(feed["all_events"]), 1,
                         "an unassigned row whose official series is in-scope stays served")
        self.assertEqual(feed["counts"]["withheld_category_conflict"], 0)

    def test_compatible_series_alert_is_served(self):
        feed, _ = self._run(["Crypto"])
        self.assertEqual(len(feed["all_events"]), 1)
        self.assertEqual(feed["counts"]["withheld_category_conflict"], 0)

    def test_unknown_categories_are_not_a_contradiction(self):
        feed, _ = self._run(None)
        self.assertEqual(len(feed["all_events"]), 1,
                         "a null categories answer is unknown and must not withhold an alert")
        self.assertEqual(feed["counts"]["withheld_category_conflict"], 0)


class HighRoiFreezeTests(unittest.TestCase):
    """Regression for the 2026-11-20T19:42Z scheduled collector failure (run
    44803531445, F-39): KXBTCY-27JAN0100-B47500 swung at 19:30:14Z with
    volume_24h_fp == 0 (archived high_roi = False), then traded before the next
    collection (volume_24h_fp > 0 in the new snapshot). Because the archive is
    append-only and freezes high_roi at detection time, the validator must
    reproduce high_roi from the inputs stored on the alert itself — never by
    joining against the current markets.json."""

    def test_detected_alert_stores_screen_inputs(self):
        snap = {
            "collected_at": "2026-11-20T19:30:14Z",
            "base_url": "https://external-api.demo.kalshi.co/trade-api/v2",
            "open_markets": [{
                "ticker": "KXBTCY-27JAN0100-B47500",
                "title": "Bitcoin price range",
                "category_id": "crypto",
                "category_basis": "seed",
                "status": "open",
                "volume_24h_fp": 0.0,
                "source": "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXBTCY-27JAN0100-B47500",
            }],
        }
        hist = {
            "series": {
                "KXBTCY-27JAN0100-B47500": {
                    "observations": [
                        {"t": "2026-11-20T19:10:00Z", "last": 0.40},
                        {"t": "2026-11-20T19:30:14Z", "last": 0.55},
                    ]
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_live = Path(tmp)
            markets_file = tmp_live / "markets.json"
            hist_file = tmp_live / "price_history.json"
            markets_file.write_text(json.dumps(snap), encoding="utf-8")
            hist_file.write_text(json.dumps(hist), encoding="utf-8")

            with mock.patch.object(build_alerts, "LIVE", tmp_live), \
                 mock.patch.object(sys, "argv", ["build_alerts.py", "--markets", str(markets_file), "--history", str(hist_file)]):
                rc = build_alerts.main()
            self.assertEqual(rc, 0)
            archive = json.loads((tmp_live / "alerts_archive.json").read_text())["alerts"]
            self.assertEqual(len(archive), 1)
            alert = archive[0]
            self.assertEqual(alert["category_basis"], "seed")
            self.assertEqual(alert["volume_24h_fp"], 0.0)
            self.assertFalse(alert["high_roi"])

            # Simulate the next collection: the same market now has 24h volume > 0,
            # and a new swing is NOT added for the already-archived (from_time, to_time).
            later_snap = {
                **snap,
                "collected_at": "2026-11-20T19:42:00Z",
                "open_markets": [{
                    **snap["open_markets"][0],
                    "volume_24h_fp": 250.0,
                }],
            }
            markets_file.write_text(json.dumps(later_snap), encoding="utf-8")
            with mock.patch.object(build_alerts, "LIVE", tmp_live), \
                 mock.patch.object(sys, "argv", ["build_alerts.py", "--markets", str(markets_file), "--history", str(hist_file)]):
                rc2 = build_alerts.main()
            self.assertEqual(rc2, 0)
            merged = json.loads((tmp_live / "alerts_archive.json").read_text())["alerts"]
            feed = json.loads((tmp_live / "alerts.json").read_text())
            self.assertEqual(feed["counts"]["new_this_run"], 0)
            self.assertFalse(merged[0]["high_roi"],
                             "append-only archive freezes high_roi at detection time")
            self.assertEqual(merged[0]["volume_24h_fp"], 0.0,
                             "stored screen input stays with the archived alert so the "
                             "frozen flag remains reproducible even after the snapshot moves on")

    def test_every_archived_alert_matches_its_own_stored_inputs(self):
        archive_path = LIVE / "alerts_archive.json"
        rules_path = ROOT / "data" / "alert_rules.json"
        if not archive_path.exists() or not rules_path.exists():
            self.skipTest("no committed archive/rules")
        archive = json.loads(archive_path.read_text()).get("alerts", [])
        roi_rules = (json.loads(rules_path.read_text()).get("high_roi") or {})
        req_basis = roi_rules.get("require_category_basis")
        req_gt = roi_rules.get("require_volume_24h_gt", -1)
        for a in archive:
            if "category_basis" in a and "volume_24h_fp" in a:
                expected = bool(a["category_basis"] == req_basis
                                and (a["volume_24h_fp"] or 0) > req_gt)
                self.assertEqual(a.get("high_roi"), expected,
                                 f"{a.get('ticker')}@{a.get('to_time')} contradicts its stored inputs")


class AssignmentProvenanceTests(unittest.TestCase):
    """F-107: a restored topic (category_assigned_from) is verified against the official
    reading it was assigned FROM — the row's own recorded series_categories — not against a
    snapshot ledger that legitimately shrinks as markets expire.

    The bug this pins, read from the cancelled collector job's check-run annotations
    (job 140572462930, 2026-11-27): six consecutive passes failed validate_alerts with
    `archive:KXAAAGASD-26NOV21-3.6600@2026-11-20T22:41:00Z assigned topic 'gas' but GET /series
    categories [] accept []`. collect.py rebuilds series_index each pass from the series in
    that pass's scan; when KXAAAGASD's last open market left the 25k newest-first window the
    ledger entry vanished, but the Nov-20 archive row permanently carries ["Economics"] from
    GET /series/KXAAAGASD. build_alerts.py assigns row-first; the validator must check the same
    way (the F-39 precedent: stored inputs are authoritative, the snapshot rolls).
    """

    BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
    TICKER = "KXAAAGASD-26NOV21-3.6600"
    SERIES = "KXAAAGASD"
    FROM_T = "2026-11-20T22:04:00Z"
    TO_T = "2026-11-20T22:41:00Z"
    GAS_COMPATIBLE = {"Economics", "Commodities", "Financials"}

    def _alert(self, row_categories, category_id="gas", assigned=True):
        a = {
            "ticker": self.TICKER, "event_ticker": "KXAAAGASD-26NOV21",
            "title": "US gas price up", "category_id": category_id,
            "category_basis": "official-series",
            "series_categories_source": self.BASE + "/series/" + self.SERIES,
            "status": "active",
            "from_time": self.FROM_T, "to_time": self.TO_T,
            "from_price": 0.65, "to_price": 0.45, "delta": -0.2, "direction": "down",
            "volume_24h_fp": 0.0,
            "market_source": self.BASE + "/markets/" + self.TICKER,
            "to_yes_bid": 0.44, "to_yes_ask": 0.46,
            "cause_link": None, "cause_status": "unverified: no official cause source collected",
            "first_seen_at": self.TO_T, "high_roi": False,
            "evidence": {
                "state": "quote_only", "contracts_traded": 0.0,
                "est_dollars": 0.0, "est_dollars_is_an_estimate": True,
                "volume_from": 100.0, "volume_to": 100.0,
                "policy_floor_contracts": 100.0, "policy_floor_is_a_kalshi_field": False,
                "why": "no contracts traded between the two observations",
                "sources": [self.BASE + "/markets/" + self.TICKER], "decided_at": self.TO_T,
            },
        }
        if row_categories is not None:
            a["series_categories"] = list(row_categories)
        if assigned:
            a["category_assigned_from"] = "GET /series categories (series_categories)"
        return a

    def _run_validator(self, row_categories, ledger_categories, category_id="gas", assigned=True):
        """Write a complete, otherwise-valid pipeline state into a temp dir and run a FRESH
        validate_alerts module against it. ledger_categories=None means the series has left
        series_index entirely (the market expired and rolled out of the scan window)."""
        alert = self._alert(row_categories, category_id, assigned)
        snap = {
            "collected_at": "2026-11-27T19:00:00Z", "base_url": self.BASE,
            "open_markets": [], "settled_markets": [],
            "series_index": ({} if ledger_categories is None else {
                self.SERIES: {"categories": list(ledger_categories), "title": "US gas price up",
                              "source": self.BASE + "/series/" + self.SERIES}}),
        }
        hist = {"series": {self.TICKER: {"observations": [
            {"t": self.FROM_T, "last": 0.65, "volume_fp": 100.0, "source": "rest"},
            {"t": self.TO_T, "last": 0.45, "volume_fp": 100.0, "source": "rest"},
        ]}}}
        rules = {"swing_threshold_dollars": 0.10,
                 "high_roi": {"require_category_basis": "official-series", "require_volume_24h_gt": 0},
                 "evidence": {"floor_contracts": 100.0}}
        # The serving rule for this single gas alert, mirroring build_alerts.publishable /
        # validate_alerts._served: unknown categories are served; known categories that exclude
        # the topic are withheld as a category conflict.
        cats = list(ledger_categories or [])
        served = (not cats) or any(c in self.GAS_COMPATIBLE for c in cats)
        ev = {s: 0 for s in ("traded_ge_floor", "traded_below_floor", "quote_only",
                             "counter_reset", "candle_unquantified", "unknown_no_observations")}
        if served:
            ev["quote_only"] = 1
        feed = {
            "schema": 1, "generated_at": "2026-11-27T19:00:00Z", "threshold_dollars": 0.10,
            "all_events": [alert] if served else [], "high_roi": [],
            "counts": {"all_events": 1 if served else 0, "high_roi": 0, "archive_total": 1,
                       "withheld_category_conflict": 0 if served else 1, "withheld_out_of_scope": 0,
                       "evidence": ev},
            "disclaimers": ["Kalshi DEMO environment (mock funds)."],
        }
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp)
            (live / "markets.json").write_text(json.dumps(snap), encoding="utf-8")
            (live / "price_history.json").write_text(json.dumps(hist), encoding="utf-8")
            (live / "alerts_archive.json").write_text(json.dumps({"schema": 1, "alerts": [alert]}), encoding="utf-8")
            (live / "alerts.json").write_text(json.dumps(feed), encoding="utf-8")
            rules_file = live / "alert_rules.json"
            rules_file.write_text(json.dumps(rules), encoding="utf-8")
            spec = importlib.util.spec_from_file_location(
                "validate_alerts_under_test", ROOT / "scripts" / "tests" / "validate_alerts.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            with mock.patch.object(mod, "LIVE", live), mock.patch.object(mod, "RULES", rules_file):
                rc = mod.main()
            return rc, list(mod.errors)

    def test_assignment_survives_series_leaving_the_ledger(self):
        # THE regression: row carries its official ["Economics"]; the series is gone from the
        # current snapshot. Before the fix this returned 1 with "categories [] accept []".
        rc, errors = self._run_validator(row_categories=["Economics"], ledger_categories=None)
        self.assertEqual(rc, 0, f"a frozen official assignment must survive the ledger shrinking: {errors}")

    def test_contradicted_row_categories_still_fail(self):
        rc, errors = self._run_validator(row_categories=["Crypto"], ledger_categories=None)
        self.assertEqual(rc, 1, "a row whose own official categories contradict its topic must still fail")
        self.assertTrue(any("accept ['crypto']" in e for e in errors), errors)

    def test_ambiguous_row_categories_still_fail(self):
        rc, errors = self._run_validator(row_categories=["Financials"], ledger_categories=None)
        self.assertEqual(rc, 1, "an ambiguous assignment (Financials accepts gas AND crypto) must fail")
        self.assertTrue(any("accept ['crypto', 'gas']" in e for e in errors), errors)

    def test_legacy_row_falls_back_to_the_snapshot(self):
        rc, errors = self._run_validator(row_categories=None, ledger_categories=["Economics"])
        self.assertEqual(rc, 0, f"a legacy row with no stored categories uses the snapshot: {errors}")

    def test_no_official_reading_anywhere_is_unknown_not_contradiction(self):
        rc, errors = self._run_validator(row_categories=None, ledger_categories=None)
        self.assertEqual(rc, 0, f"unknown is not a contradiction: {errors}")

    def test_reclassified_series_is_still_withheld_from_the_feeds(self):
        # Row-first keeps the frozen assignment valid, but the LIVE serving check reads the
        # current snapshot: a series Kalshi refiles under Crypto must leave the gas chats.
        rc, errors = self._run_validator(row_categories=["Economics"], ledger_categories=["Crypto"])
        self.assertEqual(rc, 0, f"reclassification withholds from feeds without failing the build: {errors}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
