-- ============================================================================
-- 1. Exposure by desk (net & gross)
-- Business question: how much risk capital is each desk carrying, and how
-- much of it nets out (hedged) vs. is genuinely deployed?
-- ============================================================================
SELECT d.desk_name,
       SUM(pv.market_value_usd)                       AS net_exposure,
       SUM(ABS(pv.market_value_usd))                   AS gross_exposure
FROM position_valuations pv
JOIN positions p   ON p.position_id = pv.position_id
JOIN books b       ON b.book_id = p.book_id
JOIN desks d       ON d.desk_id = b.desk_id
GROUP BY d.desk_name
ORDER BY gross_exposure DESC;

-- ============================================================================
-- 2. Exposure by asset class
-- Business question: which product types make up the book?
-- ============================================================================
SELECT i.asset_class,
       SUM(pv.market_value_usd)      AS net_exposure,
       SUM(ABS(pv.market_value_usd)) AS gross_exposure
FROM position_valuations pv
JOIN positions p    ON p.position_id = pv.position_id
JOIN instruments i  ON i.instrument_id = p.instrument_id
GROUP BY i.asset_class
ORDER BY gross_exposure DESC;

-- ============================================================================
-- 3. Largest issuer concentrations (top 5)
-- Business question: which single issuer are we most exposed to, across
-- every desk and book that happens to hold it?
-- ============================================================================
SELECT iss.issuer_name,
       SUM(ABS(pv.market_value_usd)) AS gross_exposure,
       COUNT(*)                      AS n_positions
FROM position_valuations pv
JOIN positions p     ON p.position_id = pv.position_id
JOIN instruments i   ON i.instrument_id = p.instrument_id
JOIN issuers iss     ON iss.issuer_id = i.issuer_id
GROUP BY iss.issuer_name
ORDER BY gross_exposure DESC
LIMIT 5;

-- ============================================================================
-- 4. Latest portfolio VaR / ES (all confidence levels)
-- Business question: what's today's headline risk number?
-- ============================================================================
SELECT as_of_date, metric, value
FROM risk_results
WHERE scope_type = 'Portfolio' AND (metric LIKE '%VaR%' OR metric LIKE '%ES%')
ORDER BY metric;

-- ============================================================================
-- 5. Breached / near-breached limits
-- Business question: what needs escalation today? Demonstrates the payoff
-- of keeping risk_limits (config) and risk_results (actuals) as separate
-- tables joined at query time, rather than storing a precomputed status.
-- ============================================================================
SELECT rl.limit_id, rl.metric, rl.scope_type, rl.scope_value,
       rl.limit_value, rr.value AS actual_value,
       ROUND(100 * rr.value / rl.limit_value, 1) AS utilization_pct,
       CASE
           WHEN rr.value / rl.limit_value >= 1.0 THEN 'RED'
           WHEN rr.value / rl.limit_value >= rl.warning_pct THEN 'AMBER'
           ELSE 'GREEN'
       END AS status
FROM risk_limits rl
JOIN risk_results rr
  ON rr.scope_type = rl.scope_type AND rr.scope_value = rl.scope_value AND rr.metric = rl.metric
WHERE rr.value / rl.limit_value >= rl.warning_pct
ORDER BY utilization_pct DESC;

-- ============================================================================
-- 6. Largest DV01 by desk
-- Business question: which desk carries the most rate risk?
-- ============================================================================
SELECT d.desk_name, SUM(s.dv01) AS total_dv01
FROM sensitivities s
JOIN positions p ON p.position_id = s.position_id
JOIN books b     ON b.book_id = p.book_id
JOIN desks d     ON d.desk_id = b.desk_id
WHERE s.dv01 IS NOT NULL
GROUP BY d.desk_name
ORDER BY total_dv01 DESC;

-- ============================================================================
-- 7. Largest CS01 positions (top 5, position-level)
-- Business question: which individual bonds drive our credit spread risk?
-- ============================================================================
SELECT p.instrument_id, b.book_id, s.cs01
FROM sensitivities s
JOIN positions p ON p.position_id = s.position_id
JOIN books b     ON b.book_id = p.book_id
WHERE s.cs01 IS NOT NULL
ORDER BY s.cs01 DESC
LIMIT 5;

-- ============================================================================
-- 8. Worst stress scenario by total portfolio P&L
-- Business question: which illustrative scenario hurts us most?
-- ============================================================================
SELECT scenario_name, SUM(stress_pnl) AS total_stress_pnl
FROM stress_results
GROUP BY scenario_name
ORDER BY total_stress_pnl ASC;

-- ============================================================================
-- 9. P&L attribution breakdown (latest day)
-- Business question: why did the portfolio move, and how much of that move
-- do we actually understand?
-- ============================================================================
SELECT as_of_date, actual_pnl, explained_pnl, residual_pnl,
       ROUND(100 * explained_pnl / actual_pnl, 1) AS explained_pct,
       equity_delta_pnl, gamma_pnl, vega_pnl, rates_pnl, credit_pnl, fx_pnl
FROM pnl_attribution
ORDER BY as_of_date DESC
LIMIT 1;

-- ============================================================================
-- 10. Failed / warned controls
-- Business question: is today's data trustworthy before we act on any of
-- the numbers above?
-- ============================================================================
SELECT as_of_date, control_name, status, severity, details
FROM control_results
WHERE status != 'PASS'
ORDER BY severity, control_name;

-- ============================================================================
-- 11. Day-over-day VaR change
-- Business question: is risk rising or falling? Uses LAG() over as_of_date -
-- the correct pattern for this, but with only one persisted as_of_date in
-- this project (Module 1's single-snapshot design decision), it correctly
-- returns NULL for day_over_day_change rather than a fabricated number.
-- ============================================================================
SELECT as_of_date, metric, value,
       value - LAG(value) OVER (PARTITION BY metric ORDER BY as_of_date) AS day_over_day_change
FROM risk_results
WHERE metric = 'Historical VaR 99%'
ORDER BY as_of_date;
