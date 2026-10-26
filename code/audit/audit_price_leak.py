#!/usr/bin/env python3
"""Audit: can a KRX share price be recovered from combinations of release columns?

The release carries no exchange price (decision D16). Dropping the price
columns is not enough: in August 2026 the payout file was found to recover the
mean annual close exactly through `total_payout - div_cash_total` divided by a
share count, although no price column was present. Leaks live in combinations,
so this audit searches combinations.

Search space - every numeric column of the firm-year files plus the shares in
issue (from the position ledger) and:
  a / b              for all ordered pairs
  (a - b) / c        for a, b amounts in won and c a share quantity
Each candidate is compared with the internal KRX year-end close and annual mean
close (the audit needs the internal ledger; it is not part of the public
reproduction path). A constant multiplier is allowed for (per-cent units,
thousands), so the test is on the spread of log(candidate / price) after
removing its median, not on the level.

Classification. Korean statutory filings themselves state prices: the dividend
yield is computed on a reference price, and a buyback amount divided by the
shares bought is an average purchase price. Paths built from those
DART-disclosed columns are reported as DART_DISCLOSED and allowed (D16 as
revised 2026-09-28: the test is the source, not invertibility). Any other path
that tracks the KRX price is a KRX_ORIGIN leak and fails the audit.

Exit status 1 if any KRX_ORIGIN path is found.
"""
from __future__ import annotations

import argparse
import itertools
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

TIGHT = np.log(1.02)        # within 2 % after removing the median offset
FLAG_SHARE = 0.20           # a path matching 20 % of firm-years is a leak
FLAG_CORR = 0.95            # or one whose log tracks the price this closely
MIN_N = 200

#: Columns whose values are prices, or amounts that divide into a price, as
#: stated by the filer in a DART disclosure.
DART_PRICE_BEARING = {"div_yield_disclosed", "buyback_value"}
QUANTITY = {"treasury_acquired_qty", "treasury_acq_qty_direct", "treasury_acq_qty_trust",
            "treasury_acq_qty_other", "treasury_retired_qty", "treasury_disposed_qty",
            "treasury_end_qty", "shares_issued"}
AMOUNT_HINT = ("total", "value", "cash", "assets", "equity", "profit", "revenue",
               "liabilities", "capital", "paid", "cfo", "cfi", "cff", "capex", "fcf",
               "ppe", "inventories", "receivables", "intangibles", "earnings", "sga",
               "costs", "expense", "depreciation", "distributable")


def load(release: str, ledger: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = os.path.join(release, "data")
    fin = pd.read_csv(os.path.join(d, "kobep_firmyear_financial.csv"), dtype={"corp_code": str})
    pay = pd.read_csv(os.path.join(d, "kobep_firmyear_payout.csv"), dtype={"corp_code": str})
    pos = pd.read_csv(os.path.join(d, "kobep_position_ledger.csv"),
                      usecols=["corp_code", "receipt_date", "total_shares_issued"],
                      dtype={"corp_code": str})
    pos["fiscal_year"] = pos["receipt_date"].str[:4].astype(int)
    shares = (pos.dropna(subset=["total_shares_issued"])
                 .sort_values("receipt_date")
                 .groupby(["corp_code", "fiscal_year"])["total_shares_issued"].last()
                 .rename("shares_issued").reset_index())
    df = fin.merge(pay, on=["corp_code", "fiscal_year"], how="outer").merge(
        shares, on=["corp_code", "fiscal_year"], how="left")
    con = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    px = pd.read_sql("select corp_code, fiscal_year, price_ye, price_avg from firm_year_market",
                     con, dtype={"corp_code": str})
    return df, px


def score(cand: np.ndarray, price: np.ndarray) -> tuple[int, float, float]:
    ok = np.isfinite(cand) & np.isfinite(price) & (cand > 0) & (price > 0)
    n = int(ok.sum())
    if n < MIN_N:
        return n, 0.0, 0.0
    lr = np.log(cand[ok]) - np.log(price[ok])
    tight = float(np.mean(np.abs(lr - np.median(lr)) < TIGHT))
    corr = float(np.corrcoef(np.log(cand[ok]), np.log(price[ok]))[0, 1])
    return n, tight, corr


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.1")
    ap.add_argument("--ledger", default=r"C:\KOBEP\ledger.db")
    args = ap.parse_args()

    df, px = load(args.release, args.ledger)
    df = df.merge(px, on=["corp_code", "fiscal_year"], how="inner")
    num = [c for c in df.columns
           if c not in ("corp_code", "fiscal_year", "price_ye", "price_avg")
           and pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().sum() >= MIN_N]
    X = {c: df[c].to_numpy(dtype=float) for c in num}
    targets = {"price_ye": df["price_ye"].to_numpy(float),
               "price_avg": df["price_avg"].to_numpy(float)}
    amounts = [c for c in num if any(h in c for h in AMOUNT_HINT) and c not in QUANTITY]
    quantities = [c for c in num if c in QUANTITY]

    rows = []
    with np.errstate(divide="ignore", invalid="ignore"):
        for a, b in itertools.permutations(num, 2):
            cand = X[a] / X[b]
            for t, p in targets.items():
                n, tight, corr = score(cand, p)
                if n and (tight >= FLAG_SHARE or corr >= FLAG_CORR):
                    rows.append((f"{a} / {b}", t, n, tight, corr, {a, b}))
        for a, b in itertools.permutations(amounts, 2):
            for c in quantities:
                cand = (X[a] - X[b]) / X[c]
                for t, p in targets.items():
                    n, tight, corr = score(cand, p)
                    if n and (tight >= FLAG_SHARE or corr >= FLAG_CORR):
                        rows.append((f"({a} - {b}) / {c}", t, n, tight, corr, {a, b, c}))

    out = pd.DataFrame(rows, columns=["path", "target", "n", "share_within_2pct",
                                      "log_corr", "cols"])
    out["origin"] = np.where(out["cols"].apply(lambda s: bool(s & DART_PRICE_BEARING)),
                             "DART_DISCLOSED", "KRX_ORIGIN")
    out = out.drop(columns="cols").sort_values(["origin", "share_within_2pct"],
                                               ascending=[True, False])
    report = os.path.join(args.release, "manifest", "audit_price_leak.csv")
    out.to_csv(report, index=False, lineterminator="\n")

    print(f"columns searched: {len(num)}  pairs: {len(num) * (len(num) - 1):,}  "
          f"triples: {len(amounts) * (len(amounts) - 1) * len(quantities):,}")
    print(f"flagged paths: {len(out)}  -> {report}")
    if len(out):
        print(out.groupby("origin").size().to_string())
        print(out.head(25).to_string(index=False))
    leaks = out[out["origin"] == "KRX_ORIGIN"]
    if len(leaks):
        print(f"\nFAIL: {len(leaks)} KRX-origin price path(s)", file=sys.stderr)
        sys.exit(1)
    print("\nPASS: no KRX-origin price path")


if __name__ == "__main__":
    main()
