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


class HighRoiFreezeTests(unittest.TestCase):
    """`high_roi` is a DETECTION-TIME decision and must not be re-judged against a later snapshot.

    This pins the defect that red-lined the collector on every run after 2026-11-20T19:35Z:
    validate_alerts.py re-derived the screen from the CURRENT markets.json, while build_alerts.py
    decides the flag from the snapshot at detection time and the archive is append-only. Since
    volume_24h_fp changes between collections, one archived market crossing the "> 0" boundary
    (KXBTCY-27JAN0100-B47500, stored with volume_24h_fp 0.0 and high_roi false, later traded)
    made the collector refuse to commit its own snapshot — a permanent block on freshness, i.e.
    on the live behaviour the whole site is for (see F-34).

    The replacement check is stricter in one direction and correct in the other: a flag must
    match the inputs recorded WITH the alert (so an alert whose market has since left the snapshot
    is now verified too, where before it was skipped), while disagreement with the current
    snapshot is reported as drift, never as a failure.
    """

    TICKER = "KXBTCY-27JAN0100-B47500"

    def _run(self, mutate):
        import contextlib
        import io
        import shutil
        import sys
        import tempfile
        from pathlib import Path as _P
        sys.path.insert(0, str(ROOT / "scripts" / "tests"))
        import validate_alerts as VA

        tmp = _P(tempfile.mkdtemp(prefix="kdalerts"))
        for name in ("markets.json", "alerts.json", "alerts_archive.json", "price_history.json"):
            src = LIVE / name
            if src.exists():
                shutil.copy(src, tmp / name)
        if not (tmp / "alerts_archive.json").exists():
            self.skipTest("no committed alert archive to mutate")
        VA_LIVE, VA_RULES = VA.LIVE, VA.RULES
        VA.LIVE, VA.RULES = tmp, ROOT / "data" / "alert_rules.json"
        try:
            mutate(tmp)
            VA.errors.clear()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = VA.main()
            return rc, buf.getvalue(), list(VA.errors)
        finally:
            VA.LIVE, VA.RULES = VA_LIVE, VA_RULES

    def _entry(self, doc):
        rows = doc["alerts"] if isinstance(doc, dict) else doc
        return next(r for r in rows if r.get("ticker") == self.TICKER)

    def test_drift_against_the_current_snapshot_is_allowed_and_reported(self):
        def mutate(tmp):
            mk = tmp / "markets.json"
            d = json.loads(mk.read_text())
            for m in d.get("open_markets") or []:
                if m["ticker"] == self.TICKER:
                    m["volume_24h_fp"] = 8030.00   # the market started trading after the alert was frozen
            mk.write_text(json.dumps(d))
        rc, out, errs = self._run(mutate)
        self.assertTrue(any("differs in the CURRENT snapshot" in line for line in out.splitlines()),
                        f"drift must be reported as a note, got: {out[:400]}")
        self.assertEqual(rc, 0, f"snapshot drift must not fail the collector: {errs[:3]}")

    def test_a_flag_contradicting_its_own_stored_inputs_is_rejected(self):
        def mutate(tmp):
            # Archive first: flip the flag while leaving the recorded inputs at "not high-ROI".
            fa = tmp / "alerts_archive.json"
            da = json.loads(fa.read_text())
            arows = da["alerts"] if isinstance(da, dict) else da
            flipped = []
            for r in arows:
                if r.get("ticker") == self.TICKER:
                    r["high_roi"] = True
                    r["volume_24h_fp"] = 0.0
                    r["category_basis"] = "seed"
                    flipped.append(r)
            fa.write_text(json.dumps(da))
            # Then keep the rendered feeds byte-consistent with the archive, so the ONLY failing
            # check is the flag-vs-its-own-inputs one (check 4 compares feeds to the archive).
            ff = tmp / "alerts.json"
            df = json.loads(ff.read_text())
            frows = df["all_events"]
            for r in frows:
                if r.get("ticker") == self.TICKER:
                    r["high_roi"] = True
                    r["volume_24h_fp"] = 0.0
                    r["category_basis"] = "seed"
            df["all_events"] = frows
            df["high_roi"] = [r for r in frows if r.get("high_roi")][: len(df.get("high_roi") or []) or 300]
            counts = df.setdefault("counts", {})
            counts["all_events"] = len(df["all_events"])
            counts["high_roi"] = len(df["high_roi"])
            ff.write_text(json.dumps(df))
            self.assertTrue(flipped, f"{self.TICKER} is not in the committed archive — the fixture moved")
        rc, out, errs = self._run(mutate)
        self.assertEqual(rc, 1, "a high_roi flag that contradicts its own recorded inputs must fail the build")
        self.assertTrue(any("contradicts the inputs stored with it" in e for e in errs),
                        f"the failure must name the contradiction, got: {errs[:3]}")

    def test_the_stored_inputs_are_present_on_every_entry(self):
        # The check above only works because the writer records what it saw; if a future writer
        # drops these fields the validator would silently compare None against None.
        d = json.loads((LIVE / "alerts_archive.json").read_text())
        rows = d["alerts"] if isinstance(d, dict) else d
        self.assertTrue(rows, "the archive must not be empty")
        missing = [r.get("ticker") for r in rows if "volume_24h_fp" not in r or "category_basis" not in r]
        self.assertFalse(missing, f"alerts without the inputs the screen used: {missing[:5]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
