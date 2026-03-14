from __future__ import annotations


def evaluate_mcspc_low_volume(payload: dict) -> dict:
    seizure_risk = str(payload.get("comorbidity_seizure", "0")) == "1"
    child_pugh = str(payload.get("child_pugh_score", "A"))
    rt_primary_received = str(payload.get("rt_primary_received", "0")) == "1"
    brca2_status = str(payload.get("brca2_status", "Desconocido"))
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    assay_source = str(payload.get("molecular_assay_source", "Desconocida"))
    assay_date = str(payload.get("molecular_assay_date", "")).strip()
    brca2_positive = brca2_status == "Positivo" or hrr_gene == "BRCA2"
    return {
        "label": "mCSPC low-volume / synchronous oligometastatic",
        "rt_primary_candidate": not rt_primary_received,
        "prefer_enzalutamide": not seizure_risk,
        "prefer_abiraterone": child_pugh != "C",
        "prefer_akeega": brca2_positive and assay_source not in {"", "Desconocida", "Desconocido"} and bool(assay_date),
        "rezvilutamide_candidate": not seizure_risk,
        "bone_health_complete": str(payload.get("dxa_baseline_done", "0")) == "1" and str(payload.get("calcium_vitd_started", "0")) == "1",
        "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
        "recommendation": "Prefer systemic doublets and evaluate RT to the primary when the prostate remains untreated.",
    }
