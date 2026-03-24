from __future__ import annotations

from pathlib import Path


def make_patient_payload(nss="AI-TEST-001", full_name="Paciente AI Seguro"):
    return {
        "nss": nss,
        "full_name": full_name,
        "dob": "1964-05-01",
        "line_of_therapy": 1,
        "metastasis_site": "M0",
        "volume_disease": "Low",
        "baseline_psa": 9.2,
        "testosterone_baseline": 330,
    }


def _seed_latest_assessment_state(db_path, patient_id, state, module_id=None):
    import json
    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO clinical_assessments (
            module_id, state, input_snapshot, result_snapshot, guideline_versions, status, patient_id
        ) VALUES (?, ?, ?, ?, ?, 'linked', ?)
        """,
        (
            module_id or state,
            state,
            json.dumps({}),
            json.dumps({}),
            json.dumps({}),
            patient_id,
        ),
    )
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        (state, patient_id),
    )
    conn.commit()
    conn.close()


def test_ai_models_endpoint_reports_runtime_mode_and_model_maturity(app_client):
    client, _ = app_client

    response = client.get("/api/ai/models")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["rule_based_source_of_truth"] is True
    assert payload["runtime_mode"] in {"shadow", "advisory"}
    assert "state_transition" in payload["models"]

    state_model = payload["models"]["state_transition"]
    assert state_model["maturity"] in {"not_loaded", "experimental", "shadow", "advisory"}
    assert state_model["validation_status"] in {
        "artifact_missing",
        "artifact_only",
        "registered",
        "provenance_ready",
        "validated",
    }


def test_ai_config_and_model_registry_share_default_model_dir():
    from prostanet.ai.config import get_ai_config
    from prostanet.ai.inference.model_registry import ModelRegistry

    config = get_ai_config()
    registry = ModelRegistry()

    assert Path(config.model_dir) == registry.models_dir


def test_confidence_weights_align_with_runtime_components():
    from prostanet.ai.config import CONFIDENCE_WEIGHTS
    from prostanet.engine.confidence_scoring import ConfidenceScorer

    scorer = ConfidenceScorer()
    result = scorer.score(record={})

    assert set(result["components"].keys()) == set(CONFIDENCE_WEIGHTS.keys())
    assert result["weights_used"] == CONFIDENCE_WEIGHTS


def test_state_prediction_endpoint_returns_model_status_when_unavailable(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="AI-TEST-002", full_name="Paciente Modelo Ausente")
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]

    response = client.post(f"/api/ai/predict/state-transition/{patient_id}", json={})
    assert response.status_code == 503

    body = response.get_json()
    assert body["success"] is False
    assert body["advisory_api"] is True
    assert body["rule_based_source_of_truth"] is True
    assert body["model_status"]["model_id"] == "state_transition"


def test_full_assessment_exposes_rule_based_and_ai_overlay_layers(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="AI-TEST-003", full_name="Paciente Overlay AI")
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.post(f"/api/ai/full-assessment/{payload['nss']}", json={})
    assert response.status_code == 200

    body = response.get_json()
    assert body["success"] is True
    assert body["rule_based_source_of_truth"] is True
    assert body["advisory_api"] is True
    assert body["runtime_mode"] in {"shadow", "advisory"}
    assert body["rule_based_recommendation"]["source"] == "rule_based_primary"
    assert "ai_advisory_overlay" in body
    assert "final_presented_recommendation" in body
    if body["runtime_mode"] == "shadow":
        assert body["final_presented_recommendation"]["source"] == "rule_based_primary"
