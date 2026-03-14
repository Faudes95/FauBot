from __future__ import annotations

from prostanet.shared.contracts import FieldSpec, module_schema

INDEX_LESION_LOCATION_OPTIONS = [
    "No especificada",
    "Zona periférica posterior",
    "Zona periférica anterior",
    "Zona de transición",
    "Estroma fibromuscular anterior",
    "Base",
    "Tercio medio",
    "Ápice",
    "Multifocal u otra",
]


DIAGNOSTIC_WORKUP_SCHEMA = module_schema(
    "diagnostic_workup",
    "Estudio diagnóstico antes de confirmar cáncer de próstata",
    "Valora la sospecha de cáncer clínicamente significativo antes de emitir una recomendación terapéutica formal.",
    fields=[
        FieldSpec("age", "Edad", "number", default=62, group="Contexto clínico", group_order=1, clinical_role="decision_refiner", unit="años"),
        FieldSpec("life_expectancy_years", "Esperanza de vida", "number", default=15, group="Contexto clínico", group_order=1, clinical_role="decision_refiner", unit="años", evidence_tags=["nccn_primary", "eau_2026"]),
        FieldSpec("ipss_score", "Puntaje internacional de síntomas prostáticos (IPSS)", "number", default=8, group="Contexto clínico", group_order=1, clinical_role="monitoring", unit="0-35", evidence_tags=["qol"]),
        FieldSpec("psa", "Antígeno prostático específico (PSA)", "number", required=True, default=5.8, group="Sospecha actual", group_order=2, clinical_role="required", unit="ng/mL", evidence_tags=["nccn_primary", "eau_2026"]),
        FieldSpec("psad", "Densidad del antígeno prostático específico (PSAD)", "number", default=0.12, group="Sospecha actual", group_order=2, clinical_role="required", unit="ng/mL/cc", derived_from=["psa", "prostate_volume_ml"], evidence_tags=["psad"]),
        FieldSpec("psa_velocity_ng_ml_year", "Velocidad de PSA", "number", default=0.8, group="Sospecha actual", group_order=2, clinical_role="decision_refiner", unit="ng/mL/año", evidence_tags=["psa_kinetics"]),
        FieldSpec("psa_history_interval_months", "Intervalo de la serie de PSA", "number", default=12, group="Sospecha actual", group_order=2, clinical_role="monitoring", unit="meses", evidence_tags=["psa_kinetics"]),
        FieldSpec("dre_suspicious", "Tacto rectal sospechoso", "select", options=["0", "1"], default="0", group="Exploración clínica", group_order=3, clinical_role="required", evidence_tags=["nccn_primary"]),
        FieldSpec("pirads_score", "Resultado de resonancia magnética multiparamétrica", "select", options=["0", "2", "3", "4", "5"], default="3", group="Imagen prostática", group_order=4, clinical_role="required", evidence_tags=["mpmri"]),
        FieldSpec("mpmri_date", "Fecha de resonancia magnética multiparamétrica", "date", group="Imagen prostática", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("mpmri_quality", "Calidad de resonancia magnética multiparamétrica", "select", options=["No disponible", "Subóptima", "Adecuada"], default="Adecuada", group="Imagen prostática", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("index_lesion_location", "Localización de la lesión índice", "select", options=INDEX_LESION_LOCATION_OPTIONS, default="No especificada", group="Imagen prostática", group_order=4, clinical_role="decision_refiner", evidence_tags=["mpmri"]),
        FieldSpec("index_lesion_size_mm", "Tamaño de la lesión índice", "number", default=8, group="Imagen prostática", group_order=4, clinical_role="decision_refiner", unit="mm", evidence_tags=["mpmri"]),
        FieldSpec("prostate_volume_ml", "Volumen prostático", "number", default=45, group="Imagen prostática", group_order=4, clinical_role="decision_refiner", unit="mL", evidence_tags=["psad", "mpmri"]),
        FieldSpec("planned_biopsy_type", "Tipo de biopsia prevista", "select", options=["Dirigida + sistemática", "Dirigida", "Sistemática", "Pendiente"], default="Dirigida + sistemática", group="Plan diagnóstico", group_order=5, clinical_role="decision_refiner", evidence_tags=["biopsy_strategy"]),
        FieldSpec("planned_biopsy_route", "Vía de biopsia prevista", "select", options=["Transperineal", "Transrectal", "No definida"], default="Transperineal", group="Plan diagnóstico", group_order=5, clinical_role="decision_refiner", evidence_tags=["biopsy_strategy"]),
        FieldSpec("risk_calculator_pathway", "Calculadora de riesgo o pathway MRI+PSAD", "select", options=["No usado", "EAU MRI + PSAD", "Calculadora externa"], default="No usado", group="Plan diagnóstico", group_order=5, clinical_role="decision_refiner", evidence_tags=["benchmark", "eau_2026"], benchmark_note="Permite acercar el producto a pathways MRI + PSAD y calculadoras de riesgo sin sustituir la guía."),
        FieldSpec("family_history_positive", "Historia familiar relevante", "select", options=["0", "1"], default="0", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["family_history"]),
        FieldSpec("family_history_detail", "Detalle de historia familiar", "text", default="", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["family_history"]),
        FieldSpec("germline_risk_mutation", "Mutación germinal de riesgo conocida", "select", options=["0", "1"], default="0", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["germline"]),
        FieldSpec("germline_status", "Sospecha o resultado germinal", "select", options=["Desconocido", "Sospechado", "Conocido"], default="Desconocido", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["germline"]),
        FieldSpec("prior_negative_biopsy", "Biopsia prostática previa benigna", "select", options=["0", "1"], default="0", group="Riesgo hereditario", group_order=6, clinical_role="decision_refiner", evidence_tags=["negative_biopsy_followup"]),
    ],
)
