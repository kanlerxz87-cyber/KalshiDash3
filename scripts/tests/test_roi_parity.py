#!/usr/bin/env python3
"""Browser/CI parity check for the ROI model.

The page scores live ticks in JavaScript (assets/live.js); the scheduled collector scores
the same markets in Python (scripts/roi_model.py) to produce data/live/roi.json. If those
two implementations ever disagree, the "high ROI" chat a trader watches and the picks the
site publishes are different models wearing the same name — so this test fails the build.

Both sides are run over ONE fixture (scripts/tests/fixtures_roi_parity.json), which covers:
a qualifying pick, a wide spread, a thin book, a missing book (size fields instead), a
zero-fee series, a keyword-only topic, a market past its close, a market with no close
time, an extreme price, low volume, a downward tilt, a catalyst URL inside the market's
own rules text, a one-sided quote, a market with no price at all, a market with no depth
information (the depth gate is skipped, not zeroed), and the two pinned-quote cases the
demo book actually produces (YES ask $0.00 observed verbatim in the committed snapshot;
YES bid $1.00 as its labelled mirror) where ROI is undefined and must stay unpriced.

Beyond parity this test also audits both outputs: no priced side may have a zero/negative
cost or a non-finite ROI. That matters because JSON turns JavaScript's `Infinity` into
`null`, so a browser-side regression could otherwise slip through a pure equality check.

Run: python3 scripts/tests/test_roi_parity.py
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FIX = ROOT / "scripts" / "tests" / "fixtures_roi_parity.json"
sys.path.insert(0, str(ROOT / "scripts"))
import roi_model as RM  # noqa: E402

NUM_KEYS = ["q", "mid", "micro", "last", "bid", "ask", "spread", "depth", "vol24",
            "ttc_hours", "momentum", "score", "dollars_traded_estimate"]
ENTRY_KEYS = ["side", "entry", "fee_unit", "cost", "ev", "roi"]
TOL = 1e-12


def close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), abs_tol=TOL, rel_tol=1e-12)


def audit(rows, label: str) -> list[str]:
    """Neither implementation may price a side whose cost is zero or whose ROI is not finite.

    A pinned demo quote (ask $0.0000 / bid $1.0000) makes ROI = (win − cost) / cost undefined:
    Python must not raise, and the browser must not rank Infinity above every real edge.
    """
    bad = []
    for r in rows or []:
        tag = f"{label} {r.get('ticker')}"
        e = r.get("entry")
        if e is None:
            if not (r.get("reasons") or r.get("fails")):
                bad.append(f"{tag}: unpriced without a stated reason")
            continue
        cost, roi = e.get("cost"), e.get("roi")
        if not isinstance(cost, (int, float)) or cost <= 0:
            bad.append(f"{tag}: priced a side at cost {cost!r} — a zero-cost side must be left unpriced")
        for k in ("roi", "ev"):
            v = e.get(k)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                bad.append(f"{tag}: {k} is {v!r}, not a finite number")
        sc = r.get("score")
        if sc is not None and (not isinstance(sc, (int, float)) or not math.isfinite(sc)):
            bad.append(f"{tag}: score is {sc!r}")
    return bad


def main() -> int:
    fixture = json.loads(FIX.read_text())
    model = RM.load_model()
    mine = []
    for c in fixture["cases"]:
        mine.append(RM.score(c["market"], model, c["book"], c["ctx"]))
    my_swings = RM.detect_swings(fixture["swings"]["observations"], fixture["swings"]["threshold"])
    my_catalysts = [RM.catalyst_links(c["market"]) for c in fixture["cases"]]
    my_fees = [[p, RM.taker_fee(1, p, 1), RM.taker_fee(100, p, 1), RM.maker_fee(100, p, 1)]
               for p in [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5,
                         0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99]]

    node = subprocess.run(
        ["node", str(ROOT / "scripts" / "tests" / "parity_node.js"), str(FIX), str(ROOT / "data" / "roi_model.json")],
        capture_output=True, text=True,
    )
    if node.returncode != 0:
        print("node harness failed:\n" + node.stderr[-2000:], file=sys.stderr)
        return 1
    theirs = json.loads(node.stdout)

    problems = []
    if len(mine) != len(theirs["scores"]):
        problems.append(f"case count {len(mine)} vs {len(theirs['scores'])}")
    for i, (a, b) in enumerate(zip(mine, theirs["scores"])):
        name = fixture["cases"][i]["name"]
        if bool(a.get("eligible")) != bool(b.get("eligible")):
            problems.append(f"{name}: eligible {a.get('eligible')} vs {b.get('eligible')}")
        fa = [f.split(" ")[0] for f in (a.get("fails") or [])]
        fb = [f.split(" ")[0] for f in (b.get("fails") or [])]
        if fa != fb:
            problems.append(f"{name}: gate sequence {fa} vs {fb}")
        if (a.get("reasons") or []) != (b.get("reasons") or []):
            problems.append(f"{name}: reasons {a.get('reasons')} vs {b.get('reasons')}")
        for k in NUM_KEYS:
            if not close(a.get(k), b.get(k)):
                problems.append(f"{name}.{k}: {a.get(k)!r} vs {b.get(k)!r}")
        ea, eb = a.get("entry") or {}, b.get("entry") or {}
        if ea.get("side") != eb.get("side"):
            problems.append(f"{name}.entry.side: {ea.get('side')} vs {eb.get('side')}")
        for k in ENTRY_KEYS[1:]:
            if not close(ea.get(k), eb.get(k)):
                problems.append(f"{name}.entry.{k}: {ea.get(k)!r} vs {eb.get(k)!r}")
        if (a.get("fee_multiplier") or {}) != (b.get("fee_multiplier") or {}):
            problems.append(f"{name}.fee_multiplier: {a.get('fee_multiplier')} vs {b.get('fee_multiplier')}")

    if len(my_swings) != len(theirs["swings"]):
        problems.append(f"swing count {len(my_swings)} vs {len(theirs['swings'])}")
    for i, (a, b) in enumerate(zip(my_swings, theirs["swings"])):
        for k in ("from", "to", "delta", "cents", "t", "previous_t"):
            av, bv = a.get(k), b.get(k)
            if isinstance(av, str) or isinstance(bv, str):
                if av != bv:
                    problems.append(f"swing[{i}].{k}: {av!r} vs {bv!r}")
            elif not close(av, bv):
                problems.append(f"swing[{i}].{k}: {av!r} vs {bv!r}")
        if a.get("direction") != b.get("direction"):
            problems.append(f"swing[{i}].direction: {a.get('direction')} vs {b.get('direction')}")

    if my_catalysts != theirs["catalysts"]:
        for i, (a, b) in enumerate(zip(my_catalysts, theirs["catalysts"])):
            if a != b:
                problems.append(f"catalyst[{i}]: {a} vs {b}")

    if my_fees != theirs["fees"]:
        for a, b in zip(my_fees, theirs["fees"]):
            if not all(close(x, y) for x, y in zip(a, b)):
                problems.append(f"fees at {a[0]}: {a} vs {b}")

    # Both engines are audited on their own, not just against each other.
    problems += audit(mine, "python")
    problems += audit(theirs["scores"], "browser")

    if problems:
        print("PARITY BROKEN — browser and CI would publish different models:", file=sys.stderr)
        for p in problems[:40]:
            print("  -", p, file=sys.stderr)
        return 1
    print(f"OK: {len(mine)} scoring cases, {len(my_swings)} swings, "
          f"{sum(len(c) for c in my_catalysts)} catalyst links and {len(my_fees)} fee points "
          "are identical between assets/live.js (browser) and scripts/roi_model.py (CI); "
          "no priced side has a zero cost or a non-finite ROI in either.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
