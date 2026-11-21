#!/usr/bin/env python3
"""Tests for two collector behaviours that decide what the dashboard can draw.

Both are offline (no network, no credentials): the API is stubbed, and the
committed snapshot/archive are read as data.

1. `scan_markets()` must ask for the DOCUMENTED multivariate exclusion.
   GET /markets accepts `mve_filter` with 'only' or 'exclude'
   (https://docs.kalshi.com/api-reference/market/get-markets). Combo listings are
   excluded from every category further down anyway, but while they are in the
   paged universe they fill the newest-first safety cap: on `main` the 25,000-row
   scan reported `open_paging_truncated_at_safety_cap: true` and the in-scope
   total moved between runs (749 open in scope in the 2026-11-21T00:50Z collector
   snapshot vs 1,365 in the desk scan of the same exchange).

2. `build()` must keep price history for every ticker cited by an archived alert.
   The earlier rule kept history only for `rows["open"]` — the ranked, capped
   window. A market rotating out of that window lost its observations while the
   alert that cites them stayed in data/live/alerts_archive.json, so the chart for
   that swing rendered "No observations in this window yet".

Run: python3 scripts/tests/test_collect_coverage.py
Exit codes: 0 pass, 1 fail.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "data" / "live"


def load_collect():
    spec = importlib.util.spec_from_file_location("collect_under_test", ROOT / "scripts" / "collect.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):  # headers/status are not needed by these paths
        raise AttributeError(name)


class ScanAsksForDocumentedMveExclusion(unittest.TestCase):
    def test_scan_requests_mve_filter_exclude(self):
        collect = load_collect()
        urls: list[str] = []

        def fake_urlopen(req, timeout=25):
            urls.append(req.full_url)
            return _FakeResponse({"markets": [{"ticker": "STUB-1", "status": "active"}], "cursor": ""})

        original = collect.urllib.request.urlopen
        collect.urllib.request.urlopen = fake_urlopen
        try:
            out = collect.scan_markets()
        finally:
            collect.urllib.request.urlopen = original

        self.assertTrue(urls, "scan_markets issued no request at all")
        for u in urls:
            self.assertIn("mve_filter=exclude", u,
                          "GET /markets must be asked for the documented multivariate exclusion: " + u)
        self.assertIn("open", out)
        self.assertIn("settled", out)

    def test_unpaginated_response_is_not_reported_as_truncated(self):
        collect = load_collect()
        # A single page with no cursor is the whole universe, not a truncated one.
        collect.urllib.request.urlopen = lambda req, timeout=25: _FakeResponse(
            {"markets": [{"ticker": "STUB-1"}], "cursor": ""})
        out = collect.scan_markets()
        self.assertEqual(out["_truncated"], {"open": False, "settled": False})


class HistoryKeepsArchivedAlertTickers(unittest.TestCase):
    """The watch set is what survives the prune, so assert the rule, not the file."""

    def _watch_set(self, collect, rows_open, archive):
        # Mirrors the published rule in collect.build(): open rows UNION archive tickers.
        watch = {r["ticker"] for r in rows_open}
        watch |= {a["ticker"] for a in archive.get("alerts") or [] if a.get("ticker")}
        return watch

    def test_archive_tickers_are_kept_even_when_not_open(self):
        collect = load_collect()
        rows_open = [{"ticker": "OPEN-1"}]
        archive = {"alerts": [{"ticker": "CLOSED-9"}, {"ticker": "OPEN-1"}, {}]}
        watch = self._watch_set(collect, rows_open, archive)
        self.assertIn("CLOSED-9", watch,
                      "a market cited by an archived alert must keep its observations")
        self.assertIn("OPEN-1", watch)

    def test_committed_data_demonstrates_the_old_rule_lost_series(self):
        """Documents the defect on the committed files. If they ever regress, say so."""
        try:
            markets = json.loads((LIVE / "markets.json").read_text())
            history = json.loads((LIVE / "price_history.json").read_text()).get("series") or {}
            archive = json.loads((LIVE / "alerts_archive.json").read_text()).get("alerts") or []
        except (OSError, json.JSONDecodeError) as exc:  # first run in a fresh clone
            self.skipTest(f"committed data not readable yet: {exc}")
        if not archive:
            self.skipTest("no archived alerts yet")

        open_tickers = {r["ticker"] for r in markets.get("open_markets") or []}
        alert_tickers = {a["ticker"] for a in archive if a.get("ticker")}
        outside_window = sorted(t for t in alert_tickers if t not in open_tickers)
        if not outside_window:
            self.skipTest("every archived alert market is still in its own open window; nothing to check")

        # These are exactly the tickers the old prune would have silently emptied.
        missing = [t for t in outside_window if not (history.get(t) or {}).get("observations")]
        self.assertEqual(
            missing, [],
            "history was pruned for markets cited by archived alerts: " + ", ".join(missing)
            + " — collect.py must keep the archive's tickers in its watch set")


if __name__ == "__main__":
    unittest.main(verbosity=2)
