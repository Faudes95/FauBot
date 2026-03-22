from __future__ import annotations

from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mcrpc

from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.guideline_comparison.service import GuidelineComparisonService
from prostanet.domains.patient_tracking.psma_imaging import (
    build_psma_decision_impact,
    build_psma_structured_profile_from_payload,
)
from prostanet.domains.m1_crpc.rules_eau import evaluate_m1_crpc_eau
from prostanet.domains.m1_crpc.rules_nccn import evaluate_m1_crpc
from prostanet.domains.m1_crpc.schemas import M1_CRPC_SCHEMA
from prostanet.shared.contracts import evaluation_result
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
        vision_eligible = nccn["psma_positive"] and not psma_negative_dominant_lesions and nccn["prior_arpi"] and nccn["prior_docetaxel"] and not explicit_partial_psma
        pre_taxane_pluvicto_candidate = (
            nccn["psma_positive"]
            and not psma_negative_dominant_lesions
            and nccn["prior_arpi"]
            and not nccn["prior_docetaxel"]
            and (nccn["chemotherapy_delay_candidate"] or not nccn["docetaxel_fit"] or nccn["line_context"] == "post_arpi_pre_taxane")
            and not explicit_partial_psma
        )
        card_applicable = nccn["prior_arpi"] and nccn["prior_docetaxel"]
        supportive_context = [
            "La recomendación principal permanece anclada a la Red Nacional Integral del Cáncer (NCCN) 5.2026 y la Asociación Europea de Urología (EAU) 2026.",
            "CARD se usa para priorizar cabazitaxel sobre un intercambio ARPI-ARPI cuando ya hubo docetaxel y ARPI previo.",
            "VISION se usa para exigir elegibilidad PSMA estructurada y exposición previa correcta antes de priorizar lutecio-177 PSMA-617.",
            "PROfound se usa para exigir biomarcador HRR trazable por gen y por fuente analítica antes de priorizar olaparib.",
            "Las rutas de primera línea guiadas por biomarcadores se restringen a contexto first-line mCRPC y a biomarcadores trazables.",
            psma_impact.get("rationale"),
        ]
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
            if nccn["line_context"] == "first_line_mcrpc" and nccn["hrr_positive"] and biomarker_traceable and not nccn["prior_enza_class"]:
                treatments.append(
                    {
                        "name": "Talazoparib + Enzalutamide",
                        "priority": "eligible",
                        "notes": "Use only in HRR-mutated first-line mCRPC with a traceable biomarker and without prior exhaustion of the enzalutamide class.",
                    }
                )
            if nccn["line_context"] == "first_line_mcrpc" and nccn["brca_pathway"] and biomarker_traceable and not nccn["prior_abiraterone"]:
                treatments.append(
                    {
                        "name": "Niraparib + Abiraterone",
                        "priority": "eligible",
                        "notes": f"BRCA-guided first-line mCRPC path with traceable molecular evidence ({hrr_gene}).",
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
                if nccn["docetaxel_fit"] and not nccn["prior_docetaxel"]:
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
                treatments.append(
                    {
                        "name": "Cabazitaxel",
                        "priority": "preferred",
                        "notes": self._note_for(legacy, "Cabazitaxel") or "CARD respalda priorizar cabazitaxel sobre secuenciar otro ARPI tras docetaxel y ARPI previo.",
                    }
                )
            elif not nccn["prior_docetaxel"] and nccn["docetaxel_fit"]:
                treatments.append({"name": "Docetaxel", "priority": "eligible", "notes": self._note_for(legacy, "Docetaxel")})
            if nccn["rare_histology_variant"] or nccn["neuroendocrine_features"]:
                not_recommended.append("Do not assume standard adenocarcinoma sequencing remains appropriate when rare aggressive or neuroendocrine features are present.")
        case_summary = (
            "El caso corresponde a enfermedad resistente a la castración con metástasis y requiere secuenciación terapéutica basada en biomarcadores, exposición previa y distribución metastásica. "
            f"La Red Nacional Integral del Cáncer (NCCN) 5.2026 lo resume como {nccn['label']} "
            f"y la Asociación Europea de Urología (EAU) 2026 lo contrasta como {eau['label']}."
        )
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
        if nccn["hrr_positive"] and not biomarker_traceable:
            not_recommended.append("No priorizar PARP sin gen HRR y fuente del biomarcador claramente trazables.")
        if nccn["psma_positive"] and psma_negative_dominant_lesions:
            not_recommended.append("No priorizar lutecio-177 PSMA-617 si existen lesiones dominantes PSMA-negativas no resueltas.")
        if explicit_partial_psma:
            not_recommended.append("No etiquetar la elegibilidad PSMA como plena cuando PSMA-RADS es intermedio, el radioligando es desconocido o la documentación estructurada es insuficiente.")

        preferred_seen = False
        for item in treatments:
            if item.get("priority") != "preferred":
                continue
            if not preferred_seen:
                preferred_seen = True
                continue
            item["priority"] = "eligible"
            item["notes"] = f"{item.get('notes', '').strip()} Alternativa válida, pero queda por debajo de la prioridad terapéutica principal en este escenario.".strip()

        result = evaluation_result(
            state=self.module_id,
            nccn_primary={"guideline": "NCCN", "version": "5.2026", "label": nccn["label"], "recommendation": nccn["recommendation"]},
            eau_comparison={"guideline": "EAU", "version": "2026", "label": eau["label"], "recommendation": eau["recommendation"], "comparison": comparison},
            eligible_treatments=treatments,
            not_recommended=not_recommended,
            missing_critical_inputs=missing_inputs,
            contraindications=legacy.get("contraindications", []),
            durations_and_conditions=["Prefer biomarker-directed options before recycling empiric classes when the profile supports them.", "Continue ADT backbone throughout M1 CRPC management."],
            evidence_trace=[self.registry.get_module_evidence(self.module_id)],
            trial_matches=[
                {"trial": "PROfound", "match": biomarker_traceable},
                {"trial": "VISION", "match": vision_eligible},
                {"trial": "PSMAfore", "match": pre_taxane_pluvicto_candidate},
                {"trial": "CARD", "match": card_applicable},
                {"trial": "TALAPRO-2", "match": nccn["line_context"] == "first_line_mcrpc" and nccn["hrr_positive"] and biomarker_traceable and not nccn["prior_enza_class"]},
                {"trial": "MAGNITUDE", "match": nccn["line_context"] == "first_line_mcrpc" and nccn["brca_pathway"] and biomarker_traceable and not nccn["prior_abiraterone"]},
                {"trial": "KEYNOTE-158", "match": nccn["msi_high"] or nccn["tmb_high"]},
                {"trial": "PROPHECY", "match": nccn["ar_v7_positive"]},
                {"trial": "IPATential150", "match": nccn["pten_loss"]},
                {"trial": "CAPItello-281", "match": nccn["pten_loss"]},
            ],
            applicability_badge="guideline-consistent" if nccn["castrate_confirmed"] else "selected_candidate",
            report_sections={
                "summary": "M1 CRPC sequencing and precision-oncology pathway.",
                "sequence_context": {
                    "line_context": nccn["line_context"],
                    "docetaxel_fit": nccn["docetaxel_fit"],
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
        )
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
