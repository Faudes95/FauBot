from __future__ import annotations


def classify_post_rp_eau(payload: dict) -> dict:
    psa_postop = float(payload.get("psa_postop", 0) or 0)
    if psa_postop > 0.1:
        label = "Post-RP biochemical persistence"
    else:
        label = "Post-RP follow-up"
    return {
        "label": label,
        "recommendation": "Prefer risk-adapted follow-up and early salvage decision-making over reflex adjuvant treatment.",
    }

