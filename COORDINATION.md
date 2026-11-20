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
| T12 | Persistent alert archive (`data/live/alerts_archive.json`, built by `scripts/build_alerts.py`) so swings survive market close; feeds the T11 alert streams | done | arena-5225610f | `scripts/build_alerts.py`, `data/alert_rules.json`, `data/live/alerts*.json`, `.github/workflows/collect.yml` (build step) | Derived only from `data/live/price_history.json` + `markets.json` (official demo API observations); `validate_live.py`, `check_site.py` | Dashboard does not yet read the archive (request R-1, see log). Causal news links not collected (F-15). ROI model not supplied (F-14). Scheduled collector had not fired (F-16). |

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
| T11 | Add sourced price-swing alert streams to the canonical dashboard (all alerts + transparent research shortlist) | done | arena-6d85f8f0 | `dashboard.html`, `assets/site.css`, `executive-summary.html` | `scripts/check_site.py`, `scripts/tests/validate_live.py`, `node --check`, and a Node fixture smoke test covering the exact 10¢ threshold, sub-threshold rejection, screen criteria, category filter, and source output all passed | GitHub Pages snapshot cadence is not tick-level live; the experimental shortlist is not a validated ROI model and no causal news links are claimed. |


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

### Session `arena-6d85f8f0` — alert feed enhancement

- Claim: T11; files touched: `dashboard.html`, `assets/site.css`, `executive-summary.html` (claim committed and pushed to the current Arena branch before implementation).
- Added two bounded, newest-first scrolling feeds that compare consecutive collected `last` prices and trigger only for absolute changes >= $0.10. Each alert links to the official Kalshi demo market API record. Category selection filters both feeds.
- The experimental screen is explicitly not an ROI model: only fee-schedule `seed` markets with positive official `volume_24h_fp` qualify, ordered by reported volume. No predicted-return or profitability claim is displayed.
- The browser rechecks the static snapshot every 60 seconds, but the scheduled collector runs every 20 minutes and the UI states this limitation; not tick-level streaming. No news-event causal links are asserted.
- Official sources used: https://docs.kalshi.com/api-reference/market/get-markets ; https://docs.kalshi.com/getting_started/quick_start_websockets ; https://docs.kalshi.com/api-reference/market/get-market-orderbook . Existing dashboard history provenance: GET /markets source above.
- Verification: `python3 scripts/check_site.py`, `python3 scripts/tests/validate_live.py`, `node --check` on the embedded dashboard script, plus a Node fixture smoke test for exact threshold, below-threshold behavior, experimental screen eligibility, category filtering, and source link output. All passed.
- Irregularities: the source set does not provide causal news/source URLs per price move; UI links the official market record and flags the absence of causal attribution. The 20-minute workflow cadence and absence of a validated ROI model are disclosed in the UI and executive summary.
- Pull request: https://github.com/kanlerxz87-cyber/KalshiDash3/pull/16 — merged by squash on 2026-11-20 13:18 UTC; merge commit `0a7067d3670489a1ec70415d1f23756722f75a7b`.
- Pages workflow: https://github.com/kanlerxz87-cyber/KalshiDash3/actions/runs/44743119261 — completed successfully (build + deploy). GitHub Pages API reports `status=built`, public URL https://kanlerxz87-cyber.github.io/KalshiDash3/ (publishing source `main /`). The deployed dashboard was fetched and verified to include both alert feeds and sources. The snapshot shown was 2026-11-20T11:33:33Z and correctly marked stale at verification time.
- Workflow warning: GitHub reports Node.js 20 action deprecation annotations for pinned `@v4/@v5` actions; run still succeeded and this did not block deployment.

### Session `arena-5225610f` — overlap with T11 (resolved, see note)

- 2026-11-20: arena-5225610f claimed T11 (live ≥$0.10 alert feed) on branch `arena/5225610f-kalshidash3`.
- 2026-11-20: OVERLAP. While this branch was in progress, `main` received PR #16 (arena-6d85f8f0, T11 'Add sourced price-swing alert streams', merged 13:18 UTC) with the same ≥$0.10 feeds on `dashboard.html`. Resolution: this session did NOT keep a second alert UI. The `alerts.html` page was removed; the dashboard feeds remain the single UI. This session's contribution is re-scoped as T12 (persistent archive, data layer) and the branch merges `origin/main` without discarding either side.
- 2026-11-20: Request R-1 (to the dashboard owner / integration session): point the dashboard's alert feeds at `data/live/alerts_archive.json` (or `alerts.json`) instead of recomputing from `price_history.json`, so alerts survive a market leaving the open scan (F-17). Not done in this branch because `dashboard.html` belongs to the done T11 task.
- 2026-11-20: arena-5225610f T12 (superseded wording, kept for the record). Built `scripts/build_alerts.py` → `data/live/alerts.json` (consecutive last-price observations with |Δ| ≥ $0.10, both directions) and `alerts.html` — this page was REMOVED during the merge because it duplicated the dashboard feeds from arena-6d85f8f0 (T11, PR #16). Sources: https://docs.kalshi.com/api-reference/market/get-markets (verified fields `last_price_dollars`, `volume_24h_fp`, `status`), https://docs.kalshi.com/getting_started/market_lifecycle. Irregularities F-14 (ROI model not supplied), F-15 (cause links not collected; left null), F-16 (scheduled collector never fired: last 5 runs all manual; snapshot stale ~1h44m at 13:17 UTC; source https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows). Added alert build step to `collect.yml`.
- 2026-11-20: arena-5225610f T11 follow-up: the fresh snapshot dropped the closed market that produced the first 4 alerts (collector prunes history to open markets). Added append-only `data/live/alerts_archive.json` in `build_alerts.py` and seeded it from commit b95bebb. Irregularity F-17.
- 2026-11-20: arena-5225610f T12 merged. PR https://github.com/kanlerxz87-cyber/KalshiDash3/pull/18 — merge commit `a0a8862c7328374ced662d4d36c7162461a14f70` (merge, mergeable CLEAN). Pages run 44743562211 (Deploy site to GitHub Pages) and pages-build-deployment 44743561977: success. Live `flagged.html` lists 17 irregularities (F-01..F-17), confirmed by fetch. Still open: R-1 (dashboard should read `data/live/alerts_archive.json`), F-14 (owner ROI model), F-16 (scheduled collector not yet observed on main).

## Session `arena-e5adea9d` — paper-trading simulator, verification, integration (branch `arena/e5adea9d-kalshidash3`)

### Coordination note (read first)

This session's first claim (T11–T14, commit `8d5833e`) was pushed at 13:20 UTC. Within minutes `main` received
PR #16 (T11, `arena-6d85f8f0`, dashboard alert feeds) and PR #18 (T12, `arena-5225610f`, alert archive and
`scripts/build_alerts.py`). Those two tasks were already done and are **not** repeated here. The duplicate
`alerts.py`, `alerts.html`, and a second `alert_rules.json` built by this session were withdrawn before merge, so the
repo keeps one alert pipeline and one alert UI. No `main` file owned by another session was overwritten or deleted.

### Task board (this session)

| ID | Task | Status | Owner | Files in scope | Verification | Irregularities |
|----|------|--------|-------|----------------|--------------|----------------|
| T11 | Live ≥ $0.10 swing feeds | **done by arena-6d85f8f0 (PR #16)**; this session withdrew its duplicate | arena-6d85f8f0 | — | — | F-14 (ROI model not supplied) |
| T12 | Persistent alert archive | **done by arena-5225610f (PR #18)**; this session withdrew its duplicate | arena-5225610f | — | — | F-15 to F-17; request R-1 open |
| T15 | Paper simulator: fixed rules applied to `data/live/alerts_archive.json` (main's T12 output), official taker fee, settlement from the official `result`, results by rule, topic and trade type | in progress (pending PR) | arena-e5adea9d | `scripts/simulate.py`, `data/strategies.json`, `data/live/simulation.json` (generated), `simulation.html`, `scripts/tests/test_simulate.py`, `scripts/tests/validate_live.py` (`check_simulation` block only), `.github/workflows/collect.yml` (one step after the alert build) | `python3 scripts/tests/test_simulate.py` (14 tests OK); `validate_live.py` OK; a synthetic-data render test of `simulation.html` in a temp copy (not committed) | F-19, F-20, F-21 |
| T13 | Verification and Flagged updates for T15 (facts F-50 to F-53; flagged F-18 to F-21; question Q9; suggestions G9, G10) | in progress (pending PR) | arena-e5adea9d | `data/verified_facts.json`, `data/findings.json` | Each new fact read from its official page this session (demo_env, market_lifecycle, market_settlement, orderbook_responses, GitHub Pages publishing source) | F-18 (Pages source discrepancy) |
| T14 | Integration: nav entry, index card and pipeline row, README, PR → main, merge, collector dispatch on main, Pages deploy confirm | in progress (pending PR) | arena-e5adea9d | `assets/site.js` (nav entry only), `index.html` (one card, one pipeline row), `README.md`, `COORDINATION.md` | `check_site.py` OK; `node --check` on every inline and asset script OK; jsdom render of simulation, index, strategies and dashboard with no errors; YAML parsed with js-yaml | — |

Sources were not changed: every official URL used by this session is already listed on `sources.html` (checked
before editing).

### Requests logged by this session

- **R-1 (still open, from arena-5225610f):** point the dashboard alert feeds at `data/live/alerts_archive.json`.
  Owner: dashboard. Not implemented here.
- **R-2 (new, to arena-5225610f / T12 owner):** in `scripts/build_alerts.py`, store `to_yes_bid` and `to_yes_ask`
  (taken from the observation at `to_time`) on each new archive entry. `scripts/simulate.py` already reads those
  fields when present; until they exist, most swings cannot be filled and the simulation page shows that. Flagged F-19.
  Not implemented here, because `build_alerts.py` belongs to T12.

### Log

- 2026-11-20 13:20 UTC: claimed T11–T14 (commit `8d5833e`). Checked before claiming: `main` = `cd104db`; no other open session branch.
- 2026-11-20 ~13:21 UTC: `main` advanced by PR #16 (T11) and PR #18 (T12). The T11/T12 claim overlapped that work. Withdrawn; kept only as a record. The merge conflict in this file was resolved by keeping every existing row and log line.
- 2026-11-20 13:26 UTC: re-claimed the remaining scope as T15 (simulator and page) and T13 and T14 (verification and integration), with the rows above. Re-read `origin/main` before the claim: T11 and T12 done; T13 and T14 not claimed.
- 2026-11-20 13:26–13:31 UTC: rebuilt on `origin/main` (merge). Kept only: strategy definitions, simulator, simulation page, fee and settlement tests (`test_simulate.py`), and one simulation check in `validate_live.py`. Dropped: the duplicate alert page, alert script, alert rules, and alert tests.
- 2026-11-20 13:30 UTC: observed on `main`: the collector ran again (snapshot 13:18:28Z, 506 open and 200 settled in scope). The archive holds 4 swings; all 4 are from one market that settled `no` and left the open scan, so none can be filled (F-19, R-2).
- 2026-11-20 13:31 UTC: branch pushed (`3b324cb`). The first `git pull --rebase` attempt was aborted: a branch that merges `main` cannot be rebased onto its own old tip without replaying `main`'s commits. A plain push was used instead, after checking that the remote tip is an ancestor of HEAD.
- 2026-11-20 13:31:55Z: PR #20 (`arena/e5adea9d-kalshidash3` → `main`, merge commit `ca10d37`) merged with a merge commit. `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN` before merge.
- 2026-11-20 13:31:56Z: `pages.yml` for `ca10d37` succeeded (run 44745119805). The branch-based Pages build (`pages-build-deployment`) built the collector snapshot `82218d3` at 13:32:28Z. See F-18.
- 2026-11-20 13:32Z: `collect.yml` dispatched on `main` (run 44745135044): success, all steps including the new simulate step. The collector committed `82218d3` (`data: demo snapshot 2026-11-20T13:32Z`). Snapshot 13:32:25Z, 506 open and 200 settled in scope.
- 2026-11-20 13:32Z: the new simulation run opened one paper position from the 13:18→13:32 KXDEMOFUTHOURLY-26NOV20H14-UP swing. Its stored quote was yes bid 0.01, yes ask 1.00, so a NO fill at 0.99 with a 0.00 bid later showed −1.00. That is not a tradable price. Follow-up: spread rule (F-23) and void of the breaching position.
- 2026-11-20 ~13:36Z: follow-up branch commit `a5c5d39` and merge `a83ab25` (merge of `origin/main` `82218d3`). Adds `max_quote_spread_dollars` 0.10 to `data/strategies.json`; `simulate.py` does not fill across wider quotes and voids breaching open positions; the page labels them VOID; 16 unit tests OK; `validate_live.py` OK; `check_site.py` OK. Opened as PR #21 for merge to `main`. Its merge result is in the session report, not in this board row, because the board itself can only change through a PR.
- Collector runs (checked 13:31 UTC with `gh run list --workflow collect.yml`): the last six runs are all `workflow_dispatch`, none `schedule`. The 13:18:05Z run was dispatched from `arena/5225610f-kalshidash3` and produced the 13:18:28Z snapshot. F-16 stays open.

## Session `arena-6a3c4e55` — official cause candidates, chart jump markers, R-1 (archive-backed feeds)

Branch `arena/6a3c4e55-kalshidash3`. This session is the integration session for the brief's remaining gaps. It keeps
the single canonical alert UI on `dashboard.html` and the single canonical data layer (`scripts/build_alerts.py` →
`data/live/alerts_archive.json` → `data/live/alerts.json`). It does **not** ship a second alert page, a second
detector, or a second simulator.

### Task board (this session)

| ID | Task | Status | Owner | Files in scope | Verification | Irregularities |
|----|------|--------|-------|----------------|--------------|----------------|
| T11 | Official cause candidates for every alert (event settlement sources, labelled unverified) + >=$0.10 chart jump markers + implement open request R-1 (feeds read the archive/feed, not raw retained history) | in progress | arena-6a3c4e55 | `scripts/collect_event_refs.py`, `data/live/event_refs.json` (generated), `scripts/build_alerts.py` (cause fields only), `dashboard.html` (feeds + markers), `assets/site.css`, `.github/workflows/collect.yml`, `scripts/tests/validate_live.py` (cause checks), `data/findings.json` (F-15), `COORDINATION.md` | `python3 scripts/check_site.py`, `python3 scripts/tests/validate_live.py`, `node --check` on the inline dashboard script, plus a Node fixture smoke test for feed source, category filter, cause labelling and jump markers | F-15 answered with **checkable official settlement-source candidates**, never a news attribution; causation stays `unverified` |
| T12 | Automated S1-S4 paper simulation | **withdrawn** — superseded by `arena-e5adea9d` (PR #20 merged, PR #21 follow-up). `scripts/simulate.py`, `data/live/simulation.json`, `simulation.html`, `scripts/tests/test_simulate.py` are the canonical implementation. This session's local duplicate (`scripts/simulate_strategies.py`, `data/live/simulations.json`) was deleted, not shipped. | arena-e5adea9d | — | — | — |

### Requests

- **R-1 (open since 2026-11-20, from arena-5225610f):** point the dashboard alert feeds at
  `data/live/alerts_archive.json` / `data/live/alerts.json` instead of recomputing from `price_history.json`.
  Owner: dashboard. **Implemented in this branch.**
- **R-3 (new, to arena-5225610f / T12 owner):** `scripts/build_alerts.py` should also store the bid/ask observed at
  `to_time` on each new archive entry. `scripts/simulate.py` reads `to_yes_bid` / `to_yes_ask` when present (R-2);
  this session's cause-field change does not touch them, so R-2/R-3 stay open for the archive owner.

### Log

- 2026-11-20 13:0x UTC: claimed T11-T12 on branch `arena/6a3c4e55-kalshidash3` (commit `001c4ff`), after checking
  `main` = `cd104db`. Work in progress: local `alerts.html` + `scripts/detect_alerts.py` + `scripts/simulate_strategies.py`.
- 2026-11-20: OVERLAP found on rebase. `main` had received PR #16 (arena-6d85f8f0, dashboard alert feeds) and PR #18
  (arena-5225610f, `scripts/build_alerts.py` + append-only `data/live/alerts_archive.json`), and later PR #20 / #21
  (arena-e5adea9d, paper simulator `scripts/simulate.py` + `simulation.html`). Resolution: this session ships **no**
  second alert page, **no** second detector and **no** second simulator. The local duplicates were deleted. The
  canonical `dashboard.html` feeds, the canonical archive pipeline and the canonical simulator are the ones that ship.
- 2026-11-20: rebased onto `main` repeatedly (`4dc9ee2` -> `82218d3` -> `9d3faeb`); each `COORDINATION.md` conflict was
  resolved by keeping every existing row and log line and appending this section.
- 2026-11-20: **Correction.** The first conflict resolution in this session (onto `4dc9ee2`) was written by slicing
  the conflicted working file, which silently dropped the first 135 lines of this board - the header, the task table
  and the log of sessions `arena-5761b399`, `session-1c0d1fc0`, `arena-e05bd5ff` and `arena-6d85f8f0`. The board is
  restored in full here from `origin/main` (`9d3faeb`) and this session appends to it instead of replacing it. No other
  file was affected: the truncation was confined to `COORDINATION.md`.
