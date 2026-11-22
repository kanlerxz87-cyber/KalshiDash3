/* KalshiDash3 — per-series taker multipliers in the browser paper ledgers (F-84).
 *
 * Why this exists: every paper ledger on the site used to charge the general taker rate
 * (M = 1) regardless of series. The official fee schedule's "Non-Standard Fees" table lists
 * KXBTCY, KXETHY and KXELECTIRAN at maker 0 / taker 0, and 44 of the 61 archived alerts in
 * data/live/alerts.json are KXBTCY — so most of the paper P&L was charged a fee the exchange
 * does not charge. The fix put the table in assets/alerts.js (KDA) and assets/engine.js
 * (KDLIVE) and made portfolio.html call the shared KDA.fee instead of its own copy.
 *
 * Sources checked when writing the table (2026-11-22):
 *   https://kalshi.com/docs/kalshi-fee-schedule.pdf  (General Trading Fees; Non-Standard Fees)
 *   data/strategies.json fee_model.multipliers       (the same table scripts/simulate.py uses)
 *
 * "use strict" NODE TEST — exits non-zero on any failed assertion.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..", "..");
const problems = [];
const check = (cond, msg) => { if (!cond) problems.push(msg); };

function loadLibs() {
  const html = `<!doctype html><html><body></body></html>`;
  const dom = new JSDOM(html, { url: "https://kalshidash3.invalid/", runScripts: "dangerously" });
  const win = dom.window;
  // One eval, because a top-level `const` in a separate eval is not visible to the next one.
  // The libraries are plain classic scripts, exactly as the pages load them.
  const parts = [];
  for (const rel of ["assets/alerts.js", "assets/engine.js"]) {
    parts.push(fs.readFileSync(path.join(ROOT, rel), "utf8"));
  }
  let KDA = null, KDLIVE = null;
  try {
    win.eval(parts.join("\n;\n") +
      "\n;window.__KDA = (typeof KDA === 'object') ? KDA : null;" +
      "\n;window.__KDL = window.KDL || null;");
    KDA = win.__KDA;
    KDLIVE = win.__KDL;
  } catch (e) {
    problems.push(`assets/alerts.js + assets/engine.js threw while loading: ${e && e.message}`);
  }
  return { win, KDA, KDLIVE };
}

const { KDA, KDLIVE } = loadLibs();   // KDLIVE is window.KDL (assets/engine.js)

check(!!KDA && typeof KDA.fee === "function", "assets/alerts.js must expose KDA.fee");
check(!!KDA && typeof KDA.takerMult === "function", "assets/alerts.js must expose KDA.takerMult");
check(!!KDLIVE && typeof KDLIVE.takerFee === "function", "assets/engine.js must expose KDLIVE.takerFee");
check(!!KDLIVE && typeof KDLIVE.seriesTakerMult === "function", "assets/engine.js must expose KDLIVE.seriesTakerMult");

if (KDA && KDLIVE) {
  // 1. The schedule's zero-multiplier series must cost nothing, in both browser libraries.
  for (const t of ["KXBTCY-27JAN0100-B47500", "KXETHY-26DEC31-4000", "KXELECTIRAN-27JAN01"]) {
    check(KDA.fee(100, 0.5, t) === 0, `KDA.fee must be 0 for the M = 0 series ${t} (got ${KDA.fee(100, 0.5, t)})`);
    check(KDA.takerMult(t) === 0, `KDA.takerMult must read 0 for ${t}`);
    check(KDLIVE.takerFee(100, 0.5, KDLIVE.seriesTakerMult(t)) === 0,
      `KDLIVE.takerFee must be 0 for the M = 0 series ${t}`);
  }

  // 2. The general rate still applies to every other series and to an unknown ticker.
  for (const t of ["KXAAAGASM-26NOV30-3.90", "KXPGATOUR-THRC26-BHAR", "KXEMMYCACTO-26-NOV-TWICE", ""]) {
    check(KDA.fee(100, 0.5, t) === 1.75, `KDA.fee must be $1.75/100@50c for default-M series (${t || "no ticker"})`);
  }
  check(KDA.fee(1, 0.5, "KXAAAGASM-X") === 0.02, "KDA.fee must cent-ceil: 1 contract at 50c = $0.02");
  check(KDA.fee(100, 0.5, "KXBTCY-X") === 0 && KDLIVE.takerFee(100, 0.25, 0) === 0,
    "an M = 0 fee must never be rounded up to a cent");
  check(KDA.takerMult("kxbtcy-27jan0100-b47500") === 0, "series matching must be case-insensitive");
  check(KDA.takerMult("KXBTC15M-26NOV210145-45") === 1,
    "KXBTC15M is NOT the zero-fee series KXBTCY and must keep the default M = 1");
  check(KDLIVE.takerFee(100, 0.5, 1) === 1.75 && KDLIVE.takerFee(1, 0.5, 1) === 0.02,
    "KDLIVE.takerFee general-rate maths must be unchanged");

  // 3. The browser table must agree with the ledger scripts/simulate.py reads, so the
  //    server-side and browser-side paper results cannot diverge on fees.
  const strat = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "strategies.json"), "utf8"));
  const fm = strat.fee_model || {};
  const table = fm.multipliers || {};
  const def = fm.default_taker_multiplier;
  check(Object.keys(table).length > 0, "data/strategies.json must publish fee_model.multipliers");
  for (const [series, m] of Object.entries(table)) {
    const want = Number(m);
    const got = KDA.takerMult(`${series}-TEST`);
    const gotE = KDLIVE.seriesTakerMult(`${series}-TEST`);
    check(got === want, `KDA.takerMult(${series}) = ${got}, data/strategies.json says ${want}`);
    check(gotE === want, `KDLIVE.seriesTakerMult(${series}) = ${gotE}, data/strategies.json says ${want}`);
  }
  check(Number(def) === 1, "the documented default multiplier must stay 1");
  // Every M = 0 series in the server table must be M = 0 in the browser too (and vice versa).
  const zero = Object.entries(table).filter(([, m]) => Number(m) === 0).map(([s]) => s).sort();
  check(zero.length > 0, "the schedule is expected to contain at least one M = 0 series");
  const browserZero = Object.keys(KDA.SERIES_TAKER_MULT || {}).filter(s => (KDA.SERIES_TAKER_MULT[s] === 0)).sort();
  check(JSON.stringify(browserZero) === JSON.stringify(zero),
    `browser M = 0 series ${JSON.stringify(browserZero)} must equal the server table ${JSON.stringify(zero)}`);
} else {
  problems.push("cannot assert fee behaviour: one or both libraries failed to expose their API");
}

// 4. portfolio.html must not reintroduce a private flat-rate copy of the formula.
const portfolio = fs.readFileSync(path.join(ROOT, "portfolio.html"), "utf8");
check(/const takerFee = \(c, p, ticker\) => KDA\.fee\(c, p, ticker\);/.test(portfolio),
  "portfolio.html must delegate its takerFee to the shared KDA.fee (F-84)");
check(!/Math\.ceil\(Number\(\(1 \* 0\.07/.test(portfolio),
  "portfolio.html must not carry its own flat-0.07 fee implementation again");

if (problems.length) {
  for (const p of problems) console.error("  FAIL " + p);
  console.error(`FAILED: ${problems.length} fee-multiplier check(s).`);
  process.exit(1);
}
console.log(`  ok   fee multipliers: M = 0 for ${JSON.stringify(Object.keys(KDA.SERIES_TAKER_MULT || {}))}, default M = 1, browser table == data/strategies.json, portfolio.html delegates to KDA.fee`);
console.log("OK: per-series taker multipliers verified in assets/alerts.js, assets/engine.js and portfolio.html.");
