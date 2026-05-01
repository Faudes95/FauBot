from __future__ import annotations

from datetime import date, datetime
from typing import Any

from prostanet.domains.patient_tracking.therapy_catalog import normalize_regimen_code, regimen_label


CONTRACT_VERSION = "systemic_refiner_contract_2026_04_v1"
SYSTEMIC_STATES = {
    "m0_crpc",
    "m1_crpc",
    "mcspc_high_volume",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
}
MISSING_SENTINELS = {"", "desconocido", "desconocida", "no documentado", "no documentada", "unknown", "no aplica"}
DERIVED_UI_FIELDS = {
    "metastasis_count",
    "metastasis_site",
    "metastatic_disease_known",
    "bone_site_entries",
    "visceral_site_entries",
    "nonregional_nodal_site_entries",
    "gleason_primary",
    "gleason_secondary",
    "isup_grade",
}


FIELD_DEFINITIONS: dict[str, dict[str, Any]] = {
    "psadt_months": {"label": "PSADT", "group": "Estado oncologico", "role": "required", "why_needed": "Confirma nmCRPC de alto riesgo y evita ARPI si PSADT no es de alto riesgo.", "priority": 96},
    "castrate_testosterone_confirmed": {"label": "Testosterona en rango de castracion", "group": "Estado oncologico", "role": "required", "why_needed": "No debe etiquetarse CRPC ni intensificarse como resistente sin castracion confirmada.", "priority": 100},
    "imaging_negative": {"label": "Imagen convencional M0", "group": "Estado oncologico", "role": "required", "why_needed": "Distingue nmCRPC de enfermedad metastasica y cambia todo el carril terapeutico.", "priority": 98},
    "conventional_imaging_modality": {"label": "Modalidad de imagen convencional", "group": "Estado oncologico", "role": "preference", "why_needed": "Documenta que la negatividad M0 es interpretable y comparable.", "priority": 87},
    "conventional_imaging_date": {"label": "Fecha de imagen convencional", "group": "Estado oncologico", "role": "preference", "why_needed": "Evita basar la decision en una reestadificacion vencida.", "priority": 88, "max_age_days": 90},
    "metastatic_components_capture": {"label": "Composicion metastasica", "group": "Carga tumoral", "role": "required", "why_needed": "Define volumen, visceralidad, bajo/alto volumen y si compiten doblete o triplete.", "priority": 99, "aliases": ["metastatic_disease_known", "bone_site_entries", "visceral_site_entries", "nonregional_nodal_site_entries"]},
    "metastasis_count": {"label": "Numero de metastasis", "group": "Carga tumoral", "role": "preference", "why_needed": "Ayuda a separar bajo volumen, alto volumen y fenotipos LATITUDE-like.", "priority": 86},
    "metastasis_site": {"label": "Sitio metastasico dominante", "group": "Carga tumoral", "role": "required", "why_needed": "Distingue hueso, ganglio y visceras para radiofarmacos, docetaxel y soporte oseo.", "priority": 91},
    "gleason_score": {"label": "Gleason / ISUP", "group": "Carga tumoral", "role": "preference", "why_needed": "Refina alto riesgo de novo y encaje LATITUDE/PEACE-1.", "priority": 78, "aliases": ["gleason_primary", "gleason_secondary", "isup_grade"]},
    "rt_primary_received": {"label": "RT previa al primario", "group": "Tratamiento local", "role": "required", "why_needed": "Define si la RT al primario sigue siendo opcion en bajo volumen sincrono.", "priority": 72},
    "prior_radiation": {"label": "Radioterapia previa", "group": "Tratamiento local", "role": "required", "why_needed": "Aclara contexto metacronico y factibilidad de MDT/salvage local.", "priority": 70},
    "mdt_context": {"label": "Contexto MDT", "group": "Tratamiento local", "role": "preference", "why_needed": "La terapia dirigida a metastasis debe justificarse por comite, ensayo o cohorte.", "priority": 64},
    "mcrpc_line_context": {"label": "Contexto de linea mCRPC", "group": "Secuencia", "role": "required", "why_needed": "Ordena first-line, post-ARPI, post-taxano y later-line.", "priority": 97, "aliases": ["line_context"]},
    "prior_therapy": {"label": "Terapias previas", "group": "Secuencia", "role": "required", "why_needed": "Evita reciclar ARPI agotados y activa CARD, PROfound, VISION o PSMAfore.", "priority": 97},
    "prior_docetaxel_cycles": {"label": "Ciclos previos de docetaxel", "group": "Secuencia", "role": "required", "why_needed": "Distingue docetaxel candidato de cabazitaxel post-docetaxel.", "priority": 94},
    "prior_arpi_duration_months": {"label": "Duracion de ARPI previo", "group": "Secuencia", "role": "preference", "why_needed": "CARD exige documentar exposicion previa suficiente antes de preferir cabazitaxel.", "priority": 86},
    "line_of_therapy_number": {"label": "Numero de linea", "group": "Secuencia", "role": "preference", "why_needed": "Permite segmentar respuesta y no mezclar lineas terapeuticas.", "priority": 62},
    "drug_scheme": {"label": "Esquema actual", "group": "Secuencia", "role": "preference", "why_needed": "Conecta recomendacion, vigilancia y respuesta longitudinal por linea.", "priority": 61},
    "ecog_score": {"label": "ECOG", "group": "Fitness", "role": "required", "why_needed": "Cambia docetaxel/triplete, intensidad sistemica y necesidad de revision humana.", "priority": 99, "aliases": ["ecog"]},
    "performance_status_driver": {"label": "Origen de ECOG 2", "group": "Fitness", "role": "preference", "why_needed": "Distingue deterioro cancer-relacionado de fragilidad/comorbilidad cuando ECOG es 2.", "priority": 83},
    "frailty_status": {"label": "Fragilidad", "group": "Fitness", "role": "safety", "why_needed": "Puede bloquear taxanos o mover la preferencia a opciones hormonales mejor toleradas.", "priority": 92},
    "peripheral_neuropathy_grade": {"label": "Neuropatia periferica", "group": "Fitness", "role": "safety", "why_needed": "Neuropatia grado 2-3 cambia docetaxel/cabazitaxel y tripletes.", "priority": 91},
    "bone_pain": {"label": "Dolor oseo cancer-relacionado", "group": "Fitness", "role": "preference", "why_needed": "Ayuda a interpretar ECOG 2 y encaje trial-like de docetaxel.", "priority": 74, "aliases": ["pain_burden", "pain_symptoms"]},
    "child_pugh_score": {"label": "Child-Pugh", "group": "Seguridad organica", "role": "safety", "why_needed": "Bloquea o desprioriza abiraterona, docetaxel, cabazitaxel y darolutamida segun gravedad.", "priority": 96},
    "hepatic_risk_factors": {"label": "Riesgo hepatico", "group": "Seguridad organica", "role": "safety", "why_needed": "Refina uso de abiraterona y taxanos cuando Child-Pugh no captura todo el riesgo.", "priority": 88},
    "liver_panel_date": {"label": "Fecha PFH", "group": "Seguridad organica", "role": "safety", "why_needed": "PFH reciente es necesaria antes de taxanos o abiraterona.", "priority": 90, "aliases": ["lft_date", "hepatic_panel_date"], "max_age_days": 14},
    "bilirubin": {"label": "Bilirrubina", "group": "Seguridad organica", "role": "safety", "why_needed": "Bilirrubina elevada bloquea docetaxel y puede bloquear cabazitaxel.", "priority": 91},
    "ast": {"label": "AST", "group": "Seguridad organica", "role": "safety", "why_needed": "Transaminasas elevadas cambian seguridad de abiraterona y taxanos.", "priority": 86},
    "alt": {"label": "ALT", "group": "Seguridad organica", "role": "safety", "why_needed": "Transaminasas elevadas cambian seguridad de abiraterona y taxanos.", "priority": 86},
    "alp": {"label": "Fosfatasa alcalina", "group": "Seguridad organica", "role": "safety", "why_needed": "Ayuda a distinguir bloqueo hepatico de carga osea y reglas label de docetaxel.", "priority": 78},
    "egfr": {"label": "eGFR / depuracion creatinina", "group": "Seguridad organica", "role": "safety", "why_needed": "Olaparib y darolutamida requieren ajuste o cautela renal.", "priority": 85, "aliases": ["creatinine_clearance", "clcr"]},
    "hemoglobin": {"label": "Hemoglobina", "group": "Biometria", "role": "safety", "why_needed": "PARP y cabazitaxel requieren reserva hematologica y vigilancia de anemia.", "priority": 84, "aliases": ["hb"]},
    "cbc_date": {"label": "Fecha biometria", "group": "Biometria", "role": "safety", "why_needed": "Taxanos y PARP no deben cerrarse con biometria vencida.", "priority": 91, "max_age_days": 14},
    "anc": {"label": "Neutrofilos absolutos", "group": "Biometria", "role": "safety", "why_needed": "ANC bajo bloquea docetaxel/cabazitaxel por riesgo de neutropenia febril.", "priority": 98, "aliases": ["absolute_neutrophil_count"]},
    "platelets": {"label": "Plaquetas", "group": "Biometria", "role": "safety", "why_needed": "Plaquetas bajas despriorizan taxanos y PARP.", "priority": 90, "aliases": ["platelet_count"]},
    "bone_marrow_reserve_concern": {"label": "Reserva medular comprometida", "group": "Biometria", "role": "safety", "why_needed": "Cambia PARP/cabazitaxel por riesgo hematologico acumulado.", "priority": 80},
    "taxane_hypersensitivity_history": {"label": "Hipersensibilidad a taxanos", "group": "Taxanos", "role": "safety", "why_needed": "Puede bloquear docetaxel o cabazitaxel.", "priority": 94},
    "polysorbate_hypersensitivity": {"label": "Hipersensibilidad a polisorbato 80", "group": "Taxanos", "role": "safety", "why_needed": "Contraindicacion label para docetaxel/cabazitaxel.", "priority": 94},
    "strong_cyp3a_inhibitor": {"label": "Inhibidor potente CYP3A", "group": "Interacciones", "role": "safety", "why_needed": "Cabazitaxel y ARPI/PARP pueden requerir ajuste o evitar coadministracion.", "priority": 73},
    "current_medications": {"label": "Medicacion concomitante", "group": "Interacciones", "role": "preference", "why_needed": "Polifarmacia sin revision DDI cambia preferencia entre ARPI y taxanos.", "priority": 82},
    "drug_interaction_reviewed": {"label": "Revision DDI", "group": "Interacciones", "role": "preference", "why_needed": "No debe cerrarse preferencia molecular cuando hay polifarmacia sin revisar.", "priority": 82},
    "comorbidity_seizure": {"label": "Riesgo convulsivo", "group": "Neurologico", "role": "safety", "why_needed": "Desprioriza enzalutamida/apalutamida y favorece darolutamida o abiraterona si segura.", "priority": 95},
    "stroke_history": {"label": "EVC/AIT previo", "group": "Neurologico", "role": "safety", "why_needed": "Cambia ARPI centrales y riesgo vascular.", "priority": 89},
    "cognitive_risk": {"label": "Riesgo cognitivo", "group": "Neurologico", "role": "safety", "why_needed": "Favorece esquemas con menor carga cognitiva y evita toxicidad central.", "priority": 83},
    "fall_risk": {"label": "Riesgo de caidas", "group": "Neurologico", "role": "safety", "why_needed": "ARPI pueden aumentar caidas/fracturas; afecta preferencia y vigilancia.", "priority": 83},
    "dermatitis_history": {"label": "Antecedente dermatologico", "group": "Toxicidad ARPI", "role": "safety", "why_needed": "Desprioriza apalutamida por riesgo de rash severo.", "priority": 79},
    "comorbidity_cardio": {"label": "Riesgo cardiovascular", "group": "Cardiometabolico", "role": "safety", "why_needed": "Desprioriza abiraterona/esteroide y exige vigilancia cardiovascular.", "priority": 90},
    "cv_risk_documented": {"label": "Riesgo CV documentado", "group": "Cardiometabolico", "role": "safety", "why_needed": "Da trazabilidad al riesgo cardiovascular que cambia preferencia.", "priority": 88},
    "baseline_bp": {"label": "TA basal", "group": "Cardiometabolico", "role": "monitoring", "why_needed": "Abiraterona y ARPI pueden elevar presion; TA cambia seguridad.", "priority": 77, "aliases": ["systolic_bp"]},
    "edema_risk": {"label": "Riesgo edema/IC", "group": "Cardiometabolico", "role": "safety", "why_needed": "Desprioriza abiraterona por retencion de liquidos.", "priority": 84},
    "potassium": {"label": "Potasio", "group": "Cardiometabolico", "role": "monitoring", "why_needed": "Abiraterona puede causar hipokalemia; debe corregirse antes de iniciar.", "priority": 86},
    "diabetes_uncontrolled": {"label": "Diabetes no controlada", "group": "Cardiometabolico", "role": "safety", "why_needed": "La carga de esteroides de abiraterona puede empeorar control metabolico.", "priority": 83},
    "steroid_intolerance": {"label": "Intolerancia a esteroides", "group": "Cardiometabolico", "role": "safety", "why_needed": "Desprioriza esquemas con prednisona/prednisolona.", "priority": 84},
    "glucose_or_hba1c": {"label": "Glucosa/HbA1c", "group": "Cardiometabolico", "role": "monitoring", "why_needed": "Hace segura la eleccion con esteroide y vigilancia metabolica.", "priority": 73, "aliases": ["glucose", "hba1c"]},
    "hrr_status": {"label": "Estado HRR", "group": "Biomarcadores", "role": "required", "why_needed": "Abre o cierra PARP y combinaciones de precision.", "priority": 96},
    "hrr_gene": {"label": "Gen HRR", "group": "Biomarcadores", "role": "required", "why_needed": "BRCA1/2, ATM u otros HRR cambian elegibilidad y fuerza de evidencia.", "priority": 95},
    "brca2_status": {"label": "BRCA2", "group": "Biomarcadores", "role": "preference", "why_needed": "Refina rutas BRCA-dirigidas en mHSPC y mCRPC.", "priority": 78},
    "biomarker_source": {"label": "Fuente del biomarcador", "group": "Biomarcadores", "role": "required", "why_needed": "Evita PARP sin trazabilidad analitica.", "priority": 93},
    "molecular_report_date": {"label": "Fecha informe molecular", "group": "Biomarcadores", "role": "required", "why_needed": "Asegura vigencia y fuente del biomarcador para precision.", "priority": 90, "max_age_days": 3650},
    "molecular_assay_source": {"label": "Fuente ensayo molecular", "group": "Biomarcadores", "role": "preference", "why_needed": "Trazabilidad molecular para precision en mHSPC/mCSPC.", "priority": 72},
    "molecular_assay_date": {"label": "Fecha ensayo molecular", "group": "Biomarcadores", "role": "preference", "why_needed": "Documenta vigencia del ensayo molecular.", "priority": 72, "max_age_days": 3650},
    "psma_positive": {"label": "PSMA positivo", "group": "Imagen funcional", "role": "required", "why_needed": "Abre o cierra radioligandos PSMA.", "priority": 91},
    "psma_pet_done": {"label": "PSMA-PET estructurado", "group": "Imagen funcional", "role": "preference", "why_needed": "Evita elegibilidad PSMA incompleta.", "priority": 84},
    "psma_negative_dominant_lesions": {"label": "Lesiones PSMA-negativas dominantes", "group": "Imagen funcional", "role": "safety", "why_needed": "Bloquea o degrada radioligando PSMA si hay enfermedad discordante.", "priority": 89},
    "psma_rads_score": {"label": "PSMA-RADS", "group": "Imagen funcional", "role": "preference", "why_needed": "PSMA-RADS intermedio requiere cautela antes de radioligando.", "priority": 72},
    "psma_uptake_pattern": {"label": "Patron captacion PSMA", "group": "Imagen funcional", "role": "preference", "why_needed": "Define confianza de elegibilidad a PSMA-RLT.", "priority": 72},
    "soft_tissue_metastases": {"label": "Metastasis partes blandas", "group": "Carga tumoral", "role": "preference", "why_needed": "Cambia CONTACT-02 y rutas post-ARPI con enfermedad visceral/partes blandas.", "priority": 65},
    "bone_modifying_agent": {"label": "Agente modificador oseo", "group": "Soporte", "role": "monitoring", "why_needed": "PEACE-3/radio-223 exige proteccion osea para disminuir fracturas.", "priority": 64},
    "baseline_weight": {"label": "Peso basal", "group": "Monitoreo", "role": "monitoring", "why_needed": "Ayuda a vigilar edema, caquexia y toxicidad longitudinal.", "priority": 35},
    "fatigue_baseline": {"label": "Fatiga basal", "group": "Monitoreo", "role": "monitoring", "why_needed": "Permite atribuir toxicidad de ARPI/taxanos durante seguimiento.", "priority": 35},
    "neurocognitive_baseline": {"label": "Neurocognicion basal", "group": "Monitoreo", "role": "monitoring", "why_needed": "Permite vigilar toxicidad cognitiva de ARPI.", "priority": 35},
    "fall_history_recent": {"label": "Caidas recientes", "group": "Monitoreo", "role": "monitoring", "why_needed": "Permite vigilar caidas/fracturas con ARPI y ADT.", "priority": 35},
    "baseline_qol": {"label": "Calidad de vida basal", "group": "Monitoreo", "role": "monitoring", "why_needed": "Sirve para balancear control oncologico vs carga de tratamiento.", "priority": 30},
}


STATE_CORE_FIELDS = {
    "m0_crpc": ["castrate_testosterone_confirmed", "imaging_negative", "psadt_months", "conventional_imaging_modality", "conventional_imaging_date"],
    "m1_crpc": ["castrate_testosterone_confirmed", "metastasis_site", "prior_therapy", "prior_docetaxel_cycles", "mcrpc_line_context"],
    "mcspc_high_volume": ["metastatic_components_capture", "metastasis_count", "gleason_score", "ecog_score", "frailty_status", "child_pugh_score"],
    "mcspc_high_volume_sync": ["metastatic_components_capture", "metastasis_count", "gleason_score", "ecog_score", "frailty_status", "child_pugh_score"],
    "mcspc_high_volume_metachronous": ["metastatic_components_capture", "metastasis_count", "gleason_score", "ecog_score", "frailty_status", "child_pugh_score"],
    "mcspc_low_volume_sync_oligo": ["metastatic_components_capture", "metastasis_count", "rt_primary_received", "ecog_score", "frailty_status", "child_pugh_score"],
    "mcspc_oligo_metachronous": ["metastatic_components_capture", "metastasis_count", "prior_radiation", "mdt_context", "ecog_score", "frailty_status", "child_pugh_score"],
}

ARPI_FIELDS = [
    "comorbidity_seizure", "stroke_history", "cognitive_risk", "fall_risk", "current_medications", "drug_interaction_reviewed",
    "comorbidity_cardio", "cv_risk_documented", "child_pugh_score", "hepatic_risk_factors", "dermatitis_history", "baseline_weight",
    "fatigue_baseline", "neurocognitive_baseline", "fall_history_recent", "baseline_qol",
]
ABIRATERONE_FIELDS = ["child_pugh_score", "hepatic_risk_factors", "liver_panel_date", "bilirubin", "ast", "alt", "potassium", "baseline_bp", "edema_risk", "comorbidity_cardio", "cv_risk_documented", "diabetes_uncontrolled", "steroid_intolerance", "glucose_or_hba1c"]
DOCETAXEL_FIELDS = ["ecog_score", "performance_status_driver", "peripheral_neuropathy_grade", "frailty_status", "cbc_date", "anc", "platelets", "liver_panel_date", "bilirubin", "ast", "alt", "alp", "taxane_hypersensitivity_history", "polysorbate_hypersensitivity", "bone_pain"]
CABAZITAXEL_FIELDS = ["prior_docetaxel_cycles", "prior_therapy", "cbc_date", "anc", "hemoglobin", "liver_panel_date", "bilirubin", "taxane_hypersensitivity_history", "polysorbate_hypersensitivity", "strong_cyp3a_inhibitor", "frailty_status", "ecog_score"]
OLAPARIB_FIELDS = ["hrr_status", "hrr_gene", "biomarker_source", "molecular_report_date", "prior_therapy", "hemoglobin", "platelets", "egfr", "bone_marrow_reserve_concern", "strong_cyp3a_inhibitor"]
MHCSPC_BIOMARKER_FIELDS = ["molecular_assay_source", "molecular_assay_date", "hrr_gene", "brca2_status"]
PSMA_FIELDS = ["psma_positive", "psma_pet_done", "psma_negative_dominant_lesions", "psma_rads_score", "psma_uptake_pattern"]

TREATMENT_WATCHLISTS = {
    "ADT_APALUTAMIDE": ["rash", "falls", "fractures", "seizure", "hypertension", "hypothyroidism"],
    "ADT_ENZALUTAMIDE": ["seizure", "PRES", "ischemic_heart_disease", "falls", "fatigue", "hypertension"],
    "ADT_DAROLUTAMIDE": ["ischemic_heart_disease", "seizure", "fatigue", "renal_or_hepatic_adjustment"],
    "ADT_ABIRATERONE": ["hypertension", "hypokalemia", "fluid_retention", "hepatotoxicity", "adrenal_insufficiency", "steroid_metabolic_toxicity"],
    "ADT_DOCETAXEL": ["neutropenia", "febrile_neutropenia", "hypersensitivity", "fluid_retention", "neuropathy"],
    "DOCETAXEL": ["neutropenia", "febrile_neutropenia", "hypersensitivity", "fluid_retention", "neuropathy"],
    "CABAZITAXEL": ["neutropenia", "febrile_neutropenia", "hypersensitivity", "diarrhea", "hepatic_toxicity", "elderly_toxicity"],
    "OLAPARIB": ["anemia", "thrombocytopenia", "venous_thromboembolism", "pneumonitis", "MDS_AML", "renal_dose_adjustment"],
    "OLAPARIB_ABIRATERONE": ["anemia", "venous_thromboembolism", "hypertension", "hypokalemia", "hepatotoxicity"],
    "NIRAPARIB_ABIRATERONE": ["anemia", "thrombocytopenia", "hypertension", "hypokalemia", "hepatotoxicity"],
    "TALAZOPARIB_ENZALUTAMIDE": ["anemia", "neutropenia", "seizure", "falls", "fatigue"],
}

EVIDENCE_BASIS = [
    {"source": "FDA apalutamide mCSPC/nmCRPC", "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-apalutamide-metastatic-castration-sensitive-prostate-cancer"},
    {"source": "FDA/DailyMed abiraterone", "url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=b36bff33-595e-4827-9a73-85c6954c314c"},
    {"source": "DailyMed enzalutamide", "url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=b129fdc9-1d8e-425c-a5a9-8a2ed36dfbdf"},
    {"source": "FDA/DailyMed darolutamide", "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-darolutamide-metastatic-castration-sensitive-prostate-cancer"},
    {"source": "DailyMed docetaxel", "url": "https://www.dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=81686d37-a13f-46e2-b439-a84eb1433634"},
    {"source": "FDA/DailyMed cabazitaxel", "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-lower-dose-cabazitaxel-prostate-cancer"},
    {"source": "FDA olaparib mCRPC", "url": "https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-olaparib-hrr-gene-mutated-metastatic-castration-resistant-prostate-cancer"},
    {"source": "AUA/SUO advanced prostate cancer", "url": "https://www.auanet.org/guidelines-and-quality/guidelines/advanced-prostate-cancer"},
]


def _dedupe(items: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for item in items:
        marker = repr(item)
        if marker in seen:
            continue
        result.append(item)
        seen.add(marker)
    return result


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on", "positive", "positivo", "documentado"}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _field_aliases(field_name: str) -> list[str]:
    return list(FIELD_DEFINITIONS.get(field_name, {}).get("aliases") or [])


def _field_value(payload: dict[str, Any], field_name: str) -> Any:
    for candidate in [field_name, *_field_aliases(field_name)]:
        value = payload.get(candidate)
        if value not in (None, "", [], {}):
            return value
    return payload.get(field_name)


def _field_present(payload: dict[str, Any], field_name: str) -> bool:
    value = _field_value(payload, field_name)
    if field_name == "metastatic_components_capture":
        if _truthy(payload.get("metastatic_disease_known")):
            return True
        if any(payload.get(alias) not in (None, "", [], {}, "[]") for alias in _field_aliases(field_name)):
            return True
    if isinstance(value, str) and value.strip().lower() in MISSING_SENTINELS:
        return False
    return value not in (None, "", [], {}, "[]")


def _field_stale(payload: dict[str, Any], field_name: str) -> bool:
    max_age = FIELD_DEFINITIONS.get(field_name, {}).get("max_age_days")
    if not max_age:
        return False
    value = _as_date(_field_value(payload, field_name))
    if not value:
        return False
    return (date.today() - value).days > int(max_age)


def _schema_fields(schema: dict[str, Any] | None) -> set[str]:
    return {str(field.get("name")) for field in (schema or {}).get("fields", []) if field.get("name")}


def _schema_label_index(schema: dict[str, Any] | None) -> dict[str, str]:
    return {str(field.get("name")): str(field.get("label") or field.get("name")) for field in (schema or {}).get("fields", []) if field.get("name")}


def _field_renderable(field_name: str, schema_names: set[str]) -> bool:
    if field_name in DERIVED_UI_FIELDS:
        return True
    return field_name in schema_names or any(alias in schema_names for alias in _field_aliases(field_name))


def _field_source(field_name: str, schema_names: set[str]) -> str:
    if field_name in schema_names:
        return "module_schema"
    for alias in _field_aliases(field_name):
        if alias in schema_names:
            return f"module_schema_alias:{alias}"
    if field_name in DERIVED_UI_FIELDS:
        return "module_schema_derived_widget"
    if field_name in {"line_of_therapy_number", "drug_scheme"}:
        return "longitudinal_tracking"
    return "backend_rule_only"


def _normalize_code_from_item(item: Any) -> str:
    if isinstance(item, str):
        return normalize_regimen_code(item)
    if not isinstance(item, dict):
        return ""
    for key in ("regimen_code", "drug_scheme", "name", "regimen_label", "display_label", "label"):
        code = normalize_regimen_code(item.get(key))
        if code:
            return code
    return ""


def _candidate_codes(state: str, payload: dict[str, Any], result: dict[str, Any] | None) -> list[str]:
    result = result or {}
    codes: list[str] = []
    for key in ("frontline_regimen_rankings", "eligible_treatments", "alternative_regimens", "frontline_regimen_rejections", "rejected_regimens", "blocked_treatments"):
        for item in result.get(key) or []:
            code = _normalize_code_from_item(item)
            if code:
                codes.append(code)
    preferred = _normalize_code_from_item(result.get("preferred_frontline_regimen") or result.get("preferred_treatment") or {})
    if preferred:
        codes.insert(0, preferred)
    if not codes:
        if state == "m0_crpc":
            codes.extend(["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE"])
        elif state.startswith("mcspc_"):
            codes.extend(["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_ABIRATERONE"])
            if "high_volume" in state:
                codes.extend(["ADT_DOCETAXEL_DAROLUTAMIDE", "ADT_DOCETAXEL_ABIRATERONE", "ADT_DOCETAXEL"])
        elif state == "m1_crpc":
            codes.extend(["ADT_ENZALUTAMIDE", "ADT_ABIRATERONE"])
    if state == "m1_crpc":
        prior = str(payload.get("prior_therapy") or "").lower()
        line_context = str(payload.get("mcrpc_line_context") or payload.get("line_context") or "").lower()
        hrr_positive = str(payload.get("hrr_status") or "").lower().startswith("pos")
        psma_positive = _truthy(payload.get("psma_positive"))
        if "docetax" not in prior and line_context in {"", "first_line_mcrpc", "post_arpi_pre_taxane"}:
            codes.append("DOCETAXEL")
        if "docetax" in prior:
            codes.append("CABAZITAXEL")
        if hrr_positive or any(gene in str(payload.get("hrr_gene") or "") for gene in ("BRCA", "ATM", "PALB2", "CDK12")):
            codes.append("OLAPARIB")
        if psma_positive:
            codes.append("LU177_PSMA617")
    normalized = []
    for code in codes:
        normalized_code = normalize_regimen_code(code)
        if normalized_code and normalized_code not in normalized:
            normalized.append(normalized_code)
    return normalized


def _requirements_for(state: str, payload: dict[str, Any], result: dict[str, Any] | None) -> list[dict[str, Any]]:
    codes = _candidate_codes(state, payload, result)
    fields: list[str] = list(STATE_CORE_FIELDS.get(state, []))
    if any(code.startswith("ADT_") and any(token in code for token in ("APALUTAMIDE", "ENZALUTAMIDE", "DAROLUTAMIDE", "ABIRATERONE")) for code in codes):
        fields.extend(ARPI_FIELDS)
    if any("ABIRATERONE" in code for code in codes):
        fields.extend(ABIRATERONE_FIELDS)
    if any("DOCETAXEL" in code for code in codes):
        fields.extend(DOCETAXEL_FIELDS)
    if "CABAZITAXEL" in codes:
        fields.extend(CABAZITAXEL_FIELDS)
    if any(code in codes for code in ("OLAPARIB", "OLAPARIB_ABIRATERONE", "NIRAPARIB_ABIRATERONE", "TALAZOPARIB_ENZALUTAMIDE")):
        fields.extend(OLAPARIB_FIELDS)
    if state.startswith("mcspc_"):
        fields.extend(MHCSPC_BIOMARKER_FIELDS)
    if any(code in codes for code in ("LU177_PSMA617", "RADIUM223", "ENZALUTAMIDE_RADIUM223")):
        fields.extend(PSMA_FIELDS)
    if state == "m1_crpc":
        fields.extend(["soft_tissue_metastases", "bone_modifying_agent"])
    if _safe_int(payload.get("ecog_score") or payload.get("ecog")) != 2:
        fields = [field for field in fields if field not in {"performance_status_driver", "bone_pain"}]
    prior_docetaxel_cycles = _safe_int(payload.get("prior_docetaxel_cycles")) or 0
    if prior_docetaxel_cycles <= 0 and "CABAZITAXEL" not in codes:
        fields = [field for field in fields if field != "prior_arpi_duration_months"]
    requirements = []
    for field_name in _dedupe(fields):
        definition = FIELD_DEFINITIONS.get(field_name)
        if not definition:
            continue
        requirements.append({
            "name": field_name,
            "label": definition.get("label", field_name),
            "group": definition.get("group", "Clinico"),
            "role": definition.get("role", "preference"),
            "why_needed": definition.get("why_needed", "Cambia la decision clinica."),
            "priority": int(definition.get("priority") or 50),
            "aliases": _field_aliases(field_name),
            "treatment_scope": _treatment_scope_for_field(field_name, codes),
        })
    return requirements


def _treatment_scope_for_field(field_name: str, codes: list[str]) -> list[str]:
    scope = []
    for code in codes:
        if field_name in STATE_CORE_FIELDS.get("m0_crpc", []) + STATE_CORE_FIELDS.get("m1_crpc", []) or field_name in STATE_CORE_FIELDS.get("mcspc_high_volume", []):
            scope.append(code)
        elif field_name in DOCETAXEL_FIELDS and "DOCETAXEL" in code:
            scope.append(code)
        elif field_name in CABAZITAXEL_FIELDS and code == "CABAZITAXEL":
            scope.append(code)
        elif field_name in OLAPARIB_FIELDS and code in {"OLAPARIB", "OLAPARIB_ABIRATERONE", "NIRAPARIB_ABIRATERONE", "TALAZOPARIB_ENZALUTAMIDE"}:
            scope.append(code)
        elif field_name in ABIRATERONE_FIELDS and "ABIRATERONE" in code:
            scope.append(code)
        elif field_name in ARPI_FIELDS and any(token in code for token in ("APALUTAMIDE", "ENZALUTAMIDE", "DAROLUTAMIDE", "ABIRATERONE")):
            scope.append(code)
        elif field_name in PSMA_FIELDS and code in {"LU177_PSMA617", "RADIUM223", "ENZALUTAMIDE_RADIUM223"}:
            scope.append(code)
    return _dedupe(scope)


def _active_reason(payload: dict[str, Any], field_name: str) -> str:
    value = _field_value(payload, field_name)
    numeric = _safe_float(value)
    if field_name in {"comorbidity_seizure", "stroke_history", "cognitive_risk", "fall_risk", "dermatitis_history", "comorbidity_cardio", "cv_risk_documented", "edema_risk", "diabetes_uncontrolled", "steroid_intolerance", "hepatic_risk_factors", "taxane_hypersensitivity_history", "polysorbate_hypersensitivity", "bone_marrow_reserve_concern", "strong_cyp3a_inhibitor", "psma_negative_dominant_lesions", "soft_tissue_metastases", "bone_modifying_agent"} and _truthy(value):
        return "Refinador activo documentado."
    if field_name == "child_pugh_score" and str(value or "").upper() in {"B", "C"}:
        return f"Child-Pugh {str(value).upper()} documentado."
    if field_name == "frailty_status" and str(value or "").strip().lower() in {"vulnerable", "frail"}:
        return f"Fragilidad {value} documentada."
    if field_name == "peripheral_neuropathy_grade" and numeric is not None and numeric >= 2:
        return f"Neuropatia grado {numeric:g} documentada."
    if field_name == "ecog_score" and numeric is not None and numeric >= 2:
        return f"ECOG {numeric:g} cambia intensidad."
    if field_name == "anc" and numeric is not None and numeric < 1500:
        return "ANC bajo para taxano."
    if field_name == "platelets" and numeric is not None and numeric < 100000:
        return "Plaquetas bajas para taxano/PARP."
    if field_name == "hemoglobin" and numeric is not None and numeric < 10:
        return "Hemoglobina <10 g/dL aumenta toxicidad hematologica."
    if field_name == "bilirubin" and numeric is not None and numeric > 1.2:
        return "Bilirrubina elevada cambia taxanos/abiraterona."
    if field_name == "potassium" and numeric is not None and numeric < 3.5:
        return "Hipokalemia debe corregirse antes de abiraterona."
    if field_name == "baseline_bp" and numeric is not None and numeric >= 160:
        return "TA basal elevada cambia seguridad cardiometabolica."
    if field_name == "egfr" and numeric is not None and numeric <= 50:
        return "Funcion renal reducida requiere ajuste/cautela."
    if field_name == "current_medications" and _field_present(payload, field_name) and not _truthy(payload.get("drug_interaction_reviewed")):
        return "Polifarmacia sin revision DDI."
    return ""


def _field_status(requirement: dict[str, Any], payload: dict[str, Any], schema_names: set[str]) -> dict[str, Any]:
    field_name = str(requirement["name"])
    missing = not _field_present(payload, field_name)
    stale = False if missing else _field_stale(payload, field_name)
    active_reason = "" if missing else _active_reason(payload, field_name)
    blocks_definitive = requirement.get("role") in {"required", "safety"} and (missing or stale)
    if field_name in {"current_medications", "baseline_weight", "fatigue_baseline", "neurocognitive_baseline", "fall_history_recent", "baseline_qol", "soft_tissue_metastases", "bone_modifying_agent"}:
        blocks_definitive = False
    if field_name == "drug_interaction_reviewed" and _field_present(payload, "current_medications") and not _truthy(payload.get("drug_interaction_reviewed")):
        blocks_definitive = True
    return {
        **requirement,
        "status": "missing" if missing else "stale" if stale else "active" if active_reason else "complete",
        "missing": missing,
        "stale": stale,
        "active_reason": active_reason,
        "blocks_definitive_recommendation": blocks_definitive,
        "field_source": _field_source(field_name, schema_names),
        "renderable": _field_renderable(field_name, schema_names),
        "value_present": _field_present(payload, field_name),
    }


def _status_sort_key(item: dict[str, Any]) -> tuple[int, int]:
    status_weight = {"missing": 4, "stale": 3, "active": 2, "complete": 1}.get(str(item.get("status")), 0)
    block_weight = 2 if item.get("blocks_definitive_recommendation") else 0
    return (status_weight + block_weight, int(item.get("priority") or 0))


def _preferred_entry(result: dict[str, Any], ranked: list[dict[str, Any]]) -> dict[str, Any]:
    preferred = result.get("preferred_frontline_regimen") or result.get("preferred_treatment") or {}
    if preferred:
        code = _normalize_code_from_item(preferred)
        return {
            "regimen_code": code,
            "regimen_label": preferred.get("regimen_label") or preferred.get("display_label") or preferred.get("name") or regimen_label(code),
            "preference_confidence": preferred.get("preference_confidence") or "definitive",
            "why_this_rank": list(preferred.get("selection_rationale") or preferred.get("why_this_rank") or []),
        }
    return ranked[0] if ranked else {}


def _ranked_options(result: dict[str, Any], payload: dict[str, Any], requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_items: list[dict[str, Any]] = []
    for key in ("frontline_regimen_rankings", "eligible_treatments", "alternative_regimens"):
        for item in result.get(key) or []:
            if isinstance(item, dict):
                raw_items.append(item)
    seen: set[str] = set()
    ranked = []
    for index, item in enumerate(raw_items, start=1):
        code = _normalize_code_from_item(item)
        if not code or code in seen:
            continue
        seen.add(code)
        treatment_requirements = [req for req in requirements if code in (req.get("treatment_scope") or [])]
        missing = [req["name"] for req in treatment_requirements if req.get("status") in {"missing", "stale"}]
        safety_flags = _contraindication_flags_for(code, payload)
        ranked.append({
            "rank": len(ranked) + 1,
            "regimen_code": code,
            "regimen_label": item.get("regimen_label") or item.get("display_label") or item.get("name") or regimen_label(code),
            "priority": item.get("priority", "eligible"),
            "eligibility_status": item.get("eligibility_status") or ("preferred" if item.get("priority") == "preferred" else "eligible_nonpreferred"),
            "preference_confidence": "provisional" if any(req.get("blocks_definitive_recommendation") for req in treatment_requirements) else item.get("preference_confidence", "definitive"),
            "why_this_rank": list(item.get("selection_rationale") or item.get("why_this_rank") or ([] if not item.get("notes") else [item.get("notes")]))[:4],
            "why_not_alternative": "" if item.get("priority") == "preferred" or item.get("is_preferred") else "Permanece elegible, pero queda por debajo por encaje de evidencia, seguridad o datos incompletos.",
            "missing_refiners": missing,
            "contraindication_flags": safety_flags,
            "adverse_event_watchlist": _watchlist_for(code),
        })
    return ranked


def _watchlist_for(code: str) -> list[str]:
    normalized = normalize_regimen_code(code)
    events = list(TREATMENT_WATCHLISTS.get(normalized) or [])
    if normalized == "ADT_DOCETAXEL_ABIRATERONE":
        events = _dedupe(TREATMENT_WATCHLISTS["ADT_DOCETAXEL"] + TREATMENT_WATCHLISTS["ADT_ABIRATERONE"])
    if normalized == "ADT_DOCETAXEL_DAROLUTAMIDE":
        events = _dedupe(TREATMENT_WATCHLISTS["ADT_DOCETAXEL"] + TREATMENT_WATCHLISTS["ADT_DAROLUTAMIDE"])
    return events


def _contraindication_flags_for(code: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = normalize_regimen_code(code)
    flags: list[dict[str, Any]] = []

    def add(field: str, severity: str, rationale: str) -> None:
        flags.append({"regimen_code": normalized, "field": field, "severity": severity, "rationale": rationale})

    child = str(_field_value(payload, "child_pugh_score") or "").upper()
    hepatic = _truthy(_field_value(payload, "hepatic_risk_factors"))
    seizure = _truthy(_field_value(payload, "comorbidity_seizure"))
    stroke = _truthy(_field_value(payload, "stroke_history"))
    dermatitis = _truthy(_field_value(payload, "dermatitis_history"))
    cardio = _truthy(_field_value(payload, "comorbidity_cardio")) or _truthy(_field_value(payload, "cv_risk_documented"))
    edema = _truthy(_field_value(payload, "edema_risk"))
    steroid = _truthy(_field_value(payload, "steroid_intolerance")) or _truthy(_field_value(payload, "diabetes_uncontrolled"))
    anc = _safe_float(_field_value(payload, "anc"))
    platelets = _safe_float(_field_value(payload, "platelets"))
    bilirubin = _safe_float(_field_value(payload, "bilirubin"))
    hemoglobin = _safe_float(_field_value(payload, "hemoglobin"))
    egfr = _safe_float(_field_value(payload, "egfr"))
    potassium = _safe_float(_field_value(payload, "potassium"))
    bp = _safe_float(_field_value(payload, "baseline_bp"))
    hrr_status = str(_field_value(payload, "hrr_status") or "").lower()
    hrr_gene = str(_field_value(payload, "hrr_gene") or "")
    prior = str(payload.get("prior_therapy") or "").lower()

    if "ABIRATERONE" in normalized:
        if child == "C" or hepatic:
            add("child_pugh_score", "blocker", "Riesgo hepatico relevante: abiraterona no debe liderar hasta aclarar/optimizar seguridad hepatica.")
        elif child == "B":
            add("child_pugh_score", "caution", "Child-Pugh B exige reduccion/monitoreo estrecho si se usa abiraterona.")
        if potassium is not None and potassium < 3.5:
            add("potassium", "blocker", "Hipokalemia debe corregirse antes de abiraterona.")
        if bp is not None and bp >= 160:
            add("baseline_bp", "caution", "Hipertension basal aumenta riesgo con abiraterona.")
        if cardio or edema or steroid:
            add("comorbidity_cardio", "caution", "Riesgo cardio-metabolico/esteroide desprioriza abiraterona frente a alternativas sin prednisona.")
    if normalized.endswith("ENZALUTAMIDE"):
        if seizure or stroke:
            add("comorbidity_seizure", "caution", "Riesgo convulsivo/neurovascular desprioriza enzalutamida.")
    if normalized.endswith("APALUTAMIDE"):
        if seizure:
            add("comorbidity_seizure", "caution", "Riesgo convulsivo desprioriza apalutamida.")
        if dermatitis:
            add("dermatitis_history", "caution", "Antecedente dermatologico desprioriza apalutamida por riesgo de rash.")
    if "DOCETAXEL" in normalized or normalized == "DOCETAXEL":
        if anc is not None and anc < 1500:
            add("anc", "blocker", "Neutrofilos <1500/mm3 bloquean docetaxel.")
        if platelets is not None and platelets < 100000:
            add("platelets", "blocker", "Plaquetas <100000/mm3 bloquean taxano.")
        if bilirubin is not None and bilirubin > 1.2:
            add("bilirubin", "blocker", "Bilirrubina > ULN bloquea docetaxel.")
        if _truthy(_field_value(payload, "taxane_hypersensitivity_history")) or _truthy(_field_value(payload, "polysorbate_hypersensitivity")):
            add("taxane_hypersensitivity_history", "blocker", "Hipersensibilidad a taxano/polisorbato bloquea docetaxel.")
    if normalized == "CABAZITAXEL":
        if "docetax" not in prior and (_safe_int(payload.get("prior_docetaxel_cycles")) or 0) < 1:
            add("prior_docetaxel_cycles", "blocker", "Cabazitaxel requiere tratamiento previo con docetaxel.")
        if anc is not None and anc <= 1500:
            add("anc", "blocker", "Neutrofilos <=1500/mm3 bloquean cabazitaxel.")
        if bilirubin is not None and bilirubin > 3.6:
            add("bilirubin", "blocker", "Disfuncion hepatica severa bloquea cabazitaxel.")
        if _truthy(_field_value(payload, "polysorbate_hypersensitivity")):
            add("polysorbate_hypersensitivity", "blocker", "Hipersensibilidad a polisorbato 80 bloquea cabazitaxel.")
    if normalized in {"OLAPARIB", "OLAPARIB_ABIRATERONE", "NIRAPARIB_ABIRATERONE", "TALAZOPARIB_ENZALUTAMIDE"}:
        if not hrr_status.startswith("pos") and not any(token in hrr_gene for token in ("BRCA", "ATM", "PALB2", "CDK12")):
            add("hrr_status", "blocker", "PARP requiere biomarcador HRR/BRCA trazable.")
        if hemoglobin is not None and hemoglobin < 10:
            add("hemoglobin", "caution", "Anemia basal aumenta riesgo hematologico con PARP.")
        if egfr is not None and egfr <= 30:
            add("egfr", "caution", "Funcion renal severamente reducida: no cerrar PARP sin ajuste/revision.")
    return flags


def _blocked_treatments(result: dict[str, Any], payload: dict[str, Any], candidates: list[str]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for item in result.get("frontline_regimen_rejections") or result.get("rejected_regimens") or []:
        if not isinstance(item, dict):
            continue
        code = _normalize_code_from_item(item)
        if not code:
            continue
        blocked.append({
            "regimen_code": code,
            "regimen_label": item.get("regimen_label") or item.get("name") or regimen_label(code),
            "reason": "; ".join(list(item.get("contraindication_reasons") or item.get("hard_blocks") or [])[:4]) or "No supero el ranking clinico de seguridad/evidencia.",
            "source": "ranking_engine",
        })
    for code in candidates:
        hard_flags = [flag for flag in _contraindication_flags_for(code, payload) if flag.get("severity") == "blocker"]
        if hard_flags and code not in {item["regimen_code"] for item in blocked}:
            blocked.append({
                "regimen_code": code,
                "regimen_label": regimen_label(code),
                "reason": "; ".join(flag["rationale"] for flag in hard_flags[:3]),
                "source": "decision_refiner_contract",
            })
    return blocked


def build_decision_refiner_contract(
    state: str,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    result = result or {}
    state = str(state or result.get("state") or "").strip()
    if state not in SYSTEMIC_STATES:
        return {}
    schema_names = _schema_fields(schema)
    schema_labels = _schema_label_index(schema)
    candidates = _candidate_codes(state, payload, result)
    requirements = [_field_status(req, payload, schema_names) for req in _requirements_for(state, payload, result)]
    requirements = sorted(requirements, key=_status_sort_key, reverse=True)
    visible = [item for item in requirements if item["status"] in {"missing", "stale", "active"}]
    if not visible:
        visible = [item for item in requirements if item.get("role") in {"required", "safety"}][:6]
    visible_refiners = visible[:6]
    secondary_refiners = [item for item in requirements if item not in visible_refiners]
    ranked = _ranked_options(result, payload, requirements)
    preferred = _preferred_entry(result, ranked)
    blocked = _blocked_treatments(result, payload, candidates)
    missing_fields = [item for item in requirements if item["status"] == "missing"]
    stale_fields = [item for item in requirements if item["status"] == "stale"]
    missing_renderable = [item["name"] for item in missing_fields if item.get("renderable")]
    unmapped = [item["name"] for item in requirements if not item.get("renderable") and item.get("field_source") != "longitudinal_tracking"]
    definitive_blockers = [item["name"] for item in requirements if item.get("blocks_definitive_recommendation")]
    contraindication_flags = []
    for code in candidates:
        contraindication_flags.extend(_contraindication_flags_for(code, payload))
    contraindication_flags = _dedupe(contraindication_flags)
    watchlist = [
        {"regimen_code": code, "regimen_label": regimen_label(code), "events": _watchlist_for(code)}
        for code in candidates
        if _watchlist_for(code)
    ]
    preferred_label = preferred.get("regimen_label") or regimen_label(preferred.get("regimen_code")) if preferred else ""
    why_preferred = list(preferred.get("why_this_rank") or [])[:4]
    if not why_preferred and preferred_label:
        why_preferred = [f"{preferred_label} lidera el ranking clinico actual con los datos disponibles."]
    why_not = []
    for item in ranked[1:5]:
        why_not.append({
            "regimen_code": item.get("regimen_code"),
            "regimen_label": item.get("regimen_label"),
            "reason": item.get("why_not_alternative") or "; ".join(item.get("missing_refiners") or []) or "No supero al preferente por balance clinico integral.",
        })
    for item in blocked[:4]:
        why_not.append({"regimen_code": item.get("regimen_code"), "regimen_label": item.get("regimen_label"), "reason": item.get("reason")})
    clinical_gap_reason = ""
    if definitive_blockers:
        clinical_gap_reason = "La recomendacion debe mostrarse como provisional hasta cerrar: " + ", ".join(definitive_blockers[:6]) + "."
    if unmapped:
        clinical_gap_reason = (clinical_gap_reason + " " if clinical_gap_reason else "") + "Hay refinadores usados por backend sin campo UI directo: " + ", ".join(unmapped[:6]) + "."
    return {
        "contract_version": CONTRACT_VERSION,
        "state": state,
        "scenario_family": "mCRPC" if state == "m1_crpc" else "nmCRPC" if state == "m0_crpc" else "mHSPC/mCSPC",
        "candidate_treatments": candidates,
        "preferred_treatment": preferred,
        "ranked_treatment_options": ranked,
        "blocked_treatments": blocked,
        "why_preferred": why_preferred,
        "why_not_alternatives": why_not,
        "required_fields": [item for item in requirements if item.get("role") == "required"],
        "preference_refiners": [item for item in requirements if item.get("role") == "preference"],
        "safety_refiners": [item for item in requirements if item.get("role") == "safety"],
        "monitoring_fields": [item for item in requirements if item.get("role") == "monitoring"],
        "missing_fields": missing_fields,
        "stale_fields": stale_fields,
        "missing_refiners": missing_fields + stale_fields,
        "field_source": {item["name"]: item.get("field_source") for item in requirements},
        "why_needed": {item["name"]: item.get("why_needed") for item in requirements},
        "contraindication_flags": contraindication_flags,
        "adverse_event_watchlist": watchlist,
        "clinical_gap_reason": clinical_gap_reason,
        "ui_contract": {
            "max_visible_refiners": 6,
            "visible_refiners": visible_refiners,
            "secondary_refiners": secondary_refiners,
            "missing_renderable_fields": missing_renderable,
            "unmapped_backend_fields": unmapped,
            "schema_field_names": sorted(schema_names),
            "schema_field_labels": schema_labels,
            "provisional_recommendation": bool(definitive_blockers),
        },
        "evidence_basis": EVIDENCE_BASIS,
    }


def build_static_decision_refiner_contract(state: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = build_decision_refiner_contract(state, {}, {"state": state}, schema)
    if not contract:
        return {}
    return {
        "contract_version": CONTRACT_VERSION,
        "state": state,
        "scenario_family": contract.get("scenario_family", ""),
        "candidate_treatments": contract.get("candidate_treatments", []),
        "required_fields": contract.get("required_fields", []),
        "preference_refiners": contract.get("preference_refiners", []),
        "safety_refiners": contract.get("safety_refiners", []),
        "monitoring_fields": contract.get("monitoring_fields", []),
        "ui_contract": {
            "max_visible_refiners": 6,
            "schema_field_names": contract.get("ui_contract", {}).get("schema_field_names", []),
            "unmapped_backend_fields": contract.get("ui_contract", {}).get("unmapped_backend_fields", []),
        },
    }


def attach_decision_refiner_contract(
    result: dict[str, Any],
    *,
    state: str,
    payload: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state not in SYSTEMIC_STATES:
        return result
    enriched = dict(result or {})
    contract = build_decision_refiner_contract(state, payload or {}, enriched, schema)
    if not contract:
        return enriched
    enriched["decision_refiner_contract"] = contract
    enriched["preferred_treatment"] = contract.get("preferred_treatment", {})
    enriched["ranked_treatment_options"] = contract.get("ranked_treatment_options", [])
    enriched["blocked_treatments"] = contract.get("blocked_treatments", [])
    enriched["why_preferred"] = contract.get("why_preferred", [])
    enriched["why_not_alternatives"] = contract.get("why_not_alternatives", [])
    enriched["missing_refiners"] = contract.get("missing_refiners", [])
    enriched["contraindication_flags"] = contract.get("contraindication_flags", [])
    enriched["adverse_event_watchlist"] = contract.get("adverse_event_watchlist", [])
    enriched["clinical_gap_reason"] = contract.get("clinical_gap_reason", "")
    decision_quality = dict(enriched.get("decision_quality") or {})
    if (contract.get("ui_contract") or {}).get("provisional_recommendation"):
        decision_quality["confidence_category"] = "provisional"
        decision_quality["requires_human_review"] = True
        why = list(decision_quality.get("why_not_more_confident") or [])
        if contract.get("clinical_gap_reason") and contract.get("clinical_gap_reason") not in why:
            why.append(contract.get("clinical_gap_reason"))
        decision_quality["why_not_more_confident"] = why
    enriched["decision_quality"] = decision_quality
    return enriched
