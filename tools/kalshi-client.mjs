/**
 * kalshi-client.mjs — Kalshi Trade API v2 client (demo environment by default).
 *
 * EVERY fact encoded here was checked against the official Kalshi documentation
 * (docs.kalshi.com) and against live responses from the demo REST host on
 * 2026-11-20. Citations are inline; the full line-by-line source table lives in
 * verification/api-verification.md and docs are linked from data/sources.json.
 *
 * Verified facts encoded in this file
 * -----------------------------------
 * 1. Base URLs (docs: getting_started/api_environments, getting_started/demo_env)
 *      demo (recommended) https://external-api.demo.kalshi.co/trade-api/v2
 *      demo (also supported) https://demo-api.kalshi.co/trade-api/v2
 *      prod (recommended) https://external-api.kalshi.com/trade-api/v2
 * 2. Prices/quantities are fixed-point STRINGS (docs: getting_started/fixed_point_migration):
 *      *_dollars  -> dollar strings, up to 4 dp in responses (e.g. "0.1200")
 *      *_fp       -> contract-count strings, 2 dp (e.g. "13.00")
 *    Live confirmation 2026-11-20: GET /events returned volume_fp,
 *    open_interest_fp, last_price_dollars, yes_ask_dollars, price_ranges.
 * 3. Public market-data endpoints need no auth (docs: getting_started/quick_start_market_data).
 * 4. Orderbook returns bids only, ascending, best bid last (docs:
 *    getting_started/orderbook_responses + api-reference/market/get-multiple-market-orderbooks).
 *      YES bid at X  == NO ask at 1 - X
 *      NO  bid at Y  == YES ask at 1 - Y
 * 5. Orders are V2: POST /portfolio/events/orders, side bid|ask, and the legacy
 *    /portfolio/orders write endpoints return 410 Gone code deprecated_v1_order_endpoint
 *    (docs: api-reference/orders/create-order-v2).
 * 6. Direction: bid == yes, ask == no, always; a bid at p is matched by an ask at p,
 *    i.e. price is never transformed to 1-p (docs: getting_started/order_direction).
 * 7. Signing: headers KALSHI-ACCESS-KEY / KALSHI-ACCESS-SIGNATURE / KALSHI-ACCESS-TIMESTAMP,
 *    pre-sign text = timestamp + METHOD + path-without-query, RSA-PSS(SHA-256, salt=digest)
 *    or Ed25519, timestamp tolerance 30 s (docs: getting_started/api_keys).
 * 8. Candlesticks: period_interval in MINUTES, valid {1, 60, 1440}, start/end in seconds,
 *    max 5000 periods per request; sub-minute candles do NOT exist in the REST API
 *    (docs: api-reference/market/get-market-candlesticks).
 * 9. Event-level `category` is deprecated in favour of series-level categories
 *    (docs: api-reference/events/get-events -> EventData.category deprecated: true).
 *
 * This module is dependency-free (Node >= 20 global fetch, node:crypto).
 */

import crypto from "node:crypto";
import fs from "node:fs";

/* ------------------------------------------------------------------ *
 * Endpoints
 * ------------------------------------------------------------------ */

export const HOSTS = {
  demo: {
    rest: "https://external-api.demo.kalshi.co/trade-api/v2",
    restAlt: "https://demo-api.kalshi.co/trade-api/v2",
    ws: "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
    wsAlt: "wss://demo-api.kalshi.co/trade-api/ws/v2",
    site: "https://demo.kalshi.co/",
  },
  production: {
    rest: "https://external-api.kalshi.com/trade-api/v2",
    restAlt: "https://api.elections.kalshi.com/trade-api/v2",
    ws: "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
    wsAlt: "wss://api.elections.kalshi.com/trade-api/ws/v2",
    site: "https://kalshi.com/",
  },
};

/** Query paths, all relative to the base URL. Verified against docs/llms.txt. */
export const PATHS = {
  exchangeStatus: "/exchange/status",
  events: "/events",
  event: (ticker) => `/events/${encodeURIComponent(ticker)}`,
  markets: "/markets",
  market: (ticker) => `/markets/${encodeURIComponent(ticker)}`,
  orderbook: (ticker) => `/markets/${encodeURIComponent(ticker)}/orderbook`,
  orderbooks: "/markets/orderbooks", // GET ?tickers=a,b,c  (<=100 tickers)
  trades: "/markets/trades", // GET ?market_ticker=&limit=
  candlesticks: (series, ticker) =>
    `/series/${encodeURIComponent(series)}/markets/${encodeURIComponent(ticker)}/candlesticks`,
  series: "/series", // GET ?category=&include_volume=
  seriesOne: (ticker) => `/series/${encodeURIComponent(ticker)}`,
  // Authenticated (portfolio) — read scopes documented per endpoint.
  balance: "/portfolio/balance",
  positions: "/portfolio/positions",
  fills: "/portfolio/fills",
  orders: "/portfolio/orders",
  // Orders V2 write path. The legacy /portfolio/orders POST/DELETE is 410 Gone.
  createOrderV2: "/portfolio/events/orders",
  amendOrderV2: (id) => `/portfolio/events/orders/${encodeURIComponent(id)}/amend`,
  cancelOrderV2: (id) => `/portfolio/events/orders/${encodeURIComponent(id)}`,
};

/* ------------------------------------------------------------------ *
 * Fixed-point helpers
 * ------------------------------------------------------------------ */

/** Parse a `*_dollars` / `*_fp` string into a Number. Never throws; returns null for missing. */
export function fp(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Round to a fixed number of decimals without float dust. */
export function round(value, decimals = 4) {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  const f = 10 ** decimals;
  return Math.round((value + Number.EPSILON) * f) / f;
}

export function usd(value, decimals = 2) {
  const n = fp(value);
  return n === null ? null : round(n, decimals);
}

/**
 * Snap a price onto a market's valid price grid.
 * `price_ranges` is the source of truth: bands of {start, end, step}; any price on
 * the grid is valid, any off-grid price is rejected with 400 invalid_price.
 * (docs: getting_started/fixed_point_migration.md "Price Level Structures")
 */
export function snapToGrid(priceDollars, priceRanges) {
  const p = fp(priceDollars);
  if (p === null) return null;
  const bands = Array.isArray(priceRanges) ? priceRanges : [];
  for (const band of bands) {
    const start = fp(band.start);
    const end = fp(band.end);
    const step = fp(band.step);
    if (start === null || end === null || !step) continue;
    if (p >= start - 1e-9 && p <= end + 1e-9) {
      const snapped = Math.round((p - start) / step) * step + start;
      return round(Math.min(end, Math.max(start, snapped)), 4);
    }
  }
  // Outside every band: clamp into the nearest band edge on its grid.
  const first = bands[0];
  if (!first) return round(p, 4);
  const lo = fp(first.start) ?? 0;
  const last = bands[bands.length - 1];
  const hi = fp(last.end) ?? 1;
  const step = fp(last.step) ?? 0.01;
  const clamped = Math.min(hi, Math.max(lo, p));
  return round(Math.round((clamped - lo) / step) * step + lo, 4);
}

/** Validate that a price is exactly on some band's grid (used before order submission). */
export function isOnGrid(priceDollars, priceRanges, tol = 1e-9) {
  const p = fp(priceDollars);
  if (p === null) return false;
  for (const band of priceRanges || []) {
    const start = fp(band.start);
    const end = fp(band.end);
    const step = fp(band.step);
    if (start === null || end === null || !step) continue;
    if (p < start - tol || p > end + tol) continue;
    const k = (p - start) / step;
    if (Math.abs(k - Math.round(k)) < 1e-6) return true;
  }
  return false;
}

/* ------------------------------------------------------------------ *
 * Domain maths (all derived quantities state their formula)
 * ------------------------------------------------------------------ */

/** A binary contract pays $1.00 if it settles in its favour, $0.00 otherwise. */
export const NOTIONAL_PER_CONTRACT_USD = 1.0;

/** Open interest in dollars of guaranteed maximum payout: open_interest_fp x $1.00. */
export function openInterestUsd(market) {
  const oi = fp(market?.open_interest_fp);
  return oi === null ? null : round(oi * NOTIONAL_PER_CONTRACT_USD, 2);
}

/** Lifetime traded notional: volume_fp x $1.00 (contract count x face value). */
export function notionalVolumeUsd(market) {
  const v = fp(market?.volume_fp);
  return v === null ? null : round(v * NOTIONAL_PER_CONTRACT_USD, 2);
}

/** 24h traded notional: volume_24h_fp x $1.00. */
export function notionalVolume24hUsd(market) {
  const v = fp(market?.volume_24h_fp);
  return v === null ? null : round(v * NOTIONAL_PER_CONTRACT_USD, 2);
}

/**
 * Exact dollars that changed hands on the YES leg: sum(yes_price_dollars x count_fp).
 * Computed only from the trade prints actually fetched; never extrapolated.
 */
export function tradedDollarsFromTrades(trades) {
  let sum = 0;
  let counted = 0;
  for (const t of trades || []) {
    const price = fp(t.yes_price_dollars);
    const count = fp(t.count_fp);
    if (price === null || count === null) continue;
    sum += price * count;
    counted += 1;
  }
  return { dollars: round(sum, 2), tradesCounted: counted };
}

/** Mid price in YES dollars, from the reciprocal orderbook (best yes bid + best yes ask)/2. */
export function midPrice(yesBid, yesAsk) {
  const b = fp(yesBid);
  const a = fp(yesAsk);
  if (b === null || a === null) return b ?? a;
  return round((a + b) / 2, 4);
}

/**
 * General trading fee. Kalshi's published taker fee for a binary contract is
 * fee = 0.07 x C x P x (1-P) where C = contracts and P = price in dollars,
 * rounded up to the next cent; `series.fee_type`/`fee_multiplier` scale it.
 * Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf (see data/sources.json;
 * the fee schedule is also referenced from api-reference/market/get-series-list ->
 * `fee_type` "quadratic" = "General Trading Fees Table", `fee_multiplier` applied on top).
 * If the schedule cannot be re-verified, set FEE_MODEL_VERIFIED=false and the UI
 * shows the figure as an estimate.
 */
export const FEE_MODEL_VERIFIED = false; // flagged for review: PDF not fetched in-sandbox
export const TAKER_FEE_COEFFICIENT = 0.07;

export function takerFeeUsd(count, priceDollars, feeMultiplier = 1) {
  const c = fp(count);
  const p = fp(priceDollars);
  if (c === null || p === null) return null;
  const raw = TAKER_FEE_COEFFICIENT * c * p * (1 - p) * (feeMultiplier ?? 1);
  return round(Math.ceil(raw * 100) / 100, 2);
}

/** Break-even win probability for a YES buyer at price p, fees included. */
export function breakEvenProbability(priceDollars, feeMultiplier = 1) {
  const p = fp(priceDollars);
  if (p === null || p <= 0 || p >= 1) return null;
  // Cost per contract = p + fee_per_contract. fee_per_contract = 0.07*p*(1-p)*mult.
  const per = TAKER_FEE_COEFFICIENT * p * (1 - p) * (feeMultiplier ?? 1);
  const cost = p + per;
  if (cost >= 1) return null;
  return round(cost, 4);
}

/* ------------------------------------------------------------------ *
 * Orderbook shape
 * ------------------------------------------------------------------ */

/**
 * Normalise `{yes_dollars: [[price,count],...], no_dollars: [...]}` into a ladder.
 * Arrays arrive ascending by price, best bid last (docs: orderbook_responses).
 * YES asks are derived: a NO bid at y is a YES ask at 1 - y with identical size.
 */
export function normalizeOrderbook(orderbookFp) {
  const yesBids = toLevels(orderbookFp?.yes_dollars);
  const noBids = toLevels(orderbookFp?.no_dollars);
  const yesAsks = noBids
    .map((l) => ({ price: round(1 - l.price, 4), count: l.count }))
    .sort((a, b) => a.price - b.price);
  const noAsks = yesBids
    .map((l) => ({ price: round(1 - l.price, 4), count: l.count }))
    .sort((a, b) => a.price - b.price);
  const bestYesBid = yesBids.at(-1)?.price ?? null;
  const bestYesAsk = yesAsks[0]?.price ?? null;
  return {
    yes_bids: yesBids,
    no_bids: noBids,
    yes_asks: yesAsks, // derived (1 - NO bid), not returned by the API
    no_asks: noAsks, // derived (1 - YES bid)
    best_yes_bid: bestYesBid,
    best_yes_ask: bestYesAsk,
    best_no_bid: noBids.at(-1)?.price ?? null,
    best_no_ask: noAsks[0]?.price ?? null,
    spread: bestYesBid !== null && bestYesAsk !== null ? round(bestYesAsk - bestYesBid, 4) : null,
    // Liquidity: contracts resting at or better than touch, both directions.
    yes_bid_liquidity: round(sum(yesBids.map((l) => l.count)), 2),
    yes_ask_liquidity: round(sum(yesAsks.map((l) => l.count)), 2),
    total_book_contracts: round(
      sum(yesBids.map((l) => l.count)) + sum(noBids.map((l) => l.count)),
      2,
    ),
  };
}

function toLevels(arr) {
  if (!Array.isArray(arr)) return [];
  return arr
    .map((pair) => ({ price: fp(Array.isArray(pair) ? pair[0] : null), count: fp(Array.isArray(pair) ? pair[1] : null) }))
    .filter((l) => l.price !== null && l.count !== null);
}

function sum(arr) {
  return arr.reduce((acc, v) => acc + (Number.isFinite(v) ? v : 0), 0);
}

/* ------------------------------------------------------------------ *
 * Topic classification
 * ------------------------------------------------------------------ */

/**
 * The five topics requested for this dashboard. Kalshi has no "topic" field:
 * an event carries a (deprecated) `category`, and a series carries `category`
 * plus `categories[]`. So topic membership here is DERIVED from title/ticker/
 * keyword matching, and every match records its evidence for audit.
 */
export const TOPICS = [
  {
    id: "gas-prices",
    label: "Gas prices",
    seriesHints: [/GAS/, /FUEL/, /OIL/, /WTI/, /BRENT/, /DIESEL/],
    keywords: [
      "gas price", "gas prices", "average gas price", "regular gasoline", "diesel price",
      "gasbuddy", "aaa national average", "crude oil", "wti", "brent", "fuel price", "pump price",
    ],
    exclude: ["gas station ownership", "gas tax legislation"],
  },
  {
    id: "elections",
    label: "Elections",
    seriesHints: [/PRES/, /SENATE/, /HOUSE/, /GOV/, /MAYOR/, /NOM/, /SPEAKER/, /ELECT/, /Poll/, /APPROV/],
    keywords: [
      "president", "presidential", "nominee", "nomination", "election", "senate", "house majority",
      "governor", "mayor", "speaker of the house", "approval rating", "midterm", "popular vote",
      "electoral college", "primaries", "general election", "by-election",
    ],
    exclude: [],
  },
  {
    id: "culture",
    label: "Culture",
    seriesHints: [/OSCARS/, /GRAMMY/, /EMMY/, /BOXOFFICE/, /TIMEPERSON/, /NOBEL/, /ALBUM/, /MOVIE/, /FILM/, /ENT/],
    keywords: [
      "oscar", "academy award", "grammy", "emmy", "box office", "time person", "nobel",
      "album", "movie", "film", "netflix", "spotify", "billboard", "golden globe", "best picture",
      "culture", "celebrity", "royal", "eurovision", "met gala", "pulitzer",
    ],
    exclude: [],
  },
  {
    id: "crypto",
    label: "Crypto",
    seriesHints: [/BTC/, /ETH/, /SOL/, /XRP/, /DOGE/, /CRYPTO/, /HYPE/, /AVAX/, /CHAIN/],
    keywords: [
      "bitcoin", "ethereum", "solana", "ripple", "dogecoin", "crypto", "binance", "coinbase",
      "etf", "blockchain", "tether", "stablecoin", "hyperliquid", "sat",
    ],
    exclude: ["mining legality"],
  },
  {
    id: "golf",
    label: "Golf",
    seriesHints: [/GOLF/, /PGA/, /LIV/, /MASTERS/, /THEOPEN/, /USOPEN/, /PGA Championship/, /RYDER/, /TOUR/, /TOC/, /RSM/, /WGC/, /DPW/],
    keywords: [
      "golf", "pga", "liv golf", "masters", "us open", "the open championship", "british open",
      "ryder cup", "tour championship", "fedex cup", "lpga", "deere", "augusta", "golfer",
      "hole-in-one", "major champion",
    ],
    exclude: [],
  },
];

/**
 * Classify one event into a topic. Returns null when nothing matches so unrelated
 * markets never leak into a topic page.
 */
export function classifyEvent(event, topics = TOPICS) {
  const haystack = [event.title, event.sub_title, event.series_ticker, event.category]
    .filter(Boolean)
    .join(" ");
  const low = haystack.toLowerCase();
  for (const t of topics) {
    for (const ex of t.exclude) if (low.includes(ex.toLowerCase())) continue;
    const hits = [];
    for (const re of t.seriesHints) if (re.test(event.series_ticker || "")) hits.push(`series_ticker ~ ${re}`);
    for (const k of t.keywords) if (low.includes(k.toLowerCase())) hits.push(`text ~ "${k}"`);
    if (hits.length) return { topic: t.id, label: t.label, evidence: hits.slice(0, 4) };
  }
  return null;
}

/* ------------------------------------------------------------------ *
 * Resolution / settlement reading
 * ------------------------------------------------------------------ */

/**
 * A market's settlement is read from `status` + `result`.
 * Live check 2026-11-20: active markets return `result: ""`; settled markets
 * return "yes" | "no" (docs: getting_started/market_settlement, api-reference/market/get-market).
 * We never infer a result: unknown stays null and is displayed as "unverified".
 */
export function readResolution(market) {
  const status = market?.status ?? null;
  const raw = (market?.result ?? "").toString().trim().toLowerCase();
  let outcome = null;
  if (raw === "yes") outcome = "YES";
  else if (raw === "no") outcome = "NO";
  else if (raw !== "") outcome = `UNKNOWN(${market.result})`;
  return {
    status,
    resolved: status === "settled",
    outcome,
    raw_result: market?.result ?? "",
    close_time: market?.close_time ?? null,
    settle_time: market?.settlement_at ?? market?.settle_time ?? null, // absent in live demo payload -> flagged
  };
}

/* ------------------------------------------------------------------ *
 * HTTP
 * ------------------------------------------------------------------ */

export class KalshiClient {
  /**
   * @param {{env?: 'demo'|'production', base?: string, timeoutMs?: number, retries?: number,
   *          logger?: (msg: string) => void}} opts
   */
  constructor(opts = {}) {
    const host = HOSTS[opts.env || "demo"];
    this.base = (opts.base || host.rest).replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs ?? 20_000;
    this.retries = opts.retries ?? 3;
    this.logger = opts.logger || (() => {});
    this.requests = 0;
    this.retries_used = 0;
    this.status_log = [];
  }

  /** Path from the API root, e.g. /trade-api/v2/portfolio/balance — the signed path. */
  signedPath(pathWithQuery) {
    const withoutQuery = pathWithQuery.split("?")[0];
    const url = new URL(this.base + withoutQuery);
    return url.pathname;
  }

  /**
   * GET/POST with 429/5xx backoff. Unauthenticated public requests are subject to
   * separate, undocumented numeric limits, so callers throttle (docs: rate_limits.md
   * "Unauthenticated requests").
   */
  async request(method, pathWithQuery, body, auth) {
    const url = this.base + pathWithQuery;
    let lastErr = null;
    for (let attempt = 0; attempt <= this.retries; attempt += 1) {
      const headers = { Accept: "application/json" };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (auth) Object.assign(headers, auth.headers);
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      this.requests += 1;
      const started = Date.now();
      try {
        const res = await fetch(url, {
          method,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        });
        clearTimeout(timer);
        const text = await res.text();
        let json = null;
        try {
          json = text ? JSON.parse(text) : null;
        } catch {
          json = null;
        }
        this.status_log.push({
          method,
          path: pathWithQuery.split("?")[0],
          status: res.status,
          ms: Date.now() - started,
          at: new Date().toISOString(),
        });
        if (res.ok) return { status: res.status, data: json ?? {}, headers: headerMap(res.headers) };
        if ((res.status === 429 || res.status >= 500) && attempt < this.retries) {
          this.retries_used += 1;
          const wait = backoffMs(attempt, res.status === 429 ? 1500 : 700);
          this.logger(`${method} ${pathWithQuery} -> ${res.status}; retry in ${wait}ms`);
          await sleep(wait);
          continue;
        }
        throw new ApiError(res.status, json, url);
      } catch (err) {
        clearTimeout(timer);
        if (err instanceof ApiError) throw err;
        lastErr = err;
        if (attempt < this.retries) {
          this.retries_used += 1;
          const wait = backoffMs(attempt, 800);
          this.logger(`${method} ${pathWithQuery} -> ${err.name || "Error"}: ${err.message}; retry in ${wait}ms`);
          await sleep(wait);
          continue;
        }
      }
    }
    throw new ApiError(0, { code: "network_error", message: String(lastErr?.message || lastErr) }, url);
  }

  get(pathWithQuery) {
    return this.request("GET", pathWithQuery);
  }

  getAuth(pathWithQuery, key) {
    return this.request("GET", pathWithQuery, undefined, authFor(key, "GET", this.signedPath(pathWithQuery)));
  }

  postAuth(pathWithQuery, body, key) {
    return this.request("POST", pathWithQuery, body, authFor(key, "POST", this.signedPath(pathWithQuery)));
  }

  deleteAuth(pathWithQuery, key) {
    return this.request("DELETE", pathWithQuery, undefined, authFor(key, "DELETE", this.signedPath(pathWithQuery)));
  }

  /* ----- public market data ----- */

  async exchangeStatus() {
    return (await this.get(PATHS.exchangeStatus)).data;
  }

  /** GET /events — limit max 200, cursor pagination (docs: api-reference/events/get-events). */
  async events(params = {}) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      q.set(k, String(v));
    }
    if (!q.has("limit")) q.set("limit", "200");
    return (await this.get(`${PATHS.events}?${q}`)).data;
  }

  /** Page every event matching `params`; stops at `maxPages` or empty cursor. */
  async pageEvents(params = {}, maxPages = 10) {
    const out = [];
    let cursor = "";
    let pages = 0;
    for (;;) {
      const data = await this.events({ ...params, ...(cursor ? { cursor } : {}) });
      const batch = data.events || [];
      out.push(...batch);
      pages += 1;
      cursor = data.cursor || "";
      if (!cursor || batch.length === 0 || pages >= maxPages) break;
      await sleep(250);
    }
    return { events: out, pages };
  }

  async markets(params = {}) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      q.set(k, String(v));
    }
    if (!q.has("limit")) q.set("limit", "200");
    return (await this.get(`${PATHS.markets}?${q}`)).data;
  }

  /** GET /markets/orderbooks?tickers=... — max 100 tickers (docs: get-multiple-market-orderbooks). */
  async orderbooks(tickers) {
    const chunks = chunk(tickers.filter(Boolean), 100);
    const out = {};
    for (const list of chunks) {
      const q = new URLSearchParams();
      q.set("tickers", list.join(","));
      const data = (await this.get(`${PATHS.orderbooks}?${q}`)).data;
      for (const ob of data.orderbooks || []) out[ob.ticker] = normalizeOrderbook(ob.orderbook_fp);
      await sleep(250);
    }
    return out;
  }

  /** GET /markets/trades?market_ticker=&limit= (limit max 1000 per docs: api-reference/market/get-trades) */
  async trades(marketTicker, limit = 100, extra = {}) {
    const q = new URLSearchParams({ market_ticker: marketTicker, limit: String(limit), ...extra });
    return (await this.get(`${PATHS.trades}?${q}`)).data;
  }

  /**
   * GET /series/{series}/markets/{ticker}/candlesticks
   * period_interval: 1 minute | 60 minutes | 1440 minutes (no seconds option exists).
   */
  async candlesticks(seriesTicker, ticker, startTs, endTs, periodInterval = 1) {
    const q = new URLSearchParams({
      start_ts: String(startTs),
      end_ts: String(endTs),
      period_interval: String(periodInterval),
    });
    const data = (await this.get(`${PATHS.candlesticks(seriesTicker, ticker)}?${q}`)).data;
    return data.candlesticks || [];
  }

  async seriesList(params = {}) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) q.set(k, String(v));
    return (await this.get(`${PATHS.series}?${q}`)).data;
  }

  /* ----- authenticated portfolio ----- */

  balance(key) {
    return this.getAuth(PATHS.balance, key).then((r) => r.data);
  }
  positions(key, params = {}) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    const qs = q.toString();
    return this.getAuth(PATHS.positions + (qs ? `?${qs}` : ""), key).then((r) => r.data);
  }
  fills(key, params = {}) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
    const qs = q.toString();
    return this.getAuth(PATHS.fills + (qs ? `?${qs}` : ""), key).then((r) => r.data);
  }
  orders(key, params = {}) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v) q.set(k, String(v));
    const qs = q.toString();
    return this.getAuth(PATHS.orders + (qs ? `?${qs}` : ""), key).then((r) => r.data);
  }

  /**
   * Create Order (V2). Required by the API: ticker, side, count, price,
   * time_in_force, self_trade_prevention_type (docs: create-order-v2 OpenAPI).
   * `side`: bid = long YES, ask = long NO at that same YES-leg price.
   */
  async createOrder(key, order) {
    const body = {
      ticker: order.ticker,
      side: order.side,
      count: order.count,
      price: order.price,
      time_in_force: order.time_in_force || "good_till_canceled",
      self_trade_prevention_type: order.self_trade_prevention_type || "taker_at_cross",
    };
    if (!["bid", "ask"].includes(body.side)) throw new Error("side must be 'bid' or 'ask'");
    if (!["fill_or_kill", "good_till_canceled", "immediate_or_cancel"].includes(body.time_in_force)) {
      throw new Error("time_in_force must be one of fill_or_kill|good_till_canceled|immediate_or_cancel ('GTT' is not valid)");
    }
    if (order.reduce_only && body.time_in_force !== "immediate_or_cancel") {
      // reduce_only is rejected unless IOC (docs: create-order-v2 reduce_only description)
      throw new Error("reduce_only requires time_in_force=immediate_or_cancel");
    }
    for (const k of ["client_order_id", "post_only", "reduce_only", "cancel_order_on_pause", "expiration_time", "subaccount", "order_group_id", "exchange_index"]) {
      if (order[k] !== undefined && order[k] !== null) body[k] = order[k];
    }
    return this.postAuth(PATHS.createOrderV2, body, key);
  }

  cancelOrder(key, orderId) {
    return this.request("DELETE", PATHS.cancelOrderV2(orderId), undefined, authFor(key, "DELETE", this.signedPath(PATHS.cancelOrderV2(orderId))));
  }

  amendOrder(key, orderId, changes) {
    return this.request(
      "POST",
      PATHS.amendOrderV2(orderId),
      changes,
      authFor(key, "POST", this.signedPath(PATHS.amendOrderV2(orderId))),
    );
  }
}

/* ------------------------------------------------------------------ *
 * Auth (docs: getting_started/api_keys.md)
 * ------------------------------------------------------------------ */

/** Pre-sign text: timestamp + METHOD + path (no query, no host). */
export function presignText(timestampMs, method, pathFromRoot) {
  return `${timestampMs}${method}${pathFromRoot}`;
}

/**
 * Sign with Ed25519 (recommended for new keys) or RSA-2048 RSA-PSS/SHA-256 with
 * salt length = digest length, matching the documented Python sample.
 */
export function signPresign(pem, presign) {
  const key = crypto.createPrivateKey(pem);
  if (key.asymmetricKeyType === "ed25519") {
    return crypto.sign(null, Buffer.from(presign, "utf8"), key).toString("base64");
  }
  if (key.asymmetricKeyType === "rsa") {
    return crypto
      .sign("sha256", Buffer.from(presign, "utf8"), {
        key,
        padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
        saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
      })
      .toString("base64");
  }
  throw new Error(`unsupported key type ${key.asymmetricKeyType} (expected ed25519 or rsa)`);
}

/** Build the three KALSHI-ACCESS-* headers for one request. */
export function authFor(key, method, pathFromRoot, timestampMs = Date.now()) {
  const ts = String(Math.floor(timestampMs));
  const signature = signPresign(key.privateKeyPem, presignText(ts, method, pathFromRoot));
  return {
    headers: {
      "KALSHI-ACCESS-KEY": key.keyId,
      "KALSHI-ACCESS-SIGNATURE": signature,
      "KALSHI-ACCESS-TIMESTAMP": ts,
    },
    presign: presignText(ts, method, pathFromRoot),
  };
}

/** Read credentials from the environment; returns null when unconfigured. */
export function keyFromEnv(env = process.env) {
  const keyId = env.KALSHI_API_KEY_ID;
  let privateKeyPem = env.KALSHI_PRIVATE_KEY_PEM || null;
  if (!privateKeyPem && env.KALSHI_PRIVATE_KEY_FILE) {
    privateKeyPem = readFileSafe(env.KALSHI_PRIVATE_KEY_FILE);
  }
  if (!keyId || !privateKeyPem) return null;
  return { keyId, privateKeyPem };
}

/* ------------------------------------------------------------------ *
 * Small utils
 * ------------------------------------------------------------------ */

export class ApiError extends Error {
  constructor(status, payload, url) {
    const code = payload?.code ?? payload?.error?.code ?? payload?.error?.message ?? "unknown";
    super(`HTTP ${status} ${code} @ ${url}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

export function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function backoffMs(attempt, base) {
  return Math.round(base * 2 ** attempt + Math.random() * 250);
}

export function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function headerMap(headers) {
  const out = {};
  headers.forEach((v, k) => {
    out[k] = v;
  });
  return out;
}

function readFileSafe(p) {
  try {
    return fs.readFileSync(p, "utf8");
  } catch {
    return null;
  }
}

export { crypto };
