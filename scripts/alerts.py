#!/usr/bin/env python3
"""Kalshi swing-alert engine.

A pure, dependency-free, deterministic function that turns the committed
snapshots (``data/live/markets.json`` + ``data/live/price_history.json``) into
swing alerts. No network, no credentials, no manual input.

Rule (this project's own model, labelled wherever it is displayed)
  * An alert fires when |new last price − prior last price| >= SWING_THRESHOLD_DOLLARS
    ($0.10) between two consecutive observations of the same market in
    price_history.json. Both directions are reported (UP = price rose, DOWN = price fell).
  * High-ROI model: swing_roi = |delta| / entry_price_on_moving_side, where the
    moving side is YES for an UP move (entry = prior price) and NO for a DOWN move
    (entry = 1 − prior price). A swing is ``high_roi`` when swing_roi >= roi_threshold
    (default 0.40). This is a heuristic this project computes; Kalshi returns no ROI
    field, so it is labelled a model, never data.
  * Cause: Kalshi exposes no official feed of *why* a price moved. Each alert links
    the official Kalshi market and event API URLs (verifiable) and leaves ``cause``
    blank, flagged as unverified rather than inferred.

Every alert carries the ticker, the exact query URL it came from and the
observation time, so any alert can be re-run by hand.

Official sources
  Markets .... https://docs.kalshi.com/api-reference/market/get-markets
  Candles .... https://docs.kalshi.com/api-reference/market/get-market-candlesticks
    (seconds-resolution history cannot be requested — candlesticks support 1/60/1440
     minute intervals — so swings are computed between accumulated REST observations)

CLI
  python3 scripts/alerts.py            # regenerate data/live/alerts.json from the snapshots
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live"

# The alerting threshold the brief specifies, in dollars.
SWING_THRESHOLD_DOLLARS = 0.10
# Fixed-point prices are decimal strings; float subtraction can land a hair under
# the threshold (0.30 - 0.20 == 0.0999...). Compare with a tiny epsilon so a move
# that is exactly $0.10 at the documented precision still fires.
_EPS = 1e-9
# Default for the project-local high-ROI model (a move that is >= 40% of the
# entry price on the moving side). Adjustable at render time.
DEFAULT_ROI_THRESHOLD = 0.40

MODEL_NOTE = (
    "swing_roi = |Δlast| / entry_price_on_moving_side; moving side is YES for an UP move "
    "(entry = prior price) and NO for a DOWN move (entry = 1 − prior price). high_roi is a "
    "project-local heuristic. Kalshi returns no ROI field, so this is labelled a model, not data."
)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fnum(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def event_source_url(source: str, event_ticker: str | None) -> str | None:
    """Official Kalshi event API URL for an alert.

    GET /events/{event_ticker} is the documented per-event read
    (https://docs.kalshi.com/api-reference/events/get-events). The base is derived
    from the market's own source URL so no hard-coded host is required.
    """
    if not event_ticker:
        return None
    base = source.rsplit("/markets/", 1)[0] if "/markets/" in (source or "") else ""
    if not base:
        return None
    return f"{base}/events/{event_ticker}"


def compute_alerts(open_markets, settled_markets, price_history_series,
                   swing_threshold: float = SWING_THRESHOLD_DOLLARS,
                   roi_threshold: float = DEFAULT_ROI_THRESHOLD):
    """Return (alerts, meta).

    alerts are sorted newest-observation first. Each alert is a dict with the
    fields the site renders; ``cause`` is deliberately None (blank + flagged).
    """
    index = {}
    for row in list(open_markets or []) + list(settled_markets or []):
        if row.get("ticker"):
            index[row["ticker"]] = row

    alerts = []
    for ticker, series in (price_history_series or {}).items():
        row = index.get(ticker)
        if not row:
            # An observation without a market row would have no provenance, so it
            # is skipped rather than rendered with a blank title.
            continue
        obs = (series or {}).get("observations") or []
        for i in range(1, len(obs)):
            prior = fnum(obs[i - 1].get("last"))
            new = fnum(obs[i].get("last"))
            if prior is None or new is None:
                continue
            delta = new - prior
            magnitude = abs(delta)
            if magnitude < swing_threshold - _EPS:
                continue
            direction = "up" if delta > 0 else "down"
            # Entry price on the moving side: YES for an up move, NO for a down move.
            entry = prior if delta > 0 else (1.0 - prior)
            swing_roi = round(magnitude / entry, 4) if entry > 0 else None
            alerts.append({
                "ticker": ticker,
                "event_ticker": row.get("event_ticker") or None,
                "title": row.get("title") or "",
                "category_id": row.get("category_id"),
                "category_basis": row.get("category_basis"),
                "direction": direction,
                "prior_price": round(prior, 4),
                "new_price": round(new, 4),
                "delta": round(delta, 4),
                "swing_cents": round(magnitude * 100, 2),
                "swing_roi": swing_roi,
                "high_roi": swing_roi is not None and swing_roi >= roi_threshold - _EPS,
                "observed_at": obs[i].get("t"),
                "source": row.get("source"),
                "event_source": event_source_url(row.get("source"), row.get("event_ticker")),
                # No official cause feed exists; left blank and flagged, never inferred.
                "cause": None,
                "cause_flag": "no official cause feed — left blank, not inferred",
            })

    alerts.sort(key=lambda a: a.get("observed_at") or "", reverse=True)

    by_cat: dict[str, int] = {}
    for a in alerts:
        by_cat[a["category_id"]] = by_cat.get(a["category_id"], 0) + 1

    meta = {
        "schema": 1,
        "model": "swing-alert-v1",
        "model_note": MODEL_NOTE,
        "swing_threshold_dollars": swing_threshold,
        "roi_threshold": roi_threshold,
        "generated_at": utcnow(),
        "counts": {
            "total": len(alerts),
            "high_roi": sum(1 for a in alerts if a["high_roi"]),
            "by_category": by_cat,
        },
        "sources": {
            "markets": "https://docs.kalshi.com/api-reference/market/get-markets",
            "events": "https://docs.kalshi.com/api-reference/events/get-events",
            "candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
        },
        "disclaimers": [
            "Alerts are computed from accumulated REST observations (one per collector run), "
            "not from a live WebSocket. Kalshi WebSocket sessions require an API key.",
            "swing_roi / high_roi are a project-local heuristic model, not a Kalshi field.",
            "cause is blank because Kalshi publishes no official feed of why a price moved; "
            "nothing is inferred.",
        ],
    }
    return alerts, meta


def build(swing_threshold: float = SWING_THRESHOLD_DOLLARS,
          roi_threshold: float = DEFAULT_ROI_THRESHOLD) -> dict:
    markets = json.loads((LIVE / "markets.json").read_text())
    history = json.loads((LIVE / "price_history.json").read_text())
    alerts, meta = compute_alerts(
        markets.get("open_markets"), markets.get("settled_markets"),
        history.get("series"), swing_threshold, roi_threshold,
    )
    payload = {
        "collected_at": markets.get("collected_at"),
        "observation_source": "data/live/price_history.json",
        **meta,
        "alerts": alerts,
    }
    return payload


def main() -> int:
    if not (LIVE / "markets.json").exists() or not (LIVE / "price_history.json").exists():
        print("COLLECT_FAILED: data/live/markets.json or price_history.json missing", file=sys.stderr)
        return 2
    payload = build()
    LIVE.mkdir(parents=True, exist_ok=True)
    (LIVE / "alerts.json").write_text(json.dumps(payload, indent=1))
    c = payload["counts"]
    print(f"  wrote {LIVE/'alerts.json'} ({c['total']} alerts, {c['high_roi']} high-ROI)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
