/* Node harness for the browser/CI parity test. Not part of the site.
 *
 * Loads the SAME module the page loads (assets/live.js), runs its scoring and swing
 * detector over scripts/tests/fixtures_roi_parity.json and prints the result as JSON, so
 * scripts/tests/test_roi_parity.py can compare it against scripts/roi_model.py.
 *
 * Run: node scripts/tests/parity_node.js scripts/tests/fixtures_roi_parity.json
 */
"use strict";

const fs = require("fs");
const path = require("path");
const KDLIVE = require(path.join(__dirname, "..", "..", "assets", "live.js"));

const fixturePath = process.argv[2] || path.join(__dirname, "fixtures_roi_parity.json");
const modelPath = process.argv[3] || path.join(__dirname, "..", "..", "data", "roi_model.json");

const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const model = JSON.parse(fs.readFileSync(modelPath, "utf8"));

const scores = fixture.cases.map((c) => KDLIVE.score(c.market, model, c.book, c.ctx));
const swings = KDLIVE.detectSwings(fixture.swings.observations, fixture.swings.threshold);
const catalysts = fixture.cases.map((c) => KDLIVE.catalystLinks(c.market));
const fees = [];
for (const p of [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5,
                 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99]) {
  fees.push([p, KDLIVE.takerFee(1, p, 1), KDLIVE.takerFee(100, p, 1), KDLIVE.makerFee(100, p, 1)]);
}

process.stdout.write(JSON.stringify({ scores, swings, catalysts, fees }, null, 1));
