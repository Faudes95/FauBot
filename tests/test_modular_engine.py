import sqlite3

from clinical_scores import calculate_all_scores
from prostanet.application.module_registry import ModuleRegistry
from prostanet.shared.presentation_text import humanize_result, humanize_schema, resolve_option_label


def test_modular_metadata_and_hub_routes_are_available(app_client):
    client, _ = app_client

    root_response = client.get("/", follow_redirects=False)
    assert root_response.status_code == 302
    assert root_response.headers["Location"].endswith("/clinical-hub")

    calculator_response = client.get("/calculator", follow_redirects=False)
    assert calculator_response.status_code == 302
    assert calculator_response.headers["Location"].endswith("/clinical-hub")

    modules_response = client.get("/api/modules")
    assert modules_response.status_code == 200
    modules_data = modules_response.get_json()
    assert modules_data["success"] is True
    module_ids = {item["module"] for item in modules_data["modules"]}
    assert "diagnostic_workup" in module_ids
    assert "post_negative_biopsy_followup" in module_ids
    assert "localized_initial" in module_ids
    assert "recurrence_bcr" in module_ids
    assert "adt_progression_verification" in module_ids
    assert "m1_crpc" in module_ids

    guideline_response = client.get("/api/guidelines/metadata")
    assert guideline_response.status_code == 200
    guideline_data = guideline_response.get_json()
    assert guideline_data["success"] is True
    assert guideline_data["guidelines"]["nccn_2026"]["version"] == "5.2026"
    assert guideline_data["guidelines"]["eau_2026"]["version"] == "2026"

    schema_response = client.get("/api/modules/localized_initial/schema")
    assert schema_response.status_code == 200
    schema_data = schema_response.get_json()
    assert schema_data["success"] is True
    assert "ISUP grade group" not in str(schema_data)
    assert "Grupo de grado de la Sociedad Internacional de Patología Urológica" in str(schema_data)
    localized_fields = {field["name"] for field in schema_data["schema"]["fields"]}
    assert "prior_mpmri_pirads_score" in localized_fields
    assert "adverse_histology_variant_type" in localized_fields

    diagnostic_schema_response = client.get("/api/modules/diagnostic_workup/schema")
    assert diagnostic_schema_response.status_code == 200
    diagnostic_schema_data = diagnostic_schema_response.get_json()
    lesion_field = next(
        field for field in diagnostic_schema_data["schema"]["fields"] if field["name"] == "index_lesion_location"
    )
    assert lesion_field["field_type"] == "select"
    assert lesion_field["default"] == "No especificada"
    assert "Zona periférica posterior" in lesion_field["options"]

    classifier_schema_response = client.get("/api/modules/state-classifier/schema")
    assert classifier_schema_response.status_code == 200
    classifier_schema_data = classifier_schema_response.get_json()
    classifier_fields = {field["name"]: field for field in classifier_schema_data["schema"]["fields"]}
    assert classifier_fields["prior_prostatectomy"]["label"] == "Prostatectomía radical previa por cáncer de próstata"
    assert classifier_fields["prior_radiation"]["label"] == "Radioterapia previa por cáncer de próstata"
    assert classifier_fields["bcr2"]["label"] == "Segunda recurrencia bioquímica tras tratamiento local"

    hub_response = client.get("/clinical-hub")
    assert hub_response.status_code == 200
    hub_html = hub_response.get_data(as_text=True)
    assert "Centro clínico por estadio" in hub_html
    assert "Legacy calculator" not in hub_html
    assert "Diagnóstico confirmado de cáncer de próstata" in hub_html
    assert "Biopsia prostática previa benigna" in hub_html
    assert "Contexto de progresión sistémica" in hub_html
    assert "No aplica / sin contexto de progresión bajo ADT" in hub_html
    assert "Progresión bajo ADT: verificar castración" in hub_html
    assert "1. Confirmación diagnóstica" in hub_html
    assert "2. Tratamiento local previo y recurrencia" in hub_html
    assert "3. Enfermedad metastásica conocida" in hub_html
    assert "4. Progresión bajo ADT / CRPC" in hub_html
    assert "Prostatectomía radical previa por cáncer de próstata" in hub_html
    assert "Radioterapia previa por cáncer de próstata" in hub_html
    assert "Segunda recurrencia bioquímica tras tratamiento local" in hub_html
    assert "Este contexto solo aplica cuando ya existe cáncer de próstata confirmado" in hub_html
    assert "md:hidden" in hub_html

    patients_html = client.get("/patients").get_data(as_text=True)
    assert "ui_theme.css" in patients_html
    assert "clinical_selects.js" in patients_html
    assert "Registro longitudinal de pacientes" in patients_html
    assert "Nuevo caso clínico" in patients_html

    dashboard_html = client.get("/dashboard").get_data(as_text=True)
    assert "ui_theme.css" in dashboard_html
    assert "clinical_selects.js" in dashboard_html
    assert "Panorama longitudinal de la cohorte" in dashboard_html


def test_state_classifier_routes_patients_to_expected_modules(app_client):
    client, _ = app_client

    localized = client.post("/api/state-classifier", json={"metastasis_site": "M0"})
    assert localized.status_code == 200
    assert localized.get_json()["state"] == "localized_initial"
    assert "No se detectaron tratamientos locales previos" in localized.get_json()["classification_reason"]

    diagnostic = client.post(
        "/api/state-classifier",
        json={"known_cancer_diagnosis": 0, "prior_negative_biopsy": 0, "metastasis_site": "M0"},
    )
    assert diagnostic.status_code == 200
    assert diagnostic.get_json()["state"] == "diagnostic_workup"

    diagnostic_residual = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 0,
            "prior_negative_biopsy": 0,
            "prior_prostatectomy": 1,
            "prior_radiation": 1,
            "bcr2": 1,
            "systemic_progression_context": "confirmed_crpc",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "conventional_imaging_status": "M1",
            "metastasis_site": "Bone",
            "metastasis_count": 4,
            "metachronous_metastasis": 1,
            "volume_disease": "High",
        },
    )
    assert diagnostic_residual.status_code == 200
    assert diagnostic_residual.get_json()["state"] == "diagnostic_workup"

    benign_followup = client.post(
        "/api/state-classifier",
        json={"known_cancer_diagnosis": 0, "prior_negative_biopsy": 1, "metastasis_site": "M0"},
    )
    assert benign_followup.status_code == 200
    assert benign_followup.get_json()["state"] == "post_negative_biopsy_followup"

    benign_followup_residual = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 0,
            "prior_negative_biopsy": 1,
            "prior_prostatectomy": 1,
            "bcr2": 1,
            "systemic_progression_context": "progression_on_adt_verify_castration",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "unknown",
            "metastasis_site": "Bone",
            "metastasis_count": 3,
            "volume_disease": "High",
        },
    )
    assert benign_followup_residual.status_code == 200
    assert benign_followup_residual.get_json()["state"] == "post_negative_biopsy_followup"

    recurrence = client.post(
        "/api/state-classifier",
        json={"prior_prostatectomy": 1, "psa_current": 0.4, "metastasis_site": "M0"},
    )
    assert recurrence.status_code == 200
    assert recurrence.get_json()["state"] == "recurrence_bcr"

    crpc = client.post(
        "/api/state-classifier",
        json={"castration_resistant": 1, "metastasis_site": "Bone"},
    )
    assert crpc.status_code == 200
    assert crpc.get_json()["state"] == "m1_crpc"

    adt_verification = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "systemic_progression_context": "progression_on_adt_verify_castration",
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "unknown",
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "not_restaged",
            "prior_prostatectomy": 1,
        },
    )
    assert adt_verification.status_code == 200
    assert adt_verification.get_json()["state"] == "adt_progression_verification"

    nmcrpc = client.post(
        "/api/state-classifier",
        json={
            "known_cancer_diagnosis": 1,
            "systemic_progression_context": "confirmed_crpc",
            "castrate_testosterone_status": "confirmed_castrate",
            "conventional_imaging_status": "M0",
        },
    )
    assert nmcrpc.status_code == 200
    assert nmcrpc.get_json()["state"] == "m0_crpc"


def test_localized_module_uses_nccn_2026_and_eau_2026_logic(app_client):
    client, _ = app_client

    low_payload = {
        "age": 62,
        "psa": 5.0,
        "clinical_tstage": "T1c",
        "gleason_primary": 3,
        "gleason_secondary": 3,
        "isup_grade": 1,
        "num_cores_positive": 2,
        "total_cores": 12,
        "max_core_involvement": 0.10,
        "psad": 0.10,
        "life_expectancy_years": 15,
        "prior_mpmri": 1,
        "prior_mpmri_pirads_score": "2",
        "prior_mpmri_targeted_biopsy_status": "si",
        "confirmatory_biopsy_planned": 1,
        "cribriform_pattern": 0,
        "intraductal_carcinoma": 0,
        "nodal_status": "N0",
        "metastasis_site": "M0",
    }

    response = client.post("/api/modules/localized_initial/evaluate", json=low_payload)
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["nccn_primary"]["risk_group"] == "LOW"
    assert result["nccn_primary"]["label"] != "Very Low"
    assert result["eau_comparison"]["risk_group"] == "LOW"
    assert result["applicability_badge_key"] in {"preferred", "guideline-consistent"}
    assert result["nccn_primary"]["titulo_clinico"]
    assert result["nccn_primary"]["resumen_del_caso"]
    assert result["nccn_primary"]["trayectoria_recomendada"]
    assert len(result["nccn_primary"]["fundamentos_personalizados"]) >= 2
    assert "structured_summary" in result["report_sections"]

    gg3_payload = low_payload | {
        "psa": 8.5,
        "clinical_tstage": "T2a",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "psad": 0.18,
    }
    response = client.post("/api/modules/localized_initial/evaluate", json=gg3_payload)
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["nccn_primary"]["risk_group"] == "UNFAVORABLE INTERMEDIATE"
    assert result["eau_comparison"]["risk_group"] == "INTERMEDIATE (UNFAVORABLE)"


def test_adt_progression_verification_requires_castration_before_crpc_redirection(app_client):
    client, _ = app_client

    not_castrate = client.post(
        "/api/modules/adt_progression_verification/evaluate",
        json={
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "not_castrate",
            "testosterone_value": 180,
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "M0",
            "psadt_months": 8,
        },
    )
    assert not_castrate.status_code == 200
    not_castrate_result = not_castrate.get_json()["result"]
    assert not_castrate_result["decision_quality"]["state_classification"] == "Fracaso de supresión androgénica o castración inadecuada"
    assert "optimizar" in not_castrate_result["eligible_treatments"][0]["name"].lower()

    nmcrpc = client.post(
        "/api/modules/adt_progression_verification/evaluate",
        json={
            "current_adt_context": "medical_adt_continuous",
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_value": 18,
            "progression_pattern": "biochemical_only",
            "conventional_imaging_status": "M0",
            "psadt_months": 7,
        },
    )
    assert nmcrpc.status_code == 200
    nmcrpc_result = nmcrpc.get_json()["result"]
    assert nmcrpc_result["decision_quality"]["state_classification"] == "Candidato confirmado a enfermedad resistente a la castración sin metástasis"
    assert "sin metástasis" in nmcrpc_result["eligible_treatments"][0]["name"].lower()

    mcrpc = client.post(
        "/api/modules/adt_progression_verification/evaluate",
        json={
            "current_adt_context": "orchiectomy",
            "orchiectomy_status": 1,
            "castrate_testosterone_status": "confirmed_castrate",
            "testosterone_value": 12,
            "progression_pattern": "radiographic",
            "conventional_imaging_status": "M1",
            "psadt_months": 6,
        },
    )
    assert mcrpc.status_code == 200
    mcrpc_result = mcrpc.get_json()["result"]
    assert mcrpc_result["decision_quality"]["state_classification"] == "Candidato confirmado a enfermedad resistente a la castración con metástasis"
    assert "con metástasis" in mcrpc_result["eligible_treatments"][0]["name"].lower()


def test_localized_initial_uses_pirads_and_histology_variant_to_restrict_active_surveillance(app_client):
    client, _ = app_client

    pirads_high = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 63,
            "life_expectancy_years": 15,
            "psa": 5.9,
            "psad": 0.11,
            "clinical_tstage": "T1c",
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "max_core_involvement": 0.2,
            "percent_pattern_4": 0,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "5",
            "prior_mpmri_targeted_biopsy_status": "no",
            "confirmatory_biopsy_planned": 1,
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
    )
    assert pirads_high.status_code == 200
    pirads_result = pirads_high.get_json()["result"]
    names = {item["name"] for item in pirads_result["eligible_treatments"]}
    assert "Active surveillance" not in names
    assert any("pi-rads 4 o 5" in item.lower() for item in pirads_result["not_recommended"])

    ductal = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 65,
            "life_expectancy_years": 14,
            "psa": 7.3,
            "psad": 0.14,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 3,
            "total_cores": 12,
            "max_core_involvement": 0.25,
            "percent_pattern_4": 10,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "3",
            "prior_mpmri_targeted_biopsy_status": "si",
            "confirmatory_biopsy_planned": 1,
            "adverse_histology_variant_type": "ductal_predominant",
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
    )
    assert ductal.status_code == 200
    ductal_result = ductal.get_json()["result"]
    assert "Active surveillance" not in {item["name"] for item in ductal_result["eligible_treatments"]}
    assert any("variante histológica adversa específica" in item.lower() for item in ductal_result["not_recommended"])

    small_cell = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 64,
            "life_expectancy_years": 16,
            "psa": 6.8,
            "psad": 0.12,
            "clinical_tstage": "T2a",
            "gleason_primary": 3,
            "gleason_secondary": 4,
            "isup_grade": 2,
            "num_cores_positive": 3,
            "total_cores": 12,
            "max_core_involvement": 0.3,
            "percent_pattern_4": 15,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "4",
            "prior_mpmri_targeted_biopsy_status": "si",
            "confirmatory_biopsy_planned": 1,
            "adverse_histology_variant_type": "small_cell_neuroendocrine",
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
    )
    assert small_cell.status_code == 200
    small_cell_result = small_cell.get_json()["result"]
    assert small_cell_result["decision_quality"]["unsupported_or_escalate"] is True


def test_diagnostic_and_post_negative_biopsy_modules_surface_monitoring_and_sources(app_client):
    client, _ = app_client

    diagnostic_response = client.post(
        "/api/modules/diagnostic_workup/evaluate",
        json={
            "psa": 9.2,
            "psad": 0.18,
            "dre_suspicious": 1,
            "pirads_score": 4,
            "family_history_positive": 1,
            "germline_risk_mutation": 0,
            "prior_negative_biopsy": 0,
        },
    )
    assert diagnostic_response.status_code == 200
    diagnostic_result = diagnostic_response.get_json()["result"]
    assert diagnostic_result["nccn_primary"]["risk_group"] == "DIAGNOSTIC_HIGH"
    assert diagnostic_result["monitoring_plan"]["cadence"]
    assert diagnostic_result["state_transition_targets"]
    assert diagnostic_result["source_citations"]

    sources_response = client.get("/api/modules/diagnostic_workup/sources")
    assert sources_response.status_code == 200
    sources = sources_response.get_json()["sources"]
    assert any(source["guideline_or_trial"] == "NCCN 5.2026" for source in sources)

    benign_response = client.post(
        "/api/modules/post_negative_biopsy_followup/evaluate",
        json={
            "psa": 4.2,
            "psad": 0.09,
            "pirads_score": 0,
            "dre_suspicious": 0,
            "years_since_negative_biopsy": 2,
            "family_history_positive": 0,
        },
    )
    assert benign_response.status_code == 200
    benign_result = benign_response.get_json()["result"]
    assert benign_result["nccn_primary"]["risk_group"] == "BENIGN_BIOPSY_LOW_INTENSITY"
    assert "12 a 24 meses" in benign_result["monitoring_plan"]["cadence"]
    assert any("Palmstedt 2019" in source["guideline_or_trial"] for source in benign_result["source_citations"])


def test_recurrence_module_exposes_bcr2_pathway(app_client):
    client, _ = app_client
    payload = {
        "prior_prostatectomy": 1,
        "prior_radiation": 0,
        "bcr2": 1,
        "psa_current": 0.7,
        "psa_nadir": 0.02,
        "psadt_months": 7,
        "eligible_pelvic_therapy": 0,
        "prior_secondary_rt": 1,
        "imaging_negative": 1,
    }

    response = client.post("/api/modules/recurrence_bcr/evaluate", json=payload)
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert "segunda recurrencia bioquímica" in result["nccn_primary"]["label"].lower()
    treatment_names = {item["name"] for item in result["eligible_treatments"]}
    assert "Enzalutamida con o sin leuprorelina" in treatment_names
    assert not any(name.startswith("Apalutamida + terapia de privación androgénica") for name in treatment_names)
    assert any("apalutam" in item.lower() for item in result["not_recommended"])


def test_boolean_option_label_resolver_supports_explicit_contextual_and_fallback_labels():
    assert resolve_option_label("psma_positive", "0", ["0", "1"]) == "No"
    assert resolve_option_label("cv_risk_documented", "1", ["0", "1"]) == "Documentado"
    assert resolve_option_label("docetaxel_fit", "1", ["1", "0"]) == "Sí"

    schema = humanize_schema(
        {
            "module": "m1_crpc",
            "title": "Test",
            "description": "",
            "fields": [
                {
                    "name": "docetaxel_fit",
                    "label": "Apto para docetaxel",
                    "field_type": "select",
                    "options": ["1", "0"],
                    "default": "1",
                }
            ],
        }
    )
    display_labels = [item["label"] for item in schema["fields"][0]["display_options"]]
    assert display_labels == ["Sí", "No"]


def test_all_boolean_schema_options_have_human_friendly_labels():
    registry = ModuleRegistry()
    module_ids = [item["module"] for item in registry.list_modules()]

    for module_id in module_ids:
        schema = humanize_schema(registry.get_module_schema(module_id))
        for field in schema["fields"]:
            options = [str(option) for option in field.get("options", [])]
            if field.get("field_type") == "select" and options in (["0", "1"], ["1", "0"]):
                labels = [str(item["label"]) for item in field.get("display_options", [])]
                assert "0" not in labels, f"{module_id}:{field['name']} rendered raw 0"
                assert "1" not in labels, f"{module_id}:{field['name']} rendered raw 1"


def test_capra_s_is_hidden_in_preop_scores_and_available_in_postop_module(app_client):
    preop_scores = calculate_all_scores(
        {
            "age": 65,
            "psa": 6.2,
            "clinical_tstage": "T1c",
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "pct_cores_positive": 2 / 12,
        }
    )
    assert "capra_s" not in preop_scores

    client, _ = app_client
    postop_response = client.post(
        "/api/modules/post_prostatectomy/evaluate",
        json={
            "psa": 12,
            "psa_postop": 0.03,
            "gleason_primary": 4,
            "gleason_secondary": 3,
            "surgical_margin": 1,
            "ece_status": 1,
            "svi_status": 0,
            "lni_status": 0,
            "pathologic_stage": "pT3a",
        },
    )
    assert postop_response.status_code == 200
    result = postop_response.get_json()["result"]
    assert result["state"] == "post_prostatectomy"
    assert result["report_sections"]["capra_s"]["score"] >= 0


def test_m0_crpc_prefers_observation_or_darolutamide_by_risk_and_seizure_profile(app_client):
    client, _ = app_client

    observe_response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={"psadt_months": 14, "castration_resistant": 1, "castrate_testosterone_confirmed": 1, "comorbidity_seizure": 0, "imaging_negative": 1},
    )
    assert observe_response.status_code == 200
    observe_result = observe_response.get_json()["result"]
    assert observe_result["eligible_treatments"][0]["name"].lower() == "terapia de privación androgénica + monitorización"
    assert any("tiempo de duplicación del antígeno prostático específico" in item.lower() for item in observe_result["not_recommended"])

    daro_response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={"psadt_months": 7, "castration_resistant": 1, "castrate_testosterone_confirmed": 1, "comorbidity_seizure": 1, "imaging_negative": 1},
    )
    assert daro_response.status_code == 200
    daro_result = daro_response.get_json()["result"]
    treatment_names = {item["name"] for item in daro_result["eligible_treatments"]}
    assert "Darolutamida + terapia de privación androgénica" in treatment_names
    assert any("enzalutamida/apalutamida" in item.lower() for item in daro_result["not_recommended"])


def test_advanced_modules_surface_sequence_specific_options(app_client):
    client, _ = app_client

    high_volume_response = client.post(
        "/api/modules/mcspc_high_volume/evaluate",
        json={
            "metastasis_count": 6,
            "metastasis_site": "Bone",
            "gleason_score": 9,
            "ecog_score": 1,
            "child_pugh_score": "A",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
        },
    )
    assert high_volume_response.status_code == 200
    high_volume_result = high_volume_response.get_json()["result"]
    high_volume_names = {item["name"] for item in high_volume_result["eligible_treatments"]}
    assert any(name.startswith("terapia de privación androgénica") and "Docetaxel + Darolutamida" in name for name in high_volume_names) or any(
        name.startswith("terapia de privación androgénica") and "Docetaxel + Abiraterona" in name for name in high_volume_names
    )

    m1_response = client.post(
        "/api/modules/m1_crpc/evaluate",
        json={
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "biomarker_source": "Biopsia metastásica",
            "molecular_report_date": "2026-03-01",
            "msi_status": "inestable",
            "tmb_high": 1,
            "metastasis_site": "Bone",
            "prior_therapy": "Abiraterona, Docetaxel",
            "prior_docetaxel_cycles": 6,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_taxane",
            "pain_symptoms": "Sintomatico",
            "ecog_performance_status": 1,
            "psma_positive": 1,
            "psma_negative_dominant_lesions": 0,
        },
    )
    assert m1_response.status_code == 200
    m1_result = m1_response.get_json()["result"]
    m1_names = {item["name"] for item in m1_result["eligible_treatments"]}
    assert "Olaparib" in m1_names
    assert "Pembrolizumab" in m1_names
    assert "Lutecio-177 dirigido al antígeno prostático específico de membrana" in m1_names
    assert "Cabazitaxel" in m1_names
    assert any("recombinación homóloga" in flag["label"].lower() or "hrr" in flag["label"].lower() for flag in m1_result["benchmarking_flags"])


def test_m0_crpc_requires_castration_confirmation(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m0_crpc/evaluate",
        json={"psadt_months": 7, "castration_resistant": 1, "castrate_testosterone_confirmed": 0, "imaging_negative": 1},
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert "no confirmada" in result["nccn_primary"]["label"].lower()
    assert "testosterona en rango de castración" in result["eligible_treatments"][0]["name"].lower()


def test_precision_paths_surface_akeega_and_pre_taxane_pluvicto(app_client):
    client, _ = app_client

    mhspc_response = client.post(
        "/api/modules/mcspc_high_volume/evaluate",
        json={
            "metastasis_count": 8,
            "metastasis_site": "Bone",
            "gleason_score": 9,
            "ecog_score": 1,
            "frailty_status": "Fit",
            "child_pugh_score": "A",
            "comorbidity_seizure": 0,
            "comorbidity_cardio": 0,
            "brca2_status": "Positivo",
            "hrr_gene": "BRCA2",
            "molecular_assay_source": "Biopsia metastásica",
            "molecular_assay_date": "2026-02-20",
        },
    )
    assert mhspc_response.status_code == 200
    mhspc_names = {item["name"] for item in mhspc_response.get_json()["result"]["eligible_treatments"]}
    assert any("niraparib" in name.lower() and "abiraterona" in name.lower() for name in mhspc_names)

    m1_response = client.post(
        "/api/modules/m1_crpc/evaluate",
        json={
            "hrr_status": "Negativo",
            "hrr_gene": "Desconocido",
            "biomarker_source": "Biopsia metastásica",
            "molecular_report_date": "2026-03-01",
            "msi_status": "estable",
            "metastasis_site": "Bone",
            "prior_therapy": "Enzalutamida",
            "prior_docetaxel_cycles": 0,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_arpi_pre_taxane",
            "docetaxel_fit": 0,
            "chemotherapy_delay_candidate": 1,
            "pain_symptoms": "Leve",
            "ecog_performance_status": 1,
            "psma_positive": 1,
            "psma_negative_dominant_lesions": 0,
        },
    )
    assert m1_response.status_code == 200
    m1_names = {item["name"] for item in m1_response.get_json()["result"]["eligible_treatments"]}
    assert "Lutecio-177 dirigido al antígeno prostático específico de membrana" in m1_names


def test_supportive_documents_are_mapped_without_displacing_guidelines(app_client):
    client, _ = app_client

    response = client.get("/api/modules/m1_crpc/sources")
    assert response.status_code == 200
    sources = response.get_json()["sources"]

    assert any(source["guideline_or_trial"] == "NCCN 5.2026" and source["evidence_role"] == "primary_guideline" for source in sources)
    assert any(source["local_pdf_path"].endswith("/33.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/34.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/35.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/36.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/37.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/40.pdf") for source in sources)
    assert any(source["local_pdf_path"].endswith("/41.pdf") for source in sources)


def test_m1_crpc_surfaces_a_single_tier_one_priority(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/m1_crpc/evaluate",
        json={
            "hrr_status": "Positivo",
            "hrr_gene": "BRCA2",
            "biomarker_source": "ctDNA",
            "molecular_report_date": "2026-03-01",
            "msi_status": "inestable",
            "tmb_high": 1,
            "metastasis_site": "Bone",
            "prior_therapy": "Enzalutamida, Docetaxel",
            "prior_docetaxel_cycles": 6,
            "castrate_testosterone_confirmed": 1,
            "mcrpc_line_context": "post_taxane",
            "docetaxel_fit": 0,
            "chemotherapy_delay_candidate": 1,
            "pain_symptoms": "Sintomatico",
            "ecog_performance_status": 1,
            "psma_positive": 1,
            "psma_negative_dominant_lesions": 0,
        },
    )
    assert response.status_code == 200
    treatments = response.get_json()["result"]["eligible_treatments"]
    preferred = [item for item in treatments if item["priority"] == "preferente"]
    assert len(preferred) == 1


def test_diagnostic_registration_avoids_false_treatment_history_and_hides_advanced_widgets(app_client):
    client, db_path = app_client

    diagnostic_payload = {
        "psa": 8.7,
        "psad": 0.17,
        "dre_suspicious": 1,
        "pirads_score": 4,
        "prostate_volume_ml": 42,
        "planned_biopsy_type": "Dirigida + sistemática",
        "planned_biopsy_route": "Transperineal",
    }
    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "diagnostic_workup", "payload": diagnostic_payload},
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()
    assessment_id = draft_data["assessment_id"]
    assert "redirect_url" not in draft_data
    assert draft_data["scope"] == "diagnostic"
    fragment_ids = {fragment["id"] for fragment in draft_data["registration_fragments"]}
    assert "fragment_common_identity_baseline" in fragment_ids
    assert "fragment_diagnostic" in fragment_ids
    assert "fragment_treatment_history" not in fragment_ids

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "nss": "44444444444",
            "full_name": "Paciente Diagnostico",
            "dob": "1972-04-10",
            "baseline_psa": 8.7,
            "metastasis_site": "M0",
            "volume_disease": "Low",
            "line_of_therapy": 1,
            "drug_scheme": "",
            "assessment_state": "diagnostic_workup",
        },
    )
    assert register_response.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM treatment_history")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM biopsy_details")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM diagnostic_plans")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM mri_facts")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM biopsy_trigger_events")
    assert cursor.fetchone()[0] == 1
    conn.close()

    patient_response = client.get("/api/patient/44444444444")
    assert patient_response.status_code == 200
    patient_data = patient_response.get_json()["patient"]
    assert patient_data["treatments"] == []
    assert patient_data["prior_history"]["current_state"] == "diagnostic_workup"
    assert patient_data["biopsies"] == []
    assert patient_data["diagnostic_plans"]
    assert patient_data["mri_facts"]
    assert patient_data["biopsy_triggers"]

    profile_html = client.get("/patient_profile/44444444444").get_data(as_text=True)
    assert "Última evaluación clínica modular" in profile_html
    assert "Plan diagnóstico actual" in profile_html
    assert "Historial de biopsias" not in profile_html


def test_clinical_calibration_harness_reaches_full_concordance(app_client):
    client, _ = app_client

    response = client.get("/api/clinical-calibration")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    calibration = data["calibration"]
    assert calibration["total_cases"] >= 10
    assert calibration["failed_cases"] == 0
    assert calibration["concordance_pct"] == 100.0


def test_validated_algorithms_and_decision_quality_surface_in_localized_module(app_client):
    client, _ = app_client

    response = client.post(
        "/api/modules/localized_initial/evaluate",
        json={
            "age": 63,
            "life_expectancy_years": 16,
            "psa": 5.8,
            "psad": 0.11,
            "clinical_tstage": "T1c",
            "gleason_primary": 3,
            "gleason_secondary": 3,
            "isup_grade": 1,
            "num_cores_positive": 2,
            "total_cores": 12,
            "max_core_involvement": 0.2,
            "percent_pattern_4": 0,
            "prior_mpmri": 1,
            "prior_mpmri_pirads_score": "2",
            "prior_mpmri_targeted_biopsy_status": "si",
            "confirmatory_biopsy_planned": 1,
            "nodal_status": "N0",
            "metastasis_site": "M0",
        },
    )
    assert response.status_code == 200
    result = response.get_json()["result"]
    names = {item["name"] for item in result["validated_algorithms"]}
    assert "CAPRA" in names
    assert "Tablas de Partin" in names
    assert "MSKCC pre-radical prostatectomy nomogram" in names
    assert "PREDICT Prostate" in names
    assert result["decision_quality"]["requires_human_review"] is False
    assert result["decision_quality"]["confidence_category"] in {"alta", "vigilada"}


def test_rich_longitudinal_tables_persist_from_integrated_registration(app_client):
    client, db_path = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "localized_initial",
            "payload": {
                "age": 66,
                "life_expectancy_years": 14,
                "psa": 7.1,
                "psad": 0.14,
                "clinical_tstage": "T1c",
                "gleason_primary": 3,
                "gleason_secondary": 4,
                "isup_grade": 2,
                "num_cores_positive": 3,
                "total_cores": 12,
                "max_core_involvement": 0.25,
                "percent_pattern_4": 15,
                "prior_mpmri": 1,
                "prior_mpmri_pirads_score": "3",
                "prior_mpmri_targeted_biopsy_status": "si",
                "prostate_volume_ml": 50,
                "genomic_classifier": "Decipher",
                "genomic_classifier_result": "Intermedio",
                "confirmatory_biopsy_planned": 1,
                "ipss_score": 9,
                "iief5_score": 17,
                "baseline_urinary_qol": 82,
                "baseline_sexual_qol": 68,
                "baseline_bowel_qol": 90,
                "nodal_status": "N0",
                "metastasis_site": "M0",
            },
        },
    )
    assert draft_response.status_code == 200
    assessment_id = draft_response.get_json()["assessment_id"]

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "assessment_state": "localized_initial",
            "nss": "55555555555",
            "full_name": "Paciente Localizado",
            "dob": "1968-08-20",
            "estado_residencia": "Jalisco",
            "family_history_detail": "Padre con cancer de prostata a los 70 anos",
            "baseline_psa": 7.1,
        },
    )
    assert register_response.status_code == 200
    payload = register_response.get_json()
    assert payload["recommendation_mode"] == "guideline_modular"
    assert payload["processing_summary"]["state"] == "localized_initial"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM biopsy_details")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM genomic_profile")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM patient_pros")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM active_surveillance")
    assert cursor.fetchone()[0] == 0
    conn.close()
    profile_html = client.get("/patient_profile/55555555555").get_data(as_text=True)
    assert "Benchmarking operativo del estado actual" in profile_html
    assert "Torre de control del antígeno prostático específico" in profile_html
    assert "Línea 1" not in profile_html
    patient_response = client.get("/api/patient/55555555555")
    assert patient_response.status_code == 200
    assert patient_response.get_json()["patient"]["active_surveillance"] == {}


def test_clinical_assessment_draft_and_patient_registration_flow(app_client):
    client, db_path = app_client
    payload = {
        "age": 65,
        "psa": 8.5,
        "clinical_tstage": "T2a",
        "gleason_primary": 4,
        "gleason_secondary": 3,
        "isup_grade": 3,
        "num_cores_positive": 4,
        "total_cores": 12,
        "max_core_involvement": 0.2,
        "psad": 0.18,
        "life_expectancy_years": 15,
        "cribriform_pattern": 0,
        "intraductal_carcinoma": 0,
        "nodal_status": "N0",
        "metastasis_site": "M0",
    }

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={"module_id": "localized_initial", "payload": payload},
    )
    assert draft_response.status_code == 200
    draft_data = draft_response.get_json()
    assert draft_data["success"] is True
    assessment_id = draft_data["assessment_id"]
    assert "redirect_url" not in draft_data
    assert draft_data["assessment"]["state"] == "localized_initial"
    assert draft_data["scope"] == "localized"
    fragment_ids = {fragment["id"] for fragment in draft_data["registration_fragments"]}
    assert "fragment_common_identity_baseline" in fragment_ids
    assert "fragment_localized" in fragment_ids
    assert "fragment_mexico_cohort_optional" in fragment_ids
    assert draft_data["registration_defaults"]["baseline_psa"] == 8.5
    imported_names = {item["name"] for item in draft_data["imported_clinical_fields"]}
    assert "psa" in imported_names
    assert "clinical_tstage" in imported_names

    intake_redirect = client.get("/patient_intake", follow_redirects=False)
    assert intake_redirect.status_code == 302
    assert intake_redirect.headers["Location"].endswith("/clinical-hub")

    draft_detail = client.get(f"/api/clinical-assessments/{assessment_id}")
    assert draft_detail.status_code == 200
    assert draft_detail.get_json()["scope"] == "localized"

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "nss": "11111111111",
            "full_name": "Paciente Wizard",
            "dob": "1970-01-01",
            "baseline_psa": 8.5,
            "ipss_score": 7,
            "iief5_score": 18,
            "estado_residencia": "Jalisco",
        },
    )
    assert register_response.status_code == 200
    register_data = register_response.get_json()
    assert register_data["success"] is True
    assert register_data["assessment_id"] == assessment_id
    assert register_data["next_routes"]["profile"].endswith("/patient_profile/11111111111")
    assert register_data["assessment"]["display_result"]["nccn_primary"]["titulo_clinico"]
    assert register_data["assessment"]["display_result"]["eau_comparison"]["explicacion_breve"]

    patient_response = client.get("/api/patient/11111111111")
    assert patient_response.status_code == 200
    patient_data = patient_response.get_json()["patient"]
    assert patient_data["latest_assessment"]["id"] == assessment_id
    assert patient_data["prior_history"]["assessment_source"] == "clinical_wizard"
    assert patient_data["prior_history"]["current_state"] == "localized_initial"
    assert patient_data["prior_history"]["management_intent_status"] == "candidate"
    assert patient_data["state_timeline"]
    assert patient_data["demographics"]["estado_residencia"] == "Jalisco"
    assert patient_data["pros"]
    assert patient_data["treatments"] == []

    timeline_response = client.get("/api/patients/11111111111/state-timeline")
    assert timeline_response.status_code == 200
    timeline_data = timeline_response.get_json()["state_timeline"]
    assert timeline_data[-1]["state"] == "localized_initial"
    assert timeline_data[-1]["event_kind"] == "pathology_confirmed"
    assert timeline_data[-1]["management_intent_status"] == "candidate"

    recompute_response = client.post("/api/patients/11111111111/recompute-care-plan")
    assert recompute_response.status_code == 200
    recompute_data = recompute_response.get_json()
    assert recompute_data["assessment"]["display_result"]["monitoring_plan"]["cadence"]

    profile_html = client.get("/patient_profile/11111111111").get_data(as_text=True)
    assert "Última evaluación clínica modular" in profile_html
    assert "Línea de estados clínicos persistidos" not in profile_html
    assert "Plan maestro de seguimiento protocolizado" in profile_html
    assert "Siguiente mejor acción" in profile_html
    assert "Motor de Decisión Clínica" not in profile_html


def test_legacy_results_are_normalized_to_enriched_spanish_output():
    legacy = humanize_result(
        {
            "state": "m0_crpc",
            "nccn_primary": {
                "guideline": "NCCN",
                "version": "5.2026",
                "label": "M0 CRPC",
                "recommendation": "Use ARPI intensification when PSADT is short and metastatic imaging is negative.",
            },
            "eau_comparison": {
                "guideline": "EAU",
                "version": "2026",
                "label": "M0 CRPC",
                "comparison": {"summary": "NCCN 2026 y EAU 2026 coinciden en la categoria principal."},
            },
            "eligible_treatments": [{"name": "Darolutamida + ADT", "priority": "preferred", "notes": "Preferred for seizure risk."}],
            "not_recommended": ["Avoid automatic escalation."],
            "missing_critical_inputs": ["psadt_months"],
            "contraindications": [],
            "durations_and_conditions": ["Continue ADT backbone."],
            "evidence_trace": [],
            "trial_matches": [],
            "applicability_badge": "guideline-consistent",
            "report_sections": {"summary": "M0 CRPC risk-adapted intensification pathway."},
        }
    )
    assert legacy["nccn_primary"]["titulo_clinico"]
    assert "antígeno prostático específico" in legacy["nccn_primary"]["trayectoria_recomendada"].lower()
    assert legacy["eau_comparison"]["explicacion_breve"]
    assert legacy["report_sections"]["structured_summary"]["mensaje_para_toma_de_decisiones_compartida"]
