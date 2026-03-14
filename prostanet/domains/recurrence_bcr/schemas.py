from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema


RECURRENCE_BCR_SCHEMA = module_schema(
    "recurrence_bcr",
    "Recurrencia bioquímica y BCR2",
    "Distingue rescate postoperatorio, recurrencia tras radioterapia y elegibilidad exacta para BCR2 N0M0.",
    fields=[
        FieldSpec("prior_prostatectomy", "Prostatectomía previa", "select", required=True, options=["0", "1"], default="1", group="Contexto local previo", group_order=1, clinical_role="required"),
        FieldSpec("prior_radiation", "Radioterapia previa", "select", required=True, options=["0", "1"], default="0", group="Contexto local previo", group_order=1, clinical_role="required"),
        FieldSpec("local_therapy_date", "Fecha del tratamiento local principal", "date", group="Contexto local previo", group_order=1, clinical_role="decision_refiner"),
        FieldSpec("bcr2", "Segunda recurrencia bioquímica", "select", options=["0", "1"], default="0", group="Criterios BCR2", group_order=2, clinical_role="required", evidence_tags=["bcr2"]),
        FieldSpec("psa_current", "PSA actual", "number", required=True, default=0.35, group="Criterios BCR2", group_order=2, clinical_role="required", unit="ng/mL"),
        FieldSpec("psa_nadir", "Nadir de PSA", "number", default=0.02, group="Criterios BCR2", group_order=2, clinical_role="decision_refiner", unit="ng/mL"),
        FieldSpec("psadt_months", "Tiempo de duplicación del PSA", "number", default=8, group="Criterios BCR2", group_order=2, clinical_role="required", unit="meses", evidence_tags=["psa_kinetics"]),
        FieldSpec("time_to_recurrence_months", "Tiempo a recurrencia", "number", default=18, group="Criterios BCR2", group_order=2, clinical_role="decision_refiner", unit="meses"),
        FieldSpec("ultrasensitive_psa_assay", "PSA ultrasensible documentado", "select", options=["0", "1"], default="1", group="Criterios BCR2", group_order=2, clinical_role="monitoring"),
        FieldSpec("eligible_pelvic_therapy", "Elegible para terapia pélvica", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="required"),
        FieldSpec("salvage_local_feasible", "Rescate local potencialmente curativo factible", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="required", evidence_tags=["salvage"]),
        FieldSpec("local_salvage_candidate", "Candidato clínico a rescate local", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["salvage"]),
        FieldSpec("prior_secondary_rt", "Radioterapia secundaria previa", "select", options=["0", "1"], default="0", group="Salvage y reestadificación", group_order=3, clinical_role="required"),
        FieldSpec("imaging_negative", "Imagen negativa (N0M0)", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="required"),
        FieldSpec("conventional_imaging_m0", "Imagen convencional sin metástasis (M0)", "select", options=["0", "1"], default="1", group="Salvage y reestadificación", group_order=3, clinical_role="required", evidence_tags=["imaging"]),
        FieldSpec("imaging_modality", "Modalidad de imagen predominante", "select", options=["Convencional", "PSMA-PET", "Mixta"], default="Convencional", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["imaging"]),
        FieldSpec("psma_pet_done", "PSMA-PET realizado", "select", options=["0", "1"], default="0", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["imaging"]),
        FieldSpec("psma_pet_result", "Resultado dominante de PSMA-PET", "select", options=["No realizado", "Negativo", "Local/pélvico", "Oligometastásico", "Diseminado"], default="No realizado", group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", evidence_tags=["imaging"], conditional_visibility={"psma_pet_done": ["1"]}),
        FieldSpec("phoenix_delta", "Incremento Phoenix tras radioterapia", "number", default=0, group="Salvage y reestadificación", group_order=3, clinical_role="decision_refiner", unit="ng/mL"),
    ],
)
