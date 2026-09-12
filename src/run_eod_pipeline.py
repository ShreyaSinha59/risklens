"""
Module 9c: End-of-Day Pipeline Orchestration

Runs every prior module's functions in dependency order and persists the
results to PostgreSQL. Two failure policies: an exception in a structural
stage (Validation/Valuation/Sensitivities/VaR) HALTS the run - nothing
downstream can be trusted. A WARN/FAIL control or limit status does NOT
halt - it's recorded and persisted as a flag, so it's visible rather than
silently swallowed.
"""

import json
import os
import sys

import pandas as pd
import psycopg2
import psycopg2.extras

from build_portfolio import validate_portfolio
from valuation import (
    AS_OF_DATE, latest_levels_as_of, levels_dict, value_positions, portfolio_market_value,
)
from sensitivities import compute_position_sensitivities
from var_es import build_complete_scenario_dates, shock_levels, run_historical_scenarios, historical_var, historical_es, parametric_var, CONFIDENCE_LEVELS
from pnl_attribution import compute_explained_pnl
from stress_testing import load_scenarios, translate_shocks, run_stress_scenario
from risk_limits import compute_limit_utilization, load_limits
from data_quality import run_all_controls

# DATABASE_URL is set by the host (Render/Neon) in production; falls back to
# the local Postgres socket for local development.
DB_DSN = os.environ.get("DATABASE_URL", "host=/tmp port=5432 dbname=trading_book_risk")


class PipelineHalted(Exception):
    pass


def stage(name):
    print(f"\n--- STAGE: {name} ---")


def main():
    desks = pd.read_csv("data/desks.csv")
    books = pd.read_csv("data/books.csv")
    issuers = pd.read_csv("data/issuers.csv")
    instruments = pd.read_csv("data/instruments.csv")
    positions = pd.read_csv("data/positions.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")
    changes = pd.read_csv("data/processed/risk_factor_changes.csv")

    # STAGE 1: structural validation - halts on failure
    stage("Validation")
    errors = validate_portfolio(desks, books, issuers, instruments, positions)
    if errors:
        raise PipelineHalted(f"Validation failed, halting before any calculation: {errors}")
    print(f"OK: {len(positions)} positions structurally valid.")

    # STAGE 2: valuation
    stage("Valuation")
    latest = latest_levels_as_of(levels, AS_OF_DATE)
    price_levels, fx_levels = levels_dict(latest, "Equity Price"), levels_dict(latest, "FX Spot")
    yield_levels, spread_levels = levels_dict(latest, "Yield"), levels_dict(latest, "Credit Spread")
    vol_levels = levels_dict(latest, "Implied Vol (Realized Proxy)")
    valued = value_positions(positions, instruments, fx_levels, price_levels, yield_levels, spread_levels, vol_levels)
    baseline_value = portfolio_market_value(valued)
    print(f"OK: Portfolio value = ${baseline_value:,.2f}")

    # STAGE 3: sensitivities
    stage("Sensitivities")
    sens = compute_position_sensitivities(positions, instruments, price_levels, yield_levels, spread_levels, vol_levels)
    print(f"OK: sensitivities computed for {len(sens)} positions.")

    # STAGE 4: VaR / ES
    stage("VaR / ES")
    complete_changes = build_complete_scenario_dates(changes)
    pnl_series = run_historical_scenarios(positions, instruments, latest, complete_changes, baseline_value)
    risk_result_rows = []
    for c in CONFIDENCE_LEVELS:
        risk_result_rows.append(("Portfolio", "ALL", f"Historical VaR {int(c*100)}%", historical_var(pnl_series, c)))
        risk_result_rows.append(("Portfolio", "ALL", f"Historical ES {int(c*100)}%", historical_es(pnl_series, c)))
        risk_result_rows.append(("Portfolio", "ALL", f"Parametric VaR {int(c*100)}%", parametric_var(pnl_series, c)))
    print(f"OK: {len(risk_result_rows)} VaR/ES metrics computed.")

    # STAGE 5: P&L attribution
    stage("P&L Attribution")
    scenario_date = complete_changes.index[-1]
    changes_at_date = changes[changes["date"] == scenario_date].set_index("risk_factor_id")
    shocked = shock_levels(latest, complete_changes.loc[scenario_date])
    shocked_valued = value_positions(
        positions, instruments, levels_dict(shocked, "FX Spot"), levels_dict(shocked, "Equity Price"),
        levels_dict(shocked, "Yield"), levels_dict(shocked, "Credit Spread"),
        levels_dict(shocked, "Implied Vol (Realized Proxy)"))
    actual_pnl = portfolio_market_value(shocked_valued) - baseline_value
    explained = compute_explained_pnl(positions, instruments, sens, changes_at_date)
    explained_total = explained["Explained_PnL"].sum()
    pnl_attr = {
        "scenario_date": scenario_date, "actual_pnl": actual_pnl, "explained_pnl": explained_total,
        "residual_pnl": actual_pnl - explained_total,
        "equity_delta_pnl": explained["Equity_Delta_PnL"].sum(), "gamma_pnl": explained["Gamma_PnL"].sum(),
        "vega_pnl": explained["Vega_PnL"].sum(), "rates_pnl": explained["Rates_PnL"].sum(),
        "credit_pnl": explained["Credit_PnL"].sum(), "fx_pnl": explained["FX_PnL"].sum(),
    }
    print(f"OK: Actual ${actual_pnl:,.2f}, Explained ${explained_total:,.2f}")

    # STAGE 6: stress testing
    stage("Stress Testing")
    stress_rows = []
    for scenario in load_scenarios():
        type_shocks = translate_shocks(scenario["shocks"])
        stressed_valued = run_stress_scenario(positions, instruments, latest, type_shocks)
        merged = stressed_valued.set_index("position_id")["market_value_usd"] - valued.set_index("position_id")["market_value_usd"]
        for position_id, pnl in merged.items():
            stress_rows.append((scenario["name"], position_id, pnl))
    print(f"OK: {len(stress_rows)} position-level stress results across {len(load_scenarios())} scenarios.")

    # STAGE 7: limits (needs sensitivities/valuations already persisted logic reused from Module 7)
    stage("Limits")
    limits_summary = compute_limit_utilization(positions, instruments, levels)
    n_red = (limits_summary["status"] == "RED").sum()
    print(f"OK: {len(limits_summary)} limits evaluated, {n_red} RED.")
    if n_red:
        print(f"FLAGGED (not halted): {n_red} limit breach(es) - will be persisted for investigation.")

    # STAGE 8: controls - needs valuation/attribution already done (market-value & P&L recon)
    stage("Controls")
    controls = run_all_controls(positions, instruments, levels, changes, expected_count=len(positions))
    n_fail = (controls["status"] != "PASS").sum()
    print(f"OK: {len(controls)} controls run, {n_fail} not PASS.")
    if n_fail:
        print(f"FLAGGED (not halted): {n_fail} control(s) not clean - will be persisted for review.")

    # STAGE 9: persist everything in one transaction
    stage("Persist")
    persist_all(desks, books, issuers, instruments, positions, levels, valued, sens,
                risk_result_rows, pnl_attr, stress_rows, limits_summary, controls)
    print("OK: all results persisted to PostgreSQL (single transaction).")


def persist_all(desks, books, issuers, instruments, positions, levels, valued, sens,
                 risk_result_rows, pnl_attr, stress_rows, limits_summary, controls):
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                upsert_df(cur, "desks", desks, ["desk_id"])
                upsert_df(cur, "books", books, ["book_id"])
                upsert_df(cur, "issuers", issuers, ["issuer_id"])
                upsert_df(cur, "instruments", instruments, ["instrument_id"])
                upsert_df(cur, "positions", positions, ["position_id"])
                upsert_df(cur, "market_data", levels.rename(columns={"date": "as_of_date"}), ["as_of_date", "risk_factor_id"])

                val_out = valued[["position_id", "currency", "market_value_local", "market_value_usd"]].copy()
                val_out["as_of_date"] = AS_OF_DATE
                upsert_df(cur, "position_valuations", val_out, ["position_id"])

                sens_out = sens.rename(columns={"Delta": "delta", "Gamma": "gamma", "Vega": "vega",
                                                 "DV01": "dv01", "CS01": "cs01"})[
                    ["position_id", "delta", "gamma", "vega", "dv01", "cs01"]].copy()
                sens_out["as_of_date"] = AS_OF_DATE
                upsert_df(cur, "sensitivities", sens_out, ["position_id"])

                for scope_type, scope_value, metric, value in risk_result_rows:
                    upsert_row(cur, "risk_results", ["as_of_date", "scope_type", "scope_value", "metric"],
                               {"as_of_date": AS_OF_DATE, "scope_type": scope_type, "scope_value": scope_value,
                                "metric": metric, "value": float(value)})
                for row in limits_summary.itertuples():
                    upsert_row(cur, "risk_results", ["as_of_date", "scope_type", "scope_value", "metric"],
                               {"as_of_date": AS_OF_DATE, "scope_type": row.scope, "scope_value": row.scope_value,
                                "metric": row.metric, "value": float(row.actual_value)})

                upsert_row(cur, "pnl_attribution", ["as_of_date", "scenario_date"],
                           {"as_of_date": AS_OF_DATE, **{k: (v if not hasattr(v, "item") else float(v)) for k, v in pnl_attr.items()}})

                for scenario_name, position_id, pnl in stress_rows:
                    upsert_row(cur, "stress_results", ["as_of_date", "scenario_name", "position_id"],
                               {"as_of_date": AS_OF_DATE, "scenario_name": scenario_name,
                                "position_id": position_id, "stress_pnl": float(pnl)})

                for limit in load_limits():
                    limit = dict(limit)
                    limit["scope_type"] = limit.pop("scope")
                    upsert_row(cur, "risk_limits", ["limit_id"], limit)

                for row in controls.itertuples():
                    details = row.details if isinstance(row.details, (list, dict)) else str(row.details)
                    upsert_row(cur, "control_results", ["as_of_date", "control_name"],
                               {"as_of_date": AS_OF_DATE, "control_name": row.control, "status": row.status,
                                "severity": row.severity, "details": psycopg2.extras.Json(details)})
    finally:
        conn.close()


def upsert_df(cur, table, df, conflict_cols):
    for record in df.to_dict("records"):
        upsert_row(cur, table, conflict_cols, record)


def _sanitize(value):
    # pandas/numpy NaN must become Python None here, or psycopg2 sends it to
    # Postgres as the literal numeric 'NaN' (a real, non-null value in
    # Postgres' NUMERIC type) instead of SQL NULL - IS NOT NULL would then
    # silently fail to filter it out.
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def upsert_row(cur, table, conflict_cols, record):
    cols = list(record.keys())
    values = [_sanitize(record[c]) for c in cols]
    placeholders = ", ".join(["%s"] * len(cols))
    update_cols = [c for c in cols if c not in conflict_cols]
    sql = f'INSERT INTO {table} ({", ".join(cols)}) VALUES ({placeholders}) ' \
          f'ON CONFLICT ({", ".join(conflict_cols)}) DO UPDATE SET ' + \
          ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols) if update_cols else \
          f'INSERT INTO {table} ({", ".join(cols)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
    cur.execute(sql, values)


if __name__ == "__main__":
    try:
        main()
    except PipelineHalted as e:
        print(f"\nPIPELINE HALTED: {e}")
        sys.exit(1)
