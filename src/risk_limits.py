"""
Module 7a: Risk Limits

Limits live in config/risk_limits.json (human-editable), not hardcoded here.
Actuals are pulled by re-using prior modules' saved outputs (scenario_pnls,
position_sensitivities, position_valuations) rather than recomputing from
scratch, except the stress scenario, which has no persisted total yet.
"""

import json

import pandas as pd

from valuation import AS_OF_DATE, latest_levels_as_of, levels_dict, value_positions
from var_es import historical_var
from stress_testing import load_scenarios, translate_shocks, run_stress_scenario

CONFIG_PATH = "config/risk_limits.json"


def load_limits(path=CONFIG_PATH):
    with open(path) as f:
        return json.load(f)


def classify_status(utilization, warning_pct):
    if utilization >= 1.0:
        return "RED"
    if utilization >= warning_pct:
        return "AMBER"
    return "GREEN"


def get_actual_value(limit, positions, instruments, levels):
    metric, scope, scope_value = limit["metric"], limit["scope"], limit["scope_value"]

    if metric == "99% VaR":
        pnl_series = pd.read_csv("data/processed/scenario_pnls.csv", index_col=0)["pnl"]
        return historical_var(pnl_series, 0.99)

    if metric == "Stress Loss (Combined Severe)":
        latest = latest_levels_as_of(levels, AS_OF_DATE)
        scenario = next(s for s in load_scenarios() if s["name"] == "Combined Severe Market Stress")
        type_shocks = translate_shocks(scenario["shocks"])
        baseline_valued = value_positions(
            positions, instruments, levels_dict(latest, "FX Spot"), levels_dict(latest, "Equity Price"),
            levels_dict(latest, "Yield"), levels_dict(latest, "Credit Spread"),
            levels_dict(latest, "Implied Vol (Realized Proxy)"))
        stressed_valued = run_stress_scenario(positions, instruments, latest, type_shocks)
        return -(stressed_valued["market_value_usd"].sum() - baseline_valued["market_value_usd"].sum())

    if metric in ("DV01", "CS01") and scope == "Desk":
        sens = pd.read_csv("data/processed/position_sensitivities.csv")
        return sens.loc[sens["desk_name"] == scope_value, metric].sum()

    if metric == "Issuer Concentration (Gross Exposure)" and scope == "Issuer":
        valuations = pd.read_csv("data/processed/position_valuations.csv")
        issuers = pd.read_csv("data/issuers.csv")
        merged = valuations.dropna(subset=["issuer_id"]).merge(issuers, on="issuer_id")
        return merged.loc[merged["issuer_name"] == scope_value, "market_value_usd"].abs().sum()

    raise ValueError(f"Unhandled limit definition: {limit}")


def compute_limit_utilization(positions, instruments, levels):
    rows = []
    for limit in load_limits():
        actual = get_actual_value(limit, positions, instruments, levels)
        utilization = actual / limit["limit_value"]
        rows.append({
            "limit_id": limit["limit_id"], "metric": limit["metric"], "scope": limit["scope"],
            "scope_value": limit["scope_value"], "limit_value": limit["limit_value"],
            "actual_value": actual, "utilization_pct": utilization * 100,
            "status": classify_status(utilization, limit["warning_pct"]),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    positions = pd.read_csv("data/positions.csv")
    instruments = pd.read_csv("data/instruments.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")

    summary = compute_limit_utilization(positions, instruments, levels)
    summary.to_csv("data/processed/risk_limit_summary.csv", index=False)

    pd.set_option("display.width", 120)
    print("=== Risk Limit Summary ===")
    for row in summary.itertuples():
        print(f"[{row.status:<5}] {row.metric:<38} ({row.scope}: {row.scope_value:<22}) "
              f"${row.actual_value:>14,.0f} / ${row.limit_value:>13,.0f}  ({row.utilization_pct:5.1f}%)")

    breaches = summary[summary["status"] == "RED"]
    assert len(breaches) >= 1, "Expected at least one deliberately configured breach"
    print(f"\n{len(breaches)} RED breach(es), {len(summary[summary.status=='AMBER'])} AMBER warning(s).")
