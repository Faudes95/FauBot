# -*- coding: utf-8 -*-
"""
Web Interface — Modelo de Cáncer de Próstata
Flask app que carga el modelo entrenado y sirve predicciones vía API.
"""
import os
import sys
import json
import logging
import sqlite3
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for

# Añadir directorio actual al path para importar el modelo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prostate_cancer_model import load_all
from prostanet.domains.patient_tracking.service import PatientTrackingService
from prostanet.presentation.bootstrap import register_modular_blueprints
from prostanet.presentation.ui_assets import build_ui_assets
from prostanet.presentation.view_models import build_page_chrome
from prostanet.shared.feature_flags import resolve_feature_flags
from prostanet.shared.official_diagnosis import diagnosis_capture_options
from tracking_db import configure_db_path, get_stats, init_tracking_db, patient_exists

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
    "line_of_therapy_number",
    "metastasis_count",
    "ecog_score",
    "gleason_primary",
    "gleason_secondary",
    "isup_grade",
    "ipss_score",
    "iief5_score",
    "paquetes_anio",
    "weight_kg",
    "bmi_current",
    "weight_loss_6m_pct",
    "mini_cog_score",
    "fatigue_score",
    "g8_food_intake",
    "g8_weight_loss",
    "g8_mobility",
    "g8_neuropsych",
    "g8_bmi",
    "g8_medications",
    "g8_self_health",
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


@app.context_processor
def inject_ui_assets():
    return {"ui_assets": build_ui_assets()}

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


def _reconciled_patient_snapshot(record):
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    reconciliation = build_reconciled_state(record, record.get("latest_assessment"))
    return {
        "reconciled_state": reconciliation.get("reconciled_state") or "diagnostic_workup",
        "reconciled_management_track": reconciliation.get("reconciled_management_track") or "diagnostic_surveillance",
        "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
        "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
    }


def _analysis_dataset_payload():
    from prostanet.domains.dashboard.dashboard_facade import get_analysis_dataset_bundle

    return get_analysis_dataset_bundle()


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
    """Calculadora legacy retirada. Use el centro clínico por estadio."""
    return error_response("La calculadora fue retirada. Use el centro clínico por estadio.", 410)

@app.route('/api/stats', methods=['GET'])
def api_stats():
    """Retorna estadísticas agregadas para el dashboard."""
    stats = get_stats()
    return jsonify(stats)

@app.route('/api/sync', methods=['POST'])
def api_sync():
    """Sincronización legacy retirada. Use el centro clínico para ingesta de documentos."""
    return error_response("La sincronización legacy fue retirada. Use ingesta de documentos desde el perfil del paciente.", 410)


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
    from prostanet.domains.patient_tracking.therapy_catalog import therapy_catalog_entries

    assessment_id = request.args.get("assessment_id", "").strip()
    if not assessment_id:
        return redirect("/clinical-hub")
    page_chrome = build_page_chrome(
        "patient_intake",
        "Ingreso legacy del paciente",
        "Ruta temporal de compatibilidad. El ingreso visible de nuevos casos ahora debe iniciar desde el centro clínico.",
        content_width_class="max-w-5xl",
    )
    return render_template(
        "patient_intake.html",
        assessment_id=assessment_id,
        page_chrome=page_chrome,
        therapy_catalog_entries=therapy_catalog_entries(),
        diagnosis_capture_options=diagnosis_capture_options(),
    )


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
        tracking_db.refresh_followup_agenda(data)
        longitudinal_bundle = tracking_db.refresh_longitudinal_intelligence(nss, force_recompute=False)
        data = tracking_db.get_patient_full_record(nss) or tracking_db.get_patient_history(nss)
            
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
        profile_view = {}
        if data.get("latest_assessment"):
            from prostanet.shared.presentation_text import (
                humanize_assessment,
                humanize_care_overlays,
                humanize_state_timeline,
            )
            from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

            latest_assessment = humanize_assessment(data["latest_assessment"])
            state_timeline = humanize_state_timeline(data.get("state_timeline", []))
            care_overlays = humanize_care_overlays(data.get("care_overlays", []))
            profile_view = build_patient_profile_view_model(
                patient=data,
                latest_assessment_raw=data.get("latest_assessment"),
                latest_assessment=latest_assessment,
                state_timeline=state_timeline,
                care_overlays=care_overlays,
                longitudinal_bundle=longitudinal_bundle,
            )
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

            current_context['line_of_therapy'] = current_context.get('line_of_therapy_number') or current_context.get('line_of_therapy') or 0
            current_context['psa'] = current_context.get('baseline_psa') or current_context.get('psa') or 0
            current_context['age'] = current_context.get('age') or age or 0
            current_context['ecog_score'] = current_context.get('ecog_score') or current_context.get('ecog') or 0
            current_context['ecog'] = current_context.get('ecog_score') or 0
            current_context['gleason_score'] = current_context.get('gleason_score') or current_context.get('gleason') or 6
            current_context['gleason'] = current_context.get('gleason_score') or 6
            current_context['metastasis_count'] = current_context.get('metastasis_count') or 0
            current_context['child_pugh_score'] = current_context.get('child_pugh_score') or 'A'
            current_context['rt_primary_received'] = current_context.get('rt_primary_received') or 0

            from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc
            from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

            try:
                recs = evaluate_patient_for_mhspc(current_context)
            except Exception as e:
                logger.warning(f"Error generando recomendaciones: {e}")
                recs = {"info": "Recomendaciones no disponibles para este perfil"}

            try:
                profile_view = build_patient_profile_view_model(
                    patient=data,
                    latest_assessment_raw={},
                    latest_assessment={},
                    state_timeline=[],
                    care_overlays=[],
                    recommendations=recs,
                    longitudinal_bundle=longitudinal_bundle,
                )
            except Exception as e:
                logger.warning(f"Error construyendo el perfil estructurado: {e}")
                profile_view = {
                    "diagnostic_state": False,
                    "management_track": "",
                    "clinical_compass": {},
                    "stage_specific_panels": [],
                    "algorithm_panels": [],
                    "pivotal_panel": {"eligible_matches": [], "partial_matches": [], "ineligible_matches": [], "hidden_ineligible_count": 0, "eligible_count": 0, "partial_count": 0, "ineligible_count": 0, "last_evaluated_at": "", "has_results": False},
                    "longitudinal_sections": [],
                    "supportive_evidence_context": [],
                    "source_citations": [],
                    "care_overlays": [],
                    "agenda_board": {},
                    "next_due_items": [],
                    "overdue_items": [],
                    "visit_schema": {},
                    "therapy_checkpoints": [],
                    "protocol_comparators": [],
                    "protocol_trace": {},
                    "data_provenance": [],
                    "missing_input_actions": [],
                    "clinical_signals": {
                        "critical_missing": [],
                        "awaiting_review": [],
                        "active_safety": [],
                    },
                    "next_best_action": {},
                    "transition_proposals": [],
                    "recommendation_audit": [],
                    "document_board": {},
                    "advanced_panel_context": {},
                    "missing_inputs_by_panel": {},
                    "evidence_applicability": {},
                    "recommendations": recs,
                    "copilot": {},
                }

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
            profile_view=profile_view,
            agenda_board=profile_view.get("agenda_board", {}) if isinstance(profile_view, dict) else {},
            visit_schema=profile_view.get("visit_schema", {}) if isinstance(profile_view, dict) else {},
            agenda_item_form_context=profile_view.get("agenda_item_form_context", {}) if isinstance(profile_view, dict) else {},
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
            return jsonify(
                {
                    "success": True,
                    "id": msg["followup_id"] if isinstance(msg, dict) else msg,
                    "visit_record_id": msg.get("visit_record_id") if isinstance(msg, dict) else None,
                    "agenda": msg.get("agenda") if isinstance(msg, dict) else None,
                    "intelligence": msg.get("intelligence") if isinstance(msg, dict) else None,
                }
            )
        if msg == "Paciente no encontrado":
            return error_response(msg, 404)
        return error_response(msg, 400)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error adding followup: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<nss>/agenda', methods=['GET'])
def api_patient_agenda(nss):
    import tracking_db
    try:
        agenda = tracking_db.get_patient_agenda(nss)
        if agenda is None:
            return error_response("Paciente no encontrado", 404)
        record = tracking_db.get_patient_full_record(nss)
        return jsonify({"success": True, "agenda": agenda, **_reconciled_patient_snapshot(record or {})})
    except Exception as e:
        logger.error(f"Error getting patient agenda: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/visits', methods=['POST'])
def api_save_stage_visit(patient_id):
    import tracking_db
    try:
        data = parse_json_body()
        success, payload = tracking_db.save_stage_visit_bundle(patient_id, data)
        if success:
            return jsonify({"success": True, **payload})
        if payload == "Paciente no encontrado":
            return error_response(payload, 404)
        return error_response(payload, 400)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error saving stage visit: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents', methods=['POST'])
def api_upload_source_document(patient_id):
    import tracking_db
    try:
        file_storage = request.files.get("file")
        payload = {
            "document_type": request.form.get("document_type", "auto"),
            "title": request.form.get("title", ""),
            "source_date": request.form.get("source_date", ""),
            "uploaded_by": request.form.get("uploaded_by", "clinico"),
        }
        success, result = tracking_db.save_source_document(patient_id, file_storage, payload)
        if not success:
            if result == "Paciente no encontrado":
                return error_response(result, 404)
            return error_response(result, 400)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Error uploading source document: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents', methods=['GET'])
def api_list_source_documents(patient_id):
    import tracking_db
    try:
        documents = tracking_db.list_source_documents(patient_id)
        if documents is None:
            return error_response("Paciente no encontrado", 404)
        return jsonify({"success": True, "documents": documents})
    except Exception as e:
        logger.error(f"Error listing source documents: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents/<int:document_id>/extract', methods=['POST'])
def api_extract_source_document(patient_id, document_id):
    import tracking_db
    try:
        body = request.get_json(silent=True) or {}
        success, result = tracking_db.extract_source_document(
            patient_id,
            document_id,
            document_type=body.get("document_type", ""),
        )
        if not success:
            return error_response(result, 400 if result != "Documento no encontrado" else 404)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"Error extracting source document: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents/<int:document_id>/verify', methods=['POST'])
def api_verify_source_document(patient_id, document_id):
    import tracking_db
    try:
        data = parse_json_body()
        success, result = tracking_db.verify_source_document(patient_id, document_id, data)
        if not success:
            return error_response(result, 400 if result not in {"Paciente no encontrado", "Documento no encontrado"} else 404)
        return jsonify({"success": True, **result})
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error verifying source document: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/documents/<int:document_id>/facts', methods=['GET'])
def api_get_source_document_facts(patient_id, document_id):
    import tracking_db
    try:
        bundle = tracking_db.get_document_facts(patient_id, document_id)
        if bundle is None:
            return error_response("Documento no encontrado", 404)
        return jsonify({"success": True, **bundle})
    except Exception as e:
        logger.error(f"Error fetching source document facts: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/agenda/<int:agenda_id>/complete', methods=['POST'])
def api_complete_agenda_item(patient_id, agenda_id):
    import tracking_db
    try:
        body = request.get_json(silent=True) or {}
        success = tracking_db.complete_followup_agenda_item(
            patient_id,
            agenda_id,
            visit_record_id=body.get("visit_record_id"),
        )
        if not success:
            return error_response("No fue posible completar el item de agenda", 400)
        identity = tracking_db.get_patient_history(patient_id)
        agenda = tracking_db.get_patient_agenda(identity["identity"]["nss"] if identity else patient_id)
        return jsonify({"success": True, "agenda": agenda})
    except Exception as e:
        logger.error(f"Error completing agenda item: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/visit-schema', methods=['GET'])
def api_visit_schema(patient_id):
    import tracking_db
    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        from prostanet.domains.patient_tracking.followup_agenda import build_visit_schema

        reconciliation = _reconciled_patient_snapshot(patient)
        state = request.args.get("state") or reconciliation["reconciled_state"]
        track = request.args.get("track") or reconciliation["reconciled_management_track"]
        agenda_item = None
        capture_fields = [field.strip() for field in str(request.args.get("fields") or "").split(",") if field.strip()]
        capture_context = None
        agenda_id = request.args.get("agenda_id")
        alert_key = str(request.args.get("alert_key") or "").strip()
        presentation = str(request.args.get("presentation") or "standard").strip() or "standard"
        if agenda_id:
            try:
                agenda_id_int = int(agenda_id)
            except (TypeError, ValueError):
                return error_response("agenda_id inválido", 400)
            agenda_bundle = tracking_db.get_patient_agenda(patient_id) or {}
            agenda_item = next(
                (item for item in (agenda_bundle.get("items") or []) if int(item.get("id") or 0) == agenda_id_int),
                None,
            )
            if agenda_item is None:
                return error_response("Item de agenda no encontrado", 404)
        elif alert_key:
            bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
            alert = next((item for item in (bundle.get("copilot_alerts") or []) if str(item.get("alert_key") or "") == alert_key), None)
            if alert is None:
                return error_response("Alerta clínica no encontrada", 404)
            capture_fields = [field for field in (alert.get("fields_to_capture") or []) if str(field or "").strip()]
            capture_context = {
                "title": alert.get("title") or "Resolver alerta clínica",
                "summary": alert.get("message") or "",
                "rationale": alert.get("why_now") or alert.get("message") or "Completa variables faltantes del flujo clínico.",
                "recommended_action": alert.get("recommended_action") or "",
                "decision_affected": alert.get("resolves_decision_domain") or alert.get("decision_domain") or "",
                "module_owner": alert.get("category") or "",
                "decision_targets": [alert.get("decision_domain")] if alert.get("decision_domain") else [],
                "reasoning": [alert.get("recommended_action")] if alert.get("recommended_action") else [],
                "required_inputs": capture_fields,
                "linked_agenda_ids": list(alert.get("linked_agenda_ids") or []),
                "linked_agenda_keys": list(alert.get("linked_agenda_keys") or []),
                "encounter_key": alert.get("encounter_key") or "",
                "alert_key": alert_key,
                "action_type": alert.get("action_type") or "capture",
                "expected_document_type": alert.get("expected_document_type") or "auto",
                "form_scope": {
                    "mode": "capture_block",
                    "focus": request.args.get("capture_block") or alert.get("capture_block") or "clinical_completion",
                    "fields": capture_fields,
                },
            }
        elif capture_fields:
            capture_context = {
                "title": request.args.get("capture_title") or "Completar datos críticos",
                "rationale": request.args.get("capture_rationale") or "Completa variables faltantes del flujo clínico.",
                "decision_affected": request.args.get("decision_affected") or "",
                "module_owner": request.args.get("module_owner") or "",
                "form_scope": {
                    "mode": "capture_block",
                    "focus": request.args.get("capture_group") or "clinical_completion",
                    "fields": capture_fields,
                },
            }
        visit_schema = build_visit_schema(
            state,
            track,
            agenda_item=agenda_item,
            field_scope=capture_fields or None,
            capture_context=capture_context,
            presentation=presentation,
        )
        return jsonify(
            {
                "success": True,
                "state": state,
                "management_track": track,
                "visit_schema": visit_schema,
                "agenda_item_context": visit_schema.get("agenda_item_context"),
                "alert_key": alert_key,
                "presentation": presentation,
            }
        )
    except Exception as e:
        logger.error(f"Error getting visit schema: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/protocol-comparison', methods=['GET'])
def api_protocol_comparison(patient_id):
    import tracking_db
    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        from prostanet.domains.patient_tracking.followup_agenda import build_protocol_comparators

        reconciliation = _reconciled_patient_snapshot(patient)
        state = reconciliation["reconciled_state"]
        track = reconciliation["reconciled_management_track"]
        return jsonify({"success": True, "comparators": build_protocol_comparators(state, track), "state": state, "management_track": track, **reconciliation})
    except Exception as e:
        logger.error(f"Error getting protocol comparison: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/events', methods=['POST'])
def api_record_patient_event(patient_id):
    import tracking_db
    try:
        data = parse_json_body()
        event_type = str(data.get("event_type", "")).strip()
        if not event_type:
            return error_response("Se requiere event_type", 400)
        event_id = tracking_db.record_patient_event(
            patient_id,
            event_type=event_type,
            event_date=data.get("event_date"),
            state_context=data.get("state_context", ""),
            management_track=data.get("management_track", ""),
            source_type=data.get("source_type", "manual_event"),
            source_record_id=data.get("source_record_id"),
            status=data.get("status", "recorded"),
            payload=data.get("payload") or {},
            mcode_focus=data.get("mcode_focus") or {},
        )
        if event_id is None:
            return error_response("No fue posible registrar el evento", 400)
        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=True)
        agenda = tracking_db.get_patient_agenda(patient_id)
        return jsonify({"success": True, "event_id": event_id, "agenda": agenda, **bundle})
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error recording patient event: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/results', methods=['POST'])
def api_save_patient_result(patient_id):
    import tracking_db
    try:
        data = parse_json_body()
        success, payload = tracking_db.save_structured_result(patient_id, data)
        if success:
            return jsonify({"success": True, **payload})
        return error_response(payload, 400 if payload != "Paciente no encontrado" else 404)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error saving structured result: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/state-transition/<int:proposal_id>/confirm', methods=['POST'])
def api_confirm_state_transition(patient_id, proposal_id):
    import tracking_db
    try:
        body = request.get_json(silent=True) or {}
        success, payload = tracking_db.confirm_state_transition_proposal(
            patient_id,
            proposal_id,
            confirmed_by=body.get("confirmed_by", "system"),
        )
        if success:
            return jsonify({"success": True, **payload})
        return error_response(payload, 400)
    except Exception as e:
        logger.error(f"Error confirming transition proposal: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/next-best-action', methods=['GET'])
def api_next_best_action(patient_id):
    import tracking_db
    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        action = tracking_db.get_patient_next_best_action(patient_id)
        if action is None:
            return error_response("Paciente no encontrado", 404)
        return jsonify({"success": True, "next_best_action": action, **_reconciled_patient_snapshot(patient)})
    except Exception as e:
        logger.error(f"Error getting next best action: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>/signals', methods=['GET'])
def api_patient_signals(patient_id):
    import tracking_db
    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return error_response("Paciente no encontrado", 404)
        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        signals = bundle.get("signals")
        if signals is None:
            return error_response("Paciente no encontrado", 404)
        patient = tracking_db.get_patient_full_record(patient_id) or patient
        from prostanet.shared.presentation_text import (
            humanize_assessment,
            humanize_care_overlays,
            humanize_state_timeline,
        )
        from prostanet.domains.patient_tracking.profile_compass import build_patient_profile_view_model

        latest_assessment = humanize_assessment(patient["latest_assessment"]) if patient.get("latest_assessment") else {}
        state_timeline = humanize_state_timeline(patient.get("state_timeline", []))
        care_overlays = humanize_care_overlays(patient.get("care_overlays", []))
        profile_view = build_patient_profile_view_model(
            patient=patient,
            latest_assessment_raw=patient.get("latest_assessment"),
            latest_assessment=latest_assessment,
            state_timeline=state_timeline,
            care_overlays=care_overlays,
            longitudinal_bundle=bundle,
        )
        return jsonify(
            {
                "success": True,
                "signals": signals,
                "transition_proposals": bundle.get("transition_proposals", []),
                "next_best_action": bundle.get("next_best_action", {}),
                "module_data_contracts": profile_view.get("module_data_contracts", {}),
                "missing_input_actions": profile_view.get("missing_input_actions", []),
                "missing_input_capture_tasks": profile_view.get("missing_input_capture_tasks", []),
                "intake_capture_target": profile_view.get("intake_capture_target"),
                "followup_capture_target": profile_view.get("followup_capture_target"),
                "intake_completion_block": profile_view.get("intake_completion_block", {}),
                "followup_completion_block": profile_view.get("followup_completion_block", {}),
                "psa_observability": profile_view.get("psa_observability", {}),
                "clinical_journey_events": profile_view.get("clinical_journey_events", []),
                "agenda_resolution_trace": profile_view.get("agenda_resolution_trace", []),
                "therapy_checkpoints": profile_view.get("therapy_checkpoints", []),
                "evidence_applicability": profile_view.get("evidence_applicability", {}),
                "master_followup_plan": bundle.get("master_followup_plan", profile_view.get("master_followup_plan", {})),
                "master_followup_summary": bundle.get("master_followup_summary", profile_view.get("master_followup_summary", {})),
                "copilot_alerts": bundle.get("copilot_alerts", []),
                "alert_summary": bundle.get("alert_summary", {}),
                "encounters": bundle.get("encounters", []),
                "schedule_anchor_strength": bundle.get("schedule_anchor_strength", "strong"),
                "outcome_events_summary": bundle.get("outcome_events_summary", profile_view.get("outcome_events_summary", {})),
                "pending_adjudications": bundle.get("pending_adjudications", profile_view.get("pending_adjudications", [])),
                "current_response_state": bundle.get("current_response_state", profile_view.get("current_response_state", {})),
                "current_course_status": bundle.get("current_course_status", profile_view.get("current_course_status", "")),
                "last_adjudicated_event": bundle.get("last_adjudicated_event", profile_view.get("last_adjudicated_event", {})),
                "trial_comparable_endpoints": bundle.get("trial_comparable_endpoints", profile_view.get("trial_comparable_endpoints", [])),
                "current_trial_comparable_profile": bundle.get("current_trial_comparable_profile", profile_view.get("current_trial_comparable_profile", {})),
                "prognostic_modifiers": bundle.get("prognostic_modifiers", profile_view.get("prognostic_modifiers", [])),
                "prognostic_recommended_actions": bundle.get("prognostic_recommended_actions", profile_view.get("prognostic_recommended_actions", [])),
                "prognostic_followup_impact": bundle.get("prognostic_followup_impact", profile_view.get("prognostic_followup_impact", [])),
                "prognostic_capture_targets": bundle.get("prognostic_capture_targets", profile_view.get("prognostic_capture_targets", [])),
                "backbone_alignment": bundle.get("backbone_alignment", profile_view.get("backbone_alignment", {})),
                "cadence_adjusted_by": bundle.get("cadence_adjusted_by", profile_view.get("cadence_adjusted_by", [])),
                "psa_forecast": bundle.get("psa_forecast", profile_view.get("psa_forecast", {})),
                "forecast_reliability": bundle.get("forecast_reliability", profile_view.get("forecast_reliability", {})),
                "live_benchmark": bundle.get("live_benchmark", profile_view.get("live_benchmark", {})),
                "benchmark_reliability": bundle.get("benchmark_reliability", profile_view.get("benchmark_reliability", {})),
                **_reconciled_patient_snapshot(patient),
            }
        )
    except Exception as e:
        logger.error(f"Error getting patient signals: {e}")
        return error_response(str(e), 500)


@app.route('/api/patients/<int:patient_id>', methods=['DELETE'])
def api_delete_patient_profile(patient_id):
    import tracking_db
    try:
        success, payload = tracking_db.delete_patient_profile(patient_id)
        if not success:
            return error_response(payload, 404)
        return jsonify({"success": True, "deleted": payload})
    except Exception as e:
        logger.error(f"Error deleting patient {patient_id}: {e}")
        return error_response(str(e), 500)


@app.route("/api/register_patient", methods=["POST"])
def register_patient():
    logger.info("Recibida petición POST /api/register_patient")
    try:
        import tracking_db
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
        patient_id, msg = register_new_patient(data, assessment=assessment)
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

            # ── Benchmark exploratorio legacy (no autoritativo) ──
            from prostanet.shared.precision_medicine_legacy import evaluate_patient_for_mhspc, evaluate_patient_for_mcrpc, evaluate_patient_for_nmcrpc
            from prostanet.domains.patient_tracking.event_graph import build_processing_summary

            line_therapy = safe_int(data.get('line_of_therapy_number') or data.get('line_of_therapy'), 1)
            meta_site = data.get('metastasis_site', 'M0')
            recommendations = assessment.get("result_snapshot", {}) if assessment else {}
            exploratory_benchmark = None
            
            if not assessment:
                try:
                    if line_therapy == 1:
                        exploratory_benchmark = evaluate_patient_for_mhspc(data)
                    else:
                        # Line > 1 implies Castration Resistance context in this simplified model
                        if meta_site == 'M0':
                            # nmCRPC (No metastasis detected but rising PSA implied by Line > 1)
                            exploratory_benchmark = evaluate_patient_for_nmcrpc(data)
                        else:
                            # mCRPC (Metastatic)
                            exploratory_benchmark = evaluate_patient_for_mcrpc(data)

                except Exception as e:
                    logger.error(f"Error generando recomendaciones: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    exploratory_benchmark = {"error": "Algoritmo clínico legacy no disponible"}

            full_record = tracking_service.get_full_record(data.get("nss"))
            processing_summary = build_processing_summary(
                data.get("assessment_state") or (assessment.get("state") if assessment else ""),
                data,
                full_record,
            )
            loop_payload = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=True)

            response = {
                "success": True, 
                "nss": data.get('nss'),
                "patient_id": patient_id,
                "recommendations": recommendations,
                "recommendation_mode": "guideline_modular" if assessment else "exploratory_legacy_only",
                "exploratory_benchmark": exploratory_benchmark,
                "processing_summary": processing_summary,
                "longitudinal_intelligence": loop_payload,
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
    """Registro desde calculadora legacy retirado. Use el centro clínico."""
    return error_response("La calculadora fue retirada. Use el centro clínico por estadio.", 410)


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
        import tracking_db

        tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        alerts = tracking_db.get_patient_alerts(patient_id)
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
        import tracking_db

        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        return jsonify(
            {
                "success": True,
                "new_alerts": [alert.get("alert_key") or alert.get("title") for alert in bundle.get("copilot_alerts", [])],
                "alerts": bundle.get("copilot_alerts", []),
                "alert_summary": bundle.get("alert_summary", {}),
            }
        )
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
        from clinical_scores import docetaxel_fitness
        from pivotal_studies import match_patient_to_studies, generate_pivotal_report
        from prostanet.domains.patient_tracking.mhspc_evidence import is_mhspc_state, visible_trials_for_mhspc_state
        from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

        record = get_patient_full_record(nss)
        if not record:
            return jsonify({"error": "Paciente no encontrado"}), 404

        # Construir datos del paciente para el motor de matching
        baseline = record.get('baseline', {})
        identity = record.get('identity', {})
        genomics = record.get('genomics', {})
        surgery = record.get('surgery', {})
        latest_assessment = record.get("latest_assessment") or {}
        reconciliation = build_reconciled_state(record, latest_assessment)
        current_state = reconciliation.get("reconciled_state") or ""

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
        docetaxel_payload = {}
        docetaxel_payload.update(baseline or {})
        docetaxel_payload.update(prior_hist or {})
        docetaxel_payload.update((latest_assessment.get("input_snapshot") or {}))
        docetaxel_bundle = docetaxel_fitness(docetaxel_payload)

        patient_for_match = {
            'state': current_state,
            'age': age,
            'psa': psa_current or 0,
            'psa_basal': baseline.get('baseline_psa', 0) or 0,
            'gleason_score': baseline.get('gleason_score', 6) or 6,
            'gleason_primary': baseline.get('gleason_primary'),
            'gleason_secondary': baseline.get('gleason_secondary'),
            'ecog_score': baseline.get('ecog_score', 0) or 0,
            'clinical_tstage': baseline.get('tnm_stage', 'T2a') or 'T2a',
            'metastasis_status': metastasis_status,
            'metastasis_site': metastasis_site,
            'metastasis_count': baseline.get('metastasis_count', 0) or 0,
            'volume_chaarted': baseline.get('volume_disease', 'Low') or 'Low',
            'hrr_status': genomics.get('hrr_overall') or baseline.get('hrr_status', 'Desconocido') or 'Desconocido',
            'msi_status': genomics.get('msi_status') or baseline.get('msi_status', 'Estable') or 'Estable',
            'prior_therapy': [],
            'prior_prostatectomy': bool(surgery),
            'bone_metastases': metastasis_site in ('Hueso', 'Oseas', 'Bone'),
            'visceral_metastases': metastasis_site in ('Visceral', 'Higado', 'Pulmon'),
            'fit_for_chemotherapy': bool(docetaxel_bundle.get('fit_for_docetaxel')),
            'fit_for_docetaxel': bool(docetaxel_bundle.get('fit_for_docetaxel')),
            'disease_temporality': 'metachronous' if current_state in {'mcspc_oligo_metachronous', 'mcspc_high_volume_metachronous'} else 'sync',
            'de_novo': current_state in {'mcspc_low_volume_sync_oligo', 'mcspc_high_volume_sync'},
            'peripheral_neuropathy_grade': docetaxel_payload.get('peripheral_neuropathy_grade'),
            'frailty_status': docetaxel_payload.get('frailty_status'),
            'child_pugh_score': docetaxel_payload.get('child_pugh_score'),
            'cv_risk_documented': docetaxel_payload.get('cv_risk_documented'),
            'drug_interaction_reviewed': docetaxel_payload.get('drug_interaction_reviewed'),
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
                'eligibility_details': {
                    'match_score': m.get('match_score', 0),
                    'criteria_met': m.get('criteria_met', []),
                    'criteria_failed': m.get('criteria_failed', []),
                },
                'expected_outcome': study.get('key_result', ''),
                'applicability': study.get('mexican_applicability', ''),
            }
            matches_clean.append(match_flat)
            try:
                save_pivotal_matching(identity['id'], match_flat)
            except Exception:
                pass

        hidden_cross_scenario = set()
        if is_mhspc_state(current_state):
            _, hidden_cross_scenario = visible_trials_for_mhspc_state(current_state, patient_for_match)

        visible_matches_clean = [
            item for item in matches_clean
            if item.get("study_name") not in hidden_cross_scenario
        ]
        eligible_matches = [m for m in visible_matches_clean if m.get("eligible")]
        partial_matches = [m for m in visible_matches_clean if not m.get("eligible") and float(m.get("match_score", 0) or 0) >= 0.7]
        ineligible_matches = [m for m in visible_matches_clean if m not in eligible_matches and m not in partial_matches]

        return jsonify({
            "success": True,
            "matches": matches_clean,
            "visible_matches": visible_matches_clean,
            "eligible_matches": eligible_matches,
            "partial_matches": partial_matches,
            "ineligible_matches": ineligible_matches,
            "hidden_cross_scenario_count": len(hidden_cross_scenario),
            "report": report,
            "total_studies_evaluated": len(matches_clean),
            "eligible_count": len(eligible_matches),
            "partial_count": len(partial_matches),
            "ineligible_count": len(ineligible_matches),
        })
    except Exception as e:
        logger.exception(f"Error en pivotal matching: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Dashboard Analytics Avanzado ──────────────────────────────────────────────
@app.route('/api/dashboard/summary', methods=['GET'])
def api_dashboard_summary():
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_summary_payload

        return jsonify({"success": True, **get_dashboard_summary_payload()})
    except Exception as e:
        logger.error(f"Error en dashboard_summary: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/dashboard/analytics', methods=['GET'])
def api_dashboard_analytics():
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_analytics_bundle

        return jsonify({"success": True, **get_dashboard_analytics_bundle()})
    except Exception as e:
        logger.error(f"Error en dashboard_analytics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/dashboard/calibration', methods=['GET'])
def api_dashboard_calibration():
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_calibration_bundle

        return jsonify({"success": True, **get_dashboard_calibration_bundle()})
    except Exception as e:
        logger.error(f"Error en dashboard_calibration: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/dashboard/research-intelligence', methods=['GET'])
def api_dashboard_research_intelligence():
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_research_bundle

        return jsonify({"success": True, **get_dashboard_research_bundle()})
    except Exception as e:
        logger.error(f"Error en dashboard_research_intelligence: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/dashboard_stats', methods=['GET'])
def api_dashboard_stats():
    """Alias rápido y compatible para el tablero ejecutivo."""
    try:
        from prostanet.domains.dashboard.dashboard_facade import get_dashboard_summary_payload

        summary = get_dashboard_summary_payload()
        summary["analytics_endpoint"] = "/api/dashboard/analytics"
        summary["calibration_endpoint"] = "/api/dashboard/calibration"
        summary["research_endpoint"] = "/api/dashboard/research-intelligence"
        return jsonify({"success": True, **summary})
    except Exception as e:
        logger.error(f"Error en dashboard_stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/analysis_dataset_export', methods=['GET'])
def api_analysis_dataset_export():
    try:
        payload = _analysis_dataset_payload()
        return jsonify({"success": True, "analysis_dataset_export": payload["analysis_rows"]})
    except Exception as e:
        logger.error(f"Error exporting analysis dataset: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/cohort_completeness', methods=['GET'])
def api_cohort_completeness():
    try:
        payload = _analysis_dataset_payload()
        return jsonify({"success": True, "cohort_completeness": payload["cohort_completeness_rows"], "summary": payload["summary"]})
    except Exception as e:
        logger.error(f"Error computing cohort completeness: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/research_readiness', methods=['GET'])
def api_research_readiness():
    try:
        payload = _analysis_dataset_payload()
        return jsonify({"success": True, "research_readiness": payload["research_readiness_rows"], "summary": payload["summary"]})
    except Exception as e:
        logger.error(f"Error computing research readiness: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/endpoint_readiness', methods=['GET'])
def api_endpoint_readiness():
    try:
        payload = _analysis_dataset_payload()
        return jsonify({"success": True, "endpoint_readiness": payload["endpoint_readiness_rows"], "summary": payload["summary"]})
    except Exception as e:
        logger.error(f"Error computing endpoint readiness: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Listado de Pacientes ─────────────────────────────────────────────────────
@app.route('/api/patients', methods=['GET'])
def api_list_patients():
    """Retorna lista de pacientes registrados."""
    try:
        import sqlite3
        conn = sqlite3.connect(app.config["DB_PATH"])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT pi.id, pi.nss, pi.full_name, pi.dob, pi.diagnosis_date,
                   cb.baseline_psa, cb.metastasis_site, cb.volume_disease, cb.ecog_score,
                   (SELECT COUNT(*) FROM follow_up_visits fv WHERE fv.patient_id = pi.id) as visit_count,
                   (SELECT COUNT(*) FROM smart_alerts sa WHERE sa.patient_id = pi.id AND sa.acknowledged = 0 AND COALESCE(sa.active, 1) = 1) as alert_count
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
