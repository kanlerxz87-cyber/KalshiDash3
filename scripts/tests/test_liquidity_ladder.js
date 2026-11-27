/* Regression test (defect F-100): the dashboard's implied YES-ask ladder.
 *
 * Kalshi returns BIDS ONLY. The docs define the mapping
 * (https://docs.kalshi.com/getting_started/orderbook_responses):
 *
 *   best YES ask      = $1.00 - (highest price in no_dollars)
 *   contracts at that = the count at that same no_dollars level
 *
 * and list every no_dollars level ASCENDING by price. dashboard.html rendered the no_bid
 * rows in reverse, so under the heading "YES asks, implied — contracts a buyer can lift" it
 * printed the NO-bid prices themselves ($0.9730, $0.9740, $0.9750) instead of the implied YES
 * asks ($0.0270, $0.0260, $0.0250), and ordered them best-last. A trader reading "how many
 * contracts can I buy YES for, and at what price" got the complement of the truth: on
 * KXPGATOUR-MAST27-MFIT it advertised ~20,000 contracts at $0.973-$0.975 when 6,666.66 were
 * available at $0.025.
 *
 * This test drives the shipped page in jsdom against the committed snapshot and asserts the
 * ladder prints implied YES asks in best-first order. It fails before the fix.
 *
 * Run: node scripts/tests/test_liquidity_ladder.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.log("SKIP: jsdom is not installed (npm i jsdom@26)."); process.exit(0); }

const markets = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/markets.json"), "utf8"));

const CTX2D = new Proxy({}, {
  get: (t, k) => (k === "canvas" ? {} : (["fillStyle", "strokeStyle", "font", "lineWidth", "globalAlpha"].includes(k) ? "" : () => undefined)),
  set: () => true,
});

function inlineAssets(html) {
  return html.replace(/<script src="([^"]+)"><\/script>/g, (m, src) =>
    "<script>\n" + fs.readFileSync(path.join(ROOT, src.replace(/^\.\//, "")), "utf8") + "\n</script>");
}

function mkFetch() {
  return async function fetchImpl(url) {
    const u = String(url);
    if (/external-api\.demo\.kalshi\.co|demo-api\.kalshi\.co/.test(u)) throw new TypeError("Failed to fetch");
    const rel = u.replace(/^\.\//, "").split("?")[0].replace(/^.*\/KalshiDash3(?:\.github\.io)?\//, "");
    const file = path.join(ROOT, rel);
    if (!file.startsWith(ROOT) || !fs.existsSync(file)) return { ok: false, status: 404, json: async () => ({}), text: async () => "" };
    const txt = fs.readFileSync(file, "utf8");
    return { ok: true, status: 200, json: async () => JSON.parse(txt), text: async () => txt };
  };
}

const problems = [];
const check = (cond, msg) => { if (!cond) problems.push(msg); };

(async () => {
  // Pick a market the collector captured an order book for, with real depth on both sides,
  // rather than hard-coding a ticker that a later snapshot might not contain.
  const liq = (markets.liquidity || []).filter((l) => {
    const ob = l.orderbook || {};
    return !ob.error && (ob.no_bids || []).length >= 2 && (ob.yes_bids || []).length >= 2;
  });
  if (!liq.length) { console.log("SKIP: the committed snapshot has no order book with depth on both sides."); process.exit(0); }
  const target = liq[0];
  const book = target.orderbook;

  // The official mapping, recomputed here from Kalshi's own raw levels.
  const impliedAsks = book.no_bids
    .map((r) => ({ price: Math.round((1 - r.price) * 10000) / 10000, contracts: r.contracts }))
    .sort((a, b) => a.price - b.price);
  const bestAsk = impliedAsks[0];

  const html = inlineAssets(fs.readFileSync(path.join(ROOT, "dashboard.html"), "utf8"));
  const dom = new JSDOM(html, {
    url: "https://kalshidash3.invalid/dashboard.html#" + encodeURIComponent(target.ticker),
    runScripts: "dangerously",
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = mkFetch();
      window.HTMLCanvasElement.prototype.getContext = () => CTX2D;
      window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    },
  });
  await new Promise((r) => setTimeout(r, 1500));
  const doc = dom.window.document;

  // Select the market explicitly; the hash may already have done it, but do not depend on that.
  const sel = doc.querySelector("#seriesSel");
  check(!!sel, "dashboard.html must expose the market selector (#seriesSel)");
  const head = (doc.querySelector("#liqHead") || {}).textContent || "";
  check(head.includes(target.ticker), `the liquidity panel must describe ${target.ticker}; it reads: ${head.slice(0, 200)}`);

  const blocks = [...doc.querySelectorAll("#liq > div")];
  check(blocks.length === 2, `the liquidity panel must render two ladders (YES bids, implied YES asks), got ${blocks.length}`);
  const askBlock = blocks[1];
  const askRows = [...(askBlock ? askBlock.querySelectorAll(".book .row") : [])].map((r) => {
    const spans = [...r.querySelectorAll("span")];
    return {
      priceText: (spans[0] || {}).textContent || "",
      contractsText: (spans[spans.length - 1] || {}).textContent || "",
    };
  });
  check(askRows.length > 0, "the implied YES-ask ladder rendered no rows");

  if (askRows.length) {
    // (1) The first row must be the BEST (lowest) implied ask, and the count must be the
    //     number of YES contracts actually liftable at that price.
    const firstPrice = Number(String(askRows[0].priceText).replace(/[^0-9.]/g, ""));
    const firstCount = Number(String(askRows[0].contractsText).replace(/[^0-9.]/g, ""));
    check(Math.abs(firstPrice - bestAsk.price) < 5e-5,
      `the first implied-ask row must be the best ask ${bestAsk.price} (= 1 - highest no_bid ${book.no_bids[book.no_bids.length - 1].price}), got ${firstPrice}`);
    // The site renders contract counts with 0 decimals everywhere (KD.num), so compare after
    // rounding the API's fractional count the same way; the value must be the NO-bid count.
    check(Math.abs(firstCount - Math.round(bestAsk.contracts)) < 0.011,
      `the first implied-ask row must show the contracts available at that ask (${bestAsk.contracts}), got ${firstCount}`);
    // (2) No row may print a NO-bid price as if it were a YES ask. Every implied ask below
    //     0.50 is a valid YES ask; a NO bid above 0.50 printed verbatim is the defect.
    for (const row of askRows) {
      const p = Number(String(row.priceText).replace(/[^0-9.]/g, ""));
      const isRawNoBid = book.no_bids.some((r) => Math.abs(r.price - p) < 5e-5);
      const isImpliedAsk = impliedAsks.some((r) => Math.abs(r.price - p) < 5e-5);
      check(!(isRawNoBid && !isImpliedAsk),
        `the implied-ask ladder prints the NO-bid price ${p} as a YES ask; the YES ask is 1 - ${p} = ${(1 - p).toFixed(4)}`);
    }
    // (3) Ascending price = best (cheapest) ask first, which is how a buyer reads a ladder.
    const prices = askRows.map((r) => Number(String(r.priceText).replace(/[^0-9.]/g, "")));
    const sorted = prices.slice().sort((a, b) => a - b);
    check(JSON.stringify(prices) === JSON.stringify(sorted),
      `the implied-ask ladder must be ordered best-price-first (ascending), got ${prices.join(", ")}`);
  }
  // The heading must not promise "implied" asks while showing bids verbatim.
  const askHeading = (askBlock.querySelector("h3") || {}).textContent || "";
  check(/implied/i.test(askHeading), `the ask ladder heading must say the asks are implied; it reads "${askHeading}"`);

  dom.window.eval("try{KDL.stop()}catch(e){}");

  if (problems.length) {
    console.error("LIQUIDITY LADDER PROBLEMS:");
    for (const p of problems) console.error("  -", p);
    process.exit(1);
  }
  console.log(`OK: implied YES-ask ladder for ${target.ticker} prints ${bestAsk.price} x ${bestAsk.contracts} first, ascending, with complements not raw NO bids.`);
  process.exit(0);
})().catch((e) => { console.error("FAILED:", (e && e.stack) || e); process.exit(1); });
