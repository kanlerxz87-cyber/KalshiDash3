#!/usr/bin/env python3
"""The relay's failure record: why a pass did not commit, kept in the repo (F-85).

Why this exists
  Until now the reason a collection pass failed existed only in the job's stdout. Actions job
  logs are served from `productionresultssa6.blob.core.windows.net`, which is not reachable
  from every environment that has to diagnose a stall, and a wedged run's output dies with the
  run. On 2026-11-22 a collector run held its concurrency group from 02:46Z with no commit
  after 06:17Z and the cause could not be read at all.

  `scripts/collect_relay.record_health()` now writes `data/live/collector_health.json` on every
  non-committing pass and commits that file alone. This suite pins the behaviour offline:
  git is stubbed, nothing is written to the working tree, no network is used.

What is asserted
  1. A failed pass writes the documented fields (schema, pass, outcome, detail, stderr tail,
     run identity) and keeps at most 2000 characters of the failing step's output.
  2. It commits ONLY `data/live/collector_health.json` — never a snapshot file.
  3. A non-zero git command, or a push that keeps being rejected, returns a status instead of
     raising: a diagnostic must never become a second failure.
  4. `make_pass`'s failure paths call it — a broken validator, a failed pipeline step and an
     unreachable API each leave a record.

Run: python3 scripts/tests/test_collect_health.py     (exit 0 pass, 1 fail)
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_relay():
    spec = importlib.util.spec_from_file_location("collect_relay_under_test", ROOT / "scripts" / "collect_relay.py")
    mod = importlib.util.module_from_spec(spec)
    # Register before exec: the module defines dataclasses, and dataclasses resolves the
    # defining module through sys.modules while processing them.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeSh:
    """Stand-in for collect_relay.sh that records argv and answers with chosen exit codes."""

    def __init__(self, push_codes=None, add_rc=0, diff_rc=1, commit_rc=0):
        self.calls = []
        self.push_codes = list(push_codes or [0])
        self.add_rc = add_rc
        self.diff_rc = diff_rc
        self.commit_rc = commit_rc

    def __call__(self, args, timeout=600, check=False):
        self.calls.append(list(args))
        joined = " ".join(args)
        code = 0
        if args[:2] == ["git", "add"]:
            code = self.add_rc
        elif args[:3] == ["git", "diff", "--cached"]:
            code = self.diff_rc
        elif args[:2] == ["git", "commit"]:
            code = self.commit_rc
        elif args[:2] == ["git", "push"]:
            code = self.push_codes.pop(0) if len(self.push_codes) > 1 else self.push_codes[0]
        return subprocess.CompletedProcess(args=joined, returncode=code, stdout="", stderr="")


class HealthRecordOkTests(unittest.TestCase):
    """F-98: the health file must describe the MOST RECENT pass, not the last failure."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_relay()

    def test_a_successful_pass_writes_an_ok_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(self.mod, "HEALTH_ROOT", root):
                result = self.mod.write_health_ok(7, "main")
            written = root / self.mod.HEALTH_PATH
            self.assertTrue(written.exists(), "a committing pass must record that it committed")
            doc = json.loads(written.read_text())
        self.assertEqual(result, "written")
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(doc["pass"], 7)
        self.assertEqual(doc["outcome"], "ok")
        self.assertEqual(doc["detail"], "snapshot committed")
        self.assertIn("generated_at", doc)
        self.assertIn("run", doc)
        self.assertEqual(doc["stderr_tail"], "")

    def test_the_ok_record_names_the_snapshot_it_describes(self):
        snapshot = json.loads((ROOT / "data" / "live" / "markets.json").read_text())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(self.mod, "HEALTH_ROOT", root):
                self.mod.write_health_ok(1, "main")
            doc = json.loads((root / self.mod.HEALTH_PATH).read_text())
        self.assertEqual(doc.get("snapshot_collected_at"), snapshot.get("collected_at"),
                         "the health record must name the snapshot it was written with")

    def test_the_ok_record_never_touches_the_repository_working_tree(self):
        """The suite must not leave a health file behind in the repo it runs in."""
        before = (ROOT / self.mod.HEALTH_PATH).read_text() if (ROOT / self.mod.HEALTH_PATH).exists() else None
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(self.mod, "HEALTH_ROOT", Path(temp)):
                self.mod.write_health_ok(2, "main")
        after = (ROOT / self.mod.HEALTH_PATH).read_text() if (ROOT / self.mod.HEALTH_PATH).exists() else None
        self.assertEqual(before, after, "the repository's health file must not be rewritten by a test")

    def test_the_committing_path_writes_the_ok_record_before_the_commit(self):
        source = (ROOT / "scripts" / "collect_relay.py").read_text()
        body = source.split("def do_pass(n: int)", 1)[1]
        self.assertIn("write_health_ok(n, plan.ref)", body,
                      "the committing path must record that it committed")
        self.assertLess(body.index("write_health_ok(n, plan.ref)"), body.index("commit_and_push(plan.ref)"),
                        "the record must be written before the commit that stages data/live")

    def test_a_failing_pass_still_writes_failed(self):
        source = (ROOT / "scripts" / "collect_relay.py").read_text()
        self.assertIn('"outcome": "failed"', source)
        self.assertIn('"outcome": "ok"', source)


class HealthRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_relay()

    def write_in_temp(self, fake):
        """Run record_health with ROOT pointed at a temp dir so the repo is never touched."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(self.mod, "ROOT", root), mock.patch.object(self.mod, "sh", fake), \
                 mock.patch.object(self.mod.time, "sleep"):
                result = self.mod.record_health(3, "collect timeout", "COLLECT_FAILED: HTTP 429\n" * 200, "main")
            written = root / self.mod.HEALTH_PATH
            doc = json.loads(written.read_text()) if written.exists() else None
        return result, doc, fake.calls

    def test_record_has_the_documented_fields_and_a_bounded_tail(self):
        result, doc, _ = self.write_in_temp(FakeSh())
        self.assertEqual(result, "committed")
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(doc["pass"], 3)
        self.assertEqual(doc["outcome"], "failed")
        self.assertEqual(doc["detail"], "collect timeout")
        # A8D3-1: the bound is a named constant; it must be large enough for a validator's
        # own report (header + up to 40 errors), not just one crash traceback.
        self.assertLessEqual(len(doc["stderr_tail"]), self.mod.HEALTH_TAIL_LIMIT)
        self.assertGreaterEqual(self.mod.HEALTH_TAIL_LIMIT, 4000)
        self.assertIn("COLLECT_FAILED", doc["stderr_tail"])
        self.assertIn("run", doc)
        self.assertIn("generated_at", doc)

    def test_commits_only_the_health_file(self):
        result, _, calls = self.write_in_temp(FakeSh())
        added = [c for c in calls if c[:2] == ["git", "add"]]
        self.assertEqual(added, [["git", "add", "data/live/collector_health.json"]])
        for call in calls:
            joined = " ".join(call)
            self.assertNotIn("markets.json", joined)
            self.assertNotIn("price_history.json", joined)

    def test_no_change_is_not_committed(self):
        fake = FakeSh(diff_rc=0)
        result, _, calls = self.write_in_temp(fake)
        self.assertEqual(result, "skipped")
        self.assertFalse([c for c in calls if c[:2] == ["git", "commit"]])

    def test_rejected_push_returns_a_status_instead_of_raising(self):
        result, doc, calls = self.write_in_temp(FakeSh(push_codes=[1]))
        self.assertIn(result, {"dropped", "failed"})
        self.assertTrue(doc, "the file is still written even when the push fails")
        self.assertTrue([c for c in calls if c[:2] == ["git", "fetch"]])

    def test_failure_paths_write_a_record(self):
        """make_pass must route its failure returns through record_health."""
        source = (ROOT / "scripts" / "collect_relay.py").read_text()
        body = source.split("def do_pass(n: int)", 1)[1]
        self.assertIn("def fail(detail", body)
        for marker in ('return fail("git sync"', 'return fail(f"API probe',
                       'return fail(f"{name} timeout"', 'return fail("validators: "'):
            self.assertIn(marker, body, marker)
        # the raw tuple returns that used to lose the reason must be gone from the failure paths
        self.assertNotIn('return "failed", "git sync"', body)
        self.assertNotIn('return "failed", name', body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
