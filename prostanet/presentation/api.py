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
