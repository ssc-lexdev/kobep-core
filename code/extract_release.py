#!/usr/bin/env python3
"""Extract the KOBEP-Core v1.0 release files from the internal ledger.

One deterministic pass from `ledger.db` to `data/*.csv`. Nothing in the
release is edited by hand: run this twice and the checksums must agree.

Scope decisions this script enforces (internal decision log, HANDOFF §2)
------------------------------------------------------------------------
D17  No natural persons, at any grain. Filings whose reporter is a natural
     person are dropped with everything hanging off them, and so are the
     person rows that corporate filings carry in their related-party tables.
     Pseudonymising was rejected: a receipt number links straight back to the
     public filing, so a masked name is not a removed one.
D19  Ledger files (index, positions, transactions, terms, events, entities)
     run 2011-2025; firm-year files run 2016-2025. Every ledger row carries
     `in_core_window` (receipt date in 2016-2025). The 2011-2015 rows are the
     pre-window history of the 2016-2025 panel firms, not a census of KOSPI
     in those years.
D16  No KRX-origin prices. The only prices here are the ones filers wrote
     into their own disclosures (`price_source = DART_DISCLOSED`).
     Scope freeze 2026-09-28: no market file, no ownership summary, no
     human verdicts.

Free-text fields (holding-purpose prose, change reasons, remarks) are left
out of v1.0. They name people - a reason field reads like "- <name> 증여 (-)
<shares>주" - and no name filter is reliable enough on free prose.

Usage:
    python extract_release.py [--db C:/KOBEP/ledger.db] [--out C:/KOBEP/release/KOBEP-Core_v1.0]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter

import missing_reasons
from make_vocabulary import METHOD, gloss

LEDGER_FIRST = "20110101"
LEDGER_LAST = "20251231"
CORE_FIRST = "20160101"
FY_FIRST, FY_LAST = 2016, 2025

# --------------------------------------------------------------------------
# Natural-person detection for related-party rows inside corporate filings
# --------------------------------------------------------------------------
# A filer's own status is known (`blockholder_entity.is_individual`). The
# parties listed inside a corporate filing are not, and the identifier column
# mixes business registration numbers, foreign fund codes and birth dates.
# Measured on the ledger (2026-10-01): of six-digit identifiers, 41,487 are
# valid YYMMDD dates (people), while 18,631 are not dates at all - foreign
# fund codes such as `001280` for "FID LOW PRICE STK". A digit-count rule
# would have deleted the funds and kept people with other identifier shapes.
_CORPORATE = re.compile(
    r"주식회사|\(주\)|㈜|유한|조합|재단|법인|펀드|은행|증권|보험|자산운용|투자|캐피탈|"
    r"공사|공단|기금|회사|홀딩스|파트너스|그룹|신탁|협회|학교|학원|병원|"
    r"LLC|Ltd|Inc|Fund|L\.P|\bLP\b|Limited|Corp|PLC|N\.V|B\.V|\bAG\b|\bSA\b|GmbH|Trust|"
    # Foreign legal forms whose registration numbers can look like a date -
    # `GUT EME SL`, a Spanish S.L. registered as 011127, was read as a person.
    r"\bS\.?\s?L\b|\bS\.?\s?A\b|\bK\.?\s?K\b|\bPte\b|\bCo\b|Company|Holdings?\b|Capital|"
    r"Management|Partners|Advisors|Investors|Bank",
    re.I)
_BRN = re.compile(r"\d{3}-\d{2}-\d{5}")
_HANGUL_NAME = re.compile(r"[가-힣]{2,4}")


def _birth_date(pid: str) -> bool:
    if not re.fullmatch(r"\d{6}", pid):
        return False
    month, day = int(pid[2:4]), int(pid[4:6])
    return 1 <= month <= 12 and 1 <= day <= 31


# Filing-level acquisition flags, computed from the released transaction rows
# of the filing so a reuser can recompute them. The parser's own flags read the
# coded method (HLD_MTH), which only the newest forms carry, and were 0 on
# every filing (advisor review 2026-10-07).
MARKET_PURCHASE = {"장내매수(+)", "시간외매매(+)"}
INVOLUNTARY = {"수증(+)", "합병(+)", "상속(+)", "주식매수선택권행사(+)", "출자전환",
               "대물변제수령(+)", "무상신주취득(+)", "주식배당(+)", "계열사편입(+)"}


def unit_price_kind(price, security_cls: str, flow_kind: str | None) -> str | None:
    """What `unit_price` is on this row: an executed trade price in won per
    share, a reference value (exercise-price adjustment, debt-to-equity swap
    and other non-trade rows), or a depositary-receipt price whose unit the
    filings do not state."""
    if price is None:
        return None
    if security_cls == "DEPOSITARY_RECEIPT":
        return "DR_UNIT_UNCONFIRMED"
    return "EXECUTED_KRW_PER_SHARE" if flow_kind == "TRADE" else "REFERENCE_KRW_PER_SHARE"


# An organisation's name can carry the person who signs for it: an employee
# share ownership association filed as "<company> 우리사주조합장 <name>"
# or "<name>(우리사주조합장)", an investment partnership as "<partnership>
# (대표조합원 <name>)". The organisation stays; the person's name is cut
# (found by the tightened PII audit, 2026-10-07). Names of foundations named
# after a founder ("(재)<founder> 문화재단") are the organisation's legal name and
# are kept.
_ROLE_NAME = [
    (re.compile(r"\s*[(\[]?\s*대표조합원\s*[가-힣]{2,4}\s*[)\]]?"), ""),
    (re.compile(r"우리사주\s*조합장\s*[가-힣]{2,4}\b"), "우리사주조합"),
    (re.compile(r"^[가-힣]{2,4}\s*[(\[]\s*(.*?)조합장\s*[)\]]?\s*$"), r"\1조합"),
]
ROLE_NAME_PATTERN = re.compile(r"조합장\s*[가-힣]{2,4}|대표조합원|^[가-힣]{2,4}\s*[(\[].*조합장")


def scrub_role_name(name):
    if not name:
        return name
    out = name
    for pattern, repl in _ROLE_NAME:
        out = pattern.sub(repl, out)
    return out.strip()


KSIC_TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference", "ksic_rev11.csv")
REPORT_NAME_EN = {
    "주식등의대량보유상황보고서(일반)": "Report on large shareholding (standard form)",
    "주식등의대량보유상황보고서(약식)": "Report on large shareholding (short form)",
}


def report_name_en(name: str | None) -> str | None:
    if not name:
        return None
    base = name.replace("[기재정정]", "").strip()
    en = REPORT_NAME_EN.get(base)
    if en is None:
        return None
    return ("[Amendment] " + en) if "[기재정정]" in name else en


def method_en(method: str | None) -> str | None:
    """English for the filed method, from the gloss table that also writes
    docs/kobep_vocabulary.csv - one table, so the two cannot disagree."""
    m = blank(method)
    return gloss(m, METHOD) if m else None


def norm_name(s: str | None) -> str:
    return re.sub(r"[\s.,()·]", "", s or "").upper()


def is_person_party(party_id: str | None, party_name: str | None,
                    known_people: frozenset = frozenset()) -> bool:
    """`known_people`: normalised names of the ledger's individual entities.
    A related-party row can name one of them next to a company's registration
    number (a person's name beside a company's number); the name decides."""
    pid = (party_id or "").strip()
    name = (party_name or "").strip()
    corporate = bool(_CORPORATE.search(name))
    if corporate:
        return False
    if _birth_date(pid) or norm_name(name) in known_people:
        return True
    looks_named = bool(_HANGUL_NAME.fullmatch(name.replace(" ", "")))
    return looks_named and not _BRN.fullmatch(pid)


# Issuer names that entered an entity's alias list from a mis-keyed filer
# field: 20161220000307 is Fidelity's filing on 휠라코리아 with the issuer's
# name in the filer slot (advisor review 2026-10-07). The filing stays with
# the entity; only the alias is dropped.
ALIAS_CONTAMINATION = {"BH00005": {"휠라코리아(주)"}}


# --------------------------------------------------------------------------
# Value helpers
# --------------------------------------------------------------------------
def iso(d: str | None) -> str | None:
    """YYYYMMDD -> YYYY-MM-DD; anything else -> None."""
    if not d:
        return None
    d = str(d).replace("-", "")
    if len(d) != 8 or not d.isdigit():
        return None
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def blank(v):
    return None if v in ("-", "", None) else v


def placeholder(v) -> bool:
    """Text a filer wrote in an identifier cell instead of an identifier -
    "해당없음", "해당사항 없음", "(미확정)" (399 cells, 2026-10-09). No digit, so
    no identifier: released blank, reason NA_NOT_DISCLOSED."""
    return v is not None and not re.search(r"\d", str(v))


def withheld_pid(pid) -> bool:
    v = blank(pid)
    return v is not None and _birth_date(str(v).strip())


def party_id_out(pid):
    """A related party kept as an organisation can still be identified by a
    birth date (its representative's); that value is withheld."""
    v = blank(pid)
    return None if withheld_pid(pid) or placeholder(v) else v


SECURITY_CLASS = {
    # The 18 security labels that occur in the transaction tables.
    "의결권있는 주식": "VOTING_SHARE", "보통주": "COMMON",
    "의결권있는 우선주": "VOTING_PREFERRED",
    "증권예탁증권": "DEPOSITARY_RECEIPT", "전환사채권": "CONVERTIBLE_BOND",
    "신주인수권부사채권": "BOND_WITH_WARRANT", "교환사채권": "EXCHANGEABLE_BOND",
    "신주인수권이표시된것": "WARRANT", "신주인수권표시증서": "SUBSCRIPTION_CERTIFICATE",
    "의결권있는 주식으로 전환될주식": "CONVERTIBLE_TO_VOTING",
    "보통주로 전환될 우선주": "CONVERTIBLE_PREFERRED",
    "의결권있는 주식으로 상환될주식": "REDEEMABLE_INTO_VOTING",
    "기타": "OTHER",
}


def security_class(label: str | None) -> str:
    if label in SECURITY_CLASS:
        return SECURITY_CLASS[label]
    if not label or label == "-":
        return "NOT_STATED"
    if "?" in label:
        return "UNREADABLE"
    if label.startswith("의결권있는"):
        return "VOTING_SHARE"          # filer typos: doubled or truncated label
    return "UNMAPPED"


# --------------------------------------------------------------------------
# Writer
# --------------------------------------------------------------------------
def write_csv(path: str, header: list[str], rows: list[tuple]) -> tuple[int, str]:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    data = buf.getvalue().encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)
    return len(rows), hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------
def extract(con: sqlite3.Connection) -> tuple[dict, dict]:
    q = con.execute
    report: dict = {"excluded": {}}

    # A natural person is an entity flagged individual, or one keyed on a birth
    # date under a name with no corporate form - one individual was filed as
    # an "other organisation" (type N) with a birth-date ID.
    person_reporters, people = set(), set()
    for rid, ind, id_value, name, variants in q(
            "select reporter_id, is_individual, id_value, name_normalized, name_variants "
            "from blockholder_entity"):
        if ind or (_birth_date((id_value or "").strip()) and not _CORPORATE.search(name or "")):
            person_reporters.add(rid)
            people.update(norm_name(v) for v in json.loads(variants or "[]"))
            people.add(norm_name(name))
    # Plus every party a related-party table identifies as a person by its own
    # row (birth-date ID, Hangul personal name). The same person can appear
    # elsewhere beside a company number, or in a company's alias list.
    for pid, name in q("select party_id, party_name from filing_transaction "
                       "union select party_id, party_name from terms_event"):
        if name and is_person_party(pid, name):
            people.add(norm_name(name))
    people.discard("")
    known_people = frozenset(people)
    report["excluded"]["entities_natural_person"] = len(person_reporters)
    filer_of = dict(q("select rcept_no, reporter_id from filing_entity"))
    parsed = {r[0] for r in q("select rcept_no from filing_parsed")}

    index = q("""select rcept_no, corp_code, receipt_date, report_name, form_kind,
                        is_amendment, filer_name from report_index
                 where receipt_date between ? and ? order by rcept_no""",
              (LEDGER_FIRST, LEDGER_LAST)).fetchall()
    person_filings = {r[0] for r in index if filer_of.get(r[0]) in person_reporters}

    # Filings whose text DART never served (status 014) have no filer ID, only
    # the name on the index. Every one of them carries a name some entity also
    # filed under; if any such entity is a natural person the filing is
    # dropped. That is deliberately one-sided: a name shared by a person and a
    # company (5 at extraction) goes out with the person.
    alias_kind: dict[str, set[int]] = {}
    for names, individual in q("select index_names, is_individual from blockholder_entity"):
        for name in json.loads(names or "[]"):
            alias_kind.setdefault(name, set()).add(individual)
    unparsed = [r for r in index if r[0] not in parsed]
    unparsed_person = {r[0] for r in unparsed if 1 in alias_kind.get(r[6], {1})}
    report["unparsed_filings"] = {
        "total": len(unparsed),
        "dropped_person_or_shared_name": len(unparsed_person),
        # A count, not the names: they are names of people (removed from the
        # report 2026-10-08 after the extended PII audit flagged them).
        "shared_person_company_name": sum(
            1 for r in unparsed if alias_kind.get(r[6]) == {0, 1}),
    }

    keep = {r[0] for r in index} - person_filings - unparsed_person
    report["excluded"]["filings_by_natural_persons"] = len(person_filings)
    report["excluded"]["unparsed_filings_person_name"] = len(unparsed_person)

    files: dict[str, tuple[list[str], list[tuple]]] = {}

    files["kobep_filing_index.csv"] = (
        ["rcept_no", "corp_code", "receipt_date", "in_core_window", "form_kind",
         "is_amendment", "parsed", "report_name_ko", "report_name_en"],
        # An amendment is a filing titled as one. The internal flag also took
        # DART's list remark rm="정", which marks an original that was later
        # corrected, not a correction - 1,440 originals were flagged that way
        # (advisor review 2026-10-07).
        [(r[0], r[1], iso(r[2]), int(r[2] >= CORE_FIRST), r[4], int("정정" in (r[3] or "")),
          int(r[0] in parsed), r[3], report_name_en(r[3])) for r in index if r[0] in keep])

    files["kobep_filing_entity.csv"] = (
        ["rcept_no", "reporter_id"],
        sorted((rc, rid) for rc, rid in filer_of.items() if rc in keep))

    used = {rid for rc, rid in filer_of.items() if rc in keep}

    # Display name = the name on the entity's most recent released filing, and
    # the first one alongside. The internal normalised name was often an old
    # trade name (하나금융투자 for today's 하나증권, 현대중공업지주 for HD현대);
    # researcher decision 2026-10-05. Same registration number throughout, so
    # this changes the label, never the entity.
    filed_names: dict[str, list[tuple[str, str]]] = {}
    for rc, name, receipt in q("""select p.rcept_no, p.filer_name, i.receipt_date
                                  from filing_parsed p join report_index i using (rcept_no)
                                  where p.filer_name is not null and p.filer_name <> ''"""):
        if rc in keep:
            filed_names.setdefault(filer_of[rc], []).append((receipt + rc, name.strip()))
    for v in filed_names.values():
        v.sort()
    ent_rows, withheld = [], 0
    for r in q("""select reporter_id, id_kind, id_value, name_normalized, name_variants,
                         index_names, entity_type, entity_type_code, entity_type_mixed,
                         nationality, is_nps, needs_review, review_reason
                  from blockholder_entity where is_individual = 0 order by reporter_id"""):
        if r[0] not in used or r[0] in person_reporters:
            continue
        # A company's alias list can hold the chairman it filed under (two
        # holding companies listed their chairmen's names). Those aliases are
        # names of people.
        scrub = lambda js: json.dumps(list(dict.fromkeys(  # noqa: E731
            scrub_role_name(v) for v in json.loads(js or "[]")
            if norm_name(v) not in known_people)), ensure_ascii=False)
        names = [scrub_role_name(n) for _, n in filed_names.get(r[0], [])
                 if norm_name(n) not in known_people]
        latest = names[-1] if names else scrub_role_name(r[3])
        first = names[0] if names else scrub_role_name(r[3])
        id_kind, id_value = r[1], r[2]
        if id_kind == "BIRTH_DATE" or _birth_date((id_value or "").strip()):
            # An organisation without a registration number - mostly employee
            # share ownership associations, which the internal ledger keyed as
            # FOREIGN_REG - filed under its representative's birth date. The
            # organisation stays; the date is a person's and goes.
            id_kind, id_value = "ID_WITHHELD", None
            withheld += 1
        elif placeholder(blank(id_value)):
            id_value = None
        stray = ALIAS_CONTAMINATION.get(r[0], set())
        variants = json.dumps([v for v in json.loads(scrub(r[4])) if v not in stray],
                              ensure_ascii=False)
        ent_rows.append((r[0], id_kind, id_value, latest, first, variants, scrub(r[5])) + r[6:])
    report["excluded"]["entity_birth_date_ids_withheld"] = withheld
    files["kobep_blockholder_entity.csv"] = (
        ["reporter_id", "id_kind", "id_value", "name", "name_first_filed", "name_variants_json",
         "index_names_json", "entity_type", "entity_type_code", "entity_type_mixed",
         "nationality", "is_nps", "needs_review", "review_reason"], ent_rows)

    pos = []
    for r in q("""select p.rcept_no, i.corp_code, i.receipt_date, p.formula_version,
                         p.form_kind, p.is_amendment, p.obligation_date, p.base_date,
                         p.prev_report_date, p.filer_type_code, p.relation_code,
                         p.outsider_class, p.prev_ratio, p.curr_ratio, p.prev_ratio_voting,
                         p.curr_ratio_voting, p.report_type_code, p.purpose_code,
                         p.involuntary, p.market_purchase, p.joint_filing,
                         p.total_shares_issued, d.purpose_code_derived, d.purpose_basis
                  from filing_parsed p join report_index i using (rcept_no)
                  left join purpose_derived d using (rcept_no)
                  where i.receipt_date between ? and ? order by p.rcept_no""",
                (LEDGER_FIRST, LEDGER_LAST)):
        if r[0] not in keep:
            continue
        pos.append((r[0], filer_of.get(r[0]), r[1], iso(r[2]), int(r[2] >= CORE_FIRST),
                    r[3], r[4], r[5], iso(r[6]), iso(r[7]), iso(r[8]), r[9],
                    blank(r[10]), r[11], r[12], r[13], r[14], r[15], blank(r[16]), blank(r[17]),
                    None, None, r[20],
                    blank(str(r[21]).replace(",", "")) if r[21] else None,
                    r[22], r[23]))
    files["kobep_position_ledger.csv"] = (
        ["rcept_no", "reporter_id", "corp_code", "receipt_date", "in_core_window",
         "form_version", "form_kind", "is_amendment", "obligation_date", "base_date",
         "prev_report_date", "filer_type_code", "relation_to_issuer_code",
         "outsider_class", "prev_ratio_stockequiv", "curr_ratio_stockequiv",
         "prev_ratio_voting", "curr_ratio_voting", "report_type_code",
         "holding_purpose_code", "involuntary", "market_purchase", "joint_filing",
         "total_shares_issued", "holding_purpose_code_derived", "holding_purpose_basis"], pos)

    receipt = {r[0]: r[2] for r in index}
    tx, dropped_people, withheld_tx = [], 0, []
    for r in q("""select rcept_no, row_no, party_name, party_id, change_date, method,
                         direction, security, shares_before, shares_change, shares_after,
                         unit_price, flow_kind
                  from filing_transaction order by rcept_no, row_no"""):
        if r[0] not in keep:
            continue
        if is_person_party(r[3], r[2], known_people):
            dropped_people += 1
            continue
        sc = security_class(r[7])
        withheld_tx.append(withheld_pid(r[3]))
        tx.append((r[0], r[1], int(receipt[r[0]] >= CORE_FIRST), scrub_role_name(blank(r[2])),
                   party_id_out(r[3]), iso(r[4]), blank(r[5]), r[6], blank(r[7]),
                   sc, r[8], r[9], r[10], r[11],
                   "DART_DISCLOSED" if r[11] is not None else None,
                   unit_price_kind(r[11], sc, r[12]), r[12], method_en(r[5])))
    report["excluded"]["transaction_rows_natural_person_parties"] = dropped_people
    methods_of: dict[str, set] = {}
    for t in tx:
        if t[6]:
            methods_of.setdefault(t[0], set()).add(t[6])
    i_mp = 20                       # involuntary, market_purchase
    pos[:] = [p[:i_mp] + (int(bool(methods_of.get(p[0], set()) & INVOLUNTARY)),
                          int(bool(methods_of.get(p[0], set()) & MARKET_PURCHASE))) + p[i_mp + 2:]
              for p in pos]
    files["kobep_transaction_ledger.csv"] = (
        ["rcept_no", "row_no", "in_core_window", "party_name", "party_id", "change_date",
         "method_ko", "direction", "security_ko", "security_class", "shares_before",
         "shares_change", "shares_after", "unit_price", "price_source", "unit_price_kind",
         "flow_kind", "method_en"], tx)

    terms, dropped_terms, withheld_terms = [], 0, []
    for r in q("""select rcept_no, row_no, corp_code, party_name, party_id, event_date,
                         receipt_date, table_method, security, unit_price
                  from terms_event order by rcept_no, row_no"""):
        if r[0] not in keep:
            continue
        if is_person_party(r[4], r[3], known_people):
            dropped_terms += 1
            continue
        withheld_terms.append(withheld_pid(r[4]))
        terms.append((r[0], r[1], r[2], int(r[6] >= CORE_FIRST), scrub_role_name(blank(r[3])),
                      party_id_out(r[4]), iso(r[5]), iso(r[6]), blank(r[7]), blank(r[8]),
                      security_class(r[8]) if blank(r[8]) else None, r[9],
                      "DART_DISCLOSED" if r[9] is not None else None, method_en(r[7])))
    report["excluded"]["terms_rows_natural_person_parties"] = dropped_terms
    report["excluded"]["party_ids_withheld_birth_date"] = sum(withheld_tx) + sum(withheld_terms)
    report["_hints"] = {
        "kobep_transaction_ledger.csv": {"_party_id_withheld": withheld_tx},
        "kobep_terms_event.csv": {"_party_id_withheld": withheld_terms}}
    files["kobep_terms_event.csv"] = (
        ["rcept_no", "row_no", "corp_code", "in_core_window", "party_name", "party_id",
         "event_date", "receipt_date", "method_ko", "security_ko", "security_class",
         "unit_price", "price_source", "method_en"], terms)

    ev_cols = ["event_id", "corp_code", "reporter_id", "n_filings", "entry_rcept_no",
               "entry_obligation_date", "entry_base_date", "entry_receipt_date",
               "entry_fy", "entry_ratio", "prev_ratio", "entry_report_type",
               "prior_index_filings", "entry_prev_ratio_ge5", "entry_left_truncated",
               "is_first_ever", "is_marginal_entry", "peak_ratio", "peak_date",
               "last_observed_ratio", "last_obligation_date", "exit_date", "exit_type",
               "exit_censored", "censoring_kind", "duration_days", "n_reentries",
               "purpose_at_entry", "purpose_changed", "class_at_entry", "class_last",
               "class_changed", "transition_date", "is_related_party", "joint_at_entry",
               "unattributable", "entry_before_window", "entry_filing_lag_days",
               "entry_filed_late", "entry_rep_change", "entry_left_truncated_broad"]
    date_cols = {"entry_obligation_date", "entry_base_date", "entry_receipt_date",
                 "peak_date", "last_obligation_date", "exit_date", "transition_date"}
    # Events come from `treatment_event_v1`, built from filings received up to
    # LEDGER_LAST with LEDGER_LAST as the observation cutoff
    # (build_treatment_event.py --receipt-last), so every event field can be
    # recomputed from the released filing ledger. Advisor review 2026-10-07:
    # the earlier build observed exits through 2026-07-28, beyond the ledger.
    # Holding purpose at entry, with the prose-derived category where the
    # entry filing has no PUR_OWN code (classify_purpose_text.py).
    derived_purpose = {r[0]: (r[1], r[2]) for r in q(
        "select rcept_no, purpose_code_derived, purpose_basis from purpose_derived")}
    events, late_entries = [], 0
    for r in q(f"select {', '.join(ev_cols)} from treatment_event_v1 order by event_id"):
        row = dict(zip(ev_cols, r))
        if row["reporter_id"] in person_reporters:
            continue
        if (row["entry_receipt_date"] or "") > LEDGER_LAST:
            late_entries += 1
            continue
        events.append(tuple(iso(v) if k in date_cols else v for k, v in row.items())
                      + derived_purpose.get(row["entry_rcept_no"], (None, None)))
    report["excluded"]["events_entered_after_ledger_end"] = late_entries
    report["event_observation_cutoff"] = iso(LEDGER_LAST)
    beyond = [v for e in events for k, v in zip(ev_cols, e)
              if k in date_cols and v and v > iso(LEDGER_LAST)]
    assert not beyond, f"{len(beyond)} event dates after {LEDGER_LAST}"
    report["excluded"]["events_with_natural_person_reporters"] = q(
        "select count(*) from treatment_event_v1 t join blockholder_entity b "
        "using (reporter_id) where b.is_individual = 1").fetchone()[0]
    files["kobep_event_ledger.csv"] = (
        ev_cols + ["purpose_at_entry_derived", "purpose_at_entry_basis"], events)

    files["kobep_security_class.csv"] = (
        ["security_ko", "security_class"],
        sorted({(r[8], r[9]) for r in tx if r[8]} | {(r[9], r[10]) for r in terms if r[9]}))

    # Firm master: one row per firm-year, so that stock codes and listing status
    # can change over time without a second file.
    prof = {r[0]: r for r in q("select corp_code, corp_name_en, industry_code, fiscal_month, "
                               "established from company_profile")}
    attr = {r[0]: r for r in q("select corp_code, industry, fiscal_month, listing_date "
                               "from firm_attributes")}
    orig = {r[0]: r for r in q("select corp_code, established, first_report_fy, origin_kind, "
                               "predecessor_corp_code from firm_listing_origin")}
    # Industry titles come from the official KSIC (11th revision) table for
    # the DART industry code, in Korean and English, for every firm. Until
    # 2026-10-09 the Korean title came from the exchange's current roster,
    # coarser than the code and missing for the 76 firms delisted before it.
    ksic = {}
    with open(KSIC_TABLE, encoding="utf-8", newline="") as fh:
        for k in csv.DictReader(fh):
            ksic[k["ksic_code"]] = (k["name_ko"], k["name_en"])
    fm, rule_based = [], set()
    for r in q("""select corp_code, fiscal_year, stock_code, corp_name, market, is_listed,
                         is_spv, is_financial, is_holding, delisting_date, is_partial_year
                  from firm_master where fiscal_year between 2011 and 2025
                  order by corp_code, fiscal_year"""):
        p, a, o = prof.get(r[0]), attr.get(r[0]), orig.get(r[0])
        code = p[2] if p else None
        title_ko, title_en = ksic.get(code or "", (None, None))
        is_fin, is_hold, basis = r[7], r[8], "ROSTER"
        if is_fin is None or is_hold is None:
            # Delisted before the roster: the same flags by rule from the KSIC
            # code. On the 807 firms with roster flags the rules agree 99.9 %
            # (holding company: 64992, or the truncated 649) and 98.5 %
            # (financial: divisions 64-66 other than holding companies).
            is_hold = int(bool(code) and (code.startswith("64992") or code == "649"))
            is_fin = int(bool(code) and code[:2] in ("64", "65", "66") and not is_hold)
            basis = "KSIC_RULE"
            rule_based.add(r[0])
        fm.append((r[0], r[1], r[2], r[3], p[1] if p else None, r[4], r[5], r[6], is_fin,
                   is_hold, iso(r[9]), r[10], code, title_ko, title_en,
                   (p[3] if p else None) or (a[2].replace("월", "") if a and a[2] else None),
                   a[3] if a else None, iso(o[1]) if o and o[1] else (iso(p[4]) if p else None),
                   o[3] if o else None, basis))
    report["firm_flags_by_ksic_rule"] = len(rule_based)
    files["kobep_firm_master.csv"] = (
        ["corp_code", "fiscal_year", "stock_code", "corp_name_ko", "corp_name_en", "market",
         "is_listed", "is_spv", "is_financial", "is_holding", "delisting_date",
         "is_partial_year", "ksic_code", "industry_name_ko", "industry_name_en", "fiscal_month",
         "listing_date", "established_date", "origin_kind", "firm_flag_basis"], fm)

    # Firm-year layer, 2016-2025. Financials carry no market-derived column.
    # `depreciation` is left out: the account map resolves it for 7 of 7,653
    # firm-years, which is a mapping gap, not a variable.
    fin_cols = [r[1] for r in q("pragma table_info(firm_year_financial)")
                if r[1] != "depreciation"]
    files["kobep_firmyear_financial.csv"] = (
        fin_cols,
        q(f"select {', '.join(fin_cols)} from firm_year_financial "
          "where fiscal_year between ? and ? order by corp_code, fiscal_year",
          (FY_FIRST, FY_LAST)).fetchall())

    # Payout: the reported-buyback columns (C15) under the plain names. The
    # KRX-priced estimate and everything computed from it stay internal - its
    # difference from the cash dividend recovered the mean close exactly.
    pay = []
    for r in q("""select corp_code, fiscal_year, div_cash_total, div_basis, dps,
                         payout_ratio_disclosed, div_yield_disclosed, div_stock_total,
                         disagree_flag, treasury_acquired_qty, treasury_acq_qty_direct,
                         treasury_acq_qty_trust, treasury_acq_qty_other,
                         treasury_retired_qty, treasury_disposed_qty, treasury_end_qty,
                         n_buyback_decisions, n_trust_openings, buyback_value,
                         buyback_value_basis, buyback_fs_div, total_payout_reported,
                         payout_basis_reported, div_dummy, div_initiation, div_omission,
                         div_increase, payout_ratio_reported, payout_assets_reported,
                         payout_equity_reported, payout_ocf_reported, div_assets,
                         distributable_profit_ub
                  from firm_year_payout where fiscal_year between ? and ?
                  order by corp_code, fiscal_year""", (FY_FIRST, FY_LAST)):
        total, dist = r[21], r[32]
        used = total / dist if total is not None and dist and dist > 0 else None
        pay.append(tuple(r) + (used,))
    files["kobep_firmyear_payout.csv"] = (
        ["corp_code", "fiscal_year", "div_cash_total", "div_basis", "dps",
         "payout_ratio_disclosed", "div_yield_disclosed", "div_stock_total",
         "disagree_flag", "treasury_acquired_qty", "treasury_acq_qty_direct",
         "treasury_acq_qty_trust", "treasury_acq_qty_other", "treasury_retired_qty",
         "treasury_disposed_qty", "treasury_end_qty", "n_buyback_decisions",
         "n_trust_openings", "buyback_value", "buyback_value_basis", "buyback_fs_div",
         "total_payout", "payout_basis", "div_dummy", "div_initiation", "div_omission",
         "div_increase", "payout_ratio", "payout_assets", "payout_equity", "payout_ocf",
         "div_assets", "distributable_profit_ub", "payout_capacity_used_lb"], pay)

    report["rows"] = {k: len(v[1]) for k, v in files.items()}
    return files, report


# --------------------------------------------------------------------------
# Referential checks (the full audit suite lives in audit/)
# --------------------------------------------------------------------------
def check_joins(files: dict) -> dict:
    col = lambda f, c: {r[files[f][0].index(c)] for r in files[f][1]}  # noqa: E731
    idx = col("kobep_filing_index.csv", "rcept_no")
    ent = col("kobep_blockholder_entity.csv", "reporter_id")
    firms = col("kobep_firm_master.csv", "corp_code")
    out = {}
    for f in ("kobep_position_ledger.csv", "kobep_transaction_ledger.csv",
              "kobep_terms_event.csv", "kobep_filing_entity.csv"):
        out[f"{f}: rcept_no not in index"] = len(col(f, "rcept_no") - idx)
    out["event_ledger: entry_rcept_no not in index"] = len(
        col("kobep_event_ledger.csv", "entry_rcept_no") - idx - {None})
    for f in ("kobep_filing_entity.csv", "kobep_event_ledger.csv",
              "kobep_position_ledger.csv"):
        out[f"{f}: reporter_id not in entities"] = len(col(f, "reporter_id") - ent)
    for f in ("kobep_filing_index.csv", "kobep_event_ledger.csv",
              "kobep_firmyear_financial.csv", "kobep_firmyear_payout.csv"):
        out[f"{f}: corp_code not in firm_master"] = len(col(f, "corp_code") - firms)
    for f in ("kobep_firmyear_financial.csv", "kobep_firmyear_payout.csv"):
        keys = [(r[0], r[1]) for r in files[f][1]]
        out[f"{f}: duplicate (corp_code, fiscal_year)"] = len(keys) - len(set(keys))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=r"C:\KOBEP\ledger.db")
    ap.add_argument("--out", default=r"C:\KOBEP\release\KOBEP-Core_v1.0")
    ap.add_argument("--collection-manifest", default=r"C:\KOBEP\manifest.csv")
    ap.add_argument("--parser", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "parser", "kobep_parser.py"))
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    files, report = extract(con)
    report["join_checks"] = check_joins(files)

    reasons, unclassified = missing_reasons.build(files, report.pop("_hints"))
    files["kobep_missing_reasons.csv"] = (
        ["file", "variable", "reason_code", "rule", "n_cells"], reasons)
    report["rows"]["kobep_missing_reasons.csv"] = len(reasons)
    report["missing_reasons"] = {"rules": len(reasons),
                                 "blank_cells_explained": sum(r[4] for r in reasons),
                                 "unclassified": unclassified}

    data_dir = os.path.join(args.out, "data")
    tmp = data_dir + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    sums = {}
    for name in sorted(files):
        header, rows = files[name]
        _, digest = write_csv(os.path.join(tmp, name), header, rows)
        sums[name] = digest
    shutil.rmtree(data_dir, ignore_errors=True)
    os.replace(tmp, data_dir)

    manifest = os.path.join(args.out, "manifest")
    os.makedirs(manifest, exist_ok=True)

    # Provenance per filing: what was fetched, when, and its digest, so a
    # reuser who downloads the same receipt numbers from DART can confirm they
    # hold the bytes this release was parsed from. Digests are of the payload
    # DART returned (a ZIP), uncompressed from local storage.
    collected = {}
    with open(args.collection_manifest, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["path"].startswith("doc/"):
                collected[os.path.basename(r["path"]).replace(".xml.gz", "")] = r
    parser_tag = "kobep_parser sha256:" + hashlib.sha256(
        open(args.parser, "rb").read()).hexdigest()[:12] if os.path.exists(args.parser) else ""
    idx_header, idx_rows = files["kobep_filing_index.csv"]
    i_r, i_p = idx_header.index("rcept_no"), idx_header.index("parsed")
    mrows = []
    for r in idx_rows:
        c = collected.get(r[i_r])
        mrows.append((r[i_r], c["collected_at"] if c else None,
                      c["sha256_uncompressed"] if c else None,
                      c["bytes_uncompressed"] if c else None,
                      "SERVED" if c else "NOT_SERVED",
                      parser_tag if r[i_p] == 1 else None))
    n, digest = write_csv(os.path.join(manifest, "rcept_no_manifest.csv"),
                          ["rcept_no", "collected_at", "sha256_payload", "bytes_payload",
                           "dart_text", "parser_version"], mrows)
    sums["../manifest/rcept_no_manifest.csv"] = digest
    report["manifest"] = {"rows": n, "not_served": sum(1 for m in mrows if m[4] == "NOT_SERVED")}
    with open(os.path.join(manifest, "checksums.sha256"), "w", encoding="utf-8",
              newline="\n") as fh:
        for name in sorted(sums):
            path = name[3:] if name.startswith("../") else "data/" + name
            fh.write(f"{sums[name]}  {path}\n")
    with open(os.path.join(manifest, "extract_report.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)

    print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    bad = {k: v for k, v in report["join_checks"].items() if v}
    if bad:
        print("JOIN FAILURES:", bad, file=sys.stderr)
        sys.exit(1)
    if unclassified:
        print("BLANK CELLS WITHOUT A REASON:", unclassified, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
