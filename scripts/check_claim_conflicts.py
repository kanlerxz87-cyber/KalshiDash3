#!/usr/bin/env python3
"""Parse COORDINATION.md into a machine-readable claim ledger and report overlapping scopes.

Why this exists
  On 2026-11-27 the collector had been down since 18:29Z. Between 19:35Z and 19:39Z four
  independent sessions (arena-a8d317a1, arena-c4409c73, arena-417935f1, arena-72ae7bca) each
  wrote a claim to this board for the *same* repair, each naming overlapping files
  (scripts/build_alerts.py, scripts/tests/validate_alerts.py, scripts/roi_scan.py, ...). The
  board rule ("never start a task another session has claimed") could not be enforced by a
  human reading a 3,000-line Markdown file fast enough, so the collision was discovered as a
  merge conflict after the work was done. This script turns the board's own claim tables into
  data: which session claims which file, with what status, on what board line.

What it does (and deliberately does not do)
  * Reads COORDINATION.md only. It is the single source of truth, so the ledger cannot drift
    from the board.
  * A *claim row* is a table row inside a `## Session ...` section whose first cell is a task
    id (E9D9-1, C440-2, T120, ...). The status, owner and scope cells are then parsed; the
    scope is the set of backticked paths in the "Files in scope" cell.
  * A claim is *live* when its status normalises to in-progress/unclaimed/claimed (i.e. the
    work is not recorded as done). `done`, `needs review`, `merged`, `blocked` are not live.
  * A *conflict* is one path claimed live by two or more different session ids.
  * Only the FIRST section per session is treated as that session's current statement: every
    session inserts its section at the top of the file, so a later section for the same session
    is a historical close-out.
  * It never guesses staleness. The board does not record commit times, so a claim from a
    session that stopped working yesterday looks exactly like one from a minute ago; the report
    says so instead of inventing an expiry.

Modes
  default    report + write data/session_claims.json, always exit 0. This is what the release
             gate runs: a conflicting board is a coordination problem to publish, not a reason
             to refuse to deploy a site whose own checks pass.
  --strict   exit 1 when any live overlap exists. Run this *before* editing files.

Run: python3 scripts/check_claim_conflicts.py [--strict] [--out PATH] [--board PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "COORDINATION.md"
OUT = ROOT / "data" / "session_claims.json"

# A task id: C440-2, E9D9-1, T120, R93-1, B228-1, F250-1, 91A-1, SIM-660E-01, SAFE-5C-01 …
TASK_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$|^[A-Z][A-Z0-9]*\d+[A-Z]?-\d+$")
SESSION_HEAD = re.compile(r"^##\s+Session\s+`([^`]+)`")
# Paths in a scope cell. Kept strict so prose backticks (field names, commands) never become
# "files": a claim only covers things that look like repository paths.
PATH_TOKEN = re.compile(r"`([A-Za-z0-9_.@/-]+\.(?:py|js|json|html|css|yml|yaml|md|pdf))`")
# A scope cell routinely states what a claim does NOT cover ("... — not `flagged.html`", "avoids
# `data/findings.json`", "no writes to `data/live/*`"). Those paths must not be counted as claims,
# or the ledger reports a collision that the board does not actually contain.
NEGATION = re.compile(r"\b(?:not|never|avoid|avoids|excluding|excludes?|minus|do not touch|"
                      r"no (?:direct )?writes? to|outside|instead of)\b[^;|]*$", re.I)
DIR_TOKEN = re.compile(r"`((?:scripts|assets|data|\.github)/[A-Za-z0-9_./*-]+)/?`")

LIVE_STATUS_HINTS = ("in progress", "in-progress", "in_progress", "unclaimed", "claimed",
                     "in progress (", "started", "active")
DEAD_STATUS_HINTS = ("done", "complete", "merged", "closed", "needs review", "blocked",
                     "superseded", "published", "handed over")


def cells(row: str) -> list[str]:
    """Split a Markdown table row into stripped cells (no escaped-pipe handling needed here)."""
    return [c.strip() for c in row.strip().strip("|").split("|")]


def session_of(head: str) -> str:
    """`arena-a8d317a1` and bare `c4409c73` are both session ids; normalise the prefix away."""
    s = head.strip()
    return s[len("arena-"):] if s.startswith("arena-") else s


def status_is_live(status: str) -> bool:
    s = " ".join(status.lower().split())
    if not s:
        return True  # a row with no status is not recorded as done
    if any(h in s for h in LIVE_STATUS_HINTS):
        return True
    return not any(d in s for d in DEAD_STATUS_HINTS)


def parse(board_text: str) -> dict:
    sessions: dict[str, dict] = {}   # session -> first (current) section
    order: list[str] = []
    current: str | None = None
    current_seen: set[str] = set()
    line_no = 0

    for raw in board_text.splitlines():
        line_no += 1
        m = SESSION_HEAD.match(raw)
        if m:
            sid = session_of(m.group(1))
            # Only the topmost section per session is that session's current statement.
            current = None if sid in current_seen else sid
            if current:
                current_seen.add(sid)
                order.append(sid)
                sessions[current] = {"session": current, "heading_line": line_no,
                                     "heading": raw[3:].strip(), "claims": {}}
            continue
        if current is None or not raw.lstrip().startswith("|"):
            continue
        row = cells(raw)
        if len(row) < 5:
            continue
        task = row[0].strip("`* ")
        if not TASK_ID.match(task):
            continue
        status, owner, scope = row[2], row[3], row[4]
        files: list[str] = []
        for m in PATH_TOKEN.finditer(scope):
            # Negation is scoped to the clause the path sits in: the text since the previous ';'
            # or '.' separator. "not `flagged.html`" is a disclaimer; "- `flagged.html`" is a claim.
            clause_start = max(scope.rfind(";", 0, m.start()), scope.rfind(". ", 0, m.start())) + 1
            if NEGATION.search(scope[clause_start:m.start()]):
                continue
            files.append(m.group(1))                 # exact path
        for m in DIR_TOKEN.finditer(scope):
            tok = m.group(1)
            clause_start = max(scope.rfind(";", 0, m.start()), scope.rfind(". ", 0, m.start())) + 1
            if NEGATION.search(scope[clause_start:m.start()]):
                continue
            if PATH_TOKEN.search("`" + tok + "`") is None:   # not already an exact-path claim
                # Keep a glob as written ("data/live/*"); normalise a bare directory to "dir/".
                files.append(tok if "*" in tok else (tok.rstrip("/") + "/" if "/" in tok else tok))
        files = sorted(set(files))
        sessions[current]["claims"][task] = {
            "task": task,
            "status": status,
            "status_normalised": " ".join(status.lower().split()),
            "live": status_is_live(status),
            "owner": owner,
            "files": files,
            "line": line_no,
        }
    return {"sessions": [sessions[s] for s in order]}


def build(board_text: str) -> dict:
    return _summarise(parse(board_text)["sessions"])


def _summarise(sessions: list[dict]) -> dict:
    parsed = {"sessions": sessions}
    owners: dict[str, list[dict]] = {}
    live_claims: list[dict] = []
    for section in parsed["sessions"]:
        for claim in section["claims"].values():
            entry = {"session": section["session"], "task": claim["task"],
                     "status": claim["status"], "line": claim["line"]}
            if claim["live"]:
                live_claims.append(entry)
                for path in claim["files"]:
                    owners.setdefault(path, []).append(entry)

    overlaps = []
    for path, entries in sorted(owners.items()):
        sessions_here = sorted({e["session"] for e in entries})
        if len(sessions_here) > 1:
            overlaps.append({
                "path": path,
                "sessions": sessions_here,
                "claims": [{"session": e["session"], "task": e["task"],
                            "status": e["status"], "line": e["line"]} for e in entries],
            })

    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "COORDINATION.md",
        "note": ("Claim ledger parsed from the shared board. A claim is live when its status is not "
                 "recorded as done. A conflict is one path claimed live by two or more sessions. The "
                 "board records no commit times, so this report does NOT decide staleness: a claim "
                 "from a session that stopped hours ago looks the same as one from a minute ago. "
                 "Cross-check a session's branch before taking a claim over."),
        "sessions": [{"session": s["session"], "heading": s["heading"],
                      "heading_line": s["heading_line"],
                      "claims": list(s["claims"].values())} for s in parsed["sessions"]],
        "counts": {
            "sessions": len(parsed["sessions"]),
            "claims": sum(len(s["claims"]) for s in parsed["sessions"]),
            "live_claims": len(live_claims),
            "paths_claimed_live": len(owners),
            "conflicting_paths": len(overlaps),
            "conflicting_sessions": len({e["session"] for o in overlaps for e in o["claims"]}),
        },
        "conflicts": overlaps,
    }


def build_many(board_texts: list[str]) -> dict:
    """Union several board copies (one per session branch) into one ledger.

    Each session inserts its section at the TOP of its own branch's COORDINATION.md, so a claim
    that exists only on an unmerged branch is invisible in this tree. Reading every open session
    branch's copy is what makes a pending collision visible before the work collides instead of
    after. A session id seen in more than one copy is the same session (its topmost section is
    used, exactly as in a single-board parse), so duplicates collapse rather than double-count.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    for text in board_texts:
        one = parse(text)
        for section in one["sessions"]:
            sid = section["session"]
            if sid not in merged:
                merged[sid] = section
                order.append(sid)
            else:  # union of task rows; a later copy may carry a newer status for the same task
                for task, claim in section["claims"].items():
                    prev = merged[sid]["claims"].get(task)
                    if prev is None or claim["live"] == prev["live"]:
                        merged[sid]["claims"].setdefault(task, claim)
    return _summarise([merged[s] for s in order])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a path is claimed live by more than one session")
    ap.add_argument("--out", default=str(OUT), help="where to write the ledger JSON")
    ap.add_argument("--board", action="append", default=None, metavar="PATH",
                    help=("board file to read, repeatable. Point this at other sessions' branch "
                          "copies (git show origin/<branch>:COORDINATION.md > /tmp/b.md) to union "
                          "their claims with this tree's before you start work. Default: this "
                          "tree's COORDINATION.md"))
    args = ap.parse_args(argv)

    boards = [Path(b) for b in (args.board or [str(BOARD)])]
    missing = [str(b) for b in boards if not b.exists()]
    if missing:
        print("ERROR: missing board file(s): " + ", ".join(missing), file=sys.stderr)
        return 1
    doc = build_many([b.read_text(encoding="utf-8") for b in boards])
    doc["source"] = ", ".join(str(b) for b in boards)
    out = Path(args.out)
    if out.parent.exists() or out.parent == Path("."):
        out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    c = doc["counts"]
    print(f"claims: {c['claims']} rows across {c['sessions']} current session sections "
          f"({c['live_claims']} live) · {c['paths_claimed_live']} paths claimed live")
    if doc["conflicts"]:
        print(f"OVERLAP: {c['conflicting_paths']} path(s) claimed live by more than one session "
              f"({c['conflicting_sessions']} sessions involved)")
        for o in doc["conflicts"]:
            who = ", ".join(f"{x['session']}/{x['task']}" for x in o["claims"])
            print(f"  - {o['path']}: {who}")
        if args.strict:
            print("\nSTRICT: overlapping live claims — do not start editing these paths until the "
                  "board names one owner.", file=sys.stderr)
            return 1
        print("reported, not fatal: this is a coordination signal (pass --strict to enforce)")
    else:
        print("OK: no path is claimed live by more than one session")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
