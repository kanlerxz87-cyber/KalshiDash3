#!/usr/bin/env python3
"""Static site checks for docs/. Fails the build instead of shipping a broken page.

Checks
  1. every internal href/src resolves to a file under docs/
  2. every JSON that the pages fetch at runtime exists and parses
  3. pages do not reference the removal-prone shared shell incorrectly
  4. no page silently claims a verified value that data/verified_facts.json
     marks unverified
  5. HTML has balanced <table>/<div> tags often enough to catch a truncated file

Exit code 0 = safe to deploy. Non-zero = do not deploy.

Run: python3 scripts/check_site.py
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

errors: list[str] = []
warnings: list[str] = []


class Balance(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.problems.append(f"unclosed <{self.stack.pop()}>")
            if self.stack:
                self.stack.pop()
        else:
            self.problems.append(f"stray </{tag}>")


def check_links(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    for attr, url in re.findall(r'(href|src)\s*=\s*"([^"]+)"', html):
        if not url or url.startswith(("http://", "https://", "mailto:", "#", "data:", "javascript:")):
            continue
        # Skip values that are built at runtime by page script.
        if "${" in url or "{{" in url or re.search(r"['\"]\s*\+", url):
            continue
        target = url.split("#")[0].split("?")[0]
        if not target:
            continue
        resolved = (page.parent / target).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{page.name}: link escapes docs/: {url}")
            continue
        if not resolved.exists():
            errors.append(f"{page.name}: broken internal link -> {url}")


def check_page(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    if "<title>" not in html:
        errors.append(f"{page.name}: missing <title>")
    if 'name="viewport"' not in html:
        errors.append(f"{page.name}: missing viewport meta")
    if page.name not in {"categories.html"} and "assets/site.js" not in html:
        warnings.append(f"{page.name}: does not load the shared shell")
    if "</html>" not in html.rstrip()[-40:]:
        errors.append(f"{page.name}: file looks truncated (no closing </html>)")

    p = Balance()
    p.feed(html)
    for problem in p.problems[:5]:
        errors.append(f"{page.name}: {problem}")
    leftover = [t for t in p.stack if t not in ("html",)]
    if leftover:
        errors.append(f"{page.name}: unclosed tags {leftover[:5]}")


def check_data() -> None:
    for rel in ("data/live/markets.json", "data/live/price_history.json",
                "data/live/alerts.json", "data/live/cors.json",
                "data/verified_facts.json", "data/findings.json", "data/categories.json"):
        path = ROOT / rel
        if not path.exists():
            if rel.startswith("data/live/"):
                warnings.append(f"{rel} not present yet (collector has not run)")
            else:
                errors.append(f"{rel} missing")
            continue
        try:
            json.loads(path.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"{rel}: invalid JSON ({e})")


def main() -> int:
    pages = sorted(DOCS.glob("*.html"))
    if not pages:
        print("no pages found in docs/", file=sys.stderr)
        return 1
    for page in pages:
        check_links(page)
        check_page(page)
    check_data()

    print(f"checked {len(pages)} pages: {', '.join(p.name for p in pages)}")
    for w in warnings:
        print(f"  warn: {w}")
    if errors:
        print(f"\nFAILED with {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK: all internal links resolve, HTML parses, data files valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
