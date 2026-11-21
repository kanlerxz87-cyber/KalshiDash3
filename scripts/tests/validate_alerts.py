#!/usr/bin/env python3
"""Validate the canonical alert pipeline by RECOMPUTING every swing from the
committed observations, reproducing the feeds from the archive + rules, and
enforcing the no-invention guarantees.

Validates (schema of session arena-5225610f / arena-e5adea9d, canonical on main):
  data/live/alerts_archive.json  append-only archive of >= $0.10 swings
  data/live/alerts.json          feeds (all_events, high_roi) rendered from the archive
  data/alert_rules.json          threshold + experimental screen rules

Checks
  1. schemas and provenance blocks present; threshold == 0.10 (project requirement)
  2. every alert: prices in 0..1, delta == to_price - from_price, |delta| >= threshold,
     direction sign, from_time < to_time, ISO-8601 Z stamps, https market_source
  3. no invented causes: cause_link must be null and cause_status must state unverified
  4. feeds reproduce exactly from the archive (order + membership + counts)
  5. the high_roi screen reproduces from the rules against each archive row's OWN
     recorded category_basis/volume_24h_fp (detection-time values), so the check does
     not depend on which snapshot happens to be on disk; the snapshot is a fallback
     for legacy rows without those fields
  6. evidence (T66): every alert carries `evidence`, the block that says whether contracts
     actually traded between its two observations. The contract count is RECOMPUTED from the
     committed volume_fp readings and must match exactly; a state that a recalculation
     contradicts is refused. Quote-only swings (zero contracts traded) must be labelled as such,
     and an interval whose cumulative volume did not increase must leave the count null instead
     of recording a negative number.
  7. provenance: every alert whose market still has both observations in
     price_history.json must match the recomputed diff exactly; every re-derivable
     swing must be present in the archive. Alerts whose market was pruned from the
     collector's price history are allowed (that is why the archive exists) and are
     counted as archive-only.

Run: python3 scripts/tests/validate_alerts.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LIVE = ROOT / "data" / "live"
RULES = ROOT / "data" / "alert_rules.json"

# F-65: restated rather than imported from scripts/collect.py so this validator can refuse a
# snapshot written by a broken collector. Values are the official categories/tags recorded by
# GET /series for each topic; see data/categories.json and
# https://docs.kalshi.com/api-reference/market/get-series-list
COMPATIBLE = {
    "gas": {"Economics", "Commodities", "Financials"},
    "elections": {"Elections", "Politics", "World", "International"},
    "culture": {"Entertainment", "Culture", "Pop Culture", "Awards", "Media"},
    "crypto": {"Crypto", "Financials"},
    "golf": {"Sports", "Golf"},
}

errors: list[str] = []
archive_only = 0
ev_counts: dict = {}


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"{path.name}: invalid JSON ({e})")
        return None


def iso_z(v: str) -> bool:
    try:
        datetime.strptime(str(v), "%Y-%m-%dT%H:%M:%SZ")
        return True
    except (ValueError, TypeError):
        return False


def main() -> int:
    global archive_only
    alerts_doc = load(LIVE / "alerts.json")
    archive_doc = load(LIVE / "alerts_archive.json")
    rules = load(RULES)
    if alerts_doc is None and archive_doc is None:
        print("skip: no alert data yet")
        return 0
    if archive_doc is None:
        errors.append("alerts_archive.json missing while alerts.json exists")
        return finish(0, 0)
    if alerts_doc is None:
        errors.append("alerts.json missing while alerts_archive.json exists")
        return finish(0, 0)
    if rules is None:
        errors.append("data/alert_rules.json missing")
        return finish(0, 0)

    threshold = float(rules.get("swing_threshold_dollars", -1))
    check(threshold == 0.10, f"swing_threshold_dollars must be the required 0.10, got {threshold}")

    # ---- archive schema + per-alert invariants ----
    archive = archive_doc.get("alerts")
    check(archive_doc.get("schema") == 1, "archive schema must be 1")
    check(isinstance(archive, list), "archive.alerts must be a list")
    seen_keys = set()
    for a in archive or []:
        tag = f"archive:{a.get('ticker')}@{a.get('to_time')}"
        key = (a.get("ticker"), a.get("from_time"), a.get("to_time"))
        check(key not in seen_keys, f"{tag} duplicate archive entry")
        seen_keys.add(key)
        for f in ("from_price", "to_price"):
            check(isinstance(a.get(f), (int, float)) and 0.0 <= float(a[f]) <= 1.0, f"{tag} {f} outside 0..1")
        d = a.get("delta")
        check(isinstance(d, (int, float)), f"{tag} delta missing")
        if isinstance(d, (int, float)):
            calc = round(float(a["to_price"]) - float(a["from_price"]), 6)
            check(abs(calc - float(d)) <= 1e-6, f"{tag} delta {d} != to_price - from_price ({calc})")
            check(abs(float(d)) + 1e-9 >= threshold, f"{tag} |delta| below the {threshold} threshold")
            check(("up" if d > 0 else "down") == a.get("direction"), f"{tag} direction contradicts delta sign")
        check(iso_z(a.get("from_time")) and iso_z(a.get("to_time")), f"{tag} timestamps not ISO-8601 Z")
        check(str(a.get("from_time", "")) < str(a.get("to_time", "")), f"{tag} from_time must precede to_time")
        check(str(a.get("market_source", "")).startswith("https://"), f"{tag} market_source must be https")
        check(a.get("cause_link") is None, f"{tag} cause_link must stay null (no official cause source — F-25)")
        check("unverified" in str(a.get("cause_status", "")), f"{tag} cause_status must state unverified")
        check(isinstance(a.get("high_roi"), bool), f"{tag} high_roi must be a boolean")

    # ---- evidence layer (T66) ----
    # Recomputed here from the committed observations, independent of scripts/alert_evidence.py's
    # own copy of the rule, so a bug in the classifier cannot validate itself.
    hist_for_evidence = load(LIVE / "price_history.json") or {}
    ev_series = hist_for_evidence.get("series") or {}
    ev_states = ("traded_ge_floor", "traded_below_floor", "quote_only",
                 "counter_reset", "unknown_no_observations")
    ev_counts.clear()
    ev_counts.update({s: 0 for s in ev_states})
    floor = float((rules.get("evidence") or {}).get("floor_contracts", 100.0))
    for a in archive or []:
        tag = f"archive:{a.get('ticker')}@{a.get('to_time')}"
        ev = a.get("evidence")
        check(isinstance(ev, dict), f"{tag} evidence block missing (T66)")
        if not isinstance(ev, dict):
            continue
        state = ev.get("state")
        check(state in ev_states, f"{tag} evidence.state {state!r} is not one of {ev_states}")
        if state in ev_states:
            ev_counts[state] += 1
        check(ev.get("policy_floor_is_a_kalshi_field") is False,
              f"{tag} evidence must disclose that the floor is a project rule, not a Kalshi field")
        check(isinstance(ev.get("why"), str) and ev.get("why"), f"{tag} evidence.why must explain the state")
        obs = sorted(((ev_series.get(a.get("ticker")) or {}).get("observations") or []),
                     key=lambda o: o.get("t") or "")
        by_t = {o.get("t"): o for o in obs}
        p0, p1 = by_t.get(a.get("from_time")), by_t.get(a.get("to_time"))
        if p0 is None or p1 is None:
            check(state == "unknown_no_observations",
                  f"{tag} has no committed observations but is labelled {state!r}")
            check(ev.get("contracts_traded") is None,
                  f"{tag} no observations, so contract count must stay null")
            continue
        def fnum(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        v0, v1 = fnum(p0.get("volume_fp")), fnum(p1.get("volume_fp"))
        if v0 is None or v1 is None or v1 < v0:
            check(state == "counter_reset", f"{tag} volume does not increase but is labelled {state!r}")
            check(ev.get("contracts_traded") is None,
                  f"{tag} interval count is unknowable, so it must stay null (got {ev.get('contracts_traded')!r})")
            continue
        traded = round(v1 - v0, 2)
        check(ev.get("contracts_traded") == traded,
              f"{tag} contracts_traded {ev.get('contracts_traded')!r} != volume_to - volume_from ({traded})")
        want = ("quote_only" if traded == 0
                else "traded_ge_floor" if traded >= floor else "traded_below_floor")
        check(state == want, f"{tag} state {state!r} contradicted by {traded} contracts traded "
                             f"(floor {floor:g}) -> {want!r}")
        if traded == 0:
            check(state == "quote_only", f"{tag} zero contracts traded must be labelled quote_only")

    # ---- feeds reproduce from the archive ----
    # F-65: build_alerts.py withholds an alert whose series the exchange files outside the topic
    # (the ledger is data/live/markets.json -> series_index). The rule is reproduced here from
    # the same ledger so the validator can refuse a feed that silently keeps such a row, and
    # refuse one that drops a legitimate row. Same failure mode as before: a rule that only the
    # writer knows about is a rule nobody can audit.
    MAX = 300
    state = load(LIVE / "markets.json") or {}
    ledger = state.get("series_index") or {}
    row_by_ticker = {r.get("ticker"): r for r in (state.get("open_markets") or [])}

    def _official(ticker: str) -> list:
        row = row_by_ticker.get(ticker) or {}
        if row.get("series_categories"):
            return [str(c) for c in row["series_categories"]]
        series = row.get("series_ticker") or (ticker or "").upper().split("-")[0]
        return [str(c) for c in ((ledger.get(series) or {}).get("categories") or [])]

    def _served(a: dict) -> bool:
        compatible = COMPATIBLE.get(a.get("category_id") or "", set())
        cats = _official(a.get("ticker") or "")
        if not cats or not compatible:
            return True
        return any(c in compatible for c in cats)

    counts = alerts_doc.get("counts") or {}
    served = [a for a in archive if _served(a)]
    withheld_expected = len(archive) - len(served)
    check(counts.get("withheld_category_conflict") == withheld_expected,
          f"counts.withheld_category_conflict must be {withheld_expected} when reproduced from "
          f"series_index, got {counts.get('withheld_category_conflict')!r} (F-65)")
    expected_all = served[:MAX]
    check(alerts_doc.get("all_events") == expected_all, "alerts.json all_events does not reproduce from the archive (order/membership/300 cap)")
    expected_roi = [a for a in served if a.get("high_roi")][:MAX]
    check(alerts_doc.get("high_roi") == expected_roi, "alerts.json high_roi does not reproduce from the archive")
    counts = alerts_doc.get("counts") or {}
    check(counts.get("all_events") == len(alerts_doc.get("all_events") or []), "counts.all_events mismatch")
    check(counts.get("high_roi") == len(alerts_doc.get("high_roi") or []), "counts.high_roi mismatch")
    check(counts.get("archive_total") == len(archive), "counts.archive_total mismatch")
    check(float(alerts_doc.get("threshold_dollars", -1)) == threshold, "alerts.json threshold differs from alert_rules.json")
    check(bool(alerts_doc.get("disclaimers")), "alerts.json disclaimers missing")
    ev_pub = (alerts_doc.get("counts") or {}).get("evidence")
    check(isinstance(ev_pub, dict), "alerts.json counts.evidence missing (T66)")
    if isinstance(ev_pub, dict):
        for st in ev_states:
            check(st in ev_pub, f"counts.evidence must always publish {st}")
        n_traded = ev_pub.get("traded_ge_floor", 0) + ev_pub.get("traded_below_floor", 0)
        check(ev_pub.get("traded_ge_floor") == ev_counts["traded_ge_floor"],
              f"counts.evidence.traded_ge_floor {ev_pub.get('traded_ge_floor')} != recomputed "
              f"{ev_counts['traded_ge_floor']}")
        check(ev_pub.get("quote_only") == ev_counts["quote_only"],
              f"counts.evidence.quote_only {ev_pub.get('quote_only')} != recomputed {ev_counts['quote_only']}")
        check(ev_pub.get("counter_reset") == ev_counts["counter_reset"],
              f"counts.evidence.counter_reset {ev_pub.get('counter_reset')} != recomputed {ev_counts['counter_reset']}")
        check(n_traded + ev_counts["quote_only"] + ev_counts["counter_reset"]
              + ev_counts["unknown_no_observations"] == len(archive),
              "counts.evidence states must partition the whole archive")
    check(iso_z(alerts_doc.get("generated_at")), "alerts.json generated_at not ISO-8601 Z")

    # ---- high_roi screen reproduces from the rules against the ROW ITSELF ----
    # The flag records the screen AT DETECTION TIME. The snapshot rolls every run
    # (markets enter, leave, and their volumes change), so re-deriving against the
    # CURRENT markets.json made this check clock-dependent: the collect run at
    # 2026-11-20T19:42Z failed on KXBTCY-27JAN0100-B47500@19:30:14Z — archived
    # False (volume_24h_fp 0.0 recorded on the row), derived True from a later
    # snapshot. The archive rows carry category_basis and volume_24h_fp precisely
    # so the screen can be reproduced deterministically; the snapshot is consulted
    # only for legacy rows that carry neither field. Disagreement with the current
    # snapshot is reported as drift (F-39), never as a failure.
    markets_path = LIVE / "markets.json"
    snap = load(markets_path)
    roi_rules = rules.get("high_roi") or {}
    if roi_rules:
        req_basis = roi_rules.get("require_category_basis")
        req_gt = roi_rules.get("require_volume_24h_gt", -1)
        by_ticker = {m["ticker"]: m for m in ((snap or {}).get("open_markets") or [])}
        drift = 0
        for a in archive:
            m = by_ticker.get(a.get("ticker", "")) or {}
            basis = a.get("category_basis") if a.get("category_basis") is not None else m.get("category_basis")
            vol = a.get("volume_24h_fp") if a.get("volume_24h_fp") is not None else m.get("volume_24h_fp")
            if basis is None and vol is None:
                continue  # no recorded fields and not in the snapshot: nothing to reproduce
            expected = bool(basis == req_basis and (vol or 0) > req_gt)
            check(a.get("high_roi") == expected,
                  f"archive:{a.get('ticker')}@{a.get('to_time')} high_roi {a.get('high_roi')} contradicts the "
                  f"inputs stored with it (category_basis={basis!r}, "
                  f"volume_24h_fp={vol!r}, rule-derived {expected})")
            if m:
                now = bool(m.get("category_basis") == req_basis
                           and (m.get("volume_24h_fp") or 0) > req_gt)
                if now != expected:
                    drift += 1
        if drift:
            print(f"note: {drift} archived alert(s) whose screen result differs in the CURRENT snapshot — "
                  f"expected and allowed: high_roi is frozen at detection time (volume_24h_fp changes "
                  f"between collections); the flag is verified against each entry's own stored inputs.")

    # ---- provenance: recompute swings from the committed observations ----
    hist = load(LIVE / "price_history.json")
    if hist:
        recomputed: dict[tuple, dict] = {}
        for ticker, entry in (hist.get("series") or {}).items():
            obs = sorted(entry.get("observations") or [], key=lambda o: o.get("t") or "")
            for prev, cur in zip(obs, obs[1:]):
                p0, p1 = prev.get("last"), cur.get("last")
                t0, t1 = prev.get("t"), cur.get("t")
                if p0 is None or p1 is None or not t0 or not t1 or t1 <= t0:
                    continue
                d = round(float(p1) - float(p0), 6)
                if abs(d) + 1e-9 >= threshold:
                    recomputed[(ticker, t0, t1)] = {"delta": d, "from": float(p0), "to": float(p1)}
        fresh = 0
        for a in archive:
            key = (a.get("ticker"), a.get("from_time"), a.get("to_time"))
            truth = recomputed.pop(key, None)
            if truth is None:
                archive_only += 1  # market pruned from price history — the archive's purpose
                continue
            fresh += 1
            tag = f"archive:{a['ticker']}@{a['to_time']}"
            check(abs(truth["delta"] - float(a["delta"])) <= 1e-6, f"{tag} delta differs from recomputed {truth['delta']}")
            check(abs(truth["from"] - float(a["from_price"])) <= 1e-6, f"{tag} from_price differs from recomputed")
            check(abs(truth["to"] - float(a["to_price"])) <= 1e-6, f"{tag} to_price differs from recomputed")
        missing = sorted(recomputed.keys())
        check(not missing,
              f"{len(missing)} re-derivable swing(s) missing from the archive, e.g. {[k[0] + '@' + k[2] for k in missing[:3]]}")

    return finish(len(archive or []), fresh)


def finish(total: int, fresh: int) -> int:
    if errors:
        print("INVALID alert data:", file=sys.stderr)
        for e in errors[:40]:
            print(f"  - {e}", file=sys.stderr)
        return 1
    ev_note = ""
    if ev_counts:
        ev_note = (f"evidence: {ev_counts['traded_ge_floor']} traded >= floor, "
                   f"{ev_counts['traded_below_floor']} thin, {ev_counts['quote_only']} quote-only, "
                   f"{ev_counts['counter_reset']} volume-n/a, "
                   f"{ev_counts['unknown_no_observations']} no-history; ")
    print(f"OK: {total} archived alerts provenance-checked "
          f"({ev_note}"
          f"({fresh} re-derived from price_history.json, {archive_only} archive-only — market pruned from history), "
          f"feeds and high_roi screen reproduce from alert_rules.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
