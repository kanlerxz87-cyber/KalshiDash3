#!/usr/bin/env python3
"""One-shot ledger writer for the 2026-11-22 catalyst review pass (arena-d34a9f0d, T74).

Reads the committed archive + price history, classifies each unreviewed swing from the two
observations that bound it, and writes one review row per swing into data/catalyst_review.json.

Every source below was fetched in this session and its `observed` block holds values copied out
of that response. Nothing is inferred: a row is classified `best_quote_did_not_move` only when the
committed bid AND ask are byte-identical at both reads, and `reference_not_publicly_readable` only
when the market's own rules name an index with no public read.

Not part of the release gate: this is a data-entry tool, run once, and its output is checked by
scripts/tests/validate_catalysts.py and scripts/catalysts.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data" / "catalyst_review.json"
LIVE = ROOT / "data" / "live"
FETCHED = "2026-11-22T08:20Z"

KALSHI = "https://external-api.demo.kalshi.co/trade-api/v2/markets/"

# --- verbatim readings copied out of each GET /markets/{ticker} response, this session --------
MARKET_OBSERVED = {
    "KXBTCY-27JAN0100-B97500": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' BRTI before 12 AM EST is between 95000.00-99999.99 at 12 AM EST on Jan 1, 2027, then the market resolves to Yes.",
        title="BTC price  on Jan 1, 2027?", yes_sub_title="95,000 to 99,999.99",
        floor_strike=95000, cap_strike=99999.99, strike_type="between",
        last_price_dollars="0.9700", previous_price_dollars="0.0100",
        yes_bid_dollars="0.0000", yes_ask_dollars="0.9700",
        volume_fp="72327704.49", volume_24h_fp="7692.47", open_interest_fp="7296573.11",
        status="active", result=""),
    "KXBTCY-27JAN0100-B87500": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' BRTI before 12 AM EST is between 85000.00-89999.99 at 12 AM EST on Jan 1, 2027, then the market resolves to Yes.",
        title="BTC price  on Jan 1, 2027?", yes_sub_title="85,000 to 89,999.99",
        floor_strike=85000, cap_strike=89999.99, strike_type="between",
        last_price_dollars="0.9900", previous_price_dollars="0.0200",
        yes_bid_dollars="0.0100", yes_ask_dollars="0.9900",
        volume_fp="58460186.74", volume_24h_fp="14407.93", open_interest_fp="6094361.29",
        status="active", result=""),
    "KXBTCY-27JAN0100-B77500": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' BRTI before 12 AM EST is between 75000.00-79999.99 at 12 AM EST on Jan 1, 2027, then the market resolves to Yes.",
        title="BTC price  on Jan 1, 2027?", yes_sub_title="75,000 to 79,999.99",
        floor_strike=75000, cap_strike=79999.99, strike_type="between",
        last_price_dollars="0.0400", previous_price_dollars="0.0400",
        yes_bid_dollars="0.0300", yes_ask_dollars="0.0400",
        volume_fp="39588936.51", volume_24h_fp="7568.23", open_interest_fp="5968304.27",
        status="active", result=""),
    "KXBTCY-27JAN0100-B52500": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' BRTI before 12 AM EST is between 50000.00-54999.99 at 12 AM EST on Jan 1, 2027, then the market resolves to Yes.",
        title="BTC price  on Jan 1, 2027?", yes_sub_title="50,000 to 54,999.99",
        floor_strike=50000, cap_strike=54999.99, strike_type="between",
        last_price_dollars="0.1000", previous_price_dollars="0.1300",
        yes_bid_dollars="0.0900", yes_ask_dollars="0.1000",
        volume_fp="61741094.51", volume_24h_fp="12115.19", open_interest_fp="7788363.75",
        status="active", result=""),
    "KXBTCY-27JAN0100-B47500": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' BRTI before 12 AM EST is between 45000.00-49999.99 at 12 AM EST on Jan 1, 2027, then the market resolves to Yes.",
        title="BTC price  on Jan 1, 2027?", yes_sub_title="45,000 to 49,999.99",
        floor_strike=45000, cap_strike=49999.99, strike_type="between",
        last_price_dollars="0.1400", previous_price_dollars="0.1000",
        yes_bid_dollars="0.0900", yes_ask_dollars="0.1400",
        volume_fp="80211280.95", volume_24h_fp="7639.53", open_interest_fp="26584588.26",
        status="active", result=""),
    "KXBTCY-27JAN0100-B32500": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' BRTI before 12 AM EST is between 30000.00-34999.99 at 12 AM EST on Jan 1, 2027, then the market resolves to Yes.",
        title="BTC price  on Jan 1, 2027?", yes_sub_title="30,000 to 34,999.99",
        floor_strike=30000, cap_strike=34999.99, strike_type="between",
        last_price_dollars="0.0200", previous_price_dollars="0.0400",
        yes_bid_dollars="0.0100", yes_ask_dollars="0.0200",
        volume_fp="35512765.72", volume_24h_fp="6965.13", open_interest_fp="6354404.69",
        status="active", result=""),
    "KXBTCD-26NOV2201-T58799.99": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' Bitcoin Real-Time Index (BRTI) before 1 AM EST is above 58799.99 at 1 AM EST on Nov 22, 2026, then the market resolves to Yes.",
        title="Bitcoin price on Nov 22, 2026?", yes_sub_title="$58,800 or above",
        floor_strike=58799.99, strike_type="greater",
        last_price_dollars="0.2200", previous_price_dollars="0.0000",
        yes_bid_dollars="0.0000", yes_ask_dollars="1.0000",
        volume_fp="10.40", volume_24h_fp="10.40", open_interest_fp="10.40",
        status="finalized", result="no",
        settlement_ts="2026-11-22T06:24:47.340002Z", settlement_value_dollars="0.0000"),
    "KXBTCD-26NOV2201-T58999.99": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' Bitcoin Real-Time Index (BRTI) before 1 AM EST is above 58999.99 at 1 AM EST on Nov 22, 2026, then the market resolves to Yes.",
        title="Bitcoin price on Nov 22, 2026?", yes_sub_title="$59,000 or above",
        floor_strike=58999.99, strike_type="greater",
        last_price_dollars="0.2000", previous_price_dollars="0.0000",
        yes_bid_dollars="0.0000", yes_ask_dollars="1.0000",
        volume_fp="16.17", volume_24h_fp="16.17", open_interest_fp="16.17",
        status="finalized", result="no",
        settlement_ts="2026-11-22T06:24:47.340002Z", settlement_value_dollars="0.0000"),
    "KXBTC15M-26NOV210145-45": dict(
        rules_primary="If the simple average of the sixty seconds of CF Benchmarks' BRTI before 1:45 AM EST on Nov 21, 2026 is at least the simple average of the sixty seconds of CF Benchmarks' BRTI before 1:30 AM EST on November 21, 2026, then the market resolves to Yes.",
        title="BTC price up in next 15 mins?", yes_sub_title="Target Price: $56,009.56",
        floor_strike=56009.56, strike_type="greater_or_equal",
        last_price_dollars="0.9910", previous_price_dollars="0.9910",
        yes_bid_dollars="0.0000", yes_ask_dollars="1.0000",
        volume_fp="534.48", volume_24h_fp="0.00", open_interest_fp="271.15",
        status="finalized", result="yes",
        settlement_ts="2026-11-21T06:45:02.913537Z", settlement_value_dollars="1.0000"),
    "KXAAAGASD-26NOV22-3.6450": dict(
        rules_primary="If average regular gas prices for United States are strictly greater than $3.6450 on Nov 22, 2026 according to AAA, then the market resolves to Yes.",
        title="Will average **gas prices** be above $3.6450?", yes_sub_title="Above 3.6450",
        floor_strike=3.645, strike_type="greater",
        last_price_dollars="0.2300", previous_price_dollars="0.0000",
        yes_bid_dollars="0.0000", yes_ask_dollars="1.0000",
        volume_fp="20.00", volume_24h_fp="20.00", open_interest_fp="20.00",
        status="closed", result=""),
}

AAA_SOURCE = {
    "id": "AAA_NATIONAL_AVERAGE_2026-11-22T0820Z",
    "publisher": "AAA Fuel Gauge Report (the reference this series settles on, named in its own rules_primary)",
    "url": "https://gasprices.aaa.com/",
    "fetched_at": FETCHED,
    "observed_note": "Read off the national table on the page: 'Today's AAA National Average $3.6594 / Price as of 11/21/26'. "
                     "The Nov 22 print this market settles on had not been published at fetch time.",
    "observed": {
        "todays_national_average": 3.6594,
        "price_as_of": "11/21/26",
        "regular_current_avg": 3.6594,
        "regular_yesterday_avg": 3.6898,
        "regular_week_ago_avg": 3.8406,
    },
}

BAND_RE = re.compile(r"between (\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)")


def fmt_cents(x: float) -> str:
    return f"{round(float(x) * 100)}¢"


def main() -> int:
    ledger = json.loads(LEDGER.read_text())
    archive = json.loads((LIVE / "alerts_archive.json").read_text())["alerts"]
    hist = json.loads((LIVE / "price_history.json").read_text())["series"]
    existing_reviews = {(r.get("ticker"), r.get("alert_to_time")) for r in ledger.get("reviews") or []}
    existing_sources = {s.get("id") for s in ledger.get("sources") or []}

    # --- sources -------------------------------------------------------------------------
    for ticker, observed in MARKET_OBSERVED.items():
        sid = f"KALSHI_MARKET_{ticker}"
        if sid in existing_sources:
            continue
        ledger.setdefault("sources", []).append({
            "id": sid,
            "publisher": "Kalshi demo Trade API (the market's own official record)",
            "url": KALSHI + ticker,
            "fetched_at": FETCHED,
            "observed": observed,
        })
    if AAA_SOURCE["id"] not in existing_sources:
        ledger.setdefault("sources", []).append(AAA_SOURCE)

    # --- reviews -------------------------------------------------------------------------
    added = skipped = 0
    for a in archive:
        key = (a.get("ticker"), a.get("to_time"))
        if key in existing_reviews:
            skipped += 1
            continue
        ticker = a["ticker"]
        if ticker not in MARKET_OBSERVED:
            continue
        obs = (hist.get(ticker) or {}).get("observations") or []
        before = next((o for o in obs if o.get("t") == a.get("from_time")), None)
        after = next((o for o in obs if o.get("t") == a.get("to_time")), None)
        if not before or not after:
            print(f"  ! {key}: the two bounding observations are not both in price_history.json — skipped", file=sys.stderr)
            continue
        bid1, ask1 = before.get("yes_bid"), before.get("yes_ask")
        bid2, ask2 = after.get("yes_bid"), after.get("yes_ask")
        if None in (bid1, ask1, bid2, ask2):
            print(f"  ! {key}: a bounding read carries no bid/ask — skipped", file=sys.stderr)
            continue

        mo = MARKET_OBSERVED[ticker]
        up = (a.get("delta") or 0) > 0
        arrow = "▲" if up else "▼"
        band = BAND_RE.search(mo["rules_primary"])
        band_txt = (f"{band.group(1)}–{band.group(2)}" if band else
                    (f"above {mo['rules_primary'].split('above ')[1].split(' at ')[0]}"
                     if "above " in mo["rules_primary"] else "its stated level"))
        strike = mo["floor_strike"]
        src_id = f"KALSHI_MARKET_{ticker}"
        links = [KALSHI + ticker]
        note_tail = ""
        if mo.get("result"):
            note_tail = (f" The market's own record now shows result “{mo['result']}” "
                         f"(settlement_ts {mo['settlement_ts']}, settlement value {mo['settlement_value_dollars']}), "
                         f"so this swing was priced before the outcome was known.")

        head = (f"Printed {arrow}{abs(a['delta']) * 100:.0f}¢ ({fmt_cents(a['from_price'])} → {fmt_cents(a['to_price'])}) "
                f"between {a['from_time']} and {a['to_time']}.")

        if (bid1, ask1) == (bid2, ask2):
            verdict = "best_quote_did_not_move"
            comparison = {"kind": "band_floor_from_rules", "strike": strike, "reference_side": "yes",
                          "reference_name": "the band floor written into the market's own rules"}
            note = (head + f" The committed book was identical at both reads — yes bid {float(bid1):.2f} / ask "
                    f"{float(ask1):.2f} before and after — so the ≥$0.10 change is in the last-traded print, not in "
                    f"the quoted price: "
                    f"nobody repriced this market between the two observations. The market pays only if the "
                    f"CF Benchmarks BRTI 60-second average lands in the {band_txt} band on Jan 1, 2027; that index "
                    f"has no public read, so no reading of it is quoted." + note_tail)
        elif ticker.startswith("KXAAAGASD"):
            verdict = "published_reference_on_the_same_side_as_the_move"
            comparison = {"kind": "published_value_above_strike", "strike": strike, "reference_side": "yes",
                          "reference_name": "AAA US national average (regular)",
                          "value_before": 3.6594, "value_before_at": "2026-11-21",
                          "value_after": 3.6594, "value_after_at": "2026-11-21"}
            links = ["https://gasprices.aaa.com/", KALSHI + ticker]
            note = (head + f" The committed book did reprice (yes bid/ask {float(bid1):.2f}/{float(ask1):.2f} → "
                    f"{float(bid2):.2f}/{float(ask2):.2f}). AAA's published US national average for regular was $3.6594 as of 11/21/26, above the "
                    f"$3.6450 strike — but that is the prior day's print; the Nov 22 average this market settles on "
                    f"had not been published when it was read, so this is the published figure on the same side as "
                    f"the move and not a statement about the outcome.")
        else:
            verdict = "reference_not_publicly_readable"
            comparison = {"kind": "band_floor_from_rules", "strike": strike, "reference_side": "yes",
                          "reference_name": "the band floor written into the market's own rules"}
            pays = (f"only if the CF Benchmarks BRTI 60-second average lands in the {band_txt} band on Jan 1, 2027"
                    if band else "on CF Benchmarks' BRTI against its own earlier reading")
            note = (head + f" The committed book did reprice (yes bid/ask {float(bid1):.2f}/{float(ask1):.2f} → "
                    f"{float(bid2):.2f}/{float(ask2):.2f}), so unlike the unchanged-book rows this is a real change "
                    f"in the quoted price. The market pays {pays}. That index has no public read, so no reading of it "
                    f"is quoted and nothing is asserted about why the book moved." + note_tail)

        ledger.setdefault("reviews", []).append({
            "ticker": ticker,
            "alert_to_time": a["to_time"],
            "source_ids": [s for s in ([src_id] + (["AAA_NATIONAL_AVERAGE_2026-11-22T0820Z"] if len(links) > 1 else []))],
            "window_from": a.get("from_time"),
            "window_to": a.get("to_time"),
            "comparison": comparison,
            "verdict_override": verdict,
            "links": links,
            "note": note,
        })
        added += 1

    ledger["reviewed_by_session"] = "arena-d34a9f0d"
    ledger["reviewed_on"] = "2026-11-22"
    LEDGER.write_text(json.dumps(ledger, indent=1) + "\n", encoding="utf-8")
    print(f"OK: added {added} reviews, {skipped} already present, "
          f"{len(ledger['sources'])} sources, {len(ledger['reviews'])} reviews in the ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
