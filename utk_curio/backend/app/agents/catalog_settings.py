"""Account-level catalog settings: the values a user owns, such as keyword types.

Stored at ``<CURIO_LAUNCH_CWD>/.curio/users/<user_key>/catalog-settings.json``,
beside ``imported-agents.json``, with the shape
``{"version": 1, "values": {"<key>": <value>, ...}}``. Only values the user
changed are stored; an absent key takes its shipped default. The keys, their
schemas and defaults are defined once in ``contracts.CATALOG_SETTINGS``.

The read path never raises: a missing or corrupt file, or a stored value that
no longer validates, reads as the default.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

from utk_curio.backend.app.agents import contracts
from utk_curio.backend.app.common.file_locks import exclusive_lock
from utk_curio.backend.app.packages.storage import _user_key_segment, _users_base

log = logging.getLogger(__name__)

_FILENAME = "catalog-settings.json"
_SCHEMA_VERSION = 1
_LOCK_NAMESPACE = "catalog-settings"
#: Errors reported for one rejected value; enough to fix it, short enough to read.
_MAX_ERRORS = 5


class SettingError(ValueError):
    """A value that is not valid for its key."""


def _path(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / _FILENAME


def errors(key: str, value: object) -> list[str]:
    """Why *value* is not a valid value for *key*; empty when it is."""
    from jsonschema import Draft202012Validator

    setting = contracts.CATALOG_SETTINGS.get(key)
    if setting is None:
        return [f"unknown setting {key!r}"]
    found = sorted(
        Draft202012Validator(setting.schema).iter_errors(value),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    messages = [
        f"{key}{''.join(f'[{part}]' for part in error.absolute_path)}: {error.message}"
        for error in found
    ]
    if not messages and setting.unique_by:
        seen: set[str] = set()
        for index, entry in enumerate(value):
            name = str(entry[setting.unique_by]).strip().casefold()
            if name in seen:
                messages.append(
                    f"{key}[{index}][{setting.unique_by}]: "
                    f"{entry[setting.unique_by]!r} appears more than once"
                )
            seen.add(name)
    return messages[:_MAX_ERRORS]


def _read(user_key: str) -> dict:
    path = _path(user_key)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Corrupt %s for %s; reading the defaults", _FILENAME, user_key)
        return {}
    stored = raw.get("values") if isinstance(raw, dict) else None
    return stored if isinstance(stored, dict) else {}


def stored_values(user_key: str) -> dict:
    """The values the user changed, each still valid for its key."""
    kept = {}
    for key, value in _read(user_key).items():
        if key not in contracts.CATALOG_SETTINGS:
            continue
        if errors(key, value):
            log.warning("Stored %s for %s no longer validates; reading the default", key, user_key)
            continue
        kept[key] = value
    return kept


def values(user_key: str) -> dict:
    """Every setting's value for *user_key*: the stored one, else the default."""
    stored = stored_values(user_key)
    return {
        key: copy.deepcopy(stored.get(key, setting.default))
        for key, setting in contracts.CATALOG_SETTINGS.items()
    }


def update(user_key: str, changes: dict) -> dict:
    """Apply *changes* (key to value; ``None`` restores the default) and return
    every value. Nothing is written unless every change is valid."""
    if not isinstance(changes, dict) or not changes:
        raise SettingError("send an object mapping setting keys to values")
    problems = [
        message
        for key, value in changes.items()
        if value is not None
        for message in errors(key, value)
    ]
    problems += [f"unknown setting {key!r}" for key, value in changes.items()
                 if value is None and key not in contracts.CATALOG_SETTINGS]
    if problems:
        raise SettingError("; ".join(problems[:_MAX_ERRORS]))
    path = _path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path.parent / f".{_FILENAME}.lock", namespace=_LOCK_NAMESPACE, key=user_key):
        stored = stored_values(user_key)
        for key, value in changes.items():
            if value is None or value == contracts.CATALOG_SETTINGS[key].default:
                stored.pop(key, None)
            else:
                stored[key] = value
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"version": _SCHEMA_VERSION, "values": stored}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    return values(user_key)


def configuration_for(user_key: str, keys) -> str | None:
    """The configuration slot for a run that reads *keys*. A key no setting
    defines is left out with a warning, so a definition written for another
    Curio still runs."""
    wanted = []
    for key in dict.fromkeys(keys):
        if key in contracts.CATALOG_SETTINGS:
            wanted.append(key)
        else:
            log.warning("No catalog setting is named %r; the run proceeds without it", key)
    if not wanted:
        return None
    current = values(user_key)
    return contracts.render_configuration({key: current[key] for key in wanted})
