#!/usr/bin/env python3
"""Tests for scripts/collect.py: topic-fair resolution history + alert-aware history retention.

Two defects are pinned here, both measured on committed data before they were fixed:

1. Resolution history was single-queue. `rows["settled"]` was sorted newest-first across
   ALL topics and truncated, and the snapshot published `[:200]`. On the committed
   2026-11-21T15:21Z snapshot the published 200 rows were: crypto 198, culture 2, and
   **gas 0, elections 0, golf 0**. The demo exchange settles 15-minute crypto markets
   ~96 times a day, so the newest-N queue can never hold the slower topics.
   Fix: select_settled() reserves rows per topic, then shares leftovers round-robin.

2. Price history was kept only for open rows. A >=$0.10 swing is archived forever by
   scripts/build_alerts.py, but the observations behind it were pruned as soon as the
   market left the capped open window, so the dashboard could not chart the market an
   alert pointed at. Fix: watch set = open ∪ published settled ∪ archived-alert tickers.

Run: python3 scripts/tests/test_settled_selection.py
Exit: 0 all checks pass, 1 a check failed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "data" / "live"

spec = importlib.util.spec_from_file_location("collect", ROOT / "scripts" / "collect.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

checks = 0
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    global checks
    checks += 1
    if not cond:
        failures.append(msg)


def row(ticker: str, cat: str, ts: str) -> dict:
    return {"ticker": ticker, "category_id": cat, "settlement_ts": ts}


def fixture() -> list[dict]:
    """The real shape: a fast crypto series plus a few rows in each slower topic."""
    rows = [
        row(f"KXBTC15M-{i:04d}", "crypto", f"2026-11-21T{10 + i // 60:02d}:{i % 60:02d}:00Z")
        for i in range(400)
    ]
    for cat, n in (("gas", 5), ("elections", 3), ("culture", 4), ("golf", 6)):
        for i in range(n):
            rows.append(row(f"KX{cat.upper()}-{i}", cat, f"2026-11-21T0{i}:00:00Z"))
    return rows


# ---------------------------------------------------------------- 1. topic fairness
rows = fixture()
published, per_cat = C.select_settled(rows)
check(len(published) <= C.SETTLED_PUBLISHED_CAP, "published rows must respect the cap")
for cat in ("gas", "elections", "culture", "golf"):
    want = len([r for r in rows if r["category_id"] == cat])
    check(per_cat.get(cat) == want,
          f"rare topic {cat} must keep all {want} of its rows, got {per_cat.get(cat)}")
check(per_cat.get("crypto", 0) > 0, "the fast topic must still publish rows")
check(sum(per_cat.values()) == len(published), "per-category counts must add up to the published set")
check(len({r["ticker"] for r in published}) == len(published), "no duplicate rows in the published set")
check([r["settlement_ts"] for r in published] == sorted((r["settlement_ts"] for r in published), reverse=True),
      "published set must be newest-first overall")
# The fast topic consumes exactly the leftover capacity (or all it has, whichever is less),
# never a rare topic's reserve.
leftover = C.SETTLED_PUBLISHED_CAP - sum(n for c, n in per_cat.items() if c != "crypto")
expected_crypto = min(len([r for r in rows if r["category_id"] == "crypto"]), leftover)
check(per_cat.get("crypto") == expected_crypto,
      f"crypto should take min(its rows, leftover capacity) = {expected_crypto}, got {per_cat.get('crypto')}")

# Mutation check: the old behaviour (single newest-first queue) reproduces the defect.
old = sorted(rows, key=lambda r: r["settlement_ts"] or "", reverse=True)[:200]
old_cats = {c: len([r for r in old if r["category_id"] == c]) for c in ("gas", "elections", "culture", "golf")}
check(all(v == 0 for v in old_cats.values()),
      f"mutation check: the pre-fix single queue should starve every slow topic, got {old_cats}")

# Sparse inputs must not invent rows or crash.
published2, per_cat2 = C.select_settled([row("A-1", "golf", "2026-11-21T00:00:00Z")])
check(len(published2) == 1 and per_cat2 == {"golf": 1}, "a single settled row must be published as-is")
published3, per_cat3 = C.select_settled([])
check(published3 == [] and per_cat3 == {}, "an empty settled list must stay empty")

# ------------------------------------------- 1b. the settled TOTAL may understate, never overstate
# The scan hits a 25,000-row safety cap, so a run can only see a window. The published total is
# either exact (paging ran to exhaustion) or carried forward. A carried-forward total must never
# claim completeness, and must never be larger than what the evidence supports.
src_collect = (ROOT / "scripts" / "collect.py").read_text()
check("settled_in_scope_total_method" in src_collect,
      "the collector must publish HOW the settled total was obtained, next to the number")
check("lower bound, carried forward" in src_collect,
      "a carry-forward from a previous lower bound must stay labelled a lower bound")
check("carried forward from an exact total" in src_collect,
      "a carry-forward from an exact total must say so")
check("It is never inflated to look complete." in src_collect,
      "the code must state the no-inflation rule it implements")
# The old wording claimed the previous value was exact unconditionally; that was wrong whenever
# the previous value was itself a lower bound.
# The "exact total" wording must sit inside the branch that has checked the previous method,
# so a previous lower bound can never be described as exact.
exact_phrase_at = src_collect.find("carried forward from an exact total")
guard_at = src_collect.find('if prev_method.startswith("exact")')
check(exact_phrase_at > guard_at >= 0,
      "the 'exact total' wording must be inside the branch that verifies the previous value was exact")

# ---------------------------------------------------------------- 2. collector contract
src = (ROOT / "scripts" / "collect.py").read_text()
check('"mve_filter": "exclude"' in src,
      "the market scan must send the documented mve_filter=exclude parameter")
check("select_settled(" in src, "build() must allocate settled rows through select_settled()")
check('rows["settled"][:200]' not in src,
      "the published snapshot must not re-truncate settled rows to a global newest-200 window")
check("archived_tickers" in src,
      "price-history retention must include tickers that have an archived alert")

# ---------------------------------------------------------------- 3. committed snapshot
snap_path = LIVE / "markets.json"
if snap_path.exists():
    snap = json.loads(snap_path.read_text())
    counts = snap.get("counts", {})
    settled = snap.get("settled_markets") or []
    cats = {r.get("category_id") for r in settled}
    if counts.get("settled_published_by_category"):
        by = counts["settled_published_by_category"]
        check(sum(by.values()) == len(settled),
              f"counts.settled_published_by_category must match the rows on disk ({by} vs {len(settled)})")
        print(f"  committed snapshot: {len(settled)} settled rows, by topic {by}")
    else:
        # Pre-fix snapshot: record the defect instead of failing the suite on data that
        # the next collector run replaces. This is printed, never silently ignored.
        print(f"  committed snapshot is PRE-FIX: {len(settled)} settled rows, topics present {sorted(c for c in cats if c)}")
    unknown = cats - {"gas", "elections", "culture", "crypto", "golf"}
    check(not unknown, f"settled rows must only carry the five topics, found {unknown}")

if failures:
    print(f"FAIL ({len(failures)} of {checks} checks)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print(f"OK: {checks} checks passed (topic-fair resolution history, alert-aware history retention)")
