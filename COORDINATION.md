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
| 1 | Repo review: inspect existing files, flag irregularities, create COORDINATION.md | in progress | arena/796e8144-kalshidash3 | COORDINATION.md, README.md | — | Repo contains only README.md placeholder |
| 2 | Kalshi API official-source research & verification links (trade API v2 docs/endpoints) | unclaimed | — | docs/api-sources.md | https://external-api.demo.kalshi.co/trade-api/v2 , https://demo-api.kalshi.co/trade-api/v2 | Cannot fetch from kalshi.co from sandbox (outbound restricted); all data flagged unverified until user verifies |
| 3 | Dashboard site: landing page + navigation (clean, simple dashboard UI) | unclaimed | — | index.html, assets/ | — | GitHub Pages static site |
| 4 | Category subpages: gas prices, elections, culture, crypto, golf (tables, source links, unverified flags) | unclaimed | — | gas-prices.html, elections.html, culture.html, crypto.html, golf.html | Kalshi event/market pages (links only; values unverified) | One row per event/market; blank + "unverified" where unconfirmed |
| 5 | Price movement graph component (x-axis time: seconds/minutes/hours; y-axis contract price; liquidity/contracts available) | unclaimed | — | assets/graph.js, assets/graph.html | — | Client-side chart; live fetch attempted, fallback placeholder |
| 6 | Portfolio performance tracking (Kalshi demo account); trade results analysis | unclaimed | — | portfolio.html | — | Template only; no API keys available, flagged unverified |
| 7 | Trade categorization & strategy section (categorize trades, create strategies by trade type) | unclaimed | — | strategies.html | — | |
| 8 | Suggestions section (review suggestions, choose best path before implementing) | unclaimed | — | suggestions.html | — | |
| 9 | Questions / information / answers section (preconditions for decisions; missing-info discovery suggestions) | unclaimed | — | questions.html | — | |
| 10 | Flagged for Review page (irregularities + unverified items with source links) | unclaimed | — | flagged-for-review.html | — | Linked from every page |
| 11 | Build verification: combined data re-verified line by line, no broken links, site builds | needs integration | — | — | — | Integration session only |
| 12 | GitHub Pages enable + deploy + confirm deploy succeeds | needs integration | — | — | — | Do not merge a broken site |
| 13 | PR creation (integration -> main) + merge + record PR link & merge result here | needs integration | — | — | — | Flagged irregularities do not block merge |

## Rules
- Never infer or fill in values. If a value cannot be confirmed from an official source, leave it blank and mark "unverified".
- Every table row must carry a source link to an official site (kalshi.co trade API or event/market pages).
- Flagged irregularities and unverified items go on the "Flagged for Review" page.
- Do not stop for review; work fully on your own from start to finish.
