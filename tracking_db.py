import sqlite3
import json
import os
from datetime import datetime
import logging

DEFAULT_DB_PATH = "prostanet_tracking.db"
DB_PATH = os.environ.get("PROSTANET_DB_PATH", DEFAULT_DB_PATH)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def configure_db_path(path=None):
    """Permite inyectar una base SQLite distinta, útil para tests."""
    global DB_PATH
    DB_PATH = path or os.environ.get("PROSTANET_DB_PATH", DEFAULT_DB_PATH)
    return DB_PATH


def get_db_path():
    return DB_PATH


def _is_truthy(value):
    return str(value).lower() in {"1", "true", "yes", "si", "on"}


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
    return {
        "summary": nccn.get("resumen_del_caso") or structured.get("resumen_del_caso") or report_sections.get("summary", ""),
        "current_state": assessment.get("state"),
        "transition_reason": nccn.get("trayectoria_recomendada") or structured.get("trayectoria_recomendada") or report_sections.get("summary", ""),
        "objective_progression": result.get("objective_progression", {}),
        "monitoring_plan": result.get("monitoring_plan", {}),
        "care_overlays": result.get("care_overlays", []),
        "guideline_snapshot": assessment.get("guideline_versions", {}),
    }


def _record_patient_state_transition(
    cursor,
    patient_id,
    assessment_id,
    state,
    transition_reason,
    objective_progression,
    monitoring_plan,
    care_overlays,
    latest_guideline_snapshot,
):
    cursor.execute(
        '''
        INSERT INTO patient_state_timeline (
            patient_id, assessment_id, state, transition_reason,
            objective_progression_json, monitoring_plan_json, care_overlays_json,
            latest_guideline_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            patient_id,
            assessment_id,
            state,
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
    return history

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
            pathologist_notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
        )
    ''')

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
            snapshot["transition_reason"],
            snapshot["objective_progression"],
            snapshot["monitoring_plan"],
            snapshot["care_overlays"],
            snapshot["guideline_snapshot"],
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
    if _has_any_value(
        data,
        [
            "mpmri_date",
            "pirads_score",
            "index_lesion_location",
            "index_lesion_size_mm",
            "mpmri_quality",
        ],
    ):
        payloads.append(
            {
                "study_date": data.get("mpmri_date") or datetime.now().strftime("%Y-%m-%d"),
                "study_type": "mpMRI",
                "pirads_score": _safe_int(data.get("pirads_score"), None),
                "pirads_location": data.get("index_lesion_location"),
                "lesion_size_mm": _safe_float(data.get("index_lesion_size_mm"), 0),
                "findings": {
                    "mpmri_quality": data.get("mpmri_quality"),
                    "planned_biopsy_type": data.get("planned_biopsy_type"),
                    "planned_biopsy_route": data.get("planned_biopsy_route"),
                    "risk_calculator_pathway": data.get("risk_calculator_pathway"),
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
                },
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
        test_type = str(data.get("genomic_classifier"))
    elif str(data.get("decipher_risk", "No realizado")) != "No realizado":
        test_type = "Decipher"

    actionable_findings = []
    if str(data.get("hrr_status", "")).lower() in {"positivo", "positive"}:
        actionable_findings.append(f"HRR {data.get('hrr_gene') or 'documentado'}")
    if str(data.get("brca2_status", "")).lower() in {"positivo", "positive"}:
        actionable_findings.append("BRCA2")
    if _is_truthy(data.get("tmb_high")):
        actionable_findings.append("TMB-high")

    return {
        "test_date": data.get("molecular_report_date") or data.get("molecular_assay_date") or datetime.now().strftime("%Y-%m-%d"),
        "test_type": test_type,
        "decipher_risk": None if str(data.get("decipher_risk", "No realizado")) == "No realizado" else data.get("decipher_risk"),
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
    if not _has_any_value(
        data,
        [
            "planned_biopsy_type",
            "prior_biopsy_type",
            "num_cores_positive",
            "total_cores",
            "isup_grade",
            "percent_pattern_4",
        ],
    ):
        return None
    return {
        "biopsy_date": data.get("prior_biopsy_date") or data.get("mpmri_date") or datetime.now().strftime("%Y-%m-%d"),
        "biopsy_type": data.get("prior_biopsy_type") or data.get("planned_biopsy_type") or "sistematica",
        "biopsy_context": "rebiopsia" if data.get("assessment_state") == "post_negative_biopsy_followup" else "diagnostica",
        "total_cores": _safe_int(data.get("total_cores"), 12),
        "positive_cores": _safe_int(data.get("num_cores_positive"), 0),
        "gleason_primary": _safe_int(data.get("gleason_primary"), 3),
        "gleason_secondary": _safe_int(data.get("gleason_secondary"), 3),
        "isup_grade": _safe_int(data.get("isup_grade"), 1),
        "porcentaje_patron_4": _safe_float(data.get("percent_pattern_4"), 0),
        "patron_cribiforme": 1 if _is_truthy(data.get("cribriform_pattern")) else 0,
        "carcinoma_intraductal": 1 if _is_truthy(data.get("intraductal_carcinoma")) else 0,
        "pathologist_notes": str(data.get("repeat_biopsy_trigger") or ""),
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
    return data.get("assessment_state") == "localized_initial" and _is_truthy(data.get("confirmatory_biopsy_planned"))


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
        "psadt_at_bcr": data.get("psadt_months"),
        "time_to_bcr_months": data.get("time_to_recurrence_months"),
        "salvage_treatment": salvage_treatment,
    }


def _build_surgery_payload(data):
    if data.get("assessment_state") != "post_prostatectomy" and not _has_any_value(data, ["pathologic_stage", "margin_location", "surgical_margin"]):
        return None
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

def register_new_patient(data):
    """
    Registra un nuevo paciente y su línea base clínica + tratamiento inicial.
    Retorna (success: bool, message: str)
    """
    try:
        assessment_state = str(data.get("assessment_state") or "").strip()
        advanced_states = {
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
        follow_ups = [dict(row) for row in c.fetchall()]

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

        # 9. Genomics
        c.execute("SELECT * FROM genomic_profile WHERE patient_id = ? ORDER BY test_date DESC LIMIT 1", (patient_id,))
        genomics = c.fetchone()

        # 10. Biopsies
        c.execute("SELECT * FROM biopsy_details WHERE patient_id = ? ORDER BY biopsy_date ASC", (patient_id,))
        biopsies = [dict(row) for row in c.fetchall()]

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
            'genomics': dict(genomics) if genomics else {},
            'biopsies': biopsies,
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
        }
    except Exception as e:
        logger.error(f"Error fetching patient history: {e}")
        return None

def add_followup_visit(data):
    """
    Registra una visita de seguimiento.
    data: {patient_id, psa, testosterone, toxicity, metabolic, treatment, status}
    """
    try:
        patient_id = int(data.get('patient_id'))
        if not patient_exists(patient_id):
            return False, "Paciente no encontrado"

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO follow_up_visits (
                patient_id, psa_current, testosterone_current,
                alp_current, ldh_current, albumin_current, hemoglobin_current,
                ecog_current, pain_score,
                toxicity_events, metabolic_panel, skeletal_events,
                current_treatment, dose_adjustment, disease_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id,
            data.get('psa'), data.get('testosterone'),
            data.get('alp'), data.get('ldh'), data.get('albumin'), data.get('hemoglobin'),
            data.get('ecog'), data.get('pain'),
            json.dumps(data.get('toxicity', {})),
            json.dumps(data.get('metabolic', {})),
            json.dumps(data.get('skeletal', {})),
            data.get('treatment'),
            data.get('dose'),
            data.get('status')
        ))
        
        visit_id = c.lastrowid
        conn.commit()
        conn.close()
        return True, visit_id
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
                upgrade_from_previous, previous_isup, pathologist_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('biopsy_date', datetime.now().strftime('%Y-%m-%d')),
            data.get('biopsy_type', 'sistematica'), data.get('biopsy_context', 'diagnostica'),
            _safe_int(data.get('total_cores', 12), 12), _safe_int(data.get('positive_cores', 0), 0),
            _safe_float(data.get('max_core_involvement_pct', 0), 0),
            _safe_int(data.get('gleason_primary', 3), 3), _safe_int(data.get('gleason_secondary', 3), 3),
            data.get('gleason_tertiary'), _safe_int(data.get('isup_grade', 1), 1),
            _safe_int(data.get('patron_cribiforme', 0), 0), _safe_int(data.get('carcinoma_intraductal', 0), 0),
            _safe_int(data.get('perineural_invasion', 0), 0), _safe_int(data.get('lymphovascular_invasion', 0), 0),
            _safe_float(data.get('porcentaje_patron_4', 0), 0), _safe_float(data.get('porcentaje_patron_5', 0), 0),
            _safe_int(data.get('upgrade_from_previous', 0), 0), data.get('previous_isup'),
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
        c.execute('''
            INSERT INTO surgical_details (
                patient_id, surgery_date, surgery_type, nerve_sparing,
                plnd_performed, plnd_type, nodes_removed, nodes_positive,
                pathological_gleason_primary, pathological_gleason_secondary, pathological_isup,
                pathological_stage, surgical_margin_status, margin_location,
                ece_pathological, svi_pathological, lni_pathological,
                specimen_weight_grams, tumor_volume_pct, capra_s_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('surgery_date'), data.get('surgery_type'),
            data.get('nerve_sparing'), _safe_int(data.get('plnd_performed', 0), 0),
            data.get('plnd_type'), _safe_int(data.get('nodes_removed', 0), 0),
            _safe_int(data.get('nodes_positive', 0), 0),
            data.get('pathological_gleason_primary'), data.get('pathological_gleason_secondary'),
            data.get('pathological_isup'), data.get('pathological_stage'),
            _safe_int(data.get('surgical_margin_status', 0), 0), data.get('margin_location'),
            _safe_int(data.get('ece_pathological', 0), 0), _safe_int(data.get('svi_pathological', 0), 0),
            _safe_int(data.get('lni_pathological', 0), 0),
            data.get('specimen_weight_grams'), data.get('tumor_volume_pct'),
            data.get('capra_s_score')
        ))
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
        c.execute('''
            INSERT INTO radiation_details (
                patient_id, rt_date, rt_context, rt_technique, target,
                total_dose_gy, fractions, dose_per_fraction_gy,
                concurrent_adt, adt_duration_months, adt_agent,
                gu_toxicity_grade, gi_toxicity_grade, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            patient_id, data.get('rt_date'), data.get('rt_context'),
            data.get('rt_technique'), data.get('target'),
            data.get('total_dose_gy'), data.get('fractions'),
            data.get('dose_per_fraction_gy'),
            _safe_int(data.get('concurrent_adt', 0), 0), data.get('adt_duration_months'),
            data.get('adt_agent'),
            _safe_int(data.get('gu_toxicity_grade', 0), 0), _safe_int(data.get('gi_toxicity_grade', 0), 0),
            data.get('notes')
        ))
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

        # 6. Genomic Profile
        c.execute("SELECT * FROM genomic_profile WHERE patient_id = ? ORDER BY test_date DESC LIMIT 1", (patient_id,))
        genomics = c.fetchone()

        # 7. Biopsies
        c.execute("SELECT * FROM biopsy_details WHERE patient_id = ? ORDER BY biopsy_date ASC", (patient_id,))
        biopsies = [dict(row) for row in c.fetchall()]

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
        follow_ups = [dict(row) for row in c.fetchall()]

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

        conn.close()

        return {
            'identity': dict(identity),
            'baseline': dict(baseline) if baseline else {},
            'demographics': dict(demographics) if demographics else {},
            'family_history': family_history,
            'imaging': imaging,
            'genomics': dict(genomics) if genomics else {},
            'biopsies': biopsies,
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
        updated_result = registry.evaluate_module(assessment["module_id"], assessment.get("input_snapshot", {}))
        updated_guidelines = registry.get_guidelines_metadata()
        c.execute(
            '''
            UPDATE clinical_assessments
            SET state = ?, result_snapshot = ?, guideline_versions = ?, status = ?
            WHERE id = ?
            ''',
            (
                updated_result.get("state", assessment.get("state")),
                _json_blob(updated_result),
                _json_blob(updated_guidelines),
                assessment.get("status", "linked"),
                assessment["id"],
            ),
        )
        assessment["state"] = updated_result.get("state", assessment.get("state"))
        assessment["result_snapshot"] = updated_result
        assessment["guideline_versions"] = updated_guidelines
        snapshot = _assessment_longitudinal_snapshot(assessment)
        _ensure_prior_history_row(c, patient_id)
        c.execute(
            '''
            UPDATE prior_clinical_history
            SET latest_assessment_id = ?,
                assessment_source = ?,
                assessment_module = ?,
                assessment_state = ?,
                assessment_summary = ?,
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
            assessment["id"],
            assessment.get("state"),
            f"Recomputación longitudinal: {snapshot['transition_reason']}",
            snapshot["objective_progression"],
            snapshot["monitoring_plan"],
            snapshot["care_overlays"],
            snapshot["guideline_snapshot"],
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
