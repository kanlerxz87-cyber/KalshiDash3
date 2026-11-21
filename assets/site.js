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
  const QA_RE = /demo portfolio test|portfolio cash out|\bqa\s*\d/i;
  function isQaRow(r) {
    return !r || QA_RE.test(String((r.title || "") + " " + (r.rules_primary || "")));
  }

  function basisBadge(b) {
    return b === "seed"
      ? '<span class="badge ok" title="Series ticker appears in the official Kalshi fee schedule">confirmed</span>'
      : '<span class="badge warn" title="Matched by keyword heuristic only — not confirmed by an official source">keyword</span>';
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

  return { $, $$, esc, num, money, cents, pct, ago, json, CAT_LABEL, isQaRow, basisBadge, resultBadge, statusBadge, srcLink, table, empty, snapshotBanner, nav, cadence };
})();
