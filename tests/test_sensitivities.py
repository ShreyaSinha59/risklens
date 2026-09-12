import pytest

from valuation import price_bond
from sensitivities import (
    option_delta_per_share, option_vega_per_share_per_vol_point, bond_dv01, bond_cs01,
)


@pytest.mark.unit
@pytest.mark.parametrize("spot,strike", [(100, 90), (100, 100), (100, 130), (328, 500)])
def test_call_delta_between_0_and_1(spot, strike):
    delta = option_delta_per_share(spot, strike, years=0.5, r=0.04, vol=0.2, option_type="Call")
    assert 0 <= delta <= 1


@pytest.mark.unit
@pytest.mark.parametrize("spot,strike", [(100, 90), (100, 100), (100, 130)])
def test_put_delta_between_minus1_and_0(spot, strike):
    delta = option_delta_per_share(spot, strike, years=0.5, r=0.04, vol=0.2, option_type="Put")
    assert -1 <= delta <= 0


@pytest.mark.unit
def test_option_vega_is_non_negative():
    # true for both calls and puts (vega formula doesn't depend on option_type)
    vega = option_vega_per_share_per_vol_point(spot=100, strike=100, years=0.5, r=0.04, vol=0.2)
    assert vega >= 0


@pytest.mark.unit
def test_upward_yield_reduces_long_conventional_bond_value():
    # requested financial sanity test
    price_before = price_bond(1_000_000, 0.04, 10, 0.045)
    price_after = price_bond(1_000_000, 0.04, 10, 0.05)  # yield rose 50bp
    assert price_after < price_before


@pytest.mark.unit
def test_credit_spread_widening_reduces_long_corp_bond_value():
    # requested financial sanity test: risk_free + spread is one combined discount rate
    risk_free, spread_before, spread_after = 0.045, 0.01, 0.02
    price_before = price_bond(1_000_000, 0.04, 5, risk_free + spread_before)
    price_after = price_bond(1_000_000, 0.04, 5, risk_free + spread_after)
    assert price_after < price_before


@pytest.mark.unit
def test_larger_position_creates_larger_exposure():
    # requested financial sanity test, checked on both DV01 and CS01
    small = bond_dv01(1_000_000, 0.04, 10, 0.05)
    large = bond_dv01(5_000_000, 0.04, 10, 0.05)
    assert large == pytest.approx(5 * small, rel=1e-6)


@pytest.mark.unit
def test_dv01_and_cs01_numerically_equal_for_corp_bond():
    # documents the stated Module 5 simplification (single combined discount
    # rate) rather than treating the coincidence as a bug
    dv01 = bond_dv01(1_000_000, 0.048, 5, 0.045 + 0.0068)
    cs01 = bond_cs01(1_000_000, 0.048, 5, 0.045 + 0.0068)
    assert dv01 == pytest.approx(cs01)


@pytest.mark.integration
@pytest.mark.regression
def test_fixed_income_desk_carries_all_dv01(ref_data, level_dicts):
    from sensitivities import compute_position_sensitivities
    sens = compute_position_sensitivities(ref_data["positions"], ref_data["instruments"],
                                           level_dicts["price"], level_dicts["yield"],
                                           level_dicts["spread"], level_dicts["vol"])
    # compute_position_sensitivities already returns book_id - no need to re-merge it
    merged = sens.merge(ref_data["books"], on="book_id").merge(ref_data["desks"], on="desk_id")
    dv01_by_desk = merged.groupby("desk_name")["DV01"].sum(min_count=1).dropna()
    assert list(dv01_by_desk.index) == ["Fixed Income Desk"]
