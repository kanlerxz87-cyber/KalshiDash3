#!/usr/bin/env python3
"""Kalshi demo data collector.

Runs with NO credentials and NO manual input. It reads only public endpoints of
the official Kalshi demo Trade API and writes JSON snapshots under data/live/.
The static site (docs/) then renders those snapshots, so every number the site
shows is traceable to an official API response and to the time it was fetched.

Official sources
  Endpoints ....... https://docs.kalshi.com/getting_started/api_environments
  Public data ..... https://docs.kalshi.com/getting_started/quick_start_market_data
  Get Markets ..... https://docs.kalshi.com/api-reference/market/get-markets
  Orderbook ....... https://docs.kalshi.com/api-reference/market/get-market-orderbook
  Candlesticks .... https://docs.kalshi.com/api-reference/market/get-market-candlesticks
  Lifecycle ....... https://docs.kalshi.com/getting_started/market_lifecycle

Scope: the five requested categories only (Gas Prices, Elections, Culture,
Crypto, Golf). Category membership is recorded per market as either
"seed" (the series ticker appears in the official fee schedule) or "keyword"
(heuristic title match). Nothing is silently promoted to confirmed.

Exit codes: 0 success, 2 the API was unreachable (nothing is overwritten).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LIVE = DATA / "live"

BASE = os.environ.get("KALSHI_BASE", "https://external-api.demo.kalshi.co/trade-api/v2")
UA = "KalshiDash3-collector/1.0 (+https://github.com/kanlerxz87-cyber/KalshiDash3)"

# Documented reference: https://docs.kalshi.com/api-reference/market/get-markets
PRICE_HISTORY_LIMIT = 120  # points kept per market
PER_CATEGORY_KEEP = 120    # keyword-basis rows kept per category in the committed snapshot
SEED_KEEP = 400            # confirmed (seed) rows kept per category, largest-dollar first
SETTLED_KEEP = 1600        # most recent settled rows kept per status window, so the file stays browser-sized
SETTLED_PUBLISH_CAP = 200  # settled rows PUBLISHED, chosen per topic (see select_settled)
HISTORICAL_PER_SEED = 40   # settled rows pulled per seeded series from GET /historical/markets
HISTORICAL_BACKFILL_PER_SEED = HISTORICAL_PER_SEED
HISTORICAL_PAGE = 1000     # documented maximum for GET /historical/markets?limit
SAFETY_SCAN_CAP = 25000    # paging safety stop per status; truncation is published, never hidden
OFFICIAL_VOLUME_SWEEP_TOP_K = 12  # top traded official series per topic queried directly (E9D9-3)
CITED_SERIES_READ_LIMIT = 25  # archived series read fresh per pass when the scan no longer covers them (A8D3)

# The brief limits this dashboard to listed topics. Two corrections are applied to the
# keyword fallback only — a series that is explicitly a seed can never be excluded, because
# the fee schedule is the authority for it.
#
# 1. Natural gas is not "gas prices" in the sense the brief means (retail petrol prices).
#    Verified against the official series record on 2026-11-21:
#      GET /series/KXNATGAS15M -> {"categories":["Commodities"],"title":"Natural Gas 15-minute",
#        "product_metadata":{"scope":"Natural Gas"},"settlement_sources":[{"name":"Pyth - NATGAS"}]}
#      GET /series/KXAAAGASM   -> {"categories":["Economics"],"title":"US gas price",
#        "product_metadata":{"scope":"Gasoline"},"settlement_sources":[{"name":"AAA"}]}
#    The old keyword "gas" therefore let a natural-gas futures market sit inside Gas Prices
#    (11 such rows in the 2026-11-21T00:50Z snapshot), which mislabels the topic on the page.
# 2. Kalshi's own demo QA fixtures ("Demo portfolio test only.", "Portfolio cash out QA 5")
#    are test instruments, not live events. One of them was the largest open Culture market
#    in the 2026-11-21T00:50Z snapshot and was therefore shown as culture's headline market.
#    Verified: GET /markets/KXGRAMMYNOMROTY-QA7CECC5-QA -> rules_primary "Demo portfolio test only."
EXCLUDE_KEYWORD_SERIES: dict[str, str] = {
    "KXNATGAS15M": "natural-gas futures (Commodities, Pyth NATGAS), not retail gasoline prices",
    # F-97: the SAME correction applied to the daily natural-gas contract, which reached the
    # site through a different door. Kalshi files this series under Entertainment:
    #   GET /series/KXNATGASD -> {"categories":["Entertainment"],"title":"Natural Gas Daily",
    #     "tags":["Oil & Gas"],"product_metadata":{"scope":"Natural Gas"},
    #     "settlement_sources":[{"name":"Pyth"}]}
    # so the official-category discovery (GET /series?category=Entertainment -> Culture) put
    # 20 natural-gas rows inside the Culture topic in the 2026-11-25T13:16:43Z snapshot, even
    # though the keyword classifier would have said "gas" and the sibling series KXNATGAS15M
    # is already excluded above for exactly this reason. It is neither a culture event nor a
    # retail gasoline price, so it is excluded from every topic.
    "KXNATGASD": "natural gas daily futures (official series categories ['Entertainment'], "
                 "tags ['Oil & Gas'], scope 'Natural Gas', Pyth settlement): not a culture "
                 "event and not retail gasoline prices "
                 "(https://external-api.demo.kalshi.co/trade-api/v2/series/KXNATGASD)",
    "KXNATGASMON": "natural gas monthly futures (official series tags ['Oil & Gas'], "
                   "product_metadata.scope 'Natural Gas'): not retail gasoline prices "
                   "(https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Oil%20%26%20Gas)",
}
# QA / benchmark fixtures observed on the demo exchange:
#   KXGRAMMYNOMROTY-QA7CECC5-QA -> title "Portfolio cash out QA 5", rules "Demo portfolio test only."
#   KXNEWPOPE-70-ZS01..ZS08 / ZQ01 -> yes_sub_title "Bench Run 1".."Bench Run 8", "Bench Probe 1"
EXCLUDE_TITLE_RE = re.compile(
    r"demo portfolio test|portfolio cash out|\bqa\s*\d|\bbench\s+(?:run|probe)\s*\d*\b",
    re.I,
)

# 3. A keyword fallback match on a market's TITLE is not evidence about its topic when the
#    series itself is filed by Kalshi under a category that cannot be one of the five. Two
#    instances were live on the deployed site on 2026-11-21:
#      KXEPLFIRSTGOAL / KXEPLAST / KXEPLSOA  -> series.categories ["Sports"], tags ["Soccer"]
#        matched Culture because the keyword "oscar" appears in the PLAYER'S NAME "Oscar Bobb".
#        It was Culture's headline market on the landing page ("largest open" row) that whole day.
#      KXDEMOFUTHOURLY -> series.categories ["Test"], tags ["Demo"], title
#        "Demo hourly event contract futures"; matched Crypto because its market title contains
#        "BTC". 8 of the 23 archived >= $0.10 swings were this test instrument.
#    And on 2026-11-27 (E9D9-3), 16 of the 17 open Elections rows were non-election governance
#    prop series that Kalshi files under ["Politics"] rather than ["Elections"]:
#      GET /series/KXAPRPOTUS     -> categories ["Politics"], title "Potus approval rating"
#      GET /series/KXTRUMPNOMNUM  -> categories ["Politics"], title "Number of Trump cabinet nominations"
#      GET /series/KXEOWEEK       -> categories ["Politics"], title "How many executive orders next week?"
#    whereas GET /series?category=Elections returns all 2,736 official Elections series directly.
#    Official records (fetched 2026-11-21 & 2026-11-27, GET {BASE}/series/{ticker}):
#      https://external-api.demo.kalshi.co/trade-api/v2/series/KXEPLFIRSTGOAL
#      https://external-api.demo.kalshi.co/trade-api/v2/series/KXDEMOFUTHOURLY
#      https://external-api.demo.kalshi.co/trade-api/v2/series/KXAPRPOTUS
#      https://external-api.demo.kalshi.co/trade-api/v2/series/KXTRUMPNOMNUM
#      https://external-api.demo.kalshi.co/trade-api/v2/series/KXEOWEEK
#    Rule: a row's official `categories` list is recorded on every row (category_source), and a
#    row's official categories are checked for consistency with its topic. A row whose
#    categories are known, non-empty and contain none of the topic's compatible categories is
#    dropped and counted, because the brief's five topics cannot include a series Kalshi files
#    as Test, as a different sport, or as non-election Politics. Unknown/empty categories never
#    drop a row: absence of the field is not evidence (KXBTCY, for example, returns Crypto and
#    would pass; a series with no categories list stays as it is and remains labelled by its basis).
#
#    Also documented in the same place: GET /series supports
#      ?category=<exact, case-sensitive>  (https://docs.kalshi.com/api-reference/market/get-series-list)
CATEGORY_COMPATIBLE = {
    "gas": {"Economics", "Commodities", "Financials"},
    "elections": {"Elections"},
    "culture": {"Entertainment", "Culture", "Pop Culture", "Awards", "Media"},
    "crypto": {"Crypto", "Financials"},
    "golf": {"Sports", "Golf"},
}
# Official Kalshi categories that can never belong to any of the five topics, whatever a title
# keyword says. Kept explicit so the exclusion is auditable rather than a silent side effect.
CATEGORY_NEVER_IN_SCOPE = {"Test", "Demo"}

# F-97: the official CATEGORY is a coarse bucket; the official TAGS are the domain. A series
# that carries another topic's domain tag cannot be published inside this topic, whatever
# category the exchange files it under. The case that prompted this rule is on the record:
#   GET /series/KXNATGASD -> {"categories":["Entertainment"],"title":"Natural Gas Daily",
#     "tags":["Oil & Gas"],"product_metadata":{"scope":"Natural Gas"}}
# "Entertainment" is a Culture category, so the category-only rule put natural-gas futures
# inside Culture (20 published rows in the 2026-11-25T13:16:43Z snapshot). The tags said
# "Oil & Gas". Both are official fields of the same record
# (https://docs.kalshi.com/api-reference/market/get-series-list), so the tag is the narrower
# statement and is used as the tie-break.
# Only tags that unambiguously name one of the five topics' own domains are listed. A tag that
# names no domain (frequency tags such as "15 min" or "Hourly", or a format tag such as
# "Econ Daily") never excludes a row: absence of a domain is not a contradiction.
TAG_DOMAIN_TOPIC = {
    "Oil & Gas": "gas",
    "Oil and energy": "gas",
    "Crypto": "crypto",
    "Bitcoin": "crypto",
    "Ethereum": "crypto",
    "Solana": "crypto",
    "XRP": "crypto",
    "DOGE": "crypto",
    "BNB": "crypto",
    "HYPE": "crypto",
    "Golf": "golf",
}

# F-66: a broad official category can contain the topic AND everything next to it. Sports is
# the case that matters: it is where Kalshi files golf, and also every other sport. Naming a
# specific series as out of scope is the narrow, auditable way to handle that, and each entry
# records the official record that justifies it. Applied AFTER the broad match, so golf keeps
# working while a soccer award does not become Culture.
#   KXBALLONDOR  GET /series/KXBALLONDOR -> categories ["Sports"], tags ["Soccer"]
#   KXGOLFTENNISMAJORS -> categories ["Sports"], tags ["Golf","Tennis"]: a tennis-vs-golf
#     comparison is not a golf event, so it is excluded from Golf specifically.
TOPIC_EXCLUDE_SERIES: dict[str, list[dict]] = {
    "culture": [
        {"series": "KXBALLONDOR",
         "reason": "Ballon d'Or: official series record is categories ['Sports'], tags ['Soccer'] "
                   "(https://external-api.demo.kalshi.co/trade-api/v2/series/KXBALLONDOR); it is a "
                   "football award, not a culture market"},
    ],
    "golf": [
        {"series": "KXGOLFTENNISMAJORS",
         "reason": "Tennis-vs-golf comparison: official series tags ['Golf','Tennis'] "
                   "(https://external-api.demo.kalshi.co/trade-api/v2/series/KXGOLFTENNISMAJORS); "
                   "not a golf tournament market"},
    ],
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: Status codes worth asking again. 429 is documented as "too_many_requests with no
#: Retry-After and no penalty" (https://docs.kalshi.com/getting_started/rate_limits);
#: 5xx are the exchange/edge failing transiently. Any other 4xx (400 bad request,
#: 404 unknown ticker, 410 removed endpoint) is a client error that cannot be fixed
#: by retrying, so it fails immediately and loudly instead of burning the pass.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
BACKOFF_SECONDS = 1.5
#: 429 is the one case the docs answer directly: "Unauthenticated public requests are subject
#: to separate limits ... back off on 429" (https://docs.kalshi.com/getting_started/rate_limits).
#: For a collector that pages ~60 requests per pass that answer deserves more than 1.5 s, so a
#: rate-limited read waits 3 s, 6 s, then 12 s before giving up on the pass.
RATE_LIMIT_BACKOFF_SECONDS = 3.0
#: A small pause between pages of one scan. It costs a few seconds per pass and lowers the odds
#: of tripping the unauthenticated limit in the first place, which is cheaper than the backoff.
PAGE_PAUSE_SECONDS = 0.15


def get(path: str, params: dict | None = None, retries: int = 4):
    """GET a public endpoint with bounded exponential backoff.

    Failure policy (F-85): a retryable failure is retried up to `retries` attempts and then
    raises, so a persistently unreachable exchange still fails the pass and nothing is
    overwritten (exit code 2). Before this change a single 5xx aborted the whole collection,
    because every non-429 HTTPError broke out of the loop on the first attempt — one flaky
    response from the demo API was enough to skip a pass.

    Wait schedule: 429 -> 3 s, 6 s, 12 s (the docs say to back off on 429 for unauthenticated
    public requests); 5xx / network -> 1.5 s, 3 s, 4.5 s. No wait after the final attempt.
    """
    url = BASE + path
    if params:
        from urllib.parse import urlencode
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            url += "?" + urlencode(clean)
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
        wait = BACKOFF_SECONDS * (attempt + 1)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8")), url
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code not in RETRY_STATUS:
                raise RuntimeError(f"{last} for {url}") from e
            wait = (RATE_LIMIT_BACKOFF_SECONDS * (2 ** attempt) if e.code == 429
                    else BACKOFF_SECONDS * (attempt + 1))
        except Exception as e:  # network / TLS / DNS / socket timeout
            last = f"{type(e).__name__}: {e}"
            wait = BACKOFF_SECONDS * (attempt + 1)
        if attempt + 1 < retries:
            time.sleep(wait)
    raise RuntimeError(f"{last} for {url} after {retries} attempts")


def fnum(v):
    """Parse a fixed-point string into a float; return None when unusable."""
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def load_categories():
    return json.loads((DATA / "categories.json").read_text())


def is_multivariate(m):
    """Multivariate (combo) markets are combinations of unrelated legs.

    Kalshi documents them as a separate product and they have their own
    lifecycle channels, so they are never attributed to one topic.
    https://docs.kalshi.com/getting_started/market_lifecycle
    """
    return bool(m.get("mve_collection_ticker")) or str(m.get("ticker", "")).startswith("KXMVE")


def series_of(m):
    """Best available series identifier for a market.

    Observed 2026-11-20: GET /markets returns `series_ticker: null`, so the
    field cannot be relied on. Kalshi series tickers carry no hyphen, so the
    part of the market ticker before the first "-" is the series
    (KXAAAGASM-26MAR31-4.00 -> KXAAAGASM). Measured against the seed list, which
    makes a wrong derivation visible rather than silent: it simply fails to match.
    """
    st = (m.get("series_ticker") or "").strip()
    if st:
        return st.upper()
    t = str(m.get("ticker") or "")
    return t.split("-")[0].upper() if "-" in t else t.upper()


def classify(cats, series_ticker, series_title, series_categories, market_title):
    """Return (category_id, basis) for a market, or (None, None).

    basis="seed" means the series ticker is listed in the official fee schedule:
    the market's topic is confirmed, not guessed.
    basis="keyword" means a word-boundary heuristic match on the titles.

    Word boundaries matter: a substring test put a sports combo titled
    "yes Vegas,yes Tie" into Gas Prices because "vegas" contains "gas".
    """
    st = (series_ticker or "").upper()
    for c in cats["categories"]:
        for s in c["seed_series"]:
            if s["ticker"].upper() == st:
                return c["id"], "seed"
    hay = " ".join(
        x for x in [series_ticker or "", series_title or "", series_categories or "", market_title or ""] if x
    ).lower()
    # Demo QA fixtures are never a live event, whichever keyword they happen to match.
    if EXCLUDE_TITLE_RE.search(" ".join(x for x in [market_title or "", series_title or ""] if x)):
        return None, None
    if st in EXCLUDE_KEYWORD_SERIES:
        return None, None
    for c in cats["categories"]:
        for kw in c["keyword_fallback"]:
            if re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", hay):
                return c["id"], "keyword"
    return None, None


def excluded_series_reason(cat_id: str, series_ticker: str) -> str | None:
    """Reason string when the topic names this series as out of scope (F-66), else None."""
    st = (series_ticker or "").upper()
    for ex in TOPIC_EXCLUDE_SERIES.get(cat_id or "", []):
        if ex["series"] == st:
            return ex["reason"]
    return None


def official_categories(series_record) -> list[str]:
    """The series' own `categories` list, verbatim from GET /series.

    Returns [] when the record is missing or the field is absent, and [] is treated as
    "unknown", never as "contradicts" — a field the API did not return is not evidence.
    """
    if not isinstance(series_record, dict):
        return []
    cats = series_record.get("categories")
    if isinstance(cats, list):
        return [str(c) for c in cats if str(c).strip()]
    single = series_record.get("category")
    return [str(single)] if single else []


def category_conflict(cat_id: str, official: list[str], basis: str, tags: list[str] | None = None) -> str | None:
    """Return a reason when the series' official category or tags contradict the topic, else None.

    Applied to every row, seed or keyword, because a series can be in the fee schedule and
    still not be one of the five topics: KXBALLONDOR ("Ballon d'Or") is a fee-schedule seed
    that Kalshi files under Sports, and the brief's Culture topic is not football awards.
    The fee schedule is the authority for a series EXISTING; the series record is the
    authority for its CATEGORY (https://docs.kalshi.com/api-reference/market/get-series-list).

    Unknown categories ([] ) never conflict. A known category that is in the topic's
    compatible set never conflicts. A known category outside it does conflict, and the reason
    names the official category so the count on the page is auditable.

    F-97: the category is a coarse bucket and the TAGS are the domain, so a series whose
    official tags name a DIFFERENT topic's domain conflicts even when its category is
    compatible with this one. KXNATGASD is categories ["Entertainment"] (Culture) with tags
    ["Oil & Gas"] (gas). Tags that name no topic's domain never conflict, and a row whose
    tags are unknown ([]) is left alone: an absent field is not evidence.
    """
    if not cat_id:
        return None
    for t in (tags or []):
        owner = TAG_DOMAIN_TOPIC.get(str(t))
        if owner and owner != cat_id:
            return (f"official series tags {list(tags)} name the {owner} domain, "
                    f"not {cat_id}")
    if not official:
        return None
    ok = CATEGORY_COMPATIBLE.get(cat_id, set())
    if any(o in ok for o in official):
        return None
    if any(o in CATEGORY_NEVER_IN_SCOPE for o in official):
        return f"official series categories {official} are test/demo instruments, not a live event in {cat_id}"
    return f"official series categories {official} are not {cat_id} (compatible: {sorted(ok)})"


def fetch_series_index(getter=None):
    """GET /series — used only to enrich titles/categories.

    https://docs.kalshi.com/api-reference/market/get-series-list
    The endpoint is not paginated in the documented sense (no cursor in the
    response schema), so a single call is made and failures are non-fatal.
    """
    g = getter or get
    try:
        d, _ = g("/series")
        return {s.get("ticker", "").upper(): s for s in d.get("series", []) if s.get("ticker")}
    except RuntimeError as e:
        print(f"  ! /series unavailable ({e}); continuing without it", file=sys.stderr)
        return {}


def carry_forward_series(ledger: dict, previous: dict, cited) -> int:
    """Keep a VERIFIED series record for a series the current scan no longer covers (A8D3).

    Why this exists: the ledger below is built from rows in the CURRENT open/settled window, so a
    resolved event's series leaves it as its markets age out of the scan - while the archived
    >= $0.10 swings still cite that series and `scripts/tests/validate_alerts.py` re-checks their
    topic against this ledger. On 2026-11-27 that gap stopped the collector committing at all:
    every relay pass from 18:29Z to 19:38Z failed with "archive:KXAAAGASD-26NOV21-3.6600@...:
    assigned topic 'gas' but GET /series categories [] accept []" and the published snapshot
    stayed frozen at 18:00:57Z.

    A FRESH answer always wins: this fills only a series the previous snapshot recorded categories
    for and the current snapshot does not. Nothing is inferred - the carried record is exactly the
    one `GET /series` already returned, with the same source URL - and the count is published in
    `counts.series_ledger_carried_forward` so a reader can see the ledger is partly carried.
    """
    carried = 0
    for t in sorted({str(x or "").upper() for x in cited}):
        if not t:
            continue
        current = ledger.get(t) or {}
        if current.get("categories"):
            continue
        prior = previous.get(t) or {}
        if not prior.get("categories"):
            continue
        ledger[t] = dict(prior)
        carried += 1
    return carried


def official_discovery(cats, series_index: dict | None = None, getter=None) -> tuple[dict[str, dict], list[dict]]:
    """Series the EXCHANGE itself files under each topic, via the documented filters.

    Why this exists: before F-66 the only ways into a topic were (a) a ticker in the fee
    schedule or (b) a keyword match on a title, and both are weak — the keyword path put a
    soccer prop inside Culture because a player is called Oscar, and the fee-schedule path
    put the Ballon d'Or (officially Sports) inside Culture, while Culture had almost no rows
    at all even though Kalshi lists dozens of official Entertainment series. The API documents
    exactly the filter needed:

      GET /series?category=<value>&include_volume=true
      GET /series?tags=<value>&include_volume=true
      https://docs.kalshi.com/api-reference/market/get-series-list

    Each topic declares both filters in data/categories.json (`official_categories`,
    `official_tags`). Matching is exact and case-sensitive, as the documentation requires.
    `include_volume=true` is a documented boolean query parameter returning `volume_fp` on
    each series so high-volume Elections/Culture series buried behind the 25,000-row newest-
    first 15m FX/crypto scan cap can be queried directly (`top_volume_official_series`).
    Every call is recorded (url, value, count, or the error) so the mapping is auditable, and a
    failed call is reported and skipped — it never silently widens a topic.

    Returns (series -> {category_id, filter, value, volume_fp}, calls).
    """
    g = getter or get
    by_series: dict[str, dict] = {}
    calls: list[dict] = []
    for c in cats["categories"]:
        for kind, values in (("category", c.get("official_categories") or []),
                             ("tags", c.get("official_tags") or [])):
            for value in values:
                url = f"{BASE}/series?{kind}={value}&include_volume=true"
                try:
                    d, _ = g("/series", {kind: value, "include_volume": "true"})
                except RuntimeError as e:
                    print(f"  ! {url}: {e}", file=sys.stderr)
                    calls.append({"category_id": c["id"], "filter": kind, "value": value,
                                  "url": url, "series": 0, "error": str(e)})
                    continue
                series_rows = [s for s in d.get("series", []) if s.get("ticker")]
                for s in series_rows:
                    t = s.get("ticker", "").upper()
                    vol = fnum(s.get("volume_fp"))
                    by_series.setdefault(
                        t,
                        {"category_id": c["id"], "filter": kind, "value": value, "volume_fp": vol},
                    )
                    if series_index is not None and isinstance(s, dict):
                        series_index.setdefault(t, s)
                calls.append({"category_id": c["id"], "filter": kind, "value": value,
                              "url": url, "series": len(series_rows)})
                print(f"  official {c['id']:<9} {kind}={value:<20} -> {len(series_rows)} series")
    return by_series, calls


def top_volume_official_series(official_map: dict[str, dict], top_k: int = OFFICIAL_VOLUME_SWEEP_TOP_K) -> dict[str, list[str]]:
    """Top `top_k` non-excluded official series per topic with `volume_fp > 0`, largest first.

    Why this exists (E9D9-3): `GET /markets?status=open` returns newest-first and stops at
    `SAFETY_SCAN_CAP` (25,000), which on the demo exchange is filled by 15-minute FX and
    crypto contracts. Older multi-year series (`KXPRESPERSON`, `KXPRESNOMD`, `CONTROLS`,
    `KXOSCARPIC`) sit past that cursor even though `GET /series?category=...&include_volume=true`
    reports millions of contracts traded on them. Querying the top-volume official series per
    topic recovers those live markets in a bounded number of calls without guessing tickers.
    """
    grouped: dict[str, list[tuple[float, str]]] = {}
    for st, info in (official_map or {}).items():
        cid = info.get("category_id")
        vol = info.get("volume_fp")
        if not cid or vol is None or vol <= 0:
            continue
        if st in EXCLUDE_KEYWORD_SERIES or excluded_series_reason(cid, st):
            continue
        grouped.setdefault(cid, []).append((float(vol), st))
    out: dict[str, list[str]] = {}
    for cid, items in grouped.items():
        items.sort(key=lambda pair: (-pair[0], pair[1]))
        out[cid] = [st for _, st in items[:top_k]]
    return out


def classify_in_scope(
    cats: dict,
    m: dict,
    series_index: dict,
    official_map: dict | None = None,
    record_series_fn=None,
    ledger: dict | None = None,
) -> tuple[str | None, str | None, str | None, list[str], str | None, str | None]:
    """Single source of truth for five-topic classification + QA/series/category-conflict gates.

    Used by BOTH `scripts/collect.py` and `scripts/roi_scan.py` (E9D9-2) so the live-desk ROI
    scanner cannot admit `Test` instruments (`KXDEMOFUTHOURLY`) or off-topic keyword matches
    that the collector refuses.

    Returns `(cat_id, basis, matched_by, official_cats, reject_bucket, reject_detail)` where
    `cat_id` is None whenever the market is out of scope or rejected (`reject_bucket` is one of
    `"multivariate"`, `"off_topic_or_qa"`, `"excluded_series"`, `"unclassified"`, `"conflict"`).
    """
    if is_multivariate(m):
        return None, None, None, [], "multivariate", None
    st = series_of(m)
    s = series_index.get(st) or {}
    title_blob = " ".join(
        x for x in [
            m.get("title") or "",
            m.get("yes_sub_title") or "",
            m.get("subtitle") or "",
            m.get("rules_primary") or "",
            s.get("title") or "",
        ] if x
    )
    if st in EXCLUDE_KEYWORD_SERIES or EXCLUDE_TITLE_RE.search(title_blob):
        return None, None, None, [], "off_topic_or_qa", EXCLUDE_KEYWORD_SERIES.get(st)
    cat_id, basis = classify(
        cats,
        st,
        s.get("title"),
        " ".join(s.get("categories") or []) if s.get("categories") else s.get("category"),
        m.get("title") or m.get("yes_sub_title"),
    )
    matched_by = basis
    off = (official_map or {}).get(st)
    if off:
        ex_reason = excluded_series_reason(off["category_id"], st)
        if ex_reason:
            return None, None, None, [], "excluded_series", ex_reason
        cat_id = off["category_id"]
        basis = "seed" if any(
            seed2["ticker"].upper() == st
            for c2 in cats["categories"] for seed2 in c2["seed_series"]
        ) else "keyword"
        matched_by = "official"
    if cat_id:
        ex_reason = excluded_series_reason(cat_id, st)
        if ex_reason:
            return None, None, None, [], "excluded_series", ex_reason
    if not cat_id:
        return None, None, None, [], "unclassified", None
    if record_series_fn is not None:
        record_series_fn(st)
    if ledger is not None and st in ledger:
        official = ledger[st].get("categories") or []
        official_tags = ledger[st].get("tags") or []
    else:
        official = official_categories(s)
        official_tags = s.get("tags") or []
    conflict = category_conflict(cat_id, official, basis, official_tags)
    if conflict:
        return None, None, None, official, "conflict", conflict
    return cat_id, basis, matched_by, official, None, None


def scan_markets():
    """Page GET /markets for open and settled markets.

    Documented: status filter accepts unopened|open|paused|closed|settled;
    limit max 1000; cursor pagination; a cursor that cannot be decoded is
    ignored and page 1 is returned, so we stop on an empty cursor only.
    https://docs.kalshi.com/getting_started/pagination

    The cap used to be 4000/1200, and it mattered: the demo exchange now holds
    tens of thousands of open markets, returned newest-first, and the newest
    ones are zero-volume multivariate listings (verified against
    https://external-api.demo.kalshi.co/trade-api/v2/markets?status=open&limit=2
    on 2026-11-20). A capped window therefore ranked "highest dollar amount"
    events over a biased subset — data/live/roi.json from a paged-to-exhaustion
    scan found 10,342 in-scope open markets where the 4,000-row window saw 387.
    Paging now runs to exhaustion at a 25,000-row safety stop, and truncation is
    published in counts rather than hidden.
    """
    out = {"open": [], "settled": []}
    out["_truncated"] = {}
    for status, cap in (("open", SAFETY_SCAN_CAP), ("settled", SAFETY_SCAN_CAP)):
        cursor, seen = "", 0
        truncated = False
        while True:
            # mve_filter=exclude is a DOCUMENTED parameter of GET /markets
            # ("'only' returns only multivariate events, 'exclude' excludes multivariate
            # events" — https://docs.kalshi.com/api-reference/market/get-markets). It
            # removes the combo listings that are excluded below anyway, which is what
            # pushed the newest-first scan into the safety cap: on main the 25,000-row
            # window was truncated and the in-scope total moved between collector runs
            # (749 open in scope at the 2026-11-21T00:50Z snapshot vs 1,365 in the desk
            # scan of the same exchange). Asking the API for the smaller universe is
            # honest filtering, not a wider guess.
            d, _ = get("/markets", {"status": status, "limit": 1000, "cursor": cursor or None,
                                    "mve_filter": "exclude"})
            batch = d.get("markets") or []
            out[status].extend(batch)
            seen += len(batch)
            cursor = d.get("cursor") or ""
            if not cursor or not batch:
                break
            time.sleep(PAGE_PAUSE_SECONDS)
            if seen >= cap:
                truncated = True
                break
        out["_truncated"][status] = truncated
        # Deduplicate by ticker: documented as required when paging by close time.
        dedup = {m["ticker"]: m for m in out[status] if m.get("ticker")}
        out[status] = list(dedup.values())
    return out


def dollars_traded(m):
    """Estimate of dollars traded = contracts traded x last traded price.

    This is an ESTIMATE and is labelled as such everywhere it is displayed.
    volume_fp is a contract count (F-23); last_price_dollars is a price.
    Kalshi's own `notional_value_dollars` is a different thing entirely: "the
    total value of a single contract at settlement" (F-22). It is NOT a volume
    ranking and must not be used as one.
    """
    v = fnum(m.get("volume_fp"))
    p = fnum(m.get("last_price_dollars"))
    if v is None or p is None:
        return None
    return round(v * p, 2)


def orderbook_summary(ticker, depth=10):
    """Liquidity: contracts available at each price.

    Documented: bids only, [price_dollars, count_fp] pairs ascending, best bid
    last; a YES bid at X is a NO ask at 1-X. So contracts available to a YES
    buyer at the best YES ask equals the count resting at the best NO bid.
    https://docs.kalshi.com/getting_started/orderbook_responses
    """
    try:
        d, url = get(f"/markets/{ticker}/orderbook", {"depth": depth}, retries=2)
    except RuntimeError as e:
        return {"error": str(e), "source": f"{BASE}/markets/{ticker}/orderbook?depth={depth}"}
    ob = d.get("orderbook_fp") or {}
    yes = ob.get("yes_dollars") or []
    no = ob.get("no_dollars") or []

    def lv(rows):
        out = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            p, c = fnum(row[0]), fnum(row[1])
            if p is None or c is None:
                continue
            out.append({"price": p, "contracts": c})
        return out

    yeslv, nolv = lv(yes), lv(no)
    best_yes_bid = yeslv[-1] if yeslv else None
    best_no_bid = nolv[-1] if nolv else None
    return {
        "yes_bids": yeslv,
        "no_bids": nolv,
        "best_yes_bid": best_yes_bid,
        "best_no_bid": best_no_bid,
        # Derived, per the documented reciprocal relationship.
        "best_yes_ask_derived": (round(1.0 - best_no_bid["price"], 4) if best_no_bid else None),
        "contracts_at_best_yes_ask": (best_no_bid["contracts"] if best_no_bid else None),
        "contracts_at_best_yes_bid": (best_yes_bid["contracts"] if best_yes_bid else None),
        "visible_contracts_total": round(sum(x["contracts"] for x in yeslv + nolv), 2),
        "source": f"{BASE}/markets/{ticker}/orderbook?depth={depth}",
        "fetched_at": utcnow(),
    }


def update_price_history(hist, rows, pinned=None):
    """Append a live observation per market and keep a bounded window.

    Seconds-resolution history cannot be requested from Kalshi: candlesticks
    only support 1/60/1440-minute intervals (F-29). So the only way to have a
    seconds-resolution series is to accumulate REST observations over time,
    which is exactly what this file does on every run.

    F-99: `pinned` maps a ticker to the observation timestamps an archived alert cites.
    The retention window is a cap on the SERIES, not on the swings: without this, the two
    observations that BOUND an archived swing were dropped once the series grew past
    PRICE_HISTORY_LIMIT, and the swing could no longer be read back - 62 of the 150
    archived swings had lost both bounds in the 2026-11-25T13:16:43Z snapshot, which is why
    the evidence layer reported "unknown_no_observations" for 52 of the 130 swings the page
    serves. The pinned observations are kept in addition to the window, in time order.
    """
    now = utcnow()
    for m in rows:
        t = m.get("ticker")
        p = fnum(m.get("last_price_dollars"))
        if not t or p is None:
            continue
        series = hist.get(t, {"observations": []})
        obs = series["observations"]
        obs.append(
            {
                "t": now,
                "last": p,
                "yes_bid": fnum(m.get("yes_bid_dollars")),
                "yes_ask": fnum(m.get("yes_ask_dollars")),
                "volume_fp": m.get("volume_fp"),
            }
        )
        series["observations"] = keep_observations(obs, (pinned or {}).get(t))
        hist[t] = series
    return hist


def keep_observations(obs, pin=None):
    """The newest PRICE_HISTORY_LIMIT observations, plus any pinned by an archived alert.

    Pinning is by exact timestamp: an alert cites the two observations that bound it, so
    those two are the ones that must survive. Nothing else is kept, so the file does not
    grow without bound.
    """
    keep = list(obs[-PRICE_HISTORY_LIMIT:])
    if pin:
        older = obs[:max(0, len(obs) - PRICE_HISTORY_LIMIT)]
        extra = [o for o in older if o.get("t") in pin]
        if extra:
            keep = sorted(keep + extra, key=lambda o: o.get("t") or "")
    return keep


def pinned_alert_times(path=None) -> dict:
    """The observation timestamps an archived alert cites, per ticker (F-99).

    The archive is written by scripts/build_alerts.py and is the authority on which
    observations matter: each entry names the two observations that bounded the swing
    (from_time, to_time). They are pinned so the retention window cannot delete them.
    A missing or unreadable archive yields no pins, never a guess.
    """
    p = path or (LIVE / "alerts_archive.json")
    try:
        archive = json.loads(p.read_text()).get("alerts") or []
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    pins = {}
    for a in archive:
        t = a.get("ticker")
        if not t:
            continue
        s = pins.setdefault(t, set())
        for k in ("from_time", "to_time"):
            if a.get(k):
                s.add(a[k])
    return pins


def backfill_from_candles(hist, tickers, max_series=12):
    """Rebuild a missing observation series from Kalshi's official 1-minute candles.

    Why this is the only way to fix the rest of F-67: retaining history for every ticker an
    alert cites (done above, from the archive file) stops the bleeding going forward, but it
    cannot restore what an earlier run already deleted. A settled market is never returned by
    GET /markets again, so no amount of future collection will re-observe it. Kalshi still
    publishes the move itself, in that market's own candlestick history.

    Only tickers that (a) appear in the alert archive and (b) currently have NO observations are
    touched, so collected data is never overwritten and the cost is bounded by `max_series`.
    Each written point is a candle CLOSE and is marked "source": "candle", so it can never be
    mistaken for a REST last_price observation. Documented restrictions honoured here:
    period_interval is 1/60/1440 minutes, start_ts/end_ts are seconds, and one request spans at
    most 5,000 periods (https://docs.kalshi.com/api-reference/market/get-market-candlesticks).
    A candle with no price block is skipped, never written as 0.
    """
    from datetime import datetime, timezone
    done = 0
    for ticker in tickers:
        if done >= max_series:
            break
        if hist.get(ticker, {}).get("observations"):
            continue
        series_ticker = ticker.split("-")[0]
        end = int(datetime.now(timezone.utc).timestamp())
        start = end - 5000 * 60            # exactly the documented 5,000-period maximum
        path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
        try:
            d, _ = get(path, {"start_ts": start, "end_ts": end, "period_interval": 1})
        except RuntimeError as e:
            print(f"  ! candle backfill {ticker}: {e}", file=sys.stderr)
            continue
        obs = []
        for c in d.get("candlesticks") or []:
            price = c.get("price") or {}
            close = fnum(price.get("close_dollars", price.get("close")))
            ts = c.get("end_period_ts")
            if close is None or ts is None:
                continue
            obs.append({
                "t": datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last": close,
                "yes_bid": fnum((c.get("yes_bid") or {}).get("close_dollars")),
                "yes_ask": fnum((c.get("yes_ask") or {}).get("close_dollars")),
                "volume_fp": c.get("volume_fp"),
                "source": "candle",
            })
        if obs:
            hist[ticker] = {
                "observations": obs[-PRICE_HISTORY_LIMIT:],
                "backfilled_from": f"{BASE}{path}?start_ts={start}&end_ts={end}&period_interval=1",
                "backfilled_at": utcnow(),
            }
            done += 1
            print(f"  candle backfill {ticker}: {len(obs)} one-minute closes")
    return hist, done


def public_market_row(m, cat_id, basis, keep_rules=False, official_cats=None, matched_by=None):
    row = {
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "series_ticker": series_of(m),
        "series_ticker_from_api": m.get("series_ticker"),
        "title": m.get("title") or m.get("yes_sub_title") or "",
        "category_id": cat_id,
        "category_basis": basis,
        # The official category the EXCHANGE files this series under, verbatim, so a reader can
        # see that e.g. a Culture row is Entertainment or that a row was checked and matched.
        # Empty list = the series record did not return the field; never filled in.
        "series_categories": list(official_cats or []),
        # How the topic was decided: "official" (the exchange's own GET /series filter),
        # "seed" (fee-schedule ticker) or "keyword" (title heuristic). F-66.
        "category_matched_by": matched_by or basis,
        "status": m.get("status"),
        "result": m.get("result") or None,
        "last_price_dollars": fnum(m.get("last_price_dollars")),
        "yes_bid_dollars": fnum(m.get("yes_bid_dollars")),
        "yes_ask_dollars": fnum(m.get("yes_ask_dollars")),
        "no_bid_dollars": fnum(m.get("no_bid_dollars")),
        "no_ask_dollars": fnum(m.get("no_ask_dollars")),
        "volume_fp": fnum(m.get("volume_fp")),
        "volume_24h_fp": fnum(m.get("volume_24h_fp")),
        "open_interest_fp": fnum(m.get("open_interest_fp")),
        "dollars_traded_estimate": dollars_traded(m),
        "close_time": m.get("close_time"),
        "expected_expiration_time": m.get("expected_expiration_time"),
        "settlement_ts": m.get("settlement_ts"),
        "settlement_value_dollars": fnum(m.get("settlement_value_dollars")),
        "notional_value_dollars": fnum(m.get("notional_value_dollars")),
        "source": f"{BASE}/markets/{m.get('ticker')}",
    }
    # `rules_primary` / `rules_secondary` are where Kalshi records what a market settles on,
    # and they are the ONLY honest source of a "what could have moved this" link: the catalyst
    # extraction in scripts/roi_model.py (catalyst_links) reads URLs out of exactly these
    # fields, so a snapshot that drops them publishes zero catalyst links (data/live/roi.json
    # on main reported markets_with_catalyst_url: 0 while GET /markets returns the text —
    # compare https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASD-26NOV21-3.7300
    # which carries "…according to AAA…"). Kept verbatim, for open rows only: settled rows are
    # retained for their settlement record, and doubling the committed snapshot with text no
    # page links to is not worth it. A field the API did not return stays absent — never filled.
    if keep_rules:
        for k in ("rules_primary", "rules_secondary", "subtitle"):
            v = m.get(k)
            if v:
                row[k] = v
    return row


DEFAULT_CATS = ("gas", "elections", "culture", "crypto", "golf")


def select_settled(rows, cap=SETTLED_PUBLISH_CAP, cats=DEFAULT_CATS):
    """Choose which settled rows to publish, fairly across the five topics.

    The published set used to be `rows[:200]` after one global newest-first sort. That
    silently starved four of the five topics: 15-minute crypto markets settle dozens of
    times a day, so of the 200 rows the landing page showed on 2026-11-21, 198 were crypto
    and gas/elections/culture/golf had no resolution history at all — even though the
    snapshot held 1,600 settled in-scope rows. The brief asks for live events tracked
    "until the events have resolved" with topics kept separate, so the cap is now spent
    per topic.

    Round-robin, newest-first inside each topic. A topic with less history simply stops
    contributing and the others take the remaining capacity. Returns the picked rows plus
    the per-topic split, so the snapshot can publish exactly how the cap was spent.
    """
    by_cat = {}
    for r in sorted(rows, key=lambda r: (r.get("settlement_ts") or ""), reverse=True):
        by_cat.setdefault(r.get("category_id") or "other", []).append(r)
    order = [c for c in cats if c in by_cat] + [c for c in by_cat if c not in cats]
    picked, taken = [], {c: 0 for c in order}
    while len(picked) < cap:
        progressed = False
        for c in order:
            if len(picked) >= cap:
                break
            if taken[c] < len(by_cat[c]):
                picked.append(by_cat[c][taken[c]])
                taken[c] += 1
                progressed = True
        if not progressed:
            break
    picked.sort(key=lambda r: (r.get("settlement_ts") or ""), reverse=True)
    return picked, {c: n for c, n in taken.items()}


def split_and_select_settled(rows, keep=SETTLED_KEEP, cap=SETTLED_PUBLISH_CAP):
    """Pick the published settled rows (full set first), then trim the stored window.

    This exists as its own function because the ORDER is the defect: calling select_settled()
    on the already-trimmed window looks right and is wrong. Returns
    (stored_window, published_rows, published_by_category).
    """
    published, by_cat = select_settled(rows, cap=cap)
    return rows[:keep], published, by_cat


def historical_settled(seed_tickers, per_seed=HISTORICAL_PER_SEED):
    """Settled rows for seeded series that the live endpoints can no longer return.

    Documented behaviour: markets that settled before GET /historical/cutoff's
    `market_settled_ts` "are only available via GET /historical/markets"
    (https://docs.kalshi.com/getting_started/historical_data), and `GET /markets` stops
    returning them. So a topic that settles rarely — the seeded elections series
    KXELECTIRAN is the clear case — can look like it has no resolution history at all
    even though the exchange settled some of its markets months ago.

    Parameters used here are the ones the endpoint documents
    (https://docs.kalshi.com/api-reference/historical/get-historical-markets):
    `series_ticker` (one series per call; the filters are mutually exclusive),
    `limit` (max 1000) and `cursor` for pagination.

    Bounded on purpose: one request per seeded series, at most `per_seed` settled rows
    kept, and a failure is reported and skipped — the live scan already succeeded, so a
    historical hiccup must never fail the collection.
    """
    got_rows, report = {}, {}
    for ticker in seed_tickers:
        try:
            d, url = get("/historical/markets", {"series_ticker": ticker, "limit": HISTORICAL_PAGE}, retries=2)
        except RuntimeError as e:
            report[ticker] = {"error": str(e), "kept": 0}
            print(f"  ! historical {ticker}: {e}", file=sys.stderr)
            continue
        batch = d.get("markets") or []
        kept = 0
        for m in batch:
            if not m.get("result"):          # only a resolved market has a result
                continue
            t = m.get("ticker")
            if not t or t in got_rows:
                continue
            got_rows[t] = m
            kept += 1
            if kept >= per_seed:
                break
        report[ticker] = {"returned": len(batch), "kept": kept, "url": url}
        if kept:
            print(f"  historical {ticker:<16} -> {kept} settled market(s) from the archive")
    return got_rows, report


def build(include_orderbooks: int = 4, candlestick_points: int = 0):
    cats = load_categories()
    started = utcnow()
    print(f"collect: {BASE}")
    series_index = fetch_series_index()
    print(f"  series index: {len(series_index)} entries")
    # F-65: the index is a single GET /series call, so it can be partial or unavailable. Every
    # series that produced a row — and every series in the topic seed lists — gets an
    # authoritative per-series record too, so the category check is never a function of whether
    # the bulk index happened to include that series. One request per distinct series.

    # F-66: the exchange's own topic mapping, built from the documented GET /series filters.
    official_map, official_calls = official_discovery(cats, series_index=series_index)
    print(f"  official discovery: {len(official_map)} series mapped across {len(official_calls)} calls")
    raw = scan_markets()
    print(f"  markets: open={len(raw['open'])} settled={len(raw['settled'])}")

    # The paged scan is capped, and the demo exchange is full of multivariate
    # combos, so a confirmed fee-schedule series can fall outside the window.
    # Query every seed series explicitly so "confirmed" data is never lost.
    seeded = {"open": {}, "settled": {}}
    seed_set = {seed["ticker"].upper() for c in cats["categories"] for seed in c["seed_series"]}
    for c in cats["categories"]:
        for seed in c["seed_series"]:
            for status in ("open", "settled"):
                # One page per series was another quiet truncation: hourly crypto
                # series exceed the documented 1000-row page, so a single GET /markets
                # call per series could not see the whole series. Page to exhaustion.
                cursor, got = "", 0
                while True:
                    try:
                        d, _ = get("/markets", {"series_ticker": seed["ticker"], "status": status,
                                                "limit": 1000, "cursor": cursor or None})
                    except RuntimeError as e:
                        print(f"  ! seed {seed['ticker']} {status}: {e}", file=sys.stderr)
                        break
                    batch = d.get("markets") or []
                    for m in batch:
                        seeded[status][m.get("ticker")] = m
                    got += len(batch)
                    cursor = d.get("cursor") or ""
                    if not cursor or not batch or got >= 5000:
                        break
                print(f"  seed {seed['ticker']:<16} {status:<8} -> {got} market(s)")

    # E9D9-3: top-volume official series backfill. When the 25,000-row newest-first GET /markets
    # window is filled by 15-minute FX/crypto markets, older multi-year series that the exchange
    # itself files under Elections / Entertainment / Golf / Crypto (e.g. KXPRESPERSON, KXPRESNOMD,
    # CONTROLS, KXOSCARPIC) sit past the cursor even though GET /series?...&include_volume=true
    # reports millions of contracts traded on them. Query the top-volume official series per
    # topic directly so traded markets in sparse topics are never missed by scan-cap truncation.
    official_volume_swept: dict[str, list[str]] = top_volume_official_series(official_map)
    official_swept_markets = {"open": 0, "settled": 0}
    for cid, top_series in official_volume_swept.items():
        # Settled sweep is needed for Elections (where the 25k settled window only had 1 row);
        # other topics already fill their 50-row settled quota from the main scan + seeds.
        statuses = ("open", "settled") if cid == "elections" else ("open",)
        for st_tk in top_series:
            if st_tk in seed_set:
                continue
            for status in statuses:
                try:
                    d, _ = get("/markets", {"series_ticker": st_tk, "status": status, "limit": 1000})
                except RuntimeError as e:
                    print(f"  ! official-vol {st_tk} {status}: {e}", file=sys.stderr)
                    continue
                batch = d.get("markets") or []
                for m in batch:
                    if m.get("ticker") and m.get("ticker") not in seeded[status]:
                        seeded[status][m["ticker"]] = m
                        official_swept_markets[status] += 1
                if batch:
                    print(f"  official-vol {cid:<9} {st_tk:<16} {status:<8} -> {len(batch)} market(s)")

    # Topics that settle rarely: pull their archived settled markets as well. See
    # historical_settled() for the documented reason this is necessary.
    hist_cutoff, hist_report = None, {}
    try:
        cutoff_payload, _ = get("/historical/cutoff", retries=2)
        hist_cutoff = cutoff_payload.get("market_settled_ts")
    except RuntimeError as e:
        print(f"  ! /historical/cutoff unavailable ({e})", file=sys.stderr)
    seed_tickers = [s["ticker"] for c in cats["categories"] for s in c["seed_series"]]
    hist_rows, hist_report = historical_settled(seed_tickers)
    for t, m in hist_rows.items():
        seeded["settled"].setdefault(t, m)
    print(f"  seed markets collected: open={len(seeded['open'])} settled={len(seeded['settled'])}"
          f" (historical backfill: {len(hist_rows)}, official-vol open={official_swept_markets['open']})")
    for status in ("open", "settled"):
        have = {m.get("ticker") for m in raw[status]}
        raw[status].extend([m for t, m in seeded[status].items() if t not in have])

    # Series-level category ledger, published with the snapshot (F-65). Keyed by series ticker,
    # value = the official categories verbatim plus where they came from. Series the API did not
    # answer for are recorded with categories null — unknown, never inferred.
    ledger: dict[str, dict] = {}

    def record_series(ticker: str) -> None:
        t = (ticker or "").upper()
        if not t or t in ledger:
            return
        rec = series_index.get(t)
        if rec is None:
            try:
                d, _ = get(f"/series/{t}")
                rec = d.get("series") or {}
            except RuntimeError as e:
                print(f"  ! series {t}: {e}", file=sys.stderr)
                rec = None
        cats_official = official_categories(rec)
        ledger[t] = {
            "categories": cats_official if cats_official else None,
            "title": (rec or {}).get("title"),
            "tags": (rec or {}).get("tags"),
            "source": f"{BASE}/series/{t}",
        }

    for t in sorted({series_of(m) for st2 in ("open", "settled") for m in raw[st2]}):
        record_series(t)
    # A8D3: every series an archived swing cites keeps a verified record, even after its markets
    # leave the scan window. A bounded number of series the ledger has never seen are read fresh
    # (one GET /series/{ticker} each, the same documented endpoint record_series uses); the rest
    # keep the record the previous snapshot already verified.
    previous_ledger: dict = {}
    cited_series: set = set()
    try:
        previous_ledger = json.loads((LIVE / "markets.json").read_text()).get("series_index") or {}
    except (OSError, json.JSONDecodeError, AttributeError):
        previous_ledger = {}
    try:
        archived = json.loads((LIVE / "alerts_archive.json").read_text()).get("alerts") or []
        cited_series = {(str(a.get("ticker") or "").upper().split("-")[0])
                        for a in archived if a.get("ticker")}
    except (OSError, json.JSONDecodeError, AttributeError):
        cited_series = set()
    unseen_cited = sorted(t for t in cited_series if t and t not in ledger)
    for t in unseen_cited[:CITED_SERIES_READ_LIMIT]:
        record_series(t)
    carried_forward = carry_forward_series(ledger, previous_ledger, cited_series)
    if unseen_cited or carried_forward:
        print(f"  series ledger: {len(unseen_cited[:CITED_SERIES_READ_LIMIT])} archived series read fresh, "
              f"{carried_forward} kept from the previous snapshot (no longer in the current scan)")
    no_answer = sorted(t for t, v in ledger.items() if not v["categories"])
    print(f"  series ledger: {len(ledger)} series, {len(no_answer)} without an official categories answer")

    rows = {"open": [], "settled": []}
    unclassified = {"open": 0, "settled": 0}
    excluded_mve = {"open": 0, "settled": 0}
    excluded_topic = {"open": 0, "settled": 0}
    cat_conflicts = {"open": 0, "settled": 0}
    conflict_reasons: dict[str, int] = {}
    excluded_series = {"open": 0, "settled": 0}
    excluded_series_reasons: dict[str, str] = {}
    wrong_bucket = 0
    for status in ("open", "settled"):
        for m in raw[status]:
            st = series_of(m)
            cat_id, basis, matched_by, official, rej, detail = classify_in_scope(
                cats, m, series_index, official_map=official_map,
                record_series_fn=record_series, ledger=ledger,
            )
            if rej == "multivariate":
                excluded_mve[status] += 1
                continue
            if rej == "off_topic_or_qa":
                excluded_topic[status] += 1
                continue
            if rej == "excluded_series":
                excluded_series[status] += 1
                if detail:
                    excluded_series_reasons[st] = detail
                continue
            if rej == "unclassified":
                unclassified[status] += 1
                continue
            if rej == "conflict":
                cat_conflicts[status] += 1
                if detail:
                    conflict_reasons[detail] = conflict_reasons.get(detail, 0) + 1
                continue
            # Final safety check on the lifecycle status rather than trusting the
            # bucket: 'finalized', 'determined' and 'closed' are not open markets.
            st_status = str(m.get("status") or "").lower()
            if status == "open" and st_status in ("finalized", "determined", "closed", "settled"):
                wrong_bucket += 1
                continue
            rows[status].append(
                public_market_row(m, cat_id, basis, keep_rules=(status == "open"), official_cats=official,
                                  matched_by=matched_by)
            )

    # Rank open markets by the labelled estimate so the page leads with the
    # biggest live markets in each category, then keep a bounded window per
    # category so the committed snapshot stays small enough to load in a browser.
    # Confirmed (seed) markets are always kept, even if small.
    rows["open"].sort(key=lambda r: (r["dollars_traded_estimate"] or 0), reverse=True)
    # DEFECT (fixed 2026-11-22, arena-0553d7e9): `open_in_scope` below is read AFTER the keep
    # window trims the list, so it is the PUBLISHED row count, not the number of in-scope markets
    # the scan found. categories.html used it for both labels, and the true total was published
    # nowhere (only implied by open_rows_trimmed_for_size). Both numbers are now explicit:
    #   open_in_scope_total   — classified, non-excluded open markets this run saw (before trimming)
    #   open_published_rows   — rows actually written to the snapshot (after the per-topic keep)
    # `open_in_scope` is kept unchanged for readers of older snapshots and still equals
    # open_published_rows; nothing downstream should label it "found in scope" again.
    open_in_scope_total = len(rows["open"])
    kept, per_cat_kept, per_cat_seed = [], {}, {}
    for r in rows["open"]:
        c = r["category_id"]
        if r["category_basis"] == "seed":
            # Confirmed markets are kept generously, but a universe-wide scan can
            # return thousands of them; keep the largest first and say so.
            if per_cat_seed.get(c, 0) >= SEED_KEEP:
                continue
            per_cat_seed[c] = per_cat_seed.get(c, 0) + 1
        elif per_cat_kept.get(c, 0) >= PER_CATEGORY_KEEP:
            continue
        else:
            per_cat_kept[c] = per_cat_kept.get(c, 0) + 1
        kept.append(r)
    trimmed = len(rows["open"]) - len(kept)
    rows["open"] = kept
    open_published_rows = len(kept)
    rows["settled"].sort(key=lambda r: (r.get("settlement_ts") or ""), reverse=True)
    settled_in_scope_total = len(rows["settled"])
    settled_trimmed = max(0, settled_in_scope_total - SETTLED_KEEP)
    # ORDER MATTERS, and the first version of this fix got it wrong: choosing the published
    # set AFTER `[:SETTLED_KEEP]` looks per-topic but is not, because that 1,600-row window is
    # itself nearly all crypto 15-minute markets. Measured on the 2026-11-21T20:27Z snapshot,
    # which shipped that ordering: the per-topic split still came out crypto 178 / gas 17 /
    # culture 5, with zero elections and zero golf rows. The selection therefore runs on the
    # FULL in-scope list first, and only the leftover window is trimmed for file size.
    rows["settled"], settled_published, settled_by_cat = split_and_select_settled(rows["settled"])
    rows["settled"] = rows["settled"][:SETTLED_KEEP]
    # How the in-scope settled total was obtained, published with the number so the page can
    # print the method instead of a bare count. Two sessions have now worded this line
    # differently and a third left it out; the string lives here, next to the value it describes.
    settled_scan_truncated = bool(raw.get("_truncated", {}).get("settled"))
    settled_total_method = (
        "exact count of every settled row the paged scan returned inside the five topics"
        + (f" (including {len(hist_rows)} row(s) from GET /historical/markets for seeded series)"
           if hist_rows else "")
        + ", measured before the per-topic publish selection and before the size window"
        + ("; the scan stopped at the safety cap, so this is a lower bound"
           if settled_scan_truncated else "; the scan was not truncated, so this is exact")
        + f" (safety_scan_cap {SAFETY_SCAN_CAP}, kept window {SETTLED_KEEP}, "
          f"published {len(settled_published)} across the five topics)"
    )

    # Liquidity depth for the top few open markets per category.
    depth_rows = []
    per_cat = {}
    for r in rows["open"]:
        c = r["category_id"]
        if per_cat.get(c, 0) >= include_orderbooks:
            continue
        per_cat[c] = per_cat.get(c, 0) + 1
        ob = orderbook_summary(r["ticker"])
        depth_rows.append({"ticker": r["ticker"], "category_id": c, "orderbook": ob})

    hist_path = LIVE / "price_history.json"
    hist = {}
    if hist_path.exists():
        try:
            hist = json.loads(hist_path.read_text()).get("series", {})
        except json.JSONDecodeError:
            hist = {}
    update_price_history(hist, raw["open"], pinned_alert_times())
    # Keep history for markets that are shown AND for every market that still carries a
    # recorded price swing, so an alert never points at an empty graph.
    # The original rule kept only `rows["open"]` (the capped, ranked window). A swing is
    # archived by scripts/build_alerts.py the moment it is observed, and the ranking then
    # rotates that market out of the window, so its observations were deleted while the
    # alert that cites them lived on. Measured on the 2026-11-21T00:50Z snapshot: of the 7
    # distinct tickers in data/live/alerts_archive.json, the 3 KXDEMOFUTHOURLY-* markets
    # had 0 observations left, so dashboard.html rendered "No observations in this window
    # yet" for exactly the series the alert was about. Alerts are read here as a file, not
    # written (build_alerts.py stays the only writer and this script runs first).
    # NOTE: alerts.json and alerts_archive.json are written by scripts/build_alerts.py,
    # which the collect workflow runs right after this script. This file deliberately
    # does NOT write alerts (one writer, one schema); it only probes CORS headers.
    watch = {r["ticker"] for r in rows["open"]}
    archived_tickers: set = set()
    try:
        archive = json.loads((LIVE / "alerts_archive.json").read_text()).get("alerts") or []
        archived_tickers = {a["ticker"] for a in archive if a.get("ticker")}
        watch |= archived_tickers
    except (OSError, json.JSONDecodeError, AttributeError):
        pass  # first run: no archive yet, so open rows alone define the watch set
    hist = {k: v for k, v in hist.items() if k in watch}
    # Restore what an earlier, prunier run already deleted: archive-cited tickers with no
    # observations left at all are rebuilt from their own official candles (see the docstring).
    missing_hist = sorted(t for t in archived_tickers if not hist.get(t, {}).get("observations"))
    hist, hist_backfilled = backfill_from_candles(hist, missing_hist)


    payload = {
        "schema": 1,
        "environment": "demo",
        "base_url": BASE,
        "collected_at": utcnow(),
        "started_at": started,
        "sources": {
            "environments": "https://docs.kalshi.com/getting_started/api_environments",
            "markets": "https://docs.kalshi.com/api-reference/market/get-markets",
            "orderbook": "https://docs.kalshi.com/api-reference/market/get-market-orderbook",
            "lifecycle": "https://docs.kalshi.com/getting_started/market_lifecycle",
            "candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
        },
        "counts": {
            "open_total_scanned": len(raw["open"]),
            "settled_total_scanned": len(raw["settled"]),
            # `open_in_scope` is the legacy name for the PUBLISHED row count (see the note at the
            # keep window). The scan total and the published count are published separately so a
            # page can never print one under the other's label.
            "open_in_scope": len(rows["open"]),
            "open_in_scope_total": open_in_scope_total,
            "open_published_rows": open_published_rows,
            "settled_in_scope": len(rows["settled"]),
            "settled_published_rows": len(settled_published),
            "open_out_of_scope": unclassified["open"],
            "settled_out_of_scope": unclassified["settled"],
            "open_excluded_multivariate": excluded_mve["open"],
            "settled_excluded_multivariate": excluded_mve["settled"],
            # Published, never silent: scope corrections the brief requires.
            "open_excluded_off_topic_or_qa": excluded_topic["open"],
            "settled_excluded_off_topic_or_qa": excluded_topic["settled"],
            # Category integrity (F-65): rows the topic matched by keyword or seed whose OWN
            # official series record files them under a category the topic cannot contain.
            "open_excluded_series": excluded_series["open"],
            "settled_excluded_series": excluded_series["settled"],
            "excluded_series_detail": dict(sorted(excluded_series_reasons.items())),
            "official_discovery_calls": official_calls,
            "official_discovery_series": len(official_map),
            "official_volume_swept_series": official_volume_swept,
            "official_volume_swept_open_markets": official_swept_markets["open"],
            "official_volume_swept_settled_markets": official_swept_markets["settled"],
            "open_excluded_category_conflict": cat_conflicts["open"],
            "settled_excluded_category_conflict": cat_conflicts["settled"],
            "category_conflict_reasons": dict(sorted(conflict_reasons.items())),
            "category_compatible_official": {k: sorted(v) for k, v in CATEGORY_COMPATIBLE.items()},
            "category_never_in_scope_official": sorted(CATEGORY_NEVER_IN_SCOPE),
            "excluded_series_reasons": dict(EXCLUDE_KEYWORD_SERIES),
            "seed_markets_found": len(seeded["open"]) + len(seeded["settled"]),
            # A8D3: verified series records kept from the previous snapshot because the current
            # scan no longer covers them (their events resolved and left the window).
            "series_ledger_carried_forward": carried_forward,
            # Scan completeness, published: what the ranking below could see at all.
            "open_paging_truncated_at_safety_cap": bool(raw.get("_truncated", {}).get("open")),
            "settled_paging_truncated_at_safety_cap": bool(raw.get("_truncated", {}).get("settled")),
            "safety_scan_cap": SAFETY_SCAN_CAP,
            "settled_rows_trimmed_for_size": settled_trimmed,
            # What was published out of what was in scope, and the per-topic split:
            # the row cap must never be spent by one high-frequency topic alone.
            "settled_in_scope_total": settled_in_scope_total,
            "settled_kept_window": len(rows["settled"]),
            "settled_published": len(settled_published),
            "settled_publish_cap": SETTLED_PUBLISH_CAP,
            "settled_published_by_category": settled_by_cat,
            "settled_in_scope_total_method": settled_total_method,
            "historical_cutoff_market_settled_ts": hist_cutoff,
            "historical_backfill_rows": len(hist_rows),
            "price_history_backfilled_from_candles": hist_backfilled,
            "price_history_archived_tickers": len(archived_tickers),
            "historical_backfill_report": hist_report,
            "open_rows_trimmed_for_size": trimmed,
            "rows_dropped_wrong_status": wrong_bucket,
        },
        "series_index": dict(sorted(ledger.items())),
        "open_markets": rows["open"],
        "settled_markets": settled_published,
        "liquidity": depth_rows,
        "disclaimers": [
            "All values are from the Kalshi DEMO environment (mock funds). The official docs warn that demo prices and behaviour may not reflect real markets.",
            "dollars_traded_estimate = volume_fp x last_price_dollars. It is an estimate computed here, not an official Kalshi field.",
            "category_basis=keyword rows are heuristic word-boundary matches and are flagged for review; only basis=seed rows are confirmed by the official fee schedule.",
            "Multivariate (combo) markets are excluded from every category: they combine unrelated legs and have their own lifecycle channel.",
            "Two scope corrections are published in counts: natural-gas futures (KXNATGAS15M, official series category Commodities / Pyth NATGAS) are not retail gas prices and Kalshi demo QA fixtures are not live events. Seed series can never be excluded by these rules.",
            "series_index records, per series ticker, the official categories returned by GET /series for that series (null when the API did not answer), so a row's topic can be re-checked after the row leaves the open scan.",
            "Category integrity: every row carries series_categories, the official categories returned by GET /series for its series. A row whose official categories are known and contain none of that topic's compatible categories is counted in *_excluded_category_conflict with its reason, never published under the topic. A row with no categories field returned stays published (unknown is not a contradiction).",
            "result can be yes, no, scalar, or empty. Nothing is coerced to yes/no.",
        ],
    }
    LIVE.mkdir(parents=True, exist_ok=True)
    (LIVE / "markets.json").write_text(json.dumps(payload, indent=1))
    (LIVE / "price_history.json").write_text(
        json.dumps({"schema": 1, "note": "Observations accumulated from GET /markets last_price_dollars on each collector run. Seconds resolution is only possible by accumulation because candlesticks support 1/60/1440-minute intervals only.", "series": hist}, indent=1)
    )

    print(f"  wrote {LIVE/'markets.json'} ({len(rows['open'])} in-scope open markets)")
    return payload


def probe_cors(origin="https://kanlerxz87-cyber.github.io"):
    """Record what CORS headers the demo API actually returns for our origin.

    Kalshi does not document CORS for this API, so the header set is measured,
    never assumed: a real GET with the site's Origin is sent to the public
    /exchange/status endpoint (the same probe the collect workflow curls) and
    only OBSERVED headers are recorded. A missing header is recorded as null.
    """
    url = f"{BASE}/exchange/status"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": UA,
        "Origin": origin,
    })
    result = {
        "checked_at": utcnow(),
        "origin_tested": origin,
        "request_url": url,
        "status_code": None,
        "access_control_allow_origin": None,
        "access_control_allow_methods": None,
        "access_control_allow_headers": None,
        "note": "Only headers actually observed on the response are recorded; absent headers stay null. CORS behaviour is undocumented (see flagged.html F-24).",
    }
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            result["status_code"] = r.status
            for h in ("access-control-allow-origin", "access-control-allow-methods", "access-control-allow-headers"):
                v = r.headers.get(h)
                key = "access_control_allow_" + h.split("allow-")[1]
                if v is not None:
                    result[key] = v
    except urllib.error.HTTPError as e:
        result["status_code"] = e.code
    except Exception as e:  # network unreachable — recorded honestly, nothing inferred
        result["error"] = f"{type(e).__name__}: {e}"
    (LIVE / "cors.json").write_text(json.dumps(result, indent=1))
    print(f"  wrote {LIVE/'cors.json'} (status={result['status_code']}, allow-origin={result['access_control_allow_origin']})")
    return result


def main():
    ap = argparse.ArgumentParser(description="Collect Kalshi demo public data for the dashboard.")
    ap.add_argument("--orderbooks", type=int, default=4, help="orderbooks per category")
    ap.add_argument("--no-cors-probe", action="store_true", help="skip the CORS header probe")
    args = ap.parse_args()
    try:
        build(include_orderbooks=args.orderbooks)
    except RuntimeError as e:
        print(f"COLLECT_FAILED: {e}", file=sys.stderr)
        return 2
    if not args.no_cors_probe:
        try:
            probe_cors()
        except Exception as e:
            print(f"  ! cors probe failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
