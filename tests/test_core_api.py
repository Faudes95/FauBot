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


def test_agenda_endpoints_and_stage_visit_bundle_flow(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="44444444444", full_name="Paciente Agenda")

    register_response = client.post("/api/register_patient", json=payload)
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    agenda_response = client.get(f"/api/patients/{payload['nss']}/agenda")
    assert agenda_response.status_code == 200
    agenda = agenda_response.get_json()["agenda"]
    assert agenda["items"]

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema")
    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    assert schema["sections"]

    comparators_response = client.get(f"/api/patients/{patient_id}/protocol-comparison")
    assert comparators_response.status_code == 200
    comparators = comparators_response.get_json()["comparators"]
    assert comparators[0]["mode"] == "guideline_primary"

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-15",
            "state": "diagnostic_workup",
            "management_track": "diagnostic_surveillance",
            "disease_status": "Seguimiento estable",
            "psa": 9.1,
            "psad": 0.21,
            "pirads_score": "4",
            "mpmri_quality": "Adecuada",
            "planned_biopsy_type": "Dirigida + sistemática",
            "planned_biopsy_route": "Transperineal",
        },
    )
    assert visit_response.status_code == 200
    visit_payload = visit_response.get_json()
    assert visit_payload["success"] is True
    assert isinstance(visit_payload["followup_id"], int)
    assert isinstance(visit_payload["visit_record_id"], int)

    export_response = client.get(f"/api/export/{payload['nss']}")
    export_data = export_response.get_json()
    assert export_response.status_code == 200
    assert export_data["stage_visits"]
    assert export_data["data_provenance"]

    agenda_after_response = client.get(f"/api/patients/{payload['nss']}/agenda")
    agenda_after = agenda_after_response.get_json()["agenda"]
    actionable_item = next((item for item in agenda_after["items"] if item.get("status") in {"due", "overdue", "scheduled"}), None)
    assert actionable_item is not None

    complete_response = client.post(f"/api/patients/{patient_id}/agenda/{actionable_item['id']}/complete", json={})
    assert complete_response.status_code == 200
    assert complete_response.get_json()["success"] is True


def test_longitudinal_intelligence_loop_creates_transition_proposal_and_confirmation(app_client):
    client, _ = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "diagnostic_workup",
            "payload": {
                "age": 64,
                "psa": 9.4,
                "psad": 0.22,
                "mpmri_quality": "Adecuada",
                "pirads_score": "4",
                "index_lesion_location": "Zona periférica posterior",
                "index_lesion_size_mm": 12,
                "prostate_volume_ml": 43,
                "planned_biopsy_type": "Dirigida + sistemática",
                "planned_biopsy_route": "Transperineal",
                "risk_calculator_pathway": "MRI + PSAD + ERSPC",
            },
        },
    )
    assert draft_response.status_code == 200
    assessment_id = draft_response.get_json()["assessment_id"]

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "assessment_state": "diagnostic_workup",
            "nss": "66666666666",
            "full_name": "Paciente Loop",
            "dob": "1962-06-06",
            "baseline_psa": 9.4,
        },
    )
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    assert signals_payload["signals"]["state"] == "diagnostic_workup"
    assert signals_payload["next_best_action"]["title"]

    result_response = client.post(
        f"/api/patients/{patient_id}/results",
        json={
            "result_type": "pathology",
            "payload": {
                "biopsy_date": "2026-03-15",
                "biopsy_type": "Dirigida + sistemática",
                "biopsy_context": "diagnostica",
                "total_cores": 12,
                "positive_cores": 3,
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "porcentaje_patron_4": 15,
            },
        },
    )
    assert result_response.status_code == 200
    result_payload = result_response.get_json()
    proposals = result_payload["transition_proposals"]
    assert proposals
    localized_proposal = next((item for item in proposals if item["target_state"] == "localized_initial"), None)
    assert localized_proposal is not None

    next_action_response = client.get(f"/api/patients/{patient_id}/next-best-action")
    assert next_action_response.status_code == 200
    assert "Confirmar transición" in next_action_response.get_json()["next_best_action"]["title"]

    confirm_response = client.post(
        f"/api/patients/{patient_id}/state-transition/{localized_proposal['id']}/confirm",
        json={"confirmed_by": "test"},
    )
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.get_json()
    assert confirm_payload["assessment_id"] is not None

    patient_response = client.get("/api/patient/66666666666")
    assert patient_response.status_code == 200
    patient = patient_response.get_json()["patient"]
    assert patient["latest_assessment"]["state"] == "localized_initial"


def test_source_document_pathology_flow_requires_verification_before_transition(app_client):
    client, _ = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "diagnostic_workup",
            "payload": {
                "age": 66,
                "psa": 10.1,
                "psad": 0.24,
                "mpmri_quality": "Adecuada",
                "pirads_score": "5",
                "index_lesion_location": "Zona periférica posterior",
                "index_lesion_size_mm": 14,
                "prostate_volume_ml": 42,
                "planned_biopsy_type": "Dirigida + sistemática",
                "planned_biopsy_route": "Transperineal",
            },
        },
    )
    assessment_id = draft_response.get_json()["assessment_id"]
    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "assessment_state": "diagnostic_workup",
            "nss": "77777777777",
            "full_name": "Paciente Documento Patologia",
            "dob": "1960-07-07",
            "baseline_psa": 10.1,
        },
    )
    patient_id = register_response.get_json()["patient_id"]

    upload_response = client.post(
        f"/api/patients/{patient_id}/documents",
        data={
            "title": "Reporte histopatológico inicial",
            "document_type": "pathology_report",
            "source_date": "2026-03-15",
            "file": (
                io.BytesIO(
                    b"Reporte histopatologico de prostata.\nGleason score 3+4=7.\nISUP 2.\n3/12 cores positivos.\nPatron 4 15 por ciento.\nCribriforme presente.\n"
                ),
                "pathology_report.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 200
    document = upload_response.get_json()["document"]
    document_id = document["id"]

    signals_before = client.get(f"/api/patients/{patient_id}/signals").get_json()
    assert signals_before["signals"]["state"] == "diagnostic_workup"
    assert not any(item["target_state"] == "localized_initial" for item in signals_before["transition_proposals"])

    extract_response = client.post(f"/api/patients/{patient_id}/documents/{document_id}/extract", json={})
    assert extract_response.status_code == 200
    extract_payload = extract_response.get_json()
    assert extract_payload["document"]["document_type"] == "pathology_report"
    assert any(item["field_name"] == "gleason_primary" for item in extract_payload["candidates"])

    facts_payload = [
        {
            "field_name": item["field_name"],
            "fact_group": item["fact_group"],
            "target_result_type": item["target_result_type"],
            "value": item["value"],
        }
        for item in extract_payload["candidates"]
    ]
    facts_payload.append(
        {
            "field_name": "biopsy_date",
            "fact_group": "pathology",
            "target_result_type": "pathology",
            "value": "2026-03-15",
        }
    )
    verify_response = client.post(
        f"/api/patients/{patient_id}/documents/{document_id}/verify",
        json={
            "verified_by": "test",
            "source_date": "2026-03-15",
            "facts": facts_payload,
        },
    )
    assert verify_response.status_code == 200
    verify_payload = verify_response.get_json()
    assert verify_payload["document_bundle"]["document"]["verification_status"] == "verified"
    assert verify_payload["verified_fact_bundle"]["committed_result_types"] == ["pathology"]
    assert any(item["target_state"] == "localized_initial" for item in verify_payload["transition_proposals"])

    export_response = client.get("/api/export/77777777777")
    export_payload = export_response.get_json()
    assert export_response.status_code == 200
    assert export_payload["source_documents"]
    assert export_payload["verified_document_facts"]


def test_source_document_imaging_and_genomic_reports_persist_structured_results(app_client):
    client, _ = app_client
    register_response = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="88888888888", full_name="Paciente Documento Imagen Genomica"),
    )
    patient_id = register_response.get_json()["patient_id"]

    imaging_upload = client.post(
        f"/api/patients/{patient_id}/documents",
        data={
            "title": "PSMA PET marzo 2026",
            "document_type": "imaging_report",
            "source_date": "2026-03-15",
            "file": (
                io.BytesIO(
                    b"PSMA PET positivo con SUV max 13.2. Lesiones en ganglios pelvicos y higado.\n"
                ),
                "psma_pet.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    imaging_document_id = imaging_upload.get_json()["document"]["id"]
    imaging_extract = client.post(f"/api/patients/{patient_id}/documents/{imaging_document_id}/extract", json={}).get_json()
    imaging_verify = client.post(
        f"/api/patients/{patient_id}/documents/{imaging_document_id}/verify",
        json={
            "verified_by": "test",
            "source_date": "2026-03-15",
            "facts": [
                {
                    "field_name": item["field_name"],
                    "fact_group": item["fact_group"],
                    "target_result_type": item["target_result_type"],
                    "value": item["value"],
                }
                for item in imaging_extract["candidates"]
            ]
            + [
                {
                    "field_name": "study_date",
                    "fact_group": "imaging",
                    "target_result_type": "imaging",
                    "value": "2026-03-15",
                }
            ],
        },
    )
    assert imaging_verify.status_code == 200

    genomic_upload = client.post(
        f"/api/patients/{patient_id}/documents",
        data={
            "title": "Panel molecular",
            "document_type": "genomic_report",
            "source_date": "2026-03-16",
            "file": (
                io.BytesIO(
                    b"Decipher high. BRCA2 pathogenic mutation. HRR positive. MSI stable. TMB 11.\n"
                ),
                "genomic_report.txt",
            ),
        },
        content_type="multipart/form-data",
    )
    genomic_document_id = genomic_upload.get_json()["document"]["id"]
    genomic_extract = client.post(f"/api/patients/{patient_id}/documents/{genomic_document_id}/extract", json={}).get_json()
    genomic_verify = client.post(
        f"/api/patients/{patient_id}/documents/{genomic_document_id}/verify",
        json={
            "verified_by": "test",
            "source_date": "2026-03-16",
            "facts": [
                {
                    "field_name": item["field_name"],
                    "fact_group": item["fact_group"],
                    "target_result_type": item["target_result_type"],
                    "value": item["value"],
                }
                for item in genomic_extract["candidates"]
            ]
            + [
                {
                    "field_name": "test_date",
                    "fact_group": "genomic",
                    "target_result_type": "genomic",
                    "value": "2026-03-16",
                }
            ],
        },
    )
    assert genomic_verify.status_code == 200

    documents_response = client.get(f"/api/patients/{patient_id}/documents")
    assert documents_response.status_code == 200
    assert len(documents_response.get_json()["documents"]) == 2

    patient_response = client.get("/api/patient/88888888888")
    patient = patient_response.get_json()["patient"]
    assert any("PSMA" in item["study_type"] for item in patient["imaging"])
    assert patient["genomics"]["brca2_status"] in {"positivo", "documentado"}
