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
PER_CATEGORY_KEEP = 120    # rows kept per category in the committed snapshot


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
    """
    out = {"open": [], "settled": []}
    for status, cap in (("open", 4000), ("settled", 1200)):
        cursor, seen = "", 0
        while True:
            d, _ = get("/markets", {"status": status, "limit": 1000, "cursor": cursor or None})
            batch = d.get("markets") or []
            out[status].extend(batch)
            seen += len(batch)
            cursor = d.get("cursor") or ""
            if not cursor or not batch or seen >= cap:
                break
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


def public_market_row(m, cat_id, basis):
    return {
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
                try:
                    d, _ = get("/markets", {"series_ticker": seed["ticker"], "status": status, "limit": 1000})
                except RuntimeError as e:
                    print(f"  ! seed {seed['ticker']} {status}: {e}", file=sys.stderr)
                    continue
                for m in d.get("markets") or []:
                    # Keep the buckets separate: a finalized market must never
                    # appear in the open list. The status filter is authoritative
                    # (https://docs.kalshi.com/getting_started/market_lifecycle).
                    seeded[status][m.get("ticker")] = m
                print(f"  seed {seed['ticker']:<16} {status:<8} -> {len(d.get('markets') or [])} market(s)")
    print(f"  seed markets collected: open={len(seeded['open'])} settled={len(seeded['settled'])}")
    for status in ("open", "settled"):
        have = {m.get("ticker") for m in raw[status]}
        raw[status].extend([m for t, m in seeded[status].items() if t not in have])

    rows = {"open": [], "settled": []}
    unclassified = {"open": 0, "settled": 0}
    excluded_mve = {"open": 0, "settled": 0}
    wrong_bucket = 0
    for status in ("open", "settled"):
        for m in raw[status]:
            if is_multivariate(m):
                excluded_mve[status] += 1
                continue
            st = series_of(m)
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
            rows[status].append(public_market_row(m, cat_id, basis))

    # Rank open markets by the labelled estimate so the page leads with the
    # biggest live markets in each category, then keep a bounded window per
    # category so the committed snapshot stays small enough to load in a browser.
    # Confirmed (seed) markets are always kept, even if small.
    rows["open"].sort(key=lambda r: (r["dollars_traded_estimate"] or 0), reverse=True)
    kept, per_cat_kept = [], {}
    for r in rows["open"]:
        c = r["category_id"]
        if r["category_basis"] == "seed" or per_cat_kept.get(c, 0) < PER_CATEGORY_KEEP:
            if r["category_basis"] != "seed":
                per_cat_kept[c] = per_cat_kept.get(c, 0) + 1
            kept.append(r)
    trimmed = len(rows["open"]) - len(kept)
    rows["open"] = kept
    rows["settled"].sort(key=lambda r: (r.get("settlement_ts") or ""), reverse=True)

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
    # Only keep history for markets that are actually shown, so the file stays small.
    # NOTE: alerts.json and alerts_archive.json are written by scripts/build_alerts.py,
    # which the collect workflow runs right after this script. This file deliberately
    # does NOT write alerts (one writer, one schema); it only probes CORS headers.
    watch = {r["ticker"] for r in rows["open"]}
    hist = {k: v for k, v in hist.items() if k in watch}


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
            "open_in_scope": len(rows["open"]),
            "settled_in_scope": len(rows["settled"]),
            "open_out_of_scope": unclassified["open"],
            "settled_out_of_scope": unclassified["settled"],
            "open_excluded_multivariate": excluded_mve["open"],
            "settled_excluded_multivariate": excluded_mve["settled"],
            "seed_markets_found": len(seeded["open"]) + len(seeded["settled"]),
            "open_rows_trimmed_for_size": trimmed,
            "rows_dropped_wrong_status": wrong_bucket,
        },
        "open_markets": rows["open"],
        "settled_markets": rows["settled"][:200],
        "liquidity": depth_rows,
        "disclaimers": [
            "All values are from the Kalshi DEMO environment (mock funds). The official docs warn that demo prices and behaviour may not reflect real markets.",
            "dollars_traded_estimate = volume_fp x last_price_dollars. It is an estimate computed here, not an official Kalshi field.",
            "category_basis=keyword rows are heuristic word-boundary matches and are flagged for review; only basis=seed rows are confirmed by the official fee schedule.",
            "Multivariate (combo) markets are excluded from every category: they combine unrelated legs and have their own lifecycle channel.",
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
        "note": "Only headers actually observed on the response are recorded; absent headers stay null. CORS behaviour is undocumented (see flagged.html F-14).",
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
