from __future__ import annotations

from typing import Any

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.mcspc_high_volume.rules_eau import evaluate_mcspc_high_volume_eau
from prostanet.domains.mcspc_high_volume.rules_nccn import evaluate_mcspc_high_volume
from prostanet.domains.mcspc_high_volume.schemas import (
    MCSPC_HIGH_VOLUME_METACHRONOUS_SCHEMA,
    MCSPC_HIGH_VOLUME_SCHEMA,
    MCSPC_HIGH_VOLUME_SYNC_SCHEMA,
)
from prostanet.domains.patient_tracking.mhspc_evidence import (
    build_triplet_decision,
    build_visible_mhspc_trial_matches,
)
from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
    select_mhspc_frontline_regimens,
)
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.metastatic_profile import (
    build_metastatic_composition_summary,
    has_bone_metastatic_component,
)
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


SCHEMA_BY_MODULE = {
    "mcspc_high_volume": MCSPC_HIGH_VOLUME_SCHEMA,
    "mcspc_high_volume_sync": MCSPC_HIGH_VOLUME_SYNC_SCHEMA,
    "mcspc_high_volume_metachronous": MCSPC_HIGH_VOLUME_METACHRONOUS_SCHEMA,
}


class _BaseMcspcHighVolumeService:
    module_id = "mcspc_high_volume"
    default_temporality = "auto"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return SCHEMA_BY_MODULE[self.module_id]

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_mcspc_high_volume(payload, default_temporality=self.default_temporality)
        eau = evaluate_mcspc_high_volume_eau(payload, temporality=nccn["temporal_pattern"])
        comparison = self.comparison.compare(nccn, eau)
        normalized = dict(payload)
        normalized["comorbidities"] = {
            "seizure": str(payload.get("comorbidity_seizure", "0")) == "1",
            "cardio": str(payload.get("comorbidity_cardio", "0")) == "1",
        }
        legacy = evaluate_patient_for_mhspc(normalized)
        selector_bundle = select_mhspc_frontline_regimens(
            self.module_id,
            payload,
            docetaxel_bundle=nccn["docetaxel_fitness"],
        )
        treatments = self._build_treatments(payload, nccn, legacy, selector_bundle)
        triplet_decision = build_triplet_decision(
            self.module_id,
            payload,
            docetaxel_bundle=nccn["docetaxel_fitness"],
            selector_bundle=selector_bundle,
        )
        visible_trial_matches, hidden_trial_count = build_visible_mhspc_trial_matches(
            self.module_id,
            payload,
            triplet_decision=triplet_decision,
        )
        temporal_label = "sincrónica / de novo" if nccn["temporal_pattern"] == "sync" else "metacrónica"
        title_suffix = "sincrónico" if nccn["temporal_pattern"] == "sync" else "metacrónico"
        metastatic_summary = build_metastatic_composition_summary(payload)
        case_summary = (
            "El caso corresponde a enfermedad metastásica sensible a la castración de alto volumen "
            f"{temporal_label}. La Red Nacional Integral del Cáncer (NCCN) 5.2026 la clasifica como "
            f"{nccn['label']} y la Asociación Europea de Urología (EAU) 2026 la contrasta como {eau['label']}."
        )
        if metastatic_summary.get("available"):
            case_summary = f"{case_summary} {metastatic_summary.get('narrative')}"

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=treatments,
            not_recommended=[
                "Do not downplay treatment intensification in high-volume mCSPC.",
                "Avoid low-volume style local-only strategies in high-volume disease.",
                "Do not default to ADT monotherapy in a clinically fit metastatic patient.",
                "Do not assume PEACE-1 is the principal backbone in metachronous high-volume disease without de novo/synchronous context.",
            ],
            missing_critical_inputs=[
                field
                for field in ["molecular_assay_source", "molecular_assay_date"]
                if nccn["prefer_akeega"] and str(payload.get(field, "")).strip() == ""
            ] + list(selector_bundle.get("arpi_missing_inputs") or []) + list(selector_bundle.get("arpi_stale_inputs") or []) + (
                ["brca2_origin"]
                if (str(payload.get("brca2_status", "")) == "Positivo" or str(payload.get("hrr_gene", "")) == "BRCA2")
                and nccn.get("brca2_origin", "unknown") == "unknown"
                else []
            ) + list(nccn["docetaxel_fitness"].get("missing_inputs") or []),
            contraindications=legacy.get("contraindications", []) + list(nccn["docetaxel_fitness"]["docetaxel_hard_stop_reasons"]) + (
                ["Abiraterona contraindicada: Child-Pugh C (hepatopatía severa). Ficha técnica y NCCN 2026."]
                if nccn.get("abiraterone_hepatic_gate") == "contraindicated" else
                ["Abiraterona con precaución: Child-Pugh B — monitoreo ALT/AST cada 2 semanas obligatorio."]
                if nccn.get("abiraterone_hepatic_gate") == "caution" else []
            ),
            durations_and_conditions=[
                "If docetaxel is selected, plan 6 cycles Q3W (75 mg/m² IV cada 3 semanas). CBC basal y antes de cada ciclo. Reevaluar PSA tras ciclos 2, 4 y 6.",
                "Maintain ADT backbone and continue the selected ARPI until progression or intolerance.",
            ],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=visible_trial_matches,
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": (
                    f"High-volume metastatic hormone-sensitive pathway ({temporal_label}). "
                    f"{metastatic_summary.get('narrative')}".strip()
                    if metastatic_summary.get("available")
                    else f"High-volume metastatic hormone-sensitive pathway ({temporal_label})."
                ),
                "docetaxel_fitness": nccn["docetaxel_fitness"],
                "temporal_pattern": nccn["temporal_pattern"],
                "triplet_decision": triplet_decision,
                "frontline_regimen_rankings": selector_bundle["frontline_regimen_rankings"],
                "frontline_ranking_trace": selector_bundle.get("ranking_trace", {}),
                "bone_health_bundle": {
                    "dxa_baseline_done": str(payload.get("dxa_baseline_done", "0")) == "1",
                    "calcium_vitd_started": str(payload.get("calcium_vitd_started", "0")) == "1",
                    "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
                },
            },
        )
        result["docetaxel_fitness"] = nccn["docetaxel_fitness"]
        result["fit_for_docetaxel"] = nccn["fit_for_docetaxel"]
        result["docetaxel_base_eligibility"] = nccn.get("docetaxel_base_eligibility", "")
        result["docetaxel_default_intensification"] = nccn.get("docetaxel_default_intensification", "")
        result["docetaxel_trial_fit"] = nccn.get("docetaxel_trial_fit", {})
        result["docetaxel_hard_stop_reasons"] = nccn["docetaxel_fitness"]["docetaxel_hard_stop_reasons"]
        result["docetaxel_caution_reasons"] = nccn["docetaxel_fitness"]["docetaxel_caution_reasons"]
        result["docetaxel_fit_summary"] = nccn["docetaxel_fitness"]["docetaxel_fit_summary"]
        result["disease_temporality"] = nccn["temporal_pattern"]
        result["triplet_decision"] = triplet_decision
        result["triplet_decision_card"] = triplet_decision
        result["visible_trial_matches"] = visible_trial_matches
        result["hidden_cross_scenario_trial_count"] = hidden_trial_count
        result["preferred_frontline_regimen"] = selector_bundle["preferred_regimen"]
        result["frontline_regimen_rankings"] = selector_bundle["frontline_regimen_rankings"]
        result["frontline_regimen_rejections"] = selector_bundle["frontline_regimen_rejections"]
        result["frontline_ranking_trace"] = selector_bundle.get("ranking_trace", {})
        result["ranking_policy_version"] = selector_bundle.get("ranking_policy_version", "")
        result["pivotal_trial_fit"] = selector_bundle["pivotal_trial_fit"]
        result["drug_component_metadata"] = selector_bundle["drug_component_metadata"]
        result["patient_specific_modifiers"] = selector_bundle["patient_specific_modifiers"]
        result["eligibility_gates"] = selector_bundle["eligibility_gates"]
        result["arpi_required_fields"] = list(selector_bundle.get("arpi_required_fields") or [])
        result["arpi_missing_inputs"] = list(selector_bundle.get("arpi_missing_inputs") or [])
        result["arpi_stale_inputs"] = list(selector_bundle.get("arpi_stale_inputs") or [])
        result["arpi_profile_completeness"] = str(selector_bundle.get("arpi_profile_completeness") or "")
        result["arpi_preference_readiness"] = str(selector_bundle.get("arpi_preference_readiness") or "")
        result["arpi_selection_contract"] = dict(selector_bundle.get("arpi_selection_contract") or {})
        return enrich_evaluation_result(
            result,
            clinical_title=f"Ruta priorizada de enfermedad metastásica sensible a la castración de alto volumen {title_suffix}",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "El alto volumen obliga a priorizar intensificación sistémica y evita estrategias locales aisladas como vía principal.",
                f"Temporalidad reconocida: {'sincrónica / de novo' if nccn['temporal_pattern'] == 'sync' else 'metacrónica'}.",
                nccn["docetaxel_fitness"]["docetaxel_fit_summary"],
                "El backbone líder debe salir del balance entre trial-fit, comorbilidades, fragilidad y seguridad, no de una preferencia fija por un ARPI específico.",
            ],
            alternatives=[
                "Triplete con docetaxel si el estado funcional, la neuropatía, la fragilidad y la reserva orgánica lo permiten.",
                "Triplete con abiraterona o darolutamida según el subescenario y el perfil cardiometabólico, hepático y neurológico.",
                "Dobletes con enzalutamida, apalutamida o abiraterona cuando el perfil clínico sea compatible.",
            ],
            shared_decision_message=(
                "La selección final debe equilibrar urgencia oncológica, beneficio esperado de intensificación, neuropatía, fragilidad, reserva hepática y voluntad del paciente ante toxicidad hematológica."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 confirma la necesidad de intensificación en enfermedad de alto volumen y ayuda a no extrapolar de forma indiscriminada los backbones trial-like."
            ),
        )

    def _build_treatments(self, payload: dict, nccn: dict, legacy: dict, selector_bundle: dict[str, Any]) -> list[dict]:
        treatments: list[dict] = list(selector_bundle.get("eligible_treatments") or [])
        # Enriquecer tratamientos con docetaxel con especificación de ciclos (CHAARTED/STAMPEDE)
        for tx in treatments:
            if "docetaxel" in (tx.get("name") or "").lower():
                tx.setdefault("cycles", 6)
                tx.setdefault("cycle_interval_weeks", 3)
                tx.setdefault("dose_schema", "75 mg/m² IV Q3W")
        if nccn["prefer_akeega"]:
            treatments.append({"name": "ADT + Niraparib + Abiraterone", "priority": "preferred", "notes": "BRCA2-directed precision path in mCSPC with traceable molecular assay."})
        if has_bone_metastatic_component(payload):
            treatments.append({"name": "Calcio + vitamina D", "priority": "selected_candidate", "notes": "Bundle basal de salud ósea para toda enfermedad metastásica sensible a la castración."})
            if not nccn["bone_protection_started"]:
                treatments.append({"name": "Denosumab o ácido zoledrónico", "priority": "selected_candidate", "notes": "Considerar cuando la carga ósea y el riesgo estructural lo justifican tras evaluación clínica."})
        return treatments

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower():
                return item.get("evidence", "")
        return ""


class McspcHighVolumeService(_BaseMcspcHighVolumeService):
    module_id = "mcspc_high_volume"
    default_temporality = "auto"


class McspcHighVolumeSyncService(_BaseMcspcHighVolumeService):
    module_id = "mcspc_high_volume_sync"
    default_temporality = "sync"


class McspcHighVolumeMetachronousService(_BaseMcspcHighVolumeService):
    module_id = "mcspc_high_volume_metachronous"
    default_temporality = "metachronous"
