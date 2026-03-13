# Tax Document Classification Matrix

Use this matrix to classify tax documents during visual inspection. Each entry includes
the form type, typical source, key fields to extract, the Paperless filing tag, and
visual identification hints for recognizing the form from its content.

## Income Documents

| Document Type | IRS Form | Typical Source | Key Fields | Filing Tag |
|--------------|----------|---------------|------------|------------|
| Wages & salary | W-2 | Employer | Box 1: Wages; Box 2: Federal tax withheld; Box 3-6: SS/Medicare wages & tax; Box 12: Codes (401k, etc.); Box 17: State tax | `w-2` |
| Interest income | 1099-INT | Banks, credit unions, Treasury | Box 1: Interest income; Box 3: Savings bond interest; Box 4: Federal tax withheld; Box 8: Tax-exempt interest | `1099-int` |
| Dividend income | 1099-DIV | Brokerages, mutual funds | Box 1a: Total ordinary dividends; Box 1b: Qualified dividends; Box 2a: Total capital gain distributions; Box 5: Sec 199A dividends | `1099-div` |
| Proceeds from sales | 1099-B | Brokerages | Box 1a: Description of property; Box 1b: Date acquired; Box 1c: Date sold; Box 1d: Proceeds; Box 1e: Cost basis; Box 2: Short/long-term | `1099-b` |
| Miscellaneous income | 1099-MISC | Clients, rental income | Box 1: Rents; Box 2: Royalties; Box 3: Other income; Box 4: Federal tax withheld; Box 10: Crop insurance proceeds | `1099-misc` |
| Non-employee compensation | 1099-NEC | Clients, freelance payers | Box 1: Nonemployee compensation; Box 4: Federal tax withheld | `1099-nec` |
| Retirement distributions | 1099-R | Pension plans, IRAs, 401(k) | Box 1: Gross distribution; Box 2a: Taxable amount; Box 4: Federal tax withheld; Box 7: Distribution code | `1099-r` |
| Government payments | 1099-G | State/federal government | Box 1: Unemployment compensation; Box 2: State/local tax refunds; Box 4: Federal tax withheld | `1099-g` |
| Payment card transactions | 1099-K | Payment processors (PayPal, Stripe, etc.) | Box 1a: Gross amount of payment card transactions; Box 5a-5l: Monthly breakdown | `1099-k` |
| HSA distributions | 1099-SA | HSA custodians | Box 1: Gross distribution; Box 2: Earnings on excess contributions; Box 3: Distribution code | `1099-sa` |
| Social Security benefits | SSA-1099 | Social Security Administration | Box 3: Benefits paid; Box 4: Benefits repaid; Box 5: Net benefits | `ssa-1099` |

### Visual Identification — Income Documents

- **W-2**: Two-column layout. "Wage and Tax Statement" across the top. Employer info in left column (boxes a-f), employee info below (boxes e-f). Right column has numbered boxes 1-20. OMB 1545-0008. Often printed on perforated multi-copy paper. Look for "Copy B — To Be Filed With Employee's Federal Tax Return."
- **1099-INT**: Single-column form. "Interest Income" title. Payer info at top, recipient below. Numbered boxes 1-17 on the right side. OMB 1545-0112.
- **1099-DIV**: Similar layout to 1099-INT. "Dividends and Distributions" title. Look for Box 1a/1b distinction (ordinary vs qualified). OMB 1545-0110.
- **1099-B**: Often delivered as multi-page statements from brokerages. May not look like a standard IRS form. Look for "Proceeds From Broker and Barter Exchange Transactions" header. Individual transactions listed in tabular format with acquisition date, sale date, proceeds, and cost basis columns. OMB 1545-0715.
- **1099-MISC / 1099-NEC**: Very similar layouts. Key difference: NEC has only 4 boxes and was split from MISC starting TY 2020. MISC has "Miscellaneous Information" title, NEC has "Nonemployee Compensation." Both OMB 1545-0115.
- **1099-R**: "Distributions From Pensions, Annuities, Retirement..." title. Box 7 distribution code is critical — look for it specifically. OMB 1545-0119.
- **1099-G**: "Certain Government Payments" title. OMB 1545-0120.
- **1099-K**: "Payment Card and Third Party Network Transactions" title. Monthly boxes 5a-5l are distinctive. OMB 1545-2205.
- **1099-SA**: "Distributions From an HSA, Archer MSA, or Medicare Advantage MSA" title. OMB 1545-0074.
- **SSA-1099**: Blue-tinted form. "Social Security Benefit Statement" title. Distinctive box layout with boxes 3, 4, and 5. Issued by SSA, not IRS.

## Pass-Through Entity Documents

| Document Type | IRS Form | Typical Source | Key Fields | Filing Tag |
|--------------|----------|---------------|------------|------------|
| Partnership income | Schedule K-1 (Form 1065) | Partnerships, LLCs taxed as partnerships | Box 1: Ordinary business income; Box 2: Net rental income; Box 4a: Guaranteed payments; Box 5: Interest; Box 6a: Ordinary dividends; Box 11: Section 179 deduction; Box 14: Self-employment | `k-1-1065` |
| S-Corp income | Schedule K-1 (Form 1120-S) | S-Corporations | Box 1: Ordinary business income; Box 2: Net rental income; Box 5: Interest; Box 6a: Ordinary dividends; Box 7: Royalties; Box 10: Net Section 1231 gain | `k-1-1120s` |
| Trust/estate income | Schedule K-1 (Form 1041) | Trusts, estates | Box 1: Interest income; Box 2a: Ordinary dividends; Box 3: Net short-term capital gain; Box 4a: Net long-term capital gain; Box 5: Other portfolio income; Box 9: Directly apportioned deductions | `k-1-1041` |

### Visual Identification — Pass-Through Documents

- **K-1 (1065)**: "Partner's Share of Income, Deductions, Credits, etc." header. Part I identifies the partnership (EIN, name, address). Part II identifies the partner. Part III lists income/deduction items in boxes 1-21. Look for "Form 1065" in the header to distinguish from 1120-S and 1041 K-1s. OMB 1545-0123.
- **K-1 (1120-S)**: "Shareholder's Share of Income, Deductions, Credits, etc." header. Very similar layout to 1065 K-1 but says "Form 1120-S" and identifies shareholder instead of partner. OMB 1545-0123.
- **K-1 (1041)**: "Beneficiary's Share of Income, Deductions, Credits, etc." header. Says "Form 1041" and identifies beneficiary instead of partner/shareholder. OMB 1545-0092.

**Important**: K-1s frequently arrive late (March-April) and may be revised. Always check for "AMENDED" or "FINAL" designation. K-1 packages often include supplemental schedules — inspect all pages.

## Deduction Documents

| Document Type | IRS Form | Typical Source | Key Fields | Filing Tag |
|--------------|----------|---------------|------------|------------|
| Mortgage interest | 1098 | Mortgage lender/servicer | Box 1: Mortgage interest received; Box 2: Outstanding mortgage principal; Box 5: Mortgage insurance premiums; Box 10: Property address | `1098` |
| Tuition payments | 1098-T | Colleges, universities | Box 1: Payments received for qualified tuition; Box 5: Scholarships or grants; Box 7: Prior year adjustment checkbox | `1098-t` |
| Student loan interest | 1098-E | Student loan servicers | Box 1: Student loan interest received by lender | `1098-e` |
| Charitable donations | Receipt/Letter | Nonprofits, charities | Organization name; Date of contribution; Amount; Description of non-cash property; Statement of goods/services provided | `charitable-receipt` |
| Property tax bills | Tax bill | Municipal/county assessor | Property address; Assessed value; Tax amount; Payment due dates; Parcel number | `property-tax` |

### Visual Identification — Deduction Documents

- **1098**: "Mortgage Interest Statement" title. Lender info at top-left, borrower at top-right. Key box is Box 1. OMB 1545-0901. Often printed on tax statement inserts from mortgage servicers.
- **1098-T**: "Tuition Statement" title. School info at top-left, student info at top-right. Distinctive purple/blue color on printed forms. OMB 1545-1574.
- **1098-E**: "Student Loan Interest Statement" title. Simple form with few boxes. OMB 1545-1576.
- **Charitable receipts**: No standard IRS form. Look for: organization name and address, 501(c)(3) statement, donation amount, date, and "no goods or services were provided" language (or description of quid pro quo). Letters on organization letterhead.
- **Property tax bills**: Municipal/county format varies widely. Look for: parcel/tax map number, assessed value, mill rate, tax amount, payment schedule, and municipal seal or header.

## Health Coverage Documents

| Document Type | IRS Form | Typical Source | Key Fields | Filing Tag |
|--------------|----------|---------------|------------|------------|
| Marketplace insurance | 1095-A | Health Insurance Marketplace | Column A: Monthly enrollment premiums; Column B: Monthly SLCSP premium; Column C: Monthly advance PTC | `1095-a` |
| Health coverage (insurer) | 1095-B | Health insurance companies | Part III: Covered individuals — name, SSN, months of coverage | `1095-b` |
| Employer health coverage | 1095-C | Employers with 50+ employees | Part II: Offer of coverage codes (lines 14-16); Part III: Covered individuals and months | `1095-c` |

### Visual Identification — Health Coverage Documents

- **1095-A**: "Health Insurance Marketplace Statement" title. Three-column monthly grid (columns A, B, C) covering all 12 months is distinctive. OMB 1545-2232.
- **1095-B**: "Health Coverage" title. Part III table listing covered individuals with month-by-month checkboxes. OMB 1545-2252.
- **1095-C**: "Employer-Provided Health Insurance Offer and Coverage" title. Three-part form. Part II has month-by-month rows with numeric codes. OMB 1545-2251. Largest of the three 1095 forms.

## Retirement & Savings Documents

| Document Type | IRS Form | Typical Source | Key Fields | Filing Tag |
|--------------|----------|---------------|------------|------------|
| IRA contributions | 5498 | IRA custodians | Box 1: IRA contributions; Box 2: Rollover contributions; Box 5: FMV of account; Box 10: Roth IRA contributions; Box 12a: RMD date; Box 12b: RMD amount | `5498` |
| HSA contributions | 5498-SA | HSA custodians | Box 1: Employee/self contributions; Box 2: Total contributions; Box 3: Total HSA contributions; Box 5: FMV of account | `5498-sa` |

### Visual Identification — Retirement & Savings Documents

- **5498**: "IRA Contribution Information" title. Similar layout to a 1099 but Box 5 (FMV) and Box 12a/12b (RMD info) are distinctive. Usually arrives in May-June (after tax deadline). OMB 1545-0747.
- **5498-SA**: "HSA, Archer MSA, or Medicare Advantage MSA Information" title. Box layout parallels 5498 but specific to health savings accounts. OMB 1545-0074.

## Other Documents

| Document Type | IRS Form | Typical Source | Key Fields | Filing Tag |
|--------------|----------|---------------|------------|------------|
| Gambling winnings | W-2G | Casinos, lottery, racetracks | Box 1: Reportable winnings; Box 2: Date won; Box 4: Federal tax withheld; Box 7: Type of wager | `w-2g` |

### Visual Identification — W-2G

- **W-2G**: "Certain Gambling Winnings" title. Similar layout to W-2 but specific to gambling. Box 1 is reportable winnings, Box 4 is tax withheld. OMB 1545-0238.

## Common Multi-Form Patterns

Tax document packages often bundle multiple forms. Watch for these patterns:

| Package Type | Typical Contents | How to Spot |
|-------------|-----------------|-------------|
| Brokerage annual tax package | 1099-INT + 1099-DIV + 1099-B + 1099-OID | "Consolidated 1099" header; sections separated by form type; may be 20-50+ pages |
| Employer year-end package | W-2 + state copies + ACA 1095-C | Multiple copies labeled "Copy B", "Copy C", "Copy 2"; state form may follow |
| Partnership/fund tax package | K-1 + supplemental details + state K-1s | Cover letter from fund admin; K-1 is often pages 2-3; supplemental schedules follow |
| Retirement/IRA statement | 1099-R + 5498 | Distribution info + contribution info from same custodian |
| HSA statement | 1099-SA + 5498-SA | Distribution + contribution info from HSA custodian |

## Filing Conventions

When filing to Paperless, use these conventions for tax documents:

- **Title format**: `TY YYYY [Form] - [Payer/Employer]`
  - Example: `TY 2025 W-2 - Acme Corp`
  - Example: `TY 2025 Consolidated 1099 - Fidelity Investments`
  - Example: `TY 2025 K-1 (1065) - ABC Partners LP`
- **Primary tag**: `financial`
- **Secondary tag**: `tax-relevant`
- **Form-specific tag**: use the tag from the "Filing Tag" column above
- **Correspondent**: set to payer, employer, or issuing institution
- **Document type**: `Tax Document`

For consolidated statements containing multiple form types, use the most comprehensive form designation in the title (e.g., "Consolidated 1099") and add tags for each form type contained within.
