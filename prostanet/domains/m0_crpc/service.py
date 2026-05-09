from __future__ import annotations

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_nmcrpc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.m0_crpc.rules_eau import evaluate_m0_crpc_eau
from prostanet.domains.m0_crpc.rules_nccn import evaluate_m0_crpc
from prostanet.domains.m0_crpc.schemas import M0_CRPC_SCHEMA
from prostanet.domains.patient_tracking.arpi_selection_engine import (
    build_arpi_capture_contract,
    candidate_regimens_for_state,
    evaluate_arpi_candidate,
)
from prostanet.domains.patient_tracking.therapy_catalog import build_treatment_option
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
)
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class M0CrpcService:
    module_id = "m0_crpc"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return M0_CRPC_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_m0_crpc(payload)
        eau = evaluate_m0_crpc_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        psadt = float(payload.get("psadt_months", 0) or 0)
        castrate_confirmed = str(payload.get("castrate_testosterone_confirmed", "0")) == "1"
        imaging_negative = bool(nccn.get("imaging_negative"))
        normalized = dict(payload)
        normalized["comorbidities"] = {
            "seizure": str(payload.get("comorbidity_seizure", "0")) == "1",
        }
        legacy = evaluate_patient_for_nmcrpc(normalized)
        treatments = []
        not_recommended = []
        psadt_documented = str(payload.get("psadt_months", "")).strip() != ""
        missing_critical_inputs = [field for field in ["psadt_months"] if str(payload.get(field, "")).strip() == ""]
        psadt_advisory_note = ""
        frailty = str(payload.get("frailty_status", "Fit") or "Fit").strip().lower()
        conventional_imaging_modality = str(payload.get("conventional_imaging_modality", "Desconocida") or "Desconocida").strip()
        conventional_imaging_date = str(payload.get("conventional_imaging_date") or "").strip()
        arpi_candidate_regimens = candidate_regimens_for_state(self.module_id, payload)
        arpi_capture_contract = build_arpi_capture_contract(
            self.module_id,
            payload,
            candidate_regimens=arpi_candidate_regimens,
        )
        if not psadt_documented:
            psadt_advisory_note = "Verificar PSADT <10 meses para confirmar elegibilidad per SPARTAN/PROSPER/ARAMIS. Se recomienda ARPI pero obtener PSADT es prioritario."
        elif psadt >= 10:
            psadt_advisory_note = "PSADT ≥10 meses — observación estrecha favorecida per SPARTAN/PROSPER/ARAMIS. Evaluar si ARPI aporta beneficio neto vs vigilancia."
        if not castrate_confirmed:
            treatments.append(
                build_ranked_option(
                    name="Optimizar ADT y confirmar testosterona en rango de castración",
                    rank=1,
                    priority="preferred",
                    eligibility_status="preferred",
                    regimen_code="ADT_MONO",
                    family_code="observation_family",
                    notes="Sin esta confirmación no debe etiquetarse ni intensificarse como enfermedad resistente a la castración sin metástasis.",
                    why_this_rank=["La castración confirmada sigue siendo un gate clínico duro antes de intensificar como nmCRPC."],
                    selection_rationale=["La testosterona en rango de castración es obligatoria antes de confirmar un estado nmCRPC."],
                )
            )
            not_recommended.append("Evitar iniciar un inhibidor de la vía del receptor androgénico antes de confirmar testosterona en rango de castración.")
            missing_critical_inputs.append("castrate_testosterone_confirmed")
        elif not imaging_negative:
            treatments.append(
                build_ranked_option(
                    name="Completar reestadificación y reclasificar fuera de nmCRPC",
                    rank=1,
                    priority="preferred",
                    eligibility_status="preferred",
                    regimen_code="RESTAGING",
                    family_code="observation_family",
                    notes="La intensificación tipo nmCRPC no debe cerrarse mientras la imagen convencional no confirme que el paciente sigue sin metástasis detectables.",
                    why_this_rank=["La negatividad en imagen convencional sigue siendo un criterio estructural antes de tratar como nmCRPC."],
                    selection_rationale=["La negatividad en imagen convencional sigue siendo un criterio duro antes de intensificar como nmCRPC."],
                )
            )
            not_recommended.append("Evitar etiquetar o tratar como nmCRPC si la imagen ya es positiva o no concluyente.")
            missing_critical_inputs.append("imaging_negative")
        elif nccn["observe_only"]:
            treatments.append(
                build_ranked_option(
                    name="Vigilancia estrecha con ADT y monitorización",
                    rank=1,
                    priority="preferred",
                    eligibility_status="preferred",
                    regimen_code="ADT_MONO",
                    family_code="observation_family",
                    notes="PSADT >10 meses favorece observación estrecha antes de escalar con ARPI.",
                    why_this_rank=["PSADT >10 meses mantiene la vigilancia como conducta preferente antes de escalar con ARPI."],
                    selection_rationale=["PSADT mayor de 10 meses reduce el beneficio neto inmediato de intensificación con ARPI."],
                )
            )
            not_recommended.append("Evitar escalada automatica a ARPI cuando el PSADT es mayor de 10 meses.")
        else:
            candidates = []
            for regimen_code in arpi_candidate_regimens:
                arpi_meta = evaluate_arpi_candidate(
                    self.module_id,
                    payload,
                    regimen_code,
                    candidate_regimens=arpi_candidate_regimens,
                )
                drug_label = (
                    "Enzalutamida"
                    if regimen_code == "ADT_ENZALUTAMIDE"
                    else "Apalutamida"
                    if regimen_code == "ADT_APALUTAMIDE"
                    else "Darolutamida"
                )
                note = self._note_for(legacy, drug_label)
                selection_rationale = [item for item in [arpi_meta.get("benefit_basis"), note] if item]
                selection_rationale.extend(list(arpi_meta.get("safety_rationale") or []))
                contraindications = []
                if arpi_meta.get("required_missing_fields"):
                    contraindications.append(
                        "Faltan discriminadores ARPI clave: " + ", ".join(arpi_meta.get("required_missing_fields") or [])
                    )
                if arpi_meta.get("stale_inputs"):
                    contraindications.append(
                        "Existen datos ARPI vencidos: " + ", ".join(arpi_meta.get("stale_inputs") or [])
                    )
                candidates.append(
                    {
                        "name": f"{drug_label} + terapia de privación androgénica",
                        "regimen_code": regimen_code,
                        "score": float(arpi_meta.get("benefit_adjustment") or 0.0),
                        "molecule_or_backbone": drug_label,
                        "selection_rationale": selection_rationale,
                        "contraindication_reasons": contraindications,
                        "notes": note,
                        "benefit_basis": arpi_meta.get("benefit_basis", ""),
                        "benefit_endpoint_used": arpi_meta.get("benefit_endpoint_used", ""),
                        "benefit_maturity": arpi_meta.get("benefit_maturity", ""),
                        "preference_confidence": arpi_meta.get("preference_confidence", "definitive"),
                        "required_missing_fields": list(arpi_meta.get("required_missing_fields") or []),
                        "stale_inputs": list(arpi_meta.get("stale_inputs") or []),
                        "safety_drivers_used": list(arpi_meta.get("safety_drivers_used") or []),
                    }
                )
            if nccn["prefer_darolutamide"]:
                not_recommended.append("Evitar enzalutamida/apalutamida cuando existe riesgo convulsivo relevante y darolutamida está disponible.")
            if not conventional_imaging_date:
                missing_critical_inputs.append("conventional_imaging_date")
            if conventional_imaging_modality in {"", "Desconocida"}:
                missing_critical_inputs.append("conventional_imaging_modality")
            missing_critical_inputs.extend(arpi_capture_contract.get("arpi_missing_inputs") or [])
            missing_critical_inputs.extend(arpi_capture_contract.get("arpi_stale_inputs") or [])
            missing_critical_inputs = list(dict.fromkeys(missing_critical_inputs))
            candidates.sort(key=lambda item: (item["score"], item["regimen_code"]), reverse=True)
            for index, item in enumerate(candidates):
                is_definitive = str(item.get("preference_confidence") or "definitive") == "definitive"
                is_leader = index == 0
                treatments.append(
                    build_ranked_option(
                        name=item["name"],
                        regimen_code=item["regimen_code"],
                        rank=index + 1,
                        priority="preferred" if is_leader and is_definitive else "eligible",
                        eligibility_status=(
                            "preferred"
                            if is_leader and is_definitive
                            else "eligible_with_caution"
                            if item["contraindication_reasons"] or not is_definitive
                            else "eligible_nonpreferred"
                        ),
                        family_code="arpi_family",
                        molecule_or_backbone=item["molecule_or_backbone"],
                        why_this_rank=item["selection_rationale"][:2] + item["contraindication_reasons"][:1],
                        hard_blocks=[],
                        caution_flags=item["contraindication_reasons"],
                        ranking_score=item["score"],
                        notes=item["notes"],
                        selection_rationale=item["selection_rationale"],
                        contraindication_reasons=item["contraindication_reasons"],
                        benefit_basis=item["benefit_basis"],
                        benefit_endpoint_used=item["benefit_endpoint_used"],
                        benefit_maturity=item["benefit_maturity"],
                        preference_confidence=item["preference_confidence"],
                        required_missing_fields=item["required_missing_fields"],
                        safety_drivers_used=item["safety_drivers_used"],
                        stale_inputs=item["stale_inputs"],
                    )
                )
        family_profiles: dict[str, dict] = {}
        arpi_variants = [item for item in treatments if item.get("family_code") == "arpi_family"]
        observation_variants = [item for item in treatments if item.get("family_code") == "observation_family"]
        if arpi_variants:
            family_profiles["arpi_family"] = build_family_profile(
                family_code="arpi_family",
                ordered_regimens=arpi_variants,
                context={
                    "eligibility_status": "eligible" if castrate_confirmed and imaging_negative and not nccn["observe_only"] else "conditional",
                    "caution_drivers": nccn.get("enzalutamide_caution_reasons", []) + nccn.get("apalutamide_caution_reasons", []),
                    "preference_drivers": nccn.get("darolutamide_preference_reasons", []),
                    "missing_inputs": list(dict.fromkeys(
                        [item for item in ["conventional_imaging_modality", "conventional_imaging_date"] if item in missing_critical_inputs]
                        + list(arpi_capture_contract.get("arpi_missing_inputs") or [])
                    )),
                    "stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
                    "evidence_alignment": "matched" if nccn["high_risk_nmcrpc"] else "partial",
                    "winner_reason": "La selección preferente entre ARPI se ordenó por beneficio clínico esperado, riesgo convulsivo, fragilidad, DDI, cardio y tolerabilidad global.",
                    "why_not_preferred": "Otros ARPI permanecen visibles si no existe bloqueo duro, pero bajan por beneficio relativo, seguridad o captura incompleta.",
                    "ranking_trace": [item.get("why_this_rank") or [] for item in arpi_variants],
                },
            )
        if observation_variants:
            family_profiles["observation_family"] = build_family_profile(
                family_code="observation_family",
                ordered_regimens=observation_variants,
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": "La observación con ADT sigue siendo preferente cuando aún no se confirma castración, la imagen no es M0 o el PSADT supera 10 meses.",
                    "evidence_alignment": "matched",
                },
            )
        family_order = ["observation_family", "arpi_family"] if observation_variants else ["arpi_family"]
        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=missing_critical_inputs,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="m0_crpc",
            field_values=payload,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "observation_family",
            field_values=payload,
        )
        case_summary = (
            f"El caso corresponde a enfermedad resistente a la castración sin metástasis, con tiempo de duplicación del antígeno prostático específico de {psadt:g} meses. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 mantiene el escenario como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo compara con {eau['label']}."
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=comparative_bundle.get("eligible_treatments") or treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=missing_critical_inputs,
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=["Mantener la castracion con ADT durante toda la estrategia seleccionada.", "Si se inicia ARPI, continuar hasta progresion o toxicidad inaceptable."],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[{"trial": "SPARTAN", "match": nccn["high_risk_nmcrpc"]}, {"trial": "PROSPER", "match": nccn["high_risk_nmcrpc"]}, {"trial": "ARAMIS", "match": True}],
            applicability_badge="guideline-consistent" if castrate_confirmed else "selected_candidate",
            report_sections={"summary": "M0 CRPC risk-adapted intensification pathway.", "psadt_advisory": psadt_advisory_note},
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or ("Observación / backbone" if observation_variants else "ARPI"),
                "confidence_category": "vigilada" if missing_critical_inputs else "alta",
                "requires_human_review": bool(missing_critical_inputs),
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        result["variant_ranking"] = ((family_profiles.get("arpi_family") or {}).get("variant_ranking") or {})
        result["arpi_required_fields"] = list(arpi_capture_contract.get("arpi_required_fields") or [])
        result["arpi_missing_inputs"] = list(arpi_capture_contract.get("arpi_missing_inputs") or [])
        result["arpi_stale_inputs"] = list(arpi_capture_contract.get("arpi_stale_inputs") or [])
        result["arpi_profile_completeness"] = str(arpi_capture_contract.get("arpi_profile_completeness") or "")
        result["arpi_preference_readiness"] = str(arpi_capture_contract.get("arpi_preference_readiness") or "")
        result["arpi_selection_contract"] = arpi_capture_contract
        result["patient_goals_profile"] = {
            "primary_goal": str(payload.get("primary_goal") or "balanced"),
            "visit_burden_tolerance": str(payload.get("visit_burden_tolerance") or "medium"),
            "route_preference": str(payload.get("route_preference") or "oral"),
            "symptom_priority": str(payload.get("symptom_priority") or "mixed"),
        }
        result["care_setting_contract"] = {
            "care_setting": "systemic_intensification" if arpi_variants else "supportive_only",
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad resistente a la castración sin metástasis",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                f"El tiempo de duplicación del antígeno prostático específico es de {psadt:g} meses.",
                "La confirmación de testosterona en rango de castración es obligatoria antes de considerar que el caso pertenece a este estado clínico.",
                "La imagen convencional negativa sigue siendo un gating duro antes de mantener la clasificación como nmCRPC.",
                "Cuando el tiempo de duplicación es corto, la intensificación con inhibidor de la vía del receptor androgénico gana prioridad clínica.",
                "El riesgo convulsivo, la fragilidad, la polifarmacia y el antecedente dermatológico deben cambiar realmente la selección entre ARPI.",
                "La terapia de privación androgénica debe mantenerse como base en todo el escenario.",
            ],
            alternatives=[
                "Observación estrecha con terapia de privación androgénica sola cuando el tiempo de duplicación del antígeno prostático específico supera 10 meses.",
                "Enzalutamida, apalutamida o darolutamida según riesgo convulsivo, fragilidad, interacciones y perfil cardiovascular.",
            ],
            shared_decision_message=(
                "La selección final debe integrar velocidad de progresión, riesgo neurológico, tolerancia esperada al tratamiento continuo y metas del paciente respecto a fatiga, caídas y calidad de vida."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 refuerza si el caso requiere intensificación inmediata o si aún es razonable una vigilancia estrecha."
            ),
        )

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower():
                return item.get("evidence", "")
        return ""
