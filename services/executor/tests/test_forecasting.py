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
    assert result.baseline_metrics.rmse >= result.baseline_metrics.mae
    assert {"ets", "arima"} <= set(result.candidate_metrics)
    assert len(result.backtest_folds) == 3
    assert all(fold.train_end < fold.test_time for fold in result.backtest_folds)
    assert len(result.prediction_interval_80) == 3
    assert all(point.lower_80 <= point.value <= point.upper_80 for point in result.prediction_interval_80)
    assert result.residual_anomalies == []


def test_forecast_is_not_recommended_when_candidate_loses_to_baseline() -> None:
    frame = pd.DataFrame({
        "month": pd.date_range("2025-01-01", periods=12, freq="MS"),
        "value": [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10],
    })

    result = forecast(frame, time_column="month", target_column="value", horizon=2)

    assert result.is_recommended is False
    assert "not better than baseline" in result.limitations


def test_forecast_reports_residual_anomalies_from_time_ordered_backtest() -> None:
    frame = pd.DataFrame({
        "month": pd.date_range("2024-01-01", periods=18, freq="MS"),
        "value": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 80, 27],
    })

    result = forecast(frame, time_column="month", target_column="value", horizon=3)

    assert result.residual_anomalies
    assert result.residual_anomalies[0].time.startswith("2025-05")
