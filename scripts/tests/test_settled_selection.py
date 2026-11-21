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


if __name__ == "__main__":
    sys.exit(main())
