# -*- coding: utf-8 -*-
"""
psa_history_service — Capa de servicio para el historial APE/PSA.

Responsabilidades:
  1. CRUD sobre puntos PSA en `biomarker_longitudinal` (soft-delete con `deleted_at`).
  2. Bitácora obligatoria en `psa_audit_log` para cumplir trazabilidad clínica
     (FDA 21 CFR Part 11 / GxP). Cada operación graba operación, valor antes,
     valor después, actor y razón.
  3. Recálculo síncrono de cinética PSA (`psa_kinetics_snapshot`) tras cada
     INSERT/UPDATE/DELETE. Materializa: PSA velocity, PSADT, nadir + fecha,
     PCWG3 flag, Phoenix BCR flag, ASTRO BCR flag, bounce post-RT flag.
  4. Backfill perezoso de `clinical_state_at_measurement` derivándolo del
     `reconciled_state` más cercano cuando el punto carece de etiqueta.

Imports lazy de `tracking_db` y `clinical_scores` para evitar ciclos.

Tablas tocadas:
  - biomarker_longitudinal (CRUD)
  - psa_audit_log (INSERT)
  - psa_kinetics_snapshot (UPSERT)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable


def _utc_iso() -> str:
    """ISO timestamp UTC, segundos. Reemplaza datetime.utcnow() (deprecado en 3.12+)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds')

# Estados clínicos permitidos para etiquetar un punto PSA.
ALLOWED_CLINICAL_STATES = {
    'diagnostic_workup',
    'post_negative_biopsy_followup',
    'post_prostatectomy',
    'recurrence_bcr',
    'post_radiotherapy_or_local_salvage',
    'mcspc_oligo_metachronous',
    'mcspc_low_volume_sync_oligo',
    'mcspc_high_volume_sync',
    'mcspc_high_volume_metachronous',
    'mcspc_high_volume',
    'adt_progression_verification',
    'm0_crpc',
    'm1_crpc',
    'oligoprogression_post_systemic',
}

ALLOWED_DISEASE_PHASES = {
    'localized', 'bcr', 'mhspc', 'mcrpc', 'm0_crpc', 'oligoprogression', 'unknown',
}

ALLOWED_SOURCES = {'laboratory', 'self_report', 'historical_import', 'intake', 'followup'}


def _db_path() -> str:
    """Resuelve la ruta de DB tal como la configura `tracking_db.configure_db_path`."""
    from tracking_db import get_db_path  # lazy
    return get_db_path()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def _validate_state(value: str | None) -> str | None:
    if value in (None, ''):
        return None
    if value not in ALLOWED_CLINICAL_STATES:
        raise ValueError(
            f"clinical_state '{value}' inválido. Permitidos: {sorted(ALLOWED_CLINICAL_STATES)}"
        )
    return value


def _validate_disease_phase(value: str | None) -> str | None:
    if value in (None, ''):
        return None
    if value not in ALLOWED_DISEASE_PHASES:
        raise ValueError(
            f"disease_phase '{value}' inválido. Permitidos: {sorted(ALLOWED_DISEASE_PHASES)}"
        )
    return value


def _validate_source(value: str | None) -> str | None:
    if value in (None, ''):
        return 'laboratory'
    if value not in ALLOWED_SOURCES:
        raise ValueError(
            f"source '{value}' inválido. Permitidos: {sorted(ALLOWED_SOURCES)}"
        )
    return value


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def _write_audit(
    conn: sqlite3.Connection,
    point_id: int | None,
    patient_id: int,
    operation: str,
    value_before: Any,
    value_after: Any,
    actor: str,
    reason: str | None,
) -> None:
    """INSERT en psa_audit_log. Llamar dentro de la misma transacción del CRUD."""
    def _serialize(v):
        if v is None:
            return None
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False, default=str)
        return str(v)

    conn.execute(
        '''INSERT INTO psa_audit_log
           (point_id, patient_id, operation, value_before, value_after, actor, reason, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            point_id,
            patient_id,
            operation,
            _serialize(value_before),
            _serialize(value_after),
            actor or 'system',
            reason,
            _utc_iso(),
        ),
    )


def add_psa_point(
    patient_id: int,
    value: float,
    sample_date: str,
    clinical_state: str | None = None,
    disease_phase: str | None = None,
    line_label: str | None = None,
    source: str | None = 'laboratory',
    actor: str = 'system',
    reason: str | None = None,
) -> dict[str, Any]:
    """Inserta un punto PSA en biomarker_longitudinal + audit + recompute snapshot."""
    if value is None:
        raise ValueError("value es obligatorio")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value debe ser numérico: {value!r}") from exc
    if value < 0:
        raise ValueError("value PSA no puede ser negativo")
    if not sample_date:
        raise ValueError("sample_date es obligatorio (YYYY-MM-DD)")

    clinical_state = _validate_state(clinical_state)
    disease_phase = _validate_disease_phase(disease_phase)
    source = _validate_source(source)

    now = _utc_iso()

    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                '''INSERT INTO biomarker_longitudinal
                   (patient_id, biomarker_type, value, unit, sample_date,
                    lab_source, created_at,
                    clinical_state_at_measurement, disease_phase, line_label,
                    source, created_by, updated_at, reason)
                   VALUES (?, 'PSA', ?, 'ng/mL', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    patient_id, value, sample_date, source, now,
                    clinical_state, disease_phase, line_label,
                    source, actor, now, reason,
                ),
            )
            point_id = cur.lastrowid
            _write_audit(
                conn, point_id, patient_id, 'INSERT',
                value_before=None,
                value_after={'value': value, 'sample_date': sample_date,
                             'clinical_state': clinical_state, 'disease_phase': disease_phase,
                             'line_label': line_label, 'source': source},
                actor=actor, reason=reason,
            )
    finally:
        conn.close()

    snapshot = recompute_psa_kinetics(patient_id)
    return {'point_id': point_id, 'snapshot': snapshot}


def update_psa_point(
    point_id: int,
    actor: str,
    reason: str,
    **fields: Any,
) -> dict[str, Any]:
    """UPDATE selectivo + audit + recompute. `fields` admite: value, sample_date,
    clinical_state, disease_phase, line_label, source."""
    if not reason:
        raise ValueError("reason es obligatoria para auditoría")

    allowed = {'value', 'sample_date', 'clinical_state', 'disease_phase',
               'line_label', 'source'}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Campos no permitidos: {unknown}")

    if 'clinical_state' in fields:
        fields['clinical_state'] = _validate_state(fields['clinical_state'])
    if 'disease_phase' in fields:
        fields['disease_phase'] = _validate_disease_phase(fields['disease_phase'])
    if 'source' in fields:
        fields['source'] = _validate_source(fields['source'])
    if 'value' in fields and fields['value'] is not None:
        fields['value'] = float(fields['value'])
        if fields['value'] < 0:
            raise ValueError("value PSA no puede ser negativo")

    column_map = {
        'value': 'value',
        'sample_date': 'sample_date',
        'clinical_state': 'clinical_state_at_measurement',
        'disease_phase': 'disease_phase',
        'line_label': 'line_label',
        'source': 'source',
    }

    conn = _connect()
    try:
        before = _row_to_dict(
            conn.execute(
                'SELECT * FROM biomarker_longitudinal WHERE id = ?', (point_id,)
            ).fetchone()
        )
        if not before:
            raise ValueError(f"Punto PSA id={point_id} no existe")
        if before.get('biomarker_type') != 'PSA':
            raise ValueError("update_psa_point solo aplica a biomarker_type='PSA'")

        sets, params = [], []
        for key, val in fields.items():
            sets.append(f"{column_map[key]} = ?")
            params.append(val)
        sets.append("updated_at = ?")
        params.append(_utc_iso())
        params.append(point_id)

        with conn:
            conn.execute(
                f'UPDATE biomarker_longitudinal SET {", ".join(sets)} WHERE id = ?',
                params,
            )
            _write_audit(
                conn, point_id, before['patient_id'], 'UPDATE',
                value_before={k: before.get(column_map.get(k, k))
                              for k in fields},
                value_after=fields,
                actor=actor, reason=reason,
            )
    finally:
        conn.close()

    snapshot = recompute_psa_kinetics(before['patient_id'])
    return {'point_id': point_id, 'snapshot': snapshot}


def delete_psa_point(point_id: int, actor: str, reason: str) -> dict[str, Any]:
    """Soft-delete: marca `deleted_at` y registra audit. No se borra la fila."""
    if not reason:
        raise ValueError("reason es obligatoria para auditoría")

    conn = _connect()
    try:
        before = _row_to_dict(
            conn.execute(
                'SELECT * FROM biomarker_longitudinal WHERE id = ?', (point_id,)
            ).fetchone()
        )
        if not before:
            raise ValueError(f"Punto PSA id={point_id} no existe")
        if before.get('deleted_at'):
            return {'point_id': point_id, 'already_deleted': True}

        now = _utc_iso()
        with conn:
            conn.execute(
                'UPDATE biomarker_longitudinal SET deleted_at = ?, updated_at = ? WHERE id = ?',
                (now, now, point_id),
            )
            _write_audit(
                conn, point_id, before['patient_id'], 'DELETE',
                value_before={'value': before.get('value'),
                              'sample_date': before.get('sample_date')},
                value_after=None,
                actor=actor, reason=reason,
            )
    finally:
        conn.close()

    snapshot = recompute_psa_kinetics(before['patient_id'])
    return {'point_id': point_id, 'snapshot': snapshot}


def list_psa_points(patient_id: int, include_deleted: bool = False) -> list[dict[str, Any]]:
    """Lista puntos PSA del paciente (excluye soft-deleted por defecto)."""
    conn = _connect()
    try:
        sql = '''SELECT id, patient_id, value, sample_date,
                        clinical_state_at_measurement, disease_phase, line_label,
                        source, created_by, created_at, updated_at, deleted_at, reason
                 FROM biomarker_longitudinal
                 WHERE patient_id = ? AND biomarker_type = 'PSA' '''
        if not include_deleted:
            sql += "AND deleted_at IS NULL "
        sql += 'ORDER BY sample_date ASC, id ASC'
        rows = conn.execute(sql, (patient_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_audit_log(patient_id: int, limit: int = 100) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            '''SELECT id, point_id, patient_id, operation, value_before, value_after,
                      actor, reason, timestamp
               FROM psa_audit_log WHERE patient_id = ?
               ORDER BY timestamp DESC, id DESC LIMIT ?''',
            (patient_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_kinetics_snapshot(patient_id: int) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            'SELECT * FROM psa_kinetics_snapshot WHERE patient_id = ?', (patient_id,)
        ).fetchone()
        snap = _row_to_dict(row)
        if not snap:
            return None
        # Hidratar campos JSON.
        for key in ('pcwg3_evidence_json', 'kinetics_payload_json'):
            if snap.get(key):
                try:
                    snap[key.replace('_json', '')] = json.loads(snap[key])
                except (TypeError, ValueError):
                    pass
        return snap
    finally:
        conn.close()


def _get_testosterone_history(conn: sqlite3.Connection, patient_id: int) -> list[tuple[str, float]]:
    rows = conn.execute(
        '''SELECT sample_date, value FROM biomarker_longitudinal
           WHERE patient_id = ? AND biomarker_type IN ('testosterone', 'TESTOSTERONE')
             AND deleted_at IS NULL
           ORDER BY sample_date ASC''',
        (patient_id,),
    ).fetchall()
    return [(r['sample_date'], r['value']) for r in rows if r['value'] is not None]


def _get_last_rt_date(conn: sqlite3.Connection, patient_id: int) -> str | None:
    """Mejor esfuerzo: deduce última fecha de RT desde clinical_baseline o tratamientos."""
    try:
        row = conn.execute(
            'SELECT rt_primary_date FROM clinical_baseline WHERE patient_id = ?',
            (patient_id,),
        ).fetchone()
        if row and row['rt_primary_date']:
            return row['rt_primary_date']
    except sqlite3.OperationalError:
        pass
    return None


def recompute_psa_kinetics(patient_id: int) -> dict[str, Any]:
    """Recalcula cinética y flags clínicos. Persiste en psa_kinetics_snapshot.

    Idempotente: usa INSERT OR REPLACE.
    """
    from clinical_scores import (  # lazy
        calculate_psa_kinetics,
        detect_pcwg3_progression,
        detect_phoenix_bcr,
        detect_astro_bcr,
        detect_post_rt_bounce,
    )

    conn = _connect()
    try:
        rows = conn.execute(
            '''SELECT sample_date, value FROM biomarker_longitudinal
               WHERE patient_id = ? AND biomarker_type = 'PSA' AND deleted_at IS NULL
               ORDER BY sample_date ASC''',
            (patient_id,),
        ).fetchall()
        psa_history = [(r['sample_date'], r['value']) for r in rows if r['value'] is not None]

        kinetics = calculate_psa_kinetics(psa_history) if len(psa_history) >= 2 else {
            'velocity': None, 'psadt_months': None, 'interpretation': 'Sin datos suficientes'
        }

        # Nadir y fecha del nadir.
        nadir_value, nadir_date = (None, None)
        if psa_history:
            nadir_idx = min(range(len(psa_history)), key=lambda i: psa_history[i][1])
            nadir_date, nadir_value = psa_history[nadir_idx]

        testo_hist = _get_testosterone_history(conn, patient_id)
        rt_date = _get_last_rt_date(conn, patient_id)

        pcwg3 = detect_pcwg3_progression(psa_history, testo_hist, nadir_value, nadir_date)
        phoenix = detect_phoenix_bcr(psa_history, last_rt_date=rt_date, post_rt_nadir=nadir_value)
        astro = detect_astro_bcr(psa_history)
        bounce = detect_post_rt_bounce(psa_history, last_rt_date=rt_date, nadir_value=nadir_value)

        velocity = kinetics.get('velocity')
        psadt_raw = kinetics.get('psadt_months')
        psadt = None
        if isinstance(psadt_raw, (int, float)) and psadt_raw not in (float('inf'),):
            psadt = float(psadt_raw)

        payload = {
            'velocity': velocity,
            'psadt_months': psadt,
            'psa_nadir': nadir_value,
            'psa_nadir_date': nadir_date,
            'pcwg3': pcwg3,
            'phoenix': phoenix,
            'astro': astro,
            'bounce': bounce,
            'interpretation': kinetics.get('interpretation'),
            'point_count': len(psa_history),
        }

        with conn:
            conn.execute(
                '''INSERT OR REPLACE INTO psa_kinetics_snapshot
                   (patient_id, computed_at, psa_velocity, psadt_months,
                    psa_nadir, psa_nadir_date,
                    pcwg3_progression_flag, pcwg3_evidence_json,
                    phoenix_bcr_flag, astro_bcr_flag, bounce_post_rt_flag,
                    kinetics_payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    patient_id,
                    _utc_iso(),
                    velocity,
                    psadt,
                    nadir_value,
                    nadir_date,
                    1 if pcwg3.get('flag') else 0,
                    json.dumps(pcwg3, ensure_ascii=False, default=str),
                    1 if phoenix.get('flag') else 0,
                    1 if astro.get('flag') else 0,
                    1 if bounce.get('flag') else 0,
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )

        return payload
    finally:
        conn.close()
