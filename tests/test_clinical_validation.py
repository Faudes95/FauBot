from collections import Counter

from prostanet.domains.clinical_validation import build_trajectory_catalog


def test_clinical_validation_catalog_has_52_trajectories_with_expected_family_distribution():
    trajectories = build_trajectory_catalog()

    assert len(trajectories) == 52

    family_counts = Counter(item["scenario_family"] for item in trajectories)
    assert family_counts == {
        "diagnostic_workup": 5,
        "post_negative_biopsy_followup": 4,
        "localized_initial": 7,
        "active_surveillance": 5,
        "post_prostatectomy": 5,
        "recurrence_bcr": 5,
        "post_radiotherapy_or_local_salvage": 4,
        "adt_progression_verification": 5,
        "m0_crpc": 3,
        "mHSPC": 4,
        "m1_crpc": 5,
    }

    scenario_ids = [item["scenario_id"] for item in trajectories]
    assert len(set(scenario_ids)) == len(scenario_ids)


def test_validation_trajectories_endpoint_exposes_catalog_and_family_counts(app_client):
    client, _ = app_client

    response = client.get("/api/validation/trajectories")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["total_trajectories"] == 52
    assert len(payload["trajectories"]) == 52
    assert payload["family_counts"]["m1_crpc"] == 5
    assert payload["family_counts"]["post_prostatectomy"] == 5
    assert payload["family_counts"]["adt_progression_verification"] == 5
    assert any(item["scenario_id"] == "post_prostatectomy_persistent_psa" for item in payload["trajectories"])
    assert any(item["scenario_id"] == "m1_crpc_abiraterone_hepatic_safety" for item in payload["trajectories"])
    assert any(item["scenario_id"] == "high_volume_progression_on_adt_unclosed_castration" for item in payload["trajectories"])
