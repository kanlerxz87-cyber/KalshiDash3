/**
 * collect.mjs — build data/snapshot.json for the KalshiDash3 site.
 *
 * Run it in CI (see .github/workflows/refresh-data.yml) or locally with network
 * access:
 *
 *   node tools/collect.mjs --out data/snapshot.json
 *
 * Options
 *   --base <url>      override the REST base (default demo recommended host)
 *   --env demo|production
 *   --pages <n>       event pages to scan (200 events each, default 8)
 *   --top <n>         events kept per topic (default 25)
 *   --global-top <n>  events kept on the all-topics board (default 30)
 *   --levels <n>      orderbook levels kept per side (default 10)
 *   --chart-markets <n> markets given candlesticks + trade prints (default 10)
 *   --lookback-days <n> days of settled markets to pull for the resolution log (default 7)
 *   --throttle <ms>   pause between requests (default 300)
 *
 * Nothing is invented: every stored number comes from a documented demo response
 * field; derived fields carry their formula in the snapshot's `definitions` block.
 * Requests are unauthenticated public reads, throttled, with 429 backoff.
 */

import fs from "node:fs";
import path from "node:path";
import {
  KalshiClient,
  HOSTS,
  TOPICS,
  classifyEvent,
  normalizeOrderbook,
  readResolution,
  fp,
  round,
  openInterestUsd,
  notionalVolumeUsd,
  notionalVolume24hUsd,
  tradedDollarsFromTrades,
  sleep,
  chunk,
} from "./kalshi-client.mjs";

const TOOL_VERSION = "1.0.0";
const ARGS = parseArgs(process.argv.slice(2));

function parseArgs(argv) {
  const out = {
    base: undefined,
    env: "demo",
    pages: 8,
    top: 25,
    globalTop: 30,
    levels: 10,
    chartMarkets: 10,
    lookbackDays: 7,
    throttle: 300,
    out: "data/snapshot.json",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const next = () => argv[++i];
    if (a === "--base") out.base = next();
    else if (a === "--env") out.env = next();
    else if (a === "--pages") out.pages = Number(next());
    else if (a === "--top") out.top = Number(next());
    else if (a === "--global-top") out.globalTop = Number(next());
    else if (a === "--levels") out.levels = Number(next());
    else if (a === "--chart-markets") out.chartMarkets = Number(next());
    else if (a === "--lookback-days") out.lookbackDays = Number(next());
    else if (a === "--throttle") out.throttle = Number(next());
    else if (a === "--out") out.out = next();
    else throw new Error(`unknown argument ${a}`);
  }
  return out;
}

const log = (msg) => console.log(`[collect] ${msg}`);
const client = new KalshiClient({
  env: ARGS.env,
  base: ARGS.base,
  logger: (m) => log(m),
});

/* ------------------------------------------------------------------ */

async function main() {
  const startedAt = new Date();
  log(`base=${client.base}`);

  /* 1. exchange status (GET /exchange/status) */
  let exchange = null;
  try {
    exchange = await client.exchangeStatus();
  } catch (err) {
    log(`exchange status failed: ${err.message}`);
  }

  /* 2. discovery: open events, then soon-to-close events. No nested markets yet. */
  const seen = new Map();
  const openScan = await client.pageEvents({ status: "open" }, ARGS.pages);
  for (const ev of openScan.events) seen.set(ev.event_ticker, { ...compactEvent(ev), _status: "open" });
  log(`open events scanned: ${openScan.events.length} over ${openScan.pages} page(s)`);

  let closedScan = { events: [], pages: 0 };
  try {
    closedScan = await client.pageEvents({ status: "closed" }, 3);
    for (const ev of closedScan.events) {
      if (!seen.has(ev.event_ticker)) seen.set(ev.event_ticker, { ...compactEvent(ev), _status: "closed" });
    }
  } catch (err) {
    log(`closed scan failed: ${err.message}`);
  }
  log(`closed events scanned: ${closedScan.events.length}`);

  /* 3. topic classification over the whole scanned universe */
  const byTopic = new Map(TOPICS.map((t) => [t.id, []]));
  let classified = 0;
  for (const ev of seen.values()) {
    const cls = classifyEvent(ev);
    if (!cls) continue;
    classified += 1;
    ev._topic = cls.topic;
    ev._evidence = cls.evidence;
    byTopic.get(cls.topic).push(ev);
  }
  log(`classified ${classified} of ${seen.size} events into ${TOPICS.length} topics`);

  /* 4. enrich with nested markets, ranked by open-interest dollars */
  const keepPerTopic = new Map();
  for (const t of TOPICS) {
    const list = byTopic.get(t.id).sort((a, b) => rankKey(b) - rankKey(a)).slice(0, ARGS.top);
    keepPerTopic.set(t.id, list);
  }
  const wanted = new Map();
  for (const list of keepPerTopic.values()) for (const ev of list) wanted.set(ev.event_ticker, ev);
  log(`enriching ${wanted.size} events with nested markets`);

  const enriched = [];
  for (const group of chunk([...wanted.keys()], 20)) {
    try {
      const data = await client.events({ tickers: group.join(","), with_nested_markets: "true", limit: 200 });
      for (const ev of data.events || []) enriched.push(ev);
    } catch (err) {
      log(`nested-market fetch failed for ${group.length} tickers: ${err.message}`);
    }
    await sleep(ARGS.throttle);
  }

  const events = enriched.map((ev) => {
    const markets = (ev.markets || []).map(compactMarket);
    const agg = aggregateEvent(markets);
    const cls = classifyEvent(ev);
    const best = [...markets].sort((a, b) => (b.oi_usd ?? 0) - (a.oi_usd ?? 0))[0] || null;
    return {
      event_ticker: ev.event_ticker,
      series_ticker: ev.series_ticker ?? null,
      title: ev.title ?? "",
      sub_title: ev.sub_title ?? "",
      category: ev.category ?? "",
      status: ev._status || ev.status || "open",
      strike_date: ev.strike_date ?? null,
      strike_period: ev.strike_period ?? null,
      mutually_exclusive: !!ev.mutually_exclusive,
      collateral_return_type: ev.collateral_return_type ?? "",
      last_updated_ts: ev.last_updated_ts ?? null,
      settlement_sources: (ev.settlement_sources || []).slice(0, 4).map((s) => ({ name: s.name || "", url: s.url || "" })),
      topic: cls ? cls.topic : null,
      topic_label: cls ? cls.label : null,
      topic_evidence: cls ? cls.evidence : [],
      best_market_ticker: best ? best.ticker : null,
      earliest_close_time: markets.length ? markets.map((m) => m.close_time).filter(Boolean).sort()[0] ?? null : null,
      markets,
      aggregates: agg,
    };
  });

  events.sort((a, b) => (b.aggregates.oi_usd ?? 0) - (a.aggregates.oi_usd ?? 0));

  /* 5. orderbook depth for the biggest markets -> liquidity per price level */
  const chartTargets = events.slice(0, ARGS.globalTop);
  const bookTickers = unique(chartTargets.map((e) => e.best_market_ticker).filter(Boolean)).slice(0, 100);
  const books = {};
  if (bookTickers.length) {
    try {
      const data = await client.orderbooks(bookTickers);
      for (const [ticker, ob] of Object.entries(data)) books[ticker] = trimBook(ob, ARGS.levels);
    } catch (err) {
      log(`orderbook batch failed: ${err.message}`);
    }
  }
  await sleep(ARGS.throttle);

  /* 6. candles + trade prints for the charted markets */
  const chartMarkets = [];
  for (const ev of chartTargets) {
    if (chartMarkets.length >= ARGS.chartMarkets) break;
    const m = ev.markets.find((x) => x.ticker === ev.best_market_ticker) || ev.markets[0];
    if (!m || !ev.series_ticker) continue;
    const entry = { ticker: m.ticker, event_ticker: ev.event_ticker, series_ticker: ev.series_ticker, title: m.title };
    const nowSec = Math.floor(Date.now() / 1000);
    for (const [label, minutes, spanMin] of [["m1", 1, 240], ["h1", 60, 60 * 72]]) {
      try {
        const rows = await client.candlesticks(ev.series_ticker, m.ticker, nowSec - spanMin * 60, nowSec, minutes);
        entry[`candles_${label}`] = rows.map(compactCandle);
      } catch (err) {
        entry[`candles_${label}_error`] = String(err.message).slice(0, 160);
        entry[`candles_${label}`] = [];
      }
      await sleep(ARGS.throttle);
    }
    try {
      const t = await client.trades(m.ticker, 100);
      const trades = (t.trades || []).map(compactTrade);
      entry.trades = trades;
      entry.traded_dollars_sample = tradedDollarsFromTrades(trades).dollars;
      entry.trades_sample_count = tradedDollarsFromTrades(trades).tradesCounted;
    } catch (err) {
      entry.trades_error = String(err.message).slice(0, 160);
      entry.trades = [];
    }
    await sleep(ARGS.throttle);
    chartMarkets.push(entry);
  }
  for (const ev of events) {
    const cm = chartMarkets.find((x) => x.event_ticker === ev.event_ticker);
    if (cm) {
      ev.chart = {
        ticker: cm.ticker,
        candles_m1: cm.candles_m1 || [],
        candles_h1: cm.candles_h1 || [],
        candles_m1_error: cm.candles_m1_error || null,
        candles_h1_error: cm.candles_h1_error || null,
        trades: (cm.trades || []).slice(0, 40),
        traded_dollars_sample: cm.traded_dollars_sample ?? null,
        trades_sample_count: cm.trades_sample_count ?? null,
        trades_error: cm.trades_error || null,
      };
    }
  }

  /* 7. series metadata: official category/categories + fee structure */
  const seriesMeta = {};
  const seriesTickers = unique(events.map((e) => e.series_ticker).filter(Boolean)).slice(0, 30);
  for (const s of seriesTickers) {
    try {
      const data = (await client.get(`/series/${encodeURIComponent(s)}`)).data;
      const se = data.series || {};
      seriesMeta[s] = {
        ticker: se.ticker || s,
        title: se.title || "",
        frequency: se.frequency || "",
        category: se.category ?? null,
        categories: se.categories ?? [],
        tags: se.tags ?? [],
        fee_type: se.fee_type ?? null,
        fee_multiplier: se.fee_multiplier ?? null,
        contract_url: se.contract_url || null,
        settlement_sources: (se.settlement_sources || []).slice(0, 3).map((x) => ({ name: x.name || "", url: x.url || "" })),
      };
    } catch (err) {
      seriesMeta[s] = { ticker: s, error: String(err.message).slice(0, 120) };
    }
    await sleep(ARGS.throttle);
  }
  for (const ev of events) {
    const meta = seriesMeta[ev.series_ticker];
    if (meta && !meta.error) {
      ev.series_category = meta.category;
      ev.series_categories = meta.categories;
      ev.fee_type = meta.fee_type;
      ev.fee_multiplier = meta.fee_multiplier;
    }
  }

  /* 8. resolution log: recently settled markets inside the five topics */
  const settledMarkets = [];
  const minSettledTs = Math.floor(Date.now() / 1000) - ARGS.lookbackDays * 86400;
  let settledScan = [];
  try {
    let cursor = "";
    for (let page = 0; page < 4; page += 1) {
      const data = await client.markets({ status: "settled", min_settled_ts: minSettledTs, limit: 200, ...(cursor ? { cursor } : {}) });
      settledScan.push(...(data.markets || []));
      cursor = data.cursor || "";
      if (!cursor) break;
      await sleep(ARGS.throttle);
    }
  } catch (err) {
    log(`settled scan failed: ${err.message}`);
  }
  for (const m of settledScan) {
    const cls = classifyEvent({ title: m.title, sub_title: m.yes_sub_title || "", series_ticker: m.series_ticker || "", category: m.category || "" });
    const res = readResolution(m);
    if (!res.resolved) continue;
    settledMarkets.push({
      ticker: m.ticker,
      event_ticker: m.event_ticker || null,
      series_ticker: m.series_ticker || null,
      title: m.title || "",
      outcome: res.outcome,
      raw_result: res.raw_result,
      status: res.status,
      close_time: m.close_time ?? null,
      yes_last_price_dollars: m.yes_bid_dollars ?? null,
      volume_fp: m.volume_fp ?? null,
      open_interest_fp: m.open_interest_fp ?? null,
      topic: cls ? cls.topic : null,
      category: m.category ?? null,
    });
  }
  log(`settled markets captured: ${settledMarkets.length}`);

  /* 9. write */
  const snapshot = {
    kind: "kalshidash3-snapshot",
    schema_version: 2,
    tool_version: TOOL_VERSION,
    generated_at: startedAt.toISOString(),
    generated_at_end: new Date().toISOString(),
    environment: ARGS.env,
    base_url: client.base,
    alternate_base_url: (HOSTS[ARGS.env] || HOSTS.demo).restAlt,
    ws_url: (HOSTS[ARGS.env] || HOSTS.demo).ws,
    ws_url_alternate: (HOSTS[ARGS.env] || HOSTS.demo).wsAlt,
    demo_site: (HOSTS[ARGS.env] || HOSTS.demo).site,
    exchange_status: exchange,
    definitions: {
      oi_usd: "open_interest_fp (contracts) x $1.00 face value per contract",
      volume_usd: "volume_fp (contracts) x $1.00 face value per contract",
      volume_24h_usd: "volume_24h_fp (contracts) x $1.00 face value per contract",
      traded_dollars_sample: "sum(yes_price_dollars x count_fp) over the fetched trade prints only - not a lifetime figure",
      yes_asks: "derived: a NO bid at y is a YES ask at 1 - y with identical size (docs orderbook_responses)",
      spread: "best_yes_ask - best_yes_bid, where best_yes_ask = 1 - best_no_bid",
      mid: "(best_yes_bid + best_yes_ask) / 2 in YES dollars",
      topic: "derived keyword/series-ticker match over event title + series ticker + category; Kalshi has no topic field",
      candles_m1: "GET .../candlesticks period_interval=1 (minutes); 1m is the finest interval the REST API offers",
      candles_h1: "GET .../candlesticks period_interval=60 (minutes)",
      seconds_scale: "not available from REST candlesticks; built client-side by sampling quotes",
      resolution: "market.status == 'settled' with market.result in {yes, no}; anything else is left unresolved",
    },
    scan: {
      open_pages: openScan.pages,
      open_events: openScan.events.length,
      closed_events: closedScan.events.length,
      classified_events: classified,
      unique_series: seriesTickers.length,
      requests: client.requests,
      retries: client.retries_used,
      status_histogram: histogram(client.status_log.map((s) => s.status)),
      errors: client.status_log.filter((s) => s.status >= 400 || s.status === 0).slice(0, 20),
    },
    topics: TOPICS.map((t) => {
      const list = events.filter((e) => e.topic === t.id);
      return {
        id: t.id,
        label: t.label,
        event_count: list.length,
        oi_usd: round(sum(list.map((e) => e.aggregates.oi_usd ?? 0)), 2),
        volume_24h_usd: round(sum(list.map((e) => e.aggregates.volume_24h_usd ?? 0)), 2),
        resolved_24h: settledMarkets.filter((m) => m.topic === t.id).length,
      };
    }),
    events,
    orderbooks: books,
    series: seriesMeta,
    resolutions: settledMarkets,
    portfolio: {
      configured: false,
      note:
        "Live demo-account portfolio requires KALSHI_API_KEY_ID + a private key; the CI refresh has no credentials, so this block stays empty and the site runs its simulated book. See docs/questions.html.",
    },
  };

  const outPath = path.resolve(ARGS.out);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, `${JSON.stringify(snapshot, null, 1)}\n`);
  const bytes = fs.statSync(outPath).size;
  log(`wrote ${outPath} (${(bytes / 1024).toFixed(1)} KiB, ${events.length} events, ${settledMarkets.length} resolutions)`);
  if (bytes > 3_500_000) throw new Error(`snapshot too large: ${bytes} bytes`);
}

/* ------------------------------------------------------------------ *
 * shaping helpers
 * ------------------------------------------------------------------ */

function compactEvent(ev) {
  return {
    event_ticker: ev.event_ticker,
    series_ticker: ev.series_ticker ?? null,
    title: ev.title ?? "",
    sub_title: ev.sub_title ?? "",
    category: ev.category ?? "",
    strike_date: ev.strike_date ?? null,
    strike_period: ev.strike_period ?? null,
    mutually_exclusive: !!ev.mutually_exclusive,
    collateral_return_type: ev.collateral_return_type ?? "",
    last_updated_ts: ev.last_updated_ts ?? null,
  };
}

/** Ranking key used BEFORE market data is known: prefer series that look liquid by category/recency. */
function rankKey(ev) {
  const t = Date.parse(ev.last_updated_ts || "") || 0;
  return t;
}

function compactMarket(m) {
  const oiUsd = openInterestUsd(m);
  const yesBid = fp(m.yes_bid_dollars);
  const yesAsk = fp(m.yes_ask_dollars);
  const noBid = fp(m.no_bid_dollars);
  const res = readResolution(m);
  return {
    ticker: m.ticker,
    title: m.title ?? "",
    yes_sub_title: m.yes_sub_title ?? "",
    no_sub_title: m.no_sub_title ?? "",
    status: m.status ?? "",
    result: res.outcome,
    raw_result: m.result ?? "",
    close_time: m.close_time ?? null,
    open_time: m.open_time ?? null,
    expected_expiration_time: m.expected_expiration_time ?? null,
    last_price_dollars: fp(m.last_price_dollars),
    previous_price_dollars: fp(m.previous_price_dollars),
    yes_bid_dollars: yesBid,
    yes_ask_dollars: yesAsk,
    no_bid_dollars: noBid,
    no_ask_dollars: fp(m.no_ask_dollars),
    yes_bid_size_fp: fp(m.yes_bid_size_fp),
    yes_ask_size_fp: fp(m.yes_ask_size_fp),
    no_bid_size_fp: fp(m.no_bid_size_fp),
    no_ask_size_fp: fp(m.no_ask_size_fp),
    volume_fp: fp(m.volume_fp),
    volume_24h_fp: fp(m.volume_24h_fp),
    open_interest_fp: fp(m.open_interest_fp),
    oi_usd: oiUsd,
    volume_usd: notionalVolumeUsd(m),
    volume_24h_usd: notionalVolume24hUsd(m),
    spread: yesBid !== null && yesAsk !== null ? round(yesAsk - yesBid, 4) : noBid !== null ? round(1 - noBid - (yesBid ?? 0), 4) : null,
    mid: yesBid !== null && yesAsk !== null ? round((yesBid + yesAsk) / 2, 4) : yesBid,
    price_level_structure: m.price_level_structure ?? null,
    price_ranges: (m.price_ranges || []).map((r) => ({ start: r.start, end: r.end, step: r.step })),
    rules_primary: (m.rules_primary || "").slice(0, 700),
    notional_value_dollars: fp(m.notional_value_dollars),
    market_type: m.market_type ?? null,
    can_close_early: m.can_close_early ?? null,
  };
}

function aggregateEvent(markets) {
  const oi = sum(markets.map((m) => m.open_interest_fp ?? 0));
  const vol = sum(markets.map((m) => m.volume_fp ?? 0));
  const vol24 = sum(markets.map((m) => m.volume_24h_fp ?? 0));
  const best = [...markets].sort((a, b) => (b.oi_usd ?? 0) - (a.oi_usd ?? 0))[0];
  return {
    markets: markets.length,
    open_interest_fp: round(oi, 2),
    oi_usd: round(oi, 2),
    volume_fp: round(vol, 2),
    volume_usd: round(vol, 2),
    volume_24h_fp: round(vol24, 2),
    volume_24h_usd: round(vol24, 2),
    resolved_markets: markets.filter((m) => m.status === "settled").length,
    yes_results: markets.filter((m) => m.result === "YES").length,
    no_results: markets.filter((m) => m.result === "NO").length,
    best_spread: best ? best.spread : null,
    leader: best ? { ticker: best.ticker, title: best.title, mid: best.mid, oi_usd: best.oi_usd } : null,
  };
}

function trimBook(ob, levels) {
  return {
    best_yes_bid: ob.best_yes_bid,
    best_yes_ask: ob.best_yes_ask,
    best_no_bid: ob.best_no_bid,
    best_no_ask: ob.best_no_ask,
    spread: ob.spread,
    yes_bid_liquidity: ob.yes_bid_liquidity,
    yes_ask_liquidity: ob.yes_ask_liquidity,
    total_book_contracts: ob.total_book_contracts,
    // keep the deepest (best) levels on each side
    yes_bids: ob.yes_bids.slice(-levels),
    no_bids: ob.no_bids.slice(-levels),
    yes_asks: ob.yes_asks.slice(0, levels),
  };
}

function compactCandle(c) {
  return {
    t: c.end_period_ts,
    price_open: fp(c.price?.open_dollars),
    price_high: fp(c.price?.high_dollars),
    price_low: fp(c.price?.low_dollars),
    price_close: fp(c.price?.close_dollars),
    yes_bid_open: fp(c.yes_bid?.open_dollars),
    yes_bid_close: fp(c.yes_bid?.close_dollars),
    yes_ask_open: fp(c.yes_ask?.open_dollars),
    yes_ask_close: fp(c.yes_ask?.close_dollars),
    volume_fp: fp(c.volume_fp),
    open_interest_fp: fp(c.open_interest_fp),
  };
}

function compactTrade(t) {
  return {
    trade_id: t.trade_id ?? null,
    ticker: t.ticker,
    t: t.created_time ?? null,
    yes_price_dollars: fp(t.yes_price_dollars),
    no_price_dollars: fp(t.no_price_dollars),
    count_fp: fp(t.count_fp),
    taker_book_side: t.taker_book_side ?? null,
    taker_outcome_side: t.taker_outcome_side ?? null,
    is_block_trade: !!t.is_block_trade,
    notional_usd: t.count_fp !== undefined && t.yes_price_dollars !== undefined ? round(fp(t.yes_price_dollars) * fp(t.count_fp), 4) : null,
  };
}

function sum(arr) {
  return arr.reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0);
}

function unique(arr) {
  return [...new Set(arr)];
}

function histogram(values) {
  const out = {};
  for (const v of values) out[String(v)] = (out[String(v)] || 0) + 1;
  return out;
}

main().catch((err) => {
  console.error(`[collect] FAILED: ${err?.stack || err}`);
  process.exitCode = 1;
});
