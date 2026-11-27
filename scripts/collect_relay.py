#!/usr/bin/env python3
"""Bounded collector relay for .github/workflows/collect.yml (T55, arena-b25b0914).

Why this exists
  The snapshot layer is only as fresh as the runs that write it, and on this repository the scheduler
  did not deliver them. Measured with the Actions API on 2026-11-21 (COORDINATION.md, session
  arena-b25b0914): between 06:49Z and 20:17Z collect.yml had 2 `schedule` runs against ~67 configured,
  desk.yml 2 against ~81, and the snapshot aged ~5 h behind a 45-minute stale banner. GitHub documents
  that "the schedule event can be delayed during periods of high loads ... some queued jobs may be
  dropped" (https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
  The previous "freshness watchdog" step could not compensate: it ran only after a successful commit,
  when the snapshot it measured was ~0 minutes old, so its `age >= 35 min` condition could never hold
  (0 dispatches in that window). This script replaces it.

What one run does
  pass  = sync to the remote head -> probe the demo REST root -> PRECHECKS (test_scope.py) -> collect.py
          -> build_alerts.py -> catalysts.py -> simulate.py -> every validator in VALIDATORS
          -> commit data/live -> push (retried, never forced) -> on the default branch, dispatch pages.yml
          once for that commit (its release gate runs verify_release.py before it deploys).
  relay = on the default branch, repeat the pass on a fixed grid (pass k starts at t0 + k*INTERVAL;
          a pass that overruns skips the slots it missed instead of bursting to catch up) while
          k*INTERVAL <= RELAY, and dispatch exactly one successor run of collect.yml right before the
          final pass. The concurrency group holds that successor pending until this run ends, however
          it ends (even a job timeout in the final pass), so the chain never depends on a schedule
          event. Anywhere else: one pass.

Bounds (each is enforced below and pinned by scripts/tests/test_collect_relay.py)
  1. A successor is dispatched only from the default branch, only after the loop ran for at least
     MIN_ELAPSED_FOR_SUCCESSOR minutes, only if at least one pass succeeded, at most once per run, and
     never while another collect.yml run for the branch is queued, pending, waiting or in progress.
     It is evaluated right before the final pass and, only if not sent then, once after it.
     (The first watchdog in this repository dispatched unconditionally after ~1-minute runs and looped,
     F-63; a successor that can only follow >= 2 h of work cannot do that.)
  2. The workflow's concurrency group is per ref. GitHub runs at most one run per group and keeps at
     most one pending, a newer pending run replacing the older one
     (https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
  3. Repository variable COLLECT_RELAY=off turns the relay and every dispatch off without a code change.
     It is read when a run starts. To stop a relay that is already running: set the variable, then cancel
     the run (`gh run cancel <id>`); whatever run is pending behind it then makes one pass and stops.
  4. desk.yml (the only writer of data/live/roi.json) is dispatched only when roi.json is older than
     DESK_STALE_MIN, no desk.yml run is in flight for the branch, and this run has not dispatched one in
     the last DESK_STALE_MIN minutes. desk.yml dispatches nothing itself, so this cannot loop.
  5. A pass whose validators fail commits nothing. A pass that loses a push race to a conflicting
     change is dropped; the next pass starts again from the new remote head.
  6. Pushes stay inside GitHub Pages' documented soft limit of 10 legacy builds per hour
     (https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits): a
     committing run cannot loop faster than every INTERVAL_MIN_COMMIT (10) minutes, so collect adds at
     most 6 pushes/h (4/h at the 15-minute default) and the desk dispatch at most 2/h. Only a dry run,
     which pushes nothing, may loop faster (INTERVAL_MIN_DRY_RUN).
  7. Publishing does not rely on undocumented behaviour. The GITHUB_TOKEN docs say "Commits pushed by a
     GitHub Actions workflow that uses the GITHUB_TOKEN do not trigger a GitHub Pages build", although
     GET /repos/{owner}/{repo}/pages/builds on this repository lists 29 of 96 legacy builds pushed by
     github-actions[bot] (2026-11-21). So each committed pass on the default branch dispatches pages.yml
     once ("workflow_dispatch ... events always create workflow runs", same page); pages.yml's own
     concurrency group keeps at most one pending deploy. Nothing is published for a pass that did not
     commit, from a branch, from a dry run, or with the kill switch on.

Nothing here holds or needs a credential beyond the workflow's own GITHUB_TOKEN; the Kalshi calls are
the same public, unauthenticated demo endpoints collect.py already uses.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("KALSHI_BASE", "https://external-api.demo.kalshi.co/trade-api/v2")

RELAY_DEFAULT_MIN = 330          # 5 h 30 m: the job limit is 6 h (https://docs.github.com/en/actions/reference/limits)
RELAY_MAX_MIN = 330
INTERVAL_DEFAULT_MIN = 15
INTERVAL_MIN_COMMIT = 10         # <= 6 collect pushes/h + <= 2 desk pushes/h, under the 10 builds/h soft limit
INTERVAL_MIN_DRY_RUN = 2         # a dry run pushes nothing, so it may loop faster (used to test the loop)
INTERVAL_MAX_ALLOWED = 60
MIN_ELAPSED_FOR_SUCCESSOR = 120  # minutes of looping before a successor may be dispatched
DESK_STALE_MIN = 30
ACTIVE_STATUSES = {"queued", "in_progress", "pending", "waiting", "requested"}

# Offline checks that must pass BEFORE anything is collected. arena-20d7ddf7 added test_scope.py as a step
# ahead of collect.py on main (be07a04: "so an F-65/F-66 regression cannot publish"); a failure skips the pass.
PRECHECKS = [
    ("test_scope", "scripts/tests/test_scope.py"),
]
PIPELINE = [
    ("collect", ["python3", "scripts/collect.py", "--orderbooks", "4"], 1200),
    ("build_alerts", ["python3", "scripts/build_alerts.py"], 600),
    ("catalysts", ["python3", "scripts/catalysts.py"], 600),
    ("simulate", ["python3", "scripts/simulate.py"], 600),
]
# Every validator that gated a commit in the single-pass workflow, plus test_scope.py again: it also reads
# data/live/markets.json, so after collecting it checks the NEW snapshot before anything is committed.
VALIDATORS = [
    ("test_scope", "scripts/tests/test_scope.py"),
    ("validate_live", "scripts/tests/validate_live.py"),
    ("validate_alerts", "scripts/tests/validate_alerts.py"),
    ("test_alerts", "scripts/tests/test_alerts.py"),
    ("test_coverage", "scripts/tests/test_collect_coverage.py"),
    ("test_selection", "scripts/tests/test_settled_selection.py"),
    ("test_simulate", "scripts/tests/test_simulate.py"),
    ("validate_catalysts", "scripts/tests/validate_catalysts.py"),
]
OK_OUTCOMES = ("committed", "no change", "validated")


# --------------------------------------------------------------------------- pure decisions

def parse_minutes(value, default: int, lo: int, hi: int) -> int:
    """An input in minutes, clamped to [lo, hi]; empty or garbage means `default`."""
    try:
        v = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class Plan:
    ref: str
    on_default_branch: bool
    relay_minutes: int
    interval_minutes: int
    commit: bool
    successor_allowed: bool
    desk_allowed: bool
    publish_allowed: bool
    killed: bool


def make_plan(ref: str, relay_in=None, interval_in=None, commit_in=None, kill=None,
              default_branch: str = "main") -> Plan:
    on_main = ref == default_branch
    killed = str(kill or "").strip().lower() == "off"
    relay = parse_minutes(relay_in, RELAY_DEFAULT_MIN if on_main else 0, 0, RELAY_MAX_MIN)
    if killed:
        relay = 0
    commit = str(commit_in or "true").strip().lower() != "false"
    floor = INTERVAL_MIN_COMMIT if commit else INTERVAL_MIN_DRY_RUN
    interval = parse_minutes(interval_in, INTERVAL_DEFAULT_MIN, floor, INTERVAL_MAX_ALLOWED)
    return Plan(
        ref=ref,
        on_default_branch=on_main,
        relay_minutes=relay,
        interval_minutes=interval,
        commit=commit,
        # A dry run, a branch run or a switched-off relay never dispatches anything.
        successor_allowed=on_main and relay > 0 and commit and not killed,
        desk_allowed=on_main and commit and not killed,
        publish_allowed=on_main and commit and not killed,
        killed=killed,
    )


def is_final_slot(slot: int, plan: Plan) -> bool:
    """True when no later slot fits the relay budget (always true for a single-pass run)."""
    return plan.relay_minutes <= 0 or (slot + 1) * plan.interval_minutes > plan.relay_minutes


def next_slot(t0: float, slot: int, now: float, plan: Plan):
    """(k, start_epoch) of the next pass on the fixed grid t0 + k*interval, or None when the run should stop.

    Slots are counted, not derived from the previous pass's start time: a real sleep() overshoots by a few
    milliseconds, and chaining `previous start + interval` drifted the boundary pass out of the budget
    (a 4-min/2-min dry run made 2 passes instead of 3; the branch run of 2026-11-21 20:42Z). k is always
    > slot (a slot never runs twice, even if the wall clock reads early after a sleep) and is the first
    slot after `now` (a pass that overran skips the slots it missed; it never bursts to catch up)."""
    if plan.relay_minutes <= 0:
        return None
    step = plan.interval_minutes * 60
    k = max(slot + 1, int((now - t0) // step) + 1)
    if k * plan.interval_minutes > plan.relay_minutes:
        return None
    return k, t0 + k * step


def successor_decision(plan: Plan, elapsed_min: float, ok_passes: int, other_active: int,
                       already_dispatched: bool):
    if not plan.successor_allowed:
        return False, "successor not allowed for this run (branch, dry run, single pass or COLLECT_RELAY=off)"
    if already_dispatched:
        return False, "a successor was already dispatched by this run"
    if elapsed_min < MIN_ELAPSED_FOR_SUCCESSOR:
        return False, f"looped {elapsed_min:.0f} min < {MIN_ELAPSED_FOR_SUCCESSOR} min minimum"
    if ok_passes < 1:
        return False, "no pass succeeded in this run; the cron schedules restart the relay"
    if other_active > 0:
        return False, f"{other_active} other collect.yml run(s) already queued/running for {plan.ref}"
    return True, "dispatching one successor"


def desk_decision(plan: Plan, roi_age_min, desk_active: int, last_desk_dispatch_age_min):
    if not plan.desk_allowed:
        return False, "desk dispatch not allowed for this run"
    if roi_age_min is not None and roi_age_min < DESK_STALE_MIN:
        return False, f"roi.json is {roi_age_min:.0f} min old (< {DESK_STALE_MIN})"
    if desk_active > 0:
        return False, f"{desk_active} desk.yml run(s) already in flight"
    if last_desk_dispatch_age_min is not None and last_desk_dispatch_age_min < DESK_STALE_MIN:
        return False, f"this run dispatched desk.yml {last_desk_dispatch_age_min:.0f} min ago"
    return True, "roi.json is stale: dispatching one desk scan"


def age_minutes(iso, now_epoch: float):
    if not iso:
        return None
    try:
        t = datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None
    return (now_epoch - t) / 60.0


# --------------------------------------------------------------------------- relay loop

@dataclass
class RelayResult:
    passes: list = field(default_factory=list)       # (started_epoch, outcome, detail)
    desk_dispatches: list = field(default_factory=list)
    publishes: list = field(default_factory=list)   # epochs of pages.yml dispatches (one per committed pass)
    successor: tuple = (False, "")


def run_relay(plan: Plan, *, clock, sleep, do_pass, active_runs, dispatch, roi_age_min, log=print) -> RelayResult:
    """The loop, with every side effect injected so the bounds can be tested offline."""
    res = RelayResult()
    t0 = clock()
    last_desk = None
    slot = 0
    sent = False

    def consider_successor(stage: str):
        nonlocal sent
        ok = sum(1 for _, o, _ in res.passes if o in OK_OUTCOMES)
        go, why = successor_decision(plan, (clock() - t0) / 60.0, ok, active_runs("collect.yml"), sent)
        if go:
            sent = dispatch("collect.yml")
            why = why if sent else "dispatch failed; the cron schedules remain the restart path"
        res.successor = (sent, why)
        log(f"successor ({stage}): {why}")

    if not plan.successor_allowed:
        res.successor = (False, "successor not allowed for this run (branch, dry run, single pass or COLLECT_RELAY=off)")
    while True:
        if plan.successor_allowed and not sent and is_final_slot(slot, plan):
            # Queue the successor before the final pass: it waits in the concurrency group and starts
            # when this run ends, even if the final pass hangs until the job timeout.
            consider_successor("before the final pass")
        started = clock()
        outcome, detail = do_pass(len(res.passes) + 1)
        res.passes.append((started, outcome, detail))
        log(f"pass {len(res.passes)}: {outcome} {detail}".rstrip())

        if plan.publish_allowed and outcome == "committed":
            published = dispatch("pages.yml")
            if published:
                res.publishes.append(clock())
            log(f"  publish: pages.yml {'dispatched' if published else 'dispatch failed; the next commit retries'}")

        if plan.desk_allowed:
            now = clock()
            go, why = desk_decision(plan, roi_age_min(), active_runs("desk.yml"),
                                    None if last_desk is None else (now - last_desk) / 60.0)
            log(f"  desk scan: {why}")
            if go and dispatch("desk.yml"):
                last_desk = now
                res.desk_dispatches.append(now)

        nxt = next_slot(t0, slot, clock(), plan)
        if nxt is None:
            break
        slot, start = nxt
        wait = start - clock()
        if wait > 0:
            sleep(wait)

    if plan.successor_allowed and not sent:
        # Not sent before the final pass (no pass had succeeded yet, the run ended early after an overrun,
        # or the dispatch failed): one more evaluation now that every pass is done.
        consider_successor("after the final pass")
    return res


# --------------------------------------------------------------------------- side effects (CI only)

def sh(args, timeout=600, check=False):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} -> {p.returncode}: {p.stderr.strip()[:400]}")
    return p


def _cmd_escape(value: str, prop: bool = False) -> str:
    # Workflow-command escaping: %, CR and LF in the message; also ':' and ',' in a property value.
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value


def annotate(level: str, title: str, text: str = "", tail: int = 15):
    """One annotation per call (title + the tail of `text`). One command per line would spend the
    per-step annotation allowance on a single failure and hide the ones after it."""
    body = "\n".join((text or "").strip().splitlines()[-tail:])
    print(f"::{level} title={_cmd_escape(title, prop=True)}::{_cmd_escape(body or title)}")


def probe_api() -> tuple[bool, str]:
    req = urllib.request.Request(BASE + "/exchange/status", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:  # DNS / TLS / timeout
        return False, f"{type(e).__name__}: {e}"


def sync_to_remote(ref: str) -> str:
    """Start every pass from the branch's current remote head (a pending run's checkout can be hours old)."""
    sh(["git", "fetch", "--quiet", "origin", ref], timeout=120, check=True)
    sh(["git", "reset", "--hard", "--quiet", "FETCH_HEAD"], check=True)
    sh(["git", "clean", "-fdq", "--", "data/live"])
    return sh(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()


def discard_changes():
    sh(["git", "reset", "--hard", "--quiet", "HEAD"])
    sh(["git", "clean", "-fdq", "--", "data/live"])


def commit_and_push(ref: str) -> tuple[str, str]:
    sh(["git", "add", "data/live"], check=True)
    if sh(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return "no change", ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    sh(["git", "commit", "--quiet", "-m", f"data: demo snapshot {stamp}"], check=True)
    for attempt in range(1, 4):
        if sh(["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{ref}"], timeout=120).returncode == 0:
            return "committed", sh(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
        # Someone else pushed first. Rebase onto their head (never force); a conflict drops this pass.
        sh(["git", "fetch", "--quiet", "origin", ref], timeout=120)
        if sh(["git", "rebase", "--quiet", "FETCH_HEAD"]).returncode != 0:
            sh(["git", "rebase", "--abort"])
            annotate("warning", f"pass dropped: lost a push race to a conflicting change on {ref} (attempt {attempt})")
            return "dropped", "push race with a conflicting change"
        time.sleep(2 * attempt)
    annotate("warning", f"pass dropped: push to {ref} still rejected after 3 attempts")
    return "dropped", "push rejected 3 times"


HEALTH_PATH = "data/live/collector_health.json"
#: Repo root the health file is written under. Overridable so the relay's own tests, which
#: deliberately exercise failing passes, cannot drop a real-looking record into the working
#: tree. Production leaves it None, which means "use ROOT".
HEALTH_ROOT = None


def record_health(pass_no: int, detail: str, tail: str = "", ref: str | None = None) -> str:
    """Record WHY a pass did not commit, inside the repository (F-85).

    Why: the reason a pass failed only ever existed in the job's stdout, and Actions job
    logs are served from `productionresultssa6.blob.core.windows.net`, which is not
    reachable from every environment that has to diagnose a stall — and a wedged run's
    output dies with the run. This file is tiny, is committed on its own (never with the
    snapshot), and carries the failing step's own last lines. It contains no credentials:
    the collector is credential-free by construction.

    Returns the git outcome of the health commit ("committed"/"skipped"/"dropped") so a
    caller can log it; it never raises, because a diagnostic must not become a new failure.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "schema": 1,
        "generated_at": stamp,
        "pass": pass_no,
        "outcome": "failed",
        "detail": detail,
        "stderr_tail": (tail or "")[-2000:],
        "run": {
            "workflow": "collect.yml",
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "sha": os.environ.get("GITHUB_SHA"),
        },
        "note": ("Written by scripts/collect_relay.py when a pass does not commit. Read by humans; "
                 "the site's staleness banner is what readers see. Never contains credentials."),
    }
    try:
        path = (HEALTH_ROOT or ROOT) / HEALTH_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=1) + "\n")
        sh(["git", "add", HEALTH_PATH])
        if sh(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return "skipped"
        message = f"ops: collector health {stamp} ({detail})"
        sh(["git", "commit", "--quiet", "-m", message])
        target = ref or os.environ.get("GITHUB_REF_NAME") or "main"
        for attempt in range(1, 4):
            if sh(["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{target}"], timeout=120).returncode == 0:
                return "committed"
            sh(["git", "fetch", "--quiet", "origin", target], timeout=120)
            if sh(["git", "rebase", "--quiet", "FETCH_HEAD"]).returncode != 0:
                sh(["git", "rebase", "--abort"])
                return "dropped"
            time.sleep(2 * attempt)
    except Exception as e:  # a diagnostic must never break the relay
        print(f"  ! health record failed: {type(e).__name__}: {e}")
        return "failed"
    return "failed"


def write_health_ok(pass_no: int, ref: str | None = None) -> str:
    """Record that the MOST RECENT pass committed, so the health file is never stale (F-98).

    Why: data/live/collector_health.json was written only when a pass FAILED, so after the
    collector recovered the file still said "outcome": "failed" with the old timestamp. On
    2026-11-25 the file read "failed · validators: validate_alerts · 12:01:52Z" while the
    collector was publishing a healthy snapshot every 15 minutes (13:16:43Z and later).
    A reader - a human, or the next session, which the file's own note says is who reads it -
    would conclude the collector was broken when it was not. The file is now the outcome of
    the most recent pass in BOTH directions.

    It is written to the working tree before the snapshot commit, and commit_and_push()
    stages data/live, so the "ok" record lands in the same commit as the snapshot it
    describes: no extra commit, no extra push, no race with the relay's own history.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    collected = None
    try:
        collected = json.loads((ROOT / "data" / "live" / "markets.json").read_text()).get("collected_at")
    except (OSError, json.JSONDecodeError, AttributeError):
        collected = None
    doc = {
        "schema": 1,
        "generated_at": stamp,
        "pass": pass_no,
        "outcome": "ok",
        "detail": "snapshot committed",
        "snapshot_collected_at": collected,
        "stderr_tail": "",
        "run": {
            "workflow": "collect.yml",
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "sha": os.environ.get("GITHUB_SHA"),
        },
        "note": ("Written by scripts/collect_relay.py for EVERY pass: 'failed' when a pass could not "
                 "commit, 'ok' when it did. Read by humans; the site's staleness banner is what readers "
                 "see. Never contains credentials."),
    }
    try:
        path = (HEALTH_ROOT or ROOT) / HEALTH_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=1) + "\n")
        return "written"
    except Exception as e:  # a diagnostic must never break the relay
        print(f"  ! health record (ok) failed: {type(e).__name__}: {e}")
        return "failed"


def make_pass(plan: Plan):
    def do_pass(n: int) -> tuple[str, str]:
        def fail(detail: str, tail: str = "") -> tuple[str, str]:
            # Every non-committing pass leaves a reason in the repository, not only in stdout.
            # A validator failure now passes its output as `tail`, so the health file carries the
            # validator's own message (F-108).
            outcome = record_health(n, detail, tail, plan.ref)
            print(f"  health record: {outcome}")
            return "failed", detail

        try:
            head = sync_to_remote(plan.ref)
        except RuntimeError as e:
            annotate("error", f"pass {n}: could not sync to origin/{plan.ref}", str(e))
            return fail("git sync", str(e))
        ok, why = probe_api()
        if not ok:
            annotate("warning", f"pass {n}: demo REST root unavailable ({why}); nothing collected")
            return fail(f"API probe {why}", why)
        for name, path in PRECHECKS:
            try:
                p = sh(["python3", path], timeout=600)
            except subprocess.TimeoutExpired:
                annotate("error", f"pass {n}: pre-check {name} timed out; nothing collected")
                return fail(f"pre-check {name} timeout")
            if p.returncode != 0:
                annotate("error", f"pass {n}: pre-check {name} FAILED; nothing collected", (p.stdout + p.stderr)[-3000:])
                return fail(f"pre-check {name}", p.stdout + p.stderr)
        for name, args, timeout in PIPELINE:
            try:
                p = sh(args, timeout=timeout)
            except subprocess.TimeoutExpired:
                discard_changes()
                annotate("error", f"pass {n}: {name} timed out after {timeout}s")
                return fail(f"{name} timeout")
            if p.returncode != 0:
                discard_changes()
                annotate("error", f"pass {n}: {name} FAILED (exit {p.returncode})", (p.stdout + p.stderr)[-3000:])
                return fail(f"{name} (exit {p.returncode})", p.stdout + p.stderr)
        failed = []
        # F-108: a validator's own words must survive the pass. record_health() was called with no
        # tail here, so every one of the five recorded failures on 2026-11-27 (18:31Z-19:23Z) said
        # only "validators: validate_alerts" with `stderr_tail: ""` — the reason was in stdout,
        # which is served from a blob host this project cannot always reach, and dies with the run.
        tails: list[str] = []
        for name, path in VALIDATORS:
            if not (ROOT / path).exists():
                annotate("warning", f"pass {n}: validator {path} is missing; skipped")
                continue
            try:
                p = sh(["python3", path], timeout=600)
            except subprocess.TimeoutExpired:
                failed.append(name)
                tails.append(f"[{name}] timed out after 600s")
                continue
            if p.returncode != 0:
                failed.append(name)
                annotate("error", f"pass {n}: {name} FAILED", (p.stdout + p.stderr)[-3000:])
                tails.append(f"[{name}] exit {p.returncode}\n{p.stdout}\n{p.stderr}")
        if failed:
            discard_changes()
            return fail("validators: " + ", ".join(failed), "\n".join(tails))
        if not plan.commit:
            discard_changes()
            return "validated", f"dry run on {head}; nothing committed"
        # F-98: the health file must describe the MOST RECENT pass, so a pass that commits
        # also records that it committed. commit_and_push() stages data/live, so this lands in
        # the same commit as the snapshot.
        write_health_ok(n, plan.ref)
        return commit_and_push(plan.ref)
    return do_pass


def gh_active_runs(workflow: str, ref: str) -> int:
    me = os.environ.get("GITHUB_RUN_ID", "")
    p = sh(["gh", "run", "list", "--workflow", workflow, "--branch", ref, "--limit", "20",
            "--json", "databaseId,status"], timeout=60)
    if p.returncode != 0:
        # Unknown is treated as busy: when in doubt, do not dispatch.
        annotate("warning", f"could not list {workflow} runs; treating as busy", p.stderr)
        return 1
    runs = json.loads(p.stdout or "[]")
    return sum(1 for r in runs if r.get("status") in ACTIVE_STATUSES and str(r.get("databaseId")) != me)


def gh_dispatch(workflow: str, ref: str) -> bool:
    p = sh(["gh", "workflow", "run", workflow, "--ref", ref], timeout=60)
    if p.returncode != 0:
        annotate("warning", f"dispatch of {workflow} failed", p.stderr)
        return False
    print(f"  dispatched {workflow} on {ref}")
    return True


def roi_age_min() -> float | None:
    try:
        d = json.loads((ROOT / "data" / "live" / "roi.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return age_minutes(d.get("collected_at"), time.time())


def write_summary(plan: Plan, res: RelayResult):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    rows = [f"| {i} | {datetime.fromtimestamp(t, timezone.utc).strftime('%H:%M:%SZ')} | {o} | {d} |"
            for i, (t, o, d) in enumerate(res.passes, 1)]
    text = "\n".join([
        f"### Collector relay on `{plan.ref}`",
        f"relay {plan.relay_minutes} min · every {plan.interval_minutes} min · commit {plan.commit} · "
        f"successor allowed {plan.successor_allowed} · COLLECT_RELAY off {plan.killed}",
        "", "| pass | started | outcome | detail |", "|---|---|---|---|", *rows, "",
        f"pages.yml dispatches: {len(res.publishes)} · desk.yml dispatches: {len(res.desk_dispatches)} · "
        f"successor: {res.successor[1]}",
    ])
    print(text)
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    counts: dict[str, int] = {}
    for _, o, _ in res.passes:
        counts[o] = counts.get(o, 0) + 1
    annotate("notice",
             f"relay on {plan.ref}: {len(res.passes)} pass(es) — "
             + ", ".join(f"{v} {k}" for k, v in counts.items()),
             "\n".join([
                 "; ".join(f"{i} {datetime.fromtimestamp(t, timezone.utc).strftime('%H:%M:%SZ')} {o}"
                           + (f" ({d})" if d and o != "validated" else "")
                           for i, (t, o, d) in enumerate(res.passes, 1)),
                 f"plan: relay {plan.relay_minutes} min, every {plan.interval_minutes} min, commit {plan.commit}",
                 f"pages.yml dispatches: {len(res.publishes)} · desk.yml dispatches: {len(res.desk_dispatches)}",
                 f"successor: {res.successor[1]}",
             ]))


def main() -> int:
    ref = os.environ.get("GITHUB_REF_NAME") or sh(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    plan = make_plan(ref, os.environ.get("RELAY_MINUTES"), os.environ.get("INTERVAL_MINUTES"),
                     os.environ.get("COMMIT"), os.environ.get("COLLECT_RELAY"),
                     os.environ.get("DEFAULT_BRANCH") or "main")
    print(f"plan: {plan}")
    sh(["git", "config", "user.name", "kalshi-collector-bot"], check=True)
    sh(["git", "config", "user.email", "kalshi-collector-bot@users.noreply.github.com"], check=True)
    res = run_relay(
        plan,
        clock=time.time,
        sleep=time.sleep,
        do_pass=make_pass(plan),
        active_runs=lambda wf: gh_active_runs(wf, plan.ref),
        dispatch=lambda wf: gh_dispatch(wf, plan.ref),
        roi_age_min=roi_age_min,
    )
    write_summary(plan, res)
    return 0 if any(o in OK_OUTCOMES for _, o, _ in res.passes) else 1


if __name__ == "__main__":
    sys.exit(main())
