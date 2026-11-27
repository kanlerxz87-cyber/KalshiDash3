/* Regression test (defect F-102): live discovery must not lose a market's topic when the API
 * omits series_ticker.
 *
 * data/verified_facts.json C-45 records the measured behaviour: the market object returned by
 * GET /markets on the demo environment contains event_ticker but no series_ticker key at all,
 * so the collector derives the series from the ticker prefix
 * (KXAAAGASM-26MAR31-4.00 -> KXAAAGASM) and keeps the raw value as series_ticker_from_api.
 * The browser's live path (assets/engine.js) created its market rows straight from the API
 * object, so series_ticker was absent/undefined there. Two documented behaviours quietly
 * disappeared in live mode:
 *   - the per-series fee multiplier (fee schedule, https://kalshi.com/docs/kalshi-fee-schedule.pdf)
 *     fell back to the "unlisted" default of 1, so a KXBTCY/KXETHY fill (maker 0 / taker 0 in the
 *     schedule) was charged a taker fee that Kalshi does not charge, and
 *   - the live classification had no series to fall back on.
 * The snapshot path was correct, which is why the committed pages were unaffected.
 *
 * This test drives assets/engine.js directly with an API-shaped row that has NO series_ticker,
 * exactly as GET /markets returns it, and asserts the engine recovers the series.
 *
 * Run: node scripts/tests/test_series_fallback.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

const problems = [];
const check = (cond, msg) => { if (!cond) problems.push(msg); };

/* Load assets/engine.js the way a browser would: as a script, evaluated in a bare context. */
const vm = require("vm");
const src = fs.readFileSync(path.join(ROOT, "assets/engine.js"), "utf8");
const store = {};
const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  Date,
  Math,
  JSON,
  fetch: async () => { throw new TypeError("Failed to fetch"); },
  localStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  },
  window: null,
  document: { createElement: () => ({ style: {} }), addEventListener() {} },
  location: { protocol: "https:", host: "x.invalid" },
};
sandbox.window = sandbox;
sandbox.window.localStorage = sandbox.localStorage;
sandbox.globalThis = sandbox;
sandbox.window = sandbox;       // the script assigns window.KDL; in a browser window === globalThis
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: "assets/engine.js" });

const KDL = sandbox.KDL;
check(!!KDL, "assets/engine.js must expose KDL");
if (KDL) {
  // The engine's own series derivation must be reachable and must work off the ticker.
  check(typeof KDL.seriesOf === "function",
    "the engine must expose a single series derivation (KDL.seriesOf) so live rows and snapshots agree");
  if (typeof KDL.seriesOf === "function") {
    check(KDL.seriesOf("KXETHY-27JAN0100-T4999.99") === "KXETHY",
      `KDL.seriesOf must derive KXETHY from a market ticker, got ${KDL.seriesOf("KXETHY-27JAN0100-T4999.99")}`);
    check(KDL.seriesOf("KXAAAGASM-26NOV30-3.90") === "KXAAAGASM", "KDL.seriesOf must derive KXAAAGASM");
    check(KDL.seriesOf("") === "", "KDL.seriesOf must not invent a series for an empty ticker");
  }

  // Fee multipliers must therefore be applied on a live-shaped row. The schedule lists KXETHY
  // as maker 0 / taker 0, so a fill on it must cost no trade fee.
  // Fee multipliers must therefore be applied on a live-shaped row. The schedule lists KXETHY
  // as maker 0 / taker 0, so a fill on it must cost no trade fee at all; KXAAAGASM is 1/1.
  check(typeof KDL.seriesTakerMult === "function", "the engine must expose seriesTakerMult");
  if (typeof KDL.seriesTakerMult === "function") {
    check(KDL.seriesTakerMult("KXETHY-27JAN0100-T4999.99") === 0,
      `KXETHY is taker multiplier 0 in the official fee schedule, got ${KDL.seriesTakerMult("KXETHY-27JAN0100-T4999.99")}`);
    check(KDL.seriesTakerMult("KXAAAGASM-26NOV30-3.90") === 1,
      "KXAAAGASM is taker multiplier 1 in the official fee schedule");
    check(KDL.takerFee(100, 0.5, KDL.seriesTakerMult("KXETHY-27JAN0100-T4999.99")) === 0,
      "a 100-contract fill on KXETHY must cost $0 in trade fees");
    check(KDL.takerFee(100, 0.5, KDL.seriesTakerMult("KXAAAGASM-26NOV30-3.90")) === 1.75,
      "a 100-contract fill on KXAAAGASM at 50c must cost $1.75 (the schedule's own table row)");
  }
  // And the normalizer must keep the raw API value alongside the derived one, so a row that
  // does carry series_ticker is never overwritten by the guess.
  check(typeof KDL.normalizeRow === "function", "the engine must expose normalizeRow for this audit");
  if (typeof KDL.normalizeRow === "function") {
    const derived = KDL.normalizeRow({ ticker: "KXETHY-27JAN0100-T4999.99", last_price_dollars: "0.9000" });
    check(derived.series_ticker === "KXETHY", `normalizeRow must derive KXETHY, got ${derived.series_ticker}`);
    const given = KDL.normalizeRow({ ticker: "KXETHY-27JAN0100-T4999.99", series_ticker: "KXZZZ", last_price_dollars: "0.9000" });
    check(given.series_ticker === "KXZZZ", "normalizeRow must keep a series_ticker the API did provide");
  }
}

if (problems.length) {
  console.error("SERIES FALLBACK PROBLEMS:");
  for (const p of problems) console.error("  -", p);
  process.exit(1);
}
console.log("OK: the engine derives the series from the market ticker when GET /markets omits series_ticker, and the fee multiplier follows the row's series.");
process.exit(0);
