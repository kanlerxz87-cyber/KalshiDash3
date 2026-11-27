"""Follow archived swings and outstanding paper positions beyond the ranked market lists.

Only Kalshi's own status/result are recorded. A final verified result is reusable because
`finalized` is terminal. Nonterminal outcomes are refreshed; a failed or deferred lookup
leaves the values null. See https://docs.kalshi.com/getting_started/market_lifecycle and
https://docs.kalshi.com/getting_started/historical_data.
"""
from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import quote

from build_alerts import CATEGORY_COMPATIBLE, NEVER_IN_SCOPE, series_of_ticker

# https://docs.kalshi.com/getting_started/demo_env (no production/trading credentials).
DEMO_BASES = ("https://external-api.demo.kalshi.co/trade-api/v2", "https://demo-api.kalshi.co/trade-api/v2")

# A separate budget for optional market lookups. Both the live and historical request count.
MAX_REQUESTS = 16
STATUSES = {"initialized", "active", "inactive", "closed", "determined", "disputed", "amended", "finalized"}
RESULTS = ("yes", "no", "scalar")


def market_paths(ticker: str) -> tuple[str, str]:
    path = "/markets/" + quote(ticker, safe="")
    return path, "/historical" + path


def terminal(row: dict) -> bool:
    return row.get("status") in ("finalized", "settled") and row.get("result") in RESULTS


def track(markets: dict, alerts: list, paper_positions: list, previous: dict, get, now,
          *, limit: int = MAX_REQUESTS) -> dict:
    """Build the sidecar inside markets.json. Inject the collector's GET and clock for tests."""
    base = markets["base_url"]
    if base not in DEMO_BASES:
        raise ValueError("alert lifecycle collection needs a documented demo base URL")
    existing = {r["ticker"]: r for r in markets["open_markets"] + markets["settled_markets"]}
    prior = {r["ticker"]: r for r in previous.get("rows") or []}
    ledger = markets.get("series_index") or {}
    targets = set()
    # Build candidates independently of the rank cap; Test/Demo or contradicted topics are not tracked.
    alerted = {a.get("ticker") for a in alerts}
    for a in alerts + [p for p in paper_positions if p.get("ticker") not in alerted]:
        ticker, topic = a.get("ticker"), a.get("category_id")
        if not ticker or topic not in CATEGORY_COMPATIBLE:
            continue
        ranked = existing.get(ticker) or {}
        series = ranked.get("series_ticker") or series_of_ticker(ticker)
        cats = ranked.get("series_categories") or (ledger.get(series) or {}).get("categories")
        if not cats and a.get("series_categories_source") in {f"{b}/series/{series}" for b in DEMO_BASES}:
            cats = a.get("series_categories")
        cats = set(cats or [])
        if cats & NEVER_IN_SCOPE or (cats and not cats & CATEGORY_COMPATIBLE[topic]):
            continue
        targets.add(ticker)

    rows = []
    used = 0
    stop = False
    # Unattempted, then least-recently attempted tickers. A missing record cannot starve the tail.
    for ticker in sorted(targets, key=lambda t: ((prior.get(t) or {}).get("attempted_at") or "", t)):
        live_path, historical_path = market_paths(ticker)
        old = prior.get(ticker) or {}
        record = {
            "ticker": ticker, "source": base + live_path, "status": None, "result": None,
            "settlement_ts": None, "settlement_value_dollars": None, "observed_at": None,
            "attempted_at": old.get("attempted_at"), "reason": "lookup deferred",
        }

        def copy_from(market, source, observed_at):
            status, result = market.get("status"), market.get("result")
            if (market.get("ticker") != ticker or not isinstance(status, str) or status not in STATUSES or
                    result not in (*RESULTS, None, "") or source not in (base + live_path, base + historical_path) or
                    not observed_at):
                return False
            record.update(source=source, status=status, result=result or None,
                          settlement_ts=market.get("settlement_ts"),
                          settlement_value_dollars=market.get("settlement_value_dollars"),
                          observed_at=observed_at, reason=None)
            return True

        current = existing.get(ticker) or {}
        if copy_from(current, current.get("source"), markets.get("collected_at")):
            pass
        elif terminal(old) and copy_from(old, old.get("source"), old.get("observed_at")):
            # Keep the original observation time and link; this isn't a new exchange read.
            pass
        elif not stop and used < limit:
            paths = (historical_path,) if old.get("reason") == "historical lookup deferred" else (live_path, historical_path)
            for path in paths:
                if used >= limit:
                    record["reason"] = "historical lookup deferred"
                    break
                used += 1
                record.update(source=base + path, attempted_at=now(), reason="response not verified")
                try:
                    doc, source = get(path, retries=1)
                except RuntimeError as error:
                    cause = error.__cause__
                    if isinstance(cause, HTTPError) and cause.code == 404:
                        record["reason"] = "market did not resolve at this endpoint"
                        continue  # only a live 404 justifies trying the historical partition
                    record["reason"] = "lookup unavailable"
                    stop = True  # avoid amplifying an exchange outage or its rate limit
                    break
                if isinstance(doc, dict) and isinstance(doc.get("market"), dict):
                    copy_from(doc["market"], source, now())
                break
        rows.append(record)

    return {"schema": 1, "rows": sorted(rows, key=lambda r: r["ticker"]), "lookup_requests": used}
