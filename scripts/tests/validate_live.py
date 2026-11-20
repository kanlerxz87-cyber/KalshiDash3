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


def check_event_refs() -> None:
    """Official event references: only what the API returned may be published.

    Runs only when data/live/event_refs.json exists. A settlement source is a
    place to look, never a proven cause, so nothing here may claim otherwise.
    """
    path = LIVE / "event_refs.json"
    if not path.exists():
        return
    doc = json.loads(path.read_text())
    check(doc.get("schema") == 1, "event_refs.json schema must be 1")
    check(bool(doc.get("generated_at")), "event_refs.json generated_at missing")
    check(bool(doc.get("disclaimers")), "event_refs.json disclaimers missing")
    events = doc.get("events")
    check(isinstance(events, list), "event_refs.json events must be a list")
    for ev in events or []:
        tag = f"event_refs:{ev.get('event_ticker')}"
        check(bool(ev.get("event_ticker")), f"{tag} missing event_ticker")
        check(ev.get("status") in ("ok", "unavailable"), f"{tag} bad status {ev.get('status')!r}")
        check(str(ev.get("source", "")).startswith("https://"), f"{tag} source must be an https URL")
        for s in ev.get("settlement_sources") or []:
            check(bool(s.get("name")), f"{tag} settlement source without a name")
            check(str(s.get("url", "")).startswith("https://"), f"{tag} settlement source must be an https URL")
        # A public page link is only published when the request for it worked.
        if ev.get("kalshi_public_url"):
            check(
                ev.get("kalshi_public_http_status") == 200,
                f"{tag} publishes a public Kalshi link that was not verified with HTTP 200",
            )


def check_alert_causes() -> None:
    """Alert cause fields: official candidates only, always labelled unverified.

    Runs on the archive and on the rendered feed. This is the guard against
    the failure mode the whole feature is about: a cause that cannot be
    checked, or a "verified cause" claim that the API never supports.
    """
    refs: dict[str, dict] = {}
    refs_path = LIVE / "event_refs.json"
    if refs_path.exists():
        for ev in json.loads(refs_path.read_text()).get("events") or []:
            if ev.get("event_ticker"):
                refs[ev["event_ticker"]] = ev

    sources = []
    archive_path = LIVE / "alerts_archive.json"
    if archive_path.exists():
        sources.append(("archive", json.loads(archive_path.read_text()).get("alerts") or []))
    feed_path = LIVE / "alerts.json"
    if feed_path.exists():
        sources.append(("feed", json.loads(feed_path.read_text()).get("all_events") or []))

    for where, alerts in sources:
        for a in alerts:
            tag = f"{where}:{a.get('ticker')}@{a.get('to_time')}"
            status = str(a.get("cause_status") or "")
            check("unverified" in status.lower(), f"{tag} cause_status does not say the cause is unverified")
            link = a.get("cause_link")
            if link:
                check(
                    str(link).startswith("https://external-api.demo.kalshi.co/trade-api/v2/events/"),
                    f"{tag} cause_link is not an official Kalshi event record URL",
                )
            cands = a.get("cause_candidates") or []
            check(isinstance(cands, list), f"{tag} cause_candidates must be a list")
            official = {
                (s.get("name"), s.get("url"))
                for s in (refs.get(a.get("event_ticker"), {}).get("settlement_sources") or [])
            }
            official_urls = {u for _, u in official}
            for c in cands:
                check(bool(c.get("url")), f"{tag} cause candidate without a URL")
                check(
                    str(c.get("url", "")).startswith("https://"),
                    f"{tag} cause candidate must be an https URL",
                )
                if refs:
                    check(
                        c.get("url") in official_urls,
                        f"{tag} cause candidate is not an official settlement source of its event",
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

    for bucket in ("open_markets", "settled_markets"):
        rows = doc.get(bucket)
        check(isinstance(rows, list), f"{bucket} must be a list")
        for r in rows or []:
            tag = f"{bucket}:{r.get('ticker')}"
            missing = REQUIRED_ROW_KEYS - set(r)
            check(not missing, f"{tag} missing keys {sorted(missing)}")
            check(r.get("category_id") in CATEGORY_IDS, f"{tag} bad category_id {r.get('category_id')!r}")
            check(r.get("category_basis") in ("seed", "keyword"), f"{tag} bad category_basis")
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

    check_simulation()
    check_event_refs()
    check_alert_causes()

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
