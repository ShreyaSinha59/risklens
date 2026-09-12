"""
Module 3: Portfolio Valuation and Exposure

Reusable valuation functions (position-level pricing) plus reusable
aggregation functions (exposure by book/desk/asset-class/issuer), built on
top of Module 1's reference/position tables and Module 2's risk-factor
levels. No new fields are added to those tables - this module only reads
them and derives market value.

Simplifications are documented in the accompanying explanation, not
repeated in comments here except where they affect a specific formula.
"""

import math
from datetime import date

import numpy as np
import pandas as pd

AS_OF_DATE = date(2026, 9, 4)

# Currency -> yield-curve risk factors available at that currency's tenors (Module 2 IDs)
YIELD_CURVES = {
    "USD": {2: "UST-2Y-YIELD", 5: "UST-5Y-YIELD", 10: "UST-10Y-YIELD", 30: "UST-30Y-YIELD"},
    "GBP": {5: "UKGILT-5Y-YIELD", 10: "UKGILT-10Y-YIELD"},
    "EUR": {5: "BUND-5Y-YIELD", 10: "BUND-10Y-YIELD"},
}
FX_RISK_FACTOR_FOR_CURRENCY = {"GBP": "GBPUSD", "EUR": "EURUSD"}  # USD needs no conversion


# ---------------------------------------------------------------------------
# Market data lookup
# ---------------------------------------------------------------------------
def latest_levels_as_of(levels, as_of_date):
    """One row per risk_factor_id: the latest observation on or before as_of_date."""
    dates = pd.to_datetime(levels["date"]).dt.date
    df = levels[dates <= as_of_date].sort_values("date")
    return df.groupby("risk_factor_id").last().reset_index()[["risk_factor_id", "risk_factor_type", "value"]]


def levels_dict(latest_df, risk_factor_type):
    """risk_factor_id -> value, restricted to one risk_factor_type."""
    sub = latest_df[latest_df["risk_factor_type"] == risk_factor_type]
    return sub.set_index("risk_factor_id")["value"].to_dict()


def nearest_tenor_risk_factor(currency, years_to_maturity):
    curve = YIELD_CURVES[currency]
    nearest_tenor = min(curve.keys(), key=lambda t: abs(t - years_to_maturity))
    return curve[nearest_tenor]


# ---------------------------------------------------------------------------
# Position-level pricing (pure functions - reusable by later modules,
# e.g. VaR will call these again with shocked inputs)
# ---------------------------------------------------------------------------
def price_equity(quantity, spot_price):
    return quantity * spot_price


def price_fx(quantity, base_currency, quote_currency, spot_rate):
    """quantity is a notional amount in base_currency. Returns USD value."""
    if quote_currency == "USD":
        return quantity * spot_rate          # spot_rate = USD per unit of base_currency
    if base_currency == "USD":
        return quantity                       # already a USD amount
    raise ValueError(f"Unsupported FX pair for USD reporting: {base_currency}/{quote_currency}")


def price_bond(face_value, coupon_rate, years_to_maturity, discount_rate):
    """Simplified annual-coupon DCF. Returns market value in the bond's own currency."""
    n_periods = max(1, round(years_to_maturity))
    coupon_cashflow = coupon_rate * 100
    price_per_100 = sum(coupon_cashflow / (1 + discount_rate) ** t for t in range(1, n_periods + 1))
    price_per_100 += 100 / (1 + discount_rate) ** n_periods
    return (face_value / 100) * price_per_100


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def norm_pdf(x):
    return math.exp(-0.5 * x ** 2) / math.sqrt(2 * math.pi)


def compute_d1(spot, strike, years_to_expiry, risk_free_rate, volatility):
    return (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility ** 2) * years_to_expiry) / \
           (volatility * math.sqrt(years_to_expiry))


def black_scholes_price(spot, strike, years_to_expiry, risk_free_rate, volatility, option_type):
    d1 = compute_d1(spot, strike, years_to_expiry, risk_free_rate, volatility)
    d2 = d1 - volatility * math.sqrt(years_to_expiry)
    discount = math.exp(-risk_free_rate * years_to_expiry)
    if option_type == "Call":
        return spot * norm_cdf(d1) - strike * discount * norm_cdf(d2)
    return strike * discount * norm_cdf(-d2) - spot * norm_cdf(-d1)  # Put


def convert_to_usd(value_local, currency, fx_levels):
    if currency == "USD":
        return value_local
    rate = fx_levels[FX_RISK_FACTOR_FOR_CURRENCY[currency]]
    return value_local * rate


# ---------------------------------------------------------------------------
# Enrichment: value every position, once, into a single reusable table
# ---------------------------------------------------------------------------
def value_positions(positions, instruments, fx_levels, price_levels, yield_levels,
                     spread_levels, vol_levels, as_of_date=AS_OF_DATE):
    rows = []
    inst_by_id = instruments.set_index("instrument_id").to_dict("index")

    for pos in positions.itertuples():
        inst = inst_by_id[pos.instrument_id]
        asset_class = inst["asset_class"]
        quantity = pos.quantity

        if asset_class == "Equity":
            spot = price_levels[pos.instrument_id]
            mv_local = price_equity(quantity, spot)
            currency = inst["currency"]

        elif asset_class == "FX":
            rate = fx_levels[pos.instrument_id]
            mv_local = price_fx(quantity, inst["base_currency"], inst["quote_currency"], rate)
            currency = "USD"  # FX market value is computed directly in USD (see price_fx)

        elif asset_class == "Govt Bond":
            years = (pd.Timestamp(inst["maturity_date"]).date() - as_of_date).days / 365.25
            rf_id = nearest_tenor_risk_factor(inst["currency"], years)
            discount_rate = yield_levels[rf_id]
            mv_local = price_bond(quantity, inst["coupon_rate"], years, discount_rate)
            currency = inst["currency"]

        elif asset_class == "Corp Bond":
            years = (pd.Timestamp(inst["maturity_date"]).date() - as_of_date).days / 365.25
            rf_id = nearest_tenor_risk_factor("USD", years)  # corp bonds are all USD here
            risk_free = yield_levels[rf_id]
            spread = spread_levels[f"{inst['issuer_id']}-CS"]
            mv_local = price_bond(quantity, inst["coupon_rate"], years, risk_free + spread)
            currency = inst["currency"]

        elif asset_class == "Equity Option":
            underlying_id = inst["underlying_instrument_id"]
            spot = price_levels[underlying_id]
            years = (pd.Timestamp(inst["maturity_date"]).date() - as_of_date).days / 365.25
            rf_id = nearest_tenor_risk_factor("USD", years)
            risk_free = yield_levels[rf_id]
            vol = vol_levels[f"{underlying_id.replace('-EQ', '')}-VOL"]
            premium = black_scholes_price(spot, inst["strike_price"], years, risk_free, vol, inst["option_type"])
            mv_local = quantity * inst["contract_multiplier"] * premium
            currency = inst["currency"]

        else:
            raise ValueError(f"Unhandled asset_class: {asset_class}")

        mv_usd = convert_to_usd(mv_local, currency, fx_levels)
        rows.append({
            "position_id": pos.position_id, "book_id": pos.book_id, "instrument_id": pos.instrument_id,
            "asset_class": asset_class, "issuer_id": inst["issuer_id"], "currency": currency,
            "quantity": quantity, "market_value_local": mv_local, "market_value_usd": mv_usd,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Aggregations - all simple groupby/sum on the one enriched table
# ---------------------------------------------------------------------------
def portfolio_market_value(valued): return valued["market_value_usd"].sum()
def gross_exposure(valued): return valued["market_value_usd"].abs().sum()
def net_exposure(valued): return valued["market_value_usd"].sum()

def exposure_by(valued, group_col):
    g = valued.groupby(group_col)["market_value_usd"]
    return pd.DataFrame({"net_exposure": g.sum(), "gross_exposure": g.apply(lambda s: s.abs().sum())})

def book_exposure(valued): return exposure_by(valued, "book_id")
def desk_exposure(valued, books, desks):
    enriched = valued.merge(books, on="book_id").merge(desks, on="desk_id")
    return exposure_by(enriched, "desk_name")
def asset_class_exposure(valued): return exposure_by(valued, "asset_class")
def issuer_concentration(valued, issuers, top_n=5):
    enriched = valued.dropna(subset=["issuer_id"]).merge(issuers, on="issuer_id")
    result = exposure_by(enriched, "issuer_name")
    return result.sort_values("gross_exposure", ascending=False).head(top_n)


# ---------------------------------------------------------------------------
# Run end-to-end and print the summary
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    desks = pd.read_csv("data/desks.csv")
    books = pd.read_csv("data/books.csv")
    issuers = pd.read_csv("data/issuers.csv")
    instruments = pd.read_csv("data/instruments.csv")
    positions = pd.read_csv("data/positions.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")

    latest = latest_levels_as_of(levels, AS_OF_DATE)
    price_levels = levels_dict(latest, "Equity Price")
    fx_levels = levels_dict(latest, "FX Spot")
    yield_levels = levels_dict(latest, "Yield")
    spread_levels = levels_dict(latest, "Credit Spread")
    vol_levels = levels_dict(latest, "Implied Vol (Realized Proxy)")

    valued = value_positions(positions, instruments, fx_levels, price_levels,
                              yield_levels, spread_levels, vol_levels)
    valued.to_csv("data/processed/position_valuations.csv", index=False)

    # --- sanity checks ---
    assert (gross_exposure(valued) >= abs(net_exposure(valued)) - 1e-6), "Gross must be >= |Net|"
    manual_bond_check = price_bond(10_000_000, 0.0420, 10, yield_levels["UST-10Y-YIELD"])
    assert abs(manual_bond_check - valued.loc[valued.instrument_id == "UST-GB-10Y", "market_value_local"].iloc[0]) < 1e-6
    print("Sanity checks passed: gross >= |net|; manual bond recompute matches pipeline.\n")

    print("=== Manual valuation examples ===")
    aapl_qty = positions.loc[positions.instrument_id == "AAPL-EQ", "quantity"].iloc[0]
    print(f"Equity  AAPL-EQ: {aapl_qty} x ${price_levels['AAPL-EQ']:.2f} = "
          f"${price_equity(aapl_qty, price_levels['AAPL-EQ']):,.2f}")

    bond_mv = manual_bond_check
    print(f"Bond    UST-GB-10Y: face 10,000,000 @ 4.20% coupon, 10yr, "
          f"yield {yield_levels['UST-10Y-YIELD']*100:.2f}% -> price/100 = {bond_mv/100_000:.4f} "
          f"-> MV = ${bond_mv:,.2f}")

    opt_row = instruments.set_index("instrument_id").loc["AAPL-OPT-C-500-20270130"]
    years = (pd.Timestamp(opt_row["maturity_date"]).date() - AS_OF_DATE).days / 365.25
    r = yield_levels[nearest_tenor_risk_factor("USD", years)]
    vol = vol_levels["AAPL-VOL"]
    premium = black_scholes_price(price_levels["AAPL-EQ"], opt_row["strike_price"], years, r, vol, "Call")
    opt_qty = positions.loc[positions.instrument_id == "AAPL-OPT-C-500-20270130", "quantity"].iloc[0]
    print(f"Option  AAPL Call K=500: S=${price_levels['AAPL-EQ']:.2f}, T={years:.3f}y, r={r*100:.2f}%, "
          f"sigma={vol*100:.1f}% -> premium=${premium:.4f}/share (deep OTM: spot is 35% below strike) "
          f"-> MV = {opt_qty} x 100 x ${premium:.4f} = ${opt_qty*100*premium:,.2f}\n")

    print("=== Portfolio Summary ===")
    print(f"Portfolio Value : ${portfolio_market_value(valued):,.2f}")
    print(f"Gross Exposure  : ${gross_exposure(valued):,.2f}")
    print(f"Net Exposure    : ${net_exposure(valued):,.2f}\n")

    print("--- Exposure by Asset Class ---")
    print(asset_class_exposure(valued).round(0))
    print("\n--- Exposure by Desk ---")
    print(desk_exposure(valued, books, desks).round(0))
    print("\n--- Top Issuer Concentrations ---")
    print(issuer_concentration(valued, issuers).round(0))
