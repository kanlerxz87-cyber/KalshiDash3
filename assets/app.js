// KalshiDash3 — shared client-side utilities
// NOTE: sandbox cannot reach kalshi.co (outbound restricted to GitHub hosts/package registries).
// All Kalshi values shown here are therefore UNVERIFIED placeholders with source links only.
// No values are inferred or filled in.

(function () {
  const NAV = [
    { href: "index.html", label: "Home" },
    { href: "gas-prices.html", label: "Gas Prices" },
    { href: "elections.html", label: "Elections" },
    { href: "culture.html", label: "Culture" },
    { href: "crypto.html", label: "Crypto" },
    { href: "golf.html", label: "Golf" },
    { href: "graph.html", label: "Price Graph" },
    { href: "portfolio.html", label: "Portfolio" },
    { href: "strategies.html", label: "Strategies" },
    { href: "suggestions.html", label: "Suggestions" },
    { href: "questions.html", label: "Questions / Info / Answers" },
    { href: "flagged-for-review.html", label: "Flagged for Review" },
  ];

  function renderNav() {
    const container = document.querySelector(".nav-inner");
    if (!container) return;
    const path = location.pathname.split("/").pop() || "index.html";
    container.innerHTML = NAV.map((n) => {
      const active = path === n.href ? " active" : "";
      return `<a href="${n.href}" class="${active}">${n.label}</a>`;
    }).join("");
  }

  // Official Kalshi demo trade API v2 base URLs (source links only; data not verifiable from this sandbox)
  const KALSHI_BASES = [
    "https://external-api.demo.kalshi.co/trade-api/v2",
    "https://demo-api.kalshi.co/trade-api/v2",
  ];

  function sourceLink(ticker, type = "event") {
    // Link to the official Kalshi event/market page pattern; exact URL pattern is not published,
    // so this points at the trade API v2 root as the official source for verification.
    return `<a href="${KALSHI_BASES[0]}/" target="_blank" rel="noopener">Kalshi trade API v2 (official source)</a>`;
  }

  function unverifiedCell(text = "unverified") {
    return `<span class="badge badge-unverified">${text}</span>`;
  }

  function blankCell() {
    return `<span class="value-blank">—</span> <span class="badge badge-blank">unverified</span>`;
  }

  window.KalshiDash = { KALSHI_BASES, sourceLink, unverifiedCell, blankCell };
  document.addEventListener("DOMContentLoaded", renderNav);
})();
