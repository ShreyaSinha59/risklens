from pathlib import Path

import pandas as pd
import pytest

from valuation import price_equity, price_bond, black_scholes_price

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_price_equity_is_quantity_times_price():
    assert price_equity(1200, 328.21) == pytest.approx(1200 * 328.21)


@pytest.mark.unit
def test_price_bond_at_par_when_coupon_equals_yield():
    # matches the hand-worked Module 5 manual example exactly
    price = price_bond(1_000_000, 0.05, 2, 0.05)
    assert price == pytest.approx(1_000_000.00, abs=0.01)


@pytest.mark.unit
def test_price_bond_below_par_when_yield_above_coupon():
    price = price_bond(1_000_000, 0.04, 10, 0.05)
    assert price < 1_000_000


@pytest.mark.unit
@pytest.mark.parametrize("option_type", ["Call", "Put"])
def test_black_scholes_price_is_non_negative(option_type):
    price = black_scholes_price(spot=100, strike=100, years_to_expiry=1, risk_free_rate=0.04,
                                 volatility=0.2, option_type=option_type)
    assert price >= 0


@pytest.mark.unit
def test_call_price_never_exceeds_spot():
    # a call option can never be worth more than owning the stock outright
    price = black_scholes_price(spot=100, strike=1, years_to_expiry=1, risk_free_rate=0.04,
                                 volatility=0.2, option_type="Call")
    assert price <= 100


@pytest.mark.integration
def test_real_portfolio_valuation_matches_persisted_output(baseline_valued):
    persisted = pd.read_csv(ROOT / "data/processed/position_valuations.csv")
    fresh_total = baseline_valued["market_value_usd"].sum()
    persisted_total = persisted["market_value_usd"].sum()
    assert fresh_total == pytest.approx(persisted_total, abs=1.0)
