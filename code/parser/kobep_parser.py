#!/usr/bin/env python3
"""KOBEP parser for Korean 5% beneficial-ownership reports (Stage-1 extraction).

Source
------
DART (Data Analysis, Retrieval and Transfer System, https://dart.fss.or.kr),
the electronic disclosure system operated by Korea's Financial Supervisory
Service. `document.xml` returns the original filing as a ZIP-wrapped XML.

Design basis (all empirically verified against real filings)
-----------------------------------------------------------
* DART XML is **code-driven, not string-driven**: 1,235 `ACODE` attributes
  (143 distinct), 18 distinct `AUNIT` controlled vocabularies, and 24 named
  `TABLE-GROUP ACLASS` semantic zones in a single filing.
* Code anchors exist from 2011 onward (form version 2.6). Six `AUNIT` domains
  and 13 `TABLE-GROUP` names are stable across all six form generations
  observed (2.6 / 2.9 / 3.2 / 3.6 / 3.9 / 4.0 / 4.2).
* Stage-1 (all filings) covers the summary zone plus Part 1 holding purpose
  and Part 1 change method/reason. Heavier extraction (special-relationship
  roster, funding sources, own/client account split) is Stage-2.

Pitfalls locked down by unit tests (see `test_parser.py`)
--------------------------------------------------------
P1  Never auto-classify relation code 16 ("Other") as an outsider.
    Chairman-family members and corporate foundations are filed under 16.
P2  "Relation to issuer" and "relation to filer" are *different* attributes.
    Reading the wrong one flips insider/outsider in both directions at once.
P3  Filer-type mis-mapping. Code `Y` is "pension fund / professional
    investor", NOT an individual. Treating it as an individual demotes the
    National Pension Service to UNCERTAIN while chairman families pass.
P4  Amended filings carry both pre- and post-amendment tables. Only
    `TABLE[@ACLASS='EXTRACTION']` holds the authoritative post-amendment
    values; pre-amendment values live in `ACLASS="NORMAL"` appendices.
P5  Endpoint suffix `.json` omitted -> DART returns status 101, which reads
    like an auth failure. Handled in `kobep_collector.py`.
P6  **The XML declaration lies.** Every filing declares `encoding="utf-8"`,
    but filings up to 2020 are actually CP949. Trusting the declaration
    silently mojibakes all Korean text.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, asdict, field

# --------------------------------------------------------------------------
# P6: encoding detection
# --------------------------------------------------------------------------
# Filings from 2011-2020 declare utf-8 but are encoded in CP949 (verified on
# 2011 / 2013 / 2016 / 2019 / 2020 samples). 2023+ is genuinely UTF-8.
# We ignore the declaration and pick the encoding under which Hangul survives.
_HANGUL = re.compile(r"[가-힣]")


def decode_dart(raw: bytes) -> tuple[str, str]:
    """Return (text, encoding_used), ignoring the XML declaration."""
    fallback = None
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if _HANGUL.search(text):
            return text, enc
        fallback = fallback or (text, enc)
    if fallback:
        return fallback
    return raw.decode("utf-8", "replace"), "utf-8(replace)"


def read_zip(blob: bytes) -> tuple[str, str]:
    """Unwrap a `document.xml` API response (a ZIP archive) into text."""
    archive = zipfile.ZipFile(io.BytesIO(blob))
    return decode_dart(archive.read(archive.infolist()[0].filename))


# --------------------------------------------------------------------------
# Structural extraction
# --------------------------------------------------------------------------
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_GROUP = re.compile(r'<TABLE-GROUP\s+ACLASS="([^"]*)"[^>]*>(.*?)</TABLE-GROUP>', re.S)
_EXTRACTION = re.compile(r'<TABLE\s+[^>]*ACLASS="EXTRACTION"[^>]*>.*?</TABLE>', re.S)


def _clean(text: str) -> str:
    # DART encodes line breaks as the literal entity `&cr;`.
    return _WS.sub(" ", _TAG.sub(" ", text.replace("&cr;", "\n"))).strip()


def table_groups(xml: str) -> dict[str, list[str]]:
    """Map each `TABLE-GROUP ACLASS` name to its raw segments, in document order."""
    groups: dict[str, list[str]] = {}
    for match in _GROUP.finditer(xml):
        groups.setdefault(match.group(1), []).append(match.group(2))
    return groups


def canonical_segment(segments: list[str]) -> str:
    """P4: pick the authoritative segment of an amended filing.

    Amended filings repeat most tables twice ("before" / "after"). The
    before-values appear only inside `ACLASS="NORMAL"` appendices, while the
    authoritative post-amendment values carry `ACLASS="EXTRACTION"`.
    We select on that predicate rather than on table ordering, which is not
    reliable (one observed filing contained an empty third copy).
    """
    if not segments:
        return ""
    for segment in reversed(segments):
        if _EXTRACTION.search(segment):
            return segment
    return segments[-1]


def aunit(segment: str, code: str) -> str | None:
    """Read a controlled-vocabulary value (`AUNIT` / `AUNITVALUE` pair)."""
    match = re.search(rf'AUNIT="{code}"[^>]*AUNITVALUE="([^"]*)"', segment)
    if not match:
        match = re.search(rf'AUNITVALUE="([^"]*)"[^>]*AUNIT="{code}"', segment)
    return match.group(1) if match else None


def acode(segment: str, code: str) -> str | None:
    """Read a labelled data cell (`ACODE` attribute) and normalise its text.

    Some filers wrap the cell value in a paragraph - `<TE ACODE=..><P>5.02</P>` -
    and the lookahead used to stop at that opening `<P`, returning an empty
    value. One leading `<P>` is therefore skipped. Found on the 2014-2015
    short forms (form 3.1), where it blanked 316 ratios, 300 of them the
    National Pension Service's.
    """
    match = re.search(rf'ACODE="{code}"[^>]*>\s*(?:<P[^>]*>)?(.*?)'
                      rf'(?=<(?:TD|TH|SPAN|P|TABLE|/))',
                      segment, re.S)
    if not match:
        return None
    value = _clean(match.group(1))
    return None if value in ("", "-") else value


# --------------------------------------------------------------------------
# Controlled vocabularies
# --------------------------------------------------------------------------
# Labels below were read directly from the display text adjacent to each code
# in the source filings (see `_b3_domain.py`), not inferred from documentation.

#: Relation of the *filer* to the *issuer*. This is the field that determines
#: insider vs outsider status. See P1 and P2.
RELATION_TO_ISSUER = {
    "01": ("Registered officer", "INSIDER"),
    "02": ("Major shareholder", "UNCERTAIN"),   # >=10% holders qualify, including
                                                # outside institutions -> manual review
    "03": ("De facto controlling shareholder", "INSIDER"),
    "04": ("Unregistered officer", "INSIDER"),  # appears from January 2026 with
                                                # form 6.0; an officer either way,
                                                # so it belongs with 01 and not in
                                                # the unmapped bucket, which is
                                                # where 13 once left the pension
                                                # fund (pitfall F3)
    "10": ("Largest shareholder", "INSIDER"),
    "13": ("Shareholder", "OUTSIDER"),          # e.g. National Pension Service
    "14": ("Affiliated company etc.", "INSIDER"),
    "15": ("Officer of affiliated company", "INSIDER"),
    "16": ("Other", "UNCERTAIN"),               # P1: never auto-classify as outsider
}

#: Relation of a special-related party to the *filer*. A different domain
#: entirely; conflating it with RELATION_TO_ISSUER is pitfall P2.
RELATION_TO_FILER = {
    "C": "Affiliated company", "I": "Largest shareholder", "J": "Officer",
    "L": "Other", "M": "Officer of affiliated company",
}
RELATION_TO_FILER_ALT = {"S": "Specially related party"}

#: Filer entity type. Note the value space overlaps SPECIAL_PARTY_TYPE but the
#: two are distinct domains. P3: `Y` is a pension fund, not an individual.
#: All eleven codes were read off the display text of the filings themselves
#: rather than inferred from the filer names (`_probe_crp_tp.py`); the first
#: three had been mapped from a small fixture set and the other eight - 19.4 %
#: of filings - were falling through as unlabelled.
FILER_TYPE = {
    "I": "Domestic corporation",
    "Y": "Pension fund / professional investor",
    "D": "Individual (domestic)",
    "K": "Financial institution",
    "O": "Foreign corporation",
    "F": "Individual (foreign)",
    "N": "Other organisation (domestic)",
    "U": "Other organisation (foreign)",
    "C": "Civil-code partnership",
    "W": "Statutory partnership",
    "A": "Investment company etc.",
}
#: Filer codes that denote a natural person. Insider status cannot be read off
#: a filing for these - see the P3 demotion rule.
INDIVIDUAL_FILER_TYPES = {"D", "F"}
#: Filer codes whose declared category is foreign.
FOREIGN_FILER_TYPES = {"O", "F", "U"}
SPECIAL_PARTY_TYPE = {
    "D": "Individual (domestic)", "I": "Domestic corporation",
    "K": "Financial institution", "Y": "Pension fund / professional investor",
}

#: Method of acquisition or disposal, from the Part-3 transaction detail.
ACQUISITION_METHOD = {
    "01": "On-market purchase (+)", "02": "On-market sale (-)",
    "35": "Gift received (+)", "47": "Merger (+)",
    "68": "Stock option exercise (+)", "69": "Stock option exercise (-)",
    "97": "Officer retirement (-)", "98": "Other (-)",
}
#: Acquisitions carrying no monitoring intent -> placebo-treatment candidates.
INVOLUNTARY_METHODS = {"35", "47", "68", "97"}
#: Deliberate market accumulation -> the `T_market_purchase` treatment variant.
MARKET_PURCHASE_METHODS = {"01"}

REPORT_TYPE = {"1": "New", "2": "Change in holdings", "3": "Change in terms",
               "4": "Change in holdings and terms"}
#: Value "2" flags a joint (co-filed) report - needed to detect group breakups.
FILING_MODE = {"1": "Sole", "2": "Joint"}
HOLDING_PURPOSE = {"01": "Influence over management", "02": "Passive investment",
                   "03": "General investment"}
SECURITY_TYPE = {"1": "Common stock", "3": "Subscription warrant certificate",
                 "11": "Voting stock"}


@dataclass
class Filing:
    """One parsed 5% beneficial-ownership filing (Stage-1 fields only)."""

    rcept_no: str = ""                     # DART receipt number (primary key)
    encoding: str = ""                     # encoding actually used (see P6)
    formula_version: str = ""              # DART form version, e.g. "4.2"
    form_kind: str = ""                    # standard | short (professional investors)
    is_amendment: bool = False

    # Four distinct dates exist; treatment timing uses `obligation_date`,
    # market-reaction windows use the receipt date from the index.
    obligation_date: str | None = None     # date the filing duty arose
    base_date: str | None = None           # as-of date of the reported figures
    prev_report_date: str | None = None
    this_report_date: str | None = None

    # Issuer
    issuer_name: str | None = None
    stock_code: str | None = None
    total_shares_issued: str | None = None

    # Filer
    filer_name: str | None = None
    filer_id: str | None = None            # business reg. no., or 6-digit birth date
    filer_type: str | None = None
    filer_type_code: str | None = None

    # Relation (P1, P2)
    relation_to_issuer_code: str | None = None
    relation_to_issuer: str | None = None
    outsider_class: str = "UNCERTAIN"       # INSIDER | OUTSIDER | UNCERTAIN

    # Ownership ratios. The 5% threshold is defined on a "stock-equivalent"
    # basis whose denominator varies by filer (it includes convertibles held by
    # that filer and its related parties), so the voting-basis ratio is a
    # separate quantity and is not interchangeable.
    prev_ratio_stockequiv: str | None = None
    curr_ratio_stockequiv: str | None = None
    prev_ratio_voting: str | None = None    # form version 4.2+ only; often blank
    curr_ratio_voting: str | None = None
    prev_shares: str | None = None
    curr_shares: str | None = None

    # Filing classification, purpose, and change details
    report_type_code: str | None = None
    report_type: str | None = None
    purpose_code: str | None = None
    purpose_text: str | None = None
    change_method: str | None = None
    change_reason: str | None = None
    involuntary: bool = False
    market_purchase: bool = False
    joint_filing: bool = False
    acquisition_methods: list = field(default_factory=list)

    #: Reason codes for missing values, keyed by field name. KOBEP retains
    #: missing values and records *why* they are missing rather than dropping
    #: the observation.
    missing: dict = field(default_factory=dict)


def parse(xml: str, rcept_no: str = "", encoding: str = "") -> Filing:
    """Extract Stage-1 fields from one filing's XML text."""
    groups = table_groups(xml)
    out = Filing(rcept_no=rcept_no, encoding=encoding)

    version = re.search(r"<FORMULA-VERSION[^>]*>([^<]*)<", xml)
    out.formula_version = version.group(1).strip() if version else ""
    out.form_kind = "short" if "약식" in xml[:3000] else "standard"
    out.is_amendment = "정 정 신 고" in xml[:20000] or "[기재정정]" in xml[:3000]

    duty = canonical_segment(groups.get("RPT_RSP_DT", []))
    out.obligation_date = aunit(duty, "RPT_RSP_DT")
    out.base_date = aunit(duty, "RPT_REF_DT")

    prior = canonical_segment(groups.get("BFR_IFR", []))
    out.prev_report_date = aunit(prior, "BFR_RPT_DT")
    out.this_report_date = aunit(prior, "THS_RPT_DT")

    issuer = canonical_segment(groups.get("CRP_NM", []))
    out.stock_code = acode(issuer, "CRP_CD")
    out.total_shares_issued = acode(issuer, "FLT_STK_CNT")

    summary = canonical_segment(groups.get("SUM_INF", []))
    out.issuer_name = acode(summary, "CRP_NM")
    out.prev_shares = acode(summary, "SUM_BMT_CNT")
    out.curr_shares = acode(summary, "SUM_TMT_CNT")
    out.prev_ratio_stockequiv = acode(summary, "SUM_BMT_RT")
    out.curr_ratio_stockequiv = acode(summary, "SUM_TMT_RT")
    out.prev_ratio_voting = acode(summary, "VR_BMT_RT")
    out.curr_ratio_voting = acode(summary, "VR_TMT_RT")
    if out.curr_ratio_voting is None:
        # Voting-basis ratios were only added to the summary block in form 4.2.
        out.missing["curr_ratio_voting"] = (
            "NA_NOT_APPLICABLE" if out.formula_version < "4.2" else "NA_NOT_DISCLOSED")

    # P2: relation comes from RELATION_TO_ISSUER (`FLT_CRP_RLT`); never from
    # the filer-relation attribute (`IFR_RLT`), which is a different domain.
    filer_block = canonical_segment(groups.get("RPT_DST1", []))
    out.relation_to_issuer_code = (aunit(summary, "FLT_CRP_RLT")
                                   or aunit(filer_block, "FLT_CRP_RLT"))
    if out.relation_to_issuer_code in RELATION_TO_ISSUER:
        out.relation_to_issuer, out.outsider_class = \
            RELATION_TO_ISSUER[out.relation_to_issuer_code]
    elif out.relation_to_issuer_code:
        out.relation_to_issuer = f"UNMAPPED:{out.relation_to_issuer_code}"
        out.outsider_class = "UNCERTAIN"
    else:
        out.missing["relation_to_issuer"] = "NA_PARSE_FAIL"

    out.report_type_code = aunit(summary, "RPT_DST1")
    out.report_type = REPORT_TYPE.get(out.report_type_code or "")

    out.filer_name = acode(filer_block, "IFR_NM")
    out.filer_id = acode(filer_block, "IFR_ID")
    out.filer_type_code = aunit(filer_block, "CRP_TP")
    out.filer_type = FILER_TYPE.get(out.filer_type_code or "")
    out.joint_filing = (aunit(summary, "RPT_DST2") == "2"
                        or aunit(filer_block, "RPT_DST2") == "2")

    # P3: demote to UNCERTAIN only for *individual* filers, whose insider status
    # cannot be determined from the filing alone. Code `Y` is a pension fund and
    # must not be demoted - doing so removes the National Pension Service from
    # the treatment group while chairman families remain.
    # `F` is also a natural person (individual, foreign) and was slipping past
    # this rule while `D` was caught.
    if (out.filer_type_code in INDIVIDUAL_FILER_TYPES
            and out.outsider_class == "OUTSIDER"):
        out.outsider_class = "UNCERTAIN"
        out.missing["outsider_class"] = "individual filer - manual adjudication"

    # Holding purpose is not confined to one table group. The standard form
    # carries it in a dedicated Part-1 section; the short form has no such
    # section and places the code and its free text elsewhere. Since both the
    # code and the text carry unique attribute names, searching the whole
    # document is more robust than guessing the group per form generation.
    out.purpose_code = aunit(xml, "PUR_OWN")
    out.purpose_text = (acode(xml, "HLD_OBJ_DTL") or acode(xml, "PUR_TXT")
                        or acode(xml, "OWN_PUR"))
    if out.purpose_code is None:
        # Earlier short-form generations record no purpose at all.
        out.missing["purpose_code"] = "NA_NOT_APPLICABLE"
    if out.purpose_text is None:
        out.missing["purpose_text"] = "NA_NOT_APPLICABLE"

    change = canonical_segment(groups.get("CHN_RSN_DTL", []))
    out.change_method = acode(change, "CHN_HOW")
    out.change_reason = acode(change, "CHN_RSN") or acode(change, "CHN_RSM")

    # Coded acquisition methods live in the Part-3 transaction detail, which is
    # a Stage-2 target; when present we set the treatment flags early.
    detail = canonical_segment(groups.get("TRD_RVL", []))
    methods = {m for m in re.findall(r'AUNIT="HLD_MTH"[^>]*AUNITVALUE="([^"]*)"',
                                     detail) if m != "-"}
    out.acquisition_methods = sorted(
        ACQUISITION_METHOD.get(m, f"UNMAPPED:{m}") for m in methods)
    out.involuntary = bool(methods & INVOLUNTARY_METHODS)
    out.market_purchase = bool(methods & MARKET_PURCHASE_METHODS)
    return out


def parse_blob(blob: bytes, rcept_no: str = "") -> Filing:
    """Parse a raw `document.xml` API response."""
    xml, encoding = read_zip(blob)
    return parse(xml, rcept_no, encoding)


if __name__ == "__main__":
    import glob
    import json
    import os
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    patterns = sys.argv[1:] or [os.path.join(here, "fixtures", "*.xml")]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            xml, encoding = decode_dart(open(path, "rb").read())
            filing = parse(xml, os.path.basename(path), encoding)
            shown = {k: v for k, v in asdict(filing).items()
                     if v not in (None, "", {}, [], False)}
            print(f"\n== {os.path.basename(path)}")
            print(json.dumps(shown, ensure_ascii=False, indent=1))
