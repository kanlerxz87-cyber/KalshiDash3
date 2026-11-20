#!/usr/bin/env python3
"""Validate data/live/markets.json before it is committed or rendered.

This is a schema + honesty check, not a data check. It refuses a snapshot that
is missing its provenance, that silently coerces a result to yes/no, or that
claims an official field name for a value this project computed.

Run: python3 scripts/tests/validate_live.py
"""
from __future__ import annotations

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
