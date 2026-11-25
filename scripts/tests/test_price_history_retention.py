#!/usr/bin/env python3
"""The price-history retention window must not delete the observations an alert cites (F-99).

Why this suite exists
  `scripts/collect.py` keeps at most PRICE_HISTORY_LIMIT observations per ticker so the
  committed file stays small. That cap is a limit on a SERIES, but it was silently deleting
  the two observations that BOUND an archived swing: once a market's series grew past the
  cap, the swing could no longer be read back from the repository. Measured on the
  2026-11-25T13:16:43Z snapshot: 62 of the 150 archived swings had lost BOTH bounds, which is
  why the evidence layer reported "unknown_no_observations" for 52 of the 130 swings the page
  serves, and why the chart for those tickers no longer contains the swing the alert points at.

  The archive (`data/live/alerts_archive.json`, written by scripts/build_alerts.py) is the
  authority on which observations matter: each entry names the two observations that bounded
  it. They are now pinned: kept in addition to the window, in time order.

What is asserted
  1. Without pins the window behaves exactly as before (the newest PRICE_HISTORY_LIMIT).
  2. A pinned observation survives the cap; an unpinned one still does not.
  3. The kept series stays sorted by time, so the chart is not reordered.
  4. `pinned_alert_times` reads from_time and to_time from an archive file, and returns
     nothing (never a guess) when the file is missing or unreadable.
  5. `update_price_history` keeps the pin through a real append.

Run: python3 scripts/tests/test_price_history_retention.py     (exit 0 pass, 1 fail)
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_collect():
    spec = importlib.util.spec_from_file_location("collect_under_test", ROOT / "scripts" / "collect.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def obs(i: int) -> dict:
    from datetime import datetime, timedelta, timezone
    t = datetime(2026, 11, 25, tzinfo=timezone.utc) + timedelta(minutes=i)
    return {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "last": 0.5, "yes_bid": 0.4, "yes_ask": 0.6,
            "volume_fp": "10"}


class RetentionWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collect = load_collect()
        cls.limit = cls.collect.PRICE_HISTORY_LIMIT

    def test_without_pins_the_window_is_unchanged(self):
        series = [obs(i) for i in range(self.limit + 25)]
        kept = self.collect.keep_observations(series, None)
        self.assertEqual(len(kept), self.limit)
        self.assertEqual(kept[-1], series[-1])
        self.assertEqual(kept[0], series[-self.limit])

    def test_a_pinned_observation_survives_the_cap(self):
        series = [obs(i) for i in range(self.limit + 10)]
        pin = {series[0]["t"]}
        kept = self.collect.keep_observations(series, pin)
        stamps = [o["t"] for o in kept]
        self.assertIn(series[0]["t"], stamps, "the observation an alert cites must survive")
        self.assertEqual(len(stamps), self.limit + 1)

    def test_an_unpinned_observation_is_still_dropped(self):
        series = [obs(i) for i in range(self.limit + 10)]
        kept = self.collect.keep_observations(series, {series[0]["t"]})
        stamps = [o["t"] for o in kept]
        self.assertNotIn(series[5]["t"], stamps,
                         "an observation nothing cites must still fall out of the window")

    def test_the_kept_series_stays_in_time_order(self):
        series = [obs(i) for i in range(self.limit + 10)]
        kept = self.collect.keep_observations(series, {series[0]["t"], series[3]["t"]})
        stamps = [o["t"] for o in kept]
        self.assertEqual(stamps, sorted(stamps), "the chart reads this series in time order")

    def test_update_price_history_keeps_the_pin(self):
        hist = {"T-1": {"observations": [obs(i) for i in range(self.limit + 5)]}}
        pinned = {"T-1": {hist["T-1"]["observations"][0]["t"]}}
        rows = [{"ticker": "T-1", "last_price_dollars": "0.50", "yes_bid_dollars": "0.40",
                 "yes_ask_dollars": "0.60", "volume_fp": "10"}]
        self.collect.update_price_history(hist, rows, pinned)
        stamps = [o["t"] for o in hist["T-1"]["observations"]]
        self.assertIn(hist["T-1"]["observations"][0]["t"], stamps,
                      "the observation an alert cites must survive an append")
        self.assertEqual(stamps, sorted(stamps))


class PinnedAlertTimesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collect = load_collect()

    def write_archive(self, payload: str) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="kalshi-archive-"))
        path = tmp / "alerts_archive.json"
        path.write_text(payload)
        return path

    def test_both_bounds_of_every_alert_are_pinned(self):
        path = self.write_archive(json.dumps({"alerts": [
            {"ticker": "T-1", "from_time": "2026-11-25T01:00:00Z", "to_time": "2026-11-25T02:00:00Z"},
            {"ticker": "T-2", "from_time": "2026-11-25T03:00:00Z", "to_time": "2026-11-25T04:00:00Z"},
        ]}))
        pins = self.collect.pinned_alert_times(path)
        self.assertEqual(pins["T-1"], {"2026-11-25T01:00:00Z", "2026-11-25T02:00:00Z"})
        self.assertEqual(pins["T-2"], {"2026-11-25T03:00:00Z", "2026-11-25T04:00:00Z"})

    def test_a_missing_or_unreadable_archive_pins_nothing(self):
        missing = Path(tempfile.mkdtemp(prefix="kalshi-archive-")) / "nope.json"
        self.assertEqual(self.collect.pinned_alert_times(missing), {},
                         "an absent archive must never be turned into a guess")
        broken = self.write_archive("{not json")
        self.assertEqual(self.collect.pinned_alert_times(broken), {})

    def test_the_committed_archive_is_pinned_by_the_real_file(self):
        pins = self.collect.pinned_alert_times()
        self.assertTrue(pins, "the committed archive must yield pins")
        archive = json.loads((ROOT / "data" / "live" / "alerts_archive.json").read_text())
        rows = archive.get("alerts") or []
        self.assertTrue(rows)
        for row in rows[:5]:
            self.assertIn(row["from_time"], pins.get(row["ticker"], set()))
            self.assertIn(row["to_time"], pins.get(row["ticker"], set()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
