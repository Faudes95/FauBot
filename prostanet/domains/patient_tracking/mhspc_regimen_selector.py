from __future__ import annotations

from typing import Any

from clinical_scores import docetaxel_fitness

from prostanet.domains.patient_tracking.mhspc_frontline_reference import (
    REGIMEN_PIVOTAL_TRIALS,
    component_metadata,
    get_mhspc_frontline_reference,
)
from prostanet.domains.patient_tracking.therapy_catalog import regimen_label


MHSPC_STATES = {
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}

REGIMEN_COMPONENTS = {
    "ADT_DAROLUTAMIDE": ["ADT", "Darolutamida"],
    "ADT_ENZALUTAMIDE": ["ADT", "Enzalutamida"],
    "ADT_APALUTAMIDE": ["ADT", "Apalutamida"],
    "ADT_ABIRATERONE": ["ADT", "Abiraterona"],
    "ADT_DOCETAXEL_DAROLUTAMIDE": ["ADT", "Docetaxel", "Darolutamida"],
    "ADT_DOCETAXEL_ABIRATERONE": ["ADT", "Docetaxel", "Abiraterona"],
}


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on", "documentado"}


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_mhspc_state(state: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    if state != "mcspc_high_volume":
        return state
    explicit = str(payload.get("disease_temporality", "") or "").strip().lower()
    if explicit in {"sync", "sincronico", "sincrónico", "de_novo", "denovo"}:
        return "mcspc_high_volume_sync"
    if explicit in {"metachronous", "metacronico", "metacrónico"}:
        return "mcspc_high_volume_metachronous"
    if _truthy(payload.get("metachronous_metastasis", "0")):
        return "mcspc_high_volume_metachronous"
    return "mcspc_high_volume_sync"


def is_mhspc_state(state: str) -> bool:
    return state in MHSPC_STATES


def _phenotype_profile(state: str, payload: dict[str, Any]) -> dict[str, Any]:
    exact_state = resolve_mhspc_state(state, payload)
    return {
        "state": exact_state,
        "is_high_volume": "high_volume" in exact_state,
        "is_low_volume": exact_state == "mcspc_low_volume_sync_oligo",
        "is_sync": exact_state in {"mcspc_low_volume_sync_oligo", "mcspc_high_volume_sync"},
        "is_metachronous": exact_state in {"mcspc_oligo_metachronous", "mcspc_high_volume_metachronous"},
        "is_oligometastatic": exact_state == "mcspc_oligo_metachronous",
    }


def _modifier_profile(payload: dict[str, Any], *, docetaxel_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    docetaxel = dict(docetaxel_bundle or docetaxel_fitness(payload))
    ecog = _safe_int(payload.get("ecog_score", payload.get("ecog")))
    frailty = str(payload.get("frailty_status", "Fit") or "Fit").strip()
    child_pugh = str(payload.get("child_pugh_score", "A") or "A").strip().upper()
    egfr = _safe_float(payload.get("egfr"))
    return {
        "docetaxel": docetaxel,
        "fit_for_docetaxel": bool(docetaxel.get("fit_for_docetaxel")),
        "docetaxel_status": str(docetaxel.get("fit_status") or ""),
        "ecog": ecog,
        "frailty_status": frailty,
        "child_pugh": child_pugh,
        "egfr": egfr,
        "seizure_risk": _truthy(payload.get("comorbidity_seizure")),
        "cardio_risk": _truthy(payload.get("comorbidity_cardio")) or _truthy(payload.get("cv_risk_documented")),
        "hepatic_risk": child_pugh in {"B", "C"} or _truthy(payload.get("hepatic_risk_factors")),
        "renal_risk_severe": egfr is not None and egfr < 30,
        "ddi_reviewed": _truthy(payload.get("drug_interaction_reviewed")),
        "cognitive_risk": _truthy(payload.get("cognitive_risk")) or frailty.lower() == "frail",
        "fall_risk": _truthy(payload.get("fall_risk")) or frailty.lower() in {"vulnerable", "frail"},
        "rash_history": _truthy(payload.get("history_severe_rash")) or _truthy(payload.get("severe_rash_history")),
        "hypothyroidism": _truthy(payload.get("baseline_hypothyroidism")) or _truthy(payload.get("hypothyroidism")),
        "stroke_history": _truthy(payload.get("stroke_history")) or _truthy(payload.get("cva_history")) or _truthy(payload.get("brain_lesion_history")),
        "edema_risk": _truthy(payload.get("edema_risk")) or _truthy(payload.get("edema_prone")),
        "steroid_risk": _truthy(payload.get("diabetes_uncontrolled")) or _truthy(payload.get("steroid_intolerance")),
        "visceral_metastases": _truthy(payload.get("visceral_metastases")) or str(payload.get("metastasis_site", "")).strip().lower() == "visceral",
        "metastasis_count": _safe_int(payload.get("metastasis_count")) or 0,
        "gleason_score": _safe_int(payload.get("gleason_score")) or 0,
        "rt_primary_candidate": not _truthy(payload.get("rt_primary_received")),
        "mdt_context": str(payload.get("mdt_context") or ""),
    }


def _base_score(regimen_code: str, phenotype: dict[str, Any]) -> float:
    state = phenotype["state"]
    if state == "mcspc_high_volume_sync":
        return {
            "ADT_DOCETAXEL_DAROLUTAMIDE": 92.0,
            "ADT_DOCETAXEL_ABIRATERONE": 88.0,
            "ADT_DAROLUTAMIDE": 79.0,
            "ADT_ENZALUTAMIDE": 78.0,
            "ADT_APALUTAMIDE": 76.0,
            "ADT_ABIRATERONE": 77.0,
        }.get(regimen_code, 0.0)
    if state == "mcspc_high_volume_metachronous":
        return {
            "ADT_DOCETAXEL_DAROLUTAMIDE": 86.0,
            "ADT_DOCETAXEL_ABIRATERONE": 50.0,
            "ADT_DAROLUTAMIDE": 82.0,
            "ADT_ENZALUTAMIDE": 80.0,
            "ADT_APALUTAMIDE": 78.0,
            "ADT_ABIRATERONE": 75.0,
        }.get(regimen_code, 0.0)
    if state == "mcspc_low_volume_sync_oligo":
        return {
            "ADT_ENZALUTAMIDE": 84.0,
            "ADT_APALUTAMIDE": 83.0,
            "ADT_DAROLUTAMIDE": 80.0,
            "ADT_ABIRATERONE": 79.0,
            "ADT_DOCETAXEL_DAROLUTAMIDE": 35.0,
            "ADT_DOCETAXEL_ABIRATERONE": 30.0,
        }.get(regimen_code, 0.0)
    if state == "mcspc_oligo_metachronous":
        return {
            "ADT_ENZALUTAMIDE": 83.0,
            "ADT_DAROLUTAMIDE": 81.0,
            "ADT_APALUTAMIDE": 79.0,
            "ADT_ABIRATERONE": 77.0,
            "ADT_DOCETAXEL_DAROLUTAMIDE": 28.0,
            "ADT_DOCETAXEL_ABIRATERONE": 24.0,
        }.get(regimen_code, 0.0)
    return 0.0


def _trial_fit(regimen_code: str, phenotype: dict[str, Any], modifiers: dict[str, Any]) -> dict[str, Any]:
    matched_trials = list(REGIMEN_PIVOTAL_TRIALS.get(regimen_code) or [])
    fit = "partial"
    rationale = "El subescenario no reproduce completamente la población pivote."
    if regimen_code == "ADT_DOCETAXEL_DAROLUTAMIDE":
        if phenotype["is_high_volume"] and modifiers["fit_for_docetaxel"]:
            fit = "matched" if phenotype["is_sync"] else "partial"
            rationale = (
                "ARASENS es trial-like en alto volumen con aptitud a docetaxel."
                if phenotype["is_sync"]
                else "ARASENS sigue siendo la referencia más cercana en alto volumen metacrónico apto para docetaxel."
            )
    elif regimen_code == "ADT_DOCETAXEL_ABIRATERONE":
        if phenotype["state"] == "mcspc_high_volume_sync" and modifiers["fit_for_docetaxel"]:
            fit = "matched"
            rationale = "PEACE-1 es trial-like en enfermedad sincrónica/de novo de alto volumen apta para docetaxel."
    elif regimen_code == "ADT_ABIRATERONE":
        high_risk_latitude = (
            (modifiers["gleason_score"] >= 8)
            + (modifiers["metastasis_count"] >= 3)
            + int(modifiers["visceral_metastases"])
        ) >= 2
        if phenotype["state"] == "mcspc_high_volume_sync" and high_risk_latitude:
            fit = "matched"
            rationale = "LATITUDE es trial-like en mCSPC de novo/sincrónico de alto riesgo."
        else:
            fit = "partial"
            rationale = "Abiraterona sigue siendo guideline-consistent, pero el encaje con LATITUDE depende del perfil de alto riesgo de novo."
    elif regimen_code == "ADT_DAROLUTAMIDE":
        fit = "matched"
        rationale = "ARANOTE mantiene comparabilidad amplia en mHSPC cuando se prioriza intensificación hormonal sin docetaxel."
    elif regimen_code in {"ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE"}:
        fit = "matched"
        rationale = "La intensificación con ARPI es trial-like para el subescenario mHSPC actual."
    return {
        "fit": fit,
        "matched_trials": matched_trials,
        "rationale": rationale,
    }


def _regimen_components(regimen_code: str) -> list[dict[str, Any]]:
    components = []
    for drug_name in REGIMEN_COMPONENTS.get(regimen_code, []):
        components.append(component_metadata(drug_name))
    return components


def _format_component_summary(components: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for component in components:
        label = str(component.get("drug_name") or "")
        dose = str(component.get("dose") or "")
        route = str(component.get("route") or "")
        schedule = str(component.get("schedule") or "")
        imss_key = str(component.get("imss_key") or "")
        metadata_source = str(component.get("metadata_source") or "")
        details = " · ".join(item for item in [dose, route, schedule] if item)
        suffix = f" Clave IMSS: {imss_key}." if imss_key else ""
        source = " Fuente: documento institucional." if metadata_source == "institutional_ingested_document" else " Fuente: catálogo actual." if metadata_source else ""
        if details:
            parts.append(f"{label}: {details}.{suffix}{source}".strip())
        else:
            parts.append(f"{label}.{suffix}{source}".strip())
    return " ".join(parts)


def _regimen_label(regimen_code: str) -> str:
    custom_labels = {
        "ADT_DAROLUTAMIDE": "ADT + darolutamida",
        "ADT_ENZALUTAMIDE": "ADT + enzalutamida",
        "ADT_APALUTAMIDE": "ADT + apalutamida",
        "ADT_ABIRATERONE": "ADT + abiraterona",
        "ADT_DOCETAXEL_DAROLUTAMIDE": "ADT + docetaxel + darolutamida",
        "ADT_DOCETAXEL_ABIRATERONE": "ADT + docetaxel + abiraterona",
    }
    return custom_labels.get(regimen_code, regimen_label(regimen_code))


def _apply_modifiers(regimen_code: str, phenotype: dict[str, Any], modifiers: dict[str, Any]) -> dict[str, Any]:
    score = _base_score(regimen_code, phenotype)
    reasons_for: list[str] = []
    reasons_against: list[str] = []
    hard_block = False

    trial_fit = _trial_fit(regimen_code, phenotype, modifiers)
    if trial_fit["fit"] == "matched":
        score += 5
        reasons_for.append(trial_fit["rationale"])
    else:
        score -= 3
        reasons_against.append(trial_fit["rationale"])

    if regimen_code in {"ADT_DOCETAXEL_DAROLUTAMIDE", "ADT_DOCETAXEL_ABIRATERONE"}:
        if not modifiers["fit_for_docetaxel"]:
            score -= 60
            hard_block = True
            reasons_against.extend(modifiers["docetaxel"].get("docetaxel_hard_stop_reasons") or ["No apto para docetaxel."])
        elif phenotype["is_high_volume"]:
            reasons_for.append("El fenotipo de alto volumen admite discusión real de triplete.")
        if phenotype["is_low_volume"] or phenotype["is_oligometastatic"]:
            score -= 25
            reasons_against.append("El triplete no es la estrategia visible estándar en bajo volumen u oligometastásico.")
        if regimen_code == "ADT_DOCETAXEL_ABIRATERONE" and phenotype["state"] != "mcspc_high_volume_sync":
            score -= 20
            reasons_against.append("PEACE-1 no debe extrapolarse como backbone principal fuera del alto volumen sincrónico/de novo.")

    if regimen_code.endswith("DAROLUTAMIDE"):
        if modifiers["seizure_risk"] or modifiers["cognitive_risk"] or modifiers["fall_risk"]:
            score += 12
            reasons_for.append("El perfil neurológico/cognitivo favorece darolutamida.")
        if modifiers["cardio_risk"]:
            score += 5
            reasons_for.append("El riesgo cardiovascular favorece evitar ARPI con mayor carga de eventos centrales o esteroides.")
        if modifiers["renal_risk_severe"]:
            score -= 18
            reasons_against.append("La insuficiencia renal grave desprioriza darolutamida.")
        if modifiers["child_pugh"] in {"B", "C"}:
            score -= 18
            reasons_against.append("Child-Pugh B/C desprioriza darolutamida.")

    if regimen_code == "ADT_ENZALUTAMIDE":
        if modifiers["seizure_risk"] or modifiers["stroke_history"]:
            score -= 40
            hard_block = hard_block or modifiers["seizure_risk"] or modifiers["stroke_history"]
            reasons_against.append("Riesgo convulsivo o antecedente neurológico mayor desaconsejan enzalutamida.")
        if modifiers["cognitive_risk"] or modifiers["fall_risk"]:
            score -= 10
            reasons_against.append("La vulnerabilidad cognitiva o de caídas desprioriza enzalutamida.")
        else:
            reasons_for.append("Enzalutamida es guideline-consistent si no existen banderas neurológicas.")

    if regimen_code == "ADT_APALUTAMIDE":
        if modifiers["seizure_risk"]:
            score -= 35
            hard_block = True
            reasons_against.append("Antecedente convulsivo desaconseja apalutamida.")
        if modifiers["rash_history"] or modifiers["hypothyroidism"]:
            score -= 14
            reasons_against.append("El perfil de rash / hipotiroidismo desprioriza apalutamida.")
        elif modifiers["frailty_status"].lower() != "frail":
            reasons_for.append("Apalutamida sigue siendo una opción sólida si no hay rash severo ni fragilidad marcada.")

    if regimen_code in {"ADT_ABIRATERONE", "ADT_DOCETAXEL_ABIRATERONE"}:
        if modifiers["hepatic_risk"] or modifiers["child_pugh"] in {"B", "C"}:
            score -= 45
            hard_block = True
            reasons_against.append("El riesgo hepático clínicamente relevante bloquea abiraterona.")
        if modifiers["cardio_risk"] or modifiers["edema_risk"] or modifiers["steroid_risk"]:
            score -= 16
            reasons_against.append("El perfil cardiovascular/metabólico y la carga de esteroides despriorizan abiraterona.")
        else:
            reasons_for.append("Abiraterona es razonable si el perfil hepático y cardiometabólico es favorable.")

    if modifiers["docetaxel_status"] == "fit_with_caution" and regimen_code.startswith("ADT_DOCETAXEL"):
        score -= 8
        reasons_against.append("Docetaxel sigue siendo posible, pero con cautela por la reserva clínica actual.")

    if not modifiers["ddi_reviewed"] and regimen_code in {"ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_ABIRATERONE"}:
        score -= 4
        reasons_against.append("Falta documentar revisión de interacciones farmacológicas.")
        if regimen_code == "ADT_DAROLUTAMIDE":
            score += 2

    return {
        "score": score,
        "hard_block": hard_block,
        "reasons_for": reasons_for,
        "reasons_against": reasons_against,
        "trial_fit": trial_fit,
    }


def _build_recommendation(regimen_code: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    components = _regimen_components(regimen_code)
    return {
        "regimen_code": regimen_code,
        "regimen_label": _regimen_label(regimen_code),
        "priority": "preferred",
        "is_preferred": True,
        "selection_rationale": list(evaluation["reasons_for"]),
        "contraindication_reasons": list(evaluation["reasons_against"]),
        "pivotal_trial_fit": dict(evaluation["trial_fit"]),
        "guideline_basis": ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC"],
        "component_drugs": components,
        "score": round(float(evaluation["score"]), 1),
    }


def _eligible_treatment_item(recommendation: dict[str, Any], *, priority: str, notes_prefix: str = "") -> dict[str, Any]:
    components = recommendation.get("component_drugs") or []
    rationale = recommendation.get("selection_rationale") or []
    reasons_against = recommendation.get("contraindication_reasons") or []
    summary_parts = []
    if notes_prefix:
        summary_parts.append(notes_prefix)
    if rationale:
        summary_parts.append("A favor: " + "; ".join(rationale[:2]) + ".")
    if reasons_against and priority != "preferred":
        summary_parts.append("Límites: " + "; ".join(reasons_against[:2]) + ".")
    component_summary = _format_component_summary(components)
    if component_summary:
        summary_parts.append(component_summary)
    return {
        "name": recommendation.get("regimen_label", ""),
        "priority": priority,
        "notes": " ".join(part for part in summary_parts if part).strip(),
        "regimen_code": recommendation.get("regimen_code", ""),
        "component_drugs": components,
        "pivotal_trial_fit": recommendation.get("pivotal_trial_fit", {}),
        "metadata_source": "institutional_ingested_document",
    }


def select_mhspc_frontline_regimens(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    docetaxel_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    get_mhspc_frontline_reference()
    phenotype = _phenotype_profile(state, payload)
    modifiers = _modifier_profile(payload, docetaxel_bundle=docetaxel_bundle)

    scored: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    patient_modifiers = []

    if modifiers["seizure_risk"]:
        patient_modifiers.append("Riesgo convulsivo activo")
    if modifiers["cardio_risk"]:
        patient_modifiers.append("Riesgo cardiovascular documentado")
    if modifiers["hepatic_risk"]:
        patient_modifiers.append("Riesgo hepático relevante")
    if modifiers["frailty_status"].lower() in {"vulnerable", "frail"}:
        patient_modifiers.append(f"Fragilidad {modifiers['frailty_status']}")
    if not modifiers["fit_for_docetaxel"]:
        patient_modifiers.append("No apto para docetaxel")

    for regimen_code in REGIMEN_COMPONENTS:
        evaluation = _apply_modifiers(regimen_code, phenotype, modifiers)
        recommendation = _build_recommendation(regimen_code, evaluation)
        entry = {
            **recommendation,
            "hard_block": evaluation["hard_block"],
        }
        if evaluation["hard_block"] or evaluation["score"] < 55:
            entry["is_preferred"] = False
            entry["priority"] = "not_recommended"
            rejected.append(entry)
        else:
            scored.append(entry)

    scored.sort(key=lambda item: (float(item.get("score") or 0), item.get("regimen_label", "")), reverse=True)
    rejected.sort(key=lambda item: (float(item.get("score") or 0), item.get("regimen_label", "")))

    preferred = dict(scored[0]) if scored else {}
    alternatives = [dict(item, is_preferred=False, priority="eligible") for item in scored[1:4]]

    eligible_treatments = []
    if preferred:
        eligible_treatments.append(_eligible_treatment_item(preferred, priority="preferred"))
    for alternative in alternatives:
        eligible_treatments.append(_eligible_treatment_item(alternative, priority="eligible"))

    rejection_reasons = {
        item["regimen_code"]: list(item.get("contraindication_reasons") or [])
        for item in rejected
    }
    eligibility_gates = {
        "phenotype": phenotype,
        "docetaxel_fitness": modifiers["docetaxel"],
        "safety_modifiers": {
            "seizure_risk": modifiers["seizure_risk"],
            "cardio_risk": modifiers["cardio_risk"],
            "hepatic_risk": modifiers["hepatic_risk"],
            "renal_risk_severe": modifiers["renal_risk_severe"],
            "frailty_status": modifiers["frailty_status"],
        },
    }
    pivotal_fit = {
        item["regimen_code"]: dict(item.get("pivotal_trial_fit") or {})
        for item in scored + rejected
    }

    return {
        "preferred_regimen": preferred,
        "alternative_regimens": alternatives,
        "rejected_regimens": rejected,
        "rejection_reasons": rejection_reasons,
        "eligibility_gates": eligibility_gates,
        "pivotal_trial_fit": pivotal_fit,
        "patient_specific_modifiers": patient_modifiers,
        "eligible_treatments": eligible_treatments,
        "frontline_regimen_rankings": scored,
        "frontline_regimen_rejections": rejected,
        "drug_component_metadata": {
            item["regimen_code"]: item.get("component_drugs") or []
            for item in scored + rejected
        },
    }


def preferred_non_triplet_regimen_label(state: str, payload: dict[str, Any] | None = None) -> str:
    selected = select_mhspc_frontline_regimens(state, payload)
    preferred = dict(selected.get("preferred_regimen") or {})
    if preferred and not str(preferred.get("regimen_code", "")).startswith("ADT_DOCETAXEL"):
        return str(preferred.get("regimen_label") or "")
    for item in selected.get("alternative_regimens") or []:
        regimen_code = str(item.get("regimen_code") or "")
        if not regimen_code.startswith("ADT_DOCETAXEL"):
            return str(item.get("regimen_label") or "")
    return "ADT + darolutamida"

