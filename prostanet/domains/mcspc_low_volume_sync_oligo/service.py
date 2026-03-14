from __future__ import annotations

from precision_medicine import evaluate_patient_for_mhspc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.mcspc_low_volume_sync_oligo.rules_eau import evaluate_mcspc_low_volume_eau
from prostanet.domains.mcspc_low_volume_sync_oligo.rules_nccn import evaluate_mcspc_low_volume
from prostanet.domains.mcspc_low_volume_sync_oligo.schemas import MCSPC_LOW_VOLUME_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


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
        treatments = []
        if nccn["rt_primary_candidate"]:
            treatments.append({"name": "RT al primario", "priority": "preferred", "notes": self._note_for(legacy, "Radioterapia al Primario")})
        if nccn["prefer_akeega"]:
            treatments.append({"name": "ADT + Niraparib + Abiraterone", "priority": "preferred", "notes": "Ruta de precisión para BRCA2 trazable en mCSPC."})
        if nccn["prefer_enzalutamide"]:
            treatments.append({"name": "ADT + Enzalutamida", "priority": "preferred", "notes": self._note_for(legacy, "Enzalutamida")})
        treatments.append({"name": "ADT + Apalutamida", "priority": "eligible", "notes": self._note_for(legacy, "Apalutamida")})
        if nccn["rezvilutamide_candidate"]:
            treatments.append({"name": "ADT + Rezvilutamida", "priority": "eligible", "notes": "Opción soportada por EAU 2026 en enfermedad sensible a la castración."})
        if nccn["prefer_abiraterone"]:
            treatments.append({"name": "ADT + Abiraterona", "priority": "eligible", "notes": self._note_for(legacy, "Abiraterona")})
        if str(payload.get("metastasis_site", "Bone")) == "Bone":
            treatments.append({"name": "Calcio + vitamina D", "priority": "selected_candidate", "notes": "Bundle basal de salud ósea."})
            if not nccn["bone_protection_started"]:
                treatments.append({"name": "Denosumab o ácido zoledrónico", "priority": "selected_candidate", "notes": "Considerar si la carga ósea y el riesgo estructural lo justifican."})
        case_summary = (
            "El caso corresponde a enfermedad metastásica sensible a la castración de bajo volumen u oligometastásica sincrónica. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 la describe como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 la compara con {eau['label']}."
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=treatments,
            not_recommended=["Do not position docetaxel monotherapy as a default for low-volume disease.", "Avoid presenting low-volume disease as equivalent to high-volume triplet-first disease."],
            missing_critical_inputs=[
                field
                for field in ["molecular_assay_source", "molecular_assay_date"]
                if nccn["prefer_akeega"] and str(payload.get(field, "")).strip() == ""
            ],
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=["Keep ADT backbone continuous with the selected ARPI.", "If RT to the primary is selected, integrate it with systemic therapy timing."],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "STAMPEDE H", "match": True},
                {"trial": "ARCHES", "match": True},
                {"trial": "CHART", "match": nccn["rezvilutamide_candidate"]},
                {"trial": "AKEEGA BRCA2 mCSPC", "match": nccn["prefer_akeega"]},
            ],
            applicability_badge="guideline-consistent",
            report_sections={"summary": "Low-volume metastatic hormone-sensitive pathway."},
        )
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad metastásica sensible a la castración de bajo volumen",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "El bajo volumen no equivale a enfermedad localizada; sigue requiriendo intensificación sistémica adecuada al contexto.",
                f"Candidato a radioterapia al tumor primario: {'sí' if nccn['rt_primary_candidate'] else 'no'}.",
                "La salud ósea basal debe documentarse antes de prolongar terapia sistémica en enfermedad metastásica.",
                "La selección entre enzalutamida, apalutamida y abiraterona se ajusta por comorbilidades neurológicas y hepáticas.",
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
