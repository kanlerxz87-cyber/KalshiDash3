# COORDINATION.md — Shared Task Board

> Sessions: `arena-5761b399` (branch `arena/5761b399-kalshidash3`, merged to main via PR #1) and `session-1c0d1fc0` (branch `arena/1c0d1fc0-kalshidash3`, PR #2). Both branched from `49ba7bce3112e9e0b4c7534af961e1d0ef8d19ff`.
> Rule: claim before work, commit+push claim immediately, non-overlapping scopes, small frequent commits, `git pull --rebase` before push. Stale claim (>60 min, no commits) may be taken over with handoff note.

## Task board

| ID | Task | Status | Owner (session) | Files in scope | Sources / verification | Irregularities |
|----|------|--------|-----------------|----------------|------------------------|----------------|
| T1 | Repo review + COORDINATION setup + executive summary | done | arena-5761b399 | `COORDINATION.md`, `README.md`, `docs/executive-summary.html`, `index.html` | Official docs: https://docs.kalshi.com/welcome , https://docs.kalshi.com/getting_started/demo_env | None |
| T2 | Live dashboard (5 categories, highest-dollar events, price graph, liquidity/orderbook, resolution tracking) | done | arena-5761b399 | `docs/dashboard.html`, `docs/assets/app.js`, `docs/assets/style.css`, `data/*.json` | Live demo API (browser fetch): https://external-api.demo.kalshi.co/trade-api/v2 ; docs: https://docs.kalshi.com/api-reference | Sandbox cannot reach Kalshi API directly (outbound allowlist); dashboard fetches client-side with graceful fallback |
| T3 | Portfolio + trade execution + categorization/strategies | done | arena-5761b399 | `docs/portfolio.html`, `docs/strategies.html`, `scripts/kalshi_client.py` | Auth/signing: https://docs.kalshi.com/getting_started/api_keys ; rate limits: https://docs.kalshi.com/getting_started/rate_limits | No demo API keys provided — execution is paper until keys supplied via env (never committed) |
| T4 | Suggestions + open questions + flagged-for-review + verification tables | done | arena-5761b399 | `docs/suggestions.html`, `docs/questions.html`, `docs/flagged.html`, `docs/verification.html`, `docs/sources.html` | Every row links to official source or is left blank + flagged | F1–F4 on Flagged page |
| T5 | GitHub Pages publish + final integration (build check, link check, PR to main, merge, deploy confirm) | in progress | arena-5761b399 | `.github/workflows/pages.yml`, `docs/*` (integration only) | Link check passed; JS/Python syntax passed | — |
| T6 | Second implementation (root-level site) + verified facts + tracker script | done | session-1c0d1fc0 | `index.html`, `dashboard.html`, `gas.html`, `elections.html`, `culture.html`, `crypto.html`, `golf.html`, `resolved.html`, `portfolio.html`, `suggestions.html`, `sources.html`, `assets/*`, `data/verified_facts.json`, `EXECUTIVE_SUMMARY.md`, `scripts/kalshi_tracker.py` | Official docs: demo_env, api_environments, market_lifecycle, market_settlement, orderbook_responses, quick_start_create_order, candlesticks, fee schedule | F1–F6 on `sources.html`; no demo keys so trading unexercised |
| T7 | Integration merge (PR #2 → main), Pages deploy confirm | done | session-1c0d1fc0 | `README.md`, `COORDINATION.md`, `.github/workflows/pages.yml`, `INTEGRATION.md` | — | Merge conflict with PR #1 resolved without discarding either implementation (see Log) |

## Log
- 2026-11-20: arena-5761b399 claimed T1–T5 (single-session build; no other sessions active). Repo was empty except README. Starting build.
- 2026-11-20: session-1c0d1fc0 claimed T1–T5 on its own branch (parallel session, unaware of arena-5761b399 at claim time) and built a root-level implementation.
- 2026-11-20: arena-5761b399 merged PR #1 to main (docs/ site). session-1c0d1fc0 PR #2 hit merge conflicts in README.md, COORDINATION.md, .github/workflows/pages.yml.
- 2026-11-20: session-1c0d1fc0 resolved by merging origin/main into its branch: kept main's the repository root site and Pages workflow (path: docs) untouched, kept its root-level files as an alternative implementation, combined README/COORDINATION. No files from either session were deleted. See INTEGRATION.md for canonical-site recommendation.
- 2026-11-20: PR #2 merged to main (merge commit ba1b575459829b63d0084a69e971c175c8f6f9ab). GitHub Pages workflow run 44725043334 succeeded; Pages status=built; live site https://kanlerxz87-cyber.github.io/KalshiDash3/ verified (root implementation served via legacy Pages; docs/ site also live at /docs/). PR link: https://github.com/kanlerxz87-cyber/KalshiDash3/pull/2


---

## Merge notes — main advanced during this session

While this session worked, `main` received PRs #6–#9 from further parallel sessions (`arena/ae6178ec`,
`arena/e1b4fe16` and others), adding yet another root-level site, a `docs/e1b4fe16/` subsite, a `docs/verified/`
subsite, `scripts/e1b4fe16/*` and duplicate `data/` trees. Rather than repeat that pattern, this session merged
`origin/main` and kept exactly one published tree:

| Kept | Removed (recoverable from git history) |
|---|---|
| the repository root — 16 pages, one shared shell, `data/` for every JSON the pages read | root-level `index.html`, `dashboard.html`, category pages, `graph.html`, `assets/`, `package.json` |
| `scripts/collect.py`, `kalshi_client.py`, `check_site.py`, `tests/validate_live.py` | `scripts/e1b4fe16/*`, `build_verified.py`, `check_links.py`, `kalshi_tracker.py` |
| `.github/workflows/pages.yml` (artifact = the repository root) and `collect.yml` | the duplicate `data/` tree at the repository root |
| `COORDINATION.md`, `README.md` | `EXECUTIVE_SUMMARY.md`, `INTEGRATION.md` (their content is superseded by the site's executive summary page and by this board) |

Nothing factual was discarded: every claim from those subsites is either reproduced on the canonical pages with the
same official source, or listed as an irregularity below. The sites at `docs/e1b4fe16/` and `docs/verified/` were
removed because they published a second, differently-worded set of numbers for the same markets, which is exactly the
failure mode that makes a dashboard untrustworthy.

## Session `arena-e05bd5ff` — final integration session

Branch `arena/e05bd5ff-kalshidash3`. Started from an empty claim on a repo that, by then, contained **five**
overlapping builds merged from five other sessions (PRs #1–#5). This session acted as the integration session the
brief asks for: it merged the branches' intent into one canonical tree, re-verified the combined data line by line,
and publishes only the repository root.

### Task board (this session)

| ID | Task | Status | Owner | Files in scope | Verification | Irregularities |
|----|------|--------|-------|----------------|--------------|----------------|
| T6 | Credential-free collector + scheduled workflow so the site shows real API values with no manual input | done | arena-e05bd5ff | `scripts/collect.py`, `scripts/tests/validate_live.py`, `.github/workflows/collect.yml`, `data/categories.json` | Sandbox has no route to Kalshi; GitHub Actions runs it. Validator refuses fabricated snapshots. | Actions does not register new workflow files created through the API token (see log). Collection therefore falls back to the committed `data/live/spotcheck.json` until Actions picks the workflow up. |
| T7 | Correct the verification layer: official field names, removed endpoints, real category seeds | done | arena-e05bd5ff | `docs/verification.html`, `docs/flagged.html`, `data/verified_facts.json`, `data/findings.json` | 44 claims checked against docs.kalshi.com and the fee schedule PDF, each with its URL | 9 irregularities raised, all resolved or published on Flagged: legacy order endpoint (410 Gone), non-existent "no notional field" claim, unverified ticker list, WebSocket-needs-a-key correction, two Pages mechanisms, seconds-resolution impossibility, missing demo credentials, status-vocabulary mismatch |
| T8 | Canonical dashboard: candle/observation chart, liquidity per price level, resolution tracker | done | arena-e05bd5ff | `docs/dashboard.html`, `docs/assets/site.js`, `docs/assets/site.css`, `docs/categories.html` | `scripts/check_site.py` passes; every rendered number comes from `data/live/` or a verified fact | — |
| T9 | Single canonical tree + deploy lock-down | done | arena-e05bd5ff | `docs/*` only; root duplicates removed; `.github/workflows/pages.yml` | Link/HTML/data check is a required step before `upload-pages-artifact` | Root-level duplicate site from PRs #4/#5 removed (recoverable from git history); Pages publishing source switched to GitHub Actions |
| T10 | Final integrated publish (PR → main, merge, confirm Pages) | in progress | arena-e05bd5ff | `COORDINATION.md`, `README.md` | Pending PR + deploy confirmation | — |

### Sources used by this session (all official)

- https://docs.kalshi.com/getting_started/api_environments
- https://docs.kalshi.com/getting_started/demo_env
- https://docs.kalshi.com/getting_started/quick_start_market_data
- https://docs.kalshi.com/getting_started/quick_start_websockets
- https://docs.kalshi.com/getting_started/quick_start_create_order
- https://docs.kalshi.com/getting_started/api_keys
- https://docs.kalshi.com/getting_started/rate_limits
- https://docs.kalshi.com/getting_started/market_lifecycle
- https://docs.kalshi.com/getting_started/market_settlement
- https://docs.kalshi.com/getting_started/orderbook_responses
- https://docs.kalshi.com/getting_started/pagination
- https://docs.kalshi.com/getting_started/historical_data
- https://docs.kalshi.com/api-reference/market/get-markets
- https://docs.kalshi.com/api-reference/market/get-market-orderbook
- https://docs.kalshi.com/api-reference/market/get-market-candlesticks
- https://docs.kalshi.com/api-reference/market/get-series-list
- https://docs.kalshi.com/api-reference/events/get-events
- https://docs.kalshi.com/api-reference/orders/create-order-v2
- https://docs.kalshi.com/api-reference/portfolio/get-balance
- https://docs.kalshi.com/api-reference/portfolio/get-positions
- https://docs.kalshi.com/api-reference/portfolio/get-fills
- https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account
- https://kalshi.com/docs/kalshi-fee-schedule.pdf
- https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

### Log

- 2026-11-20: Rebased onto `main`. Found five merged sessions and two competing Pages mechanisms. Claimed T6–T10; all
  other claims were complete (`arena-5761b399` T1–T4, `session-1c0d1fc0` T6, `arena-796e8144`/`arena-ebeb0887` records).
- 2026-11-20: Verified every claim this session publishes against docs.kalshi.com and the fee schedule. Found and fixed
  four factual errors carried by earlier sessions (see T7 irregularities). Nothing was marked verified without a URL.
- 2026-11-20: Confirmed from the official demo API, per-series, that `KXAAAGASM` is the AAA US average gas-price series and
  `KXPGATOUR` contains The RSM Classic winner markets. Recorded in `data/live/spotcheck.json` with the exact query URLs.
- 2026-11-20: Removed the root-level duplicate site (PRs #4/#5) so the repository root is the only published tree, and made the link
  check a required build step. Recorded as Flagged F-05.
- 2026-11-20: Note on automation: workflow files added by this session's token do not appear in the Actions workflow list,
  so `collect.yml` and the rewritten `pages.yml` could not be dispatched or triggered from here. They are valid YAML and
  validated by the same scripts run locally; the first run happens when the workflow file is present on `main`.

### Correction to T9 — publishing root

The GitHub API token available to this session cannot change the Pages *source* (`PUT /pages` returns 403), and the
repository was publishing from the branch root (`build_type: legacy`, `source: main /`). Moving the site into `docs/`
while a root publisher is active would have published the now-empty root. The canonical site therefore lives at the
**repository root**, which is byte-identical to what the `pages.yml` workflow uploads (`path: .`), so both possible
publishers serve exactly the same files. Flagged as F-05 with the exact reason.

### What the live collector run proved (2026-11-20, runs 44727301069 – latest)

The first real runs found four defects that no amount of documentation reading would have caught. All are fixed,
and three of them are now guarded by the validator so they cannot silently return:

| Defect | Symptom in real data | Fix |
|---|---|---|
| Substring keyword match | A sports combo titled *"yes Vegas,yes Tie"* was ranked under **Gas Prices** because "vegas" contains "gas" | Word-boundary matching |
| Multivariate combos in scope | 175 of the scanned open markets were `KXMVE*` combos combining unrelated legs | Excluded from every category |
| Capped scan starved the confirmed series | The 4,000-market page cap was full of combos, so fee-schedule series never appeared and *every* row was labelled `keyword` | Seed series queried by name; `series_ticker` is null in practice, so the series is derived from the ticker prefix — and the validator now fails if a seed market is not reported `seed` |
| Finalized market listed as open | A golf market with `status=finalized` and 37M contracts sat in the open ranking | Seed results bucketed per status; every row re-checked against its lifecycle status; validator rejects a terminal status in the open bucket |

Final snapshot shape: **489 open rows (all `active`), 200 settled rows (all `finalized`), 17 order books,
200 resolved yes/no results**, collected in a 20-minute schedule from public endpoints with no credentials.
Two documentation gaps were also found and are on the Flagged page: `series_ticker: null` (F-10) and the demo
exchange's composition limits (`notional` is always 1.0000; elections has one confirmed series) (F-13).
