#!/usr/bin/env python3
"""C11 spot-check, final score as a two-phase stratified audit.

Phase 1: a language model (gpt-5.5) screened all sampled rows against the
original filings. Phase 2: a human judged (a) every row the model flagged and
(b) random rows among those it passed - the seeded 10 % audit plus a seeded
150-row draw from the rest. Rows are the sampling unit, so bounds are given
both per field and per row (a row with any wrong field counts once).

Strata
  FLAGGED  rows with any model WRONG / CANT_TELL - all judged by the human
  PASSED   rows the model passed in full - a random subset judged by the human
Estimate: errors in FLAGGED + (PASSED fields / judged PASSED fields) x errors in
judged PASSED (inverse-probability expansion; Zrnic & Candes, active inference).
95 % bounds: Wilson score; for the PASSED stratum, the upper bound on its rate is
applied to its unjudged part (zero-numerator logic, Hanley & Lippman-Hand 1983).

A second model (claude-opus-5-5) re-screened every row; its agreement with the
human on all human-judged fields is reported alongside the first model's.

Versions (2026-10-23). Some audited values changed in later builds
(make_rejudge.py). The summary carries one block per version:
  audited          the human verdicts as recorded on the audited values
  audited_crit_b   the same values under the criterion fixed on 2026-10-23
                   (a derived purpose left blank although the prose can be
                   classified is WRONG): human_then_b overrides where filled
  current          the current release: changed fields take human_current,
                   left unjudged while that column is empty
The first two give the error found by the audit; the third, after the fix.

Inputs (deliverables/spotcheck): spotcheck_C11_llm.xlsx, llm_vs_human.csv,
spotcheck_C11_sample150.xlsx, llm_three_way.csv [, spotcheck_C11_claude_flags.xlsx,
spotcheck_C11_rejudge.xlsx]
Output: c11_stratified_summary.csv, c11_field_ledger.csv, c11_model_agreement.csv
"""
from __future__ import annotations

import math
import os
import sys

import pandas as pd

Z = 1.959964
D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "deliverables", "spotcheck")
KEYS = {"filings": ["rcept_no"], "transactions": ["rcept_no", "row_no"], "events": ["event_id"]}


def wilson(k: int, n: int) -> tuple[float, float]:
    if not n:
        return float("nan"), float("nan")
    p = k / n
    c = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return max(0.0, c - h), min(1.0, c + h)


def main() -> None:
    three = pd.read_csv(os.path.join(D, "llm_three_way.csv"), dtype=str).fillna("")
    # human verdicts: earlier audit (incl. blanket OK, as recorded) + 150-row blind draw + flags sheet
    hv = {}
    for r in pd.read_csv(os.path.join(D, "llm_vs_human.csv"), dtype=str).fillna("").itertuples():
        hv[(r.sheet, r.key, r.field)] = (r.human, "audit_" + ("blanket" if "blanket" in r.human_source else "explicit"))
    for s, kc in KEYS.items():
        d = pd.read_excel(os.path.join(D, "spotcheck_C11_sample150.xlsx"), sheet_name=s, dtype=str).fillna("")
        for _, r in d.iterrows():
            k = "#".join(r[c] for c in kc)
            for c in d.columns:
                if c.startswith("human_") and c != "human_note" and r[c].strip():
                    hv[(s, k, c[6:])] = (r[c].strip().upper(), "sample150_blind")
    # the rest of the sample, judged blind (2026-10-26); "-" marks a field judged earlier
    rest = os.path.join(D, "spotcheck_C11_rest208.xlsx")
    if os.path.exists(rest):
        for s, kc in KEYS.items():
            d = pd.read_excel(rest, sheet_name=s, dtype=str).fillna("")
            for _, r in d.iterrows():
                k = "#".join(r[c] for c in kc)
                for c in d.columns:
                    v = r[c].strip().upper()
                    if c.startswith("human_") and c != "human_note" and v not in ("", "-"):
                        hv[(s, k, c[6:])] = (v, "rest208_blind")
    fl = os.path.join(D, "spotcheck_C11_claude_flags.xlsx")
    if os.path.exists(fl):
        for r in pd.read_excel(fl, dtype=str).fillna("").itertuples():
            if r.human.strip():
                hv[(r.sheet, r.key, r.field)] = (r.human.strip().upper(), "claude_flag")
    three["human"] = [hv.get((s, k, f), ("", ""))[0] for s, k, f in zip(three.sheet, three.key, three.field)]
    three["human_source"] = [hv.get((s, k, f), ("", ""))[1] for s, k, f in zip(three.sheet, three.key, three.field)]
    row_flag = three.groupby(["sheet", "key"])["gpt"].transform(lambda v: v.isin(["WRONG", "CANT_TELL", ""]).any())
    three["stratum"] = row_flag.map({True: "FLAGGED", False: "PASSED"})

    # re-judgement of fields whose value changed after the audit
    three["human_then_b"] = three.human
    three["human_current"] = three.human
    three["changed_after_audit"] = False
    rj = os.path.join(D, "spotcheck_C11_rejudge.xlsx")
    if os.path.exists(rj):
        idx = {(s, k, f): i for i, (s, k, f) in enumerate(zip(three.sheet, three.key, three.field))}
        for r in pd.read_excel(rj, dtype=str).fillna("").itertuples():
            i = idx.get((r.sheet, r.key, r.field))
            if i is None:
                continue  # a new field (entry_rep_change) is checked, not scored
            i = three.index[i]
            three.at[i, "changed_after_audit"] = True
            if r.human_then_b.strip().upper() in ("OK", "WRONG"):
                three.at[i, "human_then_b"] = r.human_then_b.strip().upper()
            three.at[i, "human_current"] = r.human_current.strip().upper()
    three.to_csv(os.path.join(D, "c11_field_ledger.csv"), index=False, encoding="utf-8-sig")

    out = []
    for version, col in (("audited", "human"), ("audited_crit_b", "human_then_b"),
                         ("current", "human_current")):
        out += score(three.assign(human=three[col]), version)
    res = pd.DataFrame(out)
    res.to_csv(os.path.join(D, "c11_stratified_summary.csv"), index=False, encoding="utf-8-sig")
    # census of the sample (2026-10-26: every sampled field judged by the human):
    # plain Wilson bounds per field and per row, no stratum weighting needed
    cen = []
    for version, col in (("audited", "human"), ("audited_crit_b", "human_then_b"),
                         ("current", "human_current")):
        for scope, df in [("all", three)] + [(s, three[three.sheet == s]) for s in KEYS]:
            j = df[df[col].isin(["OK", "WRONG"])]
            k = int((j[col] == "WRONG").sum())
            rows = j.groupby(["sheet", "key"])[col].apply(lambda v: (v == "WRONG").any())
            cen.append({"version": version, "scope": scope, "fields": len(df), "judged_fields": len(j),
                        "wrong_fields": k, "field_rate": round(k / len(j), 6) if len(j) else float("nan"),
                        "field_upper95": round(wilson(k, len(j))[1], 6),
                        "rows": df.groupby(["sheet", "key"]).ngroups, "judged_rows": len(rows),
                        "wrong_rows": int(rows.sum()),
                        "row_upper95": round(wilson(int(rows.sum()), len(rows))[1], 6)})
    cen = pd.DataFrame(cen)
    cen.to_csv(os.path.join(D, "c11_census_summary.csv"), index=False, encoding="utf-8-sig")
    print(cen.to_string(index=False))
    # per field, released values, human-judged fields only (manuscript Fig. 4)
    per = []
    for (s, f), g in three.groupby(["sheet", "field"], sort=False):
        j = g[g.human_current.isin(["OK", "WRONG"])]
        k = int((j.human_current == "WRONG").sum())
        lo, hi = wilson(k, len(j))
        per.append({"sheet": s, "field": f, "n_fields": len(g), "n_scored": len(j), "n_wrong": k,
                    "error_rate": k / len(j) if len(j) else float("nan"),
                    "wilson95_lo": lo, "wilson95_hi": hi, "n_cant_tell": 0})
    pd.DataFrame(per).to_csv(os.path.join(D, "c11_field_summary_current.csv"), index=False,
                             encoding="utf-8-sig")
    # model agreement with the human on every human-judged field (as audited)
    # (the models screened the audited values, so current values are not compared)
    agr = []
    for version, col in (("audited", "human"), ("audited_crit_b", "human_then_b")):
        j = three[three[col].isin(["OK", "WRONG"])]
        for m in ("gpt", "claude"):
            v = j[j[m].isin(["OK", "WRONG"])]
            agr.append({"version": version, "model": m, "human_judged_fields": len(j),
                        "model_cant_tell": int((j[m] == "CANT_TELL").sum()),
                        "compared": len(v), "agree": int((v[m] == v[col]).sum()),
                        "agreement": round((v[m] == v[col]).mean(), 4),
                        "false_alarms": int(((v[m] == "WRONG") & (v[col] == "OK")).sum()),
                        "misses": int(((v[m] == "OK") & (v[col] == "WRONG")).sum())})
    agr = pd.DataFrame(agr)
    agr.to_csv(os.path.join(D, "c11_model_agreement.csv"), index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(res.to_string(index=False))
    print(agr.to_string(index=False))
    n_changed = int(three.changed_after_audit.sum())
    n_open = int((three.changed_after_audit & (three.human_current == "")).sum())
    print(f"\nfields changed after the audit: {n_changed}; awaiting human_current: {n_open}")


def score(three: pd.DataFrame, version: str) -> list[dict]:
    out = []
    for scope, df in [("all", three)] + [(s, three[three.sheet == s]) for s in KEYS]:
        fl_ = df[df.stratum == "FLAGGED"]
        ps = df[df.stratum == "PASSED"]
        psj = ps[ps.human != ""]
        e_f = int((fl_.human == "WRONG").sum())
        e_p = int((psj.human == "WRONG").sum())
        unj_f = int((fl_.human == "").sum())
        lo_p, hi_p = wilson(e_p, len(psj))
        est = e_f + (len(ps) / len(psj) * e_p if len(psj) else float("nan"))
        hi_total = e_f + e_p + hi_p * (len(ps) - len(psj))
        # rows as the unit
        rows_ps = ps.groupby("key")
        rj = psj.groupby("key")["human"].apply(lambda v: (v == "WRONG").any())
        rlo, rhi = wilson(int(rj.sum()), len(rj))
        out.append({
            "version": version,
            "scope": scope, "fields": len(df), "human_judged_fields": int((df.human != "").sum()),
            "flagged_fields": len(fl_), "flagged_unjudged": unj_f, "flagged_errors": e_f,
            "passed_fields": len(ps), "passed_judged_fields": len(psj), "passed_errors": e_p,
            "passed_rate_upper95": round(hi_p, 5),
            "passed_rows": rows_ps.ngroups, "passed_judged_rows": len(rj),
            "passed_row_rate_upper95": round(rhi, 5),
            "est_errors": round(est, 3), "est_error_rate": round(est / len(df), 6),
            "error_rate_upper95": round(hi_total / len(df), 6),
        })
    return out


if __name__ == "__main__":
    main()
