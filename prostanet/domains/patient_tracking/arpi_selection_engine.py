from __future__ import annotations

from datetime import date, datetime
from typing import Any

from prostanet.domains.patient_tracking.arpi_benefit_matrix import benefit_profile_for_state
from prostanet.domains.patient_tracking.therapy_catalog import normalize_regimen_code, regimen_label


ARPI_ELIGIBLE_STATES = {
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "m0_crpc",
    "m1_crpc",
    "recurrence_bcr",
}

ARPI_MOLECULE_DISCRIMINATION_BUNDLE = [
    "ecog_score",
    "frailty_status",
    "child_pugh_score",
    "hepatic_risk_factors",
    "comorbidity_seizure",
    "comorbidity_cardio",
    "cv_risk_documented",
    "drug_interaction_reviewed",
    "current_medications",
    "dermatitis_history",
    "cognitive_risk",
    "fall_risk",
    "stroke_history",
    "edema_risk",
    "steroid_intolerance",
    "diabetes_uncontrolled",
    "baseline_qol",
]

ARPI_MONITORING_BUNDLE = [
    "baseline_bp",
    "baseline_weight",
    "fatigue_baseline",
    "neurocognitive_baseline",
    "fall_history_recent",
    "lft_date",
    "bilirubin",
    "ast",
    "alt",
    "alp",
    "potassium",
    "glucose_or_hba1c",
]

ARPI_ONCOLOGIC_CONTEXT_BY_STATE = {
    "m0_crpc": [
        "psadt_months",
        "imaging_negative",
        "conventional_imaging_modality",
        "conventional_imaging_date",
        "castrate_testosterone_confirmed",
    ],
    "m1_crpc": [
        "metastasis_site",
        "prior_therapy",
        "mcrpc_line_context",
        "castrate_testosterone_confirmed",
    ],
    "mcspc_high_volume_sync": [
        "metastatic_components_capture",
        "metastasis_count",
        "bone_pain",
    ],
    "mcspc_high_volume_metachronous": [
        "metastatic_components_capture",
        "metastasis_count",
        "prior_radiation",
    ],
    "mcspc_low_volume_sync_oligo": [
        "metastatic_components_capture",
        "metastasis_count",
        "rt_primary_received",
    ],
    "mcspc_oligo_metachronous": [
        "metastatic_components_capture",
        "metastasis_count",
        "prior_radiation",
        "mdt_context",
    ],
    "recurrence_bcr": [
        "psadt_months",
        "salvage_local_feasible",
        "psma_pet_done",
    ],
}

ARPI_FIELD_ALIASES = {
    "baseline_bp": ["systolic_bp"],
    "baseline_weight": ["weight_kg"],
    "fatigue_baseline": ["fatigue_score"],
    "neurocognitive_baseline": ["mini_cog_score"],
    "fall_history_recent": ["falls_recent"],
    "lft_date": ["liver_panel_date"],
    "glucose_or_hba1c": ["glucose", "hba1c"],
    "metastatic_components_capture": [
        "metastatic_components_capture",
        "metastatic_disease_known",
        "bone_site_entries",
        "visceral_site_entries",
        "nonregional_nodal_site_entries",
    ],
    "bone_pain": ["pain_burden", "pain_symptoms"],
    "prior_radiation": ["rt_primary_received"],
}

ARPI_FRESHNESS_RULES = {
    "lft_date": 14,
    "conventional_imaging_date": 90,
    "molecular_assay_date": 3650,
    "molecular_report_date": 3650,
    "psadt_months": 30,
}

ARPI_STATE_CANDIDATES = {
    "m0_crpc": ["ADT_DAROLUTAMIDE", "ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE"],
    "m1_crpc": ["ADT_ENZALUTAMIDE", "ADT_ABIRATERONE"],
    "mcspc_high_volume_sync": [
        "ADT_DOCETAXEL_DAROLUTAMIDE",
        "ADT_DOCETAXEL_ABIRATERONE",
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
    ],
    "mcspc_high_volume_metachronous": [
        "ADT_DOCETAXEL_DAROLUTAMIDE",
        "ADT_DOCETAXEL_ABIRATERONE",
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
    ],
    "mcspc_low_volume_sync_oligo": [
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
    ],
    "mcspc_oligo_metachronous": [
        "ADT_DAROLUTAMIDE",
        "ADT_ENZALUTAMIDE",
        "ADT_APALUTAMIDE",
        "ADT_ABIRATERONE",
    ],
    "recurrence_bcr": ["ADT_ENZALUTAMIDE"],
}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "present", "positive", "positivo"}


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _nonempty_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _field_value(payload: dict[str, Any], field_name: str) -> Any:
    if field_name in payload and payload.get(field_name) not in (None, ""):
        return payload.get(field_name)
    for alias in ARPI_FIELD_ALIASES.get(field_name, []):
        value = payload.get(alias)
        if value not in (None, "", [], {}):
            return value
    return payload.get(field_name)


def _field_present(payload: dict[str, Any], field_name: str) -> bool:
    value = _field_value(payload, field_name)
    if field_name == "metastatic_components_capture":
        if _truthy(payload.get("metastatic_disease_known")):
            return True
        if any(payload.get(alias) not in (None, "", [], {}) for alias in ARPI_FIELD_ALIASES[field_name][1:]):
            return True
    if field_name in {"current_medications"}:
        return _nonempty_text(value)
    return value not in (None, "", [], {}, "Desconocido", "Desconocida", "No documentado", "No aplica", "unknown")


def _field_is_stale(payload: dict[str, Any], field_name: str) -> bool:
    max_age_days = ARPI_FRESHNESS_RULES.get(field_name)
    if not max_age_days:
        return False
    field_date = _as_date(_field_value(payload, field_name))
    if not field_date:
        return False
    return (date.today() - field_date).days > max_age_days


def canonical_arpi_state(state: str) -> str:
    return str(state or "").strip()


def is_arpi_eligible_state(state: str) -> bool:
    return canonical_arpi_state(state) in ARPI_ELIGIBLE_STATES


def candidate_regimens_for_state(
    state: str,
    payload: dict[str, Any] | None = None,
) -> list[str]:
    payload = payload or {}
    canonical = canonical_arpi_state(state)
    candidates = list(ARPI_STATE_CANDIDATES.get(canonical, []))
    if canonical == "m1_crpc":
        prior_therapy = str(payload.get("prior_therapy") or "").lower()
        if any(token in prior_therapy for token in ("enzalut", "apalut", "darolut")):
            candidates = [code for code in candidates if code != "ADT_ENZALUTAMIDE"]
        if "abirater" in prior_therapy:
            candidates = [code for code in candidates if code != "ADT_ABIRATERONE"]
    if canonical == "recurrence_bcr" and str(payload.get("salvage_local_feasible") or "").strip().lower() in {"1", "true", "yes", "si", "sí"}:
        return []
    return candidates


def arpi_required_fields_for_state(
    state: str,
    *,
    include_monitoring: bool = True,
) -> list[str]:
    canonical = canonical_arpi_state(state)
    required = list(ARPI_ONCOLOGIC_CONTEXT_BY_STATE.get(canonical, []))
    required.extend(ARPI_MOLECULE_DISCRIMINATION_BUNDLE)
    if include_monitoring:
        required.extend(ARPI_MONITORING_BUNDLE)
    return list(dict.fromkeys(required))


def build_arpi_capture_contract(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    candidate_regimens: list[str] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    canonical = canonical_arpi_state(state)
    candidates = list(candidate_regimens or candidate_regimens_for_state(canonical, payload))
    required_fields = arpi_required_fields_for_state(canonical) if candidates else []
    missing_inputs = [field for field in required_fields if not _field_present(payload, field)]
    stale_inputs = [field for field in required_fields if field not in missing_inputs and _field_is_stale(payload, field)]
    completeness = (
        "complete"
        if required_fields and not missing_inputs and not stale_inputs
        else "partial"
        if required_fields and (missing_inputs or stale_inputs)
        else "not_applicable"
    )
    preference_readiness = "ready" if completeness == "complete" else "needs_data" if required_fields else "not_applicable"
    return {
        "state": canonical,
        "candidate_regimens": candidates,
        "arpi_required_fields": required_fields,
        "arpi_missing_inputs": missing_inputs,
        "arpi_stale_inputs": stale_inputs,
        "arpi_profile_completeness": completeness,
        "arpi_preference_readiness": preference_readiness,
        "arpi_oncologic_context_bundle": list(ARPI_ONCOLOGIC_CONTEXT_BY_STATE.get(canonical, [])),
        "arpi_molecule_discrimination_bundle": list(ARPI_MOLECULE_DISCRIMINATION_BUNDLE),
        "arpi_monitoring_bundle": list(ARPI_MONITORING_BUNDLE),
    }


def _strength_value(value: str) -> float:
    return {
        "none": 0.0,
        "low": 1.0,
        "moderate": 2.0,
        "high": 3.0,
    }.get(str(value or "").strip().lower(), 0.0)


def _scenario_match_value(value: str) -> float:
    return {
        "exact": 4.0,
        "supported_extrapolation": 1.5,
        "weak_extrapolation": -1.5,
    }.get(str(value or "").strip().lower(), 0.0)


def _maturity_value(value: str) -> float:
    return {
        "early": 0.5,
        "intermediate": 1.25,
        "mature": 2.0,
    }.get(str(value or "").strip().lower(), 0.0)


def _endpoint_multiplier(state: str, endpoint: str) -> float:
    canonical = canonical_arpi_state(state)
    endpoint_key = str(endpoint or "").strip().upper()
    if canonical == "m0_crpc":
        return {"MFS": 2.0, "OS": 1.0, "RPFS": 0.5}.get(endpoint_key, 0.5)
    if canonical == "recurrence_bcr":
        return {"MFS": 2.0, "OS": 1.0, "RPFS": 0.5}.get(endpoint_key, 0.5)
    if canonical == "m1_crpc":
        return {"OS": 2.0, "RPFS": 1.5, "MFS": 0.5}.get(endpoint_key, 0.5)
    return {"OS": 2.0, "RPFS": 1.25, "MFS": 0.5}.get(endpoint_key, 0.5)


def _benefit_score(state: str, benefit_profile: dict[str, Any]) -> float:
    if not benefit_profile:
        return 0.0
    endpoint = str(benefit_profile.get("primary_benefit_endpoint") or "")
    benefit = float(benefit_profile.get("benefit_score") or 0.0)
    if benefit:
        return benefit
    return round(
        _scenario_match_value(str(benefit_profile.get("scenario_match") or ""))
        + _maturity_value(str(benefit_profile.get("evidence_maturity") or ""))
        + _strength_value(str(benefit_profile.get("os_benefit_strength") or ""))
        + _strength_value(str(benefit_profile.get("mfs_benefit_strength") or ""))
        + (_strength_value(str(benefit_profile.get("rpfs_benefit_strength") or "")) * _endpoint_multiplier(state, endpoint)),
        2,
    )


def _safety_adjustment(payload: dict[str, Any], regimen_code: str) -> tuple[float, list[str], list[str]]:
    normalized = normalize_regimen_code(regimen_code)
    value = 0.0
    reasons: list[str] = []
    drivers: list[str] = []

    seizure = _truthy(_field_value(payload, "comorbidity_seizure"))
    cardio = _truthy(_field_value(payload, "comorbidity_cardio")) or _truthy(_field_value(payload, "cv_risk_documented"))
    ddi_reviewed = _truthy(_field_value(payload, "drug_interaction_reviewed"))
    current_meds_present = _nonempty_text(_field_value(payload, "current_medications"))
    dermatitis = _truthy(_field_value(payload, "dermatitis_history"))
    cognitive_risk = _truthy(_field_value(payload, "cognitive_risk"))
    fall_risk = _truthy(_field_value(payload, "fall_risk"))
    stroke_history = _truthy(_field_value(payload, "stroke_history"))
    edema_risk = _truthy(_field_value(payload, "edema_risk"))
    steroid_intolerance = _truthy(_field_value(payload, "steroid_intolerance"))
    diabetes_uncontrolled = _truthy(_field_value(payload, "diabetes_uncontrolled"))
    hepatic_risk = _truthy(_field_value(payload, "hepatic_risk_factors")) or str(_field_value(payload, "child_pugh_score") or "").strip().upper() in {"B", "C"}
    frailty = str(_field_value(payload, "frailty_status") or "").strip().lower()
    flags = {
        "seizure_risk": seizure,
        "cardio_risk": cardio,
        "cognitive_risk": cognitive_risk,
        "fall_risk": fall_risk,
        "stroke_history": stroke_history,
        "edema_risk": edema_risk,
        "steroid_intolerance": steroid_intolerance,
        "diabetes_uncontrolled": diabetes_uncontrolled,
        "dermatitis_history": dermatitis,
        "frailty_status": frailty in {"vulnerable", "frail"},
        "hepatic_risk": hepatic_risk,
        "polypharmacy": current_meds_present and not ddi_reviewed,
    }

    if normalized.endswith("DAROLUTAMIDE"):
        if seizure:
            value += 6.0
            reasons.append("Darolutamida gana valor por riesgo convulsivo.")
            drivers.append("seizure_risk")
        if cognitive_risk or fall_risk or stroke_history:
            value += 5.0
            reasons.append("Darolutamida gana valor por riesgo cognitivo/caídas/neurológico.")
            drivers.extend([item for item in ("cognitive_risk", "fall_risk", "stroke_history") if flags[item]])
        if current_meds_present and not ddi_reviewed:
            value += 4.0
            reasons.append("Darolutamida gana valor relativo ante polifarmacia con revisión DDI pendiente.")
            drivers.append("polypharmacy")
        if cardio:
            value += 1.5
            reasons.append("El contexto cardiovascular favorece un eje androgénico sin esteroide.")
            drivers.append("cardio_risk")
    elif normalized.endswith("ENZALUTAMIDE"):
        if seizure:
            value -= 8.0
            reasons.append("Enzalutamida se penaliza por riesgo convulsivo.")
            drivers.append("seizure_risk")
        if cognitive_risk or fall_risk or stroke_history:
            value -= 5.5
            reasons.append("Enzalutamida se penaliza por riesgo cognitivo/caídas/neurológico.")
            drivers.extend([item for item in ("cognitive_risk", "fall_risk", "stroke_history") if flags[item]])
        if current_meds_present and not ddi_reviewed:
            value -= 4.0
            reasons.append("Enzalutamida se penaliza por polifarmacia sin revisión DDI formal.")
            drivers.append("polypharmacy")
    elif normalized.endswith("APALUTAMIDE"):
        if seizure:
            value -= 8.0
            reasons.append("Apalutamida se penaliza por riesgo convulsivo.")
            drivers.append("seizure_risk")
        if dermatitis:
            value -= 6.0
            reasons.append("Apalutamida se penaliza por antecedente de rash/dermatitis.")
            drivers.append("dermatitis_history")
        if cognitive_risk or fall_risk or stroke_history:
            value -= 4.5
            reasons.append("Apalutamida se penaliza por riesgo cognitivo/caídas/neurológico.")
            drivers.extend([item for item in ("cognitive_risk", "fall_risk", "stroke_history") if flags[item]])
        if frailty in {"vulnerable", "frail"}:
            value -= 2.5
            reasons.append("La fragilidad reduce el atractivo de apalutamida.")
            drivers.append("frailty_status")
    elif normalized.endswith("ABIRATERONE"):
        if hepatic_risk:
            value -= 9.0
            reasons.append("Abiraterona se penaliza por riesgo hepático/Child-Pugh desfavorable.")
            drivers.append("hepatic_risk")
        if cardio or edema_risk:
            value -= 5.5
            reasons.append("Abiraterona se penaliza por edema o riesgo cardiometabólico.")
            drivers.extend([item for item in ("cardio_risk", "edema_risk") if flags[item]])
        if steroid_intolerance or diabetes_uncontrolled:
            value -= 6.0
            reasons.append("Abiraterona se penaliza por carga de esteroides.")
            drivers.extend([item for item in ("steroid_intolerance", "diabetes_uncontrolled") if flags[item]])
        if seizure:
            value += 1.0
            reasons.append("Abiraterona gana algo de valor relativo frente a ARPI con mayor carga central.")
            drivers.append("seizure_risk")

    return value, reasons, sorted(set(drivers))


def evaluate_arpi_candidate(
    state: str,
    payload: dict[str, Any] | None,
    regimen_code: str,
    *,
    candidate_regimens: list[str] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    normalized_regimen = normalize_regimen_code(regimen_code)
    canonical = canonical_arpi_state(state)
    capture = build_arpi_capture_contract(canonical, payload, candidate_regimens=candidate_regimens)
    benefit_profile = benefit_profile_for_state(canonical, normalized_regimen)
    benefit_score = _benefit_score(canonical, benefit_profile)
    safety_adjustment, safety_reasons, safety_drivers = _safety_adjustment(payload, normalized_regimen)
    required_missing_fields = list(capture.get("arpi_missing_inputs") or [])
    stale_inputs = list(capture.get("arpi_stale_inputs") or [])
    completeness_penalty = -18.0 if required_missing_fields or stale_inputs else 0.0
    preference_confidence = "definitive" if not required_missing_fields and not stale_inputs else "provisional"
    total_adjustment = benefit_score + safety_adjustment + completeness_penalty
    benefit_endpoint_used = str(benefit_profile.get("primary_benefit_endpoint") or "")
    benefit_maturity = str(benefit_profile.get("evidence_maturity") or "")
    trial_basis = str(benefit_profile.get("trial_basis") or "")
    regulatory_support = str(benefit_profile.get("regulatory_support") or "")
    benefit_basis = (
        f"{trial_basis} con endpoint primario {benefit_endpoint_used} y soporte regulatorio {regulatory_support}."
        if trial_basis or regulatory_support
        else ""
    ).strip()
    return {
        "regimen_code": normalized_regimen,
        "regimen_label": regimen_label(normalized_regimen),
        "benefit_profile": benefit_profile,
        "benefit_score": benefit_score,
        "benefit_basis": benefit_basis,
        "benefit_endpoint_used": benefit_endpoint_used,
        "benefit_maturity": benefit_maturity,
        "benefit_adjustment": total_adjustment,
        "benefit_support": {
            "trial_basis": trial_basis,
            "regulatory_support": regulatory_support,
            "scenario_match": str(benefit_profile.get("scenario_match") or ""),
        },
        "safety_rationale": safety_reasons,
        "safety_drivers_used": safety_drivers,
        "required_missing_fields": required_missing_fields,
        "stale_inputs": stale_inputs,
        "preference_confidence": preference_confidence,
        "arpi_capture_contract": capture,
    }


def enrich_ranked_option_with_arpi_metadata(
    option: dict[str, Any],
    *,
    state: str,
    payload: dict[str, Any] | None,
    candidate_regimens: list[str] | None = None,
) -> dict[str, Any]:
    enriched = dict(option or {})
    regimen_code = str(enriched.get("regimen_code") or "")
    if not regimen_code:
        return enriched
    metadata = evaluate_arpi_candidate(
        state,
        payload or {},
        regimen_code,
        candidate_regimens=candidate_regimens,
    )
    enriched["benefit_basis"] = metadata.get("benefit_basis", "")
    enriched["benefit_endpoint_used"] = metadata.get("benefit_endpoint_used", "")
    enriched["benefit_maturity"] = metadata.get("benefit_maturity", "")
    enriched["benefit_support"] = dict(metadata.get("benefit_support") or {})
    enriched["required_missing_fields"] = list(metadata.get("required_missing_fields") or [])
    enriched["stale_inputs"] = list(metadata.get("stale_inputs") or [])
    enriched["preference_confidence"] = metadata.get("preference_confidence", "")
    enriched["safety_drivers_used"] = list(metadata.get("safety_drivers_used") or [])
    return enriched
