"""
Module 4: Historical VaR, Expected Shortfall, and (scoped) Parametric VaR

Reuses Module 3's valuation functions unchanged - "full revaluation" means
every scenario re-runs price_equity/price_bond/black_scholes_price, not a
sensitivity/delta approximation. Only risk-factor LEVELS are shocked per
scenario; AS_OF_DATE (and therefore every option's time-to-maturity) is
held fixed at today, consistent with historical-simulation methodology.
"""

import math

import numpy as np
import pandas as pd

from valuation import (
    AS_OF_DATE, latest_levels_as_of, levels_dict, value_positions, portfolio_market_value,
)

CONFIDENCE_LEVELS = [0.95, 0.99]
Z_SCORES = {0.95: 1.645, 0.99: 2.326}  # one-tailed normal quantiles; hardcoded, no scipy dependency

CHANGE_APPLICATION = {  # exact inverse of build_market_data.py's change formulas
    "Equity Price": lambda base, chg: base * math.exp(chg),
    "FX Spot":      lambda base, chg: base * math.exp(chg),
    "Yield":            lambda base, chg: base + chg / 10_000,
    "Credit Spread":    lambda base, chg: base + chg / 10_000,
    "Implied Vol (Realized Proxy)": lambda base, chg: base + chg / 100,
}


# ---------------------------------------------------------------------------
# Build the scenario set: only dates where EVERY risk factor has a change
# (differing US/UK/DE/FX calendars mean some historical dates are incomplete -
# we drop those dates rather than inventing a value for the missing factor)
# ---------------------------------------------------------------------------
def build_complete_scenario_dates(changes):
    pivot = changes.pivot(index="date", columns="risk_factor_id", values="change")
    complete = pivot.dropna(axis=0, how="any")
    return complete


def shock_levels(latest, changes_row):
    """latest: DataFrame[risk_factor_id, risk_factor_type, value]. Returns a shocked copy."""
    shocked = latest.copy()
    shocked["change"] = shocked["risk_factor_id"].map(changes_row)
    def apply_row(r):
        return CHANGE_APPLICATION[r["risk_factor_type"]](r["value"], r["change"])
    shocked["value"] = shocked.apply(apply_row, axis=1)
    return shocked[["risk_factor_id", "risk_factor_type", "value"]]


def run_historical_scenarios(positions, instruments, latest, complete_changes, baseline_value):
    scenario_pnls = {}
    for scenario_date, changes_row in complete_changes.iterrows():
        shocked = shock_levels(latest, changes_row)
        price_levels = levels_dict(shocked, "Equity Price")
        fx_levels = levels_dict(shocked, "FX Spot")
        yield_levels = levels_dict(shocked, "Yield")
        spread_levels = levels_dict(shocked, "Credit Spread")
        vol_levels = levels_dict(shocked, "Implied Vol (Realized Proxy)")

        valued = value_positions(positions, instruments, fx_levels, price_levels,
                                  yield_levels, spread_levels, vol_levels, as_of_date=AS_OF_DATE)
        scenario_value = portfolio_market_value(valued)
        scenario_pnls[scenario_date] = scenario_value - baseline_value

    return pd.Series(scenario_pnls).sort_index()


# ---------------------------------------------------------------------------
# Historical VaR / ES: order-statistic method (no interpolation)
# ---------------------------------------------------------------------------
def historical_var(pnl_series, confidence):
    n = len(pnl_series)
    k = math.ceil(round((1 - confidence) * n, 8))  # round first: float noise can push an exact integer boundary (e.g. 0.05*20) just over
    sorted_pnl = pnl_series.sort_values()
    return -sorted_pnl.iloc[k - 1]


def historical_es(pnl_series, confidence):
    n = len(pnl_series)
    k = math.ceil(round((1 - confidence) * n, 8))  # round first: float noise can push an exact integer boundary (e.g. 0.05*20) just over
    sorted_pnl = pnl_series.sort_values()
    return -sorted_pnl.iloc[:k].mean()


# ---------------------------------------------------------------------------
# Parametric VaR: normal fit to the SAME scenario P&L series (see Part C)
# ---------------------------------------------------------------------------
def parametric_var(pnl_series, confidence):
    mean = pnl_series.mean()
    std = pnl_series.std(ddof=1)
    return Z_SCORES[confidence] * std - mean


if __name__ == "__main__":
    desks = pd.read_csv("data/desks.csv")
    books = pd.read_csv("data/books.csv")
    issuers = pd.read_csv("data/issuers.csv")
    instruments = pd.read_csv("data/instruments.csv")
    positions = pd.read_csv("data/positions.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")
    changes = pd.read_csv("data/processed/risk_factor_changes.csv")

    latest = latest_levels_as_of(levels, AS_OF_DATE)
    baseline_valued = value_positions(
        positions, instruments,
        levels_dict(latest, "FX Spot"), levels_dict(latest, "Equity Price"),
        levels_dict(latest, "Yield"), levels_dict(latest, "Credit Spread"),
        levels_dict(latest, "Implied Vol (Realized Proxy)"),
    )
    baseline_value = portfolio_market_value(baseline_valued)

    complete_changes = build_complete_scenario_dates(changes)
    n_total_dates = changes["date"].nunique()
    print(f"Scenario dates: {len(complete_changes)} usable out of {n_total_dates} historical dates "
          f"({n_total_dates - len(complete_changes)} dropped for an incomplete risk-factor set that day)\n")

    pnl_series = run_historical_scenarios(positions, instruments, latest, complete_changes, baseline_value)
    pnl_series.to_csv("data/processed/scenario_pnls.csv", header=["pnl"])

    results = {}
    for c in CONFIDENCE_LEVELS:
        results[f"Historical VaR {int(c*100)}%"] = historical_var(pnl_series, c)
        results[f"Historical ES {int(c*100)}%"] = historical_es(pnl_series, c)
        results[f"Parametric VaR {int(c*100)}%"] = parametric_var(pnl_series, c)

    # --- sanity checks ---
    for c in CONFIDENCE_LEVELS:
        assert historical_es(pnl_series, c) >= historical_var(pnl_series, c) - 1e-6, \
            f"ES must be >= VaR at {c}"
    assert historical_var(pnl_series, 0.99) >= historical_var(pnl_series, 0.95) - 1e-6, \
        "99% VaR must be >= 95% VaR"
    print("Sanity checks passed: ES >= VaR at each confidence; VaR(99%) >= VaR(95%).\n")

    print(f"Baseline Portfolio Value: ${baseline_value:,.2f}\n")
    print("=== VaR / ES Comparison (1-day) ===")
    for label, value in results.items():
        print(f"{label:<22}: ${value:,.2f}")

    worst = pnl_series.sort_values().iloc[0]
    worst_date = pnl_series.sort_values().index[0]
    print(f"\nWorst single historical scenario: {worst_date}, P&L = ${worst:,.2f}")
