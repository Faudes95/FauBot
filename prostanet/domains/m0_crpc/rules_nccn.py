from __future__ import annotations


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def evaluate_m0_crpc(payload: dict) -> dict:
    psadt = float(payload.get("psadt_months", 999) or 999)
    seizure_risk = _flag(payload, "comorbidity_seizure")
    castrate_confirmed = _flag(payload, "castrate_testosterone_confirmed")
    imaging_negative = _flag(payload, "imaging_negative", "1")
    frailty_status = str(payload.get("frailty_status", "Fit") or "Fit").strip()
    cardio_risk = _flag(payload, "cv_risk_documented")
    ddi_reviewed = _flag(payload, "drug_interaction_reviewed")
    current_medications = str(payload.get("current_medications") or "").strip()
    dermatitis_history = _flag(payload, "dermatitis_history")
    conventional_imaging_modality = str(payload.get("conventional_imaging_modality", "Desconocida") or "Desconocida").strip()
    conventional_imaging_date = str(payload.get("conventional_imaging_date") or "").strip()
    current_medications_present = bool(current_medications)
    high_risk_nmcrpc = castrate_confirmed and imaging_negative and psadt <= 10
    observe_only = castrate_confirmed and imaging_negative and psadt > 10
    prefer_darolutamide = high_risk_nmcrpc and (
        seizure_risk
        or frailty_status.lower() in {"vulnerable", "frail"}
        or cardio_risk
        or (current_medications_present and not ddi_reviewed)
    )
    selection_safety_profile = {
        "seizure_risk": seizure_risk,
        "frailty_status": frailty_status,
        "cardio_risk": cardio_risk,
        "ddi_reviewed": ddi_reviewed,
        "current_medications_present": current_medications_present,
        "dermatitis_history": dermatitis_history,
        "conventional_imaging_modality": conventional_imaging_modality,
        "conventional_imaging_date": conventional_imaging_date,
    }
    if not castrate_confirmed:
        return {
            "label": "CRPC no confirmada",
            "high_risk_nmcrpc": False,
            "prefer_darolutamide": False,
            "observe_only": False,
            "castrate_confirmed": False,
            "imaging_negative": imaging_negative,
            "candidate_regimens_under_consideration": ["ADT_MONO"],
            "selection_safety_profile": selection_safety_profile,
            "recommendation": "Confirm castrate-range testosterone and optimize androgen deprivation before assigning a non-metastatic castration-resistant state.",
        }
    if not imaging_negative:
        return {
            "label": "Imagen positiva o no concluyente",
            "high_risk_nmcrpc": False,
            "prefer_darolutamide": False,
            "observe_only": False,
            "castrate_confirmed": True,
            "imaging_negative": False,
            "candidate_regimens_under_consideration": ["RESTAGING", "M1_RECLASSIFICATION"],
            "selection_safety_profile": selection_safety_profile,
            "recommendation": "Do not intensify as nmCRPC until conventional imaging confirms the disease remains non-metastatic.",
        }
    candidate_regimens = ["OBSERVATION"] if observe_only else ["ADT_ENZALUTAMIDE", "ADT_APALUTAMIDE", "ADT_DAROLUTAMIDE"]
    return {
        "label": "M0 CRPC",
        "high_risk_nmcrpc": high_risk_nmcrpc,
        "prefer_darolutamide": prefer_darolutamide,
        "observe_only": observe_only,
        "castrate_confirmed": True,
        "imaging_negative": True,
        "candidate_regimens_under_consideration": candidate_regimens,
        "selection_safety_profile": selection_safety_profile,
        "darolutamide_preference_reasons": [
            reason
            for reason, active in (
                ("Riesgo convulsivo", seizure_risk),
                ("Fragilidad relativa", frailty_status.lower() in {"vulnerable", "frail"}),
                ("Riesgo cardiovascular", cardio_risk),
                ("Polifarmacia con revisión DDI pendiente", current_medications_present and not ddi_reviewed),
            )
            if active
        ],
        "enzalutamide_caution_reasons": [
            reason
            for reason, active in (
                ("Riesgo convulsivo o vulnerabilidad neurológica", seizure_risk),
                ("Revisión DDI pendiente con polifarmacia", current_medications_present and not ddi_reviewed),
                ("Fragilidad/carga de caídas", frailty_status.lower() in {"vulnerable", "frail"}),
            )
            if active
        ],
        "apalutamide_caution_reasons": [
            reason
            for reason, active in (
                ("Riesgo convulsivo o vulnerabilidad neurológica", seizure_risk),
                ("Antecedente dermatológico relevante", dermatitis_history),
                ("Revisión DDI pendiente con polifarmacia", current_medications_present and not ddi_reviewed),
            )
            if active
        ],
        "recommendation": (
            "Use ARPI intensification when PSADT is short, testosterone remains castrate and conventional imaging is still negative."
            if high_risk_nmcrpc
            else "Observe with continued ADT when PSADT exceeds 10 months and imaging remains negative."
        ),
    }
