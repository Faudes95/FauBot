import sqlite3
import json
import os
from datetime import datetime
import logging
from pathlib import Path

DEFAULT_DB_PATH = "prostanet_tracking.db"
DB_PATH = os.environ.get("PROSTANET_DB_PATH", DEFAULT_DB_PATH)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _document_store():
    from prostanet.domains.patient_tracking.document_ingestion import PatientDocumentPrivateStore

    root = Path(DB_PATH).resolve().parent / ".prostanet_private" / "patient_documents"
    return PatientDocumentPrivateStore(root=root)


def configure_db_path(path=None):
    """Permite inyectar una base SQLite distinta, útil para tests."""
    global DB_PATH
    DB_PATH = path or os.environ.get("PROSTANET_DB_PATH", DEFAULT_DB_PATH)
    return DB_PATH


def get_db_path():
    return DB_PATH


def _is_truthy(value):
    return str(value).lower() in {"1", "true", "yes", "si", "on"}


def _is_present(value):
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _safe_float(value, default=0.0):
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def patient_exists(patient_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT 1 FROM patient_identity WHERE id = ? LIMIT 1", (patient_id,))
        exists = c.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        logger.error(f"Error checking patient existence: {e}")
        return False


def _parse_json_blob(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _json_blob(value):
    return json.dumps(value, ensure_ascii=False)


def _resolve_identity_row(cursor, nss_or_id):
    cursor.execute("SELECT * FROM patient_identity WHERE nss = ?", (str(nss_or_id),))
    identity = cursor.fetchone()
    if identity:
        return identity
    try:
        patient_id = int(nss_or_id)
    except (TypeError, ValueError):
        return None
    cursor.execute("SELECT * FROM patient_identity WHERE id = ?", (patient_id,))
    return cursor.fetchone()


def _ensure_prior_history_row(cursor, patient_id):
    cursor.execute("SELECT 1 FROM prior_clinical_history WHERE patient_id = ? LIMIT 1", (patient_id,))
    if cursor.fetchone():
        return
    cursor.execute(
        '''
        INSERT INTO prior_clinical_history (
            patient_id, rt_primary_received, rt_primary_dose_gy, rt_metastasis_history,
            prior_docetaxel_cycles, prior_arpi_agent, prior_arpi_duration
        ) VALUES (?, 0, 0, '[]', 0, NULL, 0)
        ''',
        (patient_id,),
    )


def _assessment_longitudinal_snapshot(assessment):
    result = assessment.get("result_snapshot", {}) if assessment else {}
    nccn = result.get("nccn_primary", {})
    report_sections = result.get("report_sections", {})
    structured = report_sections.get("structured_summary", {})
    decision_quality = result.get("decision_quality", {}) or {}
    return {
        "summary": nccn.get("resumen_del_caso") or structured.get("resumen_del_caso") or report_sections.get("summary", ""),
        "current_state": assessment.get("state"),
        "transition_reason": nccn.get("trayectoria_recomendada") or structured.get("trayectoria_recomendada") or report_sections.get("summary", ""),
        "objective_progression": result.get("objective_progression", {}),
        "monitoring_plan": result.get("monitoring_plan", {}),
        "care_overlays": result.get("care_overlays", []),
        "guideline_snapshot": assessment.get("guideline_versions", {}),
        "recommendation_family": decision_quality.get("recommendation_family") or result.get("recommendation_family", ""),
        "state_classification": decision_quality.get("state_classification") or result.get("state") or assessment.get("state"),
        "decision_quality": result.get("decision_quality", {}),
        "validated_algorithms": result.get("validated_algorithms", []),
    }


def _record_patient_state_transition(
    cursor,
    patient_id,
    assessment_id,
    state,
    event_kind,
    management_intent_status,
    transition_reason,
    objective_progression,
    monitoring_plan,
    care_overlays,
    latest_guideline_snapshot,
):
    cursor.execute(
        '''
        INSERT INTO patient_state_timeline (
            patient_id, assessment_id, state, event_kind, management_intent_status, transition_reason,
            objective_progression_json, monitoring_plan_json, care_overlays_json,
            latest_guideline_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            patient_id,
            assessment_id,
            state,
            event_kind,
            management_intent_status,
            transition_reason,
            _json_blob(objective_progression or {}),
            _json_blob(monitoring_plan or {}),
            _json_blob(care_overlays or []),
            _json_blob(latest_guideline_snapshot or {}),
        ),
    )


def _hydrate_timeline_rows(rows):
    timeline = []
    for row in rows:
        item = dict(row)
        item["objective_progression"] = _parse_json_blob(item.pop("objective_progression_json", None), {})
        item["monitoring_plan"] = _parse_json_blob(item.pop("monitoring_plan_json", None), {})
        item["care_overlays"] = _parse_json_blob(item.pop("care_overlays_json", None), [])
        item["latest_guideline_snapshot"] = _parse_json_blob(item.pop("latest_guideline_snapshot_json", None), {})
        item["event_kind"] = item.get("event_kind") or "recommendation_generated"
        item["management_intent_status"] = item.get("management_intent_status") or "candidate"
        timeline.append(item)
    return timeline


def _decorate_prior_history(prior_history):
    history = dict(prior_history) if prior_history else {}
    if not history:
        return {}
    history["rt_metastasis_history"] = _parse_json_blob(history.get("rt_metastasis_history"), [])
    history["objective_progression"] = _parse_json_blob(history.get("objective_progression_json"), {})
    history["monitoring_plan"] = _parse_json_blob(history.get("monitoring_plan_json"), {})
    history["care_overlays"] = _parse_json_blob(history.get("care_overlays_json"), [])
    history["latest_guideline_snapshot"] = _parse_json_blob(history.get("latest_guideline_snapshot_json"), {})
    history["management_intent_status"] = history.get("management_intent_status") or "candidate"
    return history


def _hydrate_followup_rows(rows):
    visits = []
    for row in rows:
        item = dict(row)
        item["toxicity"] = _parse_json_blob(item.pop("toxicity_events", None), {})
        item["metabolic"] = _parse_json_blob(item.pop("metabolic_panel", None), {})
        item["skeletal"] = _parse_json_blob(item.pop("skeletal_events", None), {})
        item["visit_bundle"] = _parse_json_blob(item.pop("visit_bundle_json", None), {})
        item["agenda_context"] = _parse_json_blob(item.pop("agenda_context_json", None), {})
        visits.append(item)
    return visits


def _hydrate_agenda_rows(rows):
    items = []
    for row in rows:
        item = dict(row)
        item["required_inputs"] = _parse_json_blob(item.pop("required_inputs_json", None), [])
        item["completion_rule"] = _parse_json_blob(item.pop("completion_rule_json", None), {})
        item["evidence_basis"] = _parse_json_blob(item.pop("evidence_basis_json", None), [])
        item["comparator_basis"] = _parse_json_blob(item.pop("comparator_basis_json", None), [])
        item["blockers"] = _parse_json_blob(item.pop("blockers_json", None), [])
        item["reasoning"] = _parse_json_blob(item.pop("reasoning_json", None), [])
        items.append(item)
    return items


def _hydrate_stage_visit_rows(rows):
    visits = []
    for row in rows:
        item = dict(row)
        item["visit_bundle"] = _parse_json_blob(item.pop("visit_bundle_json", None), {})
        visits.append(item)
    return visits


def _hydrate_provenance_rows(rows):
    provenance = []
    for row in rows:
        item = dict(row)
        item["value"] = _parse_json_blob(item.pop("value_json", None), None)
        provenance.append(item)
    return provenance


def _hydrate_event_rows(rows):
    events = []
    for row in rows:
        item = dict(row)
        item["payload"] = _parse_json_blob(item.pop("payload_json", None), {})
        item["mcode_focus"] = _parse_json_blob(item.pop("mcode_focus_json", None), {})
        events.append(item)
    return events


def _hydrate_signal_rows(rows):
    signals = []
    for row in rows:
        item = dict(row)
        item["signals"] = _parse_json_blob(item.pop("signals_json", None), [])
        item["critical_missing"] = _parse_json_blob(item.pop("critical_missing_json", None), [])
        item["awaiting_review"] = _parse_json_blob(item.pop("awaiting_review_json", None), [])
        item["active_safety"] = _parse_json_blob(item.pop("active_safety_json", None), [])
        item["next_best_action"] = _parse_json_blob(item.pop("next_best_action_json", None), {})
        item["mcode_projection"] = _parse_json_blob(item.pop("mcode_projection_json", None), {})
        signals.append(item)
    return signals


def _hydrate_transition_rows(rows):
    proposals = []
    for row in rows:
        item = dict(row)
        item["trigger_signals"] = _parse_json_blob(item.pop("trigger_signals_json", None), [])
        item["next_actions"] = _parse_json_blob(item.pop("next_actions_json", None), [])
        item["evidence_basis"] = _parse_json_blob(item.pop("evidence_basis_json", None), [])
        proposals.append(item)
    return proposals


def _hydrate_recommendation_audit_rows(rows):
    audits = []
    for row in rows:
        item = dict(row)
        item["outcome_snapshot"] = _parse_json_blob(item.pop("outcome_snapshot_json", None), {})
        audits.append(item)
    return audits


def _hydrate_source_document_rows(rows):
    documents = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _parse_json_blob(item.pop("metadata_json", None), {})
        documents.append(item)
    return documents


def _hydrate_document_candidate_rows(rows):
    candidates = []
    for row in rows:
        item = dict(row)
        item["value"] = _parse_json_blob(item.pop("value_json", None), None)
        candidates.append(item)
    return candidates


def _hydrate_document_task_rows(rows):
    tasks = []
    for row in rows:
        item = dict(row)
        item["summary"] = _parse_json_blob(item.pop("summary_json", None), {})
        tasks.append(item)
    return tasks


def _hydrate_verified_fact_rows(rows):
    facts = []
    for row in rows:
        item = dict(row)
        item["value"] = _parse_json_blob(item.pop("value_json", None), None)
        facts.append(item)
    return facts

def init_tracking_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # ── 1. IDENTIDAD Y DEMOGRÁFICOS (NSS) ────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS patient_identity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nss TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            dob DATE,
            diagnosis_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ── 2. PERFIL CLÍNICO BASAL (Investigación) ──────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS clinical_baseline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            
            -- Biomarcadores Básicos
            baseline_psa REAL,
            testosterone_baseline REAL,
            hemoglobin REAL,
            alp REAL, -- Fosfatasa Alcalina
            ldh REAL,
            albumin REAL,
            
            -- Estadificación
            tnm_stage TEXT,
            gleason_score INTEGER,
            metastasis_site TEXT, -- 'Hueso', 'Visceral', 'Ganglio', 'M0'
            metastasis_count INTEGER,
            volume_disease TEXT,  -- 'High' (CHAARTED) vs 'Low'
            ecog_score INTEGER,
            
            -- [NUEVO] Medicina de Precisión & Función Orgánica (Fase 3.1)
            genomic_test_done BOOLEAN DEFAULT 0,
            hrr_status TEXT,        -- 'Positivo', 'Negativo', 'Desconocido'
            msi_status TEXT,        -- 'Estable', 'Inestable'
            child_pugh_score TEXT,  -- 'A', 'B', 'C'
            pain_symptoms TEXT,     -- 'Asintomatico', 'Leve', 'Moderado-Severo'
            
            comorbidities_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS follow_up_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            visit_date DATE DEFAULT (DATE('now')),
            
            -- Biomarcadores Evolutivos
            psa_current REAL,
            testosterone_current REAL,
            alp_current REAL,       -- Fosfatasa Alcalina (Nuevo Fase 5)
            ldh_current REAL,       -- Lactato Deshidrogenasa (Nuevo Fase 5)
            albumin_current REAL,   -- Albúmina (Nuevo Fase 5)
            hemoglobin_current REAL,-- Hemoglobina (Nuevo Fase 5)
            
            -- Estado Clínico y PROMs
            ecog_current INTEGER,
            pain_score INTEGER,     -- Escala 0-10 (BPI-SF Item 3)
            
            -- Farmacovigilancia & Toxicidad (CTCAE)
            toxicity_events TEXT,   -- JSON
            metabolic_panel TEXT,   -- JSON
            skeletal_events TEXT,   -- JSON: {'fracture': 0, 'radiation': 0} (Nuevo Fase 5)
            
            -- Tratamiento Actual
            current_treatment TEXT,
            dose_adjustment TEXT,
            
            -- Status
            disease_status TEXT, 
            
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    
    # Migration for existing DBs (Idempotent check)
    try:
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN alp_current REAL")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN ldh_current REAL")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN albumin_current REAL")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN hemoglobin_current REAL")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN ecog_current INTEGER")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN pain_score INTEGER")
        c.execute("ALTER TABLE follow_up_visits ADD COLUMN skeletal_events TEXT")
    except sqlite3.OperationalError:
        pass # Columns likely exist or table just created
    for ddl in (
        "ALTER TABLE follow_up_visits ADD COLUMN creatinine_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN cystatin_c_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN bilirubin_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN ast_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN alt_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN ggt_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN glucose_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN opioid_use TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN fatigue_score INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN mini_cog_score INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN weight_kg REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN bmi_current REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN weight_loss_6m_pct REAL",
        "ALTER TABLE follow_up_visits ADD COLUMN exercise_status TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN nutrition_status TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN protein_supplements INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN seizure_history INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN dermatitis_history INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN cv_risk_status TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN ddi_reviewed INTEGER",
        "ALTER TABLE follow_up_visits ADD COLUMN hepatic_risk_status TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN visit_bundle_json TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN visit_type TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN state_at_visit TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN management_track TEXT",
        "ALTER TABLE follow_up_visits ADD COLUMN agenda_context_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── 3. HISTORIAL TERAPÉUTICO (Longitudinal) ──────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS treatment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            line_of_therapy INTEGER, -- 1, 2, 3...
            
            drug_scheme TEXT, 
            -- Enum: 'ADT_MONO', 'ADT_DOCETAXEL', 'ADT_ENZALUTAMIDE', 'ADT_APALUTAMIDE', etc.
            
            start_date DATE,
            end_date DATE,
            outcome TEXT, -- 'Ongoing', 'Progression', 'Toxicidad'
            
            nadir_psa REAL,
            time_to_nadir_months INTEGER,
            
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE treatment_history ADD COLUMN regimen_json TEXT",
        "ALTER TABLE treatment_history ADD COLUMN class_exhausted TEXT",
        "ALTER TABLE treatment_history ADD COLUMN discontinuation_reason TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── Legacy Table (Mantener compatibilidad) ───────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            source_type TEXT NOT NULL,
            age REAL, psa REAL, gleason_primary INTEGER, gleason_secondary INTEGER,
            clinical_tstage TEXT, num_cores_positive INTEGER, total_cores INTEGER,
            surgical_margin INTEGER, ece_status INTEGER, svi_status INTEGER, lni_status INTEGER,
            ml_prediction TEXT, clinical_scores TEXT, clinical_summary TEXT,
            discordance_alert BOOLEAN, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ── 4. HISTORIAL CLÍNICO PREVIO (Fase 6) ─────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS prior_clinical_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            
            -- Radioterapia
            rt_primary_received BOOLEAN DEFAULT 0,
            rt_primary_dose_gy REAL,
            rt_metastasis_history TEXT, -- JSON [{'site': 'Bone', 'technique': 'SBRT'}]
            
            -- Sistémico Previo
            prior_docetaxel_cycles INTEGER DEFAULT 0,
            prior_arpi_agent TEXT,       -- 'Abiraterona', 'Enzalutamida', etc.
            prior_arpi_duration INTEGER, -- Meses
            latest_assessment_id INTEGER,
            assessment_source TEXT,
            assessment_module TEXT,
            assessment_state TEXT,
            assessment_summary TEXT,
            
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN latest_assessment_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN assessment_source TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN assessment_module TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN assessment_state TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN assessment_summary TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN current_state TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN transition_reason TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN objective_progression_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN monitoring_plan_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN care_overlays_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN latest_guideline_snapshot_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN management_intent_status TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE prior_clinical_history ADD COLUMN recommendation_family TEXT")
    except sqlite3.OperationalError:
        pass

    # ══════════════════════════════════════════════════════════════════════════
    # ══  FASE B & C — NUEVAS TABLAS (Expediente Longitudinal + Investigación)
    # ══════════════════════════════════════════════════════════════════════════

    # ── 5. DEMOGRÁFICOS MÉXICO ──────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS patient_demographics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER UNIQUE,
            estado_residencia TEXT,          -- Estado de la República Mexicana
            seguridad_social TEXT,           -- 'IMSS', 'ISSSTE', 'Seguro Popular', 'Privado'
            escolaridad TEXT,               -- 'Primaria', 'Secundaria', 'Preparatoria', 'Licenciatura', 'Posgrado'
            ocupacion TEXT,
            estado_civil TEXT,
            etnia TEXT DEFAULT 'hispano',
            tabaquismo TEXT DEFAULT 'nunca', -- 'nunca', 'ex_fumador', 'activo_leve', 'activo_moderado', 'activo_severo'
            paquetes_anio REAL DEFAULT 0,
            diabetes_mellitus BOOLEAN DEFAULT 0,
            hipertension BOOLEAN DEFAULT 0,
            sindrome_metabolico BOOLEAN DEFAULT 0,
            actividad_fisica TEXT DEFAULT 'sedentario', -- 'sedentario', 'leve', 'moderado', 'intenso'
            ipss_score INTEGER DEFAULT 0,
            iief5_score INTEGER DEFAULT 0,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 6. HISTORIA FAMILIAR DETALLADA ──────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS family_history_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            relative_type TEXT,              -- 'Padre', 'Hermano', 'Tío paterno', 'Abuelo', 'Hijo'
            cancer_type TEXT,                -- 'Próstata', 'Mama', 'Ovario', 'Páncreas', 'Colorrectal'
            age_at_diagnosis INTEGER,
            known_mutation TEXT,             -- 'BRCA1', 'BRCA2', 'ATM', 'CHEK2', 'Desconocido'
            deceased BOOLEAN DEFAULT 0,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 7. ESTUDIOS DE IMAGEN ───────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS imaging_studies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            study_date DATE,
            study_type TEXT,                 -- 'mpMRI', 'PSMA-PET', 'CT', 'Gammagrama', 'US_transrectal'
            -- MRI specific
            pirads_score INTEGER,
            pirads_location TEXT,            -- Zona (PZ, TZ, CZ) y sector
            lesion_size_mm REAL,
            ece_suspicion BOOLEAN DEFAULT 0,
            svi_suspicion BOOLEAN DEFAULT 0,
            precise_score INTEGER,           -- 1-5 para seguimiento en VA
            -- PSMA-PET specific
            psma_result TEXT,                -- 'negativo', 'local', 'ganglionar', 'oseo', 'visceral'
            psma_suv_max REAL,
            -- Bone scan specific
            bone_scan_result TEXT,            -- 'negativo', 'sospechoso', 'positivo_limitado', 'positivo_extenso'
            bone_lesion_count INTEGER,
            -- General
            findings_json TEXT,              -- JSON libre para hallazgos detallados
            radiologist_notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS mri_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            fact_date DATE,
            mpmri_quality TEXT,
            decision_usable BOOLEAN DEFAULT 0,
            pirads_score INTEGER,
            lesion_location TEXT,
            lesion_size_mm REAL,
            prostate_volume_ml REAL,
            findings_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS diagnostic_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            plan_date DATE DEFAULT (DATE('now')),
            source_state TEXT,
            plan_type TEXT,
            plan_status TEXT,
            management_intent_status TEXT DEFAULT 'candidate',
            plan_summary TEXT,
            recommended_pathway TEXT,
            next_action TEXT,
            risk_calculator_pathway TEXT,
            trigger_conditions_json TEXT,
            evidence_context_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS biopsy_trigger_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            trigger_date DATE DEFAULT (DATE('now')),
            source_state TEXT,
            trigger_reason TEXT,
            priority TEXT,
            planned_biopsy_type TEXT,
            planned_biopsy_route TEXT,
            trigger_status TEXT,
            management_intent_status TEXT DEFAULT 'candidate',
            activation_conditions_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
    ''')

    # ── 8. PERFIL GENÓMICO ──────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS genomic_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            test_date DATE,
            test_type TEXT,                  -- 'Decipher', 'Prolaris', 'OncotypeDX_GPS', 'FoundationOne', 'Panel_HRR'
            -- Decipher
            decipher_score REAL,             -- 0.0 - 1.0
            decipher_risk TEXT,              -- 'Bajo', 'Intermedio', 'Alto'
            -- Prolaris
            prolaris_score REAL,
            -- Oncotype GPS
            gps_score REAL,                  -- 0-100
            -- HRR detallado
            brca1_status TEXT,               -- 'Wild-type', 'Mutado', 'VUS', 'No testado'
            brca2_status TEXT,
            atm_status TEXT,
            chek2_status TEXT,
            palb2_status TEXT,
            cdk12_status TEXT,
            -- Otros biomarcadores
            msi_status TEXT,                 -- 'MSS', 'MSI-H'
            tmb_score REAL,                  -- Mutations/Mb
            ar_v7_status TEXT,               -- 'Positivo', 'Negativo', 'No testado'
            pten_loss BOOLEAN DEFAULT 0,
            tp53_status TEXT,
            -- Resultado general
            hrr_overall TEXT,                -- 'Positivo', 'Negativo', 'Desconocido'
            actionable_findings TEXT,        -- JSON de hallazgos accionables
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 9. DETALLE DE BIOPSIAS ──────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS biopsy_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            biopsy_date DATE,
            biopsy_type TEXT,                -- 'sistematica', 'fusion', 'combinada', 'transperineal'
            biopsy_context TEXT,             -- 'diagnostica', 'confirmatoria_va', 'seguimiento_va', 'rebiopsia'
            total_cores INTEGER DEFAULT 12,
            positive_cores INTEGER DEFAULT 0,
            max_core_involvement_pct REAL,   -- 0-100
            -- Gleason
            gleason_primary INTEGER,
            gleason_secondary INTEGER,
            gleason_tertiary INTEGER,
            isup_grade INTEGER,
            -- Patología especial
            patron_cribiforme BOOLEAN DEFAULT 0,
            carcinoma_intraductal BOOLEAN DEFAULT 0,
            perineural_invasion BOOLEAN DEFAULT 0,
            lymphovascular_invasion BOOLEAN DEFAULT 0,
            porcentaje_patron_4 REAL,        -- 0-100
            porcentaje_patron_5 REAL,
            -- Comparación con biopsia previa
            upgrade_from_previous BOOLEAN DEFAULT 0,
            previous_isup INTEGER,
            adverse_histology_variant_type TEXT,
            adverse_histology_variant_detail TEXT,
            pathologist_notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    try:
        c.execute("ALTER TABLE biopsy_details ADD COLUMN adverse_histology_variant_type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE biopsy_details ADD COLUMN adverse_histology_variant_detail TEXT")
    except sqlite3.OperationalError:
        pass

    # ── 10. VIGILANCIA ACTIVA (AS) ──────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS active_surveillance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            enrollment_date DATE,
            enrollment_protocol TEXT,        -- 'NCCN_VL', 'NCCN_L', 'PRIAS', 'JHU', 'Custom'
            enrollment_criteria_met TEXT,    -- JSON de criterios cumplidos
            current_status TEXT DEFAULT 'activo', -- 'activo', 'salida_upgrade', 'salida_preferencia', 'salida_progresion', 'salida_ansiedad'
            exit_date DATE,
            exit_reason TEXT,
            exit_treatment TEXT,             -- 'RP', 'RT', 'Focal', 'Otro'
            -- Métricas de seguimiento
            total_biopsies_in_as INTEGER DEFAULT 0,
            total_mri_in_as INTEGER DEFAULT 0,
            months_in_as INTEGER DEFAULT 0,
            last_psa REAL,
            last_psadt_months REAL,
            notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 11. RECURRENCIA BIOQUÍMICA (BCR) ────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS biochemical_recurrence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            primary_treatment TEXT,          -- 'RP', 'RT', 'Focal'
            primary_treatment_date DATE,
            nadir_psa REAL,
            nadir_date DATE,
            -- BCR detection
            bcr_detected BOOLEAN DEFAULT 0,
            bcr_date DATE,
            bcr_psa REAL,
            bcr_definition TEXT,             -- 'AUA_0.2', 'ASTRO_Phoenix', 'EAU'
            psadt_at_bcr REAL,               -- Meses
            time_to_bcr_months INTEGER,
            -- Salvage treatment
            salvage_treatment TEXT,           -- 'sRT', 'sRT_ADT', 'ADT_only', 'observation'
            salvage_date DATE,
            salvage_response TEXT,            -- 'Completa', 'Parcial', 'Progresion'
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 12. DETALLE QUIRÚRGICO ──────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS surgical_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            surgery_date DATE,
            surgery_type TEXT,               -- 'RP_abierta', 'RP_laparoscopica', 'RP_robotica', 'focal_HIFU', 'focal_crioterapia'
            nerve_sparing TEXT,              -- 'bilateral', 'unilateral', 'ninguno'
            plnd_performed BOOLEAN DEFAULT 0,
            plnd_type TEXT,                  -- 'limitada', 'extendida', 'superextendida'
            nodes_removed INTEGER DEFAULT 0,
            nodes_positive INTEGER DEFAULT 0,
            -- Patología post-RP
            pathological_gleason_primary INTEGER,
            pathological_gleason_secondary INTEGER,
            pathological_isup INTEGER,
            pathological_stage TEXT,          -- pT2a, pT2b, pT2c, pT3a, pT3b, pT4
            surgical_margin_status BOOLEAN DEFAULT 0,
            margin_location TEXT,            -- 'apex', 'posterolateral', 'base', 'multiple'
            ece_pathological BOOLEAN DEFAULT 0,
            svi_pathological BOOLEAN DEFAULT 0,
            lni_pathological BOOLEAN DEFAULT 0,
            specimen_weight_grams REAL,
            tumor_volume_pct REAL,
            capra_s_score INTEGER,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE surgical_details ADD COLUMN surgical_approach TEXT",
        "ALTER TABLE surgical_details ADD COLUMN continence_status TEXT",
        "ALTER TABLE surgical_details ADD COLUMN potency_status TEXT",
        "ALTER TABLE surgical_details ADD COLUMN pde5i_use INTEGER",
        "ALTER TABLE surgical_details ADD COLUMN pads_per_day INTEGER",
        "ALTER TABLE surgical_details ADD COLUMN recovery_notes TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── 13. DETALLE DE RADIOTERAPIA ─────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS radiation_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            rt_date DATE,
            rt_context TEXT,                 -- 'definitiva', 'adyuvante', 'salvamento', 'paliativa', 'SBRT_met'
            rt_technique TEXT,               -- 'IMRT', 'VMAT', 'SBRT', 'Braquiterapia_LDR', 'Braquiterapia_HDR', 'Protones'
            target TEXT,                     -- 'prostata', 'lecho', 'pelvis', 'hueso', 'ganglio'
            total_dose_gy REAL,
            fractions INTEGER,
            dose_per_fraction_gy REAL,
            -- ADT concurrente
            concurrent_adt BOOLEAN DEFAULT 0,
            adt_duration_months INTEGER,
            adt_agent TEXT,                  -- 'LHRH_agonista', 'LHRH_antagonista', 'ARPI'
            -- Toxicidad aguda
            gu_toxicity_grade INTEGER DEFAULT 0,  -- CTCAE 0-4
            gi_toxicity_grade INTEGER DEFAULT 0,
            -- Notas
            notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')
    for ddl in (
        "ALTER TABLE radiation_details ADD COLUMN session_duration_minutes INTEGER",
        "ALTER TABLE radiation_details ADD COLUMN total_duration_days INTEGER",
        "ALTER TABLE radiation_details ADD COLUMN hematuria TEXT",
        "ALTER TABLE radiation_details ADD COLUMN dysuria TEXT",
        "ALTER TABLE radiation_details ADD COLUMN anemia_related TEXT",
        "ALTER TABLE radiation_details ADD COLUMN late_toxicity_json TEXT",
    ):
        try:
            c.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # ── 14. PROs (Patient-Reported Outcomes) ────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS patient_pros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            assessment_date DATE DEFAULT (DATE('now')),
            -- Urinary
            ipss_total INTEGER,              -- 0-35
            ipss_qol INTEGER,                -- 0-6
            pad_usage INTEGER DEFAULT 0,     -- Pads/día para incontinencia
            -- Sexual
            iief5_score INTEGER,             -- 5-25
            erection_sufficient BOOLEAN DEFAULT 0,
            pde5i_use BOOLEAN DEFAULT 0,
            -- Pain & QoL
            bpi_worst_pain INTEGER,          -- 0-10 (BPI-SF Item 3)
            bpi_average_pain INTEGER,        -- 0-10
            bpi_interference REAL,           -- 0-10 promedio de 7 ítems
            eq5d_index REAL,                 -- -0.5 a 1.0
            eq5d_vas INTEGER,                -- 0-100
            -- Prostate-specific QoL
            fact_p_total REAL,               -- FACT-P score
            -- Anxiety (AS patients)
            max_acs_score REAL,              -- Memorial Anxiety Scale for Prostate Cancer
            -- Notes
            clinician_notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 15. MATCHING CON ESTUDIOS PIVOTALES ─────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS pivotal_study_matching (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            evaluation_date DATE DEFAULT (DATE('now')),
            study_name TEXT,
            eligible BOOLEAN,
            eligibility_details TEXT,        -- JSON con criterios cumplidos/no cumplidos
            study_arm TEXT,                  -- 'experimental', 'control'
            expected_outcome TEXT,           -- Resultado esperado basado en el estudio
            applicability_to_patient TEXT,   -- Nota sobre aplicabilidad
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 16. ALERTAS INTELIGENTES ────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS smart_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            alert_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            alert_type TEXT,                 -- 'psa_rising', 'psadt_critical', 'upgrade_biopsy', 'ecog_decline', 'bcr_detected', 'as_exit', 'overdue_visit'
            severity TEXT,                   -- 'info', 'warning', 'critical'
            title TEXT,
            description TEXT,
            data_json TEXT,                  -- JSON con datos relevantes
            acknowledged BOOLEAN DEFAULT 0,
            acknowledged_by TEXT,
            acknowledged_date TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    # ── 17. EVALUACIONES CLÍNICAS MODULARES ────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS clinical_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_id TEXT NOT NULL,
            state TEXT NOT NULL,
            input_snapshot TEXT NOT NULL,
            result_snapshot TEXT NOT NULL,
            guideline_versions TEXT NOT NULL,
            status TEXT DEFAULT 'draft',
            patient_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS patient_state_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            state TEXT NOT NULL,
            event_kind TEXT DEFAULT 'recommendation_generated',
            management_intent_status TEXT DEFAULT 'candidate',
            transition_reason TEXT,
            objective_progression_json TEXT,
            monitoring_plan_json TEXT,
            care_overlays_json TEXT,
            latest_guideline_snapshot_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id)
        )
    ''')
    try:
        c.execute("ALTER TABLE patient_state_timeline ADD COLUMN event_kind TEXT DEFAULT 'recommendation_generated'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE patient_state_timeline ADD COLUMN management_intent_status TEXT DEFAULT 'candidate'")
    except sqlite3.OperationalError:
        pass

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS followup_agenda_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            agenda_key TEXT NOT NULL,
            state TEXT NOT NULL,
            management_track TEXT,
            item_type TEXT,
            title TEXT,
            status TEXT,
            priority TEXT,
            due_at DATE,
            window_start DATE,
            window_end DATE,
            required_inputs_json TEXT,
            completion_rule_json TEXT,
            evidence_basis_json TEXT,
            comparator_basis_json TEXT,
            generated_from_event TEXT,
            summary TEXT,
            blockers_json TEXT,
            reasoning_json TEXT,
            completed_at TIMESTAMP,
            visit_record_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(patient_id, agenda_key),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS stage_visit_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            visit_date DATE DEFAULT (DATE('now')),
            state TEXT NOT NULL,
            management_track TEXT,
            visit_type TEXT,
            visit_bundle_json TEXT,
            derived_followup_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS data_provenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            visit_record_id INTEGER,
            field_name TEXT NOT NULL,
            value_json TEXT,
            source_type TEXT,
            source_document_id TEXT,
            source_date DATE,
            verified_by TEXT,
            entered_manually BOOLEAN DEFAULT 1,
            stage_context TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(visit_record_id) REFERENCES stage_visit_records(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS patient_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_date DATE DEFAULT (DATE('now')),
            state_context TEXT,
            management_track TEXT,
            source_type TEXT,
            source_record_id INTEGER,
            status TEXT DEFAULT 'recorded',
            payload_json TEXT,
            mcode_focus_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS clinical_signal_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL UNIQUE,
            event_id INTEGER,
            state TEXT NOT NULL,
            management_track TEXT,
            ready_to_restage BOOLEAN DEFAULT 0,
            signals_json TEXT,
            critical_missing_json TEXT,
            awaiting_review_json TEXT,
            active_safety_json TEXT,
            next_best_action_json TEXT,
            mcode_projection_json TEXT,
            evidence_basis_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(event_id) REFERENCES patient_events(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS state_transition_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            proposal_key TEXT NOT NULL,
            event_id INTEGER,
            from_state TEXT NOT NULL,
            from_management_track TEXT,
            target_state TEXT NOT NULL,
            target_management_track TEXT,
            proposal_status TEXT DEFAULT 'open',
            priority TEXT,
            requires_confirmation BOOLEAN DEFAULT 1,
            rationale TEXT,
            trigger_signals_json TEXT,
            next_actions_json TEXT,
            evidence_basis_json TEXT,
            resulting_assessment_id INTEGER,
            confirmed_at TIMESTAMP,
            confirmed_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(patient_id, proposal_key),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(event_id) REFERENCES patient_events(id),
            FOREIGN KEY(resulting_assessment_id) REFERENCES clinical_assessments(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS recommendation_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            assessment_id INTEGER,
            event_id INTEGER,
            recommendation_family TEXT,
            recommended_option TEXT,
            selected_option TEXT,
            discordance_reason TEXT,
            outcome_snapshot_json TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(assessment_id) REFERENCES clinical_assessments(id),
            FOREIGN KEY(event_id) REFERENCES patient_events(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS source_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            document_key TEXT NOT NULL UNIQUE,
            document_type TEXT NOT NULL,
            title TEXT,
            file_name TEXT,
            mime_type TEXT,
            sha256 TEXT NOT NULL,
            storage_path TEXT,
            private_index_path TEXT,
            source_date DATE,
            classification_status TEXT DEFAULT 'pending',
            extraction_status TEXT DEFAULT 'pending',
            verification_status TEXT DEFAULT 'draft',
            uploaded_by TEXT,
            preview_excerpt TEXT,
            page_count INTEGER DEFAULT 0,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS document_extraction_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            candidate_key TEXT NOT NULL,
            field_name TEXT NOT NULL,
            fact_group TEXT,
            target_result_type TEXT,
            value_json TEXT,
            value_display TEXT,
            confidence REAL DEFAULT 0,
            status TEXT DEFAULT 'draft',
            extraction_method TEXT,
            evidence_excerpt TEXT,
            page_ref TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, candidate_key),
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(document_id) REFERENCES source_documents(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS document_verification_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL UNIQUE,
            task_key TEXT NOT NULL,
            task_status TEXT DEFAULT 'open',
            assigned_to TEXT,
            verified_by TEXT,
            verified_at TIMESTAMP,
            summary_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(document_id) REFERENCES source_documents(id)
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS verified_document_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            task_id INTEGER,
            fact_key TEXT,
            field_name TEXT NOT NULL,
            fact_group TEXT,
            target_result_type TEXT,
            value_json TEXT,
            value_display TEXT,
            source_date DATE,
            status TEXT DEFAULT 'verified',
            correction_note TEXT,
            verified_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id),
            FOREIGN KEY(document_id) REFERENCES source_documents(id),
            FOREIGN KEY(task_id) REFERENCES document_verification_tasks(id)
        )
        '''
    )

    conn.commit()
    conn.close()
    logger.info("Tracking DB initialized (v3 — Expediente Longitudinal + Investigación).")


def create_clinical_assessment_draft(module_id, state, input_snapshot, result_snapshot, guideline_versions):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO clinical_assessments (
                module_id, state, input_snapshot, result_snapshot, guideline_versions, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                module_id,
                state,
                json.dumps(input_snapshot, ensure_ascii=False),
                json.dumps(result_snapshot, ensure_ascii=False),
                json.dumps(guideline_versions, ensure_ascii=False),
                "draft",
            ),
        )
        assessment_id = c.lastrowid
        conn.commit()
        conn.close()
        return assessment_id
    except Exception as e:
        logger.error(f"Error creating clinical assessment draft: {e}")
        return None


def get_clinical_assessment(assessment_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM clinical_assessments WHERE id = ?", (assessment_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        assessment = dict(row)
        assessment["input_snapshot"] = _parse_json_blob(assessment.get("input_snapshot"), {})
        assessment["result_snapshot"] = _parse_json_blob(assessment.get("result_snapshot"), {})
        assessment["guideline_versions"] = _parse_json_blob(assessment.get("guideline_versions"), {})
        return assessment
    except Exception as e:
        logger.error(f"Error getting clinical assessment: {e}")
        return None


def attach_clinical_assessment_to_patient(assessment_id, patient_id):
    try:
        assessment = get_clinical_assessment(assessment_id)
        if not assessment:
            return False, "Evaluación clínica no encontrada"
        if not patient_exists(patient_id):
            return False, "Paciente no encontrado"

        snapshot = _assessment_longitudinal_snapshot(assessment)
        from prostanet.domains.patient_tracking.event_graph import (
            derive_management_intent_status,
            derive_timeline_event_kind,
        )
        record = get_patient_full_record(patient_id) or {}
        management_intent_status = derive_management_intent_status(assessment.get("state"), assessment.get("result_snapshot", {}), record)
        event_kind = derive_timeline_event_kind(assessment.get("state"), assessment.get("result_snapshot", {}), record)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        _ensure_prior_history_row(c, patient_id)
        c.execute(
            '''
            UPDATE clinical_assessments
            SET patient_id = ?, status = ?
            WHERE id = ?
            ''',
            (patient_id, "linked", assessment_id),
        )
        c.execute(
            '''
            UPDATE prior_clinical_history
            SET latest_assessment_id = ?,
                assessment_source = ?,
                assessment_module = ?,
                assessment_state = ?,
                assessment_summary = ?,
                recommendation_family = ?,
                management_intent_status = ?,
                current_state = ?,
                transition_reason = ?,
                objective_progression_json = ?,
                monitoring_plan_json = ?,
                care_overlays_json = ?,
                latest_guideline_snapshot_json = ?
            WHERE patient_id = ?
            ''',
            (
                assessment_id,
                "clinical_wizard",
                assessment.get("module_id"),
                assessment.get("state"),
                snapshot["summary"],
                snapshot.get("recommendation_family", ""),
                management_intent_status,
                snapshot["current_state"],
                snapshot["transition_reason"],
                _json_blob(snapshot["objective_progression"]),
                _json_blob(snapshot["monitoring_plan"]),
                _json_blob(snapshot["care_overlays"]),
                _json_blob(snapshot["guideline_snapshot"]),
                patient_id,
            ),
        )
        _record_patient_state_transition(
            c,
            patient_id,
            assessment_id,
            assessment.get("state"),
            event_kind,
            management_intent_status,
            snapshot["transition_reason"],
            snapshot["objective_progression"],
            snapshot["monitoring_plan"],
            snapshot["care_overlays"],
            {
                **snapshot["guideline_snapshot"],
                "decision_quality": snapshot.get("decision_quality", {}),
                "validated_algorithms": snapshot.get("validated_algorithms", []),
            },
        )
        conn.commit()
        conn.close()
        return True, "Evaluación clínica vinculada"
    except Exception as e:
        logger.error(f"Error attaching clinical assessment: {e}")
        return False, str(e)


def _fetch_latest_clinical_assessment(cursor, patient_id):
    cursor.execute(
        """
        SELECT * FROM clinical_assessments
        WHERE patient_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (patient_id,),
    )
    row = cursor.fetchone()
    if not row:
        return {}

    assessment = dict(row)
    assessment["input_snapshot"] = _parse_json_blob(assessment.get("input_snapshot"), {})
    assessment["result_snapshot"] = _parse_json_blob(assessment.get("result_snapshot"), {})
    assessment["guideline_versions"] = _parse_json_blob(assessment.get("guideline_versions"), {})
    return assessment

def save_patient_result(patient_data, ml_result, scores, summary):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check if new columns exist, if not add them (Migration logic for existing DB)
        try:
            c.execute("SELECT surgical_margin FROM patients LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating DB: Adding post-op columns...")
            c.execute("ALTER TABLE patients ADD COLUMN surgical_margin INTEGER")
            c.execute("ALTER TABLE patients ADD COLUMN ece_status INTEGER")
            c.execute("ALTER TABLE patients ADD COLUMN svi_status INTEGER")
            c.execute("ALTER TABLE patients ADD COLUMN lni_status INTEGER")

        c.execute('''
            INSERT INTO patients (
                source_id, source_type, age, psa, 
                gleason_primary, gleason_secondary, clinical_tstage,
                num_cores_positive, total_cores,
                surgical_margin, ece_status, svi_status, lni_status,
                ml_prediction, clinical_scores, clinical_summary, discordance_alert
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_data.get('source_id'),
            patient_data.get('source_type', 'manual'),
            patient_data.get('age'),
            patient_data.get('psa'),
            patient_data.get('gleason_primary'),
            patient_data.get('gleason_secondary'),
            patient_data.get('clinical_tstage'),
            patient_data.get('num_cores_positive'),
            patient_data.get('total_cores'),
            patient_data.get('surgical_margin'),
            patient_data.get('ece_status'),
            patient_data.get('svi_status'),
            patient_data.get('lni_status'),

            json.dumps(ml_result),
            json.dumps(scores),
            json.dumps(summary),
            bool(summary.get('discordance_alert'))
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save patient: {e}")
        return False


def _has_any_value(data, field_names):
    return any(data.get(field) not in (None, "") for field in field_names)


def _build_family_history_relatives(data):
    detail = str(data.get("family_history_detail", "")).strip()
    if not detail and not _is_truthy(data.get("family_history_positive")):
        return []
    return [
        {
            "relative_type": "No especificado",
            "cancer_type": "Próstata",
            "age_at_diagnosis": 0,
            "known_mutation": str(data.get("germline_status") or data.get("hrr_gene") or "Desconocido"),
            "deceased": 0,
            "notes": detail,
        }
    ]


def _build_imaging_payloads(data):
    payloads = []
    localized_prior_mri = (
        str(data.get("assessment_state") or "").strip() == "localized_initial"
        and _is_truthy(data.get("prior_mpmri"))
    )
    pirads_score = data.get("pirads_score")
    if pirads_score in (None, "", 0, "0") and localized_prior_mri:
        pirads_score = data.get("prior_mpmri_pirads_score")
    lesion_location = data.get("index_lesion_location")
    lesion_size_mm = data.get("index_lesion_size_mm")
    if _has_any_value(
        data,
        [
            "mpmri_date",
            "pirads_score",
            "prior_mpmri_pirads_score",
            "index_lesion_location",
            "index_lesion_size_mm",
            "mpmri_quality",
        ],
    ) or localized_prior_mri:
        payloads.append(
            {
                "study_date": data.get("mpmri_date") or datetime.now().strftime("%Y-%m-%d"),
                "study_type": "mpMRI",
                "pirads_score": _safe_int(pirads_score, None),
                "pirads_location": lesion_location,
                "lesion_size_mm": _safe_float(lesion_size_mm, 0),
                "precise_score": data.get("precise_score"),
                "findings": {
                    "mpmri_quality": data.get("mpmri_quality"),
                    "planned_biopsy_type": data.get("planned_biopsy_type"),
                    "planned_biopsy_route": data.get("planned_biopsy_route"),
                    "risk_calculator_pathway": data.get("risk_calculator_pathway"),
                    "post_biopsy_mri": _is_truthy(data.get("post_biopsy_mri")),
                    "persistent_lesion_signal": _is_truthy(data.get("persistent_lesion_signal")),
                    "prior_mpmri_targeted_biopsy_status": data.get("prior_mpmri_targeted_biopsy_status"),
                },
                "radiologist_notes": str(data.get("family_history_detail", ""))[:500] or None,
            }
        )
    if _is_truthy(data.get("psma_pet_done")) or str(data.get("imaging_modality", "")) == "PSMA-PET":
        payloads.append(
            {
                "study_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
                "study_type": "PSMA-PET",
                "psma_result": data.get("psma_pet_result") or ("positivo" if _is_truthy(data.get("psma_positive")) else "negativo"),
                "findings": {
                    "psma_positive": _is_truthy(data.get("psma_positive")),
                    "psma_negative_dominant_lesions": _is_truthy(data.get("psma_negative_dominant_lesions")),
                    "conventional_imaging_m0": _is_truthy(data.get("conventional_imaging_m0")),
                },
            }
        )
    if (
        str(data.get("imaging_modality", "")) == "Convencional"
        or _is_truthy(data.get("conventional_imaging_m0"))
        or str(data.get("conventional_imaging_status", "not_restaged") or "not_restaged") in {"M0", "M1"}
    ):
        conventional_status = str(data.get("conventional_imaging_status", "") or "").upper()
        payloads.append(
            {
                "study_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
                "study_type": "Convencional",
                "findings": {
                    "conventional_imaging_m0": _is_truthy(data.get("conventional_imaging_m0")) or conventional_status == "M0",
                    "conventional_imaging_status": conventional_status or ("M0" if _is_truthy(data.get("conventional_imaging_m0")) else ""),
                    "salvage_local_feasible": _is_truthy(data.get("salvage_local_feasible")),
                    "local_salvage_candidate": _is_truthy(data.get("local_salvage_candidate")),
                    "progression_pattern": data.get("progression_pattern"),
                    "castrate_testosterone_status": data.get("castrate_testosterone_status"),
                },
                "radiologist_notes": data.get("psma_pet_result"),
            }
        )
    if _is_truthy(data.get("has_bone_scan")):
        payloads.append(
            {
                "study_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
                "study_type": "Gammagrama",
                "bone_scan_result": "positivo_limitado" if str(data.get("metastasis_site", "M0")) == "Bone" else "negativo",
                "bone_lesion_count": _safe_int(data.get("metastasis_count"), 0),
            }
        )
    return payloads


def _build_mri_fact_payload(data):
    if data.get("assessment_state") not in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        return None
    if not _has_any_value(
        data,
        [
            "mpmri_date",
            "mpmri_quality",
            "pirads_score",
            "index_lesion_location",
            "index_lesion_size_mm",
            "prostate_volume_ml",
        ],
    ):
        return None
    quality = data.get("mpmri_quality") or "No disponible"
    return {
        "fact_date": data.get("mpmri_date") or datetime.now().strftime("%Y-%m-%d"),
        "mpmri_quality": quality,
        "decision_usable": 1 if quality == "Adecuada" else 0,
        "pirads_score": _safe_int(data.get("pirads_score"), None),
        "lesion_location": data.get("index_lesion_location"),
        "lesion_size_mm": _safe_float(data.get("index_lesion_size_mm"), None),
        "prostate_volume_ml": _safe_float(data.get("prostate_volume_ml"), None),
        "findings": {
            "psad": _safe_float(data.get("psad"), None),
            "psa_velocity_ng_ml_year": _safe_float(data.get("psa_velocity_ng_ml_year"), None),
            "risk_calculator_pathway": data.get("risk_calculator_pathway"),
        },
    }


def _build_diagnostic_plan_payload(data, assessment=None):
    state = str(data.get("assessment_state") or "").strip()
    if state not in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        return None
    result = (assessment or {}).get("result_snapshot", {}) if assessment else {}
    primary = result.get("nccn_primary", {}) or {}
    treatments = result.get("eligible_treatments", []) or []
    recommended_pathway = primary.get("trayectoria_recomendada") or primary.get("recommendation") or ""
    summary = primary.get("resumen_del_caso") or (result.get("report_sections", {}) or {}).get("summary", "")
    next_action = ""
    if str(data.get("mpmri_quality", "")) == "Subóptima":
        next_action = "Repetir resonancia magnética multiparamétrica de alta calidad"
    elif str(data.get("planned_biopsy_type", "")) not in {"", "Pendiente"}:
        next_action = f"{data.get('planned_biopsy_type')} por vía {data.get('planned_biopsy_route') or 'no definida'}"
    elif recommended_pathway:
        next_action = recommended_pathway
    if not summary and not next_action and not treatments:
        return None
    trigger_conditions = []
    if _safe_int(data.get("pirads_score"), 0) >= 4:
        trigger_conditions.append("Lesión PI-RADS 4-5")
    if _safe_float(data.get("psad"), 0) >= 0.15:
        trigger_conditions.append("Densidad del antígeno prostático específico elevada")
    if _is_truthy(data.get("dre_suspicious")):
        trigger_conditions.append("Tacto rectal sospechoso")
    if _safe_float(data.get("psa_velocity_ng_ml_year"), 0) >= 0.75:
        trigger_conditions.append("Cinética de antígeno prostático específico en ascenso")
    if state == "post_negative_biopsy_followup" and _is_truthy(data.get("persistent_lesion_signal")):
        trigger_conditions.append("Persistencia de lesión sospechosa tras biopsia benigna")
    if not trigger_conditions:
        trigger_conditions.append("Reevaluación estructurada según la Red Nacional Integral del Cáncer (NCCN) y la Asociación Europea de Urología (EAU)")
    return {
        "source_state": state,
        "plan_type": "reactivacion_diagnostica" if state == "post_negative_biopsy_followup" else "confirmacion_histologica",
        "plan_status": "planificado",
        "management_intent_status": "candidate",
        "plan_summary": summary,
        "recommended_pathway": recommended_pathway or next_action,
        "next_action": next_action or recommended_pathway,
        "risk_calculator_pathway": data.get("risk_calculator_pathway"),
        "trigger_conditions": trigger_conditions,
        "evidence_context": [
            "La recomendación principal sigue anclada en la Red Nacional Integral del Cáncer (NCCN) 5.2026 y la Asociación Europea de Urología (EAU) 2026.",
            "El plan diagnóstico se persiste como hecho temprano y no como confirmación histológica.",
        ],
    }


def _build_biopsy_trigger_payload(data, assessment=None):
    state = str(data.get("assessment_state") or "").strip()
    if state not in {"diagnostic_workup", "post_negative_biopsy_followup"}:
        return None
    result = (assessment or {}).get("result_snapshot", {}) if assessment else {}
    primary = result.get("nccn_primary", {}) or {}
    treatments = result.get("eligible_treatments", []) or []
    biopsy_recommended = any("biops" in str((item if isinstance(item, str) else item.get("name", ""))).lower() for item in treatments)
    trigger_reason = data.get("repeat_biopsy_trigger") if state == "post_negative_biopsy_followup" else None
    if not trigger_reason:
        if biopsy_recommended:
            trigger_reason = "Sospecha clínica suficiente para confirmación histológica"
        else:
            trigger_reason = "Mantener trigger estructurado si cambian densidad, MRI o cinética del antígeno prostático específico"
    activation_conditions = []
    if _safe_int(data.get("pirads_score"), 0) >= 4:
        activation_conditions.append("Lesión PI-RADS 4-5")
    if _safe_float(data.get("psad"), 0) >= 0.15:
        activation_conditions.append("PSAD >= 0.15")
    if _is_truthy(data.get("dre_suspicious")):
        activation_conditions.append("Tacto rectal sospechoso")
    if state == "post_negative_biopsy_followup" and _is_truthy(data.get("persistent_lesion_signal")):
        activation_conditions.append("Lesión persistente tras biopsia benigna")
    if not activation_conditions:
        activation_conditions.append(primary.get("recommendation") or "Reevaluación diagnóstica con control seriado")
    return {
        "source_state": state,
        "trigger_reason": trigger_reason,
        "priority": "alta" if biopsy_recommended else "vigilada",
        "planned_biopsy_type": (data.get("planned_biopsy_type") or data.get("prior_biopsy_type") or "Pendiente") if biopsy_recommended else "Pendiente",
        "planned_biopsy_route": (data.get("planned_biopsy_route") or "No definida") if biopsy_recommended else "No definida",
        "trigger_status": "pendiente_de_confirmacion",
        "management_intent_status": "candidate",
        "activation_conditions": activation_conditions,
    }


def _build_genomic_payload(data):
    if not _has_any_value(
        data,
        [
            "genomic_classifier",
            "genomic_classifier_result",
            "decipher_risk",
            "hrr_status",
            "hrr_gene",
            "brca2_status",
            "msi_status",
            "molecular_report_date",
            "molecular_assay_date",
        ],
    ):
        return None

    test_type = "Panel_HRR"
    if str(data.get("genomic_classifier", "No realizado")) != "No realizado":
        classifier = str(data.get("genomic_classifier"))
        if classifier == "Oncotype":
            test_type = "OncotypeDX_GPS"
        else:
            test_type = classifier
    elif str(data.get("decipher_risk", "No realizado")) != "No realizado":
        test_type = "Decipher"

    actionable_findings = []
    if str(data.get("hrr_status", "")).lower() in {"positivo", "positive"}:
        actionable_findings.append(f"HRR {data.get('hrr_gene') or 'documentado'}")
    if str(data.get("brca2_status", "")).lower() in {"positivo", "positive"}:
        actionable_findings.append("BRCA2")
    if _is_truthy(data.get("tmb_high")):
        actionable_findings.append("TMB-high")
    if str(data.get("genomic_classifier_result", "No aplica")) not in {"", "No aplica"}:
        actionable_findings.append(
            f"{test_type}:{data.get('genomic_classifier_result')}"
        )
    if _present_text := str(data.get("biomarker_source") or data.get("molecular_assay_source") or "").strip():
        actionable_findings.append(f"Fuente:{_present_text}")

    return {
        "test_date": data.get("molecular_report_date") or data.get("molecular_assay_date") or datetime.now().strftime("%Y-%m-%d"),
        "test_type": test_type,
        "decipher_risk": None if str(data.get("decipher_risk", "No realizado")) == "No realizado" else data.get("decipher_risk"),
        "prolaris_score": data.get("genomic_classifier_result") if test_type == "Prolaris" else None,
        "gps_score": data.get("genomic_classifier_result") if test_type == "OncotypeDX_GPS" else None,
        "brca2_status": data.get("brca2_status"),
        "msi_status": data.get("msi_status"),
        "hrr_overall": data.get("hrr_status", "Desconocido"),
        "tmb_score": 10 if _is_truthy(data.get("tmb_high")) else None,
        "actionable_findings": actionable_findings,
        "brca1_status": "Desconocido",
        "atm_status": "Mutado" if str(data.get("hrr_gene")) == "ATM" else "Desconocido",
        "chek2_status": "Mutado" if str(data.get("hrr_gene")) == "CHEK2" else "Desconocido",
        "palb2_status": "Mutado" if str(data.get("hrr_gene")) == "PALB2" else "Desconocido",
        "cdk12_status": "Mutado" if str(data.get("hrr_gene")) == "CDK12" else "Desconocido",
    }


def _build_biopsy_payload(data):
    assessment_state = str(data.get("assessment_state") or "").strip()
    has_histology = _has_any_value(
        data,
        [
            "gleason_primary",
            "gleason_secondary",
            "isup_grade",
            "num_cores_positive",
            "total_cores",
            "percent_pattern_4",
            "cribriform_pattern",
            "intraductal_carcinoma",
        ],
    )
    if assessment_state in {"diagnostic_workup", "post_negative_biopsy_followup"} or not has_histology:
        return None
    adverse_histology_variant_type = str(data.get("adverse_histology_variant_type", "none") or "none").strip()
    if adverse_histology_variant_type == "none" and _is_truthy(data.get("rare_histology_variant")):
        adverse_histology_variant_type = "other_aggressive_unspecified"
    adverse_histology_variant_detail = str(data.get("adverse_histology_variant_detail", "") or "").strip()
    return {
        "biopsy_date": data.get("prior_biopsy_date") or data.get("mpmri_date") or datetime.now().strftime("%Y-%m-%d"),
        "biopsy_type": data.get("prior_biopsy_type") or data.get("planned_biopsy_type") or "sistematica",
        "biopsy_context": "rebiopsia" if data.get("assessment_state") == "post_negative_biopsy_followup" else "diagnostica",
        "total_cores": _safe_int(data.get("total_cores"), 12),
        "positive_cores": _safe_int(data.get("num_cores_positive"), 0),
        "gleason_primary": _safe_int(data.get("gleason_primary"), None),
        "gleason_secondary": _safe_int(data.get("gleason_secondary"), None),
        "isup_grade": _safe_int(data.get("isup_grade"), None),
        "porcentaje_patron_4": _safe_float(data.get("percent_pattern_4"), 0),
        "max_core_involvement_pct": _safe_float(data.get("max_core_involvement"), 0) * 100,
        "patron_cribiforme": 1 if _is_truthy(data.get("cribriform_pattern")) else 0,
        "carcinoma_intraductal": 1 if _is_truthy(data.get("intraductal_carcinoma")) else 0,
        "adverse_histology_variant_type": adverse_histology_variant_type,
        "adverse_histology_variant_detail": adverse_histology_variant_detail,
        "pathologist_notes": " | ".join(
            item
            for item in [
                str(data.get("repeat_biopsy_trigger") or "").strip(),
                "MRI-targeted previa" if _is_truthy(data.get("prior_biopsy_mri_targeted")) else "",
                f"Variante adversa: {adverse_histology_variant_type}" if adverse_histology_variant_type not in {"", "none"} else "",
                adverse_histology_variant_detail,
            ]
            if item
        ),
    }


def _build_pro_payload(data):
    if not _has_any_value(
        data,
        [
            "ipss_score",
            "iief5_score",
            "baseline_qol",
            "baseline_urinary_qol",
            "baseline_sexual_qol",
            "baseline_bowel_qol",
        ],
    ):
        return None
    notes = []
    if data.get("baseline_urinary_qol") not in (None, ""):
        notes.append(f"Función urinaria basal 0-100: {data.get('baseline_urinary_qol')}")
    if data.get("baseline_sexual_qol") not in (None, ""):
        notes.append(f"Función sexual basal 0-100: {data.get('baseline_sexual_qol')}")
    if data.get("baseline_bowel_qol") not in (None, ""):
        notes.append(f"Función intestinal basal 0-100: {data.get('baseline_bowel_qol')}")
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "ipss_total": _safe_int(data.get("ipss_score"), None),
        "iief5_score": _safe_int(data.get("iief5_score"), None),
        "eq5d_vas": _safe_int(data.get("baseline_qol"), None),
        "clinician_notes": " | ".join(notes) if notes else None,
    }


def _should_enroll_as(data):
    return (
        data.get("assessment_state") == "localized_initial"
        and str(data.get("management_intent_status") or "").strip() in {"chosen", "delivered", "completed"}
        and str(data.get("selected_management") or "").strip() == "active_surveillance"
    )


def _build_bcr_payload(data):
    if data.get("assessment_state") not in {"post_prostatectomy", "recurrence_bcr"}:
        return None
    if not _has_any_value(data, ["time_to_recurrence_months", "local_therapy_date", "salvage_local_feasible", "local_salvage_candidate"]):
        return None
    primary_treatment = "RP" if _is_truthy(data.get("prior_prostatectomy")) or data.get("assessment_state") == "post_prostatectomy" else "RT"
    salvage_treatment = "observation"
    if _is_truthy(data.get("salvage_local_feasible")) or _is_truthy(data.get("local_salvage_candidate")):
        salvage_treatment = "sRT"
    return {
        "primary_treatment": primary_treatment,
        "primary_treatment_date": data.get("local_therapy_date"),
        "bcr_detected": 1 if data.get("assessment_state") == "recurrence_bcr" else 0,
        "bcr_date": datetime.now().strftime("%Y-%m-%d"),
        "bcr_psa": data.get("psa_current") or data.get("psa_postop") or data.get("baseline_psa"),
        "bcr_definition": "BCR2" if _is_truthy(data.get("bcr2")) else "BCR",
        "psadt_at_bcr": data.get("psadt_months"),
        "time_to_bcr_months": data.get("time_to_recurrence_months"),
        "salvage_treatment": salvage_treatment,
        "salvage_response": "pendiente",
    }


def _build_surgery_payload(data):
    if data.get("assessment_state") != "post_prostatectomy" and not _has_any_value(data, ["pathologic_stage", "margin_location", "surgical_margin"]):
        return None
    capra_s_score = None
    try:
        from clinical_scores import calculate_capra_s

        capra_s_score = calculate_capra_s(data).get("score")
    except Exception:
        capra_s_score = None
    return {
        "surgery_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
        "surgery_type": "RP_robotica",
        "pathological_gleason_primary": _safe_int(data.get("gleason_primary"), None),
        "pathological_gleason_secondary": _safe_int(data.get("gleason_secondary"), None),
        "pathological_isup": _safe_int(data.get("isup_grade"), None),
        "pathological_stage": data.get("pathologic_stage"),
        "surgical_margin_status": 1 if _is_truthy(data.get("surgical_margin")) else 0,
        "margin_location": data.get("margin_location"),
        "ece_pathological": 1 if _is_truthy(data.get("ece_status")) else 0,
        "svi_pathological": 1 if _is_truthy(data.get("svi_status")) else 0,
        "lni_pathological": 1 if _is_truthy(data.get("lni_status")) else 0,
        "capra_s_score": capra_s_score,
    }


def _build_radiation_payload(data):
    if not (_is_truthy(data.get("rt_primary_received")) or _is_truthy(data.get("prior_radiation"))):
        return None
    return {
        "rt_date": data.get("local_therapy_date") or datetime.now().strftime("%Y-%m-%d"),
        "rt_context": "definitiva" if _is_truthy(data.get("rt_primary_received")) else "salvamento",
        "rt_technique": "IMRT",
        "target": "prostata" if _is_truthy(data.get("rt_primary_received")) else "lecho",
        "total_dose_gy": _safe_float(data.get("rt_primary_dose_gy"), 0),
        "fractions": None,
        "dose_per_fraction_gy": None,
    }

def register_new_patient(data, assessment=None):
    """
    Registra un nuevo paciente y su línea base clínica + tratamiento inicial.
    Retorna (success: bool, message: str)
    """
    try:
        assessment_state = str(data.get("assessment_state") or "").strip()
        advanced_states = {
            "adt_progression_verification",
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume",
            "m0_crpc",
            "m1_crpc",
        }
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 1. Identidad
        try:
            c.execute('''
                INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date)
                VALUES (?, ?, ?, DATE('now'))
            ''', (data.get('nss'), data.get('full_name'), data.get('dob')))
            patient_id = c.lastrowid
        except sqlite3.IntegrityError:
            conn.close()
            return None, f"El paciente con NSS {data.get('nss')} ya existe."

        # 2. Perfil Clínico Basal
        comorbilidades = json.dumps({
            'seizure': _is_truthy(data.get('comorbidity_seizure')),
            'cardio': _is_truthy(data.get('comorbidity_cardio'))
        })
        metastasis_site = data.get('metastasis_site') or 'M0'
        metastatic_count = _safe_int(data.get('metastasis_count'), 0)
        if metastasis_site != 'M0' and metastatic_count == 0:
            metastatic_count = 1
        genomic_done = 1 if _is_truthy(data.get('genomic_test_done')) else 0
        if not genomic_done and _has_any_value(data, ['hrr_status', 'hrr_gene', 'biomarker_source', 'molecular_report_date', 'genomic_classifier', 'decipher_risk']):
            genomic_done = 1
        
        c.execute('''
            INSERT INTO clinical_baseline (
                patient_id, baseline_psa, testosterone_baseline, hemoglobin, alp, ldh, albumin,
                tnm_stage, gleason_score, metastasis_site, metastasis_count, volume_disease,
                ecog_score,
                genomic_test_done, hrr_status, msi_status, child_pugh_score, pain_symptoms,
                comorbidities_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            data.get('baseline_psa'), data.get('testosterone_baseline'),
            data.get('hemoglobin'), data.get('alp'), data.get('ldh'), data.get('albumin'),
            'TxNxMx', # Placeholder o derivado
            0, # Placeholder Gleason
            metastasis_site,
            metastatic_count,
            data.get('volume_disease'),
            0, # ECOG placeholder
            genomic_done,
            data.get('hrr_status'),
            data.get('msi_status'),
            data.get('child_pugh_score'),
            data.get('pain_symptoms'),
            comorbilidades
        ))

        # 3. Historial Terapéutico Inicial
        should_persist_treatment = bool(data.get("drug_scheme")) and (not assessment_state or assessment_state in advanced_states)
        if should_persist_treatment:
            c.execute('''
                INSERT INTO treatment_history (
                    patient_id, line_of_therapy, drug_scheme, start_date, outcome
                ) VALUES (?, ?, ?, DATE('now'), 'Ongoing')
            ''', (
                patient_id,
                data.get('line_of_therapy') or (2 if assessment_state in {'m0_crpc', 'm1_crpc'} else 1),
                data.get('drug_scheme')
            ))

        # 4. Historial Clínico Previo (Fase 6)
        c.execute('''
            INSERT INTO prior_clinical_history (
                patient_id,
                rt_primary_received, rt_primary_dose_gy, rt_metastasis_history,
                prior_docetaxel_cycles, prior_arpi_agent, prior_arpi_duration
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            1 if _is_truthy(data.get('rt_primary_received')) else 0,
            _safe_float(data.get('rt_primary_dose_gy'), 0),
            data.get('rt_metastasis_history', '[]'), # JSON string expected
            _safe_int(data.get('prior_docetaxel_cycles'), 0),
            data.get('prior_arpi_agent'),
            _safe_int(data.get('prior_arpi_duration'), 0)
        ))

        conn.commit()
        conn.close()

        if _has_any_value(data, ['estado_residencia', 'seguridad_social', 'escolaridad', 'tabaquismo', 'ipss_score', 'iief5_score']):
            save_demographics(
                patient_id,
                {
                    **data,
                    'diabetes_mellitus': 1 if _is_truthy(data.get('diabetes_mellitus')) else 0,
                    'hipertension': 1 if _is_truthy(data.get('hipertension')) else 0,
                    'sindrome_metabolico': 1 if _is_truthy(data.get('sindrome_metabolico')) else 0,
                },
            )

        relatives = _build_family_history_relatives(data)
        if relatives:
            save_family_history(patient_id, relatives)

        for imaging_payload in _build_imaging_payloads(data):
            save_imaging_study(patient_id, imaging_payload)

        mri_fact_payload = _build_mri_fact_payload(data)
        if mri_fact_payload:
            save_mri_fact(
                patient_id,
                {
                    **mri_fact_payload,
                    "assessment_id": data.get("assessment_id") or (assessment or {}).get("id"),
                },
            )

        diagnostic_plan_payload = _build_diagnostic_plan_payload(data, assessment)
        if diagnostic_plan_payload:
            save_diagnostic_plan(
                patient_id,
                {
                    **diagnostic_plan_payload,
                    "assessment_id": data.get("assessment_id") or (assessment or {}).get("id"),
                },
            )

        biopsy_trigger_payload = _build_biopsy_trigger_payload(data, assessment)
        if biopsy_trigger_payload:
            save_biopsy_trigger(
                patient_id,
                {
                    **biopsy_trigger_payload,
                    "assessment_id": data.get("assessment_id") or (assessment or {}).get("id"),
                },
            )

        genomic_payload = _build_genomic_payload(data)
        if genomic_payload:
            save_genomic_profile(patient_id, genomic_payload)

        biopsy_payload = _build_biopsy_payload(data)
        if biopsy_payload:
            save_biopsy(patient_id, biopsy_payload)

        pro_payload = _build_pro_payload(data)
        if pro_payload:
            save_pro_assessment(patient_id, pro_payload)

        if _should_enroll_as(data):
            enroll_in_as(
                patient_id,
                {
                    "protocol": "NCCN_VL",
                    "criteria_met": {
                        "confirmatory_biopsy_planned": _is_truthy(data.get("confirmatory_biopsy_planned")),
                        "prior_mpmri": _is_truthy(data.get("prior_mpmri")),
                    },
                },
            )

        bcr_payload = _build_bcr_payload(data)
        if bcr_payload:
            save_bcr(patient_id, bcr_payload)

        surgery_payload = _build_surgery_payload(data)
        if surgery_payload:
            save_surgical_details(patient_id, surgery_payload)

        radiation_payload = _build_radiation_payload(data)
        if radiation_payload:
            save_radiation_details(patient_id, radiation_payload)

        logger.info(f"Paciente {data.get('nss')} registrado con éxito (ID: {patient_id})")
        return patient_id, "Registro exitoso"

    except Exception as e:
        logger.error(f"Error registering patient: {e}")
        return None, str(e)

def get_patient_history(nss_or_id):
    """
    Recupera TODA la información del paciente para el Perfil Longitudinal.
    Incluye datos de las Fases B & C (tablas nuevas).
    Acepta NSS (string) o ID numérico del paciente.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Identity — buscar por NSS primero, luego por ID
        identity = _resolve_identity_row(c, nss_or_id)

        if not identity:
            conn.close()
            return None

        patient_id = identity['id']

        # 2. Baseline
        c.execute("SELECT * FROM clinical_baseline WHERE patient_id = ?", (patient_id,))
        baseline = c.fetchone()

        # 3. Follow-up Visits
        c.execute("SELECT * FROM follow_up_visits WHERE patient_id = ? ORDER BY visit_date ASC", (patient_id,))
        follow_ups = _hydrate_followup_rows(c.fetchall())

        # 4. Treatment History
        c.execute("SELECT * FROM treatment_history WHERE patient_id = ? ORDER BY start_date ASC", (patient_id,))
        treatments = [dict(row) for row in c.fetchall()]

        # 5. Prior Clinical History (Fase 6)
        c.execute("SELECT * FROM prior_clinical_history WHERE patient_id = ?", (patient_id,))
        prior_history = c.fetchone()

        # ── FASE B & C: Tablas nuevas ──────────────────────────────────────
        # 6. Demographics
        c.execute("SELECT * FROM patient_demographics WHERE patient_id = ?", (patient_id,))
        demographics = c.fetchone()

        # 7. Family History
        c.execute("SELECT * FROM family_history_detail WHERE patient_id = ?", (patient_id,))
        family_history = [dict(row) for row in c.fetchall()]

        # 8. Imaging
        c.execute("SELECT * FROM imaging_studies WHERE patient_id = ? ORDER BY study_date DESC", (patient_id,))
        imaging = [dict(row) for row in c.fetchall()]

        c.execute("SELECT * FROM mri_facts WHERE patient_id = ? ORDER BY fact_date DESC, id DESC", (patient_id,))
        mri_facts = [dict(row) for row in c.fetchall()]
        for item in mri_facts:
            item["findings"] = _parse_json_blob(item.pop("findings_json", None), {})

        # 9. Genomics
        c.execute("SELECT * FROM genomic_profile WHERE patient_id = ? ORDER BY test_date DESC LIMIT 1", (patient_id,))
        genomics = c.fetchone()

        # 10. Biopsies
        c.execute("SELECT * FROM biopsy_details WHERE patient_id = ? ORDER BY biopsy_date ASC", (patient_id,))
        biopsies = [dict(row) for row in c.fetchall()]

        c.execute("SELECT * FROM diagnostic_plans WHERE patient_id = ? ORDER BY plan_date DESC, id DESC", (patient_id,))
        diagnostic_plans = [dict(row) for row in c.fetchall()]
        for item in diagnostic_plans:
            item["trigger_conditions"] = _parse_json_blob(item.pop("trigger_conditions_json", None), [])
            item["evidence_context"] = _parse_json_blob(item.pop("evidence_context_json", None), [])

        c.execute("SELECT * FROM biopsy_trigger_events WHERE patient_id = ? ORDER BY trigger_date DESC, id DESC", (patient_id,))
        biopsy_triggers = [dict(row) for row in c.fetchall()]
        for item in biopsy_triggers:
            item["activation_conditions"] = _parse_json_blob(item.pop("activation_conditions_json", None), [])

        # 11. Active Surveillance
        c.execute("SELECT * FROM active_surveillance WHERE patient_id = ? ORDER BY enrollment_date DESC LIMIT 1", (patient_id,))
        as_record = c.fetchone()

        # 12. BCR
        c.execute("SELECT * FROM biochemical_recurrence WHERE patient_id = ?", (patient_id,))
        bcr = c.fetchone()

        # 13. Surgery
        c.execute("SELECT * FROM surgical_details WHERE patient_id = ?", (patient_id,))
        surgery = c.fetchone()

        # 14. Radiation
        c.execute("SELECT * FROM radiation_details WHERE patient_id = ? ORDER BY rt_date ASC", (patient_id,))
        radiation = [dict(row) for row in c.fetchall()]

        # 15. PROs
        c.execute("SELECT * FROM patient_pros WHERE patient_id = ? ORDER BY assessment_date ASC", (patient_id,))
        pros = [dict(row) for row in c.fetchall()]

        # 16. Alerts
        c.execute("SELECT * FROM smart_alerts WHERE patient_id = ? AND acknowledged = 0 ORDER BY alert_date DESC", (patient_id,))
        alerts = [dict(row) for row in c.fetchall()]

        # 17. Pivotal Study Matching
        c.execute("SELECT * FROM pivotal_study_matching WHERE patient_id = ? ORDER BY evaluation_date DESC", (patient_id,))
        pivotal_matches = [dict(row) for row in c.fetchall()]

        latest_assessment = _fetch_latest_clinical_assessment(c, patient_id)
        c.execute(
            "SELECT * FROM patient_state_timeline WHERE patient_id = ? ORDER BY created_at ASC, id ASC",
            (patient_id,),
        )
        state_timeline = _hydrate_timeline_rows(c.fetchall())

        c.execute(
            "SELECT * FROM followup_agenda_items WHERE patient_id = ? ORDER BY COALESCE(due_at, ''), id ASC",
            (patient_id,),
        )
        agenda_items = _hydrate_agenda_rows(c.fetchall())

        c.execute(
            "SELECT * FROM stage_visit_records WHERE patient_id = ? ORDER BY visit_date DESC, id DESC",
            (patient_id,),
        )
        stage_visits = _hydrate_stage_visit_rows(c.fetchall())

        c.execute(
            "SELECT * FROM data_provenance WHERE patient_id = ? ORDER BY source_date DESC, id DESC",
            (patient_id,),
        )
        data_provenance = _hydrate_provenance_rows(c.fetchall())

        c.execute(
            "SELECT * FROM patient_events WHERE patient_id = ? ORDER BY event_date DESC, id DESC",
            (patient_id,),
        )
        patient_events = _hydrate_event_rows(c.fetchall())

        c.execute(
            "SELECT * FROM clinical_signal_snapshots WHERE patient_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (patient_id,),
        )
        latest_signal_snapshot = _hydrate_signal_rows(c.fetchall())

        c.execute(
            "SELECT * FROM state_transition_proposals WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        transition_proposals = _hydrate_transition_rows(c.fetchall())

        c.execute(
            "SELECT * FROM recommendation_audit WHERE patient_id = ? ORDER BY recorded_at DESC, id DESC",
            (patient_id,),
        )
        recommendation_audit = _hydrate_recommendation_audit_rows(c.fetchall())

        c.execute(
            "SELECT * FROM source_documents WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        source_documents = _hydrate_source_document_rows(c.fetchall())

        c.execute(
            '''
            SELECT * FROM document_extraction_candidates
            WHERE patient_id = ?
            ORDER BY document_id DESC, id ASC
            ''',
            (patient_id,),
        )
        document_candidates = _hydrate_document_candidate_rows(c.fetchall())

        c.execute(
            "SELECT * FROM document_verification_tasks WHERE patient_id = ? ORDER BY updated_at DESC, id DESC",
            (patient_id,),
        )
        document_tasks = _hydrate_document_task_rows(c.fetchall())

        c.execute(
            "SELECT * FROM verified_document_facts WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        verified_document_facts = _hydrate_verified_fact_rows(c.fetchall())

        conn.close()

        return {
            'identity': dict(identity),
            'baseline': dict(baseline) if baseline else {},
            'follow_ups': follow_ups,
            'treatments': treatments,
            'prior_history': _decorate_prior_history(prior_history),
            # Fase B & C
            'demographics': dict(demographics) if demographics else {},
            'family_history': family_history,
            'imaging': imaging,
            'mri_facts': mri_facts,
            'genomics': dict(genomics) if genomics else {},
            'biopsies': biopsies,
            'diagnostic_plans': diagnostic_plans,
            'biopsy_triggers': biopsy_triggers,
            'active_surveillance': dict(as_record) if as_record else {},
            'bcr': dict(bcr) if bcr else {},
            'surgery': dict(surgery) if surgery else {},
            'radiation': radiation,
            'pros': pros,
            'alerts': alerts,
            'pivotal_matches': pivotal_matches,
            'latest_assessment': latest_assessment,
            'state_timeline': state_timeline,
            'care_overlays': _decorate_prior_history(prior_history).get("care_overlays", []),
            'agenda_items': agenda_items,
            'stage_visits': stage_visits,
            'data_provenance': data_provenance,
            'patient_events': patient_events,
            'latest_signal_snapshot': latest_signal_snapshot[0] if latest_signal_snapshot else {},
            'transition_proposals': transition_proposals,
            'recommendation_audit': recommendation_audit,
            'source_documents': source_documents,
            'document_candidates': document_candidates,
            'document_verification_tasks': document_tasks,
            'verified_document_facts': verified_document_facts,
        }
    except Exception as e:
        logger.error(f"Error fetching patient history: {e}")
        return None

def add_followup_visit(data):
    """
    Registra una visita de seguimiento.
    data: {patient_id, psa, testosterone, toxicity, metabolic, treatment, status}
    """
    return save_stage_visit_bundle(int(data.get("patient_id")), data)


def _normalize_list_value(value):
    if isinstance(value, list):
        return [item for item in value if _is_present(item)]
    if value in (None, ""):
        return []
    return [value]


def _build_imaging_payload_from_visit(data):
    modality = data.get("imaging_modality")
    if not _is_present(modality):
        return None
    findings = {}
    if modality == "PSMA-PET":
        findings = {
            "lesion_locations": _normalize_list_value(data.get("psma_lesion_locations")),
            "psma_total_lesions": _safe_int(data.get("psma_total_lesions"), 0),
            "psma_suv_bucket": data.get("psma_suv_bucket"),
            "psma_negative_dominant_lesions": _is_truthy(data.get("psma_negative_dominant_lesions")),
        }
        return {
            "study_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
            "study_type": "PSMA-PET",
            "psma_result": "Positivo" if findings["lesion_locations"] or _safe_float(data.get("psma_suv_max")) else "Negativo/indeterminado",
            "psma_suv_max": _safe_float(data.get("psma_suv_max"), None),
            "findings": findings,
        }
    if modality == "Gammagrama óseo":
        findings = {
            "distribution": _normalize_list_value(data.get("bone_distribution")),
            "bone_lesion_count": _safe_int(data.get("bone_lesion_count"), 0),
        }
        return {
            "study_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
            "study_type": "Gammagrama óseo",
            "bone_scan_result": "Positivo" if findings["bone_lesion_count"] else "Negativo/indeterminado",
            "bone_lesion_count": findings["bone_lesion_count"],
            "findings": findings,
        }
    if modality == "TAC convencional":
        findings = {
            "ct_summary": data.get("ct_summary"),
            "ct_locations": _normalize_list_value(data.get("ct_locations")),
            "conventional_imaging_status": "M1" if data.get("ct_summary") == "Metástasis" else "M0" if data.get("ct_summary") in {"Sin lesiones sospechosas", "Ganglios sospechosos"} else "",
        }
        return {
            "study_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
            "study_type": "TAC convencional",
            "findings": findings,
            "radiologist_notes": data.get("clinician_notes"),
        }
    return None


def _build_pro_payload_from_visit(data):
    keys = ("ipss_total", "iief5_score", "eq5d_vas", "fact_p_total", "pad_usage", "bpi_worst_pain", "bpi_average_pain")
    if not any(_is_present(data.get(key)) for key in keys):
        return None
    return {
        "date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
        "ipss_total": _safe_int(data.get("ipss_total"), None),
        "ipss_qol": _safe_int(data.get("ipss_qol"), None),
        "pad_usage": _safe_int(data.get("pad_usage"), 0),
        "iief5_score": _safe_int(data.get("iief5_score"), None),
        "pde5i_use": _safe_int(data.get("pde5i_use", 0), 0),
        "bpi_worst_pain": _safe_int(data.get("bpi_worst_pain"), None),
        "bpi_average_pain": _safe_int(data.get("bpi_average_pain"), None),
        "eq5d_vas": _safe_int(data.get("eq5d_vas"), None),
        "fact_p_total": _safe_float(data.get("fact_p_total"), None),
        "clinician_notes": data.get("clinician_notes"),
    }


def _build_surgery_payload_from_visit(data):
    keys = (
        "surgery_type",
        "surgical_approach",
        "nerve_sparing",
        "nodes_removed",
        "nodes_positive",
        "margin_location",
        "capra_s_score",
        "continence_status",
        "potency_status",
        "pads_per_day",
        "pde5i_use",
    )
    if not any(_is_present(data.get(key)) for key in keys):
        return None
    return {
        "surgery_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
        "surgery_type": data.get("surgery_type"),
        "surgical_approach": data.get("surgical_approach"),
        "nerve_sparing": data.get("nerve_sparing"),
        "nodes_removed": _safe_int(data.get("nodes_removed"), 0),
        "nodes_positive": _safe_int(data.get("nodes_positive"), 0),
        "margin_location": data.get("margin_location"),
        "capra_s_score": _safe_int(data.get("capra_s_score"), None),
        "continence_status": data.get("continence_status"),
        "potency_status": data.get("potency_status"),
        "pads_per_day": _safe_int(data.get("pads_per_day"), 0),
        "pde5i_use": _safe_int(data.get("pde5i_use", 0), 0),
        "recovery_notes": data.get("clinician_notes"),
        "pathological_stage": data.get("pathological_stage"),
        "pathological_isup": _safe_int(data.get("pathological_isup"), None),
        "surgical_margin_status": _safe_int(data.get("surgical_margin_status"), 0),
    }


def _build_radiation_payload_from_visit(data):
    keys = (
        "rt_context",
        "fractions",
        "total_dose_gy",
        "dose_per_fraction_gy",
        "session_duration_minutes",
        "hematuria",
        "dysuria",
        "gu_toxicity_grade",
        "gi_toxicity_grade",
    )
    if not any(_is_present(data.get(key)) for key in keys):
        return None
    return {
        "rt_date": data.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
        "rt_context": data.get("rt_context"),
        "rt_technique": data.get("rt_technique"),
        "target": data.get("target"),
        "total_dose_gy": _safe_float(data.get("total_dose_gy"), None),
        "fractions": _safe_int(data.get("fractions"), None),
        "dose_per_fraction_gy": _safe_float(data.get("dose_per_fraction_gy"), None),
        "session_duration_minutes": _safe_int(data.get("session_duration_minutes"), None),
        "hematuria": data.get("hematuria"),
        "dysuria": data.get("dysuria"),
        "anemia_related": data.get("anemia_rt"),
        "gu_toxicity_grade": _safe_int(data.get("gu_toxicity_grade"), 0),
        "gi_toxicity_grade": _safe_int(data.get("gi_toxicity_grade"), 0),
        "notes": data.get("clinician_notes"),
        "late_toxicity_json": {
            "hematuria": data.get("hematuria"),
            "dysuria": data.get("dysuria"),
            "anemia_related": data.get("anemia_rt"),
        },
    }


def _upsert_agenda_items(cursor, patient_id, items):
    existing = {}
    cursor.execute(
        "SELECT agenda_key, status, due_at, completed_at, visit_record_id FROM followup_agenda_items WHERE patient_id = ?",
        (patient_id,),
    )
    for row in cursor.fetchall():
        existing[row[0]] = {
            "status": row[1],
            "due_at": row[2],
            "completed_at": row[3],
            "visit_record_id": row[4],
        }
    active_keys = {item["agenda_key"] for item in items if item.get("agenda_key")}
    if active_keys:
        cursor.execute(
            f"""
            UPDATE followup_agenda_items
            SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ?
              AND agenda_key NOT IN ({",".join(["?"] * len(active_keys))})
              AND status NOT IN ('completed', 'superseded', 'cancelled')
            """,
            (patient_id, *active_keys),
        )
    else:
        cursor.execute(
            '''
            UPDATE followup_agenda_items
            SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ? AND status NOT IN ('completed', 'superseded', 'cancelled')
            ''',
            (patient_id,),
        )
    for item in items:
        previous = existing.get(item["agenda_key"], {})
        status = item.get("status")
        completed_at = None
        visit_record_id = None
        if previous.get("status") == "completed" and previous.get("due_at") == item.get("due_at"):
            status = "completed"
            completed_at = previous.get("completed_at")
            visit_record_id = previous.get("visit_record_id")
        cursor.execute(
            '''
            INSERT INTO followup_agenda_items (
                patient_id, agenda_key, state, management_track, item_type, title, status, priority,
                due_at, window_start, window_end, required_inputs_json, completion_rule_json,
                evidence_basis_json, comparator_basis_json, generated_from_event, summary,
                blockers_json, reasoning_json, completed_at, visit_record_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(patient_id, agenda_key) DO UPDATE SET
                state=excluded.state,
                management_track=excluded.management_track,
                item_type=excluded.item_type,
                title=excluded.title,
                status=excluded.status,
                priority=excluded.priority,
                due_at=excluded.due_at,
                window_start=excluded.window_start,
                window_end=excluded.window_end,
                required_inputs_json=excluded.required_inputs_json,
                completion_rule_json=excluded.completion_rule_json,
                evidence_basis_json=excluded.evidence_basis_json,
                comparator_basis_json=excluded.comparator_basis_json,
                generated_from_event=excluded.generated_from_event,
                summary=excluded.summary,
                blockers_json=excluded.blockers_json,
                reasoning_json=excluded.reasoning_json,
                completed_at=excluded.completed_at,
                visit_record_id=excluded.visit_record_id,
                updated_at=CURRENT_TIMESTAMP
            ''',
            (
                patient_id,
                item.get("agenda_key"),
                item.get("state"),
                item.get("management_track"),
                item.get("item_type"),
                item.get("title"),
                status,
                item.get("priority"),
                item.get("due_at"),
                item.get("window_start"),
                item.get("window_end"),
                _json_blob(item.get("required_inputs", [])),
                _json_blob(item.get("completion_rule", {})),
                _json_blob(item.get("evidence_basis", [])),
                _json_blob(item.get("comparator_basis", [])),
                item.get("generated_from_event"),
                item.get("summary"),
                _json_blob(item.get("blockers", [])),
                _json_blob(item.get("reasoning", [])),
                completed_at,
                visit_record_id,
            ),
        )


def _record_visit_provenance(cursor, patient_id, visit_record_id, state, visit_date, bundle_payload):
    tracked_fields = (
        "psa", "psad", "testosterone", "alp", "ldh", "albumin", "hemoglobin", "creatinine",
        "cystatin_c", "bilirubin", "ast", "alt", "ggt", "glucose", "ecog", "pain",
        "pirads_score", "precise_score", "psma_suv_max", "bone_lesion_count", "ct_summary",
        "mini_cog_score", "fatigue_score", "weight_kg", "bmi_current", "weight_loss_6m_pct",
        "cv_risk_documented", "drug_interaction_reviewed", "exercise_status", "nutrition_status",
        "genomic_classifier", "genomic_classifier_result", "decipher_risk",
    )
    for field_name in tracked_fields:
        value = bundle_payload.get(field_name)
        if not _is_present(value):
            continue
        cursor.execute(
            '''
            INSERT INTO data_provenance (
                patient_id, visit_record_id, field_name, value_json, source_type, source_date,
                entered_manually, stage_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                visit_record_id,
                field_name,
                _json_blob(value),
                "visit_bundle",
                visit_date,
                1,
                state,
            ),
        )


def _record_document_provenance(cursor, patient_id, document_id, document_key, state, source_date, facts, verified_by):
    for fact in facts:
        field_name = fact.get("field_name")
        if not field_name or not _is_present(fact.get("value")):
            continue
        cursor.execute(
            '''
            INSERT INTO data_provenance (
                patient_id, visit_record_id, field_name, value_json, source_type, source_document_id,
                source_date, verified_by, entered_manually, stage_context
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                field_name,
                _json_blob(fact.get("value")),
                "source_document",
                document_key,
                source_date,
                verified_by,
                0,
                state,
            ),
        )


def record_patient_event(
    patient_id,
    *,
    event_type,
    event_date=None,
    state_context="",
    management_track="",
    source_type="system",
    source_record_id=None,
    status="recorded",
    payload=None,
    mcode_focus=None,
):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO patient_events (
                patient_id, event_type, event_date, state_context, management_track,
                source_type, source_record_id, status, payload_json, mcode_focus_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                event_type,
                event_date or datetime.now().strftime("%Y-%m-%d"),
                state_context,
                management_track,
                source_type,
                source_record_id,
                status,
                _json_blob(payload or {}),
                _json_blob(mcode_focus or {}),
            ),
        )
        event_id = c.lastrowid
        conn.commit()
        conn.close()
        return event_id
    except Exception as e:
        logger.error(f"Error recording patient event: {e}")
        return None


def _persist_signal_snapshot(cursor, patient_id, event_id, bundle):
    signals = bundle.get("signals", {})
    next_best_action = bundle.get("next_best_action", {})
    cursor.execute(
        '''
        INSERT INTO clinical_signal_snapshots (
            patient_id, event_id, state, management_track, ready_to_restage,
            signals_json, critical_missing_json, awaiting_review_json, active_safety_json,
            next_best_action_json, mcode_projection_json, evidence_basis_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(patient_id) DO UPDATE SET
            event_id=excluded.event_id,
            state=excluded.state,
            management_track=excluded.management_track,
            ready_to_restage=excluded.ready_to_restage,
            signals_json=excluded.signals_json,
            critical_missing_json=excluded.critical_missing_json,
            awaiting_review_json=excluded.awaiting_review_json,
            active_safety_json=excluded.active_safety_json,
            next_best_action_json=excluded.next_best_action_json,
            mcode_projection_json=excluded.mcode_projection_json,
            evidence_basis_json=excluded.evidence_basis_json,
            updated_at=CURRENT_TIMESTAMP
        ''',
        (
            patient_id,
            event_id,
            signals.get("state"),
            signals.get("management_track"),
            1 if signals.get("ready_to_restage") else 0,
            _json_blob(signals.get("signals", [])),
            _json_blob(signals.get("critical_missing", [])),
            _json_blob(signals.get("awaiting_review", [])),
            _json_blob(signals.get("active_safety", [])),
            _json_blob(next_best_action),
            _json_blob(signals.get("mcode_projection", {})),
            _json_blob(signals.get("evidence_basis", [])),
        ),
    )


def _persist_transition_proposals(cursor, patient_id, event_id, proposals):
    active_keys = {proposal.get("proposal_key") for proposal in proposals if proposal.get("proposal_key")}
    if active_keys:
        cursor.execute(
            f"""
            UPDATE state_transition_proposals
            SET proposal_status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ?
              AND proposal_status = 'open'
              AND proposal_key NOT IN ({",".join(["?"] * len(active_keys))})
            """,
            (patient_id, *active_keys),
        )
    else:
        cursor.execute(
            '''
            UPDATE state_transition_proposals
            SET proposal_status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ? AND proposal_status = 'open'
            ''',
            (patient_id,),
        )
    for proposal in proposals:
        cursor.execute(
            '''
            INSERT INTO state_transition_proposals (
                patient_id, proposal_key, event_id, from_state, from_management_track,
                target_state, target_management_track, proposal_status, priority,
                requires_confirmation, rationale, trigger_signals_json, next_actions_json,
                evidence_basis_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(patient_id, proposal_key) DO UPDATE SET
                event_id=excluded.event_id,
                from_state=excluded.from_state,
                from_management_track=excluded.from_management_track,
                target_state=excluded.target_state,
                target_management_track=excluded.target_management_track,
                proposal_status=excluded.proposal_status,
                priority=excluded.priority,
                requires_confirmation=excluded.requires_confirmation,
                rationale=excluded.rationale,
                trigger_signals_json=excluded.trigger_signals_json,
                next_actions_json=excluded.next_actions_json,
                evidence_basis_json=excluded.evidence_basis_json,
                updated_at=CURRENT_TIMESTAMP
            ''',
            (
                patient_id,
                proposal.get("proposal_key"),
                event_id,
                proposal.get("from_state"),
                proposal.get("from_management_track"),
                proposal.get("target_state"),
                proposal.get("target_management_track"),
                proposal.get("proposal_status", "open"),
                proposal.get("priority"),
                1 if proposal.get("requires_confirmation", True) else 0,
                proposal.get("rationale"),
                _json_blob(proposal.get("trigger_signals", [])),
                _json_blob(proposal.get("next_actions", [])),
                _json_blob(proposal.get("evidence_basis", [])),
            ),
        )


def _persist_recommendation_audit(cursor, audit):
    if not audit:
        return
    cursor.execute(
        '''
        INSERT INTO recommendation_audit (
            patient_id, assessment_id, event_id, recommendation_family, recommended_option,
            selected_option, discordance_reason, outcome_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            audit.get("patient_id"),
            audit.get("assessment_id"),
            audit.get("event_id"),
            audit.get("recommendation_family"),
            audit.get("recommended_option"),
            audit.get("selected_option"),
            audit.get("discordance_reason"),
            _json_blob(audit.get("outcome_snapshot", {})),
        ),
    )


def refresh_longitudinal_intelligence(nss_or_id, event_id=None, force_recompute=False):
    from prostanet.domains.patient_tracking.longitudinal_intelligence import (
        build_longitudinal_intelligence_bundle,
        build_recommendation_audit,
    )

    if force_recompute:
        recompute_patient_care_plan(nss_or_id)
    record = get_patient_full_record(nss_or_id)
    if not record:
        return {}
    bundle = build_longitudinal_intelligence_bundle(record, record.get("latest_assessment"))
    audit = build_recommendation_audit(record["identity"]["id"], record, record.get("latest_assessment"), event_id=event_id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    _persist_signal_snapshot(c, record["identity"]["id"], event_id, bundle)
    _persist_transition_proposals(c, record["identity"]["id"], event_id, bundle.get("transition_proposals", []))
    if event_id is not None or force_recompute:
        _persist_recommendation_audit(c, audit)
    conn.commit()
    conn.close()
    refreshed = get_patient_full_record(nss_or_id)
    latest_snapshot = refreshed.get("latest_signal_snapshot") or bundle.get("signals", {})
    open_proposals = [
        proposal for proposal in (refreshed.get("transition_proposals") or []) if proposal.get("proposal_status") == "open"
    ]
    recent_audit = (refreshed.get("recommendation_audit") or [])[:8]
    return {
        "signals": latest_snapshot,
        "transition_proposals": open_proposals,
        "next_best_action": latest_snapshot.get("next_best_action") or bundle.get("next_best_action", {}),
        "recommendation_audit": recent_audit,
    }


def refresh_followup_agenda(patient_record):
    from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board, infer_management_track

    if not patient_record:
        return {}
    state = (
        (patient_record.get("latest_assessment") or {}).get("state")
        or (patient_record.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )
    management_track = infer_management_track(patient_record, state, patient_record.get("latest_assessment"))
    agenda_board = build_agenda_board(patient_record, state, management_track, patient_record.get("latest_assessment"))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    _upsert_agenda_items(c, patient_record["identity"]["id"], agenda_board.get("items", []))
    conn.commit()
    conn.close()
    return agenda_board


def get_patient_agenda(nss_or_id):
    record = get_patient_full_record(nss_or_id)
    if not record:
        return None
    agenda_board = refresh_followup_agenda(record)
    refreshed = get_patient_full_record(nss_or_id)
    agenda_board["items"] = refreshed.get("agenda_items", [])
    agenda_board["next_due_items"] = [item for item in agenda_board["items"] if item.get("status") == "due"][:4]
    agenda_board["overdue_items"] = [item for item in agenda_board["items"] if item.get("status") == "overdue"][:4]
    return agenda_board


def get_patient_signals(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("signals", {})


def get_patient_next_best_action(nss_or_id):
    bundle = refresh_longitudinal_intelligence(nss_or_id, force_recompute=False)
    if not bundle:
        return None
    return bundle.get("next_best_action", {})


def _confirm_transition_assessment(patient_id, proposal):
    from prostanet.application.module_registry import ModuleRegistry
    from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService
    from prostanet.domains.patient_tracking.event_graph import merge_record_into_assessment_payload

    record = get_patient_full_record(patient_id)
    if not record:
        return None, "Paciente no encontrado"
    registry = ModuleRegistry()
    assessment_service = ClinicalAssessmentService()
    latest_assessment = record.get("latest_assessment") or {}
    base_payload = dict((latest_assessment or {}).get("input_snapshot", {}) or {})
    payload = merge_record_into_assessment_payload(base_payload, record)
    target_state = proposal.get("target_state")
    result = registry.evaluate_module(target_state, payload)
    assessment_id = assessment_service.create_draft(
        module_id=target_state,
        state=result.get("state", target_state),
        input_snapshot=payload,
        result_snapshot=result,
        guideline_versions=registry.get_guidelines_metadata(),
    )
    if assessment_id is None:
        return None, "No se pudo crear la nueva evaluación clínica"
    linked, message = assessment_service.attach_to_patient(assessment_id, patient_id)
    if not linked:
        return None, message
    return assessment_id, "Evaluación clínica creada y vinculada"


def confirm_state_transition_proposal(patient_id, proposal_id, confirmed_by="system"):
    try:
        patient_id = int(patient_id)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            '''
            SELECT * FROM state_transition_proposals
            WHERE id = ? AND patient_id = ? AND proposal_status = 'open'
            ''',
            (proposal_id, patient_id),
        )
        proposal = c.fetchone()
        if not proposal:
            conn.close()
            return False, "Propuesta no encontrada o ya resuelta"
        proposal = dict(proposal)
        proposal["trigger_signals"] = _parse_json_blob(proposal.get("trigger_signals_json"), [])
        proposal["next_actions"] = _parse_json_blob(proposal.get("next_actions_json"), [])
        proposal["evidence_basis"] = _parse_json_blob(proposal.get("evidence_basis_json"), [])
        conn.close()

        assessment_id, message = _confirm_transition_assessment(patient_id, proposal)
        if assessment_id is None:
            return False, message

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            UPDATE state_transition_proposals
            SET proposal_status = 'confirmed',
                resulting_assessment_id = ?,
                confirmed_at = CURRENT_TIMESTAMP,
                confirmed_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (assessment_id, confirmed_by, proposal_id, patient_id),
        )
        conn.commit()
        conn.close()

        event_id = record_patient_event(
            patient_id,
            event_type="state_transition_confirmed",
            state_context=proposal.get("target_state"),
            management_track=proposal.get("target_management_track") or "",
            source_type="transition_proposal",
            source_record_id=proposal_id,
            payload={"proposal_key": proposal.get("proposal_key"), "resulting_assessment_id": assessment_id},
            mcode_focus={"condition": proposal.get("target_state")},
        )
        bundle = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        record = get_patient_full_record(patient_id)
        agenda = refresh_followup_agenda(record)
        return True, {"assessment_id": assessment_id, "agenda": agenda, **bundle}
    except Exception as e:
        logger.error(f"Error confirming transition proposal: {e}")
        return False, str(e)


def complete_followup_agenda_item(patient_id, agenda_id, visit_record_id=None):
    try:
        patient_id = int(patient_id)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            UPDATE followup_agenda_items
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                visit_record_id = COALESCE(?, visit_record_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (visit_record_id, agenda_id, patient_id),
        )
        updated = c.rowcount
        conn.commit()
        conn.close()
        return updated > 0
    except Exception as e:
        logger.error(f"Error completing agenda item: {e}")
        return False


def _coerce_document_value(value):
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return ""
        if text.startswith("[") or text.startswith("{"):
            try:
                return json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                return text
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        try:
            if "." in text:
                return float(text)
            return int(text)
        except ValueError:
            return text
    return value


def _load_source_document(patient_id, document_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM source_documents WHERE id = ? AND patient_id = ?",
        (document_id, patient_id),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["metadata"] = _parse_json_blob(item.pop("metadata_json", None), {})
    return item


def _replace_document_candidates(cursor, patient_id, document_id, candidates):
    cursor.execute("DELETE FROM document_extraction_candidates WHERE document_id = ?", (document_id,))
    for candidate in candidates:
        cursor.execute(
            '''
            INSERT INTO document_extraction_candidates (
                patient_id, document_id, candidate_key, field_name, fact_group, target_result_type,
                value_json, value_display, confidence, status, extraction_method, evidence_excerpt,
                page_ref, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''',
            (
                patient_id,
                document_id,
                candidate.get("candidate_key"),
                candidate.get("field_name"),
                candidate.get("fact_group"),
                candidate.get("target_result_type"),
                _json_blob(candidate.get("value")),
                candidate.get("value_display"),
                candidate.get("confidence", 0),
                candidate.get("status", "draft"),
                candidate.get("extraction_method"),
                candidate.get("evidence_excerpt"),
                candidate.get("page_ref"),
            ),
        )


def _upsert_document_verification_task(cursor, patient_id, document_id, task_payload, verified_by=""):
    verified_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if task_payload.get("task_status") == "verified" else None
    cursor.execute(
        '''
        INSERT INTO document_verification_tasks (
            patient_id, document_id, task_key, task_status, assigned_to, verified_by,
            verified_at, summary_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(document_id) DO UPDATE SET
            task_key=excluded.task_key,
            task_status=excluded.task_status,
            assigned_to=excluded.assigned_to,
            verified_by=excluded.verified_by,
            verified_at=excluded.verified_at,
            summary_json=excluded.summary_json,
            updated_at=CURRENT_TIMESTAMP
        ''',
        (
            patient_id,
            document_id,
            task_payload.get("task_key"),
            task_payload.get("task_status", "open"),
            task_payload.get("assigned_to", ""),
            verified_by or task_payload.get("verified_by", ""),
            verified_at or task_payload.get("verified_at"),
            _json_blob(task_payload.get("summary", {})),
        ),
    )
    cursor.execute("SELECT id FROM document_verification_tasks WHERE document_id = ?", (document_id,))
    task_row = cursor.fetchone()
    return task_row[0] if task_row else None


def _replace_verified_document_facts(cursor, patient_id, document_id, task_id, facts, verified_by):
    cursor.execute("DELETE FROM verified_document_facts WHERE document_id = ?", (document_id,))
    for fact in facts:
        cursor.execute(
            '''
            INSERT INTO verified_document_facts (
                patient_id, document_id, task_id, fact_key, field_name, fact_group, target_result_type,
                value_json, value_display, source_date, status, correction_note, verified_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''',
            (
                patient_id,
                document_id,
                task_id,
                fact.get("fact_key") or f"{fact.get('fact_group', '')}:{fact.get('field_name', '')}",
                fact.get("field_name"),
                fact.get("fact_group"),
                fact.get("target_result_type"),
                _json_blob(fact.get("value")),
                fact.get("value_display"),
                fact.get("source_date"),
                fact.get("status", "verified"),
                fact.get("correction_note", ""),
                verified_by,
            ),
        )


def _serialize_document_bundle(patient_id, document_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM source_documents WHERE id = ? AND patient_id = ?", (document_id, patient_id))
    document_rows = _hydrate_source_document_rows(c.fetchall())
    c.execute("SELECT * FROM document_extraction_candidates WHERE document_id = ? ORDER BY id ASC", (document_id,))
    candidates = _hydrate_document_candidate_rows(c.fetchall())
    c.execute("SELECT * FROM document_verification_tasks WHERE document_id = ?", (document_id,))
    tasks = _hydrate_document_task_rows(c.fetchall())
    c.execute("SELECT * FROM verified_document_facts WHERE document_id = ? ORDER BY id ASC", (document_id,))
    verified_facts = _hydrate_verified_fact_rows(c.fetchall())
    conn.close()
    document = document_rows[0] if document_rows else None
    if not document:
        return None
    preview_excerpt = _document_store().build_preview(document.get("private_index_path", ""))
    from prostanet.domains.patient_tracking.document_ingestion import get_manual_template

    return {
        "document": document,
        "candidates": candidates,
        "verification_task": tasks[0] if tasks else {},
        "verified_facts": verified_facts,
        "preview_excerpt": preview_excerpt,
        "manual_template": get_manual_template(document.get("document_type", "")),
    }


def save_source_document(patient_id, file_storage, data):
    from prostanet.domains.patient_tracking.document_ingestion import classify_document

    try:
        patient_id = int(patient_id)
        if not patient_exists(patient_id):
            return False, "Paciente no encontrado"
        if not file_storage or not getattr(file_storage, "filename", ""):
            return False, "Se requiere un archivo clínico"

        file_name = os.path.basename(file_storage.filename)
        content = file_storage.read()
        if not content:
            return False, "El archivo clínico está vacío"

        stored = _document_store().store_upload(
            patient_id=patient_id,
            file_name=file_name,
            content=content,
            mime_type=getattr(file_storage, "mimetype", "") or "",
        )
        private_payload = _document_store().get_private_payload(stored["private_index_path"])
        classification = classify_document(
            file_name=file_name,
            private_payload=private_payload,
            declared_type=str(data.get("document_type") or "auto"),
        )

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id FROM source_documents WHERE patient_id = ? AND sha256 = ?",
            (patient_id, stored["sha256"]),
        )
        existing = c.fetchone()
        if existing:
            document_id = existing["id"]
            c.execute(
                '''
                UPDATE source_documents
                SET document_type = ?, title = ?, file_name = ?, mime_type = ?, storage_path = ?,
                    private_index_path = ?, source_date = ?, classification_status = ?, preview_excerpt = ?,
                    page_count = ?, metadata_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND patient_id = ?
                ''',
                (
                    classification.get("document_type"),
                    data.get("title") or file_name,
                    file_name,
                    stored["mime_type"],
                    stored["storage_path"],
                    stored["private_index_path"],
                    data.get("source_date"),
                    classification.get("classification_status"),
                    stored.get("preview_excerpt", ""),
                    stored.get("page_count", 0),
                    _json_blob(stored.get("metadata", {})),
                    document_id,
                    patient_id,
                ),
            )
        else:
            c.execute(
                '''
                INSERT INTO source_documents (
                    patient_id, document_key, document_type, title, file_name, mime_type, sha256,
                    storage_path, private_index_path, source_date, classification_status,
                    extraction_status, verification_status, uploaded_by, preview_excerpt, page_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    patient_id,
                    stored["document_key"],
                    classification.get("document_type"),
                    data.get("title") or file_name,
                    file_name,
                    stored["mime_type"],
                    stored["sha256"],
                    stored["storage_path"],
                    stored["private_index_path"],
                    data.get("source_date"),
                    classification.get("classification_status"),
                    "pending",
                    "draft",
                    data.get("uploaded_by", "clinico"),
                    stored.get("preview_excerpt", ""),
                    stored.get("page_count", 0),
                    _json_blob(stored.get("metadata", {})),
                ),
            )
            document_id = c.lastrowid
        conn.commit()
        conn.close()

        record_patient_event(
            patient_id,
            event_type="document_attached",
            event_date=data.get("source_date") or datetime.now().strftime("%Y-%m-%d"),
            state_context=(get_patient_full_record(patient_id) or {}).get("prior_history", {}).get("current_state", ""),
            source_type="source_document",
            source_record_id=document_id,
            payload={"document_type": classification.get("document_type"), "title": data.get("title") or file_name},
            mcode_focus={"document_type": classification.get("document_type")},
        )
        return True, {"document": _serialize_document_bundle(patient_id, document_id)["document"]}
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        logger.error(f"Error saving source document: {e}")
        return False, str(e)


def list_source_documents(nss_or_id):
    record = get_patient_full_record(nss_or_id)
    if not record:
        return None
    return record.get("source_documents", [])


def extract_source_document(patient_id, document_id, document_type=""):
    from prostanet.domains.patient_tracking.document_ingestion import (
        build_verification_task,
        classify_document,
        extract_candidates_for_document,
    )

    try:
        patient_id = int(patient_id)
        document = _load_source_document(patient_id, document_id)
        if not document:
            return False, "Documento no encontrado"

        private_payload = _document_store().get_private_payload(document.get("private_index_path", ""))
        classification = classify_document(
            file_name=document.get("file_name", ""),
            private_payload=private_payload,
            declared_type=document_type or document.get("document_type", ""),
        )
        candidates = extract_candidates_for_document(
            document_type=classification.get("document_type"),
            file_name=document.get("file_name", ""),
            private_payload=private_payload,
        )
        task = build_verification_task(document_key=document.get("document_key", ""), candidates=candidates)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            UPDATE source_documents
            SET document_type = ?, classification_status = ?, extraction_status = ?,
                preview_excerpt = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (
                classification.get("document_type"),
                classification.get("classification_status"),
                "extracted" if candidates else "needs_manual_review",
                private_payload.get("preview_excerpt", "")[:1800],
                document_id,
                patient_id,
            ),
        )
        _replace_document_candidates(c, patient_id, document_id, candidates)
        _upsert_document_verification_task(c, patient_id, document_id, task)
        conn.commit()
        conn.close()
        return True, _serialize_document_bundle(patient_id, document_id)
    except Exception as e:
        logger.error(f"Error extracting source document: {e}")
        return False, str(e)


def get_document_facts(patient_id, document_id):
    try:
        patient_id = int(patient_id)
        bundle = _serialize_document_bundle(patient_id, document_id)
        if not bundle:
            return None
        return bundle
    except Exception as e:
        logger.error(f"Error fetching document facts: {e}")
        return None


def _commit_verified_document(patient_id, document, facts, verified_by):
    from prostanet.domains.patient_tracking.document_ingestion import build_document_payload_from_facts

    result_type, payload = build_document_payload_from_facts(
        document_type=document.get("document_type", ""),
        facts=facts,
    )
    record = get_patient_full_record(patient_id) or {}
    state = (
        (record.get("latest_assessment") or {}).get("state")
        or (record.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )
    management_track = (
        (record.get("latest_signal_snapshot") or {}).get("management_track")
        or (record.get("stage_visits") or [{}])[0].get("management_track", "")
    )
    if result_type in {"pathology", "imaging", "genomic"}:
        return save_structured_result(patient_id, {"result_type": result_type, "payload": payload}), [result_type]
    if result_type == "lab_panel":
        payload.update(
            {
                "state": state,
                "management_track": management_track,
                "visit_type": "document_result",
                "disease_status": "Resultado de laboratorio verificado",
                "clinician_notes": f"Resultado verificado desde documento {document.get('title') or document.get('file_name')}",
            }
        )
        return save_stage_visit_bundle(patient_id, payload), [result_type]
    if result_type == "surgery_summary":
        success = save_surgical_details(patient_id, payload)
        if not success:
            return (False, "No fue posible persistir el resumen quirúrgico"), []
        event_id = record_patient_event(
            patient_id,
            event_type="procedure_performed",
            event_date=payload.get("surgery_date") or datetime.now().strftime("%Y-%m-%d"),
            state_context="post_prostatectomy",
            management_track="post_rp",
            source_type="source_document",
            source_record_id=document.get("id"),
            payload=payload,
            mcode_focus={"procedure": "surgery_summary"},
        )
        intelligence = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        agenda = refresh_followup_agenda(get_patient_full_record(patient_id))
        return (True, {"event_id": event_id, "agenda": agenda, **intelligence}), [result_type]
    if result_type == "radiotherapy_summary":
        success = save_radiation_details(patient_id, payload)
        if not success:
            return (False, "No fue posible persistir el resumen de radioterapia"), []
        event_id = record_patient_event(
            patient_id,
            event_type="procedure_performed",
            event_date=payload.get("rt_date") or datetime.now().strftime("%Y-%m-%d"),
            state_context=state,
            management_track="post_rt",
            source_type="source_document",
            source_record_id=document.get("id"),
            payload=payload,
            mcode_focus={"procedure": "radiotherapy_summary"},
        )
        intelligence = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        agenda = refresh_followup_agenda(get_patient_full_record(patient_id))
        return (True, {"event_id": event_id, "agenda": agenda, **intelligence}), [result_type]
    return (False, "Tipo de documento no soportado para commit clínico"), []


def verify_source_document(patient_id, document_id, data):
    from prostanet.domains.patient_tracking.document_ingestion import build_verified_fact_bundle, serialize_verified_facts

    try:
        patient_id = int(patient_id)
        document = _load_source_document(patient_id, document_id)
        if not document:
            return False, "Documento no encontrado"
        verified_by = data.get("verified_by", "clinico")
        source_date = data.get("source_date") or document.get("source_date") or datetime.now().strftime("%Y-%m-%d")

        facts = []
        for item in data.get("facts", []):
            value = _coerce_document_value(item.get("value"))
            if not _is_present(value):
                continue
            value_display = item.get("value_display")
            if not value_display:
                value_display = _json_blob(value) if isinstance(value, (dict, list)) else str(value)
            facts.append(
                {
                    "fact_key": item.get("fact_key") or f"{item.get('fact_group', '')}:{item.get('field_name', '')}",
                    "field_name": item.get("field_name"),
                    "fact_group": item.get("fact_group"),
                    "target_result_type": item.get("target_result_type"),
                    "value": value,
                    "value_display": value_display,
                    "source_date": item.get("source_date") or source_date,
                    "status": item.get("status", "verified"),
                    "correction_note": item.get("correction_note", ""),
                    "verified_by": verified_by,
                }
            )
        if not facts:
            return False, "Se requiere al menos un fact verificado"

        serialized_facts = serialize_verified_facts(facts)
        commit_result, committed_types = _commit_verified_document(patient_id, document, serialized_facts, verified_by)
        if not commit_result[0]:
            return False, commit_result[1]

        bundle_summary = build_verified_fact_bundle(
            verified_by=verified_by,
            facts=serialized_facts,
            committed_result_types=committed_types,
        )

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        task_payload = {
            "task_key": f"{document.get('document_key')}:verify",
            "task_status": "verified",
            "verified_by": verified_by,
            "summary": {
                "fact_count": len(serialized_facts),
                "committed_result_types": committed_types,
                "what_changed": bundle_summary.get("what_changed", []),
            },
        }
        task_id = _upsert_document_verification_task(c, patient_id, document_id, task_payload, verified_by=verified_by)
        _replace_verified_document_facts(c, patient_id, document_id, task_id, serialized_facts, verified_by)
        _record_document_provenance(
            c,
            patient_id,
            document_id,
            document.get("document_key"),
            (get_patient_full_record(patient_id) or {}).get("prior_history", {}).get("current_state", ""),
            source_date,
            serialized_facts,
            verified_by,
        )
        c.execute(
            '''
            UPDATE source_documents
            SET verification_status = 'verified',
                extraction_status = CASE WHEN extraction_status = 'pending' THEN 'verified' ELSE extraction_status END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND patient_id = ?
            ''',
            (document_id, patient_id),
        )
        conn.commit()
        conn.close()

        response_payload = commit_result[1] if isinstance(commit_result[1], dict) else {}
        response_payload["document_bundle"] = _serialize_document_bundle(patient_id, document_id)
        response_payload["verified_fact_bundle"] = bundle_summary
        return True, response_payload
    except Exception as e:
        logger.error(f"Error verifying source document: {e}")
        return False, str(e)


def save_stage_visit_bundle(patient_id, data):
    """
    Registra una visita de seguimiento por etapa y mantiene compatibilidad con follow_up_visits.
    """
    try:
        patient_id = int(patient_id)
        if not patient_exists(patient_id):
            return False, "Paciente no encontrado"

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        record = get_patient_full_record(patient_id)
        state = (
            data.get("state")
            or (record.get("latest_assessment") or {}).get("state")
            or (record.get("prior_history") or {}).get("current_state")
            or "diagnostic_workup"
        )
        management_track = data.get("management_track") or ""
        if not management_track:
            from prostanet.domains.patient_tracking.followup_agenda import infer_management_track

            management_track = infer_management_track(record, state, record.get("latest_assessment"))
        visit_date = data.get("visit_date", datetime.now().strftime("%Y-%m-%d"))
        bundle = {
            "state": state,
            "management_track": management_track,
            "visit_date": visit_date,
            "visit_type": data.get("visit_type", "stage_followup"),
            "payload": dict(data),
        }

        c.execute(
            '''
            INSERT INTO follow_up_visits (
                patient_id, visit_date, psa_current, testosterone_current,
                alp_current, ldh_current, albumin_current, hemoglobin_current,
                ecog_current, pain_score, toxicity_events, metabolic_panel, skeletal_events,
                current_treatment, dose_adjustment, disease_status, creatinine_current,
                cystatin_c_current, bilirubin_current, ast_current, alt_current, ggt_current,
                glucose_current, opioid_use, fatigue_score, mini_cog_score, weight_kg,
                bmi_current, weight_loss_6m_pct, exercise_status, nutrition_status,
                protein_supplements, seizure_history, dermatitis_history, cv_risk_status,
                ddi_reviewed, hepatic_risk_status, visit_bundle_json, visit_type,
                state_at_visit, management_track, agenda_context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                visit_date,
                _safe_float(data.get("psa"), None),
                _safe_float(data.get("testosterone"), None),
                _safe_float(data.get("alp"), None),
                _safe_float(data.get("ldh"), None),
                _safe_float(data.get("albumin"), None),
                _safe_float(data.get("hemoglobin"), None),
                _safe_int(data.get("ecog"), None),
                _safe_int(data.get("pain"), None),
                _json_blob(data.get("toxicity", {})),
                _json_blob(data.get("metabolic", {})),
                _json_blob(data.get("skeletal", {})),
                data.get("current_treatment") or data.get("treatment"),
                data.get("dose"),
                data.get("disease_status") or data.get("status"),
                _safe_float(data.get("creatinine"), None),
                _safe_float(data.get("cystatin_c"), None),
                _safe_float(data.get("bilirubin"), None),
                _safe_float(data.get("ast"), None),
                _safe_float(data.get("alt"), None),
                _safe_float(data.get("ggt"), None),
                _safe_float(data.get("glucose"), None),
                data.get("opioid_use"),
                _safe_int(data.get("fatigue_score"), None),
                _safe_int(data.get("mini_cog_score"), None),
                _safe_float(data.get("weight_kg"), None),
                _safe_float(data.get("bmi_current"), None),
                _safe_float(data.get("weight_loss_6m_pct"), None),
                data.get("exercise_status"),
                data.get("nutrition_status"),
                _safe_int(data.get("protein_supplements", 0), 0),
                _safe_int(data.get("seizure_history", 0), 0),
                _safe_int(data.get("dermatitis_history", 0), 0),
                "documentado" if _is_truthy(data.get("cv_risk_documented")) else "",
                _safe_int(data.get("drug_interaction_reviewed", 0), 0),
                data.get("hepatic_risk_factors"),
                _json_blob(bundle),
                data.get("visit_type", "stage_followup"),
                state,
                management_track,
                _json_blob({"agenda_ids": data.get("agenda_ids", [])}),
            ),
        )
        followup_id = c.lastrowid

        c.execute(
            '''
            INSERT INTO stage_visit_records (
                patient_id, visit_date, state, management_track, visit_type, visit_bundle_json, derived_followup_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                visit_date,
                state,
                management_track,
                data.get("visit_type", "stage_followup"),
                _json_blob(bundle),
                followup_id,
            ),
        )
        visit_record_id = c.lastrowid

        _record_visit_provenance(c, patient_id, visit_record_id, state, visit_date, data)

        conn.commit()
        conn.close()

        pro_payload = _build_pro_payload_from_visit(data)
        if pro_payload:
            save_pro_assessment(patient_id, pro_payload)

        imaging_payload = _build_imaging_payload_from_visit(data)
        if imaging_payload:
            save_imaging_study(patient_id, imaging_payload)

        surgery_payload = _build_surgery_payload_from_visit(data)
        if surgery_payload and state == "post_prostatectomy":
            save_surgical_details(patient_id, surgery_payload)

        radiation_payload = _build_radiation_payload_from_visit(data)
        if radiation_payload and management_track in {"post_rt", "salvage"}:
            save_radiation_details(patient_id, radiation_payload)

        if data.get("agenda_ids"):
            for agenda_id in data.get("agenda_ids", []):
                complete_followup_agenda_item(patient_id, agenda_id, visit_record_id=visit_record_id)
        event_id = record_patient_event(
            patient_id,
            event_type="followup_visit_recorded",
            event_date=visit_date,
            state_context=state,
            management_track=management_track,
            source_type="stage_visit",
            source_record_id=visit_record_id,
            payload=bundle,
            mcode_focus={"visit_type": data.get("visit_type", "stage_followup"), "state": state},
        )
        intelligence = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        refreshed = get_patient_full_record(patient_id)
        agenda = refresh_followup_agenda(refreshed)

        return True, {
            "followup_id": followup_id,
            "visit_record_id": visit_record_id,
            "agenda": agenda,
            "intelligence": intelligence,
        }
    except Exception as e:
        logger.error(f"Error adding follow-up: {e}")
        return False, str(e)

def get_stats():
    """
    Returns aggregated statistics for the dashboard.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Total Patients
        c.execute("SELECT COUNT(*) as count FROM patients")
        total = c.fetchone()['count']
        
        # Risk Distribution (NCCN)
        # We need to parse JSON or store risk separately. Parsing JSON in SQLite is hard without JSON1 extension.
        # But we can do Python-side aggregation for small datasets.
        # Or alter table to store 'risk_group' column.
        
        # Let's fetch all and aggregate in Python for flexibility and speed (assuming <10k rows)
        c.execute("SELECT clinical_scores, discordance_alert FROM patients")
        rows = c.fetchall()
        
        risk_counts = {'BAJO': 0, 'INTERMEDIO': 0, 'ALTO': 0, 'MUY ALTO': 0, 'OTRO': 0}
        discordance_count = 0
        
        for row in rows:
            if row['discordance_alert']:
                discordance_count += 1
            
            try:
                scores = json.loads(row['clinical_scores'])
                risk = scores.get('nccn', {}).get('risk_group', 'OTRO')
                # Normalizar keys
                if 'BAJO' in risk: risk_counts['BAJO'] += 1
                elif 'INTERMEDIO' in risk: risk_counts['INTERMEDIO'] += 1
                elif 'ALTO' in risk: risk_counts['ALTO'] += 1 # Catch ALTO and MUY ALTO if needed
                if 'MUY ALTO' in risk: risk_counts['MUY ALTO'] += 1 # Overlap correction needed?
                # Actually, simpler logic:
                best_key = 'OTRO'
                for k in risk_counts.keys():
                    if k in risk:
                        best_key = k
                        break
                risk_counts[best_key] += 1
            except:
                pass
                
        conn.close()
        
        return {
            'total_patients': total,
            'risk_distribution': risk_counts,
            'discordance_rate': round((discordance_count / total * 100), 1) if total > 0 else 0,
            'discordance_count': discordance_count
        }
        
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return {}

# ══════════════════════════════════════════════════════════════════════════════
# ══  FUNCIONES CRUD — FASE B & C (Expediente Longitudinal + Investigación)
# ══════════════════════════════════════════════════════════════════════════════

def save_demographics(patient_id, data):
    """Guarda o actualiza datos demográficos del paciente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO patient_demographics (
                patient_id, estado_residencia, seguridad_social, escolaridad,
                ocupacion, estado_civil, etnia, tabaquismo, paquetes_anio,
                diabetes_mellitus, hipertension, sindrome_metabolico,
                actividad_fisica, ipss_score, iief5_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            data.get('estado_residencia'), data.get('seguridad_social'),
            data.get('escolaridad'), data.get('ocupacion'), data.get('estado_civil'),
            data.get('etnia', 'hispano'), data.get('tabaquismo', 'nunca'),
            _safe_float(data.get('paquetes_anio', 0), 0),
            _safe_int(data.get('diabetes_mellitus', 0), 0), _safe_int(data.get('hipertension', 0), 0),
            _safe_int(data.get('sindrome_metabolico', 0), 0),
            data.get('actividad_fisica', 'sedentario'),
            _safe_int(data.get('ipss_score', 0), 0), _safe_int(data.get('iief5_score', 0), 0)
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving demographics: {e}")
        return False


def save_family_history(patient_id, relatives):
    """Guarda historia familiar detallada. relatives: lista de dicts."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Limpiar registros anteriores
        c.execute("DELETE FROM family_history_detail WHERE patient_id = ?", (patient_id,))
        for rel in relatives:
            c.execute('''
                INSERT INTO family_history_detail (
                    patient_id, relative_type, cancer_type, age_at_diagnosis,
                    known_mutation, deceased
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                patient_id, rel.get('relative_type'), rel.get('cancer_type'),
                _safe_int(rel.get('age_at_diagnosis', 0), 0), rel.get('known_mutation', 'Desconocido'),
                _safe_int(rel.get('deceased', 0), 0)
            ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving family history: {e}")
        return False


def save_imaging_study(patient_id, data):
    """Registra un estudio de imagen."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO imaging_studies (
                patient_id, study_date, study_type,
                pirads_score, pirads_location, lesion_size_mm,
                ece_suspicion, svi_suspicion, precise_score,
                psma_result, psma_suv_max,
                bone_scan_result, bone_lesion_count,
                findings_json, radiologist_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('study_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('study_type'),
            data.get('pirads_score'), data.get('pirads_location'),
            data.get('lesion_size_mm'),
            _safe_int(data.get('ece_suspicion', 0), 0), _safe_int(data.get('svi_suspicion', 0), 0),
            data.get('precise_score'),
            data.get('psma_result'), data.get('psma_suv_max'),
            data.get('bone_scan_result'), data.get('bone_lesion_count'),
            json.dumps(data.get('findings', {})),
            data.get('radiologist_notes')
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving imaging study: {e}")
        return False


def save_mri_fact(patient_id, data):
    """Guarda hechos tempranos de resonancia magnética multiparamétrica para seguimiento diagnóstico."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO mri_facts (
                patient_id, assessment_id, fact_date, mpmri_quality, decision_usable,
                pirads_score, lesion_location, lesion_size_mm, prostate_volume_ml, findings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get("assessment_id"),
                data.get("fact_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("mpmri_quality"),
                _safe_int(data.get("decision_usable"), 0),
                data.get("pirads_score"),
                data.get("lesion_location"),
                data.get("lesion_size_mm"),
                data.get("prostate_volume_ml"),
                json.dumps(data.get("findings", {}), ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving MRI fact: {e}")
        return False


def save_diagnostic_plan(patient_id, data):
    """Guarda el plan diagnóstico temprano sin convertirlo en confirmación histológica."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO diagnostic_plans (
                patient_id, assessment_id, plan_date, source_state, plan_type, plan_status,
                management_intent_status, plan_summary, recommended_pathway, next_action,
                risk_calculator_pathway, trigger_conditions_json, evidence_context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get("assessment_id"),
                data.get("plan_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("source_state"),
                data.get("plan_type"),
                data.get("plan_status", "planificado"),
                data.get("management_intent_status", "candidate"),
                data.get("plan_summary"),
                data.get("recommended_pathway"),
                data.get("next_action"),
                data.get("risk_calculator_pathway"),
                json.dumps(data.get("trigger_conditions", []), ensure_ascii=False),
                json.dumps(data.get("evidence_context", []), ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving diagnostic plan: {e}")
        return False


def save_biopsy_trigger(patient_id, data):
    """Guarda un trigger de biopsia como hecho temprano pendiente de confirmación."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO biopsy_trigger_events (
                patient_id, assessment_id, trigger_date, source_state, trigger_reason,
                priority, planned_biopsy_type, planned_biopsy_route, trigger_status,
                management_intent_status, activation_conditions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get("assessment_id"),
                data.get("trigger_date", datetime.now().strftime("%Y-%m-%d")),
                data.get("source_state"),
                data.get("trigger_reason"),
                data.get("priority"),
                data.get("planned_biopsy_type"),
                data.get("planned_biopsy_route"),
                data.get("trigger_status", "pendiente_de_confirmacion"),
                data.get("management_intent_status", "candidate"),
                json.dumps(data.get("activation_conditions", []), ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving biopsy trigger: {e}")
        return False


def save_genomic_profile(patient_id, data):
    """Guarda perfil genómico del paciente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO genomic_profile (
                patient_id, test_date, test_type,
                decipher_score, decipher_risk, prolaris_score, gps_score,
                brca1_status, brca2_status, atm_status, chek2_status, palb2_status, cdk12_status,
                msi_status, tmb_score, ar_v7_status, pten_loss, tp53_status,
                hrr_overall, actionable_findings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('test_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('test_type'),
            data.get('decipher_score'), data.get('decipher_risk'),
            data.get('prolaris_score'), data.get('gps_score'),
            data.get('brca1_status'), data.get('brca2_status'),
            data.get('atm_status'), data.get('chek2_status'),
            data.get('palb2_status'), data.get('cdk12_status'),
            data.get('msi_status'), data.get('tmb_score'),
            data.get('ar_v7_status'), _safe_int(data.get('pten_loss', 0), 0),
            data.get('tp53_status'), data.get('hrr_overall', 'Desconocido'),
            json.dumps(data.get('actionable_findings', []))
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving genomic profile: {e}")
        return False


def save_biopsy(patient_id, data):
    """Registra una biopsia detallada."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO biopsy_details (
                patient_id, biopsy_date, biopsy_type, biopsy_context,
                total_cores, positive_cores, max_core_involvement_pct,
                gleason_primary, gleason_secondary, gleason_tertiary, isup_grade,
                patron_cribiforme, carcinoma_intraductal,
                perineural_invasion, lymphovascular_invasion,
                porcentaje_patron_4, porcentaje_patron_5,
                upgrade_from_previous, previous_isup, adverse_histology_variant_type,
                adverse_histology_variant_detail, pathologist_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('biopsy_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('biopsy_type', 'sistematica'), data.get('biopsy_context', 'diagnostica'),
            _safe_int(data.get('total_cores', 12), 12), _safe_int(data.get('positive_cores', 0), 0),
            _safe_float(data.get('max_core_involvement_pct', 0), 0),
            _safe_int(data.get('gleason_primary'), None), _safe_int(data.get('gleason_secondary'), None),
            data.get('gleason_tertiary'), _safe_int(data.get('isup_grade'), None),
            _safe_int(data.get('patron_cribiforme', 0), 0), _safe_int(data.get('carcinoma_intraductal', 0), 0),
            _safe_int(data.get('perineural_invasion', 0), 0), _safe_int(data.get('lymphovascular_invasion', 0), 0),
            _safe_float(data.get('porcentaje_patron_4', 0), 0), _safe_float(data.get('porcentaje_patron_5', 0), 0),
            _safe_int(data.get('upgrade_from_previous', 0), 0), data.get('previous_isup'),
            data.get('adverse_histology_variant_type'), data.get('adverse_histology_variant_detail'),
            data.get('pathologist_notes')
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving biopsy: {e}")
        return False


def enroll_in_as(patient_id, data):
    """Inscribe paciente en programa de Vigilancia Activa."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO active_surveillance (
                patient_id, enrollment_date, enrollment_protocol,
                enrollment_criteria_met, current_status
            ) VALUES (?, ?, ?, ?, 'activo')
        ''', (
            patient_id, data.get('enrollment_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('protocol', 'NCCN_VL'),
            json.dumps(data.get('criteria_met', {}))
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error enrolling in AS: {e}")
        return False


def exit_as(patient_id, data):
    """Registra salida de Vigilancia Activa."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE active_surveillance SET
                current_status = ?, exit_date = ?, exit_reason = ?, exit_treatment = ?
            WHERE patient_id = ? AND current_status = 'activo'
        ''', (
            data.get('status', 'salida_upgrade'),
            data.get('exit_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('exit_reason'),
            data.get('exit_treatment'),
            patient_id
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error exiting AS: {e}")
        return False


def save_surgical_details(patient_id, data):
    """Registra detalles de la cirugía (prostatectomía radical)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO surgical_details (
                patient_id, surgery_date, surgery_type, nerve_sparing,
                plnd_performed, plnd_type, nodes_removed, nodes_positive,
                pathological_gleason_primary, pathological_gleason_secondary, pathological_isup,
                pathological_stage, surgical_margin_status, margin_location,
                ece_pathological, svi_pathological, lni_pathological,
                specimen_weight_grams, tumor_volume_pct, capra_s_score, surgical_approach,
                continence_status, potency_status, pde5i_use, pads_per_day, recovery_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get('surgery_date'),
                data.get('surgery_type'),
                data.get('nerve_sparing'),
                _safe_int(data.get('plnd_performed', 0), 0),
                data.get('plnd_type'),
                _safe_int(data.get('nodes_removed', 0), 0),
                _safe_int(data.get('nodes_positive', 0), 0),
                data.get('pathological_gleason_primary'),
                data.get('pathological_gleason_secondary'),
                data.get('pathological_isup'),
                data.get('pathological_stage'),
                _safe_int(data.get('surgical_margin_status', 0), 0),
                data.get('margin_location'),
                _safe_int(data.get('ece_pathological', 0), 0),
                _safe_int(data.get('svi_pathological', 0), 0),
                _safe_int(data.get('lni_pathological', 0), 0),
                data.get('specimen_weight_grams'),
                data.get('tumor_volume_pct'),
                data.get('capra_s_score'),
                data.get('surgical_approach'),
                data.get('continence_status'),
                data.get('potency_status'),
                _safe_int(data.get('pde5i_use', 0), 0),
                _safe_int(data.get('pads_per_day', 0), 0),
                data.get('recovery_notes'),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving surgical details: {e}")
        return False


def save_radiation_details(patient_id, data):
    """Registra detalles de radioterapia."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            '''
            INSERT INTO radiation_details (
                patient_id, rt_date, rt_context, rt_technique, target,
                total_dose_gy, fractions, dose_per_fraction_gy,
                concurrent_adt, adt_duration_months, adt_agent,
                gu_toxicity_grade, gi_toxicity_grade, notes, session_duration_minutes,
                total_duration_days, hematuria, dysuria, anemia_related, late_toxicity_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                patient_id,
                data.get('rt_date'),
                data.get('rt_context'),
                data.get('rt_technique'),
                data.get('target'),
                data.get('total_dose_gy'),
                data.get('fractions'),
                data.get('dose_per_fraction_gy'),
                _safe_int(data.get('concurrent_adt', 0), 0),
                data.get('adt_duration_months'),
                data.get('adt_agent'),
                _safe_int(data.get('gu_toxicity_grade', 0), 0),
                _safe_int(data.get('gi_toxicity_grade', 0), 0),
                data.get('notes'),
                _safe_int(data.get('session_duration_minutes'), None),
                _safe_int(data.get('total_duration_days'), None),
                data.get('hematuria'),
                data.get('dysuria'),
                data.get('anemia_related'),
                _json_blob(data.get('late_toxicity_json', {})),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving radiation details: {e}")
        return False


def save_pro_assessment(patient_id, data):
    """Guarda evaluación de PROs (Patient-Reported Outcomes)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO patient_pros (
                patient_id, assessment_date,
                ipss_total, ipss_qol, pad_usage,
                iief5_score, erection_sufficient, pde5i_use,
                bpi_worst_pain, bpi_average_pain, bpi_interference,
                eq5d_index, eq5d_vas, fact_p_total, max_acs_score,
                clinician_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('date', datetime.now().strftime('%Y-%m-%d')),
            data.get('ipss_total'), data.get('ipss_qol'), _safe_int(data.get('pad_usage', 0), 0),
            data.get('iief5_score'), _safe_int(data.get('erection_sufficient', 0), 0),
            _safe_int(data.get('pde5i_use', 0), 0),
            data.get('bpi_worst_pain'), data.get('bpi_average_pain'),
            data.get('bpi_interference'),
            data.get('eq5d_index'), data.get('eq5d_vas'),
            data.get('fact_p_total'), data.get('max_acs_score'),
            data.get('clinician_notes')
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving PRO assessment: {e}")
        return False


def save_bcr(patient_id, data):
    """Registra recurrencia bioquímica."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO biochemical_recurrence (
                patient_id, primary_treatment, primary_treatment_date,
                nadir_psa, nadir_date,
                bcr_detected, bcr_date, bcr_psa, bcr_definition,
                psadt_at_bcr, time_to_bcr_months,
                salvage_treatment, salvage_date, salvage_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('primary_treatment'), data.get('primary_treatment_date'),
            data.get('nadir_psa'), data.get('nadir_date'),
            _safe_int(data.get('bcr_detected', 0), 0), data.get('bcr_date'),
            data.get('bcr_psa'), data.get('bcr_definition'),
            data.get('psadt_at_bcr'), data.get('time_to_bcr_months'),
            data.get('salvage_treatment'), data.get('salvage_date'),
            data.get('salvage_response')
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving BCR: {e}")
        return False


def save_structured_result(patient_id, data):
    result_type = str(data.get("result_type") or "").strip().lower()
    payload = dict(data.get("payload") or {})
    if not result_type:
        return False, "Se requiere result_type"
    if result_type == "pathology":
        success = save_biopsy(patient_id, payload)
        event_type = "pathology_verified"
    elif result_type == "genomic":
        success = save_genomic_profile(patient_id, payload)
        event_type = "genomic_result_verified"
    elif result_type == "imaging":
        success = save_imaging_study(patient_id, payload)
        event_type = "study_resulted"
    elif result_type == "goals_of_care":
        success = True
        event_type = "goals_of_care_updated"
    elif result_type == "surgery_summary":
        success = save_surgical_details(patient_id, payload)
        event_type = "procedure_performed"
    elif result_type == "radiotherapy_summary":
        success = save_radiation_details(patient_id, payload)
        event_type = "procedure_performed"
    else:
        return False, "Tipo de resultado no soportado"
    if not success:
        return False, "No fue posible persistir el resultado estructurado"
    event_id = record_patient_event(
        patient_id,
        event_type=event_type,
        event_date=payload.get("study_date") or payload.get("biopsy_date") or payload.get("test_date") or payload.get("surgery_date") or payload.get("rt_date") or datetime.now().strftime("%Y-%m-%d"),
        state_context=(get_patient_full_record(patient_id) or {}).get("prior_history", {}).get("current_state", ""),
        source_type="structured_result",
        payload={"result_type": result_type, **payload},
        mcode_focus={"result_type": result_type},
    )
    bundle = refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
    refreshed = get_patient_full_record(patient_id)
    agenda = refresh_followup_agenda(refreshed)
    return True, {"event_id": event_id, "agenda": agenda, **bundle}


def create_smart_alert(patient_id, alert_type, severity, title, description, data_dict=None):
    """Crea una alerta inteligente para un paciente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO smart_alerts (
                patient_id, alert_type, severity, title, description, data_json
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, alert_type, severity, title, description,
            json.dumps(data_dict) if data_dict else None
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error creating alert: {e}")
        return False


def get_patient_alerts(patient_id, unacknowledged_only=True):
    """Obtiene alertas de un paciente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = "SELECT * FROM smart_alerts WHERE patient_id = ?"
        if unacknowledged_only:
            query += " AND acknowledged = 0"
        query += " ORDER BY alert_date DESC"
        c.execute(query, (patient_id,))
        alerts = [dict(row) for row in c.fetchall()]
        conn.close()
        return alerts
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        return []


def acknowledge_alert(alert_id, user='system'):
    """Marca una alerta como vista/reconocida."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE smart_alerts SET
                acknowledged = 1, acknowledged_by = ?, acknowledged_date = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (user, alert_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        return False


def get_patient_full_record(nss_or_id):
    """
    Recupera el expediente COMPLETO del paciente (Fase B).
    Incluye todas las tablas nuevas para el perfil longitudinal.
    Acepta NSS (texto) o ID numérico como identificador.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Identity — buscar primero por NSS, luego por ID numérico
        identity = _resolve_identity_row(c, nss_or_id)
        if not identity:
            conn.close()
            return None
        patient_id = identity['id']

        # 2. Baseline
        c.execute("SELECT * FROM clinical_baseline WHERE patient_id = ?", (patient_id,))
        baseline = c.fetchone()

        # 3. Demographics
        c.execute("SELECT * FROM patient_demographics WHERE patient_id = ?", (patient_id,))
        demographics = c.fetchone()

        # 4. Family History
        c.execute("SELECT * FROM family_history_detail WHERE patient_id = ?", (patient_id,))
        family_history = [dict(row) for row in c.fetchall()]

        # 5. Imaging Studies
        c.execute("SELECT * FROM imaging_studies WHERE patient_id = ? ORDER BY study_date DESC", (patient_id,))
        imaging = [dict(row) for row in c.fetchall()]
        for item in imaging:
            item["findings"] = _parse_json_blob(item.pop("findings_json", None), {})

        c.execute("SELECT * FROM mri_facts WHERE patient_id = ? ORDER BY fact_date DESC, id DESC", (patient_id,))
        mri_facts = [dict(row) for row in c.fetchall()]
        for item in mri_facts:
            item["findings"] = _parse_json_blob(item.pop("findings_json", None), {})

        # 6. Genomic Profile
        c.execute("SELECT * FROM genomic_profile WHERE patient_id = ? ORDER BY test_date DESC LIMIT 1", (patient_id,))
        genomics = c.fetchone()

        # 7. Biopsies
        c.execute("SELECT * FROM biopsy_details WHERE patient_id = ? ORDER BY biopsy_date ASC", (patient_id,))
        biopsies = [dict(row) for row in c.fetchall()]

        c.execute("SELECT * FROM diagnostic_plans WHERE patient_id = ? ORDER BY plan_date DESC, id DESC", (patient_id,))
        diagnostic_plans = [dict(row) for row in c.fetchall()]
        for item in diagnostic_plans:
            item["trigger_conditions"] = _parse_json_blob(item.pop("trigger_conditions_json", None), [])
            item["evidence_context"] = _parse_json_blob(item.pop("evidence_context_json", None), [])

        c.execute("SELECT * FROM biopsy_trigger_events WHERE patient_id = ? ORDER BY trigger_date DESC, id DESC", (patient_id,))
        biopsy_triggers = [dict(row) for row in c.fetchall()]
        for item in biopsy_triggers:
            item["activation_conditions"] = _parse_json_blob(item.pop("activation_conditions_json", None), [])

        # 8. Active Surveillance
        c.execute("SELECT * FROM active_surveillance WHERE patient_id = ? ORDER BY enrollment_date DESC LIMIT 1", (patient_id,))
        as_record = c.fetchone()

        # 9. BCR
        c.execute("SELECT * FROM biochemical_recurrence WHERE patient_id = ?", (patient_id,))
        bcr = c.fetchone()

        # 10. Surgical Details
        c.execute("SELECT * FROM surgical_details WHERE patient_id = ?", (patient_id,))
        surgery = c.fetchone()

        # 11. Radiation Details
        c.execute("SELECT * FROM radiation_details WHERE patient_id = ? ORDER BY rt_date ASC", (patient_id,))
        radiation = [dict(row) for row in c.fetchall()]

        # 12. PROs
        c.execute("SELECT * FROM patient_pros WHERE patient_id = ? ORDER BY assessment_date ASC", (patient_id,))
        pros = [dict(row) for row in c.fetchall()]

        # 13. Follow-ups
        c.execute("SELECT * FROM follow_up_visits WHERE patient_id = ? ORDER BY visit_date ASC", (patient_id,))
        follow_ups = _hydrate_followup_rows(c.fetchall())

        # 14. Treatment History
        c.execute("SELECT * FROM treatment_history WHERE patient_id = ? ORDER BY start_date ASC", (patient_id,))
        treatments = [dict(row) for row in c.fetchall()]

        # 15. Prior Clinical History
        c.execute("SELECT * FROM prior_clinical_history WHERE patient_id = ?", (patient_id,))
        prior_history = c.fetchone()

        # 16. Alerts
        c.execute("SELECT * FROM smart_alerts WHERE patient_id = ? AND acknowledged = 0 ORDER BY alert_date DESC", (patient_id,))
        alerts = [dict(row) for row in c.fetchall()]

        # 17. Pivotal Study Matching
        c.execute("SELECT * FROM pivotal_study_matching WHERE patient_id = ? ORDER BY evaluation_date DESC", (patient_id,))
        pivotal_matches = [dict(row) for row in c.fetchall()]

        latest_assessment = _fetch_latest_clinical_assessment(c, patient_id)
        c.execute(
            "SELECT * FROM patient_state_timeline WHERE patient_id = ? ORDER BY created_at ASC, id ASC",
            (patient_id,),
        )
        state_timeline = _hydrate_timeline_rows(c.fetchall())

        c.execute(
            "SELECT * FROM followup_agenda_items WHERE patient_id = ? ORDER BY COALESCE(due_at, ''), id ASC",
            (patient_id,),
        )
        agenda_items = _hydrate_agenda_rows(c.fetchall())

        c.execute(
            "SELECT * FROM stage_visit_records WHERE patient_id = ? ORDER BY visit_date DESC, id DESC",
            (patient_id,),
        )
        stage_visits = _hydrate_stage_visit_rows(c.fetchall())

        c.execute(
            "SELECT * FROM data_provenance WHERE patient_id = ? ORDER BY source_date DESC, id DESC",
            (patient_id,),
        )
        data_provenance = _hydrate_provenance_rows(c.fetchall())

        c.execute(
            "SELECT * FROM patient_events WHERE patient_id = ? ORDER BY event_date DESC, id DESC",
            (patient_id,),
        )
        patient_events = _hydrate_event_rows(c.fetchall())

        c.execute(
            "SELECT * FROM clinical_signal_snapshots WHERE patient_id = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (patient_id,),
        )
        latest_signal_snapshot = _hydrate_signal_rows(c.fetchall())

        c.execute(
            "SELECT * FROM state_transition_proposals WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        transition_proposals = _hydrate_transition_rows(c.fetchall())

        c.execute(
            "SELECT * FROM recommendation_audit WHERE patient_id = ? ORDER BY recorded_at DESC, id DESC",
            (patient_id,),
        )
        recommendation_audit = _hydrate_recommendation_audit_rows(c.fetchall())

        c.execute(
            "SELECT * FROM source_documents WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        source_documents = _hydrate_source_document_rows(c.fetchall())

        c.execute(
            '''
            SELECT * FROM document_extraction_candidates
            WHERE patient_id = ?
            ORDER BY document_id DESC, id ASC
            ''',
            (patient_id,),
        )
        document_candidates = _hydrate_document_candidate_rows(c.fetchall())

        c.execute(
            "SELECT * FROM document_verification_tasks WHERE patient_id = ? ORDER BY updated_at DESC, id DESC",
            (patient_id,),
        )
        document_verification_tasks = _hydrate_document_task_rows(c.fetchall())

        c.execute(
            "SELECT * FROM verified_document_facts WHERE patient_id = ? ORDER BY created_at DESC, id DESC",
            (patient_id,),
        )
        verified_document_facts = _hydrate_verified_fact_rows(c.fetchall())

        conn.close()

        return {
            'identity': dict(identity),
            'baseline': dict(baseline) if baseline else {},
            'demographics': dict(demographics) if demographics else {},
            'family_history': family_history,
            'imaging': imaging,
            'mri_facts': mri_facts,
            'genomics': dict(genomics) if genomics else {},
            'biopsies': biopsies,
            'diagnostic_plans': diagnostic_plans,
            'biopsy_triggers': biopsy_triggers,
            'active_surveillance': dict(as_record) if as_record else {},
            'bcr': dict(bcr) if bcr else {},
            'surgery': dict(surgery) if surgery else {},
            'radiation': radiation,
            'pros': pros,
            'follow_ups': follow_ups,
            'treatments': treatments,
            'prior_history': _decorate_prior_history(prior_history),
            'alerts': alerts,
            'pivotal_matches': pivotal_matches,
            'latest_assessment': latest_assessment,
            'state_timeline': state_timeline,
            'care_overlays': _decorate_prior_history(prior_history).get("care_overlays", []),
            'agenda_items': agenda_items,
            'stage_visits': stage_visits,
            'data_provenance': data_provenance,
            'patient_events': patient_events,
            'latest_signal_snapshot': latest_signal_snapshot[0] if latest_signal_snapshot else {},
            'transition_proposals': transition_proposals,
            'recommendation_audit': recommendation_audit,
            'source_documents': source_documents,
            'document_candidates': document_candidates,
            'document_verification_tasks': document_verification_tasks,
            'verified_document_facts': verified_document_facts,
        }
    except Exception as e:
        logger.error(f"Error fetching full patient record: {e}")
        return None


def get_patient_state_timeline(nss_or_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        identity = _resolve_identity_row(c, nss_or_id)
        if not identity:
            conn.close()
            return None
        c.execute(
            "SELECT * FROM patient_state_timeline WHERE patient_id = ? ORDER BY created_at ASC, id ASC",
            (identity["id"],),
        )
        rows = _hydrate_timeline_rows(c.fetchall())
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error fetching patient state timeline: {e}")
        return None


def recompute_patient_care_plan(nss_or_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        identity = _resolve_identity_row(c, nss_or_id)
        if not identity:
            conn.close()
            return False, "Paciente no encontrado"

        patient_id = identity["id"]
        assessment = _fetch_latest_clinical_assessment(c, patient_id)
        if not assessment:
            conn.close()
            return False, "No existe una evaluación clínica modular para este paciente"

        from prostanet.application.module_registry import ModuleRegistry

        registry = ModuleRegistry()
        from prostanet.domains.patient_tracking.event_graph import (
            build_processing_summary,
            derive_management_intent_status,
            derive_timeline_event_kind,
            merge_record_into_assessment_payload,
        )

        record = get_patient_full_record(patient_id)
        enriched_payload = merge_record_into_assessment_payload(assessment.get("input_snapshot", {}), record)
        updated_result = registry.evaluate_module(assessment["module_id"], enriched_payload)
        updated_guidelines = registry.get_guidelines_metadata()
        c.execute(
            '''
            UPDATE clinical_assessments
            SET state = ?, input_snapshot = ?, result_snapshot = ?, guideline_versions = ?, status = ?
            WHERE id = ?
            ''',
            (
                updated_result.get("state", assessment.get("state")),
                _json_blob(enriched_payload),
                _json_blob(updated_result),
                _json_blob(updated_guidelines),
                assessment.get("status", "linked"),
                assessment["id"],
            ),
        )
        assessment["state"] = updated_result.get("state", assessment.get("state"))
        assessment["input_snapshot"] = enriched_payload
        assessment["result_snapshot"] = updated_result
        assessment["guideline_versions"] = updated_guidelines
        snapshot = _assessment_longitudinal_snapshot(assessment)
        processing = build_processing_summary(assessment.get("state"), enriched_payload, record)
        management_intent_status = derive_management_intent_status(assessment.get("state"), updated_result, record)
        event_kind = derive_timeline_event_kind(assessment.get("state"), updated_result, record)
        _ensure_prior_history_row(c, patient_id)
        c.execute(
            '''
            UPDATE prior_clinical_history
            SET latest_assessment_id = ?,
                assessment_source = ?,
                assessment_module = ?,
                assessment_state = ?,
                assessment_summary = ?,
                recommendation_family = ?,
                management_intent_status = ?,
                current_state = ?,
                transition_reason = ?,
                objective_progression_json = ?,
                monitoring_plan_json = ?,
                care_overlays_json = ?,
                latest_guideline_snapshot_json = ?
            WHERE patient_id = ?
            ''',
            (
                assessment["id"],
                "clinical_wizard",
                assessment.get("module_id"),
                assessment.get("state"),
                snapshot["summary"],
                snapshot.get("recommendation_family", ""),
                management_intent_status,
                snapshot["current_state"],
                snapshot["transition_reason"],
                _json_blob(snapshot["objective_progression"]),
                _json_blob(snapshot["monitoring_plan"]),
                _json_blob(snapshot["care_overlays"]),
                _json_blob({
                    **snapshot["guideline_snapshot"],
                    "decision_quality": snapshot.get("decision_quality", {}),
                    "validated_algorithms": snapshot.get("validated_algorithms", []),
                    "processing_summary": processing,
                }),
                patient_id,
            ),
        )
        _record_patient_state_transition(
            c,
            patient_id,
            assessment["id"],
            assessment.get("state"),
            event_kind,
            management_intent_status,
            f"Recomputación longitudinal: {snapshot['transition_reason']}",
            snapshot["objective_progression"],
            snapshot["monitoring_plan"],
            snapshot["care_overlays"],
            {
                **snapshot["guideline_snapshot"],
                "decision_quality": snapshot.get("decision_quality", {}),
                "validated_algorithms": snapshot.get("validated_algorithms", []),
                "processing_summary": processing,
            },
        )
        conn.commit()
        conn.close()
        return True, assessment
    except Exception as e:
        logger.error(f"Error recomputing patient care plan: {e}")
        return False, str(e)


def check_and_generate_alerts(patient_id):
    """
    Motor de alertas inteligentes.
    Analiza el estado actual del paciente y genera alertas si detecta:
    - PSA en ascenso
    - PSADT < 10 meses
    - Upgrade en biopsia
    - Cambio de ECOG
    - BCR detectado
    - Visita de seguimiento vencida
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Obtener últimas 2 visitas de seguimiento
        c.execute("""
            SELECT * FROM follow_up_visits
            WHERE patient_id = ? ORDER BY visit_date DESC LIMIT 3
        """, (patient_id,))
        visits = [dict(row) for row in c.fetchall()]

        alerts_generated = []

        if len(visits) >= 2:
            current = visits[0]
            previous = visits[1]

            # 1. PSA Rising (3 mediciones consecutivas ascendentes)
            if (current.get('psa_current') and previous.get('psa_current') and
                current['psa_current'] > previous['psa_current']):
                if len(visits) >= 3 and visits[1].get('psa_current', 0) > visits[2].get('psa_current', 0):
                    create_smart_alert(
                        patient_id, 'psa_rising', 'warning',
                        'APE en ascenso sostenido',
                        f"3 mediciones consecutivas en ascenso: {visits[2].get('psa_current', '?')} → {previous['psa_current']} → {current['psa_current']} ng/mL",
                        {'values': [v.get('psa_current') for v in reversed(visits)]}
                    )
                    alerts_generated.append('psa_rising')

            # 2. ECOG Decline
            if (current.get('ecog_current') is not None and previous.get('ecog_current') is not None and
                current['ecog_current'] > previous['ecog_current']):
                create_smart_alert(
                    patient_id, 'ecog_decline', 'warning',
                    'Deterioro del estado funcional',
                    f"ECOG empeoró de {previous['ecog_current']} a {current['ecog_current']}",
                    {'from': previous['ecog_current'], 'to': current['ecog_current']}
                )
                alerts_generated.append('ecog_decline')

        # 3. BCR Detection (post-RP: PSA > 0.2)
        c.execute("SELECT * FROM surgical_details WHERE patient_id = ?", (patient_id,))
        surgery = c.fetchone()
        if surgery and visits:
            psa_current = visits[0].get('psa_current', 0) or 0
            if psa_current >= 0.2:
                # Verificar que no exista ya una alerta reciente
                c.execute("""
                    SELECT COUNT(*) as cnt FROM smart_alerts
                    WHERE patient_id = ? AND alert_type = 'bcr_detected' AND acknowledged = 0
                """, (patient_id,))
                if c.fetchone()['cnt'] == 0:
                    create_smart_alert(
                        patient_id, 'bcr_detected', 'critical',
                        'Posible Recurrencia Bioquímica (BCR)',
                        f"PSA post-prostatectomía = {psa_current} ng/mL (≥0.2 ng/mL = BCR por criterio AUA)",
                        {'psa': psa_current, 'threshold': 0.2}
                    )
                    alerts_generated.append('bcr_detected')

        # 4. Biopsy Upgrade (en VA)
        c.execute("""
            SELECT * FROM biopsy_details WHERE patient_id = ? ORDER BY biopsy_date DESC LIMIT 2
        """, (patient_id,))
        biopsies = [dict(row) for row in c.fetchall()]
        if len(biopsies) >= 2:
            current_isup = biopsies[0].get('isup_grade', 1) or 1
            prev_isup = biopsies[1].get('isup_grade', 1) or 1
            if current_isup > prev_isup:
                create_smart_alert(
                    patient_id, 'upgrade_biopsy', 'critical',
                    'Upgrade en biopsia de seguimiento',
                    f"ISUP cambió de GG{prev_isup} a GG{current_isup}. Considerar salida de Vigilancia Activa.",
                    {'from_isup': prev_isup, 'to_isup': current_isup}
                )
                alerts_generated.append('upgrade_biopsy')

        conn.close()
        return alerts_generated

    except Exception as e:
        logger.error(f"Error in alert generation: {e}")
        return []


def export_patient_data(nss, format='dict'):
    """
    Exporta datos completos del paciente para análisis.
    format: 'dict' para Python, 'json' para JSON string, 'csv_ready' para lista plana
    """
    record = get_patient_full_record(nss)
    if not record:
        return None

    if format == 'json':
        return json.dumps(record, indent=2, default=str, ensure_ascii=False)
    elif format == 'csv_ready':
        # Flatten para CSV
        flat = {}
        flat.update({f"id_{k}": v for k, v in record.get('identity', {}).items()})
        flat.update({f"demo_{k}": v for k, v in record.get('demographics', {}).items()})
        flat.update({f"base_{k}": v for k, v in record.get('baseline', {}).items()})
        flat.update({f"gen_{k}": v for k, v in record.get('genomics', {}).items()})
        flat.update({f"surg_{k}": v for k, v in record.get('surgery', {}).items()})
        flat.update({f"as_{k}": v for k, v in record.get('active_surveillance', {}).items()})
        flat.update({f"bcr_{k}": v for k, v in record.get('bcr', {}).items()})
        flat['n_followups'] = len(record.get('follow_ups', []))
        flat['n_biopsies'] = len(record.get('biopsies', []))
        flat['n_imaging'] = len(record.get('imaging', []))
        flat['n_mri_facts'] = len(record.get('mri_facts', []))
        flat['n_diagnostic_plans'] = len(record.get('diagnostic_plans', []))
        flat['n_biopsy_triggers'] = len(record.get('biopsy_triggers', []))
        flat['n_treatments'] = len(record.get('treatments', []))
        flat['n_alerts'] = len(record.get('alerts', []))
        return flat
    else:
        return record


def save_pivotal_matching(patient_id, match_data):
    """Guarda resultado de matching con estudio pivotal."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO pivotal_study_matching (
                patient_id, study_name, eligible, eligibility_details,
                study_arm, expected_outcome, applicability_to_patient
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            match_data.get('study_name', match_data.get('name', '')),
            int(match_data.get('eligible', False)),
            json.dumps(match_data.get('criteria_details', match_data.get('eligibility_details', {}))),
            match_data.get('study_arm', 'experimental'),
            match_data.get('expected_outcome', match_data.get('key_result', '')),
            match_data.get('applicability', match_data.get('applicability_to_patient', ''))
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error saving pivotal matching: {e}")
        return False


if __name__ == "__main__":
    init_tracking_db()
