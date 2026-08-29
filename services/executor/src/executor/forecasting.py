from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from warnings import catch_warnings, simplefilter

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing


@dataclass(frozen=True)
class Metrics:
    mae: float
    rmse: float


@dataclass(frozen=True)
class ForecastPoint:
    time: str
    value: float
    lower_80: float
    upper_80: float


@dataclass(frozen=True)
class BacktestFold:
    train_end: pd.Timestamp
    test_time: pd.Timestamp
    actual: float
    predictions: dict[str, float]


@dataclass(frozen=True)
class ResidualAnomaly:
    time: str
    actual: float
    predicted: float
    residual: float
    robust_score: float


@dataclass(frozen=True)
class ForecastResult:
    target_column: str
    time_column: str
    test_start: pd.Timestamp
    baseline_model: str
    baseline_metrics: Metrics
    candidate_metrics: dict[str, Metrics]
    selected_model: str
    selected_metrics: Metrics
    is_recommended: bool
    backtest_folds: list[BacktestFold]
    prediction_interval_80: list[ForecastPoint]
    residual_anomalies: list[ResidualAnomaly]
    limitations: list[str]


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> Metrics:
    errors = actual - predicted
    return Metrics(
        mae=float(np.mean(np.abs(errors))),
        rmse=float(sqrt(float(np.mean(np.square(errors))))),
    )


def _seasonal_period(times: pd.Series) -> int | None:
    inferred = pd.infer_freq(pd.DatetimeIndex(times))
    if inferred is None:
        return None
    normalized = inferred.upper()
    if normalized.startswith(("M", "ME")):
        return 12
    if normalized.startswith("Q"):
        return 4
    if normalized.startswith("W"):
        return 52
    if normalized.startswith("D"):
        return 7
    return None


def _baseline_predictions(train: np.ndarray, period: int | None) -> dict[str, float]:
    predictions = {"naive": float(train[-1])}
    if period is not None and len(train) >= period:
        predictions["seasonal_naive"] = float(train[-period])
    return predictions


def _ets_one_step(train: np.ndarray) -> float:
    with catch_warnings():
        simplefilter("ignore")
        fitted = ExponentialSmoothing(
            train,
            trend="add" if len(train) >= 4 else None,
            initialization_method="estimated",
        ).fit(optimized=True)
    return float(np.asarray(fitted.forecast(1))[0])


def _arima_one_step(train: np.ndarray) -> float:
    with catch_warnings():
        simplefilter("ignore")
        fitted = ARIMA(train, order=(1, 1, 1), trend="t").fit()
    return float(np.asarray(fitted.forecast(1))[0])


def _candidate_predictions(train: np.ndarray, fallback: float) -> tuple[dict[str, float], list[str]]:
    predictions: dict[str, float] = {}
    limitations: list[str] = []
    for name, predictor in (("ets", _ets_one_step), ("arima", _arima_one_step)):
        try:
            prediction = predictor(train)
            if not np.isfinite(prediction):
                raise ValueError("non-finite prediction")
        except (ValueError, RuntimeError, np.linalg.LinAlgError) as error:
            prediction = fallback
            limitations.append(f"{name} backtest fallback: {type(error).__name__}")
        predictions[name] = float(prediction)
    return predictions, limitations


def _future_times(times: pd.Series, horizon: int) -> list[pd.Timestamp]:
    inferred = pd.infer_freq(pd.DatetimeIndex(times))
    if inferred:
        return [pd.Timestamp(item) for item in pd.date_range(times.iloc[-1], periods=horizon + 1, freq=inferred)[1:]]
    spacing = times.diff().dropna().median()
    if pd.isna(spacing) or spacing <= pd.Timedelta(0):
        raise ValueError("time observations must have a positive interval")
    return [pd.Timestamp(times.iloc[-1] + spacing * step) for step in range(1, horizon + 1)]


def _future_values(model: str, values: np.ndarray, horizon: int, period: int | None) -> np.ndarray:
    if model == "naive":
        return np.repeat(values[-1], horizon).astype(float)
    if model == "seasonal_naive" and period is not None and len(values) >= period:
        return np.asarray([values[-period + (step % period)] for step in range(horizon)], dtype=float)
    with catch_warnings():
        simplefilter("ignore")
        if model == "ets":
            fitted = ExponentialSmoothing(values, trend="add", initialization_method="estimated").fit(optimized=True)
        elif model == "arima":
            fitted = ARIMA(values, order=(1, 1, 1), trend="t").fit()
        else:
            raise ValueError(f"unsupported forecast model: {model}")
    return np.asarray(fitted.forecast(horizon), dtype=float)


def _residual_anomalies(folds: list[BacktestFold], model: str) -> list[ResidualAnomaly]:
    residuals = np.asarray([fold.actual - fold.predictions[model] for fold in folds], dtype=float)
    center = float(np.median(residuals))
    mad = float(np.median(np.abs(residuals - center)))
    numerical_tolerance = max(max(abs(fold.actual) for fold in folds) * 1e-6, 1e-9)
    if mad == 0:
        scores = np.where(np.isclose(residuals, center), 0.0, np.inf)
    else:
        scores = 0.6745 * np.abs(residuals - center) / mad
    return [
        ResidualAnomaly(
            time=fold.test_time.isoformat(),
            actual=fold.actual,
            predicted=fold.predictions[model],
            residual=float(residual),
            robust_score=float(score),
        )
        for fold, residual, score in zip(folds, residuals, scores, strict=True)
        if score >= 2.5 and abs(residual - center) > numerical_tolerance
    ]


def forecast(
    frame: pd.DataFrame,
    *,
    time_column: str,
    target_column: str,
    horizon: int,
) -> ForecastResult:
    if horizon < 1 or time_column not in frame or target_column not in frame:
        raise ValueError("time column, target column, and positive horizon are required")
    data = frame[[time_column, target_column]].copy()
    data[time_column] = pd.to_datetime(data[time_column], errors="coerce")
    data[target_column] = pd.to_numeric(data[target_column], errors="coerce")
    data = data.dropna().sort_values(time_column).reset_index(drop=True)
    if len(data) < max(8, horizon + 5) or data[time_column].duplicated().any():
        raise ValueError("insufficient clean, unique time-series observations")

    test_size = min(horizon, max(1, len(data) // 4))
    first_test = len(data) - test_size
    period = _seasonal_period(data[time_column])
    folds: list[BacktestFold] = []
    limitations: list[str] = []
    for test_index in range(first_test, len(data)):
        train = data[target_column].iloc[:test_index].to_numpy(dtype=float)
        baselines = _baseline_predictions(train, period)
        candidates, candidate_limitations = _candidate_predictions(train, baselines["naive"])
        limitations.extend(candidate_limitations)
        folds.append(BacktestFold(
            train_end=pd.Timestamp(data[time_column].iloc[test_index - 1]),
            test_time=pd.Timestamp(data[time_column].iloc[test_index]),
            actual=float(data[target_column].iloc[test_index]),
            predictions={**baselines, **candidates},
        ))

    actual = np.asarray([fold.actual for fold in folds], dtype=float)
    model_names = sorted(set.intersection(*(set(fold.predictions) for fold in folds)))
    model_metrics = {
        name: _metrics(actual, np.asarray([fold.predictions[name] for fold in folds], dtype=float))
        for name in model_names
    }
    baseline_model = min(
        (name for name in model_metrics if name in {"naive", "seasonal_naive"}),
        key=lambda name: (model_metrics[name].mae, model_metrics[name].rmse),
    )
    candidate_metrics = {name: model_metrics[name] for name in ("ets", "arima")}
    best_candidate = min(candidate_metrics, key=lambda name: (candidate_metrics[name].mae, candidate_metrics[name].rmse))
    baseline_metrics = model_metrics[baseline_model]
    candidate_is_better = candidate_metrics[best_candidate].mae < baseline_metrics.mae - 1e-9
    selected_model = best_candidate if candidate_is_better else baseline_model
    selected_metrics = model_metrics[selected_model]
    if not candidate_is_better:
        limitations.append("not better than baseline")

    values = data[target_column].to_numpy(dtype=float)
    future_values = _future_values(selected_model, values, horizon, period)
    residuals = actual - np.asarray([fold.predictions[selected_model] for fold in folds], dtype=float)
    residual_scale = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else abs(float(residuals[0]))
    if not np.isfinite(residual_scale) or residual_scale == 0:
        residual_scale = max(float(np.std(np.diff(values), ddof=0)), abs(float(values[-1])) * 0.01, 1e-9)
    future_times = _future_times(data[time_column], horizon)
    points = [
        ForecastPoint(
            time=time.isoformat(),
            value=float(value),
            lower_80=float(value - 1.2816 * residual_scale * sqrt(step)),
            upper_80=float(value + 1.2816 * residual_scale * sqrt(step)),
        )
        for step, (time, value) in enumerate(zip(future_times, future_values, strict=True), start=1)
    ]
    return ForecastResult(
        target_column=target_column,
        time_column=time_column,
        test_start=pd.Timestamp(data[time_column].iloc[first_test]),
        baseline_model=baseline_model,
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        selected_model=selected_model,
        selected_metrics=selected_metrics,
        is_recommended=candidate_is_better,
        backtest_folds=folds,
        prediction_interval_80=points,
        residual_anomalies=_residual_anomalies(folds, selected_model),
        limitations=list(dict.fromkeys(limitations)),
    )
