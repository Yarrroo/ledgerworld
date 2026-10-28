"""Validated storage paths for resources in the original API."""

import re
from pathlib import Path

RESOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def validate_resource_id(value: object) -> str:
    if not isinstance(value, str) or RESOURCE_ID.fullmatch(value) is None:
        raise ValueError("Resource IDs must contain 1-64 ASCII letters, digits, underscores or hyphens")
    return value


def resource_path(root: str, resource_id: str) -> str:
    """Resolve without creating anything; reject symlinks escaping the storage root."""
    path = Path(root) / validate_resource_id(resource_id)
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Resource path is outside its storage root")
    return str(path)
