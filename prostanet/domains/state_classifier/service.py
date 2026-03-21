from __future__ import annotations

from prostanet.shared.metastatic_profile import derive_legacy_metastasis, derive_mhspc_volume_context


class StateClassifierService:
    def classify(self, payload: dict) -> dict:
        known_cancer_diagnosis = self._is_true(payload.get("known_cancer_diagnosis", 1))
        prior_negative_biopsy = self._is_true(payload.get("prior_negative_biopsy"))
        metastasis_site, metastasis_count, m_substage = derive_legacy_metastasis(payload)
        systemic_progression_context = str(payload.get("systemic_progression_context", "none") or "none")
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
            volume_disease = str(payload.get("volume_disease") or derive_mhspc_volume_context(payload) or "low").lower()
        castration_resistant = (
            legacy_crpc_signal
            or systemic_progression_context == "confirmed_crpc"
            or int(float(payload.get("line_of_therapy", 1) or 1)) > 1
        )
        legacy_crpc_shortcut = self._use_legacy_crpc_shortcut(
            payload,
            legacy_crpc_signal=legacy_crpc_signal,
        )
        on_adt = current_adt_context != "none"

        metastatic = metastasis_site.upper() not in {"M0", "", "NONE", "NO"}
        requires_adt_verification = self._requires_adt_verification(
            systemic_progression_context=systemic_progression_context,
            on_adt=on_adt,
            castrate_status=castrate_status,
            progression_pattern=progression_pattern,
            prior_prostatectomy=prior_prostatectomy,
            prior_radiation=prior_radiation,
        )

        if not known_cancer_diagnosis:
            if prior_negative_biopsy:
                module = "post_negative_biopsy_followup"
            else:
                module = "diagnostic_workup"
        elif requires_adt_verification and not legacy_crpc_shortcut:
            module = "adt_progression_verification"
        elif castration_resistant:
            if legacy_crpc_shortcut:
                module = "m1_crpc" if metastatic else "m0_crpc"
            elif castrate_status != "confirmed_castrate":
                module = "adt_progression_verification"
            elif conventional_imaging_status == "M1":
                module = "m1_crpc"
            elif conventional_imaging_status == "M0":
                module = "m0_crpc"
            elif systemic_progression_context == "confirmed_crpc":
                module = "adt_progression_verification"
            elif metastatic:
                module = "m1_crpc"
            else:
                module = "m0_crpc"
        elif metastatic:
            if metachronous and metastasis_count <= 5:
                module = "mcspc_oligo_metachronous"
            elif volume_disease == "high" or metastasis_count >= 4 or metastasis_site.lower() == "visceral" or m_substage == "M1c":
                module = "mcspc_high_volume_metachronous" if metachronous else "mcspc_high_volume_sync"
            else:
                module = "mcspc_low_volume_sync_oligo"
        elif bcr2 or ((prior_prostatectomy or prior_radiation) and self._has_recurrence_signal(payload)):
            module = "recurrence_bcr"
        elif prior_prostatectomy:
            module = "post_prostatectomy"
        else:
            module = "localized_initial"

        return {
            "state": module,
            "classification_reason": self._reason_for(module),
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
    def _reason_for(module: str) -> str:
        reasons = {
            "diagnostic_workup": "No existe confirmación histológica previa y se requiere un estudio diagnóstico estructurado antes de entrar a una ruta terapéutica.",
            "post_negative_biopsy_followup": "Existe una biopsia prostática benigna previa sin diagnóstico confirmado de cáncer y debe priorizarse seguimiento de baja intensidad o reactivación diagnóstica según la nueva sospecha.",
            "localized_initial": "No se detectaron tratamientos locales previos ni marcadores de enfermedad avanzada.",
            "post_prostatectomy": "Se detectó prostatectomía radical previa sin criterios que desplacen el caso a recurrencia.",
            "recurrence_bcr": "Se detectaron marcadores de recurrencia o de segunda recurrencia bioquímica después de tratamiento local.",
            "mcspc_oligo_metachronous": "Se detectó enfermedad metastásica sensible a la castración, oligometastásica y metacrónica.",
            "mcspc_low_volume_sync_oligo": "Se detectó enfermedad metastásica sensible a la castración con patrón de bajo volumen u oligometastásico sincrónico.",
            "mcspc_high_volume_sync": "Se detectó enfermedad metastásica sensible a la castración de alto volumen sincrónica / de novo.",
            "mcspc_high_volume_metachronous": "Se detectó enfermedad metastásica sensible a la castración de alto volumen metacrónica.",
            "mcspc_high_volume": "Se detectó enfermedad metastásica sensible a la castración de alto volumen.",
            "adt_progression_verification": "Se detectó progresión bajo terapia de privación androgénica o una etiqueta de CRPC sin castración confirmada, por lo que primero debe verificarse testosterona en rango de castración y reestadificación convencional.",
            "m0_crpc": "Se detectó enfermedad resistente a la castración sin metástasis.",
            "m1_crpc": "Se detectó enfermedad resistente a la castración con metástasis.",
        }
        return reasons.get(module, "El módulo fue seleccionado por el clasificador de estado clínico.")

    @staticmethod
    def _normalize_castrate_status(payload: dict) -> str:
        explicit = str(payload.get("castrate_testosterone_status", "unknown") or "unknown")
        if explicit in {"confirmed_castrate", "not_castrate", "unknown"}:
            return explicit
        if StateClassifierService._is_true(payload.get("castrate_testosterone_confirmed")):
            return "confirmed_castrate"
        testosterone_value = payload.get("testosterone_value")
        if testosterone_value not in (None, ""):
            try:
                return "confirmed_castrate" if float(testosterone_value) <= 50 else "not_castrate"
            except (TypeError, ValueError):
                return "unknown"
        return "unknown"

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
    def _requires_adt_verification(
        *,
        systemic_progression_context: str,
        on_adt: bool,
        castrate_status: str,
        progression_pattern: str,
        prior_prostatectomy: bool,
        prior_radiation: bool,
    ) -> bool:
        if systemic_progression_context == "progression_on_adt_verify_castration":
            return True
        if systemic_progression_context == "confirmed_crpc" and castrate_status != "confirmed_castrate":
            return True
        if on_adt and castrate_status != "confirmed_castrate" and progression_pattern in {"biochemical_only", "radiographic", "clinical", "mixed"}:
            return True
        if (prior_prostatectomy or prior_radiation) and on_adt and castrate_status != "confirmed_castrate":
            return True
        return False
