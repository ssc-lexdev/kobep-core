#!/usr/bin/env python3
"""Payout spot-check: a stratified sample of firm-years to judge against the annual reports.

The five percent filings were audited field by field (C11); the payout file was not.
This draws 40 firm-years with a fixed seed, stratified so that every source of the
repurchase amount and every exception is represented, and writes a sheet for a person
to judge three fields per firm-year against the original filings on DART:

  div_cash_total   cash dividends declared for the fiscal year (won), incl. INFERRED_ZERO
  buyback_value    won paid for treasury shares and the statement used (OFS before CFS),
                   with trust purchases counted and subsidiaries' purchases left out
  buyback_basis    the recorded source or blank reason (NO_ACQUISITION, NO_MARKET_ACQUISITION,
                   NA_NOT_DISCLOSED, NA_SOURCE_CONFLICT) is the right one

Verdicts: OK / WRONG / CANT_TELL in the human_* columns, reason in human_note.

    python make_payout_check.py [--release C:/KOBEP/release/KOBEP-Core_v1.0]
                                [--ledger C:/KOBEP/ledger.db] [--out <spotcheck dir>]
"""
from __future__ import annotations

import argparse
import os
import sqlite3

import pandas as pd

SEED = 20261026
# stratum -> (filter, n)
STRATA = [
    ("CASHFLOW", lambda d: d.buyback_value_basis == "CASHFLOW", 8),
    ("EQUITY_STMT", lambda d: d.buyback_value_basis == "EQUITY_STMT", 6),
    ("EXECUTION_REPORT", lambda d: d.buyback_value_basis == "EXECUTION_REPORT", 6),
    ("NA_SOURCE_CONFLICT", lambda d: d.buyback_value_basis == "NA_SOURCE_CONFLICT", 4),
    ("NA_NOT_DISCLOSED", lambda d: d.buyback_value_basis == "NA_NOT_DISCLOSED", 3),
    ("NO_MARKET_ACQUISITION", lambda d: d.buyback_value_basis == "NO_MARKET_ACQUISITION", 4),
    ("TRUST", lambda d: (d.buyback_value_basis == "CASHFLOW") & (pd.to_numeric(d.treasury_acq_qty_trust, errors="coerce") > 0), 3),
    ("DIV_INFERRED_ZERO", lambda d: d.div_basis == "INFERRED_ZERO", 6),
]
DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


def won(v) -> str:
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return ""


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.0")
    ap.add_argument("--ledger", default=r"C:\KOBEP\ledger.db")
    ap.add_argument("--out", default=os.path.join(here, "..", "..", "deliverables", "spotcheck"))
    a = ap.parse_args()

    po = pd.read_csv(os.path.join(a.release, "data", "kobep_firmyear_payout.csv"), dtype=str)
    fm = pd.read_csv(os.path.join(a.release, "data", "kobep_firm_master.csv"), dtype=str,
                     usecols=["corp_code", "fiscal_year", "stock_code", "corp_name_ko", "corp_name_en"])
    taken, rows = set(), []
    for name, f, n in STRATA:
        pool = po[f(po) & ~(po.corp_code + po.fiscal_year).isin(taken)]
        s = pool.sample(n=min(n, len(pool)), random_state=SEED)
        taken |= set(s.corp_code + s.fiscal_year)
        rows.append(s.assign(stratum=name))
    s = pd.concat(rows).merge(fm, on=["corp_code", "fiscal_year"], how="left")

    con = sqlite3.connect(f"file:{a.ledger}?mode=ro", uri=True)
    q = lambda sql, p: [r[0] for r in con.execute(sql, p)]
    out = []
    for r in s.itertuples():
        y = int(r.fiscal_year)
        ann = q("select distinct rcept_no from dividend_item where corp_code=? and bsns_year=? "
                "union select distinct rcept_no from treasury_holding where corp_code=? and bsns_year=? "
                "union select distinct rcept_no from financial_item where corp_code=? and bsns_year=? "
                "and reprt_code='11011'", (r.corp_code, y, r.corp_code, y, r.corp_code, y))
        exe = q("select distinct rcept_no from buyback_execution where corp_code=? "
                "and substr(trade_date,1,4)=?", (r.corp_code, str(y)))
        out.append({
            "stratum": r.stratum, "corp_code": r.corp_code, "stock_code": r.stock_code,
            "corp_name_ko": r.corp_name_ko, "corp_name_en": r.corp_name_en, "fiscal_year": r.fiscal_year,
            "annual_report": "; ".join(DART + x for x in sorted(ann)),
            "execution_reports": "; ".join(DART + x for x in sorted(exe)[:6]),
            "div_cash_total": won(r.div_cash_total), "div_basis": r.div_basis, "dps": r.dps,
            "buyback_value": won(r.buyback_value), "buyback_value_basis": r.buyback_value_basis,
            "buyback_fs_div": r.buyback_fs_div if isinstance(r.buyback_fs_div, str) else "",
            "treasury_acquired_qty": r.treasury_acquired_qty, "acq_direct": r.treasury_acq_qty_direct,
            "acq_trust": r.treasury_acq_qty_trust, "acq_other": r.treasury_acq_qty_other,
            "n_buyback_decisions": r.n_buyback_decisions,
            "human_div": "", "human_buyback": "", "human_basis": "", "human_note": "",
        })
    df = pd.DataFrame(out)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "spotcheck_payout.xlsx")
    readme = pd.DataFrame({"README": [
        "Payout spot-check: 40 firm-years (seed 20261026), stratified by source of the repurchase amount and by exception.",
        "For each row open the annual report (사업보고서) for the fiscal year; for EXECUTION_REPORT rows also the execution reports.",
        "human_div: is div_cash_total the cash dividend declared for this fiscal year (배당에 관한 사항, 현금배당금총액)? "
        "For INFERRED_ZERO, is it true that no cash dividend was declared?",
        "human_buyback: is buyback_value the amount paid for the parent's market purchases of treasury shares (incl. via trust), "
        "from the separate statement first (cash-flow statement, else statement of changes in equity, else execution reports)? "
        "Blank where the basis is NA_*; 0 where NO_*.",
        "human_basis: is buyback_value_basis the right source or blank reason?",
        "Verdicts: OK / WRONG / CANT_TELL. Put the correct value or the reason in human_note.",
        "Units: amounts are in won (not thousands or millions).",
    ]})
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        readme.to_excel(w, sheet_name="README", index=False)
        df.to_excel(w, sheet_name="payout", index=False)
    print(path, len(df), "firm-years,", 3 * len(df), "fields")
    print(df.stratum.value_counts().to_string())


if __name__ == "__main__":
    main()
