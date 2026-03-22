from __future__ import annotations

from copy import deepcopy
from typing import Any

from prostanet.domains.clinical_assessments.scenario_harness import SCENARIO_LIBRARY


_MODULE_SCENARIOS = {item["scenario_id"]: deepcopy(item) for item in SCENARIO_LIBRARY}


def _module_payload(scenario_id: str, **overrides: Any) -> dict[str, Any]:
    payload = deepcopy((_MODULE_SCENARIOS.get(scenario_id) or {}).get("payload") or {})
    payload.update({key: value for key, value in overrides.items() if value is not None})
    return payload


def _module_id(scenario_id: str, fallback: str) -> str:
    return str((_MODULE_SCENARIOS.get(scenario_id) or {}).get("module_id") or fallback)


def _visit(
    visit_date: str,
    title: str,
    payload: dict[str, Any],
    oracle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "visit_date": visit_date,
        "title": title,
        "payload": {"visit_date": visit_date, **payload},
        "oracle": oracle,
    }


def _trajectory(
    *,
    scenario_id: str,
    title: str,
    scenario_family: str,
    module_id: str,
    baseline_payload: dict[str, Any],
    baseline_oracle: dict[str, Any],
    visits: list[dict[str, Any]],
    clinical_oracle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "title": title,
        "scenario_family": scenario_family,
        "module_id": module_id,
        "baseline_payload": baseline_payload,
        "baseline_oracle": baseline_oracle,
        "visits": visits,
        "clinical_oracle": clinical_oracle,
    }


def _diagnostic_workup_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="diagnostic_low_psa_recheck",
            title="Diagnóstico de sospecha baja con revaloración seriada",
            scenario_family="diagnostic_workup",
            module_id=_module_id("diagnostic_low_surveillance", "diagnostic_workup"),
            baseline_payload=_module_payload("diagnostic_low_surveillance"),
            baseline_oracle={"expected_effective_state": "diagnostic_workup"},
            visits=[
                _visit(
                    "2026-01-15",
                    "Persisten datos incompletos para rebiopsia",
                    {"psa": 4.8, "psad": 0.09},
                    {"expected_missing_inputs": ["pirads_score", "dre_suspicious"], "expected_effective_state": "diagnostic_workup"},
                ),
                _visit(
                    "2026-04-15",
                    "MRI y PSA velocity sostienen vigilancia",
                    {"psa": 4.7, "psad": 0.08, "pirads_score": 2, "dre_suspicious": 0, "psa_velocity_ng_ml_year": 0.2},
                    {"expected_effective_state": "diagnostic_workup", "expected_action_contains": "seguimiento", "expected_schedule_keywords": ["PSA", "MRI"]},
                ),
            ],
            clinical_oracle={"expected_effective_state": "diagnostic_workup", "expected_action_contains": "seguimiento", "expected_guideline_basis_any": ["NCCN 2026 diagnóstico"]},
        ),
        _trajectory(
            scenario_id="diagnostic_high_targeted_biopsy",
            title="Diagnóstico de alta sospecha con biopsia dirigida",
            scenario_family="diagnostic_workup",
            module_id=_module_id("diagnostic_high_biopsy", "diagnostic_workup"),
            baseline_payload=_module_payload("diagnostic_high_biopsy"),
            baseline_oracle={"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia"},
            visits=[
                _visit(
                    "2026-01-10",
                    "Falta ruta de biopsia y contexto MRI completo",
                    {"psa": 10.9, "psad": 0.23, "pirads_score": 4},
                    {"expected_missing_inputs": ["dre_suspicious"], "expected_action_contains": "biopsia"},
                ),
                _visit(
                    "2026-01-24",
                    "Biopsia dirigida confirmada como siguiente paso",
                    {"psa": 11.2, "psad": 0.24, "pirads_score": 5, "dre_suspicious": 1, "planned_biopsy_route": "Transperineal"},
                    {"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia", "expected_schedule_keywords": ["biopsia"]},
                ),
            ],
            clinical_oracle={"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia", "expected_guideline_basis_any": ["NCCN 2026 diagnóstico"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="diagnostic_mri_negative_psad_high",
            title="MRI negativa con PSAD alta obliga reapertura diagnóstica",
            scenario_family="diagnostic_workup",
            module_id="diagnostic_workup",
            baseline_payload=_module_payload(
                "diagnostic_low_surveillance",
                psa=5.9,
                psad=0.18,
                pirads_score=2,
                dre_suspicious=0,
                family_history_positive=1,
            ),
            baseline_oracle={"expected_effective_state": "diagnostic_workup"},
            visits=[
                _visit(
                    "2026-02-05",
                    "Persisten datos faltantes para decidir nueva biopsia",
                    {"psa": 6.2, "psad": 0.19},
                    {"expected_missing_inputs": ["pirads_score", "dre_suspicious"], "expected_action_contains": "estudio"},
                ),
                _visit(
                    "2026-05-05",
                    "PSAD alta sostenida y heredofamiliar reabren biopsia",
                    {"psa": 6.5, "psad": 0.21, "pirads_score": 2, "dre_suspicious": 1},
                    {"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia", "expected_schedule_keywords": ["biopsia", "PSA"]},
                ),
            ],
            clinical_oracle={"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia", "expected_guideline_basis_any": ["NCCN 2026 diagnóstico"]},
        ),
        _trajectory(
            scenario_id="diagnostic_hereditary_precision_path",
            title="Sospecha diagnóstica con antecedente hereditario relevante",
            scenario_family="diagnostic_workup",
            module_id="diagnostic_workup",
            baseline_payload=_module_payload(
                "diagnostic_high_biopsy",
                psa=8.8,
                psad=0.17,
                pirads_score=3,
                family_history_positive=1,
                germline_risk_mutation=1,
            ),
            baseline_oracle={"expected_effective_state": "diagnostic_workup"},
            visits=[
                _visit(
                    "2026-02-12",
                    "Faltan datos DRE/MRI para precisar el trigger",
                    {"psa": 8.9, "psad": 0.18},
                    {"expected_missing_inputs": ["pirads_score", "dre_suspicious"], "expected_action_contains": "biopsia"},
                ),
                _visit(
                    "2026-03-12",
                    "Antecedente hereditario acelera confirmación histológica",
                    {"psa": 9.3, "psad": 0.19, "pirads_score": 4, "dre_suspicious": 1},
                    {"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia", "expected_schedule_keywords": ["biopsia"]},
                ),
            ],
            clinical_oracle={"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia", "expected_guideline_basis_any": ["NCCN 2026 diagnóstico"]},
        ),
        _trajectory(
            scenario_id="diagnostic_prebiopsy_biomarker",
            title="Biomarcador prebiopsia modifica el umbral de intervención",
            scenario_family="diagnostic_workup",
            module_id="diagnostic_workup",
            baseline_payload=_module_payload(
                "diagnostic_low_surveillance",
                psa=5.7,
                psad=0.14,
                pirads_score=3,
                dre_suspicious=0,
                phi_score=45,
            ),
            baseline_oracle={"expected_effective_state": "diagnostic_workup"},
            visits=[
                _visit(
                    "2026-02-20",
                    "Falta DRE para cerrar decisión prebiopsia",
                    {"psa": 5.9, "psad": 0.15, "phi_score": 47},
                    {"expected_missing_inputs": ["dre_suspicious"], "expected_action_contains": "seguimiento"},
                ),
                _visit(
                    "2026-04-20",
                    "Biomarcador alto + DRE dudoso empuja biopsia",
                    {"psa": 6.3, "psad": 0.17, "pirads_score": 3, "dre_suspicious": 1, "phi_score": 49},
                    {"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia", "expected_schedule_keywords": ["biopsia"]},
                ),
            ],
            clinical_oracle={"expected_effective_state": "diagnostic_workup", "expected_action_contains": "biopsia", "expected_guideline_basis_any": ["NCCN 2026 diagnóstico"]},
        ),
    ]


def _post_negative_biopsy_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="post_negative_biopsy_stable_surveillance",
            title="Seguimiento estable tras biopsia negativa",
            scenario_family="post_negative_biopsy_followup",
            module_id=_module_id("benign_followup_low", "post_negative_biopsy_followup"),
            baseline_payload=_module_payload("benign_followup_low"),
            baseline_oracle={"expected_effective_state": "post_negative_biopsy_followup"},
            visits=[
                _visit("2026-02-01", "Persisten faltantes mínimos", {"psa": 4.3, "psad": 0.09}, {"expected_missing_inputs": ["pirads_score", "prior_biopsy_count"]}),
                _visit("2026-08-01", "Seguimiento conservador sostenido", {"psa": 4.4, "psad": 0.09, "pirads_score": 2, "prior_biopsy_count": 1}, {"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "seguimiento"}),
            ],
            clinical_oracle={"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "seguimiento", "expected_guideline_basis_any": ["NCCN 2026 early detection"]},
        ),
        _trajectory(
            scenario_id="post_negative_biopsy_reopen_due_to_mri",
            title="Reapertura diagnóstica por lesión persistente",
            scenario_family="post_negative_biopsy_followup",
            module_id=_module_id("benign_followup_reopen", "post_negative_biopsy_followup"),
            baseline_payload=_module_payload("benign_followup_reopen"),
            baseline_oracle={"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "reabrir"},
            visits=[
                _visit("2026-01-18", "Faltan datos de MRI dirigida", {"psa": 8.7, "psad": 0.17, "prior_biopsy_count": 2}, {"expected_missing_inputs": ["pirads_score", "dre_suspicious"]}),
                _visit("2026-02-18", "Lesión persistente obliga nueva biopsia dirigida", {"psa": 9.1, "psad": 0.18, "pirads_score": 4, "dre_suspicious": 1, "persistent_lesion_signal": 1}, {"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "biopsia", "expected_schedule_keywords": ["biopsia"]}),
            ],
            clinical_oracle={"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "biopsia", "expected_guideline_basis_any": ["EAU 2026 repeat biopsy"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="post_negative_biopsy_repeat_targeted",
            title="Biopsia dirigida repetida tras falso negativo previo",
            scenario_family="post_negative_biopsy_followup",
            module_id="post_negative_biopsy_followup",
            baseline_payload=_module_payload("benign_followup_reopen", prior_biopsy_mri_targeted=0, pirads_score=5),
            baseline_oracle={"expected_effective_state": "post_negative_biopsy_followup"},
            visits=[
                _visit("2026-03-01", "Falta documentar targeting previo", {"psa": 9.0, "psad": 0.18}, {"expected_missing_inputs": ["prior_biopsy_count", "pirads_score"]}),
                _visit("2026-04-01", "Nueva biopsia dirigida con MRI/TRUS", {"psa": 9.4, "psad": 0.2, "pirads_score": 5, "prior_biopsy_count": 2, "persistent_lesion_signal": 1}, {"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "biopsia"}),
            ],
            clinical_oracle={"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "biopsia", "expected_guideline_basis_any": ["NCCN 2026 early detection"]},
        ),
        _trajectory(
            scenario_id="post_negative_biopsy_psa_rise_without_mri",
            title="Ascenso de PSA sin MRI suficiente reabre estudio",
            scenario_family="post_negative_biopsy_followup",
            module_id="post_negative_biopsy_followup",
            baseline_payload=_module_payload("benign_followup_low", psa=5.8, psad=0.14, prior_biopsy_count=1),
            baseline_oracle={"expected_effective_state": "post_negative_biopsy_followup"},
            visits=[
                _visit("2026-04-05", "Falta MRI y DRE antes de redefinir", {"psa": 6.5, "psad": 0.16}, {"expected_missing_inputs": ["pirads_score", "dre_suspicious"]}),
                _visit("2026-06-05", "Nueva lesión MRI redefine ruta", {"psa": 6.8, "psad": 0.17, "pirads_score": 4, "dre_suspicious": 1}, {"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "estudio"}),
            ],
            clinical_oracle={"expected_effective_state": "post_negative_biopsy_followup", "expected_action_contains": "estudio", "expected_guideline_basis_any": ["EAU 2026 repeat biopsy"]},
        ),
    ]


def _localized_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="localized_very_low_active_surveillance",
            title="Muy bajo riesgo con vigilancia activa estructurada",
            scenario_family="localized_initial",
            module_id=_module_id("localized_low_as", "localized_initial"),
            baseline_payload=_module_payload("localized_low_as"),
            baseline_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "Active surveillance"},
            visits=[
                _visit("2026-03-01", "Faltan campos confirmatorios de VA", {"psa": 5.0, "clinical_tstage": "T1c"}, {"expected_missing_inputs": ["gleason_primary", "gleason_secondary", "isup_grade"]}),
                _visit("2026-09-01", "Seguimiento conserva vigilancia activa", {"psa": 5.1, "gleason_primary": 3, "gleason_secondary": 3, "isup_grade": 1, "confirmatory_biopsy_done": 1}, {"expected_effective_state": "localized_initial", "expected_action_contains": "surveillance"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "surveillance", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
        _trajectory(
            scenario_id="localized_low_risk_definitive_choice",
            title="Bajo riesgo con decisión entre vigilancia y tratamiento definitivo",
            scenario_family="localized_initial",
            module_id="localized_initial",
            baseline_payload=_module_payload("localized_low_as", psa=6.4, psad=0.14, num_cores_positive=3, max_core_involvement=0.35),
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-03-15", "Faltan datos patológicos finos", {"psa": 6.5}, {"expected_missing_inputs": ["clinical_tstage", "gleason_primary", "gleason_secondary"]}),
                _visit("2026-07-15", "Carga tumoral favorece tratamiento local", {"psa": 6.9, "clinical_tstage": "T2a", "gleason_primary": 3, "gleason_secondary": 3, "isup_grade": 1, "num_cores_positive": 4}, {"expected_effective_state": "localized_initial", "expected_action_contains": "tratamiento"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "tratamiento", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
        _trajectory(
            scenario_id="localized_favorable_intermediate",
            title="Intermedio favorable con decisión compartida",
            scenario_family="localized_initial",
            module_id="localized_initial",
            baseline_payload=_module_payload("localized_unfavorable", gleason_primary=3, gleason_secondary=4, isup_grade=2, percent_pattern_4=10, num_cores_positive=3),
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-02-28", "Faltan datos de carga tumoral", {"psa": 8.9, "clinical_tstage": "T2a"}, {"expected_missing_inputs": ["gleason_primary", "gleason_secondary", "isup_grade"]}),
                _visit("2026-06-28", "Reclasificación mantiene intermedio favorable", {"psa": 8.7, "clinical_tstage": "T2a", "gleason_primary": 3, "gleason_secondary": 4, "isup_grade": 2, "num_cores_positive": 3}, {"expected_effective_state": "localized_initial", "expected_action_contains": "RT"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "RT", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
        _trajectory(
            scenario_id="localized_unfavorable_rt_adt",
            title="Intermedio desfavorable con RT + ADT",
            scenario_family="localized_initial",
            module_id=_module_id("localized_unfavorable", "localized_initial"),
            baseline_payload=_module_payload("localized_unfavorable"),
            baseline_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "RT"},
            visits=[
                _visit("2026-01-30", "Aún faltan variables de estadificación", {"psa": 9.8, "clinical_tstage": "T2b"}, {"expected_missing_inputs": ["gleason_primary", "gleason_secondary", "isup_grade"]}),
                _visit("2026-04-30", "Se mantiene indicación de RT + ADT", {"psa": 10.1, "clinical_tstage": "T2b", "gleason_primary": 4, "gleason_secondary": 3, "isup_grade": 3}, {"expected_effective_state": "localized_initial", "expected_action_contains": "RT", "expected_schedule_keywords": ["PSA"]}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "RT", "expected_guideline_basis_any": ["NCCN 2026 localized disease"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="localized_high_risk_multimodal",
            title="Alto riesgo localizado con discusión multimodal",
            scenario_family="localized_initial",
            module_id="localized_initial",
            baseline_payload=_module_payload("localized_unfavorable", psa=18.4, clinical_tstage="T3a", gleason_primary=4, gleason_secondary=4, isup_grade=4, percent_pattern_4=60),
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-02-08", "Se requieren datos completos de carga tumoral", {"psa": 18.9, "clinical_tstage": "T3a"}, {"expected_missing_inputs": ["gleason_primary", "gleason_secondary", "isup_grade"]}),
                _visit("2026-03-08", "Alta agresividad favorece multimodalidad", {"psa": 19.1, "clinical_tstage": "T3a", "gleason_primary": 4, "gleason_secondary": 4, "isup_grade": 4}, {"expected_effective_state": "localized_initial", "expected_action_contains": "ADT"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "ADT", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
        _trajectory(
            scenario_id="localized_very_high_with_nodal_risk",
            title="Muy alto riesgo con riesgo nodal elevado",
            scenario_family="localized_initial",
            module_id="localized_initial",
            baseline_payload=_module_payload("localized_unfavorable", psa=24.5, clinical_tstage="T3b", gleason_primary=5, gleason_secondary=4, isup_grade=5, nodal_status="N0"),
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-02-18", "Faltan confirmaciones patológicas", {"psa": 25.0, "clinical_tstage": "T3b"}, {"expected_missing_inputs": ["gleason_primary", "gleason_secondary", "isup_grade"]}),
                _visit("2026-04-18", "Persisten criterios de muy alto riesgo", {"psa": 25.4, "clinical_tstage": "T3b", "gleason_primary": 5, "gleason_secondary": 4, "isup_grade": 5}, {"expected_effective_state": "localized_initial", "expected_action_contains": "ADT"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "ADT", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
        _trajectory(
            scenario_id="localized_variant_histology_review",
            title="Variante histológica agresiva obliga revisión humana",
            scenario_family="localized_initial",
            module_id=_module_id("localized_variant_escalate", "localized_initial"),
            baseline_payload=_module_payload("localized_variant_escalate"),
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-03-03", "Faltan datos completos de variante", {"psa": 7.4}, {"expected_missing_inputs": ["clinical_tstage", "gleason_primary", "gleason_secondary"]}),
                _visit("2026-04-03", "La variante agresiva mantiene revisión humana", {"psa": 7.8, "clinical_tstage": "T2a", "gleason_primary": 3, "gleason_secondary": 4, "isup_grade": 2, "histology_subtype": "small_cell_neuroendocrine"}, {"expected_effective_state": "localized_initial", "expected_action_contains": "review"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "review", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
    ]


def _active_surveillance_cases() -> list[dict[str, Any]]:
    base = _module_payload("localized_low_as")
    return [
        _trajectory(
            scenario_id="active_surveillance_entry",
            title="Ingreso formal a vigilancia activa",
            scenario_family="active_surveillance",
            module_id="localized_initial",
            baseline_payload=base,
            baseline_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "surveillance"},
            visits=[
                _visit("2026-06-01", "Falta confirmatory biopsy para sostener AS", {"psa": 5.2, "management_track": "active_surveillance"}, {"expected_missing_inputs": ["confirmatory_biopsy_done", "mri_interval_months", "num_cores_positive"]}),
                _visit("2026-09-01", "Confirmatory biopsy mantiene AS", {"psa": 5.0, "management_track": "active_surveillance", "confirmatory_biopsy_done": 1, "mri_interval_months": 12, "num_cores_positive": 2}, {"expected_effective_state": "localized_initial", "expected_action_contains": "surveillance", "expected_schedule_keywords": ["MRI", "PSA"]}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "surveillance", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
        _trajectory(
            scenario_id="active_surveillance_confirmatory_overdue",
            title="Vigilancia activa con biopsia confirmatoria vencida",
            scenario_family="active_surveillance",
            module_id="localized_initial",
            baseline_payload=base,
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-07-01", "Biopsia confirmatoria ya vencida", {"psa": 5.4, "management_track": "active_surveillance", "confirmatory_biopsy_done": 0}, {"expected_missing_inputs": ["confirmatory_biopsy_done", "mri_interval_months"]}),
                _visit("2026-10-01", "Se programa rebiopsia por atraso", {"psa": 5.6, "management_track": "active_surveillance", "confirmatory_biopsy_done": 0, "mri_interval_months": 18}, {"expected_effective_state": "localized_initial", "expected_action_contains": "biopsia"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "biopsia", "expected_guideline_basis_any": ["NCCN 2026 localized disease"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="active_surveillance_mri_new_lesion",
            title="Nueva lesión MRI durante vigilancia activa",
            scenario_family="active_surveillance",
            module_id="localized_initial",
            baseline_payload=base,
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-06-15", "MRI aún incompleta", {"psa": 5.5, "management_track": "active_surveillance"}, {"expected_missing_inputs": ["confirmatory_biopsy_done", "mri_interval_months"]}),
                _visit("2026-08-15", "Lesión PIRADS 4 reabre evaluación", {"psa": 5.8, "management_track": "active_surveillance", "confirmatory_biopsy_done": 1, "mri_interval_months": 12, "pirads_score": 4}, {"expected_effective_state": "localized_initial", "expected_action_contains": "biopsia"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "biopsia", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
        _trajectory(
            scenario_id="active_surveillance_upgrade_conversion",
            title="Upgrade histológico convierte a tratamiento",
            scenario_family="active_surveillance",
            module_id="localized_initial",
            baseline_payload=base,
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-05-20", "Aún faltan datos de rebiopsia", {"psa": 5.7, "management_track": "active_surveillance"}, {"expected_missing_inputs": ["confirmatory_biopsy_done", "num_cores_positive"]}),
                _visit("2026-07-20", "Upgrade a patrón 4 obliga salida de AS", {"psa": 6.1, "management_track": "active_surveillance", "confirmatory_biopsy_done": 1, "gleason_primary": 3, "gleason_secondary": 4, "isup_grade": 2, "num_cores_positive": 4, "upgrade_detected": 1}, {"expected_effective_state": "localized_initial", "expected_action_contains": "tratamiento"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "tratamiento", "expected_guideline_basis_any": ["NCCN 2026 localized disease"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="active_surveillance_volume_trigger",
            title="Aumento de volumen tumoral durante AS",
            scenario_family="active_surveillance",
            module_id="localized_initial",
            baseline_payload=base,
            baseline_oracle={"expected_effective_state": "localized_initial"},
            visits=[
                _visit("2026-05-10", "Falta cuantificar volumen tumoral", {"psa": 5.6, "management_track": "active_surveillance"}, {"expected_missing_inputs": ["confirmatory_biopsy_done", "num_cores_positive"]}),
                _visit("2026-08-10", "Aumento de cilindros positivos sugiere conversión", {"psa": 6.0, "management_track": "active_surveillance", "confirmatory_biopsy_done": 1, "num_cores_positive": 5, "max_core_involvement": 0.45}, {"expected_effective_state": "localized_initial", "expected_action_contains": "tratamiento"}),
            ],
            clinical_oracle={"expected_effective_state": "localized_initial", "expected_action_contains": "tratamiento", "expected_guideline_basis_any": ["NCCN 2026 localized disease"]},
        ),
    ]


def _post_prostatectomy_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="post_prostatectomy_stable",
            title="Post-RP estable con PSA indetectable",
            scenario_family="post_prostatectomy",
            module_id=_module_id("post_rp_surveillance", "post_prostatectomy"),
            baseline_payload=_module_payload("post_rp_surveillance"),
            baseline_oracle={"expected_effective_state": "post_prostatectomy"},
            visits=[
                _visit("2026-02-01", "Falta PSA ultrasensible seriado", {"psa": 0.02}, {"expected_missing_inputs": ["psa_postop", "pathologic_stage"]}),
                _visit("2026-08-01", "Continúa vigilancia rutinaria", {"psa": 0.01, "psa_postop": 0.01, "pathologic_stage": "pT2", "surgical_margin": 0}, {"expected_effective_state": "post_prostatectomy", "expected_action_contains": "vigilancia"}),
            ],
            clinical_oracle={"expected_effective_state": "post_prostatectomy", "expected_action_contains": "vigilancia", "expected_guideline_basis_any": ["NCCN 2026 post-prostatectomy"]},
        ),
        _trajectory(
            scenario_id="post_prostatectomy_adverse_features",
            title="Post-RP con patología adversa que intensifica vigilancia",
            scenario_family="post_prostatectomy",
            module_id=_module_id("post_rp_adverse", "post_prostatectomy"),
            baseline_payload=_module_payload("post_rp_adverse"),
            baseline_oracle={"expected_effective_state": "post_prostatectomy"},
            visits=[
                _visit("2026-02-10", "Faltan datos de patología completa", {"psa": 0.03}, {"expected_missing_inputs": ["pathologic_stage", "surgical_margin"]}),
                _visit("2026-05-10", "Patología adversa persiste, vigilancia estrecha", {"psa": 0.04, "psa_postop": 0.04, "pathologic_stage": "pT3a", "surgical_margin": 1, "decipher_risk": "Alto"}, {"expected_effective_state": "post_prostatectomy", "expected_action_contains": "salvage"}),
            ],
            clinical_oracle={"expected_effective_state": "post_prostatectomy", "expected_action_contains": "salvage", "expected_guideline_basis_any": ["EAU 2026 salvage window"]},
        ),
        _trajectory(
            scenario_id="post_prostatectomy_positive_margin",
            title="Post-RP con margen positivo y seguimiento dirigido",
            scenario_family="post_prostatectomy",
            module_id="post_prostatectomy",
            baseline_payload=_module_payload("post_rp_adverse", pathologic_stage="pT2", ece_status=0, svi_status=0, surgical_margin=1),
            baseline_oracle={"expected_effective_state": "post_prostatectomy"},
            visits=[
                _visit("2026-03-12", "Falta PSA ultrasensible de seguimiento", {"pathologic_stage": "pT2", "surgical_margin": 1}, {"expected_missing_inputs": ["psa", "psa_postop"]}),
                _visit("2026-05-12", "Margen positivo mantiene vigilancia estrecha", {"psa": 0.05, "psa_postop": 0.05, "pathologic_stage": "pT2", "surgical_margin": 1}, {"expected_effective_state": "post_prostatectomy", "expected_action_contains": "PSA"}),
            ],
            clinical_oracle={"expected_effective_state": "post_prostatectomy", "expected_action_contains": "PSA", "expected_guideline_basis_any": ["NCCN 2026 post-prostatectomy"]},
        ),
        _trajectory(
            scenario_id="post_prostatectomy_persistent_psa",
            title="PSA persistente post-RP reabre ruta de salvage",
            scenario_family="post_prostatectomy",
            module_id="post_prostatectomy",
            baseline_payload=_module_payload("post_rp_surveillance", psa_postop=0.12, time_to_recurrence_months=1),
            baseline_oracle={"expected_effective_state": "post_prostatectomy"},
            visits=[
                _visit("2026-01-30", "Faltan cinética y factibilidad de salvage", {"psa": 0.18, "psa_postop": 0.18}, {"expected_missing_inputs": ["psadt_months", "salvage_local_feasible", "psma_pet_done"]}),
                _visit("2026-03-30", "Persistencia de PSA mantiene familia post-RP pero abre evaluación de salvage", {"psa": 0.31, "psa_postop": 0.31, "psadt_months": 8, "salvage_local_feasible": 1, "psma_pet_done": 0}, {"expected_effective_state": "post_prostatectomy", "expected_action_contains": "salvage", "expected_schedule_keywords": ["Imagen dirigida", "PSA ultrasensible"]}),
            ],
            clinical_oracle={"expected_effective_state": "post_prostatectomy", "expected_action_contains": "salvage", "expected_guideline_basis_any": ["NCCN 2026 post-prostatectomy"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="post_prostatectomy_functional_recovery",
            title="Recuperación funcional como outcome longitudinal post-RP",
            scenario_family="post_prostatectomy",
            module_id="post_prostatectomy",
            baseline_payload=_module_payload("post_rp_surveillance"),
            baseline_oracle={"expected_effective_state": "post_prostatectomy"},
            visits=[
                _visit("2026-03-22", "Captura funcional aún incompleta", {"psa": 0.02}, {"expected_missing_inputs": ["psa_postop", "pathologic_stage"]}),
                _visit("2026-09-22", "Se documenta recuperación funcional y vigilancia estable", {"psa": 0.01, "psa_postop": 0.01, "pathologic_stage": "pT2", "surgical_margin": 0, "continence_status": "continent", "sexual_recovery_status": "partial_recovery"}, {"expected_effective_state": "post_prostatectomy", "expected_action_contains": "vigilancia"}),
            ],
            clinical_oracle={"expected_effective_state": "post_prostatectomy", "expected_action_contains": "vigilancia", "expected_guideline_basis_any": ["NCCN 2026 post-prostatectomy"]},
        ),
    ]


def _recurrence_bcr_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="bcr_post_rp_local_pelvic",
            title="BCR post-RP local/pélvica candidata a salvage",
            scenario_family="recurrence_bcr",
            module_id=_module_id("recurrence_post_rp_salvage", "recurrence_bcr"),
            baseline_payload=_module_payload("recurrence_post_rp_salvage"),
            baseline_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "salvage"},
            visits=[
                _visit("2026-02-14", "Falta cinética y PSMA para cerrar salvage", {"psa": 0.41}, {"expected_missing_inputs": ["psadt_months", "salvage_local_feasible", "psma_pet_done"]}),
                _visit("2026-04-14", "PSMA local mantiene ventana curativa", {"psa": 0.46, "psadt_months": 8, "salvage_local_feasible": 1, "psma_pet_done": 1, "psma_positive": 1, "psma_stage_after_psma": "M0", "psma_uptake_pattern": "focal", "psma_rads_score": "4"}, {"expected_effective_state": "recurrence_bcr", "expected_action_contains": "salvage", "expected_schedule_keywords": ["PSA ultrasensible", "Imagen dirigida"]}),
            ],
            clinical_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "salvage", "expected_guideline_basis_any": ["NCCN 2026 BCR"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="bcr_post_rp_oligomet_psma",
            title="BCR oligometastásica por PSMA abre MDT",
            scenario_family="recurrence_bcr",
            module_id="recurrence_bcr",
            baseline_payload=_module_payload("recurrence_post_rp_salvage", psa_current=0.62, salvage_local_feasible=0),
            baseline_oracle={"expected_effective_state": "recurrence_bcr"},
            visits=[
                _visit("2026-03-01", "Aún falta PSMA para cerrar la redirección terapéutica", {"psa": 0.65, "psadt_months": 6}, {"expected_missing_inputs": ["psma_pet_done"]}),
                _visit("2026-04-01", "PSMA oligometastásica cambia a MDT", {"psa": 0.69, "psadt_months": 6, "psma_pet_done": 1, "psma_positive": 1, "psma_radioligand": "68Ga-PSMA-11", "psma_rads_score": "4", "psma_uptake_pattern": "multifocal", "psma_stage_after_psma": "M1a", "psma_negative_dominant_lesions": 0}, {"expected_effective_state": "recurrence_bcr", "expected_action_contains": "MDT"}),
            ],
            clinical_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "MDT", "expected_guideline_basis_any": ["NCCN 2026 BCR"]},
        ),
        _trajectory(
            scenario_id="bcr_post_rp_disseminated_psma",
            title="BCR diseminada pierde rescate local aislado",
            scenario_family="recurrence_bcr",
            module_id="recurrence_bcr",
            baseline_payload=_module_payload("recurrence_post_rp_salvage", psa_current=0.9, salvage_local_feasible=0),
            baseline_oracle={"expected_effective_state": "recurrence_bcr"},
            visits=[
                _visit("2026-03-11", "Aún falta PSMA para cerrar la redirección sistémica", {"psa": 0.95, "psadt_months": 4}, {"expected_missing_inputs": ["psma_pet_done"]}),
                _visit("2026-04-11", "PSMA diseminada redirige a sistémico", {"psa": 1.1, "psadt_months": 4, "psma_pet_done": 1, "psma_positive": 1, "psma_radioligand": "18F-DCFPyL", "psma_rads_score": "5", "psma_uptake_pattern": "diseminado", "psma_stage_after_psma": "M1b", "psma_negative_dominant_lesions": 0}, {"expected_effective_state": "recurrence_bcr", "expected_action_contains": "sist"}),
            ],
            clinical_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "sist", "expected_guideline_basis_any": ["NCCN 2026 BCR"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="bcr_salvage_window_clear",
            title="Ventana de rescate clara y temprana",
            scenario_family="recurrence_bcr",
            module_id="recurrence_bcr",
            baseline_payload=_module_payload("recurrence_post_rp_salvage", psa_current=0.28, psadt_months=10, salvage_local_feasible=1),
            baseline_oracle={"expected_effective_state": "recurrence_bcr"},
            visits=[
                _visit("2026-02-20", "Falta imagen dirigida", {"psa": 0.29, "psadt_months": 10}, {"expected_missing_inputs": ["salvage_local_feasible", "psma_pet_done"]}),
                _visit("2026-03-20", "Se confirma rescate temprano", {"psa": 0.31, "psadt_months": 9, "salvage_local_feasible": 1, "psma_pet_done": 0}, {"expected_effective_state": "recurrence_bcr", "expected_action_contains": "salvage"}),
            ],
            clinical_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "salvage", "expected_guideline_basis_any": ["EAU 2026 salvage"]},
        ),
        _trajectory(
            scenario_id="bcr_salvage_window_lost",
            title="Ventana de rescate perdida por progresión sistémica",
            scenario_family="recurrence_bcr",
            module_id="recurrence_bcr",
            baseline_payload=_module_payload("recurrence_bcr2_embark"),
            baseline_oracle={"expected_effective_state": "recurrence_bcr"},
            visits=[
                _visit("2026-03-25", "Aún faltan datos para redefinir contexto", {"psa": 0.82, "psadt_months": 5}, {"expected_missing_inputs": ["psma_pet_done", "salvage_local_feasible"]}),
                _visit("2026-04-25", "Sin factibilidad local, se pierde ventana de salvage", {"psa": 0.95, "psadt_months": 5, "salvage_local_feasible": 0, "psma_pet_done": 1, "psma_stage_after_psma": "M1b", "psma_uptake_pattern": "diseminado", "psma_rads_score": "5"}, {"expected_effective_state": "recurrence_bcr", "expected_action_contains": "Enzalutamide"}),
            ],
            clinical_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "Enzalutamide", "expected_guideline_basis_any": ["NCCN 2026 BCR"]},
        ),
    ]


def _post_radiotherapy_cases() -> list[dict[str, Any]]:
    base_payload = _module_payload("recurrence_post_rp_salvage", prior_prostatectomy=0, prior_radiation=1, prior_secondary_rt=0)
    return [
        _trajectory(
            scenario_id="post_rt_psa_rise_restage",
            title="PSA ascendente post-RT requiere reestadificación",
            scenario_family="post_radiotherapy_or_local_salvage",
            module_id="recurrence_bcr",
            baseline_payload=base_payload,
            baseline_oracle={"expected_effective_state": "recurrence_bcr"},
            visits=[
                _visit("2026-02-16", "Faltan imagen y cinética", {"psa": 1.2}, {"expected_missing_inputs": ["psadt_months", "psma_pet_done"]}),
                _visit("2026-04-16", "Reestadificación redefine conducta", {"psa": 1.4, "psadt_months": 7, "psma_pet_done": 1, "psma_stage_after_psma": "M0", "psma_uptake_pattern": "focal", "psma_rads_score": "4"}, {"expected_effective_state": "recurrence_bcr", "expected_action_contains": "rescate"}),
            ],
            clinical_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "rescate", "expected_guideline_basis_any": ["EAU 2026 salvage"]},
        ),
        _trajectory(
            scenario_id="post_rt_local_salvage_candidate",
            title="Post-RT con salvage local factible",
            scenario_family="post_radiotherapy_or_local_salvage",
            module_id="recurrence_bcr",
            baseline_payload=base_payload,
            baseline_oracle={"expected_effective_state": "recurrence_bcr"},
            visits=[
                _visit("2026-02-22", "Faltan datos de factibilidad", {"psa": 1.0, "psadt_months": 9}, {"expected_missing_inputs": ["salvage_local_feasible", "psma_pet_done"]}),
                _visit("2026-03-22", "La imagen mantiene salvage local", {"psa": 1.1, "psadt_months": 9, "salvage_local_feasible": 1, "psma_pet_done": 1, "psma_stage_after_psma": "M0", "psma_uptake_pattern": "focal", "psma_rads_score": "4"}, {"expected_effective_state": "recurrence_bcr", "expected_action_contains": "salvage"}),
            ],
            clinical_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "salvage", "expected_guideline_basis_any": ["EAU 2026 salvage"]},
        ),
        _trajectory(
            scenario_id="post_rt_systemic_redirection",
            title="Post-RT con enfermedad sistémica redirige a tratamiento sistémico",
            scenario_family="post_radiotherapy_or_local_salvage",
            module_id="recurrence_bcr",
            baseline_payload=base_payload,
            baseline_oracle={"expected_effective_state": "recurrence_bcr"},
            visits=[
                _visit("2026-02-26", "Faltan datos PSMA estructurados", {"psa": 1.6, "psadt_months": 4}, {"expected_missing_inputs": ["psma_radioligand", "psma_rads_score", "psma_uptake_pattern"]}),
                _visit("2026-03-26", "PSMA diseminada abandona salvage local", {"psa": 1.9, "psadt_months": 4, "psma_pet_done": 1, "psma_radioligand": "18F-DCFPyL", "psma_uptake_pattern": "diseminado", "psma_rads_score": "5", "psma_stage_after_psma": "M1b"}, {"expected_effective_state": "recurrence_bcr", "expected_action_contains": "sist"}),
            ],
            clinical_oracle={"expected_effective_state": "recurrence_bcr", "expected_action_contains": "sist", "expected_guideline_basis_any": ["EAU 2026 salvage"]},
        ),
    ]


def _adt_progression_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="adt_progression_non_castrate",
            title="Progresión bajo ADT con testosterona no castrada",
            scenario_family="adt_progression_verification",
            module_id=_module_id("adt_progression_pending_verification", "adt_progression_verification"),
            baseline_payload=_module_payload("adt_progression_pending_verification"),
            baseline_oracle={"expected_effective_state": "adt_progression_verification"},
            visits=[
                _visit("2026-01-19", "Faltan testosterona e imagen convencional", {"psa": 1.4}, {"expected_missing_inputs": ["testosterone", "current_adt_context", "progression_pattern", "conventional_imaging_status"]}),
                _visit("2026-02-19", "Persisten criterios de castración inadecuada", {"psa": 1.6, "testosterone": 92, "current_adt_context": "medical_adt_continuous", "progression_pattern": "biochemical_only", "conventional_imaging_status": "M0"}, {"expected_effective_state": "adt_progression_verification", "expected_action_contains": "ADT"}),
            ],
            clinical_oracle={"expected_effective_state": "adt_progression_verification", "expected_action_contains": "ADT", "expected_guideline_basis_any": ["NCCN 2026 CRPC workup"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="adt_progression_castrate_biochemical",
            title="Progresión bioquímica con castración confirmada",
            scenario_family="adt_progression_verification",
            module_id=_module_id("adt_progression_confirmed_m0", "adt_progression_verification"),
            baseline_payload=_module_payload("adt_progression_confirmed_m0"),
            baseline_oracle={"expected_effective_state": "adt_progression_verification"},
            visits=[
                _visit("2026-02-08", "Falta PSADT y contexto de progresión", {"psa": 2.3, "testosterone": 18}, {"expected_missing_inputs": ["current_adt_context", "progression_pattern", "conventional_imaging_status"]}),
                _visit("2026-04-08", "Castración confirmada redirige a nmCRPC", {"psa": 2.7, "testosterone": 18, "current_adt_context": "medical_adt_continuous", "progression_pattern": "biochemical_only", "conventional_imaging_status": "M0", "psadt_months": 7}, {"expected_effective_state": "m0_crpc", "expected_action_contains": "CRPC"}),
            ],
            clinical_oracle={"expected_effective_state": "m0_crpc", "expected_action_contains": "CRPC", "expected_guideline_basis_any": ["NCCN 2026 nmCRPC"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="adt_progression_castrate_radiographic",
            title="Progresión radiográfica con castración confirmada",
            scenario_family="adt_progression_verification",
            module_id="adt_progression_verification",
            baseline_payload=_module_payload("adt_progression_pending_verification", progression_pattern="radiographic", conventional_imaging_status="not_restaged"),
            baseline_oracle={"expected_effective_state": "adt_progression_verification"},
            visits=[
                _visit("2026-02-21", "Aún faltan testosterona e imagen", {"psa": 1.9}, {"expected_missing_inputs": ["testosterone", "current_adt_context", "progression_pattern", "conventional_imaging_status"]}),
                _visit("2026-03-21", "Radiografía + castración llevan a m1 CRPC", {"psa": 2.1, "testosterone": 14, "current_adt_context": "medical_adt_continuous", "progression_pattern": "radiographic", "conventional_imaging_status": "M1b"}, {"expected_effective_state": "m1_crpc", "expected_action_contains": "CRPC"}),
            ],
            clinical_oracle={"expected_effective_state": "m1_crpc", "expected_action_contains": "CRPC", "expected_guideline_basis_any": ["NCCN 2026 mCRPC"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="adt_progression_discordant_psma",
            title="Discordancia clínica/imaging bajo ADT",
            scenario_family="adt_progression_verification",
            module_id="adt_progression_verification",
            baseline_payload=_module_payload("adt_progression_pending_verification", progression_pattern="mixed"),
            baseline_oracle={"expected_effective_state": "adt_progression_verification"},
            visits=[
                _visit("2026-03-03", "Faltan testosterona y detalle de imagen", {"psa": 1.5}, {"expected_missing_inputs": ["testosterone", "current_adt_context", "progression_pattern", "conventional_imaging_status"]}),
                _visit("2026-05-03", "Persisten dudas con PSMA indeterminada", {"psa": 1.8, "testosterone": 24, "current_adt_context": "medical_adt_continuous", "progression_pattern": "mixed", "conventional_imaging_status": "M0", "psma_pet_done": 1, "psma_rads_score": "3", "psma_uptake_pattern": "indeterminado"}, {"expected_effective_state": "adt_progression_verification", "expected_action_contains": "correlacionar"}),
            ],
            clinical_oracle={"expected_effective_state": "adt_progression_verification", "expected_action_contains": "correlacionar", "expected_guideline_basis_any": ["NCCN 2026 CRPC workup"]},
        ),
    ]


def _m0_crpc_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="m0_crpc_low_risk_psadt_slow",
            title="nmCRPC con PSADT lento",
            scenario_family="m0_crpc",
            module_id=_module_id("m0_crpc_high_risk", "m0_crpc"),
            baseline_payload=_module_payload("m0_crpc_high_risk", psadt_months=14, comorbidity_seizure=0),
            baseline_oracle={"expected_effective_state": "m0_crpc"},
            visits=[
                _visit("2026-03-14", "Falta confirmar castración y seguridad", {"psa": 3.0}, {"expected_missing_inputs": ["psadt_months", "testosterone", "current_adt_context"]}),
                _visit("2026-06-14", "PSADT lento mantiene vigilancia intensificada", {"psa": 3.4, "psadt_months": 14, "testosterone": 18, "current_adt_context": "medical_adt_continuous"}, {"expected_effective_state": "m0_crpc", "expected_action_contains": "vigilancia"}),
            ],
            clinical_oracle={"expected_effective_state": "m0_crpc", "expected_action_contains": "vigilancia", "expected_guideline_basis_any": ["NCCN 2026 nmCRPC"]},
        ),
        _trajectory(
            scenario_id="m0_crpc_high_risk_arpi",
            title="nmCRPC de alto riesgo candidata a ARPI",
            scenario_family="m0_crpc",
            module_id=_module_id("m0_crpc_high_risk", "m0_crpc"),
            baseline_payload=_module_payload("m0_crpc_high_risk"),
            baseline_oracle={"expected_effective_state": "m0_crpc"},
            visits=[
                _visit("2026-03-18", "Faltan datos de seguridad para ARPI", {"psa": 2.7, "testosterone": 17}, {"expected_missing_inputs": ["current_adt_context", "seizure_history", "dermatitis_history", "cv_risk_documented"]}),
                _visit("2026-04-18", "ARPI se confirma como siguiente paso", {"psa": 3.0, "psadt_months": 6, "testosterone": 17, "current_adt_context": "medical_adt_continuous", "cv_risk_documented": 1, "drug_interaction_reviewed": 1}, {"expected_effective_state": "m0_crpc", "expected_action_contains": "Darolutamida"}),
            ],
            clinical_oracle={"expected_effective_state": "m0_crpc", "expected_action_contains": "Darolutamida", "expected_guideline_basis_any": ["NCCN 2026 nmCRPC"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="m0_crpc_contraindication_refines_choice",
            title="nmCRPC con contraindicaciones que refinan el ARPI",
            scenario_family="m0_crpc",
            module_id="m0_crpc",
            baseline_payload=_module_payload("m0_crpc_high_risk", comorbidity_seizure=1),
            baseline_oracle={"expected_effective_state": "m0_crpc"},
            visits=[
                _visit("2026-03-28", "Faltan datos cardiometabólicos", {"psa": 2.9, "testosterone": 19}, {"expected_missing_inputs": ["current_adt_context", "cv_risk_documented", "drug_interaction_reviewed"]}),
                _visit("2026-05-28", "El riesgo condiciona la elección del ARPI", {"psa": 3.3, "psadt_months": 7, "testosterone": 19, "current_adt_context": "medical_adt_continuous", "cv_risk_documented": 1, "drug_interaction_reviewed": 1, "seizure_history": 1}, {"expected_effective_state": "m0_crpc", "expected_action_contains": "Darolutamida"}),
            ],
            clinical_oracle={"expected_effective_state": "m0_crpc", "expected_action_contains": "Darolutamida", "expected_guideline_basis_any": ["NCCN 2026 nmCRPC"]},
        ),
    ]


def _mhspc_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="mhspc_low_volume_sync_doublet",
            title="mHSPC bajo volumen sincrónico con doblete",
            scenario_family="mHSPC",
            module_id=_module_id("mcspc_low_volume_sync_rt", "mcspc_low_volume_sync_oligo"),
            baseline_payload=_module_payload("mcspc_low_volume_sync_rt"),
            baseline_oracle={"expected_effective_state": "mcspc_low_volume_sync_oligo"},
            visits=[
                _visit("2026-03-04", "Faltan datos de volumen y fitness", {"psa": 16.0}, {"expected_missing_inputs": ["metastasis_site", "metastasis_count", "ecog", "volume_disease"]}),
                _visit("2026-04-04", "Bajo volumen mantiene doblete + RT al primario", {"metastasis_site": "Bone", "metastasis_count": 3, "ecog": 0, "volume_disease": "Low", "docetaxel_fit": 1}, {"expected_effective_state": "mcspc_low_volume_sync_oligo", "expected_action_contains": "RT al primario"}),
            ],
            clinical_oracle={"expected_effective_state": "mcspc_low_volume_sync_oligo", "expected_action_contains": "RT al primario", "expected_guideline_basis_any": ["NCCN 2026 mHSPC"]},
        ),
        _trajectory(
            scenario_id="mhspc_oligometachronous_mdt",
            title="mHSPC oligometacrónico con MDT",
            scenario_family="mHSPC",
            module_id=_module_id("mcspc_oligo_metachronous_mdt", "mcspc_oligo_metachronous"),
            baseline_payload=_module_payload("mcspc_oligo_metachronous_mdt"),
            baseline_oracle={"expected_effective_state": "mcspc_oligo_metachronous"},
            visits=[
                _visit("2026-03-09", "Faltan imagen y número real de metástasis", {}, {"expected_missing_inputs": ["metastasis_site", "metastasis_count", "ecog", "volume_disease"]}),
                _visit("2026-04-09", "MDT sigue siendo candidata", {"metastasis_site": "Bone", "metastasis_count": 2, "ecog": 0, "volume_disease": "Low", "psma_pet_done": 1, "psma_uptake_pattern": "multifocal", "psma_rads_score": "4"}, {"expected_effective_state": "mcspc_oligo_metachronous", "expected_action_contains": "Metastasis-directed therapy"}),
            ],
            clinical_oracle={"expected_effective_state": "mcspc_oligo_metachronous", "expected_action_contains": "Metastasis-directed therapy", "expected_guideline_basis_any": ["NCCN 2026 mHSPC"]},
        ),
        _trajectory(
            scenario_id="mhspc_high_volume_triplet",
            title="mHSPC alto volumen candidata a triplete",
            scenario_family="mHSPC",
            module_id=_module_id("mcspc_high_volume_akeega", "mcspc_high_volume"),
            baseline_payload=_module_payload("mcspc_high_volume_akeega"),
            baseline_oracle={"expected_effective_state": "mcspc_high_volume"},
            visits=[
                _visit("2026-03-17", "Faltan datos de fitness y soporte óseo", {"metastasis_site": "Bone"}, {"expected_missing_inputs": ["metastasis_count", "ecog", "volume_disease", "dxa_baseline_done"]}),
                _visit("2026-04-17", "Carga alta y fitness mantienen intensificación", {"metastasis_site": "Bone", "metastasis_count": 7, "ecog": 1, "volume_disease": "High", "docetaxel_fit": 1, "dxa_baseline_done": 1, "calcium_vitd_started": 1}, {"expected_effective_state": "mcspc_high_volume", "expected_action_contains": "Niraparib"}),
            ],
            clinical_oracle={"expected_effective_state": "mcspc_high_volume", "expected_action_contains": "Niraparib", "expected_guideline_basis_any": ["NCCN 2026 mHSPC"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="mhspc_high_volume_fitness_limited",
            title="mHSPC alto volumen con fitness limitado reduce intensidad",
            scenario_family="mHSPC",
            module_id="mcspc_high_volume",
            baseline_payload=_module_payload("mcspc_high_volume_akeega", ecog_score=2, frailty_status="Vulnerable"),
            baseline_oracle={"expected_effective_state": "mcspc_high_volume"},
            visits=[
                _visit("2026-03-29", "Faltan datos de neuropatía y soporte", {"metastasis_site": "Bone", "metastasis_count": 6}, {"expected_missing_inputs": ["ecog", "volume_disease", "dxa_baseline_done"]}),
                _visit("2026-05-29", "Fitness limitado ajusta backbone", {"metastasis_site": "Bone", "metastasis_count": 6, "ecog": 2, "volume_disease": "High", "docetaxel_fit": 0, "dxa_baseline_done": 1}, {"expected_effective_state": "mcspc_high_volume", "expected_action_contains": "ADT"}),
            ],
            clinical_oracle={"expected_effective_state": "mcspc_high_volume", "expected_action_contains": "ADT", "expected_guideline_basis_any": ["NCCN 2026 mHSPC"]},
        ),
    ]


def _m1_crpc_cases() -> list[dict[str, Any]]:
    return [
        _trajectory(
            scenario_id="m1_crpc_pre_arpi",
            title="m1CRPC temprana antes de ARPI",
            scenario_family="m1_crpc",
            module_id=_module_id("m1_crpc_post_taxane_card_vision", "m1_crpc"),
            baseline_payload=_module_payload("m1_crpc_post_taxane_card_vision", mcrpc_line_context="pre_arpi", prior_therapy="ADT"),
            baseline_oracle={"expected_effective_state": "m1_crpc"},
            visits=[
                _visit("2026-03-06", "Faltan línea y progresión estructurada", {"psa": 7.4}, {"expected_missing_inputs": ["testosterone", "line_of_therapy_number", "drug_scheme", "progression_pattern"]}),
                _visit("2026-04-06", "Secuenciación inicial confirma ARPI", {"psa": 8.1, "testosterone": 14, "line_of_therapy_number": 1, "drug_scheme": "ADT_ENZALUTAMIDE", "progression_pattern": "radiographic"}, {"expected_effective_state": "m1_crpc", "expected_action_contains": "Enzalutamide"}),
            ],
            clinical_oracle={"expected_effective_state": "m1_crpc", "expected_action_contains": "Enzalutamide", "expected_guideline_basis_any": ["NCCN 2026 mCRPC"]},
        ),
        _trajectory(
            scenario_id="m1_crpc_post_arpi_pre_taxane",
            title="m1CRPC post-ARPI y pre-taxano",
            scenario_family="m1_crpc",
            module_id="m1_crpc",
            baseline_payload=_module_payload("m1_crpc_post_taxane_card_vision", mcrpc_line_context="post_arpi_pre_taxane", prior_therapy="Abiraterona"),
            baseline_oracle={"expected_effective_state": "m1_crpc"},
            visits=[
                _visit("2026-03-13", "Faltan seguridad y línea actual", {"psa": 12.0}, {"expected_missing_inputs": ["testosterone", "line_of_therapy_number", "drug_scheme", "progression_pattern"]}),
                _visit("2026-04-13", "Post-ARPI pre-taxano reordena secuenciación", {"psa": 13.4, "testosterone": 11, "line_of_therapy_number": 2, "drug_scheme": "DOCETAXEL", "progression_pattern": "radiographic"}, {"expected_effective_state": "m1_crpc", "expected_action_contains": "Olaparib"}),
            ],
            clinical_oracle={"expected_effective_state": "m1_crpc", "expected_action_contains": "Olaparib", "expected_guideline_basis_any": ["NCCN 2026 mCRPC"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="m1_crpc_post_taxane_card_or_vision",
            title="m1CRPC post-taxano con decisión CARD/VISION",
            scenario_family="m1_crpc",
            module_id=_module_id("m1_crpc_post_taxane_card_vision", "m1_crpc"),
            baseline_payload=_module_payload("m1_crpc_post_taxane_card_vision"),
            baseline_oracle={"expected_effective_state": "m1_crpc"},
            visits=[
                _visit("2026-03-24", "Faltan variables PSMA estructuradas", {"psa": 18.1, "testosterone": 12}, {"expected_missing_inputs": ["psma_radioligand", "psma_rads_score", "psma_uptake_pattern", "psma_negative_dominant_lesions"]}),
                _visit("2026-04-24", "PSMA alta confianza mantiene ruta CARD/VISION", {"psa": 19.5, "testosterone": 12, "line_of_therapy_number": 3, "drug_scheme": "CABAZITAXEL", "progression_pattern": "radiographic", "psma_radioligand": "68Ga-PSMA-11", "psma_rads_score": "5", "psma_uptake_pattern": "multifocal", "psma_negative_dominant_lesions": 0}, {"expected_effective_state": "m1_crpc", "expected_action_contains": "Olaparib"}),
            ],
            clinical_oracle={"expected_effective_state": "m1_crpc", "expected_action_contains": "Olaparib", "expected_guideline_basis_any": ["NCCN 2026 mCRPC"], "hard_critical": True},
        ),
        _trajectory(
            scenario_id="m1_crpc_parp_pathway",
            title="m1CRPC con ruta PARP trazable",
            scenario_family="m1_crpc",
            module_id="m1_crpc",
            baseline_payload=_module_payload("m1_crpc_post_taxane_card_vision", hrr_status="Positivo", hrr_gene="BRCA2", brca2_status="Positivo", prior_therapy="Abiraterona"),
            baseline_oracle={"expected_effective_state": "m1_crpc"},
            visits=[
                _visit("2026-03-30", "Faltan biomarcadores completos", {"psa": 15.4, "testosterone": 15}, {"expected_missing_inputs": ["testosterone", "line_of_therapy_number", "drug_scheme", "progression_pattern"]}),
                _visit("2026-04-30", "BRCA2 positiva abre PARP", {"psa": 16.7, "testosterone": 15, "line_of_therapy_number": 2, "drug_scheme": "ABIRATERONE", "progression_pattern": "radiographic", "hrr_status": "Positivo", "hrr_gene": "BRCA2", "brca2_status": "Positivo"}, {"expected_effective_state": "m1_crpc", "expected_action_contains": "PARP"}),
            ],
            clinical_oracle={"expected_effective_state": "m1_crpc", "expected_action_contains": "PARP", "expected_guideline_basis_any": ["NCCN 2026 mCRPC"]},
        ),
        _trajectory(
            scenario_id="m1_crpc_abiraterone_hepatic_safety",
            title="m1CRPC en abiraterona con monitorización hepática obligatoria",
            scenario_family="m1_crpc",
            module_id="m1_crpc",
            baseline_payload=_module_payload("m1_crpc_post_taxane_card_vision", prior_therapy="ADT", mcrpc_line_context="pre_taxane"),
            baseline_oracle={"expected_effective_state": "m1_crpc"},
            visits=[
                _visit("2026-03-31", "Faltan labs de seguridad para abiraterona", {"psa": 10.2, "testosterone": 14, "line_of_therapy_number": 1, "drug_scheme": "ABIRATERONE", "progression_pattern": "radiographic"}, {"expected_missing_inputs": ["ast", "alt", "bilirubin", "potassium", "systolic_bp", "glucose"]}),
                _visit("2026-04-30", "Elevación hepática genera alerta de seguridad", {"psa": 11.4, "testosterone": 14, "line_of_therapy_number": 1, "drug_scheme": "ABIRATERONE", "progression_pattern": "radiographic", "ast": 98, "alt": 124, "bilirubin": 2.4, "glucose": 146, "systolic_bp": 148}, {"expected_effective_state": "m1_crpc", "expected_alert_keywords": ["hepática", "Abiraterona"]}),
            ],
            clinical_oracle={"expected_effective_state": "m1_crpc", "expected_alert_keywords": ["hepática", "Abiraterona"], "expected_guideline_basis_any": ["NCCN 2026 mCRPC", "FDA/Janssen abiraterone"], "hard_critical": True},
        ),
    ]


def build_trajectory_catalog() -> list[dict[str, Any]]:
    trajectories = (
        _diagnostic_workup_cases()
        + _post_negative_biopsy_cases()
        + _localized_cases()
        + _active_surveillance_cases()
        + _post_prostatectomy_cases()
        + _recurrence_bcr_cases()
        + _post_radiotherapy_cases()
        + _adt_progression_cases()
        + _m0_crpc_cases()
        + _mhspc_cases()
        + _m1_crpc_cases()
    )
    return trajectories


def list_trajectory_summaries() -> list[dict[str, Any]]:
    return [
        {
            "scenario_id": item["scenario_id"],
            "title": item["title"],
            "scenario_family": item["scenario_family"],
            "module_id": item["module_id"],
            "visit_count": len(item["visits"]),
            "hard_critical": bool(item.get("clinical_oracle", {}).get("hard_critical")),
        }
        for item in build_trajectory_catalog()
    ]


__all__ = [
    "build_trajectory_catalog",
    "list_trajectory_summaries",
]
