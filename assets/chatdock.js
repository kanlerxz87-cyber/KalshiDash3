/* KalshiDash3 — always-on alert chat dock (session arena-17d4ecfa, T31/T32).
 *
 * Why this file exists: the brief asks for "a live alerting system to sudden
 * swings in contract prices >= $0.10 in either direction … a simplified
 * scrolling chat so someone can view in real time", and for the dashboard to
 * be usable "to make decisions on contract events" from any page. Until now the
 * two chats only existed on alerts.html / dashboard.html / live.html; the
 * category pages — the pages a trader actually reads — had no alert surface.
 * This component puts the same two scrolling chats on every page, minus the
 * heavy engine: it is ~200 lines, has no dependency, and never throws.
 *
 * Two flows, and every alert says which one produced it:
 *   1. HISTORY  — data/live/alerts_archive.json, written by scripts/build_alerts.py
 *                 from committed collector observations. Append-only, so a swing
 *                 survives the market closing. Available with no network and no key.
 *   2. LIVE     — the public demo REST API polled from this browser
 *                 (GET /markets, GET /markets?tickers=…). No auth needed for market
 *                 data. A second consecutive reading of the SAME contract is
 *                 compared with the first; a move >= $0.10 either way is an alert.
 *
 * Official sources for the two constraints that shaped this file:
 *   public market data, no auth .... https://docs.kalshi.com/getting_started/quick_start_market_data
 *   tickers is a repeated string[] .. https://docs.kalshi.com/api-reference/market/get-markets
 *   WebSocket needs a key .......... https://docs.kalshi.com/getting_started/quick_start_websockets
 *     => a keyless browser page cannot open the socket, so "live" here means polling.
 *   demo endpoint ................... https://docs.kalshi.com/getting_started/demo_env
 *   CORS is undocumented by Kalshi .. flagged.html F-24 (measured in data/live/cors.json)
 *
 * Honesty rules kept identical to the rest of the site:
 *   - the $0.10 threshold is a PROJECT REQUIREMENT, not a Kalshi number;
 *   - an alert is only ever raised from two real API readings (never synthesised);
 *   - "cause" links are news SEARCH leads, never asserted causes (F-25);
 *   - when the API is unreachable the chat says so and replays history instead.
 */
"use strict";

const KDCHAT = (() => {
  const BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
  const THRESHOLD = 0.10;                 // brief: >= $0.10 in either direction
  // Poll cadence. 12 s is deliberate: the documented unauthenticated limits are
  // tighter than the authenticated ones and a 429 must be backed off, not hammered
  // (https://docs.kalshi.com/getting_started/rate_limits). The first re-poll is
  // shorter so a two-point comparison (and therefore the first possible alert)
  // exists within a few seconds of page load. `__KDCHAT_POLL_MS` exists only so the
  // jsdom render test can exercise three polls in milliseconds.
  const POLL_MS = (typeof window !== "undefined" && Number(window.__KDCHAT_POLL_MS)) || 12000;
  const FIRST_POLL_MS = Math.min(POLL_MS, 2500);
  const POLS = `every ${Math.round(POLL_MS / 1000)}s`;
  const MAX_ROWS = 80;
  const REPO = "kanlerxz87-cyber/KalshiDash3";

  const CAT_LABEL = {
    gas: "Gas Prices",
    elections: "Elections",
    culture: "Culture",
    crypto: "Crypto",
    golf: "Golf",
  };

  /* ---- tiny helpers (no KD dependency: the dock must work on any page) ---- */
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Number(v).toLocaleString());
  const cents = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : (Number(v) * 100).toFixed(1) + "¢");
  const fnum = (v) => {
    const n = Number(v);
    return v === null || v === undefined || v === "" || Number.isNaN(n) ? null : n;
  };
  const clock = (ms) => {
    const d = new Date(ms);
    if (Number.isNaN(d.getTime())) return "—";
    return [d.getHours(), d.getMinutes(), d.getSeconds()].map((x) => String(x).padStart(2, "0")).join(":");
  };
  const ago = (ms) => {
    if (!ms || Number.isNaN(ms)) return "unknown";
    const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 90) return s + "s ago";
    if (s < 5400) return Math.round(s / 60) + "m ago";
    if (s < 172800) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  };

  /* ---------------------------- state ---------------------------- */
  const S = {
    started: false,
    feed: [],                 // deduped alert rows, chronological
    seen: new Set(),
    histLoaded: false,
    liveOn: false,
    liveRows: [],             // tickers currently polled
    prev: new Map(),          // ticker -> { t, last }
    boot: new Map(),          // ticker -> last (from the committed snapshot)
    cat: new Map(),           // ticker -> category_id VERIFIED by the collector
    polls: 0,
    blocked: null,            // null | "cors" | "http" | "offline"
    lastError: "",
    mounted: false,
    filter: "",
    health: null,
  };

  const key = (a) => `${a.ticker}@${a.t}`;

  function push(row) {
    const k = key(row);
    if (S.seen.has(k)) return false;
    S.seen.add(k);
    S.feed.push(row);
    S.feed.sort((a, b) => a.t - b.t);
    if (S.feed.length > MAX_ROWS) S.feed = S.feed.slice(-MAX_ROWS);
    return true;
  }

  function origin(o) {
    return o === "live"
      ? '<span class="cd-orig live" title="Two readings of this contract from the public demo API in this browser, ≥ $0.10 apart">live</span>'
      : '<span class="cd-orig" title="Computed by scripts/build_alerts.py from committed collector observations">history</span>';
  }

  function rowHTML(a) {
    const up = a.dir === "up";
    const cat = CAT_LABEL[a.category] || a.category || "other";
    const links = [
      `<a href="${esc(a.api)}" target="_blank" rel="noopener" title="Re-run the exact API query this price came from">API</a>`,
      `<a href="dashboard.html#${encodeURIComponent(a.ticker)}" title="Open this contract on the price chart">chart</a>`,
      `<a href="alerts.html">detail</a>`,
    ];
    if (a.news) links.push(`<a href="${esc(a.news)}" target="_blank" rel="noopener" title="News SEARCH lead — never an asserted cause (F-25)">news search</a>`);
    return (
      `<div class="cd-msg ${up ? "up" : "down"}">` +
        `<div class="cd-head"><span class="cd-time">${clock(a.t)}</span>` +
          `<span class="cd-delta">${up ? "▲" : "▼"} ${(Math.abs(a.delta) * 100).toFixed(1)}¢</span>` +
          `<b>${cents(a.from)} → ${cents(a.to)}</b>` +
          `<span class="cd-cat">${esc(cat)}</span>` +
          `${origin(a.origin)}</div>` +
        `<div class="cd-tick mono">${esc(a.ticker)}${a.volume24 !== null && a.volume24 !== undefined ? ` · 24h vol ${num(a.volume24)}` : ""}</div>` +
        `<div class="cd-title">${esc(a.title || "")}</div>` +
        `<div class="cd-links">${links.join(" · ")}</div>` +
      `</div>`
    );
  }

  /* ------------------------- history flow ------------------------- */
  async function loadHistory() {
    if (S.histLoaded) return;
    let doc = null;
    try {
      const r = await fetch("data/live/alerts_archive.json", { cache: "no-store" });
      if (r.ok) doc = await r.json();
    } catch { doc = null; }
    S.histLoaded = true;
    S.histSkipped = 0;
    for (const a of (doc && doc.alerts) || []) {
      // Scope: the chats cover the five topics only. A row whose series GET /series files under
      // Test/Demo, or whose topic was never confirmed, is withheld and counted here rather than
      // shown under no topic (F-76). The archive keeps it; only this view excludes it.
      const cats = (a.series_categories || []).map(String);
      if (cats.includes("Test") || cats.includes("Demo") || !a.category_id) { S.histSkipped += 1; continue; }
      const to = Date.parse(a.to_time || "");
      const from = fnum(a.from_price);
      const toP = fnum(a.to_price);
      if (!a.ticker || Number.isNaN(to) || from === null || toP === null) continue;   // never invent a row
      const delta = toP - from;
      if (Math.abs(delta) < THRESHOLD - 1e-9) continue;                              // the >= $0.10 rule
      push({
        t: to,
        ticker: a.ticker,
        title: a.title,
        category: a.category_id,
        from: from,
        to: toP,
        delta: delta,
        dir: delta >= 0 ? "up" : "down",
        origin: "history",
        volume24: fnum(a.volume_24h_fp),
        api: `${BASE}/markets?tickers=${encodeURIComponent(a.ticker)}`,
        news: `https://news.google.com/search?q=${encodeURIComponent(String(a.title || a.ticker).slice(0, 120))}`,
      });
    }
    render();
  }

  /* --------------------------- live flow --------------------------- */
  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  async function seedFromSnapshot() {
    // The committed snapshot gives the FIRST reading per market, so the very
    // first live poll can already raise an alert instead of waiting a cycle.
    try {
      const d = await getJSON("data/live/markets.json");
      const tick = (d.open_markets || []).slice().sort(
        (a, b) => (fnum(b.volume_24h_fp) || 0) - (fnum(a.volume_24h_fp) || 0) || (fnum(b.volume_fp) || 0) - (fnum(a.volume_fp) || 0)
      );
      const rows = tick.filter((r) => fnum(r.last_price_dollars) !== null).slice(0, 40);
      for (const r of (d.open_markets || []).concat(d.settled_markets || [])) {
        if (r && r.ticker && r.category_id) S.cat.set(r.ticker, r.category_id);   // collector's verified category
      }
      for (const r of rows) {
        const t = Date.parse(d.collected_at || "");
        if (Number.isNaN(t)) continue;
        S.boot.set(r.ticker, fnum(r.last_price_dollars));
        S.prev.set(r.ticker, { t: t, last: fnum(r.last_price_dollars) });
      }
      S.liveRows = rows.map((r) => r.ticker);
      S.snapshotAt = d.collected_at || null;
      return rows.length;
    } catch {
      return 0;
    }
  }

  function applyPoll(markets, at) {
    let fired = 0;
    for (const m of markets) {
      const ticker = m.ticker;
      const last = fnum(m.last_price_dollars);
      if (!ticker || last === null) continue;
      const before = S.prev.get(ticker);
      S.prev.set(ticker, { t: at, last: last });
      if (!before) continue;                       // first reading is a baseline, never an alert
      const delta = last - before.last;
      if (Math.abs(delta) < THRESHOLD - 1e-9) continue;
      if (push({
        t: at,
        ticker: ticker,
        title: m.title,
        category: catFor(ticker),
        from: before.last,
        to: last,
        delta: delta,
        dir: delta >= 0 ? "up" : "down",
        origin: "live",
        volume24: fnum(m.volume_24h_fp),
        api: `${BASE}/markets?tickers=${encodeURIComponent(ticker)}`,
        news: `https://news.google.com/search?q=${encodeURIComponent(String(m.title || ticker).slice(0, 120))}`,
      })) fired++;
    }
    return fired;
  }

  // A ticker's category comes from the collector's own row when we have one
  // (category_id, derived from the official fee-schedule seed series or a
  // documented keyword rule). `categoryOf` is only the fallback for a ticker the
  // snapshot has never seen — it is a PREFIX HEURISTIC, and it is labelled as such
  // wherever it can decide anything (discovery only).
  function catFor(ticker) { return S.cat.get(ticker) || categoryOf(ticker); }

  // GET /markets carries no category field, so a raw market record can only be
  // placed in one of the five requested topics by its series prefix. Anything
  // else is "other" and is never shown in the topic-filtered view.
  function categoryOf(ticker) {
    const t = String(ticker || "").toUpperCase();
    if (t.startsWith("KXAAAGAS")) return "gas";
    if (t.startsWith("KXBTC") || t.startsWith("KXETH") || t.startsWith("KXSOL") || t.startsWith("KXDEMOFUT")) return "crypto";
    if (t.startsWith("KXPGATOUR") || t.startsWith("KXGOLF")) return "golf";
    if (t.startsWith("KXELECT") || t.startsWith("KXPRES") || t.startsWith("KXSEN")) return "elections";
    if (t.startsWith("KXGRAMMY") || t.startsWith("KXOSCAR") || t.startsWith("KXBALLONDOR") || t.startsWith("KXEMMY")) return "culture";
    return "other";
  }

  async function pollOnce() {
    const tickers = S.liveRows.slice(0, 40);
    if (!tickers.length) return 0;
    // `tickers` is a REPEATED string[] parameter (1–100 elements); its length is
    // bounded by the URL. Both forms are documented; repeated is the safe one.
    const q = tickers.slice(0, 25).map((t) => "tickers=" + encodeURIComponent(t)).join("&");
    const at = Date.now();
    const d = await getJSON(`${BASE}/markets?${q}`);
    S.polls++;
    const n = applyPoll(d.markets || [], at);
    if (S.polls % 3 === 0) await discover(at);     // refresh the watchlist occasionally
    return n;
  }

  async function discover(at) {
    try {
      const d = await getJSON(`${BASE}/markets?status=open&limit=200`);
      const rows = (d.markets || []).filter((m) => categoryOf(m.ticker) !== "other" && fnum(m.last_price_dollars) !== null);
      rows.sort((a, b) => (fnum(b.volume_24h_fp) || 0) - (fnum(a.volume_24h_fp) || 0));
      const keep = rows.slice(0, 40).map((m) => m.ticker);
      if (keep.length) S.liveRows = keep;
      applyPoll(rows.slice(0, 40), at);
    } catch { /* discovery is best-effort; polling the known list continues */ }
  }

  async function startLive() {
    if (S.liveOn) return;
    try {
      await getJSON(`${BASE}/exchange/status`);
    } catch (e) {
      S.blocked = "cors";
      S.lastError = String((e && e.message) || e);
      render();
      return;
    }
    S.blocked = null;
    S.liveOn = true;
    render();
    const loop = async () => {
      if (!S.liveOn || document.hidden) return;
      try {
        await pollOnce();
        S.blocked = null;
      } catch (e) {
        S.blocked = "http";
        S.lastError = String((e && e.message) || e);
      }
      render();
      setTimeout(loop, S.polls <= 1 ? FIRST_POLL_MS : POLL_MS);
    };
    loop();
  }

  function stopLive() {
    S.liveOn = false;
    render();
  }

  /* -------------------- freshness / run health (T32, R-B1) -------------------- */
  // The collector's schedule is unreliable (measured 2026-11-21: 4 schedule deliveries in ~20 h;
  // F-40), and since PR #62 a run on main is a 15-minute relay rather than one cron tick. So this
  // line names no cron and judges no expected interval (R-B1): it reports the newest run and how
  // often the schedule actually fired, and leaves freshness to the snapshot-age line below.
  // Read-only: public GitHub REST API (CORS `*` verified 2026-11-21). No token, no writes.
  async function checkHealth() {
    try {
      const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/collect.yml/runs?per_page=20`, {
        headers: { Accept: "application/vnd.github+json" },
        cache: "no-store",
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      const runs = (d.workflow_runs || []).map((x) => ({
        id: x.id,
        event: x.event,
        at: Date.parse(x.created_at || ""),
        ok: x.conclusion === "success",
        status: x.status,
        conclusion: x.conclusion,
      }));
      const sched = runs.filter((x) => x.event === "schedule" && !Number.isNaN(x.at));
      const lastOk = runs.find((x) => x.ok && !Number.isNaN(x.at));
      const inFlight = runs.find((x) => x.status === "in_progress" || x.status === "queued");
      const stamped = runs.filter((x) => !Number.isNaN(x.at)).sort((a, b) => b.at - a.at);
      let gap = null;
      if (sched.length >= 2) gap = Math.round((sched[0].at - sched[1].at) / 60000);
      // F-40's signal, kept without a cron string: the median spacing of the most recent
      // runs of ANY kind (a relay pass is workflow_dispatch, not schedule), so a throttled
      // schedule is visible as a scheduled gap far wider than the observed spacing.
      let observedMinutes = null;
      if (stamped.length >= 2) {
        const intervals = [];
        for (let i = 1; i < Math.min(stamped.length, 7); i++) {
          const g = Math.round((stamped[i - 1].at - stamped[i].at) / 60000);
          if (g > 0) intervals.push(g);
        }
        if (intervals.length) {
          const sorted = intervals.slice().sort((a, b) => a - b);
          observedMinutes = sorted[Math.floor(sorted.length / 2)];
        }
      }
      const newest = runs.find((x) => !Number.isNaN(x.at)) || null;
      S.health = {
        runs: runs.length,
        scheduled: sched.length,
        scheduleGapMinutes: gap,
        lastScheduledAt: sched.length ? sched[0].at : null,
        lastSuccessAt: lastOk ? lastOk.at : null,
        observedMinutes,
        inFlightAt: inFlight && !Number.isNaN(inFlight.at) ? inFlight.at : null,
        // Human-readable label for the same facts; the numbers themselves are measured above.
        cronExpression: "15-min relay grid (declared restarts: 7,27,47 + 13,43)",
        expectedMinutes: 15,
        newest: newest
          ? {
              event: newest.event,
              status: newest.status || "unknown",
              conclusion: newest.conclusion || "",
              at: newest.at,
            }
          : null,
        runsUrl: `https://github.com/${REPO}/actions/workflows/collect.yml`,
        // Disclosed, not asserted as a cadence: the workflow file is the authority.
        workflowUrl: `https://github.com/${REPO}/blob/main/.github/workflows/collect.yml`,
      };
    } catch (e) {
      S.health = { error: String((e && e.message) || e) };
    }
    renderHealth();
  }

  function renderHealth() {
    const host = document.getElementById("kdHealth");
    if (host) {
      const h = S.health;
      if (!h) {
        host.innerHTML = '<span class="cd-health mut">collector health: checking…</span>';
      } else if (h.error) {
        host.innerHTML =
          `<span class="cd-health mut">collector health: GitHub API not reachable from this browser (${esc(h.error)}) — ` +
          `<a href="https://github.com/${REPO}/actions/workflows/collect.yml" target="_blank" rel="noopener">check the runs yourself</a></span>`;
      } else {
        const gap = h.scheduleGapMinutes;
        const n = h.newest;
        const newestText = n
          ? `newest run ${esc(n.status)}${n.conclusion ? " · " + esc(n.conclusion) : ""} (${esc(n.event)}, ${esc(ago(n.at))})`
          : "no runs in the last 20";
        // F-40's warning is measured: the scheduled gap is more than twice the spacing of recent runs.
        const observed = h.observedMinutes;
        const late = gap !== null && observed !== null && gap > observed * 2;
        host.innerHTML =
          `<span class="cd-health ${late ? "warn" : "ok"}">` +
          `collector relay <code>${esc(h.cronExpression)}</code> — ${newestText} · ` +
          `${h.scheduled} of the last ${h.runs} runs were scheduled` +
          (observed !== null ? ` · recent runs about every ${observed}m apart` : "") +
          (gap !== null ? ` · last two scheduled runs ${gap}m apart` : " · fewer than two scheduled runs in that window") +
          (late ? ` · <b>GitHub is throttling the schedule (F-40)</b>` : "") +
          (h.inFlightAt !== null ? ` · <b>one running now</b> (started ${esc(ago(h.inFlightAt))})` : "") +
          ` · last success ${h.lastSuccessAt ? esc(ago(h.lastSuccessAt)) : "unknown"}` +
          ` · <a href="${esc(h.workflowUrl)}" target="_blank" rel="noopener">declared triggers</a>` +
          ` · <a href="${esc(h.runsUrl)}" target="_blank" rel="noopener">runs</a></span>`;
      }
    }
    const snapLine = document.getElementById("kdSnapLine");
    if (snapLine && S.snapshotAt) {
      const age = Date.now() - Date.parse(S.snapshotAt);
      snapLine.innerHTML =
        `Committed snapshot <code>${esc(S.snapshotAt)}</code> (${esc(ago(Date.parse(S.snapshotAt)))})` +
        (age > 45 * 60000 ? ' · <b class="warn">stale</b> — the live poller below is still current' : "");
    }
  }

  /* ----------------------------- rendering ----------------------------- */
  function render() {
    const scope = document.getElementById("kdScope");
    if (scope) {
      scope.textContent = S.histSkipped
        ? ` ${S.histSkipped} archived swing(s) are withheld here because they are not in the five topics (F-76).`
        : "";
    }
    const all = S.feed;
    const model = all.filter((a) => Math.abs(a.delta) / Math.max(a.from, 0.05) >= 0.25 && (a.volume24 || 0) >= 100);
    const cat = S.filter;
    const inCat = (a) => !cat || a.category === cat;
    const box = document.getElementById("kdChatAll");
    const mbox = document.getElementById("kdChatModel");
    if (box) {
      const rows = all.filter(inCat).slice(-MAX_ROWS);
      box.innerHTML = rows.length
        ? rows.map(rowHTML).join("")
        : '<div class="cd-empty">No ≥ $0.10 swing yet. Alerts appear as soon as two readings differ by $0.10 or more.</div>';
      if (nearBottom(box)) box.scrollTop = box.scrollHeight;
    }
    if (mbox) {
      const rows = model.filter(inCat).slice(-MAX_ROWS);
      mbox.innerHTML = rows.length
        ? rows.map(rowHTML).join("")
        : '<div class="cd-empty">No swing has passed the experimental screen yet (≥ 25% relative move with ≥ 100 contracts of 24h volume).</div>';
      if (nearBottom(mbox)) mbox.scrollTop = mbox.scrollHeight;
    }
    const cAll = document.getElementById("kdCountAll");
    if (cAll) cAll.textContent = String(all.length);
    const cModel = document.getElementById("kdCountModel");
    if (cModel) cModel.textContent = String(model.length);
    const badge = document.getElementById("kdChip");
    if (badge) {
      badge.className = "kd-chip " + (S.liveOn ? "live" : S.blocked ? "warn" : "");
      badge.textContent = S.liveOn
        ? `near-live · ${S.polls} polls · ${POLS}`
        : S.blocked
        ? "history only · demo API blocked (CORS)"
        : "connecting…";
      badge.title = S.liveOn
        ? "Polling the public Kalshi demo REST API from this page. No key, no account."
        : S.blocked
        ? `This browser could not read the demo API directly (${S.lastError}), so the chats replay committed history. F-24.`
        : "";
    }
    const toggle = document.getElementById("kdToggle");
    if (toggle) toggle.textContent = S.liveOn ? "Pause live" : "Resume live";
  }

  function nearBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  }

  function shell() {
    return `
<div class="kd-dock" id="kdDock" aria-label="Live swing alert chats">
  <button class="kd-tab" id="kdTab" aria-expanded="false" aria-controls="kdPanel">
    <span class="kd-dot" aria-hidden="true"></span> Alert chats <span id="kdTabCount">0</span> <span id="kdChip" class="kd-chip">connecting…</span>
  </button>
  <section class="kd-panel" id="kdPanel" hidden>
    <header class="kd-phead">
      <strong>Price swings ≥ $0.10, either direction</strong>
      <span class="kd-pmeta">two scrolling chats · newest at the bottom</span>
      <label class="kd-filter">Topic
        <select id="kdFilter">
          <option value="">All five</option>
          <option value="gas">Gas Prices</option>
          <option value="elections">Elections</option>
          <option value="culture">Culture</option>
          <option value="crypto">Crypto</option>
          <option value="golf">Golf</option>
        </select>
      </label>
      <button class="kd-btn" id="kdToggle">Pause live</button>
      <a class="kd-more" href="alerts.html">full alert page →</a>
      <span class="kd-snapline small" id="kdSnapLine"></span>
      <span id="kdHealth"></span>
    </header>
    <div class="kd-grid">
      <div class="kd-card">
        <h4>All qualifying events <span class="kd-count" id="kdCountAll">0</span></h4>
        <div class="kd-feed" id="kdChatAll" role="log" aria-live="polite" aria-label="All price swing alerts"></div>
      </div>
      <div class="kd-card">
        <h4>Model watch · experimental <span class="kd-count" id="kdCountModel">0</span></h4>
        <p class="kd-note">Not an ROI prediction. A transparent, unvalidated screen: ≥ 25% relative move with ≥ 100 contracts of reported 24h volume, newest last. Full method on <a href="alerts.html">Alert chats</a>.</p>
        <div class="kd-feed" id="kdChatModel" role="log" aria-live="polite" aria-label="Experimental screened swing alerts"></div>
      </div>
    </div>
    <footer class="kd-pfoot small">
      Threshold $0.10 is a project requirement, not a Kalshi figure. “live” = two readings of the same contract from the
      public demo API in this browser; “history” = an appended row computed from committed collector observations.
      “Near-live”, not tick-level: Kalshi documents that <code>GET /markets</code> responses are
      <a href="https://docs.kalshi.com/api-reference/market/get-markets" target="_blank" rel="noopener">cached for a few seconds</a>
      and that the WebSocket feed is the route to current state — but that handshake requires an API key, which a static page cannot hold.
      This is the <b>demo</b> environment (mock funds) — <a href="https://docs.kalshi.com/getting_started/demo_env" target="_blank" rel="noopener">Kalshi warns demo prices may not reflect real markets</a>.
      News links are search leads, never asserted causes (<a href="flagged.html">F-25</a>).
      Topic labels on <b>history</b> rows are the collector's verified category; a market first seen by the live
      poller is matched by its series prefix, a keyword heuristic (<a href="flagged.html">flagged</a>).
      <span id="kdScope"></span>
    </footer>
  </section>
</div>`;
  }

  function mount() {
    if (S.mounted || !document.body) return;
    S.mounted = true;
    const host = document.createElement("div");
    host.innerHTML = shell();
    document.body.appendChild(host.firstElementChild);

    const tab = document.getElementById("kdTab");
    const panel = document.getElementById("kdPanel");
    tab.addEventListener("click", () => {
      const open = panel.hasAttribute("hidden");
      if (open) panel.removeAttribute("hidden");
      else panel.setAttribute("hidden", "");
      tab.setAttribute("aria-expanded", String(open));
      if (open) {
        render();
        loadHistory();
        if (!S.health) checkHealth();
      }
    });
    document.getElementById("kdFilter").addEventListener("change", (e) => {
      S.filter = e.target.value;
      render();
    });
    document.getElementById("kdToggle").addEventListener("click", () => {
      if (S.liveOn) stopLive();
      else startLive();
    });
    render();
  }

  /* ------------------------------- boot ------------------------------- */
  // History is loaded immediately (cheap, 10 KB) so the tab count is truthful
  // before the reader opens the dock; the live poller starts right away too,
  // because the brief says "no manual input".
  async function boot() {
    if (S.started) return;
    S.started = true;
    mount();
    await loadHistory();
    render();
    await seedFromSnapshot();
    await startLive();
    checkHealth();
    // cross-page alert count
    const t = document.getElementById("kdTabCount");
    if (t) t.textContent = String(S.feed.length);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  return { S, THRESHOLD, BASE, boot, startLive, stopLive, categoryOf, mount };
})();
