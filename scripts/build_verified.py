#!/usr/bin/env python3
"""Build docs/verified/index.html: a self-contained page of the verified Kalshi demo snapshot.

This is an additive page. It does not change any other file in docs/ or the root site.
Inputs : data/snapshot.json (official Kalshi API rows, each with its source query URL)
         data/findings.json (analysis, questions, sources, flagged items)
Outputs: docs/verified/index.html, docs/verified/data/*.json (copies for download)

Run from the repository root:  python3 scripts/build_verified.py
"""
import html
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "docs", "verified")

snap = json.load(open(os.path.join(DATA, "snapshot.json")))
find = json.load(open(os.path.join(DATA, "findings.json")))
E = lambda s: html.escape("" if s is None else str(s))


def blank(v):
    if v in (None, ""):
        return '<span class="blank" title="Not confirmed from the official source; left blank">unverified</span>'
    return E(v)


def market_table(rows, show_result=False):
    head = ["Market", "Label", "Status", "Last price", "YES bid", "YES ask", "Bid size", "Ask size",
            "Contracts traded", "Open interest", "Close (UTC)"]
    if show_result:
        head += ["Result", "Settled (UTC)"]
    head += ["Source"]
    out = []
    for r in rows:
        cells = [
            "<td><code>%s</code></td>" % E(r["ticker"]),
            "<td>%s</td>" % E(r["label"]),
            "<td>%s</td>" % E(r["status"]),
            "<td>%s</td>" % blank(r["last_price"] and "$" + r["last_price"]),
            "<td>%s</td>" % blank(r["yes_bid"] and "$" + r["yes_bid"]),
            "<td>%s</td>" % blank(r["yes_ask"] and "$" + r["yes_ask"]),
            "<td>%s</td>" % blank(r["bid_size"]),
            "<td>%s</td>" % blank(r["ask_size"]),
            "<td>%s</td>" % blank(r["volume_contracts"]),
            "<td>%s</td>" % blank(r["open_interest_contracts"]),
            "<td>%s</td>" % blank(r["close_time_utc"]),
        ]
        if show_result:
            res = r.get("result")
            cells.append("<td><strong>%s</strong></td>" % (E(res.upper()) if res else blank(None)))
            cells.append("<td>%s</td>" % blank(r.get("settlement_ts_utc")))
        cells.append('<td><a href="%s" target="_blank" rel="noopener">official API</a></td>' % E(r["source_url"]))
        out.append("<tr>%s</tr>" % "".join(cells))
    th = "".join("<th>%s</th>" % E(h) for h in head)
    return '<div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, "".join(out))


def section_for_topic(s):
    rows = [m for m in snap["markets"] if m["topic"] == s["topic"] and m["status"] == "open"]
    a = next((x for x in find["analysis"] if x["topic"] == s["topic"]), None)
    obs = "".join("<li>%s</li>" % E(o) for o in (a or {}).get("observations", []))
    dr = E((a or {}).get("decision_relevance", ""))
    table = market_table(rows) if rows else '<p class="muted">No open markets returned for this series at capture time (see Flagged F8).</p>'
    return """<section id="%(id)s"><h2>%(topic)s</h2>
<p class="card-line"><strong>Series</strong> <code>%(t)s</code> · %(title)s · Kalshi category <em>%(cat)s</em> · frequency %(freq)s</p>
<p class="card-line"><strong>Settlement source:</strong> %(src)s · <a href="%(url)s" target="_blank" rel="noopener">series (official API)</a> · <a href="%(pdf)s" target="_blank" rel="noopener">contract terms PDF</a></p>
%(table)s
<h3>Observations</h3><ul>%(obs)s</ul>
<p><strong>What this means for decisions:</strong> %(dr)s</p></section>""" % {
        "id": E(s["topic"].lower().replace(" ", "-")), "topic": E(s["topic"]), "t": E(s["series_ticker"]),
        "title": E(s["title"]), "cat": E(s["kalshi_category"]), "freq": E(s["frequency"]),
        "src": E(s["settlement_source"]), "url": E(s["source_url"]), "pdf": E(s["contract_terms_pdf"]),
        "table": table, "obs": obs, "dr": dr}


CSS = """
:root{--ink:#1b1f24;--muted:#5b6470;--line:#e3e7ec;--bg:#f7f9fb;--brand:#00B67A;--warn:#8a5a00;--warnbg:#fff6e5}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--ink);background:var(--bg)}
a{color:#0a6b4a}header{background:#fff;border-bottom:1px solid var(--line);padding:12px 20px;position:sticky;top:0;z-index:5}
header nav a{margin-right:12px;font-size:13px;color:var(--muted);text-decoration:none}header nav a:hover{color:var(--brand)}
main{max-width:1200px;margin:0 auto;padding:18px 20px 40px}h1{font-size:26px;margin:6px 0}h2{font-size:19px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}h3{font-size:15px;margin:14px 0 6px}
.lead{color:var(--muted)}.banner{background:var(--warnbg);border:1px solid #f0d49a;color:#6b4300;padding:8px 12px;border-radius:8px;font-size:13px;margin:10px 0}
.card-line{font-size:13px;margin:4px 0}.muted{color:var(--muted);font-size:13px}.blank{color:var(--warn);font-style:italic;font-size:12px}
.scroll{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:10px;margin:8px 0}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#f1f5f8;white-space:nowrap}
code{font-size:12px;background:#eef2f6;padding:1px 4px;border-radius:4px}.toc a{display:inline-block;margin:2px 10px 2px 0}
footer{color:var(--muted);font-size:12px;text-align:center;padding:20px}
"""


def build():
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
    for f in ("snapshot.json", "findings.json"):
        shutil.copy(os.path.join(DATA, f), os.path.join(OUT, "data", f))

    topics = [s for s in snap["series"]]
    toc = "".join('<a href="#%s">%s</a>' % (E(s["topic"].lower().replace(" ", "-")), E(s["topic"])) for s in topics)
    topic_html = "".join(section_for_topic(s) for s in topics)

    fin = [m for m in snap["markets"] if m["status"] == "finalized"]
    resolved = market_table(fin, show_result=True)

    qrows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        E(q["id"]), E(q["question"]), E(q["current_answer"]), E(q["how_to_resolve"])) for q in find["questions"])
    frows = "".join('<tr><td>%s</td><td>%s</td><td>%s<br><span class="muted">%s</span></td><td><a href="%s" target="_blank" rel="noopener">source</a></td></tr>' % (
        E(f["id"]), E(f["type"]), E(f["item"]), E(f["detail"]), E(f["source"])) for f in find["flagged"])
    srcs = "".join('<tr><td>%s</td><td><a href="%s" target="_blank" rel="noopener">%s</a></td></tr>' % (
        E(s["label"]), E(s["url"]), E(s["url"])) for s in find["sources"])
    unv = "".join("<li><strong>%s</strong>: %s</li>" % (E(u["item"]), E(u["reason"])) for u in snap["unverified_or_omitted"])
    sugg = "".join("<li><strong>%s · %s</strong> — %s <span class=\"muted\">(effort %s; risk %s; not implemented)</span></li>" % (
        E(s["id"]), E(s["title"]), E(s["detail"]), E(s["effort"]), E(s["risk"])) for s in find["suggestions"])

    doc = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Verified Kalshi demo snapshot · KalshiDash3</title><style>%(css)s</style></head>
<body>
<header><nav><a href="../index.html">Main site</a><a href="../dashboard.html">Live dashboard</a><a href="#open">Open markets</a><a href="#resolved">Resolved yes/no</a><a href="#questions">Questions</a><a href="#flagged">Flagged for Review</a><a href="#sources">Sources</a></nav></header>
<main>
<h1>Verified Kalshi demo snapshot</h1>
<p class="lead">Each value was read from the official Kalshi Trade API (demo environment) and is linked to the exact query it came from. Values that could not be confirmed are left blank and marked <span class="blank">unverified</span>.</p>
<div class="banner">Demo environment data only. Kalshi docs state demo prices "may not be reflective of those in real markets". Snapshot captured %(cap)s UTC. Volume is in <strong>contracts</strong>, not dollars: the API returns no dollar-volume field.</div>
<p class="toc">Jump to: %(toc)s</p>
<p><strong>Method:</strong> %(method)s</p>

<h2 id="open">Open markets by topic (verified snapshot)</h2>
%(topics)s

<h2 id="resolved">Resolved markets: yes or no</h2>
<p class="muted">Settled markets in the snapshot. Result is the API's <code>result</code> field. Five strikes from one monthly gas series, all YES: a tiny sample that says nothing about general accuracy. Flag F1 covers one strike whose API last price did not match its result.</p>
%(resolved)s

<h2 id="questions">Questions and information gaps</h2>
<div class="scroll"><table><thead><tr><th>ID</th><th>Question</th><th>Current answer</th><th>How to resolve</th></tr></thead><tbody>%(qrows)s</tbody></table></div>
<h3>Suggestions (for review; none implemented)</h3><ul>%(sugg)s</ul>

<h2 id="flagged">Flagged for Review</h2>
<p class="muted">Irregularities, unverified items, and repository notes. They do not block publication. Please review and request changes.</p>
<div class="scroll"><table><thead><tr><th>ID</th><th>Type</th><th>Item</th><th>Source</th></tr></thead><tbody>%(frows)s</tbody></table></div>
<h3>Omitted, or not confirmed from an official source</h3><ul>%(unv)s</ul>

<h2 id="sources">Sources</h2>
<p class="muted">Official Kalshi documentation, series endpoints, and contract-terms PDFs are listed first in the order they were used. Downloadable data: <a href="data/snapshot.json">snapshot.json</a> · <a href="data/findings.json">findings.json</a>.</p>
<div class="scroll"><table><tbody>%(srcs)s</tbody></table></div>
</main>
<footer>Built by scripts/build_verified.py from data/*.json. Not financial advice.</footer>
</body></html>
""" % {"css": CSS, "cap": E(snap["captured_at_utc"]), "toc": toc, "method": E(snap["capture_method"]),
       "topics": topic_html, "resolved": resolved, "qrows": qrows, "sugg": sugg, "frows": frows,
       "unv": unv, "srcs": srcs}
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(doc)
    print("wrote", os.path.relpath(os.path.join(OUT, "index.html"), ROOT))


if __name__ == "__main__":
    build()
