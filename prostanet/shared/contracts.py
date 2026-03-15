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
