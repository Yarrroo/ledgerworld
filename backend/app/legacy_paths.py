"""Validated storage paths for resources in the original API."""

import re
from pathlib import Path

RESOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def validate_resource_id(value: object) -> str:
    if not isinstance(value, str) or RESOURCE_ID.fullmatch(value) is None:
        raise ValueError("Resource IDs must contain 1-64 ASCII letters, digits, underscores or hyphens")
    return value


def contained_path(root: str, path: Path) -> str:
    try:
        if not path.resolve().is_relative_to(Path(root).resolve()):
            raise ValueError("Resource path is outside its storage root")
    except RuntimeError as error:
        raise ValueError("Resource path contains a cyclic symlink") from error
    return str(path)


def resource_path(root: str, resource_id: str) -> str:
    """Resolve without creating anything; reject symlinks escaping the storage root."""
    path = Path(root) / validate_resource_id(resource_id)
    return contained_path(root, path)


def validate_resource_links(root: str, resource_id: str) -> None:
    """Check stored file links before dispatch, not only their parent directory."""
    folder = Path(resource_path(root, resource_id))
    if folder.is_dir():
        for entry in folder.iterdir():
            if entry.is_symlink():
                contained_path(root, entry)


def resource_entries(root: str, *, legacy_json: bool = False):
    """List only safe resource directories and, optionally, legacy report JSON files."""
    folder = Path(root)
    if not folder.is_dir():
        return
    for entry in folder.iterdir():
        is_legacy = legacy_json and entry.suffix == ".json"
        try:
            validate_resource_id(entry.stem if is_legacy else entry.name)
            contained_path(root, entry)
            if entry.is_dir():
                validate_resource_links(root, entry.name)
                yield entry.name
            elif is_legacy and entry.is_file():
                yield entry.name
        except (ValueError, OSError):
            continue
