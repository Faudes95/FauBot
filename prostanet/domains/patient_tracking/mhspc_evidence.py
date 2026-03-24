from __future__ import annotations

from typing import Any

from clinical_scores import docetaxel_fitness
from prostanet.domains.patient_tracking.mhspc_regimen_selector import (
    preferred_non_triplet_regimen_label,
)
from prostanet.domains.patient_tracking.therapy_catalog import trial_backbone


MHSPC_STATES = {
    "mcspc_low_volume_sync_oligo",
    "mcspc_oligo_metachronous",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}

VISIBLE_TRIALS_BY_STATE = {
    "mcspc_low_volume_sync_oligo": {"ARANOTE", "ARCHES", "TITAN", "ENZAMET", "STAMPEDE"},
    "mcspc_oligo_metachronous": {"ARANOTE", "ARCHES", "TITAN", "ENZAMET"},
    "mcspc_high_volume_sync": {"ARANOTE", "ARASENS", "PEACE-1", "CHAARTED", "LATITUDE"},
    "mcspc_high_volume_metachronous": {"ARANOTE", "ARASENS", "CHAARTED"},
}

HIDDEN_TRIALS_BY_STATE = {
    "mcspc_low_volume_sync_oligo": {"ARASENS", "PEACE-1", "CHAARTED", "LATITUDE"},
    "mcspc_oligo_metachronous": {"ARASENS", "PEACE-1", "CHAARTED", "LATITUDE", "STAMPEDE"},
    "mcspc_high_volume_sync": set(),
    "mcspc_high_volume_metachronous": {"PEACE-1", "STAMPEDE"},
}


def _boolish(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "si", "sí", "yes"}


def _safe_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def resolve_mhspc_state(state: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    if state != "mcspc_high_volume":
        return state
    explicit = str(payload.get("disease_temporality", "") or "").strip().lower()
    if explicit in {"sync", "sincronico", "sincrónico", "de_novo", "denovo"}:
        return "mcspc_high_volume_sync"
    if explicit in {"metachronous", "metacronico", "metacrónico"}:
        return "mcspc_high_volume_metachronous"
    if _boolish(payload.get("metachronous_metastasis", "0")):
        return "mcspc_high_volume_metachronous"
    return "mcspc_high_volume_sync"


def is_mhspc_state(state: str) -> bool:
    return state in MHSPC_STATES


def _state_label(state: str) -> str:
    labels = {
        "mcspc_low_volume_sync_oligo": "mHSPC sincrónico de bajo volumen",
        "mcspc_oligo_metachronous": "mHSPC oligometastásico metacrónico",
        "mcspc_high_volume_sync": "mHSPC sincrónico de alto volumen",
        "mcspc_high_volume_metachronous": "mHSPC metacrónico de alto volumen",
    }
    return labels.get(state, "mHSPC")


def _preferred_non_triplet_label(state: str, payload: dict[str, Any] | None = None) -> str:
    return preferred_non_triplet_regimen_label(state, payload or {})


def build_triplet_decision(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    docetaxel_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    exact_state = resolve_mhspc_state(state, payload)
    if exact_state not in VISIBLE_TRIALS_BY_STATE:
        return {}

    docetaxel = dict(docetaxel_bundle or docetaxel_fitness(payload))
    fit_for_docetaxel = bool(docetaxel.get("fit_for_docetaxel"))
    hard_stops = list(docetaxel.get("docetaxel_hard_stop_reasons") or [])
    cautions = list(docetaxel.get("docetaxel_caution_reasons") or [])
    fit_summary = str(docetaxel.get("docetaxel_fit_summary") or "").strip()
    missing_inputs = list(docetaxel.get("missing_inputs") or [])

    status = "not_applicable"
    primary_reason = ""
    why_yes: list[str] = []
    why_no: list[str] = []
    preferred_triplet = ""
    supported_triplets: list[str] = []
    evidence_basis: list[str] = []

    if exact_state == "mcspc_high_volume_sync":
        preferred_triplet = "ADT + docetaxel + darolutamida"
        supported_triplets = ["ARASENS", "PEACE-1"]
        evidence_basis = ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC", "ARASENS", "PEACE-1"]
        if fit_for_docetaxel:
            status = "recommended"
            primary_reason = "El escenario es mHSPC sincrónico de alto volumen y el paciente es apto para docetaxel."
            why_yes = [
                "La discusión triplete sí corresponde en enfermedad de novo/sincrónica de alto volumen.",
                "ARASENS respalda triplete con darolutamida sobre backbone ADT + docetaxel.",
                "PEACE-1 puede respaldar triplete con abiraterona en contexto sincrónico/de novo.",
            ]
        else:
            status = "contraindicated" if hard_stops else "not_prioritized"
            primary_reason = "El escenario es de alto volumen, pero el paciente no es buen candidato actual a triplete con docetaxel."
            why_no = hard_stops or cautions or ["Faltan datos clínicos para declarar aptitud plena a docetaxel."]
    elif exact_state == "mcspc_high_volume_metachronous":
        preferred_triplet = "ADT + docetaxel + darolutamida"
        supported_triplets = ["ARASENS"]
        evidence_basis = ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC", "ARASENS"]
        if fit_for_docetaxel:
            status = "eligible"
            primary_reason = "El escenario es mHSPC metacrónico de alto volumen y el paciente es apto para docetaxel."
            why_yes = [
                "La intensificación fuerte sigue siendo apropiada en alto volumen.",
                "ARASENS es el backbone trial-like preferido en este escenario.",
                "PEACE-1 no debe priorizarse como backbone principal fuera del contexto de novo/sincrónico.",
            ]
        else:
            status = "contraindicated" if hard_stops else "not_prioritized"
            primary_reason = "El escenario es de alto volumen, pero hoy el triplete no se prioriza porque docetaxel no es adecuado o no está suficientemente respaldado."
            why_no = hard_stops or cautions or ["Se requiere completar fitness para docetaxel antes de considerar triplete."]
    elif exact_state == "mcspc_low_volume_sync_oligo":
        preferred_triplet = ""
        supported_triplets = []
        status = "not_applicable"
        primary_reason = "El escenario actual es mHSPC sincrónico de bajo volumen, donde la vía principal es doblete sistémico y consideración de RT al primario."
        why_no = [
            "El triplete no es el backbone principal en bajo volumen sincrónico.",
            "La evidencia visible debe priorizar RT al primario y dobletes con ARPI.",
            "PEACE-1 no debe mostrarse como estudio elegible principal para esta conducta.",
        ]
        evidence_basis = ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC", "STAMPEDE", "ARANOTE", "ARCHES", "TITAN"]
    elif exact_state == "mcspc_oligo_metachronous":
        preferred_triplet = ""
        supported_triplets = []
        status = "not_applicable"
        primary_reason = "El escenario actual es mHSPC oligometastásico metacrónico, donde la vía principal es doblete sistémico y discusión estructurada de MDT."
        why_no = [
            "El triplete no es la estrategia estándar visible en oligometastásico metacrónico.",
            "La evidencia principal favorece intensificación hormonal; docetaxel añade toxicidad sin rol principal aquí.",
            "La discusión clínica debe centrarse en doblete hormonal y MDT en contexto multidisciplinario.",
        ]
        evidence_basis = ["NCCN 5.2026 mHSPC", "EAU 2026 mHSPC", "ARANOTE", "ARCHES", "TITAN", "ENZAMET"]

    if missing_inputs and status in {"recommended", "eligible", "contraindicated", "not_prioritized"}:
        why_no = list(why_no)
        why_no.append(f"Datos faltantes que condicionan la decisión: {', '.join(missing_inputs)}.")

    status_label_map = {
        "recommended": "Sí triplete",
        "eligible": "Triplete elegible",
        "not_prioritized": "No triplete por ahora",
        "not_applicable": "No aplica triplete",
        "contraindicated": "No triplete",
    }
    tone_map = {
        "recommended": "emerald",
        "eligible": "cyan",
        "not_prioritized": "amber",
        "not_applicable": "slate",
        "contraindicated": "rose",
    }
    preferred_backbone_bundle = trial_backbone("ARASENS" if "ARASENS" in supported_triplets else "PEACE-1" if "PEACE-1" in supported_triplets else "ARANOTE")

    return {
        "show": True,
        "state": exact_state,
        "state_label": _state_label(exact_state),
        "status": status,
        "status_label": status_label_map.get(status, status),
        "tone": tone_map.get(status, "slate"),
        "is_triplet_candidate": status in {"recommended", "eligible"},
        "primary_reason": primary_reason,
        "why_yes": why_yes,
        "why_no": why_no,
        "docetaxel_fitness_summary": fit_summary,
        "hard_stop_reasons": hard_stops,
        "caution_reasons": cautions,
        "missing_inputs": missing_inputs,
        "preferred_triplet_backbone": preferred_backbone_bundle.get("recommended_trial_backbone", "") if preferred_triplet else "",
        "preferred_triplet_backbone_label": preferred_triplet,
        "supported_triplet_backbones": supported_triplets,
        "preferred_non_triplet_backbone_label": _preferred_non_triplet_label(exact_state, payload),
        "evidence_basis": evidence_basis,
    }


def visible_trials_for_mhspc_state(state: str, payload: dict[str, Any] | None = None) -> tuple[set[str], set[str]]:
    exact_state = resolve_mhspc_state(state, payload or {})
    return (
        set(VISIBLE_TRIALS_BY_STATE.get(exact_state, set())),
        set(HIDDEN_TRIALS_BY_STATE.get(exact_state, set())),
    )


def build_visible_mhspc_trial_matches(
    state: str,
    payload: dict[str, Any] | None = None,
    *,
    triplet_decision: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    payload = payload or {}
    exact_state = resolve_mhspc_state(state, payload)
    if exact_state not in VISIBLE_TRIALS_BY_STATE:
        return [], 0
    visible, hidden = visible_trials_for_mhspc_state(exact_state, payload)
    triplet = triplet_decision or build_triplet_decision(exact_state, payload)
    fit_for_docetaxel = bool(triplet.get("is_triplet_candidate"))
    matches: list[dict[str, Any]] = []
    for trial in sorted(visible):
        match = True
        reason = "Estudio concordante con el escenario clínico actual."
        if trial == "ARASENS":
            match = fit_for_docetaxel
            reason = (
                "Triplete respaldado por ARASENS porque el caso es de alto volumen y es apto para docetaxel."
                if match
                else "ARASENS no aplica hoy porque el triplete con docetaxel no está indicado o no es seguro."
            )
        elif trial == "PEACE-1":
            match = exact_state == "mcspc_high_volume_sync" and fit_for_docetaxel
            reason = (
                "PEACE-1 se correlaciona con enfermedad de novo/sincrónica de alto volumen apta para docetaxel."
                if match
                else "PEACE-1 no debe presentarse como backbone principal fuera del contexto sincrónico de alto volumen."
            )
        elif trial == "STAMPEDE":
            reason = "STAMPEDE respalda el uso de RT al primario en enfermedad metastásica de bajo volumen sincrónica."
        elif trial == "ARANOTE":
            reason = "ARANOTE respalda doblete con darolutamida en mHSPC, incluyendo subgrupos de alto y bajo volumen."
        elif trial in {"ARCHES", "TITAN", "ENZAMET"}:
            reason = "Ensayo concordante con intensificación hormonal en mHSPC."
        elif trial == "CHAARTED":
            match = "high_volume" in exact_state and fit_for_docetaxel
            reason = (
                "CHAARTED es más concordante con alto volumen y aptitud a docetaxel."
                if match
                else "CHAARTED no se prioriza en este subescenario porque la intensificación con docetaxel no es la vía principal."
            )
        elif trial == "LATITUDE":
            high_risk_latitude = (
                (_safe_int(payload.get("gleason_score") or 0) >= 8)
                + (_safe_int(payload.get("metastasis_count") or 0) >= 3)
                + int(_boolish(payload.get("visceral_metastases")) or str(payload.get("metastasis_site", "")).lower() == "visceral")
            ) >= 2
            match = exact_state == "mcspc_high_volume_sync" and high_risk_latitude
            reason = (
                "LATITUDE es concordante con mHSPC de novo de alto riesgo."
                if match
                else "LATITUDE no se prioriza porque este caso no reproduce el marco de alto riesgo de novo del ensayo."
            )
        backbone_bundle = trial_backbone(trial)
        matches.append(
            {
                "trial": trial,
                "study_name": trial,
                "match": match,
                "eligible": match,
                "visible": True,
                "reason": reason,
                "status": "aplica" if match else "no_aplica",
                "recommended_trial_backbone": backbone_bundle.get("recommended_trial_backbone", ""),
                "recommended_trial_backbone_label": backbone_bundle.get("recommended_trial_backbone_label", ""),
                "recommended_trial_backbone_note": backbone_bundle.get("recommended_trial_backbone_note", ""),
            }
        )
    return matches, len(hidden)
