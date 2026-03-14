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
    genomic_result = str(payload.get("genomic_classifier_result", "No aplica"))
    brca2_family_risk = str(payload.get("brca2_family_risk", "0")) == "1"
    micro_us_available = str(payload.get("micro_us_available", "0")) == "1"
    rare_histology_variant = str(payload.get("rare_histology_variant", "0")) == "1"
    neuroendocrine_features = str(payload.get("neuroendocrine_features", "0")) == "1"
    risk_pathway = str(payload.get("risk_calculator_pathway", "No usado"))

    if cribriform or intraductal or rare_histology_variant or neuroendocrine_features:
        return {
            "eligible": False,
            "status": "not_recommended",
            "summary": "Active surveillance is not favored because adverse histology is present.",
        }
    if brca2_family_risk:
        return {
            "eligible": False,
            "status": "not_preferred",
            "summary": "Active surveillance loses priority when a BRCA2-like hereditary signal raises concern for underestimating biological risk.",
        }
    if genomic_result == "Alto":
        return {
            "eligible": False,
            "status": "not_preferred",
            "summary": "Active surveillance loses priority when the genomic classifier suggests high biological risk.",
        }

    if nccn_group == "LOW":
        if not prior_mpmri or not confirmatory_biopsy_planned:
            return {
                "eligible": True,
                "status": "selected_candidate",
                "summary": "Active surveillance remains reasonable, but 2026-style readiness requires prior MRI and a confirmatory biopsy plan.",
            }
        if life_expectancy >= 10:
            return {
                "eligible": True,
                "status": "preferred",
                "summary": (
                    "Active surveillance is preferred in low-risk disease with >=10-year life expectancy."
                    if risk_pathway == "No usado" and not micro_us_available
                    else "Active surveillance is preferred in low-risk disease with >=10-year life expectancy and gains robustness when MRI/PSAD pathways or micro-US are available."
                ),
            }
        return {
            "eligible": True,
            "status": "observation_preferred",
            "summary": "Observation is generally preferred when life expectancy is below 10 years.",
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
        )
        return {
            "eligible": selected,
            "status": "selected_candidate" if selected else "not_preferred",
            "summary": (
                "AS may be considered only in selected favorable-intermediate cases with prior MRI, a confirmatory biopsy plan and no adverse genomic signal."
                if selected
                else "Definitive local therapy is favored over AS in this setting."
            ),
        }

    return {
        "eligible": False,
        "status": "not_recommended",
        "summary": "This NCCN 2026 risk group is not appropriate for active surveillance as a primary management strategy.",
    }
