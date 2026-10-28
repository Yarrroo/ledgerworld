"""Security boundary for the original, non-v1 API blueprints."""

from flask import Flask, current_app, jsonify, request

PREFIXES = ("/api/graph", "/api/simulation", "/api/report")


def guard_legacy_request():
    if not any(request.path == prefix or request.path.startswith(prefix + "/")
               for prefix in PREFIXES):
        return None
    if request.method != "GET":
        services = current_app.extensions["ledgerworld"]
        if not services.authorised(request.headers.get("Authorization")):
            return jsonify(success=False, error="Demo bearer token required"), 401
    return None


def register(app: Flask) -> None:
    app.before_request(guard_legacy_request)
