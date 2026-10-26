#!/usr/bin/env python3
"""Write README.md, CITATION.cff and the licence files at the release root.

Row counts come from manifest/extract_report.json, so the README cannot drift
from the files it describes. Run after extract_release.py.
"""
from __future__ import annotations

import argparse
import json
import os

VERSION = "1.1"
TITLE = ("KOBEP-Core: Korean blockholder entry and payout ledger, KOSPI 2011-2025")
AUTHOR_FAMILY, AUTHOR_GIVEN = "Choi", "Sungsoo"   # copyright holder in the licence files
# Dataset authors, as in the manuscript (ORCID iDs checked on pub.orcid.org, 2026-10-26)
AUTHORS = [
    ("Choi", "Sungsoo", "0009-0000-4010-3272", "Seoul AI School, aSSIST University; Korean Bar Association"),
    ("Oh", "Taeyeon", "0000-0002-1867-5554", "Seoul AI School, aSSIST University; Dong-A University"),
]
DOI = "10.5281/zenodo.23666227"     # v1.1 version DOI (v1.0: 10.5281/zenodo.23663204;
                                    # all versions: 10.5281/zenodo.23663203)

FILES = [
    ("kobep_firm_master.csv", "corp_code, fiscal_year",
     "Firm-year identity: stock code, names (ko/en), KSIC, listing status, origin."),
    ("kobep_filing_index.csv", "rcept_no",
     "Every 5 % beneficial-ownership filing of a legal-person filer, 2011-2025."),
    ("kobep_filing_entity.csv", "rcept_no",
     "Filing -> blockholder entity."),
    ("kobep_blockholder_entity.csv", "reporter_id",
     "Reporting entities (legal persons) resolved on registration numbers, names over time."),
    ("kobep_position_ledger.csv", "rcept_no",
     "One row per parsed filing: dates, ratios, relation, report type, purpose."),
    ("kobep_transaction_ledger.csv", "rcept_no, row_no",
     "Every reported movement in holdings, with the filer-stated unit price and its kind."),
    ("kobep_terms_event.csv", "rcept_no, row_no",
     "Changes in the terms of holdings (pledges, contracts) without share movement."),
    ("kobep_event_ledger.csv", "event_id",
     "One row per issuer x blockholder relationship: entry, peak, exit, censoring "
     "(observed through 2025-12-31)."),
    ("kobep_security_class.csv", "security_ko",
     "Security labels in the tables -> standard class."),
    ("kobep_firmyear_financial.csv", "corp_code, fiscal_year",
     "Annual statement levels and ratios, 2016-2025."),
    ("kobep_firmyear_payout.csv", "corp_code, fiscal_year",
     "Cash dividends, treasury-share quantities, reported buyback amounts, total payout."),
    ("kobep_missing_reasons.csv", "file, variable, reason_code, rule",
     "Why each blank cell is blank, by rule; every blank cell is covered."),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.1")
    args = ap.parse_args()
    rep = json.load(open(os.path.join(args.release, "manifest", "extract_report.json"),
                         encoding="utf-8"))
    rows = rep["rows"]
    table = "\n".join(f"| `{f}` | {rows.get(f, 0):,} | {k} | {d} |" for f, k, d in FILES)
    readme = f"""# {TITLE}

Version {VERSION}. DOI: https://doi.org/{DOI}
(all versions: https://doi.org/10.5281/zenodo.23663203)

A relational dataset built entirely from Korean statutory disclosures (DART,
operated by the Financial Supervisory Service). It records every 5 % beneficial-
ownership filing by a legal-person filer on a KOSPI issuer from 2011 to 2025, the
individual movements in holdings each filing reports, the blockholder entities
behind them, the issuer x blockholder relationships they form, and the issuers'
annual financials and shareholder payouts for 2016-2025.

## Files (`data/`)

| File | Rows | Key | Contents |
|---|---:|---|---|
{table}

All files are UTF-8 CSV without BOM, comma-separated, one header row, ISO dates
(YYYY-MM-DD). A blank cell is missing; every blank cell is covered by a documented
rule in `kobep_missing_reasons.csv`. Identifiers (`corp_code`, `rcept_no`,
`reporter_id`, `party_id`, ...) must be read as text - `corp_code` has leading
zeros; `code/read_kobep.py` does this.
Variables are defined in `docs/kobep_variable_dictionary.csv`; Korean values kept
as filed (`*_ko` columns) are glossed in `docs/kobep_vocabulary.csv`.

## How the files join

```
firm_master (corp_code, fiscal_year)
  |-- filing_index (rcept_no) --- filing_entity --- blockholder_entity (reporter_id)
  |       |-- position_ledger (rcept_no)
  |       |      |-- transaction_ledger (rcept_no, row_no)
  |       |-- terms_event (rcept_no, row_no)
  |-- event_ledger (event_id: corp_code x reporter_id; entry_rcept_no -> position_ledger)
  |-- firmyear_financial, firmyear_payout (corp_code, fiscal_year)
```

`audit/audit_joins.py` checks every key and foreign key on a downloaded copy.

## Scope and what is deliberately absent

- **Legal persons only.** Filings by natural persons, and natural-person rows
  inside corporate filings, are excluded. Nothing here is pseudonymised: a
  receipt number links back to the public filing, so masking would not
  de-identify.
- **No KRX-origin variables.** No exchange price, market value or return
  variable is included. Prices and yields that filers and issuers state in their
  own disclosures are kept as filed and flagged (`price_source =
  DART_DISCLOSED`; `unit_price_kind`).
- **Ledger 2011-2025, firm-year 2016-2025.** Ledger rows carry `in_core_window`
  (received 2016-2025). The 2011-2015 rows are the pre-window history of the
  2016-2025 panel firms, not a census of KOSPI in those years.
- **Reporting entities, not economic groups.** Entities are resolved on
  registration numbers; one fund house filing under several foreign
  registrations appears as several entities. `needs_review` flags the 326
  entities whose names and numbers do not line up one-to-one.
- **No ownership totals.** With natural persons excluded, sums over this file
  are legal-person holdings only, not total ownership concentration.
- **Korean names as filed.** Names of companies, funds and parties stay in
  Korean (not translated or romanised); join on the identifiers. Controlled
  values have English columns beside them (`method_en`, `report_name_en`,
  `industry_name_en`, `security_class`); `corp_name_en` is the DART English name.
- No free-text fields (they name people); purpose prose is released only as a
  derived category with its basis.

## Usage notes

- Core window: `in_core_window == 1`. Earlier rows date the entries of the
  panel firms' existing holders; they are not a 2011-2015 census.
- Amounts: filter `currency == "KRW"` in `kobep_firmyear_financial.csv` before
  pooling; five companies report in USD or HKD.
- Prices: `unit_price_kind == "EXECUTED_KRW_PER_SHARE"` for executed trade
  prices; depositary-receipt prices (`DR_UNIT_UNCONFIRMED`) are not won per share.
- Events: `entry_left_truncated == 1` marks entries with evidence of an earlier
  holding; `entry_left_truncated_broad == 1` adds entries filed because a
  joint group changed its representative filer (`entry_rep_change == 1`);`class_at_entry == "UNCERTAIN"` is not guessed (relation codes 02,
  16 or blank); `exit_censored == 1` events have no filed exit.
- Exchange data: `corp_code` is the DART issuer key; `stock_code` is the
  year-specific KRX code in `kobep_firm_master.csv`. Check `delisting_date` and
  `is_partial_year` when joining market data.

## Reproducing

`manifest/rcept_no_manifest.csv` lists every receipt number with the SHA-256 of
the payload DART returned and the collection time; the originals can be
re-downloaded from the OpenDART `document.xml` endpoint by receipt number.
`manifest/checksums.sha256` covers every file in the package;
`code/audit/audit_package.py` verifies it. The extraction, parsing and audit
code is in `code/`; `fixtures/` holds redacted originals for the parser tests.
`code/examples/make_treatment.py` is an example of use (event-level indicators
built from the files), not part of the data definition.

## Changes

- 1.1 (2026-10): `superseded_by` added to the position ledger (filings replaced
  by a later amendment); holding ratios documented as filer plus related parties
  as filed; spot-check results stated as found, corrected and re-checked; payout
  spot-check (40 firm-years, 0 errors in 120 fields) and its script added. No
  other data value changed.
- 1.0 (2026-10-26): first release, https://doi.org/10.5281/zenodo.23663204

## Licence

Data: CC BY 4.0 (`LICENSE-DATA.txt`). Code: MIT (`LICENSE-CODE.txt`).
Source disclosures: Financial Supervisory Service, DART (https://dart.fss.or.kr).

## Citation

See `CITATION.cff`.
"""
    open(os.path.join(args.release, "README.md"), "w", encoding="utf-8", newline="\n").write(readme)
    CFF_AUTHORS = "".join(
        f'  - family-names: "{fam}"\n    given-names: "{giv}"\n'
        f'    orcid: "https://orcid.org/{oid}"\n    affiliation: "{aff}"\n'
        for fam, giv, oid, aff in AUTHORS)
    cff = f"""cff-version: 1.2.0
message: "If you use this dataset, please cite it as below."
title: "{TITLE}"
version: "{VERSION}"
doi: "{DOI}"
license: CC-BY-4.0
type: dataset
authors:
{CFF_AUTHORS}keywords:
  - beneficial ownership
  - blockholders
  - shareholder activism
  - dividends
  - share repurchases
  - Korea
"""
    open(os.path.join(args.release, "CITATION.cff"), "w", encoding="utf-8", newline="\n").write(cff)
    open(os.path.join(args.release, "LICENSE-DATA.txt"), "w", encoding="utf-8", newline="\n").write(
        f"{TITLE}\nCopyright (c) 2026 {AUTHOR_GIVEN} {AUTHOR_FAMILY}\n\n"
        "The data files in this package are licensed under the Creative Commons\n"
        "Attribution 4.0 International licence (CC BY 4.0).\n"
        "Legal code: https://creativecommons.org/licenses/by/4.0/legalcode\n\n"
        "The underlying disclosures are published by the Financial Supervisory\n"
        "Service of Korea through DART (https://dart.fss.or.kr).\n")
    open(os.path.join(args.release, "LICENSE-CODE.txt"), "w", encoding="utf-8", newline="\n").write(
        f"MIT License\n\nCopyright (c) 2026 {AUTHOR_GIVEN} {AUTHOR_FAMILY}\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        "of this software and associated documentation files (the \"Software\"), to deal\n"
        "in the Software without restriction, including without limitation the rights\n"
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
        "copies of the Software, and to permit persons to whom the Software is\n"
        "furnished to do so, subject to the following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all\n"
        "copies or substantial portions of the Software.\n\n"
        "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n"
        "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
        "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
        "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
        "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
        "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
        "SOFTWARE.\n")
    print("README.md, CITATION.cff, LICENSE-DATA.txt, LICENSE-CODE.txt ->", args.release)


if __name__ == "__main__":
    main()
