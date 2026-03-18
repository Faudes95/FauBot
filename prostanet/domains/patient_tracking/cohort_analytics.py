from __future__ import annotations

from typing import Any


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr"}
ADVANCED_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}

_MEXICO_CORE_FIELDS = (
    "estado_residencia",
    "seguridad_social",
    "escolaridad",
    "actividad_fisica",
    "diabetes_mellitus",
    "hipertension",
)


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _rate(present: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((present / total) * 100.0, 1)


def _tone_from_pct(value: float) -> str:
    if value >= 80:
        return "good"
    if value >= 55:
        return "warning"
    return "danger"


def compute_patient_cohort_completeness(patient: dict[str, Any], state: str) -> dict[str, Any]:
    identity = patient.get("identity") or {}
    demographics = patient.get("demographics") or {}
    genomics = patient.get("genomics") or {}
    followups = patient.get("follow_ups") or []
    biomarker_longitudinal = patient.get("biomarker_longitudinal") or []
    verified_documents = [
        item for item in (patient.get("source_documents") or [])
        if str(item.get("verification_status") or "") == "verified"
    ]

    sections = {
        "identity": _rate(sum(1 for field in ("nss", "full_name", "dob", "diagnosis_date") if _is_present(identity.get(field))), 4),
        "mexico_core": _rate(sum(1 for field in _MEXICO_CORE_FIELDS if _is_present(demographics.get(field))), len(_MEXICO_CORE_FIELDS)),
        "pathology": 100.0 if patient.get("biopsies") else 0.0,
        "imaging": 100.0 if patient.get("imaging") else 0.0,
        "treatment": 100.0 if patient.get("treatments") or patient.get("surgery") or patient.get("radiation") else 0.0,
        "follow_up": 100.0 if followups else 0.0,
        "biomarkers": _rate(len({item.get("biomarker_type") for item in biomarker_longitudinal if item.get("biomarker_type")}), 8),
        "pros": 100.0 if patient.get("pros") else 0.0,
        "provenance": 100.0 if patient.get("data_provenance") else 0.0,
        "documents": _rate(len(verified_documents), max(len(patient.get("source_documents") or []), 1)),
        "genomics": 100.0 if any(_is_present(genomics.get(field)) for field in ("hrr_overall", "brca2_status", "msi_status", "decipher_risk")) else 0.0,
    }
    overall_pct = round(sum(sections.values()) / len(sections), 1)
    missing_sections = [key for key, value in sections.items() if value < 50.0]
    return {
        "overall_pct": overall_pct,
        "tone": _tone_from_pct(overall_pct),
        "sections": sections,
        "missing_sections": missing_sections,
        "verified_documents": len(verified_documents),
        "followup_density": len(followups),
        "state": state,
    }


def compute_patient_endpoint_readiness(patient: dict[str, Any], state: str) -> dict[str, Any]:
    identity = patient.get("identity") or {}
    followups = patient.get("follow_ups") or []
    treatments = patient.get("treatments") or []
    biopsies = patient.get("biopsies") or []
    imaging = patient.get("imaging") or []
    biomarker_longitudinal = patient.get("biomarker_longitudinal") or []
    latest_followup = _latest(followups, "visit_date")

    endpoints = {
        "time_to_histology": bool(identity.get("diagnosis_date") and biopsies),
        "time_to_treatment": bool(identity.get("diagnosis_date") and (treatments or patient.get("surgery") or patient.get("radiation"))),
        "active_surveillance_exit": bool(patient.get("active_surveillance")),
        "biochemical_recurrence": bool(patient.get("bcr")),
        "time_to_adt": any("adt" in str(item.get("drug_scheme", "")).lower() for item in treatments) or "adt" in str(latest_followup.get("current_treatment", "")).lower(),
        "time_to_crpc": state in {"m0_crpc", "m1_crpc"},
        "line_duration": any(_is_present(item.get("start_date")) and _is_present(item.get("end_date")) for item in treatments) or len(treatments) > 0,
        "psa_kinetics": sum(1 for item in biomarker_longitudinal if item.get("biomarker_type") == "PSA") >= 2 or sum(1 for item in followups if _is_present(item.get("psa_current"))) >= 2,
        "radiographic_progression": bool(imaging and latest_followup.get("disease_status")),
        # ── Endpoints de supervivencia (Fase 6.1) ──
        "overall_survival": bool(identity.get("diagnosis_date")) and _is_present(patient.get("vital_status")),
        "rpfs": bool(treatments) and state in {"mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume", "m0_crpc", "m1_crpc"},
        "mfs": bool(identity.get("diagnosis_date")) and state in {"localized_initial", "post_prostatectomy", "recurrence_bcr", "m0_crpc"},
        "ttsre": bool(patient.get("skeletal_events")) or (state in {"mcspc_high_volume", "m1_crpc"} and bool(imaging)),
        # ── Vigilancia activa KPIs (Fase 6.1) ──
        "as_conversion_rate": bool(patient.get("active_surveillance") and patient.get("active_surveillance", {}).get("exit_reason") if isinstance(patient.get("active_surveillance"), dict) else False),
        "as_time_on_protocol": bool(patient.get("active_surveillance") and identity.get("diagnosis_date")),
        # ── Biopsia estructurada (Fase 6.1) ──
        "structured_biopsy_available": any(isinstance(b, dict) and b.get("systematic_cores") for b in biopsies) if biopsies else False,
    }
    ready_count = sum(1 for value in endpoints.values() if value)
    return {
        "ready_count": ready_count,
        "total": len(endpoints),
        "overall_pct": _rate(ready_count, len(endpoints)),
        "items": endpoints,
    }


def compute_patient_research_readiness(patient: dict[str, Any], state: str) -> dict[str, Any]:
    completeness = compute_patient_cohort_completeness(patient, state)
    endpoints = compute_patient_endpoint_readiness(patient, state)
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    critical_missing = latest_signal_snapshot.get("critical_missing") or []
    score = round((completeness["overall_pct"] * 0.65) + (endpoints["overall_pct"] * 0.35), 1)
    status = "ready" if score >= 80 and not critical_missing else "partial" if score >= 55 else "not_ready"
    return {
        "score": score,
        "status": status,
        "critical_missing": critical_missing[:5],
        "missing_sections": completeness["missing_sections"],
        "endpoint_gaps": [key for key, value in endpoints["items"].items() if not value],
    }


def build_patient_kpis(
    patient: dict[str, Any],
    *,
    state: str,
    management_track: str,
    agenda_board: dict[str, Any],
    signals: dict[str, Any],
) -> list[dict[str, Any]]:
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    completeness = compute_patient_cohort_completeness(patient, state)
    research = compute_patient_research_readiness(patient, state)
    endpoints = compute_patient_endpoint_readiness(patient, state)

    active_items = agenda_board.get("active_items", agenda_board.get("items", [])) or []
    due_now = sum(1 for item in active_items if item.get("status") in {"due", "overdue"})
    overdue = sum(1 for item in active_items if item.get("status") == "overdue")
    protocol_pct = _rate(sum(1 for item in active_items if item.get("status") not in {"overdue", "blocked"}), max(len(active_items), 1))

    if state in DIAGNOSTIC_STATES:
        control_label = "Completitud diagnóstica"
        control_value = f"{max(0, 100 - (len(signals.get('critical_missing') or []) * 20))}%"
        control_detail = "MRI, trigger de biopsia y PSA/PSAD determinan si el diagnóstico ya puede cerrarse."
    elif state == "localized_initial":
        control_label = "Ruta localizada"
        control_value = str(_latest(patient.get("biopsies") or [], "biopsy_date").get("isup_grade") or "ISUP N/D")
        control_detail = "Se prioriza estabilidad histológica, MRI y PROs para sostener o cambiar estrategia local."
    elif state in POSTLOCAL_STATES:
        control_label = "Control bioquímico"
        psa_value = latest_followup.get("psa_current")
        control_value = f"PSA {psa_value}" if _is_present(psa_value) else "PSA pendiente"
        control_detail = "PSA ultrasensible y PSADT definen ventana de rescate o intensificación."
    else:
        control_label = "Control de enfermedad"
        testosterone = latest_followup.get("testosterone_current")
        control_value = (
            f"Testosterona {testosterone} ng/dL"
            if _is_present(testosterone)
            else "Castración no documentada"
        )
        control_detail = "La secuencia sistémica depende de castración, biomarcadores y respuesta longitudinal."

    safety_alerts = len(signals.get("active_safety") or [])
    safety_detail = f"{safety_alerts} alerta(s) activa(s)" if safety_alerts else "Sin alertas estructuradas activas"
    if management_track in {"on_arpi", "systemic_surveillance", "palliative_overlay"}:
        safety_detail += " · bundle ADT / soporte concurrente"

    return [
        {
            "label": control_label,
            "value": control_value,
            "detail": control_detail,
            "tone": "good" if not signals.get("state_conflict_flag") else "warning",
        },
        {
            "label": "Adherencia a protocolo",
            "value": f"{protocol_pct:.1f}%",
            "detail": f"{due_now} pendiente(s) activas, {overdue} vencida(s).",
            "tone": _tone_from_pct(protocol_pct if not overdue else max(protocol_pct - 20, 0)),
        },
        {
            "label": "Calidad de datos",
            "value": f"{completeness['overall_pct']:.1f}%",
            "detail": "Patología, imagen, follow-up, PROs, biomarcadores y provenance estructurados.",
            "tone": completeness["tone"],
        },
        {
            "label": "Seguridad / soporte",
            "value": safety_detail,
            "detail": "Resume riesgo activo, salud ósea, soporte y toxicidad relevante para la decisión.",
            "tone": "warning" if safety_alerts else "good",
        },
        {
            "label": "Research readiness",
            "value": f"{research['score']:.1f}%",
            "detail": f"Endpoint readiness {endpoints['overall_pct']:.1f}% · cohort core {completeness['overall_pct']:.1f}%",
            "tone": _tone_from_pct(research["score"]),
        },
    ]


def build_analysis_dataset_row(patient: dict[str, Any], state: str, management_track: str, signals: dict[str, Any]) -> dict[str, Any]:
    identity = patient.get("identity") or {}
    latest_followup = _latest(patient.get("follow_ups") or [], "visit_date")
    latest_biopsy = _latest(patient.get("biopsies") or [], "biopsy_date")
    latest_imaging = _latest(patient.get("imaging") or [], "study_date")
    latest_genomic = patient.get("genomics") or {}
    completeness = compute_patient_cohort_completeness(patient, state)
    endpoints = compute_patient_endpoint_readiness(patient, state)
    return {
        "patient_uid": f"PT-{identity.get('id', '')}",
        "nss_hash_hint": str(identity.get("nss", ""))[-4:],
        "diagnosis_date": identity.get("diagnosis_date"),
        "reconciled_state": state,
        "management_track": management_track,
        "latest_psa": latest_followup.get("psa_current"),
        "latest_testosterone": latest_followup.get("testosterone_current"),
        "latest_biopsy_isup": latest_biopsy.get("isup_grade"),
        "latest_pirads": latest_imaging.get("pirads_score"),
        "latest_imaging_type": latest_imaging.get("study_type"),
        "current_treatment": latest_followup.get("current_treatment"),
        "line_of_therapy": _latest(patient.get("treatments") or [], "start_date").get("line_of_therapy"),
        "hrr_status": latest_genomic.get("hrr_overall"),
        "brca2_status": latest_genomic.get("brca2_status"),
        "msi_status": latest_genomic.get("msi_status"),
        "pros_available": bool(patient.get("pros")),
        "followup_count": len(patient.get("follow_ups") or []),
        "verified_document_count": completeness["verified_documents"],
        "cohort_completeness_pct": completeness["overall_pct"],
        "endpoint_readiness_pct": endpoints["overall_pct"],
        "state_conflict_flag": bool(signals.get("state_conflict_flag")),
    }


def summarize_cohort(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    if total == 0:
        return {
            "publishable_ready_count": 0,
            "research_ready_count": 0,
            "mexico_core_complete_count": 0,
            "document_verification_coverage_count": 0,
            "endpoint_ready_distribution": {},
            "cohort_average_completeness_pct": 0.0,
            "cohort_average_research_readiness_pct": 0.0,
        }

    completeness_values = []
    readiness_values = []
    publishable_ready = 0
    research_ready = 0
    mexico_core = 0
    document_ready = 0
    endpoint_distribution = {
        "time_to_histology": 0,
        "time_to_treatment": 0,
        "active_surveillance_exit": 0,
        "biochemical_recurrence": 0,
        "time_to_adt": 0,
        "time_to_crpc": 0,
        "line_duration": 0,
        "psa_kinetics": 0,
        "radiographic_progression": 0,
    }

    for record in records:
        state = str(record.get("reconciled_state") or record.get("latest_assessment", {}).get("state") or record.get("prior_history", {}).get("current_state") or "diagnostic_workup")
        completeness = compute_patient_cohort_completeness(record, state)
        readiness = compute_patient_research_readiness(record, state)
        endpoints = compute_patient_endpoint_readiness(record, state)
        completeness_values.append(completeness["overall_pct"])
        readiness_values.append(readiness["score"])
        if completeness["overall_pct"] >= 80 and endpoints["overall_pct"] >= 60:
            publishable_ready += 1
        if readiness["status"] != "not_ready":
            research_ready += 1
        if completeness["sections"]["mexico_core"] >= 80:
            mexico_core += 1
        if completeness["verified_documents"] > 0:
            document_ready += 1
        for key, value in endpoints["items"].items():
            if value:
                endpoint_distribution[key] += 1

    return {
        "publishable_ready_count": publishable_ready,
        "research_ready_count": research_ready,
        "mexico_core_complete_count": mexico_core,
        "document_verification_coverage_count": document_ready,
        "endpoint_ready_distribution": endpoint_distribution,
        "cohort_average_completeness_pct": round(sum(completeness_values) / total, 1),
        "cohort_average_research_readiness_pct": round(sum(readiness_values) / total, 1),
    }
