from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import tracking_db


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def persist_json_run(table_name: str, payload: dict[str, Any], *, run_key: str | None = None) -> int:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    if table_name == "research_multivariate_runs":
        cursor.execute(
            """
            INSERT INTO research_multivariate_runs (
                run_key, analysis_type, cohort_key, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_key or payload.get("run_key"),
                payload.get("analysis_type"),
                payload.get("cohort_key"),
                json.dumps(payload, ensure_ascii=False, default=str),
                _now_iso(),
            ),
        )
    elif table_name == "research_propensity_runs":
        cursor.execute(
            """
            INSERT INTO research_propensity_runs (
                run_key, cohort_key, treatment_field, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_key or payload.get("run_key"),
                payload.get("cohort_key"),
                payload.get("treatment_field"),
                json.dumps(payload, ensure_ascii=False, default=str),
                _now_iso(),
            ),
        )
    elif table_name == "research_survival_snapshots":
        cursor.execute(
            """
            INSERT INTO research_survival_snapshots (
                snapshot_key, endpoint, cohort_key, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_key or payload.get("snapshot_key"),
                payload.get("endpoint"),
                payload.get("cohort_key"),
                json.dumps(payload, ensure_ascii=False, default=str),
                _now_iso(),
            ),
        )
    else:
        conn.close()
        raise ValueError(f"Tabla de research no soportada: {table_name}")
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(row_id)


def list_recent_runs(table_name: str, limit: int = 10) -> list[dict[str, Any]]:
    conn = tracking_db._connect()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT * FROM {table_name} ORDER BY created_at DESC, id DESC LIMIT ?",
        (int(limit),),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json", "{}") or "{}")
    return rows
