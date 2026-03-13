# IRS Form Matrix

Use this matrix to map source documents to IRS forms and identify required schedules during tax-form-prep.

## Federal Forms

| IRS Form | Purpose | Source Documents | Key Lines | Notes |
|----------|---------|-----------------|-----------|-------|
| **Form 1040** | U.S. Individual Income Tax Return | All W-2, 1099, K-1 | L1 wages, L2b interest, L3b dividends, L7 capital gain/loss, L8 other income, L11 AGI, L15 taxable income, L24 total tax, L37 amount owed/refund | Primary individual return; all schedules attach here |
| **Form 1041** | U.S. Income Tax Return for Estates and Trusts | K-1 (received), 1099-INT, 1099-DIV, 1099-B | L1 interest, L2a dividends, L4 capital gain/loss, L9 total income, L17 taxable income, L23 total tax | Fiduciary return; distributable net income (DNI) drives K-1 issuance |
| **Schedule A** | Itemized Deductions | 1098 (mortgage interest), property tax records, charitable receipts, medical receipts | L4 medical (>7.5% AGI), L5b state/local taxes (SALT $10K cap), L8a mortgage interest, L12 charitable, L17 total | Only beneficial when total exceeds standard deduction |
| **Schedule B** | Interest and Ordinary Dividends | 1099-INT, 1099-DIV | Part I: interest payers/amounts, Part II: dividend payers/amounts, Part III: foreign accounts | Required when interest or ordinary dividends exceed $1,500 |
| **Schedule C** | Profit or Loss from Business | 1099-NEC, 1099-MISC, business records | L1 gross receipts, L7 gross income, L28 tentative profit, L31 net profit/loss | Sole proprietorship/self-employment; feeds Schedule SE |
| **Schedule D** | Capital Gains and Losses | 1099-B, Form 8949 | L7 net short-term, L15 net long-term, L16 combined, L21 worksheet or L22 28% rate | Summarizes Form 8949; short-term vs long-term distinction critical |
| **Schedule E** | Supplemental Income and Loss | K-1 (partnership, S-corp, trust), rental records | Part I: rental (L3 rents, L21 net), Part II: partnership/S-corp (L32 total), Part III: estate/trust (L37 total) | Pass-through income; passive activity rules apply |
| **Schedule SE** | Self-Employment Tax | Schedule C net profit | L4 net earnings, L12 SE tax | Required when Schedule C net profit >= $400; 15.3% rate (12.4% SS + 2.9% Medicare) |
| **Form 8949** | Sales and Other Dispositions of Capital Assets | 1099-B (detailed transactions) | Col (a) description, (b) date acquired, (c) date sold, (d) proceeds, (e) basis, (h) gain/loss | Part I: short-term, Part II: long-term; totals flow to Schedule D |
| **Form 8960** | Net Investment Income Tax (NIIT) | 1099-INT, 1099-DIV, 1099-B, K-1 | L1 interest, L2 annuities, L3 rental/royalty, L4a net gain, L8 NII, L9 MAGI, L11 tax (3.8%) | Applies when MAGI exceeds $200K (single) / $250K (MFJ) |
| **Form 6251** | Alternative Minimum Tax (AMT) | All income docs, Schedule A | L1 taxable income, L2a-L2g adjustments, L7 AMTI, L10 exemption, L11 AMT base, L12 tentative AMT | Triggered by large SALT, ISO exercises, or high deductions |
| **Form 1040-ES** | Estimated Tax for Individuals | Prior year return, projected income | Worksheet L1 AGI, L11a estimated tax, L14b required annual payment | Quarterly vouchers; safe harbor = 100% prior year (110% if AGI > $150K) |

## Massachusetts State Forms

| MA Form | Purpose | Source Documents | Key Lines | Notes |
|---------|---------|-----------------|-----------|-------|
| **Form 1** | Massachusetts Resident Income Tax Return | Federal return, all W-2/1099/K-1 | L3 Part A 5% income (wages, interest, long-term gains), L6 Part B 5% income (interest/dividends taxed differently federally), L10 Part C 12% income (short-term capital gains) | Three-part income classification; no federal Schedule A passthrough |
| **Schedule B (MA)** | Interest, Dividends, and Certain Capital Gains | 1099-INT, 1099-DIV, 1099-B | Interest and dividend detail, bank interest exclusion ($100 single / $200 joint) | MA-specific; bank interest partially exempt |

## Document-to-Form Routing

| Source Document | Primary Form(s) | Secondary Form(s) |
|-----------------|------------------|--------------------|
| W-2 | 1040 L1 | Form 1 L3 (MA) |
| 1099-INT | Schedule B Part I, 1040 L2b | Form 8960 L1, Schedule B (MA) |
| 1099-DIV | Schedule B Part II, 1040 L3b | Form 8960 L2, Schedule D (qualified dividends), Schedule B (MA) |
| 1099-B | Form 8949, Schedule D | Form 8960 L4a, Form 1 L10 (MA short-term) |
| 1099-NEC | Schedule C | Schedule SE |
| 1099-MISC | Schedule C or Schedule E | — |
| 1099-R | 1040 L5b | Form 1 L3 (MA) |
| K-1 (partnership) | Schedule E Part II | Form 8960 (if NII), Schedule D (if capital gains) |
| K-1 (S-corp) | Schedule E Part II | Schedule D (if capital gains) |
| K-1 (trust) | Schedule E Part III | Form 8960 (if NII) |
| 1098 | Schedule A L8a | — |
| 1098-T | Form 8863 (education credits) | — |
