#!/usr/bin/env python3
"""Paper-trade the fixed strategies in data/strategies.json on the swing alerts.

PAPER ONLY. No order is placed, no account is used, and no credentials are read.
Each strategy is a fixed rule applied to committed observations, so the results
show what the rule would have produced at the observed prices. They do not show
what a trader would have earned. Demo prices may not reflect real markets
(https://docs.kalshi.com/getting_started/demo_env).

Inputs (all committed by scripts/collect.py and scripts/build_alerts.py)
  data/live/alerts_archive.json  every $0.10+ swing ever detected (append-only)
  data/live/price_history.json   one observation per market per collector run;
                                 the entry quote is the observation at to_time
  data/live/markets.json         current bids for marking, and the settled list
  data/strategies.json           strategy rules and the fee model
  data/live/simulation.json      previous state, so each alert is processed once

Output
  data/live/simulation.json      per-strategy counters, open and settled positions,
                                 topic and trade-type breakdowns

Entry: taker at the ask observed at the alert's to_time. Preferred source: the
to_yes_bid / to_yes_ask fields on the archive entry (requested as R-2; see
COORDINATION.md). Fallback: the price_history observation with that timestamp,
which exists only while the market is in the open scan. YES buys at the yes ask;
NO buys at 1 - yes bid (documented reciprocal relation:
https://docs.kalshi.com/getting_started/orderbook_responses). Nothing is filled
from a last-trade price.
Settlement: only when the market is in the settled list with result yes or no
(https://docs.kalshi.com/getting_started/market_settlement).
Fee: the official taker fee (https://kalshi.com/docs/kalshi-fee-schedule.pdf).

Run: python3 scripts/simulate.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live"
STRAT_PATH = ROOT / "data" / "strategies.json"
OUT = LIVE / "simulation.json"
MAX_CLOSED_KEPT = 200
MAX_OPEN_KEPT = 1000


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fnum(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def taker_fee(price: float, contracts: int, multiplier: int) -> float:
    """fee = round up to the next cent of M x 0.07 x C x P x (1 - P).

    Reproduces the General Trading Fees table for 1 and 100 contracts (see
    scripts/tests/test_alerts_sim.py).
    """
    if multiplier == 0:
        return 0.0
    p = Decimal(str(price))
    raw = Decimal(multiplier) * Decimal("0.07") * Decimal(contracts) * p * (Decimal(1) - p)
    cents = (raw * 100).to_integral_value(rounding=ROUND_CEILING)
    return float(cents / 100)


def multiplier_for(series: str | None, strat: dict) -> int:
    fm = strat["fee_model"]
    if series and series.upper() in fm["multipliers"]:
        return int(fm["multipliers"][series.upper()])
    return int(fm["default_taker_multiplier"])


def band_of(price: float, bands: list[dict]) -> str:
    for b in bands:
        if price < b["max_exclusive"]:
            return b["id"]
    return bands[-1]["id"]


def alert_key(a: dict) -> str:
    return f"{a['ticker']}@{a['from_time']}>{a['to_time']}"


def quote_for_signal(sig: dict, hist: dict):
    """Return (yes_bid, yes_ask, source) at the alert's to_time, or None.

    Preferred: quotes carried on the archive entry itself (fields to_yes_bid /
    to_yes_ask, requested from the alert builder; see COORDINATION.md). Fallback:
    the price_history observation whose timestamp equals to_time. The fallback
    exists only while the market is still in the open scan; expired markets have
    no stored quote, and their signals are not filled.
    """
    if "to_yes_bid" in sig or "to_yes_ask" in sig:
        return fnum(sig.get("to_yes_bid")), fnum(sig.get("to_yes_ask")), "archive"
    for o in (hist.get(sig["ticker"]) or {}).get("observations", []):
        if o.get("t") == sig["to_time"]:
            return fnum(o.get("yes_bid")), fnum(o.get("yes_ask")), "price_history"
    return None


def empty_counters() -> dict:
    return {"signals": 0, "not_filled": 0, "not_filled_no_quote": 0, "not_filled_bad_price": 0,
            "not_filled_wide_spread": 0, "voided": 0, "skipped_duplicate": 0, "filled": 0,
            "settled": 0, "wins": 0, "losses": 0, "realized_net": 0.0}


def bump(counters: dict, key: str, field: str, amount=1):
    # Tolerates state written by an earlier version of this script (missing newer counters).
    dst = counters.setdefault(key, {})
    dst[field] = dst.get(field, 0) + amount


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def main() -> int:
    strat = json.loads(STRAT_PATH.read_text())
    archive = load_json(LIVE / "alerts_archive.json", {"alerts": []})
    hist = load_json(LIVE / "price_history.json", {}).get("series", {})
    markets = json.loads((LIVE / "markets.json").read_text())
    prior = load_json(OUT, {})
    state = prior.get("state", {})
    now = utcnow()

    open_rows = {r["ticker"]: r for r in (markets.get("open_markets") or []) if r.get("ticker")}
    settled_rows = {r["ticker"]: r for r in (markets.get("settled_markets") or [])
                    if r.get("ticker") and r.get("result") in ("yes", "no", "scalar")}
    base = markets.get("base_url") or "https://external-api.demo.kalshi.co/trade-api/v2"

    strategies = strat["strategies"]
    max_spread = float(strat["max_quote_spread_dollars"])
    bands = strat["trade_type_bands"]
    contracts = int(strat["contracts_per_signal"])
    alerts = archive.get("alerts", [])
    # Trade on CONFIRMED moves only. A row whose difference the official trade tape shows to be a
    # restatement (no executed print moved the price) is not a signal: trading it would model an
    # entry at a price nobody transacted. Rows with no verdict yet keep their old behaviour so
    # the committed simulation can be reproduced from history.
    alerts = [a for a in alerts if a.get("kind") != "restatement"]
    archive_keys = {alert_key(a) for a in alerts}

    processed = set(state.get("processed_alert_ids", []))
    positions = {p["id"]: p for p in state.get("open", [])}
    closed = list(state.get("closed", []))
    counters = state.get("counters", {})

    # 1) New signals, oldest first.
    fresh = sorted((a for a in alerts if alert_key(a) not in processed), key=lambda a: a["to_time"])
    for sig in fresh:
        key = alert_key(sig)
        processed.add(key)
        q = quote_for_signal(sig, hist)
        for st in strategies:
            if st["signal_filter"] == "high_roi" and not sig.get("high_roi"):
                continue
            bump(counters, st["id"], "signals")
            if q is None:
                bump(counters, st["id"], "not_filled")
                bump(counters, st["id"], "not_filled_no_quote")
                continue
            yes_bid, yes_ask, quote_src = q
            up = sig["direction"] == "up"
            follow = st["side_rule"] == "follow"
            side = "yes" if (up == follow) else "no"
            if side == "yes":
                entry = yes_ask
            else:
                entry = None if yes_bid is None else round(1.0 - yes_bid, 4)
            if entry is None:
                bump(counters, st["id"], "not_filled")
                bump(counters, st["id"], "not_filled_no_quote")
                continue
            if not (0.01 <= entry <= 0.99):
                bump(counters, st["id"], "not_filled")
                bump(counters, st["id"], "not_filled_bad_price")
                continue
            if yes_bid is not None and yes_ask is not None and (yes_ask - yes_bid) > max_spread + 1e-9:
                bump(counters, st["id"], "not_filled")
                bump(counters, st["id"], "not_filled_wide_spread")
                continue
            dup = any(p["strategy"] == st["id"] and p["ticker"] == sig["ticker"] and p["status"] == "open"
                      for p in positions.values())
            if dup:
                bump(counters, st["id"], "skipped_duplicate")
                continue
            series = sig.get("series_ticker") or (sig["ticker"].split("-")[0] if "-" in sig["ticker"] else sig["ticker"])
            mult = multiplier_for(series, strat)
            fee = taker_fee(entry, contracts, mult)
            band = band_of(entry, bands)
            cat = sig.get("category_id") or "unknown"
            tt_key = f"{cat} | move {sig['direction']} | entry {band}"
            pid = f"{st['id']}|{key}|{side}"
            positions[pid] = {
                "id": pid, "strategy": st["id"], "alert_key": key, "ticker": sig["ticker"],
                "title": sig.get("title"), "category_id": cat, "category_basis": sig.get("category_basis"),
                "series_ticker": series, "direction": sig["direction"], "side": side,
                "trade_type": tt_key, "band": band, "entry_price": round(entry, 4),
                "entry_fee": fee, "taker_multiplier": mult, "contracts": contracts,
                "entered_at": sig["to_time"], "quote_bid": yes_bid, "quote_ask": yes_ask, "quote_source": quote_src,
                "status": "open", "outcome": None, "settled_at": None, "settled_result": None,
                "realized_net": None, "bid_now": None, "unrealized_net": None, "mark_note": None,
                "source": sig.get("market_source"),
            }
            bump(counters, st["id"], "filled")
            bump(counters, f"_cat|{st['id']}|{cat}", "filled")
            tt = counters.setdefault("_trade_types", {})
            tt.setdefault(tt_key, {"filled": 0, "settled": 0, "wins": 0, "losses": 0, "realized_net": 0.0})
            tt[tt_key]["filled"] += 1

    # 2) Void, settle, or mark every open position.
    for pid in list(positions):
        p = positions[pid]
        if p.get("quote_bid") is not None and p.get("quote_ask") is not None \
                and (p["quote_ask"] - p["quote_bid"]) > max_spread + 1e-9:
            # The entry quote breached the spread rule (possible only for fills made before the rule existed).
            p.update(status="voided", outcome="void", mark_note=f"entry spread above {max_spread:.2f}: not a tradable quote")
            bump(counters, p["strategy"], "voided")
            closed.append(p)
            del positions[pid]
            continue
        res = settled_rows.get(p["ticker"])
        if res and res["result"] == "scalar":
            p.update(status="settled_scalar", settled_result="scalar", settled_at=res.get("settlement_ts"),
                     outcome="not_scored", mark_note="scalar settlement: not scored as yes/no")
            closed.append(p)
            del positions[pid]
            continue
        if res and res["result"] in ("yes", "no"):
            won = res["result"] == p["side"]
            net = round((1.0 if won else 0.0) - p["entry_price"] - p["entry_fee"], 4)
            p.update(status="settled", settled_result=res["result"], settled_at=res.get("settlement_ts"),
                     outcome="win" if won else "loss", realized_net=net, unrealized_net=None)
            bump(counters, p["strategy"], "settled")
            bump(counters, p["strategy"], "wins" if won else "losses")
            bump(counters, p["strategy"], "realized_net", net)
            cat_key = f"_cat|{p['strategy']}|{p['category_id']}"
            bump(counters, cat_key, "settled")
            bump(counters, cat_key, "wins" if won else "losses")
            bump(counters, cat_key, "realized_net", net)
            tt = counters["_trade_types"][p["trade_type"]]
            tt["settled"] += 1
            tt["wins" if won else "losses"] += 1
            tt["realized_net"] = round(tt["realized_net"] + net, 4)
            closed.append(p)
            del positions[pid]
            continue
        cur = open_rows.get(p["ticker"])
        if cur is None:
            p["bid_now"] = None
            p["unrealized_net"] = None
            p["mark_note"] = "not in the latest snapshot and not settled: no price, nothing marked"
            continue
        bid = fnum(cur.get("yes_bid_dollars") if p["side"] == "yes" else cur.get("no_bid_dollars"))
        p["bid_now"] = bid
        p["mark_at"] = markets.get("collected_at")
        p["mark_note"] = None
        if bid is None:
            p["unrealized_net"] = None
        else:
            exit_fee = taker_fee(bid, contracts, multiplier_for(p.get("series_ticker"), strat))
            p["unrealized_net"] = round(bid - p["entry_price"] - p["entry_fee"] - exit_fee, 4)

    # 3) Summaries and state for the next run.
    open_list = sorted(positions.values(), key=lambda p: p["entered_at"], reverse=True)[:MAX_OPEN_KEPT]
    closed_list = sorted(closed, key=lambda p: p.get("settled_at") or "", reverse=True)[:MAX_CLOSED_KEPT]
    min_n = int(strat["min_settled_for_conclusion"])

    summaries = []
    for st in strategies:
        c = {**empty_counters(), **counters.get(st["id"], {})}
        opens = [p for p in open_list if p["strategy"] == st["id"]]
        unreal = [p["unrealized_net"] for p in opens if p["unrealized_net"] is not None]
        n = c["settled"]
        cats = {}
        for k, v in counters.items():
            if k.startswith(f"_cat|{st['id']}|"):
                cats[k.split("|")[2]] = {
                    "filled": v.get("filled", 0), "settled": v.get("settled", 0),
                    "wins": v.get("wins", 0), "losses": v.get("losses", 0),
                    "realized_net": round(v.get("realized_net", 0.0), 4),
                }
        summaries.append({
            "id": st["id"], "name": st["name"], "side_rule": st["side_rule"],
            "signal_filter": st["signal_filter"], "description": st["description"],
            "signals": c["signals"], "not_filled": c["not_filled"], "not_filled_wide_spread": c["not_filled_wide_spread"],
            "voided": c["voided"],
            "not_filled_no_quote": c["not_filled_no_quote"], "not_filled_bad_price": c["not_filled_bad_price"],
            "not_filled_wide_spread": c["not_filled_wide_spread"], "voided": c["voided"],
            "skipped_duplicate": c["skipped_duplicate"],
            "filled": c["filled"], "open": len(opens), "settled": n, "wins": c["wins"], "losses": c["losses"],
            "hit_rate": round(c["wins"] / n, 4) if n else None,
            "realized_net": round(c["realized_net"], 4),
            "unrealized_net_open": round(sum(unreal), 4) if unreal else None,
            "avg_realized_per_settled": round(c["realized_net"] / n, 4) if n else None,
            "conclusion": (f"Insufficient sample: {n} settled of {min_n} needed." if n < min_n
                           else "Sample reached: compare the hit rate and realised net with the fee-inclusive baseline."),
            "by_category": cats,
        })

    trade_types = [{"trade_type": k, **v, "hit_rate": round(v["wins"] / v["settled"], 4) if v["settled"] else None}
                   for k, v in sorted((counters.get("_trade_types") or {}).items())]

    # Alerts leave the archive only if it is trimmed; ids for trimmed alerts can never return.
    processed = sorted(k for k in processed if k in archive_keys)

    doc = {
        "schema": 1,
        "environment": "demo",
        "mode": strat["mode"],
        "generated_at": now,
        "snapshot_collected_at": markets.get("collected_at"),
        "rules_file": "data/strategies.json",
        "signals_file": "data/live/alerts_archive.json",
        "endpoint": base,
        "fee_model_source": strat["fee_model"]["source"],
        "counts": {
            "signals_processed_total": len(processed),
            "new_signals_this_run": len(fresh),
            "open_positions": len(open_list),
            "settled_positions_kept": len(closed_list),
        },
        "strategies": summaries,
        "trade_types": trade_types,
        "open_positions": open_list,
        "settled_positions": closed_list,
        "disclaimers": [
            "PAPER ONLY. No orders are placed and no account is used. Results are what the fixed rules would have produced at observed prices.",
            "Demo prices may not reflect real markets (https://docs.kalshi.com/getting_started/demo_env).",
            "Entry is at the observed ask in the observation at the alert time. No slippage beyond that and no fill-probability model.",
            "A signal is not filled when no bid/ask was stored at the alert time (not_filled_no_quote). The collector stores quotes only while a market is in its open scan, so most expired markets have none. Nothing is filled from last-trade prices.",
            "Fees are the official taker fee. The multipliers were read from the PDF text (see strategies.json multiplier_caveat).",
            "A quote whose yes ask minus yes bid exceeds max_quote_spread_dollars is not treated as tradable: such a signal is not filled, and an open position with such an entry quote is voided.",
            "Sample sizes are small until settled positions reach min_settled_for_conclusion. No strategy is recommended before that.",
        ],
        "state": {"processed_alert_ids": processed, "open": open_list, "closed": closed_list, "counters": counters},
    }
    LIVE.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"simulate: {len(fresh)} new signal(s); open={len(open_list)} settled_kept={len(closed_list)} -> data/live/simulation.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
