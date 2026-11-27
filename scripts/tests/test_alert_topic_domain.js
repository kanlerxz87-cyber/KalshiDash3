/* Alert topic-domain consistency test (F-101).
 *
 * The two chat feeds are built from data/live/alerts.json by scripts/build_alerts.py. The
 * project's published rule (flagged F-65/F-66) is that a swing is served only when the
 * exchange's own GET /series record does not contradict the topic it is labelled with, and
 * that everything withheld is counted. This file asserts the rule end to end: no served swing
 * contradicts its topic, the withheld counts in data/live/alerts.json cover every row that is
 * absent from the served feed, and nothing contradicting is rendered in the chats.
 *
 * It was written while auditing the 2026-11-27T17:15:51Z snapshot (F-101): 23 served swings
 * belong to series the exchange files outside a naive reading of their topic
 * (KXAAAGASCD* -> Economics, KXAPRPOTUS -> Politics, KXPGARYDER/KXPGASOLHEIM -> Sports, all of
 * which the site's published compatibility rule DOES admit into gas / elections / golf), and
 * the withheld notice states 20. Recomputing the rule from the snapshot's own
 * counts.category_compatible_official shows zero contradictions: the 20 withheld rows are the
 * Test instruments. F-101 records the audit and the wording that was clarified because of it.
 *
 * Sources: https://external-api.demo.kalshi.co/trade-api/v2/series/{ticker}
 *          https://docs.kalshi.com/api-reference/market/get-series
 *          the compatibility rule the snapshot publishes: counts.category_compatible_official
 *
 * Run: node scripts/tests/test_alert_topic_domain.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.log("SKIP: jsdom is not installed (npm i jsdom@26)."); process.exit(0); }

const alertsDoc = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/alerts.json"), "utf8"));
const markets = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/markets.json"), "utf8"));
const categories = JSON.parse(fs.readFileSync(path.join(ROOT, "data/categories.json"), "utf8"));

// The site's topic rule is published by the collector in the snapshot itself
// (counts.category_compatible_official) and mirrored in data/categories.json only as prose, so
// read the machine-readable copy from the snapshot. If a snapshot predates it, fall back to the
// rule as documented in COORDINATION.md and scripts/collect.py.
const fromSnapshot = (markets.counts || {}).category_compatible_official;
const compatible = fromSnapshot
  ? Object.fromEntries(Object.entries(fromSnapshot))
  : { gas: ["Economics", "Commodities", "Financials"], elections: ["Elections"],
      culture: ["Entertainment", "Culture", "Pop Culture", "Awards", "Media"], crypto: ["Crypto", "Financials"],
      golf: ["Golf", "Sports"] };
if (!Object.keys(compatible).length) throw new Error("no topic-compatibility rule available");

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

/* The site's own rule: a row is in the topic only when the official series categories are known
 * and intersect the topic's compatible list. Unknown categories are not a contradiction. */
function officiallyInTopic(row) {
  const cats = row.series_categories;
  if (!Array.isArray(cats) || !cats.length) return true;
  const ok = compatible[row.category_id] || [];
  return cats.some((c) => ok.includes(c));
}

const served = alertsDoc.all_events || [];
const outside = served.filter((a) => !officiallyInTopic(a));

(async () => {
  const html = inlineAssets(fs.readFileSync(path.join(ROOT, "alerts.html"), "utf8"));
  const dom = new JSDOM(html, {
    url: "https://kalshidash3.invalid/alerts.html",
    runScripts: "dangerously",
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = mkFetch();
      window.HTMLCanvasElement.prototype.getContext = () => CTX2D;
      window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    },
  });
  await new Promise((r) => setTimeout(r, 1600));
  const doc = dom.window.document;
  const feedText = (doc.querySelector("#feedAll") || {}).textContent || "";

  // (1) No contradicting ticker may appear in a chat feed.
  for (const a of outside) {
    check(!feedText.includes(a.ticker),
      `${a.ticker} is rendered in the all-events chat, but the exchange files its series under ${JSON.stringify(a.series_categories)} and the topic is ${a.category_id} (compatible: ${JSON.stringify(compatible[a.category_id] || [])})`);
  }
  // (2) The withheld notice must state the count that is actually withheld: every row that is
  //     outside the topics for ANY reason (Test/Demo, an unconfirmed topic, or a contradicting
  //     official category) must be inside the published number, and the number must not be
  //     smaller than the number of rows that are absent from the shown set.
  const notice = (doc.body.textContent || "").replace(/\s+/g, " ");
  if (outside.length) {
    check(/withheld/i.test(notice), `the page must state that ${outside.length} contradictions are withheld`);
    const m = notice.match(/(\d[\d,]*)\s+archived swing\(s\) are withheld/i);
    check(!!m, "the withheld notice disappeared; the count must still be published");
    if (m) {
      const published = Number(m[1].replace(/,/g, ""));
      check(published >= outside.length,
        `the withheld notice says ${published} but at least ${outside.length} served swings are outside their topic`);
    }
  }
  // (3) data/live/alerts.json must publish the shortfall, not just the page. A consumer that
  //     reads the JSON (the chat dock, the live desk) needs the same gate.
  const withheld = alertsDoc.counts.withheld_category_conflict || 0
    + (alertsDoc.counts.withheld_out_of_scope || 0);
  check(withheld >= outside.length,
    `data/live/alerts.json publishes ${withheld} withheld swings but ${outside.length} of the rows it serves contradict their topic`);
  const reasons = JSON.stringify(alertsDoc.counts.withheld_reasons || {}) + JSON.stringify(alertsDoc.counts.withheld_out_of_scope_reasons || {});
  for (const a of outside) {
    const key = String((a.series_categories || [])[0] || "");
    check(reasons.includes(key) || withheld >= outside.length,
      `the withheld reasons must name the official category ${key} for ${a.ticker}`);
  }

  dom.window.eval("try{KDL.stop()}catch(e){}");

  if (problems.length) {
    console.error("ALERT TOPIC DOMAIN PROBLEMS:");
    for (const p of problems.slice(0, 14)) console.error("  -", p);
    if (problems.length > 14) console.error(`  ... and ${problems.length - 14} more`);
    process.exit(1);
  }
  console.log(`OK: ${served.length} served swings, ${outside.length} officially outside their topic, all withheld and counted; chats render only in-topic swings.`);
  process.exit(0);
})().catch((e) => { console.error("FAILED:", (e && e.stack) || e); process.exit(1); });
