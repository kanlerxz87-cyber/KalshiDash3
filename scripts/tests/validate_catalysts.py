#!/usr/bin/env python3
"""Refuse a lead file that says more than the ledger can back (data/live/catalysts.json).

The point of this gate is narrow: a "catalyst" feature is the easiest thing on this site to
fabricate, so it is checked harder than the rest.

  1. every link shown must exist in data/catalyst_review.json as a source that was fetched, and
     carry that source's fetched_at;
  2. every number in a row's relation must be present in the cited fetched response;
  3. no row may use causal vocabulary (the same list scripts/catalysts.py enforces at build time,
     re-checked here on the published artefact so a hand-edit cannot slip past);
  4. every archived swing must have exactly one row, and a row with no review must be
     state=not_reviewed with no links;
  5. the file's own provenance (ledger path, generated_at, disclaimers) must be present.

Run: python3 scripts/tests/validate_catalysts.py [path]
Exit: 0 ok, 1 refused, 2 inputs missing.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent.parent
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
BANNED = ("caused", "cause of", "triggers", "triggered", "due to", "led to", "drove the",
          "because of the", "on account of")


def load(p: Path):
    if not p.exists():
        print(f"missing: {p}", file=sys.stderr)
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "live" / "catalysts.json"
    doc = load(path)
    ledger = load(ROOT / "data" / "catalyst_review.json")
    archive = load(ROOT / "data" / "live" / "alerts_archive.json")

    errors: list[str] = []
    check = errors.append

    for k in ("schema", "generated_at", "ledger", "method", "counts", "alerts", "disclaimers"):
        if doc.get(k) in (None, "", [], {}):
            check(f"{k} missing from {path.name}")
    if doc.get("ledger") != "data/catalyst_review.json":
        check("ledger must name data/catalyst_review.json")

    urls, stamps = set(), {}
    for s in ledger.get("sources") or []:
        vals = {s.get("url")} | {v for v in _urls_in(s.get("observed"))}
        for u in vals:
            if u:
                urls.add(u); urls.add(unquote(u)); stamps[u] = s.get("fetched_at"); stamps[unquote(u)] = s.get("fetched_at")
    srcs = {s.get("id"): s for s in ledger.get("sources") or []}
    review_keys = {(r.get("ticker"), r.get("alert_to_time")) for r in ledger.get("reviews") or []}
    archive_keys = {(a.get("ticker"), a.get("to_time")) for a in archive.get("alerts") or []}

    rows = doc.get("alerts") or []
    row_keys = {(r.get("ticker"), r.get("to_time")) for r in rows}
    # F-65: a swing whose own GET /series record puts it outside its topic is withheld from the
    # chats, so this table must omit it too — but the omission has to be COUNTED, not silent.
    # Reproduce the exclusion from the same series_index ledger the builder reads.
    _mp = ROOT / "data" / "live" / "markets.json"
    markets = json.loads(_mp.read_text()) if _mp.exists() else {}
    ledger_series = markets.get("series_index") or {}
    row_by_ticker = {r.get("ticker"): r for b in ("open_markets", "settled_markets")
                     for r in (markets.get(b) or [])}
    compatible = {
        "gas": {"Economics", "Commodities", "Financials"},
        "elections": {"Elections", "Politics", "World", "International"},
        "culture": {"Entertainment", "Culture", "Pop Culture", "Awards", "Media"},
        "crypto": {"Crypto", "Financials"},
        "golf": {"Sports", "Golf"},
    }

    all_compatible = set().union(*compatible.values())
    archive_cat = {(a.get("ticker"), a.get("to_time")): a.get("category_id")
                   for a in archive.get("alerts") or []}

    def _withheld(key) -> bool:
        ticker = key[0] or ""
        snap = row_by_ticker.get(ticker) or {}
        official = [str(c) for c in (snap.get("series_categories") or [])]
        if not official:
            series = snap.get("series_ticker") or ticker.upper().split("-")[0]
            official = [str(c) for c in ((ledger_series.get(series) or {}).get("categories") or [])]
        if not official:
            return False
        # The snapshot row may have been dropped by the collector precisely because it conflicted,
        # so the archived alert's own recorded topic is the fallback; when both are absent
        # (F-75: candle-backfilled row for a closed ticker), check against the union of the five
        # in-scope topics so official ["Test"] series are still withheld.
        cat = snap.get("category_id") or archive_cat.get(key)
        ok = compatible.get(cat or "") or all_compatible
        return not any(o in ok for o in official)

    expected_missing = {k for k in archive_keys if _withheld(k)}
    if (doc.get("counts") or {}).get("withheld_category_conflict") != len(expected_missing):
        check(f"counts.withheld_category_conflict must equal the swings reproduced from series_index "
              f"({len(expected_missing)}, F-65)")
    if row_keys != (archive_keys - expected_missing):
        check(f"rows must cover the archive exactly except the counted F-65 exclusions; "
              f"missing {sorted((archive_keys - expected_missing) - row_keys)[:3]}, "
              f"extra {sorted(row_keys - (archive_keys - expected_missing))[:3]}")
    if len(row_keys) != len(rows):
        check("duplicate rows for one swing")

    for r in rows:
        tag = f"{r.get('ticker')}@{r.get('to_time')}"
        for l in r.get("links") or []:
            u = l.get("url")
            if u not in urls and unquote(u or "") not in urls:
                check(f"{tag}: link is not a source the ledger fetched: {u}")
            if not l.get("fetched_at"):
                check(f"{tag}: link without a fetch time: {u}")
            elif stamps.get(u) and stamps[u] != l["fetched_at"]:
                check(f"{tag}: fetched_at {l['fetched_at']} does not match the ledger ({stamps[u]})")
        for sid in r.get("source_ids") or []:
            if sid not in srcs:
                check(f"{tag}: cites source id {sid!r}, which the ledger does not contain")
        rel = r.get("relation") or {}
        if rel:
            cited = json.dumps([srcs.get(i) for i in (r.get("source_ids")
                                or [x.get("source_id") for x in (r.get("links") or [])])], ensure_ascii=False)
            nums = {float(t) for t in NUM_RE.findall(cited)}
            for k in ("before", "after", "strike"):
                v = rel.get(k)
                if v is None:
                    continue
                if not any(abs(x - float(v)) <= max(5e-2, 1e-6 * abs(float(v))) for x in nums):
                    check(f"{tag}: relation.{k}={v} is not a number in the fetched responses cited")
            b, a_, st = rel.get("before"), rel.get("after"), rel.get("strike")
            if None not in (b, a_, st):
                if abs(rel.get("change", 0) - (a_ - b)) > 1e-6:
                    check(f"{tag}: relation.change does not recompute from the two cited values")
                want = "up" if (b < st <= a_) else ("down" if (a_ < st <= b) else None)
                if rel.get("crossed") != want:
                    check(f"{tag}: relation.crossed contradicts the two cited values")
        text = json.dumps({"note": r.get("note"), "state": r.get("state"), "method": doc.get("method"),
                           "disclaimers": doc.get("disclaimers"),
                           "links": [l.get("publisher") for l in (r.get("links") or [])]},
                          ensure_ascii=False).lower()
        for w in BANNED:
            if w in text:
                check(f"{tag}: causal wording {w!r} is not allowed in a lead")
        reviewed = r.get("state") != "not_reviewed"
        if reviewed and (r.get("ticker"), r.get("to_time")) not in review_keys:
            check(f"{tag}: state claims a review the ledger does not contain")
        if reviewed and not r.get("links"):
            check(f"{tag}: reviewed row with no link — a review must show what was fetched")
        if not reviewed and r.get("links"):
            check(f"{tag}: not_reviewed row must carry no links")
    if errors:
        print("INVALID lead file:", file=sys.stderr)
        for e in errors[:30]:
            print("  -", e, file=sys.stderr)
        return 1
    print(f"OK: {len(rows)} swing leads, {sum(len(r.get('links') or []) for r in rows)} links, each traceable to "
          f"a fetched source in data/catalyst_review.json; no causal wording; every number recomputes")
    return 0


def _urls_in(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _urls_in(v)
    elif isinstance(x, list):
        for v in x:
            yield from _urls_in(v)
    elif isinstance(x, str) and x.startswith("https://"):
        yield x


if __name__ == "__main__":
    sys.exit(main())
