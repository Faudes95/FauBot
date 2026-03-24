from __future__ import annotations

from typing import Any

from prostanet.domains.patient_tracking.reconciled_state import derive_post_prostatectomy_course


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida", "unknown", "UNKNOWN")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if str(item or "").strip()))


def _text_contains_any(text: str, needles: tuple[str, ...]) -> bool:
    haystack = str(text or "").lower()
    return any(needle in haystack for needle in needles)


def _blocking_input_satisfied(field_name: str, field_values: dict[str, Any]) -> bool:
    value = field_values.get(field_name)
    if field_name == "psa" and not _is_present(value):
        value = field_values.get("bcr_psa") or field_values.get("psa_current") or field_values.get("psa_postop")
    elif field_name == "psa_postop" and not _is_present(value):
        value = field_values.get("bcr_psa") or field_values.get("psa_current") or field_values.get("psa")
    elif field_name == "psadt_months" and not _is_present(value):
        value = field_values.get("psadt_at_bcr")
    elif field_name == "pathologic_stage" and not _is_present(value):
        value = (
            field_values.get("pathologic_stage_group")
            or field_values.get("pathologic_tstage")
            or field_values.get("pathologic_nstage")
            or field_values.get("pathologic_mstage")
        )
    elif field_name == "current_adt_context" and not _is_present(value):
        value = field_values.get("current_treatment") or field_values.get("drug_scheme")
    if field_name == "psma_pet_done":
        return str(value or "").strip().lower() in {"1", "true", "si", "sí", "yes"}
    return _is_present(value)


def _descriptor(field_name: str, *, bucket: str, why_now: str, decision_domains_blocked: list[str], capture_target: str) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "bucket": bucket,
        "why_now": why_now,
        "decision_domains_blocked": list(decision_domains_blocked or []),
        "capture_target": capture_target,
    }


def _overlay_values(values: dict[str, Any], *sources: dict[str, Any], keys: set[str]) -> None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if _is_present(value):
                values[key] = value


STATE_RULES = {
    "diagnostic_workup": {
        "blocking_inputs": ["psa", "psad", "pirads_score", "dre_suspicious"],
        "optional_context_inputs": ["family_history_positive", "germline_risk_mutation", "planned_biopsy_route"],
        "decision_domains_blocked": ["diagnostic_confirmation", "biopsy_timing"],
        "why": "La decisión diagnóstica inicial requiere riesgo clínico, densidad de PSA e imagen dirigida.",
        "capture_target": "intake",
        "focus": "official_diagnosis",
    },
    "post_negative_biopsy_followup": {
        "blocking_inputs": ["psa", "psad", "pirads_score", "prior_biopsy_count"],
        "optional_context_inputs": ["persistent_lesion_signal", "prior_biopsy_mri_targeted"],
        "decision_domains_blocked": ["repeat_biopsy", "diagnostic_reopening"],
        "why": "Sin MRI/PSAD y contexto de biopsias previas no puede definirse si debe reabrirse el estudio.",
        "capture_target": "followup",
        "focus": "official_diagnosis",
    },
    "localized_initial": {
        "blocking_inputs": ["gleason_primary", "gleason_secondary", "isup_grade", "psa"],
        "optional_context_inputs": ["clinical_tstage", "num_cores_positive", "total_cores", "max_core_involvement", "prior_mpmri_pirads_score"],
        "decision_domains_blocked": ["risk_stratification", "local_therapy_selection", "active_surveillance"],
        "why": "La estratificación localizada y la selección entre vigilancia activa, cirugía o RT requieren patología y carga tumoral basal.",
        "capture_target": "intake",
        "focus": "official_diagnosis",
    },
    "post_prostatectomy": {
        "blocking_inputs": ["psa_postop", "pathologic_stage"],
        "optional_context_inputs": ["decipher_risk", "ece_status", "svi_status", "lni_status"],
        "decision_domains_blocked": ["post_rp_followup", "salvage_window"],
        "why": "El seguimiento postoperatorio depende de PSA ultrasensible y patología definitiva.",
        "capture_target": "followup",
        "focus": "psa_monitoring",
    },
    "recurrence_bcr": {
        "blocking_inputs": ["psa", "psadt_months"],
        "optional_context_inputs": ["salvage_local_feasible", "psma_pet_done", "conventional_imaging_status", "decipher_risk"],
        "decision_domains_blocked": ["salvage_decision", "restaging"],
        "why": "La recaída bioquímica requiere cinética de PSA, antecedente local y restadificación para decidir rescate temprano.",
        "capture_target": "followup",
        "focus": "restaging",
    },
    "adt_progression_verification": {
        "blocking_inputs": ["testosterone", "current_adt_context", "progression_pattern", "conventional_imaging_status"],
        "optional_context_inputs": ["drug_scheme", "line_of_therapy_number", "psa", "psma_pet_done"],
        "decision_domains_blocked": ["castration_status", "crpc_restage"],
        "why": "No debe confirmarse progresión resistente a castración sin testosterona sérica y patrón de progresión documentado.",
        "capture_target": "followup",
        "focus": "advanced_sequencing",
    },
    "m0_crpc": {
        "blocking_inputs": ["psadt_months", "testosterone", "current_adt_context"],
        "optional_context_inputs": ["seizure_history", "dermatitis_history", "cv_risk_documented", "drug_interaction_reviewed"],
        "decision_domains_blocked": ["nmcrpc_intensification", "arpi_safety"],
        "why": "La intensificación en nmCRPC depende de PSADT, castración confirmada y perfil de seguridad del ARPI.",
        "capture_target": "followup",
        "focus": "advanced_sequencing",
    },
    "m1_crpc": {
        "blocking_inputs": ["testosterone", "line_of_therapy_number", "drug_scheme", "progression_pattern"],
        "optional_context_inputs": ["hrr_status", "brca2_status", "psma_positive", "psma_negative_dominant_lesions"],
        "decision_domains_blocked": ["mcrpc_sequencing", "precision_pathway", "psma_pathway"],
        "why": "La secuenciación en mCRPC exige castración documentada, línea terapéutica, progresión y biomarcadores accionables.",
        "capture_target": "followup",
        "focus": "advanced_sequencing",
    },
    "mcspc_oligo_metachronous": {
        "blocking_inputs": ["metastasis_site", "metastasis_count", "ecog", "volume_disease"],
        "optional_context_inputs": ["psma_pet_done", "psma_rads_score", "docetaxel_fit", "prior_local_therapy_context"],
        "decision_domains_blocked": ["mhspc_backbone", "mdt_eligibility"],
        "why": "La definición de oligometástasis real y el backbone sistémico dependen de carga metastásica, imagen y fitness.",
        "capture_target": "followup",
        "focus": "restaging",
    },
    "mcspc_low_volume_sync_oligo": {
        "blocking_inputs": ["metastasis_site", "metastasis_count", "ecog", "volume_disease"],
        "optional_context_inputs": ["primary_local_treatment_done", "docetaxel_fit", "psma_pet_done"],
        "decision_domains_blocked": ["mhspc_backbone", "primary_rt"],
        "why": "El bajo volumen sincrónico debe estratificarse bien para decidir RT al primario, doblete o escalamiento.",
        "capture_target": "followup",
        "focus": "restaging",
    },
    "mcspc_high_volume": {
        "blocking_inputs": ["metastasis_site", "metastasis_count", "ecog", "volume_disease"],
        "optional_context_inputs": ["docetaxel_fit", "hrr_status", "brca2_status", "dxa_baseline_done"],
        "decision_domains_blocked": ["mhspc_triplet", "precision_pathway", "bone_support"],
        "why": "El mHSPC de alto volumen requiere carga metastásica, fitness y biomarcadores para elegir doblete/triplete y soporte óseo.",
        "capture_target": "followup",
        "focus": "advanced_sequencing",
    },
}


ABIRATERONE_RULE = {
    "blocking_inputs": ["ast", "alt", "bilirubin", "potassium", "systolic_bp", "glucose"],
    "optional_context_inputs": ["weight_kg", "edema_grade", "hba1c"],
    "decision_domains_blocked": ["abiraterone_safety", "hepatic_monitoring"],
    "why": "Abiraterona requiere monitorización hepática, potasio, presión arterial y glucosa para continuar con seguridad.",
}


PSMA_RULE = {
    "blocking_inputs": [
        "psma_radioligand",
        "psma_rads_score",
        "psma_uptake_pattern",
        "psma_negative_dominant_lesions",
    ],
    "optional_context_inputs": [
        "psma_index_lesion_suvmax",
        "psma_total_lesions",
        "psma_lesion_locations",
        "psma_management_changed",
    ],
    "decision_domains_blocked": ["psma_pathway", "radioligand_selection"],
    "why": "La vía PSMA/radioligando necesita fenotipo estructurado, confianza diagnóstica y discordancia biológica documentada.",
}


ACTIVE_SURVEILLANCE_RULE = {
    "blocking_inputs": ["confirmatory_biopsy_done", "mri_interval_months", "psa", "num_cores_positive"],
    "optional_context_inputs": ["max_core_involvement", "pirads_score", "upgrade_detected"],
    "decision_domains_blocked": ["as_reclassification", "conversion_to_treatment"],
    "why": "La vigilancia activa solo puede sostenerse con biopsia confirmatoria, MRI seriada y triggers de reclasificación actualizados.",
}


def _field_values(patient: dict[str, Any]) -> dict[str, Any]:
    snapshot = patient.get("longitudinal_truth_snapshot") or {}
    values = dict(snapshot.get("field_values") or {})
    baseline = dict(patient.get("baseline") or {})
    assessment_inputs = dict(((patient.get("latest_assessment") or {}).get("input_snapshot") or {}))
    latest_followup = (patient.get("follow_ups") or [{}])[-1] if patient.get("follow_ups") else {}
    latest_followup_payload = (((latest_followup.get("visit_bundle") or {}).get("payload")) or {}) if latest_followup else {}
    latest_stage_visit = (patient.get("stage_visits") or [{}])[-1] if patient.get("stage_visits") else {}
    stage_payload = (((latest_stage_visit.get("visit_bundle") or {}).get("payload")) or {}) if latest_stage_visit else {}
    latest_biopsy = (patient.get("biopsies") or [{}])[-1] if patient.get("biopsies") else {}
    bcr = dict(patient.get("bcr") or {})
    as_protocol = dict(patient.get("active_surveillance_protocol") or {})
    as_legacy = dict(patient.get("active_surveillance") or {})
    latest_treatment = (patient.get("treatments") or [{}])[-1] if patient.get("treatments") else {}
    regimen_json = dict(latest_treatment.get("regimen_json") or {}) if isinstance(latest_treatment.get("regimen_json"), dict) else {}

    for source in (baseline, assessment_inputs, latest_followup, latest_followup_payload, stage_payload, latest_biopsy, bcr, as_protocol, as_legacy, latest_treatment, regimen_json):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if _is_present(value) and not _is_present(values.get(key)):
                values[key] = value

    _overlay_values(
        values,
        latest_followup,
        latest_followup_payload,
        stage_payload,
        latest_treatment,
        regimen_json,
        keys={
            "conventional_imaging_status",
            "progression_pattern",
            "line_of_therapy_number",
            "line_of_therapy",
            "drug_scheme",
            "current_treatment",
            "psma_pet_done",
            "psma_positive",
            "psma_radioligand",
            "psma_rads_score",
            "psma_uptake_pattern",
            "psma_negative_dominant_lesions",
            "psma_stage_after_psma",
            "psadt_months",
            "testosterone",
            "testosterone_current",
            "current_adt_context",
            "mcrpc_line_context",
            "prior_therapy",
        },
    )

    if not _is_present(values.get("management_track")) and _is_present(latest_followup.get("management_track")):
        values["management_track"] = latest_followup.get("management_track")
    if not _is_present(values.get("state")) and _is_present(latest_followup.get("state_at_visit")):
        values["state"] = latest_followup.get("state_at_visit")
    if not _is_present(values.get("psma_pet_done")) and _is_present(patient.get("baseline", {}).get("psma_pet_done")):
        values["psma_pet_done"] = patient.get("baseline", {}).get("psma_pet_done")
    psma_profile = dict(patient.get("psma_structured_profile") or {})
    if not _is_present(values.get("psma_pet_done")) and psma_profile.get("available"):
        values["psma_pet_done"] = 1
    if not _is_present(values.get("psma_rads_score")) and _is_present(psma_profile.get("psma_rads_score")):
        values["psma_rads_score"] = psma_profile.get("psma_rads_score")
    if not _is_present(values.get("psma_uptake_pattern")) and _is_present(psma_profile.get("psma_uptake_pattern")):
        values["psma_uptake_pattern"] = psma_profile.get("psma_uptake_pattern")
    if not _is_present(values.get("line_of_therapy_number")) and _is_present(latest_treatment.get("line_of_therapy")):
        values["line_of_therapy_number"] = latest_treatment.get("line_of_therapy")
    if not _is_present(values.get("line_of_therapy_number")) and _is_present(values.get("line_of_therapy")):
        values["line_of_therapy_number"] = values.get("line_of_therapy")
    if not _is_present(values.get("drug_scheme")) and _is_present(latest_treatment.get("drug_scheme")):
        values["drug_scheme"] = latest_treatment.get("drug_scheme")
    if not _is_present(values.get("psa")) and _is_present(bcr.get("bcr_psa")):
        values["psa"] = bcr.get("bcr_psa")
    if not _is_present(values.get("psa_postop")) and _is_present(bcr.get("bcr_psa")):
        values["psa_postop"] = bcr.get("bcr_psa")
    if not _is_present(values.get("psadt_months")) and _is_present(bcr.get("psadt_at_bcr")):
        values["psadt_months"] = bcr.get("psadt_at_bcr")
    testosterone_value = _safe_float(values.get("testosterone")) or _safe_float(values.get("testosterone_current")) or _safe_float(values.get("testosterone_value"))
    if testosterone_value is not None and not _is_present(values.get("castrate_testosterone_status")):
        values["castrate_testosterone_status"] = "confirmed_castrate" if testosterone_value <= 50 else "not_castrate"
    return values


def build_decision_input_requirements(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    latest_assessment: dict[str, Any] | None = None,
    next_best_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    field_values = _field_values(patient)
    current_state = (
        effective_state
        or str(field_values.get("state") or "")
        or (latest_assessment or {}).get("state")
        or (patient.get("latest_assessment") or {}).get("state")
        or (patient.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )
    current_track = (
        effective_management_track
        or str(field_values.get("management_track") or "")
        or patient.get("schedule_management_track")
        or ""
    )
    treatment_text = str(field_values.get("current_treatment") or field_values.get("drug_scheme") or "").lower()
    psma_profile = dict(patient.get("psma_structured_profile") or {})
    post_prostatectomy_course = derive_post_prostatectomy_course(patient)

    hard_blocking_inputs: list[str] = []
    decision_blocking_inputs: list[str] = []
    supportive_gaps: list[str] = []
    required_to_recalculate: list[str] = []
    optional_context_inputs: list[str] = []
    decision_domains_blocked: list[str] = []
    why_these_fields_now: list[str] = []
    blocking_input_descriptors: list[dict[str, Any]] = []
    focus = "clinical_completion"
    capture_target = "followup" if patient.get("follow_ups") or patient.get("stage_visits") else "intake"

    def add_fields(fields: list[str], *, bucket: str, why: str, domains: list[str]) -> None:
        target = hard_blocking_inputs if bucket == "hard_blocking_inputs" else decision_blocking_inputs if bucket == "decision_blocking_inputs" else supportive_gaps
        for field in fields:
            if not str(field or "").strip():
                continue
            target.append(field)
            blocking_input_descriptors.append(
                _descriptor(
                    str(field),
                    bucket=bucket,
                    why_now=why,
                    decision_domains_blocked=domains,
                    capture_target=capture_target,
                )
            )

    state_rule = STATE_RULES.get(current_state, {})
    if state_rule:
        add_fields(
            list(state_rule.get("blocking_inputs", [])),
            bucket="hard_blocking_inputs",
            why=str(state_rule.get("why", "")),
            domains=list(state_rule.get("decision_domains_blocked", [])),
        )
        required_to_recalculate.extend(state_rule.get("blocking_inputs", []))
        optional_context_inputs.extend(state_rule.get("optional_context_inputs", []))
        decision_domains_blocked.extend(state_rule.get("decision_domains_blocked", []))
        why_these_fields_now.append(state_rule.get("why", ""))
        focus = state_rule.get("focus", focus)
        capture_target = state_rule.get("capture_target", capture_target)

    latest_psa = _safe_float(field_values.get("psa") or field_values.get("psa_postop"))
    prior_radiation = str(field_values.get("prior_radiation") or field_values.get("prior_secondary_rt") or "").strip().lower() in {"1", "true", "yes", "si", "sí"}
    salvage_feasible = str(field_values.get("salvage_local_feasible") or "").strip().lower()
    psma_done = str(field_values.get("psma_pet_done") or "").strip().lower()
    psadt_months = _safe_float(field_values.get("psadt_months"))
    line_of_therapy = _safe_float(field_values.get("line_of_therapy_number"))
    hrr_status = str(field_values.get("hrr_status") or "").strip().lower()
    brca2_status = str(field_values.get("brca2_status") or "").strip().lower()
    progression_pattern = str(field_values.get("progression_pattern") or "").strip().lower()
    treatment_text = treatment_text.lower()

    if current_state == "post_prostatectomy":
        if post_prostatectomy_course == "persistent_psa":
            add_fields(
                ["psadt_months", "salvage_local_feasible"],
                bucket="decision_blocking_inputs",
                why="El PSA persistente postoperatorio exige distinguir vigilancia intensificada vs evaluación temprana de rescate.",
                domains=["salvage_decision"],
            )
            required_to_recalculate.extend(["psadt_months", "salvage_local_feasible"])
            optional_context_inputs.extend(["decipher_risk", "conventional_imaging_status"])
            decision_domains_blocked.extend(["salvage_decision"])
            why_these_fields_now.append("El PSA persistente posoperatorio aún no equivale a BCR, pero sí obliga a definir cinética y factibilidad de rescate.")
            focus = "restaging"
            if salvage_feasible in {"0", "false", "no"} or (latest_psa is not None and latest_psa >= 0.2):
                add_fields(
                    ["psma_pet_done"],
                    bucket="decision_blocking_inputs",
                    why="Si el rescate local ya no es claramente directo, se necesita imagen para redefinir el carril terapéutico.",
                    domains=["restaging"],
                )
                required_to_recalculate.append("psma_pet_done")
                decision_domains_blocked.append("restaging")

    if current_state == "localized_initial":
        add_fields(
            ["clinical_tstage"],
            bucket="decision_blocking_inputs",
            why="El T clínico sigue siendo relevante para cerrar riesgo localizado y escoger entre cirugía, RT o vigilancia.",
            domains=["risk_stratification", "local_therapy_selection"],
        )
        required_to_recalculate.append("clinical_tstage")

    if current_state == "recurrence_bcr":
        if salvage_feasible not in {"1", "true", "yes", "si", "sí"}:
            add_fields(
                ["salvage_local_feasible"],
                bucket="decision_blocking_inputs",
                why="La decisión entre rescate local e intensificación sistémica sigue abierta hasta documentar factibilidad local.",
                domains=["salvage_decision"],
            )
            required_to_recalculate.append("salvage_local_feasible")
        if psadt_months is None:
            why_these_fields_now.append("La recaída bioquímica necesita PSADT antes de cerrar el carril de rescate.")
        if (
            salvage_feasible in {"0", "false", "no"}
            or prior_radiation
            or (latest_psa is not None and latest_psa >= 0.5)
            or (post_prostatectomy_course == "true_bcr" and salvage_feasible in {"1", "true", "yes", "si", "sí"} and latest_psa is not None and latest_psa >= 0.2)
        ) and psma_done not in {"1", "true", "si", "sí", "yes"}:
            add_fields(
                ["psma_pet_done"],
                bucket="decision_blocking_inputs",
                why="La imagen dirigida cambia la decisión cuando el rescate local no es claramente directo o el contexto es post-RT.",
                domains=["restaging"],
            )
            required_to_recalculate.append("psma_pet_done")
            decision_domains_blocked.append("restaging")
            why_these_fields_now.append("Se necesita PSMA-PET para diferenciar rescate local aún factible frente a redirección sistémica.")
            focus = "restaging"
        if psma_done in {"1", "true", "si", "sí", "yes"}:
            add_fields(
                ["psma_rads_score", "psma_uptake_pattern"],
                bucket="decision_blocking_inputs",
                why="Una PSMA realizada pero no estructurada todavía no permite cerrar si la ruta sigue siendo local o ya sistémica.",
                domains=["restaging", "psma_pathway"],
            )
            required_to_recalculate.extend(["psma_rads_score", "psma_uptake_pattern"])
            add_fields(
                ["psma_radioligand", "psma_negative_dominant_lesions"],
                bucket="supportive_gaps",
                why="Estos datos refinan la confianza diagnóstica y la comparabilidad longitudinal de la imagen PSMA.",
                domains=["psma_pathway"],
            )
            optional_context_inputs.extend(["psma_radioligand", "psma_negative_dominant_lesions"])

    if _text_contains_any(treatment_text, ("abirater", "zytiga")):
        add_fields(
            ["ast", "alt", "bilirubin"],
            bucket="hard_blocking_inputs",
            why=ABIRATERONE_RULE["why"],
            domains=ABIRATERONE_RULE["decision_domains_blocked"],
        )
        add_fields(
            ["potassium", "systolic_bp", "glucose"],
            bucket="decision_blocking_inputs",
            why=ABIRATERONE_RULE["why"],
            domains=ABIRATERONE_RULE["decision_domains_blocked"],
        )
        required_to_recalculate.extend(["ast", "alt", "bilirubin"])
        optional_context_inputs.extend(ABIRATERONE_RULE["optional_context_inputs"])
        decision_domains_blocked.extend(ABIRATERONE_RULE["decision_domains_blocked"])
        why_these_fields_now.append(ABIRATERONE_RULE["why"])
        focus = "adt_safety"

    if (_text_contains_any(treatment_text, ("lutec", "pluvicto")) or (
        current_state in {"recurrence_bcr", "m1_crpc"} and (
            psma_profile.get("available")
            or str(field_values.get("psma_pet_done") or "").strip().lower() in {"1", "true", "si", "sí", "yes"}
        )
    )):
        psma_required_fields = ["psma_rads_score", "psma_uptake_pattern"] if psma_done in {"1", "true", "si", "sí", "yes"} else []
        if _text_contains_any(treatment_text, ("lutec", "pluvicto")):
            psma_required_fields = ["psma_radioligand", "psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"]
        add_fields(
            psma_required_fields,
            bucket="decision_blocking_inputs",
            why=PSMA_RULE["why"],
            domains=PSMA_RULE["decision_domains_blocked"],
        )
        required_to_recalculate.extend([field for field in psma_required_fields if field in {"psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"}])
        add_fields(
            [field for field in PSMA_RULE["optional_context_inputs"] if field not in psma_required_fields],
            bucket="supportive_gaps",
            why=PSMA_RULE["why"],
            domains=PSMA_RULE["decision_domains_blocked"],
        )
        optional_context_inputs.extend(PSMA_RULE["optional_context_inputs"])
        decision_domains_blocked.extend(PSMA_RULE["decision_domains_blocked"])
        why_these_fields_now.append(PSMA_RULE["why"])
        focus = "biomarker_eligibility"

    as_track_active = current_track in {"active_surveillance", "as_surveillance"}
    as_signal_present = any(
        _is_present(field_values.get(field))
        for field in ("confirmatory_biopsy_done", "confirmatory_biopsy_planned", "mri_interval_months", "upgrade_detected")
    )
    if as_track_active or current_state == "active_surveillance" or as_signal_present:
        add_fields(
            ["confirmatory_biopsy_done", "mri_interval_months"],
            bucket="hard_blocking_inputs",
            why=ACTIVE_SURVEILLANCE_RULE["why"],
            domains=ACTIVE_SURVEILLANCE_RULE["decision_domains_blocked"],
        )
        add_fields(
            ["psa", "num_cores_positive"],
            bucket="decision_blocking_inputs",
            why=ACTIVE_SURVEILLANCE_RULE["why"],
            domains=ACTIVE_SURVEILLANCE_RULE["decision_domains_blocked"],
        )
        required_to_recalculate.extend(ACTIVE_SURVEILLANCE_RULE["blocking_inputs"])
        optional_context_inputs.extend(ACTIVE_SURVEILLANCE_RULE["optional_context_inputs"])
        decision_domains_blocked.extend(ACTIVE_SURVEILLANCE_RULE["decision_domains_blocked"])
        why_these_fields_now.append(ACTIVE_SURVEILLANCE_RULE["why"])
        focus = "official_diagnosis"

    if current_state == "m0_crpc":
        if psadt_months is not None and psadt_months > 10 and line_of_therapy in (None, 0):
            supportive_gaps.extend(_dedupe(["seizure_history", "cv_risk_documented"]))
        if progression_pattern and progression_pattern not in {"biochemical_only", "mixed"}:
            add_fields(
                ["conventional_imaging_status"],
                bucket="decision_blocking_inputs",
                why="La intensificación nmCRPC pierde precisión si el patrón de progresión ya no parece exclusivamente bioquímico.",
                domains=["nmcrpc_intensification"],
            )

    if current_state == "m1_crpc":
        prior_therapy_text = str(field_values.get("prior_therapy") or "").lower()
        line_context_text = str(field_values.get("mcrpc_line_context") or "").lower()
        has_prior_taxane = any(token in prior_therapy_text for token in ("docetax", "cabazitax"))
        has_prior_arpi = any(token in prior_therapy_text for token in ("abirater", "enza", "apalut", "darolut"))
        card_or_vision_context = (
            has_prior_taxane
            and (
                has_prior_arpi
                or "post_arpi" in line_context_text
                or "post_taxane" in line_context_text
                or "later_line" in line_context_text
            )
        )
        if card_or_vision_context:
            for field in ("line_of_therapy_number", "drug_scheme", "progression_pattern"):
                hard_blocking_inputs = [item for item in hard_blocking_inputs if item != field]
                decision_blocking_inputs = [item for item in decision_blocking_inputs if item != field]
            blocking_input_descriptors = [
                item for item in blocking_input_descriptors
                if item.get("field_name") not in {"line_of_therapy_number", "drug_scheme", "progression_pattern"}
            ]
            add_fields(
                ["psma_radioligand", "psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"],
                bucket="decision_blocking_inputs",
                why="En el contexto CARD/VISION la elegibilidad PSMA estructurada pesa más que volver a pedir la línea ya conocida.",
                domains=["psma_pathway", "mcrpc_sequencing"],
            )
            required_to_recalculate.extend(["psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"])
            decision_domains_blocked.extend(["psma_pathway", "mcrpc_sequencing"])
            why_these_fields_now.append("La decisión post-taxano debe cerrarse con PSMA estructurada antes de elegir CARD/VISION o radiofármaco.")
        if line_of_therapy is not None and line_of_therapy <= 1 and not _text_contains_any(treatment_text, ("abirater", "enzalut", "apalut", "darolut")):
            add_fields(
                ["drug_scheme"],
                bucket="decision_blocking_inputs",
                why="La m1CRPC temprana debe documentar con claridad si ya recibió ARPI antes de secuenciar nuevas rutas.",
                domains=["mcrpc_sequencing"],
            )
        if hrr_status not in {"positivo", "positive", "pathogenic"} and brca2_status not in {"positivo", "positive", "pathogenic"}:
            supportive_gaps.extend(["hrr_status", "brca2_status"])

    hard_blocking_inputs = _dedupe(hard_blocking_inputs)
    decision_blocking_inputs = _dedupe(decision_blocking_inputs)
    supportive_gaps = _dedupe(supportive_gaps)
    present_blocking = [field for field in _dedupe(hard_blocking_inputs + decision_blocking_inputs) if _blocking_input_satisfied(field, field_values)]
    missing_hard = [field for field in hard_blocking_inputs if not _blocking_input_satisfied(field, field_values)]
    missing_decision = [field for field in decision_blocking_inputs if not _blocking_input_satisfied(field, field_values)]
    missing_supportive = [field for field in supportive_gaps if not _blocking_input_satisfied(field, field_values)]
    missing_blocking = _dedupe(missing_hard + missing_decision)
    headline = str((next_best_action or {}).get("title") or "").strip()
    filtered_descriptors = [
        item for item in blocking_input_descriptors
        if item.get("field_name") in set(missing_blocking + missing_supportive)
    ]

    return {
        "available": bool(hard_blocking_inputs or decision_blocking_inputs or optional_context_inputs or supportive_gaps),
        "effective_state": current_state,
        "effective_management_track": current_track,
        "blocking_inputs": missing_blocking,
        "hard_blocking_inputs": missing_hard,
        "decision_blocking_inputs": missing_decision,
        "supportive_gaps": missing_supportive,
        "required_to_recalculate": _dedupe(required_to_recalculate + missing_blocking),
        "optional_context_inputs": _dedupe(optional_context_inputs),
        "decision_domains_blocked": _dedupe(decision_domains_blocked),
        "why_these_fields_now": [item for item in _dedupe(why_these_fields_now) if item],
        "ready_inputs": present_blocking,
        "headline": headline,
        "blocking_input_descriptors": filtered_descriptors,
        "capture_block": {
            "title": "Completar datos críticos para recalcular la conducta",
            "summary": (
                "La decisión actual necesita datos complementarios antes de cerrar la recomendación."
                if missing_blocking
                else "La decisión ya tiene inputs mínimos, pero aún puede refinarse con contexto adicional."
            ),
            "fields": missing_blocking or missing_supportive or _dedupe(required_to_recalculate),
            "capture_target": capture_target,
            "focus": focus,
        },
    }


def detect_ui_contradiction_flags(
    patient: dict[str, Any],
    *,
    effective_state: str = "",
    effective_management_track: str = "",
    decision_trace: dict[str, Any] | None = None,
    schedule_bundle: dict[str, Any] | None = None,
    transition_resolution: dict[str, Any] | None = None,
    care_intent_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    effective_state = effective_state or patient.get("schedule_state") or ""
    effective_management_track = effective_management_track or patient.get("schedule_management_track") or ""
    decision_trace = dict(decision_trace or {})
    schedule_bundle = dict(schedule_bundle or {})
    transition_resolution = dict(transition_resolution or {})
    care_intent_contract = dict(care_intent_contract or {})
    latest_assessment = dict(patient.get("latest_assessment") or {})
    field_values = _field_values(patient)

    if (
        latest_assessment.get("state")
        and effective_state
        and latest_assessment.get("state") != effective_state
        and str(decision_trace.get("visibility_status") or "") in {"actionable", "contextual"}
        and transition_resolution.get("policy") != "auto_applied"
        and not str(decision_trace.get("headline") or "").lower().startswith("confirmar transición a")
    ):
        flags.append(
            {
                "key": "assessment_vs_effective_state",
                "severity": "warning",
                "title": "El assessment basal ya no coincide con el estado efectivo",
                "details": f"Assessment={latest_assessment.get('state')} vs efectivo={effective_state}.",
            }
        )

    schedule_state = str(schedule_bundle.get("schedule_state") or patient.get("schedule_state") or "")
    schedule_track = str(schedule_bundle.get("schedule_management_track") or patient.get("schedule_management_track") or "")
    override_reason = str(schedule_bundle.get("schedule_override_reason") or patient.get("schedule_override_reason") or "")
    if schedule_state and effective_state and schedule_state != effective_state and not override_reason:
        flags.append(
            {
                "key": "effective_state_vs_schedule_state",
                "severity": "critical",
                "title": "La agenda muestra un estado distinto sin motivo de override",
                "details": f"Efectivo={effective_state} vs agenda={schedule_state}.",
            }
        )
    if schedule_track and effective_management_track and schedule_track != effective_management_track and not override_reason:
        flags.append(
            {
                "key": "effective_track_vs_schedule_track",
                "severity": "critical",
                "title": "El track de agenda no coincide con el track efectivo",
                "details": f"Efectivo={effective_management_track} vs agenda={schedule_track}.",
            }
        )

    headline = str(decision_trace.get("headline") or "").lower()
    castrate_status = str(field_values.get("castrate_testosterone_status") or "").strip()
    if "castración inadecuada" in headline and castrate_status == "confirmed_castrate":
        flags.append(
            {
                "key": "stale_castration_failure_narrative",
                "severity": "critical",
                "title": "Narrativa stale de castración inadecuada",
                "details": "La narrativa principal aún sugiere falla de castración aunque la testosterona longitudinal ya está en rango de castración.",
            }
        )

    if care_intent_contract and schedule_bundle:
        consistency = schedule_bundle.get("action_schedule_consistency")
        if consistency is False:
            flags.append(
                {
                    "key": "care_intent_vs_schedule",
                    "severity": "critical",
                    "title": "La agenda no sigue la intención clínica compartida",
                    "details": f"Intención={care_intent_contract.get('intent_key')} pero schedule_primary_intent={schedule_bundle.get('schedule_primary_intent')}.",
                }
            )

    return flags


__all__ = [
    "build_decision_input_requirements",
    "detect_ui_contradiction_flags",
]
