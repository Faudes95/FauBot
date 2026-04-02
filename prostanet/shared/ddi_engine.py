# -*- coding: utf-8 -*-
"""
Motor de interacciones farmacológicas (DDI) para oncología de próstata.

Verifica interacciones CYP3A4, riesgo QTc, umbral convulsivo y
pares de fármacos críticos. Incluye mapa de formulario IMSS/ISSSTE.

Reference:
  NCCN 5.2026 — Drug interaction documentation requirement
  PharmGKB / DrugBank — CYP metabolism data
  Fizazi K et al. — Abiraterone hepatotoxicity
  Shore ND et al. — Darolutamida seizure profile
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DDIAlert:
    """Interacción farmacológica detectada."""
    severity: str  # "contraindicated" | "major" | "moderate"
    drug_a: str
    drug_b: str
    mechanism: str
    clinical_impact: str
    recommended_action: str
    alternative: str = ""
    reference: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Base de datos de interacciones críticas en oncología de próstata ──
_DDI_RULES: list[dict[str, Any]] = [
    # CYP3A4 — Abiraterona
    {"drug_a": "abiraterona", "drug_b": "ketoconazol", "severity": "contraindicated",
     "mechanism": "Abiraterona es inhibidor CYP3A4 + ketoconazol es inhibidor CYP3A4 fuerte",
     "impact": "Hepatotoxicidad severa aditiva", "action": "No coadministrar. Usar antifúngico alternativo (fluconazol tópico).",
     "alternative": "Fluconazol tópico", "ref": "Fizazi K et al. / PharmGKB"},
    {"drug_a": "abiraterona", "drug_b": "warfarina", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP2C8 — altera metabolismo de warfarina",
     "impact": "Riesgo de sangrado por aumento de INR", "action": "Monitorear INR cada 1-2 semanas al iniciar. Considerar DOAC.",
     "alternative": "Rivaroxaban, apixaban", "ref": "PharmGKB / NCCN 5.2026"},
    {"drug_a": "abiraterona", "drug_b": "simvastatina", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP3A4 — aumenta niveles de estatinas metabolizadas por CYP3A4",
     "impact": "Riesgo de miopatía/rabdomiólisis", "action": "Cambiar a rosuvastatina o pravastatina (no CYP3A4).",
     "alternative": "Rosuvastatina, pravastatina", "ref": "DrugBank"},
    # CYP3A4 — Enzalutamida (inductor)
    {"drug_a": "enzalutamida", "drug_b": "warfarina", "severity": "major",
     "mechanism": "Enzalutamida es inductor CYP3A4 fuerte — reduce niveles de warfarina",
     "impact": "Pérdida de eficacia anticoagulante → riesgo trombótico", "action": "Monitorear INR frecuente. Considerar DOAC o ajustar dosis.",
     "alternative": "Apixaban con monitoreo", "ref": "PharmGKB"},
    {"drug_a": "enzalutamida", "drug_b": "omeprazol", "severity": "moderate",
     "mechanism": "Enzalutamida induce CYP2C19 — reduce niveles de omeprazol",
     "impact": "Pérdida de eficacia del IBP", "action": "Considerar dosis doble de IBP o cambiar a pantoprazol.",
     "alternative": "Pantoprazol dosis ajustada", "ref": "PharmGKB"},
    {"drug_a": "enzalutamida", "drug_b": "midazolam", "severity": "major",
     "mechanism": "Enzalutamida induce CYP3A4 — reduce niveles de benzodiacepinas CYP3A4",
     "impact": "Pérdida de eficacia sedante", "action": "Usar lorazepam (no CYP3A4) si se necesita benzodiacepina.",
     "alternative": "Lorazepam", "ref": "DrugBank"},
    # Olaparib
    {"drug_a": "olaparib", "drug_b": "itraconazol", "severity": "major",
     "mechanism": "Itraconazol es inhibidor CYP3A4 fuerte — aumenta niveles de olaparib",
     "impact": "Toxicidad hematológica aumentada", "action": "Reducir dosis de olaparib 50% o evitar inhibidor CYP3A4 fuerte.",
     "alternative": "Fluconazol (inhibidor CYP3A4 moderado)", "ref": "PharmGKB / Label FDA"},
    # Docetaxel
    {"drug_a": "docetaxel", "drug_b": "abiraterona", "severity": "major",
     "mechanism": "Abiraterona inhibe CYP3A4 — docetaxel se metaboliza por CYP3A4",
     "impact": "Aumento potencial de toxicidad hematológica de docetaxel (neutropenia)",
     "action": "Monitorear hemograma estrechamente durante triplete ADT+docetaxel+abiraterona. Considerar ajuste de dosis si toxicidad grado 3-4.",
     "alternative": "Secuenciar en lugar de combinar cuando sea posible", "ref": "PharmGKB / ARASENS protocol safety"},
    {"drug_a": "docetaxel", "drug_b": "ketoconazol", "severity": "major",
     "mechanism": "Ketoconazol inhibe CYP3A4 — aumenta exposición a docetaxel",
     "impact": "Neutropenia severa aumentada", "action": "Evitar coadministración. Antifúngico alternativo.",
     "alternative": "Fluconazol", "ref": "Label FDA docetaxel"},
    # QTc prolongation
    {"drug_a": "enzalutamida", "drug_b": "ondansetrón", "severity": "moderate",
     "mechanism": "Ambos pueden prolongar QTc",
     "impact": "Riesgo de arritmia", "action": "ECG basal y a las 2 semanas. Considerar granisetron.",
     "alternative": "Granisetron", "ref": "NCCN Antiemesis"},
    {"drug_a": "abiraterona", "drug_b": "amiodarona", "severity": "major",
     "mechanism": "Riesgo aditivo de prolongación QTc + interacción CYP",
     "impact": "Arritmia potencialmente fatal", "action": "Monitoreo ECG estrecho. Considerar alternativa antiarrítmica.",
     "alternative": "Consultar cardiología", "ref": "PharmGKB"},
    # Seizure risk
    {"drug_a": "enzalutamida", "drug_b": "tramadol", "severity": "major",
     "mechanism": "Tramadol baja umbral convulsivo + enzalutamida tiene riesgo convulsivo 0.9%",
     "impact": "Riesgo convulsivo aumentado", "action": "Evitar tramadol. Usar morfina o hidromorfona.",
     "alternative": "Morfina, hidromorfona", "ref": "NCCN Pain / Shore ND 2019"},
    {"drug_a": "apalutamida", "drug_b": "tramadol", "severity": "major",
     "mechanism": "Apalutamida puede bajar umbral convulsivo + tramadol es proconvulsivo",
     "impact": "Riesgo convulsivo aumentado", "action": "Evitar tramadol. Cambiar a opioide sin efecto proconvulsivo.",
     "alternative": "Morfina, oxicodona", "ref": "SPARTAN safety data"},
]


# ── Formulario por institución (México) ──
_FORMULARY: dict[str, dict[str, dict[str, Any]]] = {
    "IMSS": {
        "enzalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "abiraterona": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "apalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "darolutamida": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 85000, "exception_path": "Solicitar dictamen de alta especialidad con justificación ARAMIS"},
        "docetaxel": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "cabazitaxel": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "olaparib": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 95000, "exception_path": "Solicitar excepción con resultado PROfound-eligible y reporte molecular"},
        "pembrolizumab": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 120000, "exception_path": "Solicitar excepción con resultado MSI-H/dMMR confirmado"},
        "lu177_psma": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 150000, "exception_path": "Referir a centro con medicina nuclear (CMN SXXI, CMN La Raza)"},
        "radium223": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "zoledronato": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "denosumab": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
    },
    "ISSSTE": {
        "enzalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "abiraterona": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "apalutamida": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 78000, "exception_path": "Solicitar por comité farmacoterapéutico"},
        "darolutamida": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 85000, "exception_path": "Solicitar por comité farmacoterapéutico con justificación ARAMIS/ARASENS"},
        "docetaxel": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "cabazitaxel": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
        "olaparib": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 95000, "exception_path": "Solicitar por comité con reporte molecular PROfound-eligible"},
        "pembrolizumab": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 120000, "exception_path": "Solicitar por comité con MSI-H confirmado"},
        "lu177_psma": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 150000, "exception_path": "Referir a centro de medicina nuclear con capacidad"},
        "radium223": {"available": False, "cuadro_basico": False, "generic": False, "monthly_cost_mxn": 90000, "exception_path": "Solicitar por comité con criterios ALSYMPCA"},
        "zoledronato": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 0},
        "denosumab": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 0},
    },
    "privado": {
        "enzalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 45000},
        "abiraterona": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 8000},
        "apalutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 78000},
        "darolutamida": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 85000},
        "docetaxel": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 3000},
        "cabazitaxel": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 65000},
        "olaparib": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 95000},
        "pembrolizumab": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 120000},
        "lu177_psma": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 150000},
        "radium223": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 90000},
        "zoledronato": {"available": True, "cuadro_basico": True, "generic": True, "monthly_cost_mxn": 500},
        "denosumab": {"available": True, "cuadro_basico": True, "generic": False, "monthly_cost_mxn": 12000},
    },
}


class DDIEngine:
    """Motor de verificación de interacciones farmacológicas."""

    @classmethod
    def check_interactions(cls, oncology_drugs: list[str],
                           concomitant_medications: list[str],
                           seizure_history: bool = False) -> list[DDIAlert]:
        """Verifica interacciones entre fármacos oncológicos y medicamentos concomitantes."""
        alerts: list[DDIAlert] = []
        all_drugs = [d.lower().strip() for d in oncology_drugs + concomitant_medications if d]
        all_drug_set = set(all_drugs)

        for rule in _DDI_RULES:
            a = rule["drug_a"]
            b = rule["drug_b"]
            if a in all_drugs and b in all_drugs:
                alerts.append(DDIAlert(
                    severity=rule["severity"],
                    drug_a=rule["drug_a"].title(),
                    drug_b=rule["drug_b"].title(),
                    mechanism=rule["mechanism"],
                    clinical_impact=rule["impact"],
                    recommended_action=rule["action"],
                    alternative=rule.get("alternative", ""),
                    reference=rule.get("ref", ""),
                ))

        # Seizure risk check
        if seizure_history:
            for drug in all_drugs:
                if drug in {"enzalutamida", "apalutamida"}:
                    alerts.append(DDIAlert(
                        severity="contraindicated",
                        drug_a=drug.title(),
                        drug_b="Historia de convulsiones",
                        mechanism=f"{drug.title()} baja umbral convulsivo (0.9% enzalutamida, 0.6% apalutamida)",
                        clinical_impact="Riesgo convulsivo inaceptable",
                        recommended_action=f"Contraindicar {drug.title()}. Preferir darolutamida (0.2% seizures, baja penetración BHE).",
                        alternative="Darolutamida",
                        reference="SPARTAN, PROSPER safety data / Shore ND 2019",
                    ))
            # Triple check: seizure_history + ARPI proconvulsivo + tramadol = contraindicación absoluta
            arpi_proconvulsivo = all_drug_set & {"enzalutamida", "apalutamida"}
            if arpi_proconvulsivo and "tramadol" in all_drug_set:
                arpi_name = next(iter(arpi_proconvulsivo)).title()
                alerts.append(DDIAlert(
                    severity="contraindicated",
                    drug_a=f"{arpi_name} + Tramadol",
                    drug_b="Historia de convulsiones",
                    mechanism=f"Triple riesgo convulsivo: {arpi_name} (proconvulsivo) + tramadol (baja umbral) + historia de convulsiones",
                    clinical_impact="Riesgo convulsivo inaceptablemente alto — combinación triple absolutamente contraindicada",
                    recommended_action=f"Suspender {arpi_name} y tramadol. Cambiar a darolutamida + opioide sin efecto proconvulsivo (morfina, hidromorfona).",
                    alternative="Darolutamida + morfina/hidromorfona",
                    reference="SPARTAN safety / Shore ND 2019 / NCCN Pain Management",
                ))

        return alerts

    @classmethod
    def check_formulary(cls, drug_name: str, institution: str = "IMSS") -> dict[str, Any]:
        """Verifica disponibilidad en formulario institucional."""
        inst = institution.upper()
        if inst not in _FORMULARY:
            inst = "IMSS"
        formulary = _FORMULARY[inst]

        drug_key = drug_name.lower().strip().replace("-", "").replace(" ", "_")
        # Fuzzy match
        for key in formulary:
            if key in drug_key or drug_key in key:
                entry = formulary[key]
                return {
                    "drug": drug_name,
                    "institution": inst,
                    "available": entry["available"],
                    "cuadro_basico": entry["cuadro_basico"],
                    "generic_available": entry.get("generic", False),
                    "monthly_cost_mxn": entry.get("monthly_cost_mxn", 0),
                    "exception_path": entry.get("exception_path", ""),
                }
        return {
            "drug": drug_name,
            "institution": inst,
            "available": False,
            "cuadro_basico": False,
            "generic_available": False,
            "monthly_cost_mxn": 0,
            "exception_path": "Fármaco no encontrado en formulario — verificar disponibilidad con farmacia institucional.",
        }

    @classmethod
    def full_review(cls, patient: dict[str, Any]) -> dict[str, Any]:
        """Revisión completa de DDI y formulario para un paciente."""
        # Extract medications
        current_meds_raw = patient.get("current_medications") or ""
        if isinstance(current_meds_raw, str):
            current_meds = [m.strip() for m in current_meds_raw.replace(";", ",").split(",") if m.strip()]
        else:
            current_meds = list(current_meds_raw)

        oncology_drugs_raw = patient.get("oncology_drugs") or patient.get("current_treatment") or ""
        if isinstance(oncology_drugs_raw, str):
            oncology_drugs = [m.strip() for m in oncology_drugs_raw.replace(";", ",").split(",") if m.strip()]
        else:
            oncology_drugs = list(oncology_drugs_raw)

        seizure = str(patient.get("comorbidity_seizure") or patient.get("seizure_history") or "0")
        seizure_history = seizure.lower() in {"1", "true", "yes", "si"}

        # Check interactions
        ddi_alerts = cls.check_interactions(oncology_drugs, current_meds, seizure_history)

        # Check formulary for each oncology drug
        institution = str(patient.get("institution") or patient.get("institucion") or "IMSS")
        formulary_results = []
        for drug in oncology_drugs:
            formulary_results.append(cls.check_formulary(drug, institution))

        return {
            "ddi_alerts": [a.to_dict() for a in ddi_alerts],
            "ddi_count": len(ddi_alerts),
            "contraindicated_count": sum(1 for a in ddi_alerts if a.severity == "contraindicated"),
            "formulary": formulary_results,
            "institution": institution,
            "has_data": len(oncology_drugs) > 0 or len(current_meds) > 0,
            "ddi_reviewed": len(ddi_alerts) >= 0,  # Mark as reviewed
        }
