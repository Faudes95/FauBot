from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


POST_PROSTATECTOMY_SCHEMA = module_schema(
    "post_prostatectomy",
    "Post-prostatectomía / patología",
    "Evaluación postoperatoria basada en patología, CAPRA-S, riesgo genómico y monitoreo funcional.",
    fields=[
        FieldSpec("psa", "PSA preoperatorio", "number", required=True, default=12, group="PSA y cronología", group_order=1, clinical_role="required", unit="ng/mL"),
        FieldSpec("psa_postop", "PSA posoperatorio", "number", default=0.03, group="PSA y cronología", group_order=1, clinical_role="required", unit="ng/mL"),
        FieldSpec("ultrasensitive_psa_assay", "PSA ultrasensible documentado", "select", options=["0", "1"], default="1", group="PSA y cronología", group_order=1, clinical_role="monitoring", evidence_tags=["ultrasensitive_psa"]),
        FieldSpec("local_therapy_date", "Fecha de prostatectomía radical", "date", group="PSA y cronología", group_order=1, clinical_role="decision_refiner"),
        FieldSpec("time_to_recurrence_months", "Tiempo a recurrencia o persistencia", "number", default=0, group="PSA y cronología", group_order=1, clinical_role="decision_refiner", unit="meses"),
        FieldSpec("gleason_primary", "Gleason patológico primario", "select", options=["3", "4", "5"], default="4", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("gleason_secondary", "Gleason patológico secundario", "select", options=["3", "4", "5"], default="3", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("pathologic_stage", "Estadio patológico", "select", options=["pT2", "pT3a", "pT3b", "pT4"], default="pT2", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("surgical_margin", "Margen quirúrgico positivo", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("margin_location", "Localización del margen positivo", "select", options=["", "Ápex", "Base", "Posterolateral", "Múltiple", "Otro"], default="Ápex", group="Patología posoperatoria", group_order=2, clinical_role="decision_refiner", evidence_tags=["margin_location"]),
        FieldSpec("ece_status", "Extensión extracapsular", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("svi_status", "Invasión de vesículas seminales", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("lni_status", "Invasión ganglionar", "select", options=["0", "1"], default="0", group="Patología posoperatoria", group_order=2, clinical_role="required"),
        FieldSpec("decipher_score", "Decipher GC", "number", default=0.45, group="Refinadores genómicos", group_order=3, clinical_role="optional", unit="0-1", evidence_tags=["decipher"]),
        FieldSpec("decipher_risk", "Riesgo según Decipher", "select", options=["No realizado", "Bajo", "Intermedio", "Alto"], default="No realizado", group="Refinadores genómicos", group_order=3, clinical_role="optional", evidence_tags=["decipher"]),
        FieldSpec("imaging_modality", "Modalidad de imagen para vigilancia", "select", options=["Ninguna", "Convencional", "PSMA-PET"], default="Ninguna", group="Imagen y rescate", group_order=4, clinical_role="monitoring", evidence_tags=["imaging"]),
        FieldSpec("eligible_pelvic_therapy", "Elegible para rescate pélvico", "select", options=["0", "1"], default="1", group="Imagen y rescate", group_order=4, clinical_role="decision_refiner", evidence_tags=["salvage"]),
        FieldSpec("baseline_urinary_qol", "Función urinaria basal posoperatoria", "number", default=60, group="Supervivencia funcional", group_order=5, clinical_role="monitoring", unit="0-100", evidence_tags=["qol"]),
        FieldSpec("baseline_sexual_qol", "Función sexual basal posoperatoria", "number", default=45, group="Supervivencia funcional", group_order=5, clinical_role="monitoring", unit="0-100", evidence_tags=["qol"]),
    ],
)
