#!/usr/bin/env python3
"""Load KOBEP-Core release files with identifiers kept as text.

Several keys look numeric but are not numbers: `corp_code` has leading zeros
(00100939), receipt numbers exceed float precision, and `party_id` mixes
registration numbers with fund codes. Reading them with default type inference
breaks joins. This module reads every identifier as a string and everything
else as pandas would.

    from read_kobep import read
    events = read("kobep_event_ledger.csv", data="KOBEP-Core_v1.0/data")

R:     readr::read_csv(f, col_types = readr::cols(corp_code = "c", rcept_no = "c", ...))
Stata: import delimited ..., stringcols(_all) and destring the measures you need.
"""
from __future__ import annotations

import os

import pandas as pd

#: Same list as make_dictionary.IDENTIFIERS (type "string" in the dictionary).
IDENTIFIERS = ["corp_code", "rcept_no", "entry_rcept_no", "stock_code", "ksic_code",
               "party_id", "id_value", "reporter_id", "event_id"]


def read(name: str, data: str = "data", **kwargs) -> pd.DataFrame:
    path = os.path.join(data, name)
    header = pd.read_csv(path, nrows=0).columns
    dtype = {c: str for c in IDENTIFIERS if c in header}
    dtype.update(kwargs.pop("dtype", {}) or {})
    return pd.read_csv(path, dtype=dtype, keep_default_na=False, na_values=[""], **kwargs)


if __name__ == "__main__":
    import sys
    folder = sys.argv[1] if len(sys.argv) > 1 else "data"
    for f in sorted(os.listdir(folder)):
        if f.endswith(".csv"):
            df = read(f, folder)
            print(f"{f:34} {len(df):>9,} rows  {df.shape[1]:>3} columns")
