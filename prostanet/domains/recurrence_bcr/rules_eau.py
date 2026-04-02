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
        "recommendation": "Prefiera rescate temprano adaptado al riesgo y evite salidas indiferenciadas de recurrencia.",
    }
