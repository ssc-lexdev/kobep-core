# KOBEP-Core: code

Code for **KOBEP-Core: Korean blockholder entry and payout ledger, KOSPI 2011-2025** (version 1.0).

The data are not in this repository. They are deposited at Zenodo:

- Version 1.0: https://doi.org/10.5281/zenodo.23663204
- All versions (resolves to the latest): https://doi.org/10.5281/zenodo.23663203

This repository holds the same `code/`, `docs/` and `fixtures/` folders as the Zenodo deposit,
so the extraction, parsing, audit, validation and figure code can be read, cited and reused
without downloading the data.

## Contents

| Folder | What it holds |
|---|---|
| `code/parser/` | parser for the five percent beneficial-ownership filings, with tests |
| `code/audit/` | release audits: joins, natural persons, price sources, secrets, package checksums |
| `code/validation/` | spot-check sampling and scoring scripts |
| `code/manuscript/` | figure code for the Data Descriptor |
| `code/examples/` | filtering and joining examples (not a recommended research design) |
| `code/read_kobep.py` | loader that keeps identifier columns as text |
| `docs/` | codebook, variable dictionary, vocabulary, coverage and validation summaries |
| `fixtures/` | filings used by the parser tests |

## Use

Python 3.14 with the packages in `code/requirements.txt`. To run the audits or rebuild figures,
download the Zenodo deposit and run the scripts from its root, which adds the `data/` and
`manifest/` folders this repository leaves out. Run Python with `-B` inside the deposit so that
no `__pycache__` folders are written into it.

## Licence and citation

Code: MIT (`LICENSE`). Data and documentation: CC BY 4.0 (`LICENSE-DATA.txt`).
Please cite the dataset as given in `CITATION.cff`:

Choi, S. & Oh, T. KOBEP-Core: Korean blockholder entry and payout ledger, KOSPI 2011-2025.
*Zenodo* https://doi.org/10.5281/zenodo.23663204 (2026).
