from __future__ import annotations

import json
from typing import Any


NONREGIONAL_NODAL_SITE_LABELS: dict[str, str] = {
    "retroperitoneal": "Retroperitoneales",
    "mediastinal": "Mediastinales",
    "supraclavicular": "Supraclaviculares",
    "inguinal": "Inguinales",
    "other": "Otro sitio ganglionar",
}

BONE_SITE_LABELS: dict[str, str] = {
    "skull": "Cráneo",
    "cervical_spine": "Columna cervical",
    "thoracic_spine": "Columna torácica",
    "lumbar_spine": "Columna lumbar",
    "ribs_thorax": "Costillas / tórax",
    "pelvis_sacrum": "Pelvis / sacro",
    "humerus": "Húmero",
    "forearm": "Radio / cúbito",
    "femur": "Fémur",
    "tibia_fibula": "Tibia / peroné",
    "hand": "Mano",
    "foot": "Pie",
}

AXIAL_BONE_SITE_KEYS = (
    "skull",
    "cervical_spine",
    "thoracic_spine",
    "lumbar_spine",
    "ribs_thorax",
    "pelvis_sacrum",
)

APPENDICULAR_BONE_SITE_KEYS = (
    "humerus",
    "forearm",
    "femur",
    "tibia_fibula",
    "hand",
    "foot",
)

VISCERAL_SITE_LABELS: dict[str, str] = {
    "lung": "Pulmón",
    "liver": "Hígado",
    "brain": "Cerebro",
    "adrenal": "Suprarrenal",
    "pleura": "Pleura",
    "peritoneum": "Peritoneo",
    "other": "Otro visceral",
}

NONREGIONAL_NODAL_COUNT_FIELDS = tuple(f"nonregional_nodal_{key}_count" for key in NONREGIONAL_NODAL_SITE_LABELS)
BONE_COUNT_FIELDS = tuple(f"bone_{key}_count" for key in BONE_SITE_LABELS)
VISCERAL_COUNT_FIELDS = tuple(f"visceral_{key}_count" for key in VISCERAL_SITE_LABELS)

METASTATIC_PROFILE_FIELD_NAMES = (
    "nonregional_nodal_metastasis_present",
    "nonregional_nodal_count",
    "nonregional_nodal_sites",
    "bone_metastasis_present",
    "bone_axial_count",
    "bone_appendicular_count",
    "bone_sites",
    "visceral_metastasis_present",
    "visceral_sites",
    "visceral_lesion_count",
    "metastatic_total_lesion_count",
    "metastasis_assessment_date",
    "metastasis_document_source",
    "metastasis_volume_context",
    "m_substage_resolved",
    "metastatic_profile_json",
    "visceral_other_label",
    "nonregional_nodal_other_label",
) + NONREGIONAL_NODAL_COUNT_FIELDS + BONE_COUNT_FIELDS + VISCERAL_COUNT_FIELDS


def _parse_json_blob(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _is_truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "si", "sí", "on", "positivo", "present"}


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


def _normalize_list(value: Any) -> list[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if _is_present(item)]
    parsed = _parse_json_blob(value, None)
    if isinstance(parsed, list):
        return [item for item in parsed if _is_present(item)]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _summarize_sites(entries: list[dict[str, Any]]) -> str:
    parts = []
    for item in entries:
        count = _safe_int(item.get("lesion_count"), 0)
        if count <= 0:
            continue
        label = str(item.get("label") or item.get("site") or "").strip()
        if not label:
            continue
        parts.append(f"{count} {label}")
    return ", ".join(parts)


def _site_entries_from_counts(
    data: dict[str, Any],
    prefix: str,
    labels: dict[str, str],
    *,
    other_label_field: str | None = None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for key, default_label in labels.items():
        field_name = f"{prefix}_{key}_count"
        count = _safe_int(data.get(field_name), 0)
        if count <= 0:
            continue
        label = default_label
        if key == "other" and other_label_field and _is_present(data.get(other_label_field)):
            label = str(data.get(other_label_field)).strip()
        entries.append(
            {
                "site": key,
                "label": label,
                "lesion_count": count,
                "source": data.get("metastasis_document_source") or "",
                "date": data.get("metastasis_assessment_date") or data.get("visit_date") or data.get("study_date") or "",
            }
        )
    return entries


def _legacy_m_site(data: dict[str, Any]) -> tuple[str, int]:
    raw_site = str(data.get("metastasis_site") or "M0").strip()
    count = _safe_int(data.get("metastasis_count"), 0)
    if raw_site and raw_site not in {"M0", "No aplica"} and count == 0:
        count = 1
    if raw_site in {"Hueso", "Óseo", "Oseo"}:
        raw_site = "Bone"
    elif raw_site in {"Ganglio", "Ganglionar"}:
        raw_site = "Node"
    elif raw_site in {"Visceral"}:
        raw_site = "Visceral"
    return raw_site or "M0", count


def build_metastatic_profile(data: dict[str, Any] | None) -> dict[str, Any]:
    data = data or {}
    existing = data.get("metastatic_profile")
    if not existing:
        existing = _parse_json_blob(data.get("metastatic_profile_json"), {})
    if not isinstance(existing, dict):
        existing = {}

    nodal_sites = _site_entries_from_counts(
        data,
        "nonregional_nodal",
        NONREGIONAL_NODAL_SITE_LABELS,
        other_label_field="nonregional_nodal_other_label",
    ) or list(existing.get("nonregional_nodal_sites") or [])
    bone_sites = _site_entries_from_counts(data, "bone", BONE_SITE_LABELS) or list(existing.get("bone_sites") or [])
    visceral_sites = _site_entries_from_counts(
        data,
        "visceral",
        VISCERAL_SITE_LABELS,
        other_label_field="visceral_other_label",
    ) or list(existing.get("visceral_sites") or [])

    legacy_site, legacy_count = _legacy_m_site(data)

    nonregional_nodal_count = _safe_int(data.get("nonregional_nodal_count"), 0) or sum(
        _safe_int(item.get("lesion_count"), 0) for item in nodal_sites
    )
    bone_axial_count = _safe_int(data.get("bone_axial_count"), 0) or sum(
        _safe_int(data.get(f"bone_{key}_count"), 0) for key in AXIAL_BONE_SITE_KEYS
    )
    if bone_axial_count <= 0:
        bone_axial_count = sum(
            _safe_int(item.get("lesion_count"), 0)
            for item in bone_sites
            if item.get("site") in AXIAL_BONE_SITE_KEYS
        )
    bone_appendicular_count = _safe_int(data.get("bone_appendicular_count"), 0) or sum(
        _safe_int(data.get(f"bone_{key}_count"), 0) for key in APPENDICULAR_BONE_SITE_KEYS
    )
    if bone_appendicular_count <= 0:
        bone_appendicular_count = sum(
            _safe_int(item.get("lesion_count"), 0)
            for item in bone_sites
            if item.get("site") in APPENDICULAR_BONE_SITE_KEYS
        )
    visceral_lesion_count = _safe_int(data.get("visceral_lesion_count"), 0) or sum(
        _safe_int(item.get("lesion_count"), 0) for item in visceral_sites
    )

    nonregional_nodal_present = _is_truthy(data.get("nonregional_nodal_metastasis_present")) or nonregional_nodal_count > 0
    bone_present = _is_truthy(data.get("bone_metastasis_present")) or bone_axial_count + bone_appendicular_count > 0
    visceral_present = _is_truthy(data.get("visceral_metastasis_present")) or visceral_lesion_count > 0

    truth_status = "missing"
    if any(_is_present(data.get(name)) for name in METASTATIC_PROFILE_FIELD_NAMES):
        truth_status = "captured"
    elif existing:
        truth_status = str(existing.get("metastatic_truth_status") or "captured")
    elif legacy_site not in {"", "M0", "No aplica"}:
        truth_status = "derived"

    if not (nonregional_nodal_present or bone_present or visceral_present):
        if legacy_site == "Visceral":
            visceral_present = True
            visceral_lesion_count = max(legacy_count, 1)
        elif legacy_site == "Bone":
            bone_present = True
            bone_axial_count = max(bone_axial_count, legacy_count)
        elif legacy_site == "Node":
            nonregional_nodal_present = True
            nonregional_nodal_count = max(nonregional_nodal_count, legacy_count)

    if visceral_present:
        m_substage = "M1c"
    elif bone_present:
        m_substage = "M1b"
    elif nonregional_nodal_present:
        m_substage = "M1a"
    elif legacy_site not in {"", "M0", "No aplica"}:
        m_substage = "M1"
    else:
        m_substage = "M0"

    total_count = _safe_int(data.get("metastatic_total_lesion_count"), 0)
    if total_count <= 0:
        total_count = max(
            legacy_count,
            nonregional_nodal_count + bone_axial_count + bone_appendicular_count + visceral_lesion_count,
        )
        if m_substage.startswith("M1") and total_count == 0:
            total_count = 1

    if m_substage == "M1c":
        legacy_metastasis_site = "Visceral"
    elif m_substage == "M1b":
        legacy_metastasis_site = "Bone"
    elif m_substage == "M1a":
        legacy_metastasis_site = "Node"
    elif m_substage == "M1":
        legacy_metastasis_site = "M1"
    else:
        legacy_metastasis_site = "M0"

    volume_context = str(data.get("metastasis_volume_context") or data.get("volume_disease") or "").strip()
    if not volume_context:
        volume_context = "High" if visceral_present or total_count >= 4 else ("Low" if m_substage.startswith("M1") else "")

    profile = {
        "m_substage_resolved": m_substage,
        "regional_nodal_metastasis_present": _is_truthy(data.get("regional_nodal_metastasis_present")),
        "nonregional_nodal_metastasis_present": nonregional_nodal_present,
        "nonregional_nodal_sites": nodal_sites,
        "nonregional_nodal_count": nonregional_nodal_count,
        "bone_metastasis_present": bone_present,
        "bone_axial_count": bone_axial_count,
        "bone_appendicular_count": bone_appendicular_count,
        "bone_sites": bone_sites,
        "visceral_metastasis_present": visceral_present,
        "visceral_sites": visceral_sites,
        "visceral_lesion_count": visceral_lesion_count,
        "metastatic_total_lesion_count": total_count,
        "metastasis_assessment_date": data.get("metastasis_assessment_date") or data.get("visit_date") or data.get("study_date") or existing.get("metastasis_assessment_date") or "",
        "metastasis_document_source": data.get("metastasis_document_source") or existing.get("metastasis_document_source") or "",
        "metastasis_volume_context": volume_context,
        "metastatic_truth_status": truth_status,
        "legacy_metastasis_site": legacy_metastasis_site,
        "legacy_metastasis_count": total_count,
        "metastatic_site_summary": {
            "nonregional_nodes": _summarize_sites(nodal_sites),
            "bone": _summarize_sites(bone_sites),
            "visceral": _summarize_sites(visceral_sites),
        },
    }
    profile["metastatic_burden_summary"] = summarize_metastatic_profile(profile)
    return profile


def summarize_metastatic_profile(profile: dict[str, Any] | None) -> str:
    profile = profile or {}
    if str(profile.get("m_substage_resolved") or "M0") == "M0":
        return "Sin metástasis a distancia documentadas"

    parts: list[str] = []
    nodal_summary = ((profile.get("metastatic_site_summary") or {}).get("nonregional_nodes") or "").strip()
    bone_summary = ((profile.get("metastatic_site_summary") or {}).get("bone") or "").strip()
    visceral_summary = ((profile.get("metastatic_site_summary") or {}).get("visceral") or "").strip()

    if nodal_summary:
        parts.append(f"ganglios no regionales: {nodal_summary}")
    elif profile.get("nonregional_nodal_metastasis_present"):
        parts.append(f"ganglios no regionales: {profile.get('nonregional_nodal_count') or 1}")
    if bone_summary:
        parts.append(f"hueso: {bone_summary}")
    elif profile.get("bone_metastasis_present"):
        parts.append(
            "hueso: "
            f"axial {profile.get('bone_axial_count') or 0}, "
            f"apendicular {profile.get('bone_appendicular_count') or 0}"
        )
    if visceral_summary:
        parts.append(f"víscera: {visceral_summary}")
    elif profile.get("visceral_metastasis_present"):
        parts.append(f"víscera: {profile.get('visceral_lesion_count') or 1}")

    if not parts:
        return "Metástasis a distancia sin subtipo anatómico completo"
    return " · ".join(parts)


def derive_legacy_metastasis(data: dict[str, Any] | None) -> tuple[str, int, str]:
    profile = build_metastatic_profile(data)
    return (
        str(profile.get("legacy_metastasis_site") or "M0"),
        _safe_int(profile.get("legacy_metastasis_count"), 0),
        str(profile.get("m_substage_resolved") or "M0"),
    )


def derive_mhspc_volume_context(data: dict[str, Any] | None) -> str:
    data = data or {}
    explicit = str(data.get("volume_disease") or "").strip().lower()
    if explicit in {"high", "low"}:
        return explicit

    profile = build_metastatic_profile(data)
    profile_volume = str(profile.get("metastasis_volume_context") or "").strip().lower()
    if profile_volume in {"high", "low"}:
        return profile_volume

    m_substage = str(profile.get("m_substage_resolved") or "M0").upper()
    total_bone = _safe_int(profile.get("bone_axial_count"), 0) + _safe_int(profile.get("bone_appendicular_count"), 0)
    total_lesions = _safe_int(profile.get("metastatic_total_lesion_count"), 0)
    if m_substage == "M1C":
        return "high"
    if total_bone >= 4:
        return "high"
    if m_substage in {"M1A", "M1B"} and total_lesions > 0:
        return "low"
    return "unknown"
