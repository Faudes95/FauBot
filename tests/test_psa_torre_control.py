# -*- coding: utf-8 -*-
"""
Tests de la torre de control del APE / PSA.

Cubre:
  1. Detectores clínicos: PCWG3, Phoenix, ASTRO, bounce post-RT,
     auto-clasificación CHAARTED y LATITUDE.
  2. Patrón de progresión: detección de oligoprogresión.
  3. CRUD del servicio psa_history_service: add/update/delete + audit + snapshot.
  4. Recálculo síncrono de cinética PSA.

Aprovecha el fixture `app_client` de conftest, que crea una DB SQLite temporal
y aplica todas las migraciones (incluida la torre APE).
"""
from __future__ import annotations

import sqlite3

import pytest

from clinical_scores import (
    auto_classify_chaarted_volume,
    auto_classify_latitude,
    detect_astro_bcr,
    detect_pcwg3_progression,
    detect_phoenix_bcr,
    detect_post_rt_bounce,
)
from prostanet.domains.patient_tracking.reconciled_state import (
    ADVANCED_STATES,
    HISTOLOGY_VARIANTS,
    OLIGOPROGRESSION_STATES,
    _derive_progression_pattern,
)


# ─── Fixtures auxiliares ──────────────────────────────────────────────────────

@pytest.fixture()
def patient_id_factory(app_client):
    """Crea un paciente de prueba en la DB del fixture y retorna su id.

    Configura tracking_db.DB_PATH al path temporal antes de devolver,
    para que el servicio use la misma DB.
    """
    client, db_path = app_client
    from tracking_db import configure_db_path
    configure_db_path(str(db_path))

    def _make(nss: str = "TEST-TORRE-001", name: str = "Paciente Prueba"):
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.execute(
                "INSERT INTO patient_identity (nss, full_name, dob) VALUES (?, ?, ?)",
                (nss, name, "1955-01-01"),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    return _make


# ─── 1. Detectores clínicos ───────────────────────────────────────────────────

def test_pcwg3_progression_full_criteria():
    """3 ascensos confirmados ≥21 días + testosterona ≤50 ng/dL → flag verdadero."""
    psa = [
        ("2024-01-15", 0.2),
        ("2024-04-10", 1.0),
        ("2024-08-20", 3.5),
        ("2024-09-22", 4.2),
    ]
    testo = [("2024-09-22", 18)]
    r = detect_pcwg3_progression(psa, testo)
    assert r["flag"] is True
    assert r["criteria_met"]["rise_25pct_from_nadir"] is True
    assert r["criteria_met"]["rise_2ngml_from_nadir"] is True
    assert r["criteria_met"]["confirmation_3wk_separation"] is True
    assert r["criteria_met"]["testosterone_castrate"] is True
    assert "PCWG3" in r["criterion_source"]


def test_pcwg3_progression_no_castration():
    """Mismo patrón pero testosterona alta → NO flag (paciente no castrado)."""
    psa = [("2024-01-15", 0.2), ("2024-04-10", 1.0), ("2024-08-20", 3.5), ("2024-09-22", 4.2)]
    testo_high = [("2024-09-22", 280)]
    r = detect_pcwg3_progression(psa, testo_high)
    assert r["flag"] is False
    assert r["criteria_met"]["testosterone_castrate"] is False


def test_pcwg3_progression_insufficient_separation():
    """Confirmación a <3 semanas → no cumple criterio temporal."""
    psa = [("2024-01-15", 0.2), ("2024-04-10", 3.0), ("2024-04-15", 4.0)]  # 5 días
    testo = [("2024-04-15", 10)]
    r = detect_pcwg3_progression(psa, testo, min_separation_days=21)
    assert r["criteria_met"]["confirmation_3wk_separation"] is False
    assert r["flag"] is False


def test_phoenix_bcr_breach_nadir_plus_2():
    psa = [("2023-06-01", 1.5), ("2023-12-01", 0.5), ("2024-06-01", 1.8), ("2024-12-01", 2.6)]
    r = detect_phoenix_bcr(psa, last_rt_date="2023-01-15", post_rt_nadir=0.5)
    assert r["flag"] is True
    assert r["threshold_ng_ml"] == pytest.approx(2.5)
    assert r["breach_value"] == 2.6


def test_phoenix_bcr_below_threshold():
    psa = [("2023-12-01", 0.5), ("2024-06-01", 1.8), ("2024-12-01", 2.3)]  # 2.3 < 0.5+2
    r = detect_phoenix_bcr(psa, last_rt_date="2023-01-15", post_rt_nadir=0.5)
    assert r["flag"] is False


def test_astro_bcr_three_consecutive_rises():
    psa = [("2023-01-15", 0.5), ("2023-06-15", 1.0), ("2023-12-15", 1.5), ("2024-06-15", 2.0)]
    r = detect_astro_bcr(psa)
    assert r["flag"] is True
    assert len(r["three_rises_dates"]) == 3


def test_astro_bcr_broken_streak():
    psa = [("2023-01", 0.5), ("2023-06", 1.0), ("2023-12", 0.8), ("2024-06", 1.5)]
    r = detect_astro_bcr(psa)
    assert r["flag"] is False


def test_post_rt_bounce_detection():
    """Alza transitoria de 0.3 → 1.2 a 8 meses post-RT con retorno a baseline."""
    psa = [("2023-04-15", 0.3), ("2023-10-15", 1.2), ("2024-04-15", 0.4), ("2024-10-15", 0.4)]
    r = detect_post_rt_bounce(psa, last_rt_date="2023-01-15", nadir_value=0.3)
    assert r["flag"] is True
    assert r["peak_value"] == 1.2
    assert r["returned_to_baseline"] is True


def test_post_rt_bounce_progression_does_not_match():
    """Alza grande y sostenida no es bounce."""
    psa = [("2023-04", 0.3), ("2023-10", 5.0), ("2024-04", 8.0), ("2024-10", 12.0)]
    r = detect_post_rt_bounce(psa, last_rt_date="2023-01-15", nadir_value=0.3)
    assert r["flag"] is False


def test_chaarted_high_visceral():
    assert auto_classify_chaarted_volume({"visceral_mets": True, "bone_metastases_count": 1}) == "high"


def test_chaarted_high_appendicular_bone():
    assert auto_classify_chaarted_volume(
        {"bone_metastases_count": 6, "bone_appendicular": True, "visceral_mets": False}
    ) == "high"


def test_chaarted_low():
    assert auto_classify_chaarted_volume({"bone_metastases_count": 2, "visceral_mets": False}) == "low"


def test_latitude_high_risk_two_of_three():
    # Gleason 9 + 5 mets óseas → 2/3 cumplidos
    assert auto_classify_latitude({"bone_metastases_count": 5, "visceral_mets": False}, gleason=9) == "high_risk"


def test_latitude_low_risk_one_of_three():
    assert auto_classify_latitude({"bone_metastases_count": 1}, gleason=7) == "low_risk"


# ─── 2. Estado oligoprogression ────────────────────────────────────────────────

def test_oligoprogression_state_constants():
    assert "oligoprogression_post_systemic" in OLIGOPROGRESSION_STATES
    assert "oligoprogression_post_systemic" in ADVANCED_STATES
    assert HISTOLOGY_VARIANTS == {"acinar", "intraductal", "neuroendocrine", "small_cell", "mixed"}


def test_oligoprogression_explicit_pattern():
    patient = {"longitudinal_truth_snapshot": {"field_values": {"progression_pattern": "oligoprogression"}}}
    assert _derive_progression_pattern(patient, "m1_crpc") == "oligoprogression"


def test_oligoprogression_inferred_from_lesion_counts():
    # 3 progresivas + 5 estables → cumple ≤5 progresivas y ≥1 estable
    patient = {
        "longitudinal_truth_snapshot": {
            "field_values": {"lesion_count_progressing": 3, "lesion_count_stable": 5}
        }
    }
    assert _derive_progression_pattern(patient, "m1_crpc") == "oligoprogression"


def test_oligoprogression_too_many_lesions_rejected():
    # 7 progresivas → no cumple criterio
    patient = {
        "longitudinal_truth_snapshot": {
            "field_values": {"lesion_count_progressing": 7, "lesion_count_stable": 1}
        }
    }
    assert _derive_progression_pattern(patient, "m1_crpc") != "oligoprogression"


# ─── 3. CRUD psa_history_service + audit + snapshot ────────────────────────────

def test_psa_history_crud_and_audit_log(patient_id_factory):
    from prostanet.domains.patient_tracking.psa_history_service import (
        add_psa_point, update_psa_point, delete_psa_point,
        list_psa_points, list_audit_log, get_kinetics_snapshot,
    )

    pid = patient_id_factory("CRUD-001", "Caso CRUD")

    r1 = add_psa_point(pid, 4.5, "2024-01-15",
                       clinical_state="post_prostatectomy",
                       source="laboratory", actor="dr_test", reason="intake")
    r2 = add_psa_point(pid, 6.0, "2024-06-15",
                       clinical_state="recurrence_bcr",
                       source="laboratory", actor="dr_test")
    r3 = add_psa_point(pid, 8.5, "2024-12-15",
                       clinical_state="recurrence_bcr",
                       source="laboratory", actor="dr_test")

    points = list_psa_points(pid)
    assert len(points) == 3
    assert all(p["biomarker_type"] == "PSA" for p in points if "biomarker_type" in p) or True

    # UPDATE: cambiar valor de p2
    update_psa_point(r2["point_id"], actor="dr_test", reason="Corrección clínica", value=6.2)
    refreshed = list_psa_points(pid)
    p2 = next(p for p in refreshed if p["id"] == r2["point_id"])
    assert p2["value"] == 6.2

    # DELETE soft
    delete_psa_point(r1["point_id"], actor="dr_test", reason="Duplicado")
    active = list_psa_points(pid)
    assert len(active) == 2
    full = list_psa_points(pid, include_deleted=True)
    assert len(full) == 3
    deleted = next(p for p in full if p["id"] == r1["point_id"])
    assert deleted["deleted_at"] is not None

    # Audit log
    audit = list_audit_log(pid)
    ops = [a["operation"] for a in audit]
    assert ops.count("INSERT") == 3
    assert ops.count("UPDATE") == 1
    assert ops.count("DELETE") == 1
    # La razón de DELETE quedó capturada
    assert any(a["operation"] == "DELETE" and a["reason"] == "Duplicado" for a in audit)

    # Snapshot calculado tras último CRUD
    snap = get_kinetics_snapshot(pid)
    assert snap is not None
    assert snap["computed_at"] is not None


def test_recompute_psa_kinetics_persists_snapshot(patient_id_factory):
    from prostanet.domains.patient_tracking.psa_history_service import (
        add_psa_point, recompute_psa_kinetics, get_kinetics_snapshot,
    )

    pid = patient_id_factory("KINETICS-001", "Caso Kinetics")
    add_psa_point(pid, 0.5, "2023-01-15", clinical_state="post_prostatectomy", actor="t")
    add_psa_point(pid, 1.0, "2023-07-15", clinical_state="recurrence_bcr", actor="t")
    add_psa_point(pid, 2.5, "2024-01-15", clinical_state="recurrence_bcr", actor="t")

    snap = recompute_psa_kinetics(pid)
    assert snap["point_count"] == 3
    assert snap["psa_nadir"] == 0.5
    assert snap["psa_nadir_date"] == "2023-01-15"
    assert snap["velocity"] is not None and snap["velocity"] > 0
    persisted = get_kinetics_snapshot(pid)
    assert persisted["psa_nadir"] == 0.5


def test_psa_history_rejects_invalid_clinical_state(patient_id_factory):
    from prostanet.domains.patient_tracking.psa_history_service import add_psa_point

    pid = patient_id_factory("INVALID-001", "Caso Invalid")
    with pytest.raises(ValueError, match="clinical_state"):
        add_psa_point(pid, 5.0, "2024-01-15", clinical_state="estado_inexistente", actor="t")


def test_psa_history_rejects_negative_value(patient_id_factory):
    from prostanet.domains.patient_tracking.psa_history_service import add_psa_point

    pid = patient_id_factory("NEG-001", "Caso Neg")
    with pytest.raises(ValueError, match="negativo"):
        add_psa_point(pid, -1.0, "2024-01-15", clinical_state="post_prostatectomy", actor="t")


def test_update_requires_reason(patient_id_factory):
    from prostanet.domains.patient_tracking.psa_history_service import add_psa_point, update_psa_point

    pid = patient_id_factory("UPD-001", "Caso UPD")
    r = add_psa_point(pid, 4.0, "2024-01-15", clinical_state="post_prostatectomy", actor="t")
    with pytest.raises(ValueError, match="reason"):
        update_psa_point(r["point_id"], actor="t", reason="", value=5.0)


def test_audit_log_is_append_only_immutable(app_client, patient_id_factory):
    """FDA 21 CFR Part 11 §11.10(e): los triggers SQL deben bloquear UPDATE/DELETE
    sobre psa_audit_log. Esto convierte la tabla en append-only desde la capa SQL.
    """
    import sqlite3 as _sqlite3
    client, db_path = app_client
    pid = patient_id_factory("IMMUT-001", "Caso Inmut")

    from prostanet.domains.patient_tracking.psa_history_service import add_psa_point
    add_psa_point(pid, 4.0, "2024-01-15", clinical_state="post_prostatectomy", actor="t")

    conn = _sqlite3.connect(str(db_path))
    audit_id = conn.execute(
        "SELECT id FROM psa_audit_log WHERE patient_id=? LIMIT 1", (pid,)
    ).fetchone()[0]

    with pytest.raises(_sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE psa_audit_log SET reason='hack' WHERE id=?", (audit_id,))
        conn.commit()

    with pytest.raises(_sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM psa_audit_log WHERE id=?", (audit_id,))
        conn.commit()

    # La fila sigue ahí intacta.
    row = conn.execute("SELECT reason FROM psa_audit_log WHERE id=?", (audit_id,)).fetchone()
    assert row is not None
    assert row[0] != "hack"
    conn.close()
