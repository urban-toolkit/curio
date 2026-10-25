"""Calls that go to the sandbox directly: its token and URL, reading an artifact
back, and running a dataflow's code nodes without a browser.
"""

import os
import json
import textwrap
from pathlib import Path
# import zlib
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from ..workflow_spec import seed_node_code
from .environment import REPO_ROOT, _backend_base_url_for_config


SANDBOX_CONNECT_TIMEOUT_S = 30
SANDBOX_GET_TIMEOUT_S = int(os.environ.get("CURIO_E2E_SANDBOX_GET_TIMEOUT", "300"))



def get_shared_data_dir() -> str:
    """Directory where Curio writes its DuckDB artifact store.

    Matches ``utk_curio/sandbox/util/db.py`` (``CURIO_LAUNCH_CWD`` +
    ``CURIO_SHARED_DATA``). Defaults ``CURIO_LAUNCH_CWD`` to the repo root
    so host-side Playwright resolves the same path as ``curio start`` when the
    subprocess uses ``cwd`` = repo root (and matches Docker once ``./.curio`` is
    bind-mounted to ``/app/.curio``).

    The directory holds ``curio_data.duckdb``;
    """
    launch_dir = Path(
        os.environ.get("CURIO_LAUNCH_CWD", REPO_ROOT)
    ).resolve()
    shared_disk_path = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    lod_dir = (launch_dir / Path(shared_disk_path)).resolve()
    return str(lod_dir)


# ---------------------------------------------------------------------------
# .data file helpers (zlib-compressed JSON, same format as parsers.py)
# ---------------------------------------------------------------------------

# def load_dot_data(path: str) -> dict:
#     """Read a ``.data`` file (zlib-compressed JSON) and return the parsed dict."""
#     with open(path, "rb") as f:
#         return json.loads(zlib.decompress(f.read()).decode("utf-8"))


# def save_dot_data(path: str, data: dict) -> None:
#     """Write *data* as zlib-compressed JSON to *path*."""
#     os.makedirs(os.path.dirname(path), exist_ok=True)
#     compressed = zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))
#     with open(path, "wb") as f:
#         f.write(compressed)


# def strip_volatile_keys(data: dict) -> dict:
#     """Return a shallow copy of *data* without per-run metadata (``filename``)."""
#     stripped = {**data}
#     stripped.pop("filename", None)
#     return stripped

# ---------------------------------------------------------------------------
# DuckDB artifact helpers
# ---------------------------------------------------------------------------

def sandbox_auth_header() -> dict:
    """Header proving to the sandbox that a caller may use its guarded routes.

    /exec, /execJs, /get and /install require a shared secret rather than a
    user token (utk_curio/sandbox/app/auth.py); the backend attaches the same
    one in ``_sandbox_call``. Empty when unset, matching the sandbox's
    unauthenticated local-dev mode.
    """
    token = os.environ.get('CURIO_SANDBOX_TOKEN', '').strip()
    return {'X-Curio-Sandbox-Token': token} if token else {}


def sandbox_base_url() -> str:
    """``http://host:port`` for the sandbox these tests should talk to.

    A couple of helpers below bypass the backend and call the sandbox directly
    (deliberately - DuckDB wants a single writer). They used to read only
    ``FLASK_SANDBOX_PORT``, which nothing sets in the ``CURIO_E2E_USE_EXISTING``
    path: ``e2e_existing_servers`` honours ``CURIO_E2E_SANDBOX_PORT`` and that
    is the variable the README documents. So on any non-default port the direct
    callers silently addressed **port 2000** - some other session's sandbox, or
    nothing - and the failure surfaced as an unexplained ``401`` from a URL the
    test never mentioned.

    Precedence, most specific first:

    1. ``CURIO_E2E_SANDBOX_PORT`` / ``CURIO_E2E_HOST`` - the documented knobs
       for "test the servers already running".
    2. ``FLASK_SANDBOX_PORT`` / ``FLASK_SANDBOX_HOST`` - what ``curio.py start``
       exports into the sandbox's own process, and what
       ``test_large_dataframe_e2e`` sets for the children it spawns.
    3. The stock ``127.0.0.1:2000``.
    """
    host = (
        os.environ.get('CURIO_E2E_HOST')
        or os.environ.get('FLASK_SANDBOX_HOST')
        or '127.0.0.1'
    )
    port = (
        os.environ.get('CURIO_E2E_SANDBOX_PORT')
        or os.environ.get('FLASK_SANDBOX_PORT')
        or '2000'
    )
    return f'http://{host}:{int(port)}'


def _explain_sandbox_auth_failure(resp, route: str) -> None:
    """Turn a sandbox 401/403 into the sentence that actually unblocks you.

    The guarded routes answer 401 when the shared secret does not match, and
    nothing in the response says which secret it wanted. In the use-existing
    path the running stack minted its own token unless the operator pinned one,
    so "export the same CURIO_SANDBOX_TOKEN the stack was started with" is the
    fix roughly every time - and it is not guessable from the status line.
    """
    if resp.status_code not in (401, 403):
        return
    have = 'set' if os.environ.get('CURIO_SANDBOX_TOKEN', '').strip() else 'UNSET'
    raise AssertionError(
        f"sandbox {route} -> {resp.status_code}: the shared secret was rejected. "
        f"CURIO_SANDBOX_TOKEN is {have} in this pytest process, and the sandbox "
        f"at {sandbox_base_url()} expects the value it was started with. "
        "Start the stack with an explicit CURIO_SANDBOX_TOKEN and export the "
        "same one here (curio.py start mints a random one otherwise)."
    )


def load_artifact_as_dict(artifact_id: str) -> dict:
    """Fetch a stored artifact from the sandbox and return its parsed representation."""
    import requests as _req
    resp = _req.get(
        f'{sandbox_base_url()}/get',
        params={'fileName': artifact_id},
        headers=sandbox_auth_header(),
        timeout=(SANDBOX_CONNECT_TIMEOUT_S, SANDBOX_GET_TIMEOUT_S),
    )
    _explain_sandbox_auth_failure(resp, f'/get fileName={artifact_id}')
    if not resp.ok:
        # Surface the sandbox's structured error body (added in api.py /get)
        # so pytest shows *why* the load failed.
        raise AssertionError(
            f"sandbox /get fileName={artifact_id} -> {resp.status_code}\n"
            f"{resp.text[:2000]}"
        )
    result = resp.json()
    # No `json.loads(json.dumps(result, default=str))` round-trip here. It was
    # a no-op that cost two extra copies of the whole artifact: `resp.json()`
    # has already parsed the body, so every value is JSON-native and `default`
    # can never fire. The largest example dataflow
    # (09-heterogeneous-data-linked-views) died with MemoryError *inside* that
    # round-trip - it holds the parsed object, the serialized string and the
    # re-parsed copy at once, on top of the programmatic run's expected map.
    result.pop('filename', None)  # artifact ID varies per execution run
    return result


# ---------------------------------------------------------------------------
# Two runs' outputs, compared without their JSON envelopes
# ---------------------------------------------------------------------------

#: Kinds whose value is a parquet table, which /get's Arrow route streams a
#: batch at a time.
_TABLE_KINDS = ("dataframe", "geodataframe")
#: Kinds stored as zlib-compressed JSON in a file ``value_str`` names, or as
#: JSON in ``value_json`` in older rows.
_JSON_KINDS = ("list", "dict")
#: Kinds that only name other artifacts, in ``value_json``: a tuple's values,
#: or a list or dict whose values are frames.
_PARENT_KINDS = ("outputs", "list_of_ids", "dict_of_ids")
#: Kinds whose whole value is one column of the stored row.
_ROW_COLUMNS = {
    "null": None,
    "bool": "value_int",
    "int": "value_int",
    "float": "value_float",
    "str": "value_str",
    "raster": "value_str",
}
#: The Arrow route's headers that say what a table is. X-Curio-Filename is
#: left out: it names the artifact, so it differs between any two.
_TABLE_HEADERS = (
    "X-Curio-Kind",
    "X-Curio-Rows",
    "X-Curio-Schema",
    "X-Curio-Encoded-Object-Columns",
    "X-Curio-Frame-Metadata",
)
_ARROW_STREAM = "application/vnd.apache.arrow.stream"


def artifact_meta(artifact_id: str) -> dict:
    """The sandbox's stored row for an artifact (``/artifact-meta``): its kind,
    and where its value is, without reading the value."""
    import requests as _req
    resp = _req.get(
        f'{sandbox_base_url()}/artifact-meta',
        params={'fileName': artifact_id},
        headers=sandbox_auth_header(),
        timeout=(SANDBOX_CONNECT_TIMEOUT_S, SANDBOX_GET_TIMEOUT_S),
    )
    _explain_sandbox_auth_failure(resp, f'/artifact-meta fileName={artifact_id}')
    if not resp.ok:
        raise AssertionError(
            f"sandbox /artifact-meta fileName={artifact_id} -> {resp.status_code}\n"
            f"{resp.text[:2000]}"
        )
    return resp.json()


def _artifact_table(artifact_id: str):
    """A table artifact as /get's Arrow route streams it, with its headers."""
    import pyarrow as pa
    import requests as _req
    resp = _req.get(
        f'{sandbox_base_url()}/get',
        params={'fileName': artifact_id},
        headers={
            **sandbox_auth_header(),
            'Accept': _ARROW_STREAM,
            # A GeoDataFrame's geometry comes as WKB, which is only sent on request.
            'X-Curio-Accept-Geometry': 'wkb',
        },
        timeout=(SANDBOX_CONNECT_TIMEOUT_S, SANDBOX_GET_TIMEOUT_S),
    )
    _explain_sandbox_auth_failure(resp, f'/get (Arrow) fileName={artifact_id}')
    if not resp.ok:
        raise AssertionError(
            f"sandbox /get (Arrow) fileName={artifact_id} -> {resp.status_code}\n"
            f"{resp.text[:2000]}"
        )
    table = pa.ipc.open_stream(resp.content).read_all()
    headers = {name: resp.headers.get(name) for name in _TABLE_HEADERS}
    # A stream cut short still decodes, to fewer rows.
    if str(table.num_rows) != headers["X-Curio-Rows"]:
        raise AssertionError(
            f"sandbox /get (Arrow) fileName={artifact_id} streamed {table.num_rows} "
            f"rows of {headers['X-Curio-Rows']}"
        )
    return table, headers


def _stored_json(meta: dict) -> dict | None:
    """A list or dict artifact's stored JSON, by the digest of its bytes.

    The file is the sandbox's own, in the shared data directory this process
    sees too (``get_shared_data_dir``: the stack's ``.curio``). None when it is
    not there, as for a stack on another machine.
    """
    import hashlib
    if meta.get("value_str"):
        path = Path(get_shared_data_dir()) / meta["value_str"]
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return {"digest": digest.hexdigest(), "path": str(path)}
    text = meta.get("value_json") or ""
    return {"digest": hashlib.sha256(text.encode("utf-8")).hexdigest(), "inline": text}


def snapshot_artifact(artifact_id: str) -> dict:
    """What an artifact holds, read so two runs' outputs compare without its
    JSON envelope.

    ``load_artifact_as_dict`` asks ``/get`` for the envelope the canvas reads,
    where a list becomes one ``{"data", "dataType"}`` object per element, built
    in the sandbox and parsed again here. Example 09's grid of UTCI values took
    7.3 GiB in the sandbox and 8.5 GiB in pytest that way (#1154's runs). This
    reads the stored row (``/artifact-meta``) and then, by its kind:

    * a table: the Arrow route, which streams the stored parquet a batch at a
      time, kept as a pyarrow Table with the headers that describe it;
    * a list or dict: the digest of its stored JSON;
    * a tuple, or a list or dict of frames: each value it names, the same way;
    * anything else in the row: the row's value.

    A kind this does not know, or a JSON file this process cannot see, is read
    as the envelope, as before.
    """
    meta = artifact_meta(artifact_id)
    kind = meta.get("kind")
    if kind in _ROW_COLUMNS:
        column = _ROW_COLUMNS[kind]
        return {"kind": kind, "value": meta.get(column) if column else None}
    if kind in _TABLE_KINDS:
        table, headers = _artifact_table(artifact_id)
        return {"kind": kind, "table": table, "headers": headers}
    if kind in _PARENT_KINDS:
        named = json.loads(meta.get("value_json") or "[]")
        if isinstance(named, dict):
            return {"kind": kind, "parts": {key: snapshot_artifact(part) for key, part in named.items()}}
        return {"kind": kind, "parts": [snapshot_artifact(part) for part in named]}
    if kind in _JSON_KINDS:
        stored = _stored_json(meta)
        if stored is not None:
            return {"kind": kind, **stored}
    return {"kind": kind, "envelope": load_artifact_as_dict(artifact_id)}


def _same_value(a, b) -> bool:
    """Equal, with NaN equal to NaN, through nested lists and dicts."""
    if isinstance(a, float) and isinstance(b, float):
        return a == b or (a != a and b != b)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same_value(a[key], b[key]) for key in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same_value(x, y) for x, y in zip(a, b))
    return a == b


def _same_column(a, b) -> bool:
    """Two Arrow columns hold the same values, NaN equal to NaN, however chunked.

    pyarrow's own ``equals`` calls two NaNs different, where the JSON envelope
    sent both as null, so a float column with NaN in it is compared value by
    value instead.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    if a.equals(b):
        return True
    if a.type != b.type or len(a) != len(b):
        return False
    if pa.types.is_floating(a.type):
        if not pc.all(pc.equal(pc.is_null(a), pc.is_null(b))).as_py():
            return False
        # Null where either is null, and those places already match.
        same = pc.or_kleene(pc.equal(a, b), pc.and_kleene(pc.is_nan(a), pc.is_nan(b)))
        return pc.all(pc.fill_null(same, True)).as_py()
    # A nested type can carry floats too.
    return _same_value(a.to_pylist(), b.to_pylist())


def _parsed(raw):
    """A header or metadata value, as JSON when it is JSON."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _schema_metadata(table) -> dict:
    return {
        key.decode(): _parsed(value.decode())
        for key, value in (table.schema.metadata or {}).items()
    }


def _table_differences(actual: dict, expected: dict, where: str) -> list[str]:
    out = []
    for name in _TABLE_HEADERS:
        if _parsed(actual["headers"].get(name)) != _parsed(expected["headers"].get(name)):
            out.append(f"{where}: {name} is {actual['headers'].get(name)!r}, "
                       f"expected {expected['headers'].get(name)!r}")
    a, e = actual["table"], expected["table"]
    if a.schema.names != e.schema.names:
        return out + [f"{where} has the columns {a.schema.names}, expected {e.schema.names}"]
    if not a.schema.equals(e.schema):
        out.append(f"{where}: the column types differ ({a.schema} against {e.schema})")
        return out
    if not _same_value(_schema_metadata(a), _schema_metadata(e)):
        out.append(f"{where}: the table's metadata (pandas, GeoParquet) differs")
    if a.num_rows != e.num_rows:
        return out + [f"{where} has {a.num_rows} rows, expected {e.num_rows}"]
    differing = [name for name in a.schema.names if not _same_column(a.column(name), e.column(name))]
    if differing:
        out.append(f"{where}: the values differ in the columns {differing}")
    return out


_UNREADABLE = object()


def _json_value(snapshot: dict):
    """The value a list or dict snapshot's JSON holds, or _UNREADABLE."""
    import zlib
    if "inline" in snapshot:
        return json.loads(snapshot["inline"] or "null")
    try:
        return json.loads(zlib.decompress(Path(snapshot["path"]).read_bytes()).decode("utf-8"))
    except (OSError, zlib.error, ValueError):
        return _UNREADABLE


def _short(value) -> str:
    text = repr(value)
    return text if len(text) <= 200 else text[:200] + "..."


def artifact_differences(actual: dict, expected: dict, where: str = "the output") -> list[str]:
    """How two ``snapshot_artifact`` results differ, one line per place;
    empty when they hold the same value.

    As strict as comparing the JSON envelopes was, and stricter where the
    envelope lost something: a table's values are compared as stored, its
    metadata and column types included. A list or dict whose stored bytes
    differ is read back and compared as values, so the same values written in
    another key order still match.
    """
    kind = expected.get("kind")
    if actual.get("kind") != kind:
        return [f"{where} is a {actual.get('kind')}, expected a {kind}"]
    if "envelope" in actual or "envelope" in expected:
        if "envelope" not in actual or "envelope" not in expected:
            return [f"{where}: one run's {kind} was read as stored, the other's as JSON"]
        a, e = actual["envelope"], expected["envelope"]
        if a == e:
            return []
        keys = sorted(k for k in set(a) | set(e) if a.get(k) != e.get(k))
        return [f"{where}: the JSON differs in its top-level keys {keys}"]
    if "value" in expected:
        if _same_value(actual["value"], expected["value"]):
            return []
        return [f"{where} is {_short(actual['value'])}, expected {_short(expected['value'])}"]
    if "parts" in expected:
        a, e = actual["parts"], expected["parts"]
        if isinstance(e, dict):
            if not isinstance(a, dict) or a.keys() != e.keys():
                return [f"{where} has the keys {sorted(a)}, expected {sorted(e)}"]
            return [line for key in e for line in artifact_differences(a[key], e[key], f"{where}[{key!r}]")]
        if len(a) != len(e):
            return [f"{where} has {len(a)} values, expected {len(e)}"]
        return [line for i, (x, y) in enumerate(zip(a, e))
                for line in artifact_differences(x, y, f"{where}[{i}]")]
    if "table" in expected:
        return _table_differences(actual, expected, where)
    if actual.get("digest") == expected.get("digest"):
        return []
    a, e = _json_value(actual), _json_value(expected)
    if a is _UNREADABLE or e is _UNREADABLE:
        return [f"{where}: the stored {kind} differs (sha256 {actual.get('digest')} "
                f"against {expected.get('digest')}), and one of them can no longer be read"]
    if _same_value(a, e):
        return []
    return [f"{where}: the {kind} differs from the expected one"]


def load_raster_cells(artifact_id: str):
    """A raster artifact as the sandbox serves it to an Autark map (``/raster``,
    GeoTIFF bytes): ``(grid, bands)``. *grid* is its grid as an envelope names
    it (``crs``, ``width``, ``height``, ``originX``, ``originY``, ``resX``,
    ``resY``); *bands* is a float32 array of its bands, rows from north to
    south, NaN where a cell has no value."""
    import numpy as np
    import requests as _req
    from rasterio.io import MemoryFile

    resp = _req.get(
        f'{sandbox_base_url()}/raster',
        params={'fileName': artifact_id},
        headers=sandbox_auth_header(),
        timeout=(SANDBOX_CONNECT_TIMEOUT_S, SANDBOX_GET_TIMEOUT_S),
    )
    _explain_sandbox_auth_failure(resp, f'/raster fileName={artifact_id}')
    if not resp.ok:
        raise AssertionError(
            f"sandbox /raster fileName={artifact_id} -> {resp.status_code}\n"
            f"{resp.text[:2000]}"
        )
    with MemoryFile(resp.content) as memory, memory.open() as dataset:
        bands = dataset.read(masked=True).astype("float32").filled(np.nan)
        t = dataset.transform
        grid = {
            "crs": dataset.crs.to_string() if dataset.crs is not None else None,
            "width": dataset.width, "height": dataset.height,
            "originX": t.c, "originY": t.f, "resX": t.a, "resY": t.e,
        }
    return grid, bands


def _catalog_dataset_paths(code: str) -> dict[str, str]:
    """Map every ``curio_data_path("<id>")`` in *code* to its data file.

    The browser path gets this mapping from the backend
    (``resolve_dataset_paths`` in ``backend/app/execution/node_exec.py``), which
    posts it to the sandbox as ``dataset_paths``. This helper talks to the
    sandbox directly -- deliberately, so DuckDB keeps a single writer -- so the
    mapping has to come from somewhere.

    Ask the running backend for it, via ``/api/testing/dataset-paths``, rather
    than scanning ``datasets/`` in this process. The path has to be valid in
    the SANDBOX's filesystem, and under ``CURIO_E2E_USE_EXISTING`` against a
    compose stack that is not this one: resolving here produced host paths like
    ``/home/runner/work/curio/curio/datasets/...`` for a sandbox that sees the
    same committed files at ``/app/datasets/...``, and all six curated examples
    whose loaders resolve a dataset by id failed on FileNotFoundError. Asking
    the backend also means the harness goes through the real catalog service,
    so hub, imported and computed datasets all resolve the way they do in the
    app instead of only the committed tree this used to know about.

    Falls back to nothing rather than raising when the backend cannot answer --
    the sandbox's injected resolver already raises a clear per-id error, and
    the assertion below still names an id the catalog does not have.
    """
    return _catalog_resolution(code)["paths"]


def _catalog_resolution(code: str, username: str | None = None, node_type: str | None = None) -> dict:
    """``{"paths", "formats", "collections", "mediaDir", "models", "packageModules"}`` for
    *code*, as the backend resolves them for ``/processPythonCode``, as *username* when
    given; see ``_catalog_dataset_paths``. ``packageModules`` are what the node of
    *node_type* may import from its package.

    Asked for every node, not only one that names a dataset: ``mediaDir`` is
    where a node downstream of a collection writes the files it derives.
    """
    url = f"{_backend_base_url_for_config()}/api/testing/dataset-paths"
    body = {
        "code": code,
        **({"username": username} if username else {}),
        **({"nodeType": node_type} if node_type else {}),
    }
    payload = json.dumps(body).encode("utf-8")
    req = Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(req, timeout=15) as resp:  # noqa: S310
            answer = json.loads(resp.read().decode("utf-8")) or {}
            resolved = answer.get("paths") or {}
    except HTTPError as exc:
        raise AssertionError(
            f"POST {url} answered {exc.code}. The stack must expose the testing "
            "stubs (CURIO_TESTING=1, and CURIO_ENV != 'prod'); the CI overlays "
            "set it, see docker-compose.ci.yml."
        ) from exc

    # Fail loudly rather than letting the sandbox report a generic runtime
    # error: a typo'd id, or one carrying an ``@major`` the catalog lookup does
    # not use, is a test-authoring bug and should name itself.
    from utk_curio.backend.app.datasets.domain.code_refs import DATASET_PATH_CALL_RE

    referenced = {
        dataset_id for _quote, dataset_id in DATASET_PATH_CALL_RE.findall(code)
    }
    missing = sorted(referenced - set(resolved))
    assert not missing, (
        f"curio_load_data() / curio_data_path() reference {missing}, which the backend's "
        f"catalog could not resolve (it resolved: {sorted(resolved)}). Note the "
        f"call takes the bare manifest id with no '@major'."
    )
    return {
        "paths": resolved,
        "formats": answer.get("formats") or {},
        "collections": answer.get("collections") or {},
        "mediaDir": answer.get("mediaDir"),
        "models": answer.get("models") or {},
        "packageModules": answer.get("packageModules"),
    }


def execute_workflow_programmatically(
    spec, seed: int = 42, username: str | None = None
) -> dict[str, dict]:
    """Execute every code node via the sandbox HTTP API and return
    {node_id: ``snapshot_artifact`` of its output}.

    *username* is the account the browser run signs in as, so datasets and the
    files nodes derive from them resolve the same way in both runs.

    Routes all execution through the sandbox's /exec endpoint so the sandbox's
    persistent DuckDB connection remains the sole writer throughout the test.
    The returned snapshots are what Playwright tests compare browser-produced
    outputs with (``artifact_differences``).
    """
    import requests as _req

    sandbox_url = sandbox_base_url()

    from ..workflow_spec import (
        PY_CODE_TYPES,
        propagate_node_input,
        resolve_node_input,
    )

    outputs: dict[str, dict] = {}   # node_id → {"path": artifact_id, "dataType": ...}
    expected: dict[str, dict] = {}  # node_id → snapshot of its output, taken at once (see below)
    # Nodes that give this runner no output: one only the browser runs (an
    # Autark data or compute step) and every Python node below one.
    browser_only: set[str] = set()

    for node in spec.topo_sorted_nodes():
        # Non-code nodes — and code nodes whose content is JavaScript
        # (JS_COMPUTATION) — propagate upstream output without execution: the
        # Python-exec path below would parse-error on JS source.
        if node.category != "code" or node.type not in PY_CODE_TYPES:
            propagated = propagate_node_input(spec, node.id, outputs)
            if propagated is not None:
                outputs[node.id] = propagated
            else:
                browser_only.add(node.id)
            continue

        # A Python node reading such a node has no input here, so it has no
        # ground truth either; the browser run is checked without one (#662:
        # example 06's Sunlight change reads its Autark maps). Any other
        # missing upstream is still the KeyError below.
        unrun = [uid for uid in spec.upstream_nodes(node.id) if uid not in outputs]
        if unrun and all(uid in browser_only for uid in unrun):
            browser_only.add(node.id)
            continue

        # Resolve input as the backend does (node_exec.parse_input_ref): a fan-in
        # is a list of refs, passed as a stringified list that worker.py eval()s
        # back; one upstream whose node returned several values is its outputs
        # artifact, read as a file and expanded by the worker.
        from utk_curio.backend.app.execution.node_exec import parse_input_ref

        ref = resolve_node_input(spec, node.id, outputs)
        if ref["dataType"] == "outputs" and isinstance(ref["path"], list):
            parsed = parse_input_ref({"dataType": "outputs", "data": ref["path"]})
        else:
            parsed = parse_input_ref({"path": ref["path"], "dataType": ref["dataType"]})
        data_type = parsed["dataType"]
        file_path = str(parsed["path"]) if data_type == "outputs" else parsed["path"]

        # Sandbox /exec expects code already indented as a function body
        resolved = spec.node_code(node, "python")
        seeded = seed_node_code(resolved, seed)
        indented_code = textwrap.indent(seeded, "    ")
        resolution = _catalog_resolution(indented_code, username, node.raw_type)

        resp = _req.post(
            f'{sandbox_url}/exec',
            json={
                "code": indented_code,
                "file_path": file_path,
                # The on-the-wire namespaced id (`curio.builtin/...`), as the
                # browser posts it: the sandbox tags the artifact and its log
                # lines with it (no type dispatch happens on it — dev/120).
                "nodeType": node.raw_type,
                "dataType": data_type,
                # The backend resolves these for the browser path; this runner
                # bypasses the backend, so it resolves them itself.
                "dataset_paths": resolution["paths"],
                "dataset_formats": resolution["formats"],
                "collections": resolution["collections"],
                "media_dir": resolution["mediaDir"],
                "models": resolution["models"],
                **({"package_modules": resolution["packageModules"]}
                   if resolution["packageModules"] else {}),
                # The wired circles, as the backend's runner sends them: each
                # circle k is the code's input_k.
                **({"input_slots": spec.input_slots(node.id)}
                   if spec.input_slots(node.id) else {}),
            },
            headers=sandbox_auth_header(),
            timeout=120,
        )
        _explain_sandbox_auth_failure(resp, '/exec')
        resp.raise_for_status()
        result = resp.json()

        # Treat the exec as failed only when the worker produced no output path.
        # The worker's redirect_stderr captures Python warnings (e.g. geopandas
        # UserWarning) on otherwise-successful runs, so a non-empty stderr
        # alone is not a failure signal — but a real exception leaves
        # result['output']['path'] empty (see worker.py).
        out = result.get('output') or {}
        if not out.get('path'):
            raise RuntimeError(
                f"Node {node.id} ({node.type}) failed:\n{result.get('stderr', '')}"
            )

        outputs[node.id] = {"path": out['path'], "dataType": out['dataType']}
        # Snapshot the artifact *now* - it may be invisible later when the
        # browser run uses a different session_id, or may have been
        # overwritten/evicted from DuckDB by then. A snapshot holds a table as
        # Arrow and a list or dict by its digest, never the JSON envelope. Every
        # node that reaches here is a PY_CODE_TYPES node (the only ones
        # Python-exec'd), and those are exactly the ones that get inline
        # data-content comparison.
        expected[node.id] = snapshot_artifact(out['path'])

    return expected
