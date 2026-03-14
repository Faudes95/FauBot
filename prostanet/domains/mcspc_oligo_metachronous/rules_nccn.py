from __future__ import annotations


def evaluate_mcspc_oligo_metachronous(payload: dict) -> dict:
    count = int(float(payload.get("metastasis_count", 0) or 0))
    site = str(payload.get("metastasis_site", "Bone"))
    ecog = int(float(payload.get("ecog_score", 0) or 0))
    fit_for_intensification = ecog <= 2
    seizure_risk = str(payload.get("comorbidity_seizure", "0")) == "1"
    cardio_risk = str(payload.get("comorbidity_cardio", "0")) == "1"
    brca2_status = str(payload.get("brca2_status", "Desconocido"))
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    assay_source = str(payload.get("molecular_assay_source", "Desconocida"))
    assay_date = str(payload.get("molecular_assay_date", "")).strip()
    brca2_positive = brca2_status == "Positivo" or hrr_gene == "BRCA2"
    mdt_context = str(payload.get("mdt_context", "No documentado"))
    return {
        "label": "mCSPC oligometastatic metachronous",
        "fit_for_intensification": fit_for_intensification,
        "mdt_candidate": count <= 5 and site.lower() != "visceral" and mdt_context in {"Ensayo/cohorte prospectiva", "Discusión multidisciplinaria"},
        "mdt_context": mdt_context,
        "prefer_enzalutamide": fit_for_intensification and not seizure_risk,
        "prefer_abiraterone": fit_for_intensification and not cardio_risk,
        "prefer_akeega": brca2_positive and assay_source not in {"", "Desconocida", "Desconocido"} and bool(assay_date),
        "rezvilutamide_candidate": fit_for_intensification and not seizure_risk,
        "bone_health_complete": str(payload.get("dxa_baseline_done", "0")) == "1" and str(payload.get("calcium_vitd_started", "0")) == "1",
        "bone_protection_started": str(payload.get("bone_protection_started", "0")) == "1",
        "recommendation": "Combine systemic intensification with MDT discussion when disease is limited.",
    }
