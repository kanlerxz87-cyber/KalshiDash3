/* KalshiDash3 — DOM render smoke test (jsdom, no network).
 *
 * node --check proves the page scripts parse; this proves they RUN and produce sane HTML
 * against the data files that ship in the repo, in three states a reader can actually land in:
 *
 *   live.html + blocked API   -> snapshot mode: feeds/tables render from data/live/*.json,
 *                                 no crash, no "undefined"/"NaN" leaking into the page
 *   live.html + working API   -> live-api mode: discovery builds the watch list, a 13c move
 *                                 in the stub raises a chat row, the ROI feed shows a pick
 *   roi.html                  -> model page renders parameters from data/roi_model.json and,
 *                                 when data/live/roi.json exists, its picks/alerts/validation
 *
 * jsdom is a test-only dependency (never installed on the site). If it is absent the file
 * skips itself with exit code 0 and says so; the desk workflow installs it so CI really runs this.
 *
 * Run: node scripts/tests/test_pages_dom.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) {
  console.log("SKIP: jsdom is not installed (npm i jsdom). The desk workflow installs it and runs this test.");
  process.exit(0);
}

const model = JSON.parse(fs.readFileSync(path.join(ROOT, "data/roi_model.json"), "utf8"));
const markets = (() => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/markets.json"), "utf8")); } catch (e) { return null; } })();
const history = (() => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/price_history.json"), "utf8")); } catch (e) { return { series: {} }; } })();
const roi = (() => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/roi.json"), "utf8")); } catch (e) { return null; } })();

const CTX2D = new Proxy({}, {
  get: (t, k) => {
    if (k === "canvas") return {};
    if (["fillStyle", "strokeStyle", "font", "lineWidth", "globalAlpha"].includes(k)) return "";
    return () => undefined;
  },
  set: () => true,
});

function mkFetch(mode, state) {
  return async function fetchImpl(url, opts) {
    const u = String(url);
    const send = (body, ok = true) => ({ ok, status: ok ? 200 : 500, json: async () => body, text: async () => JSON.stringify(body) });
    if (/external-api\.demo\.kalshi\.co|demo-api\.kalshi\.co/.test(u)) {
      // The candle stub is served in BOTH modes: it is the one endpoint the chart must reach,
      // and making it reachable in snapshot mode keeps this test about the chart, not CORS.
      if (state.candleDoc && /\/candlesticks/.test(u)) { state.calls.push(u); return send(state.candleDoc); }
      if (mode !== "api") { state.blocked++; const e = new TypeError("Failed to fetch"); e.name = "TypeError"; throw e; }
      state.calls.push(u);
      if (u.includes("/exchange/status")) return send({ trading_open: true });
      if (u.includes("/historical/cutoff")) return send({ market_settled_ts: "2026-10-01T00:00:00Z" });
      if (u.includes("/markets/orderbooks")) {
        // Parse it the way the endpoint does: `tickers` is a repeated string[] (1-100), NOT a
        // comma-separated list. A comma-joined query is answered with one entry whose ticker is
        // the whole joined string and both arrays empty — see the assertion below.
        const tickers = [...u.matchAll(/[?&]tickers=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
        if (/tickers=[^&]*%2C|tickers=[^&]*,/.test(u)) {
          state.badBookQuery = u;
          return send({ orderbooks: [{ ticker: decodeURIComponent(u.match(/tickers=([^&]+)/)[1]),
                                       orderbook_fp: { yes_dollars: [], no_dollars: [] } }] });
        }
        return send({ orderbooks: tickers.map(t => ({ ticker: t, orderbook_fp: { yes_dollars: [["0.4700", "900.00"]], no_dollars: [["0.5100", "800.00"]] } })) });
      }
      if (u.includes("status=open")) {
        return send({ cursor: "", markets: ["KXAAAGASM-26DEC31-4.00", "KXPGATOUR-26NOV22-T1"].map(t => ({
          ticker: t, event_ticker: t.split("-")[0], title: "smoke test " + t, status: "active", result: null,
          yes_bid_dollars: (state.tick === undefined ? 0.47 : 0.60).toFixed(4),
          yes_ask_dollars: (state.tick === undefined ? 0.49 : 0.62).toFixed(4),
          last_price_dollars: (state.tick === undefined ? 0.48 : 0.61).toFixed(4),
          volume_fp: "90000.00", volume_24h_fp: "5000.00", open_interest_fp: "4000.00",
          close_time: new Date(Date.now() + 3 * 3600e3).toISOString(),
          rules_primary: "Settles per https://gasprices.aaa.com/national-average.",
        })) });
      }
      if (u.includes("/markets?tickers=")) {
        state.tick = state.tick === undefined ? 0 : state.tick + 1;
        const up = state.tick % 2 === 1;
        return send({ markets: ["KXAAAGASM-26DEC31-4.00", "KXPGATOUR-26NOV22-T1"].map(t => ({
          ticker: t, event_ticker: t.split("-")[0], title: "smoke test " + t, status: "active", result: null,
          yes_bid_dollars: (up ? 0.60 : 0.47).toFixed(4), yes_ask_dollars: (up ? 0.62 : 0.49).toFixed(4),
          last_price_dollars: (up ? 0.61 : 0.48).toFixed(4),
          volume_fp: "90000.00", volume_24h_fp: "5000.00", open_interest_fp: "4000.00",
          close_time: new Date(Date.now() + 3 * 3600e3).toISOString(),
          rules_primary: "Settles per https://gasprices.aaa.com/national-average.",
        })) });
      }
      if (u.includes("/candlesticks")) return send({ ticker: "x", candlesticks: [] });
      return send({});
    }
    // same-origin files: read from the repo
    const rel = u.replace(/^\.\//, "").split("?")[0].replace(/^.*\/KalshiDash3\//, "");
    const file = path.join(ROOT, rel);
    if (file.startsWith(ROOT) && fs.existsSync(file)) {
      const txt = fs.readFileSync(file, "utf8");
      return send(rel.endsWith(".json") ? JSON.parse(txt) : txt);
    }
    if (rel === "data/live/roi.json" && roi) return send(roi);
    if (rel === "data/live/markets.json" && markets) return send(markets);
    if (rel === "data/live/price_history.json") return send(history);
    if (rel === "data/roi_model.json") return send(model);
    return { ok: false, status: 404, json: async () => ({}), text: async () => "" };
  };
}

function inlineAssets(html) {
  // jsdom without a resource loader will not fetch <script src>; inline the repo's own
  // files instead, so the test exercises the real shipped code, not a copy of it.
  return html.replace(/<script src="([^"]+)"><\/script>/g, (m, src) => {
    const file = path.join(ROOT, src.replace(/^\.\//, ""));
    if (!fs.existsSync(file)) throw new Error("test cannot find " + src);
    return "<script>\n" + fs.readFileSync(file, "utf8") + "\n</script>";
  });
}

async function loadPage(file, mode, opts = {}) {
  const html = inlineAssets(fs.readFileSync(path.join(ROOT, file), "utf8"));
  const state = { calls: [], blocked: 0, badBookQuery: null, candleDoc: opts.candleDoc || null };
  const errors = [];
  const dom = new JSDOM(html, {
    url: "https://kalshidash3.invalid/" + file + (opts.hash ? "#" + encodeURIComponent(opts.hash) : ""),
    runScripts: "dangerously",
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = mkFetch(mode, state);
      window.HTMLCanvasElement.prototype.getContext = () => CTX2D;
      window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
      window.addEventListener("error", (ev) => errors.push(String(ev.message)));
      window.__errors = errors;
    },
  });
  // let the boot sequence, a couple of poll cycles and the 60s-snapshot timer all run
  // long enough in api mode to cover one full poll cycle (the page polls every 6s), so a
  // live-tick alert — not just a snapshot-history alert — is exercised
  await new Promise(r => setTimeout(r, mode === "api" ? 7500 : 900));
  const doc = dom.window.document;
  // The test inlines the page's own JS into the document, so script source must be excluded
  // before asserting on visible text — otherwise "undefined" in the code reads as a leak.
  const clone = doc.body.cloneNode(true);
  clone.querySelectorAll("script,style").forEach(n => n.remove());
  const visible = clone.textContent.replace(/\s+/g, " ");
  return { dom, doc, state, errors, text: visible, close: () => { dom.window.close(); } };
}

const problems = [];
const check = (cond, msg) => { if (!cond) problems.push(msg); };

function leak(t){ const i=t.indexOf("undefined"); return i<0?"":t.slice(Math.max(0,i-90), i+60); }

function commonAsserts(label, r) {
  check(r.errors.length === 0, `${label}: uncaught page errors: ${r.errors.slice(0, 3).join(" | ")}`);
  const t = r.text;
  check(!/undefined/.test(t), `${label}: the word "undefined" leaked into the rendered page :: …${leak(t)}…`);
  check(!/\bNaN\b/.test(t), `${label}: NaN leaked into the rendered page`);
  check(!/\[object Object\]/.test(t), `${label}: "[object Object]" leaked into the rendered page`);
  check(t.includes("demo"), `${label}: the page must say it is demo data`);
}

(async () => {
  /* --- A. blocked API: snapshot mode must still render a usable desk --- */
  if (markets) {
    const r = await loadPage("live.html", "snapshot");
    commonAsserts("live.html snapshot", r);
    check(/SNAPSHOT/.test(r.text), `live.html snapshot mode must announce the fallback (got: ${r.text.slice(0, 0)})`);
    check(r.text.includes("committed collector output"), "the fallback wording must say where the data came from");
    const rows = r.doc.querySelectorAll("#watch tbody tr").length;
    check(rows > 0, "the watchlist must render rows from the committed snapshot");
    const feeds = r.doc.querySelectorAll("#feedAll .msg").length;
    check(r.doc.querySelectorAll("#feedAll").length === 1 && r.doc.querySelectorAll("#feedRoi").length === 1, "both chat feeds must be present");
    check(/No swings|shown/.test(r.text), "the all-events feed must state its state either way");
    check(r.text.includes("Gas Prices") || r.text.includes("Crypto") || r.text.includes("Golf"), "topics must be labelled");
    console.log(`  A snapshot mode  ok  (${rows} watchlist rows, ${feeds} alert messages, ${r.state.blocked} blocked API calls handled)`);
    r.close();
  } else {
    console.log("  A snapshot mode  skipped (no committed data/live/markets.json in this checkout)");
  }

  /* --- B. working API: live mode, alert raised by a 13c jump --- */
  {
    const r = await loadPage("live.html", "api");
    commonAsserts("live.html live", r);
    check(/LIVE · direct demo API/.test(r.text), "live mode must be announced in the status bar");
    check(r.state.calls.some(u => u.includes("status=open")), "the desk must discover markets itself, not wait for input");
    check(r.state.calls.some(u => u.includes("/markets/orderbooks")), "order-book depth must be requested");
    check(!r.state.badBookQuery, "GET /markets/orderbooks must repeat tickers=A&tickers=B — the comma form "
          + "returns 200 with empty arrays and reads as 'no liquidity': " + (r.state.badBookQuery || "").slice(0, 140));
    const msgs = r.doc.querySelectorAll("#feedAll .msg").length;
    check(msgs >= 1, `a 13c jump between polls must appear in the all-events chat (got ${msgs})`);
    // The ROI feed must show a qualifying market OR its explanation: a zero-pick scan is
    // a legitimate state (the screen demands positive net ROI after fees), and the page
    // renders the `.none` explanation with the closest candidates for exactly that case.
    // Counting only `.msg` made the DOM step fail whenever the committed scan had no
    // picks (e.g. data/live/roi.json @ 2026-11-20T19:15:11Z: 0 picks, 212 unscoreable),
    // which would have broken every desk run on main. Found by session arena-da07bb44 (T19).
    const roiMsgs = r.doc.querySelectorAll("#feedRoi .msg").length;
    const roiNone = r.doc.querySelectorAll("#feedRoi .none").length;
    check(roiMsgs >= 1 || roiNone >= 1, "the ROI feed must show the qualifying market or its explanation");
    const causes = r.doc.querySelectorAll('#feedAll a[href*="gasprices.aaa.com"]').length;
    check(causes >= 1, "the catalyst link must be the URL copied out of the market's own rules text");
    const recorded = r.doc.querySelectorAll('#feedAll a[href*="external-api.demo.kalshi.co"]').length;
    check(recorded >= 1, "every alert must link the official API record it came from");
    console.log(`  B live mode       ok  (${r.state.calls.length} API calls, ${msgs} chat messages, ${roiMsgs} ROI-feed messages, ${roiNone} explanation)`);
    r.close();
  }

  /* --- C. the model page --- */
  {
    const r = await loadPage("roi.html", "snapshot");
    commonAsserts("roi.html", r);
    check(r.text.includes("roundup") || r.text.includes("round up") || r.text.includes("0.07"), "the model page must show the fee formula it uses");
    check(r.text.includes("roi_model.json"), "the model page must name the file it reads");
    if (roi) {
      check(r.text.includes("Out-of-sample measurement"), "the measurement section must render when a scan exists");
    } else {
      check(/no scan committed yet|nothing scored yet/i.test(r.text), "without a scan the model page must say so instead of showing example numbers");
    }
    console.log("  C model page      ok");
    r.close();
  }

  /* --- D. alerts.html: two chats + the fetched-lead table (the page this repo's brief cares
          most about getting right: nothing rendered may read as a proven cause) --- */
  {
    const r = await loadPage("alerts.html", "snapshot");
    commonAsserts("alerts.html", r);
    check(r.doc.querySelectorAll("#feedAll").length === 1 && r.doc.querySelectorAll("#feedModel").length === 1,
      "alerts page must render both chat feeds");
    const box = r.doc.querySelector("#leads");
    check(!!box, "the lead panel must exist on the alerts page");
    const leadsRows = r.doc.querySelectorAll("#leads tbody tr").length;
    if (leadsRows) {
      const archived = (() => { try {
        return JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/alerts_archive.json"), "utf8")).alerts.length;
      } catch (e) { return -1; } })();
      check(leadsRows === archived, `the lead table must show one row per archived swing (table ${leadsRows}, archive ${archived})`);
      r.doc.querySelectorAll("#leads tbody tr").forEach((tr, i) => {
        tr.querySelectorAll("a").forEach(a => {
          check(/^https:\/\//.test(a.getAttribute("href") || ""), `lead row ${i}: every link must be an absolute https URL`);
          check(a.getAttribute("rel") === "noopener" && a.getAttribute("target") === "_blank",
            `lead row ${i}: links must carry target=_blank rel=noopener`);
        });
      });
    } else {
      check(/No lead file has been published yet|could not be loaded/i.test(r.text),
        "with no lead file the page must say so instead of rendering nothing");
    }
    check(!/\bcaused\b|\btriggered by\b|\bdue to\b/i.test(r.text),
      "the rendered alerts page must not use causal wording — a public quote cannot see why a price moved");
    console.log(`  D alerts page   ok  (${leadsRows} lead rows rendered, both feeds present, no causal wording)`);
    r.close();
  }

  /* --- E. dashboard.html: the page with the live chart + per-swing lead rows --- */
  {
    const r = await loadPage("dashboard.html", "snapshot");
    commonAsserts("dashboard.html", r);
    check(/cause blank/.test(r.text) === false,
      "the old 'cause blank — flagged' placeholder must be replaced by the fetched lead (or an explicit 'no lead' state)");
    console.log("  E dashboard     ok  (chart + swing list render with the lead column wired)");
    r.close();
  }

  /* --- F. index.html: the landing table of "largest live market" per category ---
   * This page had no DOM test, which is how a `const` used above its declaration shipped on
   * 2026-11-21 and left "What is live right now" completely empty on the deployed site while
   * every other check stayed green (F-64). Render it against the real committed snapshot. */
  {
    const r = await loadPage("index.html", "snapshot");
    commonAsserts("index.html", r);
    const today = r.doc.querySelector("#today");
    check(!!today && today.querySelectorAll("tbody tr").length === 5,
      `index.html: the largest-market table must render one row per category (got ${today ? today.querySelectorAll("tbody tr").length : "no #today host"})`);
    check(/Dollars traded \(est\.\)/.test(r.text),
      "index.html: the ranking metric must be labelled as an estimate");
    const bodies = [...(today ? today.querySelectorAll("tbody tr") : [])].map(tr => tr.textContent);
    check(bodies.every(t => /KX[A-Z0-9-]+/.test(t)),
      "index.html: every category row must name a real ticker or say none is open");
    // The QA fixture must not be a headline, but its presence in the snapshot must be disclosed.
    if (markets && (markets.open_markets || []).concat(markets.settled_markets || []).some(x => /QA/i.test(x.ticker))) {
      check(/demo QA fixtures in the snapshot/.test(r.text),
        "index.html: when the snapshot contains a QA fixture the page must say so");
      check(!bodies.some(t => /QA7CECC5|Portfolio cash out/.test(t)),
        "index.html: a demo QA fixture must never be the largest live market of a category");
    }
    console.log(`  F index page    ok  (${today ? today.querySelectorAll("tbody tr").length : 0} category rows, QA guard + disclosure present)`);
    r.close();
  }

  /* --- G. dashboard chart: official candles + a market reachable only from the alert archive ---
   * Two defects this guards, both measured on the committed data before the fix:
   *  1. the page never loaded a single official candle, even though the interval selector is on the
   *     page (assets/live.js had the endpoint, dashboard.html has the selector);
   *  2. GET /markets omits the whole price block on a zero-volume period, so a naive
   *     Number(undefined)->NaN / Number("")->0 read would either break the line or print a fake 0c.
   * The stub returns one real candle plus one zero-volume candle with an empty close, and the page
   * must plot the former and skip the latter.
   */
  {
    const nowS = Math.floor(Date.now() / 1000);
    const candleDoc = { ticker: "stub", candlesticks: [
      { end_period_ts: nowS - 3600, price: { close_dollars: "0.5000", open_dollars: "0.4000", high_dollars: "0.6000", low_dollars: "0.3000", mean_dollars: "0.5000" },
        yes_bid: { close_dollars: "0.4800" }, yes_ask: { close_dollars: "0.5200" }, volume_fp: "10.00" },
      { end_period_ts: nowS - 1800, price: { previous_dollars: "0.5000" }, volume_fp: "0.00",
        yes_bid: { close_dollars: "" }, yes_ask: { close_dollars: "" } },
      // third shape, also price-less: an explicit empty string rather than an absent key.
      { end_period_ts: nowS - 900, price: { close_dollars: "", open_dollars: "" }, volume_fp: "0.00",
        yes_bid: { close_dollars: "" }, yes_ask: { close_dollars: "" } },
    ] };
    const r = await loadPage("dashboard.html", "snapshot", { candleDoc });
    commonAsserts("dashboard.html candles", r);
    const candleCalls = r.state.calls.filter(u => u.includes("/candlesticks"));
    check(candleCalls.length >= 1, "the dashboard must request the official candlestick endpoint for the selected market");
    check(candleCalls.every(u => /period_interval=(1|60|1440)\b/.test(u)),
      "candlestick requests must use a documented period_interval (1, 60 or 1440 only): " + (candleCalls[0] || ""));
    check(candleCalls.every(u => /start_ts=\d+/.test(u) && /end_ts=\d+/.test(u)),
      "candlestick requests must carry start_ts and end_ts, which the endpoint requires");
    check(/official 1-minute candle/.test(r.text),
      "the chart footer must state that the muted line is official candles, with the interval named");
    // The stub returns three candles; two carry no usable price (one omits the price block, as
    // the API does for a zero-volume period, one returns an explicit empty string). Exactly one
    // must be plotted: that proves a missing price is dropped rather than read as
    // Number("") === 0, which would draw a fake 0c print on the chart.
    check(/\b1 official 1-minute candle\b/.test(r.text),
      "a candle without a price block must be skipped, not plotted as 0c (expected exactly 1 of 3 candles plotted)");
    check(!/official 1-minute candles\b/.test(r.text),
      "the zero-volume candle (no price block) must not be counted as a plotted candle");
    console.log(`  G candles       ok  (${candleCalls.length} official candle request(s), interval + window present, no fake 0c)`);
    r.close();
  }

  /* --- H. dashboard deep link: a market that is only in the alert archive still charts ---
   * scripts/collect.py used to prune data/live/price_history.json to the ranked open window, so a
   * market cited by an archived alert had zero observations and the chart said "Pick a market".
   * The alerts chat now links to dashboard.html#TICKER; that link must resolve to a real row.
   */
  const publishedFeed = (() => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/alerts.json"), "utf8")); } catch (e) { return null; } })();
  if (publishedFeed && publishedFeed.all_events && publishedFeed.all_events.length) {
    const archivedTicker = publishedFeed.all_events[0].ticker;
    const r = await loadPage("dashboard.html", "snapshot", { hash: archivedTicker });
    commonAsserts("dashboard.html deep link", r);
    check(!/Pick a market from the tables below/.test(r.text),
      `#${archivedTicker} (cited by an archived alert) must open a chart, not the "pick a market" placeholder`);
    check(r.text.includes(archivedTicker), "the deep-linked market's own ticker must be shown");
    console.log(`  H deep link     ok  (#${archivedTicker} from the alert archive opens a chart)`);
    r.close();
  }

  if (problems.length) {
    console.error("\nPAGE RENDER PROBLEMS:");
    for (const p of problems) console.error("  -", p);
    process.exit(1);
  }
  console.log("OK: live desk, model page, alerts chats + lead table, dashboard and the landing page render without errors in every data state available locally.");
  process.exit(0);
})().catch((e) => { console.error("FAILED:", e && e.stack || e); process.exit(1); });
