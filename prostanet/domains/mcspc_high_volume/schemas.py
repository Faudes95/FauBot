from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


def _build_schema(module_id: str, title: str, description: str) -> dict:
    return module_schema(
        module_id,
        title,
        description,
        fields=[
            FieldSpec("metastasis_count", "Número de metástasis", "number", required=True, default=6, group="Carga metastásica", group_order=1, clinical_role="required", unit="lesiones"),
            FieldSpec("metastasis_site", "Sitio metastásico", "select", options=["Bone", "Visceral"], default="Bone", group="Carga metastásica", group_order=1, clinical_role="required"),
            FieldSpec("gleason_score", "Gleason total", "number", default=8, group="Carga metastásica", group_order=1, clinical_role="decision_refiner"),
            FieldSpec("ecog_score", "ECOG", "number", default=1, group="Fitness y seguridad", group_order=2, clinical_role="required", unit="0-4"),
            FieldSpec("peripheral_neuropathy_grade", "Neuropatía periférica", "select", options=["", "0", "1", "2", "3", "4"], default="", group="Fitness y seguridad", group_order=2, clinical_role="required", unit="CTCAE"),
            FieldSpec("frailty_status", "Fragilidad clínica", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["frailty"]),
            FieldSpec("child_pugh_score", "Child-Pugh", "select", options=["A", "B", "C"], default="A", group="Fitness y seguridad", group_order=2, clinical_role="required", evidence_tags=["hepatotoxicity"]),
            FieldSpec("comorbidity_seizure", "Riesgo convulsivo", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner"),
            FieldSpec("comorbidity_cardio", "Riesgo cardiovascular", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
            FieldSpec("cv_risk_documented", "Riesgo cardiovascular documentado", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="monitoring", evidence_tags=["cardio_oncology"]),
            FieldSpec("drug_interaction_reviewed", "Interacciones farmacológicas revisadas", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="monitoring", evidence_tags=["drug_interactions"]),
            FieldSpec("hepatic_risk_factors", "Factores de riesgo hepático", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=2, clinical_role="monitoring", evidence_tags=["hepatotoxicity"]),
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
