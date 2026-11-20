// Minimal browser stubs, then evaluate engine.js and exercise the logic.
global.localStorage = { _s:{}, getItem(k){return this._s[k]||null;}, setItem(k,v){this._s[k]=v;} };
global.window = {};
global.fetch = async (url) => {
  url = String(url);
  if (url.includes("/exchange/status")) return { ok:true, status:200, json:async()=>({exchange_status:"active"}) };
  if (url.includes("/orderbook")) return { ok:true, status:200, json:async()=>({orderbook_fp:{yes_dollars:[[0.42,300],[0.45,120]],no_dollars:[[0.55,500],[0.58,80]]}}) };
  if (url.includes("/markets")) {
    const t = url.split("tickers=")[1] || "";
    const rows = t.split(",").filter(Boolean).map(tk => mk[tk]).filter(Boolean);
    return { ok:true, status:200, json:async()=>({markets: rows}) };
  }
  return { ok:false, status:404, json:async()=>({}) };
};
let seq = 0;
const mk = {};
function row(ticker, last, opts={}) {
  mk[ticker] = Object.assign({
    ticker, title: "Test market "+ticker, category_id: opts.cat||"crypto", category_basis: "seed",
    status: "active", result: "", last_price_dollars: String(last),
    yes_bid_dollars: String(Math.max(0.01, last-0.01)),
    yes_ask_dollars: String(Math.min(0.99, last+0.01)),
    no_bid_dollars: String(Math.max(0.01,1-last-0.01)), no_ask_dollars: String(Math.min(0.99,1-last+0.01)),
    volume_fp: "90000", volume_24h_fp: "20000", open_interest_fp: "50000",
    close_time: "2026-12-31T23:59:00Z", source: "https://x/"+ticker
  }, opts.extra||{});
  return mk[ticker];
}

const src = require('fs').readFileSync(require('path').join(__dirname, '..', '..', 'assets', 'engine.js'), 'utf8');
eval(src);
const KDL = window.KDL;
const AT = KDL.AT;
let fails = 0;
const check = (cond, msg) => { if (!cond) { console.log("FAIL:", msg); fails++; } else console.log("ok:", msg); };

check(KDL.ALERT_THRESHOLD === 0.10, "threshold is 0.10");
check(KDL.takerFee(100, 0.5) === 1.75 && KDL.takerFee(1, 0.5) === 0.02, "fee formula cent-ceil(0.07xCxPx(1-P)): 100@50c=1.75, 1@50c=0.02");
check(KDL.takerFee(100,0.5) === 1.75, "fee = $1.75 for 100 contracts at 50c");

// baseline tick (silent ingest sets prevPrices)
KDL.ingest([row("T-MOM", 0.40), row("T-REV", 0.80)], "live", { silent: true });
check(KDL.feedAlerts().length === 0, "silent ingest produces no alerts");

// upswing +12c on liquid market -> alert + momentum entry
AT.cfg.enabled = true; AT.cfg.strategies = { momentum: true, reversion: true, longshot: false };
AT.cfg.perStrategyCashCap = 300;
AT.state.cash = 1000; AT.state.positions = []; AT.state.closed = [];
KDL.ingest([row("T-MOM", 0.52)], "live");
let alerts = KDL.feedAlerts();
check(alerts.length === 1 && alerts[0].dir === "up" && Math.abs(alerts[0].delta-0.12)<1e-9, "upswing alert delta=+0.12");
check(alerts[0].links && alerts[0].links.api_query.startsWith("https://"), "alert carries https API link");
check(alerts[0].model && alerts[0].model.score >= KDL.MODEL.threshold, "alert passes model threshold -> appears in picks feed");
check(AT.state.positions.length === 1 && AT.state.positions[0].strategy === "momentum", "momentum entry opened");
const pos = AT.state.positions[0];
check(pos.entry_basis === "yes_ask" && Math.abs(pos.entry_price-0.53)<1e-9, "fill at yes_ask 0.53");
check(Math.abs(AT.state.cash - (1000 - pos.count*0.53 - pos.fee_entry)) < 1e-9, "cash debited cost+fee");

// downswing -10c -> stop_loss exit
KDL.ingest([row("T-MOM", 0.42)], "live");
check(AT.state.positions.length === 0, "position closed at stop");
const rec = AT.state.closed[0];
check(rec && rec.exit_reason === "stop_loss", "exit reason stop_loss");
check(rec.pnl_net < 0, "stop loss realizes a loss");
const s = AT.stats();
check(Math.abs(s.realized - rec.pnl_net) < 1e-9, "stats realized equals ledger");

// reversion: fade upswing pushing >= 0.85
AT.state.positions = []; AT.state.closed = [];
KDL.ingest([row("T-REV", 0.70)], "live", { silent: true }); // reset baseline silently
KDL.ingest([row("T-REV", 0.90)], "live");
check(AT.state.positions.some(p => p.strategy === "reversion" && p.dir === -1), "reversion opened NO after upswing to 90c");
const noPos = AT.state.positions.find(p => p.strategy === "reversion");
check(noPos.entry_basis === "no_ask", "NO fill basis recorded");

// settlement: result yes pays NO holders 0 -> close at 0
KDL.ingest([Object.assign({}, row("T-REV", 1.0), { status: "finalized", result: "yes" })], "live");
check(!AT.state.positions.some(p => p.id === noPos.id), "settled NO position removed");
const recNo = AT.state.closed.find(t => t.id === noPos.id);
check(recNo && recNo.exit_reason === "settlement" && Math.abs(recNo.pnl_net - (-(noPos.entry_price*noPos.count) - noPos.fee_entry - recNo.fee_exit)) < 0.011, "NO settlement pays 0 on YES result, net loss = entry+fees");

// threshold enforcement: +9c does NOT alert
KDL.ingest([row("T-MOM", 0.42)], "live", { silent: true });
KDL.ingest([row("T-MOM", 0.51)], "live");
check(KDL.feedAlerts().filter(a=>a.ticker==="T-MOM" && a.to===0.51).length === 0, "9-cent move does not alert");

// scalar result left open
AT.state.positions = []; AT.state.closed = []; AT.state.cash = 1000;
KDL.ingest([row("T-SC", 0.50)], "live", { silent: true });
KDL.ingest([Object.assign({}, row("T-SC", 0.62), { status: "finalized", result: "scalar", settlement_value_dollars: "0.62" })], "live");
check(KDL.feedAlerts().some(a=>a.ticker==="T-SC"), "10c+ move alerts");
check(AT.state.positions.length === 0, "scalar settlement: no auto entry existed; nothing left dangling");

console.log(fails ? `\n${fails} FAILURES` : "\nALL ENGINE TESTS PASSED");
process.exit(fails ? 1 : 0);
