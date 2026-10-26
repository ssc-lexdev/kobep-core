#!/usr/bin/env python3
"""Write docs/KOBEP_codebook_v1.0.md and docs/kobep_validation_summary.csv.

Narrative sections are written here; the variable tables are rendered from
docs/kobep_variable_dictionary.csv and the missing-value table from
data/kobep_missing_reasons.csv, so the codebook cannot disagree with the files.
Validation figures are aggregates only - no row-level exchange value appears.
Also writes docs/kobep_coverage_by_year.csv (rows per file and year).
Run after extract_release.py and make_dictionary.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import os

import pandas as pd

VALIDATION = [
    # (check, scope, n, result, note)
    ("Parser vs DART structured API (holding ratio)", "validation corpus 2024-08 to 2026-07 with both sources",
     6550, "6,550 agree within 0.005 pp (100 %)",
     "majorstock.json; older forms outside the API window; filings received in 2026 were used "
     "only to test the parser and are not in the release"),
    ("Holding-purpose derivation vs coded purpose", "released filings carrying both a filed code and purpose text",
     4916, "98.64 % agree; 01 precision 0.997 recall 0.994; 02 1.000/0.959; 03 0.971/0.888",
     "rule-based; generalisation to pre-code prose assumed; restrict to holding_purpose_basis = "
     "CODED for filed codes only"),
    ("Standard-form cover vs coded purpose (FORM_COVER basis)", "released standard-form filings "
     "with a filed code whose cover names the influence purpose", 4114, "99.34 % coded 01",
     "the cover is used only when no text rule fires"),
    ("Carried-forward purpose (PRIOR_FILING basis)", "released standard-form filings with a filed code "
     "and an earlier classified filing by the same holder on the issuer", 4027,
     "99.35 % match the earlier category; 94.85 % of 97 exit filings",
     "used only for filings still unclassified after the text rules and the cover"),
    ("Changed derived purposes vs originals", "all released filings whose derived purpose changed with the "
     "2026-10-23 rules (171 by text rules or cover, 97 carried forward)", 268, "0 errors",
     "human check of every filing against its original"),
    ("Buyback amount vs an exchange-price estimate", "statement and execution-report "
     "bases, 2016-2025", 1116, "internal plausibility check only",
     "the estimate uses exchange prices and is not released, nor are its ratios"),
    ("Spot-check design", "460 sampled rows (160 filings x 9, 200 transactions x 6, 100 events x 6 "
     "fields), fixed seed, stratified", 3240,
     "every field judged by a human reviewer against the original filing",
     "a language model screened every field first and its flags set the order of review: the 68 flagged rows "
     "first, then the 392 passed rows (358 of them blind to the model); a derived purpose left blank although "
     "its text can be classified counts as an error"),
    ("Spot-check: build examined vs original", "all 3,240 fields", 3240,
     "7 errors (0.22 %; Wilson 95 % upper bound 0.45 %), all blank derived purposes; corrected",
     "a price-parsing defect found in a first pass was corrected before this build (30,960 price cells "
     "in the internal ledger, 2.7 % of its 1,128,021 priced cells)"),
    ("Spot-check: released values vs original", "all 3,240 fields; the 12 fields changed after the "
     "audit re-judged", 3240, "0 errors; Wilson 95 % upper bound 0.12 % per field, 0.83 % per row",
     "0 of 3,240 fields and 0 of 460 rows wrong"),
    ("Language-model screens (screening tools only)", "all 3,240 human-judged fields", 3240,
     "gpt-5.5 98.9 % agree (34 false alarms) and claude-opus-5-5 99.3 % (21) as recorded; 99.1 % (28) "
     "and 99.5 % (16) under the blank-purpose criterion; 0 errors passed by either",
     "no released value depends on a model verdict"),
    ("Event dates within the ledger window", "all release events", 3267,
     "0 dates after 2025-12-31", "extract_release.py assertion"),
    ("Package integrity", "every file in the package", 0,
     "no stray files; all checksums match", "audit/audit_package.py"),
    ("Referential integrity", "all release files", 0, "0 orphan keys, 0 duplicate keys", "audit/audit_joins.py"),
    ("Natural-person screen", "data, docs, manifest and parser fixtures", 0, "0 natural persons",
     "audit/audit_pii.py; fixtures have representative and decision-maker cells redacted"),
    ("Exchange-price recoverability", "85 numeric columns (firm-year files and shares in issue); 7,140 ordered "
     "ratios a/b and 18,048 combinations (a - b)/c of won amounts over a share quantity", 0,
     "no exchange-origin price recoverable; the only implied price found is DPS / disclosed dividend "
     "yield, both issuer-disclosed", "audit/audit_price_leak.py"),
]

NARRATIVE = """# KOBEP-Core codebook, version 1.0

## 1. What the dataset is

KOBEP-Core is a relational dataset compiled from Korean statutory disclosures.
Its centre is the 5 % beneficial-ownership report (주식등의 대량보유상황보고서)
required by Article 147 of the Financial Investment Services and Capital Markets
Act: anyone who comes to hold 5 % or more of a listed company's voting
securities, or whose holding then changes by one percentage point or more, or
whose holding purpose changes, must file. KOBEP-Core turns every such filing on
a KOSPI company by a legal-person filer, 2011-2025, into a filing ledger, a
transaction ledger, blockholder entities, and issuer x blockholder relationships,
and joins them to the issuers' annual financials and shareholder payouts for
2016-2025.

Source: DART (dart.fss.or.kr), the Financial Supervisory Service's electronic
disclosure system, through the OpenDART API: `list.json` (filing index,
detail type D001), `document.xml` (filing text), the annual-report endpoints
for dividends, treasury shares and share counts, `fnlttSinglAcntAll` (full
financial statements) and `company.json` (company profile). Nothing comes from
a commercial database or from the exchange.

## 2. Scope decisions

- **Universe.** 883 companies listed on KOSPI at any time in 2016-2025 whose
  filings are in scope. Ledger rows from 2011-2015 are the pre-window history of
  these companies (658 of them have legal-person filings in those years), not a
  census of KOSPI then.
  `in_core_window` marks rows received 2016-2025.
- **Legal persons only.** Natural-person filers, and natural-person rows inside
  corporate filings, are excluded. A person is identified by a birth-date
  identifier (valid YYMMDD) under a non-corporate name, a Hangul personal-name
  form without a registration number, or a name the ledger knows to belong to an
  individual filer. Nothing is pseudonymised: a receipt number links back to
  the public filing, so masking would not de-identify.
- **No KRX-origin variables.** No exchange price, market value or return
  variable. Prices and yields stated in the disclosures themselves - the
  filer-stated `unit_price`, the issuer-stated dividend yield and buyback
  amounts - are kept as filed and flagged (`DART_DISCLOSED` in the dictionary;
  `unit_price_kind`).
- **Language.** Names of companies, funds and parties are kept as filed, in
  Korean, and are not translated or romanised: use `corp_code`, `reporter_id`
  and `rcept_no` as keys. Controlled values carry English beside the Korean:
  `method_en`, `report_name_en`, `industry_name_en` (official KSIC 11th-revision
  titles) and `security_class`; `corp_name_en` is the English name registered
  with DART. Identifier cells in which a filer wrote text such as 해당없음
  instead of a number are released blank.
- **No free text, no human verdicts.** Free-text fields name people; the holding
  purpose prose is released only as a derived category with its basis.
  No human adjudication of individual records is released.
- **No treatment labels.** `code/examples/make_treatment.py` shows how
  event-level indicators (for example, outside entries by holding purpose or
  acquisition route) can be built from these files. It is an example of use,
  not part of the data definition.
- **No ownership totals.** With natural persons and the ownership summary
  excluded, sums over the position ledger are legal-person holdings only.

## 3. How the files were built

**Parsing.** DART filing XML is code-driven: data cells carry `ACODE` and
controlled values carry `AUNIT`/`AUNITVALUE`. The parser reads codes, not
labels. Text up to 2020 is CP949 despite a UTF-8 declaration. Amended filings
contain pre- and post-amendment tables; values come from tables marked
`ACLASS="EXTRACTION"` (post-amendment).

**Entities.** Filers are resolved to reporting entities on their registration
number (business or foreign registration; for individuals a birth date -
individuals are then excluded). One entity keeps one registration number
throughout; its `name` is the name on its most recent filing. Entities are not
merged across registration numbers: a fund house filing under several foreign
registrations is several entities. `needs_review` flags entities whose names
and numbers do not map one-to-one (table in section 4). Organisations without
a registration number - mostly employee share ownership associations - often
filed under their representative's birth date; they are kept with
`id_kind = ID_WITHHELD` and no `id_value`. Related-party identifiers that read
as a birth date (YYMMDD) are withheld the same way, and a signatory's name
filed as part of an organisation's name ("... 우리사주조합장 <name>",
"(대표조합원 <name>)") is cut from it.

**Events.** One event per issuer x blockholder pair observed in 2016-2025.
Entry is the first filing with a ratio; exit is the start of the final run
below 5 %; a holder who dips below and returns has re-entered (`n_reentries`).
An exit that is never filed - a slide from 5.4 % to 4.9 % needs no report - is
censored, and `censoring_kind` separates holders still filing (last filing
within 12 months of the cutoff) from dormant ones and lapse candidates (no
filing for 36 months, last ratio below 5.5 %). Entry is left-truncated when an
earlier holding is evident (an earlier index filing whose text DART did not
serve, or a prior ratio already >= 5 %). Events are built only from filings
received up to 2025-12-31, which is also the observation cutoff, so every
event field can be recomputed from the released filing ledger.

**Classification.** `outsider_class` is a rule on the filer's declared relation
to the issuer (`relation_to_issuer_code`, FLT_CRP_RLT):

| Code | Declared relation | outsider_class |
|---|---|---|
| 13 | Shareholder | OUTSIDER |
| 01 | Registered officer | INSIDER |
| 03 | De facto controlling shareholder | INSIDER |
| 04 | Unregistered officer (form 6.0) | INSIDER |
| 10 | Largest shareholder | INSIDER |
| 14 | Affiliated company | INSIDER |
| 15 | Officer of an affiliated company | INSIDER |
| 02 | Major shareholder (>= 10 %) | UNCERTAIN - can be an outside institution |
| 16 | Other | UNCERTAIN |
| blank | - | UNCERTAIN |

UNCERTAIN is not guessed.

**Amendments.** `is_amendment` marks a filing that is itself an amendment
(index: the title carries 정정; position ledger: the filing text says so). An
original that was later corrected is 0. Values are read from the
post-amendment tables (`ACLASS="EXTRACTION"`).

**Acquisition flags.** `market_purchase` and `involuntary` are computed from the
released transaction rows of the filing (method lists in the dictionary).

**Holding purpose.** The coded purpose (01 influence, 02 passive, 03 general)
exists on the short form from version 3.9 (2020) and on the standard form only
from 4.0 (late 2022). `holding_purpose_code_derived` uses the code where filed;
before that, a short form implies 02 (it was available only to holders without
an influence purpose), and a standard form's purpose prose is classified by
rules. `holding_purpose_basis` says which.

**Payout.** Cash dividends come from the annual report's dividend section; a
section with neither a total nor a per-share figure is an inferred zero
(`div_basis = INFERRED_ZERO`). Buyback amounts are what the company reported:
the cash-flow statement, else the equity statement (lines naming an
acquisition only), else the buyback execution reports. A statement amount is
used only when the treasury-share table shows the parent buying in the market
(directly or through a trust); consolidated amounts without such purchases are
subsidiaries' buybacks or appraisal-right purchases and count as zero payout;
where the separate cash-flow statement shows a purchase but the treasury table
shows none, the amount is missing (`NA_SOURCE_CONFLICT`).

**Prices.** `unit_price` is read only when the cell holds exactly one
well-formed number; cells with two figures ("8,190/6,000") are missing.
`unit_price_kind` says what the number is: EXECUTED_KRW_PER_SHARE on TRADE
rows; REFERENCE_KRW_PER_SHARE on an exercise-price adjustment, a
debt-to-equity swap or another non-trade row; DR_UNIT_UNCONFIRMED on
depositary receipts, whose filings do not state the unit.

## 4. Files
"""

TAIL = """
## 6. Validation

Aggregates are in `docs/kobep_validation_summary.csv`. The spot-check drew
stratified samples from the release files themselves (filings by receipt-year
band and form; transactions by `flow_kind` and period; events by class and
truncation). A language model compared every sampled field with the original
filing; a person then judged every sampled field against the original, the
items the model flagged first. The first pass found a systematic defect - decimal
prices read as integers - which was corrected in 30,960 rows (2.7 % of priced
rows) before the scores below were taken.

{validation}

## 7. Limitations

- Holdings below 5 % are not observed; campaigns that never cross the threshold
  are absent.
- Exits below 5 % within one percentage point are never filed and are censored.
- Natural-person blockholders are absent; the relationships in this release are
  those of companies, funds and institutions.
- The 2011-2015 ledger covers the 2016-2025 panel companies only (survivorship).
- Firm-year files start in 2016; 2011-2014 ledger rows have no firm-year covariates.
- 270 filings in the index have no text at DART; they are listed but not parsed.
- Entities are reporting entities on registration numbers, not economic groups.
- Firm-year coverage is below one row per firm-year where DART has no annual
  report or statements for the year (`docs/kobep_coverage_by_year.csv`); the
  76 firms delisted before the exchange roster have no listing date, and their
  financial and holding-company flags are set by rule from the KSIC code
  (`firm_flag_basis = KSIC_RULE`).
- Treasury-share amounts reached through a trust lag the share counts.
- Financial statements of five companies are in USD or HKD (`currency`); do not
  pool them with won amounts. Growth rates across a currency change are blank.
- No market or exchange variable is included. To join one, use `stock_code`
  for the year from `kobep_firm_master.csv` (codes change) and check
  `delisting_date` and `is_partial_year`.
- `class_at_entry` reflects the filer's declared relation, not a judgement of
  who the holder is; a third-party acquirer and a fund both declare 'shareholder'.
"""


def coverage(data: str) -> pd.DataFrame:
    """Rows per year: filings and events by receipt/entry year; firm-years by
    fiscal year."""
    rd = lambda f, cols: pd.read_csv(os.path.join(data, f), dtype=str, usecols=cols)  # noqa: E731
    idx = rd("kobep_filing_index.csv", ["receipt_date", "parsed"])
    ev = rd("kobep_event_ledger.csv", ["entry_receipt_date"])
    fm = rd("kobep_firm_master.csv", ["corp_code", "fiscal_year"])
    fin = rd("kobep_firmyear_financial.csv", ["corp_code", "fiscal_year"])
    pay = rd("kobep_firmyear_payout.csv", ["corp_code", "fiscal_year"])
    years = range(2011, 2026)
    by = lambda s: s.value_counts().reindex([str(y) for y in years], fill_value=0)  # noqa: E731
    out = pd.DataFrame({
        "year": list(years),
        "filings_indexed": by(idx.receipt_date.str[:4]).values,
        "filings_parsed": by(idx.loc[idx.parsed == "1", "receipt_date"].str[:4]).values,
        "events_entered": by(ev.entry_receipt_date.str[:4]).values,
        "firm_master_firms": by(fm.fiscal_year).values,
        "financial_firm_years": by(fin.fiscal_year).values,
        "payout_firm_years": by(pay.fiscal_year).values,
    })
    return out


def fmt(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.0")
    args = ap.parse_args()
    docs = os.path.join(args.release, "docs")
    d = pd.read_csv(os.path.join(docs, "kobep_variable_dictionary.csv"), dtype=str).fillna("")
    mr = pd.read_csv(os.path.join(args.release, "data", "kobep_missing_reasons.csv"), dtype=str)
    rep = json.load(open(os.path.join(args.release, "manifest", "extract_report.json"), encoding="utf-8"))

    with open(os.path.join(docs, "kobep_validation_summary.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["check", "scope", "n", "result", "note"])
        w.writerows(VALIDATION)

    parts = [NARRATIVE]
    for f, g in d.groupby("file", sort=True):
        parts.append(f"\n### `{f}` - {rep['rows'].get(f, len(g)):,} rows\n\n"
                     "| Variable | Label | Unit | Source | Note |\n|---|---|---|---|---|")
        for r in g.itertuples():
            note = r.note + (f" Codes: {r.codes}" if r.codes else "")
            parts.append(f"| `{r.variable}` | {r.label_en} | {r.unit} | {r.source_origin} | {note.strip()} |")
    ent = pd.read_csv(os.path.join(args.release, "data", "kobep_blockholder_entity.csv"),
                      dtype=str).fillna("")
    reasons = ent.loc[ent.needs_review == "1", "review_reason"].str.split(";").explode()
    reasons = reasons.str.replace(r":.*", "", regex=True).value_counts()
    meaning = {"ID_SPANS_NAMES": "one registration number filed under unrelated names",
               "NAME_SPANS_IDS": "one name filed under several registration numbers",
               "MIXED_ENTITY_TYPE": "filer type code differs between filings",
               "MOJIBAKE_NAME": "a name variant is unreadable (encoding)",
               "NO_NAME": "no name on any filing",
               "NO_IDENTIFIER": "no registration number on any filing"}
    parts.append(f"\n### Entity review flags\n\n{int((ent.needs_review == '1').sum()):,} of "
                 f"{len(ent):,} entities carry `needs_review = 1`. An entity can carry several "
                 "reasons.\n\n| Reason | Meaning | Entities |\n|---|---|---:|")
    for k, v in reasons.items():
        parts.append(f"| {k} | {meaning.get(k, '')} | {v:,} |")
    cov = coverage(os.path.join(args.release, "data"))
    cov.to_csv(os.path.join(docs, "kobep_coverage_by_year.csv"), index=False, lineterminator="\n")
    parts.append("\n### Coverage by year\n\n`docs/kobep_coverage_by_year.csv`:\n\n"
                 + cov.to_markdown(index=False))
    parts.append("\n## 5. Missing values\n\nEvery blank cell is covered by one rule below "
                 "(`kobep_missing_reasons.csv`).\n\n| File | Variable | Code | Rule | Cells |\n|---|---|---|---|---:|")
    for r in mr.itertuples():
        parts.append(f"| {r.file} | `{r.variable}` | {r.reason_code} | {r.rule} | {int(r.n_cells):,} |")
    vt = "| Check | Scope | n | Result | Note |\n|---|---|---:|---|---|\n" + "\n".join(
        f"| {a} | {b} | {c:,} | {dd} | {e} |" for a, b, c, dd, e in VALIDATION)
    parts.append(TAIL.format(validation=vt))
    path = os.path.join(docs, "KOBEP_codebook_v1.0.md")
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(parts))
    print(f"-> {path}  ({sum(len(p) for p in parts):,} chars)")


if __name__ == "__main__":
    main()
