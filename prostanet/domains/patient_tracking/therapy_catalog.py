from __future__ import annotations

from copy import deepcopy
from typing import Any


ADVANCED_STATE_SCOPE = [
    "adt_progression_verification",
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume",
    "m0_crpc",
    "m1_crpc",
    "advanced",
]

THERAPY_CLASS_LABELS = {
    "observation": "Observación / sin sistémico",
    "androgen_axis": "Eje androgénico",
    "triplet": "Tripletes / intensificación",
    "taxane": "Taxanos",
    "parp": "PARP / precisión",
    "radioligand": "Radioligandos / radiofármacos",
    "immunotherapy": "Inmunoterapia",
}

THERAPY_CLASS_ORDER = {
    "observation": 0,
    "androgen_axis": 1,
    "triplet": 2,
    "taxane": 3,
    "parp": 4,
    "radioligand": 5,
    "immunotherapy": 6,
}

THERAPY_REGIMENS = [
    {
        "regimen_code": "ADT_MONO",
        "label_clinico": "ADT sola",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": [
            "mHSPC_initial",
            "mHSPC_post_docetaxel",
            "m0_CRPC_first_line",
            "mCRPC_first_line",
            "mCRPC_post_ARPI_pre_taxane",
            "mCRPC_post_taxane",
            "later_line",
        ],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT"],
        "evidence_tags": ["backbone", "legacy"],
    },
    {
        "regimen_code": "ADT_ABIRATERONE",
        "label_clinico": "ADT + abiraterona",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT", "Abiraterona"],
        "evidence_tags": ["LATITUDE", "PEACE-1"],
    },
    {
        "regimen_code": "ADT_ENZALUTAMIDE",
        "label_clinico": "ADT + enzalutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT", "Enzalutamida"],
        "evidence_tags": ["ARCHES", "ENZAMET"],
    },
    {
        "regimen_code": "ADT_APALUTAMIDE",
        "label_clinico": "ADT + apalutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "later_line"],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT", "Apalutamida"],
        "evidence_tags": ["TITAN"],
    },
    {
        "regimen_code": "ADT_DAROLUTAMIDE",
        "label_clinico": "ADT + darolutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "later_line"],
        "therapy_class": "androgen_axis",
        "contains_adt": True,
        "agents": ["ADT", "Darolutamida"],
        "evidence_tags": ["ARANOTE"],
    },
    {
        "regimen_code": "ADT_DOCETAXEL",
        "label_clinico": "ADT + docetaxel",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "triplet",
        "contains_adt": True,
        "agents": ["ADT", "Docetaxel"],
        "evidence_tags": ["CHAARTED", "STAMPEDE"],
    },
    {
        "regimen_code": "ADT_DOCETAXEL_DAROLUTAMIDE",
        "label_clinico": "ADT + docetaxel + darolutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "later_line"],
        "therapy_class": "triplet",
        "contains_adt": True,
        "agents": ["ADT", "Docetaxel", "Darolutamida"],
        "evidence_tags": ["ARASENS"],
    },
    {
        "regimen_code": "ADT_DOCETAXEL_ABIRATERONE",
        "label_clinico": "ADT + docetaxel + abiraterona",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mHSPC_initial", "later_line"],
        "therapy_class": "triplet",
        "contains_adt": True,
        "agents": ["ADT", "Docetaxel", "Abiraterona"],
        "evidence_tags": ["PEACE-1"],
    },
    {
        "regimen_code": "DOCETAXEL",
        "label_clinico": "Docetaxel",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "taxane",
        "contains_adt": False,
        "agents": ["Docetaxel"],
        "evidence_tags": ["TAX327"],
    },
    {
        "regimen_code": "CABAZITAXEL",
        "label_clinico": "Cabazitaxel",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_docetaxel", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "taxane",
        "contains_adt": False,
        "agents": ["Cabazitaxel"],
        "evidence_tags": ["CARD", "TROPIC"],
    },
    {
        "regimen_code": "OLAPARIB",
        "label_clinico": "Olaparib",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_parp", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_ARPI_pre_taxane", "mCRPC_post_taxane", "later_line"],
        "therapy_class": "parp",
        "contains_adt": False,
        "agents": ["Olaparib"],
        "evidence_tags": ["PROfound"],
    },
    {
        "regimen_code": "TALAZOPARIB_ENZALUTAMIDE",
        "label_clinico": "Talazoparib + enzalutamida",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_parp", "on_arpi", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_first_line", "mCRPC_post_ARPI_pre_taxane", "later_line"],
        "therapy_class": "parp",
        "contains_adt": False,
        "agents": ["Talazoparib", "Enzalutamida"],
        "evidence_tags": ["TALAPRO-2"],
    },
    {
        "regimen_code": "LU177_PSMA617",
        "label_clinico": "Lutecio-177 PSMA-617",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_lu177", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "mCRPC_post_Lu177", "later_line"],
        "therapy_class": "radioligand",
        "contains_adt": False,
        "agents": ["Lu177-PSMA-617"],
        "evidence_tags": ["VISION", "PSMAfore"],
    },
    {
        "regimen_code": "RADIUM223",
        "label_clinico": "Radio-223",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["on_lu177", "systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "radioligand",
        "contains_adt": False,
        "agents": ["Radio-223"],
        "evidence_tags": ["ALSYMPCA"],
    },
    {
        "regimen_code": "PEMBROLIZUMAB",
        "label_clinico": "Pembrolizumab",
        "state_scope": ADVANCED_STATE_SCOPE,
        "management_tracks": ["systemic_surveillance", "palliative_overlay"],
        "line_contexts": ["mCRPC_post_taxane", "later_line"],
        "therapy_class": "immunotherapy",
        "contains_adt": False,
        "agents": ["Pembrolizumab"],
        "evidence_tags": ["MSI-H", "TMB-high"],
    },
]

REGIMEN_LOOKUP = {item["regimen_code"]: item for item in THERAPY_REGIMENS}
REGIMEN_LABEL_LOOKUP = {item["regimen_code"]: item["label_clinico"] for item in THERAPY_REGIMENS}

REGIMEN_ALIASES = {
    "adt mono": "ADT_MONO",
    "solo adt": "ADT_MONO",
    "solo terapia de privacion androgenica": "ADT_MONO",
    "solo terapia de privación androgénica": "ADT_MONO",
    "adt + abiraterona": "ADT_ABIRATERONE",
    "abiraterona + adt": "ADT_ABIRATERONE",
    "abiraterone + adt": "ADT_ABIRATERONE",
    "adt + abiraterone": "ADT_ABIRATERONE",
    "adt + enzalutamida": "ADT_ENZALUTAMIDE",
    "enzalutamida + adt": "ADT_ENZALUTAMIDE",
    "adt + enzalutamide": "ADT_ENZALUTAMIDE",
    "enzalutamide + adt": "ADT_ENZALUTAMIDE",
    "adt + apalutamida": "ADT_APALUTAMIDE",
    "apalutamida + adt": "ADT_APALUTAMIDE",
    "adt + apalutamide": "ADT_APALUTAMIDE",
    "apalutamide + adt": "ADT_APALUTAMIDE",
    "adt + darolutamida": "ADT_DAROLUTAMIDE",
    "darolutamida + adt": "ADT_DAROLUTAMIDE",
    "adt + darolutamide": "ADT_DAROLUTAMIDE",
    "darolutamide + adt": "ADT_DAROLUTAMIDE",
    "adt + docetaxel": "ADT_DOCETAXEL",
    "docetaxel + adt": "ADT_DOCETAXEL",
    "adt + docetaxel + darolutamida": "ADT_DOCETAXEL_DAROLUTAMIDE",
    "docetaxel + darolutamida + adt": "ADT_DOCETAXEL_DAROLUTAMIDE",
    "adt + docetaxel + abiraterona": "ADT_DOCETAXEL_ABIRATERONE",
    "docetaxel + abiraterona + adt": "ADT_DOCETAXEL_ABIRATERONE",
    "docetaxel": "DOCETAXEL",
    "cabazitaxel": "CABAZITAXEL",
    "olaparib": "OLAPARIB",
    "talazoparib + enzalutamida": "TALAZOPARIB_ENZALUTAMIDE",
    "talazoparib + enzalutamide": "TALAZOPARIB_ENZALUTAMIDE",
    "lutecio-177 psma-617": "LU177_PSMA617",
    "lu177 psma617": "LU177_PSMA617",
    "lu177_psma617": "LU177_PSMA617",
    "lu177_psma-617": "LU177_PSMA617",
    "lu177_psma617": "LU177_PSMA617",
    "lu177_psma-617": "LU177_PSMA617",
    "lu177": "LU177_PSMA617",
    "pluvicto": "LU177_PSMA617",
    "radio-223": "RADIUM223",
    "radium-223": "RADIUM223",
    "radium223": "RADIUM223",
    "pembrolizumab": "PEMBROLIZUMAB",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().replace("_", " ").replace("-", " ").lower()


def therapy_catalog_entries() -> list[dict[str, Any]]:
    return deepcopy(THERAPY_REGIMENS)


def regimen_label(regimen_code: Any) -> str:
    normalized = normalize_regimen_code(regimen_code)
    if normalized in REGIMEN_LABEL_LOOKUP:
        return REGIMEN_LABEL_LOOKUP[normalized]
    return str(regimen_code or "")


def normalize_regimen_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in REGIMEN_LOOKUP:
        return text
    upper_text = text.upper()
    if upper_text in REGIMEN_LOOKUP:
        return upper_text

    normalized = _normalize_text(text)
    if normalized in REGIMEN_ALIASES:
        return REGIMEN_ALIASES[normalized]
    if text in REGIMEN_LABEL_LOOKUP.values():
        for regimen_code, label in REGIMEN_LABEL_LOOKUP.items():
            if label == text:
                return regimen_code

    fuzzy_tokens = {
        "abirater": "ADT_ABIRATERONE",
        "enzalut": "ADT_ENZALUTAMIDE",
        "apalut": "ADT_APALUTAMIDE",
        "darolut": "ADT_DAROLUTAMIDE",
        "cabazit": "CABAZITAXEL",
        "docetax": "DOCETAXEL",
        "olapar": "OLAPARIB",
        "talazopar": "TALAZOPARIB_ENZALUTAMIDE",
        "pembro": "PEMBROLIZUMAB",
        "pluvicto": "LU177_PSMA617",
        "lutec": "LU177_PSMA617",
        "lu177": "LU177_PSMA617",
        "radium": "RADIUM223",
    }
    for token, regimen_code in fuzzy_tokens.items():
        if token in normalized:
            if regimen_code == "DOCETAXEL" and "adt" in normalized:
                return "ADT_DOCETAXEL"
            return regimen_code
    if "adt" in normalized:
        return "ADT_MONO"
    return text


def therapy_select_options(
    *,
    state: str | None = None,
    management_track: str | None = None,
    line_context: str | None = None,
    include_empty: bool = True,
) -> list[dict[str, Any]]:
    state_key = str(state or "").strip()
    track_key = str(management_track or "").strip()
    line_key = str(line_context or "").strip()
    options: list[dict[str, Any]] = []
    if include_empty:
        options.append(
            {
                "value": "",
                "label": "Sin esquema sistémico confirmado",
                "group": THERAPY_CLASS_LABELS["observation"],
                "therapy_class": "observation",
                "state_scope": ADVANCED_STATE_SCOPE,
                "management_tracks": [],
                "line_contexts": [],
                "contains_adt": False,
                "agents": [],
                "evidence_tags": [],
            }
        )

    filtered = []
    for item in THERAPY_REGIMENS:
        state_ok = not state_key or state_key in item["state_scope"] or ("advanced" in item["state_scope"] and state_key in ADVANCED_STATE_SCOPE)
        track_ok = not track_key or not item["management_tracks"] or track_key in item["management_tracks"]
        if not (state_ok and track_ok):
            continue
        filtered.append(item)

    def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        context_match = 0
        if line_key:
            contexts = item.get("line_contexts") or []
            if line_key in contexts:
                context_match = -1
        return (
            THERAPY_CLASS_ORDER.get(item.get("therapy_class", ""), 99),
            context_match,
            str(item.get("label_clinico") or item.get("regimen_code") or ""),
        )

    for item in sorted(filtered, key=sort_key):
        options.append(
            {
                "value": item["regimen_code"],
                "label": item["label_clinico"],
                "group": THERAPY_CLASS_LABELS.get(item["therapy_class"], item["therapy_class"]),
                "therapy_class": item["therapy_class"],
                "state_scope": deepcopy(item["state_scope"]),
                "management_tracks": deepcopy(item["management_tracks"]),
                "line_contexts": deepcopy(item["line_contexts"]),
                "contains_adt": bool(item["contains_adt"]),
                "agents": deepcopy(item["agents"]),
                "evidence_tags": deepcopy(item["evidence_tags"]),
            }
        )
    return options
