#!/usr/bin/env python3
"""Kalshi demo collector + trade executor (no secrets in repo).

Reads credentials ONLY from environment variables:
  KALSHI_KEY_ID, KALSHI_PRIVATE_KEY_PATH (PEM file path)
Never commit keys. Public market-data endpoints need no auth.

Usage:
  python3 scripts/kalshi_client.py scan            # highest-dollar live events in 5 categories (public)
  python3 scripts/kalshi_client.py watch TICKER    # poll a market until resolved (result yes/no)
  python3 scripts/kalshi_client.py orderbook TICKER
  python3 scripts/kalshi_client.py balance         # requires auth env vars
  python3 scripts/kalshi_client.py buy TICKER YES 10 0.55   # requires auth; demo only
  python3 scripts/kalshi_client.py sell TICKER YES 10 0.55  # requires auth; demo only

Docs: https://docs.kalshi.com/getting_started/demo_env
      https://docs.kalshi.com/getting_started/api_keys
      https://docs.kalshi.com/getting_started/rate_limits
"""
import base64, datetime, json, os, sys, time
from decimal import Decimal

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

BASE = os.environ.get("KALSHI_BASE", "https://external-api.demo.kalshi.co/trade-api/v2")
CATEGORIES = {
    "gas": ["gas", "gasoline", "oil", "energy"],
    "elections": ["election", "president", "senate", "house", "vote"],
    "culture": ["culture", "movie", "oscar", "grammy", "music", "entertainment"],
    "crypto": ["crypto", "bitcoin", "btc", "ethereum", "eth"],
    "golf": ["golf", "pga", "masters", "ryder"],
}

def pub(path, params=None):
    r = requests.get(BASE + path, params=params or {}, timeout=20)
    r.raise_for_status()
    return r.json()

def sign_headers(method, path):
    kid = os.environ["KALSHI_KEY_ID"]
    pem_path = os.environ["KALSHI_PRIVATE_KEY_PATH"]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = serialization.load_pem_private_key(open(pem_path, "rb").read(), password=None)
    ts = str(int(time.time() * 1000))
    msg = (ts + method + path.split("?")[0]).encode()
    if isinstance(key, Ed25519PrivateKey):
        sig = key.sign(msg)
    else:
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
    return {"KALSHI-ACCESS-KEY": kid, "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode()}

def auth(path, method="GET", body=None):
    h = sign_headers(method, path)
    r = requests.request(method, BASE + path, headers=h, json=body, timeout=20)
    r.raise_for_status()
    return r.json()

def notional(m):
    try:
        return Decimal(m.get("volume_fp", "0")) * Decimal(m.get("last_price_dollars", "0"))
    except Exception:
        return Decimal("0")

def scan():
    series = pub("/series", {"limit": 1000}).get("series", [])
    print(f"series returned: {len(series)}")
    buckets = {k: [] for k in CATEGORIES}
    for s in series:
        hay = ((s.get("ticker") or "") + " " + (s.get("title") or "") + " " + (s.get("category") or "")).lower()
        for cat, kws in CATEGORIES.items():
            if any(k in hay for k in kws):
                buckets[cat].append(s.get("ticker"))
    for cat, tickers in buckets.items():
        print(f"\n== {cat}: {len(tickers)} series ==")
        for t in tickers[:20]:
            print(" ", t)
    # highest-dollar open markets per category
    markets = []
    cursor = ""
    while True:
        p = {"status": "open", "limit": 200}
        if cursor: p["cursor"] = cursor
        d = pub("/markets", p)
        markets += d.get("markets", [])
        cursor = d.get("cursor", "")
        if not cursor or len(markets) > 2000: break
    print(f"\nopen markets scanned: {len(markets)}")
    for cat, tickers in buckets.items():
        tset = set(tickers)
        ms = [m for m in markets if m.get("series_ticker") in tset]
        ms.sort(key=notional, reverse=True)
        print(f"\n-- {cat} top by notional (volume × last price) --")
        for m in ms[:5]:
            print(f"  {m['ticker']} | {m.get('title','')[:70]} | vol={m.get('volume_fp')} last={m.get('last_price_dollars')} notional≈${notional(m):,.2f} status={m.get('status')} result={m.get('result')!r}")

def watch(ticker):
    print(f"watching {ticker} (Ctrl+C to stop). Resolved when result in yes/no.")
    while True:
        m = pub(f"/markets/{ticker}").get("market", {})
        print(datetime.datetime.utcnow().isoformat(), "last=", m.get("last_price_dollars"),
              "bid=", m.get("yes_bid_dollars"), "ask=", m.get("yes_ask_dollars"),
              "vol=", m.get("volume_fp"), "status=", m.get("status"), "result=", m.get("result") or "(pending)")
        if m.get("result") in ("yes", "no"):
            print("RESOLVED:", m["result"]); return
        time.sleep(15)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan": scan()
    elif cmd == "watch": watch(sys.argv[2])
    elif cmd == "orderbook": print(json.dumps(pub(f"/markets/{sys.argv[2]}/orderbook", {"depth": 10}), indent=1))
    elif cmd == "balance": print(json.dumps(auth("/portfolio/balance"), indent=1))
    elif cmd in ("buy", "sell"):
        _, ticker, side, count, price = sys.argv
        body = {"ticker": ticker, "side": side.lower(), "count": int(count),
                "type": "limit", "yes_price_dollars": price if side.lower() == "yes" else None,
                "no_price_dollars": price if side.lower() == "no" else None}
        print(json.dumps(auth("/portfolio/orders", "POST", body), indent=1))
    else: sys.exit("unknown command")
