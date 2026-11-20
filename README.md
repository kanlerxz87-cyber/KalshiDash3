# KalshiDash3

Live analytics dashboard for the **Kalshi demo** prediction-market API: full-list requirements capture, market monitoring, portfolio tracking and trade analysis.

| What | Where |
| --- | --- |
| Published site (GitHub Pages) | <https://kanlerxz87-cyber.github.io/KalshiDash3/> |
| Site source | `docs/` (plain HTML/CSS/JS, no build step) |
| Executive summary | `docs/executive-summary.html` |
| API verification, line by line | `docs/verification/api-verification.md` |
| Collector / API library / trading CLI | `tools/` |
| Agent session task board | [COORDINATION.md](COORDINATION.md) |

Data source: Kalshi demo REST Trade API v2, `https://external-api.demo.kalshi.co/trade-api/v2` (alternate: `https://demo-api.kalshi.co/trade-api/v2`), per the official demo-environment page <https://docs.kalshi.com/getting_started/demo_env>.

All trading on the site is **simulated paper trading** against live demo quotes. Nothing here places real orders, and no production endpoint is used. Real order placement is available through `tools/kalshi-trade.mjs`, which needs your own demo API key (see `docs/questions.html`).
