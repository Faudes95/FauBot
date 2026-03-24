from __future__ import annotations

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_nmcrpc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.m0_crpc.rules_eau import evaluate_m0_crpc_eau
from prostanet.domains.m0_crpc.rules_nccn import evaluate_m0_crpc
from prostanet.domains.m0_crpc.schemas import M0_CRPC_SCHEMA
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
        normalized = dict(payload)
        normalized["comorbidities"] = {
            "seizure": str(payload.get("comorbidity_seizure", "0")) == "1",
        }
        legacy = evaluate_patient_for_nmcrpc(normalized)
        treatments = []
        not_recommended = []
        missing_critical_inputs = [field for field in ["psadt_months"] if str(payload.get(field, "")).strip() == ""]
        if not castrate_confirmed:
            treatments.append({"name": "Optimizar ADT y confirmar testosterona en rango de castración", "priority": "preferred", "notes": "Sin esta confirmación no debe etiquetarse ni intensificarse como enfermedad resistente a la castración sin metástasis."})
            not_recommended.append("Evitar iniciar un inhibidor de la vía del receptor androgénico antes de confirmar testosterona en rango de castración.")
            missing_critical_inputs.append("castrate_testosterone_confirmed")
        elif nccn["observe_only"]:
            treatments.append({"name": "Vigilancia estrecha con ADT y monitorización", "priority": "preferred", "notes": "PSADT >10 meses favorece observación estrecha antes de escalar con ARPI."})
            not_recommended.append("Evitar escalada automatica a ARPI cuando el PSADT es mayor de 10 meses.")
        else:
            if nccn["prefer_darolutamide"]:
                treatments.append({"name": "Darolutamida + ADT", "priority": "preferred", "notes": self._note_for(legacy, "Darolutamida")})
                not_recommended.append("Evitar enzalutamida/apalutamida cuando existe riesgo convulsivo relevante y darolutamida esta disponible.")
            else:
                treatments.append({"name": "Apalutamida + ADT", "priority": "eligible", "notes": self._note_for(legacy, "Apalutamida")})
                treatments.append({"name": "Enzalutamida + ADT", "priority": "eligible", "notes": self._note_for(legacy, "Enzalutamida")})
                treatments.append({"name": "Darolutamida + ADT", "priority": "preferred", "notes": self._note_for(legacy, "Darolutamida")})
        case_summary = (
            f"El caso corresponde a enfermedad resistente a la castración sin metástasis, con tiempo de duplicación del antígeno prostático específico de {psadt:g} meses. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 mantiene el escenario como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo compara con {eau['label']}."
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=missing_critical_inputs,
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=["Mantener la castracion con ADT durante toda la estrategia seleccionada.", "Si se inicia ARPI, continuar hasta progresion o toxicidad inaceptable."],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[{"trial": "SPARTAN", "match": nccn["high_risk_nmcrpc"]}, {"trial": "ARAMIS", "match": True}],
            applicability_badge="guideline-consistent" if castrate_confirmed else "selected_candidate",
            report_sections={"summary": "M0 CRPC risk-adapted intensification pathway."},
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad resistente a la castración sin metástasis",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                f"El tiempo de duplicación del antígeno prostático específico es de {psadt:g} meses.",
                "La confirmación de testosterona en rango de castración es obligatoria antes de considerar que el caso pertenece a este estado clínico.",
                "Cuando el tiempo de duplicación es corto, la intensificación con inhibidor de la vía del receptor androgénico gana prioridad clínica.",
                "El riesgo convulsivo modifica la selección del agente y favorece darolutamida cuando está disponible.",
                "La terapia de privación androgénica debe mantenerse como base en todo el escenario.",
            ],
            alternatives=[
                "Observación estrecha con terapia de privación androgénica sola cuando el tiempo de duplicación del antígeno prostático específico supera 10 meses.",
                "Darolutamida, apalutamida o enzalutamida según riesgo, contraindicaciones neurológicas y disponibilidad.",
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
