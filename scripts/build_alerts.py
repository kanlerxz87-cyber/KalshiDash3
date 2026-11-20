#!/usr/bin/env python3
"""Build the live price-swing alert feed from collected snapshots.

Input  (no network, no credentials):
  data/live/price_history.json  observations written by scripts/collect.py
  data/live/markets.json        market metadata from GET /markets
  data/live/event_refs.json     official event records (optional, see below)
  data/alert_rules.json         threshold and the experimental screen (mirrors the dashboard)
Output:
  data/live/alerts_archive.json append-only archive of every alert ever detected
  data/live/alerts.json         two feeds rendered from the archive: all_events and high_roi

The archive exists because scripts/collect.py keeps price history only for
markets that are currently open in scope. Without it a swing disappears from
the feed as soon as its market closes. An alert is written once and never
removed (oldest entries are trimmed only beyond ARCHIVE_LIMIT).

Each alert is a consecutive pair of last-traded-price observations for one
market whose absolute change is >= the threshold (default $0.10), in either
direction.

Cause fields
  Kalshi's API publishes no news feed and no field that says why a price moved,
  so no cause is ever asserted. What the official API does publish is the
  event record, and with it the settlement_sources the contract resolves
  against (AAA for US gas prices, CF Benchmarks for crypto reference prices,
  the PGA Tour / ESPN / Fox Sports for golf, news wires for elections and
  culture). Those are copied verbatim into `cause_candidates` and every alert
  carries an explicit `cause_status` that says the cause is unverified. They
  are checkable places to look, not an attribution of cause for any one move.

  Only reference metadata is refreshed on later runs (when a newer
  event_refs.json arrives). The alert facts - ticker, times, prices, delta -
  are never rewritten, so the archive stays append-only.

Official references
  Get Markets ..... https://docs.kalshi.com/api-reference/market/get-markets
  Get Event ....... https://docs.kalshi.com/api-reference/events/get-event
  Lifecycle ....... https://docs.kalshi.com/getting_started/market_lifecycle
Exit codes: 0 written, 1 input missing or malformed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live"
MAX_ALERTS_PER_FEED = 300
ARCHIVE_LIMIT = 5000
EPS = 1e-9
DEMO_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"

CAUSE_NONE = "unverified: no official event reference was collected for this market"
CAUSE_UNVERIFIED = (
    "unverified: the official settlement source(s) listed for this event are candidates to check, "
    "not a confirmed cause - the API publishes no news feed, so nothing links a source to this move"
)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR reading {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def load_event_refs(path: Path):
    """Return ({event_ticker: ref}, generated_at) from an optional event-refs file."""
    if not path.exists():
        return {}, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: ignoring unreadable {path}: {exc}", file=sys.stderr)
        return {}, None
    refs: dict[str, dict] = {}
    for ev in doc.get("events") or []:
        et = ev.get("event_ticker")
        if et:
            refs[et] = ev
    return refs, doc.get("generated_at")


def cause_fields(alert: dict, refs: dict[str, dict], refs_generated_at: str | None) -> dict:
    """Official, checkable cause *candidates* for one alert. Never an attribution."""
    event_ticker = alert.get("event_ticker")
    ref = refs.get(event_ticker) if event_ticker else None
    if not ref or ref.get("status") != "ok":
        return {
            "cause_link": None,
            "cause_status": CAUSE_NONE,
            "cause_candidates": [],
            "cause_kind": "none",
        }
    candidates = []
    for s in ref.get("settlement_sources") or []:
        url = s.get("url")
        if not url:
            continue
        candidates.append({"name": s.get("name") or "", "url": url})
    return {
        "cause_link": ref.get("event_source") or f"{DEMO_BASE}/events/{event_ticker}",
        "cause_status": CAUSE_UNVERIFIED,
        "cause_candidates": candidates,
        "cause_kind": "official_settlement_source",
        "cause_event_title": ref.get("title"),
        "cause_public_url": ref.get("kalshi_public_url"),
        "cause_refs_generated_at": refs_generated_at,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--history", default=str(LIVE / "price_history.json"))
    ap.add_argument("--markets", default=str(LIVE / "markets.json"))
    ap.add_argument("--event-refs", default=str(LIVE / "event_refs.json"),
                    help="optional official event references (see scripts/collect_event_refs.py)")
    ap.add_argument("--archive", default=str(LIVE / "alerts_archive.json"), help="archive output path")
    ap.add_argument("--feed", default=str(LIVE / "alerts.json"), help="rendered feed output path")
    ap.add_argument("--no-write-feed", action="store_true", help="only update the archive")
    args = ap.parse_args()

    hist = load(Path(args.history))
    markets = load(Path(args.markets))
    rules = load(ROOT / "data" / "alert_rules.json")
    refs, refs_generated_at = load_event_refs(Path(args.event_refs))
    archive_path = Path(args.archive)
    archive = load(archive_path) if archive_path.exists() else {"schema": 1, "alerts": []}
    known = {(a["ticker"], a["from_time"], a["to_time"]) for a in archive["alerts"]}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    threshold = float(rules["swing_threshold_dollars"])
    roi = rules["high_roi"]
    by_ticker = {m["ticker"]: m for m in markets.get("open_markets", [])}

    new_count = 0
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
            }
            key = (ticker, prev["t"], cur["t"])
            if key in known:
                continue
            known.add(key)
            new_count += 1
            # Experimental screen = the dashboard's 'Model watch' filter (data/alert_rules.json). Decided at detection time.
            alert["first_seen_at"] = now
            alert["high_roi"] = bool(
                m is not None
                and m.get("category_basis") == roi["require_category_basis"]
                and (m.get("volume_24h_fp") or 0) > roi["require_volume_24h_gt"]
            )
            archive["alerts"].append(alert)

    # Attach (or refresh) the official cause candidates. Only reference
    # metadata is touched: the alert facts above are never rewritten.
    enriched = 0
    with_candidates = 0
    for alert in archive["alerts"]:
        fields = cause_fields(alert, refs, refs_generated_at)
        if fields["cause_candidates"]:
            with_candidates += 1
        if any(alert.get(k) != v for k, v in fields.items()):
            alert.update(fields)
            alert["cause_attached_at"] = now
            enriched += 1

    archive["alerts"].sort(key=lambda r: (r["to_time"], abs(r["delta"])), reverse=True)
    archive["alerts"] = archive["alerts"][:ARCHIVE_LIMIT]
    archive_path.write_text(json.dumps(archive, indent=1) + "\n", encoding="utf-8")

    if args.no_write_feed:
        print(f"archive: +{new_count} new, {len(archive['alerts'])} total")
        return 0

    all_feed = list(archive["alerts"])
    roi_feed = [a for a in archive["alerts"] if a.get("high_roi")]

    def newest_first(rows):
        return rows[:MAX_ALERTS_PER_FEED]

    out = {
        "schema": 1,
        "generated_at": now,
        "snapshot_collected_at": markets.get("collected_at"),
        "threshold_dollars": threshold,
        "rules_status": rules.get("status"),
        "high_roi_rule": roi,
        "event_refs_generated_at": refs_generated_at,
        "counts": {
            "all_events": len(all_feed),
            "high_roi": len(roi_feed),
            "archive_total": len(archive["alerts"]),
            "new_this_run": new_count,
            "alerts_with_cause_candidates": with_candidates,
            "cause_fields_refreshed": enriched,
        },
        "all_events": newest_first(all_feed),
        "high_roi": newest_first(roi_feed),
        "disclaimers": [
            "Prices are last-traded prices from the Kalshi DEMO environment (mock funds).",
            "Each alert is a change between two consecutive collector observations, not a continuous tick stream.",
            "Alerts are kept in data/live/alerts_archive.json, so a move stays listed after its market leaves the open scan.",
            "cause_candidates are the official settlement_sources published for the event (AAA, CF Benchmarks, PGA Tour, news wires, ...). "
            "They are places to check, not a proven cause: the Kalshi API publishes no news feed, so every cause_status stays 'unverified'.",
            "cause_link points at the official Kalshi event record for the market; it is a reference link, not an attribution.",
            "high_roi is the dashboard's experimental 'Model watch' screen (seed series with positive volume_24h). It is not an owner-approved ROI model.",
        ],
    }
    Path(args.feed).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"OK: new={new_count} all_events={len(all_feed)} high_roi={len(roi_feed)} threshold=${threshold:.2f} "
          f"cause_candidates={with_candidates} refreshed={enriched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
