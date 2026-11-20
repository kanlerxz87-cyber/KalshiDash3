/* KalshiDash3 — browser-live layer (T13/T14/T15, session arena-d022c8de)
 *
 * Why this file exists: every other surface on this site renders a snapshot
 * committed by a scheduled collector (https://.../actions/workflows/collect.yml,
 * 20-minute cadence). That is auditable but it is not live. This layer talks to
 * the official public demo REST API directly from the page, so the alert chat and
 * the price chart move on a tick cadence, and it degrades to the committed
 * snapshot when the browser cannot reach the API.
 *
 * Verified constraints this design obeys (all official sources, re-read 2026-11-20):
 *  - The WebSocket API requires authentication during the connection handshake,
 *    and that applies to the public market-data channels too, so a browser page
 *    with no API key cannot open one. Live updates therefore come from polling the
 *    public REST endpoints, not from a socket.
 *    https://docs.kalshi.com/getting_started/quick_start_websockets
 *  - `GET /markets/{ticker}/orderbook` and the multi-market `GET /markets/orderbooks`
 *    need no authentication; the docs show a plain `fetch()` for them.
 *    https://docs.kalshi.com/getting_started/orderbook_responses
 *    https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks
 *  - Order books contain BIDS ONLY, [price_dollars, count_fp] pairs sorted ascending
 *    with the best bid LAST; a NO bid at Y is a YES ask at 1-Y.
 *    https://docs.kalshi.com/getting_started/orderbook_responses
 *  - Candlesticks support period_interval 1, 60 and 1440 minutes only, so a true
 *    seconds axis can only come from accumulating observations, which is what the
 *    in-page tick log does.
 *    https://docs.kalshi.com/api-reference/market/get-market-candlesticks
 *  - 429 responses are throttling; back off.
 *    https://docs.kalshi.com/getting_started/rate_limits
 *  - Settled markets and their candlesticks move out of the live endpoints once the
 *    historical cutoff advances, so resolution history is read from both.
 *    https://docs.kalshi.com/getting_started/historical_data
 *
 * The scoring functions below are pure and DOM-free on purpose: scripts/roi_model.py
 * implements the same formulas, and scripts/tests/test_roi_parity.py runs both on one
 * fixture and fails if a single number differs. Same file for both: data/roi_model.json.
 */
"use strict";

const KDLIVE = (() => {
  const BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  const UA_NOTE = "KalshiDash3 live layer — public unauthenticated endpoints only";

  /* ------------------------------------------------------------------ *
   * Money / fee math — mirrors scripts/roi_model.py exactly
   * ------------------------------------------------------------------ */

  // The fee schedule rounds a fee "up such that the fee + positionCost is rounded to a
  // centicent"; rounding the total up to the next cent reproduces every row of the
  // schedule's general fee table (asserted in scripts/tests/test_fees.py). Integer
  // arithmetic on millionths of a dollar is used because naive `Math.ceil(x*100)/100`
  // bills 1.13 where the schedule prints 1.12: 0.07*100*0.2*0.8 = 1.1200000000000003
  // in binary float. Mirrors roi_model.ceil_cent() exactly.
  const ceilCent = (x) => {
    if (!(x > 0)) return 0;
    const micro = Math.max(1, Math.round(x * 1e6));
    return Math.floor((micro + 9999) / 10000) / 100;
  };

  // fee = round up(M x 0.07 x C x P x (1-P))   (taker, general)
  const takerFee = (contracts, price, mult = 1) =>
    ceilCent(mult * 0.07 * contracts * price * (1 - price));

  // fee = round up(M x 0.0175 x C x P x (1-P))  (maker; M defaults to 0)
  const makerFee = (contracts, price, mult = 0) =>
    ceilCent(mult * 0.0175 * contracts * price * (1 - price));

  // Per-contract, unrounded — used for scoring; a ledger must use takerFee() because
  // the exchange rounds the total up to a cent.
  const takerFeeUnit = (price, mult = 1) => mult * 0.07 * price * (1 - price);

  const num = (v) => {
    if (v === null || v === undefined || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };

  const clip = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

  // Depth-weighted mid. Inputs are official order-book values; the formula itself is
  // this project's definition (stated in data/roi_model.json), not a Kalshi field.
  function microprice(bid, ask, sizeAtBid, sizeAtAsk) {
    if (bid === null || ask === null) return null;
    const sb = num(sizeAtBid), sa = num(sizeAtAsk);
    if (sb === null || sa === null || sb + sa <= 0) return (bid + ask) / 2;
    return (bid * sa + ask * sb) / (sa + sb);
  }

  function seriesMult(seriesTicker, model) {
    const t = String(seriesTicker || "").toUpperCase();
    const row = (model.fees && model.fees.series_multipliers && model.fees.series_multipliers.table[t]) || null;
    return {
      taker: row ? row.taker : (model.fees.defaults ? model.fees.defaults.M_taker : 1),
      maker: row ? row.maker : (model.fees.defaults ? model.fees.defaults.M_maker : 0),
      listed: !!row,
    };
  }

  /**
   * Score one market. `m` is a GET /markets market object (or the equivalent row from
   * the committed snapshot); `book` is {depth_at_bid, depth_at_ask} from the order-book
   * endpoint (may be null); `ctx` = {now_ms, momentum_dollars, series_ticker}.
   * Returns the full audit trail: q, both sides, every filter with its reason.
   */
  function score(m, model, book, ctx) {
    const p = model.parameters;
    // A quote of exactly $0.00 or exactly $1.00 is the API's "nothing resting on
    // that side" sentinel, not a tradable price: the order book of such a market is
    // empty (https://docs.kalshi.com/getting_started/orderbook_responses).
    // Mirrors roi_model.quote() exactly (parity: scripts/tests/test_roi_parity.py).
    const quote = (v) => (v === null ? null : (v > 0 && v < 1 ? v : null));
    const bid = quote(num(m.yes_bid_dollars ?? m.bid));
    const ask = quote(num(m.yes_ask_dollars ?? m.ask));
    const last0 = num(m.last_price_dollars ?? m.last);
    const last = last0 !== null && last0 <= 0 ? null : last0;   // a $0.00 last print means "no trade"
    const sb = book ? num(book.depth_at_bid) : num(m.yes_bid_size_fp);
    const sa = book ? num(book.depth_at_ask) : num(m.yes_ask_size_fp);
    const micro = microprice(bid, ask, sb, sa);
    const mid = bid !== null && ask !== null ? (bid + ask) / 2 : last;
    const mult = seriesMult(ctx.series_ticker, model);

    const reasons = [];
    if (mid === null) { reasons.push("no quoted price at all"); return { eligible: false, reasons, ticker: m.ticker }; }
    const w = p.weights;
    let q = w.mid * mid + w.last * last;
    if (micro === null) {
      // Reduced feature set (no book): reallocate the micro weight to mid, exactly as
      // the validation replay does, so browser and CI agree when depth is missing.
      q = (w.mid + w.micro) * mid + w.last * last;
      reasons.push("no order-book depth: micro weight folded into mid");
    } else {
      q += w.micro * micro;
    }
    const mom = num(ctx.momentum_dollars);
    if (mom !== null && p.trend && p.trend.reference_move_dollars) {
      q += p.trend.weight_dollars * clip(mom / p.trend.reference_move_dollars, -1, 1);
    }
    const [qlo, qhi] = p.clip_q;
    q = clip(q, qlo, qhi);

    const f = p.filters;
    const spread = bid !== null && ask !== null ? ask - bid : null;
    // Depth is only a fact when the data source carried it; an absent field is unknown,
    // not zero. Mirrors roi_model.score() exactly (parity: scripts/tests/test_roi_parity.py).
    const depthKnown = sb !== null || sa !== null;
    const depth = depthKnown ? (sb || 0) + (sa || 0) : null;
    const vol24 = num(m.volume_24h_fp);
    const ttcH = m.close_time ? ((Date.parse(m.close_time) - ctx.now_ms) / 3600000) : null;

    // Both sides, priced the way an order would actually be filled.
    // A quoted level of exactly 0.00 (or a YES bid of 1.00, i.e. a NO price of 0.00) is what
    // GET /markets returns for a market with no resting order on that side — observed on 127
    // of 387 open in-scope markets in the 2026-11-20T15:19Z snapshot, e.g.
    // KXAAAGASD-26NOV21-3.7300 with yes_bid = yes_ask = last = "0.0000". Paying $0.00 for a
    // contract cannot happen, so such a side is not buyable and is skipped rather than priced
    // at cost = 0. Mirrors roi_model.score() exactly (parity: scripts/tests/test_roi_parity.py).
    const sides = [];
    if (ask !== null && ask > 0 && ask < 1) {
      const fee = takerFeeUnit(ask, mult.taker);
      const cost = ask + fee;
      sides.push({ side: "YES", entry: ask, fee_unit: fee, cost, ev: q - cost, roi: (q - cost) / cost });
    }
    if (bid !== null && 1 - bid > 0 && 1 - bid < 1) {
      const pno = 1 - bid;
      const fee = takerFeeUnit(pno, mult.taker);
      const cost = pno + fee;
      sides.push({ side: "NO", entry: pno, fee_unit: fee, cost, ev: 1 - q - cost, roi: (1 - q - cost) / cost });
    }
    if (!sides.length && (ask !== null || bid !== null)) {
      reasons.push("quoted at a degenerate 0.00/1.00 level: no price to buy, so no entry is priced");
    }
    const best = sides.slice().sort((a, b) => b.roi - a.roi)[0] || null;

    const fail = [];
    if (spread === null) fail.push("one-sided quote: spread unknown");
    else if (spread > f.max_spread) fail.push(`spread ${(spread * 100).toFixed(1)}c > ${(f.max_spread * 100).toFixed(0)}c cap`);
    if (depth === null) reasons.push("no order-book depth in this data source; depth gate not applied");
    else if (depth < f.min_depth_contracts) fail.push(`depth ${depth.toFixed(0)} < ${f.min_depth_contracts} contracts at the touch`);
    if (vol24 === null || vol24 < f.min_volume_24h_contracts) fail.push(`24h volume ${vol24 ?? "—"} < ${f.min_volume_24h_contracts} contracts`);
    if (!best) fail.push("no buyable side");
    else {
      if (best.entry < f.min_entry_price) fail.push(`${best.side} entry ${(best.entry * 100).toFixed(1)}c below ${(f.min_entry_price * 100).toFixed(0)}c floor`);
      if (best.entry > f.max_entry_price) fail.push(`${best.side} entry ${(best.entry * 100).toFixed(1)}c above ${(f.max_entry_price * 100).toFixed(0)}c ceiling`);
      if (best.roi <= f.min_net_roi) fail.push(`net ROI ${(best.roi * 100).toFixed(2)}% not above ${(f.min_net_roi * 100).toFixed(0)}% floor`);
    }
    if (ttcH === null) fail.push("no close_time: cannot tell when it resolves");
    else if (ttcH <= 0) fail.push("already past close_time");
    else if (ttcH < f.min_ttc_hours) fail.push(`closes in ${(ttcH * 60).toFixed(0)} min < ${f.min_ttc_hours * 60} min floor`);
    else if (ttcH > f.max_ttc_hours) fail.push(`closes in ${(ttcH / 24).toFixed(0)} d > ${(f.max_ttc_hours / 24).toFixed(0)} d horizon`);
    if (f.require_seed_category && m.category_basis !== "seed") fail.push("topic not confirmed by the fee schedule (keyword match only)");

    return {
      ticker: m.ticker,
      eligible: fail.length === 0,
      fails: fail,
      reasons,
      q, mid, micro, last, bid, ask, spread, depth, vol24, ttc_hours: ttcH,
      momentum: mom,
      series_ticker: ctx.series_ticker || null,
      fee_multiplier: mult,
      entry: best,
      score: best ? best.roi : null,
      dollars_traded_estimate: num(m.volume_fp) !== null && last !== null ? num(m.volume_fp) * last : null,
    };
  }

  /**
   * Consecutive-observation swing detector: |Δlast| >= threshold in either direction.
   * Mirrors roi_model.detect_swings() exactly — every consecutive pair that crosses the
   * threshold produces one entry, nothing is filtered out here (the alert list itself
   * de-duplicates identical printed moves).
   */
  function detectSwings(observations, threshold) {
    const out = [];
    let prev = null;
    for (const o of observations) {
      const cur = { t: o.t, v: num(o.last ?? o.last_price_dollars) };
      if (cur.v === null || !cur.t) { prev = cur; continue; }
      if (prev && prev.v !== null) {
        const delta = cur.v - prev.v;
        if (Math.abs(delta) + 1e-12 >= threshold) {
          out.push({
            ticker: o.ticker ?? null,
            from: prev.v, to: cur.v, delta,
            direction: delta > 0 ? "up" : "down",
            cents: Math.round(Math.abs(delta) * 1000) / 10,
            t: cur.t, previous_t: prev.t,
            volume_fp: num(o.volume_fp),
          });
        }
      }
      prev = cur;
    }
    return out;
  }

  /** URLs that appear literally in a market's own official text fields. Never invented. */
  const URL_RE = /https?:\/\/[^\s"'<>()]+/g;
  function catalystLinks(m) {
    const fields = ["rules_primary", "rules_secondary", "subtitle", "yes_sub_title", "no_sub_title", "title"];
    const found = new Map();
    for (const k of fields) {
      const v = m && m[k];
      if (typeof v !== "string") continue;
      for (const raw of v.match(URL_RE) || []) {
        const url = raw.replace(/[.,;:]+$/, "");
        if (!found.has(url)) found.set(url, k);
      }
    }
    return Array.from(found, ([url, field]) => ({ url, field }));
  }

  /* ------------------------------------------------------------------ *
   * Live engine: probe -> poll -> ticks -> alerts -> score
   * ------------------------------------------------------------------ */

  async function fetchJson(url, ms = 9000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    try {
      const r = await fetch(url, { cache: "no-store", signal: ctrl.signal });
      if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { status: r.status });
      return await r.json();
    } finally {
      clearTimeout(timer);
    }
  }

  function create(opts = {}) {
    const base = opts.base || BASE;
    const listeners = { tick: [], alert: [], pick: [], status: [] };
    const store = opts.storage || (typeof localStorage !== "undefined" ? localStorage : null);
    const STORE_KEY = opts.storeKey || "kd.live.ticks.v1";
    const MAX_OBS = opts.maxObs || 480;

    const S = {
      mode: "probing",            // probing | live-api | snapshot | offline
      modeReason: "",
      startedAt: null,
      lastPollAt: null,
      requests: 0, failures: 0, lastError: null,
      backoffMs: 0,
      markets: new Map(),          // ticker -> latest market object
      ticks: new Map(),            // ticker -> [{t,last,yes_bid,yes_ask,volume_fp}]
      alerts: [],                  // newest first
      picks: [],
      model: null,
      watch: [],
      books: new Map(),
      timer: null, running: false,
      pollMs: opts.pollMs || 6000,
      bookMs: opts.bookMs || 30000,
      snapshotMs: opts.snapshotMs || 60000,
      lastBookAt: 0, lastSnapshotAt: 0,
      snapshotAge: null,
      cut: null,                   // GET /historical/cutoff, read live when reachable
    };

    const emit = (k, payload) => listeners[k].forEach((fn) => { try { fn(payload, S); } catch (e) { console.error(e); } });
    const on = (k, fn) => { listeners[k].push(fn); return () => { listeners[k] = listeners[k].filter((f) => f !== fn); }; };

    /* ---- persisted tick log, so a reload does not erase the session's history ---- */
    function loadTicks() {
      if (!store) return;
      try {
        const raw = store.getItem(STORE_KEY);
        if (!raw) return;
        const doc = JSON.parse(raw);
        if (doc.schema !== 1) return;
        for (const [t, obs] of Object.entries(doc.series || {})) S.ticks.set(t, obs.slice(-MAX_OBS));
      } catch (e) { /* a corrupt or full store must never break the page */ }
    }
    let savePending = false;
    function saveTicks() {
      if (!store || savePending) return;
      savePending = true;
      setTimeout(() => {
        savePending = false;
        try {
          const series = {};
          for (const [t, obs] of S.ticks) if (obs.length > 1) series[t] = obs.slice(-MAX_OBS);
          store.setItem(STORE_KEY, JSON.stringify({ schema: 1, saved_at: new Date().toISOString(), series }));
        } catch (e) { /* quota */ }
      }, 4000);
    }

    function pushTick(ticker, obs) {
      const arr = S.ticks.get(ticker) || [];
      const prev = arr[arr.length - 1];
      // Never store two points with the same timestamp or the same price: the alert
      // detector compares consecutive observations, so duplicates would mask a move.
      if (prev && prev.t === obs.t) return;
      arr.push(obs);
      if (arr.length > MAX_OBS) arr.splice(0, arr.length - MAX_OBS);
      S.ticks.set(ticker, arr);
      if (prev) {
        const threshold = S.model ? S.model.swing_alert.threshold_dollars : 0.1;
        if (prev.last !== null && obs.last !== null && Math.abs(obs.last - prev.last) + 1e-12 >= threshold) {
          addAlert(ticker, prev, obs);
        }
      }
      saveTicks();
    }

    function addAlert(ticker, prev, obs) {
      const m = S.markets.get(ticker) || {};
      const delta = obs.last - prev.last;
      const a = {
        id: `${ticker}|${prev.last.toFixed(4)}|${obs.last.toFixed(4)}|${obs.t}`,
        ticker, title: m.title || m.yes_sub_title || ticker,
        event_ticker: m.event_ticker || null,
        series_ticker: (m.ticker || ticker).split("-")[0],
        category_id: m.category_id || null, category_basis: m.category_basis || null,
        from: prev.last, to: obs.last, delta,
        cents: Math.round(Math.abs(delta) * 1000) / 10,
        direction: delta > 0 ? "up" : "down",
        t: obs.t, previous_t: prev.t,
        volume_fp: obs.volume_fp, volume_24h_fp: m.volume_24h_fp, open_interest_fp: m.open_interest_fp,
        bid: obs.yes_bid, ask: obs.yes_ask,
        close_time: m.close_time || null,
        source: `${base}/markets/${ticker}`,
        origin: S.mode === "live-api" ? "live tick" : "committed snapshot",
        catalysts: m.__catalysts || catalystLinks(m),   // computed here too: the first alert can arrive before scoring
        roi: m.__roi || null,
      };
      // De-duplicate the same printed move (a retraded poll must not spam the chat).
      if (S.alerts.some((x) => x.ticker === a.ticker && x.from === a.from && x.to === a.to)) return;
      S.alerts.unshift(a);
      if (S.alerts.length > 200) S.alerts.length = 200;
      emit("alert", a);
      if (store) {
        try {
          const raw = store.getItem("kd.live.alerts.v1");
          const list = raw ? JSON.parse(raw) : [];
          store.setItem("kd.live.alerts.v1", JSON.stringify([a].concat(list).slice(0, 200)));
        } catch (e) { /* quota */ }
      }
    }
    function loadAlerts() {
      if (!store) return;
      try { S.alerts = JSON.parse(store.getItem("kd.live.alerts.v1") || "[]").slice(0, 200); } catch (e) { S.alerts = []; }
    }

    /* ---- API calls, all public, all unauthenticated ---- */
    async function api(pathAndQuery) {
      const url = base + pathAndQuery;
      S.requests += 1;
      try {
        const d = await fetchJson(url);
        S.backoffMs = 0;
        return d;
      } catch (e) {
        S.failures += 1;
        S.lastError = `${e.message || e} for ${pathAndQuery}`;
        if (e.status === 429) S.backoffMs = Math.min(60000, (S.backoffMs || 1000) * 2 || 2000);
        throw e;
      }
    }

    async function probe() {
      try {
        await fetchJson(`${base}/exchange/status`, 5000);
        S.mode = "live-api"; S.modeReason = "the page can reach the public demo REST API directly";
      } catch (e) {
        S.mode = "snapshot";
        S.modeReason = `direct call from this browser failed (${e.message || e}); the committed snapshot from the scheduled collector is used instead`;
      }
      try { S.cut = await api("/historical/cutoff"); } catch (e) { S.cut = null; }
      emit("status", S);
    }

    /**
     * Discover the markets worth watching, with no manual input: one paged
     * GET /markets?status=open&limit=1000&mve_filter=exclude, filtered to the five topics,
     * then the watch list is the biggest by volume x price. Discovery repeats on a slower
     * cadence than polling so a newly opened market is picked up without hammering the API.
     */
    async function discover(force) {
      if (!force && S.discoveredAt && Date.now() - S.discoveredAt < (opts.discoverMs || 300000) && S.watch.length) return S.watch.length;
      const pages = opts.discoverPages || 1;
      let cursor = "", scanned = 0, ranked = [];
      for (let page = 0; page < pages; page++) {
        let d;
        try { d = await api(`/markets?status=open&limit=1000&mve_filter=exclude${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`); }
        catch (e) { break; }
        const list = d.markets || [];
        scanned += list.length;
        for (const m of list) {
          if (m.mve_collection_ticker || String(m.ticker || "").startsWith("KXMVE")) continue;   // combos are excluded
          const cid = classifyTicker(m.ticker, m);
          if (!cid) continue;                                                                     // outside the five topics
          const st = String(m.ticker).split("-")[0].toUpperCase();
          m.category_id = cid;
          m.category_basis = SEED_SERIES.has(st) ? "seed" : "keyword";
          m.source = `${base}/markets/${m.ticker}`;
          S.markets.set(m.ticker, m);
          ranked.push({ ticker: m.ticker, dollars: (num(m.volume_fp) || 0) * (num(m.last_price_dollars) || 0) });
        }
        cursor = d.cursor || "";
        if (!cursor) break;
      }
      S.scanned = scanned;
      ranked.sort((a, b) => b.dollars - a.dollars);
      const keep = new Set(S.watch);
      const fresh = ranked.map(r => r.ticker).filter(t => !keep.has(t));
      S.watch = S.watch.filter(t => S.markets.has(t)).concat(fresh).slice(0, opts.watchMax || 60);
      S.discoveredAt = Date.now();
      return S.watch.length;
    }

    async function pollMarkets(tickers) {
      // GET /markets accepts `tickers` (comma separated) and `mve_filter=exclude`, both
      // documented on https://docs.kalshi.com/api-reference/market/get-markets
      const chunks = [];
      for (let i = 0; i < tickers.length; i += 60) chunks.push(tickers.slice(i, i + 60));
      const now = new Date().toISOString();
      const seen = new Set();
      for (const c of chunks) {
        let d;
        try { d = await api(`/markets?tickers=${encodeURIComponent(c.join(","))}`); }
        catch (e) { continue; }
        for (const m of d.markets || []) {
          seen.add(m.ticker);
          S.markets.set(m.ticker, m);
          pushTick(m.ticker, {
            t: now,
            last: num(m.last_price_dollars),
            yes_bid: num(m.yes_bid_dollars),
            yes_ask: num(m.yes_ask_dollars),
            volume_fp: num(m.volume_fp),
          });
          emit("tick", m);
        }
      }
      return seen.size;
    }

    async function pollBooks(tickers) {
      // GET /markets/orderbooks takes 1-100 tickers in one request.
      // `tickers` is an ARRAY and this endpoint does NOT split a comma-joined value:
      // "?tickers=A,B" is parsed as ONE ticker named "A,B" and comes back as a single
      // EMPTY book (measured against the live demo API; the order-book guide documents
      // that an unknown ticker returns an empty entry instead of an error —
      // https://docs.kalshi.com/getting_started/orderbook_responses).
      // The array is therefore sent as REPEATED parameters: "?tickers=A&tickers=B".
      for (let i = 0; i < tickers.length; i += 100) {
        const c = tickers.slice(i, i + 100);
        const q = c.map((t) => `tickers=${encodeURIComponent(t)}`).join("&");
        let d;
        try { d = await api(`/markets/orderbooks?${q}`); }
        catch (e) { return; }
        for (const ob of d.orderbooks || []) {
          const yes = (ob.orderbook_fp && ob.orderbook_fp.yes_dollars) || [];
          const no = (ob.orderbook_fp && ob.orderbook_fp.no_dollars) || [];
          const bestYesBid = yes.length ? yes[yes.length - 1] : null;
          const bestNoBid = no.length ? no[no.length - 1] : null;
          S.books.set(ob.ticker, {
            depth_at_bid: bestYesBid ? num(bestYesBid[1]) : 0,
            depth_at_ask: bestNoBid ? num(bestNoBid[1]) : 0,          // NO bid at Y = YES ask at 1-Y
            ask_price: bestNoBid ? 1 - num(bestNoBid[0]) : null,
            bid_price: bestYesBid ? num(bestYesBid[0]) : null,
            yes_ladder: yes.map((r) => ({ price: num(r[0]), contracts: num(r[1]) })),
            no_ladder: no.map((r) => ({ price: num(r[0]), contracts: num(r[1]) })),
            at: new Date().toISOString(),
          });
        }
      }
    }

    async function candles(seriesTicker, ticker, minutes) {
      // period_interval is restricted to 1 / 60 / 1440 by the API itself.
      const interval = minutes <= 60 ? 1 : minutes <= 60 * 24 ? 60 : 1440;
      const end = Math.floor(Date.now() / 1000);
      const start = end - minutes * 60;
      const d = await api(`/series/${encodeURIComponent(seriesTicker)}/markets/${encodeURIComponent(ticker)}/candlesticks?start_ts=${start}&end_ts=${end}&period_interval=${interval}`);
      return { interval, candles: (d.candlesticks || []).map((c) => ({
        t: c.end_period_ts * 1000,
        open: num(c.price && c.price.open_dollars), high: num(c.price && c.price.high_dollars),
        low: num(c.price && c.price.low_dollars), close: num(c.price && c.price.close_dollars),
        mean: num(c.price && c.price.mean_dollars), previous: num(c.price && c.price.previous_dollars),
        bid_close: num(c.yes_bid && c.yes_bid.close_dollars), ask_close: num(c.yes_ask && c.yes_ask.close_dollars),
        volume_fp: num(c.volume_fp), open_interest_fp: num(c.open_interest_fp),
      })) };
    }

    /* ---- scoring against the shared model ---- */
    function scoreAll(topN) {
      if (!S.model) return [];
      const now = Date.now();
      const lb = (S.model.parameters.lookback_minutes || 30) * 60000;
      const out = [];
      for (const [ticker, m] of S.markets) {
        const obs = S.ticks.get(ticker) || [];
        let mom = null;
        if (obs.length > 1) {
          const cur = obs[obs.length - 1], back = [...obs].reverse().find((o) => now - Date.parse(o.t) >= lb);
          if (back && cur.last !== null && back.last !== null) mom = cur.last - back.last;
        }
        let r;
        try {
          r = score(m, S.model, S.books.get(ticker) || null, { now_ms: now, momentum_dollars: mom, series_ticker: String(ticker).split("-")[0].toUpperCase() });
        } catch (err) {
          // One malformed market must not stop the whole watch list from scoring.
          S.scanErrors = (S.scanErrors || []).concat([{ ticker, error: String(err && err.message || err) }]);
          continue;
        }
        m.category_id = m.category_id || classifyTicker(ticker, m);
        m.category_basis = m.category_basis || (SEED_SERIES.has(r.series_ticker) ? "seed" : "keyword");
        m.__catalysts = catalystLinks(m);
        m.__roi = r;
        out.push(r);
      }
      const ok = out.filter((r) => r.eligible).sort((a, b) => b.score - a.score);
      S.picks = ok.slice(0, topN || (S.model.scoring.top_k || 12));
      emit("pick", S.picks);
      return ok;
    }

    const SEED_SERIES = new Set(["KXAAAGASM", "KXELECTIRAN", "KXEMMYCACTO", "KXEMMYCACTR", "KXEMMYCSERIES",
      "KXBALLONDOR", "KXSUPERBOWLHEADLINE", "KXBTCMAX150", "KXBTCY", "KXETHY", "KXPGATOUR", "KXPGARYDER", "KXPGASOLHEIM"]);
    const KW = {
      gas: ["gas", "gasoline", "diesel"],
      elections: ["election", "president", "senate", "congress", "mayor", "governor", "nominee"],
      culture: ["emmy", "oscar", "grammy", "album", "movie", "box office", "ballon", "headline", "celebrity"],
      crypto: ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "doge"],
      golf: ["golf", "pga", "ryder cup", "solheim", "masters", "open championship"],
    };
    function classifyTicker(ticker, m) {
      // Word-boundary matching, not substring: a substring test once put "yes Vegas,yes Tie"
      // into Gas Prices because "vegas" contains "gas". Same rule as scripts/collect.py.
      const st = String(ticker).split("-")[0].toUpperCase();
      const bySeed = { KXAAAGASM: "gas", KXELECTIRAN: "elections", KXBTCMAX150: "crypto", KXBTCY: "crypto", KXETHY: "crypto", KXPGATOUR: "golf", KXPGARYDER: "golf", KXPGASOLHEIM: "golf", KXBALLONDOR: "culture" }[st];
      if (bySeed) return bySeed;
      const hay = `${m.title || ""} ${m.yes_sub_title || ""} ${m.subtitle || ""}`.toLowerCase();
      for (const [id, kws] of Object.entries(KW)) {
        for (const kw of kws) if (new RegExp(`(?<![a-z0-9])${kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![a-z0-9])`).test(hay)) return id;
      }
      return null;
    }

    /* ---- snapshot fallback: the committed CI data, refreshed on a timer ---- */
    async function loadSnapshot(snapshotUrls) {
      const j = async (u) => { const r = await fetch(u, { cache: "no-store" }); if (!r.ok) throw new Error(`HTTP ${r.status} ${u}`); return r.json(); };
      try {
        const snap = await j(snapshotUrls.markets);
        S.snapshotAge = snap.collected_at || null;
        for (const m of snap.open_markets || []) {
          const row = { ...m };
          S.markets.set(m.ticker, row);
        }
        let hist = { series: {} };
        try { hist = await j(snapshotUrls.history); } catch (e) { /* no history yet */ }
        for (const [t, s] of Object.entries(hist.series || {})) {
          const mine = S.ticks.get(t) || [];
          const seen = new Set(mine.map((o) => o.t));
          const merged = mine.concat((s.observations || []).filter((o) => !seen.has(o.t))
            .map((o) => ({ t: o.t, last: num(o.last), yes_bid: num(o.yes_bid), yes_ask: num(o.yes_ask), volume_fp: num(o.volume_fp) })))
            .sort((a, b) => Date.parse(a.t) - Date.parse(b.t)).slice(-MAX_OBS);
          S.ticks.set(t, merged);
        }
        // Swings across the committed history, so the chat is never empty for a
        // reader whose browser cannot reach the API.
        const thr = S.model ? S.model.swing_alert.threshold_dollars : 0.1;
        for (const [t, obs] of S.ticks) {
          for (const a of detectSwings(obs, thr, { ticker: t })) {
            const m = S.markets.get(t) || {};
            addAlert(t, { t: a.previous_t, last: a.from }, { t: a.t, last: a.to });
            void m;
          }
        }
        S.lastSnapshotAt = Date.now();
        emit("status", S);
        return true;
      } catch (e) {
        S.mode = S.mode === "live-api" ? "live-api" : "offline";
        S.modeReason = `${S.modeReason} | snapshot unavailable (${e.message})`;
        emit("status", S);
        return false;
      }
    }

    /* ---- main loop ---- */
    async function tick() {
      if (!S.model) return;
      let watch = (S.watch.length ? S.watch : Array.from(S.markets.keys())).slice(0, opts.watchMax || 60);
      if (S.mode === "live-api") {
        // Discover on the first live pass even when a snapshot already seeded the list: the
        // committed file can be 20 minutes old, and a market opened since then must be watched.
        if (!S.discoveredAt || Date.now() - S.discoveredAt > (opts.discoverMs || 300000) || !watch.length) await discover(!watch.length);
        watch = (S.watch.length ? S.watch : Array.from(S.markets.keys())).slice(0, opts.watchMax || 60);
        if (watch.length) {
          try { await pollMarkets(watch); } catch (e) { S.lastError = String(e.message || e); }
          if (Date.now() - S.lastBookAt > S.bookMs) { S.lastBookAt = Date.now(); try { await pollBooks(watch); } catch (e) { /* books are optional depth */ } }
        }
      }
      if (Date.now() - S.lastSnapshotAt > S.snapshotMs) await loadSnapshot(S.snapshotUrls);
      S.lastPollAt = new Date().toISOString();
      scoreAll();
      emit("status", S);
      const wait = Math.max(S.pollMs, S.backoffMs);
      if (S.running) S.timer = setTimeout(tick, wait);
    }

    async function start(cfg) {
      S.snapshotUrls = cfg.snapshotUrls || { markets: "data/live/markets.json", history: "data/live/price_history.json" };
      try {
        const r = await fetch(cfg.modelUrl || "data/roi_model.json", { cache: "no-store" });
        S.model = await r.json();
      } catch (e) {
        // The model file is part of the site; if it is missing, do not invent parameters.
        throw new Error("data/roi_model.json could not be loaded — refusing to score with guessed parameters");
      }
      loadTicks(); loadAlerts();
      S.running = true; S.startedAt = new Date().toISOString();
      await probe();
      if (cfg.seedMarkets) await loadSnapshot(S.snapshotUrls);
      if (cfg.watch) S.watch = cfg.watch;
      await tick();
      return S;
    }

    function stop() { S.running = false; clearTimeout(S.timer); }
    function setWatch(list) { S.watch = list; }
    function seriesFor(ticker) { return S.ticks.get(ticker) || []; }

    return { BASE, S, on, emit, start, stop, tick, probe, discover, setWatch, seriesFor, scoreAll, api,
             candles, score, detectSwings, catalystLinks, takerFee, makerFee, takerFeeUnit, microprice, ceilCent,
             fetchJson, classifyTicker };
  }

  const api = { create, score, detectSwings, catalystLinks, takerFee, makerFee, takerFeeUnit, microprice, ceilCent, BASE, UA_NOTE };
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node tests
  return api;
})();

if (typeof window !== "undefined") window.KDLIVE = KDLIVE;
