#!/usr/bin/env python3
"""Live-desk scan: fee-aware ROI picks + >=$0.10 swing alerts, written to data/live/roi.json.

Runs with NO credentials and NO manual input, from GitHub Actions
(.github/workflows/desk.yml). It calls only public, unauthenticated demo endpoints:

  GET /markets ............... https://docs.kalshi.com/api-reference/market/get-markets
  GET /markets/orderbooks ..... https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks
  GET /series/../candlesticks . https://docs.kalshi.com/api-reference/market/get-market-candlesticks
  GET /historical/cutoff ...... https://docs.kalshi.com/getting_started/historical_data

Design rules this file obeys:
  * One model, one file: data/roi_model.json, shared with the browser (assets/live.js).
  * Nothing is inferred. A value that the API did not return is written as null and the
    page renders it blank; a price band, hit rate or catalyst link is never invented.
  * It never writes files owned by scripts/collect.py (data/live/markets.json,
    price_history.json); it only reads them, to keep parallel sessions from colliding.

Exit codes: 0 ok, 2 the demo API was unreachable (nothing is overwritten).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import roi_model as RM          # noqa: E402  the shared model (browser mirror: assets/live.js)
import collect as COLLECT       # noqa: E402  reuse the collector's classifier so topics match exactly

LIVE = ROOT / "data" / "live"
BASE = os.environ.get("KALSHI_BASE", "https://external-api.demo.kalshi.co/trade-api/v2")
UA = "KalshiDash3-live-desk/1.0 (+https://github.com/kanlerxz87-cyber/KalshiDash3)"
INTERVAL = 0.4  # polite spacing between calls; 429 is handled by backoff


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(path: str, params: dict | None = None, retries: int = 3):
    url = BASE + path
    if params:
        from urllib.parse import urlencode
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            # doseq=True: a list value becomes REPEATED parameters
            # (?tickers=A&tickers=B), which is how Kalshi expects array arguments.
            url += "?" + urlencode(clean, doseq=True)
    last = None
    for attempt in range(retries):
        time.sleep(INTERVAL)
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8")), url
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code == 429:                      # documented: back off, no penalty
                time.sleep(2.0 * (attempt + 1))
                continue
            break
        except Exception as e:  # noqa: BLE001 - network/TLS/DNS
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{last} for {url}")


def paged_markets(params: dict, cap: int):
    """Page GET /markets with the documented cursor, deduplicated by ticker."""
    out, cursor, seen = {}, "", 0
    while True:
        d, _ = get("/markets", {**params, "limit": 1000, "cursor": cursor or None})
        batch = d.get("markets") or []
        for m in batch:
            if m.get("ticker"):
                out[m["ticker"]] = m
        seen += len(batch)
        cursor = d.get("cursor") or ""
        if not cursor or not batch or seen >= cap:
            break
    return list(out.values())


def books_for(tickers: list[str], depth_source_note: str) -> dict:
    """GET /markets/orderbooks takes 1-100 tickers per call. Bids only, ascending, best last.

    The `tickers` argument is an ARRAY and the API does not split a comma-joined
    value: `?tickers=A,B` is parsed as ONE ticker literally named "A,B" and the
    endpoint answers with a single EMPTY book for it (measured against the live
    demo API, and consistent with the order-book guide, which says an unknown
    ticker returns an empty entry rather than an error:
    https://docs.kalshi.com/getting_started/orderbook_responses).
    The array therefore has to be sent as repeated parameters
    (`?tickers=A&tickers=B`), which is what `get()` does for a list value.
    """
    out: dict[str, dict] = {}
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        try:
            d, url = get("/markets/orderbooks", {"tickers": chunk})
        except RuntimeError as e:
            print(f"  ! orderbooks chunk failed: {e}", file=sys.stderr)
            continue
        for ob in d.get("orderbooks") or []:
            yes = (ob.get("orderbook_fp") or {}).get("yes_dollars") or []
            no = (ob.get("orderbook_fp") or {}).get("no_dollars") or []
            best_yes = yes[-1] if yes else None
            best_no = no[-1] if no else None
            out[ob.get("ticker")] = {
                "depth_at_bid": RM.num(best_yes[1]) if best_yes else 0.0,
                "depth_at_ask": RM.num(best_no[1]) if best_no else 0.0,
                "bid_price": RM.num(best_yes[0]) if best_yes else None,
                "ask_price": (1.0 - RM.num(best_no[0])) if best_no else None,
                "yes_ladder": [{"price": RM.num(r[0]), "contracts": RM.num(r[1])} for r in yes if isinstance(r, list)],
                "no_ladder": [{"price": RM.num(r[0]), "contracts": RM.num(r[1])} for r in no if isinstance(r, list)],
                "source": url,
            }
    for v in out.values():
        v["note"] = depth_source_note
    return out


def load_history(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()).get("series", {})
    except json.JSONDecodeError:
        return {}


def momentum_from(series: list[dict], lookback_min: float, now_ms: int):
    """Δlast over the lookback window from this project's own observations.

    Returns None when the retained history is too old to answer (candlesticks cannot
    fill the gap: the shortest documented interval is 1 minute, and seconds resolution
    is not offered at all — https://docs.kalshi.com/api-reference/market/get-market-candlesticks).
    """
    if not series:
        return None
    try:
        newest = RM.datetime_ms(series[-1]["t"])
    except (KeyError, ValueError):
        return None
    if now_ms - newest > 2 * lookback_min * 60000:
        return None
    back_target = now_ms - lookback_min * 60000
    cur = RM.num(series[-1].get("last"))
    cand = [o for o in series if RM.datetime_ms(o["t"]) <= back_target and RM.num(o.get("last")) is not None]
    if not cand or cur is None:
        return None
    return cur - RM.num(cand[-1]["last"])


def replay_settled(model: dict, markets: list[dict], max_markets: int) -> dict:
    """Out-of-sample hit rate: signal from 1-minute candles before close, outcome from settlement.

    Reduced feature set, on purpose and stated in the output: candles carry price
    aggregates only, so depth/volume/seed filters cannot be reconstructed historically.
    """
    res = {
        "markets_tested": 0, "candles_used": 0, "signals": 0, "hits": 0, "misses": 0,
        "baseline_always_yes_bets": 0, "baseline_always_yes_hits": 0,
        "pnl_per_100_contracts": 0.0, "rois": [], "by_category": {}, "skipped": {},
        "method": "For each settled market: take the last 1-minute candle ending at or before "
                  "close_time; form q from that candle's yes_bid/yes_ask close (mid) and price close (last), "
                  "with the micro weight folded into mid; buy the side the screen prefers at that candle's price; "
                  "settle at $1 for the winning side, $0 for the losing side, per "
                  "https://docs.kalshi.com/getting_started/market_settlement. Taker fee applied with the "
                  "general formula from https://kalshi.com/docs/kalshi-fee-schedule.pdf.",
        "not_measured": [
            "the depth, 24h-volume and fee-schedule-seed filters, which a historical candle cannot reproduce",
            "slippage beyond crossing the quoted price",
            "any production market: this is the demo environment",
        ],
    }
    skip = res["skipped"]
    f = model["parameters"]["filters"]
    for m in markets:
        if res["markets_tested"] >= max_markets:
            break
        result = str(m.get("result") or "").lower()
        if result not in ("yes", "no"):
            skip["result not yes/no (scalar or empty)"] = skip.get("result not yes/no (scalar or empty)", 0) + 1
            continue
        if COLLECT.is_multivariate(m):
            skip["multivariate combo"] = skip.get("multivariate combo", 0) + 1
            continue
        close = m.get("close_time")
        if not close:
            skip["no close_time"] = skip.get("no close_time", 0) + 1
            continue
        try:
            close_ms = RM.datetime_ms(close)
        except ValueError:
            skip["unparsable close_time"] = skip.get("unparsable close_time", 0) + 1
            continue
        series_ticker = COLLECT.series_of(m)
        path = f"/series/{series_ticker}/markets/{m['ticker']}/candlesticks"
        try:
            d, url = get(path, {
                "start_ts": int(close_ms / 1000) - 7200,
                "end_ts": int(close_ms / 1000),
                "period_interval": 1,
            }, retries=2)
        except RuntimeError as e:
            skip[f"candlesticks unavailable"] = skip.get("candlesticks unavailable", 0) + 1
            continue
        cs = d.get("candlesticks") or []
        if not cs:
            skip["no candles in the 2h before close"] = skip.get("no candles in the 2h before close", 0) + 1
            continue
        res["markets_tested"] += 1
        res["candles_used"] += len(cs)
        c = cs[-1]
        bid = RM.quote(RM.num((c.get("yes_bid") or {}).get("close_dollars")))
        ask = RM.quote(RM.num((c.get("yes_ask") or {}).get("close_dollars")))
        last = RM.num((c.get("price") or {}).get("close_dollars"))
        if last is not None and last <= 0.0:
            last = None
        if bid is None and ask is None:
            skip["candle without quotes"] = skip.get("candle without quotes", 0) + 1
            continue
        w = model["parameters"]["weights"]
        mid = (bid + ask) / 2 if (bid is not None and ask is not None) else last
        if mid is None or last is None:
            skip["candle without a price"] = skip.get("candle without a price", 0) + 1
            continue
        q = RM.clip((w["mid"] + w["micro"]) * mid + w["last"] * last, *model["parameters"]["clip_q"])
        mult = RM.series_mult(series_ticker, model)
        sides = []
        if ask is not None:
            fee = RM.taker_fee_unit(ask, mult["taker"])
            cost = ask + fee
            if cost > 0:
                sides.append({"side": "YES", "entry": ask, "cost": cost, "roi": (q - cost) / cost})
        if bid is not None:
            pno = 1 - bid
            fee = RM.taker_fee_unit(pno, mult["taker"])
            cost = pno + fee
            if cost > 0:
                sides.append({"side": "NO", "entry": pno, "cost": cost, "roi": (1 - q - cost) / cost})
        # Only the price-side gates the replay can honestly apply.
        sides = [s for s in sides
                 if f["min_entry_price"] <= s["entry"] <= f["max_entry_price"] and s["roi"] > f["min_net_roi"]]
        if bid is not None and ask is not None and (ask - bid) > f["max_spread"]:
            sides = []
        res["baseline_always_yes_bets"] += 1
        if result == "yes":
            res["baseline_always_yes_hits"] += 1
        if not sides:
            skip["no side passed the replay gates"] = skip.get("no side passed the replay gates", 0) + 1
            continue
        best = sorted(sides, key=lambda s: -s["roi"])[0]
        res["signals"] += 1
        won = (best["side"] == "YES" and result == "yes") or (best["side"] == "NO" and result == "no")
        res["hits"] += 1 if won else 0
        res["misses"] += 0 if won else 1
        stake = best["cost"] * 100.0
        payout = 100.0 if won else 0.0
        res["pnl_per_100_contracts"] = round(res["pnl_per_100_contracts"] + payout - stake, 4)
        res["rois"].append(round(payout / stake - 1 if stake else 0.0, 6))
        cat = COLLECT.classify(COLLECT.load_categories(), series_ticker, None, None, m.get("title") or m.get("yes_sub_title"))
        cid = cat[0] or "unclassified"
        b = res["by_category"].setdefault(cid, {"signals": 0, "hits": 0, "pnl_per_100_contracts": 0.0})
        b["signals"] += 1
        b["hits"] += 1 if won else 0
        b["pnl_per_100_contracts"] = round(b["pnl_per_100_contracts"] + (100.0 if won else 0.0) - stake, 4)
    rois = sorted(res.pop("rois"))
    if rois:
        res["mean_net_roi"] = round(sum(rois) / len(rois), 6)
        res["median_net_roi"] = round(rois[len(rois) // 2], 6)
    if res["signals"]:
        res["hit_rate"] = round(res["hits"] / res["signals"], 4)
    else:
        res["hit_rate"] = None
    if res["baseline_always_yes_bets"]:
        res["baseline_always_yes_hit_rate"] = round(
            res["baseline_always_yes_hits"] / res["baseline_always_yes_bets"], 4)
    return res


def build(validate_n: int, out_path: Path) -> dict:
    model = RM.load_model()
    cats = COLLECT.load_categories()
    now = utcnow()
    now_ms = RM.datetime_ms(now)
    started = time.time()
    print(f"desk: {BASE}  model={model['id']}")

    # 1. open markets, combos excluded by the documented filter as well as by the local guard
    open_ms = paged_markets({"status": "open", "mve_filter": "exclude"}, cap=4000)
    print(f"  open markets: {len(open_ms)}")

    series_idx = COLLECT.fetch_series_index()

    # The paged scan is capped, and the demo exchange is full of multivariate combos and
    # long-dated event series, so a fee-schedule-confirmed series can fall OUTSIDE the
    # window entirely. Measured 2026-11-20: with the 4000-market cap the scan's in-scope
    # set held 214 markets and contained NO market of the confirmed gas, golf, elections
    # or crypto seed series - only zero-volume crypto event contracts - so every score
    # was "no quoted price at all" and no pick could be produced. Querying each seed
    # series explicitly (the same method scripts/collect.py uses) makes the confirmed
    # data reachable no matter where the paged window ends.
    seeded: dict[str, dict] = {}
    for c in cats["categories"]:
        for seed in c.get("seed_series", []):
            try:
                d, _ = get("/markets", {"series_ticker": seed["ticker"], "status": "open", "limit": 1000})
            except RuntimeError as e:
                print(f"  ! seed {seed['ticker']}: {e}", file=sys.stderr)
                continue
            for m in d.get("markets") or []:
                if m.get("ticker"):
                    seeded[m["ticker"]] = m
    have = {m.get("ticker") for m in open_ms}
    added = [t for t in seeded if t not in have]
    open_ms.extend(seeded[t] for t in added)
    print(f"  seed series: {len(seeded)} market(s), {len(added)} outside the paged window")

    rows, seen_combo = [], 0
    # NOTE: `category_id`/`category_basis` are NOT API fields — GET /markets has no topic
    # field. They are this project's classification, attached to the market object here so
    # the model's require_seed_category gate reads exactly what the page reads (the browser
    # mirror attaches the same two keys in scoreAll()).
    for m in open_ms:
        if COLLECT.is_multivariate(m):
            seen_combo += 1
            continue
        st = COLLECT.series_of(m)
        s = series_idx.get(st, {})
        cid, basis = COLLECT.classify(cats, st, s.get("title"),
                                      " ".join(s.get("categories") or []) if s.get("categories") else s.get("category"),
                                      m.get("title") or m.get("yes_sub_title"))
        if not cid:
            continue
        if str(m.get("status") or "").lower() in ("finalized", "determined", "closed", "settled"):
            continue
        m["category_id"] = cid
        m["category_basis"] = basis
        rows.append({"m": m, "cid": cid, "basis": basis, "series": st})
    print(f"  in scope: {len(rows)} open markets in the five categories ({seen_combo} combos skipped by the local guard)")

    # 2. ranking input: dollars traded estimate, labelled as an estimate
    for r in rows:
        r["dollars"] = COLLECT.dollars_traded(r["m"])

    # 3. order-book depth for EVERY in-scope market, in chunks of 100 (the documented
    #    maximum per request). Depth is a safety gate, so it is not fair to apply it only
    #    to the biggest names and leave the rest unscored.
    rows.sort(key=lambda r: -(r["dollars"] or 0))
    books = books_for([r["m"]["ticker"] for r in rows],
                      "order book depth from GET /markets/orderbooks (bids only; a NO bid at Y is a YES ask at 1-Y)")
    print(f"  order books: {len(books)}")

    # 4. score with the shared model
    hist = load_history(LIVE / "price_history.json")
    look = model["parameters"].get("lookback_minutes", 30)
    scored = []
    scoring_errors = []
    for r in rows:
        m = r["m"]
        series = (hist.get(m["ticker"]) or {}).get("observations") or []
        mom = momentum_from(series, look, now_ms)
        try:
            sc = RM.score(m, model, books.get(m["ticker"]), {"now_ms": now_ms, "momentum_dollars": mom, "series_ticker": r["series"]})
        except Exception as e:  # noqa: BLE001
            # One malformed market must never discard the whole scan. The failure is counted
            # and named rather than swallowed; the market simply does not appear in the feeds.
            scoring_errors.append({"ticker": m.get("ticker"), "error": f"{type(e).__name__}: {e}"})
            continue
        sc.update({"title": m.get("title") or m.get("yes_sub_title") or "", "category_id": r["cid"],
                   "category_basis": r["basis"], "close_time": m.get("close_time"),
                   "event_ticker": m.get("event_ticker"), "status": m.get("status"),
                   "result": m.get("result") or None,
                   "volume_fp": RM.num(m.get("volume_fp")), "volume_24h_fp": RM.num(m.get("volume_24h_fp")),
                   "open_interest_fp": RM.num(m.get("open_interest_fp")),
                   "dollars_traded_estimate": r["dollars"],
                   "catalysts": RM.catalyst_links(m),
                   "book": books.get(m["ticker"]) and {k: v for k, v in books[m["ticker"]].items() if k.endswith(("at_bid", "at_ask", "price"))} or None,
                   "source": f"{BASE}/markets/{m['ticker']}"})
        scored.append(sc)

    eligible = [s for s in scored if s["eligible"]]
    eligible.sort(key=lambda s: -(s["score"] or -9e9))
    picks = eligible[: model["scoring"]["top_k"]]
    print(f"  eligible: {len(eligible)}  picks: {len(picks)}")
    if scoring_errors:
        print(f"  ! {len(scoring_errors)} market(s) could not be scored and were left out of the feeds: "
              + ", ".join(f"{e['ticker']} ({e['error']})" for e in scoring_errors[:5]), file=sys.stderr)

    # The screen is strict on purpose, so the empty case must still be useful: show what
    # came closest and exactly which gate stopped it, instead of pretending there are picks.
    near = [s for s in scored if not s["eligible"] and s.get("score") is not None]
    near.sort(key=lambda s: (len(s.get("fails") or []), -(s["score"] or -9e9)))
    near_misses = near[:8]
    # Rows the model cannot even price (no two-sided quote, no last) are listed separately
    # with their reason, so "nothing to show" is never mistaken for "nothing happened".
    unscoreable = [s for s in scored if not s["eligible"] and s.get("score") is None][:8]

    # 5. swings >= threshold across the retained observation history
    thr = model["swing_alert"]["threshold_dollars"]
    alerts = []
    for ticker, s in hist.items():
        obs = s.get("observations") or []
        for a in RM.detect_swings(obs, thr):
            row = next((x for x in scored if x["ticker"] == ticker), None)
            if row is None:
                continue
            a.update({"ticker": ticker, "title": row["title"], "category_id": row["category_id"],
                      "category_basis": row["category_basis"], "close_time": row["close_time"],
                      "source": row["source"], "catalysts": row["catalysts"],
                      "in_picks": any(p["ticker"] == ticker for p in picks),
                      "origin": "committed snapshot observation"})
            alerts.append(a)
    alerts.sort(key=lambda a: a["t"], reverse=True)
    alerts = alerts[:120]
    print(f"  swings >= ${thr:.2f}: {len(alerts)}")

    # 6. out-of-sample validation on markets that have already settled
    settled = paged_markets({"status": "settled"}, cap=1500)
    # Same truncation risk as the open scan: query the confirmed seed series explicitly
    # so the out-of-sample replay covers settled markets of the five topics rather than
    # only whatever the paged window happened to reach.
    seeded_settled: dict[str, dict] = {}
    for c in cats["categories"]:
        for seed in c.get("seed_series", []):
            try:
                d, _ = get("/markets", {"series_ticker": seed["ticker"], "status": "settled", "limit": 1000})
            except RuntimeError as e:
                print(f"  ! seed {seed['ticker']} (settled): {e}", file=sys.stderr)
                continue
            for m in d.get("markets") or []:
                if m.get("ticker"):
                    seeded_settled[m["ticker"]] = m
    have_s = {m.get("ticker") for m in settled}
    settled.extend(seeded_settled[t] for t in seeded_settled if t not in have_s)
    settled.sort(key=lambda m: m.get("settlement_ts") or "", reverse=True)
    validation = replay_settled(model, [m for m in settled if _maybe_in_scope(cats, series_idx, m)], validate_n) \
        if validate_n else {"skipped": {"--validate": "0"}}
    print(f"  validation: {validation.get('markets_tested', 0)} markets, {validation.get('signals', 0)} signals, hit rate {validation.get('hit_rate')}")

    cutoff = None
    try:
        cutoff, _ = get("/historical/cutoff")
    except RuntimeError as e:
        print(f"  ! /historical/cutoff unavailable ({e})", file=sys.stderr)

    payload = {
        "schema": 1,
        "kind": "live-desk scan (ROI picks + swing alerts + validation)",
        "environment": "demo",
        "base_url": BASE,
        "collected_at": now,
        "runtime_seconds": round(time.time() - started, 1),
        "model": {
            "id": model["id"], "file": "data/roi_model.json",
            "sha256": hashlib.sha256((ROOT / "data" / "roi_model.json").read_bytes()).hexdigest()[:16],
            "swing_threshold_dollars": thr,
            "browser_mirror": "assets/live.js (parity enforced by scripts/tests/test_roi_parity.py)",
        },
        "sources": {
            "markets": "https://docs.kalshi.com/api-reference/market/get-markets",
            "orderbooks": "https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks",
            "orderbook_semantics": "https://docs.kalshi.com/getting_started/orderbook_responses",
            "candlesticks": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
            "fees": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
            "settlement": "https://docs.kalshi.com/getting_started/market_settlement",
            "historical_partition": "https://docs.kalshi.com/getting_started/historical_data",
            "demo_environment": "https://docs.kalshi.com/getting_started/demo_env",
        },
        "counts": {
            "open_scanned": len(open_ms),
            "open_in_scope": len(rows),
            "eligible": len(eligible),
            "picks": len(picks),
            "near_misses": len(near_misses),
            "unscoreable": sum(1 for s in scored if not s["eligible"] and s.get("score") is None),
            "orderbooks": len(books),
            "alerts": len(alerts),
            "markets_with_momentum": sum(1 for s in scored if s.get("momentum") is not None),
            "markets_with_catalyst_url": sum(1 for s in scored if s.get("catalysts")),
            "scoring_errors": len(scoring_errors),
        },
        "scoring_errors": scoring_errors[:50],
        "historical_cutoff": cutoff,
        "picks": picks,
        "near_misses": near_misses,
        "unscoreable": unscoreable,
        "alerts": alerts,
        "validation": validation,
        "disclaimers": [
            "Demo environment with mock funds. Kalshi states demo prices and behaviour may not reflect real markets: https://docs.kalshi.com/getting_started/demo_env",
            "A 'pick' is a modelled edge after the documented taker fee, not a forecast and not advice. The model reads the current book, so if the book is already correct the edge is an artefact of the blended quote.",
            "dollars_traded_estimate = volume_fp x last_price_dollars, computed by this project; Kalshi has no 'dollars traded' field (notional_value_dollars is the value of one contract at settlement).",
            "momentum is null when this project's own observation history is too sparse to measure it; it is never replaced by a guess.",
            "catalysts are URLs copied out of the market's own official record (rules/subtitle text). They are labelled 'the source this market settles on' and never as the cause of a move.",
            "the validation replay uses a reduced feature set (a 1-minute candle cannot carry book depth or 24h volume), so it measures a weaker version of the screen.",
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=1))
    try:
        shown = out_path.relative_to(ROOT)
    except ValueError:
        shown = out_path
    print(f"  wrote {shown} ({len(picks)} picks, {len(near_misses)} near misses, {len(alerts)} alerts)")
    return payload


def _maybe_in_scope(cats, series_idx, m) -> bool:
    st = COLLECT.series_of(m)
    s = series_idx.get(st, {})
    cid, _ = COLLECT.classify(cats, st, s.get("title"),
                              " ".join(s.get("categories") or []) if s.get("categories") else s.get("category"),
                              m.get("title") or m.get("yes_sub_title"))
    return bool(cid)


def main() -> int:
    ap = argparse.ArgumentParser(description="Live-desk ROI + swing scan for the Kalshi demo API")
    ap.add_argument("--validate", type=int, default=24, help="settled markets to replay (0 disables)")
    ap.add_argument("--out", default=str(LIVE / "roi.json"))
    args = ap.parse_args()
    try:
        build(validate_n=args.validate, out_path=Path(args.out))
    except RuntimeError as e:
        print(f"SCAN_FAILED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
