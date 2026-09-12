"""
Module 8: Educational FRTB Risk Class Mapping

DISCLAIMER: this is an educational mapping/explorer layer only. It labels
our existing positions and existing Module 5 sensitivities with the FRTB
risk class they would conceptually fall under. It does NOT implement risk
weights, correlations, bucket aggregation, the three correlation scenarios,
DRC, RRAO, or any other part of the Sensitivities-Based Method capital
formula, and produces NO regulatory capital number. Nothing here should be
read as, or used as, an actual capital calculation.

A corporate bond deliberately produces two rows (GIRR + Credit Spread Risk)
and an equity option three rows (Delta/Vega/Curvature, all under Equity
Risk) - this mirrors how FRTB genuinely decomposes one instrument's risk
across multiple components, reusing exactly the DV01/CS01/Delta/Gamma/Vega
already computed in Module 5.
"""

import pandas as pd
import psycopg2

from valuation import AS_OF_DATE, nearest_tenor_risk_factor
from run_eod_pipeline import DB_DSN, upsert_df

DISCLAIMER = (
    "EDUCATIONAL FRTB MAPPING ONLY - no risk weights, correlations, DRC, RRAO, "
    "or capital calculation are implemented. Not a regulatory capital engine."
)


def build_frtb_explorer(positions, instruments, sensitivities):
    inst_by_id = instruments.set_index("instrument_id").to_dict("index")
    sens_by_pos = sensitivities.set_index("position_id").to_dict("index")
    rows = []

    for pos in positions.itertuples():
        inst = inst_by_id[pos.instrument_id]
        s = sens_by_pos[pos.position_id]
        ac = inst["asset_class"]
        base = {"position_id": pos.position_id, "instrument_id": pos.instrument_id, "asset_class": ac}

        if ac == "Equity":
            rows.append({**base, "frtb_risk_class": "Equity Risk", "risk_factor": pos.instrument_id,
                         "sensitivity_type": "Delta", "sensitivity_value": s["Delta"]})

        elif ac == "Equity Option":
            underlying = inst["underlying_instrument_id"]
            vol_rf = f"{underlying.replace('-EQ', '')}-VOL"
            rows.append({**base, "frtb_risk_class": "Equity Risk", "risk_factor": underlying,
                         "sensitivity_type": "Delta", "sensitivity_value": s["Delta"]})
            rows.append({**base, "frtb_risk_class": "Equity Risk", "risk_factor": vol_rf,
                         "sensitivity_type": "Vega", "sensitivity_value": s["Vega"]})
            rows.append({**base, "frtb_risk_class": "Equity Risk", "risk_factor": underlying,
                         "sensitivity_type": "Curvature (proxy: Gamma)", "sensitivity_value": s["Gamma"]})

        elif ac == "Govt Bond":
            years = (pd.Timestamp(inst["maturity_date"]).date() - AS_OF_DATE).days / 365.25
            rf = nearest_tenor_risk_factor(inst["currency"], years)
            rows.append({**base, "frtb_risk_class": "GIRR", "risk_factor": rf,
                         "sensitivity_type": "DV01", "sensitivity_value": s["DV01"]})

        elif ac == "Corp Bond":
            years = (pd.Timestamp(inst["maturity_date"]).date() - AS_OF_DATE).days / 365.25
            rate_rf = nearest_tenor_risk_factor("USD", years)
            spread_rf = f"{inst['issuer_id']}-CS"
            rows.append({**base, "frtb_risk_class": "GIRR", "risk_factor": rate_rf,
                         "sensitivity_type": "DV01", "sensitivity_value": s["DV01"]})
            rows.append({**base, "frtb_risk_class": "Credit Spread Risk", "risk_factor": spread_rf,
                         "sensitivity_type": "CS01", "sensitivity_value": s["CS01"]})

        elif ac == "FX":
            # FX Delta wasn't computed in Module 5 (out of that module's scope) - defined fresh
            # here exactly as in Module 6's P&L attribution: quantity for quote_currency == USD
            # pairs, 0 for base_currency == USD pairs (USD value is rate-invariant there).
            fx_delta = pos.quantity if inst["quote_currency"] == "USD" else 0.0
            rows.append({**base, "frtb_risk_class": "FX Risk", "risk_factor": pos.instrument_id,
                         "sensitivity_type": "FX Delta", "sensitivity_value": fx_delta})

    return pd.DataFrame(rows)


if __name__ == "__main__":
    print(DISCLAIMER, "\n")

    positions = pd.read_csv("data/positions.csv")
    instruments = pd.read_csv("data/instruments.csv")
    sensitivities = pd.read_csv("data/processed/position_sensitivities.csv")

    explorer = build_frtb_explorer(positions, instruments, sensitivities)
    explorer.to_csv("data/processed/frtb_mapping.csv", index=False)

    print("=== Sample rows ===")
    print(explorer.head(8).to_string(index=False))

    print("\n=== Position/row count by FRTB risk class ===")
    print(explorer.groupby("frtb_risk_class").size().rename("rows"))

    print("\n=== Corp bond example: two risk classes from one instrument ===")
    print(explorer[explorer["instrument_id"] == "JPM-CB-5Y"].to_string(index=False))

    print("\n=== Equity option example: three components from one instrument ===")
    print(explorer[explorer["instrument_id"] == "AAPL-OPT-C-500-20270130"].to_string(index=False))

    n_positions = positions["position_id"].nunique()
    n_mapped = explorer["position_id"].nunique()
    assert n_mapped == n_positions, "Every position should appear at least once in the FRTB explorer"
    print(f"\nSanity check passed: all {n_positions} positions appear in the mapping "
          f"({len(explorer)} total risk-class rows, since bonds/options produce more than one row each).")

    to_persist = explorer.rename(columns={"sensitivity_value": "sensitivity_value"}).copy()
    to_persist["as_of_date"] = AS_OF_DATE
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                upsert_df(cur, "frtb_mapping", to_persist,
                          ["as_of_date", "position_id", "frtb_risk_class", "sensitivity_type"])
    finally:
        conn.close()
    print(f"Persisted {len(to_persist)} rows to frtb_mapping table.")
