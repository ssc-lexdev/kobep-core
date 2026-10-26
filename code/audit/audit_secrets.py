#!/usr/bin/env python3
"""Audit: no credential or private path in anything that will be published.

Scans the pipeline source and the release folder for API-key shapes (OpenDART
keys are 40 hex characters, data.go.kr service keys 64), common token prefixes,
and home-directory paths that would expose a user name. Exit status 1 on a hit.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

PATTERNS = {
    "hex40 (OpenDART key shape)": re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])"),
    "hex64 (data.go.kr key shape)": re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])"),
    "token prefix": re.compile(r"\b(sk-[A-Za-z0-9]{16,}|sbp_[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,})"),
    "home path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.I),
    "key assignment": re.compile(r"(crtfc_key|serviceKey|api[_-]?key)\s*[=:]\s*['\"][^'\"]{8,}", re.I),
}
SKIP_EXT = {".gz", ".zip", ".png", ".pdf"}
#: checksums.sha256 is a list of SHA-256 digests - 64 hex characters by design.
SKIP_FILES = {"checksums.sha256", "rcept_no_manifest.csv"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("roots", nargs="*",
                    default=[here, r"C:\KOBEP\release\KOBEP-Core_v1.0"])
    args = ap.parse_args()
    hits = []
    for root in args.roots:
        for dirpath, _, names in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for name in names:
                if os.path.splitext(name)[1] in SKIP_EXT or name in SKIP_FILES:
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        for label, pat in PATTERNS.items():
                            if pat.search(line):
                                hits.append((label, path, i))
    for label, path, line in hits[:50]:
        print(f"HIT  {label:28s} {path}:{line}")
    if hits:
        print(f"FAIL: {len(hits)} hit(s)")
        sys.exit(1)
    print(f"PASS: no secrets in {', '.join(args.roots)}")


if __name__ == "__main__":
    main()
