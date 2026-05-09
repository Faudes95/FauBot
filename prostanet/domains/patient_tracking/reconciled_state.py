from __future__ import annotations

from datetime import datetime
from math import log
from typing import Any

from prostanet.shared.metastatic_profile import derive_legacy_metastasis, derive_mhspc_burden_context
from prostanet.shared.systemic_progression import (
    build_progression_gate,
    normalize_castrate_status,
    resolve_systemic_progression_context,
)


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr", "post_radiotherapy_or_local_salvage"}
MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}
OLIGOPROGRESSION_STATES = {"oligoprogression_post_systemic"}
ADVANCED_STATES = {
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
} | MHSPC_STATES | OLIGOPROGRESSION_STATES
CRPC_TRACK_STATES = {"adt_progression_verification", "m0_crpc", "m1_crpc"}

# Variantes histológicas reconocidas. `neuroendocrine` y `small_cell` cambian
# la conducta terapéutica (regímenes con platinos, etc.) y deben dispararse en UI.
HISTOLOGY_VARIANTS = {"acinar", "intraductal", "neuroendocrine", "small_cell", "mixed"}

_SYSTEMIC_TOKENS = (
    "abirater",
    "apalut",
    "enzalut",
    "darolut",
    "bicalut",
    "docetax",
    "cabazitax",
    "leupro",
    "degarel",
    "goserelin",
    "triptorelin",
    "relugolix",
    "olapar",
    "talazop",
    "lutec",
    "pluvicto",
    "orchiect",
    "adt",
)

_ADT_TOKENS = (
    "leupro",
    "degarel",
    "goserelin",
    "triptorelin",
    "relugolix",
    "orchiect",
    "castrat",
    "adt",
)

_ARPI_TOKENS = ("abirater", "apalut", "enzalut", "darolut", "bicalut")
_PARP_TOKENS = ("olapar", "talazop", "parp")
_LU177_TOKENS = ("lutec", "pluvicto", "177lu", "lu177", "radiolig")


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida")


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí"}


def _parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _assessment_state(patient: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> str:
    return (
        (latest_assessment or {}).get("state")
        or (patient.get("latest_assessment") or {}).get("state")
        or (patient.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )


def _biopsy_confirms_cancer(patient: dict[str, Any]) -> bool:
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    positive_cores = _safe_int(latest_biopsy.get("positive_cores")) or 0
    return any(
        _is_present(latest_biopsy.get(field))
        for field in ("gleason_primary", "gleason_secondary", "isup_grade", "positive_cores")
    ) and positive_cores > 0


def _treatment_text(patient: dict[str, Any]) -> str:
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    if _is_present(truth_values.get("current_treatment")):
        return str(truth_values.get("current_treatment"))
    if _is_present(truth_values.get("drug_scheme")):
        return str(truth_values.get("drug_scheme"))
    treatments = patient.get("treatments") or []
    if treatments:
        latest_treatment = treatments[-1]
        regimen = latest_treatment.get("regimen_json")
        if isinstance(regimen, dict) and regimen.get("summary"):
            return str(regimen["summary"])
        if isinstance(regimen, str) and regimen.strip():
            return regimen
        if _is_present(latest_treatment.get("drug_scheme")):
            return str(latest_treatment.get("drug_scheme"))
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    return str(latest_followup.get("current_treatment") or "")


def _has_systemic_treatment(patient: dict[str, Any]) -> bool:
    haystack = _treatment_text(patient).lower()
    if any(token in haystack for token in _SYSTEMIC_TOKENS):
        return True
    treatments = patient.get("treatments") or []
    return any(_safe_int(item.get("line_of_therapy")) not in (None, 0) for item in treatments)


def _has_local_treatment(patient: dict[str, Any]) -> bool:
    return bool(patient.get("surgery")) or bool(patient.get("radiation"))


def _has_post_prostatectomy_context(patient: dict[str, Any]) -> bool:
    if patient.get("surgery"):
        return True
    prior_state = str((patient.get("prior_history") or {}).get("current_state") or "")
    if prior_state == "post_prostatectomy":
        return True
    assessment_state = str((patient.get("latest_assessment") or {}).get("state") or "")
    if assessment_state == "post_prostatectomy":
        return True
    bcr = patient.get("bcr") or {}
    primary_treatment = str(bcr.get("primary_treatment") or "").strip().upper()
    if primary_treatment in {"RP", "POST_RP", "RADICAL PROSTATECTOMY", "PROSTATECTOMY"}:
        return True
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    for source in (
        patient.get("baseline") or {},
        truth_values,
        assessment_inputs,
        bcr,
    ):
        if not isinstance(source, dict):
            continue
        if _safe_bool(source.get("prior_prostatectomy")):
            return True
        if _safe_bool(source.get("post_prostatectomy")):
            return True
        if _safe_bool(source.get("prostatectomy_done")):
            return True
        if _is_present(source.get("rp_date")) or _is_present(source.get("prostatectomy_date")):
            return True
        if _is_present(source.get("pathologic_stage")) or _is_present(source.get("pathological_stage")):
            return True
        if _is_present(source.get("surgery_type")) or _is_present(source.get("margin_location")):
            return True
        if _is_present(source.get("surgical_margin")) or _is_present(source.get("surgical_margin_status")):
            return True
    return False


def _is_metachronous_mhspc(patient: dict[str, Any]) -> bool:
    baseline = patient.get("baseline") or {}
    explicit = str(baseline.get("metachronous_metastasis", "") or "").strip().lower()
    if explicit in {"1", "true", "yes", "si", "sí"}:
        return True
    return _has_local_treatment(patient)


def _resolved_explicit_mhspc_state(patient: dict[str, Any], explicit_state: str) -> str:
    if explicit_state == "mcspc_high_volume":
        return "mcspc_high_volume_metachronous" if _is_metachronous_mhspc(patient) else "mcspc_high_volume_sync"
    return explicit_state


def _derive_adt_context(patient: dict[str, Any], state: str) -> str:
    haystack = _treatment_text(patient).lower()
    if "orchiect" in haystack:
        return "orchiectomy"
    if any(token in haystack for token in _ADT_TOKENS):
        return "medical_adt_continuous"
    if state in ADVANCED_STATES:
        return "medical_adt_continuous"
    return "none"


def _derive_castrate_status(patient: dict[str, Any], state: str) -> str:
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    latest_assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}
    explicit_status = (
        str(truth_values.get("castrate_testosterone_status") or "").strip()
        or str(latest_assessment_inputs.get("castrate_testosterone_status") or "").strip()
        or str(latest_signal_snapshot.get("castrate_testosterone_status") or "").strip()
        or str(stage_payload.get("castrate_testosterone_status") or "").strip()
    )
    latest_testosterone = _safe_float(
        truth_values.get("testosterone")
        or latest_assessment_inputs.get("testosterone_value")
        or latest_assessment_inputs.get("testosterone")
        or latest_signal_snapshot.get("testosterone")
        or stage_payload.get("testosterone_value")
        or stage_payload.get("testosterone")
    )
    if latest_testosterone is None:
        latest_testosterone = _safe_float(latest_followup.get("testosterone_current"))
    if latest_testosterone is None:
        latest_testosterone = _safe_float((patient.get("baseline") or {}).get("testosterone_baseline"))
    castrate_confirmed_flag = (
        truth_values.get("castrate_testosterone_confirmed")
        if truth_values.get("castrate_testosterone_confirmed") not in (None, "")
        else latest_assessment_inputs.get("castrate_testosterone_confirmed")
    )
    if castrate_confirmed_flag in (None, ""):
        castrate_confirmed_flag = latest_signal_snapshot.get("castrate_testosterone_confirmed")
    if castrate_confirmed_flag in (None, ""):
        castrate_confirmed_flag = stage_payload.get("castrate_testosterone_confirmed")
    return normalize_castrate_status(
        explicit_status,
        testosterone_value=latest_testosterone,
        castrate_confirmed_flag=castrate_confirmed_flag,
    )


def _derive_progression_pattern(patient: dict[str, Any], state: str) -> str:
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    explicit_pattern = str(truth_values.get("progression_pattern") or "").strip().lower()
    if explicit_pattern in {"radiographic", "clinical", "biochemical_only", "mixed", "oligoprogression"}:
        return explicit_pattern
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")

    # Oligoprogresión: ≤5 lesiones nuevas/progresivas con resto controlado bajo terapia
    # sistémica. Su detección es prerequisito para terapias dirigidas (SBRT focal,
    # MDT) sin cambiar línea sistémica. Lit: Foster CC et al. JCO 2018; ESTRO/EAU
    # consensus 2021.
    progressing = _safe_int(
        truth_values.get("lesion_count_progressing")
        or latest_followup.get("lesion_count_progressing")
        or truth_values.get("progressing_lesion_count")
    )
    stable = _safe_int(
        truth_values.get("lesion_count_stable")
        or latest_followup.get("lesion_count_stable")
        or truth_values.get("stable_lesion_count")
    )
    if progressing is not None and 0 < progressing <= 5 and (stable or 0) >= 1:
        return "oligoprogression"

    disease_status = str(
        truth_values.get("disease_status")
        or latest_followup.get("disease_status")
        or ""
    ).lower()
    if "oligoprogres" in disease_status or "oligo-progres" in disease_status:
        return "oligoprogression"
    metachronous = _is_metachronous_mhspc(patient)
    if "radiograf" in disease_status:
        return "radiographic"
    if "clinic" in disease_status:
        return "clinical"
    if "bioqu" in disease_status or "psa" in disease_status:
        return "biochemical_only"
    if state in {"m1_crpc"}:
        return "mixed"
    return "biochemical_only"


def _metastatic_context(patient: dict[str, Any]) -> tuple[str, int, bool]:
    baseline = patient.get("baseline") or {}
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    latest_assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}

    metastatic_payload = dict(baseline)
    for source in (
        truth_values,
        latest_assessment_inputs,
        latest_signal_snapshot,
        latest_followup,
        stage_payload,
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if value not in (None, "", [], {}):
                metastatic_payload[key] = value

    metastasis_site, metastasis_count, _ = derive_legacy_metastasis(metastatic_payload)
    metastatic_evidence = metastasis_site not in {"", "M0", "No aplica"}
    conventional_stage = str(truth_values.get("conventional_imaging_status") or "")
    if conventional_stage in {"M1a", "M1b", "M1c"}:
        metastatic_evidence = True
        if conventional_stage == "M1a":
            metastasis_site = "Node"
        elif conventional_stage == "M1b":
            metastasis_site = "Bone"
        elif conventional_stage == "M1c":
            metastasis_site = "Visceral"
    psma_profile = patient.get("psma_structured_profile") or {}
    if psma_profile.get("available") and psma_profile.get("clinical_pattern") != "negative":
        psma_stage = str(psma_profile.get("psma_stage_after_psma") or "")
        lesion_count = _safe_int(psma_profile.get("psma_total_lesions")) or 0
        if psma_stage in {"M1a", "M1b", "M1c"} or lesion_count:
            metastatic_evidence = True
            metastasis_count = max(metastasis_count, lesion_count)
            if psma_stage == "M1a":
                metastasis_site = "Node"
            elif psma_stage == "M1b":
                metastasis_site = "Bone"
            elif psma_stage == "M1c":
                metastasis_site = "Visceral"
            else:
                return metastasis_site or "M1", metastasis_count, metastatic_evidence
    imaging = patient.get("imaging") or []
    for study in imaging:
        study_type = str(study.get("study_type", "")).lower()
        findings = study.get("findings", {}) if isinstance(study.get("findings"), dict) else {}
        if "psma" in study_type:
            locations = findings.get("lesion_locations", []) or []
            lesion_count = _safe_int(findings.get("psma_total_lesions")) or 0
            if locations or lesion_count:
                metastatic_evidence = True
                metastasis_count = max(metastasis_count, lesion_count or len(locations))
                lowered = " ".join(str(item).lower() for item in locations)
                if "hueso" in lowered:
                    metastasis_site = "Bone"
                elif "higado" in lowered or "pulm" in lowered or "visceral" in lowered:
                    metastasis_site = "Visceral"
                elif "ganglio" in lowered:
                    metastasis_site = "Node"
                else:
                    metastasis_site = "M1"
        if "gammagrama" in study_type:
            bone_lesions = _safe_int(study.get("bone_lesion_count")) or _safe_int(findings.get("bone_lesion_count")) or 0
            if bone_lesions:
                metastatic_evidence = True
                metastasis_site = "Bone"
                metastasis_count = max(metastasis_count, bone_lesions)
        if "tac" in study_type:
            summary = str(findings.get("ct_summary") or "")
            locations = findings.get("ct_locations", []) or []
            if summary == "Metástasis" or locations:
                metastatic_evidence = True
                metastasis_count = max(metastasis_count, len(locations) or 1)
                lowered = " ".join(str(item).lower() for item in locations)
                if "hueso" in lowered:
                    metastasis_site = "Bone"
                elif "ganglio" in lowered:
                    metastasis_site = "Node"
                else:
                    metastasis_site = "Visceral"
    return metastasis_site, metastasis_count, metastatic_evidence


def _implicit_confirmed_cancer(patient: dict[str, Any], explicit_state: str) -> bool:
    if _biopsy_confirms_cancer(patient):
        return True
    if explicit_state not in DIAGNOSTIC_STATES:
        return True
    if _has_local_treatment(patient) or bool(patient.get("bcr")):
        return True
    if _has_systemic_treatment(patient):
        return True
    _, _, metastatic_evidence = _metastatic_context(patient)
    return metastatic_evidence


def _post_prostatectomy_date(patient: dict[str, Any]) -> datetime | None:
    surgery = patient.get("surgery") or {}
    bcr = patient.get("bcr") or {}
    prior_history = patient.get("prior_history") or {}
    for candidate in (
        surgery.get("surgery_date"),
        bcr.get("primary_treatment_date"),
        prior_history.get("rp_date"),
        prior_history.get("prostatectomy_date"),
    ):
        parsed = _parse_date(candidate)
        if parsed:
            return parsed
    return None


def _append_post_rp_psa_point(
    points: list[dict[str, Any]],
    *,
    value: Any,
    sample_date: Any,
    source: str,
    rp_date: datetime | None,
) -> None:
    numeric_value = _safe_float(value)
    if numeric_value is None:
        return
    parsed_date = _parse_date(sample_date)
    if rp_date and parsed_date and parsed_date < rp_date:
        return
    point = {
        "value": numeric_value,
        "sample_date": parsed_date.strftime("%Y-%m-%d") if parsed_date else "",
        "source": source,
    }
    if point not in points:
        points.append(point)


def _post_prostatectomy_psa_points(patient: dict[str, Any]) -> list[dict[str, Any]]:
    rp_date = _post_prostatectomy_date(patient)
    points: list[dict[str, Any]] = []
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    bcr = patient.get("bcr") or {}
    latest_assessment_inputs = dict(((patient.get("latest_assessment") or {}).get("input_snapshot") or {}))
    followups = list(patient.get("follow_ups", []) or [])
    biomarker_rows = list(patient.get("biomarker_longitudinal") or [])

    for row in biomarker_rows:
        biomarker_type = str(row.get("biomarker_type") or "").upper()
        if biomarker_type != "PSA":
            continue
        _append_post_rp_psa_point(
            points,
            value=row.get("value"),
            sample_date=row.get("sample_date"),
            source="biomarker_longitudinal",
            rp_date=rp_date,
        )

    for followup in followups:
        for key in ("psa_postop", "psa_current", "psa"):
            _append_post_rp_psa_point(
                points,
                value=followup.get(key),
                sample_date=followup.get("visit_date"),
                source=f"follow_up:{key}",
                rp_date=rp_date,
            )

    for key in ("psa_postop", "psa_current"):
        _append_post_rp_psa_point(
            points,
            value=truth_values.get(key),
            sample_date=((patient.get("longitudinal_truth_snapshot") or {}).get("latest_clinically_decisive_visit") or {}).get("visit_date"),
            source=f"truth:{key}",
            rp_date=rp_date,
        )

    for key in ("psa_postop", "psa_current"):
        _append_post_rp_psa_point(
            points,
            value=latest_assessment_inputs.get(key),
            sample_date=(patient.get("latest_assessment") or {}).get("assessment_date"),
            source=f"assessment:{key}",
            rp_date=rp_date,
        )

    _append_post_rp_psa_point(
        points,
        value=bcr.get("bcr_psa"),
        sample_date=bcr.get("bcr_date"),
        source="bcr",
        rp_date=rp_date,
    )

    def _sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        sample_date = str(item.get("sample_date") or "")
        return (0 if sample_date else 1, sample_date, str(item.get("source") or ""))

    return sorted(points, key=_sort_key)


def _post_prostatectomy_psa_series(patient: dict[str, Any]) -> list[float]:
    return [float(point["value"]) for point in _post_prostatectomy_psa_points(patient)]


def _derive_post_rp_psadt_months(points: list[dict[str, Any]]) -> float | None:
    dated_points = [item for item in points if item.get("sample_date") and _safe_float(item.get("value")) not in (None, 0.0)]
    if len(dated_points) < 2:
        return None
    selected = dated_points[-3:] if len(dated_points) >= 3 else dated_points[-2:]
    xs: list[float] = []
    ys: list[float] = []
    anchor_date = _parse_date(selected[0].get("sample_date"))
    if not anchor_date:
        return None
    for item in selected:
        sample_date = _parse_date(item.get("sample_date"))
        value = _safe_float(item.get("value"))
        if not sample_date or value is None or value <= 0:
            continue
        xs.append(max((sample_date - anchor_date).days, 0) / 30.44)
        ys.append(log(value))
    if len(xs) < 2 or xs[-1] <= xs[0]:
        return None
    if len(xs) == 2:
        slope = (ys[1] - ys[0]) / max(xs[1] - xs[0], 1e-6)
    else:
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator <= 0:
            return None
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    if slope <= 0:
        return None
    return round(log(2) / slope, 1)


def derive_post_prostatectomy_truth(patient: dict[str, Any]) -> dict[str, Any]:
    bcr = patient.get("bcr") or {}
    psa_points = _post_prostatectomy_psa_points(patient)
    psa_series = [float(point["value"]) for point in psa_points]
    structured_bcr_confirmed = _post_prostatectomy_bcr_confirmed(bcr)
    structured_bcr_inconsistency = bool(bcr) and not _safe_bool(bcr.get("bcr_detected")) and structured_bcr_confirmed
    if structured_bcr_confirmed:
        course = "true_bcr"
    elif not psa_series:
        course = "stable_surveillance"
    else:
        nadir_indetectable = any(value <= 0.1 for value in psa_series)
        latest_value = psa_series[-1]
        earliest_value = psa_series[0]
        postoperative_persistence_flag = _safe_bool(
            ((patient.get("baseline") or {}).get("postoperative_psa_persistent"))
            or ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {}).get("postoperative_psa_persistent")
        )
        if latest_value >= 0.2 and nadir_indetectable:
            course = "true_bcr"
        elif postoperative_persistence_flag:
            course = "persistent_psa"
        elif earliest_value >= 0.1 and not nadir_indetectable:
            course = "persistent_psa"
        elif latest_value >= 0.1 and not nadir_indetectable:
            course = "persistent_psa"
        else:
            course = "stable_surveillance"
    return {
        "course": course,
        "psa_points": psa_points,
        "psa_series": psa_series,
        "psa_current": psa_series[-1] if psa_series else None,
        "psadt_months": _derive_post_rp_psadt_months(psa_points),
        "structured_bcr_confirmed": structured_bcr_confirmed,
        "structured_bcr_inconsistency": structured_bcr_inconsistency,
        "rp_date": _post_prostatectomy_date(patient).strftime("%Y-%m-%d") if _post_prostatectomy_date(patient) else "",
    }


def _post_prostatectomy_bcr_confirmed(bcr: dict[str, Any]) -> bool:
    if not isinstance(bcr, dict):
        return False
    if _safe_bool(bcr.get("bcr_detected")):
        return True
    bcr_psa = _safe_float(bcr.get("bcr_psa"))
    if bcr_psa is not None and bcr_psa >= 0.2:
        if any(_is_present(bcr.get(field)) for field in ("bcr_date", "psadt_at_bcr", "salvage_date")):
            return True
        definition = str(bcr.get("bcr_definition") or "").strip().lower()
        if definition and definition not in {"", "none", "unknown", "pendiente"}:
            return True
    if _is_present(bcr.get("salvage_date")):
        return True
    return False


def derive_post_prostatectomy_course(patient: dict[str, Any]) -> str:
    if not _has_post_prostatectomy_context(patient):
        return ""
    return str(derive_post_prostatectomy_truth(patient).get("course") or "stable_surveillance")


def _has_postlocal_bcr(patient: dict[str, Any]) -> bool:
    bcr = patient.get("bcr") or {}
    post_rp_truth = derive_post_prostatectomy_truth(patient) if _has_post_prostatectomy_context(patient) else {}
    has_postlocal_context = _has_post_prostatectomy_context(patient) or bool(patient.get("radiation"))
    prior_state = str((patient.get("prior_history") or {}).get("current_state") or "")
    if prior_state in POSTLOCAL_STATES:
        has_postlocal_context = True
    explicit_bcr_markers = bool(post_rp_truth.get("structured_bcr_confirmed")) or any(
        _is_present(bcr.get(field))
        for field in ("bcr_psa", "psadt_at_bcr", "bcr_definition", "salvage_date", "bcr_date")
    )
    if explicit_bcr_markers and has_postlocal_context:
        return True
    if not has_postlocal_context:
        return False
    if patient.get("surgery"):
        return str(post_rp_truth.get("course") or "") == "true_bcr"
    if any(
        _is_present(bcr.get(field))
        for field in ("bcr_psa", "psadt_at_bcr", "bcr_definition", "salvage_date", "bcr_date")
    ):
        return True
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    psa_value = _safe_float(
        truth_values.get("psa")
        or truth_values.get("psa_postop")
    )
    if psa_value is None:
        latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
        psa_value = _safe_float(
            latest_followup.get("psa_postop")
            or latest_followup.get("psa_current")
        )
    return psa_value is not None and psa_value >= 0.2


def _systemic_target_state(
    patient: dict[str, Any],
    explicit_state: str,
    metastasis_site: str,
    metastasis_count: int,
    metastatic_evidence: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    treatment_text = _treatment_text(patient).lower()
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    burden_payload = dict(patient.get("baseline") or {})
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_assessment_inputs = ((patient.get("latest_assessment") or {}).get("input_snapshot") or {})
    latest_signal_snapshot = patient.get("latest_signal_snapshot") or {}
    latest_stage_visit = _latest(patient.get("stage_visits", []), "visit_date", "created_at", "recorded_at")
    stage_payload = ((latest_stage_visit.get("visit_bundle") or {}).get("payload") or {}) if latest_stage_visit else {}
    for source in (truth_values, latest_assessment_inputs, latest_signal_snapshot, latest_followup, stage_payload):
        if isinstance(source, dict):
            for key, value in source.items():
                if value not in (None, "", [], {}):
                    burden_payload[key] = value
    burden_payload.setdefault("metastasis_site", metastasis_site)
    burden_payload.setdefault("metastasis_count", metastasis_count)
    burden_context = derive_mhspc_burden_context(burden_payload)
    volume_context = str(burden_context.get("volume_disease") or "unknown")
    adt_context = _derive_adt_context(patient, explicit_state)
    castrate_status = _derive_castrate_status(patient, explicit_state)
    progression_pattern = _derive_progression_pattern(patient, explicit_state)
    disease_status = str(latest_followup.get("disease_status") or "").lower()
    explicit_progression = str(truth_values.get("progression_pattern") or "").strip().lower()
    psadt_months = _safe_float(
        truth_values.get("psadt_months")
        or latest_followup.get("psadt_months")
    )
    metachronous = _is_metachronous_mhspc(patient)
    line_of_therapy = (
        _safe_int(truth_values.get("line_of_therapy_number"))
        or _safe_int(truth_values.get("line_of_therapy"))
        or _safe_int(latest_followup.get("line_of_therapy_number"))
        or _safe_int(latest_followup.get("line_of_therapy"))
    )
    explicit_progression_context = (
        truth_values.get("systemic_progression_context")
        or latest_followup.get("systemic_progression_context")
        or ("confirmed_crpc" if explicit_state in {"m0_crpc", "m1_crpc"} else "")
        or ("progression_on_adt_verify_castration" if explicit_state == "adt_progression_verification" else "")
    )
    resolved_systemic_context = resolve_systemic_progression_context(
        explicit_progression_context,
        legacy_crpc_signal=explicit_state in {"m0_crpc", "m1_crpc"},
        line_of_therapy=line_of_therapy,
    )
    biochemical_progression_confirmed = (
        progression_pattern == "biochemical_only"
        and (
            explicit_progression == "biochemical_only"
            or psadt_months is not None
            or any(token in disease_status for token in ("progres", "ascen", "aumento", "bioqu", "psa"))
        )
    )
    phenotype_state = explicit_state
    if explicit_state in {"m0_crpc", "m1_crpc"}:
        phenotype_state = "m1_crpc" if metastatic_evidence else "m0_crpc"
    elif metastatic_evidence:
        if volume_context == "high":
            phenotype_state = "mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"
        elif burden_context.get("oligometastatic_operational") or volume_context == "low" or (metastasis_count and metastasis_count <= 3):
            phenotype_state = "mcspc_oligo_metachronous" if _has_local_treatment(patient) else "mcspc_low_volume_sync_oligo"
        else:
            phenotype_state = "mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"

    if any(token in treatment_text for token in _PARP_TOKENS + _LU177_TOKENS):
        reasons.append("Tratamiento avanzado documentado con PARP / radioligando.")
        phenotype_state = "m1_crpc" if metastatic_evidence else "m0_crpc"
        resolved_systemic_context = "confirmed_crpc"

    if explicit_state in {"m0_crpc", "m1_crpc"}:
        reasons.append("Último assessment ya documenta CRPC.")
        resolved_systemic_context = "confirmed_crpc"

    # Oligoprogresión bajo terapia sistémica con castración: subestado paralelo a
    # CRPC. Permite considerar terapia dirigida focal (SBRT/MDT) sin cambiar la
    # línea sistémica. Se identifica antes del branch CRPC clásico para no
    # colapsar todo a m0/m1_crpc cuando el patrón es realmente oligoprogresivo.
    if castrate_status == "confirmed_castrate" and progression_pattern == "oligoprogression":
        reasons.append("Oligoprogresión (≤5 lesiones progresivas, resto estable) bajo terapia sistémica con castración.")
        phenotype_state = "oligoprogression_post_systemic"
        resolved_systemic_context = "confirmed_crpc"
        return {
            "state": phenotype_state,
            "phenotype_state": phenotype_state,
            "reasons": reasons,
            **build_progression_gate(
                systemic_progression_context=resolved_systemic_context,
                on_adt=adt_context != "none",
                castrate_status=castrate_status,
                progression_pattern=progression_pattern,
                prior_prostatectomy=_has_post_prostatectomy_context(patient),
                prior_radiation=bool(patient.get("radiation")),
                phenotype_state=phenotype_state,
            ),
        }

    if castrate_status == "confirmed_castrate" and progression_pattern in {"radiographic", "clinical", "mixed"}:
        reasons.append("Progresión avanzada con testosterona en rango de castración.")
        phenotype_state = "m1_crpc" if metastatic_evidence else "m0_crpc"
        resolved_systemic_context = "confirmed_crpc"
        return {
            "state": phenotype_state,
            "phenotype_state": phenotype_state,
            "reasons": reasons,
            **build_progression_gate(
                systemic_progression_context=resolved_systemic_context,
                on_adt=adt_context != "none",
                castrate_status=castrate_status,
                progression_pattern=progression_pattern,
                prior_prostatectomy=_has_post_prostatectomy_context(patient),
                prior_radiation=bool(patient.get("radiation")),
                phenotype_state=phenotype_state,
            ),
        }

    if castrate_status == "confirmed_castrate" and biochemical_progression_confirmed:
        if progression_pattern == "biochemical_only":
            reasons.append("Ascenso bioquímico bajo testosterona en rango de castración compatible con carril CRPC.")
        phenotype_state = "m1_crpc" if metastatic_evidence else "m0_crpc"
        resolved_systemic_context = "confirmed_crpc"
        return {
            "state": phenotype_state,
            "phenotype_state": phenotype_state,
            "reasons": reasons,
            **build_progression_gate(
                systemic_progression_context=resolved_systemic_context,
                on_adt=adt_context != "none",
                castrate_status=castrate_status,
                progression_pattern=progression_pattern,
                prior_prostatectomy=_has_post_prostatectomy_context(patient),
                prior_radiation=bool(patient.get("radiation")),
                phenotype_state=phenotype_state,
            ),
        }

    if metastatic_evidence:
        if volume_context == "high":
            reasons.append(str(burden_context.get("volume_reason") or "Enfermedad sistémica con carga compatible con mCSPC de mayor volumen."))
        elif burden_context.get("oligometastatic_operational") or volume_context == "low" or (metastasis_count and metastasis_count <= 3):
            reasons.append("Carga metastásica baja / oligometastásica documentada.")
        else:
            reasons.append("Enfermedad metastásica documentada sin staging longitudinal completo.")
    elif explicit_state in MHSPC_STATES:
        phenotype_state = _resolved_explicit_mhspc_state(patient, explicit_state)
        reasons.append(
            "Se conserva el fenotipo mHSPC explícito del último assessment mientras no exista nueva evidencia estructurada que lo contradiga."
        )
    elif explicit_state in {"m0_crpc", "m1_crpc"}:
        phenotype_state = explicit_state
        resolved_systemic_context = "confirmed_crpc"
        reasons.append(
            "Se conserva el fenotipo CRPC explícito del último assessment mientras no exista nueva evidencia estructurada que lo contradiga."
        )
    elif adt_context != "none" or any(token in treatment_text for token in _ARPI_TOKENS):
        phenotype_state = "adt_progression_verification"
        reasons.append("ADT/ARPI documentados sin staging longitudinal suficiente para subtipo avanzado definitivo.")
    else:
        phenotype_state = "localized_initial"
        reasons.append("Tratamiento oncológico sistémico documentado sin suficiente staging estructurado.")

    progression_gate = build_progression_gate(
        systemic_progression_context=resolved_systemic_context,
        on_adt=adt_context != "none",
        castrate_status=castrate_status,
        progression_pattern=progression_pattern,
        prior_prostatectomy=_has_post_prostatectomy_context(patient),
        prior_radiation=bool(patient.get("radiation")),
        phenotype_state=phenotype_state if phenotype_state in MHSPC_STATES else "",
    )
    if progression_gate.get("progression_gate_active") and (
        phenotype_state in MHSPC_STATES or explicit_state in {"m0_crpc", "m1_crpc"}
    ):
        reasons.append(str(progression_gate.get("progression_gate_reason") or ""))
        resolved_state = phenotype_state
    elif progression_gate.get("progression_gate_active"):
        resolved_state = "adt_progression_verification"
    else:
        resolved_state = phenotype_state
    return {
        "state": resolved_state,
        "phenotype_state": phenotype_state,
        "reasons": reasons,
        **progression_gate,
    }


def build_reconciled_state(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explicit_state = _assessment_state(patient, latest_assessment)
    reconciled_state = explicit_state
    phenotype_state = explicit_state
    reasons: list[str] = []
    progression_gate_active = False
    progression_gate_target = ""
    progression_gate_reason = ""
    systemic_progression_context_resolved = "none"

    has_histology = _biopsy_confirms_cancer(patient)
    has_confirmed_cancer = _implicit_confirmed_cancer(patient, explicit_state)
    has_local_treatment = _has_local_treatment(patient)
    has_bcr = _has_postlocal_bcr(patient)
    post_prostatectomy_truth = derive_post_prostatectomy_truth(patient) if _has_post_prostatectomy_context(patient) else {}
    post_prostatectomy_course = str(post_prostatectomy_truth.get("course") or derive_post_prostatectomy_course(patient))
    has_systemic_treatment = _has_systemic_treatment(patient)
    metastasis_site, metastasis_count, metastatic_evidence = _metastatic_context(patient)

    if explicit_state in DIAGNOSTIC_STATES:
        if has_systemic_treatment:
            systemic_resolution = _systemic_target_state(
                patient,
                explicit_state,
                metastasis_site,
                metastasis_count,
                metastatic_evidence,
            )
            reconciled_state = systemic_resolution.get("state") or explicit_state
            phenotype_state = systemic_resolution.get("phenotype_state") or reconciled_state
            reasons.extend(systemic_resolution.get("reasons") or [])
            progression_gate_active = bool(systemic_resolution.get("progression_gate_active"))
            progression_gate_target = str(systemic_resolution.get("progression_gate_target") or "")
            progression_gate_reason = str(systemic_resolution.get("progression_gate_reason") or "")
            systemic_progression_context_resolved = str(systemic_resolution.get("systemic_progression_context_resolved") or "none")
        elif has_bcr or has_local_treatment:
            reconciled_state = "recurrence_bcr" if has_bcr else "post_prostatectomy"
            phenotype_state = reconciled_state
            reasons.append("El longitudinal ya documenta tratamiento local previo / recurrencia.")
        elif has_histology or has_confirmed_cancer:
            reconciled_state = "localized_initial"
            phenotype_state = reconciled_state
            reasons.append("Existe evidencia longitudinal de cáncer confirmado fuera del carril diagnóstico.")
    elif explicit_state == "localized_initial" and has_systemic_treatment:
        systemic_resolution = _systemic_target_state(
            patient,
            explicit_state,
            metastasis_site,
            metastasis_count,
            metastatic_evidence,
        )
        reconciled_state = systemic_resolution.get("state") or explicit_state
        phenotype_state = systemic_resolution.get("phenotype_state") or reconciled_state
        reasons.extend(systemic_resolution.get("reasons") or [])
        progression_gate_active = bool(systemic_resolution.get("progression_gate_active"))
        progression_gate_target = str(systemic_resolution.get("progression_gate_target") or "")
        progression_gate_reason = str(systemic_resolution.get("progression_gate_reason") or "")
        systemic_progression_context_resolved = str(systemic_resolution.get("systemic_progression_context_resolved") or "none")
    elif explicit_state in POSTLOCAL_STATES and has_systemic_treatment:
        systemic_resolution = _systemic_target_state(
            patient,
            explicit_state,
            metastasis_site,
            metastasis_count,
            metastatic_evidence,
        )
        reconciled_state = systemic_resolution.get("state") or explicit_state
        phenotype_state = systemic_resolution.get("phenotype_state") or reconciled_state
        reasons.extend(systemic_resolution.get("reasons") or [])
        progression_gate_active = bool(systemic_resolution.get("progression_gate_active"))
        progression_gate_target = str(systemic_resolution.get("progression_gate_target") or "")
        progression_gate_reason = str(systemic_resolution.get("progression_gate_reason") or "")
        systemic_progression_context_resolved = str(systemic_resolution.get("systemic_progression_context_resolved") or "none")
    elif explicit_state == "post_prostatectomy" and post_prostatectomy_course == "true_bcr":
        reconciled_state = "recurrence_bcr"
        phenotype_state = reconciled_state
        reasons.append("El PSA longitudinal posprostatectomía ya cumple criterio operativo de recurrencia bioquímica y debe pasar a carril de salvage.")
    elif explicit_state in MHSPC_STATES | CRPC_TRACK_STATES:
        systemic_resolution = _systemic_target_state(
            patient,
            explicit_state,
            metastasis_site,
            metastasis_count,
            metastatic_evidence,
        )
        reconciled_state = systemic_resolution.get("state") or explicit_state
        phenotype_state = systemic_resolution.get("phenotype_state") or reconciled_state
        reasons.extend(systemic_resolution.get("reasons") or [])
        progression_gate_active = bool(systemic_resolution.get("progression_gate_active"))
        progression_gate_target = str(systemic_resolution.get("progression_gate_target") or "")
        progression_gate_reason = str(systemic_resolution.get("progression_gate_reason") or "")
        systemic_progression_context_resolved = str(systemic_resolution.get("systemic_progression_context_resolved") or "none")
    else:
        phenotype_state = reconciled_state

    from prostanet.domains.patient_tracking.followup_agenda import infer_management_track

    raw_assessment = latest_assessment or patient.get("latest_assessment")
    reconciled_track = infer_management_track(patient, reconciled_state, raw_assessment)
    conflict_flag = reconciled_state != explicit_state
    if conflict_flag and not reasons:
        reasons.append("La evolución longitudinal contradice el último assessment persistido.")

    if conflict_flag and explicit_state in DIAGNOSTIC_STATES and has_systemic_treatment:
        reasons.insert(0, "Hay tratamiento sistémico documentado en follow-up, por lo que el caso no puede permanecer en triage diagnóstico.")

    return {
        "explicit_state": explicit_state,
        "reconciled_state": reconciled_state,
        "phenotype_state": phenotype_state,
        "reconciled_management_track": reconciled_track,
        "state_conflict_flag": conflict_flag,
        "state_conflict_reason": " ".join(dict.fromkeys(reason for reason in reasons if reason)).strip(),
        "progression_gate_active": progression_gate_active,
        "progression_gate_target": progression_gate_target,
        "progression_gate_reason": progression_gate_reason,
        "systemic_progression_context_resolved": systemic_progression_context_resolved,
        "supporting_evidence": {
            "confirmed_cancer": has_confirmed_cancer,
            "histology_confirmed": has_histology,
            "local_treatment_documented": has_local_treatment,
            "systemic_treatment_documented": has_systemic_treatment,
            "metastatic_evidence": metastatic_evidence,
            "metastasis_site": metastasis_site,
            "metastasis_count": metastasis_count,
            "bcr_documented": has_bcr,
            "post_prostatectomy_course": post_prostatectomy_course,
            "post_prostatectomy_psadt_months": post_prostatectomy_truth.get("psadt_months"),
            "post_prostatectomy_psa_current": post_prostatectomy_truth.get("psa_current"),
            "post_prostatectomy_structured_bcr_inconsistency": post_prostatectomy_truth.get("structured_bcr_inconsistency"),
            "phenotype_state": phenotype_state,
            "progression_gate_active": progression_gate_active,
            "progression_gate_reason": progression_gate_reason,
            "systemic_progression_context_resolved": systemic_progression_context_resolved,
        },
    }


__all__ = [
    "ADVANCED_STATES",
    "CRPC_TRACK_STATES",
    "DIAGNOSTIC_STATES",
    "MHSPC_STATES",
    "POSTLOCAL_STATES",
    "build_reconciled_state",
    "derive_post_prostatectomy_truth",
    "derive_post_prostatectomy_course",
]
