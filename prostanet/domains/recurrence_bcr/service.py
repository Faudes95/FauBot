from __future__ import annotations

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.patient_tracking.arpi_selection_engine import (
    build_arpi_capture_contract,
    candidate_regimens_for_state,
    evaluate_arpi_candidate,
)
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
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
        durations = []
        not_recommended = []
        trials = []
        missing_inputs = [field for field in ["psa_current", "psadt_months"] if str(payload.get(field, "")).strip() == ""]
        family_profiles: dict[str, dict] = {}
        family_order: list[str] = []
        salvage_variants: list[dict] = []
        local_mdt_variants: list[dict] = []
        arpi_variants: list[dict] = []
        observation_variants: list[dict] = []
        confidence_low = psma_impact.get("confidence") == "low"
        psma_pattern = str(psma_impact.get("clinical_pattern") or "").strip()
        systemic_redirect = psma_pattern == "diseminado"
        salvage_feasible = bool(nccn.get("salvage_local_feasible"))
        local_salvage_candidate = bool(nccn.get("local_salvage_candidate"))
        psma_pending = bool(nccn.get("psma_pet_recommended")) and not bool(nccn.get("psma_pet_done"))
        arpi_candidates = candidate_regimens_for_state(self.module_id, payload)
        arpi_capture_contract = build_arpi_capture_contract(
            self.module_id,
            payload,
            candidate_regimens=arpi_candidates,
        )
        missing_inputs.extend(list(arpi_capture_contract.get("arpi_missing_inputs") or []))
        missing_inputs.extend(list(arpi_capture_contract.get("arpi_stale_inputs") or []))
        missing_inputs = list(dict.fromkeys(item for item in missing_inputs if item))

        if psma_pending:
            observation_variants.append(
                build_ranked_option(
                    name="Estadificación de rescate guiada por PET/CT con PSMA",
                    regimen_code="PSMA_RESTAGING",
                    rank=len(observation_variants) + 1,
                    priority="eligible",
                    eligibility_status="eligible_with_caution",
                    family_code="observation_family",
                    molecule_or_backbone="PSMA-PET de rescate",
                    description="La imagen dirigida debe realizarse cuando cambia la estrategia de salvage o redirige fuera de rescate local.",
                    route="Imagen molecular",
                    schedule=nccn.get("psma_pet_reason") or "PET/CT PSMA antes de cerrar la vía de salvage o intensificación sistémica.",
                    metadata_source="guideline_backbone",
                    why_this_rank=[nccn.get("psma_pet_reason") or "La PSMA cambia la decisión cuando el rescate local no es trivial."],
                    selection_rationale=[nccn.get("psma_pet_reason") or "La PSMA puede reordenar salvage, MDT o redirección sistémica."],
                )
            )

        if nccn["label"] == "BCR2 N0M0":
            if nccn["enza_match"]:
                arpi_meta = evaluate_arpi_candidate(
                    self.module_id,
                    payload,
                    "ADT_ENZALUTAMIDE",
                    candidate_regimens=arpi_candidates,
                )
                preferred = (
                    arpi_meta.get("eligibility_status") == "preferred"
                    and arpi_meta.get("preference_confidence") == "definitive"
                )
                notes = [
                    "Patrón de segunda recurrencia bioquímica de alto riesgo con imagen convencional M0 y sin opción pélvica curativa dirigida.",
                    str(arpi_meta.get("benefit_basis") or ""),
                ]
                notes.extend(list(arpi_meta.get("safety_rationale") or []))
                if arpi_meta.get("required_missing_fields"):
                    notes.append(
                        "La preferencia molecular sigue provisional hasta completar: "
                        + ", ".join(arpi_meta.get("required_missing_fields") or [])
                    )
                arpi_variants.append(
                    build_ranked_option(
                        name="Enzalutamida con o sin leuprorelina",
                        regimen_code="ADT_ENZALUTAMIDE",
                        rank=1,
                        priority="preferred" if preferred else "eligible",
                        eligibility_status=(
                            "preferred"
                            if preferred
                            else str(arpi_meta.get("eligibility_status") or "eligible_with_caution")
                        ),
                        family_code="arpi_family",
                        molecule_or_backbone="Enzalutamida",
                        notes=" ".join(item for item in notes if item),
                        why_this_rank=["La intensificación sistémica tipo EMBARK solo sube cuando ya no queda rescate local con intención curativa."],
                        selection_rationale=["El escenario cumple patrón BCR2 de alto riesgo no metastásico y la vía pélvica curativa ya no domina."],
                        benefit_basis=arpi_meta.get("benefit_basis"),
                        benefit_endpoint_used=arpi_meta.get("benefit_endpoint_used"),
                        benefit_maturity=arpi_meta.get("benefit_maturity"),
                        benefit_support=arpi_meta.get("benefit_support"),
                        safety_drivers_used=arpi_meta.get("safety_drivers_used"),
                        required_missing_fields=arpi_meta.get("required_missing_fields"),
                        stale_inputs=arpi_meta.get("stale_inputs"),
                        preference_confidence=arpi_meta.get("preference_confidence"),
                    )
                )
                trials.append({"trial": "EMBARK", "match": True})
                trials.append({"trial": "PRESTO / AFT-19", "match": bool(nccn["high_risk_bcr2"]), "reason": "Ensayo contextual para intensificacion finita de ADT en BCR M0 de alto riesgo."})
            not_recommended.extend([
                "No exponga opciones sistémicas de segunda recurrencia bioquímica cuando no se cumplen los criterios del escenario.",
                "No trate apalutamida más terapia de privación androgénica como opción rutinaria de segunda recurrencia bioquímica sin una ruta fuente equivalente a la base primaria de la guía.",
            ])
            if arpi_variants:
                family_profiles["arpi_family"] = build_family_profile(
                    family_code="arpi_family",
                    ordered_regimens=arpi_variants,
                    context={
                        "eligibility_status": (
                            "eligible"
                            if arpi_capture_contract.get("arpi_preference_readiness") == "ready"
                            else "conditional"
                        ),
                        "preference_drivers": ["Patrón EMBARK-like documentado", "No persiste una vía local curativa dominante"],
                        "missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
                        "stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
                        "winner_reason": "La familia ARPI solo lidera si el caso ya pertenece a segunda recurrencia bioquímica de alto riesgo sin vía local curativa.",
                        "why_not_preferred": "No debe adelantar salvage local cuando todavía existe una ruta pélvica con intención curativa.",
                    },
                )
                family_order.append("arpi_family")
            if observation_variants:
                family_profiles["observation_family"] = build_family_profile(
                    family_code="observation_family",
                    ordered_regimens=observation_variants,
                    context={
                        "eligibility_status": "conditional",
                        "missing_inputs": ["psma_pet_done"] if psma_pending else [],
                        "winner_reason": "La reestadificación sigue visible porque puede cambiar la magnitud de la intensificación o excluir focos aún rescatables.",
                    },
                )
                family_order.append("observation_family")
        elif nccn["label"] == "Post-RP recurrence":
            if salvage_feasible and not systemic_redirect:
                salvage_variants.append(
                    build_ranked_option(
                        name="Radioterapia de rescate temprana",
                        regimen_code="SALVAGE_RT_ALONE",
                        rank=1,
                        priority="preferred",
                        eligibility_status="preferred",
                        family_code="salvage_rt_family",
                        molecule_or_backbone="Radioterapia de rescate temprana",
                        description="Rescate del lecho prostático cuando la ventana local sigue abierta.",
                        dose="64-66 Gy al lecho prostático",
                        route="Radioterapia externa",
                        schedule="20-33 fracciones según planificación",
                        component_drugs=[{"drug_name": "Radioterapia de rescate", "dose": "64-66 Gy", "route": "Radioterapia externa", "schedule": "20-33 fracciones"}],
                        metadata_source="guideline_backbone",
                        evidence_tags=["RADICALS-RT", "RAVES", "ARTISTIC"],
                        notes="Use los umbrales de persistencia o recurrencia del antígeno prostático específico y el riesgo clínico.",
                        why_this_rank=["La ventana curativa post-RP sigue abierta y el rescate temprano tiene prioridad sobre esperar más umbral de PSA."],
                        selection_rationale=["El carril dominante es salvage local mientras no exista redirector sistémico explícito."],
                    )
                )
                salvage_variants.append(
                    build_ranked_option(
                        name="Radioterapia de rescate + ADT corta",
                        regimen_code="SALVAGE_RT_SHORT_HORMONE",
                        rank=2,
                        priority="eligible",
                        eligibility_status="eligible_nonpreferred",
                        family_code="salvage_rt_family",
                        molecule_or_backbone="Radioterapia de rescate + ADT corta",
                        description="Salvage RT con supresión androgénica corta tipo GETUG-AFU 16.",
                        dose="RT 66 Gy + goserelina 10.8 mg SC cada 3 meses",
                        route="Radioterapia externa + Subcutánea",
                        schedule="33 fracciones + 2 aplicaciones",
                        duration="6 meses",
                        component_drugs=[
                            {"drug_name": "Radioterapia de rescate", "dose": "66 Gy", "route": "Radioterapia externa", "schedule": "33 fracciones"},
                            {"drug_name": "Goserelina", "dose": "10.8 mg", "route": "Subcutánea", "schedule": "Cada 3 meses"},
                        ],
                        metadata_source="guideline_backbone",
                        evidence_tags=["GETUG-AFU 16"],
                        notes="Considérese cuando la cinética y el riesgo favorecen intensificar un rescate aún curativo.",
                        why_this_rank=["La ADT corta queda detrás del rescue puro, pero sigue elegible cuando la cinética o el riesgo justifican intensificación."],
                        caution_flags=["Añade carga hormonal y toxicidad metabólica frente a salvage RT sola."],
                    )
                )
                salvage_variants.append(
                    build_ranked_option(
                        name="Radioterapia de rescate + ADT prolongada",
                        regimen_code="SALVAGE_RT_LONG_HORMONE",
                        rank=3,
                        priority="eligible",
                        eligibility_status="eligible_with_caution",
                        family_code="salvage_rt_family",
                        molecule_or_backbone="Radioterapia de rescate + ADT prolongada",
                        description="Salvage RT con intensificación hormonal prolongada tipo RTOG 9601.",
                        dose="RT 64.8 Gy + bicalutamida 150 mg VO diaria",
                        route="Radioterapia externa + Oral",
                        schedule="36 fracciones + toma diaria",
                        duration="24 meses",
                        component_drugs=[
                            {"drug_name": "Radioterapia de rescate", "dose": "64.8 Gy", "route": "Radioterapia externa", "schedule": "36 fracciones"},
                            {"drug_name": "Bicalutamida", "dose": "150 mg", "route": "Oral", "schedule": "Diaria"},
                        ],
                        metadata_source="guideline_backbone",
                        evidence_tags=["RTOG 9601"],
                        notes="Manténgase visible cuando el riesgo biológico sea mayor, pero no debe desplazar al rescue puro si aún basta un salvage temprano.",
                        why_this_rank=["La intensificación prolongada sigue elegible, pero queda detrás de salvage puro o ADT corta cuando la ventana curativa aún es directa."],
                        caution_flags=["La exposición hormonal prolongada aumenta toxicidad y no debe universalizarse."],
                    )
                )
            if psma_pattern == "local_pelvic" and not confidence_low:
                salvage_variants.append(
                    build_ranked_option(
                        name="Radioterapia de rescate guiada por PSMA",
                        regimen_code="SALVAGE_RT_ALONE",
                        rank=len(salvage_variants) + 1,
                        priority="eligible",
                        eligibility_status="eligible_nonpreferred",
                        family_code="salvage_rt_family",
                        molecule_or_backbone="Radioterapia de rescate guiada por PSMA",
                        description="PSMA local/pélvica que refuerza el volumen de rescate pero mantiene carril curativo.",
                        dose="64-66 Gy adaptados al volumen objetivo",
                        route="Radioterapia externa",
                        schedule="Planificación adaptada por PSMA",
                        metadata_source="guideline_backbone",
                        notes="PSMA local/pélvico mantiene abierta la ventana curativa y refuerza rescate dirigido.",
                        why_this_rank=["La PSMA positiva local no cambia el carril de salvage; lo refina."],
                    )
                )
            elif psma_pattern == "oligometastatic":
                local_mdt_variants.append(
                    build_ranked_option(
                        name="MDT / rescate multimodal guiado por PSMA",
                        regimen_code="PSMA_GUIDED_MDT",
                        rank=1,
                        priority="eligible",
                        eligibility_status="eligible_with_caution",
                        family_code="local_mdt_family",
                        molecule_or_backbone="MDT / SBRT dirigida",
                        description="Carga oligometastásica limitada que habilita MDT o rescate multimodal en comité oncológico.",
                        dose="SBRT 30-35 Gy en 3-5 fracciones o estrategia multimodal equivalente",
                        route="Radioterapia estereotáxica / multimodal",
                        schedule="Tratamiento local dirigido tras comité",
                        metadata_source="guideline_backbone",
                        notes="PSMA multifocal de bajo burden abre discusión de MDT/SBRT o rescate combinado.",
                        why_this_rank=["El patrón oligometastásico mantiene intención de control dirigido, pero por debajo del rescue local simple."],
                    )
                )
            elif psma_pattern == "diseminado":
                not_recommended.append("No priorizar rescate local aislado cuando el PSMA documenta patrón diseminado o estadio M1b/M1c.")
                observation_variants.append(
                    build_ranked_option(
                        name="Reestadificación sistémica post-PSMA",
                        regimen_code="SYSTEMIC_RESTAGING",
                        rank=len(observation_variants) + 1,
                        priority="preferred",
                        eligibility_status="preferred",
                        family_code="observation_family",
                        molecule_or_backbone="Reestadificación sistémica",
                        description="La distribución por PSMA reduce la plausibilidad de rescue local aislado.",
                        route="Imagen/reclasificación",
                        schedule="Redefinir carril sistémico tras PSMA",
                        metadata_source="guideline_backbone",
                        notes="La distribución por PSMA reduce la plausibilidad de rescate local aislado.",
                        why_this_rank=["Ya existe redirector sistémico explícito y el salvage local deja de ser la opción dominante."],
                    )
                )
            durations.append("Si se agrega terapia de privación androgénica a la radioterapia de rescate, use una duración adaptada al riesgo dentro del rango de 6 a 24 meses.")
            trials.extend([{"trial": "RTOG 9601", "match": True}, {"trial": "GETUG-AFU 16", "match": True}])
            if salvage_variants:
                family_profiles["salvage_rt_family"] = build_family_profile(
                    family_code="salvage_rt_family",
                    ordered_regimens=salvage_variants,
                    context={
                        "eligibility_status": "eligible" if salvage_feasible and not systemic_redirect else "conditional",
                        "missing_inputs": ["salvage_local_feasible"] if not salvage_feasible and not systemic_redirect else [],
                        "caution_drivers": ["PSMA estructurada incompleta"] if confidence_low else [],
                        "winner_reason": "La familia de salvage sigue liderando mientras la vía local curativa permanezca plausible.",
                        "why_not_preferred": "Solo pierde precedencia si la PSMA o la factibilidad local redirigen fuera del carril curativo local.",
                    },
                )
                family_order.append("salvage_rt_family")
            if local_mdt_variants:
                family_profiles["local_mdt_family"] = build_family_profile(
                    family_code="local_mdt_family",
                    ordered_regimens=local_mdt_variants,
                    context={
                        "eligibility_status": "conditional",
                        "winner_reason": "La MDT queda visible cuando el patrón es oligometastásico y aún existe una estrategia de control dirigida.",
                    },
                )
                family_order.append("local_mdt_family")
            if observation_variants:
                family_profiles["observation_family"] = build_family_profile(
                    family_code="observation_family",
                    ordered_regimens=observation_variants,
                    context={
                        "eligibility_status": "eligible" if systemic_redirect else "conditional",
                        "missing_inputs": ["psma_pet_done"] if psma_pending else [],
                        "winner_reason": "La reestadificación dirigida sigue visible cuando todavía puede cambiar el alcance del salvage o redirigir a sistémico.",
                    },
                )
                family_order.append("observation_family")
        else:
            observation_variants.append(
                build_ranked_option(
                    name="Reestadificación después de recurrencia posradioterapia",
                    regimen_code="RESTAGING",
                    rank=1,
                    priority="preferred" if not local_salvage_candidate else "eligible",
                    eligibility_status="preferred" if not local_salvage_candidate else "eligible_nonpreferred",
                    family_code="observation_family",
                    molecule_or_backbone="Reestadificación post-RT",
                    description="Confirmar recurrencia exclusivamente local frente a recurrencia sistémica antes de seleccionar tratamiento.",
                    route="Imagen/reclasificación",
                    schedule="Reestadificación completa antes de cerrar tratamiento",
                    metadata_source="guideline_backbone",
                    notes="Confirme recurrencia exclusivamente local frente a recurrencia sistémica antes de seleccionar tratamiento.",
                    why_this_rank=["La recurrencia post-RT necesita reestadificación formal antes de fijar salvage local o transición sistémica."],
                )
            )
            if nccn["local_salvage_candidate"]:
                local_mdt_variants.append(
                    build_ranked_option(
                        name="Revisión de rescate local después de radioterapia",
                        regimen_code="LOCAL_MDT",
                        rank=1,
                        priority="preferred",
                        eligibility_status="preferred",
                        family_code="local_mdt_family",
                        molecule_or_backbone="Rescate local post-RT",
                        description="Mantenga visible el rescate local solo cuando siga siendo técnicamente plausible una opción con intención curativa.",
                        route="Cirugía / ablación / radioterapia dirigida",
                        schedule="Definición multidisciplinaria de rescate post-RT",
                        metadata_source="guideline_backbone",
                        notes="Mantenga visible el rescate local solo cuando siga siendo técnicamente plausible una opción con intención curativa.",
                        why_this_rank=["La vía local aún compite formalmente cuando el rescate post-RT es técnicamente plausible."],
                    )
                )
            if psma_pattern == "local_pelvic" and not confidence_low:
                local_mdt_variants.append(
                    build_ranked_option(
                        name="Revisión de rescate local guiada por PSMA",
                        regimen_code="PSMA_GUIDED_MDT",
                        rank=len(local_mdt_variants) + 1,
                        priority="eligible",
                        eligibility_status="eligible_nonpreferred",
                        family_code="local_mdt_family",
                        molecule_or_backbone="Rescate local guiado por PSMA",
                        description="PSMA local/pélvica que apoya salvamento local si sigue siendo técnicamente factible.",
                        route="Cirugía / ablación / radioterapia dirigida",
                        schedule="Plan dirigido por PSMA",
                        metadata_source="guideline_backbone",
                        notes="PSMA local/pélvico apoya salvamento local si sigue siendo técnicamente factible.",
                        why_this_rank=["La PSMA refuerza el rescate local, pero no sustituye la reestadificación integral."],
                    )
                )
            elif psma_pattern == "oligometastatic":
                local_mdt_variants.append(
                    build_ranked_option(
                        name="MDT/SBRT guiado por PSMA",
                        regimen_code="PSMA_GUIDED_MDT",
                        rank=len(local_mdt_variants) + 1,
                        priority="eligible",
                        eligibility_status="eligible_with_caution",
                        family_code="local_mdt_family",
                        molecule_or_backbone="MDT / SBRT guiada",
                        description="Burden limitado en PSMA que habilita ruta oligometastásica contextual.",
                        dose="SBRT 30-35 Gy en 3-5 fracciones",
                        route="Radioterapia estereotáxica",
                        schedule="Tratamiento dirigido tras comité",
                        metadata_source="guideline_backbone",
                        notes="PSMA con burden limitado abre ruta oligometastásica contextual.",
                        why_this_rank=["La ruta oligometastásica sigue siendo contextual y depende de comité multidisciplinario."],
                    )
                )
            elif psma_pattern == "diseminado":
                not_recommended.append("No usar una lectura diseminada de PSMA como base para rescate local aislado después de RT.")
            trials.append({"trial": "Base de evidencia para rescate local tras radioterapia", "match": True})
            not_recommended.append("No use PET/CT con PSMA después de recurrencia posradioterapia si el paciente no es un candidato realista a rescate local.")
            if local_mdt_variants:
                family_profiles["local_mdt_family"] = build_family_profile(
                    family_code="local_mdt_family",
                    ordered_regimens=local_mdt_variants,
                    context={
                        "eligibility_status": "eligible" if local_salvage_candidate and not systemic_redirect else "conditional",
                        "winner_reason": "El rescate local posradioterapia solo lidera cuando sigue siendo técnicamente factible y la imagen no redirige a sistémico.",
                    },
                )
                family_order.append("local_mdt_family")
            if observation_variants:
                family_profiles["observation_family"] = build_family_profile(
                    family_code="observation_family",
                    ordered_regimens=observation_variants,
                    context={
                        "eligibility_status": "eligible",
                        "missing_inputs": ["psma_pet_done"] if psma_pending else [],
                        "winner_reason": "La reestadificación post-RT sigue siendo obligatoria para separar local salvage de transición sistémica.",
                    },
                )
                family_order.append("observation_family")
        if psma_impact.get("confidence") == "low":
            not_recommended.append("No escalar una decisión mayor con PSMA-RADS bajo/intermedio o estructura PSMA incompleta sin correlación adicional.")
        durations.extend(psma_impact.get("recommended_actions", [])[:2])

        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        if not preferred_regimen and observation_variants:
            preferred_regimen = dict(observation_variants[0])
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "observation_family",
            field_values=payload,
        )
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=missing_inputs,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context="recurrence_bcr",
            field_values=payload,
            monitoring_package=active_monitoring_package,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )

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
            eligible_treatments=comparative_bundle.get("eligible_treatments") or [],
            not_recommended=not_recommended,
            missing_critical_inputs=missing_inputs,
            contraindications=[],
            durations_and_conditions=durations,
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=trials,
            applicability_badge="guideline-consistent",
            report_sections={
                "summary": f"Ruta de recurrencia bioquímica: {nccn['label']}.",
                "embark_readiness": {
                    "high_risk_bcr2": nccn["high_risk_bcr2"],
                    "conventional_imaging_m0": nccn["conventional_imaging_m0"],
                    "salvage_local_feasible": nccn["salvage_local_feasible"],
                },
            },
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or nccn["label"],
                "confidence_category": "vigilada" if missing_inputs else "alta",
                "requires_human_review": bool(missing_inputs or confidence_low),
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        result["arpi_required_fields"] = list(arpi_capture_contract.get("arpi_required_fields") or [])
        result["arpi_missing_inputs"] = list(arpi_capture_contract.get("arpi_missing_inputs") or [])
        result["arpi_stale_inputs"] = list(arpi_capture_contract.get("arpi_stale_inputs") or [])
        result["arpi_profile_completeness"] = str(arpi_capture_contract.get("arpi_profile_completeness") or "")
        result["arpi_preference_readiness"] = str(arpi_capture_contract.get("arpi_preference_readiness") or "")
        result["arpi_selection_contract"] = dict(arpi_capture_contract)
        result["care_setting_contract"] = {
            "care_setting": (
                "systemic_intensification"
                if preferred_regimen.get("family_code") == "arpi_family"
                else "salvage_local"
            ),
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
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
