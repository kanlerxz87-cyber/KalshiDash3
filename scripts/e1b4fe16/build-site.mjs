#!/usr/bin/env node
// Builds the static GitHub Pages site in docs/ from data/*.json.
// No dependencies. Run: node scripts/build-site.mjs
// Every table value comes from data/snapshot.json, which records the API source URL
// and whether the official reference was opened. Nothing is inferred here.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const DOCS = join(ROOT, "docs", "e1b4fe16");
const load = (p) => JSON.parse(readFileSync(join(ROOT, p), "utf8"));

const snap = load("data/e1b4fe16/snapshot.json");
const flagData = load("data/e1b4fe16/flagged.json");
const questions = load("data/e1b4fe16/questions.json");
const suggestions = load("data/e1b4fe16/suggestions.json");
const sources = load("data/e1b4fe16/sources.json");

const FLAGS = Object.fromEntries(flagData.items.map((f) => [f.id, f]));
const CATS = [
  { id: "gas-prices", label: "Gas prices", blurb: "Daily AAA average gas-price markets (Alabama, Alaska). Primary category Economics, tag 'Oil and energy'." },
  { id: "elections", label: "Elections", blurb: "Ballot measures, nominee, debate and Secretary-General markets. Primary category Elections." },
  { id: "culture", label: "Culture", blurb: "Account-ban markets on X. Primary category Culture." },
  { id: "crypto", label: "Crypto", blurb: "Bitcoin, Chainlink, Avalanche and related markets. Primary category Crypto." },
  { id: "golf", label: "Golf", blurb: "Golf-tagged series (PGA). Primary category Sports, tag 'Golf'." },
];
const catLabel = (id) => (CATS.find((c) => c.id === id) || { label: id }).label;

// ---------- helpers ----------
const esc = (s) =>
  String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
const host = (u) => { try { return new URL(u).hostname; } catch { return u; } };
const fmtInt2 = (s) => Number(s).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const price = (s) => (s === "" || s == null ? null : `$${s}`);
const linkOut = (url, label) => `<a href="${esc(url)}" rel="noopener" target="_blank">${esc(label)}</a>`;
const unverified = (label = "Unverified") => `<span class="unv">${esc(label)}</span>`;
const flagChips = (ids) =>
  (ids || []).map((id) => `<a class="flagchip badge warn" href="flagged.html#${esc(id)}">${esc(id)}</a>`).join(" ") || '<span class="muted">none</span>';
const statusBadge = (st) => {
  const cls = st === "finalized" ? "ok" : st === "active" ? "info" : "";
  return `<span class="badge ${cls}">${esc(st || "—")}</span>`;
};
const resultBadge = (r) => {
  if (!r) return '<span class="muted">not resolved</span>';
  return `<span class="badge ${r === "yes" ? "ok" : "bad"}">${esc(r.toUpperCase())}</span>`;
};
const openedBadge = (ok) => (ok ? '<span class="badge ok">opened</span>' : '<span class="badge warn">not opened</span>');
const refCell = (url, opened) => (url ? `${linkOut(url, host(url))} ${openedBadge(opened)}` : unverified("No official link captured"));
const termsCell = (url, opened) => (url ? `${linkOut(url, "contract terms PDF")} ${openedBadge(opened)}` : unverified("No contract terms captured"));

function table(headers, rows, { numericCols = [], cls = "" } = {}) {
  const th = headers.map((h, i) => `<th class="${numericCols.includes(i) ? "num" : ""}">${h}</th>`).join("");
  const body = rows.map((r) => `<tr>${r.map((c, i) => `<td class="${numericCols.includes(i) ? "num" : ""}">${c}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table class="${cls}"><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`;
}

// ---------- page shell ----------
const NAV = [
  ["index.html", "Home"],
  ["live.html", "Live dashboard"],
  ["categories/gas-prices.html", "Gas prices"],
  ["categories/elections.html", "Elections"],
  ["categories/culture.html", "Culture"],
  ["categories/crypto.html", "Crypto"],
  ["categories/golf.html", "Golf"],
  ["analysis.html", "Analysis"],
  ["portfolio.html", "Portfolio"],
  ["suggestions.html", "Suggestions"],
  ["questions.html", "Questions"],
  ["flagged.html", "Flagged for Review"],
  ["sources.html", "Sources"],
];

function page({ root = "", file, title, active, body, scripts = "" }) {
  const nav = NAV.map(([href, label]) => {
    const cls = href === active ? ' class="active"' : "";
    return `<a href="${root}${href}"${cls}>${esc(label)}</a>`;
  }).join("");
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)} · Kalshi Demo Dashboard</title>
<meta name="description" content="Verified demo-market snapshot for Kalshi with sources, analysis, open questions and items flagged for review.">
<link rel="stylesheet" href="${root}assets/style.css">
</head>
<body>
<header class="site">
  <div class="wrap">
    <div class="brand">
      <a class="name" href="${root}index.html">Kalshi Demo Dashboard</a>
      <span class="small muted">Kalshi DEMO environment · snapshot ${esc(snap.verified_on)} · not financial advice</span>
    </div>
    <nav class="main" aria-label="Main">${nav}</nav>
  </div>
</header>
<main class="wrap" id="content">
${body}
</main>
<footer class="site">
  <div class="wrap">
    Data: Kalshi demo Trade API (<a href="https://external-api.demo.kalshi.co/trade-api/v2/exchange/status">exchange status</a>) and Kalshi documentation (<a href="https://docs.kalshi.com/llms.txt">docs index</a>).
    Demo prices may not reflect real markets. Every table row links to its source; rows that could not be confirmed are marked unverified.
    Source list: <a href="${root}sources.html">sources.html</a> · Repo: <a href="https://github.com/kanlerxz87-cyber/KalshiDash3">KalshiDash3</a>
  </div>
</footer>
${scripts}
</body>
</html>
`;
}

// ---------- derived numbers (computed only from snapshot values) ----------
const markets = snap.rows.filter((r) => r.kind === "market");
const seriesRows = snap.series;
const allFlagIds = new Set();
[...markets, ...seriesRows].forEach((r) => (r.flags || []).forEach((id) => allFlagIds.add(id)));
const flagGroups = flagData.items.reduce((acc, f) => ((acc[f.group] = (acc[f.group] || 0) + 1), acc), {});
const resolved = markets.filter((m) => m.result);
const resolvedNo = resolved.filter((m) => m.result === "no").length;
const resolvedYes = resolved.filter((m) => m.result === "yes").length;
const finalized = markets.filter((m) => m.status === "finalized").length;
const perCat = CATS.map((c) => ({
  ...c,
  markets: markets.filter((m) => m.category === c.id).length,
  series: seriesRows.filter((s) => s.category === c.id).length,
  flagged: [...markets, ...seriesRows].filter((r) => r.category === c.id && (r.flags || []).length).length,
  resolved: resolved.filter((m) => m.category === c.id).length,
}));
const rankedByVolume = [
  ...markets.map((m) => ({ type: "market", cat: m.category, name: m.ticker, title: m.title, vol: Number(m.volume), src: m.source_url, face: Number(m.volume) * Number(m.notional_value_dollars || "1") })),
  ...seriesRows.map((s) => ({ type: "series", cat: s.category, name: s.ticker, title: s.title, vol: Number(s.volume), src: s.source_url, face: null })),
].sort((a, b) => b.vol - a.vol).slice(0, 8);
const spreadRows = markets.map((m) => {
  const bid = Number(m.bid), ask = Number(m.ask);
  let quote, spread = null;
  if (bid === 0 && ask === 0) quote = "No quotes";
  else if (bid === 0 || ask >= 1) quote = "One-sided";
  else { quote = "Two-sided"; spread = ask - bid; }
  return { m, bid, ask, quote, spread };
});

// ---------- INDEX ----------
function indexPage() {
  const cards = perCat.map((c) => `
  <div class="card">
    <h3><a href="categories/${c.id}.html" class="big">${esc(c.label)}</a></h3>
    <div class="small muted">${esc(c.blurb)}</div>
    <p class="small" style="margin:10px 0 0">${c.markets} market rows · ${c.series} series rows · ${c.resolved} resolved · ${c.flagged} with flags</p>
  </div>`).join("");
  const body = `
<h1>Kalshi demo dashboard: verified snapshot</h1>
<p class="lead">A plain-English view of the Kalshi demo markets in five categories (gas prices, elections, culture, crypto, golf). Every number links to the Kalshi API response it came from. Items that could not be confirmed are marked unverified and listed on <a href="flagged.html">Flagged for Review</a>.</p>

<div class="card">
  <h2 style="margin-top:0">Executive summary</h2>
  <ul>
    <li><strong>Data source:</strong> the Kalshi <em>demo</em> Trade API responded on ${esc(snap.verified_on)} (exchange and trading active at check time). Demo prices may not match real markets (<a href="https://docs.kalshi.com/getting_started/demo_env.md">Kalshi demo docs</a>).</li>
    <li><strong>Snapshot size:</strong> ${markets.length} market rows and ${seriesRows.length} series rows across five categories. This is a verified sample. The full list is too large to pull in one session, so the <a href="live.html">live dashboard</a> loads it in your browser.</li>
    <li><strong>Resolved outcomes so far:</strong> ${resolved.length} sampled markets have a result (${resolvedNo} NO, ${resolvedYes} YES). All are Alabama or Alaska gas markets settled 2026-11-13. No crypto, election, culture or golf market in the sample has resolved.</li>
    <li><strong>Portfolio and trading: blocked.</strong> Both need a Kalshi demo account and API key, which the sandbox does not have. See <a href="portfolio.html">Portfolio</a> and question Q4.</li>
    <li><strong>Flags for review:</strong> ${flagData.items.length} items (${Object.entries(flagGroups).map(([g, n]) => `${n} ${esc(g.toLowerCase())}`).join(", ")}). Flags do not block publishing.</li>
    <li><strong>Decisions needed from you:</strong> ${suggestions.items.length} suggestions to approve, defer or reject, and ${questions.items.length} questions to answer. See <a href="suggestions.html">Suggestions</a> and <a href="questions.html">Questions</a>.</li>
  </ul>
</div>

<h2>Categories</h2>
<div class="grid">${cards}</div>

<h2>Tools</h2>
<div class="grid">
  <div class="card"><h3><a class="big" href="live.html">Live dashboard</a></h3><div class="small muted">Price chart (1 min, 1 hour, 1 day), orderbook depth (contracts available at each price), volume ranking and resolved markets. Loads from the Kalshi demo API in your browser.</div></div>
  <div class="card"><h3><a class="big" href="analysis.html">Analysis</a></h3><div class="small muted">Counts, resolved outcomes, quote quality, highest volume in the sample, and fee formula.</div></div>
  <div class="card"><h3><a class="big" href="flagged.html">Flagged for Review</a></h3><div class="small muted">Repo irregularities, data irregularities and unverified items, each with source links.</div></div>
  <div class="card"><h3><a class="big" href="sources.html">Sources</a></h3><div class="small muted">Every official page or API endpoint used, and whether it was opened.</div></div>
</div>`;
  return page({ file: "index.html", title: "Home", active: "index.html", body });
}

// ---------- CATEGORY ----------
function categoryPage(cat) {
  const ms = markets.filter((m) => m.category === cat.id);
  const ss = seriesRows.filter((s) => s.category === cat.id);
  const mRows = ms.map((m) => [
    `<a href="${esc(m.source_url)}" rel="noopener" target="_blank" class="mono">${esc(m.ticker)}</a>`,
    `<span>${esc(m.title)}</span>`,
    statusBadge(m.status),
    resultBadge(m.result),
    price(m.last) ?? unverified(),
    price(m.bid) ?? unverified(),
    price(m.ask) ?? unverified(),
    fmtInt2(m.volume),
    fmtInt2(m.open_interest),
    `<span class="mono">${esc(m.close_time)}</span>`,
    refCell(m.official_url, m.official_opened),
    termsCell(m.terms_url, m.terms_opened),
    flagChips(m.flags),
  ]);
  const sRows = ss.map((s) => [
    `<a href="${esc(s.source_url)}" rel="noopener" target="_blank" class="mono">${esc(s.ticker)}</a>`,
    esc(s.title),
    esc(s.primary_category),
    `<span class="small">${esc(s.tags)}</span>`,
    esc(s.frequency),
    fmtInt2(s.volume),
    refCell(s.official_url, s.official_opened),
    termsCell(s.terms_url, s.terms_opened),
    flagChips(s.flags),
  ]);
  const flagIds = [...new Set([...ms, ...ss].flatMap((r) => r.flags || []))];
  const flagList = flagIds.length
    ? `<ul>${flagIds.map((id) => `<li><a href="flagged.html#${esc(id)}"><strong>${esc(id)}</strong></a> ${esc(FLAGS[id]?.title || "")}</li>`).join("")}</ul>`
    : '<p class="muted">No flags on this category.</p>';
  const mBlock = ms.length
    ? `<h2>Markets (contract level, ${ms.length} rows)</h2>` +
      table(
        ["Ticker", "Title", "Status", "Result", "Last", "Bid", "Ask", "Volume (contracts)", "Open interest", "Close (UTC)", "Official reference", "Contract terms", "Flags"],
        mRows,
        { numericCols: [7, 8] }
      )
    : `<h2>Markets (contract level)</h2><div class="notice info">No open or resolved market rows for this category are in the verified snapshot. The series below still exists in the API. Open the <a href="../live.html?cat=${cat.id}">live dashboard</a> to see what is open now.</div>`;
  const sBlock = `<h2>Series (contract templates, ${ss.length} rows)</h2>` +
    table(
      ["Series", "Title", "Primary category", "Tags", "Frequency", "Volume (contracts, series total)", "Official reference", "Contract terms", "Flags"],
      sRows,
      { numericCols: [5] }
    );
  const body = `
<p class="small"><a href="../index.html">Home</a> / ${esc(cat.label)}</p>
<h1>${esc(cat.label)}</h1>
<p class="lead">${esc(cat.blurb)} Values are from the Kalshi demo API on ${esc(snap.verified_on)}. Blank or unverified cells are flagged; nothing is inferred.</p>
<div class="toolbar">
  <a class="badge info" href="../live.html?cat=${cat.id}">Open live dashboard for ${esc(cat.label)} →</a>
  <span class="small muted">${ms.length} market rows · ${ss.length} series rows · ${resolved.filter((m) => m.category === cat.id).length} resolved</span>
</div>
${mBlock}
${sBlock}
<h2>Flags on this page</h2>
<div class="card">${flagList}</div>`;
  const fixed = body.replace(/href="flagged\.html#/g, "href=\"../flagged.html#");
  return page({ root: "../", file: `categories/${cat.id}.html`, title: cat.label, active: `categories/${cat.id}.html`, body: fixed });
}

// ---------- ANALYSIS ----------
function analysisPage() {
  const catRows = perCat.map((c) => [esc(c.label), String(c.markets), String(c.series), String(c.resolved), String(c.flagged)]);
  const top = rankedByVolume.map((r) => [
    esc(catLabel(r.cat)),
    r.type === "market" ? '<span class="badge info">market</span>' : '<span class="badge">series</span>',
    `<a href="${esc(r.src)}" target="_blank" rel="noopener" class="mono">${esc(r.name)}</a>`,
    esc(r.title),
    fmtInt2(r.vol),
    r.face == null ? '<span class="muted">n/a (series total)</span>' : `$${fmtInt2(r.face)}`,
  ]);
  const spreads = spreadRows.map((x) => [
    `<span class="mono">${esc(x.m.ticker)}</span>`,
    esc(x.m.title),
    price(x.m.bid) ?? unverified(),
    price(x.m.ask) ?? unverified(),
    esc(x.quote),
    x.spread == null ? '<span class="muted">—</span>' : `$${x.spread.toFixed(4)}`,
  ]);
  const body = `
<p class="small"><a href="index.html">Home</a> / Analysis</p>
<h1>Analysis of the verified snapshot</h1>
<p class="lead">Everything on this page is computed from the verified snapshot only. No trades exist yet, so there is no trade-performance analysis (see <a href="portfolio.html">Portfolio</a>).</p>

<h2>Counts by category</h2>
${table(["Category", "Market rows", "Series rows", "Resolved markets", "Rows with flags"], catRows, { numericCols: [1, 2, 3, 4] })}
<p class="small muted">Markets in the snapshot: ${markets.length}. Finalized: ${finalized}. Resolved with a result: ${resolved.length} (NO ${resolvedNo}, YES ${resolvedYes}).</p>

<h2>Highest volume in the sample</h2>
<p class="small muted">Ranked by volume_fp (contracts). "Face value" = contracts × notional_value_dollars (1.0000 on every sampled binary market). It is the $1-per-contract face amount, not cash traded. Cash traded would need trade prices (Q1).</p>
${table(["Category", "Type", "Ticker", "Title", "Volume (contracts)", "Face value (computed)"], top, { numericCols: [4, 5] })}

<h2>Quote quality (current bid and ask)</h2>
<p class="small muted">Spread = ask − bid, computed only for two-sided quotes. One-sided quotes (bid 0 or ask 1.00) and empty books are reported as such, not as spreads.</p>
${table(["Ticker", "Title", "Bid", "Ask", "Quote type", "Spread (computed)"], spreads, { numericCols: [5] })}

<h2>Resolution</h2>
<div class="card">
  <p>${resolved.length} sampled markets have a result. Every one is a gas market settled on 2026-11-13 with result <strong>no</strong> and settlement value $0.0000 (per the API). The AAA values behind those settlements were not captured, so no price comparison is made (flag D15).</p>
  <p class="small">Settlement rule (verified in the AAA contract terms): the market pays $1.00 per winning contract, and the expiration value is the AAA figure at the stated expiration time.</p>
</div>

<h2>Fees (formula from the published schedule)</h2>
<div class="card">
  <p><strong>General taker fee:</strong> round up(0.07 × C × P × (1 − P)), where P is the contract price in dollars and C the number of contracts. <strong>Maker fee:</strong> round up(0.0175 × C × P × (1 − P)). There is no settlement fee.</p>
  <p class="small">Worked example, computed before rounding: C = 100 contracts at P = $0.46 gives 0.07 × 100 × 0.46 × 0.54 = $1.7388 (general fee). The schedule rounds up to the centicent, so the exact charge needs the schedule's rounding rule. Source: <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf">Kalshi fee schedule (page 1 of 2)</a>. Per-series multipliers are not fully confirmed (flag D16).</p>
</div>

<h2>What can and cannot be analysed yet</h2>
${table(
  ["Analysis", "Status", "Why"],
  [
    ["Counts, resolutions, quote quality, volume ranking", '<span class="badge ok">Done on sample</span>', "Verified API values in the snapshot."],
    ["Trade categories and strategy performance", '<span class="badge bad">Blocked</span>', "No trade or fill history. Needs a demo API key (U1, U7)."],
    ["Dollar amount traded per event", '<span class="badge warn">Partly</span>', "Contract counts are verified. Cash traded needs trade prices (Q1)."],
    ["Second-level price charts", '<span class="badge warn">Not available via REST</span>', "Candlesticks have a one-minute minimum (U3). Needs the WebSocket feed."],
    ["Full category ranking", '<span class="badge warn">In the live dashboard only</span>', "The full series list is too large for this snapshot (U2)."],
  ]
)}`;
  return page({ file: "analysis.html", title: "Analysis", active: "analysis.html", body });
}

// ---------- PORTFOLIO ----------
function portfolioPage() {
  const body = `
<p class="small"><a href="index.html">Home</a> / Portfolio</p>
<h1>Portfolio and trade tracking</h1>
<div class="notice bad"><strong>Status: blocked.</strong> Portfolio, balance, positions, fills and order placement all require authenticated requests. The sandbox has no Kalshi credentials, and this session cannot create a demo account or API key. Nothing on this page has been measured. Tracked by U1 and question Q4.</div>
<h2>What is needed from you (once)</h2>
<ol>
  <li>Create a Kalshi demo account. The step-by-step help article is linked from the Kalshi demo docs: <a href="https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account" rel="noopener" target="_blank">Creating and using a demo account</a> (source: <a href="https://docs.kalshi.com/getting_started/demo_env.md" target="_blank" rel="noopener">demo environment docs, opened</a>).</li>
  <li>Generate a demo API key. Demo keys only work against demo endpoints (<a href="https://docs.kalshi.com/getting_started/api_environments.md" target="_blank" rel="noopener">API environments, opened</a>).</li>
  <li>Give the key to the agent through a secure channel, never in the repo or in chat. Then the portfolio sync and trade-tracking sections can be built.</li>
</ol>
<h2>What this page will show once a key is supplied</h2>
${table(
  ["Section", "Source endpoint (authenticated)", "Status"],
  [
    ["Balance and cash", "Portfolio balance endpoint (docs.kalshi.com/api-reference)", '<span class="badge bad">Blocked</span>'],
    ["Open positions", "Portfolio positions endpoint", '<span class="badge bad">Blocked</span>'],
    ["Fills and trade history", "Portfolio fills endpoint", '<span class="badge bad">Blocked</span>'],
    ["Trade categories and strategy results", "Derived from fills (categories need your decision, Q5)", '<span class="badge bad">Blocked</span>'],
    ["Place or cancel a demo order", "Order endpoints (signed)", '<span class="badge bad">Blocked</span>'],
  ]
)}
<p class="small muted">Endpoint names are listed for orientation. Exact paths and parameters must be checked against the authenticated section of the API reference before any code is written.</p>
<h2>Decisions needed before any trade</h2>
<div class="card"><ul>
  <li>Position size and loss limits (Q6). The contract terms set a $25,000 Position Accountability Level per strike, per Member.</li>
  <li>Which categories and series may be traded (Q5).</li>
  <li>Whether orders need manual confirmation (suggestion S10).</li>
</ul></div>`;
  return page({ file: "portfolio.html", title: "Portfolio", active: "portfolio.html", body });
}

// ---------- SUGGESTIONS ----------
function suggestionsPage() {
  const rows = suggestions.items.map((s) => {
    const deps = (s.depends_on || []).map((q) => `<a href="questions.html#${esc(q)}">${esc(q)}</a>`).join(", ") || '<span class="muted">none</span>';
    return [
      `<strong>${esc(s.id)}</strong>`,
      `<strong>${esc(s.title)}</strong><div class="small muted">${esc(s.why)}</div>`,
      esc(s.effort),
      deps,
      `<span class="small">${esc(s.evidence)}</span>`,
      `<select class="decision" data-id="${esc(s.id)}" aria-label="Decision for ${esc(s.id)}">
         <option value="">Awaiting your decision</option>
         <option value="Approve">Approve</option>
         <option value="Defer">Defer</option>
         <option value="Reject">Reject</option>
       </select>`,
    ];
  });
  const body = `
<p class="small"><a href="index.html">Home</a> / Suggestions</p>
<h1>Suggestions for review</h1>
<p class="lead">Nothing here is implemented until you approve it. Pick a decision for each row. Choices are saved in this browser only, and are recorded in the repo when you tell the agent to apply them.</p>
<div class="notice info">Choices are saved in your browser (localStorage). To make them permanent, record them in data/suggestions.json or tell the agent which to approve.</div>
<div class="toolbar"><span class="status-line" id="decision-summary"></span></div>
${table(["ID", "Suggestion", "Effort", "Depends on", "Evidence", "Your decision"], rows)}`;
  return page({
    file: "suggestions.html",
    title: "Suggestions",
    active: "suggestions.html",
    body,
    scripts: '<script src="assets/suggestions.js"></script>',
  });
}

// ---------- QUESTIONS ----------
function questionsPage() {
  const rows = questions.items.map((q) => [
    `<strong id="${esc(q.id)}">${esc(q.id)}</strong>`,
    `<strong>${esc(q.question)}</strong>`,
    esc(q.known),
    `<span class="muted">${esc(q.missing)}</span>`,
    esc(q.how),
    `<span class="badge ${q.status.startsWith("Blocked") ? "bad" : q.status.startsWith("Partly") ? "warn" : "info"}">${esc(q.status)}</span>`,
    q.sources.map((s) => linkOut(s.url, s.label)).join("<br>"),
  ]);
  const body = `
<p class="small"><a href="index.html">Home</a> / Questions</p>
<h1>Questions to answer before deciding</h1>
<p class="lead">What we know (with sources), what is missing, and how to find out. A decision on trading or categories should wait until the relevant rows are answered.</p>
${table(["ID", "Question", "What we know", "What is missing", "How to discover", "Status", "Sources"], rows)}
<h2>Information gaps summary</h2>
<div class="card">
  <p>Answered in part: ${questions.items.filter((q) => q.status.startsWith("Partly")).length}. Open: ${questions.items.filter((q) => q.status.startsWith("Open")).length}. Blocked: ${questions.items.filter((q) => q.status.startsWith("Blocked")).length}.</p>
</div>`;
  return page({ file: "questions.html", title: "Questions", active: "questions.html", body });
}

// ---------- FLAGGED ----------
function flaggedPage() {
  const groups = [...new Set(flagData.items.map((f) => f.group))];
  const sevCls = { blocker: "bad", action: "warn", warning: "warn", review: "info", limit: "", info: "" };
  const sections = groups.map((g) => {
    const items = flagData.items.filter((f) => f.group === g).map((f) => `
      <div class="card" id="${esc(f.id)}">
        <div><span class="badge ${sevCls[f.severity] || ""}">${esc(f.severity)}</span>
          <strong class="mono">${esc(f.id)}</strong> · <strong>${esc(f.title)}</strong></div>
        <p style="margin:8px 0">${esc(f.detail)}</p>
        ${f.sources.length ? `<div class="small">Sources: ${f.sources.map((s) => linkOut(s.url, s.label)).join(" · ")}</div>` : '<div class="small muted">No external source (repo or process item).</div>'}
        <div class="small muted" style="margin-top:6px">Status: open, for your review. Does not block the site.</div>
      </div>`).join("");
    return `<h2>${esc(g)}</h2>${items}`;
  }).join("");
  const body = `
<p class="small"><a href="index.html">Home</a> / Flagged for Review</p>
<h1>Flagged for Review</h1>
<p class="lead">Irregularities and unverified items, published so you can review them after the site is live and request changes. Each item lists the evidence and the source links. ${flagData.items.length} items.</p>
<div class="notice">${esc(flagData.note)}</div>
${sections}`;
  return page({ file: "flagged.html", title: "Flagged for Review", active: "flagged.html", body });
}

// ---------- LIVE (shell; behaviour in assets/live.js) ----------
function livePage() {
  const body = `
<p class="small"><a href="index.html">Home</a> / Live dashboard</p>
<h1>Live dashboard</h1>
<p class="lead">Loads the Kalshi <em>demo</em> API in your browser. Pick a category, then a series, then a market. The price chart and orderbook refresh while the page is open. Nothing here places an order.</p>
<div class="notice info" id="live-status">Loading…</div>

<div class="toolbar">
  <label for="cat">Category</label>
  <select id="cat">
    <option value="gas-prices">Gas prices</option>
    <option value="elections">Elections</option>
    <option value="culture">Culture</option>
    <option value="crypto">Crypto</option>
    <option value="golf">Golf</option>
  </select>
  <label><input type="checkbox" id="autorefresh" checked> Auto-refresh every 15 s</label>
  <span class="status-line" id="last-updated"></span>
</div>

<h2>Series by volume (contracts, all-time)</h2>
<div class="table-wrap"><table><thead><tr><th>Series</th><th>Title</th><th class="num">Volume (contracts)</th><th>Frequency</th><th>Contract terms</th></tr></thead><tbody id="series-body"><tr><td colspan="5" class="muted">Loading…</td></tr></tbody></table></div>

<h2>Open markets in the selected series</h2>
<p class="small muted" id="series-label">Select a series above.</p>
<div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Title</th><th class="num">Last</th><th class="num">Bid</th><th class="num">Ask</th><th class="num">Spread</th><th class="num">Bid size</th><th class="num">Ask size</th><th class="num">Volume (contracts)</th><th class="num">Face value ($)</th><th class="num">Open interest</th><th>Close (UTC)</th></tr></thead><tbody id="market-body"></tbody></table></div>

<h2>Selected market</h2>
<p class="small muted" id="market-label">Select a market above.</p>
<div class="toolbar">
  <label for="interval">Price history interval</label>
  <select id="interval">
    <option value="1">1 minute (last 6 hours)</option>
    <option value="60" selected>1 hour (last 7 days)</option>
    <option value="1440">1 day (last 90 days)</option>
    <option value="seconds" disabled>Seconds: not available via REST (needs WebSocket)</option>
  </select>
</div>
<div class="card">
  <div class="legend small">
    <span><i style="background:#2450a6"></i>Last trade price</span>
    <span><i style="background:#0b7a5c;height:2px"></i>YES bid (close)</span>
    <span><i style="background:#a11d2e;height:2px"></i>YES ask (close)</span>
  </div>
  <div class="chart-box" id="chart"><div class="muted small">No market selected.</div></div>
  <p class="small muted">X axis: time (UTC). Y axis: contract price in dollars (0.00 to 1.00 = probability of YES).</p>
</div>

<h2>Orderbook: contracts available at each price</h2>
<p class="small muted">YES bids are buy-YES orders. A NO bid at price 1 − P is the same as a YES ask at P (Kalshi orderbook docs). Top 10 levels per side.</p>
<div class="table-wrap"><table><thead><tr><th class="num">YES bid price</th><th class="num">YES bid contracts</th><th class="num">YES ask price (1 − NO bid)</th><th class="num">YES ask contracts</th></tr></thead><tbody id="book-body"><tr><td colspan="4" class="muted">No market selected.</td></tr></tbody></table></div>

<h2>Resolved markets in the selected series</h2>
<div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Title</th><th>Result</th><th class="num">Settlement value</th><th>Close (UTC)</th><th>Last update (UTC)</th></tr></thead><tbody id="resolved-body"><tr><td colspan="6" class="muted">Select a series above.</td></tr></tbody></table></div>

<div class="notice">If this page shows a connection error, your browser could not reach the Kalshi demo API (CORS or network). The verified snapshot pages still work. Flag D18 covers this.</div>
`;
  return page({
    file: "live.html",
    title: "Live dashboard",
    active: "live.html",
    body,
    scripts: '<script src="assets/live.js"></script>',
  });
}

// ---------- SOURCES ----------
function sourcesPage() {
  const rows = sources.items.map((s) => [
    linkOut(s.url, s.name),
    esc(s.used_for),
    /Opened/.test(s.status) ? `<span class="badge ok">${esc(s.status)}</span>` : `<span class="badge">${esc(s.status)}</span>`,
  ]);
  const body = `
<p class="small"><a href="index.html">Home</a> / Sources</p>
<h1>Sources</h1>
<p class="lead">${esc(sources.note)} Checked ${esc(sources.checked_on)}.</p>
${table(["Source", "Used for", "Status"], rows)}`;
  return page({ file: "sources.html", title: "Sources", active: "sources.html", body });
}

// ---------- write ----------
const outputs = {
  "index.html": indexPage(),
  "live.html": livePage(),
  "analysis.html": analysisPage(),
  "portfolio.html": portfolioPage(),
  "suggestions.html": suggestionsPage(),
  "questions.html": questionsPage(),
  "flagged.html": flaggedPage(),
  "sources.html": sourcesPage(),
};
for (const c of CATS) outputs[`categories/${c.id}.html`] = categoryPage(c);

for (const [file, html] of Object.entries(outputs)) {
  const full = join(DOCS, file);
  mkdirSync(dirname(full), { recursive: true });
  writeFileSync(full, html);
}
console.log(`Built ${Object.keys(outputs).length} pages into docs/e1b4fe16/`);
