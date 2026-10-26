#!/usr/bin/env python3
"""Write docs/kobep_vocabulary.csv - English glosses for Korean values in the release.

Data values are kept as filed (D13 covers code and documentation, not the
filers' own vocabulary), so `method_ko` and `security_ko` stay in Korean. This
table translates every distinct value that occurs. A value seen in the data but
missing here fails the run, so the vocabulary cannot fall behind the data.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

METHOD = {
 "장내매도(-)": "on-market sale", "장내매수(+)": "on-market purchase",
 "기타(-)": "other (disposal)", "기타(+)": "other (acquisition)",
 "신규보고(+)": "holding at first report", "차입(+)": "borrowed shares",
 "장외매도(-)": "off-market sale", "장외매수(+)": "off-market purchase",
 "행사가액조정": "exercise-price adjustment", "시간외매매(-)": "after-hours sale",
 "시간외매매(+)": "after-hours purchase", "유상신주취득(+)": "rights / paid-in new shares",
 "CB인수(+)": "convertible bond subscribed", "전환등(-)": "conversion (disposal side)",
 "대여(-)": "shares lent", "전환사채의권리행사(+)": "convertible bond conversion",
 "무상신주취득(+)": "bonus shares received", "출자전환": "debt-to-equity swap",
 "제3자배정유상증자(+)": "third-party allotment",
 "합병(+)": "merger (acquisition)", "합병(-)": "merger (disposal)",
 "자본감소": "capital reduction", "특별관계해소(-)": "related-party relation ended",
 "신규상장(+)": "new listing", "회사분할": "corporate demerger",
 "담보주식처분권보유": "right to dispose of pledged shares", "주식배당(+)": "stock dividend",
 "주식분할": "stock split", "주식병합": "reverse split",
 "교환(-)": "exchange (disposal)", "교환(+)": "exchange (acquisition)",
 "BW인수(+)": "bond with warrant subscribed",
 "신규상장(무상취득)(+)": "new listing (acquired free)",
 "신규상장(유상취득)(+)": "new listing (acquired for value)",
 "전환권등소멸(-)": "conversion right extinguished", "계약중도해지": "contract terminated early",
 "신규등록(+)": "new registration", "신주인수권증권의권리행사(+)": "warrant exercise",
 "공개매수(+)": "tender offer (bought)", "공개매수청약(-)": "tender offer (tendered)",
 "콜옵션권리행사배정에따른주식처분(-)": "disposal on call-option assignment",
 "교환사채의권리행사(+)": "exchangeable bond exercise",
 "신주인수권사채의권리행사(+)": "bond-with-warrant exercise", "수증(+)": "gift received",
 "증여(-)": "gift given", "풋옵션권리행사에따른주식처분(-)": "disposal on put exercise",
 "신고대량매매(+)": "reported block purchase", "신고대량매매(-)": "reported block sale",
 "주식소각": "share retirement",
 "콜옵션권리행사에따른주식취득(+)": "acquisition on call exercise",
 "실권주인수(+)": "forfeited shares taken up", "계열사편입(+)": "joined the group (affiliate)",
 "풋옵션권리행사배정에따른주식취득(+)": "acquisition on put assignment",
 "대물변제(-)": "payment in kind (given)", "대물변제수령(+)": "payment in kind (received)",
 "계약기간만료": "contract expired", "콜옵션권리행사에따른CB취득(+)": "CB acquired on call exercise",
 "주식매수선택권부여(+)": "stock option granted",
 "주식매수선택권부여취소(-)": "stock option grant cancelled",
 "주식매수선택권행사(-)": "stock option exercised (disposal)",
 "주식매수선택권행사(+)": "stock option exercised (acquisition)",
 "매출(-)": "secondary offering", "주식매수청구권 행사(-)": "appraisal right exercised",
 "콜옵션취득(+)": "call option acquired", "우선주무배당(+)": "preferred share voting revived (no dividend)",
 "임원퇴임(-)": "officer retired", "상속(+)": "inheritance", "수증취소(-)": "gift cancelled",
 "장내매수(+)장내매수(+)": "on-market purchase (label duplicated by filer)",
 "신규주요주주(+)": "became a major shareholder", "신규선임(+)": "newly appointed",
 "자사주펀드해지(-)": "treasury-share fund terminated",
}


def gloss(value: str, table: dict) -> str | None:
    if value in table:
        return table[value]
    if "?" in value:
        return "unreadable in the filing (encoding damage)"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.0")
    args = ap.parse_args()
    data = os.path.join(args.release, "data")
    rows, missing = [], []
    for f, col in (("kobep_transaction_ledger.csv", "method_ko"),
                   ("kobep_terms_event.csv", "method_ko")):
        vc = pd.read_csv(os.path.join(data, f), dtype=str, usecols=[col],
                         keep_default_na=False)[col].value_counts()
        for v, n in vc.items():
            if not v:
                continue
            g = gloss(v, METHOD)
            if g is None:
                missing.append(v)
            rows.append((f, col, v, g, int(n)))
    sec = pd.read_csv(os.path.join(data, "kobep_security_class.csv"), dtype=str,
                      keep_default_na=False)
    rows += [("kobep_security_class.csv", "security_ko", r.security_ko, r.security_class, None)
             for r in sec.itertuples()]
    if missing:
        print("NO GLOSS:", missing, file=sys.stderr)
        sys.exit(1)
    out = pd.DataFrame(rows, columns=["file", "variable", "value_ko", "gloss_en", "n_rows"])
    dest = os.path.join(args.release, "docs", "kobep_vocabulary.csv")
    out.to_csv(dest, index=False, lineterminator="\n")
    print(f"{len(out)} values -> {dest}")


if __name__ == "__main__":
    main()
