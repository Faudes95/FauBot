from __future__ import annotations

from flask import Blueprint, render_template

from prostanet.application.module_registry import ModuleRegistry
from prostanet.presentation.view_models import build_page_chrome
from prostanet.shared.presentation_text import humanize_evidence, humanize_module_listing, humanize_schema


modular_views = Blueprint("modular_views", __name__)
registry = ModuleRegistry()


@modular_views.route("/clinical-hub", methods=["GET"])
def clinical_hub():
    modules = [humanize_module_listing(module) for module in registry.list_modules()]
    page_chrome = build_page_chrome(
        "clinical_hub",
        "Centro clínico por estadio",
        "Clasificación clínica guiada por la Red Nacional Integral del Cáncer (NCCN) 5.2026 con comparación paralela de la Asociación Europea de Urología (EAU) 2026.",
    )
    return render_template("clinical_hub.html", modules=modules, page_chrome=page_chrome)


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
    return render_template("clinical_wizard.html", schema=schema, evidence=evidence, page_chrome=page_chrome)
