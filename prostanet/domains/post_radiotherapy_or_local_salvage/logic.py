from __future__ import annotations

from copy import deepcopy
from typing import Any


YES_VALUES = {"1", "true", "yes", "si", "sí", "apto", "fit", "eligible"}
NO_VALUES = {"0", "false", "no", "na", "n/a", "not_available"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _normalize_text(value).lower() in YES_VALUES


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "Desconocido", "No documentado", "No realizado")


def _dedupe(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item or "").strip()))


def _burden_level(value: Any) -> str:
    text = _normalize_text(value).lower()
    if text in {"grave", "severo", "severa", "alto", "alta", "high"}:
        return "high"
    if text in {"moderado", "moderada", "medium"}:
        return "moderate"
    if text in {"leve", "bajo", "baja", "low"}:
        return "low"
    return ""


def _fit_for_salvage_surgery(payload: dict[str, Any]) -> bool:
    fitness_text = _normalize_text(payload.get("anesthesia_surgical_fitness")).lower()
    ecog = _safe_int(payload.get("ecog_score"))
    if fitness_text in NO_VALUES:
        return False
    if fitness_text in YES_VALUES:
        return True
    return ecog is None or ecog <= 2


def _prior_rt_modality(payload: dict[str, Any]) -> str:
    return _normalize_text(payload.get("prior_rt_modality")).upper()


def _systemic_psma_pattern(payload: dict[str, Any], psma_impact: dict[str, Any]) -> tuple[str, bool, bool]:
    stage_after = _normalize_text(payload.get("psma_stage_after_psma")).upper()
    uptake = _normalize_text(payload.get("psma_uptake_pattern")).lower()
    pattern = _normalize_text(psma_impact.get("clinical_pattern")).lower() or uptake
    lesion_count = _safe_int(payload.get("psma_total_lesions"))
    disseminated = stage_after in {"M1B", "M1C"} or pattern in {"diseminado", "systemic", "widespread"}
    oligomet = (
        not disseminated
        and (
            stage_after == "M1A"
            or pattern in {"oligometastatic", "multifocal"}
            or (lesion_count is not None and 0 < lesion_count <= 5 and stage_after not in {"", "M0"})
        )
    )
    return pattern or uptake, disseminated, oligomet


def build_post_rt_failure_definition(payload: dict[str, Any]) -> dict[str, Any]:
    psa_nadir = _safe_float(payload.get("psa_nadir"))
    psa_current = _safe_float(payload.get("psa_current", payload.get("psa")))
    phoenix_delta = _safe_float(payload.get("phoenix_delta"))
    if phoenix_delta is None and psa_nadir is not None and psa_current is not None:
        phoenix_delta = round(psa_current - psa_nadir, 3)
    biopsy_proven = _is_true(payload.get("biopsy_proven_local_recurrence"))
    radiographic_local = (
        _is_true(payload.get("mpmri_localized_recurrence"))
        or (
            _is_present(payload.get("local_recurrence_site"))
            and _normalize_text(payload.get("mpmri_done")).lower() in YES_VALUES
        )
    )
    if phoenix_delta is None:
        phoenix_status = "not_assessable"
    elif phoenix_delta >= 2.0:
        phoenix_status = "met"
    else:
        phoenix_status = "not_met"

    if phoenix_status == "met":
        failure_confirmation_basis = "phoenix"
    elif biopsy_proven:
        failure_confirmation_basis = "biopsy_proven_local_failure"
    elif radiographic_local:
        failure_confirmation_basis = "radiographic_local_failure"
    else:
        failure_confirmation_basis = "indeterminate"

    confirmed_local_failure = failure_confirmation_basis in {
        "phoenix",
        "biopsy_proven_local_failure",
        "radiographic_local_failure",
    }
    required_missing_fields: list[str] = []
    if psa_current is None:
        required_missing_fields.append("psa_current")
    if psa_nadir is None and phoenix_status == "not_assessable":
        required_missing_fields.append("psa_nadir")
    if phoenix_delta is None:
        required_missing_fields.append("phoenix_delta")
    if failure_confirmation_basis == "indeterminate":
        required_missing_fields.extend(
            [
                "biopsy_proven_local_recurrence",
                "mpmri_done",
                "mpmri_localized_recurrence",
            ]
        )

    rationale_parts: list[str] = []
    if phoenix_status == "met":
        rationale_parts.append("El incremento nadir + 2 ng/mL cumple la definición de Phoenix.")
    elif phoenix_status == "not_met":
        rationale_parts.append("El incremento de PSA todavía no cumple Phoenix.")
    else:
        rationale_parts.append("No existe información suficiente para cerrar la definición de Phoenix.")
    if failure_confirmation_basis == "biopsy_proven_local_failure":
        rationale_parts.append("Existe confirmación histológica de recurrencia local.")
    elif failure_confirmation_basis == "radiographic_local_failure":
        rationale_parts.append("La imagen local documenta recurrencia confinada y utilizable para salvage.")

    return {
        "phoenix_status": phoenix_status,
        "phoenix_delta": phoenix_delta,
        "psa_nadir": psa_nadir,
        "psa_current": psa_current,
        "failure_confirmation_basis": failure_confirmation_basis,
        "confirmed_local_failure": confirmed_local_failure,
        "required_missing_fields": _dedupe(required_missing_fields),
        "rationale": " ".join(rationale_parts).strip(),
    }


def build_post_rt_local_salvage_ranking(
    payload: dict[str, Any],
    *,
    failure_definition: dict[str, Any],
    psma_impact: dict[str, Any],
) -> dict[str, Any]:
    failure_confirmed = bool(failure_definition.get("confirmed_local_failure"))
    pattern, disseminated, oligomet = _systemic_psma_pattern(payload, psma_impact)
    urinary_burden = _burden_level(payload.get("urinary_burden"))
    incontinence_burden = _burden_level(payload.get("incontinence_burden"))
    bowel_burden = _burden_level(payload.get("bowel_burden"))
    rectal_toxicity_grade = _safe_int(payload.get("rectal_toxicity_grade")) or 0
    prostate_volume = _safe_float(payload.get("prostate_volume"))
    expertise_available = _normalize_text(payload.get("salvage_expertise_available")).lower()
    expertise_known = expertise_available not in {"", "desconocido", "unknown"}
    expertise_positive = expertise_available in YES_VALUES if expertise_known else False
    stricture_history = _is_true(payload.get("urethral_stricture_history"))
    surgery_fit = _fit_for_salvage_surgery(payload)
    local_site = _normalize_text(payload.get("local_recurrence_site")).lower()
    focal_local = _is_true(payload.get("mpmri_localized_recurrence")) or any(
        token in local_site
        for token in {"gland", "focal", "apex", "base", "peripheral", "bed", "anastomosis"}
    )

    local_required_fields = [
        "prior_rt_modality",
        "prior_rt_dose",
        "prior_rt_fields",
        "biopsy_proven_local_recurrence",
        "biopsy_date",
        "biopsy_grade_group",
        "mpmri_done",
        "mpmri_date",
        "mpmri_localized_recurrence",
        "local_recurrence_site",
        "urinary_burden",
        "incontinence_burden",
        "urethral_stricture_history",
        "bowel_burden",
        "rectal_toxicity_grade",
        "prostate_volume",
        "anesthesia_surgical_fitness",
        "salvage_expertise_available",
        "psma_pet_done",
    ]
    if _normalize_text(payload.get("psma_pet_done")).lower() in YES_VALUES:
        local_required_fields.extend(
            [
                "psma_radioligand",
                "psma_rads_score",
                "psma_uptake_pattern",
                "psma_stage_after_psma",
            ]
        )
    required_missing_fields = _dedupe(
        list(failure_definition.get("required_missing_fields") or [])
        + [field for field in local_required_fields if not _is_present(payload.get(field))]
    )

    entries = [
        {
            "regimen_code": "SALVAGE_PROSTATECTOMY",
            "name": "Salvage prostatectomy",
            "description": "Rescate quirúrgico después de radioterapia cuando persiste una vía local técnicamente defendible.",
            "dose": "Cirugía de rescate con intención curativa",
            "route": "Cirugía",
            "schedule": "Según board urooncológico y preparación preoperatoria",
            "score": 72.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "SALVAGE_CRYOTHERAPY",
            "name": "Cryotherapy de rescate",
            "description": "Ablación focal o glandular en recurrencia localizada post-RT seleccionada.",
            "dose": "Crioterapia focal o hemiablación",
            "route": "Ablación",
            "schedule": "Procedimiento único con control posterior dirigido",
            "score": 68.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "SALVAGE_HIFU",
            "name": "HIFU de rescate",
            "description": "Ultrasonido focalizado de alta intensidad como rescate local en lesión confinada.",
            "dose": "HIFU focal/glandular",
            "route": "Ablación",
            "schedule": "Procedimiento único guiado por imagen",
            "score": 66.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "SALVAGE_BRACHYTHERAPY",
            "name": "Salvage brachytherapy",
            "description": "Braquiterapia de rescate en recurrencia intraprostática seleccionada con toxicidad rectal aceptable.",
            "dose": "Braquiterapia focal o parcial",
            "route": "Braquiterapia",
            "schedule": "Planeación dosimétrica y tratamiento dirigido",
            "score": 64.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "PSMA_GUIDED_MDT",
            "name": "MDT / SBRT guiada por PSMA",
            "description": "Control dirigido de enfermedad oligorrecurrente cuando el patrón ya no es exclusivamente glandular.",
            "dose": "SBRT 30-35 Gy en 3-5 fracciones o estrategia MDT equivalente",
            "route": "Radioterapia estereotáctica / MDT",
            "schedule": "Tratamiento dirigido tras comité",
            "score": 62.0,
            "family_code": "local_mdt_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
        {
            "regimen_code": "SYSTEMIC_RESTAGING",
            "name": "Redirección sistémica / reestadificación",
            "description": "La vía local curativa se cierra y la prioridad pasa a reestadificar o secuenciar tratamiento sistémico.",
            "dose": "Restaging sistémico",
            "route": "Imagen / secuenciación",
            "schedule": "Redefinir carril sistémico con comité",
            "score": 40.0,
            "family_code": "observation_family",
            "hard_blocks": [],
            "caution_flags": [],
        },
    ]

    for entry in entries:
        code = entry["regimen_code"]
        if disseminated:
            if code == "SYSTEMIC_RESTAGING":
                entry["score"] = 96.0
                entry["why_this_rank"] = ["El patrón PSMA diseminado o estadio M1b/M1c ya no sostiene salvage local aislado."]
            else:
                entry["hard_blocks"].append("PSMA diseminada o estadio metastásico incompatible con salvage local aislado.")
                entry["score"] -= 60
        elif not failure_confirmed:
            if code == "SYSTEMIC_RESTAGING":
                entry["score"] = 82.0
                entry["caution_flags"].append("Aún no se ha cerrado Phoenix ni confirmación local equivalente.")
                entry["why_this_rank"] = ["Todavía falta confirmar fracaso post-RT antes de fijar salvage curativo."]
            else:
                entry["hard_blocks"].append("No existe definición Phoenix cerrada ni confirmación local equivalente.")
                entry["score"] -= 45
        elif oligomet:
            if code == "PSMA_GUIDED_MDT":
                entry["score"] = 88.0
                entry["why_this_rank"] = ["El patrón oligorrecurrente dirigido por PSMA favorece MDT/SBRT por encima del salvage glandular puro."]
            elif code == "SYSTEMIC_RESTAGING":
                entry["score"] = 55.0
                entry["caution_flags"].append("La vía local no está completamente cerrada, pero la MDT domina primero.")
            else:
                entry["caution_flags"].append("La enfermedad ya no parece puramente glandular; la MDT puede ser más coherente.")
                entry["score"] -= 10
        else:
            if code == "SYSTEMIC_RESTAGING":
                entry["score"] = 35.0
                entry["caution_flags"].append("La vía local sigue abierta y no debe abandonarse sin un redirector explícito.")

        if code == "SALVAGE_PROSTATECTOMY":
            if not surgery_fit:
                entry["hard_blocks"].append("La aptitud quirúrgica/anestésica no sostiene salvage prostatectomy.")
                entry["score"] -= 35
            if urinary_burden == "high" or incontinence_burden == "high":
                entry["caution_flags"].append("La carga urinaria o la incontinencia elevan la morbilidad quirúrgica de rescate.")
                entry["score"] -= 14
            if stricture_history:
                entry["caution_flags"].append("El antecedente de estenosis uretral complica la reconstrucción quirúrgica.")
                entry["score"] -= 18
            if rectal_toxicity_grade >= 3:
                entry["hard_blocks"].append("La toxicidad rectal grado alto reduce drásticamente la factibilidad quirúrgica.")
                entry["score"] -= 18
        elif code == "SALVAGE_CRYOTHERAPY":
            if not focal_local:
                entry["caution_flags"].append("La recurrencia no se ve claramente focal; cryo pierde precisión.")
                entry["score"] -= 10
            if urinary_burden == "high" or stricture_history:
                entry["caution_flags"].append("La carga urinaria/estenosis previa limita seguridad funcional de cryotherapy.")
                entry["score"] -= 14
            if not surgery_fit:
                entry["score"] += 4
                entry["why_this_rank"] = list(entry.get("why_this_rank") or []) + ["La ablación puede ser más realista que cirugía mayor si la aptitud quirúrgica es limitada."]
        elif code == "SALVAGE_HIFU":
            if not focal_local:
                entry["caution_flags"].append("HIFU funciona mejor con recurrencia intraprostática bien localizada.")
                entry["score"] -= 12
            if prostate_volume is not None and prostate_volume > 55:
                entry["caution_flags"].append("El volumen prostático grande reduce la eficiencia del HIFU de rescate.")
                entry["score"] -= 10
            if not expertise_positive and expertise_known:
                entry["hard_blocks"].append("No hay experiencia local documentada para HIFU de rescate.")
                entry["score"] -= 20
        elif code == "SALVAGE_BRACHYTHERAPY":
            modality = _prior_rt_modality(payload)
            if modality in {"LDR", "LDR_BRACHY", "HDR", "HDR_BRACHY", "BRACHY"}:
                entry["caution_flags"].append("La reirradiación con braquiterapia tras braquiterapia previa exige cautela extrema.")
                entry["score"] -= 18
            if rectal_toxicity_grade >= 2 or bowel_burden == "high":
                entry["hard_blocks"].append("La toxicidad rectal/bowel previa penaliza fuertemente salvage brachytherapy.")
                entry["score"] -= 24
            if urinary_burden == "high":
                entry["caution_flags"].append("La toxicidad urinaria previa limita braquiterapia de rescate.")
                entry["score"] -= 12
        elif code == "PSMA_GUIDED_MDT":
            if not oligomet:
                entry["hard_blocks"].append("La MDT post-RT requiere patrón oligorrecurrente claramente dirigido.")
                entry["score"] -= 45
        elif code == "SYSTEMIC_RESTAGING":
            if not disseminated and not oligomet and failure_confirmed:
                entry["why_this_rank"] = ["Debe permanecer visible como alternativa si la matriz local se cierra por toxicidad o factibilidad."]

        if expertise_known and not expertise_positive and code != "SYSTEMIC_RESTAGING":
            entry["caution_flags"].append("No existe experiencia local documentada; discutir referencia a centro con expertise.")
            entry["score"] -= 12

        entry["score"] = round(entry["score"], 1)
        entry["eligibility_status"] = "eligible_nonpreferred"
        if entry["hard_blocks"]:
            entry["eligibility_status"] = "ineligible"
        elif entry["caution_flags"]:
            entry["eligibility_status"] = "eligible_with_caution"

    ranked = sorted(entries, key=lambda item: item.get("score", 0), reverse=True)
    top = ranked[0] if ranked else {}
    if top and top["eligibility_status"] != "ineligible":
        top["eligibility_status"] = "preferred"

    dominant_local_option = {}
    if top and top["regimen_code"] != "SYSTEMIC_RESTAGING" and top["eligibility_status"] == "preferred":
        dominant_local_option = deepcopy(top)

    return {
        "ranked_options": ranked,
        "dominant_local_option": dominant_local_option,
        "required_missing_fields": required_missing_fields,
        "pattern": pattern,
        "disseminated": disseminated,
        "oligometastatic": oligomet,
    }


def build_post_rt_transition_bundle(
    payload: dict[str, Any],
    *,
    failure_definition: dict[str, Any],
    local_salvage_ranking: dict[str, Any],
) -> dict[str, Any]:
    ranked = list(local_salvage_ranking.get("ranked_options") or [])
    top = dict(ranked[0] if ranked else {})
    missing = list(local_salvage_ranking.get("required_missing_fields") or [])
    if not failure_definition.get("confirmed_local_failure"):
        transition_status = "pending_confirmation"
        reason = "No debe abrirse salvage post-RT curativo hasta cumplir Phoenix o confirmar falla local equivalente."
    elif local_salvage_ranking.get("disseminated"):
        transition_status = "redirect_systemic"
        reason = "La distribución PSMA ya no sostiene rescate local aislado."
    elif local_salvage_ranking.get("oligometastatic"):
        transition_status = "mdt_candidate"
        reason = "El patrón oligorrecurrente dirigido por PSMA favorece MDT/SBRT o rescate multimodal."
    elif top and top.get("eligibility_status") == "preferred" and top.get("regimen_code") != "SYSTEMIC_RESTAGING":
        transition_status = "local_salvage_candidate"
        reason = f"La vía local sigue abierta y la modalidad dominante es {top.get('name') or top.get('regimen_code')}."
    else:
        transition_status = "restate_before_decision"
        reason = "Aún falta cerrar restaging y factibilidad antes de fijar la modalidad de salvage."
    return {
        "transition_status": transition_status,
        "care_goal": "curative_local_control" if transition_status in {"local_salvage_candidate", "mdt_candidate"} else "restate_before_commitment" if transition_status in {"pending_confirmation", "restate_before_decision"} else "systemic_redirection",
        "trigger_reasons": _dedupe([reason, failure_definition.get("rationale")]),
        "required_missing_fields": missing,
        "dominant_local_option": deepcopy(local_salvage_ranking.get("dominant_local_option") or {}),
    }


def build_post_rt_schedule_overlay(transition_bundle: dict[str, Any]) -> dict[str, Any]:
    status = _normalize_text(transition_bundle.get("transition_status"))
    if status == "redirect_systemic":
        return {
            "schedule_primary_intent": "Cerrar vía local y redirigir a secuencia sistémica",
            "cadence_adjustment_reasons": [
                "Completar reestadificación sistémica",
                "Redefinir siguiente línea con comité multidisciplinario",
            ],
            "recommended_events": ["PET/PSMA estructurado", "Tumor board post-RT", "Secuenciación sistémica"],
        }
    if status == "mdt_candidate":
        return {
            "schedule_primary_intent": "Cerrar ruta oligorrecurrente dirigida",
            "cadence_adjustment_reasons": [
                "Confirmar burden PSMA dirigido",
                "Definir MDT/SBRT o estrategia combinada",
            ],
            "recommended_events": ["Tumor board", "Planeación MDT", "Correlación mpMRI/PSMA"],
        }
    if status == "local_salvage_candidate":
        return {
            "schedule_primary_intent": "Sostener salvage local post-RT",
            "cadence_adjustment_reasons": [
                "Correlacionar anatomía local y toxicidad previa",
                "Elegir modalidad de rescate con mayor plausibilidad curativa",
            ],
            "recommended_events": ["Valoración uro-oncológica", "Planeación de salvage local", "Revisión funcional GU/GI"],
        }
    return {
        "schedule_primary_intent": "Cerrar confirmación de falla post-RT",
        "cadence_adjustment_reasons": [
            "Confirmar Phoenix o evidencia local equivalente",
            "Completar reestadificación antes de decidir salvage",
        ],
        "recommended_events": ["PSA/nadir documentado", "mpMRI/biopsia local", "PSMA estructurado"],
    }
