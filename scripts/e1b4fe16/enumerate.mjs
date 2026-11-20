#!/usr/bin/env node
// Enumerates open and resolved markets for the five topics from the Kalshi DEMO API
// and writes data/live-snapshot.json. Every row carries the API URL it came from.
// Values the API does not return are written as null and listed in `missing`, never inferred.
//
// Usage: node scripts/e1b4fe16/enumerate.mjs            (needs network access to external-api.demo.kalshi.co)
// Exit code is non-zero if the API cannot be reached, so nothing is silently replaced.
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = join(ROOT, "data", "e1b4fe16", "live-snapshot.json");

// Topic -> how series are selected. Official category is exact and case-sensitive.
const TOPICS = [
  { id: "gas-prices", label: "Gas prices", series: { category: "Economics", prefix: "KXAAAGAS" } },
  { id: "elections", label: "Elections", series: { category: "Elections" } },
  { id: "culture", label: "Culture", series: { category: "Culture" } },
  { id: "crypto", label: "Crypto", series: { category: "Crypto" } },
  { id: "golf", label: "Golf", series: { tags: "Golf" } },
];

const REQUIRED_MARKET_FIELDS = ["ticker", "event_ticker", "title", "status", "close_time", "yes_bid_dollars", "yes_ask_dollars", "last_price_dollars", "volume_fp", "open_interest_fp"];

async function getJSON(url, attempt = 1) {
  try {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    if (attempt < 3) { await new Promise((res) => setTimeout(res, 1000 * attempt)); return getJSON(url, attempt + 1); }
    throw new Error(`${url} -> ${e.message}`);
  }
}

async function allPages(url, key) {
  const out = [];
  let cursor = "";
  do {
    const u = url + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : "");
    const d = await getJSON(u);
    out.push(...(d[key] || []));
    cursor = d.cursor || "";
  } while (cursor);
  return out;
}

async function main() {
  const status = await getJSON(`${BASE}/exchange/status`);
  if (!status.trading_active) throw new Error("exchange reports trading_active=false; not overwriting snapshot");

  const result = { generated_at: new Date().toISOString(), environment: "demo", base_url: BASE, exchange_status: status, topics: [] };

  for (const t of TOPICS) {
    const seriesUrl = t.series.tags
      ? `${BASE}/series?tags=${encodeURIComponent(t.series.tags)}&include_volume=true`
      : `${BASE}/series?category=${encodeURIComponent(t.series.category)}&include_volume=true`;
    let series = (await getJSON(seriesUrl)).series || [];
    if (t.series.prefix) series = series.filter((s) => s.ticker.startsWith(t.series.prefix));
    const topic = { id: t.id, label: t.label, source_url: seriesUrl, series: [], markets: [], resolved: [] };

    for (const s of series) {
      const sUrl = `${BASE}/series/${s.ticker}`;
      topic.series.push({ ticker: s.ticker, title: s.title, category: s.category, tags: s.tags, frequency: s.frequency, volume_fp: s.volume_fp ?? null, contract_terms_url: s.contract_terms_url ?? null, source_url: sUrl });

      const openUrl = `${BASE}/markets?series_ticker=${encodeURIComponent(s.ticker)}&status=open&limit=200`;
      const open = await allPages(openUrl, "markets");
      for (const m of open) topic.markets.push(toRow(m, openUrl));

      const allUrl = `${BASE}/markets?series_ticker=${encodeURIComponent(s.ticker)}&limit=200`;
      const all = await allPages(allUrl, "markets");
      for (const m of all.filter((x) => x.result)) topic.resolved.push({ ...toRow(m, allUrl), result: m.result, settlement_value_dollars: m.settlement_value_dollars ?? null });
    }
    result.topics.push(topic);
  }

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify(result, null, 2) + "\n");
  const counts = result.topics.map((t) => `${t.id}: ${t.series.length} series, ${t.markets.length} open, ${t.resolved.length} resolved`);
  console.log("Wrote " + OUT + "\n" + counts.join("\n"));
}

function toRow(m, sourceUrl) {
  const missing = REQUIRED_MARKET_FIELDS.filter((f) => m[f] === undefined || m[f] === null || m[f] === "");
  return {
    ticker: m.ticker,
    event_ticker: m.event_ticker ?? null,
    title: m.title ?? null,
    status: m.status ?? null,
    close_time: m.close_time ?? null,
    yes_bid_dollars: m.yes_bid_dollars ?? null,
    yes_ask_dollars: m.yes_ask_dollars ?? null,
    last_price_dollars: m.last_price_dollars ?? null,
    volume_fp: m.volume_fp ?? null,
    open_interest_fp: m.open_interest_fp ?? null,
    source_url: `${sourceUrl.split("&cursor=")[0]}`,
    missing,
    flags: missing.length ? ["D-MISSING"] : [],
  };
}

main().catch((e) => {
  console.error("FAILED: " + e.message);
  process.exit(1);
});
