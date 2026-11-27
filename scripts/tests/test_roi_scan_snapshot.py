#!/usr/bin/env python3
"""Run the live-desk scan over the REAL committed API payload, with the network stubbed off.

Two defects in this pipeline were found by running the scan against real demo data instead of
round-number fixtures, and both are pinned here:

1. **A zero-cost side killed the whole scan.** The demo book pins sides at the edge of the
   price band (`yes_ask_dollars = 0.0000`, `yes_bid_dollars = 1.0000`) — 127 of the 387 open
   in-scope markets in data/live/markets.json, collected 2026-11-20T15:19:53Z. ROI =
   (win − cost) / cost has no value at a cost of $0.00, so roi_scan died with
   ZeroDivisionError while every fixture-based test stayed green, and data/live/roi.json was
   never written. A side is now priced only when its quote sits strictly inside (0, 1); a
   degenerate level is reported as a reason and never repriced
   (scripts/roi_model.py, mirrored by assets/live.js).
2. **The order-book query was silently empty.** GET /markets/orderbooks declares `tickers` as a
   repeated string[] (1-100), unlike GET /markets, which takes a comma-separated list. Comma
   joining returns 200 with one entry whose ticker is the whole joined string and both arrays
   empty — indistinguishable from "no liquidity", and it produced `orderbooks: 0` in the
   published scan. This test asserts the request shape and that unrequested tickers are dropped.

Run: python3 scripts/tests/test_roi_scan_snapshot.py
"""
from __future__ import annotations

import io
import json
import math
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SNAP = ROOT / "data" / "live" / "markets.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "tests"))

import roi_scan  # noqa: E402
import roi_model as RM  # noqa: E402
import collect  # noqa: E402

DEGENERATE = "quoted at a degenerate 0.00/1.00 level: no price to buy, so no entry is priced"
BOGUS = "KXNOTREQUESTED-99X"


def offline_get(path, params=None, retries=3):
    """Serve exactly what the snapshot holds; anything not in it is a hard failure."""
    params = params or {}
    url = f"{roi_scan.BASE}{path}"
    doc = json.loads(SNAP.read_text())
    if path == "/markets":
        status = params.get("status")
        rows = doc["open_markets"] if status == "open" else (doc.get("settled_markets") or [])
        return {"markets": rows, "cursor": ""}, url
    if path == "/series":
        return {"series": []}, url
    if path.startswith("/series/") and not path.endswith("/candlesticks"):
        st = path.split("/series/", 1)[1].upper()
        srec = (doc.get("series_index") or {}).get(st)
        return {"series": {"ticker": st, **(srec or {})} if srec else {}}, url
    if path == "/historical/cutoff":
        # The snapshot does not hold this endpoint, and inventing a cutoff would be exactly the
        # fabrication the site forbids. RuntimeError is the path build() takes when the API is
        # unreachable: historical_cutoff stays null and the page shows it blank.
        raise RuntimeError("no /historical/cutoff payload in the committed snapshot")
    if path.startswith("/markets/orderbooks"):
        raw = params.get("tickers")
        # The regression this pins: a comma-joined string is what produced the silent empties.
        if isinstance(raw, str):
            raise AssertionError("GET /markets/orderbooks was queried with a comma-joined "
                                 f"tickers string ({raw[:60]}…); it must be a repeated list")
        want = list(raw or [])
        books = [{"ticker": t, "orderbook_fp": {
            "yes_dollars": [["0.4800", "900.00"], ["0.4900", "150.00"]],
            "no_dollars": [["0.5000", "800.00"]]}} for t in want[:3]]
        # An entry nobody asked for (the shape the comma form returns) must be dropped, and an
        # absent ticker must not be manufactured into an empty book by the caller.
        books.append({"ticker": BOGUS, "orderbook_fp": {"yes_dollars": [], "no_dollars": []}})
        return {"orderbooks": books}, url
    raise AssertionError(f"unexpected request outside the snapshot: {path} {params}")


def query_form_check() -> list[str]:
    """Assert roi_scan.get() encodes a list param as repeated keys, the only form the
    order-book endpoint accepts."""
    seen: list[str] = []

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    orig = urllib.request.urlopen

    def fake(req, timeout=None):
        seen.append(req.full_url)
        return Resp(b'{"orderbooks": []}')

    urllib.request.urlopen = fake
    try:
        roi_scan.get("/markets/orderbooks", {"tickers": ["KXA-1", "KXB-2", "KXC-3"]})
    finally:
        urllib.request.urlopen = orig
    problems = []
    url = seen[0] if seen else ""
    if "tickers=KXA-1&tickers=KXB-2&tickers=KXC-3" not in url:
        problems.append(f"tickers must be repeated, got: {url}")
    if "%2C" in url or "," in url.split("?", 1)[-1]:
        problems.append(f"comma found in the query string (the silent-empty form): {url}")
    return problems


def main() -> int:
    if not SNAP.exists():
        print("skip: data/live/markets.json is not committed yet", file=sys.stderr)
        return 1
    doc = json.loads(SNAP.read_text())
    n_open = len(doc.get("open_markets") or [])
    if n_open == 0:
        print("skip: the committed snapshot has no open markets", file=sys.stderr)
        return 1

    problems = query_form_check()

    tmp = Path(tempfile.mkdtemp(prefix="kdscan"))
    # Deliberately no price_history.json: momentum is then null for every market, which is the
    # honest state when the retained history is stale, and it removes any dependence on another
    # task's data file.
    orig_get, orig_live = roi_scan.get, roi_scan.LIVE
    roi_scan.get = offline_get
    roi_scan.LIVE = tmp
    try:
        out = tmp / "roi.json"
        payload = roi_scan.build(validate_n=0, out_path=out)   # 0 = no candlestick replay (no network)
    except Exception as e:  # noqa: BLE001 - failing on any crash is the point of this test
        problems.append(f"SCAN CRASHED on the committed snapshot: {type(e).__name__}: {e}")
        payload = None
    finally:
        roi_scan.get, roi_scan.LIVE = orig_get, orig_live
    if payload is None:
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 1

    def yes(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    c = payload["counts"]
    yes(c["open_scanned"] == n_open, f"scanned {c['open_scanned']} open markets, snapshot has {n_open}")
    yes(c["open_in_scope"] > 0, "no open market was placed in a topic — the classifier, not the API, is at fault")

    # --- order-book plumbing
    st = payload.get("orderbook_fetch") or {}
    yes(st.get("requested") == c["open_in_scope"],
        f"books were requested for {st.get('requested')} markets but {c['open_in_scope']} are in scope")
    # The stub answers 3 requested tickers plus 1 bogus one per 100-ticker chunk, and the
    # snapshot's in-scope set spans several chunks: the counts must reflect that exactly.
    n_chunks = -(-st.get("requested", 0) // 100)
    yes(st.get("returned") == 3 * n_chunks,
        f"expected {3 * n_chunks} books (3 per chunk × {n_chunks}), got {st.get('returned')}")
    yes(st.get("unexpected_tickers") == n_chunks,
        f"{n_chunks} unrequested tickers must be counted and dropped, got {st.get('unexpected_tickers')}")
    yes(st.get("failed_chunks") == 0, f"no chunk should fail against the stub, got {st.get('failed_chunks')}")
    yes(all(t != BOGUS for t in (payload.get("picks") or [])), "a ticker nobody asked for leaked in")

    # --- the degenerate-quote branch, over every market that actually has it
    pinned = [r for r in doc["open_markets"]
              if (lambda v: v is not None and (v == 0.0 or v == 1.0))(RM.num(r.get("yes_ask_dollars")))]
    yes(len(pinned) > 0, "the snapshot no longer contains a 0.00/1.00 quote — this test has stopped covering the bug")
    model = RM.load_model()
    now_ms = RM.datetime_ms(doc["collected_at"])
    degenerate_reasons = 0
    for r in pinned:
        ctx = {"now_ms": now_ms, "momentum_dollars": None, "series_ticker": collect.series_of(r)}
        try:
            s = RM.score(r, model, None, ctx)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{r['ticker']}: model still raises {type(e).__name__}: {e}")
            continue
        e = s.get("entry") or {}
        if e:
            ok = (0.0 < float(e["entry"]) < 1.0 and float(e["cost"]) > 0
                  and isinstance(e.get("roi"), (int, float)) and math.isfinite(e["roi"]))
            if not ok:
                problems.append(f"{r['ticker']}: priced a degenerate side {e}")
        elif DEGENERATE in " ".join(s.get("reasons") or []):
            degenerate_reasons += 1
    yes(len(pinned) == 0 or degenerate_reasons > 0,
        "no pinned-quote market reported the degenerate-level reason: the branch is not being exercised")

    for key in ("picks", "near_misses", "unscoreable"):
        for p in payload[key]:
            e = p.get("entry") or {}
            if e:
                yes(0.0 < float(e["entry"]) < 1.0, f"{key} {p['ticker']} entry {e['entry']} not strictly inside (0,1)")
                yes(float(e["cost"]) > 0, f"{key} {p['ticker']} priced a side at cost {e['cost']!r}")
                for f in ("roi", "ev"):
                    yes(isinstance(e.get(f), (int, float)) and math.isfinite(e[f]),
                        f"{key} {p['ticker']}.{f} is {e.get(f)!r}, not a finite number")
            sc = p.get("score")
            yes(sc is None or math.isfinite(float(sc)), f"{key} {p['ticker']}.score is {sc!r}")
            yes(str(p.get("source", "")).startswith("https://"), f"{key} {p['ticker']} has no https source")
            if key == "picks":
                yes(bool(p.get("eligible")) and not (p.get("fails") or []), f"{p['ticker']} is a pick but gated")
    for a in payload["alerts"]:
        yes(abs(float(a["delta"])) + 1e-9 >= payload["model"]["swing_threshold_dollars"],
            f"alert {a.get('ticker')}@{a.get('t')} is below the threshold")
    yes(json.dumps(payload.get("disclaimers")) not in ("[]", "null"), "disclaimers must be present")

    v = subprocess.run([sys.executable, str(ROOT / "scripts" / "tests" / "validate_roi.py"), str(out)],
                       capture_output=True, text=True)
    yes(v.returncode == 0, f"validate_roi.py refused the scan:\n{v.stderr.strip()}")

    if problems:
        print("SNAPSHOT SCAN PROBLEMS:", file=sys.stderr)
        for p in problems[:25]:
            print("  -", p, file=sys.stderr)
        return 1
    print(f"OK: roi_scan ran over {n_open} real demo markets ({c['open_in_scope']} in scope, "
          f"{len(pinned)} with a pinned 0.00/1.00 quote), query form verified as repeated tickers=, "
          f"{st['returned']} of {st['requested']} books returned with {st['unexpected_tickers']} "
          f"unrequested ticker(s) dropped, {c['picks']} picks / {c['near_misses']} near misses / "
          f"{c['unscoreable']} unpriced, {degenerate_reasons} degenerate-level reason(s), every ROI "
          f"finite — validate_roi.py accepts the file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
