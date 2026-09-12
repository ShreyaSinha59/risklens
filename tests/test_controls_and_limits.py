import pandas as pd
import pytest

from data_quality import control_duplicate_positions, control_missing_market_data, build_demo_dataset
from risk_limits import classify_status, compute_limit_utilization


@pytest.mark.unit
def test_duplicate_position_detection_flags_the_duplicate():
    positions = pd.DataFrame([
        {"position_id": "P1", "as_of_date": "2026-09-04", "book_id": "BK1", "instrument_id": "X", "quantity": 100},
        {"position_id": "P2", "as_of_date": "2026-09-04", "book_id": "BK1", "instrument_id": "X", "quantity": 100},
    ])
    result = control_duplicate_positions(positions)
    assert result["status"] == "FAIL"
    assert set(result["details"]) == {"P1", "P2"}


@pytest.mark.unit
def test_duplicate_position_detection_passes_clean_data(ref_data):
    from data_quality import control_duplicate_positions as check
    result = check(ref_data["positions"])
    assert result["status"] == "PASS"


@pytest.mark.integration
def test_missing_market_data_detection_on_injected_demo(ref_data):
    demo_positions, demo_levels = build_demo_dataset(ref_data["positions"], ref_data["levels"])
    result = control_missing_market_data(demo_positions, ref_data["instruments"], demo_levels)
    assert result["status"] == "FAIL"
    assert len(result["details"]) > 0


@pytest.mark.unit
@pytest.mark.parametrize("utilization,warning_pct,expected", [
    (1.20, 0.80, "RED"),
    (0.99, 0.80, "AMBER"),
    (0.85, 0.80, "AMBER"),
    (0.50, 0.80, "GREEN"),
])
def test_classify_status_thresholds(utilization, warning_pct, expected):
    assert classify_status(utilization, warning_pct) == expected


@pytest.mark.integration
@pytest.mark.regression
def test_jpm_issuer_concentration_breach_is_detected(ref_data):
    # locks in Module 1's deliberate design: JPM concentration should still
    # be flagged RED unless the portfolio/limit config is intentionally changed
    summary = compute_limit_utilization(ref_data["positions"], ref_data["instruments"], ref_data["levels"])
    jpm_row = summary[summary["scope_value"] == "JPMorgan Chase & Co"].iloc[0]
    assert jpm_row["status"] == "RED"
    assert jpm_row["utilization_pct"] > 100
