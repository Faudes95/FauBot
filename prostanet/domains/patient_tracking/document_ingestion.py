from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from prostanet.shared.contracts import (
    DocumentExtractionCandidate,
    SourceDocument,
    VerificationTask,
    VerifiedFact,
    VerifiedFactBundle,
)


DEFAULT_PATIENT_DOCUMENT_ROOT = Path(
    os.environ.get(
        "PROSTANET_PATIENT_DOCUMENTS",
        Path.cwd() / ".prostanet_private" / "patient_documents",
    )
)

SUPPORTED_DOCUMENT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt"}

DOCUMENT_TYPE_LABELS = {
    "pathology_report": "Reporte histopatológico / biopsia",
    "laboratory_bundle": "Paquete de laboratorios",
    "imaging_report": "Reporte de imagen",
    "genomic_report": "Reporte molecular / genómico",
    "surgery_summary": "Resumen quirúrgico",
    "radiotherapy_summary": "Resumen de radioterapia",
    "unclassified_clinical_report": "Reporte clínico por clasificar",
}

LOCATION_OPTIONS = [
    "Lecho prostático",
    "Ganglios pélvicos",
    "Ganglios retroperitoneales",
    "Hueso axial",
    "Hueso apendicular",
    "Pulmón",
    "Hígado",
    "Suprarrenal",
    "Otra visceral",
]


def _is_present(value: Any) -> bool:
    return value not in (None, "", [], {}, "No aplica", "No documentado", "Desconocido", "Desconocida")


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


def _guess_mime_type(file_name: str, explicit_mime: str = "") -> str:
    if explicit_mime:
        return explicit_mime
    return mimetypes.guess_type(file_name)[0] or "application/octet-stream"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def _value_display(value: Any) -> str:
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _bucket_psma_suv(value: float | None) -> str:
    if value is None:
        return ""
    if value < 6:
        return "<6"
    if value < 9:
        return "6-9"
    if value < 12:
        return "9-12"
    return ">12"


def _manual_template(document_type: str) -> list[dict[str, Any]]:
    templates = {
        "pathology_report": [
            {"field_name": "biopsy_date", "label": "Fecha de biopsia", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "date"},
            {"field_name": "gleason_primary", "label": "Gleason primario", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "number"},
            {"field_name": "gleason_secondary", "label": "Gleason secundario", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "number"},
            {"field_name": "isup_grade", "label": "ISUP / Grade Group", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "number"},
            {"field_name": "positive_cores", "label": "Cilindros positivos", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "number"},
            {"field_name": "total_cores", "label": "Cilindros totales", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "number"},
            {"field_name": "porcentaje_patron_4", "label": "Porcentaje patrón 4", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "number"},
            {"field_name": "patron_cribiforme", "label": "Patrón cribriforme", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "checkbox"},
            {"field_name": "carcinoma_intraductal", "label": "Carcinoma intraductal", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "checkbox"},
            {"field_name": "adverse_histology_variant_type", "label": "Variante histológica adversa", "fact_group": "pathology", "target_result_type": "pathology", "field_type": "text"},
        ],
        "laboratory_bundle": [
            {"field_name": "visit_date", "label": "Fecha del laboratorio", "fact_group": "lab_panel", "target_result_type": "lab_panel", "field_type": "date"},
            {"field_name": "psa", "label": "PSA", "fact_group": "lab_panel", "target_result_type": "lab_panel", "field_type": "number"},
            {"field_name": "testosterone", "label": "Testosterona", "fact_group": "lab_panel", "target_result_type": "lab_panel", "field_type": "number"},
            {"field_name": "hemoglobin", "label": "Hemoglobina", "fact_group": "lab_panel", "target_result_type": "lab_panel", "field_type": "number"},
            {"field_name": "creatinine", "label": "Creatinina", "fact_group": "lab_panel", "target_result_type": "lab_panel", "field_type": "number"},
            {"field_name": "ldh", "label": "LDH", "fact_group": "lab_panel", "target_result_type": "lab_panel", "field_type": "number"},
            {"field_name": "alp", "label": "ALP", "fact_group": "lab_panel", "target_result_type": "lab_panel", "field_type": "number"},
        ],
        "imaging_report": [
            {"field_name": "study_date", "label": "Fecha del estudio", "fact_group": "imaging", "target_result_type": "imaging", "field_type": "date"},
            {"field_name": "study_type", "label": "Modalidad", "fact_group": "imaging", "target_result_type": "imaging", "field_type": "text"},
            {"field_name": "psma_result", "label": "Resultado PSMA", "fact_group": "imaging", "target_result_type": "imaging", "field_type": "text"},
            {"field_name": "psma_suv_max", "label": "SUV max", "fact_group": "imaging", "target_result_type": "imaging", "field_type": "number"},
            {"field_name": "lesion_locations", "label": "Ubicaciones de lesión (coma separada)", "fact_group": "imaging", "target_result_type": "imaging", "field_type": "textarea"},
            {"field_name": "psma_total_lesions", "label": "Número total de lesiones", "fact_group": "imaging", "target_result_type": "imaging", "field_type": "number"},
        ],
        "genomic_report": [
            {"field_name": "test_date", "label": "Fecha del estudio", "fact_group": "genomic", "target_result_type": "genomic", "field_type": "date"},
            {"field_name": "test_type", "label": "Tipo de estudio", "fact_group": "genomic", "target_result_type": "genomic", "field_type": "text"},
            {"field_name": "hrr_overall", "label": "HRR global", "fact_group": "genomic", "target_result_type": "genomic", "field_type": "text"},
            {"field_name": "brca2_status", "label": "BRCA2", "fact_group": "genomic", "target_result_type": "genomic", "field_type": "text"},
            {"field_name": "msi_status", "label": "MSI", "fact_group": "genomic", "target_result_type": "genomic", "field_type": "text"},
            {"field_name": "tmb_score", "label": "TMB", "fact_group": "genomic", "target_result_type": "genomic", "field_type": "number"},
            {"field_name": "decipher_risk", "label": "Decipher", "fact_group": "genomic", "target_result_type": "genomic", "field_type": "text"},
        ],
        "surgery_summary": [
            {"field_name": "surgery_date", "label": "Fecha de cirugía", "fact_group": "surgery", "target_result_type": "surgery_summary", "field_type": "date"},
            {"field_name": "pathological_stage", "label": "Estadio patológico", "fact_group": "surgery", "target_result_type": "surgery_summary", "field_type": "text"},
            {"field_name": "surgical_margin_status", "label": "Margen positivo", "fact_group": "surgery", "target_result_type": "surgery_summary", "field_type": "checkbox"},
            {"field_name": "margin_location", "label": "Localización del margen", "fact_group": "surgery", "target_result_type": "surgery_summary", "field_type": "text"},
            {"field_name": "nodes_removed", "label": "Ganglios resecados", "fact_group": "surgery", "target_result_type": "surgery_summary", "field_type": "number"},
            {"field_name": "nodes_positive", "label": "Ganglios positivos", "fact_group": "surgery", "target_result_type": "surgery_summary", "field_type": "number"},
        ],
        "radiotherapy_summary": [
            {"field_name": "rt_date", "label": "Fecha de inicio RT", "fact_group": "radiotherapy", "target_result_type": "radiotherapy_summary", "field_type": "date"},
            {"field_name": "rt_context", "label": "Contexto RT", "fact_group": "radiotherapy", "target_result_type": "radiotherapy_summary", "field_type": "text"},
            {"field_name": "rt_technique", "label": "Técnica", "fact_group": "radiotherapy", "target_result_type": "radiotherapy_summary", "field_type": "text"},
            {"field_name": "total_dose_gy", "label": "Dosis total (Gy)", "fact_group": "radiotherapy", "target_result_type": "radiotherapy_summary", "field_type": "number"},
            {"field_name": "fractions", "label": "Fracciones", "fact_group": "radiotherapy", "target_result_type": "radiotherapy_summary", "field_type": "number"},
            {"field_name": "hematuria", "label": "Hematuria", "fact_group": "radiotherapy", "target_result_type": "radiotherapy_summary", "field_type": "text"},
            {"field_name": "dysuria", "label": "Disuria", "fact_group": "radiotherapy", "target_result_type": "radiotherapy_summary", "field_type": "text"},
        ],
    }
    return templates.get(document_type, [])


class PatientDocumentPrivateStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or DEFAULT_PATIENT_DOCUMENT_ROOT)

    def store_upload(
        self,
        *,
        patient_id: int,
        file_name: str,
        content: bytes,
        mime_type: str = "",
    ) -> dict[str, Any]:
        suffix = Path(file_name).suffix.lower()
        if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
            raise ValueError("Tipo de archivo no soportado. Use PDF, imagen o texto.")

        sha256 = _sha256_bytes(content)
        document_key = f"p{patient_id}-{sha256[:16]}"
        patient_dir = self.root / f"patient_{patient_id}"
        patient_dir.mkdir(parents=True, exist_ok=True)

        storage_path = patient_dir / f"{sha256}{suffix}"
        if not storage_path.exists():
            storage_path.write_bytes(content)

        private_payload = self._build_private_payload(storage_path, file_name, mime_type or _guess_mime_type(file_name))
        index_path = patient_dir / f"{sha256}.json"
        index_path.write_text(json.dumps(private_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "document_key": document_key,
            "sha256": sha256,
            "storage_path": str(storage_path),
            "private_index_path": str(index_path),
            "mime_type": private_payload.get("mime_type", ""),
            "page_count": private_payload.get("page_count", 0),
            "preview_excerpt": private_payload.get("preview_excerpt", ""),
            "file_name": file_name,
            "metadata": {
                "file_size_bytes": len(content),
                "suffix": suffix,
            },
        }

    def get_private_payload(self, index_path: str) -> dict[str, Any]:
        path = Path(index_path)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def build_preview(self, index_path: str, max_chars: int = 1200) -> str:
        payload = self.get_private_payload(index_path)
        preview = str(payload.get("preview_excerpt") or "")
        if len(preview) > max_chars:
            return preview[:max_chars].rstrip() + "..."
        return preview

    def _build_private_payload(self, storage_path: Path, file_name: str, mime_type: str) -> dict[str, Any]:
        text_by_page: list[dict[str, Any]] = []
        all_text = ""
        page_count = 0
        suffix = storage_path.suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(str(storage_path))
            page_count = len(reader.pages)
            for page_number, page in enumerate(reader.pages, start=1):
                extracted = _normalize_text(page.extract_text() or "")
                if extracted:
                    text_by_page.append({"page": page_number, "text": extracted})
            all_text = "\n".join(item["text"] for item in text_by_page)
        elif suffix == ".txt":
            raw = storage_path.read_text(encoding="utf-8", errors="ignore")
            normalized = _normalize_text(raw)
            if normalized:
                text_by_page.append({"page": 1, "text": normalized})
                all_text = normalized
            page_count = 1
        else:
            page_count = 1

        return {
            "file_name": file_name,
            "mime_type": mime_type,
            "source_path": str(storage_path),
            "page_count": page_count,
            "preview_excerpt": all_text[:1800],
            "full_text_available": bool(all_text),
            "text_by_page": text_by_page,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }


def classify_document(
    *,
    file_name: str,
    private_payload: dict[str, Any],
    declared_type: str = "",
) -> dict[str, Any]:
    text = " ".join(item.get("text", "") for item in private_payload.get("text_by_page", []))
    lowered = f"{file_name} {text}".lower()
    if declared_type and declared_type not in {"auto", "infer", "detectar"}:
        document_type = declared_type
    elif any(token in lowered for token in ("gleason", "isup", "adenocarcinoma", "cilindro", "core", "cribriform", "intraductal")):
        document_type = "pathology_report"
    elif any(token in lowered for token in ("psa", "testosterona", "hemoglob", "creatinina", "ldh", "fosfatasa alcalina", "bilirrub", "ggt")):
        document_type = "laboratory_bundle"
    elif any(token in lowered for token in ("psma", "pet", "tomograf", "tac", "ct ", "gammagrama", "bone scan", "suv")):
        document_type = "imaging_report"
    elif any(token in lowered for token in ("brca", "hrr", "msi", "tmb", "decipher", "oncotype", "prolaris", "genomic")):
        document_type = "genomic_report"
    elif any(token in lowered for token in ("prostatectom", "margin", "pstage", "p t", "nerve-sparing", "ganglios resecados")):
        document_type = "surgery_summary"
    elif any(token in lowered for token in ("radioterapia", "fractions", "fracciones", "gy", "imrt", "sbrt", "vmat")):
        document_type = "radiotherapy_summary"
    else:
        document_type = "unclassified_clinical_report"

    return {
        "document_type": document_type,
        "document_type_label": DOCUMENT_TYPE_LABELS.get(document_type, document_type),
        "classification_status": "classified" if document_type != "unclassified_clinical_report" else "needs_review",
        "text_available": bool(text.strip()),
    }


def extract_candidates_for_document(
    *,
    document_type: str,
    file_name: str,
    private_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    text_pages = private_payload.get("text_by_page", []) or []
    full_text = "\n".join(item.get("text", "") for item in text_pages)
    if not full_text.strip():
        return []

    if document_type == "pathology_report":
        return _extract_pathology_candidates(full_text, text_pages)
    if document_type == "laboratory_bundle":
        return _extract_lab_candidates(full_text, text_pages)
    if document_type == "imaging_report":
        return _extract_imaging_candidates(full_text, text_pages, file_name=file_name)
    if document_type == "genomic_report":
        return _extract_genomic_candidates(full_text, text_pages)
    if document_type == "surgery_summary":
        return _extract_surgery_candidates(full_text, text_pages)
    if document_type == "radiotherapy_summary":
        return _extract_radiotherapy_candidates(full_text, text_pages)
    return []


def build_verification_task(
    *,
    document_key: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    pending_fields = [item.get("field_name", "") for item in candidates if item.get("field_name")]
    return VerificationTask(
        task_key=f"{document_key}:verify",
        task_status="ready_for_review" if candidates else "manual_review_required",
        summary={
            "candidate_count": len(candidates),
            "pending_fields": pending_fields[:8],
        },
        pending_fields=pending_fields,
    ).to_dict()


def build_verified_fact_bundle(
    *,
    verified_by: str,
    facts: list[dict[str, Any]],
    committed_result_types: list[str],
) -> dict[str, Any]:
    return VerifiedFactBundle(
        verified_by=verified_by,
        facts=facts,
        committed_result_types=committed_result_types,
        what_changed=[_change_label_for_result_type(item) for item in committed_result_types],
    ).to_dict()


def build_document_payload_from_facts(
    *,
    document_type: str,
    facts: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    fact_map = {item.get("field_name"): item.get("value") for item in facts if item.get("field_name")}
    fact_groups = {item.get("fact_group") for item in facts}
    result_type = next((item.get("target_result_type") for item in facts if item.get("target_result_type")), "")
    if not result_type:
        result_type = {
            "pathology_report": "pathology",
            "laboratory_bundle": "lab_panel",
            "imaging_report": "imaging",
            "genomic_report": "genomic",
            "surgery_summary": "surgery_summary",
            "radiotherapy_summary": "radiotherapy_summary",
        }.get(document_type, "")

    if result_type == "pathology":
        payload = {
            "biopsy_date": fact_map.get("biopsy_date"),
            "biopsy_type": fact_map.get("biopsy_type") or "Dirigida + sistemática",
            "biopsy_context": fact_map.get("biopsy_context") or "diagnostica",
            "total_cores": _safe_int(fact_map.get("total_cores")),
            "positive_cores": _safe_int(fact_map.get("positive_cores")),
            "gleason_primary": _safe_int(fact_map.get("gleason_primary")),
            "gleason_secondary": _safe_int(fact_map.get("gleason_secondary")),
            "isup_grade": _safe_int(fact_map.get("isup_grade")),
            "porcentaje_patron_4": _safe_float(fact_map.get("porcentaje_patron_4")),
            "patron_cribiforme": 1 if str(fact_map.get("patron_cribiforme")).lower() in {"1", "true", "si", "yes", "positivo", "presente"} else 0,
            "carcinoma_intraductal": 1 if str(fact_map.get("carcinoma_intraductal")).lower() in {"1", "true", "si", "yes", "positivo", "presente"} else 0,
            "adverse_histology_variant_type": fact_map.get("adverse_histology_variant_type"),
            "adverse_histology_variant_detail": fact_map.get("adverse_histology_variant_detail"),
            "pathologist_notes": fact_map.get("pathologist_notes"),
        }
        return result_type, {key: value for key, value in payload.items() if _is_present(value)}

    if result_type == "lab_panel":
        payload = {
            "visit_date": fact_map.get("visit_date"),
            "psa": _safe_float(fact_map.get("psa")),
            "testosterone": _safe_float(fact_map.get("testosterone")),
            "hemoglobin": _safe_float(fact_map.get("hemoglobin")),
            "creatinine": _safe_float(fact_map.get("creatinine")),
            "cystatin_c": _safe_float(fact_map.get("cystatin_c")),
            "ldh": _safe_float(fact_map.get("ldh")),
            "alp": _safe_float(fact_map.get("alp")),
            "bilirubin": _safe_float(fact_map.get("bilirubin")),
            "ast": _safe_float(fact_map.get("ast")),
            "alt": _safe_float(fact_map.get("alt")),
            "ggt": _safe_float(fact_map.get("ggt")),
            "glucose": _safe_float(fact_map.get("glucose")),
        }
        return result_type, {key: value for key, value in payload.items() if _is_present(value)}

    if result_type == "imaging":
        study_type = str(fact_map.get("study_type") or "").strip() or "PSMA-PET"
        locations = fact_map.get("lesion_locations") or []
        if isinstance(locations, str):
            locations = [item.strip() for item in locations.split(",") if item.strip()]
        suv = _safe_float(fact_map.get("psma_suv_max"))
        findings = {
            "lesion_locations": locations,
            "psma_total_lesions": _safe_int(fact_map.get("psma_total_lesions")),
            "psma_suv_bucket": fact_map.get("psma_suv_bucket") or _bucket_psma_suv(suv),
            "ct_summary": fact_map.get("ct_summary"),
            "ct_locations": locations,
            "bone_distribution": fact_map.get("bone_distribution"),
            "bone_lesion_count": _safe_int(fact_map.get("bone_lesion_count")),
            "psma_negative_dominant_lesions": str(fact_map.get("psma_negative_dominant_lesions")).lower() in {"1", "true", "si", "yes"},
        }
        payload = {
            "study_date": fact_map.get("study_date"),
            "study_type": study_type,
            "psma_result": fact_map.get("psma_result"),
            "psma_suv_max": suv,
            "bone_scan_result": fact_map.get("bone_scan_result"),
            "bone_lesion_count": _safe_int(fact_map.get("bone_lesion_count")),
            "findings": {key: value for key, value in findings.items() if _is_present(value)},
            "radiologist_notes": fact_map.get("radiologist_notes"),
        }
        return result_type, {key: value for key, value in payload.items() if _is_present(value)}

    if result_type == "genomic":
        actionable = fact_map.get("actionable_findings") or []
        if isinstance(actionable, str):
            actionable = [item.strip() for item in actionable.split(",") if item.strip()]
        payload = {
            "test_date": fact_map.get("test_date"),
            "test_type": fact_map.get("test_type"),
            "decipher_risk": fact_map.get("decipher_risk"),
            "gps_score": _safe_float(fact_map.get("gps_score")),
            "prolaris_score": _safe_float(fact_map.get("prolaris_score")),
            "brca2_status": fact_map.get("brca2_status"),
            "msi_status": fact_map.get("msi_status"),
            "hrr_overall": fact_map.get("hrr_overall"),
            "tmb_score": _safe_float(fact_map.get("tmb_score")),
            "actionable_findings": actionable,
        }
        return result_type, {key: value for key, value in payload.items() if _is_present(value)}

    if result_type == "surgery_summary":
        payload = {
            "surgery_date": fact_map.get("surgery_date"),
            "pathological_stage": fact_map.get("pathological_stage"),
            "pathological_gleason_primary": _safe_int(fact_map.get("pathological_gleason_primary")),
            "pathological_gleason_secondary": _safe_int(fact_map.get("pathological_gleason_secondary")),
            "pathological_isup": _safe_int(fact_map.get("pathological_isup")),
            "surgical_margin_status": 1 if str(fact_map.get("surgical_margin_status")).lower() in {"1", "true", "si", "yes", "positivo"} else 0,
            "margin_location": fact_map.get("margin_location"),
            "nodes_removed": _safe_int(fact_map.get("nodes_removed")),
            "nodes_positive": _safe_int(fact_map.get("nodes_positive")),
            "surgical_approach": fact_map.get("surgical_approach"),
            "continence_status": fact_map.get("continence_status"),
            "potency_status": fact_map.get("potency_status"),
            "recovery_notes": fact_map.get("recovery_notes"),
        }
        return result_type, {key: value for key, value in payload.items() if _is_present(value)}

    if result_type == "radiotherapy_summary":
        late_toxicity = {}
        for key in ("hematuria", "dysuria", "anemia_related"):
            if _is_present(fact_map.get(key)):
                late_toxicity[key] = fact_map.get(key)
        payload = {
            "rt_date": fact_map.get("rt_date"),
            "rt_context": fact_map.get("rt_context"),
            "rt_technique": fact_map.get("rt_technique"),
            "target": fact_map.get("target"),
            "total_dose_gy": _safe_float(fact_map.get("total_dose_gy")),
            "fractions": _safe_int(fact_map.get("fractions")),
            "dose_per_fraction_gy": _safe_float(fact_map.get("dose_per_fraction_gy")),
            "session_duration_minutes": _safe_int(fact_map.get("session_duration_minutes")),
            "total_duration_days": _safe_int(fact_map.get("total_duration_days")),
            "hematuria": fact_map.get("hematuria"),
            "dysuria": fact_map.get("dysuria"),
            "anemia_related": fact_map.get("anemia_related"),
            "notes": fact_map.get("notes"),
            "late_toxicity_json": late_toxicity,
        }
        return result_type, {key: value for key, value in payload.items() if _is_present(value)}

    if fact_groups == {"lab_panel"}:
        return "lab_panel", fact_map
    return result_type, fact_map


def document_label(document_type: str) -> str:
    return DOCUMENT_TYPE_LABELS.get(document_type, document_type)


def _change_label_for_result_type(result_type: str) -> str:
    return {
        "pathology": "Se actualizó histología verificada y se revaluó la etapa clínica.",
        "lab_panel": "Se actualizaron laboratorios longitudinales y la agenda clínica.",
        "imaging": "Se estructuró imagen verificable y se recalcularon checkpoints terapéuticos.",
        "genomic": "Se actualizó el perfil molecular verificable para decisiones dirigidas por biomarcadores.",
        "surgery_summary": "Se persistió el resumen quirúrgico y su contexto patológico.",
        "radiotherapy_summary": "Se persistió el resumen de radioterapia con dosis y toxicidad.",
    }.get(result_type, f"Se verificó un documento clínico de tipo {result_type}.")


def _candidate(
    *,
    field_name: str,
    fact_group: str,
    value: Any,
    target_result_type: str,
    confidence: float,
    evidence_excerpt: str = "",
    page_ref: str = "",
    extraction_method: str = "regex_heuristic",
) -> dict[str, Any]:
    return DocumentExtractionCandidate(
        candidate_key=f"{fact_group}:{field_name}",
        field_name=field_name,
        fact_group=fact_group,
        value=value,
        value_display=_value_display(value),
        target_result_type=target_result_type,
        confidence=confidence,
        extraction_method=extraction_method,
        evidence_excerpt=evidence_excerpt,
        page_ref=page_ref,
    ).to_dict()


def _find_excerpt(text_pages: list[dict[str, Any]], pattern: str) -> tuple[str, str]:
    regex = re.compile(pattern, re.IGNORECASE)
    for item in text_pages:
        match = regex.search(item.get("text", ""))
        if not match:
            continue
        text = item.get("text", "")
        start = max(match.start() - 60, 0)
        end = min(match.end() + 120, len(text))
        return text[start:end].strip(), f"p.{item.get('page')}"
    return "", ""


def _extract_number(text: str, labels: list[str]) -> float | None:
    for label in labels:
        match = re.search(rf"{label}\s*[:=]?\s*(-?\d+(?:[\.,]\d+)?)", text, re.IGNORECASE)
        if match:
            return _safe_float(match.group(1).replace(",", "."))
    return None


def _extract_pathology_candidates(text: str, text_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    gleason_match = re.search(r"gleason(?:\s+score)?\s*[:=]?\s*(\d)\s*\+\s*(\d)", text, re.IGNORECASE)
    if gleason_match:
        excerpt, page_ref = _find_excerpt(text_pages, r"gleason(?:\s+score)?")
        candidates.extend(
            [
                _candidate(field_name="gleason_primary", fact_group="pathology", value=int(gleason_match.group(1)), target_result_type="pathology", confidence=0.94, evidence_excerpt=excerpt, page_ref=page_ref),
                _candidate(field_name="gleason_secondary", fact_group="pathology", value=int(gleason_match.group(2)), target_result_type="pathology", confidence=0.94, evidence_excerpt=excerpt, page_ref=page_ref),
            ]
        )
    isup_match = re.search(r"(?:isup|grade group|grupo de grado)\s*[:=]?\s*(\d)", text, re.IGNORECASE)
    if isup_match:
        excerpt, page_ref = _find_excerpt(text_pages, r"(?:isup|grade group|grupo de grado)")
        candidates.append(_candidate(field_name="isup_grade", fact_group="pathology", value=int(isup_match.group(1)), target_result_type="pathology", confidence=0.92, evidence_excerpt=excerpt, page_ref=page_ref))
    cores_match = re.search(r"(\d+)\s*(?:/|de)\s*(\d+)\s*(?:cores|cilindros)", text, re.IGNORECASE)
    if cores_match:
        excerpt, page_ref = _find_excerpt(text_pages, r"(?:cores|cilindros)")
        candidates.extend(
            [
                _candidate(field_name="positive_cores", fact_group="pathology", value=int(cores_match.group(1)), target_result_type="pathology", confidence=0.88, evidence_excerpt=excerpt, page_ref=page_ref),
                _candidate(field_name="total_cores", fact_group="pathology", value=int(cores_match.group(2)), target_result_type="pathology", confidence=0.88, evidence_excerpt=excerpt, page_ref=page_ref),
            ]
        )
    pattern4 = _extract_number(text, [r"patr[oó]n\s*4", r"pattern\s*4"])
    if pattern4 is not None:
        excerpt, page_ref = _find_excerpt(text_pages, r"(?:patr[oó]n|pattern)\s*4")
        candidates.append(_candidate(field_name="porcentaje_patron_4", fact_group="pathology", value=pattern4, target_result_type="pathology", confidence=0.82, evidence_excerpt=excerpt, page_ref=page_ref))
    lower = text.lower()
    if "cribriform" in lower:
        excerpt, page_ref = _find_excerpt(text_pages, r"cribriform")
        candidates.append(_candidate(field_name="patron_cribiforme", fact_group="pathology", value=True, target_result_type="pathology", confidence=0.9, evidence_excerpt=excerpt, page_ref=page_ref))
    if "intraduct" in lower:
        excerpt, page_ref = _find_excerpt(text_pages, r"intraduct")
        candidates.append(_candidate(field_name="carcinoma_intraductal", fact_group="pathology", value=True, target_result_type="pathology", confidence=0.9, evidence_excerpt=excerpt, page_ref=page_ref))
    for keyword, variant in (
        ("ductal", "ductal_predominant"),
        ("sarcomatoid", "sarcomatoid"),
        ("signet ring", "signet_ring"),
        ("adenosquamous", "adenosquamous_or_squamous"),
        ("squamous", "adenosquamous_or_squamous"),
        ("basal cell", "basal_cell"),
        ("mucinous", "mucinous_colloid"),
        ("small cell", "small_cell_neuroendocrine"),
        ("neuroendocrine", "small_cell_neuroendocrine"),
    ):
        if keyword in lower:
            excerpt, page_ref = _find_excerpt(text_pages, keyword)
            candidates.append(_candidate(field_name="adverse_histology_variant_type", fact_group="pathology", value=variant, target_result_type="pathology", confidence=0.85, evidence_excerpt=excerpt, page_ref=page_ref))
            break
    return candidates


def _extract_lab_candidates(text: str, text_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    label_map = {
        "psa": [r"psa", r"ant[ií]geno prost[aá]tico"],
        "testosterone": [r"testosterona", r"testosterone"],
        "hemoglobin": [r"hemoglobina", r"hemoglobin"],
        "creatinine": [r"creatinina", r"creatinine"],
        "cystatin_c": [r"cistatina\s*c", r"cystatin\s*c"],
        "ldh": [r"ldh"],
        "alp": [r"fosfatasa alcalina", r"\balp\b"],
        "ast": [r"\bast\b", r"tgo"],
        "alt": [r"\balt\b", r"tgp"],
        "ggt": [r"\bggt\b"],
        "bilirubin": [r"bilirrubina", r"bilirubin"],
        "glucose": [r"glucosa", r"glucose"],
    }
    candidates: list[dict[str, Any]] = []
    for field_name, labels in label_map.items():
        value = _extract_number(text, labels)
        if value is None:
            continue
        excerpt, page_ref = _find_excerpt(text_pages, labels[0])
        candidates.append(_candidate(field_name=field_name, fact_group="lab_panel", value=value, target_result_type="lab_panel", confidence=0.83, evidence_excerpt=excerpt, page_ref=page_ref))
    return candidates


def _extract_imaging_candidates(text: str, text_pages: list[dict[str, Any]], *, file_name: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    lowered = f"{file_name} {text}".lower()
    study_type = "PSMA-PET" if "psma" in lowered else "Gammagrama" if any(token in lowered for token in ("gammagrama", "bone scan")) else "TAC" if any(token in lowered for token in ("tomograf", "tac", " ct ")) else "Imagen"
    candidates.append(_candidate(field_name="study_type", fact_group="imaging", value=study_type, target_result_type="imaging", confidence=0.75))
    if study_type == "PSMA-PET":
        positive = any(token in lowered for token in ("captación patológica", "psma positivo", "positivo", "avid"))
        candidates.append(_candidate(field_name="psma_result", fact_group="imaging", value="positivo" if positive else "negativo", target_result_type="imaging", confidence=0.72))
        suv = _extract_number(text, [r"suv\s*max", r"\bsuv\b"])
        if suv is not None:
            excerpt, page_ref = _find_excerpt(text_pages, r"suv")
            candidates.append(_candidate(field_name="psma_suv_max", fact_group="imaging", value=suv, target_result_type="imaging", confidence=0.88, evidence_excerpt=excerpt, page_ref=page_ref))
            candidates.append(_candidate(field_name="psma_suv_bucket", fact_group="imaging", value=_bucket_psma_suv(suv), target_result_type="imaging", confidence=0.99, evidence_excerpt=excerpt, page_ref=page_ref, extraction_method="derived_bucket"))
        locations = [location for location in LOCATION_OPTIONS if location.lower().split()[0] in lowered]
        if locations:
            candidates.append(_candidate(field_name="lesion_locations", fact_group="imaging", value=locations, target_result_type="imaging", confidence=0.7))
            candidates.append(_candidate(field_name="psma_total_lesions", fact_group="imaging", value=len(locations), target_result_type="imaging", confidence=0.6, extraction_method="location_count"))
    elif study_type == "Gammagrama":
        bone_count = _safe_int(_extract_number(text, [r"lesiones", r"focos"]))
        if bone_count is not None:
            excerpt, page_ref = _find_excerpt(text_pages, r"(?:lesiones|focos)")
            candidates.append(_candidate(field_name="bone_lesion_count", fact_group="imaging", value=bone_count, target_result_type="imaging", confidence=0.78, evidence_excerpt=excerpt, page_ref=page_ref))
        candidates.append(_candidate(field_name="bone_scan_result", fact_group="imaging", value="positivo" if any(token in lowered for token in ("positivo", "metast", "captación")) else "negativo", target_result_type="imaging", confidence=0.7))
    elif study_type == "TAC":
        summary = "Metástasis" if any(token in lowered for token in ("metástasis", "metastasis", "lesiones sospechosas")) else "Sin lesiones sospechosas"
        candidates.append(_candidate(field_name="ct_summary", fact_group="imaging", value=summary, target_result_type="imaging", confidence=0.72))
        locations = [location for location in LOCATION_OPTIONS if location.lower().split()[0] in lowered]
        if locations:
            candidates.append(_candidate(field_name="lesion_locations", fact_group="imaging", value=locations, target_result_type="imaging", confidence=0.68))
    return candidates


def _extract_genomic_candidates(text: str, text_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    lowered = text.lower()
    if "decipher" in lowered:
        candidates.append(_candidate(field_name="test_type", fact_group="genomic", value="Decipher", target_result_type="genomic", confidence=0.82))
        for risk in ("low", "intermediate", "high", "bajo", "intermedio", "alto"):
            if risk in lowered:
                excerpt, page_ref = _find_excerpt(text_pages, risk)
                candidates.append(_candidate(field_name="decipher_risk", fact_group="genomic", value=risk, target_result_type="genomic", confidence=0.78, evidence_excerpt=excerpt, page_ref=page_ref))
                break
    if "oncotype" in lowered:
        candidates.append(_candidate(field_name="test_type", fact_group="genomic", value="OncotypeDX_GPS", target_result_type="genomic", confidence=0.8))
    if "prolaris" in lowered:
        candidates.append(_candidate(field_name="test_type", fact_group="genomic", value="Prolaris", target_result_type="genomic", confidence=0.8))
    for gene in ("brca2", "brca1", "atm", "palb2", "chek2", "cdk12"):
        if gene in lowered:
            excerpt, page_ref = _find_excerpt(text_pages, gene)
            status = "positivo" if any(token in lowered for token in (f"{gene} mut", f"{gene} pathogenic", f"{gene} deleter")) else "documentado"
            candidates.append(_candidate(field_name=f"{gene}_status", fact_group="genomic", value=status, target_result_type="genomic", confidence=0.76, evidence_excerpt=excerpt, page_ref=page_ref))
    if any(token in lowered for token in ("hrr", "homologous recombination")):
        candidates.append(_candidate(field_name="hrr_overall", fact_group="genomic", value="positivo" if "positive" in lowered or "mut" in lowered else "documentado", target_result_type="genomic", confidence=0.72))
    if "msi" in lowered:
        candidates.append(_candidate(field_name="msi_status", fact_group="genomic", value="MSI-H" if "high" in lowered or "msi-h" in lowered else "estable", target_result_type="genomic", confidence=0.73))
    tmb = _extract_number(text, [r"tmb"])
    if tmb is not None:
        excerpt, page_ref = _find_excerpt(text_pages, r"tmb")
        candidates.append(_candidate(field_name="tmb_score", fact_group="genomic", value=tmb, target_result_type="genomic", confidence=0.76, evidence_excerpt=excerpt, page_ref=page_ref))
    return candidates


def _extract_surgery_candidates(text: str, text_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    pstage_match = re.search(r"\bp?t?([0-4][a-c]?)\b", text, re.IGNORECASE)
    if pstage_match:
        excerpt, page_ref = _find_excerpt(text_pages, r"\bp?t?[0-4]")
        candidates.append(_candidate(field_name="pathological_stage", fact_group="surgery", value=f"pT{pstage_match.group(1).upper()}", target_result_type="surgery_summary", confidence=0.78, evidence_excerpt=excerpt, page_ref=page_ref))
    if "margin" in text.lower() or "margen" in text.lower():
        excerpt, page_ref = _find_excerpt(text_pages, r"(?:margin|margen)")
        positive = any(token in text.lower() for token in ("positive margin", "margen positivo", "focalmente positivo"))
        candidates.append(_candidate(field_name="surgical_margin_status", fact_group="surgery", value=positive, target_result_type="surgery_summary", confidence=0.74, evidence_excerpt=excerpt, page_ref=page_ref))
    nodes_removed = _extract_number(text, [r"ganglios resecados", r"nodes removed"])
    nodes_positive = _extract_number(text, [r"ganglios positivos", r"positive nodes"])
    if nodes_removed is not None:
        candidates.append(_candidate(field_name="nodes_removed", fact_group="surgery", value=int(nodes_removed), target_result_type="surgery_summary", confidence=0.75))
    if nodes_positive is not None:
        candidates.append(_candidate(field_name="nodes_positive", fact_group="surgery", value=int(nodes_positive), target_result_type="surgery_summary", confidence=0.75))
    return candidates


def _extract_radiotherapy_candidates(text: str, text_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    lowered = text.lower()
    if "sbrt" in lowered:
        candidates.append(_candidate(field_name="rt_technique", fact_group="radiotherapy", value="SBRT", target_result_type="radiotherapy_summary", confidence=0.82))
    elif "vmat" in lowered:
        candidates.append(_candidate(field_name="rt_technique", fact_group="radiotherapy", value="VMAT", target_result_type="radiotherapy_summary", confidence=0.82))
    elif "imrt" in lowered:
        candidates.append(_candidate(field_name="rt_technique", fact_group="radiotherapy", value="IMRT", target_result_type="radiotherapy_summary", confidence=0.82))
    dose = _extract_number(text, [r"dosis total", r"\bgy\b"])
    if dose is not None:
        excerpt, page_ref = _find_excerpt(text_pages, r"(?:dosis total|\bgy\b)")
        candidates.append(_candidate(field_name="total_dose_gy", fact_group="radiotherapy", value=dose, target_result_type="radiotherapy_summary", confidence=0.78, evidence_excerpt=excerpt, page_ref=page_ref))
    fractions = _extract_number(text, [r"fracciones", r"fractions"])
    if fractions is not None:
        excerpt, page_ref = _find_excerpt(text_pages, r"(?:fracciones|fractions)")
        candidates.append(_candidate(field_name="fractions", fact_group="radiotherapy", value=int(fractions), target_result_type="radiotherapy_summary", confidence=0.8, evidence_excerpt=excerpt, page_ref=page_ref))
    for symptom, field_name in (("hematuria", "hematuria"), ("disuria", "dysuria"), ("anemia", "anemia_related")):
        if symptom in lowered:
            excerpt, page_ref = _find_excerpt(text_pages, symptom)
            candidates.append(_candidate(field_name=field_name, fact_group="radiotherapy", value="documentada", target_result_type="radiotherapy_summary", confidence=0.64, evidence_excerpt=excerpt, page_ref=page_ref))
    return candidates


def serialize_verified_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized = []
    for fact in facts:
        serialized.append(
            VerifiedFact(
                field_name=fact.get("field_name", ""),
                fact_group=fact.get("fact_group", ""),
                value=fact.get("value"),
                value_display=fact.get("value_display", _value_display(fact.get("value"))),
                target_result_type=fact.get("target_result_type", ""),
                source_date=fact.get("source_date", ""),
                status=fact.get("status", "verified"),
                correction_note=fact.get("correction_note", ""),
                verified_by=fact.get("verified_by", ""),
            ).to_dict()
        )
    return serialized


def get_manual_template(document_type: str) -> list[dict[str, Any]]:
    return _manual_template(document_type)
