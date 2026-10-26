#!/usr/bin/env python3
"""Combined C11 score: human verdict on audited rows, LLM verdict elsewhere.

Inputs
  llm workbook        spotcheck_C11_llm.xlsx (LLM verdict per field, human_audit flag)
  human workbook      spotcheck_C11_human.xlsx (human_<field> marks, may be blank)
  decisions csv       human_decisions_chat.csv (verdicts given in conversation)
  --blanket-ok        audited fields with no explicit human mark count as OK; the
                      researcher reviewed the remaining rows and had no objection
                      (2026-10-05). Recorded in the output so the claim is visible.

Outputs spotcheck_summary.csv (per sheet x field: n, wrong, rate, Wilson 95 %)
and llm_vs_human.csv (agreement of the LLM with the human on audited rows).
"""
from __future__ import annotations

import argparse
import math
import os

import pandas as pd

Z = 1.959964
FIELDS = {
    "filings": ["obligation_date", "report_type_code", "relation_to_issuer_code",
                "prev_ratio_stockequiv", "curr_ratio_stockequiv", "holding_purpose_code",
                "holding_purpose_code_derived", "total_shares_issued", "filer_name"],
    "transactions": ["party_name", "change_date", "method_ko", "shares_change",
                     "shares_after", "unit_price"],
    "events": ["entry_obligation_date", "entry_ratio", "class_at_entry",
               "entry_left_truncated", "exit_type", "exit_date"],
}
KEYS = {"filings": ["rcept_no"], "transactions": ["rcept_no", "row_no"], "events": ["event_id"]}


def wilson(k: int, n: int) -> tuple[float, float]:
    if not n:
        return float("nan"), float("nan")
    p = k / n
    c = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return max(0.0, c - h), min(1.0, c + h)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("llm_workbook")
    ap.add_argument("human_workbook")
    ap.add_argument("decisions")
    ap.add_argument("--blanket-ok", action="store_true")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    dec = pd.read_csv(args.decisions, dtype=str, encoding="utf-8-sig").fillna("")
    explicit = {(r.sheet, r.key, r.field): r.verdict.upper() for r in dec.itertuples()
                if r.verdict.upper() in ("OK", "WRONG", "CANT_TELL")}
    llm = pd.read_excel(args.llm_workbook, sheet_name=None, dtype=str)
    hum = pd.read_excel(args.human_workbook, sheet_name=None, dtype=str)
    summary, agree = [], []
    for sheet, fields in FIELDS.items():
        L = llm[sheet].fillna("")
        H = hum[sheet].fillna("")
        key = lambda df: df[KEYS[sheet]].agg("#".join, axis=1)  # noqa: E731
        L["_k"], H["_k"] = key(L), key(H)
        hmap = H.set_index("_k")
        for f in fields:
            n = k = cant = 0
            for _, r in L.iterrows():
                kk = r["_k"]
                lv = r.get(f"llm_{f}", "").upper()
                if r["human_audit"]:
                    hv = explicit.get((sheet, kk, f)) or (
                        hmap.at[kk, f"human_{f}"].upper() if kk in hmap.index
                        and hmap.at[kk, f"human_{f}"] else "")
                    src = "human"
                    if not hv and args.blanket_ok:
                        hv, src = "OK", "human (blanket)"
                    if hv:
                        agree.append((sheet, f, kk, lv, hv, src))
                    v = hv
                else:
                    v = lv
                if v == "CANT_TELL" or not v:
                    cant += 1
                    continue
                n += 1
                k += v == "WRONG"
            lo, hi = wilson(k, n)
            summary.append((sheet, f, n, k, k / n if n else float("nan"), lo, hi, cant))
    S = pd.DataFrame(summary, columns=["sheet", "field", "n_scored", "n_wrong", "error_rate",
                                       "wilson95_lo", "wilson95_hi", "n_cant_tell"])
    A = pd.DataFrame(agree, columns=["sheet", "field", "key", "llm", "human", "human_source"])
    os.makedirs(args.out_dir, exist_ok=True)
    S.to_csv(os.path.join(args.out_dir, "spotcheck_summary.csv"), index=False, lineterminator="\n")
    A.to_csv(os.path.join(args.out_dir, "llm_vs_human.csv"), index=False, lineterminator="\n")
    pd.set_option("display.width", 170)
    print(S.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\nitem-level, by sheet")
    for sheet in FIELDS:
        s = S[S.sheet == sheet]
        print(f"  {sheet:13s} fields scored {int(s.n_scored.sum()):5d}  wrong {int(s.n_wrong.sum()):3d}  "
              f"rate {s.n_wrong.sum() / s.n_scored.sum():.4f}")
    if len(A):
        both = A[A.llm.isin(["OK", "WRONG"])]
        print(f"\nLLM vs human on audited fields: {len(A)} pairs; LLM decided {len(both)}, "
              f"agreed {(both.llm == both.human).sum()} ({(both.llm == both.human).mean():.3f}); "
              f"LLM WRONG but human OK {((both.llm == 'WRONG') & (both.human == 'OK')).sum()}; "
              f"LLM OK but human WRONG {((both.llm == 'OK') & (both.human == 'WRONG')).sum()}; "
              f"LLM CANT_TELL {(A.llm == 'CANT_TELL').sum()}")
        print("human source:", A.human_source.value_counts().to_dict())


if __name__ == "__main__":
    main()
