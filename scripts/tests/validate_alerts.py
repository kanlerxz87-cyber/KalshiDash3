#!/usr/bin/env python3
"""Validate data/live/alerts.json by RECOMPUTING every alert from price_history.json.

This is a provenance check, not just a schema check: an alert is only valid if the same
>= $0.10 diff can be re-derived from the committed observations, and every re-derivable
diff must appear in the file. A fabricated or stale alert fails the build.

Run: python3 scripts/tests/validate_alerts.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "data" / "live"
CATEGORY_IDS = {"gas", "elections", "culture", "crypto", "golf"}
ALLOWED_RESULTS = {None, "yes", "no", "scalar", ""}

errors: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def fnum(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    alerts_path = LIVE / "alerts.json"
    hist_path = LIVE / "price_history.json"
    if not alerts_path.exists():
        print("skip: no alerts.json yet")
        return 0
    doc = json.loads(alerts_path.read_text())

    check(doc.get("schema") == 1, "schema must be 1")
    check(doc.get("environment") == "demo", "environment must be demo")
    check(doc.get("base_url") == "https://external-api.demo.kalshi.co/trade-api/v2", "wrong base_url")
    check(doc.get("threshold_dollars") == 0.10, "threshold must be the required 0.10")
    check(bool(doc.get("threshold_note")), "threshold_note missing (threshold must be labelled a project requirement)")
    check(isinstance(doc.get("sources"), dict) and doc["sources"], "sources block missing")
    check(bool(doc.get("disclaimers")), "disclaimers missing")
    try:
        datetime.strptime(doc.get("generated_at", ""), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errors.append(f"generated_at not ISO-8601 Z: {doc.get('generated_at')!r}")

    alerts = doc.get("alerts")
    check(isinstance(alerts, list), "alerts must be a list")

    # ---- recompute ground truth from the committed observations ----
    recomputed: dict[tuple, dict] = {}
    if hist_path.exists():
        hist = json.loads(hist_path.read_text())
        for ticker, entry in (hist.get("series") or {}).items():
            obs = sorted(entry.get("observations") or [], key=lambda o: o.get("t") or "")
            for i in range(1, len(obs)):
                prev, cur = obs[i - 1], obs[i]
                p0, p1 = fnum(prev.get("last")), fnum(cur.get("last"))
                t0, t1 = prev.get("t"), cur.get("t")
                if p0 is None or p1 is None or not t0 or not t1 or t1 <= t0:
                    continue
                d = round(p1 - p0, 6)
                if abs(d) + 1e-12 >= 0.10:
                    recomputed[(ticker, t0)] = {
                        "delta": d, "from": round(p0, 6), "to": round(p1, 6), "to_ts": t1,
                    }

    seen: set[tuple] = set()
    for a in alerts or []:
        tag = f"alert:{a.get('ticker')}@{a.get('to_ts')}"
        key = (a.get("ticker"), a.get("from_ts"))
        check(key not in seen, f"{tag} duplicate alert for the same from-observation")
        seen.add(key)

        check(str(a.get("source", "")).startswith("https://"), f"{tag} source must be https")
        check(a.get("observed_basis") == "api_diff", f"{tag} observed_basis must be api_diff")
        check(a.get("category_id") is None or a.get("category_id") in CATEGORY_IDS,
              f"{tag} bad category_id {a.get('category_id')!r}")
        check(a.get("result") in ALLOWED_RESULTS, f"{tag} illegal result {a.get('result')!r}")
        for f in ("from_price_dollars", "to_price_dollars"):
            check(a.get(f) is None or 0.0 <= float(a[f]) <= 1.0, f"{tag} {f} outside 0..1")
        for f in ("from_ts", "to_ts"):
            try:
                datetime.strptime(str(a.get(f, "")), "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                errors.append(f"{tag} {f} not ISO-8601 Z: {a.get(f)!r}")
        check(str(a.get("from_ts", "")) < str(a.get("to_ts", "")), f"{tag} from_ts must precede to_ts")

        d = a.get("delta_dollars")
        check(d is not None and abs(float(d)) >= 0.10 - 1e-9, f"{tag} delta below the 0.10 threshold")
        calc = round(float(a["to_price_dollars"]) - float(a["from_price_dollars"]), 6)
        check(d is not None and abs(calc - float(d)) <= 1e-9, f"{tag} delta does not equal to - from")
        check(("up" if d > 0 else "down") == a.get("direction"), f"{tag} direction contradicts delta sign")

        # Provenance: the same diff must be re-derivable from the observations.
        truth = recomputed.get(key)
        check(truth is not None, f"{tag} NOT re-derivable from price_history.json — possible fabrication or stale snapshot")
        if truth:
            check(abs(truth["delta"] - float(d)) <= 1e-9, f"{tag} delta differs from recomputed {truth['delta']}")
            check(abs(truth["from"] - float(a["from_price_dollars"])) <= 1e-9, f"{tag} from price differs from recomputed")
            check(abs(truth["to"] - float(a["to_price_dollars"])) <= 1e-9, f"{tag} to price differs from recomputed")

    # Completeness: every re-derivable swing must be in the file.
    missing = [k for k in recomputed if k not in seen]
    check(not missing, f"{len(missing)} re-derivable swing(s) missing from alerts.json, e.g. {sorted(missing)[:3]}")

    counts = doc.get("counts") or {}
    check(counts.get("alerts") == len(alerts or []), "counts.alerts does not match the alerts list length")

    if errors:
        print("INVALID alerts.json:", file=sys.stderr)
        for e in errors[:40]:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(alerts or [])} alerts, all re-derived from {len(recomputed)} recomputed swings "
          f"in price_history.json (provenance verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
