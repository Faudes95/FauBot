from __future__ import annotations

from typing import Any


def classify_nccn(payload: dict[str, Any]) -> dict[str, Any]:
    tstage = str(payload.get("clinical_tstage", "T2a")).upper()
    gg = int(payload.get("isup_grade", 1))
    psa = float(payload.get("psa", 0) or 0)
    n_pos = int(payload.get("num_cores_positive", 0) or 0)
    total_cores = max(int(payload.get("total_cores", 12) or 12), 1)
    pct = payload.get("pct_cores_positive")
    if pct in (None, ""):
        pct = n_pos / total_cores
    pct = float(pct or 0)
    nodal_status = str(payload.get("nodal_status", "N0")).upper()

    if nodal_status == "N1":
        return {
            "label": "Regional N1M0",
            "risk_group": "REGIONAL N1M0",
            "reasons": ["Regional node-positive non-metastatic disease."],
            "recommendation": "Consider definitive RT plus long-course ADT and systemic intensification in eligible patients.",
        }

    high_risk_features = 0
    if tstage in {"T3A", "T3B", "T4"}:
        high_risk_features += 1
    if gg >= 4:
        high_risk_features += 1
    if psa > 20:
        high_risk_features += 1

    very_high_features = 0
    if tstage in {"T3A", "T3B", "T4"}:
        very_high_features += 1
    if gg >= 4:
        very_high_features += 1
    if psa > 40:
        very_high_features += 1
    if very_high_features >= 2:
        return {
            "label": "Very High",
            "risk_group": "VERY HIGH",
            "reasons": ["At least two very-high-risk features by NCCN 5.2026."],
            "recommendation": "EBRT plus long-course ADT with systemic intensification for eligible patients, or RP in selected candidates.",
        }

    if high_risk_features >= 1:
        return {
            "label": "High",
            "risk_group": "HIGH",
            "reasons": ["At least one high-risk feature by NCCN 5.2026."],
            "recommendation": "EBRT plus long-course ADT, or RP with pelvic nodal dissection in selected patients.",
        }

    ir_factors = 0
    if tstage in {"T2B", "T2C"}:
        ir_factors += 1
    if gg in {2, 3}:
        ir_factors += 1
    if 10 <= psa <= 20:
        ir_factors += 1

    if gg == 3 or ir_factors >= 2 or pct >= 0.5:
        return {
            "label": "Unfavorable Intermediate",
            "risk_group": "UNFAVORABLE INTERMEDIATE",
            "reasons": ["GG3, multiple intermediate-risk factors, or >=50% positive cores."],
            "recommendation": "RT plus short-course ADT or RP in eligible patients.",
        }

    if ir_factors == 1:
        return {
            "label": "Favorable Intermediate",
            "risk_group": "FAVORABLE INTERMEDIATE",
            "reasons": ["Single intermediate-risk factor, GG1-2, and <50% positive cores."],
            "recommendation": "Observation or definitive local therapy; AS only in carefully selected patients with >10-year life expectancy.",
        }

    return {
        "label": "Low",
        "risk_group": "LOW",
        "reasons": ["cT1-T2a, GG1, PSA <10 without higher-risk features."],
        "recommendation": "Active surveillance is preferred for most men with >=10-year life expectancy; observation if <10 years.",
    }


def active_surveillance_position(payload: dict[str, Any], nccn_group: str) -> dict[str, Any]:
    gg = int(payload.get("isup_grade", 1))
    psad = float(payload.get("psad", 0) or 0)
    pct = float(payload.get("pct_cores_positive", 0) or 0)
    max_inv = float(payload.get("max_core_involvement", 0) or 0)
    life_expectancy = float(payload.get("life_expectancy_years", 15) or 15)
    percent_pattern_4 = float(payload.get("percent_pattern_4", 0) or 0)
    cribriform = str(payload.get("cribriform_pattern", "0")) == "1"
    intraductal = str(payload.get("intraductal_carcinoma", "0")) == "1"
    prior_mpmri = str(payload.get("prior_mpmri", "0")) == "1"
    confirmatory_biopsy_planned = str(payload.get("confirmatory_biopsy_planned", "0")) == "1"
    pirads_score = _normalize_pirads(payload.get("prior_mpmri_pirads_score"))
    targeted_biopsy_status = str(payload.get("prior_mpmri_targeted_biopsy_status", "desconocido") or "desconocido")
    genomic_result = str(payload.get("genomic_classifier_result", "No aplica"))
    brca2_family_risk = str(payload.get("brca2_family_risk", "0")) == "1"
    micro_us_available = str(payload.get("micro_us_available", "0")) == "1"
    adverse_variant_type = _normalized_adverse_variant(payload)
    neuroendocrine_features = str(payload.get("neuroendocrine_features", "0")) == "1"
    risk_pathway = str(payload.get("risk_calculator_pathway", "No usado"))
    severe_variant = adverse_variant_type in {"small_cell_neuroendocrine", "sarcomatoid", "signet_ring", "mixed_multiple", "other_aggressive", "other_aggressive_unspecified"}
    any_adverse_variant = adverse_variant_type not in {"", "none"}

    if severe_variant or neuroendocrine_features:
        return {
            "eligible": False,
            "status": "not_recommended",
            "summary": "La vigilancia activa no es apropiada porque existe una variante histológica adversa de muy alto riesgo o rasgos neuroendocrinos emergentes.",
            "requires_escalation": True,
            "adverse_variant_type": adverse_variant_type,
        }
    if cribriform or intraductal or any_adverse_variant:
        return {
            "eligible": False,
            "status": "not_recommended",
            "summary": "La vigilancia activa no se favorece porque existe histología adversa, incluida variante específica, patrón cribiforme o carcinoma intraductal.",
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }
    if brca2_family_risk:
        return {
            "eligible": False,
            "status": "not_preferred",
            "summary": "La vigilancia activa pierde prioridad cuando existe una señal hereditaria tipo BRCA2 que eleva el riesgo biológico infravalorado.",
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }
    if genomic_result == "Alto":
        return {
            "eligible": False,
            "status": "not_preferred",
            "summary": "La vigilancia activa pierde prioridad cuando el clasificador genómico sugiere alto riesgo biológico.",
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }
    if prior_mpmri and pirads_score is None:
        return {
            "eligible": True,
            "status": "selected_candidate",
            "summary": "La vigilancia activa puede seguir sobre la mesa, pero no debe priorizarse hasta documentar el PI-RADS de la resonancia magnética previa.",
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }

    if nccn_group == "LOW":
        if not prior_mpmri or not confirmatory_biopsy_planned:
            return {
                "eligible": True,
                "status": "selected_candidate",
                "summary": "La vigilancia activa sigue siendo razonable, pero la preparación al estilo 2026 requiere resonancia magnética previa y biopsia confirmatoria planificada.",
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        if pirads_score is not None and pirads_score >= 4 and targeted_biopsy_status != "si":
            return {
                "eligible": False,
                "status": "not_preferred",
                "summary": "Con PI-RADS 4 o 5 sin biopsia dirigida documentada, la vigilancia activa no debe sostenerse como opción preferente hasta completar confirmación dirigida.",
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        if pirads_score is not None and pirads_score >= 4:
            return {
                "eligible": True,
                "status": "selected_candidate",
                "summary": "Incluso con histología favorable, un PI-RADS 4 o 5 no permite mantener vigilancia activa como preferente; como máximo queda como candidato seleccionado con seguimiento reforzado.",
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        if pirads_score == 3:
            return {
                "eligible": True,
                "status": "selected_candidate",
                "summary": "Con PI-RADS 3, PSAD baja y estrategia confirmatoria estructurada, la vigilancia activa puede mantenerse como candidato seleccionado, no como preferente automática.",
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        if life_expectancy >= 10:
            return {
                "eligible": True,
                "status": "preferred",
                "summary": (
                    "La vigilancia activa es preferente en enfermedad de bajo riesgo con una esperanza de vida mayor o igual a 10 años."
                    if risk_pathway == "No usado" and not micro_us_available
                    else "La vigilancia activa es preferente en enfermedad de bajo riesgo con una esperanza de vida mayor o igual a 10 años y gana robustez cuando existen pathways MRI + PSAD o micro-US."
                ),
                "requires_escalation": False,
                "adverse_variant_type": adverse_variant_type,
            }
        return {
            "eligible": True,
            "status": "observation_preferred",
            "summary": "La observación suele ser preferente cuando la esperanza de vida es menor de 10 años.",
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }

    if nccn_group == "FAVORABLE INTERMEDIATE":
        selected = (
            gg <= 2
            and psad < 0.15
            and pct < 0.34
            and max_inv <= 0.5
            and percent_pattern_4 <= 10
            and life_expectancy > 10
            and prior_mpmri
            and confirmatory_biopsy_planned
            and genomic_result in {"No aplica", "Bajo", "Intermedio"}
            and pirads_score in {None, 2, 3}
            and not (pirads_score and pirads_score >= 4)
            and targeted_biopsy_status in {"si", "desconocido"}
        )
        if pirads_score is not None and pirads_score >= 4 and targeted_biopsy_status != "si":
            selected = False
        return {
            "eligible": selected,
            "status": "selected_candidate" if selected else "not_preferred",
            "summary": (
                "La vigilancia activa solo puede considerarse en casos intermedios favorables seleccionados, con resonancia magnética previa, plan de biopsia confirmatoria y sin histología adversa."
                if selected
                else "En este contexto se favorece la terapia local definitiva por encima de la vigilancia activa."
            ),
            "requires_escalation": False,
            "adverse_variant_type": adverse_variant_type,
        }

    return {
        "eligible": False,
        "status": "not_recommended",
        "summary": "Este grupo de riesgo de la Red Nacional Integral del Cáncer (NCCN) 2026 no es apropiado para vigilancia activa como estrategia principal de manejo.",
        "requires_escalation": False,
        "adverse_variant_type": adverse_variant_type,
    }


def _normalize_pirads(value: Any) -> int | None:
    if value in (None, "", "desconocido"):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed in {2, 3, 4, 5} else None


def _normalized_adverse_variant(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("adverse_histology_variant_type", "none") or "none").strip()
    if explicit and explicit != "none":
        return explicit
    if str(payload.get("rare_histology_variant", "0")) == "1":
        return "other_aggressive_unspecified"
    return "none"
