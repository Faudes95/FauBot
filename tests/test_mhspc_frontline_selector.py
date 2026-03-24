from __future__ import annotations

from prostanet.domains.clinical_validation.trajectory_catalog import build_trajectory_catalog
from prostanet.domains.patient_tracking.mhspc_frontline_reference import (
    ensure_mhspc_frontline_reference,
)


def test_mhspc_frontline_reference_persists_curated_drug_metadata(tmp_path):
    bundle = ensure_mhspc_frontline_reference(root=tmp_path)

    assert bundle["raw_snapshot_path"]
    assert bundle["curated_reference_path"]
    assert (tmp_path / "raw_ingestion_snapshot.json").exists()
    assert (tmp_path / "curated_treatment_reference.json").exists()
    assert bundle["curated_reference"]["components"]["Darolutamida"]["imss_key"] == "010.000.7076.00"
    assert bundle["curated_reference"]["components"]["Abiraterona"]["route"] == "Oral"


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


def test_high_volume_sync_prefers_triplet_and_exposes_component_metadata(app_client):
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
        },
    )

    assert response.status_code == 200
    result = response.get_json()["result"]
    preferred = result["preferred_frontline_regimen"]

    assert preferred["regimen_code"] == "ADT_DOCETAXEL_DAROLUTAMIDE"
    assert any(component["drug_name"] == "Docetaxel" for component in preferred["component_drugs"])
    assert any(component["metadata_source"] == "current_catalog" for component in preferred["component_drugs"])


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


def test_oracle_alignment_keeps_castrate_biochemical_case_in_m0_crpc():
    catalog = {
        item["scenario_id"]: item
        for item in build_trajectory_catalog()
    }

    scenario = catalog["adt_progression_castrate_biochemical"]

    assert scenario["baseline_oracle"]["expected_effective_state"] == "adt_progression_verification"
    assert scenario["visits"][1]["oracle"]["expected_effective_state"] == "m0_crpc"
    assert scenario["clinical_oracle"]["expected_effective_state"] == "m0_crpc"
