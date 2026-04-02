from __future__ import annotations

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mcrpc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.arpi_selection_engine import (
    build_arpi_capture_contract,
    candidate_regimens_for_state,
    evaluate_arpi_candidate,
)
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.m1_crpc.rules_eau import evaluate_m1_crpc_eau
from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA
from prostanet.domains.patient_tracking.therapy_catalog import build_treatment_option
from prostanet.domains.patient_tracking.therapeutic_family_engine import (
    build_active_regimen_monitoring_package,
    build_comparative_bundle,
    build_family_profile,
    build_ranked_option,
    build_sequence_transition_bundle,
    regimen_family_code,
)
from prostanet.shared.contracts import evaluation_result
from prostanet.shared.metastatic_profile import build_metastatic_composition_summary
from prostanet.shared.recommendation_enrichment import enrich_evaluation_result


class M1CrpcService:
    module_id = "m1_crpc"

    def __init__(self) -> None:
        self.registry = EvidenceRegistryService()
        self.comparison = GuidelineComparisonService()

    def schema(self) -> dict:
        return M1_CRPC_SCHEMA

    def evaluate(self, payload: dict) -> dict:
        nccn = evaluate_m1_crpc(payload)
        eau = evaluate_m1_crpc_eau(payload)
        comparison = self.comparison.compare(nccn, eau)
        normalized = dict(payload)
        if isinstance(normalized.get("prior_therapy"), str):
            normalized["prior_therapy"] = [item.strip() for item in normalized["prior_therapy"].split(",") if item.strip()]
        legacy = evaluate_patient_for_mcrpc(normalized)
        biomarker_source = str(payload.get("biomarker_source", "Desconocida"))
        hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
        psma_negative_dominant_lesions = str(payload.get("psma_negative_dominant_lesions", "0")) == "1"
        psma_profile = (
            build_psma_structured_profile_from_payload(payload)
            if str(payload.get("psma_pet_done", "0")) == "1" or str(payload.get("psma_positive", "0")) == "1"
            else {"available": False}
        )
        psma_impact = build_psma_decision_impact(psma_profile, state=self.module_id, patient={"baseline": payload})
        molecular_report_date = str(payload.get("molecular_report_date", "")).strip()
        biomarker_traceable = biomarker_source not in {"", "Desconocida", "Desconocido"} and (not nccn["hrr_positive"] or hrr_gene not in {"", "Desconocido"})
        explicit_partial_psma = psma_profile.get("source_mode") == "structured" and (
            psma_impact.get("confidence") == "low"
            or str(psma_profile.get("psma_radioligand") or "") in {"", "Desconocido"}
            or str(psma_profile.get("psma_rads_score") or "") == "3"
        )
        taxane_candidate_now = bool(nccn.get("taxane_candidate_now"))
        taxane_verified = str(nccn.get("docetaxel_verification_status") or "verified") == "verified"
        taxane_available_now = (
            taxane_candidate_now
            and str(nccn.get("docetaxel_base_eligibility") or "") in {"eligible", "eligible_with_caution"}
            and taxane_verified
        )
        taxane_needs_verification = taxane_candidate_now and not taxane_verified
        taxane_blocked_now = str(nccn.get("docetaxel_base_eligibility") or "") == "contraindicated"
        abiraterone_hard_block = bool(nccn.get("abiraterone_hard_block"))
        abiraterone_caution = bool(nccn.get("abiraterone_caution"))
        current_medications_present = bool(nccn.get("current_medications_present"))
        ddi_reviewed = bool(nccn.get("drug_interaction_reviewed"))
        seizure_risk = bool(nccn.get("comorbidity_seizure"))
        frailty_status = str(nccn.get("frailty_status") or "Fit").strip().lower()
        vision_eligible = nccn["psma_positive"] and not psma_negative_dominant_lesions and nccn["prior_arpi"] and nccn["prior_docetaxel"] and not explicit_partial_psma
        pre_taxane_pluvicto_candidate = (
            nccn["psma_positive"]
            and not psma_negative_dominant_lesions
            and nccn["prior_arpi"]
            and not nccn["prior_docetaxel"]
            and (
                nccn["chemotherapy_delay_candidate"]
                or taxane_blocked_now
                or taxane_needs_verification
                or str(nccn.get("docetaxel_default_intensification") or "") == "conditional"
                or nccn["line_context"] == "post_arpi_pre_taxane"
            )
            and not explicit_partial_psma
        )
        prior_arpi_duration = float(payload.get("prior_arpi_duration_months", 0) or 0)
        prior_arpi_duration_documented = str(payload.get("prior_arpi_duration_months", "")).strip() != ""
        card_applicable = nccn["prior_arpi"] and nccn["prior_docetaxel"]
        card_fully_validated = card_applicable and prior_arpi_duration_documented and prior_arpi_duration >= 6
        supportive_context = [
            "La recomendación principal permanece anclada a la Red Nacional Integral del Cáncer (NCCN) 5.2026 y la Asociación Europea de Urología (EAU) 2026.",
            "CARD se usa para priorizar cabazitaxel sobre un intercambio ARPI-ARPI cuando ya hubo docetaxel y ARPI previo.",
            "VISION se usa para exigir elegibilidad PSMA estructurada y exposición previa correcta antes de priorizar lutecio-177 PSMA-617.",
            "PROfound se usa para exigir biomarcador HRR trazable por gen y por fuente analítica antes de priorizar olaparib.",
            "Las rutas de primera línea guiadas por biomarcadores se restringen a contexto first-line mCRPC y a biomarcadores trazables.",
            psma_impact.get("rationale"),
        ]
        arpi_candidate_regimens = candidate_regimens_for_state(self.module_id, payload)
        arpi_capture_contract = build_arpi_capture_contract(
            self.module_id,
            payload,
            candidate_regimens=arpi_candidate_regimens,
        )
        treatments = []
        missing_inputs = []
        not_recommended = [
            "Avoid repeating exhausted ARPI sequences without a biomarker or sequencing rationale.",
            "Do not offer Radium-223 in visceral metastatic disease.",
            "Do not use MRI or PET as routine monitoring tools outside a trial-oriented or decision-changing context.",
        ]

        if not nccn["castrate_confirmed"]:
            treatments.append(
                {
                    "name": "Confirm castrate testosterone and optimize ADT",
                    "priority": "preferred",
                    "notes": "No debe secuenciarse como enfermedad resistente a la castración con metástasis sin confirmar testosterona en rango de castración.",
                }
            )
            missing_inputs.append("castrate_testosterone_confirmed")
            not_recommended.append("Do not intensify or relabel as mCRPC until castrate-range testosterone is documented.")
        else:
            if nccn["line_context"] == "first_line_mcrpc" and not nccn["prior_arpi"]:
                frontline_candidates = []
                if not nccn["prior_enza_class"]:
                    arpi_meta = evaluate_arpi_candidate(
                        self.module_id,
                        payload,
                        "ADT_ENZALUTAMIDE",
                        candidate_regimens=arpi_candidate_regimens,
                    )
                    enzalutamide_notes = [
                        "Ruta estándar de primera línea mCRPC antes de reciclar clases o saltar directamente a inmunoterapia por biomarcadores aislados."
                    ]
                    if arpi_meta.get("benefit_basis"):
                        enzalutamide_notes.append(str(arpi_meta.get("benefit_basis") or ""))
                    enzalutamide_notes.extend(list(arpi_meta.get("safety_rationale") or []))
                    if arpi_meta.get("required_missing_fields"):
                        enzalutamide_notes.append(
                            "Perfil ARPI incompleto: " + ", ".join(arpi_meta.get("required_missing_fields") or [])
                        )
                    frontline_candidates.append(
                        {
                            "name": "Enzalutamide",
                            "score": float(arpi_meta.get("benefit_adjustment") or 0.0),
                            "notes": " ".join(enzalutamide_notes),
                            "arpi_meta": arpi_meta,
                        }
                    )
                if not nccn["prior_abiraterone"] and not abiraterone_hard_block:
                    arpi_meta = evaluate_arpi_candidate(
                        self.module_id,
                        payload,
                        "ADT_ABIRATERONE",
                        candidate_regimens=arpi_candidate_regimens,
                    )
                    abiraterone_notes = [
                        "Alternativa estándar de primera línea mCRPC cuando no existe contraindicación hepática relevante."
                    ]
                    if arpi_meta.get("benefit_basis"):
                        abiraterone_notes.append(str(arpi_meta.get("benefit_basis") or ""))
                    abiraterone_notes.extend(list(arpi_meta.get("safety_rationale") or []))
                    if arpi_meta.get("required_missing_fields"):
                        abiraterone_notes.append(
                            "Perfil ARPI incompleto: " + ", ".join(arpi_meta.get("required_missing_fields") or [])
                        )
                    frontline_candidates.append(
                        {
                            "name": "Acetato de Abiraterona",
                            "score": float(arpi_meta.get("benefit_adjustment") or 0.0),
                            "notes": " ".join(abiraterone_notes),
                            "arpi_meta": arpi_meta,
                        }
                    )
                elif not nccn["prior_abiraterone"] and abiraterone_hard_block:
                    not_recommended.append("No priorizar abiraterona cuando existe riesgo hepático clínicamente relevante o Child-Pugh B/C.")
                frontline_candidates.sort(key=lambda item: (item["score"], item["name"]), reverse=True)
                for index, item in enumerate(frontline_candidates):
                    arpi_meta = dict(item.get("arpi_meta") or {})
                    definitive = str(arpi_meta.get("preference_confidence") or "definitive") == "definitive"
                    treatments.append(
                        {
                            "name": item["name"],
                            "priority": "preferred" if index == 0 and definitive else "eligible",
                            "notes": item["notes"],
                            "benefit_basis": arpi_meta.get("benefit_basis", ""),
                            "benefit_endpoint_used": arpi_meta.get("benefit_endpoint_used", ""),
                            "benefit_maturity": arpi_meta.get("benefit_maturity", ""),
                            "preference_confidence": arpi_meta.get("preference_confidence", "definitive"),
                            "required_missing_fields": list(arpi_meta.get("required_missing_fields") or []),
                            "stale_inputs": list(arpi_meta.get("stale_inputs") or []),
                            "safety_drivers_used": list(arpi_meta.get("safety_drivers_used") or []),
                        }
                    )
            if nccn["line_context"] == "first_line_mcrpc" and nccn["hrr_positive"] and biomarker_traceable and not nccn["prior_enza_class"]:
                treatments.append(
                    {
                        "name": "Talazoparib + Enzalutamide",
                        "priority": "selected_candidate",
                        "notes": "Ruta de precisión first-line válida cuando el biomarcador HRR es trazable, pero no debe sobreponerse automáticamente a la secuencia estándar ARPI en esta v1 clínica.",
                    }
                )
            if nccn["line_context"] == "first_line_mcrpc" and nccn["brca_pathway"] and biomarker_traceable and not nccn["prior_abiraterone"]:
                treatments.append(
                    {
                        "name": "Niraparib + Abiraterone",
                        "priority": "selected_candidate",
                        "notes": f"Ruta BRCA de primera línea con biomarcador trazable ({hrr_gene}); se muestra como overlay de precisión y no como sustituto automático de la secuencia estándar ARPI.",
                    }
                )
            if biomarker_traceable and nccn["prior_arpi"]:
                treatments.append(
                    {
                        "name": "Olaparib",
                        "priority": "preferred",
                        "notes": (
                            self._note_for(legacy, "Olaparib")
                            or f"Biomarcador HRR trazable ({hrr_gene}) documentado desde {biomarker_source.lower()}."
                        ),
                    }
                )
            if nccn["msi_high"] or nccn["tmb_high"]:
                treatments.append(
                    {
                        "name": "Pembrolizumab",
                        "priority": "preferred" if nccn["msi_high"] else "eligible",
                        "notes": self._note_for(legacy, "Pembrolizumab") or "Vía inmunológica habilitada por MSI-H/dMMR o carga mutacional tumoral alta.",
                    }
                )
            # ── AR-V7: preferir quimioterapia sobre ARPI (PROPHECY / Antonarakis 2014) ──
            if nccn["ar_v7_positive"] and nccn["prior_arpi"]:
                if taxane_available_now and not nccn["prior_docetaxel"]:
                    treatments.append({
                        "name": "Docetaxel (AR-V7 dirigido)",
                        "priority": "preferred",
                        "notes": "AR-V7 positivo predice resistencia a ARPI. PROPHECY (Armstrong 2019) y Antonarakis NEJM 2014 respaldan preferir taxanos sobre secuenciar otro ARPI.",
                    })
                not_recommended.append("No secuenciar otro ARPI cuando AR-V7 es positivo — la resistencia está documentada (PROPHECY, Antonarakis 2014).")
            # ── TP53 + RB1 loss → sospecha NEPC / lineage plasticity (Beltran 2016) ──
            if nccn["nepc_suspected"]:
                treatments.append({
                    "name": "Carboplatino + Etopósido",
                    "priority": "preferred",
                    "notes": (
                        f"Sospecha de transformación neuroendocrina (score NEPC: {nccn['nepc_suspicion_score']}/7). "
                        "TP53/RB1 loss + marcadores clínicos sugieren lineage plasticity. "
                        "Beltran 2016 y Aggarwal 2018 respaldan esquema platinum-based."
                    ),
                })
                not_recommended.append("No continuar ARPI como línea principal si existe sospecha fuerte de transformación neuroendocrina (NEPC).")
            elif nccn["lineage_plasticity_risk"]:
                treatments.append({
                    "name": "Monitoreo intensivo NEPC",
                    "priority": "eligible",
                    "notes": "TP53 + RB1 loss documentados — riesgo de lineage plasticity. Monitorear NSE, LDH, cromogranina A y PSA discordante bajo. Considerar biopsia si progresa.",
                })
            # ── PTEN loss → inhibidores AKT (IPATential150 / CAPItello-281) ──
            if nccn["pten_loss"]:
                treatments.append({
                    "name": "Ipatasertib + Abiraterona",
                    "priority": "eligible",
                    "notes": "PTEN loss documentado. IPATential150 (de Bono 2020) mostró beneficio en rPFS en subgrupo PTEN-loss. Considerar si no hay contraindicación a abiraterona.",
                })
                supportive_context.append("PTEN loss activa la vía PI3K/AKT y se asocia a peor pronóstico bajo ARPI estándar (Jamaspishvili 2018).")
            # ── CDK12 biallelic → alta carga neoantigénica → IO (Wu 2018) ──
            if nccn["cdk12_biallelic"] and not (nccn["msi_high"] or nccn["tmb_high"]):
                treatments.append({
                    "name": "Pembrolizumab (CDK12-dirigido)",
                    "priority": "eligible",
                    "notes": "CDK12 bialélico genera alta carga neoantigénica independiente de MSI-H. Wu 2018 y Antonarakis 2020 respaldan inmunoterapia en este contexto.",
                })
            # ── TMB zona gris (6-10 mut/Mb) → monitoreo ──
            if nccn["tmb_zone"] == "gray" and not nccn["msi_high"]:
                treatments.append({
                    "name": "Monitoreo TMB zona gris",
                    "priority": "eligible",
                    "notes": f"TMB {nccn['tmb_value']:.0f} mut/Mb en zona gris (6-10). No alcanza umbral para IO, pero monitorear si sube en siguiente biopsia líquida.",
                })
            # ── ctDNA rising → señal de resistencia temprana (Wyatt 2021) ──
            if nccn["ctdna_rising"]:
                not_recommended.append("ctDNA en ascenso sugiere resistencia emergente — anticipar cambio de línea antes de progresión radiográfica (Wyatt 2021, Chi 2022).")
            if vision_eligible:
                treatments.append(
                    {
                        "name": "Lu-177 PSMA-617",
                        "priority": "preferred",
                        "notes": self._note_for(legacy, "Lu-177 PSMA") or "Elegibilidad tipo VISION documentada con PSMA positivo de alta confianza y sin lesiones dominantes PSMA-negativas.",
                    }
                )
            elif pre_taxane_pluvicto_candidate:
                treatments.append(
                    {
                        "name": "Lu-177 PSMA-617",
                        "priority": "selected_candidate",
                        "notes": "PSMA positivo documentado en contexto pre-taxano con necesidad clínica de diferir o evitar docetaxel.",
                    }
                )
            elif nccn["psma_positive"] and nccn["prior_arpi"]:
                treatments.append(
                    {
                        "name": "Lu-177 PSMA-617",
                        "priority": "selected_candidate",
                        "notes": "PSMA positivo documentado, pero la elegibilidad de radioligando sigue siendo parcial o incompleta.",
                    }
                )
            if str(psma_profile.get("psma_radioligand") or "") == "18F-PSMA-1007":
                not_recommended.append("Usar cautela al sobreinterpretar hallazgos óseos dudosos con 18F-PSMA-1007 cuando la decisión dependa exclusivamente del PET.")
            if nccn["symptomatic_bone_only"]:
                treatments.append({"name": "Radium-223", "priority": "eligible", "notes": self._note_for(legacy, "Radium-223")})
            if card_applicable:
                card_priority = "preferred" if card_fully_validated else "eligible"
                card_notes = self._note_for(legacy, "Cabazitaxel") or "CARD respalda priorizar cabazitaxel sobre secuenciar otro ARPI tras docetaxel y ARPI previo."
                if not prior_arpi_duration_documented:
                    card_notes += " Nota: duración de ARPI previo no documentada — verificar ≥6 meses per CARD (de Wit 2019) para confirmar prioridad."
                elif prior_arpi_duration < 6:
                    card_notes += f" Precaución: duración de ARPI previo ({prior_arpi_duration:.0f} meses) <6 meses — CARD requería ≥6 meses de exposición previa."
                treatments.append(
                    {
                        "name": "Cabazitaxel",
                        "priority": card_priority,
                        "notes": card_notes,
                    }
                )
            elif not nccn["prior_docetaxel"] and taxane_available_now:
                treatments.append(
                    {
                        "name": "Docetaxel",
                        "priority": "eligible",
                        "notes": (
                            self._note_for(legacy, "Docetaxel")
                            or "Docetaxel sigue siendo una alternativa estructurada cuando la elegibilidad taxano ya fue verificada y no hay exposición previa."
                        ),
                    }
                )
            elif not nccn["prior_docetaxel"] and taxane_needs_verification:
                for field in list(nccn.get("docetaxel_missing_inputs") or []) + list(nccn.get("docetaxel_stale_inputs") or []):
                    if field not in missing_inputs:
                        missing_inputs.append(field)
                not_recommended.append("No cerrar una ruta taxano en mCRPC sin verificar antes CBC/LFT y seguridad estructurada de docetaxel.")
            elif not nccn["prior_docetaxel"] and taxane_blocked_now:
                not_recommended.append("Docetaxel no debe competir hoy porque la elegibilidad taxano está clínicamente bloqueada.")
            if nccn["rare_histology_variant"] or nccn["neuroendocrine_features"]:
                not_recommended.append("Do not assume standard adenocarcinoma sequencing remains appropriate when rare aggressive or neuroendocrine features are present.")
        case_summary = (
            "El caso corresponde a enfermedad resistente a la castración con metástasis y requiere secuenciación terapéutica basada en biomarcadores, exposición previa y distribución metastásica. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 lo resume como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo contrasta como {eau['label']}."
        )
        metastatic_summary = build_metastatic_composition_summary(payload)
        if metastatic_summary.get("available"):
            case_summary = f"{case_summary} {metastatic_summary.get('narrative')}"
        if nccn["hrr_positive"] and biomarker_source in {"", "Desconocida", "Desconocido"}:
            missing_inputs.append("biomarker_source")
        if nccn["hrr_positive"] and hrr_gene in {"", "Desconocido"}:
            missing_inputs.append("hrr_gene")
        if (nccn["hrr_positive"] or nccn["msi_high"] or nccn["tmb_high"] or nccn["brca_pathway"]) and not molecular_report_date:
            missing_inputs.append("molecular_report_date")
        if nccn["psma_positive"] and psma_negative_dominant_lesions:
            missing_inputs.append("psma_negative_dominant_lesions")
        if card_applicable:
            not_recommended.append("No priorizar un intercambio ARPI-ARPI por encima de cabazitaxel tras docetaxel y ARPI previo salvo justificación biomolecular clara.")
            if not prior_arpi_duration_documented:
                missing_inputs.append("prior_arpi_duration_months")
        if nccn["hrr_positive"] and not biomarker_traceable:
            not_recommended.append("No priorizar PARP sin gen HRR y fuente del biomarcador claramente trazables.")
        if nccn["psma_positive"] and psma_negative_dominant_lesions:
            not_recommended.append("No priorizar lutecio-177 PSMA-617 si existen lesiones dominantes PSMA-negativas no resueltas.")
        if explicit_partial_psma:
            not_recommended.append("No etiquetar la elegibilidad PSMA como plena cuando PSMA-RADS es intermedio, el radioligando es desconocido o la documentación estructurada es insuficiente.")
        missing_inputs.extend(arpi_capture_contract.get("arpi_missing_inputs") or [])
        missing_inputs.extend(arpi_capture_contract.get("arpi_stale_inputs") or [])
        missing_inputs = list(dict.fromkeys(missing_inputs))
        not_recommended = list(dict.fromkeys(not_recommended))

        preferred_seen = False
        for item in treatments:
            if item.get("priority") != "preferred":
                continue
            if not preferred_seen:
                preferred_seen = True
                continue
            item["priority"] = "eligible"
            item["notes"] = f"{item.get('notes', '').strip()} Alternativa válida, pero queda por debajo de la prioridad terapéutica principal en este escenario.".strip()
        ranked_treatments = []
        for index, item in enumerate(treatments, start=1):
            hydrated = self._hydrate_treatment_item(item, rank=index)
            ranked_treatments.append(hydrated)
        treatments = ranked_treatments

        family_profiles: dict[str, dict] = {}
        family_order: list[str] = []
        grouped: dict[str, list[dict]] = {}
        for item in treatments:
            family_code = str(item.get("family_code") or regimen_family_code(item.get("regimen_code")))
            grouped.setdefault(family_code, []).append(item)
            if family_code not in family_order:
                family_order.append(family_code)

        if grouped.get("arpi_family"):
            family_profiles["arpi_family"] = build_family_profile(
                family_code="arpi_family",
                ordered_regimens=grouped["arpi_family"],
                context={
                    "eligibility_status": "eligible",
                    "caution_drivers": [
                        reason
                        for reason, active in (
                            ("Riesgo convulsivo", seizure_risk),
                            ("Fragilidad relativa", frailty_status in {"vulnerable", "frail"}),
                            ("Polifarmacia con DDI pendiente", current_medications_present and not ddi_reviewed),
                        )
                        if active
                    ],
                    "missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
                    "stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
                    "winner_reason": "La familia ARPI se ordenó por secuencia clínica, seguridad neurológica y exposición previa.",
                    "why_not_preferred": "Los ARPI no preferentes permanecen visibles si no existe bloqueo duro, pero caen por secuencia, toxicidad o biomarcadores superiores.",
                },
            )
        if grouped.get("abiraterone_steroid_family"):
            family_profiles["abiraterone_steroid_family"] = build_family_profile(
                family_code="abiraterone_steroid_family",
                ordered_regimens=grouped["abiraterone_steroid_family"],
                context={
                    "eligibility_status": "conditional" if abiraterone_caution else ("contraindicated" if abiraterone_hard_block else "eligible"),
                    "hard_blocks": ["Riesgo hepático relevante"] if abiraterone_hard_block else [],
                    "caution_drivers": ["Riesgo cardio-metabólico o revisión DDI pendiente"] if abiraterone_caution else [],
                    "missing_inputs": list(arpi_capture_contract.get("arpi_missing_inputs") or []),
                    "stale_inputs": list(arpi_capture_contract.get("arpi_stale_inputs") or []),
                    "winner_reason": "Abiraterona compite cuando sigue siendo first-line plausible y no existe bloqueo hepático.",
                },
            )
        if grouped.get("taxane_family"):
            family_profiles["taxane_family"] = build_family_profile(
                family_code="taxane_family",
                ordered_regimens=grouped["taxane_family"],
                context={
                    "eligibility_status": str(nccn.get("docetaxel_base_eligibility") or "conditional"),
                    "hard_blocks": list(nccn.get("docetaxel_hard_stop_reasons") or []),
                    "missing_inputs": list(nccn.get("docetaxel_missing_inputs") or []),
                    "stale_inputs": list(nccn.get("docetaxel_stale_inputs") or []),
                    "winner_reason": "La familia taxano se ordenó con elegibilidad estructurada, secuencia CARD/TAX327 y exposición previa.",
                },
            )
        if grouped.get("parp_family"):
            family_profiles["parp_family"] = build_family_profile(
                family_code="parp_family",
                ordered_regimens=grouped["parp_family"],
                context={
                    "eligibility_status": "eligible" if biomarker_traceable and nccn["hrr_positive"] else "conditional",
                    "missing_inputs": [item for item in ["biomarker_source", "hrr_gene", "molecular_report_date"] if item in missing_inputs],
                    "winner_reason": "La familia PARP exige HRR trazable por gen y por fuente.",
                },
            )
        if grouped.get("psma_rlt_family"):
            family_profiles["psma_rlt_family"] = build_family_profile(
                family_code="psma_rlt_family",
                ordered_regimens=grouped["psma_rlt_family"],
                context={
                    "eligibility_status": "eligible" if vision_eligible or pre_taxane_pluvicto_candidate else "conditional",
                    "missing_inputs": [item for item in ["psma_negative_dominant_lesions"] if item in missing_inputs],
                    "caution_drivers": ["Elegibilidad PSMA parcial o discordante"] if explicit_partial_psma or psma_negative_dominant_lesions else [],
                    "winner_reason": "La familia PSMA-RLT se ordena por elegibilidad tipo VISION/PSMAfore y estructuración PSMA completa.",
                },
            )
        if grouped.get("radium223_family"):
            family_profiles["radium223_family"] = build_family_profile(
                family_code="radium223_family",
                ordered_regimens=grouped["radium223_family"],
                context={
                    "eligibility_status": "eligible" if nccn["symptomatic_bone_only"] else "conditional",
                    "winner_reason": "Radio-223 solo sube cuando domina el dolor óseo sin visceralidad.",
                },
            )
        if grouped.get("immunotherapy_family"):
            family_profiles["immunotherapy_family"] = build_family_profile(
                family_code="immunotherapy_family",
                ordered_regimens=grouped["immunotherapy_family"],
                context={
                    "eligibility_status": "eligible" if nccn["msi_high"] or nccn["tmb_high"] else "conditional",
                    "winner_reason": "La inmunoterapia exige un biomarcador inmune accionable o un racional molecular fuerte.",
                },
            )

        comparative_bundle = build_comparative_bundle(
            family_profiles=family_profiles,
            family_order=family_order,
        )
        preferred_regimen = dict(comparative_bundle.get("preferred_regimen") or {})
        sequence_transition_bundle = build_sequence_transition_bundle(
            state=self.module_id,
            preferred_regimen=preferred_regimen,
            eligible_treatments=comparative_bundle.get("eligible_treatments") or treatments,
            current_treatment=payload.get("current_treatment") or "",
            missing_critical_inputs=missing_inputs,
            progression_pattern=str(payload.get("progression_pattern") or ""),
            line_context=nccn.get("line_context") or "",
            field_values=payload,
            comparative_eligibility_matrix=comparative_bundle.get("comparative_eligibility_matrix") or {},
        )
        active_monitoring_package = build_active_regimen_monitoring_package(
            preferred_regimen.get("regimen_code"),
            family_code=preferred_regimen.get("family_code") or "observation_family",
            field_values=payload,
        )

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=comparative_bundle.get("eligible_treatments") or treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=missing_inputs,
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=["Prefer biomarker-directed options before recycling empiric classes when the profile supports them.", "Continue ADT backbone throughout M1 CRPC management."],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "PROfound", "match": biomarker_traceable},
                {"trial": "PROPEL", "match": nccn["hrr_positive"] and biomarker_traceable and not nccn["prior_abiraterone"]},
                {"trial": "VISION", "match": vision_eligible},
                {"trial": "PSMAfore", "match": pre_taxane_pluvicto_candidate},
                {"trial": "CARD", "match": card_applicable},
                {"trial": "TALAPRO-2", "match": nccn["line_context"] == "first_line_mcrpc" and nccn["hrr_positive"] and biomarker_traceable and not nccn["prior_enza_class"]},
                {"trial": "MAGNITUDE", "match": nccn["line_context"] == "first_line_mcrpc" and nccn["brca_pathway"] and biomarker_traceable and not nccn["prior_abiraterone"]},
                {"trial": "TRITON-3", "match": nccn["brca_pathway"] and biomarker_traceable},
                {"trial": "AFFIRM", "match": not nccn["prior_enza_class"]},
                {"trial": "COU-AA-301/302", "match": not nccn["prior_abiraterone"] and not abiraterone_hard_block},
                {"trial": "TAX 327", "match": taxane_available_now and not nccn["prior_docetaxel"]},
                {"trial": "TROPIC", "match": card_applicable},
                {"trial": "ALSYMPCA", "match": nccn["symptomatic_bone_only"]},
                {"trial": "KEYNOTE-158", "match": nccn["msi_high"] or nccn["tmb_high"]},
                {"trial": "PROPHECY", "match": nccn["ar_v7_positive"]},
                {"trial": "IPATential150", "match": nccn["pten_loss"]},
                {"trial": "CAPItello-281", "match": nccn["pten_loss"]},
            ],
            applicability_badge="guideline-consistent" if nccn["castrate_confirmed"] else "selected_candidate",
            report_sections={
                "summary": (
                    f"M1 CRPC sequencing and precision-oncology pathway. {metastatic_summary.get('narrative')}".strip()
                    if metastatic_summary.get("available")
                    else "M1 CRPC sequencing and precision-oncology pathway."
                ),
                "sequence_context": {
                    "line_context": nccn["line_context"],
                    "docetaxel_fit": nccn["docetaxel_fit"],
                    "docetaxel_base_eligibility": nccn.get("docetaxel_base_eligibility"),
                    "docetaxel_verification_status": nccn.get("docetaxel_verification_status"),
                    "chemotherapy_delay_candidate": nccn["chemotherapy_delay_candidate"],
                },
            },
            decision_changing_inputs=[
                "Confirmar testosterona en rango de castración antes de secuenciar como enfermedad resistente a la castración con metástasis.",
                "Confirmar gen HRR y fuente del biomarcador si se plantea PARP.",
                "Confirmar elegibilidad PSMA completa si se plantea radioligando dirigido.",
            ],
            supportive_evidence_context=supportive_context,
            benchmarking_flags=[
                {"label": "Biomarcador HRR trazable", "status": "complete" if biomarker_traceable else "missing", "rationale": "Necesario antes de olaparib."},
                {"label": "Elegibilidad radioligando documentada", "status": "complete" if vision_eligible or pre_taxane_pluvicto_candidate else "missing", "rationale": "Necesaria antes de lutecio-177 PSMA-617."},
                {"label": "Secuencia post-docetaxel + ARPI documentada", "status": "complete" if card_applicable else "incomplete", "rationale": "Aclara si aplica la priorización de cabazitaxel tipo CARD."},
                {"label": "Contexto de línea mCRPC documentado", "status": "complete" if nccn["line_context"] else "missing", "rationale": "Ordena el uso conservador de TALAPRO-2, MAGNITUDE y PSMAfore."},
                {"label": "AR-V7 documentado", "status": "complete" if nccn["ar_v7_positive"] else "incomplete", "rationale": "AR-V7+ redirige de ARPI a quimioterapia (PROPHECY)."},
                {"label": "Panel TP53/RB1/PTEN", "status": "complete" if any([nccn["tp53_altered"], nccn["rb1_loss"], nccn["pten_loss"]]) else "incomplete", "rationale": "Detecta lineage plasticity (NEPC) y candidatura AKT."},
                {"label": "CDK12 evaluado", "status": "complete" if nccn["cdk12_biallelic"] else "incomplete", "rationale": "CDK12 bialélico abre IO independiente de MSI."},
                {"label": "ctDNA monitoreado", "status": "complete" if nccn["ctdna_detected"] or nccn["ctdna_rising"] else "incomplete", "rationale": "Sensor de resistencia emergente pre-radiográfica."},
                {"label": "Score NEPC evaluado", "status": "complete" if nccn["nepc_suspicion_score"] > 0 else "incomplete", "rationale": "Detecta transformación neuroendocrina temprana."},
            ],
            decision_quality={
                "recommendation_family": preferred_regimen.get("family_label") or nccn.get("label") or "mCRPC",
                "confidence_category": "vigilada" if missing_inputs else "alta",
                "requires_human_review": bool(missing_inputs or nccn["nepc_suspected"]),
            },
        )
        result["comparative_eligibility_matrix"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["therapeutic_family_profiles"] = comparative_bundle.get("comparative_eligibility_matrix") or {}
        result["preferred_frontline_regimen"] = preferred_regimen
        result["preferred_regimen_code"] = preferred_regimen.get("regimen_code", "")
        result["alternative_regimens"] = comparative_bundle.get("alternative_regimens") or []
        result["patient_goals_profile"] = {
            "primary_goal": str(payload.get("primary_goal") or "max_control"),
            "visit_burden_tolerance": str(payload.get("visit_burden_tolerance") or "medium"),
            "route_preference": str(payload.get("route_preference") or "no_preference"),
            "symptom_priority": str(payload.get("symptom_priority") or ("pain" if nccn["symptomatic_bone_only"] else "mixed")),
        }
        result["care_setting_contract"] = {
            "care_setting": "systemic_precision" if preferred_regimen.get("family_code") in {"parp_family", "psma_rlt_family", "immunotherapy_family"} else "systemic_intensification",
            "family_code": preferred_regimen.get("family_code") or "",
            "family_label": preferred_regimen.get("family_label") or "",
        }
        result["sequence_transition_bundle"] = sequence_transition_bundle
        result["active_regimen_monitoring_package"] = active_monitoring_package
        result["arpi_required_fields"] = list(arpi_capture_contract.get("arpi_required_fields") or [])
        result["arpi_missing_inputs"] = list(arpi_capture_contract.get("arpi_missing_inputs") or [])
        result["arpi_stale_inputs"] = list(arpi_capture_contract.get("arpi_stale_inputs") or [])
        result["arpi_profile_completeness"] = str(arpi_capture_contract.get("arpi_profile_completeness") or "")
        result["arpi_preference_readiness"] = str(arpi_capture_contract.get("arpi_preference_readiness") or "")
        result["arpi_selection_contract"] = arpi_capture_contract
        return enrich_evaluation_result(
            result,
            clinical_title="Ruta priorizada de enfermedad resistente a la castración con metástasis",
            case_summary=case_summary,
            recommended_trajectory=nccn["recommendation"],
            personalized_fundamentals=[
                "La secuencia se redefine por el estado de reparación por recombinación homóloga, la inestabilidad microsatelital y la positividad para antígeno prostático específico de membrana.",
                "La carga mutacional tumoral alta también puede abrir inmunoterapia cuando existe trazabilidad molecular suficiente.",
                "La exposición previa a inhibidores de la vía del receptor androgénico y taxanos determina qué clases siguen activas y cuáles ya están agotadas.",
                "La presencia de metástasis óseas sintomáticas sin compromiso visceral abre opciones óseo-dirigidas específicas.",
                "AR-V7 positivo redirige la secuencia de ARPI a quimioterapia basándose en resistencia documentada al receptor androgénico.",
                "TP53 + RB1 loss activan vigilancia de lineage plasticity y transformación neuroendocrina, cambiando el esquema a platinum-based cuando se confirma.",
                "PTEN loss abre la vía PI3K/AKT como alternativa terapéutica con inhibidores AKT combinados.",
                "CDK12 bialélico genera carga neoantigénica alta e independiza la candidatura a inmunoterapia de MSI-H.",
                "ctDNA en ascenso anticipa resistencia terapéutica semanas antes que PSA, permitiendo cambio de línea proactivo.",
            ],
            alternatives=[
                "Olaparib o inmunoterapia cuando el perfil molecular lo respalda.",
                "Quimioterapia, radiofármacos o terapias dirigidas según biomarcadores, exposición previa y sitio metastásico dominante.",
            ],
            shared_decision_message=(
                "La decisión final debe armonizar biomarcadores, síntomas, reserva funcional, toxicidades acumuladas y disponibilidad real de terapias dirigidas o radiofármacos."
            ),
            comparison_message=(
                "La comparación con la Asociación Europea de Urología (EAU) 2026 sirve para confirmar si la secuencia priorizada por biomarcadores coincide o si debe discutirse en comité oncológico multidisciplinario."
            ),
        )

    @staticmethod
    def _note_for(legacy: dict, drug_label: str) -> str:
        for item in legacy.get("recommendations", []):
            if drug_label.lower() in item.get("combination", "").lower() or drug_label.lower() in item.get("drug", "").lower():
                return item.get("evidence", "")
        return ""

    @staticmethod
    def _hydrate_treatment_item(item: dict[str, str], *, rank: int = 1) -> dict:
        name = str(item.get("name") or "").strip()
        notes = str(item.get("notes") or "").strip()
        priority = str(item.get("priority") or "eligible").strip()
        regimen_hint = {
            "Enzalutamide": "ADT_ENZALUTAMIDE",
            "Acetato de Abiraterona": "ADT_ABIRATERONE",
            "Talazoparib + Enzalutamide": "TALAZOPARIB_ENZALUTAMIDE",
            "Niraparib + Abiraterone": "NIRAPARIB_ABIRATERONE",
            "Olaparib": "OLAPARIB",
            "Pembrolizumab": "PEMBROLIZUMAB",
            "Lu-177 PSMA-617": "LU177_PSMA617",
            "Radium-223": "RADIUM223",
            "Cabazitaxel": "CABAZITAXEL",
            "Docetaxel": "DOCETAXEL",
            "Docetaxel (AR-V7 dirigido)": "DOCETAXEL",
            "Carboplatino + Etopósido": "CARBOPLATIN_ETOPOSIDE",
            "Monitoreo intensivo NEPC": "OBSERVATION",
            "Pembrolizumab (CDK12-dirigido)": "PEMBROLIZUMAB",
            "Monitoreo TMB zona gris": "OBSERVATION",
        }.get(name, "")
        family_code = regimen_family_code(regimen_hint or name)
        eligibility_status = (
            "preferred"
            if priority == "preferred"
            else "eligible_with_caution"
            if priority in {"selected_candidate", "not_preferred"}
            else "eligible_nonpreferred"
        )
        hydrated = build_ranked_option(
            name=name,
            regimen_code=regimen_hint or name,
            rank=rank,
            priority=priority,
            eligibility_status=eligibility_status,
            notes=notes,
            family_code=family_code,
            molecule_or_backbone=name,
            why_this_rank=[notes] if notes else [],
            caution_flags=[] if priority == "preferred" else ([notes] if notes else []),
            selection_rationale=[notes] if notes else [],
            benefit_basis=str(item.get("benefit_basis") or ""),
            benefit_endpoint_used=str(item.get("benefit_endpoint_used") or ""),
            benefit_maturity=str(item.get("benefit_maturity") or ""),
            preference_confidence=str(item.get("preference_confidence") or "definitive"),
            required_missing_fields=list(item.get("required_missing_fields") or []),
            stale_inputs=list(item.get("stale_inputs") or []),
            safety_drivers_used=list(item.get("safety_drivers_used") or []),
        )
        if not hydrated.get("description"):
            hydrated["description"] = notes or name
        return hydrated
