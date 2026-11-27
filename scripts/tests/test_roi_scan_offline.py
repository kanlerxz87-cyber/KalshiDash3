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

# Open fixtures must close in the FUTURE relative to whenever this runs, otherwise the
# model's own "already past close_time" gate rejects them and the assertions below fail for
# a reason that has nothing to do with the code under test (this happened on main: the
# hard-coded 2026-11-20T17:00:00Z became the past and three checks went red).
import datetime as _d

def _future(hours=2):
    return (_d.datetime.now(_d.timezone.utc) + _d.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


CLOSE = _future(2)


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
    # Observed demo shape, not a synthetic one: an illiquid market quoted "0.0000" on both
    # sides (e.g. KXAAAGASD-26NOV21-3.7300 on
    # https://external-api.demo.kalshi.co/trade-api/v2/markets?series_ticker=KXAAAGASD&status=open,
    # 2026-11-20). Both sides then have a zero cost basis, the model must refuse them and the
    # scan must survive: a ZeroDivisionError in this path is what left data/live/roi.json
    # unpublished (Actions run 44762120780 at 15:19:59Z).
    mkt("KXAAAGASM-26DEC31-5.50", 0.0, 0.0, 0.0, 5000.0, "US average gas price on Dec 31 (0c book)?"),
    # must be excluded entirely: a multivariate combo mentioning gas
    {"ticker": "KXMVE-26NOV20-A", "event_ticker": "KXMVE-26NOV20", "title": "yes gas,yes tie",
     "mve_collection_ticker": "KXMVE-26NOV20", "status": "active", "yes_bid_dollars": "0.3000",
     "yes_ask_dollars": "0.3200", "last_price_dollars": "0.3100", "volume_fp": "10.00",
     "volume_24h_fp": "10.00", "close_time": CLOSE},
    # E9D9-2: Test-category instrument matching Crypto keyword ("BTC") that leaked into near_misses
    mkt("KXDEMOFUTHOURLY-26NOV27H18-UP", 0.01, 1.00, 0.55, 0.0, "Demo BTC at or above 59876.36 USD"),
    # E9D9-3: non-election Politics series matching Elections keyword ("president")
    mkt("KXAPRPOTUS-26DEC04-38.6", 0.40, 0.44, 0.42, 100.0, "President approval rating above 38.6%?"),
    # E9D9-2: daily natural-gas series filed under Entertainment/Oil & Gas
    mkt("KXNATGASD-26NOV27-3.30", 0.45, 0.49, 0.47, 500.0, "Will natural gas close above 3.30?"),
]
# tiny size on the golf market so its own book is thin
OPEN[1]["yes_bid_size_fp"] = "20.00"
OPEN[1]["yes_ask_size_fp"] = "0.00"

# A settled market must sit in the PAST, so both are derived from the clock too (an earlier
# revision had the golf one closing 2026-11-21T23:00Z — "settled" with a future close_time,
# which is a state the API cannot return).
SETTLED = [
    mkt("KXAAAGASM-26NOV19-4.00", 0.60, 0.62, 0.61, 1200.0, "US average gas price on Nov 19?",
        close=_future(-20), status="finalized", result="no"),
    mkt("KXPGATOUR-26NOV21-T1", 0.55, 0.57, 0.56, 8000.0, "The RSM Classic: winner 1?",
        close=_future(-2), status="finalized", result="yes"),
]

BOOKS = {
    "KXAAAGASM-26DEC31-4.00": {"yes": [["0.4800", "900.00"]], "no": [["0.5100", "800.00"]]},
    # a two-sided 0c book: depth passes, so nothing but the degenerate quote stops it
    "KXAAAGASM-26DEC31-5.50": {"yes": [["0.0000", "900.00"]], "no": [["1.0000", "800.00"]]},
    "KXPGATOUR-26NOV22-T60": {"yes": [["0.2000", "20.00"]], "no": []},
    "KXMVE-26NOV20-A": {"yes": [], "no": []},
}


def fake_get(path, params=None, retries=3):
    pairs = list(params.items()) if isinstance(params, dict) else list(params or [])
    params = dict(pairs)

    def getall(key):
        return [v for k, v in pairs if k == key]

    url = f"{roi_scan.BASE}{path}"
    if path == "/series":
        if not params:
            return {"series": [
                {"ticker": "KXDEMOFUTHOURLY", "categories": ["Test"], "tags": ["Demo"], "title": "Demo hourly event contract futures"},
                {"ticker": "KXAPRPOTUS", "categories": ["Politics"], "tags": ["Recurring", "Trump"], "title": "Potus approval rating"},
                {"ticker": "KXNATGASD", "categories": ["Entertainment"], "tags": ["Oil & Gas"], "title": "Natural Gas Daily"},
            ]}, url
        return {"series": []}, url
    if path.startswith("/series/") and not path.endswith("/candlesticks"):
        return {"series": {}}, url
    if path == "/historical/cutoff":
        return {"market_settled_ts": "2026-09-01T00:00:00Z", "trades_created_ts": "2026-10-01T00:00:00Z"}, url
    if path.startswith("/markets/orderbooks"):
        # `tickers` is a repeated string[] (1-100) per
        # https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks, and the demo
        # host does not split a comma-joined value: observed 2026-11-20, `?tickers=A,B,C` answered
        # 200 with ONE entry whose ticker was the literal "A,B,C" and empty arrays, and a joined
        # value over the documented 200-char limit answered 400 — the "order books: 0" line in
        # Actions run 44762120780. This fixture accepts the repeated form in either calling
        # convention (a dict with a list value, as roi_scan.py sends it with urlencode(doseq), or a
        # raw list of pairs) and REFUSES any comma, so a regression cannot slip through as a
        # successful-looking empty answer.
        raw = []
        for v in getall("tickers"):
            raw.extend(v if isinstance(v, (list, tuple)) else [v])
        assert raw, "the order-book call must send at least one tickers= value"
        assert not any("," in str(v) for v in raw), \
            f"tickers must be repeated one per parameter, not comma-joined: {raw}"
        tickers = [str(v) for v in raw if v]
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

    def fake_collect_get(path, params=None, retries=3):
        if path == "/series" and not params:
            return {"series": [
                {"ticker": "KXDEMOFUTHOURLY", "categories": ["Test"], "tags": ["Demo"], "title": "Demo hourly event contract futures"},
                {"ticker": "KXAPRPOTUS", "categories": ["Politics"], "tags": ["Recurring", "Trump"], "title": "Potus approval rating"},
                {"ticker": "KXNATGASD", "categories": ["Entertainment"], "tags": ["Oil & Gas"], "title": "Natural Gas Daily"},
            ]}, path
        if path == "/series" and params:
            return {"series": []}, path
        if path.startswith("/series/"):
            return {"series": {}}, path
        return {"series": []}, path

    collect.get = fake_collect_get
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

    yes(doc["counts"]["open_scanned"] == 7, f"scanned {doc['counts']['open_scanned']} open markets, expected 7")
    yes(doc["counts"]["open_in_scope"] == 3,
        f"in scope {doc['counts']['open_in_scope']}, expected 3 (combo + Test + Politics + KXNATGASD must be excluded)")
    yes(doc["counts"].get("open_excluded_category_conflict") == 2,
        f"expected 2 category conflicts (KXDEMOFUTHOURLY + KXAPRPOTUS), got {doc['counts'].get('open_excluded_category_conflict')}")
    yes(doc["counts"].get("open_excluded_off_topic_or_qa") == 1,
        f"expected 1 off-topic/QA exclusion (KXNATGASD), got {doc['counts'].get('open_excluded_off_topic_or_qa')}")
    all_out_tickers = {p["ticker"] for k in ("picks", "near_misses", "unscoreable") for p in doc[k]}
    for forbidden in ("KXDEMOFUTHOURLY-26NOV27H18-UP", "KXAPRPOTUS-26DEC04-38.6", "KXNATGASD-26NOV27-3.30"):
        yes(forbidden not in all_out_tickers, f"{forbidden} must not appear in picks/near_misses/unscoreable")
    tickers = [p["ticker"] for p in doc["picks"]]
    yes("KXAAAGASM-26DEC31-4.00" in tickers, f"the qualifying gas market must be a pick, got {tickers}")
    yes("KXMVE-26NOV20-A" not in tickers, "a combo must never be picked")
    yes("KXMVE-26NOV20-A" not in [p["ticker"] for p in doc["alerts"]], "a combo must never raise an alert")
    unsc = {p["ticker"]: p for p in doc["unscoreable"]}
    yes(doc["counts"]["unscoreable"] == 2, f"two markets have no price to buy (one one-sided, one quoted 0c), got {doc['counts']['unscoreable']}")
    zero = unsc.get("KXAAAGASM-26DEC31-5.50")
    yes(zero is not None, "the 0c-quote market must be listed as unscoreable, not dropped")
    yes(bool(zero) and any("degenerate" in r or "no buyable side" in str(f) for r in (zero.get("reasons") or []) for f in (zero.get("fails") or [None])) or
        bool(zero) and (any("degenerate" in r for r in (zero.get("reasons") or [])) or any("no buyable side" in str(f) for f in (zero.get("fails") or []))),
        f"the 0c-quote market must say why it cannot be priced, got reasons={((zero or {}).get('reasons'))} fails={((zero or {}).get('fails'))}")
    yes(bool(zero) and zero.get("entry") is None, "a degenerate quote must never carry a modelled entry")
    yes("KXAAAGASM-26DEC31-5.50" not in tickers, "a market with no buyable price can never be a pick")
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
    d5 = json.loads(out.read_text())
    d5["near_misses"].append({
        "ticker": "KXDEMOFUTHOURLY-26NOV27H18-UP", "eligible": False,
        "fails": ["spread 99.0c > 10c cap"], "reasons": [], "score": -0.68,
        "bid": 0.01, "ask": 1.0, "last": 0.55,
        "entry": {"side": "NO", "entry": 0.99, "cost": 0.9907, "roi": -0.68, "fee_unit": 0.0007, "ev": -0.67},
        "title": "Demo BTC at or above 59876.36 USD", "category_id": "crypto",
        "category_basis": "keyword", "series_categories": ["Test"],
        "result": None, "catalysts": [], "source": "https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDEMOFUTHOURLY-26NOV27H18-UP",
    })
    bad_cases["a Test-category instrument in near_misses"] = (d5, "contradicts official series record")
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
