from __future__ import annotations

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.mcspc_low_volume_sync_oligo.rules_eau import evaluate_mcspc_low_volume_eau
from prostanet.domains.mcspc_low_volume_sync_oligo.rules_nccn import evaluate_mcspc_low_volume
from prostanet.domains.mcspc_low_volume_sync_oligo.schemas import MCSPC_LOW_VOLUME_SCHEMA
from prostanet.domains.patient_tracking.mhspc_evidence import (
    build_triplet_decision,
    build_visible_mhspc_trial_matches,
)
from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
    select_mhspc_frontline_regimens,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
)
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.metastatic_profile import (
    build_metastatic_composition_summary,
    has_bone_metastatic_component,
)
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result
from copy import deepcopy


class McspcLowVolumeSyncOligoService:
    module_id = "mcspc_low_volume_sync_oligo"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return MCSPC_LOW_VOLUME_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_mcspc_low_volume(payload)
        eau = evaluate_mcspc_low_volume_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        normalized = dict(payload)
        normalized["comorbidities"] = {
            "seizure": str(payload.get("comorbidity_seizure", "0")) == "1",
            "cardio": str(payload.get("comorbidity_cardio", "0")) == "1",
        }
        legacy = evaluate_patient_for_mhspc(normalized)
        selector_bundle = select_mhspc_frontline_regimens(self.module_id, payload)
        triplet_decision = build_triplet_decision(self.module_id, payload, selector_bundle=selector_bundle)
        visible_trial_matches, hidden_trial_count = build_visible_mhspc_trial_matches(
            self.module_id,
            payload,
            triplet_decision=triplet_decision,
        )
        family_profiles = deepcopy(selector_bundle.get("comparative_eligibility_matrix") or {})
        if nccn["rt_primary_candidate"]:
            local_options = list(((family_profiles.get("local_mdt_family") or {}).get("variant_ranking") or {}).get("eligible_regimens_ranked") or [])
            local_options.append(
                build_ranked_option(
                    name="RT al primario",
                    regimen_code="RT_TO_PRIMARY",
                    rank=len(local_options) + 1,
                    priority="eligible",
                    eligibility_status="eligible_nonpreferred",
                    family_code="local_mdt_family",
                    molecule_or_backbone="Radioterapia al primario",
                    description="Control local del tumor primario en mHSPC de bajo volumen sincrónico.",
                    route="Radioterapia externa",
                    schedule="Integrada con ADT/doblete",
                    metadata_source="guideline_backbone",
                    notes=self._note_for(legacy, "Radioterapia al Primario"),
                    why_this_rank=["El control local del primario añade valor en bajo volumen, pero no sustituye la intensificación sistémica dominante."],
                )
            )
            family_profiles["local_mdt_family"] = build_family_profile(
                family_code="local_mdt_family",
                ordered_regimens=local_options,
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": "El control local del primario compite formalmente en bajo volumen, pero suele quedar detrás del doblete sistémico preferente.",
                },
            )
        if nccn["prefer_akeega"]:
            parp_options = list(((family_profiles.get("parp_family") or {}).get("variant_ranking") or {}).get("eligible_regimens_ranked") or [])
            parp_options.append(
                build_ranked_option(
                    name="ADT + Niraparib + Abiraterone",
                    regimen_code="NIRAPARIB_ABIRATERONE",
                    rank=len(parp_options) + 1,
                    priority="eligible",
                    eligibility_status="eligible_with_caution",
                    family_code="parp_family",
                    molecule_or_backbone="Niraparib + abiraterona",
                    notes="Ruta de precisión para BRCA2 trazable en mCSPC.",
                    why_this_rank=["La vía de precisión BRCA2 sigue visible, pero no debe ocultar el backbone sistémico dominante del escenario."],
                )
            )
            family_profiles["parp_family"] = build_family_profile(
                family_code="parp_family",
                ordered_regimens=parp_options,
                context={
                    "eligibility_status": "conditional",
                    "missing_inputs": [
                        field
                        for field in ["molecular_assay_source", "molecular_assay_date"]
                        if str(payload.get(field, "")).strip() == ""
                    ],
                    "winner_reason": "La precisión BRCA2 queda visible como overlay, no como reemplazo automático del doblete basal.",
                },
            )
        family_order = ["arpi_family", "abiraterone_steroid_family", "local_mdt_family", "parp_family", "observation_family"]
        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or selector_bundle.get("preferred_frontline_regimen") or {})
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=[
                field
                for field in ["molecular_assay_source", "molecular_assay_date"]
                if nccn["prefer_akeega"] and str(payload.get(field, "")).strip() == ""
            ] + list(selector_bundle.get("arpi_missing_inputs") or []) + list(selector_bundle.get("arpi_stale_inputs") or []),
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="mHSPC_initial",
            field_values=payload,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "arpi_family",
            field_values=payload,
        )
        metastatic_summary = build_metastatic_composition_summary(payload)
        case_summary = (
            "El caso corresponde a enfermedad metastásica sensible a la castración de bajo volumen u oligometastásica sincrónica. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 la describe como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 la compara con {eau['label']}."
        )
        if metastatic_summary.get("available"):
            case_summary = f"{case_summary} {metastatic_summary.get('narrative')}"

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=comparative_bundle.get("eligible_treatments") or selector_bundle.get("eligible_treatments") or [],
            not_recommended=["Do not position docetaxel monotherapy as a default for low-volume disease.", "Avoid presenting low-volume disease as equivalent to high-volume triplet-first disease."],
            missing_critical_inputs=[
                field
                for field in ["molecular_assay_source", "molecular_assay_date"]
                if nccn["prefer_akeega"] and str(payload.get(field, "")).strip() == ""
            ],
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=[
                "Keep ADT backbone continuous with the selected ARPI.",
                "If RT to the primary is selected, integrate it with systemic therapy timing.",
                "Mantener calcio y vitamina D como soporte basal de salud ósea." if has_bone_metastatic_component(payload) else "",
                "Considerar denosumab o ácido zoledrónico si la carga ósea y el riesgo estructural lo justifican." if has_bone_metastatic_component(payload) and not nccn["bone_protection_started"] else "",
            ],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=visible_trial_matches,
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": (
                    f"Low-volume metastatic hormone-sensitive pathway. {metastatic_summary.get('narrative')}".strip()
                    if metastatic_summary.get("available")
                    else "Low-volume metastatic hormone-sensitive pathway."
                ),
                "triplet_decision": triplet_decision,
                "frontline_regimen_rankings": selector_bundle["frontline_regimen_rankings"],
                "frontline_ranking_trace": selector_bundle.get("ranking_trace", {}),
            },
        )
        result["triplet_decision"] = triplet_decision
        result["triplet_decision_card"] = triplet_decision
        result["visible_trial_matches"] = visible_trial_matches
        result["hidden_cross_scenario_trial_count"] = hidden_trial_count
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or selector_bundle.get("alternative_regimens") or []
        result["frontline_regimen_rankings"] = selector_bundle["frontline_regimen_rankings"]
        result["frontline_regimen_rejections"] = selector_bundle["frontline_regimen_rejections"]
        result["frontline_ranking_trace"] = selector_bundle.get("ranking_trace", {})
        result["ranking_policy_version"] = selector_bundle.get("ranking_policy_version", "")
        result["pivotal_trial_fit"] = selector_bundle["pivotal_trial_fit"]
        result["drug_component_metadata"] = selector_bundle["drug_component_metadata"]
        result["patient_specific_modifiers"] = selector_bundle["patient_specific_modifiers"]
        result["eligibility_gates"] = selector_bundle["eligibility_gates"]
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or family_profiles
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or family_profiles
        result["care_setting_contract"] = {
            "care_setting": "systemic_intensification",
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["decision_quality"] = {
            "recommendation_family": preferred_regimen.get("family_label") or "ARPI",
            "confidence_category": "vigilada" if result.get("missing_critical_inputs") else "alta",
            "requires_human_review": bool(result.get("missing_critical_inputs")),
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        result["arpi_required_fields"] = list(selector_bundle.get("arpi_required_fields") or [])
        result["arpi_missing_inputs"] = list(selector_bundle.get("arpi_missing_inputs") or [])
        result["arpi_stale_inputs"] = list(selector_bundle.get("arpi_stale_inputs") or [])
        result["arpi_profile_completeness"] = str(selector_bundle.get("arpi_profile_completeness") or "")
        result["arpi_preference_readiness"] = str(selector_bundle.get("arpi_preference_readiness") or "")
        result["arpi_selection_contract"] = dict(selector_bundle.get("arpi_selection_contract") or {})
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad metastásica sensible a la castración de bajo volumen",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "El bajo volumen no equivale a enfermedad localizada; sigue requiriendo intensificación sistémica adecuada al contexto.",
                f"Candidato a radioterapia al tumor primario: {'sí' if nccn['rt_primary_candidate'] else 'no'}.",
                "La salud ósea basal debe documentarse antes de prolongar terapia sistémica en enfermedad metastásica.",
                "La selección entre darolutamida, enzalutamida, apalutamida y abiraterona se ajusta por comorbilidades neurológicas, cardiovasculares y hepáticas.",
            ],
            alternatives=[
                "Radioterapia al tumor primario cuando la próstata no ha recibido tratamiento local y el escenario sigue siendo de bajo volumen.",
                "Doblete sistémico individualizado según riesgo de convulsiones, tolerancia hepática y preferencias del paciente.",
            ],
            shared_decision_message=(
                "La conducta final debe integrar volumen metastásico real, estado funcional, toxicidad esperada y la conveniencia de añadir o no tratamiento local al primario."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 ayuda a confirmar cuándo la radioterapia al primario agrega valor y cómo priorizar el doblete sistémico."
            ),
        )

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower():
                return item.get("evidence", "")
        return ""
