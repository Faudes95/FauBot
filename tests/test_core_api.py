import csv
import io
import json
import sqlite3

from prostanet.shared.tnm_engine import TNMEngine
from prostanet.shared.official_diagnosis import build_official_diagnosis_context


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


def _seed_latest_assessment_state(db_path, patient_id, state, module_id=None):
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


def _insert_postlocal_bcr_context(db_path, patient_id, *, surgery_date="2024-01-15", bcr_date="2026-03-01", bcr_psa=0.42, psadt=8.0):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO surgical_details (
            patient_id, surgery_date, surgery_type, pathological_stage
        ) VALUES (?, ?, 'RP_robotica', 'pT2')
        """,
        (patient_id, surgery_date),
    )
    cursor.execute(
        """
        INSERT INTO biochemical_recurrence (
            patient_id, primary_treatment, primary_treatment_date, bcr_detected,
            bcr_date, bcr_psa, bcr_definition, psadt_at_bcr
        ) VALUES (?, 'RP', ?, 1, ?, ?, 'AUA_0.2', ?)
        """,
        (patient_id, surgery_date, bcr_date, bcr_psa, psadt),
    )
    conn.commit()
    conn.close()


def _insert_treatment_line(db_path, patient_id, *, line_of_therapy, drug_scheme, start_date, end_date=None, context="metastatic"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO treatment_history (
            patient_id, line_of_therapy, drug_scheme, start_date, end_date, outcome, regimen_json, line_of_therapy_context
        ) VALUES (?, ?, ?, ?, ?, 'Ongoing', ?, ?)
        """,
        (
            patient_id,
            line_of_therapy,
            drug_scheme,
            start_date,
            end_date,
            json.dumps(
                {
                    "line_of_therapy_number": line_of_therapy,
                    "drug_scheme": drug_scheme,
                    "drug_scheme_label": drug_scheme,
                    "line_of_therapy_context": context,
                }
            ),
            context,
        ),
    )
    conn.commit()
    conn.close()


def _insert_psa_longitudinal_points(db_path, patient_id, points):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for sample_date, value in points:
        cursor.execute(
            """
            INSERT INTO biomarker_longitudinal (
                patient_id, biomarker_type, value, unit, sample_date, lab_source
            ) VALUES (?, 'PSA', ?, 'ng/mL', ?, 'unit_test')
            """,
            (patient_id, value, sample_date),
        )
    conn.commit()
    conn.close()


def _update_patient_contact_status(
    db_path,
    patient_id,
    *,
    last_contact_date="2026-03-15",
    last_contact_status="alive",
    vital_status="alive",
):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE patient_identity
        SET last_contact_date = ?, last_contact_status = ?, vital_status = ?
        WHERE id = ?
        """,
        (last_contact_date, last_contact_status, vital_status, patient_id),
    )
    conn.commit()
    conn.close()


def _insert_genomic_profile(db_path, patient_id, *, test_date="2026-03-05", hrr="Positivo", brca2="Positivo", msi="Estable"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO genomic_profile (
            patient_id, test_date, test_type, brca2_status, msi_status, hrr_overall
        ) VALUES (?, ?, 'Panel_HRR', ?, ?, ?)
        """,
        (patient_id, test_date, brca2, msi, hrr),
    )
    conn.commit()
    conn.close()


def _insert_psma_imaging(db_path, patient_id, *, study_date="2026-03-07", psma_positive=True):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO imaging_studies (
            patient_id, study_date, study_type, psma_result, findings_json
        ) VALUES (?, ?, 'PSMA PET/CT', ?, ?)
        """,
        (
            patient_id,
            study_date,
            "positivo" if psma_positive else "negativo",
            json.dumps(
                {
                    "lesion_locations": ["hueso", "ganglios"],
                    "psma_total_lesions": 2,
                }
            ),
        ),
    )
    conn.commit()
    conn.close()


def _update_latest_assessment_input(db_path, patient_id, payload):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, input_snapshot
        FROM clinical_assessments
        WHERE patient_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (patient_id,),
    )
    row = cursor.fetchone()
    if row is None:
        conn.close()
        raise AssertionError("No latest assessment found to update")
    current_snapshot = json.loads(row[1] or "{}")
    current_snapshot.update(payload)
    cursor.execute(
        "UPDATE clinical_assessments SET input_snapshot = ? WHERE id = ?",
        (json.dumps(current_snapshot), row[0]),
    )
    conn.commit()
    conn.close()


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


def test_stage_visit_persists_survival_status_and_anchor_events(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="30000000001", full_name="Supervivencia Demo")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_date="2026-02-20", bcr_psa=0.55)

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "state": "recurrence_bcr",
            "visit_date": "2026-03-15",
            "psa": 0.62,
            "survival_status_update": {
                "vital_status": "alive",
                "last_contact_date": "2026-03-15",
                "last_contact_status": "clinic_visit",
            },
            "survival_anchor_events": [
                {"anchor_type": "psa_progression", "anchor_date": "2026-02-20", "anchor_source": "biochemical_recurrence"},
                {"anchor_type": "treatment_start", "anchor_date": "2024-01-15", "anchor_source": "surgery"},
            ],
        },
    )

    assert visit_response.status_code == 200
    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id)
    assert record["survival_status_detail"]["vital_status"] == "alive"
    assert record["survival_status_detail"]["last_contact_date"] == "2026-03-15"
    anchor_types = {item["anchor_type"] for item in record["survival_anchor_events"]}
    assert "psa_progression" in anchor_types
    assert "treatment_start" in anchor_types

    survival_response = client.get(f"/api/patients/{patient_id}/survival-endpoints")
    assert survival_response.status_code == 200
    survival_data = survival_response.get_json()["survival_status"]
    endpoint_types = {item["type"] for item in survival_data["endpoints"]}
    assert "OS" in endpoint_types
    assert "TTR" in endpoint_types
    assert "BCR_FS" in endpoint_types


def test_stage_visit_persists_structured_biopsy_and_active_surveillance(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="30000000002", full_name="Biopsia VA Demo")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "state": "localized_initial",
            "visit_date": "2026-03-10",
            "structured_biopsy": {
                "biopsy_date": "2026-03-01",
                "biopsy_type": "fusion",
                "biopsy_route": "transperineal",
                "biopsy_context": "confirmatory_as",
                "mri_pirads_at_biopsy": 4,
                "systematic_cores": [
                    {"core_id": "S1", "location_sextant": "right_base", "core_type": "systematic", "positive": True, "gleason_primary": 3, "gleason_secondary": 3, "isup_grade": 1, "involvement_pct": 20},
                    {"core_id": "S2", "location_sextant": "left_base", "core_type": "systematic", "positive": False},
                ],
                "targeted_cores": [
                    {"core_id": "T1", "location_sextant": "target_1", "core_type": "targeted", "positive": True, "gleason_primary": 3, "gleason_secondary": 4, "isup_grade": 2, "mri_target_concordance": True}
                ],
            },
            "active_surveillance_update": {
                "protocol": "PRIAS",
                "criteria_met": {"isup_max": True},
                "schedule_items": [
                    {"item_type": "psa", "title": "PSA protocolizado", "due_date": "2026-06-01", "interval_months": 3, "status": "scheduled", "priority": "mandatory"},
                    {"item_type": "rebiopsy", "title": "Biopsia confirmatoria", "due_date": "2027-03-01", "interval_months": 12, "status": "scheduled", "priority": "mandatory"},
                ],
                "trigger_events": [
                    {"trigger_type": "mri_new_lesion", "detected_date": "2026-03-10", "detail": "Lesión índice PI-RADS 4", "severity": "monitoring_intensification", "recommended_action": "Mantener vigilancia intensificada"}
                ],
            },
        },
    )

    assert visit_response.status_code == 200
    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id)
    assert len(record["structured_biopsy_sessions"]) == 1
    assert record["structured_biopsy_sessions"][0]["biopsy_context"] == "confirmatory_as"
    assert record["structured_biopsy_sessions"][0]["targeted_cores"][0]["positive"] is True
    assert record["active_surveillance_protocol"]["enrollment_protocol"] == "PRIAS"
    assert len(record["active_surveillance_protocol"]["schedule"]) == 2
    assert len(record["active_surveillance_protocol"]["reclassification_triggers"]) == 1

    as_response = client.get(f"/api/patients/{patient_id}/active-surveillance")
    assert as_response.status_code == 200
    protocol_summary = as_response.get_json()["protocol_summary"]
    assert protocol_summary["has_data"] is True


def test_stage_visit_persists_sre_bma_bone_health_and_rt_detail(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="30000000003", full_name="Hueso RT Demo")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(db_path, patient_id, line_of_therapy=1, drug_scheme="ADT_ABIRATERONE", start_date="2025-12-01", context="mcrpc")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "state": "m1_crpc",
            "visit_date": "2026-03-12",
            "skeletal_events": [
                {"event_type": "pathological_fracture", "event_date": "2026-03-05", "site": "femur", "intervention": "stabilization", "surgical_intervention": True},
            ],
            "bone_modifying_agent": {
                "agent": "denosumab",
                "start_date": "2026-03-12",
                "frequency": "q4w",
                "dental_clearance_done": True,
                "onj_monitoring": True,
                "doses_administered": 1,
            },
            "bone_health_snapshot": {
                "snapshot_date": "2026-03-12",
                "dxa_performed": True,
                "worst_t_score": -2.7,
                "frax_major_pct": 18.0,
                "frax_hip_pct": 5.2,
                "calcium_level": 9.1,
                "creatinine": 1.0,
            },
            "radiotherapy_course": {
                "rt_intent": "MDT",
                "modality": "SBRT",
                "target_volume": "metastasis_directed",
                "total_dose_gy": 30,
                "fractions": 3,
                "dose_per_fraction_gy": 10,
                "rt_start_date": "2026-03-20",
                "rt_end_date": "2026-03-24",
                "mdt_site_details": [
                    {"site_location": "left_iliac_bone", "modality": "SBRT", "dose_gy": 30, "fractions": 3, "dose_per_fraction_gy": 10}
                ],
                "toxicity": [
                    {"domain": "GI", "phase": "acute", "grade": 1, "details": "Nausea leve"}
                ],
            },
        },
    )

    assert visit_response.status_code == 200
    import tracking_db

    record = tracking_db.get_patient_full_record(patient_id)
    assert len(record["skeletal_events"]) == 1
    assert record["bone_modifying_agent"]["agent"] == "denosumab"
    assert record["bone_health"]["worst_t_score"] == -2.7
    assert len(record["radiotherapy_courses_detailed"]) == 1
    assert record["radiotherapy_courses_detailed"][0]["mdt_site_details"][0]["site_location"] == "left_iliac_bone"

    sre_response = client.get(f"/api/patients/{patient_id}/skeletal-events")
    rt_response = client.get(f"/api/patients/{patient_id}/radiotherapy-detail")
    assert sre_response.status_code == 200
    assert rt_response.status_code == 200


def test_legacy_domain_writes_dual_write_into_canonical_tables(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="30000000004", full_name="Legacy Backfill Demo")
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]

    import tracking_db

    assert tracking_db.save_biopsy(patient_id, {
        "biopsy_date": "2026-02-01",
        "biopsy_type": "fusion",
        "biopsy_context": "diagnostica",
        "total_cores": 12,
        "positive_cores": 2,
        "gleason_primary": 3,
        "gleason_secondary": 4,
        "isup_grade": 2,
    }) is True
    assert tracking_db.enroll_in_as(patient_id, {
        "enrollment_date": "2026-02-15",
        "protocol": "PRIAS",
        "criteria_met": {"psa_max": True},
    }) is True
    assert tracking_db.save_radiation_details(patient_id, {
        "rt_date": "2026-02-20",
        "rt_context": "salvamento",
        "rt_technique": "VMAT",
        "target": "lecho",
        "total_dose_gy": 66,
        "fractions": 33,
        "dose_per_fraction_gy": 2,
        "gu_toxicity_grade": 1,
        "gi_toxicity_grade": 0,
    }) is True

    record = tracking_db.get_patient_full_record(patient_id)
    assert len(record["structured_biopsy_sessions"]) == 1
    assert record["active_surveillance_protocol"]["enrollment_protocol"] == "PRIAS"
    assert len(record["radiotherapy_courses_detailed"]) == 1


def test_cohort_survival_and_domain_completeness_endpoints(app_client):
    client, db_path = app_client
    patient_ids = []
    for idx in range(2):
        payload = make_patient_payload(nss=f"3000000001{idx}", full_name=f"Cohorte {idx}")
        register = client.post("/api/register_patient", json=payload)
        patient_id = register.get_json()["patient_id"]
        patient_ids.append(patient_id)
        _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
        _insert_postlocal_bcr_context(db_path, patient_id, bcr_date=f"2026-02-2{idx}", bcr_psa=0.3 + idx)
        client.post(
            f"/api/patients/{patient_id}/visits",
            json={
                "state": "recurrence_bcr",
                "visit_date": f"2026-03-1{idx}",
                "survival_status_update": {
                    "vital_status": "deceased" if idx == 1 else "alive",
                    "date_of_death": "2026-03-18" if idx == 1 else "",
                    "cause_of_death": "prostate_cancer" if idx == 1 else "",
                    "last_contact_date": f"2026-03-1{idx}",
                    "last_contact_status": "clinic_visit",
                },
                "survival_anchor_events": [
                    {"anchor_type": "treatment_start", "anchor_date": "2024-01-15", "anchor_source": "surgery"},
                    {"anchor_type": "psa_progression", "anchor_date": f"2026-02-2{idx}", "anchor_source": "biochemical_recurrence"},
                ],
            },
        )

    curve_response = client.get("/api/cohorts/survival-curves?endpoint=OS")
    assert curve_response.status_code == 200
    curve_data = curve_response.get_json()
    assert curve_data["success"] is True
    assert curve_data["n_patients"] >= 2
    assert "curve" in curve_data

    analysis_response = client.get("/api/cohorts/survival-analysis?endpoint=OS")
    assert analysis_response.status_code == 200
    analysis_data = analysis_response.get_json()
    assert analysis_data["success"] is True
    assert analysis_data["status"] in {"ok", "insufficient_data", "lifelines_unavailable", "no_usable_covariates"}

    completeness_response = client.get("/api/cohorts/domain-completeness")
    assert completeness_response.status_code == 200
    completeness_data = completeness_response.get_json()
    assert completeness_data["success"] is True
    assert completeness_data["total_patients"] >= 2
    assert "domain_counts" in completeness_data

    invalid_numeric = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="22222222222") | {"line_of_therapy": "primera"},
    )
    assert invalid_numeric.status_code == 400
    invalid_data = invalid_numeric.get_json()
    assert invalid_data["success"] is False
    assert "line_of_therapy" in invalid_data["error"]


def test_clinical_hub_hides_classifier_noise_and_starts_empty(app_client):
    client, _ = app_client

    response = client.get("/clinical-hub")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Qué corrige este clasificador" not in html
    assert "Clasificar estado" not in html
    assert "Seleccione un dominio o complete el clasificador" in html
    assert "setActiveDomain(null);" in html


def test_visit_schema_includes_official_diagnosis_capture_fields(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="23232323232", full_name="Paciente Diagnóstico Oficial"))
    patient_id = register.get_json()["patient_id"]

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema")

    assert schema_response.status_code == 200
    schema = schema_response.get_json()["visit_schema"]
    field_names = {
        field["name"]
        for section in schema["sections"]
        for field in section["fields"]
    }
    for field_name in (
        "histology_subtype",
        "gleason_primary",
        "gleason_secondary",
        "isup_grade",
        "clinical_tstage",
        "nodal_status",
        "clinical_stage_group",
        "clinical_risk_group",
    ):
        assert field_name in field_names


def test_official_diagnosis_context_builds_localized_phrase_from_structured_fields(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="24242424242", full_name="Paciente Localizado Oficial") | {
        "histology_subtype": "Adenocarcinoma acinar",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "clinical_tstage": "T2b",
        "nodal_status": "N0",
        "clinical_stage_group": "IIA",
        "clinical_risk_group": "intermedio desfavorable",
    }

    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200

    import tracking_db

    record = tracking_db.get_patient_full_record(register.get_json()["patient_id"])
    context = build_official_diagnosis_context(
        patient=record,
        state="localized_initial",
        raw_assessment={},
        display_assessment={},
        operational_module_label="Enfermedad localizada o regional N1M0",
    )

    assert context["official_diagnosis_status"] == "complete"
    assert "Adenocarcinoma acinar de próstata Gleason 7 (4+3)" in context["official_diagnosis"]
    assert "riesgo intermedio desfavorable" in context["official_diagnosis"]
    assert "etapa clínica IIA" in context["official_diagnosis"]


def test_official_diagnosis_context_falls_back_to_operational_label_when_missing(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="25252525252", full_name="Paciente Fallback Diagnóstico"))
    assert register.status_code == 200

    import tracking_db

    record = tracking_db.get_patient_full_record(register.get_json()["patient_id"])
    context = build_official_diagnosis_context(
        patient=record,
        state="localized_initial",
        raw_assessment={},
        display_assessment={},
        operational_module_label="Enfermedad localizada o regional N1M0",
    )

    assert context["official_diagnosis_status"] == "missing"
    assert context["official_diagnosis"] == "Enfermedad localizada o regional N1M0"


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


def test_alerts_endpoint_matches_signals_copilot_alerts(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="34343434343", full_name="Paciente Alertas Canonicas"))
    patient_id = register.get_json()["patient_id"]

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    alerts_response = client.get(f"/api/alerts/{patient_id}")

    assert signals_response.status_code == 200
    assert alerts_response.status_code == 200

    signal_alerts = signals_response.get_json()["copilot_alerts"]
    api_alerts = alerts_response.get_json()["alerts"]

    assert signal_alerts
    assert {item["alert_key"] for item in signal_alerts} == {item["alert_key"] for item in api_alerts}


def test_schedule_persists_distinct_supportive_care_items_with_distinct_schedule_keys(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="35353535353", full_name="Paciente Schedule Keys"))
    patient_id = register.get_json()["patient_id"]

    import tracking_db

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    tracking_db._upsert_scheduled_events(
        cursor,
        patient_id,
        "systemic_surveillance",
        [
            {
                "schedule_key": "state:track:bone_support",
                "encounter_key": "encounter:support",
                "event_type": "supportive_care",
                "label": "Salud ósea y soporte",
                "management_track": "systemic_surveillance",
                "due_date": "2026-03-20",
                "guideline": "NCCN 2026",
            },
            {
                "schedule_key": "state:track:frailty_fitness",
                "encounter_key": "encounter:support",
                "event_type": "supportive_care",
                "label": "Fragilidad y fitness terapéutica",
                "management_track": "systemic_surveillance",
                "due_date": "2026-03-20",
                "guideline": "EAU 2026",
            },
        ],
    )
    conn.commit()
    cursor.execute(
        """
        SELECT id, schedule_key, label
        FROM scheduled_events
        WHERE patient_id = ?
        ORDER BY id ASC
        """,
        (patient_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0][0] != rows[1][0]
    assert {row[1] for row in rows} == {"state:track:bone_support", "state:track:frailty_fitness"}


def test_agenda_and_schedule_expose_encounters(app_client):
    client, _ = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="36363636363", full_name="Paciente Encounters"))
    patient_id = register.get_json()["patient_id"]

    agenda_response = client.get("/api/patients/36363636363/agenda")
    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")

    assert agenda_response.status_code == 200
    assert schedule_response.status_code == 200

    agenda_payload = agenda_response.get_json()["agenda"]
    schedule_payload = schedule_response.get_json()

    assert agenda_payload["encounters"]
    assert schedule_payload["scheduled_encounters"]
    assert schedule_payload["next_encounter"]


def test_adt_progression_verification_groups_confirmation_encounter_and_fuses_alerts(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="37373737373", full_name="Paciente ADT Progression"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule?track=systemic_surveillance")
    signals_response = client.get(f"/api/patients/{patient_id}/signals")

    assert schedule_response.status_code == 200
    assert signals_response.status_code == 200

    schedule_payload = schedule_response.get_json()
    encounters = schedule_payload["scheduled_encounters"]
    confirmation = next(enc for enc in encounters if enc["encounter_type"] == "progression_confirmation")

    assert confirmation["title"] == "Cita de confirmación de progresión bajo ADT"
    task_types = {task["item_type"] for task in confirmation["tasks"]}
    assert {"therapy_review", "lab_panel", "imaging"} <= task_types
    assert schedule_payload["schedule_anchor_strength"] == "weak"

    signal_alerts = signals_response.get_json()["copilot_alerts"]
    assert sum(1 for alert in signal_alerts if alert["decision_domain"] == "systemic_sequencing") <= 1


def test_schedule_exposes_master_followup_plan_for_phase_one_scenarios(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="38383838383", full_name="Paciente Plan Maestro"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule?track=systemic_surveillance")
    assert schedule_response.status_code == 200

    payload = schedule_response.get_json()
    master_plan = payload["master_followup_plan"]

    assert master_plan["scenario_state"] == "adt_progression_verification"
    assert master_plan["guideline_basis"]
    assert master_plan["next_encounter"]
    assert master_plan["summary"]["headline"]
    assert master_plan["plan_key"]
    assert master_plan["plan_status"] in {"active", "provisional"}
    assert master_plan["calendar_horizon_months"] == 12
    assert master_plan["timeline"]
    assert master_plan["inline_actions_enabled"] is True
    timeline_dates = [item["ideal_due_at"] for item in master_plan["timeline"] if item.get("ideal_due_at")]
    assert timeline_dates == sorted(timeline_dates)
    assert all("scheduled_due_at" in item for item in master_plan["timeline"])
    assert all("completion_progress" in item for item in master_plan["timeline"])
    assert all("inline_actions_enabled" in item for item in master_plan["timeline"])
    assert any(item["tasks"] for item in master_plan["timeline"])
    first_task = next(task for item in master_plan["timeline"] for task in item["tasks"])
    assert {"required", "action_mode", "completed_at"} <= set(first_task.keys())
    assert payload["plan_version"]
    assert payload["calendar_horizon_months"] == 12
    assert payload["timeline"]


def test_completed_inline_task_remains_visible_and_counts_toward_encounter_progress(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="38383838384", full_name="Paciente Progreso Encounter"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    agenda_response = client.get(f"/api/patients/{patient_id}/agenda?track=systemic_surveillance")
    assert agenda_response.status_code == 200
    agenda = agenda_response.get_json()["agenda"]
    lab_item = next(item for item in agenda["items"] if item["agenda_key"] == "adt_progression_verification:systemic_surveillance:labs")

    visit_response = client.post(
        f"/api/patients/{patient_id}/visits",
        json={
            "agenda_ids": [lab_item["id"]],
            "agenda_submission_mode": "item_scoped",
            "visit_date": "2026-03-20",
            "state": "adt_progression_verification",
            "management_track": "systemic_surveillance",
            "psa": 6.4,
            "testosterone": 18,
            "alp": 120,
            "ldh": 200,
            "hemoglobin": 13.2,
        },
    )
    assert visit_response.status_code == 200

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule?track=systemic_surveillance")
    assert schedule_response.status_code == 200
    encounter = next(
        item
        for item in schedule_response.get_json()["scheduled_encounters"]
        if item["encounter_key"] == "adt_progression_verification:systemic_surveillance:progression_confirmation"
    )
    completed_lab_task = next(task for task in encounter["tasks"] if task["agenda_key"] == lab_item["agenda_key"])

    assert encounter["completion_progress"]["label"] == "1/3"
    assert encounter["completed_required_task_count"] == 1
    assert completed_lab_task["status"] == "completed"
    assert completed_lab_task["completed_at"]


def test_alert_key_opens_directed_visit_schema_with_capture_context(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39393939393", full_name="Paciente Alerta Dirigida"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    alerts = signals_response.get_json()["copilot_alerts"]
    capture_alert = next(alert for alert in alerts if alert["fields_to_capture"])

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema?alert_key={capture_alert['alert_key']}")
    assert schema_response.status_code == 200

    payload = schema_response.get_json()
    visit_schema = payload["visit_schema"]
    agenda_context = payload["agenda_item_context"]
    field_names = {
        field["name"]
        for section in visit_schema["sections"]
        for field in section["fields"]
    }

    assert visit_schema["submission_mode"] == "item_scoped"
    assert visit_schema["presentation_mode"] == "mini_capture"
    assert visit_schema["focus_fields"] == capture_alert["fields_to_capture"]
    assert visit_schema["auto_visit_date"]
    assert visit_schema["allow_visit_date_override"] is True
    assert agenda_context["mode"] == "mini_capture"
    assert agenda_context["alert_key"] == capture_alert["alert_key"]
    assert agenda_context["action_type"] == capture_alert["action_type"]
    assert set(capture_alert["fields_to_capture"]) == field_names
    assert "visit_date" not in field_names
    assert "clinician_notes" not in field_names


def test_signals_expose_outcome_adjudication_bundle(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39494949494", full_name="Paciente Bundle Outcomes"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    followup_response = client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 6.8,
            "testosterone": 124,
            "treatment": "ADT",
            "status": "Progresión radiográfica",
        },
    )
    assert followup_response.status_code == 200

    response = client.get(f"/api/patients/{patient_id}/signals")

    assert response.status_code == 200
    payload = response.get_json()
    summary = payload["outcome_events_summary"]

    assert summary["total"] >= 1
    assert "castration_resistance" in summary["by_axis"]
    assert payload["pending_adjudications"]
    assert payload["current_course_status"]
    assert isinstance(payload["trial_comparable_endpoints"], list)


def test_bcr_without_imaging_stays_non_metastatic_and_pending_restaging(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39595959595", full_name="Paciente BCR High Risk"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.42, psadt=8.0)

    response = client.get(f"/api/patients/{patient_id}/outcomes")

    assert response.status_code == 200
    payload = response.get_json()
    event_types = {item["event_type"] for item in payload["outcome_events"]}
    pending_keys = {item["status_key"] for item in payload["pending_adjudications"]}

    assert {"bcr_detected", "high_risk_bcr", "salvage_window_open"} <= event_types
    assert "radiographic_progression" not in event_types
    assert any(key.endswith("salvage_imaging") for key in pending_keys)
    assert payload["current_trial_comparable_profile"]["benchmark_family"] == "EMBARK_like"
    assert payload["current_trial_comparable_profile"]["recommended_trial_backbone_label"] == "ADT + enzalutamida"
    assert "alto riesgo" in payload["current_course_status"].lower()


def test_crpc_not_confirmed_without_castrate_testosterone(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39696969696", full_name="Paciente CRPC Pendiente"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    followup_response = client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 6.2,
            "testosterone": 120,
            "treatment": "ADT",
            "status": "Progresión radiográfica",
        },
    )
    assert followup_response.status_code == 200

    response = client.get(f"/api/patients/{patient_id}/outcomes")

    assert response.status_code == 200
    payload = response.get_json()
    event_types = {item["event_type"] for item in payload["outcome_events"]}

    assert "crpc_confirmation_pending" in event_types
    assert "crpc_confirmed" not in event_types
    assert any("crpc_confirmation" in item["status_key"] for item in payload["pending_adjudications"])
    assert "pendiente" in payload["current_course_status"].lower()


def test_mhspc_psa_milestones_surface_trial_comparable_endpoints(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="39797979797", full_name="Paciente mHSPC Milestones")
    payload["baseline_psa"] = 100.0
    register = client.post("/api/register_patient", json=payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "mcspc_high_volume")

    followup_response = client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 5.0,
            "testosterone": 18,
            "treatment": "Abiraterona + ADT",
            "status": "Respuesta parcial",
        },
    )
    assert followup_response.status_code == 200

    response = client.get(f"/api/patients/{patient_id}/outcomes")

    assert response.status_code == 200
    payload = response.get_json()
    endpoints = {
        item["endpoint_key"]: item
        for item in payload["trial_comparable_endpoints"]
    }

    assert endpoints["psa50"]["status"] == "complete"
    assert endpoints["psa90"]["status"] == "complete"
    assert payload["current_trial_comparable_profile"]["benchmark_family"] == "ARANOTE_ARASENS_PEACE1_like"
    assert "ADT + darolutamida" in payload["current_trial_comparable_profile"]["recommended_trial_backbone_label"]
    assert "respuesta bioquímica profunda" in payload["current_course_status"].lower()


def test_m1_crpc_psmafore_like_profile_detected(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39898989898", full_name="Paciente PSMAfore"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(db_path, patient_id, {"psma_positive": "1", "m_substage_resolved": "M1b"})
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ADT_ABIRATERONE",
        start_date="2025-01-15",
        context="mCRPC_post_ARPI_pre_taxane",
    )
    _insert_psma_imaging(db_path, patient_id, psma_positive=True)

    response = client.get(f"/api/patients/{patient_id}/outcomes")

    assert response.status_code == 200
    payload = response.get_json()
    event_types = {item["event_type"] for item in payload["outcome_events"]}

    assert "psma_positive_pathway" in event_types
    assert payload["current_trial_comparable_profile"]["benchmark_family"] == "PSMAfore_like"
    assert "PSMAfore" in payload["current_trial_comparable_profile"]["matched_trials"]
    assert payload["current_trial_comparable_profile"]["recommended_trial_backbone_label"] == "Lutecio-177 PSMA-617"


def test_schedule_exposes_pending_adjudication_tasks_and_outcome_anchor(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999990", full_name="Paciente Outcome Anchor"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, patient_id, bcr_psa=0.38, psadt=7.5)

    response = client.get(f"/api/patients/{patient_id}/schedule")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["pending_adjudication_tasks"]
    assert payload["outcome_anchor"]["event_type"] in {"high_risk_bcr", "salvage_window_open", "bcr_detected"}
    assert payload["current_course_status"]


def test_cohort_benchmarks_endpoint_aggregates_trial_like_families(app_client):
    client, db_path = app_client

    bcr_register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999991", full_name="Paciente Cohorte BCR"))
    bcr_id = bcr_register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, bcr_id, "recurrence_bcr")
    _insert_postlocal_bcr_context(db_path, bcr_id, bcr_psa=0.44, psadt=8.0)

    crpc_register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999992", full_name="Paciente Cohorte PSMA"))
    crpc_id = crpc_register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, crpc_id, "m1_crpc")
    _update_latest_assessment_input(db_path, crpc_id, {"psma_positive": "1", "m_substage_resolved": "M1b"})
    _insert_treatment_line(
        db_path,
        crpc_id,
        line_of_therapy=1,
        drug_scheme="ADT_ABIRATERONE",
        start_date="2025-01-15",
        context="mCRPC_post_ARPI_pre_taxane",
    )

    response = client.get("/api/cohorts/benchmarks")

    assert response.status_code == 200
    payload = response.get_json()
    families = payload["benchmark_families"]

    assert payload["total_patients"] >= 2
    assert "EMBARK_like" in families
    assert "PSMAfore_like" in families
    assert families["EMBARK_like"]["matched"] >= 1
    assert families["PSMAfore_like"]["matched"] >= 1


def test_psa_forecast_endpoint_returns_ready_bundle_for_stable_advanced_line(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999993", full_name="Paciente Forecast Ready"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2025-10-01",
        context="mCRPC_first_line",
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2025-11-01", 1.2),
            ("2026-01-01", 1.8),
            ("2026-03-01", 2.6),
        ],
    )
    _update_patient_contact_status(db_path, patient_id, last_contact_date="2026-03-15")

    response = client.get(f"/api/patients/{patient_id}/psa-forecast")

    assert response.status_code == 200
    payload = response.get_json()
    forecast = payload["psa_forecast"]
    assert forecast["status"] in {"ready", "low_confidence"}
    assert len(forecast["forecast_points"]) == 3
    assert payload["forecast_reliability"]["confidence_label"] in {"high", "medium", "low"}


def test_psa_forecast_endpoint_suppresses_numeric_projection_when_data_is_insufficient(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="39999999994", full_name="Paciente Forecast Insuficiente"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2026-01-15",
        context="mCRPC_first_line",
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2026-02-01", 1.5),
            ("2026-03-01", 2.1),
        ],
    )

    response = client.get(f"/api/patients/{patient_id}/psa-forecast")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["psa_forecast"]["status"] == "insufficient_data"
    assert payload["psa_forecast"]["show"] is False


def test_live_benchmark_and_profile_cards_render_for_advanced_patient(app_client):
    client, db_path = app_client
    target_payload = make_patient_payload(nss="39999999995", full_name="Paciente Benchmark Vivo")
    register = client.post("/api/register_patient", json=target_payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2025-06-01",
        context="mCRPC_first_line",
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2025-10-01", 1.0),
            ("2025-12-01", 1.4),
            ("2026-03-01", 2.0),
        ],
    )
    _update_patient_contact_status(db_path, patient_id, last_contact_date="2026-03-15")

    for idx in range(10):
        comparator = client.post(
            "/api/register_patient",
            json=make_patient_payload(nss=f"4999999999{idx}", full_name=f"Comparator {idx}"),
        )
        comparator_id = comparator.get_json()["patient_id"]
        _seed_latest_assessment_state(db_path, comparator_id, "m1_crpc")
        _insert_treatment_line(
            db_path,
            comparator_id,
            line_of_therapy=1,
            drug_scheme="ENZALUTAMIDE",
            start_date=f"2025-0{(idx % 6) + 1}-01",
            context="mCRPC_first_line",
        )
        _insert_psa_longitudinal_points(
            db_path,
            comparator_id,
            [
                ("2025-09-01", 0.9 + idx * 0.05),
                ("2025-12-01", 1.1 + idx * 0.05),
                ("2026-03-01", 1.5 + idx * 0.06),
            ],
        )
        _update_patient_contact_status(db_path, comparator_id, last_contact_date="2026-03-15")

    benchmark_response = client.get(f"/api/patients/{patient_id}/live-benchmark")
    profile_response = client.get(f"/patient_profile/{target_payload['nss']}")

    assert benchmark_response.status_code == 200
    benchmark_payload = benchmark_response.get_json()
    assert benchmark_payload["live_benchmark"]["status"] == "ready"
    assert benchmark_payload["benchmark_reliability"]["cohort_size"] >= 10
    assert profile_response.status_code == 200
    html = profile_response.get_data(as_text=True)
    assert "Benchmark Vivo" in html
    assert "Time-Machine PSA" in html


def test_signals_outcomes_and_cohort_survival_analysis_expose_forecast_and_live_benchmark(app_client):
    client, db_path = app_client
    target_payload = make_patient_payload(nss="39999999996", full_name="Paciente Señales Prospectivas")
    register = client.post("/api/register_patient", json=target_payload)
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ENZALUTAMIDE",
        start_date="2025-06-01",
        context="mCRPC_first_line",
    )
    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2025-06-01", 0.9),
            ("2025-09-01", 1.0),
            ("2025-12-01", 1.3),
            ("2026-03-01", 1.9),
        ],
    )
    _update_patient_contact_status(db_path, patient_id, last_contact_date="2026-03-15")

    for idx in range(10):
        comparator = client.post(
            "/api/register_patient",
            json=make_patient_payload(nss=f"5999999999{idx}", full_name=f"Comparator Señales {idx}"),
        )
        comparator_id = comparator.get_json()["patient_id"]
        _seed_latest_assessment_state(db_path, comparator_id, "m1_crpc")
        _insert_treatment_line(
            db_path,
            comparator_id,
            line_of_therapy=1,
            drug_scheme="ENZALUTAMIDE",
            start_date="2025-05-01",
            context="mCRPC_first_line",
        )
        _insert_psa_longitudinal_points(
            db_path,
            comparator_id,
            [
                ("2025-06-01", 0.7 + idx * 0.03),
                ("2025-09-01", 0.8 + idx * 0.04),
                ("2025-12-01", 1.0 + idx * 0.05),
                ("2026-03-01", 1.4 + idx * 0.06),
            ],
        )
        _update_patient_contact_status(db_path, comparator_id, last_contact_date="2026-03-15")

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    outcomes_response = client.get(f"/api/patients/{patient_id}/outcomes")
    cohort_benchmarks_response = client.get("/api/cohorts/benchmarks")
    forecast_analysis_response = client.get("/api/cohorts/survival-analysis?endpoint=PSA_FORECAST")

    assert signals_response.status_code == 200
    assert outcomes_response.status_code == 200
    assert cohort_benchmarks_response.status_code == 200
    assert forecast_analysis_response.status_code == 200

    signals_payload = signals_response.get_json()
    outcomes_payload = outcomes_response.get_json()
    benchmarks_payload = cohort_benchmarks_response.get_json()
    analysis_payload = forecast_analysis_response.get_json()

    assert signals_payload["psa_forecast"]["status"] in {"ready", "low_confidence"}
    assert "live_benchmark" in signals_payload
    assert outcomes_payload["psa_forecast"]["status"] in {"ready", "low_confidence"}
    assert outcomes_payload["live_benchmark"]["status"] == "ready"
    assert "live_benchmark_summary" in benchmarks_payload
    assert "psa_forecast_summary" in benchmarks_payload
    assert analysis_payload["status"] == "ok"
    assert "summary_by_horizon" in analysis_payload


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


def test_delete_patient_endpoint_removes_profile_and_related_rows(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="23232323232", full_name="Paciente Eliminable")
    register_response = client.post("/api/register_patient", json=payload)
    patient_id = register_response.get_json()["patient_id"]

    client.post(
        "/api/add_followup",
        json={
            "patient_id": patient_id,
            "psa": 4.1,
            "testosterone": 18,
            "ecog": 1,
            "pain": 0,
            "treatment": "ADT",
            "status": "Estable",
        },
    )

    delete_response = client.delete(f"/api/patients/{patient_id}")
    assert delete_response.status_code == 200
    delete_payload = delete_response.get_json()
    assert delete_payload["success"] is True
    assert delete_payload["deleted"]["patient_id"] == patient_id

    patient_response = client.get(f"/api/patient/{payload['nss']}")
    assert patient_response.status_code == 404

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patient_identity WHERE id = ?", (patient_id,))
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM clinical_baseline WHERE patient_id = ?", (patient_id,))
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM follow_up_visits WHERE patient_id = ?", (patient_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()


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


def test_visit_schema_supports_inline_task_presentation_for_item_scoped_arpi_bundle(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45454545456", full_name="Paciente Inline Agenda"))
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

    agenda = client.get(f"/api/patients/{patient_id}/agenda").get_json()["agenda"]
    arpi_item = next(item for item in agenda["items"] if item["title"] == "Bundle de seguridad ARPI")

    schema_response = client.get(f"/api/patients/{patient_id}/visit-schema?agenda_id={arpi_item['id']}&presentation=inline_task")
    assert schema_response.status_code == 200
    payload = schema_response.get_json()
    schema = payload["visit_schema"]
    field_names = {
        field["name"]
        for section in schema["sections"]
        for field in section["fields"]
    }

    assert schema["presentation_mode"] == "inline_task"
    assert schema["submission_mode"] == "item_scoped"
    assert schema["task_scope"]["agenda_key"] == arpi_item["agenda_key"]
    assert schema["task_scope"]["action_mode"] == arpi_item["action_mode"]
    assert schema["encounter_key"] == arpi_item["encounter_key"]
    assert schema["plan_key"]
    assert schema["auto_visit_date"]
    assert schema["allow_visit_date_override"] is True
    assert "visit_date" not in field_names
    assert "clinician_notes" not in field_names
    assert set(schema["focus_fields"]) == field_names
    assert field_names == {
        field
        for field in arpi_item["required_inputs"]
        if field and not str(field).startswith("source_document:")
    }
    assert payload["agenda_item_context"]["mode"] == "inline_task"


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


def test_agenda_route_exposes_required_action_mode_and_completed_at(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="45555555559", full_name="Paciente Agenda Enriquecida"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "adt_progression_verification")

    agenda_response = client.get(f"/api/patients/{patient_id}/agenda")
    assert agenda_response.status_code == 200
    agenda = agenda_response.get_json()["agenda"]

    assert agenda["items"]
    assert all({"required", "action_mode", "completed_at"} <= set(item.keys()) for item in agenda["items"])
    assert agenda["encounters"]
    first_task = next(task for encounter in agenda["encounters"] for task in encounter["tasks"])
    assert {"required", "action_mode", "completed_at"} <= set(first_task.keys())


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


def test_response_visualization_exposes_integrated_treatment_timeline_and_preserves_swimmer(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="88888888891", full_name="Timeline Integrada"))
    patient_id = register.get_json()["patient_id"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE patient_identity SET diagnosis_date = ? WHERE id = ?", ("2025-12-15", patient_id))
    cursor.execute(
        """
        INSERT INTO treatment_history (
            patient_id, line_of_therapy, drug_scheme, start_date, end_date, outcome,
            nadir_psa, time_to_nadir_months, regimen_json, line_of_therapy_context
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            1,
            "ADT_ABIRATERONE",
            "2025-12-15",
            "2026-02-10",
            "Progression",
            8.0,
            1,
            json.dumps({
                "line_of_therapy_number": 1,
                "drug_scheme": "ADT_ABIRATERONE",
                "drug_scheme_label": "ADT + Abiraterona",
                "baseline_psa": 20.0,
                "nadir_psa": 8.0,
                "time_to_nadir_months": 1,
                "line_of_therapy_context": "mHSPC_initial",
            }),
            "mHSPC_initial",
        ),
    )
    cursor.execute(
        """
        INSERT INTO treatment_history (
            patient_id, line_of_therapy, drug_scheme, start_date, outcome, regimen_json, line_of_therapy_context
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            patient_id,
            2,
            "ADT_DAROLUTAMIDE",
            "2026-02-11",
            "Ongoing",
            json.dumps({
                "line_of_therapy_number": 2,
                "drug_scheme": "ADT_DAROLUTAMIDE",
                "drug_scheme_label": "ADT + Darolutamida",
                "baseline_psa": 12.0,
                "nadir_psa": 4.0,
                "time_to_nadir_months": 1,
                "line_of_therapy_context": "mHSPC_post_docetaxel",
            }),
            "mHSPC_post_docetaxel",
        ),
    )
    conn.commit()
    conn.close()

    _insert_psa_longitudinal_points(
        db_path,
        patient_id,
        [
            ("2025-12-15", 20.0),
            ("2026-01-15", 8.0),
            ("2026-02-10", 12.0),
            ("2026-03-10", 4.0),
        ],
    )

    visualization = client.post(f"/api/patients/{patient_id}/response-visualization")
    assert visualization.status_code == 200
    payload = visualization.get_json()["visualization"]
    timeline = payload["psa_trajectory"]["integrated_treatment_timeline"]

    assert payload["swimmer"]
    assert payload["psa_trajectory"]["has_data"] is True
    assert timeline["has_integrated_timeline"] is True
    assert len(timeline["treatment_lanes"]) == 2
    assert "2025-12-15" in timeline["axis_dates"]
    assert "2026-02-11" in timeline["axis_dates"]
    marker_types = {marker["type"] for marker in timeline["lane_markers"]}
    assert "PSA50" in marker_types
    assert "PD" in marker_types
    assert "LINE_CHANGE" in marker_types


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
    assert profile["evidence_applicability"]["supporting_trials"][0]["recommended_trial_backbone_label"] == "Lutecio-177 PSMA-617"


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
    client, db_path = app_client
    client.post("/api/register_patient", json=make_patient_payload(nss="93939393939", full_name="Paciente Cohorte"))

    summary = client.get("/api/dashboard/summary")
    assert summary.status_code == 200
    summary_payload = summary.get_json()
    assert "total_patients" in summary_payload
    assert "cohort_completeness" not in summary_payload
    assert "scenario_harness" not in summary_payload

    analytics = client.get("/api/dashboard/analytics")
    assert analytics.status_code == 200
    analytics_payload = analytics.get_json()
    assert "cohort_completeness" in analytics_payload
    assert "research_readiness" in analytics_payload
    assert "endpoint_readiness" in analytics_payload

    calibration = client.get("/api/dashboard/calibration")
    assert calibration.status_code == 200
    assert "scenario_harness" in calibration.get_json()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT cache_key FROM dashboard_cache_snapshots ORDER BY cache_key")
    cache_keys = {row["cache_key"] for row in cursor.fetchall()}
    conn.close()
    assert "dashboard_analytics_v1" in cache_keys
    assert "dashboard_calibration_v1" in cache_keys

    dashboard = client.get("/api/dashboard_stats")
    assert dashboard.status_code == 200
    payload = dashboard.get_json()
    assert "cohort_completeness" not in payload
    assert "scenario_harness" not in payload
    assert payload["analytics_endpoint"] == "/api/dashboard/analytics"
    assert payload["calibration_endpoint"] == "/api/dashboard/calibration"

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


def test_risk_tools_endpoint_shows_only_erspc_in_diagnostic_context(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494949", full_name="Paciente ERSPC") | {
            "dre_suspicious": 1,
            "prior_biopsy_count": 1,
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "diagnostic_workup")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    payload = response.get_json()
    tool_keys = [card["tool_key"] for card in payload["cards"]]
    assert tool_keys == ["erspc"]
    assert payload["cards"][0]["fidelity"] == "proxy_estimate"


def test_risk_tools_endpoint_gates_localized_rp_candidate_tools(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494950", full_name="Paciente RP") | {
            "clinical_tstage": "T2b",
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "isup_grade": 3,
            "life_expectancy_years": 14,
            "num_cores_positive": 5,
            "total_cores": 12,
            "local_treatment_consideration": "both",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    cards = response.get_json()["cards"]
    tool_keys = {card["tool_key"] for card in cards}
    assert {"capra", "damico", "predict_prostate", "mskcc_preop", "partin"} <= tool_keys
    assert "capra_s" not in tool_keys
    damico = next(card for card in cards if card["tool_key"] == "damico")
    assert damico["primary_result"] == "INTERMEDIO"


def test_risk_tools_endpoint_exposes_prognostic_impact_for_high_risk_localized_case(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494954", full_name="Paciente Riesgo Alto Localizado") | {
            "baseline_psa": 24.5,
            "clinical_tstage": "T3a",
            "gleason_primary": 4,
            "gleason_secondary": 4,
            "isup_grade": 4,
            "life_expectancy_years": 12,
            "num_cores_positive": 8,
            "total_cores": 12,
            "local_treatment_consideration": "both",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    payload = response.get_json()
    modifier_keys = {item["modifier_key"] for item in payload["prognostic_modifiers"]}
    assert "localized_unfavorable_biology" in modifier_keys
    assert payload["recommended_actions"]
    assert payload["followup_impact"]


def test_risk_tools_endpoint_exposes_capture_targets_for_missing_score_inputs(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494955", full_name="Paciente Score Incompleto") | {
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "isup_grade": 3,
            "life_expectancy_years": 13,
            "local_treatment_consideration": "both",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    payload = response.get_json()
    capture_targets = {item["tool_key"]: item for item in payload["capture_targets"]}
    assert "damico" in capture_targets
    assert "clinical_tstage" in capture_targets["damico"]["raw_fields"]


def test_risk_tools_endpoint_hides_surgical_nomograms_for_rt_only_candidates(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494951", full_name="Paciente RT") | {
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "life_expectancy_years": 11,
            "num_cores_positive": 3,
            "total_cores": 12,
            "local_treatment_consideration": "radical_radiotherapy",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    tool_keys = {card["tool_key"] for card in response.get_json()["cards"]}
    assert {"capra", "damico", "predict_prostate"} <= tool_keys
    assert "mskcc_preop" not in tool_keys
    assert "partin" not in tool_keys


def test_risk_tools_endpoint_prioritizes_capra_s_post_prostatectomy_and_interprets_decipher(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494952", full_name="Paciente CAPRA-S") | {
            "baseline_psa": 11.2,
            "gleason_primary": 4,
            "gleason_secondary": 3,
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO surgical_details (
            patient_id, surgery_date, surgery_type, pathological_stage,
            pathological_gleason_primary, pathological_gleason_secondary,
            surgical_margin_status, ece_pathological, svi_pathological, lni_pathological, pathological_isup
        ) VALUES (?, '2025-02-10', 'RP_robotica', 'pT3a', 4, 3, 1, 1, 0, 0, 3)
        """,
        (patient_id,),
    )
    cursor.execute(
        """
        INSERT INTO genomic_profile (
            patient_id, test_date, test_type, decipher_score, decipher_risk, hrr_overall
        ) VALUES (?, '2025-04-01', 'Decipher', 0.81, 'Alto', 'Desconocido')
        """,
        (patient_id,),
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/patients/{patient_id}/risk-tools")

    assert response.status_code == 200
    cards = response.get_json()["cards"]
    assert cards[0]["tool_key"] == "capra_s"
    assert cards[0]["status"] == "calculated"
    msk_post = next(card for card in cards if card["tool_key"] == "mskcc_bcr_post_rp")
    assert msk_post["status"] == "calculated"
    assert "5 años" in msk_post["primary_result"]
    decipher = next(card for card in cards if card["tool_key"] == "decipher")
    assert decipher["fidelity"] == "interpreted_from_report"
    assert "0.81" in decipher["primary_result"]


def test_post_rp_prognostic_impact_flows_into_signals_and_schedule(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494956", full_name="Paciente RP Impacto") | {
            "baseline_psa": 18.6,
            "gleason_primary": 4,
            "gleason_secondary": 4,
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "post_prostatectomy")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO surgical_details (
            patient_id, surgery_date, surgery_type, pathological_stage,
            pathological_gleason_primary, pathological_gleason_secondary,
            surgical_margin_status, ece_pathological, svi_pathological, lni_pathological, pathological_isup
        ) VALUES (?, '2025-03-01', 'RP_robotica', 'pT3a', 4, 4, 1, 1, 1, 0, 4)
        """,
        (patient_id,),
    )
    conn.commit()
    conn.close()

    signals_response = client.get(f"/api/patients/{patient_id}/signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.get_json()
    modifier_keys = {item["modifier_key"] for item in signals_payload["prognostic_modifiers"]}
    assert "post_rp_high_bcr_risk" in modifier_keys
    assert signals_payload["prognostic_followup_impact"]

    schedule_response = client.get(f"/api/patients/{patient_id}/schedule")
    assert schedule_response.status_code == 200
    schedule_payload = schedule_response.get_json()
    assert schedule_payload["cadence_adjusted_by"]
    assert schedule_payload["prognostic_rationale"]


def test_psmafore_like_signals_expose_backbone_alignment(app_client):
    client, db_path = app_client
    register = client.post("/api/register_patient", json=make_patient_payload(nss="94949494957", full_name="Paciente Alineacion PSMAfore"))
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "m1_crpc")
    _update_latest_assessment_input(db_path, patient_id, {"psma_positive": "1", "m_substage_resolved": "M1b"})
    _insert_treatment_line(
        db_path,
        patient_id,
        line_of_therapy=1,
        drug_scheme="ADT_ABIRATERONE",
        start_date="2025-01-15",
        context="mCRPC_post_ARPI_pre_taxane",
    )
    _insert_psma_imaging(db_path, patient_id, psma_positive=True)

    response = client.get(f"/api/patients/{patient_id}/signals")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["current_trial_comparable_profile"]["benchmark_family"] == "PSMAfore_like"
    assert payload["backbone_alignment"]["trial_backbone_label"] == "Lutecio-177 PSMA-617"
    assert payload["backbone_alignment"]["current_regimen_label"] == "ADT + abiraterona"
    assert payload["backbone_alignment"]["alignment_status"] == "divergent"


def test_clinical_assessment_context_requests_only_missing_score_inputs(app_client):
    client, _ = app_client

    diagnostic_draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "diagnostic_workup",
            "payload": {
                "age": 64,
                "psa": 6.8,
            },
        },
    )
    diagnostic_id = diagnostic_draft.get_json()["assessment_id"]
    diagnostic_context = client.get(f"/api/clinical-assessments/{diagnostic_id}").get_json()
    assert diagnostic_context["applicable_scores"] == ["erspc"]
    assert {item["name"] for item in diagnostic_context["score_missing_inputs"]} == {"dre_suspicious"}

    localized_draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "psa": 8.9,
                "gleason_primary": 4,
                "gleason_secondary": 3,
                "life_expectancy_years": 13,
                "local_treatment_consideration": "both",
            },
        },
    )
    localized_id = localized_draft.get_json()["assessment_id"]
    localized_context = client.get(f"/api/clinical-assessments/{localized_id}").get_json()
    assert set(localized_context["applicable_scores"]) == {"capra", "damico", "predict_prostate", "mskcc_preop", "partin"}
    missing = {item["name"] for item in localized_context["score_missing_inputs"]}
    assert "clinical_tstage" in missing
    assert "isup_grade" in missing
    assert "num_cores_positive" in missing
    assert "total_cores" in missing


def test_post_rp_assessment_context_requests_mskcc_postop_inputs(app_client):
    client, _ = app_client

    post_rp_draft = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "post_prostatectomy",
            "payload": {
                "psa": 9.8,
                "pathologic_stage": "pT3a",
                "surgical_margin": 1,
            },
        },
    )
    draft_id = post_rp_draft.get_json()["assessment_id"]
    context = client.get(f"/api/clinical-assessments/{draft_id}").get_json()

    assert set(context["applicable_scores"]) == {"capra_s", "mskcc_bcr_post_rp"}
    missing = {item["name"] for item in context["score_missing_inputs"]}
    assert "pathology_gleason_primary" in missing
    assert "pathology_gleason_secondary" in missing
    assert "ece_status" in missing
    assert "svi_status" in missing
    assert "lni_status" in missing


def test_dashboard_stats_include_risk_tool_and_upgrade_metrics(app_client):
    client, db_path = app_client
    register = client.post(
        "/api/register_patient",
        json=make_patient_payload(nss="94949494953", full_name="Paciente Cohorte Risk Tools") | {
            "clinical_tstage": "T2b",
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "isup_grade": 3,
            "life_expectancy_years": 12,
            "num_cores_positive": 4,
            "total_cores": 12,
            "clinical_risk_group": "intermedio desfavorable",
            "local_treatment_consideration": "both",
        },
    )
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "localized_initial")

    dashboard = client.get("/api/dashboard/analytics")

    assert dashboard.status_code == 200
    payload = dashboard.get_json()
    assert "risk_tool_stats" in payload
    assert "capra_distribution" in payload
    assert "damico_distribution" in payload
    assert "capra_s_distribution" in payload
    assert "mskcc_bcr_post_rp_stats" in payload
    assert "upgrade_stats" in payload
    assert "pathologic_upgrade_count" in payload["upgrade_stats"]
    assert "prognostic_modifier_stats" in payload
    assert "backbone_alignment_stats" in payload
    assert "prognostic_followup_impact_count" in payload
    assert "incomplete_prognostic_scores_count" in payload


def test_pivotal_match_hides_peace1_for_sync_low_volume_mhspc(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="40000000004", full_name="mHSPC Low Volume Demo")
    payload.update(
        {
            "metastasis_site": "Bone",
            "volume_disease": "Low",
            "ecog_score": 0,
            "metastasis_count": 2,
        }
    )
    register = client.post("/api/register_patient", json=payload)
    assert register.status_code == 200
    patient_id = register.get_json()["patient_id"]
    _seed_latest_assessment_state(db_path, patient_id, "mcspc_low_volume_sync_oligo")

    response = client.get(f"/api/pivotal_match/{payload['nss']}")

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    visible_names = {str(item.get("study_name", "")) for item in data["eligible_matches"] + data["partial_matches"] + data["ineligible_matches"]}
    assert "PEACE-1" not in visible_names
    assert "ARASENS" not in visible_names
    assert data["hidden_cross_scenario_count"] >= 1


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


def test_consent_signature_is_required_before_opening_record_and_visible_in_profile(app_client):
    client, db_path = app_client
    payload = make_patient_payload(nss="70000000001", full_name="Paciente Consentido")

    draft_response = client.post(
        "/api/research/consent/draft",
        json={"payload": payload, "source_context": "pytest"},
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()
    assert draft_data["success"] is True
    draft_id = draft_data["draft_id"]

    blocked_finalize = client.post(f"/api/research/consent/draft/{draft_id}/finalize")
    assert blocked_finalize.status_code == 400
    assert "sin consentimiento firmado" in blocked_finalize.get_json()["error"].lower()

    sign_response = client.post(
        f"/api/research/consent/draft/{draft_id}/sign",
        json={
            "signer_name": payload["full_name"],
            "signature_data_url": "data:image/png;base64,ZmlybWFfZGVtbw==",
            "accepted": True,
            "audit_metadata": {"channel": "pytest"},
        },
    )
    assert sign_response.status_code == 200
    sign_data = sign_response.get_json()
    assert sign_data["status"] == "signed"
    assert sign_data["evidence"]["content_hash"]

    finalize_response = client.post(f"/api/research/consent/draft/{draft_id}/finalize")
    assert finalize_response.status_code == 200
    finalize_data = finalize_response.get_json()
    assert finalize_data["success"] is True
    assert isinstance(finalize_data["patient_id"], int)
    assert finalize_data["consent"]["status"] == "signed"

    profile_response = client.get(f"/patient_profile/{payload['nss']}")
    assert profile_response.status_code == 200
    profile_html = profile_response.get_data(as_text=True)
    assert "Consentimiento de uso secundario de datos" in profile_html
    assert "Firma electrónica del paciente" in profile_html
    assert "Hash de evidencia" in profile_html

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patient_consents")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM consent_signature_evidence")
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_dashboard_research_intelligence_endpoint_returns_modular_panels(app_client):
    client, _ = app_client
    metastatic_payload = make_patient_payload(nss="70000000002", full_name="Paciente Research 1")
    metastatic_payload.update(
        {
            "metastasis_site": "Bone",
            "volume_disease": "High",
            "metastasis_count": 6,
            "ecog_score": 1,
            "known_cancer_diagnosis": 1,
            "metachronous_metastasis": 0,
        }
    )
    localized_payload = make_patient_payload(nss="70000000003", full_name="Paciente Research 2")
    localized_payload.update({"baseline_psa": 4.2, "metastasis_site": "M0"})

    first = client.post("/api/register_patient", json=metastatic_payload)
    second = client.post("/api/register_patient", json=localized_payload)
    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get("/api/dashboard/research-intelligence")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert "survival" in data
    assert "multivariate" in data
    assert "comparative_effectiveness" in data
    assert "operational_outcomes" in data
    assert "quality_indicators" in data
    assert "benchmarking" in data
    assert "dynamic_cohorts" in data
    assert "consent_governance" in data
    assert "research_readiness" in data
    assert isinstance(data["dynamic_cohorts"], list)
    assert data["consent_governance"]["total_patients"] >= 2


def test_research_cohort_survival_and_export_endpoints_work(app_client):
    client, db_path = app_client
    first_payload = make_patient_payload(nss="70000000004", full_name="Cohorte Uno")
    first_payload.update({"baseline_psa": 12.5, "ecog_score": 1})
    second_payload = make_patient_payload(nss="70000000005", full_name="Cohorte Dos")
    second_payload.update({"baseline_psa": 3.1, "ecog_score": 0})

    first = client.post("/api/register_patient", json=first_payload)
    second = client.post("/api/register_patient", json=second_payload)
    assert first.status_code == 200
    assert second.status_code == 200
    first_id = first.get_json()["patient_id"]
    second_id = second.get_json()["patient_id"]

    _update_patient_contact_status(db_path, first_id, last_contact_date="2026-03-12", vital_status="alive")
    _update_patient_contact_status(db_path, second_id, last_contact_date="2026-03-12", vital_status="alive")

    cohort_response = client.post(
        "/api/research/cohorts",
        json={
            "title": "PSA basal alto",
            "description": "Pacientes con PSA basal elevado para análisis institucional.",
            "filters": [{"field": "baseline_psa", "op": "gte", "value": 10}],
        },
    )
    assert cohort_response.status_code == 200
    cohort = cohort_response.get_json()["cohort"]
    assert cohort["title"] == "PSA basal alto"
    assert first_id in cohort["patient_ids"]
    assert second_id not in cohort["patient_ids"]

    cohort_detail = client.get(f"/api/research/cohorts/{cohort['id']}")
    assert cohort_detail.status_code == 200
    assert cohort_detail.get_json()["cohort"]["size"] == 1

    survival_response = client.get(f"/api/research/survival-curves?endpoint=OS&cohort_id={cohort['id']}")
    assert survival_response.status_code == 200
    survival_data = survival_response.get_json()
    assert survival_data["success"] is True
    assert survival_data["endpoint"] == "OS"
    assert survival_data["cohort_label"] == "PSA basal alto"

    export_response = client.get(f"/api/research/export/csv?cohort_id={cohort['id']}")
    assert export_response.status_code == 200
    export_data = export_response.get_json()
    assert export_data["success"] is True
    assert export_data["record_count"] == 1
    assert "baseline_psa" in export_data["csv"]
    assert export_data["manifest"]["scope_label"] == "PSA basal alto"
