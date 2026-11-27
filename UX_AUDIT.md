# Static-site accessibility and interaction audit

**Date:** 2026-11-27  
**Scope:** The checked-in 21 HTML pages and shared styling/runtime. This is a focused source/DOM inspection, not a WCAG conformance assessment, screen-reader test, or full browser usability study. No application or market-data files were changed.

## Summary

The basic page shell is consistent: all 21 pages have English document language, a viewport declaration, a title, exactly one `<h1>`, and a `<main>` landmark. A local jsdom scan found no duplicate element IDs, unnamed buttons/links/form controls by a simple accessible-name heuristic, missing image `alt` attributes, or positive `tabindex` values. `scripts/check_site.py` also passes its HTML parse and internal-link checks.

The audit found three worthwhile improvements for a later implementation session. They are recommendations, not claims that the site is inaccessible to every user:

| ID | Observation from the checked-in tree | Why it matters / suggested follow-up | Evidence |
|---|---|---|---|
| UX-1 | Four charts are rendered as `<canvas>` elements with generic `aria-label` text. The visible pointer readout does not provide a keyboard-operable equivalent series of chart points. | Add a textual summary and an accessible data table (or equivalent keyboard-readable point list) synchronized with the selected market/time window. Keep the canvas as the visual chart. | [`dashboard.html`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/dashboard.html), [`live.html`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/live.html), [`portfolio.html`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/portfolio.html), [`trading.html`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/trading.html) |
| UX-2 | Category filter buttons are visually selected through classes or inline border changes, but the runtime renderers do not set a programmatic selected/pressed state. Shared navigation marks the active link with a class but does not set `aria-current`. | Synchronize state attributes such as `aria-pressed` on filters and `aria-current="page"` on the active page link whenever those controls rerender. Verify with keyboard and screen-reader interaction. | [`alerts.html`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/alerts.html), [`live.html`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/live.html), [`assets/site.js`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/assets/site.js) |
| UX-3 | The checked-in CSS has smooth scrolling and animated live/status elements. The only `prefers-reduced-motion` rule disables the shared chat-dot pulse; the live desk pulse, fresh-message slide, and smooth-scroll declarations remain active. Four `role="log" aria-live="polite"` feeds appear in the page HTML and two more are created by the shared dock (six total). | Extend reduced-motion handling to all transitions/animations and smooth scrolling. Consider a clear pause/quiet mode or batched announcements so users can control frequent live-feed updates. | [`assets/site.css`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/assets/site.css), [`assets/live.css`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/assets/live.css), [`assets/chatdock.js`](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/assets/chatdock.js) |

## Checks performed

- `python3 scripts/check_site.py` — **PASS**, 21 pages parsed; internal links resolve and data files parse.
- `node --check` / comprehensive regression and DOM checks are included in `python3 scripts/verify_release.py`; that full release gate passed during this session after installing its test-only `jsdom@26` dependency with `npm install --no-save --package-lock=false jsdom@26`.
- A read-only jsdom pass over the 21 root HTML files checked language, viewport, title, main landmark, one `<h1>`, duplicate IDs, accessible names for links/buttons/form controls, image alt attributes, fragment targets, new-window link `rel`, and positive `tabindex`. It found **21/21** page shells passing those baseline checks. The scan counted 344 links, 36 native/button controls, four canvases, no images, and no positive tabindex values.
- CSS/runtime inspection found six polite live log feeds across checked-in HTML and shared dock code; one reduced-motion rule; multiple smooth-scroll declarations; and remaining live-desk/fresh-message animations.

## Limitations and handoff

- The accessible-name check is deliberately simple; it does not calculate computed accessible names or verify focus order after runtime rendering.
- No contrast ratios, zoom/reflow, mobile overflow, keyboard-only journeys, screen-reader announcements, chart-data comprehension, or real assistive-technology behavior were tested.
- These UX findings were not added to the site's `Flagged for Review` table because that page and its findings ledgers have active, separate owners. They are recorded here for handoff; no project claim of accessibility certification is made.
