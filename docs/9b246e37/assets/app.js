/* KalshiDash3 — renders tables from data/dashboard.json. No network calls except the local JSON file.
   Blank values are shown as "— unverified" and never filled in. */
(function () {
  const base = document.body.dataset.base || "./";
  const view = document.body.dataset.view;
  const app = document.getElementById("app");

  function el(tag, attrs, children) {
    const n = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === "class") n.className = attrs[k];
      else if (k === "href") n.href = attrs[k];
      else if (k === "title") n.title = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(c => {
      if (c === null || c === undefined || c === false) return;
      n.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return n;
  }
  const blank = () => el("span", { class: "blank", title: "Not confirmed by an official source — left blank" }, ["— unverified"]);
  const cell = (v, cls) => (v === "" || v === null || v === undefined) ? el("td", { class: cls }, [blank()]) : el("td", { class: cls }, [String(v)]);
  const link = (href, text) => el("a", { href, target: "_blank", rel: "noopener" }, [text]);
  const pill = (kind, text) => el("span", { class: "pill " + kind }, [text]);
  const flagsCell = (ids) => el("td", { class: "flags" }, (ids || []).map(id => el("span", {}, [id])));
  const short = (u) => { try { const x = new URL(u); return x.hostname + x.pathname.slice(0, 32) + (x.pathname.length > 32 ? "…" : ""); } catch (e) { return u; } };

  function table(headers, rows, opts) {
    const thead = el("thead", {}, [el("tr", {}, headers.map(h => el("th", { class: h.wrap ? "wrap" : "" }, [h.label])))]);
    const tbody = el("tbody", {}, rows);
    return el("div", { class: "table-wrap" }, [el("table", {}, [thead, tbody])]);
  }

  function setActive() {
    const here = location.pathname.replace(/\/index\.html$/, "/");
    document.querySelectorAll("header.site nav a").forEach(a => {
      const p = new URL(a.href, location.href).pathname.replace(/\/index\.html$/, "/");
      if (p === here) a.classList.add("active");
    });
  }

  function fmtVal(v) { return v === "" || v === undefined ? "" : v; }

  function kpis(data) {
    const topic = data.rows.filter(r => ["gas", "elections", "culture", "crypto", "golf"].includes(r.category));
    const verified = topic.filter(r => r.verification === "verified").length;
    const partial = topic.filter(r => r.verification === "partial").length;
    const card = (k, v, s) => el("div", { class: "card" }, [el("div", { class: "k" }, [k]), el("div", { class: "v" }, [v]), el("div", { class: "s" }, [s])]);
    return el("div", { class: "grid" }, [
      card("Tracked rows", topic.length, "Markets + series in 5 topics"),
      card("Verified rows", verified, "All shown fields come from the API"),
      card("Partial rows", partial, "Some fields blank (unverified)"),
      card("Resolved examples", data.resolved.length, "Demo test markets only"),
      card("Open flags", data.flags.length, "See Flagged for Review"),
      card("AAA national avg (regular)", "$" + data.aaa.current, "As of " + data.aaa.as_of + " · AAA"),
    ]);
  }

  const CATS = [
    { id: "gas", label: "Gas prices", href: "categories/gas.html" },
    { id: "elections", label: "Elections", href: "categories/elections.html" },
    { id: "culture", label: "Culture", href: "categories/culture.html" },
    { id: "crypto", label: "Crypto", href: "categories/crypto.html" },
    { id: "golf", label: "Golf", href: "categories/golf.html" },
  ];

  function categoryCards(data) {
    return el("div", { class: "grid" }, CATS.map(c => {
      const rs = data.rows.filter(r => r.category === c.id);
      const vol = rs.reduce((s, r) => s + (parseFloat(r.volume) || 0), 0);
      return el("a", { class: "card", href: base + c.href, style: "text-decoration:none;color:inherit" }, [
        el("div", { class: "k" }, [c.label]),
        el("div", { class: "v" }, [rs.length + " rows"]),
        el("div", { class: "s" }, [vol ? "Known volume: " + vol.toLocaleString("en-US") + " contracts (partial)" : "Known volume: see table"]),
      ]);
    }));
  }

  function renderOverview(data) {
    app.append(
      el("h1", {}, ["Kalshi demo dashboard — overview"]),
      el("p", { class: "lead" }, ["Snapshot of Kalshi's DEMO exchange taken " + data.meta.snapshot_window_utc + " UTC. Five topics: gas prices, elections, culture, crypto, golf. Every value links to its source. Blanks are unverified."]),
      el("div", { class: "notice warn" }, [el("strong", {}, ["Demo prices are not real-market prices. "]), "Kalshi says demo markets 'may not be reflective of those in real markets' (", link(data.urls.docs_demo_env, "docs"), "). Do not use these numbers for real decisions."]),
      kpis(data),
      el("h2", {}, ["Categories"]),
      categoryCards(data),
      el("h2", {}, ["Executive summary"]),
      el("div", { class: "card" }, [
        el("ul", {}, [
          el("li", {}, ["The DEMO exchange is active (", link(data.exchange.source_url, "exchange status"), "). Trading and portfolio access need a demo API key, which this sandbox does not have. No trades were placed."]),
          el("li", {}, ["Gas markets settle on AAA's national average for regular gas. AAA's national average is $3.6898 as of 11/20/26 (", link(data.aaa.source_url, "AAA"), "). The demo ladder for Nov 30, 2026 spans $2.50–$3.60 strikes; quotes are thin, and the '$3.50' rung is the only one in the sample with a non-trivial bid and ask (0.50 / 0.51)."]),
          el("li", {}, ["Crypto has the most contracts traded at series level (LINK 24.5M, BTC 19.5M, AVAX 17.5M, per the API), but volume is contracts, not dollars (F-11)."]),
          el("li", {}, ["Elections, culture, and golf show little or no volume in the snapshot. Culture settlement sources are irregular (F-05)."]),
          el("li", {}, ["Only demo test markets have resolved in the sample. Their yes/no results are shown as examples, not as real outcomes (F-02)."]),
          el("li", {}, ["Questions that must be answered before decisions: see the Questions page. Improvements are on the Suggestions page for your choice; nothing has been implemented from them."]),
        ]),
      ]),
    );
  }

  function categoryTable(data, catId) {
    const rows = data.rows.filter(r => r.category === catId);
    const sorted = catId === "gas" ? rows : rows.slice().sort((a, b) => (parseFloat(b.volume) || 0) - (parseFloat(a.volume) || 0));
    const headers = [
      { label: "Ticker" }, { label: "Type" }, { label: "Title", wrap: true }, { label: "Status" }, { label: "Last price ($)" },
      { label: "Yes bid" }, { label: "Yes ask" }, { label: "Open interest" }, { label: "Volume (contracts)" },
      { label: "Close time (UTC)" }, { label: "Result" }, { label: "Frequency" }, { label: "Settlement source", wrap: true },
      { label: "Terms PDF" }, { label: "Last updated" }, { label: "Verification" }, { label: "Flags" }, { label: "Source (official)" },
    ];
    const body = sorted.map(r => el("tr", {}, [
      el("td", {}, [r.ticker]),
      el("td", {}, [r.type]),
      el("td", { class: "wrap" }, [r.title]),
      el("td", {}, [r.status]),
      cell(r.last_price, "num"),
      cell(r.yes_bid, "num"), cell(r.yes_ask, "num"),
      cell(r.open_interest, "num"),
      cell(r.volume ? Number(r.volume).toLocaleString("en-US") : "", "num"),
      cell(r.close_time), cell(r.result || "pending"), cell(r.frequency), el("td", { class: "wrap" }, [r.settlement_source || ""].map(x => x || blank())),
      r.terms_url ? el("td", {}, [link(r.terms_url, "PDF")]) : el("td", {}, [blank()]),
      cell(r.last_updated),
      el("td", {}, [pill(r.verification === "verified" ? "verified" : "partial", r.verification)]),
      flagsCell(r.flags),
      el("td", {}, [link(r.source_url, "API ↗")]),
    ]));
    return table(headers, body);
  }

  function renderCategory(data, catId) {
    const meta = CATS.find(c => c.id === catId);
    const rows = data.rows.filter(r => r.category === catId);
    const notes = {
      gas: "Each rung asks whether AAA's national average for regular gas is strictly above the strike on the stated date. Settlement source: AAA. Sorted by strike (ascending).",
      elections: "Series-level totals (not event-level). Election coverage is partial: the Elections list has 529 result pages (F-09, F-17).",
      culture: "Both culture series have 0.00 volume in the snapshot. Settlement-source lists contain placeholders; manual review is required (F-05).",
      crypto: "Series-level volumes are contract counts, not dollars (F-11). Sorted by volume (descending). Index-based contracts settle on CF Benchmarks.",
      golf: "Only one golf series and one related market were found. Coverage is thin (F-15).",
    };
    app.append(
      el("p", { class: "lead" }, [el("a", { href: base + "index.html" }, ["← Overview"]), "  ·  ", el("strong", {}, [meta.label])]),
      el("h1", {}, [meta.label + " — Kalshi demo markets"]),
      el("p", { class: "lead" }, [notes[catId]]),
      el("div", { class: "notice warn" }, ["Demo data — not production (F-01). " + rows.length + " row(s) in this snapshot. Blank cells are unverified and were not filled in."]),
    );
    if (catId === "gas") {
      const a = data.aaa;
      app.append(el("div", { class: "card" }, [
        el("strong", {}, ["AAA national average, regular (settlement reference)"]),
        el("div", {}, ["Today (" + a.as_of + "): $" + a.current + " · Yesterday: $" + a.yesterday + " · Week ago: $" + a.week_ago + " · Month ago: $" + a.month_ago + " · Year ago: $" + a.year_ago]),
        el("div", { class: "s" }, ["Highest recorded regular (AAA table): " + a.highest_recorded_regular + " · Source: ", link(a.source_url, "gasprices.aaa.com"), " · Verified 2026-11-20 ~11:10 UTC"]),
      ]));
    }
    app.append(el("h2", {}, ["Table (" + rows.length + " rows)"]), categoryTable(data, catId));
    app.append(el("h2", {}, ["Analysis"]), analysisFor(data, catId));
  }

  function analysisFor(data, catId) {
    const items = {
      gas: [
        "AAA's national regular average fell from $4.2786 (month ago) to $3.6898 (today) per AAA's table. Market rungs run from $2.50 to $3.60 in the snapshot.",
        "Quotes are one-sided at $2.50–$2.90 (last 0.01, yes bid 0.00, yes ask 1.00) and $3.00–$3.40 (last 0.97–0.98). The $3.50 rung has a non-trivial top of book (bid 0.50 × 103.81, ask 0.51 × 97.27) and the largest volume in the set (6,828 contracts).",
        "Why the demo quote for $3.50 is 0.50 while AAA's average is above $3.50 is not explained by the data. Open question Q-05; no conclusion is drawn (F-10).",
      ],
      elections: [
        "Four series, 41 contracts total across all four (sum of the snapshot values). Activity is too thin for price-based analysis.",
        "Settlement sources are named as many news outlets rather than one official body, which may make resolution harder to verify (Q-12).",
      ],
      culture: [
        "Both series show 0.00 volume. There is no price or liquidity signal.",
        "Settlement-source lists include placeholders and unrelated outlets (F-05). Treat these as unverified until the rulebook is reviewed.",
      ],
      crypto: [
        "Largest series by contracts traded: KXLINK (24,510,512), KXBTCMINY (19,464,180), KXAVAX (17,532,299). Series totals only; no per-market prices were captured.",
        "Several series are at 0 or near 0 volume (KXNEAR, KXFDVFOGO, KXDOGEPERP). KXDOGEPERP has no settlement source (F-08).",
      ],
      golf: [
        "PGA Major Wins (KXPGAMAJOR) has 0.00 volume. The one market captured (Bryson DeChambeau, 1+ majors in 2027) has no quotes or volume.",
        "No live tournament market was found. Golf coverage is a gap (F-15).",
      ],
    };
    return el("ul", {}, (items[catId] || []).map(t => el("li", {}, [t])));
  }

  function renderPortfolio(data) {
    app.append(
      el("h1", {}, ["Portfolio, trades & strategies"]),
      el("div", { class: "notice bad" }, [el("strong", {}, ["Status: BLOCKED — no demo API key. "]), "Portfolio, balance, order, and fill data require signed requests (", link(data.urls.docs_auth, "authentication docs"), "). No demo account credentials exist in this sandbox, and the agent cannot create one. No trades were placed, and no P&L is shown. Provide a demo key (suggestion S-02) to unblock."]),
      el("h2", {}, ["Portfolio (demo account)"]),
      table([{ label: "Metric" }, { label: "Value" }, { label: "Source" }, { label: "Status" }], [
        el("tr", {}, [el("td", {}, ["Balance"]), cell(""), el("td", {}, [blank()]), el("td", {}, [pill("blocked", "blocked")])]),
        el("tr", {}, [el("td", {}, ["Open positions"]), cell(""), el("td", {}, [blank()]), el("td", {}, [pill("blocked", "blocked")])]),
        el("tr", {}, [el("td", {}, ["Realized P&L"]), cell(""), el("td", {}, [blank()]), el("td", {}, [pill("blocked", "blocked")])]),
        el("tr", {}, [el("td", {}, ["Trades placed"]), el("td", { class: "num" }, ["0"]), el("td", {}, [link(data.urls.docs_auth, "no trades placed (see auth docs)")]), el("td", {}, [pill("verified", "verified")])]),
      ]),
      el("h2", {}, ["Trade categories and strategies"]),
      el("p", { class: "lead" }, ["Trades have not been placed, so no strategy can be measured. The categories below are the planned structure, not findings. Each will be filled from the demo account only after trades exist (S-07)."]),
      table([{ label: "Trade category" }, { label: "Definition" }, { label: "Trades" }, { label: "Result" }], [
        el("tr", {}, [el("td", {}, ["Directional"]), el("td", { class: "wrap" }, ["Buy YES or NO on a view of the outcome"]), el("td", { class: "num" }, ["0"]), cell("")]),
        el("tr", {}, [el("td", {}, ["Range / threshold"]), el("td", { class: "wrap" }, ["Ladder rungs (e.g. gas above $X)"]), el("td", { class: "num" }, ["0"]), cell("")]),
        el("tr", {}, [el("td", {}, ["Hedge / pair"]), el("td", { class: "wrap" }, ["Offsetting positions across related markets"]), el("td", { class: "num" }, ["0"]), cell("")]),
      ]),
    );
  }

  function renderAnalysis(data) {
    const res = data.resolved.map(r => el("tr", {}, [
      el("td", {}, [r.ticker]), el("td", { class: "wrap" }, [r.title]),
      el("td", {}, [pill(r.result === "yes" ? "verified" : "partial", r.result.toUpperCase())]),
      cell(r.settlement_value_dollars, "num"), cell(r.last_price_dollars, "num"),
      el("td", { class: "num" }, [Number(r.volume).toLocaleString("en-US")]),
      cell(r.settlement_ts), el("td", {}, [link(r.source_url, "API ↗")]), el("td", {}, [pill("partial", "demo test")]),
    ]));
    app.append(
      el("h1", {}, ["Analysis & findings"]),
      el("p", { class: "lead" }, ["Findings from the snapshot. Each one points back to the table or source it came from. Nothing here is a trading recommendation."]),
      el("h2", {}, ["How events resolved (YES or NO)"]),
      el("p", {}, ["Settled markets report result 'yes' or 'no' with status 'finalized'. Only demo test markets have resolved in this sample. No real market from the five topics has resolved in the snapshot, so resolution tracking has no real data yet (Q-04)."]),
      table([{ label: "Ticker" }, { label: "Title", wrap: true }, { label: "Result" }, { label: "Settlement value ($)" }, { label: "Last price ($)" }, { label: "Volume (contracts)" }, { label: "Settlement time (UTC)" }, { label: "Source" }, { label: "Type" }], res),
      el("h2", {}, ["Findings by category"]),
      ...["gas", "crypto", "elections", "culture", "golf"].map(c => el("div", { class: "card", style: "margin:10px 0" }, [el("strong", {}, [c.toUpperCase()]), analysisFor(data, c)])),
      el("h2", {}, ["Strategy analysis"]),
      el("div", { class: "notice info" }, ["No strategies can be evaluated yet. There are no placed trades, so there are no results by trade type. See Portfolio and Questions Q-03 and Q-11."]),
      el("h2", {}, ["Reference: AAA gas average (regular)"]),
      el("p", {}, ["Today $" + data.aaa.current + " (" + data.aaa.as_of + ") · Source: ", link(data.aaa.source_url, "AAA national average"), "."]),
    );
  }

  function renderQuestions(data) {
    const statusPill = s => pill(s === "Answered" ? "answered" : s === "Partly answered" ? "partly" : "unanswered", s);
    app.append(
      el("h1", {}, ["Questions, answers & information gaps"]),
      el("p", { class: "lead" }, ["Questions that must be answered before a decision can be made. Each row says what is known, what is missing, and how to find it."]),
      table([{ label: "ID" }, { label: "Question", wrap: true }, { label: "Status" }, { label: "Answer (from sources)", wrap: true }, { label: "Missing information", wrap: true }, { label: "How to discover", wrap: true }, { label: "Source" }],
        data.questions.map(q => el("tr", {}, [
          el("td", {}, [q.id]), el("td", { class: "wrap" }, [q.question]), el("td", {}, [statusPill(q.status)]),
          el("td", { class: "wrap" }, [q.answer]), el("td", { class: "wrap" }, [q.missing_info]), el("td", { class: "wrap" }, [q.how_to_discover]),
          el("td", {}, [link(q.source_url, "source ↗")]),
        ]))),
    );
  }

  function renderSuggestions(data) {
    const KEY = "kalshidash3-shortlist";
    let saved = []; try { saved = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { saved = []; }
    const box = el("div", { class: "notice info" }, [
      el("strong", {}, ["Nothing here is implemented. "]),
      "Tick the suggestions you want, then tell the agent which IDs to implement (e.g. 'S-01, S-03'). Ticks save only in this browser; they do not change the site or the repo.",
    ]);
    app.append(
      el("h1", {}, ["Suggestions — choose the best path"]),
      el("p", { class: "lead" }, ["Ways to improve decision-making and data quality. Review each one and pick. No changes are made until you choose."]),
      box,
      ...data.suggestions.map(s => {
        const cb = el("input", { type: "checkbox", "data-id": s.id });
        cb.checked = saved.includes(s.id);
        cb.addEventListener("change", () => {
          const cur = new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
          cb.checked ? cur.add(s.id) : cur.delete(s.id);
          localStorage.setItem(KEY, JSON.stringify([...cur]));
        });
        return el("div", { class: "suggest" }, [
          el("h3", {}, [s.id + " · " + s.title]),
          el("div", {}, [s.detail]),
          el("div", { class: "meta" }, ["Benefit: " + s.benefit + " · Cost: " + s.cost + (s.risk ? " · Risk: " + s.risk : "")]),
          el("label", {}, [cb, "Shortlist this suggestion"]),
        ]);
      }),
    );
  }

  function renderFlagged(data) {
    app.append(
      el("h1", {}, ["Flagged for Review"]),
      el("p", { class: "lead" }, ["Irregularities, unverified items, and open issues. Flagged items do not block publication. Each one links to its source so you can review and request changes."]),
      table([{ label: "ID" }, { label: "Severity" }, { label: "Issue", wrap: true }, { label: "Detail", wrap: true }, { label: "Source to review" }],
        data.flags.map(f => el("tr", {}, [
          el("td", {}, [f.id]), el("td", {}, [pill(f.severity, f.severity)]),
          el("td", { class: "wrap" }, [f.title]), el("td", { class: "wrap" }, [f.detail]),
          el("td", {}, [link(f.source_url, "open ↗")]),
        ]))),
      el("h2", {}, ["Unverified rows"]),
      el("p", {}, ["Rows with any blank or partial field: " + data.rows.filter(r => r.verification !== "verified").map(r => r.ticker).join(", ") + "."]),
    );
  }

  function renderSources(data) {
    const u = data.urls;
    const list = [
      ["Kalshi API docs — index (llms.txt)", u.docs_llms],
      ["Kalshi API docs — Welcome", u.docs_welcome],
      ["Kalshi demo environment", u.docs_demo_env],
      ["Authenticated requests (signing)", u.docs_auth],
      ["Market settlement", u.docs_settlement],
      ["Series list endpoint (category filter, volume definition)", u.docs_series_list],
      ["Candlesticks endpoint (fields, limits)", u.docs_candlesticks],
      ["Orderbook endpoint (YES/NO representation)", u.docs_orderbook],
      ["Demo: exchange status", u.exchange_status],
      ["Demo: series — Crypto", u.series_crypto],
      ["Demo: series — Elections", u.series_elections],
      ["Demo: series — Culture", u.series_culture],
      ["Demo: series — Sports (includes golf)", u.series_sports_golf],
      ["Demo: events — KXAAAGASM (gas ladder)", u.gas_events],
      ["Demo: events — KXPGAMAJOR (golf)", u.golf_events],
      ["Demo: settled markets (resolution examples)", u.settled_markets],
      ["AAA national average (settlement reference)", u.aaa_national],
    ];
    app.append(
      el("h1", {}, ["Sources & verification log"]),
      el("p", { class: "lead" }, ["Every number on this site came from one of these pages, retrieved on 2026-11-20 (UTC). If a page changes, the value may change. Re-check before relying on it."]),
      table([{ label: "Source" }, { label: "Link (official)", wrap: true }], list.map(([a, b]) => el("tr", {}, [el("td", { class: "wrap" }, [a]), el("td", {}, [link(b, short(b))])]))),
      el("h2", {}, ["Verification performed"]),
      el("ul", {}, [
        el("li", {}, ["Demo API responses were copied field by field; fields missing from the response (e.g. truncated) were left blank."]),
        el("li", {}, ["Settlement and resolution rules were quoted from the rules_primary fields returned by the API."]),
        el("li", {}, ["AAA values were read from gasprices.aaa.com on 2026-11-20 (Current Avg $3.6898, 11/20/26)."]),
        el("li", {}, ["Sandbox curl to the demo host failed (SSL error), so every Kalshi value was taken from fetch results, not a direct connection."]),
        el("li", {}, ["The exchange status, candlestick, and orderbook responses were checked against the documented schemas."]),
      ]),
      el("h2", {}, ["Not verified (listed for review)"]),
      el("ul", {}, [
        el("li", {}, ["Production (non-demo) prices — not retrieved."]),
        el("li", {}, ["Full category enumeration — not done (F-17)."]),
        el("li", {}, ["Kalshi fee schedule PDF — referenced in docs, not opened."]),
        el("li", {}, ["Browser access (CORS) from GitHub Pages to the demo API — not tested (F-16)."]),
      ]),
    );
  }

  const views = {
    overview: renderOverview,
    portfolio: renderPortfolio,
    analysis: renderAnalysis,
    questions: renderQuestions,
    suggestions: renderSuggestions,
    flagged: renderFlagged,
    sources: renderSources,
  };

  setActive();
  if (!app) return;
  fetch(base + "data/dashboard.json", { cache: "no-store" })
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(data => {
      if (view && view.startsWith("cat:")) renderCategory(data, view.slice(4));
      else if (views[view]) views[view](data);
      else app.append(el("p", {}, ["Unknown view."]));
    })
    .catch(err => {
      app.append(el("div", { class: "notice bad" }, ["Could not load data/dashboard.json: " + err.message]));
    });
})();
