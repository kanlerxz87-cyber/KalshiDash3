#!/usr/bin/env python3
"""F-107: a closed series must not vanish from an archive's category evidence.

Reproduces the failure in Actions run 46058016625 without network or orders.
The test runs the real collector build, alert builder and alert validator in a
scratch tree. The API response is a fixture, not a verified live observation.
Official route: https://docs.kalshi.com/api-reference/market/get-series
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
import collect  # noqa: E402
import build_alerts  # noqa: E402


def validator_module():
    spec = importlib.util.spec_from_file_location("validate_alerts_retention", ROOT / "scripts/tests/validate_alerts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ArchivedSeriesRetention(unittest.TestCase):
    def build(self, root, *, categories=("Economics",), unavailable=False, in_index=False):
        live = root / "data/live"
        live.mkdir(parents=True)
        shutil.copy(ROOT / "data/alert_rules.json", root / "data/alert_rules.json")
        # Fixed regression fixtures model the two assignment-bearing entries in
        # the original failure. Do not depend on a rolling production archive:
        # its documented 5,000-row cap may legitimately retire those entries.
        ticker = "KXAAAGASD-26NOV21-3.6600"
        alerts = [{
            "ticker": ticker, "category_id": "gas", "category_basis": "official-series",
            "series_categories": ["Economics"],
            "category_assigned_from": "GET /series categories (series_categories)",
            "market_source": collect.BASE + "/markets/" + ticker,
            "from_time": start, "to_time": end,
            "from_price": before, "to_price": after, "delta": round(after - before, 4),
            "direction": "up" if after > before else "down", "high_roi": False,
            "volume_24h_fp": None, "cause_link": None,
            "cause_status": "unverified: no official cause source collected",
        } for start, end, before, after in (
            ("2026-11-20T22:10:00Z", "2026-11-20T22:41:00Z", 0.07, 0.21),
            ("2026-11-20T21:42:00Z", "2026-11-20T22:04:00Z", 0.19, 0.09),
        )]
        # Two distinct alert rows reference one series. Neither market is in raw.
        (live / "alerts_archive.json").write_text(json.dumps({"schema": 1, "alerts": alerts}))
        requests = []
        series = {"ticker": "KXAAAGASD", "categories": list(categories), "title": "US gas price up", "tags": ["Econ Daily"]}

        def get(path, params=None, **kwargs):
            requests.append(path)
            if path == "/historical/cutoff":
                return {}, "fixture://cutoff"
            if path == "/series/KXAAAGASD":
                if unavailable:
                    raise RuntimeError("fixture API unavailable")
                return {"series": series}, collect.BASE + path
            raise AssertionError("unexpected request " + path)

        with patch.object(collect, "LIVE", live), \
                patch.object(collect, "load_categories", return_value={"categories": []}), \
                patch.object(collect, "fetch_series_index", return_value={"KXAAAGASD": series} if in_index else {}), \
                patch.object(collect, "official_discovery", return_value=({}, [])), \
                patch.object(collect, "scan_markets", return_value={"open": [], "settled": []}), \
                patch.object(collect, "historical_settled", return_value=({}, {})), \
                patch.object(collect, "backfill_from_candles", side_effect=lambda h, ts: (h, 0)), \
                patch.object(collect, "get", side_effect=get), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            payload = collect.build(include_orderbooks=0)
        return payload, requests

    def test_absent_from_scan_is_re_fetched_once_and_validation_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, calls = self.build(root)
            self.assertEqual(payload["open_markets"], [])
            self.assertEqual(payload["settled_markets"], [])
            self.assertEqual(calls.count("/series/KXAAAGASD"), 1)
            entry = payload["series_index"]["KXAAAGASD"]
            self.assertEqual(entry["categories"], ["Economics"])
            self.assertEqual(entry["source"], collect.BASE + "/series/KXAAAGASD")
            live = root / "data/live"
            with patch.object(build_alerts, "ROOT", root), patch.object(build_alerts, "LIVE", live), \
                    patch.object(sys, "argv", ["build_alerts.py"]), redirect_stdout(io.StringIO()):
                self.assertEqual(build_alerts.main(), 0)
            validator = validator_module()
            validator.LIVE = live
            validator.RULES = root / "data/alert_rules.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(validator.main(), 0, "\n".join(validator.errors))
            # Negative control: removing the retained entry reproduces the old
            # failure. A relaxed validator would incorrectly pass this case.
            payload["series_index"].pop("KXAAAGASD")
            (live / "markets.json").write_text(json.dumps(payload))
            validator = validator_module()
            validator.LIVE = live
            validator.RULES = root / "data/alert_rules.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(validator.main(), 1)
            self.assertTrue(any("assigned topic" in e for e in validator.errors))

    def test_failed_official_lookup_stays_unknown_never_inferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, calls = self.build(Path(tmp), unavailable=True)
            entry = payload["series_index"]["KXAAAGASD"]
            self.assertIsNone(entry["categories"])
            self.assertIsNone(entry["title"])
            self.assertEqual(calls.count("/series/KXAAAGASD"), 1)
            # Existing strict validation is deliberately not bypassed for unknown
            # official categories. This test proves the fix fabricates nothing.

    def test_current_official_answer_is_not_replaced_by_archived_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = self.build(Path(tmp), categories=("Test",))
            self.assertEqual(payload["series_index"]["KXAAAGASD"]["categories"], ["Test"])

    def test_bulk_official_answer_avoids_extra_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, calls = self.build(Path(tmp), in_index=True)
            self.assertEqual(payload["series_index"]["KXAAAGASD"]["categories"], ["Economics"])
            self.assertNotIn("/series/KXAAAGASD", calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
