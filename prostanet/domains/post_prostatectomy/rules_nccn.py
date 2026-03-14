from __future__ import annotations


def classify_post_rp(payload: dict) -> dict:
    psa_postop = float(payload.get("psa_postop", 0) or 0)
    margin = str(payload.get("surgical_margin", "0")) == "1"
    ece = str(payload.get("ece_status", "0")) == "1"
    svi = str(payload.get("svi_status", "0")) == "1"
    lni = str(payload.get("lni_status", "0")) == "1"
    decipher_risk = str(payload.get("decipher_risk", "No realizado"))
    eligible_pelvic_therapy = str(payload.get("eligible_pelvic_therapy", "1")) == "1"
    time_to_recurrence = float(payload.get("time_to_recurrence_months", 0) or 0)
    adverse = margin or ece or svi or lni

    if psa_postop > 0.1:
        return {
            "label": "PSA persistence/recurrence",
            "recommendation": "Escalate to recurrence/salvage assessment rather than routine surveillance.",
            "adverse_features": adverse,
            "early_salvage_emphasis": eligible_pelvic_therapy,
        }
    if adverse or decipher_risk == "Alto":
        return {
            "label": "Adverse pathology under surveillance",
            "recommendation": "Prefer close monitoring with early salvage planning; use Decipher and timing of recurrence to refine urgency instead of reflex adjuvant treatment for every patient.",
            "adverse_features": adverse,
            "early_salvage_emphasis": eligible_pelvic_therapy and (decipher_risk == "Alto" or 0 < time_to_recurrence <= 24),
        }
    return {
        "label": "Post-RP surveillance",
        "recommendation": "Standard postoperative surveillance is appropriate.",
        "adverse_features": adverse,
        "early_salvage_emphasis": False,
    }
