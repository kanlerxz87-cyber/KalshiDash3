/* KalshiDash3 — live engine: browser polling of the official Kalshi DEMO API,
 * ≥$0.10 swing alert detection, the transparent "model picks" scorer, chat
 * feeds, and the automated paper-trading (AUTO-SIM) engine.
 *
 * Design constraints (all verified against official sources):
 *  - The demo REST root https://external-api.demo.kalshi.co/trade-api/v2 serves
 *    public market data with no credentials (collector + workflow probe prove it).
 *  - GET /markets?tickers=a,b,c with tickers as the ONLY filter returns every
 *    matching market in one response; limit/cursor are not applied.
 *    https://docs.kalshi.com/api-reference/market/get-markets
 *  - Responses are cached briefly; prices can lag the exchange by seconds.
 *    https://docs.kalshi.com/api-reference/market/get-markets
 *  - Unauthenticated requests have separate rate limits — back off on 429.
 *    https://docs.kalshi.com/getting_started/rate_limits
 *  - Settlement: YES outcome pays YES holders $1/contract, NO outcome pays NO
 *    holders $1/contract; settlement fees are zero for simple yes/no.
 *    https://docs.kalshi.com/getting_started/market_settlement
 *  - Taker fee formula (general rate): fee = M x 0.07 x C x P x (1-P), rounded
 *    up to the next cent. https://kalshi.com/docs/kalshi-fee-schedule.pdf
 *
 * Everything the engine stores locally is labelled as a simulation. It never
 * places real orders: demo order placement needs API keys (see flagged.html).
 */
"use strict";

window.KDL = (() => {
  const BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  const ALERT_THRESHOLD = 0.10;      // project requirement: swing >= $0.10 in either direction
  const MAX_WATCH = 60;              // tickers per poll cycle (chunked)
  const CHUNK = 20;                  // tickers per /markets?tickers= request
  const FEED_MAX = 400;              // alert ring buffer
  const LS_FEED = "kalshidash3.alerts.v1";
  const LS_AUTOSIM = "kalshidash3.autosim.v1";
  const LS_CORS = "kalshidash3.cors.v1";

  const S = {
    corsOk: null,            // null = unknown, true = live REST works, false = blocked
    corsDetail: null,        // {checked_at, detail}
    probing: false,
    intervalMs: 10000,       // default poll interval (documented-cache lag makes <5s pointless)
    timer: null,
    running: false,
    failures: 0,
    paused: false,
    backoffUntil: 0,
    lastTickAt: null,
    lastError: null,
    tickCount: 0,
    markets: new Map(),      // ticker -> last row seen (any source)
    prevPrices: new Map(),   // ticker -> {price, at} from previous tick
    watch: [],               // ticker list to poll
    onRows: new Set(),       // callbacks(rows, source)
    onAlert: new Set(),      // callbacks(alert)
    onStatus: new Set(),     // callbacks(status)
    selectedBooks: new Map() // ticker -> orderbook summary (live)
  };

  // ---------------------------------------------------------------- helpers
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function num(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }

  function cents(v) { return v === null || v === undefined ? "—" : (v * 100).toFixed(1) + "¢"; }

  function money(v, d = 2) { return v === null || v === undefined ? "—" : "$" + Number(v).toFixed(d); }

  function takerFee(count, price, mult = 1) {
    // Documented general taker rate: fee = ceil(M x 0.07 x C x P x (1-P)) in cents.
    // https://kalshi.com/docs/kalshi-fee-schedule.pdf — per-series multipliers can differ.
    // The product is rounded to 6 decimals BEFORE the cent-ceil so float noise
    // (0.07*100*0.5*0.5*100 = 175.00000000000003) cannot overcharge a cent.
    if (!(count > 0) || !(price > 0) || price >= 1) return null;
    const centsRaw = mult * 0.07 * count * price * (1 - price) * 100;
    return Math.ceil(Number(centsRaw.toFixed(6))) / 100;
  }

  function marketPageLinks(row) {
    const t = encodeURIComponent(row.ticker || "");
    const q = encodeURIComponent((row.title || row.ticker || "").slice(0, 120));
    return {
      api_query: `${BASE}/markets?tickers=${t}`,
      api_orderbook: `${BASE}/markets/${t}/orderbook?depth=10`,
      demo_ui: "https://demo.kalshi.co/",
      news_google: `https://news.google.com/search?q=${q}`,
      news_bing: `https://www.bing.com/news/search?q=${q}`,
      news_ddg: `https://duckduckgo.com/?q=${q}&iax=news&ia=news`,
    };
  }

  // ---------------------------------------------------------------- CORS probe
  // The demo API is reached from the user's browser directly. CORS support is not
  // documented by Kalshi, so the engine probes GET /exchange/status (the same
  // public endpoint the collector workflow curls) and records the outcome.
  async function probe(force = false) {
    if (S.probing) return S.corsOk;
    if (!force) {
      const cached = readJSON(LS_CORS);
      if (cached && cached.ok === true && Date.now() - cached.at < 10 * 60e3) {
        S.corsOk = true; S.corsDetail = cached; notifyStatus(); return true;
      }
      if (cached && cached.ok === false && Date.now() - cached.at < 5 * 60e3) {
        S.corsOk = false; S.corsDetail = cached; notifyStatus(); return false;
      }
    }
    S.probing = true; notifyStatus();
    const started = Date.now();
    let ok = false, detail = "";
    try {
      const r = await fetch(BASE + "/exchange/status", { cache: "no-store" });
      ok = r.ok;
      detail = `HTTP ${r.status} in ${Date.now() - started}ms`;
      if (r.ok) { try { await r.json(); } catch { /* body shape not required */ } }
    } catch (e) {
      ok = false;
      detail = `${e.name || "Error"}: ${e.message || "network/CORS failure"}`;
    }
    S.probing = false;
    S.corsOk = ok;
    S.corsDetail = { ok, at: Date.now(), detail, base: BASE };
    writeJSON(LS_CORS, S.corsDetail);
    notifyStatus();
    return ok;
  }

  // ---------------------------------------------------------------- REST
  async function get(path, params) {
    const url = new URL(BASE + path);
    if (params) for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    }
    const r = await fetch(url, { cache: "no-store" });
    if (r.status === 429) {
      const e = new Error("HTTP 429 (rate limited) for " + path);
      e.rateLimited = true; throw e;
    }
    if (!r.ok) throw new Error("HTTP " + r.status + " for " + path);
    return r.json();
  }

  // ---------------------------------------------------------------- alert detection
  function makeAlert(row, from, to, delta, origin, note) {
    const d = Math.round(delta * 1000) / 1000;
    return {
      id: `${row.ticker}@${Date.now()}@${d > 0 ? "up" : "down"}`,
      ts: Date.now(),
      ticker: row.ticker,
      title: row.title || row.yes_sub_title || row.ticker,
      category_id: row.category_id || null,
      category_basis: row.category_basis || null,
      from: Math.round(from * 1000) / 1000,
      to: Math.round(to * 1000) / 1000,
      delta: d,
      dir: d > 0 ? "up" : "down",
      volume_fp: num(row.volume_fp),
      volume_24h_fp: num(row.volume_24h_fp),
      open_interest_fp: num(row.open_interest_fp),
      yes_bid: num(row.yes_bid_dollars),
      yes_ask: num(row.yes_ask_dollars),
      status: row.status || null,
      result: row.result || null,
      origin,                       // "live" (browser poll) | "collector" (committed history)
      note: note || null,
      links: marketPageLinks(row),
      model: null                   // filled by scoreAlert when the model runs
    };
  }

  function ingest(rows, origin, opts = {}) {
    const fired = [];
    for (const raw of rows) {
      const row = normalizeRow(raw);
      if (!row.ticker || row.last_price_dollars === null) continue;
      const prev = S.prevPrices.get(row.ticker);
      S.markets.set(row.ticker, Object.assign({}, S.markets.get(row.ticker) || {}, row, { _at: Date.now(), _origin: origin }));
      if (prev && !opts.silent) {
        const delta = row.last_price_dollars - prev.price;
        if (Math.abs(delta) >= ALERT_THRESHOLD - 1e-9) {
          const a = makeAlert(row, prev.price, row.last_price_dollars, delta, origin, opts.note || null);
          fired.push(a);
        }
      }
      S.prevPrices.set(row.ticker, { price: row.last_price_dollars, at: Date.now() });
    }
    for (const a of fired) { scoreAlert(a); pushAlert(a); for (const cb of S.onAlert) cb(a); }
    for (const cb of S.onRows) cb(rows, origin);
    return fired;
  }

  function normalizeRow(raw) {
    return {
      ticker: raw.ticker,
      event_ticker: raw.event_ticker || null,
      series_ticker: raw.series_ticker || (raw.ticker ? String(raw.ticker).split("-")[0] : null),
      title: raw.title || raw.yes_sub_title || raw.ticker,
      category_id: raw.category_id || null,
      category_basis: raw.category_basis || null,
      status: raw.status || null,
      result: raw.result || null,
      last_price_dollars: num(raw.last_price_dollars),
      yes_bid_dollars: num(raw.yes_bid_dollars),
      yes_ask_dollars: num(raw.yes_ask_dollars),
      no_bid_dollars: num(raw.no_bid_dollars),
      no_ask_dollars: num(raw.no_ask_dollars),
      volume_fp: num(raw.volume_fp),
      volume_24h_fp: num(raw.volume_24h_fp),
      open_interest_fp: num(raw.open_interest_fp),
      dollars_traded_estimate: num(raw.dollars_traded_estimate),
      close_time: raw.close_time || null,
      settlement_value_dollars: num(raw.settlement_value_dollars),
      source: raw.source || null
    };
  }

  // ---------------------------------------------------------------- model (transparent scorer)
  // Weights and components are published verbatim on alerts.html and
  // strategies.html. This is a heuristic screen, NOT a backtested strategy:
  // flagged for review (F-26) — it has never been validated against fills.
  const MODEL = {
    weights: { liquidity: 0.30, band: 0.25, momentum: 0.30, spread: 0.15 },
    threshold: 0.55,
    clamp01: (x) => Math.max(0, Math.min(1, x)),
    components(m, a) {
      const vol24 = num(m.volume_24h_fp) || 0;
      const oi = num(m.open_interest_fp) || 0;
      const dollars = num(m.dollars_traded_estimate) || 0;
      const liq = this.clamp01((Math.log10(vol24 + 1) / 5) * 0.7 + (Math.log10(dollars + 1) / 6) * 0.3);
      const p = a ? a.to : num(m.last_price_dollars) || 0.5;
      const band = p <= 0.03 || p >= 0.97 ? 0 : this.clamp01(1 - Math.abs(p - 0.5) / 0.47);
      const mom = a ? this.clamp01(Math.abs(a.delta) / 0.30) : 0;
      const bid = num(m.yes_bid_dollars), ask = num(m.yes_ask_dollars);
      const spread = (bid !== null && ask !== null) ? Math.max(0, ask - bid) : null;
      const sp = spread === null ? 0.4 : this.clamp01(1 - spread / 0.10);
      return { liquidity: liq, band, momentum: mom, spread: sp, _spread_dollars: spread };
    },
    reasons(m, a) {
      const c = this.components(m, a);
      const out = [
        `liquidity ${(c.liquidity).toFixed(2)} (24h vol ${m.volume_24h_fp ?? "—"}, $traded est. ${m.dollars_traded_estimate ?? "—"})`,
        `price band ${(c.band).toFixed(2)} (${cents(a ? a.to : m.last_price_dollars)})`,
        `momentum ${(c.momentum).toFixed(2)} (${a ? `${a.dir === "up" ? "▲" : "▼"} ${(Math.abs(a.delta) * 100).toFixed(1)}¢ swing` : "no swing yet"})`,
        `spread ${(c.spread).toFixed(2)} (bid/ask gap ${c._spread_dollars === null ? "unknown" : (c._spread_dollars * 100).toFixed(1) + "¢"})`
      ];
      return { score: c.liquidity * this.weights.liquidity + c.band * this.weights.band +
                      c.momentum * this.weights.momentum + c.spread * this.weights.spread, reasons: out };
    }
  };

  function scoreAlert(a) {
    const m = S.markets.get(a.ticker) || a;
    const r = MODEL.reasons(m, a);
    a.model = {
      score: Math.round(r.score * 1000) / 1000,
      reasons: r.reasons,
      modeled_roi_if_yes_at_ask: a.links && num(m.yes_ask_dollars) > 0
        ? Math.round(((1 - num(m.yes_ask_dollars)) / num(m.yes_ask_dollars)) * 1000) / 1000 : null,
      threshold: MODEL.threshold,
      disclaimer: "Heuristic screen, not backtested, not advice (F-26)."
    };
    return a;
  }

  function scoreMarket(m) {
    const r = MODEL.reasons(m, null);
    return r;
  }

  // ---------------------------------------------------------------- alert feed storage
  function readJSON(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } }
  function writeJSON(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private mode */ } }

  let feed = null;
  function loadFeed() {
    feed = readJSON(LS_FEED);
    if (!feed || feed.v !== 1 || !Array.isArray(feed.alerts)) feed = { v: 1, alerts: [], counters: { up: 0, down: 0 } };
    return feed;
  }
  function pushAlert(a) {
    if (!feed) loadFeed();
    if (feed.alerts.some((x) => x.id === a.id)) return;
    feed.alerts.push(a);
    feed.counters[a.dir] = (feed.counters[a.dir] || 0) + 1;
    if (feed.alerts.length > FEED_MAX) feed.alerts = feed.alerts.slice(-FEED_MAX);
    writeJSON(LS_FEED, feed);
  }
  function feedAlerts() { if (!feed) loadFeed(); return feed.alerts.slice().sort((a, b) => a.ts - b.ts); }
  function clearFeed() { feed = { v: 1, alerts: [], counters: { up: 0, down: 0 } }; writeJSON(LS_FEED, feed); }

  // ---------------------------------------------------------------- chat feed rendering
  // Chat style: newest at the BOTTOM, auto-scroll while the reader is at the
  // bottom (a "pause on scroll up" behaviour), like a simplified chat client.
  function renderFeed(container, alerts, opts = {}) {
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
    container.innerHTML = alerts.map((a) => bubble(a, opts)).join("") ||
      '<div class="chat-empty">No alerts yet. The feed fills when a contract moves ≥ $0.10 between two observations.</div>';
    if (opts.autoScroll !== false && nearBottom) container.scrollTop = container.scrollHeight;
  }

  function bubble(a, opts = {}) {
    const up = a.dir === "up";
    const cat = opts.catLabels ? (opts.catLabels[a.category_id] || "Other") : (a.category_id || "other");
    const t = new Date(a.ts);
    const hh = [t.getHours(), t.getMinutes(), t.getSeconds()].map((x) => String(x).padStart(2, "0")).join(":");
    const modelBit = a.model && a.model.score >= MODEL.threshold
      ? `<span class="badge ok" title="Model score ≥ threshold — also shown in the model feed">model ${(a.model.score).toFixed(2)}</span>` : "";
    const why = opts.showWhy && a.model
      ? `<div class="chat-why">why: ${a.model.reasons.map(esc).join(" · ")} · modeled ROI if YES at ask: ${a.model.modeled_roi_if_yes_at_ask === null ? "—" : Math.round(a.model.modeled_roi_if_yes_at_ask * 100) + "%"}</div>` : "";
    const l = a.links || {};
    // T66 evidence chip: only rendered when the field exists. "quote_only" is the case that
    // matters for a trader — the reported last price changed and NO contract traded — so it is
    // styled as a warning, not as a neutral label.
    const EV = {
      traded_ge_floor: { t: "traded", c: "ok", tip: "Contracts traded in the interval at or above this project's floor" },
      traded_below_floor: { t: "thin", c: "warn", tip: "Contracts traded in the interval, but below this project's floor" },
      quote_only: { t: "no trades", c: "bad", tip: "The reported last price changed with ZERO contracts traded in the interval" },
      counter_reset: { t: "volume n/a", c: "dim", tip: "The cumulative volume field did not increase between the two reads, so the interval's contract count cannot be derived" },
      unknown_no_observations: { t: "no history", c: "dim", tip: "The two observations that bound this swing are not in the committed history" },
    };
    const ev = a.evidence_state ? EV[a.evidence_state] : null;
    const evBit = ev
      ? `<span class="badge ${ev.c}" title="${esc(ev.tip)}">${esc(ev.t)}${a.contracts_traded !== null && a.contracts_traded !== undefined ? " · " + num(a.contracts_traded) + " contracts" : ""}</span>`
      : "";
    const rev = a.evidence_reversion;
    const revBit = rev && rev.gave_back_half === true
      ? `<span class="badge dim" title="A later observation returned to at least half the move">gave back ≥½</span>` : "";
    return `<div class="chat-msg ${up ? "up" : "down"}">
      <div class="chat-head">
        <span class="chat-time">${hh}</span>
        <span class="badge ${up ? "ok" : "bad"}">${up ? "▲" : "▼"} ${(Math.abs(a.delta) * 100).toFixed(1)}¢</span>
        <b>${cents(a.from)} → ${cents(a.to)}</b>
        <span class="mono chat-ticker">${esc(a.ticker)}</span>
        ${modelBit}
        ${evBit}
        ${revBit}
        <span class="badge dim">${esc(cat)}</span>
        <span class="badge ${a.origin === "live" ? "live" : "dim"}" title="${a.origin === "live" ? "Detected in your browser from the live demo API" : "Recovered from the collector's committed price history"}">${a.origin}</span>
      </div>
      <div class="chat-title">${esc(a.title)}</div>
      ${why}
      <div class="chat-links">
        <a href="${esc(l.api_query || "#")}" target="_blank" rel="noopener" title="Exact demo API query for this market">API</a>
        <a href="${esc(l.api_orderbook || "#")}" target="_blank" rel="noopener" title="Live order book from the demo API">book</a>
        <a href="${esc(l.demo_ui || "#")}" target="_blank" rel="noopener" title="Kalshi demo trading UI">demo UI</a>
        <a href="${esc(l.news_google || "#")}" target="_blank" rel="noopener" title="Possible-cause lead: news search for this market title — unverified">news leads ▸</a>
      </div>
    </div>`;
  }

  // ---------------------------------------------------------------- polling
  function setWatch(tickers) { S.watch = (tickers || []).slice(0, MAX_WATCH); }

  function notifyStatus() {
    const st = {
      corsOk: S.corsOk, probing: S.probing, running: S.running, paused: S.paused,
      intervalMs: S.intervalMs, lastTickAt: S.lastTickAt, lastError: S.lastError,
      tickCount: S.tickCount, backoff: S.backoffUntil > Date.now()
    };
    for (const cb of S.onStatus) cb(st);
  }

  function chunk(arr, n) { const out = []; for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n)); return out; }

  async function tick() {
    if (!S.running || S.paused || S.corsOk !== true) return;
    if (Date.now() < S.backoffUntil) return;
    const tickers = S.watch.filter((t) => {
      const m = S.markets.get(t);
      return !m || !["finalized", "determined", "closed", "settled"].includes(String(m.status || "").toLowerCase());
    });
    if (!tickers.length) { S.lastTickAt = Date.now(); notifyStatus(); return; }
    try {
      // tickers as the ONLY filter -> every matching market in one response,
      // no pagination (https://docs.kalshi.com/api-reference/market/get-markets)
      for (const c of chunk(tickers, CHUNK)) {
        const d = await get("/markets", { tickers: c.join(",") });
        ingest(d.markets || [], "live");
      }
      S.failures = 0; S.lastTickAt = Date.now(); S.tickCount++; S.lastError = null;
    } catch (e) {
      S.failures++; S.lastError = String(e.message || e);
      if (e.rateLimited) {
        // Unauthenticated limits are undocumented — exponential backoff, capped at 2 min.
        // https://docs.kalshi.com/getting_started/rate_limits
        S.backoffUntil = Date.now() + Math.min(120e3, S.intervalMs * Math.pow(2, S.failures));
      }
    }
    notifyStatus();
  }

  function start(intervalMs) {
    if (intervalMs) S.intervalMs = Math.max(2000, intervalMs);
    S.running = true;
    if (S.timer) clearInterval(S.timer);
    S.timer = setInterval(() => { if (!S.paused) tick(); }, S.intervalMs);
    tick();
    notifyStatus();
  }
  function stop() { S.running = false; if (S.timer) clearInterval(S.timer); S.timer = null; notifyStatus(); }
  function setPaused(p) { S.paused = p; notifyStatus(); }

  // Live order book for a single selected market (1 request per tick max).
  async function fetchOrderbook(ticker, depth = 10) {
    try {
      const d = await get(`/markets/${encodeURIComponent(ticker)}/orderbook`, { depth });
      const ob = d.orderbook_fp || d.orderbook || {};
      const lv = (rows) => (rows || []).filter((r) => Array.isArray(r) && r.length >= 2 && num(r[0]) !== null && num(r[1]) !== null)
        .map((r) => ({ price: num(r[0]), contracts: num(r[1]) }));
      const yes = lv(ob.yes_dollars), no = lv(ob.no_dollars);
      const bestYesBid = yes.length ? yes[yes.length - 1] : null;
      const bestNoBid = no.length ? no[no.length - 1] : null;
      const summary = {
        yes_bids: yes, no_bids: no,
        best_yes_bid: bestYesBid,
        best_yes_ask_derived: bestNoBid ? Math.round((1 - bestNoBid.price) * 10000) / 10000 : null,
        contracts_at_best_yes_bid: bestYesBid ? bestYesBid.contracts : null,
        contracts_at_best_yes_ask: bestNoBid ? bestNoBid.contracts : null,
        visible_contracts_total: Math.round(yes.concat(no).reduce((a, x) => a + x.contracts, 0) * 100) / 100,
        fetched_at: new Date().toISOString(),
        source: `${BASE}/markets/${encodeURIComponent(ticker)}/orderbook?depth=${depth}`
      };
      S.selectedBooks.set(ticker, summary);
      return summary;
    } catch (e) {
      return { error: String(e.message || e), source: `${BASE}/markets/${encodeURIComponent(ticker)}/orderbook?depth=${depth}` };
    }
  }

  // ---------------------------------------------------------------- snapshot + collector history (fallback layer)
  async function loadSnapshot(base = "") {
    let snap = null;
    try { snap = await (await fetch(base + "data/live/markets.json", { cache: "no-store" })).json(); } catch { snap = null; }
    if (snap) {
      ingest((snap.open_markets || []).concat(snap.settled_markets || []), "collector", { silent: true });
    }
    return snap;
  }

  // Committed server-side alerts, produced by scripts/build_alerts.py:
  //   data/live/alerts.json          -> {all_events: [...]}  (current feed)
  //   data/live/alerts_archive.json  -> {alerts: [...]}      (append-only history)
  // Schema per entry: ticker, title, category_id, category_basis, from_price,
  // to_price, delta, direction ("up"|"down"), from_time, to_time, status,
  // volume_24h_fp, market_source, cause_link (always null — causes are never
  // invented server-side), first_seen_at, high_roi.
  // The chats compute news-SEARCH lead links from the title themselves and
  // label them unverified (F-25); cause_link stays null and untouched.
  function collectorAlertFromEntry(a) {
    const t = Date.parse(a.to_time || "");
    const delta = num(a.delta);
    const row = Object.assign({}, S.markets.get(a.ticker) || {}, a);
    const links = marketPageLinks({ ticker: a.ticker, title: a.title });
    if (a.market_source) links.api_query = a.market_source;
    const full = makeAlert(row, num(a.from_price), num(a.to_price), delta, "collector",
      `Server-side swing between committed observations ${a.from_time} → ${a.to_time}. ${a.cause_status || ""}`);
    full.id = `${a.ticker}@${a.to_time}@${a.direction || (delta > 0 ? "up" : "down")}`;
    if (!Number.isNaN(t)) full.ts = t;
    full.high_roi_screen = a.high_roi === true;
    full.ts_source = a.to_time || null;
    // T66: the evidence behind the swing travels with it. `evidence` is frozen at detection
    // time by scripts/build_alerts.py; `evidence_reversion` may improve as reads accumulate.
    // Absent on legacy archive rows (written before the field existed) — never inferred here.
    full.evidence = a.evidence || null;
    full.evidence_reversion = a.evidence_reversion || null;
    full.evidence_state = (a.evidence && a.evidence.state) || null;
    full.contracts_traded = a.evidence ? a.evidence.contracts_traded : null;
    if (a.evidence && a.evidence.why) full.note = `${full.note} Evidence: ${a.evidence.why}.`;
    return full;
  }

  async function loadCollectorAlerts(base = "") {
    const revived = [];
    const known = new Set(feedAlerts().map((a) => a.id));
    for (const path of ["data/live/alerts_archive.json", "data/live/alerts.json"]) {
      let doc = null;
      try { doc = await (await fetch(base + path, { cache: "no-store" })).json(); } catch { doc = null; }
      const entries = doc ? (doc.alerts || doc.all_events || []) : [];
      for (const a of entries) {
        if (!a || !a.ticker || num(a.delta) === null) continue;
        const full = collectorAlertFromEntry(a);
        if (known.has(full.id)) continue;
        known.add(full.id);
        scoreAlert(full);
        pushAlert(full);
        revived.push(full);
      }
    }
    return revived;
  }

  // ---------------------------------------------------------------- AUTO-SIM (paper trading engine)
  // Labelled AUTO-SIM everywhere. It NEVER places real orders: demo order
  // placement needs API keys the project does not have (flagged.html F-07/F-27).
  const STRATS = {
    momentum: {
      id: "momentum", label: "Momentum chase",
      rule: "After a ≥ +$0.10 upswing on a market with ≥ 200 contracts traded in 24h, buy YES at the ask.",
      exit: "Take-profit / stop-loss at ±$0.10 from the entry fill, or settlement.",
      size: 25, maxOpen: 3, cooldownMs: 5 * 60e3
    },
    reversion: {
      id: "reversion", label: "Spike fade",
      rule: "After a ≥ +$0.10 upswing that pushes the price to ≥ 85¢, buy NO; after a ≥ $0.10 downswing to ≤ 15¢, buy YES.",
      exit: "Take-profit / stop-loss at ±$0.10, or settlement.",
      size: 25, maxOpen: 3, cooldownMs: 5 * 60e3
    },
    longshot: {
      id: "longshot", label: "Favorite harvest",
      rule: "On confirmed-series markets (category_basis=seed) priced ≥ 90¢ with more than 36h to close and no recent swing: buy YES small.",
      exit: "Take-profit at +5¢, stop-loss at −10¢, or settlement.",
      size: 10, maxOpen: 4, cooldownMs: 60 * 60e3
    }
  };

  const AT = {
    cfg: { enabled: true, cashStart: 1000, perStrategyCashCap: 300, strategies: { momentum: true, reversion: true, longshot: true } },
    state: null,
    lastEntryAt: new Map(),   // ticker+strategy -> ts (cooldown)
    listeners: new Set(),

    load() {
      const d = readJSON(LS_AUTOSIM);
      this.cfg = Object.assign({}, this.cfg, d && d.cfg || {});
      this.cfg.strategies = Object.assign({ momentum: true, reversion: true, longshot: true }, d && d.cfg && d.cfg.strategies || {});
      this.state = d && d.state && d.state.v === 1 ? d.state : this.freshState();
      return this.state;
    },
    freshState() {
      return {
        v: 1, cash: this.cfg.cashStart, positions: [], closed: [],
        seq: 0, started_at: new Date().toISOString()
      };
    },
    save() { writeJSON(LS_AUTOSIM, { cfg: this.cfg, state: this.state }); },
    reset() { this.state = this.freshState(); this.save(); for (const cb of this.listeners) cb(); },

    openRisk() {
      return this.state.positions.reduce((a, p) => a + p.count * p.entry_price, 0);
    },

    strategyOpen(sid) { return this.state.positions.filter((p) => p.strategy === sid).length; },
    strategySpend(sid) {
      return this.state.positions.filter((p) => p.strategy === sid).reduce((a, p) => a + p.count * p.entry_price, 0);
    },
    inCooldown(ticker, sid) {
      const at = this.lastEntryAt.get(`${ticker}@${sid}`);
      return at && Date.now() - at < (STRATS[sid] ? STRATS[sid].cooldownMs : 0);
    },

    // Buy YES (dir=+1) or NO (dir=-1) at the quoted price.
    // Fill basis: prefer the quoted side ask; never invent one.
    enter(row, dir, sid, opts = {}) {
      if (!this.cfg.enabled || !this.cfg.strategies[sid]) return null;
      if (row.result) return null; // already determined
      const yesAsk = num(row.yes_ask_dollars), yesBid = num(row.yes_bid_dollars);
      const noAsk = num(row.no_ask_dollars) !== null ? num(row.no_ask_dollars) : (yesBid !== null ? Math.round((1 - yesBid) * 10000) / 10000 : null);
      let fill, basis;
      if (dir === 1) {
        if (yesAsk === null || yesAsk <= 0 || yesAsk >= 1) return null;
        fill = yesAsk; basis = "yes_ask";
      } else {
        if (noAsk === null || noAsk <= 0 || noAsk >= 1) return null;
        fill = noAsk; basis = "no_ask";
      }
      const st = STRATS[sid];
      const count = opts.size || st.size;
      const feeIn = takerFee(count, fill);
      if (feeIn === null) return null;
      const cost = count * fill + feeIn;
      if (cost > this.state.cash) return null;
      if (this.strategySpend(sid) + count * fill > this.cfg.perStrategyCashCap) return null;
      const p = {
        id: ++this.state.seq,
        ts: Date.now(),
        ticker: row.ticker,
        title: row.title || row.ticker,
        dir,                              // +1 = YES bought, -1 = NO bought
        strategy: sid,
        category_id: row.category_id || null,
        category_basis: row.category_basis || null,
        count, entry_price: fill, entry_basis: basis,
        fee_entry: feeIn,
        trigger: opts.trigger || null,    // what caused the entry (alert delta etc.)
        trigger_alert_id: opts.trigger_alert_id || null,
        status: "open"
      };
      this.state.cash -= cost;
      this.state.positions.push(p);
      this.lastEntryAt.set(`${row.ticker}@${sid}`, Date.now());
      this.save();
      return p;
    },

    // Close a position: exitPrice is expressed in the TRADED side's price terms
    // (YES price for YES positions, NO price for NO positions) unless settled.
    close(pos, exitPrice, basis, reason) {
      const idx = this.state.positions.indexOf(pos);
      if (idx < 0) return null;
      const feeOut = takerFee(pos.count, Math.max(0.0001, Math.min(0.9999, exitPrice)));
      // Economic P&L in the traded side's price terms: (exit - entry) x count.
      // For settlements exitPrice IS the per-contract payout ($1 winner / $0
      // loser), so a losing settled position books gross = -entry x count —
      // the stake was already paid at entry. Settlement semantics:
      // YES outcome pays YES holders $1/contract, NO outcome pays NO holders
      // $1/contract; settlement fees are zero for simple yes/no determinations.
      // https://docs.kalshi.com/getting_started/market_settlement
      const gross = (exitPrice - pos.entry_price) * pos.count;
      const net = gross - pos.fee_entry - (feeOut || 0);
      const rec = {
        ...pos, exit_ts: Date.now(), exit_price: Math.round(exitPrice * 10000) / 10000,
        exit_basis: basis, exit_reason: reason || "manual", fee_exit: feeOut || 0,
        pnl_gross: Math.round(gross * 100) / 100, pnl_net: Math.round(net * 100) / 100,
        status: "closed"
      };
      this.state.positions.splice(idx, 1);
      this.state.closed.push(rec);
      this.state.cash += pos.count * exitPrice - (feeOut || 0);
      // ^ settlement pays $1 per winning contract; a price exit sells at exitPrice.
      this.save();
      return rec;
    },

    // Called on every batch of fresh rows (live poll or snapshot refresh).
    onRows(rows) {
      if (!this.state) this.load();
      if (!this.cfg.enabled) return;
      const byTicker = new Map();
      for (const raw of rows) { const r = normalizeRow(raw); if (r.ticker) byTicker.set(r.ticker, r); }

      // 1) exits for open positions
      for (const pos of this.state.positions.slice()) {
        const r = byTicker.get(pos.ticker);
        if (!r) continue;
        const st = r.status ? String(r.status).toLowerCase() : "";
        const done = st === "finalized" || st === "determined" || (r.result === "yes" || r.result === "no");
        if (done) {
          if (r.result === "yes" || r.result === "no") {
            pos.settle_result = r.result;
            const payout = (pos.dir === 1 ? (r.result === "yes" ? 1 : 0) : (r.result === "no" ? 1 : 0));
            this.close(pos, payout, "settlement", "settlement");
          }
          // result=scalar or empty on a done market: left open, flagged on the page.
          continue;
        }
        // price exits use the YES price space; convert for NO positions
        const yesBid = r.yes_bid_dollars, yesLast = r.last_price_dollars;
        const exitYes = yesBid !== null ? yesBid : yesLast;   // exits fill at the bid when known
        if (exitYes === null) continue;
        const yesSpaceEntry = pos.dir === 1 ? pos.entry_price : Math.round((1 - pos.entry_price) * 10000) / 10000;
        const move = exitYes - yesSpaceEntry;
        const tp = pos.strategy === "longshot" ? 0.05 : 0.10;
        const sl = 0.10;
        if (pos.dir === 1) {
          if (move >= tp) this.close(pos, pos.entry_price + tp, pos.strategy === "longshot" ? "target" : "target", "take_profit");
          else if (move <= -sl) this.close(pos, exitYes, exitYes === yesBid ? "yes_bid" : "last", "stop_loss");
        } else {
          // NO position: profit when YES price falls
          if (move <= -tp) this.close(pos, pos.entry_price + tp, "derived", "take_profit");
          else if (move >= sl) this.close(pos, Math.max(0.0001, 1 - exitYes), exitYes === yesBid ? "derived_from_yes_bid" : "derived_from_last", "stop_loss");
        }
      }

      // 2) entries — driven by recent alerts (momentum, reversion) or statics (longshot)
      const recent = feedAlerts().filter((a) => a.origin === "live" && Date.now() - a.ts < 90e3);
      for (const a of recent.slice(-12).reverse()) {
        const r = byTicker.get(a.ticker) || S.markets.get(a.ticker);
        if (!r) continue;
        if (a.dir === "up" && (num(r.volume_24h_fp) || 0) >= 200) {
          if (this.strategyOpen("momentum") < STRATS.momentum.maxOpen && !this.inCooldown(a.ticker, "momentum")) {
            this.enter(r, 1, "momentum", { trigger: `upswing ${(a.delta * 100).toFixed(1)}¢`, trigger_alert_id: a.id });
          }
          if (a.to >= 0.85 && this.strategyOpen("reversion") < STRATS.reversion.maxOpen && !this.inCooldown(a.ticker, "reversion")) {
            this.enter(r, -1, "reversion", { trigger: `fade upswing to ${(a.to * 100).toFixed(1)}¢`, trigger_alert_id: a.id });
          }
        }
        if (a.dir === "down" && a.to <= 0.15 && this.strategyOpen("reversion") < STRATS.reversion.maxOpen && !this.inCooldown(a.ticker, "reversion")) {
          this.enter(r, 1, "reversion", { trigger: `fade downswing to ${(a.to * 100).toFixed(1)}¢`, trigger_alert_id: a.id });
        }
      }
      // longshot: scan watched rows
      if (this.cfg.strategies.longshot && this.strategyOpen("longshot") < STRATS.longshot.maxOpen) {
        for (const r of byTicker.values()) {
          if (r.category_basis !== "seed" || r.result) continue;
          const last = r.last_price_dollars;
          if (last === null || last < 0.90 || last > 0.95) continue;
          if (!r.close_time || Date.parse(r.close_time) - Date.now() < 36 * 3600e3) continue;
          if (recent.some((a) => a.ticker === r.ticker)) continue;
          if (this.inCooldown(r.ticker, "longshot")) continue;
          const e = this.enter(r, 1, "longshot", { trigger: `favorite ${cents(last)} ≥36h to close` });
          if (e) break; // one per tick
        }
      }
      for (const cb of this.listeners) cb();
    },

    stats() {
      const closed = this.state.closed;
      const by = (key) => {
        const out = {};
        for (const t of closed.concat(this.state.positions.map((p) => ({ ...p, pnl_gross: null, pnl_net: null, open: true })))) {
          const k = key(t) || "unknown";
          out[k] ||= { n: 0, open: 0, wins: 0, losses: 0, stake: 0, fees: 0, net: 0 };
          out[k].n++;
          if (t.open) out[k].open++;
          out[k].stake += t.count * t.entry_price;
          out[k].fees += (t.fee_entry || 0) + (t.fee_exit || 0);
          out[k].net += t.pnl_net || 0;
          if (t.pnl_net > 0) out[k].wins++;
          if (t.pnl_net < 0) out[k].losses++;
        }
        return out;
      };
      const equity = this.state.cash + this.openRisk();
      const realized = closed.reduce((a, t) => a + t.pnl_net, 0);
      return {
        cash: this.state.cash, equity, realized,
        fees: closed.reduce((a, t) => a + t.fee_entry + t.fee_exit, 0),
        openCount: this.state.positions.length,
        openRisk: this.openRisk(),
        byStrategy: by((t) => t.strategy),
        byCategory: by((t) => t.category_id),
        byBand: by((t) => bandOf(t.entry_price)),
        byExitReason: by((t) => t.exit_reason || "open")
      };
    }
  };

  function bandOf(p) {
    const B = [[0, .1, "0–10¢"], [.1, .25, "10–25¢"], [.25, .5, "25–50¢"], [.5, .75, "50–75¢"], [.75, .9, "75–90¢"], [.9, 1.0001, "90–100¢"]];
    return (B.find((b) => p >= b[0] && p < b[1]) || B[B.length - 1])[2];
  }

  // Hook the auto-sim into every ingest automatically (unless disabled by page).
  let autoHook = true;
  for (const cb of S.onRows) { /* existing listeners stay */ }
  function addRowsListener(cb, { noAuto = false } = {}) { S.onRows.add(cb); return () => S.onRows.delete(cb); }

  // The auto-sim subscribes once, here, so trading.html and alerts.html both
  // keep the ledger moving; pages that must not trade set AT.cfg.enabled=false.
  S.onRows.add((rows, origin) => {
    if (autoHook && AT.cfg && AT.cfg.enabled) {
      try { AT.onRows(rows); } catch (e) { console.error("auto-sim error", e); }
    }
  });

  // ---------------------------------------------------------------- init
  AT.load();

  return {
    BASE, ALERT_THRESHOLD, MODEL, STRATS,   // BASE lets a page print the exact official URL it queried
    probe, get, setWatch, start, stop, setPaused, fetchOrderbook,
    ingest, loadSnapshot, loadCollectorAlerts,
    feedAlerts, clearFeed, renderFeed, bubble, pushAlert, makeAlert,
    scoreMarket, scoreAlert,
    AT,
    onRows: addRowsListener,
    onAlert: (cb) => (S.onAlert.add(cb), () => S.onAlert.delete(cb)),
    onStatus: (cb) => (S.onStatus.add(cb), () => S.onStatus.delete(cb)),
    state: S,
    esc, num, cents, money, takerFee, bandOf,
    markets: S.markets
  };
})();
