import pandas as pd

from executor.forecasting import forecast


def test_forecast_holds_out_latest_observations() -> None:
    frame = pd.DataFrame({
        "month": pd.date_range("2025-01-01", periods=12, freq="MS"),
        "revenue": [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32],
    })

    result = forecast(frame, time_column="month", target_column="revenue", horizon=3)

    assert result.test_start > frame["month"].iloc[-4]
    assert result.baseline_metrics.mae >= 0
    assert len(result.prediction_interval_80) == 3


def test_forecast_is_not_recommended_when_candidate_loses_to_baseline() -> None:
    frame = pd.DataFrame({
        "month": pd.date_range("2025-01-01", periods=12, freq="MS"),
        "value": [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10],
    })

    result = forecast(frame, time_column="month", target_column="value", horizon=2)

    assert result.is_recommended is False
    assert "not better than baseline" in result.limitations
