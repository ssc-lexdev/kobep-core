#!/usr/bin/env python3
"""Audit: keys are unique and every foreign key resolves, reading the CSVs only.

Unlike the other audits this one needs nothing but the release itself, so a
reuser can run it on a downloaded copy. Exit status 1 on any failure.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter

PRIMARY = {
    "kobep_filing_index.csv": ("rcept_no",),
    "kobep_filing_entity.csv": ("rcept_no",),
    "kobep_blockholder_entity.csv": ("reporter_id",),
    "kobep_position_ledger.csv": ("rcept_no",),
    "kobep_transaction_ledger.csv": ("rcept_no", "row_no"),
    "kobep_terms_event.csv": ("rcept_no", "row_no"),
    "kobep_event_ledger.csv": ("event_id",),
    "kobep_security_class.csv": ("security_ko",),
    "kobep_firm_master.csv": ("corp_code", "fiscal_year"),
    "kobep_firmyear_financial.csv": ("corp_code", "fiscal_year"),
    "kobep_firmyear_payout.csv": ("corp_code", "fiscal_year"),
}
FOREIGN = [  # (child file, child column, parent file, parent column)
    ("kobep_filing_entity.csv", "rcept_no", "kobep_filing_index.csv", "rcept_no"),
    ("kobep_filing_entity.csv", "reporter_id", "kobep_blockholder_entity.csv", "reporter_id"),
    ("kobep_position_ledger.csv", "rcept_no", "kobep_filing_index.csv", "rcept_no"),
    ("kobep_position_ledger.csv", "reporter_id", "kobep_blockholder_entity.csv", "reporter_id"),
    ("kobep_transaction_ledger.csv", "rcept_no", "kobep_position_ledger.csv", "rcept_no"),
    ("kobep_transaction_ledger.csv", "security_ko", "kobep_security_class.csv", "security_ko"),
    ("kobep_terms_event.csv", "rcept_no", "kobep_filing_index.csv", "rcept_no"),
    ("kobep_event_ledger.csv", "entry_rcept_no", "kobep_position_ledger.csv", "rcept_no"),
    ("kobep_event_ledger.csv", "reporter_id", "kobep_blockholder_entity.csv", "reporter_id"),
    ("kobep_event_ledger.csv", "corp_code", "kobep_firm_master.csv", "corp_code"),
    ("kobep_filing_index.csv", "corp_code", "kobep_firm_master.csv", "corp_code"),
    ("kobep_firmyear_financial.csv", "corp_code", "kobep_firm_master.csv", "corp_code"),
    ("kobep_firmyear_payout.csv", "corp_code", "kobep_firm_master.csv", "corp_code"),
]


def read(path: str) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.0")
    args = ap.parse_args()
    data = os.path.join(args.release, "data")
    tables = {f: read(os.path.join(data, f)) for f in PRIMARY}
    failures = []
    for f, key in PRIMARY.items():
        dup = sum(n - 1 for n in Counter(tuple(r[k] for k in key) for r in tables[f]).values()
                  if n > 1)
        blank = sum(1 for r in tables[f] if any(not r[k] for k in key))
        print(f"  {f:34s} {len(tables[f]):>9,} rows   duplicate keys {dup}   blank keys {blank}")
        if dup or blank:
            failures.append(f"{f}: key")
    for child, ccol, parent, pcol in FOREIGN:
        parents = {r[pcol] for r in tables[parent]}
        orphans = sum(1 for r in tables[child] if r[ccol] and r[ccol] not in parents)
        print(f"  {child}.{ccol} -> {parent}.{pcol}: orphans {orphans}")
        if orphans:
            failures.append(f"{child}.{ccol}")
    if failures:
        print("FAIL:", failures)
        sys.exit(1)
    print("PASS: keys unique, all foreign keys resolve")


if __name__ == "__main__":
    main()
