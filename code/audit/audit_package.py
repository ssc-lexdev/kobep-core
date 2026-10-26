#!/usr/bin/env python3
"""Check the release package as a whole, and write its checksums.

1. `data/` holds exactly the twelve release CSVs - nothing else.
2. No editor or system debris anywhere: Office lock files (`~$*`, which carry
   the account name of whoever opened the file), `*.tmp`, `*.bak`, `.DS_Store`,
   `Thumbs.db`, `__pycache__`, `*.pyc`.
3. `manifest/checksums.sha256` lists every file in the package except itself,
   and every digest matches.

    python audit_package.py --release <root> --write   # (re)write checksums, then check
    python audit_package.py --release <root>           # check only (a downloaded copy)

Exit status 1 on any failure.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import sys

DATA_FILES = {
    "kobep_blockholder_entity.csv", "kobep_event_ledger.csv", "kobep_filing_entity.csv",
    "kobep_filing_index.csv", "kobep_firm_master.csv", "kobep_firmyear_financial.csv",
    "kobep_firmyear_payout.csv", "kobep_missing_reasons.csv", "kobep_position_ledger.csv",
    "kobep_security_class.csv", "kobep_terms_event.csv", "kobep_transaction_ledger.csv",
}
DEBRIS = ["~$*", "*.tmp", "*.bak", "*.swp", ".DS_Store", "Thumbs.db", "desktop.ini",
          "*.pyc", "__pycache__", ".ipynb_checkpoints"]
CHECKSUMS = "manifest/checksums.sha256"


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def walk(root: str) -> tuple[list[str], list[str]]:
    files, debris = [], []
    for here, dirs, names in os.walk(root):
        for d in list(dirs):
            if any(fnmatch.fnmatch(d, p) for p in DEBRIS):
                debris.append(os.path.relpath(os.path.join(here, d), root))
                dirs.remove(d)
        for n in names:
            rel = os.path.relpath(os.path.join(here, n), root).replace(os.sep, "/")
            (debris if any(fnmatch.fnmatch(n, p) for p in DEBRIS) else files).append(rel)
    return sorted(files), sorted(debris)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.0")
    ap.add_argument("--write", action="store_true", help="rewrite the checksum file first")
    args = ap.parse_args()
    root = args.release
    failures = []

    files, debris = walk(root)
    if debris:
        failures.append(f"debris: {debris}")
    data = {f[5:] for f in files if f.startswith("data/")}
    if data != DATA_FILES:
        failures.append(f"data/ extra {sorted(data - DATA_FILES)} missing {sorted(DATA_FILES - data)}")

    listed = [f for f in files if f != CHECKSUMS]
    if args.write and not failures:
        with open(os.path.join(root, CHECKSUMS), "w", encoding="utf-8", newline="\n") as fh:
            for f in listed:
                fh.write(f"{sha256(os.path.join(root, f))}  {f}\n")

    recorded = {}
    with open(os.path.join(root, CHECKSUMS), encoding="utf-8") as fh:
        for line in fh:
            digest, name = line.rstrip("\n").split("  ", 1)
            recorded[name] = digest
    if set(recorded) != set(listed):
        failures.append(f"checksum list: unlisted {sorted(set(listed) - set(recorded))} "
                        f"stale {sorted(set(recorded) - set(listed))}")
    bad = [f for f in listed if f in recorded and sha256(os.path.join(root, f)) != recorded[f]]
    if bad:
        failures.append(f"digest mismatch: {bad}")

    print(f"{len(listed)} files, {len(data)} data files, {len(debris)} debris, "
          f"{len(recorded)} checksums")
    if failures:
        print("FAIL\n  " + "\n  ".join(failures), file=sys.stderr)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
