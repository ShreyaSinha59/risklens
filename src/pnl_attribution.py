"""
Module 6a: P&L Attribution

Actual P&L (full revaluation, reusing Module 4's scenario engine for the
single most recent historical date) vs. Explained P&L (Module 5's
sensitivities x Module 2's actual observed risk-factor changes on that same
date). Residual = Actual - Explained.

Sign convention (stated explicitly, see accompanying explanation): Delta/
Gamma/Vega are direct dV/dx, so P&L = +sensitivity x change. DV01/CS01 were
defined in Module 5 as "loss per 1bp rise", so their P&L needs a sign flip:
P&L = -DV01 x change_bp. FX Delta is computed fresh here (Module 5 excluded
FX) using the same quantity-if-quote-is-USD-else-0 logic as Module 3's
price_fx.
"""

import pandas as pd

from valuation import (
    AS_OF_DATE, latest_levels_as_of, levels_dict, value_positions,
    portfolio_market_value, nearest_tenor_risk_factor,
)
from var_es import build_complete_scenario_dates, shock_levels
from sensitivities import compute_position_sensitivities


def compute_explained_pnl(positions, instruments, sens, changes_at_date):
    inst_by_id = instruments.set_index("instrument_id").to_dict("index")
    sens_by_pos = sens.set_index("position_id").to_dict("index")
    rows = []

    for pos in positions.itertuples():
        inst = inst_by_id[pos.instrument_id]
        s = sens_by_pos[pos.position_id]
        asset_class = inst["asset_class"]
        row = {"position_id": pos.position_id, "Equity_Delta_PnL": 0.0, "Gamma_PnL": 0.0,
               "Vega_PnL": 0.0, "Rates_PnL": 0.0, "Credit_PnL": 0.0, "FX_PnL": 0.0}

        if asset_class == "Equity":
            d_s = changes_at_date.loc[pos.instrument_id, "current_value"] - \
                  changes_at_date.loc[pos.instrument_id, "previous_value"]
            row["Equity_Delta_PnL"] = s["Delta"] * d_s

        elif asset_class == "Equity Option":
            underlying_id = inst["underlying_instrument_id"]
            d_s = changes_at_date.loc[underlying_id, "current_value"] - \
                  changes_at_date.loc[underlying_id, "previous_value"]
            row["Equity_Delta_PnL"] = s["Delta"] * d_s
            row["Gamma_PnL"] = 0.5 * s["Gamma"] * d_s ** 2
            vol_rf = f"{underlying_id.replace('-EQ', '')}-VOL"
            if vol_rf in changes_at_date.index:
                d_vol_pts = changes_at_date.loc[vol_rf, "change"]
                row["Vega_PnL"] = s["Vega"] * d_vol_pts

        elif asset_class == "Govt Bond":
            years = (pd.Timestamp(inst["maturity_date"]).date() - AS_OF_DATE).days / 365.25
            rf_id = nearest_tenor_risk_factor(inst["currency"], years)
            d_y_bp = changes_at_date.loc[rf_id, "change"]
            row["Rates_PnL"] = -s["DV01"] * d_y_bp

        elif asset_class == "Corp Bond":
            years = (pd.Timestamp(inst["maturity_date"]).date() - AS_OF_DATE).days / 365.25
            rf_id = nearest_tenor_risk_factor("USD", years)
            d_y_bp = changes_at_date.loc[rf_id, "change"]
            row["Rates_PnL"] = -s["DV01"] * d_y_bp
            spread_rf = f"{inst['issuer_id']}-CS"
            d_spread_bp = changes_at_date.loc[spread_rf, "change"]
            row["Credit_PnL"] = -s["CS01"] * d_spread_bp

        elif asset_class == "FX":
            if inst["quote_currency"] == "USD" and pos.instrument_id in changes_at_date.index:
                d_rate = changes_at_date.loc[pos.instrument_id, "current_value"] - \
                         changes_at_date.loc[pos.instrument_id, "previous_value"]
                row["FX_PnL"] = pos.quantity * d_rate
            # base_currency == "USD" pairs: FX_PnL stays 0 - USD value is rate-invariant
            # by construction in our model (see Module 3's price_fx), not a residual source.

        rows.append(row)

    explained = pd.DataFrame(rows)
    explained["Explained_PnL"] = explained[
        ["Equity_Delta_PnL", "Gamma_PnL", "Vega_PnL", "Rates_PnL", "Credit_PnL", "FX_PnL"]
    ].sum(axis=1)
    return explained


if __name__ == "__main__":
    instruments = pd.read_csv("data/instruments.csv")
    positions = pd.read_csv("data/positions.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")
    changes = pd.read_csv("data/processed/risk_factor_changes.csv")

    latest = latest_levels_as_of(levels, AS_OF_DATE)
    price_levels = levels_dict(latest, "Equity Price")
    fx_levels = levels_dict(latest, "FX Spot")
    yield_levels = levels_dict(latest, "Yield")
    spread_levels = levels_dict(latest, "Credit Spread")
    vol_levels = levels_dict(latest, "Implied Vol (Realized Proxy)")

    baseline_valued = value_positions(positions, instruments, fx_levels, price_levels,
                                       yield_levels, spread_levels, vol_levels)
    baseline_value = portfolio_market_value(baseline_valued)

    sens = compute_position_sensitivities(positions, instruments, price_levels,
                                           yield_levels, spread_levels, vol_levels)

    complete = build_complete_scenario_dates(changes)
    scenario_date = complete.index[-1]
    changes_row = complete.loc[scenario_date]
    changes_at_date = changes[changes["date"] == scenario_date].set_index("risk_factor_id")

    shocked = shock_levels(latest, changes_row)
    shocked_valued = value_positions(
        positions, instruments, levels_dict(shocked, "FX Spot"), levels_dict(shocked, "Equity Price"),
        levels_dict(shocked, "Yield"), levels_dict(shocked, "Credit Spread"),
        levels_dict(shocked, "Implied Vol (Realized Proxy)"),
    )
    shocked_value = portfolio_market_value(shocked_valued)
    actual_pnl_total = shocked_value - baseline_value

    explained = compute_explained_pnl(positions, instruments, sens, changes_at_date)
    explained_pnl_total = explained["Explained_PnL"].sum()
    residual_total = actual_pnl_total - explained_pnl_total

    # --- sanity checks ---
    assert abs(actual_pnl_total - (explained_pnl_total + residual_total)) < 1e-6, \
        "Actual must equal Explained + Residual by construction"
    explained_pct = 100 * explained_pnl_total / actual_pnl_total if actual_pnl_total != 0 else float("nan")
    assert -50 <= explained_pct <= 150, f"Explained %% looks implausible: {explained_pct:.1f}%% - check for a unit/sign bug"
    print("Sanity checks passed: Actual = Explained + Residual; Explained %% within a plausible range.\n")

    print(f"Attribution date: {scenario_date} (most recent complete historical scenario)\n")
    print(f"Actual P&L      : ${actual_pnl_total:,.2f}")
    print("\n--- Explained P&L by factor ---")
    for col, label in [("Equity_Delta_PnL", "Equity/Delta"), ("Gamma_PnL", "Gamma"),
                        ("Vega_PnL", "Vega"), ("Rates_PnL", "Rates/DV01"),
                        ("Credit_PnL", "Credit/CS01"), ("FX_PnL", "FX")]:
        print(f"{label:<14}: ${explained[col].sum():,.2f}")
    print(f"{'Total Explained':<14}: ${explained_pnl_total:,.2f}")
    print(f"\nResidual        : ${residual_total:,.2f}")
    print(f"Explained %     : {explained_pct:.1f}%")
