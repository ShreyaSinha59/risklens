import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from valuation import AS_OF_DATE, latest_levels_as_of, levels_dict, value_positions  # noqa: E402


@pytest.fixture(scope="session")
def ref_data():
    return {
        "desks": pd.read_csv(ROOT / "data/desks.csv"),
        "books": pd.read_csv(ROOT / "data/books.csv"),
        "issuers": pd.read_csv(ROOT / "data/issuers.csv"),
        "instruments": pd.read_csv(ROOT / "data/instruments.csv"),
        "positions": pd.read_csv(ROOT / "data/positions.csv"),
        "levels": pd.read_csv(ROOT / "data/processed/risk_factor_levels.csv"),
        "changes": pd.read_csv(ROOT / "data/processed/risk_factor_changes.csv"),
    }


@pytest.fixture(scope="session")
def latest_levels(ref_data):
    return latest_levels_as_of(ref_data["levels"], AS_OF_DATE)


@pytest.fixture(scope="session")
def level_dicts(latest_levels):
    return {
        "price": levels_dict(latest_levels, "Equity Price"),
        "fx": levels_dict(latest_levels, "FX Spot"),
        "yield": levels_dict(latest_levels, "Yield"),
        "spread": levels_dict(latest_levels, "Credit Spread"),
        "vol": levels_dict(latest_levels, "Implied Vol (Realized Proxy)"),
    }


@pytest.fixture(scope="session")
def baseline_valued(ref_data, level_dicts):
    return value_positions(
        ref_data["positions"], ref_data["instruments"], level_dicts["fx"], level_dicts["price"],
        level_dicts["yield"], level_dicts["spread"], level_dicts["vol"])


@pytest.fixture(scope="session")
def scenario_pnls():
    path = ROOT / "data/processed/scenario_pnls.csv"
    if not path.exists():
        pytest.skip("scenario_pnls.csv not generated yet - run src/var_es.py first")
    return pd.read_csv(path, index_col=0)["pnl"]
