"""The manifest exchanged between the sandbox parent and an isolated child.

This module is the trust boundary. Everything a child sends back is written by
a process that just executed hostile-by-assumption user code, so the parent
treats it as attacker-controlled input and validates it here before acting on
any of it.

Two rules shape the design:

**JSON only, never pickle.** The obvious way to return a DataFrame from a child
is ``pickle``, and it would be a straight path back to the privilege we just
removed: ``pickle.loads`` executes constructor code chosen by whoever wrote the
stream. The manifest therefore carries only a kind tag, JSON scalars, and
*filenames*. Real payloads travel as parquet or JSON files in the scratch
directory, and the parent moves those bytes into the artifact store without
parsing them.

**Filenames, not paths.** A child that could name ``../../instance/urban_workflow.db``
or ``/etc/passwd`` as its output would turn the parent's own store-write into an
arbitrary file read. ``validate_scratch_filename`` accepts a single flat
filename and nothing else; the parent joins it to the scratch directory itself
and re-checks containment.

Both directions use the same module so the two sides cannot drift.
"""

import json
import os
import re


class ProtocolError(ValueError):
    """A manifest was malformed, oversized, or tried to escape the scratch dir.

    Raised by the parent. Callers turn it into a node failure reported in
    ``stderr`` like any other, never a 500.
    """


# ---------------------------------------------------------------------------
# Input specs: parent -> child
#
# Asymmetric with the response on purpose. The parent is trusted by the child,
# so the child parses these without validation; the parent is *not* trusted by
# the child's output, which is why everything below the response section is
# defensive. Keeping both shapes in one file is what stops them drifting.
#
# The parent stages real payloads as files in the child's scratch directory and
# names them here, so the child rebuilds ``arg`` without ever opening DuckDB:
#
#   {"kind": "none"}                       no input wired to this node
#   {"kind": "null"}
#   {"kind": "bool"|"int"|"float"|"str", "value": ...}
#   {"kind": "json", "file": "in_0.json"}                       list or dict
#   {"kind": "dataframe", "file": "in_0.parquet",
#    "encoded_object_columns": [...]}
#   {"kind": "geodataframe", "file": "in_0.parquet",
#    "encoded_object_columns": [...], "frame_metadata": {...}}
#   {"kind": "raster", "file": "in_0.tif"}
#   {"kind": "sequence", "container": "list"|"tuple", "items": [spec, ...]}
#   {"kind": "mapping", "items": {"key": spec, ...}}
#
# 'sequence' with container 'tuple' is how an upstream merge ('outputs') and a
# stored tuple both arrive; the child rebuilds the right container so user code
# sees exactly what the in-process path would have handed it.
# ---------------------------------------------------------------------------

INPUT_NONE = {"kind": "none"}

INPUT_KINDS = frozenset({
    "none", "null", "bool", "int", "float", "str",
    "json", "dataframe", "geodataframe", "raster", "sequence", "mapping",
})


# The kinds a node output may carry. Mirrors codec.detect_kind's return values.
# 'unknown' is deliberately absent: detect_kind returns it for objects Curio
# cannot store, and save_to_duckdb already raises on them, so a child claiming
# 'unknown' is either confused or probing.
VALID_KINDS = frozenset({
    "null", "bool", "int", "float", "str",
    "list", "dict", "dataframe", "geodataframe", "raster", "outputs",
})

# Kinds whose payload is a file in the scratch directory rather than an inline
# JSON value. Everything else must be inline and small.
FILE_BACKED_KINDS = frozenset({"dataframe", "geodataframe", "raster", "list", "dict"})

# A flat filename: no directory separators, no parent refs, no leading dot.
# The parent joins this to the scratch dir itself, so anything that could
# change the meaning of that join is rejected outright.
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Caps. These bound the parent's own work on a hostile manifest; they are not
# a substitute for the child's rlimits, which bound the child itself.
#
# The envelope cap must stay comfortably above the sum of the field caps, or a
# node that legitimately prints a lot would have its whole manifest rejected
# instead of having its output truncated. Worst case below is roughly
# 10 MB of stdout plus 256 KiB of stderr, against a 16 MiB envelope.
MAX_MANIFEST_BYTES = 16 << 20         # hard backstop against a runaway child
MAX_STDOUT_LINES = 5_000
MAX_STDOUT_LINE_CHARS = 2_000
MAX_STDERR_CHARS = 256 << 10
MAX_OUTPUTS_ITEMS = 256               # tuple fan-out from one node
MAX_INLINE_STRING_CHARS = 1 << 20
MAX_IMPORT_STATEMENTS = 128
MAX_IMPORT_STATEMENT_CHARS = 500


def validate_scratch_filename(name):
    """Return *name* if it is a safe flat filename, else raise ProtocolError.

    Rejects absolute paths, anything containing a separator, ``..``, NUL, and
    names that are empty or over-long. Note this does not touch the
    filesystem: :func:`resolve_in_scratch` does the containment check once the
    parent knows the scratch directory.
    """
    if not isinstance(name, str):
        raise ProtocolError(f"filename must be a string, got {type(name).__name__}")
    if not _SAFE_FILENAME.match(name):
        raise ProtocolError(f"unsafe filename in child manifest: {name!r}")
    # Belt and braces: the regex already excludes these, but this is the check
    # a future edit to the pattern must not silently drop.
    if name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise ProtocolError(f"unsafe filename in child manifest: {name!r}")
    return name


def resolve_in_scratch(scratch_dir, name):
    """Join *name* to *scratch_dir*, proving the result stays inside it.

    Defends against the case the filename check alone cannot see: a symlink
    the child dropped in the scratch directory pointing somewhere else. The
    real path of the result must still be under the real scratch directory.
    """
    validate_scratch_filename(name)
    root = os.path.realpath(scratch_dir)
    candidate = os.path.realpath(os.path.join(root, name))
    if candidate != root and not candidate.startswith(root + os.sep):
        raise ProtocolError(
            f"child manifest names a file outside its scratch directory: {name!r}"
        )
    return candidate


def _check_inline_value(kind, value):
    """Validate an inline (non file-backed) payload for *kind*."""
    if kind == "null":
        if value is not None:
            raise ProtocolError("kind 'null' must carry a null value")
        return None
    if kind == "bool":
        if not isinstance(value, bool):
            raise ProtocolError(f"kind 'bool' carried {type(value).__name__}")
        return value
    if kind == "int":
        # bool is an int subclass; a bool here means the child mislabelled it.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProtocolError(f"kind 'int' carried {type(value).__name__}")
        return value
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProtocolError(f"kind 'float' carried {type(value).__name__}")
        return float(value)
    if kind == "str":
        if not isinstance(value, str):
            raise ProtocolError(f"kind 'str' carried {type(value).__name__}")
        if len(value) > MAX_INLINE_STRING_CHARS:
            raise ProtocolError("inline string payload exceeds the size cap")
        return value
    raise ProtocolError(f"kind {kind!r} has no inline representation")


def validate_payload(payload, *, _depth=0):
    """Validate one output descriptor, recursing into ``outputs`` bundles.

    Returns the normalized descriptor. Raises :class:`ProtocolError` on
    anything the parent should not act on.
    """
    if _depth > 2:
        # A tuple of tuples of tuples is not a shape Curio produces, and
        # unbounded recursion here is a denial-of-service on the parent.
        raise ProtocolError("output nesting is too deep")
    if not isinstance(payload, dict):
        raise ProtocolError(f"output descriptor must be an object, got {type(payload).__name__}")

    kind = payload.get("kind")
    if kind not in VALID_KINDS:
        raise ProtocolError(f"unknown output kind: {kind!r}")

    if kind == "outputs":
        items = payload.get("items")
        if not isinstance(items, list):
            raise ProtocolError("kind 'outputs' must carry an items list")
        if len(items) > MAX_OUTPUTS_ITEMS:
            raise ProtocolError(
                f"outputs bundle has {len(items)} items, over the {MAX_OUTPUTS_ITEMS} cap"
            )
        return {
            "kind": "outputs",
            "items": [validate_payload(item, _depth=_depth + 1) for item in items],
        }

    if kind in FILE_BACKED_KINDS:
        name = payload.get("file")
        if name is None:
            raise ProtocolError(f"kind {kind!r} must name a file")
        validate_scratch_filename(name)
        result = {"kind": kind, "file": name}
        meta = payload.get("meta")
        if meta is not None:
            if not isinstance(meta, (dict, list)):
                raise ProtocolError("output meta must be an object or array")
            result["meta"] = meta
        return result

    return {"kind": kind, "value": _check_inline_value(kind, payload.get("value"))}


def _validate_stdout(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProtocolError("stdout must be a list of strings")
    if len(raw) > MAX_STDOUT_LINES:
        raw = raw[:MAX_STDOUT_LINES]
    lines = []
    for line in raw:
        if not isinstance(line, str):
            raise ProtocolError("stdout entries must be strings")
        lines.append(line[:MAX_STDOUT_LINE_CHARS])
    return lines


def _validate_imports(raw):
    """Import statements the child reports as having succeeded.

    These are replayed verbatim in a later child's prologue, so they are code.
    Restrict them to what the hoister can produce: a single-line ``import`` or
    ``from ... import ...`` statement, with no separators that would let a
    second statement ride along.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProtocolError("imports must be a list of strings")
    statements = []
    for statement in raw[:MAX_IMPORT_STATEMENTS]:
        if not isinstance(statement, str):
            raise ProtocolError("import entries must be strings")
        if len(statement) > MAX_IMPORT_STATEMENT_CHARS:
            raise ProtocolError("import statement exceeds the size cap")
        if "\n" in statement or "\r" in statement or ";" in statement:
            raise ProtocolError(f"import statement is not a single statement: {statement!r}")
        if not (statement.startswith("import ") or statement.startswith("from ")):
            raise ProtocolError(f"not an import statement: {statement!r}")
        statements.append(statement)
    return statements


def parse_child_result(raw, *, scratch_dir=None):
    """Parse and validate the JSON a child wrote back.

    *raw* is the raw text (or bytes) of the manifest. When *scratch_dir* is
    given, every file-backed payload is additionally resolved and checked for
    containment, which is the check that catches a planted symlink.

    Returns a dict with keys ``ok``, ``stdout``, ``stderr``, ``output`` and
    ``imports``. Raises :class:`ProtocolError` for anything malformed.
    """
    if isinstance(raw, bytes):
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ProtocolError("child manifest exceeds the size cap")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            # A pickle stream lands here: it is binary and not valid UTF-8.
            raise ProtocolError(f"child manifest is not UTF-8 text: {exc}") from exc
    if not isinstance(raw, str):
        raise ProtocolError(f"child manifest must be text, got {type(raw).__name__}")
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ProtocolError("child manifest exceeds the size cap")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"child manifest is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ProtocolError("child manifest must be a JSON object")

    stderr = payload.get("stderr") or ""
    if not isinstance(stderr, str):
        raise ProtocolError("stderr must be a string")
    stderr = stderr[:MAX_STDERR_CHARS]

    result = {
        "ok": bool(payload.get("ok")),
        "stdout": _validate_stdout(payload.get("stdout")),
        "stderr": stderr,
        "imports": _validate_imports(payload.get("imports")),
        "output": None,
    }

    if result["ok"]:
        output = payload.get("output")
        if output is None:
            raise ProtocolError("a successful child manifest must carry an output")
        result["output"] = validate_payload(output)
        if scratch_dir is not None:
            _resolve_files(result["output"], scratch_dir)

    return result


def _resolve_files(descriptor, scratch_dir):
    """Attach a checked absolute path to every file-backed descriptor."""
    if descriptor["kind"] == "outputs":
        for item in descriptor["items"]:
            _resolve_files(item, scratch_dir)
        return
    if "file" in descriptor:
        descriptor["path"] = resolve_in_scratch(scratch_dir, descriptor["file"])


def build_exec_request(
    *,
    code,
    node_type,
    data_type,
    scratch_dir,
    input_spec,
    dataset_paths=None,
    session_imports=None,
    limits=None,
    wall_timeout=None,
):
    """Assemble the request the parent hands to the zygote.

    Kept here beside the response parser so the two halves of the wire format
    stay in one file.

    ``wall_timeout`` is enforced by the zygote, not by the parent. The zygote is
    the child's parent process, so while it holds an unreaped child the pid
    cannot be recycled and a kill is guaranteed to hit the right process. The
    sandbox killing a pid it does not own would race pid reuse and could signal
    something else entirely.
    """
    return {
        "code": code,
        "node_type": node_type,
        "data_type": data_type,
        "scratch_dir": str(scratch_dir),
        "input": input_spec,
        "dataset_paths": dict(dataset_paths or {}),
        "session_imports": list(session_imports or []),
        "limits": dict(limits or {}),
        "wall_timeout": wall_timeout,
    }


def encode_request(request):
    """Serialize a request for the pipe. Compact, single line, UTF-8."""
    return json.dumps(request, separators=(",", ":")).encode("utf-8")


def decode_request(raw):
    """Child side: parse the request the parent sent.

    The child trusts the parent, so this is a plain parse. The asymmetry is
    deliberate and is the whole point of the boundary.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)
