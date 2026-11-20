# COORDINATION.md — Shared Task Board

> Session ID: `arena-5761b399` · Branch: `arena/5761b399-kalshidash3` · Base: `49ba7bce3112e9e0b4c7534af961e1d0ef8d19ff` (main)
> Rule: claim before work, commit+push claim immediately, non-overlapping scopes, small frequent commits, `git pull --rebase` before push. Stale claim (>60 min, no commits) may be taken over with handoff note.

## Task board

| ID | Task | Status | Owner (session) | Files in scope | Sources / verification | Irregularities |
|----|------|--------|-----------------|----------------|------------------------|----------------|
| T1 | Repo review + COORDINATION setup + executive summary | done | arena-5761b399 | `COORDINATION.md`, `README.md`, `docs/executive-summary.html`, `docs/index.html` | Official docs: https://docs.kalshi.com/welcome , https://docs.kalshi.com/getting_started/demo_env | None |
| T2 | Live dashboard (5 categories, highest-dollar events, price graph, liquidity/orderbook, resolution tracking) | done | arena-5761b399 | `docs/dashboard.html`, `docs/assets/app.js`, `docs/assets/style.css`, `data/*.json` | Live demo API (browser fetch): https://external-api.demo.kalshi.co/trade-api/v2 ; docs: https://docs.kalshi.com/api-reference | Sandbox cannot reach Kalshi API directly (outbound allowlist); dashboard fetches client-side with graceful fallback |
| T3 | Portfolio + trade execution + categorization/strategies | done | arena-5761b399 | `docs/portfolio.html`, `docs/strategies.html`, `scripts/kalshi_client.py` | Auth/signing: https://docs.kalshi.com/getting_started/api_keys ; rate limits: https://docs.kalshi.com/getting_started/rate_limits | No demo API keys provided — execution is paper until keys supplied via env (never committed) |
| T4 | Suggestions + open questions + flagged-for-review + verification tables | done | arena-5761b399 | `docs/suggestions.html`, `docs/questions.html`, `docs/flagged.html`, `docs/verification.html`, `docs/sources.html` | Every row links to official source or is left blank + flagged | F1–F4 on Flagged page |
| T5 | GitHub Pages publish + final integration (build check, link check, PR to main, merge, deploy confirm) | in progress | arena-5761b399 | `.github/workflows/pages.yml`, `docs/*` (integration only) | Link check passed; JS/Python syntax passed | — |

## Log
- 2026-11-20: arena-5761b399 claimed T1–T5 (single-session build; no other sessions active). Repo was empty except README. Starting build.
