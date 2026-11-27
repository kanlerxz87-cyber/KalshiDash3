#!/usr/bin/env python3
"""Offline tests for the bounded collector relay (T55, arena-b25b0914).

Pins every bound documented in scripts/collect_relay.py and the shape of
.github/workflows/collect.yml, so the relay cannot quietly turn back into the
runaway dispatch loop of F-63 or the never-firing watchdog it replaces.
Whole relays are simulated with a fake clock: nothing sleeps, nothing touches git,
GitHub or the Kalshi API.

Run: python3 scripts/tests/test_collect_relay.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("collect_relay", ROOT / "scripts" / "collect_relay.py")
R = importlib.util.module_from_spec(spec)
sys.modules["collect_relay"] = R   # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(R)

FAIL: list[str] = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def setUpModule():
    """Point the relay's failure record at a temp dir (F-87).

    `make_pass` now records failures in `data/live/collector_health.json`. These tests
    deliberately exercise failing passes, so without this they would drop a real-looking health
    record into the working tree. ROOT itself is left alone: the fixtures resolve real
    `scripts/tests/...` paths through it.
    """
    global _TMP_ROOT
    _TMP_ROOT = tempfile.TemporaryDirectory(prefix="relay-root-")
    R.HEALTH_ROOT = Path(_TMP_ROOT.name)


def tearDownModule():
    _TMP_ROOT.cleanup()


class FakeWorld:
    """A clock plus recorders for every side effect run_relay can cause."""

    def __init__(self, outcomes=None, pass_seconds=70, active=None, roi_age=None, overshoot=0.0,
                 dispatch_ok=None):
        self.now = 1_800_000_000.0
        self.outcomes = outcomes            # callable(n) -> (outcome, detail)
        self.pass_seconds = pass_seconds    # seconds, or callable(n) -> seconds
        self.active = active or {}          # workflow -> count of other active runs
        self.roi_age = roi_age              # callable(now) -> minutes | None
        self.overshoot = overshoot          # added to every sleep: > 0 late wake-up, < 0 clock reads early
        self.dispatch_ok = dispatch_ok      # callable(attempt) -> bool
        self.dispatched: list[tuple[float, str]] = []
        self.attempts: list[tuple[float, str]] = []
        self.pass_starts: list[float] = []

    def clock(self):
        return self.now

    def sleep(self, s):
        assert s >= 0
        self.now += max(0.0, s + self.overshoot)

    def do_pass(self, n):
        if len(self.pass_starts) >= 200:     # 330/10 + 1 = 34 is the most a relay may ever make
            raise RuntimeError("runaway relay: more than 200 passes")
        self.pass_starts.append(self.now)
        self.now += self.pass_seconds(n) if callable(self.pass_seconds) else self.pass_seconds
        return self.outcomes(n) if self.outcomes else ("committed", f"sha{n}")

    def active_runs(self, wf):
        return self.active.get(wf, 0)

    def dispatch(self, wf):
        self.attempts.append((self.now, wf))
        if self.dispatch_ok and not self.dispatch_ok(wf, sum(1 for _, w in self.attempts if w == wf)):
            return False
        self.dispatched.append((self.now, wf))
        return True

    def roi_age_min(self):
        return self.roi_age(self.now) if self.roi_age else 5.0

    def run(self, plan):
        return R.run_relay(plan, clock=self.clock, sleep=self.sleep, do_pass=self.do_pass,
                           active_runs=self.active_runs, dispatch=self.dispatch,
                           roi_age_min=self.roi_age_min, log=lambda *_: None)


def main() -> int:
    print("plans")
    p = R.make_plan("main")
    check((p.relay_minutes, p.interval_minutes, p.commit) == (330, 15, True),
          f"main defaults to a 330-min relay every 15 min ({p.relay_minutes}/{p.interval_minutes})")
    check(p.successor_allowed and p.desk_allowed, "main may dispatch a successor and the desk scan")
    b = R.make_plan("arena/x-kalshidash3")
    check(b.relay_minutes == 0 and not b.successor_allowed and not b.desk_allowed,
          "a session branch defaults to one pass and dispatches nothing")
    b2 = R.make_plan("arena/x-kalshidash3", relay_in="30")
    check(b2.relay_minutes == 30 and not b2.successor_allowed and not b2.desk_allowed,
          "a branch may loop when asked but can never dispatch a successor or desk scan")
    k = R.make_plan("main", kill="OFF ")
    check(k.relay_minutes == 0 and not k.successor_allowed and not k.desk_allowed and k.killed,
          "COLLECT_RELAY=off (any case/whitespace) gives one pass and no dispatches on main")
    d = R.make_plan("main", relay_in="6", interval_in="2", commit_in="false")
    check(d.interval_minutes == 2 and not d.successor_allowed and not d.desk_allowed,
          "a dry run may loop every 2 min but dispatches nothing")
    check(R.make_plan("main", interval_in="2").interval_minutes == R.INTERVAL_MIN_COMMIT,
          "a committing run is clamped to the 10-min floor")
    check(R.make_plan("main", relay_in="9999").relay_minutes == R.RELAY_MAX_MIN, "relay is clamped to 330 min")
    check(R.make_plan("main", relay_in="abc", interval_in="").relay_minutes == 330, "garbage input -> default")
    check(R.make_plan("develop", default_branch="develop").successor_allowed,
          "the default branch is configurable (DEFAULT_BRANCH), not hard-wired")

    print("rate bounds")
    pushes_per_hour = 60 / R.INTERVAL_MIN_COMMIT + 60 / R.DESK_STALE_MIN
    check(pushes_per_hour <= 10, f"worst-case pushes/h {pushes_per_hour:g} <= Pages soft limit of 10 builds/h")
    check(R.MIN_ELAPSED_FOR_SUCCESSOR >= 60, "a successor needs >= 60 min of looping (F-63 was ~1-2 min)")
    check(R.RELAY_MAX_MIN + 15 <= 360, "relay budget + a final pass fits the 6 h job limit")

    print("full relay on main (fake clock)")
    w = FakeWorld()
    res = w.run(p)
    starts = [t for t, _, _ in res.passes]
    gaps = {round(b - a) for a, b in zip(starts, starts[1:])}
    check(len(res.passes) == 23, f"330 min / 15 min -> 23 passes (got {len(res.passes)})")
    check(gaps == {900}, f"passes start exactly 15 min apart (gaps {sorted(gaps)})")
    check(starts[-1] - starts[0] <= 330 * 60, "no pass starts after the relay budget")
    succ = [t for t, wf in w.dispatched if wf == "collect.yml"]
    check(len(succ) == 1 and starts[-2] < succ[0] <= starts[-1],
          "exactly one successor, queued right before the final pass")
    check(succ and succ[0] - starts[0] >= R.MIN_ELAPSED_FOR_SUCCESSOR * 60, "... and only after >= 120 min of looping")
    check(res.successor[0] is True, f"successor recorded ({res.successor[1]})")
    check(not any(wf == "desk.yml" for _, wf in w.dispatched), "fresh roi.json -> no desk dispatch")
    pages = [t for t, wf in w.dispatched if wf == "pages.yml"]
    check(len(pages) == 23 == len(res.publishes), f"one pages.yml dispatch per committed pass ({len(pages)}/23)")

    print("publishing")
    mixed = {1: ("committed", "a"), 2: ("no change", ""), 3: ("failed", "validators: test_alerts"),
             4: ("dropped", "push race"), 5: ("committed", "b")}
    w = FakeWorld(outcomes=lambda n: mixed.get(n, ("no change", "")))
    res = w.run(p)
    pages = [t for t, wf in w.dispatched if wf == "pages.yml"]
    check(len(pages) == 2 and pages[0] < w.pass_starts[1] and w.pass_starts[4] < pages[1] < w.pass_starts[5],
          "pages.yml only after the two passes that committed (not after no change / failed / dropped)")
    check(p.publish_allowed and not b.publish_allowed and not k.publish_allowed and not d.publish_allowed,
          "publishing only from main with commits on and the kill switch off")

    print("real clocks (the 2026-11-21 20:42Z branch dry run made 2 passes where 3 were due)")
    for label, over in (("sleep overshoots 5 ms", 0.005), ("sleep overshoots 3 s", 3.0),
                        ("wall clock reads 5 ms early", -0.005)):
        w = FakeWorld(overshoot=over)
        res = w.run(p)
        g = [b - a for a, b in zip(w.pass_starts, w.pass_starts[1:])]
        check(len(res.passes) == 23 and min(g) > 890, f"{label}: still 23 passes, none repeated (min gap {min(g):.3f}s)")
    w = FakeWorld(overshoot=-0.005, pass_seconds=0, outcomes=lambda n: ("failed", "API probe URLError"))
    res = w.run(p)
    g = [b - a for a, b in zip(w.pass_starts, w.pass_starts[1:])]
    check(len(res.passes) == 23 and min(g) > 890,
          f"instant failing passes + an early clock: no slot runs twice ({len(res.passes)} passes, min gap {min(g):.3f}s)")
    w = FakeWorld(overshoot=0.005)
    res = w.run(R.make_plan("arena/x-kalshidash3", relay_in="4", interval_in="2", commit_in="false"))
    check(len(res.passes) == 3, f"4-min / 2-min dry run with a real-ish clock -> 3 passes (got {len(res.passes)})")

    print("overruns")
    w = FakeWorld(pass_seconds=lambda n: 40 * 60 if n == 3 else 70)
    res = w.run(p)
    g = [b - a for a, b in zip(w.pass_starts, w.pass_starts[1:])]
    check(min(g) >= 900, f"a 40-min pass skips missed slots instead of bursting (min gap {min(g):.0f}s)")
    check(len(res.passes) == 21, f"... and the two slots it covered are dropped (got {len(res.passes)} passes)")
    check(all(round((t - w.pass_starts[0]) % 900) == 0 for t in w.pass_starts), "... and later passes stay on the grid")
    w = FakeWorld(pass_seconds=lambda n: 60 * 60 if n == 23 else 70)
    res = w.run(p)
    succ = [t for t, wf in w.dispatched if wf == "collect.yml"]
    check(len(succ) == 1 and succ[0] <= w.pass_starts[-1],
          "a final pass that hangs into the job timeout still leaves one successor queued")

    print("successor retries")
    w = FakeWorld(outcomes=lambda n: ("committed", "x") if n == 23 else ("failed", "collect"))
    res = w.run(p)
    succ = [t for t, wf in w.dispatched if wf == "collect.yml"]
    check(len(succ) == 1 and succ[0] > w.pass_starts[-1], "only the final pass succeeded -> one successor, after it")
    w = FakeWorld(dispatch_ok=lambda wf, attempt: wf != "collect.yml" or attempt > 1)
    res = w.run(p)
    tries = [t for t, wf in w.attempts if wf == "collect.yml"]
    sent = [t for t, wf in w.dispatched if wf == "collect.yml"]
    check(len(tries) == 2 and len(sent) == 1 and res.successor[0],
          "a failed dispatch before the final pass is retried exactly once, after it")
    w = FakeWorld(dispatch_ok=lambda wf, attempt: wf != "collect.yml")
    res = w.run(p)
    check(len([1 for _, wf in w.attempts if wf == "collect.yml"]) == 2 and not res.successor[0]
          and "cron" in res.successor[1], "two failed dispatches -> give up; the crons stay the restart path")

    print("desk dispatch spacing")
    w = FakeWorld(roi_age=lambda now: 999.0)          # roi.json never gets fresher (desk keeps failing)
    w.run(p)
    desk = [t for t, wf in w.dispatched if wf == "desk.yml"]
    spacing = [b - a for a, b in zip(desk, desk[1:])]
    check(len(desk) >= 2 and min(spacing) >= R.DESK_STALE_MIN * 60,
          f"stale roi.json -> desk dispatched at most every {R.DESK_STALE_MIN} min ({len(desk)} in 5.5 h)")
    w = FakeWorld(roi_age=lambda now: 999.0, active={"desk.yml": 1})
    w.run(p)
    check(not any(wf == "desk.yml" for _, wf in w.dispatched), "no desk dispatch while a desk run is in flight")

    print("successor guards")
    w = FakeWorld(outcomes=lambda n: ("failed", "API probe HTTP 503"))
    res = w.run(p)
    check(not any(wf == "collect.yml" for _, wf in w.dispatched) and "no pass succeeded" in res.successor[1],
          "a relay where every pass failed does not chain (crons restart it)")
    w = FakeWorld(active={"collect.yml": 1})
    res = w.run(p)
    check(not any(wf == "collect.yml" for _, wf in w.attempts), "no successor while another collect run is queued")
    short = R.make_plan("main", relay_in="60")
    w = FakeWorld()
    res = w.run(short)
    check(not any(wf == "collect.yml" for _, wf in w.dispatched) and "minimum" in res.successor[1],
          "a relay shorter than the 120-min minimum never dispatches a successor")
    ok, why = R.successor_decision(p, 400, 5, 0, already_dispatched=True)
    check(not ok, "never a second successor from the same run")

    print("runs that must dispatch nothing")
    for label, plan in (("branch", b), ("branch relay", b2), ("kill switch", k), ("dry run", d)):
        w = FakeWorld(roi_age=lambda now: 999.0)
        res = w.run(plan)
        check(w.attempts == [], f"{label}: zero dispatches ({len(res.passes)} pass(es))")
    w = FakeWorld()
    res = w.run(d)
    check(len(res.passes) == 4, f"dry run 6 min / 2 min -> 4 passes (got {len(res.passes)})")

    print("helpers")
    now = datetime(2026, 11, 21, 20, 0, 0, tzinfo=timezone.utc).timestamp()
    check(round(R.age_minutes("2026-11-21T19:30:00Z", now)) == 30, "age_minutes: 30 min")
    check(R.age_minutes("", now) is None and R.age_minutes("garbage", now) is None, "unknown age stays None")

    print("workflow file (.github/workflows/collect.yml)")
    y = (ROOT / ".github" / "workflows" / "collect.yml").read_text()
    check(re.search(r"group:\s*collect-\$\{\{\s*github\.ref\s*\}\}", y) is not None, "concurrency group is per ref")
    check(re.search(r"cancel-in-progress:\s*false", y) is not None, "a running relay is never cancelled by a new run")
    check("gh workflow run" not in y, "the YAML itself dispatches nothing (only the guarded script may)")
    check(len(re.findall(r"run:\s*python3 -u scripts/collect_relay\.py", y)) == 1, "the job runs the relay script once")
    m = re.search(r"timeout-minutes:\s*(\d+)", y)
    check(m is not None and R.RELAY_MAX_MIN + 10 <= int(m.group(1)) <= 360,
          f"job timeout covers the relay and stays under 6 h ({m.group(1) if m else None})")
    check(re.search(r"fetch-depth:\s*0", y) is not None, "full history checkout (passes reset and may rebase)")
    check(len(re.findall(r"cron:", y)) >= 1, "cron schedules remain as the restart path")
    check(re.search(r"actions:\s*write", y) is not None, "actions: write granted for the guarded dispatches")
    check("vars.COLLECT_RELAY" in y, "kill switch wired from the repository variable")

    print("script invariants")
    src = (ROOT / "scripts" / "collect_relay.py").read_text()
    check(src.count('"workflow", "run"') == 1, "exactly one place can issue `gh workflow run` (gh_dispatch)")
    check(src.count('dispatch("collect.yml")') == 1, "one code path dispatches a successor (consider_successor)")
    check(len(re.findall(r"\bgh_dispatch\(", src)) == 2, "gh_dispatch is only reachable through run_relay's guarded callback")
    check("--force" not in src and "push -f" not in src, "pushes are never forced")
    old = {"validate_live.py", "validate_alerts.py", "test_alerts.py", "test_collect_coverage.py",
           "test_settled_selection.py", "test_simulate.py", "validate_catalysts.py"}
    listed = {Path(path).name for _, path in R.VALIDATORS}
    check(old <= listed, f"every validator that gated the old single-pass commit still gates each pass")
    missing = [path for _, path in R.VALIDATORS if not (ROOT / path).exists()]
    check(not missing, f"every listed validator exists (missing: {missing})")

    print("one pass, in order (git, network and subprocesses stubbed)")
    calls: list[str] = []

    class Done:
        def __init__(self, rc=0, stderr=""):
            self.returncode, self.stdout, self.stderr = rc, "", stderr

    def fake_sh(args, timeout=600, check=False):
        calls.append(" ".join(args[1:2]) if args[0] == "python3" else " ".join(args[:2]))
        rc = 1 if fail_on and args[0] == "python3" and args[1] == fail_on else 0
        # A failing validator prints its reason to stderr; the relay must forward those lines
        # into the health record (F-108), so the stub emits a distinctive, recognisable tail.
        return Done(rc, stderr=(f"INVALID data from {args[1]}: assigned topic 'gas' but categories [] accept []"
                                if rc else ""))

    saved = (R.sh, R.sync_to_remote, R.probe_api, R.commit_and_push, R.discard_changes, R.annotate)
    notes: list[str] = []
    # No real workflow commands from a test: verify_release.py runs this inside pages.yml, where a printed
    # "::error::" would become a bogus annotation on the Pages check run.
    R.annotate = lambda level, title, text="", tail=15: notes.append(f"{level}: {title}")
    R.sh, R.sync_to_remote, R.probe_api = fake_sh, (lambda ref: "abc1234"), (lambda: (True, "HTTP 200"))
    R.commit_and_push = lambda ref: (calls.append("commit_and_push"), ("committed", "def5678"))[1]
    R.discard_changes = lambda: calls.append("discard")
    try:
        fail_on = None
        out = R.make_pass(R.make_plan("main"))(1)
        order = [c for c in calls if c.startswith("scripts/")]
        check(out == ("committed", "def5678") and calls[-1] == "commit_and_push", f"a clean pass commits last ({out})")
        check(order[0] == "scripts/tests/test_scope.py" and order[1] == "scripts/collect.py",
              "test_scope.py runs BEFORE collect.py (be07a04's intent kept)")
        check(order.count("scripts/tests/test_scope.py") == 2 and order.index("scripts/tests/validate_live.py") > 1,
              "... and again after collecting, on the new snapshot, before the commit")
        calls.clear(); fail_on = "scripts/tests/test_scope.py"
        out = R.make_pass(R.make_plan("main"))(2)
        check(out[0] == "failed" and "scripts/collect.py" not in calls and "commit_and_push" not in calls
              and any("pre-check test_scope FAILED" in x for x in notes),
              f"a failing pre-check collects and commits nothing, and says so ({out[1]})")
        calls.clear(); fail_on = "scripts/tests/validate_live.py"
        out = R.make_pass(R.make_plan("main"))(3)
        check(out[0] == "failed" and "commit_and_push" not in calls and "discard" in calls,
              f"a failing validator discards the pass ({out[1]})")
        # F-108: the health record must name the failing validator AND carry its own last lines.
        health = json.loads((R.HEALTH_ROOT / R.HEALTH_PATH).read_text())
        check(health.get("outcome") == "failed" and "validate_live" in (health.get("detail") or ""),
              f"the health record names the failing validator ({health.get('detail')!r})")
        check("categories [] accept []" in (health.get("stderr_tail") or ""),
              "the health record carries the failing validator's OWN stderr tail, not an empty string (F-108)")
        check("[validate_live]" in (health.get("stderr_tail") or ""),
              "the tail is labelled with which validator produced it")
        calls.clear(); fail_on = None
        out = R.make_pass(R.make_plan("main", commit_in="false"))(4)
        check(out[0] == "validated" and "commit_and_push" not in calls, "a dry-run pass validates and commits nothing")
    finally:
        R.sh, R.sync_to_remote, R.probe_api, R.commit_and_push, R.discard_changes, R.annotate = saved

    print("")
    if FAIL:
        print(f"FAILED: {len(FAIL)} check(s)")
        return 1
    print("OK: collector relay bounds, decisions and workflow shape verified.")
    return 0


if __name__ == "__main__":
    # This file runs its own check harness (not unittest), so the unittest hook above would
    # never fire here: call it directly, or a deliberately failing fixture would write a
    # real-looking data/live/collector_health.json into the working tree.
    setUpModule()
    try:
        sys.exit(main())
    finally:
        tearDownModule()
