from __future__ import annotations


def evaluate_mcspc_high_volume(payload: dict) -> dict:
    ecog = int(float(payload.get("ecog_score", 0) or 0))
    child_pugh = str(payload.get("child_pugh_score", "A"))
    seizure_risk = str(payload.get("comorbidity_seizure", "0")) == "1"
    cardio_risk = str(payload.get("comorbidity_cardio", "0")) == "1"
    frailty = str(payload.get("frailty_status", "Fit"))
    fit_for_docetaxel = ecog <= 2 and child_pugh != "C" and frailty != "Frail"
    assay_source = str(payload.get("molecular_assay_source", payload.get("biomarker_source", "Desconocida")))
    assay_date = str(payload.get("molecular_assay_date", "")).strip()
    brca2_status = str(payload.get("brca2_status", "Desconocido"))
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    brca2_positive = brca2_status == "Positivo" or hrr_gene == "BRCA2"
    molecular_traceable = brca2_positive and assay_source not in {"", "Desconocida", "Desconocido"} and bool(assay_date)
    return {
        "label": "mCSPC high-volume",
        "fit_for_docetaxel": fit_for_docetaxel,
        "prefer_akeega": molecular_traceable,
        "prefer_triplet_darolutamide": fit_for_docetaxel and not seizure_risk,
        "prefer_triplet_abiraterone": fit_for_docetaxel and not cardio_risk and child_pugh != "C",
        "rezvilutamide_candidate": not seizure_risk and frailty != "Frail",
        "bone_health_complete": str(payload.get("dxa_baseline_done", "0")) == "1" and str(payload.get("calcium_vitd_started", "0")) == "1",
        "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
        "molecular_traceable": molecular_traceable,
        "recommendation": "Prioritize triplet therapy when clinically fit; otherwise use best doublet option.",
    }
