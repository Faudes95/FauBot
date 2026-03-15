# -*- coding: utf-8 -*-
"""
CTCAE v5.0 — Toxicidad estructurada para cáncer de próstata.

Define los eventos adversos más relevantes para terapias de próstata
con validación de grado, categoría y atribución.

Referencia: NCI Common Terminology Criteria for Adverse Events v5.0 (2017)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ── Términos CTCAE relevantes para terapias de Ca. próstata ─────────────────

PROSTATE_CTCAE_TERMS: dict[str, dict[str, str]] = {
    # Hematológicos
    "neutropenia": {"category": "hematologic", "es": "Neutropenia", "common_agents": "docetaxel, cabazitaxel"},
    "anemia": {"category": "hematologic", "es": "Anemia", "common_agents": "ADT, docetaxel, abiraterona"},
    "thrombocytopenia": {"category": "hematologic", "es": "Trombocitopenia", "common_agents": "docetaxel, cabazitaxel, olaparib"},
    "febrile_neutropenia": {"category": "hematologic", "es": "Neutropenia febril", "common_agents": "docetaxel, cabazitaxel"},
    # Hepáticos
    "alt_increased": {"category": "hepatic", "es": "Elevación de ALT", "common_agents": "abiraterona, enzalutamida"},
    "ast_increased": {"category": "hepatic", "es": "Elevación de AST", "common_agents": "abiraterona, enzalutamida"},
    "bilirubin_increased": {"category": "hepatic", "es": "Hiperbilirrubinemia", "common_agents": "abiraterona"},
    "hepatotoxicity": {"category": "hepatic", "es": "Hepatotoxicidad", "common_agents": "abiraterona"},
    # Cardiovasculares
    "hypertension": {"category": "cardiovascular", "es": "Hipertensión", "common_agents": "abiraterona, ADT"},
    "cardiac_arrhythmia": {"category": "cardiovascular", "es": "Arritmia cardiaca", "common_agents": "ADT, abiraterona"},
    "thromboembolic_event": {"category": "cardiovascular", "es": "Evento tromboembólico", "common_agents": "ADT, enzalutamida"},
    "edema": {"category": "cardiovascular", "es": "Edema", "common_agents": "abiraterona, docetaxel"},
    "qt_prolongation": {"category": "cardiovascular", "es": "Prolongación QT", "common_agents": "ADT (agonistas GnRH)"},
    # Gastrointestinales
    "nausea": {"category": "gastrointestinal", "es": "Náusea", "common_agents": "docetaxel, cabazitaxel, olaparib"},
    "diarrhea": {"category": "gastrointestinal", "es": "Diarrea", "common_agents": "abiraterona, docetaxel, enzalutamida"},
    "constipation": {"category": "gastrointestinal", "es": "Estreñimiento", "common_agents": "opioides, ondansetrón"},
    "mucositis": {"category": "gastrointestinal", "es": "Mucositis oral", "common_agents": "docetaxel"},
    # Neurológicos
    "seizure": {"category": "neurologic", "es": "Crisis convulsiva", "common_agents": "enzalutamida, apalutamida"},
    "peripheral_neuropathy": {"category": "neurologic", "es": "Neuropatía periférica", "common_agents": "docetaxel, cabazitaxel"},
    "cognitive_disturbance": {"category": "neurologic", "es": "Alteración cognitiva", "common_agents": "ADT, enzalutamida"},
    "fatigue": {"category": "neurologic", "es": "Fatiga", "common_agents": "ADT, enzalutamida, abiraterona, docetaxel, RT"},
    "dizziness": {"category": "neurologic", "es": "Mareo/vértigo", "common_agents": "apalutamida, darolutamida"},
    # Dermatológicos
    "rash": {"category": "dermatologic", "es": "Exantema/rash", "common_agents": "apalutamida, enzalutamida"},
    "alopecia": {"category": "dermatologic", "es": "Alopecia", "common_agents": "docetaxel, cabazitaxel"},
    # Renales / Electrolitos
    "hypokalemia": {"category": "renal", "es": "Hipokalemia", "common_agents": "abiraterona"},
    "acute_kidney_injury": {"category": "renal", "es": "Lesión renal aguda", "common_agents": "denosumab, zoledronato"},
    "fluid_retention": {"category": "renal", "es": "Retención de líquidos", "common_agents": "abiraterona, docetaxel"},
    # Endocrinos / Metabólicos
    "hot_flashes": {"category": "endocrine", "es": "Bochornos", "common_agents": "ADT (todas las formas)"},
    "gynecomastia": {"category": "endocrine", "es": "Ginecomastia", "common_agents": "ADT, bicalutamida"},
    "hyperglycemia": {"category": "endocrine", "es": "Hiperglucemia", "common_agents": "ADT, abiraterona + prednisona"},
    "weight_gain": {"category": "endocrine", "es": "Aumento de peso", "common_agents": "ADT"},
    # Musculoesqueléticos
    "bone_fracture": {"category": "musculoskeletal", "es": "Fractura ósea", "common_agents": "ADT, denosumab (al suspender)"},
    "arthralgia": {"category": "musculoskeletal", "es": "Artralgia", "common_agents": "enzalutamida, apalutamida, ADT"},
    "osteoporosis": {"category": "musculoskeletal", "es": "Osteoporosis", "common_agents": "ADT prolongada"},
    # Genitourinarios
    "urinary_incontinence": {"category": "genitourinary", "es": "Incontinencia urinaria", "common_agents": "prostatectomía, RT"},
    "erectile_dysfunction": {"category": "genitourinary", "es": "Disfunción eréctil", "common_agents": "prostatectomía, RT, ADT"},
    "hematuria": {"category": "genitourinary", "es": "Hematuria", "common_agents": "RT, tumor local"},
    "urinary_retention": {"category": "genitourinary", "es": "Retención urinaria", "common_agents": "tumor local, post-biopsia"},
}

VALID_CATEGORIES = {
    "hematologic", "hepatic", "cardiovascular", "gastrointestinal",
    "neurologic", "dermatologic", "renal", "endocrine",
    "musculoskeletal", "genitourinary", "other",
}

VALID_ATTRIBUTIONS = {
    "definite", "probable", "possible", "unlikely", "unrelated",
}

VALID_ACTIONS = {
    "none", "dose_reduction", "dose_delay", "drug_interruption",
    "drug_discontinuation", "hospitalization", "supportive_care",
    "medication_added", "procedure", "other",
}


@dataclass(frozen=True)
class ToxicityEvent:
    """Evento adverso estructurado CTCAE v5."""
    term: str
    grade: int  # 1-5
    category: str
    attribution: str = "possible"
    onset_date: str = ""
    resolution_date: str = ""
    action_taken: str = "none"
    agent_suspected: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CTCAEValidationError(ValueError):
    """Error de validación CTCAE."""
    pass


def validate_toxicity_event(event_dict: dict[str, Any]) -> ToxicityEvent:
    """
    Valida y construye un ToxicityEvent desde un dict.

    Raises:
        CTCAEValidationError si algún campo es inválido.
    """
    term = str(event_dict.get("term", "")).strip().lower()
    if not term:
        raise CTCAEValidationError("Se requiere un término CTCAE (campo 'term').")

    # Permitir términos no estándar con categoría 'other'
    known = term in PROSTATE_CTCAE_TERMS

    grade = event_dict.get("grade", 1)
    try:
        grade = int(grade)
    except (TypeError, ValueError):
        grade = 1
    if grade < 1 or grade > 5:
        raise CTCAEValidationError(f"Grado CTCAE debe ser 1-5, recibido: {grade}")

    category = str(event_dict.get("category", "")).strip().lower()
    if not category and known:
        category = PROSTATE_CTCAE_TERMS[term]["category"]
    if not category:
        category = "other"
    if category not in VALID_CATEGORIES:
        raise CTCAEValidationError(f"Categoría inválida: '{category}'. Válidas: {VALID_CATEGORIES}")

    attribution = str(event_dict.get("attribution", "possible")).strip().lower()
    if attribution not in VALID_ATTRIBUTIONS:
        attribution = "possible"

    action = str(event_dict.get("action_taken", "none")).strip().lower()
    if action not in VALID_ACTIONS:
        action = "other"

    return ToxicityEvent(
        term=term,
        grade=grade,
        category=category,
        attribution=attribution,
        onset_date=str(event_dict.get("onset_date", "")),
        resolution_date=str(event_dict.get("resolution_date", "")),
        action_taken=action,
        agent_suspected=str(event_dict.get("agent_suspected", "")),
        notes=str(event_dict.get("notes", "")),
    )


def validate_toxicity_list(events: list[dict]) -> list[ToxicityEvent]:
    """Valida una lista de eventos de toxicidad."""
    validated = []
    for ev in events:
        validated.append(validate_toxicity_event(ev))
    return validated


def severity_summary(events: list[ToxicityEvent]) -> dict[str, Any]:
    """
    Genera un resumen de severidad de toxicidad.

    Retorna:
        - max_grade: grado máximo reportado
        - grade_3_plus_count: total de eventos grado ≥3
        - categories_affected: categorías únicas afectadas
        - requires_dose_modification: True si algún evento requirió cambio de dosis
        - active_events: eventos sin fecha de resolución
    """
    if not events:
        return {
            "max_grade": 0,
            "grade_3_plus_count": 0,
            "categories_affected": [],
            "requires_dose_modification": False,
            "active_events": 0,
        }

    dose_mod_actions = {"dose_reduction", "dose_delay", "drug_interruption", "drug_discontinuation"}

    return {
        "max_grade": max(e.grade for e in events),
        "grade_3_plus_count": sum(1 for e in events if e.grade >= 3),
        "categories_affected": sorted({e.category for e in events}),
        "requires_dose_modification": any(e.action_taken in dose_mod_actions for e in events),
        "active_events": sum(1 for e in events if not e.resolution_date),
    }
