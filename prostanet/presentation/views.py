from __future__ import annotations

from flask import Blueprint, render_template

from prostanet.application.module_registry import ModuleRegistry
from prostanet.presentation.view_models import build_page_chrome
from prostanet.shared.metastatic_profile import (
    APPENDICULAR_BONE_SITE_KEYS,
    AXIAL_BONE_SITE_KEYS,
    BONE_SITE_LABELS,
    NONREGIONAL_NODAL_SITE_LABELS,
    VISCERAL_SITE_LABELS,
)
from prostanet.shared.presentation_text import humanize_evidence, humanize_module_listing, humanize_schema


modular_views = Blueprint("modular_views", __name__)
registry = ModuleRegistry()


def _quick_classifier_config() -> dict:
    def _group(label: str, keys: tuple[str, ...]) -> dict:
        return {
            "label": label,
            "options": [
                {"site_key": key, "label": BONE_SITE_LABELS[key]}
                for key in keys
            ],
        }

    return {
        "bone_site_groups": [
            _group("Esqueleto axial", AXIAL_BONE_SITE_KEYS),
            _group("Esqueleto apendicular", APPENDICULAR_BONE_SITE_KEYS),
        ],
        "visceral_site_options": [
            {"site_key": key, "label": VISCERAL_SITE_LABELS[key]}
            for key in VISCERAL_SITE_LABELS
        ],
        "nonregional_nodal_site_options": [
            {"site_key": key, "label": NONREGIONAL_NODAL_SITE_LABELS[key]}
            for key in NONREGIONAL_NODAL_SITE_LABELS
        ],
    }


@modular_views.route("/clinical-hub", methods=["GET"])
def clinical_hub():
    modules = [humanize_module_listing(module) for module in registry.list_modules()]
    page_chrome = build_page_chrome(
        "clinical_hub",
        "Centro clínico por estadio",
        "Clasificación clínica guiada por la Red Nacional Integral del Cáncer (NCCN) 5.2026 con comparación paralela de la Asociación Europea de Urología (EAU) 2026.",
    )
    return render_template(
        "clinical_hub.html",
        modules=modules,
        page_chrome=page_chrome,
        quick_classifier_config=_quick_classifier_config(),
    )


@modular_views.route("/wizard/<module_id>", methods=["GET"])
def wizard(module_id: str):
    schema = humanize_schema(registry.get_module_schema(module_id))
    evidence = humanize_evidence(registry.get_module_evidence(module_id))
    page_chrome = build_page_chrome(
        "clinical_hub",
        schema["title"],
        schema["description"],
        content_width_class="max-w-7xl",
    )
    return render_template(
        "clinical_wizard.html",
        schema=schema,
        evidence=evidence,
        page_chrome=page_chrome,
        metastatic_capture_config=_quick_classifier_config(),
    )
