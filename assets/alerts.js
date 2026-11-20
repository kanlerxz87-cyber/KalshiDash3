/* KalshiDash3 — alerting + simulation library (KDA).
 *
 * Everything here consumes ONLY committed collector output (data/live/*.json) —
 * real values observed from the official demo API — plus, when the user explicitly
 * enables it, a clearly-labelled SIMULATED tick stream that is never persisted and
 * never mixed into files or tables of API values.
 *
 * The $0.10 swing threshold and the model weights below are PROJECT REQUIREMENTS /
 * project-defined heuristics, not official Kalshi numbers. Every page that renders
 * them says so.
 */
"use strict";

const KDA = (() => {
  const $ = (s, r = document) => (window.KD ? KD.$(s, r) : r.querySelector(s));
  const esc = (s) => (window.KD ? KD.esc(s) : String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])));
  const num = (v, d = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? (window.KD ? KD.num(v) : "—") : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const cents = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? (window.KD ? KD.cents(v) : "—") : (Number(v) * 100).toFixed(1) + "¢");

  /* ------------------------------------------------------------------ *
   * 1 · High-ROI scoring model — project-defined, versioned, transparent *
   * ------------------------------------------------------------------ */
  const MODEL = {
    version: "v1.0",
    threshold_score: 55,
    weights: { magnitude: 0.35, relative: 0.25, liquidity: 0.20, volume: 0.20 },
    doc: [
      ["Magnitude", "min(|Δ$| / 0.25, 1)", "A 25¢ swing scores full marks; the brief's ≥$0.10 trigger is the floor, not the target."],
      ["Relative move", "min(|Δ$| / max(entry, 0.05) / 0.5, 1)", "A 10¢ move at 15¢ is a 67% repricing; at 90¢ it is 11%. Both matter, in different ways."],
      ["Liquidity at the touch", "min(contracts at best bid+ask / 500, 1); unknown ⇒ 0.5", "An alert you cannot trade is not high ROI. Unknown depth scores neutral 0.5 and is marked as such."],
      ["Recent volume", "min(log10(1 + volume_24h) / 4, 1); unknown ⇒ 0.5", "≈10k contracts traded in 24h scores full marks; unknown scores neutral 0.5."],
    ],
    note: "Weights are a project choice made to rank swing alerts by tradability, not an official Kalshi metric and not investment advice. The formula is shown so it can be criticised and changed.",
  };

  function scoreAlert(a, market, liq) {
    const d = Math.abs(Number(a.delta_dollars) || 0);
    const entry = Math.max(Number(a.from_price_dollars) || 0.05, 0.05);
    const dFactor = Math.min(d / 0.25, 1);
    const rFactor = Math.min(d / entry / 0.5, 1);
    let liqFactor = 0.5, liqKnown = false;
    if (liq && liq.orderbook && !liq.orderbook.error) {
      const c = (liq.orderbook.contracts_at_best_yes_bid || 0) + (liq.orderbook.contracts_at_best_yes_ask || 0);
      liqFactor = Math.min(c / 500, 1);
      liqKnown = true;
    }
    let volFactor = 0.5, volKnown = false;
    const v24 = market ? Number(market.volume_24h_fp) : NaN;
    if (Number.isFinite(v24) && v24 >= 0) {
      volFactor = Math.min(Math.log10(1 + v24) / 4, 1);
      volKnown = true;
    }
    const w = MODEL.weights;
    const score = Math.round(100 * (w.magnitude * dFactor + w.relative * rFactor + w.liquidity * liqFactor + w.volume * volFactor));
    return {
      score, liqKnown, volKnown,
      parts: {
        magnitude: Math.round(100 * w.magnitude * dFactor),
        relative: Math.round(100 * w.relative * rFactor),
        liquidity: Math.round(100 * w.liquidity * liqFactor),
        volume: Math.round(100 * w.volume * volFactor),
      },
    };
  }

  /* ------------------------------------------------------------------ *
   * 2 · Where a cause would first appear — official research links      *
   *    (starting points, NOT verified per-alert causes — see F-15)      *
   * ------------------------------------------------------------------ */
  const RESEARCH = {
    gas: [{ label: "EIA — gasoline & diesel data", url: "https://www.eia.gov/petroleum/gas/" }],
    elections: [
      { label: "FEC — election results & filings", url: "https://www.fec.gov/" },
      { label: "U.S. Election Assistance Commission", url: "https://www.eac.gov/" },
    ],
    culture: [
      { label: "Academy (Oscars)", url: "https://www.oscars.org/" },
      { label: "Recording Academy (Grammys)", url: "https://www.grammy.com/" },
      { label: "Television Academy (Emmys)", url: "https://www.emmys.com/" },
    ],
    crypto: [
      { label: "CME Group — cryptocurrency markets", url: "https://www.cmegroup.com/markets/cryptocurrencies.html" },
      { label: "Coinbase — prices", url: "https://www.coinbase.com/prices" },
    ],
    golf: [{ label: "PGA Tour — official", url: "https://www.pgatour.com/" }],
  };

  /* ------------------------------------------------------------------ *
   * 3 · Data loading                                                     *
   * ------------------------------------------------------------------ */
  async function loadJSON(path) {
    const bust = (path.includes("?") ? "&" : "?") + "_=" + Date.now();
    const r = await fetch(path + bust, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status} for ${path}`);
    return r.json();
  }

  function indexMarkets(snap) {
    const byTicker = {};
    for (const b of ["open_markets", "settled_markets"]) for (const r of (snap && snap[b]) || []) byTicker[r.ticker] = r;
    return byTicker;
  }
  function indexLiquidity(snap) {
    const m = {};
    for (const l of (snap && snap.liquidity) || []) m[l.ticker] = l;
    return m;
  }

  /* ------------------------------------------------------------------ *
   * 4 · Chat component — simplified scrolling chat, newest at bottom     *
   * ------------------------------------------------------------------ */
  function makeChat(host, { title, emptyText }) {
    host.classList.add("chatwrap");
    host.innerHTML =
      `<div class="chathead"><span class="chattitle">${esc(title)}</span><span class="chatcount small mut"></span></div>` +
      `<div class="chatlog" tabindex="0"></div>` +
      `<div class="chatfoot small mut">newest at bottom · auto-scroll pauses while you scroll up · hover a bubble for details</div>`;
    const log = host.querySelector(".chatlog");
    const count = host.querySelector(".chatcount");
    let pinned = true;
    log.addEventListener("scroll", () => {
      pinned = log.scrollTop + log.clientHeight >= log.scrollHeight - 48;
    });
    function bubble(a, sc) {
      const up = a.direction === "up";
      const sim = !!a.sim;
      const sys = !!a.sys;
      const d = (a.delta_dollars >= 0 ? "+" : "−") + "$" + Math.abs(a.delta_dollars).toFixed(2);
      const titleShort = (a.title || "market not in current snapshot").replace(/\*\*/g, "").slice(0, 84);
      const t = (a.to_ts || "").replace("T", " ").replace("Z", "") + "Z";
      const cat = a.category_id ? `<span class="chip">${esc(catLabel(a.category_id))}</span>` : `<span class="chip warn">unknown</span>`;
      const scChip = sc ? `<span class="chip score" title="model ${MODEL.version}: magnitude ${sc.parts.magnitude} + relative ${sc.parts.relative} + liquidity ${sc.parts.liquidity} + volume ${sc.parts.volume}">score ${sc.score}</span>` : "";
      const badge = sys ? `<span class="badge">SYS</span>`
        : sim ? `<span class="badge sim" title="Simulated tick — generated in this browser for testing the alerting path. Not API data; never persisted.">SIM</span>`
        : `<span class="badge api" title="Diff of two consecutive observations collected from the official demo API">API</span>`;
      const head = sys || (sim && !a.from_ts)
        ? `<div class="bubline">${badge} <b>${esc(a.ticker)}</b></div>`
        : `<div class="bubline">${badge} <b class="${up ? "g" : "r"}">${up ? "▲" : "▼"} ${esc(d)}</b> <code>${esc(a.ticker)}</code></div>`;
      return `<div class="bub ${up ? "up" : "down"}${sim ? " simb" : ""}">` +
        head +
        `<div class="small">${esc(titleShort)}</div>` +
        `<div class="small mut">${cat} ${sys || (sim && !a.from_ts) ? esc(t) : `${cents(a.from_price_dollars)} → <b>${cents(a.to_price_dollars)}</b> · ` + esc(t)}${scChip}</div>` +
        `<div class="small"><a href="${esc(a.source || "#")}" target="_blank" rel="noopener">${sys ? "workflow" : sim ? "about (flagged page)" : "API query"}</a>` +
        (sim ? ` <span class="mut">· simulated tick (not market data)</span>` : ``) +
        `</div></div>`;
    }
    function push(a, sc, { silent } = {}) {
      const atBottom = pinned;
      log.insertAdjacentHTML("beforeend", bubble(a, sc));
      while (log.children.length > 120) log.removeChild(log.firstChild);
      if (atBottom && !silent) log.scrollTop = log.scrollHeight;
      count.textContent = `${log.children.length} shown`;
    }
    function reset() { log.innerHTML = ""; count.textContent = ""; pinned = true; }
    return { push, reset, log, count };
  }

  function catLabel(id) {
    return (window.KD && KD.CAT_LABEL[id]) || id;
  }

  /* ------------------------------------------------------------------ *
   * 5 · Simulated tick stream — optional, labelled, ephemeral            *
   *    Seeds a random walk at each market's REAL last price and steps it *
   *    by a scale taken from that market's OWN observed diffs. Clearly   *
   *    marked SIM everywhere; never persisted; default OFF.              *
   * ------------------------------------------------------------------ */
  function mulberry32(seed) {
    let t = seed >>> 0;
    return () => {
      t += 0x6d2b79f5;
      let r = Math.imul(t ^ (t >>> 15), 1 | t);
      r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  function makeSim({ markets, hist, onAlert, onTick, intervalMs = 1400, seed = 42 }) {
    const rows = (markets || []).filter((m) => Number.isFinite(Number(m.last_price_dollars)) && Number(m.last_price_dollars) > 0.01 && Number(m.last_price_dollars) < 0.99);
    const obs = (hist && hist.series) || {};
    const rng = mulberry32(seed);
    const st = new Map();
    for (const m of rows) {
      const h = (obs[m.ticker] || {}).observations || [];
      const diffs = [];
      for (let i = 1; i < h.length; i++) {
        const d = Number(h[i].last) - Number(h[i - 1].last);
        if (Number.isFinite(d)) diffs.push(Math.abs(d));
      }
      const sigma = diffs.length ? Math.max(0.01, Math.min(0.08, diffs.reduce((s, x) => s + x, 0) / diffs.length * 2.5)) : 0.02;
      st.set(m.ticker, { price: Number(m.last_price_dollars), sigma, row: m });
    }
    let timer = null, n = 0;
    function stepOnce() {
      if (!st.size) return;
      const keys = Array.from(st.keys());
      const ticker = keys[Math.floor(rng() * keys.length)];
      const s = st.get(ticker);
      // Base zero-mean noise scaled by the market's own observed volatility, plus a
      // deliberate ~12% chance of a 10-25c jump so the >= $0.10 alerting path is
      // actually exercised by the preview. This is a TEST SIGNAL, clearly badged SIM.
      let step = (rng() + rng() - 1) * s.sigma * 1.8;
      if (rng() < 0.12) step = (rng() < 0.5 ? -1 : 1) * (0.10 + rng() * 0.15);
      const prev = s.price;
      const next = Math.min(0.99, Math.max(0.01, prev + step));
      s.price = next;
      n++;
      const tick = {
        ticker, sim: true, direction: next >= prev ? "up" : "down",
        delta_dollars: Math.round((next - prev) * 1e6) / 1e6,
        from_price_dollars: Math.round(prev * 1e6) / 1e6,
        to_price_dollars: Math.round(next * 1e6) / 1e6,
        to_ts: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
        title: s.row.title, category_id: s.row.category_id, source: s.row.source,
      };
      if (onTick) onTick(tick);
      if (Math.abs(tick.delta_dollars) + 1e-12 >= 0.10 && onAlert) onAlert(tick);
    }
    return {
      start() { if (!timer) timer = setInterval(stepOnce, intervalMs); },
      stop() { if (timer) { clearInterval(timer); timer = null; } },
      get running() { return !!timer; },
      get ticks() { return n; },
    };
  }

  /* ------------------------------------------------------------------ *
   * 6 · Deterministic trade replay over COLLECTED observations           *
   *    (the automated simulated trader used on portfolio.html)           *
   *    Entries fill at the observed best ask, exits at the observed best *
   *    bid of the SAME observation — no fills are invented between runs. *
   * ------------------------------------------------------------------ */
  const TRADE_FEE_RATE = 0.07; // general taker fee: 0.07 × C × P × (1−P) — official fee schedule

  // Rounded up to the cent exactly like the manual paper ledger on portfolio.html
  // (`ceil(0.07 × C × P × (1−P) × 100) / 100`), so both ledgers use the same math.
  function fee(contracts, price) {
    return Math.ceil(TRADE_FEE_RATE * contracts * price * (1 - price) * 100) / 100;
  }

  function replayStrategies({ markets, hist, liq, stake = 100, topPerCat = 5, strategies = ["S1", "S2", "S3", "S4"] }) {
    const liqByTicker = liq || {};
    const series = (hist && hist.series) || {};
    // Universe: per category, the top N open markets by dollars-traded estimate that have >= 2 observations.
    const byCat = {};
    for (const m of markets || []) {
      if (m.status !== "active") continue;
      const h = series[m.ticker] && series[m.ticker].observations;
      if (!h || h.length < 2) continue;
      (byCat[m.category_id] ||= []).push(m);
    }
    const universe = [];
    for (const cat of Object.keys(byCat)) {
      const rows = byCat[cat]
        .filter((m) => Number(m.dollars_traded_estimate) > 0)
        .sort((a, b) => b.dollars_traded_estimate - a.dollars_traded_estimate);
      universe.push(...(Number.isFinite(topPerCat) ? rows.slice(0, topPerCat) : rows));
    }

    // Global event list: every observation of every universe market, in time order.
    const events = [];
    for (const m of universe) {
      for (const o of series[m.ticker].observations) {
        const last = Number(o.last), bid = Number(o.yes_bid), ask = Number(o.yes_ask);
        if (!Number.isFinite(last) || last < 0 || last > 1) continue;
        events.push({ t: o.t, ticker: m.ticker, row: m, last, bid: Number.isFinite(bid) ? bid : null, ask: Number.isFinite(ask) ? ask : null, vol: Number(o.volume_fp) });
      }
    }
    events.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : a.ticker < b.ticker ? -1 : 1));

    const STRATS = {
      S1: { name: "S1 momentum", desc: "top-5/category · enter on ≥5¢ move with volume growth · trail 5¢ · YES only" },
      S2: { name: "S2 = S1 + liquidity floor", desc: "same as S1 but only when ≥100 contracts rest at the best ask in the snapshot book" },
      S3: { name: "S3 = S1 + fee-aware band", desc: "same as S1 but skips 25–75¢ entries unless the trigger move was ≥10¢" },
      S4: { name: "S4 resolution fade", desc: "at final observation: fade a ≤10¢/≥90¢ price only when the favored side has zero resting bids" },
    };

    const trades = [];
    let cash = 10000, tradeId = 0;
    const pos = new Map(); // key `${strategy}:${ticker}` -> position
    const curve = [];      // (t, equity)

    function mark(p, last, bid, ask) {
      const px = p.side === "yes" ? last : 1 - last;
      return p.contracts * px;
    }
    function bookFor(ticker) {
      const l = liqByTicker[ticker];
      return l && l.orderbook && !l.orderbook.error ? l.orderbook : null;
    }

    for (const ev of events) {
      for (const id of strategies) {
        if (id === "S4") continue; // resolved at the end, below
        const key = id + ":" + ev.ticker;
        const p = pos.get(key);
        const hasPosition = !!(p && p.contracts);
        const prev = hasPosition ? null : (p ? p.lastObs : null);
        // ---- S1-family entry (fires on a CONSECUTIVE observation pair) ----
        if (prev) {
          const move = ev.last - prev.price;
          const volGrew = Number.isFinite(ev.vol) && Number.isFinite(prev.vol) && ev.vol > prev.vol;
          const entryMove = Math.abs(move) >= 0.05 && move > 0 && volGrew; // YES-only momentum on up-moves
          if (entryMove) {
            const book = bookFor(ev.ticker);
            if (id === "S2" && (!book || (book.contracts_at_best_yes_ask || 0) < 100)) { pos.set(key, { lastObs: { price: ev.last, vol: ev.vol }, skipped: true }); continue; }
            const fill = ev.ask && ev.ask > 0 && ev.ask < 1 ? ev.ask : ev.last;
            const inBand = fill >= 0.25 && fill <= 0.75;
            if (id === "S3" && inBand && Math.abs(move) < 0.10) { pos.set(key, { lastObs: { price: ev.last, vol: ev.vol }, skipped: true }); continue; }
            const contracts = Math.floor(stake / fill);
            if (contracts >= 1) {
              const f = fee(contracts, fill);
              cash -= contracts * fill + f;
              tradeId++;
              pos.set(key, {
                id: tradeId, strategy: id, ticker: ev.ticker, row: ev.row, side: "yes",
                entry_ts: ev.t, entry_fill: fill, contracts, entry_fee: f, peak: ev.last, lastObs: { price: ev.last, vol: ev.vol },
              });
              continue;
            }
          }
        }
        // ---- trailing exit ----
        if (p && p.contracts) {
          p.peak = Math.max(p.peak, ev.last);
          p.lastObs = { price: ev.last, vol: ev.vol };
          if (ev.last <= p.peak - 0.05) {
            const fill = ev.bid && ev.bid > 0 && ev.bid < 1 ? ev.bid : ev.last;
            const f = fee(p.contracts, fill);
            cash += p.contracts * fill - f;
            trades.push({
              id: p.id, strategy: p.strategy, ticker: p.ticker, title: p.row.title, category_id: p.row.category_id,
              side: "yes", entry_ts: p.entry_ts, exit_ts: ev.t, entry_fill: p.entry_fill, exit_fill: fill,
              contracts: p.contracts, fees: p.entry_fee + f,
              pnl: p.contracts * (fill - p.entry_fill) - (p.entry_fee + f), status: "closed",
              source: p.row.source,
            });
            pos.delete(key);
            continue;
          }
        }
        if (!p) pos.set(key, { lastObs: { price: ev.last, vol: ev.vol } });
        else if (!p.contracts) p.lastObs = { price: ev.last, vol: ev.vol }; // advance the consecutive-pair reference
      }
      curve.push({ t: ev.t, equity: cash + Array.from(pos.values()).reduce((s, p) => s + (p.contracts ? mark(p, ev.last) : 0), 0) });
    }

    // ---- S4: one pass at each market's final observation ----
    // S4 positions are OPEN positions awaiting settlement: they are recorded only in
    // `open` (never in the closed-trade list) and resolve when a run first sees the
    // market's literal API `result`.
    if (strategies.includes("S4")) {
      const lastByTicker = new Map();
      for (const ev of events) lastByTicker.set(ev.ticker, ev);
      for (const [ticker, ev] of lastByTicker) {
        const book = bookFor(ticker);
        if (!book) continue;
        const yesBids = (book.yes_bids || []).reduce((s, x) => s + (x.contracts || 0), 0);
        const noBids = (book.no_bids || []).reduce((s, x) => s + (x.contracts || 0), 0);
        let side = null, fill = null;
        if (ev.last <= 0.10 && yesBids === 0) { side = "yes"; fill = ev.ask && ev.ask > 0 && ev.ask <= 0.20 ? ev.ask : null; }
        if (ev.last >= 0.90 && noBids === 0) { side = "no"; const px = ev.bid && ev.bid >= 0.80 ? 1 - ev.bid : null; fill = px && px <= 0.20 ? px : null; }
        if (!side || fill === null) continue;
        const contracts = Math.floor(stake / fill);
        if (contracts < 1) continue;
        const f = fee(contracts, fill);
        cash -= contracts * fill + f;
        tradeId++;
        pos.set("S4:" + ticker, {
          id: tradeId, strategy: "S4", ticker, row: ev.row, side, entry_ts: ev.t, entry_fill: fill,
          contracts, entry_fee: f, lastObs: { price: ev.last },
          note: "held until the market settles — payoff $1 per winning contract, no settlement fee",
        });
        curve.push({ t: ev.t, equity: cash + Array.from(pos.values()).reduce((s, p) => s + (p.contracts ? mark(p, ev.last) : 0), 0) });
      }
    }

    // Open positions marked to the final observation of their market.
    const finalByTicker = new Map();
    for (const ev of events) finalByTicker.set(ev.ticker, ev);
    const open = [];
    for (const p of pos.values()) {
      if (!p.contracts) continue;
      const ev = finalByTicker.get(p.ticker);
      const last = ev ? ev.last : p.lastObs.price;
      const value = p.contracts * (p.side === "yes" ? last : 1 - last);
      open.push({
        id: p.id, strategy: p.strategy, ticker: p.ticker, title: p.row.title, category_id: p.row.category_id,
        side: p.side, entry_ts: p.entry_ts, entry_fill: p.entry_fill, contracts: p.contracts, fees: p.entry_fee,
        mark_price: p.side === "yes" ? last : Math.round((1 - last) * 1e6) / 1e6,
        unrealized: value - p.contracts * p.entry_fill - p.entry_fee,
        status: "open", note: p.note || null, source: p.row.source,
      });
    }

    // Equity-curve drawdown.
    let peakE = -Infinity, maxDD = 0;
    for (const pt of curve) {
      peakE = Math.max(peakE, pt.equity);
      maxDD = Math.max(maxDD, peakE - pt.equity);
    }

    const closed = trades;
    function statsFor(id) {
      const t = closed.filter((x) => x.strategy === id);
      const o = open.filter((x) => x.strategy === id);
      const wins = t.filter((x) => x.pnl > 0).length;
      const realized = t.reduce((s, x) => s + x.pnl, 0);
      const unreal = o.reduce((s, x) => s + x.unrealized, 0);
      return {
        strategy: id, name: STRATS[id].name, trades: t.length + o.length, closed: t.length, open: o.length,
        wins, win_rate: t.length ? wins / t.length : null,
        realized_pnl: realized, unrealized_pnl: unreal,
        fees: t.reduce((s, x) => s + x.fees, 0) + o.reduce((s, x) => s + (x.fees || 0), 0),
      };
    }
    return {
      universe_size: universe.length,
      events: events.length,
      trades: closed,
      open,
      stats: strategies.map(statsFor),
      equity: curve,
      max_drawdown_portfolio: maxDD, // portfolio-level: all strategies' combined equity curve
      ending_cash: cash,
      STRATS,
      stake,
    };
  }

  return { MODEL, RESEARCH, scoreAlert, loadJSON, indexMarkets, indexLiquidity, makeChat, makeSim, replayStrategies, fee, TRADE_FEE_RATE, mulberry32, esc, cents, num };
})();
