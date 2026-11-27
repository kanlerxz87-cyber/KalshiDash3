#!/usr/bin/env python3
"""Classify every >= $0.10 swing alert by the evidence behind it: was it a trade, or a quote?

Why this file exists
  The alert rule watches `last_price_dollars`, which Kalshi documents as "Price for the last
  traded YES contract on this market in dollars"
  (https://docs.kalshi.com/api-reference/market/get-markets). Consecutive observations of that
  field can be >= $0.10 apart for two very different reasons:

    a) contracts actually changed hands in the interval, or
    b) no trade printed at all and the reported "last" price simply differs between the two
       reads (a stale/late reference, a book change, a demo-environment artefact).

  On the committed 2026-11-21T23:01:10Z snapshot, 25 of 48 archived swings moved >= 50c while
  fewer than 200 contracts traded in the interval, and several moved with ZERO contracts
  traded. Presenting those as "the price moved" without saying which kind of event it was is
  the one thing this project must not do (README rule 1: no invented values).

What this module does, and does not, claim
  It computes, from the two observations that bound the swing and nothing else:

    contracts_traded  = volume_fp(to) - volume_fp(from)
                        Kalshi: volume_fp is the "market volume in contracts"
                        (https://docs.kalshi.com/api-reference/market/get-markets). The
                        difference of the cumulative field between two reads is therefore the
                        number of contracts traded between them -- arithmetic on two cited
                        numbers, not an estimate.
    est_dollars       = contracts_traded x to_price. An ESTIMATE computed here (contracts trade
                        at different prices inside the interval), labelled as an estimate and
                        never presented as a Kalshi field. This project has no official
                        "dollars traded" field (F-01, Q1).
    reversion         = whether later observations returned to within half the move. Counts and
                        distances only; no claim about why.

  It does NOT claim a cause, a motive, conviction, or that a quoted price is tradable. The word
  "cause" is refused here for the same reason scripts/catalysts.py refuses it (F-15, F-25).

The quote check (49BA-1) — is the printed price even inside the book?
  `evidence.state` above says whether a trade happened. It does not say whether the recorded
  end price was *executable*: last_price_dollars is a print, while yes_bid_dollars and
  yes_ask_dollars are the two-sided quote read at the same instant from the same Get Markets
  response (https://docs.kalshi.com/api-reference/market/get-markets, and the response is
  documented as cached/lagging the exchange by several seconds). A print can therefore sit
  outside the current quote — either side — with no trade at the quote at all.

  `evidence.quote` publishes that comparison per row:
    inside_quote    to_price is within [to_yes_bid, to_yes_ask] of the same read
    outside_quote   it is not; `outside_by_dollars` says by how much
    unknown_quote   no usable two-sided quote was recorded with the read (legacy rows) --
                    nothing is inferred
  It is a comparison of two recorded official fields, nothing more. It does not claim why the
  print sits outside the quote, and it does not re-score the frozen `high_roi` flag.

States (exhaustive, and each one is falsifiable from the snapshot)
  traded_ge_floor      contracts_traded >= policy floor; a trade printed in the interval
  traded_below_floor   contracts_traded > 0 but below the floor
  quote_only           contracts_traded == 0 -- the reported price changed with no trade
  counter_reset        volume_fp DECREASED (or an observation is missing it), so the field does
                       not behave as a monotonic counter across these two reads; the interval's
                       contract count is unknowable from these reads and is left null
  candle_unquantified  one of the two observations is a CANDLE BACKFILL point. Candlestick
                       volume_fp is documented as "the number of contracts bought on the market
                       during the candlestick period" -- a PER-PERIOD figure, NOT the cumulative
                       volume_fp on GET /markets. Differencing those two different meanings would
                       invent a contract count, so the count is left null and the state names why
  unknown_no_observations  the swing's two observations are not in the committed history
                       (market pruned or archive-only). Nothing is inferred.

The floor is a PROJECT RULE, not a Kalshi field. Kalshi publishes no per-move significance
field; the floor exists only so a dashboard can offer a "traded only" view, it is written in
data/alert_rules.json next to the rule that uses it, and every row still shows the exact
contract count so a reader can apply their own floor.

Run: python3 scripts/build_alerts.py (it calls evaluate() for every alert it serves)
Test: python3 scripts/tests/test_evidence.py
"""
from __future__ import annotations

NON_ASCII_FIELD_NOTE = "est_dollars is computed here (contracts x price); it is not a Kalshi field."

SOURCES = {
    "fields": "https://docs.kalshi.com/api-reference/market/get-markets",
    "candles": "https://docs.kalshi.com/api-reference/market/get-market-candlesticks",
    "lifecycle": "https://docs.kalshi.com/getting_started/market_lifecycle",
    "demo": "https://docs.kalshi.com/getting_started/demo_env",
    # The quote fields (yes_bid_dollars / yes_ask_dollars) are documented on Get Markets; the
    # bid-only structure of the order book behind them is documented on Order Book Responses.
    "quote": "https://docs.kalshi.com/getting_started/orderbook_responses",
}

DEFAULT_FLOOR = 100.0
REVERSION_WINDOW = 3          # observations looked at after the swing
HALF_MOVE = 0.5               # "gave back at least half the move" threshold
EPS = 1e-9
QUOTE_EPS = 1e-9              # float tolerance for "inside the quote"


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def index_observations(observations) -> dict:
    """{iso timestamp: observation} for the observations that carry a timestamp."""
    out = {}
    for o in observations or []:
        t = o.get("t")
        if isinstance(t, str) and t:
            out[t] = o
    return out


def _round(x, n=4):
    return None if x is None else round(float(x), n)


def reversion(alert: dict, by_time: dict, sorted_times: list) -> dict:
    """Did the price hold the move? Counts and distances only, from later observations.

    `gave_back_half` is true when a later observation within REVERSION_WINDOW sits at least
    half the move back towards `from_price`. That is arithmetic on cited prices.
    """
    to_t = alert.get("to_time")
    frm, to = _num(alert.get("from_price")), _num(alert.get("to_price"))
    if to_t not in by_time or frm is None or to is None:
        return {"observed_after": 0, "min_distance_from_from_price": None,
                "gave_back_half": None, "still_open": True}
    idx = sorted_times.index(to_t)
    later = sorted_times[idx + 1: idx + 1 + REVERSION_WINDOW]
    move = abs(to - frm)
    dists = []
    for t in later:
        p = _num((by_time.get(t) or {}).get("last"))
        if p is not None:
            dists.append(abs(p - frm))
    out = {
        "observed_after": len(dists),
        "min_distance_from_from_price": _round(min(dists)) if dists else None,
        "gave_back_half": (min(dists) <= move * HALF_MOVE + EPS) if dists else None,
        "still_open": not dists,
    }
    return out


def quote_check(alert: dict, observation=None) -> dict:
    """Compare the swing's printed end price with the two-sided quote of the SAME read.

    Both sides come from one Get Markets response, so this is a comparison of two recorded
    official fields, not an estimate: `to_price` was last_price_dollars and
    `to_yes_bid`/`to_yes_ask` were yes_bid_dollars/yes_ask_dollars at that instant. The alert
    row's own fields are preferred (they are frozen with the row); when a legacy row carries
    no quote, the observation that bounds it is consulted, and the provenance used is named.

    Returns one of three states and never a guess:
      inside_quote   to_yes_bid <= to_price <= to_yes_ask
      outside_quote  to_price lies outside that band; `outside_by_dollars` is the distance
      unknown_quote  no usable two-sided quote (missing, non-numeric, or bid > ask / out of 0..1)
    """
    price = _num(alert.get("to_price"))
    bid = _num(alert.get("to_yes_bid"))
    ask = _num(alert.get("to_yes_ask"))
    source = "alert.to_yes_bid / alert.to_yes_ask (GET /markets at the to_time read)"
    if (bid is None or ask is None) and isinstance(observation, dict):
        ob, oa = _num(observation.get("yes_bid")), _num(observation.get("yes_ask"))
        if ob is not None and oa is not None:
            bid, ask = ob, oa
            source = "price_history observation at to_time (GET /markets)"
    base = {
        "to_last_price": _round(price),
        "to_yes_bid": _round(bid),
        "to_yes_ask": _round(ask),
        "quote_source": source,
        "sources": {"quote": SOURCES["quote"], "fields": SOURCES["fields"]},
    }
    usable = (
        price is not None and bid is not None and ask is not None
        and -EPS <= bid <= ask + EPS <= 1.0 + EPS
    )
    if not usable:
        base.update({
            "state": "unknown_quote",
            "spread_dollars": None,
            "outside_by_dollars": None,
            "why": "no usable two-sided quote (yes_bid_dollars / yes_ask_dollars) was recorded "
                   "with this read, so whether the printed price sat inside the quote cannot "
                   "be checked and is left unknown",
        })
        return base
    if bid - QUOTE_EPS <= price <= ask + QUOTE_EPS:
        state, outside_by = "inside_quote", 0.0
        why = (f"the printed price {price:.2f} is inside the quote recorded at the same read "
               f"(yes_bid {bid:.2f} / yes_ask {ask:.2f})")
    else:
        state = "outside_quote"
        outside_by = max(bid - price, price - ask, 0.0)
        side = "above the recorded yes_ask" if price > ask else "below the recorded yes_bid"
        why = (f"the printed price {price:.2f} is {side} ({ask:.2f} / {bid:.2f} bid) — the "
               f"last-traded price of the interval is {outside_by:.2f} outside the two-sided "
               f"quote recorded in the same read, so it is not a price a reader could have "
               f"traded at that quote; this does not claim why the two differ")
    base.update({
        "state": state,
        "spread_dollars": _round(ask - bid),
        "outside_by_dollars": _round(outside_by),
        "why": why,
    })
    return base


def evaluate(alert: dict, observations, floor: float = DEFAULT_FLOOR) -> dict:
    """Evaluate one archived swing against the committed observations of its market."""
    by_time = index_observations(observations)
    times = sorted(by_time)
    frm_t, to_t = alert.get("from_time"), alert.get("to_time")
    base = {
        "policy_floor_contracts": float(floor),
        "policy_floor_is_a_kalshi_field": False,
        "sources": dict(SOURCES),
    }
    # 49BA-1: the quote comparison travels with every state, including the ones that cannot
    # quantify the interval, because it needs only the fields recorded with the read.
    base["quote"] = quote_check(alert, by_time.get(to_t))
    rev = reversion(alert, by_time, times)
    base["reversion"] = rev

    if frm_t not in by_time or to_t not in by_time:
        base.update({
            "state": "unknown_no_observations",
            "contracts_traded": None,
            "est_dollars": None,
            "why": "the two observations that bound this swing are not in the committed "
                   "price history (the market was pruned or the row is archive-only)",
        })
        return base

    # The contract count is only computable when BOTH reads are REST observations of the
    # cumulative GET /markets volume_fp. Candlestick volume_fp has a different meaning (per
    # period), documented at
    # https://docs.kalshi.com/api-reference/market/get-market-candlesticks
    src0 = (by_time[frm_t] or {}).get("source") or "rest"
    src1 = (by_time[to_t] or {}).get("source") or "rest"
    if src0 != "rest" or src1 != "rest":
        base.update({
            "state": "candle_unquantified",
            "contracts_traded": None,
            "est_dollars": None,
            "volume_from": _num((by_time[frm_t] or {}).get("volume_fp")),
            "volume_to": _num((by_time[to_t] or {}).get("volume_fp")),
            "observation_sources": [src0, src1],
            "why": "at least one of the two observations is a candle-backfill point; candlestick "
                   "volume_fp is a PER-PERIOD contract count, not the cumulative volume_fp on "
                   "GET /markets, so subtracting one from the other would invent a number",
        })
        return base

    v0 = _num((by_time[frm_t] or {}).get("volume_fp"))
    v1 = _num((by_time[to_t] or {}).get("volume_fp"))
    to_price = _num(alert.get("to_price"))

    if v0 is None or v1 is None or v1 + EPS < v0:
        base.update({
            "state": "counter_reset",
            "contracts_traded": None,
            "est_dollars": None,
            "volume_from": v0,
            "volume_to": v1,
            "why": "volume_fp is documented as the market's cumulative volume in contracts "
                   "(Get Markets); between these two reads it did not increase, so the "
                   "contracts traded in this interval cannot be derived from them — left null "
                   "rather than guessed",
        })
        return base

    traded = round(v1 - v0, 2)
    est = round(traded * to_price, 2) if to_price is not None else None
    if traded <= EPS:
        state = "quote_only"
        why = ("no contracts traded between these two reads (volume_fp unchanged), so the "
               "reported last price changed without a trade in the interval")
    elif traded < float(floor) - EPS:
        state = "traded_below_floor"
        why = (f"{traded:g} contracts traded in the interval, below this project's "
               f"{float(floor):g}-contract floor for calling a swing a market move")
    else:
        state = "traded_ge_floor"
        why = (f"{traded:g} contracts traded in the interval, at or above this project's "
               f"{float(floor):g}-contract floor")
    base.update({
        "state": state,
        "contracts_traded": traded,
        "est_dollars": est,
        "volume_from": round(v0, 2),
        "volume_to": round(v1, 2),
        "why": why,
        "note": NON_ASCII_FIELD_NOTE,
    })
    return base


def summarize(evaluated) -> dict:
    """Counts for the feed header. Deterministic order; every state always present."""
    states = ("traded_ge_floor", "traded_below_floor", "quote_only",
              "counter_reset", "candle_unquantified", "unknown_no_observations")
    counts = {s: 0 for s in states}
    gave_back = 0
    held = 0
    for a in evaluated or []:
        ev = (a or {}).get("evidence") or a or {}
        st = ev.get("state")
        if st in counts:
            counts[st] += 1
        rev = ev.get("reversion") or ev.get("evidence_reversion") or {}
        if rev.get("gave_back_half") is True:
            gave_back += 1
        elif rev.get("gave_back_half") is False:
            held += 1
    counts["gave_back_half_within_3"] = gave_back
    counts["held_false"] = held
    counts["floor_contracts"] = float(DEFAULT_FLOOR)
    return counts


QUOTE_STATES = ("inside_quote", "outside_quote", "unknown_quote")


def summarize_quote(rows) -> dict:
    """Counts for the quote check (49BA-1). Every state always present; no derived ratio.

    Read from `evidence.quote.state` on each row. A row without the block (written before this
    check existed) counts as unknown_quote rather than being assumed inside the quote.
    """
    counts = {s: 0 for s in QUOTE_STATES}
    for a in rows or []:
        q = ((a or {}).get("evidence") or {}).get("quote") or {}
        st = q.get("state")
        counts[st if st in counts else "unknown_quote"] += 1
    counts["rows"] = len(rows or [])
    return counts
