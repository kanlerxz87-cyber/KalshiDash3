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

# Reuse the collector's documented GET helper (UA, 429 backoff, JSON parse) instead of
# duplicating HTTP behaviour in a second file.
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from collect import BASE as _DEFAULT_BASE
    from collect import get as tape_get_impl
except Exception:                                # pragma: no cover - only if collect.py is absent
    _DEFAULT_BASE, tape_get_impl = None, None
MAX_ALERTS_PER_FEED = 300
ARCHIVE_LIMIT = 5000
EPS = 1e-9


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR reading {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def parse_ts(v):
    """Parse an ISO-8601 stamp as returned by GET /markets. Returns None if absent/invalid."""
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Verifying a candidate change against the official trade tape
# ---------------------------------------------------------------------------
# WHY
# ---
# `last_price_dollars` is the last traded price, but GET /markets returns no
# "this is a new print" flag, and the field this project first tried to use for
# that job does not work:
#
#   * KXBTCY-27JAN0100-B87500 reported last = 0.04, then 0.99, then 0.02 across
#     three collector runs. GET /markets/trades?ticker=...&limit=20 returned 20
#     prints, all at 0.0200: no 99c print ever existed. Its updated_time sat at
#     2026-04-28 throughout.
#   * KXAAAGASW-26NOV23-3.6200 printed at 0.9700 on 2026-11-21T06:28:37Z while
#     its updated_time still read 2026-11-15T21:34:40Z. So updated_time does NOT
#     advance on a trade and cannot be used to decide whether a print happened.
#
# The only authoritative record of executed prices is the trade tape itself, so
# that is what verifies a candidate:
#
#   GET /markets/trades?ticker=<t>&min_ts=<unix>&max_ts=<unix>
#   https://docs.kalshi.com/api-reference/market/get-trades
#
# Each entry carries yes_price_dollars, count_fp, created_time and trade_id, so a
# verified alert can show the actual prints behind the move and the reader can
# re-fetch the same window. Nothing here infers a price; a window with no prints,
# or a window this process could not read, is labelled as exactly that.
TAPE_SLACK_SECONDS = 90      # window widened by this much on both sides
NOTE_EVIDENCE = (
    "Trade-tape windows already fetched from the official demo API, keyed by "
    "ticker|window-start|window-end. Every verdict in alerts_archive.json carries the "
    "query it came from and the time the window was fetched, so it can be re-checked by "
    "requesting the same URL again. Written by scripts/build_alerts.py; never hand-edited."
)
TAPE_PAGE_LIMIT = 1000       # documented max for GET /markets/trades


def fetch_tape(base, ticker, from_ts, to_ts, getter):
    """Return (prints, error) for one market inside [from_ts - slack, to_ts + slack]."""
    params = {
        "ticker": ticker,
        "min_ts": int(from_ts) - TAPE_SLACK_SECONDS,
        "max_ts": int(to_ts) + TAPE_SLACK_SECONDS,
        "limit": TAPE_PAGE_LIMIT,
    }
    try:
        doc, url = getter("/markets/trades", params)
    except Exception as exc:                      # network, TLS, HTTP, JSON: all non-fatal
        return [], f"{type(exc).__name__}: {exc}"
    rows = []
    for t in (doc or {}).get("trades", []) or []:
        p = t.get("yes_price_dollars")
        try:
            price = float(p)
        except (TypeError, ValueError):
            continue
        ts = parse_ts(t.get("created_time"))
        if ts is None:
            continue
        rows.append({
            "trade_id": t.get("trade_id"),
            "created_time": t.get("created_time"),
            "_ts": ts.timestamp(),
            "yes_price_dollars": price,
            "count_fp": t.get("count_fp"),
            "taker_side": t.get("taker_outcome_side") or t.get("taker_side"),
        })
    rows.sort(key=lambda r: r["_ts"])
    return rows, None


def verify_with_tape(prints, threshold, start_price=None, start_time=None):
    """Decide a candidate against executed prints.

    Returns (verdict, detail) where verdict is one of:
      tape-confirmed       two consecutive prints in the window differ by >= threshold
      tape-flat            prints exist but none differ by >= threshold
      no-prints-in-window  the exchange has no prints in this window at all
      unverified           the tape could not be read, so nothing is claimed
    """
    if not prints:
        return "no-prints-in-window", (
            "the exchange's trade tape returns no prints for this market in this window, "
            "so the change between the two snapshots was not an executed move"
        )
    if len(prints) == 1 and "n_prints" in prints[0]:
        # Aggregate evidence: every print in the window was recorded at the same price.
        # With one distinct price no consecutive pair can differ, so this is sound without
        # the individual timestamps; anything richer is left unverified below.
        agg = prints[0]
        prices = agg.get("distinct_prices") or []
        if len(prices) == 1 and int(agg.get("n_prints") or 0) > 0:
            return "tape-flat", (
                f"all {agg['n_prints']} print(s) on the exchange tape in this window were at "
                f"{float(prices[0]):.4f}, so no two consecutive prints could differ by the "
                "threshold and the snapshot difference was not an executed move"
            )
        return "unverified", (
            "the recorded tape window carries more than one price but not the print order, "
            "so it cannot decide the move either way; left unverified"
        )
    # The price the market was reporting at the start of the interval is itself an executed
    # price (it is the market's own last-traded price), so it is a legitimate starting point.
    # Without it, a repricing whose executing print falls just inside the window but whose
    # predecessor falls just outside would be judged flat and wrongly discarded — measured
    # here on KXAAAGASM-26DEC31-3.30, where the 0.71 -> 0.29 print is at 22:27 (inside the
    # 20:01 -> 00:50 window) while the 0.71 prints it superseded were at 14:26 (outside it).
    chain = list(prints)
    if start_price is not None:
        chain = [{"trade_id": None, "created_time": start_time, "yes_price_dollars": float(start_price)}] + chain
    peak = None
    for prev, cur in zip(chain, chain[1:]):
        d = round(cur["yes_price_dollars"] - prev["yes_price_dollars"], 4)
        if abs(d) + EPS >= threshold and (peak is None or abs(d) > abs(peak["delta"])):
            peak = {
                "delta": d,
                "from_price": prev["yes_price_dollars"],
                "to_price": cur["yes_price_dollars"],
                "from_time": prev["created_time"],
                "to_time": cur["created_time"],
                "from_trade_id": prev["trade_id"],
                "to_trade_id": cur["trade_id"],
            }
    if peak:
        via = "the market's own price at the start of the interval followed by an exchange print" if peak["from_trade_id"] is None else "two consecutive exchange prints"
        return "tape-confirmed", (
            f"{via} moved {peak['from_price']:.2f} -> {peak['to_price']:.2f} "
            f"({peak['from_time']} -> {peak['to_time']}); trade ids "
            f"{peak['from_trade_id']} and {peak['to_trade_id']}"
        )
    return "tape-flat", (
        f"{len(prints)} print(s) on the exchange tape in this window, but no two consecutive "
        "prints differ by the threshold, so the snapshot difference was not an executed move"
    )


# Verdict -> what the row is allowed to claim. Only an executed move confirmed by the
# official trade tape counts as a move in the >= $0.10 feed.
KINDS = {
    "tape-confirmed": "move",
    "tape-flat": "restatement",
    "no-prints-in-window": "restatement",
    "unverified": "unverified",
}


def tape_window(prev, cur):
    from_ts, to_ts = parse_ts(prev.get("t")), parse_ts(cur.get("t"))
    if from_ts is None or to_ts is None:
        return None
    return int(from_ts.timestamp()), int(to_ts.timestamp())


def evidence_key(ticker, window):
    return f"{ticker}|{window[0]}|{window[1]}"


def verify_candidate(base, ticker, prev, cur, getter, threshold, evidence=None):
    """Run the tape check for one candidate change. Returns (verdict, detail, prints, source).

    `evidence` is an optional dict cache of windows already fetched. A cache hit is
    still labelled with the query it came from and the time it was fetched, so a
    verdict is never detached from its provenance; a miss is fetched live and stored
    in the cache, which the caller persists.
    """
    window = tape_window(prev, cur)
    if base is None or window is None:
        return "unverified", (
            "the trade tape could not be queried for this window (no base URL or "
            "unparseable observation time), so no verdict is claimed"
        ), [], None
    m0, m1 = window
    source = f"{base.rstrip('/')}/markets/trades?ticker={ticker}&min_ts={m0 - TAPE_SLACK_SECONDS}&max_ts={m1 + TAPE_SLACK_SECONDS}&limit={TAPE_PAGE_LIMIT}"
    key = evidence_key(ticker, window)
    cached = (evidence or {}).get(key)
    if cached and cached.get("trades") is not None:
        prints = [{k: v for k, v in t.items() if not k.startswith("_")} for t in cached["trades"]]
        verdict, detail = verify_with_tape(cached["trades"], threshold, prev.get("last"), prev.get("t"))
        return verdict, f"{detail} (tape window fetched {cached.get('fetched_at')})", prints, cached.get("source") or source
    prints, err = fetch_tape(base, ticker, m0, m1, getter)
    if err:
        return "unverified", f"the trade tape query failed ({err}), so no verdict is claimed", [], source
    if evidence is not None:
        evidence[key] = {
            "ticker": ticker,
            "window": {"min_ts": m0 - TAPE_SLACK_SECONDS, "max_ts": m1 + TAPE_SLACK_SECONDS},
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": source,
            "trades": [{k: v for k, v in p.items() if not k.startswith("_")} for p in prints],
        }
    verdict, detail = verify_with_tape(prints, threshold, prev.get("last"), prev.get("t"))
    return verdict, detail, [{k: v for k, v in p.items() if not k.startswith("_")} for p in prints], source


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--history", default=str(LIVE / "price_history.json"))
    ap.add_argument("--markets", default=str(LIVE / "markets.json"))
    ap.add_argument("--no-write-feed", action="store_true", help="only update the archive")
    ap.add_argument("--offline", action="store_true",
                    help="do not call the trade tape; every new candidate is stored as unverified "
                         "and no verdict is asserted (tests and air-gapped runs)")
    ap.add_argument("--relabel", action="store_true",
                    help="also re-verify rows already in the archive that carry no tape verdict")
    args = ap.parse_args()

    hist = load(Path(args.history))
    markets = load(Path(args.markets))
    rules = load(ROOT / "data" / "alert_rules.json")
    archive_path = LIVE / "alerts_archive.json"
    archive = load(archive_path) if archive_path.exists() else {"schema": 1, "alerts": []}
    # Two key sets on purpose. `known` prevents duplicate ARCHIVE entries and includes every
    # stored row, so a re-run never rewrites history. `detected` is what a fresh detection
    # pass would reproduce from the observations currently on disk; it drives the self-heal
    # below and cannot use a stored row whose from-observation has since been pruned.
    known = {(a["ticker"], a["from_time"], a["to_time"]) for a in archive["alerts"]}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    evidence_path = LIVE / "trade_evidence.json"
    evidence = load(evidence_path) if evidence_path.exists() else {"schema": 1, "note": NOTE_EVIDENCE, "windows": {}}
    evidence.setdefault("windows", {})

    base = markets.get("base_url") or _DEFAULT_BASE
    if args.offline or tape_get_impl is None:
        def tape_get(path, params):
            raise RuntimeError("--offline: the trade tape was not queried")
    else:
        tape_get = tape_get_impl

    threshold = float(rules["swing_threshold_dollars"])
    roi = rules["high_roi"]
    by_ticker = {m["ticker"]: m for m in markets.get("open_markets", [])}

    new_count = 0
    restated_count = 0
    for ticker, rec in hist.get("series", {}).items():
        obs = [o for o in rec.get("observations", []) if o.get("last") is not None]
        m = by_ticker.get(ticker)
        for prev, cur in zip(obs, obs[1:]):
            a, b = float(prev["last"]), float(cur["last"])
            delta = round(b - a, 4)
            if abs(delta) + EPS < threshold:
                continue
            verdict, verdict_detail, prints, tape_source = verify_candidate(base, ticker, prev, cur, tape_get, threshold, evidence["windows"])
            kind = KINDS[verdict]
            alert = {
                "ticker": ticker,
                "event_ticker": m.get("event_ticker") if m else None,
                "title": m.get("title") if m else None,
                "category_id": m.get("category_id") if m else None,
                "category_basis": m.get("category_basis") if m else None,
                "status": m.get("status") if m else None,
                "from_time": prev["t"],
                "to_time": cur["t"],
                # Verbatim exchange fields that back the verdict, plus the tape evidence.
                "from_updated_time": prev.get("updated_time"),
                "to_updated_time": cur.get("updated_time"),
                "to_previous_price": cur.get("previous_price"),
                "to_volume_fp": cur.get("volume_fp"),
                "kind": kind,
                "verification": verdict,
                "verification_detail": verdict_detail,
                "tape_source": tape_source,
                "tape_prints": prints,
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
            if kind == "restatement":
                restated_count += 1
            # Experimental screen = the dashboard's 'Model watch' filter (data/alert_rules.json). Decided at detection time.
            alert["first_seen_at"] = now
            alert["high_roi"] = bool(
                m is not None
                and m.get("category_basis") == roi["require_category_basis"]
                and (m.get("volume_24h_fp") or 0) > roi["require_volume_24h_gt"]
            )
            archive["alerts"].append(alert)

    # ---- provenance pass for rows archived before the move/restatement fields existed ----
    # Rows written before `kind` was recorded carry no evidence, so the feed cannot say
    # whether they are moves. The observations that produced them are still on disk, so the
    # same documented rule is applied now and the archive is labelled. Nothing is deleted:
    # a row keeps its prices, times and deltas, and only gains the classification the
    # evidence supports. A row whose window is no longer re-derivable is labelled
    # `legacy-unverifiable` and left where it is, so it is visible rather than silently
    # dropped or silently trusted.
    relabelled = 0
    for a in archive["alerts"]:
        # Rows that carried no verdict, or that were left unverified because the tape could not
        # be read, are re-checked: `unverified` asserts nothing, so improving it loses no
        # information. A row that already has a verdict is final and is never rewritten.
        if a.get("kind") and a.get("kind") != "unverified":
            continue
        if not args.relabel:
            break
        rec = (hist.get("series") or {}).get(a.get("ticker") or "") or {}
        obs = [o for o in (rec.get("observations") or []) if o.get("last") is not None]
        prev_o = next((o for o in obs if o.get("t") == a.get("from_time")), None)
        cur_o = next((o for o in obs if o.get("t") == a.get("to_time")), None)
        if prev_o is None or cur_o is None:
            a["kind"] = "legacy-unverifiable"
            a["kind_reason"] = (
                "archived before the move/restatement provenance was recorded, and the "
                "observations behind it are no longer in price_history.json; kept and shown "
                "with no claim either way"
            )
        else:
            verdict, detail, prints, source = verify_candidate(base, a.get("ticker"), prev_o, cur_o, tape_get, threshold, evidence["windows"])
            # Never downgrade a row that already had a verdict to `unverified`: an offline run must
            # not erase evidence it simply could not re-fetch this time.
            if verdict == "unverified" and a.get("kind") in ("move", "restatement"):
                continue
            a["kind"] = KINDS[verdict]
            a["verification"] = verdict
            a["verification_detail"] = detail
            a["tape_source"] = source
            a["tape_prints"] = prints
            a["from_updated_time"] = prev_o.get("updated_time")
            a["to_updated_time"] = cur_o.get("updated_time")
            a["to_previous_price"] = cur_o.get("previous_price")
            a["to_volume_fp"] = cur_o.get("volume_fp")
            relabelled += 1

    if args.offline or tape_get_impl is None:
        pass
    else:
        evidence["fetched_at"] = now
        evidence_path.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")

    archive["alerts"].sort(key=lambda r: (r["to_time"], abs(r["delta"])), reverse=True)
    archive["alerts"] = archive["alerts"][:ARCHIVE_LIMIT]
    archive_path.write_text(json.dumps(archive, indent=1) + "\n", encoding="utf-8")

    if args.no_write_feed:
        print(f"archive: +{new_count} new ({restated_count} restatement(s)), {len(archive['alerts'])} total")
        return 0

    # The brief's feed is a feed of MOVES of >= $0.10. A restatement (a difference the
    # exchange's own updated_time says cannot be a new print) is not a move, so it is
    # shown separately and never mixed into all_events. Rows written before `kind`
    # existed have no provenance; they are kept in all_events because dropping data on
    # the strength of a field that was never collected would be a silent rewrite.
    def is_move(a):
        return a.get("kind") == "move"

    all_feed = [a for a in archive["alerts"] if is_move(a)]
    restated_feed = [a for a in archive["alerts"] if a.get("kind") == "restatement"]
    unverified_feed = [a for a in archive["alerts"] if a.get("kind") not in ("move", "restatement")]
    roi_feed = [a for a in all_feed if a.get("high_roi")]

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
            "restatements_excluded": len(restated_feed),
            "unverified_excluded": len(unverified_feed),
            "relabelled_this_run": relabelled,
            "archive_total": len(archive["alerts"]),
            "new_this_run": new_count,
            "new_restatements_this_run": restated_count,
        },
        "all_events": newest_first(all_feed),
        "high_roi": newest_first(roi_feed),
        "restatements": newest_first(restated_feed),
        "unverified": newest_first(unverified_feed),
        "verification_rule": (
            "all_events contains only changes between two consecutive snapshots that the official "
            "trade tape confirms: two consecutive prints inside the window differing by at least the "
            "threshold (GET /markets/trades?ticker=&min_ts=&max_ts=). A change the tape shows to be "
            "flat, or for which the market has no prints in the window, is a restatement of the last "
            "trade rather than a move and is listed under 'restatements'. A change whose tape window "
            "could not be read is kept out of all_events and listed under 'unverified' with the "
            "query that failed. https://docs.kalshi.com/api-reference/market/get-trades"
        ),
        "disclaimers": [
            "Prices are last-traded prices from the Kalshi DEMO environment (mock funds).",
            "Each alert is a change between two consecutive collector observations, not a continuous tick stream.",
            "Differentials whose exchange updated_time did not advance are restatements, not moves; they are excluded from all_events and listed under restatements.",
            "Rows archived before the provenance fields existed are labelled legacy-unverifiable when their observations are no longer on disk; they are not deleted and not asserted to be moves.",
            "Alerts are kept in data/live/alerts_archive.json, so a move stays listed after its market leaves the open scan.",
            "cause_link is null on every alert: no official cause source has been collected, so none is shown.",
            "high_roi is the dashboard's experimental 'Model watch' screen (seed series with positive volume_24h). It is not an owner-approved ROI model.",
        ],
    }
    (LIVE / "alerts.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(
        f"OK: new={new_count} all_events={len(all_feed)} high_roi={len(roi_feed)} "
        f"restatements_excluded={len(restated_feed)} threshold=${threshold:.2f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
