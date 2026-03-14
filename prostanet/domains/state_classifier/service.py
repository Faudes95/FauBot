from __future__ import annotations


class StateClassifierService:
    def classify(self, payload: dict) -> dict:
        known_cancer_diagnosis = self._is_true(payload.get("known_cancer_diagnosis", 1))
        prior_negative_biopsy = self._is_true(payload.get("prior_negative_biopsy"))
        metastasis_site = str(payload.get("metastasis_site", "M0") or "M0")
        metastasis_count = int(float(payload.get("metastasis_count", 0) or 0))
        castration_resistant = self._is_true(payload.get("castration_resistant")) or int(float(payload.get("line_of_therapy", 1) or 1)) > 1
        prior_prostatectomy = self._is_true(payload.get("prior_prostatectomy"))
        prior_radiation = self._is_true(payload.get("prior_radiation"))
        bcr2 = self._is_true(payload.get("bcr2"))
        metachronous = self._is_true(payload.get("metachronous_metastasis"))
        volume_disease = str(payload.get("volume_disease", "Low") or "Low").lower()

        metastatic = metastasis_site.upper() not in {"M0", "", "NONE", "NO"}

        if not known_cancer_diagnosis:
            if prior_negative_biopsy:
                module = "post_negative_biopsy_followup"
            else:
                module = "diagnostic_workup"
        elif castration_resistant:
            if metastatic:
                module = "m1_crpc"
            else:
                module = "m0_crpc"
        elif metastatic:
            if metachronous and metastasis_count <= 5:
                module = "mcspc_oligo_metachronous"
            elif volume_disease == "high" or metastasis_count >= 4 or metastasis_site.lower() == "visceral":
                module = "mcspc_high_volume"
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
            "mcspc_high_volume": "Se detectó enfermedad metastásica sensible a la castración de alto volumen.",
            "m0_crpc": "Se detectó enfermedad resistente a la castración sin metástasis.",
            "m1_crpc": "Se detectó enfermedad resistente a la castración con metástasis.",
        }
        return reasons.get(module, "El módulo fue seleccionado por el clasificador de estado clínico.")
