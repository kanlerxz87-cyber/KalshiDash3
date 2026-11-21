#!/usr/bin/env python3
"""Offline release gate. Requires Python 3.11+, Node 20+, and jsdom 26.

Does not collect data, execute orders, or rewrite published snapshots. A passing
suite checks the committed evidence and fixture behavior, not live API uptime,
external link availability, causal news attribution, or profitable strategies.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


class InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attrs = dict(attrs)
            self.active = not attrs.get("src") and attrs.get("type", "").lower() in (
                "", "text/javascript", "application/javascript", "module"
            )
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            if self.active:
                self.scripts.append("".join(self.parts))
            self.active = False


def run(*args: str) -> bool:
    print("\n+ " + " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, check=False).returncode == 0


def main() -> int:
    if not shutil.which("node"):
        print("ERROR: Node is required; browser checks must not silently skip.", file=sys.stderr)
        return 1
    # The existing DOM test intentionally skips without jsdom. A release must not.
    if not run("node", "-e", "require('jsdom')"):
        print("ERROR: install test dependency: npm install --no-save --package-lock=false jsdom@26", file=sys.stderr)
        return 1

    failed: list[str] = []
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        try:
            compile(path.read_bytes(), str(path), "exec")
        except (SyntaxError, ValueError) as error:
            print(error, file=sys.stderr)
            failed.append(str(path.relative_to(ROOT)))

    for path in sorted((ROOT / "assets").glob("*.js")):
        if not run("node", "--check", str(path.relative_to(ROOT))):
            failed.append(str(path.relative_to(ROOT)))

    with tempfile.TemporaryDirectory(prefix="kalshi-release-") as directory:
        for page in sorted(ROOT.glob("*.html")):
            parser = InlineScripts()
            parser.feed(page.read_text())
            for index, source in enumerate(parser.scripts):
                path = Path(directory) / f"{page.stem}-{index}.mjs"
                path.write_text(source)
                if not run("node", "--check", str(path)):
                    failed.append(f"{page.name} inline script {index}")

    tests = ROOT / "scripts" / "tests"
    for path in sorted(tests.glob("validate_*.py")) + sorted(tests.glob("test_*.py")):
        if not run(sys.executable, str(path.relative_to(ROOT))):
            failed.append(path.name)
    for name in ("engine.test.js", "test_engine_node.js", "test_pages_dom.js"):
        if not run("node", f"scripts/tests/{name}"):
            failed.append(name)
    if not run(sys.executable, "scripts/check_site.py"):
        failed.append("check_site.py")

    if failed:
        print("\nRELEASE REFUSED: " + ", ".join(failed), file=sys.stderr)
        return 1
    print("\nPASS: offline release checks. Live API, account access and external URLs not certified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
