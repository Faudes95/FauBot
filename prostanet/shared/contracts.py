from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    field_type: str
    required: bool = False
    help_text: str = ""
    options: list[Any] = field(default_factory=list)
    default: Any = None
    group: str = ""
    group_order: int = 0
    clinical_role: str = ""
    unit: str = ""
    conditional_visibility: dict[str, Any] = field(default_factory=dict)
    derived_from: list[str] = field(default_factory=list)
    evidence_tags: list[str] = field(default_factory=list)
    benchmark_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegistrationFragment:
    id: str
    title: str
    applies_to_states: list[str] = field(default_factory=list)
    fields: list[FieldSpec] = field(default_factory=list)
    persist_targets: list[str] = field(default_factory=list)
    clinical_influence: list[str] = field(default_factory=list)
    optional_research: bool = False
    benchmark_only: bool = False
    imported_fields: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fields"] = [field.to_dict() for field in self.fields]
        return data


@dataclass(frozen=True)
class DiagnosticPlanEvent:
    plan_type: str
    status: str = "planificado"
    summary: str = ""
    next_action: str = ""
    management_intent_status: str = "candidate"
    trigger_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MriFact:
    fact_date: str = ""
    quality: str = ""
    decision_usable: bool = False
    pirads_score: int | None = None
    lesion_location: str = ""
    lesion_size_mm: float | None = None
    prostate_volume_ml: float | None = None
    findings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BiopsyTriggerEvent:
    trigger_reason: str
    priority: str = "pendiente"
    planned_type: str = ""
    planned_route: str = ""
    status: str = "pendiente_de_confirmacion"
    management_intent_status: str = "candidate"
    activation_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceCitation:
    citation_id: str
    title: str
    guideline_or_trial: str
    source_tier: str
    document_id: str = ""
    evidence_role: str = ""
    license_class: str = ""
    doi_or_url: str = ""
    local_pdf_path: str = ""
    disease_state: str = ""
    line_of_therapy: str = ""
    biomarker_scope: str = ""
    symptom_scope: str = ""
    toxicity_scope: str = ""
    followup_implications: str = ""
    supports_rule_ids: list[str] = field(default_factory=list)
    applies_to_modules: list[str] = field(default_factory=list)
    derived_rule_ids: list[str] = field(default_factory=list)
    field_implications: list[str] = field(default_factory=list)
    ui_surfaces: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonitoringPlan:
    title: str
    cadence: str
    actions: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StateTransition:
    target_state: str
    label: str
    when: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CareOverlay:
    overlay_type: str
    title: str
    status: str
    reasons: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToxicityProfile:
    domain: str
    risks: list[str] = field(default_factory=list)
    monitoring: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromBattery:
    title: str
    instruments: list[str] = field(default_factory=list)
    cadence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgendaItem:
    agenda_key: str
    item_type: str
    title: str
    state: str
    management_track: str
    due_at: str = ""
    ideal_due_at: str = ""
    scheduled_due_at: str = ""
    window_start: str = ""
    window_end: str = ""
    delay_days: int = 0
    plan_key: str = ""
    completed_at: str = ""
    status: str = "scheduled"
    priority: str = "routine"
    summary: str = ""
    required_inputs: list[str] = field(default_factory=list)
    required: bool = True
    action_mode: str = "capture"
    completion_rule: dict[str, Any] = field(default_factory=dict)
    evidence_basis: list[str] = field(default_factory=list)
    comparator_basis: list[str] = field(default_factory=list)
    generated_from_event: str = ""
    action_label: str = ""
    blockers: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    decision_targets: list[str] = field(default_factory=list)
    panel_targets: list[str] = field(default_factory=list)
    write_targets: list[str] = field(default_factory=list)
    form_scope: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StageProtocolDefinition:
    state: str
    management_track: str
    title: str
    cadence_summary: str
    purpose: str
    evidence_basis: list[str] = field(default_factory=list)
    comparator_basis: list[str] = field(default_factory=list)
    agenda_defaults: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisitBundle:
    state: str
    management_track: str
    visit_type: str = "stage_followup"
    visit_date: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TherapyCheckpoint:
    key: str
    title: str
    status: str
    rationale: str
    action: str = ""
    evidence_basis: list[str] = field(default_factory=list)
    decision_supported: str = ""
    why_it_matters_now: str = ""
    inputs_required: list[str] = field(default_factory=list)
    blocking_if_missing: bool = False
    last_input_source: str = ""
    last_input_date: str = ""
    changes_recommendation_if_resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CopilotAlert:
    alert_key: str
    category: str
    decision_domain: str
    severity: str
    title: str
    message: str
    why_now: str = ""
    recommended_action: str = ""
    fields_to_capture: list[str] = field(default_factory=list)
    detail_items: list[dict[str, Any]] = field(default_factory=list)
    linked_agenda_ids: list[int] = field(default_factory=list)
    linked_agenda_keys: list[str] = field(default_factory=list)
    linked_encounter_keys: list[str] = field(default_factory=list)
    can_be_resolved_in_visit: bool = False
    creates_or_links_agenda_item: bool = False
    action_type: str = "capture"
    capture_block: str = ""
    encounter_key: str = ""
    resolves_decision_domain: str = ""
    expected_document_type: str = ""
    resolution_mode: str = ""
    focus_fields: list[str] = field(default_factory=list)
    primary_button_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EncounterTask:
    agenda_id: int | None
    agenda_key: str
    title: str
    item_type: str
    status: str
    due_at: str = ""
    ideal_due_at: str = ""
    scheduled_due_at: str = ""
    completed_at: str = ""
    delay_days: int = 0
    action_label: str = ""
    required: bool = True
    action_mode: str = "capture"
    expected_document_type: str = ""
    decision_targets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EncounterPlan:
    encounter_key: str
    encounter_type: str
    state: str
    management_track: str
    title: str
    summary: str
    due_at: str = ""
    ideal_due_at: str = ""
    scheduled_due_at: str = ""
    completed_at: str = ""
    delay_days: int = 0
    plan_key: str = ""
    status: str = "scheduled"
    priority: str = "routine"
    visit_modality: str = "clinic"
    task_count: int = 0
    required_task_count: int = 0
    completed_required_task_count: int = 0
    completion_progress: dict[str, Any] = field(default_factory=dict)
    tasks: list[EncounterTask] = field(default_factory=list)
    decision_domains: list[str] = field(default_factory=list)
    decision_domains_covered: list[str] = field(default_factory=list)
    guideline_basis: list[str] = field(default_factory=list)
    alerts_resolved_by_this_encounter: list[str] = field(default_factory=list)
    alert_count: int = 0
    anchor_strength: str = "strong"
    inline_actions_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tasks"] = [task.to_dict() for task in self.tasks]
        return data


@dataclass(frozen=True)
class ScheduleAnchorAssessment:
    anchor_date: str = ""
    anchor_source: str = ""
    strength: str = "strong"
    is_fallback: bool = False
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AlertActionPayload:
    action_type: str = "capture"
    capture_block: str = ""
    fields_to_capture: list[str] = field(default_factory=list)
    encounter_key: str = ""
    linked_agenda_keys: list[str] = field(default_factory=list)
    expected_document_type: str = ""
    resolves_decision_domain: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScenarioCadenceRule:
    scenario_state: str
    management_track: str
    phase_label: str
    guideline_basis: list[str] = field(default_factory=list)
    anchor_priority: list[str] = field(default_factory=list)
    cadence_rules: list[str] = field(default_factory=list)
    encounter_templates: list[str] = field(default_factory=list)
    required_tasks: list[str] = field(default_factory=list)
    escalation_rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MasterFollowupPlan:
    plan_version: str
    plan_key: str
    scenario_state: str
    management_track: str
    title: str
    phase_label: str = ""
    plan_status: str = "active"
    calendar_horizon_months: int = 12
    guideline_basis: list[str] = field(default_factory=list)
    comparator_basis: list[str] = field(default_factory=list)
    anchor: dict[str, Any] = field(default_factory=dict)
    scenario_rule: dict[str, Any] = field(default_factory=dict)
    next_encounter: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    encounter_timeline: list[dict[str, Any]] = field(default_factory=list)
    inline_actions_enabled: bool = False
    blocking_alerts: list[dict[str, Any]] = field(default_factory=list)
    overdue_items: list[dict[str, Any]] = field(default_factory=list)
    due_items: list[dict[str, Any]] = field(default_factory=list)
    optional_items: list[dict[str, Any]] = field(default_factory=list)
    highlight_actions: list[str] = field(default_factory=list)
    gaps_to_close: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClinicalFact:
    fact_key: str
    category: str
    value: Any = None
    fact_date: str = ""
    source_type: str = ""
    source_priority: str = ""
    verified: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutcomeEvent:
    event_key: str
    event_type: str
    scenario_state: str
    management_track: str
    axis: str = ""
    adjudication_status: str = "confirmed"
    event_date: str = ""
    source_priority: str = ""
    decision_impact: str = ""
    summary: str = ""
    provisional: bool = False
    blocking_fields: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdjudicationStatus:
    status_key: str
    title: str
    rationale: str
    status: str = "pending"
    severity: str = "warning"
    provisional: bool = True
    decision_domain: str = ""
    capture_block: str = ""
    action_type: str = "capture"
    expected_document_type: str = ""
    linked_outcome_event: str = ""
    linked_encounter_key: str = ""
    linked_agenda_keys: list[str] = field(default_factory=list)
    fields_to_capture: list[str] = field(default_factory=list)
    recommended_action: str = ""
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrialComparableEndpoint:
    endpoint_key: str
    label: str
    status: str
    value: Any = None
    scenario_state: str = ""
    trial_family: str = ""
    comparable: bool = False
    provisional: bool = False
    details: str = ""
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkSnapshot:
    benchmark_family: str
    scenario_state: str
    management_track: str
    eligibility_status: str
    matched_trials: list[str] = field(default_factory=list)
    endpoint_snapshot: dict[str, Any] = field(default_factory=dict)
    cohort_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstitutionalComparator:
    label: str
    mode: str
    title: str
    cadence_summary: str
    source_label: str = ""
    source_url: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataFreshnessFact:
    label: str
    value: str
    date: str
    freshness_status: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProvenanceFact:
    field_name: str
    source_type: str
    source_date: str = ""
    source_document_id: str = ""
    verified_by: str = ""
    entered_manually: bool = False
    stage_context: str = ""
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PatientEvent:
    patient_id: int
    event_type: str
    event_date: str
    state_context: str = ""
    management_track: str = ""
    source_type: str = ""
    source_record_id: int | None = None
    status: str = "recorded"
    payload: dict[str, Any] = field(default_factory=dict)
    mcode_focus: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClinicalSignalSet:
    state: str
    management_track: str
    ready_to_restage: bool = False
    signals: list[dict[str, Any]] = field(default_factory=list)
    critical_missing: list[str] = field(default_factory=list)
    awaiting_review: list[str] = field(default_factory=list)
    active_safety: list[str] = field(default_factory=list)
    mcode_projection: dict[str, Any] = field(default_factory=dict)
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StateTransitionProposal:
    proposal_key: str
    from_state: str
    target_state: str
    rationale: str
    from_management_track: str = ""
    target_management_track: str = ""
    priority: str = "routine"
    proposal_status: str = "open"
    requires_confirmation: bool = True
    trigger_signals: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NextBestAction:
    title: str
    recommendation_family: str
    rationale: str
    immediate_actions: list[str] = field(default_factory=list)
    data_that_could_change_course: list[str] = field(default_factory=list)
    contraindication_modifiers: list[str] = field(default_factory=list)
    evidence_basis: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationAudit:
    patient_id: int
    recommendation_family: str
    recommended_option: str
    selected_option: str = ""
    discordance_reason: str = ""
    assessment_id: int | None = None
    event_id: int | None = None
    outcome_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceDocument:
    patient_id: int
    document_key: str
    document_type: str
    title: str = ""
    file_name: str = ""
    mime_type: str = ""
    sha256: str = ""
    storage_path: str = ""
    private_index_path: str = ""
    source_date: str = ""
    classification_status: str = "pending"
    extraction_status: str = "pending"
    verification_status: str = "draft"
    preview_excerpt: str = ""
    page_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentExtractionCandidate:
    candidate_key: str
    field_name: str
    fact_group: str
    value: Any
    value_display: str = ""
    target_result_type: str = ""
    confidence: float = 0.0
    status: str = "draft"
    extraction_method: str = ""
    evidence_excerpt: str = ""
    page_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationTask:
    task_key: str
    task_status: str = "open"
    assigned_to: str = ""
    verified_by: str = ""
    verified_at: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    pending_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerifiedFact:
    field_name: str
    fact_group: str
    value: Any
    value_display: str = ""
    target_result_type: str = ""
    source_date: str = ""
    status: str = "verified"
    correction_note: str = ""
    verified_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerifiedFactBundle:
    verified_by: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    committed_result_types: list[str] = field(default_factory=list)
    what_changed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def module_schema(
    module_id: str,
    title: str,
    description: str,
    fields: list[FieldSpec],
) -> dict[str, Any]:
    return {
        "module": module_id,
        "title": title,
        "description": description,
        "fields": [field.to_dict() for field in fields],
    }


def evaluation_result(
    *,
    state: str,
    nccn_primary: dict[str, Any],
    eau_comparison: dict[str, Any],
    eligible_treatments: list[dict[str, Any]] | list[str],
    not_recommended: list[str],
    missing_critical_inputs: list[str],
    contraindications: list[str],
    durations_and_conditions: list[str],
    evidence_trace: list[dict[str, Any]],
    trial_matches: list[dict[str, Any]],
    applicability_badge: str,
    report_sections: dict[str, Any],
    decision_changing_inputs: list[str] | None = None,
    supportive_evidence_context: list[str] | None = None,
    benchmarking_flags: list[dict[str, Any]] | None = None,
    validated_algorithms: list[dict[str, Any]] | None = None,
    decision_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "nccn_primary": nccn_primary,
        "eau_comparison": eau_comparison,
        "eligible_treatments": eligible_treatments,
        "not_recommended": not_recommended,
        "missing_critical_inputs": missing_critical_inputs,
        "contraindications": contraindications,
        "durations_and_conditions": durations_and_conditions,
        "evidence_trace": evidence_trace,
        "trial_matches": trial_matches,
        "applicability_badge": applicability_badge,
        "report_sections": report_sections,
        "decision_changing_inputs": decision_changing_inputs or [],
        "supportive_evidence_context": supportive_evidence_context or [],
        "benchmarking_flags": benchmarking_flags or [],
        "validated_algorithms": validated_algorithms or [],
        "decision_quality": decision_quality or {},
    }
