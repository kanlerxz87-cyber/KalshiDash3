#!/usr/bin/env python3
"""The series ledger must keep verified records for events that have left the scan (A8D3).

`data/live/markets.json` carries `series_index`: the official `GET /series` categories per series
ticker. It is built from the rows in the CURRENT open/settled window (`record_series`), so when an
event resolves and its markets age out, its series leaves the ledger - while the archived
>= $0.10 swings still cite that series and `scripts/tests/validate_alerts.py` re-checks each
archived alert's topic against that ledger.

Measured consequence on 2026-11-27 (see COORDINATION.md, session `arena-a8d317a1`): every
`collect.yml` relay pass from 18:29Z to 19:38Z failed with

    archive:KXAAAGASD-26NOV21-3.6600@2026-11-20T22:41:00Z assigned topic 'gas'
    but GET /series categories [] accept []

and the published snapshot stayed frozen at `collected_at 2026-11-27T18:00:57Z`. `KXAAAGASD` is
officially `categories: ["Economics"]` (GET /trade-api/v2/series/KXAAAGASD), i.e. inside Gas Prices;
only its ledger entry had disappeared.

What is asserted here
  1. `carry_forward_series` fills a series the current ledger no longer covers from the previous
     snapshot's verified record, and counts it.
  2. A fresh answer always wins: a series the current scan did cover is never overwritten.
  3. An entry with no categories answers nothing - it is not carried and does not "confirm" a topic.
  4. Series the archive does not cite are not carried (the ledger stays a record of events, not a
     cache of the whole exchange).
  5. `build()` wires the helper in and publishes the count, so the carry is disclosed, not silent.

Run: python3 scripts/tests/test_series_ledger_carry.py
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_collect():
    spec = importlib.util.spec_from_file_location("collect_under_test_ledger", ROOT / "scripts" / "collect.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class CarryForwardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collect = load_collect()

    def test_a_series_the_scan_no_longer_covers_keeps_its_verified_record(self):
        ledger = {"KXOTHER": {"categories": ["Crypto"], "title": "other", "tags": None,
                              "source": "https://external-api.demo.kalshi.co/trade-api/v2/series/KXOTHER"}}
        previous = {"KXAAAGASD": {"categories": ["Economics"], "title": "US gas price up",
                                  "tags": ["Oil & Gas"],
                                  "source": "https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASD"}}
        carried = self.collect.carry_forward_series(ledger, previous, {"KXAAAGASD"})
        self.assertEqual(carried, 1)
        self.assertEqual(ledger["KXAAAGASD"]["categories"], ["Economics"],
                         "the verified categories must survive the series leaving the scan")
        self.assertEqual(ledger["KXAAAGASD"]["source"],
                         "https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASD",
                         "the carried record keeps the official source it was read from")

    def test_a_fresh_answer_always_wins(self):
        ledger = {"KXAAAGASD": {"categories": ["Commodities"], "title": "fresh", "tags": None,
                                "source": "https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASD"}}
        previous = {"KXAAAGASD": {"categories": ["Economics"], "title": "stale",
                                  "source": "https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASD"}}
        carried = self.collect.carry_forward_series(ledger, previous, {"KXAAAGASD"})
        self.assertEqual(carried, 0)
        self.assertEqual(ledger["KXAAAGASD"]["categories"], ["Commodities"],
                         "a series the current scan covered must never be overwritten by an older record")
        self.assertEqual(ledger["KXAAAGASD"]["title"], "fresh")

    def test_an_unanswered_previous_record_is_not_carried(self):
        ledger = {}
        previous = {"KXAAAGASD": {"categories": None, "title": "no answer", "tags": None,
                                  "source": "https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASD"}}
        self.assertEqual(self.collect.carry_forward_series(ledger, previous, {"KXAAAGASD"}), 0)
        self.assertNotIn("KXAAAGASD", ledger, "unknown must stay unknown - nothing is inferred")

    def test_only_series_the_archive_cites_are_carried(self):
        ledger = {}
        previous = {
            "KXAAAGASD": {"categories": ["Economics"], "title": "cited", "tags": None, "source": "s1"},
            "KXUNRELATED": {"categories": ["Crypto"], "title": "not cited", "tags": None, "source": "s2"},
        }
        carried = self.collect.carry_forward_series(ledger, previous, {"kxaaagasd-26nov21-3.6600"[:9]})
        self.assertEqual(carried, 1)
        self.assertIn("KXAAAGASD", ledger)
        self.assertNotIn("KXUNRELATED", ledger,
                         "the ledger stays a record of events the archive cites, not a cache of everything")

    def test_series_names_are_compared_upper_case(self):
        ledger = {}
        previous = {"KXAAAGASD": {"categories": ["Economics"], "title": "t", "tags": None, "source": "s"}}
        self.assertEqual(self.collect.carry_forward_series(ledger, previous, {"kxaaagasd"}), 1)

    def test_build_wires_the_helper_and_publishes_the_count(self):
        source = (ROOT / "scripts" / "collect.py").read_text()
        self.assertIn("carried_forward = carry_forward_series(ledger, previous_ledger, cited_series)", source,
                      "build() must actually carry the records forward")
        self.assertIn('"series_ledger_carried_forward": carried_forward', source,
                      "the carry must be published in counts, not applied silently")
        self.assertIn("alerts_archive.json", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
