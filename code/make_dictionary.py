#!/usr/bin/env python3
"""Write docs/kobep_variable_dictionary.csv from the release files.

Labels, units and provenance are written here by hand, from the builder
scripts that compute each column; counts, types and code lists are measured
from the files, so they cannot drift from what is published. A release column
without a label fails the run.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

D, DER, DISC = "DART", "derived", "DART_DISCLOSED"
#: Keys and codes that look numeric but must be read as text: leading zeros
#: matter (corp_code 00100939) and receipt numbers exceed float precision.
#: `code/read_kobep.py` applies the same list.
IDENTIFIERS = {"corp_code", "rcept_no", "entry_rcept_no", "superseded_by", "stock_code", "ksic_code",
               "party_id", "id_value", "reporter_id", "event_id"}
CRP_TP = ("I domestic corporation; K financial institution; Y pension fund or "
          "professional investor; A investment company etc.; N other organisation "
          "(domestic); U other organisation (foreign); O foreign corporation; "
          "C civil-code partnership; W statutory partnership")
# (label, unit, source, note)
COMMON = {
    "corp_code": ("DART issuer identifier (8 digits)", "", D, "join key across files"),
    "fiscal_year": ("Fiscal year of the annual report", "year", D, ""),
    "rcept_no": ("DART receipt number of the 5 % filing", "", D,
                 "opens the original at dart.fss.or.kr/dsaf001/main.do?rcpNo="),
    "reporter_id": ("KOBEP blockholder entity identifier", "", DER, "see blockholder_entity"),
    "in_core_window": ("1 if received 2016-01-01 to 2025-12-31", "0/1", DER,
                       "0 = pre-window history 2011-2015 of panel firms"),
    "receipt_date": ("Date DART received the filing", "date", D, ""),
    "row_no": ("Row position within the filing's table", "", DER, ""),
}
LABELS = {
 "kobep_filing_index.csv": {
  "form_kind": ("standard or short (약식, professional investors) form", "", D, ""),
  "is_amendment": ("1 if the filing is itself an amendment (title carries 정정)", "0/1", DER,
                   "an original that was later corrected is 0"),
  "parsed": ("1 if the filing text was retrieved and parsed", "0/1", DER,
             "0 = DART did not serve the text (status 014)"),
  "report_name_ko": ("Report title as listed by DART", "text (ko)", D, ""),
  "report_name_en": ("English rendering of report_name_ko", "text", DER,
                     "standard or short form; [Amendment] for 기재정정")},
 "kobep_filing_entity.csv": {},
 "kobep_blockholder_entity.csv": {
  "id_kind": ("Kind of identifier the entity is keyed on", "code", DER,
              "BRN business registration number; FOREIGN_REG foreign registration; "
              "NAME_ONLY no identifier filed; ID_WITHHELD an organisation filed under a "
              "person's birth date, which is not released"),
  "id_value": ("Business registration or foreign registration number", "", D, ""),
  "name": ("Entity name as filed on its most recent filing", "text", D,
           "trade names change; one registration number throughout"),
  "name_first_filed": ("Entity name as filed on its earliest filing", "text", D, ""),
  "name_variants_json": ("Names filed in the filing text", "JSON list", D, "person names removed"),
  "index_names_json": ("Names shown on the DART filing index", "JSON list", D, "person names removed"),
  "entity_type": ("Filer type as declared (CRP_TP)", "text", D, ""),
  "entity_type_code": ("Filer type code (CRP_TP)", "code", D, CRP_TP),
  "entity_type_mixed": ("1 if the entity filed under more than one type", "0/1", DER, ""),
  "nationality": ("Domestic or foreign, from the declared type", "code", DER, ""),
  "is_nps": ("1 for the National Pension Service", "0/1", DER, ""),
  "needs_review": ("1 if entity resolution is flagged for review", "0/1", DER, ""),
  "review_reason": ("Why the entity is flagged", "text", DER, "")},
 "kobep_position_ledger.csv": {
  "form_version": ("DART form version (FORMULA-VERSION)", "", D, "2.2-6.0"),
  "form_kind": ("standard or short form", "", D, ""),
  "is_amendment": ("1 if the filing text marks itself an amendment", "0/1", D,
                   "values are read from the post-amendment tables (ACLASS=EXTRACTION)"),
  "superseded_by": ("rcept_no of the later amendment that replaces this filing", "rcept_no", DER,
                    "set: same reporter_id, corp_code and obligation_date; every filing received "
                    "before the set's latest amendment points to it. Before summing quantities or "
                    "amounts, drop rows with superseded_by filled (v1.1)"),
  "obligation_date": ("Date the reporting duty arose (RPT_RSP_DT)", "date", D, ""),
  "base_date": ("As-of date of the reported holding (RPT_REF_DT)", "date", D, ""),
  "prev_report_date": ("Date of the filer's previous report", "date", D, ""),
  "filer_type_code": ("Filer type code (CRP_TP)", "code", D, CRP_TP),
  "relation_to_issuer_code": ("Filer's relation to the issuer (FLT_CRP_RLT)", "code", D,
                              "01 officer, 02 major shareholder, 03 de facto controller, "
                              "04 unregistered officer, 10 largest shareholder, 13 shareholder, "
                              "14 affiliate, 15 affiliate officer, 16 other"),
  "outsider_class": ("INSIDER / OUTSIDER / UNCERTAIN from the relation code", "code", DER,
                     "OUTSIDER: 13; INSIDER: 01, 03, 04, 10, 14, 15; UNCERTAIN: 02 (a >=10 % "
                     "holder may be an outside institution), 16, blank"),
  "prev_ratio_stockequiv": ("Holding ratio in the previous report, stock-equivalent basis", "%", D,
                            "filer and related parties combined, as filed"),
  "curr_ratio_stockequiv": ("Holding ratio in this report, stock-equivalent basis", "%", D,
                            "filer and related parties combined, as filed (SUM_TMT_RT); not recomputed "
                            "after natural-person rows were removed, so it can include related natural "
                            "persons' shares; the 5 % threshold is defined on this basis"),
  "prev_ratio_voting": ("Previous holding ratio, voting-share basis", "%", D, "form 4.2+"),
  "curr_ratio_voting": ("Current holding ratio, voting-share basis", "%", D, "form 4.2+"),
  "report_type_code": ("1 new, 2 change in holdings, 3 change in terms, 4 both", "code", D, ""),
  "holding_purpose_code": ("01 influence over management, 02 passive, 03 general investment",
                           "code", D,
                           "coded from short form 3.9 (2020) and standard form 4.0 (late 2022)"),
  "involuntary": ("1 if a released transaction row of the filing is a non-purchase "
                  "acquisition", "0/1", DER,
                  "method_ko in 수증(+), 합병(+), 상속(+), 주식매수선택권행사(+), 출자전환, "
                  "대물변제수령(+), 무상신주취득(+), 주식배당(+), 계열사편입(+)"),
  "market_purchase": ("1 if a released transaction row of the filing is an on-exchange "
                      "purchase", "0/1", DER, "method_ko in 장내매수(+), 시간외매매(+)"),
  "joint_filing": ("1 for a joint (연명) report", "0/1", D, ""),
  "total_shares_issued": ("Issuer's shares in issue stated in the filing", "shares", D, ""),
  "holding_purpose_code_derived": ("Holding purpose 01/02/03: the code where filed, else derived",
                                   "code", DER, "see holding_purpose_basis; derived values are "
                                   "rule-based (98.6 % agreement on released coded filings with text)"),
  "holding_purpose_basis": ("How the purpose was obtained", "code", DER,
                            "CODED / FORM_ELIGIBILITY (pre-code short form = 02) / TEXT_RULE / "
                            "FORM_COVER (standard-form cover names the influence purpose, prose "
                            "settles nothing = 01; 99.3 % of covered coded filings are 01) / "
                            "PRIOR_FILING (still unclassified: the same holder's latest earlier "
                            "CODED, TEXT_RULE or FORM_COVER category on the issuer; not after a "
                            "short form) / UNCLASSIFIED / NO_TEXT")},
 "kobep_transaction_ledger.csv": {
  "party_name": ("Party whose holding moved (filer or related party)", "text", D,
                 "legal persons only"),
  "party_id": ("Party's registration number", "", D,
               "six-digit values reading as a birth date are withheld"),
  "change_date": ("Date of the movement", "date", D, ""),
  "method_ko": ("Method of acquisition or disposal as filed (HLD_MTH)", "text (ko)", D,
                "e.g. 장내매수(+) on-market purchase; see vocabulary"),
  "direction": ("+1 acquisition, -1 disposal", "", DER, "from the method's sign"),
  "security_ko": ("Security class as filed", "text (ko)", D, ""),
  "security_class": ("Standardised security class", "code", DER, "see security_class"),
  "shares_before": ("Holding before the movement", "shares", D, ""),
  "shares_change": ("Size of the movement", "shares", D, ""),
  "shares_after": ("Holding after the movement", "shares", D, ""),
  "unit_price": ("Price per unit as stated by the filer", "see unit_price_kind", DISC,
                 "a filer-stated price, not an exchange quote"),
  "price_source": ("DART_DISCLOSED when unit_price is present", "code", DER, ""),
  "method_en": ("English gloss of method_ko", "text", DER,
                "same table as docs/kobep_vocabulary.csv"),
  "unit_price_kind": ("What unit_price is on this row", "code", DER,
                      "EXECUTED_KRW_PER_SHARE (flow_kind TRADE); REFERENCE_KRW_PER_SHARE "
                      "(exercise-price adjustment, swap and other non-trade rows); "
                      "DR_UNIT_UNCONFIRMED (depositary receipts; unit not stated)"),
  "flow_kind": ("Economic kind of the movement", "code", DER,
                "TRADE cash trade; OTHER unspecified; NON_CASH bonus/split/merger; "
                "PERIMETER related-party perimeter change; LENDING; DERIVATIVE; UNKNOWN")},
 "kobep_terms_event.csv": {
  "party_name": ("Party named in the terms-change row", "text", D, ""),
  "party_id": ("Party's registration number", "", D,
               "six-digit values reading as a birth date are withheld"),
  "event_date": ("Date of the change in terms", "date", D, ""),
  "method_ko": ("Coded method in the terms table", "text (ko)", D, ""),
  "security_ko": ("Security class as filed", "text (ko)", D, ""),
  "security_class": ("Standardised security class", "code", DER, ""),
  "unit_price": ("Price stated in the terms row", "KRW", DISC, ""),
  "price_source": ("DART_DISCLOSED when unit_price is present", "code", DER, ""),
  "method_en": ("English gloss of method_ko", "text", DER, "")},
 "kobep_security_class.csv": {
  "security_ko": ("Security label as it appears in the tables", "text (ko)", D, ""),
  "security_class": ("Standardised class", "code", DER, "")},
}
EVENT = {
 "event_id": ("Event identifier, one per (issuer, blockholder) relationship", "", DER, ""),
 "n_filings": ("Filings in the relationship", "count", DER, ""),
 "entry_rcept_no": ("Receipt number of the entry filing", "", D, ""),
 "entry_obligation_date": ("Obligation date of the entry filing", "date", D, ""),
 "entry_base_date": ("As-of date of the entry filing", "date", D, ""),
 "entry_receipt_date": ("Receipt date of the entry filing", "date", D, ""),
 "entry_fy": ("Year of entry_obligation_date", "year", DER, "see entry_filed_late"),
 "entry_ratio": ("Holding ratio at entry", "%", D, "stock-equivalent"),
 "prev_ratio": ("Prior ratio stated on the entry filing", "%", D, ""),
 "entry_report_type": ("Report type of the entry filing", "", D, ""),
 "prior_index_filings": ("Earlier index filings by the pair whose text was never parsed", "count", DER, ""),
 "entry_prev_ratio_ge5": ("1 if the entry filing's prior ratio is already >= 5 %", "0/1", DER, ""),
 "entry_left_truncated": ("1 if an earlier holding is evident", "0/1", DER,
                          "prior_index_filings > 0 or entry_prev_ratio_ge5 = 1"),
 "is_first_ever": ("1 if a new report with no sign of earlier holding", "0/1", DER, ""),
 "is_marginal_entry": ("1 if entry ratio is 5.0-5.3 %", "0/1", DER,
                       "exit least observable: a fall below 5 % may need no report"),
 "peak_ratio": ("Highest ratio in the relationship", "%", DER, ""),
 "peak_date": ("Obligation date of the peak", "date", DER, ""),
 "last_observed_ratio": ("Ratio on the last filing", "%", DER, ""),
 "last_obligation_date": ("Obligation date of the last filing", "date", DER, ""),
 "exit_date": ("Obligation date of the first filing in the final run below 5 %", "date", DER,
               "blank when exit_censored = 1"),
 "exit_type": ("OBSERVED_BELOW_THRESHOLD or CENSORED_NO_FILING", "code", DER,
               "a sub-1pp slide below 5 % is never filed"),
 "exit_censored": ("1 if no exit is observed", "0/1", DER, "observed through 2025-12-31, the last receipt date in the ledger"),
 "censoring_kind": ("STILL_HOLDING / DORMANT / LAPSE_CANDIDATE", "code", DER, ""),
 "duration_days": ("Days from entry to exit or last filing", "days", DER, ""),
 "n_reentries": ("Times the holder crossed back above 5 %", "count", DER, ""),
 "purpose_at_entry": ("Holding-purpose code on the entry filing", "code", D,
                      "short form 3.9+ / standard form 4.0+"),
 "purpose_changed": ("1 if the purpose code changed", "0/1", DER, ""),
 "class_at_entry": ("Outsider class at entry", "code", DER, "rule-based; no human verdicts"),
 "class_last": ("Outsider class on the last filing", "code", DER, ""),
 "class_changed": ("1 if the class changed", "0/1", DER, ""),
 "transition_date": ("Obligation date of the first class change", "date", DER, ""),
 "is_related_party": ("1 insider, 0 outsider at entry", "0/1", DER, ""),
 "joint_at_entry": ("1 if the entry filing was joint", "0/1", D, ""),
 "unattributable": ("1 if the filer block never parsed", "0/1", DER, ""),
 "entry_before_window": ("1 if the entry was received before 2016", "0/1", DER, ""),
 "entry_filing_lag_days": ("Receipt date minus obligation date of the entry", "days", DER, ""),
 "purpose_at_entry_derived": ("Holding purpose at entry, coded or derived", "code", DER,
                              "as holding_purpose_code_derived on the entry filing"),
 "purpose_at_entry_basis": ("How purpose_at_entry_derived was obtained", "code", DER, ""),
 "entry_filed_late": ("1 if entry_filing_lag_days > 120", "0/1", DER,
                      "conservative data-quality flag, not a legal determination of late filing"),
 "entry_rep_change": ("1 if the entry filing reports a change of the joint group's "
                      "representative filer", "0/1", DER,
                      "read from the filing's report reason; the group held the shares before, "
                      "so the entry is not a new holding. Blank if the filing has no reason cell"),
 "entry_left_truncated_broad": ("1 if entry_left_truncated = 1 or entry_rep_change = 1",
                                "0/1", DER, "entry_left_truncated and is_first_ever keep the "
                                "narrow definition"),
}
FIRM = {
 "stock_code": ("KRX stock code in that year", "", D, ""),
 "corp_name_ko": ("Company name (Korean)", "text (ko)", D, ""),
 "corp_name_en": ("Company name (English, as registered with DART)", "text", D, ""),
 "market": ("Market", "code", D, "KOSPI"),
 "is_listed": ("1 if listed in that year", "0/1", DER, "annual-report basis"),
 "is_spv": ("1 for special-purpose vehicles", "0/1", DER, ""),
 "is_financial": ("1 for financial firms", "0/1", DER, "see firm_flag_basis"),
 "is_holding": ("1 for holding companies", "0/1", DER, "see firm_flag_basis"),
 "delisting_date": ("Delisting date", "date", D, ""),
 "is_partial_year": ("1 if listed for part of the year", "0/1", DER, ""),
 "ksic_code": ("Korean Standard Industrial Classification code", "code", D, ""),
 "industry_name_ko": ("KSIC 11th-revision title of ksic_code (Korean)", "text (ko)", D,
                      "Statistics Korea classification; code reported in DART company.json"),
 "industry_name_en": ("KSIC 11th-revision title of ksic_code (English)", "text", D,
                      "official English title"),
 "fiscal_month": ("Fiscal year-end month", "month", D, ""),
 "listing_date": ("Listing date", "date", D, ""),
 "established_date": ("Date of incorporation", "date", D, ""),
 "origin_kind": ("LONG_LISTED / IPO / SPINOFF / UNKNOWN", "code", DER, ""),
 "firm_flag_basis": ("Source of is_financial and is_holding", "code", DER,
                     "ROSTER exchange roster; KSIC_RULE from ksic_code for firms delisted before "
                     "the roster (holding: 64992; financial: divisions 64-66 other than holding)"),
}
FIN_LEVEL = "KRW (or `currency`)"
FIN = {
 "fs_basis": ("CFS consolidated or OFS separate, chosen per firm-year", "code", D, "consolidated first"),
 "fs_basis_changed": ("1 if the basis differs from the prior year", "0/1", DER, ""),
 "n_items": ("Core accounts resolved (of 33)", "count", DER, ""),
 "currency": ("Reporting currency", "code", D, "USD/HKD for 5 firms - filter before pooling"),
 "unit_suspect": ("1 if assets jump ~1,000-fold from the prior year", "0/1", DER, "flagged, not corrected"),
 "signed_magnitudes": ("Magnitude accounts filed with a sign", "count", DER, "absolute values used"),
 "roa": ("profit / assets", "ratio", DER, ""),
 "roe": ("profit / equity (equity > 0)", "ratio", DER, ""),
 "op_margin": ("operating_profit / revenue (revenue > 0)", "ratio", DER, ""),
 "net_margin": ("profit / revenue (revenue > 0)", "ratio", DER, ""),
 "cfo_assets": ("cfo / assets", "ratio", DER, ""),
 "effective_tax_rate": ("tax_expense / pretax_profit (pretax > 0)", "ratio", DER, ""),
 "fcf": ("cfo - capex", FIN_LEVEL, DER, ""),
 "fcf_assets": ("fcf / assets", "ratio", DER, ""),
 "capex_assets": ("capex / assets", "ratio", DER, ""),
 "debt_equity": ("liabilities / equity (equity > 0)", "ratio", DER, ""),
 "liabilities_assets": ("liabilities / assets", "ratio", DER, ""),
 "current_ratio": ("current_assets / current_liabilities", "ratio", DER, ""),
 "interest_coverage": ("operating_profit / finance_costs", "ratio", DER, ""),
 "size": ("ln(assets)", "ln of reporting-currency amount", DER, "see currency"),
 "ppe_assets": ("ppe / assets", "ratio", DER, ""),
 "invrec_assets": ("(inventories + receivables) / assets", "ratio", DER, ""),
 "cash_assets": ("cash / assets", "ratio", DER, ""),
 "re_te": ("retained_earnings / equity (equity > 0)", "ratio", DER, ""),
 "firm_age": ("fiscal_year - year of incorporation", "years", DER, ""),
 "revenue_growth": ("revenue growth over the prior year, same currency", "ratio", DER, ""),
 "assets_growth": ("asset growth over the prior year, same currency", "ratio", DER, ""),
}
FIN_LEVELS = ["assets", "liabilities", "equity", "equity_parent", "current_assets",
              "noncurrent_assets", "current_liabilities", "noncurrent_liabilities", "cash",
              "retained_earnings", "issued_capital", "ppe", "inventories", "receivables",
              "intangibles", "revenue", "operating_profit", "profit", "profit_parent",
              "cost_of_sales", "sga", "pretax_profit", "tax_expense", "finance_costs",
              "cfo", "cfi", "cff", "capex", "dividends_paid", "interest_paid", "tax_paid"]
for lv in FIN_LEVELS:
    FIN[lv] = (f"{lv.replace('_', ' ')} (annual statements, fs_basis)", FIN_LEVEL, D, "")
FIN["eps_basic"] = ("Basic earnings per share", "KRW per share", D, "")
PAY = {
 "div_cash_total": ("Cash dividends declared", "KRW", D, "alotMatter"),
 "div_basis": ("REPORTED / INFERRED_ZERO / TOTAL_NOT_DISCLOSED / MISSING", "code", DER,
               "INFERRED_ZERO = dividend section filed with no total and no DPS; "
               "TOTAL_NOT_DISCLOSED = DPS filed, total blank or in the wrong unit"),
 "dps": ("Cash dividend per share", "KRW", D, ""),
 "payout_ratio_disclosed": ("Payout ratio as disclosed", "%", D, ""),
 "div_yield_disclosed": ("Dividend yield as disclosed", "%", DISC,
                         "computed by the filer on a reference price"),
 "div_stock_total": ("Stock dividends", "KRW", D, ""),
 "disagree_flag": ("1 if the filer's repeated figures disagree >10x", "0/1", DER, ""),
 "treasury_acquired_qty": ("Treasury shares acquired in the year", "shares", D, ""),
 "treasury_acq_qty_direct": ("... of which direct purchases (직접취득)", "shares", D, ""),
 "treasury_acq_qty_trust": ("... of which via trust (신탁)", "shares", D,
                            "statement amounts lag trust purchases"),
 "treasury_acq_qty_other": ("... of which other (merger, odd lots, appraisal)", "shares", D, ""),
 "treasury_retired_qty": ("Treasury shares retired", "shares", D, ""),
 "treasury_disposed_qty": ("Treasury shares disposed", "shares", D, ""),
 "treasury_end_qty": ("Treasury shares held at year end", "shares", D, ""),
 "n_buyback_decisions": ("Buyback decision filings (B001) in the year", "count", D, ""),
 "n_trust_openings": ("Buyback trust contracts opened in the year", "count", D, ""),
 "buyback_value": ("Won paid for treasury shares", "KRW", DISC,
                   "cash-flow statement, else equity statement, else execution reports"),
 "buyback_value_basis": ("Source of buyback_value", "code", DER,
                         "CASHFLOW / EQUITY_STMT / EXECUTION_REPORT / NO_ACQUISITION / "
                         "NO_MARKET_ACQUISITION / NA_NOT_DISCLOSED / NA_SOURCE_CONFLICT; "
                         "statement amounts used only when the parent bought in the market"),
 "buyback_fs_div": ("OFS or CFS statement used", "code", D, "separate first"),
 "total_payout": ("div_cash_total + buyback_value", "KRW", DER, "no exchange price used"),
 "payout_basis": ("CASH_ONLY / CASH_PLUS_REPORTED_BUYBACK / NONE", "code", DER, ""),
 "div_dummy": ("1 if a cash dividend was paid", "0/1", DER, ""),
 "div_initiation": ("1 if div_dummy = 1 in t and 0 in t-1", "0/1", DER, "t-1 must be observed"),
 "div_omission": ("1 if div_dummy = 0 in t and 1 in t-1", "0/1", DER, "t-1 must be observed"),
 "div_increase": ("1 if div_cash_total in t exceeds a positive t-1 amount", "0/1", DER,
                  "t-1 must be observed"),
 "payout_ratio": ("total_payout / profit", "ratio", DER, ""),
 "payout_assets": ("total_payout / assets", "ratio", DER, ""),
 "payout_equity": ("total_payout / equity", "ratio", DER, ""),
 "payout_ocf": ("total_payout / cfo", "ratio", DER, ""),
 "div_assets": ("div_cash_total / assets", "ratio", DER, ""),
 "distributable_profit_ub": ("equity - issued_capital; upper bound of distributable profit",
                             "KRW", DER, "Commercial Act art. 462(1)"),
 "payout_capacity_used_lb": ("total_payout / distributable_profit_ub; lower bound", "ratio", DER, ""),
}
MISSING = {
 "file": ("Release file", "", DER, ""), "variable": ("Column", "", DER, ""),
 "reason_code": ("Why the cells are blank", "code", DER, "defined in the codebook, section 5"),
 "rule": ("Condition selecting the cells", "text", DER, ""),
 "n_cells": ("Blank cells covered by the rule", "count", DER, ""),
}
LABELS["kobep_event_ledger.csv"] = EVENT
LABELS["kobep_firm_master.csv"] = FIRM
LABELS["kobep_firmyear_financial.csv"] = FIN
LABELS["kobep_firmyear_payout.csv"] = PAY
LABELS["kobep_missing_reasons.csv"] = MISSING


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.1")
    args = ap.parse_args()
    data = os.path.join(args.release, "data")
    rows, unlabelled = [], []
    for f in sorted(os.listdir(data)):
        df = pd.read_csv(os.path.join(data, f), dtype=str, keep_default_na=False)
        for c in df.columns:
            spec = LABELS.get(f, {}).get(c) or COMMON.get(c)
            if spec is None:
                unlabelled.append(f"{f}.{c}")
                continue
            label, unit, source, note = spec
            s = df[c]
            filled = s[s != ""]
            numeric = pd.to_numeric(filled, errors="coerce")
            kind = ("empty" if not len(filled) else "string" if c in IDENTIFIERS
                    else "integer" if numeric.notna().all() and (numeric % 1 == 0).all()
                    else "number" if numeric.notna().all() else "string")
            codes = ""
            if unit in ("code", "0/1") and filled.nunique() <= 15:
                vc = filled.value_counts()
                codes = "; ".join(f"{k}={v}" for k, v in sorted(vc.items()))
            rows.append((f, c, label, unit, kind, source, len(df), int((s == "").sum()),
                         codes, note))
    if unlabelled:
        print("UNLABELLED:", unlabelled, file=sys.stderr)
        sys.exit(1)
    out = pd.DataFrame(rows, columns=["file", "variable", "label_en", "unit", "type",
                                      "source_origin", "n_rows", "n_blank", "codes", "note"])
    docs = os.path.join(args.release, "docs")
    os.makedirs(docs, exist_ok=True)
    dest = os.path.join(docs, "kobep_variable_dictionary.csv")
    out.to_csv(dest, index=False, lineterminator="\n")
    print(f"{len(out)} variables -> {dest}")
    print(out.groupby("source_origin").size().to_string())


if __name__ == "__main__":
    main()
