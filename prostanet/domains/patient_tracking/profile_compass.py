from __future__ import annotations

import json
from typing import Any

from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board, infer_management_track, longitudinal_item_sort_key
from prostanet.domains.patient_tracking.capture_flows import build_missing_input_capture_bundle
from prostanet.domains.patient_tracking.cohort_analytics import (
    build_patient_kpis,
    compute_patient_cohort_completeness,
    compute_patient_endpoint_readiness,
    compute_patient_research_readiness,
)
from prostanet.domains.patient_tracking.master_followup_plan import build_master_followup_plan
from prostanet.domains.patient_tracking.mhspc_evidence import (
    build_triplet_decision,
    is_mhspc_state,
    visible_trials_for_mhspc_state,
)
from prostanet.domains.patient_tracking.psa_line_monitor import build_psa_by_treatment_line
from prostanet.domains.patient_tracking.prognostic_impact import build_prognostic_impact_bundle
from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
from prostanet.domains.patient_tracking.risk_tools import build_risk_tools_panel
from prostanet.domains.patient_tracking.therapy_catalog import summarize_trial_backbones, trial_backbone
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label, therapy_select_options
from prostanet.shared.official_diagnosis import build_official_diagnosis_context, diagnosis_field_label


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCALIZED_STATES = {"localized_initial"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr"}
ADVANCED_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}

PRIMARY_QUESTION_MAP = {
    "diagnostic_workup": "¿Debemos confirmar histología, repetir MRI o activar biopsia?",
    "post_negative_biopsy_followup": "¿La señal persistente justifica re-biopsia o seguimiento?",
    "localized_initial": "¿Conviene vigilancia activa, cirugía o radioterapia hoy?",
    "post_prostatectomy": "¿Basta vigilancia o hay que acelerar rescate posoperatorio?",
    "recurrence_bcr": "¿Existe una ventana curativa de rescate o ya hay que intensificar?",
    "adt_progression_verification": "¿Es CRPC confirmado o primero hay que verificar castración?",
    "mcspc_oligo_metachronous": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC?",
    "mcspc_low_volume_sync_oligo": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC?",
    "mcspc_high_volume_sync": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC de novo de alto volumen?",
    "mcspc_high_volume_metachronous": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC metacrónico de alto volumen?",
    "mcspc_high_volume": "¿Qué intensificación sistémica y soporte concurrente corresponden en mHSPC?",
    "m0_crpc": "¿Debe intensificarse nmCRPC y con qué prioridad clínica?",
    "m1_crpc": "¿Cuál es la siguiente secuencia sistémica prioritaria según biomarcadores y seguridad?",
}

STATE_DISPLAY_MAP = {
    "diagnostic_workup": "Diagnóstico inicial",
    "post_negative_biopsy_followup": "Seguimiento tras biopsia benigna",
    "localized_initial": "Enfermedad localizada o regional N1M0",
    "post_prostatectomy": "Seguimiento posprostatectomía",
    "recurrence_bcr": "Recurrencia bioquímica",
    "adt_progression_verification": "Progresión bajo ADT / verificación",
    "mcspc_oligo_metachronous": "mHSPC oligometastásico metacrónico",
    "mcspc_low_volume_sync_oligo": "mHSPC sincrónico de bajo volumen",
    "mcspc_high_volume_sync": "mHSPC de alto volumen sincrónico",
    "mcspc_high_volume_metachronous": "mHSPC de alto volumen metacrónico",
    "mcspc_high_volume": "mHSPC de alto volumen",
    "m0_crpc": "CRPC sin metástasis",
    "m1_crpc": "CRPC metastásico",
}

ALGORITHM_EXPLANATIONS = {
    "capra": {
        "what_score_means": "Resume riesgo clínico pretratamiento en enfermedad localizada combinando PSA, Gleason, T clínico, edad y biopsia.",
        "risk_interpretation": "A mayor CAPRA, mayor probabilidad de recurrencia bioquímica tras tratamiento local.",
        "clinical_decision_supported": "Ayuda a refinar vigilancia activa vs tratamiento local y la intensidad del counseling prequirúrgico.",
    },
    "briganti": {
        "what_score_means": "Estima el riesgo de compromiso ganglionar pélvico antes de cirugía.",
        "risk_interpretation": "Riesgos altos apoyan discutir linfadenectomía extendida y carga ganglionar esperada.",
        "clinical_decision_supported": "Refina la decisión de disección ganglionar en candidatos quirúrgicos.",
    },
    "partin": {
        "what_score_means": "Distribuye la probabilidad entre órgano confinado, extensión extracapsular, invasión seminal y ganglios.",
        "risk_interpretation": "La categoría dominante ayuda a anticipar patología y a modular estrategia local.",
        "clinical_decision_supported": "Apoya counseling preoperatorio y expectativa patológica.",
    },
    "mskcc_preop": {
        "what_score_means": "Estima la probabilidad de enfermedad órgano-confinada y otros desenlaces patológicos preoperatorios.",
        "risk_interpretation": "Mayor probabilidad órgano-confinada sugiere cirugía con expectativa patológica más favorable.",
        "clinical_decision_supported": "Apoya selección y counseling quirúrgico.",
    },
    "capra_s": {
        "what_score_means": "Resume riesgo posprostatectomía usando patología final, márgenes, ganglios y PSA.",
        "risk_interpretation": "A mayor CAPRA-S, mayor riesgo de recurrencia y necesidad de vigilancia/re-evaluación más estrecha.",
        "clinical_decision_supported": "Ayuda a definir seguimiento posoperatorio y ventana de rescate.",
    },
    "predict_prostate": {
        "what_score_means": "Modelo pronóstico de mortalidad específica y beneficio relativo de tratamiento local.",
        "risk_interpretation": "El resultado contextualiza beneficio esperado frente a expectativa de vida y riesgo competitivo.",
        "clinical_decision_supported": "Apoya decisión compartida entre vigilancia, cirugía y radioterapia.",
    },
}

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


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _format_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "No disponible"
    return f"{number:.1f}%"


def _format_date(value: Any) -> str:
    return str(value or "Sin fecha")


def _text_tone(value: Any, *, good: set[str] | None = None, bad: set[str] | None = None) -> str:
    text = str(value or "").lower()
    if good and text in {item.lower() for item in good}:
        return "success"
    if bad and text in {item.lower() for item in bad}:
        return "danger"
    return "neutral"


def _parse_json_blob(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _latest_item(items: list[dict[str, Any]], *date_keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in date_keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[0]


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "positivo", "positive", "realizado", "realizada", "iniciado", "iniciada", "completo", "completa"}


def _yes_no(value: Any) -> str:
    if value in (None, ""):
        return "No documentado"
    return "Sí" if _truthy(value) else "No"


def _source_badge(label: str, date_value: Any = "") -> str:
    if not label:
        return ""
    if date_value:
        return f"Fuente: {label} · {date_value}"
    return f"Fuente: {label}"


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return ""


def _build_family_history_summary(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "Sin antecedente hereditario estructurado."
    parts = []
    for entry in entries[:3]:
        relative = entry.get("relative_type") or "Familiar"
        cancer = entry.get("cancer_type") or "cáncer"
        mutation = entry.get("known_mutation")
        detail = f"{relative}: {cancer}"
        if _is_present(mutation) and mutation != "Desconocido":
            detail += f" ({mutation})"
        parts.append(detail)
    return "; ".join(parts)


def _build_pro_delta_summary(pros: list[dict[str, Any]]) -> list[str]:
    if len(pros) < 2:
        return []
    baseline = pros[0]
    latest = pros[-1]
    bullets = []
    for label, key, reverse_good in (
        ("IPSS", "ipss_total", True),
        ("IIEF-5", "iief5_score", False),
        ("EQ-5D VAS", "eq5d_vas", False),
    ):
        base = _safe_float(baseline.get(key))
        current = _safe_float(latest.get(key))
        if base is None or current is None:
            continue
        delta = current - base
        if abs(delta) < 0.5:
            bullets.append(f"{label} sin cambio clínicamente relevante frente al basal.")
            continue
        direction = "mejoría" if (delta < 0 and reverse_good) or (delta > 0 and not reverse_good) else "deterioro"
        bullets.append(f"{label}: {direction} de {abs(delta):.1f} puntos frente al basal.")
    return bullets


def _module_data_contracts() -> list[dict[str, Any]]:
    return [
        {
            "module": "algorithm_panels",
            "inputs_required": ["validated_algorithms", "raw score inputs", "clinical context"],
            "primary_source": "assessment modular + cálculos estructurados",
            "accepted_truth_status": ["captured", "verified"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "therapy_checkpoints",
            "inputs_required": ["labs", "biomarcadores", "imagen", "toxicidad", "línea terapéutica"],
            "primary_source": "agenda longitudinal + longitudinal intelligence",
            "accepted_truth_status": ["captured", "verified"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "document_board",
            "inputs_required": ["documento fuente", "facts verificados"],
            "primary_source": "source_documents + verified_document_facts",
            "accepted_truth_status": ["verified"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "evidence_applicability",
            "inputs_required": ["estado reconciliado", "trial matching", "gaps de elegibilidad"],
            "primary_source": "pivotal matches + reconciliación longitudinal",
            "accepted_truth_status": ["captured", "verified", "derived"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "psa_observability",
            "inputs_required": ["biomarker_longitudinal", "follow_up_visits", "treatment_history"],
            "primary_source": "serie longitudinal de PSA",
            "accepted_truth_status": ["captured", "derived"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "clinical_journey",
            "inputs_required": ["eventos clínicos", "visitas", "tratamientos", "documentos"],
            "primary_source": "event graph longitudinal",
            "accepted_truth_status": ["captured", "verified", "derived"],
            "modifies_clinical_decision": False,
        },
        {
            "module": "comorbidity_frailty_fitness",
            "inputs_required": ["CCI", "G8", "Fried", "ECOG", "Child-Pugh"],
            "primary_source": "baseline + follow-up estructurado",
            "accepted_truth_status": ["captured", "verified"],
            "modifies_clinical_decision": True,
        },
        {
            "module": "adt_side_effects",
            "inputs_required": ["perfil CV/metabólico", "salud ósea", "fatiga", "cognición"],
            "primary_source": "seguimiento ADT",
            "accepted_truth_status": ["captured", "verified", "derived"],
            "modifies_clinical_decision": True,
        },
    ]


def _label_for_field(field_name: str) -> str:
    labels = {
        "line_of_therapy_number": "número de línea terapéutica",
        "line_of_therapy_context": "contexto clínico de línea",
        "g8_food_intake": "G8: ingesta de alimentos",
        "g8_weight_loss": "G8: pérdida de peso",
        "g8_mobility": "G8: movilidad",
        "g8_neuropsych": "G8: estado neuropsicológico",
        "g8_bmi": "G8: categoría BMI",
        "g8_medications": "G8: medicamentos diarios",
        "g8_self_health": "G8: percepción de salud",
        "weight_loss_6m_pct": "pérdida de peso en 6 meses",
        "low_activity": "actividad física reducida",
        "slow_gait": "marcha lenta",
        "weak_grip": "fuerza de prensión baja",
        "mini_cog_score": "Mini-Cog",
        "fatigue_score": "fatiga",
        "cv_risk_documented": "riesgo cardiovascular documentado",
        "drug_interaction_reviewed": "revisión de interacciones",
        "psma_positive": "PSMA",
        "hrr_status": "HRR / BRCA",
        "msi_status": "MSI / TMB",
        "castrate_testosterone_status": "estado de castración",
        "testosterone": "testosterona",
    }
    return labels.get(field_name, diagnosis_field_label(field_name))


def _build_missing_input_actions(
    *,
    patient: dict[str, Any],
    state: str,
    management_track: str,
    missing_inputs_by_panel: dict[str, list[str]],
    therapy_checkpoints: list[dict[str, Any]],
    agenda_items: list[dict[str, Any]],
    copilot: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str]:
    bundle = build_missing_input_capture_bundle(
        patient=patient,
        state=state,
        management_track=management_track,
        missing_inputs_by_panel=missing_inputs_by_panel,
        therapy_checkpoints=therapy_checkpoints,
        agenda_items=agenda_items,
        copilot=copilot,
    )
    actions = []
    for task in bundle.get("tasks", []):
        actions.append(
            {
                **task,
                "fields": [_label_for_field(field) for field in (task.get("raw_fields") or [])[:8]],
            }
        )
    return actions[:8], bundle.get("intake_capture_target", ""), bundle.get("followup_capture_target", "")


def _build_psa_observability(patient: dict[str, Any], copilot: dict[str, Any]) -> dict[str, Any]:
    monitoring = build_psa_by_treatment_line(patient)
    if monitoring.get("has_data"):
        return monitoring
    trajectory = ((copilot or {}).get("response_visualization") or {}).get("psa_trajectory") or {}
    points = list(trajectory.get("points") or [])
    if not points:
        return {"has_data": False, "points": [], "treatment_bands": [], "line_segments": [], "line_events": [], "metrics": {}, "source": "missing"}
    monitoring["points"] = points
    monitoring["treatment_bands"] = trajectory.get("treatment_bands") or []
    return monitoring


def _build_clinical_journey_events(patient: dict[str, Any], state: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    identity = patient.get("identity") or {}
    if identity.get("diagnosis_date"):
        events.append({"date": identity.get("diagnosis_date"), "title": "Diagnóstico", "origin": "patient_identity", "decision": STATE_DISPLAY_MAP.get(state, "Ruta clínica actual")})
    for biopsy in patient.get("biopsies") or []:
        events.append({
            "date": biopsy.get("biopsy_date"),
            "title": f"Biopsia / patología GG{biopsy.get('isup_grade')}" if _is_present(biopsy.get("isup_grade")) else "Biopsia / patología",
            "origin": "biopsy_details",
            "decision": biopsy.get("risk_group") or "Confirmación histológica",
        })
    for imaging in patient.get("imaging") or []:
        events.append({
            "date": imaging.get("study_date"),
            "title": imaging.get("study_type") or "Imagen",
            "origin": "imaging_studies",
            "decision": imaging.get("psma_result") or imaging.get("clinical_impact") or "Reestadificación",
        })
    for treatment in patient.get("treatments") or []:
        events.append({
            "date": treatment.get("start_date"),
            "title": regimen_label(treatment.get("drug_scheme")) or "Cambio de tratamiento",
            "origin": "treatment_history",
            "decision": _first_nonempty(
                f"L{treatment.get('line_of_therapy_number')}: {LINE_CONTEXT_LABELS.get(str(treatment.get('line_of_therapy_context') or ''), treatment.get('line_of_therapy_context') or '')}".strip(": "),
                treatment.get("line_of_therapy_context"),
                "Secuenciación sistémica",
            ),
        })
    for visit in patient.get("follow_ups") or []:
        events.append({
            "date": visit.get("visit_date"),
            "title": "Visita de seguimiento",
            "origin": "follow_up_visits",
            "decision": visit.get("disease_status") or visit.get("current_treatment") or "Seguimiento longitudinal",
        })
    for response in patient.get("response_assessments") or []:
        events.append({
            "date": response.get("assessment_date"),
            "title": "Re-evaluación terapéutica",
            "origin": "response_assessments",
            "decision": response.get("response_category") or "Sin categoría documentada",
        })
    for event in patient.get("patient_events") or []:
        if str(event.get("event_type") or "") not in {"therapy_started", "therapy_line_changed"}:
            continue
        payload = event.get("payload") or {}
        events.append({
            "date": event.get("event_date"),
            "title": payload.get("label") or "Cambio de línea terapéutica",
            "origin": "patient_events",
            "decision": payload.get("decision") or "Secuenciación sistémica actualizada",
        })
    for document in (patient.get("source_documents") or [])[:20]:
        if document.get("verification_status") == "verified":
            events.append({
                "date": document.get("updated_at") or document.get("created_at"),
                "title": document.get("title") or document.get("file_name") or "Documento verificado",
                "origin": "source_documents",
                "decision": "Documento con facts comprometidos al longitudinal",
            })
    events = [event for event in events if event.get("date")]
    return sorted(events, key=lambda item: str(item.get("date")), reverse=True)[:20]


def _build_agenda_resolution_trace(archived_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traces = []
    for item in archived_items[:10]:
        traces.append(
            {
                "title": item.get("title"),
                "status": item.get("status"),
                "resolved_at": item.get("completed_at") or item.get("updated_at") or item.get("due_at"),
                "summary": item.get("summary"),
            }
        )
    return traces


def _build_data_freshness(patient: dict[str, Any], state: str) -> list[dict[str, Any]]:
    followup = _latest_item(patient.get("follow_ups", []), "visit_date")
    biopsy = _latest_item(patient.get("biopsies", []), "biopsy_date")
    imaging = _latest_item(patient.get("imaging", []), "study_date")
    mri_fact = _latest_item(patient.get("mri_facts", []), "fact_date")
    genomics = patient.get("genomics") or {}
    latest_pro = _latest_item(patient.get("pros", []), "assessment_date")
    entries = [
        {
            "label": "PSA",
            "value": _first_nonempty(followup.get("psa_current"), patient.get("baseline", {}).get("baseline_psa"), "No documentado"),
            "date": _first_nonempty(followup.get("visit_date"), patient.get("identity", {}).get("diagnosis_date"), "Sin fecha"),
        },
        {
            "label": "Patología",
            "value": (
                f"GG{biopsy.get('isup_grade')}"
                if _is_present(biopsy.get("isup_grade"))
                else "Sin confirmación histológica"
            ),
            "date": _first_nonempty(biopsy.get("biopsy_date"), "Sin fecha"),
        },
        {
            "label": "MRI / imagen decisora",
            "value": _first_nonempty(
                mri_fact.get("mpmri_quality"),
                imaging.get("study_type"),
                patient.get("baseline", {}).get("metastasis_site"),
                "No documentada",
            ),
            "date": _first_nonempty(mri_fact.get("fact_date"), imaging.get("study_date"), "Sin fecha"),
        },
        {
            "label": "Biomarcador",
            "value": _first_nonempty(
                genomics.get("test_type"),
                genomics.get("hrr_overall"),
                genomics.get("decipher_risk"),
                "No documentado",
            ),
            "date": _first_nonempty(genomics.get("test_date"), "Sin fecha"),
        },
        {
            "label": "PRO",
            "value": (
                f"IPSS {latest_pro.get('ipss_total')}"
                if _is_present(latest_pro.get("ipss_total"))
                else "Sin PROs recientes"
            ),
            "date": _first_nonempty(latest_pro.get("assessment_date"), "Sin fecha"),
        },
    ]
    if state in ADVANCED_STATES | {"adt_progression_verification"}:
        entries.insert(
            1,
            {
                "label": "Testosterona",
                "value": _first_nonempty(followup.get("testosterone_current"), patient.get("baseline", {}).get("testosterone_baseline"), "No documentada"),
                "date": _first_nonempty(followup.get("visit_date"), patient.get("identity", {}).get("diagnosis_date"), "Sin fecha"),
            },
        )
    return entries


def _build_primary_evidence_anchor(display_result: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = []
    for source in display_result.get("source_citations", [])[:]:
        role = source.get("evidence_role")
        if role == "primary_guideline":
            anchors.append(
                {
                    "label": source.get("guideline_or_trial") or source.get("title"),
                    "title": source.get("title"),
                    "url": source.get("doi_or_url") or "",
                    "local_pdf_path": source.get("local_pdf_path") or "",
                }
            )
    return anchors[:3]


def _merge_unique_text(primary: list[str], extra: list[str], *, limit: int = 6) -> list[str]:
    merged: list[str] = []
    for item in primary + extra:
        if not _is_present(item):
            continue
        text = str(item).strip()
        if text and text not in merged:
            merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def _response_tone(label: str) -> str:
    text = str(label or "").strip().lower()
    if text in {"pd", "progressive_disease", "progresion", "progresión", "progression"}:
        return "danger"
    if text in {"cr", "pr", "respuesta", "partial_response", "complete_response"}:
        return "success"
    if text in {"sd", "stable_disease", "estable"}:
        return "neutral"
    return "neutral"


def _build_parallel_modifier_bundle(copilot: dict[str, Any], state: str) -> dict[str, Any]:
    modifiers: list[dict[str, str]] = []
    course_adjusters: list[str] = []
    next_actions: list[str] = []
    safety_modifiers: list[str] = []

    def add_modifier(label: str, detail: Any, tone: str = "neutral") -> None:
        if not _is_present(detail):
            return
        detail_text = str(detail).strip()
        if any(item["label"] == label and item["detail"] == detail_text for item in modifiers):
            return
        modifiers.append({"label": label, "detail": detail_text, "tone": tone})

    def add_course(item: Any) -> None:
        if _is_present(item):
            course_adjusters.append(str(item).strip())

    def add_next(item: Any) -> None:
        if _is_present(item):
            next_actions.append(str(item).strip())

    def add_safety(item: Any) -> None:
        if _is_present(item):
            safety_modifiers.append(str(item).strip())

    alerts = copilot.get("clinical_alerts") or []
    critical_alert = next((item for item in alerts if str(item.get("severity", "")).lower() == "critical"), None)
    if not critical_alert:
        critical_alert = next((item for item in alerts if str(item.get("severity", "")).lower() == "warning"), None)
    if critical_alert:
        add_modifier("Seguridad activa", critical_alert.get("title"), "danger" if str(critical_alert.get("severity", "")).lower() == "critical" else "warning")
        add_course(critical_alert.get("title"))
        add_next(critical_alert.get("recommended_action"))
        add_safety(critical_alert.get("title"))

    fitness = copilot.get("therapeutic_fitness") or {}
    fit_score = fitness.get("fit_score") or {}
    frailty = fitness.get("frailty") or {}
    egfr = fitness.get("egfr") or {}
    child_pugh = fitness.get("child_pugh") or {}
    competing_mortality = fitness.get("competing_mortality") or {}
    fit_category = str(fit_score.get("category") or "")
    frailty_status = str(frailty.get("status") or "")
    fitness_modifier_added = False
    if fit_score.get("is_complete") is False:
        missing_fit_inputs = fit_score.get("missing_inputs") or []
        fit_gap_text = "Faltan inputs para definir intensidad terapéutica"
        if missing_fit_inputs:
            fit_gap_text += f": {', '.join(missing_fit_inputs[:3])}"
        add_modifier("Fitness terapéutica", fit_gap_text, "warning")
        add_course("ajustar intensidad tras completar fitness terapéutica")
        add_next("Completar fitness terapéutica para confirmar intensidad del tratamiento")
        add_safety("La intensidad terapéutica sigue pendiente por datos de fitness incompletos.")
        fitness_modifier_added = True
    elif fit_category and fit_category != "Fit":
        add_modifier("Fitness terapéutica", f"{fit_category}: {fit_score.get('recommended_intensity', 'ajustar intensidad')}", "danger" if fit_category == "Frail" else "warning")
        add_course(fit_score.get("recommended_intensity"))
        add_safety(f"Fitness {fit_category.lower()} para intensificación estándar.")
        fitness_modifier_added = True
    elif frailty_status and frailty_status != "Fit":
        add_modifier("Fragilidad", f"{frailty_status}: {', '.join(frailty.get('clinical_actions', [])[:1]) or 'requiere ajuste de intensidad'}", "warning")
        add_course(", ".join(frailty.get("clinical_actions", [])[:1]))
        fitness_modifier_added = True
    if egfr.get("egfr") is not None and float(egfr.get("egfr") or 0) < 60:
        if not fitness_modifier_added:
            add_modifier("Función renal", f"eGFR {egfr.get('egfr')} mL/min ({egfr.get('stage', 'sin estadio')})", "warning")
        add_next(", ".join(egfr.get("clinical_actions", [])[:1]))
        add_safety(f"Función renal reducida: eGFR {egfr.get('egfr')} mL/min.")
    if str(child_pugh.get("grade") or "") in {"B", "C"}:
        if not fitness_modifier_added:
            add_modifier("Riesgo hepático", f"Child-Pugh {child_pugh.get('grade')}", "danger" if str(child_pugh.get("grade")) == "C" else "warning")
        add_next(", ".join(child_pugh.get("clinical_actions", [])[:1]))
        add_safety(f"Riesgo hepático Child-Pugh {child_pugh.get('grade')}.")
    if (competing_mortality.get("mortality_5yr_pct") or 0) >= 30:
        if not fitness_modifier_added:
            add_modifier("Mortalidad competitiva", f"{competing_mortality.get('mortality_5yr_pct')}% a 5 años", "warning")
        add_course(competing_mortality.get("recommendation"))
        add_safety(competing_mortality.get("recommendation"))

    precision = copilot.get("precision_genomics") or {}
    precision_actions = [
        value.get("clinical_action")
        for value in precision.values()
        if isinstance(value, dict) and _is_present(value.get("clinical_action"))
    ]
    if precision_actions:
        add_modifier("Biología accionable", f"{precision.get('actionable_count', len(precision_actions))} vía(s): {precision_actions[0]}", "success")
        for action in precision_actions[:2]:
            add_course(action)
    nepc = precision.get("nepc_suspicion") or {}
    if nepc.get("suspected"):
        add_modifier("Sospecha NEPC", f"Score {nepc.get('score', 'N/D')} con vigilancia de plasticidad de linaje", "danger")
        add_course("Revalorar biopsia y secuenciación platinum-based si la sospecha neuroendocrina se sostiene.")
        add_safety("Sospecha de transformación neuroendocrina / plasticidad de linaje.")

    ddi = copilot.get("ddi_review") or {}
    interactions = ddi.get("interactions") or []
    contraindicated = [item for item in interactions if str(item.get("severity", "")).lower() == "contraindicated"]
    major = [item for item in interactions if str(item.get("severity", "")).lower() in {"contraindicated", "major"}]
    if major:
        lead = contraindicated[0] if contraindicated else major[0]
        detail = (
            f"{len(contraindicated)} contraindicación(es) y {max(len(major) - len(contraindicated), 0)} interacción(es) mayor(es)."
            if contraindicated else
            f"{len(major)} interacción(es) mayor(es) activas."
        )
        add_modifier("Interacciones / formulario", detail, "danger" if contraindicated else "warning")
        add_next(lead.get("recommended_action"))
        add_safety(lead.get("clinical_impact") or lead.get("mechanism"))

    pro_intelligence = copilot.get("pro_intelligence") or {}
    pro_alerts = pro_intelligence.get("alerts") or []
    lead_pro = next((item for item in pro_alerts if str(item.get("severity", "")).lower() == "critical"), None)
    if not lead_pro:
        lead_pro = next((item for item in pro_alerts if str(item.get("severity", "")).lower() == "warning"), None)
    if lead_pro:
        add_modifier("Resultados reportados por el paciente", lead_pro.get("title"), "danger" if str(lead_pro.get("severity", "")).lower() == "critical" else "warning")
        add_course(lead_pro.get("title"))
        add_next(lead_pro.get("recommended_action"))
        add_safety(lead_pro.get("message"))

    oligo = copilot.get("oligomet_assessment") or {}
    if oligo.get("has_data"):
        mdt = oligo.get("mdt_decision") or {}
        sbrt = oligo.get("sbrt_eligibility") or {}
        decision_code = str(mdt.get("decision") or "")
        if decision_code:
            tone = "success" if decision_code == "mdt_plus_systemic" else "warning" if decision_code in {"confirm_psma", "biopsy_then_decide"} else "neutral"
            add_modifier("Carga oligometastásica", mdt.get("rationale") or f"{oligo.get('lesion_count', 0)} lesiones documentadas", tone)
            add_course(mdt.get("rationale"))
        elif sbrt.get("eligible"):
            add_modifier("SBRT/MDT", "Elegible para discusión MDT/SBRT focal", "success")
            add_next("Discutir MDT/SBRT en tumor board si la imagen funcional y la carga oligometastásica se sostienen.")

    response = copilot.get("latest_response_assessment") or {}
    response_label = _first_nonempty(response.get("overall_response"), response.get("recist_category"), response.get("psa_response_category"))
    if response_label:
        tone = _response_tone(response_label)
        detail = f"{response_label} ({_first_nonempty(response.get('assessment_date'), response.get('created_at'), 'sin fecha')})"
        add_modifier("Respuesta terapéutica", detail, tone)
        if tone == "danger":
            add_course("La progresión objetiva obliga re-evaluación de línea y reestadificación dirigida.")
            add_next("Confirmar progresión y redefinir secuencia terapéutica / imagen de decisión.")
            add_safety("Progresión terapéutica reciente documentada.")

    return {
        "active_modifiers": modifiers[:6],
        "what_could_change_course": _merge_unique_text([], course_adjusters, limit=6),
        "next_actions": _merge_unique_text([], next_actions, limit=6),
        "safety_modifiers": _merge_unique_text([], safety_modifiers, limit=4),
    }


def _build_clinical_compass(
    *,
    patient: dict[str, Any],
    state: str,
    reconciliation: dict[str, Any],
    display_assessment: dict[str, Any],
    raw_assessment: dict[str, Any],
    state_timeline: list[dict[str, Any]],
    diagnosis_context: dict[str, Any],
    copilot_modifiers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    nccn = display_result.get("nccn_primary", {}) if display_result else {}
    latest_event = state_timeline[-1] if state_timeline else {}
    monitoring = display_result.get("monitoring_plan", {}) if display_result else {}
    decision_quality = display_result.get("decision_quality", {}) if display_result else {}
    state_conflict = bool(reconciliation.get("state_conflict_flag"))
    freshness = _build_data_freshness(patient, state)
    last_decisive = freshness[1] if state in DIAGNOSTIC_STATES and len(freshness) > 1 else freshness[0]
    current_diagnosis = diagnosis_context.get("official_diagnosis") or _first_nonempty(
        display_assessment.get("module_label"),
        STATE_DISPLAY_MAP.get(state),
        "Diagnóstico en consolidación",
    )
    operational_module_label = _first_nonempty(display_assessment.get("module_label"), STATE_DISPLAY_MAP.get(state), state)
    modifier_bundle = copilot_modifiers or {}
    what_could_change_course = _merge_unique_text(
        _as_list(display_result.get("decision_changing_inputs"))[:4] or _as_list(display_result.get("missing_critical_inputs"))[:4],
        modifier_bundle.get("what_could_change_course", []),
        limit=6,
    )
    next_actions = _merge_unique_text(
        _as_list(monitoring.get("actions"))[:4],
        modifier_bundle.get("next_actions", []),
        limit=6,
    )
    return {
        "current_diagnosis": current_diagnosis,
        "official_diagnosis": current_diagnosis,
        "official_diagnosis_status": diagnosis_context.get("official_diagnosis_status", "missing"),
        "official_diagnosis_missing_fields": diagnosis_context.get("official_diagnosis_missing_fields", []),
        "official_diagnosis_source_summary": diagnosis_context.get("official_diagnosis_source_summary", ""),
        "operational_module_label": operational_module_label,
        "current_stage_label": _first_nonempty(STATE_DISPLAY_MAP.get(state), state) if state_conflict else operational_module_label,
        "explicit_stage_label": _first_nonempty(STATE_DISPLAY_MAP.get(reconciliation.get("explicit_state")), reconciliation.get("explicit_state")),
        "state_conflict_flag": state_conflict,
        "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
        "management_intent_status": _first_nonempty(latest_event.get("management_intent_status_label"), "Pendiente de confirmación"),
        "event_kind_label": _first_nonempty(latest_event.get("event_kind_label"), "Recomendación generada"),
        "primary_clinical_question": PRIMARY_QUESTION_MAP.get(state, "¿Cuál es la siguiente mejor decisión clínica?"),
        "recommended_direction": (
            "La etapa longitudinal reconciliada requiere confirmar transición y reemitir recomendación modular sobre el estado vigente."
            if state_conflict
            else _first_nonempty(nccn.get("trayectoria_recomendada"), nccn.get("recommendation"), "Sin dirección priorizada")
        ),
        "why_this_now": _as_list(nccn.get("fundamentos_personalizados"))[:3] or _as_list(display_result.get("report_sections", {}).get("risk_features"))[:3],
        "what_could_change_course": what_could_change_course,
        "next_actions": next_actions,
        "monitoring_cadence": _first_nonempty(monitoring.get("cadence"), "Sin cadencia estructurada"),
        "data_freshness": freshness,
        "last_decisive_data": last_decisive,
        "evidence_anchor": _build_primary_evidence_anchor(display_result),
        "confidence_category": _first_nonempty(decision_quality.get("confidence_category"), "No documentada"),
        "recommendation_family": "Estado reconciliado por confirmar" if state_conflict else _first_nonempty(decision_quality.get("recommendation_family"), raw_result.get("recommendation_family"), "No documentada"),
        "decision_changing_inputs": _as_list(display_result.get("decision_changing_inputs")),
        "why_not_more_confident": _as_list(decision_quality.get("why_not_more_confident")) or _as_list(display_result.get("why_not_more_confident")),
        "active_modifiers": modifier_bundle.get("active_modifiers", []),
        "safety_modifiers": modifier_bundle.get("safety_modifiers", []),
    }


def _localized_decision_board(raw_result: dict[str, Any]) -> dict[str, Any]:
    options = []
    for item in raw_result.get("eligible_treatments", []):
        options.append(
            {
                "label": item.get("name", "Opción"),
                "value": item.get("priority", "eligible"),
                "tone": "success" if item.get("priority") in {"preferred", "eligible"} else "neutral",
                "detail": item.get("notes", ""),
            }
        )
    not_prioritized = _as_list(raw_result.get("not_recommended"))
    if not_prioritized:
        options.append(
            {
                "label": "No priorizar",
                "value": not_prioritized[0],
                "tone": "warning",
                "detail": "Se mantiene visible para la conversación clínica, pero no como trayectoria principal.",
            }
        )
    return {
        "title": "Decision board local",
        "subtitle": "Qué trayectorias siguen abiertas hoy según la etapa actual.",
        "items": options,
        "bullets": _as_list(raw_result.get("nccn_primary", {}).get("alternativas_razonables"))[:3],
    }


def _localized_context_panel(patient: dict[str, Any], raw_assessment: dict[str, Any]) -> dict[str, Any]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    latest_biopsy = _latest_item(patient.get("biopsies", []), "biopsy_date")
    latest_imaging = _latest_item(patient.get("imaging", []), "study_date")
    items = [
        {"label": "PI-RADS previo", "value": _first_nonempty(payload.get("prior_mpmri_pirads_score"), "No documentado")},
        {"label": "Biopsia dirigida previa", "value": _first_nonempty(payload.get("prior_mpmri_targeted_biopsy_status"), "No documentada")},
        {"label": "PRECISE", "value": _first_nonempty(latest_imaging.get("precise_score"), "No documentado")},
        {"label": "Patrón 4", "value": _first_nonempty(payload.get("percent_pattern_4"), latest_biopsy.get("percent_pattern_4"), "No documentado")},
        {"label": "Cribriforme", "value": "Sí" if _first_nonempty(payload.get("cribriform_pattern"), latest_biopsy.get("patron_cribiforme")) in (1, "1", True) else "No"},
        {"label": "Carcinoma intraductal", "value": "Sí" if _first_nonempty(payload.get("intraductal_carcinoma"), latest_biopsy.get("carcinoma_intraductal")) in (1, "1", True) else "No"},
        {"label": "Variante histológica adversa", "value": _first_nonempty(payload.get("adverse_histology_variant_type"), "No documentada")},
    ]
    bullets = []
    classifier = payload.get("genomic_classifier")
    if _is_present(classifier) and classifier != "No realizado":
        bullets.append(f"{classifier} documentado con resultado {_first_nonempty(payload.get('genomic_classifier_result'), 'sin resultado estructurado')}.")
    family_history = _build_family_history_summary(patient.get("family_history", []))
    if family_history:
        bullets.append(f"Historia familiar / germinal: {family_history}")
    return {
        "title": "Contexto anatómico y patológico",
        "subtitle": "Datos que modulan elegibilidad real de vigilancia activa y decisión local.",
        "items": items,
        "bullets": bullets,
    }


def _localized_shared_decision_panel(patient: dict[str, Any], raw_assessment: dict[str, Any], display_result: dict[str, Any]) -> dict[str, Any]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    pros = patient.get("pros", [])
    baseline_pro = pros[0] if pros else {}
    items = [
        {"label": "IPSS basal", "value": _first_nonempty(payload.get("ipss_score"), baseline_pro.get("ipss_total"), patient.get("demographics", {}).get("ipss_score"), "No documentado")},
        {"label": "IIEF-5 basal", "value": _first_nonempty(payload.get("iief5_score"), baseline_pro.get("iief5_score"), patient.get("demographics", {}).get("iief5_score"), "No documentado")},
        {"label": "QoL urinaria basal", "value": _first_nonempty(payload.get("baseline_urinary_qol"), "No documentada")},
        {"label": "QoL sexual basal", "value": _first_nonempty(payload.get("baseline_sexual_qol"), "No documentada")},
        {"label": "QoL intestinal basal", "value": _first_nonempty(payload.get("baseline_bowel_qol"), "No documentada")},
    ]
    delta_bullets = _build_pro_delta_summary(pros)
    return {
        "title": "Decisión compartida y funcionalidad basal",
        "subtitle": "Base funcional y de beneficio absoluto antes de definir cirugía, radioterapia o vigilancia.",
        "items": items,
        "bullets": delta_bullets or _as_list(display_result.get("nccn_primary", {}).get("mensaje_para_toma_de_decisiones_compartida")) or _as_list(display_result.get("supportive_evidence_context"))[:2],
    }


def _diagnostic_panel(patient: dict[str, Any], raw_assessment: dict[str, Any]) -> list[dict[str, Any]]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    latest_plan = _latest_item(patient.get("diagnostic_plans", []), "plan_date")
    latest_mri = _latest_item(patient.get("mri_facts", []), "fact_date")
    latest_trigger = _latest_item(patient.get("biopsy_triggers", []), "trigger_date")
    return [
        {
            "title": "Ruta diagnóstica activa",
            "subtitle": "Qué debe pasar ahora para confirmar o reabrir el diagnóstico.",
            "items": [
                {"label": "Plan actual", "value": _first_nonempty(latest_plan.get("plan_type"), "Ruta diagnóstica")},
                {"label": "Siguiente acción", "value": _first_nonempty(latest_plan.get("next_action"), latest_plan.get("recommended_pathway"), "Pendiente de confirmar")},
                {"label": "PSAD", "value": _first_nonempty(payload.get("psad"), "No documentado")},
                {"label": "PI-RADS", "value": _first_nonempty(latest_mri.get("pirads_score"), payload.get("pirads_score"), "No documentado")},
            ],
            "bullets": _as_list(latest_plan.get("trigger_conditions"))[:3],
        },
        {
            "title": "MRI y disparador de biopsia",
            "subtitle": "Calidad de imagen y condiciones que hoy cambian la conducta.",
            "items": [
                {"label": "Calidad MRI", "value": _first_nonempty(latest_mri.get("mpmri_quality"), "No documentada")},
                {"label": "Lesión índice", "value": _first_nonempty(latest_mri.get("lesion_location"), payload.get("index_lesion_location"), "No especificada")},
                {"label": "Trigger de biopsia", "value": _first_nonempty(latest_trigger.get("trigger_reason"), "No documentado")},
                {"label": "Vía prevista", "value": _first_nonempty(latest_trigger.get("planned_biopsy_route"), payload.get("planned_biopsy_route"), "No definida")},
            ],
            "bullets": _as_list(latest_trigger.get("activation_conditions"))[:3],
        },
        {
            "title": "Riesgo hereditario y re-biopsia",
            "subtitle": "Información familiar y previa que cambia el umbral diagnóstico.",
            "items": [
                {"label": "Historia familiar", "value": _build_family_history_summary(patient.get("family_history", []))},
                {"label": "Estado germinal", "value": _first_nonempty(payload.get("germline_status"), "No documentado")},
                {"label": "Biopsias previas", "value": _first_nonempty(payload.get("prior_biopsy_count"), "No documentado")},
                {"label": "MRI dirigida previa", "value": _first_nonempty(payload.get("prior_biopsy_mri_targeted"), "No documentado")},
            ],
            "bullets": [],
        },
    ]


def _localized_panels(patient: dict[str, Any], raw_assessment: dict[str, Any], display_result: dict[str, Any], raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    panels = [
        _localized_decision_board(raw_result),
        _localized_context_panel(patient, raw_assessment),
        _localized_shared_decision_panel(patient, raw_assessment, display_result),
    ]
    eligible_names = {item.get("name") for item in raw_result.get("eligible_treatments", [])}
    if "Radical prostatectomy" in eligible_names:
        panels.insert(
            2,
            {
                "title": "Panel prequirúrgico",
                "subtitle": "Nomogramas y riesgo patológico solo porque la cirugía sigue siendo una opción real.",
                "items": [
                    {"label": "Cirugía", "value": "Candidato a prostatectomía radical"},
                    {"label": "Objetivo", "value": "Counseling patológico y riesgo ganglionar"},
                ],
                "bullets": [
                    "CAPRA, Briganti, Partin y MSKCC se muestran abajo como refinadores prequirúrgicos.",
                    "Los resultados genómicos y PROs se integran para la conversación compartida, no para sustituir guías.",
                ],
            },
        )
    return panels


def _postlocal_panels(patient: dict[str, Any], raw_assessment: dict[str, Any], display_result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    surgery = patient.get("surgery") or {}
    latest_imaging = _latest_item(patient.get("imaging", []), "study_date")
    items = [
        {
            "title": "Recurrencia y rescate",
            "subtitle": "Variables que determinan si existe todavía una ventana curativa o intensificación temprana.",
            "items": [
                {"label": "PSA ultrasensible", "value": _first_nonempty(payload.get("ultrasensitive_psa_assay"), "No documentado")},
                {"label": "Tiempo a recurrencia", "value": _first_nonempty(payload.get("time_to_recurrence_months"), patient.get("bcr", {}).get("time_to_recurrence_months"), "No documentado")},
                {"label": "Márgenes", "value": _first_nonempty(payload.get("margin_location"), surgery.get("margin_location"), "No documentado")},
                {"label": "Decipher", "value": _first_nonempty(payload.get("decipher_risk"), patient.get("genomics", {}).get("decipher_risk"), "No documentado")},
            ],
            "bullets": _as_list(display_result.get("decision_changing_inputs"))[:3],
        },
        {
            "title": "Imagen y ventana curativa",
            "subtitle": "Qué imagen existe y si todavía hay un rescate local factible.",
            "items": [
                {"label": "Imagen convencional", "value": _first_nonempty(payload.get("conventional_imaging_m0"), payload.get("conventional_imaging_status"), "No documentada")},
                {"label": "PSMA-PET", "value": _first_nonempty(payload.get("psma_pet_result"), latest_imaging.get("psma_result"), "No documentado")},
                {"label": "Rescate local factible", "value": _first_nonempty(payload.get("salvage_local_feasible"), payload.get("local_salvage_candidate"), "No documentado")},
                {"label": "Terapia pélvica elegible", "value": _first_nonempty(payload.get("eligible_pelvic_therapy"), "No documentada")},
            ],
            "bullets": _as_list(display_result.get("supportive_evidence_context"))[:2],
        },
    ]
    return items


def _build_advanced_panel_context(
    patient: dict[str, Any],
    raw_assessment: dict[str, Any],
    raw_result: dict[str, Any],
    display_result: dict[str, Any],
    copilot: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    prior_history = patient.get("prior_history") or {}
    baseline = patient.get("baseline") or {}
    genomics = patient.get("genomics") or {}
    latest_followup = _latest_item(patient.get("follow_ups", []), "visit_date")
    latest_treatment = _latest_item(patient.get("treatments", []), "start_date")
    latest_imaging = _latest_item(patient.get("imaging", []), "study_date")
    latest_stage_visit = _latest_item(patient.get("stage_visits", []), "visit_date")
    latest_visit_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {})
    if not latest_visit_payload:
        latest_visit_payload = ((latest_followup.get("visit_bundle") or {}).get("payload") or {})
    precision = (copilot or {}).get("precision_genomics") or {}
    fitness = (copilot or {}).get("therapeutic_fitness") or {}
    adt_effects = (copilot or {}).get("adt_side_effects") or {}
    ddi = (copilot or {}).get("ddi_review") or {}
    verified_facts = patient.get("verified_document_facts") or []
    verified_by_field: dict[str, dict[str, Any]] = {}
    for fact in verified_facts:
        field_name = fact.get("field_name")
        if field_name and field_name not in verified_by_field and _is_present(fact.get("value")):
            verified_by_field[field_name] = fact
    latest_psma = next(
        (
            item
            for item in (patient.get("imaging") or [])
            if "psma" in str(item.get("study_type", "")).lower()
        ),
        {},
    )
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    try:
        from prostanet.domains.patient_tracking.longitudinal_intelligence import build_state_classifier_payload

        inferred_payload = build_state_classifier_payload(patient, raw_assessment)
    except Exception:
        inferred_payload = {}

    def _candidate(value: Any, source_label: str, source_date: Any, evidence_status: str) -> dict[str, Any]:
        return {
            "value": value,
            "source_label": source_label,
            "source_date": str(source_date or ""),
            "evidence_status": evidence_status,
        }

    def _verified_candidate(field_name: str) -> dict[str, Any] | None:
        fact = verified_by_field.get(field_name)
        if not fact:
            return None
        return _candidate(fact.get("value"), "documento verificado", fact.get("source_date"), "verified")

    def _visit_candidate(field_name: str) -> dict[str, Any] | None:
        if _is_present(latest_visit_payload.get(field_name)):
            return _candidate(
                latest_visit_payload.get(field_name),
                "stage_visit_records" if latest_stage_visit.get("visit_date") else "follow_up_visits",
                latest_stage_visit.get("visit_date") or latest_followup.get("visit_date"),
                "captured",
            )
        return None

    def _assessment_candidate(field_name: str) -> dict[str, Any] | None:
        if _is_present(payload.get(field_name)):
            return _candidate(payload.get(field_name), "assessment modular", raw_assessment.get("assessment_date"), "captured")
        return None

    def _first_candidate(*candidates: dict[str, Any] | None) -> dict[str, Any]:
        for candidate in candidates:
            if candidate and _is_present(candidate.get("value")):
                return candidate
        return _candidate("", "", "", "missing")

    def _resolved_item(
        *,
        label: str,
        field_name: str,
        candidates: list[dict[str, Any] | None],
        formatter=None,
        default: str = "No documentado",
        drives_eligibility: bool = False,
    ) -> dict[str, Any]:
        chosen = _first_candidate(*candidates)
        raw_value = chosen.get("value")
        if not _is_present(raw_value):
            value = default
        else:
            value = formatter(raw_value) if formatter else raw_value
        status = chosen.get("evidence_status", "missing")
        status_label = {
            "verified": "verificado",
            "captured": "capturado",
            "inferred": "inferido",
            "missing": "faltante",
        }.get(status, status)
        detail = ""
        if chosen.get("source_label"):
            detail = f"{_source_badge(chosen.get('source_label', ''), chosen.get('source_date', ''))} · {status_label}"
        else:
            detail = status_label.capitalize()
        return {
            "label": label,
            "field_name": field_name,
            "value": value,
            "detail": detail,
            "source_label": chosen.get("source_label", ""),
            "source_date": chosen.get("source_date", ""),
            "evidence_status": status,
            "drives_eligibility": drives_eligibility,
        }

    hrr_gene_display = _first_nonempty(
        latest_visit_payload.get("hrr_gene"),
        payload.get("hrr_gene"),
        "documentado",
    )
    hrr_item = _resolved_item(
        label="HRR / BRCA",
        field_name="hrr_status",
        candidates=[
            _verified_candidate("hrr_status"),
            _visit_candidate("hrr_status"),
            _candidate(genomics.get("hrr_overall"), "genomic_profile", genomics.get("test_date"), "captured") if _is_present(genomics.get("hrr_overall")) else None,
            _assessment_candidate("hrr_status"),
            _candidate(baseline.get("hrr_status"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("hrr_status")) else None,
        ],
        formatter=lambda value: f"{value}{f' ({hrr_gene_display})' if _is_present(hrr_gene_display) else ''}",
        drives_eligibility=True,
    )

    msi_item = _resolved_item(
        label="MSI / TMB",
        field_name="msi_status",
        candidates=[
            _verified_candidate("msi_status"),
            _visit_candidate("msi_status"),
            _candidate(genomics.get("msi_status"), "genomic_profile", genomics.get("test_date"), "captured") if _is_present(genomics.get("msi_status")) else None,
            _assessment_candidate("msi_status"),
            _candidate("TMB-high", "stage_visit_records", latest_stage_visit.get("visit_date"), "captured") if _truthy(latest_visit_payload.get("tmb_high")) else None,
            _candidate("TMB-high", "assessment modular", raw_assessment.get("assessment_date"), "captured") if _truthy(payload.get("tmb_high")) else None,
        ],
        drives_eligibility=True,
    )

    psma_value = None
    if _is_present(latest_psma.get("psma_result")):
        psma_value = "Sí" if str(latest_psma.get("psma_result", "")).lower().startswith("pos") else "No"
    psma_item = _resolved_item(
        label="PSMA",
        field_name="psma_positive",
        candidates=[
            _verified_candidate("psma_positive"),
            _visit_candidate("psma_positive"),
            _candidate(psma_value, "imaging_studies", latest_psma.get("study_date"), "captured") if _is_present(psma_value) else None,
            _assessment_candidate("psma_positive"),
        ],
        formatter=lambda value: value if value in {"Sí", "No"} else _yes_no(value),
        drives_eligibility=True,
    )

    psma_negative_item = _resolved_item(
        label="Lesiones dominantes PSMA negativas",
        field_name="psma_negative_dominant_lesions",
        candidates=[
            _verified_candidate("psma_negative_dominant_lesions"),
            _visit_candidate("psma_negative_dominant_lesions"),
            _candidate(
                (latest_psma.get("findings") or {}).get("psma_negative_dominant_lesions"),
                "imaging_studies",
                latest_psma.get("study_date"),
                "captured",
            ) if isinstance(latest_psma.get("findings"), dict) else None,
            _assessment_candidate("psma_negative_dominant_lesions"),
        ],
        formatter=_yes_no,
        drives_eligibility=True,
    )

    sequencing_items = [
        _resolved_item(
            label="Número de línea terapéutica",
            field_name="line_of_therapy_number",
            candidates=[
                _verified_candidate("line_of_therapy_number") or _verified_candidate("line_of_therapy"),
                _visit_candidate("line_of_therapy_number") or _visit_candidate("line_of_therapy"),
                _candidate(
                    latest_treatment.get("line_of_therapy_number") or latest_treatment.get("line_of_therapy"),
                    "treatment_history",
                    latest_treatment.get("start_date"),
                    "captured",
                ) if _is_present(latest_treatment.get("line_of_therapy_number") or latest_treatment.get("line_of_therapy")) else None,
                _assessment_candidate("line_of_therapy_number") or _assessment_candidate("line_of_therapy"),
            ],
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Contexto clínico de la línea",
            field_name="line_of_therapy_context",
            candidates=[
                _verified_candidate("line_of_therapy_context"),
                _visit_candidate("line_of_therapy_context"),
                _candidate(
                    LINE_CONTEXT_LABELS.get(str(latest_treatment.get("line_of_therapy_context") or ""), latest_treatment.get("line_of_therapy_context")),
                    "treatment_history",
                    latest_treatment.get("start_date"),
                    "captured",
                ) if _is_present(latest_treatment.get("line_of_therapy_context")) else None,
                _candidate(
                    LINE_CONTEXT_LABELS.get(str(payload.get("line_of_therapy_context") or ""), payload.get("line_of_therapy_context")),
                    "assessment modular",
                    raw_assessment.get("assessment_date"),
                    "captured",
                ) if _is_present(payload.get("line_of_therapy_context")) else None,
            ],
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Esquema actual",
            field_name="drug_scheme",
            candidates=[
                _verified_candidate("drug_scheme"),
                _visit_candidate("drug_scheme"),
                _candidate(latest_treatment.get("drug_scheme"), "treatment_history", latest_treatment.get("start_date"), "captured") if _is_present(latest_treatment.get("drug_scheme")) else None,
                _candidate(latest_followup.get("current_treatment"), "follow_up_visits", latest_followup.get("visit_date"), "captured") if _is_present(latest_followup.get("current_treatment")) else None,
                _assessment_candidate("drug_scheme"),
                _candidate(latest_signal_snapshot.get("recommended_option"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(latest_signal_snapshot.get("recommended_option")) else None,
            ],
            formatter=regimen_label,
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Contexto actual de ADT",
            field_name="current_adt_context",
            candidates=[
                _verified_candidate("current_adt_context"),
                _visit_candidate("current_adt_context"),
                _assessment_candidate("current_adt_context"),
                _candidate(inferred_payload.get("current_adt_context"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(inferred_payload.get("current_adt_context")) else None,
            ],
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Estado de castración",
            field_name="castrate_testosterone_status",
            candidates=[
                _verified_candidate("castrate_testosterone_status"),
                _visit_candidate("castrate_testosterone_status"),
                _assessment_candidate("castrate_testosterone_status"),
                _candidate(inferred_payload.get("castrate_testosterone_status"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(inferred_payload.get("castrate_testosterone_status")) else None,
            ],
            drives_eligibility=True,
        ),
        _resolved_item(
            label="Patrón de progresión",
            field_name="progression_pattern",
            candidates=[
                _verified_candidate("progression_pattern"),
                _visit_candidate("progression_pattern"),
                _candidate((patient.get("response_assessments") or [{}])[0].get("response_category"), "response_assessments", (patient.get("response_assessments") or [{}])[0].get("assessment_date"), "captured") if patient.get("response_assessments") else None,
                _assessment_candidate("progression_pattern"),
                _candidate(inferred_payload.get("progression_pattern"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(inferred_payload.get("progression_pattern")) else None,
            ],
            drives_eligibility=False,
        ),
        _resolved_item(
            label="Imagen convencional / PSMA",
            field_name="conventional_imaging_status",
            candidates=[
                _verified_candidate("conventional_imaging_status"),
                _visit_candidate("conventional_imaging_status"),
                _candidate((latest_imaging.get("findings") or {}).get("conventional_imaging_status"), "imaging_studies", latest_imaging.get("study_date"), "captured") if isinstance(latest_imaging.get("findings"), dict) else None,
                _assessment_candidate("conventional_imaging_status"),
                _candidate(inferred_payload.get("conventional_imaging_status"), "inferencia longitudinal", latest_signal_snapshot.get("updated_at"), "inferred") if _is_present(inferred_payload.get("conventional_imaging_status")) else None,
            ],
            drives_eligibility=True,
        ),
    ]

    bone_bundle_complete = all(
        _truthy(
            _first_nonempty(
                latest_visit_payload.get(field),
                latest_followup.get(field),
                payload.get(field),
                baseline.get(field),
            )
        )
        for field in ("dxa_baseline_done", "calcium_vitd_started", "bone_protection_started")
    )

    safety_items = [
        _resolved_item(
            label="ECOG",
            field_name="ecog",
            candidates=[
                _verified_candidate("ecog"),
                _visit_candidate("ecog"),
                _candidate(latest_followup.get("ecog_current"), "follow_up_visits", latest_followup.get("visit_date"), "captured") if _is_present(latest_followup.get("ecog_current")) else None,
                _candidate(baseline.get("ecog_score"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("ecog_score")) else None,
            ],
            drives_eligibility=False,
        ),
        _resolved_item(
            label="Fragilidad / fitness",
            field_name="frailty_status",
            candidates=[
                _verified_candidate("frailty_status"),
                _visit_candidate("frailty_status"),
                _candidate((fitness.get("frailty") or {}).get("status"), "therapeutic_fitness", latest_followup.get("visit_date"), "captured") if _is_present((fitness.get("frailty") or {}).get("status")) else None,
                _candidate(latest_followup.get("frailty_status"), "follow_up_visits", latest_followup.get("visit_date"), "captured") if _is_present(latest_followup.get("frailty_status")) else None,
                _candidate(baseline.get("frailty_status"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("frailty_status")) else None,
            ],
            drives_eligibility=False,
        ),
        _resolved_item(
            label="Child-Pugh / riesgo hepático",
            field_name="child_pugh_score",
            candidates=[
                _verified_candidate("child_pugh_score"),
                _visit_candidate("child_pugh_score"),
                _candidate((fitness.get("child_pugh") or {}).get("grade"), "therapeutic_fitness", latest_followup.get("visit_date"), "captured") if _is_present((fitness.get("child_pugh") or {}).get("grade")) else None,
                _assessment_candidate("child_pugh_score"),
                _candidate(baseline.get("child_pugh_score"), "clinical_baseline", patient.get("identity", {}).get("diagnosis_date"), "captured") if _is_present(baseline.get("child_pugh_score")) else None,
            ],
            drives_eligibility=False,
        ),
        _resolved_item(
            label="Riesgo CV documentado",
            field_name="cv_risk_documented",
            candidates=[
                _verified_candidate("cv_risk_documented"),
                _visit_candidate("cv_risk_documented"),
                _candidate(latest_followup.get("cv_risk_status"), "follow_up_visits", latest_followup.get("visit_date"), "captured") if _is_present(latest_followup.get("cv_risk_status")) else None,
                _candidate((adt_effects.get("cv_risk") or {}).get("risk_category"), "adt_side_effects", latest_followup.get("visit_date"), "captured") if _is_present((adt_effects.get("cv_risk") or {}).get("risk_category")) else None,
            ],
            formatter=lambda value: value if str(value).lower() in {"alto", "intermedio", "bajo"} else _yes_no(value),
            drives_eligibility=False,
        ),
        {
            "label": "Bundle óseo",
            "field_name": "bone_bundle",
            "value": "Completo" if bone_bundle_complete else "Incompleto",
            "detail": _source_badge(
                "stage_visit_records" if latest_stage_visit.get("visit_date") else "follow_up_visits",
                latest_stage_visit.get("visit_date") or latest_followup.get("visit_date"),
            ) + f" · {'capturado' if bone_bundle_complete else 'faltante'}",
            "source_label": "stage_visit_records" if latest_stage_visit.get("visit_date") else "follow_up_visits",
            "source_date": latest_stage_visit.get("visit_date") or latest_followup.get("visit_date") or "",
            "evidence_status": "captured" if bone_bundle_complete else "missing",
            "drives_eligibility": False,
        },
        _resolved_item(
            label="Interacciones y overlays",
            field_name="drug_interaction_reviewed",
            candidates=[
                _verified_candidate("drug_interaction_reviewed"),
                _visit_candidate("drug_interaction_reviewed"),
                _candidate(
                    f"{len(ddi.get('interactions') or [])} interacciones activas" if ddi.get("has_interactions") else "",
                    "ddi_review",
                    latest_followup.get("visit_date"),
                    "captured",
                ) if ddi else None,
                _candidate((patient.get("care_overlays") or [{}])[0].get("title"), "care_overlays", latest_followup.get("visit_date"), "captured") if patient.get("care_overlays") else None,
            ],
            default="Sin alertas destacadas",
            drives_eligibility=False,
        ),
    ]

    biomarker_items = [
        hrr_item,
        msi_item,
        psma_item,
        psma_negative_item,
        _resolved_item(
            label="Elegibilidad molecular destacada",
            field_name="precision_signal",
            candidates=[
                _candidate((precision.get("ar_v7") or {}).get("clinical_action"), "precision_genomics", raw_assessment.get("assessment_date"), "inferred"),
                _candidate((precision.get("pten") or {}).get("clinical_action"), "precision_genomics", raw_assessment.get("assessment_date"), "inferred"),
                _candidate((precision.get("cdk12") or {}).get("clinical_action"), "precision_genomics", raw_assessment.get("assessment_date"), "inferred"),
            ],
            default="Sin disparador molecular activo",
            drives_eligibility=False,
        ),
    ]

    def _panel_meta(items: list[dict[str, Any]], title: str, bullets: list[str], source_hints: list[str]) -> dict[str, Any]:
        sources = [item.get("source_label") for item in items if item.get("source_label")]
        updated_at = _first_nonempty(*(item.get("source_date") for item in items if item.get("source_date")))
        return {
            "title": title,
            "updated_at": updated_at,
            "sources": list(dict.fromkeys(sources or source_hints)),
            "items": items,
            "bullets": bullets,
        }

    sequencing_missing = [
        item.get("field_name")
        for item in sequencing_items
        if item.get("evidence_status") in {"missing", "inferred"} and item.get("drives_eligibility")
    ]
    biomarker_missing = [
        item.get("field_name")
        for item in biomarker_items
        if item.get("evidence_status") in {"missing", "inferred"} and item.get("drives_eligibility")
    ]
    safety_missing = [
        item.get("field_name")
        for item in safety_items
        if item.get("evidence_status") == "missing" and item.get("field_name")
    ]

    context = {
        "sequencing_context": _panel_meta(
            sequencing_items,
            "Secuenciación sistémica actual",
            [item.get("name") for item in raw_result.get("eligible_treatments", [])[:3]],
            ["stage_visit_records", "treatment_history", "inferencia longitudinal"],
        ),
        "biomarker_context": _panel_meta(
            biomarker_items,
            "Biomarcadores y elegibilidad terapéutica",
            _as_list(display_result.get("decision_changing_inputs"))[:4],
            ["verified_document_facts", "genomic_profile", "imaging_studies"],
        ),
        "safety_support_context": _panel_meta(
            safety_items,
            "Seguridad y soporte concurrente",
            [overlay.get("title") for overlay in patient.get("care_overlays", [])[:3]],
            ["follow_up_visits", "therapeutic_fitness", "adt_side_effects", "ddi_review"],
        ),
    }
    return context, {
        "sequencing_context": sequencing_missing,
        "biomarker_context": biomarker_missing,
        "safety_support_context": safety_missing,
    }


def _advanced_panels(
    patient: dict[str, Any],
    raw_assessment: dict[str, Any],
    raw_result: dict[str, Any],
    display_result: dict[str, Any],
    copilot: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[str]]]:
    context, missing_inputs = _build_advanced_panel_context(patient, raw_assessment, raw_result, display_result, copilot)
    panels = []
    subtitles = {
        "sequencing_context": "Dónde está parado el paciente hoy y qué trayectorias siguen abiertas.",
        "biomarker_context": "Información accionable que hoy ordena PARP, inmunoterapia, PSMA y secuenciación.",
        "safety_support_context": "Capas que cambian aptitud terapéutica, seguridad y soporte longitudinal.",
    }
    for key in ("sequencing_context", "biomarker_context", "safety_support_context"):
        entry = context.get(key) or {}
        panels.append(
            {
                "title": entry.get("title"),
                "subtitle": subtitles.get(key, ""),
                "items": entry.get("items", []),
                "bullets": entry.get("bullets", []),
                "sources": entry.get("sources", []),
                "updated_at": entry.get("updated_at", ""),
                "missing_inputs": missing_inputs.get(key, []),
            }
        )
    return panels, context, missing_inputs


def _copilot_orientation_panel(copilot_modifiers: dict[str, Any]) -> dict[str, Any] | None:
    modifiers = copilot_modifiers.get("active_modifiers") or []
    if not modifiers:
        return None
    return {
        "title": "Modificadores activos del copilot",
        "subtitle": "Capas paralelas ya integradas que hoy cambian intensidad, seguridad o priorización clínica.",
        "items": [
            {
                "label": item.get("label", "Modificador"),
                "value": item.get("detail", ""),
                "detail": (
                    "Alta prioridad" if item.get("tone") == "danger"
                    else "Vigilancia reforzada" if item.get("tone") == "warning"
                    else "Accionable" if item.get("tone") == "success"
                    else "Contexto clínico"
                ),
            }
            for item in modifiers[:4]
        ],
        "bullets": _merge_unique_text(
            copilot_modifiers.get("what_could_change_course", []),
            copilot_modifiers.get("next_actions", []),
            limit=5,
        ),
    }


def _build_stage_specific_panels(
    *,
    patient: dict[str, Any],
    state: str,
    raw_assessment: dict[str, Any],
    display_assessment: dict[str, Any],
    copilot_modifiers: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    if state in DIAGNOSTIC_STATES:
        panels = _diagnostic_panel(patient, raw_assessment)
    elif state in LOCALIZED_STATES:
        panels = _localized_panels(patient, raw_assessment, display_result, raw_result)
    elif state in POSTLOCAL_STATES:
        panels = _postlocal_panels(patient, raw_assessment, display_result)
    elif state in ADVANCED_STATES:
        panels, _, _ = _advanced_panels(patient, raw_assessment, raw_result, display_result)
    else:
        panels = []
    modifier_panel = _copilot_orientation_panel(copilot_modifiers or {})
    if modifier_panel:
        panels.append(modifier_panel)
    return panels


def _segment(label: str, value: Any, tone: str) -> dict[str, Any]:
    number = max(0.0, min(100.0, _safe_float(value) or 0.0))
    return {"label": label, "value": number, "display": f"{number:.1f}%", "tone": tone}


def _algorithm_panel_entry(raw_algorithm: dict[str, Any], display_algorithm: dict[str, Any], stage: str) -> dict[str, Any]:
    key = raw_algorithm.get("key")
    result_snapshot = raw_algorithm.get("result_snapshot", {}) or {}
    algorithm_meta = ALGORITHM_EXPLANATIONS.get(key, {})
    missing_inputs = list(dict.fromkeys((raw_algorithm.get("inputs_missing") or []) + (result_snapshot.get("missing_inputs") or [])))
    inputs_used = result_snapshot.get("inputs_used") or raw_algorithm.get("inputs_used") or []
    if isinstance(inputs_used, dict):
        inputs_used = [f"{field}: {value}" for field, value in inputs_used.items() if _is_present(value)]
    panel = {
        "name": display_algorithm.get("name") or raw_algorithm.get("name"),
        "status": display_algorithm.get("status") or raw_algorithm.get("status"),
        "summary": display_algorithm.get("summary") or raw_algorithm.get("summary"),
        "clinical_use": display_algorithm.get("clinical_use") or raw_algorithm.get("clinical_use"),
        "evidence_note": display_algorithm.get("evidence_note") or raw_algorithm.get("evidence_note"),
        "source_label": raw_algorithm.get("source_label", ""),
        "source_url": raw_algorithm.get("source_url", ""),
        "visual_type": "external_result",
        "primary_metric": None,
        "bars": [],
        "segments": [],
        "threshold": None,
        "details": [],
        "what_score_means": result_snapshot.get("what_score_means") or algorithm_meta.get("what_score_means") or "",
        "risk_interpretation": result_snapshot.get("risk_interpretation") or algorithm_meta.get("risk_interpretation") or "",
        "inputs_used": inputs_used,
        "missing_inputs": missing_inputs,
        "data_truth_status": result_snapshot.get("data_truth_status") or ("incomplete" if missing_inputs else "captured"),
        "clinical_decision_supported": result_snapshot.get("clinical_decision_supported") or algorithm_meta.get("clinical_decision_supported") or display_algorithm.get("clinical_use") or "",
    }
    if key == "capra":
        panel["visual_type"] = "score_band"
        panel["primary_metric"] = {
            "label": "CAPRA",
            "value": f"{result_snapshot.get('score', '0')}/{result_snapshot.get('max_score', '10')}",
            "detail": result_snapshot.get("risk_group", "No documentado"),
        }
        panel["bars"] = [
            _segment("Libre de BCR a 3 años", str(result_snapshot.get("bcr_free_3y", "0")).replace("%", ""), "cyan"),
            _segment("Libre de BCR a 5 años", str(result_snapshot.get("bcr_free_5y", "0")).replace("%", ""), "emerald"),
        ]
    elif key == "briganti":
        risk = _safe_float(result_snapshot.get("probabilidad_raw") or str(result_snapshot.get("probabilidad_lni", "0")).replace("%", ""))
        panel["visual_type"] = "gauge"
        panel["primary_metric"] = {
            "label": "Riesgo ganglionar",
            "value": _format_pct(risk),
            "detail": result_snapshot.get("eplnd_texto", ""),
        }
        panel["bars"] = [_segment("LNI estimado", risk, "amber")]
        panel["threshold"] = {"label": result_snapshot.get("umbral", "Umbral clínico"), "value": 5}
    elif key == "partin":
        panel["visual_type"] = "stacked"
        panel["segments"] = [
            _segment("Órgano confinado", result_snapshot.get("oc_prob"), "emerald"),
            _segment("ECE", result_snapshot.get("ece_prob"), "amber"),
            _segment("SVI", result_snapshot.get("svi_prob"), "orange"),
            _segment("LNI", result_snapshot.get("lni_prob"), "rose"),
        ]
    elif key == "mskcc_preop":
        probability = _safe_float(result_snapshot.get("probabilidad_raw") or str(result_snapshot.get("probabilidad_organo_confinado", "0")).replace("%", ""))
        panel["visual_type"] = "gauge"
        panel["primary_metric"] = {
            "label": "Órgano confinado",
            "value": _format_pct(probability),
            "detail": result_snapshot.get("interpretacion", ""),
        }
        panel["bars"] = [_segment("Probabilidad preoperatoria", probability, "cyan")]
    elif key == "capra_s":
        panel["visual_type"] = "score_band"
        panel["primary_metric"] = {
            "label": "CAPRA-S",
            "value": f"{result_snapshot.get('score', '0')}/{result_snapshot.get('max_score', '12')}",
            "detail": result_snapshot.get("risk_group", "No documentado"),
        }
    elif key == "predict_prostate":
        panel["visual_type"] = "readiness"
        panel["details"] = missing_inputs
    elif raw_algorithm.get("integration_mode") == "external_result":
        panel["visual_type"] = "external_result"
        snapshot = raw_algorithm.get("result_snapshot", {})
        classifier = snapshot.get("classifier") or display_algorithm.get("name") or raw_algorithm.get("name")
        result_text = snapshot.get("result") or snapshot.get("decipher_risk") or display_algorithm.get("status")
        panel["primary_metric"] = {
            "label": classifier,
            "value": result_text,
            "detail": "Resultado externo documentado",
        }
    elif stage in DIAGNOSTIC_STATES:
        panel["visual_type"] = "readiness"
        panel["details"] = missing_inputs
    return panel


def _build_algorithm_panels(
    *,
    state: str,
    raw_assessment: dict[str, Any],
    display_assessment: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    raw_algorithms = raw_result.get("validated_algorithms", []) or []
    display_algorithms = display_result.get("validated_algorithms", []) or []
    panels = [
        _algorithm_panel_entry(raw_algorithm, display_algorithm, state)
        for raw_algorithm, display_algorithm in zip(raw_algorithms, display_algorithms)
    ]
    if state in ADVANCED_STATES:
        panels = [panel for panel in panels if panel["visual_type"] == "external_result"]
    return panels


def _dedupe_pivotal_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(matches, key=lambda item: (str(item.get("evaluation_date", "")), int(item.get("id", 0))), reverse=True)
    deduped = []
    seen = set()
    for item in ordered:
        study_name = item.get("study_name")
        if not study_name or study_name in seen:
            continue
        seen.add(study_name)
        deduped.append(item)
    return deduped


def _normalize_pivotal_match(match: dict[str, Any]) -> dict[str, Any]:
    details = _parse_json_blob(match.get("eligibility_details"), {})
    normalized = dict(match)
    normalized["eligible"] = bool(match.get("eligible"))
    normalized["match_score"] = _safe_float(details.get("match_score"))
    normalized["criteria_met"] = details.get("criteria_met", [])
    normalized["criteria_failed"] = details.get("criteria_failed", [])
    backbone_bundle = details.get("recommended_trial_backbone") or trial_backbone(match.get("study_name"))
    if isinstance(backbone_bundle, dict):
        normalized.update(
            {
                "recommended_trial_backbone": backbone_bundle.get("recommended_trial_backbone", ""),
                "recommended_trial_backbone_label": backbone_bundle.get("recommended_trial_backbone_label", ""),
                "recommended_trial_backbone_source": backbone_bundle.get("recommended_trial_backbone_source", ""),
                "recommended_trial_backbone_note": backbone_bundle.get("recommended_trial_backbone_note", ""),
            }
        )
    return normalized


def _build_triplet_decision_for_profile(
    *,
    state: str,
    raw_assessment: dict[str, Any] | None,
) -> dict[str, Any]:
    if not is_mhspc_state(state):
        return {}
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    payload = dict((raw_assessment or {}).get("input_snapshot", {}) or {})
    existing = dict(raw_result.get("triplet_decision") or raw_result.get("triplet_decision_card") or {})
    if existing:
        return existing
    return build_triplet_decision(
        state,
        payload,
        docetaxel_bundle=raw_result.get("docetaxel_fitness"),
    )


def _build_pivotal_panel(matches: list[dict[str, Any]], *, state: str = "") -> dict[str, Any]:
    normalized = [_normalize_pivotal_match(item) for item in _dedupe_pivotal_matches(matches)]
    hidden_cross_scenario = 0
    if is_mhspc_state(state):
        _, hidden_trials = visible_trials_for_mhspc_state(state, {})
        hidden_cross_scenario = sum(1 for item in normalized if str(item.get("study_name") or "") in hidden_trials)
        normalized = [item for item in normalized if str(item.get("study_name") or "") not in hidden_trials]
    eligible = [item for item in normalized if item.get("eligible")]
    partial = [item for item in normalized if not item.get("eligible") and (item.get("match_score") or 0) >= 0.7]
    ineligible = [item for item in normalized if item not in eligible and item not in partial]
    last_evaluated_at = _first_nonempty(normalized[0].get("evaluation_date") if normalized else "", "")
    return {
        "eligible_matches": eligible,
        "partial_matches": partial,
        "ineligible_matches": ineligible,
        "hidden_ineligible_count": len(ineligible),
        "eligible_count": len(eligible),
        "partial_count": len(partial),
        "ineligible_count": len(ineligible),
        "hidden_cross_scenario_count": hidden_cross_scenario,
        "last_evaluated_at": last_evaluated_at,
        "has_results": bool(normalized),
    }


def _scenario_for_state(state: str) -> str:
    if state in DIAGNOSTIC_STATES:
        return "localizado"
    if state == "localized_initial":
        return "localizado"
    if state == "post_prostatectomy":
        return "adyuvancia"
    if state == "recurrence_bcr":
        return "rescate"
    if state == "m0_crpc":
        return "nmCRPC"
    if state in {"m1_crpc"}:
        return "mCRPC"
    if state == "adt_progression_verification":
        return "verification"
    if state in {"mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync", "mcspc_high_volume_metachronous", "mcspc_high_volume"}:
        return "mHSPC"
    return ""


def _build_evidence_applicability(
    *,
    state: str,
    pivotal_panel: dict[str, Any],
    display_assessment: dict[str, Any],
) -> dict[str, Any]:
    scenario = _scenario_for_state(state)
    current_recommendation = _first_nonempty(
        ((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("titulo_clinico"),
        ((display_assessment or {}).get("display_result", {}) or {}).get("nccn_primary", {}).get("label"),
        STATE_DISPLAY_MAP.get(state),
    )
    all_matches = (
        list(pivotal_panel.get("eligible_matches") or [])
        + list(pivotal_panel.get("partial_matches") or [])
        + list(pivotal_panel.get("ineligible_matches") or [])
    )
    scenario_matches = [item for item in all_matches if str(item.get("scenario", "")).lower() == scenario.lower()] if scenario else all_matches
    prioritized = [
        item for item in (list(pivotal_panel.get("eligible_matches") or []) + list(pivotal_panel.get("partial_matches") or []))
        if not scenario or str(item.get("scenario", "")).lower() == scenario.lower()
    ]
    applicability_cards = []
    for match in prioritized[:4]:
        is_eligible = bool(match.get("eligible"))
        criteria_met = (match.get("criteria_met") or [])[:3]
        criteria_failed = (match.get("criteria_failed") or [])[:3]
        decision_supported = current_recommendation
        eligibility_rationale = (
            f"Elegible porque cumple: {', '.join(criteria_met)}."
            if is_eligible and criteria_met
            else "Elegible por concordancia clínica global con el escenario actual."
            if is_eligible
            else f"Parcial porque aún faltan o fallan: {', '.join(criteria_failed)}."
            if criteria_failed
            else "Parcial por concordancia incompleta con el escenario actual."
        )
        applicability_cards.append(
            {
                "study_name": match.get("study_name", "Estudio"),
                "scenario": match.get("scenario", ""),
                "status": "Aplicable" if is_eligible else "Parcial",
                "expected_outcome": match.get("expected_outcome") or match.get("key_result") or "",
                "criteria_met": criteria_met,
                "criteria_failed": criteria_failed,
                "match_score": match.get("match_score"),
                "applicability": match.get("applicability") or "",
                "decision_supported": decision_supported,
                "eligibility_rationale": eligibility_rationale,
                "clinical_takeaway": (
                    f"Puede respaldar la recomendación actual: {decision_supported}."
                    if is_eligible
                    else "Aún no sostiene una decisión definitiva hasta resolver los gaps clínicos."
                ),
                "evidence_strength": "Alta" if is_eligible else "Condicionada",
                "recommended_trial_backbone": match.get("recommended_trial_backbone", ""),
                "recommended_trial_backbone_label": match.get("recommended_trial_backbone_label", ""),
                "recommended_trial_backbone_source": match.get("recommended_trial_backbone_source", ""),
                "recommended_trial_backbone_note": match.get("recommended_trial_backbone_note", ""),
            }
        )
    return {
        "scenario": scenario,
        "recommendation_label": current_recommendation,
        "eligible_count": sum(1 for item in scenario_matches if item.get("eligible")),
        "partial_count": sum(1 for item in scenario_matches if not item.get("eligible") and (item.get("match_score") or 0) >= 0.7),
        "supporting_trials": applicability_cards,
        "has_results": bool(scenario_matches),
        "gaps": _merge_unique_text([], [gap for card in applicability_cards for gap in (card.get("criteria_failed") or [])], limit=5),
        "summary": (
            "La evidencia se mantiene restringida hasta confirmar si el paciente realmente pertenece a mHSPC, nmCRPC o mCRPC."
            if scenario == "verification"
            else
            f"La recomendación actual se está contrastando con estudios pivotales del escenario {scenario}."
            if scenario
            else "La aplicabilidad de evidencia se está contrastando con los estudios pivotales disponibles."
        ),
    }


def _build_document_board(patient: dict[str, Any]) -> dict[str, Any]:
    from prostanet.domains.patient_tracking.document_ingestion import document_label

    documents = list(patient.get("source_documents") or [])
    tasks_by_document = {
        item.get("document_id"): item
        for item in (patient.get("document_verification_tasks") or [])
        if item.get("document_id")
    }
    candidates_by_document: dict[int, list[dict[str, Any]]] = {}
    for candidate in patient.get("document_candidates") or []:
        candidates_by_document.setdefault(candidate.get("document_id"), []).append(candidate)
    verified_today = (patient.get("verified_document_facts") or [])[:10]
    pending_documents = [
        {
            **item,
            "document_type_label": document_label(item.get("document_type", "")),
            "candidate_count": len(candidates_by_document.get(item.get("id"), [])),
            "task": tasks_by_document.get(item.get("id"), {}),
        }
        for item in documents
        if item.get("verification_status") != "verified"
    ]
    verified_documents = [
        {
            **item,
            "document_type_label": document_label(item.get("document_type", "")),
            "task": tasks_by_document.get(item.get("id"), {}),
        }
        for item in documents
        if item.get("verification_status") == "verified"
    ]
    latest_changes = []
    for item in verified_documents[:5]:
        summary = (item.get("task") or {}).get("summary", {})
        for change in summary.get("what_changed", [])[:2]:
            latest_changes.append(
                {
                    "document_title": item.get("title") or item.get("file_name"),
                    "change": change,
                    "verified_at": (item.get("task") or {}).get("verified_at") or item.get("updated_at"),
                    "updated_panels": summary.get("updated_panels", []),
                    "updated_decisions": summary.get("updated_decisions", []),
                    "created_or_closed_agenda_items": summary.get("created_or_closed_agenda_items", []),
                    "changed_recommendation": summary.get("changed_recommendation"),
                }
            )
    return {
        "documents": documents,
        "pending_documents": pending_documents,
        "verified_documents": verified_documents[:6],
        "verified_today": verified_today,
        "latest_changes": latest_changes[:6],
        "pending_count": len(pending_documents),
        "verified_count": len(verified_documents),
    }


def _build_longitudinal_sections(patient: dict[str, Any], state: str, display_assessment: dict[str, Any]) -> list[dict[str, Any]]:
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    sections = [
        {"key": "follow_ups", "title": "Visitas de seguimiento", "count": len(patient.get("follow_ups", [])), "default_open": False},
        {"key": "stage_visits", "title": "Bundles de visita por etapa", "count": len(patient.get("stage_visits", [])), "default_open": state in ADVANCED_STATES},
        {"key": "pros", "title": "Resultados reportados por el paciente", "count": len(patient.get("pros", [])), "default_open": False},
        {"key": "diagnostic_assets", "title": "Activos diagnósticos", "count": len(patient.get("diagnostic_plans", [])) + len(patient.get("mri_facts", [])) + len(patient.get("biopsy_triggers", [])), "default_open": state in DIAGNOSTIC_STATES},
        {"key": "biopsies", "title": "Biopsias y patología", "count": len(patient.get("biopsies", [])), "default_open": False},
        {"key": "benchmarking", "title": "Benchmarking", "count": len(display_result.get("benchmarking_flags", [])), "default_open": False},
        {"key": "provenance", "title": "Provenance clínica", "count": len(patient.get("data_provenance", [])), "default_open": False},
        {"key": "demographics", "title": "Demografía y cohorte", "count": len([item for item in (patient.get("demographics") or {}).values() if _is_present(item)]), "default_open": False},
    ]
    return sections


def _build_copilot_sections(patient: dict[str, Any], state: str, management_track: str, raw_assessment: dict[str, Any]) -> dict[str, Any]:
    """Build copilot clinical data: schedule, alerts, comorbidity scores, ADT side effects."""
    import logging
    copilot_logger = logging.getLogger(__name__)
    copilot: dict[str, Any] = {
        "schedule": [],
        "scheduled_encounters": [],
        "next_encounter": {},
        "overdue_alerts": [],
        "clinical_alerts": [],
        "comorbidity_scores": {},
        "adt_side_effects": None,
        "schedule_anchor_date": "",
        "schedule_anchor_source": "",
        "schedule_anchor_strength": "strong",
        "latest_response_assessment": {},
    }

    patient_id = patient.get("identity", {}).get("id")
    if not patient_id:
        return copilot

    identity = patient.get("identity", {})
    baseline = patient.get("baseline", {}) or {}
    prior = patient.get("prior_history", {}) or {}
    followups = patient.get("follow_ups", []) or []

    # ── Schedule ──
    try:
        import tracking_db

        schedule_bundle = tracking_db.sync_scheduled_events(
            patient,
            state=state,
            management_track=management_track,
            horizon_months=12,
        )
        copilot["schedule"] = schedule_bundle.get("schedule", [])[:20]
        copilot["scheduled_encounters"] = schedule_bundle.get("scheduled_encounters", [])[:6]
        copilot["next_encounter"] = schedule_bundle.get("next_encounter", {})
        copilot["schedule_anchor_date"] = schedule_bundle.get("anchor_date", "")
        copilot["schedule_anchor_source"] = schedule_bundle.get("anchor_source", "")
        copilot["schedule_anchor_strength"] = schedule_bundle.get("schedule_anchor_strength", "strong")
        copilot["overdue_alerts"] = [
            item for item in (schedule_bundle.get("schedule") or [])
            if item.get("status") == "overdue" and not item.get("completed")
        ]
    except Exception as exc:
        copilot_logger.debug("Copilot schedule error: %s", exc)

    # ── Clinical alerts ──
    try:
        persisted_alerts = patient.get("alerts") or []
        if persisted_alerts:
            copilot["clinical_alerts"] = [dict(alert) for alert in persisted_alerts]
    except Exception as exc:
        copilot_logger.debug("Copilot alerts error: %s", exc)

    # ── Comorbidity scores (CCI, G8) ──
    try:
        from clinical_scores import charlson_comorbidity_index, g8_geriatric_assessment
        score_data: dict[str, Any] = {}
        score_data.update(identity)
        score_data.update(baseline)
        score_data.update(prior)
        copilot["comorbidity_scores"]["charlson"] = charlson_comorbidity_index(score_data)
        copilot["comorbidity_scores"]["g8"] = g8_geriatric_assessment(score_data)
    except Exception as exc:
        copilot_logger.debug("Copilot comorbidity error: %s", exc)

    # ── Therapeutic fitness (eGFR, Child-Pugh, frailty, fit score) ──
    try:
        from clinical_scores import egfr_ckd_epi_2021, child_pugh_dynamic, fried_frailty_index, competing_mortality_estimate, treatment_fit_score
        fitness_data: dict[str, Any] = {}
        fitness_data.update(identity)
        fitness_data.update(baseline)
        fitness_data.update(prior)
        if followups:
            fitness_data.update(followups[-1])

        fitness: dict[str, Any] = {"has_data": False}

        # eGFR
        creat = fitness_data.get("creatinine_current") or fitness_data.get("creatinine")
        pat_age = None
        try:
            pat_age = int(float(fitness_data.get("age") or fitness_data.get("edad") or 0))
        except (ValueError, TypeError):
            pass
        pat_sex = str(fitness_data.get("sex") or fitness_data.get("sexo") or "M")
        if creat and pat_age:
            try:
                fitness["egfr"] = egfr_ckd_epi_2021(float(creat), pat_age, pat_sex)
                fitness["has_data"] = True
            except (ValueError, TypeError):
                pass

        # Child-Pugh
        bili = fitness_data.get("bilirubin_current") or fitness_data.get("bilirubin")
        alb = fitness_data.get("albumin_current") or fitness_data.get("albumin")
        inr_val = fitness_data.get("inr_current") or fitness_data.get("inr")
        asc = str(fitness_data.get("ascites", "none"))
        enc = str(fitness_data.get("encephalopathy", "none"))
        try:
            cp = child_pugh_dynamic(
                bilirubin=float(bili) if bili else None,
                albumin=float(alb) if alb else None,
                inr=float(inr_val) if inr_val else None,
                ascites=asc, encephalopathy=enc,
            )
            fitness["child_pugh"] = cp
            fitness["has_data"] = True
        except (ValueError, TypeError):
            pass

        # Fried frailty
        wl_pct = fitness_data.get("weight_loss_6m_pct")
        fatigue = fitness_data.get("fatigue_score")
        ecog_val = fitness_data.get("ecog_current") or fitness_data.get("ecog_score")
        low_activity = fitness_data.get("low_activity")
        slow_gait = fitness_data.get("slow_gait")
        weak_grip = fitness_data.get("weak_grip")
        try:
            frailty = fried_frailty_index(
                weight_loss_pct=float(wl_pct) if wl_pct not in (None, "") else None,
                fatigue_score=float(fatigue) if fatigue else None,
                low_activity=_truthy(low_activity) if low_activity not in (None, "") else None,
                slow_gait=_truthy(slow_gait) if slow_gait not in (None, "") else None,
                weak_grip=_truthy(weak_grip) if weak_grip not in (None, "") else None,
                ecog=int(float(ecog_val)) if ecog_val else None,
                age=pat_age,
            )
            fitness["frailty"] = frailty
            fitness["has_data"] = True
        except (ValueError, TypeError):
            pass

        # Competing mortality
        cci_score = None
        cci_data = copilot.get("comorbidity_scores", {}).get("charlson", {})
        if cci_data and cci_data.get("is_complete"):
            cci_score = cci_data.get("adjusted_score") or cci_data.get("raw_score")
        egfr_val = fitness.get("egfr", {}).get("egfr")
        frailty_st = fitness.get("frailty", {}).get("status")
        if pat_age:
            try:
                fitness["competing_mortality"] = competing_mortality_estimate(
                    age=pat_age, cci=int(cci_score) if cci_score is not None else 0,
                    egfr=egfr_val, frailty_status=frailty_st,
                )
                fitness["has_data"] = True
            except (ValueError, TypeError):
                pass

        # Treatment Fit Score
        g8_data = copilot.get("comorbidity_scores", {}).get("g8", {})
        g8_val = g8_data.get("total_score") if g8_data and g8_data.get("is_complete") else None
        cp_grade = fitness.get("child_pugh", {}).get("grade")
        try:
            fitness["fit_score"] = treatment_fit_score(
                ecog=int(float(ecog_val)) if ecog_val else None,
                cci=int(cci_score) if cci_score is not None else None,
                g8=float(g8_val) if g8_val else None,
                egfr=egfr_val,
                child_pugh=cp_grade,
                frailty_status=frailty_st,
                age=pat_age,
            )
            fitness["has_data"] = True
        except (ValueError, TypeError):
            pass

        copilot["therapeutic_fitness"] = fitness
    except Exception as exc:
        copilot_logger.debug("Copilot therapeutic fitness error: %s", exc)
        copilot["therapeutic_fitness"] = {"has_data": False}

    # ── ADT side effects (only if on ADT) ──
    if prior.get("prior_adt") or management_track in ("on_arpi", "systemic_surveillance"):
        try:
            from prostanet.domains.patient_tracking.adt_side_effects import ADTSideEffectService
            adt_data: dict[str, Any] = {}
            adt_data.update(identity)
            adt_data.update(baseline)
            adt_data.update(prior)
            if followups:
                adt_data.update(followups[-1])
            profile = ADTSideEffectService.full_assessment(adt_data)
            copilot["adt_side_effects"] = profile.to_dict()
        except Exception as exc:
            copilot_logger.debug("Copilot ADT side effects error: %s", exc)

    # ── PRO intelligence (Salto 3) ──
    try:
        from prostanet.domains.patient_tracking.pro_engine import PRODecisionEngine
        pro_data: dict[str, Any] = {}
        pro_data.update(identity)
        pro_data.update(baseline)
        pro_data.update(prior)
        if followups:
            pro_data.update(followups[-1])
        # PRO data from patient_pros table
        pro_record = patient.get("pros") or {}
        if isinstance(pro_record, dict):
            pro_data.update(pro_record)

        pro_alerts = PRODecisionEngine.evaluate_all(patient_id, pro_data)
        copilot["pro_intelligence"] = {
            "alerts": [a.to_dict() for a in pro_alerts],
            "alert_count": len(pro_alerts),
            "critical_count": sum(1 for a in pro_alerts if a.severity == "critical"),
            "has_data": len(pro_alerts) > 0,
        }
    except Exception as exc:
        copilot_logger.debug("Copilot PRO intelligence error: %s", exc)
        copilot["pro_intelligence"] = {"alerts": [], "alert_count": 0, "critical_count": 0, "has_data": False}

    # ── Precision genomics panel ──
    try:
        genomic = patient.get("genomics") or {}
        if not isinstance(genomic, dict):
            genomic = {}
        # Merge genomic fields that may be at patient root level
        for gkey in ("ar_v7_status", "tp53_status", "rb1_status", "pten_loss", "pten_status",
                      "cdk12_status", "ctdna_detected", "ctdna_vaf", "ctdna_rising",
                      "tmb_value", "tmb_mutations_per_mb", "nse", "neuron_specific_enolase",
                      "ldh", "lactate_dehydrogenase", "psa_discordant_low", "neuroendocrine_features"):
            if gkey not in genomic and patient.get(gkey) is not None:
                genomic[gkey] = patient[gkey]

        from prostanet.domains.m1_crpc.rules_nccn import _status_positive
        precision_panel: dict[str, Any] = {
            "ar_v7": {
                "status": str(genomic.get("ar_v7_status", "No evaluado")),
                "positive": _status_positive(genomic, "ar_v7_status"),
                "clinical_action": "Resistencia a ARPI — preferir taxanos" if _status_positive(genomic, "ar_v7_status") else None,
            },
            "tp53_rb1": {
                "tp53": str(genomic.get("tp53_status", "No evaluado")),
                "rb1": str(genomic.get("rb1_status", "No evaluado")),
                "lineage_plasticity": _status_positive(genomic, "tp53_status") and _status_positive(genomic, "rb1_status"),
                "clinical_action": "Vigilancia NEPC activa" if (_status_positive(genomic, "tp53_status") and _status_positive(genomic, "rb1_status")) else None,
            },
            "pten": {
                "status": str(genomic.get("pten_loss", genomic.get("pten_status", "No evaluado"))),
                "loss": _status_positive(genomic, "pten_loss") or _status_positive(genomic, "pten_status"),
                "clinical_action": "Candidato AKT inhibitor" if (_status_positive(genomic, "pten_loss") or _status_positive(genomic, "pten_status")) else None,
            },
            "cdk12": {
                "status": str(genomic.get("cdk12_status", "No evaluado")),
                "biallelic": _status_positive(genomic, "cdk12_status"),
                "clinical_action": "Candidato IO independiente de MSI" if _status_positive(genomic, "cdk12_status") else None,
            },
            "tmb": {
                "value": None,
                "zone": "unknown",
            },
            "ctdna": {
                "detected": str(genomic.get("ctdna_detected", "0")) == "1",
                "vaf": None,
                "rising": str(genomic.get("ctdna_rising", "0")) == "1",
                "clinical_action": "Resistencia emergente — anticipar cambio" if str(genomic.get("ctdna_rising", "0")) == "1" else None,
            },
            "nepc_suspicion": {
                "score": 0,
                "suspected": False,
            },
        }
        # TMB
        try:
            tmb_v = float(genomic.get("tmb_value") or genomic.get("tmb_mutations_per_mb") or 0)
            if tmb_v > 0:
                precision_panel["tmb"]["value"] = tmb_v
                precision_panel["tmb"]["zone"] = "high" if tmb_v > 10 else ("gray" if tmb_v >= 6 else "low")
        except (ValueError, TypeError):
            pass
        # ctDNA VAF
        try:
            vaf = float(genomic.get("ctdna_vaf") or 0)
            if vaf > 0:
                precision_panel["ctdna"]["vaf"] = vaf
        except (ValueError, TypeError):
            pass
        # NEPC score
        nepc_s = 0
        if precision_panel["tp53_rb1"]["lineage_plasticity"]:
            nepc_s += 2
        if str(genomic.get("neuroendocrine_features", "0")) == "1":
            nepc_s += 2
        try:
            nse_v = float(genomic.get("nse") or genomic.get("neuron_specific_enolase") or 0)
            if nse_v > 16.3:
                nepc_s += 1
        except (ValueError, TypeError):
            pass
        try:
            ldh_v = float(genomic.get("ldh") or genomic.get("lactate_dehydrogenase") or 0)
            if ldh_v > 250:
                nepc_s += 1
        except (ValueError, TypeError):
            pass
        if str(genomic.get("psa_discordant_low", "0")) == "1":
            nepc_s += 1
        precision_panel["nepc_suspicion"]["score"] = nepc_s
        precision_panel["nepc_suspicion"]["suspected"] = nepc_s >= 3

        # Count actionable biomarkers
        actionable_count = sum(1 for v in precision_panel.values() if isinstance(v, dict) and v.get("clinical_action"))
        precision_panel["actionable_count"] = actionable_count
        precision_panel["has_data"] = any(
            isinstance(v, dict) and (v.get("positive") or v.get("loss") or v.get("biallelic") or v.get("detected") or v.get("value"))
            for v in precision_panel.values()
        )

        copilot["precision_genomics"] = precision_panel
    except Exception as exc:
        copilot_logger.debug("Copilot precision genomics error: %s", exc)
        copilot["precision_genomics"] = {"has_data": False, "actionable_count": 0}

    # ── Oligometastatic assessment (Salto 4) ──
    try:
        from prostanet.domains.patient_tracking.oligomet_engine import OligometDecisionEngine
        oligo_data: dict[str, Any] = {}
        oligo_data.update(identity)
        oligo_data.update(baseline)
        oligo_data.update(prior)
        if followups:
            oligo_data.update(followups[-1])

        oligo_lesions: list[dict[str, Any]] = []
        for lesion in patient.get("lesion_tracking") or []:
            les: dict[str, Any] = dict(lesion)
            measurements = les.get("measurements") or []
            meas = measurements[-1] if measurements else {}
            if meas:
                les["longest_diameter_mm"] = meas.get("longest_diameter_mm")
                les["suvmax"] = meas.get("suvmax")
            if les.get("suvmax") and float(les["suvmax"] or 0) > 0:
                les["psma_avid"] = "1"
            oligo_lesions.append(les)

        oligo_data["lesions"] = oligo_lesions
        oligo_data["psma_positive"] = "1" if any(
            str(l.get("psma_avid", "0")) == "1" for l in oligo_lesions
        ) else str(oligo_data.get("psma_positive", "0"))

        oligo_result = OligometDecisionEngine.evaluate(oligo_data)
        copilot["oligomet_assessment"] = oligo_result
    except Exception as exc:
        copilot_logger.debug("Copilot oligomet error: %s", exc)
        copilot["oligomet_assessment"] = {"has_data": False}

    # ── DDI + Formulary review (Salto 5) ──
    try:
        from prostanet.shared.ddi_engine import DDIEngine
        ddi_data: dict[str, Any] = {}
        ddi_data.update(identity)
        ddi_data.update(baseline)
        ddi_data.update(prior)
        if followups:
            ddi_data.update(followups[-1])

        # Get institution from patient data
        institution = str(ddi_data.get("institution") or ddi_data.get("institucion") or "privado").lower()

        ddi_data["institution"] = institution
        ddi_raw = DDIEngine.full_review(ddi_data)
        # Normalize keys for template
        copilot["ddi_review"] = {
            "interactions": ddi_raw.get("ddi_alerts", []),
            "formulary": ddi_raw.get("formulary", []),
            "has_interactions": ddi_raw.get("ddi_count", 0) > 0,
            "has_formulary": len(ddi_raw.get("formulary", [])) > 0,
        }
    except Exception as exc:
        copilot_logger.debug("Copilot DDI review error: %s", exc)
        copilot["ddi_review"] = {"interactions": [], "formulary": [], "has_interactions": False, "has_formulary": False}

    # ── Response visualization (waterfall, spider, swimmer) ──
    try:
        from prostanet.domains.reporting.response_visualization import ResponseVisualizationService
        treatments = patient.get("treatments") or []
        psa_series = patient.get("psa_series") or []
        lesion_data = patient.get("lesion_tracking") or []

        diagnosis_date = identity.get("diagnosis_date")
        baseline_psa_val = baseline.get("baseline_psa")

        viz_bundle = ResponseVisualizationService.build_visualization_bundle(
            treatments=treatments,
            lesions=lesion_data,
            psa_series=psa_series,
            baseline_psa=float(baseline_psa_val) if baseline_psa_val else None,
            diagnosis_date=diagnosis_date,
        )
        copilot["response_visualization"] = viz_bundle.to_dict()
    except Exception as exc:
        copilot_logger.debug("Copilot response visualization error: %s", exc)
        copilot["response_visualization"] = {"waterfall": [], "spider": {"has_data": False}, "swimmer": [], "psa_trajectory": {"has_data": False}}

    response_assessments = patient.get("response_assessments") or []
    if response_assessments:
        copilot["latest_response_assessment"] = response_assessments[0]

    # ── TNM Staging ──
    try:
        from prostanet.shared.tnm_engine import TNMEngine
        tnm_data: dict[str, Any] = {}
        tnm_data.update(identity)
        tnm_data.update(baseline)
        tnm_data.update(prior)
        if followups:
            tnm_data.update(followups[-1])
        # Also check the assessment input_snapshot for clinical_tstage
        input_snap = (raw_assessment or {}).get("input_snapshot", {})
        if input_snap:
            for key in ("clinical_tstage", "nodal_status", "metastasis_site", "dre_finding", "dre_suspicious"):
                if input_snap.get(key) and not tnm_data.get(key):
                    tnm_data[key] = input_snap[key]
        copilot["tnm_staging"] = TNMEngine.assemble(tnm_data)
    except Exception as exc:
        copilot_logger.debug("Copilot TNM staging error: %s", exc)
        copilot["tnm_staging"] = {"has_data": False}

    # ── Structured biopsy section ──
    try:
        from prostanet.domains.patient_tracking.structured_biopsy import StructuredBiopsyService
        biopsies = patient.get("biopsies") or []
        if biopsies and isinstance(biopsies[-1], dict):
            parsed_biopsy = StructuredBiopsyService.parse_structured_biopsy(biopsies[-1])
            copilot["structured_biopsy"] = StructuredBiopsyService.build_biopsy_summary_for_profile(parsed_biopsy)
        else:
            copilot["structured_biopsy"] = {"has_data": False}
    except Exception as exc:
        copilot_logger.debug("Copilot structured biopsy error: %s", exc)
        copilot["structured_biopsy"] = {"has_data": False}

    # ── Active surveillance protocol section ──
    try:
        from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
        if management_track == "active_surveillance" or state == "localized_initial":
            as_data: dict[str, Any] = {}
            as_data.update(identity)
            as_data.update(baseline)
            as_data.update(prior)
            if followups:
                as_data.update(followups[-1])
            as_protocol = ActiveSurveillanceService.build_as_protocol(as_data, state)
            copilot["active_surveillance"] = ActiveSurveillanceService.build_as_summary_for_profile(as_protocol)
        else:
            copilot["active_surveillance"] = {"has_data": False}
    except Exception as exc:
        copilot_logger.debug("Copilot active surveillance error: %s", exc)
        copilot["active_surveillance"] = {"has_data": False}

    # ── Radiotherapy detail section ──
    try:
        from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService
        rt_courses = patient.get("rt_courses") or patient.get("radiotherapy_courses") or []
        if rt_courses:
            rt_summary = RadiotherapyDetailService.build_rt_history(patient)
            copilot["radiotherapy_detail"] = RadiotherapyDetailService.build_rt_summary_for_profile(rt_summary)
        else:
            copilot["radiotherapy_detail"] = {"has_data": False}
    except Exception as exc:
        copilot_logger.debug("Copilot radiotherapy detail error: %s", exc)
        copilot["radiotherapy_detail"] = {"has_data": False}

    # ── Skeletal events section ──
    try:
        from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
        sre_raw = patient.get("skeletal_events") or patient.get("sre_events") or []
        if sre_raw or state in ADVANCED_STATES:
            sre_data: dict[str, Any] = {}
            sre_data.update(identity)
            sre_data.update(baseline)
            sre_data.update(prior)
            if followups:
                sre_data.update(followups[-1])
            sre_data["skeletal_events"] = sre_raw
            sre_profile = SkeletalEventService.build_sre_profile(sre_data, state)
            copilot["skeletal_events"] = SkeletalEventService.build_sre_summary_for_profile(sre_profile)
        else:
            copilot["skeletal_events"] = {"has_data": False}
    except Exception as exc:
        copilot_logger.debug("Copilot skeletal events error: %s", exc)
        copilot["skeletal_events"] = {"has_data": False}

    # ── Survival endpoints section ──
    try:
        from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
        survival_status = SurvivalEndpointService.compute_endpoints(patient, state)
        copilot["survival_endpoints"] = SurvivalEndpointService.build_survival_summary_for_profile(survival_status)
    except Exception as exc:
        copilot_logger.debug("Copilot survival endpoints error: %s", exc)
        copilot["survival_endpoints"] = {"has_data": False}

    return copilot


def build_patient_profile_view_model(
    *,
    patient: dict[str, Any],
    latest_assessment_raw: dict[str, Any] | None,
    latest_assessment: dict[str, Any] | None,
    state_timeline: list[dict[str, Any]],
    care_overlays: list[dict[str, Any]],
    recommendations: dict[str, Any] | None = None,
    longitudinal_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assessment = latest_assessment or {}
    raw_assessment = latest_assessment_raw or {}
    reconciliation_input = dict(raw_assessment)
    for key, value in assessment.items():
        if value not in (None, "", [], {}):
            reconciliation_input[key] = value
    if raw_assessment.get("input_snapshot") and not reconciliation_input.get("input_snapshot"):
        reconciliation_input["input_snapshot"] = raw_assessment.get("input_snapshot")
    reconciliation = build_reconciled_state(
        patient,
        patient.get("latest_assessment") or reconciliation_input or assessment,
    )
    state = reconciliation.get("reconciled_state") or assessment.get("state") or patient.get("prior_history", {}).get("current_state") or ""
    diagnostic_state = state in DIAGNOSTIC_STATES
    display_result = assessment.get("display_result", {}) if assessment else {}
    management_track = reconciliation.get("reconciled_management_track") or infer_management_track(patient, state, raw_assessment)
    operational_module_label = _first_nonempty(assessment.get("module_label"), STATE_DISPLAY_MAP.get(state), state)
    diagnosis_context = build_official_diagnosis_context(
        patient=patient,
        state=state,
        raw_assessment=raw_assessment,
        display_assessment=assessment,
        operational_module_label=operational_module_label,
    )
    risk_tools_bundle = build_risk_tools_panel(
        patient=patient,
        state=state,
        raw_assessment=raw_assessment,
        display_assessment=assessment,
    )
    triplet_decision = _build_triplet_decision_for_profile(
        state=state,
        raw_assessment=raw_assessment,
    )
    agenda_board = build_agenda_board(patient, state, management_track, raw_assessment)
    persisted_agenda_items = [dict(item) for item in (patient.get("agenda_items") or agenda_board.get("items", []))]
    scheduled_by_key = {
        str(item.get("schedule_key") or ""): item
        for item in (patient.get("scheduled_events") or [])
        if str(item.get("schedule_key") or "")
    }
    for item in persisted_agenda_items:
        scheduled = scheduled_by_key.get(str(item.get("agenda_key") or ""), {})
        item["plan_key"] = scheduled.get("plan_key") or item.get("plan_key") or ""
        item["ideal_due_at"] = scheduled.get("ideal_due_at") or item.get("ideal_due_at") or item.get("due_at") or ""
        item["scheduled_due_at"] = scheduled.get("scheduled_due_at") or item.get("scheduled_due_at") or item.get("due_at") or ""
        item["delay_days"] = int(scheduled.get("delay_days") or item.get("delay_days") or 0)
        item["completed_at"] = scheduled.get("completed_at") or item.get("completed_at") or ""
        item["required"] = bool(scheduled.get("required", item.get("required", True)))
        item["action_mode"] = scheduled.get("action_mode") or item.get("action_mode") or "capture"
        if item["completed_at"] and str(item.get("status") or "") not in {"cancelled", "superseded"}:
            item["status"] = "completed"
    persisted_agenda_items.sort(key=longitudinal_item_sort_key)
    active_agenda_items = [item for item in persisted_agenda_items if item.get("status") not in {"completed", "superseded", "cancelled"}]
    archived_agenda_items = [item for item in persisted_agenda_items if item.get("status") in {"completed", "superseded", "cancelled"}]
    next_due_items = [item for item in active_agenda_items if item.get("status") in {"due", "due_today"}][:4]
    overdue_items = [item for item in active_agenda_items if item.get("status") == "overdue"][:4]
    active_recommendations = [item for item in active_agenda_items if item.get("status") in {"due", "due_today", "overdue", "scheduled", "blocked"}][:5]
    agenda_board["items"] = active_agenda_items
    agenda_board["active_items"] = active_agenda_items
    agenda_board["archived_items"] = archived_agenda_items
    agenda_board["next_due_items"] = next_due_items
    agenda_board["overdue_items"] = overdue_items
    agenda_board["active_recommendations"] = active_recommendations
    from prostanet.domains.patient_tracking.encounter_planner import build_encounter_plans

    timeline_agenda_items = sorted(
        [dict(item) for item in [*active_agenda_items, *archived_agenda_items]],
        key=longitudinal_item_sort_key,
    )
    enriched_encounters = build_encounter_plans(
        timeline_agenda_items,
        state=state,
        management_track=management_track,
        protocol_trace=agenda_board.get("protocol_trace") or {},
    )
    actionable_encounters = [
        encounter
        for encounter in enriched_encounters
        if str(encounter.get("status") or "scheduled") not in {"completed", "cancelled", "superseded"}
    ]
    agenda_board["encounters"] = enriched_encounters
    agenda_board["next_encounter"] = next(
        (encounter for encounter in actionable_encounters if str(encounter.get("visit_modality") or "") != "async"),
        actionable_encounters[0] if actionable_encounters else {},
    )
    latest_signal_snapshot = dict(patient.get("latest_signal_snapshot") or {})
    latest_signal_snapshot.update(
        {
            "explicit_state": reconciliation.get("explicit_state"),
            "reconciled_state": reconciliation.get("reconciled_state"),
            "reconciled_management_track": reconciliation.get("reconciled_management_track"),
            "state_conflict_flag": reconciliation.get("state_conflict_flag"),
            "state_conflict_reason": reconciliation.get("state_conflict_reason"),
            "supporting_evidence": reconciliation.get("supporting_evidence", {}),
        }
    )
    latest_signal_snapshot.setdefault("critical_missing", [])
    latest_signal_snapshot.setdefault("awaiting_review", [])
    latest_signal_snapshot.setdefault("active_safety", [])
    adjudication_snapshot = dict(patient.get("latest_adjudication_snapshot") or {})
    trial_benchmark_snapshot = dict(patient.get("latest_trial_benchmark_snapshot") or {})
    if not adjudication_snapshot or not trial_benchmark_snapshot:
        from prostanet.domains.patient_tracking.disease_course_outcomes import build_disease_course_bundle

        runtime_outcomes = build_disease_course_bundle(
            patient,
            state=state,
            management_track=management_track,
            latest_assessment=raw_assessment,
        )
        adjudication_snapshot = {
            "current_course_status": runtime_outcomes.get("current_course_status", ""),
            "current_response_state": runtime_outcomes.get("current_response_state", {}),
            "last_adjudicated_event": runtime_outcomes.get("last_adjudicated_event", {}),
            "pending_adjudications": runtime_outcomes.get("pending_adjudications", []),
            "outcome_events_summary": runtime_outcomes.get("outcome_events_summary", {}),
            "milestone_plan": runtime_outcomes.get("milestone_plan", []),
            "outcome_anchor": runtime_outcomes.get("outcome_anchor", {}),
        }
        trial_benchmark_snapshot = {
            "current_trial_profile": runtime_outcomes.get("current_trial_comparable_profile", {}),
            "trial_endpoints": runtime_outcomes.get("trial_comparable_endpoints", []),
            "benchmark_snapshot": {
                "benchmark_snapshots": runtime_outcomes.get("benchmark_snapshots", []),
                "survival_status": runtime_outcomes.get("survival_status", {}),
            },
        }
        patient_outcome_events = runtime_outcomes.get("outcome_events", [])
    else:
        patient_outcome_events = list(patient.get("outcome_events") or [])
    current_trial_profile = dict(trial_benchmark_snapshot.get("current_trial_profile") or {})
    if current_trial_profile and not current_trial_profile.get("recommended_trial_backbone_label"):
        current_trial_profile.update(
            summarize_trial_backbones(list(current_trial_profile.get("matched_trials") or []))
        )
        trial_benchmark_snapshot["current_trial_profile"] = current_trial_profile
    longitudinal_bundle = longitudinal_bundle or {}
    psa_forecast = dict(longitudinal_bundle.get("psa_forecast") or {})
    live_benchmark = dict(longitudinal_bundle.get("live_benchmark") or {})
    if not psa_forecast:
        from prostanet.domains.patient_tracking.psa_forecast import build_psa_forecast

        psa_forecast = build_psa_forecast(patient, state=state)
    if not live_benchmark:
        try:
            import tracking_db
            from prostanet.domains.patient_tracking.live_benchmark import build_live_benchmark

            conn = tracking_db.connect_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
            cohort_ids = [int(row[0]) for row in cursor.fetchall()]
            conn.close()
            cohort_records = [
                tracking_db.get_patient_full_record(candidate_id)
                for candidate_id in cohort_ids
                if candidate_id
            ]
            live_benchmark = build_live_benchmark(
                patient,
                cohort_records,
                state=state,
                management_track=management_track,
            )
        except Exception:
            live_benchmark = {
                "status": "not_applicable",
                "show": False,
                "state": state,
                "narrative": "Benchmark Vivo no pudo calcularse con el contexto actual.",
                "flags": ["comparabilidad_limitada"],
                "reliability": {
                    "cohort_size": 0,
                    "percentile_available": False,
                    "curve_available": False,
                    "published_reference_available": False,
                    "confidence_label": "not_applicable",
                    "cohort_tier": "none",
                },
            }
    forecast_reliability = dict(psa_forecast.get("reliability") or {})
    benchmark_reliability = dict(live_benchmark.get("reliability") or {})
    prognostic_impact_bundle = build_prognostic_impact_bundle(
        patient=patient,
        state=state,
        management_track=management_track,
        raw_assessment=raw_assessment,
        risk_tools_bundle=risk_tools_bundle,
        current_trial_profile=current_trial_profile,
    )
    latest_signal_snapshot.update(
        {
            "outcome_events_summary": adjudication_snapshot.get("outcome_events_summary", {}),
            "pending_adjudications": adjudication_snapshot.get("pending_adjudications", []),
            "current_response_state": adjudication_snapshot.get("current_response_state", {}),
            "current_course_status": adjudication_snapshot.get("current_course_status", ""),
            "last_adjudicated_event": adjudication_snapshot.get("last_adjudicated_event", {}),
            "trial_comparable_endpoints": trial_benchmark_snapshot.get("trial_endpoints", []),
            "current_trial_comparable_profile": trial_benchmark_snapshot.get("current_trial_profile", {}),
            "prognostic_modifiers": prognostic_impact_bundle.get("prognostic_modifiers", []),
            "prognostic_recommended_actions": prognostic_impact_bundle.get("recommended_actions", []),
            "prognostic_followup_impact": prognostic_impact_bundle.get("followup_impact", []),
            "prognostic_capture_targets": prognostic_impact_bundle.get("capture_targets", []),
            "backbone_alignment": prognostic_impact_bundle.get("backbone_alignment", {}),
            "cadence_adjusted_by": prognostic_impact_bundle.get("cadence_adjusted_by", []),
            "psa_forecast": psa_forecast,
            "forecast_reliability": forecast_reliability,
            "live_benchmark": live_benchmark,
            "benchmark_reliability": benchmark_reliability,
        }
    )
    transition_proposals = [
        proposal for proposal in (patient.get("transition_proposals") or []) if proposal.get("proposal_status") == "open"
    ]
    document_board = _build_document_board(patient)
    copilot_sections = _build_copilot_sections(patient, state, management_track, raw_assessment)
    master_followup_plan = build_master_followup_plan(
        patient,
        state=state,
        management_track=management_track,
        agenda_board=agenda_board,
        signals=latest_signal_snapshot,
        copilot_alerts=copilot_sections.get("clinical_alerts") or patient.get("alerts") or [],
        next_best_action=latest_signal_snapshot.get("next_best_action") or {},
    )
    agenda_board["master_followup_plan"] = master_followup_plan
    agenda_board["master_followup_summary"] = master_followup_plan.get("summary", {})
    agenda_board["alerts_linked"] = master_followup_plan.get("blocking_alerts", [])
    copilot_modifiers = _build_parallel_modifier_bundle(copilot_sections, state)
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    display_result = assessment.get("display_result", {}) if assessment else {}
    advanced_panel_context = {}
    missing_inputs_by_panel = {}
    stage_specific_panels = _build_stage_specific_panels(
        patient=patient,
        state=state,
        raw_assessment=raw_assessment,
        display_assessment=assessment,
        copilot_modifiers=copilot_modifiers,
    )
    if state in ADVANCED_STATES:
        stage_specific_panels, advanced_panel_context, missing_inputs_by_panel = _advanced_panels(
            patient,
            raw_assessment,
            raw_result,
            display_result,
            copilot_sections,
        )
        modifier_panel = _copilot_orientation_panel(copilot_modifiers or {})
        if modifier_panel:
            stage_specific_panels.append(modifier_panel)
    if diagnosis_context.get("official_diagnosis_missing_fields_raw"):
        missing_inputs_by_panel["official_diagnosis"] = diagnosis_context.get("official_diagnosis_missing_fields_raw", [])
    pivotal_panel = _build_pivotal_panel(patient.get("pivotal_matches", []), state=state)
    evidence_applicability = _build_evidence_applicability(
        state=state,
        pivotal_panel=pivotal_panel,
        display_assessment=assessment,
    )
    cohort_completeness = compute_patient_cohort_completeness(patient, state)
    research_readiness = compute_patient_research_readiness(patient, state)
    endpoint_readiness = compute_patient_endpoint_readiness(patient, state)
    patient_kpis = build_patient_kpis(
        patient,
        state=state,
        management_track=management_track,
        agenda_board=agenda_board,
        signals=latest_signal_snapshot,
    )
    missing_input_actions, intake_capture_target, followup_capture_target = _build_missing_input_actions(
        patient=patient,
        state=state,
        management_track=management_track,
        missing_inputs_by_panel=missing_inputs_by_panel,
        therapy_checkpoints=agenda_board.get("therapy_checkpoints", []),
        agenda_items=active_agenda_items,
        copilot=copilot_sections,
    )
    capture_bundle = build_missing_input_capture_bundle(
        patient=patient,
        state=state,
        management_track=management_track,
        missing_inputs_by_panel=missing_inputs_by_panel,
        therapy_checkpoints=agenda_board.get("therapy_checkpoints", []),
        agenda_items=active_agenda_items,
        copilot=copilot_sections,
    )
    psa_observability = _build_psa_observability(patient, copilot_sections)
    psa_observability["forecast"] = psa_forecast
    response_visualization = dict(copilot_sections.get("response_visualization") or {})
    psa_trajectory = dict(response_visualization.get("psa_trajectory") or {})
    if psa_observability.get("points") and not psa_trajectory.get("points"):
        psa_trajectory["points"] = list(psa_observability.get("points") or [])
    if psa_observability.get("treatment_bands") and not psa_trajectory.get("treatment_bands"):
        psa_trajectory["treatment_bands"] = list(psa_observability.get("treatment_bands") or [])
    integrated_timeline = dict(psa_trajectory.get("integrated_treatment_timeline") or {})
    axis_dates = set(psa_trajectory.get("axis_dates") or [])
    axis_dates.update(point.get("date") for point in (psa_trajectory.get("points") or []) if point.get("date"))
    psa_trajectory["forecast_curve"] = list(psa_forecast.get("forecast_curve") or [])
    psa_trajectory["forecast_points"] = list(psa_forecast.get("forecast_points") or [])
    psa_trajectory["forecast_status"] = psa_forecast.get("status", "")
    psa_trajectory["forecast_reliability"] = forecast_reliability
    axis_dates.update(point.get("date") for point in (psa_forecast.get("forecast_curve") or []) if point.get("date"))
    if integrated_timeline:
        integrated_axis_dates = set(integrated_timeline.get("axis_dates") or [])
        integrated_axis_dates.update(axis_dates)
        integrated_timeline["axis_dates"] = sorted(date_text for date_text in integrated_axis_dates if date_text)
        psa_trajectory["integrated_treatment_timeline"] = integrated_timeline
    psa_trajectory["axis_dates"] = sorted(date_text for date_text in axis_dates if date_text)
    psa_trajectory["has_data"] = bool(
        psa_trajectory.get("points")
        or (psa_trajectory.get("integrated_treatment_timeline") or {}).get("has_integrated_timeline")
    )
    response_visualization["psa_trajectory"] = psa_trajectory
    copilot_sections["response_visualization"] = response_visualization
    clinical_journey_events = _build_clinical_journey_events(patient, state)
    for line_event in psa_observability.get("line_events") or []:
        if line_event not in clinical_journey_events:
            clinical_journey_events.append(line_event)
    clinical_journey_events = sorted(
        [event for event in clinical_journey_events if event.get("date")],
        key=lambda item: str(item.get("date")),
        reverse=True,
    )[:24]
    agenda_resolution_trace = _build_agenda_resolution_trace(archived_agenda_items)
    return {
        "diagnostic_state": diagnostic_state,
        "management_track": management_track,
        "reconciled_state": state,
        "reconciled_management_track": management_track,
        "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
        "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
        "clinical_compass": _build_clinical_compass(
            patient=patient,
            state=state,
            reconciliation=reconciliation,
            display_assessment=assessment,
            raw_assessment=raw_assessment,
            state_timeline=state_timeline,
            diagnosis_context=diagnosis_context,
            copilot_modifiers=copilot_modifiers,
        ),
        "official_diagnosis": diagnosis_context.get("official_diagnosis", ""),
        "official_diagnosis_status": diagnosis_context.get("official_diagnosis_status", "missing"),
        "official_diagnosis_missing_fields": diagnosis_context.get("official_diagnosis_missing_fields", []),
        "official_diagnosis_source_summary": diagnosis_context.get("official_diagnosis_source_summary", ""),
        "operational_module_label": diagnosis_context.get("operational_module_label", operational_module_label),
        "risk_tools_panel": risk_tools_bundle.get("cards", []),
        "upgrade_panel": risk_tools_bundle.get("upgrade_panel", {}),
        "risk_tool_missing_inputs": risk_tools_bundle.get("missing_inputs", []),
        "risk_tool_fidelity_summary": risk_tools_bundle.get("fidelity_summary", {}),
        "prognostic_modifiers": prognostic_impact_bundle.get("prognostic_modifiers", []),
        "prognostic_recommended_actions": prognostic_impact_bundle.get("recommended_actions", []),
        "prognostic_followup_impact": prognostic_impact_bundle.get("followup_impact", []),
        "prognostic_capture_targets": prognostic_impact_bundle.get("capture_targets", []),
        "backbone_alignment": prognostic_impact_bundle.get("backbone_alignment", {}),
        "cadence_adjusted_by": prognostic_impact_bundle.get("cadence_adjusted_by", []),
        "triplet_decision": triplet_decision,
        "triplet_decision_card": triplet_decision,
        "stage_specific_panels": stage_specific_panels,
        "algorithm_panels": _build_algorithm_panels(
            state=state,
            raw_assessment=raw_assessment,
            display_assessment=assessment,
        ),
        "module_data_contracts": _module_data_contracts(),
        "pivotal_panel": pivotal_panel,
        "evidence_applicability": evidence_applicability,
        "advanced_panel_context": advanced_panel_context,
        "therapy_catalog_options": therapy_select_options(state=state, management_track=management_track, include_empty=True),
        "missing_inputs_by_panel": missing_inputs_by_panel,
        "missing_input_actions": missing_input_actions,
        "missing_input_capture_tasks": capture_bundle.get("tasks", []),
        "intake_capture_target": intake_capture_target,
        "followup_capture_target": followup_capture_target,
        "intake_completion_block": capture_bundle.get("intake_completion_block", {}),
        "followup_completion_block": capture_bundle.get("followup_completion_block", {}),
        "clinical_journey_events": clinical_journey_events,
        "psa_observability": psa_observability,
        "psa_forecast": psa_forecast,
        "forecast_reliability": forecast_reliability,
        "live_benchmark": live_benchmark,
        "benchmark_reliability": benchmark_reliability,
        "agenda_resolution_trace": agenda_resolution_trace,
        "longitudinal_sections": _build_longitudinal_sections(patient, state, assessment),
        "supportive_evidence_context": _as_list(display_result.get("supportive_evidence_context"))[:3],
        "source_citations": display_result.get("source_citations", []),
        "care_overlays": care_overlays,
        "agenda_board": agenda_board,
        "master_followup_plan": master_followup_plan,
        "master_followup_summary": master_followup_plan.get("summary", {}),
        "active_agenda_items": active_agenda_items,
        "archived_agenda_items": archived_agenda_items,
        "encounters": agenda_board.get("encounters", []),
        "next_encounter": agenda_board.get("next_encounter", {}),
        "next_due_items": next_due_items,
        "overdue_items": overdue_items,
        "visit_schema": agenda_board.get("visit_schema", {}),
        "agenda_item_form_context": agenda_board.get("visit_schema", {}).get("agenda_item_context"),
        "therapy_checkpoints": agenda_board.get("therapy_checkpoints", []),
        "protocol_comparators": agenda_board.get("protocol_comparators", []),
        "protocol_trace": agenda_board.get("protocol_trace", {}),
        "data_provenance": (patient.get("data_provenance") or [])[:12],
        "clinical_signals": latest_signal_snapshot,
        "next_best_action": latest_signal_snapshot.get("next_best_action", {}),
        "transition_proposals": transition_proposals,
        "recommendation_audit": (patient.get("recommendation_audit") or [])[:8],
        "outcome_events": patient_outcome_events,
        "outcome_events_summary": adjudication_snapshot.get("outcome_events_summary", {}),
        "pending_adjudications": adjudication_snapshot.get("pending_adjudications", []),
        "current_response_state": adjudication_snapshot.get("current_response_state", {}),
        "current_course_status": adjudication_snapshot.get("current_course_status", ""),
        "last_adjudicated_event": adjudication_snapshot.get("last_adjudicated_event", {}),
        "trial_comparable_endpoints": trial_benchmark_snapshot.get("trial_endpoints", []),
        "current_trial_comparable_profile": trial_benchmark_snapshot.get("current_trial_profile", {}),
        "benchmark_snapshots": (trial_benchmark_snapshot.get("benchmark_snapshot") or {}).get("benchmark_snapshots", []),
        "document_board": document_board,
        "patient_kpis": patient_kpis,
        "cohort_completeness": cohort_completeness,
        "research_readiness": research_readiness,
        "endpoint_readiness": endpoint_readiness,
        "consent_summary": patient.get("consent_summary", {}),
        "consent_evidence": patient.get("consent_evidence", {}),
        "operational_outcomes": patient.get("operational_outcomes", []),
        "clavien_dindo_events": patient.get("clavien_dindo_events", []),
        "functional_recovery_snapshots": patient.get("functional_recovery_snapshots", []),
        "recommendations": recommendations or {},
        "copilot": copilot_sections,
    }
