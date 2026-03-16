import csv
import io
import json
import sqlite3

from prostanet.shared.tnm_engine import TNMEngine


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


def test_visit_schema_filters_fields_for_item_scoped_arpi_bundle(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45454545454", full_name="Paciente Item Agenda"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            3.4,
            18.0,
            "Abiraterona + ADT",
            "Seguimiento estable",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    agenda = client.get("/api/patients/45454545454/agenda").get_json()["agenda"]
    arpi_item = next(item for item in agenda["items"] if item["title"] == "Bundle de seguridad ARPI")

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema?agenda_id={arpi_item['id']}")
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    assert payload["visit_schema"]["submission_mode"] == "item_scoped"
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }
    assert {"visit_date", "mini_cog_score", "fatigue_score", "cv_risk_documented", "drug_interaction_reviewed"} <= field_names
    assert "line_of_therapy" not in field_names
    assert payload["agenda_item_context"]["decision_targets"] == ["arpi_safety", "supportive_care", "treatment_tolerability"]


def test_visit_schema_supports_capture_block_for_missing_inputs(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555555", full_name="Paciente Captura Dirigida"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=mcspc_high_volume"
        "&track=on_arpi"
        "&fields=line_of_therapy_number,line_of_therapy_context,psa"
        "&capture_title=Confirmar%20linea%20terapeutica"
        "&capture_group=advanced_sequencing"
        "&decision_affected=systemic_sequencing"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }
    assert {"visit_date", "line_of_therapy_number", "line_of_therapy_context", "psa", "clinician_notes"} <= field_names
    assert payload["agenda_item_context"]["mode"] == "capture_block"
    assert payload["agenda_item_context"]["decision_targets"] == ["systemic_sequencing"]


def test_visit_schema_uses_canonical_regimen_dropdown_for_advanced_tracks(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555556", full_name="Paciente Catalogo Terapia"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=mcspc_high_volume"
        "&track=on_arpi"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    drug_field = next(
        field
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
        if field["name"] == "drug_scheme"
    )
    assert drug_field["field_type"] == "select"
    option_values = [option["value"] for option in drug_field["options"] if isinstance(option, dict) and option.get("value")]
    assert "ADT_ABIRATERONE" in option_values
    assert "ADT_ENZALUTAMIDE" in option_values
    assert "ADT_DOCETAXEL_DAROLUTAMIDE" not in option_values


def test_visit_schema_includes_structured_metastatic_distribution_for_advanced_tracks(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555558", full_name="Paciente TNM Metastasico"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(
        f"/api/patients/{patient_id}/visit-schema"
        "?state=mcspc_high_volume"
        "&track=systemic_surveillance"
    )
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    field_names = {
        field["name"]
        for section in payload["visit_schema"]["sections"]
        for field in section["fields"]
    }
    assert {
        "nonregional_nodal_retroperitoneal_count",
        "bone_femur_count",
        "bone_ribs_thorax_count",
        "visceral_lung_count",
        "visceral_liver_count",
        "metastasis_assessment_date",
    } <= field_names


def test_register_patient_normalizes_canonical_regimen_code_from_catalog(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="45555555557", full_name="Paciente Regimen Canonico") | {
        "assessment_state": "mcspc_high_volume",
        "line_of_therapy_number": 1,
        "line_of_therapy_context": "mHSPC_initial",
        "drug_scheme": "Abiraterona + ADT",
    }

    response = client.post("/api/register_patient", json=payload)

    assert response.status_code == 200
    patient = client.get("/api/patient/45555555557").get_json()["patient"]
    assert patient["treatments"][-1]["drug_scheme"] == "ADT_ABIRATERONE"


def test_item_scoped_advanced_visit_updates_canonical_longitudinal_targets(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="46464646464", full_name="Paciente Seguimiento Dirigido"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            4.1,
            22.0,
            "Abiraterona + ADT",
            "Seguimiento estable",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    agenda = client.get("/api/patients/46464646464/agenda").get_json()["agenda"]
    therapy_item = next(item for item in agenda["items"] if item["item_type"] == "therapy_review")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "agenda_ids": [therapy_item["id"]],
            "agenda_submission_mode": "item_scoped",
            "visit_date": "2026-03-20",
            "state": "adt_progression_verification",
            "management_track": "on_arpi",
            "disease_status": "Seguimiento estable",
            "current_treatment": "Abiraterona + ADT",
            "ecog": 1,
            "line_of_therapy": 1,
            "drug_scheme": "ADT_ABIRATERONE",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "progression_pattern": "none",
            "conventional_imaging_status": "M1",
        },
    )
    assert visit_response.status_code == 200
    assert visit_response.get_json()["success"] is True

    record_response = client.get("/api/patient/46464646464")
    assert record_response.status_code == 200
    patient = record_response.get_json()["patient"]
    assert patient["treatments"][-1]["drug_scheme"] == "ADT_ABIRATERONE"

    agenda_after = client.get("/api/patients/46464646464/agenda").get_json()["agenda"]
    assert any(item["agenda_key"] == therapy_item["agenda_key"] for item in agenda_after["active_items"])
    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    refreshed = tracking_db.get_patient_full_record("46464646464")
    profile = build_patient_profile_view_model(
        patient=refreshed,
        latest_assessment_raw=refreshed.get("latest_assessment") or {},
        latest_assessment=refreshed.get("latest_assessment") or {},
        state_timeline=refreshed.get("state_timeline") or [],
        care_overlays=refreshed.get("care_overlays") or [],
        recommendations={},
    )
    sequencing_items = {
        item["label"]: item
        for item in profile["advanced_panel_context"]["sequencing_context"]["items"]
    }
    assert sequencing_items["Esquema actual"]["value"] == "ADT + abiraterona"
    assert sequencing_items["Esquema actual"]["evidence_status"] == "captured"


def test_line_change_from_visit_creates_event_and_psa_monitoring_by_line(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="46565656565", full_name="Paciente Cambio de Linea"))
    patient_id = register.get_json()["patient_id"]

    first_visit = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-03-15",
            "state": "adt_progression_verification",
            "management_track": "on_arpi",
            "disease_status": "Control inicial",
            "current_treatment": "Abiraterona + ADT",
            "line_of_therapy_number": 1,
            "line_of_therapy_context": "mHSPC_initial",
            "drug_scheme": "ADT_ABIRATERONE",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "psa": 10.5,
            "testosterone": 18,
        },
    )
    assert first_visit.status_code == 200

    second_visit = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "visit_date": "2026-05-20",
            "state": "m1_crpc",
            "management_track": "on_docetaxel",
            "disease_status": "Cambio por progresión",
            "current_treatment": "Docetaxel + ADT",
            "line_of_therapy_number": 2,
            "line_of_therapy_context": "mCRPC_post_ARPI_pre_taxane",
            "drug_scheme": "ADT_DOCETAXEL_DAROLUTAMIDE",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "psa": 6.2,
            "testosterone": 16,
        },
    )
    assert second_visit.status_code == 200

    import tracking_db
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    refreshed = tracking_db.get_patient_full_record("46565656565")
    assert [event["event_type"] for event in refreshed["patient_events"]][:2] == ["therapy_line_changed", "followup_visit_recorded"]
    assert refreshed["treatments"][0]["outcome"] == "Changed"
    assert refreshed["treatments"][0]["end_date"] == "2026-05-20"
    assert refreshed["treatments"][-1]["line_of_therapy_number"] == 2

    profile = build_patient_profile_view_model(
        patient=refreshed,
        latest_assessment_raw=refreshed.get("latest_assessment") or {},
        latest_assessment=refreshed.get("latest_assessment") or {},
        state_timeline=refreshed.get("state_timeline") or [],
        care_overlays=refreshed.get("care_overlays") or [],
        recommendations={},
    )
    line_segments = profile["psa_observability"]["line_segments"]
    assert len(line_segments) >= 2
    assert any(segment["line_of_therapy_number"] == 2 for segment in line_segments)
    assert profile["psa_observability"]["metrics"]["current_line_label"].startswith("L2")


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


def test_schedule_uses_track_anchor_dates_and_fallbacks(app_client):
    client, db_path = app_client

    post_rp = client.post("/api/register_patient", json=make_patient_payload(nss="55555555555", full_name="Post RP"))
    patient_id = post_rp.get_json()["patient_id"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        ("post_prostatectomy", patient_id),
    )
    cursor.execute(
        '''
        INSERT INTO surgical_details (patient_id, surgery_date, surgery_type)
        VALUES (?, ?, ?)
        ''',
        (patient_id, "2026-01-10", "RP_robotica"),
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/patients/{patient_id}/schedule")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["anchor_date"] == "2026-01-10"
    assert payload["anchor_source"] == "surgical_details.surgery_date"

    arpi = client.post("/api/register_patient", json=make_patient_payload(nss="55555555556", full_name="ARPI"))
    arpi_id = arpi.get_json()["patient_id"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE prior_clinical_history SET current_state = ? WHERE patient_id = ?",
        ("m1_crpc", arpi_id),
    )
    cursor.execute(
        '''
        INSERT INTO treatment_history (patient_id, line_of_therapy, drug_scheme, start_date, outcome)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (arpi_id, 1, "ADT_ABIRATERONE", "2026-02-01", "Ongoing"),
    )
    conn.commit()
    conn.close()

    arpi_schedule = client.get(f"/api/patients/{arpi_id}/schedule")
    assert arpi_schedule.status_code == 200
    arpi_payload = arpi_schedule.get_json()
    assert arpi_payload["management_track"] == "on_arpi"
    assert arpi_payload["anchor_date"] == "2026-02-01"
    assert arpi_payload["anchor_source"] == "treatment_history.start_date"

    fallback = client.post("/api/register_patient", json=make_patient_payload(nss="55555555557", full_name="Fallback"))
    fallback_id = fallback.get_json()["patient_id"]
    fallback_schedule = client.get(f"/api/patients/{fallback_id}/schedule")
    assert fallback_schedule.status_code == 200
    fallback_payload = fallback_schedule.get_json()
    assert fallback_payload["anchor_date"]
    assert fallback_payload["anchor_source"] == "identity.diagnosis_date"


def test_response_assessment_parses_boolean_strings_and_validates_required_fields(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="66666666666", full_name="Respuesta"))
    patient_id = register.get_json()["patient_id"]

    valid = client.post(
        f"/api/patients/{patient_id}/response-assessment",
        json={
            "soft_tissue": {
                "current_sum_mm": 70,
                "baseline_sum_mm": 100,
                "new_lesions": "false",
                "non_target_progression": "0",
            },
            "psa": {
                "baseline_psa": 10,
                "current_psa": 4,
                "confirmed": "yes",
            },
        },
    )
    assert valid.status_code == 200
    response = valid.get_json()["response"]
    assert response["soft_tissue"]["category"] == "PR"
    assert response["soft_tissue"]["new_lesions"] is False
    assert response["psa"]["confirmed"] is True

    invalid = client.post(
        f"/api/patients/{patient_id}/response-assessment",
        json={"soft_tissue": {"current_sum_mm": 40}},
    )
    assert invalid.status_code == 400
    assert "baseline_sum_mm" in invalid.get_json()["error"]


def test_tumor_board_reads_genomics_and_demographics_correctly(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="77777777779", full_name="Tumor Board"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO patient_demographics (patient_id, charlson_score, g8_score, frailty_status)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(patient_id) DO UPDATE SET
            charlson_score = excluded.charlson_score,
            g8_score = excluded.g8_score,
            frailty_status = excluded.frailty_status
        ''',
        (patient_id, 4, 11.5, "vulnerable"),
    )
    cursor.execute(
        '''
        INSERT INTO genomic_profile (patient_id, test_date, test_type, brca2_status, actionable_findings)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (patient_id, "2026-03-01", "FoundationOne", "Mutado", json.dumps(["BRCA2"])),
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/patients/{patient_id}/tumor-board")
    assert response.status_code == 200
    tumor_board = response.get_json()["tumor_board"]
    assert tumor_board["patient_summary"]["charlson_score"] == 4
    assert tumor_board["patient_summary"]["g8_score"] == 11.5
    assert tumor_board["patient_summary"]["frailty_status"] == "vulnerable"
    assert tumor_board["genomic_profile"]["available"] is True
    assert tumor_board["genomic_profile"]["brca2"] == "Mutado"


def test_response_visualization_falls_back_to_followups_and_stage_visit_writes_biomarkers(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="88888888889", full_name="Visualización"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE patient_identity SET diagnosis_date = ? WHERE id = ?", ("2025-12-01", patient_id))
    cursor.execute(
        '''
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, visit_bundle_json, visit_type, state_at_visit, management_track, agenda_context_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            patient_id,
            "2026-03-01",
            5.2,
            json.dumps({}),
            "stage_followup",
            "diagnostic_workup",
            "diagnostic_surveillance",
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    visualization = client.post(f"/api/patients/{patient_id}/response-visualization")
    assert visualization.status_code == 200
    points = visualization.get_json()["visualization"]["psa_trajectory"]["points"]
    assert points
    assert points[-1]["psa"] == 5.2

    register_tracking = client.post("/api/register_patient", json=make_patient_payload(nss="88888888890", full_name="Tracking"))
    tracking_id = register_tracking.get_json()["patient_id"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE patient_identity SET diagnosis_date = ? WHERE id = ?", ("2025-12-01", tracking_id))
    conn.commit()
    conn.close()

    schedule = client.get(f"/api/patients/{tracking_id}/schedule")
    assert schedule.status_code == 200
    assert schedule.get_json()["schedule"]

    visit = client.post(
        f"/api/patients/{tracking_id}/visits",
        json={
            "visit_date": "2026-03-15",
            "state": "diagnostic_workup",
            "management_track": "diagnostic_surveillance",
            "disease_status": "Seguimiento estable",
            "psa": 4.8,
            "testosterone": 22,
            "hemoglobin": 13.1,
            "creatinine": 0.9,
            "ldh": 180,
            "alp": 95,
            "bilirubin": 0.7,
            "glucose": 99,
        },
    )
    assert visit.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM biomarker_longitudinal WHERE patient_id = ? AND biomarker_type = 'PSA'", (tracking_id,))
    assert cursor.fetchone()[0] >= 1
    cursor.execute("SELECT COUNT(*) FROM scheduled_events WHERE patient_id = ? AND event_type = 'psa' AND completed = 1", (tracking_id,))
    assert cursor.fetchone()[0] >= 1
    conn.close()


def test_profile_compass_promotes_parallel_copilot_layers_into_active_orientation(app_client):
    client, _ = app_client
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    register_response = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="90909090909", full_name="Paciente Copilot Avanzado"),
    )
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    patient = {
        "identity": {
            "id": patient_id,
            "diagnosis_date": "2026-01-01",
            "age": 78,
            "sex": "M",
        },
        "baseline": {
            "baseline_psa": 32.0,
            "metastasis_site": "Bone",
            "ecog_score": 2,
            "institution": "IMSS",
        },
        "prior_history": {
            "current_state": "m1_crpc",
            "prior_adt": 1,
            "prior_therapy": "Enzalutamida, Docetaxel",
            "current_adt_context": "medical_adt_continuous",
        },
        "follow_ups": [
            {
                "visit_date": "2026-03-01",
                "psa_current": 28.0,
                "testosterone_current": 18.0,
                "creatinine_current": 1.8,
                "bilirubin_current": 2.2,
                "albumin_current": 3.0,
                "inr_current": 1.8,
                "ecog_current": 2,
                "fatigue_score": 8,
                "fatigue_score_previous": 5,
                "pain_score": 8,
                "pain_score_previous": 4,
                "eq5d_vas": 35,
                "eq5d_vas_previous": 60,
                "current_treatment": "Enzalutamida",
                "current_medications": "Tramadol, Warfarina",
                "institution": "IMSS",
            }
        ],
        "genomics": {
            "ar_v7_status": "Positivo",
            "tp53_status": "Mutado",
            "rb1_status": "Loss",
            "pten_loss": "Loss",
            "cdk12_status": "Biallelic",
            "tmb_value": 12,
            "ctdna_rising": "1",
        },
        "lesion_tracking": [
            {
                "lesion_id": "L1",
                "anatomical_location": "bone",
                "psma_avid": "1",
                "current_status": "new",
                "measurements": [
                    {
                        "suvmax": 12.5,
                        "longest_diameter_mm": 18,
                    }
                ],
            }
        ],
        "response_assessments": [
            {
                "overall_response": "PD",
                "assessment_date": "2026-03-10",
            }
        ],
        "state_timeline": [
            {
                "management_intent_status_label": "Delivered",
                "event_kind_label": "Therapy review",
            }
        ],
        "family_history": [],
        "biopsies": [],
        "imaging": [],
        "mri_facts": [],
        "diagnostic_plans": [],
        "biopsy_triggers": [],
        "pros": [],
        "treatments": [{"drug_scheme": "Enzalutamida", "start_date": "2026-01-15"}],
        "care_overlays": [],
        "pivotal_matches": [],
        "stage_visits": [],
        "agenda_items": [],
        "data_provenance": [],
        "source_documents": [],
        "document_verification_tasks": [],
        "document_candidates": [],
        "verified_document_facts": [],
        "latest_signal_snapshot": {},
        "transition_proposals": [],
        "recommendation_audit": [],
    }

    latest_assessment = {
        "state": "m1_crpc",
        "module_label": "CRPC metastásico",
        "display_result": {
            "nccn_primary": {
                "label": "CRPC metastásico",
                "trayectoria_recomendada": "Priorizar secuenciación sistémica guiada por biomarcadores y seguridad.",
                "fundamentos_personalizados": ["Existe progresión reciente y biología accionable."],
            },
            "monitoring_plan": {
                "cadence": "Laboratorios y revisión clínica cada 4 semanas.",
                "actions": ["Control laboratorial estrecho mientras se redefine la línea."],
            },
            "decision_quality": {
                "confidence_category": "vigilada",
            },
            "decision_changing_inputs": ["Confirmar elegibilidad PSMA y tolerancia a quimioterapia."],
            "source_citations": [],
        },
    }
    latest_assessment_raw = {
        "input_snapshot": {
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
        },
        "result_snapshot": {
            "eligible_treatments": [{"name": "Cabazitaxel", "priority": "preferred"}],
            "validated_algorithms": [],
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=latest_assessment_raw,
        latest_assessment=latest_assessment,
        state_timeline=patient["state_timeline"],
        care_overlays=[],
        recommendations={},
    )

    labels = {item["label"] for item in profile["clinical_compass"]["active_modifiers"]}
    assert "Fitness terapéutica" in labels
    assert "Biología accionable" in labels
    assert "Interacciones / formulario" in labels
    assert "Resultados reportados por el paciente" in labels
    assert "Respuesta terapéutica" in labels
    assert any(panel["title"] == "Modificadores activos del copilot" for panel in profile["stage_specific_panels"])
    assert any(
        "triplete" in item.lower() or "monoterapia" in item.lower() or "ajustar intensidad" in item.lower()
        for item in profile["clinical_compass"]["what_could_change_course"]
    )


def test_schedule_endpoint_uses_same_cadence_as_visible_agenda(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="45454545454", full_name="Paciente Calendario")

    register_response = client.post("/api/register_patient", json=payload)
    assert register_response.status_code == 200
    patient_id = register_response.get_json()["patient_id"]

    agenda_response = client.get(f"/api/patients/{payload['nss']}/agenda")
    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")

    assert agenda_response.status_code == 200
    assert schedule_response.status_code == 200

    agenda_items = agenda_response.get_json()["agenda"]["items"]
    schedule_payload = schedule_response.get_json()
    schedule_items = schedule_payload["schedule"]

    agenda_pairs = sorted((item["title"], item["due_at"]) for item in agenda_items)
    schedule_pairs = sorted((item["label"], item["due_date"]) for item in schedule_items)

    assert agenda_pairs == schedule_pairs
    assert schedule_payload["protocol_trace"]["anchor_date"]
    assert schedule_payload["protocol_label"]


def test_profile_view_model_builds_advanced_context_and_evidence_applicability():
    from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

    patient = {
        "identity": {
            "id": 1,
            "full_name": "Paciente CRPC",
            "nss": "90909090909",
            "diagnosis_date": "2025-01-10",
            "dob": "1960-01-01",
            "age": 66,
        },
        "baseline": {
            "baseline_psa": 24.3,
            "ecog_score": 1,
            "metastasis_site": "Bone",
            "hrr_status": "BRCA2 mutado",
            "msi_status": "estable",
        },
        "prior_history": {
            "line_of_therapy": 2,
            "prior_adt": 1,
        },
        "follow_ups": [
            {
                "visit_date": "2026-03-01",
                "ecog": 1,
                "fatigue_score": 4,
                "cv_risk_documented": 1,
                "drug_interaction_reviewed": 1,
            }
        ],
        "treatments": [
            {
                "start_date": "2026-02-01",
                "drug_scheme": "ADT_ENZALUTAMIDE",
            }
        ],
        "imaging": [
            {
                "study_date": "2026-02-10",
                "study_type": "PSMA-PET",
            }
        ],
        "genomics": {
            "hrr_overall": "BRCA2 mutado",
            "msi_status": "estable",
            "report_date": "2026-02-05",
        },
        "care_overlays": [{"title": "Bundle óseo activo"}],
        "pivotal_matches": [
            {
                "study_name": "VISION",
                "scenario": "mCRPC",
                "eligible": 1,
                "evaluation_date": "2026-03-05",
                "expected_outcome": "rPFS y control clínico con Lu-177 PSMA.",
                "eligibility_details": json.dumps(
                    {
                        "match_score": 0.92,
                        "criteria_met": ["PSMA positivo", "mCRPC post-ARPI"],
                        "criteria_failed": ["Sin taxano previo documentado"],
                    }
                ),
                "applicability": "Alta aplicabilidad clínica en mCRPC PSMA positivo.",
            }
        ],
        "pros": [],
        "agenda_items": [],
        "data_provenance": [],
        "transition_proposals": [],
        "recommendation_audit": [],
        "document_candidates": [],
        "document_verification_tasks": [],
        "verified_document_facts": [],
        "source_documents": [],
        "latest_signal_snapshot": {},
    }
    latest_assessment_raw = {
        "assessment_date": "2026-03-05",
        "input_snapshot": {
            "line_of_therapy": 2,
            "drug_scheme": "ADT_ENZALUTAMIDE",
            "castrate_testosterone_status": "confirmed_castrate",
            "conventional_imaging_status": "M1",
            "psma_positive": 1,
            "cv_risk_documented": 1,
        },
        "result_snapshot": {
            "eligible_treatments": [{"name": "Lutetio-177 PSMA"}, {"name": "Olaparib"}],
            "decision_changing_inputs": ["PSMA positivo", "BRCA2 mutado"],
        },
    }
    latest_assessment = {
        "state": "m1_crpc",
        "module_label": "CRPC metastásico",
        "display_result": {
            "nccn_primary": {
                "titulo_clinico": "Secuenciación basada en PSMA y biomarcadores",
                "label": "CRPC metastásico",
                "trayectoria_recomendada": "Priorizar terapia dirigida por PSMA/HRR.",
            },
            "decision_changing_inputs": ["PSMA positivo", "BRCA2 mutado"],
            "decision_quality": {"confidence_category": "alta", "recommendation_family": "mCRPC"},
            "source_citations": [],
        },
    }

    profile = build_patient_profile_view_model(
        patient=patient,
        latest_assessment_raw=latest_assessment_raw,
        latest_assessment=latest_assessment,
        state_timeline=[{"management_intent_status_label": "Pendiente de confirmación", "event_kind_label": "Recomendación generada"}],
        care_overlays=patient["care_overlays"],
    )

    assert profile["advanced_panel_context"]["sequencing_context"]["items"]
    assert profile["advanced_panel_context"]["biomarker_context"]["items"]
    assert profile["advanced_panel_context"]["safety_support_context"]["items"]
    assert profile["evidence_applicability"]["supporting_trials"]
    assert profile["evidence_applicability"]["supporting_trials"][0]["study_name"] == "VISION"


def test_patient_profile_hides_persisted_state_timeline_ui(app_client):
    client, _ = app_client
    payload = make_patient_payload(nss="56565656565", full_name="Paciente Perfil")
    register_response = client.post("/api/register_patient", json=payload)
    assert register_response.status_code == 200

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)
    assert "Línea de estados clínicos persistidos" not in html


def test_reconciled_state_moves_systemic_patient_out_of_diagnostic_lane(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="91919191919", full_name="Paciente Reconciliado"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-15",
            2.5,
            30.0,
            "Abiraterona + ADT",
            "Respuesta Parcial",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    assert signals_payload["signals"]["reconciled_state"] == "adt_progression_verification"
    assert signals_payload["signals"]["state_conflict_flag"] is True

    agenda_response = client.get("/api/patients/91919191919/agenda")
    assert agenda_response.status_code == 200
    agenda = agenda_response.get_json()["agenda"]
    assert agenda["management_track"] == "on_arpi"
    titles = [item["title"] for item in agenda["items"]]
    assert any("Bundle de seguridad ARPI" in title for title in titles)
    assert all("Biopsia" not in title for title in titles)

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["reconciled_state"] == "adt_progression_verification"
    assert schedule_payload["state_conflict_flag"] is True


def test_reconciled_state_keeps_low_volume_mcspc_low_when_systemic_doublet_is_used(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="91919191918", full_name="Paciente mHSPC bajo volumen")
    payload.update(
        {
            "tnm_stage": "TxN0M1b",
            "metastasis_site": "Bone",
            "metastasis_count": 3,
            "volume_disease": "Low",
            "bone_metastasis_present": 1,
            "bone_ribs_thorax_count": 1,
            "bone_femur_count": 2,
            "bone_axial_count": 1,
            "bone_appendicular_count": 2,
            "metastasis_assessment_date": "2026-03-16",
            "metastasis_document_source": "PSMA-PET",
        }
    )
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO follow_up_visits (
            patient_id, visit_date, psa_current, testosterone_current, current_treatment,
            disease_status, ecog_current, agenda_context_json, visit_bundle_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            "2026-03-16",
            4.2,
            32.0,
            "ADT + Abiraterona",
            "Respuesta Parcial",
            1,
            json.dumps({}),
            json.dumps({}),
        ),
    )
    conn.commit()
    conn.close()

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()["signals"]
    assert signals_payload["reconciled_state"] == "mcspc_low_volume_sync_oligo"
    assert signals_payload["supporting_evidence"]["metastasis_count"] == 3

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["reconciled_state"] == "mcspc_low_volume_sync_oligo"


def test_agenda_endpoint_separates_active_and_archived_items(app_client):
    client, _ = app_client
    register_response = client.post("/api/register_patient", json=make_patient_payload(nss="92929292929", full_name="Paciente Agenda Archivada"))
    patient_id = register_response.get_json()["patient_id"]

    agenda_before = client.get("/api/patients/92929292929/agenda").get_json()["agenda"]
    assert agenda_before["active_items"]
    agenda_item = agenda_before["active_items"][0]

    complete_response = client.post(f"/api/patients/{patient_id}/agenda/{agenda_item['id']}/complete", json={})
    assert complete_response.status_code == 200

    agenda_after = client.get("/api/patients/92929292929/agenda").get_json()["agenda"]
    assert all(item["id"] != agenda_item["id"] for item in agenda_after["active_items"])
    assert any(item["id"] == agenda_item["id"] for item in agenda_after["archived_items"])


def test_dashboard_stats_and_analysis_exports_include_research_readiness(app_client):
    client, _ = app_client
    client.post("/api/register_patient", json=make_patient_payload(nss="93939393939", full_name="Paciente Cohorte"))

    dashboard = client.get("/api/dashboard_stats")
    assert dashboard.status_code == 200
    payload = dashboard.get_json()
    assert "cohort_completeness" in payload
    assert "research_readiness" in payload
    assert "endpoint_readiness" in payload

    dataset = client.get("/api/analysis_dataset_export")
    assert dataset.status_code == 200
    assert isinstance(dataset.get_json()["analysis_dataset_export"], list)

    completeness = client.get("/api/cohort_completeness")
    assert completeness.status_code == 200
    assert "cohort_completeness" in completeness.get_json()

    readiness = client.get("/api/research_readiness")
    assert readiness.status_code == 200
    assert "research_readiness" in readiness.get_json()

    endpoint = client.get("/api/endpoint_readiness")
    assert endpoint.status_code == 200
    assert "endpoint_readiness" in endpoint.get_json()


def test_tnm_engine_maps_case_specific_real_stage_images():
    assembled = TNMEngine.assemble({"clinical_tstage": "T2b"})
    assert assembled["t_data"]["image"] == "real_stage/t2b_real.png"

    assembled_upper = TNMEngine.assemble({"clinical_tstage": "T2B"})
    assert assembled_upper["t_data"]["image"] == "real_stage/t2b_real.png"

    assembled_composite = TNMEngine.assemble({"tnm_stage": "T2cN0M0"})
    assert assembled_composite["t_data"]["image"] == "real_stage/t2c_real.png"


def test_tnm_engine_uses_real_stage_images_for_n1_and_m1():
    assembled = TNMEngine.assemble({"tnm_stage": "T4N1M1"})
    assert assembled["t_data"]["image"] == "real_stage/t4_real.png"
    assert assembled["n_data"]["image"] == "real_stage/n1_real.png"
    assert assembled["m_data"]["image_src"].startswith("data:image/svg+xml")


def test_tnm_engine_resolves_metastatic_substages_from_structured_distribution():
    nodal = TNMEngine.assemble(
        {
            "nonregional_nodal_metastasis_present": 1,
            "nonregional_nodal_retroperitoneal_count": 2,
        }
    )
    assert nodal["m_stage"] == "M1a"
    assert nodal["m_data"]["image_src"].startswith("data:image/svg+xml")

    bone = TNMEngine.assemble(
        {
            "bone_metastasis_present": 1,
            "bone_femur_count": 2,
            "bone_ribs_thorax_count": 1,
        }
    )
    assert bone["m_stage"] == "M1b"
    assert "fémur" in bone["m_data"]["summary"].lower()

    visceral = TNMEngine.assemble(
        {
            "visceral_metastasis_present": 1,
            "visceral_lung_count": 2,
            "visceral_liver_count": 1,
        }
    )
    assert visceral["m_stage"] == "M1c"
    assert visceral["m_data"]["image_src"].startswith("data:image/svg+xml")
