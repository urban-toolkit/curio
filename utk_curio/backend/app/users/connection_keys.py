"""Per-user connection keys — the API keys a data-loading node reaches only by
name (memo dev/116, DEC-074).

A node's code says ``api_key = curio_secret("census")``; the value never
appears in the code, the saved dataflow, a proposal, the chat, or the runtime
journal. The backend resolves the names that appear in the code at execution
time and hands the values to the sandbox inside the execution request, where
they exist only as an injected callable (never an environment variable — node
code can read ``os.environ`` — never a staged file, never a log line).

This module is the ONE place values are read back. Everyone else — routes,
grounding, cards — holds :class:`ConnectionKeyRef` (name, host, delivery,
timestamps) and nothing more.

Storage: ``.curio/users/<key>/connection-keys.json``, mode 0600 in a 0700
directory, written atomically (temp file + ``os.replace``) under the same
two-layer lock the project spec uses. ``.curio/users`` is already in the
sandbox isolation's ``SENSITIVE_PATHS``, so node code running under isolation
cannot open the file the resolver reads. **Plaintext at rest**: the same
posture as the LLM key column today; encryption is T4's remainder and lands
by swapping :class:`ConnectionKeyStore`'s backend — callers keep their refs.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from utk_curio.backend.app.common.file_locks import exclusive_lock
from utk_curio.backend.app.common.user_storage import GUEST_KEY, user_key_segment, users_base

log = logging.getLogger(__name__)

STORE_FILENAME = "connection-keys.json"
STORE_VERSION = 1
_LOCK_NAMESPACE = "connection-keys"

#: The name in ``curio_secret("<name>")`` — lower-case, short, path-safe.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
#: Literal ``curio_secret("<name>")`` calls in node code — the ONE regex the
#: execution resolvers (Play, the validation runner) and the grounding gate
#: share. Single or double quotes, because users edit generated code. Only a
#: literal argument can be resolved; a dynamic one is simply not found, and
#: the sandbox names it as missing.
SECRET_CALL_RE = re.compile(r"""curio_secret\(\s*(["'])([a-z0-9][a-z0-9_-]{0,39})\1\s*\)""")
#: Bound the per-execution resolution work (mirrors the sandbox's cap).
MAX_SECRET_NAMES = 8
#: A bare hostname (no scheme, path, port or userinfo), already lower-cased.
HOST_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

MAX_KEYS_PER_USER = 32
MAX_VALUE_CHARS = 4096

#: How the API expects the key. ``code`` = the node's code decides (default);
#: ``query:<param>`` / ``header:<Header-Name>`` also let a probe carry it.
DELIVERY_CODE = "code"
_DELIVERY_PREFIXES = ("query:", "header:")


class ConnectionKeyError(ValueError):
    """A request the store refuses; carries the HTTP status a route returns."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ConnectionKeyRef:
    """What everyone but the resolver sees — never the value."""

    name: str
    host: str
    delivery: str
    created_at: float
    last_used_at: float | None = None

    @property
    def use_line(self) -> str:
        """The one line of node code that reaches this key."""
        return f'api_key = curio_secret("{self.name}")'

    def to_payload(self) -> dict:
        return {
            "name": self.name,
            "host": self.host,
            "delivery": self.delivery,
            "use": self.use_line,
            "createdAt": self.created_at,
            "lastUsedAt": self.last_used_at,
        }


# ---------------------------------------------------------------------------
# Normalisation (pure)
# ---------------------------------------------------------------------------


def normalize_name(name: object) -> str:
    text = str(name or "").strip().lower()
    if not NAME_RE.match(text):
        raise ConnectionKeyError(
            "a key name is 1–40 characters: lower-case letters, digits, '-' or '_', "
            "starting with a letter or digit"
        )
    return text


def normalize_host(host: object) -> str:
    """A bare hostname: ``https://api.census.gov/data?x=1`` → ``api.census.gov``."""
    text = str(host or "").strip().lower()
    if "://" in text:
        text = urlsplit(text).hostname or ""
    else:
        text = text.split("/", 1)[0].split("?", 1)[0]
        if "@" in text:
            text = text.rsplit("@", 1)[1]
        text = text.split(":", 1)[0]
    text = text.rstrip(".")
    if not HOST_RE.match(text):
        raise ConnectionKeyError("host must be a hostname such as api.census.gov")
    return text


def normalize_delivery(delivery: object) -> str:
    text = str(delivery if delivery is not None else DELIVERY_CODE).strip()
    if not text or text == DELIVERY_CODE:
        return DELIVERY_CODE
    for prefix in _DELIVERY_PREFIXES:
        if text.startswith(prefix):
            token = text[len(prefix):].strip()
            if not _TOKEN_RE.match(token):
                raise ConnectionKeyError(
                    f"'{prefix}' needs a parameter or header name (letters, digits, '-' or '_')"
                )
            return prefix + token
    raise ConnectionKeyError("delivery must be 'code', 'query:<param>' or 'header:<Header-Name>'")


def normalize_value(value: object) -> str:
    if not isinstance(value, str):
        raise ConnectionKeyError("the key value must be a string")
    text = value.strip()
    if not text:
        raise ConnectionKeyError("the key value is empty")
    if len(text) > MAX_VALUE_CHARS:
        raise ConnectionKeyError(f"the key value is longer than {MAX_VALUE_CHARS} characters")
    if any(ch in text for ch in "\r\n"):
        raise ConnectionKeyError("the key value must be a single line")
    return text


def secret_names(code: object) -> list[str]:
    """The names *code* reaches through literal ``curio_secret("<name>")``
    calls, in order, deduplicated, bounded."""
    if not isinstance(code, str) or "curio_secret" not in code:
        return []
    names: list[str] = []
    for match in SECRET_CALL_RE.finditer(code):
        name = match.group(2)
        if name not in names:
            names.append(name)
        if len(names) >= MAX_SECRET_NAMES:
            break
    return names


def suggest_name(host: str) -> str:
    """``api.census.gov`` → ``census``; ``data.cityofchicago.org`` → ``cityofchicago``.
    The second-level label, made name-safe; the host itself when in doubt."""
    try:
        host = normalize_host(host)
    except ConnectionKeyError:
        return ""
    labels = host.split(".")
    label = labels[-2] if len(labels) >= 2 else labels[0]
    text = re.sub(r"[^a-z0-9_-]", "-", label).strip("-")[:40]
    return text if NAME_RE.match(text) else re.sub(r"[^a-z0-9_-]", "-", host)[:40]


def storage_key_for(user) -> str:
    """The on-disk user key: the shared guest → ``guest``, else the numeric id
    (the same key that names the projects and datasets directories)."""
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    if user is None:
        raise ConnectionKeyError("Authorization required.", 401)
    if getattr(user, "is_guest", False):
        if getattr(user, "username", None) == CURIO_SHARED_GUEST_USERNAME:
            return GUEST_KEY
        raise ConnectionKeyError("Sign in to save connection keys — guest sessions are temporary.", 403)
    return str(user.id)


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class ConnectionKeyStore:
    """File-backed store; the T4-replaceable interface. Only :meth:`resolve`
    returns values."""

    def __init__(self, base: Path | None = None):
        self._base = base

    # -- paths ---------------------------------------------------------------

    def _user_dir(self, user_key: str) -> Path:
        base = self._base if self._base is not None else users_base()
        return base / user_key_segment(user_key)

    def path(self, user_key: str) -> Path:
        return self._user_dir(user_key) / STORE_FILENAME

    def _locked(self, user_key: str):
        d = self._user_dir(user_key)
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
        return exclusive_lock(d / f".{STORE_FILENAME}.lock", namespace=_LOCK_NAMESPACE, key=user_key)

    # -- file I/O ---------------------------------------------------------------

    def _read(self, user_key: str) -> dict:
        """The raw document, or an empty one. A corrupt file is reported once
        (without its contents) and treated as empty — never as a crash."""
        path = self.path(user_key)
        if not path.is_file():
            return {"version": STORE_VERSION, "keys": {}}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, ValueError) as exc:
            log.warning("connection-keys store for %s is unreadable (%s) — treated as empty",
                        user_key, exc.__class__.__name__)
            raise ConnectionKeyError("the connection-keys store is unreadable", 500)
        keys = doc.get("keys") if isinstance(doc, dict) else None
        if not isinstance(keys, dict):
            raise ConnectionKeyError("the connection-keys store is malformed", 500)
        return {"version": STORE_VERSION, "keys": keys}

    def _write(self, user_key: str, doc: dict) -> None:
        path = self.path(user_key)
        fd, tmp = tempfile.mkstemp(prefix=".connection-keys.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _ref(name: str, entry: dict) -> ConnectionKeyRef:
        return ConnectionKeyRef(
            name=name,
            host=str(entry.get("host") or ""),
            delivery=str(entry.get("delivery") or DELIVERY_CODE),
            created_at=float(entry.get("createdAt") or 0.0),
            last_used_at=entry.get("lastUsedAt"),
        )

    # -- the interface ----------------------------------------------------------

    def list(self, user_key: str) -> list[ConnectionKeyRef]:
        doc = self._read(user_key)
        return [self._ref(name, entry) for name, entry in sorted(doc["keys"].items())
                if isinstance(entry, dict)]

    def get(self, user_key: str, name: str) -> ConnectionKeyRef | None:
        entry = self._read(user_key)["keys"].get(name)
        return self._ref(name, entry) if isinstance(entry, dict) else None

    def put(self, user_key: str, name: object, host: object, value: object,
            delivery: object = DELIVERY_CODE, *, replace: bool = False) -> tuple[ConnectionKeyRef, bool]:
        """Save (or overwrite) a key. Returns ``(ref, created)``. Re-binding an
        existing name to a DIFFERENT host needs ``replace=True`` (409 otherwise),
        so a typo cannot silently point a key at another host."""
        name = normalize_name(name)
        host = normalize_host(host)
        delivery = normalize_delivery(delivery)
        value = normalize_value(value)
        with self._locked(user_key):
            doc = self._read(user_key)
            keys = doc["keys"]
            current = keys.get(name)
            created = not isinstance(current, dict)
            if not created and current.get("host") != host and not replace:
                raise ConnectionKeyError(
                    f"'{name}' is saved for {current.get('host')}; pass replace to bind it to {host}", 409
                )
            if created and len(keys) >= MAX_KEYS_PER_USER:
                raise ConnectionKeyError(f"at most {MAX_KEYS_PER_USER} connection keys per account", 400)
            now = time.time()
            keys[name] = {
                "host": host,
                "delivery": delivery,
                "value": value,
                "createdAt": current.get("createdAt", now) if not created else now,
                "lastUsedAt": None if created else current.get("lastUsedAt"),
            }
            self._write(user_key, doc)
            return self._ref(name, keys[name]), created

    def delete(self, user_key: str, name: object) -> bool:
        name = normalize_name(name)
        with self._locked(user_key):
            doc = self._read(user_key)
            if name not in doc["keys"]:
                return False
            del doc["keys"][name]
            self._write(user_key, doc)
            return True

    def resolve(self, user_key: str, names: Iterable[str]) -> dict[str, str]:
        """The values for the KNOWN names among *names* — the only method that
        returns values. Unknown names are omitted so the sandbox can name them.
        Fail-open: a missing or unreadable store resolves to nothing (the run
        then fails inside the sandbox with the key named, like dataset paths)."""
        wanted = []
        for name in names or ():
            try:
                wanted.append(normalize_name(name))
            except ConnectionKeyError:
                continue
        if not wanted:
            return {}
        try:
            doc = self._read(user_key)
        except ConnectionKeyError:
            return {}
        out: dict[str, str] = {}
        for name in wanted:
            entry = doc["keys"].get(name)
            if isinstance(entry, dict) and isinstance(entry.get("value"), str):
                out[name] = entry["value"]
        if out:
            self._touch(user_key, list(out))
        return out

    def _touch(self, user_key: str, names: list[str]) -> None:
        """Best-effort ``lastUsedAt`` — never blocks or fails an execution."""
        try:
            with self._locked(user_key):
                doc = self._read(user_key)
                now = time.time()
                changed = False
                for name in names:
                    entry = doc["keys"].get(name)
                    if isinstance(entry, dict):
                        entry["lastUsedAt"] = now
                        changed = True
                if changed:
                    self._write(user_key, doc)
        except Exception:  # pragma: no cover - a stat, not a contract
            log.debug("connection-keys lastUsedAt update skipped for %s", user_key, exc_info=True)


_DEFAULT_STORE: ConnectionKeyStore | None = None


def default_store() -> ConnectionKeyStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = ConnectionKeyStore()
    return _DEFAULT_STORE
