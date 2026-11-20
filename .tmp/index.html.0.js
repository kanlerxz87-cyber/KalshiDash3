
KD.nav("");
(async () => {
  let snap = null;
  try { snap = await KD.json("data/live/markets.json"); } catch (e) { snap = null; }
  KD.snapshotBanner(snap);
  const k = KD.$("#kpis");
  if (!snap) {
    k.innerHTML = `<div class="card"><div class="kpi">—<small>awaiting first snapshot</small></div></div>`;
    KD.$("#today").innerHTML = KD.empty("No snapshot yet. See the notice above.");
    return;
  }
  const open = snap.open_markets || [], settled = snap.settled_markets || [];
  const confirmed = open.filter(r => r.category_basis === "seed").length;
  const resolved = settled.filter(r => r.result === "yes" || r.result === "no").length;
  const live = KD.CAT_LABEL;
  k.innerHTML = [
    ["Open markets in scope", KD.num(open.length), "the five requested categories only"],
    ["Confirmed category match", KD.num(confirmed), "series ticker listed in the official fee schedule"],
    ["Resolved yes/no captured", KD.num(resolved), "of " + KD.num(settled.length) + " settled markets in scope"],
    ["Snapshot age", KD.ago(snap.collected_at), "collected " + KD.esc(snap.collected_at || "")],
  ].map(([label, val, sub]) => `<div class="card"><div class="kpi">${val}<small>${label}</small></div><p class="small" style="margin-top:6px">${sub}</p></div>`).join("");

  // Highest dollars-traded estimate per category, 1 row each.
  const top = {};
  for (const r of open) {
    if (r.dollars_traded_estimate === null || r.dollars_traded_estimate === undefined) continue;
    if (!top[r.category_id] || r.dollars_traded_estimate > top[r.category_id].dollars_traded_estimate) top[r.category_id] = r;
  }
  const rows = Object.keys(live).map(id => {
    const r = top[id];
    return {
      cat: live[id],
      title: r ? `<a href="dashboard.html#${KD.esc(r.ticker)}">${KD.esc((r.title || "").replace(/\*\*/g, "").slice(0, 68))}</a>` +
                 `<div class="small mut mono">${KD.esc(r.ticker)}</div>` : '<span class="na">none open in scope</span>',
      dollars: r ? KD.money(r.dollars_traded_estimate, 0) : '<span class="na">—</span>',
      price: r ? KD.cents(r.last_price_dollars) : '<span class="na">—</span>',
      vol: r ? KD.num(r.volume_fp) : '<span class="na">—</span>',
      oi: r ? KD.num(r.open_interest_fp) : '<span class="na">—</span>',
      basis: r ? KD.basisBadge(r.category_basis) : '<span class="na">—</span>',
      src: r ? KD.srcLink(r.source, "API") : '<span class="na">—</span>',
    };
  });
  KD.$("#today").innerHTML = KD.table(
    [{ key: "cat", label: "Category" }, { key: "title", label: "Largest live market" },
     { key: "dollars", label: "Dollars traded (est.)", num: true }, { key: "price", label: "Last price", num: true },
     { key: "vol", label: "Contracts", num: true }, { key: "oi", label: "Open int.", num: true },
     { key: "basis", label: "Category basis" },
     { key: "src", label: "Source" }],
    rows
  ) + `<p class="small mut">“Dollars traded (est.)” = volume × last price, computed by this project.
     Kalshi has no official “dollars traded” field — see
     <a href="questions.html">Q1</a> for why <code>notional_value_dollars</code> is the wrong field for this.
     “Confirmed” means the series ticker appears in the
     <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noopener">official fee schedule</a>;
     “keyword” is a heuristic match and is <a href="flagged.html">flagged</a>.</p>`;
})();
