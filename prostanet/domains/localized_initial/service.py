from __future__ import annotations

from clinical_scores import briganti_lni, capra_score, kattan_organ_confined, partin_tables

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.localized_initial.rules_eau import classify_eau
from prostanet.domains.localized_initial.rules_nccn import active_surveillance_position, classify_nccn
from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class LocalizedInitialService:
    module_id = "localized_initial"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return LOCALIZED_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        missing = self._missing(payload, ["psa", "clinical_tstage", "isup_grade", "num_cores_positive", "total_cores"])
        nccn = classify_nccn(payload)
        eau = classify_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        capra = capra_score(payload)
        briganti = briganti_lni(payload)
        partin = partin_tables(payload)
        msk = kattan_organ_confined(payload)
        as_position = active_surveillance_position(payload, nccn["risk_group"])

        # Multi-protocol AS eligibility via active_surveillance module
        as_multi_eligibility = []
        try:
            from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
            as_multi_eligibility = ActiveSurveillanceService.check_eligibility(payload, "localized_initial")
            # Enrich as_position with multi-protocol results
            eligible_protocols = [e.protocol for e in as_multi_eligibility if e.eligible]
            if eligible_protocols:
                as_position["multi_protocol_eligible"] = eligible_protocols
                as_position["multi_protocol_details"] = [
                    {"protocol": e.protocol, "eligible": e.eligible, "criteria_met": e.criteria_met, "criteria_failed": e.criteria_failed}
                    for e in as_multi_eligibility
                ]
            else:
                as_position["multi_protocol_eligible"] = []
                as_position["multi_protocol_details"] = [
                    {"protocol": e.protocol, "eligible": False, "criteria_failed": e.criteria_failed}
                    for e in as_multi_eligibility
                ]
        except Exception:
            pass

        urinary_qol = float(payload.get("baseline_urinary_qol", 0) or 0)
        sexual_qol = float(payload.get("baseline_sexual_qol", 0) or 0)
        bowel_qol = float(payload.get("baseline_bowel_qol", 0) or 0)
        genomic_result = str(payload.get("genomic_classifier_result", "No aplica"))
        prior_pirads = str(payload.get("prior_mpmri_pirads_score", "desconocido") or "desconocido")
        adverse_variant_type = self._adverse_variant_type(payload)
        predict_ready = all(
            payload.get(field) not in (None, "")
            for field in ("age", "psa", "clinical_tstage", "isup_grade", "life_expectancy_years")
        )

        eligible_treatments = self._eligible_treatments(
            nccn["risk_group"],
            float(payload.get("life_expectancy_years", 15) or 15),
            as_position,
            urinary_qol,
            sexual_qol,
            bowel_qol,
            genomic_result,
            adverse_variant_type,
        )
        not_recommended = self._not_recommended(nccn["risk_group"], as_position, genomic_result, adverse_variant_type, prior_pirads, payload)
        durations = self._durations(nccn["risk_group"])
        applicability = as_position["status"] if as_position["eligible"] else ("not_recommended" if as_position.get("requires_escalation") else "guideline-consistent")

        psa = float(payload.get("psa", 0) or 0)
        clinical_tstage = str(payload.get("clinical_tstage", "T1c")).upper()
        isup_grade = int(payload.get("isup_grade", 1) or 1)
        num_cores_positive = int(payload.get("num_cores_positive", 0) or 0)
        total_cores = int(payload.get("total_cores", 0) or 0)
        life_expectancy = float(payload.get("life_expectancy_years", 15) or 15)
        case_summary = (
            f"El caso corresponde a enfermedad localizada o regional sin metástasis a distancia, "
            f"con antígeno prostático específico de {psa:g} ng/mL, estadio clínico {clinical_tstage}, "
            f"grupo de grado {isup_grade} de la Sociedad Internacional de Patología Urológica y "
            f"{num_cores_positive}/{total_cores} cilindros positivos. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 lo ubica en {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo compara como {eau['label']}."
        )

        report_sections = {
            "summary": f"NCCN 5.2026 classifies this patient as {nccn['label']}. EAU 2026 comparison: {eau['label']}.",
            "risk_features": nccn["reasons"],
            "active_surveillance": as_position["summary"],
            "nomograms": {
                "capra": capra,
                "briganti": briganti,
                "partin": partin,
                "mskcc_preop": msk,
                "predict_prostate_ready": predict_ready,
                "prior_mpmri_pirads_score": prior_pirads,
                "adverse_histology_variant_type": adverse_variant_type,
            },
        }

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
                "treatment_intent": eau["treatment_intent"],
                "comparison": comparison,
            },
            eligible_treatments=eligible_treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=missing,
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "ProtecT", "match": nccn["risk_group"] in {"LOW", "FAVORABLE INTERMEDIATE"}},
                {"trial": "SPCG-4", "match": nccn["risk_group"] in {"FAVORABLE INTERMEDIATE", "UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH"}},
            ],
            applicability_badge=applicability,
            report_sections=report_sections,
        )
        if as_position.get("requires_escalation"):
            result["state_classification_override"] = "unsupported_or_escalate"
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de manejo inicial localizado",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                *nccn["reasons"],
                as_position["summary"],
                f"Esperanza de vida estimada: {life_expectancy:g} años.",
                f"Puntaje pronóstico CAPRA: {capra.get('score', 'no disponible') if isinstance(capra, dict) else capra}.",
                f"Riesgo ganglionar según Briganti: {briganti.get('risk_pct', 'no disponible') if isinstance(briganti, dict) else briganti}.",
                f"Tablas de Partin: probabilidad de organo-confinamiento {partin.get('oc_prob', 'no disponible')}% y riesgo ganglionar {partin.get('lni_prob', 'no disponible')}%.",
                f"Nomograma preoperatorio MSKCC: organo-confinamiento {msk.get('probabilidad_organo_confinado', msk.get('probabilidad_raw', 'no disponible'))}%.",
                (
                    f"PI-RADS previo documentado: {prior_pirads}."
                    if prior_pirads != "desconocido"
                    else "Falta documentar el PI-RADS de la resonancia magnética previa, lo que reduce la solidez de la decisión en vigilancia activa."
                ),
                (
                    f"Variante histológica adversa documentada: {adverse_variant_type}."
                    if adverse_variant_type not in {"none", ""}
                    else "No se documenta una variante histológica adversa adicional más allá de patrón cribiforme o carcinoma intraductal."
                ),
                "PREDICT Prostate debe correrse cuando las entradas estan completas para cuantificar beneficio absoluto y reforzar la decision compartida."
                if predict_ready
                else "PREDICT Prostate aun no puede correrse con total trazabilidad porque faltan entradas estructuradas de counseling.",
                "Los PROs basales y la señal genómica modulan la conversación entre vigilancia activa, cirugía y radioterapia cuando el caso es limítrofe.",
            ],
            alternatives=[
                "Prostatectomía radical o radioterapia definitiva según candidabilidad quirúrgica, preferencia del paciente y disponibilidad local.",
                "Observación clínica cuando la esperanza de vida sea limitada o la carga de comorbilidad reduzca el beneficio de un tratamiento local definitivo.",
            ],
            shared_decision_message=(
                "La decisión final debe integrar la expectativa de vida, la disposición a vigilancia activa, la tolerancia a terapia local definitiva y la relevancia de preservar función urinaria, sexual y calidad de vida."
            ),
            comparison_message=(
                (
                    "La comparación con la Asociación Europea de Urología (EAU) 2026 coincide en la franja clínica principal "
                    "y ayuda a definir si el caso debe orientarse a vigilancia activa, tratamiento local definitivo o manejo intensificado."
                    if comparison["status"] == "coincide"
                    else "La comparación con la Asociación Europea de Urología (EAU) 2026 muestra una diferencia de guías y debe revisarse junto con la elegibilidad para vigilancia activa, tratamiento local definitivo o intensificación."
                )
            ),
        )

    @staticmethod
    def _missing(payload: dict, required_fields: list[str]) -> list[str]:
        return [field for field in required_fields if str(payload.get(field, "")).strip() == ""]

    @staticmethod
    def _eligible_treatments(
        nccn_group: str,
        life_expectancy: float,
        as_position: dict,
        urinary_qol: float,
        sexual_qol: float,
        bowel_qol: float,
        genomic_result: str,
        adverse_variant_type: str,
    ) -> list[dict]:
        treatments: list[dict] = []
        if as_position.get("requires_escalation"):
            return [
                {
                    "name": "Revisión por uropatología y tumor board",
                    "priority": "preferente",
                    "notes": "La variante histológica adversa obliga a revisión experta y definición individualizada de estadificación y tratamiento definitivo.",
                },
                {
                    "name": "Terapia local definitiva tras revisión experta",
                    "priority": "eligible",
                    "notes": "La vigilancia activa no debe plantearse como conducta principal cuando existe una variante histológica adversa de muy alto riesgo.",
                },
            ]
        if as_position["eligible"]:
            treatments.append({"name": "Active surveillance", "priority": as_position["status"], "notes": as_position["summary"]})
        if nccn_group == "LOW":
            if life_expectancy < 10:
                treatments.append({"name": "Observation", "priority": "preferred", "notes": "Observation is preferred below 10-year life expectancy."})
            treatments.append({"name": "Definitive RT", "priority": "eligible", "notes": "Consider when surveillance is not acceptable, especially if urinary baseline is already fragile and surgery would be less attractive." if urinary_qol < 60 else "Consider when surveillance is not acceptable."})
            treatments.append({"name": "Radical prostatectomy", "priority": "eligible", "notes": "For appropriate surgical candidates after shared decision-making, particularly if bowel baseline disfavors RT." if bowel_qol < 60 else "For appropriate surgical candidates after shared decision-making."})
        elif nccn_group == "FAVORABLE INTERMEDIATE":
            treatments.extend([
                {"name": "Definitive RT", "priority": "eligible", "notes": "Reasonable standard option for FIR disease, especially if sexual baseline preservation is a major concern." if sexual_qol > 60 else "Reasonable standard option for FIR disease."},
                {"name": "Radical prostatectomy", "priority": "eligible", "notes": "Standard option for suitable surgical candidates." if bowel_qol >= 60 else "Standard option for suitable surgical candidates, particularly if baseline bowel function makes RT less attractive."},
            ])
            if life_expectancy <= 10:
                treatments.append({"name": "Observation", "priority": "preferred", "notes": "Preferred in selected men with 5-10 years life expectancy."})
        elif nccn_group == "UNFAVORABLE INTERMEDIATE":
            treatments.extend([
                {"name": "RT + ADT", "priority": "preferred", "notes": "Short-course ADT should be paired with RT in most eligible patients."},
                {"name": "Radical prostatectomy", "priority": "eligible", "notes": "Use in properly selected patients with pelvic nodal planning as indicated."},
            ])
        elif nccn_group == "HIGH":
            treatments.extend([
                {"name": "EBRT + ADT", "priority": "preferred", "notes": "Long-course ADT intensification path."},
                {"name": "Radical prostatectomy + PLND", "priority": "eligible", "notes": "For selected surgical candidates in experienced centers."},
            ])
        elif nccn_group == "VERY HIGH":
            treatments.extend([
                {"name": "EBRT + ADT", "priority": "preferred", "notes": "Use long-course ADT and intensification for eligible men."},
                {"name": "EBRT + ADT + abiraterone", "priority": "preferred", "notes": "Systemic intensification path for very-high-risk disease."},
                {"name": "Radical prostatectomy + PLND", "priority": "selected_candidate", "notes": "Reserved for carefully chosen surgical candidates."},
            ])
        else:
            treatments.extend([
                {"name": "Definitive RT + ADT", "priority": "preferred", "notes": "Regional N1M0 pathway."},
                {"name": "Systemic intensification", "priority": "eligible", "notes": "Use in eligible regional node-positive disease per NCCN 2026 pathway."},
            ])
        if genomic_result == "Alto":
            for item in treatments:
                if item["name"] == "Active surveillance":
                    item["priority"] = "not_preferred"
                    item["notes"] = "A high genomic classifier signal lowers confidence in surveillance despite otherwise favorable clinicopathologic features."
        if adverse_variant_type == "ductal_predominant":
            for item in treatments:
                if item["name"] == "Active surveillance":
                    item["priority"] = "not_preferred"
                    item["notes"] = "Ductal-predominant histology should move the discussion away from routine active surveillance."
        return treatments

    @staticmethod
    def _not_recommended(
        nccn_group: str,
        as_position: dict,
        genomic_result: str,
        adverse_variant_type: str,
        prior_pirads: str,
        payload: dict,
    ) -> list[str]:
        items = []
        if nccn_group in {"UNFAVORABLE INTERMEDIATE", "HIGH", "VERY HIGH", "REGIONAL N1M0"}:
            items.append("Active surveillance should not be presented as a standard management strategy.")
        if not as_position["eligible"] and nccn_group == "FAVORABLE INTERMEDIATE":
            items.append("Avoid presenting favorable-intermediate AS as equivalent to low-risk surveillance.")
        if genomic_result == "Alto":
            items.append("Avoid downplaying a high genomic classifier result when choosing between surveillance and definitive local therapy.")
        if adverse_variant_type not in {"", "none"}:
            items.append("No presentar vigilancia activa como equivalente a terapia definitiva cuando existe una variante histológica adversa específica.")
        if prior_pirads in {"4", "5"} and str(payload.get("prior_mpmri_targeted_biopsy_status", "desconocido")) != "si":
            items.append("No sostener vigilancia activa con PI-RADS 4 o 5 sin biopsia dirigida documentada.")
        return items

    @staticmethod
    def _durations(nccn_group: str) -> list[str]:
        mapping = {
            "UNFAVORABLE INTERMEDIATE": ["If RT is selected, pair with ADT for 4-6 months."],
            "HIGH": ["If EBRT is selected, use ADT for 18-36 months.", "If EBRT + brachytherapy is used, 12 months may be considered."],
            "VERY HIGH": ["If EBRT is selected, use ADT for 18-36 months.", "Systemic intensification with abiraterone can be considered for eligible patients."],
            "REGIONAL N1M0": ["Long-course ADT is usually required with definitive RT.", "Escalate systemic therapy in eligible patients."],
        }
        return mapping.get(nccn_group, [])

    @staticmethod
    def _adverse_variant_type(payload: dict) -> str:
        explicit = str(payload.get("adverse_histology_variant_type", "none") or "none").strip()
        if explicit and explicit != "none":
            return explicit
        if str(payload.get("rare_histology_variant", "0")) == "1":
            return "other_aggressive_unspecified"
        return "none"
