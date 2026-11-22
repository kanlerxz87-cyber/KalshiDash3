#!/usr/bin/env python3
"""Decision tests for the freshness monitor's rescue rule (F-86).

Why this exists
  The monitor used to skip whenever any collect.yml run was in flight, which is exactly
  the state a wedged run leaves behind. On 2026-11-22 a scheduled relay run held the
  concurrency group from 02:46Z while the newest collector commit stayed at 06:17Z; the
  snapshot went two hours stale and nothing fired until a human cancelled the run.
  `scripts/freshness_guard.py` encodes the rule that replaces that judgement call, and
  this file pins every branch of it.

Scenarios (all offline, epochs supplied explicitly):
  1. fresh snapshot                        -> ok
  2. stale + young in-flight run            -> wait (a slow pass is not a wedged one)
  3. stale + in-flight run older than 75 m  -> cancel THAT run (the oldest active one)
  4. stale + nothing in flight + no recent  -> dispatch exactly one
     workflow_dispatch
  5. stale + nothing in flight + a dispatch
     created 10 min ago                     -> wait (F-63 runaway-dispatch guard)
  6. queued-but-not-started run             -> counted as in flight, not cancelled until 75 m
  7. cancel never also dispatches           -> action is a single value
  8. CLI writes ACTION/RUN_ID/WHY           -> the workflow can act on it

Run: python3 scripts/tests/test_freshness_guard.py     (exit 0 pass, 1 fail)
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 22, 8, 30, tzinfo=timezone.utc).timestamp()


def load_guard():
    spec = importlib.util.spec_from_file_location("freshness_guard_under_test", ROOT / "scripts" / "freshness_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stamp(minutes_ago: float) -> str:
    """A createdAt string in the format gh emits, N minutes before NOW."""
    from datetime import timedelta
    return (datetime.fromtimestamp(NOW, timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(status="in_progress", minutes_ago=5.0, event="schedule", run_id=1):
    return {"databaseId": run_id, "status": status, "createdAt": stamp(minutes_ago), "event": event}


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load_guard()

    def test_fresh_snapshot_does_nothing(self):
        action, why = self.g.classify(12, [run()], NOW)
        self.assertEqual(action, "ok")
        self.assertIn("fresh enough", why)

    def test_young_in_flight_run_is_left_alone(self):
        action, why = self.g.classify(50, [run(minutes_ago=10)], NOW)
        self.assertEqual(action, "wait")
        self.assertIn("in flight", why)
        self.assertIn("does not cancel", why)

    def test_wedged_run_is_cancelled(self):
        action, why = self.g.classify(135, [run(minutes_ago=135)], NOW)
        self.assertEqual(action, "cancel")
        self.assertIn("cancel that run", why)

    def test_oldest_active_run_is_the_target(self):
        runs = [run(minutes_ago=8, run_id=11), run(minutes_ago=140, run_id=22), run(minutes_ago=95, run_id=33)]
        age, _ = self.g.classify(140, runs, NOW), None
        with tempfile.TemporaryDirectory() as tmp:
            runs_file = Path(tmp) / "runs.json"
            runs_file.write_text(json.dumps(runs))
            env_file = Path(tmp) / "env"
            env_file.write_text("")
            self.g.main(["--age-min", "140", "--runs-json", str(runs_file), "--now", str(NOW), "--env-file", str(env_file)])
            env = dict(line.split("=", 1) for line in env_file.read_text().strip().splitlines())
        self.assertEqual(env["GUARD_ACTION"], "cancel")
        self.assertEqual(env["GUARD_RUN_ID"], "22", "the oldest active run holds the group")

    def test_dispatch_when_nothing_is_in_flight(self):
        action, why = self.g.classify(60, [run(status="completed", minutes_ago=90)], NOW)
        self.assertEqual(action, "dispatch")
        self.assertIn("nothing in flight", why)

    def test_recent_dispatch_blocks_a_second_one(self):
        action, why = self.g.classify(60, [run(status="completed", minutes_ago=10, event="workflow_dispatch")], NOW)
        self.assertEqual(action, "wait")
        self.assertIn("F-63", why)

    def test_old_dispatch_does_not_block(self):
        action, _ = self.g.classify(60, [run(status="completed", minutes_ago=61, event="workflow_dispatch")], NOW)
        self.assertEqual(action, "dispatch")

    def test_queued_run_counts_as_in_flight_but_is_not_cancelled_early(self):
        action, why = self.g.classify(50, [run(status="queued", minutes_ago=20)], NOW)
        self.assertEqual(action, "wait")
        self.assertIn("in flight", why)

    def test_cancel_is_never_also_a_dispatch(self):
        action, _ = self.g.classify(200, [run(minutes_ago=200, event="workflow_dispatch")], NOW)
        self.assertEqual(action, "cancel", "a cancelled run's pending successor is the fresh pass; do not queue another")

    def test_unknown_age_is_not_guessed(self):
        action, why = self.g.classify(None, [run(minutes_ago=200)], NOW)
        self.assertEqual(action, "ok")
        self.assertIn("unknown", why)

    def test_thresholds_match_the_documented_values(self):
        self.assertEqual(self.g.STALE_MIN, 45)
        self.assertEqual(self.g.STALL_MIN, 75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
