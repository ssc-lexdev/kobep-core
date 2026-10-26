"""Reason codes for every blank cell in the release (decision D5).

KOBEP keeps missing values and says why. A cell-level table would run to
millions of rows for the transaction ledger, so reasons are recorded per rule:
(file, variable, reason_code, rule, n_cells). The extractor fails if any blank
cell is matched by no rule - "every blank has a reason" is checked, not
asserted.

Codes
-----
NA_NOT_APPLICABLE     the value is undefined for this row (a new report has no
                      prior ratio; an uncensored event has no censoring kind)
NA_FORM_VERSION       the field did not exist in the form version filed
                      (holding-purpose code from 3.9/2020, voting-basis ratios
                      from 4.2)
NA_NOT_DISCLOSED      the filer or statement left it blank
NA_NOT_COLLECTED      available from DART but not collected for v1.0
NA_UNDEFINED_RATIO    a ratio whose denominator is missing, zero or negative
NA_CURRENCY_MISMATCH  amounts in different currencies cannot be summed
NA_NO_PRIOR_YEAR      a change variable in a firm's first observed year
NA_RULE_UNDETERMINED  a derived category whose rules reach no decision
NA_SOURCE_CONFLICT    two DART sources disagree on whether the value exists
NA_WITHHELD_PERSONAL  the filed value is a natural person's birth date (an
                      organisation filed under its representative's) and is
                      not released
"""
from __future__ import annotations

import pandas as pd

ND, NA, FV = "NA_NOT_DISCLOSED", "NA_NOT_APPLICABLE", "NA_FORM_VERSION"
NC, NR, UR = "NA_NOT_COLLECTED", "NA_NOT_RESOLVED", "NA_UNDEFINED_RATIO"
CM, NP = "NA_CURRENCY_MISMATCH", "NA_NO_PRIOR_YEAR"
RU = "NA_RULE_UNDETERMINED"
WP = "NA_WITHHELD_PERSONAL"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace("", None), errors="coerce")


def _version(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def rules(name: str, df: pd.DataFrame) -> list[tuple[str, str, str, pd.Series]]:
    """(variable, code, rule text, mask over rows) - checked in order; the first
    rule that matches a blank cell owns it."""
    T = pd.Series(True, index=df.index)
    if name == "kobep_position_ledger.csv":
        v = _version(df["form_version"])
        new = df["report_type_code"] == "1"
        return [
            ("prev_report_date", NA, "report_type_code = 1 (new report)", new),
            ("prev_report_date", ND, "otherwise", T),
            ("prev_ratio_stockequiv", NA, "report_type_code = 1 (new report)", new),
            ("prev_ratio_stockequiv", ND, "otherwise", T),
            ("prev_ratio_voting", FV, "form_version < 4.2", v < 4.2),
            ("prev_ratio_voting", NA, "report_type_code = 1 (new report)", new),
            ("prev_ratio_voting", ND, "otherwise", T),
            ("curr_ratio_voting", FV, "form_version < 4.2", v < 4.2),
            ("curr_ratio_voting", ND, "otherwise", T),
            # The two forms number their versions separately: the short form
            # gained PUR_OWN at 3.9 (2020), the standard form only at 4.0 (late
            # 2022) - standard 3.9 has no code (852 filings).
            ("holding_purpose_code", FV, "short form < 3.9 or standard form < 4.0",
             ((df["form_kind"] == "short") & (v < 3.9))
             | ((df["form_kind"] == "standard") & (v < 4.0))),
            ("holding_purpose_code", ND, "otherwise", T),
            ("relation_to_issuer_code", ND, "filer entered '-'", T),
            ("curr_ratio_stockequiv", ND, "summary ratio cell blank", T),
            ("report_type_code", ND, "report type not marked", T),
            ("total_shares_issued", ND, "issuer share count blank", T),
            ("holding_purpose_code_derived", RU, "holding_purpose_basis UNCLASSIFIED",
             df["holding_purpose_basis"] == "UNCLASSIFIED"),
            ("holding_purpose_code_derived", ND, "standard form with no purpose prose", T),
        ]
    if name == "kobep_transaction_ledger.csv":
        return [
            ("unit_price", NA, "flow_kind not TRADE (no consideration stated)",
             df["flow_kind"] != "TRADE"),
            ("unit_price", ND, "trade row without a price", T),
            ("price_source", NA, "unit_price blank", df["unit_price"] == ""),
            ("unit_price_kind", NA, "unit_price blank", df["unit_price"] == ""),
            ("method_en", NA, "method_ko blank", df["method_ko"] == ""),
            ("direction", NA, "method has no sign (e.g. 'exercise price adjustment')", T),
            ("method_ko", ND, "method cell '-' or blank", T),
            ("party_id", WP, "six-digit value reading as a birth date beside an organisation name",
             df["_party_id_withheld"]),
        ] + [(c, ND, "cell blank, '-' or a placeholder such as 해당없음 in the filing", T) for c in (
            "shares_before", "shares_change", "shares_after", "security_ko",
            "change_date", "party_name", "party_id")] + [
        ]
    if name == "kobep_terms_event.csv":
        return [("party_id", WP, "six-digit value reading as a birth date beside an organisation name",
                 df["_party_id_withheld"])] + [
            (c, ND, "terms-change rows carry few coded cells", T)
                for c in ("party_name", "party_id", "event_date", "method_ko",
                          "security_ko", "unit_price")] + [
            ("security_class", NA, "security_ko blank", T),
            ("method_en", NA, "method_ko blank", T),
            ("price_source", NA, "unit_price blank", T)]
    if name == "kobep_event_ledger.csv":
        censored = df["exit_censored"] == "1"
        return [
            ("prev_ratio", NA, "entry filing is a new report", df["entry_report_type"] == "New"),
            ("prev_ratio", ND, "otherwise", T),
            ("exit_date", NA, "exit_censored = 1", censored),
            ("censoring_kind", NA, "exit_censored = 0", ~censored),
            ("transition_date", NA, "class_changed = 0", df["class_changed"] == "0"),
            ("purpose_at_entry", FV,
             "entry filing is short form < 3.9 or standard form < 4.0",
             df["_entry_no_purpose_field"]),
            ("purpose_at_entry", ND, "otherwise", T),
            ("purpose_changed", FV, "no purpose code on any filing", T),
            ("is_related_party", NA, "class_at_entry UNCERTAIN", df["class_at_entry"] == "UNCERTAIN"),
            ("is_related_party", ND, "otherwise", T),
            ("is_marginal_entry", NA, "entry_ratio blank", T),
            ("purpose_at_entry_derived", RU, "purpose_at_entry_basis UNCLASSIFIED",
             df["purpose_at_entry_basis"] == "UNCLASSIFIED"),
            ("purpose_at_entry_derived", ND, "entry filing has no purpose prose", T),
        ]
    if name == "kobep_blockholder_entity.csv":
        return [
            ("review_reason", NA, "needs_review = 0", df["needs_review"] == "0"),
            ("review_reason", ND, "otherwise", T),
            ("id_value", WP, "id_kind ID_WITHHELD", df["id_kind"] == "ID_WITHHELD"),
            ("id_value", ND, "no identifier on any filing", T),
        ]
    if name == "kobep_firm_master.csv":
        return [
            ("delisting_date", NA, "not delisted in that year", T),
            ("corp_name_en", NC, "company profile not collected for this firm", T),
            ("ksic_code", NC, "company profile not collected for this firm", T),
            ("established_date", NC, "company profile not collected for this firm", T),
            ("industry_name_ko", NC, "ksic_code blank or not in the KSIC 11th-revision table", T),
            ("industry_name_en", NC, "ksic_code blank or not in the KSIC 11th-revision table", T),
            ("listing_date", NC, "delisted before the exchange roster that gives listing dates; "
             "DART carries no listing date", T),
            ("fiscal_month", NC, "neither source carries it", T),
        ]
    if name == "kobep_firmyear_financial.csv":
        ratios = {"roa", "roe", "op_margin", "net_margin", "cfo_assets", "effective_tax_rate",
                  "fcf_assets", "capex_assets", "debt_equity", "liabilities_assets",
                  "current_ratio", "interest_coverage", "ppe_assets", "invrec_assets",
                  "cash_assets", "re_te"}
        out = []
        for c in df.columns:
            if c in ratios:
                out.append((c, UR, "numerator or denominator blank, or denominator <= 0", T))
            elif c in ("revenue_growth", "assets_growth"):
                out.append((c, NP, "no prior year, or the reporting currency changed", T))
            elif c == "firm_age":
                out.append((c, NC, "establishment date not collected", T))
            elif c == "size":
                out.append((c, UR, "total assets blank or <= 0 (log undefined)", T))
            elif c == "fcf":
                out.append((c, ND, "cfo or capex not reported", T))
            else:
                out.append((c, ND, "account not reported in the annual statements", T))
        return out
    if name == "kobep_firmyear_payout.csv":
        payer = df["div_dummy"] == "1"
        cur = df["payout_basis"] == "NONE"
        return [
            ("dps", NA, "no cash dividend", df["div_dummy"] == "0"),
            ("dps", ND, "otherwise", T),
            ("payout_ratio_disclosed", NA, "no cash dividend", df["div_dummy"] == "0"),
            ("payout_ratio_disclosed", ND, "otherwise", T),
            ("div_yield_disclosed", NA, "no cash dividend", df["div_dummy"] == "0"),
            ("div_yield_disclosed", ND, "otherwise", T),
            ("div_stock_total", NA, "no stock dividend", T),
            ("div_cash_total", ND, "div_basis MISSING, or TOTAL_NOT_DISCLOSED (per-share amount "
             "filed, total left blank or in the wrong unit)", T),
            ("div_dummy", ND, "div_basis MISSING or TOTAL_NOT_DISCLOSED", T),
        ] + [(c, NA, "no movement of that kind reported", T) for c in (
            "treasury_acquired_qty", "treasury_acq_qty_direct", "treasury_acq_qty_trust",
            "treasury_acq_qty_other", "treasury_retired_qty", "treasury_disposed_qty")] + [
            ("treasury_end_qty", ND, "treasury table absent for the year", T),
            ("buyback_value", "NA_SOURCE_CONFLICT",
             "separate cash-flow shows a purchase, treasury table shows none",
             df["buyback_value_basis"] == "NA_SOURCE_CONFLICT"),
            ("buyback_value", ND, "buyback_value_basis NA_NOT_DISCLOSED", T),
            ("buyback_fs_div", NA, "basis is not a financial statement", T),
            ("total_payout", CM, "statements not in KRW with a buyback",
             cur & (df["div_basis"].isin(["REPORTED", "INFERRED_ZERO"]))
             & (df["buyback_value"] != "")),
            ("total_payout", ND, "dividend or buyback amount missing", T),
        ] + [(c, NP, "cash dividend of fiscal year t-1 not observed", T) for c in (
            "div_initiation", "div_omission", "div_increase")] + [
            (c, UR, "total_payout blank or denominator <= 0", T) for c in (
                "payout_ratio", "payout_assets", "payout_equity", "payout_ocf",
                "payout_capacity_used_lb")] + [
            ("div_assets", UR, "div_cash_total blank or total assets blank or <= 0", T)] + [
            ("distributable_profit_ub", ND, "equity or issued capital not reported", T)]
    return []


def build(files: dict[str, tuple[list[str], list[tuple]]],
          hints: dict[str, dict[str, list]] | None = None) -> tuple[list[tuple], dict]:
    """`hints`: per file, extra row-aligned boolean columns that the files do
    not carry (which blank party IDs were withheld)."""
    hints = hints or {}
    out, unclassified = [], {}
    # The entry filing's form decides whether an event can have a purpose code.
    ph, prow = files["kobep_position_ledger.csv"]
    i_r, i_k, i_v = ph.index("rcept_no"), ph.index("form_kind"), ph.index("form_version")
    no_field = {r[i_r]: (r[i_k] == "short" and float(r[i_v]) < 3.9)
                or (r[i_k] == "standard" and float(r[i_v]) < 4.0) for r in prow}
    for name, (header, rows) in sorted(files.items()):
        df = pd.DataFrame(rows, columns=header).astype(object).where(
            lambda x: x.notna(), "").astype(str)
        for col, values in hints.get(name, {}).items():
            df[col] = pd.Series(values, index=df.index, dtype=bool)
        if name in ("kobep_transaction_ledger.csv", "kobep_terms_event.csv") \
                and "_party_id_withheld" not in df:
            df["_party_id_withheld"] = False
        if name == "kobep_event_ledger.csv":
            df["_entry_no_purpose_field"] = df["entry_rcept_no"].map(no_field).fillna(False)
        blank = {c: df[c] == "" for c in header if (df[c] == "").any()}
        if not blank:
            continue
        owned = {c: pd.Series(False, index=df.index) for c in blank}
        for var, code, rule, mask in rules(name, df):
            if var not in blank:
                continue
            hit = blank[var] & mask & ~owned[var]
            n = int(hit.sum())
            if n:
                out.append((name, var, code, rule, n))
                owned[var] |= hit
        for c in blank:
            left = int((blank[c] & ~owned[c]).sum())
            if left:
                unclassified[f"{name}.{c}"] = left
    return out, unclassified
