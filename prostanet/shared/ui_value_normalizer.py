from __future__ import annotations

import re
from typing import Any

from prostanet.shared.official_diagnosis import diagnosis_field_label


_MISSING_SENTINELS = {"", "none", "null", "nan", "n/a"}
_LABEL_MAP = {
    "actionable": "Accionable",
    "insufficient_data": "Datos insuficientes",
    "incomplete": "Incompleto",
    "not_applicable": "No aplica",
    "unknown": "Desconocido",
    "missing": "Faltante",
    "high": "Alta",
    "medium": "Media",
    "low": "Baja",
    "limited": "Limitada",
    "state_only": "Por estado clínico",
    "matched": "Alineado",
    "partial": "Parcial",
    "aligned": "Alineado",
    "adjacent": "Cercano",
    "divergent": "Divergente",
    "no_response": "Sin respuesta objetiva",
    "precision_pathway": "Vía de medicina de precisión",
    "talapro2_like": "Perfil comparable a TALAPRO-2",
}
_TEXT_REPLACEMENTS = (
    ("latest_assessment.created_at", "la fecha del assessment más reciente"),
    ("precision_pathway", "vía de medicina de precisión"),
    ("biomarker_longitudinal", "serie longitudinal de biomarcadores"),
    ("state_only", "por estado clínico"),
    ("no_response", "sin respuesta objetiva"),
    ("TALAPRO2_like", "Perfil comparable a TALAPRO-2"),
)
_FIELD_LABEL_MAP = {
    "psma_negative_dominant_lesions": "Lesiones dominantes PSMA negativas",
    "current_adt_context": "Contexto actual de ADT",
    "drug_scheme": "Esquema sistémico actual",
    "line_of_therapy_number": "Número de línea terapéutica",
    "line_of_therapy_context": "Contexto clínico de la línea actual",
    "current_treatment": "Tratamiento actual",
    "castrate_testosterone_status": "Estado de castración",
    "progression_pattern": "Patrón de progresión",
    "disease_status": "Estado clínico de la enfermedad",
    "conventional_imaging_status": "Imagen convencional actual",
    "imaging_modality": "Modalidad de imagen",
    "visit_date": "Fecha de la visita",
    "psma_pet_done": "Disponibilidad de PSMA-PET",
    "psma_positive": "Expresión global de PSMA",
    "psma_rads_score": "PSMA-RADS",
    "bone_distribution_documented": "Distribución ósea documentada",
    "psma_radioligand": "Radioligando PSMA",
    "psma_uptake_pattern": "Patrón de captación PSMA",
    "salvage_local_feasible": "Factibilidad de rescate local",
    "pathologic_stage": "Estadio patológico",
    "psadt_months": "Tiempo de duplicación de PSA",
    "testosterone": "Testosterona sérica",
    "psa": "PSA actual",
    "psa_current": "PSA actual",
    "psa_postop": "PSA posoperatorio",
    "bcr_psa": "PSA al momento de la recurrencia bioquímica",
    "hemoglobin": "Hemoglobina",
    "alp": "Fosfatasa alcalina",
    "ldh": "LDH",
    "creatinine": "Creatinina",
    "bilirubin": "Bilirrubina",
    "ast": "AST",
    "alt": "ALT",
    "ggt": "GGT",
    "glucose": "Glucosa",
    "hrr_status": "Estado HRR",
    "brca2_status": "Estado BRCA2",
    "msi_status": "Estado MSI",
    "molecular_assay_date": "Fecha del estudio molecular",
    "biomarker_source": "Fuente del biomarcador",
    "hrr_gene": "Gen HRR alterado",
    "line_of_therapy": "Número de línea terapéutica",
    "cv_risk_documented": "Antecedentes cardiovasculares mayores",
    "drug_interaction_reviewed": "Revisión de interacciones farmacológicas",
    "seizure_history": "Antecedente convulsivo",
    "dermatitis_history": "Antecedentes cutáneos relevantes",
    "dxa_baseline_done": "Densitometría basal",
    "calcium_vitd_started": "Suplementación con calcio y vitamina D",
    "bone_protection_started": "Protección ósea activa",
    "vitamin_d_level": "Nivel de vitamina D",
    "bone_bundle": "Bundle de salud ósea",
    "charlson_comorbidity_index": "Índice de Charlson",
    "g8": "Tamizaje geriátrico G8",
    "frailty_status": "Fragilidad clínica",
    "myocardial_infarction": "Infarto previo de miocardio",
    "congestive_heart_failure": "Insuficiencia cardiaca congestiva",
    "peripheral_vascular_disease": "Enfermedad vascular periférica",
    "cerebrovascular_disease": "Enfermedad cerebrovascular",
    "dementia": "Deterioro cognitivo o demencia",
    "chronic_pulmonary_disease": "Enfermedad pulmonar crónica",
    "connective_tissue_disease": "Enfermedad del tejido conectivo",
    "peptic_ulcer_disease": "Úlcera péptica",
    "mild_liver_disease": "Hepatopatía leve",
    "diabetes_without_complications": "Diabetes sin complicaciones",
    "diabetes_with_complications": "Diabetes con complicaciones",
    "hemiplegia": "Hemiplejia",
    "renal_disease": "Enfermedad renal",
    "solid_tumor_localized": "Tumor sólido localizado previo",
    "leukemia_lymphoma": "Leucemia o linfoma",
    "moderate_severe_liver_disease": "Hepatopatía moderada o severa",
    "metastatic_solid_tumor": "Tumor sólido metastásico",
    "aids_hiv": "VIH/SIDA",
    "mini_cog_score": "Mini-Cog",
    "fatigue_score": "Síntomas de fatiga",
    "peripheral_neuropathy_grade": "Neuropatía periférica",
    "weight_kg": "Peso actual",
    "bmi_current": "Índice de masa corporal",
    "weight_loss_6m_pct": "Pérdida de peso en 6 meses",
    "low_activity": "Actividad física reducida",
    "slow_gait": "Marcha lenta",
    "weak_grip": "Fuerza de prensión reducida",
    "ecog": "ECOG",
    "ecog_score": "ECOG",
    "g8_food_intake": "G8: ingesta de alimentos",
    "g8_weight_loss": "G8: pérdida de peso",
    "g8_mobility": "G8: movilidad",
    "g8_neuropsych": "G8: estado neuropsicológico",
    "g8_bmi": "G8: categoría de IMC",
    "g8_medications": "G8: medicamentos diarios",
    "g8_self_health": "G8: percepción de salud",
}
_CAPTURE_TARGET_LABELS = {
    "followup": "Visita clínica",
    "intake": "Expediente basal",
    "verification": "Validación clínica",
    "document_upload": "Documento fuente",
}
_CAPTURE_TARGET_CTAS = {
    "followup": "Completar en visita",
    "intake": "Completar en expediente",
    "verification": "Validar dato capturado",
    "document_upload": "Subir documento fuente",
}
_SOURCE_LABEL_MAP = {
    "assessment": "Assessment modular",
    "assessment modular": "Assessment modular",
    "clinical_baseline": "Baseline clínico",
    "baseline": "Baseline clínico",
    "follow_up": "Visita longitudinal",
    "follow_up_visits": "Visita longitudinal",
    "stage_visit": "Bundle de visita",
    "stage_visit_records": "Bundle de visita",
    "visit_bundle": "Bundle de visita",
    "verified_document": "Documento verificado",
    "source_document": "Documento fuente",
    "source_documents": "Documento fuente",
    "biomarker_longitudinal": "Serie longitudinal de biomarcadores",
    "structured_result": "Resultado estructurado",
    "transition_proposal": "Transición longitudinal",
    "legacy_summary_backfill": "Resumen histórico",
    "system": "Sistema longitudinal",
}
_FACT_GROUP_LABEL_MAP = {
    "pathology": "Patología",
    "lab_panel": "Panel de laboratorio",
    "imaging": "Imagen",
    "genomic": "Perfil molecular",
    "surgery": "Resumen quirúrgico",
    "radiotherapy": "Resumen de radioterapia",
    "followup": "Seguimiento clínico",
}
_DECISION_DOMAIN_LABELS = {
    "systemic_sequencing": "la secuenciación sistémica",
    "precision_pathway": "la vía de medicina de precisión",
    "psma_pathway": "la elegibilidad PSMA/Lu-177",
    "arpi_safety": "la seguridad del tratamiento actual",
    "bone_safety": "el soporte óseo",
    "treatment_fitness": "la aptitud terapéutica",
    "disease_control": "el control actual de la enfermedad",
    "official_diagnosis": "el diagnóstico clínico formal",
    "salvage_decision": "la decisión de rescate",
    "restaging": "la reestadificación",
    "castration_status": "la verificación de castración",
    "crpc_restage": "la reclasificación a CRPC",
    "nmcrpc_intensification": "la intensificación en nmCRPC",
    "mcrpc_sequencing": "la siguiente secuencia en mCRPC",
    "parp_eligibility": "la elegibilidad a PARP",
    "advanced_sequencing": "la secuenciación avanzada",
    "diagnostic_confirmation": "la confirmación diagnóstica",
    "biopsy_timing": "el momento de la biopsia",
    "local_therapy_selection": "la selección de tratamiento local",
    "active_surveillance": "la vigilancia activa",
}


def _looks_like_machine_field(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in _FIELD_LABEL_MAP:
        return True
    if lowered.startswith("source_document:"):
        return True
    return ("_" in stripped and " " not in stripped) or lowered in {"followup", "intake", "verification", "document_upload"}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_SENTINELS
    return False


def normalize_ui_label(value: Any, *, default: str = "No disponible") -> Any:
    if _is_missing(value):
        return default
    if not isinstance(value, str):
        return value

    text = value.strip()
    lowered = text.lower()
    if lowered in _LABEL_MAP:
        return _LABEL_MAP[lowered]
    if lowered.startswith("none "):
        return default
    return text


def normalize_ui_value(value: Any, *, default: str = "No disponible") -> Any:
    if _is_missing(value):
        return default
    if isinstance(value, str):
        return normalize_ui_label(value, default=default)
    return value


def normalize_ui_text(value: Any, *, default: str = "No disponible") -> str:
    if _is_missing(value):
        return default
    text = " ".join(str(value).split())
    for raw, replacement in _TEXT_REPLACEMENTS:
        text = text.replace(raw, replacement)
    for raw, replacement in _LABEL_MAP.items():
        if raw in {"missing", "unknown", "incomplete", "actionable", "insufficient_data", "not_applicable"}:
            continue
        text = re.sub(rf"\b{re.escape(raw)}\b", replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip()
    lowered = text.lower()
    if lowered in _LABEL_MAP:
        return _LABEL_MAP[lowered]
    if lowered.startswith("none "):
        return default
    return text or default


def normalize_field_label(value: Any, *, default: str = "Dato no disponible") -> str:
    if _is_missing(value):
        return default
    text = str(value).strip()
    lowered = text.lower()
    underscored = lowered.replace(" ", "_")
    if lowered in _FIELD_LABEL_MAP:
        return _FIELD_LABEL_MAP[lowered]
    if underscored in _FIELD_LABEL_MAP:
        return _FIELD_LABEL_MAP[underscored]
    if lowered.startswith("source_document:"):
        suffix = lowered.split(":", 1)[1]
        if suffix == "genomic_report":
            return "Adjuntar reporte molecular verificable"
        if suffix == "pathology_report":
            return "Adjuntar reporte histopatológico verificable"
        if suffix == "radiology_report":
            return "Adjuntar reporte radiológico verificable"
        return "Adjuntar documento fuente verificable"
    if text in _CAPTURE_TARGET_LABELS:
        return _CAPTURE_TARGET_LABELS[text]
    if _looks_like_machine_field(text):
        return _FIELD_LABEL_MAP.get(lowered, diagnosis_field_label(text))
    return text


def normalize_field_list(values: list[Any] | tuple[Any, ...] | None, *, limit: int | None = None) -> list[str]:
    items = [normalize_field_label(value) for value in list(values or []) if str(value or "").strip()]
    deduped = list(dict.fromkeys(item for item in items if item))
    return deduped[:limit] if limit else deduped


def normalize_capture_target_label(value: Any, *, default: str = "Captura clínica") -> str:
    if _is_missing(value):
        return default
    text = str(value).strip()
    lowered = text.lower()
    if lowered.startswith("source_document:"):
        return "Documento fuente"
    return _CAPTURE_TARGET_LABELS.get(lowered, normalize_field_label(text, default=default))


def normalize_capture_target_cta(value: Any, *, default: str = "Completar captura clínica") -> str:
    if _is_missing(value):
        return default
    text = str(value).strip()
    lowered = text.lower()
    if lowered.startswith("source_document:"):
        return "Subir documento fuente"
    return _CAPTURE_TARGET_CTAS.get(lowered, default)


def normalize_source_label(value: Any, *, default: str = "Fuente clínica") -> str:
    if _is_missing(value):
        return default
    text = str(value).strip()
    lowered = text.lower()
    underscored = lowered.replace(" ", "_")
    if lowered.startswith("source_document:"):
        return "Documento fuente"
    return _SOURCE_LABEL_MAP.get(lowered) or _SOURCE_LABEL_MAP.get(underscored) or normalize_field_label(text, default=default)


def normalize_fact_group_label(value: Any, *, default: str = "Dato clínico") -> str:
    if _is_missing(value):
        return default
    text = str(value).strip()
    lowered = text.lower()
    underscored = lowered.replace(" ", "_")
    return _FACT_GROUP_LABEL_MAP.get(lowered) or _FACT_GROUP_LABEL_MAP.get(underscored) or normalize_field_label(text, default=default)


def normalize_decision_domain_label(value: Any, *, default: str = "la decisión clínica") -> str:
    if _is_missing(value):
        return default
    text = str(value).strip()
    lowered = text.lower()
    return _DECISION_DOMAIN_LABELS.get(lowered, normalize_field_label(text, default=default))


def normalize_input_fact_list(values: list[Any] | tuple[Any, ...] | None, *, limit: int | None = None) -> list[str]:
    rendered: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        if ": " in text:
            label, detail = text.split(": ", 1)
            if _looks_like_machine_field(label):
                text = f"{normalize_field_label(label)}: {detail}"
        elif _looks_like_machine_field(text):
            text = normalize_field_label(text)
        rendered.append(text)
    deduped = list(dict.fromkeys(rendered))
    return deduped[:limit] if limit else deduped


def normalize_numeric_with_unit(value: Any, unit: str, *, default: str = "No disponible") -> str:
    normalized = normalize_ui_value(value, default=default)
    if normalized == default:
        return default
    return f"{normalized} {unit}".strip()


def normalize_last_decisive_data(payload: dict[str, Any] | None) -> dict[str, str]:
    data = dict(payload or {})
    return {
        "label": str(normalize_ui_value(data.get("label"), default="Sin dato decisor principal")),
        "value": str(normalize_ui_value(data.get("value"), default="Completar captura estructurada.")),
        "date": str(normalize_ui_value(data.get("date"), default="")),
        "source": str(normalize_ui_value(data.get("source") or data.get("source_label"), default="")),
    }


def normalize_ui_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: normalize_ui_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [normalize_ui_payload(value) for value in payload]
    if isinstance(payload, str):
        return normalize_ui_label(payload)
    return payload
