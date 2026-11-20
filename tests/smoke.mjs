import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
const js = await readFile(new URL('../app.js', import.meta.url), 'utf8');
const css = await readFile(new URL('../styles.css', import.meta.url), 'utf8');
const readme = await readFile(new URL('../README.md', import.meta.url), 'utf8');

for (const asset of ['styles.css', 'app.js']) assert.ok(html.includes(asset), `index.html must load ${asset}`);
for (const route of ['dashboard', 'markets', 'portfolio', 'analysis', 'questions', 'suggestions', 'review', 'sources']) {
  assert.ok(js.includes(`'${route}'`) || js.includes(`\"${route}\"`), `missing route ${route}`);
}
for (const topic of ['gas', 'elections', 'culture', 'crypto', 'golf']) assert.ok(js.includes(`${topic}: {label:`), `missing topic ${topic}`);
assert.ok(js.includes('https://external-api.demo.kalshi.co/trade-api/v2'), 'must use the documented demo REST host');
assert.ok(js.includes('/markets?${params.toString()}'), 'must request market listings');
assert.ok(js.includes('/orderbook'), 'must request orderbook levels');
assert.ok(js.includes('DOCS.markets'), 'market rows must link to field documentation');
assert.ok(js.includes('sourceMarketURL(m.ticker)'), 'each market row must link to its official API resource');
assert.ok(js.includes('DOCS.orderbook'), 'orderbook rows must link to official field documentation');
assert.ok(js.includes('create-order-v2'), 'must reference the current V2 order documentation');
assert.ok(js.includes('https://docs.kalshi.com/getting_started/market_lifecycle'), 'must link resolution/lifecycle documentation');
assert.ok(!js.includes('api-reference/portfolio/create-order'), 'must not link the obsolete legacy create-order route');
assert.ok(js.includes('No API keys are requested, stored, or embedded'), 'must disclose that static client has no private credentials');
assert.ok(js.includes('Metric definition unresolved · ranking disabled'), 'must leave dollar-volume ranking unverified');
assert.ok(js.includes('No ask levels are inferred or synthesized'), 'must not fabricate ask depth');
assert.ok(css.includes('@media(max-width:700px)'), 'must have a mobile layout');
assert.ok(readme.includes('Flagged for review') && readme.includes('Official sources checked'), 'README must include review flags and official sources');
console.log('Static dashboard smoke checks passed.');
