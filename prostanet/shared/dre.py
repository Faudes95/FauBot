from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


DRE_FINDING_OPTIONS = [
    "Normal",
    "T1 - No palpable (detectado por PSA)",
    "T2a - Afecta ≤50% de un lóbulo",
    "T2b - Afecta >50% de un lóbulo",
    "T2c - Afecta ambos lóbulos",
    "T3 - Extensión fuera de la cápsula",
    "T4 - Invade órganos adyacentes",
]

TRUE_VALUES = {"1", "true", "yes", "si", "sí", "on", "positive", "positivo", "sospechoso", "abnormal"}
FALSE_VALUES = {"0", "false", "no", "normal", "negativo", "negative", "no sospechoso"}
NORMAL_DRE_VALUES = {"", "0", "normal", "no", "false", "negativo", "negative", "no sospechoso"}


@dataclass(frozen=True)
class DREAssessment:
    """Normalized digital rectal exam signal used across diagnostic flows."""

    is_documented: bool
    is_suspicious: bool
    implied_tstage: str | None = None
    source: str | None = None
    raw_value: Any | None = None

    @property
    def binary_value(self) -> str:
        return "1" if self.is_suspicious else "0"


def normalize_dre(payload: dict[str, Any] | None, *, include_clinical_stage: bool = True) -> DREAssessment:
    """Return a single DRE interpretation from structured and legacy fields.

    Newer wizards capture ``dre_finding`` as a T-stage-like option, while older
    routes capture ``dre_suspicious`` as a binary flag. This helper keeps those
    representations clinically equivalent without inventing a normal DRE when
    no DRE field was documented.
    """
    data = payload or {}
    source_order = ["dre_finding", "dre_findings", "dre_suspicious"]
    if include_clinical_stage:
        source_order.extend(["clinical_tstage", "tnm_stage"])

    documented: list[DREAssessment] = []
    for source in source_order:
        if source not in data:
            continue
        assessment = _assessment_from_value(data.get(source), source=source)
        if assessment.is_documented:
            documented.append(assessment)

    suspicious = [item for item in documented if item.is_suspicious]
    if suspicious:
        staged = next((item for item in suspicious if item.implied_tstage), None)
        return staged or suspicious[0]
    if documented:
        staged = next((item for item in documented if item.implied_tstage), None)
        return staged or documented[0]
    return DREAssessment(is_documented=False, is_suspicious=False)


def has_dre_documentation(payload: dict[str, Any] | None) -> bool:
    """True when a DRE-specific field, normal or abnormal, was supplied."""
    data = payload or {}
    for source in ("dre_finding", "dre_findings", "dre_suspicious"):
        if source in data and _assessment_from_value(data.get(source), source=source).is_documented:
            return True
    return False


def is_dre_suspicious(payload: dict[str, Any] | None, *, include_clinical_stage: bool = True) -> bool:
    return normalize_dre(payload, include_clinical_stage=include_clinical_stage).is_suspicious


def apply_dre_normalization(
    payload: dict[str, Any] | None,
    *,
    include_clinical_stage: bool = True,
    in_place: bool = False,
) -> dict[str, Any]:
    """Fill legacy-compatible DRE fields when a DRE signal is documented."""
    data = payload if in_place else dict(payload or {})
    assessment = normalize_dre(data, include_clinical_stage=include_clinical_stage)
    if not assessment.is_documented:
        return data

    data["dre_suspicious"] = assessment.binary_value
    if assessment.source in {"dre_findings", "dre_finding"} and "dre_finding" not in data:
        data["dre_finding"] = assessment.raw_value
    if assessment.implied_tstage and assessment.is_suspicious and not _has_value(data.get("clinical_tstage")):
        data["clinical_tstage"] = assessment.implied_tstage
    return data


def dre_to_tstage(value: Any) -> str | None:
    assessment = _assessment_from_value(value, source="dre_finding")
    return assessment.implied_tstage


def _assessment_from_value(value: Any, *, source: str) -> DREAssessment:
    if value is None:
        return DREAssessment(False, False, source=source, raw_value=value)

    raw = str(value).strip()
    if raw == "":
        return DREAssessment(False, False, source=source, raw_value=value)

    normalized = raw.casefold()
    if normalized in NORMAL_DRE_VALUES:
        return DREAssessment(True, False, source=source, raw_value=value)

    tstage = _canonical_tstage(raw)
    if tstage:
        return DREAssessment(True, _is_suspicious_tstage(tstage), tstage, source, value)

    if normalized in TRUE_VALUES:
        return DREAssessment(True, True, "T2a", source, value)
    if normalized in FALSE_VALUES:
        return DREAssessment(True, False, source=source, raw_value=value)

    # Descriptive abnormal findings should remain safety-positive even without
    # a precise T-stage.
    if any(token in normalized for token in ("nodul", "indur", "asimetr", "duro", "hard", "sospech")):
        return DREAssessment(True, True, "T2a", source, value)

    return DREAssessment(True, False, source=source, raw_value=value)


def _canonical_tstage(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text.upper())
    match = re.search(r"T([1-4])([ABC])?", compact)
    if not match:
        return None

    number = match.group(1)
    suffix = match.group(2) or ""
    if number == "2" and suffix == "":
        return "T2a"
    return f"T{number}{suffix.lower()}"


def _is_suspicious_tstage(tstage: str) -> bool:
    return str(tstage or "").upper().startswith(("T2", "T3", "T4"))


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No realizado", "Desconocido", "Desconocida")
