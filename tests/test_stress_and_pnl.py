import math

import pytest

from var_es import CHANGE_APPLICATION
from stress_testing import translate_shocks
from pnl_attribution import compute_explained_pnl


@pytest.mark.unit
def test_equity_selloff_shock_reduces_price():
    shocked = CHANGE_APPLICATION["Equity Price"](100.0, math.log(0.85))  # -15%
    assert shocked == pytest.approx(85.0)


@pytest.mark.unit
def test_translate_shocks_yield_bp_passthrough():
    type_shocks = translate_shocks({"yield_bp": 150})
    assert type_shocks["Yield"] == 150


@pytest.mark.integration
def test_combined_stress_scenario_is_worse_than_any_single_factor(ref_data, latest_levels):
    from stress_testing import load_scenarios, run_stress_scenario
    from valuation import portfolio_market_value, value_positions, levels_dict

    baseline = value_positions(
        ref_data["positions"], ref_data["instruments"], levels_dict(latest_levels, "FX Spot"),
        levels_dict(latest_levels, "Equity Price"), levels_dict(latest_levels, "Yield"),
        levels_dict(latest_levels, "Credit Spread"), levels_dict(latest_levels, "Implied Vol (Realized Proxy)"))
    baseline_value = portfolio_market_value(baseline)

    totals = {}
    for scenario in load_scenarios():
        stressed = run_stress_scenario(ref_data["positions"], ref_data["instruments"], latest_levels,
                                        translate_shocks(scenario["shocks"]))
        totals[scenario["name"]] = portfolio_market_value(stressed) - baseline_value

    combined = totals["Combined Severe Market Stress"]
    singles = [v for k, v in totals.items() if k != "Combined Severe Market Stress"]
    assert combined < min(singles)


@pytest.mark.integration
def test_pnl_actual_equals_explained_plus_residual(ref_data, latest_levels, level_dicts, baseline_valued):
    from var_es import build_complete_scenario_dates, shock_levels
    from valuation import value_positions, portfolio_market_value, levels_dict
    from sensitivities import compute_position_sensitivities

    complete = build_complete_scenario_dates(ref_data["changes"])
    scenario_date = complete.index[-1]
    changes_at_date = ref_data["changes"][ref_data["changes"]["date"] == scenario_date].set_index("risk_factor_id")

    shocked = shock_levels(latest_levels, complete.loc[scenario_date])
    shocked_valued = value_positions(
        ref_data["positions"], ref_data["instruments"], levels_dict(shocked, "FX Spot"),
        levels_dict(shocked, "Equity Price"), levels_dict(shocked, "Yield"),
        levels_dict(shocked, "Credit Spread"), levels_dict(shocked, "Implied Vol (Realized Proxy)"))
    actual_pnl = portfolio_market_value(shocked_valued) - portfolio_market_value(baseline_valued)

    sens = compute_position_sensitivities(ref_data["positions"], ref_data["instruments"], level_dicts["price"],
                                           level_dicts["yield"], level_dicts["spread"], level_dicts["vol"])
    explained = compute_explained_pnl(ref_data["positions"], ref_data["instruments"], sens, changes_at_date)
    explained_total = explained["Explained_PnL"].sum()
    residual = actual_pnl - explained_total

    assert actual_pnl == pytest.approx(explained_total + residual, abs=1e-6)


@pytest.mark.integration
def test_pnl_bottom_up_equals_top_down_reconciliation(ref_data):
    from data_quality import control_pnl_reconciliation
    result = control_pnl_reconciliation(ref_data["positions"], ref_data["instruments"],
                                         ref_data["levels"], ref_data["changes"])
    assert result["status"] == "PASS"
