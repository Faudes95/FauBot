import csv
import io
import json
import sqlite3


def make_patient_payload(nss="12345678901", full_name="Paciente Demo"):
    return {
        "nss": nss,
        "full_name": full_name,
        "dob": "1960-01-01",
        "line_of_therapy": 1,
        "metastasis_site": "M0",
        "volume_disease": "Low",
        "baseline_psa": 8.4,
        "testosterone_baseline": 320,
    }


def test_register_patient_returns_real_id_and_persists_core_tables(app_client):
    client, db_path = app_client
    payload = make_patient_payload()

    response = client.post("/api/register_patient", json=payload)

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert isinstance(data["patient_id"], int)
    assert data["patient_id"] > 0
    assert data["nss"] == payload["nss"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patient_identity")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM clinical_baseline")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM prior_clinical_history")
    assert cursor.fetchone()[0] == 1
    conn.close()

    record_response = client.get(f"/api/patient/{payload['nss']}")
    assert record_response.status_code == 200
    record = record_response.get_json()
    assert record["success"] is True
    assert record["patient"]["identity"]["full_name"] == payload["full_name"]


def test_register_patient_rejects_duplicate_nss(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="11111111111")

    first = client.post("/api/register_patient", json=payload)
    second = client.post("/api/register_patient", json=payload)

    assert first.status_code == 200
    assert second.status_code == 400
    second_data = second.get_json()
    assert second_data["success"] is False
    assert "ya existe" in second_data["error"]


def test_register_patient_validates_required_fields_and_numeric_types(app_client):
    client, _ = app_client

    missing_required = client.post("/api/register_patient", json={"full_name": "Sin NSS"})
    assert missing_required.status_code == 400
    assert missing_required.get_json()["success"] is False

    invalid_numeric = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="22222222222") | {"line_of_therapy": "primera"},
    )
    assert invalid_numeric.status_code == 400
    invalid_data = invalid_numeric.get_json()
    assert invalid_data["success"] is False
    assert "line_of_therapy" in invalid_data["error"]


def test_followup_alerts_and_export_flow(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="33333333333", full_name="Paciente Seguimiento")

    register_response = client.post("/api/register_patient", json=payload)
    patient_data = register_response.get_json()
    patient_id = patient_data["patient_id"]

    followup_response = client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 2.1,
            "testosterone": 15,
            "ecog": 1,
            "pain": 2,
            "treatment": "ADT",
            "status": "Estable",
        },
    )
    assert followup_response.status_code == 200
    followup_data = followup_response.get_json()
    assert followup_data["success"] is True
    assert isinstance(followup_data["id"], int)

    check_alerts_response = client.post(f"/api/alerts/{patient_id}/check")
    assert check_alerts_response.status_code == 200
    check_alerts_data = check_alerts_response.get_json()
    assert check_alerts_data["success"] is True
    assert isinstance(check_alerts_data["new_alerts"], list)

    alerts_response = client.get(f"/api/alerts/{patient_id}")
    assert alerts_response.status_code == 200
    alerts_data = alerts_response.get_json()
    assert alerts_data["success"] is True
    assert isinstance(alerts_data["alerts"], list)

    export_response = client.get(f"/api/export/{payload['nss']}")
    assert export_response.status_code == 200
    export_data = export_response.get_json()
    assert export_data["identity"]["nss"] == payload["nss"]
    assert len(export_data["follow_ups"]) == 1

    export_json_response = client.get(f"/api/export/{payload['nss']}?format=json")
    assert export_json_response.status_code == 200
    export_json = json.loads(export_json_response.get_data(as_text=True))
    assert export_json["identity"]["full_name"] == payload["full_name"]

    export_csv_response = client.get(f"/api/export/{payload['nss']}/csv")
    assert export_csv_response.status_code == 200
    csv_rows = list(csv.DictReader(io.StringIO(export_csv_response.get_data(as_text=True))))
    assert len(csv_rows) == 1
    assert csv_rows[0]["id_nss"] == payload["nss"]
    assert csv_rows[0]["n_followups"] == "1"


def test_patient_and_alert_routes_return_404_for_missing_patient(app_client):
    client, _ = app_client

    patient_response = client.get("/api/patient/00000000000")
    assert patient_response.status_code == 404
    assert patient_response.get_json()["success"] is False

    alerts_response = client.get("/api/alerts/999")
    assert alerts_response.status_code == 404
    assert alerts_response.get_json()["success"] is False

    export_response = client.get("/api/export/00000000000")
    assert export_response.status_code == 404
    assert export_response.get_json()["success"] is False
