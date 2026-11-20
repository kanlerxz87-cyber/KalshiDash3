#!/usr/bin/env python3
"""Run the live-desk scan over the REAL committed API payload, with the network stubbed off.

Why this test exists: the scan (scripts/roi_scan.py, run by .github/workflows/desk.yml) had
never completed a run. On the demo data it died with `ZeroDivisionError: float division by
zero` — 127 of the 387 open in-scope markets in data/live/markets.json carry
`yes_ask_dollars = 0.0000`, so the YES side costs nothing and ROI = (win − cost) / cost is
undefined. Every fixture in scripts/tests/fixtures_roi_parity.json used round numbers that
avoided that state, so the pipeline that was supposed to publish the ROI model's output was
red for its whole existence while its own tests stayed green.

This test closes that gap by driving the actual scan over the actual snapshot rows the
collector captured from the official demo API — no network, no fabricated prices, and it is
the same code path the runner executes. It asserts the scan (a) completes, (b) prices nothing
with a zero cost or non-finite ROI, and (c) still passes scripts/tests/validate_roi.py.

Run: python3 scripts/tests/test_roi_scan_snapshot.py
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SNAP = ROOT / "data" / "live" / "markets.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "tests"))

import roi_scan  # noqa: E402
import roi_model as RM  # noqa: E402
import collect  # noqa: E402


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
    if path == "/historical/cutoff":
        # The snapshot does not hold this endpoint, and inventing a cutoff would be exactly
        # the fabrication the site forbids. RuntimeError is the path build() takes when the
        # API is unreachable: historical_cutoff stays null and the page shows it blank.
        raise RuntimeError("no /historical/cutoff payload in the committed snapshot")
    if path.startswith("/markets/orderbooks"):
        # No books in this file: depth is genuinely unknown for the scan here, which is the
        # state that must degrade to "gate not applied" rather than to "0 contracts".
        tickers = [t for t in (params.get("tickers") or "").split(",") if t]
        return {"orderbooks": [{"ticker": t,
                                 "orderbook_fp": {"yes_dollars": [], "no_dollars": []}} for t in tickers]}, url
    raise AssertionError(f"unexpected request outside the snapshot: {path} {params}")


def main() -> int:
    if not SNAP.exists():
        print("skip: data/live/markets.json is not committed yet", file=sys.stderr)
        return 1
    doc = json.loads(SNAP.read_text())
    n_open = len(doc.get("open_markets") or [])
    if n_open == 0:
        print("skip: the committed snapshot has no open markets", file=sys.stderr)
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="kdscan"))
    # Deliberately no price_history.json: momentum is then null for every market, which is
    # the honest state and also removes any dependence on another task's data file.
    orig_get, orig_live = roi_scan.get, roi_scan.LIVE
    roi_scan.get = offline_get
    roi_scan.LIVE = tmp
    try:
        out = tmp / "roi.json"
        payload = roi_scan.build(validate_n=0, out_path=out)   # 0 = no candlestick replay (no network)
    except Exception as e:  # noqa: BLE001 - the whole point is to fail on any crash
        print(f"SCAN CRASHED on the committed snapshot: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        roi_scan.get, roi_scan.LIVE = orig_get, orig_live

    problems: list[str] = []

    def yes(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    c = payload["counts"]
    yes(c["open_scanned"] == n_open, f"scanned {c['open_scanned']} open markets, snapshot has {n_open}")
    yes(c["open_in_scope"] > 0, "no open market was placed in a topic — the classifier, not the API, is at fault")

    # The rows that used to crash the scan must be scored, not skipped: run the model over
    # every one of them with the same inputs build() used, and require the stated reason.
    pinned = [r for r in doc["open_markets"]
              if (lambda v: v is not None and v == 0.0)(RM.num(r.get("yes_ask_dollars")))]
    yes(len(pinned) > 0, "the snapshot no longer contains a $0.00 ask — this test has stopped covering the bug")
    model = RM.load_model()
    now_ms = RM.datetime_ms(doc["collected_at"])
    crashes, missing_reason, bad_cost = [], [], []
    for r in pinned:
        ctx = {"now_ms": now_ms, "momentum_dollars": None, "series_ticker": collect.series_of(r)}
        try:
            s = RM.score(r, model, None, ctx)
        except Exception as e:  # noqa: BLE001
            crashes.append(f"{r['ticker']}: {type(e).__name__}: {e}")
            continue
        if "YES ask $0.00: cost zero, so ROI divides by zero — side left unpriced" not in " ".join(s.get("reasons") or []):
            missing_reason.append(str(r["ticker"]))
        en = s.get("entry") or {}
        if en and not (isinstance(en.get("cost"), (int, float)) and en["cost"] > 0
                       and isinstance(en.get("roi"), (int, float)) and math.isfinite(en["roi"])):
            bad_cost.append(f"{r['ticker']}: {en}")
    yes(not crashes, f"{len(crashes)} pinned markets still crash the model, e.g. {crashes[:2]}")
    yes(not missing_reason, f"{len(missing_reason)} pinned markets scored without stating why the side "
                            f"is unpriced, e.g. {missing_reason[:3]}")
    yes(not bad_cost, f"pinned markets produced an unpriceable side, e.g. {bad_cost[:3]}")

    for key in ("picks", "near_misses", "unscoreable"):
        for p in payload[key]:
            e = p.get("entry") or {}
            if e:
                yes(isinstance(e.get("cost"), (int, float)) and e["cost"] > 0,
                    f"{key} {p['ticker']} priced a side at cost {e.get('cost')!r}")
                for f in ("roi", "ev"):
                    v = e.get(f)
                    yes(isinstance(v, (int, float)) and math.isfinite(v),
                        f"{key} {p['ticker']}.{f} is {v!r}, not a finite number")
            yes(isinstance(p.get("score"), (int, float, type(None)))
                and (p.get("score") is None or math.isfinite(p["score"])),
                f"{key} {p['ticker']}.score is {p.get('score')!r}")
        if key == "picks":
            yes(all(p.get("eligible") for p in payload["picks"]), "a pick must be eligible")

    for a in payload["alerts"]:
        yes(abs(float(a["delta"])) + 1e-9 >= payload["model"]["swing_threshold_dollars"],
            f"alert {a.get('ticker')}@{a.get('t')} is below the threshold")

    # The same gate CI runs before committing the file must accept it.
    v = subprocess.run([sys.executable, str(ROOT / "scripts" / "tests" / "validate_roi.py"), str(out)],
                       capture_output=True, text=True)
    yes(v.returncode == 0, f"validate_roi.py refused the scan:\n{v.stderr.strip()}")
    yes(json.loads(out.read_text())["schema"] == 1, "payload schema must be 1")

    if problems:
        print("SNAPSHOT SCAN PROBLEMS:", file=sys.stderr)
        for p in problems[:25]:
            print("  -", p, file=sys.stderr)
        return 1
    print(f"OK: roi_scan ran over {n_open} real demo markets ({c['open_in_scope']} in scope, "
          f"{len(pinned)} with a pinned $0.00 ask), {c['picks']} picks, {c['near_misses']} near "
          f"misses, {c['unscoreable']} unpriced, {c['alerts']} swings — every ROI finite, "
          f"validate_roi.py accepts the file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
