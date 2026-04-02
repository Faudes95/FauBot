from __future__ import annotations

from clinical_scores import docetaxel_fitness


def _flag(payload: dict, key: str, default: str = "0") -> bool:
    return str(payload.get(key, default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


def _status_positive(payload: dict, key: str) -> bool:
    val = str(payload.get(key, "Desconocido")).lower()
    return val.startswith("pos") or val in {"detected", "detectado", "mutado", "loss", "perdida", "biallelic", "bialélico"}


def _normalize_line_context(value: str, *, prior_arpi: bool, prior_docetaxel: bool) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "first_line_mcrpc", "line_1", "line1", "first_line", "pre_arpi"}:
        return "first_line_mcrpc"
    if normalized in {"post_arpi_pre_taxane", "pre_taxane"}:
        return "post_arpi_pre_taxane"
    if normalized in {"post_taxane", "post_docetaxel", "later_line"}:
        return "post_taxane"
    if prior_arpi and prior_docetaxel:
        return "post_taxane"
    if prior_arpi:
        return "post_arpi_pre_taxane"
    return "first_line_mcrpc"


def _safe_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def evaluate_m1_crpc(payload: dict) -> dict:
    hrr = str(payload.get("hrr_status", "Desconocido"))
    msi = str(payload.get("msi_status", "desconocido"))
    psma_positive = _flag(payload, "psma_positive")
    tmb_high = _flag(payload, "tmb_high")
    prior_docetaxel_cycles = int(float(payload.get("prior_docetaxel_cycles", 0) or 0))
    prior_therapy = str(payload.get("prior_therapy", ""))
    prior_therapy_lower = prior_therapy.lower()
    prior_arpi = any(
        token in prior_therapy_lower
        for token in ["abirater", "enzalut", "apalut", "darolut", "rezvilut"]
    )
    chemotherapy_delay_candidate = _flag(payload, "chemotherapy_delay_candidate")
    castrate_confirmed = _flag(payload, "castrate_testosterone_confirmed")
    prior_abiraterone = "abirater" in prior_therapy_lower
    prior_enza_class = any(
        token in prior_therapy_lower for token in ["enzalut", "apalut", "darolut", "rezvilut"]
    )
    prior_docetaxel = prior_docetaxel_cycles >= 6 or "docetax" in prior_therapy_lower
    line_context = _normalize_line_context(
        str(payload.get("mcrpc_line_context", payload.get("line_context", "first_line_mcrpc")) or "first_line_mcrpc"),
        prior_arpi=prior_arpi,
        prior_docetaxel=prior_docetaxel,
    )
    hrr_gene = str(payload.get("hrr_gene", "Desconocido"))
    symptomatic_bone_only = str(payload.get("pain_symptoms", "Asintomatico")) != "Asintomatico" and str(payload.get("metastasis_site", "Bone")) == "Bone"

    ecog_score = _safe_int(payload.get("ecog_score") or payload.get("ecog_performance_status") or payload.get("ecog") or 1) or 1
    frailty_status = str(payload.get("frailty_status", "Fit") or "Fit").strip()
    child_pugh_score = str(payload.get("child_pugh_score", "A") or "A").strip().upper()
    cardio_risk = _flag(payload, "cv_risk_documented")
    ddi_reviewed = _flag(payload, "drug_interaction_reviewed")
    hepatic_risk = _flag(payload, "hepatic_risk_factors") or child_pugh_score in {"B", "C"}
    current_medications = str(payload.get("current_medications") or "").strip()
    current_medications_present = bool(current_medications)
    seizure_risk = _flag(payload, "comorbidity_seizure") or _status_positive(payload, "seizure_history")
    taxane_candidate_now = not prior_docetaxel and line_context in {"first_line_mcrpc", "post_arpi_pre_taxane"}

    taxane_payload = dict(payload)
    taxane_payload.setdefault("ecog_score", ecog_score)
    taxane_payload["force_docetaxel_verification"] = 1 if taxane_candidate_now else 0
    taxane_payload["docetaxel_context"] = "mcrpc_taxane_competition"
    docetaxel_bundle = docetaxel_fitness(taxane_payload)
    legacy_docetaxel_fit = str(payload.get("docetaxel_fit", "")).strip()
    docetaxel_fit = bool(docetaxel_bundle.get("fit_for_docetaxel"))
    if not taxane_candidate_now and legacy_docetaxel_fit in {"0", "1"}:
        docetaxel_fit = legacy_docetaxel_fit == "1"

    abiraterone_hard_block = hepatic_risk
    abiraterone_caution = cardio_risk or not ddi_reviewed

    # ── Biomarcadores expandidos ─────────────────────────────────────
    ar_v7_positive = _status_positive(payload, "ar_v7_status")
    tp53_altered = _status_positive(payload, "tp53_status")
    rb1_loss = _status_positive(payload, "rb1_status")
    pten_loss = _status_positive(payload, "pten_loss") or _status_positive(payload, "pten_status")
    cdk12_biallelic = _status_positive(payload, "cdk12_status")

    tmb_value = _safe_float(payload.get("tmb_value") or payload.get("tmb_mutations_per_mb") or 0)
    tmb_zone = "high" if (tmb_high or (tmb_value is not None and tmb_value > 10)) else (
        "gray" if (tmb_value is not None and 6 <= tmb_value <= 10) else "low"
    )

    ctdna_detected = _flag(payload, "ctdna_detected")
    ctdna_vaf = _safe_float(payload.get("ctdna_vaf") or 0) or None
    ctdna_rising = _flag(payload, "ctdna_rising")

    neuroendocrine_features = _flag(payload, "neuroendocrine_features")
    nepc_suspicion_score = 0
    if tp53_altered and rb1_loss:
        nepc_suspicion_score += 2
    if neuroendocrine_features:
        nepc_suspicion_score += 2
    nse_elevated = False
    nse = _safe_float(payload.get("nse") or payload.get("neuron_specific_enolase") or 0)
    if nse is not None and nse > 16.3:
        nse_elevated = True
        nepc_suspicion_score += 1
    ldh_elevated = False
    ldh = _safe_float(payload.get("ldh") or payload.get("lactate_dehydrogenase") or 0)
    if ldh is not None and ldh > 250:
        ldh_elevated = True
        nepc_suspicion_score += 1
    psa_discordant_low = _flag(payload, "psa_discordant_low")
    if psa_discordant_low:
        nepc_suspicion_score += 1
    nepc_suspected = nepc_suspicion_score >= 3
    lineage_plasticity_risk = tp53_altered and rb1_loss

    return {
        "label": "M1 CRPC",
        "hrr_positive": hrr.lower().startswith("pos"),
        "msi_high": msi == "inestable",
        "tmb_high": tmb_high or (tmb_value is not None and tmb_value > 10),
        "psma_positive": psma_positive,
        "prior_arpi": prior_arpi,
        "prior_docetaxel": prior_docetaxel,
        "prior_abiraterone": prior_abiraterone,
        "prior_enza_class": prior_enza_class,
        "symptomatic_bone_only": symptomatic_bone_only,
        "line_context": line_context,
        "docetaxel_fit": docetaxel_fit,
        "taxane_candidate_now": taxane_candidate_now,
        "docetaxel_fitness": docetaxel_bundle,
        "docetaxel_base_eligibility": str(docetaxel_bundle.get("docetaxel_base_eligibility") or "not_assessable"),
        "docetaxel_verification_status": str(docetaxel_bundle.get("docetaxel_verification_status") or "verified"),
        "docetaxel_block_type": str(docetaxel_bundle.get("docetaxel_block_type") or "none"),
        "docetaxel_required_now": bool(docetaxel_bundle.get("docetaxel_required_now")),
        "docetaxel_default_intensification": str(docetaxel_bundle.get("docetaxel_default_intensification") or "no"),
        "docetaxel_hard_stop_reasons": list(docetaxel_bundle.get("docetaxel_hard_stop_reasons") or []),
        "docetaxel_missing_inputs": list(docetaxel_bundle.get("docetaxel_missing_inputs") or []),
        "docetaxel_stale_inputs": list(docetaxel_bundle.get("docetaxel_stale_inputs") or []),
        "chemotherapy_delay_candidate": chemotherapy_delay_candidate,
        "castrate_confirmed": castrate_confirmed,
        "brca_pathway": hrr_gene in {"BRCA1", "BRCA2"},
        "hrr_gene": hrr_gene,
        "rare_histology_variant": str(payload.get("rare_histology_variant", "0")) == "1",
        "neuroendocrine_features": neuroendocrine_features,
        "ecog_score": ecog_score,
        "frailty_status": frailty_status,
        "child_pugh_score": child_pugh_score,
        "cv_risk_documented": cardio_risk,
        "drug_interaction_reviewed": ddi_reviewed,
        "current_medications_present": current_medications_present,
        "current_medications": current_medications,
        "comorbidity_seizure": seizure_risk,
        "hepatic_risk": hepatic_risk,
        "abiraterone_hard_block": abiraterone_hard_block,
        "abiraterone_caution": abiraterone_caution,
        "selection_safety_profile": {
            "ecog_score": ecog_score,
            "frailty_status": frailty_status,
            "child_pugh_score": child_pugh_score,
            "cardio_risk": cardio_risk,
            "ddi_reviewed": ddi_reviewed,
            "current_medications_present": current_medications_present,
            "seizure_risk": seizure_risk,
            "hepatic_risk": hepatic_risk,
        },
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
        "recommendation": "Prioritize biomarker-driven and sequence-aware options before recycling exhausted classes, while verifying taxane eligibility structurally when docetaxel still competes.",
    }
