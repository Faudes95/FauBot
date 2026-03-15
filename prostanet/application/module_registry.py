from __future__ import annotations

from prostanet.domains.adt_progression_verification.service import AdtProgressionVerificationService
from prostanet.domains.evidence_registry.service import EvidenceRegistryService
from prostanet.domains.diagnostic_workup.service import DiagnosticWorkupService
from prostanet.domains.localized_initial.service import LocalizedInitialService
from prostanet.domains.m0_crpc.service import M0CrpcService
from prostanet.domains.m1_crpc.service import M1CrpcService
from prostanet.domains.mcspc_high_volume.service import McspcHighVolumeService
from prostanet.domains.mcspc_low_volume_sync_oligo.service import McspcLowVolumeSyncOligoService
from prostanet.domains.mcspc_oligo_metachronous.service import McspcOligoMetachronousService
from prostanet.domains.post_negative_biopsy_followup.service import PostNegativeBiopsyFollowupService
from prostanet.domains.post_prostatectomy.service import PostProstatectomyService
from prostanet.domains.recurrence_bcr.service import RecurrenceBCRService
from prostanet.domains.state_classifier.service import StateClassifierService
from prostanet.domains.state_classifier.schemas import STATE_CLASSIFIER_SCHEMA
from prostanet.shared.decision_quality import build_decision_quality
from prostanet.shared.module_support import apply_support_bundle, support_bundle_for_module
from prostanet.shared.validated_algorithms import build_validated_algorithms


class ModuleRegistry:
    def __init__(self) -> None:
        self.evidence_registry = EvidenceRegistryService()
        self.state_classifier = StateClassifierService()
        self.services = {
            "diagnostic_workup": DiagnosticWorkupService(),
            "post_negative_biopsy_followup": PostNegativeBiopsyFollowupService(),
            "localized_initial": LocalizedInitialService(),
            "post_prostatectomy": PostProstatectomyService(),
            "recurrence_bcr": RecurrenceBCRService(),
            "adt_progression_verification": AdtProgressionVerificationService(),
            "mcspc_oligo_metachronous": McspcOligoMetachronousService(),
            "mcspc_low_volume_sync_oligo": McspcLowVolumeSyncOligoService(),
            "mcspc_high_volume": McspcHighVolumeService(),
            "m0_crpc": M0CrpcService(),
            "m1_crpc": M1CrpcService(),
        }

    def list_modules(self) -> list[dict]:
        return self.evidence_registry.list_modules()

    def get_module_schema(self, module_id: str) -> dict:
        return self.services[module_id].schema()

    def get_state_classifier_schema(self) -> dict:
        return STATE_CLASSIFIER_SCHEMA

    def evaluate_module(self, module_id: str, payload: dict) -> dict:
        result = self.services[module_id].evaluate(payload)
        evidence = self.get_module_evidence(module_id)
        bundle = support_bundle_for_module(module_id, payload, result, evidence)
        enriched = apply_support_bundle(
            result,
            monitoring=bundle["monitoring"],
            transitions=bundle["transitions"],
            survivorship_risks=bundle["survivorship_risks"],
            palliative_flags=bundle["palliative_flags"],
            care_overlays=bundle["care_overlays"],
            source_citations=bundle["source_citations"],
            evidence_gaps=bundle["evidence_gaps"],
            objective_progression=bundle["objective_progression"],
            decision_changing_inputs=bundle["decision_changing_inputs"],
            supportive_evidence_context=bundle["supportive_evidence_context"],
            benchmarking_flags=bundle["benchmarking_flags"],
        )
        enriched["validated_algorithms"] = build_validated_algorithms(module_id, payload, enriched)
        enriched["decision_quality"] = build_decision_quality(module_id, payload, enriched)
        enriched["state_classification"] = enriched["decision_quality"].get("state_classification", enriched.get("state"))
        enriched["recommendation_family"] = enriched["decision_quality"].get("recommendation_family", "")
        enriched["why_not_more_confident"] = enriched["decision_quality"].get("why_not_more_confident", [])
        return enriched

    def classify_state(self, payload: dict) -> dict:
        return self.state_classifier.classify(payload)

    def get_module_evidence(self, module_id: str) -> dict:
        return self.evidence_registry.get_module_evidence(module_id)

    def get_module_sources(self, module_id: str) -> list[dict]:
        return self.evidence_registry.get_module_sources(module_id)

    def get_guidelines_metadata(self) -> dict[str, dict]:
        return self.evidence_registry.get_guidelines_metadata()
