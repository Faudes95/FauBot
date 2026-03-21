from __future__ import annotations

from typing import Any


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

FOLLOWUP_PREFERRED_FIELDS = {
    "line_of_therapy_number",
    "line_of_therapy_context",
    "drug_scheme",
    "current_treatment",
    "current_adt_context",
    "castrate_testosterone_status",
    "psa",
    "testosterone",
    "alp",
    "ldh",
    "hemoglobin",
    "fatigue_score",
    "mini_cog_score",
    "peripheral_neuropathy_grade",
    "cv_risk_documented",
    "drug_interaction_reviewed",
    "dxa_baseline_done",
    "calcium_vitd_started",
    "bone_protection_started",
    "vitamin_d_level",
}

FIELD_GROUP_HINTS = {
    "line_of_therapy_number": ("advanced_sequencing", "systemic_sequencing"),
    "line_of_therapy_context": ("advanced_sequencing", "systemic_sequencing"),
    "drug_scheme": ("advanced_sequencing", "systemic_sequencing"),
    "current_treatment": ("advanced_sequencing", "systemic_sequencing"),
    "current_adt_context": ("advanced_sequencing", "castration_status"),
    "castrate_testosterone_status": ("advanced_sequencing", "castration_status"),
    "psa": ("psa_monitoring", "disease_control"),
    "testosterone": ("psa_monitoring", "castration_status"),
    "hrr_status": ("biomarker_eligibility", "parp_eligibility"),
    "hrr_gene": ("biomarker_eligibility", "parp_eligibility"),
    "brca2_status": ("biomarker_eligibility", "parp_eligibility"),
    "msi_status": ("biomarker_eligibility", "precision_pathway"),
    "tmb_high": ("biomarker_eligibility", "precision_pathway"),
    "biomarker_source": ("biomarker_eligibility", "precision_pathway"),
    "molecular_assay_date": ("biomarker_eligibility", "precision_pathway"),
    "psma_positive": ("biomarker_eligibility", "psma_eligibility"),
    "psma_negative_dominant_lesions": ("biomarker_eligibility", "psma_eligibility"),
    "dxa_baseline_done": ("bone_support", "bone_safety"),
    "calcium_vitd_started": ("bone_support", "bone_safety"),
    "bone_protection_started": ("bone_support", "bone_safety"),
    "vitamin_d_level": ("bone_support", "bone_safety"),
    "cv_risk_documented": ("adt_safety", "cv_safety"),
    "drug_interaction_reviewed": ("adt_safety", "arpi_safety"),
    "mini_cog_score": ("frailty_fitness", "treatment_fitness"),
    "fatigue_score": ("frailty_fitness", "treatment_fitness"),
    "peripheral_neuropathy_grade": ("frailty_fitness", "treatment_fitness"),
    "weight_kg": ("frailty_fitness", "treatment_fitness"),
    "bmi_current": ("frailty_fitness", "treatment_fitness"),
    "weight_loss_6m_pct": ("frailty_fitness", "treatment_fitness"),
    "g8_food_intake": ("frailty_fitness", "treatment_fitness"),
    "g8_weight_loss": ("frailty_fitness", "treatment_fitness"),
    "g8_mobility": ("frailty_fitness", "treatment_fitness"),
    "g8_neuropsych": ("frailty_fitness", "treatment_fitness"),
    "g8_bmi": ("frailty_fitness", "treatment_fitness"),
    "g8_medications": ("frailty_fitness", "treatment_fitness"),
    "g8_self_health": ("frailty_fitness", "treatment_fitness"),
    "low_activity": ("frailty_fitness", "treatment_fitness"),
    "slow_gait": ("frailty_fitness", "treatment_fitness"),
    "weak_grip": ("frailty_fitness", "treatment_fitness"),
    "ecog": ("frailty_fitness", "treatment_fitness"),
    "ecog_score": ("frailty_fitness", "treatment_fitness"),
    "histology_subtype": ("official_diagnosis", "official_diagnosis"),
    "gleason_primary": ("official_diagnosis", "official_diagnosis"),
    "gleason_secondary": ("official_diagnosis", "official_diagnosis"),
    "isup_grade": ("official_diagnosis", "official_diagnosis"),
    "clinical_tstage": ("official_diagnosis", "official_diagnosis"),
    "nodal_status": ("official_diagnosis", "official_diagnosis"),
    "clinical_stage_group": ("official_diagnosis", "official_diagnosis"),
    "clinical_risk_group": ("official_diagnosis", "official_diagnosis"),
}

GROUP_META = {
    "frailty_fitness": {
        "title": "Completar fragilidad y fitness terapéutica",
        "rationale": "Desbloquea CCI, G8, Fried y aptitud terapéutica con datos reales, sin defaults optimistas.",
        "module_owner": "comorbidity_frailty_fitness",
        "decision_affected": "treatment_fitness",
    },
    "advanced_sequencing": {
        "title": "Confirmar línea terapéutica y secuenciación sistémica",
        "rationale": "Documenta cambios reales de línea y esquema para que el copiloto y la torre de APE por línea reflejen la evolución verdadera.",
        "module_owner": "advanced_panel_context",
        "decision_affected": "systemic_sequencing",
    },
    "biomarker_eligibility": {
        "title": "Completar biomarcadores accionables",
        "rationale": "Puede abrir o cerrar PARP, PSMA u otras rutas de precisión con impacto directo en la decisión.",
        "module_owner": "biomarker_context",
        "decision_affected": "precision_pathway",
    },
    "adt_safety": {
        "title": "Completar seguridad ARPI / ADT",
        "rationale": "Permite ajustar seguridad cardiovascular, cognitiva e interacciones antes de sostener o intensificar tratamiento.",
        "module_owner": "adt_side_effects",
        "decision_affected": "arpi_safety",
    },
    "bone_support": {
        "title": "Completar soporte óseo",
        "rationale": "Aclara riesgo óseo y medidas preventivas para evitar fractura u osteoporosis durante terapia prolongada.",
        "module_owner": "safety_support_context",
        "decision_affected": "bone_safety",
    },
    "psa_monitoring": {
        "title": "Completar monitoreo biológico por línea",
        "rationale": "Permite ver si la línea actual mejoró o perdió control del APE y si ya requiere cambio de conducta.",
        "module_owner": "psa_observability",
        "decision_affected": "disease_control",
    },
    "official_diagnosis": {
        "title": "Completar diagnóstico oficial",
        "rationale": "Permite mostrar un diagnóstico oncológico formal, preciso y trazable en vez de depender solo del módulo clínico operativo.",
        "module_owner": "official_diagnosis",
        "decision_affected": "official_diagnosis",
    },
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(item for item in values if _is_present(item)))


def _resolve_group(field_name: str) -> tuple[str, str]:
    return FIELD_GROUP_HINTS.get(field_name, ("frailty_fitness", "clinical_completion"))


def build_missing_input_capture_bundle(
    *,
    patient: dict[str, Any],
    state: str,
    management_track: str,
    missing_inputs_by_panel: dict[str, list[str]],
    therapy_checkpoints: list[dict[str, Any]],
    agenda_items: list[dict[str, Any]],
    copilot: dict[str, Any],
) -> dict[str, Any]:
    has_followup_flow = bool(patient.get("follow_ups") or patient.get("stage_visits"))
    followup_capture_target = "followup" if has_followup_flow else ""
    intake_capture_target = "intake" if not has_followup_flow else ""
    tasks: list[dict[str, Any]] = []

    def add_task(
        *,
        key: str,
        raw_fields: list[str],
        title: str | None = None,
        rationale: str | None = None,
        input_group: str | None = None,
        module_owner: str | None = None,
        decision_affected: str | None = None,
        force_target: str | None = None,
        always_show: bool = False,
    ) -> None:
        fields = _dedupe(raw_fields)
        if not fields and not always_show:
            return
        group_key, field_decision = _resolve_group(fields[0]) if fields else (input_group or "frailty_fitness", "")
        group_key = input_group or group_key
        meta = GROUP_META.get(group_key, {})
        agenda_match = next(
            (
                item
                for item in agenda_items
                if any(field in (item.get("required_inputs") or []) for field in fields)
            ),
            {},
        )
        capture_target = force_target or (
            "followup"
            if has_followup_flow or any(field in FOLLOWUP_PREFERRED_FIELDS for field in fields)
            else "intake"
        )
        tasks.append(
            {
                "key": key,
                "title": title or meta.get("title") or "Completar inputs críticos",
                "rationale": rationale or meta.get("rationale") or "Faltan datos estructurados para sostener una decisión clínica.",
                "module_owner": module_owner or meta.get("module_owner") or group_key,
                "decision_affected": decision_affected or meta.get("decision_affected") or field_decision,
                "input_group": group_key,
                "capture_target": capture_target,
                "preferred_entrypoint": capture_target,
                "agenda_id": agenda_match.get("id"),
                "raw_fields": fields,
                "form_scope": {"mode": "capture_block", "focus": group_key, "fields": fields},
                "action_label": "Completar en visita" if capture_target == "followup" else "Completar ingreso",
                "task_kind": "recapture" if always_show and not fields else "missing",
            }
        )

    fitness = (copilot or {}).get("therapeutic_fitness") or {}
    frailty = fitness.get("frailty") or {}
    charlson = ((copilot or {}).get("comorbidity_scores") or {}).get("charlson") or {}
    g8 = ((copilot or {}).get("comorbidity_scores") or {}).get("g8") or {}
    fit_score = (fitness.get("fit_score") or {})
    if not charlson.get("is_complete") or not g8.get("is_complete") or not frailty.get("is_complete") or not fit_score.get("is_complete"):
        add_task(
            key="frailty_fitness",
            raw_fields=(
                (charlson.get("missing_inputs") or [])
                + (g8.get("missing_inputs") or [])
                + (frailty.get("missing_inputs") or [])
                + (fit_score.get("missing_inputs") or [])
            ),
            input_group="frailty_fitness",
        )

    for panel_name, fields in (missing_inputs_by_panel or {}).items():
        if panel_name == "sequencing_context":
            add_task(key="sequencing_context", raw_fields=fields, input_group="advanced_sequencing")
        elif panel_name == "biomarker_context":
            add_task(key="biomarker_context", raw_fields=fields, input_group="biomarker_eligibility")
        elif panel_name == "safety_support_context":
            add_task(key="safety_support_context", raw_fields=fields, input_group="adt_safety")
        elif panel_name == "official_diagnosis":
            add_task(key="official_diagnosis", raw_fields=fields, input_group="official_diagnosis")

    for checkpoint in therapy_checkpoints or []:
        if checkpoint.get("status") != "needs_data":
            continue
        add_task(
            key=f"checkpoint_{checkpoint.get('key')}",
            raw_fields=checkpoint.get("inputs_required") or [],
            title=checkpoint.get("title"),
            rationale=checkpoint.get("why_it_matters_now"),
            decision_affected=checkpoint.get("decision_supported"),
        )

    if state in ADVANCED_STATES:
        add_task(
            key="line_refresh",
            raw_fields=[
                "line_of_therapy_number",
                "line_of_therapy_context",
                "drug_scheme",
                "current_adt_context",
                "castrate_testosterone_status",
                "psa",
                "testosterone",
            ],
            input_group="advanced_sequencing",
            title="Confirmar línea terapéutica y control biológico de esta visita",
            rationale="Debe recapturarse en cada visita avanzada para detectar cambios de línea y medir si mejoró el antígeno prostático específico con esa secuencia.",
            force_target="followup",
            always_show=True,
        )

    deduped_tasks: list[dict[str, Any]] = []
    seen = set()
    for task in tasks:
        marker = (task.get("title"), tuple(task.get("raw_fields") or []), task.get("capture_target"))
        if marker in seen:
            continue
        seen.add(marker)
        deduped_tasks.append(task)

    def build_block(target: str) -> dict[str, Any]:
        block_tasks = [task for task in deduped_tasks if task.get("capture_target") == target]
        block_fields = _dedupe([field for task in block_tasks for field in (task.get("raw_fields") or [])])
        return {
            "capture_target": target,
            "title": "Completar datos críticos del ingreso" if target == "intake" else "Completar datos críticos de la visita",
            "summary": "Solicita los inputs faltantes o variables dinámicas que deben reconfirmarse para sostener decisión clínica real.",
            "tasks": block_tasks,
            "fields": block_fields,
        } if block_tasks else {}

    return {
        "tasks": deduped_tasks[:8],
        "intake_capture_target": intake_capture_target,
        "followup_capture_target": followup_capture_target or "followup",
        "intake_completion_block": build_block("intake"),
        "followup_completion_block": build_block("followup"),
    }


def prepend_capture_block_to_visit_sections(
    sections: list[dict[str, Any]],
    capture_block: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not capture_block or not (capture_block.get("fields") or []):
        return sections

    requested_fields = set(capture_block.get("fields") or [])
    extracted_fields: list[dict[str, Any]] = []
    remaining_sections: list[dict[str, Any]] = []

    for section in sections:
        remaining_fields = []
        for field in section.get("fields", []):
            if field.get("name") in requested_fields:
                extracted_fields.append(field)
            else:
                remaining_fields.append(field)
        if remaining_fields:
            clone = dict(section)
            clone["fields"] = remaining_fields
            remaining_sections.append(clone)

    if not extracted_fields:
        return sections

    capture_section = {
        "id": f"capture_{capture_block.get('capture_target')}",
        "title": capture_block.get("title") or "Completar datos críticos",
        "description": capture_block.get("summary") or "",
        "fields": extracted_fields,
    }
    return [capture_section] + remaining_sections
