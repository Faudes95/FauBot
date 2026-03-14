from __future__ import annotations

from copy import deepcopy
from typing import Any

from tracking_db import get_patient_full_record

from prostanet.shared.contracts import FieldSpec, RegistrationFragment


STATE_SCOPE_MAP = {
    "diagnostic_workup": "diagnostic",
    "post_negative_biopsy_followup": "diagnostic",
    "localized_initial": "localized",
    "post_prostatectomy": "postlocal",
    "recurrence_bcr": "postlocal",
    "mcspc_oligo_metachronous": "advanced",
    "mcspc_low_volume_sync_oligo": "advanced",
    "mcspc_high_volume": "advanced",
    "m0_crpc": "advanced",
    "m1_crpc": "advanced",
}

SCOPE_CONFIG = {
    "diagnostic": {
        "label": "Ruta diagnóstica / biopsia benigna previa",
        "description": "El wizard ya captura la sospecha clínica central. Aquí se agregan identidad, línea basal y longitudinal para persistir sin inventar tratamiento sistémico.",
        "bullets": [
            "Los datos clínicos del asistente se importan y persisten desde la evaluación modular.",
            "No se solicita línea terapéutica ni esquema sistémico.",
            "Se agregan identidad, laboratorios basales, síntomas y cohorte opcional.",
        ],
    },
    "localized": {
        "label": "Ruta localizada inicial",
        "description": "La evaluación modular ya resolvió riesgo, vigilancia activa y refinadores locales. Esta fase completa el longitudinal y los PROs basales.",
        "bullets": [
            "Se preservan los datos clínicos del asistente para seguimiento y benchmarking.",
            "Se suman identidad, PROs funcionales y cohorte opcional.",
            "No se habilita tratamiento sistémico por defecto.",
        ],
    },
    "postlocal": {
        "label": "Ruta poslocal / recurrencia bioquímica",
        "description": "El wizard ya capturó rescate, PSA ultrasensible e imagen. Esta fase completa identidad, historial previo y longitudinal de rescate.",
        "bullets": [
            "Los disparadores de rescate y recurrencia viajan desde la evaluación modular.",
            "Se agrega historia terapéutica previa y cohorte opcional.",
            "Solo se habilita tratamiento sistémico si el estado clínico realmente lo requiere.",
        ],
    },
    "advanced": {
        "label": "Ruta avanzada",
        "description": "El wizard ya capturó biomarcadores, seguridad y secuencia. Esta fase completa identidad, tratamiento longitudinal y cohorte opcional.",
        "bullets": [
            "Los biomarcadores y warnings del asistente se importan y persisten.",
            "Se habilita el bloque de tratamiento e historial terapéutico.",
            "La captura adicional alimenta dashboard, perfil y benchmarking operativo.",
        ],
    },
}

CANONICAL_FIELD_MAP = {
    "comorb_seizure": "comorbidity_seizure",
    "comorb_cardio": "comorbidity_cardio",
}

CANONICAL_VALUE_MAPS = {
    "metastasis_site": {
        "Hueso": "Bone",
        "Ganglio": "Node",
        "Óseo": "Bone",
        "Oseo": "Bone",
        "Sin metástasis a distancia (M0)": "M0",
    },
    "pain_symptoms": {
        "Moderado-Severo": "Sintomatico",
        "Moderado/Severo": "Sintomatico",
    },
    "msi_status": {
        "Estable": "estable",
        "Inestable": "inestable",
        "MSS": "estable",
        "MSI-H": "inestable",
    },
}


def _field(name: str, label: str, field_type: str, **kwargs) -> FieldSpec:
    return FieldSpec(name=name, label=label, field_type=field_type, **kwargs)


def _common_fragment() -> RegistrationFragment:
    return RegistrationFragment(
        id="fragment_common_identity_baseline",
        title="Identidad, laboratorios y línea basal",
        applies_to_states=list(STATE_SCOPE_MAP.keys()),
        persist_targets=["patient_identity", "clinical_baseline"],
        clinical_influence=[
            "Sostiene el longitudinal basal y evita gaps al abrir el perfil del paciente.",
            "La línea basal viaja a analítica, alertas y seguimiento.",
        ],
        fields=[
            _field("full_name", "Nombre completo", "text", required=True, group="Identidad", group_order=1, clinical_role="required"),
            _field("nss", "Número de seguridad social", "text", required=True, group="Identidad", group_order=1, clinical_role="required"),
            _field("dob", "Fecha de nacimiento", "date", required=True, group="Identidad", group_order=1, clinical_role="required"),
            _field("baseline_psa", "Antígeno prostático específico basal (PSA)", "number", group="Laboratorio basal", group_order=2, clinical_role="required", unit="ng/mL"),
            _field("testosterone_baseline", "Testosterona basal", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="ng/dL"),
            _field("hemoglobin", "Hemoglobina", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="g/dL"),
            _field("alp", "Fosfatasa alcalina", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="UI/L"),
            _field("ldh", "Lactato deshidrogenasa", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="UI/L"),
            _field("albumin", "Albúmina", "number", group="Laboratorio basal", group_order=2, clinical_role="decision_refiner", unit="g/dL"),
        ],
    )


def _diagnostic_fragment() -> RegistrationFragment:
    return RegistrationFragment(
        id="fragment_diagnostic",
        title="Síntomas y antecedentes familiares longitudinales",
        applies_to_states=["diagnostic_workup", "post_negative_biopsy_followup"],
        persist_targets=["patient_demographics", "family_history_detail"],
        clinical_influence=[
            "Completa la línea basal sintomática y la trazabilidad familiar.",
            "Ayuda a seguimiento diagnóstico y benchmarking de rebiopsia.",
        ],
        fields=[
            _field("ipss_score", "Puntaje internacional de síntomas prostáticos (IPSS)", "number", group="Síntomas basales", group_order=1, clinical_role="monitoring", unit="0-35"),
            _field("family_history_detail", "Detalle estructurado de historia familiar", "text", group="Riesgo hereditario", group_order=2, clinical_role="decision_refiner", help_text="Ej. Padre con cáncer de próstata a los 64 años; BRCA2 en hermana."),
        ],
    )


def _localized_fragment() -> RegistrationFragment:
    return RegistrationFragment(
        id="fragment_localized",
        title="PROs y función basal",
        applies_to_states=["localized_initial"],
        persist_targets=["patient_demographics", "patient_pros"],
        clinical_influence=[
            "Permite comparar vigilancia activa, cirugía y radioterapia con resultados funcionales basales.",
            "Alimenta el longitudinal de PROs desde el ingreso.",
        ],
        fields=[
            _field("ipss_score", "Puntaje internacional de síntomas prostáticos (IPSS)", "number", group="PROs basales", group_order=1, clinical_role="monitoring", unit="0-35"),
            _field("iief5_score", "Índice internacional de función eréctil de 5 preguntas (IIEF-5)", "number", group="PROs basales", group_order=1, clinical_role="monitoring", unit="5-25"),
        ],
    )


def _postlocal_fragment() -> RegistrationFragment:
    return RegistrationFragment(
        id="fragment_postlocal",
        title="Contexto de imagen y rescate longitudinal",
        applies_to_states=["post_prostatectomy", "recurrence_bcr"],
        persist_targets=["imaging_studies", "biochemical_recurrence"],
        clinical_influence=[
            "Completa la trazabilidad de rescate, gammagrama y cronología de recurrencia.",
        ],
        fields=[
            _field("has_bone_scan", "Gammagrama óseo disponible", "select", options=["0", "1"], default="0", group="Imagen complementaria", group_order=1, clinical_role="monitoring"),
        ],
    )


def _advanced_history_fragment() -> RegistrationFragment:
    return RegistrationFragment(
        id="fragment_treatment_history",
        title="Tratamiento actual e historial terapéutico",
        applies_to_states=[
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume",
            "m0_crpc",
            "m1_crpc",
        ],
        persist_targets=["treatment_history", "prior_clinical_history"],
        clinical_influence=[
            "Alimenta secuenciación terapéutica, perfil longitudinal y benchmarking de adopción.",
        ],
        fields=[
            _field("line_of_therapy", "Línea terapéutica", "select", options=["1", "2"], default="1", group="Tratamiento actual", group_order=1, clinical_role="required"),
            _field("drug_scheme", "Esquema farmacológico", "select", options=[
                "",
                "ADT_MONO",
                "ADT_ENZALUTAMIDE",
                "ADT_APALUTAMIDE",
                "ADT_ABIRATERONE",
                "ADT_DOCETAXEL_DAROLUTAMIDE",
                "ADT_DOCETAXEL_ABIRATERONE",
            ], default="", group="Tratamiento actual", group_order=1, clinical_role="decision_refiner"),
            _field("rt_primary_received", "Radioterapia primaria previa", "select", options=["0", "1"], default="0", group="Historial previo", group_order=2, clinical_role="monitoring"),
            _field("rt_primary_dose_gy", "Dosis total de radioterapia primaria", "number", group="Historial previo", group_order=2, clinical_role="monitoring", unit="Gy"),
            _field("prior_docetaxel_cycles", "Ciclos previos de docetaxel", "number", default=0, group="Historial previo", group_order=2, clinical_role="decision_refiner", unit="ciclos"),
            _field("prior_arpi_agent", "Inhibidor previo de la vía del receptor androgénico", "select", options=["", "Abiraterona", "Enzalutamida", "Apalutamida", "Darolutamida"], default="", group="Historial previo", group_order=2, clinical_role="decision_refiner"),
            _field("prior_arpi_duration", "Duración del inhibidor previo de la vía del receptor androgénico", "number", default=0, group="Historial previo", group_order=2, clinical_role="decision_refiner", unit="meses"),
        ],
    )


def _mexico_fragment() -> RegistrationFragment:
    return RegistrationFragment(
        id="fragment_mexico_cohort_optional",
        title="Perfil demográfico de México para investigación",
        applies_to_states=list(STATE_SCOPE_MAP.keys()),
        persist_targets=["patient_demographics"],
        clinical_influence=[
            "No cambia la recomendación primaria, pero fortalece cohortes y benchmarking poblacional.",
        ],
        optional_research=True,
        benchmark_only=True,
        fields=[
            _field("estado_residencia", "Estado de residencia", "select", options=[
                "",
                "Aguascalientes", "Baja California", "Baja California Sur", "Campeche", "Chiapas",
                "Chihuahua", "CDMX", "Coahuila", "Colima", "Durango", "Estado de Mexico",
                "Guanajuato", "Guerrero", "Hidalgo", "Jalisco", "Michoacan", "Morelos",
                "Nayarit", "Nuevo Leon", "Oaxaca", "Puebla", "Queretaro", "Quintana Roo",
                "San Luis Potosi", "Sinaloa", "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala",
                "Veracruz", "Yucatan", "Zacatecas",
            ], group="Cohorte México", group_order=1, clinical_role="optional"),
            _field("seguridad_social", "Institución de seguridad social", "select", options=["", "IMSS", "ISSSTE", "IMSS-Bienestar", "SEDENA", "Privado", "Sin_seguridad"], group="Cohorte México", group_order=1, clinical_role="optional"),
            _field("escolaridad", "Escolaridad", "select", options=["", "Sin_estudios", "Primaria", "Secundaria", "Preparatoria", "Licenciatura", "Posgrado"], group="Cohorte México", group_order=1, clinical_role="optional"),
            _field("ocupacion", "Ocupación", "text", group="Cohorte México", group_order=2, clinical_role="optional"),
            _field("estado_civil", "Estado civil", "select", options=["", "Soltero", "Casado", "Union_libre", "Divorciado", "Viudo"], group="Cohorte México", group_order=2, clinical_role="optional"),
            _field("tabaquismo", "Tabaquismo", "select", options=["nunca", "ex_fumador", "activo_leve", "activo_moderado", "activo_severo"], default="nunca", group="Cohorte México", group_order=3, clinical_role="optional"),
            _field("paquetes_anio", "Paquetes-año", "number", group="Cohorte México", group_order=3, clinical_role="optional"),
            _field("actividad_fisica", "Actividad física", "select", options=["sedentario", "leve", "moderado", "intenso"], default="sedentario", group="Cohorte México", group_order=3, clinical_role="optional"),
            _field("diabetes_mellitus", "Diabetes mellitus", "select", options=["0", "1"], default="0", group="Comorbilidad metabólica", group_order=4, clinical_role="optional"),
            _field("hipertension", "Hipertensión", "select", options=["0", "1"], default="0", group="Comorbilidad metabólica", group_order=4, clinical_role="optional"),
            _field("sindrome_metabolico", "Síndrome metabólico", "select", options=["0", "1"], default="0", group="Comorbilidad metabólica", group_order=4, clinical_role="optional"),
        ],
    )


def _persist_targets_for_field(field_name: str, scope: str) -> list[str]:
    mapping = {
        "baseline_psa": ["clinical_baseline"],
        "mpmri_date": ["imaging_studies"],
        "index_lesion_location": ["imaging_studies"],
        "germline_status": ["family_history_detail", "genomic_profile"],
        "percent_pattern_4": ["biopsy_details"],
        "confirmatory_biopsy_planned": ["active_surveillance"],
        "decipher_risk": ["genomic_profile"],
        "psma_pet_result": ["imaging_studies"],
        "hrr_gene": ["genomic_profile"],
        "brca2_status": ["genomic_profile"],
        "mcrpc_line_context": ["prior_clinical_history"],
        "dxa_baseline_done": ["clinical_assessments"],
        "bone_protection_started": ["clinical_assessments"],
    }
    default_targets = {
        "diagnostic": ["clinical_assessments", "imaging_studies"],
        "localized": ["clinical_assessments", "biopsy_details"],
        "postlocal": ["clinical_assessments", "biochemical_recurrence"],
        "advanced": ["clinical_assessments", "clinical_baseline", "prior_clinical_history"],
    }
    return mapping.get(field_name, default_targets[scope])


def _is_present(value: Any) -> bool:
    return value not in (None, "")


class PatientTrackingService:
    def get_full_record(self, nss: str) -> dict | None:
        return get_patient_full_record(nss)

    def scope_for_state(self, state: str) -> str:
        return STATE_SCOPE_MAP.get(state, "diagnostic")

    def canonicalization_map(self) -> dict[str, Any]:
        return {
            "aliases": deepcopy(CANONICAL_FIELD_MAP),
            "values": deepcopy(CANONICAL_VALUE_MAPS),
        }

    def build_registration_context(
        self,
        *,
        module_schema: dict[str, Any],
        module_id: str,
        state: str,
        assessment_input: dict[str, Any],
    ) -> dict[str, Any]:
        scope = self.scope_for_state(state or module_id)
        config = deepcopy(SCOPE_CONFIG[scope])
        fragments = [_common_fragment()]
        if scope == "diagnostic":
            fragments.append(_diagnostic_fragment())
        elif scope == "localized":
            fragments.append(_localized_fragment())
        elif scope == "postlocal":
            fragments.append(_postlocal_fragment())
            fragments.append(_advanced_history_fragment())
        else:
            fragments.append(_advanced_history_fragment())
        fragments.append(_mexico_fragment())

        imported_fields = []
        for field in module_schema.get("fields", []):
            value = assessment_input.get(field["name"])
            if not _is_present(value):
                continue
            imported_fields.append(
                {
                    "name": field["name"],
                    "label": field["label"],
                    "value": value,
                    "options": field.get("options", []),
                    "clinical_role": field.get("clinical_role", ""),
                    "persist_targets": _persist_targets_for_field(field["name"], scope),
                }
            )

        defaults = {
            "assessment_state": state,
            "baseline_psa": assessment_input.get("baseline_psa", assessment_input.get("psa", "")),
            "metastasis_site": assessment_input.get("metastasis_site", "M0" if scope != "advanced" else ""),
            "volume_disease": assessment_input.get("volume_disease", "Low" if scope != "advanced" else ""),
            "line_of_therapy": "2" if state in {"m0_crpc", "m1_crpc"} else "1",
        }

        return {
            "scope": scope,
            "scope_label": config["label"],
            "scope_description": config["description"],
            "scope_bullets": config["bullets"],
            "registration_fragments": [fragment.to_dict() for fragment in fragments],
            "registration_defaults": defaults,
            "canonicalization_map": self.canonicalization_map(),
            "imported_clinical_fields": imported_fields,
        }

    def merge_assessment_payload(self, assessment: dict[str, Any], registration_payload: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(assessment.get("input_snapshot", {}) or {})
        merged.update({key: value for key, value in registration_payload.items() if _is_present(value)})
        merged["assessment_id"] = assessment.get("id")
        merged["assessment_state"] = registration_payload.get("assessment_state") or assessment.get("state") or ""
        merged["assessment_module"] = assessment.get("module_id") or merged.get("assessment_state", "")
        if not _is_present(merged.get("baseline_psa")) and _is_present(merged.get("psa")):
            merged["baseline_psa"] = merged.get("psa")
        if merged.get("assessment_state") in {"m0_crpc", "m1_crpc"} and not _is_present(merged.get("line_of_therapy")):
            merged["line_of_therapy"] = "2"
        return self.canonicalize_payload(merged)

    def canonicalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        canonical = {}
        for key, value in payload.items():
            canonical_key = CANONICAL_FIELD_MAP.get(key, key)
            canonical[canonical_key] = value

        for field_name, value_map in CANONICAL_VALUE_MAPS.items():
            if field_name in canonical and canonical[field_name] in value_map:
                canonical[field_name] = value_map[canonical[field_name]]

        if canonical.get("genomic_test_done") in (None, "", "0", 0, False):
            genomic_markers = [
                canonical.get("hrr_status"),
                canonical.get("hrr_gene"),
                canonical.get("biomarker_source"),
                canonical.get("molecular_report_date"),
                canonical.get("genomic_classifier"),
                canonical.get("genomic_classifier_result"),
                canonical.get("decipher_risk"),
                canonical.get("brca2_status"),
            ]
            canonical["genomic_test_done"] = "1" if any(_is_present(item) and item not in {"No realizado", "No aplica", "Desconocido", "Desconocida"} for item in genomic_markers) else "0"

        if not _is_present(canonical.get("imaging_modality")):
            canonical["imaging_modality"] = "Ninguna"

        return canonical
