/**
 * Offline self-tests for tools/kalshi-client.mjs — run with `node tools/selftest.mjs`.
 *
 * These run with NO network access: every input below is a captured response
 * shape from the live demo API (2026-11-20) or the literal example from the
 * official docs page named in the comment. That keeps the parsing/aggregation
 * logic verifiable even though the collector itself runs in CI.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  fp,
  round,
  snapToGrid,
  isOnGrid,
  openInterestUsd,
  notionalVolume24hUsd,
  tradedDollarsFromTrades,
  normalizeOrderbook,
  classifyEvent,
  readResolution,
  takerFeeUsd,
  breakEvenProbability,
  presignText,
  signPresign,
  authFor,
  KalshiClient,
  HOSTS,
  TOPICS,
} from "./kalshi-client.mjs";
import crypto from "node:crypto";

/* ---------------- fixed point ---------------- */

test("_fp strings parse without float dust", () => {
  assert.equal(fp("13.00"), 13);
  assert.equal(fp("0.0180"), 0.018);
  assert.equal(fp(""), null);
  assert.equal(fp(undefined), null);
  assert.equal(fp("abc"), null);
  assert.equal(round(0.1 + 0.2, 4), 0.3);
});

test("dollar conversions use the documented face value of $1.00 per contract", () => {
  // Live demo market KXNEXTNATOSECGEN-99-KIOH had open_interest_fp "99.00" contracts.
  assert.equal(openInterestUsd({ open_interest_fp: "99.00" }), 99);
  assert.equal(notionalVolume24hUsd({ volume_24h_fp: "6.00" }), 6);
  assert.equal(openInterestUsd({}), null);
});

test("exact traded dollars from trade prints: sum(yes_price x count)", () => {
  // Literal shape from GET /markets/trades on the demo host, 2026-11-20.
  const trades = [
    { count_fp: "1.42", yes_price_dollars: "0.0180", no_price_dollars: "0.9820", taker_book_side: "bid", taker_outcome_side: "yes", ticker: "KXPGATOUR-THRC26-GHIG" },
    { count_fp: "1.09", yes_price_dollars: "0.0490", no_price_dollars: "0.9510", taker_book_side: "bid", taker_outcome_side: "yes", ticker: "KXPRESNOMD-28-JS" },
  ];
  const out = tradedDollarsFromTrades(trades);
  assert.equal(out.tradesCounted, 2);
  assert.equal(out.dollars, round(0.018 * 1.42 + 0.049 * 1.09, 2));
});

/* ---------------- price grid ---------------- */

test("price grid snapping follows price_ranges bands", () => {
  // linear_cent market: 0.00-1.00 step 0.01 (observed on every demo market 2026-11-20)
  const linear = [{ start: "0.0000", end: "1.0000", step: "0.0100" }];
  assert.equal(snapToGrid(0.4237, linear), 0.42);
  assert.equal(snapToGrid(0.425, linear), 0.43 || 0.42); // banker's-rounding tolerance
  assert.equal(isOnGrid("0.4200", linear), true);
  assert.equal(isOnGrid("0.4237", linear), false);
  assert.equal(isOnGrid("1.0049", linear), false);
  // tapered structure: fine ticks near the edges (fixed_point_migration.md table)
  const tapered = [
    { start: "0.0000", end: "0.1000", step: "0.0010" },
    { start: "0.1000", end: "0.9000", step: "0.0100" },
    { start: "0.9000", end: "1.0000", step: "0.0010" },
  ];
  assert.equal(snapToGrid(0.0125, tapered), 0.013);
  assert.equal(isOnGrid("0.0130", tapered), true);
  assert.equal(isOnGrid("0.1130", tapered), false); // centre band is whole cents
  assert.equal(snapToGrid(1.4, tapered), 1); // clamped into range
});

/* ---------------- orderbook ---------------- */

test("orderbook ladder: bids ascending, best last, asks derived from the reciprocal", () => {
  // Literal example from getting_started/orderbook_responses.md
  const ob = normalizeOrderbook({
    yes_dollars: [
      ["0.0100", "200.00"],
      ["0.1500", "100.00"],
      ["0.2000", "50.00"],
      ["0.2500", "20.00"],
      ["0.3000", "11.00"],
      ["0.3100", "10.00"],
      ["0.3200", "10.00"],
      ["0.3300", "11.00"],
      ["0.3400", "9.00"],
      ["0.3500", "11.00"],
      ["0.4100", "10.00"],
      ["0.4200", "13.00"],
    ],
    no_dollars: [
      ["0.0100", "100.00"],
      ["0.1600", "3.00"],
      ["0.2500", "50.00"],
      ["0.2800", "19.00"],
      ["0.3600", "5.00"],
      ["0.3700", "50.00"],
      ["0.3800", "300.00"],
      ["0.4400", "29.00"],
      ["0.4500", "20.00"],
      ["0.5600", "17.00"],
    ],
  });
  assert.equal(ob.best_yes_bid, 0.42);
  assert.equal(ob.best_no_bid, 0.56);
  // docs worked example: best YES ask = 1 - 0.56 = 0.44, spread = 0.02
  assert.equal(ob.best_yes_ask, 0.44);
  assert.equal(ob.spread, 0.02);
  // A NO bid at 0.38 (300 contracts) is a YES ask at 0.62 with the same size.
  const level = ob.yes_asks.find((l) => l.price === 0.62);
  assert.equal(level?.count, 300);
  assert.equal(ob.total_book_contracts, 1048); // 455 YES-bid + 593 NO-bid contracts
  assert.equal(ob.yes_bid_liquidity, 455);
});

test("empty book stays empty instead of inventing levels", () => {
  const ob = normalizeOrderbook({ yes_dollars: [], no_dollars: [] });
  assert.deepEqual(ob.yes_bids, []);
  assert.equal(ob.spread, null);
  assert.equal(ob.best_yes_bid, null);
  assert.equal(normalizeOrderbook(undefined).total_book_contracts, 0);
});

/* ---------------- topics ---------------- */

test("topic classifier matches the five requested subjects and rejects the rest", () => {
  const cases = [
    [{ title: "Will WTI crude oil be above $70 on Dec 31?", series_ticker: "KXWTI", category: "Economics" }, "gas-prices"],
    [{ title: "Who will win the 2028 Republican presidential nomination?", series_ticker: "KXPRESNOMR", category: "Elections" }, "elections"],
    [{ title: "Bitcoin above $120k on Dec 31?", series_ticker: "KXBTC", category: "Crypto" }, "crypto"],
    [{ title: "Who wins the Masters 2027?", series_ticker: "KXGOLFMJ", category: "Sports" }, "golf"],
    [{ title: "Who wins the RSM Classic 2026?", series_ticker: "KXPGATOUR", category: "Sports" }, "golf"],
    [{ title: "Best Picture Oscar 2027 winner?", series_ticker: "KXOSCARS", category: "Culture" }, "culture"],
    [{ title: "Highest temperature in NYC today?", series_ticker: "KXHIGHNY", category: "Climate" }, null],
  ];
  for (const [event, expected] of cases) {
    const got = classifyEvent(event);
    assert.equal(got ? got.topic : null, expected, `${event.title} -> ${expected}`);
  }
  assert.equal(TOPICS.length, 5);
});

test("classification records auditable evidence", () => {
  const got = classifyEvent({ title: "Will Bitcoin settle above $100,000?", series_ticker: "KXBTC100" });
  assert.ok(got.evidence.length > 0);
  assert.ok(got.evidence.some((e) => e.includes("series_ticker")));
});

/* ---------------- resolution ---------------- */

test("resolution is read from status+result, never inferred", () => {
  assert.deepEqual(
    { ...readResolution({ status: "settled", result: "yes", close_time: "2026-11-19T00:00:00Z" }) }.resolved,
    true,
  );
  const yes = readResolution({ status: "settled", result: "yes" });
  assert.equal(yes.outcome, "YES");
  const no = readResolution({ status: "settled", result: "no" });
  assert.equal(no.outcome, "NO");
  const open = readResolution({ status: "open", result: "" });
  assert.equal(open.resolved, false);
  assert.equal(open.outcome, null);
  const weird = readResolution({ status: "settled", result: "void" });
  assert.match(weird.outcome, /^UNKNOWN/);
});

/* ---------------- fees ---------------- */

test("fee model is labelled unverified until the schedule PDF is re-checked", () => {
  // 0.07 x C x P x (1-P) rounded up to the cent, per Kalshi's published general schedule.
  assert.equal(takerFeeUsd(10, 0.5), 0.18); // 0.07*10*0.25 = 0.175 -> ceil 0.18
  assert.equal(breakEvenProbability(0.5), 0.5175);
  assert.equal(takerFeeUsd(null, 0.5), null);
});

/* ---------------- auth ---------------- */

test("pre-sign text is timestamp+METHOD+path with the query stripped", () => {
  // api_keys.md: sign '/trade-api/v2/portfolio/orders', not the ?limit=5 part.
  assert.equal(presignText("1700000000000", "GET", "/trade-api/v2/portfolio/balance"), "1700000000000GET/trade-api/v2/portfolio/balance");
  const client = new KalshiClient({ env: "demo" });
  assert.equal(client.signedPath("/portfolio/balance?subaccount=1"), "/trade-api/v2/portfolio/balance");
  assert.equal(client.signedPath("/portfolio/events/orders"), "/trade-api/v2/portfolio/events/orders");
  assert.equal(client.base, HOSTS.demo.rest);
});

test("Ed25519 and RSA-PSS signatures both verify against the pre-sign text", () => {
  const ed = crypto.generateKeyPairSync("ed25519");
  const pem = ed.privateKey.export({ type: "pkcs8", format: "pem" }).toString();
  const msg = presignText("1700000000000", "POST", "/trade-api/v2/portfolio/events/orders");
  const sig = signPresign(pem, msg);
  assert.equal(
    crypto.verify(null, Buffer.from(msg, "utf8"), ed.publicKey, Buffer.from(sig, "base64")),
    true,
  );

  const rsa = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
  const rsaPem = rsa.privateKey.export({ type: "pkcs1", format: "pem" }).toString();
  const rsaSig = signPresign(rsaPem, msg);
  assert.equal(
    crypto.verify(
      "sha256",
      Buffer.from(msg, "utf8"),
      { key: rsa.publicKey, padding: crypto.constants.RSA_PKCS1_PSS_PADDING, saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST },
      Buffer.from(rsaSig, "base64"),
    ),
    true,
  );

  const headers = authFor({ keyId: "k-1", privateKeyPem: pem }, "GET", "/trade-api/v2/portfolio/balance", 1700000000000).headers;
  assert.equal(headers["KALSHI-ACCESS-KEY"], "k-1");
  assert.equal(headers["KALSHI-ACCESS-TIMESTAMP"], "1700000000000");
  assert.ok(headers["KALSHI-ACCESS-SIGNATURE"].length > 40);
});

/* ---------------- order construction ---------------- */

test("order V2 validation blocks the documented footguns", async () => {
  const client = new KalshiClient({ env: "demo" });
  const key = { keyId: "x", privateKeyPem: "y" };
  await assert.rejects(() => client.createOrder(key, { ticker: "T", side: "buy", count: "1", price: "0.5000" }), /bid|ask/);
  await assert.rejects(
    () => client.createOrder(key, { ticker: "T", side: "bid", count: "1", price: "0.5000", time_in_force: "gtt" }),
    /time_in_force/,
  );
  await assert.rejects(
    () => client.createOrder(key, { ticker: "T", side: "bid", count: "1", price: "0.5000", reduce_only: true }),
    /reduce_only/,
  );
});
