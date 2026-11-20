#!/usr/bin/env python3
"""Collect official event metadata for every event in scope.

Reads the committed snapshot (data/live/markets.json), works out which events
the five requested categories cover, and asks the official Kalshi demo API for
each of those events' records. Only fields the API returned are kept:

  title, sub_title, category, strike_date, series_ticker
  settlement_sources[]  -> the official reference websites for the event
  kalshi_public_url     -> the public Kalshi page for the event (verified
                           with an HTTP request, so a dead link is never
                           published as if it worked)

Why settlement_sources matter: Kalshi resolves each contract against named
sources (AAA for US gas prices, CF Benchmarks for crypto reference prices, the
PGA Tour / ESPN / Fox Sports for golf, news wires for elections and culture).
Those are exactly the websites whose data can move the contract, so they are
the honest, official "where to look" links for a sudden price jump. They are
NOT a claim that any one of them moved at the moment of a jump - the API
publishes no news feed, so causation stays unverified and is labelled as such
on the site and on the Flagged page.

Official sources
  Get Event ....... https://docs.kalshi.com/api-reference/events/get-event
  Get Events ...... https://docs.kalshi.com/api-reference/events/get-events
  Demo env ........ https://docs.kalshi.com/getting_started/demo_env

Writes: data/live/event_refs.json

Exit codes: 0 success (including "no events in scope"), 2 the snapshot is
missing/unreadable.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live"
BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
UA = "KalshiDash3-collector/1.0 (+https://github.com/kanlerxz87-cyber/KalshiDash3)"

SOURCES = {
    "get_event": "https://docs.kalshi.com/api-reference/events/get-event",
    "get_events": "https://docs.kalshi.com/api-reference/events/get-events",
    "demo_env": "https://docs.kalshi.com/getting_started/demo_env",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_json(path: str, retries: int = 3):
    url = BASE + path
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
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{last} for {url}")


def verify_public_url(url: str, timeout: int = 20):
    """Return (http_status, final_url) for a public Kalshi page, or (None, None).

    A link is only published as working when the request actually succeeded,
    so the site never sends a reader to a 404.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return getattr(r, "status", 200), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, url
    except Exception:
        return None, None


def build() -> int:
    snap_path = LIVE / "markets.json"
    if not snap_path.exists():
        print(f"missing input: {snap_path}", file=sys.stderr)
        return 2
    try:
        snap = json.loads(snap_path.read_text())
    except json.JSONDecodeError as e:
        print(f"invalid JSON {snap_path}: {e}", file=sys.stderr)
        return 2

    # Which events are in scope? Only events that appear on an in-scope market.
    events: dict[str, dict] = {}
    for bucket in ("open_markets", "settled_markets"):
        for row in snap.get(bucket) or []:
            et = row.get("event_ticker")
            if not et:
                continue
            rec = events.setdefault(et, {
                "event_ticker": et,
                "series_ticker": row.get("series_ticker"),
                "categories": set(),
                "tickers": set(),
            })
            if row.get("category_id"):
                rec["categories"].add(row["category_id"])
            if row.get("ticker"):
                rec["tickers"].add(row["ticker"])

    # One compact request per series covers every event of that series.
    by_series: dict[str, list[str]] = {}
    for et, rec in events.items():
        by_series.setdefault(rec["series_ticker"] or "", []).append(et)

    fetched: dict[str, dict] = {}
    for series, ets in sorted(by_series.items()):
        if not series:
            continue
        try:
            payload, url = get_json(f"/events?series_ticker={series}&limit=200")
        except RuntimeError as e:
            print(f"  series {series}: {e}", file=sys.stderr)
            continue
        for ev in (payload or {}).get("events") or []:
            if ev.get("event_ticker") in ets:
                fetched[ev["event_ticker"]] = {"event": ev, "source": url}
        time.sleep(0.2)

    # Any event the series listing did not return is fetched directly, so a
    # missing listing page never silently drops a market's reference.
    for et in sorted(events):
        if et in fetched:
            continue
        try:
            payload, url = get_json(f"/events/{et}")
        except RuntimeError as e:
            print(f"  event {et}: {e}", file=sys.stderr)
            continue
        ev = (payload or {}).get("event") or payload
        if ev.get("event_ticker"):
            fetched[et] = {"event": ev, "source": url}
        time.sleep(0.2)

    # Public Kalshi page per series (verified once per series).
    public: dict[str, dict] = {}
    for series in sorted(by_series):
        if not series:
            continue
        url = f"https://kalshi.com/markets/{series.lower()}"
        status, final = verify_public_url(url)
        public[series] = {"url": url, "http_status": status, "final_url": final}
        time.sleep(0.2)

    out = []
    for et in sorted(events):
        rec = events[et]
        got = fetched.get(et)
        if not got:
            out.append({
                "event_ticker": et,
                "series_ticker": rec["series_ticker"],
                "category_ids": sorted(rec["categories"]),
                "status": "unavailable",
                "note": "The official events listing did not return this event in the run above.",
                "source": f"{BASE}/events/{et}",
            })
            continue
        ev = got["event"]
        sources = []
        for s in ev.get("settlement_sources") or []:
            if s.get("url"):
                sources.append({"name": s.get("name") or "", "url": s["url"]})
        pub = public.get(rec["series_ticker"] or "", {})
        # Only publish a public Kalshi link that actually resolved (HTTP 200).
        pub_ok = pub.get("http_status") == 200
        out.append({
            "event_ticker": et,
            "series_ticker": ev.get("series_ticker") or rec["series_ticker"],
            "api_category": ev.get("category"),
            "title": ev.get("title"),
            "sub_title": ev.get("sub_title"),
            "strike_date": ev.get("strike_date"),
            "last_updated_ts": ev.get("last_updated_ts"),
            "category_ids": sorted(rec["categories"]),
            "settlement_sources": sources,
            "kalshi_public_url": pub.get("url") if pub_ok else None,
            "kalshi_public_http_status": pub.get("http_status"),
            "kalshi_public_final_url": pub.get("final_url") if pub_ok else None,
            "kalshi_public_note": None if pub_ok else
                "The public Kalshi page for this series was not reachable in this run, so no link is published.",
            "status": "ok",
            "source": got["source"],
            "event_source": f"{BASE}/events/{et}",
        })

    payload = {
        "schema": 1,
        "generated_at": utcnow(),
        "snapshot_collected_at": snap.get("collected_at"),
        "environment": snap.get("environment"),
        "base_url": BASE,
        "method": (
            "For every event that appears on an in-scope market, GET /events?series_ticker={series} is called on the "
            "official Kalshi demo API and the returned fields are stored verbatim: title, sub_title, strike_date, "
            "category and settlement_sources. settlement_sources are the official reference websites the contract "
            "resolves against (AAA for US gas prices, CF Benchmarks for crypto reference prices, the PGA Tour / ESPN / "
            "Fox Sports for golf, news wires for elections and culture). They are the places to look for the reason a "
            "price moved; they are NOT an attribution of cause for any particular jump, because the API publishes no "
            "news feed. The public Kalshi link is only published when the request for it succeeded."
        ),
        "sources": SOURCES,
        "counts": {
            "events_in_scope": len(events),
            "events_fetched": sum(1 for e in out if e.get("status") == "ok"),
            "events_unavailable": sum(1 for e in out if e.get("status") != "ok"),
            "events_with_settlement_sources": sum(1 for e in out if e.get("settlement_sources")),
            "settlement_source_links": sum(len(e.get("settlement_sources") or []) for e in out),
        },
        "events": out,
        "disclaimers": [
            "Demo environment: market data is mock and may not reflect real markets.",
            "settlement_sources are copied verbatim from the official API response. Their reachability is not asserted.",
            "No causal claim is made: the API has no news feed, so a swing's cause stays unverified.",
        ],
    }
    if payload["counts"]["events_fetched"] == 0:
        # Never replace a good reference file with an empty one: a failed run
        # leaves the previous file in place (with its own generated_at) and the
        # alert builder keeps the candidates it already has.
        print("event refs: no events could be fetched; keeping the previous file", file=sys.stderr)
        if (LIVE / "event_refs.json").exists():
            return 0
    (LIVE / "event_refs.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"event refs: {payload['counts']['events_fetched']}/{payload['counts']['events_in_scope']} events "
          f"-> {LIVE / 'event_refs.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
