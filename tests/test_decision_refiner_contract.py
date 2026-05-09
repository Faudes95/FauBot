from __future__ import annotations

from datetime import date


SYSTEMIC_MODULES = [
    "m0_crpc",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "m1_crpc",
]


def _today() -> str:
    return date.today().isoformat()


def _docetaxel_labs() -> dict:
    return {
        "cbc_date": _today(),
        "anc": 2600,
        "platelets": 225000,
        "hemoglobin": 13.1,
        "liver_panel_date": _today(),
        "bilirubin": 0.8,
        "ast": 24,
        "alt": 22,
        "alp": 96,
        "taxane_hypersensitivity_history": "0",
        "polysorbate_hypersensitivity": "0",
        "strong_cyp3a_inhibitor": "0",
        "egfr": 82,
    }


def _arpi_safety() -> dict:
    return {
        "comorbidity_seizure": "0",
        "stroke_history": "0",
        "cognitive_risk": "0",
        "fall_risk": "0",
        "current_medications": "enalapril",
        "drug_interaction_reviewed": "1",
        "comorbidity_cardio": "0",
        "cv_risk_documented": "0",
        "child_pugh_score": "A",
        "hepatic_risk_factors": "0",
        "liver_panel_date": _today(),
        "bilirubin": 0.8,
        "ast": 24,
        "alt": 22,
        "dermatitis_history": "0",
        "baseline_bp": 128,
        "edema_risk": "0",
        "potassium": 4.2,
        "diabetes_uncontrolled": "0",
        "steroid_intolerance": "0",
        "glucose_or_hba1c": 102,
        "baseline_weight": 78,
        "fatigue_baseline": 2,
        "neurocognitive_baseline": 28,
        "fall_history_recent": "0",
        "baseline_qol": 78,
    }


def _metastatic_capture() -> dict:
    return {
        "metastatic_components_capture": "bone:7",
        "metastatic_disease_known": "1",
        "metastasis_site": "Bone",
        "metastasis_count": 7,
        "metastatic_total_lesion_count": 7,
        "bone_metastasis_present": "1",
        "bone_site_entries": '[{"site_key":"spine","lesion_count":7}]',
        "visceral_metastasis_present": "0",
        "visceral_site_entries": "[]",
        "nonregional_nodal_metastasis_present": "0",
        "nonregional_nodal_site_entries": "[]",
        "gleason_score": 9,
        "gleason_primary": 4,
        "gleason_secondary": 5,
        "isup_grade": 5,
    }


def _contract(result: dict) -> dict:
    contract = result.get("decision_refiner_contract") or {}
    assert contract, "module response must include decision_refiner_contract"
    return contract


def test_static_decision_refiner_contracts_are_renderable_from_schema(app_client):
    client, _ = app_client

    for module_id in SYSTEMIC_MODULES:
        response = client.get(f"/api/modules/{module_id}/schema")
        assert response.status_code == 200
        schema = response.get_json()["schema"]
        contract = schema.get("decision_refiner_contract") or {}

        assert contract["contract_version"].startswith("systemic_refiner_contract")
        assert contract["ui_contract"]["max_visible_refiners"] == 6
        assert contract["ui_contract"]["unmapped_backend_fields"] == []


def test_m0_arpi_contract_keeps_recommendation_provisional_when_safety_refiners_are_missing(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={
            "psadt_months": 6,
            "castration_resistant": "1",
            "imaging_negative": "1",
            "castrate_testosterone_confirmed": "1",
            "conventional_imaging_modality": "TC + gammagrama óseo",
            "conventional_imaging_date": _today(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    contract = _contract(result)

    assert contract["scenario_family"] == "nmCRPC"
    assert contract["ui_contract"]["provisional_recommendation"] is True
    assert len(contract["ui_contract"]["visible_refiners"]) <= 6
    assert contract["ui_contract"]["missing_renderable_fields"]
    assert contract["ui_contract"]["unmapped_backend_fields"] == []
    assert result["decision_quality"]["confidence_category"] == "provisional"
    assert result["clinical_gap_reason"]


def test_mhspc_contract_compares_doublets_triplets_and_caps_visible_refiners(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            **_metastatic_capture(),
            **_arpi_safety(),
            **_docetaxel_labs(),
            "ecog_score": 1,
            "performance_status_driver": "cancer_related",
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "molecular_assay_source": "ctDNA",
            "molecular_assay_date": _today(),
            "hrr_gene": "Desconocido",
            "brca2_status": "Desconocido",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    contract = _contract(result)
    candidates = set(contract["candidate_treatments"])

    assert "mHSPC" in contract["scenario_family"]
    assert "ADT_DOCETAXEL_ABIRATERONE" in candidates or "ADT_DOCETAXEL_DAROLUTAMIDE" in candidates
    assert "ADT_ABIRATERONE" in candidates or "ADT_DAROLUTAMIDE" in candidates
    assert len(contract["ui_contract"]["visible_refiners"]) <= 6
    assert contract["ui_contract"]["unmapped_backend_fields"] == []
    assert result["preferred_treatment"]["regimen_code"]
    assert result["ranked_treatment_options"]
    assert result["adverse_event_watchlist"]


def test_mcrpc_contract_surfaces_precision_taxane_and_safety_blockers(app_client):
    client, _ = app_client

    payload = {
        **_arpi_safety(),
        **_docetaxel_labs(),
        "hrr_status": "Positivo",
        "hrr_gene": "BRCA2",
        "biomarker_source": "ctDNA",
        "molecular_report_date": _today(),
        "metastasis_site": "Bone",
        "prior_therapy": "abiraterona, docetaxel",
        "prior_docetaxel_cycles": 6,
        "prior_arpi_duration_months": 8,
        "castrate_testosterone_confirmed": "1",
        "mcrpc_line_context": "post_taxane",
        "pain_symptoms": "Sintomatico",
        "ecog_score": 1,
        "frailty_status": "Fit",
        "peripheral_neuropathy_grade": "1",
        "psma_positive": "1",
        "psma_pet_done": "1",
        "psma_negative_dominant_lesions": "0",
        "psma_rads_score": "5",
        "psma_uptake_pattern": "diseminado",
        "soft_tissue_metastases": "0",
        "bone_modifying_agent": "1",
    }
    payload["anc"] = 900

    response = client.post("/api/modules/m1_crpc/evaluate", json=payload)

    assert response.status_code == 200
    result = response.get_json()["result"]
    contract = _contract(result)
    blocked_codes = {item["regimen_code"] for item in contract["blocked_treatments"]}
    flag_fields = {flag["field"] for flag in contract["contraindication_flags"]}

    assert contract["scenario_family"] == "mCRPC"
    assert "OLAPARIB" in contract["candidate_treatments"]
    assert "CABAZITAXEL" in contract["candidate_treatments"]
    assert "CABAZITAXEL" in blocked_codes
    assert "anc" in flag_fields
    assert contract["ui_contract"]["unmapped_backend_fields"] == []
    assert len(contract["ui_contract"]["visible_refiners"]) <= 6
