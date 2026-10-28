"""Security boundary for the original, non-v1 API blueprints."""

from pathlib import Path

from flask import Flask, current_app, jsonify, request

from ..legacy_paths import resource_path, validate_resource_id

RESOURCE_FIELDS = ("project_id", "simulation_id", "report_id")

PREFIXES = ("/api/graph", "/api/simulation", "/api/report")


def resource_exists(field: str, resource_id: str) -> bool:
    from ..models.project import ProjectManager
    from ..services.report_agent import ReportManager
    from ..services.simulation_manager import SimulationManager

    if field == "project_id":
        return Path(ProjectManager._get_project_meta_path(resource_id)).is_file()
    if field == "simulation_id":
        return (Path(SimulationManager()._get_simulation_dir(resource_id)) / "state.json").is_file()
    folder = Path(ReportManager._get_report_folder(resource_id))
    legacy = Path(resource_path(ReportManager.REPORTS_DIR, resource_id) + ".json")
    if not legacy.resolve().is_relative_to(Path(ReportManager.REPORTS_DIR).resolve()):
        raise ValueError("Resource path is outside its storage root")
    return folder.is_dir() or legacy.is_file()


def validate_request_resources():
    values = [(key, value) for key, value in (request.view_args or {}).items()
              if key in RESOURCE_FIELDS]
    for key in RESOURCE_FIELDS:
        values.extend((key, value) for value in request.args.getlist(key))
    if request.is_json:
        data = request.get_json(silent=True)
        if data is not None and not isinstance(data, dict):
            return jsonify(success=False, error="JSON body must be an object"), 400
        values.extend((key, data[key]) for key in RESOURCE_FIELDS if data and key in data)
    try:
        for _, value in values:
            validate_resource_id(value)
        if (request.endpoint in {"simulation.get_simulation_posts", "simulation.get_simulation_comments"}
                and any(value not in {"twitter", "reddit"}
                        for value in request.args.getlist("platform"))):
            return jsonify(success=False, error="Unsupported platform"), 400
        for field, value in values:
            if not resource_exists(field, value):
                return jsonify(success=False, error="Resource not found"), 404
    except (ValueError, OSError):
        return jsonify(success=False, error="Invalid resource ID or storage path"), 400
    return None


def guard_legacy_request():
    if not any(request.path == prefix or request.path.startswith(prefix + "/")
               for prefix in PREFIXES):
        return None
    if request.method != "GET":
        services = current_app.extensions["ledgerworld"]
        if not services.authorised(request.headers.get("Authorization")):
            return jsonify(success=False, error="Demo bearer token required"), 401
    return validate_request_resources()


def register(app: Flask) -> None:
    app.before_request(guard_legacy_request)
