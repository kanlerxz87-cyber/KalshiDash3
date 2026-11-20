#!/usr/bin/env python3
"""Build data/live/alerts.json — every observed swing of >= $0.10 in contract price.

The $0.10 swing threshold is a PROJECT REQUIREMENT from the brief, not a fact about
the Kalshi API; it is recorded here as `threshold_dollars` so no page can mistake it
for an official number.

Inputs (both are committed snapshots written by scripts/collect.py — this script
needs no network access and no credentials):
  data/live/price_history.json  — accumulated observations of GET /markets fields
                                  (last_price_dollars recorded as `last`, plus
                                  best bid/ask and volume at each observation)
  data/live/markets.json        — the matching market snapshot (titles, categories,
                                  per-row source URLs)

Method: for every market with at least two accumulated observations, diff each pair of
CONSECUTIVE observations. Every pair whose |delta| >= threshold becomes one alert record
carrying both timestamps, both prices, the direction, and the API query URL for the
market. Nothing is interpolated, extrapolated, or inferred: an alert exists only where
two real collected observations straddle a >= $0.10 move.

Run: python3 scripts/build_alerts.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live"

BASE_URL = "https://external-api.demo.kalshi.co/trade-api/v2"
THRESHOLD_DOLLARS = 0.10

# Market fields copied verbatim from the snapshot row onto each alert.
ROW_FIELDS = ("title", "category_id", "category_basis", "status", "result")


def now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fnum(v):
    """Observation numbers are stored as floats, volumes as strings; tolerate both."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    hist_path = LIVE / "price_history.json"
    markets_path = LIVE / "markets.json"
    if not hist_path.exists():
        print("skip: data/live/price_history.json not present yet (collector has not run)")
        return 0

    hist = json.loads(hist_path.read_text())
    rows: dict[str, dict] = {}
    if markets_path.exists():
        snap = json.loads(markets_path.read_text())
        for bucket in ("open_markets", "settled_markets"):
            for r in snap.get(bucket) or []:
                rows[r.get("ticker", "")] = r

    alerts: list[dict] = []
    series = hist.get("series") or {}
    pairs = 0
    for ticker, entry in series.items():
        obs = entry.get("observations") or []
        # Sort defensively by timestamp; the collector appends in order already.
        obs = sorted(obs, key=lambda o: o.get("t") or "")
        for i in range(1, len(obs)):
            prev, cur = obs[i - 1], obs[i]
            p_prev, p_cur = fnum(prev.get("last")), fnum(cur.get("last"))
            if p_prev is None or p_cur is None:
                continue
            t_prev, t_cur = prev.get("t"), cur.get("t")
            if not t_prev or not t_cur or t_cur <= t_prev:
                continue
            pairs += 1
            delta = round(p_cur - p_prev, 6)
            if abs(delta) + 1e-12 < THRESHOLD_DOLLARS:
                continue
            row = rows.get(ticker) or {}
            alert = {
                "ticker": ticker,
                "direction": "up" if delta > 0 else "down",
                "delta_dollars": delta,
                "from_price_dollars": round(p_prev, 6),
                "to_price_dollars": round(p_cur, 6),
                "from_ts": t_prev,
                "to_ts": t_cur,
                "from_bid_dollars": fnum(prev.get("yes_bid")),
                "to_bid_dollars": fnum(cur.get("yes_bid")),
                "from_ask_dollars": fnum(prev.get("yes_ask")),
                "to_ask_dollars": fnum(cur.get("yes_ask")),
                "source": row.get("source") or f"{BASE_URL}/markets/{ticker}",
                "observed_basis": "api_diff",
            }
            for f in ROW_FIELDS:
                alert[f] = row.get(f)
            alerts.append(alert)

    alerts.sort(key=lambda a: (-abs(a["delta_dollars"]), a["to_ts"], a["ticker"]))

    times = sorted({o.get("t") for e in series.values() for o in (e.get("observations") or []) if o.get("t")})
    doc = {
        "schema": 1,
        "environment": "demo",
        "base_url": BASE_URL,
        "generated_at": now_z(),
        "threshold_dollars": THRESHOLD_DOLLARS,
        "threshold_note": (
            "The >= $0.10 swing threshold is a requirement of this project (the brief), "
            "not an official Kalshi number. Alerts are diffs between two CONSECUTIVE "
            "observations collected by scripts/collect.py from the official demo API; "
            "nothing is interpolated."
        ),
        "note": (
            "One alert per consecutive observation pair with |delta| >= threshold, on the "
            "`last` traded price series. Between collector runs no prices are visible to "
            "this method; see Flagged F-14 for the WebSocket that would close that gap."
        ),
        "counts": {
            "alerts": len(alerts),
            "up": sum(1 for a in alerts if a["direction"] == "up"),
            "down": sum(1 for a in alerts if a["direction"] == "down"),
            "pairs_compared": pairs,
            "markets_with_history": len(series),
        },
        "coverage": {
            "first_observation": times[0] if times else None,
            "last_observation": times[-1] if times else None,
            "distinct_observation_runs": len(times),
        },
        "sources": {
            "markets_endpoint": f"{BASE_URL}/markets",
            "markets_docs": "https://docs.kalshi.com/api-reference/market/get-markets",
            "candlesticks_docs": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
            "websocket_docs": "https://docs.kalshi.com/getting_started/quick_start_websockets",
        },
        "disclaimers": [
            "Demo environment: mock funds; prices may not reflect real markets "
            "(https://docs.kalshi.com/getting_started/demo_env).",
            "A >= $0.10 diff between two observations is an observed swing, not a "
            "verified cause; per-alert cause attribution is out of scope (see flagged F-15).",
        ],
        "alerts": alerts,
    }

    out = LIVE / "alerts.json"
    out.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"OK: {len(alerts)} alerts (up {doc['counts']['up']} / down {doc['counts']['down']}) "
          f"from {pairs} consecutive pairs across {len(series)} markets -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
