from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class Metrics: mae: float
@dataclass(frozen=True)
class ForecastPoint: time: str; value: float; lower_80: float; upper_80: float
@dataclass(frozen=True)
class ForecastResult:
    target_column: str; time_column: str; test_start: pd.Timestamp; baseline_metrics: Metrics; selected_model: str; selected_metrics: Metrics; is_recommended: bool; prediction_interval_80: list[ForecastPoint]; limitations: list[str]

def forecast(frame: pd.DataFrame, *, time_column: str, target_column: str, horizon: int) -> ForecastResult:
    if horizon < 1 or time_column not in frame or target_column not in frame: raise ValueError("time column, target column, and positive horizon are required")
    data = frame[[time_column, target_column]].copy(); data[time_column] = pd.to_datetime(data[time_column], errors="coerce"); data[target_column] = pd.to_numeric(data[target_column], errors="coerce"); data = data.dropna().sort_values(time_column)
    if len(data) < max(6, horizon + 3) or data[time_column].duplicated().any(): raise ValueError("insufficient clean, unique time-series observations")
    test_size = min(horizon, max(1, len(data) // 4)); train, test = data.iloc[:-test_size], data.iloc[-test_size:]
    y_train, y_test = train[target_column].to_numpy(float), test[target_column].to_numpy(float)
    baseline_values = np.repeat(y_train[-1], test_size); baseline = Metrics(float(np.mean(abs(y_test - baseline_values))))
    coefficients = np.polyfit(np.arange(len(y_train)), y_train, 1); candidate_values = np.polyval(coefficients, np.arange(len(y_train), len(y_train) + test_size)); candidate = Metrics(float(np.mean(abs(y_test - candidate_values))))
    recommended = candidate.mae < baseline.mae; model, metrics = ("linear_trend", candidate) if recommended else ("naive", baseline)
    values = data[target_column].to_numpy(float); future = np.polyval(np.polyfit(np.arange(len(values)), values, 1), np.arange(len(values), len(values) + horizon)) if recommended else np.repeat(values[-1], horizon)
    residual = float(np.std(y_test - (candidate_values if recommended else baseline_values), ddof=0)); spacing = data[time_column].diff().dropna().median()
    points = [ForecastPoint(str(data[time_column].iloc[-1] + spacing * (i + 1)), float(value), float(value - 1.2816 * residual), float(value + 1.2816 * residual)) for i, value in enumerate(future)]
    return ForecastResult(target_column, time_column, pd.Timestamp(test[time_column].iloc[0]), baseline, model, metrics, recommended, points, [] if recommended else ["not better than baseline"])
