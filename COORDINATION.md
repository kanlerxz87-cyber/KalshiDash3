# COORDINATION — KalshiDash3

Shared task board for all agent sessions working on this repo. **Read this before touching any file.**

Rules in force (from the project brief):

1. Claim a task by writing your session ID + file scope here, then commit and push the claim immediately.
2. Never start a task claimed by another session. If you need a file another session owns, log a request in the **Change requests** section instead of editing it.
3. Work on your own branch `session-<id>/<task>`, keep scopes non-overlapping, commit small and often, `git pull --rebase` before every push.
4. Shared outputs (`docs/data/*.json`, `docs/index.html`, `docs/assets/nav.js`, this file) are edited only by the final integration session.
5. On completion record sources, verification performed, and irregularities here and mark the task `done`. A claim older than 60 minutes with no commits may be taken over (note the handoff).
6. `needs review` = item is listed on the **Flagged for Review** page (`docs/flagged-for-review.html`). It never blocks work.

---

## Sessions

| Session ID | Branch | First seen | Status |
| --- | --- | --- | --- |
| `9b3ccf08` | `arena/9b3ccf08-kalshidash3` | 2026-11-20 11:10 UTC | active — full-stack + final integration |

No other session had claimed anything when this board was created at 2026-11-20 11:10 UTC (repo contained only a 13-byte `README.md`, single commit `49ba7bc`, only branch `main`). A single session therefore executes every task below and finishes as the integration session, as permitted by the brief. If another session appears, it should re-claim anything marked `in progress` whose last commit is older than 60 minutes and note the handoff here.

## Task board

| # | Task | Status | Owner | File scope |
| --- | --- | --- | --- | --- |
| T1 | Coordination board, repo skeleton, `.gitignore` | in progress | `9b3ccf08` | `COORDINATION.md`, `.gitignore`, `README.md` |
| T2 | Verify Kalshi demo API line by line against official docs + live responses | in progress | `9b3ccf08` | `docs/verification/**`, `docs/data/sources.json` |
| T3 | Collector + shared API library (`tools/collect.mjs`, `tools/kalshi-client.mjs`) | unclaimed | — | `tools/kalshi-client.mjs`, `tools/collect.mjs`, `tools/fixtures/**` |
| T4 | GitHub Actions data refresh (best-effort, non-blocking) | unclaimed | — | `.github/workflows/refresh-data.yml` |
| T5 | Static site shell: landing page, nav, styles, data loader | unclaimed | — | `docs/index.html`, `docs/assets/**` |
| T6 | Live dashboard: dollar-volume ranking, price chart (s/m/h), orderbook depth/liquidity | unclaimed | — | `docs/dashboard.html`, `docs/event.html`, `docs/assets/dashboard.js`, `docs/assets/event.js` |
| T7 | Topic subpages: gas prices, elections, culture, crypto, golf | unclaimed | — | `docs/topics/*.html`, `docs/assets/topics.js` |
| T8 | Portfolio + trade execution/analytics + strategy engine | unclaimed | — | `docs/portfolio.html`, `docs/trades.html`, `docs/strategies.html`, `docs/assets/portfolio.js`, `tools/kalshi-trade.mjs` |
| T9 | Suggestions, questions/missing-information, methodology, executive summary | unclaimed | — | `docs/suggestions.html`, `docs/questions.html`, `docs/methodology.html`, `docs/executive-summary.html` |
| T10 | Flagged-for-review page | unclaimed | — | `docs/flagged-for-review.html`, `docs/data/flags.json` |
| T11 | Integration: merge, re-verify combined data, link check, GitHub Pages publish, PR → main | unclaimed | — | all of the above |

## Change requests

_None yet._

## Log

- **2026-11-20 11:10 UTC — `9b3ccf08`** — Board created. Claims T1–T11 (no competing sessions). Branch `arena/9b3ccf08-kalshidash3` from `49ba7bce3112e9e0b4c7534af961e1d0ef8d19ff`.
