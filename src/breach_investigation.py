"""
Module 7c: Breach Investigation Workflow

Runs against the real, clean portfolio (Part B already demonstrated the
controls catching bad data on a separate demo dataset). This step exists to
show the SAME controls clearing a real breach before we trust it as genuine
risk, not a data artifact.
"""

import pandas as pd

from valuation import AS_OF_DATE, latest_levels_as_of, levels_dict, value_positions
from var_es import build_complete_scenario_dates, shock_levels
from data_quality import run_all_controls
from risk_limits import compute_limit_utilization


def investigate_breach(breach, positions, instruments, issuers, books, desks, levels, changes, valuations):
    print("BREACH DETECTED")
    print(f"{breach.metric} - {breach.scope}: {breach.scope_value}")
    print(f"${breach.actual_value:,.0f} vs ${breach.limit_value:,.0f} limit "
          f"({breach.utilization_pct:.1f}% utilization)\n")

    # Step 1-2: data quality + reconciliation
    dq = run_all_controls(positions, instruments, levels, changes, expected_count=len(positions))
    dq_pass = (dq["status"] == "PASS").all()
    recon = dq[dq["control"].str.contains("Reconciliation")]
    recon_pass = (recon["status"] == "PASS").all()
    print(f"Data Quality: {'PASS' if dq_pass else 'FAIL - see data_quality.py output'}")
    print(f"Position/Value/P&L Reconciliation: {'PASS' if recon_pass else 'FAIL'}\n")

    # Step 3: prior vs current exposure (positions are a single daily snapshot in this
    # project - see Module 1 - so "prior" means the SAME positions marked at yesterday's
    # market levels, isolating whether a recent market move drove the breach)
    issuer_positions = valuations.dropna(subset=["issuer_id"]).merge(issuers, on="issuer_id")
    issuer_positions = issuer_positions[issuer_positions["issuer_name"] == breach.scope_value]
    current_exposure = issuer_positions["market_value_usd"].abs().sum()

    latest = latest_levels_as_of(levels, AS_OF_DATE)
    complete = build_complete_scenario_dates(changes)
    prior_date = complete.index[-1]
    prior_levels = shock_levels(latest, complete.loc[prior_date])
    prior_valued = value_positions(
        positions, instruments, levels_dict(prior_levels, "FX Spot"), levels_dict(prior_levels, "Equity Price"),
        levels_dict(prior_levels, "Yield"), levels_dict(prior_levels, "Credit Spread"),
        levels_dict(prior_levels, "Implied Vol (Realized Proxy)"))
    prior_issuer = prior_valued.dropna(subset=["issuer_id"]).merge(issuers, on="issuer_id")
    prior_exposure = prior_issuer[prior_issuer["issuer_name"] == breach.scope_value]["market_value_usd"].abs().sum()

    pct_change = 100 * (current_exposure - prior_exposure) / prior_exposure
    print(f"Prior Exposure (positions marked at {prior_date} levels): ${prior_exposure:,.0f}")
    print(f"Current Exposure (today):                                  ${current_exposure:,.0f}  ({pct_change:+.2f}%)")
    driven_by_market = abs(pct_change) > 2.0
    print(f"-> {'Notable recent market move' if driven_by_market else 'Positions unchanged, exposure essentially flat day-over-day: this is a STRUCTURAL concentration, not a recent market spike'}\n")

    # Step 4: largest contributors
    contributors = issuer_positions.merge(positions[["position_id", "book_id"]].drop_duplicates(),
                                           on="position_id", suffixes=("", "_p")) \
                                    .merge(books, on="book_id").merge(desks, on="desk_id")
    contributors = contributors.reindex(contributors["market_value_usd"].abs().sort_values(ascending=False).index)
    print("Primary Contributors:")
    print(contributors[["instrument_id", "desk_name", "book_id", "market_value_usd"]].head(5).to_string(index=False))
    top_book = contributors.iloc[0]["book_id"]
    top_desk = contributors.iloc[0]["desk_name"]

    # Step 5: market drivers - check the risk factors tied to this issuer on the most recent date
    changes_at_date = changes[changes["date"] == prior_date].set_index("risk_factor_id")
    issuer_id = issuer_positions["issuer_id"].iloc[0]
    spread_rf = f"{issuer_id}-CS"
    equity_rf = f"{issuer_id.replace('ISS_', '')}-EQ"
    print("\nMarket Drivers (most recent day):")
    if spread_rf in changes_at_date.index:
        print(f"  {spread_rf}: {changes_at_date.loc[spread_rf, 'change']:+.1f} bp")
    if equity_rf in changes_at_date.index:
        print(f"  {equity_rf}: {changes_at_date.loc[equity_rf, 'change']*100:+.2f}% (log return)")

    # Step 6: preliminary conclusion
    print("\nPreliminary Assessment:")
    if dq_pass and recon_pass and not driven_by_market:
        print(f"Likely a genuine, STRUCTURAL single-issuer concentration breach driven by position sizing "
              f"in {top_desk} / {top_book}, not a data quality issue or a sudden adverse market move.")
        print("Recommend desk-level review of the concentrated holdings and consideration of a position "
              "reduction or a formal limit waiver request.")
    elif not dq_pass or not recon_pass:
        print("Data quality or reconciliation issues were found - investigate those BEFORE treating this "
              "breach as a genuine risk event.")
    else:
        print("Exposure moved materially with the market - likely a genuine, market-driven risk increase.")


if __name__ == "__main__":
    desks = pd.read_csv("data/desks.csv")
    books = pd.read_csv("data/books.csv")
    issuers = pd.read_csv("data/issuers.csv")
    instruments = pd.read_csv("data/instruments.csv")
    positions = pd.read_csv("data/positions.csv")
    levels = pd.read_csv("data/processed/risk_factor_levels.csv")
    changes = pd.read_csv("data/processed/risk_factor_changes.csv")
    valuations = pd.read_csv("data/processed/position_valuations.csv")

    limits = compute_limit_utilization(positions, instruments, levels)
    breach = limits[limits["status"] == "RED"].iloc[0]

    investigate_breach(breach, positions, instruments, issuers, books, desks, levels, changes, valuations)
