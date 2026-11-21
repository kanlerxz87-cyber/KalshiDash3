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
SETTLED_PUBLISHED_CAP = 600  # settled rows published, allocated ACROSS topics (see select_settled)
SETTLED_RESERVE_PER_CATEGORY = 60  # each topic's own newest rows, kept before any leftover is shared
SAFETY_SCAN_CAP = 25000    # paging safety stop per status; truncation is published, never hidden

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
}
EXCLUDE_TITLE_RE = re.compile(r"demo portfolio test|portfolio cash out|\bqa\s*\d", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(path: str, params: dict | None = None, retries: int = 3):
    """GET a public endpoint with small exponential backoff.

    Documented behaviour: 429 returns too_many_requests with no Retry-After and
    no penalty (https://docs.kalshi.com/getting_started/rate_limits).
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
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8")), url
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except Exception as e:  # network / TLS / DNS
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{last} for {url}")


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


def fetch_series_index():
    """GET /series — used only to enrich titles/categories.

    https://docs.kalshi.com/api-reference/market/get-series-list
    The endpoint is not paginated in the documented sense (no cursor in the
    response schema), so a single call is made and failures are non-fatal.
    """
    try:
        d, _ = get("/series")
        return {s.get("ticker", "").upper(): s for s in d.get("series", []) if s.get("ticker")}
    except RuntimeError as e:
        print(f"  ! /series unavailable ({e}); continuing without it", file=sys.stderr)
        return {}


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
            # mve_filter=exclude is a documented query parameter of GET /markets
            # ("'only' returns only multivariate events, 'exclude' excludes multivariate
            # events", https://docs.kalshi.com/api-reference/market/get-markets). Without
            # it the safety cap is spent on combo listings that are then discarded by
            # is_multivariate(), so the cap truncates real markets instead of combos:
            # the collector published open_in_scope 749 while scripts/roi_scan.py, which
            # already sent this filter, counted 1,365 in-scope open markets for the same
            # exchange. The local is_multivariate() check is kept as a belt-and-braces
            # guard in case the parameter is ever ignored.
            d, _ = get("/markets", {"status": status, "limit": 1000, "cursor": cursor or None,
                                    "mve_filter": "exclude"})
            batch = d.get("markets") or []
            out[status].extend(batch)
            seen += len(batch)
            cursor = d.get("cursor") or ""
            if not cursor or not batch:
                break
            if seen >= cap:
                truncated = True
                break
        out["_truncated"][status] = truncated
        # Deduplicate by ticker: documented as required when paging by close time.
        dedup = {m["ticker"]: m for m in out[status] if m.get("ticker")}
        out[status] = list(dedup.values())
    return out


def select_settled(rows, cap=SETTLED_PUBLISHED_CAP, reserve=SETTLED_RESERVE_PER_CATEGORY):
    """Choose which settled markets to publish, FAIRLY ACROSS TOPICS.

    Why this exists (measured on the committed 2026-11-21T15:21Z snapshot before the fix):
    sorting every settled market by settlement_ts and keeping the newest N published
    200 rows of which **198 were crypto** (culture 2, gas 0, elections 0, golf 0). The
    demo exchange lists 15-minute crypto series that settle roughly 96 times a day, so a
    single newest-first queue is structurally starved of every slower topic. The brief
    asks for events to be tracked "until the events have resolved", per topic, so a
    resolution feed that can only show crypto is not a feed.

    Allocation, stated so the page can disclose it:
      1. each topic gets its own newest `reserve` rows;
      2. any capacity left over goes round-robin across the topics (newest-first inside a
         topic), so a topic that has no recent settlements costs nothing and a fast topic
         can only ever take the leftover capacity, never another topic's reserve;
      3. the published list is re-sorted newest-first overall for display.
    The published counts per category are returned so they can be written into `counts`
    rather than inferred by a reader.
    """
    by_cat: dict[str, list] = {}
    for r in sorted(rows, key=lambda r: (r.get("settlement_ts") or ""), reverse=True):
        by_cat.setdefault(r.get("category_id") or "unknown", []).append(r)
    picked: dict[str, list] = {c: lst[:reserve] for c, lst in by_cat.items()}
    used = sum(len(v) for v in picked.values())
    if used < cap:
        idx: dict[str, int] = {c: len(picked[c]) for c in by_cat}
        progressed = True
        while used < cap and progressed:
            progressed = False
            for c, lst in by_cat.items():
                if used >= cap:
                    break
                i = idx[c]
                if i < len(lst):
                    picked[c].append(lst[i])
                    idx[c] = i + 1
                    used += 1
                    progressed = True
    published = [r for lst in picked.values() for r in lst]
    published.sort(key=lambda r: (r.get("settlement_ts") or ""), reverse=True)
    per_cat = {c: len(v) for c, v in sorted(picked.items())}
    return published, per_cat


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


def update_price_history(hist, rows):
    """Append a live observation per market and keep a bounded window.

    Seconds-resolution history cannot be requested from Kalshi: candlesticks
    only support 1/60/1440-minute intervals (F-29). So the only way to have a
    seconds-resolution series is to accumulate REST observations over time,
    which is exactly what this file does on every run.
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
        series["observations"] = obs[-PRICE_HISTORY_LIMIT:]
        hist[t] = series
    return hist


def backfill_from_candles(hist, tickers, max_series=12):
    """Rebuild a missing observation series from Kalshi's official 1-minute candles.

    Why: an archived >=$0.10 alert whose observations were pruned before the retention fix
    above can never be charted again by accumulation alone — the market has already settled,
    so no future GET /markets will ever report it. The move itself is still published by
    Kalshi, in the market's own candlestick history, so the chart can show the real series
    around the alert instead of an empty box.

    Only markets that (a) appear in the alert archive and (b) have no observations at all are
    backfilled, so this never overwrites collected data and costs at most `max_series`
    requests. Each backfilled point is a candle CLOSE, not a REST last_price observation, and
    is marked "source": "candle" so the two can be told apart. Documented restrictions used
    here: period_interval is 1/60/1440 minutes, start_ts/end_ts are seconds, and one request
    spans at most 5,000 periods (https://docs.kalshi.com/api-reference/market/get-market-candlesticks).
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
        start = end - 5000 * 60            # 5,000 one-minute periods, the documented maximum
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
            when = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            obs.append({
                "t": when,
                "last": close,
                "yes_bid": fnum((c.get("yes_bid") or {}).get("close_dollars")),
                "yes_ask": fnum((c.get("yes_ask") or {}).get("close_dollars")),
                "volume_fp": c.get("volume_fp"),
                "source": "candle",
            })
        if obs:
            hist[ticker] = {"observations": obs[-PRICE_HISTORY_LIMIT:],
                            "backfilled_from": f"{BASE}{path}?start_ts={start}&end_ts={end}&period_interval=1",
                            "backfilled_at": utcnow()}
            done += 1
            print(f"  candle backfill {ticker}: {len(obs)} one-minute closes")
    return hist, done


def public_market_row(m, cat_id, basis, keep_rules=False):
    row = {
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "series_ticker": series_of(m),
        "series_ticker_from_api": m.get("series_ticker"),
        "title": m.get("title") or m.get("yes_sub_title") or "",
        "category_id": cat_id,
        "category_basis": basis,
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


def build(include_orderbooks: int = 4, candlestick_points: int = 0):
    cats = load_categories()
    started = utcnow()
    print(f"collect: {BASE}")
    series_index = fetch_series_index()
    print(f"  series index: {len(series_index)} entries")
    raw = scan_markets()
    print(f"  markets: open={len(raw['open'])} settled={len(raw['settled'])}")

    # The paged scan is capped, and the demo exchange is full of multivariate
    # combos, so a confirmed fee-schedule series can fall outside the window.
    # Query every seed series explicitly so "confirmed" data is never lost.
    seeded = {"open": {}, "settled": {}}
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
    print(f"  seed markets collected: open={len(seeded['open'])} settled={len(seeded['settled'])}")
    for status in ("open", "settled"):
        have = {m.get("ticker") for m in raw[status]}
        raw[status].extend([m for t, m in seeded[status].items() if t not in have])

    rows = {"open": [], "settled": []}
    unclassified = {"open": 0, "settled": 0}
    excluded_mve = {"open": 0, "settled": 0}
    excluded_topic = {"open": 0, "settled": 0}
    wrong_bucket = 0
    for status in ("open", "settled"):
        for m in raw[status]:
            if is_multivariate(m):
                excluded_mve[status] += 1
                continue
            st = series_of(m)
            if st in EXCLUDE_KEYWORD_SERIES or EXCLUDE_TITLE_RE.search(
                " ".join(x for x in [m.get("title") or "", (series_index.get(st, {}) or {}).get("title") or ""] if x)
            ):
                excluded_topic[status] += 1
                continue
            s = series_index.get(st, {})
            cat_id, basis = classify(
                cats,
                st,
                s.get("title"),
                " ".join(s.get("categories") or []) if s.get("categories") else s.get("category"),
                m.get("title") or m.get("yes_sub_title"),
            )
            if not cat_id:
                unclassified[status] += 1
                continue
            # Final safety check on the lifecycle status rather than trusting the
            # bucket: 'finalized', 'determined' and 'closed' are not open markets.
            st_status = str(m.get("status") or "").lower()
            if status == "open" and st_status in ("finalized", "determined", "closed", "settled"):
                wrong_bucket += 1
                continue
            rows[status].append(public_market_row(m, cat_id, basis, keep_rules=(status == "open")))

    # Rank open markets by the labelled estimate so the page leads with the
    # biggest live markets in each category, then keep a bounded window per
    # category so the committed snapshot stays small enough to load in a browser.
    # Confirmed (seed) markets are always kept, even if small.
    rows["open"].sort(key=lambda r: (r["dollars_traded_estimate"] or 0), reverse=True)
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
    rows["settled"].sort(key=lambda r: (r.get("settlement_ts") or ""), reverse=True)
    settled_in_scope_total = len(rows["settled"])
    settled_rows, settled_by_category = select_settled(rows["settled"])
    settled_trimmed = max(0, settled_in_scope_total - len(settled_rows))
    rows["settled"] = settled_rows

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
    update_price_history(hist, raw["open"])
    # Which tickers keep their observation history. This used to be "open rows only",
    # and that silently deleted the history of markets the alert feed was still pointing
    # at: scripts/build_alerts.py archives a >=$0.10 swing forever, but once a market
    # rotated out of the capped open window (or settled) its observations were pruned, so
    # dashboard.html#TICKER from an alert rendered "No observations in this window yet"
    # for the exact series the alert was about (measured: 3 of 7 tickers in
    # alerts_archive.json had 0 observations left on the 2026-11-21T00:50Z snapshot).
    # The watch set is therefore open ∪ recently settled ∪ every ticker that already has
    # an archived alert. The archive is read here, never written: its single writer stays
    # scripts/build_alerts.py.
    archived_tickers: set[str] = set()
    archive_path = LIVE / "alerts_archive.json"
    if archive_path.exists():
        try:
            for a in json.loads(archive_path.read_text()).get("alerts", []):
                if a.get("ticker"):
                    archived_tickers.add(a["ticker"])
        except (json.JSONDecodeError, OSError):
            archived_tickers = set()
    watch = ({r["ticker"] for r in rows["open"]}
             | {r["ticker"] for r in rows["settled"]}
             | archived_tickers)
    kept_hist = {k: v for k, v in hist.items() if k in watch}
    hist_pruned = len(hist) - len(kept_hist)
    hist = kept_hist
    # Tickers an archived alert names but for which no observation survived (pruned before
    # the retention fix, or collected while the market was outside the open window) are
    # rebuilt from the market's own official candles, and only those.
    missing = sorted(t for t in archived_tickers if not hist.get(t, {}).get("observations"))
    hist, backfilled = backfill_from_candles(hist, missing)

    # Exact total, or the best defensible one when the scan was capped (see counts).
    prev_counts, prev_settled = {}, []
    try:
        prev_doc = json.loads((LIVE / "markets.json").read_text())
        prev_counts = prev_doc.get("counts") or {}
        prev_settled = prev_doc.get("settled_markets") or []
    except (OSError, json.JSONDecodeError):
        prev_counts = {}
    if not raw.get("_truncated", {}).get("settled"):
        settled_total_published = settled_in_scope_total
        settled_total_method = "exact: this run paged the settled scan to exhaustion"
    else:
        base = prev_counts.get("settled_in_scope_total")
        if isinstance(base, int) and base > 0:
            since = prev_counts.get("collected_at") or None
            known = {r.get("ticker") for r in prev_settled}
            known |= {r.get("ticker") for r in rows["settled"]}
            new_ticks = {r.get("ticker") for r in rows["settled"]} - {r.get("ticker") for r in prev_settled}
            settled_total_published = base + len(new_ticks)
            settled_total_method = (
                "carried forward: the settled scan was truncated by the %d-row safety cap, so the "
                "previous run's exact total (%s) plus the %d settled tickers this run had not seen "
                "before. Tickers settled in the capped gap and never observed are not counted."
                % (SAFETY_SCAN_CAP, f"{base:,}", len(new_ticks)))
            del since, known
        else:
            settled_total_published = settled_in_scope_total
            settled_total_method = (
                "lower bound: the settled scan was truncated by the %d-row safety cap and no "
                "previous exact total was stored, so this is only what this run's window held."
                % SAFETY_SCAN_CAP)

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
            # What this page/table actually PUBLISHES (kept for schema compatibility). These are
            # not totals: the scan finds far more, which is why the totals below are published
            # separately and every page labels the difference (F-72).
            "open_in_scope": len(rows["open"]),
            "settled_in_scope": len(rows["settled"]),
            "open_published_rows": len(rows["open"]),
            "settled_published_rows": len(rows["settled"]),
            "open_out_of_scope": unclassified["open"],
            "settled_out_of_scope": unclassified["settled"],
            "open_excluded_multivariate": excluded_mve["open"],
            "settled_excluded_multivariate": excluded_mve["settled"],
            # Published, never silent: scope corrections the brief requires.
            "open_excluded_off_topic_or_qa": excluded_topic["open"],
            "settled_excluded_off_topic_or_qa": excluded_topic["settled"],
            "excluded_series_reasons": dict(EXCLUDE_KEYWORD_SERIES),
            "seed_markets_found": len(seeded["open"]) + len(seeded["settled"]),
            # Scan completeness, published: what the ranking below could see at all.
            "open_paging_truncated_at_safety_cap": bool(raw.get("_truncated", {}).get("open")),
            "settled_paging_truncated_at_safety_cap": bool(raw.get("_truncated", {}).get("settled")),
            "safety_scan_cap": SAFETY_SCAN_CAP,
            "scan_sends_mve_filter_exclude": True,
            # Resolution history is allocated across topics, and the allocation is
            # published so a reader never has to infer why a topic is thin.
            # Exact while paging ran to exhaustion. When the safety cap stopped the scan, the
            # window covers only the newest N settled markets, so the previous exact total is
            # carried forward plus this run's newly settled tickers. The method is published
            # next to the number so neither kind of value is passed off as the other.
            "settled_in_scope_total": settled_total_published,
            "settled_in_scope_total_method": settled_total_method,
            "settled_in_scope_this_run_window": settled_in_scope_total,
            "settled_published": len(rows["settled"]),
            "settled_published_cap": SETTLED_PUBLISHED_CAP,
            "settled_published_reserve_per_category": SETTLED_RESERVE_PER_CATEGORY,
            "settled_published_by_category": settled_by_category,
            "settled_published_by_category_allocation": (
                "per-topic reserve of %d newest rows each, then round-robin for any leftover "
                "capacity, then re-sorted newest-first" % SETTLED_RESERVE_PER_CATEGORY),
            "settled_rows_trimmed_for_size": settled_trimmed,
            "open_rows_trimmed_for_size": trimmed,
            "rows_dropped_wrong_status": wrong_bucket,
            # Price-history retention: open + settled + every ticker with an archived alert.
            "price_history_series_kept": len(hist),
            "price_history_series_pruned": hist_pruned,
            "price_history_kept_for_archived_alerts": len(archived_tickers),
            "price_history_backfilled_from_candles": backfilled,
            "price_history_backfill_note": (
                "Archived-alert tickers with no surviving observation are rebuilt from "
                "GET /series/{series}/markets/{ticker}/candlesticks (1-minute closes, marked "
                "source=candle) so a published swing can always be charted."),
        },
        "open_markets": rows["open"],
        "settled_markets": rows["settled"],
        "liquidity": depth_rows,
        "disclaimers": [
            "All values are from the Kalshi DEMO environment (mock funds). The official docs warn that demo prices and behaviour may not reflect real markets.",
            "dollars_traded_estimate = volume_fp x last_price_dollars. It is an estimate computed here, not an official Kalshi field.",
            "category_basis=keyword rows are heuristic word-boundary matches and are flagged for review; only basis=seed rows are confirmed by the official fee schedule.",
            "Multivariate (combo) markets are excluded from every category: they combine unrelated legs and have their own lifecycle channel.",
            "Two scope corrections are published in counts: natural-gas futures (KXNATGAS15M, official series category Commodities / Pyth NATGAS) are not retail gas prices and Kalshi demo QA fixtures are not live events. Seed series can never be excluded by these rules.",
            "result can be yes, no, scalar, or empty. Nothing is coerced to yes/no.",
        ],
    }
    LIVE.mkdir(parents=True, exist_ok=True)
    (LIVE / "markets.json").write_text(json.dumps(payload, indent=1))
    (LIVE / "price_history.json").write_text(
        json.dumps({"schema": 1, "note": "Observations accumulated from GET /markets last_price_dollars on each collector run. Seconds resolution is only possible by accumulation because candlesticks support 1/60/1440-minute intervals only.", "series": hist}, indent=1)
    )

    print(f"  wrote {LIVE/'markets.json'} ({len(rows['open'])} in-scope open markets, "
          f"{len(rows['settled'])} settled rows {settled_by_category})")
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
