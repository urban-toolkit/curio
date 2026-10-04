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

from ..workflow_spec import resolve_code_references, seed_node_code
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



def _catalog_dataset_paths(code: str) -> dict[str, str]:
    """Map every ``curio_data_path("<id>")`` in *code* to its data file.

    The browser path gets this mapping from the backend
    (``_resolve_exec_dataset_paths`` in ``backend/app/api/routes.py``), which
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


def _catalog_resolution(code: str, username: str | None = None) -> dict:
    """``{"paths", "formats", "collections", "mediaDir", "models"}`` for *code*, as the backend
    resolves them for ``/processPythonCode``, as *username* when given; see
    ``_catalog_dataset_paths``.

    Asked for every node, not only one that names a dataset: ``mediaDir`` is
    where a node downstream of a collection writes the files it derives.
    """
    url = f"{_backend_base_url_for_config()}/api/testing/dataset-paths"
    body = {"code": code, **({"username": username} if username else {})}
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
    from utk_curio.backend.app.api.routes import _DATASET_PATH_CALL_RE

    referenced = {
        dataset_id for _quote, dataset_id in _DATASET_PATH_CALL_RE.findall(code)
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
    }


def execute_workflow_programmatically(
    spec, seed: int = 42, username: str | None = None
) -> dict[str, str]:
    """Execute every code node via the sandbox HTTP API and return {node_id: artifact_id}.

    *username* is the account the browser run signs in as, so datasets and the
    files nodes derive from them resolve the same way in both runs.

    Routes all execution through the sandbox's /exec endpoint so the sandbox's
    persistent DuckDB connection remains the sole writer throughout the test.
    The returned artifact IDs are used by Playwright tests to compare
    sandbox-produced outputs with browser-produced ones.
    """
    import requests as _req

    sandbox_url = sandbox_base_url()

    from ..workflow_spec import (
        PY_CODE_TYPES,
        propagate_node_input,
        resolve_node_input,
    )

    outputs: dict[str, dict] = {}   # node_id → {"path": artifact_id, "dataType": ...}
    expected: dict[str, dict] = {}  # node_id → eager-loaded artifact dict (see fix below)

    for node in spec.topo_sorted_nodes():
        # Non-code nodes — and code nodes whose content is JavaScript
        # (JS_COMPUTATION) — propagate upstream output without execution: the
        # Python-exec path below would parse-error on JS source.
        if node.category != "code" or node.type not in PY_CODE_TYPES:
            propagated = propagate_node_input(spec, node.id, outputs)
            if propagated is not None:
                outputs[node.id] = propagated
            continue

        # Resolve input (mirrors process_python_code in backend routes.py)
        ref = resolve_node_input(spec, node.id, outputs)
        if ref["dataType"] == "outputs":
            # Pass as stringified list; worker.py eval()s it back
            file_path = str(ref["path"])
            data_type = "outputs"
        else:
            file_path = ref["path"]
            data_type = ref["dataType"]

        # Sandbox /exec expects code already indented as a function body
        resolved = resolve_code_references(node.content, node.widgets, "python", spec.input_slots(node.id))
        seeded = seed_node_code(resolved, seed)
        indented_code = textwrap.indent(seeded, "    ")
        resolution = _catalog_resolution(indented_code, username)

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
        # Load the artifact contents *now* and stash them — the artifact may be
        # invisible later when the browser run uses a different session_id, or
        # may have been overwritten/evicted from DuckDB by then. Every node that
        # reaches here is a PY_CODE_TYPES node (the only ones Python-exec'd), and
        # those are exactly the ones that get inline data-content comparison.
        expected[node.id] = load_artifact_as_dict(out['path'])

    return expected
