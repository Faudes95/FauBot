from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema
from prostanet.shared.dre import DRE_FINDING_OPTIONS


POST_NEGATIVE_BIOPSY_SCHEMA = module_schema(
    "post_negative_biopsy_followup",
    "Seguimiento después de una biopsia benigna inicial",
    "Estructura el seguimiento de baja intensidad tras biopsia benigna y detecta cuándo debe reabrirse el estudio diagnóstico.",
    fields=[
        FieldSpec("psa", "Antígeno prostático específico (PSA)", "number", required=True, default=4.6, group="Sospecha actual", group_order=1, clinical_role="required", unit="ng/mL", evidence_tags=["nccn_primary", "eau_2026"]),
        FieldSpec("psad", "Densidad del antígeno prostático específico (PSAD)", "number", default=0.09, group="Sospecha actual", group_order=1, clinical_role="required", unit="ng/mL/cc", derived_from=["psa", "prostate_volume_ml"], evidence_tags=["psad"]),
        FieldSpec("psa_velocity_ng_ml_year", "Velocidad de PSA", "number", default=0.4, group="Sospecha actual", group_order=1, clinical_role="decision_refiner", unit="ng/mL/año", evidence_tags=["psa_kinetics"]),
        FieldSpec("psa_history_interval_months", "Intervalo de la serie de PSA", "number", default=12, group="Sospecha actual", group_order=1, clinical_role="monitoring", unit="meses", evidence_tags=["psa_kinetics"]),
        FieldSpec("pirads_score", "Resultado de resonancia magnética multiparamétrica", "select", options=["0", "2", "3", "4", "5"], default="0", group="Imagen actual", group_order=2, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("post_biopsy_mri", "Resonancia magnética posterior a biopsia", "select", options=["0", "1"], default="0", group="Imagen actual", group_order=2, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("persistent_lesion_signal", "Persistencia de lesión sospechosa", "select", options=["0", "1"], default="0", group="Imagen actual", group_order=2, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("dre_finding", "Hallazgo al tacto rectal (estadio T)", "select", options=DRE_FINDING_OPTIONS, default="Normal", group="Exploración clínica", group_order=3, clinical_role="required", evidence_tags=["nccn_primary"]),
        FieldSpec("years_since_negative_biopsy", "Años desde la biopsia benigna", "number", default=1, group="Biopsia previa", group_order=4, clinical_role="required", unit="años", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("prior_biopsy_date", "Fecha de la biopsia previa", "date", group="Biopsia previa", group_order=4, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("prior_biopsy_type", "Tipo de biopsia previa", "select", options=["Sistemática", "Dirigida", "Fusión", "Desconocida"], default="Sistemática", group="Biopsia previa", group_order=4, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("prior_biopsy_mri_targeted", "Biopsia previa guiada por MRI", "select", options=["0", "1"], default="0", group="Biopsia previa", group_order=4, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("prior_biopsy_count", "Número de biopsias previas", "number", default=1, group="Biopsia previa", group_order=4, clinical_role="decision_refiner", unit="biopsias", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("repeat_biopsy_trigger", "Motivo de rebiopsia", "select", options=["PSA/PSAD", "MRI persistente", "Tacto rectal", "Historia familiar", "Sin criterio"], default="PSA/PSAD", group="Motivo de reactivación", group_order=5, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
        FieldSpec("family_history_positive", "Historia familiar relevante", "select", options=["0", "1"], default="0", group="Motivo de reactivación", group_order=5, clinical_role="decision_refiner", evidence_tags=["family_history"]),
    ],
)
