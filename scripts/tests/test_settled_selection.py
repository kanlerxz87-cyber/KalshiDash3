#!/usr/bin/env python3
"""Fixture tests for the topic-fair settled-row selection and the historical backfill.

Why this file exists: the published resolution history used to be `rows[:200]` after one
global newest-first sort. 15-minute crypto markets settle dozens of times a day, so the
200 published rows were 198 crypto / 2 culture on the 2026-11-21 snapshot and three of the
five requested topics had no resolution history at all. The brief asks for events to be
tracked "until the events have resolved", with topics kept separate, so the cap is now
spent per topic. These tests pin that behaviour, and pin the /historical/markets request
shape to the parameters Kalshi documents.

Official sources:
  https://docs.kalshi.com/getting_started/historical_data
  https://docs.kalshi.com/api-reference/historical/get-historical-markets
  https://docs.kalshi.com/api-reference/market/get-markets

Run: python3 scripts/tests/test_settled_selection.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("collect", ROOT / "scripts/collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)

failures: list[str] = []
checks = 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        failures.append(msg)


def row(ticker, cat, ts, result="yes"):
    return {"ticker": ticker, "category_id": cat, "settlement_ts": ts, "result": result,
            "status": "finalized"}


# ---------------------------------------------------------------- select_settled
# Fixture shape taken from the real snapshot (2026-11-21T15:21:23Z): one high-frequency
# topic dominates, the other four settle rarely or not at all.
fixture = [row(f"KXBTC15M-{i:04d}", "crypto", f"2026-11-21T{10 + i // 60:02d}:{i % 60:02d}:00Z") for i in range(400)]
fixture += [row("KXAAAGASM-1", "gas", "2026-11-20T10:00:00Z")]
fixture += [row("KXPGATOUR-1", "golf", "2026-11-20T11:00:00Z")]
fixture += [row("KXELECTIRAN-1", "elections", "2026-07-01T15:24:15Z")]
fixture += [row("KXEMMYCSERIES-1", "culture", "2026-09-15T02:00:00Z")]

picked, split = collect.select_settled(fixture, cap=200)
per_cat = {}
for r in picked:
    per_cat[r["category_id"]] = per_cat.get(r["category_id"], 0) + 1
check(len(picked) == 200, f"cap honoured: expected 200 picked, got {len(picked)}")
check(set(per_cat) == {"crypto", "gas", "golf", "elections", "culture"},
      f"all five topics must survive the cap, got {sorted(per_cat)}")
check(per_cat.get("elections") == 1, "the single settled elections row must be published")
check(per_cat.get("gas") == 1 and per_cat.get("golf") == 1 and per_cat.get("culture") == 1,
      "each rare topic must keep all of its rows")
check(per_cat.get("crypto") == 196, f"crypto takes leftover capacity (expected 196, got {per_cat.get('crypto')})")
check(sum(split.values()) == 200, f"published split must sum to the cap, got {split}")
check(split.get("elections") == 1, "the published split must name elections, so the allocation is auditable")

# newest-first inside the published set, so the page's own sort still reads correctly
ts = [r["settlement_ts"] for r in picked]
check(ts == sorted(ts, reverse=True), "published set must stay newest-first")

# a topic shortfall must not block the others (no infinite loop, no padding with duplicates)
only_two = [row("A-1", "gas", "2026-11-20T10:00:00Z"), row("B-1", "gas", "2026-11-20T09:00:00Z")]
picked2, split2 = collect.select_settled(only_two, cap=200)
check(len(picked2) == 2, f"short input returns what exists, got {len(picked2)}")
check(len({r['ticker'] for r in picked2}) == 2, "no duplicate rows when there is not enough history")

# empty input
picked3, split3 = collect.select_settled([], cap=200)
check(picked3 == [] and split3 == {}, "empty input returns nothing and no split")

# The old behaviour, reproduced to prove the test would have caught it.
old = sorted(fixture, key=lambda r: r["settlement_ts"], reverse=True)[:200]
check(sum(1 for r in old if r["category_id"] != "crypto") == 0,
      "the old global [:200] really does drop every non-crypto row (regression witness)")


# ---------------------------------------------------------------- historical_settled
# Stub the HTTP layer: prove the request uses exactly the documented parameters and that
# a failure is skipped, not raised (a historical hiccup must never fail a collection).
calls: list[tuple] = []
ARCHIVE = {"markets": [
    {"ticker": "KXELECTIRAN-26JUL01", "result": "no", "status": "finalized",
     "settlement_ts": "2026-07-01T15:24:15Z", "title": "Will Iran hold a presidential election before Jul 1, 2026?",
     "series_ticker": "KXELECTIRAN", "event_ticker": "KXELECTIRAN-26JUL01"},
    {"ticker": "KXELECTIRAN-OPENISH", "result": None, "status": "active"},  # no result yet -> refused
]}


def fake_get(path, params=None, retries=3):
    calls.append((path, dict(params or {})))
    if path == "/historical/markets":
        if params.get("series_ticker") == "BOOM":
            raise RuntimeError("HTTP 400 bad request")
        return ARCHIVE, "https://external-api.demo.kalshi.co/trade-api/v2" + path
    raise AssertionError(f"unexpected path {path}")


collect.get = fake_get
rows, report = collect.historical_settled(["KXELECTIRAN", "BOOM"], per_seed=10)

check(rows.get("KXELECTIRAN-26JUL01") is not None, "the archived settled elections market is kept")
check("KXELECTIRAN-OPENISH" not in rows, "a market without a result is not treated as resolved")
check(calls[0][0] == "/historical/markets", "the endpoint called is the documented historical one")
check(calls[0][1] == {"series_ticker": "KXELECTIRAN", "limit": collect.HISTORICAL_PAGE},
      f"request uses the documented series_ticker + limit params, got {calls[0][1]}")
check(collect.HISTORICAL_PAGE <= 1000, "limit must respect the documented maximum of 1000")
check(report["BOOM"].get("kept") == 0 and "error" in report["BOOM"],
      "a failing series is reported, not raised")
check(report["KXELECTIRAN"]["kept"] == 1 and report["KXELECTIRAN"]["returned"] == 2,
      "the report counts what the endpoint returned and what was kept")

# per_seed bound
many = {"markets": [{"ticker": f"T-{i}", "result": "yes"} for i in range(50)]}
collect.get = lambda path, params=None, retries=3: (many, "u")
bounded, _ = collect.historical_settled(["X"], per_seed=5)
check(len(bounded) == 5, f"per-seed bound honoured (expected 5, got {len(bounded)})")


if failures:
    print(f"FAIL: {len(failures)} of {checks} checks failed", file=sys.stderr)
    for f in failures:
        print(f"  - {f}", file=sys.stderr)
    sys.exit(1)
print(f"OK: topic-fair settled selection + historical backfill ({checks} checks)")
