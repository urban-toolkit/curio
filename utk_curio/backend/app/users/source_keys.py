"""The keys an account saved for the Discovery Catalog's sources: the Data
source kind in API Settings.

A source manifest names the key it sends in ``auth.secretId``, so this store
is keyed by that id: a key a new source declares needs no column, migration or
code. Which source receives a key is decided when one is sent
(``discovery/infrastructure/credentials.py``): only a source whose manifest
names its id, and only at that source's own origin.

Storage: ``.curio/users/<key>/source-keys.json``, an owner-only file
(``common.owner_only_file``: 0600 in a 0700 directory, written atomically under
the two-layer lock)::

    {"version": 1, "keys": {"<secret id>": {"value": "...", "savedAt": <epoch>}}}

A file of its own, beside ``connection-keys.json``: node code reads that
file's keys by name through ``curio_secret``, and a source's key never reaches
node code. Only :func:`value_for` (and :meth:`SourceKeyStore.value` under it)
returns a value; everything else returns secret ids. **Plaintext at rest**,
as the other owner-only files are.

A guest on a ``--deploy`` instance is every visitor at once, so it holds no
keys: nothing is listed or sent for it, and nothing is saved
(``capabilities.token_refusal`` refuses it first). What the one local user
saved as the shared guest without ``--deploy`` stays on disk for the next
local run.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from utk_curio.backend.app.common import owner_only_file
from utk_curio.backend.app.common.user_storage import GUEST_KEY, user_key_segment, users_base

log = logging.getLogger(__name__)

STORE_FILENAME = "source-keys.json"
STORE_VERSION = 1
_LOCK_NAMESPACE = "source-keys"

MAX_KEYS_PER_USER = 32
MAX_VALUE_CHARS = 4096
MAX_SECRET_ID_CHARS = 100


class SourceKeyError(ValueError):
    """A request the store refuses; carries the HTTP status a route returns."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check_changes(changes: object) -> dict[str, str | None]:
    """*changes* as the store applies them: each secret id to its value, or to
    None when the value is ``""`` (remove the key). Raises
    :class:`SourceKeyError` naming the first problem; never echoes a value."""
    if not isinstance(changes, dict):
        raise SourceKeyError("source_keys must map each key's secret id to its value")
    checked: dict[str, str | None] = {}
    for secret_id, value in changes.items():
        if not isinstance(secret_id, str) or not secret_id.strip() or len(secret_id) > MAX_SECRET_ID_CHARS:
            raise SourceKeyError("a Data source key is named by the secret id its sources declare")
        if not isinstance(value, str):
            raise SourceKeyError(f"the key for {secret_id} must be a string; an empty one removes it")
        if value == "":
            checked[secret_id] = None
            continue
        text = value.strip()
        if not text:
            raise SourceKeyError(f"the key for {secret_id} is empty")
        if "\r" in text or "\n" in text:
            raise SourceKeyError(f"the key for {secret_id} must be a single line")
        if len(text) > MAX_VALUE_CHARS:
            raise SourceKeyError(f"the key for {secret_id} is longer than {MAX_VALUE_CHARS} characters")
        checked[secret_id] = text
    return checked


def storage_key_for(user) -> str | None:
    """The account's folder under ``.curio/users/``: its numeric id, or
    ``guest`` for the shared guest. None for no user, for the shared guest
    under ``--deploy``, and for any other guest: they hold no keys."""
    from utk_curio.backend import config

    if user is None:
        return None
    if getattr(user, "is_guest", False):
        shared = getattr(user, "username", None) == config.CURIO_SHARED_GUEST_USERNAME
        return GUEST_KEY if shared and config.CURIO_NO_AUTH else None
    user_id = getattr(user, "id", None)
    return str(user_id) if isinstance(user_id, int) and not isinstance(user_id, bool) else None


class SourceKeyStore:
    """File-backed store of each account's Data source keys. Only
    :meth:`value` returns a key."""

    def __init__(self, base: Path | None = None):
        self._base = base

    def _user_dir(self, user_key: str) -> Path:
        base = self._base if self._base is not None else users_base()
        return base / user_key_segment(user_key)

    def path(self, user_key: str) -> Path:
        return self._user_dir(user_key) / STORE_FILENAME

    def _locked(self, user_key: str):
        return owner_only_file.locked(
            self._user_dir(user_key), STORE_FILENAME, namespace=_LOCK_NAMESPACE, key=user_key
        )

    def _read(self, user_key: str) -> dict[str, dict]:
        """The saved keys by secret id. A file that cannot be read is an error,
        reported without its contents."""
        path = self.path(user_key)
        if not path.is_file():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, ValueError) as exc:
            log.warning("source-keys store for %s is unreadable (%s)", user_key, exc.__class__.__name__)
            raise SourceKeyError("the Data source keys file is unreadable", 500)
        keys = doc.get("keys") if isinstance(doc, dict) else None
        if not isinstance(keys, dict):
            log.warning("source-keys store for %s is malformed", user_key)
            raise SourceKeyError("the Data source keys file is malformed", 500)
        return {
            secret_id: entry
            for secret_id, entry in keys.items()
            if isinstance(entry, dict) and isinstance(entry.get("value"), str) and entry["value"]
        }

    def saved(self, user_key: str) -> list[str]:
        """The secret ids this account holds a key for, sorted. A file that
        cannot be read holds none here: sign-in and the key list never fail
        on it."""
        try:
            return sorted(self._read(user_key))
        except SourceKeyError:
            return []

    def value(self, user_key: str, secret_id: str) -> str | None:
        """The one read that returns a key. None when there is none, or the
        file cannot be read."""
        try:
            entry = self._read(user_key).get(secret_id)
        except SourceKeyError:
            return None
        return entry["value"] if entry else None

    def update(self, user_key: str, changes: object) -> None:
        """Save each value in *changes* and remove each key whose value is
        ``""``; keys it does not name stay. Checked whole before anything is
        written, and a file that cannot be read is never replaced."""
        checked = check_changes(changes)
        with self._locked(user_key):
            keys = self._read(user_key)
            now = time.time()
            for secret_id, value in checked.items():
                if value is None:
                    keys.pop(secret_id, None)
                else:
                    keys[secret_id] = {"value": value, "savedAt": now}
            if len(keys) > MAX_KEYS_PER_USER:
                raise SourceKeyError(f"at most {MAX_KEYS_PER_USER} Data source keys per account")
            owner_only_file.write_json(self.path(user_key), {"version": STORE_VERSION, "keys": keys})


_DEFAULT_STORE: SourceKeyStore | None = None


def default_store() -> SourceKeyStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = SourceKeyStore()
    return _DEFAULT_STORE


def saved_for(user) -> list[str]:
    """The secret ids *user* holds a key for; none for a guest under ``--deploy``."""
    user_key = storage_key_for(user)
    return default_store().saved(user_key) if user_key else []


def value_for(user, secret_id: str) -> str | None:
    """The key *user* saved under *secret_id*, or None."""
    user_key = storage_key_for(user)
    return default_store().value(user_key, secret_id) if user_key and secret_id else None


def save_for(user, changes: object) -> None:
    """Apply *changes* to *user*'s keys (see :meth:`SourceKeyStore.update`)."""
    user_key = storage_key_for(user)
    if user_key is None:
        raise SourceKeyError("This account cannot hold Data source keys.", 403)
    default_store().update(user_key, changes)
