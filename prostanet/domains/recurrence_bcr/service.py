from __future__ import annotations

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.recurrence_bcr.rules_eau import classify_recurrence_eau
from prostanet.domains.recurrence_bcr.rules_nccn import classify_recurrence
from prostanet.domains.recurrence_bcr.schemas import RECURRENCE_BCR_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class RecurrenceBCRService:
    module_id = "recurrence_bcr"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return RECURRENCE_BCR_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_recurrence(payload)
        eau = classify_recurrence_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        psma_profile = (
            build_psma_structured_profile_from_payload(payload)
            if str(payload.get("psma_pet_done", "0")) == "1"
            else {"available": False}
        )
        psma_impact = build_psma_decision_impact(psma_profile, state=self.module_id, patient={"baseline": payload})
        psa_current = float(payload.get("psa_current", payload.get("psa", 0)) or 0)
        psadt = float(payload.get("psadt_months", 0) or 0)
        treatments = []
        durations = []
        not_recommended = []
        trials = []
        missing_inputs = [field for field in ["psa_current", "psadt_months"] if str(payload.get(field, "")).strip() == ""]

        if nccn["label"] == "BCR2 N0M0":
            if nccn["enza_match"]:
                treatments.append({"name": "Enzalutamide +/- leuprolide", "priority": "preferred", "notes": "High-risk BCR2 pattern with conventional M0 imaging and no curative pelvic-directed option."})
                trials.append({"trial": "EMBARK", "match": True})
            if nccn["psma_pet_recommended"] and not nccn["psma_pet_done"]:
                treatments.append({"name": "PSMA-PET directed salvage staging", "priority": "selected_candidate", "notes": nccn["psma_pet_reason"]})
            not_recommended.extend([
                "Do not expose BCR2 systemic options when criteria are not met.",
                "Do not treat apalutamide plus ADT as a routine BCR2 option without a source pathway equivalent to the primary guideline base.",
            ])
        elif nccn["label"] == "Post-RP recurrence":
            treatments.append({"name": "Early salvage RT evaluation", "priority": "preferred", "notes": "Use PSA persistence/recurrence thresholds and clinical risk."})
            if nccn["psma_pet_recommended"] and not nccn["psma_pet_done"]:
                treatments.append({"name": "PSMA-PET directed salvage staging", "priority": "selected_candidate", "notes": nccn["psma_pet_reason"]})
            if psma_impact.get("clinical_pattern") == "local_pelvic" and psma_impact.get("confidence") != "low":
                treatments.append({"name": "Salvage RT guiada por PSMA", "priority": "eligible", "notes": "PSMA local/pélvico mantiene abierta la ventana curativa y refuerza rescate dirigido."})
            elif psma_impact.get("clinical_pattern") == "oligometastatic":
                treatments.append({"name": "MDT / rescate multimodal guiado por PSMA", "priority": "selected_candidate", "notes": "PSMA multifocal de bajo burden abre discusión de MDT/SBRT o rescate combinado."})
            elif psma_impact.get("clinical_pattern") == "diseminado":
                not_recommended.append("No priorizar rescate local aislado cuando el PSMA documenta patrón diseminado o estadio M1b/M1c.")
                treatments.append({"name": "Reestadificación sistémica post-PSMA", "priority": "eligible", "notes": "La distribución por PSMA reduce la plausibilidad de rescate local aislado."})
            durations.append("If ADT is added with secondary RT, use a risk-adapted duration in the 6-24 month range.")
            trials.extend([{"trial": "RTOG 9601", "match": True}, {"trial": "GETUG-AFU 16", "match": True}])
        else:
            if nccn["local_salvage_candidate"]:
                treatments.append({"name": "Post-RT local salvage review", "priority": "preferred", "notes": "Keep local salvage visible only when a curative-intent option remains technically plausible."})
            treatments.append({"name": "Re-staging after RT recurrence", "priority": "preferred", "notes": "Confirm local-only versus systemic recurrence before treatment selection."})
            if nccn["psma_pet_recommended"] and not nccn["psma_pet_done"]:
                treatments.append({"name": "PSMA-PET directed salvage staging", "priority": "selected_candidate", "notes": nccn["psma_pet_reason"]})
            if psma_impact.get("clinical_pattern") == "local_pelvic" and psma_impact.get("confidence") != "low":
                treatments.append({"name": "Revisión de rescate local guiada por PSMA", "priority": "eligible", "notes": "PSMA local/pélvico apoya salvamento local si sigue siendo técnicamente factible."})
            elif psma_impact.get("clinical_pattern") == "oligometastatic":
                treatments.append({"name": "MDT/SBRT guiado por PSMA", "priority": "selected_candidate", "notes": "PSMA con burden limitado abre ruta oligometastásica contextual."})
            elif psma_impact.get("clinical_pattern") == "diseminado":
                not_recommended.append("No usar una lectura diseminada de PSMA como base para rescate local aislado después de RT.")
            trials.append({"trial": "Local salvage after RT evidence set", "match": True})
            not_recommended.append("Do not use PSMA-PET after RT recurrence unless the patient is a realistic local-salvage candidate.")
        if psma_impact.get("confidence") == "low":
            not_recommended.append("No escalar una decisión mayor con PSMA-RADS bajo/intermedio o estructura PSMA incompleta sin correlación adicional.")
        durations.extend(psma_impact.get("recommended_actions", [])[:2])

        case_summary = (
            f"El caso corresponde a {nccn['label']} con antígeno prostático específico actual de {psa_current:g} ng/mL "
            f"y tiempo de duplicación del antígeno prostático específico de {psadt:g} meses. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 prioriza {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo compara como {eau['label']}."
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=missing_inputs,
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=trials,
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": f"Recurrence pathway: {nccn['label']}.",
                "embark_readiness": {
                    "high_risk_bcr2": nccn["high_risk_bcr2"],
                    "conventional_imaging_m0": nccn["conventional_imaging_m0"],
                    "salvage_local_feasible": nccn["salvage_local_feasible"],
                },
            },
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de recurrencia bioquímica",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "La conducta cambia según antecedente de prostatectomía radical, radioterapia previa o segunda recurrencia bioquímica sin metástasis.",
                f"El tiempo de duplicación del antígeno prostático específico observado es de {psadt:g} meses.",
                "Las rutas sistémicas para segunda recurrencia bioquímica de alto riesgo solo deben activarse si cumplen exactamente los criterios del escenario y no queda rescate local potencialmente curativo.",
                "La tomografía por emisión de positrones dirigida al antígeno prostático específico de membrana debe usarse solo si cambia una decisión de rescate y no como imagen rutinaria indiscriminada.",
                psma_impact.get("rationale"),
            ],
            alternatives=[
                "Radioterapia de rescate temprana y terapia de privación androgénica adaptada al riesgo si el escenario es posterior a prostatectomía radical.",
                "Reestadificación completa y discusión de rescate local frente a transición sistémica si la recurrencia ocurre después de radioterapia.",
            ],
            shared_decision_message=(
                "La decisión debe integrar velocidad de recaída, imágenes disponibles, oportunidad real de rescate pélvico y preferencia del paciente sobre toxicidad urinaria, intestinal y sistémica."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 confirma si la ruta dominante es rescate temprano, reestadificación o una vía sistémica específica de segunda recurrencia bioquímica."
            ),
        )
