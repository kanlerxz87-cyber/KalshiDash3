#!/usr/bin/env python3
"""Validate data/live/markets.json before it is committed or rendered.

This is a schema + honesty check, not a data check. It refuses a snapshot that
is missing its provenance, that silently coerces a result to yes/no, or that
claims an official field name for a value this project computed.

Run: python3 scripts/tests/validate_live.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "data" / "live"
ALLOWED_RESULTS = {None, "yes", "no", "scalar", ""}
CATEGORY_IDS = {"gas", "elections", "culture", "crypto", "golf"}
REQUIRED_ROW_KEYS = {
    "ticker", "title", "category_id", "category_basis", "status", "result",
    "last_price_dollars", "volume_fp", "dollars_traded_estimate", "source",
}

errors: list[str] = []


def load_seed_series() -> set[str]:
    path = ROOT / "data" / "categories.json"
    if not path.exists():
        return set()
    doc = json.loads(path.read_text())
    out = set()
    for c in doc.get("categories", []):
        for s in c.get("seed_series", []):
            out.add(str(s.get("ticker", "")).upper())
    return out


SEED_SERIES = load_seed_series()


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def check_by_category(tag: str, row: dict, pre_narrowing_elections: bool = False) -> None:
    # Kept independent of scripts/collect.py on purpose: the validator must be able to refuse a
    # snapshot produced by a broken collector, so it re-states the rule rather than importing it.
    compatible = {
        "gas": {"Economics", "Commodities", "Financials"},
        "elections": {"Elections", "Politics", "World", "International"} if pre_narrowing_elections else {"Elections"},
        "culture": {"Entertainment", "Culture", "Pop Culture", "Awards", "Media"},
        "crypto": {"Crypto", "Financials"},
        "golf": {"Sports", "Golf"},
    }
    official = [str(c) for c in (row.get("series_categories") or [])]
    cat = row.get("category_id")
    if not official or cat not in compatible:
        return
    if any(o in compatible[cat] for o in official):
        return
    errors.append(
        f"{tag} published under {cat} but its official series categories are {official} (F-65)"
    )


def check_simulation() -> None:
    """Simulation-only check. Runs only when data/live/simulation.json exists.

    Every paper position must (a) come from an archived alert, (b) use an entry
    price in 0.01-0.99 and the official taker fee for its series, and (c) have a
    realised result that recomputes from the stored result and entry.
    """
    path = LIVE / "simulation.json"
    if not path.exists():
        return
    doc = json.loads(path.read_text())
    check(doc.get("schema") == 1, "simulation.json schema must be 1")
    check("PAPER" in str(doc.get("mode", "")), "simulation must be labelled PAPER ONLY")
    check(bool(doc.get("disclaimers")), "simulation disclaimers missing")

    strat = json.loads((ROOT / "data" / "strategies.json").read_text())
    check(
        [x["id"] for x in doc.get("strategies") or []] == [x["id"] for x in strat["strategies"]],
        "simulation strategies must match data/strategies.json",
    )

    archive_path = LIVE / "alerts_archive.json"
    archive_keys = set()
    if archive_path.exists():
        for a in json.loads(archive_path.read_text()).get("alerts", []):
            archive_keys.add(f"{a['ticker']}@{a['from_time']}>{a['to_time']}")

    spec = importlib.util.spec_from_file_location("simulate", ROOT / "scripts" / "simulate.py")
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)

    for group in ("open_positions", "settled_positions"):
        for pos in doc.get(group) or []:
            tag = f"{group[:-1]} {pos.get('id')}"
            entry = float(pos["entry_price"])
            check(0.01 <= entry <= 0.99, f"{tag} entry outside 0.01-0.99")
            mult = int(pos["taker_multiplier"])
            check(
                abs(float(pos["entry_fee"]) - sim.taker_fee(entry, int(pos["contracts"]), mult)) < 1e-9,
                f"{tag} entry fee does not match the official taker formula",
            )
            check(pos.get("side") in ("yes", "no"), f"{tag} bad side")
            check(
                pos.get("alert_key") in archive_keys if archive_keys else False,
                f"{tag} alert_key is not in data/live/alerts_archive.json",
            )
            if pos.get("status") == "settled":
                payoff = 1.0 if pos.get("settled_result") == pos.get("side") else 0.0
                expect = round(payoff - entry - float(pos["entry_fee"]), 4)
                check(
                    abs(float(pos["realized_net"]) - expect) < 1e-9,
                    f"{tag} realized_net does not recompute",
                )
    for st in doc.get("strategies") or []:
        check(
            st.get("settled", 0) == st.get("wins", 0) + st.get("losses", 0),
            f"strategy {st.get('id')} win/loss does not add up to settled",
        )


def main() -> int:
    path = LIVE / "markets.json"
    if not path.exists():
        print("skip: no snapshot yet")
        return 0
    doc = json.loads(path.read_text())

    check(doc.get("schema") == 1, "schema must be 1")
    check(doc.get("environment") == "demo", "environment must be demo")
    check(bool(doc.get("collected_at")), "collected_at missing")
    check(isinstance(doc.get("sources"), dict) and doc["sources"], "sources block missing")
    check(bool(doc.get("disclaimers")), "disclaimers missing")

    ts = doc.get("collected_at", "")
    try:
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append(f"collected_at not ISO-8601 Z: {ts!r}")

    pre_narrowing = "Politics" in (((doc.get("counts") or {}).get("category_compatible_official") or {}).get("elections") or [])
    for bucket in ("open_markets", "settled_markets"):
        rows = doc.get(bucket)
        check(isinstance(rows, list), f"{bucket} must be a list")
        for r in rows or []:
            tag = f"{bucket}:{r.get('ticker')}"
            missing = REQUIRED_ROW_KEYS - set(r)
            check(not missing, f"{tag} missing keys {sorted(missing)}")
            check(r.get("category_id") in CATEGORY_IDS, f"{tag} bad category_id {r.get('category_id')!r}")
            check(r.get("category_basis") in ("seed", "keyword"), f"{tag} bad category_basis")
            # Category integrity (F-65): the official categories recorded on a row must not
            # contradict the topic the row is published under. The check is deliberately
            # one-directional: an absent list is unknown and passes.
            if "series_categories" in r:
                cats = r.get("series_categories")
                check(isinstance(cats, list), f"{tag} series_categories must be a list")
                check_by_category(tag, r, pre_narrowing_elections=pre_narrowing)
            # A market whose series is in the fee-schedule seed list must never be
            # demoted to "keyword": that would understate what is confirmed.
            seed_series = SEED_SERIES
            if r.get("series_ticker") in seed_series:
                check(
                    r.get("category_basis") == "seed",
                    f"{tag} series {r.get('series_ticker')} is a fee-schedule seed but basis="
                    f"{r.get('category_basis')!r}",
                )
            check(r.get("result") in ALLOWED_RESULTS, f"{tag} illegal result {r.get('result')!r}")
            if bucket == "open_markets":
                # A market that has finished must never be presented as open.
                check(
                    str(r.get("status")) not in ("finalized", "determined", "closed", "settled"),
                    f"{tag} is in open_markets with terminal status {r.get('status')!r}",
                )
            check(str(r.get("source", "")).startswith("https://"), f"{tag} source must be an https URL")
            # Never invent a price.
            check(
                r.get("last_price_dollars") is None or 0.0 <= float(r["last_price_dollars"]) <= 1.0,
                f"{tag} last price outside 0..1",
            )
            if r.get("dollars_traded_estimate") is not None:
                check(
                    float(r["dollars_traded_estimate"]) >= 0,
                    f"{tag} negative dollars_traded_estimate",
                )

    for liq in doc.get("liquidity") or []:
        ob = liq.get("orderbook") or {}
        if "error" in ob:
            # A failed orderbook fetch is allowed and must stay visible.
            continue
        check(str(ob.get("source", "")).startswith("https://"), f"{liq.get('ticker')} liquidity source")
        for side in ("yes_bids", "no_bids"):
            rows = ob.get(side) or []
            prices = [x["price"] for x in rows]
            check(prices == sorted(prices), f"{liq.get('ticker')} {side} not ascending")

    # Alert feed (written by scripts/build_alerts.py) and the CORS header probe.
    # alerts.json schema is the parallel sessions' build_alerts.py output:
    # all_events[] with from_price/to_price/delta/direction.
    alerts_path = LIVE / "alerts.json"
    if alerts_path.exists():
        adoc = json.loads(alerts_path.read_text())
        check(adoc.get("schema") == 1, "alerts.json schema must be 1")
        check(float(adoc.get("threshold_dollars") or 0) == 0.10, "alerts.json threshold_dollars must be 0.10")
        for a in adoc.get("all_events") or []:
            d = a.get("delta")
            if d is not None:
                check(abs(float(d)) >= 0.10 - 1e-9, f"alert {a.get('ticker')}@{a.get('to_time')} delta {d} is below the $0.10 requirement")
                check((float(d) > 0) == (a.get("direction") == "up"), f"alert {a.get('ticker')}@{a.get('to_time')} direction contradicts its delta")
            check(str(a.get("market_source", "")).startswith("https://"),
                  f"alert {a.get('ticker')}@{a.get('to_time')} market_source must be https")
            check(a.get("cause_link") is None, f"alert {a.get('ticker')} cause_link must stay null — causes are never invented (F-15)")
    cors_path = LIVE / "cors.json"
    if cors_path.exists():
        cdoc = json.loads(cors_path.read_text())
        check(bool(cdoc.get("checked_at")), "cors.json checked_at missing")
        check(str(cdoc.get("origin_tested", "")).startswith("https://"), "cors.json origin_tested must be https")
        check("access_control_allow_origin" in cdoc, "cors.json must record allow-origin (or null) — never assume it")
    check_simulation()

    if errors:
        print("INVALID live snapshot:", file=sys.stderr)
        for e in errors[:40]:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(doc.get('open_markets') or [])} open, "
        f"{len(doc.get('settled_markets') or [])} settled, "
        f"{len(doc.get('liquidity') or [])} orderbooks, collected_at={ts}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
