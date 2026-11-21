#!/usr/bin/env python3
"""Tests for scripts/watchdog.py — the bounded freshness decision.

The failure this guards against was shipped once (F-63): the first freshness step dispatched
a collection unconditionally from inside a collection, so it chained five runs in five
minutes. Every branch is pinned here, especially "fresh snapshot must not dispatch", which is
what stops a chain.

Run: python3 scripts/tests/test_watchdog.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location("watchdog", ROOT / "scripts" / "watchdog.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

checks = 0
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    global checks
    checks += 1
    if not cond:
        failures.append(msg)


NOW = datetime(2026, 11, 21, 20, 30, 0, tzinfo=timezone.utc)


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# 1. fresh snapshot -> never dispatch (this is the anti-chain guard)
for age in (0, 1, 20, 34):
    d = W.decide(at(age), NOW, 0, 0)
    check(d["dispatch"] is False, f"a {age}-minute-old snapshot must not dispatch (got {d['reason']})")
    check("fresh" in d["reason"], f"the skip reason for a fresh snapshot must say so (got {d['reason']})")

# 2. stale snapshot, nothing running -> dispatch exactly once
for age in (35, 36, 120, 300):
    d = W.decide(at(age), NOW, 0, 0)
    check(d["dispatch"] is True, f"a {age}-minute-old snapshot with nothing in flight must dispatch (got {d['reason']})")
    check("stale" in d["reason"], f"the dispatch reason must say the snapshot is stale (got {d['reason']})")

# 3. boundary is inclusive at stale_min, and the threshold is configurable
check(W.decide(at(35), NOW, 0, 0)["dispatch"] is True, "35m must be stale at the default threshold")
check(W.decide(at(34.9), NOW, 0, 0)["dispatch"] is False, "34.9m must be fresh at the default threshold")
check(W.decide(at(50), NOW, 0, 0, stale_min=60)["dispatch"] is False, "a custom 60m threshold must treat 50m as fresh")
check(W.decide(at(70), NOW, 0, 0, stale_min=60)["dispatch"] is True, "a custom 60m threshold must treat 70m as stale")

# 4. in-flight collection -> never dispatch, whatever the age
for age in (120, 600):
    d = W.decide(at(age), NOW, 1, 0)
    check(d["dispatch"] is False, "an in-flight collection must block a second dispatch")
    check("in flight" in d["reason"], f"the skip reason must name the in-flight run (got {d['reason']})")

# 5. hourly cap -> never dispatch, whatever the age
for used in (3, 4):
    d = W.decide(at(600), NOW, 0, used)
    check(d["dispatch"] is False, f"the hourly cap (3) must block dispatch at {used} used")
    check("cap" in d["reason"], f"the skip reason must name the cap (got {d['reason']})")
check(W.decide(at(600), NOW, 0, 2)["dispatch"] is True, "2 dispatches in the hour must still allow one more (cap is 3)")

# 6. no timestamp -> skip, never dispatch on absent data
for junk in ("", "not-a-date", "2026-13-45T99:99:99Z"):
    d = W.decide(junk, NOW, 0, 0)
    check(d["dispatch"] is False, f"an unparseable timestamp ({junk!r}) must not dispatch")

# 7. parse_ts accepts the exact format the collector writes
p = W.parse_ts("2026-11-21T20:21:50Z")
check(p is not None and p.year == 2026 and p.hour == 20 and p.tzinfo is not None,
      "parse_ts must accept the collector's Z-suffixed UTC timestamp and stay timezone-aware")

# 8. the decision reports the facts it used, so a log line is auditable
d = W.decide(at(90), NOW, 0, 1)
for key in ("collected_at", "in_flight", "dispatches_last_hour", "stale_min", "max_per_hour", "age_min"):
    check(key in d, f"the decision must report {key} so the workflow log is auditable")
check(d["age_min"] == 90.0, f"age_min must be computed, got {d['age_min']}")

# 9. the CLI contract the workflow relies on
run = subprocess.run([sys.executable, str(ROOT / "scripts" / "watchdog.py"),
                      "--collected-at", at(90), "--now", "2026-11-21T20:30:00Z"],
                     capture_output=True, text=True)
check(run.returncode == 0, "the CLI must exit 0 even when skipping")
check(run.stdout.strip() == "dispatch", f"the CLI must print 'dispatch' for a stale snapshot, got {run.stdout.strip()!r}")
run2 = subprocess.run([sys.executable, str(ROOT / "scripts" / "watchdog.py"),
                       "--collected-at", at(2), "--now", "2026-11-21T20:30:00Z", "--json"],
                      capture_output=True, text=True)
check(run2.returncode == 0, "the CLI must exit 0 on skip")
try:
    doc = json.loads(run2.stdout)
    check(doc["dispatch"] is False, "--json must report dispatch=false for a fresh snapshot")
except json.JSONDecodeError:
    check(False, "--json must emit valid JSON")

# 10. the workflow must actually run the watchdog OUTSIDE the collect run, or the stuck case
#     (scheduler drops collect -> nothing runs collect) is not fixed.
desk = (ROOT / ".github" / "workflows" / "desk.yml").read_text()
check("scripts/watchdog.py" in desk,
      "desk.yml (a separate schedule) must consult scripts/watchdog.py so a dropped collect run is revived")
check("workflow_dispatch" in desk or "gh workflow run" in desk,
      "desk.yml must be able to dispatch the collector")

if failures:
    print(f"FAIL ({len(failures)} of {checks} checks)")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print(f"OK: {checks} checks passed (fresh never dispatches, stale dispatches once, in-flight and hourly caps honoured)")
