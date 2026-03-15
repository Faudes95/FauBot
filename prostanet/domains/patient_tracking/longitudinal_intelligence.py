from __future__ import annotations

from datetime import date, datetime
from typing import Any

from prostanet.application.module_registry import ModuleRegistry
from prostanet.domains.patient_tracking.event_graph import merge_record_into_assessment_payload
from prostanet.domains.patient_tracking.followup_agenda import build_agenda_board, infer_management_track
from prostanet.shared.contracts import ClinicalSignalSet, NextBestAction, RecommendationAudit, StateTransitionProposal


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

COMMON_EVIDENCE = ["NCCN 2026", "EAU 2026"]


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "No realizado", "Desconocido", "Desconocida")


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


def _latest(items: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not items:
        return {}
    for key in keys:
        dated = [item for item in items if item.get(key)]
        if dated:
            return sorted(dated, key=lambda item: str(item.get(key)), reverse=True)[0]
    return items[-1]


def _current_state(patient: dict[str, Any], latest_assessment: dict[str, Any] | None) -> str:
    return (
        (latest_assessment or {}).get("state")
        or (patient.get("latest_assessment") or {}).get("state")
        or (patient.get("prior_history") or {}).get("current_state")
        or "diagnostic_workup"
    )


def _biopsy_confirms_cancer(patient: dict[str, Any]) -> bool:
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    return any(
        _is_present(latest_biopsy.get(field))
        for field in ("gleason_primary", "gleason_secondary", "isup_grade", "positive_cores")
    ) and (_safe_int(latest_biopsy.get("positive_cores")) or 0) > 0


def _derive_current_treatment(patient: dict[str, Any]) -> str:
    treatments = patient.get("treatments") or []
    if treatments:
        current = treatments[-1]
        regimen = current.get("regimen_json")
        if isinstance(regimen, dict) and regimen.get("summary"):
            return str(regimen["summary"])
        if isinstance(regimen, str) and regimen.strip():
            return regimen
        if current.get("drug_scheme"):
            return str(current.get("drug_scheme"))
    followup = _latest(patient.get("follow_ups", []), "visit_date")
    return str(followup.get("current_treatment") or "")


def _derive_metastatic_context(patient: dict[str, Any]) -> tuple[str, int]:
    baseline = patient.get("baseline") or {}
    metastasis_site = str(baseline.get("metastasis_site") or "M0")
    metastasis_count = _safe_int(baseline.get("metastasis_count")) or 0
    imaging = patient.get("imaging") or []
    for study in imaging:
        study_type = str(study.get("study_type", "")).lower()
        findings = study.get("findings", {}) if isinstance(study.get("findings"), dict) else {}
        if "psma" in study_type:
            locations = findings.get("lesion_locations", []) or []
            lesion_count = _safe_int(findings.get("psma_total_lesions")) or 0
            if locations or lesion_count:
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
            bone_lesions = _safe_int(study.get("bone_lesion_count")) or _safe_int((findings or {}).get("bone_lesion_count")) or 0
            if bone_lesions:
                metastasis_site = "Bone"
                metastasis_count = max(metastasis_count, bone_lesions)
        if "tac" in study_type:
            summary = str((findings or {}).get("ct_summary") or "")
            locations = (findings or {}).get("ct_locations", []) or []
            if summary == "Metástasis" or locations:
                metastasis_count = max(metastasis_count, len(locations) or 1)
                lowered = " ".join(str(item).lower() for item in locations)
                if "hueso" in lowered:
                    metastasis_site = "Bone"
                elif "ganglio" in lowered:
                    metastasis_site = "Node"
                else:
                    metastasis_site = "Visceral"
    return metastasis_site, metastasis_count


def _derive_progression_pattern(patient: dict[str, Any], state: str) -> str:
    followup = _latest(patient.get("follow_ups", []), "visit_date")
    disease_status = str(followup.get("disease_status") or "").lower()
    if "radiograf" in disease_status:
        return "radiographic"
    if "clinic" in disease_status:
        return "clinical"
    if "bioqu" in disease_status or "psa" in disease_status:
        return "biochemical_only"
    if state in {"m1_crpc"}:
        return "mixed"
    return "biochemical_only"


def _derive_current_adt_context(patient: dict[str, Any], state: str) -> str:
    treatment_text = _derive_current_treatment(patient).lower()
    if "orchiect" in treatment_text:
        return "orchiectomy"
    adt_tokens = ("leupro", "degarelix", "goserelin", "triptorelin", "relugolix", "castr")
    if any(token in treatment_text for token in adt_tokens):
        return "medical_adt_continuous"
    if state in ADVANCED_STATES | MHSPC_STATES:
        return "medical_adt_continuous"
    return "none"


def _derive_castrate_status(patient: dict[str, Any], state: str) -> str:
    followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_testosterone = _safe_float(followup.get("testosterone_current"))
    if latest_testosterone is None:
        latest_testosterone = _safe_float(patient.get("baseline", {}).get("testosterone_baseline"))
        if state in {"m0_crpc", "m1_crpc", "adt_progression_verification"} and latest_testosterone is not None:
            return "confirmed_castrate" if latest_testosterone <= 50 else "not_castrate"
        return "unknown"
    return "confirmed_castrate" if latest_testosterone <= 50 else "not_castrate"


def _derive_conventional_imaging_status(patient: dict[str, Any], state: str) -> str:
    imaging = patient.get("imaging") or []
    for study in imaging:
        study_type = str(study.get("study_type", "")).lower()
        findings = study.get("findings", {}) if isinstance(study.get("findings"), dict) else {}
        if "tac" in study_type:
            status = str(findings.get("conventional_imaging_status") or "")
            if status:
                return status.upper()
        if "gammagrama" in study_type and str(study.get("bone_scan_result", "")).lower().startswith("positivo"):
            return "M1"
    if state in {"m1_crpc"}:
        return "M1"
    if state in {"m0_crpc", "adt_progression_verification"}:
        return "M0"
    return "NOT_RESTAGED"


def build_state_classifier_payload(patient: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    state = _current_state(patient, latest_assessment)
    metastasis_site, metastasis_count = _derive_metastatic_context(patient)
    state_payload = {
        "known_cancer_diagnosis": 1 if _biopsy_confirms_cancer(patient) or state not in DIAGNOSTIC_STATES else 0,
        "prior_negative_biopsy": 1 if state == "post_negative_biopsy_followup" else 0,
        "prior_prostatectomy": 1 if patient.get("surgery") else 0,
        "prior_radiation": 1 if patient.get("radiation") else 0,
        "bcr2": 1 if str((patient.get("bcr") or {}).get("bcr_definition", "")).upper() == "BCR2" else 0,
        "metastasis_site": metastasis_site,
        "metastasis_count": metastasis_count,
        "volume_disease": (patient.get("baseline") or {}).get("volume_disease") or ("High" if metastasis_count >= 4 or metastasis_site == "Visceral" else "Low"),
        "metachronous_metastasis": 1 if state == "mcspc_oligo_metachronous" else 0,
        "psa_current": _safe_float(_latest(patient.get("follow_ups", []), "visit_date").get("psa_current")) or _safe_float((patient.get("bcr") or {}).get("bcr_psa")) or _safe_float((patient.get("baseline") or {}).get("baseline_psa")),
        "current_adt_context": _derive_current_adt_context(patient, state),
        "castrate_testosterone_status": _derive_castrate_status(patient, state),
        "progression_pattern": _derive_progression_pattern(patient, state),
        "conventional_imaging_status": _derive_conventional_imaging_status(patient, state),
        "line_of_therapy": (patient.get("treatments") or [{}])[-1].get("line_of_therapy", 1) if patient.get("treatments") else 1,
    }
    if state in {"m0_crpc", "m1_crpc"}:
        state_payload["systemic_progression_context"] = "confirmed_crpc"
    elif state == "adt_progression_verification":
        state_payload["systemic_progression_context"] = "progression_on_adt_verify_castration"
    else:
        state_payload["systemic_progression_context"] = "none"
    return state_payload


def _build_mcode_projection(patient: dict[str, Any], state: str, management_track: str) -> dict[str, Any]:
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    genomics = patient.get("genomics") or {}
    return {
        "condition": {
            "primary_diagnosis": state,
            "management_track": management_track,
            "stage": (patient.get("prior_history") or {}).get("current_state") or state,
        },
        "disease_status": latest_followup.get("disease_status") or "Seguimiento estable",
        "biomarkers": {
            "hrr_status": genomics.get("hrr_overall"),
            "brca2_status": genomics.get("brca2_status"),
            "msi_status": genomics.get("msi_status"),
            "decipher_risk": genomics.get("decipher_risk"),
        },
        "procedures": {
            "biopsies": len(patient.get("biopsies") or []),
            "imaging_studies": len(patient.get("imaging") or []),
            "surgery": bool(patient.get("surgery")),
            "radiation_courses": len(patient.get("radiation") or []),
        },
        "medications": {
            "current_treatment": _derive_current_treatment(patient),
            "prior_lines": len(patient.get("treatments") or []),
        },
        "provenance": {
            "items": len(patient.get("data_provenance") or []),
        },
    }


def build_clinical_signals(patient: dict[str, Any], latest_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    state = _current_state(patient, latest_assessment)
    management_track = infer_management_track(patient, state, latest_assessment or patient.get("latest_assessment"))
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    latest_mri = _latest(patient.get("mri_facts", []), "fact_date")
    latest_imaging = _latest(patient.get("imaging", []), "study_date")
    bcr = patient.get("bcr") or {}
    signals = []
    critical_missing = []
    awaiting_review = []
    active_safety = []

    psa = _safe_float(latest_followup.get("psa_current")) or _safe_float(bcr.get("bcr_psa")) or _safe_float((patient.get("baseline") or {}).get("baseline_psa"))
    testosterone = _safe_float(latest_followup.get("testosterone_current"))
    ecog = _safe_int(latest_followup.get("ecog_current"))
    pain = _safe_int(latest_followup.get("pain_score"))
    latest_mri_quality = latest_mri.get("mpmri_quality")
    pirads = latest_mri.get("pirads_score") or latest_imaging.get("pirads_score")
    psadt = _safe_float(bcr.get("psadt_at_bcr")) or _safe_float((latest_assessment or {}).get("input_snapshot", {}).get("psadt_months"))
    verified_document_types = {
        str(item.get("document_type") or "")
        for item in (patient.get("source_documents") or [])
        if str(item.get("verification_status") or "") == "verified"
    }

    if _is_present(psa):
        signals.append(
            {
                "key": "psa",
                "label": "PSA actual",
                "value": f"{psa:.2f} ng/mL",
                "status": "informative",
                "detail": "Último antígeno prostático específico disponible en el longitudinal.",
            }
        )
    if _is_present(testosterone) and state in ADVANCED_STATES | MHSPC_STATES:
        signals.append(
            {
                "key": "testosterone",
                "label": "Testosterona",
                "value": f"{testosterone:.1f} ng/dL",
                "status": "good" if testosterone <= 50 else "warning",
                "detail": "La enfermedad resistente a la castración requiere testosterona en rango de castración.",
            }
        )

    if state in DIAGNOSTIC_STATES:
        if not _is_present(latest_mri_quality):
            critical_missing.append("Resonancia magnética multiparamétrica utilizable")
        if not _is_present(psa):
            critical_missing.append("PSA o densidad de PSA actual")
        if patient.get("biopsy_triggers") and not patient.get("biopsies"):
            awaiting_review.append("Existe trigger de biopsia activo sin histología confirmada")
        if _safe_int(pirads) is not None and _safe_int(pirads) >= 4:
            signals.append(
                {
                    "key": "pirads_high",
                    "label": "PI-RADS alto",
                    "value": f"PI-RADS {pirads}",
                    "status": "warning",
                    "detail": "El hallazgo radiológico exige ruta diagnóstica acelerada y confirmación histológica.",
                }
            )

    if state == "localized_initial":
        if management_track == "active_surveillance" and not patient.get("pros"):
            critical_missing.append("PROs basales/seriales para vigilancia activa")
        if management_track == "active_surveillance" and not patient.get("biopsies"):
            critical_missing.append("Biopsia confirmatoria o seguimiento histológico")
        if patient.get("biopsies") and "pathology_report" not in verified_document_types:
            critical_missing.append("Reporte histopatológico completo verificable")
        if latest_biopsy:
            adverse_variant = str(latest_biopsy.get("adverse_histology_variant_type") or "none")
            if adverse_variant not in {"", "none"}:
                awaiting_review.append("Histología adversa tipificada requiere revisión de manejo local")
            if _safe_int(latest_biopsy.get("isup_grade")) and _safe_int(latest_biopsy.get("isup_grade")) >= 2:
                signals.append(
                    {
                        "key": "histologic_progression",
                        "label": "Progresión histológica",
                        "value": f"ISUP {latest_biopsy.get('isup_grade')}",
                        "status": "warning",
                        "detail": "La progresión histológica puede obligar salida de vigilancia activa.",
                    }
                )

    if state in POSTLOCAL_STATES:
        if not _is_present(psa):
            critical_missing.append("PSA ultrasensible actual")
        if patient.get("biopsies") and "pathology_report" not in verified_document_types:
            critical_missing.append("Reporte histopatológico completo verificable")
        if state == "post_prostatectomy" and psa is not None and psa >= 0.2:
            signals.append(
                {
                    "key": "possible_bcr",
                    "label": "Señal de recurrencia bioquímica",
                    "value": f"PSA {psa:.2f} ng/mL",
                    "status": "warning",
                    "detail": "La elevación posoperatoria sugiere reestadificación y evaluación de rescate.",
                }
            )
        if state == "recurrence_bcr":
            if not _is_present(psadt):
                critical_missing.append("Tiempo de duplicación del PSA (PSADT)")
            if not patient.get("imaging"):
                awaiting_review.append("No existe imagen estructurada para decidir rescate o transición")

    if state in ADVANCED_STATES | MHSPC_STATES:
        if _derive_castrate_status(patient, state) == "unknown":
            critical_missing.append("Testosterona actual para contexto avanzado")
        if not patient.get("genomics"):
            critical_missing.append("Biomarcadores accionables documentados")
        if "genomic_report" not in verified_document_types:
            critical_missing.append("Resultado molecular verificable para PARP / biomarcadores")
        if ecog is not None and ecog >= 2:
            active_safety.append("Estado funcional comprometido; ajustar intensidad terapéutica")
        if pain is not None and pain >= 7:
            active_safety.append("Dolor significativo; activar overlay paliativo concurrente")
        if str(latest_followup.get("hepatic_risk_status") or latest_followup.get("hepatic_risk_factors") or "").strip():
            active_safety.append("Riesgo hepático activo")
        if str(latest_followup.get("cv_risk_status") or "").strip():
            active_safety.append("Riesgo cardiovascular activo")
        if _safe_int(latest_followup.get("seizure_history")) == 1:
            active_safety.append("Antecedente convulsivo relevante para selección de ARPI")
        if _safe_int(latest_followup.get("dermatitis_history")) == 1:
            active_safety.append("Dermatitis/rash previo relevante para selección de ARPI")
        if management_track == "on_lu177" and not patient.get("imaging"):
            critical_missing.append("PSMA-PET válido para sostener elegibilidad a Lutecio-177")
        elif any("psma" in str(item.get("study_type", "")).lower() for item in (patient.get("imaging") or [])) and "imaging_report" not in verified_document_types:
            critical_missing.append("Informe PSMA-PET verificable")

    ready_to_restage = bool(awaiting_review) or any(item.get("status") == "warning" for item in signals if item.get("key") in {"possible_bcr", "histologic_progression"})
    return ClinicalSignalSet(
        state=state,
        management_track=management_track,
        ready_to_restage=ready_to_restage,
        signals=signals,
        critical_missing=critical_missing,
        awaiting_review=awaiting_review,
        active_safety=active_safety,
        mcode_projection=_build_mcode_projection(patient, state, management_track),
        evidence_basis=COMMON_EVIDENCE,
    ).to_dict()


def build_state_transition_proposals(
    patient: dict[str, Any],
    signals: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    current_state = signals.get("state") or _current_state(patient, latest_assessment)
    current_track = signals.get("management_track") or infer_management_track(patient, current_state, latest_assessment or patient.get("latest_assessment"))
    proposals: list[dict[str, Any]] = []
    latest_biopsy = _latest(patient.get("biopsies", []), "biopsy_date")
    latest_followup = _latest(patient.get("follow_ups", []), "visit_date")
    psa = _safe_float(latest_followup.get("psa_current")) or _safe_float((patient.get("bcr") or {}).get("bcr_psa"))
    registry = ModuleRegistry()
    classifier_payload = build_state_classifier_payload(patient, latest_assessment)
    classifier_target = registry.classify_state(classifier_payload).get("state")

    if current_state in DIAGNOSTIC_STATES and _biopsy_confirms_cancer(patient):
        proposals.append(
            StateTransitionProposal(
                proposal_key=f"{current_state}:localized_after_histology",
                from_state=current_state,
                from_management_track=current_track,
                target_state="localized_initial",
                target_management_track="localized_decision",
                priority="high",
                rationale="Ya existe histología confirmatoria compatible con cáncer de próstata y el caso debe pasar a estratificación localizada/regional.",
                trigger_signals=["Histología confirmada", "Ruta diagnóstica completada"],
                next_actions=["Confirmar transición a evaluación localizada", "Revisar grupo de riesgo y nomogramas quirúrgicos/locales"],
                evidence_basis=COMMON_EVIDENCE,
            ).to_dict()
        )

    adverse_histology = str(latest_biopsy.get("adverse_histology_variant_type") or "none")
    biopsy_upgrade = _safe_int(latest_biopsy.get("isup_grade")) or 0
    if current_track == "active_surveillance" and (
        biopsy_upgrade >= 2
        or _safe_int(latest_biopsy.get("carcinoma_intraductal")) == 1
        or _safe_int(latest_biopsy.get("patron_cribiforme")) == 1
        or adverse_histology not in {"", "none"}
    ):
        proposals.append(
            StateTransitionProposal(
                proposal_key="localized_initial:exit_active_surveillance",
                from_state="localized_initial",
                from_management_track=current_track,
                target_state="localized_initial",
                target_management_track="localized_decision",
                priority="high",
                rationale="La vigilancia activa ya no parece segura por progresión histológica o histología adversa documentada.",
                trigger_signals=["Progresión histológica", "Histología adversa"],
                next_actions=["Confirmar salida de vigilancia activa", "Rediscutir cirugía o radioterapia definitiva"],
                evidence_basis=COMMON_EVIDENCE,
            ).to_dict()
        )

    if current_state == "post_prostatectomy" and psa is not None and psa >= 0.2:
        proposals.append(
            StateTransitionProposal(
                proposal_key="post_prostatectomy:to_recurrence_bcr",
                from_state="post_prostatectomy",
                from_management_track=current_track,
                target_state="recurrence_bcr",
                target_management_track="salvage",
                priority="high",
                rationale="El PSA post prostatectomía sugiere recurrencia bioquímica y obliga reabrir la ruta de rescate.",
                trigger_signals=["PSA posoperatorio compatible con recurrencia"],
                next_actions=["Confirmar etapa de recurrencia bioquímica", "Recalcular PSADT y factibilidad de rescate"],
                evidence_basis=COMMON_EVIDENCE,
            ).to_dict()
        )

    if classifier_target and classifier_target != current_state and not (
        current_state == "localized_initial" and classifier_target == "localized_initial"
    ):
        rationale = registry.classify_state(classifier_payload).get("classification_reason") or "La nueva información cambia la etapa clínica probable."
        proposals.append(
            StateTransitionProposal(
                proposal_key=f"{current_state}:{classifier_target}:classifier",
                from_state=current_state,
                from_management_track=current_track,
                target_state=classifier_target,
                target_management_track=infer_management_track(patient, classifier_target, latest_assessment or patient.get("latest_assessment")),
                priority="high" if classifier_target in ADVANCED_STATES else "routine",
                rationale=rationale,
                trigger_signals=signals.get("awaiting_review", [])[:2] or ["Señales longitudinales compatibles con cambio de etapa"],
                next_actions=[
                    f"Confirmar transición a {classifier_target}",
                    "Actualizar recomendación modular y agenda después de la confirmación",
                ],
                evidence_basis=COMMON_EVIDENCE,
            ).to_dict()
        )

    deduped: list[dict[str, Any]] = []
    seen = set()
    for item in proposals:
        key = item.get("proposal_key")
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def build_next_best_action(
    patient: dict[str, Any],
    signals: dict[str, Any],
    proposals: list[dict[str, Any]],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = signals.get("state") or _current_state(patient, latest_assessment)
    management_track = signals.get("management_track") or infer_management_track(patient, state, latest_assessment or patient.get("latest_assessment"))
    agenda = build_agenda_board(patient, state, management_track, latest_assessment or patient.get("latest_assessment"))
    due_titles = [item.get("title") for item in agenda.get("items", []) if item.get("status") in {"due", "overdue"}][:3]
    checkpoint_actions = [item.get("action") for item in agenda.get("therapy_checkpoints", []) if item.get("status") in {"attention", "ready"} and item.get("action")][:2]
    result = (latest_assessment or patient.get("latest_assessment") or {}).get("result_snapshot", {})
    eligible = result.get("eligible_treatments", []) or []
    recommended_option = ""
    if eligible:
        first = eligible[0]
        recommended_option = str(first.get("name") if isinstance(first, dict) else first)
    recommendation_family = (result.get("decision_quality", {}) or {}).get("recommendation_family") or state

    if proposals:
        proposal = proposals[0]
        actions = proposal.get("next_actions", [])[:]
        actions.extend(due_titles)
        return NextBestAction(
            title=f"Confirmar transición a {proposal.get('target_state')}",
            recommendation_family=recommendation_family,
            rationale=proposal.get("rationale") or "La nueva información longitudinal ya cambió la etapa clínica esperada.",
            immediate_actions=[item for item in actions if item][:3],
            data_that_could_change_course=(signals.get("critical_missing") or [])[:3],
            contraindication_modifiers=(signals.get("active_safety") or [])[:3],
            evidence_basis=proposal.get("evidence_basis") or COMMON_EVIDENCE,
        ).to_dict()

    if state in DIAGNOSTIC_STATES:
        title = "Completar confirmación histológica y cerrar la ruta diagnóstica"
        rationale = "La etapa diagnóstica solo progresa con histología confirmada y MRI utilizable."
    elif state == "localized_initial":
        title = "Mantener o redefinir la estrategia local según riesgo y función"
        rationale = "La decisión local depende de patología, MRI, PROs y algoritmos contextuales."
    elif state in POSTLOCAL_STATES:
        title = "Revisar ventana de rescate y control bioquímico"
        rationale = "El seguimiento post tratamiento local exige PSA ultrasensible, PSADT e imagen solo si cambia la conducta."
    else:
        title = "Reevaluar secuencia sistémica y seguridad activa"
        rationale = "La enfermedad avanzada debe balancear elegibilidad terapéutica, biomarcadores y toxicidad."

    immediate_actions = due_titles + checkpoint_actions
    if not immediate_actions and signals.get("critical_missing"):
        immediate_actions = signals.get("critical_missing", [])[:3]
    return NextBestAction(
        title=title,
        recommendation_family=recommendation_family,
        rationale=rationale,
        immediate_actions=immediate_actions[:3],
        data_that_could_change_course=(signals.get("critical_missing") or [])[:3],
        contraindication_modifiers=(signals.get("active_safety") or [])[:3],
        evidence_basis=COMMON_EVIDENCE,
    ).to_dict()


def build_recommendation_audit(
    patient_id: int,
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None,
    event_id: int | None = None,
) -> dict[str, Any] | None:
    assessment = latest_assessment or patient.get("latest_assessment") or {}
    result = assessment.get("result_snapshot", {}) or {}
    eligible = result.get("eligible_treatments", []) or []
    recommended_option = ""
    if eligible:
        first = eligible[0]
        recommended_option = str(first.get("name") if isinstance(first, dict) else first)
    recommendation_family = (result.get("decision_quality", {}) or {}).get("recommendation_family") or result.get("state") or assessment.get("state") or ""
    if not recommendation_family and not recommended_option:
        return None
    selected_option = _derive_current_treatment(patient)
    discordance_reason = ""
    if recommended_option and selected_option and recommended_option.lower() not in selected_option.lower():
        discordance_reason = "La exposición terapéutica actual no coincide con la recomendación modular vigente."
    elif recommended_option and not selected_option:
        discordance_reason = "Aún no existe selección terapéutica documentada."
    return RecommendationAudit(
        patient_id=patient_id,
        assessment_id=assessment.get("id"),
        event_id=event_id,
        recommendation_family=recommendation_family,
        recommended_option=recommended_option or assessment.get("state") or "",
        selected_option=selected_option,
        discordance_reason=discordance_reason,
        outcome_snapshot={
            "state": assessment.get("state"),
            "management_track": infer_management_track(patient, assessment.get("state") or "", assessment),
        },
    ).to_dict()


def build_longitudinal_intelligence_bundle(
    patient: dict[str, Any],
    latest_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signals = build_clinical_signals(patient, latest_assessment)
    proposals = build_state_transition_proposals(patient, signals, latest_assessment)
    next_best_action = build_next_best_action(patient, signals, proposals, latest_assessment)
    return {
        "signals": signals,
        "transition_proposals": proposals,
        "next_best_action": next_best_action,
    }
