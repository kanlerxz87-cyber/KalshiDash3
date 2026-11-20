#!/usr/bin/env python3
"""Build the live price-swing alert feed from collected snapshots.

Input  (no network, no credentials):
  data/live/price_history.json  observations written by scripts/collect.py
  data/live/markets.json        market metadata from GET /markets
  data/alert_rules.json         thresholds and the (placeholder) high-ROI screen
Output:
  data/live/alerts.json         two feeds: all_events and high_roi

Each alert is a consecutive pair of last-traded-price observations for one
market whose absolute change is >= the threshold (default $0.10), in either
direction. Cause fields (news / website links) are deliberately left null:
no official source for a cause is collected, so none is invented.

Official references
  Get Markets ..... https://docs.kalshi.com/api-reference/market/get-markets
  Lifecycle ....... https://docs.kalshi.com/getting_started/market_lifecycle
Exit codes: 0 written, 1 input missing or malformed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live"
MAX_ALERTS_PER_FEED = 300
EPS = 1e-9


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR reading {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    hist = load(LIVE / "price_history.json")
    markets = load(LIVE / "markets.json")
    rules = load(ROOT / "data" / "alert_rules.json")

    threshold = float(rules["swing_threshold_dollars"])
    roi = rules["high_roi"]
    by_ticker = {m["ticker"]: m for m in markets.get("open_markets", [])}
    lo, hi = roi["post_move_price_band_dollars"]

    all_feed, roi_feed = [], []
    for ticker, rec in hist.get("series", {}).items():
        obs = [o for o in rec.get("observations", []) if o.get("last") is not None]
        m = by_ticker.get(ticker)
        for prev, cur in zip(obs, obs[1:]):
            a, b = float(prev["last"]), float(cur["last"])
            delta = round(b - a, 4)
            if abs(delta) + EPS < threshold:
                continue
            alert = {
                "ticker": ticker,
                "event_ticker": m.get("event_ticker") if m else None,
                "title": m.get("title") if m else None,
                "category_id": m.get("category_id") if m else None,
                "category_basis": m.get("category_basis") if m else None,
                "status": m.get("status") if m else None,
                "from_time": prev["t"],
                "to_time": cur["t"],
                "from_price": a,
                "to_price": b,
                "delta": delta,
                "direction": "up" if delta > 0 else "down",
                "volume_24h_fp": (m or {}).get("volume_24h_fp"),
                "market_source": (m or {}).get("source"),
                "cause_link": None,
                "cause_status": "unverified: no official cause source collected",
            }
            all_feed.append(alert)
            # High-ROI placeholder screen (see data/alert_rules.json).
            if (
                m is not None
                and m.get("status") == roi["require_status"]
                and (m.get("volume_24h_fp") or 0) > roi["require_volume_24h_gt"]
                and lo - EPS <= b <= hi + EPS
                and abs(delta) + EPS >= roi["min_abs_swing_dollars"]
            ):
                alert = dict(alert)
                alert["implied_return"] = round((1 - b) / b, 4) if b > 0 else None
                roi_feed.append(alert)

    def newest_first(rows):
        rows.sort(key=lambda r: (r["to_time"], abs(r["delta"])), reverse=True)
        return rows[:MAX_ALERTS_PER_FEED]

    out = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_collected_at": markets.get("collected_at"),
        "threshold_dollars": threshold,
        "high_roi_status": rules.get("status"),
        "high_roi_rule": roi,
        "counts": {"all_events": len(all_feed), "high_roi": len(roi_feed)},
        "all_events": newest_first(all_feed),
        "high_roi": newest_first(roi_feed),
        "disclaimers": [
            "Prices are last-traded prices from the Kalshi DEMO environment (mock funds).",
            "Each alert is a change between two consecutive collector observations, not a continuous tick stream.",
            "cause_link is null on every alert: no official cause source has been collected, so none is shown.",
            "The high_roi feed uses a placeholder screen (data/alert_rules.json, status=placeholder); it is not an owner-approved model.",
        ],
    }
    (LIVE / "alerts.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"OK: all_events={len(all_feed)} high_roi={len(roi_feed)} threshold=${threshold:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
