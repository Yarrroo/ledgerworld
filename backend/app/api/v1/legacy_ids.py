"""Id validation for the upstream engine's routes (Security 2), installed on the app by `create_app`.

The upstream `/api/graph`, `/api/simulation` and `/api/report` blueprints join ids taken from the
URL, the query string, a form or a JSON body straight into filesystem paths. Every id they take
(a URL segment, or a top-level field, named `*_id`) must match `ID_PATTERN` before a handler
runs: a malformed id in the URL answers 404 (no such resource can exist), one in the query, form
or body answers 400. The handlers themselves answer 404 for a well-formed id they do not know.
"""

from __future__ import annotations

import re
from typing import Any

from flask import Flask, jsonify, request

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
UPSTREAM_BLUEPRINTS = frozenset({"graph", "simulation", "report"})


def valid_id(value: Any) -> bool:
    """A string id of 1-64 letters, digits, `_` or `-`; an int (an agent's index) is not a path."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def _refuse(status: int, name: str):
    return jsonify({"success": False, "error": f"invalid {name}"}), status


def check_request():
    """The before-request hook: refuse a malformed id before an upstream handler sees it."""
    if request.blueprint not in UPSTREAM_BLUEPRINTS:
        return None
    for name, value in (request.view_args or {}).items():
        if name.endswith("_id") and not valid_id(value):
            return _refuse(404, name)
    for source in (request.args, request.form):
        for name in source:
            if name.endswith("_id") and not all(valid_id(v) for v in source.getlist(name)):
                return _refuse(400, name)
    body = request.get_json(silent=True) if request.is_json else None
    if isinstance(body, dict):
        for name, value in body.items():
            if name.endswith("_id") and value is not None and not valid_id(value):
                return _refuse(400, name)
    return None


def install(app: Flask) -> None:
    app.before_request(check_request)
