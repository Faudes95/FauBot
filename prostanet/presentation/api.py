from __future__ import annotations

from flask import Blueprint, jsonify, request

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.clinical_assessments.service import ClinicalAssessmentService
from prostanet.domains.clinical_assessments.scenario_harness import run_scenario_harness
from prostanet.domains.patient_tracking.service import PatientTrackingService
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
    from prostanet.domains.patient_tracking.schedule_engine import generate_schedule
    from prostanet.domains.patient_tracking.followup_agenda import infer_management_track

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        state = (patient.get("latest_assessment") or {}).get("state") or (patient.get("prior_history") or {}).get("current_state") or "diagnostic_workup"
        track = request.args.get("track") or infer_management_track(patient, state, patient.get("latest_assessment"))

        identity = patient.get("identity", {})
        start_date = identity.get("diagnosis_date") or identity.get("created_at", "")
        horizon = int(request.args.get("horizon_months", 12))

        schedule = generate_schedule(
            patient_id=patient_id,
            management_track=track,
            treatment_start_date=start_date,
            horizon_months=horizon,
        )

        return jsonify({
            "success": True,
            "state": state,
            "management_track": track,
            "schedule": [ev.to_dict() for ev in schedule],
            "total_events": len(schedule),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/schedule/overdue", methods=["GET"])
def patient_overdue(patient_id: int) -> tuple:
    """Detecta eventos de seguimiento vencidos."""
    import tracking_db
    from prostanet.domains.patient_tracking.schedule_engine import check_overdue
    from prostanet.domains.patient_tracking.followup_agenda import infer_management_track

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        state = (patient.get("latest_assessment") or {}).get("state") or "diagnostic_workup"
        track = infer_management_track(patient, state, patient.get("latest_assessment"))

        identity = patient.get("identity", {})
        start_date = identity.get("diagnosis_date") or identity.get("created_at", "")

        overdue = check_overdue(
            patient_id=patient_id,
            management_track=track,
            treatment_start_date=start_date,
        )

        return jsonify({
            "success": True,
            "overdue_alerts": [a.to_dict() for a in overdue],
            "overdue_count": len(overdue),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@modular_api.route("/api/patients/<int:patient_id>/clinical-alerts", methods=["GET"])
def patient_clinical_alerts(patient_id: int) -> tuple:
    """Ejecuta el motor de alertas clínicas y retorna alertas activas."""
    import tracking_db
    from prostanet.domains.patient_tracking.alert_engine import ClinicalAlertEngine

    try:
        patient = tracking_db.get_patient_full_record(patient_id)
        if not patient:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        # Build consolidated patient dict for alert engine
        alert_data = {}
        alert_data.update(patient.get("identity", {}))
        alert_data.update(patient.get("baseline", {}) or {})
        if patient.get("prior_history"):
            alert_data.update(patient["prior_history"])

        # Include latest followup data
        followups = patient.get("follow_ups", [])
        if followups:
            last = followups[-1]
            alert_data["psa"] = last.get("psa_current")
            alert_data["hemoglobin"] = last.get("hemoglobin_current")
            alert_data["ecog"] = last.get("ecog_current")
            alert_data["testosterone"] = last.get("testosterone_current")
            alert_data["alp"] = last.get("alp_current")
            if len(followups) >= 2:
                alert_data["ecog_previous"] = followups[-2].get("ecog_current")

        # Include assessment state info
        assessment = patient.get("latest_assessment")
        if assessment:
            state = assessment.get("state", "")
            from prostanet.domains.patient_tracking.followup_agenda import infer_management_track
            alert_data["management_track"] = infer_management_track(patient, state, assessment)

        alerts = ClinicalAlertEngine.run_all(patient_id, alert_data)

        return jsonify({
            "success": True,
            "alerts": [a.to_dict() for a in alerts],
            "critical_count": sum(1 for a in alerts if a.severity == "critical"),
            "warning_count": sum(1 for a in alerts if a.severity == "warning"),
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
            soft_tissue = ResponseAssessmentService.assess_soft_tissue(
                current_sum_mm=float(st_data.get("current_sum_mm", 0)),
                baseline_sum_mm=float(st_data.get("baseline_sum_mm", 0)),
                nadir_sum_mm=float(st_data.get("nadir_sum_mm", 0)) or None,
                new_lesions=bool(st_data.get("new_lesions", False)),
                non_target_progression=bool(st_data.get("non_target_progression", False)),
            )

        # Bone assessment (PCWG3)
        bone_data = data.get("bone")
        if bone_data:
            bone = ResponseAssessmentService.assess_bone(
                new_lesion_count=int(bone_data.get("new_lesion_count", 0)),
                prior_scan_new_lesions=int(bone_data.get("prior_scan_new_lesions", 0)),
                is_first_assessment=bool(bone_data.get("is_first_assessment", False)),
            )

        # PSA response
        psa_data = data.get("psa")
        if psa_data:
            psa = ResponseAssessmentService.assess_psa(
                baseline_psa=float(psa_data.get("baseline_psa", 0)),
                current_psa=float(psa_data.get("current_psa", 0)),
                nadir_psa=float(psa_data.get("nadir_psa", 0)) or None,
                confirmed_at_4_weeks=bool(psa_data.get("confirmed", False)),
            )

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
            conn.commit()
            conn.close()
        except Exception as db_err:
            import logging
            logging.getLogger(__name__).warning("Error persisting response assessment: %s", db_err)

        return jsonify({
            "success": True,
            "response": composite.to_dict(),
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
    """Genera datos de visualización de respuesta terapéutica (waterfall, spider, swimmer)."""
    from prostanet.domains.reporting.response_visualization import ResponseVisualizationService
    from tracking_db import get_full_record, get_db_connection

    try:
        record = get_full_record(patient_id)
        if not record:
            return jsonify({"success": False, "error": "Paciente no encontrado."}), 404

        treatments = record.get("treatments") or []
        baseline_psa = (record.get("baseline") or {}).get("baseline_psa")
        diagnosis_date = (record.get("identity") or {}).get("diagnosis_date")

        # Obtener lesiones con mediciones
        lesion_data = []
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id, lesion_id, anatomical_location, lesion_category FROM lesion_tracking WHERE patient_id = ?", (patient_id,))
            for tl in c.fetchall():
                c.execute(
                    "SELECT measurement_date, longest_diameter_mm, suvmax, volume_ml FROM lesion_measurements WHERE lesion_id = ? ORDER BY measurement_date ASC",
                    (tl["id"],)
                )
                measurements = [dict(m) for m in c.fetchall()]
                if measurements:
                    lesion_data.append({
                        "lesion_id": tl["lesion_id"] or str(tl["id"]),
                        "anatomical_location": tl["anatomical_location"],
                        "lesion_category": tl["lesion_category"],
                        "measurements": measurements,
                    })
            conn.close()
        except Exception:
            pass

        # Obtener serie PSA longitudinal
        psa_series = []
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute(
                "SELECT sample_date, value FROM biomarker_longitudinal WHERE patient_id = ? AND biomarker_type = 'PSA' ORDER BY sample_date ASC",
                (patient_id,),
            )
            psa_series = [dict(r) for r in c.fetchall()]
            conn.close()
        except Exception:
            pass

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
