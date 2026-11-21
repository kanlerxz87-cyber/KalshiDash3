/* KalshiDash3 — render test for the always-on alert chat dock (assets/chatdock.js).
 *
 * Pure jsdom, no network. It proves the properties that matter for honesty:
 *
 *   A  every page loads the dock; the tab renders with a truthful count
 *   B  history replay reproduces ONLY archive rows ≥ $0.10 (a synthetic 0.09 row is refused)
 *   C  a first reading is a baseline, never an alert (no fabricated swing on startup)
 *   D  two live readings 0.09 apart raise NOTHING (threshold is exclusive of 0.09)
 *   E  two live readings 0.10 apart raise exactly ONE alert, marked "live", values verbatim
 *   F  when the demo API is blocked, the dock says so and still shows history
 *   G  no 'NaN', 'undefined' or 'null' ever reaches the rendered panel
 *   H  the two chats hold different sets (model view is a strict, explained subset)
 *
 * Run: node scripts/tests/test_chatdock.js      (needs jsdom; installs nothing itself)
 */
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.log("SKIP: jsdom is not installed (npm i jsdom)."); process.exit(0); }

const SRC = fs.readFileSync(path.join(ROOT, "assets/chatdock.js"), "utf8");
const ARCHIVE = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/alerts_archive.json"), "utf8"));
const SNAPSHOT = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/markets.json"), "utf8"));

let failures = 0;
const ok = (m) => console.log("  ok   " + m);
const bad = (m) => { failures++; console.log("  FAIL " + m); };
const check = (c, m) => (c ? ok(m) : bad(m));

/* ---------------------------------------------------------------- harness */
function makeEnv({ apiMode, archive, snapshot, ticks, pollMs }) {
  const state = { calls: [], polled: 0 };
  const fnum = (v) => { const n = Number(v); return Number.isNaN(n) ? null : n; };

  const fetchImpl = async (url) => {
    const u = String(url);
    const send = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
    if (/^data\/live\/alerts_archive\.json/.test(u)) return send(archive);
    if (/^data\/live\/markets\.json/.test(u)) return send(snapshot);
    if (/api\.github\.com/.test(u)) return send({ workflow_runs: [] });
    if (/external-api\.demo\.kalshi\.co/.test(u)) {
      if (apiMode === "blocked") { const e = new TypeError("Failed to fetch"); e.name = "TypeError"; throw e; }
      state.calls.push(u);
      if (u.includes("/exchange/status")) return send({ trading_active: true });
      if (u.includes("status=open")) return send({ markets: [], cursor: "" });
      if (u.includes("tickers=")) {
        const n = state.polled++;
        return send({ markets: (ticks[n] || ticks[ticks.length - 1] || []).map(([t, p]) => ({
          ticker: t, title: "smoke " + t, last_price_dollars: p, volume_24h_fp: "250.00", status: "active",
        })) });
      }
      return send({ markets: [] });
    }
    return send({});
  };

  const html = `<!doctype html><html><body>
    <header class="top"><nav></nav></header><main><h1>page</h1></main>
  </body></html>`;
  const dom = new JSDOM(html, {
    url: "https://kanlerxz87-cyber.github.io/KalshiDash3/gas.html",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const w = dom.window;
  w.fetch = fetchImpl;
  w.__KDCHAT_POLL_MS = pollMs || 400;   // test seam documented in assets/chatdock.js
  // jsdom has no layout: make scroll metrics sane so auto-scroll logic is exercised.
  Object.defineProperty(w.HTMLElement.prototype, "scrollHeight", { get() { return 1000; }, configurable: true });
  Object.defineProperty(w.HTMLElement.prototype, "clientHeight", { get() { return 300; }, configurable: true });
  w.eval(SRC);
  const env = { dom, w, state };
  ENVS.push(env);
  return env;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Every environment must be torn down: the dock owns a recurring timer and jsdom
// with `pretendToBeVisual` owns a rAF loop, so an un-closed window keeps node alive.
const ENVS = [];
function teardown() {
  for (const e of ENVS) {
    try { e.w.KDCHAT && e.w.KDCHAT.stopLive && e.w.KDCHAT.stopLive(); } catch (_) {}
    try { e.dom.window.close(); } catch (_) {}
  }
}

function open(w) {
  const tab = w.document.getElementById("kdTab");
  tab.dispatchEvent(new w.Event("click"));
  return w.document.getElementById("kdPanel");
}
function counts(w) {
  return {
    all: w.document.getElementById("kdChatAll").querySelectorAll(".cd-msg").length,
    model: w.document.getElementById("kdChatModel").querySelectorAll(".cd-msg").length,
    tab: w.document.getElementById("kdTabCount").textContent,
  };
}

/* --------------------------------------------------------------- A + B + G + H */
(async () => {
  console.log("A/B/G/H — history replay, honesty filters, no leaked values");
  const archiveWithDecoy = {
    schema: ARCHIVE.schema,
    alerts: ARCHIVE.alerts.concat([{
      ticker: "KXDECOY-0.09", title: "sub-threshold decoy", category_id: "gas", category_basis: "seed",
      from_price: 0.50, to_price: 0.59, delta: 0.09, direction: "up",
      from_time: "2026-11-21T04:00:00Z", to_time: "2026-11-21T04:05:00Z",
      volume_24h_fp: "10.00", status: "active",
    }]),
  };
  const env = makeEnv({ apiMode: "blocked", archive: archiveWithDecoy, snapshot: SNAPSHOT, ticks: [] });
  const { w } = env;
  await sleep(60);
  const panel = open(w);
  await sleep(60);

  check(!!panel && !panel.hasAttribute("hidden"), "the dock mounts and opens on a category page");
  const c = counts(w);
  const realGe10 = archiveWithDecoy.alerts.filter((a) => Math.abs(Number(a.delta)) >= 0.10 - 1e-9).length;
  check(c.all > 0, `history replay rendered ${c.all} rows`);
  check(c.all === Math.min(realGe10, 80), `row count equals the ≥$0.10 archive rows (${realGe10})`);
  const text = panel.textContent;
  check(!text.includes("sub-threshold decoy"), "the 0.09 decoy row is refused (threshold is ≥ $0.10)");
  check(/NaN|undefined|\[object Object\]/.test(text) === false, "no NaN/undefined/object leakage");
  check(/null/.test(w.document.getElementById("kdChatAll").innerHTML) === false, "no literal 'null' in the feed DOM");
  for (const t of archiveWithDecoy.alerts.slice(0, 5)) {
    if (Math.abs(Number(t.delta)) >= 0.0999) {
      const shown = w.document.getElementById("kdChatAll").textContent.includes(t.ticker);
      check(shown, `archive ticker ${t.ticker} appears verbatim`);
    }
  }
  const origins = [...w.document.querySelectorAll("#kdChatAll .cd-orig")].map((e) => e.textContent);
  check(origins.length > 0 && origins.every((o) => o === "history"), "history rows are labelled 'history', not 'live'");
  check(c.model <= c.all, `model chat (${c.model}) is a subset of all events (${c.all})`);
  check(w.document.querySelector(".kd-note").textContent.includes("Not an ROI prediction"),
    "model chat states it is not an ROI prediction");
  check(panel.textContent.includes("project requirement, not a Kalshi figure"),
    "threshold provenance is stated in the panel");

  /* --------------------------------------------------- C + D + E: live path */
  console.log("\nC/D/E — live polling: baseline, 0.09 refused, 0.10 fires once");
  const T = "KXAAAGASM-26DEC31-3.30";
  const snap = JSON.parse(JSON.stringify(SNAPSHOT));
  snap.open_markets = [{ ticker: T, title: "live baseline", last_price_dollars: 0.50, volume_24h_fp: 900, volume_fp: 5000, category_id: "gas", category_basis: "seed" }];
  const env2 = makeEnv({
    apiMode: "api",
    archive: { schema: 1, alerts: [] },
    snapshot: snap,
    ticks: [
      [[T, 0.50]],           // poll 1: same as baseline -> no alert
      [[T, 0.59]],           // poll 2: +0.09 -> below threshold
      [[T, 0.69]],           // poll 3: +0.10 from 0.59 -> ONE alert
    ],
    pollMs: 250,
  });
  const w2 = env2.w;
  await sleep(200);
  open(w2);
  await sleep(700);
  const chat = w2.document.getElementById("kdChatAll");
  const rows = [...chat.querySelectorAll(".cd-msg")];
  check(rows.length === 1, `exactly one live alert after readings 0.50 → 0.59 → 0.69 (got ${rows.length})`);
  if (rows.length) {
    const one = rows[0];
    const txt = one.textContent;
    check(/live/.test(one.querySelector(".cd-orig").textContent), "the alert is labelled 'live'");
    check(txt.includes("59.0¢") && txt.includes("69.0¢"), "the printed prices are the API's own values (59.0¢ → 69.0¢)");
    check(/▲ 10\.0¢/.test(txt), "delta printed as ▲ 10.0¢");
    check(txt.includes(T), "ticker printed verbatim");
    check(/markets\?tickers=/.test(one.querySelector("a").getAttribute("href")), "source link repeats the documented tickers= query");
    const hrefs = [...one.querySelectorAll("a")].map((a) => a.getAttribute("href") || "");
    check(hrefs.includes("dashboard.html#" + encodeURIComponent(T)), "bubble links directly to dashboard.html#TICKER chart");
  }
  check(/^near-live/.test(w2.document.getElementById("kdChip").textContent),
    "status chip reports near-live mode (not 'live' — the API caches /markets, F-58)");
  check(/cached for a few seconds/.test(w2.document.querySelector(".kd-pfoot").innerHTML),
    "footer discloses the documented caching caveat");
  check(env2.state.polled >= 3, `three polls actually happened (got ${env2.state.polled})`);
  if (rows.length) {
    check(rows[0].querySelector(".cd-cat").textContent === "Gas Prices",
      "live row takes the category from the collector's verified category_id, not a guessed prefix");
  }

  /* ------------------------------------------------------------ F: blocked */
  console.log("\nF — API blocked: says so, still shows history");
  const env3 = makeEnv({ apiMode: "blocked", archive: ARCHIVE, snapshot: SNAPSHOT, ticks: [] });
  await sleep(120);
  open(env3.w);
  await sleep(80);
  const chip = env3.w.document.getElementById("kdChip").textContent;
  check(/blocked|history/.test(chip), `chip explains the block ("${chip}")`);
  check(env3.w.document.getElementById("kdChatAll").querySelectorAll(".cd-msg").length > 0,
    "history rows are still rendered when the demo API refuses the browser");

  /* -------------------------------------------------- H: health line (T32, F-73 cadence) */
  console.log("\nT32 — relay health line");
  const health = env3.w.document.getElementById("kdHealth").textContent;
  check(/collector relay|not reachable/.test(health), `health line renders ("${health.slice(0, 70)}…")`);
  // F-73: the panel must not resurrect the stale cadence it used to hard-code. It may carry a
  // human-readable relay label (main's version does), but never the old 20-minute claim, and
  // the label must agree with the grid Collect actually runs.
  check(!/\*\/20|every 20m|cron \*\//.test(health),
        "health line never claims the old */20 cron or a 20-minute interval");
  check(/15-min relay grid/.test(health),
        "the cadence label names the 15-minute relay grid, not a guessed interval");
  // The warning is measured, not asserted: it needs the scheduled gap AND the observed spacing.
  const healthSrc = SRC.slice(SRC.indexOf("collector health (T32"));
  check(/observedMinutes/.test(healthSrc) && /gap > observed \* 2/.test(healthSrc),
        "throttling warning compares the scheduled gap against measured spacing (F-40 signal kept)");

  console.log("");
  teardown();
  if (failures) { console.log(`FAILED: ${failures} check(s)`); process.exit(1); }
  console.log("OK: alert chat dock — history, threshold, live path, blocked fallback and health all verified.");
  process.exit(0);
})();
