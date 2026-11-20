/* KalshiDash3 — engine behaviour test (Node, no browser).
 *
 * The live layer's DOM rendering is checked by check_site.py + node --check; what this file
 * pins is the *behaviour* of the engine, which is where "is it really live?" is decided:
 *
 *   A  a reachable API  -> mode live-api, ticks recorded, a >=10c move raises one alert,
 *                          picks are scored with the shared model, and the 429 path backs off
 *   B  a blocked API    -> mode snapshot, the committed snapshot is used, history is merged,
 *                          swings over that history still raise alerts, and NOTHING is invented
 *   C  no snapshot      -> mode offline, no fabricated rows, feeds stay empty
 *   D  a missing model  -> the engine refuses to start rather than scoring with guessed weights
 *
 * Run: node scripts/tests/test_engine_node.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const ROOT = path.join(__dirname, "..", "..");
const model = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "roi_model.json"), "utf8"));

function market(t, bid, ask, last, over = {}) {
  return Object.assign({
    ticker: t, event_ticker: t.split("-")[0], title: "engine test " + t,
    yes_bid_dollars: bid === null ? null : bid.toFixed(4),
    yes_ask_dollars: ask === null ? null : ask.toFixed(4),
    last_price_dollars: last === null ? null : last.toFixed(4),
    volume_fp: "120000.00", volume_24h_fp: "5000.00", open_interest_fp: "9000.00",
    status: "active", result: null, close_time: "2027-01-01T05:00:00Z",
    yes_bid_size_fp: "500.00", yes_ask_size_fp: "400.00",
  }, over);
}

function withFetch(handler) {
  const calls = [];
  global.fetch = async (url, opts) => {
    calls.push(String(url));
    const r = await handler(String(url));
    if (r instanceof Error) throw r;
    return { ok: r.status === undefined ? true : r.status === 200, status: r.status || 200, json: async () => r.body };
  };
  return calls;
}

async function scenarioA() {
  let price = 0.48, blocked = 1;
  const books = { orderbooks: [{ ticker: "KXAAAGASM-27JAN01-T4.00", orderbook_fp: { yes_dollars: [["0.4800", "900.00"]], no_dollars: [["0.5100", "800.00"]] } }] };
  withFetch(async (url) => {
    if (url.includes("/exchange/status")) return { body: { trading_open: true } };
    if (url.includes("/historical/cutoff")) return { body: { market_settled_ts: "2026-10-01T00:00:00Z" } };
    if (url.includes("/markets/orderbooks")) return { body: books };
    if (url.includes("data/roi_model.json")) return { body: model };
    if (url.includes("status=open")) {                        // discovery pass: no watch list yet
      return { body: { markets: [market("KXAAAGASM-27JAN01-T4.00", 0.47, 0.49, 0.48)], cursor: "" } };
    }
    if (url.includes("/markets?tickers=")) {
      price = price === 0.48 ? 0.61 : 0.48;                   // a 13c jump, then a 13c drop
      return { body: { markets: [market("KXAAAGASM-27JAN01-T4.00", price - 0.01, price + 0.01, price)] } };
    }
    return { body: {} };
  });
  delete require.cache[require.resolve(path.join(ROOT, "assets", "live.js"))];
  const KDLIVE = require(path.join(ROOT, "assets", "live.js"));
  const eng = KDLIVE.create({ pollMs: 10, bookMs: 10, snapshotMs: 10, storage: null });
  const alerts = [];
  eng.on("alert", (a) => alerts.push(a));
  await eng.start({ modelUrl: "data/roi_model.json", seedMarkets: false });
  eng.stop();
  eng.S.lastSnapshotAt = Infinity;                            // do not fall back in this scenario
  assert.strictEqual(eng.S.mode, "live-api", "reachable API must report live-api");
  assert.deepStrictEqual(eng.S.watch, ["KXAAAGASM-27JAN01-T4.00"], "discovery must build the watch list by itself");
  await eng.tick(); await eng.tick();
  const ticks = eng.seriesFor("KXAAAGASM-27JAN01-T4.00");
  assert.ok(ticks.length >= 2, `ticks recorded (${ticks.length})`);
  assert.ok(alerts.length >= 1, "a 13c jump must raise an alert");
  assert.ok(alerts.every(a => Math.abs(a.cents) >= 10), "every alert >= 10c");
  const roi = eng.S.markets.get("KXAAAGASM-27JAN01-T4.00").__roi;
  assert.ok(roi && typeof roi.score === "number", "the selected market is scored");
  assert.ok(eng.S.books.has("KXAAAGASM-27JAN01-T4.00"), "order book depth was fetched in the same pass");
  // 429 handling: the engine must back off, not hammer
  let hit = 0;
  withFetch(async () => { hit++; const e = new Error("HTTP 429"); e.status = 429; throw e; });
  await eng.tick();
  assert.ok(eng.S.backoffMs >= 2000 || eng.S.failures > 0, "429 raises the backoff or is counted");
  console.log("  A live-api mode, tick log, >=10c alerting, scoring and 429 handling  ok");
}

async function scenarioB() {
  const snap = {
    schema: 1, environment: "demo", collected_at: new Date().toISOString(), base_url: "https://example.invalid/v2",
    open_markets: [market("KXPGATOUR-26NOV22-T1", 0.3, 0.32, 0.31, { category_id: "golf", category_basis: "seed", source: "https://example.invalid/markets/1" })],
    settled_markets: [], liquidity: [],
  };
  const hist = { series: { "KXPGATOUR-26NOV22-T1": { observations: [
    { t: "2026-11-20T10:00:00Z", last: 0.30, yes_bid: 0.29, yes_ask: 0.31, volume_fp: "10.00" },
    { t: "2026-11-20T10:20:00Z", last: 0.44, yes_bid: 0.43, yes_ask: 0.45, volume_fp: "12.00" },
    { t: "2026-11-20T10:40:00Z", last: 0.45, yes_bid: 0.44, yes_ask: 0.46, volume_fp: "12.00" },
  ] } } };
  withFetch(async (url) => {
    if (url.includes("example.invalid") || url.includes("external-api")) { const e = new TypeError("Failed to fetch"); throw e; }
    if (url.includes("data/roi_model.json")) return { body: model };
    if (url.includes("data/live/markets.json")) return { body: snap };
    if (url.includes("data/live/price_history.json")) return { body: hist };
    return { body: {} };
  });
  delete require.cache[require.resolve(path.join(ROOT, "assets", "live.js"))];
  const KDLIVE = require(path.join(ROOT, "assets", "live.js"));
  const eng = KDLIVE.create({ storage: null, snapshotMs: 0 });
  await eng.start({ modelUrl: "data/roi_model.json", seedMarkets: true });
  eng.stop();
  assert.strictEqual(eng.S.mode, "snapshot", `blocked API must fall back to snapshot (got ${eng.S.mode})`);
  assert.ok(eng.S.markets.has("KXPGATOUR-26NOV22-T1"), "snapshot markets are loaded");
  assert.ok(eng.S.alerts.length >= 1, "swings inside the committed history still raise alerts");
  const a = eng.S.alerts.find(x => Math.abs(x.cents) >= 10);
  assert.ok(a, "the 14c move in history is the alert");
  assert.strictEqual(a.origin, "committed snapshot", "the alert says where it came from");
  assert.ok(eng.S.modeReason.includes("direct call from this browser failed"), "the reason is shown, not hidden");
  console.log(`  B snapshot fallback, history merge, alert origin labelling  ok (${eng.S.alerts.length} alerts from history)`);
}

async function scenarioC() {
  // model file present (it ships with the site), both the API and the snapshot unreachable
  withFetch(async (url) => { if (url.includes("data/roi_model.json")) return { body: model }; throw new TypeError("Failed to fetch"); });
  delete require.cache[require.resolve(path.join(ROOT, "assets", "live.js"))];
  const KDLIVE = require(path.join(ROOT, "assets", "live.js"));
  const eng = KDLIVE.create({ storage: null });
  await eng.start({ modelUrl: "data/roi_model.json", seedMarkets: true });
  eng.stop();
  assert.strictEqual(eng.S.mode, "offline", `nothing reachable must report offline (got ${eng.S.mode})`);
  assert.strictEqual(eng.S.markets.size, 0, "no invented markets");
  assert.strictEqual(eng.S.alerts.length, 0, "no invented alerts");
  assert.strictEqual(eng.S.picks.length, 0, "no invented picks");
  console.log("  C offline mode invents nothing  ok");
}

async function scenarioD() {
  withFetch(async () => { throw new TypeError("Failed to fetch"); });
  delete require.cache[require.resolve(path.join(ROOT, "assets", "live.js"))];
  const KDLIVE = require(path.join(ROOT, "assets", "live.js"));
  const eng = KDLIVE.create({ storage: null });
  let threw = null;
  try { await eng.start({ modelUrl: "data/does-not-exist.json" }); } catch (e) { threw = e; }
  eng.stop();
  assert.ok(threw && /refusing to score with guessed parameters/.test(threw.message),
    "a missing model file must stop the engine, not let it guess");
  console.log("  D missing model file refuses to guess  ok");
}

async function scenarioE() {
  // The multi-orderbook endpoint takes `tickers` as an ARRAY. It does NOT split a
  // comma-joined value: "?tickers=A,B" is parsed as ONE ticker named "A,B" and comes
  // back as a single EMPTY book (measured against the live demo API; the order-book
  // guide documents that an unknown ticker yields an empty entry, not an error —
  // https://docs.kalshi.com/getting_started/orderbook_responses).
  // The request must therefore use REPEATED parameters: "?tickers=A&tickers=B".
  const calls = withFetch(async (url) => {
    if (url.includes("/exchange/status")) return { body: { trading_open: true } };
    if (url.includes("/historical/cutoff")) return { body: { market_settled_ts: "2026-10-01T00:00:00Z" } };
    if (url.includes("/markets/orderbooks")) return { body: { orderbooks: [] } };
    if (url.includes("data/roi_model.json")) return { body: model };
    if (url.includes("/markets?tickers=")) return { body: { markets: [] } };
    return { body: {} };
  });
  delete require.cache[require.resolve(path.join(ROOT, "assets", "live.js"))];
  const KDLIVE = require(path.join(ROOT, "assets", "live.js"));
  const eng = KDLIVE.create({ pollMs: 10, bookMs: 0, snapshotMs: 10, storage: null });
  await eng.start({ modelUrl: "data/roi_model.json", seedMarkets: false });
  eng.stop();
  eng.setWatch(["KXAAAGASM-27JAN01-T4.00", "KXPGATOUR-26NOV22-T1"]);
  eng.S.lastSnapshotAt = Infinity;
  await eng.tick();
  const ob = calls.filter((u) => u.includes("/markets/orderbooks"));
  assert.ok(ob.length >= 1, "an order-book request was made");
  assert.ok(!ob.some((u) => u.includes("%2C")), "order-book tickers must not be comma-joined");
  assert.ok(ob.some((u) => (u.match(/tickers=/g) || []).length === 2),
    "both tickers must be sent as repeated parameters");
  console.log("  E order-book tickers are sent as repeated parameters  ok");
}

(async () => {
  await scenarioA(); await scenarioB(); await scenarioC(); await scenarioD(); await scenarioE();
  console.log("OK: live engine behaviour verified in five modes.");
})().catch((e) => { console.error("FAILED:", e.message); process.exit(1); });
