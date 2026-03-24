from __future__ import annotations

from typing import Any

from prostanet.shared.metastatic_profile import derive_legacy_metastasis, derive_mhspc_volume_context


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr"}
MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}
ADVANCED_STATES = {
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
} | MHSPC_STATES
CRPC_TRACK_STATES = {"adt_progression_verification", "m0_crpc", "m1_crpc"}

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
    explicit_status = str(truth_values.get("castrate_testosterone_status") or "").strip()
    if explicit_status in {"confirmed_castrate", "not_castrate"}:
        return explicit_status
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_testosterone = _safe_float(truth_values.get("testosterone"))
    if latest_testosterone is None:
        latest_testosterone = _safe_float(latest_followup.get("testosterone_current"))
    if latest_testosterone is None:
        latest_testosterone = _safe_float((patient.get("baseline") or {}).get("testosterone_baseline"))
    if latest_testosterone is None:
        return "unknown"
    return "confirmed_castrate" if latest_testosterone <= 50 else "not_castrate"


def _derive_progression_pattern(patient: dict[str, Any], state: str) -> str:
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
    explicit_pattern = str(truth_values.get("progression_pattern") or "").strip().lower()
    if explicit_pattern in {"radiographic", "clinical", "biochemical_only", "mixed"}:
        return explicit_pattern
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    disease_status = str(
        truth_values.get("disease_status")
        or latest_followup.get("disease_status")
        or ""
    ).lower()
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
    metastasis_site, metastasis_count, _ = derive_legacy_metastasis(baseline)
    metastatic_evidence = metastasis_site not in {"", "M0", "No aplica"}
    truth = patient.get("longitudinal_truth_snapshot") or {}
    truth_values = truth.get("field_values") or {}
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


def _post_prostatectomy_psa_series(patient: dict[str, Any]) -> list[float]:
    values: list[float] = []
    baseline = patient.get("baseline") or {}
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    bcr = patient.get("bcr") or {}
    latest_assessment_inputs = dict(((patient.get("latest_assessment") or {}).get("input_snapshot") or {}))
    followups = sorted(patient.get("follow_ups", []) or [], key=lambda item: str(item.get("visit_date") or ""))

    for source in (
        baseline,
        truth_values,
        latest_assessment_inputs,
        bcr,
    ):
        if not isinstance(source, dict):
            continue
        for key in ("psa_postop", "psa", "bcr_psa"):
            value = _safe_float(source.get(key))
            if value is not None:
                values.append(value)
    for followup in followups:
        for key in ("psa_postop", "psa_current", "psa"):
            value = _safe_float(followup.get(key))
            if value is not None:
                values.append(value)
    return values


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

    bcr = patient.get("bcr") or {}
    if _post_prostatectomy_bcr_confirmed(bcr):
        return "true_bcr"

    psa_series = _post_prostatectomy_psa_series(patient)
    if not psa_series:
        return "stable_surveillance"

    nadir_indetectable = any(value <= 0.1 for value in psa_series)
    latest_value = psa_series[-1]
    earliest_value = psa_series[0]
    postoperative_persistence_flag = _safe_bool(
        ((patient.get("baseline") or {}).get("postoperative_psa_persistent"))
        or ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {}).get("postoperative_psa_persistent")
    )

    if latest_value >= 0.2 and nadir_indetectable:
        return "true_bcr"
    if postoperative_persistence_flag:
        return "persistent_psa"
    if earliest_value >= 0.1 and not nadir_indetectable:
        return "persistent_psa"
    if latest_value >= 0.1 and not nadir_indetectable:
        return "persistent_psa"
    return "stable_surveillance"


def _has_postlocal_bcr(patient: dict[str, Any]) -> bool:
    bcr = patient.get("bcr") or {}
    has_postlocal_context = _has_post_prostatectomy_context(patient) or bool(patient.get("radiation"))
    prior_state = str((patient.get("prior_history") or {}).get("current_state") or "")
    if prior_state in POSTLOCAL_STATES:
        has_postlocal_context = True
    explicit_bcr_markers = _post_prostatectomy_bcr_confirmed(bcr) or any(
        _is_present(bcr.get(field))
        for field in ("bcr_psa", "psadt_at_bcr", "bcr_definition", "salvage_date", "bcr_date")
    )
    if explicit_bcr_markers and has_postlocal_context:
        return True
    if not has_postlocal_context:
        return False
    if patient.get("surgery"):
        return derive_post_prostatectomy_course(patient) == "true_bcr"
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
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    treatment_text = _treatment_text(patient).lower()
    truth_values = ((patient.get("longitudinal_truth_snapshot") or {}).get("field_values") or {})
    volume_context = derive_mhspc_volume_context(patient.get("baseline") or {})
    adt_context = _derive_adt_context(patient, explicit_state)
    castrate_status = _derive_castrate_status(patient, explicit_state)
    progression_pattern = _derive_progression_pattern(patient, explicit_state)
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    disease_status = str(latest_followup.get("disease_status") or "").lower()
    explicit_progression = str(truth_values.get("progression_pattern") or "").strip().lower()
    psadt_months = _safe_float(
        truth_values.get("psadt_months")
        or latest_followup.get("psadt_months")
    )
    metachronous = _is_metachronous_mhspc(patient)
    biochemical_progression_confirmed = (
        progression_pattern == "biochemical_only"
        and (
            explicit_progression == "biochemical_only"
            or psadt_months is not None
            or any(token in disease_status for token in ("progres", "ascen", "aumento", "bioqu", "psa"))
        )
    )

    if any(token in treatment_text for token in _PARP_TOKENS + _LU177_TOKENS):
        reasons.append("Tratamiento avanzado documentado con PARP / radioligando.")
        return "m1_crpc" if metastatic_evidence else "adt_progression_verification", reasons

    if explicit_state in {"m0_crpc", "m1_crpc"}:
        reasons.append("Último assessment ya documenta CRPC.")
        return explicit_state, reasons

    if castrate_status == "confirmed_castrate" and progression_pattern in {"radiographic", "clinical", "mixed"}:
        reasons.append("Progresión avanzada con testosterona en rango de castración.")
        return "m1_crpc" if metastatic_evidence else "m0_crpc", reasons

    if castrate_status == "confirmed_castrate" and biochemical_progression_confirmed:
        if progression_pattern == "biochemical_only":
            reasons.append("Ascenso bioquímico bajo testosterona en rango de castración compatible con carril CRPC.")
        return "m1_crpc" if metastatic_evidence else "m0_crpc", reasons

    if metastatic_evidence:
        if volume_context == "high" or metastasis_site == "Visceral" or metastasis_count >= 4:
            reasons.append("Enfermedad sistémica con carga compatible con mCSPC de mayor volumen.")
            return ("mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"), reasons
        if volume_context == "low" or (metastasis_count and metastasis_count <= 3):
            reasons.append("Carga metastásica baja / oligometastásica documentada.")
            if _has_local_treatment(patient):
                return "mcspc_oligo_metachronous", reasons
            return "mcspc_low_volume_sync_oligo", reasons
        reasons.append("Enfermedad metastásica documentada sin staging longitudinal completo.")
        return ("mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"), reasons

    if adt_context != "none" or any(token in treatment_text for token in _ARPI_TOKENS):
        reasons.append("ADT/ARPI documentados sin staging longitudinal suficiente para subtipo avanzado definitivo.")
        return "adt_progression_verification", reasons

    reasons.append("Tratamiento oncológico sistémico documentado sin suficiente staging estructurado.")
    return "localized_initial", reasons


def build_reconciled_state(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explicit_state = _assessment_state(patient, latest_assessment)
    reconciled_state = explicit_state
    reasons: list[str] = []

    has_histology = _biopsy_confirms_cancer(patient)
    has_confirmed_cancer = _implicit_confirmed_cancer(patient, explicit_state)
    has_local_treatment = _has_local_treatment(patient)
    has_bcr = _has_postlocal_bcr(patient)
    post_prostatectomy_course = derive_post_prostatectomy_course(patient)
    has_systemic_treatment = _has_systemic_treatment(patient)
    metastasis_site, metastasis_count, metastatic_evidence = _metastatic_context(patient)

    if explicit_state in DIAGNOSTIC_STATES:
        if has_systemic_treatment:
            reconciled_state, systemic_reasons = _systemic_target_state(
                patient,
                explicit_state,
                metastasis_site,
                metastasis_count,
                metastatic_evidence,
            )
            reasons.extend(systemic_reasons)
        elif has_bcr or has_local_treatment:
            reconciled_state = "recurrence_bcr" if has_bcr else "post_prostatectomy"
            reasons.append("El longitudinal ya documenta tratamiento local previo / recurrencia.")
        elif has_histology or has_confirmed_cancer:
            reconciled_state = "localized_initial"
            reasons.append("Existe evidencia longitudinal de cáncer confirmado fuera del carril diagnóstico.")
    elif explicit_state == "localized_initial" and has_systemic_treatment:
        reconciled_state, systemic_reasons = _systemic_target_state(
            patient,
            explicit_state,
            metastasis_site,
            metastasis_count,
            metastatic_evidence,
        )
        reasons.extend(systemic_reasons)
    elif explicit_state in POSTLOCAL_STATES and has_systemic_treatment:
        reconciled_state, systemic_reasons = _systemic_target_state(
            patient,
            explicit_state,
            metastasis_site,
            metastasis_count,
            metastatic_evidence,
        )
        reasons.extend(systemic_reasons)
    elif explicit_state == "post_prostatectomy" and post_prostatectomy_course == "true_bcr":
        reconciled_state = "recurrence_bcr"
        reasons.append("El PSA longitudinal posprostatectomía ya cumple criterio operativo de recurrencia bioquímica y debe pasar a carril de salvage.")
    elif explicit_state in CRPC_TRACK_STATES:
        reconciled_state, systemic_reasons = _systemic_target_state(
            patient,
            explicit_state,
            metastasis_site,
            metastasis_count,
            metastatic_evidence,
        )
        reasons.extend(systemic_reasons)

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
        "reconciled_management_track": reconciled_track,
        "state_conflict_flag": conflict_flag,
        "state_conflict_reason": " ".join(dict.fromkeys(reason for reason in reasons if reason)).strip(),
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
        },
    }


__all__ = [
    "ADVANCED_STATES",
    "CRPC_TRACK_STATES",
    "DIAGNOSTIC_STATES",
    "MHSPC_STATES",
    "POSTLOCAL_STATES",
    "build_reconciled_state",
    "derive_post_prostatectomy_course",
]
