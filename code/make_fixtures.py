#!/usr/bin/env python3
"""Select and redact the original-filing fixtures shipped with the release.

The original XML is not redistributed (decision D12/D17): it names natural
persons. A small set of originals is still needed so that the parser can be
tested and a reuser can see what the code reads. Fixtures are chosen so that
no natural person appears in them at all - filer, related parties and
transaction parties are companies - and the contact block every filing carries
(the preparer's name, phone, e-mail, fax and addresses) is blanked. So is the
value beside every label naming a natural person who signs or decides for an
organisation - representative (대표자, 대표이사, 대표조합원, 업무집행조합원), a
corporate largest shareholder's representative, the decision-maker - whether
the cell is coded (SUB_REP, SUB_DEC) or not. Added 2026-10-08 after
"대표이사 <name>" (a CEO's name) was found in a released fixture.

Strata: form generation (2.x / 3.x / 4.x / 6.0) x {standard, short}, plus an
amended and a joint filing, 13 in total, chosen deterministically (the earliest
qualifying receipt number in each stratum). Output: fixtures/<rcept_no>.xml in
UTF-8 and fixtures/fixtures.csv.

Every fixture is re-scanned after redaction against the internal list of
natural-person names and against phone and e-mail patterns; any hit fails.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "parser"))
sys.path.insert(0, HERE)
from kobep_parser import read_zip  # noqa: E402
from extract_release import _birth_date, _CORPORATE, is_person_party, norm_name  # noqa: E402

BLANK_CODES = re.compile(r"RSP_MAN\w*|IFR_ADR2|ADR2|RSP_MAN_ADR2|SUB_REP|SUB_DEC")
#: Labels whose neighbouring value cell names a person acting for an organisation.
PERSON_LABEL = re.compile(r"대표자|대표이사|대표조합원|업무집행조합원|의사결정권자")
_PAIR = re.compile(r'(<T[DE][^>]*>)((?:(?!</T[DE]>).){0,80}?)(</T[DE]>\s*<T[DEU][^>]*>)(.*?)(</T[DEU]>)',
                   re.S)
PERSON_ID_CELLS = ("SPC_ID2", "PRH_ID", "IFR_ID")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"0\d{1,2}[-)\s]\d{3,4}[-\s]\d{4}")
STRATA = [("2", "standard"), ("2", "short"), ("3", "standard"), ("3", "short"),
          ("4", "standard"), ("4", "short"), ("6", "standard"), ("6", "short")]


def _label(cell: str) -> str:
    return re.sub(r"<[^>]+>|&cr;|\s+", "", cell)


def redact(xml: str) -> str:
    xml = re.sub(r'(<(?:TE|TD|TU)[^>]*ACODE="(?:' + BLANK_CODES.pattern + r')"[^>]*>)(.*?)(</(?:TE|TD|TU)>)',
                 lambda m: m.group(1) + "[REDACTED]" + m.group(3), xml, flags=re.S)

    def by_label(m: re.Match) -> str:
        value = _label(m.group(4))
        if PERSON_LABEL.search(_label(m.group(2))) and value not in ("", "-", "[REDACTED]"):
            return m.group(1) + m.group(2) + m.group(3) + "[REDACTED]" + m.group(5)
        return m.group(0)
    return _PAIR.sub(by_label, xml)


def fixture_problems(xml: str, people: set[str]) -> list[str]:
    """Checks shared with audit/audit_pii.py: a person-label value left
    unredacted, a known person's name (also when written with spaces between
    syllables, as in "<X Y Z>"), or a contact detail."""
    out = []
    for m in _PAIR.finditer(xml):
        if PERSON_LABEL.search(_label(m.group(2))) and _label(m.group(4)) not in ("", "-", "[REDACTED]"):
            out.append(f"person label value: {_label(m.group(2))}")
    text = re.sub(r"<[^>]+>", " ", xml)
    if EMAIL.search(text) or PHONE.search(text):
        out.append("contact detail")
    spaced = {t.replace(" ", "") for t in re.findall(r"(?<![가-힣])[가-힣](?: [가-힣]){1,3}(?![가-힣])", text)}
    tokens = {norm_name(t) for t in re.findall(r"[가-힣]{2,4}", text)} | spaced
    hit = tokens & people
    if hit:
        out.append(f"person name {sorted(hit)[:3]}")
    return out


def cells(xml: str, code: str) -> list[str]:
    return [re.sub(r"<[^>]+>|\s+", " ", v).strip() for v in
            re.findall(rf'ACODE="{code}"[^>]*>(.*?)</(?:TE|TD|TU)>', xml, re.S)]


def clean(xml: str, people: set[str]) -> tuple[bool, str]:
    for code in PERSON_ID_CELLS:
        for v in cells(xml, code):
            if _birth_date(v.replace(" ", "")):
                return False, f"{code} birth date"
    for nm_code, id_code in (("SPC_NM", "SPC_ID2"), ("PRH_NM", "PRH_ID")):
        for n, i in zip(cells(xml, nm_code), cells(xml, id_code)):
            if n and is_person_party(i, n):
                return False, f"{nm_code} person"
    # Some filings reach DART with their Korean text already replaced by "?"
    # (20220802000226 has 610 runs of "????", the issuer name included). They
    # parse, but they show a reader nothing; a readable filing of the same
    # stratum is taken instead (2026-10-09).
    if len(re.findall(r"\?{3,}", xml)) >= 5:
        return False, "text lost at source"
    problems = fixture_problems(xml, people)
    return (False, problems[0]) if problems else (True, "")


def person_names(con) -> set[str]:
    people = set()
    for v, ind in con.execute("select name_variants, is_individual from blockholder_entity"):
        if ind:
            people.update(norm_name(x) for x in json.loads(v or "[]"))
    for pid, nm in con.execute("select party_id, party_name from filing_transaction"):
        if nm and is_person_party(pid, nm):
            people.add(norm_name(nm))
    return {p for p in people if len(p) >= 3}      # 2-syllable names collide with words


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=r"C:\KOBEP\ledger.db")
    ap.add_argument("--raw", default=r"C:\KOBEP\raw\doc")
    ap.add_argument("--out", default=r"C:\KOBEP\release\KOBEP-Core_v1.0\fixtures")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    people = person_names(con)

    released = {r[0] for r in csv.reader(open(os.path.join(
        os.path.dirname(args.out), "data", "kobep_filing_index.csv"), encoding="utf-8"))}
    cand = con.execute("""
        select p.rcept_no, i.corp_code, p.formula_version, p.form_kind, p.is_amendment,
               p.joint_filing from filing_parsed p join report_index i using (rcept_no)
        order by p.rcept_no""").fetchall()
    want = {s: None for s in STRATA}
    want[("amend", "")] = None
    want[("joint", "")] = None
    want[("burnin", "")] = None
    tried = 0
    for rc, corp, ver, kind, amend, joint in cand:
        if rc not in released or not ver:
            continue
        keys = [(ver.split(".")[0], kind)]
        # Amended and joint filings are drawn from the core window so that the
        # early-form strata do not absorb them.
        if amend and rc >= "2016":
            keys.append(("amend", ""))
        if joint and rc >= "2016":
            keys.append(("joint", ""))
        if rc < "2016":
            keys.append(("burnin", ""))
        keys = [k for k in keys if k in want and want[k] is None]
        if not keys:
            continue
        path = os.path.join(args.raw, corp, f"{rc}.xml.gz")
        if not os.path.exists(path):
            continue
        tried += 1
        xml = redact(read_zip(gzip.decompress(open(path, "rb").read()))[0])
        ok, _why = clean(xml, people)
        if ok:
            want[keys[0]] = (rc, ver, kind, amend, joint, xml)
        if all(want.values()):
            break
    os.makedirs(args.out, exist_ok=True)
    rows = []
    for (a, b), v in sorted(want.items(), key=lambda x: str(x[0])):
        if not v:
            print(f"no clean fixture for stratum {a} {b}")
            continue
        rc, ver, kind, amend, joint, xml = v
        with open(os.path.join(args.out, f"{rc}.xml"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(xml)
        rows.append((rc, f"{a}{'.x ' + b if b else ''}".strip(), ver, kind, amend, joint))
    with open(os.path.join(args.out, "fixtures.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["rcept_no", "stratum", "form_version", "form_kind", "is_amendment", "joint_filing"])
        w.writerows(sorted(rows))
    print(f"{len(rows)} fixtures written ({tried} candidates screened) -> {args.out}")


if __name__ == "__main__":
    main()
