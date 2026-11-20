#!/usr/bin/env python3
"""Append the facts verified in the 2026-11-20 official-source re-audit.

Every row below was checked against the linked official page on the date in
`checked_on`. Nothing is inferred: each `value` is either quoted from the page
or is a value this project measured against the official demo API, with the
query recorded.

Run: python3 scripts/add_verified_facts.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "data" / "verified_facts.json"

NEW = [
    {
        "id": "F-55",
        "claim": "GET /markets/orderbooks takes `tickers` as an array of 1-100 ticker strings, repeated as separate query parameters",
        "value": "tickers is a required string[] of 1-100 items; the request form is ?tickers=A&tickers=B",
        "source": "https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks",
        "verified": True,
        "checked_on": "2026-11-20",
        "how": "Read the endpoint reference: the `tickers` parameter is typed string[] and the example repeats the parameter name once per ticker.",
        "note": "Measured against the live demo API on 2026-11-20: ?tickers=A&tickers=B returned two separate populated books; ?tickers=A,B returned ONE book keyed by the literal string \"A,B\" with empty arrays (HTTP 400 for some pairs). The comma-joined form silently loses every depth value, so this project sends the array as repeated parameters in scripts/roi_scan.py and assets/live.js.",
    },
    {
        "id": "F-56",
        "claim": "Kalshi publishes one web page per series at https://kalshi.com/markets/<series-ticker-lowercase>, and that page carries Kalshi's own news digest for the series",
        "value": "https://kalshi.com/markets/kxaaagasm, /kxaaagasd, /kxballondor, /kxelectiran, /kxethy, /kxpgatour and /kxbtcy all resolve to a live series page; several show an 'AI Digest' with its own linked sources",
        "source": "https://kalshi.com/markets/kxethy",
        "verified": True,
        "checked_on": "2026-11-20",
        "how": "Fetched each series page and read the title and the AI Digest block. kalshi.com/markets/kxdemofuthourly does NOT resolve (it is a demo-only series with no production page).",
        "note": "This is the only official per-series lead Kalshi publishes, so it is what every >= $0.10 swing row links to. It is a LEAD: the digest discusses the series, not this market's move. The page shows PRODUCTION prices while this dashboard's prices come from the DEMO environment.",
    },
    {
        "id": "F-57",
        "claim": "A market's rules_primary / rules_secondary / subtitle fields are the only place a source URL appears inside a market record",
        "value": "GET /markets has no news, url, cause or catalyst field of any kind",
        "source": "https://docs.kalshi.com/api-reference/market/get-markets",
        "verified": True,
        "checked_on": "2026-11-20",
        "how": "Read the documented Get Markets response schema field by field; no news or url field exists.",
        "note": "Basis for leaving cause_link null on every alert row and for the F-15 / F-25 flags. The market's own settlement rules (rules_primary) are the official statement of what the market settles on; they are shown, but they are not a cause of a price move.",
    },
    {
        "id": "F-58",
        "claim": "The July 7, 2026 fee schedule applies a per-series multiplier M to the general taker and maker formulas",
        "value": "general taker = round up(M x 0.07 x C x P x (1-P)); general maker = round up(M x 0.0175 x C x P x (1-P)); M = 1 for KXAAAGASM, KXPGATOUR, KXPGARYDER, KXPGASOLHEIM; M = 0 for KXELECTIRAN, KXBTCY, KXETHY",
        "source": "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
        "verified": True,
        "checked_on": "2026-11-20",
        "how": "Read the fee-schedule PDF: 'Last updated and effective: July 7, 2026', the general fee table, and the non-standard fee table listing the per-series multipliers.",
        "note": "scripts/tests/test_fees.py reproduces all 42 general-table numbers and checks the listed multipliers. Series absent from the table use M = 1 by default and are listed in F-20 for a human check against the PDF.",
    },
    {
        "id": "F-59",
        "claim": "The orderbook response carries BIDS ONLY; the implied ask is $1 minus the best NO bid",
        "value": "yes_dollars[] and no_dollars[] are the bid sides; each level is [price_dollars, count_fp]; prices ascend and the best bid is last",
        "source": "https://docs.kalshi.com/getting_started/orderbook_responses",
        "verified": True,
        "checked_on": "2026-11-20",
        "how": "Read the official order-book response guide.",
        "note": "The liquidity ladder on dashboard.html shows the bid side of the book and the implied ask derived from it, and says so.",
    },
    {
        "id": "F-60",
        "claim": "Candlestick history is available per market with an epoch-second start_ts/end_ts and a period_interval in seconds",
        "value": "period_interval accepts 60 (1 minute) up to 604800 (1 week); the response is paginated with a cursor",
        "source": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
        "verified": True,
        "checked_on": "2026-11-20",
        "how": "Read the endpoint reference and confirmed live against the demo API: a 1-minute request over a verified epoch range returned populated candles.",
        "note": "The dashboard's seconds/minutes/hours window selector chooses the shortest interval the API actually serves; it never interpolates a finer tick than Kalshi published.",
    },
    {
        "id": "F-61",
        "claim": "A GitHub Actions schedule event only fires when the workflow file exists on the DEFAULT branch, and scheduled runs always use the default branch",
        "value": "'This event will only trigger a workflow run if the workflow file exists on the default branch.' / 'Scheduled workflows will only run on the default branch.'",
        "source": "https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows",
        "verified": True,
        "checked_on": "2026-11-20",
        "how": "Read the official 'Events that trigger workflows' reference, schedule section.",
        "note": "Root cause of F-16: collect.yml's cron was present in the repository but the workflow only starts scheduling once the file is on main. Measured: the first `schedule`-event run of this repository was 2026-11-20T19:14:35Z on main (run 44800299801). The same page also states that scheduled runs can be delayed or dropped under high load, and that scheduled workflows are auto-disabled in a public repository after 60 days without activity.",
    },
    {
        "id": "F-62",
        "claim": "Scheduled workflows can be delayed and some queued runs dropped, so a schedule is best-effort and the site must not depend on it alone",
        "value": "'The schedule event can be delayed during periods of high loads of GitHub Actions workflow runs. High load times include the start of every hour. If the load is sufficiently high enough, some queued jobs may be dropped.'",
        "source": "https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows",
        "verified": True,
        "checked_on": "2026-11-20",
        "how": "Read the official reference, schedule section.",
        "note": "Basis for the browser-side live polling: the page reads the API directly when the browser can reach it, and falls back to the committed snapshot when it cannot.",
    },
]


def main() -> int:
    doc = json.loads(FACTS.read_text(encoding="utf-8"))
    facts = doc["facts"]
    have = {f["id"] for f in facts}
    added = 0
    for f in NEW:
        if f["id"] in have:
            continue
        facts.append(f)
        added += 1
    doc["facts"] = facts
    doc["generated"] = "2026-11-20 (official-source re-audit, session arena-0f71797f)"
    doc["counts"] = {
        "total": len(facts),
        "verified": sum(1 for f in facts if f.get("verified")),
        "unverified": sum(1 for f in facts if not f.get("verified")),
    }
    FACTS.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"added {added} fact(s); total {len(facts)} "
          f"({doc['counts']['verified']} verified, {doc['counts']['unverified']} unverified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
