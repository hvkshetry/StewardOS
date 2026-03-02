"""Tax year constants, filing status mappings, and Schedule C category maps."""

TAX_YEAR = 2026

# Valid filing statuses for PolicyEngine US
FILING_STATUSES = {
    "single": "SINGLE",
    "married_filing_jointly": "JOINT",
    "married_filing_separately": "SEPARATE",
    "head_of_household": "HEAD_OF_HOUSEHOLD",
}

# 1040-ES quarterly due dates (standard)
QUARTERLY_DUE_DATES = {
    2026: {
        "Q1": "2026-04-15",
        "Q2": "2026-06-15",
        "Q3": "2026-09-15",
        "Q4": "2027-01-15",
    },
}

# Schedule C deduction category mappings
# Maps common Actual Budget category names -> Schedule C line descriptions
SCHEDULE_C_CATEGORIES = {
    # Actual Budget category -> (Schedule C line, description)
    "Home Office": ("line_30", "Business use of home (simplified or actual)"),
    "Office Supplies": ("line_18", "Office expense"),
    "Software & Subscriptions": ("line_18", "Office expense (software)"),
    "Internet": ("line_25", "Utilities (business portion)"),
    "Phone": ("line_25", "Utilities (business portion)"),
    "Health Insurance": ("line_n/a", "Self-employed health insurance deduction (Form 1040)"),
    "Retirement Contributions": ("line_n/a", "SEP-IRA / Solo 401(k) (Form 1040)"),
    "Professional Development": ("line_27a", "Other expenses (education/training)"),
    "Travel": ("line_24a", "Travel"),
    "Meals (Business)": ("line_24b", "Meals (50% deductible)"),
    "Vehicle": ("line_9", "Car and truck expenses"),
    "Legal & Professional": ("line_17", "Legal and professional services"),
    "Advertising": ("line_8", "Advertising"),
    "Insurance (Business)": ("line_15", "Insurance (other than health)"),
    "Rent (Office)": ("line_20b", "Rent - other business property"),
    "Repairs": ("line_21", "Repairs and maintenance"),
    "Taxes & Licenses": ("line_23", "Taxes and licenses"),
    "Contract Labor": ("line_11", "Contract labor"),
    "Bank Fees": ("line_27a", "Other expenses (bank fees)"),
}

# Safe harbor thresholds
# US states supported by PolicyEngine US (all 50 + DC)
# Set default state in server invocation or pass per-call
DEFAULT_STATE = "NY"
SUPPORTED_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
]

SAFE_HARBOR_MULTIPLIER_HIGH_INCOME = 1.10  # 110% of prior year tax if AGI > $150k
SAFE_HARBOR_MULTIPLIER_STANDARD = 1.00     # 100% of prior year tax if AGI <= $150k
SAFE_HARBOR_CURRENT_YEAR_PCT = 0.90        # 90% of current year tax (alternative)
HIGH_INCOME_AGI_THRESHOLD = 150_000
