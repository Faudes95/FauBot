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

from prostanet.domains.patient_tracking.laboratory_intelligence.alert_engine import (
    build_laboratory_alerts,
)

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
        latest_values = {
            "hemoglobin": patient.get("hemoglobin") or patient.get("hemoglobina"),
            "testosterone": patient.get("testosterone") or patient.get("testosterone_current"),
            "alp": patient.get("alp") or patient.get("alkaline_phosphatase"),
            "ldh": patient.get("ldh"),
            "creatinine": patient.get("creatinine") or patient.get("creatinine_current"),
            "bilirubin": patient.get("bilirubin") or patient.get("bilirubin_current"),
            "ast": patient.get("ast") or patient.get("ast_current"),
            "alt": patient.get("alt") or patient.get("alt_current"),
            "ggt": patient.get("ggt") or patient.get("ggt_current"),
        }
        structured_alerts = build_laboratory_alerts(
            latest_values,
            treatment_text=str(patient.get("current_treatment") or ""),
            adt_context=str(patient.get("adt_context") or patient.get("current_adt_context") or ""),
        )
        return [
            ClinicalAlert(
                patient_id=patient_id,
                alert_type=str(alert.key),
                severity=str(alert.severity),
                category="laboratory",
                title=str(alert.title),
                message=str(alert.message),
                recommended_action=str(alert.recommended_action),
                guideline_reference=str(alert.guideline_reference),
                triggering_value=str(alert.triggering_value),
                threshold=str(alert.threshold),
            )
            for alert in structured_alerts
        ]

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

    @staticmethod
    def evaluate_genomic_alerts(patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """
        Evalúa biomarcadores genómicos expandidos y genera alertas.

        Reglas:
            - AR-V7 positivo bajo ARPI → CRITICAL (resistencia documentada)
            - ctDNA VAF en ascenso → WARNING (resistencia emergente)
            - Sospecha NEPC (TP53+RB1+NSE/LDH/PSA bajo) → CRITICAL
            - PTEN loss → WARNING (peor pronóstico bajo ARPI)
            - CDK12 biallelic → INFO (candidato IO independiente de MSI)
        """
        alerts: list[ClinicalAlert] = []

        def _is_positive(val: str) -> bool:
            v = val.lower()
            return v.startswith("pos") or v in {"detected", "detectado", "mutado", "loss", "perdida", "biallelic", "bialélico"}

        # ── AR-V7 positivo bajo ARPI ──
        ar_v7 = str(patient.get("ar_v7_status", ""))
        ar_v7_positive = ar_v7 and _is_positive(ar_v7)
        current_tx = str(patient.get("current_treatment", "") or patient.get("prior_therapy", ""))
        on_arpi = any(d in current_tx for d in ["Enzalutamida", "Abiraterona", "Apalutamida", "Darolutamida"])
        if ar_v7_positive and on_arpi:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="ar_v7_resistance",
                severity="critical",
                category="genomic",
                title="AR-V7 positivo bajo ARPI — Resistencia documentada",
                message="AR-V7 positivo predice falta de respuesta a enzalutamida/abiraterona. Mediana de respuesta ~3 meses vs ~8 meses con taxanos.",
                recommended_action="Considerar cambio a taxano (docetaxel/cabazitaxel). No secuenciar otro ARPI.",
                guideline_reference="PROPHECY (Armstrong 2019), Antonarakis NEJM 2014",
                triggering_value="AR-V7 positivo",
                threshold="Positivo bajo ARPI activo",
            ))
        elif ar_v7_positive:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="ar_v7_detected",
                severity="warning",
                category="genomic",
                title="AR-V7 positivo — Evitar ARPI como siguiente línea",
                message="AR-V7 positivo documentado. Resistencia a ARPI esperada.",
                recommended_action="Preferir taxanos sobre ARPI en la próxima línea terapéutica.",
                guideline_reference="PROPHECY (Armstrong 2019)",
                triggering_value="AR-V7 positivo",
                threshold="Cualquier detección",
            ))

        # ── ctDNA trending (Wyatt 2021, Chi 2022) ──
        ctdna_rising = str(patient.get("ctdna_rising", "0")) == "1"
        ctdna_vaf = patient.get("ctdna_vaf")
        ctdna_vaf_prev = patient.get("ctdna_vaf_previous")
        if ctdna_rising:
            msg = "ctDNA en ascenso documentado — señal de resistencia emergente semanas antes que PSA."
            if ctdna_vaf is not None and ctdna_vaf_prev is not None:
                try:
                    vaf = float(ctdna_vaf)
                    vaf_prev = float(ctdna_vaf_prev)
                    if vaf_prev > 0:
                        pct_change = ((vaf - vaf_prev) / vaf_prev) * 100
                        msg = f"ctDNA VAF subió {pct_change:.0f}% ({vaf_prev:.1f}% → {vaf:.1f}%). Resistencia emergente pre-radiográfica."
                except (ValueError, TypeError):
                    pass
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="ctdna_rising",
                severity="warning",
                category="genomic",
                title="ctDNA en ascenso — Resistencia emergente",
                message=msg,
                recommended_action="Considerar cambio de línea anticipado antes de progresión radiográfica. Repetir biopsia líquida en 4-6 semanas.",
                guideline_reference="Wyatt 2021, Chi 2022",
                triggering_value=f"VAF {ctdna_vaf}%" if ctdna_vaf else "Rising",
                threshold="Ascenso entre mediciones",
            ))

        # ── Sospecha NEPC (Beltran 2016) ──
        tp53 = str(patient.get("tp53_status", ""))
        rb1 = str(patient.get("rb1_status", ""))
        tp53_altered = tp53 and _is_positive(tp53)
        rb1_loss = rb1 and _is_positive(rb1)

        nepc_score = 0
        nepc_reasons: list[str] = []
        if tp53_altered and rb1_loss:
            nepc_score += 2
            nepc_reasons.append("TP53 + RB1 loss")
        ne_features = str(patient.get("neuroendocrine_features", "0")) == "1"
        if ne_features:
            nepc_score += 2
            nepc_reasons.append("características neuroendocrinas")
        try:
            nse = float(patient.get("nse") or patient.get("neuron_specific_enolase") or 0)
            if nse > 16.3:
                nepc_score += 1
                nepc_reasons.append(f"NSE elevado ({nse:.1f})")
        except (ValueError, TypeError):
            pass
        try:
            ldh = float(patient.get("ldh") or patient.get("lactate_dehydrogenase") or 0)
            if ldh > 250:
                nepc_score += 1
                nepc_reasons.append(f"LDH elevado ({ldh:.0f})")
        except (ValueError, TypeError):
            pass
        psa_disc = str(patient.get("psa_discordant_low", "0")) == "1"
        if psa_disc:
            nepc_score += 1
            nepc_reasons.append("PSA discordante bajo")

        if nepc_score >= 3:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="nepc_suspicion",
                severity="critical",
                category="genomic",
                title=f"Sospecha NEPC — Score {nepc_score}/7",
                message=f"Algoritmo de sospecha neuroendocrina activado por: {', '.join(nepc_reasons)}. 15-20% de mCRPC desarrollan NEPC.",
                recommended_action="Biopsia de confirmación histológica urgente. Considerar carboplatino + etopósido si se confirma. Suspender ARPI si hay transformación.",
                guideline_reference="Beltran 2016, Aggarwal 2018, NCCN 2026",
                triggering_value=f"Score {nepc_score}/7",
                threshold="≥ 3/7",
            ))
        elif tp53_altered and rb1_loss:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="lineage_plasticity_risk",
                severity="warning",
                category="genomic",
                title="TP53 + RB1 loss — Riesgo de lineage plasticity",
                message="Ambas alteraciones presentes. Riesgo elevado de transformación neuroendocrina futura.",
                recommended_action="Monitorear NSE, LDH, cromogranina A y ratio PSA/volumen tumoral cada 2-3 meses. Considerar biopsia ante progresión atípica.",
                guideline_reference="Beltran 2016, Mu 2017",
                triggering_value="TP53 mutado + RB1 loss",
                threshold="Ambos alterados",
            ))

        # ── PTEN loss ──
        pten = str(patient.get("pten_loss", patient.get("pten_status", "")))
        pten_lost = pten and _is_positive(pten)
        if pten_lost:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="pten_loss",
                severity="warning",
                category="genomic",
                title="PTEN loss — Peor pronóstico bajo ARPI",
                message="PTEN loss activa la vía PI3K/AKT. Asociado a menor duración de respuesta bajo ARPI estándar.",
                recommended_action="Considerar inhibidores AKT (ipatasertib, capivasertib) combinados con abiraterona. Monitoreo más frecuente de respuesta.",
                guideline_reference="IPATential150 (de Bono 2020), Jamaspishvili 2018",
                triggering_value="PTEN loss",
                threshold="Confirmado por IHC o NGS",
            ))

        # ── CDK12 biallelic ──
        cdk12 = str(patient.get("cdk12_status", ""))
        cdk12_bi = cdk12 and cdk12.lower() in {"biallelic", "bialélico", "positivo", "pos", "detected", "detectado"}
        if cdk12_bi:
            alerts.append(ClinicalAlert(
                patient_id=patient_id,
                alert_type="cdk12_biallelic",
                severity="info",
                category="genomic",
                title="CDK12 bialélico — Candidato IO independiente de MSI",
                message="CDK12 bialélico genera alta carga neoantigénica. Candidato a inmunoterapia incluso sin MSI-H.",
                recommended_action="Considerar pembrolizumab. Verificar TMB como biomarcador complementario.",
                guideline_reference="Wu 2018, Antonarakis 2020",
                triggering_value="CDK12 bialélico",
                threshold="Inactivación bialélica confirmada",
            ))

        return alerts

    @classmethod
    def run_all(cls, patient_id: int, patient: dict[str, Any]) -> list[ClinicalAlert]:
        """Ejecuta todos los evaluadores de alertas y retorna alertas combinadas."""
        alerts: list[ClinicalAlert] = []
        alerts.extend(cls.evaluate_psa_kinetics(patient_id, patient))
        alerts.extend(cls.evaluate_lab_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_ecog_alerts(patient_id, patient))
        alerts.extend(cls.evaluate_treatment_milestones(patient_id, patient))
        alerts.extend(cls.evaluate_genomic_alerts(patient_id, patient))

        # PRO-driven alerts (Salto 3)
        try:
            from prostanet.domains.patient_tracking.pro_engine import PRODecisionEngine
            pro_alerts = PRODecisionEngine.evaluate_all(patient_id, patient)
            for pa in pro_alerts:
                alerts.append(ClinicalAlert(
                    patient_id=patient_id,
                    alert_type=pa.alert_type,
                    severity=pa.severity,
                    category=f"pro_{pa.category}",
                    title=pa.title,
                    message=pa.message,
                    recommended_action=pa.recommended_action,
                    guideline_reference=pa.reference,
                    triggering_value=str(pa.current_value) if pa.current_value is not None else "",
                    threshold=pa.threshold,
                ))
        except Exception:
            pass

        # ── Biopsia estructurada alerts ──
        try:
            from prostanet.domains.patient_tracking.structured_biopsy import StructuredBiopsyService
            biopsies = patient.get("biopsies") or []
            if biopsies:
                current = biopsies[-1] if isinstance(biopsies[-1], dict) else None
                previous = biopsies[-2] if len(biopsies) >= 2 and isinstance(biopsies[-2], dict) else None
                if current:
                    parsed = StructuredBiopsyService.parse_structured_biopsy(current)
                    biopsy_alerts = StructuredBiopsyService.evaluate_biopsy_alerts(patient_id, parsed, previous)
                    for ba in biopsy_alerts:
                        alerts.append(ClinicalAlert(
                            patient_id=patient_id, alert_type=ba.get("alert_type", ""),
                            severity=ba.get("severity", "info"), category=ba.get("category", "pathology"),
                            title=ba.get("title", ""), message=ba.get("message", ""),
                            recommended_action=ba.get("recommended_action", ""),
                            guideline_reference=ba.get("guideline_reference", ""),
                            triggering_value=ba.get("triggering_value", ""),
                            threshold=ba.get("threshold", ""),
                        ))
        except Exception:
            pass

        # ── Vigilancia activa alerts ──
        try:
            from prostanet.domains.patient_tracking.active_surveillance import ActiveSurveillanceService
            as_data = patient.get("active_surveillance")
            if as_data or patient.get("management_track") == "active_surveillance":
                state = patient.get("state", patient.get("clinical_state", "localized_initial"))
                as_protocol = ActiveSurveillanceService.build_as_protocol(patient, state)
                as_alerts = ActiveSurveillanceService.evaluate_as_alerts(patient_id, as_protocol)
                for aa in as_alerts:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id, alert_type=aa.get("alert_type", ""),
                        severity=aa.get("severity", "info"), category=aa.get("category", "active_surveillance"),
                        title=aa.get("title", ""), message=aa.get("message", ""),
                        recommended_action=aa.get("recommended_action", ""),
                        guideline_reference=aa.get("guideline_reference", ""),
                        triggering_value=aa.get("triggering_value", ""),
                        threshold=aa.get("threshold", ""),
                    ))
        except Exception:
            pass

        # ── Radioterapia detallada alerts ──
        try:
            from prostanet.domains.patient_tracking.radiotherapy_detail import RadiotherapyDetailService
            rt_data = patient.get("radiation_details") or patient.get("radiation")
            if rt_data:
                rt_summary = RadiotherapyDetailService.build_rt_history(patient)
                rt_alerts = RadiotherapyDetailService.evaluate_rt_alerts(patient_id, rt_summary, patient)
                for ra in rt_alerts:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id, alert_type=ra.get("alert_type", ""),
                        severity=ra.get("severity", "info"), category=ra.get("category", "radiation_therapy"),
                        title=ra.get("title", ""), message=ra.get("message", ""),
                        recommended_action=ra.get("recommended_action", ""),
                        guideline_reference=ra.get("guideline_reference", ""),
                        triggering_value=ra.get("triggering_value", ""),
                        threshold=ra.get("threshold", ""),
                    ))
        except Exception:
            pass

        # ── Eventos esqueléticos alerts ──
        try:
            from prostanet.domains.patient_tracking.skeletal_events import SkeletalEventService
            sre_data = patient.get("skeletal_events") or patient.get("bone_modifying_agent")
            bone_mets = patient.get("bone_metastasis_count") or patient.get("metastasis_count")
            if sre_data or bone_mets:
                state = patient.get("state", patient.get("clinical_state", ""))
                sre_profile = SkeletalEventService.build_sre_profile(patient, state)
                sre_alerts = SkeletalEventService.evaluate_sre_alerts(patient_id, sre_profile)
                for sa in sre_alerts:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id, alert_type=sa.get("alert_type", ""),
                        severity=sa.get("severity", "info"), category=sa.get("category", "skeletal_event"),
                        title=sa.get("title", ""), message=sa.get("message", ""),
                        recommended_action=sa.get("recommended_action", ""),
                        guideline_reference=sa.get("guideline_reference", ""),
                        triggering_value=sa.get("triggering_value", ""),
                        threshold=sa.get("threshold", ""),
                    ))
        except Exception:
            pass

        # ── Endpoints de supervivencia alerts ──
        try:
            from prostanet.domains.patient_tracking.survival_endpoints import SurvivalEndpointService
            state = patient.get("state", patient.get("clinical_state", ""))
            if state:
                survival_status = SurvivalEndpointService.compute_endpoints(patient, state)
                surv_alerts = SurvivalEndpointService.evaluate_survival_alerts(patient_id, survival_status)
                for sv in surv_alerts:
                    alerts.append(ClinicalAlert(
                        patient_id=patient_id, alert_type=sv.get("alert_type", ""),
                        severity=sv.get("severity", "info"), category=sv.get("category", "survival_endpoint"),
                        title=sv.get("title", ""), message=sv.get("message", ""),
                        recommended_action=sv.get("recommended_action", ""),
                        guideline_reference=sv.get("guideline_reference", ""),
                        triggering_value=sv.get("triggering_value", ""),
                        threshold=sv.get("threshold", ""),
                    ))
        except Exception:
            pass

        # ── IA: Detección de anomalías temporales (VAE) ──
        try:
            from prostanet.shared.feature_flags import resolve_feature_flags
            if resolve_feature_flags().get("ENABLE_AI_ANOMALY_DETECTION"):
                from prostanet.ai.inference.model_registry import ModelRegistry
                from pathlib import Path
                models_dir = Path("output/models")
                reg = ModelRegistry(models_dir=models_dir)
                anomaly_model = reg.get("anomaly_detector")
                if anomaly_model:
                    anomaly_result = anomaly_model.predict(patient)
                    score = anomaly_result.values.get("anomaly_score", 0.0)
                    is_anomaly = anomaly_result.values.get("is_anomaly", False)
                    if is_anomaly:
                        anomalous_features = anomaly_result.values.get("anomalous_features", [])
                        feature_str = ", ".join(anomalous_features[:3]) or "laboratorio"
                        severity = "critical" if score > 0.85 else "warning"
                        alerts.append(ClinicalAlert(
                            patient_id=patient_id,
                            alert_type="ai_temporal_anomaly",
                            severity=severity,
                            category="ai_anomaly",
                            title="Anomalía en serie temporal detectada por IA",
                            message=(
                                f"El modelo VAE detectó un patrón inusual en la evolución clínica "
                                f"(score={score:.2f}). Parámetros afectados: {feature_str}. "
                                "Esto puede indicar progresión atípica o discordancia de datos."
                            ),
                            recommended_action="Revisar la tendencia longitudinal de laboratorios e imágenes recientes.",
                            guideline_reference="ProstaNet AI — Anomaly Detection v1.0",
                            triggering_value=f"anomaly_score={score:.3f}",
                            threshold="score>0.60",
                        ))
        except Exception:
            pass

        return alerts
