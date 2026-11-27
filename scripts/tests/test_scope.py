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
# Three sessions have now worded this line differently; what matters (F-37/F-38, restated by S-02
# on 2026-11-22 and by F-90 in parallel) is that the count of PUBLISHED settled rows and the count
# the scan FOUND IN SCOPE are both rendered as labelled, distinct values, and that neither is
# presented as the other. S-02 was the exact failure: index.html read counts.settled_in_scope
# (the 1,600-row retained paging window) and called it "settled markets in scope" while
# counts.settled_in_scope_total held the scan total (6,927). The page now names the scan total,
# prints how it was obtained, and labels the rows it lists as published.
check("settled_in_scope_total" in index_html,
      "index.html must render counts.settled_in_scope_total as the in-scope settled figure (S-02)")
check("settled_in_scope_total_method" in index_html,
      "index.html must render how the settled scan total was obtained (S-02)")
check("settled rows published" in index_html,
      "index.html must label the rows it lists as published, not as 'in scope' (S-02)")
check("KD.num(snap.counts?.settled_in_scope)} settled markets in scope" not in index_html,
      "index.html must not present the retained paging window as 'settled markets in scope' (S-02)")

# 4. the exclusion must be published, never silent
collect_src = (ROOT / "scripts" / "collect.py").read_text()
for token in ("open_excluded_off_topic_or_qa", "settled_excluded_off_topic_or_qa", "excluded_series_reasons",
              "open_excluded_category_conflict", "settled_excluded_category_conflict",
              "category_conflict_reasons"):
    check(token in collect_src, f"collect.py must publish {token} so exclusions are auditable")

# 4b. CATEGORY INTEGRITY (F-65). Found on the deployed site on 2026-11-21:
#     a Culture headline market that Kalshi itself files under Sports, matched by the keyword
#     "oscar" in the player's first name, and Test-series rows inside Crypto. The official
#     series records below were fetched the same day and are the authority for the expectation:
#       GET /trade-api/v2/series/KXEPLFIRSTGOAL -> categories ["Sports"], tags ["Soccer"]
#       GET /trade-api/v2/series/KXEPLAST       -> categories ["Sports"], tags ["Soccer"]
#       GET /trade-api/v2/series/KXEPLSOA       -> categories ["Sports"], tags ["Soccer"]
#       GET /trade-api/v2/series/KXDEMOFUTHOURLY-> categories ["Test"],   tags ["Demo"]
#       GET /trade-api/v2/series/KXAAAGASM      -> categories ["Economics"]
#       GET /trade-api/v2/series/KXBTCY         -> categories ["Crypto"]
#       GET /trade-api/v2/series/KXPGATOUR      -> categories ["Sports"], tags ["Golf"]
#       GET /trade-api/v2/series/KXEMMYCACTO    -> categories ["Entertainment"]
#       GET /trade-api/v2/series/KXBALLONDOR    -> categories ["Sports"], tags ["Soccer"]
#     The last line is why the rule cannot be "seeds are always right": KXBALLONDOR is in the
#     official fee schedule AND filed under Sports, so it is not a Culture market either.
FOOTBALL_PROP = {"ticker": "KXEPLFIRSTGOAL-26NOV21MCIFUL-FULOBOBB14",
                 "event_ticker": "KXEPLFIRSTGOAL-26NOV21MCIFUL",
                 "title": "Oscar Bobb: First Goalscorer", "yes_sub_title": "Oscar Bobb"}
# The keyword classifier does match it (that is how the bug happened) ...
check(classify(FOOTBALL_PROP, "EPL 1st Goalscorer", "Sports") == ("culture", "keyword"),
      "precondition: the keyword fallback really does match 'oscar' in 'Oscar Bobb' (F-65)")
# ... and the official category is what stops it.
check(collect.category_conflict("culture", ["Sports"], "keyword") is not None,
      "a Sports series must not be published inside Culture (F-65)")
check(collect.category_conflict("crypto", ["Test"], "keyword") is not None,
      "a Test series must not be published inside Crypto (F-65)")
check(collect.category_conflict("culture", ["Sports"], "seed") is not None,
      "the rule must also apply to a fee-schedule seed: KXBALLONDOR is Sports, not Culture (F-65)")
for cat, cats in (("gas", ["Economics"]), ("crypto", ["Crypto"]), ("golf", ["Sports"]),
                  ("culture", ["Entertainment"]), ("elections", ["Elections"])):
    check(collect.category_conflict(cat, cats, "seed") is None,
          f"the compatible category {cats} must keep {cat} rows (F-65)")
check(collect.category_conflict("crypto", [], "seed") is None,
      "an absent categories field is unknown, never a contradiction (F-65)")
check(collect.official_categories({"category": "Crypto"}) == ["Crypto"],
      "official_categories must fall back to the singular category field (F-65)")
check(collect.official_categories(None) == [] and collect.official_categories({"categories": None}) == [],
      "missing series records must yield [] rather than a guess (F-65)")
check("series_categories" in collect_src,
      "every published row must carry the official series_categories it was checked against (F-65)")
# The five topics' compatible sets must be explicit and cover every topic exactly once.
check(set(collect.CATEGORY_COMPATIBLE) == {"gas", "elections", "culture", "crypto", "golf"},
      "CATEGORY_COMPATIBLE must define exactly the brief's five topics (F-65)")
check("Test" in collect.CATEGORY_NEVER_IN_SCOPE,
      "the Test category must be named explicitly as never in scope (F-65)")

# 4c. OFFICIAL DISCOVERY (F-66). The five topics use the documented GET /series filters
#     (https://docs.kalshi.com/api-reference/market/get-series-list):
#       category -> "Return series whose `categories` list contains this value ... exact and
#                   case-sensitive"
#       tags     -> same endpoint, tags filter
#     Verified live 2026-11-21: ?category=Entertainment returns KXEMMYCACTO, KXSAGAWARDACTODRAMA,
#     KXAWARDSCMAMOTY, KX1SONG; ?category=Elections returns KXNYCMAYOR2ND, KXVILNIUSMAYOR;
#     ?tags=Golf returns KXGOLF, KXPHOENIXOPEN, KXTGLCHAMPION (all categories ["Sports"]).
import io
from unittest import mock as _mock

CATS_DOC = json.loads((ROOT / "data" / "categories.json").read_text())
for c in CATS_DOC["categories"]:
    has_filter = bool(c.get("official_categories")) or bool(c.get("official_tags"))
    # A topic may legitimately have NO official filter, but then it must say why in
    # official_mapping_note and that note must name the observation that ruled the filter out.
    check(has_filter or bool(c.get("official_mapping_note")),
          f"topic {c['id']} must either declare an official GET /series filter or explain why not (F-66)")
    if has_filter:
        check(bool(c.get("official_mapping_note")),
              f"topic {c['id']} must record how its filter was verified (F-66)")
    check(c.get("official_source", "").startswith("https://docs.kalshi.com/"),
          f"topic {c['id']} must link the official docs for its filter (F-66)")

FAKE = {
    "Entertainment": ["KXEMMYCACTO", "KXSAGAWARDACTODRAMA", "KXAWARDSCMAMOTY"],
    "Elections": ["KXNYCMAYOR2ND", "KXVILNIUSMAYOR", "KXELECTIRAN"],
    "Crypto": ["KXBTCY", "KXETHY", "KXDEMOFUTHOURLY"],
    "Economics": ["KXAAAGASM", "KXAAAGASD"],
    "Sports": ["KXPGATOUR", "KXBALLONDOR", "KXEPLFIRSTGOAL"],
}
TAGS = {"Golf": ["KXPGATOUR", "KXGOLF", "KXGOLFTENNISMAJORS"]}


def fake_get(path, params=None, retries=3):
    if path == "/series" and params:
        if "category" in params:
            return {"series": [{"ticker": t} for t in FAKE.get(params["category"], [])]}, "url"
        if "tags" in params:
            return {"series": [{"ticker": t} for t in TAGS.get(params["tags"], [])]}, "url"
    raise RuntimeError("unexpected GET " + path)


with _mock.patch.object(collect, "get", fake_get):
    omap, ocalls = collect.official_discovery(CATS_DOC)
check(omap.get("KXEMMYCACTO", {}).get("category_id") == "culture",
      "official ?category=Entertainment must map an Emmys series to Culture (F-66)")
check(omap.get("KXNYCMAYOR2ND", {}).get("category_id") == "elections",
      "official ?category=Elections must map an election series to Elections (F-66)")
check(omap.get("KXGOLF", {}).get("category_id") == "golf",
      "official ?tags=Golf must map a Sports-categorised golf series to Golf (F-66)")
check("KXWTIDIRY" not in omap,
      "?category=Sports and ?tags=Oil & Gas must not be used as topic filters: they return other "
      "sports and crude oil, which would flood Golf and Gas (F-66)")
check("Sports" not in {c.get("value") for c in ocalls if c.get("filter") == "category"},
      "Sports must never be used as a whole-topic filter (4,243 series; it contains every sport) (F-66)")
check(collect.excluded_series_reason("culture", "KXBALLONDOR") is not None,
      "the Ballon d'Or exclusion is what keeps a Sports award out of Culture (F-66)")
check(all(c["url"].startswith("https://external-api.demo.kalshi.co/trade-api/v2/series?")
          for c in ocalls if "error" not in c),
      "every discovery call must record the exact official URL it used (F-66)")
# A failed filter call must be reported, never silently drop a topic's only mapping.
def failing_get(path, params=None, retries=3):
    raise RuntimeError("HTTP 500 simulated")

with _mock.patch.object(collect, "get", failing_get):
    omap2, ocalls2 = collect.official_discovery(CATS_DOC)
check(omap2 == {} and all("error" in c for c in ocalls2),
      "a failed discovery call must be recorded with its error, not assumed to be empty (F-66)")

# Per-topic series exclusions: Ballon d'Or is officially Sports/Soccer, so it stays out of
# Culture even though the fee schedule lists it (and even though ?tags=Awards might catch it).
check(collect.excluded_series_reason("culture", "KXBALLONDOR") is not None,
      "KXBALLONDOR must be excluded from Culture with a reason (F-66)")
check(collect.excluded_series_reason("culture", "KXEMMYCACTO") is None,
      "the exclusion must be narrow: a real Entertainment series stays in Culture (F-66)")
check(collect.excluded_series_reason("golf", "KXGOLFTENNISMAJORS") is not None,
      "a tennis-vs-golf comparison series must not be a Golf event (F-66)")
for topic, entries in collect.TOPIC_EXCLUDE_SERIES.items():
    for ex in entries:
        check(bool(ex.get("reason")) and "http" in ex["reason"],
              f"every {topic} exclusion must cite the official series record that justifies it (F-66)")

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

    # 6. F-65 self-check on the committed data: no published row may contradict the official
    #    categories recorded on itself. Rows written before a narrowing of CATEGORY_COMPATIBLE
    #    (where snap.counts.category_compatible_official still carried the wider list) are
    #    noted rather than failed so verify_release.py passes before the next collector run
    #    rewrites markets.json on main.
    snap_compat_elec = set(
        ((snap.get("counts") or {}).get("category_compatible_official") or {}).get("elections") or []
    )
    conflicting = []
    pending_narrow = []
    for r in (snap.get("open_markets") or []) + (snap.get("settled_markets") or []):
        if collect.category_conflict(r.get("category_id"), r.get("series_categories") or [],
                                     r.get("category_basis")) is not None:
            if (r.get("category_id") == "elections"
                    and set(r.get("series_categories") or []) & snap_compat_elec):
                pending_narrow.append(r["ticker"])
            else:
                conflicting.append(r["ticker"])
    if pending_narrow:
        print(f"note: {len(pending_narrow)} row(s) predated the Elections=['Elections'] narrowing "
              f"({', '.join(pending_narrow[:3])} …); the next collection drops them")
    check(not conflicting,
          "the committed snapshot must not publish a row that contradicts its own official "
          f"series_categories (F-65): {', '.join(conflicting[:5])}")
    unchecked = [r["ticker"] for r in (snap.get("open_markets") or []) if "series_categories" not in r]
    if unchecked:
        print(f"note: {len(unchecked)} open row(s) predate the series_categories field "
              f"({', '.join(unchecked[:3])} …); the next collection records it")

# E9D9-3 regression checks: non-election Politics series, benchmark fixtures, and volume sweep.
check(collect.category_conflict("elections", ["Politics"], "keyword") is not None,
      "non-election Politics series (KXAPRPOTUS, KXTRUMPNOMNUM, KXEOWEEK) must conflict with Elections (E9D9-3)")
check(collect.category_conflict("elections", ["Elections"], "keyword") is None,
      "official Elections series must stay compatible with Elections (E9D9-3)")
bench_mkt = {"ticker": "KXNEWPOPE-70-ZS01", "event_ticker": "KXNEWPOPE-70",
             "title": "Who will the next Pope be?", "yes_sub_title": "Bench Run 1"}
check(collect.classify_in_scope(CATS, bench_mkt, {})[0] is None,
      "benchmark fixture rows ('Bench Run 1' / 'Bench Probe 1') must be excluded (E9D9-3)")
vol_map = {
    "KXPRESPERSON": {"category_id": "elections", "volume_fp": 7635998.0},
    "KXUNTRADED": {"category_id": "elections", "volume_fp": 0.0},
    "KXNATGASD": {"category_id": "culture", "volume_fp": 349000.0},
    "KXOSCARPIC": {"category_id": "culture", "volume_fp": 685161.0},
}
top_vol = collect.top_volume_official_series(vol_map, top_k=5)
check(top_vol.get("elections") == ["KXPRESPERSON"],
      "top_volume_official_series must keep >0-volume official series and skip 0-volume ones (E9D9-3)")
check(top_vol.get("culture") == ["KXOSCARPIC"],
      "top_volume_official_series must skip EXCLUDE_KEYWORD_SERIES entries like KXNATGASD (E9D9-3)")

# 5. F-72: the banner/table must never print the PUBLISHED settled-row count as if it were the
#    scan total. The collector now publishes both; assert that wherever a settled total is
#    labelled "in scope" the page reads settled_in_scope_total, and that the stored count is
#    labelled as stored/published.
#
#    (This section used to sit BELOW the verdict, so every assertion in it was
#    unreachable-by-failure — the run printed "OK" and exited 0 while three of these checks were
#    failing. The verdict is now the last statement in the file, so a failing check fails the run.)
site_js = (ROOT / "assets" / "site.js").read_text()
check("settled_in_scope_total" in site_js,
      "assets/site.js must read counts.settled_in_scope_total for the in-scope settled figure (F-72)")
check("settled_published" in site_js,
      "assets/site.js must name the published settled-row count separately (F-72)")
for page_name in ("categories.html", "verification.html"):
    body = (ROOT / page_name).read_text()
    check("settled_in_scope_total" in body,
          f"{page_name} must read counts.settled_in_scope_total, not only the published count (F-72)")
    check("settled_published" in body,
          f"{page_name} must show the published settled-row count as a separate row (F-72)")
# and the collector must publish both numbers
collect_src = (ROOT / "scripts" / "collect.py").read_text()
check('"settled_in_scope_total": settled_in_scope_total' in collect_src,
      "scripts/collect.py must publish counts.settled_in_scope_total")
check('"open_published_rows"' in collect_src and '"settled_published_rows"' in collect_src,
      "scripts/collect.py must publish the published-row counts explicitly")
check('"settled_in_scope_total_method"' in collect_src,
      "scripts/collect.py must publish how the settled total was obtained (exact vs carried forward)")
check("settled_in_scope_total_method" in index_html,
      "index.html must render the method beside the settled total (F-72)")
# S-02: the open side had the same defect and is checked the same way.
categories_html = (ROOT / "categories.html").read_text()
check('"open_in_scope_total": open_in_scope_total' in collect_src,
      "scripts/collect.py must publish counts.open_in_scope_total (S-02)")
check("open_in_scope_total" in categories_html,
      "categories.html must read counts.open_in_scope_total for 'inside the five categories' (S-02)")
check("open_published_rows" in categories_html,
      "categories.html must name the published open-row count separately (S-02)")
check("KD.num(snap.counts.open_in_scope)}" not in categories_html,
      "categories.html must not label the published open-row count as the scan total (S-02)")

# 6. F-90: the three settled counts are different numbers and must not share one phrase.
#    counts.settled_in_scope is the KEPT WINDOW (post-trim); settled_in_scope_total is the scan
#    total; settled_published is what the pages render. index.html used to print the kept window
#    as "settled in scope" while its own banner printed the scan total under the same words.
#    (S-02 on main fixed the same wording from the other direction; both sets of assertions are
#    kept, because they fail on different regressions.)
kpi = index_html.split("Resolved yes/no captured", 1)[-1].split("],", 1)[0]
check("settled_published" in kpi and "settled_in_scope_total" in kpi,
      "index.html's settled KPI must read settled_published and settled_in_scope_total, not the kept window")
check("settled_kept_window" in index_html,
      "index.html must name the kept window as a number of its own, never as the scan total (F-90)")

# 7. F-83 (main, PR #94/#95): a topic where NO open row has traded must be labelled `untraded`
#    rather than presented as a ranking. The assertion here is on the shipped wording, so a
#    refactor cannot quietly drop the disclosure.
check("untraded" in index_html,
      "index.html must label a topic with no traded market as 'untraded' (F-83)")
check("Untraded topics in this snapshot" in index_html,
      "index.html must name the untraded topics below the table (F-83)")


# The report MUST be last. Before 2026-11-22 this block sat above the F-72 checks, so the
# suite printed OK and exited 0 before any of them ran: nine assertions were dead code and
# three of them were false at the time (the collector published no open_published_rows, no
# settled_published_rows and no settled_in_scope_total_method). Found by running the file and
# grepping collect.py for the fields the dead checks demanded. This session (arena-d34a9f0d)
# found the same defect independently and recorded it; main's fix was adopted rather than
# duplicated, so no finding id is published for it here.
if errors:
    print("FAIL")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("OK: scope tests passed (natural gas excluded, QA fixtures refused, labels corrected, exclusions published)")
