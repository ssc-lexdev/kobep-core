#!/usr/bin/env python3
"""Tests of the KOBEP parser against the public fixtures and the released files.

Run from the package:   python -B code/parser/test_parser.py
               or with: python -B test_parser.py --release <KOBEP-Core_v1.0 folder>
(-B keeps Python from writing __pycache__ into the package, which would no
longer match manifest/checksums.sha256.)

Two kinds of test:

1. Regression against the release. Each file in `fixtures/` is an original
   DART filing (preparer contact and representative names redacted). It is
   parsed here and every field the release takes from it - dates, report type,
   relation to the issuer, ratios, form version, amendment flag, and each
   transaction row - must equal the same filing's row in `data/`. A change to
   the parser that alters released values fails here before it reaches a file.

2. The parsing pitfalls of Korean 5 % filings, each observed in real filings
   and each one that corrupts values silently rather than raising an error:
     P1  relation code 16 'other' (and 02) never auto-classified OUTSIDER
     P2  relation to the issuer read from FLT_CRP_RLT, not the filer relation
     P3  filer type Y is a pension fund, not an individual
     P4  amended filings: post-amendment (ACLASS=EXTRACTION) values win
     P5  every code domain complete - no UNMAPPED values
     P6  the XML declaration says UTF-8 whatever the encoding; detection must
         not rely on it
     P7  prices: one well-formed number per cell, decimals kept

Exit status 1 on any failure. Rewritten 2026-10-09 for the public fixtures;
the previous version expected the internal fixture names (2011_*, 2024_정정*).
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kobep_parser import (  # noqa: E402
    ACQUISITION_METHOD, FILER_TYPE, INDIVIDUAL_FILER_TYPES, RELATION_TO_ISSUER,
    decode_dart, parse)
from parse_transactions import price, rows_from  # noqa: E402

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        _failures.append(name)


def section(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def release_root(arg: str | None) -> str:
    """The package root: given, or two levels up from code/parser, or the
    default build location."""
    for cand in (arg, os.path.dirname(os.path.dirname(HERE)), r"C:\KOBEP\release\KOBEP-Core_v1.0"):
        if cand and os.path.isdir(os.path.join(cand, "fixtures")) and os.path.isdir(os.path.join(cand, "data")):
            return cand
    raise SystemExit("release folder with fixtures/ and data/ not found; pass --release")


def num(v) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def iso(d: str | None) -> str:
    d = (d or "").replace("-", "")
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 and d.isdigit() else ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release")
    root = release_root(ap.parse_args().release)
    fx_dir, data = os.path.join(root, "fixtures"), os.path.join(root, "data")
    fixtures = list(csv.DictReader(open(os.path.join(fx_dir, "fixtures.csv"), encoding="utf-8")))
    wanted = {f["rcept_no"] for f in fixtures}
    pos = {r["rcept_no"]: r for r in csv.DictReader(
        open(os.path.join(data, "kobep_position_ledger.csv"), encoding="utf-8")) if r["rcept_no"] in wanted}
    tx: dict[str, list[dict]] = {}
    with open(os.path.join(data, "kobep_transaction_ledger.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["rcept_no"] in wanted:
                tx.setdefault(r["rcept_no"], []).append(r)
    print(f"release: {root}\nfixtures: {len(fixtures)}")

    parsed = {}
    for f in fixtures:
        raw = open(os.path.join(fx_dir, f"{f['rcept_no']}.xml"), "rb").read()
        xml, enc = decode_dart(raw)
        parsed[f["rcept_no"]] = (parse(xml, f["rcept_no"], enc), xml, raw)

    section("1  Regression: parser output equals the released rows")
    for f in fixtures:
        rc = f["rcept_no"]
        filing, xml, _ = parsed[rc]
        row = pos.get(rc)
        tag = f"{rc} ({f['stratum']})"
        if row is None:
            check(f"{tag} present in position ledger", False)
            continue
        diffs = []
        pairs = [("obligation_date", iso(filing.obligation_date), row["obligation_date"]),
                 ("base_date", iso(filing.base_date), row["base_date"]),
                 ("report_type_code", filing.report_type_code or "", row["report_type_code"]),
                 ("relation_to_issuer_code", "" if filing.relation_to_issuer_code in (None, "-")
                  else filing.relation_to_issuer_code, row["relation_to_issuer_code"]),
                 ("outsider_class", filing.outsider_class, row["outsider_class"]),
                 ("form_version", filing.formula_version, row["form_version"]),
                 ("form_kind", filing.form_kind, row["form_kind"]),
                 ("is_amendment", str(int(bool(filing.is_amendment))), row["is_amendment"])]
        for name, got, want in pairs:
            if (got or "") != (want or ""):
                diffs.append(f"{name} {got!r}!={want!r}")
        for name in ("curr_ratio_stockequiv", "prev_ratio_stockequiv"):
            got, want = num(getattr(filing, name)), num(row[name])
            if got != want and not (got is not None and want is not None and abs(got - want) < 1e-9):
                diffs.append(f"{name} {got}!={want}")
        check(f"{tag} position fields", not diffs, "; ".join(diffs[:4]))

        rows = rows_from(xml)
        rel = tx.get(rc, [])
        check(f"{tag} transaction row count {len(rel)}", len(rows) == len(rel), f"parsed {len(rows)}")
        bad = [i for i, (a, b) in enumerate(zip(rows, rel), 1)
               if num(a["shares_change"]) != num(b["shares_change"])
               or num(a["shares_after"]) != num(b["shares_after"])
               or num(a["unit_price"]) != num(b["unit_price"])
               or (a["change_date"] and iso(a["change_date"]) != b["change_date"])]
        if rows and rel:
            check(f"{tag} transaction values", not bad, f"rows {bad[:5]}")

    section("P1  Relation code 16 ('Other') and 02 never auto-classified OUTSIDER")
    check("code 16 -> UNCERTAIN", RELATION_TO_ISSUER["16"][1] == "UNCERTAIN")
    check("code 02 (major shareholder) -> UNCERTAIN", RELATION_TO_ISSUER["02"][1] == "UNCERTAIN")
    outsiders = [k for k, v in RELATION_TO_ISSUER.items() if v[1] == "OUTSIDER"]
    check("only code 13 auto-classifies as OUTSIDER", outsiders == ["13"], str(outsiders))

    section("P2  Relation to the issuer comes from FLT_CRP_RLT")
    with_rel = [rc for rc, (fl, xml, _) in parsed.items() if 'AUNIT="FLT_CRP_RLT"' in xml]
    check("fixtures carrying FLT_CRP_RLT", bool(with_rel), f"{len(with_rel)} of {len(parsed)}")
    for rc in with_rel:
        fl, xml, _ = parsed[rc]
        coded = re.search(r'AUNIT="FLT_CRP_RLT"[^>]*AUNITVALUE="([^"]*)"', xml)
        if coded and coded.group(1) not in ("", "-"):
            check(f"{rc} relation equals FLT_CRP_RLT value", fl.relation_to_issuer_code == coded.group(1),
                  f"{fl.relation_to_issuer_code} vs {coded.group(1)}")

    section("P3  Filer types: a pension fund is never an individual")
    check("filer type 'Y' is a pension fund", FILER_TYPE["Y"] == "Pension fund / professional investor")
    check("filer-type domain is complete (11 codes)", len(FILER_TYPE) == 11, f"{len(FILER_TYPE)} mapped")
    check("individual codes are exactly D and F", INDIVIDUAL_FILER_TYPES == {"D", "F"},
          str(INDIVIDUAL_FILER_TYPES))
    check("Y not treated as an individual", "Y" not in INDIVIDUAL_FILER_TYPES)
    for rc, (fl, _, _) in parsed.items():
        if fl.filer_type_code == "Y" and fl.relation_to_issuer_code == "13":
            check(f"{rc} pension-fund shareholder stays OUTSIDER", fl.outsider_class == "OUTSIDER")

    section("P4  Amended filings: post-amendment values win")
    amended = [f["rcept_no"] for f in fixtures if f["is_amendment"] == "1"]
    check("an amended fixture is present", bool(amended))
    for rc in amended:
        fl, xml, _ = parsed[rc]
        check(f"{rc} recognised as an amendment", bool(fl.is_amendment))
        check(f"{rc} carries post-amendment tables", 'ACLASS="EXTRACTION"' in xml)
        check(f"{rc} ratio equals the released (post-amendment) value",
              num(fl.curr_ratio_stockequiv) == num(pos[rc]["curr_ratio_stockequiv"]),
              f"{fl.curr_ratio_stockequiv} vs {pos[rc]['curr_ratio_stockequiv']}")

    section("P5  Code domains complete")
    # A filer who writes "-" has not stated a relation; the release leaves the
    # code blank and the class UNCERTAIN. Only a real, unknown code fails.
    unmapped = [(rc, fl.relation_to_issuer) for rc, (fl, _, _) in parsed.items()
                if (fl.relation_to_issuer or "").startswith("UNMAPPED")
                and fl.relation_to_issuer_code not in (None, "", "-")]
    check("all relation codes mapped across fixtures", not unmapped, str(unmapped))
    unmapped_type = [(rc, fl.filer_type_code) for rc, (fl, _, _) in parsed.items()
                     if fl.filer_type_code and fl.filer_type_code not in FILER_TYPE]
    check("all filer-type codes mapped across fixtures", not unmapped_type, str(unmapped_type))
    check("acquisition-method domain has 8 codes", len(ACQUISITION_METHOD) >= 8, str(sorted(ACQUISITION_METHOD)))

    section("P6  The XML declaration is uninformative; Korean text survives")
    for rc, (fl, _, raw) in parsed.items():
        declares = re.search(rb'encoding="([^"]+)"', raw[:300])
        check(f"{rc} issuer name decoded as Korean text",
              bool(re.search(r"[가-힣]", fl.issuer_name or "")),
              f"declared {declares.group(1).decode() if declares else '-'}; issuer {fl.issuer_name!r}")

    section("P7  Prices: one well-formed number per cell, decimals kept")
    for cell, want in (("13,269.75", 13269.75), ("8,190/6,000", None), ("(5,827)", 5827),
                       ("21,978(원)", 21978), ("20,101,26", None), ("87,401 (87,576)", None),
                       ("-", None), ("3,193원/주", 3193)):
        check(f"price({cell!r}) == {want!r}", price(cell) == want, f"got {price(cell)!r}")

    print("\n" + "=" * 78)
    if _failures:
        print(f"FAILED ({len(_failures)}): {_failures}")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
