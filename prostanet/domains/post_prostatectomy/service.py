from __future__ import annotations

from clinical_scores import calculate_capra_s

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.post_prostatectomy.rules_eau import classify_post_rp_eau
from prostanet.domains.post_prostatectomy.rules_nccn import classify_post_rp
from prostanet.domains.post_prostatectomy.schemas import POST_PROSTATECTOMY_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class PostProstatectomyService:
    module_id = "post_prostatectomy"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return POST_PROSTATECTOMY_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        missing = [field for field in ["psa", "psa_postop"] if str(payload.get(field, "")).strip() == ""]
        nccn = classify_post_rp(payload)
        eau = classify_post_rp_eau(payload)
        capra_s = calculate_capra_s(payload)
        comparison = self.comparison.compare(nccn, eau)
        label = nccn["label"]
        eligible = []
        not_recommended = []
        durations = []
        decipher_risk = str(payload.get("decipher_risk", "No realizado"))
        imaging_modality = str(payload.get("imaging_modality", "Ninguna"))

        if label == "PSA persistence/recurrence":
            eligible.append({"name": "Recurrence/BCR workflow", "priority": "preferred", "notes": "Use the recurrence module for salvage and BCR2 logic."})
            not_recommended.append("Do not present CAPRA-S as a substitute for salvage-pathway staging.")
        elif nccn["adverse_features"]:
            eligible.append({"name": "Close surveillance", "priority": "preferred", "notes": "Monitor PSA closely and trigger early salvage when indicated."})
            eligible.append({"name": "Early salvage planning", "priority": "preferred" if nccn.get("early_salvage_emphasis") else "eligible", "notes": "Discuss timing and need for RT +/- ADT using recurrence module."})
            not_recommended.append("Avoid framing adjuvant RT as mandatory for every adverse-pathology patient.")
        else:
            eligible.append({"name": "Routine postoperative surveillance", "priority": "preferred", "notes": "Continue PSA monitoring."})
        if decipher_risk == "Alto":
            durations.append("El riesgo Decipher alto favorece una conversación más temprana sobre rescate posoperatorio si el contexto anatómico sigue siendo curable.")
        if imaging_modality == "PSMA-PET":
            durations.append("La imagen PSMA-PET en el contexto posoperatorio debe cambiar una decisión real de rescate y no sustituir la cronología del PSA ultrasensible.")

        psa_postop = float(payload.get("psa_postop", 0) or 0)
        pathologic_stage = str(payload.get("pathologic_stage", "pTx")).strip() or "pTx"
        case_summary = (
            f"El escenario corresponde a seguimiento después de prostatectomía radical, "
            f"con estadio patológico {pathologic_stage} y antígeno prostático específico posoperatorio de {psa_postop:g} ng/mL. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 describe el caso como {nccn['label']}, "
            f"mientras la Asociación Europea de Urología (EAU) 2026 lo contrasta como {eau['label']}."
        )

        report_sections = {
            "summary": f"Post-RP status: {nccn['label']}. CAPRA-S belongs only to this module.",
            "capra_s": capra_s,
            "validated_algorithms": {
                "capra_s_score": capra_s.get("score") if isinstance(capra_s, dict) else None,
                "decipher_risk": decipher_risk,
            },
        }

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=eligible,
            not_recommended=not_recommended,
            missing_critical_inputs=missing,
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[{"trial": "RADICALS-RT", "match": nccn["adverse_features"]}, {"trial": "SWOG-8794", "match": nccn["adverse_features"]}],
            applicability_badge="guideline-consistent",
            report_sections=report_sections,
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada después de prostatectomía radical",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                f"El puntaje postoperatorio CAPRA-S se conserva solo en este módulo y no debe extrapolarse al contexto preoperatorio.",
                f"Puntaje postoperatorio CAPRA-S estimado: {capra_s.get('score', 'no disponible') if isinstance(capra_s, dict) else capra_s}.",
                "La conducta depende de la combinación de antígeno prostático específico posoperatorio, márgenes, extensión extracapsular, invasión de vesículas seminales y ganglios.",
                "Decipher y el tiempo a recurrencia refinan la urgencia del rescate, pero no convierten la adyuvancia rutinaria en estándar universal.",
                "El objetivo es activar rescate temprano cuando exista persistencia o recurrencia, evitando adyuvancia rutinaria indiscriminada.",
            ],
            alternatives=[
                "Vigilancia estrecha con antígeno prostático específico seriado cuando no hay persistencia bioquímica franca.",
                "Planificación temprana de radioterapia de rescate con o sin terapia de privación androgénica en presencia de factores adversos y riesgo clínico suficiente.",
            ],
            shared_decision_message=(
                "La recomendación debe equilibrar la probabilidad de recurrencia, la toxicidad urinaria o sexual esperable y la disposición del paciente a adelantar o diferir tratamiento de rescate."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 ayuda a distinguir vigilancia estrecha frente a planificación temprana de rescate sin convertir la adyuvancia en una obligación automática."
            ),
        )
