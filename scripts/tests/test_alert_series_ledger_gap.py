#!/usr/bin/env python3
"""Regression: a series that has aged out of `series_index` must not stop the collector (A8D3).

What happened, measured rather than assumed
  2026-11-27T18:29Z (PR #149 merge) to 19:38Z, EVERY `collect.yml` relay pass on `main` failed
  with `detail: validators: validate_alerts` and committed nothing, so the published snapshot
  stayed frozen at `collected_at 2026-11-27T18:00:57Z`. The cause was recorded only after
  `scripts/collect_relay.py` started writing a failing validator's own output into
  `data/live/collector_health.json`; the reproduction run on a session branch
  (run 46057975142) recorded:

      INVALID alert data:
        - archive:KXAAAGASD-26NOV21-3.6600@2026-11-20T22:41:00Z assigned topic 'gas'
          but GET /series categories [] accept []

  `KXAAAGASD` ("US gas price up") is officially `categories: ["Economics"]`, i.e. inside Gas
  Prices. The archived alert was written when that series had a row in the scan window and
  `GET /series/KXAAAGASD` confirmed the topic (`category_assigned_from`). Once its markets settled
  and left the window, `scripts/collect.py` no longer recorded the series in `series_index`
  (the ledger is built from rows in the CURRENT scan), so the validator read `[]` - unknown - and
  failed the pass. Because every pass regenerates the same (correct) archive, the failure repeated
  forever: the collector could never commit again.

What this suite pins
  1. An archived alert whose series is ABSENT from `series_index` passes: unknown is not a
     contradiction, the same rule `scripts/build_alerts.py` applies to a row with no categories.
     The validator states how many rows this applies to instead of hiding them.
  2. An archived alert whose series IS in the ledger under a category the topic cannot contain
     still fails - the check keeps its teeth for a PROVABLE contradiction.

The fixtures are the COMMITTED snapshot copied to a temp directory and then mutated, so the test
reproduces the production condition exactly without touching `data/live/`.

Run: python3 scripts/tests/test_alert_series_ledger_gap.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "data" / "live"
VALIDATOR = ROOT / "scripts" / "tests" / "validate_alerts.py"


def load_validator(live_dir: Path):
    """Load validate_alerts.py fresh (its `errors` list is module state) against `live_dir`."""
    spec = importlib.util.spec_from_file_location("validate_alerts_under_test", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    mod.LIVE = live_dir
    mod.RULES = ROOT / "data" / "alert_rules.json"
    return mod


def cited_series_with_topic_assigned(archive: dict) -> str:
    """A series that an archived alert says GET /series confirmed at detection time."""
    for a in archive.get("alerts", []):
        if a.get("category_assigned_from"):
            return str(a["ticker"]).upper().split("-")[0]
    raise AssertionError("the committed archive carries no category_assigned_from row to test with")


class SeriesLedgerGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ("markets.json", "alerts_archive.json", "price_history.json", "alerts.json"):
            if not (LIVE / name).exists():
                raise unittest.SkipTest(f"no committed {name} to build the fixture from")
        cls.archive = json.loads((LIVE / "alerts_archive.json").read_text())
        cls.series = cited_series_with_topic_assigned(cls.archive)
        cls.topic = next((a.get("category_id") for a in cls.archive["alerts"]
                          if a.get("category_assigned_from") and str(a["ticker"]).upper().startswith(cls.series)),
                         None)
        if not cls.topic:
            raise unittest.SkipTest("no assigned topic to test with")

    def _fixture(self, tmp: Path, ledger_entry) -> Path:
        """Copy the committed live directory; replace (or drop) one series_index entry."""
        live = tmp / "live"
        live.mkdir()
        for name in ("markets.json", "alerts_archive.json", "price_history.json", "alerts.json"):
            shutil.copyfile(LIVE / name, live / name)
        snap = json.loads((live / "markets.json").read_text())
        self.assertIn(self.series, snap.get("series_index") or {},
                      "the fixture series must start out in the ledger")
        if ledger_entry is None:
            snap["series_index"].pop(self.series)
        else:
            snap["series_index"][self.series] = ledger_entry
        (live / "markets.json").write_text(json.dumps(snap), encoding="utf-8")
        return live

    def _run(self, live: Path):
        mod = load_validator(live)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mod.main()
        return code, out.getvalue(), list(getattr(mod, "errors", []))

    def test_series_missing_from_ledger_is_unknown_not_a_contradiction(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = self._fixture(Path(tmp), None)
            code, stdout, errors = self._run(live)
        self.assertEqual(errors, [], f"unknown series must not fail the pass: {errors[:3]}")
        self.assertEqual(code, 0, "a series that aged out of the ledger must not block the commit")
        self.assertIn("no longer carries in series_index", stdout,
                      "the validator must disclose the rows it could not re-check")
        self.assertIn("unknown is not a contradiction", stdout)

    def test_a_known_contradiction_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            # `Sports` is not a category the gas topic can contain: a PROVABLE contradiction.
            live = self._fixture(Path(tmp), {
                "categories": ["Sports"],
                "title": "planted for the regression",
                "tags": None,
                "source": f"https://external-api.demo.kalshi.co/trade-api/v2/series/{self.series}",
            })
            code, _stdout, errors = self._run(live)
        self.assertEqual(code, 1, "a provable contradiction must still refuse the pass")
        joined = "\n".join(errors)
        self.assertIn("assigned topic", joined,
                      f"the contradiction must be named, got: {joined[:400]}")

    def test_the_committed_tree_still_passes(self):
        """The unmutated committed snapshot must pass: this fix must not weaken the current pass."""
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live"
            live.mkdir()
            for name in ("markets.json", "alerts_archive.json", "price_history.json", "alerts.json"):
                shutil.copyfile(LIVE / name, live / name)
            code, _stdout, errors = self._run(live)
        self.assertEqual((code, errors), (0, []), f"committed data must validate: {errors[:3]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
