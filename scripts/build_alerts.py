#!/usr/bin/env python3
"""Build the live price-swing alert feed from collected snapshots.

Input  (no network, no credentials):
  data/live/price_history.json  observations written by scripts/collect.py
  data/live/markets.json        market metadata from GET /markets
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
direction. Cause fields (news / website links) are deliberately left null:
no official source for a cause is collected, so none is invented.

Official references
  Get Markets ..... https://docs.kalshi.com/api-reference/market/get-markets
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

# F-65 category integrity. Same table scripts/collect.py applies to the snapshot, restated here
# so the feed builder can refuse an archived alert the current snapshot contradicts. Sources for
# each official category: GET https://external-api.demo.kalshi.co/trade-api/v2/series/<ticker>
# (schema: https://docs.kalshi.com/api-reference/market/get-series-list).
CATEGORY_COMPATIBLE = {
    "gas": {"Economics", "Commodities", "Financials"},
    "elections": {"Elections", "Politics", "World", "International"},
    "culture": {"Entertainment", "Culture", "Pop Culture", "Awards", "Media"},
    "crypto": {"Crypto", "Financials"},
    "golf": {"Sports", "Golf"},
}


def series_of_ticker(ticker: str) -> str:
    """Series ticker from a market ticker. Kalshi series tickers contain no hyphen.

    Same derivation as scripts/collect.py (series_of); restated so this script keeps working if
    the snapshot row has already been dropped.
    """
    t = (ticker or "").upper()
    return t.split("-")[0] if "-" in t else t


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR reading {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--history", default=str(LIVE / "price_history.json"))
    ap.add_argument("--markets", default=str(LIVE / "markets.json"))
    ap.add_argument("--no-write-feed", action="store_true", help="only update the archive")
    args = ap.parse_args()

    hist = load(Path(args.history))
    markets = load(Path(args.markets))
    rules = load(ROOT / "data" / "alert_rules.json")
    archive_path = LIVE / "alerts_archive.json"
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
                # F-65: the official series categories recorded on the snapshot row, verbatim,
                # so an alert can be re-checked against the exchange's own classification.
                # Absent when the snapshot row predates the field — never inferred.
                "series_categories": (m or {}).get("series_categories"),
                "status": m.get("status") if m else None,
                "from_time": prev["t"],
                "to_time": cur["t"],
                "from_price": a,
                "to_price": b,
                "delta": delta,
                "direction": "up" if delta > 0 else "down",
                "volume_24h_fp": (m or {}).get("volume_24h_fp"),
                # Provenance must survive the market leaving the scan. If the snapshot row is
                # gone, the endpoint that recorded this swing is still knowable from the
                # snapshot's own base URL and the ticker — that is a URL this project called,
                # not a value invented about the market.
                "market_source": (m or {}).get("source")
                or (f"{markets.get('base_url').rstrip('/')}/markets/{ticker}" if markets.get("base_url") else None),
                # R-2: quotes carried at the swing's to_time so simulate.py can
                # fill the signal later even after the market leaves the open
                # scan (its price_history fallback stops working then). Null
                # when the observation carried no bid/ask — never invented.
                "to_yes_bid": cur.get("yes_bid"),
                "to_yes_ask": cur.get("yes_ask"),
                "cause_link": None,
                "cause_status": "unverified: no official cause source collected",
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

    # F-65 repair, applied to the archive's RECORDED CATEGORY FIELD only — never to the prices,
    # times, deltas or high_roi flag, which stay frozen at detection time:
    #
    # Merging two collector branches brought archive entries whose rows predate `series_categories`
    # (12 of the demo Test series among them), so those alerts carried no official categories. The
    # snapshot's series_index now answers for them, and leaving the field null would make the
    # withholding rule silently allow exactly the rows it exists to remove. A category this project
    # has since verified from GET /series is therefore written onto the entry; an entry whose series
    # is not in the ledger is left null (unknown is not a contradiction).
    series_ledger = markets.get("series_index") or {}
    repaired = 0
    for a in archive["alerts"]:
        if "series_categories" in a and a["series_categories"]:
            continue
        entry = series_ledger.get(series_of_ticker(a.get("ticker") or "")) or {}
        cats = entry.get("categories")
        if cats:
            a["series_categories"] = [str(c) for c in cats]
            a["series_categories_source"] = entry.get("source")
            repaired += 1
    if repaired:
        print(f"archive: recorded official series_categories on {repaired} entr(y/ies) from series_index")

    archive["alerts"].sort(key=lambda r: (r["to_time"], abs(r["delta"])), reverse=True)
    archive["alerts"] = archive["alerts"][:ARCHIVE_LIMIT]
    archive_path.write_text(json.dumps(archive, indent=1) + "\n", encoding="utf-8")

    if args.no_write_feed:
        print(f"archive: +{new_count} new, {len(archive['alerts'])} total")
        return 0

    # F-65: an archived alert stays in the archive (history is never rewritten), but it must
    # not be served when the exchange's own series record says its series is not in that topic.
    #
    # The first version of this check only looked at snapshot rows, which was backwards: the
    # collector DROPS a conflicting row, so a row-membership test would have kept precisely the
    # alerts that were supposed to disappear. The collector now publishes `series_index` — the
    # official GET /series categories per series ticker — and that ledger is the authority here.
    # A series with no ledger entry, or with null categories, is unknown and is served.
    ledger = markets.get("series_index") or {}
    conflicts: dict[str, dict] = {}

    def official_for(ticker: str) -> list[str]:
        row = by_ticker.get(ticker)
        if row and row.get("series_categories"):
            return [str(c) for c in row["series_categories"]]
        entry = ledger.get((row or {}).get("series_ticker") or series_of_ticker(ticker)) or {}
        return [str(c) for c in (entry.get("categories") or [])]

    def publishable(a) -> bool:
        cats = official_for(a.get("ticker") or "")
        cat = a.get("category_id")
        compatible = CATEGORY_COMPATIBLE.get(cat or "", set())
        if not cats or not compatible:
            return True
        if any(c in compatible for c in cats):
            return True
        conflicts.setdefault(cat, {}).setdefault(str(cats), 0)
        conflicts[cat][str(cats)] += 1
        return False

    served = [a for a in archive["alerts"] if publishable(a)]
    withheld = len(archive["alerts"]) - len(served)
    all_feed = list(served)
    roi_feed = [a for a in served if a.get("high_roi")]

    def newest_first(rows):
        return rows[:MAX_ALERTS_PER_FEED]

    out = {
        "schema": 1,
        "generated_at": now,
        "snapshot_collected_at": markets.get("collected_at"),
        "threshold_dollars": threshold,
        "rules_status": rules.get("status"),
        "high_roi_rule": roi,
        "counts": {
            "all_events": len(all_feed),
            "high_roi": len(roi_feed),
            "archive_total": len(archive["alerts"]),
            "new_this_run": new_count,
            # F-65: archived, but withheld from the feeds because the snapshot's own row for the
            # market records official series categories that exclude it from its topic.
            "withheld_category_conflict": withheld,
            "withheld_reasons": {k: dict(v) for k, v in sorted(conflicts.items())},
        },
        "all_events": newest_first(all_feed),
        "high_roi": newest_first(roi_feed),
        "disclaimers": [
            "Prices are last-traded prices from the Kalshi DEMO environment (mock funds).",
            "Each alert is a change between two consecutive collector observations, not a continuous tick stream.",
            "Alerts are kept in data/live/alerts_archive.json, so a move stays listed after its market leaves the open scan.",
            "cause_link is null on every alert: no official cause source has been collected, so none is shown.",
            "high_roi is the dashboard's experimental 'Model watch' screen (seed series with positive volume_24h). It is not an owner-approved ROI model.",
            "Category integrity: an archived alert is withheld from both feeds (counts.withheld_category_conflict) when the market's own snapshot row records official series categories that exclude it from that topic. The archive itself is never rewritten.",
        ],
    }
    (LIVE / "alerts.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"OK: new={new_count} all_events={len(all_feed)} high_roi={len(roi_feed)} "
          f"withheld={withheld} threshold=${threshold:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
