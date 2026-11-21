#!/usr/bin/env python3
"""Decide whether a stale snapshot justifies dispatching one collection. No network.

Why this is a separate, tested file
-----------------------------------
`collect.yml` already carries a bounded freshness step, but it only runs *inside a
collection*: if GitHub's scheduler drops the collect runs, nothing executes the watchdog and
nothing revives the data. Measured on `gh run list --workflow=collect.yml` (2026-11-21):

    scheduled collect runs: 2026-11-20T19:19Z (failed), 2026-11-21T00:49Z, 06:0xZ,
                            15:15:48Z, 15:20:32Z  -> then nothing until a manual dispatch at
                            20:26Z, i.e. ~5h with a 20-minute cron.

GitHub documents that scheduled workflows may be delayed and that "some queued jobs may be
dropped" (https://docs.github.com/en/actions/reference/workflows-and-events/events-that-trigger-workflows),
so the throttling is expected behaviour, not a bug in the cron expression. The fix is to let
*any* scheduled workflow revive the collector, with hard limits so it cannot become the
runaway dispatch loop that was shipped and reverted once already (F-63: five runs in five
minutes, 06:34-06:39Z).

The decision is a pure function so every guard can be tested offline, including the exact
case that misfired before:

    python3 scripts/watchdog.py --help

Exit code 0 always (a skip is not an error); the decision is printed as
`dispatch` or `skip: <reason>` and is also available as JSON with --json.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone


def parse_ts(value: str) -> datetime | None:
    """Parse the snapshot's `collected_at` (ends in Z) or return None."""
    if not value:
        return None
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        d = datetime.fromisoformat(v)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def decide(collected_at: str, now: datetime, in_flight: int, dispatches_last_hour: int,
           stale_min: int = 35, max_per_hour: int = 3) -> dict:
    """Return {'dispatch': bool, 'reason': str, ...measured facts}.

    Order matters and is chosen so that the cheapest, most conservative reason wins:
      1. no timestamp           -> skip (nothing to reason about)
      2. a collection in flight -> skip (never overlap, whatever the age)
      3. hourly cap reached     -> skip (hard limit; this is what F-63 lacked in practice)
      4. snapshot fresh         -> skip (the common case; must not spin)
      5. otherwise              -> dispatch exactly once
    A dispatched run collects fresh data, so the snapshot it leaves behind is fresh and the
    very next invocation takes branch 4. That is what makes the chain self-limiting at one.
    """
    got = parse_ts(collected_at)
    facts = {"collected_at": collected_at, "in_flight": in_flight,
             "dispatches_last_hour": dispatches_last_hour,
             "stale_min": stale_min, "max_per_hour": max_per_hour}
    if got is None:
        return {"dispatch": False, "reason": "no snapshot timestamp to reason about", **facts}
    age_min = (now - got).total_seconds() / 60.0
    facts["age_min"] = round(age_min, 1)
    if in_flight > 0:
        return {"dispatch": False, "reason": f"{in_flight} collection(s) already in flight", **facts}
    if dispatches_last_hour >= max_per_hour:
        return {"dispatch": False, "reason": f"hourly dispatch cap reached ({dispatches_last_hour}/{max_per_hour})", **facts}
    if age_min < stale_min:
        return {"dispatch": False, "reason": f"snapshot is fresh ({age_min:.0f}m < {stale_min}m)", **facts}
    return {"dispatch": True, "reason": f"snapshot is stale ({age_min:.0f}m >= {stale_min}m)", **facts}


def main() -> int:
    ap = argparse.ArgumentParser(description="Bounded freshness decision (no network).")
    ap.add_argument("--collected-at", default="", help="snapshot collected_at, e.g. 2026-11-21T20:21:50Z")
    ap.add_argument("--now", default="", help="ISO timestamp to evaluate against (default: now, UTC)")
    ap.add_argument("--in-flight", type=int, default=0)
    ap.add_argument("--dispatches-last-hour", type=int, default=0)
    ap.add_argument("--stale-min", type=int, default=35)
    ap.add_argument("--max-per-hour", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    now = parse_ts(a.now) or datetime.now(timezone.utc)
    out = decide(a.collected_at, now, a.in_flight, a.dispatches_last_hour,
                 a.stale_min, a.max_per_hour)
    print(json.dumps(out, indent=1) if a.json else ("dispatch" if out["dispatch"] else f"skip: {out['reason']}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
