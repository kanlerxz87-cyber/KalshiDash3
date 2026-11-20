
KD.nav("");
(function ensureNav(){const h=KD.$("#nav");if(!h)return;
 for(const[href,label]of[["live.html","Live Desk"],["roi.html","ROI Model"]]){
  if(!h.querySelector(`a[href="${href}"]`)){const a=document.createElement("a");a.href=href;a.textContent=label;
   if(href===location.pathname.split("/").pop())a.className="on";h.appendChild(a);} } })();

const CATS = { gas:"Gas Prices", elections:"Elections", culture:"Culture", crypto:"Crypto", golf:"Golf" };
const num = (v,d=2)=> (v===null||v===undefined||Number.isNaN(Number(v))) ? '<span class="na" title="not returned by the API — left blank, not guessed">—</span>' : Number(v).toFixed(d);

function paramTable(model){
  const rows=[];
  const w=model.parameters.weights;
  rows.push(["fair estimate q","mid, microprice, last blended",""+`q = ${w.mid}·mid + ${w.micro}·micro + ${w.last}·last, then a momentum tilt, then clipped to [${model.parameters.clip_q[0]}, ${model.parameters.clip_q[1]}]`,"https://docs.kalshi.com/api-reference/market/get-markets","market price fields"]);
  if(model.parameters.trend) rows.push(["momentum tilt","this project's tick history",`tilt = ${model.parameters.trend.weight_dollars} × clip(momentum / ${model.parameters.trend.reference_move_dollars}, −1, 1) — a ${model.parameters.trend.reference_move_dollars} move shifts q by at most ${model.parameters.trend.weight_dollars}`,"https://docs.kalshi.com/api-reference/market/get-market-candlesticks","candles offer 1/60/1440 min only, so sub-minute momentum needs its own log"]);
  const f=model.parameters.filters;
  rows.push(["swing threshold","project rule",`±$${model.swing_alert.threshold_dollars} between consecutive observations, either direction`,"","brief requirement, stored in the model file so it is not buried in code"]);
  rows.push(["max spread","",`${(f.max_spread*100).toFixed(0)}¢`,"https://docs.kalshi.com/getting_started/orderbook_responses","spread is derived: best YES ask = 1 − best NO bid"]);
  rows.push(["min depth at touch","",`${f.min_depth_contracts} contracts (skipped, not zeroed, when the source carries no book)`,"https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks","1–100 tickers per request"]);
  rows.push(["min 24h volume","",`${f.min_volume_24h_contracts} contracts`,"https://docs.kalshi.com/api-reference/market/get-markets","volume_24h_fp is a contract count"]);
  rows.push(["entry price band","",`$${f.min_entry_price.toFixed(2)} – $${f.max_entry_price.toFixed(2)}`,"","avoids the extremes where one cent of rounding dominates"]);
  rows.push(["time to resolution","",`${f.min_ttc_hours} h – ${f.max_ttc_hours} h`,"https://docs.kalshi.com/getting_started/market_lifecycle","close_time is the API field"]);
  rows.push(["topic confirmation","",f.require_seed_category?"only markets whose series ticker is in the fee schedule":"all five topics, keyword matches included","https://kalshi.com/docs/kalshi-fee-schedule.pdf","this is why a keyword match is never presented as confirmed"]);
  rows.push(["ranking","",`net ROI = (q − cost) / cost, cost = entry price + unit taker fee; keep top ${model.scoring.top_k}`,"","ROI, not cents of edge, because the brief asked for return on investment"]);
  return KD.table([{key:"k",label:"Parameter"},{key:"src",label:"Where it comes from"},{key:"v",label:"Value in force"},{key:"doc",label:"Official source"},{key:"note",label:"Why"}],
    rows.map(r=>({k:`<b>${r[0]}</b>`,src:r[1]?`<span class="mut">${r[1]}</span>`:'<span class="mut">this project</span>',v:`<span class="mono">${r[2]}</span>`,
      doc:r[3]?`<a href="${r[3]}" target="_blank" rel="noopener">docs</a>`:'<span class="na">no official source — project rule</span>',note:`<span class="small mut">${r[4]}</span>`})));
}

function feeTable(model){
  const t=(model.fees.series_multipliers||{}).table||{};
  const rows=Object.entries(t).map(([s,v])=>({s:`<code>${KD.esc(s)}</code>`,
    d:KD.esc(v.description_in_pdf||""),
    mk:v.maker===0?'<span class="badge">0 (no maker fee)</span>':`<span class="mono">${v.maker}</span>`,
    tk:v.taker===0?'<span class="badge">0 (no taker fee)</span>':`<span class="mono">${v.taker}</span>`,
    src:'<a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noopener">schedule</a>'}));
  return KD.table([{key:"s",label:"Series (only those this project can put in scope)"},{key:"d",label:"Description as printed"},
    {key:"mk",label:"Maker multiplier",num:true},{key:"tk",label:"Taker multiplier",num:true},{key:"src",label:"Source"}],rows,
    {empty:"none transcribed"}) +
    `<p class="small mut">Defaults for any series not in that table: taker multiplier ${model.fees.defaults.M_taker}, maker ${model.fees.defaults.M_maker}.
     The schedule does not publish a machine-readable full list, so unlisted series are treated as general <b>and labelled unlisted</b> in every
     pick row (<code>fee_multiplier.listed</code>) rather than assumed to be zero-fee.</p>`;
}

function picksTable(rows, label){
  if(!rows||!rows.length) return `<div class="card"><p class="empty">${label}</p></div>`;
  return KD.table([
    {key:"m",label:"Market"},{key:"cat",label:"Topic"},
    {key:"q",label:"model q",num:true},{key:"mid",label:"mid",num:true},{key:"micro",label:"micro",num:true},{key:"last",label:"last",num:true},
    {key:"spr",label:"spread",num:true},{key:"dep",label:"depth",num:true},{key:"side",label:"side"},
    {key:"entry",label:"entry",num:true},{key:"fee",label:"fee/c",num:true},{key:"cost",label:"cost",num:true},
    {key:"edge",label:"edge",num:true},{key:"roi",label:"net ROI",num:true},{key:"ttc",label:"to close",num:true},
    {key:"why",label:"gates"},{key:"src",label:"source"},
  ], rows.map(p=>({
    m:`<a href="live.html#${encodeURIComponent(p.ticker)}">${KD.esc((p.title||p.ticker).replace(/\*\*/g,"").slice(0,58))}</a><div class="small mut mono">${KD.esc(p.ticker)}</div>`,
    cat:`${CATS[p.category_id]||"—"} ${KD.basisBadge(p.category_basis)}`,
    q:num(p.q,4), mid:num(p.mid,4), micro:p.micro===null||p.micro===undefined?'<span class="na">—</span>':num(p.micro,4),
    last:num(p.last,4), spr:p.spread===null||p.spread===undefined?'<span class="na">—</span>':(p.spread*100).toFixed(1)+"¢",
    dep:p.depth===null||p.depth===undefined?'<span class="na">no book</span>':KD.num(p.depth),
    side:p.entry?`<b>${p.entry.side}</b>`:'<span class="na">—</span>',
    entry:p.entry?KD.cents(p.entry.entry):'<span class="na">—</span>',
    fee:p.entry?num(p.entry.fee_unit*100,3):'<span class="na">—</span>',
    cost:p.entry?num(p.entry.cost,4):'<span class="na">—</span>',
    edge:p.entry?((p.entry.ev>=0?"+":"")+(p.entry.ev*100).toFixed(2)+"¢"):'<span class="na">—</span>',
    roi:p.score===null||p.score===undefined?'<span class="na">—</span>':`<b>${(p.score*100).toFixed(2)}%</b>`,
    ttc:p.ttc_hours===null||p.ttc_hours===undefined?'<span class="na">—</span>':p.ttc_hours.toFixed(1)+" h",
    why:(p.eligible?'<span class="badge ok">all gates pass</span>':`<span class="badge warn">${KD.esc((p.fails||p.reasons||[""])[0]||"gated")}</span>`)+
        (p.reasons&&p.reasons.length?`<div class="small mut">${KD.esc(p.reasons.join(" · "))}</div>`:"")+
        (p.fee_multiplier&&!p.fee_multiplier.listed?'<div class="small mut">fee multiplier: general default (series not listed in the schedule)</div>':""),
    src:KD.srcLink(p.source,"API"),
  })),{empty:"—"});
}

function validationBlock(v){
  if(!v||!Object.keys(v).length) return `<div class="card"><p class="empty">No measurement committed yet.</p></div>`;
  const k=[["markets replayed",KD.num(v.markets_tested)],["candles read",KD.num(v.candles_used)],
    ["signals",KD.num(v.signals)],["hits",KD.num(v.hits)],["misses",KD.num(v.misses)],
    ["hit rate",v.hit_rate===null||v.hit_rate===undefined?"—":(v.hit_rate*100).toFixed(1)+"%"],
    ["baseline: always buy YES",v.baseline_always_yes_hit_rate===null||v.baseline_always_yes_hit_rate===undefined?"—":(v.baseline_always_yes_hit_rate*100).toFixed(1)+"%"],
    ["mean net ROI",v.mean_net_roi===undefined?"—":(v.mean_net_roi*100).toFixed(2)+"%"],
    ["median net ROI",v.median_net_roi===undefined?"—":(v.median_net_roi*100).toFixed(2)+"%"],
    ["P&L per 100 contracts",v.pnl_per_100_contracts===undefined?"—":"$"+Number(v.pnl_per_100_contracts).toFixed(2)]];
  const skipped=Object.entries(v.skipped||{});
  return `<div class="kpirow">`+k.map(([l,val])=>`<div class="card"><div class="l">${l}</div><div class="v">${val}</div></div>`).join("")+`</div>`+
    `<p class="small mut">Rows that could not be replayed, and why: ${skipped.length?skipped.map(([r,n])=>`<code>${KD.esc(r)}</code> ×${n}`).join(" · "):"none skipped"}.</p>`;
}

(async function(){
  let model=null, scan=null;
  try{ model=await KD.json("data/roi_model.json"); }catch(e){}
  try{ scan=await KD.json("data/live/roi.json"); }catch(e){}
  if(!model){
    KD.$("#params").innerHTML=KD.empty("data/roi_model.json could not be read, so no parameter is displayed. Nothing is filled in from memory.");
    KD.$("#formula").textContent="unavailable";
    return;
  }
  const p=model.parameters,f=p.filters;
  KD.$("#formula").textContent =
`q      = ${model.parameters.weights.mid}·mid + ${model.parameters.weights.micro}·micro + ${model.parameters.weights.last}·last
         + ${p.trend.weight_dollars}·clip(momentum/${p.trend.reference_move_dollars})      → clipped to [${p.clip_q[0]}, ${p.clip_q[1]}]
micro  = (bid·size_at_ask + ask·size_at_bid) / (size_at_ask + size_at_bid)
yes: cost = ask + (${model.fees.defaults.M_taker}·0.07·ask·(1−ask))       ev = q − cost            roi = ev / cost
no:  cost = (1−bid) + (0.07·(1−bid)·bid)                            ev = 1 − q − cost        roi = ev / cost
fee  = roundup(M × 0.07 × C × P × (1 − P))   (general taker; maker 0.0175; M per series below)
gate = spread ≤ ${(f.max_spread*100).toFixed(0)}¢ · depth ≥ ${f.min_depth_contracts} · vol24h ≥ ${f.min_volume_24h_contracts} · entry $${f.min_entry_price}–$${f.max_entry_price} · ${f.min_ttc_hours} h ≤ ttc ≤ ${f.max_ttc_hours} h${f.require_seed_category?" · fee-schedule-confirmed topic only":""} · roi > ${(f.min_net_roi*100).toFixed(0)}%
alert = |Δlast between consecutive observations| ≥ $${model.swing_alert.threshold_dollars}`;
  KD.$("#formulaNote").innerHTML =
    `The <code>micro</code> line is this project's definition of a depth-weighted mid; the price and size inputs are
     official API fields (<a href="https://docs.kalshi.com/getting_started/orderbook_responses" target="_blank" rel="noopener">order-book responses</a>).
     The fee line is quoted from the
     <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noopener">published schedule</a>.
     Settle-out is $1 to the winning side, $0 to the other
     (<a href="https://docs.kalshi.com/getting_started/market_settlement" target="_blank" rel="noopener">settlement</a>).`;
  KD.$("#paramStamp").innerHTML = `model id <code>${KD.esc(model.id)}</code> · schema ${model.schema} · owner session <code>${KD.esc(model.owner_session||"—")}</code>`+
    (scan&&scan.model?` · the committed scan used hash <code>${KD.esc(scan.model.sha256||"—")}</code>`:"");
  KD.$("#params").innerHTML = paramTable(model);
  KD.$("#fees").innerHTML = feeTable(model);
  KD.$("#thrInline").textContent = "$"+model.swing_alert.threshold_dollars;

  if(!scan){
    KD.$("#scanStamp").innerHTML = '<span class="badge warn">no scan committed yet</span> the desk workflow writes <code>data/live/roi.json</code> on a schedule; until then this page shows the model only, never an example number.';
    KD.$("#picks").innerHTML=KD.empty("nothing scored yet");
    return;
  }
  const drift = scan.model && scan.model.sha256 && model.__hash === scan.model.sha256;
  KD.$("#scanStamp").innerHTML = `collected <b>${KD.esc(scan.collected_at||"—")}</b> (${KD.ago(scan.collected_at)}) · environment <b>${KD.esc(scan.environment||"—")}</b> · endpoint <code>${KD.esc(scan.base_url||"—")}</code> · model <code>${KD.esc(scan.model?.id||"—")}</code> hash <code>${KD.esc(scan.model?.sha256||"—")}</code>`+
    ` · runtime ${scan.runtime_seconds===undefined?"—":scan.runtime_seconds+"s"}`+
    (scan.historical_cutoff?` · historical cutoff <code>${KD.esc(scan.historical_cutoff.market_settled_ts||"—")}</code>`:"");
  const c=scan.counts||{};
  KD.$("#scanKpis").innerHTML=[
    ["open markets scanned",KD.num(c.open_scanned),"status=open, combos excluded"],
    ["in the five topics",KD.num(c.open_in_scope),"classified by series or word-boundary keyword"],
    ["pass every gate",KD.num(c.eligible),`of which ${KD.num(c.picks)} shown as picks`],
    ["gated but close",KD.num(c.near_misses),`+${KD.num(c.unscoreable)} with no two-sided quote`],
    ["swings ≥ threshold",KD.num(c.alerts),"in the retained collector history"],
    ["with momentum measured",KD.num(c.markets_with_momentum),"needs ≥2 observations in the window"],
    ["with a URL in their own rules",KD.num(c.markets_with_catalyst_url),"the only links the desk can honestly show"],
  ].map(([l,v,s])=>`<div class="card"><div class="l">${l}</div><div class="v">${v}</div><div class="small mut">${s}</div></div>`).join("");

  KD.$("#picks").innerHTML = (scan.picks&&scan.picks.length)
    ? picksTable(scan.picks)
    : `<div class="card"><p class="empty">No market passes every gate in this scan. That is a normal result: a
       positive edge after crossing the spread and paying the taker fee is rare on a well-quoted book. The
       closest candidates and the exact gate that stopped each one are listed below.</p></div>`;
  KD.$("#near").innerHTML = (scan.near_misses&&scan.near_misses.length)?picksTable(scan.near_misses):'<p class="small mut">no near misses recorded in this scan.</p>';
  KD.$("#unsc").innerHTML = (scan.unscoreable&&scan.unscoreable.length)
    ? `<p class="small mut"><b>${scan.unscoreable.length} market(s) could not be priced at all</b> — usually a one-sided
        quote, where the spread cannot be measured. They are listed without an entry rather than given an invented one:</p>`+
      KD.table([{key:"m",label:"Market"},{key:"why",label:"why not scored"},{key:"src",label:"source"}],
        scan.unscoreable.map(u=>({m:`<code>${KD.esc(u.ticker)}</code><div class="small mut">${KD.esc((u.title||"").slice(0,60))}</div>`,
          why:(u.reasons||[]).map(r=>`<span class="badge warn">${KD.esc(r)}</span>`).join(" ")||'<span class="na">—</span>',src:KD.srcLink(u.source,"API")})))
    : "";
  const thr = (scan.model&&scan.model.swing_threshold_dollars)||model.swing_alert.threshold_dollars;
  KD.$("#alerts").innerHTML = (scan.alerts&&scan.alerts.length)
    ? KD.table([
      {key:"t",label:"observed (UTC)"},{key:"m",label:"market"},{key:"mv",label:"move",num:true},
      {key:"fr",label:"from → to",num:true},{key:"cat",label:"topic"},{key:"picks",label:"in picks"},
      {key:"cause",label:"source named in the market's own record"},{key:"src",label:"source"}],
      scan.alerts.slice(0,40).map(a=>({
        t:`<span class="mono">${KD.esc(a.t||"")}</span><div class="small mut">prev ${KD.esc(a.previous_t||"—")}</div>`,
        m:`<a href="live.html#${encodeURIComponent(a.ticker)}">${KD.esc((a.title||a.ticker||"").replace(/\*\*/g,"").slice(0,58))}</a><div class="small mut mono">${KD.esc(a.ticker)}</div>`,
        mv:`<b style="color:${a.delta>0?"var(--ok)":"var(--bad)"}">${a.delta>0?"▲":"▼"} ${Math.abs(a.cents).toFixed(1)}¢</b>`,
        fr:`$${Number(a.from).toFixed(2)} → $${Number(a.to).toFixed(2)}`,
        cat:`${CATS[a.category_id]||"—"} ${KD.basisBadge(a.category_basis)}`,
        picks:a.in_picks?'<span class="badge ok">yes</span>':'<span class="badge">no</span>',
        cause:(a.catalysts&&a.catalysts.length)?a.catalysts.map(cc=>{
          const lab=KD.esc(String(cc.url).replace(/^https?:\/\//,"").slice(0,40));
          return `<a href="${KD.esc(cc.url)}" target="_blank" rel="noopener">${lab}</a> <span class="mut small">(${KD.esc(cc.field)})</span>`;
        }).join(" · "):'<span class="na">no URL in the market record</span>',
        src:KD.srcLink(a.source,"API")})),{empty:"no qualifying swings in the retained history"})
    : '<p class="small mut">no alerts in this scan (the collector history has not accumulated two observations of the same market inside the retained window yet).</p>';

  KD.$("#valMethod").textContent = (scan.validation&&scan.validation.method)||"no method recorded";
  KD.$("#validation").innerHTML = validationBlock(scan.validation||{});
  const byc=(scan.validation&&scan.validation.by_category)||{};
  KD.$("#validationCats").innerHTML = Object.keys(byc).length
    ? KD.table([{key:"c",label:"Topic"},{key:"s",label:"signals",num:true},{key:"h",label:"hits",num:true},
                {key:"r",label:"hit rate",num:true},{key:"p",label:"P&L per 100 contracts",num:true}],
      Object.entries(byc).map(([k,v])=>({c:CATS[k]||k,s:KD.num(v.signals),h:KD.num(v.hits),
        r:v.signals?((v.hits/v.signals)*100).toFixed(1)+"%":'<span class="na">—</span>',
        p:"$"+Number(v.pnl_per_100_contracts||0).toFixed(2)})))
    : "";
  const lims=(scan.validation&&scan.validation.not_measured)||[];
  KD.$("#valLimits").innerHTML = "Not measured: "+(lims.length?lims.map(x=>`<i>${KD.esc(x)}</i>`).join(" · "):"nothing recorded")
    + (scan.disclaimers&&scan.disclaimers.length?`<br><br>Scan disclaimers: ${scan.disclaimers.map(d=>KD.esc(d)).join(" · ")}`:"");
})();
