from __future__ import annotations

import json
from typing import Any

from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board, infer_management_track


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCALIZED_STATES = {"localized_initial"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr"}
ADVANCED_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
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
    "mcspc_high_volume": "mHSPC de alto volumen",
    "m0_crpc": "CRPC sin metástasis",
    "m1_crpc": "CRPC metastásico",
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


def _build_clinical_compass(
    *,
    patient: dict[str, Any],
    state: str,
    display_assessment: dict[str, Any],
    raw_assessment: dict[str, Any],
    state_timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    nccn = display_result.get("nccn_primary", {}) if display_result else {}
    latest_event = state_timeline[-1] if state_timeline else {}
    monitoring = display_result.get("monitoring_plan", {}) if display_result else {}
    decision_quality = display_result.get("decision_quality", {}) if display_result else {}
    freshness = _build_data_freshness(patient, state)
    last_decisive = freshness[1] if state in DIAGNOSTIC_STATES and len(freshness) > 1 else freshness[0]
    current_diagnosis = _first_nonempty(
        nccn.get("label"),
        display_assessment.get("module_label"),
        STATE_DISPLAY_MAP.get(state),
        "Diagnóstico en consolidación",
    )
    return {
        "current_diagnosis": current_diagnosis,
        "current_stage_label": _first_nonempty(display_assessment.get("module_label"), STATE_DISPLAY_MAP.get(state), state),
        "management_intent_status": _first_nonempty(latest_event.get("management_intent_status_label"), "Pendiente de confirmación"),
        "event_kind_label": _first_nonempty(latest_event.get("event_kind_label"), "Recomendación generada"),
        "primary_clinical_question": PRIMARY_QUESTION_MAP.get(state, "¿Cuál es la siguiente mejor decisión clínica?"),
        "recommended_direction": _first_nonempty(nccn.get("trayectoria_recomendada"), nccn.get("recommendation"), "Sin dirección priorizada"),
        "why_this_now": _as_list(nccn.get("fundamentos_personalizados"))[:3] or _as_list(display_result.get("report_sections", {}).get("risk_features"))[:3],
        "what_could_change_course": _as_list(display_result.get("decision_changing_inputs"))[:4] or _as_list(display_result.get("missing_critical_inputs"))[:4],
        "next_actions": _as_list(monitoring.get("actions"))[:4],
        "monitoring_cadence": _first_nonempty(monitoring.get("cadence"), "Sin cadencia estructurada"),
        "data_freshness": freshness,
        "last_decisive_data": last_decisive,
        "evidence_anchor": _build_primary_evidence_anchor(display_result),
        "confidence_category": _first_nonempty(decision_quality.get("confidence_category"), "No documentada"),
        "recommendation_family": _first_nonempty(decision_quality.get("recommendation_family"), raw_result.get("recommendation_family"), "No documentada"),
        "decision_changing_inputs": _as_list(display_result.get("decision_changing_inputs")),
        "why_not_more_confident": _as_list(decision_quality.get("why_not_more_confident")) or _as_list(display_result.get("why_not_more_confident")),
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


def _advanced_panels(patient: dict[str, Any], raw_assessment: dict[str, Any], raw_result: dict[str, Any], display_result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    prior_history = patient.get("prior_history") or {}
    baseline = patient.get("baseline") or {}
    genomics = patient.get("genomics") or {}
    return [
        {
            "title": "Secuenciación sistémica actual",
            "subtitle": "Dónde está parado el paciente hoy y qué trayectorias siguen abiertas.",
            "items": [
                {"label": "Línea terapéutica", "value": _first_nonempty(payload.get("line_of_therapy"), prior_history.get("line_of_therapy"), "No documentada")},
                {"label": "Esquema actual", "value": _first_nonempty(payload.get("drug_scheme"), patient.get("treatments", [{}])[-1].get("drug_scheme") if patient.get("treatments") else "", "No documentado")},
                {"label": "Estado de castración", "value": _first_nonempty(payload.get("castrate_testosterone_status"), "No documentado")},
                {"label": "Imagen convencional", "value": _first_nonempty(payload.get("conventional_imaging_status"), baseline.get("metastasis_site"), "No documentada")},
            ],
            "bullets": [item.get("name") for item in raw_result.get("eligible_treatments", [])[:3]],
        },
        {
            "title": "Biomarcadores y elegibilidad terapéutica",
            "subtitle": "Información accionable que hoy ordena PARP, inmunoterapia, PSMA y secuenciación.",
            "items": [
                {"label": "HRR / BRCA", "value": _first_nonempty(genomics.get("hrr_overall"), payload.get("hrr_status"), payload.get("brca2_status"), baseline.get("hrr_status"), "No documentado")},
                {"label": "MSI / TMB", "value": _first_nonempty(genomics.get("msi_status"), payload.get("msi_status"), payload.get("tmb_high"), baseline.get("msi_status"), "No documentado")},
                {"label": "PSMA", "value": _first_nonempty(payload.get("psma_positive"), "No documentado")},
                {"label": "Lesiones PSMA negativas", "value": _first_nonempty(payload.get("psma_negative_dominant_lesions"), "No documentado")},
            ],
            "bullets": _as_list(display_result.get("decision_changing_inputs"))[:4],
        },
        {
            "title": "Seguridad y soporte concurrente",
            "subtitle": "Capas que cambian aptitud terapéutica y seguimiento longitudinal.",
            "items": [
                {"label": "ECOG", "value": _first_nonempty(baseline.get("ecog_score"), "No documentado")},
                {"label": "Child-Pugh", "value": _first_nonempty(baseline.get("child_pugh_score"), payload.get("child_pugh_score"), "No documentado")},
                {"label": "Riesgo CV documentado", "value": _first_nonempty(payload.get("cv_risk_documented"), "No documentado")},
                {"label": "Bundle óseo", "value": "Completo" if all(_first_nonempty(payload.get(field)) in (1, "1", True, "Realizada", "Realizado", "Iniciada", "Iniciados") for field in ("dxa_baseline_done", "calcium_vitd_started", "bone_protection_started")) else "Incompleto"},
            ],
            "bullets": [overlay.get("title") for overlay in patient.get("care_overlays", [])[:3]],
        },
    ]


def _build_stage_specific_panels(
    *,
    patient: dict[str, Any],
    state: str,
    raw_assessment: dict[str, Any],
    display_assessment: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_result = (raw_assessment or {}).get("result_snapshot", {}) if raw_assessment else {}
    display_result = (display_assessment or {}).get("display_result", {}) if display_assessment else {}
    if state in DIAGNOSTIC_STATES:
        return _diagnostic_panel(patient, raw_assessment)
    if state in LOCALIZED_STATES:
        return _localized_panels(patient, raw_assessment, display_result, raw_result)
    if state in POSTLOCAL_STATES:
        return _postlocal_panels(patient, raw_assessment, display_result)
    if state in ADVANCED_STATES:
        return _advanced_panels(patient, raw_assessment, raw_result, display_result)
    return []


def _segment(label: str, value: Any, tone: str) -> dict[str, Any]:
    number = max(0.0, min(100.0, _safe_float(value) or 0.0))
    return {"label": label, "value": number, "display": f"{number:.1f}%", "tone": tone}


def _algorithm_panel_entry(raw_algorithm: dict[str, Any], display_algorithm: dict[str, Any], stage: str) -> dict[str, Any]:
    key = raw_algorithm.get("key")
    result_snapshot = raw_algorithm.get("result_snapshot", {}) or {}
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
        panel["details"] = raw_algorithm.get("inputs_missing", [])
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
        panel["details"] = raw_algorithm.get("inputs_missing", [])
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
    return normalized


def _build_pivotal_panel(matches: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [_normalize_pivotal_match(item) for item in _dedupe_pivotal_matches(matches)]
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
        "last_evaluated_at": last_evaluated_at,
        "has_results": bool(normalized),
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
        {"key": "state_timeline", "title": "Estados persistidos", "count": len(patient.get("state_timeline", [])), "default_open": True},
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


def build_patient_profile_view_model(
    *,
    patient: dict[str, Any],
    latest_assessment_raw: dict[str, Any] | None,
    latest_assessment: dict[str, Any] | None,
    state_timeline: list[dict[str, Any]],
    care_overlays: list[dict[str, Any]],
    recommendations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assessment = latest_assessment or {}
    raw_assessment = latest_assessment_raw or {}
    state = assessment.get("state") or patient.get("prior_history", {}).get("current_state") or ""
    diagnostic_state = state in DIAGNOSTIC_STATES
    display_result = assessment.get("display_result", {}) if assessment else {}
    management_track = infer_management_track(patient, state, raw_assessment)
    agenda_board = build_agenda_board(patient, state, management_track, raw_assessment)
    persisted_agenda_items = patient.get("agenda_items") or agenda_board.get("items", [])
    next_due_items = [item for item in persisted_agenda_items if item.get("status") == "due"][:4]
    overdue_items = [item for item in persisted_agenda_items if item.get("status") == "overdue"][:4]
    active_recommendations = [item for item in persisted_agenda_items if item.get("status") in {"due", "overdue"}][:5]
    agenda_board["items"] = persisted_agenda_items
    agenda_board["next_due_items"] = next_due_items
    agenda_board["overdue_items"] = overdue_items
    agenda_board["active_recommendations"] = active_recommendations
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    transition_proposals = [
        proposal for proposal in (patient.get("transition_proposals") or []) if proposal.get("proposal_status") == "open"
    ]
    document_board = _build_document_board(patient)
    return {
        "diagnostic_state": diagnostic_state,
        "management_track": management_track,
        "clinical_compass": _build_clinical_compass(
            patient=patient,
            state=state,
            display_assessment=assessment,
            raw_assessment=raw_assessment,
            state_timeline=state_timeline,
        ),
        "stage_specific_panels": _build_stage_specific_panels(
            patient=patient,
            state=state,
            raw_assessment=raw_assessment,
            display_assessment=assessment,
        ),
        "algorithm_panels": _build_algorithm_panels(
            state=state,
            raw_assessment=raw_assessment,
            display_assessment=assessment,
        ),
        "pivotal_panel": _build_pivotal_panel(patient.get("pivotal_matches", [])),
        "longitudinal_sections": _build_longitudinal_sections(patient, state, assessment),
        "supportive_evidence_context": _as_list(display_result.get("supportive_evidence_context"))[:3],
        "source_citations": display_result.get("source_citations", []),
        "care_overlays": care_overlays,
        "agenda_board": agenda_board,
        "next_due_items": next_due_items,
        "overdue_items": overdue_items,
        "visit_schema": agenda_board.get("visit_schema", {}),
        "therapy_checkpoints": agenda_board.get("therapy_checkpoints", []),
        "protocol_comparators": agenda_board.get("protocol_comparators", []),
        "data_provenance": (patient.get("data_provenance") or [])[:12],
        "clinical_signals": latest_signal_snapshot,
        "next_best_action": latest_signal_snapshot.get("next_best_action", {}),
        "transition_proposals": transition_proposals,
        "recommendation_audit": (patient.get("recommendation_audit") or [])[:8],
        "document_board": document_board,
        "recommendations": recommendations or {},
    }
