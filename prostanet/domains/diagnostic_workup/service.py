from __future__ import annotations

from prostanet.domains.diagnostic_workup.rules_eau import classify_diagnostic_workup_eau
from prostanet.domains.diagnostic_workup.rules_nccn import classify_diagnostic_workup
from prostanet.domains.diagnostic_workup.schemas import DIAGNOSTIC_WORKUP_SCHEMA
from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.dre import has_dre_documentation, normalize_dre
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class DiagnosticWorkupService:
    module_id = "diagnostic_workup"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return DIAGNOSTIC_WORKUP_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = classify_diagnostic_workup(payload)
        eau = classify_diagnostic_workup_eau(payload)
        comparison = self.comparison.compare(nccn, eau)

        psa = float(payload.get("psa", 0) or 0)
        psad = float(payload.get("psad", 0) or 0)
        pirads = int(float(payload.get("pirads_score", 0) or 0))
        dre = normalize_dre(payload)
        erspc_ready = all(payload.get(field) not in (None, "") for field in ("age", "psa")) and has_dre_documentation(payload)

        treatments = []
        if nccn["biopsy_indicated"]:
            treatments.append(
                {
                    "name": "Biopsia dirigida más biopsia sistemática",
                    "priority": "preferred",
                    "notes": "La sospecha clínica supera el umbral de observación aislada y justifica confirmación histológica.",
                }
            )
        if nccn["repeat_high_quality_mri"]:
            treatments.append(
                {
                    "name": "Repetir resonancia magnética multiparamétrica de alta calidad",
                    "priority": "selected_candidate",
                    "notes": "Una MRI subóptima no debe sustentar una falsa tranquilidad diagnóstica.",
                }
            )
        treatments.append(
            {
                "name": "Resonancia magnética multiparamétrica con revisión dirigida",
                "priority": "eligible",
                "notes": "Sirve para precisar la localización de lesiones y evitar una decisión ciega basada solo en antígeno prostático específico.",
            }
        )
        if not nccn["biopsy_indicated"]:
            treatments.append(
                {
                    "name": "Repetición estructurada de antígeno prostático específico y densidad del antígeno prostático específico",
                    "priority": "eligible",
                    "notes": "Adecuado cuando la sospecha es baja y no existe una señal clínica fuerte.",
                }
            )

        not_recommended = [
            "No usar la tomografía por emisión de positrones dirigida al antígeno prostático específico de membrana como sustituto de la confirmación histológica.",
            "No diferir indefinidamente la biopsia si persisten densidad elevada del antígeno prostático específico, tacto rectal sospechoso o una lesión PI-RADS 4 o 5.",
        ]
        durations = [
            "Si la sospecha es baja, repetir antígeno prostático específico y densidad del antígeno prostático específico en 6 a 12 semanas antes de descartar la vía diagnóstica.",
            "Si la sospecha es intermedia o alta, priorizar resonancia magnética y biopsia sin demoras prolongadas.",
        ]

        case_summary = (
            f"El paciente se encuentra en estudio diagnóstico sin confirmación histológica previa, con antígeno prostático específico de {psa:g} ng/mL, "
            f"densidad del antígeno prostático específico de {psad:g}, tacto rectal {'sospechoso' if dre.is_suspicious else 'no sospechoso'} "
            f"y resonancia magnética multiparamétrica con PI-RADS {pirads if pirads else 'no disponible'}. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 lo sitúa en {nccn['label'].lower()} y la Asociación Europea de Urología (EAU) 2026 lo compara como {eau['label'].lower()}."
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={
                "guideline": "NCCN",
                "version": "5.2026",
                "label": nccn["label"],
                "risk_group": nccn["risk_group"],
                "recommendation": nccn["recommendation"],
                "reasons": nccn["reasons"],
            },
            eau_comparison={
                "guideline": "EAU",
                "version": "2026",
                "label": eau["label"],
                "risk_group": eau["risk_group"],
                "recommendation": eau["recommendation"],
                "comparison": comparison,
            },
            eligible_treatments=treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=[field for field in ["psa"] if str(payload.get(field, "")).strip() == ""],
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[],
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": case_summary,
                "diagnostic_risk_pct": nccn["significant_risk_pct"],
                "validated_algorithms": {
                    "erspc_ready": erspc_ready,
                },
            },
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de estudio diagnóstico",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                *nccn["reasons"],
                f"Riesgo estimado de cáncer clínicamente significativo: {nccn['significant_risk_pct']}%.",
                "El pathway MRI + PSAD y la velocidad de PSA ya modifican la intensidad diagnóstica cuando el caso es limítrofe.",
                (
                    "Las entradas estan listas para correr ERSPC Risk Calculator como refinador libre de deteccion temprana."
                    if erspc_ready
                    else "ERSPC Risk Calculator sigue incompleto porque faltan entradas basales clave."
                ),
                "La confirmación histológica sigue siendo el punto de entrada obligatorio antes de una ruta terapéutica formal.",
            ],
            alternatives=[
                "Repetir antígeno prostático específico y densidad del antígeno prostático específico cuando la sospecha es baja y no hay disparadores clínicos mayores.",
                "Revisar la resonancia magnética multiparamétrica antes de indicar una biopsia repetida si existe una biopsia benigna previa.",
            ],
            shared_decision_message=(
                "La decisión entre biopsia inmediata y revaluación corta debe integrar el grado de sospecha, la ansiedad diagnóstica del paciente, la expectativa de vida y la calidad de la resonancia magnética disponible."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 ayuda a confirmar si la sospecha es suficiente para avanzar a biopsia o si aún puede mantenerse una revaloración estructurada."
            ),
        )
