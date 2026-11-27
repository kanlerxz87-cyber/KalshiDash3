#!/usr/bin/env python3
"""Live parity audit for the committed demo snapshot (session arena-035cd7c0).

Two modes:

  python3 scripts/audit_live_parity.py --compare data/audit/live_observations.json
      Offline: compare a recorded set of live observations against the committed
      data/live/markets.json + data/live/alerts.json. This mode needs no network
      and is the mode exercised in this session's verification.

  python3 scripts/audit_live_parity.py --fetch
      Re-fetch every selected record from the official demo Trade API over the
      network, write data/audit/live_observations.json, then run the same
      comparison. Requires outbound HTTPS to external-api.demo.kalshi.co.
      (This session's sandbox had no direct egress to that host; the recorded
      observations in data/audit/live_observations.json were fetched on
      2026-11-27 through the platform fetch route and transcribed field by
      field. Network mode is therefore provided for re-runs from a machine
      with egress and is not claimed as exercised here.)

Comparison contract (nothing is inferred; a field only passes when the
committed value equals the value returned by the official API):

  series  - categories, tags and title must match data/live/markets.json
            series_index exactly (topic classification parity).
  markets - immutable fields (event_ticker, title, close_time) must match.
            A row that is finalized on BOTH sides must match on result
            (yes/no), settlement_ts, settlement_value_dollars,
            last_price_dollars, volume_fp and open_interest_fp exactly.
            A row active on both sides must have empty result on both sides;
            price/volume drift is expected and recorded, not failed.
            A row that changed state between snapshot and fetch (e.g. was
            active at snapshot, finalized now) is recorded as
            "expected_drift_since_snapshot" and never fails.
            rules_primary is only compared when the committed row carries it
            (published settled rows do not).

Disclosed boundaries that never fail the exit code but are always listed:
  - a ticker absent from the published rows (alert archive covers a wider
    window than the size-capped published tables) -> "not_in_published_rows"
  - a series absent from series_index (an excluded series) -> "not_in_series_index"

Exit code 0 = no field mismatches. Exit code 1 = at least one real mismatch.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
IMMUTABLE = ("event_ticker", "title", "close_time")
FINALIZED = ("finalized", "settled")


def load_committed():
    markets = json.loads((ROOT / "data/live/markets.json").read_text())
    alerts = json.loads((ROOT / "data/live/alerts.json").read_text())
    rows = {r["ticker"]: r for r in markets["open_markets"] + markets["settled_markets"]}
    alert_rows = {a["ticker"]: a for a in alerts["all_events"]}
    return markets, rows, alert_rows


def num(v):
    return None if v is None else float(v)


def compare(obs, markets, rows, alert_rows):
    si = markets["series_index"]
    out = {"series": [], "markets": [], "mismatches": []}
    for s in obs["series"]:
        t = s["ticker"]
        c = si.get(t)
        if c is None:
            out["series"].append({"ticker": t, "status": "not_in_series_index",
                                  "observed_categories": s["categories"]})
            continue
        rec = {"ticker": t,
               "categories_match": (c.get("categories") or []) == s["categories"],
               "tags_match": (c.get("tags") or []) == s["tags"],
               "title_match": c.get("title") == s["title"]}
        if not (rec["categories_match"] and rec["tags_match"] and rec["title_match"]):
            rec["committed"] = {"categories": c.get("categories"), "tags": c.get("tags"),
                                "title": c.get("title")}
            rec["observed"] = {"categories": s["categories"], "tags": s["tags"],
                               "title": s["title"]}
            out["mismatches"].append({"kind": "series", "ticker": t})
        out["series"].append(rec)

    for o in obs["markets"]:
        t = o["ticker"]
        c = rows.get(t)
        if c is None:
            out["markets"].append({"ticker": t, "status": "not_in_published_rows",
                                   "alert_row_present": t in alert_rows,
                                   "observed_result": o.get("result"),
                                   "observed_status": o.get("status"),
                                   "source": o.get("url")})
            continue
        rec = {"ticker": t, "category_id": c["category_id"],
               "committed_status": c["status"], "observed_status": o.get("status"),
               "committed_result": c.get("result"), "observed_result": o.get("result"),
               "source": o.get("url")}
        bad = False
        for f in IMMUTABLE:
            ok = c.get(f) == o.get(f)
            rec[f + "_match"] = ok
            if not ok:
                bad = True
                rec[f + "_committed"] = c.get(f)
                rec[f + "_observed"] = o.get(f)
        if c.get("rules_primary"):
            ok = c["rules_primary"].startswith(o.get("rules_primary_prefix", ""))
            rec["rules_match"] = ok
            bad = bad or not ok
        else:
            rec["rules_match"] = None  # published settled rows carry no rules_primary
        cfin = c["status"] in FINALIZED
        ofin = o.get("status") in FINALIZED
        if cfin and ofin:
            rec["comparison"] = "finalized_vs_finalized"
            for field, co, oo in (
                ("result", (c.get("result") or ""), (o.get("result") or "")),
                ("settlement_ts", c.get("settlement_ts"), o.get("settlement_ts")),
                ("settlement_value", num(c.get("settlement_value_dollars")),
                 num(o.get("settlement_value_dollars"))),
                ("last_price", num(c.get("last_price_dollars")), num(o.get("last_price_dollars"))),
                ("volume", num(c.get("volume_fp")), num(o.get("volume_fp"))),
                ("open_interest", num(c.get("open_interest_fp")), num(o.get("open_interest_fp"))),
            ):
                ok = co == oo
                rec[field + "_match"] = ok
                if not ok:
                    bad = True
                    rec[field + "_committed"] = co
                    rec[field + "_observed"] = oo
        elif not cfin and not ofin:
            rec["comparison"] = "active_vs_active"
            rec["result_both_empty"] = (not c.get("result")) and (not o.get("result"))
            rec["last_price_committed"] = c.get("last_price_dollars")
            rec["last_price_observed"] = o.get("last_price_dollars")
            rec["volume_committed"] = c.get("volume_fp")
            rec["volume_observed"] = o.get("volume_fp")
            if not rec["result_both_empty"]:
                bad = True
        else:
            rec["comparison"] = "expected_drift_since_snapshot"
            rec["direction"] = ("committed_active_now_finalized"
                                if (not cfin and ofin) else "other")
        if t in alert_rows:
            a = alert_rows[t]
            rec["alert_row"] = {"to_price": a.get("to_price"), "delta": a.get("delta"),
                                "high_roi": a.get("high_roi"), "to_time": a.get("to_time")}
        if bad:
            out["mismatches"].append({"kind": "market", "ticker": t})
        out["markets"].append(rec)
    return out


def fetch_live(selection):
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "KalshiDash3-audit/1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    obs = {"note": "Re-fetched by scripts/audit_live_parity.py --fetch",
           "exchange_status": None, "series": [], "markets": [], "orderbooks": []}
    st = get(f"{BASE}/exchange/status")
    obs["exchange_status"] = {"url": f"{BASE}/exchange/status",
                              "exchange_active": st.get("exchange_active"),
                              "trading_active": st.get("trading_active")}
    for t in selection["series"]:
        s = get(f"{BASE}/series/{t}")["series"]
        obs["series"].append({"ticker": t, "categories": s.get("categories"),
                              "tags": s.get("tags"), "title": s.get("title"),
                              "fee_multiplier": s.get("fee_multiplier"),
                              "frequency": s.get("frequency"),
                              "url": f"{BASE}/series/{t}"})
    for t in selection["markets"]:
        mk = get(f"{BASE}/markets/{t}")["market"]
        obs["markets"].append({
            "ticker": t, "status": mk.get("status"), "result": mk.get("result") or "",
            "last_price_dollars": float(mk.get("last_price_dollars") or 0),
            "yes_bid_dollars": float(mk.get("yes_bid_dollars") or 0),
            "yes_ask_dollars": float(mk.get("yes_ask_dollars") or 0),
            "volume_fp": float(mk.get("volume_fp") or 0),
            "open_interest_fp": float(mk.get("open_interest_fp") or 0),
            "event_ticker": mk.get("event_ticker"), "title": mk.get("title"),
            "close_time": mk.get("close_time"), "settlement_ts": mk.get("settlement_ts"),
            "settlement_value_dollars": (float(mk["settlement_value_dollars"])
                                         if mk.get("settlement_value_dollars") is not None else None),
            "rules_primary_prefix": (mk.get("rules_primary") or "")[:40],
            "url": f"{BASE}/markets/{t}"})
    return obs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", metavar="OBS_JSON",
                    help="offline: compare recorded observations to committed data")
    ap.add_argument("--fetch", action="store_true",
                    help="network: re-fetch data/audit/selection.json from the live API first")
    args = ap.parse_args()

    if args.fetch:
        selection = json.loads((ROOT / "data/audit/selection.json").read_text())
        obs = fetch_live(selection)
        path = ROOT / "data/audit/live_observations.json"
        path.write_text(json.dumps(obs, indent=1))
        print(f"fetched {len(obs['series'])} series + {len(obs['markets'])} markets -> {path}")
    elif args.compare:
        obs = json.loads(Path(args.compare).read_text())
    else:
        ap.error("choose --compare OBS_JSON or --fetch")

    markets, rows, alert_rows = load_committed()
    res = compare(obs, markets, rows, alert_rows)
    out_path = ROOT / "data/audit/parity_results.json"
    out_path.write_text(json.dumps(res, indent=1))

    n_series = len(res["series"])
    n_markets = len(res["markets"])
    n_fin = sum(1 for r in res["markets"] if r.get("comparison") == "finalized_vs_finalized")
    n_act = sum(1 for r in res["markets"] if r.get("comparison") == "active_vs_active")
    n_drift = sum(1 for r in res["markets"] if r.get("comparison") == "expected_drift_since_snapshot")
    n_absent = sum(1 for r in res["markets"] if r.get("status") == "not_in_published_rows")
    n_sabsent = sum(1 for r in res["series"] if r.get("status") == "not_in_series_index")
    print(f"series observed: {n_series} ({n_sabsent} not in series_index, listed not failed)")
    print(f"markets observed: {n_markets} = {n_fin} finalized + {n_act} active + "
          f"{n_drift} state-drift + {n_absent} not-in-published-rows")
    if res["mismatches"]:
        print(f"MISMATCHES: {len(res['mismatches'])}")
        for m in res["mismatches"]:
            print("  ", m)
        sys.exit(1)
    print("OK: every compared field equals the committed value (no inference, no tolerance).")
    print(f"results -> {out_path}")


if __name__ == "__main__":
    main()
