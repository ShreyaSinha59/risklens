# UAT Cases — Trading Book Risk & Controls

Manual, business-user-facing acceptance tests. Run against the live dashboard
(`streamlit run src/dashboard.py`) and API (`uvicorn src.api:app --port 8000`)
after an EOD pipeline run (`python src/run_eod_pipeline.py`).

| Field | Meaning |
|---|---|
| Status | Pass / Fail / Blocked — filled in by the tester, not pre-set |

---

**UAT-01**
- Requirement/Feature: 99% VaR displayed correctly
- Scenario: Risk Manager checks today's headline VaR before the morning risk meeting
- Precondition: EOD pipeline has run for today's `as_of_date`
- Steps: 1) Open Executive Dashboard. 2) Read the "99% VaR (1-day)" tile.
- Expected Result: Value matches `GET /risk/var` for `metric='Historical VaR 99%'`, formatted as USD
- Status: ______

**UAT-02**
- Requirement/Feature: Expected Shortfall consistency
- Scenario: Analyst wants to confirm ES is never understated relative to VaR
- Precondition: VaR/ES persisted for the current date
- Steps: 1) Call `GET /risk/var`. 2) Compare `Historical ES 99%` to `Historical VaR 99%`.
- Expected Result: ES ≥ VaR at both 95% and 99%
- Status: ______

**UAT-03**
- Requirement/Feature: Sensitivities by desk
- Scenario: Analyst wants to know which desk carries the most rate risk today
- Precondition: Sensitivities persisted
- Steps: 1) Open Risk Explorer -> "By Desk" tab. 2) Read DV01 column.
- Expected Result: Fixed Income Desk shows the only non-null DV01; Equities/FX Desks show blank, not zero or an error
- Status: ______

**UAT-04**
- Requirement/Feature: Option Greeks are asset-class-appropriate
- Scenario: Analyst inspects an equity option position
- Precondition: An Equity Option position exists (e.g. `AAPL-OPT-C-500-20270130`)
- Steps: 1) Open Risk Explorer -> Position-Level tab. 2) Find the option row.
- Expected Result: Delta, Gamma, Vega are populated; DV01, CS01 are blank for that row
- Status: ______

**UAT-05**
- Requirement/Feature: P&L Attribution reconciles
- Scenario: Analyst investigates yesterday's P&L move
- Precondition: `pnl_attribution` persisted for the latest scenario date
- Steps: 1) Open P&L & Stress page. 2) Read the waterfall chart's final "Actual P&L" total bar.
- Expected Result: Sum of the individual factor bars (Equity/Delta, Gamma, Vega, Rates, Credit, FX, Residual) equals the Actual P&L total bar exactly
- Status: ______

**UAT-06**
- Requirement/Feature: Stress scenario severity ordering
- Scenario: Manager wants confirmation the combined scenario is genuinely the worst case
- Precondition: Stress results persisted for all 4 scenarios
- Steps: 1) Open P&L & Stress page. 2) Read the Stress Scenario Comparison chart.
- Expected Result: "Combined Severe Market Stress" shows a larger loss than each of the 3 single-factor scenarios individually
- Status: ______

**UAT-07**
- Requirement/Feature: Limit breach is visible and correctly colored
- Scenario: Controls user checks for active breaches
- Precondition: JPM issuer concentration limit is configured at $35M (`config/risk_limits.json`)
- Steps: 1) Open Limits & Breach Investigation page. 2) Locate the JPM Issuer Concentration row.
- Expected Result: Status badge shows RED, utilization > 100%, and the breach appears in the "Breach Investigation" expander below
- Status: ______

**UAT-08**
- Requirement/Feature: Near-breach (AMBER) is distinguishable from a real breach
- Scenario: Manager scans for early warnings, not just hard breaches
- Precondition: Stress Loss and CS01 limits are configured with an 80% warning threshold
- Steps: 1) Open Limits & Breach Investigation page. 2) Review all rows, not just RED ones.
- Expected Result: "Stress Loss (Combined Severe)" and "CS01 (Fixed Income Desk)" both show AMBER, visually distinct in color from both GREEN and RED
- Status: ______

**UAT-09**
- Requirement/Feature: Data quality controls are trustworthy before acting on a breach
- Scenario: Controls user is asked to confirm today's numbers are clean before the breach is escalated
- Precondition: EOD pipeline has run
- Steps: 1) Open Data Quality / Controls page. 2) Confirm "Controls Not Passing" tile.
- Expected Result: Tile reads 0 on a clean run; if non-zero, each failing control's row is expandable to show which records/risk factors are affected
- Status: ______

**UAT-10**
- Requirement/Feature: Reconciliation controls catch a genuine break
- Scenario: QA wants to confirm the P&L reconciliation control is not a rubber stamp
- Precondition: None (uses the demo injection path)
- Steps: 1) Run `python src/data_quality.py` from the terminal. 2) Read the "Demo dataset" results block.
- Expected Result: At least 6 of 7 row-level controls report FAIL/WARN on the injected demo data, while the same controls report PASS on the real portfolio block immediately below
- Status: ______

**UAT-11**
- Requirement/Feature: FRTB Explorer is clearly labeled non-regulatory
- Scenario: A reviewer unfamiliar with the project's scope opens the FRTB page
- Precondition: `frtb_mapping` table populated
- Steps: 1) Open FRTB Explorer page.
- Expected Result: A visible warning banner states this is an educational mapping only, with no capital calculation, before any data is shown
- Status: ______

**UAT-12**
- Requirement/Feature: FRTB risk class filtering works
- Scenario: Analyst wants to see only GIRR-classified rows
- Precondition: `frtb_mapping` table populated
- Steps: 1) Open FRTB Explorer. 2) Select "GIRR" from the risk class dropdown.
- Expected Result: Table shows only Govt Bond and Corp Bond rate-leg rows; no Equity/FX/Credit Spread rows appear
- Status: ______

**UAT-13**
- Requirement/Feature: API returns real data, not a stub
- Scenario: A future consumer team wants to verify the API before integrating
- Precondition: API running (`uvicorn src.api:app --port 8000`)
- Steps: 1) `curl http://localhost:8000/risk/summary`. 2) Compare `portfolio_value` to the dashboard's Executive Dashboard tile.
- Expected Result: Values match exactly (same underlying `risk_results`/`position_valuations` tables)
- Status: ______

**UAT-14**
- Requirement/Feature: API input validation rejects invalid parameters
- Scenario: A consumer accidentally sends an unsupported grouping
- Precondition: API running
- Steps: 1) `curl "http://localhost:8000/risk/sensitivities?group_by=currency"` (not a supported value).
- Expected Result: HTTP 422 response, not a 500 error or a silently wrong/empty result
- Status: ______

**UAT-15**
- Requirement/Feature: Position drilldown from a desk-level number
- Scenario: Manager sees Fixed Income Desk's high CS01 and wants to see which bonds drive it
- Precondition: Sensitivities persisted
- Steps: 1) Open Risk Explorer -> Position-Level tab. 2) Filter by desk = "Fixed Income Desk". 3) Sort/scan for the largest CS01 values.
- Expected Result: JPM-CB-10Y, JPM-CB-3Y, and JPM-CB-2Y (the deliberately concentrated positions) appear at or near the top
- Status: ______
