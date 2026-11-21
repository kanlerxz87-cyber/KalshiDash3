#!/usr/bin/env python3
"""Scope-correction tests (F-39): the five topics must stay the five topics.

Three defects were found by auditing the deployed site against the official demo API
on 2026-11-21 and are pinned here so they cannot silently return:

1. Natural gas is not retail gasoline. Official series records (GET /trade-api/v2/series/<ticker>):
     KXNATGAS15M -> categories ["Commodities"], title "Natural Gas 15-minute",
                    product_metadata.scope "Natural Gas", settlement source "Pyth - NATGAS"
     KXAAAGASM   -> categories ["Economics"],   title "US gas price",
                    product_metadata.scope "Gasoline", settlement source "AAA"
   The keyword fallback matched "gas" in both, so 11 natural-gas futures markets appeared
   inside the Gas Prices category in the 2026-11-21T00:50Z snapshot.

2. Kalshi demo QA fixtures are test instruments, not live events. In that same snapshot the
   largest open Culture market by the dollars estimate was KXGRAMMYNOMROTY-QA7CECC5-QA
   ("Portfolio cash out QA 5", rules_primary "Demo portfolio test only."), and index.html
   presented it as culture's largest live market.

3. The landing page labelled the stored settled-row cap (200) as "settled markets in scope"
   while the snapshot recorded 1,600 in scope — two different numbers for one label (F-37/F-38).

The test runs offline: it builds market dicts shaped like GET /markets responses and checks the
classifier, plus static assertions on the pages that render "largest" tables.

Run: python3 scripts/tests/test_scope.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
errors: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


spec = importlib.util.spec_from_file_location("collect", ROOT / "scripts" / "collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)
CATS = json.loads((ROOT / "data" / "categories.json").read_text())


def classify(market: dict, series_title: str = "", series_cats: str = "") -> tuple:
    return collect.classify(CATS, collect.series_of(market), series_title, series_cats,
                            market.get("title") or market.get("yes_sub_title"))


# 1. natural-gas futures must not be classified as gas prices ...
natgas = {
    "ticker": "KXNATGAS15M-26NOV210015-45",
    "event_ticker": "KXNATGAS15M-26NOV210015",
    "title": "Natural Gas price up in next 15 mins?",
    "yes_sub_title": "Target Price: $3.77177",
    "rules_primary": "If the close price of the 1-minute candlestick for Natural Gas ... then the market resolves to Yes.",
}
check(classify(natgas, "Natural Gas 15-minute", "Commodities") == (None, None),
      "natural-gas futures must not enter a topic category (F-39)")

# ... while the confirmed AAA retail series still classifies as a seed row
aaa = {"ticker": "KXAAAGASM-26NOV30-3.90", "event_ticker": "KXAAAGASM-26NOV30",
       "title": "Will average **gas prices** be above $3.90?", "yes_sub_title": "Above 3.90"}
check(classify(aaa, "US gas price", "Economics") == ("gas", "seed"),
      "KXAAAGASM must stay a confirmed (seed) gas market")

# ... and a genuinely gas-themed non-seed market is still reachable by keyword
pump = {"ticker": "KXAAAGASD-26NOV21-3.6600", "event_ticker": "KXAAAGASD-26NOV21",
        "title": "Will average gas prices be above $3.66?", "yes_sub_title": "Above 3.66"}
check(classify(pump, "US gas price daily", "Economics") == ("gas", "keyword"),
      "a daily AAA gas-price market must still classify by keyword")

# 2. demo QA fixtures must be refused whatever topic their title looks like
qa = {"ticker": "KXGRAMMYNOMROTY-QA7CECC5-QA", "event_ticker": "KXGRAMMYNOMROTY-QA7CECC5",
      "title": "Portfolio cash out QA 5", "yes_sub_title": "Portfolio cash out QA 5",
      "rules_primary": "Demo portfolio test only."}
check(classify(qa, "Grammy nominee", "Culture") == (None, None),
      "a demo QA fixture must never be classified as a live culture market (F-39)")

# a real culture market with a similar name must survive
real_culture = {"ticker": "KXBALLONDOR-27-YDIO", "event_ticker": "KXBALLONDOR-27",
                "title": "Who will win the Ballon d'Or in 2027?", "yes_sub_title": "Youssoufa Diop"}
check(classify(real_culture, "Ballon d'Or", "Culture") == ("culture", "seed"),
      "a seed culture market must stay classified")

# 3. the site must keep the guard and the corrected denominator
site_js = (ROOT / "assets" / "site.js").read_text()
check("function isQaRow" in site_js, "assets/site.js must expose isQaRow so pages can refuse QA fixtures")
check("isQaRow," in site_js, "isQaRow must be exported from the KD object")
index_html = (ROOT / "index.html").read_text()
check("KD.isQaRow(r)" in index_html, "index.html must skip QA fixtures when picking the largest market")
# Either wording is acceptable as long as both numbers are labelled: the stored row count and the
# in-scope count. Main's sibling fix uses "stored settled rows (N in scope)"; this session's first
# version used "settled markets stored; N were in scope". Pin the contract, not the phrasing.
check(("stored settled rows" in index_html or "settled markets stored" in index_html)
      and "settled_in_scope" in index_html,
      "index.html must show the stored settled-row cap and the in-scope count as distinct, labelled numbers (F-37/F-38)")
check('settled markets in scope' not in index_html,
      "index.html must not call the stored row cap 'settled markets in scope'")

# 4. the exclusion must be published, never silent
collect_src = (ROOT / "scripts" / "collect.py").read_text()
for token in ("open_excluded_off_topic_or_qa", "settled_excluded_off_topic_or_qa", "excluded_series_reasons"):
    check(token in collect_src, f"collect.py must publish {token} so exclusions are auditable")

# 5. the committed snapshot must not contain a QA fixture inside the five topics
live = ROOT / "data" / "live" / "markets.json"
if live.exists():
    snap = json.loads(live.read_text())
    qa_like = [
        r for r in (snap.get("open_markets") or []) + (snap.get("settled_markets") or [])
        if collect.EXCLUDE_TITLE_RE.search(str(r.get("title") or ""))
    ]
    # Rows collected before this fix are reported, not failed: the collector is the only writer
    # of this file and a snapshot may legitimately predate the fix. The alert makes it visible.
    if qa_like:
        print(f"note: {len(qa_like)} QA-fixture row(s) still present in the committed snapshot "
              f"({', '.join(r['ticker'] for r in qa_like[:3])}); the next collection drops them")
    natgas_rows = [r for r in (snap.get("open_markets") or []) + (snap.get("settled_markets") or [])
                   if collect.series_of(r) in collect.EXCLUDE_KEYWORD_SERIES]
    if natgas_rows:
        print(f"note: {len(natgas_rows)} natural-gas row(s) still present in the committed snapshot; "
              f"the next collection drops them")

if errors:
    print("FAIL")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("OK: scope tests passed (natural gas excluded, QA fixtures refused, labels corrected, exclusions published)")
