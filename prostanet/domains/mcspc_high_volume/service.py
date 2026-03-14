from __future__ import annotations

from precision_medicine import evaluate_patient_for_mhspc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.mcspc_high_volume.rules_eau import evaluate_mcspc_high_volume_eau
from prostanet.domains.mcspc_high_volume.rules_nccn import evaluate_mcspc_high_volume
from prostanet.domains.mcspc_high_volume.schemas import MCSPC_HIGH_VOLUME_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class McspcHighVolumeService:
    module_id = "mcspc_high_volume"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return MCSPC_HIGH_VOLUME_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_mcspc_high_volume(payload)
        eau = evaluate_mcspc_high_volume_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        normalized = dict(payload)
        normalized["comorbidities"] = {
            "seizure": str(payload.get("comorbidity_seizure", "0")) == "1",
            "cardio": str(payload.get("comorbidity_cardio", "0")) == "1",
        }
        legacy = evaluate_patient_for_mhspc(normalized)
        treatments = []
        if nccn["prefer_akeega"]:
            treatments.append({"name": "ADT + Niraparib + Abiraterone", "priority": "preferred", "notes": "BRCA2-directed precision path in mCSPC with traceable molecular assay."})
        if nccn["prefer_triplet_darolutamide"]:
            treatments.append({"name": "ADT + Docetaxel + Darolutamida", "priority": "preferred", "notes": self._note_for(legacy, "Darolutamida")})
        if nccn["prefer_triplet_abiraterone"]:
            treatments.append({"name": "ADT + Docetaxel + Abiraterona", "priority": "preferred", "notes": self._note_for(legacy, "Abiraterona")})
        if not treatments:
            if str(payload.get("comorbidity_seizure", "0")) != "1":
                treatments.append({"name": "ADT + Enzalutamida", "priority": "preferred", "notes": self._note_for(legacy, "Enzalutamida")})
            treatments.append({"name": "ADT + Apalutamida", "priority": "eligible", "notes": self._note_for(legacy, "Apalutamida")})
            if nccn["rezvilutamide_candidate"]:
                treatments.append({"name": "ADT + Rezvilutamida", "priority": "eligible", "notes": "Opción soportada por EAU 2026 para intensificación hormonal cuando se selecciona doblete."})
            if str(payload.get("child_pugh_score", "A")) != "C":
                treatments.append({"name": "ADT + Abiraterona", "priority": "eligible", "notes": self._note_for(legacy, "Abiraterona")})
        if str(payload.get("metastasis_site", "Bone")) == "Bone":
            treatments.append({"name": "Calcio + vitamina D", "priority": "selected_candidate", "notes": "Bundle basal de salud ósea para toda enfermedad metastásica sensible a la castración."})
            if not nccn["bone_protection_started"]:
                treatments.append({"name": "Denosumab o ácido zoledrónico", "priority": "selected_candidate", "notes": "Considerar cuando la carga ósea y el riesgo estructural lo justifican tras evaluación clínica."})
        case_summary = (
            "El caso corresponde a enfermedad metastásica sensible a la castración de alto volumen. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 la clasifica como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 la contrasta como {eau['label']}."
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=treatments,
            not_recommended=[
                "Do not downplay treatment intensification in high-volume mCSPC.",
                "Avoid low-volume style local-only strategies in high-volume disease.",
                "Do not default to ADT monotherapy in a clinically fit metastatic patient.",
            ],
            missing_critical_inputs=[
                field
                for field in ["molecular_assay_source", "molecular_assay_date"]
                if nccn["prefer_akeega"] and str(payload.get(field, "")).strip() == ""
            ],
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=["If docetaxel is selected, plan 6 cycles.", "Maintain ADT backbone and continue the selected ARPI until progression or intolerance."],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "CHAARTED", "match": True},
                {"trial": "ARASENS", "match": nccn["fit_for_docetaxel"]},
                {"trial": "CHART", "match": nccn["rezvilutamide_candidate"]},
                {"trial": "AKEEGA BRCA2 mCSPC", "match": nccn["prefer_akeega"]},
            ],
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": "High-volume metastatic hormone-sensitive pathway.",
                "bone_health_bundle": {
                    "dxa_baseline_done": str(payload.get("dxa_baseline_done", "0")) == "1",
                    "calcium_vitd_started": str(payload.get("calcium_vitd_started", "0")) == "1",
                    "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
                },
            },
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad metastásica sensible a la castración de alto volumen",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "El alto volumen de enfermedad obliga a priorizar intensificación sistémica y evita estrategias locales aisladas como vía principal.",
                f"Aptitud para docetaxel: {'sí' if nccn['fit_for_docetaxel'] else 'no'}.",
                "La vía de precisión con niraparib más abiraterona solo debe activarse si existe BRCA2 trazable por gen, fuente y fecha de ensayo.",
                "Las comorbilidades neurológicas, cardiovasculares y hepáticas redefinen qué triplete o doblete es clínicamente más seguro.",
            ],
            alternatives=[
                "Triplete con docetaxel si el estado funcional y la reserva orgánica lo permiten.",
                "Doblete con inhibidor del receptor androgénico cuando la quimioterapia no es apropiada o el perfil de toxicidad obliga a desescalar.",
            ],
            shared_decision_message=(
                "La selección final debe equilibrar urgencia oncológica, beneficio esperado de intensificación, fragilidad clínica y voluntad del paciente ante toxicidad hematológica, neuropatía y monitorización estrecha."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 confirma la necesidad de intensificación en enfermedad de alto volumen y ayuda a evitar subtratamiento."
            ),
        )

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower():
                return item.get("evidence", "")
        return ""
