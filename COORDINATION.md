# KalshiDash3 — Coordination Board

Shared task board for parallel agent sessions. Each session works on its own branch
(`session-<id>/<task>`) and edits only the files in its claimed scope. Do not start a
task another session has claimed. Make small, frequent commits; run `git pull --rebase`
before every push. If a claim is more than 60 minutes old with no commits, another
session may take over and note the handoff here.

## Session claiming this board
- Session ID: `arena/796e8144-kalshidash3` (branch `arena/796e8144-kalshidash3`, branched from
  `49ba7bce3112e9e0b4c7534af961e1d0ef8d19ff` of `main`)

## Tasks

| # | Task | Status | Owner | Files touched | Sources / verification | Notes |
|---|------|--------|-------|---------------|------------------------|-------|
| 1 | Repo review: inspect existing files, flag irregularities, create COORDINATION.md | done | arena/796e8144-kalshidash3 | COORDINATION.md, README.md | — | Repo contained only README.md placeholder |
| 2 | Kalshi API official-source research & verification links | done | arena/796e8144-kalshidash3 | All *.html pages | https://external-api.demo.kalshi.co/trade-api/v2 , https://demo-api.kalshi.co/trade-api/v2 | Sandbox cannot reach kalshi.co (outbound limited to GitHub hosts/package registries). Source links embedded in every page; no separate api-sources.md created. All Kalshi values flagged unverified |
| 3 | Dashboard site: landing page + navigation | done | arena/796e8144-kalshidash3 | index.html, assets/style.css, assets/app.js | — | GitHub Pages static site; shared nav injected by app.js |
| 4 | Category subpages: gas prices, elections, culture, crypto, golf | done | arena/796e8144-kalshidash3 | gas-prices.html, elections.html, culture.html, crypto.html, golf.html | Kalshi trade API v2 (links only; values unverified) | One row per page, blank + unverified per verification rules |
| 5 | Price movement graph component | done | arena/796e8144-kalshidash3 | graph.html, assets/vendor/chart.umd.js | — | Chart.js v4.4.1 vendored from npm; X=time (seconds/minutes/hours), Y=contract price, bid/ask + liquidity sizes; live fetch attempted from browser, fallback placeholder |
| 6 | Portfolio performance tracking | done | arena/796e8144-kalshidash3 | portfolio.html | — | Template only; no API keys; flagged unverified |
| 7 | Trade categorization & strategy section | done | arena/796e8144-kalshidash3 | strategies.html | — | Suggestion frameworks only, not market data |
| 8 | Suggestions section | done | arena/796e8144-kalshidash3 | suggestions.html | — | Review-before-implement table |
| 9 | Questions / information / answers section | done | arena/796e8144-kalshidash3 | questions.html | — | Decision preconditions + missing-info discovery suggestions |
| 10 | Flagged for Review page | done | arena/796e8144-kalshidash3 | flagged-for-review.html | All pages link to it | 10 flagged items with official source links |
| 11 | Build verification: combined data re-verified line by line, no broken links | done | arena/796e8144-kalshidash3 | — | Local link check: all relative links OK | All values blank/unverified per rules; no values inferred |
| 12 | GitHub Pages enable + deploy + confirm deploy succeeds | needs integration | — | — | — | Awaiting Pages enable |
| 13 | PR creation (this branch -> main) + merge + record PR link & merge result here | needs integration | — | — | — | Flagged irregularities do not block merge |

## Rules
- Never infer or fill in values. If a value cannot be confirmed from an official source, leave it blank and mark "unverified".
- Every table row carries a source link to an official Kalshi site (kalshi.co trade API or event/market pages).
- Flagged irregularities and unverified items go on the "Flagged for Review" page.
- Do not stop for review; work fully on your own from start to finish.
