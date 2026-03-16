from __future__ import annotations


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)) == "1"


def _status_positive(payload: dict, key: str) -> bool:
    val = str(payload.get(key, "Desconocido")).lower()
    return val.startswith("pos") or val in {"detected", "detectado", "mutado", "loss", "perdida", "biallelic", "bialélico"}


def evaluate_m1_crpc(payload: dict) -> dict:
    hrr = str(payload.get("hrr_status", "Desconocido"))
    msi = str(payload.get("msi_status", "desconocido"))
    psma_positive = _flag(payload, "psma_positive")
    tmb_high = _flag(payload, "tmb_high")
    prior_docetaxel_cycles = int(float(payload.get("prior_docetaxel_cycles", 0) or 0))
    prior_therapy = str(payload.get("prior_therapy", ""))
    prior_arpi = any(drug in prior_therapy for drug in ["Abiraterona", "Enzalutamida", "Apalutamida", "Darolutamida", "Rezvilutamida"])
    line_context = str(payload.get("mcrpc_line_context", payload.get("line_context", "first_line_mcrpc")) or "first_line_mcrpc")
    docetaxel_fit = str(payload.get("docetaxel_fit", "1")) == "1"
    chemotherapy_delay_candidate = _flag(payload, "chemotherapy_delay_candidate")
    castrate_confirmed = _flag(payload, "castrate_testosterone_confirmed")
    prior_abiraterone = "Abiraterona" in prior_therapy
    prior_enza_class = any(drug in prior_therapy for drug in ["Enzalutamida", "Apalutamida", "Darolutamida", "Rezvilutamida"])
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    symptomatic_bone_only = str(payload.get("pain_symptoms", "Asintomatico")) != "Asintomatico" and str(payload.get("metastasis_site", "Bone")) == "Bone"

    # ── Biomarcadores expandidos ─────────────────────────────────────
    ar_v7_positive = _status_positive(payload, "ar_v7_status")
    tp53_altered = _status_positive(payload, "tp53_status")
    rb1_loss = _status_positive(payload, "rb1_status")
    pten_loss = _status_positive(payload, "pten_loss") or _status_positive(payload, "pten_status")
    cdk12_biallelic = _status_positive(payload, "cdk12_status")

    # TMB continuo (no solo binario)
    tmb_value = None
    try:
        tmb_value = float(payload.get("tmb_value") or payload.get("tmb_mutations_per_mb") or 0)
    except (ValueError, TypeError):
        pass
    tmb_zone = "high" if (tmb_high or (tmb_value is not None and tmb_value > 10)) else (
        "gray" if (tmb_value is not None and 6 <= tmb_value <= 10) else "low"
    )

    # ctDNA
    ctdna_detected = _flag(payload, "ctdna_detected")
    ctdna_vaf = None
    try:
        ctdna_vaf = float(payload.get("ctdna_vaf") or 0) or None
    except (ValueError, TypeError):
        pass
    ctdna_rising = _flag(payload, "ctdna_rising")

    # Algoritmo de sospecha NEPC (Beltran 2016 / NCCN 2026)
    neuroendocrine_features = _flag(payload, "neuroendocrine_features")
    nepc_suspicion_score = 0
    if tp53_altered and rb1_loss:
        nepc_suspicion_score += 2
    if neuroendocrine_features:
        nepc_suspicion_score += 2
    nse_elevated = False
    try:
        nse = float(payload.get("nse") or payload.get("neuron_specific_enolase") or 0)
        if nse > 16.3:
            nse_elevated = True
            nepc_suspicion_score += 1
    except (ValueError, TypeError):
        pass
    ldh_elevated = False
    try:
        ldh = float(payload.get("ldh") or payload.get("lactate_dehydrogenase") or 0)
        if ldh > 250:
            ldh_elevated = True
            nepc_suspicion_score += 1
    except (ValueError, TypeError):
        pass
    psa_discordant_low = _flag(payload, "psa_discordant_low")
    if psa_discordant_low:
        nepc_suspicion_score += 1
    nepc_suspected = nepc_suspicion_score >= 3

    # Lineage plasticity flag (TP53 + RB1 combined)
    lineage_plasticity_risk = tp53_altered and rb1_loss

    return {
        "label": "M1 CRPC",
        "hrr_positive": hrr.lower().startswith("pos"),
        "msi_high": msi == "inestable",
        "tmb_high": tmb_high or (tmb_value is not None and tmb_value > 10),
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
        "neuroendocrine_features": neuroendocrine_features,
        # ── Nuevos flags de precisión ──
        "ar_v7_positive": ar_v7_positive,
        "tp53_altered": tp53_altered,
        "rb1_loss": rb1_loss,
        "lineage_plasticity_risk": lineage_plasticity_risk,
        "pten_loss": pten_loss,
        "cdk12_biallelic": cdk12_biallelic,
        "tmb_value": tmb_value,
        "tmb_zone": tmb_zone,
        "ctdna_detected": ctdna_detected,
        "ctdna_vaf": ctdna_vaf,
        "ctdna_rising": ctdna_rising,
        "nepc_suspected": nepc_suspected,
        "nepc_suspicion_score": nepc_suspicion_score,
        "nse_elevated": nse_elevated,
        "ldh_elevated": ldh_elevated,
        "psa_discordant_low": psa_discordant_low,
        "recommendation": "Prioritize biomarker-driven and sequence-aware options before recycling exhausted classes.",
    }
