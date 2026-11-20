#!/usr/bin/env python3
"""Check that every internal href/src in docs/verified/*.html resolves to a file in the repo.
External links are listed (not fetched) so they can be reviewed manually.
Usage: python3 scripts/check_links.py  (exit 1 if any internal link is broken)"""
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(ROOT, "docs", "verified")


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.refs.append(v)


bad, external, ok = [], set(), 0
for dp, _, files in os.walk(SCAN):
    for f in files:
        if not f.endswith(".html"):
            continue
        path = os.path.join(dp, f)
        p = P()
        p.feed(open(path, encoding="utf-8").read())
        for ref in p.refs:
            if ref.startswith("#") or re.match(r"^(mailto:|javascript:)", ref):
                continue
            if ref.startswith("http"):
                external.add(ref)
                continue
            target = os.path.normpath(os.path.join(dp, ref.split("#")[0].split("?")[0]))
            if os.path.exists(target):
                ok += 1
            else:
                bad.append((os.path.relpath(path, ROOT), ref))
print("internal refs ok:", ok)
print("broken internal refs:", len(bad))
for b in bad:
    print("  BROKEN", b)
print("distinct external links (review manually):", len(external))
sys.exit(1 if bad else 0)
