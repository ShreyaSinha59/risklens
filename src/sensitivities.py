"""
Module 5: Risk Sensitivities (Delta, Gamma, Vega, DV01, CS01)

Convention used throughout: every sensitivity is "$ P&L per one unit of that
risk factor's move" - Delta per $1 spot move, Vega per 1 vol point, DV01/CS01
per 1bp. Options' Greeks are analytic (closed-form, from Black-Scholes);
bonds' DV01/CS01 are bump-and-reprice against the same price_bond DCF used
in Module 3/4, consistent with this project's full-revaluation approach.

Simplification stated explicitly: our bond discount rate is a single summed
number (risk_free + spread for corp bonds). Bumping either component by 1bp
therefore produces an identical price impact, so DV01 and CS01 come out
numerically equal for a given corp bond here - in reality they can diverge
because the two curves don't always move in parallel. Option Rho (rate
sensitivity) is not computed - out of this module's requested scope.
"""

import math

import numpy as np
import pandas as pd

from valuation import (
    AS_OF_DATE, YIELD_CURVES, latest_levels_as_of, levels_dict,
    nearest_tenor_risk_factor, price_bond, compute_d1, norm_cdf, norm_pdf,
)

BP = 0.0001


# ---------------------------------------------------------------------------
# Equity / Option Greeks (analytic)
# ---------------------------------------------------------------------------
def option_delta_per_share(spot, strike, years, r, vol, option_type):
    d1 = compute_d1(spot, strike, years, r, vol)
    return norm_cdf(d1) if option_type == "Call" else norm_cdf(d1) - 1


def option_gamma_per_share(spot, strike, years, r, vol):
    d1 = compute_d1(spot, strike, years, r, vol)
    return norm_pdf(d1) / (spot * vol * math.sqrt(years))


def option_vega_per_share_per_vol_point(spot, strike, years, r, vol):
    d1 = compute_d1(spot, strike, years, r, vol)
    return spot * norm_pdf(d1) * math.sqrt(years) * 0.01  # per 1 vol point (0.01 in decimal terms)


# ---------------------------------------------------------------------------
# Bond DV01 / CS01 (bump-and-reprice against Module 3's price_bond)
# ---------------------------------------------------------------------------
def bond_dv01(face_value, coupon_rate, years, discount_rate):
    base = price_bond(face_value, coupon_rate, years, discount_rate)
    bumped = price_bond(face_value, coupon_rate, years, discount_rate + BP)
    return base - bumped  # positive = loses value when rates rise, for a long position


def bond_duration(face_value, coupon_rate, years, discount_rate):
    price = price_bond(face_value, coupon_rate, years, discount_rate)
    if price == 0:
        return np.nan
    return bond_dv01(face_value, coupon_rate, years, discount_rate) / (price * BP)


# CS01 uses the same bump mechanism as DV01 (see module docstring on why they
# come out numerically equal in this simplified single-discount-rate model)
def bond_cs01(face_value, coupon_rate, years, discount_rate):
    return bond_dv01(face_value, coupon_rate, years, discount_rate)


# ---------------------------------------------------------------------------
# Position-level sensitivities: only populate metrics applicable to the asset class
# ---------------------------------------------------------------------------
def compute_position_sensitivities(positions, instruments, price_levels, yield_levels,
                                    spread_levels, vol_levels, as_of_date=AS_OF_DATE):
    inst_by_id = instruments.set_index("instrument_id").to_dict("index")
    rows = []

    for pos in positions.itertuples():
        inst = inst_by_id[pos.instrument_id]
        asset_class = inst["asset_class"]
        quantity = pos.quantity
        row = {"position_id": pos.position_id, "book_id": pos.book_id, "instrument_id": pos.instrument_id,
               "asset_class": asset_class, "Delta": np.nan, "Gamma": np.nan, "Vega": np.nan,
               "DV01": np.nan, "CS01": np.nan}

        if asset_class == "Equity":
            row["Delta"] = quantity  # dV/dS = quantity, since V = quantity x S

        elif asset_class == "Equity Option":
            underlying_id = inst["underlying_instrument_id"]
            spot = price_levels[underlying_id]
            years = (pd.Timestamp(inst["maturity_date"]).date() - as_of_date).days / 365.25
            r = yield_levels[nearest_tenor_risk_factor("USD", years)]
            vol = vol_levels[f"{underlying_id.replace('-EQ', '')}-VOL"]
            mult = quantity * inst["contract_multiplier"]
            row["Delta"] = mult * option_delta_per_share(spot, inst["strike_price"], years, r, vol, inst["option_type"])
            row["Gamma"] = mult * option_gamma_per_share(spot, inst["strike_price"], years, r, vol)
            row["Vega"] = mult * option_vega_per_share_per_vol_point(spot, inst["strike_price"], years, r, vol)

        elif asset_class == "Govt Bond":
            years = (pd.Timestamp(inst["maturity_date"]).date() - as_of_date).days / 365.25
            rf_id = nearest_tenor_risk_factor(inst["currency"], years)
            discount_rate = yield_levels[rf_id]
            row["DV01"] = bond_dv01(quantity, inst["coupon_rate"], years, discount_rate)

        elif asset_class == "Corp Bond":
            years = (pd.Timestamp(inst["maturity_date"]).date() - as_of_date).days / 365.25
            rf_id = nearest_tenor_risk_factor("USD", years)
            risk_free = yield_levels[rf_id]
            spread = spread_levels[f"{inst['issuer_id']}-CS"]
            discount_rate = risk_free + spread
            row["DV01"] = bond_dv01(quantity, inst["coupon_rate"], years, discount_rate)
            row["CS01"] = bond_cs01(quantity, inst["coupon_rate"], years, discount_rate)

        # FX: no metrics in this module - out of the requested scope (Sections 1-3 only)

        rows.append(row)

    return pd.DataFrame(rows)


def aggregate_sensitivities(sens, group_col):
    metrics = ["Delta", "Gamma", "Vega", "DV01", "CS01"]
    return sens.groupby(group_col)[metrics].sum(min_count=1)


if __name__ == "__main__":
    desks = pd.read_csv("data/desks.csv")
    books = pd.read_csv("data/books.csv")
    instruments = pd.read_csv("data/instruments.csv")
    positions = pd.read_csv("data/positions.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")

    latest = latest_levels_as_of(levels, AS_OF_DATE)
    price_levels = levels_dict(latest, "Equity Price")
    yield_levels = levels_dict(latest, "Yield")
    spread_levels = levels_dict(latest, "Credit Spread")
    vol_levels = levels_dict(latest, "Implied Vol (Realized Proxy)")

    sens = compute_position_sensitivities(positions, instruments, price_levels,
                                           yield_levels, spread_levels, vol_levels)
    sens_full = sens.merge(positions[["position_id", "book_id"]].drop_duplicates(), on=["position_id", "book_id"]) \
                     .merge(books, on="book_id").merge(desks, on="desk_id")
    sens_full.to_csv("data/processed/position_sensitivities.csv", index=False)

    # --- sanity checks ---
    opt_rows = sens[sens["asset_class"] == "Equity Option"].merge(
        positions[["position_id", "quantity"]], on="position_id")
    opt_inst = instruments.set_index("instrument_id")
    for r in opt_rows.itertuples():
        inst = opt_inst.loc[r.instrument_id]
        mult = r.quantity * inst["contract_multiplier"]
        per_share_delta = r.Delta / mult
        if inst["option_type"] == "Call":
            assert 0 <= per_share_delta <= 1, f"Call delta out of [0,1] for {r.instrument_id}"
        else:
            assert -1 <= per_share_delta <= 0, f"Put delta out of [-1,0] for {r.instrument_id}"
    print("Sanity check 1 passed: all per-share call deltas in [0,1], put deltas in [-1,0].")

    govt = sens[sens["asset_class"] == "Govt Bond"].merge(positions[["position_id", "quantity"]], on="position_id")
    assert ((govt["quantity"] > 0) == (govt["DV01"] > 0)).all(), \
        "A long govt bond should have positive DV01 (loses value when yields rise)"
    print("Sanity check 2 passed: DV01 sign matches long/short for every govt bond.")

    corp = sens[sens["asset_class"] == "Corp Bond"].merge(positions[["position_id", "quantity"]], on="position_id")
    assert ((corp["quantity"] > 0) == (corp["CS01"] > 0)).all(), \
        "A long corp bond should have positive CS01 (loses value when spreads widen)"
    print("Sanity check 3 passed: CS01 sign matches long/short for every corp bond.\n")

    print("=== Manual example: AAPL stock vs AAPL 500 Call ===")
    print(sens[sens["instrument_id"].isin(["AAPL-EQ", "AAPL-OPT-C-500-20270130"])].to_string(index=False))

    print("\n=== Manual example: UST-GB-10Y (govt) vs JPM-CB-5Y (corp) ===")
    print(sens[sens["instrument_id"].isin(["UST-GB-10Y", "JPM-CB-5Y"])].to_string(index=False))

    print("\n=== Sensitivity Summary by Book ===")
    print(aggregate_sensitivities(sens_full, "book_id").round(2))
    print("\n=== Sensitivity Summary by Desk ===")
    print(aggregate_sensitivities(sens_full, "desk_name").round(2))
    print("\n=== Sensitivity Summary by Asset Class ===")
    print(aggregate_sensitivities(sens_full, "asset_class").round(2))
