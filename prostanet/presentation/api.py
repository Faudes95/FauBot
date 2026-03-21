from __future__ import annotations

from flask import Blueprint, jsonify, request
import tracking_db

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService
from prostanet.domains.clinical_assessments.scenario_harness import run_scenario_harness
from prostanet.domains.patient_tracking.service import PatientTrackingService
from prostanet.shared.converters import safe_bool, safe_float, safe_int
from prostanet.shared.presentation_text import (
    humanize_assessment,
    humanize_care_overlays,
    humanize_evidence,
    humanize_guidelines,
    humanize_module_listing,
    humanize_registration_context,
    humanize_result,
    humanize_schema,
    humanize_sources,
    humanize_state_timeline,
)
from prostanet.domains.research_intelligence.comparative_effectiveness import (
    run_propensity_analysis,
)
from prostanet.domains.research_intelligence.consent_governance import (
    create_consent_draft,
    finalize_consent_draft_payload,
    get_consent_draft_payload,
    get_current_consent_payload,
    sign_consent_draft_payload,
)
from prostanet.domains.research_intelligence.dynamic_cohorting import (
    create_dynamic_cohort,
    get_dynamic_cohort_payload,
    list_dynamic_cohort_payload,
)
from prostanet.domains.research_intelligence.institutional_benchmarking import (
    build_institutional_benchmark_payload,
)
from prostanet.domains.research_intelligence.multivariate_analysis import (
    build_cox_payload,
    build_logistic_payload,
)
from prostanet.domains.research_intelligence.operational_outcomes import (
    build_operational_outcomes_payload,
)
from prostanet.domains.research_intelligence.quality_indicators import (
    build_quality_indicator_payload,
)
from prostanet.domains.research_intelligence.research_exports import (
    build_cdisc_mapping_payload,
    build_csv_export_payload,
    build_redcap_export_payload,
)
from prostanet.domains.research_intelligence.survival_registry import (
    build_survival_registry_payload,
)


modular_api = Blueprint("modular_api", __name__)
registry = ModuleRegistry()
assessment_service = ClinicalAssessmentService()
tracking_service = PatientTrackingService()


def _parse_json() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Se requiere un cuerpo JSON valido.")
    return data


def _coerce_payload(payload: dict, schema: dict) -> dict:
    coerced = dict(payload)
    for field in schema.get("fields", []):
        name = field["name"]
        value = coerced.get(name)
        if value in (None, ""):
            continue
        text = str(value)
        if field.get("field_type") == "number":
            coerced[name] = float(text) if "." in text else int(float(text))
            continue
        if field.get("field_type") == "select":
            try:
                numeric = float(text)
            except (TypeError, ValueError):
                continue
            coerced[name] = numeric if "." in text else int(numeric)
    return coerced


def _validated_bool(value, field_name: str, *, default=None):
    parsed = safe_bool(value, default=default)
    if value not in (None, "") and parsed is None:
        raise ValueError(f"Valor no válido para '{field_name}'. Use true/false, 1/0, si/no o yes/no.")
    return parsed


def _serialize_alerts(alerts):
    """Acepta tanto ClinicalAlert como dicts ya serializados."""
    serialized = []
    for alert in alerts or []:
        if isinstance(alert, dict):
            serialized.append(alert)
        elif hasattr(alert, "to_dict"):
            serialized.append(alert.to_dict())
        elif hasattr(alert, "__dict__"):
            serialized.append(dict(alert.__dict__))
        else:
            serialized.append({"value": alert})
    return serialized


@modular_api.route("/api/state-classifier", methods=["POST"])
def state_classifier() -> tuple:
    try:
        payload = _coerce_payload(_parse_json(), registry.get_state_classifier_schema())
        result = registry.classify_state(payload)
        result["state_label"] = humanize_module_listing({"module": result["state"], "title": result["state"], "core_questions": []})["title"]
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/modules", methods=["GET"])
def list_modules() -> tuple:
    modules = [humanize_module_listing(module) for module in registry.list_modules()]
    return jsonify({"success": True, "modules": modules})


@modular_api.route("/api/modules/state-classifier/schema", methods=["GET"])
def state_classifier_schema() -> tuple:
    return jsonify({"success": True, "schema": humanize_schema(registry.get_state_classifier_schema())})


@modular_api.route("/api/modules/<module_id>/schema", methods=["GET"])
def module_schema(module_id: str) -> tuple:
    try:
        return jsonify({"success": True, "schema": humanize_schema(registry.get_module_schema(module_id))})
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404


@modular_api.route("/api/modules/<module_id>/evaluate", methods=["POST"])
def evaluate_module(module_id: str) -> tuple:
    try:
        schema = registry.get_module_schema(module_id)
        payload = _coerce_payload(_parse_json(), schema)
        return jsonify({"success": True, "result": humanize_result(registry.evaluate_module(module_id, payload))})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/clinical-assessments/draft", methods=["POST"])
def create_clinical_assessment_draft() -> tuple:
    try:
        data = _parse_json()
        module_id = str(data.get("module_id", "")).strip()
        if not module_id:
            raise ValueError("Se requiere el identificador del módulo clínico.")

        schema = registry.get_module_schema(module_id)
        payload = _coerce_payload(data.get("payload", {}), schema)
        result = registry.evaluate_module(module_id, payload)
        assessment_id = assessment_service.create_draft(
            module_id=module_id,
            state=result["state"],
            input_snapshot=payload,
            result_snapshot=result,
            guideline_versions=registry.get_guidelines_metadata(),
        )
        if assessment_id is None:
            raise RuntimeError("No se pudo crear el borrador de evaluación clínica.")

        assessment = assessment_service.get_draft(assessment_id)
        registration_context = tracking_service.build_registration_context(
            module_schema=schema,
            module_id=module_id,
            state=result["state"],
            assessment_input=payload,
        )

        return jsonify(
            {
                "success": True,
                "assessment_id": assessment_id,
                "assessment": humanize_assessment(assessment) if assessment else None,
                "result": humanize_result(result),
                **humanize_registration_context(registration_context),
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/clinical-assessments/<int:assessment_id>", methods=["GET"])
def get_clinical_assessment_draft(assessment_id: int) -> tuple:
    assessment = assessment_service.get_draft(assessment_id)
    if not assessment:
        return jsonify({"success": False, "error": "Evaluación clínica no encontrada."}), 404
    module_id = assessment.get("module_id", "")
    schema = registry.get_module_schema(module_id) if module_id else {"fields": []}
    registration_context = tracking_service.build_registration_context(
        module_schema=schema,
        module_id=module_id,
        state=assessment.get("state", ""),
        assessment_input=assessment.get("input_snapshot", {}) or {},
        assessment_result=assessment.get("result_snapshot", {}) or {},
    )
    return jsonify(
        {
            "success": True,
            "assessment": humanize_assessment(assessment),
            **humanize_registration_context(registration_context),
        }
    )


@modular_api.route("/api/modules/<module_id>/evidence", methods=["GET"])
def module_evidence(module_id: str) -> tuple:
    try:
        return jsonify({"success": True, "evidence": humanize_evidence(registry.get_module_evidence(module_id))})
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404


@modular_api.route("/api/modules/<module_id>/sources", methods=["GET"])
def module_sources(module_id: str) -> tuple:
    try:
        return jsonify({"success": True, "sources": humanize_sources(registry.get_module_sources(module_id))})
    except KeyError:
        return jsonify({"success": False, "error": "Modulo no soportado."}), 404


@modular_api.route("/api/guidelines/metadata", methods=["GET"])
def guideline_metadata() -> tuple:
    return jsonify({"success": True, "guidelines": humanize_guidelines(registry.get_guidelines_metadata())})


@modular_api.route("/api/clinical-calibration", methods=["GET"])
def clinical_calibration() -> tuple:
    summary = run_scenario_harness(registry)
    return jsonify({"success": True, "calibration": summary})


@modular_api.route("/api/patients/<nss>/state-timeline", methods=["GET"])
def patient_state_timeline(nss: str) -> tuple:
    from tracking_db import get_patient_state_timeline

    timeline = get_patient_state_timeline(nss)
    if timeline is None:
        return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
    return jsonify({"success": True, "state_timeline": humanize_state_timeline(timeline)})


@modular_api.route("/api/patients/<nss>/recompute-care-plan", methods=["POST"])
def recompute_patient_care_plan_route(nss: str) -> tuple:
    from tracking_db import get_patient_state_timeline, recompute_patient_care_plan

    success, result = recompute_patient_care_plan(nss)
    if not success:
        status = 404 if "no encontrado" in str(result).lower() else 400
        return jsonify({"success": False, "error": str(result)}), status
    assessment = humanize_assessment(result)
    timeline = get_patient_state_timeline(nss) or []
    return jsonify(
        {
            "success": True,
            "assessment": assessment,
            "state_timeline": humanize_state_timeline(timeline),
            "care_overlays": humanize_care_overlays(
                assessment.get("display_result", {}).get("care_overlays", [])
            ),
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# ══  COPILOTO CLÍNICO — Scheduling, Alertas, Response Assessment
# ══════════════════════════════════════════════════════════════════════════════


@modular_api.route("/api/patients/<int:patient_id>/schedule", methods=["GET"])
def patient_schedule(patient_id: int) -> tuple:
    """Genera el calendario de seguimiento programado para el paciente."""
    import tracking_db
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        reconciliation = build_reconciled_state(patient, patient.get("latest_assessment"))
        state = reconciliation.get("reconciled_state") or "diagnostic_workup"
        track = request.args.get("track") or reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"

        horizon = int(request.args.get("horizon_months", 12))
        schedule_bundle = tracking_db.sync_scheduled_events(
            patient,
            state=state,
            management_track=track,
            horizon_months=horizon,
        )

        return jsonify({
            "success": True,
            "state": schedule_bundle.get("state", state),
            "management_track": schedule_bundle.get("management_track", track),
            "reconciled_state": reconciliation.get("reconciled_state", state),
            "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
            "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
            "anchor_date": schedule_bundle.get("anchor_date", ""),
            "anchor_source": schedule_bundle.get("anchor_source", ""),
            "protocol_trace": schedule_bundle.get("protocol_trace", {}),
            "protocol_label": schedule_bundle.get("protocol_label", ""),
            "schedule": schedule_bundle.get("schedule", []),
            "scheduled_items": schedule_bundle.get("scheduled_items", schedule_bundle.get("schedule", [])),
            "active_schedule": schedule_bundle.get("active_schedule", schedule_bundle.get("schedule", [])),
            "archived_schedule": schedule_bundle.get("archived_schedule", []),
            "scheduled_encounters": schedule_bundle.get("scheduled_encounters", []),
            "encounters": schedule_bundle.get("encounters", []),
            "next_encounter": schedule_bundle.get("next_encounter", {}),
            "master_followup_plan": schedule_bundle.get("master_followup_plan", {}),
            "master_followup_summary": schedule_bundle.get("master_followup_summary", {}),
            "plan_key": (schedule_bundle.get("master_followup_plan") or {}).get("plan_key", ""),
            "guideline_basis": (schedule_bundle.get("master_followup_plan") or {}).get("guideline_basis", []),
            "plan_version": (schedule_bundle.get("master_followup_plan") or {}).get("plan_version", ""),
            "plan_status": (schedule_bundle.get("master_followup_plan") or {}).get("plan_status", "active"),
            "calendar_horizon_months": (schedule_bundle.get("master_followup_plan") or {}).get("calendar_horizon_months", horizon),
            "timeline": (schedule_bundle.get("master_followup_plan") or {}).get("timeline", []),
            "schedule_anchor_strength": schedule_bundle.get("schedule_anchor_strength", "strong"),
            "prognostic_rationale": schedule_bundle.get("prognostic_rationale", (schedule_bundle.get("master_followup_plan") or {}).get("prognostic_rationale", [])),
            "cadence_adjusted_by": schedule_bundle.get("cadence_adjusted_by", (schedule_bundle.get("master_followup_plan") or {}).get("cadence_adjusted_by", [])),
            "backbone_alignment": schedule_bundle.get("backbone_alignment", (schedule_bundle.get("master_followup_plan") or {}).get("backbone_alignment", {})),
            "milestone_plan": schedule_bundle.get("milestone_plan", []),
            "outcome_anchor": schedule_bundle.get("outcome_anchor", {}),
            "pending_adjudication_tasks": schedule_bundle.get("pending_adjudication_tasks", []),
            "outcome_events_summary": schedule_bundle.get("outcome_events_summary", {}),
            "pending_adjudications": schedule_bundle.get("pending_adjudications", []),
            "current_response_state": schedule_bundle.get("current_response_state", {}),
            "current_course_status": schedule_bundle.get("current_course_status", ""),
            "last_adjudicated_event": schedule_bundle.get("last_adjudicated_event", {}),
            "trial_comparable_endpoints": schedule_bundle.get("trial_comparable_endpoints", []),
            "current_trial_comparable_profile": schedule_bundle.get("current_trial_comparable_profile", {}),
            "total_events": len(schedule_bundle.get("scheduled_items", schedule_bundle.get("schedule", []))),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/outcomes", methods=["GET"])
def patient_outcomes(patient_id: int) -> tuple:
    import tracking_db

    try:
        if not tracking_db.patient_exists(patient_id):
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        payload = tracking_db.get_patient_outcomes(patient_id)
        if payload is None:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohorts/benchmarks", methods=["GET"])
def cohort_benchmarks() -> tuple:
    import tracking_db

    try:
        payload = tracking_db.get_cohort_benchmarks()
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/risk-tools", methods=["GET"])
def patient_risk_tools(patient_id: int) -> tuple:
    import tracking_db
    from prostanet.domains.patient_tracking.disease_course_outcomes import build_disease_course_bundle
    from prostanet.domains.patient_tracking.prognostic_impact import build_prognostic_impact_bundle
    from prostanet.domains.patient_tracking.risk_tools import build_risk_tools_panel
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state
    from prostanet.shared.presentation_text import humanize_assessment

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        raw_assessment = patient.get("latest_assessment") or {}
        assessment = humanize_assessment(raw_assessment) if raw_assessment else {}
        reconciliation = build_reconciled_state(patient, raw_assessment)
        state = reconciliation.get("reconciled_state") or raw_assessment.get("state") or (patient.get("prior_history") or {}).get("current_state") or ""
        bundle = build_risk_tools_panel(
            patient=patient,
            state=state,
            raw_assessment=raw_assessment,
            display_assessment=assessment,
        )
        current_trial_profile = dict((patient.get("latest_trial_benchmark_snapshot") or {}).get("current_trial_profile") or {})
        if not current_trial_profile:
            current_trial_profile = build_disease_course_bundle(
                patient,
                state=state,
                management_track=reconciliation.get("reconciled_management_track") or "",
                latest_assessment=raw_assessment,
            ).get("current_trial_comparable_profile", {})
        prognostic_bundle = build_prognostic_impact_bundle(
            patient=patient,
            state=state,
            management_track=reconciliation.get("reconciled_management_track") or "",
            raw_assessment=raw_assessment,
            risk_tools_bundle=bundle,
            current_trial_profile=current_trial_profile,
        )
        return jsonify({"success": True, **bundle, **prognostic_bundle})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/schedule/overdue", methods=["GET"])
def patient_overdue(patient_id: int) -> tuple:
    """Detecta eventos de seguimiento vencidos."""
    import tracking_db
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        reconciliation = build_reconciled_state(patient, patient.get("latest_assessment"))
        state = reconciliation.get("reconciled_state") or "diagnostic_workup"
        track = reconciliation.get("reconciled_management_track") or "diagnostic_surveillance"
        schedule_bundle = tracking_db.sync_scheduled_events(
            patient,
            state=state,
            management_track=track,
            horizon_months=int(request.args.get("horizon_months", 12)),
        )
        overdue = [item for item in (schedule_bundle.get("active_schedule") or schedule_bundle.get("schedule") or []) if item.get("status") == "overdue" and not item.get("completed")]

        return jsonify({
            "success": True,
            "reconciled_state": reconciliation.get("reconciled_state", state),
            "state_conflict_flag": reconciliation.get("state_conflict_flag", False),
            "state_conflict_reason": reconciliation.get("state_conflict_reason", ""),
            "anchor_date": schedule_bundle.get("anchor_date", ""),
            "anchor_source": schedule_bundle.get("anchor_source", ""),
            "protocol_trace": schedule_bundle.get("protocol_trace", {}),
            "schedule_anchor_strength": schedule_bundle.get("schedule_anchor_strength", "strong"),
            "overdue_alerts": overdue,
            "overdue_count": len(overdue),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/clinical-alerts", methods=["GET"])
def patient_clinical_alerts(patient_id: int) -> tuple:
    """Retorna la salida canónica de alertas del copiloto para este paciente."""
    import tracking_db

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        alerts = bundle.get("copilot_alerts", [])
        return jsonify({
            "success": True,
            "alerts": alerts,
            "critical_count": sum(1 for a in alerts if a.get("severity") == "critical"),
            "warning_count": sum(1 for a in alerts if a.get("severity") == "warning"),
            "alert_summary": bundle.get("alert_summary", {}),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/response-assessment", methods=["POST"])
def patient_response_assessment(patient_id: int) -> tuple:
    """Evalúa respuesta terapéutica (RECIST 1.1, PCWG3, PSA)."""
    import tracking_db
    from prostanet.domains.patient_tracking.response_assessment import ResponseAssessmentService

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        soft_tissue = None
        bone = None
        psa = None

        # Soft tissue assessment (RECIST 1.1)
        st_data = data.get("soft_tissue")
        if st_data:
            current_sum = safe_float(st_data.get("current_sum_mm"), None)
            baseline_sum = safe_float(st_data.get("baseline_sum_mm"), None)
            if current_sum is None or baseline_sum is None:
                raise ValueError("Para evaluar tejidos blandos se requieren 'current_sum_mm' y 'baseline_sum_mm'.")
            soft_tissue = ResponseAssessmentService.assess_soft_tissue(
                current_sum_mm=current_sum,
                baseline_sum_mm=baseline_sum,
                nadir_sum_mm=safe_float(st_data.get("nadir_sum_mm"), None),
                new_lesions=_validated_bool(st_data.get("new_lesions"), "soft_tissue.new_lesions", default=False),
                non_target_progression=_validated_bool(st_data.get("non_target_progression"), "soft_tissue.non_target_progression", default=False),
            )

        # Bone assessment (PCWG3)
        bone_data = data.get("bone")
        if bone_data:
            lesion_count = safe_int(bone_data.get("new_lesion_count"), None)
            if lesion_count is None:
                raise ValueError("Para evaluar respuesta ósea se requiere 'new_lesion_count'.")
            bone = ResponseAssessmentService.assess_bone(
                new_lesion_count=lesion_count,
                prior_scan_new_lesions=safe_int(bone_data.get("prior_scan_new_lesions"), 0),
                is_first_assessment=_validated_bool(bone_data.get("is_first_assessment"), "bone.is_first_assessment", default=False),
            )

        # PSA response
        psa_data = data.get("psa")
        if psa_data:
            baseline_psa = safe_float(psa_data.get("baseline_psa"), None)
            current_psa = safe_float(psa_data.get("current_psa"), None)
            if baseline_psa is None or current_psa is None:
                raise ValueError("Para evaluar respuesta por PSA se requieren 'baseline_psa' y 'current_psa'.")
            psa = ResponseAssessmentService.assess_psa(
                baseline_psa=baseline_psa,
                current_psa=current_psa,
                nadir_psa=safe_float(psa_data.get("nadir_psa"), None),
                confirmed_at_4_weeks=_validated_bool(psa_data.get("confirmed"), "psa.confirmed", default=False),
            )

        if not any((soft_tissue, bone, psa)):
            raise ValueError("Se requiere al menos un bloque válido: 'soft_tissue', 'bone' o 'psa'.")

        # Composite
        composite = ResponseAssessmentService.composite_response(soft_tissue, bone, psa)

        # Persist
        try:
            conn = tracking_db._connect()
            c = conn.cursor()
            c.execute(
                """INSERT INTO response_assessments
                   (patient_id, assessment_date, recist_category, sum_target_diameters,
                    baseline_sum_diameters, nadir_sum_diameters, pcwg3_bone_status,
                    new_bone_lesion_count, psa_response_category, psa_baseline,
                    psa_current, psa_nadir, psa_change_from_baseline_pct,
                    overall_response, clinical_benefit, details_json)
                   VALUES (?,date('now'),?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    patient_id,
                    soft_tissue.category if soft_tissue else None,
                    soft_tissue.sum_target_diameters_mm if soft_tissue else None,
                    soft_tissue.baseline_sum_mm if soft_tissue else None,
                    soft_tissue.nadir_sum_mm if soft_tissue else None,
                    bone.status if bone else None,
                    bone.new_lesion_count if bone else None,
                    psa.category if psa else None,
                    psa.baseline_psa if psa else None,
                    psa.current_psa if psa else None,
                    psa.nadir_psa if psa else None,
                    psa.change_from_baseline_pct if psa else None,
                    composite.overall,
                    1 if composite.clinical_benefit else 0,
                    __import__("json").dumps(composite.to_dict(), ensure_ascii=False),
                ),
            )
            assessment_id = c.lastrowid
            conn.commit()
            conn.close()
            event_id = tracking_db.record_patient_event(
                patient_id,
                event_type="study_resulted",
                event_date=None,
                state_context=(patient.get("latest_assessment") or {}).get("state", ""),
                management_track=(patient.get("latest_signal_snapshot") or {}).get("management_track", ""),
                source_type="response_assessment",
                source_record_id=assessment_id,
                payload={"response": composite.to_dict()},
                mcode_focus={"resource": "response_assessment"},
            )
            tracking_db.refresh_longitudinal_intelligence(patient_id, event_id=event_id, force_recompute=False)
        except Exception as db_err:
            import logging
            logging.getLogger(__name__).warning("Error persisting response assessment: %s", db_err)

        # Enrich with survival context when PD detected
        survival_context = {}
        try:
            survival_context = ResponseAssessmentService.evaluate_with_survival_context(patient, composite)
        except Exception:
            pass

        return jsonify({
            "success": True,
            "response": composite.to_dict(),
            "survival_context": survival_context,
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/comorbidity-scores", methods=["POST"])
def patient_comorbidity_scores(patient_id: int) -> tuple:
    """Calcula CCI, G8 y PHI para el paciente."""
    import tracking_db
    from clinical_scores import charlson_comorbidity_index, g8_geriatric_assessment, prostate_health_index

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        # Merge patient data with incoming data
        score_data = {}
        score_data.update(patient.get("identity", {}))
        score_data.update(patient.get("baseline", {}) or {})
        score_data.update(data)

        results = {}
        results["charlson"] = charlson_comorbidity_index(score_data)
        results["g8"] = g8_geriatric_assessment(score_data)

        # PHI only if biomarkers available
        if score_data.get("free_psa") and score_data.get("p2psa"):
            results["phi"] = prostate_health_index(score_data)

        # Persist CCI if calculated
        try:
            conn = tracking_db._connect()
            c = conn.cursor()
            c.execute(
                "UPDATE patient_demographics SET charlson_score=?, charlson_details_json=?, g8_score=? WHERE patient_id=?",
                (
                    results["charlson"]["age_adjusted_score"],
                    __import__("json").dumps(results["charlson"]),
                    results["g8"]["score"],
                    patient_id,
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        return jsonify({"success": True, "scores": results})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/tumor-board", methods=["GET"])
def patient_tumor_board(patient_id: int) -> tuple:
    """Genera presentación estructurada para tumor board / comité multidisciplinario."""
    import tracking_db
    from prostanet.domains.reporting.tumor_board import TumorBoardPresentation

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        presentation = TumorBoardPresentation.generate(patient)
        return jsonify({"success": True, "tumor_board": presentation})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/survivorship-plan", methods=["GET"])
def patient_survivorship_plan(patient_id: int) -> tuple:
    """Genera plan de cuidado de sobrevivencia personalizado."""
    import tracking_db
    from prostanet.domains.patient_tracking.survivorship import SurvivorshipCarePlan
    from prostanet.domains.patient_tracking.followup_agenda import infer_management_track

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        state = (patient.get("latest_assessment") or {}).get("state") or "diagnostic_workup"
        track = infer_management_track(patient, state, patient.get("latest_assessment"))
        plan = SurvivorshipCarePlan.generate(patient, state, track)
        return jsonify({"success": True, "survivorship_plan": plan})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/structured-biopsy", methods=["POST"])
def patient_structured_biopsy(patient_id: int) -> tuple:
    """Parsea y analiza biopsia estructurada con mapa sextante y concordancia MRI."""
    import tracking_db
    from prostanet.domains.patient_tracking.structured_biopsy import StructuredBiopsyService

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        parsed = StructuredBiopsyService.parse_structured_biopsy(data)
        summary = StructuredBiopsyService.build_biopsy_summary_for_profile(parsed)

        # Check for upgrade vs previous biopsy
        biopsies = patient.get("biopsies") or []
        previous = biopsies[-1] if biopsies and isinstance(biopsies[-1], dict) else None
        upgrade = StructuredBiopsyService.evaluate_upgrade_from_previous(parsed, previous)
        concordance = StructuredBiopsyService.check_mri_concordance(parsed)
        alerts = StructuredBiopsyService.evaluate_biopsy_alerts(patient_id, parsed, previous)

        return jsonify({
            "success": True,
            "biopsy_summary": summary,
            "upgrade_assessment": upgrade,
            "mri_concordance": concordance,
            "alerts": [a.to_dict() for a in alerts],
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/active-surveillance", methods=["GET"])
def patient_active_surveillance(patient_id: int) -> tuple:
    """Evalúa elegibilidad AS multi-protocolo, construye protocolo y agenda."""
    import tracking_db
    from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        assessment = patient.get("latest_assessment") or {}
        reconciliation = build_reconciled_state(patient, assessment)
        state = reconciliation.get("reconciled_state", "")

        as_data = {}
        as_data.update(patient.get("identity", {}))
        as_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            as_data.update(patient["prior_history"])
        followups = patient.get("follow_ups", [])
        if followups:
            as_data.update(followups[-1])

        eligibility = ActiveSurveillanceService.check_eligibility(as_data, state)
        protocol = ActiveSurveillanceService.build_as_protocol(as_data, state)
        summary = ActiveSurveillanceService.build_as_summary_for_profile(protocol)
        alerts = ActiveSurveillanceService.evaluate_as_alerts(patient_id, protocol)

        return jsonify({
            "success": True,
            "eligibility": [e.__dict__ if hasattr(e, "__dict__") else e for e in eligibility],
            "protocol_summary": summary,
            "alerts": _serialize_alerts(alerts),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/radiotherapy-detail", methods=["GET"])
def patient_radiotherapy_detail(patient_id: int) -> tuple:
    """Historial detallado de radioterapia con validación de fraccionamiento y toxicidad."""
    import tracking_db
    from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        rt_summary = RadiotherapyDetailService.build_rt_history(patient)
        profile_summary = RadiotherapyDetailService.build_rt_summary_for_profile(rt_summary)
        alerts = RadiotherapyDetailService.evaluate_rt_alerts(patient_id, rt_summary)

        return jsonify({
            "success": True,
            "rt_summary": profile_summary,
            "alerts": _serialize_alerts(alerts),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/skeletal-events", methods=["GET"])
def patient_skeletal_events(patient_id: int) -> tuple:
    """Perfil de eventos esqueléticos, riesgo SRE y cumplimiento BMA."""
    import tracking_db
    from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        assessment = patient.get("latest_assessment") or {}
        reconciliation = build_reconciled_state(patient, assessment)
        state = reconciliation.get("reconciled_state", "")

        sre_data = {}
        sre_data.update(patient.get("identity", {}))
        sre_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            sre_data.update(patient["prior_history"])
        followups = patient.get("follow_ups", [])
        if followups:
            sre_data.update(followups[-1])
        sre_data["skeletal_events"] = patient.get("skeletal_events") or patient.get("sre_events") or []

        profile = SkeletalEventService.build_sre_profile(sre_data, state)
        summary = SkeletalEventService.build_sre_summary_for_profile(profile)
        alerts = SkeletalEventService.evaluate_sre_alerts(patient_id, profile)

        return jsonify({
            "success": True,
            "sre_profile": summary,
            "alerts": _serialize_alerts(alerts),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/survival-endpoints", methods=["GET"])
def patient_survival_endpoints(patient_id: int) -> tuple:
    """Calcula endpoints de supervivencia (OS, rPFS, MFS, BCR-FS, TTPP, TTSRE, etc.)."""
    import tracking_db
    from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
    from prostanet.domains.patient_tracking.reconciled_state import build_reconciled_state

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        assessment = patient.get("latest_assessment") or {}
        reconciliation = build_reconciled_state(patient, assessment)
        state = reconciliation.get("reconciled_state", "")

        survival_status = SurvivalEndpointService.compute_endpoints(patient, state)
        summary = SurvivalEndpointService.build_survival_summary_for_profile(survival_status)
        alerts = SurvivalEndpointService.evaluate_survival_alerts(patient_id, survival_status)

        return jsonify({
            "success": True,
            "survival_status": summary,
            "alerts": _serialize_alerts(alerts),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/psa-forecast", methods=["GET"])
def patient_psa_forecast(patient_id: int) -> tuple:
    """Devuelve forecast prospectivo de PSA para la línea terapéutica actual."""
    import tracking_db

    try:
        if not tracking_db.patient_exists(patient_id):
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        return jsonify(
            {
                "success": True,
                "psa_forecast": bundle.get("psa_forecast", {}),
                "forecast_reliability": bundle.get("forecast_reliability", {}),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/live-benchmark", methods=["GET"])
def patient_live_benchmark(patient_id: int) -> tuple:
    """Devuelve benchmarking vivo del paciente contra cohorte similar y referencia publicada."""
    import tracking_db

    try:
        if not tracking_db.patient_exists(patient_id):
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404
        bundle = tracking_db.refresh_longitudinal_intelligence(patient_id, force_recompute=False)
        return jsonify(
            {
                "success": True,
                "live_benchmark": bundle.get("live_benchmark", {}),
                "benchmark_reliability": bundle.get("benchmark_reliability", {}),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohorts/survival-curves", methods=["GET"])
def cohort_survival_curves() -> tuple:
    """Devuelve curva Kaplan-Meier y dataset tiempo-evento para un endpoint."""
    import tracking_db
    from prostanet.domains.patient_tracking.survival_analysis import build_survival_curve_payload

    try:
        endpoint_type = str(request.args.get("endpoint_type") or request.args.get("endpoint") or "OS").strip() or "OS"
        state_filter = str(request.args.get("state") or "").strip() or None
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        patient_ids = [int(row["id"]) for row in cursor.fetchall()]
        conn.close()
        records = [tracking_db.get_patient_full_record(patient_id) for patient_id in patient_ids]
        records = [record for record in records if record]
        payload = build_survival_curve_payload(records, endpoint_type, state_filter=state_filter)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohorts/survival-analysis", methods=["GET"])
def cohort_survival_analysis() -> tuple:
    """Devuelve análisis Cox PH sobre el endpoint solicitado."""
    import tracking_db
    from prostanet.domains.patient_tracking.survival_analysis import build_cox_analysis_payload
    from prostanet.domains.patient_tracking.psa_forecast import build_psa_forecast_backtest

    try:
        endpoint_type = str(request.args.get("endpoint_type") or request.args.get("endpoint") or "OS").strip() or "OS"
        state_filter = str(request.args.get("state") or "").strip() or None
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        patient_ids = [int(row["id"]) for row in cursor.fetchall()]
        conn.close()
        records = [tracking_db.get_patient_full_record(patient_id) for patient_id in patient_ids]
        records = [record for record in records if record]
        if endpoint_type.upper() == "PSA_FORECAST":
            payload = build_psa_forecast_backtest(records)
        else:
            payload = build_cox_analysis_payload(records, endpoint_type, state_filter=state_filter)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/cohorts/domain-completeness", methods=["GET"])
def cohort_domain_completeness() -> tuple:
    """Resume completitud operativa por dominio longitudinal canónico."""
    import tracking_db
    from prostanet.domains.patient_tracking.survival_analysis import build_domain_completeness_payload

    try:
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        patient_ids = [int(row["id"]) for row in cursor.fetchall()]
        conn.close()
        records = [tracking_db.get_patient_full_record(patient_id) for patient_id in patient_ids]
        records = [record for record in records if record]
        payload = build_domain_completeness_payload(records)
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/versions/current", methods=["GET"])
def research_current_consent_version() -> tuple:
    try:
        return jsonify({"success": True, **get_current_consent_payload()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/draft", methods=["POST"])
def research_create_consent_draft() -> tuple:
    try:
        data = _parse_json()
        payload = tracking_service.canonicalize_payload(dict(data.get("payload") or data))
        assessment_id = payload.get("assessment_id")
        if assessment_id not in (None, ""):
            assessment = assessment_service.get_draft(int(float(assessment_id)))
            if not assessment:
                raise ValueError("Evaluación clínica no encontrada.")
            payload = tracking_service.merge_assessment_payload(assessment, payload)
        payload["nss"] = str(payload.get("nss", "")).strip()
        payload["full_name"] = str(payload.get("full_name", "")).strip()
        if not payload["nss"] or not payload["full_name"]:
            raise ValueError("Se requieren NSS y nombre completo para iniciar el consentimiento.")
        source_context = str(data.get("source_context") or "wizard")
        return jsonify({"success": True, **create_consent_draft(payload, source_context=source_context)})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/draft/<int:draft_id>", methods=["GET"])
def research_get_consent_draft(draft_id: int) -> tuple:
    try:
        draft = get_consent_draft_payload(draft_id)
        if not draft:
            return jsonify({"success": False, "error": "Borrador no encontrado."}), 404
        return jsonify({"success": True, "draft": draft})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/draft/<int:draft_id>/sign", methods=["POST"])
def research_sign_consent_draft(draft_id: int) -> tuple:
    try:
        payload = _parse_json()
        result = sign_consent_draft_payload(draft_id, payload)
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/consent/draft/<int:draft_id>/finalize", methods=["POST"])
def research_finalize_consent_draft(draft_id: int) -> tuple:
    try:
        result = finalize_consent_draft_payload(draft_id)
        return jsonify({"success": True, **result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/cohorts", methods=["GET", "POST"])
def research_cohorts() -> tuple:
    try:
        if request.method == "GET":
            return jsonify({"success": True, "cohorts": list_dynamic_cohort_payload()})
        data = _parse_json()
        title = str(data.get("title", "")).strip()
        filters = list(data.get("filters") or [])
        if not title or not filters:
            raise ValueError("Se requieren título y filtros para crear una cohorte.")
        cohort = create_dynamic_cohort(
            title=title,
            filters=filters,
            description=str(data.get("description") or "").strip(),
        )
        return jsonify({"success": True, "cohort": cohort})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/cohorts/<int:cohort_id>", methods=["GET"])
def research_cohort_detail(cohort_id: int) -> tuple:
    try:
        cohort = get_dynamic_cohort_payload(cohort_id)
        if not cohort:
            return jsonify({"success": False, "error": "Cohorte no encontrada."}), 404
        return jsonify({"success": True, "cohort": cohort})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/survival-curves", methods=["GET"])
def research_survival_curves() -> tuple:
    try:
        endpoint = request.args.get("endpoint", "OS")
        cohort_id = request.args.get("cohort_id")
        stratify_by = request.args.get("stratify_by", "reconciled_state")
        payload = build_survival_registry_payload(
            endpoint=endpoint,
            cohort_id=int(cohort_id) if cohort_id not in (None, "") else None,
            stratify_by=stratify_by,
        )
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/survival-analysis/cox", methods=["GET"])
def research_survival_cox() -> tuple:
    try:
        endpoint = request.args.get("endpoint", "OS")
        cohort_id = request.args.get("cohort_id")
        covariates = [item for item in request.args.getlist("covariate") if item]
        payload = build_cox_payload(
            endpoint=endpoint,
            cohort_id=int(cohort_id) if cohort_id not in (None, "") else None,
            covariates=covariates or None,
        )
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/survival-analysis/logistic", methods=["GET"])
def research_logistic() -> tuple:
    try:
        outcome = request.args.get("outcome", "molecular_report_available")
        cohort_id = request.args.get("cohort_id")
        covariates = [item for item in request.args.getlist("covariate") if item]
        payload = build_logistic_payload(
            outcome=outcome,
            cohort_id=int(cohort_id) if cohort_id not in (None, "") else None,
            covariates=covariates or None,
        )
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/propensity", methods=["POST"])
def research_propensity() -> tuple:
    try:
        data = _parse_json()
        payload = run_propensity_analysis(
            cohort_id=int(data.get("cohort_id")),
            treatment_field=str(data.get("treatment_field")),
            treatment_value=str(data.get("treatment_value")),
            control_value=str(data.get("control_value")),
            outcome_field=str(data.get("outcome_field") or "survival_os_event"),
            covariates=list(data.get("covariates") or []),
            caliper=float(data.get("caliper") or 0.2),
        )
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/outcomes/operational", methods=["GET"])
def research_operational_outcomes() -> tuple:
    try:
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        records = [tracking_db.get_patient_full_record(int(row["id"])) for row in cursor.fetchall()]
        conn.close()
        payload = build_operational_outcomes_payload([record for record in records if record])
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/quality-indicators", methods=["GET"])
def research_quality_indicators() -> tuple:
    try:
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        records = [tracking_db.get_patient_full_record(int(row["id"])) for row in cursor.fetchall()]
        conn.close()
        payload = build_quality_indicator_payload([record for record in records if record])
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/benchmarks", methods=["GET"])
def research_benchmarks() -> tuple:
    try:
        conn = tracking_db._connect()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM patient_identity ORDER BY id ASC")
        records = [tracking_db.get_patient_full_record(int(row["id"])) for row in cursor.fetchall()]
        conn.close()
        payload = build_institutional_benchmark_payload([record for record in records if record])
        return jsonify({"success": True, **payload})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/export/csv", methods=["GET"])
def research_export_csv() -> tuple:
    try:
        cohort_id = request.args.get("cohort_id")
        payload = build_csv_export_payload(cohort_id=int(cohort_id) if cohort_id not in (None, "") else None)
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/export/redcap", methods=["GET"])
def research_export_redcap() -> tuple:
    try:
        cohort_id = request.args.get("cohort_id")
        payload = build_redcap_export_payload(cohort_id=int(cohort_id) if cohort_id not in (None, "") else None)
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/research/export/cdisc", methods=["GET"])
def research_export_cdisc() -> tuple:
    try:
        cohort_id = request.args.get("cohort_id")
        payload = build_cdisc_mapping_payload(cohort_id=int(cohort_id) if cohort_id not in (None, "") else None)
        return jsonify({"success": True, **payload})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/adt-side-effects", methods=["POST"])
def patient_adt_side_effects(patient_id: int) -> tuple:
    """Evaluación de efectos secundarios de ADT (CV, metabólico, óseo)."""
    import tracking_db
    from prostanet.domains.patient_tracking.adt_side_effects import ADTSideEffectService

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        adt_data = {}
        adt_data.update(patient.get("identity", {}))
        adt_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            adt_data.update(patient["prior_history"])
        followups = patient.get("follow_ups", [])
        if followups:
            adt_data.update(followups[-1])
        adt_data.update(data)

        profile = ADTSideEffectService.full_assessment(adt_data)
        return jsonify({"success": True, "adt_side_effects": profile.to_dict()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/palliative-assessment", methods=["POST"])
def patient_palliative_assessment(patient_id: int) -> tuple:
    """Evaluación paliativa integral."""
    import tracking_db
    from prostanet.domains.palliative_pathway.service import PalliativePathwayService

    try:
        data = _parse_json()
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        pall_data = {}
        pall_data.update(patient.get("identity", {}))
        pall_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            pall_data.update(patient["prior_history"])
        followups = patient.get("follow_ups", [])
        if followups:
            pall_data.update(followups[-1])
        pall_data.update(data)

        assessment = PalliativePathwayService.full_assessment(pall_data)
        return jsonify({"success": True, "palliative_assessment": assessment.to_dict()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/decision-aids/compare", methods=["POST"])
def decision_aids_compare() -> tuple:
    """Genera comparación de opciones de tratamiento para decisión compartida."""
    from prostanet.domains.reporting.decision_aids import DecisionAidService

    try:
        data = _parse_json()
        options = data.get("options", [])
        if not options:
            return jsonify({"success": False, "error": "Se requiere lista de opciones de tratamiento."}), 400

        comparison = DecisionAidService.generate_comparison(
            options=options,
            risk_group=data.get("risk_group", ""),
            patient_priorities=data.get("patient_priorities"),
        )
        return jsonify({"success": True, "decision_aid": comparison})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/decision-aids/patient-summary", methods=["POST"])
def decision_aids_patient_summary() -> tuple:
    """Genera resumen en lenguaje para paciente sobre un tratamiento."""
    from prostanet.domains.reporting.decision_aids import DecisionAidService

    try:
        data = _parse_json()
        treatment = data.get("treatment", "")
        if not treatment:
            return jsonify({"success": False, "error": "Se requiere el tratamiento."}), 400

        summary = DecisionAidService.generate_patient_summary(
            treatment_key=treatment,
            patient_name=data.get("patient_name", "usted"),
        )
        return jsonify({"success": True, "patient_summary": summary})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/diagnostic-calculators", methods=["POST"])
def diagnostic_calculators() -> tuple:
    """Ejecuta calculadoras diagnósticas avanzadas (4Kscore, ERSPC, PHI)."""
    from clinical_scores import four_k_score, erspc_risk_calculator, prostate_health_index

    try:
        data = _parse_json()
        results = {}

        if data.get("psa") and data.get("free_psa"):
            results["four_k_score"] = four_k_score(data)

            if data.get("p2psa"):
                results["phi"] = prostate_health_index(data)

        if data.get("psa"):
            results["erspc"] = erspc_risk_calculator(data)

        if not results:
            return jsonify({"success": False, "error": "Se requiere al menos PSA para ejecutar calculadoras."}), 400

        return jsonify({"success": True, "calculators": results})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/response-visualization", methods=["POST"])
def response_visualization(patient_id: int) -> tuple:
    """Genera datos de visualización terapéutica con swimmer legacy y timeline integrado en PSA."""
    from prostanet.domains.reporting.response_visualization import ResponseVisualizationService
    from tracking_db import get_full_record

    try:
        record = get_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        treatments = record.get("treatments") or []
        baseline_psa = (record.get("baseline") or {}).get("baseline_psa")
        diagnosis_date = (record.get("identity") or {}).get("diagnosis_date")
        lesion_data = record.get("lesion_tracking") or []
        psa_series = record.get("psa_series") or []

        bundle = ResponseVisualizationService.build_visualization_bundle(
            treatments=treatments,
            lesions=lesion_data,
            psa_series=psa_series,
            baseline_psa=float(baseline_psa) if baseline_psa else None,
            diagnosis_date=diagnosis_date,
        )

        return jsonify({"success": True, "visualization": bundle.to_dict()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
