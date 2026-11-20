/* Live price chart + liquidity view. Calls ONLY documented public demo endpoints from the viewer's browser:
   GET /series/{series}/markets/{ticker}/candlesticks  (period_interval 1, 60 or 1440 minutes; start_ts/end_ts in seconds)
   GET /markets/{ticker}/orderbook?depth=N              (yes_dollars / no_dollars = [price, contracts], best bid last)
   If the browser cannot reach the API (e.g. CORS), the page says so and keeps the last good data. */
(function () {
  const API = "https://external-api.demo.kalshi.co/trade-api/v2";
  const base = document.body.dataset.base || "./";
  const $ = id => document.getElementById(id);
  const RANGES = {
    1:    [["1 hour", 3600], ["6 hours", 6 * 3600], ["1 day", 86400], ["3 days", 3 * 86400]],
    60:   [["1 day", 86400], ["7 days", 7 * 86400], ["30 days", 30 * 86400]],
    1440: [["30 days", 30 * 86400], ["90 days", 90 * 86400], ["365 days", 365 * 86400]],
  };
  let timer = null, lastGood = null;

  function fmtTime(sec, period) {
    const d = new Date(sec * 1000);
    const p = n => String(n).padStart(2, "0");
    const date = `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`;
    if (period === 1440) return date;
    return `${date} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
  }

  function seriesFor(ticker) { return ticker.split("-")[0]; }

  function setPeriodOptions() {
    const period = Number($("period").value);
    const rs = RANGES[period];
    const sel = $("range");
    sel.innerHTML = "";
    rs.forEach(([label, sec], i) => {
      const o = document.createElement("option");
      o.value = sec; o.textContent = label; if (i === rs.length - 1) o.selected = true;
      sel.appendChild(o);
    });
  }

  async function getJSON(url) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 12000);
    try {
      const r = await fetch(url, { signal: ctrl.signal, headers: { accept: "application/json" } });
      if (!r.ok) throw new Error("HTTP " + r.status + " from " + url.replace(API, "API"));
      return await r.json();
    } finally { clearTimeout(t); }
  }

  function setStatus(msg, kind) {
    const s = $("status");
    s.className = "notice " + (kind || "info");
    s.textContent = msg;
  }

  function drawChart(points, period) {
    const W = 900, H = 340, L = 60, R = 16, T = 14, B = 40;
    const xs = points.map(p => p.t), t0 = Math.min(...xs), t1 = Math.max(...xs) || t0 + 1;
    const X = t => L + (t - t0) / (t1 - t0 || 1) * (W - L - R);
    const Y = v => T + (1 - v) * (H - T - B);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Contract price chart">`;
    [0, 0.25, 0.5, 0.75, 1].forEach(v => {
      svg += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#e2e8f0"/>`;
      svg += `<text x="${L - 8}" y="${Y(v) + 4}" font-size="12" text-anchor="end" fill="#5d6b7a">$${v.toFixed(2)}</text>`;
    });
    for (let i = 0; i <= 4; i++) {
      const t = t0 + (t1 - t0) * i / 4;
      svg += `<text x="${X(t)}" y="${H - 14}" font-size="12" text-anchor="middle" fill="#5d6b7a">${fmtTime(t, period)}</text>`;
    }
    svg += `<text x="${L}" y="${T - 2}" font-size="12" fill="#5d6b7a">Y: last traded YES price (USD, $0–$1) · X: time (UTC), ${period === 1 ? "1-minute" : period === 60 ? "1-hour" : "1-day"} candles</text>`;
    // break line at gaps (null prices)
    let d = "", pen = false;
    points.forEach(p => {
      if (p.v === null) { pen = false; return; }
      d += (pen ? " L" : " M") + X(p.t).toFixed(1) + " " + Y(p.v).toFixed(1);
      pen = true;
    });
    svg += `<path d="${d}" fill="none" stroke="#00785a" stroke-width="2"/>`;
    points.forEach(p => { if (p.v !== null) svg += `<circle cx="${X(p.t).toFixed(1)}" cy="${Y(p.v).toFixed(1)}" r="2" fill="#00785a"/>`; });
    svg += `</svg>`;
    $("chart").innerHTML = points.some(p => p.v !== null) ? svg : `<p class="blank">No traded prices in this window (empty candlesticks for this market).</p>`;
  }

  function fillTable(id, rows, cols) {
    const tb = $(id);
    tb.innerHTML = "";
    if (!rows.length) { tb.innerHTML = `<tr><td class="blank" colspan="${cols.length}">— none in the API response (unverified / no resting orders)</td></tr>`; return; }
    rows.forEach(r => {
      const tr = document.createElement("tr");
      cols.forEach((c, i) => {
        const td = document.createElement("td");
        td.className = i === 0 ? "num" : "num";
        td.textContent = r[i];
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
  }

  async function loadCandles(ticker, series, period, span) {
    const now = Math.floor(Date.now() / 1000);
    const start = now - Number(span);
    const url = `${API}/series/${encodeURIComponent(series)}/markets/${encodeURIComponent(ticker)}/candlesticks?start_ts=${start}&end_ts=${now}&period_interval=${period}`;
    const data = await getJSON(url);
    const cs = data.candlesticks || [];
    const pts = cs.map(c => ({
      t: c.end_period_ts,
      v: c.price && c.price.close_dollars !== null && c.price.close_dollars !== undefined ? Number(c.price.close_dollars) : null,
      vol: c.volume_fp, oi: c.open_interest_fp,
      bid: c.yes_bid && c.yes_bid.close_dollars, ask: c.yes_ask && c.yes_ask.close_dollars,
    }));
    return { url, pts, count: cs.length };
  }

  async function loadBook(ticker) {
    const url = `${API}/markets/${encodeURIComponent(ticker)}/orderbook?depth=10`;
    const data = await getJSON(url);
    const ob = data.orderbook_fp || {};
    // Bids are ascending (best last). Show best first.
    const yesBids = (ob.yes_dollars || []).map(([p, q]) => [Number(p), Number(q)]).sort((a, b) => b[0] - a[0]);
    // A NO bid at price p is equivalent to a YES ask at 1 - p (docs: orderbook responses).
    const yesAsks = (ob.no_dollars || []).map(([p, q]) => [Number((1 - Number(p)).toFixed(4)), Number(q)]).sort((a, b) => a[0] - b[0]);
    return { url, yesBids, yesAsks };
  }

  async function refresh() {
    const ticker = $("ticker").value.trim();
    if (!ticker) { setStatus("Enter a market ticker.", "warn"); return; }
    const series = $("series").value.trim() || seriesFor(ticker);
    const period = Number($("period").value);
    const span = Number($("range").value);
    setStatus("Loading " + ticker + " from the Kalshi demo API…", "info");
    try {
      const [c, b] = await Promise.all([loadCandles(ticker, series, period, span), loadBook(ticker)]);
      lastGood = { c, b, ticker, period, when: new Date() };
      drawChart(c.pts, period);
      const last = c.pts.filter(p => p.v !== null).slice(-1)[0];
      $("latest").textContent = last ? "$" + last.v.toFixed(4) + " (last traded YES)" : "—";
      $("latestAt").textContent = last ? fmtTime(last.t, period) + " UTC" : "No trades in window";
      fillTable("bids", b.yesBids.slice(0, 10).map(([p, q]) => [p.toFixed(2), q.toFixed(2)]), ["Price ($)", "Contracts"]);
      fillTable("asks", b.yesAsks.slice(0, 10).map(([p, q]) => [p.toFixed(2), q.toFixed(2)]), ["Price ($)", "Contracts"]);
      const recent = c.pts.slice(-12).reverse();
      fillTable("recent", recent.map(p => [fmtTime(p.t, period), p.v === null ? "—" : p.v.toFixed(4), p.vol || "—", p.oi || "—"]), ["Time (UTC)", "Last ($)", "Volume (contracts)", "Open interest"]);
      $("sources").innerHTML = `Sources: <a href="${c.url}" target="_blank" rel="noopener">candlesticks API ↗</a> · <a href="${b.url}" target="_blank" rel="noopener">orderbook API ↗</a> · <a href="https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md" target="_blank" rel="noopener">docs ↗</a>`;
      setStatus(`Updated ${new Date().toISOString().slice(11, 19)} UTC · ${c.count} candles · ${b.yesBids.length + b.yesAsks.length} resting levels. Demo data — not production prices.`, c.count ? "good" : "warn");
    } catch (err) {
      const msg = `Could not reach the demo API from this browser (${err.message}). This can happen if the browser blocks cross-origin requests (see F-16). ` +
        (lastGood ? "Showing the last good data." : "No data to show yet.");
      setStatus(msg, "bad");
    }
  }

  function schedule() {
    if (timer) clearInterval(timer);
    if ($("auto").checked) timer = setInterval(refresh, 30000);
  }

  async function init() {
    try {
      const data = await fetch(base + "data/dashboard.json").then(r => r.json());
      const dl = $("tickers");
      data.rows.filter(r => r.type === "market").forEach(r => {
        const o = document.createElement("option"); o.value = r.ticker; dl.appendChild(o);
      });
      data.rows.filter(r => r.type === "market").slice(0, 1).forEach(() => {});
      ["KXAAAGASM-26NOV30-3.50", "KXDEMOFUTHOURLY-26NOV20H11-UP"].forEach(t => {
        const o = document.createElement("option"); o.value = t; dl.appendChild(o);
      });
    } catch (e) { /* datalist is optional */ }
    $("ticker").value = "KXAAAGASM-26NOV30-3.50";
    setPeriodOptions();
    $("period").addEventListener("change", () => { setPeriodOptions(); refresh(); });
    $("range").addEventListener("change", refresh);
    $("ticker").addEventListener("change", () => { $("series").value = ""; refresh(); });
    $("go").addEventListener("click", refresh);
    $("auto").addEventListener("change", schedule);
    schedule();
    refresh();
  }

  if ($("chart")) init();
})();
