from __future__ import annotations

from copy import deepcopy
from typing import Any
import re


REQUESTED_PIVOTAL_STUDY_NAMES: tuple[str, ...] = (
    "RADICALS-RT",
    "EMBARK",
    "PRESTO / AFT-19",
    "CHAARTED",
    "LATITUDE",
    "STAMPEDE",
    "ENZAMET",
    "ARCHES",
    "TITAN",
    "PEACE-1",
    "ARASENS",
    "ARANOTE",
    "AMPLITUDE",
    "SPARTAN",
    "PROSPER",
    "ARAMIS",
    "TAX-327",
    "TROPIC",
    "CARD",
    "COU-AA-301",
    "COU-AA-302",
    "AFFIRM",
    "PREVAIL",
    "ALSYMPCA",
    "VISION",
    "PSMAfore",
    "TheraP",
    "PEACE-3",
    "PROfound",
    "PROpel",
    "MAGNITUDE",
    "TALAPRO-2",
    "TRITON-3",
    "IMPACT",
    "IPATential150",
    "CONTACT-02",
)


def normalize_study_name(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = text.replace("PSMAFORE", "PSMAFORE")
    text = text.replace("TAX 327", "TAX-327")
    text = text.replace("TAX327", "TAX-327")
    text = text.replace("PROPEL", "PROPEL")
    text = text.replace("PROFOUND", "PROFOUND")
    text = text.replace("IPATENTIAL150", "IPATENTIAL150")
    text = text.replace("AFT19", "AFT-19")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"[^A-Z0-9]+", "", text)
    aliases = {
        "PRESTOAFT19": "PRESTOAFT19",
        "AFT19": "PRESTOAFT19",
        "PRESTO": "PRESTOAFT19",
        "COUAA301": "COUAA301",
        "COUAA302": "COUAA302",
        "TAX327": "TAX327",
        "PSMAFORE": "PSMAFORE",
        "THERAP": "THERAP",
    }
    return aliases.get(text, text)


def _source(label: str, url: str, tier: str = "primary_trial") -> dict[str, str]:
    return {"label": label, "url": url, "source_tier": tier}


def _patient(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "age": 68,
        "psa": 18.0,
        "psa_current": 18.0,
        "gleason_score": 8,
        "gleason_primary": 4,
        "gleason_secondary": 4,
        "clinical_tstage": "T3A",
        "ecog_score": 1,
        "metastasis_status": "M0",
        "metastasis_site": "M0",
        "metastasis_count": 0,
        "volume_chaarted": "Low",
        "castration_resistant": False,
        "testosterone_current": 18,
        "prior_therapy": [],
        "prior_prostatectomy": False,
        "fit_for_chemotherapy": True,
        "peripheral_neuropathy_grade": 0,
        "frailty_status": "Fit",
        "child_pugh_score": "A",
        "drug_interaction_reviewed": 1,
        "cv_risk_documented": 1,
        "hrr_status": "Negativo",
        "brca_status": "Negativo",
        "msi_status": "Estable",
        "psma_pet_result": "No realizado",
        "psma_negative_dominant_lesions": False,
        "bone_metastases": False,
        "visceral_metastases": False,
        "symptomatic_bone": False,
        "pain_symptoms": "Leve",
        "line_of_therapy_context": "",
        "line_of_therapy_number": 1,
    }
    payload.update(overrides)
    return payload


def _profile(
    canonical_name: str,
    *,
    aliases: list[str],
    scenario: str,
    disease_state: str,
    module_id: str,
    line_context: str,
    regimen_code: str,
    regimen_label: str,
    agents: list[str],
    intervention: str,
    control: str,
    endpoint: str,
    key_result: str,
    population: str,
    criteria: dict[str, Any],
    required_inputs: list[str],
    adverse_events: list[str],
    contraindications: list[str],
    clinical_gap_reason: str,
    flagship_payload: dict[str, Any],
    sources: list[dict[str, str]],
    year: int,
    phase: str = "III",
    nccn_category: str = "evidence_context",
) -> dict[str, Any]:
    key = normalize_study_name(canonical_name)
    return {
        "study_key": key,
        "canonical_name": canonical_name,
        "aliases": aliases,
        "phase": phase,
        "scenario": scenario,
        "disease_state": disease_state,
        "module_id": module_id,
        "line_of_therapy_context": line_context,
        "regimen_code": regimen_code,
        "regimen_label": regimen_label,
        "agents": agents,
        "intervention": intervention,
        "control": control,
        "primary_endpoint": endpoint,
        "key_result": key_result,
        "population": population,
        "eligibility_criteria": criteria,
        "required_inputs": required_inputs,
        "adverse_event_watchlist": adverse_events,
        "contraindication_flags": contraindications,
        "clinical_gap_reason": clinical_gap_reason,
        "flagship_patient": {
            "id": f"flagship_{key.lower()}",
            "summary": population,
            "payload": flagship_payload,
            "expected": {
                "module_id": module_id,
                "study_name": canonical_name,
                "regimen_code": regimen_code,
                "line_of_therapy_context": line_context,
            },
        },
        "source_citations": sources,
        "year": year,
        "nccn_category": nccn_category,
        "mexican_applicability": (
            "Aplicabilidad condicionada por acceso local al farmaco, imagen molecular, perfil molecular, "
            "reserva funcional y comorbilidades. Prostamed debe mostrar brechas antes de cerrar conducta."
        ),
    }


PIVOTAL_STUDY_CATALOG: list[dict[str, Any]] = [
    _profile(
        "RADICALS-RT",
        aliases=["RADICALS", "RADICALS RT"],
        scenario="adyuvancia",
        disease_state="post_prostatectomy",
        module_id="post_prostatectomy",
        line_context="post_rp_early_salvage",
        regimen_code="EARLY_SALVAGE_RT",
        regimen_label="RT de salvage temprano vs RT adyuvante",
        agents=["Radioterapia"],
        intervention="RT adyuvante inmediata comparada con observacion y salvage temprano.",
        control="Salvage temprano al elevarse PSA.",
        endpoint="Supervivencia libre de progresion bioquimica.",
        key_result="Favorece reservar RT para salvage temprano en lugar de adyuvancia rutinaria cuando la ventana local sigue abierta.",
        population="Post-prostatectomia con factores patologicos adversos, PSA bajo o indetectable y sin metastasis.",
        criteria={"age_min": 18, "age_max": 85, "psa_min": 0, "psa_max": 0.2, "gleason_min": 6, "gleason_max": 10, "ecog_max": 2, "metastasis": "M0", "prior_prostatectomy": True},
        required_inputs=["psa_current", "prior_prostatectomy", "pathologic_stage", "surgical_margin", "metastasis_status"],
        adverse_events=["toxicidad urinaria", "toxicidad intestinal", "disfuncion sexual", "fatiga"],
        contraindications=["metastasis confirmada", "toxicidad urinaria no controlada", "enfermedad inflamatoria intestinal activa"],
        clinical_gap_reason="Sin PSA postoperatorio trazable no se puede separar adyuvancia de salvage temprano.",
        flagship_payload=_patient(state="post_prostatectomy", psa=0.08, psa_current=0.08, prior_prostatectomy=True, pathologic_stage="pT3a", surgical_margin=1, metastasis_status="M0"),
        sources=[_source("RADICALS-RT / ARTISTIC collaboration", "https://pubmed.ncbi.nlm.nih.gov/33002431/")],
        year=2020,
    ),
    _profile(
        "EMBARK",
        aliases=["EMBARK BCR"],
        scenario="rescate",
        disease_state="high_risk_bcr_m0",
        module_id="recurrence_bcr",
        line_context="bcr_high_risk_systemic",
        regimen_code="ADT_ENZALUTAMIDE",
        regimen_label="Enzalutamida con o sin leuprolida",
        agents=["ADT", "Enzalutamida"],
        intervention="Enzalutamida + leuprolida o enzalutamida monoterapia.",
        control="Leuprolida sola.",
        endpoint="Supervivencia libre de metastasis.",
        key_result="Intensificacion del eje androgenico mejora MFS en recurrencia bioquimica M0 de alto riesgo.",
        population="BCR M0 de alto riesgo con PSADT corto y sin opcion local dominante.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 1, "psa_max": 999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 1, "metastasis": "M0", "psadt_max_months": 9},
        required_inputs=["psa_current", "psadt_months", "metastasis_status", "salvage_local_feasible", "seizure_history"],
        adverse_events=["fatiga", "caidas", "hipertension", "eventos cognitivos", "convulsiones raras"],
        contraindications=["convulsiones previas", "alto riesgo de caidas", "interacciones CYP no revisadas"],
        clinical_gap_reason="No debe liderar si existe salvage local potencialmente curativo o si falta PSADT.",
        flagship_payload=_patient(state="recurrence_bcr", psa=3.2, psa_current=3.2, psadt_months=5.0, metastasis_status="M0", prior_prostatectomy=True, salvage_local_feasible=False, seizure_history=0, line_of_therapy_context="bcr_high_risk_systemic"),
        sources=[_source("EMBARK", "https://pubmed.ncbi.nlm.nih.gov/37851874/")],
        year=2023,
    ),
    _profile(
        "PRESTO / AFT-19",
        aliases=["PRESTO", "AFT-19", "PRESTO AFT-19"],
        scenario="rescate",
        disease_state="high_risk_bcr_m0",
        module_id="recurrence_bcr",
        line_context="bcr_high_risk_intensified_adt",
        regimen_code="ADT_APALUTAMIDE_ABIRATERONE",
        regimen_label="ADT +/- apalutamida +/- abiraterona/prednisona",
        agents=["ADT", "Apalutamida", "Abiraterona", "Prednisona"],
        intervention="Intensificacion finita de ADT con apalutamida y abiraterona/prednisona.",
        control="ADT sola por duracion finita.",
        endpoint="Supervivencia libre de progresion bioquimica.",
        key_result="Define un arquetipo de BCR de alto riesgo donde la intensificacion sistemica exige seguridad cardiovascular, hepatica y metabolica.",
        population="BCR de alto riesgo posterior a terapia local, M0 por imagen convencional y PSADT corto.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 0.5, "psa_max": 999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 1, "metastasis": "M0", "psadt_max_months": 9},
        required_inputs=["psa_current", "psadt_months", "metastasis_status", "child_pugh_score", "cv_risk_documented", "seizure_history"],
        adverse_events=["hipertension", "hipokalemia", "edema", "rash", "fatiga", "fracturas"],
        contraindications=["Child-Pugh B/C", "hipertension no controlada", "convulsiones previas", "alto riesgo de caidas"],
        clinical_gap_reason="No se debe ofrecer triplete hormonal si faltan PSADT, M0 convencional o seguridad hepatocardiovascular.",
        flagship_payload=_patient(state="recurrence_bcr", psa=2.6, psa_current=2.6, psadt_months=4.5, metastasis_status="M0", child_pugh_score="A", cv_risk_documented=1, seizure_history=0),
        sources=[_source("PRESTO / AFT-19", "https://pubmed.ncbi.nlm.nih.gov/?term=PRESTO+AFT-19+prostate+cancer")],
        year=2024,
    ),
    _profile(
        "CHAARTED",
        aliases=["E3805", "CHAARTED E3805"],
        scenario="mHSPC",
        disease_state="mHSPC high-volume",
        module_id="mcspc_high_volume_sync",
        line_context="mHSPC_initial",
        regimen_code="ADT_DOCETAXEL",
        regimen_label="ADT + docetaxel",
        agents=["ADT", "Docetaxel"],
        intervention="ADT + docetaxel por 6 ciclos.",
        control="ADT sola.",
        endpoint="Supervivencia global.",
        key_result="Mayor beneficio en enfermedad metastasica sensible a castracion de alto volumen apta para docetaxel.",
        population="mHSPC de alto volumen, ECOG conservado y reserva medular/hepatica adecuada.",
        criteria={"age_min": 18, "age_max": 85, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 1, "metastasis": "M1", "fit_for_chemotherapy": True},
        required_inputs=["metastasis_count", "metastasis_site", "ecog_score", "peripheral_neuropathy_grade", "anc", "platelets", "child_pugh_score"],
        adverse_events=["neutropenia", "neuropatia", "fatiga", "infeccion", "alopecia"],
        contraindications=["neuropatia grado >=2", "neutropenia", "plaquetopenia", "ECOG alto", "hiperbilirrubinemia"],
        clinical_gap_reason="Docetaxel no debe recomendarse sin verificar aptitud, hemograma, funcion hepatica y neuropatia.",
        flagship_payload=_patient(state="mcspc_high_volume_sync", psa=84, metastasis_status="M1", metastasis_site="Bone", metastasis_count=6, volume_chaarted="High", de_novo=True, fit_for_chemotherapy=True, anc=2400, platelets=210000),
        sources=[_source("CHAARTED", "https://pubmed.ncbi.nlm.nih.gov/26244877/")],
        year=2015,
        nccn_category="1",
    ),
    _profile(
        "LATITUDE",
        aliases=["LATITUDE trial"],
        scenario="mHSPC",
        disease_state="mHSPC high-risk de novo",
        module_id="mcspc_high_volume_sync",
        line_context="mHSPC_initial",
        regimen_code="ADT_ABIRATERONE",
        regimen_label="ADT + abiraterona + prednisona",
        agents=["ADT", "Abiraterona", "Prednisona"],
        intervention="ADT + abiraterona/prednisona.",
        control="ADT + placebo.",
        endpoint="Supervivencia global y rPFS.",
        key_result="Beneficio en mHSPC de novo de alto riesgo definido por criterios LATITUDE.",
        population="mHSPC de novo con al menos dos factores de alto riesgo: Gleason >=8, >=3 lesiones oseas o visceral.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 0, "psa_max": 99999, "gleason_min": 8, "gleason_max": 10, "ecog_max": 2, "metastasis": "M1", "de_novo": True, "high_risk_latitude": True},
        required_inputs=["gleason_score", "metastasis_count", "visceral_metastases", "child_pugh_score", "cv_risk_documented"],
        adverse_events=["hipertension", "hipokalemia", "edema", "hepatotoxicidad", "retencion hidrica"],
        contraindications=["Child-Pugh B/C", "hipertension no controlada", "insuficiencia cardiaca avanzada", "hipokalemia no corregida"],
        clinical_gap_reason="Falta de criterios LATITUDE o de seguridad hepatocardiovascular impide cerrar abiraterona.",
        flagship_payload=_patient(state="mcspc_high_volume_sync", psa=120, gleason_score=9, metastasis_status="M1", metastasis_site="Bone", metastasis_count=5, visceral_metastases=True, de_novo=True, child_pugh_score="A"),
        sources=[_source("LATITUDE", "https://pubmed.ncbi.nlm.nih.gov/28578607/")],
        year=2017,
        nccn_category="1",
    ),
    _profile(
        "STAMPEDE",
        aliases=["STAMPEDE platform", "STAMPEDE RT"],
        scenario="mHSPC",
        disease_state="mHSPC platform",
        module_id="mcspc_low_volume_sync_oligo",
        line_context="mHSPC_initial",
        regimen_code="RT_PRIMARY_LOW_VOLUME",
        regimen_label="ADT + intensificacion/RT al primario segun brazo STAMPEDE",
        agents=["ADT", "Radioterapia", "Docetaxel", "Abiraterona"],
        intervention="Brazos de intensificacion sistemica y RT al primario.",
        control="ADT estandar.",
        endpoint="Supervivencia global y failure-free survival.",
        key_result="Plataforma que informa intensificacion y RT al primario, especialmente en bajo volumen metastasico.",
        population="mHSPC con decision segun volumen, temporalidad y aptitud para intensificacion.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 2, "metastasis": "M1"},
        required_inputs=["metastasis_site", "metastasis_count", "volume_chaarted", "de_novo", "ecog_score"],
        adverse_events=["toxicidad urinaria por RT", "toxicidad intestinal", "toxicidad hormonal", "toxicidad por docetaxel/abiraterona segun brazo"],
        contraindications=["alto volumen para RT al primario", "metastasis visceral dominante para RT local", "contraindicaciones del farmaco elegido"],
        clinical_gap_reason="STAMPEDE no es un unico regimen; requiere definir brazo aplicable por volumen y objetivo terapeutico.",
        flagship_payload=_patient(state="mcspc_low_volume_sync_oligo", psa=42, metastasis_status="M1", metastasis_site="Bone", metastasis_count=2, volume_chaarted="Low", de_novo=True),
        sources=[_source("STAMPEDE", "https://pubmed.ncbi.nlm.nih.gov/?term=STAMPEDE+prostate+cancer+radiotherapy+primary")],
        year=2018,
        nccn_category="1",
    ),
    _profile(
        "ENZAMET",
        aliases=["ENZAMET trial"],
        scenario="mHSPC",
        disease_state="mHSPC",
        module_id="mcspc_oligo_metachronous",
        line_context="mHSPC_initial",
        regimen_code="ADT_ENZALUTAMIDE",
        regimen_label="ADT + enzalutamida",
        agents=["ADT", "Enzalutamida"],
        intervention="Enzalutamida + ADT.",
        control="Antiandrogeno no esteroideo convencional + ADT.",
        endpoint="Supervivencia global.",
        key_result="Soporta intensificacion hormonal con enzalutamida en mHSPC.",
        population="mHSPC recurrente o de novo con ECOG adecuado, considerando fatiga, caidas y riesgo convulsivo.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 2, "metastasis": "M1"},
        required_inputs=["metastasis_status", "ecog_score", "seizure_history", "fall_risk", "drug_interaction_reviewed"],
        adverse_events=["fatiga", "hipertension", "caidas", "eventos cognitivos", "convulsiones raras"],
        contraindications=["convulsiones previas", "alto riesgo de caidas", "deterioro cognitivo severo"],
        clinical_gap_reason="Enzalutamida requiere revisar neurologia, caidas e interacciones antes de seleccionar ARPI.",
        flagship_payload=_patient(state="mcspc_oligo_metachronous", psa=31, metastasis_status="M1", metastasis_site="Bone", metastasis_count=2, seizure_history=0, fall_risk="low"),
        sources=[_source("ENZAMET", "https://pubmed.ncbi.nlm.nih.gov/31157964/")],
        year=2019,
        nccn_category="1",
    ),
    _profile(
        "ARCHES",
        aliases=["ARCHES trial"],
        scenario="mHSPC",
        disease_state="mHSPC",
        module_id="mcspc_oligo_metachronous",
        line_context="mHSPC_initial",
        regimen_code="ADT_ENZALUTAMIDE",
        regimen_label="ADT + enzalutamida",
        agents=["ADT", "Enzalutamida"],
        intervention="Enzalutamida + ADT.",
        control="Placebo + ADT.",
        endpoint="rPFS.",
        key_result="Mejora rPFS en mHSPC a traves de volumenes y exposicion previa limitada a docetaxel.",
        population="mHSPC con enfermedad metastasica documentada, candidato a ARPI.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 2, "metastasis": "M1"},
        required_inputs=["metastasis_status", "ecog_score", "seizure_history", "fall_risk"],
        adverse_events=["fatiga", "hipertension", "caidas", "fracturas"],
        contraindications=["convulsiones previas", "interacciones no revisadas", "alto riesgo de caidas"],
        clinical_gap_reason="ARCHES no debe cerrar seleccion si faltan seguridad neurologica y riesgo de caidas.",
        flagship_payload=_patient(state="mcspc_oligo_metachronous", psa=29, metastasis_status="M1", metastasis_site="Bone", metastasis_count=3, seizure_history=0, fall_risk="low"),
        sources=[_source("ARCHES", "https://pubmed.ncbi.nlm.nih.gov/31329516/")],
        year=2019,
        nccn_category="1",
    ),
    _profile(
        "TITAN",
        aliases=["TITAN trial"],
        scenario="mHSPC",
        disease_state="mHSPC",
        module_id="mcspc_low_volume_sync_oligo",
        line_context="mHSPC_initial",
        regimen_code="ADT_APALUTAMIDE",
        regimen_label="ADT + apalutamida",
        agents=["ADT", "Apalutamida"],
        intervention="Apalutamida + ADT.",
        control="Placebo + ADT.",
        endpoint="OS y rPFS.",
        key_result="Apoya doblete con apalutamida en mHSPC con vigilancia dermatologica, tiroidea y de caidas.",
        population="mHSPC de novo o recurrente con perfil apto para apalutamida.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 2, "metastasis": "M1"},
        required_inputs=["metastasis_status", "ecog_score", "seizure_history", "fall_risk", "thyroid_status"],
        adverse_events=["rash", "hipotiroidismo", "caidas", "fracturas", "fatiga"],
        contraindications=["convulsiones previas", "rash severo no controlado", "alto riesgo de fractura sin soporte oseo"],
        clinical_gap_reason="Apalutamida requiere vigilar piel, tiroides, caidas y salud osea.",
        flagship_payload=_patient(state="mcspc_low_volume_sync_oligo", psa=37, metastasis_status="M1", metastasis_site="Bone", metastasis_count=2, seizure_history=0, fall_risk="low", thyroid_status="normal"),
        sources=[_source("TITAN", "https://pubmed.ncbi.nlm.nih.gov/31150574/")],
        year=2019,
        nccn_category="1",
    ),
    _profile(
        "PEACE-1",
        aliases=["PEACE1"],
        scenario="mHSPC",
        disease_state="mHSPC de novo high-volume",
        module_id="mcspc_high_volume_sync",
        line_context="mHSPC_initial_triplet",
        regimen_code="ADT_DOCETAXEL_ABIRATERONE",
        regimen_label="ADT + docetaxel + abiraterona/prednisona +/- RT",
        agents=["ADT", "Docetaxel", "Abiraterona", "Prednisona", "Radioterapia"],
        intervention="ADT + docetaxel + abiraterona/prednisona con evaluacion de RT al primario.",
        control="ADT + docetaxel.",
        endpoint="rPFS y OS.",
        key_result="Soporta triplete en mHSPC de novo, especialmente alto volumen, si la aptitud a docetaxel y abiraterona es adecuada.",
        population="mHSPC de novo/sincronico de alto volumen apto para triplete.",
        criteria={"age_min": 18, "age_max": 80, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 1, "metastasis": "M1", "de_novo": True, "fit_for_chemotherapy": True},
        required_inputs=["metastasis_count", "disease_temporality", "fit_for_chemotherapy", "child_pugh_score", "anc", "platelets"],
        adverse_events=["neutropenia", "neuropatia", "hipertension", "hipokalemia", "hepatotoxicidad", "toxicidad RT si aplica"],
        contraindications=["no apto para docetaxel", "Child-Pugh B/C", "hipertension no controlada", "neuropatia grado >=2"],
        clinical_gap_reason="PEACE-1 no debe extrapolarse fuera de de novo alto volumen ni sin verificar doble seguridad docetaxel/abiraterona.",
        flagship_payload=_patient(state="mcspc_high_volume_sync", psa=150, gleason_score=9, metastasis_status="M1", metastasis_site="Bone", metastasis_count=8, volume_chaarted="High", disease_temporality="sync", de_novo=True, fit_for_chemotherapy=True, anc=2600, platelets=220000),
        sources=[_source("PEACE-1", "https://pubmed.ncbi.nlm.nih.gov/35405085/")],
        year=2022,
        nccn_category="1",
    ),
    _profile(
        "ARASENS",
        aliases=["ARASENS trial"],
        scenario="mHSPC",
        disease_state="mHSPC triplet",
        module_id="mcspc_high_volume_sync",
        line_context="mHSPC_initial_triplet",
        regimen_code="ADT_DOCETAXEL_DAROLUTAMIDE",
        regimen_label="ADT + docetaxel + darolutamida",
        agents=["ADT", "Docetaxel", "Darolutamida"],
        intervention="Darolutamida + ADT + docetaxel.",
        control="Placebo + ADT + docetaxel.",
        endpoint="Supervivencia global.",
        key_result="Triplete con darolutamida mejora OS en mHSPC apto para docetaxel.",
        population="mHSPC apto para docetaxel, con revision de interacciones y reserva funcional.",
        criteria={"age_min": 18, "age_max": 85, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 1, "metastasis": "M1", "fit_for_chemotherapy": True},
        required_inputs=["fit_for_chemotherapy", "anc", "platelets", "peripheral_neuropathy_grade", "drug_interaction_reviewed", "child_pugh_score"],
        adverse_events=["neutropenia", "fatiga", "rash", "hipertension", "interacciones"],
        contraindications=["no apto para docetaxel", "interacciones no revisadas", "deterioro hepatico severo"],
        clinical_gap_reason="ARASENS exige comprobar que el paciente tolera docetaxel y que darolutamida no tiene interacciones relevantes.",
        flagship_payload=_patient(state="mcspc_high_volume_sync", psa=92, metastasis_status="M1", metastasis_site="Bone", metastasis_count=5, volume_chaarted="High", fit_for_chemotherapy=True, anc=2500, platelets=205000, drug_interaction_reviewed=1),
        sources=[_source("ARASENS", "https://pubmed.ncbi.nlm.nih.gov/35179323/")],
        year=2022,
        nccn_category="1",
    ),
    _profile(
        "ARANOTE",
        aliases=["ARANOTE trial"],
        scenario="mHSPC",
        disease_state="mHSPC doublet",
        module_id="mcspc_low_volume_sync_oligo",
        line_context="mHSPC_initial",
        regimen_code="ADT_DAROLUTAMIDE",
        regimen_label="ADT + darolutamida",
        agents=["ADT", "Darolutamida"],
        intervention="Darolutamida + ADT sin docetaxel.",
        control="Placebo + ADT.",
        endpoint="rPFS.",
        key_result="Darolutamida + ADT mejora rPFS frente a ADT sola en mHSPC sin quimioterapia obligatoria.",
        population="mHSPC de novo o recurrente, ECOG 0-2, cuando se busca doblete hormonal con menor carga neurologica.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 2, "metastasis": "M1"},
        required_inputs=["metastasis_status", "ecog_score", "drug_interaction_reviewed", "renal_function", "child_pugh_score"],
        adverse_events=["fatiga", "hipertension", "rash", "dolor musculoesqueletico"],
        contraindications=["interacciones no revisadas", "deterioro hepatico severo", "deterioro renal severo sin ajuste"],
        clinical_gap_reason="Darolutamida debe integrarse como doblete y no confundirse con el triplete ARASENS.",
        flagship_payload=_patient(state="mcspc_low_volume_sync_oligo", psa=56, metastasis_status="M1", metastasis_site="Bone", metastasis_count=2, drug_interaction_reviewed=1, renal_function="adequate"),
        sources=[_source("ARANOTE", "https://pmc.ncbi.nlm.nih.gov/articles/PMC11654448/")],
        year=2024,
        nccn_category="evidence_context",
    ),
    _profile(
        "AMPLITUDE",
        aliases=["AMPLITUDE trial"],
        scenario="mHSPC",
        disease_state="mCSPC HRR-mutated",
        module_id="mcspc_high_volume_sync",
        line_context="mHSPC_initial_precision",
        regimen_code="NIRAPARIB_ABIRATERONE",
        regimen_label="Niraparib + abiraterona/prednisona + ADT",
        agents=["Niraparib", "Abiraterona", "Prednisona", "ADT"],
        intervention="Niraparib + abiraterona/prednisona agregado a ADT.",
        control="Abiraterona/prednisona + ADT.",
        endpoint="rPFS.",
        key_result="Traslada PARP a mCSPC con alteraciones HRR; requiere biomarcador trazable y vigilancia hematologica.",
        population="mCSPC/mHSPC con alteracion HRR, frecuentemente alto volumen, candidato a abiraterona y PARP.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 2, "metastasis": "M1", "hrr_positive": True},
        required_inputs=["hrr_status", "biomarker_source", "hemoglobin", "platelets", "child_pugh_score", "cv_risk_documented"],
        adverse_events=["anemia", "trombocitopenia", "neutropenia", "hipertension", "hipokalemia", "hepatotoxicidad"],
        contraindications=["HRR no documentado", "mielosupresion basal", "Child-Pugh B/C", "hipertension no controlada"],
        clinical_gap_reason="AMPLITUDE no debe mostrarse como opcion de precision sin HRR trazable y reserva hematologica.",
        flagship_payload=_patient(state="mcspc_high_volume_sync", psa=115, metastasis_status="M1", metastasis_site="Bone", metastasis_count=6, hrr_status="Positivo", brca_status="BRCA2", biomarker_source="somatic_panel", hemoglobin=12.8, platelets=210000, child_pugh_score="A"),
        sources=[_source("AMPLITUDE", "https://www.nature.com/articles/s41591-025-03961-8")],
        year=2025,
        nccn_category="emerging_primary_trial",
    ),
]


def _m0_profile(name: str, regimen_code: str, regimen_label: str, agents: list[str], ae: list[str], contra: list[str], source: str, year: int) -> dict[str, Any]:
    return _profile(
        name,
        aliases=[f"{name} trial"],
        scenario="nmCRPC",
        disease_state="nmCRPC high-risk",
        module_id="m0_crpc",
        line_context="m0_CRPC_first_line",
        regimen_code=regimen_code,
        regimen_label=regimen_label,
        agents=agents,
        intervention=f"{regimen_label} manteniendo ADT.",
        control="Placebo + ADT.",
        endpoint="Supervivencia libre de metastasis.",
        key_result=f"{name} respalda intensificacion en nmCRPC con PSADT <=10 meses y testosterona de castracion.",
        population="nmCRPC M0 por imagen convencional, PSADT corto, ADT continua y ECOG conservado.",
        criteria={"age_min": 18, "age_max": 90, "psa_min": 2, "psa_max": 999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 1, "metastasis": "M0", "castration_resistant": True, "psadt_max_months": 10},
        required_inputs=["psa_current", "psadt_months", "testosterone_current", "metastasis_status", "seizure_history", "fall_risk"],
        adverse_events=ae,
        contraindications=contra,
        clinical_gap_reason="nmCRPC exige confirmar testosterona de castracion, M0 convencional y PSADT antes de iniciar ARPI.",
        flagship_payload=_patient(state="m0_crpc", psa=6.4, psa_current=6.4, psadt_months=5.8, metastasis_status="M0", metastasis_site="M0", castration_resistant=True, testosterone_current=16, seizure_history=0, fall_risk="low"),
        sources=[_source(name, source)],
        year=year,
        nccn_category="1",
    )


PIVOTAL_STUDY_CATALOG.extend([
    _m0_profile("SPARTAN", "ADT_APALUTAMIDE", "ADT + apalutamida", ["ADT", "Apalutamida"], ["rash", "hipotiroidismo", "caidas", "fracturas"], ["convulsiones previas", "rash severo", "alto riesgo de fractura sin soporte"], "https://pubmed.ncbi.nlm.nih.gov/29420164/", 2018),
    _m0_profile("PROSPER", "ADT_ENZALUTAMIDE", "ADT + enzalutamida", ["ADT", "Enzalutamida"], ["fatiga", "hipertension", "caidas", "eventos cognitivos"], ["convulsiones previas", "alto riesgo de caidas", "deterioro cognitivo severo"], "https://pubmed.ncbi.nlm.nih.gov/29420163/", 2018),
    _m0_profile("ARAMIS", "ADT_DAROLUTAMIDE", "ADT + darolutamida", ["ADT", "Darolutamida"], ["fatiga", "dolor musculoesqueletico", "rash"], ["interacciones no revisadas", "deterioro hepatico severo"], "https://pubmed.ncbi.nlm.nih.gov/30763142/", 2019),
])


def _mcrpc_payload(**overrides: Any) -> dict[str, Any]:
    base = _patient(
        state="m1_crpc",
        psa=38,
        psa_current=38,
        metastasis_status="M1",
        metastasis_site="Bone",
        metastasis_count=5,
        castration_resistant=True,
        testosterone_current=14,
        line_of_therapy_context="mCRPC_first_line",
        hrr_status="Negativo",
        brca_status="Negativo",
    )
    base.update(overrides)
    return base


def _mcrpc_profile(
    name: str,
    *,
    aliases: list[str],
    regimen_code: str,
    regimen_label: str,
    agents: list[str],
    intervention: str,
    control: str,
    endpoint: str,
    key_result: str,
    population: str,
    criteria: dict[str, Any],
    required_inputs: list[str],
    adverse_events: list[str],
    contraindications: list[str],
    payload: dict[str, Any],
    source: str,
    year: int,
    line_context: str = "mCRPC_first_line",
) -> dict[str, Any]:
    return _profile(
        name,
        aliases=aliases,
        scenario="mCRPC",
        disease_state="mCRPC",
        module_id="m1_crpc",
        line_context=line_context,
        regimen_code=regimen_code,
        regimen_label=regimen_label,
        agents=agents,
        intervention=intervention,
        control=control,
        endpoint=endpoint,
        key_result=key_result,
        population=population,
        criteria=criteria,
        required_inputs=required_inputs,
        adverse_events=adverse_events,
        contraindications=contraindications,
        clinical_gap_reason="mCRPC requiere confirmar castracion, linea previa, biomarcadores y seguridad especifica antes de cerrar la conducta.",
        flagship_payload=payload,
        sources=[_source(name, source)],
        year=year,
        nccn_category="1",
    )


_MCRPC_BASE = {"age_min": 18, "age_max": 90, "psa_min": 0, "psa_max": 99999, "gleason_min": 6, "gleason_max": 10, "ecog_max": 2, "metastasis": "M1", "castration_resistant": True}

PIVOTAL_STUDY_CATALOG.extend([
    _mcrpc_profile("TAX-327", aliases=["TAX 327", "TAX327"], regimen_code="DOCETAXEL", regimen_label="Docetaxel + prednisona", agents=["Docetaxel", "Prednisona"], intervention="Docetaxel cada 3 semanas + prednisona.", control="Mitoxantrona + prednisona.", endpoint="Supervivencia global.", key_result="Establece docetaxel como quimioterapia de referencia en mCRPC sintomatico apto.", population="mCRPC sintomatico o progresivo, apto para taxano.", criteria={**_MCRPC_BASE, "fit_for_chemotherapy": True}, required_inputs=["ecog_score", "anc", "platelets", "peripheral_neuropathy_grade", "child_pugh_score"], adverse_events=["neutropenia", "neuropatia", "fatiga", "infeccion"], contraindications=["neuropatia grado >=2", "neutropenia", "plaquetopenia", "ECOG alto"], payload=_mcrpc_payload(prior_therapy=[], fit_for_chemotherapy=True, anc=2500, platelets=215000), source="https://pubmed.ncbi.nlm.nih.gov/15034500/", year=2004),
    _mcrpc_profile("TROPIC", aliases=["TROPIC trial"], regimen_code="CABAZITAXEL", regimen_label="Cabazitaxel + prednisona", agents=["Cabazitaxel", "Prednisona"], intervention="Cabazitaxel + prednisona.", control="Mitoxantrona + prednisona.", endpoint="Supervivencia global.", key_result="Soporta cabazitaxel post-docetaxel en mCRPC con reserva medular.", population="mCRPC progresado a docetaxel.", criteria={**_MCRPC_BASE, "prior_docetaxel": True, "fit_for_chemotherapy": True}, required_inputs=["prior_therapy", "anc", "platelets", "peripheral_neuropathy_grade"], adverse_events=["neutropenia febril", "diarrea", "fatiga", "neuropatia"], contraindications=["neutropenia", "hipersensibilidad a taxanos", "neuropatia severa"], payload=_mcrpc_payload(prior_therapy=["Docetaxel"], fit_for_chemotherapy=True, anc=2300, platelets=190000, line_of_therapy_context="mCRPC_post_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/20888992/", year=2010, line_context="mCRPC_post_taxane"),
    _mcrpc_profile("CARD", aliases=["CARD trial"], regimen_code="CABAZITAXEL", regimen_label="Cabazitaxel + prednisona", agents=["Cabazitaxel", "Prednisona"], intervention="Cabazitaxel frente a cambio a ARPI alternativo.", control="Abiraterona o enzalutamida alternativa.", endpoint="rPFS y OS.", key_result="Prioriza cabazitaxel sobre reciclaje ARPI tras docetaxel y progresion temprana a ARPI.", population="mCRPC post-docetaxel y post-ARPI.", criteria={**_MCRPC_BASE, "prior_docetaxel": True, "prior_arpi": True, "fit_for_chemotherapy": True}, required_inputs=["prior_therapy", "prior_arpi_duration_months", "anc", "platelets"], adverse_events=["neutropenia", "diarrea", "fatiga"], contraindications=["neutropenia", "ECOG alto", "hipersensibilidad a taxanos"], payload=_mcrpc_payload(prior_therapy=["Docetaxel", "Enzalutamida", "ARPI"], prior_arpi_duration_months=8, fit_for_chemotherapy=True, anc=2300, platelets=190000, line_of_therapy_context="mCRPC_post_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/31566937/", year=2019, line_context="mCRPC_post_taxane"),
    _mcrpc_profile("COU-AA-301", aliases=["COU AA 301", "COU-AA301"], regimen_code="ADT_ABIRATERONE", regimen_label="Abiraterona + prednisona", agents=["Abiraterona", "Prednisona", "ADT"], intervention="Abiraterona/prednisona post-docetaxel.", control="Placebo + prednisona.", endpoint="Supervivencia global.", key_result="Abiraterona mejora OS en mCRPC post-docetaxel si no hay bloqueo hepatocardiaco.", population="mCRPC post-docetaxel.", criteria={**_MCRPC_BASE, "prior_docetaxel": True}, required_inputs=["prior_therapy", "child_pugh_score", "cv_risk_documented", "potassium"], adverse_events=["hipertension", "hipokalemia", "edema", "hepatotoxicidad"], contraindications=["Child-Pugh B/C", "hipertension no controlada", "hipokalemia"], payload=_mcrpc_payload(prior_therapy=["Docetaxel"], child_pugh_score="A", potassium=4.1, line_of_therapy_context="mCRPC_post_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/21612468/", year=2011, line_context="mCRPC_post_taxane"),
    _mcrpc_profile("COU-AA-302", aliases=["COU AA 302", "COU-AA302"], regimen_code="ADT_ABIRATERONE", regimen_label="Abiraterona + prednisona", agents=["Abiraterona", "Prednisona", "ADT"], intervention="Abiraterona/prednisona pre-quimioterapia.", control="Placebo + prednisona.", endpoint="rPFS y OS.", key_result="Soporta abiraterona en mCRPC quimio-naive asintomatico o minimamente sintomatico.", population="mCRPC sin quimioterapia previa, asintomatico o con sintomas leves.", criteria={**_MCRPC_BASE, "no_prior_docetaxel": True}, required_inputs=["prior_therapy", "pain_symptoms", "child_pugh_score", "cv_risk_documented"], adverse_events=["hipertension", "hipokalemia", "edema", "hepatotoxicidad"], contraindications=["Child-Pugh B/C", "hipertension no controlada", "insuficiencia cardiaca avanzada"], payload=_mcrpc_payload(prior_therapy=[], pain_symptoms="Leve", child_pugh_score="A"), source="https://pubmed.ncbi.nlm.nih.gov/23228172/", year=2012),
    _mcrpc_profile("AFFIRM", aliases=["AFFIRM trial"], regimen_code="ADT_ENZALUTAMIDE", regimen_label="Enzalutamida", agents=["Enzalutamida", "ADT"], intervention="Enzalutamida post-docetaxel.", control="Placebo.", endpoint="Supervivencia global.", key_result="Enzalutamida mejora OS post-docetaxel en mCRPC.", population="mCRPC post-docetaxel sin contraindicacion neurologica.", criteria={**_MCRPC_BASE, "prior_docetaxel": True}, required_inputs=["prior_therapy", "seizure_history", "fall_risk", "drug_interaction_reviewed"], adverse_events=["fatiga", "hipertension", "caidas", "convulsiones raras"], contraindications=["convulsiones previas", "alto riesgo de caidas"], payload=_mcrpc_payload(prior_therapy=["Docetaxel"], seizure_history=0, fall_risk="low", line_of_therapy_context="mCRPC_post_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/22894553/", year=2012, line_context="mCRPC_post_taxane"),
    _mcrpc_profile("PREVAIL", aliases=["PREVAIL trial"], regimen_code="ADT_ENZALUTAMIDE", regimen_label="Enzalutamida", agents=["Enzalutamida", "ADT"], intervention="Enzalutamida pre-quimioterapia.", control="Placebo.", endpoint="rPFS y OS.", key_result="Soporta enzalutamida en mCRPC quimio-naive.", population="mCRPC sin quimioterapia previa, asintomatico o minimamente sintomatico.", criteria={**_MCRPC_BASE, "no_prior_docetaxel": True}, required_inputs=["prior_therapy", "pain_symptoms", "seizure_history", "fall_risk"], adverse_events=["fatiga", "hipertension", "caidas", "eventos cognitivos"], contraindications=["convulsiones previas", "alto riesgo de caidas"], payload=_mcrpc_payload(prior_therapy=[], pain_symptoms="Leve", seizure_history=0, fall_risk="low"), source="https://pubmed.ncbi.nlm.nih.gov/24881730/", year=2014),
    _mcrpc_profile("ALSYMPCA", aliases=["ALSYMPCA trial"], regimen_code="RADIUM223", regimen_label="Radio-223", agents=["Radio-223"], intervention="Radio-223 por 6 ciclos.", control="Placebo + mejor soporte.", endpoint="Supervivencia global.", key_result="Opcion para metastasis oseas sintomaticas sin visceralidad, con proteccion osea.", population="mCRPC con metastasis oseas sintomaticas, sin metastasis viscerales.", criteria={**_MCRPC_BASE, "bone_metastases": True, "visceral_metastases": False, "symptomatic_bone": True}, required_inputs=["bone_metastases", "visceral_metastases", "symptomatic_bone", "hemoglobin", "platelets", "bone_modifying_agent"], adverse_events=["mielosupresion", "nausea", "diarrea", "fracturas si no hay soporte oseo"], contraindications=["metastasis viscerales", "mielosupresion", "ausencia de enfermedad osea sintomatica"], payload=_mcrpc_payload(bone_metastases=True, symptomatic_bone=True, visceral_metastases=False, hemoglobin=12.1, platelets=190000, bone_modifying_agent="denosumab"), source="https://pubmed.ncbi.nlm.nih.gov/23863050/", year=2013, line_context="mCRPC_bone_predominant"),
    _mcrpc_profile("VISION", aliases=["VISION trial"], regimen_code="LU177_PSMA617", regimen_label="Lu-177-PSMA-617", agents=["Lu-177-PSMA-617"], intervention="Lu-177-PSMA-617 + estandar de cuidado.", control="Estandar de cuidado.", endpoint="rPFS y OS.", key_result="Radioligando para mCRPC PSMA+ post-ARPI y taxano, sin lesiones dominantes PSMA-negativas.", population="mCRPC PSMA+ con exposicion previa a ARPI y taxano.", criteria={**_MCRPC_BASE, "prior_arpi": True, "prior_docetaxel": True, "psma_pet_positive": True}, required_inputs=["psma_pet_result", "psma_negative_dominant_lesions", "prior_therapy", "hemoglobin", "renal_function"], adverse_events=["xerostomia", "nausea", "fatiga", "mielosupresion", "toxicidad renal"], contraindications=["PSMA negativo", "lesiones dominantes PSMA-negativas", "mielosupresion", "deterioro renal severo"], payload=_mcrpc_payload(prior_therapy=["Enzalutamida", "ARPI", "Docetaxel"], psma_pet_result="Positivo", psma_negative_dominant_lesions=False, hemoglobin=11.8, renal_function="adequate", line_of_therapy_context="mCRPC_post_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/34161051/", year=2021, line_context="mCRPC_post_taxane"),
    _mcrpc_profile("PSMAfore", aliases=["PSMAFORE", "PSMA fore"], regimen_code="LU177_PSMA617", regimen_label="Lu-177-PSMA-617 pre-taxano", agents=["Lu-177-PSMA-617"], intervention="Lu-177-PSMA-617 post-ARPI pre-taxano.", control="Cambio de ARPI.", endpoint="rPFS.", key_result="Adelanta radioligando en mCRPC PSMA+ tras ARPI y antes de taxano cuando la seleccion por PET es adecuada.", population="mCRPC PSMA+, post-ARPI, taxane-naive.", criteria={**_MCRPC_BASE, "prior_arpi": True, "no_prior_docetaxel": True, "psma_pet_positive": True}, required_inputs=["psma_pet_result", "psma_negative_dominant_lesions", "prior_therapy", "taxane_fit_or_deferral_reason"], adverse_events=["xerostomia", "nausea", "fatiga", "mielosupresion"], contraindications=["PSMA negativo", "lesiones dominantes PSMA-negativas", "mielosupresion"], payload=_mcrpc_payload(prior_therapy=["Abiraterona", "ARPI"], psma_pet_result="Positivo", psma_negative_dominant_lesions=False, taxane_fit_or_deferral_reason="pre_taxane_trial", line_of_therapy_context="mCRPC_post_ARPI_pre_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/?term=PSMAfore+lutetium+177+prostate+cancer", year=2024, line_context="mCRPC_post_ARPI_pre_taxane"),
    _mcrpc_profile("TheraP", aliases=["THERAP", "TheraP trial"], regimen_code="LU177_PSMA617", regimen_label="Lu-177-PSMA-617 vs cabazitaxel", agents=["Lu-177-PSMA-617", "Cabazitaxel"], intervention="Lu-177-PSMA-617.", control="Cabazitaxel.", endpoint="Respuesta de PSA >=50%.", key_result="Ensayo comparativo con seleccion PSMA/FDG estricta; no debe fusionarse con VISION.", population="mCRPC PSMA+ post-docetaxel candidato a cabazitaxel.", criteria={**_MCRPC_BASE, "prior_docetaxel": True, "psma_pet_positive": True}, required_inputs=["psma_pet_result", "fdg_discordant_disease", "prior_therapy", "fit_for_chemotherapy"], adverse_events=["xerostomia", "mielosupresion", "fatiga", "toxicidad por taxano si se elige control"], contraindications=["PSMA negativo", "enfermedad FDG discordante", "mielosupresion"], payload=_mcrpc_payload(prior_therapy=["Docetaxel"], psma_pet_result="Positivo", fdg_discordant_disease=False, fit_for_chemotherapy=True, line_of_therapy_context="mCRPC_post_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/33581798/", year=2021, line_context="mCRPC_post_taxane"),
    _mcrpc_profile("PEACE-3", aliases=["EORTC 1333", "PEACE3"], regimen_code="ENZALUTAMIDE_RADIUM223", regimen_label="Enzalutamida + radio-223", agents=["Enzalutamida", "Radio-223", "ADT"], intervention="Enzalutamida + radio-223 con agente oseo mandatorio.", control="Enzalutamida.", endpoint="rPFS.", key_result="Combinacion en mCRPC con metastasis oseas; exige agente modificador oseo para mitigar fracturas.", population="mCRPC con metastasis oseas, sin visceralidad dominante y candidato a enzalutamida/radio-223.", criteria={**_MCRPC_BASE, "bone_metastases": True, "visceral_metastases": False, "symptomatic_bone": True}, required_inputs=["bone_metastases", "visceral_metastases", "bone_modifying_agent", "seizure_history", "hemoglobin", "platelets"], adverse_events=["fracturas", "mielosupresion", "fatiga", "hipertension"], contraindications=["sin agente oseo", "metastasis viscerales", "mielosupresion", "convulsiones previas"], payload=_mcrpc_payload(bone_metastases=True, symptomatic_bone=True, visceral_metastases=False, bone_modifying_agent="zoledronic_acid", seizure_history=0, hemoglobin=12.3, platelets=200000), source="https://pubmed.ncbi.nlm.nih.gov/40450503/", year=2025, line_context="mCRPC_bone_predominant"),
    _mcrpc_profile("PROfound", aliases=["PROFOUND"], regimen_code="OLAPARIB", regimen_label="Olaparib", agents=["Olaparib"], intervention="Olaparib.", control="ARPI alternativo.", endpoint="rPFS.", key_result="PARP post-ARPI en mCRPC con alteracion HRR trazable.", population="mCRPC HRR+ progresado a ARPI.", criteria={**_MCRPC_BASE, "prior_arpi": True, "hrr_positive": True}, required_inputs=["hrr_status", "biomarker_source", "hemoglobin", "platelets", "renal_function"], adverse_events=["anemia", "fatiga", "nausea", "trombocitopenia", "neutropenia"], contraindications=["HRR no documentado", "mielosupresion", "MDS/AML previo", "deterioro renal severo"], payload=_mcrpc_payload(prior_therapy=["Abiraterona", "ARPI"], hrr_status="Positivo", brca_status="BRCA2", biomarker_source="somatic_panel", hemoglobin=12.6, platelets=200000, renal_function="adequate", line_of_therapy_context="mCRPC_post_ARPI_pre_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/32343890/", year=2020, line_context="mCRPC_post_ARPI_pre_taxane"),
    _mcrpc_profile("PROpel", aliases=["PROPEL"], regimen_code="OLAPARIB_ABIRATERONE", regimen_label="Olaparib + abiraterona/prednisona", agents=["Olaparib", "Abiraterona", "Prednisona"], intervention="Olaparib + abiraterona/prednisona.", control="Abiraterona/prednisona.", endpoint="rPFS.", key_result="Combinacion de PARP + ARSI en primera linea mCRPC; requiere seguridad hematologica y hepatocardiovascular.", population="mCRPC primera linea, especialmente con biomarcador HRR/BRCA documentado segun politica local.", criteria={**_MCRPC_BASE, "no_prior_docetaxel": True}, required_inputs=["hrr_status", "hemoglobin", "platelets", "child_pugh_score", "cv_risk_documented"], adverse_events=["anemia", "fatiga", "nausea", "hipertension", "hipokalemia"], contraindications=["mielosupresion", "Child-Pugh B/C", "hipertension no controlada"], payload=_mcrpc_payload(prior_therapy=[], hrr_status="Positivo", brca_status="BRCA2", hemoglobin=12.4, platelets=210000, child_pugh_score="A"), source="https://pubmed.ncbi.nlm.nih.gov/36227348/", year=2022),
    _mcrpc_profile("MAGNITUDE", aliases=["MAGNITUDE trial"], regimen_code="NIRAPARIB_ABIRATERONE", regimen_label="Niraparib + abiraterona/prednisona", agents=["Niraparib", "Abiraterona", "Prednisona"], intervention="Niraparib + abiraterona/prednisona.", control="Abiraterona/prednisona.", endpoint="rPFS.", key_result="Beneficio concentrado en HRR/BRCA; no extrapolar a HRR negativo.", population="mCRPC primera linea con alteracion HRR, particularmente BRCA.", criteria={**_MCRPC_BASE, "hrr_positive": True, "no_prior_docetaxel": True}, required_inputs=["hrr_status", "biomarker_source", "hemoglobin", "platelets", "child_pugh_score"], adverse_events=["anemia", "trombocitopenia", "hipertension", "fatiga"], contraindications=["HRR no documentado", "mielosupresion", "Child-Pugh B/C"], payload=_mcrpc_payload(prior_therapy=[], hrr_status="Positivo", brca_status="BRCA2", biomarker_source="germline_panel", hemoglobin=12.7, platelets=220000), source="https://pubmed.ncbi.nlm.nih.gov/36990608/", year=2023),
    _mcrpc_profile("TALAPRO-2", aliases=["TALAPRO2"], regimen_code="TALAZOPARIB_ENZALUTAMIDE", regimen_label="Talazoparib + enzalutamida", agents=["Talazoparib", "Enzalutamida"], intervention="Talazoparib + enzalutamida.", control="Enzalutamida.", endpoint="rPFS.", key_result="PARP + enzalutamida en primera linea mCRPC, con mayor relevancia si HRR/BRCA positivo.", population="mCRPC primera linea con perfil molecular y seguridad hematologica disponibles.", criteria={**_MCRPC_BASE, "no_prior_docetaxel": True}, required_inputs=["hrr_status", "hemoglobin", "platelets", "seizure_history", "fall_risk"], adverse_events=["anemia", "neutropenia", "fatiga", "hipertension", "caidas"], contraindications=["mielosupresion", "convulsiones previas", "alto riesgo de caidas"], payload=_mcrpc_payload(prior_therapy=[], hrr_status="Positivo", brca_status="BRCA2", hemoglobin=12.2, platelets=205000, seizure_history=0, fall_risk="low"), source="https://pubmed.ncbi.nlm.nih.gov/37171034/", year=2023),
    _mcrpc_profile("TRITON-3", aliases=["TRITON3"], regimen_code="RUCAPARIB", regimen_label="Rucaparib", agents=["Rucaparib"], intervention="Rucaparib.", control="Docetaxel o ARPI segun eleccion del investigador.", endpoint="rPFS.", key_result="Rucaparib para mCRPC BRCA+ despues de ARPI, con vigilancia hematologica/hepatica.", population="mCRPC con BRCA1/2 alterado tras ARPI.", criteria={**_MCRPC_BASE, "prior_arpi": True, "hrr_positive": True}, required_inputs=["brca_status", "biomarker_source", "hemoglobin", "platelets", "liver_panel_date"], adverse_events=["anemia", "fatiga", "nausea", "elevacion transaminasas"], contraindications=["BRCA no documentado", "mielosupresion", "hepatotoxicidad significativa"], payload=_mcrpc_payload(prior_therapy=["Enzalutamida", "ARPI"], hrr_status="Positivo", brca_status="BRCA2", biomarker_source="somatic_panel", hemoglobin=12.5, platelets=210000, liver_panel_date="2026-03-20", line_of_therapy_context="mCRPC_post_ARPI_pre_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/36990613/", year=2023, line_context="mCRPC_post_ARPI_pre_taxane"),
    _mcrpc_profile("IMPACT", aliases=["Sipuleucel-T IMPACT"], regimen_code="SIPULEUCEL_T", regimen_label="Sipuleucel-T", agents=["Sipuleucel-T"], intervention="Sipuleucel-T.", control="Placebo/apheresis control.", endpoint="Supervivencia global.", key_result="Inmunoterapia celular para mCRPC asintomatico o minimamente sintomatico, sin visceralidad dominante.", population="mCRPC asintomatico/minimamente sintomatico, ECOG bueno, sin inmunosupresion relevante.", criteria={**_MCRPC_BASE, "no_prior_docetaxel": True, "visceral_metastases": False}, required_inputs=["pain_symptoms", "visceral_metastases", "ecog_score", "immunosuppression", "life_expectancy_months"], adverse_events=["escalofrios", "fiebre", "fatiga", "reacciones infusion"], contraindications=["enfermedad sintomatica rapida", "metastasis viscerales dominantes", "inmunosupresion significativa"], payload=_mcrpc_payload(prior_therapy=[], pain_symptoms="Ninguno", visceral_metastases=False, immunosuppression=False, life_expectancy_months=18), source="https://pubmed.ncbi.nlm.nih.gov/20818862/", year=2010),
    _mcrpc_profile("IPATential150", aliases=["IPATENTIAL150", "IPATential 150"], regimen_code="IPATASERTIB_ABIRATERONE", regimen_label="Ipatasertib + abiraterona/prednisona", agents=["Ipatasertib", "Abiraterona", "Prednisona"], intervention="Ipatasertib + abiraterona/prednisona.", control="Abiraterona/prednisona.", endpoint="rPFS.", key_result="AKT + abiraterona en mCRPC con perdida PTEN; seguridad metabolica y gastrointestinal decisiva.", population="mCRPC primera linea con perdida PTEN por IHQ/NGS.", criteria={**_MCRPC_BASE, "pten_loss": True, "no_prior_docetaxel": True}, required_inputs=["pten_status", "glucose_control", "child_pugh_score", "diarrhea_baseline"], adverse_events=["diarrea", "rash", "hiperglucemia", "hepatotoxicidad"], contraindications=["diabetes no controlada", "diarrea severa basal", "Child-Pugh B/C"], payload=_mcrpc_payload(prior_therapy=[], pten_status="loss", pten_loss=True, glucose_control="controlled", diarrhea_baseline="none", child_pugh_score="A"), source="https://pubmed.ncbi.nlm.nih.gov/32888431/", year=2020),
    _mcrpc_profile("CONTACT-02", aliases=["CONTACT02", "CONTACT 02"], regimen_code="CABOZANTINIB_ATEZOLIZUMAB", regimen_label="Cabozantinib + atezolizumab", agents=["Cabozantinib", "Atezolizumab"], intervention="Cabozantinib + atezolizumab.", control="Segundo ARPI.", endpoint="rPFS y OS.", key_result="Opcion investigacional/condicionada para mCRPC post-ARPI con metastasis de partes blandas extrapelvicas; seguridad inmune y vascular es critica.", population="mCRPC post-ARPI con enfermedad medible de partes blandas extrapelvicas.", criteria={**_MCRPC_BASE, "prior_arpi": True, "soft_tissue_metastases": True}, required_inputs=["prior_therapy", "soft_tissue_metastases", "autoimmune_disease", "bleeding_risk", "blood_pressure_control"], adverse_events=["hipertension", "diarrea", "fatiga", "eventos inmunes", "sangrado", "tromboembolismo"], contraindications=["enfermedad autoinmune activa", "sangrado activo", "hipertension no controlada", "uso alto de esteroides"], payload=_mcrpc_payload(prior_therapy=["Enzalutamida", "ARPI"], soft_tissue_metastases=True, metastasis_site="Visceral", visceral_metastases=True, autoimmune_disease=False, bleeding_risk="low", blood_pressure_control="controlled", line_of_therapy_context="mCRPC_post_ARPI_pre_taxane"), source="https://pubmed.ncbi.nlm.nih.gov/40523369/", year=2025, line_context="mCRPC_post_ARPI_pre_taxane"),
])


_ALIAS_INDEX: dict[str, dict[str, Any]] = {}
for _profile_item in PIVOTAL_STUDY_CATALOG:
    for _alias in [_profile_item["canonical_name"], *_profile_item.get("aliases", [])]:
        _ALIAS_INDEX[normalize_study_name(_alias)] = _profile_item


def get_pivotal_profile(study_name: Any) -> dict[str, Any] | None:
    profile = _ALIAS_INDEX.get(normalize_study_name(study_name))
    return deepcopy(profile) if profile else None


def iter_requested_pivotal_profiles() -> list[dict[str, Any]]:
    return [deepcopy(item) for item in PIVOTAL_STUDY_CATALOG]


def _legacy_record(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": profile["canonical_name"],
        "phase": profile.get("phase", "III"),
        "scenario": profile["scenario"],
        "intervention": profile["intervention"],
        "control": profile["control"],
        "primary_endpoint": profile["primary_endpoint"],
        "key_result": profile["key_result"],
        "population": profile["population"],
        "eligibility_criteria": deepcopy(profile.get("eligibility_criteria", {})),
        "mexican_applicability": profile.get("mexican_applicability", ""),
        "nccn_category": profile.get("nccn_category", "evidence_context"),
        "year": profile.get("year", 0),
    }


def _merge_profile_metadata(study: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(study)
    merged.setdefault("aliases", [])
    aliases = list(dict.fromkeys([*merged.get("aliases", []), *profile.get("aliases", [])]))
    merged["aliases"] = aliases
    for key in (
        "study_key",
        "disease_state",
        "module_id",
        "line_of_therapy_context",
        "regimen_code",
        "regimen_label",
        "agents",
        "required_inputs",
        "adverse_event_watchlist",
        "contraindication_flags",
        "clinical_gap_reason",
        "flagship_patient",
        "source_citations",
    ):
        merged[key] = deepcopy(profile.get(key))
    # Preserve mature legacy text when already present, but fill missing fields for new coverage.
    merged.setdefault("control", profile.get("control", ""))
    merged.setdefault("primary_endpoint", profile.get("primary_endpoint", ""))
    merged.setdefault("key_result", profile.get("key_result", ""))
    merged.setdefault("population", profile.get("population", ""))
    return merged


def enhance_legacy_pivotal_studies(studies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enhanced: list[dict[str, Any]] = []
    seen: set[str] = set()
    for study in studies:
        profile = get_pivotal_profile(study.get("name"))
        if profile:
            enhanced.append(_merge_profile_metadata(study, profile))
            seen.add(profile["study_key"])
        else:
            enhanced.append(deepcopy(study))
            seen.add(normalize_study_name(study.get("name")))
    for profile in PIVOTAL_STUDY_CATALOG:
        if profile["study_key"] not in seen:
            enhanced.append(_merge_profile_metadata(_legacy_record(profile), profile))
            seen.add(profile["study_key"])
    return enhanced


def build_pivotal_alias_index(studies: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for study in studies:
        names = [study.get("name"), *study.get("aliases", [])]
        for name in names:
            if name:
                index[normalize_study_name(name)] = study
    return index


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or str(value).strip().lower() in {"unknown", "desconocido", "no realizado", "not_done"}


def missing_required_inputs(profile: dict[str, Any], patient_data: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in profile.get("required_inputs", []):
        if _is_missing(patient_data.get(field)):
            missing.append(field)
    return missing


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "si", "sí", "yes", "positive", "positivo", "loss"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def derive_contraindication_flags(profile: dict[str, Any], patient_data: dict[str, Any]) -> list[dict[str, str]]:
    agents = {str(agent).lower() for agent in profile.get("agents", [])}
    flags: list[dict[str, str]] = []

    def add(severity: str, label: str, reason: str) -> None:
        flags.append({"severity": severity, "label": label, "reason": reason})

    if {"docetaxel", "cabazitaxel"} & agents:
        if _num(patient_data.get("peripheral_neuropathy_grade")) >= 2:
            add("hard_stop", "Neuropatia periferica", "Taxano no seguro con neuropatia grado >=2.")
        if patient_data.get("anc") not in (None, "") and _num(patient_data.get("anc")) < 1500:
            add("hard_stop", "Neutropenia", "Taxano requiere reserva neutrofilica adecuada.")
        if patient_data.get("platelets") not in (None, "") and _num(patient_data.get("platelets")) < 100000:
            add("hard_stop", "Plaquetopenia", "Taxano requiere plaquetas adecuadas.")
        if _num(patient_data.get("ecog_score")) >= 3:
            add("hard_stop", "ECOG alto", "Quimioterapia no debe liderar con ECOG >=3.")

    if "abiraterona" in agents or "abiraterone" in agents:
        if str(patient_data.get("child_pugh_score", "A")).upper() in {"B", "C"}:
            add("hard_stop", "Riesgo hepatico", "Abiraterona no debe liderar con Child-Pugh B/C.")
        if _truthy(patient_data.get("uncontrolled_hypertension")) or str(patient_data.get("blood_pressure_control", "controlled")).lower() == "uncontrolled":
            add("hard_stop", "Hipertension no controlada", "Corregir presion arterial antes de abiraterona.")
        if patient_data.get("potassium") not in (None, "") and _num(patient_data.get("potassium")) < 3.5:
            add("hard_stop", "Hipokalemia", "Corregir potasio antes de abiraterona.")

    if {"enzalutamida", "enzalutamide", "apalutamida", "apalutamide"} & agents:
        if _truthy(patient_data.get("seizure_history")):
            add("hard_stop", "Antecedente convulsivo", "ARPI con penetrancia SNC requiere evitarse o discutir alternativa.")
        if str(patient_data.get("fall_risk", "low")).lower() in {"high", "alto"}:
            add("caution", "Riesgo de caidas", "Aumenta riesgo funcional con ARPI; considerar darolutamida u otra estrategia.")

    if "darolutamida" in agents or "darolutamide" in agents:
        if str(patient_data.get("drug_interaction_reviewed", "1")).lower() in {"0", "false", "no"}:
            add("caution", "Interacciones pendientes", "Darolutamida requiere revision de interacciones y funcion organica.")

    if {"olaparib", "niraparib", "talazoparib", "rucaparib"} & agents:
        if patient_data.get("hemoglobin") not in (None, "") and _num(patient_data.get("hemoglobin")) < 10:
            add("hard_stop", "Anemia basal", "PARP requiere reserva hematologica adecuada.")
        if patient_data.get("platelets") not in (None, "") and _num(patient_data.get("platelets")) < 100000:
            add("hard_stop", "Plaquetopenia", "PARP puede agravar mielosupresion.")
        if _truthy(patient_data.get("prior_mds_aml")):
            add("hard_stop", "MDS/AML previo", "Evitar PARP sin revision hematologica especializada.")

    if "lu-177-psma-617" in agents or "lu177-psma-617" in agents:
        if str(patient_data.get("psma_pet_result", "")).lower() not in {"positivo", "positive"}:
            add("hard_stop", "PSMA no positivo", "Radioligando exige PET PSMA positivo.")
        if _truthy(patient_data.get("psma_negative_dominant_lesions")) or _truthy(patient_data.get("fdg_discordant_disease")):
            add("hard_stop", "Discordancia PSMA/FDG", "Lesiones dominantes no PSMA positivas bloquean radioligando.")

    if "radio-223" in agents or "radium-223" in agents:
        if _truthy(patient_data.get("visceral_metastases")):
            add("hard_stop", "Metastasis visceral", "Radio-223 no corresponde con visceralidad dominante.")
        if str(patient_data.get("bone_modifying_agent", "")).strip() == "":
            add("caution", "Soporte oseo pendiente", "Combinaciones con radio-223 requieren denosumab o zoledronato salvo contraindicacion.")

    if "sipuleucel-t" in agents:
        if str(patient_data.get("pain_symptoms", "")).lower() not in {"ninguno", "none", "leve", "mild"}:
            add("hard_stop", "Sintomas avanzados", "Sipuleucel-T aplica mejor en enfermedad asintomatica o minimamente sintomatica.")
        if _truthy(patient_data.get("immunosuppression")):
            add("hard_stop", "Inmunosupresion", "Inmunoterapia celular requiere revisar inmunosupresion.")

    if "atezolizumab" in agents:
        if _truthy(patient_data.get("autoimmune_disease")):
            add("hard_stop", "Autoinmunidad activa", "Checkpoint inhibitor requiere evitarse o discusion especializada.")
        if str(patient_data.get("blood_pressure_control", "controlled")).lower() == "uncontrolled":
            add("hard_stop", "Hipertension no controlada", "Cabozantinib requiere control vascular previo.")
        if str(patient_data.get("bleeding_risk", "low")).lower() in {"high", "alto"}:
            add("hard_stop", "Riesgo de sangrado", "Cabozantinib no debe liderar con sangrado activo o alto riesgo.")

    if "ipatasertib" in agents:
        if str(patient_data.get("glucose_control", "controlled")).lower() == "uncontrolled":
            add("hard_stop", "Hiperglucemia/diabetes", "AKT requiere control metabolico antes de iniciar.")
        if str(patient_data.get("diarrhea_baseline", "none")).lower() in {"severe", "severa"}:
            add("hard_stop", "Diarrea basal severa", "AKT puede agravar diarrea.")

    return flags


def build_flagship_patient_suite() -> list[dict[str, Any]]:
    suite: list[dict[str, Any]] = []
    for profile in PIVOTAL_STUDY_CATALOG:
        suite.append(
            {
                "study_name": profile["canonical_name"],
                "study_key": profile["study_key"],
                "payload": deepcopy(profile["flagship_patient"]["payload"]),
                "expected": deepcopy(profile["flagship_patient"]["expected"]),
                "required_inputs": list(profile.get("required_inputs", [])),
                "adverse_event_watchlist": list(profile.get("adverse_event_watchlist", [])),
                "contraindication_flags": list(profile.get("contraindication_flags", [])),
            }
        )
    return suite
