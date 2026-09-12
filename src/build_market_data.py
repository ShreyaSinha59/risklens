"""
Module 2: Market Data Ingestion & Historical Risk-Factor Changes

Pulls real market data (Yahoo Finance, FRED) plus two explicitly-labeled
synthetic/proxy series where free real data isn't available at daily
granularity, normalizes everything into a common risk-factor schema, and
derives the historical level-to-level changes used by later risk modules.

Design notes (explicit simplifications):
- Options' time-to-expiry is NOT modeled here - it's a deterministic
  instrument attribute (maturity_date - as_of_date), computed at valuation
  time, not a market-observed series.
- Options' discount rate reuses the Yield risk factors below rather than
  creating a duplicate "interest rate" series.
- Each risk factor's "previous value" is the prior available observation
  in ITS OWN series, not a value aligned to a shared calendar. Different
  markets (US equities, UK/DE bonds, FX) trade on different calendars, and
  we are deliberately NOT forward-filling gaps to force alignment - if a
  later module needs a common calendar, that will be a separate, explicit
  decision with a stated reason.
"""

import io
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

AS_OF_DATE = date(2026, 9, 4)          # matches Module 1 portfolio as_of_date
LOOKBACK_DAYS = 730                     # ~2 years of history
START_DATE = AS_OF_DATE - timedelta(days=LOOKBACK_DAYS)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

EQUITY_TICKERS = ["AAPL", "MSFT", "JPM", "XOM", "AMZN", "GOOGL", "META", "NVDA", "BAC", "KO"]
VOL_UNDERLYINGS = ["AAPL", "JPM", "MSFT", "NVDA", "XOM"]   # the 5 names our options are written on

UST_SERIES = {"UST-2Y-YIELD": "DGS2", "UST-5Y-YIELD": "DGS5", "UST-10Y-YIELD": "DGS10", "UST-30Y-YIELD": "DGS30"}
CREDIT_SERIES = {  # issuer risk_factor_id -> FRED OAS bucket, bucket chosen from Module 1 credit_rating
    "ISS_AAPL-CS": "BAMLC0A2CAA",   # AA+  -> AA bucket
    "ISS_MSFT-CS": "BAMLC0A1CAAA",  # AAA  -> AAA bucket
    "ISS_JPM-CS":  "BAMLC0A3CA",    # A+   -> A bucket
    "ISS_XOM-CS":  "BAMLC0A2CAA",   # AA-  -> AA bucket
    "ISS_BAC-CS":  "BAMLC0A3CA",    # A    -> A bucket
}
FX_SERIES = {"EURUSD": "DEXUSEU", "GBPUSD": "DEXUSUK", "USDJPY": "DEXJPUS",
             "AUDUSD": "DEXUSAL", "USDCHF": "DEXSZUS", "USDCAD": "DEXCAUS"}
SYNTHETIC_GOVT_YIELDS = {  # risk_factor_id -> (starting level, seed)
    "UKGILT-5Y-YIELD": (0.0400, 101), "UKGILT-10Y-YIELD": (0.0420, 102),
    "BUND-5Y-YIELD": (0.0250, 103), "BUND-10Y-YIELD": (0.0270, 104),
}

RISK_TYPE_CHANGE_TYPE = {
    "Equity Price": "Log Return",
    "FX Spot": "Log Return",
    "Yield": "bp Change",
    "Credit Spread": "bp Change",
    "Implied Vol (Realized Proxy)": "Vol Pt Change",
}


# ---------------------------------------------------------------------------
# SECTION 1: Raw ingestion functions (source-agnostic shape: date, value)
# ---------------------------------------------------------------------------
def fetch_yahoo_prices(ticker, start_date, end_date):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": int(pd.Timestamp(start_date).timestamp()),
              "period2": int(pd.Timestamp(end_date).timestamp()), "interval": "1d"}
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    dates = pd.to_datetime(result["timestamp"], unit="s").date
    df = pd.DataFrame({"date": dates, "value": closes})
    return df.dropna(subset=["value"])  # a null close = missing observation, not silently filled


def fetch_fred_series(series_id, start_date, end_date):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for no observation
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
    return df.dropna(subset=["value"])


def generate_synthetic_yield(start_level, start_date, end_date, seed, daily_bp_vol=3.0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start_date, end_date).date
    changes_bp = rng.normal(0, daily_bp_vol, size=len(dates))
    changes_bp[0] = 0.0  # anchor the first observation exactly at start_level
    level = start_level + np.cumsum(changes_bp) / 10_000
    return pd.DataFrame({"date": dates, "value": level})


# ---------------------------------------------------------------------------
# SECTION 2: Pull raw data and write it, untouched, to data/raw/
# ---------------------------------------------------------------------------
def pull_raw_data():
    equity_rows = []
    for ticker in EQUITY_TICKERS:
        try:
            df = fetch_yahoo_prices(ticker, START_DATE, AS_OF_DATE)
            df["ticker"] = ticker
            equity_rows.append(df.rename(columns={"value": "close"}))
        except Exception as e:
            print(f"WARNING: equity fetch failed for {ticker}: {e}")
    equity_prices_raw = pd.concat(equity_rows, ignore_index=True)[["date", "ticker", "close"]]

    yield_rows = []
    for rf_id, series_id in UST_SERIES.items():
        df = fetch_fred_series(series_id, START_DATE, AS_OF_DATE)
        df["series_id"] = series_id
        yield_rows.append(df.rename(columns={"value": "value_pct"}))
    treasury_yields_raw = pd.concat(yield_rows, ignore_index=True)[["date", "series_id", "value_pct"]]

    credit_rows = []
    for rf_id, series_id in CREDIT_SERIES.items():
        df = fetch_fred_series(series_id, START_DATE, AS_OF_DATE)
        df["series_id"] = series_id
        credit_rows.append(df.rename(columns={"value": "value_pct"}))
    credit_oas_raw = pd.concat(credit_rows, ignore_index=True).drop_duplicates(subset=["date", "series_id"])[
        ["date", "series_id", "value_pct"]]

    fx_rows = []
    for pair, series_id in FX_SERIES.items():
        df = fetch_fred_series(series_id, START_DATE, AS_OF_DATE)
        df["series_id"] = series_id
        fx_rows.append(df.rename(columns={"value": "rate"}))
    fx_rates_raw = pd.concat(fx_rows, ignore_index=True)[["date", "series_id", "rate"]]

    synth_rows = []
    for rf_id, (start_level, seed) in SYNTHETIC_GOVT_YIELDS.items():
        df = generate_synthetic_yield(start_level, START_DATE, AS_OF_DATE, seed)
        df["curve_id"] = rf_id
        synth_rows.append(df)
    govt_yields_synthetic_raw = pd.concat(synth_rows, ignore_index=True)[["date", "curve_id", "value"]]

    raw_tables = {
        "equity_prices_raw": equity_prices_raw,
        "treasury_yields_raw": treasury_yields_raw,
        "credit_oas_raw": credit_oas_raw,
        "fx_rates_raw": fx_rates_raw,
        "govt_yields_synthetic_raw": govt_yields_synthetic_raw,
    }
    for name, df in raw_tables.items():
        df.to_csv(f"data/raw/{name}.csv", index=False)
    return raw_tables


# ---------------------------------------------------------------------------
# SECTION 3: Normalize raw data into the common risk-factor level schema
#            (date, risk_factor_id, risk_factor_type, value)
# ---------------------------------------------------------------------------
def normalize_to_levels(raw):
    frames = []

    eq = raw["equity_prices_raw"].rename(columns={"ticker": "risk_factor_id", "close": "value"}).copy()
    eq["risk_factor_id"] = eq["risk_factor_id"] + "-EQ"
    eq["risk_factor_type"] = "Equity Price"
    frames.append(eq[["date", "risk_factor_id", "risk_factor_type", "value"]])

    id_by_series = {v: k for k, v in UST_SERIES.items()}
    ust = raw["treasury_yields_raw"].copy()
    ust["risk_factor_id"] = ust["series_id"].map(id_by_series)
    ust["risk_factor_type"] = "Yield"
    ust["value"] = ust["value_pct"] / 100.0
    frames.append(ust[["date", "risk_factor_id", "risk_factor_type", "value"]])

    id_by_series = {v: k for k, v in CREDIT_SERIES.items()}
    # NOTE: two issuers can share one FRED bucket (e.g. AAPL and XOM both use the AA bucket) -
    # that many-to-one mapping is the "rating-bucket approximation" flagged in Part B.
    credit = raw["credit_oas_raw"].copy()
    credit_expanded = []
    for rf_id, series_id in CREDIT_SERIES.items():
        sub = credit[credit["series_id"] == series_id].copy()
        sub["risk_factor_id"] = rf_id
        credit_expanded.append(sub)
    credit = pd.concat(credit_expanded, ignore_index=True)
    credit["risk_factor_type"] = "Credit Spread"
    credit["value"] = credit["value_pct"] / 100.0
    frames.append(credit[["date", "risk_factor_id", "risk_factor_type", "value"]])

    fx = raw["fx_rates_raw"].copy()
    id_by_series = {v: k for k, v in FX_SERIES.items()}
    fx["risk_factor_id"] = fx["series_id"].map(id_by_series)
    fx["risk_factor_type"] = "FX Spot"
    fx = fx.rename(columns={"rate": "value"})
    frames.append(fx[["date", "risk_factor_id", "risk_factor_type", "value"]])

    synth = raw["govt_yields_synthetic_raw"].rename(columns={"curve_id": "risk_factor_id"}).copy()
    synth["risk_factor_type"] = "Yield"
    frames.append(synth[["date", "risk_factor_id", "risk_factor_type", "value"]])

    # Implied vol proxy: 21-day rolling realized volatility, annualized, from real equity closes.
    # First 20 observations per ticker are NaN (not enough history for the window) and are dropped -
    # this is a legitimate "insufficient history" case, not a data-quality problem to paper over.
    vol_frames = []
    for ticker in VOL_UNDERLYINGS:
        px = raw["equity_prices_raw"][raw["equity_prices_raw"]["ticker"] == ticker].sort_values("date")
        log_ret = np.log(px["close"] / px["close"].shift(1))
        realized_vol = log_ret.rolling(21).std() * np.sqrt(252)
        vdf = pd.DataFrame({"date": px["date"], "value": realized_vol})
        vdf["risk_factor_id"] = f"{ticker}-VOL"
        vdf["risk_factor_type"] = "Implied Vol (Realized Proxy)"
        vol_frames.append(vdf.dropna(subset=["value"]))
    frames.append(pd.concat(vol_frames, ignore_index=True)[["date", "risk_factor_id", "risk_factor_type", "value"]])

    levels = pd.concat(frames, ignore_index=True)
    return clean_levels(levels)


def clean_levels(levels):
    before = len(levels)
    levels = levels.drop_duplicates(subset=["date", "risk_factor_id"], keep="last")
    n_dupes = before - len(levels)
    if n_dupes:
        print(f"NOTE: dropped {n_dupes} duplicate (date, risk_factor_id) rows")

    bounds = {
        "Equity Price": (0, None),
        "Yield": (-0.02, 0.20),
        "Credit Spread": (0, 0.20),
        "FX Spot": (0, None),
        "Implied Vol (Realized Proxy)": (0, 3.0),
    }
    valid_mask = pd.Series(True, index=levels.index)
    for rf_type, (lo, hi) in bounds.items():
        type_mask = levels["risk_factor_type"] == rf_type
        if lo is not None:
            valid_mask &= ~(type_mask & (levels["value"] < lo))
        if hi is not None:
            valid_mask &= ~(type_mask & (levels["value"] > hi))
    n_invalid = (~valid_mask).sum()
    if n_invalid:
        print(f"NOTE: dropped {n_invalid} rows with implausible values (outside sanity bounds)")
    levels = levels[valid_mask]

    return levels.sort_values(["risk_factor_id", "date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# SECTION 4: Derive historical changes from levels
#            (date, risk_factor_id, risk_factor_type, previous_value, current_value, change_type, change)
# ---------------------------------------------------------------------------
def build_changes(levels):
    df = levels.sort_values(["risk_factor_id", "date"]).copy()
    df["previous_value"] = df.groupby("risk_factor_id")["value"].shift(1)
    df = df.dropna(subset=["previous_value"])  # first obs per risk factor has no prior value - drop, don't fill
    df = df.rename(columns={"value": "current_value"})
    df["change_type"] = df["risk_factor_type"].map(RISK_TYPE_CHANGE_TYPE)

    def compute_change(row):
        if row["change_type"] == "Log Return":
            return np.log(row["current_value"] / row["previous_value"])
        if row["change_type"] == "bp Change":
            return (row["current_value"] - row["previous_value"]) * 10_000
        if row["change_type"] == "Vol Pt Change":
            return (row["current_value"] - row["previous_value"]) * 100
        raise ValueError(f"Unhandled change_type: {row['change_type']}")

    df["change"] = df.apply(compute_change, axis=1)
    return df[["date", "risk_factor_id", "risk_factor_type", "previous_value",
               "current_value", "change_type", "change"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# SECTION 5: Validation
# ---------------------------------------------------------------------------
def validate_market_data(levels, changes):
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check(not levels.duplicated(subset=["date", "risk_factor_id"]).any(),
          "Duplicate (date, risk_factor_id) in levels")
    check(not changes.duplicated(subset=["date", "risk_factor_id"]).any(),
          "Duplicate (date, risk_factor_id) in changes")
    type_per_id = levels.groupby("risk_factor_id")["risk_factor_type"].nunique()
    check((type_per_id == 1).all(), "A risk_factor_id maps to more than one risk_factor_type")
    check(levels["value"].notna().all(), "Null value in levels")
    check(changes[["previous_value", "current_value", "change"]].notna().all().all(), "Null value in changes")

    return errors


# ---------------------------------------------------------------------------
# SECTION 6: Run pipeline, write processed output, print samples
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Fetching market data from {START_DATE} to {AS_OF_DATE} ...")
    raw = pull_raw_data()
    print("Raw data written to data/raw/\n")

    levels = normalize_to_levels(raw)
    changes = build_changes(levels)

    errors = validate_market_data(levels, changes)
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    levels.to_csv("data/processed/risk_factor_levels.csv", index=False)
    changes.to_csv("data/processed/risk_factor_changes.csv", index=False)

    print(f"All validation checks passed.")
    print(f"{levels['risk_factor_id'].nunique()} risk factors, "
          f"{len(levels)} level observations, {len(changes)} change observations.\n")

    print("--- risk_factor_levels sample ---")
    print(levels.head(3).to_string(index=False))
    print("\n--- risk_factor_changes sample ---")
    print(changes.head(3).to_string(index=False))
