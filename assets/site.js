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
      .map((r, i) => {
        // data-field lets the live-price updater find a cell without re-rendering the
        // whole table; rowAttr lets a page tag a row with its market ticker.
        const attrs = opts.rowAttr ? " " + opts.rowAttr(r, i) : "";
        return "<tr" + attrs + ">" +
          headers.map((h) => `<td${h.num ? ' class="r"' : ""} data-field="${esc(h.key)}">${r[h.key] ?? ""}</td>`).join("") +
          "</tr>";
      })
      .join("");
    return `<div class="tw"><table><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table></div>`;
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
      `<b>In scope:</b> ${num(meta.counts?.open_in_scope)} open / ${num(meta.counts?.settled_in_scope)} settled` +
      (stale ? ` · <b>Stale fallback:</b> the scheduled collector has not run recently, so these numbers may be out of date.` : "") +
      `</div>`;
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

  /* ------------------------------------------------------------------ *
   * Browser-side live refresh.
   *
   * The committed snapshot (data/live/markets.json) is the fallback that
   * always works. When the browser itself can reach the official demo API
   * (CORS was measured, not assumed — see data/live/cors.json), the page
   * also polls the API directly and updates the live price cells in place.
   * The freshness strip always says which of the two is being shown; the
   * page never claims a price it did not receive.
   * ------------------------------------------------------------------ */

  const LIVE_BASE = "https://external-api.demo.kalshi.co/trade-api/v2";

  function liveStrip() {
    let host = $("#liveStrip");
    if (!host) {
      host = document.createElement("div");
      host.id = "liveStrip";
      host.className = "lives";
      const main = $("main.wrap") || $("main") || $(".top .wrap");
      const h1 = main && main.querySelector("h1");
      if (main && h1) h1.insertAdjacentElement("afterend", host);
      else if (main) main.insertBefore(host, main.firstChild);
      else document.body.insertBefore(host, document.body.firstChild);
    }
    return host;
  }

  function setLiveState(state, detail) {
    const host = liveStrip();
    if (!host) return;
    const cls = state === "live" ? "ok" : state === "stale" ? "warn" : state === "blocked" ? "bad" : "";
    host.className = "lives " + cls;
    host.innerHTML =
      `<span class="dot"></span><b>${esc(state === "live" ? "LIVE" : state === "stale" ? "SNAPSHOT" : state === "blocked" ? "API BLOCKED" : "CHECKING")}</b>` +
      `<span class="mut">${esc(detail || "")}</span>`;
  }

  // Poll the official demo API for the tickers on this page and update the
  // price cells. Only fields the API actually returned are written.
  async function startLiveRefresh(opts = {}) {
    const intervalMs = opts.intervalMs || 20000;
    const base = opts.base || LIVE_BASE;
    let snap = null;
    try { snap = await json("data/live/markets.json"); } catch { snap = null; }
    const tickers = (opts.tickers || []).filter(Boolean);
    if (!tickers.length) { setLiveState("snapshot", "no tickers on this page"); return null; }

    const seen = new Map();
    const stamp = () => new Date().toISOString().replace("T", " ").replace("Z", " UTC");

    async function pull() {
      // GET /markets takes `tickers` as a comma-separated list — see
      // https://docs.kalshi.com/api-reference/market/get-markets
      const chunks = [];
      for (let i = 0; i < tickers.length; i += 60) chunks.push(tickers.slice(i, i + 60));
      let got = 0;
      for (const c of chunks) {
        let d;
        try {
          const r = await fetch(`${base}/markets?tickers=${encodeURIComponent(c.join(","))}`, { cache: "no-store" });
          if (!r.ok) throw new Error("HTTP " + r.status);
          d = await r.json();
        } catch (e) {
          setLiveState("blocked", "browser could not reach the demo API (" + (e.message || e) + ") — showing the committed snapshot");
          return got;
        }
        for (const m of d.markets || []) {
          got++;
          seen.set(m.ticker, m);
          paint(m);
        }
      }
      setLiveState("live", `${got} live quotes · polled ${stamp()}`);
      return got;
    }

    function paint(m) {
      const el = document.querySelector(`[data-live-ticker="${CSS.escape(m.ticker)}"]`);
      if (!el) return;
      for (const td of el.querySelectorAll("td[data-field]")) {
        const f = td.dataset.field;
        let v = null;
        if (f === "last") v = m.last_price_dollars;
        else if (f === "bid") v = m.yes_bid_dollars;
        else if (f === "ask") v = m.yes_ask_dollars;
        else if (f === "vol") v = m.volume_fp;
        else if (f === "oi") v = m.open_interest_fp;
        else if (f === "status") v = null;
        if (v === null || v === undefined) continue;
        td.innerHTML = cents(v);
        td.classList.add("livecell");
      }
    }

    await pull();
    const t = setInterval(pull, intervalMs);
    return { stop: () => clearInterval(t), pull, seen };
  }

  return { $, $$, esc, num, money, cents, pct, ago, json, CAT_LABEL, basisBadge, resultBadge, statusBadge, srcLink, table, empty, snapshotBanner, nav, liveStrip, setLiveState, startLiveRefresh, LIVE_BASE };
})();
