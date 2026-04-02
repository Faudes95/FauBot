from __future__ import annotations

from clinical_scores import briganti_lni, capra_score, kattan_organ_confined, partin_tables

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.localized_initial.rules_eau import classify_eau
from prostanet.domains.localized_initial.rules_nccn import active_surveillance_position, classify_nccn
from prostanet.domains.localized_initial.schemas import LOCALIZED_SCHEMA
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
)
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
        ranked_treatments = [
            self._hydrate_localized_treatment_item(
                item,
                rank=index,
                risk_group=nccn["risk_group"],
                as_position=as_position,
            )
            for index, item in enumerate(eligible_treatments, start=1)
        ]
        grouped: dict[str, list[dict]] = {}
        family_order: list[str] = []
        for item in ranked_treatments:
            family_code = str(item.get("family_code") or "observation_family")
            grouped.setdefault(family_code, []).append(item)
            if family_code not in family_order:
                family_order.append(family_code)
        preferred_family_order = self._family_order_for_localized(nccn["risk_group"], as_position, family_order)
        family_profiles: dict[str, dict] = {}
        if grouped.get("active_surveillance_family"):
            family_profiles["active_surveillance_family"] = build_family_profile(
                family_code="active_surveillance_family",
                ordered_regimens=grouped["active_surveillance_family"],
                context={
                    "eligibility_status": "eligible" if as_position.get("eligible") else "conditional",
                    "caution_drivers": [as_position.get("summary")] if as_position.get("status") in {"selected_candidate", "not_preferred"} else [],
                    "winner_reason": "La vigilancia activa solo lidera cuando la biología, la RM/biopsia confirmatoria y la esperanza de vida sostienen esa vía.",
                    "why_not_preferred": "Pierde prioridad con histología adversa, MRI de mayor riesgo o expectativa de vida limitada.",
                },
            )
        if grouped.get("radiotherapy_family"):
            family_profiles["radiotherapy_family"] = build_family_profile(
                family_code="radiotherapy_family",
                ordered_regimens=grouped["radiotherapy_family"],
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": "La familia radioterapia se ordena por grupo de riesgo y necesidad de ADT corta o prolongada.",
                },
            )
        if grouped.get("multimodal_local_family"):
            family_profiles["multimodal_local_family"] = build_family_profile(
                family_code="multimodal_local_family",
                ordered_regimens=grouped["multimodal_local_family"],
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": "La intensificación multimodal local domina cuando el riesgo muy alto o regional exige control local y sistémico combinados.",
                },
            )
        if grouped.get("surgery_family"):
            family_profiles["surgery_family"] = build_family_profile(
                family_code="surgery_family",
                ordered_regimens=grouped["surgery_family"],
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": "La cirugía permanece visible para candidatos apropiados, pero su prioridad depende del riesgo y del contexto funcional basal.",
                },
            )
        if grouped.get("observation_family"):
            family_profiles["observation_family"] = build_family_profile(
                family_code="observation_family",
                ordered_regimens=grouped["observation_family"],
                context={
                    "eligibility_status": "eligible",
                    "winner_reason": "La observación solo sube cuando la expectativa de vida o el balance beneficio-riesgo reducen la utilidad de terapia local definitiva.",
                },
            )
        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=preferred_family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "observation_family",
            field_values=payload,
        )
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or ranked_treatments,
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=missing,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="localized_initial",
            field_values=payload,
            monitoring_package=active_monitoring_package,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
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
            eligible_treatments=comparative_bundle.get("eligible_treatments") or ranked_treatments,
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
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or nccn["label"],
                "confidence_category": "vigilada" if missing else "alta",
                "requires_human_review": bool(as_position.get("requires_escalation")),
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        result["variant_ranking"] = ((family_profiles.get("active_surveillance_family") or {}).get("variant_ranking") or {})
        result["care_setting_contract"] = {
            "care_setting": "curative_local",
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
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
                    "name": "Revisión por uropatología y comité oncológico",
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
            treatments.append({"name": "Vigilancia activa", "priority": as_position["status"], "notes": as_position["summary"]})
        if nccn_group == "LOW":
            if life_expectancy < 10:
                treatments.append({"name": "Observación clínica", "priority": "preferred", "notes": "La observación clínica suele ser preferente cuando la esperanza de vida es menor de 10 años."})
            treatments.append({"name": "Radioterapia definitiva", "priority": "eligible", "notes": "Considérese cuando la vigilancia activa no es aceptable, especialmente si la línea basal urinaria ya es frágil y la cirugía sería menos atractiva." if urinary_qol < 60 else "Considérese cuando la vigilancia activa no es aceptable."})
            treatments.append({"name": "Prostatectomía radical", "priority": "eligible", "notes": "Para candidatos quirúrgicos apropiados tras decisión compartida, sobre todo si la función intestinal basal hace menos atractiva la radioterapia." if bowel_qol < 60 else "Para candidatos quirúrgicos apropiados tras decisión compartida."})
        elif nccn_group == "FAVORABLE INTERMEDIATE":
            treatments.extend([
                {"name": "Radioterapia definitiva", "priority": "eligible", "notes": "Opción estándar razonable para enfermedad intermedia favorable, especialmente si preservar la función sexual basal es prioritario." if sexual_qol > 60 else "Opción estándar razonable para enfermedad intermedia favorable."},
                {"name": "Prostatectomía radical", "priority": "eligible", "notes": "Opción estándar para candidatos quirúrgicos apropiados." if bowel_qol >= 60 else "Opción estándar para candidatos quirúrgicos apropiados, particularmente si la función intestinal basal hace menos atractiva la radioterapia."},
            ])
            if life_expectancy <= 10:
                treatments.append({"name": "Observación clínica", "priority": "preferred", "notes": "Puede ser preferente en hombres seleccionados con esperanza de vida de 5 a 10 años."})
        elif nccn_group == "UNFAVORABLE INTERMEDIATE":
            treatments.extend([
                {"name": "Radioterapia + terapia de privación androgénica", "priority": "preferred", "notes": "La terapia de privación androgénica de curso corto debe acompañar a la radioterapia en la mayoría de los pacientes elegibles."},
                {"name": "Prostatectomía radical", "priority": "eligible", "notes": "Úsese en pacientes seleccionados apropiadamente, con planeación ganglionar pélvica cuando esté indicada."},
            ])
        elif nccn_group == "HIGH":
            treatments.extend([
                {"name": "Radioterapia externa + terapia de privación androgénica", "priority": "preferred", "notes": "Ruta de intensificación con terapia de privación androgénica prolongada."},
                {"name": "Prostatectomía radical + disección ganglionar pélvica", "priority": "eligible", "notes": "Para candidatos quirúrgicos seleccionados en centros con experiencia."},
            ])
        elif nccn_group == "VERY HIGH":
            treatments.extend([
                {"name": "Radioterapia externa + terapia de privación androgénica", "priority": "preferred", "notes": "Úsese terapia de privación androgénica prolongada e intensificación en hombres elegibles."},
                {"name": "Radioterapia externa + terapia de privación androgénica + abiraterona", "priority": "preferred", "notes": "Ruta de intensificación sistémica para enfermedad de muy alto riesgo."},
                {"name": "Prostatectomía radical + disección ganglionar pélvica", "priority": "selected_candidate", "notes": "Reservada para candidatos quirúrgicos cuidadosamente seleccionados."},
            ])
        else:
            treatments.extend([
                {"name": "Radioterapia definitiva + terapia de privación androgénica", "priority": "preferred", "notes": "Ruta preferente para enfermedad regional N1M0."},
                {"name": "Intensificación sistémica", "priority": "eligible", "notes": "Úsese en enfermedad regional con ganglios positivos cuando el paciente sea elegible según NCCN 2026."},
            ])
        if genomic_result == "Alto":
            for item in treatments:
                if item["name"] == "Vigilancia activa":
                    item["priority"] = "not_preferred"
                    item["notes"] = "Una señal genómica de alto riesgo reduce la confianza en vigilancia activa pese a características clinicopatológicas aparentemente favorables."
        if adverse_variant_type == "ductal_predominant":
            for item in treatments:
                if item["name"] == "Vigilancia activa":
                    item["priority"] = "not_preferred"
                    item["notes"] = "El predominio ductal debe alejar la conversación de una vigilancia activa rutinaria."
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
            items.append("La vigilancia activa no debe presentarse como estrategia estándar de manejo en este escenario.")
        if not as_position["eligible"] and nccn_group == "FAVORABLE INTERMEDIATE":
            items.append("Evite presentar la vigilancia activa en intermedio favorable como equivalente a la de bajo riesgo.")
        if genomic_result == "Alto":
            items.append("No minimice un clasificador genómico alto al elegir entre vigilancia y terapia local definitiva.")
        if adverse_variant_type not in {"", "none"}:
            items.append("No presentar vigilancia activa como equivalente a terapia definitiva cuando existe una variante histológica adversa específica.")
        if prior_pirads in {"4", "5"} and str(payload.get("prior_mpmri_targeted_biopsy_status", "desconocido")) != "si":
            items.append("No sostener vigilancia activa con PI-RADS 4 o 5 sin biopsia dirigida documentada.")
        return items

    @staticmethod
    def _durations(nccn_group: str) -> list[str]:
        mapping = {
            "UNFAVORABLE INTERMEDIATE": ["Si se selecciona radioterapia, acompáñela con terapia de privación androgénica por 4 a 6 meses."],
            "HIGH": ["Si se selecciona radioterapia externa, use terapia de privación androgénica por 18 a 36 meses.", "Si se utiliza radioterapia externa con braquiterapia, pueden considerarse 12 meses en pacientes seleccionados."],
            "VERY HIGH": ["Si se selecciona radioterapia externa, use terapia de privación androgénica por 18 a 36 meses.", "Puede considerarse intensificación sistémica con abiraterona en pacientes elegibles."],
            "REGIONAL N1M0": ["La terapia de privación androgénica prolongada suele ser necesaria junto con radioterapia definitiva.", "Escale terapia sistémica en pacientes elegibles."],
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

    @staticmethod
    def _family_order_for_localized(nccn_group: str, as_position: dict, discovered: list[str]) -> list[str]:
        if nccn_group == "LOW":
            preferred = ["active_surveillance_family", "observation_family", "radiotherapy_family", "surgery_family"]
            if as_position.get("status") == "observation_preferred":
                preferred = ["observation_family", "active_surveillance_family", "radiotherapy_family", "surgery_family"]
        elif nccn_group == "FAVORABLE INTERMEDIATE":
            preferred = ["radiotherapy_family", "surgery_family", "active_surveillance_family", "observation_family"]
        elif nccn_group in {"UNFAVORABLE INTERMEDIATE", "HIGH"}:
            preferred = ["radiotherapy_family", "surgery_family", "multimodal_local_family", "active_surveillance_family", "observation_family"]
        else:
            preferred = ["multimodal_local_family", "radiotherapy_family", "surgery_family", "observation_family", "active_surveillance_family"]
        for family_code in discovered:
            if family_code not in preferred:
                preferred.append(family_code)
        return preferred

    @staticmethod
    def _hydrate_localized_treatment_item(
        item: dict[str, Any],
        *,
        rank: int,
        risk_group: str,
        as_position: dict,
    ) -> dict[str, Any]:
        name = str(item.get("name") or "").strip()
        notes = str(item.get("notes") or "").strip()
        priority = str(item.get("priority") or "eligible").strip()
        lower_name = name.lower()
        regimen_code = "OBSERVATION"
        family_code = "observation_family"
        description = notes or name
        dose = ""
        route = ""
        schedule = ""
        duration = ""
        component_drugs: list[dict[str, Any]] = []
        therapy_class = ""
        evidence_tags: list[str] = []

        if "vigilancia activa" in lower_name:
            regimen_code = "ACTIVE_SURVEILLANCE"
            family_code = "active_surveillance_family"
            route = "Seguimiento estructurado"
            schedule = "PSA seriado + mpMRI + biopsia confirmatoria"
            duration = "Continuo mientras no exista upgrade o progresión"
            description = notes or "Seguimiento estructurado para evitar tratamiento local inmediato sin perder ventana curativa."
        elif "observación clínica" in lower_name:
            regimen_code = "OBSERVATION"
            family_code = "observation_family"
            route = "Seguimiento clínico"
            schedule = "PSA seriado y reevaluación por expectativa de vida/comorbilidad"
            description = notes or "Observación clínica cuando el beneficio de tratamiento local definitivo es bajo."
        elif "prostatectomía radical" in lower_name:
            regimen_code = "RP_PLND" if "ganglionar" in lower_name else "RADICAL_PROSTATECTOMY"
            family_code = "surgery_family"
            route = "Cirugía"
            schedule = "Evento único con seguimiento posoperatorio"
            description = notes or "Tratamiento quirúrgico local definitivo."
        elif "abiraterona" in lower_name:
            regimen_code = "RT_ADT_ABIRATERONE" if risk_group == "VERY HIGH" else "REGIONAL_RT_ADT_ABIRATERONE"
            family_code = "multimodal_local_family"
            dose = "RT definitiva + ADT prolongada + abiraterona"
            route = "Radioterapia externa + Sistémica oral"
            schedule = "RT + ADT prolongada con intensificación"
            duration = "ADT 18-36 meses; abiraterona según elegibilidad"
            description = notes or "Intensificación multimodal local para riesgo muy alto o regional."
        elif "radioterapia" in lower_name:
            family_code = "radiotherapy_family"
            if "privación androgénica" in lower_name or "adt" in lower_name:
                regimen_code = "RT_SHORT_ADT" if risk_group == "UNFAVORABLE INTERMEDIATE" else "RT_LONG_ADT"
                dose = "Radioterapia definitiva + ADT"
                route = "Radioterapia externa + Supresión androgénica"
                schedule = "RT diaria + ADT concomitante"
                duration = "4-6 meses" if risk_group == "UNFAVORABLE INTERMEDIATE" else "18-36 meses"
            else:
                regimen_code = "DEFINITIVE_RT"
                dose = "RT definitiva según técnica elegida"
                route = "Radioterapia externa"
                schedule = "20-39 fracciones según protocolo"
            description = notes or "Tratamiento local definitivo con radioterapia."
        elif "uropatología" in lower_name or "comité oncológico" in lower_name:
            regimen_code = "RESTAGING"
            family_code = "observation_family"
            route = "Revisión multidisciplinaria"
            schedule = "Confirmación histológica y board oncológico"
            description = notes or "Revisión experta antes de cerrar terapia definitiva."

        eligibility_status = (
            "preferred"
            if priority in {"preferred", "preferente", "observation_preferred"}
            else "eligible_with_caution"
            if priority in {"selected_candidate", "not_preferred"}
            else "eligible_nonpreferred"
        )
        why = [notes] if notes else []
        if family_code == "active_surveillance_family" and as_position.get("status") != "preferred":
            why.append(as_position.get("summary") or "La vigilancia activa sigue condicionada por la selección clínica fina.")
        return build_ranked_option(
            name=name,
            regimen_code=regimen_code,
            rank=rank,
            priority="preferred" if eligibility_status == "preferred" else "eligible",
            eligibility_status=eligibility_status,
            family_code=family_code,
            molecule_or_backbone=name,
            description=description,
            dose=dose,
            route=route,
            schedule=schedule,
            duration=duration,
            component_drugs=component_drugs,
            metadata_source="guideline_backbone",
            therapy_class=therapy_class,
            evidence_tags=evidence_tags,
            notes=notes,
            why_this_rank=why,
            selection_rationale=why,
            caution_flags=[] if eligibility_status == "preferred" else why[:1],
        )
