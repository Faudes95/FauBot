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
    options: list[str] = field(default_factory=list)
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
    window_start: str = ""
    window_end: str = ""
    status: str = "scheduled"
    priority: str = "routine"
    summary: str = ""
    required_inputs: list[str] = field(default_factory=list)
    completion_rule: dict[str, Any] = field(default_factory=dict)
    evidence_basis: list[str] = field(default_factory=list)
    comparator_basis: list[str] = field(default_factory=list)
    generated_from_event: str = ""
    action_label: str = ""
    blockers: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)

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
