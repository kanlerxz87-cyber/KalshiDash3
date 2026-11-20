#!/usr/bin/env python3
"""Fee-model check against the official fee schedule table.

Every expectation below is a row copied from the "General Trading Fees Table" in
https://kalshi.com/docs/kalshi-fee-schedule.pdf (last updated and effective July 7, 2026),
which lists, for each price, the fee for 1 contract and the fee for 100 contracts.
If the implementation stops reproducing the published table, this test fails — that is the
point: the ROI screen's edge is measured in tenths of a cent, so a wrong fee is a wrong pick.

Run: python3 scripts/tests/test_fees.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import roi_model as RM  # noqa: E402

# (price of 1 contract, fee for 1 contract, price for 100 contracts, fee for 100 contracts)
PDF_GENERAL_TABLE = [
    (0.01, 0.01, 1.00, 0.07),
    (0.05, 0.01, 5.00, 0.34),
    (0.10, 0.01, 10.00, 0.63),
    (0.15, 0.01, 15.00, 0.90),
    (0.20, 0.02, 20.00, 1.12),
    (0.25, 0.02, 25.00, 1.32),
    (0.30, 0.02, 30.00, 1.47),
    (0.35, 0.02, 35.00, 1.60),
    (0.40, 0.02, 40.00, 1.68),
    (0.45, 0.02, 45.00, 1.74),
    (0.50, 0.02, 50.00, 1.75),
    (0.55, 0.02, 55.00, 1.74),
    (0.60, 0.02, 60.00, 1.68),
    (0.65, 0.02, 65.00, 1.60),
    (0.70, 0.02, 70.00, 1.47),
    (0.75, 0.02, 75.00, 1.32),
    (0.80, 0.02, 80.00, 1.12),
    (0.85, 0.01, 85.00, 0.90),
    (0.90, 0.01, 90.00, 0.63),
    (0.95, 0.01, 95.00, 0.34),
    (0.99, 0.01, 99.00, 0.07),
]


def main() -> int:
    bad = []
    for price, fee_one, price_hundred, fee_hundred in PDF_GENERAL_TABLE:
        got_one = RM.taker_fee(1, price)
        got_hundred = RM.taker_fee(100, price)
        if abs(got_one - fee_one) > 1e-9:
            bad.append(f"P={price}: fee for 1 contract is ${got_one:.2f}, the schedule prints ${fee_one:.2f}")
        if abs(got_hundred - fee_hundred) > 1e-9:
            bad.append(f"P={price}: fee for 100 contracts is ${got_hundred:.2f}, the schedule prints ${fee_hundred:.2f}")
        if abs(RM.num(price_hundred) - price_hundred) > 1e-9:
            bad.append(f"P={price}: sanity on the price column")

    # Maker side: the schedule's default maker multiplier is 0, so a resting order costs
    # nothing until it trades; and where a series lists 1, the 0.0175 factor applies.
    if RM.maker_fee(100, 0.50, 0) != 0.0:
        bad.append("maker fee with the default multiplier (0) must be zero")
    if RM.maker_fee(100, 0.50, 1) != RM.ceil_cent(0.0175 * 100 * 0.5 * 0.5):
        bad.append("maker formula must be roundup(M x 0.0175 x C x P x (1-P))")
    # 0.0175 x 100 x 0.50 x 0.50 = 0.4375, rounded up to the next cent = 0.44
    if RM.maker_fee(100, 0.50, 1) != 0.44:
        bad.append(f"maker fee for 100 contracts at 50c computed {RM.maker_fee(100, 0.50, 1)}, expected 0.44")

    # Series multipliers that the schedule lists explicitly for this project's categories.
    model = RM.load_model()
    table = model["fees"]["series_multipliers"]["table"]
    for series, want in (("KXAAAGASM", (1, 1)), ("KXBTCY", (0, 0)), ("KXETHY", (0, 0)), ("KXPGATOUR", (1, 1))):
        row = table.get(series)
        if not row:
            bad.append(f"{series} multiplier row missing from data/roi_model.json")
            continue
        if (row["maker"], row["taker"]) != want:
            bad.append(f"{series}: transcribed ({row['maker']}, {row['taker']}) but the schedule prints {want}")
    unlisted = RM.series_mult("KXNOSUCHSERIES", model)
    if (unlisted["taker"], unlisted["maker"], unlisted["listed"]) != (1, 0, False):
        bad.append("an unlisted series must fall back to the general default (taker 1, maker 0) and say it is unlisted")

    if bad:
        print("FEE MODEL DISAGREES WITH THE PUBLISHED SCHEDULE:")
        for b in bad:
            print("  -", b)
        return 1
    print(f"OK: taker fees reproduce all {len(PDF_GENERAL_TABLE)} rows of the published general table (21 prices x 2 sizes = 42 numbers);")
    print("    maker default 0, KXAAAGASM/KXBTCY/KXETHY/KXPGATOUR multipliers match the Non-Standard Fees table.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
