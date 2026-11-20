# Integration note — two implementations

Two parallel sessions built the same dashboard:

1. **`docs/` site (live on GitHub Pages)** — from `arena-5761b399`, merged via PR #1. Pages workflow deploys `docs/`.
2. **Root-level site** — from `session-1c0d1fc0` (this branch, PR #2). Same features, different layout (`index.html`, `dashboard.html`, category pages, `assets/js/*`), plus `data/verified_facts.json` and `scripts/kalshi_tracker.py`.

**Recommendation:** pick one as canonical and delete the other in a follow-up PR, or merge the best of both (e.g. keep `docs/` navigation, port `verified_facts.json` table into `docs/sources.html`). Until then, the live site is `docs/`; the root site can be previewed by serving the repo root.

**PR link:** https://github.com/kanlerxz87-cyber/KalshiDash3/pull/2
**Merge result:** see COORDINATION.md Log (T7).
