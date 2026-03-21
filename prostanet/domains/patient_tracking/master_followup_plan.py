from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from prostanet.shared.contracts import (
    MasterFollowupPlan,
    ScenarioCadenceRule,
    ScheduleAnchorAssessment,
)


PLAN_VERSION = "2026.1"
DEFAULT_CALENDAR_HORIZON_MONTHS = 12


SCENARIO_FOLLOWUP_MATRIX: dict[str, dict[str, Any]] = {
    "diagnostic_workup": {
        "phase_label": "Fase 2",
        "guideline_basis": ["NCCN 2026 diagnóstico", "EAU 2026 diagnóstico"],
        "anchor_priority": ["stage_visit_records.visit_date", "source_documents.source_date", "latest_assessment.created_at"],
        "cadence_rules": ["PSA seriado mientras se completa MRI/biopsia.", "Escalar a biopsia dirigida + sistemática si persiste señal de riesgo."],
        "encounter_templates": ["diagnostic_followup", "diagnostic_workup", "documentation"],
        "required_tasks": ["psa", "mri", "biopsy"],
        "escalation_rules": ["MRI o biopsia vencidas elevan seguimiento diagnóstico prioritario."],
    },
    "post_negative_biopsy_followup": {
        "phase_label": "Fase 2",
        "guideline_basis": ["EAU 2026 repeat biopsy", "NCCN 2026 early detection"],
        "anchor_priority": ["biopsy_details.biopsy_date", "stage_visit_records.visit_date", "latest_assessment.created_at"],
        "cadence_rules": ["PSA/PSAD seriado y mpMRI de control.", "Rebiopsia si persisten triggers anatómicos o bioquímicos."],
        "encounter_templates": ["diagnostic_followup", "diagnostic_workup"],
        "required_tasks": ["psa", "mri", "biopsy"],
        "escalation_rules": ["Persistencia de señal pese a biopsia benigna reabre estudio diagnóstico."],
    },
    "localized_initial": {
        "phase_label": "Fase 2",
        "guideline_basis": ["NCCN 2026 localized disease", "EAU 2026 localized disease"],
        "anchor_priority": ["stage_visit_records.visit_date", "source_documents.source_date", "latest_assessment.created_at"],
        "cadence_rules": ["Alinear riesgo, histología y preferencias antes de definir manejo local.", "Si vigilancia activa es elegible, protocolizar PSA, MRI y biopsia confirmatoria."],
        "encounter_templates": ["localized_decision", "surveillance_visit", "surveillance_restage"],
        "required_tasks": ["psa", "pro_assessment", "therapy_review"],
        "escalation_rules": ["Riesgo desfavorable o histología adversa desplazan vigilancia activa."],
    },
    "post_prostatectomy": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 post-prostatectomy", "EAU 2026 salvage window"],
        "anchor_priority": ["surgical_details.surgery_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["PSA ultrasensible estrecho durante los primeros 24 meses.", "Vigilar continencia, función sexual y ventana curativa de rescate."],
        "encounter_templates": ["postlocal_followup", "salvage_restage", "documentation"],
        "required_tasks": ["psa", "pro_assessment", "imaging"],
        "escalation_rules": ["Ascenso bioquímico o margen/estadio adverso aceleran reestadificación y rescate."],
    },
    "recurrence_bcr": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 BCR", "EAU 2026 salvage"],
        "anchor_priority": ["biochemical_recurrence.bcr_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["PSA ultrasensible y PSADT sostienen la ventana de rescate.", "Imagen dirigida cuando cambia factibilidad de salvamento o intensificación."],
        "encounter_templates": ["postlocal_followup", "salvage_restage", "documentation"],
        "required_tasks": ["psa", "imaging", "therapy_review"],
        "escalation_rules": ["PSADT rápido o imagen positiva elevan prioridad del salvamento."],
    },
    "adt_progression_verification": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 CRPC workup", "EAU 2026 progression under ADT"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date", "latest_assessment.created_at"],
        "cadence_rules": ["Carril corto de confirmación bajo ADT.", "Verificar testosterona, backbone ADT, línea terapéutica, PSA/labs y reestadificación antes de llamar CRPC."],
        "encounter_templates": ["progression_confirmation", "progression_support", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "imaging", "supportive_care"],
        "escalation_rules": ["Si testosterona no está en castración, no escalar a CRPC.", "Anchor fallback debe generar alerta de fortalecimiento del protocolo."],
    },
    "mcspc_oligo_metachronous": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC", "EAU 2026 mHSPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Seguimiento sistémico con labs, PSA, seguridad y reestadificación.", "Mantener revisión de línea terapéutica y backbone ADT en cada visita."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Cambio de carga tumoral o progresión oligometastásica reabre reestadificación."],
    },
    "mcspc_low_volume_sync_oligo": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC", "EAU 2026 mHSPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["PSA/labs trimestrales y reestadificación protocolizada.", "Monitorear seguridad, soporte óseo y tolerabilidad de intensificación."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Cualquier cambio de línea o progresión radiográfica acelera encounter clínico."],
    },
    "mcspc_high_volume_sync": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC high-volume", "EAU 2026 mHSPC", "ARASENS", "PEACE-1", "ARANOTE"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Seguimiento sistémico intensivo con laboratorios, imagen y bundles de seguridad.", "Monitorizar respuesta biológica, aptitud a docetaxel y tolerancia por línea terapéutica en enfermedad sincrónica / de novo."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Síntomas o carga tumoral creciente adelantan reestadificación.", "Si docetaxel deja de ser apropiado, reabrir selección de doblete visible con darolutamida."],
    },
    "mcspc_high_volume_metachronous": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC high-volume", "EAU 2026 mHSPC", "ARASENS", "ARANOTE"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Seguimiento sistémico intensivo con laboratorios, imagen y bundles de seguridad.", "Monitorizar respuesta biológica y tolerancia por línea evitando sobreextrapolar PEACE-1 como backbone metacrónico principal."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Síntomas o carga tumoral creciente adelantan reestadificación.", "Si docetaxel deja de ser apropiado, reabrir selección de doblete visible con darolutamida."],
    },
    "mcspc_high_volume": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mHSPC high-volume", "EAU 2026 mHSPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Seguimiento sistémico intensivo con laboratorios, imagen y bundles de seguridad.", "Monitorizar respuesta biológica y tolerancia por línea terapéutica."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Síntomas o carga tumoral creciente adelantan reestadificación."],
    },
    "m0_crpc": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 nmCRPC", "EAU 2026 CRPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["PSA/labs seriados y verificación de castración sostenida.", "Reestadificar si cinética o clínica sugieren transición metastásica."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care"],
        "escalation_rules": ["PSADT acelerado o nueva imagen positiva escalan a revisión inmediata."],
    },
    "m1_crpc": {
        "phase_label": "Fase 1",
        "guideline_basis": ["NCCN 2026 mCRPC", "EAU 2026 mCRPC"],
        "anchor_priority": ["treatment_history.start_date", "stage_visit_records.visit_date", "source_documents.source_date"],
        "cadence_rules": ["Visita sistémica con labs, seguridad, reestadificación y revisión terapéutica.", "Biomarcadores y PSMA deben mantenerse actualizados por línea activa."],
        "encounter_templates": ["systemic_followup", "restaging", "documentation"],
        "required_tasks": ["therapy_review", "lab_panel", "supportive_care", "imaging"],
        "escalation_rules": ["Biomarcador o PSMA faltante bloquean decisiones de precisión."],
    },
}


def _unique_preserving(values: list[Any]) -> list[Any]:
    ordered: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, "", [], {}):
            continue
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(value)
    return ordered


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _timeline_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("ideal_due_at") or item.get("due_at") or ""),
        str(item.get("scheduled_due_at") or item.get("due_at") or ""),
        str(item.get("title") or ""),
    )


def _within_horizon(item: dict[str, Any], anchor_dt: date, horizon_months: int) -> bool:
    reference = _parse_iso_date(item.get("scheduled_due_at") or item.get("ideal_due_at") or item.get("due_at"))
    if reference is None:
        return True
    horizon_days = max(horizon_months, 1) * 31
    return reference <= (anchor_dt + timedelta(days=horizon_days))


def _scenario_rule(state: str, management_track: str) -> dict[str, Any]:
    raw = SCENARIO_FOLLOWUP_MATRIX.get(state) or {
        "phase_label": "Fase 2",
        "guideline_basis": ["NCCN 2026", "EAU 2026"],
        "anchor_priority": ["stage_visit_records.visit_date", "source_documents.source_date", "latest_assessment.created_at"],
        "cadence_rules": ["Mantener seguimiento reconciliado por estado y track."],
        "encounter_templates": ["systemic_followup"],
        "required_tasks": [],
        "escalation_rules": [],
    }
    return ScenarioCadenceRule(
        scenario_state=state,
        management_track=management_track,
        phase_label=str(raw.get("phase_label") or "Fase 2"),
        guideline_basis=list(raw.get("guideline_basis") or []),
        anchor_priority=list(raw.get("anchor_priority") or []),
        cadence_rules=list(raw.get("cadence_rules") or []),
        encounter_templates=list(raw.get("encounter_templates") or []),
        required_tasks=list(raw.get("required_tasks") or []),
        escalation_rules=list(raw.get("escalation_rules") or []),
    ).to_dict()


def _summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "agenda_key": item.get("agenda_key", ""),
        "title": item.get("title", ""),
        "status": item.get("status", ""),
        "due_at": item.get("due_at", ""),
        "item_type": item.get("item_type", ""),
        "summary": item.get("summary", ""),
        "required_inputs": list(item.get("required_inputs") or []),
    }


def _summarize_alert(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_key": alert.get("alert_key", ""),
        "title": alert.get("title", ""),
        "severity": alert.get("severity", ""),
        "category": alert.get("category", ""),
        "decision_domain": alert.get("decision_domain", ""),
        "recommended_action": alert.get("recommended_action", ""),
        "action_type": alert.get("action_type", ""),
        "fields_to_capture": list(alert.get("fields_to_capture") or []),
    }


def link_alerts_to_encounters(encounters: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts_by_encounter: dict[str, list[dict[str, Any]]] = {}
    for alert in alerts or []:
        for encounter_key in alert.get("linked_encounter_keys") or []:
            if encounter_key:
                alerts_by_encounter.setdefault(str(encounter_key), []).append(alert)

    enriched: list[dict[str, Any]] = []
    for encounter in encounters or []:
        current = dict(encounter)
        linked = alerts_by_encounter.get(str(current.get("encounter_key") or ""), [])
        current["alerts_resolved_by_this_encounter"] = _unique_preserving(
            [str(alert.get("title") or "") for alert in linked if str(alert.get("title") or "")]
        )
        current["alert_count"] = len(linked)
        current["guideline_basis"] = _unique_preserving(list(current.get("guideline_basis") or []))
        current["decision_domains_covered"] = _unique_preserving(
            list(current.get("decision_domains_covered") or current.get("decision_domains") or [])
        )
        enriched.append(current)
    return enriched


def build_master_followup_plan(
    patient: dict[str, Any],
    state: str,
    management_track: str,
    agenda_board: dict[str, Any],
    signals: dict[str, Any] | None = None,
    copilot_alerts: list[dict[str, Any]] | None = None,
    next_best_action: dict[str, Any] | None = None,
    plan_key: str = "",
    calendar_horizon_months: int = DEFAULT_CALENDAR_HORIZON_MONTHS,
) -> dict[str, Any]:
    signals = signals or {}
    copilot_alerts = [dict(alert) for alert in (copilot_alerts or []) if isinstance(alert, dict)]
    protocol = dict(agenda_board.get("stage_protocol") or {})
    protocol_trace = dict(agenda_board.get("protocol_trace") or {})
    comparators = list(agenda_board.get("protocol_comparators") or [])
    active_items = [dict(item) for item in (agenda_board.get("active_items") or agenda_board.get("items") or [])]
    overdue_items = [_summarize_item(item) for item in active_items if str(item.get("status") or "") == "overdue"]
    due_items = [_summarize_item(item) for item in active_items if str(item.get("status") or "") in {"due", "due_today"}]
    optional_items = [_summarize_item(item) for item in active_items if str(item.get("status") or "") in {"scheduled", "blocked"}]
    rule = _scenario_rule(state, management_track)

    blocking_alerts = [
        _summarize_alert(alert)
        for alert in copilot_alerts
        if str(alert.get("category") or "") in {"decision_blocker", "safety", "protocol_due"}
    ][:6]
    guideline_basis = _unique_preserving(
        list(rule.get("guideline_basis") or [])
        + list(protocol.get("evidence_basis") or [])
    )
    comparator_basis = _unique_preserving(
        [str(item.get("title") or item.get("label") or "") for item in comparators if str(item.get("title") or item.get("label") or "")]
    )
    prognostic_modifiers = [dict(item) for item in list(signals.get("prognostic_modifiers") or []) if isinstance(item, dict)]
    backbone_alignment = dict(signals.get("backbone_alignment") or {})
    cadence_adjusted_by = [str(item) for item in list(signals.get("cadence_adjusted_by") or []) if str(item or "").strip()]
    prognostic_rationale = [
        {
            "title": str(item.get("title") or item.get("modifier_key") or "Impacto pronóstico"),
            "severity": str(item.get("severity") or "info"),
            "why_it_matters_now": str(item.get("why_it_matters_now") or ""),
            "followup_impact": list(item.get("followup_impact") or []),
            "recommended_actions": list(item.get("recommended_actions") or []),
        }
        for item in prognostic_modifiers[:4]
    ]
    anchor = ScheduleAnchorAssessment(
        anchor_date=str(protocol_trace.get("anchor_date") or ""),
        anchor_source=str(protocol_trace.get("anchor_source") or ""),
        strength="weak" if protocol_trace.get("anchor_is_fallback") else "strong",
        is_fallback=bool(protocol_trace.get("anchor_is_fallback")),
        rationale="Anclaje derivado del mejor origen longitudinal disponible.",
    ).to_dict()
    anchor_dt = _parse_iso_date(anchor.get("anchor_date")) or date.today()
    resolved_plan_key = plan_key or f"{state}:{management_track}:{anchor.get('anchor_date') or anchor_dt.isoformat()}"
    linked_encounters = []
    for encounter in link_alerts_to_encounters(list(agenda_board.get("encounters") or []), copilot_alerts):
        current = dict(encounter)
        current["plan_key"] = str(current.get("plan_key") or resolved_plan_key)
        current["ideal_due_at"] = str(current.get("ideal_due_at") or current.get("due_at") or "")
        current["scheduled_due_at"] = str(current.get("scheduled_due_at") or current.get("due_at") or "")
        current["delay_days"] = int(current.get("delay_days") or 0)
        linked_encounters.append(current)
    linked_encounters.sort(key=_timeline_sort_key)
    timeline = [encounter for encounter in linked_encounters if _within_horizon(encounter, anchor_dt, calendar_horizon_months)]
    actionable_timeline = [
        encounter
        for encounter in timeline
        if str(encounter.get("status") or "scheduled") not in {"completed", "cancelled", "superseded"}
    ]
    next_encounter = dict(
        next(
            (encounter for encounter in actionable_timeline if str(encounter.get("visit_modality") or "") != "async"),
            actionable_timeline[0] if actionable_timeline else {},
        )
    )
    highlight_actions = _unique_preserving(
        list((next_best_action or {}).get("immediate_actions") or [])
        + [str(action) for item in prognostic_modifiers for action in list(item.get("recommended_actions") or [])]
        + [str(alert.get("recommended_action") or "") for alert in blocking_alerts]
        + [str(item.get("recommended_action") or item.get("title") or "") for item in list(signals.get("pending_adjudications") or [])]
        + [str(task.get("title") or "") for task in list((next_encounter or {}).get("tasks") or [])[:3]]
    )[:8]
    gaps_to_close = _unique_preserving(
        list(signals.get("critical_missing") or [])
        + [
            f"{item.get('title')}: {', '.join(item.get('fields', []) or item.get('raw_fields', []) or [])}"
            for item in list(signals.get("prognostic_capture_targets") or [])
            if list(item.get("fields") or item.get("raw_fields") or [])
        ]
        + [str(item.get("title") or "") for item in list(signals.get("pending_adjudications") or [])]
        + [
            f"{alert.get('title')}: {', '.join(alert.get('fields_to_capture') or [])}"
            for alert in blocking_alerts
            if alert.get("fields_to_capture")
        ]
    )[:8]
    summary = {
        "headline": str(protocol.get("title") or "Plan maestro de seguimiento"),
        "cadence_summary": str(protocol.get("cadence_summary") or ""),
        "overdue_count": len(overdue_items),
        "due_now_count": len(due_items),
        "optional_count": len(optional_items),
        "blocking_alert_count": len(blocking_alerts),
        "pending_adjudication_count": len(list(signals.get("pending_adjudications") or [])),
        "next_encounter_title": str(next_encounter.get("title") or "Sin encounter priorizado"),
        "next_encounter_due_at": str(next_encounter.get("due_at") or ""),
        "anchor_strength": anchor.get("strength", "strong"),
        "timeline_count": len(timeline),
        "plan_status": "provisional" if anchor.get("is_fallback") else "active",
        "current_course_status": str(signals.get("current_course_status") or ""),
        "last_adjudicated_event": str((signals.get("last_adjudicated_event") or {}).get("summary") or ""),
        "prognostic_modifier_count": len(prognostic_modifiers),
        "cadence_adjusted_count": len(cadence_adjusted_by),
    }
    return MasterFollowupPlan(
        plan_version=PLAN_VERSION,
        plan_key=resolved_plan_key,
        scenario_state=state,
        management_track=management_track,
        title=str(protocol.get("title") or "Plan maestro de seguimiento protocolizado"),
        phase_label=str(rule.get("phase_label") or ""),
        plan_status="provisional" if anchor.get("is_fallback") else "active",
        calendar_horizon_months=calendar_horizon_months,
        guideline_basis=guideline_basis,
        comparator_basis=comparator_basis,
        anchor=anchor,
        scenario_rule=rule,
        next_encounter=next_encounter,
        timeline=timeline,
        encounter_timeline=timeline,
        blocking_alerts=blocking_alerts,
        overdue_items=overdue_items[:6],
        due_items=due_items[:6],
        optional_items=optional_items[:6],
        highlight_actions=highlight_actions,
        gaps_to_close=gaps_to_close,
        prognostic_rationale=prognostic_rationale,
        cadence_adjusted_by=cadence_adjusted_by,
        backbone_alignment=backbone_alignment,
        summary=summary,
        inline_actions_enabled=any(bool(encounter.get("inline_actions_enabled")) for encounter in timeline),
    ).to_dict()
