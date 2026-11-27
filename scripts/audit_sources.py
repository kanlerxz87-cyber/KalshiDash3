#!/usr/bin/env python3
"""Offline citation-integrity audit, NOT live value verification.

Require exact official demo origins and ticker-matched endpoint paths on public
market rows. HTTPS alone (or a substring containing 'demo') is not provenance.
Sources for allowed hosts and routes:
  https://docs.kalshi.com/getting_started/demo_env
  https://docs.kalshi.com/api-reference/market/get-market
  https://docs.kalshi.com/api-reference/market/get-market-orderbook
  https://docs.kalshi.com/api-reference/market/get-series

No network, orders, credentials, or file writes. Success certifies link structure
only, not URL availability, data freshness, quoted values, or a causal claim.
Run: python3 scripts/audit_sources.py [--root PATH] [--json]
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEMO_HOSTS = frozenset({"external-api.demo.kalshi.co", "demo-api.kalshi.co"})
CLAIM_HOSTS = frozenset({"docs.kalshi.com", "kalshi.com", "help.kalshi.com",
                         "docs.github.com", "github.com"})
TICKER = re.compile(r"[A-Za-z0-9_.-]+\Z")


def safe_url(value: object):
    """Reject userinfo, ports, control characters and ambiguous URL spellings."""
    if not isinstance(value, str) or not value or re.search(r"[\s\\]", value):
        return None
    try:
        u = urlsplit(value)
        if (u.scheme != "https" or u.username is not None or u.password is not None
                or u.port is not None or not u.hostname or u.netloc != u.hostname):
            return None
        return u
    except ValueError:
        return None


def demo_source(value: object, ticker: object, kind: str = "market") -> bool:
    """A canonical demo source must identify this exact ticker, not another row."""
    u = safe_url(value)
    if u is None or u.hostname not in DEMO_HOSTS or u.fragment:
        return False
    if not isinstance(ticker, str) or not TICKER.fullmatch(ticker):
        return False
    paths = {
        "market": f"/trade-api/v2/markets/{ticker}",
        "series": f"/trade-api/v2/series/{ticker}",
        "orderbook": f"/trade-api/v2/markets/{ticker}/orderbook",
    }
    if kind not in paths or u.path != paths[kind]:
        return False
    if kind != "orderbook":
        return not u.query
    if not u.query:
        return True
    # Current collector requests depth=10. Permit documented non-negative depth,
    # but never an unrelated query, duplicate parameter or embedded redirect.
    query = parse_qsl(u.query, keep_blank_values=True)
    return (len(query) == 1 and query[0][0] == "depth"
            and bool(re.fullmatch(r"[0-9]+", query[0][1])))


def claim_source(value: object) -> bool:
    u = safe_url(value)
    if u is None:
        return False
    if u.hostname in DEMO_HOSTS:
        return u.path.startswith("/trade-api/v2/")
    if u.hostname not in CLAIM_HOSTS:
        return False
    if u.hostname == "github.com":
        # GitHub hosts arbitrary user content; only this project's requirement
        # ledger qualifies here. This is project evidence, not a Kalshi claim.
        return u.path.startswith("/kanlerxz87-cyber/KalshiDash3/")
    return True


def audit(root: Path = ROOT) -> dict:
    errors: list[str] = []
    counts: Counter = Counter()

    def load(name: str) -> dict:
        try:
            doc = json.loads((root / name).read_text())
            if not isinstance(doc, dict):
                raise ValueError("expected JSON object")
            return doc
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
            return {}

    def rows(doc: dict, key: str, label: str) -> list:
        value = doc.get(key)
        if not isinstance(value, list):
            errors.append(f"{label}.{key}: required row list missing or invalid")
            return []
        return value

    def check_row(row: object, label: str, source: str = "source",
                  kind: str = "market", ticker: str | None = None) -> None:
        counts[label] += 1
        if not isinstance(row, dict) or not demo_source(
                row.get(source), ticker if ticker is not None else row.get("ticker"), kind):
            errors.append(f"{label}[{counts[label] - 1}]: {source} must be an exact official demo {kind} URL matching its ticker")

    for filename, groups, source in (
        ("markets", ("open_markets", "settled_markets"), "source"),
        ("alerts", ("all_events", "high_roi"), "market_source"),
        ("alerts_archive", ("alerts",), "market_source"),
        ("roi", ("picks", "near_misses", "unscoreable", "alerts"), "source"),
        ("simulation", ("open_positions", "settled_positions"), "source"),
        ("catalysts", ("alerts",), "market_source"),
    ):
        label = f"data/live/{filename}.json"
        doc = load(label)
        for group in groups:
            for row in rows(doc, group, label):
                check_row(row, f"{filename}.{group}", source)
                if filename == "catalysts" and isinstance(row, dict):
                    check_row(row, "catalysts.settlement_references", "settlement_reference_source")
        if filename in {"markets", "roi", "simulation"}:
            if doc.get("environment") != "demo":
                errors.append(f"{label}: environment must be demo")
            base = doc.get("endpoint" if filename == "simulation" else "base_url")
            if base not in {f"https://{h}/trade-api/v2" for h in DEMO_HOSTS}:
                errors.append(f"{label}: base must be an exact official demo REST root")
        if filename == "markets":
            ledger = doc.get("series_index")
            if not isinstance(ledger, dict):
                errors.append(f"{label}.series_index: required object missing or invalid")
            else:
                for ticker, row in ledger.items():
                    check_row(row, "markets.series_index", kind="series", ticker=ticker)
            for row in rows(doc, "liquidity", label):
                if not isinstance(row, dict):
                    errors.append(f"{label}.liquidity: invalid row")
                    continue
                check_row(row.get("orderbook"), "markets.liquidity", kind="orderbook", ticker=row.get("ticker"))

    facts = load("data/verified_facts.json")
    for row in rows(facts, "facts", "data/verified_facts.json"):
        counts["facts"] += 1
        if not isinstance(row, dict):
            errors.append("facts: invalid row")
            continue
        tag = row.get("id", "unknown")
        if not claim_source(row.get("source")):
            errors.append(f"facts.{tag}: missing or non-allowlisted official/project citation")
        if not isinstance(row.get("verified"), bool):
            errors.append(f"facts.{tag}: verified must be explicitly true or false")
        elif not row["verified"]:
            counts["unverified_facts"] += 1
            if row.get("value") not in (None, ""):
                errors.append(f"facts.{tag}: unverified value must remain blank")
            if not (row.get("flag") or row.get("note")):
                errors.append(f"facts.{tag}: unverified row needs an explanation")

    return {
        "scope": "offline citation integrity only; NOT verification of values, freshness, availability, causality or ROI",
        "counts": dict(sorted(counts.items())),
        "errors": errors,
        "passed": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.root)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for label, count in result["counts"].items():
            print(f"{label}: {count}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        print(("PASS: " if result["passed"] else "FAIL: ") + result["scope"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
