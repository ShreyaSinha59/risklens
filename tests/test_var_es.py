import pandas as pd
import pytest

from var_es import historical_var, historical_es, parametric_var

# the exact 20-observation toy example walked through by hand in Module 4
TOY_PNL = pd.Series([-4.5, -3.2, -2.8, -2.1, -1.9, -1.5, -1.2, -0.8, -0.5, -0.3,
                      0.1, 0.4, 0.6, 0.9, 1.1, 1.4, 1.8, 2.2, 2.9, 3.6])


@pytest.mark.unit
def test_historical_var_matches_hand_worked_example():
    assert historical_var(TOY_PNL, 0.95) == pytest.approx(4.5)


@pytest.mark.unit
def test_es_equals_var_when_tail_has_one_observation():
    # documents the known small-sample artifact from Module 4, not a bug
    assert historical_es(TOY_PNL, 0.95) == pytest.approx(historical_var(TOY_PNL, 0.95))


@pytest.mark.integration
def test_var_99_gte_var_95_on_real_scenarios(scenario_pnls):
    assert historical_var(scenario_pnls, 0.99) >= historical_var(scenario_pnls, 0.95)


@pytest.mark.integration
@pytest.mark.parametrize("confidence", [0.95, 0.99])
def test_expected_shortfall_gte_var_on_real_scenarios(scenario_pnls, confidence):
    # the property explicitly requested: ES >= VaR at matching confidence
    assert historical_es(scenario_pnls, confidence) >= historical_var(scenario_pnls, confidence)


@pytest.mark.integration
@pytest.mark.parametrize("confidence", [0.95, 0.99])
def test_parametric_var_is_positive(scenario_pnls, confidence):
    assert parametric_var(scenario_pnls, confidence) > 0
