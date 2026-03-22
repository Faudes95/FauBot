from __future__ import annotations

from typing import Any


LAB_METADATA = {
    "TESTOSTERONA": {"key": "testosterone", "label": "Testosterona", "unit": "ng/dL", "family": "endocrine"},
    "HEMOGLOBINA": {"key": "hemoglobin", "label": "Hemoglobina", "unit": "g/dL", "family": "hematologic"},
    "ALP": {"key": "alp", "label": "Fosfatasa alcalina", "unit": "UI/L", "family": "bone_burden"},
    "LDH": {"key": "ldh", "label": "LDH", "unit": "UI/L", "family": "bone_burden"},
    "CREATININA": {"key": "creatinine", "label": "Creatinina", "unit": "mg/dL", "family": "renal"},
    "BILIRRUBINA": {"key": "bilirubin", "label": "Bilirrubina", "unit": "mg/dL", "family": "hepatic"},
    "AST": {"key": "ast", "label": "AST", "unit": "UI/L", "family": "hepatic"},
    "ALT": {"key": "alt", "label": "ALT", "unit": "UI/L", "family": "hepatic"},
    "GGT": {"key": "ggt", "label": "GGT", "unit": "UI/L", "family": "hepatic"},
    "GLUCOSA": {"key": "glucose", "label": "Glucosa", "unit": "mg/dL", "family": "metabolic"},
    "HBA1C": {"key": "hba1c", "label": "HbA1c", "unit": "%", "family": "metabolic"},
    "CALCIO": {"key": "calcium_level", "label": "Calcio", "unit": "mg/dL", "family": "bone_support"},
    "VITAMINA_D": {"key": "vitamin_d_level", "label": "Vitamina D", "unit": "ng/mL", "family": "bone_support"},
    "ALBUMINA": {"key": "albumin", "label": "Albúmina", "unit": "g/dL", "family": "hepatic"},
    "CISTATINA_C": {"key": "cystatin_c", "label": "Cistatina C", "unit": "mg/L", "family": "renal"},
}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado")


def build_laboratory_series(patient: dict[str, Any]) -> dict[str, dict[str, Any]]:
    series_map: dict[str, dict[str, Any]] = {}
    for entry in list(patient.get("biomarker_longitudinal") or []):
        biomarker_type = str(entry.get("biomarker_type") or "").upper()
        metadata = LAB_METADATA.get(biomarker_type)
        if not metadata:
            continue
        target = series_map.setdefault(
            metadata["key"],
            {
                "key": metadata["key"],
                "label": metadata["label"],
                "unit": metadata["unit"],
                "family": metadata["family"],
                "points": [],
                "source": "biomarker_longitudinal",
            },
        )
        if _is_present(entry.get("value")) and _is_present(entry.get("sample_date")):
            target["points"].append(
                {
                    "date": str(entry.get("sample_date") or "")[:10],
                    "value": entry.get("value"),
                }
            )

    latest_followup = (patient.get("follow_ups") or [])[-1] if patient.get("follow_ups") else {}
    followup_field_map = {
        "testosterone": "testosterone_current",
        "hemoglobin": "hemoglobin_current",
        "alp": "alp_current",
        "ldh": "ldh_current",
        "creatinine": "creatinine_current",
        "bilirubin": "bilirubin_current",
        "ast": "ast_current",
        "alt": "alt_current",
        "ggt": "ggt_current",
        "glucose": "glucose_current",
        "albumin": "albumin_current",
        "cystatin_c": "cystatin_c_current",
        "hba1c": "hba1c",
        "calcium_level": "calcium_level",
        "vitamin_d_level": "vitamin_d_level",
    }
    followup_date = str(latest_followup.get("visit_date") or "")[:10]
    for metadata in LAB_METADATA.values():
        key = metadata["key"]
        field_name = followup_field_map.get(key)
        if not field_name or not _is_present(latest_followup.get(field_name)) or not followup_date:
            continue
        target = series_map.setdefault(
            key,
            {
                "key": key,
                "label": metadata["label"],
                "unit": metadata["unit"],
                "family": metadata["family"],
                "points": [],
                "source": "follow_up_visits",
            },
        )
        if not any(point.get("date") == followup_date for point in target["points"]):
            target["points"].append({"date": followup_date, "value": latest_followup.get(field_name)})

    for item in series_map.values():
        item["points"] = sorted(item["points"], key=lambda point: str(point.get("date") or ""))
        if item["points"]:
            item["latest_value"] = item["points"][-1]["value"]
            item["latest_date"] = item["points"][-1]["date"]
    return series_map
