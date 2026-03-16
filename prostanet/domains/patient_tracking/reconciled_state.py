from __future__ import annotations

from typing import Any

from prostanet.shared.metastatic_profile import derive_legacy_metastasis, derive_mhspc_volume_context


DIAGNOSTIC_STATES = {"diagnostic_workup", "post_negative_biopsy_followup"}
POSTLOCAL_STATES = {"post_prostatectomy", "recurrence_bcr"}
MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume",
}
ADVANCED_STATES = {
    "adt_progression_verification",
    "m0_crpc",
    "m1_crpc",
} | MHSPC_STATES

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
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_testosterone = _safe_float(latest_followup.get("testosterone_current"))
    if latest_testosterone is None:
        latest_testosterone = _safe_float((patient.get("baseline") or {}).get("testosterone_baseline"))
    if latest_testosterone is None:
        return "unknown"
    return "confirmed_castrate" if latest_testosterone <= 50 else "not_castrate"


def _derive_progression_pattern(patient: dict[str, Any], state: str) -> str:
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    disease_status = str(latest_followup.get("disease_status") or "").lower()
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
    imaging = patient.get("imaging") or []
    metastatic_evidence = metastasis_site not in {"", "M0", "No aplica"}
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


def _systemic_target_state(
    patient: dict[str, Any],
    explicit_state: str,
    metastasis_site: str,
    metastasis_count: int,
    metastatic_evidence: bool,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    treatment_text = _treatment_text(patient).lower()
    volume_context = derive_mhspc_volume_context(patient.get("baseline") or {})
    adt_context = _derive_adt_context(patient, explicit_state)
    castrate_status = _derive_castrate_status(patient, explicit_state)
    progression_pattern = _derive_progression_pattern(patient, explicit_state)
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    disease_status = str(latest_followup.get("disease_status") or "").lower()

    if any(token in treatment_text for token in _PARP_TOKENS + _LU177_TOKENS):
        reasons.append("Tratamiento avanzado documentado con PARP / radioligando.")
        return "m1_crpc" if metastatic_evidence else "adt_progression_verification", reasons

    if explicit_state in {"m0_crpc", "m1_crpc"}:
        reasons.append("Último assessment ya documenta CRPC.")
        return explicit_state, reasons

    if castrate_status == "confirmed_castrate" and progression_pattern in {"radiographic", "clinical", "mixed"}:
        reasons.append("Progresión avanzada con testosterona en rango de castración.")
        return "m1_crpc" if metastatic_evidence else "m0_crpc", reasons

    if metastatic_evidence:
        if volume_context == "high" or metastasis_site == "Visceral" or metastasis_count >= 4:
            reasons.append("Enfermedad sistémica con carga compatible con mCSPC de mayor volumen.")
            return "mcspc_high_volume", reasons
        if volume_context == "low" or (metastasis_count and metastasis_count <= 3):
            reasons.append("Carga metastásica baja / oligometastásica documentada.")
            if _has_local_treatment(patient):
                return "mcspc_oligo_metachronous", reasons
            return "mcspc_low_volume_sync_oligo", reasons
        reasons.append("Enfermedad metastásica documentada sin staging longitudinal completo.")
        return "mcspc_high_volume", reasons

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
    has_bcr = bool(patient.get("bcr"))
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
        },
    }
