/* Saves the visitor's decision for each suggestion in this browser only (localStorage).
 * Nothing is sent anywhere. Decisions are recorded in the repo only when the owner asks.
 */
(function () {
  "use strict";
  var KEY = "kalshi-dash-suggestion-decisions";
  function read() { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; } }
  function write(obj) { try { localStorage.setItem(KEY, JSON.stringify(obj)); } catch (e) { /* storage blocked: ignore */ } }
  function summary() {
    var d = read();
    var counts = { Approve: 0, Defer: 0, Reject: 0 };
    Object.keys(d).forEach(function (k) { if (counts[d[k]] !== undefined) counts[d[k]]++; });
    var el = document.getElementById("decision-summary");
    if (el) el.textContent = "Saved in this browser: " + counts.Approve + " approved, " + counts.Defer + " deferred, " + counts.Reject + " rejected.";
  }
  document.addEventListener("DOMContentLoaded", function () {
    var saved = read();
    document.querySelectorAll("select.decision").forEach(function (sel) {
      var id = sel.getAttribute("data-id");
      if (saved[id]) sel.value = saved[id];
      sel.addEventListener("change", function () {
        var d = read();
        if (sel.value) d[id] = sel.value; else delete d[id];
        write(d);
        summary();
      });
    });
    summary();
  });
})();
