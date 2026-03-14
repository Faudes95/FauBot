from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


MCSPC_LOW_VOLUME_SCHEMA = module_schema(
    "mcspc_low_volume_sync_oligo",
    "mCSPC bajo volumen o oligometastásico sincrónico",
    "Ruta de dobletes, tripletes seleccionados y radioterapia al primario para enfermedad metastásica sensible a la castración de bajo volumen.",
    fields=[
        FieldSpec("metastasis_count", "Número de metástasis", "number", required=True, default=2, group="Carga metastásica", group_order=1, clinical_role="required", unit="lesiones"),
        FieldSpec("metastasis_site", "Sitio metastásico", "select", options=["Bone", "Node", "Visceral"], default="Bone", group="Carga metastásica", group_order=1, clinical_role="required"),
        FieldSpec("gleason_score", "Gleason total", "number", default=7, group="Carga metastásica", group_order=1, clinical_role="decision_refiner"),
        FieldSpec("rt_primary_received", "Radioterapia local previa", "select", options=["0", "1"], default="0", group="Tratamiento local", group_order=2, clinical_role="required"),
        FieldSpec("ecog_score", "ECOG", "number", default=0, group="Fitness y seguridad", group_order=3, clinical_role="required", unit="0-4"),
        FieldSpec("frailty_status", "Fragilidad clínica", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Fitness y seguridad", group_order=3, clinical_role="decision_refiner", evidence_tags=["frailty"]),
        FieldSpec("child_pugh_score", "Child-Pugh", "select", options=["A", "B", "C"], default="A", group="Fitness y seguridad", group_order=3, clinical_role="required"),
        FieldSpec("comorbidity_seizure", "Riesgo convulsivo", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=3, clinical_role="decision_refiner"),
        FieldSpec("comorbidity_cardio", "Riesgo cardiovascular", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=3, clinical_role="decision_refiner", evidence_tags=["cardio_oncology"]),
        FieldSpec("cv_risk_documented", "Riesgo cardiovascular documentado", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=3, clinical_role="monitoring", evidence_tags=["cardio_oncology"]),
        FieldSpec("drug_interaction_reviewed", "Interacciones farmacológicas revisadas", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=3, clinical_role="monitoring", evidence_tags=["drug_interactions"]),
        FieldSpec("hepatic_risk_factors", "Factores de riesgo hepático", "select", options=["0", "1"], default="0", group="Fitness y seguridad", group_order=3, clinical_role="monitoring", evidence_tags=["hepatotoxicity"]),
        FieldSpec("molecular_assay_source", "Fuente del ensayo molecular", "select", options=["Desconocida", "Tejido primario", "Biopsia metastásica", "ctDNA"], default="Desconocida", group="Biomarcadores", group_order=4, clinical_role="decision_refiner", evidence_tags=["biomarkers"]),
        FieldSpec("molecular_assay_date", "Fecha del ensayo molecular", "date", group="Biomarcadores", group_order=4, clinical_role="decision_refiner", evidence_tags=["biomarkers"]),
        FieldSpec("hrr_gene", "Gen HRR predominante", "select", options=["Desconocido", "BRCA2", "BRCA1", "ATM", "PALB2", "CDK12", "Otro"], default="Desconocido", group="Biomarcadores", group_order=4, clinical_role="optional", evidence_tags=["hrr"]),
        FieldSpec("brca2_status", "Estado BRCA2", "select", options=["Desconocido", "Positivo", "Negativo"], default="Desconocido", group="Biomarcadores", group_order=4, clinical_role="decision_refiner", evidence_tags=["hrr"]),
        FieldSpec("dxa_baseline_done", "DXA basal realizada", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=5, clinical_role="monitoring", evidence_tags=["bone_health"]),
        FieldSpec("calcium_vitd_started", "Calcio y vitamina D iniciados", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=5, clinical_role="monitoring", evidence_tags=["bone_health"]),
        FieldSpec("bone_protection_started", "Protección ósea iniciada", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=5, clinical_role="monitoring", evidence_tags=["bone_health"]),
        FieldSpec("rare_histology_variant", "Variante histológica agresiva poco común", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=5, clinical_role="optional", evidence_tags=["variant_histology"]),
        FieldSpec("neuroendocrine_features", "Rasgos neuroendocrinos emergentes", "select", options=["0", "1"], default="0", group="Salud ósea", group_order=5, clinical_role="optional", evidence_tags=["variant_histology"]),
        FieldSpec("baseline_qol", "Calidad de vida basal", "number", default=75, group="Resultados reportados por el paciente", group_order=4, clinical_role="monitoring", unit="0-100", evidence_tags=["qol"]),
    ],
)
