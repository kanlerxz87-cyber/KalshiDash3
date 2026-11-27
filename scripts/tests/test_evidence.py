#!/usr/bin/env python3
"""Offline tests for scripts/alert_evidence.py.

Every test builds its own observations; nothing here reads the committed snapshot, so a
regression in the classifier cannot hide behind whatever data happens to be on disk.

Run: python3 scripts/tests/test_evidence.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import alert_evidence as E  # noqa: E402

FAILED: list[str] = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)


def obs(t, last, vol, bid=None, ask=None):
    return {"t": t, "last": last, "volume_fp": vol, "yes_bid": bid, "yes_ask": ask}


def alert(frm_t, to_t, frm, to):
    return {"ticker": "T-1", "from_time": frm_t, "to_time": to_t,
            "from_price": frm, "to_price": to, "delta": round(to - frm, 4)}


T0, T1, T2, T3, T4 = ("2026-11-21T22:46:10Z", "2026-11-21T23:01:10Z",
                      "2026-11-21T23:16:10Z", "2026-11-21T23:31:10Z",
                      "2026-11-21T23:46:10Z")


def test_traded_above_floor():
    a = alert(T0, T1, 0.50, 0.72)
    ev = E.evaluate(a, [obs(T0, 0.50, 1000.0), obs(T1, 0.72, 1400.0)])
    check(ev["state"] == "traded_ge_floor", f"traded_ge_floor expected, got {ev['state']}")
    check(ev["contracts_traded"] == 400.0, f"contracts 400 expected, got {ev['contracts_traded']}")
    # est_dollars = 400 x 0.72, computed here, labelled as an estimate
    check(ev["est_dollars"] == 288.0, f"est_dollars 288 expected, got {ev['est_dollars']}")
    check(ev["policy_floor_is_a_kalshi_field"] is False, "the floor must be disclosed as a project rule")


def test_traded_below_floor():
    a = alert(T0, T1, 0.99, 0.02)
    ev = E.evaluate(a, [obs(T0, 0.99, 5000.0), obs(T1, 0.02, 5030.0)])
    check(ev["state"] == "traded_below_floor", f"traded_below_floor expected, got {ev['state']}")
    check(ev["contracts_traded"] == 30.0, f"contracts 30 expected, got {ev['contracts_traded']}")


def test_quote_only_zero_volume():
    a = alert(T0, T1, 0.99, 0.02)
    ev = E.evaluate(a, [obs(T0, 0.99, 5000.0), obs(T1, 0.02, 5000.0)])
    check(ev["state"] == "quote_only", f"quote_only expected, got {ev['state']}")
    check(ev["contracts_traded"] == 0.0, f"contracts 0 expected, got {ev['contracts_traded']}")
    check(ev["est_dollars"] == 0.0, f"est_dollars 0 expected, got {ev['est_dollars']}")


def test_counter_reset_is_null_not_negative():
    # The demo environment really does this: see the -85 / -20 / -22.45 deltas in the
    # 2026-11-21 archive. A negative contract count would be a fabricated number.
    a = alert(T0, T1, 0.65, 0.45)
    ev = E.evaluate(a, [obs(T0, 0.65, 120.0), obs(T1, 0.45, 100.0)])
    check(ev["state"] == "counter_reset", f"counter_reset expected, got {ev['state']}")
    check(ev["contracts_traded"] is None, "a reset interval must leave contracts_traded null")


def test_candle_backfill_point_is_never_differenced():
    # Candlestick volume_fp is documented as "the number of contracts bought on the market
    # during the candlestick period" -- a per-period count, not the cumulative volume_fp on
    # GET /markets. Subtracting across a candle point would invent a contract count.
    a = alert(T0, T1, 0.55, 0.65)
    o0 = obs(T0, 0.55, 10.0)
    o1 = obs(T1, 0.65, 20.0)
    o1["source"] = "candle"
    ev = E.evaluate(a, [o0, o1])
    check(ev["state"] == "candle_unquantified", f"candle_unquantified expected, got {ev['state']}")
    check(ev["contracts_traded"] is None, "a candle-derived interval must leave the count null")
    check(ev["observation_sources"] == ["rest", "candle"], "the row must name the observation sources")


def test_candle_point_on_the_from_side_also_blocks_the_count():
    a = alert(T0, T1, 0.55, 0.65)
    o0 = obs(T0, 0.55, 10.0)
    o0["source"] = "candle"
    ev = E.evaluate(a, [o0, obs(T1, 0.65, 20.0)])
    check(ev["state"] == "candle_unquantified", f"candle_unquantified expected, got {ev['state']}")
    check(ev["contracts_traded"] is None, "the count must stay null")


def test_missing_volume_field_is_null():
    a = alert(T0, T1, 0.55, 0.65)
    ev = E.evaluate(a, [{"t": T0, "last": 0.55}, {"t": T1, "last": 0.65}])
    check(ev["state"] == "counter_reset", f"missing volume must be counter_reset, got {ev['state']}")
    check(ev["contracts_traded"] is None, "missing volume must not produce a number")


def test_unknown_when_observations_absent():
    a = alert("2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z", 0.10, 0.30)
    ev = E.evaluate(a, [obs(T0, 0.50, 10.0), obs(T1, 0.60, 20.0)])
    check(ev["state"] == "unknown_no_observations", f"unknown expected, got {ev['state']}")
    check(ev["contracts_traded"] is None, "unknown must not produce a number")
    check(ev["reversion"]["gave_back_half"] is None, "unknown must not claim a reversion")


def test_reversion_detects_give_back():
    a = alert(T0, T1, 0.02, 0.99)
    ev = E.evaluate(a, [obs(T0, 0.02, 10.0), obs(T1, 0.99, 20.0), obs(T2, 0.02, 30.0)])
    check(ev["reversion"]["observed_after"] == 1, "one later observation expected")
    check(ev["reversion"]["gave_back_half"] is True, "a full give-back must be detected")
    check(ev["reversion"]["still_open"] is False, "a swing with a later read is not still open")


def test_reversion_holds():
    a = alert(T0, T1, 0.02, 0.99)
    ev = E.evaluate(a, [obs(T0, 0.02, 10.0), obs(T1, 0.99, 20.0),
                        obs(T2, 0.97, 30.0), obs(T3, 0.98, 40.0)])
    check(ev["reversion"]["gave_back_half"] is False, "a held move must not be called a give-back")


def test_reversion_window_is_three_and_open_when_last():
    a = alert(T0, T1, 0.02, 0.99)
    ev = E.evaluate(a, [obs(T0, 0.02, 10.0), obs(T1, 0.99, 20.0)])
    check(ev["reversion"]["still_open"] is True, "the newest swing has no later read: still_open")
    check(ev["reversion"]["observed_after"] == 0, "no later observations expected")


def test_reversion_window_ignores_the_fourth_read():
    a = alert(T0, T1, 0.02, 0.99)
    t5 = "2026-11-22T00:01:10Z"
    ev = E.evaluate(a, [obs(T0, 0.02, 10.0), obs(T1, 0.99, 20.0), obs(T2, 0.98, 30.0),
                        obs(T3, 0.99, 40.0), obs(T4, 0.98, 50.0), obs(t5, 0.02, 60.0)])
    # The fifth later read gives the move back, but the documented window is three reads:
    # T2, T3, T4. Counting it would overstate how often a price gives a move back.
    check(ev["reversion"]["observed_after"] == 3, "exactly three later reads are in the window")
    check(ev["reversion"]["gave_back_half"] is False,
          "only the first three later reads count towards the window")


def test_floor_is_configurable_and_reported():
    a = alert(T0, T1, 0.50, 0.72)
    ev = E.evaluate(a, [obs(T0, 0.50, 1000.0), obs(T1, 0.72, 1400.0)], floor=500.0)
    check(ev["state"] == "traded_below_floor", f"floor 500 must downgrade a 400-contract move, got {ev['state']}")
    check(ev["policy_floor_contracts"] == 500.0, "the applied floor must be reported on the row")


def test_every_state_is_reachable_and_summarized():
    rows = [
        alert(T0, T1, 0.50, 0.72),
        alert(T0, T1, 0.99, 0.02),
        alert(T0, T1, 0.02, 0.99),
        {"ticker": "X", "from_time": "2020-01-01T00:00:00Z", "to_time": "2020-01-01T00:15:00Z",
         "from_price": 0.1, "to_price": 0.3},
    ]
    hist = [obs(T0, 0.50, 1000.0), obs(T1, 0.72, 1400.0)]
    evaluated = [{"evidence": E.evaluate(a, hist)} for a in rows]
    s = E.summarize(evaluated)
    for state in ("traded_ge_floor", "traded_below_floor", "quote_only",
                  "counter_reset", "candle_unquantified", "unknown_no_observations"):
        check(state in s, f"summary must always carry {state}")
    check(s["unknown_no_observations"] == 1, "one alert has no observations")
    check(s["floor_contracts"] == E.DEFAULT_FLOOR, "summary must state the floor")


# ---------------------------------------------------------------- 49BA-1: quote check
# last_price_dollars is a print; yes_bid_dollars / yes_ask_dollars are the two-sided quote of
# the SAME Get Markets read. A print outside that band was not executable at the recorded
# quote, and the alert must say so instead of presenting the print as a tradable move.

def quoted(frm, to, bid, ask):
    a = alert(T0, T1, frm, to)
    a["to_yes_bid"], a["to_yes_ask"] = bid, ask
    return a


def test_quote_inside_is_labelled_inside():
    a = quoted(0.40, 0.52, 0.51, 0.53)
    q = E.evaluate(a, [obs(T0, 0.40, 100.0), obs(T1, 0.52, 200.0)])["quote"]
    check(q["state"] == "inside_quote", f"inside_quote expected, got {q['state']}")
    check(q["outside_by_dollars"] == 0.0, f"an inside print has no distance, got {q['outside_by_dollars']}")
    check(q["spread_dollars"] == 0.02, f"spread 0.02 expected, got {q['spread_dollars']}")


def test_print_above_the_ask_is_outside_the_quote():
    # The committed KXBTCY-27JAN0100-B97500 rows: a 0.01 -> 0.97 print recorded against a
    # yes_bid 0.00 / yes_ask 0.01 quote. The 96c "move" was never available at the quote.
    a = quoted(0.01, 0.97, 0.00, 0.01)
    ev = E.evaluate(a, [obs(T0, 0.01, 72562103.0), obs(T1, 0.97, 72562103.0)])
    q = ev["quote"]
    check(q["state"] == "outside_quote", f"outside_quote expected, got {q['state']}")
    check(q["outside_by_dollars"] == 0.96, f"distance 0.96 expected, got {q['outside_by_dollars']}")
    check(q["spread_dollars"] == 0.01, f"spread 0.01 expected, got {q['spread_dollars']}")
    check(ev["state"] == "quote_only", "the state block must stay independent of the quote check")
    check("not a price a reader could have traded" in q["why"], f"the why must say it plainly: {q['why']}")


def test_print_below_the_bid_is_outside_the_quote():
    a = quoted(0.30, 0.12, 0.20, 0.40)
    q = E.evaluate(a, [obs(T0, 0.30, 10.0), obs(T1, 0.12, 30.0)])["quote"]
    check(q["state"] == "outside_quote", f"outside_quote expected, got {q['state']}")
    check(q["outside_by_dollars"] == 0.08, f"distance 0.08 expected, got {q['outside_by_dollars']}")


def test_missing_quote_is_unknown_not_inside():
    a = alert(T0, T1, 0.30, 0.45)          # legacy row: no to_yes_bid / to_yes_ask
    q = E.evaluate(a, [obs(T0, 0.30, 10.0), obs(T1, 0.45, 30.0)])["quote"]
    check(q["state"] == "unknown_quote", f"unknown_quote expected, got {q['state']}")
    check(q["outside_by_dollars"] is None, "an unknown quote must not carry a distance")
    check("unknown" in q["why"], f"the why must say it is unknown: {q['why']}")


def test_inverted_or_out_of_range_quote_is_unknown():
    for bid, ask in ((0.60, 0.40), (0.10, 1.20), (-0.10, 0.50)):
        a = quoted(0.30, 0.45, bid, ask)
        q = E.evaluate(a, [obs(T0, 0.30, 10.0), obs(T1, 0.45, 30.0)])["quote"]
        check(q["state"] == "unknown_quote",
              f"bid {bid} / ask {ask} is not a usable quote, got {q['state']}")


def test_quote_falls_back_to_the_bounding_observation_and_names_it():
    a = alert(T0, T1, 0.30, 0.90)          # legacy row, but the observation carries the quote
    ev = E.evaluate(a, [obs(T0, 0.30, 10.0, bid=0.30, ask=0.35), obs(T1, 0.90, 30.0, bid=0.34, ask=0.36)])
    q = ev["quote"]
    check(q["state"] == "outside_quote", f"outside_quote expected from the observation, got {q['state']}")
    check(q["to_yes_bid"] == 0.34 and q["to_yes_ask"] == 0.36, f"observation quote expected, got {q}")
    check("observation" in q["quote_source"], f"the fallback source must be named: {q['quote_source']}")


def test_quote_summary_counts_every_row_and_never_assumes_inside():
    rows = [
        {"evidence": E.evaluate(quoted(0.40, 0.52, 0.51, 0.53), [])},
        {"evidence": E.evaluate(quoted(0.01, 0.97, 0.00, 0.01), [])},
        {"evidence": E.evaluate(alert(T0, T1, 0.30, 0.45), [])},          # no quote at all
        {"evidence": {"state": "traded_ge_floor"}},                       # pre-49BA-1 row
    ]
    s = E.summarize_quote(rows)
    check(s["inside_quote"] == 1, f"one inside expected, got {s['inside_quote']}")
    check(s["outside_quote"] == 1, f"one outside expected, got {s['outside_quote']}")
    check(s["unknown_quote"] == 2, f"two unknown expected (no block, no quote), got {s['unknown_quote']}")
    check(s["rows"] == 4, f"rows 4 expected, got {s['rows']}")
    check(sum(s[k] for k in ("inside_quote", "outside_quote", "unknown_quote")) == s["rows"],
          "the three quote states must partition the rows")


def test_never_emits_a_cause():
    banned = ("cause", "caused", "because of", "trigger")
    for a in (alert(T0, T1, 0.5, 0.7), alert(T0, T1, 0.99, 0.02)):
        ev = E.evaluate(a, [obs(T0, 0.5, 10.0), obs(T1, 0.7, 20.0)])
        text = (ev.get("why") or "").lower() + " " + (ev.get("note") or "").lower()
        for b in banned:
            check(b not in text, f"evidence text must not assert a {b!r}: {text!r}")


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        before = len(FAILED)
        fn()
        print(("ok   " if len(FAILED) == before else "FAIL ") + name)
    if FAILED:
        print("\nFAILURES:", file=sys.stderr)
        for f in FAILED:
            print("  -", f, file=sys.stderr)
        return 1
    print(f"\nOK: {len(tests)} evidence-classifier tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
