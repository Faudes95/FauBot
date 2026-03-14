from __future__ import annotations

import os
from typing import Any


DEFAULT_FEATURE_FLAGS = {
    "ENABLE_CLINICAL_WIZARDS": True,
    "ENABLE_NCCN_2026_ENGINE": True,
    "ENABLE_EAU_2026_COMPARE": True,
    "ENABLE_BCR2_MODULE": True,
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

