#!/usr/bin/env python3
"""Retry policy of the collector's single HTTP entry point (F-85).

Why this exists
  `scripts/collect.py` aborts the whole pass (exit 2, nothing committed) when `get()`
  raises. Before this change `get()` retried only HTTP 429: every other status broke out
  of the loop on the first attempt, so ONE transient 5xx from the demo API skipped a
  pass. Measured on 2026-11-22, a `collect.yml` relay run held its concurrency group
  from 02:46Z while the newest collector commit stayed at 06:17Z — the published
  snapshot aged ~2 h. The cause was not readable (Actions job logs live on a host this
  sandbox cannot reach), so this file pins the behaviour that is checkable instead:
  retryable failures are retried, non-retryable ones fail immediately, and the total
  attempt count stays bounded.

What is asserted
  1. 503, 503 then 200 -> returns the parsed body, three calls, two sleeps.
  2. Retryable failures until the budget runs out -> RuntimeError, exactly `retries`
     calls, `retries - 1` sleeps (no pointless sleep after the last attempt).
  3. 404 -> RuntimeError immediately, exactly ONE call (documented client error;
     https://docs.kalshi.com/api-reference/market/get-markets returns 404 for an
     unknown ticker, and retrying cannot fix it).
  4. Network-level failure (URLError) then 200 -> returns, proving a dropped
     connection no longer costs the pass.
  5. 429 is still retried, per the documented "no penalty" behaviour
     (https://docs.kalshi.com/getting_started/rate_limits), and on a longer schedule than a
     5xx: 3 s, 6 s, 12 s (doubling) instead of 1.5 s, 3 s, 4.5 s (linear), because a
     rate-limited collector that retries in milliseconds just trips the limit again.
  6. A scan pauses briefly between pages (PAGE_PAUSE_SECONDS) instead of hammering the
     unauthenticated limit with ~60 back-to-back page reads.

Offline: `urllib.request.urlopen` and `time.sleep` are patched inside the collector
module. No network, no credentials, no files written.

Run: python3 scripts/tests/test_collect_retry.py     (exit 0 pass, 1 fail)
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_collector():
    spec = importlib.util.spec_from_file_location("collect_retry_under_test", ROOT / "scripts" / "collect.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResponse(io.BytesIO):
    """Minimal stand-in for the object urlopen returns: a context manager with .read()."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def http_error(code, reason="test"):
    return urllib.error.HTTPError("https://example.invalid/x", code, reason, None, None)


class RetryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_collector()

    def run_get(self, side_effect, retries=None):
        kwargs = {"side_effect": side_effect}
        with mock.patch.object(self.mod.urllib.request, "urlopen", **kwargs) as urlopen, \
             mock.patch.object(self.mod.time, "sleep") as sleep:
            calls = {"urlopen": urlopen, "sleep": sleep}
            try:
                body, url = self.mod.get("/markets", {"limit": 2}, **({"retries": retries} if retries else {}))
                outcome = ("ok", body, url)
            except RuntimeError as e:
                outcome = ("error", str(e))
        return outcome, calls

    def test_transient_5xx_is_retried_then_returns(self):
        outcome, calls = self.run_get([http_error(503, "Service Unavailable"), http_error(502), ok({"markets": []})])
        self.assertEqual(outcome[0], "ok", outcome)
        self.assertEqual(outcome[1], {"markets": []})
        self.assertIn("/markets?limit=2", outcome[2])
        self.assertEqual(calls["urlopen"].call_count, 3)
        self.assertEqual(calls["sleep"].call_count, 2, "one sleep between attempts, none after the last")

    def test_retry_budget_is_bounded(self):
        outcome, calls = self.run_get([http_error(500, "Internal Server Error")] * 10, retries=4)
        self.assertEqual(outcome[0], "error", outcome)
        self.assertIn("HTTP 500", outcome[1])
        self.assertIn("after 4 attempts", outcome[1])
        self.assertEqual(calls["urlopen"].call_count, 4)
        self.assertEqual(calls["sleep"].call_count, 3)

    def test_client_error_fails_on_the_first_attempt(self):
        outcome, calls = self.run_get([http_error(404, "Not Found")] * 3)
        self.assertEqual(outcome[0], "error", outcome)
        self.assertIn("HTTP 404", outcome[1])
        self.assertEqual(calls["urlopen"].call_count, 1, "a 404 must not be retried")
        self.assertEqual(calls["sleep"].call_count, 0)

    def test_network_failure_is_retried(self):
        outcome, calls = self.run_get([urllib.error.URLError("connection reset"), ok({"markets": [{"ticker": "T"}]})])
        self.assertEqual(outcome[0], "ok", outcome)
        self.assertEqual(outcome[1]["markets"][0]["ticker"], "T")
        self.assertEqual(calls["urlopen"].call_count, 2)

    def test_429_keeps_its_documented_retry(self):
        outcome, calls = self.run_get([http_error(429, "Too Many Requests"), ok({"markets": []})])
        self.assertEqual(outcome[0], "ok", outcome)
        self.assertEqual(calls["urlopen"].call_count, 2)

    def test_429_backoff_doubles_and_5xx_backoff_is_linear(self):
        outcome, calls = self.run_get([http_error(429, "Too Many Requests")] * 10, retries=4)
        self.assertEqual(outcome[0], "error", outcome)
        waits = [c.args[0] for c in calls["sleep"].call_args_list]
        self.assertEqual(waits, [3.0, 6.0, 12.0], "429 backs off on the documented advice")

        outcome, calls = self.run_get([http_error(503, "Service Unavailable")] * 10, retries=4)
        waits = [c.args[0] for c in calls["sleep"].call_args_list]
        self.assertEqual(waits, [1.5, 3.0, 4.5])

    def test_scan_pauses_between_pages(self):
        self.assertGreater(self.mod.PAGE_PAUSE_SECONDS, 0)
        source = (ROOT / "scripts" / "collect.py").read_text()
        self.assertIn("time.sleep(PAGE_PAUSE_SECONDS)", source)

    def test_retry_status_set_is_the_documented_one(self):
        self.assertEqual(set(self.mod.RETRY_STATUS), {429, 500, 502, 503, 504})
        for code in (400, 401, 403, 404, 410):
            self.assertNotIn(code, self.mod.RETRY_STATUS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
