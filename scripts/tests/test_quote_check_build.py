#!/usr/bin/env python3
"""49BA-1: the real alert builder must write the per-row quote check, and the real validator
must refuse a row whose label contradicts its own recorded fields.

The regression that matters: `last_price_dollars` is a print, `yes_bid_dollars` /
`yes_ask_dollars` are the two-sided quote of the SAME Get Markets read
(https://docs.kalshi.com/api-reference/market/get-markets). A swing whose printed end price sits
outside that band was not available at the quote, so the row has to say so instead of presenting
the print as an executable move. This runs the shipped build → alert builder → strict validator in
a scratch tree; every price here is a fixture, not a live observation.

Negative controls: mislabelling the row, dropping the block from one row, and dropping the
published counts each make the validator fail.

Run: python3 scripts/tests/test_quote_check_build.py
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_alerts  # noqa: E402

BASE = "https://external-api.demo.kalshi.co/trade-api/v2"

# Printed ends OUTSIDE the quote of the same read: the committed KXBTCY-27JAN0100-B97500 rows
# reverse 1c <-> 97c against a 0.00 / 0.01 quote, which is exactly the case this check exists for.
OUT_TICKER = "KXBTCY-27JAN0100-B97500"
IN_TICKER = "KXPGATOUR-26NOV22-T4"


def _market(ticker: str, title: str, category: str, basis: str = "seed", vol24: float = 5.0) -> dict:
    return {
        "ticker": ticker,
        "event_ticker": ticker.split("-")[0],
        "series_ticker": ticker.split("-")[0],
        "title": title,
        "category_id": category,
        "category_basis": basis,
        "series_categories": ["Crypto" if category == "crypto" else "Sports"],
        "category_matched_by": "official",
        "status": "active",
        "volume_24h_fp": vol24,
        "volume_fp": 1000.0,
        "source": f"{BASE}/markets/{ticker}",
    }


def history() -> dict:
    """Two consecutive reads per market; the second is the swing's to_time."""
    return {
        "schema": 1,
        "note": "fixture, not a live observation",
        "series": {
            OUT_TICKER: {"observations": [
                {"t": "2026-11-27T22:00:00Z", "last": 0.01, "yes_bid": 0.0, "yes_ask": 0.01, "volume_fp": "1000.00"},
                {"t": "2026-11-27T22:15:00Z", "last": 0.97, "yes_bid": 0.0, "yes_ask": 0.01, "volume_fp": "1100.00"},
            ]},
            IN_TICKER: {"observations": [
                {"t": "2026-11-27T22:00:00Z", "last": 0.40, "yes_bid": 0.39, "yes_ask": 0.41, "volume_fp": "500.00"},
                {"t": "2026-11-27T22:15:00Z", "last": 0.52, "yes_bid": 0.51, "yes_ask": 0.53, "volume_fp": "700.00"},
            ]},
        },
    }


def markets() -> dict:
    return {
        "schema": 1,
        "environment": "demo",
        "base_url": BASE,
        "collected_at": "2026-11-27T22:15:01Z",
        "counts": {},
        "series_index": {
            "KXBTCY": {"categories": ["Crypto"], "source": f"{BASE}/series/KXBTCY"},
            "KXPGATOUR": {"categories": ["Sports"], "source": f"{BASE}/series/KXPGATOUR"},
        },
        "open_markets": [
            _market(OUT_TICKER, "BTC price on Jan 1, 2027?", "crypto"),
            _market(IN_TICKER, "Golf outright winner (fixture)", "golf"),
        ],
        "settled_markets": [],
    }


class QuoteCheckBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.live = self.root / "data/live"
        self.live.mkdir(parents=True)
        shutil.copy(ROOT / "data/alert_rules.json", self.root / "data/alert_rules.json")
        (self.live / "price_history.json").write_text(json.dumps(history()))
        (self.live / "markets.json").write_text(json.dumps(markets()))

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        with patch.object(build_alerts, "ROOT", self.root), \
                patch.object(build_alerts, "LIVE", self.live), \
                patch.object(sys, "argv", ["build_alerts.py"]), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(build_alerts.main(), 0)

    def validate(self):
        spec = importlib.util.spec_from_file_location("validate_alerts_quote", ROOT / "scripts/tests/validate_alerts.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.LIVE = self.live
        mod.RULES = self.root / "data/alert_rules.json"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = mod.main()
        return code, mod.errors

    def feed(self):
        return json.loads((self.live / "alerts.json").read_text())

    def archive(self):
        return json.loads((self.live / "alerts_archive.json").read_text())

    # ------------------------------------------------------------------ positive
    def test_builder_writes_the_quote_block_on_every_row(self):
        self.build()
        rows = self.archive()["alerts"]
        self.assertEqual(len(rows), 2, "one swing per market expected")
        for a in rows:
            self.assertIn("quote", a["evidence"], f"{a['ticker']} must carry evidence.quote")
            self.assertIn(a["evidence"]["quote"]["state"],
                          ("inside_quote", "outside_quote", "unknown_quote"))

    def test_print_outside_the_quote_is_marked_with_its_distance(self):
        self.build()
        out = next(a for a in self.archive()["alerts"] if a["ticker"] == OUT_TICKER)
        q = out["evidence"]["quote"]
        self.assertEqual(q["state"], "outside_quote")
        self.assertAlmostEqual(q["outside_by_dollars"], 0.96, places=4)
        self.assertAlmostEqual(q["spread_dollars"], 0.01, places=4)
        self.assertEqual((q["to_yes_bid"], q["to_yes_ask"]), (0.0, 0.01))
        # The independent state block is unchanged: 100 contracts traded, at the floor.
        self.assertEqual(out["evidence"]["state"], "traded_ge_floor")
        self.assertEqual(out["evidence"]["contracts_traded"], 100.0)

    def test_print_inside_the_quote_is_marked_inside(self):
        self.build()
        inside = next(a for a in self.archive()["alerts"] if a["ticker"] == IN_TICKER)
        q = inside["evidence"]["quote"]
        self.assertEqual(q["state"], "inside_quote")
        self.assertEqual(q["outside_by_dollars"], 0.0)

    def test_published_counts_describe_the_served_rows(self):
        self.build()
        qc = self.feed()["counts"]["quote_check"]
        self.assertEqual(qc["rows"], 2)
        self.assertEqual(qc["inside_quote"], 1)
        self.assertEqual(qc["outside_quote"], 1)
        self.assertEqual(qc["unknown_quote"], 0)

    def test_validator_accepts_the_built_feed(self):
        self.build()
        code, errors = self.validate()
        self.assertEqual(code, 0, "\n".join(errors))

    # ------------------------------------------------------------------ negative controls
    def _mutate(self, fn):
        doc = self.archive()
        fn(doc)
        (self.live / "alerts_archive.json").write_text(json.dumps(doc))

    def test_validator_refuses_a_label_that_contradicts_the_recorded_fields(self):
        self.build()
        self._mutate(lambda d: d["alerts"][0]["evidence"]["quote"].update({"state": "inside_quote"}))
        code, errors = self.validate()
        self.assertEqual(code, 1)
        self.assertTrue(any("quote.state" in e for e in errors), errors)

    def test_validator_refuses_a_partial_block(self):
        self.build()
        self._mutate(lambda d: d["alerts"][0]["evidence"].pop("quote", None))
        code, errors = self.validate()
        self.assertEqual(code, 1)
        self.assertTrue(any("must carry it on every row" in e for e in errors), errors)

    def test_validator_refuses_missing_published_counts(self):
        self.build()
        doc = self.feed()
        doc["counts"].pop("quote_check", None)
        (self.live / "alerts.json").write_text(json.dumps(doc))
        code, errors = self.validate()
        self.assertEqual(code, 1)
        self.assertTrue(any("counts.quote_check missing" in e for e in errors), errors)

    def test_validator_refuses_a_wrong_outside_count(self):
        self.build()
        doc = self.feed()
        doc["counts"]["quote_check"]["outside_quote"] = 2
        (self.live / "alerts.json").write_text(json.dumps(doc))
        code, errors = self.validate()
        self.assertEqual(code, 1)
        self.assertTrue(any("counts.quote_check.outside_quote" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
