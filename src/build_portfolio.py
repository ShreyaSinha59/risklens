"""
Module 1: Synthetic Trading Portfolio (final schema)

Builds five tables per the agreed data model: desks, books, issuers,
instruments, positions.

Design note (explicit simplification): this reference data and this position
book are hand-crafted, not randomly sampled. The project needs specific,
engineered scenarios later (issuer concentration, a desk approaching a risk
limit), and random sampling would fight that goal. A real bank's book is
never hand-typed like this - flagging so it isn't mistaken for realistic
random data.
"""

import pandas as pd
from datetime import date

AS_OF_DATE = date(2026, 9, 4)

# ---------------------------------------------------------------------------
# SECTION 1: Desks
# ---------------------------------------------------------------------------
desks = pd.DataFrame([
    {"desk_id": "DSK_EQ", "desk_name": "Equities Desk", "asset_class_focus": "Equity, Equity Option"},
    {"desk_id": "DSK_FI", "desk_name": "Fixed Income Desk", "asset_class_focus": "Govt Bond, Corp Bond"},
    {"desk_id": "DSK_FX", "desk_name": "FX Desk", "asset_class_focus": "FX"},
])

# ---------------------------------------------------------------------------
# SECTION 2: Books
# ---------------------------------------------------------------------------
books = pd.DataFrame([
    {"book_id": "BK_EQ_LS", "book_name": "US Equity Long/Short", "desk_id": "DSK_EQ"},
    {"book_id": "BK_EQ_DERIV", "book_name": "Equity Derivatives", "desk_id": "DSK_EQ"},
    {"book_id": "BK_RATES_GOVT", "book_name": "Rates - Government Bonds", "desk_id": "DSK_FI"},
    {"book_id": "BK_CREDIT_IG", "book_name": "Investment Grade Credit", "desk_id": "DSK_FI"},
    {"book_id": "BK_CREDIT_CONC", "book_name": "Credit - Concentrated Book", "desk_id": "DSK_FI"},
    {"book_id": "BK_FX_MAJORS", "book_name": "FX Majors", "desk_id": "DSK_FX"},
])

# ---------------------------------------------------------------------------
# SECTION 3: Issuers
# ---------------------------------------------------------------------------
issuers = pd.DataFrame([
    {"issuer_id": "ISS_UST",    "issuer_name": "United States Treasury",      "issuer_type": "Sovereign", "country": "US", "sector": None, "credit_rating": "AA+"},
    {"issuer_id": "ISS_UKGILT", "issuer_name": "United Kingdom Gilt",         "issuer_type": "Sovereign", "country": "UK", "sector": None, "credit_rating": "AA"},
    {"issuer_id": "ISS_BUND",   "issuer_name": "Federal Republic of Germany", "issuer_type": "Sovereign", "country": "DE", "sector": None, "credit_rating": "AAA"},
    {"issuer_id": "ISS_AAPL",  "issuer_name": "Apple Inc",              "issuer_type": "Corporate", "country": "US", "sector": "Technology",             "credit_rating": "AA+"},
    {"issuer_id": "ISS_MSFT",  "issuer_name": "Microsoft Corp",         "issuer_type": "Corporate", "country": "US", "sector": "Technology",             "credit_rating": "AAA"},
    {"issuer_id": "ISS_JPM",   "issuer_name": "JPMorgan Chase & Co",    "issuer_type": "Corporate", "country": "US", "sector": "Financials",             "credit_rating": "A+"},
    {"issuer_id": "ISS_XOM",   "issuer_name": "Exxon Mobil Corp",       "issuer_type": "Corporate", "country": "US", "sector": "Energy",                 "credit_rating": "AA-"},
    {"issuer_id": "ISS_BAC",   "issuer_name": "Bank of America Corp",   "issuer_type": "Corporate", "country": "US", "sector": "Financials",             "credit_rating": "A"},
    {"issuer_id": "ISS_AMZN",  "issuer_name": "Amazon.com Inc",         "issuer_type": "Corporate", "country": "US", "sector": "Consumer Discretionary", "credit_rating": "AA"},
    {"issuer_id": "ISS_GOOGL", "issuer_name": "Alphabet Inc",           "issuer_type": "Corporate", "country": "US", "sector": "Technology",             "credit_rating": "AA+"},
    {"issuer_id": "ISS_META",  "issuer_name": "Meta Platforms Inc",     "issuer_type": "Corporate", "country": "US", "sector": "Technology",             "credit_rating": "A+"},
    {"issuer_id": "ISS_NVDA",  "issuer_name": "NVIDIA Corp",            "issuer_type": "Corporate", "country": "US", "sector": "Technology",             "credit_rating": "A+"},
    {"issuer_id": "ISS_KO",    "issuer_name": "Coca-Cola Co",           "issuer_type": "Corporate", "country": "US", "sector": "Consumer Staples",       "credit_rating": "A+"},
])

# ---------------------------------------------------------------------------
# SECTION 4: Instruments
# ---------------------------------------------------------------------------
INSTRUMENT_COLUMNS = [
    "instrument_id", "instrument_name", "asset_class", "issuer_id", "underlying_instrument_id",
    "currency", "base_currency", "quote_currency", "maturity_date", "coupon_rate",
    "strike_price", "option_type", "contract_multiplier",
]

def _fill_defaults(row, **defaults):
    for key, value in defaults.items():
        row.setdefault(key, value)
    return row

# 4a. Equities - one instrument per name, holds the equity price risk factor
equities = [
    {"instrument_id": "AAPL-EQ",  "instrument_name": "Apple Inc Common Stock",              "issuer_id": "ISS_AAPL"},
    {"instrument_id": "MSFT-EQ",  "instrument_name": "Microsoft Corp Common Stock",          "issuer_id": "ISS_MSFT"},
    {"instrument_id": "JPM-EQ",   "instrument_name": "JPMorgan Chase & Co Common Stock",     "issuer_id": "ISS_JPM"},
    {"instrument_id": "XOM-EQ",   "instrument_name": "Exxon Mobil Corp Common Stock",        "issuer_id": "ISS_XOM"},
    {"instrument_id": "AMZN-EQ",  "instrument_name": "Amazon.com Inc Common Stock",          "issuer_id": "ISS_AMZN"},
    {"instrument_id": "GOOGL-EQ", "instrument_name": "Alphabet Inc Common Stock",            "issuer_id": "ISS_GOOGL"},
    {"instrument_id": "META-EQ",  "instrument_name": "Meta Platforms Inc Common Stock",      "issuer_id": "ISS_META"},
    {"instrument_id": "NVDA-EQ",  "instrument_name": "NVIDIA Corp Common Stock",             "issuer_id": "ISS_NVDA"},
    {"instrument_id": "BAC-EQ",   "instrument_name": "Bank of America Corp Common Stock",    "issuer_id": "ISS_BAC"},
    {"instrument_id": "KO-EQ",    "instrument_name": "Coca-Cola Co Common Stock",            "issuer_id": "ISS_KO"},
]
equities = [_fill_defaults(r, asset_class="Equity", underlying_instrument_id=None, currency="USD",
                            base_currency=None, quote_currency=None, maturity_date=None,
                            coupon_rate=None, strike_price=None, option_type=None,
                            contract_multiplier=None) for r in equities]

# 4b. Equity Options - underlying_instrument_id links back to the equity above
options = [
    {"instrument_id": "AAPL-OPT-C-500-20270130", "instrument_name": "Apple Inc Jan-2027 500 Call",       "underlying_instrument_id": "AAPL-EQ", "issuer_id": "ISS_AAPL", "maturity_date": date(2027, 1, 30),  "strike_price": 500.0, "option_type": "Call"},
    {"instrument_id": "AAPL-OPT-P-450-20270130", "instrument_name": "Apple Inc Jan-2027 450 Put",        "underlying_instrument_id": "AAPL-EQ", "issuer_id": "ISS_AAPL", "maturity_date": date(2027, 1, 30),  "strike_price": 450.0, "option_type": "Put"},
    {"instrument_id": "JPM-OPT-C-300-20270619",  "instrument_name": "JPMorgan Chase Jun-2027 300 Call",  "underlying_instrument_id": "JPM-EQ",  "issuer_id": "ISS_JPM",  "maturity_date": date(2027, 6, 19),  "strike_price": 300.0, "option_type": "Call"},
    {"instrument_id": "MSFT-OPT-P-380-20261218", "instrument_name": "Microsoft Dec-2026 380 Put",        "underlying_instrument_id": "MSFT-EQ", "issuer_id": "ISS_MSFT", "maturity_date": date(2026, 12, 18), "strike_price": 380.0, "option_type": "Put"},
    {"instrument_id": "NVDA-OPT-C-140-20270320", "instrument_name": "NVIDIA Mar-2027 140 Call",          "underlying_instrument_id": "NVDA-EQ", "issuer_id": "ISS_NVDA", "maturity_date": date(2027, 3, 20),  "strike_price": 140.0, "option_type": "Call"},
    {"instrument_id": "XOM-OPT-P-100-20261120",  "instrument_name": "Exxon Mobil Nov-2026 100 Put",      "underlying_instrument_id": "XOM-EQ",  "issuer_id": "ISS_XOM",  "maturity_date": date(2026, 11, 20), "strike_price": 100.0, "option_type": "Put"},
]
options = [_fill_defaults(r, asset_class="Equity Option", currency="USD", base_currency=None,
                           quote_currency=None, coupon_rate=None, contract_multiplier=100)
           for r in options]

# 4c. Government Bonds - a tenor ladder on US Treasuries plus two other sovereigns
govt_bonds = [
    {"instrument_id": "UST-GB-2Y",     "instrument_name": "US Treasury 2Y Note",  "issuer_id": "ISS_UST",    "currency": "USD", "maturity_date": date(2028, 9, 4),  "coupon_rate": 0.0400},
    {"instrument_id": "UST-GB-5Y",     "instrument_name": "US Treasury 5Y Note",  "issuer_id": "ISS_UST",    "currency": "USD", "maturity_date": date(2031, 9, 4),  "coupon_rate": 0.0400},
    {"instrument_id": "UST-GB-10Y",    "instrument_name": "US Treasury 10Y Note", "issuer_id": "ISS_UST",    "currency": "USD", "maturity_date": date(2036, 9, 4),  "coupon_rate": 0.0420},
    {"instrument_id": "UST-GB-30Y",    "instrument_name": "US Treasury 30Y Bond", "issuer_id": "ISS_UST",    "currency": "USD", "maturity_date": date(2056, 9, 4),  "coupon_rate": 0.0450},
    {"instrument_id": "UKGILT-GB-5Y",  "instrument_name": "UK Gilt 5Y",           "issuer_id": "ISS_UKGILT", "currency": "GBP", "maturity_date": date(2031, 9, 4),  "coupon_rate": 0.0400},
    {"instrument_id": "UKGILT-GB-10Y", "instrument_name": "UK Gilt 10Y",          "issuer_id": "ISS_UKGILT", "currency": "GBP", "maturity_date": date(2036, 9, 4),  "coupon_rate": 0.0420},
    {"instrument_id": "BUND-GB-5Y",    "instrument_name": "German Bund 5Y",       "issuer_id": "ISS_BUND",   "currency": "EUR", "maturity_date": date(2031, 9, 4),  "coupon_rate": 0.0250},
    {"instrument_id": "BUND-GB-10Y",   "instrument_name": "German Bund 10Y",      "issuer_id": "ISS_BUND",   "currency": "EUR", "maturity_date": date(2036, 9, 4),  "coupon_rate": 0.0270},
]
govt_bonds = [_fill_defaults(r, asset_class="Govt Bond", underlying_instrument_id=None,
                              base_currency=None, quote_currency=None, strike_price=None,
                              option_type=None, contract_multiplier=None) for r in govt_bonds]

# 4d. Corporate Bonds - deliberately JPM-heavy across two books (issuer concentration)
corp_bonds = [
    {"instrument_id": "AAPL-CB-5Y",  "instrument_name": "Apple Inc 5Y Corp Bond",         "issuer_id": "ISS_AAPL", "maturity_date": date(2031, 9, 4), "coupon_rate": 0.0400},
    {"instrument_id": "MSFT-CB-5Y",  "instrument_name": "Microsoft Corp 5Y Corp Bond",    "issuer_id": "ISS_MSFT", "maturity_date": date(2031, 9, 4), "coupon_rate": 0.0380},
    {"instrument_id": "XOM-CB-7Y",   "instrument_name": "Exxon Mobil 7Y Corp Bond",       "issuer_id": "ISS_XOM",  "maturity_date": date(2033, 9, 4), "coupon_rate": 0.0450},
    {"instrument_id": "BAC-CB-5Y",   "instrument_name": "Bank of America 5Y Corp Bond",   "issuer_id": "ISS_BAC",  "maturity_date": date(2031, 9, 4), "coupon_rate": 0.0500},
    {"instrument_id": "JPM-CB-5Y",   "instrument_name": "JPMorgan Chase 5Y Corp Bond",    "issuer_id": "ISS_JPM",  "maturity_date": date(2031, 9, 4), "coupon_rate": 0.0480},
    {"instrument_id": "AAPL-CB-10Y", "instrument_name": "Apple Inc 10Y Corp Bond",        "issuer_id": "ISS_AAPL", "maturity_date": date(2036, 9, 4), "coupon_rate": 0.0430},
    {"instrument_id": "JPM-CB-2Y",   "instrument_name": "JPMorgan Chase 2Y Corp Bond",    "issuer_id": "ISS_JPM",  "maturity_date": date(2028, 9, 4), "coupon_rate": 0.0450},
    {"instrument_id": "JPM-CB-3Y",   "instrument_name": "JPMorgan Chase 3Y Corp Bond",    "issuer_id": "ISS_JPM",  "maturity_date": date(2029, 9, 4), "coupon_rate": 0.0460},
    {"instrument_id": "JPM-CB-10Y",  "instrument_name": "JPMorgan Chase 10Y Corp Bond",   "issuer_id": "ISS_JPM",  "maturity_date": date(2036, 9, 4), "coupon_rate": 0.0500},
    {"instrument_id": "XOM-CB-3Y",   "instrument_name": "Exxon Mobil 3Y Corp Bond",       "issuer_id": "ISS_XOM",  "maturity_date": date(2029, 9, 4), "coupon_rate": 0.0420},
]
corp_bonds = [_fill_defaults(r, asset_class="Corp Bond", underlying_instrument_id=None, currency="USD",
                              base_currency=None, quote_currency=None, strike_price=None,
                              option_type=None, contract_multiplier=None) for r in corp_bonds]

# 4e. FX - no issuer; base/quote currency instead of a single "currency" field
fx = [
    {"instrument_id": "EURUSD", "instrument_name": "Euro / US Dollar Spot",              "base_currency": "EUR", "quote_currency": "USD"},
    {"instrument_id": "GBPUSD", "instrument_name": "British Pound / US Dollar Spot",     "base_currency": "GBP", "quote_currency": "USD"},
    {"instrument_id": "USDJPY", "instrument_name": "US Dollar / Japanese Yen Spot",      "base_currency": "USD", "quote_currency": "JPY"},
    {"instrument_id": "AUDUSD", "instrument_name": "Australian Dollar / US Dollar Spot", "base_currency": "AUD", "quote_currency": "USD"},
    {"instrument_id": "USDCHF", "instrument_name": "US Dollar / Swiss Franc Spot",       "base_currency": "USD", "quote_currency": "CHF"},
    {"instrument_id": "USDCAD", "instrument_name": "US Dollar / Canadian Dollar Spot",   "base_currency": "USD", "quote_currency": "CAD"},
]
fx = [_fill_defaults(r, asset_class="FX", issuer_id=None, underlying_instrument_id=None, currency=None,
                      maturity_date=None, coupon_rate=None, strike_price=None, option_type=None,
                      contract_multiplier=None) for r in fx]

instruments = pd.DataFrame(equities + options + govt_bonds + corp_bonds + fx)[INSTRUMENT_COLUMNS]

# ---------------------------------------------------------------------------
# SECTION 5: Positions - already-netted; one row per (book, instrument, as_of_date)
# ---------------------------------------------------------------------------
position_specs = [
    # Equities desk / US Equity Long-Short book
    ("BK_EQ_LS", "AAPL-EQ", 1_200), ("BK_EQ_LS", "MSFT-EQ", 800), ("BK_EQ_LS", "JPM-EQ", 2_000),
    ("BK_EQ_LS", "XOM-EQ", -1_500), ("BK_EQ_LS", "AMZN-EQ", 500), ("BK_EQ_LS", "GOOGL-EQ", -700),
    ("BK_EQ_LS", "META-EQ", 600), ("BK_EQ_LS", "NVDA-EQ", 900), ("BK_EQ_LS", "BAC-EQ", -1_800),
    ("BK_EQ_LS", "KO-EQ", 2_500),

    # Equities desk / Equity Derivatives book
    ("BK_EQ_DERIV", "AAPL-OPT-C-500-20270130", 50), ("BK_EQ_DERIV", "AAPL-OPT-P-450-20270130", -30),
    ("BK_EQ_DERIV", "JPM-OPT-C-300-20270619", 100), ("BK_EQ_DERIV", "MSFT-OPT-P-380-20261218", 40),
    ("BK_EQ_DERIV", "NVDA-OPT-C-140-20270320", 25), ("BK_EQ_DERIV", "XOM-OPT-P-100-20261120", -20),

    # Fixed Income desk / Rates - Government Bonds book
    ("BK_RATES_GOVT", "UST-GB-2Y", 5_000_000), ("BK_RATES_GOVT", "UST-GB-5Y", 8_000_000),
    ("BK_RATES_GOVT", "UST-GB-10Y", 10_000_000), ("BK_RATES_GOVT", "UST-GB-30Y", -3_000_000),
    ("BK_RATES_GOVT", "UKGILT-GB-5Y", 4_000_000), ("BK_RATES_GOVT", "UKGILT-GB-10Y", 3_000_000),
    ("BK_RATES_GOVT", "BUND-GB-5Y", 6_000_000), ("BK_RATES_GOVT", "BUND-GB-10Y", -2_000_000),

    # Fixed Income desk / Investment Grade Credit book
    ("BK_CREDIT_IG", "AAPL-CB-5Y", 3_000_000), ("BK_CREDIT_IG", "MSFT-CB-5Y", 2_500_000),
    ("BK_CREDIT_IG", "XOM-CB-7Y", 2_000_000), ("BK_CREDIT_IG", "BAC-CB-5Y", 1_500_000),
    ("BK_CREDIT_IG", "JPM-CB-5Y", 4_000_000), ("BK_CREDIT_IG", "AAPL-CB-10Y", 2_000_000),

    # Fixed Income desk / Credit - Concentrated book (deliberately JPM-heavy)
    ("BK_CREDIT_CONC", "JPM-CB-2Y", 12_000_000), ("BK_CREDIT_CONC", "JPM-CB-3Y", 15_000_000),
    ("BK_CREDIT_CONC", "JPM-CB-10Y", 10_000_000), ("BK_CREDIT_CONC", "XOM-CB-3Y", 2_000_000),

    # FX desk / FX Majors book
    ("BK_FX_MAJORS", "EURUSD", 5_000_000), ("BK_FX_MAJORS", "GBPUSD", -3_000_000),
    ("BK_FX_MAJORS", "USDJPY", 10_000_000), ("BK_FX_MAJORS", "AUDUSD", 2_000_000),
    ("BK_FX_MAJORS", "USDCHF", -4_000_000), ("BK_FX_MAJORS", "USDCAD", 6_000_000),
]

positions = pd.DataFrame([
    {
        "position_id": f"POS{i + 1:04d}",
        "as_of_date": AS_OF_DATE,
        "book_id": book_id,
        "instrument_id": instrument_id,
        "quantity": quantity,
    }
    for i, (book_id, instrument_id, quantity) in enumerate(position_specs)
])


# ---------------------------------------------------------------------------
# SECTION 6: Validation
# ---------------------------------------------------------------------------
def validate_portfolio(desks, books, issuers, instruments, positions):
    """Returns a list of human-readable error strings; empty list = all checks passed."""
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    # --- unique primary keys ---
    check(desks["desk_id"].is_unique, "Duplicate desk_id in desks")
    check(books["book_id"].is_unique, "Duplicate book_id in books")
    check(issuers["issuer_id"].is_unique, "Duplicate issuer_id in issuers")
    check(instruments["instrument_id"].is_unique, "Duplicate instrument_id in instruments")
    check(positions["position_id"].is_unique, "Duplicate position_id in positions")

    # --- always-mandatory fields present ---
    check(desks[["desk_id", "desk_name", "asset_class_focus"]].notna().all().all(), "Missing required field in desks")
    check(books[["book_id", "book_name", "desk_id"]].notna().all().all(), "Missing required field in books")
    check(issuers[["issuer_id", "issuer_name", "issuer_type", "country", "credit_rating"]].notna().all().all(),
          "Missing required field in issuers")
    check(instruments[["instrument_id", "instrument_name", "asset_class"]].notna().all().all(),
          "Missing required field in instruments")
    check(positions[["position_id", "as_of_date", "book_id", "instrument_id", "quantity"]].notna().all().all(),
          "Missing required field in positions")

    # --- valid asset classes ---
    allowed_asset_classes = {"Equity", "Equity Option", "Govt Bond", "Corp Bond", "FX"}
    check(set(instruments["asset_class"]).issubset(allowed_asset_classes),
          f"Unexpected asset_class value: {set(instruments['asset_class']) - allowed_asset_classes}")

    # --- foreign keys ---
    check(books["desk_id"].isin(desks["desk_id"]).all(), "books.desk_id references an unknown desk")
    non_null_issuer_refs = instruments["issuer_id"].dropna()
    check(non_null_issuer_refs.isin(issuers["issuer_id"]).all(),
          "instruments.issuer_id references an unknown issuer")
    non_null_underlying = instruments["underlying_instrument_id"].dropna()
    check(non_null_underlying.isin(instruments["instrument_id"]).all(),
          "instruments.underlying_instrument_id references an unknown instrument")
    check(positions["book_id"].isin(books["book_id"]).all(), "positions.book_id references an unknown book")
    check(positions["instrument_id"].isin(instruments["instrument_id"]).all(),
          "positions.instrument_id references an unknown instrument")

    # --- FX / issuer null consistency (schema decision from Module 1 design) ---
    fx_mask = instruments["asset_class"] == "FX"
    check(instruments.loc[fx_mask, "issuer_id"].isna().all(), "FX instruments should have issuer_id = NULL")
    check(instruments.loc[~fx_mask, "issuer_id"].notna().all(), "Non-FX instruments must have an issuer_id")

    # --- sensible signed quantities ---
    check((positions["quantity"] != 0).all(), "A position has zero quantity, which is not a real position")
    check(positions["quantity"].abs().lt(1_000_000_000).all(), "A position quantity looks implausibly large")

    # --- no duplicate (book, instrument, as_of_date) ---
    dup_mask = positions.duplicated(subset=["book_id", "instrument_id", "as_of_date"], keep=False)
    check(not dup_mask.any(), "Duplicate (book_id, instrument_id, as_of_date) combination found in positions")

    return errors


# ---------------------------------------------------------------------------
# SECTION 7: Write CSVs and show samples
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    errors = validate_portfolio(desks, books, issuers, instruments, positions)
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    print(f"All validation checks passed. {len(positions)} positions across "
          f"{positions['book_id'].nunique()} books and {desks.shape[0]} desks.\n")

    tables = {
        "desks": desks, "books": books, "issuers": issuers,
        "instruments": instruments, "positions": positions,
    }
    for name, df in tables.items():
        df.to_csv(f"data/{name}.csv", index=False)

    print("Wrote:", ", ".join(f"data/{name}.csv" for name in tables), "\n")

    for name, df in tables.items():
        print(f"--- {name} sample (first 3 rows) ---")
        print(df.head(3).to_string(index=False))
        print()
