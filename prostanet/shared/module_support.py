from __future__ import annotations

from copy import deepcopy
from typing import Any

from prostanet.shared.contracts import CareOverlay, MonitoringPlan, StateTransition


def monitoring_plan(
    title: str,
    cadence: str,
    actions: list[str],
    triggers: list[str],
    evidence_basis: list[str],
) -> dict[str, Any]:
    return MonitoringPlan(
        title=title,
        cadence=cadence,
        actions=actions,
        triggers=triggers,
        evidence_basis=evidence_basis,
    ).to_dict()


def state_transition(target_state: str, label: str, when: str, rationale: str) -> dict[str, Any]:
    return StateTransition(
        target_state=target_state,
        label=label,
        when=when,
        rationale=rationale,
    ).to_dict()


def care_overlay(
    overlay_type: str,
    title: str,
    status: str,
    reasons: list[str],
    actions: list[str],
) -> dict[str, Any]:
    return CareOverlay(
        overlay_type=overlay_type,
        title=title,
        status=status,
        reasons=reasons,
        actions=actions,
    ).to_dict()


def benchmark_flag(label: str, status: str, rationale: str) -> dict[str, Any]:
    return {
        "label": label,
        "status": status,
        "rationale": rationale,
    }


def apply_support_bundle(
    result: dict[str, Any],
    *,
    monitoring: dict[str, Any],
    transitions: list[dict[str, Any]],
    survivorship_risks: list[str] | None = None,
    palliative_flags: list[str] | None = None,
    care_overlays: list[dict[str, Any]] | None = None,
    source_citations: list[dict[str, Any]] | None = None,
    evidence_gaps: list[str] | None = None,
    objective_progression: dict[str, Any] | None = None,
    decision_changing_inputs: list[str] | None = None,
    supportive_evidence_context: list[str] | None = None,
    benchmarking_flags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    enriched = deepcopy(result)
    enriched["monitoring_plan"] = monitoring
    enriched["state_transition_targets"] = transitions
    enriched["survivorship_risks"] = survivorship_risks or []
    enriched["palliative_flags"] = palliative_flags or []
    enriched["care_overlays"] = care_overlays or []
    enriched["source_citations"] = source_citations or []
    enriched["evidence_gaps"] = evidence_gaps or []
    enriched["objective_progression"] = objective_progression or {}
    enriched["decision_changing_inputs"] = decision_changing_inputs or enriched.get("decision_changing_inputs", [])
    enriched["supportive_evidence_context"] = supportive_evidence_context or enriched.get("supportive_evidence_context", [])
    enriched["benchmarking_flags"] = benchmarking_flags or enriched.get("benchmarking_flags", [])
    return enriched


def support_bundle_for_module(module_id: str, payload: dict[str, Any], result: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    state_label = result.get("nccn_primary", {}).get("label", result.get("state", module_id))
    source_citations = evidence.get("source_citations", [])
    survivorship_risks: list[str] = []
    palliative_flags: list[str] = []
    overlays: list[dict[str, Any]] = []
    evidence_gaps: list[str] = []
    objective_progression = result.get("objective_progression", {})
    decision_changing_inputs: list[str] = []
    supportive_evidence_context: list[str] = []
    benchmarking_flags: list[dict[str, Any]] = []

    def _is_true(value: Any) -> bool:
        return str(value).lower() in {"1", "true", "yes", "si", "on"}

    def _missing(value: Any) -> bool:
        return value in (None, "", "Desconocida", "Desconocido", "No realizado", "No aplica")

    if module_id == "diagnostic_workup":
        monitoring = monitoring_plan(
            "Plan de estudio diagnóstico",
            "Revisión clínica y de biomarcadores en 6 a 12 semanas según el nivel de sospecha.",
            [
                "Repetir antígeno prostático específico y densidad del antígeno prostático específico si la sospecha es baja o límite.",
                "Confirmar resonancia magnética multiparamétrica antes de diferir biopsia cuando persista incertidumbre.",
                "Escalar a biopsia dirigida más biopsia sistemática cuando el riesgo de cáncer clínicamente significativo sea intermedio o alto.",
            ],
            [
                "Escalar si la resonancia magnética muestra PI-RADS 4 o 5.",
                "Escalar si la densidad del antígeno prostático específico es 0.15 o mayor o el tacto rectal es sospechoso.",
            ],
            ["EAU 2026 diagnóstico", "NCCN 5.2026 PROS-A/PROS-B"],
        )
        transitions = [
            state_transition("localized_initial", "Confirmación histológica de cáncer localizado", "Después de biopsia positiva", "Activa los módulos terapéuticos formales."),
            state_transition("post_negative_biopsy_followup", "Seguimiento tras biopsia benigna", "Si la biopsia es benigna", "Mantiene vigilancia de baja o moderada intensidad."),
        ]
        decision_changing_inputs = [
            "Documentar volumen prostático y calidad de la resonancia magnética multiparamétrica para sostener la densidad del antígeno prostático específico.",
            "Confirmar tipo y vía de biopsia antes de diferir confirmación histológica.",
        ]
        supportive_evidence_context = [
            "La recomendación principal sigue anclada a NCCN/EAU; los pathways MRI + PSAD y benchmarks externos solo refinan captura y experiencia de producto.",
        ]
        benchmarking_flags = [
            benchmark_flag("PSAD derivable", "complete" if not _missing(payload.get("prostate_volume_ml")) else "missing", "Se necesita volumen prostático para sostener la interpretación de PSAD."),
            benchmark_flag("Pathway MRI + calculadora", "complete" if str(payload.get("risk_calculator_pathway", "No usado")) != "No usado" else "missing", "Acerca el wizard a benchmarking tipo EAU/MSK sin desplazar la guía."),
        ]
        evidence_gaps = ["Añadir integración automatizada de captura de resonancia magnética multiparamétrica y tomografía por emisión de positrones dirigida al antígeno prostático específico de membrana desde documentos fuente."]
    elif module_id == "post_negative_biopsy_followup":
        monitoring = monitoring_plan(
            "Plan de seguimiento tras biopsia benigna",
            "Antígeno prostático específico cada 12 a 24 meses y resonancia magnética o rebiopsia solo si reaparece sospecha clínica.",
            [
                "Mantener seguimiento de baja intensidad cuando el antígeno prostático específico se mantiene por debajo de 10 y la densidad es menor de 0.15.",
                "Repetir resonancia magnética o biopsia si persiste elevación de antígeno prostático específico, densidad alta o tacto rectal sospechoso.",
            ],
            [
                "Escalar si el antígeno prostático específico supera 10 ng/mL.",
                "Escalar si la densidad del antígeno prostático específico es 0.15 o mayor o reaparece lesión sospechosa.",
            ],
            ["EAU 2026 seguimiento", "Palmstedt 2019"],
        )
        transitions = [
            state_transition("diagnostic_workup", "Reapertura del estudio diagnóstico", "Ante nueva sospecha", "Permite nueva imagen y eventual rebiopsia."),
        ]
        survivorship_risks = ["Ansiedad por el antígeno prostático específico y sobrediagnóstico si el seguimiento es demasiado intensivo."]
        decision_changing_inputs = [
            "Precisar fecha, tipo y número de biopsias previas antes de decidir rebiopsia.",
            "Confirmar si existe resonancia magnética posterior a biopsia con lesión persistente antes de subir intensidad.",
        ]
        supportive_evidence_context = [
            "Palmstedt 2019 y Canary PASS se usan como soporte de intensidad de seguimiento y benchmarking del flujo, no como reemplazo de la recomendación primaria.",
        ]
        benchmarking_flags = [
            benchmark_flag("Historial de biopsias capturado", "complete" if not _missing(payload.get("prior_biopsy_count")) else "missing", "Necesario para distinguir seguimiento prudente de repetición innecesaria."),
            benchmark_flag("Cinética de PSA documentada", "complete" if not _missing(payload.get("psa_velocity_ng_ml_year")) else "missing", "Refina el umbral para reactivar el estudio diagnóstico."),
        ]
    elif module_id == "localized_initial":
        as_selected = any(
            any(label in str(item.get("name", "")) for label in {"Vigilancia activa", "Active surveillance"})
            for item in result.get("eligible_treatments", [])
            if isinstance(item, dict)
        )
        prior_mpmri = _is_true(payload.get("prior_mpmri"))
        prior_pirads = str(payload.get("prior_mpmri_pirads_score", "desconocido") or "desconocido")
        targeted_status = str(payload.get("prior_mpmri_targeted_biopsy_status", "desconocido") or "desconocido")
        adverse_variant_type = str(payload.get("adverse_histology_variant_type", "none") or "none")
        if adverse_variant_type == "none" and _is_true(payload.get("rare_histology_variant")):
            adverse_variant_type = "other_aggressive_unspecified"
        monitoring = monitoring_plan(
            "Plan de seguimiento inicial",
            "Antígeno prostático específico cada 6 meses y tacto rectal anual en vigilancia activa; seguimiento según terapia definitiva si se elige tratamiento local.",
            [
                "Repetir biopsia confirmatoria o resonancia magnética en el horizonte de 6 a 24 meses si se elige vigilancia activa.",
                "Documentar función urinaria, intestinal, sexual y ansiedad por el antígeno prostático específico desde el inicio.",
            ],
            [
                "Escalar si hay upgrading, aumento del volumen tumoral, histología adversa o progresión clínica.",
                "Escalar a seguimiento posoperatorio o posradioterapia una vez que se realice tratamiento local.",
            ],
            ["NCCN 5.2026 localizado", "EAU 2026 tratamiento", "Olsson 2020"],
        )
        transitions = [
            state_transition("post_prostatectomy", "Seguimiento posterior a prostatectomía radical", "Si se realiza cirugía", "Cambia a la vía posoperatoria y activa CAPRA-S."),
            state_transition("recurrence_bcr", "Recurrencia bioquímica", "Si aparece persistencia o recurrencia bioquímica tras tratamiento local", "Activa rescate temprano y reestadificación."),
        ]
        survivorship_risks = [
            "Deterioro urinario, sexual o intestinal según la estrategia elegida.",
            "Ansiedad por el antígeno prostático específico y abandono de vigilancia activa si el monitoreo es inconsistente.",
        ]
        decision_changing_inputs = [
            "Capturar porcentaje de patrón 4 e histología adversa para afinar elegibilidad de vigilancia activa.",
            "Documentar PI-RADS de la resonancia magnética previa y si ya existió biopsia dirigida antes de sostener vigilancia activa.",
            "Documentar resultados reportados por el paciente basales antes de elegir cirugía, radioterapia o vigilancia activa.",
            "No sostener vigilancia activa expandida sin resonancia magnética previa y biopsia confirmatoria planificada.",
        ]
        supportive_evidence_context = [
            "Los benchmarks MSK y Canary PASS se usan para experiencia de producto y completitud, sin desplazar la recomendación principal de NCCN/EAU.",
        ]
        benchmarking_flags = [
            benchmark_flag("PROs basales", "complete" if not _missing(payload.get("baseline_urinary_qol")) else "missing", "Mejora comparabilidad funcional entre estrategias locales."),
            benchmark_flag("Biopsia confirmatoria planificada", "complete" if _is_true(payload.get("confirmatory_biopsy_planned")) else "missing", "Benchmark importante para vigilancia activa robusta."),
            benchmark_flag("Clasificador genómico documentado", "complete" if str(payload.get("genomic_classifier", "No realizado")) != "No realizado" else "missing", "Refinador opcional en decisiones limítrofes."),
            benchmark_flag("MRI previa documentada", "complete" if prior_mpmri else "missing", "Necesaria para una vigilancia activa más robusta en 2026."),
            benchmark_flag("PI-RADS previo documentado", "complete" if prior_mpmri and prior_pirads != "desconocido" else "missing" if prior_mpmri else "not_applicable", "Aclara si la vigilancia activa puede sostenerse con seguridad."),
            benchmark_flag("Biopsia dirigida previa documentada", "complete" if targeted_status == "si" else "incomplete" if prior_mpmri and prior_pirads in {"4", "5"} else "not_applicable", "Especialmente relevante cuando la resonancia magnética previa reporta PI-RADS 4 o 5."),
            benchmark_flag("Variante histológica especificada", "complete" if adverse_variant_type not in {"", "none"} else "not_applicable", "Evita dejar en binario una histología que cambia la conducta clínica."),
        ]
        if as_selected:
            overlays.append(
                care_overlay(
                    "survivorship_supportive_care",
                    "Soporte de vigilancia activa",
                    "activo",
                    ["Caso elegible o candidato seleccionado para vigilancia activa."],
                    [
                        "Aplicar EPIC-26 o FACT-P al ingreso y en revisiones seriadas.",
                        "Reforzar educación sobre disparadores de salida de vigilancia activa.",
                    ],
                )
            )
        if adverse_variant_type in {"small_cell_neuroendocrine", "sarcomatoid", "signet_ring", "mixed_multiple", "other_aggressive", "other_aggressive_unspecified"}:
            overlays.append(
                care_overlay(
                    "tumor_board",
                    "Revisión experta de histología adversa",
                    "pendiente",
                    ["La variante histológica documentada exige revisión de uropatología y discusión multidisciplinaria."],
                    ["Confirmar subtipo histológico, revalorar extensión local y definir si el caso debe salir del carril localizado estándar."],
                )
            )
    elif module_id == "post_prostatectomy":
        monitoring = monitoring_plan(
            "Plan posoperatorio",
            "Antígeno prostático específico ultrasensible seriado y revisión funcional urinaria y sexual.",
            [
                "Monitorizar persistencia del antígeno prostático específico y factores patológicos adversos.",
                "Planificar rescate temprano si el antígeno prostático específico es detectable o ascendente.",
            ],
            [
                "Escalar a recurrencia si el antígeno prostático específico persiste o asciende.",
                "Escalar soporte funcional si persisten incontinencia o disfunción sexual.",
            ],
            ["NCCN 5.2026 PROS-8/PROS-9", "EAU 2026 seguimiento y calidad de vida"],
        )
        transitions = [
            state_transition("recurrence_bcr", "Ruta de recurrencia bioquímica", "Si hay persistencia o recurrencia posoperatoria", "Permite rescate temprano y terapia adaptada al riesgo."),
        ]
        survivorship_risks = [
            "Incontinencia urinaria persistente o disfunción sexual tras prostatectomía radical.",
            "Necesidad de rehabilitación funcional y soporte psicosocial de supervivencia.",
        ]
        decision_changing_inputs = [
            "Definir localización del margen y riesgo genómico posoperatorio antes de discutir adyuvancia o rescate.",
            "Confirmar cronología de PSA ultrasensible y tiempo a recurrencia para evitar salidas indiferenciadas.",
        ]
        benchmarking_flags = [
            benchmark_flag("Decipher documentado", "complete" if not _missing(payload.get("decipher_risk")) and str(payload.get("decipher_risk")) != "No realizado" else "missing", "Refina las discusiones posoperatorias de riesgo."),
            benchmark_flag("PROs funcionales posoperatorios", "complete" if not _missing(payload.get("baseline_urinary_qol")) else "missing", "Hace visible el impacto funcional en el seguimiento."),
            benchmark_flag("Candidato a rescate pélvico documentado", "complete" if not _missing(payload.get("eligible_pelvic_therapy")) else "missing", "Aclara si la conversación debe girar hacia rescate temprano curativo."),
        ]
    elif module_id == "recurrence_bcr":
        monitoring = monitoring_plan(
            "Plan de recurrencia y rescate",
            "Antígeno prostático específico y testosterona seriados, imagen dirigida por riesgo y vigilancia de toxicidad de rescate.",
            [
                "Confirmar si la recurrencia es posterior a cirugía, posterior a radioterapia o segunda recurrencia bioquímica.",
                "Usar imagen y cinética del antígeno prostático específico para decidir rescate local frente a vía sistémica.",
            ],
            [
                "Escalar a enfermedad metastásica sensible a la castración si aparece metástasis.",
                "Escalar a overlay paliativo si hay dolor, deterioro funcional o recaída rápida sintomática.",
            ],
            ["NCCN 5.2026 PROS-9 a PROS-12", "EAU 2026 recurrencia bioquímica"],
        )
        transitions = [
            state_transition("mcspc_oligo_metachronous", "Enfermedad oligometastásica metacrónica sensible a la castración", "Si aparece diseminación oligometastásica", "Abre discusión de terapia dirigida a metástasis."),
            state_transition("m0_crpc", "Enfermedad resistente a la castración sin metástasis", "Si se documenta resistencia a la castración sin metástasis visibles", "Activa secuenciación de agentes hormonales."),
        ]
        survivorship_risks = [
            "Toxicidad urinaria, intestinal y sexual asociada a radioterapia de rescate o terapia sistémica.",
            "Ansiedad por recaída y fatiga por tratamientos prolongados.",
        ]
        decision_changing_inputs = [
            "Confirmar modalidad de imagen, imagen convencional M0 y factibilidad real de rescate local antes de activar una ruta sistémica de BCR2.",
            "Documentar tiempo a recurrencia y criterio exacto de BCR2 para no sobretratar rescates pélvicos potencialmente curativos.",
        ]
        supportive_evidence_context = [
            "APCCC 2024 se usa como consenso de apoyo en zonas grises, sin reemplazar la jerarquía principal de NCCN/EAU.",
        ]
        benchmarking_flags = [
            benchmark_flag("Criterios exactos de BCR2", "complete" if _is_true(payload.get("bcr2")) and not _missing(payload.get("psadt_months")) else "incomplete", "La ruta sistémica solo debe abrirse cuando el escenario BCR2 esté bien documentado."),
            benchmark_flag("Imagen documentada", "complete" if not _missing(payload.get("imaging_modality")) else "missing", "Aclara rescate local frente a transición sistémica."),
            benchmark_flag("Salvage local documentado", "complete" if not _missing(payload.get("salvage_local_feasible")) else "missing", "EMBARK solo debe abrirse si no queda rescate curativo razonable."),
            benchmark_flag("PSMA-PET alineado a decisión", "complete" if _is_true(payload.get("psma_pet_done")) or not _missing(payload.get("psma_pet_result")) else "incomplete", "La imagen avanzada debe justificarse por cambio de conducta, no por rutina."),
        ]
    elif module_id == "adt_progression_verification":
        monitoring = monitoring_plan(
            "Plan de verificación bajo ADT",
            "Testosterona, antígeno prostático específico y reestadificación convencional en el corto plazo antes de mover el caso a una ruta CRPC definitiva.",
            [
                "Revisar adherencia, fecha de la última aplicación de ADT, mecanismo de castración y contexto real de progresión.",
                "No etiquetar CRPC si la testosterona aún no está documentada en rango de castración.",
            ],
            [
                "Redirigir a M0 CRPC si se confirma castración adecuada e imagen convencional M0.",
                "Redirigir a M1 CRPC si se confirma castración adecuada e imagen convencional M1.",
            ],
            ["NCCN 5.2026 CRPC", "EAU 2026 castration-resistant disease"],
        )
        transitions = [
            state_transition("m0_crpc", "Enfermedad resistente a la castración sin metástasis", "Si se confirma castración e imagen convencional M0", "Abre la ruta M0 CRPC con decisión adaptada al riesgo."),
            state_transition("m1_crpc", "Enfermedad resistente a la castración con metástasis", "Si se confirma castración e imagen convencional M1", "Abre la secuenciación avanzada guiada por biomarcadores."),
        ]
        decision_changing_inputs = [
            "Confirmar testosterona en rango de castración antes de asignar CRPC.",
            "Definir si la imagen convencional es M0 o M1 antes de abrir la ruta resistente correcta.",
            "Documentar fecha de la última ADT y patrón real de progresión antes de intensificar.",
        ]
        supportive_evidence_context = [
            "Las guías primarias exigen progresión con testosterona en rango de castración antes de catalogar CRPC.",
            "Las referencias regulatorias de nmCRPC solo deben aplicarse después de completar esta verificación.",
        ]
        benchmarking_flags = [
            benchmark_flag("Castración documentada", "complete" if str(payload.get("castrate_testosterone_status", "unknown")) == "confirmed_castrate" else "missing", "No debe abrirse CRPC sin esta verificación."),
            benchmark_flag("Imagen convencional documentada", "complete" if str(payload.get("conventional_imaging_status", "not_restaged")) in {"M0", "M1"} else "missing", "Separa M0 CRPC de M1 CRPC."),
            benchmark_flag("Fecha de ADT documentada", "complete" if not _missing(payload.get("last_adt_date")) else "missing", "Ayuda a detectar fracaso real de supresión androgénica."),
        ]
    elif module_id in {"mcspc_oligo_metachronous", "mcspc_low_volume_sync_oligo", "mcspc_high_volume"}:
        monitoring = monitoring_plan(
            "Plan de vigilancia metastásica sensible a la castración",
            "Evaluación clínica, laboratorio y síntomas cada 1 a 3 meses con reestadificación guiada por progresión o toxicidad.",
            [
                "Registrar dolor, estado funcional, fosfatasa alcalina, hemoglobina y complicaciones estructurales.",
                "No detener terapia solo por antígeno prostático específico; correlacionar con imagen y deterioro clínico.",
            ],
            [
                "Escalar a enfermedad resistente a la castración si hay testosterona suprimida y progresión objetiva.",
                "Escalar overlay paliativo si existe dolor óseo, compresión medular, fractura o deterioro funcional.",
            ],
            ["EAU 2026 enfermedad metastásica", "NCCN 5.2026 PROS-13 a PROS-15"],
        )
        transitions = [
            state_transition("m1_crpc", "Enfermedad resistente a la castración con metástasis", "Si hay progresión con testosterona de castración", "Activa la secuenciación de enfermedad resistente."),
        ]
        survivorship_risks = [
            "Fatiga, toxicidad metabólica y cardiovascular por terapia de privación androgénica prolongada.",
            "Complicaciones esqueléticas y deterioro de calidad de vida si no se vigila el dolor ni el estado funcional.",
        ]
        decision_changing_inputs = [
            "No escalar a triplete o doblete intensivo sin documentar fragilidad, riesgo cardiovascular e interacciones farmacológicas.",
            "Capturar calidad de vida basal antes de elegir intensificación sostenida.",
            "Documentar DXA, calcio/vitamina D y protección ósea antes de normalizar secuencias prolongadas en enfermedad metastásica.",
        ]
        supportive_evidence_context = [
            "APCCC 2024 orienta consenso en zonas grises; los documentos de cardiotoxicidad, fragilidad, interacciones y hepatotoxicidad solo modulan seguridad y monitoreo.",
            "El estudio real-world de mHSPC se usa para benchmarking operativo de adopción, no para desplazar la recomendación primaria.",
        ]
        benchmarking_flags = [
            benchmark_flag("Riesgo cardiovascular documentado", "complete" if _is_true(payload.get("cv_risk_documented")) or _is_true(payload.get("comorbidity_cardio")) else "missing", "Base mínima para cardio-oncología al usar ARPI o abiraterona."),
            benchmark_flag("Revisión de interacciones", "complete" if _is_true(payload.get("drug_interaction_reviewed")) else "missing", "Evita toxicidad oculta por polifarmacia."),
            benchmark_flag("PRO basal", "complete" if not _missing(payload.get("baseline_qol")) else "missing", "Benchmark de seguimiento funcional en enfermedad avanzada."),
            benchmark_flag("DXA basal", "complete" if _is_true(payload.get("dxa_baseline_done")) else "missing", "Hace visible la prevención ósea temprana."),
            benchmark_flag("Calcio y vitamina D", "complete" if _is_true(payload.get("calcium_vitd_started")) else "missing", "Bundle mínimo de salud ósea."),
            benchmark_flag("Protección ósea iniciada", "complete" if _is_true(payload.get("bone_protection_started")) else "missing", "Mide qué tan cerca está la práctica real del soporte óseo esperado."),
        ]
        overlays.extend(
            [
                care_overlay(
                    "bone_health",
                    "Salud ósea y prevención estructural",
                    "activo" if _is_true(payload.get("calcium_vitd_started")) or _is_true(payload.get("bone_protection_started")) else "pendiente",
                    ["Toda enfermedad metastásica sensible a la castración requiere revisión de dolor, riesgo esquelético y ejercicio estructurado."],
                    ["Documentar DXA basal, calcio/vitamina D, evaluar necesidad de agentes óseo-dirigidos y reforzar ejercicio supervisado."],
                ),
                care_overlay(
                    "rehab_qol",
                    "Rehabilitación y calidad de vida",
                    "pendiente" if _missing(payload.get("baseline_qol")) else "monitoreado",
                    ["La calidad de vida basal debe acompañar la selección de intensificación sistémica."],
                    ["Capturar FACT-P, EQ-5D o EPIC-26 basal y repetir en visitas seriadas."],
                ),
            ]
        )
        if module_id == "mcspc_high_volume" or any("dolor" in item.lower() for item in result.get("contraindications", [])):
            palliative_flags.append("Vigilar necesidad precoz de radioterapia paliativa, prevención de fractura patológica y compresión medular.")
    elif module_id == "m0_crpc":
        monitoring = monitoring_plan(
            "Plan de enfermedad resistente a la castración sin metástasis",
            "Antígeno prostático específico, testosterona, estado funcional y eventos adversos cada 1 a 3 meses; imagen periódica guiada por riesgo.",
            [
                "Mantener terapia de privación androgénica como columna basal.",
                "Reevaluar caídas, fatiga, estado cognitivo y riesgo convulsivo durante terapia hormonal intensificada.",
            ],
            [
                "Escalar a enfermedad resistente a la castración con metástasis si aparece progresión radiográfica.",
                "Escalar overlay de soporte si aparecen caídas, fracturas o toxicidad neurocognitiva.",
            ],
            ["NCCN 5.2026 PROS-16", "EAU 2026 enfermedad resistente a la castración"],
        )
        transitions = [
            state_transition("m1_crpc", "Enfermedad resistente a la castración con metástasis", "Si la imagen demuestra metástasis", "Activa terapias guiadas por biomarcadores y secuenciación."),
        ]
        survivorship_risks = [
            "Fatiga, caídas, deterioro cognitivo y toxicidad metabólica durante terapia hormonal de larga duración.",
        ]
        decision_changing_inputs = [
            "Confirmar testosterona en rango de castración antes de etiquetar enfermedad resistente a la castración sin metástasis.",
            "No subir intensidad sin documentar riesgo convulsivo, fragilidad y riesgo cardiovascular basal.",
        ]
        supportive_evidence_context = [
            "Los documentos de cardiotoxicidad, fragilidad y revisión de interacciones solo modulan seguridad y monitoreo; NCCN/EAU conservan la recomendación principal.",
        ]
        benchmarking_flags = [
            benchmark_flag("Confirmación de castración", "complete" if _is_true(payload.get("castrate_testosterone_confirmed")) else "missing", "Evita clasificar erróneamente un estado no resistente."),
            benchmark_flag("Riesgo cardiovascular documentado", "complete" if _is_true(payload.get("cv_risk_documented")) else "missing", "Refuerza cardio-oncología antes de ARPI."),
            benchmark_flag("Interacciones revisadas", "complete" if _is_true(payload.get("drug_interaction_reviewed")) else "missing", "Evita toxicidad farmacológica prevenible."),
        ]
    elif module_id == "m1_crpc":
        monitoring = monitoring_plan(
            "Plan de enfermedad resistente a la castración con metástasis",
            "Evaluación clínica, laboratorio y revisión de síntomas cada 1 a 2 meses, con imagen cada 3 a 6 meses o antes si existe deterioro clínico.",
            [
                "Registrar dolor, uso de opioides, hemoglobina, creatinina, fosfatasa alcalina y toxicidades hematológicas.",
                "Decidir cambio terapéutico por combinación de progresión bioquímica, radiográfica y clínica, no por antígeno prostático específico aislado.",
            ],
            [
                "Activar soporte óseo si hay metástasis óseas o tratamiento con terapia de privación androgénica prolongada.",
                "Activar cuidados paliativos concurrentes si existe dolor, deterioro funcional o complicación estructural.",
            ],
            ["NCCN 5.2026 PROS-17/PROS-18", "EAU 2026 seguimiento de enfermedad resistente a la castración"],
        )
        transitions = [
            state_transition("m1_crpc", "Secuenciación terapéutica dentro del mismo estado", "Tras progresión objetiva", "La enfermedad mantiene el mismo estado, pero cambia la clase terapéutica activa."),
        ]
        survivorship_risks = [
            "Anemia, fatiga, eventos tromboembólicos, toxicidad hematológica y deterioro funcional progresivo.",
            "Complicaciones esqueléticas, dolor refractario y carga del cuidador en enfermedad avanzada.",
        ]
        palliative_flags.extend(
            [
                "Evaluar dolor óseo, radioterapia paliativa, compresión medular y objetivos de cuidado en cada revisión.",
                "No retrasar cuidados paliativos concurrentes cuando exista alta carga sintomática.",
            ]
        )
        decision_changing_inputs = [
            "Confirmar testosterona en rango de castración antes de secuenciar como enfermedad resistente a la castración con metástasis.",
            "Confirmar gen HRR y fuente del biomarcador antes de activar ruta PARP.",
            "Confirmar positividad PSMA sin lesiones dominantes PSMA-negativas antes de priorizar lutecio-177 PSMA-617.",
            "No subir intensidad sin documentar fragilidad, riesgo cardiovascular, interacciones farmacológicas y riesgo hepático.",
        ]
        supportive_evidence_context = [
            "CARD favorece cabazitaxel sobre intercambiar otro ARPI tras docetaxel y ARPI previo.",
            "VISION exige selección estructurada con PSMA positivo y exclusión de lesiones dominantes PSMA-negativas.",
            "PROfound exige biomarcador HRR trazable por gen y por fuente analítica.",
            "Los documentos de cardiotoxicidad, fragilidad, interacciones y hepatotoxicidad generan overlays de seguridad y monitoreo, no reemplazan la ruta principal de guías.",
        ]
        benchmarking_flags = [
            benchmark_flag("HRR trazable", "complete" if not _missing(payload.get("hrr_gene")) and not _missing(payload.get("biomarker_source")) else "missing", "Necesario antes de PARP."),
            benchmark_flag("Elegibilidad PSMA documentada", "complete" if _is_true(payload.get("psma_positive")) and not _is_true(payload.get("psma_negative_dominant_lesions")) else "missing", "Necesario antes de radioligando dirigido."),
            benchmark_flag("Riesgo cardiovascular documentado", "complete" if _is_true(payload.get("cv_risk_documented")) else "missing", "Seguridad basal para secuencias prolongadas."),
            benchmark_flag("Revisión de interacciones", "complete" if _is_true(payload.get("drug_interaction_reviewed")) else "missing", "Reduce polifarmacia de alto riesgo."),
            benchmark_flag("Bundle hepático basal", "complete" if _is_true(payload.get("hepatic_risk_factors")) or str(payload.get("child_pugh_score", "A")) != "A" else "incomplete", "Permite vigilar hepatotoxicidad si se usa abiraterona."),
            benchmark_flag("Castración confirmada", "complete" if _is_true(payload.get("castrate_testosterone_confirmed")) else "missing", "Evita reclasificar erróneamente el estado clínico."),
            benchmark_flag("Contexto de línea mCRPC", "complete" if not _missing(payload.get("mcrpc_line_context")) else "missing", "Ordena rutas pre-taxano, post-taxano y PARP de primera línea."),
            benchmark_flag("Informe molecular fechado", "complete" if not _missing(payload.get("molecular_report_date")) else "missing", "Mejora trazabilidad clínica y regulatoria."),
        ]
        overlays.extend(
            [
                care_overlay(
                    "cardio_oncology",
                    "Bundle de cardio-oncología",
                    "pendiente" if not _is_true(payload.get("cv_risk_documented")) else "activo",
                    ["La intensificación hormonal y la secuenciación avanzada elevan el peso clínico del riesgo cardiovascular."],
                    ["Documentar presión arterial, antecedente cardiovascular, fármacos concomitantes y plan de seguimiento seriado."],
                ),
                care_overlay(
                    "frailty_geriatric",
                    "Bundle de fragilidad y geriatría",
                    "activo" if str(payload.get("frailty_status", "Fit")) in {"Vulnerable", "Frail"} else "pendiente",
                    ["La fragilidad y las comorbilidades específicas cambian tolerabilidad real aun cuando la recomendación primaria no cambie."],
                    ["Aplicar evaluación geriátrica breve, revisar sarcopenia, soporte nutricional y metas del paciente."],
                ),
                care_overlay(
                    "drug_interaction_review",
                    "Revisión de interacciones farmacológicas",
                    "pendiente" if not _is_true(payload.get("drug_interaction_reviewed")) else "activo",
                    ["La polifarmacia modifica exposición a ARPI y toxicidad."],
                    ["Revisar CYP, anticoagulantes, anticonvulsivos y tratamientos cardiovasculares antes de iniciar o secuenciar ARPI."],
                ),
                care_overlay(
                    "hepatic_monitoring",
                    "Monitoreo hepático si se usa abiraterona",
                    "activo",
                    ["La hepatotoxicidad por abiraterona exige seguimiento más estrecho al inicio y ante factores de riesgo."],
                    ["Solicitar pruebas de función hepática basales y repetirlas en semanas 4 a 8 o antes si aparece toxicidad."],
                ),
                care_overlay(
                    "bone_health",
                    "Protección ósea y prevención de eventos esqueléticos",
                    "activo",
                    ["La carga ósea sintomática y las secuencias largas aumentan eventos estructurales y necesidad de soporte concomitante."],
                    ["Documentar dolor, riesgo de fractura, vitamina D/calcio y necesidad de radioterapia paliativa o agentes óseo-dirigidos."],
                ),
                care_overlay(
                    "rehab_qol",
                    "Rehabilitación y calidad de vida",
                    "pendiente" if _missing(payload.get("baseline_qol")) else "activo",
                    ["El monitoreo funcional y la calidad de vida deben acompañar cualquier secuencia avanzada prolongada."],
                    ["Capturar FACT-P o EQ-5D basal y repetirlo durante progresión o cambio de línea."],
                ),
                care_overlay(
                    "palliative_care",
                    "Soporte paliativo concurrente",
                    "vigilancia reforzada",
                    ["Estado avanzado con necesidad de vigilancia estrecha de síntomas y complicaciones estructurales."],
                    [
                        "Aplicar BPI-SF y resultados reportados por el paciente en cada revisión.",
                        "Evaluar necesidad de radioterapia paliativa, soporte óseo y conversación de objetivos de cuidado.",
                    ],
                ),
            ]
        )
    else:
        monitoring = monitoring_plan(
            "Plan longitudinal estructurado",
            "Seguimiento adaptado al estado clínico vigente.",
            ["Conservar trazabilidad entre módulo, evaluación y perfil longitudinal."],
            ["Reevaluar al cambiar síntomas, biomarcadores o imagen."],
            ["ProstaNet 2026"],
        )
        transitions = []

    # ── CCI/G8 benchmarking flags for all modules ──
    _age_for_g8 = 0
    try:
        _age_for_g8 = int(float(payload.get("age") or payload.get("edad") or 0))
    except (ValueError, TypeError):
        pass
    if _age_for_g8 >= 70:
        benchmarking_flags.append(
            benchmark_flag("G8 Geriatric Screening", "complete" if not _missing(payload.get("g8_score")) else "missing", "Paciente ≥70 años: documentar G8 antes de intensificar tratamiento (corte ≤14 = fragilidad).")
        )
    if module_id not in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        benchmarking_flags.append(
            benchmark_flag("Charlson Comorbidity Index", "complete" if not _missing(payload.get("charlson_score")) else "missing", "CCI ajustado por edad modula la tolerabilidad e intensidad terapéutica.")
        )

    return {
        "monitoring": monitoring,
        "transitions": transitions,
        "survivorship_risks": survivorship_risks,
        "palliative_flags": palliative_flags,
        "care_overlays": overlays,
        "source_citations": source_citations,
        "evidence_gaps": evidence_gaps,
        "objective_progression": objective_progression,
        "state_label": state_label,
        "decision_changing_inputs": decision_changing_inputs,
        "supportive_evidence_context": supportive_evidence_context,
        "benchmarking_flags": benchmarking_flags,
    }
