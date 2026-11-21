#!/usr/bin/env python3
"""Execute the alarm's actual dispatch shell with a fake gh, never the real service."""
from pathlib import Path
import os
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/freshness-alarm.yml'


def dispatch_script():
    text = WORKFLOW.read_text()
    section = text.split('      - name: Dispatch one collection', 1)[1]
    block = section.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0]
    return textwrap.dedent(block)


class AlarmDispatch(unittest.TestCase):
    def run_alarm(self, in_flight='0', recent='0', dispatch_rc='0'):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            gh = path / 'gh'
            gh.write_text('''#!/bin/bash
if [[ "$1 $2" == "run list" ]]; then
  if [[ "$*" == *"--json status"* ]]; then echo "$IN_FLIGHT"; else echo "$RECENT"; fi
elif [[ "$1 $2" == "workflow run" ]]; then
  printf '%s\\n' "$*" >> "$CALLS"
  exit "$DISPATCH_RC"
else exit 2
fi
''')
            gh.chmod(0o755)
            calls = path / 'calls'
            env = dict(os.environ, PATH=f'{path}:{os.environ["PATH"]}',
                       IN_FLIGHT=in_flight, RECENT=recent, DISPATCH_RC=dispatch_rc,
                       CALLS=str(calls), AGE_MIN='50')
            result = subprocess.run(['bash', '-c', dispatch_script()], env=env,
                                    text=True, capture_output=True)
            return result, calls.read_text().splitlines() if calls.exists() else []

    def test_dispatch_uses_documented_cli_arguments(self):
        result, calls = self.run_alarm()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['workflow run collect.yml --ref main'])
        self.assertIn('queued one collection', result.stdout)

    def test_running_or_queued_collection_prevents_dispatch(self):
        result, calls = self.run_alarm(in_flight='1')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_recent_dispatch_prevents_dispatch(self):
        result, calls = self.run_alarm(recent='1')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_dispatch_failure_is_not_reported_as_success(self):
        result, calls = self.run_alarm(dispatch_rc='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn('dispatch failed', result.stdout)
        self.assertNotIn('queued one collection', result.stdout)

    def test_only_stale_snapshots_enter_dispatch_step(self):
        workflow = WORKFLOW.read_text()
        section = workflow.split('      - name: Dispatch one collection', 1)[1].split('\n      - name:', 1)[0]
        self.assertIn("if: env.STALE == '1'", section)


if __name__ == '__main__':
    unittest.main()
