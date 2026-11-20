#!/usr/bin/env python3
"""Update data/findings.json with what the 2026-11-20 official-source re-audit found.

Only flags/questions/suggestions that this session re-checked against a named
official source are touched; everything else in the file is left exactly as the
earlier sessions wrote it.

Run: python3 scripts/update_findings.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINDINGS = ROOT / "data" / "findings.json"

UPDATES = {
    "F-15": {
        "item": "Causes of sharp price jumps are still not collected — Kalshi's API has no news or cause field",
        "why": "The brief asks for website links that may have caused a move of at least $0.10. The official Get Markets schema (read again 2026-11-20) has no news, url, cause or catalyst field, and no official source maps a price move to an event. Every alert therefore still carries cause_link = null and is labelled 'unverified'. Linking a news site and calling it the cause would be fabrication.",
        "action": "Left blank by design, and the blank is now visible on every row. What was added instead is the two links that ARE official and checkable: the market's own API record, and Kalshi's own series page, which carries Kalshi's own AI Digest for that series (verified for KXAAAGASM, KXAAAGASD, KXBALLONDOR, KXELECTIRAN, KXETHY, KXPGATOUR and KXBTCY on 2026-11-20). Those are labelled 'leads', never causes.",
        "severity": "medium",
        "sources": [
            "https://docs.kalshi.com/api-reference/market/get-markets",
            "https://kalshi.com/markets/kxethy",
        ],
    },
    "F-16": {
        "item": "Scheduled collection: the cron only takes effect once the workflow file is on the default branch",
        "why": "Earlier checks saw 0 `schedule` events across every run of this repository and concluded that scheduling was broken. Re-checked on 2026-11-20: the schedule DID fire. Run 44800299801 was created with event=`schedule` at 2026-11-20T19:14:35Z on `main`, hours after the repository's last manual dispatch. The official reference states the rule directly: 'This event will only trigger a workflow run if the workflow file exists on the default branch' and 'Scheduled workflows will only run on the default branch'. collect.yml only reached main when the integration PR merged, so no earlier cron could fire. The same reference also warns that scheduled runs can be delayed or dropped under load, and that public repositories auto-disable schedules after 60 days without activity.",
        "action": "collect.yml and desk.yml are on main with their cron schedules, and a scheduled run has now been observed end to end. The site no longer depends on the schedule alone: every page also polls the demo API directly from the browser when the browser can reach it (CORS was measured, not assumed - see data/live/cors.json), and the freshness strip always says whether the number on screen came from the live API or from the committed snapshot.",
        "severity": "medium",
        "sources": [
            "https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows",
            "https://docs.kalshi.com/api-reference/market/get-markets",
        ],
    },
    "F-25": {
        "item": "Alert 'possible-cause' links were generic news-search links; they are now the market's own records",
        "why": "An earlier build pointed every swing at a Google/Bing/DuckDuckGo news search for the market title. That is a link to a search engine, not to a source, and it cannot be checked row by row. Re-checked on 2026-11-20 against the official Get Markets schema: the API carries no news field at all, and the only official per-series publication is Kalshi's own series page, which carries Kalshi's own AI Digest with linked sources.",
        "action": "Replaced. Each >= $0.10 row now links (a) the official demo API record for that exact ticker and (b) Kalshi's own page for that series. Both are labelled as leads; no causal claim is rendered anywhere, and cause_link remains null. A demo-only series with no production page (KXDEMOFUTHOURLY) gets the API link only - the link is not fabricated.",
        "severity": "low",
        "sources": [
            "https://docs.kalshi.com/api-reference/market/get-markets",
            "https://docs.kalshi.com/getting_started/quick_start_market_data",
            "https://kalshi.com/markets/kxpgatour",
        ],
    },
    "F-30": {
        "item": "The demo environment's per-market order-book depth was silently empty because of a malformed request",
        "why": "The multiple-order-book endpoint takes `tickers` as an ARRAY. This project sent it as one comma-joined string. Measured live on 2026-11-20: the comma form returns a single book keyed by the literal string \"A,B\" with empty price arrays (HTTP 400 for some pairs), while the repeated form ?tickers=A&tickers=B returns two separate populated books. Every liquidity ladder, every ROI depth figure and every near-miss score was therefore reading zero depth, and the ROI screen classified liquid markets as illiquid.",
        "action": "Fixed in scripts/roi_scan.py and assets/live.js (repeated query parameters). The browser/CI parity test now includes a case that asserts the repeated form is used and that a comma-joined request is rejected. A fresh scan afterwards reported 214 order books collected for 214 in-scope markets.",
        "severity": "high",
        "sources": [
            "https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks",
            "https://docs.kalshi.com/getting_started/orderbook_responses",
        ],
    },
    "F-31": {
        "item": "The desk scan produced no eligible pick, so the ROI validation measures nothing yet",
        "why": "After the order-book fix the desk scan runs cleanly (run 44800733375, 46s, 214 order books) but reports 0 eligible picks, 0 alerts and 2 near misses: KXGRAMMYNOMROTY-QA7CECC5-QA (unknown spread, depth 10, net ROI -3.38%) and KXDEMOFUTHOURLY-26NOV20H20-UP (98c spread, YES entry 99c, net ROI -36.11%). With no signals the out-of-sample validation reports 0 signals, 0 hits, 0 misses and no hit rate. That is an honest empty result, not a working model.",
        "action": "Published as-is with the numbers visible on roi.html and live.html. The eligibility rules are not relaxed to manufacture picks: a 98-cent spread and a 99-cent entry are not tradeable, and the near misses are shown with the reason each was rejected. The model needs more qualifying markets (and, for a real hit rate, settlement results) before its output means anything.",
        "severity": "medium",
        "sources": [
            "https://docs.kalshi.com/getting_started/orderbook_responses",
            "https://kalshi.com/docs/kalshi-fee-schedule.pdf",
        ],
    },
    "F-32": {
        "item": "Kalshi's series pages show PRODUCTION prices while this dashboard shows DEMO prices",
        "why": "The new series links point at kalshi.com, the production site; every price on this dashboard comes from external-api.demo.kalshi.co, the demo environment. The official demo-environment page states the demo has mock funds, is isolated from production, and that demo prices may differ from real markets. A reader who follows a series link and compares numbers will see different values, and could reasonably think one of them is wrong.",
        "action": "Every series link carries a title and a label saying it is Kalshi's own page for the series and that it carries Kalshi's news digest, and the footer and every page banner state that this site's values are demo-environment values. The two are never presented as the same number.",
        "severity": "medium",
        "sources": [
            "https://docs.kalshi.com/getting_started/demo_env",
            "https://docs.kalshi.com/api-reference/market/get-markets",
        ],
    },
}

NEW_QUESTIONS = [
    {
        "id": "Q10",
        "question": "Should a swing row ever name a cause, and if so, what would count as an acceptable source?",
        "known": "Kalshi publishes one official per-series page carrying an 'AI Digest' with its own linked sources (verified 2026-11-20 for the gas, culture, elections, crypto and golf series in scope). The digest discusses the series, not the specific market's move, and it is written for the production site.",
        "unknown": "Whether a digest that describes the series is close enough to 'why this market moved' to be shown on the same row as the move. The brief forbids asserting unsupported causality, so this session shows it as a lead and labels it as one.",
        "answer_if_forced": "Show the series page as a lead, never as a cause; keep cause_link null until a source that names the specific market and the specific time exists.",
        "decision_needed": "Confirm whether the AI Digest link is the right granularity of lead, or whether a narrower source is wanted.",
        "sources": [
            "https://kalshi.com/markets/kxethy",
            "https://docs.kalshi.com/api-reference/market/get-markets",
        ],
    },
]

NEW_SUGGESTIONS = [
    {
        "id": "G19",
        "suggestion": "Let the desk scan keep its near misses, and turn them into a watch list rather than dropping them.",
        "why_it_helps_decisions": "Right now the desk scan reports 0 eligible picks and 2 near misses. The near misses are the only actionable output: one is a 98-cent spread on a 1-hour market, the other a market with an unknown spread. A watch list that shows why each was rejected tells you what a small rule change (a wider spread tolerance, a minimum depth) would pick up, before any rule is changed.",
        "effort": "Small — roi.json already carries the rejection reason for each near miss.",
        "risk": "None. It displays numbers that already exist and changes no trading logic.",
        "success_metric": "roi.html lists each near miss with its rejection reason and the value it would have needed.",
        "status": "partially implemented — the reasons are published on roi.html; a dedicated watch list is still to do.",
        "sources": [
            "https://docs.kalshi.com/getting_started/orderbook_responses",
        ],
    },
    {
        "id": "G20",
        "suggestion": "Poll the demo API from the browser for the top-dollar markets only, and rate-limit it by the documented public limit.",
        "why_it_helps_decisions": "The committed snapshot is at best 20 minutes old, which is the difference between a tradeable signal and a stale one. The dashboard already fetches the demo API from the browser on live.html; doing the same for the highest-dollar market on every category page would make each page live without any manual step.",
        "effort": "Done for the category pages and the home page in this session (assets/site.js startLiveRefresh).",
        "risk": "Public unauthenticated requests have their own rate limit, and the API's responses are cached for a short time, so a browser poll can see a price a few seconds old. The freshness strip shows the poll time so no one mistakes it for a tick stream.",
        "success_metric": "Every category page shows a LIVE strip with a poll time when the browser can reach the API, and says plainly when it cannot.",
        "status": "implemented",
        "sources": [
            "https://docs.kalshi.com/getting_started/rate_limits",
            "https://docs.kalshi.com/api-reference/market/get-markets",
        ],
    },
]


def main() -> int:
    doc = json.loads(FINDINGS.read_text(encoding="utf-8"))

    by_id = {f["id"]: f for f in doc["flagged"]}
    for fid, patch in UPDATES.items():
        f = by_id.get(fid)
        if not f:
            # A flag this session raises for the first time is appended, not dropped.
            doc["flagged"].append(dict(patch, id=fid))
            continue
        f.update(patch)

    q_ids = {q["id"] for q in doc["questions"]}
    for q in NEW_QUESTIONS:
        if q["id"] not in q_ids:
            doc["questions"].append(q)

    g_ids = {g["id"] for g in doc["suggestions"]}
    for g in NEW_SUGGESTIONS:
        if g["id"] not in g_ids:
            doc["suggestions"].append(g)

    doc["generated"] = "2026-11-20 (official-source re-audit, session arena-0f71797f)"
    FINDINGS.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"flagged={len(doc['flagged'])} questions={len(doc['questions'])} suggestions={len(doc['suggestions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
