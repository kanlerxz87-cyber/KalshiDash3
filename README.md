# KalshiDash3

Kalshi DEMO market dashboard: gas prices, elections, culture, crypto, and golf.

- **Live site:** https://kanlerxz87-cyber.github.io/KalshiDash3/ (GitHub Pages, `main` branch, `/` root)
- **Executive summary:** [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md)
- **Data:** [data/dashboard.json](data/dashboard.json). Values copied from the Kalshi DEMO API (`https://external-api.demo.kalshi.co/trade-api/v2`); blanks are unverified.
- **Coordination board:** [COORDINATION.md](COORDINATION.md)
- **Flagged for review:** [flagged.html](flagged.html) on the site.

Static site, no build step. Pages: `index.html`, `categories/*.html`, `live.html`, `portfolio.html`, `analysis.html`, `questions.html`, `suggestions.html`, `flagged.html`, `sources.html`. Scripts: `assets/app.js` (tables), `assets/live.js` (chart, public endpoints only).

Not investment advice. Demo prices may not reflect real markets (see Kalshi's [demo environment docs](https://docs.kalshi.com/getting_started/demo_env.md)).
