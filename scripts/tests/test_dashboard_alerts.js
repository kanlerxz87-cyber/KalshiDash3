#!/usr/bin/env node
/* Fixture smoke test for dashboard.html.
 *
 * No dependencies: the page script runs in a vm context with a small DOM stub,
 * so the three behaviours this session added are checked against real markup:
 *
 *   R-1  the alert panels read the canonical archive (data/live/alerts_archive.json),
 *        so an alert whose market has left the open scan is still listed, and the
 *        rendered feed is used only when the archive is absent;
 *   the official settlement sources attached to an alert are shown as candidates
 *        with an explicit "unverified cause" label and never as a proven cause;
 *   the price chart marks every recorded jump of at least $0.10 for the selected
 *        market (amber line + diamond, labelled with the size of the jump).
 *
 * Run: node scripts/tests/test_dashboard_alerts.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const ROOT = path.resolve(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "dashboard.html"), "utf8");
const siteJs = fs.readFileSync(path.join(ROOT, "assets", "site.js"), "utf8");
const inline = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const CRYPTO = "KXDEMOFUTHOURLY-26NOV20H14-UP";
const GOLF = "KXPGATOUR-THRC26-X";
const CLOSED = "KXDEMOFUTHOURLY-26NOV20H12-UP";   // settled, no longer in the open scan
const FEED_ONLY = "FEED-ONLY-1";
const EVENT_URL = "https://external-api.demo.kalshi.co/trade-api/v2/events/KXDEMOFUTHOURLY-26NOV20H14";
const COINBASE = { name: "Coinbase", url: "https://www.coinbase.com/price" };

const minutesAgo = (m) => new Date(Date.now() - m * 60000).toISOString().replace(/\.\d+Z$/, "Z");
const T0 = minutesAgo(40);
const T1 = minutesAgo(30);
const T2 = minutesAgo(20);

function marketRow(ticker, title, categoryId, basis, volume24h, dollars) {
  return {
    ticker, title, category_id: categoryId, category_basis: basis, status: "active", result: "",
    last_price_dollars: 0.5, volume_fp: 100, volume_24h_fp: volume24h, open_interest_fp: 10,
    dollars_traded_estimate: dollars,
    source: `https://external-api.demo.kalshi.co/trade-api/v2/markets/${ticker}`,
    event_ticker: ticker.split("-").slice(0, 2).join("-"),
  };
}

const MARKETS = {
  schema: 1, environment: "demo", base_url: "https://external-api.demo.kalshi.co/trade-api/v2",
  collected_at: minutesAgo(5),
  counts: { open_total_scanned: 2, settled_total_scanned: 0, open_in_scope: 2, settled_in_scope: 0 },
  sources: {}, disclaimers: [],
  open_markets: [
    marketRow(CRYPTO, "Demo BTC at or above 61498.92 USD", "crypto", "keyword", 4485, 500),
    marketRow(GOLF, "The RSM Classic winner", "golf", "seed", 1200, 400),
  ],
  settled_markets: [], liquidity: [],
};

const HISTORY = {
  schema: 1,
  series: {
    [CRYPTO]: { observations: [
      { t: T0, last: 0.35, bid: 0.34, ask: 0.36 },
      { t: T1, last: 0.55, bid: 0.54, ask: 0.56 },
      { t: T2, last: 0.50, bid: 0.49, ask: 0.51 },
    ] },
  },
};

const ARCHIVE = {
  schema: 1,
  alerts: [
    {
      ticker: CRYPTO, event_ticker: "KXDEMOFUTHOURLY-26NOV20H14", title: "Demo BTC at or above 61498.92 USD",
      category_id: "crypto", category_basis: "keyword", status: "active",
      from_time: T0, to_time: T1, from_price: 0.35, to_price: 0.55, delta: 0.2, direction: "up",
      volume_24h_fp: 4485, market_source: `https://external-api.demo.kalshi.co/trade-api/v2/markets/${CRYPTO}`,
      cause_link: EVENT_URL,
      cause_status: "unverified: the official settlement source(s) listed for this event are candidates to check, not a confirmed cause",
      cause_candidates: [COINBASE], cause_kind: "official_settlement_source",
      first_seen_at: T1, high_roi: false,
    },
    {
      ticker: CLOSED, event_ticker: "KXDEMOFUTHOURLY-26NOV20H12", title: "Demo BTC at or above 61985.83 USD",
      category_id: "crypto", category_basis: "keyword", status: "finalized",
      from_time: T0, to_time: T1, from_price: 0.55, to_price: 0.45, delta: -0.1, direction: "down",
      volume_24h_fp: 4485, market_source: `https://external-api.demo.kalshi.co/trade-api/v2/markets/${CLOSED}`,
      cause_link: null, cause_status: "unverified: no official event reference was collected for this market",
      cause_candidates: [], cause_kind: "none",
      first_seen_at: T1, high_roi: false,
    },
    {
      ticker: GOLF, event_ticker: "KXPGATOUR-THRC26", title: "The RSM Classic winner",
      category_id: "golf", category_basis: "seed", status: "active",
      from_time: T0, to_time: T1, from_price: 0.5, to_price: 0.4, delta: -0.1, direction: "down",
      volume_24h_fp: 1200, market_source: `https://external-api.demo.kalshi.co/trade-api/v2/markets/${GOLF}`,
      cause_link: null, cause_status: "unverified: no official event reference was collected for this market",
      cause_candidates: [], cause_kind: "none",
      first_seen_at: T1, high_roi: true,
    },
  ],
};

const FEED = {
  schema: 1, generated_at: minutesAgo(5), counts: {}, disclaimers: [],
  all_events: [{
    ticker: FEED_ONLY, event_ticker: "FEED", title: "Feed only alert", category_id: "crypto",
    category_basis: "keyword", status: "active", from_time: T0, to_time: T1, from_price: 0.3, to_price: 0.4,
    delta: 0.1, direction: "up", volume_24h_fp: 10, market_source: "https://example.invalid/markets/x",
    cause_link: null, cause_status: "unverified: none", cause_candidates: [], high_roi: false,
  }],
  high_roi: [],
};

function makeCtx() {
  const ops = [];
  const ctx = new Proxy({}, {
    get(target, prop) {
      if (prop in target) return target[prop];
      const fn = (...args) => { ops.push({ op: String(prop), args }); };
      target[prop] = fn;
      return fn;
    },
    set(target, prop, value) { target[prop] = value; return true; },
  });
  return { ctx, ops };
}

async function runDashboard(files) {
  const { ctx, ops } = makeCtx();
  const els = {};
  const el = (sel) => {
    if (typeof sel !== "string" || !sel.startsWith("#")) return null;
    const id = sel.slice(1);
    if (!els[id]) {
      els[id] = {
        id, innerHTML: "", textContent: "", value: "", clientWidth: 900, width: 900, height: 340,
        dataset: {}, style: {}, handlers: {},
        addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); },
        getContext() { return ctx; },
        querySelectorAll() { return []; },
      };
    }
    return els[id];
  };
  el("#seriesSel").value = "last";
  el("#window").value = "m";

  const document = {
    body: {},
    hidden: false,
    querySelector: (sel) => el(sel),
    querySelectorAll: () => [],
    getElementById: (id) => el("#" + id),
    addEventListener() {},
  };
  const window = {
    devicePixelRatio: 1,
    location: { hash: "" },
    addEventListener() {},
    setInterval() { return 0; },
  };
  const sandbox = {
    document, window, console,
    history: { replaceState() {} },
    location: window.location,
    getComputedStyle: () => ({ getPropertyValue: () => "#334455" }),
    setTimeout, clearTimeout, Date, Math, JSON, Number, String, Array, Object, Boolean, Promise, Error,
    encodeURIComponent, decodeURIComponent, isFinite, parseInt, parseFloat,
  };
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);

  // Serve the fixtures instead of the network. `KD` is a const binding inside
  // the context, so the override has to happen inside the context too.
  sandbox.__fixtureJson = async (p) => {
    const clean = String(p).split("?")[0];
    if (!(clean in files)) throw new Error("no fixture for " + clean);
    return files[clean];
  };
  vm.runInContext(siteJs, context, { filename: "site.js" });
  vm.runInContext("KD.json = __fixtureJson;", context);
  vm.runInContext(inline, context, { filename: "dashboard.html" });
  // Let the async load() settle.
  for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 1));
  return { els, ops, sandbox };
}

function fire(els, id, type, event) {
  const el = els[id];
  assert.ok(el, "missing element " + id);
  for (const fn of el.handlers[type] || []) fn(event);
}

async function test_archive_drives_the_feeds() {
  const { els } = await runDashboard({
    "data/live/markets.json": MARKETS,
    "data/live/price_history.json": HISTORY,
    "data/live/alerts_archive.json": ARCHIVE,
    "data/live/alerts.json": FEED,
  });
  const html = els.allAlerts.innerHTML;
  assert.ok(html.includes(CRYPTO), "the archive alert must be listed");
  assert.ok(html.includes(CLOSED), "an alert whose market left the open scan must still be listed (R-1)");
  assert.ok(!html.includes(FEED_ONLY), "the archive wins over the rendered feed");
  assert.strictEqual(els.allAlertCount.textContent, "3 shown");
  assert.ok(els.alertFreshness.textContent.includes("alerts_archive.json"), "the freshness line names the archive");
}

async function test_cause_candidates_are_labelled_unverified() {
  const { els } = await runDashboard({
    "data/live/markets.json": MARKETS,
    "data/live/price_history.json": HISTORY,
    "data/live/alerts_archive.json": ARCHIVE,
  });
  const html = els.allAlerts.innerHTML;
  assert.ok(html.includes("unverified cause"), "the candidate must be labelled unverified");
  assert.ok(html.includes(COINBASE.url), "the official settlement source must be linked");
  assert.ok(html.includes("Coinbase"), "the settlement source name must be shown");
  assert.ok(html.includes(EVENT_URL), "the official event record must be linked");
  assert.ok(html.includes("Not a confirmed cause"), "the disclaimer must say it is not a confirmed cause");
  assert.ok(html.includes("No official event reference was collected"), "alerts without a reference say so");
}

async function test_category_filter_still_applies() {
  const { els } = await runDashboard({
    "data/live/markets.json": MARKETS,
    "data/live/price_history.json": HISTORY,
    "data/live/alerts_archive.json": ARCHIVE,
  });
  fire(els, "catFilter", "change", { target: { value: "golf" } });
  assert.strictEqual(els.allAlertCount.textContent, "1 shown");
  assert.ok(els.allAlerts.innerHTML.includes(GOLF));
  assert.ok(!els.allAlerts.innerHTML.includes(CRYPTO));
  fire(els, "catFilter", "change", { target: { value: "" } });
  assert.strictEqual(els.allAlertCount.textContent, "3 shown");
}

async function test_model_watch_uses_the_archived_screen_flag() {
  const { els } = await runDashboard({
    "data/live/markets.json": MARKETS,
    "data/live/price_history.json": HISTORY,
    "data/live/alerts_archive.json": ARCHIVE,
  });
  assert.strictEqual(els.modelAlertCount.textContent, "1 shown");
  assert.ok(els.modelAlerts.innerHTML.includes(GOLF));
}

async function test_chart_marks_jumps_of_at_least_ten_cents() {
  const { ops } = await runDashboard({
    "data/live/markets.json": MARKETS,
    "data/live/price_history.json": HISTORY,
    "data/live/alerts_archive.json": ARCHIVE,
  });
  const labels = ops.filter((o) => o.op === "fillText").map((o) => String(o.args[0]));
  assert.ok(labels.some((l) => l.includes("+20¢")), "the +20¢ jump must be marked on the chart: " + JSON.stringify(labels));
  assert.ok(!labels.some((l) => l.includes("5¢")), "a 5¢ move must not be marked");
  assert.ok(ops.some((o) => o.op === "setLineDash"), "the jump marker draws a dashed line");
}

async function test_feed_is_used_when_the_archive_is_missing() {
  const { els } = await runDashboard({
    "data/live/markets.json": MARKETS,
    "data/live/price_history.json": HISTORY,
    "data/live/alerts.json": FEED,
  });
  assert.ok(els.allAlerts.innerHTML.includes(FEED_ONLY), "the rendered feed is used when there is no archive");
  assert.ok(els.alertFreshness.textContent.includes("alerts.json"));
}

async function test_history_is_only_a_last_resort() {
  const { els } = await runDashboard({
    "data/live/markets.json": MARKETS,
    "data/live/price_history.json": HISTORY,
  });
  assert.ok(els.allAlerts.innerHTML.includes(CRYPTO), "the retained history is the last resort");
  assert.ok(els.alertFreshness.textContent.includes("price history"));
}

(async () => {
  const tests = [
    ["the archive drives the alert panels (R-1)", test_archive_drives_the_feeds],
    ["cause candidates are labelled unverified", test_cause_candidates_are_labelled_unverified],
    ["the category filter still applies", test_category_filter_still_applies],
    ["Model watch uses the archived screen flag", test_model_watch_uses_the_archived_screen_flag],
    ["the chart marks jumps of at least $0.10", test_chart_marks_jumps_of_at_least_ten_cents],
    ["the rendered feed is used without an archive", test_feed_is_used_when_the_archive_is_missing],
    ["the retained history is the last resort", test_history_is_only_a_last_resort],
  ];
  let failed = 0;
  for (const [name, fn] of tests) {
    try {
      await fn();
      console.log("ok   - " + name);
    } catch (err) {
      failed++;
      console.log("FAIL - " + name);
      console.log("       " + (err && err.message));
    }
  }
  console.log(failed ? `\n${failed} of ${tests.length} dashboard tests failed` : `\nall ${tests.length} dashboard tests passed`);
  process.exit(failed ? 1 : 0);
})();
