BEGIN;

CREATE SCHEMA IF NOT EXISTS finance;
SET search_path TO finance;

CREATE TABLE IF NOT EXISTS party_refs (
    party_uuid          UUID PRIMARY KEY,
    party_type          TEXT NOT NULL CHECK (party_type IN ('person', 'entity')),
    legal_name          TEXT NOT NULL,
    jurisdiction_code   TEXT,
    status              TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS liability_types (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS liabilities (
    id                      SERIAL PRIMARY KEY,
    name                    TEXT NOT NULL,
    liability_type_code     TEXT NOT NULL REFERENCES liability_types(code),
    jurisdiction_id         INTEGER REFERENCES jurisdictions(id),
    primary_borrower_uuid   UUID NOT NULL REFERENCES party_refs(party_uuid),
    collateral_asset_id     INTEGER REFERENCES assets(id),
    lender_name             TEXT,
    account_number_last4    TEXT,
    currency                TEXT NOT NULL DEFAULT 'USD',
    origination_date        DATE,
    maturity_date           DATE,
    original_principal      NUMERIC(20,4),
    outstanding_principal   NUMERIC(20,4) NOT NULL,
    credit_limit            NUMERIC(20,4),
    rate_type               TEXT NOT NULL DEFAULT 'fixed',
    rate_index              TEXT,
    interest_rate           NUMERIC(9,6),
    rate_spread_bps         NUMERIC(10,4),
    amortization_months     INTEGER,
    remaining_term_months   INTEGER,
    payment_frequency       TEXT NOT NULL DEFAULT 'monthly',
    scheduled_payment       NUMERIC(20,4),
    escrow_payment          NUMERIC(20,4),
    next_payment_date       DATE,
    prepayment_penalty      NUMERIC(20,4),
    status                  TEXT NOT NULL DEFAULT 'active',
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS liability_rate_terms (
    id                      SERIAL PRIMARY KEY,
    liability_id            INTEGER NOT NULL REFERENCES liabilities(id) ON DELETE CASCADE,
    effective_date          DATE NOT NULL,
    rate_type               TEXT NOT NULL,
    rate_index              TEXT,
    interest_rate           NUMERIC(9,6),
    rate_spread_bps         NUMERIC(10,4),
    cap_rate                NUMERIC(9,6),
    floor_rate              NUMERIC(9,6),
    reset_frequency_months  INTEGER,
    notes                   TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT liability_rate_terms_unique UNIQUE (liability_id, effective_date)
);

CREATE TABLE IF NOT EXISTS liability_payments (
    id                      SERIAL PRIMARY KEY,
    liability_id            INTEGER NOT NULL REFERENCES liabilities(id) ON DELETE CASCADE,
    payment_date            DATE NOT NULL,
    amount_total            NUMERIC(20,4) NOT NULL,
    amount_principal        NUMERIC(20,4),
    amount_interest         NUMERIC(20,4),
    amount_escrow           NUMERIC(20,4),
    source                  TEXT NOT NULL DEFAULT 'manual',
    reference               TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS liability_cashflow_schedule (
    id                      SERIAL PRIMARY KEY,
    liability_id            INTEGER NOT NULL REFERENCES liabilities(id) ON DELETE CASCADE,
    due_date                DATE NOT NULL,
    opening_balance         NUMERIC(20,4) NOT NULL,
    payment_total           NUMERIC(20,4) NOT NULL,
    payment_principal       NUMERIC(20,4) NOT NULL,
    payment_interest        NUMERIC(20,4) NOT NULL,
    payment_escrow          NUMERIC(20,4),
    closing_balance         NUMERIC(20,4) NOT NULL,
    scenario_tag            TEXT NOT NULL DEFAULT 'base',
    source                  TEXT NOT NULL DEFAULT 'generated',
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT liability_cashflow_unique UNIQUE (liability_id, due_date, scenario_tag)
);

CREATE TABLE IF NOT EXISTS refinance_offers (
    id                          SERIAL PRIMARY KEY,
    liability_id                INTEGER NOT NULL REFERENCES liabilities(id) ON DELETE CASCADE,
    offer_date                  DATE NOT NULL,
    lender_name                 TEXT,
    product_type                TEXT NOT NULL DEFAULT 'rate_term_refi',
    offered_rate                NUMERIC(9,6) NOT NULL,
    rate_type                   TEXT NOT NULL DEFAULT 'fixed',
    offered_term_months         INTEGER NOT NULL,
    offered_principal           NUMERIC(20,4),
    points_cost                 NUMERIC(20,4) NOT NULL DEFAULT 0,
    lender_fees                 NUMERIC(20,4) NOT NULL DEFAULT 0,
    third_party_fees            NUMERIC(20,4) NOT NULL DEFAULT 0,
    prepayment_penalty_cost     NUMERIC(20,4) NOT NULL DEFAULT 0,
    cash_out_amount             NUMERIC(20,4) NOT NULL DEFAULT 0,
    metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS liability_analytics_runs (
    id                          SERIAL PRIMARY KEY,
    liability_id                INTEGER NOT NULL REFERENCES liabilities(id) ON DELETE CASCADE,
    refinance_offer_id          INTEGER REFERENCES refinance_offers(id) ON DELETE SET NULL,
    run_type                    TEXT NOT NULL,
    run_date                    DATE NOT NULL,
    recommendation              TEXT NOT NULL,
    npv_savings                 NUMERIC(20,4),
    break_even_months           NUMERIC(12,4),
    annual_payment_change       NUMERIC(20,4),
    assumptions                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    outputs                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_liabilities_borrower ON liabilities(primary_borrower_uuid, status);
CREATE INDEX IF NOT EXISTS idx_liabilities_collateral ON liabilities(collateral_asset_id);
CREATE INDEX IF NOT EXISTS idx_liability_schedule_due_date ON liability_cashflow_schedule(liability_id, due_date);
CREATE INDEX IF NOT EXISTS idx_liability_payments_date ON liability_payments(liability_id, payment_date);
CREATE INDEX IF NOT EXISTS idx_refinance_offers_liability_date ON refinance_offers(liability_id, offer_date);
CREATE INDEX IF NOT EXISTS idx_liability_analytics_runs_liability ON liability_analytics_runs(liability_id, run_date);

INSERT INTO liability_types (code, name, description) VALUES
    ('mortgage_fixed', 'Fixed-Rate Mortgage', 'Traditional amortizing mortgage with fixed note rate'),
    ('mortgage_arm', 'Adjustable-Rate Mortgage', 'Mortgage with periodic index+spread resets'),
    ('heloc', 'Home Equity Line of Credit', 'Revolving home-equity credit line with variable rate'),
    ('home_equity_loan', 'Home Equity Loan', 'Second-lien amortizing loan against home equity'),
    ('other_secured', 'Other Secured Debt', 'Other long-term debt collateralized by specific assets')
ON CONFLICT (code) DO NOTHING;

COMMIT;
