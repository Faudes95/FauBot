from __future__ import annotations


def classify_recurrence_eau(payload: dict) -> dict:
    if str(payload.get("bcr2", "0")) == "1":
        label = "BCR2 N0M0"
    elif str(payload.get("prior_prostatectomy", "0")) == "1":
        label = "Post-RP biochemical recurrence"
    else:
        label = "Post-RT biochemical recurrence"
    return {
        "label": label,
        "recommendation": "Prefer early risk-adapted salvage and avoid undifferentiated recurrence outputs.",
    }

