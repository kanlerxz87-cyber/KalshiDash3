/* KalshiDash3 — regression test for the chat counters (defect F-104).
 *
 * The two scrolling chats on alerts.html, and the always-on dock on every page, each print a
 * count next to a list. The count used to be the size of the whole held set while the list held
 * only its newest rows, so it claimed 154 alerts over a feed of 120 and 3 model picks that were
 * not on screen at all. This test pins the property the page must keep:
 *
 *   A  the chip's stated number of shown rows equals the rows actually in the DOM
 *   B  the chip's stated held number equals the rows that qualify for the view
 *   C  when the list is capped, the chip says so and a control offers the held-back rows
 *   D  using that control renders every qualifying row and the chip then states the full count
 *   E  the dock's counters equal the rows the dock renders
 *   F  no NaN / undefined / null ever reaches a counter
 *
 * It reads the committed data/live/alerts.json, so it follows the archive as it grows instead of
 * depending on a hand-written number. Pure jsdom, no network.
 *
 * Run: node scripts/tests/test_chat_counts.js      (needs jsdom; installs nothing itself)
 */
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.log("SKIP: jsdom is not installed (npm i jsdom)."); process.exit(0); }

const ALERTS = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/alerts.json"), "utf8"));
const ARCHIVE = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/alerts_archive.json"), "utf8"));

let failures = 0;
const ok = (m) => console.log("  ok   " + m);
const bad = (m) => { failures++; console.log("  FAIL " + m); };
const check = (c, m) => (c ? ok(m) : bad(m));

const readJSON = (rel) => JSON.parse(fs.readFileSync(path.join(ROOT, rel), "utf8"));

// The chip has four honest shapes. Anything else is a defect, not a formatting choice.
function parseCount(text) {
  const s = String(text || "").trim();
  let m = /^(\d+)\s+in view$/.exec(s);
  if (m) return { shown: Number(m[1]), held: Number(m[1]) };
  m = /^(\d+)\s+newest of\s+(\d+)$/.exec(s);
  if (m) return { shown: Number(m[1]), held: Number(m[2]) };
  m = /^(\d+)\s+newest of\s+(\d+)\s+qualify/.exec(s);
  if (m) return { shown: Number(m[1]), held: Number(m[2]) };
  m = /^(\d+)\s+of\s+(\d+)\s+qualify$/.exec(s);
  if (m) return { shown: Number(m[1]), held: Number(m[2]) };
  m = /^(\d+)\s+of\s+(\d+)\s+shown$/.exec(s);
  if (m) return { shown: Number(m[1]), held: Number(m[2]) };
  // The dock's shape: "80 of 154" — the rows it renders and the rows it holds.
  m = /^(\d+)\s+of\s+(\d+)$/.exec(s);
  if (m) return { shown: Number(m[1]), held: Number(m[2]) };
  return null;
}

const fetchImpl = async (url) => {
  const u = String(url);
  const send = (body) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) });
  const rel = u.replace(/^https?:\/\/[^/]+\//, "").split("?")[0];
  if (rel === "data/live/alerts.json") return send(ALERTS);
  if (rel === "data/live/alerts_archive.json") return send(ARCHIVE);
  if (rel === "data/live/markets.json") return send(readJSON("data/live/markets.json"));
  if (rel === "data/live/price_history.json") return send(readJSON("data/live/price_history.json"));
  if (rel === "data/live/catalysts.json") return send({ generated_at: "", ledger: "", leads: [], disclaimers: [] });
  if (rel === "data/live/roi.json") return send(readJSON("data/live/roi.json"));
  if (rel === "data/alert_rules.json") return send(readJSON("data/alert_rules.json"));
  if (rel === "data/verified_facts.json") return send(readJSON("data/verified_facts.json"));
  if (rel === "data/findings.json") return send(readJSON("data/findings.json"));
  if (rel === "data/categories.json") return send(readJSON("data/categories.json"));
  // The demo API and every other host are unreachable here: the page must render from the
  // committed snapshot alone. A page that needs the network is a page that cannot be tested.
  const e = new TypeError("Failed to fetch");
  e.name = "TypeError";
  throw e;
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const dom = await JSDOM.fromFile(path.join(ROOT, "alerts.html"), {
    runScripts: "dangerously",
    resources: "usable",
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = fetchImpl;
      window.HTMLCanvasElement.prototype.getContext = () => new Proxy({}, {
        get: (t, k) => (k === "canvas" ? {} : (typeof t[k] === "undefined" ? () => undefined : t[k])),
        set: () => true,
      });
      try { window.localStorage.clear(); } catch (e) { /* no storage */ }
    },
  });
  const doc = dom.window.document;
  await sleep(2500);

  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const rowsIn = (sel) => doc.querySelectorAll(sel + " .chat-msg").length;

  console.log("A/B — the chip describes the feed it sits on");
  const allChip = txt(doc.querySelector("#allCount"));
  const modelChip = txt(doc.querySelector("#modelCount"));
  const allRows = rowsIn("#feedAll");
  const modelRows = rowsIn("#feedModel");

  const allParsed = parseCount(allChip);
  const modelParsed = parseCount(modelChip);
  check(allParsed !== null, `the all-events chip uses an honest count shape (read "${allChip}")`);
  check(modelParsed !== null, `the model chip uses an honest count shape (read "${modelChip}")`);
  if (!allParsed || !modelParsed) {
    console.log(`\nFAIL: ${failures} problem(s).`);
    process.exit(1);
  }
  check(allParsed.shown === allRows,
    `the all-events chip states ${allParsed.shown} shown and the feed holds ${allRows} rows`);
  check(modelParsed.shown === modelRows,
    `the model chip states ${modelParsed.shown} shown and the feed holds ${modelRows} rows`);
  check(allParsed.held === ALERTS.counts.all_events,
    `the all-events chip states ${allParsed.held} held, and the committed feed holds ${ALERTS.counts.all_events}`);
  check(modelParsed.held === ALERTS.counts.high_roi,
    `the model chip states ${modelParsed.held} held, and the committed feed holds ${ALERTS.counts.high_roi}`);

  console.log("\nC — a capped list says so and offers the rest");
  const btnAll = doc.querySelector("#btnAllMore");
  const btnModel = doc.querySelector("#btnModelMore");
  check(!!btnAll && !!btnModel, "the two chats each have a control for the held-back rows");
  if (allRows < allParsed.held) {
    check(!btnAll.hidden, `with ${allParsed.held} held and ${allRows} shown the control is visible`);
    check(/older/i.test(txt(btnAll)), `the control names what it will show ("${txt(btnAll)}")`);
    check(/newest/i.test(allChip), `the chip says the list is capped ("${allChip}")`);
  } else {
    check(btnAll.hidden, "nothing is held back, so the control is hidden");
  }
  if (modelRows < modelParsed.held) {
    check(!btnModel.hidden, `with ${modelParsed.held} held and ${modelRows} shown the control is visible`);
    check(/older/i.test(txt(btnModel)), `the control names what it will show ("${txt(btnModel)}")`);
  } else {
    check(btnModel.hidden, "nothing is held back, so the control is hidden");
  }

  console.log("\nD — the control really opens every qualifying row");
  if (btnAll && !btnAll.hidden) {
    btnAll.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    await sleep(500);
    const rows = rowsIn("#feedAll");
    const chip = txt(doc.querySelector("#allCount"));
    const parsed = parseCount(chip);
    check(rows === allParsed.held, `after expanding, the feed holds every qualifying row (${rows} of ${allParsed.held})`);
    check(parsed && parsed.shown === rows, `after expanding, the chip agrees with the feed ("${chip}" vs ${rows} rows)`);
  }
  if (btnModel && !btnModel.hidden) {
    btnModel.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    await sleep(500);
    const rows = rowsIn("#feedModel");
    const chip = txt(doc.querySelector("#modelCount"));
    const parsed = parseCount(chip);
    check(rows === modelParsed.held, `after expanding, the model feed holds every qualifying row (${rows} of ${modelParsed.held})`);
    check(parsed && parsed.shown === rows, `after expanding, the model chip agrees with the feed ("${chip}" vs ${rows} rows)`);
  }

  console.log("\nE — the dock's counters equal the rows the dock renders");
  const dockAll = txt(doc.querySelector("#kdCountAll"));
  const dockModel = txt(doc.querySelector("#kdCountModel"));
  const dockAllRows = doc.querySelectorAll("#kdChatAll .cd-msg").length;
  const dockModelRows = doc.querySelectorAll("#kdChatModel .cd-msg").length;
  const dAll = parseCount(dockAll), dModel = parseCount(dockModel);
  check(dAll !== null, `the dock's all-events counter uses an honest shape (read "${dockAll}")`);
  check(dModel !== null, `the dock's model counter uses an honest shape (read "${dockModel}")`);
  if (dAll) check(dAll.shown === dockAllRows, `the dock states ${dAll.shown} shown and renders ${dockAllRows} rows`);
  if (dModel) check(dModel.shown === dockModelRows, `the dock states ${dModel.shown} shown and renders ${dockModelRows} rows`);

  console.log("\nF — no NaN / undefined / null in any counter");
  for (const [name, value] of [["#allCount", allChip], ["#modelCount", modelChip], ["#kdCountAll", dockAll], ["#kdCountModel", dockModel]]) {
    check(!/NaN|undefined|null/i.test(value), `${name} has no placeholder text ("${value}")`);
  }

  dom.window.close();
  if (failures) { console.log(`\nFAIL: ${failures} problem(s).`); process.exit(1); }
  console.log("\nOK: every chat counter states exactly what its list holds.");
})().catch((e) => { console.error(e); process.exit(2); });
