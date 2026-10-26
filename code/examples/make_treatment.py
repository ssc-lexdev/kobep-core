#!/usr/bin/env python3
"""Example: regenerate treatment labels from the released ledger.

This is an example of use, not part of the dataset's definition. Nothing in
`data/` depends on it.

The release ships no treatment variable (decision D12): a label encodes one
research question. This script builds twelve example variants from the
public files, so a reuser can see how such indicators are formed and change a
threshold in one place. Unit: one row per event (issuer x blockholder).

Base definition - an outside entry:
    class_at_entry = OUTSIDER  (relation to issuer 13 'shareholder')
    and is_related_party = 0 and entry_left_truncated = 0
    and unattributable = 0

Variants (all 0/1 unless stated):
  T_broad            the base definition
  T_strict           T_broad and the class never changes to INSIDER/UNCERTAIN
                     over the relationship. A rule-based definition: a
                     version verified by people would need adjudications,
                     which are not released.
  T_ever_first       T_broad and the issuer's first T_broad entry in the ledger
  T_control          T_broad and holding purpose at entry = 01 (influence)
  T_general          T_broad and purpose at entry in {01, 03}
  T_any              T_broad regardless of purpose (= T_broad; kept for the
                     design's naming)
  T_ex_passive       T_broad and purpose at entry != 02
  T_ex_nps           T_broad and the holder is not the National Pension Service
  T_market_purchase  T_broad and the entry filing has market_purchase = 1 and
                     involuntary = 0 (position ledger)
  T_involuntary      T_broad and the entry filing has involuntary = 1 (gift,
                     merger, option, debt-to-equity swap or another
                     non-purchase route; see the dictionary)
  T_intensity_band   entry ratio band for T_broad: 5-10, 10-15, 15+ (string)
  T_type             holder type for T_broad: PENSION_PRO, FINANCIAL,
                     CORPORATE, FOREIGN, OTHER (string)

Holding purpose uses `purpose_at_entry_derived` (coded where filed, otherwise
derived from the purpose prose; see its basis column). Dates, censoring and
truncation flags come with the event ledger and are not recomputed here.

Usage:  python make_treatment.py --data <release>/data --out treatment_variants.csv
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

TYPE = {"Y": "PENSION_PRO", "K": "FINANCIAL", "A": "FINANCIAL", "I": "CORPORATE",
        "O": "FOREIGN", "U": "FOREIGN"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True, help="the release data/ folder")
    ap.add_argument("--out", default="treatment_variants.csv")
    args = ap.parse_args()
    rd = lambda f, **k: pd.read_csv(os.path.join(args.data, f), dtype=str, **k)  # noqa: E731
    ev = rd("kobep_event_ledger.csv").fillna("")
    ent = rd("kobep_blockholder_entity.csv",
             usecols=["reporter_id", "entity_type_code", "nationality", "is_nps"]).fillna("")
    pos = rd("kobep_position_ledger.csv",
             usecols=["rcept_no", "market_purchase", "involuntary"]).set_index("rcept_no")
    ev = ev.merge(ent, on="reporter_id", how="left")

    base = ((ev.class_at_entry == "OUTSIDER") & (ev.is_related_party == "0")
            & (ev.entry_left_truncated == "0") & (ev.unattributable == "0"))
    purpose = ev.purpose_at_entry_derived
    bought = ev.entry_rcept_no.map(pos.market_purchase).eq("1")
    involuntary = ev.entry_rcept_no.map(pos.involuntary).eq("1")

    out = pd.DataFrame({"event_id": ev.event_id, "corp_code": ev.corp_code,
                        "reporter_id": ev.reporter_id,
                        "entry_obligation_date": ev.entry_obligation_date})
    out["T_broad"] = base.astype(int)
    out["T_strict"] = (base & (ev.class_last == "OUTSIDER")).astype(int)
    first = ev[base].sort_values(["entry_obligation_date", "event_id"]).groupby("corp_code").event_id.first()
    out["T_ever_first"] = ev.event_id.isin(first).astype(int)
    out["T_control"] = (base & (purpose == "01")).astype(int)
    out["T_general"] = (base & purpose.isin(["01", "03"])).astype(int)
    out["T_any"] = out["T_broad"]
    out["T_ex_passive"] = (base & (purpose != "02")).astype(int)
    out["T_ex_nps"] = (base & (ev.is_nps != "1")).astype(int)
    out["T_market_purchase"] = (base & bought & ~involuntary).astype(int)
    out["T_involuntary"] = (base & involuntary).astype(int)
    ratio = pd.to_numeric(ev.entry_ratio, errors="coerce")
    band = pd.cut(ratio, [0, 10, 15, 1000], right=False, labels=["5-10", "10-15", "15+"]).astype(str)
    out["T_intensity_band"] = band.where(base, "")
    out["T_type"] = ev.entity_type_code.map(TYPE).fillna("OTHER").where(base, "")
    out["purpose_basis"] = ev.purpose_at_entry_basis
    out.sort_values("event_id").to_csv(args.out, index=False, lineterminator="\n")
    cols = [c for c in out.columns if c.startswith("T_") and c not in ("T_intensity_band", "T_type")]
    print(f"{len(out):,} events -> {args.out}")
    print(out[cols].sum().to_string())
    print(out.loc[out.T_broad == 1, "T_type"].value_counts().to_string())


if __name__ == "__main__":
    main()
