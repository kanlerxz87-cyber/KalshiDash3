/* KalshiDash3 — live dashboard (browser fetches demo API directly; no keys needed for public data).
   Docs: https://docs.kalshi.com/getting_started/demo_env
         https://docs.kalshi.com/api-reference/market/get-market-orderbook
         https://docs.kalshi.com/api-reference/market/get-market-candlesticks
   Portfolio/trading needs demo API keys (see portfolio page); until then this page runs a
   clearly-labeled PAPER ledger in localStorage so the workflow is testable with zero manual input. */
"use strict";
const BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
const CATS = [
  {id:"gas", label:"Gas Prices", kws:["gas","gasoline","oil","energy"]},
  {id:"elections", label:"Elections", kws:["election","president","senate","house","vote"]},
  {id:"culture", label:"Culture", kws:["culture","movie","oscar","grammy","music","entertainment"]},
  {id:"crypto", label:"Crypto", kws:["crypto","bitcoin","btc","ethereum","eth"]},
  {id:"golf", label:"Golf", kws:["golf","pga","masters","ryder"]},
];
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = (v, d=2) => { const n = Number(v); return Number.isFinite(n) ? n.toLocaleString(undefined,{maximumFractionDigits:d}) : "—"; };
const money = v => { const n = Number(v); return Number.isFinite(n) ? "$" + n.toLocaleString(undefined,{minimumFractionDigits:2, maximumFractionDigits:2}) : "—"; };
const notional = m => { const v = Number(m.volume_fp||0) * Number(m.last_price_dollars||0); return Number.isFinite(v) ? v : 0; };

async function jget(path, params={}) {
  const q = new URLSearchParams(params).toString();
  const r = await fetch(BASE + path + (q ? "?" + q : ""), {headers:{"Accept":"application/json"}});
  if (!r.ok) throw new Error("HTTP " + r.status + " " + path);
  return r.json();
}

/* ---------- series discovery ---------- */
let seriesCache = [];
async function loadSeries() {
  const d = await jget("/series", {limit:1000});
  seriesCache = d.series || [];
  return seriesCache;
}
function catOfSeries(s) {
  const hay = ((s.ticker||"") + " " + (s.title||"") + " " + (s.category||"")).toLowerCase();
  for (const c of CATS) if (c.kws.some(k => hay.includes(k))) return c.id;
  return null;
}

/* ---------- markets ---------- */
let allMarkets = [];
async function loadMarkets() {
  let cursor = "", out = [];
  while (true) {
    const p = {status:"open", limit:200};
    if (cursor) p.cursor = cursor;
    const d = await jget("/markets", p);
    out = out.concat(d.markets || []);
    cursor = d.cursor || "";
    if (!cursor || out.length > 2000) break;
  }
  allMarkets = out;
  return out;
}
function topByCat(catId, n=8) {
  const tickers = new Set(seriesCache.filter(s => catOfSeries(s) === catId).map(s => s.ticker));
  return allMarkets.filter(m => tickers.has(m.series_ticker))
    .sort((a,b) => notional(b) - notional(a)).slice(0, n);
}

/* ---------- rendering: tables ---------- */
function marketRow(m) {
  const res = m.result ? `<span class="badge ok">${esc(m.result.toUpperCase())}</span>` : `<span class="badge">open</span>`;
  return `<tr>
    <td class="mono">${esc(m.ticker)}</td>
    <td>${esc(m.title || m.yes_sub_title || "")}</td>
    <td>${money(notional(m))}</td>
    <td>${num(m.volume_fp,0)}</td>
    <td>${m.last_price_dollars ?? "—"}</td>
    <td>${m.yes_bid_dollars ?? "—"} / ${m.yes_ask_dollars ?? "—"}</td>
    <td>${res}</td>
    <td><button class="btn ghost" data-watch="${esc(m.ticker)}">Watch</button></td>
  </tr>`;
}
function renderTop() {
  const host = $("#topTables"); if (!host) return;
  host.innerHTML = CATS.map(c => {
    const rows = topByCat(c.id);
    return `<div class="card" style="grid-column:1/-1"><h3>${c.label} <span class="mut small">— highest dollar (notional ≈ volume × last price)</span></h3>
      ${rows.length ? `<table><thead><tr><th>Ticker</th><th>Title</th><th>Notional</th><th>Volume</th><th>Last</th><th>Bid/Ask</th><th>Result</th><th></th></tr></thead><tbody>${rows.map(marketRow).join("")}</tbody></table>`
      : `<p class="mut">No open markets matched this category yet. Series discovery is live — check the Verification page for the matched series list.</p>`}
    </div>`;
  }).join("");
  host.querySelectorAll("[data-watch]").forEach(b => b.addEventListener("click", () => selectMarket(b.dataset.watch)));
}

/* ---------- chart: X=time, Y=contract price ---------- */
let selTicker = null, series = [], pollTimer = null, windowMode = "minutes";
async function selectMarket(ticker) {
  selTicker = ticker; series = [];
  $("#selInfo").textContent = "Loading " + ticker + " …";
  await refreshChart();
  clearInterval(pollTimer);
  pollTimer = setInterval(refreshChart, 5000);
  document.getElementById("chartCard").scrollIntoView({behavior:"smooth", block:"nearest"});
}
async function refreshChart() {
  if (!selTicker) return;
  try {
    const m = (await jget(`/markets/${selTicker}`)).market || {};
    const now = Date.now();
    series.push({t: now, p: Number(m.last_price_dollars ?? NaN), bid: Number(m.yes_bid_dollars ?? NaN), ask: Number(m.yes_ask_dollars ?? NaN)});
    const span = windowMode === "seconds" ? 120000 : windowMode === "minutes" ? 3600000 : 86400000;
    series = series.filter(s => now - s.t <= span);
    $("#selInfo").innerHTML = `<b>${esc(m.ticker)}</b> · ${esc(m.title||"")} · last <b>${m.last_price_dollars ?? "—"}</b> · bid ${m.yes_bid_dollars ?? "—"} · ask ${m.yes_ask_dollars ?? "—"} · vol ${num(m.volume_fp,0)} · status ${esc(m.status||"")} · result ${m.result ? `<span class="badge ok">${esc(m.result.toUpperCase())}</span>` : "pending"}`;
    drawChart(); loadOrderbook(selTicker);
  } catch(e) { $("#selInfo").textContent = "Chart fetch failed: " + e.message; }
}
function drawChart() {
  const cv = $("#priceChart"); if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr);
  ctx.clearRect(0,0,W,H);
  const pad = {l:52, r:14, t:14, b:30};
  const pts = series.filter(s => Number.isFinite(s.p));
  ctx.strokeStyle = "#24302b"; ctx.fillStyle = "#9fb3a9"; ctx.font = "12px system-ui";
  for (let i=0;i<=4;i++){ const y = pad.t + (H-pad.t-pad.b)*i/4; ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(W-pad.r,y); ctx.stroke();
    ctx.fillText((1 - i/4).toFixed(2), 8, y+4); }
  if (pts.length < 1) { ctx.fillText("Collecting live points… (polling every 5s)", pad.l+10, pad.t+24); return; }
  const t0 = pts[0].t, t1 = Math.max(pts[pts.length-1].t, t0+1000);
  const X = t => pad.l + (W-pad.l-pad.r) * (t - t0) / (t1 - t0);
  const Y = p => pad.t + (H-pad.t-pad.b) * (1 - p);
  // x labels
  for (let i=0;i<=4;i++){ const t = t0 + (t1-t0)*i/4; ctx.fillText(new Date(t).toLocaleTimeString(), X(t)-28, H-8); }
  ctx.strokeStyle = "#00B67A"; ctx.lineWidth = 2; ctx.beginPath();
  pts.forEach((s,i) => i ? ctx.lineTo(X(s.t), Y(s.p)) : ctx.moveTo(X(s.t), Y(s.p)));
  ctx.stroke();
  ctx.fillStyle = "#00B67A"; pts.forEach(s => { ctx.beginPath(); ctx.arc(X(s.t), Y(s.p), 2.5, 0, 7); ctx.fill(); });
  ctx.fillStyle = "#e8f0ec"; ctx.fillText("Y = contract price ($0–$1) · X = time (" + windowMode + " window)", pad.l+10, pad.t+14);
}

/* ---------- orderbook / liquidity ---------- */
async function loadOrderbook(ticker) {
  try {
    const d = await jget(`/markets/${ticker}/orderbook`, {depth:10});
    const ob = d.orderbook_fp || d.orderbook || {};
    const yes = ob.yes_dollars || [], no = ob.no_dollars || [];
    const maxQ = Math.max(1, ...yes.map(r=>Number(r[1]||0)), ...no.map(r=>Number(r[1]||0)));
    const row = (r, side) => `<div style="display:flex;justify-content:space-between;gap:8px" class="small mono">
      <span>${side} $${Number(r[0]).toFixed(4)}</span><span>${num(r[1],0)} contracts</span></div>
      <div class="bar" style="margin:3px 0 8px"><i style="width:${(Number(r[1]||0)/maxQ*100).toFixed(1)}%"></i></div>`;
    $("#liquidity").innerHTML =
      `<div><h4 style="margin:4px 0">YES bids <span class="mut small">(ask = 1 − best NO bid)</span></h4>${yes.length ? yes.map(r=>row(r,"YES")).join("") : '<p class="mut small">No YES bids.</p>'}</div>
       <div><h4 style="margin:4px 0">NO bids</h4>${no.length ? no.map(r=>row(r,"NO")).join("") : '<p class="mut small">No NO bids.</p>'}</div>`;
    const tot = yes.reduce((a,r)=>a+Number(r[1]||0),0) + no.reduce((a,r)=>a+Number(r[1]||0),0);
    $("#liqSummary").textContent = `Visible depth: ${num(tot,0)} contracts across ${yes.length+no.length} price levels. Source: GET /markets/{ticker}/orderbook.`;
  } catch(e) { $("#liquidity").innerHTML = `<p class="mut">Orderbook unavailable: ${esc(e.message)}</p>`; }
}

/* ---------- resolution tracker ---------- */
async function refreshResolved() {
  const host = $("#resolvedTable"); if (!host) return;
  try {
    const d = await jget("/markets", {status:"settled", limit:100});
    const rows = (d.markets||[]).filter(m => ["gas","elections","culture","crypto","golf"].some(k =>
      ((m.series_ticker||"")+" "+(m.title||"")).toLowerCase().includes(k) || catOfSeries({ticker:m.series_ticker,title:m.title,category:""}) === m.series_ticker));
    host.innerHTML = `<table><thead><tr><th>Ticker</th><th>Title</th><th>Resolved</th><th>Last price</th><th>Volume</th></tr></thead><tbody>${
      (d.markets||[]).slice(0,15).map(m=>`<tr><td class="mono">${esc(m.ticker)}</td><td>${esc(m.title||"")}</td>
      <td>${m.result ? `<span class="badge ok">${esc(m.result.toUpperCase())}</span>` : "—"}</td>
      <td>${m.last_price_dollars ?? "—"}</td><td>${num(m.volume_fp,0)}</td></tr>`).join("")
    }</tbody></table><p class="mut small">Showing latest settled markets from the demo API (status=settled). Use Watch to follow a live market until result = yes/no.</p>`;
  } catch(e) { host.innerHTML = `<p class="mut">Settled-market fetch failed: ${esc(e.message)}</p>`; }
}

/* ---------- paper trading ledger ---------- */
const LS = "kalshidash3_paper";
const ledger = () => JSON.parse(localStorage.getItem(LS) || '{"cash":10000,"trades":[]}');
const save = l => localStorage.setItem(LS, JSON.stringify(l));
function categorize(t) {
  const hay = (t.ticker+" "+(t.title||"")).toLowerCase();
  for (const c of CATS) if (c.kws.some(k => hay.includes(k))) return c.label;
  return "Other";
}
function renderLedger() {
  const l = ledger();
  const byCat = {}; l.trades.forEach(t => { const c = categorize(t); byCat[c] = byCat[c] || {n:0, notional:0}; byCat[c].n++; byCat[c].notional += t.count * t.price; });
  $("#paperCash").textContent = money(l.cash);
  $("#paperTrades").innerHTML = l.trades.length ? `<table><thead><tr><th>Time</th><th>Ticker</th><th>Side</th><th>Count</th><th>Price</th><th>Category</th></tr></thead><tbody>${
    l.trades.slice().reverse().map(t=>`<tr><td class="small">${new Date(t.ts).toLocaleString()}</td><td class="mono">${esc(t.ticker)}</td><td>${esc(t.side.toUpperCase())}</td><td>${t.count}</td><td>$${t.price}</td><td>${esc(t.cat)}</td></tr>`).join("")}</tbody></table>` : `<p class="mut">No paper trades yet. Use the trade form below.</p>`;
  $("#catSummary").innerHTML = Object.keys(byCat).length ? `<table><thead><tr><th>Category</th><th>Trades</th><th>Notional</th></tr></thead><tbody>${
    Object.entries(byCat).map(([c,v])=>`<tr><td>${esc(c)}</td><td>${v.n}</td><td>${money(v.notional)}</td></tr>`).join("")}</tbody></table>` : "";
}
function paperTrade() {
  const ticker = $("#ptTicker").value.trim(), side = $("#ptSide").value, count = Number($("#ptCount").value), price = Number($("#ptPrice").value);
  if (!ticker || !(count>0) || !(price>0 && price<1)) { alert("Enter ticker, count>0, price 0–1."); return; }
  const l = ledger(); const cost = count * price;
  if (cost > l.cash) { alert("Insufficient paper cash."); return; }
  l.cash -= cost; l.trades.push({ts: Date.now(), ticker, side, count, price, cat: categorize({ticker})});
  save(l); renderLedger();
}

/* ---------- boot ---------- */
async function boot() {
  const status = $("#liveStatus");
  try {
    status.textContent = "Connecting to demo API…";
    await loadSeries();
    const ms = await loadMarkets();
    status.innerHTML = `Live · ${ms.length} open markets · ${seriesCache.length} series · ${new Date().toLocaleTimeString()}`;
    renderTop(); refreshResolved();
    const first = topByCat("crypto")[0] || topByCat("elections")[0] || ms[0];
    if (first) selectMarket(first.ticker);
  } catch(e) {
    status.innerHTML = `Could not reach demo API from this browser (${esc(e.message)}). Check network / CORS and retry. Static verified tables remain available.`;
  }
  const wm = $("#windowMode"); if (wm) wm.addEventListener("change", () => { windowMode = wm.value; series = []; refreshChart(); });
  const rb = $("#refreshBtn"); if (rb) rb.addEventListener("click", boot);
  const tb = $("#tradeBtn"); if (tb) tb.addEventListener("click", paperTrade);
  const rt = $("#resetPaper"); if (rt) rt.addEventListener("click", () => { save({cash:10000,trades:[]}); renderLedger(); });
  renderLedger();
}
document.addEventListener("DOMContentLoaded", boot);
