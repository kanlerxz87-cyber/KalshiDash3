#!/usr/bin/env python3
"""Kalshi demo trade executor and portfolio reader.

Reads credentials ONLY from environment variables. Nothing is ever written to
the repository, and the script refuses to run against production unless you
explicitly opt in.

    KALSHI_KEY_ID           the API key id
    KALSHI_PRIVATE_KEY_PATH path to the PEM private key (Ed25519 or RSA)
    KALSHI_BASE             optional, defaults to the demo Trade API root
    KALSHI_ALLOW_PRODUCTION optional, set to 1 to permit a non-demo base URL

Official sources
  Endpoints ....... https://docs.kalshi.com/getting_started/api_environments
  Signing ......... https://docs.kalshi.com/getting_started/api_keys
  Orders (V2) ..... https://docs.kalshi.com/api-reference/orders/create-order-v2
  Balance ......... https://docs.kalshi.com/api-reference/portfolio/get-balance
  Positions ....... https://docs.kalshi.com/api-reference/portfolio/get-positions
  Fills ........... https://docs.kalshi.com/api-reference/portfolio/get-fills
  Rate limits ..... https://docs.kalshi.com/getting_started/rate_limits

IMPORTANT — corrected behaviour
  The legacy /portfolio/orders write endpoints were removed by Kalshi and now
  return 410 Gone with code deprecated_v1_order_endpoint. This script posts to
  /portfolio/events/orders instead, with the V2 body shape:
      {ticker, side: "bid"|"ask", count, price, time_in_force,
       self_trade_prevention_type}
  `bid` buys YES, `ask` sells YES (equivalently buys NO). A 201 means the order
  was ACCEPTED, not that it is resting: check remaining_count.

Usage
  python3 scripts/kalshi_client.py balance
  python3 scripts/kalshi_client.py positions [--settled all]
  python3 scripts/kalshi_client.py fills
  python3 scripts/kalshi_client.py buy  TICKER 25 0.42        # buy YES
  python3 scripts/kalshi_client.py sell TICKER 25 0.42        # sell YES (buy NO)
  python3 scripts/kalshi_client.py cancel ORDER_ID
  python3 scripts/kalshi_client.py scan                        # public, no key
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

DEFAULT_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
TIF_VALUES = ("fill_or_kill", "good_till_canceled", "immediate_or_cancel")
STP_VALUES = ("taker_at_cross", "maker")


def base_url() -> str:
    base = os.environ.get("KALSHI_BASE", DEFAULT_BASE).rstrip("/")
    demo = "demo" in base or base.startswith("https://demo-api")
    if not demo and os.environ.get("KALSHI_ALLOW_PRODUCTION") != "1":
        sys.exit(
            "Refusing to run against a non-demo base URL.\n"
            f"  base = {base}\n"
            "This project is scoped to the demo environment "
            "(https://docs.kalshi.com/getting_started/demo_env).\n"
            "Set KALSHI_ALLOW_PRODUCTION=1 only if you really mean it."
        )
    return base


def load_key():
    """Load the private key. Kalshi accepts Ed25519 or RSA-PSS with SHA-256."""
    key_id = os.environ.get("KALSHI_KEY_ID")
    pem_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    if not key_id or not pem_path:
        sys.exit(
            "Missing credentials. Set KALSHI_KEY_ID and KALSHI_PRIVATE_KEY_PATH.\n"
            "Create demo keys at https://demo.kalshi.co/ -> Account Settings -> API Keys\n"
            "Docs: https://docs.kalshi.com/getting_started/api_keys"
        )
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        sys.exit("pip install cryptography")

    with open(pem_path, "rb") as fh:
        key = serialization.load_pem_private_key(fh.read(), password=None)
    return key_id, key


def sign(key_id: str, key, method: str, path: str) -> dict:
    """Build the three documented headers.

    The signed message is: timestamp + METHOD + path, where path is the full
    path from the API root and MUST exclude the query string.
    https://docs.kalshi.com/getting_started/api_keys
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    ts = str(int(time.time() * 1000))
    msg = (ts + method.upper() + path).encode("utf-8")
    if isinstance(key, Ed25519PrivateKey):
        sig = key.sign(msg)
    else:
        sig = key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
        "Content-Type": "application/json",
    }


def request(method: str, endpoint: str, body: dict | None = None, auth: bool = True,
            query: str = "") -> tuple[int, dict | str]:
    """Call an endpoint. `endpoint` excludes the /trade-api/v2 prefix."""
    base = base_url()
    full_path = urlparse(base).path + endpoint
    url = base + endpoint + (("?" + query) if query else "")
    headers = {"Accept": "application/json", "User-Agent": "KalshiDash3-executor/1.0"}
    if auth:
        key_id, key = load_key()
        headers.update(sign(key_id, key, method, full_path))
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or ""
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def money(txt) -> Decimal:
    try:
        return Decimal(str(txt))
    except (InvalidOperation, TypeError, ValueError):
        sys.exit(f"Not a valid decimal amount: {txt!r}")


def cmd_balance(_a):
    code, body = request("GET", "/portfolio/balance")
    if code != 200:
        return fail(code, body)
    print(f"balance_dollars  = {body.get('balance_dollars')}")
    print(f"portfolio_value  = {body.get('portfolio_value')} (cents: {body.get('portfolio_value')})")
    print(f"updated_ts       = {body.get('updated_ts')}")
    print(json.dumps(body, indent=2))
    return 0


def cmd_positions(a):
    code, body = request("GET", "/portfolio/positions", query=f"settlement_status={a.settled}&count_filter=position")
    if code != 200:
        return fail(code, body)
    rows = body.get("market_positions") or []
    print(f"{len(rows)} position(s), settlement_status={a.settled}")
    for p in rows:
        print(
            f"  {p.get('ticker'):<44} position_fp={p.get('position_fp'):>10} "
            f"realized_pnl={p.get('realized_pnl_dollars'):>9} fees_paid={p.get('fees_paid_dollars'):>8} "
            f"exposure={p.get('market_exposure_dollars')}"
        )
    return 0


def cmd_fills(a):
    code, body = request("GET", "/portfolio/fills", query=f"limit={a.limit}")
    if code != 200:
        return fail(code, body)
    fills = body.get("fills") or []
    print(f"{len(fills)} fill(s)")
    for f in fills:
        print(
            f"  {f.get('ticker'):<44} outcome={f.get('outcome_side')} book={f.get('book_side')} "
            f"count={f.get('count_fp')} yes_price={f.get('yes_price_dollars')} fee={f.get('fee_cost')}"
        )
    return 0


def place(side: str, ticker: str, count: str, price: str, tif: str, stp: str) -> int:
    if tif not in TIF_VALUES:
        sys.exit(f"time_in_force must be one of {TIF_VALUES}")
    if stp not in STP_VALUES:
        sys.exit(f"self_trade_prevention_type must be one of {STP_VALUES}")
    p = money(price)
    if not (Decimal("0") < p < Decimal("1")):
        sys.exit("price must be strictly between 0 and 1 dollar — a binary contract settles at $1 or $0")
    body = {
        "ticker": ticker,
        "side": side,
        "count": str(count),
        "price": f"{p:.4f}",
        "time_in_force": tif,
        "self_trade_prevention_type": stp,
    }
    code, resp = request("POST", "/portfolio/events/orders", body=body)
    if code != 201:
        return fail(code, resp)
    print("Order accepted (201). Accepted is not the same as resting:")
    print(f"  order_id        = {resp.get('order_id')}")
    print(f"  fill_count      = {resp.get('fill_count')}")
    print(f"  remaining_count = {resp.get('remaining_count')}")
    if str(resp.get("remaining_count")) in ("0", "0.00"):
        print("  -> nothing is resting; the order was fully filled or killed.")
    return 0


def cmd_buy(a):
    return place("bid", a.ticker, a.count, a.price, a.tif, a.stp)


def cmd_sell(a):
    return place("ask", a.ticker, a.count, a.price, a.tif, a.stp)


def cmd_cancel(a):
    code, resp = request("DELETE", f"/portfolio/events/orders/{a.order_id}")
    if code not in (200, 201):
        return fail(code, resp)
    print(json.dumps(resp, indent=2))
    print("Note: the documented cancel response returns order_id, client_order_id and reduced_by.")
    return 0


def cmd_scan(_a):
    """Public, credential-free scan limited to the five requested categories."""
    import collect  # sibling module
    payload = collect.build(include_orderbooks=2)
    print(json.dumps(payload["counts"], indent=2))
    return 0


def fail(code: int, body) -> int:
    print(f"HTTP {code}", file=sys.stderr)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        print(f"  code    = {err.get('code')}", file=sys.stderr)
        print(f"  message = {err.get('message')}", file=sys.stderr)
        if err.get("details"):
            print(f"  details = {err.get('details')}", file=sys.stderr)
        print(json.dumps(body, indent=2), file=sys.stderr)
    else:
        print(str(body)[:800], file=sys.stderr)
    if code == 410:
        print("\n410 Gone usually means a removed legacy endpoint. "
              "See https://docs.kalshi.com/api-reference/orders/create-order-v2", file=sys.stderr)
    if code == 429:
        print("\nRate limited. Documented behaviour: exponential backoff, no Retry-After header.",
              file=sys.stderr)
    if code == 401:
        print("\nUnauthorised. Check the key id, the signature algorithm for that key, and that the "
              "system clock is within 30 seconds of Kalshi's.", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Kalshi demo executor (demo-only by default).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("balance", help="GET /portfolio/balance").set_defaults(fn=cmd_balance)

    p = sub.add_parser("positions", help="GET /portfolio/positions")
    p.add_argument("--settled", default="all", choices=["unsettled", "settled", "all"])
    p.set_defaults(fn=cmd_positions)

    p = sub.add_parser("fills", help="GET /portfolio/fills")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(fn=cmd_fills)

    for name, fn in (("buy", cmd_buy), ("sell", cmd_sell)):
        p = sub.add_parser(name, help="POST /portfolio/events/orders")
        p.add_argument("ticker")
        p.add_argument("count")
        p.add_argument("price")
        p.add_argument("--tif", default="good_till_canceled", choices=TIF_VALUES)
        p.add_argument("--stp", default="taker_at_cross", choices=STP_VALUES)
        p.set_defaults(fn=fn)

    p = sub.add_parser("cancel", help="DELETE /portfolio/events/orders/{order_id}")
    p.add_argument("order_id")
    p.set_defaults(fn=cmd_cancel)

    sub.add_parser("scan", help="public 5-category scan, no credentials").set_defaults(fn=cmd_scan)

    a = ap.parse_args()
    try:
        return a.fn(a)
    except SystemExit:
        raise
    except Exception as e:  # network or library trouble
        print(f"ERROR {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
