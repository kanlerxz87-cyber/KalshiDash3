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
function makeEnv({ apiMode, archive, snapshot, ticks, pollMs, health }) {
  const state = { calls: [], polled: 0 };
  const fnum = (v) => { const n = Number(v); return Number.isNaN(n) ? null : n; };

  const fetchImpl = async (url) => {
    const u = String(url);
    const send = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
    if (/^data\/live\/alerts_archive\.json/.test(u)) return send(archive);
    if (/^data\/live\/markets\.json/.test(u)) return send(snapshot);
    // R93-3: the collector's own pass record. Omitting it must behave exactly as before.
    if (/^data\/live\/collector_health\.json/.test(u)) {
      return health ? send(health) : send({}, 404);
    }
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
    modelTotal: w.document.getElementById("kdCountModel").textContent,
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
  // F-76: a ≥$0.10 row is replayed only when it is in one of the five topics. Rows whose series
  // GET /series files under Test/Demo, or with no confirmed topic, are withheld and counted.
  const inScope = archiveWithDecoy.alerts.filter((a) => {
    const cats = (a.series_categories || []).map(String);
    return Math.abs(Number(a.delta)) >= 0.10 - 1e-9
      && !cats.includes("Test") && !cats.includes("Demo") && !!a.category_id;
  }).length;
  check(c.all > 0, `history replay rendered ${c.all} rows`);
  check(c.all === Math.min(inScope, 80), `row count equals the in-scope ≥$0.10 archive rows (${inScope})`);
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
  // T70/D-02: the model chat must be exactly the archive's frozen high_roi screen, not an inline
  // rule of its own, and it must not be a filter over the all-events display window (F-95: with a
  // single 80-row buffer the model chat showed 58 of the 96 frozen rows). The two interfaces are:
  //   - the rendered model list shows the newest MAX_ROWS (80) of the WHOLE frozen screen;
  //   - the model counter reports the WHOLE frozen screen, AND how many of them are on screen.
  // (main's earlier version compared against the frozen rows inside the newest 80 events; that
  // tolerated the truncation. This version keeps main's badge check and restores the screen check.)
  //
  // F-105 (2026-11-27): the badge used to print the held count alone ("123") next to a list of
  // 80 rows, so the badge claimed 123 model picks while the reader could see 80 of them. The
  // counter now prints both numbers ("80 of 123"). The check below keeps the original intent —
  // the held number must be the whole frozen screen, never a subset of it — and adds the F-105
  // property that the shown number matches the rows actually rendered.
  const frozenScreen = archiveWithDecoy.alerts.filter((a) => {
    const cats = (a.series_categories || []).map(String);
    return Math.abs(Number(a.delta)) >= 0.10 - 1e-9
      && !cats.includes("Test") && !cats.includes("Demo") && !!a.category_id
      && a.high_roi === true;
  }).length;
  check(c.model === Math.min(frozenScreen, 80),
    `rendered model rows equal the frozen high_roi screen up to the 80-row display window (min(${frozenScreen}, 80))`);
  const modelCounter = /^(\d+)(?:\s+of\s+(\d+))?$/.exec(String(c.modelTotal).trim());
  check(!!modelCounter, `the model counter is a plain count, or a count of what is shown (read "${c.modelTotal}")`);
  if (modelCounter) {
    check(Number(modelCounter[2] === undefined ? modelCounter[1] : modelCounter[2]) === frozenScreen,
      `the model counter's held number equals the whole frozen high_roi screen (${frozenScreen})`);
    check(Number(modelCounter[1]) === c.model,
      `the model counter's shown number (${modelCounter[1]}) equals the rows rendered (${c.model})`);
  }
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

  /* -------------------------------------------------- H: health line (T32) */
  console.log("\nT32 — run health line (R-B1: no cron name, no expected interval)");
  const health = env3.w.document.getElementById("kdHealth").textContent;
  // R-B1 + F-73 together: the panel must report what it can prove (the newest run, how many of
  // the last N were scheduled, the last success), must never resurrect the 20-minute claim, and
  // must not turn a fixed interval into a pass/fail judgement about the relay itself.
  check(/collector relay|collector:|not reachable/.test(health), `health line renders ("${health.slice(0, 70)}…")`);
  check(!/\*\/20|cronExpression|every 20m/.test(health), "health line names no cron and no expected interval (R-B1, F-73)");
  check(/newest run|no runs in the last|API not reachable/.test(health), "health line reports the newest run (R-B1)");
  check(/15-min relay grid/.test(health), "the relay label names the 15-minute grid the collector actually runs (F-73)");
  const healthSrc = SRC.slice(SRC.indexOf("freshness / run health"));
  check(/observedMinutes/.test(healthSrc) && /gap > observed \* 2/.test(healthSrc),
        "the throttling warning compares the scheduled gap against measured spacing (F-40 signal kept)");

  /* ------------------------------------ R93-3: staleness + collector-failure disclosure */
  console.log("\nR93-3 — a blocked poller must not be called 'current', and a failed pass must be visible");
  const old = new Date(Date.now() - 3 * 3600 * 1000).toISOString().replace(/\.\d+Z$/, "Z");
  const staleSnap = { ...SNAPSHOT, collected_at: old };

  // (a) blocked poller + a stale snapshot: the old wording claimed the poller was "still current".
  const envA = makeEnv({ apiMode: "blocked", archive: ARCHIVE, snapshot: staleSnap, ticks: [] });
  await sleep(150); open(envA.w); await sleep(100);
  const snapLine = envA.w.document.getElementById("kdSnapLine").textContent;
  check(!/still current/.test(snapLine),
    `the dock does not claim a blocked poller is current ("${snapLine.slice(-70)}")`);
  check(/no live poller is running/.test(snapLine),
    "it says every row is as old as the snapshot instead");
  check(/stale/.test(snapLine), "it still labels the snapshot stale");

  // (b) the same stale snapshot with the poller running: the history rows are the stale part.
  const envB = makeEnv({ apiMode: "live", archive: ARCHIVE, snapshot: staleSnap,
    ticks: [[["KXBTCY-27JAN0100-B47500", 0.5]]], pollMs: 400 });
  await sleep(900); open(envB.w); await sleep(400);
  const snapLineB = envB.w.document.getElementById("kdSnapLine").textContent;
  check(/live poller is current/.test(snapLineB) && /history rows\s+are not/.test(snapLineB),
    `with the poller running it says the poller is current and history is not ("${snapLineB.slice(-80)}")`);

  // (c) a FAILED last pass is named on the page, with the run linked, no GitHub visit required.
  const failedHealth = {
    schema: 1, generated_at: new Date(Date.now() - 10 * 60000).toISOString().replace(/\.\d+Z$/, "Z"),
    pass: 2, outcome: "failed", detail: "validators: validate_alerts", stderr_tail: "",
    run: { workflow: "collect.yml", run_id: "46058054873", attempt: "1", sha: "abc" },
  };
  const envC = makeEnv({ apiMode: "blocked", archive: ARCHIVE, snapshot: SNAPSHOT, ticks: [], health: failedHealth });
  await sleep(150); open(envC.w); await sleep(120);
  const note = envC.w.document.getElementById("kdHealthNote").textContent;
  check(/last collector pass failed/.test(note), `a failed pass is named ("${note.slice(0, 60)}…")`);
  check(/validate_alerts/.test(note), "the failing step is named, not just 'something failed'");
  const links = [...envC.w.document.querySelectorAll("#kdHealthNote a")].map((a) => a.href);
  check(links.some((h) => h.includes("/actions/runs/46058054873")), "the failing run is linked");

  // (d) a healthy pass says so, and an absent record says nothing at all.
  const okHealth = { ...failedHealth, outcome: "ok", detail: "snapshot committed" };
  const envD = makeEnv({ apiMode: "blocked", archive: ARCHIVE, snapshot: SNAPSHOT, ticks: [], health: okHealth });
  await sleep(150); open(envD.w); await sleep(120);
  const noteD = envD.w.document.getElementById("kdHealthNote").textContent;
  check(/last collector pass committed/.test(noteD) && !/failed/.test(noteD),
    `a committed pass is reported as such ("${noteD.slice(0, 50)}…")`);
  const noteE = env3.w.document.getElementById("kdHealthNote").textContent;
  check(noteE === "", "no health record means no claim either way");

  console.log("");
  teardown();
  if (failures) { console.log(`FAILED: ${failures} check(s)`); process.exit(1); }
  console.log("OK: alert chat dock — history, threshold, live path, blocked fallback and health all verified.");
  process.exit(0);
})();
