#!/usr/bin/env python3
"""Kalshi demo tracker / trader / analyzer (headless companion to the static site).

Uses only the standard library + `cryptography` (for Ed25519/RSA signing) if available.
Keys come from env vars — never hardcode or commit them:
  KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH (PEM file), KALSHI_BASE_URL (default demo).

Examples:
  KALSHI_API_KEY_ID=... KALSHI_PRIVATE_KEY_PATH=./demo.key python3 scripts/kalshi_tracker.py --rank
  python3 scripts/kalshi_tracker.py --track --interval 60 --out data/tracked.json
  KALSHI_API_KEY_ID=... KALSHI_PRIVATE_KEY_PATH=./demo.key python3 scripts/kalshi_tracker.py --balance
  KALSHI_API_KEY_ID=... KALSHI_PRIVATE_KEY_PATH=./demo.key python3 scripts/kalshi_tracker.py --analyze
  KALSHI_API_KEY_ID=... KALSHI_PRIVATE_KEY_PATH=./demo.key python3 scripts/kalshi_tracker.py --trade --ticker KXBTC-... --side yes --action buy --count 1 --price 0.50

Official refs:
  Demo env: https://docs.kalshi.com/getting_started/demo_env
  Environments/signing: https://docs.kalshi.com/getting_started/api_environments
  Create order: https://docs.kalshi.com/getting_started/quick_start_create_order.md
"""
import argparse, base64, json, os, sys, time, urllib.parse, urllib.request, uuid
from datetime import datetime, timezone

DEMO_BASE = "https://external-api.demo.kalshi.co/trade-api/v2"
PROD_BASE = "https://external-api.kalshi.com/trade-api/v2"

CATEGORIES = {
    "gas": (["KXAAAGAS", "KXAAAGASM", "KXGAS"], ["gas price", "gasoline", "aaa gas"]),
    "elections": (["KXELECT", "KXGOV", "KXSENATE", "KXHOUSE", "KXPRES"], ["election", "governor", "senate", "congress", "midterm", "mayor", "president"]),
    "culture": (["KXOSCAR", "KXEMMY", "KXGRAMMY", "KXMOVIE", "KXBOXOFFICE", "KXENT"], ["oscar", "emmy", "grammy", "movie", "box office", "entertainment", "concert", "album"]),
    "crypto": (["KXBTC", "KXETH", "KXCRYPTO", "KXSOL", "KXXRP"], ["bitcoin", "crypto", "btc", "ethereum", "solana", "xrp"]),
    "golf": (["KXPGATOUR", "KXPGARYDER", "KXPGASOLHEIM", "KXGOLF", "KXMASTERS"], ["golf", "pga tour", "masters", "ryder cup", "solheim"]),
}

def classify(m):
    series = (m.get("series_ticker") or "").upper()
    ticker = (m.get("ticker") or "").upper()
    text = f"{ticker} {series} {m.get('title','')} {m.get('event_ticker','')}".lower()
    for cat, (prefixes, kws) in CATEGORIES.items():
        for p in prefixes:
            if series.startswith(p) or ticker.startswith(p):
                return cat
    for cat, (prefixes, kws) in CATEGORIES.items():
        for kw in kws:
            if kw in text:
                return cat
    return None

def num(v, default=0):
    try:
        return float(v) if v not in (None, "") else default
    except Exception:
        return default

def volume(m):
    return num(m.get("volume_fp", m.get("volume", 0)))

def get_json(base, path, params=None, headers=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def fetch_all_open(base, max_pages=10):
    out, cursor = [], ""
    for _ in range(max_pages):
        params = {"status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        d = get_json(base, "/markets", params)
        out.extend(d.get("markets", []))
        cursor = d.get("cursor") or ""
        if not cursor:
            break
    return out

def rank(markets):
    return sorted(markets, key=lambda m: (volume(m), num(m.get("open_interest_fp", m.get("open_interest", 0)))), reverse=True)

# --- auth ---
def load_key():
    kid = os.environ.get("KALSHI_API_KEY_ID", "")
    path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
    if not kid or not path:
        raise SystemExit("Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH env vars (demo key).")
    with open(path, "rb") as f:
        pem = f.read()
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
        key = serialization.load_pem_private_key(pem, password=None, backend=default_backend())
    except ImportError:
        raise SystemExit("Install cryptography: pip install cryptography")
    return kid, key, Ed25519PrivateKey, padding, hashes

def sign(kid, key, Ed25519PrivateKey, padding, hashes, method, path_no_query):
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method.upper()}{path_no_query}".encode()
    if isinstance(key, Ed25519PrivateKey):
        sig = key.sign(msg)
    else:
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
    return {"KALSHI-ACCESS-KEY": kid, "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts, "Content-Type": "application/json"}

def authed(base, kid, key, Ed25519PrivateKey, padding, hashes, method, path, body=None):
    h = sign(kid, key, Ed25519PrivateKey, padding, hashes, method, path.split("?")[0])
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=h, method=method.upper())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def analyze(fills, settlements):
    by_cat, by_side = {}, {}
    taker = maker = 0
    notional = 0.0
    for f in fills:
        cat = classify({"ticker": f.get("ticker", ""), "series_ticker": f.get("series_ticker", ""), "title": f.get("ticker", "")}) or "other"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        side = str(f.get("side", f.get("outcome_side", "unknown"))).lower()
        by_side[side] = by_side.get(side, 0) + 1
        if f.get("is_taker"):
            taker += 1
        else:
            maker += 1
        p = f.get("yes_price_fixed", None)
        p = float(p) if p is not None else (float(f.get("yes_price", 0)) / 100 if f.get("yes_price") is not None else 0)
        c = float(f.get("count_fp", f.get("count", 0)))
        notional += p * c
    wins = losses = 0
    pnl = 0
    for s in settlements:
        rev = int(s.get("revenue", 0)); cost = int(s.get("yes_total_cost", 0)) + int(s.get("no_total_cost", 0))
        d = rev - cost; pnl += d
        if d > 0: wins += 1
        elif d < 0: losses += 1
    return {"fills": len(fills), "notional": round(notional, 2), "taker": taker, "maker": maker,
            "by_category": by_cat, "by_side": by_side,
            "settled": len(settlements), "wins": wins, "losses": losses, "settlement_pnl_cents": pnl,
            "hints": ["Compare win rate by category before adding size.",
                       "High taker share = paying spread; prefer limit orders in wide markets.",
                       "Review avg entry vs settlement outcome per category."]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("KALSHI_BASE_URL", DEMO_BASE))
    ap.add_argument("--rank", action="store_true")
    ap.add_argument("--track", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--out", default="data/tracked.json")
    ap.add_argument("--balance", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--trade", action="store_true")
    ap.add_argument("--ticker", default="")
    ap.add_argument("--side", default="yes", choices=["yes", "no"])
    ap.add_argument("--action", default="buy", choices=["buy", "sell"])
    ap.add_argument("--count", default="1")
    ap.add_argument("--price", type=float, default=0.50)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    if args.rank:
        markets = [m for m in fetch_all_open(base) if classify(m)]
        top = rank(markets)[:25]
        for m in top:
            print(f"{m.get('ticker')}\t{classify(m)}\tvol={volume(m):.0f}\t{m.get('title','')[:80]}")
        print(f"\nTotal in-scope open markets: {len(markets)} (base={base})")

    if args.track:
        tracked = {}
        if os.path.exists(args.out):
            try:
                tracked = json.load(open(args.out))
            except Exception:
                tracked = {}
        while True:
            markets = [m for m in fetch_all_open(base) if classify(m)]
            for m in rank(markets)[:10]:
                t = m.get("ticker")
                if t not in tracked:
                    tracked[t] = {"ticker": t, "title": m.get("title", ""), "first_seen": datetime.now(timezone.utc).isoformat(),
                                  "last_price": m.get("last_price_dollars", m.get("last_price")), "status": m.get("status", ""), "result": m.get("result", "")}
            # check resolutions for tracked
            for t in list(tracked.keys()):
                try:
                    d = get_json(base, f"/markets/{urllib.parse.quote(t)}")
                    m = d.get("market", d)
                    tracked[t]["status"] = m.get("status", "")
                    tracked[t]["result"] = m.get("result", "")
                    if m.get("result") in ("yes", "no"):
                        tracked[t]["resolved_at"] = datetime.now(timezone.utc).isoformat()
                except Exception as e:
                    print(f"warn {t}: {e}", file=sys.stderr)
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
            json.dump(tracked, open(args.out, "w"), indent=2)
            print(f"[{datetime.now(timezone.utc).isoformat()}] tracked={len(tracked)} resolved={sum(1 for v in tracked.values() if v.get('result') in ('yes','no'))}")
            time.sleep(args.interval)

    if args.balance or args.analyze or args.trade:
        kid, key, Ed, pad, hashes = load_key()
        if args.balance:
            print(json.dumps(authed(base, kid, key, Ed, pad, hashes, "GET", "/portfolio/balance"), indent=2))
        if args.analyze:
            fills = authed(base, kid, key, Ed, pad, hashes, "GET", "/portfolio/fills?limit=200").get("fills", [])
            setts = authed(base, kid, key, Ed, pad, hashes, "GET", "/portfolio/settlements?limit=200").get("settlements", [])
            print(json.dumps(analyze(fills, setts), indent=2))
        if args.trade:
            if not args.ticker:
                raise SystemExit("--ticker required for --trade")
            body = {"ticker": args.ticker, "side": "bid" if args.action == "buy" else "ask",
                    "outcome_side": args.side, "count": str(args.count), "price": f"{args.price:.4f}",
                    "time_in_force": "good_till_canceled", "self_trade_prevention_type": "taker_at_cross",
                    "client_order_id": str(uuid.uuid4())}
            print(json.dumps(authed(base, kid, key, Ed, pad, hashes, "POST", "/portfolio/events/orders", body), indent=2))

if __name__ == "__main__":
    main()
