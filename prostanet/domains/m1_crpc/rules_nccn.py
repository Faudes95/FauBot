from __future__ import annotations


def evaluate_m1_crpc(payload: dict) -> dict:
    hrr = str(payload.get("hrr_status", "Desconocido"))
    msi = str(payload.get("msi_status", "desconocido"))
    psma_positive = str(payload.get("psma_positive", "0")) == "1"
    tmb_high = str(payload.get("tmb_high", "0")) == "1"
    prior_docetaxel_cycles = int(float(payload.get("prior_docetaxel_cycles", 0) or 0))
    prior_therapy = str(payload.get("prior_therapy", ""))
    prior_arpi = any(drug in prior_therapy for drug in ["Abiraterona", "Enzalutamida", "Apalutamida", "Darolutamida", "Rezvilutamida"])
    line_context = str(payload.get("mcrpc_line_context", payload.get("line_context", "first_line_mcrpc")) or "first_line_mcrpc")
    docetaxel_fit = str(payload.get("docetaxel_fit", "1")) == "1"
    chemotherapy_delay_candidate = str(payload.get("chemotherapy_delay_candidate", "0")) == "1"
    castrate_confirmed = str(payload.get("castrate_testosterone_confirmed", "0")) == "1"
    prior_abiraterone = "Abiraterona" in prior_therapy
    prior_enza_class = any(drug in prior_therapy for drug in ["Enzalutamida", "Apalutamida", "Darolutamida", "Rezvilutamida"])
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    symptomatic_bone_only = str(payload.get("pain_symptoms", "Asintomatico")) != "Asintomatico" and str(payload.get("metastasis_site", "Bone")) == "Bone"
    return {
        "label": "M1 CRPC",
        "hrr_positive": hrr.lower().startswith("pos"),
        "msi_high": msi == "inestable",
        "tmb_high": tmb_high,
        "psma_positive": psma_positive,
        "prior_arpi": prior_arpi,
        "prior_docetaxel": prior_docetaxel_cycles >= 6 or "Docetaxel" in prior_therapy,
        "prior_abiraterone": prior_abiraterone,
        "prior_enza_class": prior_enza_class,
        "symptomatic_bone_only": symptomatic_bone_only,
        "line_context": line_context,
        "docetaxel_fit": docetaxel_fit,
        "chemotherapy_delay_candidate": chemotherapy_delay_candidate,
        "castrate_confirmed": castrate_confirmed,
        "brca_pathway": hrr_gene in {"BRCA1", "BRCA2"},
        "hrr_gene": hrr_gene,
        "rare_histology_variant": str(payload.get("rare_histology_variant", "0")) == "1",
        "neuroendocrine_features": str(payload.get("neuroendocrine_features", "0")) == "1",
        "recommendation": "Prioritize biomarker-driven and sequence-aware options before recycling exhausted classes.",
    }
