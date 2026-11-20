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
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LIVE = DATA / "live"

BASE = os.environ.get("KALSHI_BASE", "https://external-api.demo.kalshi.co/trade-api/v2")
UA = "KalshiDash3-collector/1.0 (+https://github.com/kanlerxz87-cyber/KalshiDash3)"

# Documented reference: https://docs.kalshi.com/api-reference/market/get-markets
PRICE_HISTORY_LIMIT = 240  # points kept per market


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


def classify(cats, series_ticker, series_title, series_categories, market_title):
    """Return (category_id, basis) for a market, or (None, None).

    basis="seed" means the series ticker is listed in the official fee schedule.
    basis="keyword" means a heuristic title/series match. The distinction is
    carried all the way to the rendered table.
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
            if kw.lower() in hay:
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
        "series_ticker": m.get("series_ticker"),
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

    rows = {"open": [], "settled": []}
    unclassified = {"open": 0, "settled": 0}
    for status in ("open", "settled"):
        for m in raw[status]:
            st = (m.get("series_ticker") or "").upper()
            s = series_index.get(st, {})
            cat_id, basis = classify(
                cats,
                m.get("series_ticker"),
                s.get("title"),
                " ".join(s.get("categories") or []) if s.get("categories") else s.get("category"),
                m.get("title") or m.get("yes_sub_title"),
            )
            if not cat_id:
                unclassified[status] += 1
                continue
            rows[status].append(public_market_row(m, cat_id, basis))

    # Rank open markets by the labelled estimate so the page leads with the
    # biggest live markets in each category.
    rows["open"].sort(key=lambda r: (r["dollars_traded_estimate"] or 0), reverse=True)
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
    watch = [r["ticker"] for r in rows["open"][:120]]
    update_price_history(hist, raw["open"])
    hist = {k: v for k, v in hist.items() if k in set(watch) | set(hist.keys())}

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
        },
        "open_markets": rows["open"],
        "settled_markets": rows["settled"][:200],
        "liquidity": depth_rows,
        "disclaimers": [
            "All values are from the Kalshi DEMO environment (mock funds). The official docs warn that demo prices and behaviour may not reflect real markets.",
            "dollars_traded_estimate = volume_fp x last_price_dollars. It is an estimate computed here, not an official Kalshi field.",
            "category_basis=keyword rows are heuristic matches and are flagged for review; only basis=seed rows are confirmed by the official fee schedule.",
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


def main():
    ap = argparse.ArgumentParser(description="Collect Kalshi demo public data for the dashboard.")
    ap.add_argument("--orderbooks", type=int, default=4, help="orderbooks per category")
    args = ap.parse_args()
    try:
        build(include_orderbooks=args.orderbooks)
    except RuntimeError as e:
        print(f"COLLECT_FAILED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
