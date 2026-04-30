import sqlite3

from prostanet.domains.diagnostic_workup.rules_eau import classify_diagnostic_workup_eau
from prostanet.domains.diagnostic_workup.rules_nccn import classify_diagnostic_workup
from prostanet.domains.patient_tracking.risk_tools import build_intake_score_requirements
from prostanet.domains.post_negative_biopsy_followup.rules_eau import classify_post_negative_biopsy_eau
from prostanet.domains.post_negative_biopsy_followup.rules_nccn import classify_post_negative_biopsy
from prostanet.shared.dre import normalize_dre


def test_dre_finding_tstage_options_are_case_safe():
    t2a = normalize_dre({"dre_finding": "T2a - Afecta <=50% de un lobulo"})
    assert t2a.is_documented is True
    assert t2a.is_suspicious is True
    assert t2a.implied_tstage == "T2a"

    t2b = normalize_dre({"dre_finding": "T2B - Afecta >50% de un lobulo"})
    assert t2b.is_suspicious is True
    assert t2b.implied_tstage == "T2b"

    normal = normalize_dre({"dre_finding": "Normal"})
    assert normal.is_documented is True
    assert normal.is_suspicious is False


def test_diagnostic_rules_treat_dre_finding_as_independent_suspicion_signal():
    payload = {
        "age": 64,
        "psa": 3.1,
        "psad": 0.05,
        "pirads_score": 2,
        "dre_finding": "T2b - Afecta >50% de un lobulo",
    }

    nccn = classify_diagnostic_workup(payload)
    eau = classify_diagnostic_workup_eau(payload)

    assert nccn["biopsy_indicated"] is True
    assert nccn["dre_implied_tstage"] == "T2b"
    assert any("tacto rectal es sospechoso" in reason for reason in nccn["reasons"])
    assert eau["risk_group"] == "DIAGNOSTIC_HIGH"


def test_post_negative_biopsy_reopens_with_dre_finding_only():
    payload = {
        "psa": 3.4,
        "psad": 0.06,
        "pirads_score": 2,
        "dre_finding": "T2a - Afecta <=50% de un lobulo",
        "prior_biopsy_count": 1,
    }

    nccn = classify_post_negative_biopsy(payload)
    eau = classify_post_negative_biopsy_eau(payload)

    assert nccn["reopen_diagnostic_workup"] is True
    assert nccn["risk_group"] == "BENIGN_BIOPSY_REOPEN"
    assert eau["risk_group"] == "BENIGN_BIOPSY_REOPEN"


def test_intake_score_requirements_accept_documented_dre_finding():
    requirements = build_intake_score_requirements(
        module_id="diagnostic_workup",
        state="diagnostic_workup",
        assessment_input={
            "age": 64,
            "psa": 6.8,
            "dre_finding": "Normal",
        },
    )

    missing_names = {item["name"] for item in requirements["score_missing_inputs"]}
    assert "dre_suspicious" not in missing_names


def test_registration_persists_dre_finding_as_suspicious_baseline(app_client):
    client, db_path = app_client

    draft_response = client.post(
        "/api/clinical-assessments/draft",
        json={
            "module_id": "diagnostic_workup",
            "payload": {
                "age": 64,
                "psa": 3.1,
                "psad": 0.05,
                "pirads_score": 2,
                "dre_finding": "T2a - Afecta <=50% de un lobulo",
            },
        },
    )
    assert draft_response.status_code == 200
    assessment_id = draft_response.get_json()["assessment_id"]

    register_response = client.post(
        "/api/register_patient",
        json={
            "assessment_id": assessment_id,
            "nss": "77777777771",
            "full_name": "Paciente TR Normalizado",
            "dob": "1962-01-01",
            "baseline_psa": 3.1,
        },
    )
    assert register_response.status_code == 200

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT cb.dre_suspicious, cb.clinical_tstage
        FROM clinical_baseline cb
        JOIN patient_identity pi ON pi.id = cb.patient_id
        WHERE pi.nss = ?
        """,
        ("77777777771",),
    )
    row = cursor.fetchone()
    conn.close()

    assert row[0] == 1
    assert str(row[1]).upper() == "T2A"
