# KOBEP-Core codebook, version 1.1

## 1. What the dataset is

KOBEP-Core is a relational dataset compiled from Korean statutory disclosures.
Its centre is the 5 % beneficial-ownership report (주식등의 대량보유상황보고서)
required by Article 147 of the Financial Investment Services and Capital Markets
Act: anyone who comes to hold 5 % or more of a listed company's voting
securities, or whose holding then changes by one percentage point or more, or
whose holding purpose changes, must file. KOBEP-Core turns every such filing on
a KOSPI company by a legal-person filer, 2011-2025, into a filing ledger, a
transaction ledger, blockholder entities, and issuer x blockholder relationships,
and joins them to the issuers' annual financials and shareholder payouts for
2016-2025.

Source: DART (dart.fss.or.kr), the Financial Supervisory Service's electronic
disclosure system, through the OpenDART API: `list.json` (filing index,
detail type D001), `document.xml` (filing text), the annual-report endpoints
for dividends, treasury shares and share counts, `fnlttSinglAcntAll` (full
financial statements) and `company.json` (company profile). Nothing comes from
a commercial database or from the exchange.

## 2. Scope decisions

- **Universe.** 883 companies listed on KOSPI at any time in 2016-2025 whose
  filings are in scope. Ledger rows from 2011-2015 are the pre-window history of
  these companies (658 of them have legal-person filings in those years), not a
  census of KOSPI then.
  `in_core_window` marks rows received 2016-2025.
- **Legal persons only.** Natural-person filers, and natural-person rows inside
  corporate filings, are excluded. A person is identified by a birth-date
  identifier (valid YYMMDD) under a non-corporate name, a Hangul personal-name
  form without a registration number, or a name the ledger knows to belong to an
  individual filer. Nothing is pseudonymised: a receipt number links back to
  the public filing, so masking would not de-identify.
- **No KRX-origin variables.** No exchange price, market value or return
  variable. Prices and yields stated in the disclosures themselves - the
  filer-stated `unit_price`, the issuer-stated dividend yield and buyback
  amounts - are kept as filed and flagged (`DART_DISCLOSED` in the dictionary;
  `unit_price_kind`).
- **Language.** Names of companies, funds and parties are kept as filed, in
  Korean, and are not translated or romanised: use `corp_code`, `reporter_id`
  and `rcept_no` as keys. Controlled values carry English beside the Korean:
  `method_en`, `report_name_en`, `industry_name_en` (official KSIC 11th-revision
  titles) and `security_class`; `corp_name_en` is the English name registered
  with DART. Identifier cells in which a filer wrote text such as 해당없음
  instead of a number are released blank.
- **No free text, no human verdicts.** Free-text fields name people; the holding
  purpose prose is released only as a derived category with its basis.
  No human adjudication of individual records is released.
- **No treatment labels.** `code/examples/make_treatment.py` shows how
  event-level indicators (for example, outside entries by holding purpose or
  acquisition route) can be built from these files. It is an example of use,
  not part of the data definition.
- **No ownership totals.** The ratios in the position ledger are the
  combined ratios of the filer and its related parties as filed. Natural-person
  rows were removed but the ratios were not recomputed, so they can include
  shares of related natural persons; summed across filings, holders or groups
  they count overlapping holdings more than once and do not measure ownership
  concentration. No ownership summary is released.

## 3. How the files were built

**Parsing.** DART filing XML is code-driven: data cells carry `ACODE` and
controlled values carry `AUNIT`/`AUNITVALUE`. The parser reads codes, not
labels. Text up to 2020 is CP949 despite a UTF-8 declaration. Amended filings
contain pre- and post-amendment tables; values come from tables marked
`ACLASS="EXTRACTION"` (post-amendment).

**Entities.** Filers are resolved to reporting entities on their registration
number (business or foreign registration; for individuals a birth date -
individuals are then excluded). One entity keeps one registration number
throughout; its `name` is the name on its most recent filing. Entities are not
merged across registration numbers: a fund house filing under several foreign
registrations is several entities. `needs_review` flags entities whose names
and numbers do not map one-to-one (table in section 4). Organisations without
a registration number - mostly employee share ownership associations - often
filed under their representative's birth date; they are kept with
`id_kind = ID_WITHHELD` and no `id_value`. Related-party identifiers that read
as a birth date (YYMMDD) are withheld the same way, and a signatory's name
filed as part of an organisation's name ("... 우리사주조합장 <name>",
"(대표조합원 <name>)") is cut from it.

**Events.** One event per issuer x blockholder pair observed in 2016-2025.
Entry is the first filing with a ratio; exit is the start of the final run
below 5 %; a holder who dips below and returns has re-entered (`n_reentries`).
An exit that is never filed - a slide from 5.4 % to 4.9 % needs no report - is
censored, and `censoring_kind` separates holders still filing (last filing
within 12 months of the cutoff) from dormant ones and lapse candidates (no
filing for 36 months, last ratio below 5.5 %). Entry is left-truncated when an
earlier holding is evident (an earlier index filing whose text DART did not
serve, or a prior ratio already >= 5 %). Events are built only from filings
received up to 2025-12-31, which is also the observation cutoff, so every
event field can be recomputed from the released filing ledger.

**Classification.** `outsider_class` is a rule on the filer's declared relation
to the issuer (`relation_to_issuer_code`, FLT_CRP_RLT):

| Code | Declared relation | outsider_class |
|---|---|---|
| 13 | Shareholder | OUTSIDER |
| 01 | Registered officer | INSIDER |
| 03 | De facto controlling shareholder | INSIDER |
| 04 | Unregistered officer (form 6.0) | INSIDER |
| 10 | Largest shareholder | INSIDER |
| 14 | Affiliated company | INSIDER |
| 15 | Officer of an affiliated company | INSIDER |
| 02 | Major shareholder (>= 10 %) | UNCERTAIN - can be an outside institution |
| 16 | Other | UNCERTAIN |
| blank | - | UNCERTAIN |

UNCERTAIN is not guessed.

**Amendments.** `is_amendment` marks a filing that is itself an amendment
(index: the title carries 정정; position ledger: the filing text says so). An
original that was later corrected is 0. Values are read from the
post-amendment tables (`ACLASS="EXTRACTION"`). The ledgers keep every filing as
received, so an original and its amendment both appear. Since v1.1,
`superseded_by` gives, for every filing received before the latest amendment in
its set (same `reporter_id`, `corp_code` and `obligation_date`), the receipt
number of that amendment; drop rows with `superseded_by` filled before summing
quantities or amounts. An amendment that changes the obligation date is not
matched.

**Acquisition flags.** `market_purchase` and `involuntary` are computed from the
released transaction rows of the filing (method lists in the dictionary).

**Holding purpose.** The coded purpose (01 influence, 02 passive, 03 general)
exists on the short form from version 3.9 (2020) and on the standard form only
from 4.0 (late 2022). `holding_purpose_code_derived` uses the code where filed;
before that, a short form implies 02 (it was available only to holders without
an influence purpose), and a standard form's purpose prose is classified by
rules. `holding_purpose_basis` says which.

**Payout.** Cash dividends come from the annual report's dividend section; a
section with neither a total nor a per-share figure is an inferred zero
(`div_basis = INFERRED_ZERO`). Buyback amounts are what the company reported:
the cash-flow statement, else the equity statement (lines naming an
acquisition only), else the buyback execution reports. A statement amount is
used only when the treasury-share table shows the parent buying in the market
(directly or through a trust); consolidated amounts without such purchases are
subsidiaries' buybacks or appraisal-right purchases and count as zero payout;
where the separate cash-flow statement shows a purchase but the treasury table
shows none, the amount is missing (`NA_SOURCE_CONFLICT`).

**Prices.** `unit_price` is read only when the cell holds exactly one
well-formed number; cells with two figures ("8,190/6,000") are missing.
`unit_price_kind` says what the number is: EXECUTED_KRW_PER_SHARE on TRADE
rows; REFERENCE_KRW_PER_SHARE on an exercise-price adjustment, a
debt-to-equity swap or another non-trade row; DR_UNIT_UNCONFIRMED on
depositary receipts, whose filings do not state the unit.

## 4. Files


### `kobep_blockholder_entity.csv` - 1,698 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `reporter_id` | KOBEP blockholder entity identifier |  | derived | see blockholder_entity |
| `id_kind` | Kind of identifier the entity is keyed on | code | derived | BRN business registration number; FOREIGN_REG foreign registration; NAME_ONLY no identifier filed; ID_WITHHELD an organisation filed under a person's birth date, which is not released Codes: BRN=1407; FOREIGN_REG=253; ID_WITHHELD=37; NAME_ONLY=1 |
| `id_value` | Business registration or foreign registration number |  | DART |  |
| `name` | Entity name as filed on its most recent filing | text | DART | trade names change; one registration number throughout |
| `name_first_filed` | Entity name as filed on its earliest filing | text | DART |  |
| `name_variants_json` | Names filed in the filing text | JSON list | DART | person names removed |
| `index_names_json` | Names shown on the DART filing index | JSON list | DART | person names removed |
| `entity_type` | Filer type as declared (CRP_TP) | text | DART |  |
| `entity_type_code` | Filer type code (CRP_TP) | code | DART | I domestic corporation; K financial institution; Y pension fund or professional investor; A investment company etc.; N other organisation (domestic); U other organisation (foreign); O foreign corporation; C civil-code partnership; W statutory partnership Codes: A=7; C=47; I=1007; K=175; N=185; O=249; U=1; W=20; Y=7 |
| `entity_type_mixed` | 1 if the entity filed under more than one type | 0/1 | derived | Codes: 0=1637; 1=61 |
| `nationality` | Domestic or foreign, from the declared type | code | derived | Codes: DOMESTIC=1448; FOREIGN=250 |
| `is_nps` | 1 for the National Pension Service | 0/1 | derived | Codes: 0=1697; 1=1 |
| `needs_review` | 1 if entity resolution is flagged for review | 0/1 | derived | Codes: 0=1372; 1=326 |
| `review_reason` | Why the entity is flagged | text | derived |  |

### `kobep_event_ledger.csv` - 3,267 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `event_id` | Event identifier, one per (issuer, blockholder) relationship |  | derived |  |
| `corp_code` | DART issuer identifier (8 digits) |  | DART | join key across files |
| `reporter_id` | KOBEP blockholder entity identifier |  | derived | see blockholder_entity |
| `n_filings` | Filings in the relationship | count | derived |  |
| `entry_rcept_no` | Receipt number of the entry filing |  | DART |  |
| `entry_obligation_date` | Obligation date of the entry filing | date | DART |  |
| `entry_base_date` | As-of date of the entry filing | date | DART |  |
| `entry_receipt_date` | Receipt date of the entry filing | date | DART |  |
| `entry_fy` | Year of entry_obligation_date | year | derived | see entry_filed_late |
| `entry_ratio` | Holding ratio at entry | % | DART | stock-equivalent |
| `prev_ratio` | Prior ratio stated on the entry filing | % | DART |  |
| `entry_report_type` | Report type of the entry filing |  | DART |  |
| `prior_index_filings` | Earlier index filings by the pair whose text was never parsed | count | derived |  |
| `entry_prev_ratio_ge5` | 1 if the entry filing's prior ratio is already >= 5 % | 0/1 | derived | Codes: 0=2761; 1=506 |
| `entry_left_truncated` | 1 if an earlier holding is evident | 0/1 | derived | prior_index_filings > 0 or entry_prev_ratio_ge5 = 1 Codes: 0=2760; 1=507 |
| `is_first_ever` | 1 if a new report with no sign of earlier holding | 0/1 | derived | Codes: 0=515; 1=2752 |
| `is_marginal_entry` | 1 if entry ratio is 5.0-5.3 % | 0/1 | derived | exit least observable: a fall below 5 % may need no report Codes: 0=2252; 1=983 |
| `peak_ratio` | Highest ratio in the relationship | % | derived |  |
| `peak_date` | Obligation date of the peak | date | derived |  |
| `last_observed_ratio` | Ratio on the last filing | % | derived |  |
| `last_obligation_date` | Obligation date of the last filing | date | derived |  |
| `exit_date` | Obligation date of the first filing in the final run below 5 % | date | derived | blank when exit_censored = 1 |
| `exit_type` | OBSERVED_BELOW_THRESHOLD or CENSORED_NO_FILING | code | derived | a sub-1pp slide below 5 % is never filed Codes: CENSORED_NO_FILING=1194; OBSERVED_BELOW_THRESHOLD=2073 |
| `exit_censored` | 1 if no exit is observed | 0/1 | derived | observed through 2025-12-31, the last receipt date in the ledger Codes: 0=2073; 1=1194 |
| `censoring_kind` | STILL_HOLDING / DORMANT / LAPSE_CANDIDATE | code | derived | Codes: DORMANT=506; LAPSE_CANDIDATE=36; STILL_HOLDING=652 |
| `duration_days` | Days from entry to exit or last filing | days | derived |  |
| `n_reentries` | Times the holder crossed back above 5 % | count | derived |  |
| `purpose_at_entry` | Holding-purpose code on the entry filing | code | DART | short form 3.9+ / standard form 4.0+ Codes: 01=156; 02=683; 03=23 |
| `purpose_changed` | 1 if the purpose code changed | 0/1 | derived | Codes: 0=1791; 1=189 |
| `class_at_entry` | Outsider class at entry | code | derived | rule-based; no human verdicts Codes: INSIDER=618; OUTSIDER=1754; UNCERTAIN=895 |
| `class_last` | Outsider class on the last filing | code | derived | Codes: INSIDER=619; OUTSIDER=1835; UNCERTAIN=813 |
| `class_changed` | 1 if the class changed | 0/1 | derived | Codes: 0=2916; 1=351 |
| `transition_date` | Obligation date of the first class change | date | derived |  |
| `is_related_party` | 1 insider, 0 outsider at entry | 0/1 | derived | Codes: 0=1754; 1=618 |
| `joint_at_entry` | 1 if the entry filing was joint | 0/1 | DART | Codes: 0=1719; 1=1548 |
| `unattributable` | 1 if the filer block never parsed | 0/1 | derived | Codes: 0=3267 |
| `entry_before_window` | 1 if the entry was received before 2016 | 0/1 | derived | Codes: 0=2094; 1=1173 |
| `entry_filing_lag_days` | Receipt date minus obligation date of the entry | days | derived |  |
| `entry_filed_late` | 1 if entry_filing_lag_days > 120 | 0/1 | derived | conservative data-quality flag, not a legal determination of late filing Codes: 0=3237; 1=30 |
| `entry_rep_change` | 1 if the entry filing reports a change of the joint group's representative filer | 0/1 | derived | read from the filing's report reason; the group held the shares before, so the entry is not a new holding. Blank if the filing has no reason cell Codes: 0=3135; 1=132 |
| `entry_left_truncated_broad` | 1 if entry_left_truncated = 1 or entry_rep_change = 1 | 0/1 | derived | entry_left_truncated and is_first_ever keep the narrow definition Codes: 0=2638; 1=629 |
| `purpose_at_entry_derived` | Holding purpose at entry, coded or derived | code | derived | as holding_purpose_code_derived on the entry filing Codes: 01=996; 02=2218; 03=23 |
| `purpose_at_entry_basis` | How purpose_at_entry_derived was obtained | code | derived | Codes: CODED=862; FORM_COVER=4; FORM_ELIGIBILITY=1532; TEXT_RULE=839; UNCLASSIFIED=30 |

### `kobep_filing_entity.csv` - 33,238 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `rcept_no` | DART receipt number of the 5 % filing |  | DART | opens the original at dart.fss.or.kr/dsaf001/main.do?rcpNo= |
| `reporter_id` | KOBEP blockholder entity identifier |  | derived | see blockholder_entity |

### `kobep_filing_index.csv` - 33,508 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `rcept_no` | DART receipt number of the 5 % filing |  | DART | opens the original at dart.fss.or.kr/dsaf001/main.do?rcpNo= |
| `corp_code` | DART issuer identifier (8 digits) |  | DART | join key across files |
| `receipt_date` | Date DART received the filing | date | DART |  |
| `in_core_window` | 1 if received 2016-01-01 to 2025-12-31 | 0/1 | derived | 0 = pre-window history 2011-2015 of panel firms Codes: 0=10543; 1=22965 |
| `form_kind` | standard or short (약식, professional investors) form |  | DART |  |
| `is_amendment` | 1 if the filing is itself an amendment (title carries 정정) | 0/1 | derived | an original that was later corrected is 0 Codes: 0=32483; 1=1025 |
| `parsed` | 1 if the filing text was retrieved and parsed | 0/1 | derived | 0 = DART did not serve the text (status 014) Codes: 0=270; 1=33238 |
| `report_name_ko` | Report title as listed by DART | text (ko) | DART |  |
| `report_name_en` | English rendering of report_name_ko | text | derived | standard or short form; [Amendment] for 기재정정 |

### `kobep_firm_master.csv` - 11,837 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `corp_code` | DART issuer identifier (8 digits) |  | DART | join key across files |
| `fiscal_year` | Fiscal year of the annual report | year | DART |  |
| `stock_code` | KRX stock code in that year |  | DART |  |
| `corp_name_ko` | Company name (Korean) | text (ko) | DART |  |
| `corp_name_en` | Company name (English, as registered with DART) | text | DART |  |
| `market` | Market | code | DART | KOSPI Codes: KOSPI=11837 |
| `is_listed` | 1 if listed in that year | 0/1 | derived | annual-report basis Codes: 1=11837 |
| `is_spv` | 1 for special-purpose vehicles | 0/1 | derived | Codes: 0=11837 |
| `is_financial` | 1 for financial firms | 0/1 | derived | see firm_flag_basis Codes: 0=11051; 1=786 |
| `is_holding` | 1 for holding companies | 0/1 | derived | see firm_flag_basis Codes: 0=10913; 1=924 |
| `delisting_date` | Delisting date | date | DART |  |
| `is_partial_year` | 1 if listed for part of the year | 0/1 | derived | Codes: 0=11797; 1=40 |
| `ksic_code` | Korean Standard Industrial Classification code | code | DART |  |
| `industry_name_ko` | KSIC 11th-revision title of ksic_code (Korean) | text (ko) | DART | Statistics Korea classification; code reported in DART company.json |
| `industry_name_en` | KSIC 11th-revision title of ksic_code (English) | text | DART | official English title |
| `fiscal_month` | Fiscal year-end month | month | DART |  |
| `listing_date` | Listing date | date | DART |  |
| `established_date` | Date of incorporation | date | DART |  |
| `origin_kind` | LONG_LISTED / IPO / SPINOFF / UNKNOWN | code | derived | Codes: IPO=192; LONG_LISTED=11238; SPINOFF=252; UNKNOWN=155 |
| `firm_flag_basis` | Source of is_financial and is_holding | code | derived | ROSTER exchange roster; KSIC_RULE from ksic_code for firms delisted before the roster (holding: 64992; financial: divisions 64-66 other than holding) Codes: KSIC_RULE=882; ROSTER=10955 |

### `kobep_firmyear_financial.csv` - 7,653 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `corp_code` | DART issuer identifier (8 digits) |  | DART | join key across files |
| `fiscal_year` | Fiscal year of the annual report | year | DART |  |
| `fs_basis` | CFS consolidated or OFS separate, chosen per firm-year | code | DART | consolidated first Codes: CFS=6580; OFS=1073 |
| `fs_basis_changed` | 1 if the basis differs from the prior year | 0/1 | derived | Codes: 0=7485; 1=168 |
| `n_items` | Core accounts resolved (of 33) | count | derived |  |
| `currency` | Reporting currency | code | DART | USD/HKD for 5 firms - filter before pooling Codes: HKD=1; KRW=7627; USD=25 |
| `unit_suspect` | 1 if assets jump ~1,000-fold from the prior year | 0/1 | derived | flagged, not corrected Codes: 0=7653 |
| `signed_magnitudes` | Magnitude accounts filed with a sign | count | derived | absolute values used |
| `assets` | assets (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `liabilities` | liabilities (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `equity` | equity (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `equity_parent` | equity parent (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `current_assets` | current assets (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `noncurrent_assets` | noncurrent assets (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `current_liabilities` | current liabilities (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `noncurrent_liabilities` | noncurrent liabilities (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `cash` | cash (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `retained_earnings` | retained earnings (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `issued_capital` | issued capital (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `ppe` | ppe (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `inventories` | inventories (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `receivables` | receivables (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `intangibles` | intangibles (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `revenue` | revenue (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `operating_profit` | operating profit (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `profit` | profit (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `profit_parent` | profit parent (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `eps_basic` | Basic earnings per share | KRW per share | DART |  |
| `cost_of_sales` | cost of sales (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `sga` | sga (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `pretax_profit` | pretax profit (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `tax_expense` | tax expense (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `finance_costs` | finance costs (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `cfo` | cfo (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `cfi` | cfi (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `cff` | cff (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `capex` | capex (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `dividends_paid` | dividends paid (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `interest_paid` | interest paid (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `tax_paid` | tax paid (annual statements, fs_basis) | KRW (or `currency`) | DART |  |
| `roa` | profit / assets | ratio | derived |  |
| `roe` | profit / equity (equity > 0) | ratio | derived |  |
| `op_margin` | operating_profit / revenue (revenue > 0) | ratio | derived |  |
| `net_margin` | profit / revenue (revenue > 0) | ratio | derived |  |
| `cfo_assets` | cfo / assets | ratio | derived |  |
| `effective_tax_rate` | tax_expense / pretax_profit (pretax > 0) | ratio | derived |  |
| `fcf` | cfo - capex | KRW (or `currency`) | derived |  |
| `fcf_assets` | fcf / assets | ratio | derived |  |
| `capex_assets` | capex / assets | ratio | derived |  |
| `debt_equity` | liabilities / equity (equity > 0) | ratio | derived |  |
| `liabilities_assets` | liabilities / assets | ratio | derived |  |
| `current_ratio` | current_assets / current_liabilities | ratio | derived |  |
| `interest_coverage` | operating_profit / finance_costs | ratio | derived |  |
| `size` | ln(assets) | ln of reporting-currency amount | derived | see currency |
| `ppe_assets` | ppe / assets | ratio | derived |  |
| `invrec_assets` | (inventories + receivables) / assets | ratio | derived |  |
| `cash_assets` | cash / assets | ratio | derived |  |
| `re_te` | retained_earnings / equity (equity > 0) | ratio | derived |  |
| `firm_age` | fiscal_year - year of incorporation | years | derived |  |
| `revenue_growth` | revenue growth over the prior year, same currency | ratio | derived |  |
| `assets_growth` | asset growth over the prior year, same currency | ratio | derived |  |

### `kobep_firmyear_payout.csv` - 8,219 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `corp_code` | DART issuer identifier (8 digits) |  | DART | join key across files |
| `fiscal_year` | Fiscal year of the annual report | year | DART |  |
| `div_cash_total` | Cash dividends declared | KRW | DART | alotMatter |
| `div_basis` | REPORTED / INFERRED_ZERO / TOTAL_NOT_DISCLOSED / MISSING | code | derived | INFERRED_ZERO = dividend section filed with no total and no DPS; TOTAL_NOT_DISCLOSED = DPS filed, total blank or in the wrong unit Codes: INFERRED_ZERO=2414; MISSING=10; REPORTED=5785; TOTAL_NOT_DISCLOSED=10 |
| `dps` | Cash dividend per share | KRW | DART |  |
| `payout_ratio_disclosed` | Payout ratio as disclosed | % | DART |  |
| `div_yield_disclosed` | Dividend yield as disclosed | % | DART_DISCLOSED | computed by the filer on a reference price |
| `div_stock_total` | Stock dividends | KRW | DART |  |
| `disagree_flag` | 1 if the filer's repeated figures disagree >10x | 0/1 | derived | Codes: 0=8118; 1=101 |
| `treasury_acquired_qty` | Treasury shares acquired in the year | shares | DART |  |
| `treasury_acq_qty_direct` | ... of which direct purchases (직접취득) | shares | DART |  |
| `treasury_acq_qty_trust` | ... of which via trust (신탁) | shares | DART | statement amounts lag trust purchases |
| `treasury_acq_qty_other` | ... of which other (merger, odd lots, appraisal) | shares | DART |  |
| `treasury_retired_qty` | Treasury shares retired | shares | DART |  |
| `treasury_disposed_qty` | Treasury shares disposed | shares | DART |  |
| `treasury_end_qty` | Treasury shares held at year end | shares | DART |  |
| `n_buyback_decisions` | Buyback decision filings (B001) in the year | count | DART |  |
| `n_trust_openings` | Buyback trust contracts opened in the year | count | DART |  |
| `buyback_value` | Won paid for treasury shares | KRW | DART_DISCLOSED | cash-flow statement, else equity statement, else execution reports |
| `buyback_value_basis` | Source of buyback_value | code | derived | CASHFLOW / EQUITY_STMT / EXECUTION_REPORT / NO_ACQUISITION / NO_MARKET_ACQUISITION / NA_NOT_DISCLOSED / NA_SOURCE_CONFLICT; statement amounts used only when the parent bought in the market Codes: CASHFLOW=1124; EQUITY_STMT=39; EXECUTION_REPORT=102; NA_NOT_DISCLOSED=204; NA_SOURCE_CONFLICT=35; NO_ACQUISITION=6158; NO_MARKET_ACQUISITION=557 |
| `buyback_fs_div` | OFS or CFS statement used | code | DART | separate first Codes: CFS=36; OFS=1127 |
| `total_payout` | div_cash_total + buyback_value | KRW | derived | no exchange price used |
| `payout_basis` | CASH_ONLY / CASH_PLUS_REPORTED_BUYBACK / NONE | code | derived | Codes: CASH_ONLY=6744; CASH_PLUS_REPORTED_BUYBACK=1213; NONE=262 |
| `div_dummy` | 1 if a cash dividend was paid | 0/1 | derived | Codes: 0=2483; 1=5716 |
| `div_initiation` | 1 if div_dummy = 1 in t and 0 in t-1 | 0/1 | derived | t-1 must be observed Codes: 0=7770; 1=324 |
| `div_omission` | 1 if div_dummy = 0 in t and 1 in t-1 | 0/1 | derived | t-1 must be observed Codes: 0=7801; 1=293 |
| `div_increase` | 1 if div_cash_total in t exceeds a positive t-1 amount | 0/1 | derived | t-1 must be observed Codes: 0=5439; 1=2655 |
| `payout_ratio` | total_payout / profit | ratio | derived |  |
| `payout_assets` | total_payout / assets | ratio | derived |  |
| `payout_equity` | total_payout / equity | ratio | derived |  |
| `payout_ocf` | total_payout / cfo | ratio | derived |  |
| `div_assets` | div_cash_total / assets | ratio | derived |  |
| `distributable_profit_ub` | equity - issued_capital; upper bound of distributable profit | KRW | derived | Commercial Act art. 462(1) |
| `payout_capacity_used_lb` | total_payout / distributable_profit_ub; lower bound | ratio | derived |  |

### `kobep_missing_reasons.csv` - 135 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `file` | Release file |  | derived |  |
| `variable` | Column |  | derived |  |
| `reason_code` | Why the cells are blank | code | derived | defined in the codebook, section 5 Codes: NA_CURRENCY_MISMATCH=1; NA_FORM_VERSION=5; NA_NOT_APPLICABLE=28; NA_NOT_COLLECTED=1; NA_NOT_DISCLOSED=67; NA_NO_PRIOR_YEAR=5; NA_RULE_UNDETERMINED=2; NA_SOURCE_CONFLICT=1; NA_UNDEFINED_RATIO=23; NA_WITHHELD_PERSONAL=2 |
| `rule` | Condition selecting the cells | text | derived |  |
| `n_cells` | Blank cells covered by the rule | count | derived |  |

### `kobep_position_ledger.csv` - 33,238 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `rcept_no` | DART receipt number of the 5 % filing |  | DART | opens the original at dart.fss.or.kr/dsaf001/main.do?rcpNo= |
| `reporter_id` | KOBEP blockholder entity identifier |  | derived | see blockholder_entity |
| `corp_code` | DART issuer identifier (8 digits) |  | DART | join key across files |
| `receipt_date` | Date DART received the filing | date | DART |  |
| `in_core_window` | 1 if received 2016-01-01 to 2025-12-31 | 0/1 | derived | 0 = pre-window history 2011-2015 of panel firms Codes: 0=10498; 1=22740 |
| `form_version` | DART form version (FORMULA-VERSION) |  | DART | 2.2-6.0 |
| `form_kind` | standard or short form |  | DART |  |
| `is_amendment` | 1 if the filing text marks itself an amendment | 0/1 | DART | values are read from the post-amendment tables (ACLASS=EXTRACTION) Codes: 0=32483; 1=755 |
| `superseded_by` | rcept_no of the later amendment that replaces this filing | rcept_no | derived | set: same reporter_id, corp_code and obligation_date; every filing received before the set's latest amendment points to it. Before summing quantities or amounts, drop rows with superseded_by filled (v1.1) |
| `obligation_date` | Date the reporting duty arose (RPT_RSP_DT) | date | DART |  |
| `base_date` | As-of date of the reported holding (RPT_REF_DT) | date | DART |  |
| `prev_report_date` | Date of the filer's previous report | date | DART |  |
| `filer_type_code` | Filer type code (CRP_TP) | code | DART | I domestic corporation; K financial institution; Y pension fund or professional investor; A investment company etc.; N other organisation (domestic); U other organisation (foreign); O foreign corporation; C civil-code partnership; W statutory partnership Codes: A=20; C=204; I=14555; K=7921; N=614; O=3214; U=12; W=52; Y=6646 |
| `relation_to_issuer_code` | Filer's relation to the issuer (FLT_CRP_RLT) | code | DART | 01 officer, 02 major shareholder, 03 de facto controller, 04 unregistered officer, 10 largest shareholder, 13 shareholder, 14 affiliate, 15 affiliate officer, 16 other Codes: 01=7; 02=1706; 03=48; 10=11819; 13=16154; 14=474; 15=1; 16=2319 |
| `outsider_class` | INSIDER / OUTSIDER / UNCERTAIN from the relation code | code | derived | OUTSIDER: 13; INSIDER: 01, 03, 04, 10, 14, 15; UNCERTAIN: 02 (a >=10 % holder may be an outside institution), 16, blank Codes: INSIDER=12349; OUTSIDER=16154; UNCERTAIN=4735 |
| `prev_ratio_stockequiv` | Holding ratio in the previous report, stock-equivalent basis | % | DART | filer and related parties combined, as filed |
| `curr_ratio_stockequiv` | Holding ratio in this report, stock-equivalent basis | % | DART | filer and related parties combined, as filed (SUM_TMT_RT); not recomputed after natural-person rows were removed, so it can include related natural persons' shares; the 5 % threshold is defined on this basis |
| `prev_ratio_voting` | Previous holding ratio, voting-share basis | % | DART | form 4.2+ |
| `curr_ratio_voting` | Current holding ratio, voting-share basis | % | DART | form 4.2+ |
| `report_type_code` | 1 new, 2 change in holdings, 3 change in terms, 4 both | code | DART | Codes: 1=4717; 2=21054; 3=5047; 4=2419 |
| `holding_purpose_code` | 01 influence over management, 02 passive, 03 general investment | code | DART | coded from short form 3.9 (2020) and standard form 4.0 (late 2022) Codes: 01=4165; 02=4921; 03=907 |
| `involuntary` | 1 if a released transaction row of the filing is a non-purchase acquisition | 0/1 | derived | method_ko in 수증(+), 합병(+), 상속(+), 주식매수선택권행사(+), 출자전환, 대물변제수령(+), 무상신주취득(+), 주식배당(+), 계열사편입(+) Codes: 0=32452; 1=786 |
| `market_purchase` | 1 if a released transaction row of the filing is an on-exchange purchase | 0/1 | derived | method_ko in 장내매수(+), 시간외매매(+) Codes: 0=22703; 1=10535 |
| `joint_filing` | 1 for a joint (연명) report | 0/1 | DART | Codes: 0=10313; 1=22925 |
| `total_shares_issued` | Issuer's shares in issue stated in the filing | shares | DART |  |
| `holding_purpose_code_derived` | Holding purpose 01/02/03: the code where filed, else derived | code | derived | see holding_purpose_basis; derived values are rule-based (98.6 % agreement on released coded filings with text) Codes: 01=14830; 02=17337; 03=907 |
| `holding_purpose_basis` | How the purpose was obtained | code | derived | CODED / FORM_ELIGIBILITY (pre-code short form = 02) / TEXT_RULE / FORM_COVER (standard-form cover names the influence purpose, prose settles nothing = 01; 99.3 % of covered coded filings are 01) / PRIOR_FILING (still unclassified: the same holder's latest earlier CODED, TEXT_RULE or FORM_COVER category on the issuer; not after a short form) / UNCLASSIFIED / NO_TEXT Codes: CODED=9993; FORM_COVER=41; FORM_ELIGIBILITY=12380; NO_TEXT=1; PRIOR_FILING=97; TEXT_RULE=10563; UNCLASSIFIED=163 |

### `kobep_security_class.csv` - 16 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `security_ko` | Security label as it appears in the tables | text (ko) | DART |  |
| `security_class` | Standardised class | code | derived | Codes: BOND_WITH_WARRANT=1; COMMON=1; CONVERTIBLE_BOND=1; CONVERTIBLE_PREFERRED=1; CONVERTIBLE_TO_VOTING=1; DEPOSITARY_RECEIPT=1; EXCHANGEABLE_BOND=1; OTHER=1; REDEEMABLE_INTO_VOTING=1; SUBSCRIPTION_CERTIFICATE=1; UNREADABLE=1; VOTING_PREFERRED=1; VOTING_SHARE=3; WARRANT=1 |

### `kobep_terms_event.csv` - 213 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `rcept_no` | DART receipt number of the 5 % filing |  | DART | opens the original at dart.fss.or.kr/dsaf001/main.do?rcpNo= |
| `row_no` | Row position within the filing's table |  | derived |  |
| `corp_code` | DART issuer identifier (8 digits) |  | DART | join key across files |
| `in_core_window` | 1 if received 2016-01-01 to 2025-12-31 | 0/1 | derived | 0 = pre-window history 2011-2015 of panel firms Codes: 0=21; 1=192 |
| `party_name` | Party named in the terms-change row | text | DART |  |
| `party_id` | Party's registration number |  | DART | six-digit values reading as a birth date are withheld |
| `event_date` | Date of the change in terms | date | DART |  |
| `receipt_date` | Date DART received the filing | date | DART |  |
| `method_ko` | Coded method in the terms table | text (ko) | DART |  |
| `security_ko` | Security class as filed | text (ko) | DART |  |
| `security_class` | Standardised security class | code | derived | Codes: CONVERTIBLE_BOND=1; VOTING_SHARE=19 |
| `unit_price` | Price stated in the terms row | KRW | DART_DISCLOSED |  |
| `price_source` | DART_DISCLOSED when unit_price is present | code | derived | Codes: DART_DISCLOSED=1 |
| `method_en` | English gloss of method_ko | text | derived |  |

### `kobep_transaction_ledger.csv` - 995,936 rows

| Variable | Label | Unit | Source | Note |
|---|---|---|---|---|
| `rcept_no` | DART receipt number of the 5 % filing |  | DART | opens the original at dart.fss.or.kr/dsaf001/main.do?rcpNo= |
| `row_no` | Row position within the filing's table |  | derived |  |
| `in_core_window` | 1 if received 2016-01-01 to 2025-12-31 | 0/1 | derived | 0 = pre-window history 2011-2015 of panel firms Codes: 0=361266; 1=634670 |
| `party_name` | Party whose holding moved (filer or related party) | text | DART | legal persons only |
| `party_id` | Party's registration number |  | DART | six-digit values reading as a birth date are withheld |
| `change_date` | Date of the movement | date | DART |  |
| `method_ko` | Method of acquisition or disposal as filed (HLD_MTH) | text (ko) | DART | e.g. 장내매수(+) on-market purchase; see vocabulary |
| `direction` | +1 acquisition, -1 disposal |  | derived | from the method's sign |
| `security_ko` | Security class as filed | text (ko) | DART |  |
| `security_class` | Standardised security class | code | derived | see security_class Codes: BOND_WITH_WARRANT=494; COMMON=72361; CONVERTIBLE_BOND=6031; CONVERTIBLE_PREFERRED=1; CONVERTIBLE_TO_VOTING=225; DEPOSITARY_RECEIPT=7538; EXCHANGEABLE_BOND=467; NOT_STATED=166; OTHER=156; REDEEMABLE_INTO_VOTING=5; SUBSCRIPTION_CERTIFICATE=1691; UNREADABLE=9; VOTING_PREFERRED=22; VOTING_SHARE=904409; WARRANT=2361 |
| `shares_before` | Holding before the movement | shares | DART |  |
| `shares_change` | Size of the movement | shares | DART |  |
| `shares_after` | Holding after the movement | shares | DART |  |
| `unit_price` | Price per unit as stated by the filer | see unit_price_kind | DART_DISCLOSED | a filer-stated price, not an exchange quote |
| `price_source` | DART_DISCLOSED when unit_price is present | code | derived | Codes: DART_DISCLOSED=952675 |
| `unit_price_kind` | What unit_price is on this row | code | derived | EXECUTED_KRW_PER_SHARE (flow_kind TRADE); REFERENCE_KRW_PER_SHARE (exercise-price adjustment, swap and other non-trade rows); DR_UNIT_UNCONFIRMED (depositary receipts; unit not stated) Codes: DR_UNIT_UNCONFIRMED=7244; EXECUTED_KRW_PER_SHARE=844277; REFERENCE_KRW_PER_SHARE=101154 |
| `flow_kind` | Economic kind of the movement | code | derived | TRADE cash trade; OTHER unspecified; NON_CASH bonus/split/merger; PERIMETER related-party perimeter change; LENDING; DERIVATIVE; UNKNOWN Codes: DERIVATIVE=1816; LENDING=4549; NON_CASH=4821; OTHER=116001; PERIMETER=5245; TRADE=852727; UNKNOWN=10777 |
| `method_en` | English gloss of method_ko | text | derived | same table as docs/kobep_vocabulary.csv |

### Entity review flags

326 of 1,698 entities carry `needs_review = 1`. An entity can carry several reasons.

| Reason | Meaning | Entities |
|---|---|---:|
| ID_SPANS_NAMES | one registration number filed under unrelated names | 228 |
| NAME_SPANS_IDS | one name filed under several registration numbers | 85 |
| MIXED_ENTITY_TYPE | filer type code differs between filings | 61 |
| MOJIBAKE_NAME | a name variant is unreadable (encoding) | 3 |
| NO_NAME | no name on any filing | 3 |
| NO_IDENTIFIER | no registration number on any filing | 1 |

### Coverage by year

`docs/kobep_coverage_by_year.csv`:

|   year |   filings_indexed |   filings_parsed |   events_entered |   firm_master_firms |   financial_firm_years |   payout_firm_years |
|-------:|------------------:|-----------------:|-----------------:|--------------------:|-----------------------:|--------------------:|
|   2011 |              1815 |             1815 |              375 |                 718 |                      0 |                   0 |
|   2012 |              1846 |             1846 |              162 |                 725 |                      0 |                   0 |
|   2013 |              2026 |             2026 |              166 |                 734 |                      0 |                   0 |
|   2014 |              2234 |             2234 |              213 |                 746 |                      0 |                   0 |
|   2015 |              2622 |             2577 |              257 |                 762 |                      0 |                   0 |
|   2016 |              2259 |             2206 |              255 |                 777 |                    706 |                 782 |
|   2017 |              2279 |             2239 |              260 |                 795 |                    723 |                 799 |
|   2018 |              2516 |             2458 |              309 |                 800 |                    739 |                 811 |
|   2019 |              2244 |             2194 |              220 |                 805 |                    744 |                 821 |
|   2020 |              3013 |             2989 |              227 |                 815 |                    751 |                 824 |
|   2021 |              2376 |             2376 |              209 |                 822 |                    759 |                 827 |
|   2022 |              1967 |             1967 |              147 |                 823 |                    760 |                 831 |
|   2023 |              2152 |             2152 |              161 |                 831 |                    828 |                 842 |
|   2024 |              2072 |             2072 |              138 |                 842 |                    838 |                 843 |
|   2025 |              2087 |             2087 |              168 |                 842 |                    805 |                 839 |

## 5. Missing values

Every blank cell is covered by one rule below (`kobep_missing_reasons.csv`).

| File | Variable | Code | Rule | Cells |
|---|---|---|---|---:|
| kobep_blockholder_entity.csv | `review_reason` | NA_NOT_APPLICABLE | needs_review = 0 | 1,372 |
| kobep_blockholder_entity.csv | `id_value` | NA_WITHHELD_PERSONAL | id_kind ID_WITHHELD | 37 |
| kobep_blockholder_entity.csv | `id_value` | NA_NOT_DISCLOSED | no identifier on any filing | 3 |
| kobep_event_ledger.csv | `prev_ratio` | NA_NOT_APPLICABLE | entry filing is a new report | 2,484 |
| kobep_event_ledger.csv | `exit_date` | NA_NOT_APPLICABLE | exit_censored = 1 | 1,194 |
| kobep_event_ledger.csv | `censoring_kind` | NA_NOT_APPLICABLE | exit_censored = 0 | 2,073 |
| kobep_event_ledger.csv | `transition_date` | NA_NOT_APPLICABLE | class_changed = 0 | 2,841 |
| kobep_event_ledger.csv | `purpose_at_entry` | NA_FORM_VERSION | entry filing is short form < 3.9 or standard form < 4.0 | 2,405 |
| kobep_event_ledger.csv | `purpose_changed` | NA_FORM_VERSION | no purpose code on any filing | 1,287 |
| kobep_event_ledger.csv | `is_related_party` | NA_NOT_APPLICABLE | class_at_entry UNCERTAIN | 895 |
| kobep_event_ledger.csv | `is_marginal_entry` | NA_NOT_APPLICABLE | entry_ratio blank | 32 |
| kobep_event_ledger.csv | `purpose_at_entry_derived` | NA_RULE_UNDETERMINED | purpose_at_entry_basis UNCLASSIFIED | 30 |
| kobep_firm_master.csv | `delisting_date` | NA_NOT_APPLICABLE | not delisted in that year | 10,955 |
| kobep_firm_master.csv | `listing_date` | NA_NOT_COLLECTED | delisted before the exchange roster that gives listing dates; DART carries no listing date | 882 |
| kobep_firmyear_financial.csv | `assets` | NA_NOT_DISCLOSED | account not reported in the annual statements | 9 |
| kobep_firmyear_financial.csv | `liabilities` | NA_NOT_DISCLOSED | account not reported in the annual statements | 4 |
| kobep_firmyear_financial.csv | `equity` | NA_NOT_DISCLOSED | account not reported in the annual statements | 43 |
| kobep_firmyear_financial.csv | `equity_parent` | NA_NOT_DISCLOSED | account not reported in the annual statements | 1,380 |
| kobep_firmyear_financial.csv | `current_assets` | NA_NOT_DISCLOSED | account not reported in the annual statements | 171 |
| kobep_firmyear_financial.csv | `noncurrent_assets` | NA_NOT_DISCLOSED | account not reported in the annual statements | 172 |
| kobep_firmyear_financial.csv | `current_liabilities` | NA_NOT_DISCLOSED | account not reported in the annual statements | 172 |
| kobep_firmyear_financial.csv | `noncurrent_liabilities` | NA_NOT_DISCLOSED | account not reported in the annual statements | 174 |
| kobep_firmyear_financial.csv | `cash` | NA_NOT_DISCLOSED | account not reported in the annual statements | 101 |
| kobep_firmyear_financial.csv | `retained_earnings` | NA_NOT_DISCLOSED | account not reported in the annual statements | 353 |
| kobep_firmyear_financial.csv | `issued_capital` | NA_NOT_DISCLOSED | account not reported in the annual statements | 640 |
| kobep_firmyear_financial.csv | `ppe` | NA_NOT_DISCLOSED | account not reported in the annual statements | 26 |
| kobep_firmyear_financial.csv | `inventories` | NA_NOT_DISCLOSED | account not reported in the annual statements | 396 |
| kobep_firmyear_financial.csv | `receivables` | NA_NOT_DISCLOSED | account not reported in the annual statements | 2,466 |
| kobep_firmyear_financial.csv | `intangibles` | NA_NOT_DISCLOSED | account not reported in the annual statements | 2,274 |
| kobep_firmyear_financial.csv | `revenue` | NA_NOT_DISCLOSED | account not reported in the annual statements | 200 |
| kobep_firmyear_financial.csv | `operating_profit` | NA_NOT_DISCLOSED | account not reported in the annual statements | 182 |
| kobep_firmyear_financial.csv | `profit` | NA_NOT_DISCLOSED | account not reported in the annual statements | 83 |
| kobep_firmyear_financial.csv | `profit_parent` | NA_NOT_DISCLOSED | account not reported in the annual statements | 1,813 |
| kobep_firmyear_financial.csv | `eps_basic` | NA_NOT_DISCLOSED | account not reported in the annual statements | 1,009 |
| kobep_firmyear_financial.csv | `cost_of_sales` | NA_NOT_DISCLOSED | account not reported in the annual statements | 433 |
| kobep_firmyear_financial.csv | `sga` | NA_NOT_DISCLOSED | account not reported in the annual statements | 715 |
| kobep_firmyear_financial.csv | `pretax_profit` | NA_NOT_DISCLOSED | account not reported in the annual statements | 47 |
| kobep_firmyear_financial.csv | `tax_expense` | NA_NOT_DISCLOSED | account not reported in the annual statements | 145 |
| kobep_firmyear_financial.csv | `finance_costs` | NA_NOT_DISCLOSED | account not reported in the annual statements | 617 |
| kobep_firmyear_financial.csv | `cfo` | NA_NOT_DISCLOSED | account not reported in the annual statements | 103 |
| kobep_firmyear_financial.csv | `cfi` | NA_NOT_DISCLOSED | account not reported in the annual statements | 103 |
| kobep_firmyear_financial.csv | `cff` | NA_NOT_DISCLOSED | account not reported in the annual statements | 117 |
| kobep_firmyear_financial.csv | `capex` | NA_NOT_DISCLOSED | account not reported in the annual statements | 1,330 |
| kobep_firmyear_financial.csv | `dividends_paid` | NA_NOT_DISCLOSED | account not reported in the annual statements | 2,723 |
| kobep_firmyear_financial.csv | `interest_paid` | NA_NOT_DISCLOSED | account not reported in the annual statements | 1,457 |
| kobep_firmyear_financial.csv | `tax_paid` | NA_NOT_DISCLOSED | account not reported in the annual statements | 675 |
| kobep_firmyear_financial.csv | `roa` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 90 |
| kobep_firmyear_financial.csv | `roe` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 144 |
| kobep_firmyear_financial.csv | `op_margin` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 289 |
| kobep_firmyear_financial.csv | `net_margin` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 281 |
| kobep_firmyear_financial.csv | `cfo_assets` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 111 |
| kobep_firmyear_financial.csv | `effective_tax_rate` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 1,928 |
| kobep_firmyear_financial.csv | `fcf` | NA_NOT_DISCLOSED | cfo or capex not reported | 1,410 |
| kobep_firmyear_financial.csv | `fcf_assets` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 1,411 |
| kobep_firmyear_financial.csv | `capex_assets` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 1,331 |
| kobep_firmyear_financial.csv | `debt_equity` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 64 |
| kobep_firmyear_financial.csv | `liabilities_assets` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 12 |
| kobep_firmyear_financial.csv | `current_ratio` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 172 |
| kobep_firmyear_financial.csv | `interest_coverage` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 653 |
| kobep_firmyear_financial.csv | `size` | NA_UNDEFINED_RATIO | total assets blank or <= 0 (log undefined) | 9 |
| kobep_firmyear_financial.csv | `ppe_assets` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 34 |
| kobep_firmyear_financial.csv | `invrec_assets` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 272 |
| kobep_firmyear_financial.csv | `cash_assets` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 110 |
| kobep_firmyear_financial.csv | `re_te` | NA_UNDEFINED_RATIO | numerator or denominator blank, or denominator <= 0 | 392 |
| kobep_firmyear_financial.csv | `revenue_growth` | NA_NO_PRIOR_YEAR | no prior year, or the reporting currency changed | 905 |
| kobep_firmyear_financial.csv | `assets_growth` | NA_NO_PRIOR_YEAR | no prior year, or the reporting currency changed | 731 |
| kobep_firmyear_payout.csv | `dps` | NA_NOT_DISCLOSED | otherwise | 2,447 |
| kobep_firmyear_payout.csv | `payout_ratio_disclosed` | NA_NOT_DISCLOSED | otherwise | 2,880 |
| kobep_firmyear_payout.csv | `div_yield_disclosed` | NA_NOT_DISCLOSED | otherwise | 2,564 |
| kobep_firmyear_payout.csv | `div_stock_total` | NA_NOT_APPLICABLE | no stock dividend | 8,043 |
| kobep_firmyear_payout.csv | `div_cash_total` | NA_NOT_DISCLOSED | div_basis MISSING, or TOTAL_NOT_DISCLOSED (per-share amount filed, total left blank or in the wrong unit) | 20 |
| kobep_firmyear_payout.csv | `div_dummy` | NA_NOT_DISCLOSED | div_basis MISSING or TOTAL_NOT_DISCLOSED | 20 |
| kobep_firmyear_payout.csv | `treasury_acquired_qty` | NA_NOT_APPLICABLE | no movement of that kind reported | 6,205 |
| kobep_firmyear_payout.csv | `treasury_acq_qty_direct` | NA_NOT_APPLICABLE | no movement of that kind reported | 6,252 |
| kobep_firmyear_payout.csv | `treasury_acq_qty_trust` | NA_NOT_APPLICABLE | no movement of that kind reported | 6,252 |
| kobep_firmyear_payout.csv | `treasury_acq_qty_other` | NA_NOT_APPLICABLE | no movement of that kind reported | 6,252 |
| kobep_firmyear_payout.csv | `treasury_retired_qty` | NA_NOT_APPLICABLE | no movement of that kind reported | 7,696 |
| kobep_firmyear_payout.csv | `treasury_disposed_qty` | NA_NOT_APPLICABLE | no movement of that kind reported | 7,038 |
| kobep_firmyear_payout.csv | `treasury_end_qty` | NA_NOT_DISCLOSED | treasury table absent for the year | 2,506 |
| kobep_firmyear_payout.csv | `buyback_value` | NA_SOURCE_CONFLICT | separate cash-flow shows a purchase, treasury table shows none | 35 |
| kobep_firmyear_payout.csv | `buyback_value` | NA_NOT_DISCLOSED | buyback_value_basis NA_NOT_DISCLOSED | 204 |
| kobep_firmyear_payout.csv | `buyback_fs_div` | NA_NOT_APPLICABLE | basis is not a financial statement | 7,056 |
| kobep_firmyear_payout.csv | `total_payout` | NA_CURRENCY_MISMATCH | statements not in KRW with a buyback | 5 |
| kobep_firmyear_payout.csv | `total_payout` | NA_NOT_DISCLOSED | dividend or buyback amount missing | 257 |
| kobep_firmyear_payout.csv | `div_initiation` | NA_NO_PRIOR_YEAR | cash dividend of fiscal year t-1 not observed | 125 |
| kobep_firmyear_payout.csv | `div_omission` | NA_NO_PRIOR_YEAR | cash dividend of fiscal year t-1 not observed | 125 |
| kobep_firmyear_payout.csv | `div_increase` | NA_NO_PRIOR_YEAR | cash dividend of fiscal year t-1 not observed | 125 |
| kobep_firmyear_payout.csv | `payout_ratio` | NA_UNDEFINED_RATIO | total_payout blank or denominator <= 0 | 2,699 |
| kobep_firmyear_payout.csv | `payout_assets` | NA_UNDEFINED_RATIO | total_payout blank or denominator <= 0 | 789 |
| kobep_firmyear_payout.csv | `payout_equity` | NA_UNDEFINED_RATIO | total_payout blank or denominator <= 0 | 843 |
| kobep_firmyear_payout.csv | `payout_ocf` | NA_UNDEFINED_RATIO | total_payout blank or denominator <= 0 | 2,443 |
| kobep_firmyear_payout.csv | `payout_capacity_used_lb` | NA_UNDEFINED_RATIO | total_payout blank or denominator <= 0 | 1,624 |
| kobep_firmyear_payout.csv | `div_assets` | NA_UNDEFINED_RATIO | div_cash_total blank or total assets blank or <= 0 | 594 |
| kobep_firmyear_payout.csv | `distributable_profit_ub` | NA_NOT_DISCLOSED | equity or issued capital not reported | 1,230 |
| kobep_position_ledger.csv | `prev_report_date` | NA_NOT_APPLICABLE | report_type_code = 1 (new report) | 3,897 |
| kobep_position_ledger.csv | `prev_ratio_stockequiv` | NA_NOT_APPLICABLE | report_type_code = 1 (new report) | 4,222 |
| kobep_position_ledger.csv | `prev_ratio_stockequiv` | NA_NOT_DISCLOSED | otherwise | 10 |
| kobep_position_ledger.csv | `prev_ratio_voting` | NA_FORM_VERSION | form_version < 4.2 | 27,025 |
| kobep_position_ledger.csv | `prev_ratio_voting` | NA_NOT_APPLICABLE | report_type_code = 1 (new report) | 811 |
| kobep_position_ledger.csv | `prev_ratio_voting` | NA_NOT_DISCLOSED | otherwise | 4,696 |
| kobep_position_ledger.csv | `curr_ratio_voting` | NA_FORM_VERSION | form_version < 4.2 | 27,025 |
| kobep_position_ledger.csv | `curr_ratio_voting` | NA_NOT_DISCLOSED | otherwise | 5,411 |
| kobep_position_ledger.csv | `holding_purpose_code` | NA_FORM_VERSION | short form < 3.9 or standard form < 4.0 | 23,244 |
| kobep_position_ledger.csv | `holding_purpose_code` | NA_NOT_DISCLOSED | otherwise | 1 |
| kobep_position_ledger.csv | `superseded_by` | NA_NOT_APPLICABLE | no later amendment by the same filer on the same issuer with the same obligation_date | 32,515 |
| kobep_position_ledger.csv | `relation_to_issuer_code` | NA_NOT_DISCLOSED | filer entered '-' | 710 |
| kobep_position_ledger.csv | `curr_ratio_stockequiv` | NA_NOT_DISCLOSED | summary ratio cell blank | 16 |
| kobep_position_ledger.csv | `report_type_code` | NA_NOT_DISCLOSED | report type not marked | 1 |
| kobep_position_ledger.csv | `total_shares_issued` | NA_NOT_DISCLOSED | issuer share count blank | 38 |
| kobep_position_ledger.csv | `holding_purpose_code_derived` | NA_RULE_UNDETERMINED | holding_purpose_basis UNCLASSIFIED | 163 |
| kobep_position_ledger.csv | `holding_purpose_code_derived` | NA_NOT_DISCLOSED | standard form with no purpose prose | 1 |
| kobep_terms_event.csv | `party_name` | NA_NOT_DISCLOSED | terms-change rows carry few coded cells | 104 |
| kobep_terms_event.csv | `party_id` | NA_NOT_DISCLOSED | terms-change rows carry few coded cells | 108 |
| kobep_terms_event.csv | `event_date` | NA_NOT_DISCLOSED | terms-change rows carry few coded cells | 110 |
| kobep_terms_event.csv | `method_ko` | NA_NOT_DISCLOSED | terms-change rows carry few coded cells | 191 |
| kobep_terms_event.csv | `security_ko` | NA_NOT_DISCLOSED | terms-change rows carry few coded cells | 193 |
| kobep_terms_event.csv | `unit_price` | NA_NOT_DISCLOSED | terms-change rows carry few coded cells | 212 |
| kobep_terms_event.csv | `security_class` | NA_NOT_APPLICABLE | security_ko blank | 193 |
| kobep_terms_event.csv | `method_en` | NA_NOT_APPLICABLE | method_ko blank | 191 |
| kobep_terms_event.csv | `price_source` | NA_NOT_APPLICABLE | unit_price blank | 212 |
| kobep_transaction_ledger.csv | `unit_price` | NA_NOT_APPLICABLE | flow_kind not TRADE (no consideration stated) | 41,997 |
| kobep_transaction_ledger.csv | `unit_price` | NA_NOT_DISCLOSED | trade row without a price | 1,264 |
| kobep_transaction_ledger.csv | `price_source` | NA_NOT_APPLICABLE | unit_price blank | 43,261 |
| kobep_transaction_ledger.csv | `unit_price_kind` | NA_NOT_APPLICABLE | unit_price blank | 43,261 |
| kobep_transaction_ledger.csv | `method_en` | NA_NOT_APPLICABLE | method_ko blank | 10,238 |
| kobep_transaction_ledger.csv | `direction` | NA_NOT_APPLICABLE | method has no sign (e.g. 'exercise price adjustment') | 13,905 |
| kobep_transaction_ledger.csv | `method_ko` | NA_NOT_DISCLOSED | method cell '-' or blank | 10,238 |
| kobep_transaction_ledger.csv | `party_id` | NA_WITHHELD_PERSONAL | six-digit value reading as a birth date beside an organisation name | 2,804 |
| kobep_transaction_ledger.csv | `shares_before` | NA_NOT_DISCLOSED | cell blank, '-' or a placeholder such as 해당없음 in the filing | 7,761 |
| kobep_transaction_ledger.csv | `shares_change` | NA_NOT_DISCLOSED | cell blank, '-' or a placeholder such as 해당없음 in the filing | 333 |
| kobep_transaction_ledger.csv | `shares_after` | NA_NOT_DISCLOSED | cell blank, '-' or a placeholder such as 해당없음 in the filing | 1,251 |
| kobep_transaction_ledger.csv | `security_ko` | NA_NOT_DISCLOSED | cell blank, '-' or a placeholder such as 해당없음 in the filing | 166 |
| kobep_transaction_ledger.csv | `change_date` | NA_NOT_DISCLOSED | cell blank, '-' or a placeholder such as 해당없음 in the filing | 25 |
| kobep_transaction_ledger.csv | `party_name` | NA_NOT_DISCLOSED | cell blank, '-' or a placeholder such as 해당없음 in the filing | 5 |
| kobep_transaction_ledger.csv | `party_id` | NA_NOT_DISCLOSED | cell blank, '-' or a placeholder such as 해당없음 in the filing | 401 |

## 6. Validation

Aggregates are in `docs/kobep_validation_summary.csv`. The spot-check drew
stratified samples from the release files themselves (filings by receipt-year
band and form; transactions by `flow_kind` and period; events by class and
truncation). A language model compared every sampled field with the original
filing; a person then judged every sampled field against the original, the
items the model flagged first. The first pass found a systematic defect - decimal
prices read as integers - which was corrected in 30,960 rows (2.7 % of priced
rows) before the scores below were taken.

| Check | Scope | n | Result | Note |
|---|---|---:|---|---|
| Parser vs DART structured API (holding ratio) | validation corpus 2024-08 to 2026-07 with both sources | 6,550 | 6,550 agree within 0.005 pp (100 %) | majorstock.json; older forms outside the API window; filings received in 2026 were used only to test the parser and are not in the release |
| Holding-purpose derivation vs coded purpose | released filings carrying both a filed code and purpose text | 4,916 | 98.64 % agree; 01 precision 0.997 recall 0.994; 02 1.000/0.959; 03 0.971/0.888 | rule-based; generalisation to pre-code prose assumed; restrict to holding_purpose_basis = CODED for filed codes only |
| Standard-form cover vs coded purpose (FORM_COVER basis) | released standard-form filings with a filed code whose cover names the influence purpose | 4,114 | 99.34 % coded 01 | the cover is used only when no text rule fires |
| Carried-forward purpose (PRIOR_FILING basis) | released standard-form filings with a filed code and an earlier classified filing by the same holder on the issuer | 4,027 | 99.35 % match the earlier category; 94.85 % of 97 exit filings | used only for filings still unclassified after the text rules and the cover |
| Changed derived purposes vs originals | all released filings whose derived purpose changed with the 2026-10-23 rules (171 by text rules or cover, 97 carried forward) | 268 | 0 errors | human check of every filing against its original |
| Payout amounts vs annual reports | 40 firm-years, fixed seed (20261026), stratified by repurchase source, blank reason, trust purchases and inferred-zero dividends | 120 | 0 errors in 120 fields (cash dividend, repurchase amount, recorded source) | human check against annual and execution reports; code/validation/make_payout_check.py (v1.1) |
| Buyback amount vs an exchange-price estimate | statement and execution-report bases, 2016-2025 | 1,116 | internal plausibility check only | the estimate uses exchange prices and is not released, nor are its ratios |
| Spot-check design | 460 sampled rows (160 filings x 9, 200 transactions x 6, 100 events x 6 fields), fixed seed, stratified | 3,240 | every field judged by a human reviewer against the original filing | a language model screened every field first and its flags set the order of review: the 68 flagged rows first, then the 392 passed rows (358 of them blind to the model); a derived purpose left blank although its text can be classified counts as an error |
| Spot-check: defects found | all 3,240 fields | 3,240 | decimal prices read as integers (6 of 200 sampled prices flagged by the model screen of the first build); 7 blank derived purposes in 160 sampled filings | both corrected throughout the release before deposit: 30,960 price cells in the internal ledger (2.7 % of 1,128,021 priced cells); purpose rules extended, 268 released filings changed and checked |
| Spot-check: released values re-checked | all 3,240 fields; the 12 fields changed after the audit re-judged | 3,240 | 0 errors in the sample | the same sample guided the corrections, so this confirms them; it is not an independent estimate of the error rate of unsampled records |
| Language-model screens (screening tools only) | all 3,240 human-judged fields | 3,240 | gpt-5.5 98.9 % agree (34 false alarms) and claude-opus-5-5 99.3 % (21) as recorded; 99.1 % (28) and 99.5 % (16) under the blank-purpose criterion; 0 errors passed by either | no released value depends on a model verdict |
| Event dates within the ledger window | all release events | 3,267 | 0 dates after 2025-12-31 | extract_release.py assertion |
| Package integrity | every file in the package | 0 | no stray files; all checksums match | audit/audit_package.py |
| Referential integrity | all release files | 0 | 0 orphan keys, 0 duplicate keys | audit/audit_joins.py |
| Natural-person screen | data, docs, manifest and parser fixtures | 0 | 0 natural persons | audit/audit_pii.py; fixtures have representative and decision-maker cells redacted |
| Exchange-price recoverability | 85 numeric columns (firm-year files and shares in issue); 7,140 ordered ratios a/b and 18,048 combinations (a - b)/c of won amounts over a share quantity | 0 | no exchange-origin price recoverable; the only implied price found is DPS / disclosed dividend yield, both issuer-disclosed | audit/audit_price_leak.py |

## 7. Limitations

- Holdings below 5 % are not observed; campaigns that never cross the threshold
  are absent.
- Exits below 5 % within one percentage point are never filed and are censored.
- Natural-person blockholders are absent; the relationships in this release are
  those of companies, funds and institutions.
- The 2011-2015 ledger covers the 2016-2025 panel companies only (survivorship).
- Firm-year files start in 2016; 2011-2014 ledger rows have no firm-year covariates.
- 270 filings in the index have no text at DART; they are listed but not parsed.
- Entities are reporting entities on registration numbers, not economic groups.
- Firm-year coverage is below one row per firm-year where DART has no annual
  report or statements for the year (`docs/kobep_coverage_by_year.csv`); the
  76 firms delisted before the exchange roster have no listing date, and their
  financial and holding-company flags are set by rule from the KSIC code
  (`firm_flag_basis = KSIC_RULE`).
- Treasury-share amounts reached through a trust lag the share counts.
- Financial statements of five companies are in USD or HKD (`currency`); do not
  pool them with won amounts. Growth rates across a currency change are blank.
- No market or exchange variable is included. To join one, use `stock_code`
  for the year from `kobep_firm_master.csv` (codes change) and check
  `delisting_date` and `is_partial_year`.
- `class_at_entry` reflects the filer's declared relation, not a judgement of
  who the holder is; a third-party acquirer and a fund both declare 'shareholder'.
