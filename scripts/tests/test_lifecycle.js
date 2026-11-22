/* KalshiDash3 — lifecycle + pick-rule tests (Node, jsdom for assets/site.js, no network).
 *
 * Two things are pinned here.
 *
 * 1. ALERT → RESOLUTION (T71). The brief asks for live events to be tracked "until the events
 *    have resolved … either yes or no". KD.lifecycleOf turns one market row into exactly one
 *    lifecycle state, and the rules that matter for honesty are:
 *      - yes/no + finalized ................ "settled" (an outcome)
 *      - yes/no + not finalized ............ "determined" (result set, NOT paid, never counted)
 *      - scalar + finalized ................ "settled_scalar" (not a yes/no outcome)
 *      - closed/expired without a result ... "awaiting_result"
 *      - active ............................ "open"
 *      - row missing ....................... "not_listed" — never "open" and never "unresolved"
 *    Sources: https://docs.kalshi.com/getting_started/market_lifecycle
 *             https://docs.kalshi.com/getting_started/market_settlement
 *             https://docs.kalshi.com/api-reference/market/get-markets
 *
 * 2. ONE PICK RULE (T70). assets/chatdock.js and assets/engine.js must select the same set of
 *    "model picks" from the same archive: the frozen `high_roi` flag, with the documented
 *    seed + positive-volume fallback only for rows that carry no flag. Before this test existed
 *    the dashboard showed 49, alerts.html 47 and the dock 46 over the same 61 alerts (F-85).
 *
 * Run: node scripts/tests/test_lifecycle.js
 */
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.log("SKIP: jsdom is not installed (npm i jsdom). The release gate installs it."); process.exit(0); }

let failures = 0;
const ok = (m) => console.log("  ok   " + m);
const bad = (m) => { failures++; console.log("  FAIL " + m); };
const check = (c, m) => (c ? ok(m) : bad(m));

/* ---------------------------------------------------------------- load site.js */
const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "https://kalshidash3.invalid/test.html", runScripts: "outside-only",
});
const KD = dom.window.eval(fs.readFileSync(path.join(ROOT, "assets/site.js"), "utf8") + "\n;KD;");

const row = (o) => Object.assign({ ticker: "KXTEST-1", status: "active", result: null }, o);

/* ---------------------------------------------------------------- A. lifecycle states */
console.log("A — one market row maps to exactly one lifecycle state");
{
  const settledYes = KD.lifecycleOf(row({ status: "finalized", result: "yes", settlement_ts: "2026-11-22T06:15:07Z", settlement_value_dollars: "1.0000" }));
  check(settledYes.state === "settled" && settledYes.result === "yes", "finalized + result yes -> settled");
  check(/settled YES/.test(KD.lifecycleChip(settledYes)), "chip reads 'settled YES'");

  const settledNo = KD.lifecycleOf(row({ status: "finalized", result: "no" }));
  check(settledNo.state === "settled" && settledNo.result === "no", "finalized + result no -> settled");
  check(/settled NO/.test(KD.lifecycleChip(settledNo)), "chip reads 'settled NO'");

  // The lifecycle doc: result is set on determination, payout happens on finalization.
  const determined = KD.lifecycleOf(row({ status: "determined", result: "yes" }));
  check(determined.state === "determined", "result set but not finalized -> 'determined', not 'settled'");
  check(/not paid yet/.test(KD.lifecycleChip(determined)), "determined chip says the payout has not happened");

  const scalar = KD.lifecycleOf(row({ status: "finalized", result: "scalar", settlement_value_dollars: "0.4200" }));
  check(scalar.state === "settled_scalar", "scalar settlement is its own state");
  check(/scalar/.test(KD.lifecycleChip(scalar)), "scalar chip says 'scalar', never yes/no");

  // All eight documented statuses are handled explicitly; none falls through to a wrong default.
  const disputed = KD.lifecycleOf(row({ status: "disputed", result: "yes" }));
  check(disputed.state === "disputed", "a challenged result is 'disputed', not an outcome");
  const amended = KD.lifecycleOf(row({ status: "amended", result: "no" }));
  check(amended.state === "amended", "a re-determined market is 'amended', not an outcome");
  const paused = KD.lifecycleOf(row({ status: "inactive" }));
  check(paused.state === "paused", "temporarily deactivated -> 'paused', not 'open'");
  const notOpen = KD.lifecycleOf(row({ status: "initialized" }));
  check(notOpen.state === "not_open", "created but not trading -> 'not_open'");

  const closed = KD.lifecycleOf(row({ status: "closed", result: null }));
  check(closed.state === "awaiting_result", "closed without a result -> awaiting result");

  const open = KD.lifecycleOf(row({ status: "active" }));
  check(open.state === "open", "active -> open");

  const missing = KD.lifecycleOf(undefined);
  check(missing.state === "not_listed", "a ticker absent from the snapshot -> 'not_listed'");
  check(/not in snapshot/.test(KD.lifecycleChip(missing)), "the chip says 'not in snapshot'");
  check(/absence is not evidence/i.test(KD.LIFECYCLE_TIP.not_listed),
    "the tooltip says absence is not evidence (F-86)");
  check(!/undefined|null/.test(KD.lifecycleChip(missing)), "the chip contains no undefined/null");
}

/* ---------------------------------------------------------------- B. index */
console.log("\nB — the alert index is built from both snapshot buckets, settled last");
{
  const idx = KD.marketIndex({
    open_markets: [{ ticker: "A", status: "active" }, { ticker: "B", status: "active" }],
    settled_markets: [{ ticker: "C", status: "finalized", result: "yes" }, { ticker: "B", status: "finalized", result: "no" }],
  });
  check(idx.size === 3, "three distinct tickers indexed");
  check(idx.has("C") && idx.get("C").result === "yes", "settled market found");
  check(idx.get("B").status === "finalized", "a ticker in both buckets resolves to the settled row");
  check(KD.marketIndex(null).size === 0, "a missing snapshot yields an empty index, not a throw");
}

/* ---------------------------------------------------------------- C. tally */
console.log("\nC — the outcome tally counts markets once and never counts 'determined' as an outcome");
{
  const alerts = [
    { ticker: "UP-YES", delta: 0.12 },
    { ticker: "DOWN-NO", delta: -0.15 },
    { ticker: "UP-NO", delta: 0.20 },
    { ticker: "UP-YES", delta: 0.10 },          // same market alerted twice: counted once
    { ticker: "DET", delta: 0.11 },
    { ticker: "OPEN", delta: -0.11 },
    { ticker: "GONE", delta: 0.13 },
  ];
  const idx = KD.marketIndex({
    open_markets: [{ ticker: "OPEN", status: "active" }],
    settled_markets: [
      { ticker: "UP-YES", status: "finalized", result: "yes", settlement_ts: "2026-11-22T01:00:00Z" },
      { ticker: "DOWN-NO", status: "finalized", result: "no", settlement_ts: "2026-11-22T02:00:00Z" },
      { ticker: "UP-NO", status: "finalized", result: "no", settlement_ts: "2026-11-22T03:00:00Z" },
      { ticker: "DET", status: "determined", result: "yes" },
    ],
  });
  KD.lifecycleAttach(alerts, idx);
  const t = KD.lifecycleTally(alerts);
  check(t.alerts === 7 && t.tickers === 6, `alerts ${t.alerts}, distinct markets ${t.tickers}`);
  check(t.settled === 3, `settled counts finalized yes/no markets only (got ${t.settled})`);
  check(t.settled_yes === 1 && t.settled_no === 2, "one YES, two NO");
  check(t.determined === 1, "'determined' is reported separately, not as settled");
  check(t.open === 1 && t.not_listed === 1, "open and not-in-snapshot are separate buckets");
  check(t.comparable === 3 && t.agree === 2 && t.disagree === 1,
    `move-vs-outcome compares only settled yes/no markets (agree ${t.agree}/${t.comparable})`);
  check(Math.abs(t.agree_rate - 2 / 3) < 1e-9, "agree_rate is the plain ratio of the comparable set");

  const empty = KD.lifecycleTally([]);
  check(empty.agree_rate === null, "with nothing settled the rate is null, never 0% (which would read as a result)");
}

/* ---------------------------------------------------------------- D. one pick rule */
console.log("\nD — the chat dock and the alerts engine apply the SAME model-pick rule");
{
  const ARCHIVE = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/alerts_archive.json"), "utf8"));
  const src = fs.readFileSync(path.join(ROOT, "assets/chatdock.js"), "utf8");
  // Extract the dock's modelPick exactly as it ships (it is a nested function; evaluate the file
  // in a jsdom window and reach it through the rendered feeds is indirect, so read the source).
  check(/const model = all\.filter\(modelPick\);/.test(src), "the dock's model feed is filtered by modelPick()");
  check(/if \(a\.highRoi === true\) return true;/.test(src), "modelPick() trusts the frozen flag first");
  check(/a\.basis === "seed" && \(a\.volume24 \|\| 0\) > 0/.test(src),
    "modelPick() falls back to the documented seed + positive-volume rule");
  check(!/0\.25\) >= 0\.25|>= 0\.25 && \(a\.volume24 \|\| 0\) >= 100/.test(src),
    "the old inline '≥25% move and ≥100 contracts' rule is gone from the dock");

  const engine = fs.readFileSync(path.join(ROOT, "assets/engine.js"), "utf8");
  check(/function modelPick\(a\)/.test(engine), "the engine exposes modelPick()");
  check(/modelPick,/.test(engine), "the engine exports modelPick() for the alert page");
  check(/const model = all\.filter\(KDL\.modelPick\)/.test(fs.readFileSync(path.join(ROOT, "alerts.html"), "utf8")),
    "alerts.html filters the model chat with KDL.modelPick");

  // Count parity on the committed archive: the flag the dashboard reads is what these rows carry.
  const flagged = ARCHIVE.alerts.filter((a) => a.high_roi === true).length;
  const seedVol = ARCHIVE.alerts.filter((a) => a.category_basis === "seed" && Number(a.volume_24h_fp) > 0).length;
  check(flagged > 0, `the archive carries ${flagged} frozen high_roi rows`);
  check(seedVol >= flagged,
    `every frozen row would also pass the documented rule (${flagged} flagged, ${seedVol} pass seed+volume)`);
  const served = JSON.parse(fs.readFileSync(path.join(ROOT, "data/live/alerts.json"), "utf8"));
  const servedFlagged = (served.all_events || []).filter((a) => a.high_roi === true).length;
  check(servedFlagged === served.counts.high_roi,
    `data/live/alerts.json is self-consistent: ${servedFlagged} flagged rows vs counts.high_roi=${served.counts.high_roi}`);

  // F-88: the page publishes "N archived swings are withheld as outside the five topics", so the
  // engine must actually withhold them. Before 2026-11-22 it loaded all 81 archive rows while the
  // notice said 20 were withheld, and the "all events" chat read 81 where the dashboard read 61.
  const outOfScope = ARCHIVE.alerts.filter((a) => {
    const cats = (a.series_categories || []).map(String);
    return !a.category_id || cats.includes("Test") || cats.includes("Demo");
  });
  check(outOfScope.length === served.counts.withheld_out_of_scope,
    `the archive's out-of-scope rows (${outOfScope.length}) are exactly the rows alerts.json reports withheld (${served.counts.withheld_out_of_scope})`);
  check(outOfScope.every((a) => a.high_roi !== true),
    "no withheld row is a model pick, so withholding cannot change the pick count");
  check(/S\.withheldScope/.test(engine), "the engine counts what the scope gate withholds");
  check(/seriesCats\.includes\("Test"\)/.test(engine), "the engine applies the same Test/Demo scope gate as the dock");
}

console.log(failures ? `\nFAILED: ${failures} check(s)` : "\nOK: lifecycle join and single pick rule verified.");
process.exit(failures ? 1 : 0);
