
KD.nav("dashboard.html");
const state = { snap: null, hist: null, sel: null, cat: "" };

const WINDOWS = { s: 15 * 60e3, m: 6 * 3600e3, h: 72 * 3600e3, all: Infinity };

function pickInitialTicker() {
  const h = decodeURIComponent(location.hash.replace("#", ""));
  if (h) return h;
  const open = (state.snap?.open_markets || []).filter(r => r.dollars_traded_estimate);
  return open.length ? open[0].ticker : null;
}

function renderAlerts() {
  const marketRows = (state.snap?.open_markets || []).concat(state.snap?.settled_markets || []);
  const byTicker = new Map(marketRows.map(row => [row.ticker, row]));
  const alerts = [];
  for (const [ticker, data] of Object.entries(state.hist?.series || {})) {
    const market = byTicker.get(ticker);
    if (!market || (state.cat && market.category_id !== state.cat)) continue;
    const points = (data.observations || [])
      .filter(p => Number.isFinite(Date.parse(p.t)) && p.last !== null && p.last !== undefined && Number.isFinite(Number(p.last)))
      .slice().sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
    for (let i = 1; i < points.length; i++) {
      const before = Number(points[i - 1].last), after = Number(points[i].last);
      const change = after - before;
      if (Math.abs(change) + 1e-9 < 0.10) continue;
      alerts.push({ ticker, market, before, after, change, time: points[i].t, previousTime: points[i - 1].t });
    }
  }
  alerts.sort((a, b) => Date.parse(b.time) - Date.parse(a.time));
  const all = alerts.slice(0, 100);
  const screen = alerts.filter(a => a.market.category_basis === "seed" && Number(a.market.volume_24h_fp) > 0)
    .sort((a, b) => Number(b.market.volume_24h_fp) - Number(a.market.volume_24h_fp) || Date.parse(b.time) - Date.parse(a.time))
    .slice(0, 100);
  const renderFeed = (items, emptyText) => items.length ? items.map(a => {
    const sign = a.change > 0 ? "+" : "−";
    const direction = a.change > 0 ? "up" : "down";
    const title = `${a.market.title} · ${a.ticker}`;
    return `<article class="alert-item">
      <div class="alert-top"><time datetime="${KD.esc(a.time)}">${KD.esc(a.time.replace("T", " ").replace("Z", " UTC"))}</time><span>${KD.esc(KD.CAT_LABEL[a.market.category_id] || "")}</span></div>
      <span class="alert-market">${KD.esc(title)}</span>
      <span class="alert-move ${direction}">${sign}${(Math.abs(a.change) * 100).toFixed(1)}¢</span>
      <span class="small mut"> ${ (a.before * 100).toFixed(1)}¢ → ${(a.after * 100).toFixed(1)}¢</span>
      <div><a href="${KD.esc(a.market.source)}" target="_blank" rel="noopener">Official Kalshi market API record</a></div>
    </article>`;
  }).join("") : `<div class="alert-empty">${emptyText}</div>`;
  KD.$("#allAlerts").innerHTML = renderFeed(all, "No qualifying swings in the retained observations.");
  KD.$("#modelAlerts").innerHTML = renderFeed(screen, "No qualifying alerts meet the experimental screen.");
  KD.$("#allAlertCount").textContent = `${all.length} shown`;
  KD.$("#modelAlertCount").textContent = `${screen.length} shown`;
  const fetched = state.snap?.collected_at;
  KD.$("#alertFreshness").textContent = fetched
    ? `Alert scan uses consecutive snapshots through ${fetched} UTC. The collector runs on a scheduled cadence; this page checks for a newer committed snapshot once per minute. Older alerts may fall outside the retained chart history.`
    : "Alert feeds are empty until a sourced snapshot is available.";
}

function renderTables() {
  const open = (state.snap?.open_markets || []).filter(r => !state.cat || r.category_id === state.cat);
  const host = KD.$("#tables");
  const byCat = {};
  for (const r of open) (byCat[r.category_id] ||= []).push(r);
  const ids = Object.keys(KD.CAT_LABEL).filter(id => !state.cat || id === state.cat);
  host.innerHTML = ids.map(id => {
    const rows = (byCat[id] || []).slice(0, 8);
    const liqByTicker = {};
    for (const l of state.snap?.liquidity || []) liqByTicker[l.ticker] = l.orderbook || {};
    const trs = rows.map(r => {
      const ob = liqByTicker[r.ticker] || {};
      return {
        ticker: `<button class="ghost" data-t="${KD.esc(r.ticker)}" style="padding:2px 8px;font-size:11.5px">chart</button>`,
        title: `<a href="${KD.esc(r.source)}" target="_blank" rel="noopener" title="${KD.esc(r.title)}">${KD.esc(r.title)}</a>
                <div class="small mut mono">${KD.esc(r.ticker)}</div>`,
        dollars: KD.money(r.dollars_traded_estimate, 0),
        vol: KD.num(r.volume_fp),
        oi: KD.num(r.open_interest_fp),
        last: KD.cents(r.last_price_dollars),
        bid: KD.cents(r.yes_bid_dollars),
        ask: KD.cents(ob.best_yes_ask_derived ?? r.yes_ask_dollars),
        atAsk: ob.contracts_at_best_yes_ask === undefined ? '<span class="na">—</span>' : KD.num(ob.contracts_at_best_yes_ask),
        atBid: ob.contracts_at_best_yes_bid === undefined ? '<span class="na">—</span>' : KD.num(ob.contracts_at_best_yes_bid),
        status: KD.statusBadge(r.status),
        basis: KD.basisBadge(r.category_basis),
      };
    });
    return `<div class="card"><h3>${KD.CAT_LABEL[id]} <span class="small mut">${rows.length} of ${(byCat[id] || []).length} open in scope</span></h3>` +
      KD.table([
        { key: "ticker", label: "" }, { key: "title", label: "Market" },
        { key: "dollars", label: "$/traded est.", num: true }, { key: "vol", label: "Contracts", num: true },
        { key: "oi", label: "Open int.", num: true }, { key: "last", label: "Last", num: true },
        { key: "bid", label: "YES bid", num: true }, { key: "ask", label: "YES ask*", num: true },
        { key: "atAsk", label: "Qty at ask", num: true }, { key: "atBid", label: "Qty at bid", num: true },
        { key: "status", label: "Status" }, { key: "basis", label: "Category" },
      ], trs, { empty: "No open markets matched this category in the current snapshot." }) + `</div>`;
  }).join("");
  host.querySelectorAll("[data-t]").forEach(b => b.addEventListener("click", () => select(b.dataset.t)));
}

function renderResolved() {
  const rows = (state.snap?.settled_markets || [])
    .filter(r => !state.cat || r.category_id === state.cat)
    .slice(0, 60)
    .map(r => ({
      time: r.settlement_ts ? KD.esc(r.settlement_ts.replace("T", " ").replace("Z", "Z")) : '<span class="na">—</span>',
      ticker: `<a href="${KD.esc(r.source)}" target="_blank" rel="noopener" class="mono">${KD.esc(r.ticker)}</a>`,
      title: KD.esc(r.title),
      cat: KD.CAT_LABEL[r.category_id] || "—",
      result: KD.resultBadge(r.result),
      settle: KD.money(r.settlement_value_dollars, 4),
      last: KD.cents(r.last_price_dollars),
      vol: KD.num(r.volume_fp),
      basis: KD.basisBadge(r.category_basis),
    }));
  KD.$("#resolved").innerHTML = KD.table([
    { key: "time", label: "Settled (UTC)" }, { key: "ticker", label: "Ticker" }, { key: "title", label: "Market" },
    { key: "cat", label: "Category" }, { key: "result", label: "Resolved" }, { key: "settle", label: "Settlement value", num: true },
    { key: "last", label: "Last price", num: true }, { key: "vol", label: "Contracts", num: true }, { key: "basis", label: "Category basis" },
  ], rows, { empty: "No settled markets in scope in this snapshot." });
}

function renderPending() {
  const rows = (state.snap?.open_markets || [])
    .filter(r => !state.cat || r.category_id === state.cat)
    .slice(0, 80)
    .map(r => ({
      ticker: `<a href="${KD.esc(r.source)}" target="_blank" rel="noopener" class="mono">${KD.esc(r.ticker)}</a>`,
      title: KD.esc(r.title),
      cat: KD.CAT_LABEL[r.category_id] || "—",
      close: r.close_time ? KD.esc(r.close_time.replace("T", " ").replace("Z", "Z")) : '<span class="na">—</span>',
      expiry: r.expected_expiration_time ? KD.esc(r.expected_expiration_time.replace("T", " ")) : '<span class="na">—</span>',
      status: KD.statusBadge(r.status),
      result: KD.resultBadge(r.result),
    }));
  KD.$("#pending").innerHTML = KD.table([
    { key: "ticker", label: "Ticker" }, { key: "title", label: "Market" }, { key: "cat", label: "Category" },
    { key: "close", label: "Close time (UTC)" }, { key: "expiry", label: "Expected resolution" },
    { key: "status", label: "Lifecycle status" }, { key: "result", label: "Result so far" },
  ], rows, { empty: "No open markets in scope." });
}

function select(ticker) {
  state.sel = ticker;
  history.replaceState(null, "", "#" + encodeURIComponent(ticker));
  drawChart();
  drawLiq();
}

function currentRow() {
  if (!state.sel) return null;
  return (state.snap?.open_markets || []).concat(state.snap?.settled_markets || [])
    .find(r => r.ticker === state.sel) || null;
}

function drawChart() {
  const cv = KD.$("#priceChart");
  const row = currentRow();
  const meta = KD.$("#chartMeta"), foot = KD.$("#chartFoot");
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 900, H = 340;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const css = getComputedStyle(document.body);
  const line = css.getPropertyValue("--line"), mut = css.getPropertyValue("--mut"), green = "#00b67a", bad = "#f2695c";
  if (!row) {
    meta.textContent = "Pick a market from the tables below.";
    foot.textContent = "";
    return;
  }
  const series = (state.hist?.series?.[row.ticker]?.observations) || [];
  const key = KD.$("#seriesSel").value;
  const win = WINDOWS[KD.$("#window").value] || Infinity;
  const now = Date.now();
  const pts = series
    .map(o => ({ t: Date.parse(o.t), v: o[key] }))
    .filter(p => Number.isFinite(p.t) && p.v !== null && p.v !== undefined && !Number.isNaN(p.v))
    .filter(p => win === Infinity || now - p.t <= win);

  meta.innerHTML = `<b>${KD.esc(row.title)}</b> · <code>${KD.esc(row.ticker)}</code> · ` +
    `category ${KD.CAT_LABEL[row.category_id] || "—"} ${KD.basisBadge(row.category_basis)} · ` +
    `status ${KD.statusBadge(row.status)} · result ${KD.resultBadge(row.result)} · ` +
    `last ${KD.cents(row.last_price_dollars)} · ${KD.num(row.volume_fp)} contracts traded · ` +
    `open interest ${KD.num(row.open_interest_fp)}`;

  const pad = { l: 54, r: 14, t: 16, b: 34 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  ctx.strokeStyle = line; ctx.fillStyle = mut; ctx.font = "11px ui-monospace,monospace"; ctx.lineWidth = 1;
  // Y axis: contract price is bounded 0..1 by definition.
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + ih * i / 4;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillText("$" + (1 - i / 4).toFixed(2), 6, y + 4);
  }
  ctx.fillText("price", 6, pad.t - 4);

  if (pts.length < 1) {
    ctx.fillStyle = mut; ctx.font = "13px system-ui";
    ctx.fillText("No observations in this window yet.", pad.l + 12, pad.t + 26);
    ctx.font = "11px ui-monospace,monospace";
    foot.innerHTML = `Seconds-resolution history cannot be requested from Kalshi: candlesticks only support
      1, 60 and 1440-minute intervals (<a href="https://docs.kalshi.com/api-reference/market/get-market-candlesticks" target="_blank" rel="noopener">source</a>).
      This chart therefore plots <b>one observation per collector run</b> from
      <code>data/live/price_history.json</code>; widen the window or wait for more runs.`;
    return;
  }
  const t0 = pts[0].t, t1 = Math.max(pts[pts.length - 1].t, t0 + 60000);
  const X = t => pad.l + iw * (t - t0) / (t1 - t0);
  const Y = v => pad.t + ih * (1 - Math.min(1, Math.max(0, v)));
  for (let i = 0; i <= 4; i++) {
    const t = t0 + (t1 - t0) * i / 4;
    const d = new Date(t);
    const label = (t1 - t0) > 86400e3 ? `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:00`
      : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    ctx.fillText(label, X(t) - 26, H - 10);
  }
  ctx.strokeStyle = key === "ask" ? bad : green;
  ctx.lineWidth = 2;
  ctx.beginPath();
  pts.forEach((p, i) => i ? ctx.lineTo(X(p.t), Y(p.v)) : ctx.moveTo(X(p.t), Y(p.v)));
  ctx.stroke();
  ctx.fillStyle = key === "ask" ? bad : green;
  pts.forEach(p => { ctx.beginPath(); ctx.arc(X(p.t), Y(p.v), 2.4, 0, 7); ctx.fill(); });
  // last point callout
  const lastP = pts[pts.length - 1];
  ctx.fillStyle = css.getPropertyValue("--txt");
  ctx.font = "12px system-ui";
  ctx.fillText((key === "last" ? "last " : key === "bid" ? "bid " : "ask ") + (lastP.v * 100).toFixed(1) + "¢",
    Math.min(X(lastP.t) + 6, W - 80), Math.max(Y(lastP.v) - 6, 12));

  foot.innerHTML = `${pts.length} observation${pts.length === 1 ? "" : "s"} between
    ${KD.esc(new Date(t0).toISOString())} and ${KD.esc(new Date(t1).toISOString())} (UTC).
    Y axis is the contract price in dollars, bounded 0–1. Collected by
    <code>scripts/collect.py</code> from <a href="https://docs.kalshi.com/api-reference/market/get-markets" target="_blank" rel="noopener">GET /markets</a>.`;
}

function drawLiq() {
  const host = KD.$("#liq"), head = KD.$("#liqHead");
  const ob = (state.snap?.liquidity || []).find(l => l.ticker === state.sel)?.orderbook;
  if (!state.sel) { head.textContent = "Pick a market to see its order book."; host.innerHTML = ""; return; }
  if (!ob) {
    head.innerHTML = `No order book snapshot was collected for <code>${KD.esc(state.sel)}</code> in this run.
      Order books are collected for the top few markets per category only. Live source:
      <a href="https://docs.kalshi.com/api-reference/market/get-market-orderbook" target="_blank" rel="noopener">GET /markets/{ticker}/orderbook</a>.`;
    host.innerHTML = "";
    return;
  }
  if (ob.error) { head.innerHTML = `<span class="badge bad">order book unavailable</span> ${KD.esc(ob.error)}`; host.innerHTML = ""; return; }
  const maxC = Math.max(1, ...ob.yes_bids.map(x => x.contracts), ...ob.no_bids.map(x => x.contracts));
  const ladder = (rows, side) => rows.slice().reverse().slice(0, 10).map(r =>
    `<div class="row"><span>$${r.price.toFixed(4)}</span>
     <span class="bar ${side === "ask" ? "ask" : ""}"><i style="width:${(r.contracts / maxC * 100).toFixed(1)}%"></i></span>
     <span class="r">${KD.num(r.contracts)}</span></div>`).join("") || '<p class="empty">No resting orders on this side.</p>';
  head.innerHTML = `Order book for <code>${KD.esc(state.sel)}</code>, collected ${KD.esc(ob.fetched_at || "")}.
    Best YES bid <b>${KD.cents(ob.best_yes_bid?.price)}</b> (${KD.num(ob.contracts_at_best_yes_bid)} contracts) ·
    best YES ask <b>${KD.cents(ob.best_yes_ask_derived)}</b> (${KD.num(ob.contracts_at_best_yes_ask)} contracts) ·
    visible depth ${KD.num(ob.visible_contracts_total)} contracts ·
    <a href="${KD.esc(ob.source)}" target="_blank" rel="noopener">query</a>`;
  host.innerHTML =
    `<div><h3>YES bids — contracts a seller can hit</h3><div class="book">${ladder(ob.yes_bids, "bid")}</div></div>` +
    `<div><h3>YES asks, implied — contracts a buyer can lift</h3><div class="book">${ladder(ob.no_bids, "ask")}</div></div>`;
  KD.$("#chartFoot").innerHTML += "";
}

let loading = false;
async function load() {
  if (loading) return;
  loading = true;
  const refresh = Date.now();
  try { state.snap = await KD.json(`data/live/markets.json?refresh=${refresh}`); } catch { /* retain last successful snapshot */ }
  try { state.hist = await KD.json(`data/live/price_history.json?refresh=${refresh}`); } catch { /* retain last successful history */ }
  KD.snapshotBanner(state.snap);
  renderAlerts();
  if (!state.snap) {
    KD.$("#tables").innerHTML = KD.empty("No snapshot committed yet.");
    KD.$("#resolved").innerHTML = KD.empty("No snapshot committed yet.");
    KD.$("#pending").innerHTML = KD.empty("No snapshot committed yet.");
    loading = false;
    return;
  }
  const sel = KD.$("#catFilter");
  sel.innerHTML = '<option value="">All five</option>' +
    Object.entries(KD.CAT_LABEL).map(([id, l]) => `<option value="${id}">${l}</option>`).join("");
  sel.value = state.cat;
  renderTables(); renderResolved(); renderPending();
  const available = (state.snap.open_markets || []).concat(state.snap.settled_markets || []);
  if (!state.sel || !available.some(r => r.ticker === state.sel)) {
    const preferred = pickInitialTicker();
    state.sel = available.some(r => r.ticker === preferred) ? preferred : (available[0]?.ticker || null);
  }
  drawChart(); drawLiq();
  loading = false;
}

KD.$("#catFilter").addEventListener("change", e => { state.cat = e.target.value; renderAlerts(); renderTables(); renderResolved(); renderPending(); });
KD.$("#window").addEventListener("change", drawChart);
KD.$("#seriesSel").addEventListener("change", drawChart);
KD.$("#reload").addEventListener("click", load);
window.addEventListener("resize", () => { drawChart(); });
load();
window.setInterval(() => { if (!document.hidden) load(); }, 60_000);
