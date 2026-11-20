#!/usr/bin/env node
// Checks the built site and the data behind it. Exits non-zero on any failure.
//  1. Every data file parses as JSON.
//  2. Every table row has an https API source link and a verification status.
//  3. Every flag ID referenced in data exists in flagged.json.
//  4. Every internal link and #anchor in docs/*.html resolves to a real file or id.
//  5. No 'undefined' or 'NaN' leaked into the HTML.
// External links are checked for https only (no network access needed).
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { dirname, join, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const DOCS = join(ROOT, "docs", "e1b4fe16");
let failures = 0;
const fail = (msg) => { failures++; console.error("FAIL: " + msg); };
const ok = (msg) => console.log("ok:   " + msg);

// 1. JSON
const dataFiles = ["data/e1b4fe16/snapshot.json", "data/e1b4fe16/flagged.json", "data/e1b4fe16/questions.json", "data/e1b4fe16/suggestions.json", "data/e1b4fe16/sources.json"];
const data = {};
for (const f of dataFiles) {
  try { data[f] = JSON.parse(readFileSync(join(ROOT, f), "utf8")); ok(f + " parses"); }
  catch (e) { fail(f + " is not valid JSON: " + e.message); }
}
const snap = data["data/e1b4fe16/snapshot.json"];
const flagged = data["data/e1b4fe16/flagged.json"];
const flagIds = new Set((flagged?.items || []).map((i) => i.id));
const httpsOk = (u) => typeof u === "string" && /^https:\/\//.test(u);

// 2 & 3. Rows and flags
if (snap) {
  const rows = [...(snap.rows || []), ...(snap.series || [])];
  for (const r of rows) {
    const label = r.ticker || "(no ticker)";
    if (!httpsOk(r.source_url)) fail(`${label}: source_url missing or not https`);
    if (!snap.verified_on) fail("snapshot.verified_on missing");
    if (r.official_url && !httpsOk(r.official_url)) fail(`${label}: official_url not https`);
    if (r.terms_url && !httpsOk(r.terms_url)) fail(`${label}: terms_url not https`);
    if (!r.official_url && !r.terms_url && !(r.flags || []).includes("U5")) fail(`${label}: no official or terms reference and no U5 flag`);
    if (r.official_url && r.official_opened === false && !(r.flags || []).length) fail(`${label}: official reference not opened but no flag`);
    for (const id of r.flags || []) if (!flagIds.has(id)) fail(`${label}: unknown flag ${id}`);
  }
  ok(`${rows.length} table rows checked (source links, references, flags)`);
  const ids = (flagged?.items || []).map((i) => i.id);
  if (new Set(ids).size !== ids.length) fail("duplicate flag ids");
  for (const it of flagged?.items || []) for (const s of it.sources || []) if (!httpsOk(s.url)) fail(`flag ${it.id}: non-https source ${s.url}`);
  ok(`${ids.length} flag items checked`);
}
for (const f of ["data/e1b4fe16/questions.json", "data/e1b4fe16/suggestions.json", "data/e1b4fe16/sources.json"]) {
  if (!data[f]) continue;
  for (const it of data[f].items || []) for (const s of it.sources || []) {
    const u = s.url;
    if (u && !httpsOk(u)) fail(`${f} ${it.id || ""}: non-https ${u}`);
  }
}
if (data["data/e1b4fe16/suggestions.json"]) {
  for (const s of data["data/e1b4fe16/suggestions.json"].items) for (const q of s.depends_on || []) {
    if (!(data["data/e1b4fe16/questions.json"]?.items || []).some((x) => x.id === q)) fail(`suggestion ${s.id} depends on unknown question ${q}`);
  }
  ok("suggestion dependencies resolve");
}

// 4 & 5. HTML
function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : p.endsWith(".html") ? [p] : [];
  });
}
if (!existsSync(DOCS)) { fail("docs/ folder missing: run node scripts/e1b4fe16/build-site.mjs"); }
else {
  const pages = walk(DOCS);
  const idsByFile = new Map();
  for (const p of pages) {
    const html = readFileSync(p, "utf8");
    idsByFile.set(p, new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])));
  }
  for (const p of pages) {
    const html = readFileSync(p, "utf8");
    const rel = relative(ROOT, p);
    if (/\bundefined\b|\bNaN\b/.test(html.replace(/<script[\s\S]*?<\/script>/g, ""))) fail(`${rel}: contains 'undefined' or 'NaN'`);
    for (const m of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
      const link = m[1];
      if (/^(mailto:|javascript:|data:)/.test(link)) continue;
      if (/^https?:\/\//.test(link)) {
        if (!link.startsWith("https://")) fail(`${rel}: non-https external link ${link}`);
        continue;
      }
      const [pathPart, anchor] = link.split("#");
      const target = pathPart === "" ? p : resolve(dirname(p), pathPart.split("?")[0]);
      if (pathPart && pathPart.split("?")[0] && !existsSync(target)) { fail(`${rel}: broken link ${link}`); continue; }
      if (anchor) {
        const ids = idsByFile.get(target) || new Set();
        if (!ids.has(anchor)) fail(`${rel}: missing anchor #${anchor} in ${relative(ROOT, target)}`);
      }
    }
  }
  ok(`${pages.length} HTML pages checked for internal links, anchors and leaked values`);
}

if (failures) {
  console.error(`\n${failures} check(s) failed.`);
  process.exit(1);
}
console.log("\nAll site checks passed.");
