"""
Module 6b: Stress Testing

Scenarios live in config/stress_scenarios.json (human-readable units), not
hardcoded here. The shock mechanism reuses Module 4's CHANGE_APPLICATION -
a stress test is just one more hand-picked scenario through the same
full-revaluation engine used for Historical VaR.
"""

import json
import math

import pandas as pd

from valuation import (
    AS_OF_DATE, latest_levels_as_of, levels_dict, value_positions, portfolio_market_value,
)
from var_es import CHANGE_APPLICATION

CONFIG_PATH = "config/stress_scenarios.json"

# maps a config key (human units) to (risk_factor_type, converter to internal units)
SHOCK_KEY_MAP = {
    "equity_pct": ("Equity Price", lambda pct: math.log(1 + pct / 100)),
    "yield_bp": ("Yield", lambda bp: bp),
    "credit_spread_bp": ("Credit Spread", lambda bp: bp),
    "vol_points": ("Implied Vol (Realized Proxy)", lambda pts: pts),
}

EXPECTED_DIRECTION = {
    "Equity Selloff": "Book is net long equities + option delta -> expect a LOSS.",
    "Rapid Rate Increase": "Book carries positive net DV01 (long duration) throughout -> expect a LOSS.",
    "Credit Spread Widening": "All corp bond positions are long, incl. the deliberate JPM concentration -> expect a sizeable LOSS.",
    "Combined Severe Market Stress": "All of the above stack together (FX not shocked, out of scope) -> expect the LARGEST loss.",
}


def load_scenarios(path=CONFIG_PATH):
    with open(path) as f:
        return json.load(f)


def translate_shocks(shocks_config):
    type_shocks = {}
    for key, value in shocks_config.items():
        rf_type, convert = SHOCK_KEY_MAP[key]
        type_shocks[rf_type] = convert(value)
    return type_shocks


def shock_levels_by_type(latest, type_shocks):
    shocked = latest.copy()
    def apply_row(r):
        if r["risk_factor_type"] in type_shocks:
            return CHANGE_APPLICATION[r["risk_factor_type"]](r["value"], type_shocks[r["risk_factor_type"]])
        return r["value"]
    shocked["value"] = shocked.apply(apply_row, axis=1)
    return shocked[["risk_factor_id", "risk_factor_type", "value"]]


def run_stress_scenario(positions, instruments, latest, type_shocks):
    shocked = shock_levels_by_type(latest, type_shocks)
    valued = value_positions(
        positions, instruments, levels_dict(shocked, "FX Spot"), levels_dict(shocked, "Equity Price"),
        levels_dict(shocked, "Yield"), levels_dict(shocked, "Credit Spread"),
        levels_dict(shocked, "Implied Vol (Realized Proxy)"), as_of_date=AS_OF_DATE,
    )
    return valued


if __name__ == "__main__":
    desks = pd.read_csv("data/desks.csv")
    books = pd.read_csv("data/books.csv")
    instruments = pd.read_csv("data/instruments.csv")
    positions = pd.read_csv("data/positions.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")

    latest = latest_levels_as_of(levels, AS_OF_DATE)
    baseline_valued = value_positions(
        positions, instruments, levels_dict(latest, "FX Spot"), levels_dict(latest, "Equity Price"),
        levels_dict(latest, "Yield"), levels_dict(latest, "Credit Spread"),
        levels_dict(latest, "Implied Vol (Realized Proxy)"),
    )
    baseline_value = portfolio_market_value(baseline_valued)
    baseline_by_pos = baseline_valued.set_index("position_id")

    scenarios = load_scenarios()
    scenario_results = {}

    for scenario in scenarios:
        name = scenario["name"]
        print(f"=== {name} ===")
        print(scenario["description"])
        print(f"Expected direction: {EXPECTED_DIRECTION[name]}\n")

        type_shocks = translate_shocks(scenario["shocks"])
        stressed_valued = run_stress_scenario(positions, instruments, latest, type_shocks)
        stressed_value = portfolio_market_value(stressed_valued)
        stress_pnl_total = stressed_value - baseline_value

        merged = stressed_valued.merge(
            baseline_by_pos[["market_value_usd"]], on="position_id", suffixes=("_stressed", "_base"))
        merged["stress_pnl"] = merged["market_value_usd_stressed"] - merged["market_value_usd_base"]
        merged = merged.merge(positions[["position_id", "book_id"]].drop_duplicates(),
                               on="position_id", suffixes=("", "_pos")) \
                        .merge(books, on="book_id").merge(desks, on="desk_id")
        scenario_results[name] = merged

        print(f"Base Portfolio Value    : ${baseline_value:,.2f}")
        print(f"Stressed Portfolio Value: ${stressed_value:,.2f}")
        print(f"Stress P&L              : ${stress_pnl_total:,.2f}\n")

        print("Stress loss by asset class:")
        print(merged.groupby("asset_class")["stress_pnl"].sum().round(0).to_string())
        print("\nStress loss by desk:")
        print(merged.groupby("desk_name")["stress_pnl"].sum().round(0).to_string())
        print("\nTop 5 contributors:")
        print(merged.reindex(merged["stress_pnl"].abs().sort_values(ascending=False).index)
              [["instrument_id", "book_id", "stress_pnl"]].head(5).to_string(index=False))
        print("\n" + "-" * 60 + "\n")

    # --- sanity checks ---
    eq_selloff = scenario_results["Equity Selloff"]
    eq_pnl = eq_selloff[eq_selloff["asset_class"].isin(["Equity", "Equity Option"])]["stress_pnl"].sum()
    assert eq_pnl < 0, "Equity Selloff should produce a loss given our net long equity book"

    rate_shock = scenario_results["Rapid Rate Increase"]
    bond_pnl = rate_shock[rate_shock["asset_class"].isin(["Govt Bond", "Corp Bond"])]["stress_pnl"].sum()
    assert bond_pnl < 0, "Rapid Rate Increase should produce a loss given positive net DV01"

    totals = {name: df["stress_pnl"].sum() for name, df in scenario_results.items()}
    assert totals["Combined Severe Market Stress"] < min(
        totals["Equity Selloff"], totals["Rapid Rate Increase"], totals["Credit Spread Widening"]), \
        "Combined stress should be worse than any single-factor scenario"

    print("Sanity checks passed:")
    print(" - Equity Selloff produced a loss on equity/option positions, as predicted.")
    print(" - Rapid Rate Increase produced a loss on bond positions, as predicted.")
    print(" - Combined scenario loss exceeds every single-factor scenario loss.")
