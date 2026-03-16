from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from prostanet.domains.patient_tracking.therapy_catalog import regimen_label

LINE_COLORS = [
    "rgba(59, 130, 246, 0.12)",
    "rgba(16, 185, 129, 0.12)",
    "rgba(245, 158, 11, 0.12)",
    "rgba(236, 72, 153, 0.12)",
    "rgba(168, 85, 247, 0.12)",
    "rgba(14, 165, 233, 0.12)",
]

LINE_CONTEXT_LABELS = {
    "mHSPC_initial": "mHSPC inicial",
    "mHSPC_post_docetaxel": "mHSPC post-docetaxel",
    "m0_CRPC_first_line": "m0 CRPC primera línea",
    "mCRPC_first_line": "mCRPC primera línea",
    "mCRPC_post_ARPI_pre_taxane": "mCRPC post-ARPI pre-taxano",
    "mCRPC_post_taxane": "mCRPC post-taxano",
    "mCRPC_post_PARP": "mCRPC post-PARP",
    "mCRPC_post_Lu177": "mCRPC post-Lu177",
    "later_line": "Líneas posteriores",
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _fmt_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def _line_label(number: Any, context: Any, scheme: Any) -> str:
    number_label = f"L{number}" if _is_present(number) else "Línea"
    context_label = LINE_CONTEXT_LABELS.get(str(context or ""), context or "")
    scheme_label = regimen_label(scheme) if _is_present(scheme) else ""
    if context_label and scheme_label:
        return f"{number_label} · {context_label} · {scheme_label}"
    if context_label:
        return f"{number_label} · {context_label}"
    if scheme_label:
        return f"{number_label} · {scheme_label}"
    return number_label


def _extract_psa_points(patient: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    biomarker_rows = [
        row
        for row in (patient.get("biomarker_longitudinal") or [])
        if str(row.get("biomarker_type") or "").upper() == "PSA" and _is_present(row.get("value")) and _is_present(row.get("sample_date"))
    ]
    if biomarker_rows:
        points = [
            {
                "date": str(row.get("sample_date"))[:10],
                "psa": _safe_float(row.get("value")),
                "source": "biomarker_longitudinal",
            }
            for row in biomarker_rows
            if _safe_float(row.get("value")) is not None
        ]
        return sorted(points, key=lambda item: item["date"]), "biomarker_longitudinal"

    points = []
    baseline_psa = (patient.get("baseline") or {}).get("baseline_psa")
    diagnosis_date = (patient.get("identity") or {}).get("diagnosis_date")
    if _is_present(baseline_psa) and _is_present(diagnosis_date):
        points.append(
            {
                "date": str(diagnosis_date)[:10],
                "psa": _safe_float(baseline_psa),
                "source": "clinical_baseline",
            }
        )
    for visit in patient.get("follow_ups") or []:
        psa_value = _safe_float(visit.get("psa_current"))
        if psa_value is None or not _is_present(visit.get("visit_date")):
            continue
        points.append(
            {
                "date": str(visit.get("visit_date"))[:10],
                "psa": psa_value,
                "source": "follow_up_visits",
            }
        )
    deduped = {}
    for point in points:
        deduped[(point["date"], point["psa"])] = point
    return sorted(deduped.values(), key=lambda item: item["date"]), "follow_up_visits" if points else "missing"


def _extract_treatment_bands(patient: dict[str, Any], points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    treatments = [
        row
        for row in (patient.get("treatments") or [])
        if _is_present(row.get("start_date")) and any(
            _is_present(row.get(field))
            for field in ("line_of_therapy_number", "line_of_therapy_context", "drug_scheme", "current_treatment")
        )
    ]
    if not treatments:
        return []

    treatments = sorted(treatments, key=lambda item: str(item.get("start_date")))
    point_dates = [_parse_iso_date(point.get("date")) for point in points if point.get("date")]
    last_known_date = max([item for item in point_dates if item is not None], default=date.today())
    bands = []
    for index, treatment in enumerate(treatments):
        start_date = _parse_iso_date(treatment.get("start_date"))
        if not start_date:
            continue
        explicit_end = _parse_iso_date(treatment.get("end_date"))
        next_start = _parse_iso_date(treatments[index + 1].get("start_date")) if index + 1 < len(treatments) else None
        if explicit_end:
            end_date = explicit_end
        elif next_start:
            end_date = next_start - timedelta(days=1)
        else:
            end_date = last_known_date
        label = _line_label(
            treatment.get("line_of_therapy_number"),
            treatment.get("line_of_therapy_context"),
            treatment.get("drug_scheme") or treatment.get("current_treatment"),
        )
        bands.append(
            {
                "start_date": _fmt_date(start_date),
                "end_date": _fmt_date(end_date),
                "line_of_therapy_number": treatment.get("line_of_therapy_number"),
                "line_of_therapy_context": treatment.get("line_of_therapy_context"),
                "drug_scheme": treatment.get("drug_scheme") or treatment.get("current_treatment"),
                "drug_scheme_label": regimen_label(treatment.get("drug_scheme") or treatment.get("current_treatment")),
                "label": label,
                "color": LINE_COLORS[index % len(LINE_COLORS)],
                "source": "treatment_history",
            }
        )
    return bands


def _segment_points_by_line(points: list[dict[str, Any]], bands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from clinical_scores import calculate_psa_kinetics

    segments = []
    for band in bands:
        start_date = _parse_iso_date(band.get("start_date"))
        end_date = _parse_iso_date(band.get("end_date"))
        if not start_date:
            continue
        segment_points = [
            point
            for point in points
            if _parse_iso_date(point.get("date")) and start_date <= _parse_iso_date(point.get("date")) <= (end_date or date.today())
        ]
        values = [point.get("psa") for point in segment_points if _is_present(point.get("psa"))]
        baseline_psa = values[0] if values else None
        nadir_psa = min(values) if values else None
        current_psa = values[-1] if values else None
        best_pct_change = None
        if baseline_psa not in (None, 0) and nadir_psa is not None:
            best_pct_change = ((nadir_psa - baseline_psa) / baseline_psa) * 100
        kinetics = calculate_psa_kinetics(
            [(point.get("date"), point.get("psa")) for point in segment_points if point.get("date") and _is_present(point.get("psa"))]
        ) if len(segment_points) >= 2 else {}
        segments.append(
            {
                **band,
                "baseline_psa": baseline_psa,
                "nadir_psa": nadir_psa,
                "current_psa": current_psa,
                "best_pct_change": round(best_pct_change, 1) if best_pct_change is not None else None,
                "psa50_achieved": bool(best_pct_change is not None and best_pct_change <= -50),
                "psa_velocity": kinetics.get("velocity"),
                "psadt": kinetics.get("psadt"),
                "point_count": len(segment_points),
            }
        )
    return segments


def build_psa_by_treatment_line(patient: dict[str, Any]) -> dict[str, Any]:
    from clinical_scores import calculate_psa_kinetics

    points, source = _extract_psa_points(patient)
    if not points:
        return {
            "has_data": False,
            "points": [],
            "treatment_bands": [],
            "line_segments": [],
            "line_events": [],
            "metrics": {},
            "source": source,
        }

    bands = _extract_treatment_bands(patient, points)
    segments = _segment_points_by_line(points, bands)
    kinetics = calculate_psa_kinetics(
        [(point.get("date"), point.get("psa")) for point in points if point.get("date") and _is_present(point.get("psa"))]
    )
    psa_values = [point.get("psa") for point in points if _is_present(point.get("psa"))]
    line_events = [
        {
            "date": segment.get("start_date"),
            "title": segment.get("label"),
            "decision": "Inicio o cambio de línea terapéutica",
            "origin": "treatment_history",
            "line_of_therapy_number": segment.get("line_of_therapy_number"),
            "line_of_therapy_context": segment.get("line_of_therapy_context"),
        }
        for segment in segments
    ]
    return {
        "has_data": True,
        "points": points,
        "treatment_bands": bands,
        "line_segments": segments,
        "line_events": line_events,
        "metrics": {
            "current_psa": psa_values[-1] if psa_values else None,
            "nadir_psa": min(psa_values) if psa_values else None,
            "psa_velocity": kinetics.get("velocity"),
            "psadt": kinetics.get("psadt"),
            "interpretation": kinetics.get("interpretation"),
            "current_line_label": segments[-1].get("label") if segments else "",
        },
        "source": source,
    }
