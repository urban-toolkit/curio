"""Redact secret values out of text before it is stored or shown (dev/116).

Lives in ``utk_curio.common`` because BOTH the backend and the sandbox call
it and neither may import the other.

A connection key (``users/connection_keys.py``) exists in three places at run
time — the 0600 store, the execution request in flight, the sandbox namespace
closure — and must not gain a fourth by being *printed*: node stdout/stderr
ride the ``/exec`` response into the runtime journal, the validation runner's
tails, the Solve card and the review card. ``redact`` is the ONE helper every
such boundary calls with exactly the values that execution (or probe) was
handed — never a global scan, never a heuristic.
"""

from __future__ import annotations

from typing import Mapping

#: Values shorter than this are not redacted: replacing "abc" everywhere would
#: mangle ordinary text, and a 7-character "key" is not a credential.
MIN_REDACT_CHARS = 8

REDACTED_TEMPLATE = "«redacted:{name}»"


def redact(text: str | None, values: Mapping[str, str] | None) -> str | None:
    """Replace every occurrence of each value in *values* with
    ``«redacted:<name>»``. Longest values first, so a value that contains
    another is replaced whole. ``None`` passes through; an empty mapping is a
    no-op."""
    if text is None or not values:
        return text
    if not isinstance(text, str):
        return text
    ordered = sorted(
        ((name, value) for name, value in values.items()
         if isinstance(value, str) and len(value) >= MIN_REDACT_CHARS),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    out = text
    for name, value in ordered:
        if value in out:
            out = out.replace(value, REDACTED_TEMPLATE.format(name=name))
    return out


def redact_all(texts: Mapping[str, str | None], values: Mapping[str, str] | None) -> dict:
    """``redact`` over a mapping of named texts (a response's stdout/stderr)."""
    return {key: redact(text, values) for key, text in texts.items()}
