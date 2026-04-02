from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


def _docetaxel_visibility() -> dict:
    return {
        "ecog_score": ["", "0", "1", "2"],
        "peripheral_neuropathy_grade": ["", "0", "1", "2"],
        "frailty_status": ["", "Fit", "Vulnerable"],
        "child_pugh_score": ["", "A", "B"],
    }


def _build_schema(module_id: str, title: str, description: str) -> dict:
    return module_schema(
        module_id,
        title,
        description,
        fields=[
            FieldSpec(
                "metastatic_components_capture",
                "Distribución metastásica documentada",
                "metastatic_components",
                required=True,
                group="Carga metastásica",
                group_order=1,
                clinical_role="required",
                help_text="Documente componentes óseos, viscerales y ganglionares no regionales. El asistente derivará automáticamente la composición metastásica, el subtipo M y la carga total.",
                benchmark_note="Permite enfermedad mixta visceral + ósea + nodal sin colapsarla a un solo sitio metastásico legado.",
            ),
            FieldSpec(
                "gleason_score",
                "Perfil Gleason / ISUP",
                "gleason_profile",
                default={"gleason_primary": "4", "gleason_secondary": "4", "gleason_tertiary": "", "gleason_score": "8", "isup_grade": "4"},
                group="Carga metastásica",
                group_order=1,
                clinical_role="decision_refiner",
                help_text="Documente patrón primario, secundario y el terciario si existe. El sistema derivará automáticamente el Gleason total y el ISUP para alimentar diagnóstico y decisión terapéutica.",
            ),
            FieldSpec("ecog_score", "ECOG", "number", default=1, group="Fitness y seguridad", group_order=2, clinical_role="required", unit="0-4"),
            FieldSpec(
                "performance_status_driver",
                "Origen del deterioro funcional",
                "select",
                options=["mixed_or_unclear", "cancer_related", "comorbidity_or_frailty"],
                default="mixed_or_unclear",
                group="Fitness y seguridad",
                group_order=2,
                clinical_role="decision_refiner",
                help_text="Úselo sobre todo cuando ECOG es 2 para distinguir si el deterioro parece impulsado por cáncer/dolor óseo o por comorbilidad/fragilidad.",
                conditional_visibility={"ecog_score": ["2"]},
            ),
            FieldSpec("peripheral_neuropathy_grade", "Neuropatía periférica", "select", options=["", "0", "1", "2", "3", "4"], default="", group="Fitness y seguridad", group_order=2, clinical_role="required", unit="CTCAE"),
            FieldSpec("frailty_status", "Fragilidad clínica", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["frailty"]),
            FieldSpec("child_pugh_score", "Child-Pugh", "select", options=["A", "B", "C"], default="A", group="Fitness y seguridad", group_order=2, clinical_role="required", evidence_tags=["hepatotoxicity"]),
            FieldSpec(
                "cbc_date",
                "Fecha de biometría hemática",
                "date",
                group="Elegibilidad a docetaxel",
                group_order=3,
                clinical_role="required",
                help_text="Use una biometría hemática vigente de 14 días o menos cuando docetaxel siga siendo opción real.",
                conditional_visibility=_docetaxel_visibility(),
            ),
            FieldSpec("anc", "ANC basal", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="/mm3", evidence_tags=["cbc"], conditional_visibility=_docetaxel_visibility()),
            FieldSpec("platelets", "Plaquetas basales", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="/mm3", evidence_tags=["cbc"], conditional_visibility=_docetaxel_visibility()),
            FieldSpec(
                "liver_panel_date",
                "Fecha de pruebas hepáticas",
                "date",
                group="Elegibilidad a docetaxel",
                group_order=3,
                clinical_role="required",
                help_text="Use pruebas hepáticas vigentes de 14 días o menos cuando compitan docetaxel, ARPI o abiraterona.",
            ),
            FieldSpec("bilirubin", "Bilirrubina total", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="mg/dL", evidence_tags=["hepatotoxicity"]),
            FieldSpec("ast", "AST (TGO)", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", evidence_tags=["hepatotoxicity"]),
            FieldSpec("alt", "ALT (TGP)", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", evidence_tags=["hepatotoxicity"]),
            FieldSpec("alp", "Fosfatasa alcalina", "number", default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", unit="U/L", evidence_tags=["hepatotoxicity"]),
            FieldSpec("taxane_hypersensitivity_history", "Hipersensibilidad previa a taxanos", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            FieldSpec("polysorbate_hypersensitivity", "Hipersensibilidad a polisorbato 80", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="required", conditional_visibility=_docetaxel_visibility()),
            FieldSpec("bone_pain", "Dolor óseo relacionado con la enfermedad", "select", options=["", "0", "1"], default="", group="Elegibilidad a docetaxel", group_order=3, clinical_role="decision_refiner", help_text="Especialmente útil si ECOG es 2 para adjudicar un deterioro cáncer-relacionado tipo PEACE-1 / CHAARTED parcial.", conditional_visibility={"ecog_score": ["2"]}),
            FieldSpec("comorbidity_seizure", "Riesgo convulsivo", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner"),
            FieldSpec("comorbidity_cardio", "Riesgo cardiovascular", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
            FieldSpec("cv_risk_documented", "Riesgo cardiovascular documentado", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="monitoring", evidence_tags=["cardio_oncology"]),
            FieldSpec("drug_interaction_reviewed", "Interacciones farmacológicas revisadas", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="monitoring", evidence_tags=["drug_interactions"]),
            FieldSpec("current_medications", "Medicaciones concomitantes", "text", default="", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["drug_interactions"]),
            FieldSpec("dermatitis_history", "Antecedente dermatológico relevante", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["arsi_safety"]),
            FieldSpec("cognitive_risk", "Riesgo cognitivo clínicamente relevante", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["neurotoxicity"]),
            FieldSpec("fall_risk", "Riesgo de caídas", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["falls"]),
            FieldSpec("stroke_history", "Antecedente de EVC/AIT", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["neurovascular"]),
            FieldSpec("edema_risk", "Riesgo de edema / IC", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
            FieldSpec("steroid_intolerance", "Intolerancia a esteroides", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["steroids"]),
            FieldSpec("diabetes_uncontrolled", "Diabetes no controlada", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["metabolic_risk"]),
            FieldSpec("hepatic_risk_factors", "Factores de riesgo hepático", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="monitoring", evidence_tags=["hepatotoxicity"]),
            FieldSpec("baseline_bp", "Presión arterial basal sistólica", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", unit="mmHg", evidence_tags=["cardio_oncology"]),
            FieldSpec("baseline_weight", "Peso basal", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", unit="kg", evidence_tags=["qol"]),
            FieldSpec("fatigue_baseline", "Fatiga basal", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", unit="0-10", evidence_tags=["qol"]),
            FieldSpec("neurocognitive_baseline", "Línea basal neurocognitiva", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", unit="puntaje", evidence_tags=["neurotoxicity"]),
            FieldSpec("fall_history_recent", "Caídas recientes", "select", options=["0", "1"], default="0", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", evidence_tags=["falls"]),
            FieldSpec("potassium", "Potasio basal", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", unit="mEq/L", evidence_tags=["metabolic_risk"]),
            FieldSpec("glucose_or_hba1c", "Glucosa o HbA1c basal", "number", default="", group="Monitoreo basal ARPI", group_order=4, clinical_role="monitoring", evidence_tags=["metabolic_risk"]),
            FieldSpec("biomarker_source", "Fuente del biomarcador", "select", options=["Desconocida", "Tejido primario", "Biopsia metastásica", "ctDNA"], default="Desconocida", group="Biomarcadores", group_order=3, clinical_role="optional", evidence_tags=["biomarkers"]),
            FieldSpec("molecular_assay_source", "Fuente del ensayo molecular", "select", options=["Desconocida", "Tejido primario", "Biopsia metastásica", "ctDNA"], default="Desconocida", group="Biomarcadores", group_order=3, clinical_role="decision_refiner", evidence_tags=["biomarkers"]),
            FieldSpec("molecular_assay_date", "Fecha del ensayo molecular", "date", group="Biomarcadores", group_order=3, clinical_role="decision_refiner", evidence_tags=["biomarkers"]),
            FieldSpec("hrr_gene", "Gen HRR predominante", "select", options=["Desconocido", "BRCA2", "BRCA1", "ATM", "PALB2", "CDK12", "Otro"], default="Desconocido", group="Biomarcadores", group_order=3, clinical_role="optional", evidence_tags=["hrr"]),
            FieldSpec("brca2_status", "Estado BRCA2", "select", options=["Desconocido", "Positivo", "Negativo"], default="Desconocido", group="Biomarcadores", group_order=3, clinical_role="decision_refiner", evidence_tags=["hrr"]),
            FieldSpec("dxa_baseline_done", "DXA basal realizada", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="monitoring", evidence_tags=["bone_health"]),
            FieldSpec("calcium_vitd_started", "Calcio y vitamina D iniciados", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="monitoring", evidence_tags=["bone_health"]),
            FieldSpec("bone_protection_started", "Protección ósea iniciada", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="monitoring", evidence_tags=["bone_health"]),
            FieldSpec("rare_histology_variant", "Variante histológica agresiva poco común", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="optional", evidence_tags=["variant_histology"]),
            FieldSpec("neuroendocrine_features", "Rasgos neuroendocrinos emergentes", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=4, clinical_role="optional", evidence_tags=["variant_histology"]),
            FieldSpec("baseline_qol", "Calidad de vida basal", "number", default=70, group="Resultados reportados por el paciente", group_order=4, clinical_role="monitoring", unit="0-100", evidence_tags=["qol"]),
        ],
    )


MCSPC_HIGH_VOLUME_SCHEMA = _build_schema(
    "mcspc_high_volume",
    "mCSPC alto volumen",
    "Ruta de tripletes y dobletes para enfermedad metastásica sensible a la castración de alto volumen.",
)

MCSPC_HIGH_VOLUME_SYNC_SCHEMA = _build_schema(
    "mcspc_high_volume_sync",
    "mCSPC alto volumen sincrónico",
    "Ruta de tripletes y dobletes para enfermedad metastásica sensible a la castración de alto volumen sincrónica / de novo.",
)

MCSPC_HIGH_VOLUME_METACHRONOUS_SCHEMA = _build_schema(
    "mcspc_high_volume_metachronous",
    "mCSPC alto volumen metacrónico",
    "Ruta de intensificación sistémica para enfermedad metastásica sensible a la castración de alto volumen metacrónica.",
)
