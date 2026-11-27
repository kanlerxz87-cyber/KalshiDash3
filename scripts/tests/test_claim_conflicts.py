#!/usr/bin/env python3
"""Tests for scripts/check_claim_conflicts.py — the board -> claim-ledger parser (R93-1).

Why these tests exist
  The script exists because four concurrent sessions claimed the same collector repair on
  2026-11-27 and the collision surfaced as a merge conflict instead of as a warning. A parser
  that silently under-reports would put us straight back there, so each rule it relies on is
  pinned here with a synthetic board; the last block then runs it against the real
  COORDINATION.md and the real repository paths.

Rules pinned
  1. A live claim by two sessions on one path is a conflict; the same path is fine once one
     session records its task as done.
  2. A scope cell that says a path is NOT covered ("— not `flagged.html`", "avoids
     `data/findings.json`") does not claim that path. Prose disclaimers are the difference
     between a true collision and a false alarm.
  3. Only the topmost `## Session` section per session is its current statement; later sections
     are history and are not re-counted (this board grows by inserting at the top).
  4. Directory scopes (`data/live/*`) are captured; prose backticks that are not paths are not.
  5. A table row that is not a task claim (field documentation) is ignored.
  6. `--strict` exits 1 on a real overlap and 0 when the board is clean; the default mode always
     exits 0 and writes the ledger, because a conflicting board must not block a site deploy.

Run: python3 scripts/tests/test_claim_conflicts.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "check_claim_conflicts.py"
sys.path.insert(0, str(ROOT / "scripts"))

import check_claim_conflicts as chk  # noqa: E402


def board(*sections: str) -> str:
    head = "# COORDINATION.md — Shared Task Board\n\n> rule line\n\n"
    return head + "\n".join(sections)


def section(session: str, *rows: str) -> str:
    body = "\n".join(rows)
    return (f"## Session `{session}` — synthetic\n\n"
            "| ID | Task | Status | Owner | Files in scope | Verification |\n"
            "|---|---|---|---|---|---|\n"
            f"{body}\n")


ROW1 = "| X1-1 | do a thing | in progress | arena-aaaa | `scripts/a.py`, `assets/a.js` | x |"
ROW1_DONE = "| X1-1 | do a thing | done | arena-aaaa | `scripts/a.py`, `assets/a.js` | x |"
ROW2 = "| B2-1 | do the same thing | in progress | arena-bbbb | `scripts/a.py` | y |"


class ParseRules(unittest.TestCase):
    def test_conflict_between_two_live_claims(self):
        doc = chk.build(board(section("arena-aaaa", ROW1), section("arena-bbbb", ROW2)))
        paths = {c["path"]: c for c in doc["conflicts"]}
        self.assertIn("scripts/a.py", paths)
        self.assertEqual(paths["scripts/a.py"]["sessions"], ["aaaa", "bbbb"])
        self.assertNotIn("assets/a.js", paths)          # claimed by one session only
        self.assertEqual(doc["counts"]["conflicting_paths"], 1)

    def test_done_claim_is_not_live(self):
        doc = chk.build(board(section("arena-aaaa", ROW1_DONE), section("arena-bbbb", ROW2)))
        self.assertEqual(doc["conflicts"], [])
        self.assertEqual(doc["counts"]["live_claims"], 1)   # only bbbb's row

    def test_no_status_is_treated_as_live(self):
        row = "| X1-2 | unstated |   | arena-aaaa | `scripts/a.py` | x |"
        doc = chk.build(board(section("arena-aaaa", row)))
        self.assertEqual(doc["counts"]["live_claims"], 1)

    def test_negated_paths_are_not_claims(self):
        row = ("| X1-3 | publish | in progress | arena-aaaa | `COORDINATION.md` (this section) only "
               "— **not** `flagged.html`, **not** `data/findings.json` | x |")
        doc = chk.build(board(section("arena-aaaa", row)))
        files = doc["sessions"][0]["claims"][0]["files"]
        self.assertEqual(files, ["COORDINATION.md"])

    def test_avoids_and_no_writes_are_not_claims(self):
        for phrase in ("avoids `data/findings.json`", "no direct writes to `data/live/*`"):
            row = f"| X1-4 | work | in progress | arena-aaaa | `scripts/a.py`, {phrase} | x |"
            files = chk.build(board(section("arena-aaaa", row)))["sessions"][0]["claims"][0]["files"]
            self.assertEqual(files, ["scripts/a.py"], phrase)

    def test_only_topmost_section_per_session_counts(self):
        # The board grows by inserting at the top, so a session's first section is current.
        old = section("arena-aaaa", "| X1-9 | ancient | in progress | arena-aaaa | `scripts/a.py` | x |")
        new = section("arena-aaaa", "| X1-8 | current | done | arena-aaaa | `scripts/b.py` | x |")
        doc = chk.build(board(new, old))
        tasks = list(doc["sessions"][0]["claims"])
        self.assertEqual(len(doc["sessions"]), 1)
        self.assertEqual([t["task"] for t in tasks], ["X1-8"])

    def test_directory_scope_is_a_claim(self):
        row = "| X1-5 | sweep | in progress | arena-aaaa | `data/live/*`, `scripts/tests/` | x |"
        files = chk.build(board(section("arena-aaaa", row)))["sessions"][0]["claims"][0]["files"]
        self.assertIn("data/live/*", files)
        self.assertIn("scripts/tests/", files)

    def test_non_task_rows_are_ignored(self):
        row = "| `volume_fp` | contracts traded | yes | no | n/a | schema |"   # field doc row
        doc = chk.build(board(section("arena-aaaa", row, ROW1)))
        self.assertEqual([c["task"] for c in doc["sessions"][0]["claims"]], ["X1-1"])

    def test_arena_prefix_is_normalised(self):
        doc = chk.build(board(section("arena-aaaa", ROW1), section("arena-bbbb", ROW2)))
        self.assertEqual({s["session"] for s in doc["sessions"]}, {"aaaa", "bbbb"})

    def test_build_many_unions_branch_copies(self):
        a = board(section("arena-aaaa", ROW1))
        b = board(section("arena-bbbb", ROW2))      # bbbb's claim exists only on its own branch
        doc = chk.build_many([a, b])
        self.assertEqual([c["path"] for c in doc["conflicts"]], ["scripts/a.py"])

    def test_build_many_collapses_the_same_session(self):
        a = board(section("arena-aaaa", ROW1))
        b = board(section("arena-aaaa", ROW1), section("arena-bbbb", ROW2))
        doc = chk.build_many([a, b])
        self.assertEqual(doc["counts"]["sessions"], 2)
        self.assertEqual(len(doc["conflicts"]), 1)


class CommandLine(unittest.TestCase):
    def run_cli(self, text: str, *args: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "COORDINATION.md"
            path.write_text(text)
            return subprocess.run([sys.executable, str(SCRIPT), "--board", str(path),
                                   "--out", str(Path(tmp) / "claims.json"), *args],
                                  capture_output=True, text=True, cwd=ROOT)

    def test_strict_fails_on_overlap(self):
        r = self.run_cli(board(section("arena-aaaa", ROW1), section("arena-bbbb", ROW2)), "--strict")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("STRICT", r.stderr)

    def test_default_passes_on_overlap(self):
        r = self.run_cli(board(section("arena-aaaa", ROW1), section("arena-bbbb", ROW2)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("reported, not fatal", r.stdout)

    def test_clean_board_strict_passes(self):
        r = self.run_cli(board(section("arena-aaaa", ROW1)), "--strict")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK: no path is claimed live", r.stdout)

    def test_writes_ledger_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "COORDINATION.md"
            path.write_text(board(section("arena-aaaa", ROW1)))
            out = Path(tmp) / "claims.json"
            subprocess.run([sys.executable, str(SCRIPT), "--board", str(path), "--out", str(out)],
                           check=True, capture_output=True, cwd=ROOT)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["schema"], 1)
            self.assertEqual(doc["source"], str(path))
            self.assertIn("does NOT decide staleness", doc["note"])
            self.assertEqual(doc["counts"]["claims"], 1)


class RealBoard(unittest.TestCase):
    """The real board and the real tree, so a parser regression cannot hide behind fixtures."""

    def setUp(self):
        self.text = (ROOT / "COORDINATION.md").read_text(encoding="utf-8")
        self.doc = chk.build(self.text)

    def test_parses_many_sessions_and_claims(self):
        self.assertGreater(self.doc["counts"]["sessions"], 20)
        self.assertGreater(self.doc["counts"]["claims"], 20)

    def test_every_claim_has_owner_and_files(self):
        for s in self.doc["sessions"]:
            for c in s["claims"]:
                self.assertTrue(c["owner"], f"{c['task']} has no owner cell")
                self.assertIsInstance(c["files"], list)

    def test_ledger_staleness_is_disclaimed(self):
        # The board has no commit times, so the report must not pretend to date claims.
        self.assertIn("does NOT decide staleness", self.doc["note"])

    def test_negation_rule_holds_on_the_real_board(self):
        """9312ad1f's R93-2 says 'not `flagged.html`' — it must not be read as a claim."""
        for s in self.doc["sessions"]:
            if s["session"] != "9312ad1f":
                continue
            for c in s["claims"]:
                self.assertNotIn("flagged.html", c["files"], c["task"])
                self.assertNotIn("data/findings.json", c["files"], c["task"])

    def test_directory_scopes_point_at_real_directories(self):
        for s in self.doc["sessions"]:
            for c in s["claims"]:
                for f in c["files"]:
                    if f.endswith("/") or f.endswith("/*"):
                        base = ROOT / f.split("*")[0].rstrip("/")
                        self.assertTrue(base.is_dir(), f"{c['task']}: {f} is not a directory")


if __name__ == "__main__":
    unittest.main(verbosity=2)
