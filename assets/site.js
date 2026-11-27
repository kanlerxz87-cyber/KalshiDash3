/* KalshiDash3 — shared site shell + table renderers.
 * No build step, no dependencies: GitHub Pages serves docs/ as-is.
 * Every number rendered here comes from data/live/*.json (produced by
 * scripts/collect.py from the official demo API) or data/verified_facts.json
 * (checked against docs.kalshi.com). Nothing is hand-typed into the HTML.
 */
"use strict";

const KD = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const num = (v, d = 0) =>
    v === null || v === undefined || Number.isNaN(Number(v))
      ? '<span class="na" title="Not returned by the API — left blank rather than guessed">—</span>'
      : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

  const money = (v, d = 2) =>
    v === null || v === undefined || Number.isNaN(Number(v)) ? '<span class="na">—</span>' : "$" + Number(v).toFixed(d);

  const cents = (v) =>
    v === null || v === undefined || Number.isNaN(Number(v)) ? '<span class="na">—</span>' : (Number(v) * 100).toFixed(1) + "¢";

  const pct = (v, d = 1) =>
    v === null || v === undefined || Number.isNaN(Number(v)) ? '<span class="na">—</span>' : (Number(v) * 100).toFixed(d) + "%";

  const ago = (iso) => {
    if (!iso) return "unknown";
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return "unknown";
    const s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    if (s < 86400) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  };

  async function json(path) {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status} for ${path}`);
    return r.json();
  }

  const CAT_LABEL = { gas: "Gas Prices", elections: "Elections", culture: "Culture", crypto: "Crypto", golf: "Golf" };

  // Defect F-39 (2026-11-21): the 2026-11-21T00:50Z snapshot's largest open Culture market by
  // dollars estimate was the Kalshi demo QA fixture "Portfolio cash out QA 5" (GET
  // /markets/KXGRAMMYNOMROTY-QA7CECC5-QA -> rules_primary "Demo portfolio test only."), so the
  // landing page presented a test instrument as a live culture event. scripts/collect.py now
  // excludes these from every category and publishes the counts; this guard keeps a stale or
  // hand-edited snapshot from putting one back at the top of a "largest live market" table.
  const QA_RE = /demo portfolio test|portfolio cash out|\bqa\s*\d|\bbench\s+(?:run|probe)\s*\d*\b/i;
  function isQaRow(r) {
    return !r || QA_RE.test(String((r.title || "") + " " + (r.yes_sub_title || "") + " " + (r.rules_primary || "")));
  }

  function basisBadge(b, matchedBy) {
    if (b === "seed") {
      return '<span class="badge ok" title="Series ticker appears in the official Kalshi fee schedule">confirmed</span>';
    }
    if (matchedBy === "official") {
      return '<span class="badge ok" title="Series matched by Kalshi\'s official GET /series category/tag filter (not in the fee-schedule seed list)">official series</span>';
    }
    return '<span class="badge warn" title="Matched by keyword heuristic only — not confirmed by an official source">keyword</span>';
  }

  function resultBadge(r) {
    if (r === "yes") return '<span class="badge ok">YES</span>';
    if (r === "no") return '<span class="badge bad">NO</span>';
    if (r === "scalar") return '<span class="badge warn" title="Scalar settlement — not a yes/no outcome">SCALAR</span>';
    return '<span class="badge">pending</span>';
  }

  function statusBadge(s) {
    if (!s) return '<span class="na">—</span>';
    const cls = s === "active" ? "ok" : s === "finalized" ? "" : "warn";
    return `<span class="badge ${cls}">${esc(s)}</span>`;
  }

  function srcLink(url, label = "source") {
    if (!url) return '<span class="na">—</span>';
    return `<a class="srclink" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(url)}">${esc(label)}</a>`;
  }

  /* ------------------------------------------------------------------------ lifecycle
   * The brief asks for live events to be followed "until the events have resolved … either
   * yes or no". An alert is a moment in a market's life, so every alert surface can answer one
   * more question than it used to: what happened to the market afterwards?
   *
   * Everything below reads only two official fields from the collector's snapshot:
   *   status  — the market's lifecycle state   https://docs.kalshi.com/getting_started/market_lifecycle
   *   result  — yes | no | scalar once determined; settlement_ts is filled on finalization
   *                                            https://docs.kalshi.com/getting_started/market_settlement
   *                                            https://docs.kalshi.com/api-reference/market/get-markets
   *
   * Two honesty rules are built into the code, not just the prose:
   *   1. "determined" is NOT "settled". The lifecycle doc says result is set when the market is
   *      determined and positions are paid when it is finalized, so a determined market is
   *      labelled "result set · not paid yet" and never counted as an outcome.
   *   2. Absence is not evidence. The committed snapshot is a ranked window, not the whole
   *      exchange (see scripts/collect.py), so a ticker that is not in it is labelled
   *      "not in snapshot" — never "unresolved" and never "open" (D-03).
   */
  // Statuses as published on https://docs.kalshi.com/getting_started/market_lifecycle (8 values, all
  // handled explicitly so none of them can fall through to a wrong default):
  //   initialized · active · inactive · closed · determined · disputed · amended · finalized
  const RESULT_BEARING = new Set(["determined", "disputed", "amended"]);
  const TERMINAL_STATUS = new Set(["finalized", "settled", "determined", "disputed", "amended", "closed", "expired"]);

  function marketIndex(doc) {
    const m = new Map();
    for (const r of (doc?.alert_lifecycle?.rows || [])) if (r?.ticker) m.set(r.ticker, r);
    // Current ranked rows take precedence; tracking fills the gaps without changing the ranking.
    for (const r of (doc?.open_markets || []).concat(doc?.settled_markets || [])) {
      if (r?.ticker) m.set(r.ticker, { ...r, observed_at: doc.collected_at || null });
    }
    return m;
  }

  function lifecycleOf(row) {
    if (!row) return { state: "not_listed", status: null, result: null };
    const status = String(row.status || "").toLowerCase();
    const result = typeof row.result === "string" ? row.result.toLowerCase() : null;
    const base = {
      status: status || null,
      result: result,
      settlement_ts: row.settlement_ts || null,
      settlement_value_dollars: row.settlement_value_dollars ?? null,
      source: row.source || null,
      observed_at: row.observed_at || null,
      reason: row.reason || null,
    };
    if (!status) return { ...base, state: "unverified", result: null };
    const isResult = result === "yes" || result === "no" || result === "scalar";
    if (isResult) {
      if (status === "finalized" || status === "settled") {
        return Object.assign(base, { state: result === "scalar" ? "settled_scalar" : "settled" });
      }
      // A disputed result may be re-determined, and an amended market has been re-determined;
      // both are reported as what they are rather than as an outcome.
      if (status === "disputed") return Object.assign(base, { state: "disputed" });
      if (status === "amended") return Object.assign(base, { state: "amended" });
      return Object.assign(base, { state: "determined" });
    }
    if (status === "inactive") return Object.assign(base, { state: "paused" });
    if (status === "initialized") return Object.assign(base, { state: "not_open" });
    if (TERMINAL_STATUS.has(status)) return Object.assign(base, { state: "awaiting_result" });
    return Object.assign(base, { state: "open" });
  }

  const LIFECYCLE_SPEC = {
    settled: ["ok", "settled"],
    settled_scalar: ["warn", "settled (scalar)"],
    determined: ["warn", "result set · not paid yet"],
    disputed: ["warn", "result disputed"],
    amended: ["warn", "re-determined"],
    awaiting_result: ["dim", "closed · no result yet"],
    paused: ["dim", "paused by the exchange"],
    not_open: ["dim", "not open yet"],
    open: ["dim", "still open"],
    not_listed: ["dim", "not in snapshot"],
    unverified: ["warn", "status unverified"],
  };
  const LIFECYCLE_TIP = {
    settled: "Finalized: Kalshi's own result field says how this market resolved",
    settled_scalar: "Finalized with a scalar value — not a yes/no outcome, so it is not counted as one",
    determined: "The result field is populated but the market is not finalized yet, so no payout has been made",
    disputed: "The result has been challenged and may be re-determined, so it is not counted as an outcome",
    amended: "Re-determined after a dispute; the settlement timer has restarted, so it is not counted as an outcome",
    awaiting_result: "Closed but no result is published in the snapshot yet",
    paused: "Temporarily deactivated by the exchange — trading is paused but the market has not closed",
    not_open: "Created but not yet open for trading",
    open: "Still trading at the time of the snapshot in which this was last seen",
    not_listed: "No ranked or followed record for this market; absence is not evidence of an outcome",
    unverified: "The collector has not confirmed the market's current status; no result is assumed",
  };

  function lifecycleChip(life) {
    if (!life) return "";
    const spec = LIFECYCLE_SPEC[life.state] || LIFECYCLE_SPEC.not_listed;
    let text = spec[1];
    if (life.state === "settled" && life.result) text += " " + String(life.result).toUpperCase();
    const when = life.settlement_ts ? ` (${String(life.settlement_ts).replace("T", " ").replace("Z", " UTC")})` : "";
    const reason = life.reason ? ` (${life.reason})` : "";
    return `<span class="badge ${spec[0]}" title="${esc((LIFECYCLE_TIP[life.state] || "") + when + reason)}">${esc(text)}</span>`;
  }

  // Attach the lifecycle of the market each alert fired on. Never invents one: an alert whose
  // ticker is absent from the index gets state "not_listed".
  function lifecycleAttach(alerts, index) {
    for (const a of alerts || []) {
      if (!a || !a.ticker) continue;
      a.lifecycle = lifecycleOf(index && index.get ? index.get(a.ticker) : null);
    }
    return alerts;
  }

  /* Tally of what happened to the events behind a set of alerts. "agreement" is the bare
   * descriptive question the brief implies — did the printed move point the same way as the
   * eventual outcome — and it is deliberately reported as a count, not as a hit rate that would
   * dress a sample of a few demo markets up as a strategy (D-04). */
  function lifecycleTally(alerts) {
    const tickers = new Map();
    for (const a of alerts || []) {
      if (!a || !a.ticker) continue;
      if (!tickers.has(a.ticker)) tickers.set(a.ticker, a);
    }
    const t = {
      alerts: (alerts || []).length, tickers: tickers.size, open: 0, settled: 0,
      settled_yes: 0, settled_no: 0, settled_scalar: 0, determined: 0,
      disputed: 0, amended: 0, paused: 0, not_open: 0,
      awaiting_result: 0, not_listed: 0, unverified: 0, agree: 0, disagree: 0, comparable: 0,
    };
    for (const a of tickers.values()) {
      const l = a.lifecycle;
      if (!l) continue;
      if (l.state === "settled" || l.state === "settled_scalar") t.settled += 1;
      if (l.state === "settled" && l.result === "yes") t.settled_yes += 1;
      if (l.state === "settled" && l.result === "no") t.settled_no += 1;
      if (l.state === "settled_scalar") t.settled_scalar += 1;
      if (l.state === "determined") t.determined += 1;
      if (l.state === "disputed") t.disputed += 1;
      if (l.state === "amended") t.amended += 1;
      if (l.state === "paused") t.paused += 1;
      if (l.state === "not_open") t.not_open += 1;
      if (l.state === "awaiting_result") t.awaiting_result += 1;
      if (l.state === "not_listed") t.not_listed += 1;
      if (l.state === "unverified") t.unverified += 1;
      if (l.state === "open") t.open += 1;
      const d = Number(a.delta ?? (Number(a.to) - Number(a.from)));
      if (l.state === "settled" && (l.result === "yes" || l.result === "no") && Number.isFinite(d) && d !== 0) {
        t.comparable += 1;
        const agrees = (d > 0 && l.result === "yes") || (d < 0 && l.result === "no");
        if (agrees) t.agree += 1; else t.disagree += 1;
      }
    }
    t.agree_rate = t.comparable ? t.agree / t.comparable : null;
    return t;
  }

  function empty(msg) {
    return `<p class="empty">${msg}</p>`;
  }

  function table(headers, rows, opts = {}) {
    if (!rows.length) return empty(opts.empty || "No rows.");
    const th = headers.map((h) => `<th${h.num ? ' class="r"' : ""}>${h.label}</th>`).join("");
    const tb = rows
      .map((r) => "<tr>" + headers.map((h) => `<td${h.num ? ' class="r"' : ""}>${r[h.key] ?? ""}</td>`).join("") + "</tr>")
      .join("");
    return `<div class="tw"><table><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table></div>`;
  }

  /* F-73 (2026-11-21): prose said "every 20 minutes" while the collector moved to a 15-minute
   * relay grid, so any hard-coded cadence goes stale the next time the schedule changes. Compute
   * it instead, from the observation timestamps the collector already commits:
   *   - cadence = median of the last up-to-10 observation intervals
   *   - lag     = snapshot age expressed in multiples of that median (what makes a gap visible)
   * Returns null rather than guessing when the history is too short to measure. */
  async function cadence() {
    try {
      const [hist, meta] = await Promise.all([json("data/live/price_history.json"), json("data/live/markets.json")]);
      const times = new Set();
      for (const s of Object.values((hist && hist.series) || {})) {
        for (const o of (s && s.observations) || []) if (o && o.t) times.add(o.t);
      }
      const ts = Array.from(times).map((t) => Date.parse(t)).filter((n) => !Number.isNaN(n)).sort((a, b) => a - b);
      if (ts.length < 2) return null;
      const gaps = [];
      for (let i = 1; i < ts.length; i++) {
        const g = (ts[i] - ts[i - 1]) / 60000;
        if (g > 0) gaps.push(g);
      }
      const window = gaps.slice(-10);
      const sorted = window.slice().sort((a, b) => a - b);
      if (!sorted.length) return null;
      const median = sorted[Math.floor(sorted.length / 2)];
      const snapshotAt = meta && meta.collected_at;
      const age = snapshotAt ? Math.max(0, (Date.now() - Date.parse(snapshotAt)) / 60000) : null;
      return {
        median,
        sampleSize: window.length,
        distinctGaps: Array.from(new Set(window.map((g) => Math.round(g)))).sort((a, b) => a - b),
        age,
        behind: age === null ? null : Math.floor(age / median),
        snapshotAt,
        observations: ts.length,
      };
    } catch (e) {
      return null;
    }
  }

  function snapshotBanner(meta) {
    const host = $("#snapshotBanner");
    if (!host) return;
    if (!meta) {
      host.innerHTML =
        `<div class="notice warn"><b>No live snapshot committed yet.</b> The tables below are empty on purpose: this site never invents a price. ` +
        `Rankings appear after the <a href="https://github.com/kanlerxz87-cyber/KalshiDash3/actions/workflows/collect.yml">collector workflow</a> commits <code>data/live/markets.json</code>. ` +
        `The collector calls only public demo endpoints, so it needs no credentials.</div>`;
      return;
    }
    const age = Date.now() - Date.parse(meta.collected_at || "");
    const stale = !(age < 45 * 60 * 1000);
    host.innerHTML =
      `<div class="notice ${stale ? "warn" : "blue"}">` +
      `<b>Snapshot:</b> ${esc(meta.collected_at)} <span class="mut">(${ago(meta.collected_at)})</span> · ` +
      `<b>Environment:</b> ${esc(meta.environment)} · ` +
      `<b>Endpoint:</b> <code>${esc(meta.base_url)}</code> · ` +
      `<b>Scanned:</b> ${num(meta.counts?.open_total_scanned)} open / ${num(meta.counts?.settled_total_scanned)} settled · ` +
      `<b>Published:</b> ${num(meta.counts?.open_published_rows ?? meta.counts?.open_in_scope)} open / ` +
      `${num(meta.counts?.settled_published ?? meta.counts?.settled_in_scope)} settled rows ` +
      `<span class="mut">(settled rows are allocated across the five topics; ` +
      `${num(meta.counts?.settled_in_scope_total ?? meta.counts?.settled_in_scope)} settled markets were found in scope)</span>` +
      (stale
        ? ` · <b>Stale fallback:</b> no collection has committed for ${ago(meta.collected_at).replace(" ago", "")}, so these numbers may be out of date. ` +
          `GitHub's scheduler is best-effort — its docs say scheduled runs "can be delayed" and "some queued jobs may be dropped" ` +
          `(<a href="https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule" target="_blank" rel="noopener">GitHub Actions: schedule</a>) — ` +
          `and the site shows the snapshot age instead of implying it is current. The alert chats on the <a href="live.html">Live Desk</a> still poll the demo API directly when CORS allows.`
        : "") +
      `<span class="kd-cadence"></span>` +
      `</div>`;
    // F-73: the cadence is measured from the committed observations, never typed into the page.
    // It is rendered after the banner so a slow history fetch cannot delay the snapshot line.
    const slot = host.querySelector(".kd-cadence");
    if (slot) {
      cadence().then((c) => {
        if (!c) {
          slot.innerHTML = ` · <b>Cadence:</b> not measurable from the committed observations yet`;
          return;
        }
        slot.innerHTML =
          ` · <b>Cadence:</b> about every ${num(Math.round(c.median))} min` +
          ` <span class="mut">(median of the last ${num(c.sampleSize)} observation intervals; distinct gaps seen: ` +
          `${esc(c.distinctGaps.join(", "))} min; ${num(c.observations)} observation times on record)</span>` +
          (c.behind !== null && c.behind >= 3
            ? ` · <b class="warn">snapshot is ${num(c.behind)} collection intervals behind</b> — the collector is not keeping its cadence, so read every price here as of <code>${esc(c.snapshotAt)}</code>`
            : "");
      });
    }
  }

  function nav(active) {
    const items = [
      ["index.html", "Home"],
      ["executive-summary.html", "Summary"],
      ["categories.html", "Categories"],
      ["dashboard.html", "Live Dashboard"],
      ["live.html", "Live Desk"],
      ["roi.html", "ROI Model"],
      ["alerts.html", "Alert Chats"],
      ["trading.html", "Auto-Sim"],
      ["portfolio.html", "Portfolio"],
      ["strategies.html", "Strategies"],
      ["simulation.html", "Paper trading"],
      ["suggestions.html", "Suggestions"],
      ["questions.html", "Questions"],
      ["verification.html", "Verification"],
      ["flagged.html", "Flagged"],
      ["sources.html", "Sources"],
    ];
    const host = $("#nav");
    if (!host) return;
    host.innerHTML =
      `<a class="brand" href="index.html">Kalshi<b>Dash3</b></a>` +
      items.map(([h, l]) => `<a href="${h}"${h === active ? ' class="on"' : ""}>${l}</a>`).join("");
  }

  return { $, $$, esc, num, money, cents, pct, ago, json, CAT_LABEL, isQaRow, basisBadge, resultBadge, statusBadge, srcLink, table, empty, snapshotBanner, nav, cadence,
    marketIndex, lifecycleOf, lifecycleChip, lifecycleAttach, lifecycleTally, LIFECYCLE_SPEC, LIFECYCLE_TIP };
})();
