from __future__ import annotations

from prostanet.domains.clinical_validation.vertical_verification import (
    _vertical_from_snapshot,
    run_vertical_verification,
)


def test_run_vertical_verification_returns_seeded_and_live_coverage(app_client):
    client, _ = app_client

    report = run_vertical_verification(
        app=client.application,
        base_url="http://127.0.0.1:8080",
        visual_mode="textual",
        live_limit_per_vertical=1,
        seed_live_samples_when_missing=True,
    )

    assert report["seeded"]["summary"]["total_cases"] == 22
    assert report["current_db"]["summary"]["total_cases"] >= 2
    assert report["current_db"]["summary"]["sample_coverage"]["crpc_first"] >= 1
    assert report["current_db"]["summary"]["sample_coverage"]["post_rp_salvage_first"] >= 1

    for case in report["current_db"]["cases"]:
        status_checks = {
            item["key"]: item["passed"]
            for item in case.get("api_contract_assertions", [])
            if item["key"] in {
                "signals_status_code",
                "schedule_status_code",
                "full_assessment_status_code",
                "copilot_status_code",
            }
        }
        assert status_checks == {
            "signals_status_code": True,
            "schedule_status_code": True,
            "full_assessment_status_code": True,
            "copilot_status_code": True,
        }


def test_vertical_audit_endpoint_returns_report(app_client):
    client, _ = app_client

    response = client.post(
        "/api/validation/vertical-audit",
        json={
            "visual_mode": "textual",
            "live_limit_per_vertical": 1,
            "seed_live_samples_when_missing": True,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["report"]["seeded"]["summary"]["total_cases"] == 22
    assert payload["report"]["current_db"]["summary"]["sample_coverage"]["crpc_first"] >= 1


def test_vertical_snapshot_does_not_classify_post_rt_recurrence_as_post_rp_vertical():
    snapshot = {
        "signals": {"effective_state": "recurrence_bcr"},
        "longitudinal_bundle": {
            "crpc_copilot_bundle": {"available": False},
            "post_rp_salvage_bundle": {"available": False},
        },
        "patient_record": {
            "bcr": {"primary_treatment": "RT"},
            "latest_assessment": {"input_snapshot": {"prior_radiation": 1}},
            "prior_history": {"current_state": "recurrence_bcr"},
            "baseline": {},
            "surgery": {},
        },
    }

    assert _vertical_from_snapshot(snapshot) == "other"
