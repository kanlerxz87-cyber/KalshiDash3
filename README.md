# Kalshi Demo Market Research Dashboard

A GitHub Pages-compatible, read-only research interface for Kalshi demo markets in five requested topic areas: gas prices, elections, culture, crypto, and golf. The browser requests open and settled market listings directly from Kalshi's official demo Trade API. Market values are not hard-coded. Rows are source-linked to the corresponding demo API resource; unresolved values display as blank or unreported.

## Executive summary

- The repo initially contained only this project title and no app, market data, credentials, deployment configuration, or analysis. This implementation adds a static dashboard, decision checklist, suggestions queue, and flagged-review page.
- Official Kalshi docs list the recommended demo REST base `https://external-api.demo.kalshi.co/trade-api/v2` and also support `https://demo-api.kalshi.co/trade-api/v2`. This app uses the recommended external host. The docs describe unauthenticated public market-data requests.
- The UI polls open and settled listings, shows reported YES bid/size, YES ask size, and volume if returned, and provides open/resolved views. Topic groupings use transparent title/ticker keyword matching; these are not claimed to be Kalshi's official topic taxonomy.
- **Volume and quoted sizes are contract counts, not dollar amounts.** The market schema also includes `notional_value_dollars`, but the checked schema does not establish that it is event-level traded-dollar volume. No dollar-volume ranking is asserted until the requested measure and its semantics are confirmed.
- Price chart snapshots are collected in the active browser session only. It is not a persistent historical feed. The official candlestick endpoint documents 1-, 60-, and 1440-minute periods; fine-grained seconds history is not claimed.
- Portfolio data and trading are intentionally not connected. Private API calls require signed authentication; a private signing key must not be placed in a public browser bundle. Balances/P&L remain blank, and no trade can be submitted by this static site.
- Open questions and unverified assumptions are listed in the dashboard's **Decision checklist** and **Flagged for review** sections.

## Run locally

Serve the repository root with any static file server, for example:

```sh
python3 -m http.server 8080
```

Open `http://localhost:8080`. Browser access to the demo API depends on the API's current network/CORS behavior. If unavailable, the page reports the failure and does not fabricate values.

## GitHub Pages

`.github/workflows/pages.yml` publishes the static site from `main` using GitHub Actions. In the repository settings, set **Pages → Build and deployment → Source** to **GitHub Actions**. The deploy will run after changes reach `main` or from the Actions workflow-dispatch control. No build step or secrets are required for public market data. Private account access must not be added to this workflow as a static secret exposed to client-side code.

## Official sources checked

| Subject | First-party Kalshi source |
|---|---|
| Demo/production API environments | [API Environments](https://docs.kalshi.com/getting_started/api_environments) |
| Public market data and orderbook example | [Quick Start: Market Data](https://docs.kalshi.com/getting_started/quick_start_market_data) |
| Market fields, filters, pagination | [Get Markets](https://docs.kalshi.com/api-reference/market/get-markets) |
| Market lifecycle, determination, and settlement | [Market Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) |
| Raw orderbook bid levels | [Get Market Orderbook](https://docs.kalshi.com/api-reference/market/get-market-orderbook) |
| Candlestick periods and fields | [Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) |
| WebSocket demo connection and authentication | [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) |
| Account balance and signing headers | [Get Balance](https://docs.kalshi.com/api-reference/portfolio/get-balance) |
| Positions and fills | [Get Positions](https://docs.kalshi.com/api-reference/portfolio/get-positions) · [Get Fills](https://docs.kalshi.com/api-reference/portfolio/get-fills) |
| Current order endpoint (not used) | [Create Order (V2)](https://docs.kalshi.com/api-reference/orders/create-order-v2) |
| API key signing | [API Keys](https://docs.kalshi.com/getting_started/api_keys) |

See `COORDINATION.md` for the task log and verification record. See the dashboard's **Flagged for review** page for operational and evidence limitations.
