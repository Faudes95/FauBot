from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any

from prostanet.shared.contracts import (
    AgendaItem,
    FieldSpec,
    InstitutionalComparator,
    StageProtocolDefinition,
    TherapyCheckpoint,
    VisitBundle,
)


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
LOCALIZED_STATES = {"localized_initial"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr"}
ADVANCED_STATES = {
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
}

MANAGEMENT_TRACK_LABELS = {
    "diagnostic_surveillance": "Ruta diagnóstica activa",
    "rebiopsy_surveillance": "Seguimiento tras biopsia benigna",
    "localized_decision": "Decisión local activa",
    "active_surveillance": "Vigilancia activa",
    "pre_surgery": "Preparación prequirúrgica",
    "post_rp": "Seguimiento post prostatectomía radical",
    "post_rt": "Seguimiento post radioterapia",
    "salvage": "Ruta de rescate",
    "on_arpi": "Tratamiento activo con ARPI",
    "on_docetaxel": "Tratamiento activo con quimioterapia",
    "on_parp": "Tratamiento activo con PARP",
    "on_lu177": "Tratamiento activo con Lutecio-177",
    "systemic_surveillance": "Seguimiento sistémico activo",
    "palliative_overlay": "Overlay paliativo concurrente",
}

COMMON_IMAGING_LOCATIONS = [
    "Lecho prostático",
    "Ganglios pélvicos",
    "Ganglios retroperitoneales",
    "Hueso axial",
    "Hueso apendicular",
    "Pulmón",
    "Hígado",
    "Suprarrenal",
    "Otra visceral",
]


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _fmt_date(value: date | None) -> str:
    return value.isoformat() if value else ""


def _add_months(base: date, months: int) -> date:
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _latest_by(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if _is_present(value):
            return value
    return ""


def _treatment_text(patient: dict[str, Any]) -> str:
    treatments = patient.get("treatments") or []
    if treatments:
        return str((treatments[-1] or {}).get("drug_scheme") or "")
    follow_ups = patient.get("follow_ups") or []
    if follow_ups:
        return str((follow_ups[-1] or {}).get("current_treatment") or "")
    return ""


def infer_management_track(patient: dict[str, Any], state: str, raw_assessment: dict[str, Any] | None = None) -> str:
    payload = (raw_assessment or {}).get("input_snapshot", {}) if raw_assessment else {}
    treatment_text = _treatment_text(patient).lower()
    overlays = patient.get("care_overlays") or []
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    pain_score = _safe_float(latest_followup.get("pain_score"))
    if any("pali" in str(item.get("title", "")).lower() for item in overlays) or (pain_score is not None and pain_score >= 7):
        return "palliative_overlay"
    if state == "diagnostic_workup":
        return "diagnostic_surveillance"
    if state == "post_negative_biopsy_followup":
        return "rebiopsy_surveillance"
    if state == "localized_initial":
        active_surveillance = patient.get("active_surveillance") or {}
        if str(active_surveillance.get("current_status", "")).lower() == "activo":
            return "active_surveillance"
        eligible = ((raw_assessment or {}).get("result_snapshot", {}) or {}).get("eligible_treatments", []) or []
        eligible_names = " ".join(str(item.get("name", "")) for item in eligible if isinstance(item, dict)).lower()
        if "prostatectomy" in eligible_names or "cirug" in eligible_names:
            return "pre_surgery"
        return "localized_decision"
    if state == "post_prostatectomy":
        return "post_rp"
    if state == "recurrence_bcr":
        radiation = patient.get("radiation") or []
        if radiation and not patient.get("surgery"):
            return "post_rt"
        return "salvage"
    if "lutec" in treatment_text or "pluvicto" in treatment_text:
        return "on_lu177"
    if any(token in treatment_text for token in ("olaparib", "talazoparib", "niraparib")):
        return "on_parp"
    if any(token in treatment_text for token in ("docetaxel", "cabazitaxel")):
        return "on_docetaxel"
    if any(token in treatment_text for token in ("apalutamide", "enzalutamide", "darolutamide", "abiraterone", "abiraterona", "bicalutamide", "bicalutamida")):
        return "on_arpi"
    return "systemic_surveillance"


def _field(name: str, label: str, field_type: str, **kwargs: Any) -> dict[str, Any]:
    return FieldSpec(name=name, label=label, field_type=field_type, **kwargs).to_dict()


def build_visit_schema(state: str, management_track: str) -> dict[str, Any]:
    sections = [
        {
            "title": "Contexto de la visita",
            "subtitle": "Hechos mínimos para ubicar esta visita en el longitudinal.",
            "fields": [
                _field("visit_date", "Fecha de visita", "date", required=True),
                _field(
                    "disease_status",
                    "Estado clínico resumido",
                    "select",
                    options=[
                        "Seguimiento estable",
                        "Respuesta",
                        "Progresión bioquímica",
                        "Progresión radiográfica",
                        "Toxicidad limitante",
                        "Pendiente de confirmación",
                    ],
                    required=True,
                    default="Seguimiento estable",
                ),
                _field("current_treatment", "Tratamiento actual", "text"),
                _field("clinician_notes", "Notas clínicas", "textarea"),
            ],
        }
    ]

    if state in DIAGNOSTIC_STATES:
        sections.append(
            {
                "title": "Ruta diagnóstica activa",
                "subtitle": "Captura solo datos que cambian la decisión diagnóstica hoy.",
                "fields": [
                    _field("psa", "PSA actual", "number", unit="ng/mL"),
                    _field("psad", "Densidad de PSA", "number"),
                    _field("mpmri_quality", "Calidad de MRI multiparamétrica", "select", options=["Adecuada", "Subóptima", "No realizada"]),
                    _field("pirads_score", "PI-RADS", "select", options=["", "2", "3", "4", "5"]),
                    _field("index_lesion_location", "Localización de lesión índice", "text"),
                    _field("index_lesion_size_mm", "Tamaño de lesión índice", "number", unit="mm"),
                    _field("prostate_volume_ml", "Volumen prostático", "number", unit="mL"),
                    _field("planned_biopsy_type", "Tipo de biopsia prevista", "select", options=["", "Sistemática", "Dirigida + sistemática", "Transperineal", "Transrectal"]),
                    _field("planned_biopsy_route", "Vía prevista de biopsia", "select", options=["", "Transperineal", "Transrectal"]),
                    _field("family_history_detail", "Historia familiar / germinal relevante", "textarea"),
                ],
            }
        )
    elif state == "localized_initial":
        localized_fields = [
            _field("psa", "PSA actual", "number", unit="ng/mL"),
            _field("prior_mpmri_pirads_score", "PI-RADS previo", "select", options=["", "2", "3", "4", "5", "desconocido"]),
            _field("prior_mpmri_targeted_biopsy_status", "Biopsia dirigida previa", "select", options=["", "si", "no", "desconocido"]),
            _field("precise_score", "PRECISE", "select", options=["", "1", "2", "3", "4", "5"]),
            _field("percent_pattern_4", "Porcentaje de patrón 4", "number", unit="%"),
            _field("cribriform_pattern", "Patrón cribriforme", "checkbox"),
            _field("intraductal_carcinoma", "Carcinoma intraductal", "checkbox"),
            _field(
                "adverse_histology_variant_type",
                "Variante histológica adversa",
                "select",
                options=[
                    "none",
                    "ductal_predominant",
                    "sarcomatoid",
                    "signet_ring",
                    "adenosquamous_or_squamous",
                    "basal_cell",
                    "mucinous_colloid",
                    "small_cell_neuroendocrine",
                    "mixed_multiple",
                    "other_aggressive",
                ],
                default="none",
            ),
            _field("adverse_histology_variant_detail", "Detalle histológico", "textarea"),
            _field("ipss_total", "IPSS actual", "number"),
            _field("iief5_score", "IIEF-5 actual", "number"),
            _field("eq5d_vas", "EQ-5D VAS", "number"),
            _field("fact_p_total", "FACT-P", "number"),
            _field("genomic_classifier", "Clasificador genómico documentado", "select", options=["", "Decipher", "Oncotype DX Prostate", "Prolaris"]),
            _field("genomic_classifier_result", "Resultado documentado", "text"),
        ]
        sections.append(
            {
                "title": "Decisión local y vigilancia",
                "subtitle": "Variables anatómicas, patológicas y funcionales que definen la ruta local.",
                "fields": localized_fields,
            }
        )
    elif state == "post_prostatectomy":
        sections.append(
            {
                "title": "Seguimiento post prostatectomía radical",
                "subtitle": "PSA ultrasensible, recuperación funcional y datos patológicos si siguen faltando.",
                "fields": [
                    _field("psa", "PSA ultrasensible", "number", unit="ng/mL"),
                    _field("pad_usage", "Pads/día", "number"),
                    _field("continence_status", "Continencia", "select", options=["", "Continente", "Leve", "Moderada", "Severa"]),
                    _field("iief5_score", "IIEF-5 actual", "number"),
                    _field("pde5i_use", "Uso de PDE5i", "checkbox"),
                    _field("surgery_type", "Tipo de cirugía", "text"),
                    _field("surgical_approach", "Abordaje", "select", options=["", "Abierta", "Laparoscópica", "Robótica"]),
                    _field("nerve_sparing", "Preservación nerviosa", "text"),
                    _field("nodes_removed", "Ganglios resecados", "number"),
                    _field("nodes_positive", "Ganglios positivos", "number"),
                    _field("margin_location", "Localización del margen", "text"),
                    _field("capra_s_score", "CAPRA-S", "number"),
                    _field("decipher_risk", "Decipher documentado", "text"),
                ],
            }
        )
    elif management_track in {"post_rt", "salvage"}:
        sections.append(
            {
                "title": "Seguimiento post radioterapia / rescate",
                "subtitle": "Toxicidad GU/GI, fraccionamiento si faltó capturarse y recuperación funcional.",
                "fields": [
                    _field("psa", "PSA actual", "number", unit="ng/mL"),
                    _field("rt_context", "Contexto de RT", "select", options=["", "Primaria", "Adyuvante", "Salvamento", "Paliativa"]),
                    _field("fractions", "Número de sesiones", "number"),
                    _field("total_dose_gy", "Dosis total", "number", unit="Gy"),
                    _field("dose_per_fraction_gy", "Dosis por fracción", "number", unit="Gy"),
                    _field("session_duration_minutes", "Duración promedio de sesión", "number", unit="min"),
                    _field("hematuria", "Hematuria", "select", options=["", "No", "Leve", "Moderada", "Severa"]),
                    _field("dysuria", "Disuria", "select", options=["", "No", "Leve", "Moderada", "Severa"]),
                    _field("anemia_rt", "Anemia relacionada", "select", options=["", "No", "Sí"]),
                    _field("gu_toxicity_grade", "Toxicidad GU", "number"),
                    _field("gi_toxicity_grade", "Toxicidad GI", "number"),
                    _field("eq5d_vas", "EQ-5D VAS", "number"),
                ],
            }
        )
    else:
        sections.append(
            {
                "title": "Seguimiento sistémico",
                "subtitle": "Laboratorio, seguridad y carga tumoral por modalidad activa.",
                "fields": [
                    _field("psa", "PSA actual", "number", unit="ng/mL"),
                    _field("testosterone", "Testosterona", "number", unit="ng/dL"),
                    _field("creatinine", "Creatinina", "number", unit="mg/dL"),
                    _field("cystatin_c", "Cistatina C", "number", unit="mg/L"),
                    _field("alp", "ALP", "number", unit="UI/L"),
                    _field("ldh", "LDH", "number", unit="UI/L"),
                    _field("bilirubin", "Bilirrubina", "number", unit="mg/dL"),
                    _field("ast", "AST", "number", unit="UI/L"),
                    _field("alt", "ALT", "number", unit="UI/L"),
                    _field("ggt", "GGT", "number", unit="UI/L"),
                    _field("glucose", "Glucosa", "number", unit="mg/dL"),
                    _field("hemoglobin", "Hemoglobina", "number", unit="g/dL"),
                    _field("pain", "Dolor", "number", unit="0-10"),
                    _field("ecog", "ECOG", "select", options=["", "0", "1", "2", "3", "4"]),
                    _field("frailty_status", "Fragilidad", "select", options=["", "fit", "vulnerable", "frail"]),
                    _field("cv_risk_documented", "Riesgo CV documentado", "checkbox"),
                    _field("drug_interaction_reviewed", "Revisión de interacciones", "checkbox"),
                    _field("hepatic_risk_factors", "Riesgo hepático", "text"),
                    _field("weight_kg", "Peso", "number", unit="kg"),
                    _field("bmi_current", "BMI", "number"),
                    _field("weight_loss_6m_pct", "Pérdida ponderal 6 meses", "number", unit="%"),
                    _field("exercise_status", "Actividad física", "select", options=["", "No realiza", "Ligera", "Moderada", "Intensa"]),
                    _field("nutrition_status", "Estado nutricional", "select", options=["", "Adecuado", "Sobrepeso", "Desnutrición", "Riesgo"]),
                    _field("protein_supplements", "Suplementos proteicos", "checkbox"),
                    _field("mini_cog_score", "Mini-Cog", "number"),
                    _field("fatigue_score", "Brief Fatigue Inventory", "number"),
                    _field("seizure_history", "Antecedente convulsivo", "checkbox"),
                    _field("dermatitis_history", "Dermatitis / rash previo", "checkbox"),
                    _field("opioid_use", "Uso de opioides", "select", options=["", "No", "PRN", "Crónico"]),
                ],
            }
        )
        sections.append(
            {
                "title": "Imagen oncológica opcional de esta visita",
                "subtitle": "Si hoy se revisó imagen, persístela de manera estructurada para volumen y distribución.",
                "fields": [
                    _field("imaging_modality", "Modalidad revisada", "select", options=["", "PSMA-PET", "Gammagrama óseo", "TAC convencional"]),
                    _field("psma_suv_max", "SUV max", "number"),
                    _field("psma_suv_bucket", "Bucket SUV", "select", options=["", "<6", "6-9", "9-12", ">12"]),
                    _field("psma_total_lesions", "Número total de lesiones PSMA", "number"),
                    _field("psma_lesion_locations", "Ubicación de lesiones PSMA", "multi_select", options=COMMON_IMAGING_LOCATIONS),
                    _field("psma_negative_dominant_lesions", "Lesiones dominantes PSMA negativas", "checkbox"),
                    _field("bone_lesion_count", "Lesiones positivas en gammagrama", "number"),
                    _field("bone_distribution", "Distribución ósea", "multi_select", options=COMMON_IMAGING_LOCATIONS),
                    _field("ct_summary", "Resumen TAC", "select", options=["", "Sin lesiones sospechosas", "Ganglios sospechosos", "Metástasis"]),
                    _field("ct_locations", "Ubicación de hallazgos TAC", "multi_select", options=COMMON_IMAGING_LOCATIONS),
                ],
            }
        )

    return VisitBundle(
        state=state,
        management_track=management_track,
        sections=sections,
    ).to_dict()


def _agenda_item(
    agenda_key: str,
    item_type: str,
    title: str,
    state: str,
    management_track: str,
    base_date: date | None,
    interval_days: int,
    *,
    priority: str = "routine",
    summary: str = "",
    required_inputs: list[str] | None = None,
    completion_rule: dict[str, Any] | None = None,
    evidence_basis: list[str] | None = None,
    comparator_basis: list[str] | None = None,
    generated_from_event: str = "",
    blockers: list[str] | None = None,
    reasoning: list[str] | None = None,
) -> dict[str, Any]:
    today = date.today()
    due_at = (base_date or today) + timedelta(days=interval_days)
    window_start = due_at - timedelta(days=14)
    window_end = due_at + timedelta(days=30)
    status = "scheduled"
    if blockers:
        status = "blocked"
    elif due_at < today:
        status = "overdue"
    elif window_start <= today <= window_end:
        status = "due"
    action_label = "Completar"
    if item_type in {"psa", "testosterone", "lab_panel", "pro_assessment", "toxicity_review", "therapy_review"}:
        action_label = "Registrar visita"
    elif item_type in {"imaging", "biopsy"}:
        action_label = "Registrar estudio"
    return AgendaItem(
        agenda_key=agenda_key,
        item_type=item_type,
        title=title,
        state=state,
        management_track=management_track,
        due_at=_fmt_date(due_at),
        window_start=_fmt_date(window_start),
        window_end=_fmt_date(window_end),
        status=status,
        priority=priority,
        summary=summary,
        required_inputs=required_inputs or [],
        completion_rule=completion_rule or {},
        evidence_basis=evidence_basis or [],
        comparator_basis=comparator_basis or [],
        generated_from_event=generated_from_event,
        action_label=action_label,
        blockers=blockers or [],
        reasoning=reasoning or [],
    ).to_dict()


def build_protocol_comparators(state: str, management_track: str) -> list[dict[str, Any]]:
    comparators = [
        InstitutionalComparator(
            label="guideline_primary",
            mode="guideline_primary",
            title="Carril primario de guías",
            cadence_summary="NCCN 2026 + EAU 2026 definen la vigilancia y los disparadores principales.",
            notes=["Nunca se sustituye por benchmarks institucionales o supportive evidence."],
        ).to_dict()
    ]
    if management_track == "active_surveillance":
        comparators.append(
            InstitutionalComparator(
                label="MSK",
                mode="institutional_benchmark",
                title="Benchmark MSK para vigilancia activa",
                cadence_summary="PSA seriado, MRI y biopsia de confirmación/reevaluación en vigilancia activa.",
                source_label="MSK Active Surveillance",
                source_url="https://www.mskcc.org/cancer-care/types/prostate/treatment/active-surveillance",
                notes=["Benchmark visible, pero la agenda primaria sigue siendo guías NCCN/EAU."],
            ).to_dict()
        )
        comparators.append(
            InstitutionalComparator(
                label="Keck_USC",
                mode="institutional_benchmark",
                title="Benchmark Keck/USC",
                cadence_summary="Referencia institucional pública para trayectoria terapéutica y vigilancia local.",
                source_label="Keck/USC",
                source_url="https://www.keckmedicine.org/blog/treatment-options-for-prostate-cancer/",
            ).to_dict()
        )
    if management_track == "post_rp":
        comparators.append(
            InstitutionalComparator(
                label="center_protocol",
                mode="local_center_protocol",
                title="Protocolo local configurable post prostatectomía",
                cadence_summary="4, 8, 12 semanas; 6, 9, 12, 18, 24 y 36 meses, marcado explícitamente como protocolo local.",
                notes=["No desplaza el carril primario guiado por NCCN/EAU."],
            ).to_dict()
        )
    if management_track in {"on_arpi", "on_docetaxel", "on_parp", "on_lu177"}:
        comparators.append(
            InstitutionalComparator(
                label="source_pending",
                mode="source_pending",
                title="Comparadores institucionales avanzados",
                cadence_summary="Cleveland Clinic y Global Robotics permanecen pendientes hasta contar con documento verificable.",
                notes=["No se usan como default mientras no exista fuente pública validada."],
            ).to_dict()
        )
    return comparators


def build_stage_protocol(state: str, management_track: str, patient: dict[str, Any]) -> dict[str, Any]:
    if state == "diagnostic_workup":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Agenda diagnóstica",
            cadence_summary="Revisión en 6-12 semanas con PSA/PSAD, MRI y biopsia según riesgo.",
            purpose="Confirmar o descartar histología sin retrasar una lesión clínicamente significativa.",
            evidence_basis=["NCCN 2026", "EAU 2026 diagnóstico", "EAU Follow-up 2026"],
            comparator_basis=[],
        ).to_dict()
    if state == "post_negative_biopsy_followup":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Seguimiento tras biopsia benigna",
            cadence_summary="PSA cada 12-24 meses; MRI/rebiopsia solo si reaparece señal de riesgo.",
            purpose="Evitar rebiopsias innecesarias sin perder cáncer clínicamente significativo.",
            evidence_basis=["NCCN 2026", "EAU 2026 seguimiento", "5.pdf"],
            comparator_basis=[],
        ).to_dict()
    if management_track == "active_surveillance":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Agenda de vigilancia activa",
            cadence_summary="PSA no más frecuente que cada 6 meses; MRI/biopsia según readiness y riesgo.",
            purpose="Sostener vigilancia activa segura con disparadores claros de salida.",
            evidence_basis=["NCCN 2026", "EAU 2026 localized", "EAU Follow-up 2026"],
            comparator_basis=["MSK Active Surveillance", "Keck/USC"],
        ).to_dict()
    if management_track == "pre_surgery":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Preparación prequirúrgica",
            cadence_summary="Counseling preoperatorio, algoritmos prequirúrgicos y PROs antes de definir cirugía.",
            purpose="Alinear riesgo patológico, función basal y decisión compartida antes de prostatectomía.",
            evidence_basis=["NCCN 2026", "EAU 2026 localized"],
            comparator_basis=["MSK pre-op", "Partin", "Briganti"],
        ).to_dict()
    if management_track == "post_rp":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Seguimiento post prostatectomía radical",
            cadence_summary="Primer PSA alrededor de 6-8 semanas; luego cada 6 meses hasta 3 años y anual después.",
            purpose="Detectar persistencia/recurrencia temprana y medir recuperación funcional.",
            evidence_basis=["NCCN 2026", "EAU Follow-up 2026"],
            comparator_basis=["center_protocol"],
        ).to_dict()
    if management_track == "post_rt":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Seguimiento post radioterapia",
            cadence_summary="PSA y toxicidad seriados; imagen solo cuando cambia conducta.",
            purpose="Vigilar control bioquímico y toxicidad GU/GI tardía.",
            evidence_basis=["NCCN 2026", "EAU Follow-up 2026", "1.pdf"],
            comparator_basis=[],
        ).to_dict()
    if management_track == "salvage":
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Ruta de rescate",
            cadence_summary="PSA ultrasensible, PSADT e imagen dirigida para definir ventana curativa o intensificación.",
            purpose="No perder oportunidad de rescate curativo y evitar intensificación prematura.",
            evidence_basis=["NCCN 2026", "EAU 2026 recurrencia", "FDA EMBARK"],
            comparator_basis=[],
        ).to_dict()
    if state in ADVANCED_STATES:
        return StageProtocolDefinition(
            state=state,
            management_track=management_track,
            title="Agenda sistémica avanzada",
            cadence_summary="Labs/síntomas cada 1-3 meses; imagen cada 3-6 meses o antes si hay deterioro clínico.",
            purpose="Secuenciar terapia, vigilar toxicidad y activar soporte concurrente.",
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "36.pdf", "37.pdf", "40.pdf", "41.pdf"],
            comparator_basis=[],
        ).to_dict()
    return StageProtocolDefinition(
        state=state,
        management_track=management_track,
        title="Agenda clínica",
        cadence_summary="Seguimiento estructurado según etapa y eventos longitudinales.",
        purpose="Mantener continuidad, seguridad y datos decisores vigentes.",
        evidence_basis=["NCCN 2026", "EAU 2026"],
        comparator_basis=[],
    ).to_dict()


def _diagnostic_agenda(patient: dict[str, Any], state: str, track: str) -> list[dict[str, Any]]:
    identity = patient.get("identity") or {}
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    latest_mri = _latest_by(patient.get("mri_facts", []), "fact_date")
    latest_trigger = _latest_by(patient.get("biopsy_triggers", []), "trigger_date")
    reference = _parse_date(_first_nonempty(latest_followup.get("visit_date"), latest_trigger.get("trigger_date"), identity.get("diagnosis_date"))) or date.today()
    items = [
        _agenda_item(
            f"{state}:{track}:psa_review",
            "psa",
            "PSA / PSAD y revisión clínica",
            state,
            track,
            reference,
            42,
            summary="Repetir PSA/PSAD y revisar si la sospecha sigue activa.",
            required_inputs=["psa", "psad"],
            completion_rule={"any_of": ["psa", "psad"]},
            evidence_basis=["EAU 2026 diagnóstico", "NCCN 2026"],
            generated_from_event="recommendation_generated",
        ),
    ]
    if not latest_mri or not _is_present(latest_mri.get("mpmri_quality")):
        items.append(
            _agenda_item(
                f"{state}:{track}:mri_quality",
                "imaging",
                "MRI multiparamétrica de calidad diagnóstica",
                state,
                track,
                reference,
                14,
                priority="high",
                summary="La ruta diagnóstica sigue incompleta sin MRI utilizable o equivalente.",
                required_inputs=["mpmri_quality", "pirads_score"],
                completion_rule={"all_of": ["mpmri_quality"]},
                evidence_basis=["EAU 2026 diagnóstico", "NCCN 2026"],
                generated_from_event="recommendation_generated",
            )
        )
    if latest_trigger and not patient.get("biopsies"):
        trigger_date = _parse_date(latest_trigger.get("trigger_date")) or reference
        items.append(
            _agenda_item(
                f"{state}:{track}:biopsy",
                "biopsy",
                "Biopsia dirigida + sistemática",
                state,
                track,
                trigger_date,
                30,
                priority="high",
                summary="El trigger de biopsia ya está activo y aún no existe histología confirmada.",
                required_inputs=["planned_biopsy_type", "planned_biopsy_route"],
                completion_rule={"requires_event_target": "biopsy_details"},
                evidence_basis=["EAU 2026 diagnóstico", "NCCN 2026"],
                generated_from_event="biopsy_trigger",
            )
        )
    return items


def _localized_agenda(patient: dict[str, Any], state: str, track: str) -> list[dict[str, Any]]:
    identity = patient.get("identity") or {}
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    latest_pro = _latest_by(patient.get("pros", []), "assessment_date")
    latest_biopsy = _latest_by(patient.get("biopsies", []), "biopsy_date")
    latest_mri = _latest_by(patient.get("imaging", []), "study_date")
    base_date = _parse_date(_first_nonempty(latest_followup.get("visit_date"), latest_biopsy.get("biopsy_date"), identity.get("diagnosis_date"))) or date.today()
    items = []
    if track == "active_surveillance":
        items.extend(
            [
                _agenda_item(
                    f"{state}:{track}:psa",
                    "psa",
                    "PSA seriado",
                    state,
                    track,
                    base_date,
                    180,
                    summary="El carril guideline-primary de vigilancia activa usa PSA no más frecuente que cada 6 meses.",
                    required_inputs=["psa"],
                    completion_rule={"any_of": ["psa"]},
                    evidence_basis=["EAU Follow-up 2026", "NCCN 2026", "MSK Active Surveillance"],
                    comparator_basis=["MSK Active Surveillance", "Keck/USC"],
                    generated_from_event="followup_visit_recorded",
                ),
                _agenda_item(
                    f"{state}:{track}:pros",
                    "pro_assessment",
                    "PROs urinarios, sexuales e intestinales",
                    state,
                    track,
                    _parse_date(latest_pro.get("assessment_date")) or base_date,
                    180,
                    summary="Comparar calidad de vida y síntomas contra el basal ayuda a sostener la ruta elegida.",
                    required_inputs=["ipss_total", "iief5_score", "eq5d_vas"],
                    completion_rule={"any_of": ["ipss_total", "iief5_score", "eq5d_vas"]},
                    evidence_basis=["EAU Follow-up 2026", "CEASAR style PRO logic"],
                    generated_from_event="followup_visit_recorded",
                ),
                _agenda_item(
                    f"{state}:{track}:mri_biopsy",
                    "imaging",
                    "MRI / biopsia confirmatoria según readiness",
                    state,
                    track,
                    _parse_date(_first_nonempty(latest_mri.get("study_date"), latest_biopsy.get("biopsy_date"), identity.get("diagnosis_date"))) or date.today(),
                    365,
                    priority="high",
                    summary="Confirmar estabilidad anatómica e histológica antes de sostener vigilancia activa expandida.",
                    required_inputs=["prior_mpmri_pirads_score", "precise_score"],
                    completion_rule={"any_of": ["pirads_score", "precise_score", "biopsy_details"]},
                    evidence_basis=["EAU 2026 localized", "NCCN 2026", "MSK Active Surveillance"],
                    comparator_basis=["MSK Active Surveillance", "Keck/USC"],
                    generated_from_event="management_selected",
                ),
            ]
        )
    elif track == "pre_surgery":
        items.extend(
            [
                _agenda_item(
                    f"{state}:{track}:surgery_board",
                    "therapy_review",
                    "Decision board prequirúrgico",
                    state,
                    track,
                    base_date,
                    14,
                    priority="high",
                    summary="Revisar CAPRA, Briganti, Partin y MSKCC junto con PROs y patología.",
                    required_inputs=["capra", "briganti", "partin", "mskcc_preop"],
                    completion_rule={"note": "Revisión clínica del panel prequirúrgico"},
                    evidence_basis=["NCCN 2026", "EAU 2026", "MSK pre-op"],
                    comparator_basis=["MSK pre-op", "Partin", "Briganti"],
                    generated_from_event="management_selected",
                ),
                _agenda_item(
                    f"{state}:{track}:pros_baseline",
                    "pro_assessment",
                    "Completar PROs basales",
                    state,
                    track,
                    _parse_date(latest_pro.get("assessment_date")) or base_date,
                    14,
                    priority="high",
                    summary="La conversación compartida antes de cirugía requiere línea funcional basal documentada.",
                    required_inputs=["ipss_total", "iief5_score", "eq5d_vas", "fact_p_total"],
                    completion_rule={"any_of": ["ipss_total", "iief5_score", "eq5d_vas"]},
                    evidence_basis=["EAU 2026 localized", "NCCN 2026"],
                    generated_from_event="management_selected",
                ),
            ]
        )
    else:
        items.append(
            _agenda_item(
                f"{state}:{track}:shared_decision",
                "therapy_review",
                "Revisar decisión local y datos faltantes",
                state,
                track,
                base_date,
                21,
                summary="Cerrar datos anatómicos, patológicos y funcionales antes de fijar la trayectoria local.",
                required_inputs=["prior_mpmri_pirads_score", "percent_pattern_4", "ipss_total"],
                completion_rule={"note": "Documentar datos decisores faltantes"},
                evidence_basis=["EAU 2026 localized", "NCCN 2026"],
                generated_from_event="recommendation_generated",
            )
        )
    return items


def _postlocal_agenda(patient: dict[str, Any], state: str, track: str) -> list[dict[str, Any]]:
    identity = patient.get("identity") or {}
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    surgery = patient.get("surgery") or {}
    bcr = patient.get("bcr") or {}
    base_date = _parse_date(_first_nonempty(latest_followup.get("visit_date"), bcr.get("bcr_date"), surgery.get("surgery_date"), identity.get("diagnosis_date"))) or date.today()
    items = []
    if track == "post_rp":
        surgery_date = _parse_date(surgery.get("surgery_date")) or base_date
        if not latest_followup:
            items.append(
                _agenda_item(
                    f"{state}:{track}:psa_first",
                    "psa",
                    "Primer PSA ultrasensible post prostatectomía",
                    state,
                    track,
                    surgery_date,
                    56,
                    priority="high",
                    summary="El primer PSA alrededor de 6-8 semanas orienta persistencia posoperatoria.",
                    required_inputs=["psa"],
                    completion_rule={"any_of": ["psa"]},
                    evidence_basis=["EAU Follow-up 2026", "NCCN 2026"],
                    comparator_basis=["center_protocol"],
                    generated_from_event="procedure_performed",
                )
            )
        else:
            items.append(
                _agenda_item(
                    f"{state}:{track}:psa_serial",
                    "psa",
                    "PSA ultrasensible seriado",
                    state,
                    track,
                    _parse_date(latest_followup.get("visit_date")) or base_date,
                    180,
                    summary="Luego del primer control, el carril guideline-primary sigue PSA cada 6 meses hasta 3 años.",
                    required_inputs=["psa"],
                    completion_rule={"any_of": ["psa"]},
                    evidence_basis=["EAU Follow-up 2026", "NCCN 2026"],
                    comparator_basis=["center_protocol"],
                    generated_from_event="followup_visit_recorded",
                )
            )
        items.append(
            _agenda_item(
                f"{state}:{track}:functional",
                "pro_assessment",
                "Recuperación funcional urinaria y sexual",
                state,
                track,
                _parse_date(latest_followup.get("visit_date")) or surgery_date,
                90,
                summary="Pads/día, continencia, potencia y uso de PDE5i cambian soporte y rehabilitación.",
                required_inputs=["pad_usage", "iief5_score"],
                completion_rule={"any_of": ["pad_usage", "iief5_score"]},
                evidence_basis=["EAU Follow-up 2026", "NCCN 2026"],
                generated_from_event="procedure_performed",
            )
        )
    else:
        items.extend(
            [
                _agenda_item(
                    f"{state}:{track}:psa_rescue",
                    "psa",
                    "PSA ultrasensible / PSADT",
                    state,
                    track,
                    base_date,
                    90,
                    priority="high",
                    summary="La cinética del PSA determina si todavía existe ventana curativa o si ya hay que intensificar.",
                    required_inputs=["psa"],
                    completion_rule={"any_of": ["psa"]},
                    evidence_basis=["EAU 2026 recurrencia", "NCCN 2026", "FDA EMBARK"],
                    generated_from_event="recommendation_generated",
                ),
                _agenda_item(
                    f"{state}:{track}:imaging_gate",
                    "imaging",
                    "Imagen dirigida por rescate",
                    state,
                    track,
                    base_date,
                    120,
                    summary="Solo indicar PSMA-PET o imagen adicional si cambia la factibilidad de rescate.",
                    required_inputs=["imaging_modality"],
                    completion_rule={"requires_event_target": "imaging_studies"},
                    evidence_basis=["EAU 2026 recurrencia", "NCCN 2026"],
                    generated_from_event="recommendation_generated",
                ),
            ]
        )
    return items


def _advanced_agenda(patient: dict[str, Any], state: str, track: str) -> list[dict[str, Any]]:
    latest_followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    latest_imaging = _latest_by(patient.get("imaging", []), "study_date")
    base_date = _parse_date(_first_nonempty(latest_followup.get("visit_date"), latest_imaging.get("study_date"), patient.get("identity", {}).get("diagnosis_date"))) or date.today()
    interval_days = 60
    lab_interval_days = 60
    imaging_interval_days = 120
    if track == "on_docetaxel":
        interval_days = 21
        lab_interval_days = 21
        imaging_interval_days = 84
    elif track == "on_parp":
        interval_days = 28
        lab_interval_days = 28
        imaging_interval_days = 84
    elif track == "on_lu177":
        interval_days = 42
        lab_interval_days = 42
        imaging_interval_days = 84
    elif track == "on_arpi":
        interval_days = 42
        lab_interval_days = 42
        imaging_interval_days = 120
    items = [
        _agenda_item(
            f"{state}:{track}:therapy_review",
            "therapy_review",
            "Revisión terapéutica activa",
            state,
            track,
            base_date,
            interval_days,
            priority="high",
            summary="Revisar respuesta, toxicidad, síntomas y continuidad del backbone terapéutico.",
            required_inputs=["disease_status", "current_treatment", "ecog"],
            completion_rule={"note": "Revisión clínica y terapéutica"},
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
            generated_from_event="followup_visit_recorded",
        ),
        _agenda_item(
            f"{state}:{track}:labs",
            "lab_panel",
            "Laboratorio de seguridad y actividad",
            state,
            track,
            base_date,
            lab_interval_days,
            priority="high",
            summary="PSA, testosterona y laboratorio ampliado según terapia activa.",
            required_inputs=["psa", "testosterone", "alp", "ldh", "hemoglobin"],
            completion_rule={"any_of": ["psa", "testosterone", "alp", "ldh", "hemoglobin"]},
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "37.pdf", "40.pdf", "41.pdf"],
            generated_from_event="followup_visit_recorded",
        ),
        _agenda_item(
            f"{state}:{track}:imaging",
            "imaging",
            "Imagen oncológica seriada",
            state,
            track,
            _parse_date(latest_imaging.get("study_date")) or base_date,
            imaging_interval_days,
            summary="Reestadificar cada 3-6 meses o antes si hay deterioro clínico o nuevo dolor.",
            required_inputs=["imaging_modality"],
            completion_rule={"requires_event_target": "imaging_studies"},
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
            generated_from_event="followup_visit_recorded",
        ),
    ]
    if track == "on_arpi":
        items.append(
            _agenda_item(
                f"{state}:{track}:arpi_safety",
                "toxicity_review",
                "Bundle de seguridad ARPI",
                state,
                track,
                base_date,
                28,
                priority="high",
                summary="Convulsiones, dermatitis, cognición, fatiga, CV/DDI/hepático, nutrición y actividad física.",
                required_inputs=["mini_cog_score", "fatigue_score", "cv_risk_documented", "drug_interaction_reviewed"],
                completion_rule={"any_of": ["mini_cog_score", "fatigue_score", "cv_risk_documented", "drug_interaction_reviewed"]},
                evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "37.pdf", "40.pdf", "41.pdf"],
                generated_from_event="followup_visit_recorded",
            )
        )
    items.append(
        _agenda_item(
            f"{state}:{track}:bone_support",
            "supportive_care",
            "Salud ósea y soporte",
            state,
            track,
            base_date,
            90,
            summary="Vigilar DXA, calcio/vitamina D, protección ósea, ejercicio y soporte psicosocial.",
            required_inputs=["dxa_baseline_done", "calcium_vitd_started", "bone_protection_started"],
            completion_rule={"note": "Completar bundle óseo y rehabilitación"},
            evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "39.pdf"],
            generated_from_event="followup_visit_recorded",
        )
    )
    if track == "palliative_overlay":
        items.append(
            _agenda_item(
                f"{state}:{track}:goals_of_care",
                "goals_of_care",
                "Objetivos de cuidado y soporte paliativo",
                state,
                track,
                base_date,
                14,
                priority="high",
                summary="Dolor, fractura, compresión medular, carga sintomática y apoyo psicosocial deben revisarse de forma concurrente.",
                required_inputs=["pain", "opioid_use", "clinician_notes"],
                completion_rule={"note": "Registrar objetivos de cuidado y control sintomático"},
                evidence_basis=["NCCN 2026 supportive care", "EAU 2026 avanzada"],
                generated_from_event="followup_visit_recorded",
            )
        )
    return items


def build_agenda_items(patient: dict[str, Any], state: str, management_track: str) -> list[dict[str, Any]]:
    if state in DIAGNOSTIC_STATES:
        items = _diagnostic_agenda(patient, state, management_track)
    elif state in LOCALIZED_STATES:
        items = _localized_agenda(patient, state, management_track)
    elif state in POSTLOCAL_STATES:
        items = _postlocal_agenda(patient, state, management_track)
    else:
        items = _advanced_agenda(patient, state, management_track)
    items.extend(_document_agenda_items(patient, state, management_track))
    return items


def _document_agenda_items(patient: dict[str, Any], state: str, management_track: str) -> list[dict[str, Any]]:
    docs = patient.get("source_documents") or []
    verified_types = {
        str(item.get("document_type") or "")
        for item in docs
        if str(item.get("verification_status") or "") == "verified"
    }
    items: list[dict[str, Any]] = []
    base_date = date.today()
    if patient.get("biopsies") and "pathology_report" not in verified_types:
        items.append(
            _agenda_item(
                f"{state}:{management_track}:pathology_source",
                "pathology_review",
                "Falta reporte histopatológico completo",
                state,
                management_track,
                base_date,
                3,
                priority="high",
                summary="La histología estructurada existe, pero falta el reporte fuente verificable para trazabilidad y reestadificación segura.",
                required_inputs=["source_document:pathology_report"],
                completion_rule={"requires_document_type": "pathology_report"},
                evidence_basis=["NCCN 2026", "EAU 2026"],
                generated_from_event="document_missing",
            )
        )
    if state in ADVANCED_STATES and "genomic_report" not in verified_types:
        items.append(
            _agenda_item(
                f"{state}:{management_track}:molecular_source",
                "pathology_review",
                "Falta resultado molecular verificable para PARP / biomarcadores",
                state,
                management_track,
                base_date,
                7,
                priority="high",
                summary="Las rutas PARP, precisión terapéutica y algunos checkpoints avanzados requieren documento molecular verificable.",
                required_inputs=["source_document:genomic_report"],
                completion_rule={"requires_document_type": "genomic_report"},
                evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
                generated_from_event="document_missing",
            )
        )
    advanced_psma_context = state in ADVANCED_STATES or management_track == "salvage"
    psma_imaging_exists = any("psma" in str(item.get("study_type", "")).lower() for item in (patient.get("imaging") or []))
    if advanced_psma_context and psma_imaging_exists and "imaging_report" not in verified_types:
        items.append(
            _agenda_item(
                f"{state}:{management_track}:psma_source",
                "imaging",
                "Falta informe PSMA-PET verificable",
                state,
                management_track,
                base_date,
                7,
                priority="high",
                summary="La elegibilidad a rutas PSMA dirigidas y algunas decisiones de rescate requieren informe fuente verificable.",
                required_inputs=["source_document:imaging_report"],
                completion_rule={"requires_document_type": "imaging_report"},
                evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
                generated_from_event="document_missing",
            )
        )
    return items


def build_therapy_checkpoints(patient: dict[str, Any], state: str, management_track: str) -> list[dict[str, Any]]:
    baseline = patient.get("baseline") or {}
    genomics = patient.get("genomics") or {}
    followup = _latest_by(patient.get("follow_ups", []), "visit_date")
    treatment_text = _treatment_text(patient).lower()
    checkpoints: list[dict[str, Any]] = []
    if state == "localized_initial":
        genomics_ready = any(_is_present(genomics.get(key)) for key in ("decipher_risk", "prolaris_score", "gps_score"))
        checkpoints.append(
            TherapyCheckpoint(
                key="shared_decision_local",
                title="Decisión local y shared decision making",
                status="ready" if _is_present(followup.get("psa_current")) or patient.get("baseline", {}).get("baseline_psa") else "needs_data",
                rationale="PI-RADS, patología, PROs y algoritmos prequirúrgicos deben alinearse antes de fijar cirugía, RT o vigilancia.",
                action="Completar PROs y revisar panel de algoritmos contextuales.",
                evidence_basis=["NCCN 2026", "EAU 2026 localized"],
            ).to_dict()
        )
        checkpoints.append(
            TherapyCheckpoint(
                key="genomic_localized",
                title="Firma tisular documentada",
                status="available" if genomics_ready else "optional",
                rationale="Decipher / Oncotype / Prolaris refinan casos limítrofes, pero no sustituyen la guía.",
                action="Persistir resultado externo si ya existe.",
                evidence_basis=["NCCN 2026", "EAU 2026 localized"],
            ).to_dict()
        )
        return checkpoints
    if state in {"post_prostatectomy", "recurrence_bcr"}:
        psa_present = _is_present(followup.get("psa_current"))
        checkpoints.append(
            TherapyCheckpoint(
                key="salvage_gate",
                title="Gate de rescate",
                status="ready" if psa_present else "needs_data",
                rationale="PSA ultrasensible, PSADT, márgenes, Decipher e imagen definen la oportunidad de rescate.",
                action="Actualizar PSA e imagen si la trayectoria clínica cambió.",
                evidence_basis=["NCCN 2026", "EAU 2026 recurrencia", "FDA EMBARK"],
            ).to_dict()
        )
        return checkpoints
    if state in ADVANCED_STATES:
        hrr_ready = any(_is_present(genomics.get(key)) for key in ("hrr_overall", "brca2_status", "atm_status"))
        psma_ready = any("psma" in str(item.get("study_type", "")).lower() for item in (patient.get("imaging") or []))
        arpi_safety_ready = all(
            _is_present(followup.get(key))
            for key in ("ecog_current",)
        )
        checkpoints.extend(
            [
                TherapyCheckpoint(
                    key="biomarker_gate",
                    title="Biomarcadores accionables",
                    status="ready" if hrr_ready else "needs_data",
                    rationale="HRR/BRCA, MSI/TMB y trazabilidad molecular ordenan PARP e inmunoterapia.",
                    action="Documentar fuente y fecha molecular antes de intensificar.",
                    evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "35.pdf"],
                ).to_dict(),
                TherapyCheckpoint(
                    key="psma_gate",
                    title="Elegibilidad PSMA / Lutecio",
                    status="ready" if psma_ready else "needs_data",
                    rationale="Lutecio y rutas PSMA requieren imagen estructurada y descarte de lesiones dominantes PSMA negativas.",
                    action="Registrar PSMA-PET estructurado si la decisión terapéutica depende de ello.",
                    evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "34.pdf"],
                ).to_dict(),
                TherapyCheckpoint(
                    key="arpi_safety",
                    title="Seguridad ARPI",
                    status="ready" if management_track != "on_arpi" or arpi_safety_ready else "needs_data",
                    rationale="Convulsiones, cognición, rash, CV, interacciones y riesgo hepático cambian el ARPI más seguro.",
                    action="Completar bundle de seguridad específico cuando el paciente use o sea candidato a ARPI.",
                    evidence_basis=["NCCN 2026", "EAU 2026 avanzada", "37.pdf", "40.pdf", "41.pdf"],
                ).to_dict(),
            ]
        )
        if "docetaxel" in treatment_text and _safe_float(followup.get("hemoglobin_current")) is None:
            checkpoints.append(
                TherapyCheckpoint(
                    key="docetaxel_cbc",
                    title="Toxicidad hematológica en docetaxel",
                    status="needs_data",
                    rationale="CBC y estado funcional deben mantenerse vigentes en quimioterapia activa.",
                    action="Agregar laboratorio y ECOG en la siguiente visita.",
                    evidence_basis=["NCCN 2026", "EAU 2026 avanzada"],
                ).to_dict()
            )
    return checkpoints


def build_agenda_board(patient: dict[str, Any], state: str, management_track: str, raw_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    items = build_agenda_items(patient, state, management_track)
    overdue = [item for item in items if item.get("status") == "overdue"]
    due = [item for item in items if item.get("status") == "due"]
    protocol = build_stage_protocol(state, management_track, patient)
    therapy_checkpoints = build_therapy_checkpoints(patient, state, management_track)
    return {
        "management_track": management_track,
        "management_track_label": MANAGEMENT_TRACK_LABELS.get(management_track, management_track),
        "stage_protocol": protocol,
        "items": items,
        "next_due_items": due[:4],
        "overdue_items": overdue[:4],
        "active_recommendations": [item for item in items if item.get("status") in {"due", "overdue"}][:5],
        "therapy_checkpoints": therapy_checkpoints,
        "protocol_comparators": build_protocol_comparators(state, management_track),
        "visit_schema": build_visit_schema(state, management_track),
    }
