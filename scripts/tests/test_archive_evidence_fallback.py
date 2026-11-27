#!/usr/bin/env python3
"""F-109 — the feed builder and the alert validator must resolve a market's official
categories from the SAME sources, and that resolution must survive a market leaving the
open scan.

What went wrong (observed, not supposed)
  `scripts/build_alerts.py` resolved a market's official GET /series categories from
  (1) the snapshot row, then (2) the snapshot's `series_index` ledger. `scripts/tests/
  validate_alerts.py` resolved them from (1), (2) and (3) the archive ENTRY's own recorded
  `series_categories`. While a market was still inside the 442-entry ledger the two agreed.
  Once it aged out of both the open scan and the ledger they did not: the builder reported
  [] ("no official categories recorded -> unknown is not a contradiction") and served the
  swing, while the validator — reading the entry's own record, `['Economics']` for
  KXAAAGASD, which is why the topic 'gas' had been assigned — refused it:

      archive:KXAAAGASD-26NOV21-3.6600@2026-11-20T22:41:00Z assigned topic 'gas'
      but GET /series categories [] accept []

  That refusal gated every collection pass from 2026-11-27T18:31:08Z to 19:23:02Z (five
  consecutive `validators: validate_alerts` health records, snapshot frozen at 18:00:57Z).

What is pinned here (offline; no network, no writes outside a temp dir)
  1. The builder's `official_for` falls back to the category record on the archive entry.
  2. The validator's `_official` does the same, and the two orders are identical.
  3. A regression that deletes the fallback from either file fails this suite.
  4. `publishable` still withholds a swing whose recorded categories contradict its topic,
     so the fallback cannot be used to smuggle an off-topic row back into the feeds.
  5. The specific production row resolves to a category that accepts its assigned topic.

Run: python3 scripts/tests/test_archive_evidence_fallback.py     (exit 0 pass, 1 fail)
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "scripts" / "build_alerts.py"
VALIDATOR = ROOT / "scripts" / "tests" / "validate_alerts.py"
LIVE = ROOT / "data" / "live"

# The production case, named so the next reader can check it against the archive.
PRODUCTION_TICKER = "KXAAAGASD-26NOV21-3.6600"
PRODUCTION_SERIES = "KXAAAGASD"

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def function_source(path: Path, name: str) -> str:
    """Source text of a function in `path`, with its docstring removed.

    The docstring is stripped on purpose: these functions explain the resolution order in prose,
    and a plain substring search would otherwise match the explanation instead of the code it
    describes.
    """
    text = path.read_text()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                start = body[1].lineno if len(body) > 1 else node.end_lineno
                return "\n".join(text.splitlines()[start - 1:node.end_lineno])
            return ast.get_source_segment(text, node) or ""
    return ""


def test_builder_reads_the_archive_record() -> None:
    src = function_source(BUILDER, "official_for")
    check(bool(src), "build_alerts.py must define official_for()")
    check("series_categories" in src,
          "builder official_for() must consult the archive entry's recorded series_categories (F-109)")
    check("archive_recorded" in src or "recorded_cache" in src,
          "builder official_for() must fall back to the recorded per-ticker categories")
    # Order matters: the exchange's CURRENT record first, the detection-time record last.
    row_at = src.find("by_ticker")
    ledger_at = src.find("series_index")
    recorded_at = max(src.find("archive_recorded"), src.find("recorded_cache"))
    check(-1 < row_at < ledger_at < recorded_at,
          "builder resolution order must be snapshot row -> series_index -> archived record")


def test_validator_reads_the_archive_record() -> None:
    src = function_source(VALIDATOR, "_official")
    check(bool(src), "validate_alerts.py must define _official()")
    check("entry_categories" in src,
          "validator _official() must fall back to the archive entry's recorded categories (F-109)")
    row_at = src.find("row_by_ticker")
    ledger_at = src.find("ledger.get")
    recorded_at = src.find("entry_categories.get")
    check(-1 < row_at < ledger_at < recorded_at,
          "validator resolution order must be snapshot row -> series_index -> archived record")


def test_the_two_files_agree_on_the_order() -> None:
    b = function_source(BUILDER, "official_for")
    v = function_source(VALIDATOR, "_official")
    for label, src in (("builder", b), ("validator", v)):
        order = [i for i, token in sorted(
            ((src.find("by_ticker"), "row"), (src.find("series_index") if label == "builder" else src.find("ledger.get"), "ledger"),
             (max(src.find("archive_recorded"), src.find("recorded_cache")) if label == "builder"
              else src.find("entry_categories.get"), "recorded"))) ]
        check(len(order) == 3 and order[0] >= 0,
              f"{label} must name all three resolution sources")


def test_the_fallback_cannot_readmit_an_off_topic_swing() -> None:
    """The fallback supplies CATEGORIES; publishable() must still refuse a contradiction."""
    src = function_source(BUILDER, "publishable")
    check(bool(src), "build_alerts.py must define publishable()")
    check("CATEGORY_COMPATIBLE" in src,
          "publishable() must still test the topic against CATEGORY_COMPATIBLE")


def test_production_row_now_resolves() -> None:
    archive_path = LIVE / "alerts_archive.json"
    if not archive_path.exists():
        check(False, "alerts_archive.json missing")
        return
    archive = json.loads(archive_path.read_text()).get("alerts") or []
    rows = [a for a in archive if a.get("ticker") == PRODUCTION_TICKER]
    check(bool(rows), f"the archive should still carry {PRODUCTION_TICKER} (append-only)")
    recorded = next((a.get("series_categories") for a in rows if a.get("series_categories")), None)
    check(bool(recorded), f"{PRODUCTION_TICKER} must carry its recorded series_categories")
    if recorded:
        # Restated here rather than imported from the builder: a test that imports the rule it
        # checks cannot catch the rule being changed.
        compatible = {"gas": {"Economics", "Commodities", "Financials"}}
        check(any(c in compatible["gas"] for c in recorded),
              f"{PRODUCTION_TICKER} recorded {recorded}, which must satisfy the 'gas' topic")
        check(any(a.get("category_id") == "gas" for a in rows),
              f"{PRODUCTION_TICKER} entries must keep the 'gas' topic they were assigned")


def test_failed_series_refetch_cannot_reopen_the_outage() -> None:
    """F-107's fix re-fetches GET /series for archive-cited series; this pins its failure path.

    scripts/collect.py resolves archive-cited series through its own `record_series()`, which
    records `categories: None` when the fetch raises (pinned by that fix's
    `test_failed_official_lookup_stays_unknown_never_inferred`). One transient error on
    /series/<archive-only series> then puts the ledger back in the state that gated five
    collection passes, while the archive still holds the topic the exchange's record justified.
    This runs arena-72ae7bca's own harness — the real collector build, feed builder and validator
    — with `unavailable=True`, and requires the pass to succeed.
    """
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "scripts" / "tests"))
        import collect  # noqa: F401  (imported by the harness)
        import build_alerts  # noqa: F401
        import test_archive_series_retention as harness
    except ImportError as exc:  # the fix this protects was reverted out of the tree
        check(False, f"the F-107 retention harness is missing, so this case cannot be run: {exc}")
        return
    from contextlib import redirect_stdout
    from unittest.mock import patch
    import io

    case = harness.ArchivedSeriesRetention()
    with tempfile.TemporaryDirectory(prefix="kalshi-f109-") as temp:
        root = Path(temp)
        payload, _calls = case.build(root, unavailable=True)
        check(payload["series_index"]["KXAAAGASD"]["categories"] is None,
              "precondition: a failed re-fetch leaves the ledger's categories null")
        live = root / "data" / "live"
        with patch.object(build_alerts, "ROOT", root), patch.object(build_alerts, "LIVE", live), \
                patch.object(sys, "argv", ["build_alerts.py"]), redirect_stdout(io.StringIO()):
            built = build_alerts.main()
        check(built == 0, "the feed builder must still publish the archive's own record")
        validator = harness.validator_module()
        validator.LIVE = live
        validator.RULES = root / "data" / "alert_rules.json"
        with redirect_stdout(io.StringIO()):
            rc = validator.main()
        check(rc == 0, "validator refused after a failed GET /series re-fetch (F-109): "
                       + " | ".join(validator.errors[:3]))


def test_end_to_end_repair_and_validate() -> None:
    """The real scripts, on a scratch copy, with the production condition forced.

    This is F-109's actual failure mode: remove the series from the open scan AND from the
    ledger, leaving only the archive's own record, then require BOTH the feed builder and the
    validator to succeed. Before the fix the validator refused this tree; after it, both pass.
    """
    scratch = Path(tempfile.mkdtemp(prefix="kalshi-f107-"))
    try:
        shutil.copytree(ROOT / "scripts", scratch / "scripts")
        shutil.copytree(ROOT / "data", scratch / "data")
        live = scratch / "data" / "live"
        markets = json.loads((live / "markets.json").read_text())
        markets["open_markets"] = [
            r for r in (markets.get("open_markets") or [])
            if not str(r.get("ticker") or "").startswith(PRODUCTION_SERIES)
        ]
        (markets.get("series_index") or {}).pop(PRODUCTION_SERIES, None)
        (live / "markets.json").write_text(json.dumps(markets))

        built = subprocess.run([sys.executable, "scripts/build_alerts.py"], cwd=scratch,
                               capture_output=True, text=True)
        check(built.returncode == 0, f"feed builder failed on the aged-out tree: {built.stderr[-400:]}")
        validated = subprocess.run([sys.executable, "scripts/tests/validate_alerts.py"], cwd=scratch,
                                   capture_output=True, text=True)
        check(validated.returncode == 0,
              "validator refused the aged-out tree (F-109 regression): " + validated.stderr[-600:])
        check("categories [] accept []" not in validated.stderr,
              "the 'categories [] accept []' contradiction must not reappear")

        # And the feeds must still be reproducible from the archive after the repair.
        feed = json.loads((live / "alerts.json").read_text())
        check(feed.get("counts", {}).get("archive_total") == len(json.loads(
            (live / "alerts_archive.json").read_text()).get("alerts") or []),
              "counts.archive_total must match the archive after the repair")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    for test in (test_builder_reads_the_archive_record,
                 test_validator_reads_the_archive_record,
                 test_the_two_files_agree_on_the_order,
                 test_the_fallback_cannot_readmit_an_off_topic_swing,
                 test_production_row_now_resolves,
                 test_failed_series_refetch_cannot_reopen_the_outage,
                 test_end_to_end_repair_and_validate):
        before = len(failures)
        test()
        print(("  ok   " if len(failures) == before else "  FAIL ") + test.__name__)
    if failures:
        print("\nFAIL: scope-source parity (F-109)")
        for f in failures:
            print("  - " + f)
        return 1
    print("\nOK: the feed builder and the alert validator resolve official categories from the same "
          "three sources, in the same order, and survive a market leaving the open scan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
