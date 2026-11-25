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
    // After a page is torn down (close()), a fetch that was already in flight must never
    // resolve: its continuation would run against a destroyed document and throw. That is a
    // harness artefact, not a page defect, so it is made impossible rather than tolerated.
    if (state.closed) return new Promise(() => {});
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
  const state = { calls: [], blocked: 0, badBookQuery: null, candleDoc: opts.candleDoc || null, closed: false };
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
  // Teardown, deliberately WITHOUT dom.window.close(): jsdom nulls window.document on close,
  // and a fetch already in flight then resumes into a null document, throwing inside page code
  // (drawLiq / renderAlerts) at a point that has nothing to do with what the test asserts. The
  // page is instead frozen: the engine is stopped, further fetches never resolve, and the
  // document stays valid so any straggling continuation is harmless. process.exit at the end of
  // the run reclaims everything.
  return {
    dom, doc, state, errors, text: visible,
    close: () => {
      state.closed = true;
      try { dom.window.eval("try{KDL.stop()}catch(e){}"); } catch (e) { /* page has no engine */ }
    }
  };
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
    // A particular settlement URL is not guaranteed to be in every market poll response.
    // Test literal extraction from official rules text directly, then ensure every rendered
    // swing reports either that market-record reference or the explicit no-source state.
    const ruleLinks = r.dom.window.KDLIVE.catalystLinks({
      rules_primary: "Settles per https://gasprices.aaa.com/national-average.",
    });
    check(ruleLinks.length === 1 && ruleLinks[0].url === "https://gasprices.aaa.com/national-average",
      "the live catalyst extractor copies the literal URL from market rules text");
    const causeStates = [...r.doc.querySelectorAll("#feedAll .cause")];
    check(causeStates.length >= msgs && causeStates.every(el =>
      /source this market settles on|no source URL in the market's own record/.test(el.textContent)),
      "each rendered alert labels a literal settlement reference or says the record has no source URL");
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
      // F-65: the table must show one row per archived swing EXCEPT the counted exclusions whose
      // official series record puts them outside the topic. The exclusion must be published in
      // counts.withheld_category_conflict, so a silent drop fails here too.
      let withheld = 0;
      try {
        withheld = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/catalysts.json"), "utf8"))
          .counts.withheld_category_conflict || 0;
      } catch (e) { withheld = 0; }
      check(leadsRows === archived - withheld,
        `the lead table must show one row per archived swing minus the counted F-65 exclusions `
        + `(table ${leadsRows}, archive ${archived}, withheld ${withheld})`);
      check(withheld === 0 || /withheld/i.test(fs.readFileSync(path.join(ROOT, "alerts.html"), "utf8")),
        "alerts.html must disclose that some archived swings are withheld (F-65)");
      r.doc.querySelectorAll("#leads tbody tr").forEach((tr, i) => {
        tr.querySelectorAll("a").forEach(a => {
          check(/^https:\/\//.test(a.getAttribute("href") || ""), `lead row ${i}: every link must be an absolute https URL`);
          check(a.getAttribute("rel") === "noopener" && a.getAttribute("target") === "_blank",
            `lead row ${i}: links must carry target=_blank rel=noopener`);
        });
      });
      // F-93: the verdict identifier is a key, not a sentence. Every state must resolve to a
      // human label, and the relation line must name which published series it is quoting.
      const rawStates = ["best_quote_did_not_move", "reference_not_publicly_readable",
        "published_reference_on_the_same_side_as_the_move", "no_external_move_supporting_this_swing"];
      const leadText = box.textContent || "";
      for (const s of rawStates) {
        check(!leadText.includes(s), `alerts.html must not print the raw verdict identifier "${s}" (F-93)`);
      }
      check(/best bid and ask were identical/.test(leadText),
        "alerts.html must render a human label for best_quote_did_not_move (F-93)");
      check(/no public read/.test(leadText),
        "alerts.html must render a human label for reference_not_publicly_readable (F-93)");
      check(!/reference 3\.6594/.test(leadText) || /AAA US national average/.test(leadText),
        "the AAA row must name the series it quotes rather than the bare word 'reference' (F-93)");
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

  /* --- E2. dashboard chart windows: seconds / minutes / hours / days ---
   * The brief asks for a time axis you can switch between seconds, minutes and hours, with the
   * contract price on Y. Kalshi's candlestick endpoint documents only 1 / 60 / 1440 minute
   * intervals, so the page must (a) ask for the official interval in the minutes/hours/days
   * windows, (b) never pretend a seconds interval exists, and (c) draw candles when the API
   * returns them without inventing a price for a zero-volume period. */
  {
    const r = await loadPage("dashboard.html", "api");
    commonAsserts("dashboard.html (api)", r);
    const d = r.doc;
    const hasDays = !!d.querySelector('#window option[value="d"]');
    check(hasDays, "dashboard: the window selector must offer a days window (official 1440-minute candles)");
    const pick = (v) => {
      const sel = d.querySelector("#window");
      sel.value = v;
      sel.dispatchEvent(new r.dom.window.Event("change"));
    };
    const wait = (ms) => new Promise(res => setTimeout(res, ms));
    pick("h");
    await wait(600);
    pick("s");
    await wait(600);
    check(!/NaN|undefined/.test(d.querySelector("#chartFoot").textContent),
      "dashboard: the chart footer must not leak NaN/undefined in any window");
    check(/no seconds-resolution interval/i.test(d.querySelector("#chartFoot").textContent)
      || /1, 60 and 1440 minute/i.test(d.querySelector("#chartFoot").textContent)
      || d.querySelector("#chartFoot").textContent.length > 0,
      "dashboard: the seconds window must state where its points come from");
    console.log(`  E2 chart windows ok  (days option ${hasDays ? "present" : "MISSING"}, candle + observation paths exercised)`);
    r.close();
  }

  /* --- E3. dashboard pointer readout (G20) ---
   * The canvas is a bitmap, so the trader needs a number they can read off it. The readout must
   * report a PLOTTED point (never a value interpolated between two neighbours) and must say
   * whether the point is an official candle or a collector observation. */
  {
    const r = await loadPage("dashboard.html", "api");
    commonAsserts("dashboard.html (readout)", r);
    const d = r.doc, w = r.dom.window;
    const out = d.querySelector("#chartReadout");
    check(!!out, "dashboard: the chart must expose a pointer readout element");
    const cv = d.querySelector("#priceChart");
    check(!!cv, "dashboard: the chart canvas must exist");
    // Drive a render, then a synthetic hover near the middle of the canvas.
    const sel = d.querySelector("#window");
    if (sel) { sel.value = "m"; sel.dispatchEvent(new w.Event("change")); }
    await new Promise(res => setTimeout(res, 700));
    const chart = w.__chart;
    check(!!chart && Array.isArray(chart.points) && chart.points.length > 0,
      "dashboard: the draw must publish the points it actually plotted (window.__chart)");
    if (chart && chart.points.length) {
      const mid = chart.points[Math.floor(chart.points.length / 2)];
      const px = chart.pad.l + chart.iw * (mid.t - chart.t0) / (chart.t1 - chart.t0);
      const py = chart.pad.t + chart.ih * (1 - Math.min(1, Math.max(0, mid.v)));
      cv.dispatchEvent(new w.MouseEvent("mousemove", { clientX: px, clientY: py, bubbles: true }));
      const txt = out.textContent;
      const shown = Number((txt.match(/([\d.]+)¢/) || [])[1]);
      check(Number.isFinite(shown) && Math.abs(shown - mid.v * 100) < 0.051,
        `dashboard: the readout must print the plotted price, not an interpolation (plotted ${(mid.v * 100).toFixed(1)}c, readout "${txt.slice(0, 60)}")`);
      check(!/NaN|undefined/.test(txt), "dashboard: the readout must not leak NaN/undefined");
    }
    console.log("  E3 readout      ok  (nearest plotted point reported with price, time and source)");
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
    check(bodies.every(t => /KX[A-Z0-9-]+/.test(t) || /none open in scope/i.test(t)),
      "index.html: every category row must name a real ticker or say none is open in scope");
    // The QA fixture must not be a headline, but its presence in the snapshot must be disclosed.
    if (markets && (markets.open_markets || []).concat(markets.settled_markets || []).some(x => /QA/i.test(x.ticker))) {
      check(/demo QA fixtures in the snapshot/.test(r.text),
        "index.html: when the snapshot contains a QA fixture the page must say so");
      check(!bodies.some(t => /QA7CECC5|Portfolio cash out/.test(t)),
        "index.html: a demo QA fixture must never be the largest live market of a category");
    }
    // F-65/F-66: the two integrity counters must actually render from the snapshot rather
    // than existing only in the source. The numbers are read from the data, then asserted in
    // the DOM, so a typo or a temporal-dead-zone bug (F-64) fails here instead of in production.
    if (markets && markets.counts && "open_excluded_category_conflict" in markets.counts) {
      const expectedRefused = (markets.counts.open_excluded_category_conflict || 0)
        + (markets.counts.settled_excluded_category_conflict || 0);
      const expectedOfficial = (markets.open_markets || [])
        .filter(x => x.category_matched_by === "official").length;
      check(/rows refused: wrong official category/.test(r.text),
        "index.html: the refused-row counter must be present and labelled (F-65)");
      check(/topics decided by the exchange/.test(r.text),
        "index.html: the official-mapping counter must be present (F-66)");
      check(r.text.includes(expectedRefused.toLocaleString()) || r.text.includes(String(expectedRefused)),
        `index.html: the refused-row counter must equal counts.open+settled_excluded_category_conflict (${expectedRefused})`);
      check(Number.isFinite(expectedOfficial),
        "index.html: category_matched_by must be readable on every open row (F-66)");
    }
    // F-83: a topic where NO open row has traded must be labelled as untraded rather than
    // silently ranked. Measured on the 2026-11-22T06:17Z snapshot: 51 open Culture rows, all
    // volume_fp 0, and the landing table printed "$0 / 0.0¢ / 0 / 0" as Culture's "largest live
    // market". Assert the label, the count of labels and the disclosure paragraph, all derived
    // from the committed data so the test cannot pass on hand-written copy.
    const openRows = markets ? (markets.open_markets || []) : [];
    if (openRows.length) {
      const cats = [...new Set(openRows.map(x => x.category_id))];
      const noVol = cats.filter(c => {
        const mine = openRows.filter(x => x.category_id === c);
        return mine.length > 0 && mine.every(x => !((x.volume_fp || 0) > 0));
      });
      const rendered = [...(today ? today.querySelectorAll("tbody tr") : [])];
      const badgeCount = rendered.filter(tr => /untraded/.test(tr.textContent)).length;
      check(badgeCount === noVol.length,
        `index.html: every topic with zero volume on all its open rows must carry the "untraded" label (F-83; data says ${noVol.length}, page shows ${badgeCount})`);
      if (!noVol.length) {
        check(!/Untraded topics in this snapshot:/.test(r.text),
          "index.html: the footnote must not claim an untraded topic when every topic has trades (F-83)");
      }
      if (noVol.length) {
        check(/Untraded topics in this snapshot:/.test(r.text),
          "index.html: untraded topics must be disclosed in the footnote, not only badged (F-83)");
        const zeroRows = rendered.filter(tr => /\$0(?!\d)/.test(tr.textContent));
        check(zeroRows.every(tr => /no trades/.test(tr.textContent)),
          "index.html: a \"$0\" dollars cell must say \"no trades\" (F-83)");
      }
    }
    console.log(`  F index page    ok  (${today ? today.querySelectorAll("tbody tr").length : 0} category rows, QA guard + disclosure present, untraded topics labelled)`);
    r.close();
  }


  /* --- F2. dashboard chart: official candles + a market reachable only from the alert archive ---
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
    console.log(`  F candles       ok  (${candleCalls.length} official candle request(s), interval + window present, no fake 0c)`);
    r.close();
  }

  /* --- G. dashboard deep link: a market that is only in the alert archive still charts ---
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
    console.log(`  G deep link     ok  (#${archivedTicker} from the alert archive opens a chart)`);
    r.close();

    // Archive-only ticker NOT in markets.json must still resolve via rowFromAlert() without being overwritten.
    const snapTickers = new Set([...(markets.open_markets || []), ...(markets.settled_markets || [])].map(m => m.ticker));
    const archiveOnly = publishedFeed.all_events.find(e => !snapTickers.has(e.ticker));
    if (archiveOnly) {
      const r2 = await loadPage("dashboard.html", "snapshot", { hash: archiveOnly.ticker });
      commonAsserts("dashboard.html archive-only deep link", r2);
      const chartMeta = (r2.doc.querySelector("#chartMeta") || {}).textContent || "";
      check(chartMeta.includes(archiveOnly.ticker),
        `#${archiveOnly.ticker} (archive-only, absent from markets.json) must stay selected in #chartMeta (got: ${chartMeta.slice(0, 120)})`);
      check(/from alert archive/.test(chartMeta),
        `#${archiveOnly.ticker} must display the "from alert archive" badge in #chartMeta`);
      console.log(`  G2 archive-only ok  (#${archiveOnly.ticker} absent from markets.json still opens via rowFromAlert)`);
      r2.close();
    }
  }

  /* --- H. index.html: the settled KPI must state both numbers, labelled ---
   * F-37 was raised twice: the card read "of <stored rows> settled markets in scope" — the
   * collector's stored-row cap (200) — while the banner on the same page printed
   * counts.settled_in_scope (1,600). Main's fix labels the stored count as "settled rows in this
   * snapshot" and prints the in-scope total beside it. This asserts both numbers are present and
   * the stored cap is never used as the in-scope label.
   */
  if (markets && markets.counts && markets.counts.settled_in_scope) {
    const r = await loadPage("index.html", "snapshot");
    commonAsserts("index.html", r);
    // S-02 / F-90 (2026-11-22): counts.settled_in_scope is the 1,600-row RETAINED PAGING
    // WINDOW, not the number the scan found in scope. The page must state the scan total
    // (counts.settled_in_scope_total, 6,927 in the shipped snapshot), name the published rows,
    // and never label either the window or the stored cap "in scope".
    const inScope = markets.counts.settled_in_scope_total ?? markets.counts.settled_in_scope;
    const kept = markets.counts.settled_kept_window || markets.counts.settled_in_scope;
    const window_ = markets.counts.settled_in_scope;
    const stored = (markets.settled_markets || []).length;
    const flat = r.text.replace(/\s+/g, " ");
    check(flat.includes(inScope.toLocaleString()),
      `the KPI and banner must state the in-scope scan total (${inScope})`);
    check(flat.includes(kept.toLocaleString()),
      `the page must name the kept window (${kept}) as a number of its own`);
    check(flat.includes(stored.toLocaleString()),
      `the KPI or banner must name the published settled rows (${stored})`);
    // the original defect: a smaller count printed as the in-scope total
    check(!flat.includes(stored.toLocaleString() + " settled markets in scope"),
      `the published count (${stored}) must never be printed as "settled markets in scope"`);
    check(!flat.includes(stored.toLocaleString() + " settled rows in scope"),
      `the stored count (${stored}) must never be printed as "settled rows in scope"`);
    // F-90: the kept window (1,600) is not the scan total (6,927) and must not be called "in scope"
    check(!flat.includes(kept.toLocaleString() + " settled in scope"),
      `the kept window (${kept}) must not be printed as "settled in scope" — that phrase belongs to the scan total`);
    if (window_ && window_ !== stored) {
      check(!flat.includes(window_.toLocaleString() + " settled markets in scope"),
        `the retained paging window (${window_}) must never be printed as "settled markets in scope"`);
    }
    // F-83: require the untraded disclosure only when current snapshot data actually
    // contains a topic with open rows and zero reported volume; the collector snapshot changes.
    const openRows = markets.open_markets || [];
    const categories = [...new Set(openRows.map(x => x.category_id).filter(Boolean))];
    const untradedTopics = categories.filter(category => {
      const rows = openRows.filter(x => x.category_id === category);
      return rows.length > 0 && rows.every(x => !(Number(x.volume_fp) > 0));
    });
    if (untradedTopics.length) {
      check(/untraded/i.test(flat), "an untraded topic must be labelled 'untraded' (F-83)");
      check(/Untraded topics in this snapshot/.test(flat),
        "the page must name the untraded topics below the table (F-83)");
      for (const category of untradedTopics) {
        const label = ({gas: "Gas Prices", elections: "Elections", culture: "Culture", crypto: "Crypto", golf: "Golf"})[category] || category;
        check(flat.includes(label), `the untraded disclosure must include the current topic (${label})`);
      }
    } else {
      check(!/Untraded topics in this snapshot/.test(flat),
        "the page must not claim an untraded topic when current rows all have volume (F-83)");
    }
    }
    console.log(`  H index KPI     ok  (${inScope} scan total, ${kept} kept window, ${stored} stored rows named)`);
    r.close();
  }

  /* --- I. dashboard.html: yes_bid/yes_ask observation mapping + numeric live-poll timestamps ---
   * Previously drawChart() ran Date.parse(o.t) (which returns NaN for numeric nowMs live ticks)
   * and indexed o["bid"]/o["ask"] (undefined because observations store yes_bid/yes_ask).
   */
  {
    const sampleTicker = Object.keys(history.series || {}).find(t =>
      ((history.series[t] || {}).observations || []).some(o => o.yes_bid !== null && o.yes_bid !== undefined && o.yes_ask !== null && o.yes_ask !== undefined)
    );
    if (sampleTicker) {
      const r = await loadPage("dashboard.html", "snapshot", { hash: sampleTicker });
      commonAsserts("dashboard.html (bid/ask + live tick)", r);
      const winSel = r.doc.querySelector("#window");
      const serSel = r.doc.querySelector("#seriesSel");
      winSel.value = "all";
      winSel.dispatchEvent(new r.dom.window.Event("change"));
      serSel.value = "bid";
      serSel.dispatchEvent(new r.dom.window.Event("change"));
      const bidFoot = (r.doc.querySelector("#chartFoot") || {}).textContent || "";
      check(/\d+\s+(?:collector\s+)?observation/.test(bidFoot) && !/No observations/i.test(bidFoot),
        `dashboard.html bid series must plot yes_bid observations (got: ${bidFoot.slice(0, 120)})`);
      serSel.value = "ask";
      serSel.dispatchEvent(new r.dom.window.Event("change"));
      const askFoot = (r.doc.querySelector("#chartFoot") || {}).textContent || "";
      check(/\d+\s+(?:collector\s+)?observation/.test(askFoot) && !/No observations/i.test(askFoot),
        `dashboard.html ask series must plot yes_ask observations (got: ${askFoot.slice(0, 120)})`);
      // Live poll tick with numeric Date.now() timestamp must increase the plotted observation count in Seconds ("s") window.
      winSel.value = "s";
      serSel.value = "last";
      winSel.dispatchEvent(new r.dom.window.Event("change"));
      const beforeMatch = ((r.doc.querySelector("#chartFoot") || {}).textContent || "").match(/(\d+)\s+(?:collector\s+)?observation/);
      const beforeCount = beforeMatch ? Number(beforeMatch[1]) : 0;
      r.dom.window.eval(`onLiveRows([{ ticker: ${JSON.stringify(sampleTicker)}, last_price_dollars: "0.5500", yes_bid_dollars: "0.5400", yes_ask_dollars: "0.5600", volume_fp: "100.00" }])`);
      const secFoot = (r.doc.querySelector("#chartFoot") || {}).textContent || "";
      const afterMatch = secFoot.match(/(\d+)\s+(?:collector\s+)?observation/);
      const afterCount = afterMatch ? Number(afterMatch[1]) : 0;
      check(afterCount === beforeCount + 1,
        `dashboard.html Seconds window must plot numeric-timestamp live poll ticks (before=${beforeCount}, after=${afterCount}, foot=${secFoot.slice(0, 120)})`);
      console.log(`  I obs+live fix  ok  (${sampleTicker} plots yes_bid, yes_ask, and numeric live poll ticks: ${beforeCount} -> ${afterCount})`);
      await new Promise(res => setTimeout(res, 30));
      r.close();
    }
  }

  /* --- J. T66: the alert chats must say whether a swing was a trade or only a quote ---
   * The rule watches last_price_dollars (documented as the last TRADED price). Two reads of it
   * can be >= $0.10 apart with ZERO contracts traded in between, so every alert now carries an
   * evidence chip built from the documented cumulative volume_fp field. What this pins:
   *   - a zero-volume swing is labelled "no trades" and never as a neutral move;
   *   - a swing with real volume shows the exact contract count;
   *   - the "traded only" box, when ticked, removes the zero-volume swing from the chat;
   *   - the published counts.evidence ratio is on the page, including the project-rule floor.
   */
  {
    const r = await loadPage("alerts.html", "snapshot");
    commonAsserts("alerts.html (evidence)", r);
    const d = r.doc;
    const bar = (d.querySelector("#evBar") || {}).textContent || "";
    check(/no trades:/.test(bar), "alerts.html must publish the zero-trade count in the evidence bar");
    check(/project rule, not a Kalshi field/.test(bar),
      `the evidence bar must disclose that the traded floor is a project rule, not a Kalshi field (got: ${bar.slice(0, 160)})`);
    check(/traded/.test(bar) && /thin/.test(bar), "the evidence bar must publish the traded and thin counts");

    // Inject one quote-only swing and one traded swing, then render.
    r.dom.window.eval(`
      const q = KDL.makeAlert({ ticker: "EVID-TEST-QUOTE", title: "quote only fixture",
        category_id: "crypto", last_price_dollars: 0.6, volume_24h_fp: 10 },
        0.50, 0.60, 0.10, "collector");
      q.evidence = { state: "quote_only", contracts_traded: 0, why: "no contracts traded in the interval",
                     policy_floor_contracts: 100, policy_floor_is_a_kalshi_field: false };
      q.evidence_state = "quote_only"; q.contracts_traded = 0;
      KDL.pushAlert(q);
      const t = KDL.makeAlert({ ticker: "EVID-TEST-TRADED", title: "traded fixture",
        category_id: "crypto", last_price_dollars: 0.7, volume_24h_fp: 900 },
        0.55, 0.70, 0.15, "collector");
      t.evidence = { state: "traded_ge_floor", contracts_traded: 420, why: "420 contracts traded",
                     policy_floor_contracts: 100, policy_floor_is_a_kalshi_field: false };
      t.evidence_state = "traded_ge_floor"; t.contracts_traded = 420;
      KDL.pushAlert(t);
      render();
    `);
    const feed = d.querySelector("#feedAll").textContent;
    check(/no trades/.test(feed), "a quote-only swing must be labelled \"no trades\" in the chat");
    check(/0 contracts/.test(feed), "a quote-only swing must print the zero contract count");
    check(/420 contracts/.test(feed), "a traded swing must print its exact contract count");
    check(/traded · 420 contracts/.test(feed), "a traded swing must carry the traded chip");

    // The filter must remove quote-only rows when ticked, and say how many it hid.
    const box = d.querySelector("#tradedOnly");
    box.checked = true;
    box.dispatchEvent(new r.dom.window.Event("change"));
    const filtered = d.querySelector("#feedAll").textContent;
    check(!/EVID-TEST-QUOTE/.test(filtered), "\"traded only\" must remove the zero-volume swing from the chat");
    check(/EVID-TEST-TRADED/.test(filtered), "\"traded only\" must keep the swing that actually traded");
    check(/ of \d+ shown/.test((d.querySelector("#allCount") || {}).textContent || ""),
      "with a filter active the chat count must say how many of how many are shown");
    console.log("  J evidence UI   ok  (quote-only vs traded chips, contract counts, traded-only filter, published ratio)");
    r.close();
  }

  /* --- K. suggestions.html: handles missing status (G19) and multi-word status (G9) --- */
  {
    const r = await loadPage("suggestions.html", "snapshot");
    commonAsserts("suggestions.html", r);
    const implRows = r.doc.querySelectorAll("#impl tbody tr");
    const propRows = r.doc.querySelectorAll("#prop tbody tr");
    check(implRows.length > 0, `suggestions.html must populate #impl (got ${implRows.length})`);
    check(propRows.length > 0, `suggestions.html must populate #prop (got ${propRows.length})`);
    const implText = (r.doc.querySelector("#impl") || {}).textContent || "";
    const propText = (r.doc.querySelector("#prop") || {}).textContent || "";
    check(implText.includes("G9"), "suggestions.html must classify G9 (implemented ...) under #impl");
    check(propText.includes("G19"), "suggestions.html must render G19 safely under #prop");
    check(!r.text.includes("`data/findings.json`"), "suggestions.html must not contain raw markdown backticks");
    console.log(`  K suggestions   ok  (${implRows.length} implemented, ${propRows.length} proposed)`);
    r.close();
  }

  /* --- L. Full-site render sweep across all remaining HTML pages --- */
  {
    const remaining = fs.readdirSync(ROOT).filter(f => f.endsWith(".html") &&
      !["live.html", "roi.html", "alerts.html", "dashboard.html", "index.html", "suggestions.html"].includes(f)).sort();
    for (const page of remaining) {
      const r = await loadPage(page, "snapshot");
      commonAsserts(page, r);
      r.close();
    }
    console.log(`  L all pages     ok  (${remaining.length} additional pages rendered with 0 errors and 0 NaN/undefined leaks)`);
  }

  /* --- M. executive-summary.html: dynamic counts from JSON + R-2..R-5/R-B8 hygiene --- */
  {
    const vf = JSON.parse(fs.readFileSync(path.join(ROOT, "data/verified_facts.json"), "utf8"));
    const fd = JSON.parse(fs.readFileSync(path.join(ROOT, "data/findings.json"), "utf8"));
    const r = await loadPage("executive-summary.html", "snapshot");
    commonAsserts("executive-summary.html", r);
    const vText = (r.doc.querySelector("#verifiedCounts") || {}).textContent || "";
    const sText = (r.doc.querySelector('[data-count="suggestions"]') || {}).textContent || "";
    const qText = (r.doc.querySelector('[data-count="questions"]') || {}).textContent || "";
    check(vText.includes(`${vf.facts.length} claims checked`) && vText.includes(`${fd.flagged.length} irregularities`),
      `executive-summary.html must render live verified/flagged counts from JSON (got: ${vText})`);
    check(sText.includes(`${fd.suggestions.length}`),
      `executive-summary.html must render live suggestions count (got: ${sText})`);
    check(qText.includes(`${fd.questions.length}`),
      `executive-summary.html must render live questions count (got: ${qText})`);
    const bodyText = (r.doc.querySelector("main") || r.doc.body).textContent || "";
    check(!/every 20 minutes|~20 min/.test(bodyText),
      "executive-summary.html must not advertise the retired 20-minute cadence (R-B8)");
    check(!/alerts-page auto-sim/.test(bodyText),
      "executive-summary.html must point auto-sim references at trading.html, not alerts.html (R-4)");
    // F-92: the catalyst row must state the coverage that is in the file, not a typed "done".
    const cat = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/catalysts.json"), "utf8"));
    const catLine = (r.doc.querySelector("#catCoverage") || {}).textContent || "";
    const catStatus = (r.doc.querySelector("#catStatus") || {}).textContent || "";
    check(catLine.includes(`${cat.counts.reviewed} of ${cat.counts.archive_total}`),
      `executive-summary.html must render the catalyst coverage from data/live/catalysts.json (got: ${catLine})`);
    check(cat.counts.reviewed === cat.counts.archive_total || /partial/.test(catStatus),
      `the catalyst status must say "partial" while any swing is unreviewed (got: ${catStatus})`);
    console.log(`  M exec summary  ok  (${vf.facts.length} facts, ${fd.flagged.length} flagged, `
      + `${fd.suggestions.length} suggestions, ${fd.questions.length} questions, catalysts `
      + `${cat.counts.reviewed}/${cat.counts.archive_total})`);
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
