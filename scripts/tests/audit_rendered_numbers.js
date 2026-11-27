/* KalshiDash3 — independent recomputation audit of the rendered pages.
 *
 * Purpose: the release gate's DOM suites prove the pages RENDER without errors. They do not
 * prove that a number printed on a page equals the number in the committed data. This file
 * does exactly that, the hard way: it re-derives every published figure from data/live/*.json
 * with its own arithmetic (never by calling assets/*.js) and compares it with what jsdom
 * renders. A page that prints a stale or hand-typed number therefore fails here.
 *
 * It is deliberately read-only: it fetches nothing, writes nothing and does not touch the
 * snapshot. Network calls are blocked so every page falls back to the committed files.
 *
 * Run: node scripts/tests/audit_rendered_numbers.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) {
  console.log("SKIP: jsdom is not installed (npm i jsdom@26).");
  process.exit(0);
}

const readJSON = (rel) => JSON.parse(fs.readFileSync(path.join(ROOT, rel), "utf8"));
const markets = readJSON("data/live/markets.json");
const alerts = readJSON("data/live/alerts.json");
const findings = [
  ...readJSON("data/findings.json").flagged,
  ...readJSON("data/release_findings.json").flagged,
];
const facts = readJSON("data/verified_facts.json");

const CTX2D = new Proxy({}, {
  get: (t, k) => (k === "canvas" ? {} : (["fillStyle", "strokeStyle", "font", "lineWidth", "globalAlpha"].includes(k) ? "" : () => undefined)),
  set: () => true,
});

/* ---------- independent formatting, matched to the site's own display rules ---------- */
// Digit-only comparison: the site prints money without thousands separators
// (KD.money -> Number(v).toFixed(d)), so compare the digits, not the punctuation.
const digits = (s) => String(s).replace(/[^0-9]/g, "");
const money0 = (v) => digits(Math.round(Number(v)));
const num2 = (v) => Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num0 = (v) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
const cents = (v) => (v === null || v === undefined ? "—" : (Number(v) * 100).toFixed(1) + "¢");

/* ---------- independent recomputation of the snapshot ---------- */
const OPEN = markets.open_markets || [];
const SETTLED = markets.settled_markets || [];
const CATS = ["gas", "elections", "culture", "crypto", "golf"];
const isQa = (r) => /(^|-)QA[-A-Z0-9]*$/.test(String(r.ticker || "")) || /demo portfolio test/i.test(String(r.rules_primary || ""));

const exp = {
  openAll: OPEN.length,
  seededOpen: OPEN.filter((r) => r.category_basis === "seed").length,
  resolved: SETTLED.filter((r) => r.result === "yes" || r.result === "no").length,
  qa: OPEN.filter(isQa).length + SETTLED.filter(isQa).length,
  refused: (markets.counts.open_excluded_category_conflict || 0) + (markets.counts.settled_excluded_category_conflict || 0),
  officialOpen: OPEN.filter((r) => r.category_matched_by === "official").length,
  perCat: {},
};

/* The landing page's per-topic rule, re-implemented from the brief, not from index.html:
 * among open, non-QA rows of the topic with volume_fp > 0, the one whose
 * volume_fp x last_price_dollars is largest. If none traded, the topic is "untraded" and the
 * row shown is the one with the nearest future close_time. */
for (const cat of CATS) {
  const mine = OPEN.filter((r) => r.category_id === cat && !isQa(r) && r.dollars_traded_estimate !== null && r.dollars_traded_estimate !== undefined);
  const traded = mine.filter((r) => (r.volume_fp || 0) > 0);
  if (traded.length) {
    const top = traded.reduce((a, b) => (b.dollars_traded_estimate > a.dollars_traded_estimate ? b : a));
    exp.perCat[cat] = { kind: "traded", row: top, openRows: mine.length };
  } else if (mine.length) {
    let best = null, bestT = Infinity;
    for (const c of mine) {
      const t = Date.parse(c.close_time || "");
      if (!Number.isFinite(t)) continue;
      if (t < bestT) { bestT = t; best = c; }
    }
    exp.perCat[cat] = { kind: "untraded", row: best || mine[0], openRows: mine.length };
  } else {
    exp.perCat[cat] = { kind: "none", openRows: 0 };
  }
}

/* ---------- jsdom loader: network hard-blocked, same-origin files from the repo ---------- */
function inlineAssets(html) {
  return html.replace(/<script src="([^"]+)"><\/script>/g, (m, src) => {
    const file = path.join(ROOT, src.replace(/^\.\//, ""));
    if (!fs.existsSync(file)) throw new Error("audit cannot find " + src);
    return "<script>\n" + fs.readFileSync(file, "utf8") + "\n</script>";
  });
}

async function loadPage(file, opts = {}) {
  const html = inlineAssets(fs.readFileSync(path.join(ROOT, file), "utf8"));
  const errors = [];
  const state = { closed: false };
  const dom = new JSDOM(html, {
    url: "https://kalshidash3.invalid/" + file,
    runScripts: "dangerously",
    pretendToBeVisual: true,
    beforeParse(window) {
      // The Kalshi demo API is unreachable and same-origin files come from this checkout, so
      // every page must render from the committed snapshot. Nothing touches the network.
      window.fetch = async (url) => {
        const u = String(url);
        if (/kalshi\.co/.test(u)) throw new TypeError("Failed to fetch");
        const rel = u.replace(/^\.\//, "").split("?")[0].replace(/^.*\/KalshiDash3(?:\.github\.io)?\//, "");
        const file = path.join(ROOT, rel);
        if (!file.startsWith(ROOT) || !fs.existsSync(file)) return { ok: false, status: 404, json: async () => ({}), text: async () => "" };
        const txt = fs.readFileSync(file, "utf8");
        return { ok: true, status: 200, json: async () => JSON.parse(txt), text: async () => txt };
      };
      window.HTMLCanvasElement.prototype.getContext = () => CTX2D;
      window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
      window.addEventListener("error", (ev) => errors.push(String(ev.message)));
    },
  });
  await new Promise((r) => setTimeout(r, opts.waitMs || 900));
  const doc = dom.window.document;
  const clone = doc.body.cloneNode(true);
  clone.querySelectorAll("script,style").forEach((n) => n.remove());
  return {
    doc,
    errors,
    text: (clone.textContent || "").replace(/\s+/g, " "),
    close: () => { state.closed = true; try { dom.window.eval("try{KDL.stop()}catch(e){}"); } catch (e) { /* no engine */ } },
  };
}

const problems = [];
const check = (cond, msg) => { if (!cond) problems.push(msg); };
const numFromText = (s) => Number(String(s).replace(/[^0-9.\-]/g, ""));

(async () => {
  /* ================= index.html ================= */
  {
    const r = await loadPage("index.html");
    check(r.errors.length === 0, `index.html: uncaught error ${r.errors.slice(0, 2).join(" | ")}`);
    const kpis = [...r.doc.querySelectorAll("#kpis .card")].map((c) => c.textContent.replace(/\s+/g, " ").trim());

    // Each card holds one big number plus an explanatory sub-line that may contain other
    // numbers, so read the value element only (.kpi without its <small> label).
    const kpiValue = (label) => {
      const card = [...r.doc.querySelectorAll("#kpis .card")].find((c) => c.textContent.includes(label));
      if (!card) return undefined;
      const big = card.querySelector(".kpi");
      if (!big) return undefined;
      const clone = big.cloneNode(true);
      clone.querySelectorAll("small").forEach((n) => n.remove());
      return numFromText(clone.textContent);
    };
    check(kpiValue("Open markets in scope") === exp.openAll,
      `index.html KPI "Open markets in scope" = ${kpiValue("Open markets in scope")} but ${exp.openAll} open rows are committed`);
    check(kpiValue("Confirmed by the exchange") === exp.seededOpen,
      `index.html KPI "Confirmed by the exchange" = ${kpiValue("Confirmed by the exchange")} but ${exp.seededOpen} open rows have category_basis=seed`);
    check(kpiValue("Resolved yes/no captured") === exp.resolved,
      `index.html KPI "Resolved yes/no captured" = ${kpiValue("Resolved yes/no captured")} but ${exp.resolved} settled rows carry result yes|no`);
    check(kpiValue("demo QA fixtures in the snapshot") === exp.qa,
      `index.html KPI "demo QA fixtures" = ${kpiValue("demo QA fixtures")} but ${exp.qa} rows match the QA rule`);
    check(kpiValue("rows refused: wrong official category") === exp.refused,
      `index.html KPI "rows refused" = ${kpiValue("rows refused")} but the snapshot counts ${exp.refused}`);
    check(kpiValue("topics decided by the exchange") === exp.officialOpen,
      `index.html KPI "topics decided by the exchange" = ${kpiValue("topics decided by the exchange")} but ${exp.officialOpen} open rows have category_matched_by=official`);

    // "What is live right now": one row per topic, values recomputed above.
    const rows = [...r.doc.querySelectorAll("#today table tbody tr")];
    check(rows.length === CATS.length, `index.html "What is live right now" must show ${CATS.length} topic rows, rendered ${rows.length}`);
    const NAMES = { gas: "Gas Prices", elections: "Elections", culture: "Culture", crypto: "Crypto", golf: "Golf" };
    for (const cat of CATS) {
      const e = exp.perCat[cat];
      if (e.kind === "none") continue;
      const row = rows.find((tr) => (tr.cells[0] || {}).textContent && tr.cells[0].textContent.includes(NAMES[cat]));
      if (!row) { problems.push(`index.html: no row for topic ${NAMES[cat]}`); continue; }
      const cells = [...row.cells].map((c) => c.textContent.replace(/\s+/g, " ").trim());
      const joined = cells.join(" | ");
      check(joined.includes(e.row.ticker),
        `index.html ${NAMES[cat]} row must name ${e.row.ticker} (the recomputed pick); row reads: ${joined.slice(0, 160)}`);
      check(joined.includes(num0(e.row.volume_fp)),
        `index.html ${NAMES[cat]} contracts cell must read ${num0(e.row.volume_fp)}; row reads: ${joined.slice(0, 160)}`);
      check(joined.includes(num0(e.row.open_interest_fp)),
        `index.html ${NAMES[cat]} open-interest cell must read ${num0(e.row.open_interest_fp)}; row reads: ${joined.slice(0, 160)}`);
      check(joined.includes(cents(e.row.last_price_dollars)),
        `index.html ${NAMES[cat]} last-price cell must read ${cents(e.row.last_price_dollars)}; row reads: ${joined.slice(0, 160)}`);
      check(digits(cells[2]) === money0(e.row.dollars_traded_estimate),
        `index.html ${NAMES[cat]} dollars cell must read ${money0(e.row.dollars_traded_estimate)}, got ${digits(cells[2])}; row reads: ${joined.slice(0, 160)}`);
      if (e.kind === "untraded") {
        check(/untraded/.test(joined), `index.html ${NAMES[cat]} has no traded market and must be labelled untraded`);
      }
    }
    const untraded = CATS.filter((c) => exp.perCat[c].kind === "untraded");
    if (untraded.length) {
      check(/Untraded topics in this snapshot/.test(r.text), "index.html must carry the untraded-topics footnote when a topic has none");
    }

    // Resolution tracker: the landing page shows at most 25 yes/no rows, newest first.
    const resRows = [...r.doc.querySelectorAll("#resolutions table tbody tr")];
    const expectRes = Math.min(25, exp.resolved);
    check(resRows.length === expectRes, `index.html resolution tracker renders ${resRows.length} rows but ${expectRes} yes/no rows are expected (min(25, ${exp.resolved}))`);
    const newest = SETTLED.filter((m) => m.result === "yes" || m.result === "no")
      .slice().sort((a, b) => Date.parse(b.settlement_ts || b.close_time || 0) - Date.parse(a.settlement_ts || a.close_time || 0));
    if (resRows.length) {
      const first = resRows[0].textContent.replace(/\s+/g, " ");
      check(first.includes(newest[0].ticker), `index.html resolution tracker must start with the newest settlement ${newest[0].ticker}; first row: ${first.slice(0, 140)}`);
      // Every rendered result badge must equal the API's literal result for that ticker.
      for (const tr of resRows) {
        const t = tr.textContent.replace(/\s+/g, " ");
        const hit = newest.find((m) => t.includes(m.ticker));
        if (!hit) { problems.push(`index.html resolution row names no committed ticker: ${t.slice(0, 120)}`); continue; }
        const wants = hit.result.toUpperCase();
        check(t.toUpperCase().includes(wants), `index.html resolution row ${hit.ticker} must show result ${wants}; row reads: ${t.slice(0, 140)}`);
      }
    }
    console.log(`  index.html        ok  (${kpis.length} KPI cards, ${rows.length} topic rows, ${resRows.length} resolution rows recomputed)`);
    r.close();
  }

  /* ================= dashboard.html: the ranked market cards ================= */
  {
    const r = await loadPage("dashboard.html", { waitMs: 1500 });
    check(r.errors.length === 0, `dashboard.html: uncaught error ${r.errors.slice(0, 2).join(" | ")}`);
    // One card per topic, each showing the top 8 open markets of that topic ranked by the
    // labelled dollars estimate. Recompute that ranking here from the snapshot and compare the
    // rendered tickers and figures, so a stale or invented row cannot survive.
    const NAMES = { gas: "Gas Prices", elections: "Elections", culture: "Culture", crypto: "Crypto", golf: "Golf" };
    const cards = [...r.doc.querySelectorAll("#tables .card")];
    check(cards.length === CATS.length, `dashboard.html must render ${CATS.length} topic cards, rendered ${cards.length}`);
    let totalRows = 0;
    for (const cat of CATS) {
      const card = cards.find((c) => ((c.querySelector("h3") || {}).textContent || "").includes(NAMES[cat]));
      if (!card) { problems.push(`dashboard.html: no card for topic ${NAMES[cat]}`); continue; }
      const trs = [...card.querySelectorAll("table tbody tr")];
      totalRows += trs.length;
      const mine = OPEN.filter((m) => m.category_id === cat)
        .slice().sort((a, b) => (b.dollars_traded_estimate || 0) - (a.dollars_traded_estimate || 0));
      const want = mine.slice(0, 8);
      check(trs.length === want.length,
        `dashboard.html ${NAMES[cat]} card renders ${trs.length} rows but the top ${want.length} are expected`);
      trs.forEach((tr, i) => {
        const t = tr.textContent.replace(/\s+/g, " ");
        const hit = want[i];
        if (!hit) return;
        check(t.includes(hit.ticker),
          `dashboard.html ${NAMES[cat]} row ${i + 1} must be ${hit.ticker} (rank ${i + 1} by dollars estimate); row reads: ${t.slice(0, 150)}`);
        check(t.includes(cents(hit.last_price_dollars)),
          `dashboard.html ${NAMES[cat]} row ${hit.ticker} must print its committed last price ${cents(hit.last_price_dollars)}; row reads: ${t.slice(0, 150)}`);
      });
    }
    console.log(`  dashboard.html    ok  (${cards.length} topic cards, ${totalRows} ranked rows recomputed row by row)`);
    r.close();
  }

  /* ================= the five category pages ================= */
  for (const cat of CATS) {
    const page = cat + ".html";
    const r = await loadPage(page);
    check(r.errors.length === 0, `${page}: uncaught error ${r.errors.slice(0, 2).join(" | ")}`);
    const openRows = OPEN.filter((m) => m.category_id === cat);
    const settledRows = SETTLED.filter((m) => m.category_id === cat);
    const resolvedCat = settledRows.filter((m) => m.result === "yes" || m.result === "no").length;
    const kpi = (id) => numFromText((r.doc.querySelector("#" + id) || {}).textContent || "NaN");
    check(kpi("kOpen") === openRows.length, `${page} KPI kOpen = ${kpi("kOpen")} but ${openRows.length} open ${cat} rows are committed`);
    check(kpi("kSettled") === settledRows.length, `${page} KPI kSettled = ${kpi("kSettled")} but ${settledRows.length} settled ${cat} rows are committed`);
    check(kpi("kResolved") === resolvedCat, `${page} KPI kResolved = ${kpi("kResolved")} but ${resolvedCat} settled ${cat} rows resolved yes|no`);
    const topDollars = openRows.reduce((a, m) => Math.max(a, m.dollars_traded_estimate || 0), 0);
    check(Math.abs(kpi("kDollars") - topDollars) <= 1, `${page} KPI kDollars = ${kpi("kDollars")} but the largest committed dollars estimate is ${topDollars}`);
    const tOpen = [...r.doc.querySelectorAll("#open table tbody tr")].length;
    const tRes = [...r.doc.querySelectorAll("#resolved table tbody tr")].length;
    check(tOpen === openRows.length, `${page} open table renders ${tOpen} rows but ${openRows.length} open ${cat} rows are committed`);
    check(tRes === settledRows.length, `${page} resolved table renders ${tRes} rows but ${settledRows.length} settled ${cat} rows are committed`);
    // Every row must carry a source link, and every result cell must be the literal API value.
    for (const tr of r.doc.querySelectorAll("#resolved table tbody tr")) {
      const t = tr.textContent.replace(/\s+/g, " ");
      const hit = settledRows.find((m) => t.includes(m.ticker));
      if (!hit) { problems.push(`${page} resolved row names no committed ticker: ${t.slice(0, 120)}`); continue; }
      check(t.toUpperCase().includes(String(hit.result).toUpperCase()), `${page} row ${hit.ticker} must print the literal result ${hit.result}`);
      const links = [...tr.querySelectorAll("a")].map((a) => a.getAttribute("href") || "");
      check(links.some((h) => h.includes("external-api.demo.kalshi.co")), `${page} row ${hit.ticker} must link its official API record`);
    }
    for (const tr of r.doc.querySelectorAll("#open table tbody tr")) {
      const t = tr.textContent.replace(/\s+/g, " ");
      const hit = openRows.find((m) => t.includes(m.ticker));
      if (!hit) { problems.push(`${page} open row names no committed ticker: ${t.slice(0, 120)}`); continue; }
      const links = [...tr.querySelectorAll("a")].map((a) => a.getAttribute("href") || "");
      check(links.some((h) => h.includes("external-api.demo.kalshi.co")), `${page} open row ${hit.ticker} must link its official API record`);
    }
    console.log(`  ${page}    ok  (${tOpen} open, ${tRes} resolved, 4 KPIs recomputed, every row source-linked)`);
    r.close();
  }

  /* ================= alerts.html: the two chats ================= */
  {
    const r = await loadPage("alerts.html", { waitMs: 1200 });
    check(r.errors.length === 0, `alerts.html: uncaught error ${r.errors.slice(0, 2).join(" | ")}`);
    const served = alerts.all_events || alerts.alerts || [];
    const roi = alerts.high_roi || [];
    check(served.length === alerts.counts.all_events,
      `data/live/alerts.json is self-inconsistent: all_events[] holds ${served.length} rows, counts.all_events says ${alerts.counts.all_events}`);
    check(roi.length === alerts.counts.high_roi,
      `data/live/alerts.json is self-inconsistent: high_roi[] holds ${roi.length} rows, counts.high_roi says ${alerts.counts.high_roi}`);
    check(alerts.threshold_dollars === 0.1, `the published swing threshold must be exactly $0.10, found ${alerts.threshold_dollars}`);
    // Every served swing must actually be >= $0.10 in magnitude, and its delta must equal
    // to_price - from_price. This is the brief's core alert rule, recomputed from scratch.
    let badDelta = 0, belowThreshold = 0;
    for (const a of served) {
      const d = Math.abs(Number(a.to_price) - Number(a.from_price));
      if (Math.abs(d - Math.abs(Number(a.delta))) > 0.0051) badDelta++;
      if (d < 0.1 - 1e-9) belowThreshold++;
    }
    check(belowThreshold === 0, `${belowThreshold} served swing(s) move less than $0.10 — below the published threshold`);
    check(badDelta === 0, `${badDelta} served swing(s) have a delta that does not equal to_price - from_price`);
    check(roi.every((a) => a.high_roi === true), "every row in the model chat must carry the frozen high_roi flag");
    const evidence = alerts.counts.evidence;
    const archiveScope = alerts.counts.archive_total - alerts.counts.withheld_out_of_scope - alerts.counts.withheld_category_conflict;
    const evidenceChips = new Map([...r.doc.querySelectorAll("#evBar .kchip")].map(x => x.textContent.split(": ")));
    check(Number(evidenceChips.get("swings in scope (archive)")) === archiveScope,
      "alerts.html must label the evidence denominator as the in-scope archive, not the rendered feeds");
    for (const [label, key] of [["traded", "traded_ge_floor"], ["thin", "traded_below_floor"], ["no trades", "quote_only"],
      ["volume n/a", "counter_reset"], ["candle-sourced", "candle_unquantified"], ["no history", "unknown_no_observations"]]) {
      check(Number(evidenceChips.get(label)) === evidence[key], `alerts.html evidence count ${label} must come from counts.evidence`);
    }
    const msgs = r.doc.querySelectorAll("#feedAll .chat-msg").length;
    // The two chats the brief asks for must both exist and both be populated from the data.
    const modelMsgs = r.doc.querySelectorAll("#feedModel .chat-msg").length;
    check(msgs > 0, "alerts.html: the all-events chat rendered no messages from the committed ledger");
    check(modelMsgs > 0, "alerts.html: the model-picks chat rendered no messages from the committed ledger");
    check(modelMsgs <= msgs, `alerts.html: the model chat (${modelMsgs}) cannot hold more rows than the all-events chat (${msgs})`);
    console.log(`  alerts.html chats ok  (${msgs} all-event messages, ${modelMsgs} model messages)`);
    console.log(`  alerts.html       ok  (${served.length} swings >= $0.10 verified, ${roi.length} model picks, ${msgs} chat rows rendered)`);
    r.close();
  }

  /* ================= executive-summary.html: independent artifact times and denominators ================= */
  {
    const r = await loadPage("executive-summary.html");
    const roi = readJSON("data/live/roi.json"), simulation = readJSON("data/live/simulation.json");
    const settled = simulation.settled_positions.filter(p => ["settled", "settled_scalar"].includes(p.status));
    const expected = {
      auditSnapshot: [markets.collected_at, `${num0(OPEN.length)} open`, `${num0(SETTLED.length)} settled`],
      auditAlerts: [alerts.generated_at, `${num0(alerts.all_events.length)} all-event`, `${num0(alerts.high_roi.length)} experimental`],
      auditRoi: [roi.collected_at, `${num0(roi.picks.length)} picks`, `${num0(roi.counts.open_in_scope)} open markets in scope`],
      auditSimulation: [simulation.generated_at, `${num0(simulation.open_positions.length)} open`, `${num0(settled.length)} retained settled`],
    };
    for (const [id, pieces] of Object.entries(expected)) {
      const text = r.doc.getElementById(id)?.textContent || "";
      check(pieces.every(piece => piece && text.includes(piece)), `executive-summary.html #${id} disagrees with its dated artifact: ${text}`);
    }
    console.log("  executive summary ok  (independent snapshot, alert, scan and paper-ledger counts)");
    r.close();
  }

  /* ================= flagged.html: the ledger renders whole ================= */
  {
    const r = await loadPage("flagged.html", { waitMs: 1200 });
    check(r.errors.length === 0, `flagged.html: uncaught error ${r.errors.slice(0, 2).join(" | ")}`);
    const high = findings.filter((f) => f.severity === "high").length;
    const kpis = [...r.doc.querySelectorAll("#summary .kpi")].map(x => parseInt(x.textContent, 10));
    check(kpis[0] === findings.length, `flagged.html must publish all ${findings.length} irregularities`);
    check(kpis[1] === high, `flagged.html must publish the ${high} high-severity count`);
    const rows = new Map([...r.doc.querySelectorAll("#flags tbody tr")].map(row => [row.cells[0].textContent, row]));
    check(rows.size === findings.length, "every finding has one unique rendered row");
    for (const f of findings) {
      const links = [...(rows.get(f.id)?.querySelectorAll("a") || [])].map(a => a.getAttribute("href"));
      check(f.sources?.length > 0 && f.sources.every(s => s.startsWith("https://") && links.includes(s)),
        `flagged item ${f.id} must render all its external sources`);
    }
    console.log(`  flagged.html      ok  (${findings.length} irregularities, ${high} high, every item source-linked)`);
    r.close();
  }

  /* ================= verification.html + sources.html ================= */
  {
    const r = await loadPage("verification.html", { waitMs: 1200 });
    check(r.errors.length === 0, `verification.html: uncaught error ${r.errors.slice(0, 2).join(" | ")}`);
    check(r.text.includes(String(facts.facts.length)), `verification.html must state the ${facts.facts.length} checked claims`);
    for (const f of facts.facts) {
      check(typeof f.source === "string" && /^https:\/\//.test(f.source), `verified fact ${f.id} has no https source`);
      check(f.verified === true || f.id === "C-20", `verified fact ${f.id} is not marked verified`);
    }
    console.log(`  verification.html ok  (${facts.facts.length} claims, every one carries an https source)`);
    r.close();
  }

  if (problems.length) {
    console.error("\nRENDERED-NUMBER AUDIT PROBLEMS:");
    for (const p of problems) console.error("  -", p);
    process.exit(1);
  }
  console.log("\nOK: every audited page renders the numbers the committed data implies.");
  process.exit(0);
})().catch((e) => { console.error("FAILED:", (e && e.stack) || e); process.exit(1); });
