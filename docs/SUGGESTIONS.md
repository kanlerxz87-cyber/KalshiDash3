# Suggestions — Improving Decision-Making

These suggestions are proposals for improving the KalshiDash3 dashboard and the trading
decisions it supports. They are collected here so they can be reviewed and the best path chosen
**before** any change is implemented. Each suggestion states the problem it addresses, the
proposed change, the information needed to decide, and the risk.

## S1 — Resolve the category mapping before relying on topic filtering

- **Problem:** The mapping of Kalshi `series_ticker`s to the five topics (gas, elections,
  culture, crypto, golf) is currently a *proposed* keyword mapping and is unverified.
- **Proposed change:** Publish the confirmed mapping to `data/categories.json` after
  pulling the live series list. Until then, clearly badge any auto-assigned category as
  "proposed".
- **Information needed:** The authoritative series list per topic (see
  [`QUESTIONS_AND_GAPS.md`](QUESTIONS_AND_GAPS.md) B1).
- **Risk:** Low implementation cost; high value — wrong categories misdirect strategy.

## S2 — Add a backend proxy if browser CORS blocks trading

- **Problem:** Browser-direct calls to `/portfolio/*` may be blocked by Kalshi's CORS policy
  (unverified). If blocked, trade execution and portfolio reads cannot work from a static
  GitHub Pages site.
- **Proposed change:** Deploy a minimal proxy (GitHub Actions on a schedule, or a small
  serverless function) that forwards Kalshi requests with the API key held as a secret. The
  frontend calls the proxy with relative URLs.
- **Information needed:** Confirm CORS behavior (B2). Confirm the proxy host and secret
  storage approach.
- **Risk:** Adds moving parts and a secret; required only if CORS is restricted.

## S3 — Use WebSocket push for the "seconds" view and order book

- **Problem:** The "seconds" price view and live order book currently poll the REST API.
  Polling adds latency and extra requests.
- **Proposed change:** Subscribe to Kalshi's WebSocket (`wss://…/trade-api/ws/v2`) for
  price and order-book updates once the subscription schema is verified.
- **Information needed:** The verified WS channel/subscription format (B10).
- **Risk:** Medium — depends on WS schema verification; fallback to polling remains.

## S4 — Add a proper dollar-volume metric (or confirm none exists)

- **Problem:** "Highest dollar amount" events cannot be ranked directly because Kalshi has no
  dollar-amount field; the current estimate is `volume_24h × last_price`.
- **Proposed change:** Confirm with Kalshi whether a notional/dollar field exists (event
  metadata, settlement value, etc.). If none exists, keep the clearly-labeled estimate and add
  a secondary rank by `volume` and by open interest if exposed.
- **Information needed:** Confirmation of any dollar/notional field (B4).
- **Risk:** Low — improves ranking accuracy and user trust.

## S5 — Categorize and score trades for strategy analysis

- **Problem:** Trades need to be grouped into strategies to analyze performance.
- **Proposed change:** Extend the portfolio page to tag each fill/position with (topic, side,
  action, horizon) and compute per-strategy metrics: count, win rate, realized PnL, fees, and
  return on cost. Add a simple strategy comparison table.
- **Information needed:** Confirm fee/settlement rules (B6) for accurate PnL.
- **Risk:** Low — pure analytics; high value for "create strategies".

## S6 — Add risk limits and order guards

- **Problem:** Automated/one-click trading can exceed position caps or margin.
- **Proposed change:** Enforce max order size and max position checks using `cap_count` and the
  demo balance before submitting orders; surface warnings.
- **Information needed:** Confirm cap/limit semantics (B8) and margin rules (B7).
- **Risk:** Low — reduces unintended risk.

## S7 — Persist snapshots for historical analysis

- **Problem:** The dashboard is live-only; historical comparison is limited.
- **Proposed change:** Periodically snapshot market state (price, volume, order book) and
  portfolio state to a data store, then add a history view and performance-over-time charts.
- **Information needed:** A storage backend (e.g., a GitHub Actions artifact or an external
  store); confirm retention and rate limits (B9).
- **Risk:** Medium — storage cost and complexity.

## S8 — Add a decision-support "review" workflow

- **Problem:** Suggestions and flagged items need a clear path from review to implementation.
- **Proposed change:** Add a lightweight status workflow to the Suggestions and Flagged pages
  (proposed → reviewed → accepted/rejected → implemented), so the best path is chosen before
  changes are made.
- **Information needed:** Nothing external — this is a product decision.
- **Risk:** Low.

## S9 — Verify and document fee/settlement rules

- **Problem:** PnL and strategy evaluation depend on fee and settlement rules that are not yet
  verified.
- **Proposed change:** Confirm the official fee schedule and settlement timing; encode them in
  the portfolio calculations and document them with a source link.
- **Information needed:** Kalshi official fee/settlement documentation (B6).
- **Risk:** Low — improves the accuracy of all performance analysis.

## S10 — Make polling cadence configurable and rate-limit-aware

- **Problem:** A fixed polling interval may violate Kalshi rate limits or miss moves.
- **Proposed change:** Expose the poll interval in settings and default to a conservative value;
  back off on rate-limit errors.
- **Information needed:** Kalshi rate-limit headers/documentation (B9).
- **Risk:** Low.

## Priority order for decision-making

1. **S1** (category mapping) and **S2** (CORS proxy) — unblock correct data and trading.
2. **S4** (dollar-volume) and **S9** (fee/settlement) — correctness of ranking and PnL.
3. **S5** (strategy scoring) — delivers the "create strategies" requirement.
4. **S3, S6, S7, S8, S10** — polish, latency, risk, history, and workflow.
