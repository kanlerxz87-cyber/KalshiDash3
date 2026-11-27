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

T66: each alert also carries `evidence` — whether contracts traded in the
interval (from the documented cumulative volume field) or the quoted price
moved with no trade at all. See scripts/alert_evidence.py.

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

import alert_evidence

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
    "elections": {"Elections"},
    "culture": {"Entertainment", "Culture", "Pop Culture", "Awards", "Media"},
    "crypto": {"Crypto", "Financials"},
    "golf": {"Sports", "Golf"},
}

# Categories the exchange uses for its own test instruments. `GET /series` files
# KXDEMOFUTHOURLY under ["Test"], tag "Demo" (observed 2026-11-21), and the collector
# already refuses such rows for the five topics (F-61). An alert about one of those
# markets is not an event in gas, elections, culture, crypto or golf, so it is withheld
# from the chats while staying in the archive.
NEVER_IN_SCOPE = {"Test", "Demo"}
DEMO_BASES = ("https://external-api.demo.kalshi.co/trade-api/v2", "https://demo-api.kalshi.co/trade-api/v2")


def series_of_ticker(ticker: str) -> str:
    """Series ticker from a market ticker. Kalshi series tickers contain no hyphen.

    Same derivation as scripts/collect.py (series_of); restated so this script keeps working if
    the snapshot row has already been dropped.
    """
    t = (ticker or "").upper()
    return t.split("-")[0] if "-" in t else t


def archived_series_categories(a: dict) -> list[str]:
    """Return recorded categories only when they cite this series on the demo API."""
    series = series_of_ticker(a.get("ticker") or "")
    if a.get("series_categories_source") not in {f"{base}/series/{series}" for base in DEMO_BASES}:
        return []
    return [str(c) for c in (a.get("series_categories") or [])]


def alert_categories(a: dict, row: dict, ledger: dict) -> list[str]:
    """Prefer current official metadata; a rolling scan can omit an archived ticker."""
    series = row.get("series_ticker") or series_of_ticker(a.get("ticker") or "")
    categories = row.get("series_categories") or (ledger.get(series) or {}).get("categories")
    return [str(c) for c in categories] if categories else archived_series_categories(a)


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
    # snapshot's series_index now answers for them. Record the source with the categories while
    # it is available; don't replace previously sourced metadata with a later classification.
    series_ledger = markets.get("series_index") or {}
    repaired = 0
    for a in archive["alerts"]:
        if archived_series_categories(a):
            continue
        series = series_of_ticker(a.get("ticker") or "")
        entry = series_ledger.get(series) or {}
        cats = [str(c) for c in (entry.get("categories") or [])]
        source = entry.get("source")
        if cats and source in {f"{base}/series/{series}" for base in DEMO_BASES}:
            a["series_categories"] = cats
            a["series_categories_source"] = source
            repaired += 1
    if repaired:
        print(f"archive: recorded official series_categories on {repaired} entr(y/ies) from series_index")

    # T66: every swing now carries the EVIDENCE behind it, not just a price difference. The
    # rule watches last_price_dollars, which Kalshi defines as the last TRADED price; two reads
    # of it can differ by >= $0.10 with no trade at all in between. `evidence.state` says which
    # kind of event this was, and `evidence.contracts_traded` is the difference of the documented
    # cumulative volume field between the two observations (null when the counter does not
    # behave monotonically — never a negative or guessed count). See scripts/alert_evidence.py.
    floor = float((rules.get("evidence") or {}).get("floor_contracts", alert_evidence.DEFAULT_FLOOR))
    series_hist = hist.get("series") or {}
    for a in archive["alerts"]:
        obs_list = (series_hist.get(a.get("ticker")) or {}).get("observations") or []
        current = alert_evidence.evaluate(a, obs_list, floor=floor)
        prior = a.get("evidence") or {}
        # FROZEN AT FIRST DETECTION, for the same reason high_roi is: a later observation can
        # change the reversion answer (a swing that was "still open" gains later reads), but the
        # contract count between the two bounding observations can never change — the volume
        # field is cumulative and both reads are fixed. Keeping the detection-time block makes
        # feed reproduction byte-exact instead of clock-dependent (see validate_alerts.py).
        base = {
            "state": current["state"],
            "contracts_traded": current["contracts_traded"],
            "est_dollars": current["est_dollars"],
            "est_dollars_is_an_estimate": True,
            "volume_from": current.get("volume_from"),
            "volume_to": current.get("volume_to"),
            "policy_floor_contracts": current["policy_floor_contracts"],
            "policy_floor_is_a_kalshi_field": False,
            "why": current["why"],
            "sources": current["sources"],
            "decided_at": (prior.get("decided_at") if prior.get("state") == current["state"]
                           else now),
        }
        # Reversion is a live observation about later reads, so it is refreshed every build and
        # kept OUTSIDE the frozen block: it is allowed to improve as history accumulates.
        a["evidence"] = base
        a["evidence_reversion"] = current["reversion"]
        if prior.get("state") and prior.get("state") != current["state"]:
            print(f"evidence: {a.get('ticker')}@{a.get('to_time')} re-classified "
                  f"{prior.get('state')} -> {current['state']} (volume field changed on re-read)")
    # Same repair for a MISSING TOPIC. Legacy entries were written while their market sat in
    # the open scan, then the market left it; category_id stayed null even though the series
    # record was known. GET /series now answers, so the topic is restored when exactly one of
    # the five topics accepts that series. Prices, times, deltas and high_roi stay untouched.
    # Ambiguous (a series filed under Financials could be gas or crypto) or unknown series are
    # left null and the row is withheld below — an unconfirmed topic is not a topic.
    assigned = 0
    for a in archive["alerts"]:
        if a.get("category_id"):
            continue
        cats = set(archived_series_categories(a))
        if cats & NEVER_IN_SCOPE:
            continue
        topics = sorted(t for t, comp in CATEGORY_COMPATIBLE.items() if cats & comp)
        if len(topics) == 1:
            a["category_id"] = topics[0]
            a["category_basis"] = "official-series"
            a["category_assigned_from"] = "GET /series categories (series_categories)"
            assigned += 1
    if assigned:
        print(f"archive: restored the topic on {assigned} entr(y/ies) from official series categories")

    archive["alerts"].sort(key=lambda r: (r["to_time"], abs(r["delta"])), reverse=True)
    archive["alerts"] = archive["alerts"][:ARCHIVE_LIMIT]
    archive_path.write_text(json.dumps(archive, indent=1) + "\n", encoding="utf-8")

    if args.no_write_feed:
        print(f"archive: +{new_count} new, {len(archive['alerts'])} total")
        return 0

    # F-65: an archived alert stays in the archive (history is never rewritten), but it must
    # not be served when the exchange's own series record says its series is not in that topic.
    #
    # The ledger can reject a row even if it is not ranked, but is itself refreshed from a
    # bounded scan. When neither current source has categories, use the alert's own sourced copy.
    conflicts: dict[str, dict] = {}
    out_of_scope: dict[str, int] = {}

    def publishable(a) -> bool:
        cats = alert_categories(a, by_ticker.get(a.get("ticker")) or {}, series_ledger)
        cat = a.get("category_id")
        # 1. The exchange's own record files the series under a test/demo category.
        never = sorted({c for c in cats if c in NEVER_IN_SCOPE})
        if never:
            key = "series filed under " + ", ".join(never)
            out_of_scope[key] = out_of_scope.get(key, 0) + 1
            return False
        # 2. An unclassified or unsupported topic cannot appear in the five-topic feeds.
        if cat not in CATEGORY_COMPATIBLE:
            key = "no supported topic recorded"
            out_of_scope[key] = out_of_scope.get(key, 0) + 1
            return False
        compatible = CATEGORY_COMPATIBLE[cat]
        # 3. No official categories recorded: unknown is not a contradiction.
        if not cats:
            return True
        if any(c in compatible for c in cats):
            return True
        # 4. The exchange says this market is not in the topic it was counted under.
        conflicts.setdefault(cat, {}).setdefault(str(cats), 0)
        conflicts[cat][str(cats)] += 1
        return False

    served = [a for a in archive["alerts"] if publishable(a)]
    conflict_count = sum(sum(d.values()) for d in conflicts.values())
    scope_count = sum(out_of_scope.values())
    withheld = len(archive["alerts"]) - len(served)
    all_feed = list(served)
    roi_feed = [a for a in served if a.get("high_roi")]
    if withheld != conflict_count + scope_count:
        print(f"ERROR: withheld {withheld} != conflicts {conflict_count} + out_of_scope {scope_count}",
              file=sys.stderr)
        return 1

    # Each feed has its own newest-first window; a model-watch entry can be older than the
    # all-events window. Counts describe the serialized windows, not the untrimmed archive.
    all_window = all_feed[:MAX_ALERTS_PER_FEED]
    roi_window = roi_feed[:MAX_ALERTS_PER_FEED]
    out = {
        "schema": 1,
        "generated_at": now,
        "snapshot_collected_at": markets.get("collected_at"),
        "threshold_dollars": threshold,
        "rules_status": rules.get("status"),
        "high_roi_rule": roi,
        "counts": {
            "all_events": len(all_window),
            "high_roi": len(roi_window),
            "archive_total": len(archive["alerts"]),
            "new_this_run": new_count,
            # F-65: archived, but withheld from the feeds because the snapshot's own row for the
            # market records official series categories that exclude it from its topic.
            "withheld_category_conflict": conflict_count,
            "withheld_reasons": {k: dict(v) for k, v in sorted(conflicts.items())},
            # T66: how many of the served swings were backed by trades, and how many were a
            # quoted price that changed with no trade at all. Always published, so the ratio
            # cannot quietly get worse for a reader who never opens a row.
            "evidence": alert_evidence.summarize(all_feed),
            "withheld_out_of_scope": scope_count,
            "withheld_out_of_scope_reasons": dict(sorted(out_of_scope.items())),
        },
        "all_events": all_window,
        "high_roi": roi_window,
        "disclaimers": [
            "Prices are last-traded prices from the Kalshi DEMO environment (mock funds).",
            "Each alert is a change between two consecutive collector observations, not a continuous tick stream.",
            "Alerts are kept in data/live/alerts_archive.json, so a move stays listed after its market leaves the open scan.",
            "cause_link is null on every alert: no official cause source has been collected, so none is shown.",
            "high_roi is the dashboard's experimental 'Model watch' screen (seed series with positive volume_24h). It is not an owner-approved ROI model.",
            "Evidence: each alert's evidence.state says whether contracts actually traded between the two observations (traded_ge_floor / traded_below_floor), whether the reported last price changed with NO trade at all in the interval (quote_only), or whether the cumulative volume field did not increase so the interval's contract count is unknowable (counter_reset). The floor is a project rule, not a Kalshi field (scripts/alert_evidence.py).",
            "est_dollars on an alert is contracts traded in the interval multiplied by the later price. It is computed here, not a Kalshi field, and it is an estimate because contracts trade at different prices inside one interval.",
            "Each feed contains its own newest 300 qualifying rows. The row counts describe these windows; evidence counts describe the full in-scope archive.",
            "An archived alert is withheld when official series categories contradict its topic. Current metadata takes precedence; a sourced archive record is used if the rolling snapshot has no categories for that series.",
            "Scope: the chats cover the five topics only. An archived swing whose series GET /series files under Test/Demo, or for which no single topic can be confirmed, is withheld and counted (counts.withheld_out_of_scope) rather than shown under the wrong topic.",
        ],
    }
    (LIVE / "alerts.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"OK: new={new_count} all_events={len(all_feed)} high_roi={len(roi_feed)} "
          f"withheld={withheld} (conflicts={conflict_count}, out_of_scope={scope_count}) "
          f"threshold=${threshold:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
