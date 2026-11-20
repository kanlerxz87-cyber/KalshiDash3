/* Live dashboard for the Kalshi DEMO Trade API.
 * Runs in the visitor's browser. Read-only: GET requests to public market-data endpoints only.
 * Endpoints used (verified in docs.kalshi.com, see sources.html):
 *   GET /series?category=...&include_volume=true   (or ?tags=Golf)
 *   GET /markets?series_ticker=...&status=open
 *   GET /markets?series_ticker=...                  (resolved markets: result non-empty)
 *   GET /markets/{ticker}/orderbook
 *   GET /series/{series}/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval
 * No API key is used or needed for these endpoints.
 */
(function () {
  "use strict";

  var API = "https://external-api.demo.kalshi.co/trade-api/v2";
  var CATS = {
    "gas-prices": { label: "Gas prices", seriesUrl: API + "/series?category=Economics&include_volume=true", filter: function (s) { return s.ticker.indexOf("KXAAAGAS") === 0; } },
    elections: { label: "Elections", seriesUrl: API + "/series?category=Elections&include_volume=true" },
    culture: { label: "Culture", seriesUrl: API + "/series?category=Culture&include_volume=true" },
    crypto: { label: "Crypto", seriesUrl: API + "/series?category=Crypto&include_volume=true" },
    golf: { label: "Golf", seriesUrl: API + "/series?tags=Golf&include_volume=true" }
  };
  var WINDOWS = { "1": 6 * 3600, "60": 7 * 86400, "1440": 90 * 86400 };

  var state = { cat: "gas-prices", series: null, seriesTicker: null, market: null, timer: null, chartTimer: null };

  // ---------- DOM helpers (no innerHTML with API data) ----------
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "text") n.textContent = attrs[k];
      else if (k === "cls") n.className = attrs[k];
      else if (k === "href") { n.setAttribute("href", attrs[k]); n.setAttribute("rel", "noopener"); n.setAttribute("target", "_blank"); }
      else if (k === "onclick") n.addEventListener("click", attrs[k]);
      else n.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function td(text, cls) { return el("td", { cls: cls || "", text: text == null || text === "" ? "—" : String(text) }); }
  function tdNode(node, cls) { return el("td", { cls: cls || "" }, [node]); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function setStatus(msg, kind) {
    var box = document.getElementById("live-status");
    box.className = "notice " + (kind === "bad" ? "bad" : kind === "ok" ? "ok" : "info");
    box.textContent = msg;
  }
  function fmtN(s, d) {
    var n = Number(s);
    if (!isFinite(n)) return "—";
    return n.toLocaleString("en-US", { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d });
  }
  function fmtP(s) { return s == null || s === "" ? "—" : "$" + Number(s).toFixed(4); }
  function fmtTs(ts) { return ts ? new Date(ts).toISOString().replace(".000Z", "Z").replace("T", " ") : "—"; }
  function fmtEpoch(sec) { return new Date(sec * 1000).toISOString().replace(".000Z", "Z").replace("T", " "); }

  function getJSON(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " from " + url.replace(API, "…"));
      return r.json();
    });
  }

  // ---------- series ----------
  function loadSeries() {
    var cfg = CATS[state.cat];
    setStatus("Loading " + cfg.label + " series from the Kalshi demo API…", "info");
    var body = document.getElementById("series-body");
    clear(body); body.appendChild(el("tr", null, [el("td", { colspan: "5", cls: "muted", text: "Loading…" })]));
    return getJSON(cfg.seriesUrl).then(function (data) {
      var list = (data.series || []).slice();
      if (cfg.filter) list = list.filter(cfg.filter);
      list.sort(function (a, b) { return Number(b.volume_fp) - Number(a.volume_fp); });
      state.series = list;
      renderSeries();
      setStatus(cfg.label + ": " + list.length + " series loaded from the demo API.", "ok");
      stamp();
    }).catch(function (e) {
      clear(body);
      body.appendChild(el("tr", null, [el("td", { colspan: "5", cls: "muted", text: "Could not load series." })]));
      setStatus("Could not reach the Kalshi demo API from this browser (" + e.message + "). CORS or network may be blocking it. The verified snapshot pages still work.", "bad");
    });
  }

  function renderSeries() {
    var body = document.getElementById("series-body");
    clear(body);
    state.series.slice(0, 30).forEach(function (s) {
      var tr = el("tr", { cls: "clickable" + (s.ticker === state.seriesTicker ? " selected" : "") });
      tr.addEventListener("click", function () { selectSeries(s.ticker); });
      tr.appendChild(td(s.ticker, "mono"));
      tr.appendChild(td(s.title));
      tr.appendChild(td(fmtN(s.volume_fp), "num"));
      tr.appendChild(td(s.frequency));
      tr.appendChild(s.contract_terms_url ? tdNode(el("a", { href: s.contract_terms_url, text: "PDF" })) : td("—"));
      body.appendChild(tr);
    });
    if (!state.series.length) body.appendChild(el("tr", null, [el("td", { colspan: "5", cls: "muted", text: "No series returned." })]));
  }

  function selectSeries(ticker) {
    state.seriesTicker = ticker;
    state.market = null;
    renderSeries();
    document.getElementById("series-label").textContent = "Series " + ticker + " (open markets, sorted by volume).";
    clearMarket();
    loadMarkets();
    loadResolved();
  }

  // ---------- markets ----------
  function fetchAll(url) {
    var out = [];
    function page(cursor) {
      var u = url + (cursor ? "&cursor=" + encodeURIComponent(cursor) : "");
      return getJSON(u).then(function (d) {
        out = out.concat(d.markets || []);
        if (d.cursor && out.length < 1000) return page(d.cursor);
        return out;
      });
    }
    return page("");
  }

  function loadMarkets() {
    var t = state.seriesTicker;
    var body = document.getElementById("market-body");
    clear(body);
    body.appendChild(el("tr", null, [el("td", { colspan: "12", cls: "muted", text: "Loading open markets…" })]));
    return fetchAll(API + "/markets?series_ticker=" + encodeURIComponent(t) + "&status=open&limit=200").then(function (ms) {
      if (t !== state.seriesTicker) return;
      ms.sort(function (a, b) { return Number(b.volume_fp) - Number(a.volume_fp); });
      clear(body);
      if (!ms.length) {
        body.appendChild(el("tr", null, [el("td", { colspan: "12", cls: "muted", text: "No open markets returned for this series right now." })]));
      }
      ms.forEach(function (m) {
        var notional = Number(m.notional_value_dollars || "1");
        var spread = (Number(m.yes_ask_dollars) > 0 && Number(m.yes_bid_dollars) > 0 && Number(m.yes_ask_dollars) < 1)
          ? (Number(m.yes_ask_dollars) - Number(m.yes_bid_dollars)).toFixed(4) : "—";
        var tr = el("tr", { cls: "clickable" + (state.market && state.market.ticker === m.ticker ? " selected" : "") });
        tr.addEventListener("click", function () { selectMarket(m, tr); });
        tr.appendChild(td(m.ticker, "mono"));
        tr.appendChild(td(m.title));
        tr.appendChild(td(fmtP(m.last_price_dollars), "num"));
        tr.appendChild(td(fmtP(m.yes_bid_dollars), "num"));
        tr.appendChild(td(fmtP(m.yes_ask_dollars), "num"));
        tr.appendChild(td(spread === "—" ? "—" : "$" + spread, "num"));
        tr.appendChild(td(fmtN(m.yes_bid_size_fp), "num"));
        tr.appendChild(td(fmtN(m.yes_ask_size_fp), "num"));
        tr.appendChild(td(fmtN(m.volume_fp), "num"));
        tr.appendChild(td("$" + fmtN(Number(m.volume_fp) * notional), "num"));
        tr.appendChild(td(fmtN(m.open_interest_fp), "num"));
        tr.appendChild(td(m.close_time));
        body.appendChild(tr);
      });
      stamp();
    }).catch(function (e) {
      clear(body);
      body.appendChild(el("tr", null, [el("td", { colspan: "12", cls: "muted", text: "Could not load markets (" + e.message + ")." })]));
    });
  }

  function loadResolved() {
    var t = state.seriesTicker;
    var body = document.getElementById("resolved-body");
    clear(body);
    body.appendChild(el("tr", null, [el("td", { colspan: "6", cls: "muted", text: "Loading…" })]));
    return fetchAll(API + "/markets?series_ticker=" + encodeURIComponent(t) + "&limit=200").then(function (ms) {
      if (t !== state.seriesTicker) return;
      var res = ms.filter(function (m) { return m.result; });
      clear(body);
      if (!res.length) body.appendChild(el("tr", null, [el("td", { colspan: "6", cls: "muted", text: "No resolved markets in this series yet." })]));
      res.forEach(function (m) {
        var tr = el("tr");
        tr.appendChild(td(m.ticker, "mono"));
        tr.appendChild(td(m.title));
        tr.appendChild(tdNode(el("span", { cls: "badge " + (m.result === "yes" ? "ok" : "bad"), text: String(m.result).toUpperCase() })));
        tr.appendChild(td(fmtP(m.settlement_value_dollars), "num"));
        tr.appendChild(td(m.close_time));
        tr.appendChild(td(m.updated_time));
        body.appendChild(tr);
      });
    }).catch(function (e) {
      clear(body);
      body.appendChild(el("tr", null, [el("td", { colspan: "6", cls: "muted", text: "Could not load resolved markets (" + e.message + ")." })]));
    });
  }

  // ---------- market detail ----------
  function selectMarket(m, rowEl) {
    state.market = m;
    document.getElementById("market-label").textContent = m.ticker + " · " + m.title + " · status " + m.status + (m.result ? " · result " + m.result : "");
    renderMarketRowsHighlight();
    if (rowEl) rowEl.classList.add("selected");
    loadBook();
    loadChart();
  }
  function renderMarketRowsHighlight() {
    var rows = document.querySelectorAll("#market-body tr");
    rows.forEach(function (r) { r.classList.remove("selected"); });
  }
  function clearMarket() {
    document.getElementById("market-label").textContent = "Select a market above.";
    clear(document.getElementById("chart"));
    document.getElementById("chart").appendChild(el("div", { cls: "muted small", text: "No market selected." }));
    var b = document.getElementById("book-body"); clear(b);
    b.appendChild(el("tr", null, [el("td", { colspan: "4", cls: "muted", text: "No market selected." })]));
  }

  function loadBook() {
    var m = state.market; if (!m) return;
    var body = document.getElementById("book-body");
    return getJSON(API + "/markets/" + encodeURIComponent(m.ticker) + "/orderbook").then(function (d) {
      if (!state.market || state.market.ticker !== m.ticker) return;
      var ob = d.orderbook_fp || {};
      var yes = (ob.yes_dollars || []).slice().reverse().slice(0, 10); // highest bid first
      var no = (ob.no_dollars || []).slice().reverse().slice(0, 10);
      clear(body);
      var n = Math.max(yes.length, no.length);
      if (!n) { body.appendChild(el("tr", null, [el("td", { colspan: "4", cls: "muted", text: "Empty orderbook: no resting orders right now." })])); return; }
      for (var i = 0; i < n; i++) {
        var y = yes[i], nb = no[i];
        var askPrice = nb ? (1 - Number(nb[0])).toFixed(4) : null;
        var tr = el("tr");
        tr.appendChild(td(y ? "$" + y[0] : "—", "num"));
        tr.appendChild(td(y ? fmtN(y[1]) : "—", "num"));
        tr.appendChild(td(askPrice ? "$" + askPrice : "—", "num"));
        tr.appendChild(td(nb ? fmtN(nb[1]) : "—", "num"));
        body.appendChild(tr);
      }
      stamp();
    }).catch(function (e) {
      clear(body);
      body.appendChild(el("tr", null, [el("td", { colspan: "4", cls: "muted", text: "Could not load orderbook (" + e.message + ")." })]));
    });
  }

  function loadChart() {
    var m = state.market; if (!m) return;
    var period = document.getElementById("interval").value;
    if (period === "seconds") return;
    var end = Math.floor(Date.now() / 1000);
    var start = end - WINDOWS[period];
    var url = API + "/series/" + encodeURIComponent(m.series_ticker || state.seriesTicker) + "/markets/" + encodeURIComponent(m.ticker) +
      "/candlesticks?start_ts=" + start + "&end_ts=" + end + "&period_interval=" + period;
    var box = document.getElementById("chart");
    return getJSON(url).then(function (d) {
      if (!state.market || state.market.ticker !== m.ticker) return;
      var pts = (d.candlesticks || []).map(function (c) {
        return {
          t: c.end_period_ts,
          trade: c.price && c.price.close_dollars != null ? Number(c.price.close_dollars) : null,
          bid: c.yes_bid && c.yes_bid.close_dollars != null ? Number(c.yes_bid.close_dollars) : null,
          ask: c.yes_ask && c.yes_ask.close_dollars != null ? Number(c.yes_ask.close_dollars) : null
        };
      });
      drawChart(box, pts, period);
      stamp();
    }).catch(function (e) {
      clear(box);
      box.appendChild(el("div", { cls: "muted small", text: "Could not load price history (" + e.message + ")." }));
    });
  }

  function drawChart(box, pts, period) {
    clear(box);
    var W = 900, H = 320, L = 56, R = 16, T = 12, B = 44;
    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("width", "100%");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Contract price over time");
    function line(x1, y1, x2, y2, stroke, dash) {
      var l = document.createElementNS(NS, "line");
      l.setAttribute("x1", x1); l.setAttribute("y1", y1); l.setAttribute("x2", x2); l.setAttribute("y2", y2);
      l.setAttribute("stroke", stroke || "#e2e6ee"); if (dash) l.setAttribute("stroke-dasharray", dash);
      svg.appendChild(l);
    }
    function text(x, y, s, anchor) {
      var t = document.createElementNS(NS, "text");
      t.setAttribute("x", x); t.setAttribute("y", y); t.setAttribute("text-anchor", anchor || "start");
      t.textContent = s; svg.appendChild(t);
    }
    function poly(key, color, dash) {
      var coords = [];
      pts.forEach(function (p, i) {
        if (p[key] == null) return;
        var x = pts.length > 1 ? L + (W - L - R) * (p.t - pts[0].t) / Math.max(1, pts[pts.length - 1].t - pts[0].t) : L;
        var y = T + (H - T - B) * (1 - p[key]);
        coords.push(x.toFixed(1) + "," + y.toFixed(1));
      });
      if (coords.length < 2) return;
      var pl = document.createElementNS(NS, "polyline");
      pl.setAttribute("points", coords.join(" "));
      pl.setAttribute("fill", "none"); pl.setAttribute("stroke", color); pl.setAttribute("stroke-width", dash ? "1.5" : "2");
      if (dash) pl.setAttribute("stroke-dasharray", dash);
      svg.appendChild(pl);
    }
    // y gridlines 0..1
    [0, 0.25, 0.5, 0.75, 1].forEach(function (v) {
      var y = T + (H - T - B) * (1 - v);
      line(L, y, W - R, y);
      text(L - 8, y + 4, v.toFixed(2), "end");
    });
    text(L, H - 6, "Y: contract price (USD, 0–1)");
    if (!pts.length) {
      text(L + 12, T + 40, "No candlesticks returned for this window (no trades or quotes yet).");
    } else {
      // x labels
      var t0 = pts[0].t, t1 = pts[pts.length - 1].t;
      text(L, H - 22, "X: " + fmtEpoch(t0) + " UTC");
      text(W - R, H - 22, fmtEpoch(t1) + " UTC", "end");
      poly("trade", "#2450a6");
      poly("bid", "#0b7a5c", "4 3");
      poly("ask", "#a11d2e", "4 3");
      var last = pts[pts.length - 1];
      var lastTxt = "Last: " + (last.trade == null ? "—" : last.trade.toFixed(4)) + " · bid " + (last.bid == null ? "—" : last.bid.toFixed(4)) + " · ask " + (last.ask == null ? "—" : last.ask.toFixed(4)) + " · period " + period + " min" ;
      text(W - R, T + 14, lastTxt, "end");
    }
    box.appendChild(svg);
  }

  // ---------- refresh & wiring ----------
  function stamp() {
    document.getElementById("last-updated").textContent = "Last updated " + new Date().toISOString().replace(".000Z", "Z").replace("T", " ") + " (UTC)";
  }
  function startTimers() {
    clearInterval(state.timer);
    state.timer = setInterval(function () {
      if (!document.getElementById("autorefresh").checked) return;
      if (state.seriesTicker) { loadMarkets(); loadResolved(); }
      if (state.market) loadBook();
    }, 15000);
    clearInterval(state.chartTimer);
    state.chartTimer = setInterval(function () {
      if (!document.getElementById("autorefresh").checked) return;
      if (state.market) loadChart();
    }, 60000);
  }

  function init() {
    var q = new URLSearchParams(window.location.search).get("cat");
    if (q && CATS[q]) state.cat = q;
    var sel = document.getElementById("cat");
    sel.value = state.cat;
    sel.addEventListener("change", function () {
      state.cat = sel.value; state.seriesTicker = null; state.market = null;
      clearMarket();
      document.getElementById("market-body").innerHTML = "";
      document.getElementById("resolved-body").innerHTML = "";
      document.getElementById("series-label").textContent = "Select a series above.";
      loadSeries();
    });
    document.getElementById("interval").addEventListener("change", loadChart);
    clearMarket();
    loadSeries().then(function () {
      if (state.series && state.series.length) selectSeries(state.series[0].ticker);
    });
    startTimers();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
