#!/usr/bin/env python3
"""Offline end-to-end check of scripts/roi_scan.py, with the API replaced by fixtures.

The sandbox has no route to the Kalshi demo host, so the scan is exercised here against a
hand-built fixture that is shaped exactly like the documented responses:
  GET /markets ................ https://docs.kalshi.com/api-reference/market/get-markets
  GET /markets/orderbooks ..... https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks
  GET /series/../candlesticks . https://docs.kalshi.com/api-reference/market/get-market-candlesticks
and then the produced file is fed to scripts/tests/validate_roi.py, so both the writer and
the gate are tested together. In CI the same scan runs against the real demo API and the
same validator runs again on the committed result.

Run: python3 scripts/tests/test_roi_scan_offline.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "tests"))

import datetime as _dt

import roi_scan  # noqa: E402
import collect  # noqa: E402

# Derived from the clock, never hard-coded. An earlier revision pinned CLOSE to
# "2026-11-20T17:00:00Z"; roi_scan scores against the real wall clock, so once that hour
# passed every fixture market tripped the "already past close_time" gate, the scan produced
# zero picks, and this test failed for a reason that had nothing to do with the code — while
# still having passed in CI an hour earlier. A test whose fixture expires is a test that
# silently stops testing, so the open fixtures are always three hours ahead of now.
def _hours_ahead(h: float) -> str:
    t = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=h)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


CLOSE = _hours_ahead(3)


def mkt(t, bid, ask, last, vol24, title, close=CLOSE, status="active", result=None, vb="900.00", va="800.00"):
    return {
        "ticker": t, "event_ticker": t.split("-")[0], "title": title, "yes_sub_title": title,
        # a null quote level is sent as JSON null, the way the API omits an unquoted side
        "yes_bid_dollars": None if bid is None else f"{bid:.4f}",
        "yes_ask_dollars": None if ask is None else f"{ask:.4f}",
        "last_price_dollars": None if last is None else f"{last:.4f}",
        "yes_bid_size_fp": vb, "yes_ask_size_fp": va,
        "volume_fp": "90000.00", "volume_24h_fp": f"{vol24:.2f}", "open_interest_fp": "40000.00",
        "status": status, "result": result, "close_time": close, "expected_expiration_time": close,
        "rules_primary": "Settles per the published report at https://gasprices.aaa.com/national-average.",
        "notional_value_dollars": "1.0000",
    }


OPEN = [
    # eligible: 0.48/0.48 with a 13c upward move in the fixture history -> q 0.50, small positive ROI
    mkt("KXAAAGASM-26DEC31-4.00", 0.48, 0.48, 0.48, 5000.0, "US average gas price on Dec 31?"),
    # gated: one-sided quote, so the spread cannot be measured
    mkt("KXPGATOUR-26NOV22-T60", 0.20, None, None, 30000.0, "The RSM Classic: winner?"),
    # must be excluded entirely: a multivariate combo mentioning gas
    {"ticker": "KXMVE-26NOV20-A", "event_ticker": "KXMVE-26NOV20", "title": "yes gas,yes tie",
     "mve_collection_ticker": "KXMVE-26NOV20", "status": "active", "yes_bid_dollars": "0.3000",
     "yes_ask_dollars": "0.3200", "last_price_dollars": "0.3100", "volume_fp": "10.00",
     "volume_24h_fp": "10.00", "close_time": CLOSE},
]
# tiny size on the golf market so its own book is thin
OPEN[1]["yes_bid_size_fp"] = "20.00"
OPEN[1]["yes_ask_size_fp"] = "0.00"

# A settled market must sit in the PAST, so both are derived from the clock too (an earlier
# revision had the golf one closing 2026-11-21T23:00Z — "settled" with a future close_time,
# which is a state the API cannot return).
SETTLED = [
    mkt("KXAAAGASM-26NOV19-4.00", 0.60, 0.62, 0.61, 1200.0, "US average gas price on Nov 19?",
        close=_hours_ahead(-8), status="finalized", result="no"),
    mkt("KXPGATOUR-26NOV21-T1", 0.55, 0.57, 0.56, 8000.0, "The RSM Classic: winner 1?",
        close=_hours_ahead(-3), status="finalized", result="yes"),
]

BOOKS = {
    "KXAAAGASM-26DEC31-4.00": {"yes": [["0.4800", "900.00"]], "no": [["0.5100", "800.00"]]},
    "KXPGATOUR-26NOV22-T60": {"yes": [["0.2000", "20.00"]], "no": []},
    "KXMVE-26NOV20-A": {"yes": [], "no": []},
}


def fake_get(path, params=None, retries=3):
    params = params or {}
    url = f"{roi_scan.BASE}{path}"
    if path == "/series":
        return {"series": []}, url
    if path == "/historical/cutoff":
        return {"market_settled_ts": "2026-09-01T00:00:00Z", "trades_created_ts": "2026-10-01T00:00:00Z"}, url
    if path.startswith("/markets/orderbooks"):
        tickers = [t for t in (params.get("tickers") or "").split(",") if t]
        obs = []
        for t in tickers:
            b = BOOKS.get(t)
            obs.append({"ticker": t, "orderbook_fp": {"yes_dollars": b["yes"], "no_dollars": b["no"]} if b else {"yes_dollars": [], "no_dollars": []}})
        return {"orderbooks": obs}, url
    if path.startswith("/series/") and path.endswith("/candlesticks"):
        tk = path.split("/markets/")[1].split("/")[0]
        # Both fixtures are deliberately quoted away from the traded price, so the blended
        # estimate differs from the touch by more than the fee: one signal per side, and
        # both sides happen to be right.
        if tk.endswith("T1"):     # golf: quoted 0.30/0.32, traded 0.44, settles YES -> a YES signal that wins
            cs = [{"end_period_ts": 1795000000, "yes_bid": {"close_dollars": "0.3000"},
                   "yes_ask": {"close_dollars": "0.3200"}, "price": {"close_dollars": "0.4400"},
                   "volume_fp": "500.00", "open_interest_fp": "9000.00"}]
        else:                      # gas: quoted 0.70/0.72, traded 0.58, settles NO -> a NO signal that wins
            cs = [{"end_period_ts": 1794900000, "yes_bid": {"close_dollars": "0.7000"},
                   "yes_ask": {"close_dollars": "0.7200"}, "price": {"close_dollars": "0.5800"},
                   "volume_fp": "400.00", "open_interest_fp": "40000.00"}]
        return {"ticker": tk, "candlesticks": cs}, url
    if path == "/markets":
        status = params.get("status")
        if status == "settled":
            return {"markets": SETTLED, "cursor": ""}, url
        if status == "open":
            return {"markets": OPEN, "cursor": ""}, url
        if params.get("tickers"):
            want = set(params["tickers"].split(","))
            return {"markets": [m for m in OPEN if m["ticker"] in want]}, url
        return {"markets": []}, url
    raise AssertionError(f"unexpected request in the fixture: {path} {params}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="kdsim"))
    # History for the eligible market, timestamped relative to now so the 30-minute
    # lookback window keeps working whenever this runs: 0.35 -> 0.48 is a 13c swing.
    import datetime as _dt
    def ago(mins):
        return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp / "price_history.json").write_text(json.dumps({"schema": 1, "series": {
        "KXAAAGASM-26DEC31-4.00": {"observations": [
            {"t": ago(36), "last": 0.35, "yes_bid": 0.34, "yes_ask": 0.36, "volume_fp": "80000.00"},
            {"t": ago(2), "last": 0.48, "yes_bid": 0.47, "yes_ask": 0.49, "volume_fp": "90000.00"},
        ]}}}))
    orig_get, orig_collect_get, orig_live = roi_scan.get, collect.get, roi_scan.LIVE
    roi_scan.get = fake_get
    collect.get = lambda path, params=None, retries=3: ({"series": []}, path)
    roi_scan.LIVE = tmp
    try:
        out = tmp / "roi.json"
        doc = roi_scan.build(validate_n=2, out_path=out)
    finally:
        roi_scan.get, collect.get, roi_scan.LIVE = orig_get, orig_collect_get, orig_live

    problems = []

    def yes(cond, msg):
        if not cond:
            problems.append(msg)

    yes(doc["counts"]["open_scanned"] == 3, f"scanned {doc['counts']['open_scanned']} open markets, expected 3")
    yes(doc["counts"]["open_in_scope"] == 2, f"in scope {doc['counts']['open_in_scope']}, expected 2 (the combo must be excluded)")
    tickers = [p["ticker"] for p in doc["picks"]]
    yes("KXAAAGASM-26DEC31-4.00" in tickers, f"the qualifying gas market must be a pick, got {tickers}")
    yes("KXMVE-26NOV20-A" not in tickers, "a combo must never be picked")
    yes("KXMVE-26NOV20-A" not in [p["ticker"] for p in doc["alerts"]], "a combo must never raise an alert")
    unsc = {p["ticker"]: p for p in doc["unscoreable"]}
    yes(doc["counts"]["unscoreable"] == 1, f"exactly one market has no two-sided quote, got {doc['counts']['unscoreable']}")
    yes("KXPGATOUR-26NOV22-T60" in unsc, f"the one-sided market must be listed as unscoreable, got {list(unsc)}")
    yes("no quoted price" in " ".join(unsc.get("KXPGATOUR-26NOV22-T60", {}).get("reasons", [])),
        "its reason must be the missing quote, not an invented price")
    yes(unsc.get("KXPGATOUR-26NOV22-T60", {}).get("entry") is None,
        "an unscoreable row must not carry a modelled entry")
    al = doc["alerts"]
    yes(len(al) == 1 and abs(al[0]["delta"] - 0.13) < 1e-9, f"expected exactly one 13c alert, got {al}")
    yes(al and al[0]["in_picks"] is True, "the alert must be marked as belonging to the picks feed")
    yes(al and al[0]["catalysts"] and "gasprices.aaa.com" in al[0]["catalysts"][0]["url"],
        "the catalyst link must be copied from the market's own rules text")
    v = doc["validation"]
    yes(v["markets_tested"] == 2, f"replay should cover both settled fixtures, got {v['markets_tested']}")
    yes(v["signals"] == 2, f"the replay should find one signal per settled market, got {v['signals']} skipped={v['skipped']}")
    yes(v["hits"] == 2 and v["misses"] == 0, f"both fixture signals must win, got hits={v['hits']} misses={v['misses']}")
    yes(v["pnl_per_100_contracts"] > 0, f"a 2-for-2 record must show positive pnl, got {v['pnl_per_100_contracts']}")
    yes(v["not_measured"] and v["method"], "the replay must state its method and its limits")
    # the golf candle is quoted 0.80/0.82 and settles yes -> a YES entry is expected and must win
    yes(v["baseline_always_yes_bets"] == 2, "baseline must count both replayed markets")
    yes(isinstance(v.get("hit_rate"), float) and v.get("hit_rate") == 1.0, f"hit rate must be the measured fraction, got {v.get('hit_rate')}")
    yes(set(v["by_category"]) <= {"gas", "golf"}, f"replay rows must be attributed to a real category, got {list(v['by_category'])}")
    for p in doc["picks"]:
        yes(str(p["source"]).startswith("https://"), "every pick needs an https source")
        yes(p["fee_multiplier"]["listed"] is True, "the gas series is listed in the fee schedule, so the multiplier must say so")
    yes(json.dumps(doc.get("disclaimers")) != "[]", "disclaimers must be present")

    gate = subprocess.run([sys.executable, str(ROOT / "scripts" / "tests" / "validate_roi.py"), str(out)],
                          capture_output=True, text=True)
    yes(gate.returncode == 0, f"validate_roi.py rejected its own output:\n{gate.stderr}")
    sample = out

    # The gate must actually reject a bad file — a validator that always passes is theatre.
    gate_dir = tmp / "neg"
    gate_dir.mkdir()
    bad_cases = {}
    d1 = json.loads(out.read_text())
    d1["alerts"].append({"ticker": "KXAAAGASM-26DEC31-4.00", "t": "2026-11-20T13:00:00Z", "previous_t": "2026-11-20T12:00:00Z",
                         "from": 0.48, "to": 0.51, "delta": 0.03, "direction": "up", "cents": 3.0,
                         "category_id": "gas", "category_basis": "seed", "source": "https://x/y", "catalysts": [],
                         "in_picks": True})
    bad_cases["a 3c move labelled as an alert"] = (d1, "below the")
    d2 = json.loads(out.read_text())
    if d2["picks"]:
        d2["picks"][0]["eligible"] = False
        d2["picks"][0]["fails"] = ["depth 1 < 50 contracts at the touch"]
    bad_cases["a gated market left in picks"] = (d2, "not eligible")
    d3 = json.loads(out.read_text())
    d3.pop("collected_at")
    bad_cases["a scan with no timestamp"] = (d3, "collected_at")
    d4 = json.loads(out.read_text())
    if d4["picks"]:
        d4["picks"][0]["category_basis"] = "keyword"
    bad_cases["a keyword-only match presented as a pick"] = (d4, "keyword-only")
    for label, (doc_bad, needle) in bad_cases.items():
        f = gate_dir / f"{abs(hash(label))}.json"
        f.write_text(json.dumps(doc_bad))
        g = subprocess.run([sys.executable, str(ROOT / "scripts" / "tests" / "validate_roi.py"), str(f)],
                           capture_output=True, text=True)
        yes(g.returncode != 0, f"validate_roi.py accepted a bad file: {label}")
        yes(needle in (g.stderr + g.stdout), f"validate_roi.py rejected {label} for the wrong reason: {g.stderr[:200]}")
    print(f"    negative cases: {len(bad_cases)} bad files all refused by validate_roi.py")

    if problems:
        print("ROI SCAN OFFLINE CHECK FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"OK: scan wrote {len(doc['picks'])} picks, {len(doc['near_misses'])} near misses, {len(al)} alerts;")
    print(f"    combos excluded, one-sided quote gated (not priced), validation replay "
          f"{v['signals']} signals / hit rate {v['hit_rate']}; validate_roi.py accepted the file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
