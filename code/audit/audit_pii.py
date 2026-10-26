#!/usr/bin/env python3
"""Audit: no natural person appears anywhere in the release (decision D17).

Four checks, all of which must come back empty:

  1. reporters   every reporter_id in the release is a non-individual entity
                 in the internal ledger.
  2. identifiers no identifier column holds a valid YYMMDD birth date or a
                 resident-registration-number shape - not even beside a
                 corporate name, where it is a representative's birth date
                 (tightened 2026-10-07) - and no entity is keyed BIRTH_DATE.
  3. known names no text cell equals a name the internal ledger knows to be a
                 natural person: every name variant of an individual entity and
                 every party name on a person row the extractor dropped. This
                 is the check that catches romanised foreign individuals, whose
                 identifiers are passport-style and pass check 2.
  4. contact     no e-mail address or Korean phone number in any cell.
  5. role names  no name cell carries a signatory's name ("우리사주조합장 <name>",
                 "대표조합원 <name>").
  6. fixtures    every parser fixture (original filing XML) has the value
                 beside each representative / decision-maker label redacted,
                 no known person's name (also written with spaces between
                 syllables) and no contact detail (added 2026-10-08).
  7. other text  docs/, manifest/, code/ (comments included) and the root
                 files carry no contact detail or known person name (code/
                 and root files added 2026-10-09, after example names were
                 found in code comments).

Names that are also used by a corporate entity (e.g. a holding company named
after its founder) are reported separately as ambiguous rather than failed.
The audit reads the internal ledger for the reference lists; it is part of the
release gate, not of the public reproduction path.

Exit status 1 on any failure.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from extract_release import (_CORPORATE, ROLE_NAME_PATTERN, _birth_date,  # noqa: E402
                             is_person_party)

#: Words that entered the person-name list from mis-typed party rows.
NOT_NAMES = {"우리사주"}
ID_COLS = {"party_id", "id_value"}
NAME_COLS = {"party_name", "name"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}\b")
RRN = re.compile(r"\b\d{6}-[1-8]\d{6}\b")


def norm(s: str) -> str:
    return re.sub(r"[\s.,()·]", "", s or "").upper()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.1")
    ap.add_argument("--ledger", default=r"C:\KOBEP\ledger.db")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{args.ledger}?mode=ro", uri=True)

    individual, person_names, corp_names = set(), set(), set()
    for rid, ind, id_value, name, variants in con.execute(
            "select reporter_id, is_individual, id_value, name_normalized, name_variants "
            "from blockholder_entity"):
        # Flagged individual, or keyed on a birth date under a non-corporate name.
        person = bool(ind) or (_birth_date((id_value or "").strip())
                               and not _CORPORATE.search(name or ""))
        if person:
            individual.add(rid)
        for v in json.loads(variants or "[]") + [name or ""]:
            (person_names if person else corp_names).add(norm(v))
    for pid, name in con.execute("select party_id, party_name from filing_transaction"):
        if name and is_person_party(pid, name):
            person_names.add(norm(name))
    person_names = {n for n in person_names if len(n) >= 2}
    ambiguous_names = person_names & corp_names
    person_only = person_names - corp_names

    data = os.path.join(args.release, "data")
    fail, ambiguous = Counter(), Counter()
    examples: dict[str, list] = {}
    for fname in sorted(os.listdir(data)):
        with open(os.path.join(data, fname), encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                rid = row.get("reporter_id")
                if rid and rid in individual:
                    fail[f"{fname}: individual reporter_id"] += 1
                name = row.get("party_name") or row.get("name") or ""
                if row.get("id_kind") == "BIRTH_DATE":
                    fail[f"{fname}: id_kind BIRTH_DATE"] += 1
                for col in ID_COLS & row.keys():
                    v = (row[col] or "").strip()
                    if _birth_date(v) or RRN.search(v):
                        fail[f"{fname}.{col}: birth-date/RRN shape"] += 1
                        examples.setdefault(fname + col, []).append((v, name))
                for col, v in row.items():
                    if not v:
                        continue
                    if EMAIL.search(v) or PHONE.search(v):
                        fail[f"{fname}.{col}: contact detail"] += 1
                    if col in NAME_COLS or col.endswith("_json"):
                        cells = json.loads(v) if col.endswith("_json") else [v]
                        for cell in cells:
                            if ROLE_NAME_PATTERN.search(cell):
                                fail[f"{fname}.{col}: signatory name"] += 1
                                examples.setdefault(fname + col, []).append(cell)
                            key = norm(cell)
                            if key in person_only:
                                fail[f"{fname}.{col}: known person name"] += 1
                                examples.setdefault(fname + col, []).append(cell)
                            elif key in ambiguous_names:
                                ambiguous[f"{fname}.{col}"] += 1
                                examples.setdefault("amb:" + fname + col, []).append(cell)

    # 6-7. Fixtures and the remaining text files of the package.
    from make_fixtures import fixture_problems, person_names  # noqa: E402
    people3 = person_names(con)
    fx = os.path.join(args.release, "fixtures")
    for fname in sorted(os.listdir(fx)) if os.path.isdir(fx) else []:
        if fname.endswith(".xml"):
            for prob in fixture_problems(open(os.path.join(fx, fname), encoding="utf-8").read(), people3):
                fail[f"fixtures/{fname}: {prob}"] += 1
    others = []
    for sub in ("docs", "manifest", "code"):
        for here, _, fs in os.walk(os.path.join(args.release, sub)):
            others += [os.path.join(here, f) for f in fs]
    others += [os.path.join(args.release, f) for f in os.listdir(args.release)
               if os.path.isfile(os.path.join(args.release, f))]
    for path in sorted(others):
        if path.endswith((".csv", ".md", ".txt", ".py", ".json", ".cff", ".sha256", ".do", ".R")):
            sub, fname = os.path.split(os.path.relpath(path, args.release))
            text = open(path, encoding="utf-8", errors="replace").read()
            if EMAIL.search(text) or PHONE.search(text):
                fail[f"{sub}/{fname}: contact detail"] += 1
            hit = ({norm(t) for t in re.findall(r"[가-힣]{3,4}", text)} & person_only) - NOT_NAMES
            if hit:
                fail[f"{sub}/{fname}: known person name"] += 1
                examples.setdefault(f"{sub}/{fname}", []).extend(sorted(hit)[:5])

    print(f"reference: {len(individual):,} individual entities, "
          f"{len(person_only):,} person-only names, {len(ambiguous_names):,} shared names")
    for k, v in sorted(ambiguous.items()):
        sample = sorted(set(examples.get('amb:' + k.replace('.', '', 1), [])))[:8]
        print(f"  ambiguous (person & company share the name): {k} {v}")
    amb_names = sorted({c for k, v in examples.items() if k.startswith("amb:") for c in v})
    if amb_names:
        print("  shared names seen:", amb_names[:30])
    if fail:
        for k, v in sorted(fail.items()):
            print(f"FAIL {k}: {v}")
        for k, v in examples.items():
            if not k.startswith("amb:"):
                print("   e.g.", k, v[:8])
        sys.exit(1)
    print("PASS: no natural person found")


if __name__ == "__main__":
    main()
