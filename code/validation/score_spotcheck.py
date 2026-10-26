#!/usr/bin/env python3
"""Score the reviewed spot-check workbook: error rates with Wilson 95 % intervals.

Reads the `chk_*` marks written by reviewers into the workbook from
`make_spotcheck.py`. CANT_TELL is reported but excluded from the denominator,
and so is a blank mark; both counts are printed so that a half-finished review
cannot pass for a clean one. Writes `spotcheck_summary.csv` (per sheet, per
field) for the Technical Validation table.
"""
from __future__ import annotations

import argparse
import math
import os

import pandas as pd

Z = 1.959964


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centre = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workbook")
    args = ap.parse_args()
    rows = []
    for sheet in ("filings", "transactions", "events"):
        df = pd.read_excel(args.workbook, sheet_name=sheet, dtype=str).fillna("")
        for col in [c for c in df.columns if c.startswith("chk_")]:
            marks = df[col].str.strip().str.upper()
            ok, wrong = int((marks == "OK").sum()), int((marks == "WRONG").sum())
            cant, blank = int((marks == "CANT_TELL").sum()), int((marks == "").sum())
            n = ok + wrong
            lo, hi = wilson(wrong, n)
            rows.append((sheet, col[4:], n, wrong, wrong / n if n else float("nan"),
                         lo, hi, cant, blank))
        item_wrong = (df[[c for c in df.columns if c.startswith("chk_")]]
                      .apply(lambda s: s.str.strip().str.upper()) == "WRONG").any(axis=1)
        reviewed = (df[[c for c in df.columns if c.startswith("chk_")]] != "").all(axis=1)
        k, n = int((item_wrong & reviewed).sum()), int(reviewed.sum())
        lo, hi = wilson(k, n)
        rows.append((sheet, "ANY_FIELD (item level)", n, k, k / n if n else float("nan"),
                     lo, hi, None, int((~reviewed).sum())))
    out = pd.DataFrame(rows, columns=["sheet", "field", "n_scored", "n_wrong", "error_rate",
                                      "wilson95_lo", "wilson95_hi", "n_cant_tell",
                                      "n_unreviewed"])
    dest = os.path.join(os.path.dirname(os.path.abspath(args.workbook)),
                        "spotcheck_summary.csv")
    out.to_csv(dest, index=False, lineterminator="\n")
    pd.set_option("display.width", 160)
    print(out.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"-> {dest}")


if __name__ == "__main__":
    main()
