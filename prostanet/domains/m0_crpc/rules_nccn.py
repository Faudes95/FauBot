from __future__ import annotations


def evaluate_m0_crpc(payload: dict) -> dict:
    psadt = float(payload.get("psadt_months", 999) or 999)
    seizure_risk = str(payload.get("comorbidity_seizure", "0")) == "1"
    castrate_confirmed = str(payload.get("castrate_testosterone_confirmed", "0")) == "1"
    if not castrate_confirmed:
        return {
            "label": "CRPC no confirmada",
            "high_risk_nmcrpc": False,
            "prefer_darolutamide": False,
            "observe_only": False,
            "castrate_confirmed": False,
            "recommendation": "Confirm castrate-range testosterone and optimize androgen deprivation before assigning a non-metastatic castration-resistant state.",
        }
    return {
        "label": "M0 CRPC",
        "high_risk_nmcrpc": psadt <= 10,
        "prefer_darolutamide": seizure_risk and psadt <= 10,
        "observe_only": psadt > 10,
        "castrate_confirmed": True,
        "recommendation": "Use ARPI intensification when PSADT is short and metastatic imaging is negative.",
    }
