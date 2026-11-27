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
NEVER_IN_SCOPE = {"Test", "Demo"}  # GET /series categories of the exchange's own test instruments

COMPATIBLE = {
    "gas": {"Economics", "Commodities", "Financials"},
    "elections": {"Elections"},
    "culture": {"Entertainment", "Culture", "Pop Culture", "Awards", "Media"},
    "crypto": {"Crypto", "Financials"},
    "golf": {"Sports", "Golf"},
}

errors: list[str] = []
archive_only = 0
candle_only = 0
ev_counts: dict = {}
quote_rows = 0      # archived rows carrying evidence.quote (49BA-1)
quote_outside = 0   # ...of which the printed end price sat outside the recorded quote


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


def qnum(v):
    """float or None, for the quote check's own recomputation (49BA-1)."""
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def iso_z(v: str) -> bool:
    try:
        datetime.strptime(str(v), "%Y-%m-%dT%H:%M:%SZ")
        return True
    except (ValueError, TypeError):
        return False


def main() -> int:
    global archive_only, candle_only, quote_rows, quote_outside
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
                 "counter_reset", "candle_unquantified", "unknown_no_observations")
    ev_counts.clear()
    ev_counts.update({s: 0 for s in ev_states})
    quote_rows = 0
    quote_outside = 0
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
        # 49BA-1: the quote check is recomputed here from the row's OWN recorded fields, with a
        # deliberately separate implementation, and must match. A print outside the two-sided
        # quote of the same read has to be labelled outside_quote with the distance recorded --
        # that is the one case a trader must not read as an executable move.
        q = ev.get("quote")
        if isinstance(q, dict):
            quote_rows += 1
            q_price = qnum(a.get("to_price"))
            q_bid = qnum(a.get("to_yes_bid"))
            q_ask = qnum(a.get("to_yes_ask"))
            if q_price is not None and q_bid is not None and q_ask is not None \
                    and -1e-9 <= q_bid <= q_ask + 1e-9 <= 1.0 + 1e-9:
                inside = q_bid - 1e-9 <= q_price <= q_ask + 1e-9
                want = "inside_quote" if inside else "outside_quote"
                check(q.get("state") == want,
                      f"{tag} quote.state {q.get('state')!r} contradicts the recorded fields "
                      f"(last {q_price}, bid {q_bid}, ask {q_ask} => {want})")
                if inside:
                    check(q.get("outside_by_dollars") in (0, 0.0, None),
                          f"{tag} inside_quote must not record a distance, got "
                          f"{q.get('outside_by_dollars')!r}")
                else:
                    want_by = round(max(q_bid - q_price, q_price - q_ask, 0.0), 4)
                    check(q.get("outside_by_dollars") == want_by,
                          f"{tag} outside_by_dollars {q.get('outside_by_dollars')!r} != "
                          f"recomputed {want_by}")
                    quote_outside += 1
                check(q.get("spread_dollars") == round(q_ask - q_bid, 4),
                      f"{tag} quote.spread_dollars does not recompute from the recorded quote")
            else:
                check(q.get("state") == "unknown_quote",
                      f"{tag} has no usable recorded quote, so quote.state must be "
                      f"unknown_quote (got {q.get('state')!r})")
                check(q.get("outside_by_dollars") is None,
                      f"{tag} unknown_quote must not record a distance")
            # A quote must never be invented: whatever the block says it used, the numbers must
            # equal the row's own recorded fields. The fallback to the bounding observation is
            # named in quote_source and may only differ for rows that carry no quote at all.
            if a.get("to_yes_bid") is not None and a.get("to_yes_ask") is not None:
                check(q.get("to_yes_bid") == qnum(a.get("to_yes_bid"))
                      and q.get("to_yes_ask") == qnum(a.get("to_yes_ask")),
                      f"{tag} quote bid/ask differ from the row's recorded to_yes_bid/to_yes_ask")
                check("alert.to_yes_bid" in str(q.get("quote_source", "")),
                      f"{tag} quote used a fallback source although the row carries a quote")
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
        if (p0.get("source") or "rest") != "rest" or (p1.get("source") or "rest") != "rest":
            check(state == "candle_unquantified",
                  f"{tag} is bounded by a candle-backfill observation, so it must be labelled "
                  f"candle_unquantified (got {state!r}): candlestick volume_fp is per period")
            check(ev.get("contracts_traded") is None,
                  f"{tag} candle-derived interval count must stay null")
            continue
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
    # 49BA-1: a feed either carries the quote block on every row (build_alerts writes it for the
    # whole archive) or predates it. A partial block is refused rather than tolerated, so the
    # check cannot decay into an exemption: as soon as one row has it, every row must.
    if quote_rows:
        check(quote_rows == len(archive or []),
              f"evidence.quote is present on {quote_rows} of {len(archive or [])} archived rows; "
              f"a feed that carries the quote check must carry it on every row (49BA-1)")

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
        cats = _official(a.get("ticker") or "")
        # Scope: an exchange-test series is never an event in the five topics; an alert with
        # no confirmed topic is withheld rather than shown under a guessed one.
        if any(c in NEVER_IN_SCOPE for c in cats):
            return False
        cat = a.get("category_id")
        if not cat:
            return False
        compatible = COMPATIBLE.get(cat, set())
        # No official categories recorded: unknown is not a contradiction (same as the builder).
        if not cats:
            return True
        return any(c in compatible for c in cats)

    counts = alerts_doc.get("counts") or {}
    served = [a for a in archive if _served(a)]
    withheld_expected = len(archive) - len(served)
    check(counts.get("withheld_category_conflict", 0) + counts.get("withheld_out_of_scope", 0) == withheld_expected,
          f"counts.withheld_category_conflict + counts.withheld_out_of_scope must be {withheld_expected} when "
          f"reproduced from series_index, got {counts.get('withheld_category_conflict')!r} + "
          f"{counts.get('withheld_out_of_scope')!r} (F-65, F-76)")
    # A topic restored from GET /series (category_assigned_from) must be the ONLY topic that
    # accepts that series; an ambiguous or contradicted assignment fails the build.
    #
    # A8D3: an UNKNOWN series is not a contradiction. The ledger only covers series that have a
    # row in the CURRENT snapshot window, so a resolved event's series drops out of it as its
    # market leaves the scan - while the archived alert keeps the topic GET /series confirmed
    # when it was written. Treating that gap as a contradiction stopped the collector committing
    # at all: measured 2026-11-27T18:29Z..19:38Z, every relay pass failed with
    # "archive:KXAAAGASD-26NOV21-3.6600@2026-11-20T22:41:00Z assigned topic 'gas' but GET /series
    # categories [] accept []" (KXAAAGASD's rows had aged out of the ledger) and the published
    # snapshot stayed frozen at 18:00:57Z. `build_alerts.py` already applies exactly this rule to
    # a row with no categories ("unknown is not a contradiction"), so the validator now states it
    # too, counts the rows it applies to, and still refuses a PROVABLE contradiction.
    unverifiable_series = 0
    for a in archive:
        if not a.get("category_assigned_from"):
            continue
        cats = _official(a.get("ticker") or "")
        if not cats:
            unverifiable_series += 1
            continue
        topics = sorted(t for t, comp in COMPATIBLE.items() if set(cats) & comp)
        check(topics == [a.get("category_id")],
              f"archive:{a.get('ticker')}@{a.get('to_time')} assigned topic {a.get('category_id')!r} "
              f"but GET /series categories {cats!r} accept {topics!r}")
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
        # The published block describes the SERVED feeds (the archive also holds rows withheld as
        # out of scope or as a category conflict), so it is recomputed over exactly the rows that
        # were served and must equal them state by state. Comparing it with the whole archive
        # would let a published ratio quietly under-count while the check still passed.
        served_keys = {(a.get("ticker"), a.get("from_time"), a.get("to_time")) for a in served}
        ev_served = {st: 0 for st in ev_states}
        for a in archive or []:
            key = (a.get("ticker"), a.get("from_time"), a.get("to_time"))
            if key not in served_keys:
                continue
            st = (a.get("evidence") or {}).get("state")
            if st in ev_served:
                ev_served[st] += 1
        for st in ev_states:
            check(ev_pub.get(st) == ev_served[st],
                  f"counts.evidence.{st} {ev_pub.get(st)} != recomputed {ev_served[st]} "
                  f"over the served rows")
        check(sum(ev_served.values()) == len(served),
              f"counts.evidence states must partition the {len(served)} served rows, "
              f"got {sum(ev_served.values())}")
        check(sum(ev_counts.values()) == len(archive),
              f"recomputed evidence states must partition the {len(archive)} archived rows, "
              f"got {sum(ev_counts.values())}")
    # 49BA-1: the published quote counts describe the SERVED rows and must equal a recomputation
    # over exactly those rows (an absent block on a served row counts as unknown_quote).
    #
    # A feed built before this check exists carries neither the per-row block (refused above as
    # soon as ONE row has it) nor this count block. That state is named in the output instead of
    # failing the build, because the committed snapshot on main is written by the collector, not
    # by the branch that adds the check; scripts/tests/test_quote_check_build.py is what proves the
    # BUILDER always writes it, so a regression that stops writing it fails a test immediately.
    qc_pub = (alerts_doc.get("counts") or {}).get("quote_check")
    if quote_rows == 0 and qc_pub is None:
        print("note: this feed predates the per-row quote check (49BA-1); no quote block is "
              "present and none is expected until the next collector pass writes one")
    else:
        check(isinstance(qc_pub, dict), "alerts.json counts.quote_check missing (49BA-1)")
    if isinstance(qc_pub, dict):
        served_keys_q = {(a.get("ticker"), a.get("from_time"), a.get("to_time")) for a in served}
        qc_want = {"inside_quote": 0, "outside_quote": 0, "unknown_quote": 0}
        for a in archive or []:
            if (a.get("ticker"), a.get("from_time"), a.get("to_time")) not in served_keys_q:
                continue
            st = (((a.get("evidence") or {}).get("quote")) or {}).get("state")
            qc_want[st if st in qc_want else "unknown_quote"] += 1
        for st in ("inside_quote", "outside_quote", "unknown_quote"):
            check(st in qc_pub, f"counts.quote_check must always publish {st}")
            check(qc_pub.get(st) == qc_want[st],
                  f"counts.quote_check.{st} {qc_pub.get(st)!r} != recomputed {qc_want[st]} "
                  f"over the served rows (49BA-1)")
        check(qc_pub.get("rows") == len(served),
              f"counts.quote_check.rows {qc_pub.get('rows')!r} != the {len(served)} served rows")
        check(qc_pub.get("outside_quote", 0) <= qc_pub.get("rows", 0) >= qc_pub.get("inside_quote", 0),
              "counts.quote_check states cannot exceed the number of served rows")
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
    # One exclusion, stated rather than silent: a pair of observations is only re-derived when
    # both are REST reads of last_price_dollars. A candle-backed point carries the candle CLOSE
    # for that period, which is not the same quantity as a REST last_price read at a minute
    # boundary (a closed market's final candle can print a settlement-side close), so a swing
    # across one is verified by the archive itself and NOT re-derived here. The number of
    # excluded pairs is printed, and every such alert still has to pass the evidence block
    # above, which forces it to say that its contract count is unquantifiable.
    hist = load(LIVE / "price_history.json")
    if hist:
        recomputed: dict[tuple, dict] = {}
        candle_pairs: set = set()
        for ticker, entry in (hist.get("series") or {}).items():
            obs = sorted(entry.get("observations") or [], key=lambda o: o.get("t") or "")
            for prev, cur in zip(obs, obs[1:]):
                p0, p1 = prev.get("last"), cur.get("last")
                t0, t1 = prev.get("t"), cur.get("t")
                if p0 is None or p1 is None or not t0 or not t1 or t1 <= t0:
                    continue
                if (prev.get("source") or "rest") != "rest" or (cur.get("source") or "rest") != "rest":
                    candle_pairs.add((ticker, t0, t1))
                    continue
                d = round(float(p1) - float(p0), 6)
                if abs(d) + 1e-9 >= threshold:
                    recomputed[(ticker, t0, t1)] = {"delta": d, "from": float(p0), "to": float(p1)}
        fresh = 0
        for a in archive:
            key = (a.get("ticker"), a.get("from_time"), a.get("to_time"))
            truth = recomputed.pop(key, None)
            if truth is None:
                if key in candle_pairs:
                    candle_only += 1     # verified via the archive; see the note above
                else:
                    archive_only += 1    # market pruned from price history — the archive's purpose
                continue
            fresh += 1
            tag = f"archive:{a['ticker']}@{a['to_time']}"
            check(abs(truth["delta"] - float(a["delta"])) <= 1e-6, f"{tag} delta differs from recomputed {truth['delta']}")
            check(abs(truth["from"] - float(a["from_price"])) <= 1e-6, f"{tag} from_price differs from recomputed")
            check(abs(truth["to"] - float(a["to_price"])) <= 1e-6, f"{tag} to_price differs from recomputed")
        missing = sorted(recomputed.keys())
        check(not missing,
              f"{len(missing)} re-derivable swing(s) missing from the archive, e.g. {[k[0] + '@' + k[2] for k in missing[:3]]}")

    if unverifiable_series:
        print(f"note: {unverifiable_series} archived alert(s) cite a series the current snapshot no "
              f"longer carries in series_index; the topic stored with them came from GET /series "
              f"and is kept, not re-contradicted (unknown is not a contradiction)")
    return finish(len(archive or []), fresh)


def finish(total: int, fresh: int) -> int:
    if errors:
        print("INVALID alert data:", file=sys.stderr)
        for e in errors[:40]:
            print(f"  - {e}", file=sys.stderr)
        return 1
    ev_note = ""
    if quote_rows:
        print(f"quote check (49BA-1): {quote_rows} rows recomputed, {quote_outside} printed "
              f"outside the recorded quote")
    if ev_counts:
        ev_note = (f"evidence: {ev_counts['traded_ge_floor']} traded >= floor, "
                   f"{ev_counts['traded_below_floor']} thin, {ev_counts['quote_only']} quote-only, "
                   f"{ev_counts['counter_reset']} volume-n/a, "
                   f"{ev_counts['candle_unquantified']} candle-sourced, "
                   f"{ev_counts['unknown_no_observations']} no-history; ")
    print(f"OK: {total} archived alerts provenance-checked "
          f"({ev_note}"
          f"({fresh} re-derived from price_history.json, {archive_only} archive-only — market pruned "
          f"from history, {candle_only} bounded by a candle-backfill read), "
          f"feeds and high_roi screen reproduce from alert_rules.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
