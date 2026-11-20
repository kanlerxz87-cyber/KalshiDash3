// KalshiDash3 — shared client-side utilities (graph page)
// NOTE: this sandbox cannot reach kalshi.co/docs.kalshi.co (outbound limited to
// GitHub hosts and package registries). No Kalshi market values are hardcoded here.

(function () {
  const NAV = [
    { href: "index.html", label: "Home" },
    { href: "dashboard.html", label: "Dashboard" },
    { href: "gas.html", label: "Gas Prices" },
    { href: "elections.html", label: "Elections" },
    { href: "culture.html", label: "Culture" },
    { href: "crypto.html", label: "Crypto" },
    { href: "golf.html", label: "Golf" },
    { href: "resolved.html", label: "Resolved (Yes / No)" },
    { href: "graph.html", label: "Price Graph" },
    { href: "portfolio.html", label: "Portfolio" },
    { href: "suggestions.html", label: "Suggestions / Q&A" },
    { href: "sources.html", label: "Sources & Flagged" },
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

  document.addEventListener("DOMContentLoaded", renderNav);
})();
