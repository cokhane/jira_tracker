"""Board registry — loads projects.yaml (per-board config), hot-reloaded on mtime change.

Mirrors config.py's get_settings() pattern: the file is re-read automatically when its
timestamp changes, so editing projects.yaml (adding a board, changing a roster) takes effect
on the next request WITHOUT a restart. Shared secrets stay in .env (see config.py); this
module only knows the list of boards and each board's per-team overrides.

One board = one ProjectEntry (key/name/db_file + raw overrides). resolve_cfg() merges an
entry with the shared Settings into a ProjectConfig that sync/report code consumes.
"""
import os
from dataclasses import dataclass, field

import yaml

from app.config import ProjectConfig, get_settings


@dataclass
class ProjectEntry:
    key: str
    name: str
    db_file: str
    overrides: dict = field(default_factory=dict)


# Cached registry + the projects.yaml mtime it was built from (same trick as get_settings).
_cache: dict = {"entries": None, "mtime": None, "path": None}

# Fields consumed directly off the entry — everything else in a board's block is an override.
_STRUCTURAL = {"key", "name", "db_file"}


def _projects_path() -> str:
    return get_settings().projects_file


def _file_mtime(path: str) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def _parse(path: str) -> list[ProjectEntry]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    raw_list = data.get("projects", []) if isinstance(data, dict) else []
    entries: list[ProjectEntry] = []
    for block in raw_list:
        if not isinstance(block, dict) or not block.get("key"):
            continue
        key = str(block["key"]).strip()
        name = str(block.get("name") or key)
        db_file = str(block.get("db_file") or f"{key.lower()}.db")
        overrides = {k: v for k, v in block.items() if k not in _STRUCTURAL}
        entries.append(ProjectEntry(key=key, name=name, db_file=db_file, overrides=overrides))
    return entries


def get_registry() -> list[ProjectEntry]:
    """All configured boards, rebuilt if projects.yaml changed since last read."""
    path = _projects_path()
    mtime = _file_mtime(path)
    if _cache["entries"] is None or _cache["mtime"] != mtime or _cache["path"] != path:
        _cache["entries"] = _parse(path) if mtime is not None else []
        _cache["mtime"] = mtime
        _cache["path"] = path
    return _cache["entries"]


def get_project_entry(key: str) -> ProjectEntry | None:
    """The board with this key (case-insensitive), or None if it isn't configured."""
    target = (key or "").strip().upper()
    return next((e for e in get_registry() if e.key.upper() == target), None)


def resolve_cfg(key: str) -> ProjectConfig | None:
    """Merge a board's entry with the shared Settings into a ProjectConfig (None if unknown)."""
    entry = get_project_entry(key)
    if entry is None:
        return None
    return ProjectConfig(
        settings=get_settings(),
        key=entry.key,
        name=entry.name,
        db_file=entry.db_file,
        overrides=entry.overrides,
    )


def reload_registry() -> list[ProjectEntry]:
    """Force an immediate re-read of projects.yaml (used by POST /api/config/reload)."""
    _cache["entries"] = None
    return get_registry()
