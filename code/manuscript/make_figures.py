#!/usr/bin/env python3
"""Figures for the Data Descriptor, drawn from the release files.

Fig. 1  workflow: DART endpoints -> stored payloads -> parsing -> ledgers ->
        entities and events -> release, with the audits that gate it.
Fig. 2  how the twelve files join.
Fig. 3  data overview: filings by receipt year and form; relationships by
        entry year and declared class; exits and censoring by year.
Fig. 4  spot-check: error rate and Wilson 95 % interval per checked field.

    python make_figures.py --release <root> --spotcheck <spotcheck_summary.csv> --out <dir>

Only release files and the aggregate spot-check table are read; no exchange
data. Output: PNG (300 dpi) and PDF per figure.
"""
from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8,
                     "axes.spines.top": False, "axes.spines.right": False})
BLUE, ORANGE, GREEN, GREY, RED = "#3274a1", "#e1812c", "#3a923a", "#9e9e9e", "#c03d3e"


def save(fig, out, name):
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(out, f"{name}.{ext}"), dpi=300, bbox_inches="tight")
    plt.close(fig)


def box(ax, x, y, w, h, title, body="", color=BLUE, fs=7.0):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.015",
                                fc=color, ec="none", alpha=0.12))
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.015",
                                fc="none", ec=color, lw=1))
    ax.text(x + w / 2, y + h - 0.02, title, ha="center", va="top", weight="bold", fontsize=fs)
    if body:
        ax.text(x + w / 2, y + h - 0.07, body, ha="center", va="top", fontsize=fs - 1.3,
                linespacing=1.35)


def arrow(ax, x0, y0, x1, y1):
    ax.annotate("", (x1, y1), (x0, y0),
                arrowprops=dict(arrowstyle="-|>", color="#444", lw=0.9))


def fig_workflow(out):
    fig, ax = plt.subplots(figsize=(9.0, 4.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_xlim(-0.01, 1.0)
    cols = [0.005, 0.26, 0.515, 0.77]
    w, h = 0.215, 0.38
    box(ax, cols[0], 0.58, w, h, "1  Collection (OpenDART)",
        "list.json D001: filing index\ndocument.xml: filing text\nalotMatter, tesstkAcqsDspsSttus,\n"
        "stockTotqySttus: annual report\nfnlttSinglAcntAll: statements\nlist.json B001/E001 +\n"
        "document.xml: buyback reports\ncompany.json: profile", BLUE)
    box(ax, cols[1], 0.58, w, h, "2  Storage",
        "single-threaded, resumable queue\nstatus 000 accepted only\npayload stored unmodified\n"
        "SHA-256 per payload\nstatus 014: listed, not parsed\n(270 filings)", BLUE)
    box(ax, cols[2], 0.58, w, h, "3  Parsing",
        "ACODE / AUNIT codes, not labels\nCP949 behind UTF-8 declaration\n"
        "ACLASS=EXTRACTION (amended)\nforms 2.2-6.0\ntransaction rows by code\n"
        "one-number price rule\nflow_kind, unit_price_kind", ORANGE)
    box(ax, cols[3], 0.58, w, h, "4  Ledgers",
        "filing index\nposition ledger\ntransaction ledger\nterms-change rows\n"
        "firm-year financials\nfirm-year payout\n(reported buybacks)", ORANGE)
    box(ax, cols[3], 0.07, w, h, "5  Entities and events",
        "registration-number entities\nentry / peak / exit\nre-entry, censoring\n"
        "left truncation, filing lag\nrelation-to-issuer class\nholding purpose\n"
        "(coded / form / text rule)", GREEN)
    box(ax, cols[2], 0.07, w, h, "6  Release scope",
        "legal persons only\n(birth-date IDs withheld,\nsignatory names cut)\n"
        "ledger 2011-2025\nfirm-year 2016-2025\nevents observed to 2025-12-31\n"
        "no exchange-origin variable", GREEN)
    box(ax, cols[1], 0.07, w, h, "7  Audits (release gate)",
        "keys and foreign keys\nno natural person\nno exchange-price path\n"
        "no credentials\nevent dates <= 2025-12-31\nno stray files, checksums\n"
        "two runs, same checksums", RED)
    box(ax, cols[0], 0.07, w, h, "8  Deposit",
        "12 CSV files\ncodebook, dictionary,\nvocabulary, coverage,\nvalidation summary\n"
        "per-filing provenance\ncode and parser fixtures", GREY)
    for a, b in ((0, 1), (1, 2), (2, 3)):
        arrow(ax, cols[a] + w, 0.77, cols[b], 0.77)
    arrow(ax, cols[3] + w / 2, 0.58, cols[3] + w / 2, 0.45)
    for a, b in ((3, 2), (2, 1), (1, 0)):
        arrow(ax, cols[a], 0.25, cols[b] + w, 0.25)
    save(fig, out, "fig1_workflow")


def fig_schema(out, rows):
    fig, ax = plt.subplots(figsize=(8.0, 4.2))
    ax.set_xlim(-0.02, 1.03)
    ax.set_ylim(-0.02, 1)
    ax.axis("off")
    w, h = 0.19, 0.13

    def node(x, y, name, key, color):
        n = rows.get(f"kobep_{name}.csv")
        box(ax, x, y, w, h, name, f"key: {key}\n{n:,} rows" if n else f"key: {key}", color, fs=6.6)
        return (x, y)

    def hline(a, b, label):
        y = a[1] + h / 2
        ax.plot([a[0] + w, b[0]], [y, y], color="#555", lw=0.8)
        ax.text((a[0] + w + b[0]) / 2, y + 0.015, label, fontsize=5.6, ha="center", color="#333")

    def vline(a, b, label):
        x = a[0] + w / 2
        ax.plot([x, x], [a[1], b[1] + h], color="#555", lw=0.8)
        ax.text(x + 0.008, (a[1] + b[1] + h) / 2, label, fontsize=5.6, va="center", color="#333")

    xs = [0.0, 0.27, 0.54, 0.81]
    fm = node(0.405, 0.85, "firm_master", "corp_code, fiscal_year", GREY)
    fi = node(xs[0], 0.57, "filing_index", "rcept_no", BLUE)
    fe = node(xs[1], 0.57, "filing_entity", "rcept_no", BLUE)
    be = node(xs[2], 0.57, "blockholder_entity", "reporter_id", GREEN)
    ev = node(xs[3], 0.57, "event_ledger", "event_id", GREEN)
    po = node(xs[0], 0.29, "position_ledger", "rcept_no", ORANGE)
    tx = node(xs[1], 0.29, "transaction_ledger", "rcept_no, row_no", ORANGE)
    te = node(xs[2], 0.29, "terms_event", "rcept_no, row_no", ORANGE)
    sc = node(xs[3], 0.29, "security_class", "security_ko", GREY)
    node(0.135, 0.0, "firmyear_financial", "corp_code, fiscal_year", GREY)
    node(0.405, 0.0, "firmyear_payout", "corp_code, fiscal_year", GREY)
    node(0.675, 0.0, "missing_reasons", "file, variable, rule", RED)
    hline(fi, fe, "rcept_no")
    hline(fe, be, "reporter_id")
    hline(be, ev, "reporter_id")
    vline(fi, po, "rcept_no")
    vline(fe, tx, "rcept_no")
    for a, rad in ((fi, 0.15), (ev, -0.15)):
        ax.annotate("", (a[0] + w / 2, a[1] + h), (fm[0] + (0 if a is fi else w), fm[1] + h / 2),
                    arrowprops=dict(arrowstyle="-", color="#555", lw=0.8,
                                    connectionstyle=f"arc3,rad={rad}"))
    ax.text(0.2, 0.89, "corp_code", fontsize=5.6)
    ax.text(0.74, 0.89, "corp_code", fontsize=5.6)
    ax.text(0.5, 0.235, "terms_event joins filing_index on rcept_no; security_class maps "
            "security_ko in transactions and terms; event_ledger.entry_rcept_no points to "
            "position_ledger", fontsize=5.6, ha="center", color="#333")
    ax.text(0.5, 0.17, "firm-year files join firm_master on (corp_code, fiscal_year); "
            "missing_reasons documents blank cells in every file", fontsize=5.6, ha="center",
            color="#333")
    save(fig, out, "fig2_schema")


def fig_overview(out, data):
    rd = lambda f, c: pd.read_csv(os.path.join(data, f), dtype=str, usecols=c)  # noqa: E731
    idx = rd("kobep_filing_index.csv", ["receipt_date", "form_kind"])
    ev = rd("kobep_event_ledger.csv", ["entry_receipt_date", "class_at_entry", "exit_date",
                                       "exit_censored"])
    years = list(range(2011, 2026))
    idx["y"] = idx.receipt_date.str[:4].astype(int)
    f = idx.groupby(["y", "form_kind"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    ev["y"] = ev.entry_receipt_date.str[:4].astype(int)
    c = ev.groupby(["y", "class_at_entry"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    ex = ev[ev.exit_censored == "0"].exit_date.str[:4].astype(int).value_counts().reindex(
        years, fill_value=0)
    # (d) payout file, descriptive only: share of firm-years with a cash dividend and with a
    # company-reported repurchase amount, among firm-years where the amount is not blank
    po = pd.read_csv(os.path.join(data, "kobep_firmyear_payout.csv"),
                     usecols=["fiscal_year", "div_cash_total", "buyback_value"])
    g = po.groupby("fiscal_year")
    div_share = 100 * g.div_cash_total.apply(lambda v: (v > 0).sum() / v.notna().sum())
    bb_share = 100 * g.buyback_value.apply(lambda v: (v > 0).sum() / v.notna().sum())

    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.8))
    axes = axes.ravel()
    a = axes[0]
    a.bar(f.index, f.get("standard", 0), color=BLUE, label="Standard form")
    a.bar(f.index, f.get("short", 0), bottom=f.get("standard", 0), color=ORANGE, label="Short form")
    a.axvline(2015.5, color=GREY, ls="--", lw=0.8)
    a.set_title("Filings by receipt year", loc="left", fontsize=8)
    a.set_ylabel("Filings")
    a.set_ylim(0, 1.25 * (f.get("standard", 0) + f.get("short", 0)).max())
    a.legend(frameon=True, framealpha=0.9, edgecolor="none", fontsize=6, loc="upper left")
    b = axes[1]
    bottom = 0
    for cls, col in (("OUTSIDER", BLUE), ("INSIDER", ORANGE), ("UNCERTAIN", GREY)):
        vals = c.get(cls, pd.Series(0, index=years))
        b.bar(c.index, vals, bottom=bottom, color=col, label=cls.capitalize())
        bottom = bottom + vals
    b.axvline(2015.5, color=GREY, ls="--", lw=0.8)
    b.set_title("Relationships by entry year", loc="left", fontsize=8)
    b.legend(frameon=True, framealpha=0.9, edgecolor="none", fontsize=6, loc="upper right")
    d = axes[2]
    d.bar(ex.index, ex.values, color=GREEN)
    d.set_title("Observed below-threshold exits", loc="left", fontsize=8)
    b.set_ylabel("Relationships")
    d.set_ylabel("Relationships")
    e = axes[3]
    e.plot(div_share.index, div_share.values, "o-", ms=3, color=BLUE, label="Cash dividend")
    e.plot(bb_share.index, bb_share.values, "s-", ms=3, color=ORANGE, label="Reported repurchase amount")
    e.set_ylim(0, 100)
    e.set_xlim(2010.4, 2025.6)
    e.set_title("Firm-years with a payout", loc="left", fontsize=8)
    e.set_ylabel("Share of firm-years (%)")
    e.legend(frameon=True, framealpha=0.9, edgecolor="none", fontsize=6, loc="center left")
    for letter, axx in zip("abcd", axes):
        axx.set_xticks([2011, 2015, 2020, 2025])
        axx.text(-0.16, 1.08, letter, transform=axx.transAxes, weight="bold", fontsize=9)
        axx.set_xlabel("Fiscal year" if axx is e else "Year")
    fig.tight_layout()
    save(fig, out, "fig3_overview")


def fig_spotcheck(out, path):
    s = pd.read_csv(path)
    s["label"] = s.sheet.str[:-1] + ": " + s.field
    s = s.iloc[::-1]
    fig, ax = plt.subplots(figsize=(4.6, 4.4))
    y = range(len(s))
    ax.errorbar(100 * s.error_rate, y,
                xerr=[100 * (s.error_rate - s.wilson95_lo), 100 * (s.wilson95_hi - s.error_rate)],
                fmt="o", ms=3, color=BLUE, ecolor=GREY, elinewidth=1, capsize=1.5)
    ax.set_yticks(list(y))
    ax.set_yticklabels(s.label, fontsize=6)
    ax.set_xlabel("Error rate (%), Wilson 95% interval")
    ax.set_xlim(-0.2, max(4.0, 100 * s.wilson95_hi.max() + 0.5))
    fig.tight_layout()
    save(fig, out, "fig4_spotcheck")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--release", default=r"C:\KOBEP\release\KOBEP-Core_v1.0")
    ap.add_argument("--spotcheck", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    import json
    rows = json.load(open(os.path.join(args.release, "manifest", "extract_report.json"),
                          encoding="utf-8"))["rows"]
    fig_workflow(args.out)
    fig_schema(args.out, rows)
    fig_overview(args.out, os.path.join(args.release, "data"))
    fig_spotcheck(args.out, args.spotcheck)
    print("figures ->", args.out)


if __name__ == "__main__":
    main()
