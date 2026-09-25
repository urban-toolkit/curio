"""The ``curio_secret("<name>")`` callable injected into a node's namespace
(memo dev/116, DEC-074) — the sandbox half of per-user connection keys.

The backend resolves the names that appear in the code and sends the values
in the ``/exec`` request as ``secrets: {name: value}``. Here they become ONE
callable in the exec namespace and nothing else: never an environment
variable (node code can read ``os.environ``), never a file in scratch, never
a log line. Both execution modes — the in-process worker and the isolated
child — use these two helpers so the contract has one home.
"""

from __future__ import annotations

import re
import types

#: Mirrors ``users/connection_keys.NAME_RE`` on the backend.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_SECRETS = 8
MAX_VALUE_CHARS = 4096

MISSING_TEMPLATE = (
    "No connection key named '{name}' is saved for this account - save one "
    "under Settings > Connection keys (its host, and the key itself), then "
    "run this node again. Node code reaches it only as curio_secret('{name}')."
)


def shape_secrets(raw) -> dict[str, str]:
    """Defensive re-shaping of the request field: a dict of valid names to
    single-line string values, bounded. Anything else is dropped silently —
    the node then fails with the key named, never with a shape error."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for name, value in raw.items():
        if len(out) >= MAX_SECRETS:
            break
        if not isinstance(name, str) or not NAME_RE.match(name):
            continue
        if not isinstance(value, str) or not value or len(value) > MAX_VALUE_CHARS:
            continue
        out[name] = value
    return out


class _SecretResolver:
    """``curio_secret(name) -> str``. A class with ``__slots__`` and a
    read-only mapping so the values are not one attribute lookup away in a
    debugger dump; the hard boundary stays the process/uid one."""

    __slots__ = ("_values",)

    def __init__(self, values: dict[str, str]):
        self._values = types.MappingProxyType(dict(values))

    def __call__(self, name) -> str:
        value = self._values.get(str(name))
        if value is None:
            raise RuntimeError(MISSING_TEMPLATE.format(name=name))
        return value

    def __repr__(self) -> str:  # never the values
        return f"<curio_secret: {len(self._values)} key(s)>"


def make_curio_secret(secrets) -> _SecretResolver:
    return _SecretResolver(shape_secrets(secrets))
