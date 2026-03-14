# -*- coding: utf-8 -*-
"""
Web Interface — Modelo de Cáncer de Próstata
Flask app que carga el modelo entrenado y sirve predicciones vía API.
"""
import os
import sys
import json
import logging
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for

# Añadir directorio actual al path para importar el modelo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prostate_cancer_model import load_all, predict_patient
from clinical_scores import calculate_all_scores, generate_comprehensive_summary
from db_connector import fetch_prostate_patients
from prostanet.domains.patient_tracking.service import PatientTrackingService
from prostanet.presentation.bootstrap import register_modular_blueprints
from prostanet.presentation.view_models import build_page_chrome
from prostanet.shared.feature_flags import resolve_feature_flags
from tracking_db import configure_db_path, get_stats, init_tracking_db, patient_exists, save_patient_result

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
tracking_service = PatientTrackingService()

# ── Funciones de conversión segura (campos vacíos del formulario) ──────────
def safe_float(val, default=0.0):
    """Convierte a float de forma segura. '' o None → default."""
    if val is None or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    """Convierte a int de forma segura. '' o None → default."""
    if val is None or val == '':
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default

app = Flask(__name__, template_folder="templates", static_folder="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APP_CONFIG = {
    "DB_PATH": os.environ.get("PROSTANET_DB_PATH", os.path.join(BASE_DIR, "prostanet_tracking.db")),
    "MODEL_DIR": os.path.join(BASE_DIR, "model_output"),
    "LOAD_MODEL": True,
    "TESTING": False,
}
DEFAULT_APP_CONFIG.update(resolve_feature_flags(DEFAULT_APP_CONFIG))
REGISTER_NUMERIC_FIELDS = (
    "assessment_id",
    "baseline_psa",
    "testosterone_baseline",
    "hemoglobin",
    "alp",
    "ldh",
    "albumin",
    "rt_primary_dose_gy",
    "prior_docetaxel_cycles",
    "prior_arpi_duration",
    "line_of_therapy",
    "metastasis_count",
    "ecog_score",
    "ipss_score",
    "iief5_score",
    "paquetes_anio",
)
FOLLOWUP_NUMERIC_FIELDS = (
    "psa",
    "testosterone",
    "alp",
    "ldh",
    "albumin",
    "hemoglobin",
    "ecog",
    "pain",
)

app.config.update(DEFAULT_APP_CONFIG)

model = None
artifacts = None
ts_risk = None


def error_response(message, status_code):
    return jsonify({"success": False, "error": message}), status_code


def parse_json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Se requiere un cuerpo JSON válido.")
    return data


def require_non_empty_fields(data, field_names):
    missing = [field for field in field_names if str(data.get(field, "")).strip() == ""]
    if missing:
        raise ValueError(f"Campos requeridos: {', '.join(missing)}")


def validate_numeric_fields(data, field_names):
    for field in field_names:
        value = data.get(field)
        if value in (None, ""):
            continue
        try:
            float(value)
        except (TypeError, ValueError):
            raise ValueError(f"'{field}' debe ser numérico.")


def ensure_model_loaded():
    global model, artifacts, ts_risk

    if model is not None:
        return
    if not app.config.get("LOAD_MODEL", True):
        raise RuntimeError("La carga del modelo está deshabilitada en la configuración actual.")

    import torch
    import prostate_cancer_model as pcm

    loaded_model, loaded_artifacts, loaded_ts_risk = load_all(app.config["MODEL_DIR"])
    pcm.DEVICE = torch.device("cpu")
    model = loaded_model.cpu()
    artifacts = loaded_artifacts
    ts_risk = loaded_ts_risk.cpu() if loaded_ts_risk is not None else None
    logger.info("✅ Modelo cargado desde %s (CPU)", app.config["MODEL_DIR"])


def create_app(config=None):
    app.config.update(DEFAULT_APP_CONFIG)
    if config:
        app.config.update(config)
    app.config.update(resolve_feature_flags(app.config))

    configure_db_path(app.config["DB_PATH"])
    init_tracking_db()
    register_modular_blueprints(app)

    global model, artifacts, ts_risk
    if app.config.get("LOAD_MODEL", True):
        ensure_model_loaded()
    else:
        model = None
        artifacts = None
        ts_risk = None

    return app


@app.route("/")
def index():
    return redirect(url_for("modular_views.clinical_hub"))

@app.route("/calculator")
def calculator():
    return redirect(url_for("modular_views.clinical_hub"))

@app.route("/v2")
def calculator_v2():
    return redirect(url_for("modular_views.clinical_hub"))


@app.route("/predict", methods=["POST"])
def predict():
    return error_response("La calculadora fue retirada. Use el centro clínico por estadio.", 410)
    data = {}
    try:
        ensure_model_loaded()
        data = parse_json_body()

        # Gleason: calcular total desde primario + secundario
        gleason_primary = safe_int(data.get('gleason_primary'), 3)
        gleason_secondary = safe_int(data.get('gleason_secondary'), 3)
        gleason_total = gleason_primary + gleason_secondary

        # Volumen prostático para PSAD
        vol = safe_float(data.get('volumen_prostatico'), 40)
        psa_val = safe_float(data.get('psa'), 0)
        psad = psa_val / vol if vol > 0 else 0.3

        # ISUP Calculation Logic (Prioritize explicit input, else derive from Gleason)
        isup_input = data.get('isup_grade')
        if isup_input is not None and isup_input != '':
             isup_grade = safe_int(isup_input, 1)
        else:
             if gleason_total <= 6: isup_grade = 1
             elif gleason_total == 7 and gleason_primary == 3: isup_grade = 2
             elif gleason_total == 7 and gleason_primary == 4: isup_grade = 3
             elif gleason_total == 8: isup_grade = 4
             elif gleason_total >= 9: isup_grade = 5
             else: isup_grade = 1

        # ── Conversión segura de todas las variables del formulario ──────
        patient = {
            'age':                    safe_int(data.get('age'), 65),
            'psa':                    psa_val,
            'ecog':                   safe_int(data.get('ecog'), 0),
            'stage':                  safe_int(data.get('stage'), 2),
            'gleason':                gleason_total,
            'cci':                    safe_int(data.get('cci'), 0),
            'psad':                   psad,
            'isup_grade':             isup_grade,
            'pirads':                 safe_int(data.get('pirads'), 1),
            'pct_cores_positive':     safe_float(data.get('pct_cores_positive'), 0),
            'num_cores_positive':     safe_int(data.get('num_cores_positive'), 0),
            'total_cores':            safe_int(data.get('total_cores'), 12),
            'max_core_involvement':   safe_float(data.get('max_core_involvement'), 0),
            'perineural_invasion':    safe_int(data.get('pni', data.get('perineural_invasion')), 0),
            'lymphovascular_invasion': safe_int(data.get('lvi', data.get('lymphovascular_invasion')), 0),
            'surgical_margin_status': safe_int(data.get('surgical_margin', data.get('surgical_margin_status')), 0),
            'extracapsular_extension_status': safe_int(data.get('ece_status', data.get('extracapsular_extension_status')), 0),
            'seminal_vesicle_invasion_status': safe_int(data.get('svi_status', data.get('seminal_vesicle_invasion_status')), 0),
            'lymph_node_invasion_status': safe_int(data.get('lni_status', data.get('lymph_node_invasion_status')), 0),
            'race_ethnicity':         str(data.get('race_ethnicity') or 'caucasico'),
            'dre_findings':           str(data.get('dre_findings') or 'T2a'),
            'family_history':         safe_int(data.get('family_history'), 0),
            'bmi':                    safe_float(data.get('bmi'), 25.0),
            'testosterone':           safe_float(data.get('testosterone'), 350.0),
            'free_psa_ratio':         safe_float(data.get('free_psa_ratio'), 0.15),
            'previous_biopsies':      safe_int(data.get('previous_biopsies'), 0),
            'genomic_score':          safe_float(data.get('genomic_score'), 0.0),
        }

        # ── Datos extendidos para herramientas clínicas ──────────────────
        uso_5ari_raw = data.get('uso_5ari', 'no')
        uso_5ari_val = 1 if str(uso_5ari_raw).lower() in ('si', 'sí', '1', 'true', 'yes') else 0

        clinical_data = {
            **patient,
            'gleason_primary':    gleason_primary,
            'gleason_secondary':  gleason_secondary,
            'clinical_tstage':    str(data.get('clinical_tstage') or 'T2a'),
            'volumen_prostatico': vol,
            'surgical_margin_status': patient['surgical_margin_status'],
            'surgical_margin': patient['surgical_margin_status'],
            'extracapsular_extension': patient['extracapsular_extension_status'],
            'ece_status': patient['extracapsular_extension_status'],
            'seminal_vesicle_invasion': patient['seminal_vesicle_invasion_status'],
            'svi_status': patient['seminal_vesicle_invasion_status'],
            'lymph_node_invasion': patient['lymph_node_invasion_status'],
            'lni_status': patient['lymph_node_invasion_status'],
            'gleason_total': gleason_total,
            'isup_grade': isup_grade,
            'pct_cores_positive': safe_float(data.get('pct_cores_positive'), 0),
            'num_cores_positive': safe_int(data.get('num_cores_positive'), 0),
            'total_cores': safe_int(data.get('total_cores'), 12),
            'tipo_biopsia': str(data.get('tipo_biopsia') or 'sistematica'),
            'patron_cribiforme': safe_int(data.get('patron_cribiforme'), 0),
            'carcinoma_intraductal': safe_int(data.get('carcinoma_intraductal'), 0),
            'porcentaje_patron_4': safe_float(data.get('porcentaje_patron_4'), 0),
            'tamano_lesion_mm': safe_float(data.get('tamano_lesion_mm'), 0),
            'psma_resultado': str(data.get('psma_resultado') or 'no_realizado'),
            'bone_scan_result': str(data.get('bone_scan_result') or 'no_realizado'),
            'genomic_test_type': str(data.get('genomic_test_type') or 'ninguna'),
            'hrr_status': str(data.get('hrr_status') or 'desconocido'),
            'msi_status': str(data.get('msi_status') or 'desconocido'),
            'tabaquismo': str(data.get('tabaquismo') or 'nunca'),
            'diabetes_mellitus': safe_int(data.get('diabetes_mellitus'), 0),
            'hipertension': safe_int(data.get('hipertension'), 0),
            'sindrome_metabolico': safe_int(data.get('sindrome_metabolico'), 0),
            'ipss_score': safe_int(data.get('ipss_score'), 0),
            'mpmri_ece_suspicion': safe_int(data.get('mpmri_ece_suspicion'), 0),
            'mpmri_svi_suspicion': safe_int(data.get('mpmri_svi_suspicion'), 0),
            # Variables de laboratorio extendidas
            'creatinina': safe_float(data.get('creatinina'), 0),
            'hemoglobina': safe_float(data.get('hemoglobina'), 0),
            'fosfatasa_alcalina': safe_float(data.get('fosfatasa_alcalina', data.get('alp')), 0),
            'ldh': safe_float(data.get('ldh'), 0),
            'uso_5ari': uso_5ari_val,
        }

        # ── PSA Kinetics (NUEVO) ────────────────────────────────────────
        from clinical_scores import calculate_psa_kinetics
        # Expecting 'psa_history': [{'date': 'YYYY-MM-DD', 'value': 4.5}, ...]
        psa_history_input = data.get('psa_history', [])
        # Convert to tuple list for function
        history_tuples = [(item['date'], float(item['value'])) for item in psa_history_input if 'date' in item and 'value' in item]
        # Include current PSA as well if valid date provided, otherwise assume history includes it or it's separate
        # For simplicity, we calculate based on history provided.
        
        psa_kinetics = calculate_psa_kinetics(history_tuples)

        # ── Ejecutar predicción ML + scores clínicos ─────────────────────
        ml_result = predict_patient(model, artifacts, patient, ts_risk)
        clinical_scores = calculate_all_scores(clinical_data)

        # ── Generar Resumen Clínico Inteligente ──────────────────────────
        # summary = generate_comprehensive_summary(clinical_scores, ml_result, clinical_data)
        
        # ── Generar Reporte Narrativo Textual (NUEVO) ────────────────────
        from report_generator import generate_narrative_report
        narrative_report = generate_narrative_report(clinical_data, clinical_scores, psa_kinetics)
        
        # Guardar en base de datos de seguimiento
        save_patient_result(clinical_data, ml_result, clinical_scores, {'narrative': narrative_report, 'kinetics': psa_kinetics})

        return jsonify({
            "success": True,
            "prediction": ml_result,
            "clinical_scores": clinical_scores,
            "psa_kinetics": psa_kinetics,
            "narrative_report": narrative_report,
        })

    except ValueError as e:
        logger.error(f"❌ Error de Validación (ValueError): {str(e)}")
        logger.error(f"🔍 Datos recibidos: {json.dumps(data, indent=2)}")
        return jsonify({"success": False, "error": f"Error de Datos: {str(e)}"}), 400
    except Exception as e:
        logger.exception("Error en predicción")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def api_stats():
    """Retorna estadísticas agregadas para el dashboard."""
    stats = get_stats()
    return jsonify(stats)

@app.route('/api/sync', methods=['POST'])
def api_sync():
    """Sincroniza pacientes desde la base de datos maestra."""
    ensure_model_loaded()
    patients = fetch_prostate_patients()
    processed_count = 0
    
    for p in patients:
        try:
            # Reutilizar lógica de predicción
            # Preparar datos adicionales necesarios para el modelo
            # (El modelo necesita 'volumen_prostatico' para PSAD si no existe, etc.)
            # Usar defaults seguros si faltan datos
            p_data = p.copy()
            if 'volumen_prostatico' not in p_data: p_data['volumen_prostatico'] = 40
            
            # 1. ML Prediction
            ml_res = predict_patient(model, artifacts, p_data)
            
            # 2. Clinical Scores
            scores = calculate_all_scores(p_data)
            
            # 3. Summary
            summary = generate_comprehensive_summary(scores, ml_res, p_data)
            
            # 4. Save
            p_data['source_type'] = 'urologia_db'
            save_patient_result(p_data, ml_res, scores, summary)
            
            processed_count += 1
        except Exception as e:
            app.logger.error(f"Error processing synced patient {p.get('source_id')}: {e}")
            continue
            
    return jsonify({
        "success": True, 
        "synced_count": processed_count,
        "total_found": len(patients)
    })


@app.route("/patients")
def patients_list():
    page_chrome = build_page_chrome(
        "patients",
        "Pacientes registrados",
        "Cohorte longitudinal vinculada al centro clínico, con filtros operativos, alertas activas y acceso al perfil de cada paciente.",
        content_width_class="max-w-7xl",
    )
    return render_template("patients.html", page_chrome=page_chrome)

@app.route("/dashboard")
def dashboard():
    page_chrome = build_page_chrome(
        "dashboard",
        "Tablero clínico ejecutivo",
        "Vista analítica de la cohorte con métricas, gráficas, benchmarking y líneas de investigación bajo el mismo tema clínico del centro principal.",
        content_width_class="max-w-7xl",
        requires_charts=True,
    )
    return render_template("dashboard.html", page_chrome=page_chrome)

@app.route("/patient_intake")
def patient_intake():
    assessment_id = request.args.get("assessment_id", "").strip()
    if not assessment_id:
        return redirect("/clinical-hub")
    page_chrome = build_page_chrome(
        "patient_intake",
        "Ingreso legacy del paciente",
        "Ruta temporal de compatibilidad. El ingreso visible de nuevos casos ahora debe iniciar desde el centro clínico.",
        content_width_class="max-w-5xl",
    )
    return render_template("patient_intake.html", assessment_id=assessment_id, page_chrome=page_chrome)


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route('/patient_profile/<nss>')
def patient_profile(nss):
    import tracking_db # Import local para evitar circularidad si la hubiera, o simplemente consistencia
    try:
        data = tracking_db.get_patient_history(nss)
        if not data:
            return "Paciente no encontrado", 404
            
        # Calcular edad
        dob_str = data['identity'].get('dob')
        if dob_str:
            try:
                dob = datetime.strptime(str(dob_str), '%Y-%m-%d')
                age = (datetime.now() - dob).days // 365
            except (ValueError, TypeError):
                age = 0
        else:
            age = 0
        data['identity']['age'] = age
        
        recs = {}
        latest_assessment = {}
        state_timeline = []
        care_overlays = []
        if data.get("latest_assessment"):
            from prostanet.shared.presentation_text import (
                humanize_assessment,
                humanize_care_overlays,
                humanize_state_timeline,
            )

            latest_assessment = humanize_assessment(data["latest_assessment"])
            state_timeline = humanize_state_timeline(data.get("state_timeline", []))
            care_overlays = humanize_care_overlays(data.get("care_overlays", []))
        else:
            # Fallback legado solo cuando todavía no existe evaluación modular persistida.
            current_context = dict(data.get('baseline') or {})
            current_context.update(data.get('identity') or {})
            if data.get('prior_history'):
                current_context.update(data['prior_history'])
            if data.get('follow_ups'):
                last_visit = data['follow_ups'][-1]
                if last_visit.get('psa_current') is not None:
                    current_context['psa_current'] = last_visit['psa_current']

            current_context.setdefault('line_of_therapy', 1)
            current_context.setdefault('psa', current_context.get('baseline_psa', 0))
            current_context.setdefault('age', age)
            current_context.setdefault('ecog', current_context.get('ecog_score', 0))
            current_context.setdefault('gleason', current_context.get('gleason_score', 6))

            try:
                from precision_medicine import evaluate_patient_for_mhspc

                recs = evaluate_patient_for_mhspc(current_context)
            except Exception as e:
                logger.warning(f"Error generando recomendaciones: {e}")
                recs = {"info": "Recomendaciones no disponibles para este perfil"}

        page_chrome = build_page_chrome(
            "patients",
            f"Expediente longitudinal de {data['identity'].get('full_name', 'paciente')}",
            "Seguimiento longitudinal integrado con biomarcadores, resultados reportados por el paciente, alertas y trazabilidad clínica.",
            content_width_class="max-w-7xl",
            requires_charts=True,
            show_page_header=False,
        )

        return render_template(
            'patient_profile.html',
            patient=data,
            recommendations=recs,
            latest_assessment=latest_assessment,
            state_timeline=state_timeline,
            care_overlays=care_overlays,
            page_chrome=page_chrome,
        )
    except Exception as e:
        logger.error(f"Error rendering profile: {e}")
        return f"Error interno: {e}", 500

@app.route('/api/add_followup', methods=['POST'])
def add_followup():
    import tracking_db
    try:
        data = parse_json_body()
        require_non_empty_fields(data, ("patient_id",))
        validate_numeric_fields(data, ("patient_id",) + FOLLOWUP_NUMERIC_FIELDS)
        data["patient_id"] = int(float(data["patient_id"]))
        success, msg = tracking_db.add_followup_visit(data)
        if success:
            return jsonify({"success": True, "id": msg})
        if msg == "Paciente no encontrado":
            return error_response(msg, 404)
        return error_response(msg, 400)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error adding followup: {e}")
        return error_response(str(e), 500)


@app.route("/api/register_patient", methods=["POST"])
def register_patient():
    logger.info("Recibida petición POST /api/register_patient")
    try:
        data = parse_json_body()
        data["nss"] = str(data.get("nss", "")).strip()
        data["full_name"] = str(data.get("full_name", "")).strip()
        require_non_empty_fields(data, ("nss", "full_name"))
        validate_numeric_fields(data, REGISTER_NUMERIC_FIELDS)
        logger.info(f"JSON decoded. NSS: {data.get('nss')}")

        assessment = None
        assessment_id = data.get("assessment_id")
        if assessment_id not in (None, ""):
            assessment_id = int(float(assessment_id))
            from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService

            assessment_service = ClinicalAssessmentService()
            assessment = assessment_service.get_draft(assessment_id)
            if not assessment:
                return error_response("Evaluación clínica no encontrada.", 400)
        else:
            assessment_id = None

        if assessment:
            data = tracking_service.merge_assessment_payload(assessment, data)
        else:
            data = tracking_service.canonicalize_payload(data)
        
        from tracking_db import register_new_patient
        patient_id, msg = register_new_patient(data)
        logger.info(f"DB Result: {patient_id}, {msg}")
        
        if patient_id is not None:
            link_warning = None
            if assessment_id is not None:
                from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService

                assessment_service = ClinicalAssessmentService()
                linked, link_msg = assessment_service.attach_to_patient(assessment_id, patient_id)
                if not linked:
                    logger.warning("No se pudo vincular la evaluación clínica %s al paciente %s: %s", assessment_id, patient_id, link_msg)
                    link_warning = link_msg

            # ── Integración Motor Clínico (Precision Medicine) ──
            from precision_medicine import evaluate_patient_for_mhspc, evaluate_patient_for_mcrpc, evaluate_patient_for_nmcrpc
            
            line_therapy = safe_int(data.get('line_of_therapy'), 1)
            meta_site = data.get('metastasis_site', 'M0')
            recommendations = assessment.get("result_snapshot", {}) if assessment else {}
            
            if not assessment:
                try:
                    if line_therapy == 1:
                        recommendations = evaluate_patient_for_mhspc(data)
                    else:
                        # Line > 1 implies Castration Resistance context in this simplified model
                        if meta_site == 'M0':
                            # nmCRPC (No metastasis detected but rising PSA implied by Line > 1)
                            recommendations = evaluate_patient_for_nmcrpc(data)
                        else:
                            # mCRPC (Metastatic)
                            recommendations = evaluate_patient_for_mcrpc(data)

                except Exception as e:
                    logger.error(f"Error generando recomendaciones: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    recommendations = {"error": "Algoritmo clínico no disponible"}

            response = {
                "success": True, 
                "nss": data.get('nss'),
                "patient_id": patient_id,
                "recommendations": recommendations,
                "msg": msg,
                "assessment_id": assessment_id,
                "next_routes": {
                    "profile": f"/patient_profile/{data.get('nss')}",
                    "patients": "/patients",
                    "dashboard": "/dashboard",
                },
            }
            if assessment:
                from prostanet.shared.presentation_text import humanize_assessment

                response["assessment"] = humanize_assessment(assessment)
            if link_warning:
                response["warning"] = link_warning
            return jsonify(response)
        return error_response(msg, 400)
            
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.exception("Error en registro de paciente")
        return error_response(str(e), 500)


# ══════════════════════════════════════════════════════════════════════════════
# ══  REGISTRO DESDE CALCULADORA (Flujo Integrado)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/register_from_calculator", methods=["POST"])
def register_from_calculator():
    return error_response("La calculadora fue retirada. Use el centro clínico por estadio.", 410)
    """
    Registra un paciente directamente desde la calculadora.
    Guarda: identidad, baseline clínico, scores calculados y reporte narrativo.
    El reporte sirve como documento de ingreso y punto de partida del seguimiento.
    """
    try:
        data = request.get_json()
        logger.info(f"Registro desde calculadora: NSS={data.get('nss')}")

        import sqlite3
        conn = sqlite3.connect('prostanet_tracking.db')
        c = conn.cursor()

        nss = data.get('nss', '').strip()
        full_name = data.get('full_name', '').strip()
        dob = data.get('dob')
        dx_date = data.get('diagnosis_date')

        if not nss or not full_name:
            return jsonify({"success": False, "error": "NSS y nombre son requeridos"}), 400

        # Check if patient already exists
        c.execute("SELECT id FROM patient_identity WHERE nss = ?", (nss,))
        existing = c.fetchone()
        if existing:
            conn.close()
            return jsonify({"success": False, "error": f"Paciente con NSS {nss} ya existe"}), 400

        # 1. Insert patient identity
        c.execute("""INSERT INTO patient_identity (nss, full_name, dob, diagnosis_date)
                     VALUES (?, ?, ?, ?)""", (nss, full_name, dob, dx_date))
        patient_id = c.lastrowid

        # 2. Insert clinical baseline
        c.execute("""INSERT INTO clinical_baseline (
            patient_id, baseline_psa, testosterone_baseline, hemoglobin, alp, ldh,
            tnm_stage, gleason_score, metastasis_site, volume_disease, ecog_score,
            genomic_test_done, hrr_status, msi_status, comorbidities_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            patient_id,
            data.get('baseline_psa', 0),
            data.get('testosterone_baseline', 0),
            data.get('hemoglobin', 0),
            data.get('alp', 0),
            data.get('ldh', 0),
            data.get('tnm_stage', 'T2a'),
            data.get('gleason_score', 6),
            data.get('metastasis_site', 'M0'),
            data.get('volume_disease', 'Low'),
            data.get('ecog_score', 0),
            data.get('genomic_test_done', 0),
            data.get('hrr_status', 'desconocido'),
            data.get('msi_status', 'desconocido'),
            json.dumps({
                'cci': data.get('cci', 0),
                'bmi': data.get('bmi', 25),
                'family_history': data.get('family_history', 0),
                'tabaquismo': data.get('tabaquismo', 'nunca'),
                'diabetes_mellitus': data.get('diabetes_mellitus', 0),
                'hipertension': data.get('hipertension', 0),
                'sindrome_metabolico': data.get('sindrome_metabolico', 0),
                'uso_5ari': data.get('uso_5ari', 'no'),
                'creatinina': data.get('creatinina', 0),
                'ipss_score': data.get('ipss_score', 0),
            })
        ))

        # 3. Insert biopsy details if available
        cores_pos = data.get('cores_positivos', 0)
        cores_tot = data.get('cores_totales', 12)
        if cores_pos > 0 or cores_tot > 0:
            try:
                c.execute("""INSERT INTO biopsy_details (
                    patient_id, biopsy_date, biopsy_type, cores_taken, cores_positive,
                    gleason_primary, gleason_secondary, gleason_sum, grade_group, pirads_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    patient_id,
                    dx_date or datetime.now().strftime('%Y-%m-%d'),
                    data.get('tipo_biopsia', 'sistematica'),
                    cores_tot,
                    cores_pos,
                    data.get('gleason_score', 6) // 2,  # approximation
                    data.get('gleason_score', 6) - (data.get('gleason_score', 6) // 2),
                    data.get('gleason_score', 6),
                    1,  # Will be recalculated
                    data.get('pirads', 0)
                ))
            except Exception as e:
                logger.warning(f"Error guardando biopsia: {e}")

        # 4. Save demographics
        try:
            c.execute("""INSERT INTO patient_demographics (
                patient_id, tabaquismo, diabetes_mellitus, hipertension,
                sindrome_metabolico, ipss_score, ocupacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                patient_id,
                data.get('tabaquismo', 'nunca'),
                data.get('diabetes_mellitus', 0),
                data.get('hipertension', 0),
                data.get('sindrome_metabolico', 0),
                data.get('ipss_score', 0),
                'No especificada'
            ))
        except Exception as e:
            logger.warning(f"Error guardando demographics: {e}")

        # 5. Save calculated scores as prior clinical history
        scores = data.get('calculated_scores', {})
        report = data.get('narrative_report', '')
        kinetics = data.get('psa_kinetics', {})

        try:
            c.execute("""INSERT OR REPLACE INTO prior_clinical_history (
                patient_id, calculated_scores_json, narrative_report, psa_kinetics_json, source
            ) VALUES (?, ?, ?, ?, ?)""", (
                patient_id,
                json.dumps(scores),
                report,
                json.dumps(kinetics),
                'calculator'
            ))
        except Exception:
            # Table may not have these columns, create it
            try:
                c.execute("""CREATE TABLE IF NOT EXISTS calculator_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER,
                    calculated_scores_json TEXT,
                    narrative_report TEXT,
                    psa_kinetics_json TEXT,
                    source TEXT DEFAULT 'calculator',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(patient_id) REFERENCES patient_identity(id)
                )""")
                c.execute("""INSERT INTO calculator_reports (
                    patient_id, calculated_scores_json, narrative_report, psa_kinetics_json, source
                ) VALUES (?, ?, ?, ?, ?)""", (
                    patient_id, json.dumps(scores), report, json.dumps(kinetics), 'calculator'
                ))
            except Exception as e2:
                logger.warning(f"Error guardando scores/report: {e2}")

        conn.commit()
        conn.close()

        logger.info(f"Paciente registrado desde calculadora: {nss} (ID={patient_id})")

        return jsonify({
            "success": True,
            "patient_id": patient_id,
            "nss": nss,
            "msg": f"Paciente {full_name} registrado con scores y reporte como documento de ingreso"
        })

    except Exception as e:
        logger.exception("Error registrando desde calculadora")
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# ══  FASE B & C — NUEVOS ENDPOINTS API (Expediente Longitudinal + Investigación)
# ══════════════════════════════════════════════════════════════════════════════

# ── Demográficos México ──────────────────────────────────────────────────────
@app.route('/api/demographics/<int:patient_id>', methods=['POST'])
def api_save_demographics(patient_id):
    """Guarda o actualiza datos demográficos del paciente."""
    try:
        from tracking_db import save_demographics
        data = request.get_json()
        success = save_demographics(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando demográficos"}), 400
    except Exception as e:
        logger.error(f"Error en demographics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Historia Familiar ────────────────────────────────────────────────────────
@app.route('/api/family_history/<int:patient_id>', methods=['POST'])
def api_save_family_history(patient_id):
    """Guarda historia familiar detallada (lista de familiares)."""
    try:
        from tracking_db import save_family_history
        data = request.get_json()
        relatives = data.get('relatives', [])
        success = save_family_history(patient_id, relatives)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando historia familiar"}), 400
    except Exception as e:
        logger.error(f"Error en family history: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Estudios de Imagen ───────────────────────────────────────────────────────
@app.route('/api/imaging/<int:patient_id>', methods=['POST'])
def api_save_imaging(patient_id):
    """Registra un estudio de imagen (MRI, PSMA-PET, gammagrama, etc)."""
    try:
        from tracking_db import save_imaging_study
        data = request.get_json()
        success = save_imaging_study(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando imagen"}), 400
    except Exception as e:
        logger.error(f"Error en imaging: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Perfil Genómico ──────────────────────────────────────────────────────────
@app.route('/api/genomics/<int:patient_id>', methods=['POST'])
def api_save_genomics(patient_id):
    """Guarda perfil genómico del paciente."""
    try:
        from tracking_db import save_genomic_profile
        data = request.get_json()
        success = save_genomic_profile(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando genómica"}), 400
    except Exception as e:
        logger.error(f"Error en genomics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Biopsias ─────────────────────────────────────────────────────────────────
@app.route('/api/biopsy/<int:patient_id>', methods=['POST'])
def api_save_biopsy(patient_id):
    """Registra una biopsia detallada."""
    try:
        from tracking_db import save_biopsy
        data = request.get_json()
        success = save_biopsy(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando biopsia"}), 400
    except Exception as e:
        logger.error(f"Error en biopsy: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Vigilancia Activa ────────────────────────────────────────────────────────
@app.route('/api/active_surveillance/<int:patient_id>/enroll', methods=['POST'])
def api_enroll_as(patient_id):
    """Inscribe paciente en Vigilancia Activa."""
    try:
        from tracking_db import enroll_in_as
        data = request.get_json()
        success = enroll_in_as(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error inscribiendo en VA"}), 400
    except Exception as e:
        logger.error(f"Error en AS enroll: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/active_surveillance/<int:patient_id>/exit', methods=['POST'])
def api_exit_as(patient_id):
    """Registra salida de Vigilancia Activa."""
    try:
        from tracking_db import exit_as
        data = request.get_json()
        success = exit_as(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error saliendo de VA"}), 400
    except Exception as e:
        logger.error(f"Error en AS exit: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Recurrencia Bioquímica ───────────────────────────────────────────────────
@app.route('/api/bcr/<int:patient_id>', methods=['POST'])
def api_save_bcr(patient_id):
    """Registra recurrencia bioquímica."""
    try:
        from tracking_db import save_bcr
        data = request.get_json()
        success = save_bcr(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando BCR"}), 400
    except Exception as e:
        logger.error(f"Error en BCR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Cirugía ──────────────────────────────────────────────────────────────────
@app.route('/api/surgery/<int:patient_id>', methods=['POST'])
def api_save_surgery(patient_id):
    """Registra detalles de prostatectomía radical."""
    try:
        from tracking_db import save_surgical_details
        data = request.get_json()
        success = save_surgical_details(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando cirugía"}), 400
    except Exception as e:
        logger.error(f"Error en surgery: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Radioterapia ─────────────────────────────────────────────────────────────
@app.route('/api/radiation/<int:patient_id>', methods=['POST'])
def api_save_radiation(patient_id):
    """Registra detalles de radioterapia."""
    try:
        from tracking_db import save_radiation_details
        data = request.get_json()
        success = save_radiation_details(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando radioterapia"}), 400
    except Exception as e:
        logger.error(f"Error en radiation: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── PROs (Patient-Reported Outcomes) ─────────────────────────────────────────
@app.route('/api/pros/<int:patient_id>', methods=['POST'])
def api_save_pros(patient_id):
    """Guarda evaluación de PROs."""
    try:
        from tracking_db import save_pro_assessment
        data = request.get_json()
        success = save_pro_assessment(patient_id, data)
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error guardando PROs"}), 400
    except Exception as e:
        logger.error(f"Error en PROs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Alertas Inteligentes ─────────────────────────────────────────────────────
@app.route('/api/alerts/<int:patient_id>', methods=['GET'])
def api_get_alerts(patient_id):
    """Obtiene alertas activas de un paciente."""
    try:
        if not patient_exists(patient_id):
            return error_response("Paciente no encontrado", 404)
        from tracking_db import get_patient_alerts
        alerts = get_patient_alerts(patient_id)
        return jsonify({"success": True, "alerts": alerts})
    except Exception as e:
        logger.error(f"Error obteniendo alertas: {e}")
        return error_response(str(e), 500)


@app.route('/api/alerts/<int:patient_id>/check', methods=['POST'])
def api_check_alerts(patient_id):
    """Ejecuta el motor de alertas y genera nuevas si aplican."""
    try:
        if not patient_exists(patient_id):
            return error_response("Paciente no encontrado", 404)
        from tracking_db import check_and_generate_alerts
        new_alerts = check_and_generate_alerts(patient_id)
        return jsonify({"success": True, "new_alerts": new_alerts})
    except Exception as e:
        logger.error(f"Error generando alertas: {e}")
        return error_response(str(e), 500)


@app.route('/api/alerts/acknowledge/<int:alert_id>', methods=['POST'])
def api_acknowledge_alert(alert_id):
    """Marca una alerta como vista/reconocida."""
    try:
        from tracking_db import acknowledge_alert
        data = request.get_json() or {}
        success = acknowledge_alert(alert_id, user=data.get('user', 'system'))
        if success:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Error actualizando alerta"}), 400
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Exportación de Datos ─────────────────────────────────────────────────────
@app.route('/api/export/<nss>', methods=['GET'])
def api_export_patient(nss):
    """Exporta datos completos del paciente en JSON."""
    try:
        from tracking_db import export_patient_data
        fmt = request.args.get('format', 'dict')
        if fmt not in {"dict", "json"}:
            return error_response("Formato de exportación no soportado", 400)
        data = export_patient_data(nss, format=fmt)
        if data is None:
            return error_response("Paciente no encontrado", 404)
        if fmt == 'json':
            return app.response_class(data, mimetype='application/json')
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error exportando datos: {e}")
        return error_response(str(e), 500)


@app.route('/api/export/<nss>/csv', methods=['GET'])
def api_export_patient_csv(nss):
    """Exporta datos aplanados del paciente como CSV."""
    try:
        from tracking_db import export_patient_data
        import csv
        import io
        flat = export_patient_data(nss, format='csv_ready')
        if flat is None:
            return error_response("Paciente no encontrado", 404)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=flat.keys())
        writer.writeheader()
        writer.writerow(flat)
        csv_str = output.getvalue()

        return app.response_class(
            csv_str,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=prostanet_{nss}.csv'}
        )
    except Exception as e:
        logger.error(f"Error exportando CSV: {e}")
        return error_response(str(e), 500)


# ── Confrontación con Estudios Pivotales ─────────────────────────────────────
@app.route('/api/pivotal_match/<nss>', methods=['GET'])
def api_pivotal_match(nss):
    """Evalúa elegibilidad del paciente contra estudios pivotales."""
    try:
        from tracking_db import get_patient_full_record
        from pivotal_studies import match_patient_to_studies, generate_pivotal_report

        record = get_patient_full_record(nss)
        if not record:
            return jsonify({"error": "Paciente no encontrado"}), 404

        # Construir datos del paciente para el motor de matching
        baseline = record.get('baseline', {})
        identity = record.get('identity', {})
        genomics = record.get('genomics', {})
        surgery = record.get('surgery', {})

        # Calcular edad
        from datetime import datetime
        dob = identity.get('dob')
        age = 65
        if dob:
            try:
                dob_dt = datetime.strptime(str(dob), '%Y-%m-%d')
                age = (datetime.now() - dob_dt).days // 365
            except Exception:
                pass

        # PSA actual (último follow-up o baseline)
        follow_ups = record.get('follow_ups', [])
        psa_current = follow_ups[-1].get('psa_current', 0) if follow_ups else baseline.get('baseline_psa', 0)

        # Claves deben coincidir con lo que espera match_patient_to_studies()
        metastasis_site = baseline.get('metastasis_site', 'M0') or 'M0'
        metastasis_status = 'M0' if metastasis_site in ('M0', '', None) else 'M1'

        prior_hist = record.get('prior_history') or {}
        prior_docetaxel_cycles = prior_hist.get('prior_docetaxel_cycles', 0) or 0
        prior_arpi_agent = prior_hist.get('prior_arpi_agent')

        patient_for_match = {
            'age': age,
            'psa': psa_current or 0,
            'psa_basal': baseline.get('baseline_psa', 0) or 0,
            'gleason_score': baseline.get('gleason_score', 6) or 6,
            'ecog_score': baseline.get('ecog_score', 0) or 0,
            'clinical_tstage': baseline.get('tnm_stage', 'T2a') or 'T2a',
            'metastasis_status': metastasis_status,
            'metastasis_site': metastasis_site,
            'volume_chaarted': baseline.get('volume_disease', 'Low') or 'Low',
            'hrr_status': genomics.get('hrr_overall') or baseline.get('hrr_status', 'Desconocido') or 'Desconocido',
            'msi_status': genomics.get('msi_status') or baseline.get('msi_status', 'Estable') or 'Estable',
            'prior_therapy': [],
            'prior_prostatectomy': bool(surgery),
            'bone_metastases': metastasis_site in ('Hueso', 'Oseas', 'Bone'),
            'visceral_metastases': metastasis_site in ('Visceral', 'Higado', 'Pulmon'),
            'fit_for_chemotherapy': (baseline.get('ecog_score', 0) or 0) <= 1,
        }

        # Construir lista de terapias previas
        if prior_docetaxel_cycles > 0:
            patient_for_match['prior_therapy'].append('Docetaxel')
        if prior_arpi_agent:
            patient_for_match['prior_therapy'].append(str(prior_arpi_agent))
            patient_for_match['prior_therapy'].append('ARPI')
        if prior_hist.get('rt_primary_received'):
            patient_for_match['prior_therapy'].append('Radioterapia')

        matches = match_patient_to_studies(patient_for_match)
        report = generate_pivotal_report(patient_for_match)

        # Guardar matching en DB y construir respuesta limpia para JSON
        from tracking_db import save_pivotal_matching
        matches_clean = []
        for m in matches:
            study = m.get('study', {})
            # Datos limpios para save y para respuesta JSON
            match_flat = {
                'study_name': study.get('name', ''),
                'scenario': study.get('scenario', ''),
                'phase': study.get('phase', ''),
                'intervention': study.get('intervention', ''),
                'key_result': study.get('key_result', ''),
                'eligible': m.get('eligible', False),
                'match_score': m.get('match_score', 0),
                'criteria_met': m.get('criteria_met', []),
                'criteria_failed': m.get('criteria_failed', []),
                'expected_outcome': study.get('key_result', ''),
                'applicability': study.get('mexican_applicability', ''),
            }
            matches_clean.append(match_flat)
            try:
                save_pivotal_matching(identity['id'], match_flat)
            except Exception:
                pass

        return jsonify({
            "success": True,
            "matches": matches_clean,
            "report": report,
            "total_studies_evaluated": len(matches_clean),
            "eligible_count": sum(1 for m in matches_clean if m.get('eligible')),
        })
    except Exception as e:
        logger.exception(f"Error en pivotal matching: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Dashboard Analytics Avanzado ──────────────────────────────────────────────
@app.route('/api/dashboard_stats', methods=['GET'])
def api_dashboard_stats():
    """Retorna estadísticas avanzadas para el dashboard ejecutivo."""
    try:
        import sqlite3
        conn = sqlite3.connect(app.config["DB_PATH"])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        stats = {}

        # Total patients (identity table)
        c.execute("SELECT COUNT(*) as n FROM patient_identity")
        stats['total_patients'] = c.fetchone()['n']

        # Metastasis distribution
        c.execute("""SELECT COALESCE(cb.metastasis_site, 'M0') as site, COUNT(*) as n
                     FROM patient_identity pi
                     LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
                     GROUP BY site""")
        stats['metastasis_distribution'] = {r['site']: r['n'] for r in c.fetchall()}

        # Volume distribution
        c.execute("""SELECT COALESCE(cb.volume_disease, 'No registrado') as vol, COUNT(*) as n
                     FROM patient_identity pi
                     LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
                     GROUP BY vol""")
        stats['volume_distribution'] = {r['vol']: r['n'] for r in c.fetchall()}

        # ECOG distribution
        c.execute("""SELECT COALESCE(cb.ecog_score, 0) as ecog, COUNT(*) as n
                     FROM patient_identity pi
                     LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
                     GROUP BY ecog""")
        stats['ecog_distribution'] = {str(r['ecog']): r['n'] for r in c.fetchall()}

        # PSA values for histogram
        c.execute(
            """
            SELECT CAST(cb.baseline_psa AS REAL) AS baseline_psa
            FROM clinical_baseline cb
            WHERE NULLIF(TRIM(COALESCE(cb.baseline_psa, '')), '') IS NOT NULL
              AND CAST(cb.baseline_psa AS REAL) > 0
            """
        )
        stats['psa_values'] = [r['baseline_psa'] for r in c.fetchall()]

        # Monthly enrollment
        c.execute("""SELECT strftime('%Y-%m', pi.diagnosis_date) as month, COUNT(*) as n
                     FROM patient_identity pi
                     WHERE pi.diagnosis_date IS NOT NULL
                     GROUP BY month ORDER BY month""")
        stats['enrollment_by_month'] = {r['month']: r['n'] for r in c.fetchall()}

        # Alert counts by type
        c.execute("""SELECT alert_type, COUNT(*) as n FROM smart_alerts
                     WHERE acknowledged = 0 GROUP BY alert_type""")
        stats['active_alerts_by_type'] = {r['alert_type']: r['n'] for r in c.fetchall()}

        # Total active alerts
        c.execute("SELECT COUNT(*) as n FROM smart_alerts WHERE acknowledged = 0")
        stats['total_active_alerts'] = c.fetchone()['n']

        # Data completeness
        c.execute("SELECT COUNT(*) as n FROM patient_demographics")
        stats['demographics_count'] = c.fetchone()['n']

        c.execute("SELECT COUNT(*) as n FROM genomic_profile")
        stats['genomics_count'] = c.fetchone()['n']

        c.execute("SELECT COUNT(*) as n FROM biopsy_details")
        stats['biopsies_count'] = c.fetchone()['n']

        c.execute("SELECT COUNT(*) as n FROM imaging_studies")
        stats['imaging_count'] = c.fetchone()['n']

        c.execute("SELECT COUNT(*) as n FROM patient_pros")
        stats['pros_count'] = c.fetchone()['n']

        c.execute("SELECT COUNT(*) as n FROM surgical_details")
        stats['surgeries_count'] = c.fetchone()['n']

        c.execute("SELECT COUNT(*) as n FROM active_surveillance WHERE exit_date IS NULL")
        stats['active_surveillance_count'] = c.fetchone()['n']

        c.execute("SELECT COUNT(*) as n FROM follow_up_visits")
        stats['total_followups'] = c.fetchone()['n']

        c.execute("PRAGMA table_info(clinical_assessments)")
        assessment_columns = {row["name"] for row in c.fetchall()}
        input_snapshot_column = (
            "input_snapshot_json"
            if "input_snapshot_json" in assessment_columns
            else "input_snapshot"
        )

        c.execute(
            f"""
            SELECT ca.state, ca.{input_snapshot_column} AS input_snapshot_payload
            FROM clinical_assessments ca
            INNER JOIN prior_clinical_history ph ON ph.latest_assessment_id = ca.id
            """
        )
        assessment_rows = c.fetchall()
        stats["latest_assessment_count"] = len(assessment_rows)

        advanced_states = {
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume",
            "m0_crpc",
            "m1_crpc",
        }
        mhspc_states = {
            "mcspc_oligo_metachronous",
            "mcspc_low_volume_sync_oligo",
            "mcspc_high_volume",
        }

        def _truthy(value):
            return str(value).lower() in {"1", "true", "yes", "si", "on"}

        biomarker_complete = 0
        pros_baseline = 0
        ddi_reviewed = 0
        cv_documented = 0
        lft_documented = 0
        psma_documented = 0
        dxa_documented = 0
        bone_protection = 0
        salvage_documented = 0
        line_context_documented = 0
        molecular_reported = 0

        for row in assessment_rows:
            payload = json.loads(row["input_snapshot_payload"] or "{}")
            state = row["state"]
            if state in advanced_states and payload.get("hrr_gene") not in (None, "", "Desconocido") and payload.get("biomarker_source") not in (None, "", "Desconocida"):
                biomarker_complete += 1
            if any(payload.get(field) not in (None, "") for field in ["baseline_qol", "baseline_urinary_qol", "baseline_sexual_qol", "baseline_bowel_qol"]):
                pros_baseline += 1
            if _truthy(payload.get("drug_interaction_reviewed")):
                ddi_reviewed += 1
            if _truthy(payload.get("cv_risk_documented")):
                cv_documented += 1
            if payload.get("child_pugh_score") or _truthy(payload.get("hepatic_risk_factors")):
                lft_documented += 1
            if _truthy(payload.get("psma_positive")) and not _truthy(payload.get("psma_negative_dominant_lesions")):
                psma_documented += 1
            if state in mhspc_states and _truthy(payload.get("dxa_baseline_done")):
                dxa_documented += 1
            if state in mhspc_states and (_truthy(payload.get("bone_protection_started")) or _truthy(payload.get("calcium_vitd_started"))):
                bone_protection += 1
            if state in {"recurrence_bcr", "post_prostatectomy"} and (
                payload.get("salvage_local_feasible") not in (None, "")
                or payload.get("eligible_pelvic_therapy") not in (None, "")
            ):
                salvage_documented += 1
            if state == "m1_crpc" and payload.get("mcrpc_line_context"):
                line_context_documented += 1
            if payload.get("molecular_report_date") or payload.get("molecular_assay_date"):
                molecular_reported += 1

        stats["biomarker_complete_count"] = biomarker_complete
        stats["pros_baseline_count"] = pros_baseline
        stats["ddi_reviewed_count"] = ddi_reviewed
        stats["cv_documented_count"] = cv_documented
        stats["lft_documented_count"] = lft_documented
        stats["psma_eligibility_count"] = psma_documented
        stats["dxa_documented_count"] = dxa_documented
        stats["bone_protection_count"] = bone_protection
        stats["salvage_documented_count"] = salvage_documented
        stats["mcrpc_line_context_count"] = line_context_documented
        stats["molecular_report_count"] = molecular_reported

        c.execute(
            f"""
            SELECT COUNT(DISTINCT ph.patient_id) as n
            FROM prior_clinical_history ph
            INNER JOIN treatment_history th ON th.patient_id = ph.patient_id
            WHERE ph.current_state IN ({",".join(["?"] * len(mhspc_states))})
              AND th.drug_scheme IS NOT NULL
              AND th.drug_scheme != ''
              AND th.drug_scheme != 'ADT_MONO'
            """,
            tuple(mhspc_states),
        )
        stats["mhspc_combination_adherence_count"] = c.fetchone()["n"]

        conn.close()
        return jsonify({"success": True, **stats})
    except Exception as e:
        logger.error(f"Error en dashboard_stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Listado de Pacientes ─────────────────────────────────────────────────────
@app.route('/api/patients', methods=['GET'])
def api_list_patients():
    """Retorna lista de pacientes registrados."""
    try:
        import sqlite3
        conn = sqlite3.connect('prostanet_tracking.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT pi.id, pi.nss, pi.full_name, pi.dob, pi.diagnosis_date,
                   cb.baseline_psa, cb.metastasis_site, cb.volume_disease, cb.ecog_score,
                   (SELECT COUNT(*) FROM follow_up_visits fv WHERE fv.patient_id = pi.id) as visit_count,
                   (SELECT COUNT(*) FROM smart_alerts sa WHERE sa.patient_id = pi.id AND sa.acknowledged = 0) as alert_count
            FROM patient_identity pi
            LEFT JOIN clinical_baseline cb ON cb.patient_id = pi.id
            ORDER BY pi.created_at DESC
        """)
        patients = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify({"success": True, "patients": patients})
    except Exception as e:
        logger.error(f"Error listando pacientes: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Perfil Completo (JSON) ───────────────────────────────────────────────────
@app.route('/api/patient/<nss>', methods=['GET'])
def api_get_patient(nss):
    """Retorna el expediente completo del paciente en JSON."""
    try:
        from tracking_db import get_patient_full_record
        record = get_patient_full_record(nss)
        if not record:
            return error_response("Paciente no encontrado", 404)
        return jsonify({"success": True, "patient": record})
    except Exception as e:
        logger.error(f"Error obteniendo paciente: {e}")
        return error_response(str(e), 500)


# ── Resumen de estudios pivotales disponibles ─────────────────────────────────
@app.route('/api/pivotal_studies', methods=['GET'])
def api_pivotal_studies():
    """Retorna resumen de todos los estudios pivotales disponibles."""
    try:
        from pivotal_studies import get_studies_summary, count_studies_by_scenario
        return jsonify({
            "success": True,
            "studies": get_studies_summary(),
            "by_scenario": count_studies_by_scenario()
        })
    except Exception as e:
        logger.error(f"Error obteniendo estudios: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    # Iniciar servidor
    create_app()
    print("Starting Flask server...")
    app.run(host="0.0.0.0", port=8080, debug=False)
