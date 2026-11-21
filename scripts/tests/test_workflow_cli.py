#!/usr/bin/env python3
"""Guard: no workflow may call `gh` with a flag `gh` does not define.

Why this test exists (F-74 / R-B7, fixed by T58 in this branch)
---------------------------------------------------------------
`.github/workflows/freshness-alarm.yml` used to dispatch the collector with

    gh workflow run collect.yml --ref main --event workflow_dispatch

`gh workflow run` has no `--event` flag. Its whole flag set is `--ref/-r`,
`--field/-F`, `--raw-field/-f` and `--json`, taken from the CLI source
(https://github.com/cli/cli/blob/trunk/pkg/cmd/workflow/run/run.go) and from
`gh workflow run --help`. The command therefore exits non-zero every time, the
step's `|| echo "::warning::dispatch failed…"` swallows it, and the workflow
silently never restarts collection.

A documentation claim can rot; a test cannot. This one parses every workflow
file, extracts each `gh <subcommand> …` invocation (continuing over `\` line
joins), and rejects any flag outside the documented set for the subcommands
this repository uses. It is offline and needs no token.

Run: python3 scripts/tests/test_workflow_cli.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# Documented flag sets. Sources:
#   gh workflow run  -> https://cli.github.com/manual/gh_workflow_run
#   gh run list      -> https://cli.github.com/manual/gh_run_list
#   gh run cancel    -> https://cli.github.com/manual/gh_run_cancel
#   gh api           -> https://cli.github.com/manual/gh_api
#   gh pr create     -> https://cli.github.com/manual/gh_pr_create
FLAGS = {
    "workflow run": {"-r", "--ref", "-f", "--field", "-F", "--raw-field", "--json"},
    "run list": {"-w", "--workflow", "-b", "--branch", "-L", "--limit", "--json", "-q", "--jq",
                 "--event", "--status", "-c", "--created", "--commit"},
    "run cancel": {"-R", "--repo"},
    "run view": {"--json", "-q", "--jq", "--log"},
    "api": {"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header",
            "--input", "--paginate", "--slurp", "--jq", "-q", "--template", "-t",
            "--cache", "--silent", "-i", "--include", "--verbose"},
    "pr create": {"-t", "--title", "-b", "--body", "-B", "--base", "-H", "--head",
                  "-d", "--draft", "-f", "--fill", "--fill-first", "--fill-verbose",
                  "-r", "--reviewer", "-a", "--assignee", "-l", "--label", "-m", "--milestone",
                  "-p", "--project", "--recover", "--no-maintainer-edit"},
}

failures: list[str] = []
checks = 0


def check(ok: bool, label: str) -> None:
    global checks
    checks += 1
    if ok:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        failures.append(label)


GH_COMMANDS = {"workflow", "run", "api", "pr", "issue", "repo", "auth", "release",
               "secret", "variable", "cache", "label", "gist", "search", "status"}


def strip_quotes(line: str) -> str:
    """Replace quoted spans with a placeholder so values are never read as flags."""
    out, quote, escaped = [], "", False
    for ch in line:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                out.append('""')
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            continue
        out.append(ch)
    return "".join(out)


def invocations(text: str):
    """Yield (line number, subcommand, tokens) for each `gh …` command.

    `\\`-terminated lines are joined first so a flag on a continuation line is
    still attributed to its command. Quoted values are masked, and a `gh` that is
    not in command position (prose inside an `echo`) is not a command.
    """
    logical: list[tuple[int, str]] = []
    buffer, start = "", 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            line = ""            # YAML comment: prose, never a command
        if not buffer:
            start = number
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        buffer += line
        logical.append((start, buffer))
        buffer = ""
    if buffer:
        logical.append((start, buffer))

    for number, line in logical:
        masked = strip_quotes(line)
        # `gh` must sit at a command position: start, $(), |, ;, &&, ||, sudo
        for match in re.finditer(r"(?:^|[|;(]|&&|\|\||\bsudo\s)\s*gh\s+([a-z-]+)(?:\s+([a-z-]+))?", masked):
            first, second = match.group(1), match.group(2)
            if first not in GH_COMMANDS:
                continue                      # prose, not a gh invocation
            sub = first if second in (None, "") or f"{first} {second}" not in FLAGS else f"{first} {second}"
            rest = masked[match.end():]
            tokens = [t for t in re.split(r"\s+", rest.strip()) if t]
            if sub != f"{first} {second}":
                tokens = [second] + tokens if second else tokens
            yield number, sub, tokens


def main() -> int:
    print(f"workflow files: {len(WORKFLOWS)}")
    check(bool(WORKFLOWS), "at least one workflow file exists")
    if not WORKFLOWS:
        print("\nFAILED: no workflows to check")
        return 1

    unknown_subs: set[str] = set()
    offending: list[str] = []
    seen_commands = 0

    for path in WORKFLOWS:
        text = path.read_text()
        for number, sub, tokens in invocations(text):
            # The known two-word subcommands; anything else means this test's
            # knowledge is stale, which is a failure, not a silent pass.
            if sub not in FLAGS:
                two = f"{sub.split()[0]} {tokens[0]}" if tokens else sub
                if two in FLAGS:
                    sub, tokens = two, tokens[1:]
                else:
                    unknown_subs.add(f"{path.name}:{number} gh {sub}")
                    continue
            seen_commands += 1
            allowed = FLAGS[sub]
            for token in tokens:
                if token.startswith("#"):
                    break
                if not token.startswith("-"):
                    continue
                flag = token.split("=", 1)[0]
                # `-q=...` style is not used here; treat attached short values as their stem
                if flag not in allowed and len(flag) == 2 and flag in allowed:
                    continue
                if flag not in allowed:
                    offending.append(f"{path.name}:{number} `gh {sub}` uses `{flag}` "
                                     f"(allowed: {', '.join(sorted(allowed))})")

    check(seen_commands > 0, f"found {seen_commands} gh invocations to audit")
    check(not unknown_subs,
          "every gh subcommand is one this test knows the flags of"
          + ("" if not unknown_subs else f" — unknown: {sorted(unknown_subs)}"))
    check(not offending,
          "no gh invocation uses an undefined flag"
          + ("" if not offending else ":\n       " + "\n       ".join(offending)))

    # The exact historical defect, pinned so the fix cannot regress.
    alarm = ROOT / ".github" / "workflows" / "freshness-alarm.yml"
    if alarm.exists():
        body = alarm.read_text()
        # Only command lines count: the fix explains itself in a YAML comment that
        # necessarily names the retired flag, and a comment cannot be executed.
        commands = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
        check("--event" not in commands,
              "freshness-alarm.yml no longer passes the non-existent `--event` flag (F-74)")
        check("gh workflow run collect.yml" in body,
              "freshness-alarm.yml still dispatches the collector (the fix kept its purpose)")
        # A dispatch that can fail silently is the reason F-74 went unnoticed for hours.
        check("dispatch failed" in body,
              "a failed dispatch is still surfaced as a workflow warning")

    print("")
    if failures:
        print(f"FAILED: {len(failures)} of {checks} checks")
        return 1
    print(f"OK: {checks} checks — every `gh` call in .github/workflows uses documented flags.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
