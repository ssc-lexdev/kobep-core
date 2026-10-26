#!/usr/bin/env python3
"""Stage-two parsing: the transaction ledger inside each filing.

Stage one read the summary block - who filed, against whom, at what ratio.
That is enough to place an entry in time but not to price it. The detail table
(`TABLE-GROUP ACLASS="HLD_MTH"`) carries what the summary does not: every
change in the position, dated, with the method and, decisively, the executed
unit price.

WHY THIS IS WORTH A SEPARATE PASS
---------------------------------
The activism literature measures what happened to the target's share price. It
rarely measures what the activist actually earned, because execution prices are
not disclosed - a US Schedule 13D reports only the last sixty days of
transactions. Korea requires the full change history with prices on every
filing, so the holder's own cash flows can be reconstructed from the register
itself.

WHAT THE ROWS LOOK LIKE
-----------------------
Data cells are `<TE ACODE="...">` and `<TU AUNIT="...">`, not `<TD>`. Reading
this table with a positional or `<TD>`-based parser returns nothing at all,
which is the same lesson as HANDOFF 3-B(4): the codes are the parse path.

    SPC_NM        유한회사 그레이스홀딩스     the party, one row each
    SPC_ID2       245-87-01068              business registration number
    MDF_DT        2018년 11월 14일           date of the change
    HLD_MTH       장내매수(+)                how
    STK_KND       의결권있는 주식             what class of security
    BFR_MDF_CNT   2,938,938                 held before
    MDF_SDK_CNT   2,383,728                 change
    AFR_MDF_CNT   5,322,666                 held after
    HLD_UNT_PR2   24,557                    executed price

FOUR TRAPS, ALL OBSERVED
------------------------
generation   the price code is HLD_UNT_PR, PR2, PRG or PRJ depending on the
             form version, so it is matched by prefix rather than by name.
line breaks  values arrive with the literal entity `&cr;` inside them
             ("&cr;24,557"), which has to go before the number can be read.
joint filing one filing covers several parties; SPC_NM separates them. Summing
             the table without splitting on it produces a joint total, which is
             what HANDOFF 3-J(3) warns about for Hanjin KAL.
securities   "주식등" includes convertibles and warrants. STK_KND is kept
             verbatim so that ordinary shares can be isolated later rather than
             silently pooled with mezzanine (HANDOFF 3-K(3)).

Prices are absent on some rows - a new filing that reports a position built
before the reporting period has no price to state. Those rows are stored with a
null price rather than dropped, so the share counts still reconcile and the
missing cost is visible instead of assumed.
"""
from __future__ import annotations

import gzip
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from kobep_parser import (decode_dart, read_zip, table_groups,  # noqa: E402
                          canonical_segment)

HOME = os.environ.get("KOBEP_HOME", r"C:\KOBEP")
DOC_ROOT = os.path.join(HOME, "raw", "doc")

SCHEMA = """
CREATE TABLE IF NOT EXISTS filing_transaction (
  rcept_no     TEXT NOT NULL,
  row_no       INTEGER NOT NULL,
  party_name   TEXT,          -- SPC_NM, one row per party in a joint filing
  party_id     TEXT,          -- SPC_ID2, the join key that names cannot be
  change_date  TEXT,          -- MDF_DT, normalised to YYYYMMDD
  method       TEXT,          -- HLD_MTH as filed
  direction    INTEGER,       -- +1 acquisition, -1 disposal, from the (+)/(-)
  security     TEXT,          -- STK_KND verbatim; ordinary vs mezzanine
  shares_before INTEGER,
  shares_change INTEGER,
  shares_after  INTEGER,
  unit_price   INTEGER,       -- executed price, NULL when not stated
  remark       TEXT,
  PRIMARY KEY (rcept_no, row_no)
);
CREATE INDEX IF NOT EXISTS ix_tx_party ON filing_transaction(party_id, change_date);
CREATE INDEX IF NOT EXISTS ix_tx_date ON filing_transaction(change_date);
"""

#: One row is a sequence of TE/TU cells carrying ACODE or AUNIT.
_CELL = re.compile(r'<T[EU]\b[^>]*?(?:ACODE|AUNIT)="([^"]+)"[^>]*>(.*?)</T[EU]>', re.S)
_ROW = re.compile(r"<TR\b[^>]*>(.*?)</TR>", re.S)
_BODY = re.compile(r"<TBODY>(.*?)</TBODY>", re.S)
_TAG = re.compile(r"<[^>]+>")


def text(value: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", value.replace("&cr;", " "))).strip()


#: SQLite stores integers in 64 bits. Anything wider is not a large number,
#: it is a cell whose contents ran together: stripping punctuation from
#: "3,599원(주1)" style text concatenates every digit present, and three cells
#: in the corpus produced 20- and 21-digit "prices" that way. Those are
#: unreadable, so they are stored as absent rather than as a fabricated figure.
_INT64 = 2 ** 63 - 1


def integer(value: str):
    cleaned = re.sub(r"[^\d-]", "", text(value))
    if cleaned in ("", "-"):
        return None
    try:
        number = int(cleaned)
    except ValueError:
        return None
    return number if -_INT64 <= number <= _INT64 else None


_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def price(value: str):
    """An executed price, decimals kept.

    `integer()` strips every non-digit, so 13,269.75 became 1,326,975 - a
    hundred-fold error found by the C11 spot-check (2026-10-04) in 3 of 200
    sampled rows - and it ran two figures together: "8,190/6,000" became
    81,906,000. Filers decorate a single price freely - "(5,827)",
    "21,978(원)", "처분 (684)", "3,193원/주" - so the rule is: exactly one
    well-formed number in the cell is the price; none, or more than one
    ("8,190/6,000", "87,401 (87,576)", the malformed "20,101,26"), is absent.
    """
    v = text(value)
    numbers = _NUMBER.findall(v)
    if len(numbers) != 1:
        return None
    rest = v.replace(numbers[0], "", 1)
    if re.search(r"\d", rest):
        return None
    number = float(numbers[0].replace(",", ""))
    return int(number) if number.is_integer() else round(number, 4)


def date8(value: str):
    """Dates appear as 2018년 11월 14일, 2022.05.16 or 20180114."""
    digits = re.findall(r"\d+", text(value))
    if len(digits) >= 3:
        y, m, d = digits[0], digits[1], digits[2]
        if len(y) == 4:
            return f"{y}{int(m):02d}{int(d):02d}"
    if len(digits) == 1 and len(digits[0]) == 8:
        return digits[0]
    return None


def direction_of(method: str):
    if "(+)" in method:
        return 1
    if "(-)" in method or "(－)" in method:
        return -1
    return None


def rows_from(xml: str) -> list[dict]:
    groups = table_groups(xml)
    segment = canonical_segment(groups.get("HLD_MTH", []))
    if not segment:
        return []
    # The group holds more than one table. From form 4.4 the first is a caption
    # carrying only "(단위 : 주, 원)", and the transactions are in the one after
    # it. Reading only the first TBODY returned the caption and an empty result
    # for every filing on 4.4 and later - 4,190 documents, including all of
    # 2026 - while older forms happened to put the data first and looked fine.
    bodies = [match.group(1) for match in _BODY.finditer(segment)]
    if not bodies:
        return []

    out = []
    for raw_row in _ROW.finditer("\n".join(bodies)):
        cells = {}
        for cell in _CELL.finditer(raw_row.group(1)):
            code, value = cell.group(1), cell.group(2)
            # The price code is generation-dependent; fold the variants.
            key = "HLD_UNT_PR" if code.startswith("HLD_UNT_PR") else code
            cells.setdefault(key, value)
        if not cells:
            continue
        change = integer(cells.get("MDF_SDK_CNT", ""))
        after = integer(cells.get("AFR_MDF_CNT", ""))
        if change is None and after is None:
            continue          # a placeholder row for a party with no movement
        method = text(cells.get("HLD_MTH", ""))
        out.append({
            "party_name": text(cells.get("SPC_NM", "")) or None,
            "party_id": text(cells.get("SPC_ID2", "")) or None,
            "change_date": date8(cells.get("MDF_DT", "")),
            "method": method or None,
            "direction": direction_of(method),
            "security": text(cells.get("STK_KND", "")) or None,
            "shares_before": integer(cells.get("BFR_MDF_CNT", "")),
            "shares_change": change,
            "shares_after": after,
            "unit_price": price(cells.get("HLD_UNT_PR", "")),
            "remark": text(cells.get("RMK", "")) or None,
        })
    return out


def documents(wanted: set[str]) -> list[str]:
    """5 % filings only. raw/doc also holds treasury-share reports, which have
    no HLD_MTH table and would just inflate the 'no detail table' count."""
    paths = []
    for root, _dirs, names in os.walk(DOC_ROOT):
        for name in names:
            if name.endswith(".xml.gz") and name.replace(".xml.gz", "") in wanted:
                paths.append(os.path.join(root, name))
    return sorted(paths)


def main() -> None:
    conn = sqlite3.connect(os.path.join(HOME, "ledger.db"), timeout=1800)
    conn.execute("PRAGMA busy_timeout = 1800000")
    conn.executescript(SCHEMA)

    wanted = {r[0] for r in conn.execute('SELECT rcept_no FROM report_index')}
    paths = documents(wanted)
    print(f"documents on disk: {len(paths):,}")

    # Resumable by default. --rebuild re-reads every filing, which a change to
    # how a cell is read (the price fix of 2026-10-04) requires; refine_
    # transactions.py must run afterwards, since a replaced row loses flow_kind.
    done = set() if "--rebuild" in sys.argv else {r[0] for r in conn.execute(
        "SELECT DISTINCT rcept_no FROM filing_transaction")}
    written, empty, failed = 0, 0, 0
    reasons: dict[str, int] = {}

    for i, path in enumerate(paths, 1):
        rcept_no = os.path.basename(path).replace(".xml.gz", "")
        if rcept_no in done:
            continue
        try:
            # Stored as gzip around the API's ZIP response, so the name says
            # .xml.gz but two layers come off before there is any XML.
            with gzip.open(path, "rb") as handle:
                blob = handle.read()
            xml, _enc = (read_zip(blob) if blob[:2] == b"PK"
                         else decode_dart(blob))
            rows = rows_from(xml)
        except Exception as error:
            # A bare counter here once hid a coding error as a data problem:
            # every document "failed" and the run reported an empty table
            # rather than a broken parser. Keep the reason.
            failed += 1
            reasons[type(error).__name__] = reasons.get(type(error).__name__, 0) + 1
            continue
        if not rows:
            empty += 1
            continue
        # Columns are named rather than positional: refine_transactions.py adds
        # flow_kind afterwards, so a bare VALUES list stops matching the table.
        conn.executemany(
            "INSERT OR REPLACE INTO filing_transaction"
            "(rcept_no,row_no,party_name,party_id,change_date,method,direction,"
            " security,shares_before,shares_change,shares_after,unit_price,remark)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(rcept_no, n, r["party_name"], r["party_id"], r["change_date"],
              r["method"], r["direction"], r["security"], r["shares_before"],
              r["shares_change"], r["shares_after"], r["unit_price"],
              r["remark"]) for n, r in enumerate(rows)])
        written += len(rows)
        if i % 1000 == 0:
            conn.commit()
            print(f"  {i:,}/{len(paths):,}  rows {written:,}", flush=True)
    conn.commit()

    total, docs = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT rcept_no) FROM filing_transaction"
    ).fetchone()
    priced = conn.execute(
        "SELECT COUNT(*) FROM filing_transaction WHERE unit_price IS NOT NULL"
    ).fetchone()[0]
    dated = conn.execute(
        "SELECT COUNT(*) FROM filing_transaction WHERE change_date IS NOT NULL"
    ).fetchone()[0]

    print(f"\nfiling_transaction: {total:,} rows from {docs:,} documents")
    print(f"  with a date        {dated:,}  ({dated/total:.1%})")
    print(f"  with a unit price  {priced:,}  ({priced/total:.1%})")
    print(f"  documents with no detail table: {empty:,}   unreadable: {failed:,}")
    if reasons:
        print(f"  failure reasons: {reasons}")

    print("\nmethod mix (top 12)")
    for method, n, p in conn.execute(
            "SELECT method, COUNT(*), SUM(unit_price IS NOT NULL) "
            "FROM filing_transaction GROUP BY 1 ORDER BY 2 DESC LIMIT 12"):
        print(f"  {str(method)[:24]:26s} {n:7,d}  priced {p/n:5.0%}")


if __name__ == "__main__":
    main()
