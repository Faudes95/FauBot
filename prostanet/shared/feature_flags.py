from __future__ import annotations

import os
from typing import Any


DEFAULT_FEATURE_FLAGS = {
    # ── Existing clinical flags ──
    "ENABLE_CLINICAL_WIZARDS": True,
    "ENABLE_NCCN_2026_ENGINE": True,
    "ENABLE_EAU_2026_COMPARE": True,
    "ENABLE_BCR2_MODULE": True,
    # ── AI Models ──
    "ENABLE_AI_STATE_PREDICTION": False,
    "ENABLE_AI_TREATMENT_PREDICTION": False,
    "ENABLE_AI_SURVIVAL_MODEL": False,
    "ENABLE_AI_ANOMALY_DETECTION": False,
    "ENABLE_AI_NLP_EXTRACTION": False,
    # ── AI Agents ──
    "ENABLE_AGENT_CDA": False,
    "ENABLE_AGENT_PSA": False,
    "ENABLE_AGENT_TOA": False,
    "ENABLE_AGENT_QAA": False,
    "ENABLE_AGENT_RIA": False,
    # ── Vertical copiloto clínico ──
    "ENABLE_CRPC_COPILOT": False,
    "ENABLE_POST_RP_SALVAGE_COPILOT": False,
    # ── Engine ──
    "ENABLE_RECALCULATION_ENGINE": False,
    "ENABLE_EVENT_BUS": False,
}


def resolve_feature_flags(config: dict[str, Any] | None = None) -> dict[str, bool]:
    config = config or {}
    flags: dict[str, bool] = {}
    for key, default in DEFAULT_FEATURE_FLAGS.items():
        env_val = os.environ.get(key)
        if key in config:
            flags[key] = bool(config[key])
        elif env_val is not None:
            flags[key] = env_val.lower() in {"1", "true", "yes", "on"}
        else:
            flags[key] = default
    return flags
