"""Exact-scope tax configuration for household-tax-mcp.

The server covers a narrow exact surface:
- tax years 2025 and 2026
- jurisdictions US + MA only
- individual and fiduciary return/payment planning
- fail-closed on unsupported forms, credits, entities, and income categories

Tax-Calculator is the required federal individual kernel for this exact engine.
If it is unavailable, the service startup is invalid rather than falling back
to an in-repo approximation.
"""

from __future__ import annotations

from decimal import Decimal

SUPPORTED_TAX_YEARS = (2025, 2026)
DEFAULT_TAX_YEAR = 2026
SUPPORTED_JURISDICTIONS = ("US", "MA")
SUPPORTED_STATE = "MA"
SUPPORTED_ENTITY_TYPES = ("individual", "fiduciary")
SUPPORTED_FILING_STATUSES = (
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
)
SUPPORTED_FIDUCIARY_KINDS = ("trust", "estate")

ZERO = Decimal("0.00")
HUNDRED = Decimal("100.00")

# ---------------------------------------------------------------------------
# Authority bundles and kernel identifiers (year-keyed)
# ---------------------------------------------------------------------------

AUTHORITY_BUNDLE_VERSIONS = {
    2025: "us_ma_2025_v1",
    2026: "us_ma_2026_v1",
}

FEDERAL_INDIVIDUAL_KERNELS = {2025: "taxcalc_2025", 2026: "taxcalc_2026"}
FEDERAL_INDIVIDUAL_KERNEL_REASON = "taxcalc_required_kernel"
FEDERAL_FIDUCIARY_KERNELS = {2025: "builtin_2025_fiduciary_kernel", 2026: "builtin_2026_fiduciary_kernel"}
MASSACHUSETTS_KERNELS = {2025: "builtin_2025_ma_kernel", 2026: "builtin_2026_ma_kernel"}

# ---------------------------------------------------------------------------
# Federal individual constants (documentation — Tax-Calculator loads
# these internally via policy.set_year(); included for reference only)
# ---------------------------------------------------------------------------

# Standard deduction: Rev. Proc. 2024-40 (TY2025), Rev. Proc. 2025-32 (TY2026).
FEDERAL_STANDARD_DEDUCTION = {
    2025: {
        "single": Decimal("15750.00"),
        "married_filing_jointly": Decimal("31500.00"),
        "married_filing_separately": Decimal("15750.00"),
        "head_of_household": Decimal("23625.00"),
    },
    2026: {
        "single": Decimal("16100.00"),
        "married_filing_jointly": Decimal("32200.00"),
        "married_filing_separately": Decimal("16100.00"),
        "head_of_household": Decimal("24150.00"),
    },
}

# Ordinary income brackets: Rev. Proc. 2024-40 (TY2025), Rev. Proc. 2025-32 (TY2026).
FEDERAL_ORDINARY_BRACKETS = {
    2025: {
        "single": (
            (Decimal("0.00"), Decimal("11925.00"), Decimal("0.10")),
            (Decimal("11925.00"), Decimal("48475.00"), Decimal("0.12")),
            (Decimal("48475.00"), Decimal("103350.00"), Decimal("0.22")),
            (Decimal("103350.00"), Decimal("197300.00"), Decimal("0.24")),
            (Decimal("197300.00"), Decimal("250525.00"), Decimal("0.32")),
            (Decimal("250525.00"), Decimal("626350.00"), Decimal("0.35")),
            (Decimal("626350.00"), None, Decimal("0.37")),
        ),
        "married_filing_jointly": (
            (Decimal("0.00"), Decimal("23850.00"), Decimal("0.10")),
            (Decimal("23850.00"), Decimal("96950.00"), Decimal("0.12")),
            (Decimal("96950.00"), Decimal("206700.00"), Decimal("0.22")),
            (Decimal("206700.00"), Decimal("394600.00"), Decimal("0.24")),
            (Decimal("394600.00"), Decimal("501050.00"), Decimal("0.32")),
            (Decimal("501050.00"), Decimal("751600.00"), Decimal("0.35")),
            (Decimal("751600.00"), None, Decimal("0.37")),
        ),
        "married_filing_separately": (
            (Decimal("0.00"), Decimal("11925.00"), Decimal("0.10")),
            (Decimal("11925.00"), Decimal("48475.00"), Decimal("0.12")),
            (Decimal("48475.00"), Decimal("103350.00"), Decimal("0.22")),
            (Decimal("103350.00"), Decimal("197300.00"), Decimal("0.24")),
            (Decimal("197300.00"), Decimal("250525.00"), Decimal("0.32")),
            (Decimal("250525.00"), Decimal("375800.00"), Decimal("0.35")),
            (Decimal("375800.00"), None, Decimal("0.37")),
        ),
        "head_of_household": (
            (Decimal("0.00"), Decimal("17000.00"), Decimal("0.10")),
            (Decimal("17000.00"), Decimal("64850.00"), Decimal("0.12")),
            (Decimal("64850.00"), Decimal("103350.00"), Decimal("0.22")),
            (Decimal("103350.00"), Decimal("197300.00"), Decimal("0.24")),
            (Decimal("197300.00"), Decimal("250500.00"), Decimal("0.32")),
            (Decimal("250500.00"), Decimal("626350.00"), Decimal("0.35")),
            (Decimal("626350.00"), None, Decimal("0.37")),
        ),
    },
    2026: {
        "single": (
            (Decimal("0.00"), Decimal("12400.00"), Decimal("0.10")),
            (Decimal("12400.00"), Decimal("50400.00"), Decimal("0.12")),
            (Decimal("50400.00"), Decimal("105700.00"), Decimal("0.22")),
            (Decimal("105700.00"), Decimal("201775.00"), Decimal("0.24")),
            (Decimal("201775.00"), Decimal("256225.00"), Decimal("0.32")),
            (Decimal("256225.00"), Decimal("640600.00"), Decimal("0.35")),
            (Decimal("640600.00"), None, Decimal("0.37")),
        ),
        "married_filing_jointly": (
            (Decimal("0.00"), Decimal("24800.00"), Decimal("0.10")),
            (Decimal("24800.00"), Decimal("100800.00"), Decimal("0.12")),
            (Decimal("100800.00"), Decimal("211400.00"), Decimal("0.22")),
            (Decimal("211400.00"), Decimal("403550.00"), Decimal("0.24")),
            (Decimal("403550.00"), Decimal("512450.00"), Decimal("0.32")),
            (Decimal("512450.00"), Decimal("768700.00"), Decimal("0.35")),
            (Decimal("768700.00"), None, Decimal("0.37")),
        ),
        "married_filing_separately": (
            (Decimal("0.00"), Decimal("12400.00"), Decimal("0.10")),
            (Decimal("12400.00"), Decimal("50400.00"), Decimal("0.12")),
            (Decimal("50400.00"), Decimal("105700.00"), Decimal("0.22")),
            (Decimal("105700.00"), Decimal("201775.00"), Decimal("0.24")),
            (Decimal("201775.00"), Decimal("256225.00"), Decimal("0.32")),
            (Decimal("256225.00"), Decimal("384350.00"), Decimal("0.35")),
            (Decimal("384350.00"), None, Decimal("0.37")),
        ),
        "head_of_household": (
            (Decimal("0.00"), Decimal("17700.00"), Decimal("0.10")),
            (Decimal("17700.00"), Decimal("67450.00"), Decimal("0.12")),
            (Decimal("67450.00"), Decimal("105700.00"), Decimal("0.22")),
            (Decimal("105700.00"), Decimal("201750.00"), Decimal("0.24")),
            (Decimal("201750.00"), Decimal("256200.00"), Decimal("0.32")),
            (Decimal("256200.00"), Decimal("640600.00"), Decimal("0.35")),
            (Decimal("640600.00"), None, Decimal("0.37")),
        ),
    },
}

# Preferential rate thresholds (LTCG / qualified dividends).
FEDERAL_PREFERENTIAL_THRESHOLDS = {
    2025: {
        "single": {"zero_rate_top": Decimal("48350.00"), "fifteen_rate_top": Decimal("533400.00")},
        "married_filing_jointly": {"zero_rate_top": Decimal("96700.00"), "fifteen_rate_top": Decimal("600050.00")},
        "married_filing_separately": {"zero_rate_top": Decimal("48350.00"), "fifteen_rate_top": Decimal("300025.00")},
        "head_of_household": {"zero_rate_top": Decimal("64750.00"), "fifteen_rate_top": Decimal("566700.00")},
    },
    2026: {
        "single": {"zero_rate_top": Decimal("49450.00"), "fifteen_rate_top": Decimal("545500.00")},
        "married_filing_jointly": {"zero_rate_top": Decimal("98900.00"), "fifteen_rate_top": Decimal("613700.00")},
        "married_filing_separately": {"zero_rate_top": Decimal("49450.00"), "fifteen_rate_top": Decimal("306850.00")},
        "head_of_household": {"zero_rate_top": Decimal("66200.00"), "fifteen_rate_top": Decimal("579600.00")},
    },
}

# NIIT thresholds — statutory, not inflation-adjusted (IRC section 1411).
FEDERAL_NIIT_THRESHOLDS = {
    "single": Decimal("200000.00"),
    "married_filing_jointly": Decimal("250000.00"),
    "married_filing_separately": Decimal("125000.00"),
    "head_of_household": Decimal("200000.00"),
}
FEDERAL_NIIT_RATE = Decimal("0.038")

# ---------------------------------------------------------------------------
# Federal fiduciary constants (builtin kernel — used in code)
# ---------------------------------------------------------------------------

# Fiduciary ordinary brackets: Rev. Proc. 2024-40 (TY2025), Rev. Proc. 2025-32 (TY2026).
FEDERAL_FIDUCIARY_BRACKETS = {
    2025: (
        (Decimal("0.00"), Decimal("3150.00"), Decimal("0.10")),
        (Decimal("3150.00"), Decimal("11450.00"), Decimal("0.24")),
        (Decimal("11450.00"), Decimal("15650.00"), Decimal("0.35")),
        (Decimal("15650.00"), None, Decimal("0.37")),
    ),
    2026: (
        (Decimal("0.00"), Decimal("3300.00"), Decimal("0.10")),
        (Decimal("3300.00"), Decimal("11700.00"), Decimal("0.24")),
        (Decimal("11700.00"), Decimal("16000.00"), Decimal("0.35")),
        (Decimal("16000.00"), None, Decimal("0.37")),
    ),
}

FEDERAL_FIDUCIARY_PREFERENTIAL_THRESHOLDS = {
    2025: {
        "zero_rate_top": Decimal("3150.00"),
        "fifteen_rate_top": Decimal("15450.00"),
    },
    2026: {
        "zero_rate_top": Decimal("3300.00"),
        "fifteen_rate_top": Decimal("16250.00"),
    },
}

FEDERAL_FIDUCIARY_NIIT_THRESHOLD = {
    2025: Decimal("15650.00"),
    2026: Decimal("16000.00"),
}

# Fiduciary exemption — statutory, not inflation-adjusted.
FIDUCIARY_EXEMPTION = {
    "estate": Decimal("600.00"),
    "simple_trust": Decimal("300.00"),
    "complex_trust": Decimal("100.00"),
}

# ---------------------------------------------------------------------------
# Massachusetts constants (builtin kernel — used in code)
# ---------------------------------------------------------------------------

# MA rates are statutory / fixed.
MA_GENERAL_RATE = Decimal("0.05")
MA_SHORT_TERM_CAPITAL_GAINS_RATE = Decimal("0.085")
MA_SURTAX_RATE = Decimal("0.04")

# Surtax threshold: MA DOR Circular M 2025 / 2026.
MA_SURTAX_THRESHOLD = {
    2025: Decimal("1083150.00"),
    2026: Decimal("1107750.00"),
}

# Personal exemption: MA DOR 2025 / 2026 — same values both years.
MA_PERSONAL_EXEMPTION = {
    2025: {
        "single": Decimal("4400.00"),
        "married_filing_jointly": Decimal("8800.00"),
        "married_filing_separately": Decimal("4400.00"),
        "head_of_household": Decimal("6800.00"),
    },
    2026: {
        "single": Decimal("4400.00"),
        "married_filing_jointly": Decimal("8800.00"),
        "married_filing_separately": Decimal("4400.00"),
        "head_of_household": Decimal("6800.00"),
    },
}

# ---------------------------------------------------------------------------
# Estimated payment and safe-harbor constants (statutory — year-independent)
# ---------------------------------------------------------------------------

FEDERAL_ESTIMATED_TAX_TRIGGER = Decimal("1000.00")
FEDERAL_REQUIRED_PAYMENT_RATIO = Decimal("0.90")
FEDERAL_PRIOR_YEAR_HIGH_AGI_THRESHOLD = Decimal("150000.00")
FEDERAL_PRIOR_YEAR_HIGH_AGI_RATIO = Decimal("1.10")
FEDERAL_PRIOR_YEAR_STANDARD_RATIO = Decimal("1.00")

MA_ESTIMATED_TAX_TRIGGER = Decimal("400.00")
MA_REQUIRED_PAYMENT_RATIO = Decimal("0.80")

FEDERAL_ANNUALIZATION_FACTORS = (
    Decimal("4.0"),
    Decimal("2.4"),
    Decimal("1.5"),
    Decimal("1.0"),
)
FEDERAL_ANNUALIZED_CUMULATIVE_PERCENTAGES = (
    Decimal("0.225"),
    Decimal("0.450"),
    Decimal("0.675"),
    Decimal("0.900"),
)
MA_REGULAR_CUMULATIVE_PERCENTAGES = (
    Decimal("0.25"),
    Decimal("0.50"),
    Decimal("0.75"),
    Decimal("1.00"),
)
MA_ANNUALIZED_CUMULATIVE_PERCENTAGES = (
    Decimal("0.20"),
    Decimal("0.40"),
    Decimal("0.60"),
    Decimal("0.80"),
)

# ---------------------------------------------------------------------------
# Installment due dates and annualization periods (year-keyed)
# ---------------------------------------------------------------------------

FEDERAL_INSTALLMENT_DUE_DATES = {
    2025: ("2025-04-15", "2025-06-16", "2025-09-15", "2026-01-15"),
    2026: ("2026-04-15", "2026-06-15", "2026-09-15", "2027-01-15"),
}

MA_INSTALLMENT_DUE_DATES = {
    2025: ("2025-04-15", "2025-06-16", "2025-09-15", "2026-01-15"),
    2026: ("2026-04-15", "2026-06-16", "2026-09-15", "2027-01-15"),
}

ANNUALIZED_INCOME_PERIOD_END_DATES = {
    2025: ("2025-03-31", "2025-05-31", "2025-08-31", "2025-12-31"),
    2026: ("2026-03-31", "2026-05-31", "2026-08-31", "2026-12-31"),
}

# ---------------------------------------------------------------------------
# SALT cap (OBBB Act, TY2025+) — Tax-Calculator handles the phase-down
# internally; stored here for documentation/validation reference.
# ---------------------------------------------------------------------------

SALT_CAP = {
    2025: {"default": Decimal("40000.00"), "married_filing_separately": Decimal("20000.00")},
    2026: {"default": Decimal("40000.00"), "married_filing_separately": Decimal("20000.00")},
}

# ---------------------------------------------------------------------------
# Feature support configuration
# ---------------------------------------------------------------------------

INDIVIDUAL_RECOGNIZED_UNSUPPORTED_FIELDS = {
    "other_ordinary_income",
    "self_employment_income",
    "qbi_deduction",
    "foreign_tax_credit",
    "other_nonrefundable_credits",
    "social_security_benefits",
    "rental_income",
    "k1_income",
    "farm_income",
    "tax_exempt_interest",
    "multi_state_allocations",
}

FIDUCIARY_RECOGNIZED_UNSUPPORTED_FIELDS = {
    "charitable_deduction",
    "tax_exempt_interest",
    "foreign_tax_credit",
    "alternative_minimum_tax",
    "accumulation_distribution",
    "throwback_tax",
    "net_operating_loss",
    "special_election_flags",
    "multi_state_allocations",
}

# ---------------------------------------------------------------------------
# Supported scope descriptions
# ---------------------------------------------------------------------------

INDIVIDUAL_SUPPORTED_SCOPE = (
    "2025/2026 federal + Massachusetts resident returns",
    "wages, taxable interest, ordinary dividends, qualified dividends, short-term gains, and long-term gains",
    "standard deduction or itemized deductions (medical, SALT, mortgage interest, charitable, casualty, other)",
    "child tax credit with qualifying dependents",
    "alternative minimum tax exposure",
    "Massachusetts raw simple base or explicit Massachusetts taxable line amounts",
    "prior-year tax facts, withholding, estimated payments, and optional annualized-income periods for safe-harbor planning",
)

FIDUCIARY_SUPPORTED_SCOPE = (
    "2025/2026 federal + Massachusetts resident trust and estate returns",
    "taxable interest, ordinary dividends, qualified dividends, short-term gains, long-term gains, other ordinary income",
    "deductions, fiduciary exemption, prior-year tax facts, withholding, and estimated payments",
    "optional annualized-income periods for exact safe-harbor planning",
    "distribution planning only when capital gains DNI treatment is explicitly provided",
)
