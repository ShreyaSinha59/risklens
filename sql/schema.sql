-- Trading Book Risk & Controls: PostgreSQL schema
-- Deliberately not over-normalized: results tables carry a redundant
-- as_of_date for query simplicity/date-partitioning; risk_results is a
-- generic metric store rather than one table per metric type.

-- ============================== REFERENCE DATA ==============================

CREATE TABLE desks (
    desk_id             TEXT PRIMARY KEY,
    desk_name           TEXT NOT NULL,
    asset_class_focus   TEXT NOT NULL
);

CREATE TABLE books (
    book_id             TEXT PRIMARY KEY,
    book_name           TEXT NOT NULL,
    desk_id             TEXT NOT NULL REFERENCES desks(desk_id)
);

CREATE TABLE issuers (
    issuer_id           TEXT PRIMARY KEY,
    issuer_name         TEXT NOT NULL,
    issuer_type         TEXT NOT NULL,
    country             TEXT NOT NULL,
    sector              TEXT,
    credit_rating       TEXT NOT NULL
);

CREATE TABLE instruments (
    instrument_id             TEXT PRIMARY KEY,
    instrument_name           TEXT NOT NULL,
    asset_class               TEXT NOT NULL,
    issuer_id                 TEXT REFERENCES issuers(issuer_id),               -- NULL for FX
    underlying_instrument_id  TEXT REFERENCES instruments(instrument_id),        -- Equity Option only
    currency                  TEXT,
    base_currency              TEXT,
    quote_currency             TEXT,
    maturity_date              DATE,
    coupon_rate                NUMERIC,
    strike_price                NUMERIC,
    option_type                TEXT,
    contract_multiplier        NUMERIC
);

-- ================================ SOURCE DATA ================================

CREATE TABLE positions (
    position_id         TEXT PRIMARY KEY,
    as_of_date          DATE NOT NULL,
    book_id             TEXT NOT NULL REFERENCES books(book_id),
    instrument_id       TEXT NOT NULL REFERENCES instruments(instrument_id),
    quantity            NUMERIC NOT NULL,
    UNIQUE (book_id, instrument_id, as_of_date)
);

CREATE TABLE market_data (
    as_of_date          DATE NOT NULL,
    risk_factor_id      TEXT NOT NULL,
    risk_factor_type    TEXT NOT NULL,
    value               NUMERIC NOT NULL,
    PRIMARY KEY (as_of_date, risk_factor_id)
);

-- ============================== DERIVED / RESULTS ==============================

CREATE TABLE position_valuations (
    position_id         TEXT PRIMARY KEY REFERENCES positions(position_id),
    as_of_date          DATE NOT NULL,
    currency            TEXT NOT NULL,
    market_value_local  NUMERIC NOT NULL,
    market_value_usd    NUMERIC NOT NULL
);

CREATE TABLE sensitivities (
    position_id         TEXT PRIMARY KEY REFERENCES positions(position_id),
    as_of_date          DATE NOT NULL,
    delta               NUMERIC,
    gamma               NUMERIC,
    vega                NUMERIC,
    dv01                NUMERIC,
    cs01                NUMERIC
);

-- Generic scalar metric store: VaR/ES (scope_type='Portfolio'), stress totals
-- (scope_type='Portfolio', metric='Stress Loss: <scenario>'), DV01/CS01
-- aggregates (scope_type='Desk'), issuer concentration (scope_type='Issuer').
CREATE TABLE risk_results (
    id                  SERIAL PRIMARY KEY,
    as_of_date          DATE NOT NULL,
    scope_type          TEXT NOT NULL,      -- Portfolio / Desk / Issuer
    scope_value         TEXT NOT NULL,
    metric              TEXT NOT NULL,      -- e.g. 'Historical VaR 99%', 'DV01', 'Issuer Gross Exposure'
    value               NUMERIC NOT NULL,
    UNIQUE (as_of_date, scope_type, scope_value, metric)
);

CREATE TABLE pnl_attribution (
    id                  SERIAL PRIMARY KEY,
    as_of_date          DATE NOT NULL,
    scenario_date       DATE NOT NULL,
    actual_pnl          NUMERIC NOT NULL,
    explained_pnl       NUMERIC NOT NULL,
    residual_pnl        NUMERIC NOT NULL,
    equity_delta_pnl    NUMERIC,
    gamma_pnl           NUMERIC,
    vega_pnl            NUMERIC,
    rates_pnl           NUMERIC,
    credit_pnl          NUMERIC,
    fx_pnl              NUMERIC,
    UNIQUE (as_of_date, scenario_date)
);

CREATE TABLE stress_results (
    as_of_date          DATE NOT NULL,
    scenario_name       TEXT NOT NULL,
    position_id         TEXT NOT NULL REFERENCES positions(position_id),
    stress_pnl          NUMERIC NOT NULL,
    PRIMARY KEY (as_of_date, scenario_name, position_id)
);

-- =================================== CONFIG ===================================

CREATE TABLE risk_limits (
    limit_id            TEXT PRIMARY KEY,
    metric              TEXT NOT NULL,
    scope_type          TEXT NOT NULL,
    scope_value         TEXT NOT NULL,
    limit_value         NUMERIC NOT NULL,
    warning_pct         NUMERIC NOT NULL
);

-- =================================== CONTROL ===================================

CREATE TABLE control_results (
    id                  SERIAL PRIMARY KEY,
    as_of_date          DATE NOT NULL,
    control_name        TEXT NOT NULL,
    status              TEXT NOT NULL,      -- PASS / WARN / FAIL
    severity            TEXT NOT NULL,      -- Low / Medium / High
    details             JSONB,
    UNIQUE (as_of_date, control_name)
);

CREATE INDEX idx_positions_book ON positions(book_id);
CREATE INDEX idx_positions_instrument ON positions(instrument_id);
CREATE INDEX idx_market_data_rf ON market_data(risk_factor_id);
CREATE INDEX idx_risk_results_lookup ON risk_results(as_of_date, scope_type, metric);
CREATE INDEX idx_stress_results_scenario ON stress_results(as_of_date, scenario_name);

-- Added for Module 10 (API/Dashboard): persists Module 8's FRTB mapping,
-- which previously only existed as a CSV.
CREATE TABLE frtb_mapping (
    id                  SERIAL PRIMARY KEY,
    as_of_date          DATE NOT NULL,
    position_id         TEXT NOT NULL REFERENCES positions(position_id),
    instrument_id       TEXT NOT NULL,
    asset_class         TEXT NOT NULL,
    frtb_risk_class     TEXT NOT NULL,
    risk_factor         TEXT NOT NULL,
    sensitivity_type    TEXT NOT NULL,
    sensitivity_value   NUMERIC,
    UNIQUE (as_of_date, position_id, frtb_risk_class, sensitivity_type)
);
