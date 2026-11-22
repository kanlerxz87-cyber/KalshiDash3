#!/usr/bin/env python3
"""Decide what the freshness monitor should do about a stale snapshot (F-86).

Why this exists
  `.github/workflows/freshness-alarm.yml` used to skip its rescue whenever *any*
  `collect.yml` run was in flight:

      if [ "$in_flight" -gt 0 ]; then echo "already running; not dispatching"; exit 0; fi

  That is correct while the in-flight run is producing commits, and useless when it is
  not. Measured on 2026-11-22: schedule run 44970894475 (collect.yml) started 02:46:23Z
  and held the `collect-refs/heads/main` concurrency group while the newest collector
  commit stayed f364db9 at 06:17:13Z — the published snapshot aged past two hours and
  the monitor never fired, because the wedged run counted as "in flight". A human had
  to cancel it by hand. This module turns that manual rescue into a rule.

The rule
  * snapshot younger than STALE_MIN (45 min, the threshold the site's own banner uses)
    -> nothing to do.
  * stale, and an in-flight `collect.yml` run is older than STALL_MIN (75 min = five
    missed passes on the relay's 15-minute grid) -> that run is considered wedged:
    cancel it. Whatever run is pending behind it in the concurrency group then starts
    and does a fresh pass from the current remote head. Cancelling is safe by
    construction: `scripts/collect_relay.py` re-syncs to the remote head at the start of
    every pass (`git reset --hard FETCH_HEAD`) and pushes are atomic, so a cancelled run
    cannot leave a half-written snapshot behind.
  * stale, and an in-flight run is younger than STALL_MIN -> wait. It may be a normal
    slow pass; cancelling here would fight the relay instead of helping it.
  * stale, nothing in flight, and no `workflow_dispatch` run of collect.yml created in
    the last hour -> dispatch exactly one run. The one-hour guard is what stops the
    runaway dispatch loop recorded as F-63 (a collection every 1-2 minutes on 2026-11-21).
  * stale, nothing in flight, but a dispatch already happened within the hour -> wait.

  Only one action is ever returned, and the cancel path never also dispatches: the
  pending run behind the cancelled one is already the fresh pass. This keeps the monitor
  from adding runs to a queue that is already occupied.

Nothing here talks to the network. The workflow passes the `gh run list --json` output in,
so the decision is testable offline (scripts/tests/test_freshness_guard.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STALE_MIN = 45          # the staleness threshold the site's own banner uses
STALL_MIN = 75          # five missed passes on the relay's 15-minute grid
DISPATCH_WINDOW_MIN = 60  # at most one monitor dispatch per hour (F-63)
ACTIVE_STATUSES = {"in_progress", "queued", "pending", "waiting", "requested"}


def run_age_minutes(run: dict, now_epoch: float) -> float | None:
    """Age of a run in minutes from its createdAt, or None when it cannot be parsed."""
    stamp = run.get("createdAt")
    if not stamp:
        return None
    from datetime import datetime, timezone
    try:
        when = datetime.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now_epoch - when.timestamp()) / 60.0


def classify(age_min: float, runs: list, now_epoch: float,
             stale_min: float = STALE_MIN, stall_min: float = STALL_MIN,
             dispatch_window_min: float = DISPATCH_WINDOW_MIN) -> tuple[str, str]:
    """Return (action, reason). Actions: ok | wait | cancel | dispatch.

    `runs` is the parsed `gh run list --workflow=collect.yml --json
    databaseId,status,createdAt,event` payload for the default branch.
    """
    if age_min is None:
        return "ok", "snapshot age unknown; the page states its own age, nothing to do"
    if age_min < stale_min:
        return "ok", f"snapshot is {age_min:.0f} min old (< {stale_min:.0f} min): fresh enough"

    active = []
    for run in runs or []:
        if str(run.get("status")) not in ACTIVE_STATUSES:
            continue
        age = run_age_minutes(run, now_epoch)
        active.append((age, run))

    stalled = [(age, run) for age, run in active if age is not None and age >= stall_min]
    if stalled:
        age, run = max(stalled, key=lambda pair: pair[0])
        return ("cancel",
                f"snapshot is {age_min:.0f} min old and in-flight run {run.get('databaseId')} has been "
                f"going {age:.0f} min (>= {stall_min:.0f} min) without refreshing it: cancel that run and let "
                f"the run pending behind it in the concurrency group take over")

    if active:
        youngest = min((age for age, _ in active if age is not None), default=None)
        shown = f"{youngest:.0f} min old" if youngest is not None else "age unknown"
        return "wait", (f"snapshot is {age_min:.0f} min old but a collector run is in flight ({shown}); "
                        f"a slow pass is not a wedged one, so this monitor does not cancel it")

    recent = [run for run in (runs or [])
              if str(run.get("event")) == "workflow_dispatch"
              and (run_age_minutes(run, now_epoch) is not None)
              and run_age_minutes(run, now_epoch) < dispatch_window_min]
    if recent:
        return "wait", (f"snapshot is {age_min:.0f} min old, but this monitor already dispatched a collection "
                        f"{min(run_age_minutes(r, now_epoch) for r in recent):.0f} min ago (< "
                        f"{dispatch_window_min:.0f} min); waiting for the cron instead of looping (F-63)")

    return "dispatch", f"snapshot is {age_min:.0f} min old, nothing in flight, no dispatch in the last {dispatch_window_min:.0f} min"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decide the freshness monitor's action.")
    parser.add_argument("--age-min", required=True, type=float, help="age of data/live/markets.json")
    parser.add_argument("--runs-json", required=True, help="file holding `gh run list --json databaseId,status,createdAt,event`")
    parser.add_argument("--now", type=float, default=None, help="epoch seconds (default: now)")
    parser.add_argument("--env-file", default=None, help="append ACTION / RUN_ID / WHY to this file (e.g. $GITHUB_ENV)")
    args = parser.parse_args(argv)

    import time
    now = args.now if args.now is not None else time.time()
    runs = json.loads(Path(args.runs_json).read_text() or "[]")
    action, reason = classify(args.age_min, runs, now)

    run_id = ""
    if action == "cancel":
        # The wedged run is the OLDEST active one: a healthy relay keeps committing, so a run
        # that has been going for hours while the snapshot ages is the one holding the group.
        candidates = [(run_age_minutes(run, now), run) for run in runs
                      if str(run.get("status")) in ACTIVE_STATUSES and run.get("databaseId")]
        candidates = [(age, run) for age, run in candidates if age is not None]
        if candidates:
            run_id = str(max(candidates, key=lambda pair: pair[0])[1].get("databaseId"))

    print(f"action={action}: {reason}")
    if args.env_file:
        with open(args.env_file, "a", encoding="utf-8") as fh:
            fh.write(f"GUARD_ACTION={action}\nGUARD_RUN_ID={run_id}\nGUARD_WHY={reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
