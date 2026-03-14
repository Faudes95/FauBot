from __future__ import annotations

from flask import Flask

from prostanet.presentation.api import modular_api
from prostanet.presentation.views import modular_views


def register_modular_blueprints(app: Flask) -> None:
    if "modular_api" not in app.blueprints:
        app.register_blueprint(modular_api)
    if "modular_views" not in app.blueprints:
        app.register_blueprint(modular_views)
