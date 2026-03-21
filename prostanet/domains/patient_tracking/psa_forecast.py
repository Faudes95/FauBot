from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label

ADVANCED_FORECAST_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}

FORECAST_HORIZONS = (3, 6, 12)
_MIN_POINTS = 3
_MIN_SPAN_DAYS = 42
_LINE_STABLE_DAYS = 84
_OUTLIER_Z = 2.5
_EPSILON = 0.01


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _parse_date(value: Any) -> date | None:
    if not value or value in ("", "No aplica"):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _months_between(start: date | None, end: date | None) -> float | None:
    if not start or not end:
        return None
    return round((end - start).days / 30.44, 2)


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, "", "No aplica"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _current_line_context(patient: dict[str, Any], monitoring: dict[str, Any]) -> dict[str, Any]:
    segments = list(monitoring.get("line_segments") or [])
    if segments:
        return dict(segments[-1])

    treatments = list(patient.get("treatments") or [])
    latest_treatment = treatments[-1] if treatments else {}
    return {
        "start_date": latest_treatment.get("start_date") or "",
        "end_date": latest_treatment.get("end_date") or "",
        "line_of_therapy_number": latest_treatment.get("line_of_therapy_number") or latest_treatment.get("line_of_therapy") or 1,
        "line_of_therapy_context": latest_treatment.get("line_of_therapy_context") or "",
        "drug_scheme": latest_treatment.get("drug_scheme") or latest_treatment.get("current_treatment") or "",
        "label": regimen_label(latest_treatment.get("drug_scheme") or latest_treatment.get("current_treatment")) or "Línea actual",
        "baseline_psa": (monitoring.get("metrics") or {}).get("current_psa"),
        "nadir_psa": (monitoring.get("metrics") or {}).get("nadir_psa"),
        "point_count": len(monitoring.get("points") or []),
    }


def _points_for_current_line(monitoring: dict[str, Any], line_context: dict[str, Any]) -> list[dict[str, Any]]:
    points = list(monitoring.get("points") or [])
    if not points:
        return []
    start_date = _parse_date(line_context.get("start_date"))
    end_date = _parse_date(line_context.get("end_date"))
    filtered: list[dict[str, Any]] = []
    for point in points:
        point_date = _parse_date(point.get("date"))
        if not point_date:
            continue
        if start_date and point_date < start_date:
            continue
        if end_date and point_date > end_date:
            continue
        psa = _safe_float(point.get("psa"))
        if psa is None or psa < 0:
            continue
        filtered.append({"date": point_date.isoformat(), "psa": psa})
    return filtered


def _prepare_regression_points(points: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    ordered = sorted(points, key=lambda item: item.get("date") or "")
    base_date = _parse_date(ordered[0]["date"])
    x_values = []
    y_values = []
    kept = []
    for point in ordered:
        point_date = _parse_date(point.get("date"))
        psa = _safe_float(point.get("psa"))
        if not base_date or not point_date or psa is None:
            continue
        months = (point_date - base_date).days / 30.44
        x_values.append(months)
        y_values.append(math.log(max(psa, _EPSILON)))
        kept.append(point)
    return np.asarray(x_values, dtype=float), np.asarray(y_values, dtype=float), kept


def _fit_log_psa_model(points: list[dict[str, Any]]) -> dict[str, Any]:
    x, y, kept_points = _prepare_regression_points(points)
    if len(kept_points) < _MIN_POINTS:
        return {"status": "insufficient_data", "reason": "Puntos PSA insuficientes para ajuste."}

    weights = np.linspace(1.0, 2.0, len(x))
    try:
        coeffs, covariance = np.polyfit(x, y, 1, w=weights, cov=True)
    except Exception:
        return {"status": "insufficient_data", "reason": "No fue posible ajustar el modelo longitudinal de PSA."}

    slope = float(coeffs[0])
    intercept = float(coeffs[1])
    y_hat = slope * x + intercept
    residuals = y - y_hat
    mad = float(np.median(np.abs(residuals - np.median(residuals)))) if len(residuals) else 0.0

    outlier_indices: list[int] = []
    if mad > 1e-6 and len(x) >= 4:
        for idx, residual in enumerate(residuals):
            robust_z = abs(residual - np.median(residuals)) / (1.4826 * mad)
            if robust_z > _OUTLIER_Z:
                outlier_indices.append(idx)

    if outlier_indices and len(x) - len(outlier_indices) >= _MIN_POINTS:
        mask = np.ones(len(x), dtype=bool)
        mask[outlier_indices] = False
        x = x[mask]
        y = y[mask]
        kept_points = [point for idx, point in enumerate(kept_points) if idx not in outlier_indices]
        weights = np.linspace(1.0, 2.0, len(x))
        coeffs, covariance = np.polyfit(x, y, 1, w=weights, cov=True)
        slope = float(coeffs[0])
        intercept = float(coeffs[1])
        y_hat = slope * x + intercept
        residuals = y - y_hat

    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-9 else 1.0
    sigma = math.sqrt(max(ss_res / max(len(x) - 2, 1), 0.0))

    return {
        "status": "ok",
        "points": kept_points,
        "x": x,
        "y": y,
        "slope": slope,
        "intercept": intercept,
        "covariance": covariance,
        "sigma": sigma,
        "r2": max(min(r2, 1.0), -1.0),
        "outlier_count": len(outlier_indices),
    }


def _predict_log_point(model: dict[str, Any], x_months: float) -> dict[str, float]:
    vector = np.asarray([x_months, 1.0], dtype=float)
    covariance = np.asarray(model.get("covariance"))
    sigma = float(model.get("sigma") or 0.0)
    y_hat = float(model["slope"] * x_months + model["intercept"])
    mean_var = float(vector @ covariance @ vector.T) if covariance.size else 0.0
    pred_var = max(mean_var + sigma**2, 1e-9)
    pred_sd = math.sqrt(pred_var)
    lower = math.exp(y_hat - 1.96 * pred_sd)
    upper = math.exp(y_hat + 1.96 * pred_sd)
    expected = math.exp(y_hat)
    return {
        "expected_psa": expected,
        "lower_psa": lower,
        "upper_psa": upper,
        "interval_width": upper - lower,
    }


def _line_reliability(
    *,
    current_points: list[dict[str, Any]],
    line_context: dict[str, Any],
    model: dict[str, Any],
) -> dict[str, Any]:
    first_date = _parse_date(current_points[0]["date"]) if current_points else None
    last_date = _parse_date(current_points[-1]["date"]) if current_points else None
    span_days = (last_date - first_date).days if first_date and last_date else 0
    line_start = _parse_date(line_context.get("start_date")) or first_date
    line_age_days = (last_date - line_start).days if line_start and last_date else 0

    minimum_data_passed = len(current_points) >= _MIN_POINTS and span_days >= _MIN_SPAN_DAYS
    line_stability_passed = line_age_days >= _LINE_STABLE_DAYS
    model_fit_quality = _round_or_none(max(float(model.get("r2") or 0.0), 0.0), 3)
    outlier_burden = int(model.get("outlier_count") or 0)

    prediction_interval_width = None
    if model.get("status") == "ok" and current_points:
        x_values = model.get("x")
        last_x = float(x_values[-1]) if x_values is not None and len(x_values) else 0.0
        next_point = _predict_log_point(model, last_x + 6.0)
        prediction_interval_width = _round_or_none(next_point["interval_width"], 2)

    reasons = []
    if not minimum_data_passed:
        reasons.append("Menos de 3 puntos válidos o ventana temporal insuficiente dentro de la línea actual.")
    if minimum_data_passed and not line_stability_passed:
        reasons.append("La línea terapéutica actual es demasiado reciente para extrapolar con seguridad.")
    if model_fit_quality is not None and model_fit_quality < 0.4:
        reasons.append("La tendencia longitudinal de PSA es poco estable para una extrapolación numérica robusta.")
    if outlier_burden:
        reasons.append("Se detectaron valores PSA atípicos que ensanchan la incertidumbre del modelo.")

    if not minimum_data_passed or model.get("status") != "ok":
        confidence = "insufficient_data"
    elif not line_stability_passed or model_fit_quality is not None and model_fit_quality < 0.4:
        confidence = "low"
    elif model_fit_quality is not None and model_fit_quality >= 0.75 and outlier_burden == 0 and line_age_days >= 120:
        confidence = "high"
    else:
        confidence = "medium"

    return {
        "minimum_data_passed": minimum_data_passed,
        "line_stability_passed": line_stability_passed,
        "model_fit_quality": model_fit_quality,
        "outlier_burden": outlier_burden,
        "prediction_interval_width": prediction_interval_width,
        "confidence_label": confidence,
        "reasons": reasons,
        "line_age_days": line_age_days,
        "point_span_days": span_days,
    }


def _projected_psadt_months(slope_per_month: float) -> float | None:
    if slope_per_month <= 1e-6:
        return None
    return round(math.log(2) / slope_per_month, 1)


def _estimate_psadt_crossings(model: dict[str, Any], points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    thresholds = (10, 6, 3)
    results: list[dict[str, Any]] = []
    current_psadt = _projected_psadt_months(float(model.get("slope") or 0.0))
    last_date = _parse_date(points[-1]["date"]) if points else None
    x_values = model.get("x")
    y_values = model.get("y")
    x = list(x_values) if x_values is not None else []
    y = list(y_values) if y_values is not None else []
    if not last_date or len(x) < 3:
        return results

    acceleration = None
    if len(x) >= 5:
        split = len(x) // 2
        early_x = np.asarray(x[: split + 1], dtype=float)
        early_y = np.asarray(y[: split + 1], dtype=float)
        late_x = np.asarray(x[split:], dtype=float)
        late_y = np.asarray(y[split:], dtype=float)
        if len(early_x) >= 2 and len(late_x) >= 2:
            early_slope, _ = np.polyfit(early_x, early_y, 1)
            late_slope, _ = np.polyfit(late_x, late_y, 1)
            delta_months = max(float(late_x[-1] - early_x[-1]), 0.5)
            if late_slope > early_slope > 0:
                acceleration = (late_slope - early_slope) / delta_months

    for threshold in thresholds:
        slope_threshold = math.log(2) / threshold
        entry = {
            "threshold_key": f"psadt_lt_{threshold}",
            "label": f"PSADT < {threshold} meses",
            "status": "not_reached",
            "estimated_crossing_date": "",
            "months_until_crossing": None,
            "projected_psadt_months": current_psadt,
        }
        if current_psadt is not None and current_psadt <= threshold:
            entry["status"] = "crossed_now"
            entry["estimated_crossing_date"] = last_date.isoformat()
            entry["months_until_crossing"] = 0.0
        elif acceleration and acceleration > 0:
            current_slope = float(model.get("slope") or 0.0)
            if slope_threshold > current_slope:
                months_until = (slope_threshold - current_slope) / acceleration
                if 0 < months_until <= 12:
                    crossing_date = last_date + timedelta(days=int(months_until * 30.44))
                    entry["status"] = "forecast_crossing"
                    entry["estimated_crossing_date"] = crossing_date.isoformat()
                    entry["months_until_crossing"] = _round_or_none(months_until, 1)
        results.append(entry)
    return results


def _estimate_absolute_thresholds(
    line_context: dict[str, Any],
    forecast_curve: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    thresholds: list[dict[str, Any]] = []
    nadir = _safe_float(line_context.get("nadir_psa"))
    if nadir is None or nadir <= 0:
        return thresholds

    absolute_thresholds = [
        {
            "threshold_key": "nadir_plus_2",
            "label": "Nadir + 2 ng/mL",
            "target_psa": nadir + 2.0,
        },
        {
            "threshold_key": "pcwg3_psa_progression",
            "label": "Aumento ≥25% y ≥2 ng/mL sobre nadir",
            "target_psa": max(nadir * 1.25, nadir + 2.0),
        },
    ]
    for threshold in absolute_thresholds:
        entry = {
            **threshold,
            "status": "not_reached",
            "estimated_crossing_date": "",
            "months_until_crossing": None,
        }
        for point in forecast_curve:
            if (point.get("expected_psa") or 0.0) >= threshold["target_psa"]:
                entry["status"] = "forecast_crossing"
                entry["estimated_crossing_date"] = point["date"]
                entry["months_until_crossing"] = point.get("horizon_months")
                break
        thresholds.append(entry)
    return thresholds


def _build_predictive_alerts(
    reliability: dict[str, Any],
    psadt_thresholds: list[dict[str, Any]],
    absolute_thresholds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    confidence = reliability.get("confidence_label")
    if confidence not in {"high", "medium", "low"}:
        return alerts

    for item in psadt_thresholds:
        if item.get("status") in {"crossed_now", "forecast_crossing"}:
            threshold_key = str(item.get("threshold_key") or "")
            months_until = _safe_float(item.get("months_until_crossing"))
            severity = "warning"
            if threshold_key.endswith("_3"):
                severity = "critical"
            elif threshold_key.endswith("_6"):
                severity = "warning"
            if months_until is None or months_until <= 6:
                alerts.append(
                    {
                        "severity": severity,
                        "title": item.get("label"),
                        "message": (
                            f"La tendencia actual sugiere {item.get('label', '').lower()} "
                            f"{'ya presente' if months_until == 0 else f'en ~{months_until:.1f} meses'}."
                        ),
                        "threshold_key": threshold_key,
                    }
                )

    for item in absolute_thresholds:
        months_until = _safe_float(item.get("months_until_crossing"))
        if item.get("status") == "forecast_crossing" and months_until is not None and months_until <= 6:
            alerts.append(
                {
                    "severity": "warning",
                    "title": item.get("label"),
                    "message": f"Si la tendencia actual persiste, alcanzará {item.get('label')} en ~{months_until:.1f} meses.",
                    "threshold_key": item.get("threshold_key"),
                }
            )
    return alerts[:5]


def build_psa_forecast(
    patient: dict[str, Any],
    *,
    state: str = "",
) -> dict[str, Any]:
    resolved_state = str(state or patient.get("reconciled_state") or (patient.get("latest_assessment") or {}).get("state") or "")
    if resolved_state not in ADVANCED_FORECAST_STATES:
        return {
            "status": "not_applicable",
            "show": False,
            "state": resolved_state,
            "forecast_points": [],
            "forecast_curve": [],
            "threshold_events": [],
            "predictive_alerts": [],
            "reliability": {
                "minimum_data_passed": False,
                "line_stability_passed": False,
                "model_fit_quality": None,
                "outlier_burden": 0,
                "prediction_interval_width": None,
                "confidence_label": "not_applicable",
                "reasons": ["La predicción prospectiva PSA v1 solo aplica a enfermedad avanzada."],
            },
        }

    monitoring = build_psa_by_treatment_line(patient)
    points = list(monitoring.get("points") or [])
    if not points:
        return {
            "status": "insufficient_data",
            "show": False,
            "state": resolved_state,
            "forecast_points": [],
            "forecast_curve": [],
            "threshold_events": [],
            "predictive_alerts": [],
            "reliability": {
                "minimum_data_passed": False,
                "line_stability_passed": False,
                "model_fit_quality": None,
                "outlier_burden": 0,
                "prediction_interval_width": None,
                "confidence_label": "insufficient_data",
                "reasons": ["No hay datos PSA longitudinales suficientes para construir una proyección."],
            },
        }

    line_context = _current_line_context(patient, monitoring)
    current_points = _points_for_current_line(monitoring, line_context)
    if not current_points:
        current_points = points

    model = _fit_log_psa_model(current_points)
    reliability = _line_reliability(current_points=current_points, line_context=line_context, model=model)
    if model.get("status") != "ok":
        reliability["confidence_label"] = "insufficient_data"
        reliability["reasons"] = reliability.get("reasons") or [str(model.get("reason") or "No fue posible ajustar el forecast de PSA.")]
        return {
            "status": "insufficient_data",
            "show": False,
            "state": resolved_state,
            "forecast_points": [],
            "forecast_curve": [],
            "threshold_events": [],
            "predictive_alerts": [],
            "current_line_label": line_context.get("label") or "Línea actual",
            "current_regimen_label": regimen_label(line_context.get("drug_scheme")) or line_context.get("drug_scheme") or "",
            "line_of_therapy_number": line_context.get("line_of_therapy_number"),
            "reliability": reliability,
        }

    prepared_points = list(model.get("points") or current_points)
    first_date = _parse_date(prepared_points[0]["date"]) if prepared_points else None
    last_date = _parse_date(prepared_points[-1]["date"]) if prepared_points else None
    x_values = model.get("x")
    last_x = float(x_values[-1]) if x_values is not None and len(x_values) else 0.0

    forecast_points = []
    forecast_curve = []
    for horizon in FORECAST_HORIZONS:
        prediction = _predict_log_point(model, last_x + float(horizon))
        target_date = last_date + timedelta(days=int(horizon * 30.44)) if last_date else None
        forecast_points.append(
            {
                "horizon_months": horizon,
                "date": target_date.isoformat() if target_date else "",
                "expected_psa": _round_or_none(prediction["expected_psa"], 2),
                "lower_psa": _round_or_none(prediction["lower_psa"], 2),
                "upper_psa": _round_or_none(prediction["upper_psa"], 2),
                "interval_width": _round_or_none(prediction["interval_width"], 2),
            }
        )
    for horizon in range(1, 13):
        prediction = _predict_log_point(model, last_x + float(horizon))
        target_date = last_date + timedelta(days=int(horizon * 30.44)) if last_date else None
        forecast_curve.append(
            {
                "horizon_months": horizon,
                "date": target_date.isoformat() if target_date else "",
                "expected_psa": _round_or_none(prediction["expected_psa"], 2),
                "lower_psa": _round_or_none(prediction["lower_psa"], 2),
                "upper_psa": _round_or_none(prediction["upper_psa"], 2),
            }
        )

    psadt_thresholds = _estimate_psadt_crossings(model, prepared_points)
    absolute_thresholds = _estimate_absolute_thresholds(line_context, forecast_curve)
    threshold_events = psadt_thresholds + absolute_thresholds
    predictive_alerts = _build_predictive_alerts(reliability, psadt_thresholds, absolute_thresholds)

    projected_psadt = _projected_psadt_months(float(model.get("slope") or 0.0))
    status = "ready"
    show = True
    if reliability["confidence_label"] == "low":
        status = "low_confidence"
    elif reliability["confidence_label"] == "insufficient_data":
        status = "insufficient_data"
        show = False

    return {
        "status": status,
        "show": show,
        "state": resolved_state,
        "current_line_label": line_context.get("label") or "Línea actual",
        "current_regimen_label": regimen_label(line_context.get("drug_scheme")) or line_context.get("drug_scheme") or "",
        "line_of_therapy_number": line_context.get("line_of_therapy_number"),
        "line_of_therapy_context": line_context.get("line_of_therapy_context") or "",
        "current_line_start_date": line_context.get("start_date") or "",
        "last_observed_date": last_date.isoformat() if last_date else "",
        "current_psa": _round_or_none(_safe_float(prepared_points[-1]["psa"]) if prepared_points else None, 2),
        "nadir_psa": _round_or_none(min(_safe_float(point.get("psa")) or 0.0 for point in prepared_points) if prepared_points else None, 2),
        "forecast_points": forecast_points,
        "forecast_curve": forecast_curve,
        "threshold_events": threshold_events,
        "predictive_alerts": predictive_alerts,
        "projected_psadt_months": projected_psadt,
        "trend_summary": (
            "Si la tendencia actual persiste, el PSA continuará en ascenso con señal longitudinal consistente."
            if float(model.get("slope") or 0.0) > 0
            else "La tendencia actual sugiere estabilidad o descenso de PSA dentro de la línea actual."
        ),
        "reliability": reliability,
    }


def _matching_actual_point(
    points: list[dict[str, Any]],
    target_date: date,
    tolerance_days: int,
) -> dict[str, Any] | None:
    matches: list[tuple[int, dict[str, Any]]] = []
    for point in points:
        point_date = _parse_date(point.get("date"))
        if not point_date:
            continue
        delta_days = abs((point_date - target_date).days)
        if delta_days <= tolerance_days:
            matches.append((delta_days, point))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[0][1]


def build_psa_forecast_backtest(patient_records: list[dict[str, Any]]) -> dict[str, Any]:
    horizon_tolerances = {3: 45, 6: 60, 12: 90}
    rows = []
    by_horizon: dict[int, list[dict[str, Any]]] = {3: [], 6: [], 12: []}
    by_state: dict[str, dict[int, list[dict[str, Any]]]] = {}

    for patient in patient_records:
        state = str(patient.get("reconciled_state") or (patient.get("latest_assessment") or {}).get("state") or (patient.get("prior_history") or {}).get("current_state") or "")
        if state not in ADVANCED_FORECAST_STATES:
            continue
        monitoring = build_psa_by_treatment_line(patient)
        line_context = _current_line_context(patient, monitoring)
        points = _points_for_current_line(monitoring, line_context)
        if len(points) < 4:
            continue
        ordered = sorted(points, key=lambda item: item.get("date") or "")
        for index in range(2, len(ordered) - 1):
            history = ordered[: index + 1]
            model = _fit_log_psa_model(history)
            if model.get("status") != "ok":
                continue
            origin_date = _parse_date(history[-1]["date"])
            if not origin_date:
                continue
            for horizon in FORECAST_HORIZONS:
                target_date = origin_date + timedelta(days=int(horizon * 30.44))
                actual = _matching_actual_point(ordered[index + 1 :], target_date, horizon_tolerances[horizon])
                if not actual:
                    continue
                actual_date = _parse_date(actual.get("date"))
                if not actual_date:
                    continue
                history_x, _, _ = _prepare_regression_points(history)
                if len(history_x) == 0:
                    continue
                target_x = float((actual_date - _parse_date(history[0]["date"])).days / 30.44)
                prediction = _predict_log_point(model, target_x)
                actual_psa = _safe_float(actual.get("psa"))
                if actual_psa is None:
                    continue
                row = {
                    "patient_id": (patient.get("identity") or {}).get("id"),
                    "state": state,
                    "horizon_months": horizon,
                    "predicted_psa": _round_or_none(prediction["expected_psa"], 2),
                    "actual_psa": _round_or_none(actual_psa, 2),
                    "abs_error": _round_or_none(abs(prediction["expected_psa"] - actual_psa), 2),
                    "covered_by_interval": bool(prediction["lower_psa"] <= actual_psa <= prediction["upper_psa"]),
                }
                rows.append(row)
                by_horizon[horizon].append(row)
                state_bucket = by_state.setdefault(state, {3: [], 6: [], 12: []})
                state_bucket[horizon].append(row)

    def summarize(bucket: list[dict[str, Any]]) -> dict[str, Any]:
        if not bucket:
            return {"n_predictions": 0, "mae": None, "median_abs_error": None, "coverage_pct": None}
        abs_errors = [float(item["abs_error"]) for item in bucket if item.get("abs_error") is not None]
        coverage = [1 if item.get("covered_by_interval") else 0 for item in bucket]
        return {
            "n_predictions": len(bucket),
            "mae": _round_or_none(sum(abs_errors) / len(abs_errors), 2) if abs_errors else None,
            "median_abs_error": _round_or_none(float(np.median(abs_errors)), 2) if abs_errors else None,
            "coverage_pct": _round_or_none(sum(coverage) / len(coverage) * 100.0, 1) if coverage else None,
        }

    by_state_summary = {
        state: {str(horizon): summarize(bucket) for horizon, bucket in horizon_buckets.items()}
        for state, horizon_buckets in by_state.items()
    }
    return {
        "status": "ok" if rows else "insufficient_data",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "eligible_predictions": len(rows),
        "summary_by_horizon": {str(horizon): summarize(bucket) for horizon, bucket in by_horizon.items()},
        "summary_by_state": by_state_summary,
        "rows": rows[:250],
    }
