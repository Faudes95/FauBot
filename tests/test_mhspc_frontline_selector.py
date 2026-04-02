from __future__ import annotations

from datetime import date, timedelta

from prostanet.domains.clinical_validation.trajectory_catalog import build_trajectory_catalog
from prostanet.domains.patient_tracking import mhspc_frontline_reference as mhspc_reference_module
from prostanet.domains.patient_tracking.mhspc_frontline_reference import ensure_mhspc_frontline_reference


def _recent_docetaxel_labs(**overrides):
    payload = {
        "cbc_date": (date.today() - timedelta(days=3)).isoformat(),
        "anc": 2200,
        "platelets": 210000,
        "liver_panel_date": (date.today() - timedelta(days=4)).isoformat(),
        "bilirubin": 0.8,
        "ast": 32,
        "alt": 30,
        "alp": 110,
        "taxane_hypersensitivity_history": 0,
        "polysorbate_hypersensitivity": 0,
    }
    payload.update(overrides)
    return payload


def test_mhspc_frontline_reference_persists_curated_drug_metadata(tmp_path):
    mhspc_reference_module._REFERENCE_CACHE.clear()
    bundle = ensure_mhspc_frontline_reference(root=tmp_path)

    assert bundle["raw_snapshot_path"]
    assert bundle["curated_reference_path"]
    assert (tmp_path / "raw_ingestion_snapshot.json").exists()
    assert (tmp_path / "curated_treatment_reference.json").exists()
    assert bundle["curated_reference"]["components"]["Darolutamida"]["imss_key"] == "010.000.7076.00"
    assert bundle["curated_reference"]["components"]["Abiraterona"]["route"] == "Oral"


def test_mhspc_frontline_reference_reuses_process_cache_for_same_signature(tmp_path, monkeypatch):
    mhspc_reference_module._REFERENCE_CACHE.clear()
    ensure_mhspc_frontline_reference(root=tmp_path)

    def _fail_raw_snapshot():
        raise AssertionError("La referencia mHSPC no debe reingerirse si la firma de archivos no cambió.")

    def _fail_curated_reference():
        raise AssertionError("La referencia mHSPC no debe reconstruirse si la firma de archivos no cambió.")

    monkeypatch.setattr(mhspc_reference_module, "build_raw_ingestion_snapshot", _fail_raw_snapshot)
    monkeypatch.setattr(mhspc_reference_module, "build_curated_treatment_reference", _fail_curated_reference)

    cached = ensure_mhspc_frontline_reference(root=tmp_path)

    assert cached["curated_reference"]["components"]["Darolutamida"]["imss_key"] == "010.000.7076.00"


def test_low_volume_frontline_does_not_default_to_darolutamide_without_risk(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_low_volume_sync_oligo/evaluate",
        json={
            "metastasis_count": 2,
            "metastasis_site": "Bone",
            "ecog_score": 0,
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "rt_primary_received": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["preferred_frontline_regimen"]["regimen_code"] == "ADT_ENZALUTAMIDE"
    assert "enzalutamida" in result["eligible_treatments"][0]["name"].lower()
    assert result["preferred_frontline_regimen"]["regimen_code"] != "ADT_DAROLUTAMIDE"


def test_low_volume_frontline_prefers_darolutamide_when_neurologic_risk_is_present(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_low_volume_sync_oligo/evaluate",
        json={
            "metastasis_count": 2,
            "metastasis_site": "Bone",
            "ecog_score": 0,
            "comorbidity_seizure": 1,
            "cv_risk_documented": 1,
            "drug_interaction_reviewed": 0,
            "rt_primary_received": 0,
            "frailty_status": "Vulnerable",
            "child_pugh_score": "A",
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]

    assert preferred["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert any(component["drug_name"] == "Darolutamida" for component in preferred["component_drugs"])
    assert any(component["imss_key"] == "010.000.7076.00" for component in preferred["component_drugs"])


def test_high_volume_sync_prefers_clinically_ranked_triplet_and_exposes_component_metadata(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]

    assert preferred["regimen_code"] == "ADT_DOCETAXEL_ABIRATERONE"
    assert any(component["drug_name"] == "Docetaxel" for component in preferred["component_drugs"])
    assert any(component["drug_name"] == "Abiraterona" for component in preferred["component_drugs"])
    assert any(component["metadata_source"] == "current_catalog" for component in preferred["component_drugs"])
    assert "Intravenosa" in preferred["route"]
    assert "Oral" in preferred["route"]
    assert "Subcutánea / intramuscular" in preferred["route"]
    assert "75 mg/m²" in preferred["dose"]
    assert "1000 mg al día" in preferred["dose"]
    assert preferred["description"]


def test_hepatic_risk_rejects_abiraterone_regimens(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 6,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "B",
            "hepatic_risk_factors": 1,
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    rejections = {
        item["regimen_code"]: item
        for item in result["frontline_regimen_rejections"]
    }

    assert "ADT_ABIRATERONE" in rejections
    assert "ADT_DOCETAXEL_ABIRATERONE" in rejections
    assert any("hep" in reason.lower() for reason in rejections["ADT_ABIRATERONE"]["contraindication_reasons"])


def test_high_volume_sync_conditional_docetaxel_with_seizure_defaults_to_darolutamide(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 5,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 1}],
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 2,
            "frailty_status": "Vulnerable",
            "child_pugh_score": "A",
            "comorbidity_seizure": 1,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "diabetes_uncontrolled": 0,
            "steroid_intolerance": 0,
            "edema_risk": 0,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    trace = result["frontline_ranking_trace"]

    assert preferred["regimen_code"] == "ADT_DAROLUTAMIDE"
    assert result["docetaxel_base_eligibility"] == "elegible_with_caution"
    assert result["docetaxel_default_intensification"] == "no"
    assert result["triplet_decision"]["status"] == "not_prioritized"
    assert "darolutamida" in trace["winner_reason"].lower()
    assert "docetaxel" in trace["why_not_triplet"].lower()
    assert "latitude-like" in trace["why_not_abiraterone"].lower() or "darolutamida" in trace["why_not_abiraterone"].lower()


def test_high_volume_sync_ecog2_cancer_related_keeps_triplet_conditional_not_blocked(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 5,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 1}],
            "gleason_primary": 4,
            "gleason_secondary": 5,
            "ecog_score": 2,
            "performance_status_driver": "cancer_related",
            "bone_pain": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["fit_for_docetaxel"] is True
    assert result["docetaxel_base_eligibility"] == "elegible_with_caution"
    assert result["docetaxel_default_intensification"] == "conditional"
    assert result["docetaxel_trial_fit"]["peace1_like"] == "partial"
    assert result["triplet_decision"]["status"] == "conditional"
    assert result["preferred_frontline_regimen"]["regimen_code"] != "ADT_DOCETAXEL_DAROLUTAMIDE"


def test_high_volume_sync_ecog2_frailty_driven_removes_docetaxel_default(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 5,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "ecog_score": 2,
            "performance_status_driver": "comorbidity_or_frailty",
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Vulnerable",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            "comorbidity_seizure": 1,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["docetaxel_default_intensification"] == "no"
    assert result["triplet_decision"]["status"] == "not_prioritized"
    assert result["preferred_frontline_regimen"]["regimen_code"] == "ADT_DAROLUTAMIDE"


def test_high_volume_sync_allows_abiraterone_to_override_only_with_visible_latitude_like_rationale(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastatic_disease_known": 1,
            "metastasis_count": 6,
            "bone_site_entries": [
                {"site_key": "thoracic_spine", "lesion_count": 3},
                {"site_key": "femur", "lesion_count": 1},
            ],
            "visceral_site_entries": [{"site_key": "liver", "lesion_count": 2}],
            "gleason_primary": 5,
            "gleason_secondary": 4,
            "gleason_tertiary": 5,
            "ecog_score": 0,
            "peripheral_neuropathy_grade": 2,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_seizure": 1,
            "comorbidity_cardio": 0,
            "cv_risk_documented": 0,
            "drug_interaction_reviewed": 1,
            "diabetes_uncontrolled": 0,
            "steroid_intolerance": 0,
            "edema_risk": 0,
            **_recent_docetaxel_labs(),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]
    trace = result["frontline_ranking_trace"]

    assert preferred["regimen_code"] == "ADT_ABIRATERONE"
    assert "latitud" in trace["winner_reason"].lower()
    assert "darolutamida" in trace["why_not_darolutamide"].lower() or "puntaje clínico" in trace["why_not_darolutamide"].lower()


def test_oracle_alignment_keeps_castrate_biochemical_case_in_m0_crpc():
    catalog = {
        item["scenario_id"]: item
        for item in build_trajectory_catalog()
    }

    scenario = catalog["adt_progression_castrate_biochemical"]

    assert scenario["baseline_oracle"]["expected_effective_state"] == "adt_progression_verification"
    assert scenario["visits"][1]["oracle"]["expected_effective_state"] == "m0_crpc"
    assert scenario["clinical_oracle"]["expected_effective_state"] == "m0_crpc"


def test_high_volume_sync_without_current_docetaxel_labs_stays_pending_validation(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["triplet_decision"]["status"] == "pending_validation"
    assert result["docetaxel_fitness"]["docetaxel_verification_status"] == "pending_labs"
    assert "anc" in [item.lower() for item in result["triplet_decision"]["missing_inputs"]]
    assert not any("<1500" in reason for reason in result["triplet_decision"]["hard_stop_reasons"])


def test_high_volume_sync_with_stale_docetaxel_labs_requests_refresh(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(
                cbc_date=(date.today() - timedelta(days=25)).isoformat(),
                liver_panel_date=(date.today() - timedelta(days=25)).isoformat(),
            ),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["triplet_decision"]["status"] == "pending_validation"
    assert result["docetaxel_fitness"]["docetaxel_verification_status"] == "stale_labs"
    assert "anc" in [item.lower() for item in result["triplet_decision"]["stale_inputs"]]


def test_high_volume_sync_low_anc_creates_label_based_docetaxel_block(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/mcspc_high_volume_sync/evaluate",
        json={
            "metastasis_count": 7,
            "metastasis_site": "Bone",
            "ecog_score": 1,
            "peripheral_neuropathy_grade": 0,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "drug_interaction_reviewed": 1,
            **_recent_docetaxel_labs(anc=1200),
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]

    assert result["triplet_decision"]["status"] == "contraindicated"
    assert result["docetaxel_fitness"]["docetaxel_block_type"] == "label"
    assert any("neutrófilos <1500/mm3" in reason.lower() for reason in result["triplet_decision"]["hard_stop_reasons"])
