#!/usr/bin/env python3
"""Attach fetched, source-linked catalysts to the >=$0.10 swings (data/live/catalysts.json).

Why this file exists
  data/live/alerts_archive.json deliberately keeps `cause_link: null` on every alert, because
  no official source for a cause had been collected (F-15). The brief asks for "events and
  website links that may have caused a sharp jump". A cause is not fetchable from an API, so
  this project does not claim one: it publishes the market's OWN settlement reference, plus a
  fetched reading of that reference at the time of the swing, and lets the reader judge.

Inputs (no network, no credentials)
  data/live/alerts_archive.json   every swing >= the threshold, with its timestamps
  data/live/markets.json          the collected market records (rules text when the collector kept it)
  data/catalyst_review.json       the review ledger: URLs a session actually fetched and read,
                                  with the values copied out of each response

Output
  data/live/catalysts.json        one row per archived swing: state, links, the numbers the
                                  comparison was made from, and the arithmetic on them

Rules this file obeys
  * A link is rendered only if it appears in data/catalyst_review.json, and a value only if the
    ledger's own `observed` block contains it — the builder re-reads both and refuses otherwise.
  * `comparison` is recomputed here from the ledger's numbers; a stale or hand-edited
    relation is caught, not published.
  * No row is invented for an unreviewed swing: it is written as `not_reviewed` with no links,
    so "nothing was found" is visibly different from "nobody looked".
  * Causal language is refused (see BANNED), including for a swing whose reference moved in the
    same minute: coincidence in time is what can be shown from outside the exchange.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.parse import unquote
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "live"
LEDGER = ROOT / "data" / "catalyst_review.json"
OUT = LIVE / "catalysts.json"

BANNED = ("caused", "cause of", "triggers", "triggered", "due to", "led to", "drove the",
          "because of the", "on account of")
URL_RE = re.compile(r"^https://[^\s\"']+$")
VERDICTS = {"external_move_coincides", "external_move_coincides_in_direction",
            "no_external_move_supporting_this_swing", "no_external_move_in_window",
            "published_reference_on_the_same_side_as_the_move",
            "published_reference_on_the_other_side_of_the_strike", "not_reviewed"}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path) -> dict:
    if not path.exists():
        print(f"missing input: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def refuse(problems: list[str]) -> None:
    if problems:
        print("catalysts refused:", file=sys.stderr)
        for p in problems[:30]:
            print("  -", p, file=sys.stderr)
        sys.exit(1)


NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def norm_url(u: str) -> str:
    """Percent-encoding is not part of a link's identity: the ledger may quote the request it
    made with encoded colons and the review with literal ones, and both are the same fetch."""
    return unquote(str(u or "")).strip()


def ledger_link_index(ledger: dict) -> dict[str, dict]:
    """Every URL the ledger is allowed to vouch for, mapped to the source that carries it."""
    idx: dict[str, dict] = {}
    for s in ledger.get("sources") or []:
        urls = {s.get("url")}
        for v in (s.get("observed") or {}).values():
            if isinstance(v, str) and v.startswith("https://"):
                urls.add(v)
        for u in urls:
            if u:
                idx[u] = s
                idx.setdefault(norm_url(u), s)
    return idx


def cited_value(source: dict, value) -> bool:
    """Is this number actually in the fetched response the ledger claims to have read?"""
    obs = source.get("observed") or {}
    def tol(x: float) -> float:
        return max(5e-2, 1e-6 * abs(x))

    if isinstance(value, (int, float)):
        def walk(x):
            if isinstance(x, dict):
                return any(walk(v) for v in x.values())
            if isinstance(x, list):
                return any(walk(v) for v in x)
            if isinstance(x, (int, float)):
                return abs(float(x) - float(value)) <= tol(float(value))
            # A number quoted inside the verbatim text of a response (a strike written into a
            # market's own rules sentence, e.g. "…at or above 61498.92 USD…") counts: it is in
            # the fetched record, which is exactly what this gate exists to confirm.
            return any(abs(float(t) - float(value)) <= tol(float(value)) for t in NUM_RE.findall(x))
        return walk(obs)
    return value in json.dumps(obs)


def relation(cmp: dict) -> dict:
    """The arithmetic between the reference reading and the strike. Nothing else.

    `crossed` is stated for an "at or above" strike only as the fact that the printed value
    moved from below the strike to at-or-above it (or the reverse), which is arithmetic on two
    cited numbers — not a claim that the market should have moved, and not a claim about cause.
    """
    strike = cmp.get("strike")
    before, after = cmp.get("value_before"), cmp.get("value_after")
    out = {"kind": cmp.get("kind"), "strike": strike,
           "before": before, "before_at": cmp.get("value_before_at"),
           "after": after, "after_at": cmp.get("value_after_at"),
           "reference_side": cmp.get("reference_side")}
    if None in (before, after) or strike is None:
        out["incomplete"] = True
        return out
    out["change"] = round(after - before, 4)
    out["distance_to_strike_before"] = round(before - strike, 4)
    out["distance_to_strike_after"] = round(after - strike, 4)
    if before < strike <= after:
        out["crossed"] = "up"
    elif after < strike <= before:
        out["crossed"] = "down"
    else:
        out["crossed"] = None
    return out


def strike_is_above(cmp: dict) -> bool:
    """Is the cited reference reading at or above the strike? Arithmetic on two cited numbers."""
    strike, after = cmp.get("strike"), cmp.get("value_after")
    return None not in (strike, after) and float(after) >= float(strike)


def derive_verdict(rel: dict, delta) -> str:
    """What the cited numbers and the printed direction jointly say. Deliberately modest."""
    if rel.get("crossed"):
        return "external_move_coincides"
    if rel.get("incomplete"):
        return "not_reviewed"
    if rel.get("before") is not None and rel.get("after") is not None and rel.get("strike") is not None:
        above = float(rel["after"]) >= float(rel["strike"])
        up = (delta or 0) > 0
        return ("published_reference_on_the_same_side_as_the_move" if above == up
                else "published_reference_on_the_other_side_of_the_strike")
    return "no_external_move_in_window"


def build() -> dict:
    problems: list[str] = []
    archive = load(LIVE / "alerts_archive.json")
    ledger = load(LEDGER)
    markets_path = LIVE / "markets.json"
    markets = load(markets_path) if markets_path.exists() else {"open_markets": [], "settled_markets": []}
    rows = {}
    for bucket in ("open_markets", "settled_markets"):
        for r in markets.get(bucket) or []:
            if r.get("ticker"):
                rows[r["ticker"]] = r

    links_ok = ledger_link_index(ledger)
    reviews = {}
    for rv in ledger.get("reviews") or []:
        key = (rv.get("ticker"), rv.get("alert_to_time"))
        if key in reviews:
            problems.append(f"duplicate ledger review for {key}")
        reviews[key] = rv

    src_by_id = {s.get("id"): s for s in ledger.get("sources") or []}
    out_rows = []
    for a in archive.get("alerts") or []:
        ticker, to_time = a.get("ticker"), a.get("to_time")
        snap = rows.get(ticker) or {}
        rv = reviews.get((ticker, to_time))
        # The market record itself is the only place a settlement reference is written down
        # (https://docs.kalshi.com/api-reference/market/get-markets). If the collector did not
        # keep the text, these stay null and the ledger's copy is used instead.
        rules_text = snap.get("rules_primary") or None
        settlement_source = snap.get("source") or (
            f"{markets.get('base_url')}/markets/{ticker}" if markets.get("base_url") else None)
        row = {
            "ticker": ticker,
            "to_time": to_time,
            "from_time": a.get("from_time"),
            "from_price": a.get("from_price"),
            "to_price": a.get("to_price"),
            "delta": a.get("delta"),
            "direction": a.get("direction"),
            "category_id": a.get("category_id"),
            "title": a.get("title") or snap.get("title"),
            "market_source": a.get("market_source"),
            "market_status": snap.get("status") or a.get("status"),
            "result_as_returned": snap.get("result") if "result" in snap else None,
            "settlement_reference_text": None,
            "settlement_reference_source": settlement_source,
            "links": [],
            "state": "not_reviewed",
            "relation": None,
            "note": ("No review entry for this swing, so nothing is asserted about it. "
                     "Not the same as 'no news existed': nobody in this project has read the "
                     "reference for this market at this minute yet."),
            "reviewed_at": None,
        }
        if rules_text:
            row["settlement_reference_text"] = rules_text
        if rv:
            for u in rv.get("links") or []:
                if u not in links_ok and norm_url(u) not in links_ok:
                    problems.append(f"{ticker}@{to_time}: link not in the ledger's fetched sources: {u}")
                    continue
                s = links_ok.get(u) or links_ok.get(norm_url(u))
                row["links"].append({"url": u, "publisher": s.get("publisher"), "source_id": s.get("id"),
                                     "fetched_at": s.get("fetched_at")})
            srcs = []
            for sid in rv.get("source_ids") or []:
                s = src_by_id.get(sid)
                if s is None:
                    problems.append(f"{ticker}@{to_time}: source id {sid!r} is not in the ledger")
                    continue
                srcs.append(s)
            cmp = rv.get("comparison") or {}
            for s in srcs:
                if s.get("publisher", "").startswith("Kalshi demo Trade API"):
                    txt = (s.get("observed") or {}).get("rules_primary")
                    if txt:
                        row["settlement_reference_text"] = txt
                        row["settlement_reference_source"] = s.get("url")
            for key in ("value_before", "value_after", "strike"):
                val = cmp.get(key)
                if val is None:
                    continue
                if not any(cited_value(s, val) for s in srcs):
                    problems.append(f"{ticker}@{to_time}: {key}={val} is not in any fetched source it cites")
            rel = relation(cmp)
            rel["strike_side_after"] = ("at_or_above" if (rel.get("after") is not None and strike_is_above(cmp))
                                        else "below")
            row["relation"] = rel
            verdict = rv.get("verdict_override") or derive_verdict(rel, a.get("delta"))
            if verdict not in VERDICTS:
                problems.append(f"{ticker}@{to_time}: unknown verdict {verdict!r}")
                verdict = "not_reviewed"
            row["state"] = verdict
            row["source_ids"] = [x.get("id") for x in srcs]
            row["note"] = rv.get("note") or ""
            row["window"] = {"from": rv.get("window_from"), "to": rv.get("window_to")}
            stamps = [x.get("fetched_at") for x in srcs if x.get("fetched_at")]
            row["reviewed_at"] = max(stamps) if stamps else None
            text = json.dumps({"n": row["note"], "l": row["links"], "m": ledger.get("method")},
                              ensure_ascii=False).lower()
            for w in BANNED:
                if w in text:
                    problems.append(f"{ticker}@{to_time}: causal wording {w!r} is not what this page may say")
        out_rows.append(row)

    refuse(problems)

    reviewed = [r for r in out_rows if r["state"] != "not_reviewed"]
    counts = {
        "archive_total": len(out_rows),
        "reviewed": len(reviewed),
        "not_reviewed": len(out_rows) - len(reviewed),
        "external_move_coincides": sum(1 for r in out_rows if r["state"].startswith("external_move_coincides")),
        "no_external_move_supporting": sum(1 for r in out_rows if r["state"].startswith("no_external_move")),
        "links_shown": sum(len(r["links"]) for r in out_rows),
    }
    return {
        "schema": 1,
        "generated_at": utcnow(),
        "snapshot_collected_at": markets.get("collected_at"),
        "ledger": "data/catalyst_review.json",
        "ledger_reviewed_by": ledger.get("reviewed_by_session"),
        "threshold_dollars": (json.loads((ROOT / "data" / "alert_rules.json").read_text())).get("swing_threshold_dollars"),
        "method": ledger.get("method"),
        "counts": counts,
        "alerts": out_rows,
        "disclaimers": [
            "A link here is a fetched reading of the reference a market settles on, next to the minute the swing was recorded. It does not explain why the price moved, and this project does not claim that it does.",
            "Prices are last-traded prices from the Kalshi DEMO environment, where Kalshi states prices and behaviour may not reflect real markets: https://docs.kalshi.com/getting_started/demo_env",
            "A swing can be one small print in a thin book. Where the ledger records 24h volume and the bid/ask around the print, they are shown so the size of the move can be weighed against the size of the trade.",
            "not_reviewed means nobody in this project has read that market's reference for that minute yet. It is not a statement that no news existed.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="build data/live/catalysts.json from the review ledger")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    doc = build()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    c = doc["counts"]
    print(f"OK: {c['reviewed']}/{c['archive_total']} swings carry a fetched source link "
          f"({c['external_move_coincides']} where the reference moved in the same window, "
          f"{c['no_external_move_supporting']} where it did not); {c['not_reviewed']} not_reviewed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
