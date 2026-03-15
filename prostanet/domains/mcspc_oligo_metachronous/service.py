from __future__ import annotations

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.mcspc_oligo_metachronous.rules_eau import evaluate_mcspc_oligo_metachronous_eau
from prostanet.domains.mcspc_oligo_metachronous.rules_nccn import evaluate_mcspc_oligo_metachronous
from prostanet.domains.mcspc_oligo_metachronous.schemas import MCSPC_OLIGO_METACHRONOUS_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class McspcOligoMetachronousService:
    module_id = "mcspc_oligo_metachronous"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return MCSPC_OLIGO_METACHRONOUS_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_mcspc_oligo_metachronous(payload)
        eau = evaluate_mcspc_oligo_metachronous_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        normalized = dict(payload)
        normalized["comorbidities"] = {
            "seizure": str(payload.get("comorbidity_seizure", "0")) == "1",
            "cardio": str(payload.get("comorbidity_cardio", "0")) == "1",
        }
        legacy = evaluate_patient_for_mhspc(normalized)
        treatments = []
        if nccn["mdt_candidate"]:
            treatments.append({"name": "Metastasis-directed therapy", "priority": "selected_candidate", "notes": "Limited metachronous burden supports MDT discussion in tumor board."})
        if nccn["prefer_akeega"]:
            treatments.append({"name": "ADT + Niraparib + Abiraterone", "priority": "preferred", "notes": "Ruta de precisión para BRCA2 trazable en enfermedad sensible a la castración."})
        if nccn["prefer_enzalutamide"]:
            treatments.append({"name": "ADT + Enzalutamida", "priority": "preferred", "notes": self._note_for(legacy, "Enzalutamida")})
        if nccn["prefer_abiraterone"]:
            treatments.append({"name": "ADT + Abiraterona", "priority": "eligible", "notes": self._note_for(legacy, "Abiraterona")})
        if nccn["rezvilutamide_candidate"]:
            treatments.append({"name": "ADT + Rezvilutamida", "priority": "eligible", "notes": "Opción soportada por EAU 2026 cuando se selecciona doblete hormonal."})
        treatments.append({"name": "ADT + Apalutamida", "priority": "eligible", "notes": self._note_for(legacy, "Apalutamida")})
        if str(payload.get("metastasis_site", "Bone")) == "Bone":
            treatments.append({"name": "Calcio + vitamina D", "priority": "selected_candidate", "notes": "Bundle basal de salud ósea."})
            if not nccn["bone_protection_started"]:
                treatments.append({"name": "Denosumab o ácido zoledrónico", "priority": "selected_candidate", "notes": "Considerar según riesgo estructural y carga ósea."})
        case_summary = (
            "El caso corresponde a enfermedad metastásica sensible a la castración, oligometastásica y metacrónica. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 la sitúa como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 la compara con {eau['label']}."
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": "Combine systemic intensification with MDT discussion when disease is limited."},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=treatments,
            not_recommended=[
                "Avoid under-classifying metachronous metastatic disease as localized recurrence only.",
                "Do not omit systemic therapy solely because burden is limited.",
                "Do not present metastasis-directed therapy as standard-of-care outside a trial-like or multidisciplinary context.",
            ],
            missing_critical_inputs=[
                field
                for field in ["molecular_assay_source", "molecular_assay_date"]
                if nccn["prefer_akeega"] and str(payload.get(field, "")).strip() == ""
            ],
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=["Continue ADT backbone with the selected ARPI until progression or intolerance.", "Use MDT only after multidisciplinary review."],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "STAMPEDE", "match": True},
                {"trial": "PEACE-1", "match": nccn["fit_for_intensification"]},
                {"trial": "CHART", "match": nccn["rezvilutamide_candidate"]},
                {"trial": "AKEEGA BRCA2 mCSPC", "match": nccn["prefer_akeega"]},
            ],
            applicability_badge="selected_candidate" if nccn["mdt_candidate"] else "guideline-consistent",
            report_sections={"summary": "Metachronous oligometastatic hormone-sensitive pathway."},
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad oligometastásica metacrónica",
            case_summary=case_summary,
            recommended_trajectory="Combinar intensificación sistémica con discusión estructurada de terapia dirigida a metástasis cuando la carga de enfermedad siga siendo limitada.",
            personalized_fundamentals=[
                f"Candidato a terapia dirigida a metástasis: {'sí' if nccn['mdt_candidate'] else 'no'}.",
                f"Aptitud para intensificación sistémica: {'sí' if nccn['fit_for_intensification'] else 'no'}.",
                "La carga limitada de enfermedad no debe reclasificarse como recurrencia localizada simple, porque sigue siendo enfermedad metastásica sensible a la castración.",
                "La discusión de terapia dirigida a metástasis solo debe sostenerse si existe contexto de ensayo, cohorte prospectiva o comité multidisciplinario.",
            ],
            alternatives=[
                "Doblete sistémico con inhibidor del receptor androgénico cuando la terapia dirigida a metástasis no es factible o no cambia la estrategia principal.",
                "Discusión multidisciplinaria para decidir si la terapia dirigida a metástasis puede retrasar otras escaladas sin comprometer control oncológico.",
            ],
            shared_decision_message=(
                "La decisión final debe integrar número y sitio de metástasis, factibilidad técnica de tratamiento dirigido, tolerancia a intensificación sistémica y objetivos del paciente."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 es especialmente útil para decidir el peso relativo de la terapia dirigida a metástasis frente a la intensificación sistémica."
            ),
        )

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower():
                return item.get("evidence", "")
        return ""
