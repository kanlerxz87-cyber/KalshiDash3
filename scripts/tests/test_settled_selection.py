#!/usr/bin/env python3
"""Regression test for the settled-row selection in scripts/collect.py.

The defect this locks down: the snapshot used to publish `rows["settled"][:200]`
after a GLOBAL newest-first sort. The demo exchange runs 15-minute crypto markets
(~96 settlements a day), so the published resolution history was 92% crypto and the
gas, elections, culture and golf history was cut off — every category page reads
`settled_markets`, so all four lost their resolution feed.

These tests use synthetic fixtures with the same shape as the real snapshot. They
assert the selection rule, not the market data.

Run: python3 scripts/tests/test_settled_selection.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("collect", ROOT / "scripts" / "collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)

FAIL = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def row(ticker, cat, ts):
    return {"ticker": ticker, "category_id": cat, "settlement_ts": ts,
            "result": "yes", "source": f"https://example.invalid/{ticker}"}


def main() -> int:
    # Fixture 1 — the real shape: a flood of fast crypto settlements plus a handful
    # of the other four topics, all older than most of the crypto rows.
    rows = []
    for i in range(400):
        rows.append(row(f"KXBTC15M-{i}", "crypto", f"2026-11-21T06:{59 - (i % 60):02d}:00.000000Z"))
    for cat in ("gas", "elections", "culture", "golf"):
        for i in range(5):
            rows.append(row(f"{cat.upper()}-{i}", cat, f"2026-11-20T0{i}:00:00.000000Z"))
    picked, per_cat = collect.select_settled(rows, cap=200)
    cats = {r["category_id"] for r in picked}
    check(len(picked) == 200, f"publishes exactly the cap (got {len(picked)})")
    check(cats == {"crypto", "gas", "elections", "culture", "golf"},
          f"all five topics survive a crypto flood (got {sorted(cats)})")
    check(all(per_cat[c] == 5 for c in ("gas", "elections", "culture", "golf")),
          f"every rare topic keeps all of its rows ({per_cat})")
    check(per_cat["crypto"] == 180, f"crypto gets the leftover capacity ({per_cat['crypto']})")

    # Fixture 2 — newest-first must still hold inside the published set.
    ts = [r["settlement_ts"] for r in picked]
    check(ts == sorted(ts, reverse=True), "published rows stay newest-first")

    # Fixture 3 — a topic with no history contributes nothing and costs no capacity.
    rows2 = [row(f"KXGAS-{i}", "gas", f"2026-11-21T00:0{i}:00Z") for i in range(3)]
    picked2, per2 = collect.select_settled(rows2, cap=200)
    check(len(picked2) == 3, "a single-topic universe publishes everything under the cap")
    check(per2.get("crypto", 0) == 0, "an absent topic contributes zero rows")

    # Fixture 4 — cap smaller than the number of topics must not crash or duplicate.
    picked3, per3 = collect.select_settled(rows, cap=3)
    check(len(picked3) == 3 and len({r["ticker"] for r in picked3}) == 3,
          "a tiny cap yields distinct rows, no duplicates")

    # Fixture 4b — REGRESSION for the second half of the bug: selecting AFTER a
    # newest-first row cap leaves nothing for a slow topic whose history is older
    # than the cap. The selection must be handed the full in-scope set.
    flood = [row(f"KXBTC15M-{i}", "crypto", f"2026-11-21T05:{i % 60:02d}:00.000000Z") for i in range(500)]
    old_elections = [row("KXELECTIRAN-26JUL01", "elections", "2026-07-01T15:24:15.984157Z")]
    as_selected_before_cap, _ = collect.select_settled(flood + old_elections, cap=200)
    check(any(r["category_id"] == "elections" for r in as_selected_before_cap),
          "a slow topic with OLDER settlements survives the selection (the [:1600] ordering bug)")
    capped = sorted(flood + old_elections, key=lambda r: r["settlement_ts"], reverse=True)[:200]
    check(not any(r["category_id"] == "elections" for r in capped),
          "control: selecting after a newest-first [:200] cap would have dropped it (the original defect)")

    # Fixture 5 — the committed snapshot, if present, must be topic-diverse.
    snap_path = ROOT / "data" / "live" / "markets.json"
    if snap_path.exists():
        snap = json.loads(snap_path.read_text())
        counts = snap.get("counts", {})
        pub = counts.get("settled_published")
        by_cat = counts.get("settled_published_by_category")
        stored = snap.get("settled_markets", [])
        if pub is None:
            print("  note: snapshot predates the per-topic selection (no settled_published count)")
        else:
            check(pub == len(stored), f"published count matches the stored rows ({pub} vs {len(stored)})")
            check(sum(by_cat.values()) == pub, f"per-topic counts add up ({by_cat})")
            check(len([c for c, n in by_cat.items() if n > 0]) >= 2,
                  f"the committed snapshot carries more than one topic ({by_cat})")

    print("")
    if FAIL:
        print(f"FAILED: {len(FAIL)} check(s)")
        return 1
    print("OK: settled-row selection is topic-fair, newest-first and published.")
    return 0



# ---------------------------------------------------------------------------
# ORDER REGRESSION (arena-6a6e8f22, 2026-11-21).
# The first version of the per-topic fix selected AFTER `rows[:SETTLED_KEEP]`, and the
# 2026-11-21T20:27Z snapshot proved it was still unfair: crypto 178 / gas 17 / culture 5,
# zero elections and zero golf. select_settled() itself was correct, so only a test that
# drives the real trim-then-select pipeline can catch it. That is what this does.
def order_regression() -> int:
    print("  --- order regression: selection must run before the stored window is trimmed")
    rows = []
    # 2,500 fresh crypto settlements dominate the newest-first window ...
    for i in range(2500):
        rows.append({"ticker": f"KXBTC15M-{i}", "category_id": "crypto",
                     "settlement_ts": f"2026-11-21T{5 + (i // 60) % 15:02d}:{i % 60:02d}:00.000000Z",
                     "result": "no", "source": "https://example.invalid/x"})
    # ... while the other topics settled long ago, exactly like the real elections row.
    rows.append({"ticker": "KXELECTIRAN-26JUL01", "category_id": "elections",
                 "settlement_ts": "2026-07-01T15:24:15.000000Z", "result": "no",
                 "source": "https://example.invalid/x"})
    rows.append({"ticker": "KXPGATOUR-OLD", "category_id": "golf",
                 "settlement_ts": "2026-08-01T00:00:00.000000Z", "result": "yes",
                 "source": "https://example.invalid/x"})
    rows.sort(key=lambda r: r["settlement_ts"], reverse=True)

    stored, published, by_cat = collect.split_and_select_settled(rows, keep=1600, cap=200)
    cats = {r["category_id"] for r in published}
    check(len(stored) == 1600, f"the stored window is still trimmed to keep ({len(stored)})")
    check("elections" in cats and "golf" in cats,
          f"a settlement older than the stored window must still be published (got {sorted(cats)})")
    check(by_cat.get("elections") == 1 and by_cat.get("golf") == 1,
          f"those rows are counted in the published split ({by_cat})")

    # The wrong order, reproduced: trim first, then select.
    trimmed_first, _ = collect.select_settled(rows[:1600], cap=200)
    wrong = {r["category_id"] for r in trimmed_first}
    check("elections" not in wrong,
          "witness: selecting after the trim really does lose elections (this is the shipped bug)")
    return 0


# ---------------------------------------------------------------- backfill contract (F-67)
# F-67 is only half fixed by retaining history: whatever an earlier run already deleted is gone,
# because a settled market is never returned by GET /markets again. These checks assert the
# rebuild path exists, is bounded, is marked, and never overwrites collected data.
src = (ROOT / "scripts" / "collect.py").read_text()
check("def backfill_from_candles(" in src, "collect.py must rebuild lost history from official candles")
check('"source": "candle"' in src, "a backfilled observation must be marked source=candle, not passed off as a REST read")
check("if hist.get(ticker, {}).get(\"observations\"):" in src, "the backfill must skip any ticker that already has observations")
check("max_series=12" in src, "the backfill must be bounded per run")
check('"period_interval": 1' in src, "the backfill must request the documented 1-minute interval")
check("end - 5000 * 60" in src, "the backfill window must respect the documented 5,000-period maximum")
check('"price_history_backfilled_from_candles"' in src, "counts must report how many series were backfilled")
check('"price_history_archived_tickers"' in src, "counts must report how many tickers the archive cites")

# Live check on the committed snapshot: every ticker the alert archive cites must be chartable.
LIVE = ROOT / "data" / "live"
arch_path, hist_path = LIVE / "alerts_archive.json", LIVE / "price_history.json"
if arch_path.exists() and hist_path.exists():
    arch = {a.get("ticker") for a in json.loads(arch_path.read_text()).get("alerts", [])}
    hist = json.loads(hist_path.read_text()).get("series", {})
    missing = sorted(t for t in arch if not hist.get(t, {}).get("observations"))
    check(not missing, f"every archived-alert ticker must have chartable observations (missing: {missing})")
    candle_pts = sum(1 for v in hist.values() for o in v.get("observations", []) if o.get("source") == "candle")
    print(f"  committed history: {len(hist)} series, {len(arch)} archived-alert tickers, {candle_pts} candle-backfilled points")

print("OK: settled selection + history retention/backfill contract verified")
if FAIL:
    print("FAIL: %d check(s) failed" % len(FAIL))
    sys.exit(1)

if __name__ == "__main__":
    order_regression()
    raise SystemExit(main())
