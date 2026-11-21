/* KalshiDash3 — verification page render test (jsdom, no network).

 * Why this exists (T57, arena-220b524c):
 *   verification.html claims "every static claim links to an official source".
 *   Nothing tested that the page's *citation-integrity* table actually rendered.
 *   A typo in the render path, a renamed JSON key, or a hand-edited row would
 *   have shown an empty section on the live site while every other check passed
 *   — the exact failure this page is supposed to make impossible.
 *
 * What it asserts:
 *   1. data/verified_facts.json still carries doc_links, and every row has the
 *      fields the page reads (id, url, page_title, in_official_index, cited_times)
 *   2. every cited URL is https and on docs.kalshi.com — a source link must be
 *      the vendor's own page, never a search result or a mirror
 *   3. ids are unique and the per-URL citation count is an integer >= 0
 *   4. the page renders one <tr> per row, shows the "resolves" badge for
 *      verified rows, and leaks no "undefined"/"NaN"
 *
 * Run: node scripts/tests/test_verification_links.js
 */
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");

let JSDOM;
try { ({ JSDOM } = require("jsdom")); }
catch (e) { console.log("SKIP: jsdom is not installed (npm i jsdom)."); process.exit(0); }

let failures = 0;
const ok = (m) => console.log("  ok   " + m);
const bad = (m) => { failures++; console.log("  FAIL " + m); };
const check = (c, m) => (c ? ok(m) : bad(m));

const FACTS = JSON.parse(fs.readFileSync(path.join(ROOT, "data/verified_facts.json"), "utf8"));

function inlineAssets(html) {
  return html.replace(/<script src="([^"]+)"><\/script>/g, (m, src) => {
    const file = path.join(ROOT, src.replace(/^\.\//, ""));
    if (!fs.existsSync(file)) throw new Error("test cannot find " + src);
    return "<script>\n" + fs.readFileSync(file, "utf8") + "\n</script>";
  });
}

(async () => {
  console.log("A — data file shape");
  const links = FACTS.doc_links;
  check(Array.isArray(links) && links.length > 0, `doc_links present (${links ? links.length : 0} rows)`);
  if (!Array.isArray(links) || !links.length) {
    console.log("\nFAILED: no doc_links to check");
    process.exit(1);
  }
  const required = ["id", "url", "page_title", "in_official_index", "cited_times", "verified"];
  const missing = links.flatMap((r, i) => required.filter(k => !(k in r)).map(k => `row ${i} missing ${k}`));
  check(missing.length === 0, `every row carries the fields the page reads${missing.length ? ": " + missing.slice(0, 4).join("; ") : ""}`);

  console.log("\nB — every source link is Kalshi's own documentation");
  const badHost = links.filter(r => !/^https:\/\/docs\.kalshi\.com\/[a-z0-9_\-/]+$/.test(r.url || ""));
  check(badHost.length === 0,
        `all ${links.length} URLs are https://docs.kalshi.com/…${badHost.length ? ": " + badHost.slice(0, 3).map(r => r.url).join(", ") : ""}`);
  check(links.every(r => r.url.endsWith(".md") === false),
        "no row points at the raw .md form of a page (readers get HTML, not source)");

  console.log("\nC — ids and citation counts");
  const ids = links.map(r => r.id);
  check(new Set(ids).size === ids.length, "row ids are unique");
  check(links.every(r => Number.isInteger(r.cited_times) && r.cited_times >= 0),
        "cited_times is a non-negative integer on every row");
  // At least one link must actually be cited, or the table is decorative.
  check(links.some(r => r.cited_times > 0), "at least one row records a real citation");

  console.log("\nD — the page renders it");
  const html = inlineAssets(fs.readFileSync(path.join(ROOT, "verification.html"), "utf8"));
  const errors = [];
  const dom = new JSDOM(html, {
    url: "https://kalshidash3.invalid/verification.html",
    runScripts: "dangerously",
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = async (url) => {
        const file = path.join(ROOT, String(url).split("?")[0]);
        try {
          const body = JSON.parse(fs.readFileSync(file, "utf8"));
          return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
        } catch (e) {
          return { ok: false, status: 404, json: async () => ({}), text: async () => "{}" };
        }
      };
      window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
      window.addEventListener("error", (ev) => errors.push(String(ev.message)));
    },
  });

  await new Promise(r => setTimeout(r, 900));
  const doc = dom.window.document;
  const host = doc.getElementById("docLinks");
  check(!!host, "#docLinks exists on the page");
  check(errors.length === 0, `no uncaught page errors${errors.length ? ": " + errors.slice(0, 2).join(" | ") : ""}`);
  const rows = host ? host.querySelectorAll("tbody tr").length : 0;
  check(rows === links.length, `rendered ${rows} rows for ${links.length} data rows`);
  const badges = host ? host.querySelectorAll("tbody .badge.ok").length : 0;
  check(badges === links.filter(r => r.verified).length,
        `${badges} "resolves" badges for ${links.filter(r => r.verified).length} verified rows`);
  const text = host ? host.textContent : "";
  check(!/undefined|\bNaN\b|\[object Object\]/.test(text), "no undefined / NaN / [object Object] in the rendered table");
  check(/docs\.kalshi\.com/.test(text), "the table shows the documentation hostname");

  dom.window.close();
  console.log("");
  if (failures) { console.log(`FAILED: ${failures} check(s)`); process.exit(1); }
  console.log("OK: verification citation table — data, hosts, ids and render all verified.");
  process.exit(0);
})();
