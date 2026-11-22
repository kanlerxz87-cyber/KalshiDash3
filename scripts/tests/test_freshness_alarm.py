#!/usr/bin/env python3
"""Execute the alarm's actual shell steps with a fake gh, never the real service.

History
  This file used to run the single "Dispatch one collection" step and stub `gh run list`
  with two counters. F-86 changed the design: the decision now lives in
  `scripts/freshness_guard.py` (tested on its own in test_freshness_guard.py) and the
  workflow has three steps — decide, cancel a wedged run, dispatch one. So this file now
  exercises the *wiring*: the real shell text of each step, a fake `gh` that only answers
  the documented commands, and the real guard script. Nothing here talks to GitHub.

What is pinned
  1. The decide step asks for the exact JSON fields the guard reads and writes
     `GUARD_ACTION` into `$GITHUB_ENV`.
  2. A stale snapshot with nothing in flight produces `GUARD_ACTION=dispatch`, and the
     dispatch step then runs exactly `workflow run collect.yml --ref main`.
  3. A stale snapshot with a *young* in-flight run produces `wait`, and neither the
     dispatch nor the cancel step can fire (both are gated on `GUARD_ACTION`).
  4. A stale snapshot with a run older than 75 minutes produces `cancel` plus that run's
     id, and the cancel step runs `run cancel <id>` — and never a dispatch.
  5. A failing dispatch is not reported as success.
  6. Each action step is gated on `GUARD_ACTION`, and the whole chain is still gated on
     the staleness of the snapshot (`env.STALE == '1'`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/freshness-alarm.yml'
NOW = datetime.now(timezone.utc)


def step_section(marker: str) -> str:
    """The whole YAML section of the workflow step whose name starts with `marker`."""
    text = WORKFLOW.read_text()
    return text.split(f'      - name: {marker}', 1)[1].split('\n      - name:', 1)[0]


def step_block(marker: str) -> str:
    """The `run: |` shell of that step."""
    section = step_section(marker)
    block = section.split('        run: |\n', 1)[1]
    return textwrap.dedent(block)


def step_runs(marker: str, env: dict) -> bool:
    """Evaluate the step's `if:` the way GitHub does for the one form used here.

    Every action step in this workflow is gated on `env.NAME == 'value'`; anything else is
    treated as "no condition, always run" so a future unconditional step is not skipped
    silently by this harness.
    """
    match = re.search(r"^        if: (.+)$", step_section(marker), re.M)
    if not match:
        return True
    condition = match.group(1).strip()
    gate = re.fullmatch(r"env\.([A-Z_]+) == '([^']*)'", condition)
    if not gate:
        raise AssertionError(f"this harness cannot evaluate: {condition}")
    return env.get(gate.group(1)) == gate.group(2)


def minutes_ago(minutes: float) -> str:
    from datetime import timedelta
    return (NOW - timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')


def run_json(status: str, age_min: float, event: str = 'schedule', run_id: int = 1) -> dict:
    return {'databaseId': run_id, 'status': status, 'createdAt': minutes_ago(age_min), 'event': event}


FAKE_GH = '''#!/bin/bash
if [[ "$1 $2" == "run list" ]]; then
  cat "$RUNS_JSON"
elif [[ "$1 $2" == "run cancel" ]]; then
  printf 'run cancel %s\\n' "$3" >> "$CALLS"
  exit "${CANCEL_RC:-0}"
elif [[ "$1 $2" == "workflow run" ]]; then
  printf '%s\\n' "$*" >> "$CALLS"
  exit "$DISPATCH_RC"
else
  exit 2
fi
'''


class AlarmChain(unittest.TestCase):
    def run_chain(self, runs, age_min=90, stale='1', dispatch_rc='0', cancel_rc='0'):
        """Run the decide step, then whichever action step the guard selected."""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            gh = path / 'gh'
            gh.write_text(FAKE_GH)
            gh.chmod(0o755)
            # Mirror the runner layout inside the temp cwd: the decide step runs
            # `python3 scripts/freshness_guard.py` and writes ./runs.json.
            (path / 'scripts').mkdir()
            shutil.copy(ROOT / 'scripts/freshness_guard.py', path / 'scripts/freshness_guard.py')
            runs_file = path / 'runs_source.json'   # NOT runs.json: the step redirects into ./runs.json
            runs_file.write_text(json.dumps(runs))
            env_file = path / 'github_env'
            env_file.write_text('')
            calls = path / 'calls'
            env = dict(os.environ, PATH=f'{path}:{os.environ["PATH"]}', AGE_MIN=str(age_min),
                       RUNS_JSON=str(runs_file), CALLS=str(calls), DISPATCH_RC=dispatch_rc,
                       CANCEL_RC=cancel_rc, GITHUB_ENV=str(env_file), STALE=stale)

            # cwd=temp so the step's `> runs.json` lands in the sandbox, never in the repo.
            decided = subprocess.run(['bash', '-c', step_block('Decide what to do')],
                                     env=env, text=True, capture_output=True, cwd=temp)
            self.assertEqual(decided.returncode, 0, decided.stderr)
            env.update(dict(line.split('=', 1) for line in env_file.read_text().strip().splitlines()
                            if '=' in line))

            ran = []
            for marker in ('Cancel a wedged collection', 'Dispatch one collection'):
                if step_runs(marker, env):
                    ran.append(subprocess.run(['bash', '-c', step_block(marker)],
                                              env=env, text=True, capture_output=True, cwd=temp))
            return decided, ran, (calls.read_text().splitlines() if calls.exists() else [])

    # --- 1/2: dispatch path -------------------------------------------------------------
    def test_guard_requests_the_fields_it_reads(self):
        text = step_block('Decide what to do')
        self.assertIn('databaseId,status,createdAt,event', text)
        self.assertIn('--env-file "$GITHUB_ENV"', text)

    def test_stale_and_idle_dispatches_one_run_with_documented_arguments(self):
        decided, executed, calls = self.run_chain([run_json('completed', 200)])
        self.assertIn('action=dispatch', decided.stdout)
        self.assertEqual(calls, ['workflow run collect.yml --ref main'])
        self.assertIn('queued one collection', executed[0].stdout)

    # --- 3: young in-flight run ----------------------------------------------------
    def test_young_in_flight_run_blocks_both_actions(self):
        decided, executed, calls = self.run_chain([run_json('in_progress', 10)])
        self.assertIn('action=wait', decided.stdout)
        self.assertEqual(calls, [], 'a slow pass must not trigger a cancel or a dispatch')

    # --- 4: wedged run -------------------------------------------------------------
    def test_wedged_run_is_cancelled_and_nothing_is_dispatched(self):
        decided, executed, calls = self.run_chain([run_json('in_progress', 150, run_id=4242)],
                                                  age_min=160)
        self.assertIn('action=cancel', decided.stdout)
        self.assertEqual(calls, ['run cancel 4242'], 'cancel the wedged run, do not queue another')
        self.assertIn('cancelling it', executed[0].stdout)

    # --- 5: honest failure ---------------------------------------------------------
    def test_dispatch_failure_is_not_reported_as_success(self):
        decided, executed, calls = self.run_chain([run_json('completed', 200)], dispatch_rc='1')
        step = executed[0]
        self.assertNotEqual(step.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn('dispatch failed', step.stdout)
        self.assertNotIn('queued one collection', step.stdout)

    def test_cancel_failure_is_not_reported_as_success(self):
        decided, executed, calls = self.run_chain([run_json('in_progress', 150, run_id=7)],
                                                  age_min=160, cancel_rc='1')
        self.assertNotEqual(executed[0].returncode, 0)
        self.assertEqual(calls, ['run cancel 7'])

    # --- 6: gating ----------------------------------------------------------------
    def test_action_steps_are_gated_on_the_guard_verdict_and_staleness(self):
        workflow = WORKFLOW.read_text()
        decide = workflow.split('      - name: Decide what to do', 1)[1].split('\n      - name:', 1)[0]
        cancel = workflow.split('      - name: Cancel a wedged collection', 1)[1].split('\n      - name:', 1)[0]
        dispatch = workflow.split('      - name: Dispatch one collection', 1)[1].split('\n      - name:', 1)[0]
        self.assertIn("if: env.STALE == '1'", decide)
        self.assertIn("if: env.GUARD_ACTION == 'cancel'", cancel)
        self.assertIn("if: env.GUARD_ACTION == 'dispatch'", dispatch)

    def test_monitor_never_runs_a_bare_in_flight_skip(self):
        text = WORKFLOW.read_text()
        self.assertNotIn('already running; not dispatching', text,
                         'the old blanket skip is what made a wedged run invisible (F-86)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
