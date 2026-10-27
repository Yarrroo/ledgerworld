"""/api/v1: one typed API behind the demo token for the six screens (system brief §11, C6)."""

from __future__ import annotations

from flask import Flask

from .routes import bp
from .services import Services

__all__ = ["Services", "register"]


def register(app: Flask, services: Services | None = None) -> Flask:
    """Mount /api/v1 on ``app`` with ``services`` (the deployed wiring when None)."""
    app.extensions["ledgerworld"] = services or Services.from_env()
    app.register_blueprint(bp, url_prefix="/api/v1")
    return app
