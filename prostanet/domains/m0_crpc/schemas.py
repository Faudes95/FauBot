from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


M0_CRPC_SCHEMA = module_schema(
    "m0_crpc",
    "M0 CRPC",
    "Ruta de intensificación adaptada al riesgo en enfermedad resistente a la castración sin metástasis.",
    fields=[
        FieldSpec("psadt_months", "Tiempo de duplicación del PSA", "number", required=True, default=7, group="Riesgo oncológico", group_order=1, clinical_role="required", unit="meses", evidence_tags=["psa_kinetics"]),
        FieldSpec("castration_resistant", "Resistente a la castración", "select", required=True, options=["1"], default="1", group="Riesgo oncológico", group_order=1, clinical_role="required"),
        FieldSpec("imaging_negative", "Imagen negativa", "select", options=["0", "1"], default="1", group="Riesgo oncológico", group_order=1, clinical_role="required"),
        FieldSpec("castrate_testosterone_confirmed", "Testosterona en rango de castración confirmada", "select", options=["0", "1"], default="1", group="Riesgo oncológico", group_order=1, clinical_role="required", evidence_tags=["castration_confirmation"]),
        FieldSpec("comorbidity_seizure", "Riesgo convulsivo", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["arsi_safety"]),
        FieldSpec("frailty_status", "Fragilidad clínica", "select", options=["Fit", "Vulnerable", "Frail"], default="Fit", group="Seguridad y tolerabilidad", group_order=2, clinical_role="decision_refiner", evidence_tags=["frailty"]),
        FieldSpec("cv_risk_documented", "Riesgo cardiovascular documentado", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="monitoring", evidence_tags=["cardio_oncology"]),
        FieldSpec("drug_interaction_reviewed", "Interacciones farmacológicas revisadas", "select", options=["0", "1"], default="0", group="Seguridad y tolerabilidad", group_order=2, clinical_role="monitoring", evidence_tags=["drug_interactions"]),
        FieldSpec("baseline_qol", "Calidad de vida basal", "number", default=70, group="Resultados reportados por el paciente", group_order=3, clinical_role="monitoring", unit="0-100", evidence_tags=["qol"]),
    ],
)
