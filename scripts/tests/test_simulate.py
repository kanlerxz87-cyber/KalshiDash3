#!/usr/bin/env python3
"""Unit tests for scripts/simulate.py: fee model, settlement, and signal handling.

Fixtures are synthetic and live only in a temporary directory. Nothing is
written under data/, so no invented market value reaches the site. The swing
detector and the archive builder are tested by main's owner, not here.

The fee table is copied from the official General Trading Fees table
(https://kalshi.com/docs/kalshi-fee-schedule.pdf, July 7, 2026 update) for 1 and
100 contracts. If the formula drifts from the table, these tests fail.

Run: python3 scripts/tests/test_simulate.py
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


simulate = load("simulate")

# (price, fee for 1 contract, fee for 100 contracts), from the General Trading Fees table.
FEE_TABLE = [
    (0.01, 0.01, 0.07), (0.05, 0.01, 0.34), (0.10, 0.01, 0.63), (0.15, 0.01, 0.90),
    (0.20, 0.02, 1.12), (0.25, 0.02, 1.32), (0.30, 0.02, 1.47), (0.35, 0.02, 1.60),
    (0.40, 0.02, 1.68), (0.45, 0.02, 1.74), (0.50, 0.02, 1.75), (0.55, 0.02, 1.74),
    (0.60, 0.02, 1.68), (0.65, 0.02, 1.60), (0.70, 0.02, 1.47), (0.75, 0.02, 1.32),
    (0.80, 0.02, 1.12), (0.85, 0.01, 0.90), (0.90, 0.01, 0.63), (0.95, 0.01, 0.34),
    (0.99, 0.01, 0.07),
]

STRAT = json.loads((ROOT / "data" / "strategies.json").read_text())
T_SIG = "2026-11-20T11:30:00Z"
T_NEXT = "2026-11-20T11:40:00Z"


class FeeTest(unittest.TestCase):
    def test_general_table_one_contract(self):
        for price, one, _ in FEE_TABLE:
            with self.subTest(price=price):
                self.assertAlmostEqual(simulate.taker_fee(price, 1, 1), one, places=4)

    def test_general_table_hundred_contracts(self):
        for price, _, hundred in FEE_TABLE:
            with self.subTest(price=price):
                self.assertAlmostEqual(simulate.taker_fee(price, 100, 1), hundred, places=4)

    def test_zero_multiplier_series_have_no_fee(self):
        self.assertEqual(simulate.taker_fee(0.5, 10, 0), 0.0)

    def test_fee_multipliers_from_schedule(self):
        fm = STRAT["fee_model"]["multipliers"]
        self.assertEqual(fm["KXBTCY"], 0)
        self.assertEqual(fm["KXETHY"], 0)
        self.assertEqual(fm["KXELECTIRAN"], 0)
        self.assertEqual(fm["KXAAAGASM"], 1)

    def test_no_settlement_fee_in_model(self):
        # The schedule states no settlement fee; the model must not add one.
        self.assertIn("settlement", STRAT["fee_model"]["settlement_fee"].lower())
        self.assertNotIn("settlement_fee_dollars", json.dumps(STRAT["fee_model"]).lower())


class SimulateTest(unittest.TestCase):
    """Run simulate.main() on synthetic inputs in a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.saved = (simulate.LIVE, simulate.OUT, simulate.STRAT_PATH)
        simulate.LIVE = self.dir
        simulate.OUT = self.dir / "simulation.json"
        simulate.STRAT_PATH = self.dir / "strategies.json"
        simulate.STRAT_PATH.write_text(json.dumps(STRAT))

    def tearDown(self):
        simulate.LIVE, simulate.OUT, simulate.STRAT_PATH = self.saved
        self._tmp.cleanup()

    def _write(self, alerts, history, open_rows=(), settled_rows=()):
        (self.dir / "alerts_archive.json").write_text(json.dumps({"schema": 1, "alerts": alerts}))
        (self.dir / "price_history.json").write_text(json.dumps({"schema": 1, "series": history}))
        (self.dir / "markets.json").write_text(json.dumps({
            "collected_at": T_NEXT, "base_url": "https://example.invalid/v2",
            "open_markets": list(open_rows), "settled_markets": list(settled_rows)}))

    def _alert(self, direction="up", high_roi=True, ticker="KXAAAGASM-X-1", **extra):
        a = {"ticker": ticker, "event_ticker": "E", "title": "x", "category_id": "gas",
             "category_basis": "seed", "from_time": "2026-11-20T11:20:00Z", "to_time": T_SIG,
             "from_price": 0.40 if direction == "up" else 0.60,
             "to_price": 0.50 if direction == "up" else 0.45,
             "delta": 0.10 if direction == "up" else -0.15, "direction": direction,
             "market_source": "https://example.invalid/m", "high_roi": high_roi}
        a.update(extra)
        return a

    def _obs(self, bid, ask, t=T_SIG):
        return {"observations": [{"t": t, "last": 0.5, "yes_bid": bid, "yes_ask": ask, "volume_fp": "1"}]}

    def _run(self):
        simulate.main()
        return json.loads(simulate.OUT.read_text())

    def _strat(self, doc, sid):
        return next(s for s in doc["strategies"] if s["id"] == sid)

    def test_up_swing_momentum_buys_yes_at_ask_and_wins(self):
        self._write([self._alert("up")], {"KXAAAGASM-X-1": self._obs(0.49, 0.50)},
                    settled_rows=[{"ticker": "KXAAAGASM-X-1", "result": "yes", "settlement_ts": T_NEXT}])
        doc = self._run()
        self.assertEqual(self._strat(doc, "S1")["wins"], 1)
        closed = [p for p in doc["settled_positions"] if p["strategy"] == "S1"][0]
        self.assertEqual(closed["side"], "yes")
        self.assertAlmostEqual(closed["entry_price"], 0.50)
        self.assertAlmostEqual(closed["entry_fee"], 0.02)
        # Win pays 1.00; net = 1.00 - 0.50 - 0.02 (no settlement fee).
        self.assertAlmostEqual(closed["realized_net"], 0.48)

    def test_up_swing_momentum_buys_yes_and_loses(self):
        self._write([self._alert("up")], {"KXAAAGASM-X-1": self._obs(0.49, 0.50)},
                    settled_rows=[{"ticker": "KXAAAGASM-X-1", "result": "no", "settlement_ts": T_NEXT}])
        doc = self._run()
        self.assertEqual(self._strat(doc, "S1")["losses"], 1)
        closed = [p for p in doc["settled_positions"] if p["strategy"] == "S1"][0]
        self.assertAlmostEqual(closed["realized_net"], -0.52)

    def test_fade_buys_no_at_one_minus_bid(self):
        # NO costs 1 - yes_bid. With bid 0.49 that is 0.51.
        self._write([self._alert("up")], {"KXAAAGASM-X-1": self._obs(0.49, 0.50)},
                    settled_rows=[{"ticker": "KXAAAGASM-X-1", "result": "no", "settlement_ts": T_NEXT}])
        doc = self._run()
        closed = [p for p in doc["settled_positions"] if p["strategy"] == "S2"][0]
        self.assertEqual(closed["side"], "no")
        self.assertAlmostEqual(closed["entry_price"], 0.51)
        self.assertEqual(closed["outcome"], "win")

    def test_no_quote_is_not_filled_and_not_priced_from_last_trade(self):
        self._write([self._alert("up")], {}, settled_rows=[
            {"ticker": "KXAAAGASM-X-1", "result": "no", "settlement_ts": T_NEXT}])
        doc = self._run()
        s1 = self._strat(doc, "S1")
        self.assertEqual(s1["filled"], 0)
        self.assertEqual(s1["not_filled_no_quote"], 1)
        self.assertEqual(s1["settled"], 0)

    def test_archive_quote_fields_are_used_when_present(self):
        self._write([self._alert("up", to_yes_bid=0.30, to_yes_ask=0.32)], {})
        doc = self._run()
        p = [x for x in doc["open_positions"] if x["strategy"] == "S1"][0]
        self.assertEqual(p["quote_source"], "archive")
        self.assertAlmostEqual(p["entry_price"], 0.32)

    def test_high_roi_filter_only_for_s3_and_s4(self):
        self._write([self._alert("up", high_roi=False)], {"KXAAAGASM-X-1": self._obs(0.49, 0.50)})
        doc = self._run()
        self.assertEqual(self._strat(doc, "S1")["signals"], 1)
        self.assertEqual(self._strat(doc, "S3")["signals"], 0)

    def test_bad_price_is_not_filled(self):
        self._write([self._alert("up")], {"KXAAAGASM-X-1": self._obs(0.00, 0.00)})
        doc = self._run()
        s1 = self._strat(doc, "S1")
        self.assertEqual(s1["filled"], 0)
        self.assertEqual(s1["not_filled_bad_price"], 1)

    def test_rerun_is_idempotent(self):
        self._write([self._alert("up")], {"KXAAAGASM-X-1": self._obs(0.49, 0.50)})
        first = self._run()
        second = self._run()
        self.assertEqual(first["counts"]["signals_processed_total"], second["counts"]["signals_processed_total"])
        self.assertEqual(self._strat(first, "S1")["filled"], self._strat(second, "S1")["filled"])
        self.assertEqual(second["counts"]["new_signals_this_run"], 0)

    def test_open_position_is_marked_to_bid_and_fee_is_charged_at_exit(self):
        self._write([self._alert("up")], {"KXAAAGASM-X-1": self._obs(0.49, 0.50)},
                    open_rows=[{"ticker": "KXAAAGASM-X-1", "yes_bid_dollars": 0.60, "no_bid_dollars": 0.38,
                                "series_ticker": "KXAAAGASM"}])
        doc = self._run()
        p = [x for x in doc["open_positions"] if x["strategy"] == "S1"][0]
        self.assertEqual(p["status"], "open")
        self.assertAlmostEqual(p["bid_now"], 0.60)
        # Exit fee on 0.60 for 1 contract = 0.02. Unrealised = 0.60 - 0.50 - 0.02 - 0.02.
        self.assertAlmostEqual(p["unrealized_net"], 0.06)


if __name__ == "__main__":
    unittest.main(verbosity=2)
