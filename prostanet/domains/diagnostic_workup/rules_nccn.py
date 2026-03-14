from __future__ import annotations


def classify_diagnostic_workup(payload: dict) -> dict:
    psa = float(payload.get("psa", 0) or 0)
    psad = float(payload.get("psad", 0) or 0)
    if not psad:
        prostate_volume = float(payload.get("prostate_volume_ml", 0) or 0)
        if psa and prostate_volume:
            psad = psa / prostate_volume
    pirads = int(float(payload.get("pirads_score", 0) or 0))
    dre_suspicious = _is_true(payload.get("dre_suspicious"))
    family_history = _is_true(payload.get("family_history_positive"))
    family_history_detail = str(payload.get("family_history_detail", "")).strip()
    germline_risk = _is_true(payload.get("germline_risk_mutation"))
    germline_status = str(payload.get("germline_status", "Desconocido"))
    prior_negative_biopsy = _is_true(payload.get("prior_negative_biopsy"))
    psa_velocity = float(payload.get("psa_velocity_ng_ml_year", 0) or 0)
    risk_pathway = str(payload.get("risk_calculator_pathway", "No usado"))
    mpmri_quality = str(payload.get("mpmri_quality", "Adecuada"))
    lesion_size = float(payload.get("index_lesion_size_mm", 0) or 0)
    planned_biopsy_route = str(payload.get("planned_biopsy_route", "No definida"))
    ipss_score = float(payload.get("ipss_score", 0) or 0)

    score = 0
    reasons: list[str] = []

    if psa >= 10:
        score += 2
        reasons.append("El antígeno prostático específico es igual o mayor de 10 ng/mL.")
    elif psa >= 4:
        score += 1
        reasons.append("El antígeno prostático específico se encuentra por encima del umbral de vigilancia.")

    if psad >= 0.15:
        score += 2
        reasons.append("La densidad del antígeno prostático específico es 0.15 o mayor.")
    elif psad >= 0.10:
        score += 1
        reasons.append("La densidad del antígeno prostático específico es intermedia y merece contexto adicional.")

    if dre_suspicious:
        score += 2
        reasons.append("El tacto rectal es sospechoso.")

    if pirads >= 4:
        score += 2
        reasons.append("La resonancia magnética multiparamétrica muestra una lesión PI-RADS 4 o 5.")
    elif pirads == 3:
        score += 1
        reasons.append("La resonancia magnética multiparamétrica muestra una lesión PI-RADS 3.")

    if family_history or germline_risk or family_history_detail:
        score += 1
        reasons.append("Existe un modificador hereditario o familiar que eleva la sospecha clínica.")
    if germline_status in {"Sospechado", "Conocido"} and not germline_risk:
        score += 1
        reasons.append("La sospecha o confirmación germinal obliga a sostener una ruta diagnóstica de menor tolerancia al retraso.")
    if psa_velocity >= 0.75:
        score += 1
        reasons.append("La velocidad del antígeno prostático específico es clínicamente relevante y refuerza la sospecha.")
    if lesion_size >= 10 and pirads >= 3:
        score += 1
        reasons.append("El tamaño de la lesión índice es relevante y aumenta la urgencia de confirmación histológica.")
    if risk_pathway != "No usado" and pirads <= 3 and psad < 0.15 and not dre_suspicious:
        score = max(0, score - 1)
        reasons.append("El pathway MRI + PSAD o la calculadora de riesgo reduce ligeramente la urgencia en un caso limítrofe.")
    if mpmri_quality == "Subóptima":
        reasons.append("La resonancia magnética disponible es subóptima y no debe usarse para tranquilizar falsamente un caso limítrofe.")
    if planned_biopsy_route == "Transperineal":
        reasons.append("La vía transperineal ya está identificada y favorece una planificación diagnóstica más robusta si se decide biopsia.")
    if ipss_score >= 20:
        reasons.append("El componente sintomático basal justifica alinear la decisión diagnóstica con impacto clínico y no solo con biomarcadores.")

    if score >= 6:
        label = "Alta sospecha diagnóstica"
        recommendation = "Realizar biopsia dirigida más biopsia sistemática sin diferir el estudio; si la histología confirma enfermedad de alto riesgo o regional, preparar imagen avanzada para estadificación."
        risk_group = "DIAGNOSTIC_HIGH"
    elif score >= 3:
        label = "Sospecha diagnóstica intermedia"
        recommendation = "Completar resonancia magnética multiparamétrica y avanzar a biopsia dirigida más sistemática si persiste la sospecha por densidad del antígeno prostático específico, tacto rectal o PI-RADS 3 o mayor."
        risk_group = "DIAGNOSTIC_INTERMEDIATE"
    else:
        label = "Sospecha diagnóstica baja"
        recommendation = "Repetir antígeno prostático específico y densidad del antígeno prostático específico, confirmar técnica de medición y reservar la biopsia para elevación persistente o nueva señal clínica."
        risk_group = "DIAGNOSTIC_LOW"

    significant_risk_pct = min(85, max(10, 12 + score * 10))
    if prior_negative_biopsy:
        reasons.append("Existe antecedente de biopsia benigna, por lo que la decisión debe integrar el nuevo nivel de sospecha y no repetir biopsia de forma automática.")

    return {
        "label": label,
        "risk_group": risk_group,
        "score": score,
        "significant_risk_pct": significant_risk_pct,
        "biopsy_indicated": score >= 3 or dre_suspicious or pirads >= 4,
        "repeat_high_quality_mri": mpmri_quality == "Subóptima" and score >= 2,
        "recommendation": recommendation,
        "reasons": reasons,
    }


def _is_true(value) -> bool:
    return str(value).lower() in {"1", "true", "yes", "si", "on"}
