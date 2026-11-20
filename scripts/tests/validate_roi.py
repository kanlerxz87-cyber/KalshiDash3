#!/usr/bin/env python3
"""Honesty + schema gate for data/live/roi.json, run before it is committed.

This is not a data check — it is a fabrication check. It refuses a scan that:
  * carries no provenance (base_url, collected_at, model hash, per-row source URL)
  * reports a swing alert whose change is below the model's own threshold
  * reports a pick that fails one of the model's own filters, or whose prices are
    outside 0..1, or whose entry is on a side the market does not quote
  * labels a keyword-only topic match as confirmed
  * hides behind a number where the API returned nothing (null must stay null)

Run: python3 scripts/tests/validate_roi.py [path]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT = ROOT / "data" / "live" / "roi.json"
ALLOWED_RESULT = {None, "", "yes", "no", "scalar"}

errors: list[str] = []
warns: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        print(f"skip: {path.relative_to(ROOT)} not written yet (desk workflow has not run)")
        return 0
    doc = json.loads(path.read_text())
    model = json.loads((ROOT / "data" / "roi_model.json").read_text())
    thr = float(model["swing_alert"]["threshold_dollars"])
    filters = model["parameters"]["filters"]

    check(doc.get("schema") == 1, "schema must be 1")
    check(doc.get("environment") == "demo", "environment must be demo — this project never presents demo data as production")
    for k in ("base_url", "collected_at", "sources", "disclaimers", "model", "counts"):
        check(bool(doc.get(k)), f"{k} missing — a scan without provenance is not publishable")
    try:
        datetime.strptime(doc.get("collected_at", ""), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append("collected_at is not an ISO-8601 Z timestamp")
    check(str(doc.get("base_url", "")).startswith("https://"), "base_url must be https")
    check("demo" in str(doc.get("base_url", "")), "base_url must be the demo host")

    for a in doc.get("alerts") or []:
        tag = f"alert {a.get('ticker')}@{a.get('t')}"
        check(abs(float(a.get("delta") or 0)) + 1e-9 >= thr,
              f"{tag}: |Δ|={a.get('delta')} is below the {thr} threshold — this must not be in the feed")
        check(a.get("direction") in ("up", "down"), f"{tag} bad direction")
        check(str(a.get("source", "")).startswith("https://"), f"{tag} has no https source link")
        for p in (a.get("from"), a.get("to")):
            check(p is None or 0.0 <= float(p) <= 1.0, f"{tag} price {p} outside 0..1")
        check(a.get("category_id") in {"gas", "elections", "culture", "crypto", "golf"}, f"{tag} out-of-scope category")
        for c in a.get("catalysts") or []:
            check(str(c.get("url", "")).startswith(("http://", "https://")), f"{tag} catalyst is not a URL")

    for key in ("picks", "near_misses", "unscoreable"):
        for p in doc.get(key) or []:
            tag = f"{key} {p.get('ticker')}"
            check(str(p.get("source", "")).startswith("https://"), f"{tag} has no https source link")
            e = p.get("entry") or {}
            if key == "unscoreable":
                # by definition there is no priced side here; the only honest output is the
                # reason, and a reason must therefore exist
                check(not e, f"{tag} is listed as unscoreable but carries an entry")
                check(bool(p.get("reasons")), f"{tag} unscoreable without a stated reason")
                continue
            check(e.get("side") in ("YES", "NO"), f"{tag} entry side {e.get('side')!r}")
            for f in ("entry", "cost", "roi", "fee_unit", "ev"):
                v = e.get(f)
                check(v is None or isinstance(v, (int, float)), f"{tag}.{f} must be a number or null, got {v!r}")
            if e.get("entry") is not None:
                check(0.0 <= float(e["entry"]) <= 1.0, f"{tag} entry price outside 0..1")
            for f in ("bid", "ask", "last"):
                v = p.get(f)
                check(v is None or 0.0 <= float(v) <= 1.0, f"{tag}.{f}={v} outside 0..1")
            check(p.get("result") in ALLOWED_RESULT, f"{tag} illegal result {p.get('result')!r}")
            if p.get("category_basis") == "keyword":
                check(key == "near_misses" or not filters.get("require_seed_category"),
                      f"{tag} is a keyword-only match and must not be presented as a pick")
            if key == "picks":
                check(bool(p.get("eligible")), f"{tag} is in picks but is not eligible")
                check(not (p.get("fails") or []), f"{tag} is in picks but carries failing gates {p.get('fails')}")
                if p.get("score") is not None:
                    check(float(p["score"]) > float(filters["min_net_roi"]),
                          f"{tag} is in picks with a non-positive ROI {p['score']}")
            else:
                check(not p.get("eligible"), f"{tag} is in near_misses but is eligible — it belongs in picks")
            for c in p.get("catalysts") or []:
                check(str(c.get("url", "")).startswith(("http://", "https://")), f"{tag} catalyst is not a URL")

    v = doc.get("validation") or {}
    if v and v.get("signals"):
        check(0.0 <= float(v["hit_rate"]) <= 1.0, "validation.hit_rate must be a fraction")
        check(v.get("markets_tested", 0) > 0, "validation reports signals but no markets were tested")
        check(bool(v.get("method")) and bool(v.get("not_measured")),
              "validation must state its method AND what it could not measure")
    if not (doc.get("picks") or []):
        warns.append("no picks in this scan (normal: the screen demands a positive edge after fees)")

    if errors:
        try:
            shown = str(path.relative_to(ROOT))
        except ValueError:
            shown = str(path)
        print(f"INVALID scan {shown}:", file=sys.stderr)
        for e in errors[:40]:
            print("  -", e, file=sys.stderr)
        return 1
    try:
        shown = str(path.relative_to(ROOT))
    except ValueError:
        shown = str(path)
    print(f"OK {shown}: {len(doc.get('picks') or [])} picks, {len(doc.get('near_misses') or [])} near misses, "
          f"{len(doc.get('alerts') or [])} alerts, collected_at={doc.get('collected_at')} — "
          "provenance present, no sub-threshold alert, no ineligible pick, no coerced result.")
    for w in warns:
        print("  warn:", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
