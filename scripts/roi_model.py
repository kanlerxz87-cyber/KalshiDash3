#!/usr/bin/env python3
"""KalshiDash3 ROI screen — the Python half of one model.

The browser half is ``assets/live.js``. Both read ``data/roi_model.json`` and both
implement the same arithmetic; ``scripts/tests/test_roi_parity.py`` runs them on one
fixture and fails if a single number differs, so the CI-committed picks and the
in-browser live picks can never quietly drift apart.

Every input is a documented field of the public demo API:
  GET /markets ............. https://docs.kalshi.com/api-reference/market/get-markets
  GET /markets/orderbooks .. https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks
  order-book semantics ..... https://docs.kalshi.com/getting_started/orderbook_responses
  fees ..................... https://kalshi.com/docs/kalshi-fee-schedule.pdf
  settlement payout ........ https://docs.kalshi.com/getting_started/market_settlement
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "data" / "roi_model.json"

URL_RE = re.compile(r"https?://[^\s\"'<>()]+")
TEXT_FIELDS = ("rules_primary", "rules_secondary", "subtitle", "yes_sub_title", "no_sub_title", "title")


def load_model(path: Path = MODEL_PATH) -> dict:
    return json.loads(Path(path).read_text())


def ceil_cent(x: float) -> float:
    """Round up to the next cent, in integer arithmetic so binary float dust cannot inflate a fee.

    The fee schedule says the fee is rounded "up such that the fee + positionCost is
    rounded to a centicent". Rounding the total up to the next cent reproduces every row
    of the schedule's general table exactly (asserted in scripts/tests/test_fees.py).
    Naive `math.ceil(x * 100) / 100` does NOT: 0.07 x 100 x 0.2 x 0.8 evaluates to
    1.1200000000000003 in float and would bill $1.13 where the schedule prints $1.12.
    Working in millionths of a dollar with floor division avoids that entirely, and the
    browser mirror (assets/live.js) uses the identical integer route.
    """
    micro = round(x * 1e6)               # 1e-6 dollars, exact for the magnitudes here
    if x <= 0:
        return 0.0
    micro = max(1, micro)                 # any positive fee rounds up, never down to zero
    return ((micro + 9_999) // 10_000) / 100.0


def taker_fee(contracts: float, price: float, mult: float = 1.0) -> float:
    """fee = round up(M x 0.07 x C x P x (1-P))  — the general taker formula."""
    return ceil_cent(mult * 0.07 * contracts * price * (1.0 - price))


def maker_fee(contracts: float, price: float, mult: float = 0.0) -> float:
    """fee = round up(M x 0.0175 x C x P x (1-P)) — maker M defaults to 0."""
    return ceil_cent(mult * 0.0175 * contracts * price * (1.0 - price))


def taker_fee_unit(price: float, mult: float = 1.0) -> float:
    """Per-contract, unrounded — used for scoring only; a ledger must use taker_fee()."""
    return mult * 0.07 * price * (1.0 - price)


def num(v):
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def clip(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def quote(v):
    """A tradable quote, or None.

    The API reports a side with no resting orders with the boundary value
    0.0000 (and the opposite side with 1.0000): the order book of such a market
    is empty — "A market with no resting orders returns empty yes_dollars and
    no_dollars arrays" (https://docs.kalshi.com/getting_started/orderbook_responses).
    $0.00 and $1.00 are therefore "no quote", not a price you can trade at.
    Treating them as quotes made the model price a YES entry at $0.00 and then
    divide by a zero cost (ZeroDivisionError), and it reported a 0c spread for a
    market with no orders at all.
    """
    if v is None:
        return None
    return v if 0.0 < v < 1.0 else None


def microprice(bid, ask, size_at_bid, size_at_ask):
    """Depth-weighted mid. Inputs are official; the formula is this project's."""
    if bid is None or ask is None:
        return None
    sb, sa = num(size_at_bid), num(size_at_ask)
    if sb is None or sa is None or sb + sa <= 0:
        return (bid + ask) / 2
    return (bid * sa + ask * sb) / (sa + sb)


def series_mult(series_ticker: str, model: dict) -> dict:
    t = str(series_ticker or "").upper()
    table = (((model.get("fees") or {}).get("series_multipliers") or {}).get("table")) or {}
    row = table.get(t)
    d = (model.get("fees") or {}).get("defaults") or {"M_taker": 1, "M_maker": 0}
    if row:
        return {"taker": row["taker"], "maker": row["maker"], "listed": True}
    return {"taker": d["M_taker"], "maker": d["M_maker"], "listed": False}


def score(market: dict, model: dict, book: dict | None, ctx: dict) -> dict:
    """Return the full audit trail for one market. Mirrors KDLIVE.score() exactly."""
    p = model["parameters"]
    # A quote of exactly $0.00 or exactly $1.00 is the API's "nothing resting on
    # that side" sentinel, not a tradable price: the order book of such a market
    # is empty (https://docs.kalshi.com/getting_started/orderbook_responses).
    bid = quote(num(market.get("yes_bid_dollars", market.get("bid"))))
    ask = quote(num(market.get("yes_ask_dollars", market.get("ask"))))
    last = num(market.get("last_price_dollars", market.get("last")))
    if last is not None and last <= 0.0:
        last = None                      # a $0.00 last print means "no trade"
    sb = num(book.get("depth_at_bid")) if book else num(market.get("yes_bid_size_fp"))
    sa = num(book.get("depth_at_ask")) if book else num(market.get("yes_ask_size_fp"))
    micro = microprice(bid, ask, sb, sa)
    mid = (bid + ask) / 2 if (bid is not None and ask is not None) else last
    mult = series_mult(ctx.get("series_ticker"), model)

    reasons: list[str] = []
    if mid is None:
        return {"ticker": market.get("ticker"), "eligible": False, "reasons": ["no quoted price at all"]}
    w = p["weights"]
    q = w["mid"] * mid + w["last"] * last
    if micro is None:
        q = (w["mid"] + w["micro"]) * mid + w["last"] * last
        reasons.append("no order-book depth: micro weight folded into mid")
    else:
        q += w["micro"] * micro
    mom = num(ctx.get("momentum_dollars"))
    trend = p.get("trend") or {}
    if mom is not None and trend.get("reference_move_dollars"):
        q += trend["weight_dollars"] * clip(mom / trend["reference_move_dollars"], -1.0, 1.0)
    lo, hi = p["clip_q"]
    q = clip(q, lo, hi)

    f = p["filters"]
    spread = (ask - bid) if (bid is not None and ask is not None) else None
    # Depth is only a fact when the data source actually carried it. An absent field is
    # unknown, not zero: gating on "0 contracts" would silently reject a market for a
    # limitation of the caller's data rather than of the market.
    depth_known = sb is not None or sa is not None
    depth = (sb or 0) + (sa or 0) if depth_known else None
    vol24 = num(market.get("volume_24h_fp"))
    close_time = market.get("close_time")
    ttc_h = None
    if close_time:
        try:
            t = datetime_ms(close_time)
            ttc_h = (t - ctx["now_ms"]) / 3600000.0
        except ValueError:
            ttc_h = None

    # A quoted level of exactly 0.00 (or a NO-side 1.00, i.e. a YES bid of 0.00) is what
    # GET /markets returns for a market with no resting order on that side — observed on
    # 127 of 387 open in-scope markets in the 2026-11-20T15:19Z snapshot, e.g.
    # KXAAAGASD-26NOV21-3.7300 with yes_bid = yes_ask = last = "0.0000". Paying $0.00 for a
    # contract cannot happen, so such a side is not buyable: it is skipped here instead of
    # producing cost = 0 and a ZeroDivisionError that aborted the whole scan. The side is
    # never silently repriced; when neither side is buyable the market reports
    # "no buyable side" below, exactly as a market with no quotes does.
    # Field types per https://docs.kalshi.com/api-reference/market/get-markets
    sides = []
    if ask is not None and 0.0 < ask < 1.0:
        fee = taker_fee_unit(ask, mult["taker"])
        cost = ask + fee
        sides.append({"side": "YES", "entry": ask, "fee_unit": fee, "cost": cost, "ev": q - cost, "roi": (q - cost) / cost})
    if bid is not None and 0.0 < (1.0 - bid) < 1.0:
        pno = 1 - bid
        fee = taker_fee_unit(pno, mult["taker"])
        cost = pno + fee
        sides.append({"side": "NO", "entry": pno, "fee_unit": fee, "cost": cost, "ev": 1 - q - cost, "roi": (1 - q - cost) / cost})
    if not sides and (ask is not None or bid is not None):
        reasons.append("quoted at a degenerate 0.00/1.00 level: no price to buy, so no entry is priced")
    best = sorted(sides, key=lambda s: -s["roi"])[0] if sides else None

    fail = []
    if spread is None:
        fail.append("one-sided quote: spread unknown")
    elif spread > f["max_spread"]:
        fail.append(f"spread {spread * 100:.1f}c > {f['max_spread'] * 100:.0f}c cap")
    if depth is None:
        reasons.append("no order-book depth in this data source; depth gate not applied")
    elif depth < f["min_depth_contracts"]:
        fail.append(f"depth {depth:.0f} < {f['min_depth_contracts']:g} contracts at the touch")
    if vol24 is None or vol24 < f["min_volume_24h_contracts"]:
        fail.append(f"24h volume {vol24 if vol24 is not None else '—'} < {f['min_volume_24h_contracts']:g} contracts")
    if not best:
        fail.append("no buyable side")
    else:
        if best["entry"] < f["min_entry_price"]:
            fail.append(f"{best['side']} entry {best['entry'] * 100:.1f}c below {f['min_entry_price'] * 100:.0f}c floor")
        if best["entry"] > f["max_entry_price"]:
            fail.append(f"{best['side']} entry {best['entry'] * 100:.1f}c above {f['max_entry_price'] * 100:.0f}c ceiling")
        if best["roi"] <= f["min_net_roi"]:
            fail.append(f"net ROI {best['roi'] * 100:.2f}% not above {f['min_net_roi'] * 100:.0f}% floor")
    if ttc_h is None:
        fail.append("no close_time: cannot tell when it resolves")
    elif ttc_h <= 0:
        fail.append("already past close_time")
    elif ttc_h < f["min_ttc_hours"]:
        fail.append(f"closes in {ttc_h * 60:.0f} min < {f['min_ttc_hours'] * 60:g} min floor")
    elif ttc_h > f["max_ttc_hours"]:
        fail.append(f"closes in {ttc_h / 24:.0f} d > {f['max_ttc_hours'] / 24:g} d horizon")
    if f.get("require_seed_category") and market.get("category_basis") != "seed":
        fail.append("topic not confirmed by the fee schedule (keyword match only)")

    volume_fp = num(market.get("volume_fp"))
    return {
        "ticker": market.get("ticker"),
        "eligible": not fail,
        "fails": fail,
        "reasons": reasons,
        "q": q, "mid": mid, "micro": micro, "last": last, "bid": bid, "ask": ask,
        "spread": spread, "depth": depth, "vol24": vol24, "ttc_hours": ttc_h,
        "momentum": mom, "series_ticker": ctx.get("series_ticker"),
        "fee_multiplier": mult, "entry": best, "score": best["roi"] if best else None,
        "dollars_traded_estimate": volume_fp * last if (volume_fp is not None and last is not None) else None,
    }


def datetime_ms(iso: str) -> int:
    """Epoch ms for the API's ISO-8601 'Z' timestamps, without a tz database."""
    iso = iso.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z?$", iso)
    if not m:
        raise ValueError(f"unparsable timestamp {iso!r}")
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or "0"
    days = days_from_civil(y, mo, d)
    ms = ((days * 86400 + h * 3600 + mi * 60 + s) * 1000) + int(round(float("0." + frac) * 1000))
    return ms


def days_from_civil(y: int, m: int, d: int) -> int:
    """Howard Hinnant's civil-from-days, days since 1970-01-01. No dependencies."""
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def detect_swings(observations: list[dict], threshold: float) -> list[dict]:
    """|last - previous last| >= threshold, either direction. Mirrors KDLIVE.detectSwings()."""
    out, prev = [], None
    for o in observations:
        cur = {"t": o.get("t"), "v": num(o.get("last", o.get("last_price_dollars")))}
        if cur["v"] is None or not cur["t"]:
            prev = cur
            continue
        if prev and prev["v"] is not None:
            delta = cur["v"] - prev["v"]
            if abs(delta) + 1e-12 >= threshold:
                out.append({
                    "from": prev["v"], "to": cur["v"], "delta": delta,
                    "direction": "up" if delta > 0 else "down",
                    "cents": round(abs(delta) * 1000) / 10,
                    "t": cur["t"], "previous_t": prev["t"],
                    "volume_fp": num(o.get("volume_fp")),
                })
        prev = cur
    return out


def catalyst_links(market: dict) -> list[dict]:
    """URLs that appear literally in the market's own official text fields.

    GET /markets has no news/URL field (see the response schema at
    https://docs.kalshi.com/api-reference/market/get-markets), so anything shown here is
    copied out of the record verbatim and is labelled "the source this market settles on"
    — never "the news that moved it".
    """
    found: dict[str, str] = {}
    for k in TEXT_FIELDS:
        v = market.get(k)
        if not isinstance(v, str):
            continue
        for raw in URL_RE.findall(v):
            url = raw.rstrip(".,;:")
            found.setdefault(url, k)
    return [{"url": u, "field": k} for u, k in found.items()]
