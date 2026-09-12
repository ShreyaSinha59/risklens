"""
Module 7b: Data Quality / Reconciliation Controls

Row-level controls (duplicates, missing fields, invalid mappings, missing/
stale market data, outliers, position-count recon) are demonstrated on a
DEMO dataset with deliberately injected bad records - the real portfolio
files are never modified. Aggregate controls (market-value recon, P&L
recon) require successful valuation, so they're demonstrated against the
real, clean portfolio instead (see explanation).
"""

from datetime import timedelta

import pandas as pd

from valuation import AS_OF_DATE, latest_levels_as_of, levels_dict, nearest_tenor_risk_factor, value_positions
from var_es import build_complete_scenario_dates, shock_levels


# ---------------------------------------------------------------------------
# Demo dataset with deliberately injected issues (real files untouched)
# ---------------------------------------------------------------------------
def build_demo_dataset(positions, levels):
    demo_positions = positions.copy()

    dup_row = demo_positions.iloc[0].copy()
    dup_row["position_id"] = "POS9001"  # duplicate of an existing (book, instrument, as_of_date)
    demo_positions = pd.concat([demo_positions, pd.DataFrame([dup_row])], ignore_index=True)

    demo_positions = pd.concat([demo_positions, pd.DataFrame([{
        # BK_EQ_DERIV doesn't hold AAPL-EQ directly (only options on it), so this
        # doesn't collide with an existing (book, instrument, as_of_date) triple
        "position_id": "POS9002", "as_of_date": AS_OF_DATE.isoformat(),
        "book_id": "BK_EQ_DERIV", "instrument_id": "AAPL-EQ", "quantity": None,  # missing required field
    }])], ignore_index=True)

    demo_positions = pd.concat([demo_positions, pd.DataFrame([{
        "position_id": "POS9003", "as_of_date": AS_OF_DATE.isoformat(),
        "book_id": "BK_EQ_LS", "instrument_id": "FAKE-EQ-999", "quantity": 100,  # invalid mapping
    }])], ignore_index=True)

    demo_levels = levels.copy()
    # Missing market data: drop EVERY observation for one risk factor (not just the latest),
    # so it's genuinely absent from the "available" set, not merely stale-by-one-day.
    demo_levels = demo_levels[demo_levels["risk_factor_id"] != "NVDA-VOL"].reset_index(drop=True)

    dates = pd.to_datetime(demo_levels["date"]).dt.date
    stale_cutoff = AS_OF_DATE - timedelta(days=20)
    demo_levels = demo_levels[~((demo_levels["risk_factor_id"] == "JPM-EQ") & (dates > stale_cutoff))].reset_index(drop=True)  # stale

    dates = pd.to_datetime(demo_levels["date"]).dt.date  # recompute after prior filters
    xom_latest = dates[demo_levels["risk_factor_id"] == "XOM-EQ"].max()
    demo_levels = demo_levels[~((demo_levels["risk_factor_id"] == "XOM-EQ") & (dates == xom_latest))]
    demo_levels = pd.concat([demo_levels, pd.DataFrame([{
        "date": xom_latest.isoformat(), "risk_factor_id": "XOM-EQ",
        "risk_factor_type": "Equity Price", "value": 50_000.0,  # outlier
    }])], ignore_index=True)

    return demo_positions, demo_levels


# ---------------------------------------------------------------------------
# Row-level controls
# ---------------------------------------------------------------------------
def control_duplicate_positions(positions):
    dupes = positions[positions.duplicated(subset=["book_id", "instrument_id", "as_of_date"], keep=False)]
    return {"control": "Duplicate Positions", "status": "FAIL" if len(dupes) else "PASS",
            "severity": "High", "details": dupes["position_id"].tolist()}


def control_missing_required_fields(positions):
    required = ["position_id", "as_of_date", "book_id", "instrument_id", "quantity"]
    bad = positions[positions[required].isna().any(axis=1)]
    return {"control": "Missing Required Fields", "status": "FAIL" if len(bad) else "PASS",
            "severity": "High", "details": bad["position_id"].tolist()}


def control_invalid_mappings(positions, instruments):
    bad = positions[~positions["instrument_id"].isin(instruments["instrument_id"])]
    return {"control": "Invalid Instrument Mapping", "status": "FAIL" if len(bad) else "PASS",
            "severity": "High", "details": bad[["position_id", "instrument_id"]].to_dict("records")}


def control_missing_market_data(positions, instruments, levels, as_of_date=AS_OF_DATE):
    latest = latest_levels_as_of(levels, as_of_date)
    available = set(latest["risk_factor_id"])
    inst_by_id = instruments.set_index("instrument_id").to_dict("index")
    missing = []
    for pos in positions.itertuples():
        inst = inst_by_id.get(pos.instrument_id)
        if inst is None:
            continue  # caught by control_invalid_mappings
        ac = inst["asset_class"]
        required = []
        if ac in ("Equity", "FX"):
            required = [pos.instrument_id]
        elif ac in ("Govt Bond", "Corp Bond"):
            years = (pd.Timestamp(inst["maturity_date"]).date() - as_of_date).days / 365.25
            currency = inst["currency"] if ac == "Govt Bond" else "USD"
            required = [nearest_tenor_risk_factor(currency, years)]
            if ac == "Corp Bond":
                required.append(f"{inst['issuer_id']}-CS")
        elif ac == "Equity Option":
            underlying = inst["underlying_instrument_id"]
            years = (pd.Timestamp(inst["maturity_date"]).date() - as_of_date).days / 365.25
            required = [underlying, f"{underlying.replace('-EQ', '')}-VOL", nearest_tenor_risk_factor("USD", years)]
        for rf in required:
            if rf not in available:
                missing.append({"position_id": pos.position_id, "missing_risk_factor": rf})
    return {"control": "Missing Market Data", "status": "FAIL" if missing else "PASS",
            "severity": "High", "details": missing}


def control_stale_market_data(levels, as_of_date=AS_OF_DATE, threshold_days=10):
    last_dates = pd.to_datetime(levels.groupby("risk_factor_id")["date"].max()).dt.date
    gap_days = last_dates.apply(lambda d: (as_of_date - d).days)
    stale = gap_days[gap_days > threshold_days]
    return {"control": "Stale Market Data", "status": "WARN" if len(stale) else "PASS",
            "severity": "Medium", "details": {k: f"{v} days old" for k, v in stale.items()}}


def control_outlier_values(levels, z_threshold=4.0):
    outliers = []
    for rf_id, group in levels.sort_values("date").groupby("risk_factor_id"):
        if len(group) < 31:
            continue
        history, latest_value = group.iloc[:-1]["value"], group.iloc[-1]["value"]
        mean, std = history.mean(), history.std()
        if std == 0:
            continue
        z = (latest_value - mean) / std
        if abs(z) > z_threshold:
            outliers.append({"risk_factor_id": rf_id, "z_score": round(z, 2), "latest_value": latest_value})
    return {"control": "Outlier Values", "status": "FAIL" if outliers else "PASS",
            "severity": "Medium", "details": outliers}


def control_position_count_reconciliation(positions, expected_count):
    actual = len(positions)
    return {"control": "Position Count Reconciliation", "status": "PASS" if actual == expected_count else "FAIL",
            "severity": "Medium", "details": f"expected {expected_count}, actual {actual}"}


# ---------------------------------------------------------------------------
# Aggregate controls (need successful valuation - run on the real, clean portfolio)
# ---------------------------------------------------------------------------
def control_market_value_reconciliation(positions, instruments, levels, tolerance=1.0):
    latest = latest_levels_as_of(levels, AS_OF_DATE)
    fresh = value_positions(
        positions, instruments, levels_dict(latest, "FX Spot"), levels_dict(latest, "Equity Price"),
        levels_dict(latest, "Yield"), levels_dict(latest, "Credit Spread"),
        levels_dict(latest, "Implied Vol (Realized Proxy)"))
    fresh_total = fresh["market_value_usd"].sum()
    persisted_total = pd.read_csv("data/processed/position_valuations.csv")["market_value_usd"].sum()
    diff = abs(fresh_total - persisted_total)
    return {"control": "Market Value Reconciliation (fresh recompute vs persisted)",
            "status": "PASS" if diff <= tolerance else "FAIL", "severity": "High",
            "details": f"fresh=${fresh_total:,.2f}, persisted=${persisted_total:,.2f}, diff=${diff:,.2f}"}


def control_pnl_reconciliation(positions, instruments, levels, changes, tolerance=1.0):
    latest = latest_levels_as_of(levels, AS_OF_DATE)
    baseline = value_positions(
        positions, instruments, levels_dict(latest, "FX Spot"), levels_dict(latest, "Equity Price"),
        levels_dict(latest, "Yield"), levels_dict(latest, "Credit Spread"),
        levels_dict(latest, "Implied Vol (Realized Proxy)"))
    complete = build_complete_scenario_dates(changes)
    shocked = shock_levels(latest, complete.loc[complete.index[-1]])
    shocked_valued = value_positions(
        positions, instruments, levels_dict(shocked, "FX Spot"), levels_dict(shocked, "Equity Price"),
        levels_dict(shocked, "Yield"), levels_dict(shocked, "Credit Spread"),
        levels_dict(shocked, "Implied Vol (Realized Proxy)"))
    position_pnls = shocked_valued.set_index("position_id")["market_value_usd"] - \
                    baseline.set_index("position_id")["market_value_usd"]
    bottom_up = position_pnls.sum()
    top_down = shocked_valued["market_value_usd"].sum() - baseline["market_value_usd"].sum()
    diff = abs(bottom_up - top_down)
    return {"control": "P&L Reconciliation (bottom-up vs top-down)",
            "status": "PASS" if diff <= tolerance else "FAIL", "severity": "Medium",
            "details": f"sum of position P&Ls=${bottom_up:,.2f}, portfolio P&L=${top_down:,.2f}, diff=${diff:,.2f}"}


def run_all_controls(positions, instruments, levels, changes, expected_count):
    results = [
        control_duplicate_positions(positions),
        control_missing_required_fields(positions),
        control_invalid_mappings(positions, instruments),
        control_missing_market_data(positions, instruments, levels),
        control_stale_market_data(levels),
        control_outlier_values(levels),
        control_position_count_reconciliation(positions, expected_count),
        control_market_value_reconciliation(positions, instruments, levels),
        control_pnl_reconciliation(positions, instruments, levels, changes),
    ]
    return pd.DataFrame(results)


def print_control_results(df, title):
    print(f"=== {title} ===")
    for row in df.itertuples():
        detail = row.details if not isinstance(row.details, (list, dict)) else (
            f"{len(row.details)} exception(s)" if row.details else "none")
        print(f"[{row.status:<4}] ({row.severity:<6}) {row.control:<50} {detail}")
    print()


if __name__ == "__main__":
    positions = pd.read_csv("data/positions.csv")
    instruments = pd.read_csv("data/instruments.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")
    changes = pd.read_csv("data/processed/risk_factor_changes.csv")

    demo_positions, demo_levels = build_demo_dataset(positions, levels)
    demo_results = pd.DataFrame([
        control_duplicate_positions(demo_positions),
        control_missing_required_fields(demo_positions),
        control_invalid_mappings(demo_positions, instruments),
        control_missing_market_data(demo_positions, instruments, demo_levels),
        control_stale_market_data(demo_levels),
        control_outlier_values(demo_levels),
        control_position_count_reconciliation(demo_positions, expected_count=len(positions)),
    ])
    print_control_results(demo_results, "Demo dataset (deliberately injected issues)")

    clean_results = run_all_controls(positions, instruments, levels, changes, expected_count=len(positions))
    print_control_results(clean_results, "Real portfolio (clean)")

    assert (demo_results["status"] != "PASS").sum() >= 6, "Demo dataset should trip most controls"
    assert (clean_results["status"] == "PASS").all(), "Real portfolio should pass every control"
    print("Sanity checks passed: demo data trips the controls; real portfolio passes all of them.")
