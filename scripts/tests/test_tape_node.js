/* KalshiDash3 — tick-level trade-tape alert tests (Node, no browser, no network).
 *
 * These lock in the >= $0.10 rule as applied to EXECUTED PRINTS instead of price
 * snapshots, and they pin the reason the distinction matters:
 *
 *   GET /markets/trades?ticker=KXAAAGASM-26DEC31-3.30  (read 2026-11-21)
 *   prints 0.71 at 2026-11-20T14:26:53Z, then 0.29 at 22:27:19Z, 22:42:22Z, 02:42:40Z ...
 *   -> a real -$0.42 move, which the tape proves print by print.
 *
 *   GET /markets/trades?ticker=KXBTCY-27JAN0100-B87500  (read 2026-11-21)
 *   20 consecutive prints, all 0.0200 -> the snapshots that read 0.99 were restatements.
 *
 * Run: node scripts/tests/test_tape_node.js
 */
"use strict";
const path = require("path");
const KDLIVE = require(path.join(__dirname, "..", "..", "assets", "live.js"));

let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass += 1; console.log(`  ok   ${name}`); }
  else { fail += 1; console.log(`  FAIL ${name}${extra ? " — " + extra : ""}`); }
}

const print = (id, t, p, n, side) => ({
  trade_id: id, created_time: t, yes_price_dollars: p.toFixed(4),
  count_fp: n, taker_outcome_side: side,
});

console.log("A. a confirmed repricing between two prints fires at exactly the 10c boundary");
{
  const trades = [
    print("t1", "2026-11-20T22:27:19.138991Z", 0.29, "7.26", "no"),
    print("t2", "2026-11-20T14:26:53.438355Z", 0.71, "5.29", "yes"),
  ];
  const sw = KDLIVE.detectTapeSwings(trades, 0.10);
  check("one swing detected", sw.length === 1, `got ${sw.length}`);
  check("direction is down", sw[0] && sw[0].direction === "down");
  check("from/to are the executed prices", sw[0] && sw[0].from === 0.71 && sw[0].to === 0.29);
  check("both trade ids carried as proof", sw[0] && sw[0].from_trade_id === "t2" && sw[0].to_trade_id === "t1");
  check("timestamps ordered old -> new", sw[0] && Date.parse(sw[0].previous_t) < Date.parse(sw[0].t));
}

console.log("B. a tape of identical prints produces no alert (the restatement case)");
{
  const trades = Array.from({ length: 20 }, (_, i) =>
    print(`b${i}`, `2026-11-21T06:26:${String(10 + i).padStart(2, "0")}.000000Z`, 0.02, "1.5", "yes"));
  check("no swings from 20 identical prints", KDLIVE.detectTapeSwings(trades, 0.10).length === 0);
}

console.log("C. sub-threshold prints do not fire, exactly 10c does");
{
  const nine = [print("c1", "2026-11-21T00:00:00Z", 0.55, "1", "yes"), print("c2", "2026-11-21T00:01:00Z", 0.64, "1", "yes")];
  check("9c move does not fire", KDLIVE.detectTapeSwings(nine, 0.10).length === 0);
  const ten = [print("d1", "2026-11-21T00:00:00Z", 0.55, "1", "yes"), print("d2", "2026-11-21T00:01:00Z", 0.65, "1", "yes")];
  check("10c move fires", KDLIVE.detectTapeSwings(ten, 0.10).length === 1);
}

console.log("D. only prints after the cursor fire, so a reload does not replay the chat");
{
  const trades = [
    print("e1", "2026-11-21T00:00:00Z", 0.20, "1", "yes"),
    print("e2", "2026-11-21T00:05:00Z", 0.50, "1", "yes"),
  ];
  const since = Date.parse("2026-11-21T00:01:00Z");
  check("old pair suppressed by cursor", KDLIVE.detectTapeSwings(trades, 0.10, { sinceMs: since }).length === 0);
  check("same pair fires without a cursor", KDLIVE.detectTapeSwings(trades, 0.10).length === 1);
}

console.log("E. malformed rows are ignored rather than guessed");
{
  const trades = [
    { trade_id: "x", created_time: "not-a-date", yes_price_dollars: "0.50" },
    { trade_id: "y", created_time: "2026-11-21T00:00:00Z", yes_price_dollars: "" },
    print("z1", "2026-11-21T00:00:00Z", 0.30, "1", "yes"),
    print("z2", "2026-11-21T00:01:00Z", 0.40, "1", "yes"),
  ];
  const sw = KDLIVE.detectTapeSwings(trades, 0.10);
  check("only the two clean prints pair up", sw.length === 1 && sw[0].from_trade_id === "z1");
}

console.log(fail ? `\nFAILED: ${fail} check(s)` : `\nOK: ${pass} trade-tape alert checks passed.`);
process.exit(fail ? 1 : 0);
