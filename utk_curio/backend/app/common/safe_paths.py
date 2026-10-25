"""Path-safety primitives used everywhere Curio composes a filesystem path
from untrusted input.

Threat model
------------
Any string that originates (directly or indirectly) from an HTTP request,
a workflow spec, a saved manifest, an environment variable that a user can
influence, or any other non-hard-coded source is **untrusted**. Joining such
a string naively onto a base directory lets an attacker read or clobber
files outside Curio's sandbox via classic path-traversal payloads:

- ``"../../etc/passwd"`` — ``..`` segments walking above the base.
- ``"subdir/../../../etc/shadow"`` — traversal buried mid-path.
- ``"foo\x00.txt"`` — NUL byte truncation tricks on C bindings.
- ``"foo/bar"`` when a single segment is expected — silently creates
  nested directories the caller didn't intend.
- Symlinks that already live on disk and point outside the base.
- Prefix-matching false positives (e.g. ``/tmp/data`` vs ``/tmp/data-evil``
  under a naive ``str.startswith`` check).

Any code in Curio that builds a path from untrusted input MUST route the
untrusted segments through this module before touching the filesystem.
Routing everything through one chokepoint gives us:

* a single place to audit,
* uniform error behaviour (:class:`PathTraversalError`, a
  :class:`PermissionError` subclass), and
* consistent error messages — every rejection is prefixed with
  ``"Path traversal blocked"`` so tests and log parsers can assert on a
  single stable token.

Two layers of defence
---------------------
1. **Component validation** (primary) — :func:`validate_component` rejects
   each individual segment *before any syscall happens* if it contains
   ``..`` / ``.`` reserved names, forward or backward slashes, NUL bytes,
   control characters, is empty/non-string, or contains characters outside
   ``[A-Za-z0-9._-]``. Catching traversal up front is cheap and never
   depends on filesystem state.

2. **Containment check** (belt-and-braces) — :func:`is_within` verifies the
   final resolved path is inside the resolved base using
   :meth:`pathlib.PurePath.relative_to` (proper path-segment semantics, not
   string prefix matching). This catches symlink escapes and anything the
   component check missed — and remains safe even if callers opt out of
   validation.

Which helper should I use?
--------------------------
+--------------------------------+-----------------------------------------+
| Situation                      | Helper                                  |
+================================+=========================================+
| Single untrusted segment under | ``safe_child(base, name)``              |
| a trusted base                 |                                         |
+--------------------------------+-----------------------------------------+
| Multiple segments, any mix of  | ``safe_join(base, *parts)``             |
| literal + untrusted            |                                         |
+--------------------------------+-----------------------------------------+
| Validate an identifier without | ``validate_component(value)``           |
| building a path                |                                         |
+--------------------------------+-----------------------------------------+
| Ad-hoc "is X inside Y?" check  | ``is_within(x, y)``                     |
+--------------------------------+-----------------------------------------+

Examples
--------
Happy path::

    >>> from utk_curio.backend.app.common.safe_paths import safe_join
    >>> safe_join("/srv/curio/users", "42", "projects", "abc-123")
    PosixPath('/srv/curio/users/42/projects/abc-123')

Traversal is rejected up front::

    >>> safe_join("/srv/curio/users", "42", "projects", "../../etc")
    Traceback (most recent call last):
      ...
    PathTraversalError: Path traversal blocked: path component contains a
    path separator: '../../etc'

Symlink escape is still caught even if the caller skips per-segment
validation::

    >>> # /srv/curio/users/evil -> /etc
    >>> safe_join("/srv/curio/users", "evil", "passwd", validate=False)
    Traceback (most recent call last):
      ...
    PathTraversalError: Path traversal blocked: resolved path /etc/passwd
    escapes base /srv/curio/users

Migration notes
---------------
When migrating a call site, prefer :func:`safe_join` over manual
``Path(base) / untrusted`` + ``startswith`` checks. See
``utk_curio/backend/app/projects/storage.py`` and the ``/get`` handler in
``utk_curio/backend/app/api/routes.py`` for canonical usages.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Union

__all__ = [
    "PathTraversalError",
    "validate_component",
    "safe_join",
    "safe_child",
    "is_within",
]


class PathTraversalError(PermissionError):
    """Raised when an unsafe path segment or an escape from the base is detected.

    Subclasses :class:`PermissionError` so existing handlers that catch
    :class:`PermissionError` (including legacy Curio code paths and the
    ``test_path_traversal_blocked`` regression test) continue to work
    without modification.

    Every message produced by this module is prefixed with the fixed token
    ``"Path traversal blocked"`` so log/test assertions can pivot on a
    single word rather than fragile substring matches.
    """


# Rules for a "safe" single segment:
#   - first character: letter or digit (forbid leading '.', '-', '_')
#   - subsequent characters: letters, digits, '.', '_', '-'
#   - total length: 1..255 characters
# The explicit ``_RESERVED_NAMES`` check below still rejects bare "." / ".."
# even though they'd otherwise fail the leading-char rule — we want a clear,
# purpose-built error message for those.
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_RESERVED_NAMES = {".", ".."}


def _reject(reason: str) -> None:
    """Internal: raise :class:`PathTraversalError` with the canonical prefix."""
    raise PathTraversalError(f"Path traversal blocked: {reason}")


def validate_component(value: object, *, field: str = "path component") -> str:
    """Validate that *value* is a safe single path segment.

    This is the primary defence: it runs before any filesystem lookup and
    is cheap enough to call on every user-controlled identifier that will
    later be interpolated into a path (project ids, filenames, template
    names, etc.).

    Accepted
        Non-empty strings of 1..255 characters matching
        ``^[A-Za-z0-9][A-Za-z0-9._-]*$``.

    Rejected (each with its own specific error message)
        - ``None`` / non-string types
        - empty strings
        - the reserved names ``"."`` and ``".."``
        - any NUL byte (``"\\x00"``)
        - forward or backward slashes (path separators)
        - anything outside the allowed charset (including whitespace,
          control characters, Unicode punctuation, emoji, etc.)

    Parameters
    ----------
    value:
        The candidate segment to validate. Typed as ``object`` so callers
        can pass values straight from ``request.args.get`` / JSON payloads
        without pre-casting.
    field:
        Human-readable label used to build the error message (e.g.
        ``"project_id"``, ``"output filename"``). Defaults to
        ``"path component"``.

    Returns
    -------
    str
        *value* unchanged on success. The return type is narrowed to
        :class:`str` so callers can use the result directly.

    Raises
    ------
    PathTraversalError
        If *value* fails any of the rules above.

    Examples
    --------
    >>> validate_component("abc-123.data")
    'abc-123.data'
    >>> validate_component("../etc", field="project_id")
    Traceback (most recent call last):
      ...
    PathTraversalError: Path traversal blocked: project_id contains a path
    separator: '../etc'
    """
    if not isinstance(value, str):
        _reject(f"{field} must be a string, got {type(value).__name__}")
    if not value:
        _reject(f"{field} is empty")
    if value in _RESERVED_NAMES:
        _reject(f"{field} is a reserved name: {value!r}")
    if "\x00" in value:
        _reject(f"{field} contains a NUL byte")
    if "/" in value or "\\" in value:
        _reject(f"{field} contains a path separator: {value!r}")
    if not _SAFE_COMPONENT_RE.match(value):
        _reject(f"{field} has unsafe characters: {value!r}")
    return value  # type: ignore[return-value]


def is_within(path: Path, base: Path) -> bool:
    """Return ``True`` iff *path* is the same as, or nested inside, *base*.

    Uses :meth:`pathlib.PurePath.relative_to` (path-segment semantics), so
    unlike a naive ``str(path).startswith(str(base))`` check:

    - ``/tmp/data`` is **not** considered inside ``/tmp/data-other`` (no
      prefix-match false positives); and
    - both arguments are ``resolve()``\\ 'd first, so symlinks are followed
      and ``..`` segments are collapsed before the comparison.

    Use this as a last-line defence after composing a path from untrusted
    input, or as a standalone check ("is this file under the shared data
    dir?") when you already have an absolute path.

    Parameters
    ----------
    path, base:
        Any :class:`pathlib.Path` (absolute or relative — both are resolved
        against the process CWD).

    Returns
    -------
    bool
        ``True`` if ``path.resolve()`` is equal to or a descendant of
        ``base.resolve()``; ``False`` otherwise.

    Notes
    -----
    Does not raise on non-existent paths — ``Path.resolve()`` on a missing
    path returns the absolute form without touching the filesystem for the
    tail segments, which is exactly what we want for a pre-flight check.
    """
    resolved = path.resolve()
    resolved_base = base.resolve()
    try:
        resolved.relative_to(resolved_base)
        return True
    except ValueError:
        return False


def safe_join(
    base: Union[str, Path],
    *parts: str,
    validate: bool = True,
    field: str = "path component",
) -> Path:
    """Join *parts* under *base* and guarantee the result stays inside *base*.

    This is the workhorse of the module. It is the recommended way to build
    any filesystem path that mixes a trusted base with untrusted segments.
    The function applies both defences:

    1. If *validate* is ``True`` (the default), each of *parts* is run
       through :func:`validate_component`. Traversal payloads are rejected
       before any syscall runs.
    2. The joined path is then ``resolve()``\\ 'd and checked with
       :func:`is_within`. This step **always** runs, even when
       ``validate=False``, and catches symlink escapes plus anything the
       segment check missed.

    Parameters
    ----------
    base:
        Trusted root directory. Must be hard-coded, derived from trusted
        configuration, or itself the output of an earlier ``safe_join``.
        It is ``resolve()``\\ 'd before the containment check.
    *parts:
        Zero or more path segments to append to *base*. A mix of literal
        strings (``"projects"``) and untrusted values (a user-supplied
        project id) is fine — when ``validate=True`` the literal segments
        pass trivially because they match the safe charset.
    validate:
        When ``True`` (default), validate every segment in *parts* with
        :func:`validate_component`. Set to ``False`` **only** when either:

        - the segments have already been validated by the caller (to avoid
          double work), or
        - the endpoint historically accepted nested relative paths and
          tightening to single-segment validation would break clients
          (see the ``/get`` and ``/get-preview`` handlers in
          ``app/api/routes.py``).

        The final containment check runs regardless, so opting out still
        leaves the escape-proof guarantee intact.
    field:
        Human-readable label used in component-level error messages.

    Returns
    -------
    pathlib.Path
        The fully-resolved absolute path. Guaranteed to satisfy
        ``is_within(returned_path, Path(base).resolve())``.

    Raises
    ------
    PathTraversalError
        - A segment fails :func:`validate_component` (when ``validate`` is
          ``True``), or
        - the resolved target escapes *base* (always).

    Examples
    --------
    Typical usage — trusted literals + one untrusted segment::

        return safe_join(
            users_base,            # trusted
            str(int(user_id)),     # trusted (coerced to digits)
            "projects",            # trusted literal
            project_id,            # UNTRUSTED — validated here
            field="project_id",
        )

    Skipping per-segment validation for a legacy endpoint that still wants
    the containment guarantee::

        try:
            full_path = safe_join(
                base_path, file_name, validate=False, field="fileName",
            )
        except PathTraversalError as exc:
            return f"Invalid file path: {exc}", 403
    """
    base_path = Path(base).resolve()
    if validate:
        for part in parts:
            validate_component(part, field=field)
    target = base_path.joinpath(*parts).resolve()
    if not is_within(target, base_path):
        _reject(f"resolved path {target!s} escapes base {base_path!s}")
    return target


def safe_child(base: Union[str, Path], name: str, *, field: str = "name") -> Path:
    """Resolve a single untrusted child *name* under *base*.

    Thin convenience wrapper around :func:`safe_join` for the very common
    "one user-supplied segment under a trusted directory" case. The name
    is always validated with :func:`validate_component`.

    Parameters
    ----------
    base:
        Trusted root directory.
    name:
        Untrusted single-segment name (e.g. a project id, a filename).
    field:
        Error-message label; defaults to ``"name"``.

    Returns
    -------
    pathlib.Path
        Resolved absolute path, guaranteed to be inside *base*.

    Raises
    ------
    PathTraversalError
        If *name* is unsafe or the resolved target escapes *base*.
    """
    return safe_join(base, name, field=field)
