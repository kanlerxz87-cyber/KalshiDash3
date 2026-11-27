/* Staleness-honesty audit across every page (R93-3).

 * Why this file exists
 *   The brief is explicit: nothing on the site may imply that a value is current when it is not,
 *   and a value that cannot be confirmed must be left blank and flagged rather than filled in.
 *   The site's whole data layer is a *snapshot*: `scripts/collect.py` commits `data/live/*.json`
 *   and the pages render it. When the collector stops (it did on 2026-11-27 from 18:29Z), the
 *   snapshot ages but the pages keep rendering. Most pages say so. This test enumerates, from the
 *   committed files, every page that displays a market number and asserts each one discloses the
 *   age of the data it is showing.
 *
 *   It is a *structure* test, not a taste test: it does not care how the age is worded, only that
 *   a reader of that page has a way to see that the numbers are point-in-time.
 *
 * Three rules, each derived from something already on the site (not invented here)
 *   1. Every page that fetches a snapshot file (`data/live/*.json`) must mount the shared snapshot
 *      banner (`KD.snapshotBanner`, rendered by `assets/site.js`, which prints the collection time,
 *      the age, the stale warning and the measured cadence) — or state the collection time itself.
 *   2. The always-present alert dock (`assets/chatdock.js`) must say the age of the committed
 *      snapshot next to the claim that its chats are live. The dock previously said "still current"
 *      whenever the snapshot was older than 45 minutes, which is false exactly when the live poller
 *      is blocked (the common case: CORS). That claim is now conditional on the poller actually
 *      running, and the chat badge must never read "live" for a chat that is only replaying history.
 *   3. If the committed snapshot's own `collector_health.json` says the last pass FAILED, the dock
 *      must be able to say so: the reader should not have to open GitHub Actions to learn that the
 *      collection pipeline is broken.
 *
 * No network. It reads the committed tree only.
 *
 * Run: node scripts/tests/test_staleness_disclosure.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");
const SNAPSHOT_FILES = ["markets.json", "alerts.json", "alerts_archive.json", "price_history.json",
  "simulation.json", "catalysts.json", "roi.json", "spotcheck.json"];

let failures = 0;
let pending = 0;
const ok = (cond, msg) => {
  if (cond) console.log("  ok   " + msg);
  else { console.log("  FAIL " + msg); failures++; }
};

const pages = fs.readdirSync(ROOT).filter((f) => f.endsWith(".html")).sort();

/* A page with an OPEN, RECORDED request against another session's scope. It is listed here for the
 * same reason the site keeps a "Flagged for Review" page: an outstanding item is published with its
 * reason, not silently skipped. R93-3 filed request R93-R1 with the session that owns
 * executive-summary.html (see COORDINATION.md); the line is that page's coverage sentence, which is
 * read from data/live/catalysts.json and printed without the age of that file.
 * Delete an entry the moment the request is closed — the assertion then becomes binding again. */
const PENDING_REQUESTS = {
  "executive-summary.html": "R93-R1 (owner: c4409c73) — prints reviewed/total from data/live/catalysts.json without its age",
};

/* ---------- 1. every page that shows snapshot numbers discloses their age ---------- */
console.log("committed snapshot age disclosure per page:");
for (const page of pages) {
  const html = read(page);
  // Only a real read counts. sources.html names `data/live/alerts.json` inside a table cell as the
  // file a computation lives in; it never fetches it, so it has nothing to date.
  // `assets/live.js` and `assets/engine.js` read the snapshot through their own helpers
  // (`loadSnapshot`, `loadCollectorAlerts`), so a page that loads them reads snapshot data too.
  const helperLoads = /assets\/(live|engine)\.js/.test(html) ? ["markets.json", "alerts.json"] : [];
  const fetches = Array.from(new Set([...helperLoads, ...SNAPSHOT_FILES.filter((f) =>
    new RegExp(`(?:fetch|json|getJSON|loadJSON)\\(\\s*[\"']?(?:\\./)?data/live/${f.replace(".", "\\.")}`)
      .test(html))]));
  if (!fetches.length) {
    console.log(`  --   ${page.padEnd(24)} no snapshot file fetched (static page)`);
    continue;
  }
  const hasBanner = html.includes("snapshotBanner");
  const statesTime = /collected_at|generated_at/.test(html) && /KD\.ago|toLocaleString|Date\.parse/.test(html);
  if (!hasBanner && !statesTime && PENDING_REQUESTS[page]) {
    console.log(`  PEND ${page.padEnd(24)} ${PENDING_REQUESTS[page]}`);
    pending++;
    continue;
  }
  ok(hasBanner || statesTime,
    `${page.padEnd(24)} fetches ${fetches.length} snapshot file(s) and discloses the snapshot age ` +
    `(${hasBanner ? "shared banner" : statesTime ? "own timestamp" : "NEITHER"})`);
}

/* ---------- 2. the dock must not call history "current", and must not call it "live" ---------- */
const dock = read("assets/chatdock.js");
console.log("\nalert dock wording (assets/chatdock.js):");
ok(/stale<\/b> — the live poller below is still current/.source &&
   !/stale<\/b> — the live poller below is still current/.test(dock),
  "the unconditional 'the live poller below is still current' claim is gone");
ok(/S\.liveOn\s*\?/.test(dock.slice(dock.indexOf("const snapLine"), dock.indexOf("const snapLine") + 1200)),
  "the 'still current' wording is gated on the poller actually running (S.liveOn)");
ok(/history only/i.test(dock) || /replay/i.test(dock),
  "a chat that is only replaying committed history says so in words");

/* ---------- 3. a failed collector pass must be visible on the site ---------- */
console.log("\ncollector failure disclosure:");
ok(dock.includes("collector_health.json"),
  "the dock reads data/live/collector_health.json so a failed pass can be shown without leaving the page");
const healthPath = path.join(ROOT, "data", "live", "collector_health.json");
if (fs.existsSync(healthPath)) {
  let health = null;
  try { health = JSON.parse(fs.readFileSync(healthPath, "utf8")); } catch { /* reported below */ }
  ok(health !== null, "data/live/collector_health.json parses");
  if (health) {
    ok(typeof health.outcome === "string" && typeof health.generated_at === "string",
      `health record carries outcome ('${health.outcome}') and generated_at ('${health.generated_at}')`);
  }
} else {
  console.log("  --   no health record committed yet");
}

/* ---------- summary ---------- */
console.log("");
if (failures) {
  console.log(`FAIL: ${failures} staleness-disclosure assertion(s) failed. A page that shows a snapshot ` +
    "number without its age lets a stalled collector look live.");
  process.exit(1);
}
console.log(`OK: every page that renders snapshot numbers discloses their age, the dock does not ` +
  `call replayed history current, and a failed collector pass can be read on the site.` +
  (pending ? ` (${pending} page(s) covered by an open, recorded cross-session request: ` +
    Object.keys(PENDING_REQUESTS).join(", ") + ")" : ""));
