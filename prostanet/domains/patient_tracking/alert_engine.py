# -*- coding: utf-8 -*-
"""
Motor de alertas clínicas para seguimiento activo de Ca. próstata.

Evalúa automáticamente umbrales de seguridad en cinética de PSA,
laboratorios, ECOG y milestones de tratamiento.
Genera alertas que se persisten en smart_alerts.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ClinicalAlert:
    """Alerta clínica generada automáticamente."""
    patient_id: int
    alert_type: str
    severity: str  # "info" | "warning" | "critical"
    category: str  # "psa_kinetics" | "laboratory" | "ecog" | "treatment_milestone" | "safety"
    title: str
    message: str
    recommended_action: str = ""
    guideline_reference: str = ""
    triggering_value: str = ""
    threshold: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClinicalAlertEngine:
    """
    Evalúa condiciones clínicas y genera alertas.
    Diseñado para ejecutarse después de cada visita de seguimiento o evaluación clínica.
    """

    @staticmethod
    def evaluate_psa_kinetics(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa cinética de PSA y genera alertas según umbrales clínicos.

        Umbrales:
            - PSADT <3 meses → CRÍTICO (progresión rápida)
            - PSADT 3-10 meses → WARNING (alto riesgo nmCRPC/progresión)
            - Velocidad PSA >0.75 ng/mL/año en contexto diagnóstico → WARNING
            - PSA >0.2 ng/mL post-RP → WARNING (posible BCR)
            - PSA nadir + 2 ng/mL post-RT → WARNING (criterio Phoenix BCR)
        """
        alerts: list[ClinicalAlert] = []

        psadt = patient.get("psadt_months") or patient.get("psa_doubling_time")
        if psadt is not None:
            try:
                psadt = float(psadt)
                if psadt > 0 and psadt < 3:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="psadt_critical",
                        severity="critical",
                        category="psa_kinetics",
                        title="PSADT < 3 meses — Progresión rápida",
                        message=f"Tiempo de duplicación de PSA: {psadt:.1f} meses. Indicativo de enfermedad agresiva con alto riesgo de progresión a metástasis.",
                        recommended_action="Considerar intensificación terapéutica urgente. Re-estadificación con PSMA-PET si disponible.",
                        guideline_reference="NCCN 5.2026: nmCRPC alto riesgo / EAU 2026",
                        triggering_value=f"{psadt:.1f} meses",
                        threshold="< 3 meses",
                    ))
                elif psadt > 0 and psadt <= 10:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="psadt_warning",
                        severity="warning",
                        category="psa_kinetics",
                        title="PSADT ≤ 10 meses — Alto riesgo",
                        message=f"Tiempo de duplicación de PSA: {psadt:.1f} meses. Criterio de alto riesgo para nmCRPC.",
                        recommended_action="Considerar ARPI (apalutamida, enzalutamida, darolutamida) si en contexto CRPC. Verificar castración.",
                        guideline_reference="NCCN 5.2026: SPARTAN, PROSPER, ARAMIS",
                        triggering_value=f"{psadt:.1f} meses",
                        threshold="≤ 10 meses",
                    ))
            except (ValueError, TypeError):
                pass

        psa_velocity = patient.get("psa_velocity")
        if psa_velocity is not None:
            try:
                vel = float(psa_velocity)
                if vel > 0.75:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="psa_velocity_elevated",
                        severity="warning",
                        category="psa_kinetics",
                        title="Velocidad de PSA > 0.75 ng/mL/año",
                        message=f"Velocidad de PSA: {vel:.2f} ng/mL/año. Valor elevado que sugiere enfermedad clínicamente significativa.",
                        recommended_action="Considerar biopsia si no diagnosticado. En post-tratamiento, evaluar recurrencia.",
                        guideline_reference="Carter HB et al. JAMA 1992 / NCCN 5.2026",
                        triggering_value=f"{vel:.2f} ng/mL/año",
                        threshold="> 0.75 ng/mL/año",
                    ))
            except (ValueError, TypeError):
                pass

        # PSA post-RP detectable
        psa_current = patient.get("psa") or patient.get("psa_current")
        management_track = patient.get("management_track", "")
        if psa_current is not None and management_track == "post_rp":
            try:
                psa_val = float(psa_current)
                if psa_val >= 0.2:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="bcr_post_rp",
                        severity="warning",
                        category="psa_kinetics",
                        title="PSA ≥ 0.2 ng/mL post-prostatectomía",
                        message=f"PSA actual: {psa_val:.2f} ng/mL. Cumple criterio de recurrencia bioquímica post-RP.",
                        recommended_action="Confirmar con segunda determinación. Considerar PSMA-PET para re-estadificación. Evaluar RT de rescate temprana.",
                        guideline_reference="NCCN 5.2026 / EAU 2026: Criterio BCR post-RP",
                        triggering_value=f"{psa_val:.2f} ng/mL",
                        threshold="≥ 0.2 ng/mL",
                    ))
            except (ValueError, TypeError):
                pass

        return alerts

    @staticmethod
    def evaluate_lab_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa valores de laboratorio contra umbrales de seguridad.

        Umbrales:
            - Hemoglobina <10 g/dL bajo ADT → WARNING
            - AST/ALT >3x ULN bajo abiraterona → CRITICAL
            - ANC <1500 bajo docetaxel → CRITICAL
            - Testosterona >50 ng/dL bajo ADT → WARNING (castración no lograda)
            - ALP >2x ULN → WARNING (posible progresión ósea)
        """
        alerts: list[ClinicalAlert] = []

        hb = patient.get("hemoglobin") or patient.get("hemoglobina")
        if hb is not None:
            try:
                hb = float(hb)
                if 0 < hb < 10:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="anemia_adt",
                        severity="warning",
                        category="laboratory",
                        title="Anemia significativa (Hb < 10 g/dL)",
                        message=f"Hemoglobina: {hb:.1f} g/dL. Anemia grado 2+ frecuente bajo ADT/quimioterapia.",
                        recommended_action="Evaluar causa (ferropenia, sangrado, infiltración medular). Considerar transfusión si sintomático o Hb <8.",
                        guideline_reference="CTCAE v5 / NCCN Supportive Care",
                        triggering_value=f"{hb:.1f} g/dL",
                        threshold="< 10 g/dL",
                    ))
            except (ValueError, TypeError):
                pass

        testosterone = patient.get("testosterone") or patient.get("testosterone_current")
        adt_context = patient.get("adt_context", "none")
        if testosterone is not None and adt_context not in ("none", "", None):
            try:
                t = float(testosterone)
                if t > 50:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="castration_not_achieved",
                        severity="warning",
                        category="laboratory",
                        title="Testosterona > 50 ng/dL — Castración no lograda",
                        message=f"Testosterona: {t:.0f} ng/dL bajo ADT. No se ha logrado nivel de castración.",
                        recommended_action="Verificar adherencia a ADT. Considerar cambio de análogo GnRH o orquiectomía. Repetir testosterona en 4 semanas.",
                        guideline_reference="NCCN 5.2026 / EAU 2026: T <50 ng/dL requerido",
                        triggering_value=f"{t:.0f} ng/dL",
                        threshold="< 50 ng/dL",
                    ))
            except (ValueError, TypeError):
                pass

        alp = patient.get("alp") or patient.get("alkaline_phosphatase")
        if alp is not None:
            try:
                alp = float(alp)
                if alp > 240:  # ~2x ULN (ULN ~120 UI/L)
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="alp_elevated",
                        severity="warning",
                        category="laboratory",
                        title="Fosfatasa alcalina > 2x ULN",
                        message=f"ALP: {alp:.0f} UI/L. Elevación significativa sugiere progresión ósea o hepatopatía.",
                        recommended_action="Gammagrama óseo o PSMA-PET para evaluación de carga ósea. Descartar obstrucción biliar.",
                        guideline_reference="NCCN 5.2026",
                        triggering_value=f"{alp:.0f} UI/L",
                        threshold="> 240 UI/L (2x ULN)",
                    ))
            except (ValueError, TypeError):
                pass

        return alerts

    @staticmethod
    def evaluate_ecog_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa cambios en ECOG Performance Status.

        Umbrales:
            - ECOG ≥3 → CRITICAL (reevaluar intensidad terapéutica)
            - Incremento ≥1 punto vs última visita → WARNING
        """
        alerts: list[ClinicalAlert] = []

        ecog = patient.get("ecog") or patient.get("ecog_score")
        if ecog is not None:
            try:
                ecog = int(float(ecog))
                if ecog >= 3:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="ecog_critical",
                        severity="critical",
                        category="ecog",
                        title=f"ECOG {ecog} — Deterioro funcional severo",
                        message=f"ECOG Performance Status: {ecog}. Paciente con limitación significativa para autocuidado.",
                        recommended_action="Reevaluar intensidad terapéutica. Considerar transición a mejor soporte de cuidado o tratamiento adaptado. Evaluación paliativa.",
                        guideline_reference="NCCN 5.2026 / EAU 2026",
                        triggering_value=str(ecog),
                        threshold="≥ 3",
                    ))
            except (ValueError, TypeError):
                pass

        ecog_prev = patient.get("ecog_previous")
        if ecog is not None and ecog_prev is not None:
            try:
                delta = int(float(ecog)) - int(float(ecog_prev))
                if delta >= 1:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="ecog_decline",
                        severity="warning",
                        category="ecog",
                        title=f"Deterioro ECOG: {int(float(ecog_prev))} → {int(float(ecog))}",
                        message=f"Incremento de {delta} punto(s) en ECOG. Evaluar causa (progresión, toxicidad, comorbilidad).",
                        recommended_action="Investigar causa del deterioro. Ajustar plan terapéutico si está relacionado con toxicidad.",
                        guideline_reference="NCCN Supportive Care",
                        triggering_value=f"ECOG {int(float(ecog))}",
                        threshold="Incremento ≥ 1 punto",
                    ))
            except (ValueError, TypeError):
                pass

        return alerts

    @staticmethod
    def evaluate_treatment_milestones(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa milestones de tratamiento que requieren acción.

        - Duración de ADT (6, 12, 18, 24 meses) → info/recordatorio
        - Ciclos de docetaxel completados (6 = estándar)
        - Ventana de re-evaluación ARPI
        """
        alerts: list[ClinicalAlert] = []

        adt_months = patient.get("adt_duration_months")
        if adt_months is not None:
            try:
                months = float(adt_months)
                milestones = [
                    (6, "6 meses de ADT — Reevaluar respuesta y tolerancia"),
                    (12, "12 meses de ADT — Considerar intensificación o modulación"),
                    (18, "18 meses de ADT — Checkpoint de duración"),
                    (24, "24 meses de ADT — Evaluar suspensión vs continuación según riesgo"),
                ]
                for milestone_months, title in milestones:
                    if abs(months - milestone_months) < 1:
                        alerts.append(ClinicalAlert(
                            patient_id=patient_id,
                            alert_type=f"adt_milestone_{milestone_months}m",
                            severity="info",
                            category="treatment_milestone",
                            title=title,
                            message=f"Duración actual de ADT: {months:.0f} meses.",
                            recommended_action="Revisar plan terapéutico, efectos metabólicos/cardiovasculares y QoL.",
                            guideline_reference="NCCN 5.2026 / EAU 2026",
                            triggering_value=f"{months:.0f} meses",
                            threshold=f"{milestone_months} meses",
                        ))
            except (ValueError, TypeError):
                pass

        docetaxel_cycles = patient.get("prior_docetaxel_cycles")
        if docetaxel_cycles is not None:
            try:
                cycles = int(float(docetaxel_cycles))
                if cycles >= 6:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id,
                        alert_type="docetaxel_complete",
                        severity="info",
                        category="treatment_milestone",
                        title=f"Docetaxel: {cycles} ciclos completados",
                        message=f"Se completaron {cycles} ciclos de docetaxel (estándar = 6). Re-evaluar respuesta y plan de continuación.",
                        recommended_action="Re-estadificación con imagen. Evaluar transición a mantenimiento o siguiente línea.",
                        guideline_reference="TAX-327 / CHAARTED",
                        triggering_value=str(cycles),
                        threshold="6 ciclos",
                    ))
            except (ValueError, TypeError):
                pass

        return alerts

    @classmethod
    def run_all(cls, patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """Ejecuta todos los evaluadores de alertas y retorna alertas combinadas."""
        alerts: list[ClinicalAlert] = []
        alerts.extend(cls.evaluate_psa_kinetics(patient_id, patient))
        alerts.extend(cls.evaluate_lab_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_ecog_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_treatment_milestones(patient_id, patient))
        return alerts
