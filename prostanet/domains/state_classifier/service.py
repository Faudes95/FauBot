from __future__ import annotations

from prostanet.shared.metastatic_profile import (
    derive_legacy_metastasis,
    derive_mhspc_burden_context,
)
from prostanet.shared.systemic_progression import (
    build_progression_gate,
    normalize_castrate_status,
    resolve_systemic_progression_context,
)


MHSPC_STATES = {
    "mcspc_oligo_metachronous",
    "mcspc_low_volume_sync_oligo",
    "mcspc_high_volume_sync",
    "mcspc_high_volume_metachronous",
    "mcspc_high_volume",
}


class StateClassifierService:
    def classify(self, payload: dict) -> dict:
        burden_context = derive_mhspc_burden_context(payload)
        known_cancer_diagnosis = self._is_true(payload.get("known_cancer_diagnosis", 1))
        prior_negative_biopsy = self._is_true(payload.get("prior_negative_biopsy"))
        metastasis_site, metastasis_count, m_substage = derive_legacy_metastasis(payload)
        systemic_progression_context = str(payload.get("systemic_progression_context", "") or "")
        current_adt_context = str(payload.get("current_adt_context", "none") or "none")
        castrate_status = self._normalize_castrate_status(payload)
        progression_pattern = str(payload.get("progression_pattern", "biochemical_only") or "biochemical_only")
        conventional_imaging_status = str(payload.get("conventional_imaging_status", "not_restaged") or "not_restaged").upper()
        legacy_crpc_signal = self._is_true(payload.get("castration_resistant"))
        if not known_cancer_diagnosis:
            metastasis_site = "M0"
            metastasis_count = 0
            prior_prostatectomy = False
            prior_radiation = False
            bcr2 = False
            metachronous = False
            volume_disease = "low"
            burden_context = {
                **burden_context,
                "volume_disease": "low",
                "volume_reason": "",
                "oligometastatic_operational": False,
            }
            systemic_progression_context = "none"
            current_adt_context = "none"
            castrate_status = "unknown"
            progression_pattern = "biochemical_only"
            conventional_imaging_status = "NOT_RESTAGED"
            legacy_crpc_signal = False
        else:
            prior_prostatectomy = self._is_true(payload.get("prior_prostatectomy"))
            prior_radiation = self._is_true(payload.get("prior_radiation"))
            bcr2 = self._is_true(payload.get("bcr2"))
            metachronous = self._is_true(payload.get("metachronous_metastasis"))
            volume_disease = str(burden_context.get("volume_disease") or "low").lower()
        systemic_progression_context_resolved = resolve_systemic_progression_context(
            systemic_progression_context,
            legacy_crpc_signal=legacy_crpc_signal,
            line_of_therapy=payload.get("line_of_therapy"),
        )
        castration_resistant = systemic_progression_context_resolved == "confirmed_crpc"
        legacy_crpc_shortcut = self._use_legacy_crpc_shortcut(
            payload,
            legacy_crpc_signal=legacy_crpc_signal,
        )
        on_adt = current_adt_context != "none"

        metastatic = (
            burden_context.get("metastasis_count", 0) not in (None, 0)
            or str(burden_context.get("m_substage_resolved") or m_substage).upper() not in {"", "M0"}
            or metastasis_site.upper() not in {"M0", "", "NONE", "NO"}
        )
        phenotype_state = self._resolve_phenotype_state(
            known_cancer_diagnosis=known_cancer_diagnosis,
            prior_negative_biopsy=prior_negative_biopsy,
            prior_prostatectomy=prior_prostatectomy,
            prior_radiation=prior_radiation,
            bcr2=bcr2,
            castration_resistant=castration_resistant,
            castrate_status=castrate_status,
            conventional_imaging_status=conventional_imaging_status,
            metastatic=metastatic,
            metachronous=metachronous,
            burden_context=burden_context,
            metastasis_count=metastasis_count,
            legacy_crpc_shortcut=legacy_crpc_shortcut,
            payload=payload,
        )
        progression_gate = build_progression_gate(
            systemic_progression_context=systemic_progression_context_resolved,
            on_adt=on_adt,
            castrate_status=castrate_status,
            progression_pattern=progression_pattern,
            prior_prostatectomy=prior_prostatectomy,
            prior_radiation=prior_radiation,
            phenotype_state=phenotype_state if phenotype_state in MHSPC_STATES else "",
        )

        if not known_cancer_diagnosis:
            module = phenotype_state
        elif progression_gate.get("progression_gate_active") and phenotype_state in MHSPC_STATES:
            module = phenotype_state
        elif progression_gate.get("progression_gate_active") and not legacy_crpc_shortcut:
            module = "adt_progression_verification"
        else:
            module = phenotype_state

        return {
            "state": module,
            "classification_reason": self._reason_for(
                module,
                burden_context=burden_context,
                metachronous=metachronous,
                progression_gate=progression_gate,
                phenotype_state=phenotype_state,
            ),
            "derived_metastatic_context": burden_context,
            "phenotype_state": phenotype_state,
            **progression_gate,
        }

    @staticmethod
    def _is_true(value) -> bool:
        return str(value).lower() in {"1", "true", "yes", "si", "on"}

    @staticmethod
    def _has_recurrence_signal(payload: dict) -> bool:
        psa_current = float(payload.get("psa_current", payload.get("psa", 0)) or 0)
        psa_postop = float(payload.get("psa_postop", 0) or 0)
        phoenix = float(payload.get("phoenix_delta", 0) or 0)
        return psa_postop > 0.1 or psa_current > 0.1 or phoenix >= 2.0

    @staticmethod
    def _reason_for(
        module: str,
        *,
        burden_context: dict | None = None,
        metachronous: bool = False,
        progression_gate: dict[str, object] | None = None,
        phenotype_state: str = "",
    ) -> str:
        burden_context = burden_context or {}
        progression_gate = progression_gate or {}
        volume_reason = str(burden_context.get("volume_reason") or "").strip()
        reasons = {
            "diagnostic_workup": "No existe confirmación histológica previa y se requiere un estudio diagnóstico estructurado antes de entrar a una ruta terapéutica.",
            "post_negative_biopsy_followup": "Existe una biopsia prostática benigna previa sin diagnóstico confirmado de cáncer y debe priorizarse seguimiento de baja intensidad o reactivación diagnóstica según la nueva sospecha.",
            "localized_initial": "No se detectaron tratamientos locales previos ni marcadores de enfermedad avanzada.",
            "post_prostatectomy": "Se detectó prostatectomía radical previa sin criterios que desplacen el caso a recurrencia.",
            "recurrence_bcr": "Se detectaron marcadores de recurrencia o de segunda recurrencia bioquímica después de tratamiento local.",
            "post_radiotherapy_or_local_salvage": "Se detectó radioterapia previa con señal de recurrencia; debe separarse la ruta post-RT para confirmar Phoenix, restadificar y priorizar salvage local, MDT o redirección sistémica.",
            "mcspc_oligo_metachronous": f"Se detectó enfermedad metastásica sensible a la castración, oligometastásica y metacrónica. {volume_reason}".strip(),
            "mcspc_low_volume_sync_oligo": f"Se detectó enfermedad metastásica sensible a la castración con patrón de bajo volumen u oligometastásico sincrónico. {volume_reason}".strip(),
            "mcspc_high_volume_sync": f"Se detectó enfermedad metastásica sensible a la castración de alto volumen sincrónica / de novo. {volume_reason}".strip(),
            "mcspc_high_volume_metachronous": f"Se detectó enfermedad metastásica sensible a la castración de alto volumen metacrónica. {volume_reason}".strip(),
            "mcspc_high_volume": f"Se detectó enfermedad metastásica sensible a la castración de alto volumen. {volume_reason}".strip(),
            "adt_progression_verification": "Se detectó progresión bajo terapia de privación androgénica o una etiqueta de CRPC sin castración confirmada, por lo que primero debe verificarse testosterona en rango de castración y reestadificación convencional.",
            "m0_crpc": "Se detectó enfermedad resistente a la castración sin metástasis.",
            "m1_crpc": "Se detectó enfermedad resistente a la castración con metástasis.",
        }
        reason = reasons.get(module, "El módulo fue seleccionado por el clasificador de estado clínico.")
        if module == "mcspc_low_volume_sync_oligo" and not metachronous and burden_context.get("oligometastatic_operational"):
            reason = f"{reason} Patrón operativo oligometastásico sincrónico (<=5 lesiones sin criterio de alto volumen).".strip()
        if progression_gate.get("progression_gate_active"):
            gate_reason = str(progression_gate.get("progression_gate_reason") or "").strip()
            if gate_reason and module == phenotype_state and module in MHSPC_STATES:
                return f"{reason} {gate_reason}".strip()
        return reason

    @staticmethod
    def _normalize_castrate_status(payload: dict) -> str:
        return normalize_castrate_status(
            payload.get("castrate_testosterone_status", "unknown"),
            testosterone_value=payload.get("testosterone_value"),
            castrate_confirmed_flag=payload.get("castrate_testosterone_confirmed"),
        )

    @staticmethod
    def _use_legacy_crpc_shortcut(payload: dict, *, legacy_crpc_signal: bool) -> bool:
        if not legacy_crpc_signal:
            return False
        explicit_progression_context = str(payload.get("systemic_progression_context", "") or "").strip()
        explicit_castrate_status = str(payload.get("castrate_testosterone_status", "") or "").strip()
        explicit_testosterone_value = payload.get("testosterone_value")
        explicit_conventional_imaging = str(payload.get("conventional_imaging_status", "") or "").strip()
        explicit_adt_context = str(payload.get("current_adt_context", "") or "").strip()
        explicit_castration_confirmation = payload.get("castrate_testosterone_confirmed")
        if explicit_progression_context:
            return False
        if explicit_castrate_status:
            return False
        if explicit_testosterone_value not in (None, ""):
            return False
        if explicit_conventional_imaging:
            return False
        if explicit_adt_context:
            return False
        if explicit_castration_confirmation not in (None, ""):
            return False
        return True

    @staticmethod
    def _resolve_phenotype_state(
        *,
        known_cancer_diagnosis: bool,
        prior_negative_biopsy: bool,
        prior_prostatectomy: bool,
        prior_radiation: bool,
        bcr2: bool,
        castration_resistant: bool,
        castrate_status: str,
        conventional_imaging_status: str,
        metastatic: bool,
        metachronous: bool,
        burden_context: dict,
        metastasis_count: int,
        legacy_crpc_shortcut: bool,
        payload: dict,
    ) -> str:
        if not known_cancer_diagnosis:
            return "post_negative_biopsy_followup" if prior_negative_biopsy else "diagnostic_workup"
        if castration_resistant and (legacy_crpc_shortcut or castrate_status == "confirmed_castrate"):
            if legacy_crpc_shortcut:
                return "m1_crpc" if metastatic else "m0_crpc"
            if conventional_imaging_status == "M1" or metastatic:
                return "m1_crpc"
            if conventional_imaging_status == "M0":
                return "m0_crpc"
        if metastatic:
            volume_disease = str(burden_context.get("volume_disease") or "low").lower()
            if volume_disease == "high":
                return "mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"
            if metachronous and burden_context.get("oligometastatic_operational"):
                return "mcspc_oligo_metachronous"
            if metachronous and metastasis_count and metastasis_count <= 5:
                return "mcspc_oligo_metachronous"
            return "mcspc_low_volume_sync_oligo"
        if prior_radiation and not prior_prostatectomy and StateClassifierService._has_recurrence_signal(payload):
            return "post_radiotherapy_or_local_salvage"
        if bcr2 or (prior_prostatectomy and StateClassifierService._has_recurrence_signal(payload)):
            return "recurrence_bcr"
        if prior_prostatectomy:
            return "post_prostatectomy"
        return "localized_initial"
