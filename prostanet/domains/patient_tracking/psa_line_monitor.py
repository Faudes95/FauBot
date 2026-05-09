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
        if str(row.get("biomarker_type") or "").upper() == "PSA"
        and _is_present(row.get("value"))
        and _is_present(row.get("sample_date"))
        and not row.get("deleted_at")  # respetar soft-delete
    ]
    if biomarker_rows:
        points = [
            {
                "date": str(row.get("sample_date"))[:10],
                "psa": _safe_float(row.get("value")),
                "source": row.get("source") or "biomarker_longitudinal",
                # Etiquetas requeridas por la vista por estadio. Valores `None`
                # se backfilean perezosamente desde el reconciled_state cercano.
                "clinical_state_at_measurement": row.get("clinical_state_at_measurement"),
                "disease_phase": row.get("disease_phase"),
                "line_label": row.get("line_label"),
                "point_id": row.get("id"),
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
                # Bug fix: calculate_psa_kinetics retorna `psadt_months`, no `psadt`.
                # Conservamos ambas keys para no romper consumidores legacy.
                "psadt_months": kinetics.get("psadt_months"),
                "psadt": kinetics.get("psadt_months"),
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
            # Bug fix: leer `psadt_months` (canónico). Mantener alias `psadt` por compat.
            "psadt_months": kinetics.get("psadt_months"),
            "psadt": kinetics.get("psadt_months"),
            "interpretation": kinetics.get("interpretation"),
            "current_line_label": segments[-1].get("label") if segments else "",
        },
        "source": source,
    }


# ─── Vista por estadio clínico ───────────────────────────────────────────────
# Habilita la "torre de control APE" en su modo agrupado por estadio (localizado,
# BCR, mHSPC, mCRPC, oligoprogression). Es el complemento clínico de la vista por
# línea terapéutica: dos lentes de la misma serie para que el médico pueda
# evaluar tanto la respuesta al tratamiento como la dinámica del estadio.

# Etiquetas legibles + colores semáforo. Se sirven al frontend para construir
# bandas y chips. Mantén sincronizados con .stage-chip-* en ui_theme.css.
STAGE_DISPLAY = {
    "diagnostic_workup": ("Diagnóstico", "#94a3b8"),
    "post_negative_biopsy_followup": ("Vigilancia post-biopsia", "#94a3b8"),
    "post_prostatectomy": ("Post-prostatectomía", "#22c55e"),
    "recurrence_bcr": ("BCR", "#f59e0b"),
    "post_radiotherapy_or_local_salvage": ("Post-RT / Rescate local", "#f59e0b"),
    "mcspc_oligo_metachronous": ("mHSPC oligo metacrónico", "#fb923c"),
    "mcspc_low_volume_sync_oligo": ("mHSPC bajo vol. sincrónico", "#fb923c"),
    "mcspc_high_volume_sync": ("mHSPC alto vol. sincrónico", "#f97316"),
    "mcspc_high_volume_metachronous": ("mHSPC alto vol. metacrónico", "#f97316"),
    "mcspc_high_volume": ("mHSPC alto volumen", "#f97316"),
    "adt_progression_verification": ("Verificación progresión ADT", "#dc2626"),
    "m0_crpc": ("m0 CRPC", "#dc2626"),
    "m1_crpc": ("m1 CRPC", "#dc2626"),
    "oligoprogression_post_systemic": ("Oligoprogresión", "#a855f7"),
}


def _stage_display(state: str | None) -> tuple[str, str]:
    if not state:
        return ("Sin estadio", "#64748b")
    return STAGE_DISPLAY.get(state, (state, "#64748b"))


def _segment_points_by_stage(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa puntos PSA contiguos del mismo `clinical_state_at_measurement`.

    No re-ordena: respeta el orden cronológico ya garantizado por
    `_extract_psa_points`. Cada cambio de estado abre un nuevo segmento.
    """
    from clinical_scores import calculate_psa_kinetics

    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for p in points:
        stage = p.get("clinical_state_at_measurement") or "unknown"
        if current is None or current["state"] != stage:
            if current is not None:
                segments.append(current)
            label, color = _stage_display(stage)
            current = {
                "state": stage,
                "label": label,
                "color": color,
                "points": [],
                "start_date": p.get("date"),
                "end_date": p.get("date"),
            }
        current["points"].append(p)
        current["end_date"] = p.get("date")
    if current is not None:
        segments.append(current)

    # Métricas por segmento (mismas que vista por línea: baseline, nadir, current,
    # velocity, PSADT, %Δ).
    for seg in segments:
        values = [pt["psa"] for pt in seg["points"] if _is_present(pt.get("psa"))]
        seg["baseline_psa"] = values[0] if values else None
        seg["nadir_psa"] = min(values) if values else None
        seg["current_psa"] = values[-1] if values else None
        seg["point_count"] = len(seg["points"])
        if seg["baseline_psa"] not in (None, 0) and seg["nadir_psa"] is not None:
            seg["best_pct_change"] = round(
                ((seg["nadir_psa"] - seg["baseline_psa"]) / seg["baseline_psa"]) * 100, 1
            )
        else:
            seg["best_pct_change"] = None
        if len(seg["points"]) >= 2:
            k = calculate_psa_kinetics(
                [(pt["date"], pt["psa"]) for pt in seg["points"]
                 if pt.get("date") and _is_present(pt.get("psa"))]
            )
            seg["psa_velocity"] = k.get("velocity")
            seg["psadt_months"] = k.get("psadt_months")
        else:
            seg["psa_velocity"] = None
            seg["psadt_months"] = None
    return segments


def _detect_stage_transitions(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Marca los cambios de estadio entre puntos consecutivos para overlay UI."""
    transitions: list[dict[str, Any]] = []
    prev_state = None
    prev_psa = None
    for p in points:
        stage = p.get("clinical_state_at_measurement") or "unknown"
        if prev_state is not None and stage != prev_state:
            from_label, _ = _stage_display(prev_state)
            to_label, to_color = _stage_display(stage)
            psa_delta = None
            if prev_psa is not None and p.get("psa") is not None:
                psa_delta = round(p["psa"] - prev_psa, 2)
            transitions.append({
                "date": p.get("date"),
                "from_state": prev_state,
                "from_label": from_label,
                "to_state": stage,
                "to_label": to_label,
                "to_color": to_color,
                "psa_at_transition": p.get("psa"),
                "psa_delta": psa_delta,
            })
        prev_state = stage
        prev_psa = p.get("psa")
    return transitions


def build_psa_by_stage(patient: dict[str, Any]) -> dict[str, Any]:
    """Torre de control APE — agrupación por estadio clínico.

    Forma del retorno: idéntica a `build_psa_by_treatment_line` para que el
    frontend pueda renderizarla con el mismo componente, sustituyendo
    `line_segments` por `stage_segments` y agregando `transitions`.
    """
    from clinical_scores import calculate_psa_kinetics

    points, source = _extract_psa_points(patient)
    if not points:
        return {
            "has_data": False,
            "points": [],
            "stage_segments": [],
            "transitions": [],
            "metrics": {},
            "source": source,
        }

    stage_segments = _segment_points_by_stage(points)
    transitions = _detect_stage_transitions(points)
    psa_values = [p.get("psa") for p in points if _is_present(p.get("psa"))]
    kinetics = calculate_psa_kinetics(
        [(p.get("date"), p.get("psa")) for p in points
         if p.get("date") and _is_present(p.get("psa"))]
    ) if len(points) >= 2 else {}

    return {
        "has_data": True,
        "points": points,
        "stage_segments": stage_segments,
        "transitions": transitions,
        "metrics": {
            "current_psa": psa_values[-1] if psa_values else None,
            "nadir_psa": min(psa_values) if psa_values else None,
            "psa_velocity": kinetics.get("velocity"),
            "psadt_months": kinetics.get("psadt_months"),
            "psadt": kinetics.get("psadt_months"),
            "interpretation": kinetics.get("interpretation"),
            "current_stage": stage_segments[-1].get("state") if stage_segments else None,
            "current_stage_label": stage_segments[-1].get("label") if stage_segments else "",
        },
        "source": source,
    }
