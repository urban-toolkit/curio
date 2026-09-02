import os
import re
import json
import time
# import zlib
import shutil
import textwrap
from pathlib import Path
from io import BytesIO
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

import allure
import pytest
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    expect,
)

# Repo root is 4 levels up: test_frontend -> tests -> backend -> utk_curio -> curio-main
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

# PNGs from workflow E2E tests: ``screenshot_{workflow_stem}_{test_name}.png``
WORKFLOW_SCREENSHOT_EXPECTED_DIR = os.path.join(
    REPO_ROOT, "docs", "examples", "dataflows", "expected_outputs"
)

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


def load_artifact_as_dict(artifact_id: str) -> dict:
    """Fetch a stored artifact from the sandbox and return its parsed representation."""
    import requests as _req
    sandbox_host = os.environ.get('FLASK_SANDBOX_HOST', '127.0.0.1')
    sandbox_port = int(os.environ.get('FLASK_SANDBOX_PORT', '2000'))
    resp = _req.get(
        f'http://{sandbox_host}:{sandbox_port}/get',
        params={'fileName': artifact_id},
        headers=sandbox_auth_header(),
        timeout=(SANDBOX_CONNECT_TIMEOUT_S, SANDBOX_GET_TIMEOUT_S),
    )
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
# Deterministic seeding for reproducible programmatic execution
# ---------------------------------------------------------------------------

_SEED_PREFIX = (
    "import numpy as _np; _np.random.seed({seed}); "
    "import random as _rnd; _rnd.seed({seed})\n"
)


def seed_node_code(code: str, seed: int = 42) -> str:
    """Prepend deterministic random-seed lines to *code*.

    Uses underscore-prefixed aliases (``_np``, ``_rnd``) so the seed
    imports never shadow the user's own ``import numpy as np``.
    """
    return _SEED_PREFIX.format(seed=seed) + code


_WIDGET_RE = re.compile(r"\[!!\s*(.*?)\s*!!\]")


def resolve_widget_placeholders(code: str) -> str:
    """Replace ``[!! name$type$default !!]`` widget markers with defaults.

    The frontend resolves these before sending code to the sandbox; the
    programmatic executor must do the same.
    """
    def _replace(m):
        parts = m.group(1).split("$")
        if len(parts) >= 3:
            return parts[2]
        return m.group(0)
    return _WIDGET_RE.sub(_replace, code)


PLAYWRIGHT_EXPECTED_DIR = os.path.join(
    REPO_ROOT, ".curio", "playwright", "expected"
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def _backend_base_url_for_config() -> str:
    """Resolve the backend URL for fetching ``/api/config/public``.

    When attaching to an already-running stack (``CURIO_E2E_USE_EXISTING=1``)
    or running the fixture-spawned subprocess, the backend's actual state
    is the single source of truth for the auth/guest/project flags — the
    pytest process env alone cannot reproduce it, because the ``curio start``
    subprocess overrides these vars from its CLI flags.
    """
    host = os.environ.get("CURIO_E2E_HOST", "localhost")
    port = os.environ.get("CURIO_E2E_BACKEND_PORT") or os.environ.get(
        "BACKEND_PORT", "5002"
    )
    return f"http://{host}:{port}"


_PUBLIC_CONFIG_CACHE: dict | None = None


def _fetch_public_config() -> dict | None:
    """Return the cached ``/api/config/public`` body, or ``None`` if offline.

    Result is memoised for the pytest session because a Curio backend does
    not change its auth flags at runtime (they're read from the process env
    at import time). Callers treat ``None`` as "backend unreachable, fall
    back to env inspection".
    """
    global _PUBLIC_CONFIG_CACHE
    if _PUBLIC_CONFIG_CACHE is not None:
        return _PUBLIC_CONFIG_CACHE
    url = f"{_backend_base_url_for_config()}/api/config/public"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            if resp.getcode() != 200:
                return None
            body = resp.read().decode("utf-8") or "{}"
            _PUBLIC_CONFIG_CACHE = json.loads(body)
            return _PUBLIC_CONFIG_CACHE
    except (URLError, OSError, ValueError):
        return None


def auth_enabled_env() -> bool:
    """True when the running backend has user auth enabled.

    Prefers the live backend's ``/api/config/public`` response so the pytest
    process never disagrees with the backend subprocess (whose ``CURIO_NO_AUTH``
    is set by ``curio.py start`` CLI flags, not inherited from pytest env).
    Falls back to env vars when the backend is not yet reachable (e.g. fixture
    setup phase before the port is bound).
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        if cfg.get("curio_no_project") or cfg.get("skip_project_page"):
            return False
        return not bool(cfg.get("curio_no_auth"))
    if env_flag("CURIO_NO_PROJECT", False):
        return False
    return not env_flag("CURIO_NO_AUTH", False)


def allow_guest_login_env() -> bool:
    """True when guest login is enabled on the running backend.

    Like :func:`auth_enabled_env`, prefers the live ``/api/config/public``
    response and only falls back to pytest-process env vars when the backend
    is unreachable.
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        return bool(cfg.get("allow_guest_login"))
    if "ALLOW_GUEST_LOGIN" in os.environ:
        return env_flag("ALLOW_GUEST_LOGIN", False)
    return os.environ.get("CURIO_ENV", "dev") != "prod"


def skip_project_page_env() -> bool:
    """True when the running backend hides the ``/projects`` page.

    Mirrors :func:`auth_enabled_env`: prefer the live backend's view (via
    ``/api/config/public``) over pytest-process env inspection, since the
    ``curio start`` subprocess sets ``CURIO_NO_PROJECT`` from its CLI flags
    and pytest does not inherit that.
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        return bool(cfg.get("skip_project_page") or cfg.get("curio_no_project"))
    return env_flag("CURIO_NO_PROJECT", False)


def require_user_auth() -> None:
    if not auth_enabled_env():
        pytest.skip("This test requires CURIO_NO_AUTH=0")


def require_project_page() -> None:
    """Skip the current test when Curio is running in ``--no-project`` mode.

    Tests that drive the ``/projects`` list page or the per-user save/load
    File-menu entries should call this so they're skipped (rather than
    timing out on missing UI) when the backend reports
    ``curio_no_project=true``.
    """
    if skip_project_page_env():
        pytest.skip("This test requires CURIO_NO_PROJECT=0")


def require_no_project_mode() -> None:
    """Skip the current test unless Curio is running in ``--no-project`` mode.

    Inverse of :func:`require_project_page`: tests that specifically assert
    the no-project UI (e.g. that the File menu hides project-backed entries)
    only make sense when the backend reports ``curio_no_project=true``.
    """
    if not skip_project_page_env():
        pytest.skip("This test requires CURIO_NO_PROJECT=1")


# ---------------------------------------------------------------------------
# Vega-Lite SVG helpers
# ---------------------------------------------------------------------------

def dot_data_to_vega_values(data: dict) -> list[dict]:
    """Convert a ``.data`` dict to the row-oriented list that Vega expects.

    Mirrors the frontend ``parseDataframe`` / ``parseGeoDataframe`` functions
    in ``src/utils/parsing.ts``.

    The ``dataframe`` format can be either dict-of-dicts (``to_dict()``)
    or dict-of-lists (``to_dict(orient='list')``); both are handled.
    """
    dtype = data.get("dataType")
    raw = data.get("data", {})
    if dtype == "dataframe":
        columns = list(raw.keys())
        first_col = raw[columns[0]]
        if isinstance(first_col, dict):
            keys = list(first_col.keys())
        else:
            keys = list(range(len(first_col)))
        return [
            {col: raw[col][k] for col in columns}
            for k in keys
        ]
    elif dtype == "geodataframe":
        return [f["properties"] for f in raw.get("features", [])]
    return []


def save_expected_svg(dataflow_name: str, node_id: str, svg_content: str) -> str:
    """Save a programmatically generated expected SVG to
    ``.curio/playwright/expected/<dataflow_name>/<node_id>.svg``.

    Returns the absolute path of the saved file.
    """
    dest_dir = os.path.join(PLAYWRIGHT_EXPECTED_DIR, dataflow_name)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{node_id}.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    return path


def load_expected_svg(dataflow_name: str, node_id: str) -> str | None:
    """Load a previously saved expected SVG, or return ``None``."""
    path = os.path.join(PLAYWRIGHT_EXPECTED_DIR, dataflow_name, f"{node_id}.svg")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def compare_svg_structure(
    actual_svg: str,
    expected_svg: str,
) -> list[str]:
    """Structurally compare two Vega-rendered SVG strings.

    Returns an empty list when the two SVGs are structurally equivalent.

    The comparison walks the ``<g>`` element tree and checks that both
    SVGs share the same hierarchy of ``class``, ``role``, and
    ``aria-roledescription`` attributes at every level.
    """
    import xml.etree.ElementTree as ET

    SVG_NS = "http://www.w3.org/2000/svg"

    _STRUCTURAL_ATTRS = ("class", "role", "aria-roledescription")

    def _parse(svg_str: str, label: str):
        try:
            return ET.fromstring(svg_str), []
        except ET.ParseError as e:
            return None, [f"{label} SVG is not valid XML: {e}"]

    def _sig(el) -> str:
        """Structural signature of an element: tag + key attributes."""
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        parts = [tag]
        for attr in _STRUCTURAL_ATTRS:
            val = el.get(attr)
            if val:
                parts.append(f"{attr}={val}")
        return "|".join(parts)

    def _g_children(el):
        """Return direct ``<g>`` children of *el*."""
        return [
            ch for ch in el
            if ch.tag == f"{{{SVG_NS}}}g" or ch.tag == "g"
        ]

    def _compare_g_tree(actual_el, expected_el, path: str, diffs: list):
        """Recursively compare ``<g>`` sub-trees by structural signature."""
        actual_gs = _g_children(actual_el)
        expected_gs = _g_children(expected_el)

        if len(actual_gs) != len(expected_gs):
            diffs.append(
                f"At {path}: <g> child count differs — "
                f"actual={len(actual_gs)}, expected={len(expected_gs)}"
            )
            return

        for i, (a_g, e_g) in enumerate(zip(actual_gs, expected_gs)):
            a_sig = _sig(a_g)
            e_sig = _sig(e_g)
            child_path = f"{path}/g[{i}]"
            if a_sig != e_sig:
                diffs.append(
                    f"At {child_path}: signature mismatch — "
                    f"actual=({a_sig}), expected=({e_sig})"
                )
            else:
                _compare_g_tree(a_g, e_g, child_path, diffs)

    diffs: list[str] = []

    actual_root, errs = _parse(actual_svg, "Actual")
    if errs:
        return errs
    expected_root, errs = _parse(expected_svg, "Expected")
    if errs:
        return errs

    _compare_g_tree(actual_root, expected_root, "svg", diffs)

    return diffs


def _ensure_parsers_env():
    """Ensure ``CURIO_LAUNCH_CWD`` and ``CURIO_SHARED_DATA`` are set.

    ``get_db_path`` in ``utk_curio/sandbox/util/db.py`` reads these to
    resolve the path to ``curio_data.duckdb``.  When the test process is
    *not* started via ``curio start`` (e.g. ``CURIO_E2E_USE_EXISTING`` in
    CI) these variables may be absent, so we default them here.
    """
    if "CURIO_LAUNCH_CWD" not in os.environ:
        os.environ["CURIO_LAUNCH_CWD"] = REPO_ROOT
    if "CURIO_SHARED_DATA" not in os.environ:
        os.environ["CURIO_SHARED_DATA"] = str(
            Path(os.path.join(REPO_ROOT, ".curio", "data")).resolve()
        )

"""
def execute_workflow_programmatically(spec, seed: int = 42) -> dict[str, str]:
    #Execute every code node in-process and return *{node_id: expected_path}*.

    # Mirrors the sandbox ``python_wrapper.txt`` flow — load upstream data,
    # call user code, serialise via ``parseOutput`` / ``save_memory_mapped_file``
    # — but runs entirely inside the test process.  Results are copied to
    # ``.curio/playwright/expected/<workflow>/`` for later comparison with the
    # browser-produced ``.data`` files.
    #
    _ensure_parsers_env()

    from utk_curio.sandbox.util.parsers import (
        parseInput,
        parseOutput,
        save_memory_mapped_file,
        load_memory_mapped_file,
        checkIOType,
    )

    outputs: dict[str, dict] = {}   # node_id → {"path": ..., "dataType": ...}
    expected: dict[str, str] = {}   # node_id → absolute path in expected dir

    dataflow_name = os.path.splitext(os.path.basename(spec.filepath))[0]
    dest_dir = os.path.join(PLAYWRIGHT_EXPECTED_DIR, dataflow_name)
    os.makedirs(dest_dir, exist_ok=True)

    # User code uses relative paths (e.g. "docs/examples/data/…") that are
    # resolved from the repo root — the same CWD the sandbox uses via
    # CURIO_LAUNCH_CWD.  Switch CWD for the duration of execution.
    original_cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        for node in spec.topo_sorted_nodes():
            # Non-code nodes: propagate upstream output without execution
            if node.category != "code":
                upstreams = spec.upstream_nodes(node.id)
                if len(upstreams) == 1 and upstreams[0] in outputs:
                    outputs[node.id] = outputs[upstreams[0]]
                elif len(upstreams) > 1:
                    outputs[node.id] = {
                        "path": [outputs[uid] for uid in upstreams if uid in outputs],
                        "dataType": "outputs",
                    }
                continue

            # --- resolve input (mirrors python_wrapper.txt lines 30-49) ---
            upstreams = spec.upstream_nodes(node.id)
            if not upstreams:
                incoming = ""
            elif len(upstreams) == 1:
                up = outputs[upstreams[0]]
                if up.get("dataType") == "outputs":
                    incoming = []
                    for elem in up["path"]:
                        raw = load_memory_mapped_file(elem["path"])
                        incoming.append(parseInput(raw))
                else:
                    raw = load_memory_mapped_file(up["path"])
                    incoming = parseInput(raw)
            else:
                incoming = []
                for uid in upstreams:
                    raw = load_memory_mapped_file(outputs[uid]["path"])
                    incoming.append(parseInput(raw))

            # --- exec seeded user code ---
            resolved = resolve_widget_placeholders(node.content)
            seeded = seed_node_code(resolved, seed)

            # Provide the same top-level imports as python_wrapper.txt
            import warnings as _w; _w.filterwarnings("ignore")
            import rasterio, geopandas, pandas, mmap, hashlib, ast  # noqa: F811
            ns: dict = {
                "warnings": _w, "rasterio": rasterio,
                "gpd": geopandas, "geopandas": geopandas,
                "pd": pandas, "pandas": pandas,
                "json": json, "mmap": mmap, "zlib": zlib, "os": os,
                "time": time, "hashlib": hashlib, "ast": ast,
            }
            exec(
                "def userCode(arg):\n" + textwrap.indent(seeded, "    "),
                ns,
            )
            result = ns["userCode"](incoming)

            # --- serialise exactly like the sandbox ---
            parsed = parseOutput(result)
            checkIOType(parsed, node.type, False)
            rel_path = save_memory_mapped_file(parsed)

            outputs[node.id] = {"path": rel_path, "dataType": parsed["dataType"]}

            gt_path = os.path.join(dest_dir, f"{dataflow_name}_{node.id}.data")
            shutil.copy2(
                os.path.join(get_shared_data_dir(), rel_path),
                gt_path,
            )
            expected[node.id] = gt_path
    finally:
        os.chdir(original_cwd)

    return expected
"""

def _catalog_dataset_paths(code: str) -> dict[str, str]:
    """Map every ``curio_dataset_path("<id>")`` in *code* to its data file.

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
    if "curio_dataset_path" not in code:
        return {}

    url = f"{_backend_base_url_for_config()}/api/testing/dataset-paths"
    payload = json.dumps({"code": code}).encode("utf-8")
    req = Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(req, timeout=15) as resp:  # noqa: S310
            resolved = (json.loads(resp.read().decode("utf-8")) or {}).get(
                "paths"
            ) or {}
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
        f"curio_dataset_path() references {missing}, which the backend's "
        f"catalog could not resolve (it resolved: {sorted(resolved)}). Note the "
        f"call takes the bare manifest id with no '@major'."
    )
    return resolved


def execute_workflow_programmatically(spec, seed: int = 42) -> dict[str, str]:
    """Execute every code node via the sandbox HTTP API and return {node_id: artifact_id}.

    Routes all execution through the sandbox's /exec endpoint so the sandbox's
    persistent DuckDB connection remains the sole writer throughout the test.
    The returned artifact IDs are used by Playwright tests to compare
    sandbox-produced outputs with browser-produced ones.
    """
    import requests as _req

    sandbox_host = os.environ.get('FLASK_SANDBOX_HOST', '127.0.0.1')
    sandbox_port = int(os.environ.get('FLASK_SANDBOX_PORT', '2000'))
    sandbox_url = f'http://{sandbox_host}:{sandbox_port}'

    from .workflow_spec import PY_CODE_TYPES

    outputs: dict[str, dict] = {}   # node_id → {"path": artifact_id, "dataType": ...}
    expected: dict[str, dict] = {}  # node_id → eager-loaded artifact dict (see fix below)

    for node in spec.topo_sorted_nodes():
        # Non-code nodes — and code nodes whose content is JavaScript
        # (JS_COMPUTATION) — propagate upstream output without execution: the
        # Python-exec path below would parse-error on JS source.
        if node.category != "code" or node.type not in PY_CODE_TYPES:
            upstreams = spec.upstream_nodes(node.id)
            if len(upstreams) == 1 and upstreams[0] in outputs:
                outputs[node.id] = outputs[upstreams[0]]
            elif len(upstreams) > 1:
                outputs[node.id] = {
                    "path": [outputs[uid] for uid in upstreams if uid in outputs],
                    "dataType": "outputs",
                }
            continue

        # Resolve input (mirrors process_python_code in backend routes.py)
        upstreams = spec.upstream_nodes(node.id)
        if not upstreams:
            file_path = ""
            data_type = ""
        elif len(upstreams) == 1:
            up = outputs[upstreams[0]]
            if up.get("dataType") == "outputs":
                # Pass as stringified list; worker.py eval()s it back
                file_path = str(up["path"])
                data_type = "outputs"
            else:
                file_path = up["path"]
                data_type = up["dataType"]
        else:
            file_path = str([outputs[uid] for uid in upstreams])
            data_type = "outputs"

        # Sandbox /exec expects code already indented as a function body
        resolved = resolve_widget_placeholders(node.content)
        seeded = seed_node_code(resolved, seed)
        indented_code = textwrap.indent(seeded, "    ")

        resp = _req.post(
            f'{sandbox_url}/exec',
            json={
                "code": indented_code,
                "file_path": file_path,
                # Send the on-the-wire namespaced id (`curio.builtin/...`)
                # so the sandbox's checkIOType matches what the browser
                # frontend posts; otherwise the programmatic runner would
                # enable IO validation that the browser path silently skips.
                "nodeType": node.raw_type,
                "dataType": data_type,
                # The backend resolves these for the browser path; this runner
                # bypasses the backend, so it resolves them itself.
                "dataset_paths": _catalog_dataset_paths(indented_code),
            },
            headers=sandbox_auth_header(),
            timeout=120,
        )
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


def _wait_for_reactflow_ready(
    page: Page,
    *,
    padding: float = 0.2,
    stable_frames: int = 3,
    timeout_ms: int = 10000,
) -> None:
    """Force ReactFlow into a deterministic viewport before screenshotting.

    Without this, ``save_workflow_test_screenshot`` races the app-side
    ``fitView`` call in ``useWorkflowOperations`` (which runs on a
    ``setTimeout`` after the workflow is uploaded). The screenshot can
    fire before the transform has been applied, producing a pre-fit
    canvas where nodes overflow the viewport.

    Strategy:

    1. Wait until at least one ``.react-flow__node`` is on the page.
    2. Call ``fitView({ padding, duration: 0 })`` on the instance
       exposed at ``window.__curio_reactFlow`` (see ``MainCanvas.tsx``).
       ``duration: 0`` skips the ReactFlow animation so the transform
       is applied synchronously.
    3. Poll the ``.react-flow__viewport`` ``transform`` attribute until
       it has stayed identical for ``stable_frames`` consecutive reads
       (guards against Monaco's layout settling and any late
       node-size measurements from ReactFlow).
    """
    page.wait_for_function(
        "() => document.querySelectorAll('.react-flow__node').length > 0",
        timeout=timeout_ms,
    )

    page.evaluate(
        """(padding) => {
            const fit = window.__curio_fitViewWithMenuOffset;
            if (typeof fit === 'function') {
                fit({ padding, duration: 0, includeHiddenNodes: true });
            }
        }""",
        padding,
    )

    page.wait_for_function(
        """(stable_frames) => {
            const vp = document.querySelector('.react-flow__viewport');
            if (!vp) return false;
            const current = vp.style.transform || '';
            if (!current) return false;
            window.__curio_vp_samples = window.__curio_vp_samples || [];
            const samples = window.__curio_vp_samples;
            samples.push(current);
            if (samples.length > stable_frames) samples.shift();
            if (samples.length < stable_frames) return false;
            return samples.every((s) => s === samples[0]);
        }""",
        arg=stable_frames,
        timeout=timeout_ms,
    )

    page.evaluate("delete window.__curio_vp_samples")


def _capture_full_page(page: Page):
    """Return a Pillow RGB image of the full scrollable page.

    Scrolls to top-left first so the capture is deterministic, then uses
    Playwright's ``full_page=True`` to grab everything.
    """
    from PIL import Image

    page.evaluate("window.scrollTo(0, 0)")
    raw = page.screenshot(full_page=True)
    return Image.open(BytesIO(raw)).convert("RGB")


def _capture_element(page: Page, selector: str):
    """Return a Pillow RGB image of one element, or raise if it is not there.

    For a baseline whose subject is a panel rather than a page. A full-page
    capture of, say, an agent chat turn is more than half static canvas and
    chrome, which does not just waste the image - it dilutes the comparison,
    since a regression inside the panel is a small fraction of the frame
    against a 20% budget.
    """
    from PIL import Image

    locator = page.locator(selector)
    locator.wait_for(state="visible", timeout=15000)
    raw = locator.screenshot()
    return Image.open(BytesIO(raw)).convert("RGB")


def _image_to_png_bytes(img) -> bytes:
    """Encode a Pillow image to PNG bytes for Allure attachments."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def dump_browser_log(
    workflow_filepath: str,
    test_name: str,
    log_entries: list,
    autk_errors: dict | None = None,
    webgpu_diagnostics: dict | None = None,
) -> str:
    """Write captured browser console + pageerror events (and any AUTK error
    tab text we extracted from the DOM) to a plain text file alongside the
    expected screenshot, and attach it to the Allure report.

    Returns the path written.
    """
    stem = os.path.splitext(os.path.basename(workflow_filepath))[0]
    os.makedirs(WORKFLOW_SCREENSHOT_EXPECTED_DIR, exist_ok=True)
    log_path = os.path.join(
        WORKFLOW_SCREENSHOT_EXPECTED_DIR,
        f"screenshot_{stem}_{test_name}_browser_log.txt",
    )
    lines: list[str] = []
    lines.append(f"# Browser log for {stem} :: {test_name}")
    lines.append(f"# Captured {len(log_entries)} console/pageerror events")
    lines.append("")
    if webgpu_diagnostics is not None:
        lines.append("## WebGPU diagnostics (probed once per session)")
        lines.append(json.dumps(webgpu_diagnostics, indent=2, default=str))
        lines.append("")
    if autk_errors:
        lines.append("## AUTK error tab text (extracted from DOM)")
        for node_id, text in autk_errors.items():
            lines.append(f"--- node {node_id} ---")
            lines.append(text or "(empty)")
            lines.append("")
    lines.append("## Console / pageerror events (chronological)")
    for entry in log_entries:
        if entry.get("kind") == "pageerror":
            lines.append(f"[pageerror] {entry.get('message', '')}")
        else:
            loc = entry.get("location") or {}
            url = loc.get("url", "")
            line_no = loc.get("lineNumber", "")
            lines.append(
                f"[{entry.get('type', 'log')}] {entry.get('text', '')}"
                f"  ({url}:{line_no})"
            )
    payload = "\n".join(lines) + "\n"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(payload)
    try:
        allure.attach(
            payload,
            name=f"screenshot_{stem}_{test_name}_browser_log.txt",
            attachment_type=allure.attachment_type.TEXT,
        )
    except Exception:
        pass
    return log_path


def accept_confirm_dialog(
    page: Page,
    *,
    title,
    button: str,
    timeout: float = 10000,
):
    """Accept the in-app confirmation a catalog raises (#196, #197).

    The three catalogs replaced ``window.confirm`` with a ``ConfirmDialog``
    built on ``ModalShell``, so ``page.once("dialog", ...)`` no longer fires -
    a test still relying on it clicks the card button and then silently does
    nothing, and fails later for the wrong reason.

    The drawers are themselves ``role="dialog"``, so a bare
    ``get_by_role("dialog")`` is ambiguous whenever one is open. The modal is
    located by its accessible name instead, which ConfirmDialog wires from its
    heading through ``aria-labelledby``.

    ``title`` takes a string or a compiled pattern; ``button`` is the confirm
    button's exact label (it often repeats the card's, e.g. "Add to project").
    Returns the dialog locator so a caller can assert on its body first.
    """
    dialog = page.get_by_role("dialog", name=title)
    expect(dialog).to_be_visible(timeout=timeout)
    dialog.get_by_role("button", name=button, exact=True).click()
    expect(dialog).to_have_count(0, timeout=timeout)
    return dialog


def dismiss_toasts(
    page: Page,
    *,
    timeout: float = 3000,
    quiet_ms: float = 2500,
    max_rounds: int = 8,
) -> int:
    """Close visible toasts and wait for the toast region to go quiet.

    Worth doing before any visual baseline. Toasts are transient, bottom-right,
    and up to 360px wide, so whether one is on screen at capture time depends on
    timing rather than on the behaviour under test - and they sit exactly where
    canvas content usually is. Leaving them in makes the comparison flaky and
    obscures what the baseline is for.

    The *quiet* wait is the part that matters. A node reaching "Done" does not
    mean its follow-up work has finished: the dataset install-save is debounced
    500 ms past it and answers seconds later, so the toasts it raises (a save,
    an install) arrive well after the status flips. A single sweep dismisses
    nothing (there is nothing there yet) and the toast then lands in the
    capture. So sweep, wait ``quiet_ms`` for a late arrival, and sweep again
    until a full window passes with none.

    Never call this before an ASSERTION about a toast - it erases the evidence.
    A "couldn't be generated" warning in particular is a bug rather than routine
    noise (#180); ``test_computed_json_output_e2e.py`` records toasts through a
    MutationObserver and fails on that one.

    Safe to call when there are none. Bounded by *max_rounds*, so a toast that
    genuinely re-fires forever costs a few seconds rather than hanging - it just
    ends up in the screenshot, which is the honest outcome.
    """
    container = page.locator('[aria-label="Notifications"]')
    dismissed = 0

    for _ in range(max_rounds):
        # Each close click re-renders the list, so re-resolve rather than
        # iterating a stale handle set.
        for _ in range(12):
            buttons = container.locator("button.btn-close")
            if buttons.count() == 0:
                break
            try:
                buttons.first.click(timeout=1000)
                dismissed += 1
            except PlaywrightTimeoutError:
                break

        # Did another arrive during the quiet window? wait_for_function resolving
        # means one showed up, so loop and clear it; a timeout means quiet.
        try:
            page.wait_for_function(
                "() => !!document.querySelector('[aria-label=\"Notifications\"] .toast')",
                timeout=quiet_ms,
            )
        except PlaywrightTimeoutError:
            return dismissed

    return dismissed


def save_workflow_test_screenshot(
    page: Page,
    workflow_filepath: str,
    *,
    test_name: str,
    pixel_threshold: int = 30,
    max_diff_ratio: float = 0.20,
    fit_reactflow: bool = True,
    clip_selector: str | None = None,
) -> str:
    """Compare or create an expected screenshot for a workflow test.

    If the expected file already exists the current page is captured and
    compared pixel-by-pixel against it.  Both images are resized to the
    same dimensions before comparison so layout-only size changes don't
    cause false positives.  The assertion fails when more than
    *max_diff_ratio* (default 15 %) of pixels differ by more than
    *pixel_threshold* (per-channel, 0-255).

    On failure the expected, actual, and diff images are attached to the
    Allure report so that reviewers can inspect the regression directly
    from the GitHub Actions artifact.

    If the file does **not** exist yet the screenshot is saved as the new
    baseline. Note that a first run therefore *always* passes - generate a
    baseline deliberately, against a build where the behaviour is already
    correct, and eyeball the PNG before committing it. A baseline captured
    against a broken build enshrines the bug as expected output.

    Set *fit_reactflow* to ``False`` for pages with no canvas (the projects list,
    the catalog). The default path pins the ReactFlow viewport first, which waits
    on ``.react-flow__node`` and would otherwise spend its whole timeout waiting
    for a node that is never going to exist.

    Pass *clip_selector* when the subject of the baseline is one element rather
    than the page. The capture is then that element's box, so every pixel is
    about the thing under test and the diff budget is spent on it instead of on
    surrounding chrome.

    Returns the path to the expected screenshot file.
    """
    from PIL import Image, ImageChops, ImageEnhance
    import numpy as np

    stem = os.path.splitext(os.path.basename(workflow_filepath))[0]
    os.makedirs(WORKFLOW_SCREENSHOT_EXPECTED_DIR, exist_ok=True)
    filename = f"screenshot_{stem}_{test_name}.png"
    expected_path = os.path.join(WORKFLOW_SCREENSHOT_EXPECTED_DIR, filename)

    # Pin the ReactFlow viewport to a deterministic fitView before any
    # capture, so baselines and subsequent comparisons share the same
    # zoom/pan regardless of when the in-app setTimeout(fitView) fires.
    if fit_reactflow:
        _wait_for_reactflow_ready(page)

    def _capture():
        if clip_selector is not None:
            return _capture_element(page, clip_selector)
        return _capture_full_page(page)

    if not os.path.isfile(expected_path):
        _capture().save(expected_path)

    expected_img = Image.open(expected_path).convert("RGB")
    actual_img = _capture()

    target_w = max(actual_img.width, expected_img.width)
    target_h = max(actual_img.height, expected_img.height)
    actual_cmp = actual_img.resize((target_w, target_h), Image.LANCZOS)
    expected_cmp = expected_img.resize((target_w, target_h), Image.LANCZOS)

    diff = ImageChops.difference(actual_cmp, expected_cmp)
    arr = np.asarray(diff)
    total = int(arr.shape[0] * arr.shape[1])
    mismatched = int((arr > pixel_threshold).any(axis=2).sum())
    ratio = mismatched / total if total else 0.0

    if ratio > max_diff_ratio:
        actual_path = os.path.join(
            WORKFLOW_SCREENSHOT_EXPECTED_DIR,
            f"screenshot_{stem}_{test_name}_actual.png",
        )
        actual_img.save(actual_path)

        diff_highlighted = ImageEnhance.Brightness(diff).enhance(3.0)

        allure.attach(
            _image_to_png_bytes(expected_cmp),
            name=f"{filename} — expected",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            _image_to_png_bytes(actual_cmp),
            name=f"{filename} — actual",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            _image_to_png_bytes(diff_highlighted),
            name=f"{filename} — diff",
            attachment_type=allure.attachment_type.PNG,
        )

        raise AssertionError(
            f"Screenshot regression for {filename}: "
            f"{mismatched}/{total} pixels differ ({ratio:.2%}), "
            f"allowed {max_diff_ratio:.2%}. "
            f"Expected {expected_img.size[0]}x{expected_img.size[1]}, "
            f"actual {actual_img.size[0]}x{actual_img.size[1]}. "
            f"Actual saved to {actual_path}. "
            f"See Allure report attachments for visual diff."
        )
    return expected_path


def debug_log(location: str, message: str, data: dict = None, hypothesis_id: str = ""):
    """Write a single NDJSON debug entry to ``.curio/playwright.log``."""
    try:
        log_path = os.path.join(REPO_ROOT, ".curio", "playwright.log")
        entry = {
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "hypothesisId": hypothesis_id,
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Network / server helpers
# ---------------------------------------------------------------------------

def is_port_in_use(port: int) -> bool:
    """Return ``True`` if *port* is already listening on localhost."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_http_ready(
    base_url: str,
    path: str = "/live",
    timeout: float = 30.0,
    interval: float = 0.5,
) -> None:
    """Wait until ``GET base_url + path`` returns 200 or raise ``TimeoutError``."""
    url = f"{base_url.rstrip('/')}{path}"
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=5) as resp:
                if resp.getcode() == 200:
                    return
        except (URLError, OSError) as e:
            last_err = e
        time.sleep(interval)
    raise TimeoutError(
        f"HTTP GET {url} did not return 200 within {timeout}s "
        f"(last error: {last_err})"
    )


def wait_for_port(
    port: int, timeout: float = 30.0, interval: float = 0.5
) -> None:
    """Wait until something is listening on *port* or raise ``TimeoutError``."""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(interval)
    raise TimeoutError(
        f"Port {port} did not become ready within {timeout}s"
    )


def e2e_existing_servers():
    """When ``CURIO_E2E_USE_EXISTING=1``, use already-running servers.

    Waits for backend and sandbox ``/live`` to respond before returning.
    """
    host = os.environ.get("CURIO_E2E_HOST", "localhost")
    backend_port = int(os.environ.get("CURIO_E2E_BACKEND_PORT", "5002"))
    sandbox_port = int(os.environ.get("CURIO_E2E_SANDBOX_PORT", "2000"))
    frontend_port = int(os.environ.get("CURIO_E2E_FRONTEND_PORT", "8080"))
    base = f"http://{host}"
    wait_for_http_ready(f"{base}:{backend_port}", timeout=60.0)
    wait_for_http_ready(f"{base}:{sandbox_port}", timeout=60.0)
    return {
        "backend_port": backend_port,
        "sandbox_port": sandbox_port,
        "frontend_port": frontend_port,
        "_host": host,
    }


def base_url(servers: dict, port_key: str) -> str:
    """Build an ``http://host:port`` URL from the *servers* dict."""
    host = servers.get("_host", "127.0.0.1")
    port = servers[port_key]
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# Reusable auth + canvas-entry helpers
#
# Every workflow/project E2E test needs the same bootstrap: sign up a fresh
# user, land on /projects, then open a new empty workflow canvas. These
# helpers centralise that choreography so individual tests (and the class
# scoped ``loaded_workflow`` fixture) stay focused on their actual assertions.
# ---------------------------------------------------------------------------

DEFAULT_TEST_PASSWORD = "testpass123"


def signup_e2e_user(
    page,
    base_url: str,
    *,
    name: str,
    username: str,
    password: str = DEFAULT_TEST_PASSWORD,
) -> None:
    """Sign up a fresh user via the ``/auth/signup`` form.

    Waits until the sign-up flow has redirected to ``/projects`` so callers
    can immediately interact with the authenticated UI.
    """
    require_user_auth()
    page.goto(f"{base_url}/auth/signup")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Create an account").wait_for(timeout=30000)
    page.get_by_label("Name", exact=True).fill(name)
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_label("Confirm Password").fill(password)
    page.get_by_role("button", name="Create account").click()
    page.wait_for_url("**/projects", timeout=30000)


def wait_for_projects_page(page, *, timeout: float = 10000) -> None:
    """Wait until ``/projects`` has rendered.

    The page no longer has an ``<h1>Projects</h1>`` — the section tab strip
    (AppSectionTabs) names the page instead, so wait on that link. ``exact``
    keeps this off the Curio logo link, whose accessible name is "Curio".
    """
    page.get_by_role("link", name="Projects", exact=True).wait_for(timeout=timeout)


def project_card(page, name: str):
    """The ``/projects`` card whose title is *name*, scoped to the card grid.

    Not ``get_by_text(name)``: the browse rebuild auto-selects the first card so
    the detail drawer arrives populated, and that drawer renders the same name
    in an ``<h2>``. With one project on the page a bare text lookup therefore
    resolves to two elements and Playwright fails it as a strict mode violation.

    Keys off the two attributes ``ProjectsList.tsx`` exposes for exactly this -
    ``data-curio-projects-scroll`` on the scroller and ``data-project-id`` on
    each card - both of which the Jest suite already pins.
    """
    return page.locator(
        '[data-curio-projects-scroll="true"] [data-project-id]'
    ).filter(has_text=name)


def open_new_workflow(page) -> None:
    """From ``/projects``, click "+ New Dataflow" and wait for the canvas."""
    page.get_by_text("+ New Dataflow").click()
    page.wait_for_url("**/dataflow/**", timeout=15000)
    page.wait_for_load_state("domcontentloaded")


def signup_and_enter_new_workflow(
    page,
    base_url: str,
    *,
    name: str,
    username: str,
    password: str = DEFAULT_TEST_PASSWORD,
) -> None:
    """Sign up a user and navigate to a fresh empty dataflow canvas."""
    signup_e2e_user(
        page, base_url, name=name, username=username, password=password,
    )
    open_new_workflow(page)


# ---------------------------------------------------------------------------
# DB stubs for Playwright — the browser does not drive the signup form.
#
# ``/api/testing/stub-login`` creates or fetches a user and returns a fresh
# session token, which we install as the ``session_token`` cookie on the
# Playwright context. ``/api/testing/stub-project`` seeds a workflow row
# owned by that user so ``/projects`` has something to render. Both endpoints
# require ``CURIO_TESTING=1``; see ``backend/app/testing/routes.py``.
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "session_token"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 10.0,
) -> dict:
    """Unauthenticated JSON request, returning the parsed body.

    Uses ``urllib`` (stdlib only) to match the rest of this module instead
    of introducing a ``requests`` dependency. For routes behind ``require_auth``
    use :func:`api_json`, which carries the bearer token.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted local URL)
        body = resp.read().decode("utf-8") or "{}"
        return json.loads(body)


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    """POST *payload* as JSON to *url* and return the parsed JSON body."""
    return _request_json(url, method="POST", payload=payload, timeout=timeout)


def _get_json(url: str, timeout: float = 10.0) -> dict:
    """GET *url* and return the parsed JSON body."""
    return _request_json(url, method="GET", timeout=timeout)


def api_json(
    url: str,
    token: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 10.0,
    raw: bool = False,
    extra_headers: dict | None = None,
):
    """Authenticated JSON request against the backend, stdlib only.

    The escape hatch for asserting backend state from a browser test: it makes a
    seeding or persistence problem fail in about a second with the offending
    payload, instead of as a 15-second locator timeout that says nothing about
    which side broke.

    ``extra_headers`` carries anything the target needs beyond the bearer token.
    The sandbox is the case that needs it: its code-execution routes require a
    shared secret rather than a user token (see the ``sandbox_auth_headers``
    fixture).
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted local URL)
        body = resp.read()
        # ``raw`` for binary endpoints (e.g. a .curio.zip archive), where the
        # point is the bytes rather than a JSON document.
        return body if raw else json.loads(body.decode("utf-8") or "{}")


def require_owner_view(page, *, timeout: float = 4000) -> None:
    """Fail when the dataflow opened read-only as the shared guest.

    This used to ``pytest.skip`` here, and that was the wrong call. A dataflow's
    packages, datasets and agents are visible only to the user who installed
    them, so a browser that lands as the shared guest sees empty catalogs -
    which means every test guarded by this is testing nothing. Skipping made
    that invisible: ``scripts/test.sh`` booted its shared stack without
    ``--auth``, and 43 tests across 22 files - the whole agent-catalog suite
    among them - quietly skipped while the run reported green.

    The environment being wrong is a setup bug, and a setup bug should be loud.
    Detection is unchanged; only the consequence is. The fix when this fires is
    to boot with ``--auth`` (which ``scripts/test.sh`` and the
    ``curio_servers`` fixture both now do), never to tolerate the state.
    """
    banner = page.get_by_test_id("shared-view-banner")
    try:
        banner.wait_for(state="visible", timeout=timeout)
    except PlaywrightTimeoutError:
        return  # no banner → authenticated owner, proceed
    raise AssertionError(
        "Dataflow opened read-only as the shared guest, so this test would "
        "assert against empty catalogs. The stack is running without user "
        "auth: boot it with `--auth` (scripts/test.sh does, and so does the "
        "curio_servers fixture), or unset CURIO_NO_AUTH in the pytest "
        "environment so the fixture passes --auth for you."
    )


_TOOLS_PALETTES = {
    "packages": ("#packages-palette", "Open node package palette", "Package templates"),
    "datasets": ("#datasets-palette", "Open dataset palette", "Dataset palette"),
    "agents": ("#agents-palette", "Open agent palette", "Agent palette"),
}


def open_tools_palette(page, kind: str):
    """Open one of the left-rail tool palettes and return its panel locator.

    Re-callable: the trigger's ``title`` flips to ``Close …`` once open, so this
    matches either title and only clicks when the panel is not already showing.
    That matters for a test that needs both palettes, because they are mutually
    exclusive (``ToolsMenu`` keeps a single ``activePalette``) and opening one
    closes the other, so coming back to the first one is a normal thing to do.

    ``force=True`` because the ReactFlow pane overlaps the rail.
    """
    try:
        root_sel, trigger_title, panel_name = _TOOLS_PALETTES[kind]
    except KeyError:
        raise ValueError(
            f"kind must be one of {sorted(_TOOLS_PALETTES)}, got {kind!r}"
        ) from None
    close_title = trigger_title.replace("Open ", "Close ", 1)
    trigger = page.locator(
        f'{root_sel} button[title="{trigger_title}"], '
        f'{root_sel} button[title="{close_title}"]'
    )
    trigger.wait_for(state="visible", timeout=30000)
    panel = page.locator(root_sel).get_by_role("region", name=panel_name)
    if panel.count() == 0 or not panel.first.is_visible():
        trigger.click(force=True)
    panel.wait_for(state="visible", timeout=10000)
    return panel


def close_tools_palette(page, kind: str) -> None:
    """Close a left-rail tool palette, if it is open.

    The open panel is ~545px wide and floats *over* the canvas, so it covers the
    left third of the drop area. That is invisible to ``drag_to_canvas`` (which
    dispatches its drop on the pane directly, without hit-testing) but not to
    ``connect_nodes``, which fails when another element is topmost at a handle's
    centre. A test that drops a dataset row and then wires the graph therefore
    has to give the canvas back once the row has been dragged.

    Idempotent and safe to call when nothing is open, mirroring
    ``open_tools_palette``.
    """
    try:
        root_sel, trigger_title, panel_name = _TOOLS_PALETTES[kind]
    except KeyError:
        raise ValueError(
            f"kind must be one of {sorted(_TOOLS_PALETTES)}, got {kind!r}"
        ) from None
    panel = page.locator(root_sel).get_by_role("region", name=panel_name)
    if panel.count() == 0 or not panel.first.is_visible():
        return
    close_title = trigger_title.replace("Open ", "Close ", 1)
    # ``force=True`` because the ReactFlow pane overlaps the rail.
    page.locator(f'{root_sel} button[title="{close_title}"]').click(force=True)
    panel.first.wait_for(state="hidden", timeout=10000)


def install_session_cookie(page, frontend_url: str, token: str) -> None:
    """Install *token* as the ``session_token`` cookie on *page*'s context.

    Mirrors what ``setToken`` does in ``utils/authApi.ts`` (``js-cookie``
    defaults: path=/``, host-only, no ``Secure`` on http). Playwright derives
    the domain from ``url`` when neither ``domain`` nor ``path`` is set, so
    the SPA's ``Cookies.get("session_token")`` finds the same value.
    """
    page.context.add_cookies(
        [
            {
                "name": SESSION_COOKIE_NAME,
                "value": token,
                "url": frontend_url,
            }
        ]
    )


def _await_session(backend_url: str, token: str, *, timeout: float = 10.0) -> None:
    """Block until *token* authenticates, or fail saying it never did.

    Not defensive padding - it closes a real race in this harness. The autouse
    ``e2e_clean_db`` truncates ``user`` / ``user_session`` straight out of the
    sqlite file from the pytest process, before and after every test, while the
    backend serves threaded off a pooled connection. A pooled reader can hold a
    snapshot taken before the row this call just created, and the next
    ``require_auth`` request then answers 401.

    A browser test never notices: a page load stands between the stub-login and
    the first authenticated request. A test that drives the API directly fires
    the next request microseconds later, which is where the race became visible
    (an intermittent 401 on one parameter of ``test_agent_runs_e2e.py``). Wait
    for the state we just asked for instead of assuming it landed.
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            api_json(f"{backend_url}/api/auth/me", token)
            return
        except HTTPError as exc:  # noqa: PERF203 - the retry IS the point
            if exc.code != 401:
                raise
            last = f"HTTP {exc.code}"
        except URLError as exc:
            last = str(exc)
        time.sleep(0.05)
    raise AssertionError(
        f"a freshly stubbed session never authenticated within {timeout}s "
        f"(last: {last or 'unknown'}) - the backend may not be up, or the DB "
        f"was truncated after the token was issued"
    )


def stub_db_user(
    backend_url: str,
    *,
    username: str,
    name: str,
    password: str = DEFAULT_TEST_PASSWORD,
    email: str | None = None,
    project_name: str | None = None,
    project_spec: dict | None = None,
) -> dict:
    """Seed a user (and optionally a project) over HTTP. No browser involved.

    The half of :func:`stub_db_login` that does not touch Playwright, split out
    for tests that live in this suite to reuse ``curio_servers`` but drive the
    backend directly - ``test_agent_runs_e2e.py``, like
    ``test_library_install_integration.py`` before it, requests no ``page``.

    Returns ``{user, token, created}``, plus ``project`` when one was stubbed.
    """
    payload = {"username": username, "name": name, "password": password}
    if email is not None:
        payload["email"] = email
    login = _post_json(f"{backend_url}/api/testing/stub-login", payload)
    _await_session(backend_url, login["token"])

    if project_name is not None:
        project_payload: dict = {"username": username, "name": project_name}
        if project_spec is not None:
            project_payload["spec"] = project_spec
        login["project"] = _post_json(
            f"{backend_url}/api/testing/stub-project", project_payload,
        )
    return login


def stub_db_login(
    page,
    frontend_url: str,
    backend_url: str,
    *,
    username: str,
    name: str,
    password: str = DEFAULT_TEST_PASSWORD,
    email: str | None = None,
    project_name: str | None = None,
    project_spec: dict | None = None,
) -> dict:
    """DB stub helper for Curio E2E tests.

    Creates (or re-uses) *username* directly via ``/api/testing/stub-login``,
    installs the returned session token as the browser cookie, and — when
    ``project_name`` is provided — seeds a workflow row owned by that user
    via ``/api/testing/stub-project`` so the ``/projects`` list page has
    content to render.

    Returns the parsed ``stub-login`` JSON (``{user, token, created}``),
    augmented with ``project`` when one was stubbed.

    The HTTP half is :func:`stub_db_user`; this adds the browser cookie. A test
    with no browser calls that one directly.
    """
    login = stub_db_user(
        backend_url,
        username=username,
        name=name,
        password=password,
        email=email,
        project_name=project_name,
        project_spec=project_spec,
    )
    install_session_cookie(page, frontend_url, login["token"])
    return login


def stub_login_and_enter_workflow(
    page,
    frontend_url: str,
    backend_url: str,
    *,
    username: str,
    name: str,
    password: str = DEFAULT_TEST_PASSWORD,
    project_name: str = "StubbedDataflow",
    project_spec: dict | None = None,
) -> dict:
    """DB-stubbed fast-path into an empty dataflow canvas.

    Creates the user + an empty project directly via
    ``/api/testing/stub-login`` and ``/api/testing/stub-project``, installs
    the session cookie on the Playwright context, and navigates straight to
    ``/dataflow/<project_id>`` — **no UI interaction**. Returns the full
    ``stub_db_login`` payload (``{user, token, created, project}``).

    This skips both the signup form and the "+ New Dataflow" click on
    ``/projects`` so the class-scoped ``loaded_workflow`` fixture spends its
    warm-up time on the actual workflow upload instead of UI plumbing.
    """
    result = stub_db_login(
        page,
        frontend_url=frontend_url,
        backend_url=backend_url,
        username=username,
        name=name,
        password=password,
        project_name=project_name,
        project_spec=project_spec,
    )
    project_id = result["project"]["id"]
    page.goto(f"{frontend_url}/dataflow/{project_id}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=15000)
    return result


# ---------------------------------------------------------------------------
# Reusable upload helper
# ---------------------------------------------------------------------------

def upload_workflow(
    page, app_frontend, workflow_file: str, expected_node_count: int
):
    """Open the File menu on the current workflow canvas, upload a workflow
    JSON and wait until the expected number of nodes render.

    The caller is expected to have already navigated ``page`` to a
    ``/dataflow/...`` route (e.g. via ``signup_and_enter_new_workflow``).
    """
    debug_log(
        "fixtures.py:upload_workflow",
        "upload_workflow called",
        {
            "page_type": type(page).__name__,
            "app_frontend_type": type(app_frontend).__name__,
            "workflow_file": workflow_file,
            "expected_node_count": expected_node_count,
            "page_is_closed": page.is_closed(),
            "page_url": str(page.url),
        },
        "H1,H2,H3",
    )
    page.wait_for_load_state("domcontentloaded")

    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PlaywrightError:
        pass

    file_menu_btn = page.get_by_role("button", name=re.compile("File"))
    file_menu_btn.wait_for(state="visible", timeout=60000)
    file_menu_btn.scroll_into_view_if_needed()
    # force=True so the click isn't captured by the ReactFlow canvas layer
    file_menu_btn.click(force=True)

    # Click "Load dataflow" and upload the JSON file
    load_spec = page.get_by_role("button", name="Load dataflow")
    load_spec.wait_for(state="visible", timeout=15000)
    assert load_spec.is_visible()

    with page.expect_file_chooser() as fc_info:
        # The role locator, not get_by_text: the File menu row is a <div>
        # wrapping a <button> carrying the same label (UpMenu.tsx), so the text
        # engine matches both and the click dies of a strict-mode violation.
        load_spec.click()
    fc_info.value.set_files(workflow_file)

    # Wait until all expected nodes have rendered on the ReactFlow canvas
    page.wait_for_function(
        f"document.querySelectorAll('.react-flow__node').length >= "
        f"{expected_node_count}",
        timeout=60000,
    )
    # hide the tools menu bar so it doesn't interfere with the test
    # get parent of #step-loading
    step_loading = page.locator("#step-loading")
    tools_menu_bar = step_loading.locator("..")
    if tools_menu_bar.count() >= 1:
        page.evaluate(
            "element => { element.style.display = 'none'; }",
            tools_menu_bar.element_handle() # Pass the ElementHandle to the evaluate function
        )

        assert tools_menu_bar.is_hidden() is True, (
            f"Tools menu bar is not hidden"
        )


# ---------------------------------------------------------------------------
# Canvas authoring helpers (drag a node in, connect it, give it code, run it)
# ---------------------------------------------------------------------------
#
# Everything above builds a canvas by *loading* a dataflow (a Trill JSON through
# the File menu, or a spec seeded into the DB). These helpers cover the other
# half: what a user does by hand. They are deliberately DOM/event driven rather
# than store driven, because the two are not equivalent -
# ``window.__curio_reactFlow.setNodes`` writes only React Flow's zustand store,
# and ReactFlow's ``useStoreUpdater`` pushes the provider's node array straight
# back over it on the next render, so a node (or a code edit) injected that way
# silently disappears.

CANVAS_DROP_TARGET = ".curio-canvas-drop-target"

# One HTML5 drag, start to finish, on the elements the app actually listens to.
#
# ``dragstart`` has to be fired on the SOURCE, not just the drop constructed by
# hand: the built-in tiles and the package palette rows put their payload on
# ``dataTransfer`` inside their own ``onDragStart``, and dataset rows go further
# and stash the payload in a module singleton via ``beginDatasetDrag`` (the
# canvas reads that singleton in preference to ``getData``, because custom MIME
# types do not round-trip reliably). Skipping ``dragstart`` therefore drops an
# empty payload, which ``handleDrop`` ignores without a word.
_DRAG_TO_CANVAS_JS = r"""({ source, targetSelector, clientX, clientY }) => {
    const target = document.querySelector(targetSelector);
    if (!target) return `no drop target matching ${targetSelector}`;
    // The identifying attribute and the draggable element are not always the
    // same node: a dataset palette row carries data-dataset-id on its wrapper
    // and puts onDragStart on an inner grip, so dispatching on the wrapper
    // would fire nothing (events bubble up, never down). Built-in tiles and
    // package rows are themselves draggable, so this resolves to the element
    // itself for them.
    const dragSource = source.hasAttribute("draggable")
        ? source
        : source.querySelector("[draggable]");
    if (!dragSource) return "source has no draggable element";
    const dataTransfer = new DataTransfer();
    const fire = (el, type, coords) => {
        el.dispatchEvent(new DragEvent(type, {
            bubbles: true,
            cancelable: true,
            dataTransfer,
            ...(coords || {}),
        }));
    };
    const coords = { clientX, clientY };
    fire(dragSource, "dragstart", coords);
    // dragover before drop: handleDragOver is where the canvas sets dropEffect,
    // and a dataset drag ("copy") is refused outright by a browser that saw
    // effectAllowed "move".
    fire(target, "dragover", coords);
    fire(target, "drop", coords);
    fire(dragSource, "dragend", coords);
    return "ok";
}"""


def canvas_nodes(page) -> list[dict]:
    """Every node on the canvas as ``{"id", "nodeType"}``.

    Projected, not returned raw: ``node.data`` holds a ``PythonInterpreter``
    instance and the ``outputCallback`` / ``propagationCallback`` closures, and
    Playwright cannot serialize either, so handing back the real nodes fails
    with an unhelpful "Unexpected value" from inside evaluate().
    """
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
    return page.evaluate(
        """() => window.__curio_reactFlow.getNodes().map((n) => ({
            id: n.id,
            nodeType: (n.data && n.data.nodeType) || null,
        }))"""
    )


def canvas_node_type(page, node_id: str) -> str | None:
    """The ``data.nodeType`` of one canvas node.

    Every node renders as the single React Flow type ``__curioUniversalNode``,
    so the DOM cannot tell a loader from a transformation; the real kind only
    exists in node data.
    """
    for node in canvas_nodes(page):
        if node["id"] == node_id:
            return node["nodeType"]
    return None


def node_locator(page, node_id: str):
    """Return a Playwright ``Locator`` for a ReactFlow node element."""
    return page.locator(f'.react-flow__node[data-id="{node_id}"]')


def enable_save_output(page, node_id: str) -> None:
    """Turn on one node's save-output toggle, so running it leaves a dataset.

    The database-icon switch beside the play button, and it is **off by
    default** (``CURIO_DEFAULT_SAVE_NODE_OUTPUT``, documented in
    ``docs/DATA-CATALOG.md``). With it off a run writes a parquet under
    ``.curio/data/`` and stops there: ``routes.py`` gates the auto-install on
    ``save_output_dataset``, so no ``computed.<dataflow>.<node>@1`` is ever
    installed into the account store.

    A test that runs a producing node and then looks for its dataset in a
    catalog therefore has to flip this first. Three catalog tests did not, and
    passed anyway for years because the per-user store outlived ``reset-db`` and
    held 37 ``computed.*`` rows from earlier runs - a ``computed.``-prefixed
    card was always there to find, just never this test's.

    Clicks the label rather than the input: the checkbox is visually hidden by
    ``SaveOutputToggle.module.css``, so ``check()`` fails actionability. Scoped
    inside the node because the id is built from Curio's ``data.nodeId``, which
    a caller holding React Flow's ``data-id`` cannot assume it has.
    """
    node = node_locator(page, node_id)
    box = node.locator('input[id^="save-output-"]').first
    box.wait_for(state="attached", timeout=15000)
    if box.is_checked():
        return
    node.locator('label:has(input[id^="save-output-"])').first.click()
    expect(box).to_be_checked(timeout=10000)


def save_dataflow(page, *, timeout: float = 30000) -> None:
    """Save the open dataflow through the File menu, and wait for the write.

    Gates on the write itself rather than on the File menu closing: the menu can
    close before the PUT is answered, and a test that then reads the server sees
    the pre-save spec.
    """
    file_btn = page.get_by_role("button", name=re.compile("File"))
    file_btn.wait_for(state="visible", timeout=15000)
    file_btn.click(force=True)
    save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
    save_btn.wait_for(state="visible", timeout=10000)
    with page.expect_response(
        lambda r: "/api/projects" in r.url
        and r.request.method in ("POST", "PUT")
        and r.ok,
        timeout=timeout,
    ):
        save_btn.click()
    save_btn.wait_for(state="hidden", timeout=timeout)


def frame_node(page, node_id: str, *, zoom: float = 0.9,
               settle_ms: float = 1000) -> None:
    """Pan and zoom the canvas so one node fills the frame.

    For scenes whose subject is *inside* a node. The baseline harness fits the
    viewport to the whole dataflow, which is right for a scene about the graph
    and wrong for one about a chart: at fit zoom a 525x350 node is a ~90x60
    thumbnail, and a screenshot of it cannot show what the scene claims. The
    `05-vega-lite-multi-view-drilldown` example has 28 nodes, so its captures
    were two near-identical canvas wallpapers.

    Keeps the full 1280x720 frame rather than clipping to the node, so the
    surrounding canvas still reads as context.

    ``window.__curio_reactFlow`` is the instance ``MainCanvas.tsx`` exposes for
    exactly this; ``setCenter`` takes flow coordinates, hence the node's own
    position plus half its measured size.
    """
    page.evaluate(
        """({ nodeId, zoom }) => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const node = rf.getNodes().find((n) => n.id === nodeId);
            if (!node) return;
            const w = node.width || node.measured?.width || 525;
            const h = node.height || node.measured?.height || 350;
            rf.setCenter(node.position.x + w / 2, node.position.y + h / 2, {
                zoom, duration: 700,
            });
        }""",
        {"nodeId": node_id, "zoom": zoom},
    )
    page.wait_for_timeout(settle_ms)


def drag_to_canvas(page, source, *, at: tuple[float, float] | None = None,
                   timeout: float = 15000) -> str:
    """Drag *source* onto the canvas and return the id of the node it created.

    *source* is a locator for anything draggable that the canvas accepts: a
    built-in palette tile (``#step-transformation``), a package palette row
    (``[data-pkg-template-id="..."]``), or a dataset row/card
    (``[data-dataset-id="..."]``). *at* is an offset from the pane's top-left
    corner; the pane centre is used when omitted.

    Mind the geometry when dropping more than one node: a node renders 525x350
    at zoom 1, so offsets less than ~600px apart horizontally overlap, and the
    later node's body then covers the earlier one's connection handle. In a
    1280x720 viewport, ``(150, 150)`` and ``(760, 150)`` is a pair that leaves
    both facing handles exposed.

    Ids are ``uuid4`` and assigned inside ``createCodeNode``, so the only way to
    learn the new one is to diff the canvas before and after.
    """
    before = {node["id"] for node in canvas_nodes(page)}

    # Wait for the drag SOURCE too, not just the drop target. A tile that is
    # attached but not yet interactive produces an empty dataTransfer payload,
    # and the drop then silently creates nothing - which surfaces much later as
    # the "Drop produced no node" assertion below, blaming the canvas.
    source.wait_for(state="visible", timeout=timeout)

    pane = page.locator(CANVAS_DROP_TARGET)
    pane.wait_for(state="visible", timeout=timeout)
    box = pane.bounding_box()
    assert box, f"{CANVAS_DROP_TARGET} has no layout box"
    if at is None:
        client_x = box["x"] + box["width"] / 2
        client_y = box["y"] + box["height"] / 2
    else:
        client_x = box["x"] + at[0]
        client_y = box["y"] + at[1]

    source.wait_for(state="visible", timeout=timeout)
    source.scroll_into_view_if_needed()
    result = page.evaluate(
        _DRAG_TO_CANVAS_JS,
        {
            "source": source.element_handle(),
            "targetSelector": CANVAS_DROP_TARGET,
            "clientX": client_x,
            "clientY": client_y,
        },
    )
    assert result == "ok", f"drag to canvas failed: {result}"

    try:
        page.wait_for_function(
            "(n) => window.__curio_reactFlow.getNodes().length > n",
            arg=len(before),
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            "Drop produced no node. Either the drag payload was empty (the "
            "source's own onDragStart did not run) or the canvas is refusing "
            "drops (dashboard mode / shared read-only view)."
        ) from None

    created = [n for n in canvas_nodes(page) if n["id"] not in before]
    assert len(created) == 1, (
        f"expected exactly one new node, got {created}"
    )
    node_id = created[0]["id"]
    node_locator(page, node_id).wait_for(state="visible", timeout=timeout)
    return node_id


# Monaco is bundled and pinned on ``window`` by index.tsx, so the editor
# instance is reachable; it is found by DOM containment because a canvas holds
# one editor per code node and ``getEditors()`` returns all of them.
_SET_NODE_CODE_JS = r"""({ nodeId, code }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!nodeEl) return "node is not on the canvas";
    const editorEl = nodeEl.querySelector(".monaco-editor");
    if (!editorEl) return "node has no code editor";
    const editors = (window.monaco && window.monaco.editor
        && window.monaco.editor.getEditors && window.monaco.editor.getEditors()) || [];
    const match = editors.find((e) => editorEl.contains(e.getDomNode()));
    if (!match) return "no monaco instance owns this node's editor";
    match.setValue(code);
    return "ok";
}"""

_NODE_CODE_IS_JS = r"""({ nodeId, code }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
    if (!editorEl) return false;
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const match = editors.find((e) => editorEl.contains(e.getDomNode()));
    return !!match && match.getValue() === code;
}"""


def set_node_code(page, node_id: str, code: str, *, timeout: float = 15000) -> None:
    """Replace a code node's source with *code*.

    Goes through Monaco's ``setValue``, which fires
    ``onDidChangeModelContent`` -> ``handleCodeChange`` -> ``setCode`` ->
    ``floatCode`` -> ``data.code``. That last hop is the only thing that
    publishes editor text to the node, so this is the same path a keystroke
    takes rather than a back door around it.

    Do not reach for ``page.keyboard.type`` instead: the editor runs with
    ``autoClosingBrackets: "always"`` and ``formatOnType: true``, so typed
    Python comes back with extra brackets and re-indentation and never
    round-trips.
    """
    node_el = node_locator(page, node_id)
    node_el.scroll_into_view_if_needed()
    # The pane stays mounted when inactive, so the editor exists either way,
    # but activating the tab keeps a failure legible in --headed runs.
    code_tab = node_el.locator('.nav-link[data-rr-ui-event-key="code"]').first
    try:
        code_tab.wait_for(state="visible", timeout=2000)
        if "active" not in (code_tab.get_attribute("class") or ""):
            code_tab.dispatch_event("click")
    except PlaywrightTimeoutError:
        pass
    node_el.locator(".monaco-editor").first.wait_for(state="visible", timeout=timeout)

    deadline = time.time() + timeout / 1000
    result = None
    while True:
        result = page.evaluate(_SET_NODE_CODE_JS, {"nodeId": node_id, "code": code})
        if result == "ok" or time.time() >= deadline:
            break
        page.wait_for_timeout(250)
    assert result == "ok", f"could not set code on node {node_id}: {result}"

    # setValue is synchronous but the React round-trip to data.code is not, so
    # confirm the editor is actually holding the new text before running it.
    page.wait_for_function(
        _NODE_CODE_IS_JS, arg={"nodeId": node_id, "code": code}, timeout=timeout
    )


def read_node_code(page, node_id: str, *, timeout: float = 15000) -> str:
    """Return the Python/JS source a code node currently holds.

    Reads Monaco rather than ``data.code`` because the editor is what the run
    actually sends, and because node data cannot be serialized out of the page
    (see ``canvas_nodes``).
    """
    node_el = node_locator(page, node_id)
    node_el.locator(".monaco-editor").first.wait_for(state="attached", timeout=timeout)
    code = page.evaluate(
        """(nodeId) => {
            const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
            const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
            if (!editorEl) return null;
            const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
            const match = editors.find((e) => editorEl.contains(e.getDomNode()));
            return match ? match.getValue() : null;
        }""",
        node_id,
    )
    assert code is not None, f"could not read code from node {node_id}"
    return code


def _handle_locator(page, node_id: str, handle_id: str):
    return page.locator(
        f'.react-flow__node[data-id="{node_id}"] '
        f'.react-flow__handle[data-handleid="{handle_id}"]'
    )


def connect_nodes(page, source_id: str, target_id: str, *,
                  source_handle: str = "out", target_handle: str = "in",
                  timeout: float = 15000) -> str:
    """Drag an edge from *source_id*'s output handle to *target_id*'s input.

    Returns the edge id, which React Flow derives deterministically as
    ``reactflow__edge-<source><sourceHandle>-<target><targetHandle>``.

    Uses real pointer moves rather than a synthetic event pair, because React
    Flow tracks a connection through pointermove on the pane and never sees a
    lone pointerup on the target handle. The intermediate moves matter for the
    same reason. Coordinates come from ``bounding_box()`` so the viewport's CSS
    transform is already baked in.
    """
    src = _handle_locator(page, source_id, source_handle)
    tgt = _handle_locator(page, target_id, target_handle)
    for locator, node_id, handle_id in (
        (src, source_id, source_handle), (tgt, target_id, target_handle)
    ):
        try:
            locator.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeoutError:
            raise AssertionError(
                f"node {node_id} has no {handle_id!r} handle - check the "
                f"node type's manifest ports (a data-loading node has no "
                f"input, and a bidirectional node uses 'in/out')"
            ) from None
    src.scroll_into_view_if_needed()
    src_box, tgt_box = src.bounding_box(), tgt.bounding_box()
    assert src_box and tgt_box, "connection handles have no layout box"

    # React Flow starts and ends a connection by hit-testing whatever sits under
    # the pointer, so a handle that is merely *present* is not enough: if another
    # node's body overlaps it, mousedown lands on that instead and the whole drag
    # is a silent no-op. Check it up front, because the symptom otherwise is an
    # unexplained "no edge" 15 seconds later.
    for locator, node_id, handle_id in (
        (src, source_id, source_handle), (tgt, target_id, target_handle)
    ):
        covering = locator.evaluate(
            """(el) => {
                const r = el.getBoundingClientRect();
                const top = document.elementFromPoint(
                    r.x + r.width / 2, r.y + r.height / 2
                );
                if (!top) return "nothing (the handle is outside the viewport)";
                if (top === el || el.contains(top)) return null;
                return `<${top.tagName.toLowerCase()} class="${top.className}">`;
            }"""
        )
        if covering:
            raise AssertionError(
                f"node {node_id}'s {handle_id!r} handle is not the topmost "
                f"element at its own centre; {covering} is. Space the nodes "
                f"further apart when dropping them (a node is 525x350 at "
                f"zoom 1) or scroll the handle into view."
            )

    src_x = src_box["x"] + src_box["width"] / 2
    src_y = src_box["y"] + src_box["height"] / 2
    tgt_x = tgt_box["x"] + tgt_box["width"] / 2
    tgt_y = tgt_box["y"] + tgt_box["height"] / 2

    page.mouse.move(src_x, src_y)
    page.mouse.down()
    page.mouse.move(tgt_x, tgt_y, steps=16)
    # A second move on the spot: React Flow only marks a handle "connectable"
    # from a pointermove it receives while already over it.
    page.mouse.move(tgt_x, tgt_y)
    page.mouse.up()

    edge_id = (
        f"reactflow__edge-{source_id}{source_handle}-{target_id}{target_handle}"
    )
    try:
        page.wait_for_function(
            """({ source, target }) => (window.__curio_reactFlow.getEdges() || [])
                .some((e) => e.source === source && e.target === target)""",
            arg={"source": source_id, "target": target_id},
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"no edge from {source_id} to {target_id} after the drag. A "
            f"rejected connection toasts instead of throwing (cycle, or "
            f"incompatible ports), so check the canvas for a toast."
        ) from None
    page.locator(f'[data-testid="rf__edge-{edge_id}"]').wait_for(
        state="attached", timeout=timeout
    )
    return edge_id


_HEAVY_NODE_TYPES = {
    "AUTK_GRAMMAR",
    "DATA_LOADING",
    "DATA_TRANSFORMATION",
    "COMPUTATION_ANALYSIS",
}


def node_execution_timeout_ms(node_type: str) -> int:
    """Return a generous timeout for nodes that execute heavy data ops.

    AUTK_GRAMMAR shares the data-node budget: a node with a `data` section
    runs it in the backend sandbox - autk-db parses a local OSM PBF
    (multi-MB) via DuckDB-WASM in Node and round-trips the layers back over
    HTTP. This is deterministic and fast now that the data is local: a
    1.6 MB PBF (171k features) parses in ~12 s including cold-start WASM
    init, and the largest bundled PBF is ~6 MB, so 2 min is ~2.5x the
    worst case. The old 5-min budget dated from the Overpass era (a remote,
    throttled OSM endpoint), which has since been removed - a node that now
    runs past this budget is hung, not slow, so fail it.

    Accepts either the legacy uppercase name a ``NodeSpec`` carries
    (``DATA_LOADING``) or the namespaced id the frontend uses on the wire
    (``curio.builtin/data-loading``).
    """
    canonical = (node_type or "").rsplit("/", 1)[-1].split("@", 1)[0]
    canonical = canonical.replace("-", "_").upper()
    return 120000 if canonical in _HEAVY_NODE_TYPES else 30000


def read_node_error_text(node_el) -> str | None:
    """Return the error message text from a code node's inline output
    area. Returns ``None`` if it cannot be read.

    Works for both autk behavior nodes and Python/JS code nodes:
    CodeEditor renders any output (success or error) into the same output box,
    the one carrying the ``[N]:`` counter. For autk,
    ``autkBehaviorFactory``'s catch block sets
    ``output = { code: 'error', content: err.message }``; for
    COMPUTATION_ANALYSIS / DATA_LOADING / DATA_TRANSFORMATION the
    sandbox's stderr/exception traceback is routed there too. We
    switch to the code tab so that area is in the layout, then read
    it.
    """
    try:
        code_tab = node_el.locator(
            '.nav-link[data-rr-ui-event-key="code"]'
        ).first
        try:
            code_tab.wait_for(state="visible", timeout=2000)
            if "active" not in (code_tab.get_attribute("class") or ""):
                code_tab.click(force=True)
        except Exception:
            # Some autk nodes may not expose a code tab depending on
            # NodeEditor config; fall through and read whatever is
            # currently visible.
            pass
        output_area = node_el.locator("[data-curio-node-output]").first
        output_area.wait_for(state="visible", timeout=2000)
        return output_area.text_content()
    except Exception:
        return None


def read_node_output_text(page, node_id: str, *, timeout: float = 10000) -> str:
    """Return the text of a code node's inline output box.

    Reads ``[data-curio-node-output]`` rather than ``.nowheel.nodrag``: that
    class sits on the editor wrapper too, and the wrapper's ``textContent``
    starts with every line of code Monaco has rendered.

    The text is the Jupyter-style counter followed by the result, e.g.
    ``"[1]:Saved to file: xyz"`` or ``"[ ]:No output yet"``.
    """
    box = node_locator(page, node_id).locator("[data-curio-node-output]").first
    box.wait_for(state="visible", timeout=timeout)
    return box.text_content() or ""


def activate_header_icon(locator) -> None:
    """Press one of a node header's icon buttons (the pencil, the settings cog).

    Two reasons a normal click does not work here. The buttons activate on
    ``pointerdown`` + ``pointerup`` and deliberately swallow the native click
    (``useHeaderIconDragClick``, so that press-and-drag still moves the node),
    and app chrome overlaps the header band at the top of the canvas, which means
    a real click at the button's centre is delivered to the overlay instead.
    Dispatching the two pointer events skips hit-testing entirely, the same way
    the play button's ``dispatch_event("click")`` does.

    The drag threshold is satisfied for free: a dispatched event carries
    ``clientX``/``clientY`` of 0, so down and up read as the same point.
    """
    locator.wait_for(state="attached", timeout=15000)
    locator.dispatch_event("pointerdown")
    locator.dispatch_event("pointerup")


# Any of these proves the play click was honoured: the header swaps the play SVG
# for a spinner, the status attribute leaves "idle", or the inline counter flips
# from "[ ]:" to "[*]:".
_PLAY_ACKNOWLEDGED_JS = r"""(nodeId) => {
    const el = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!el) return false;
    if (el.querySelector('.spinner-border')) return true;
    const status = el.querySelector('[data-curio-node-status]');
    if (status && status.getAttribute('data-curio-node-status') !== 'idle') return true;
    const texts = [...el.querySelectorAll('[data-curio-node-output], span')]
        .map(e => e.textContent);
    return texts.some(
        t => /\[(\d+|\*)\]:/.test(t) || /^(Running|Done|Error)$/.test(t.trim())
    );
}"""


def play_node(page, node_id: str, *, max_attempts: int = 3) -> None:
    """Click *play* on one node and confirm execution actually started.

    Note this runs the node's not-yet-successful ancestors too
    (``playNodesUpTo``), so playing the tail of a chain is enough to run it.

    We don't use ``play_btn.click(force=True)`` - ``force=True`` skips
    actionability checks so React Flow's transformed viewport, pointer
    events, or an overlay can swallow the click. And the button is an
    ``<svg>`` (FontAwesomeIcon), so ``SVGElement`` has no native ``click()``
    and calling it through evaluate raises ``TypeError``.
    ``dispatch_event("click")`` sends a bubbling synthetic ``MouseEvent``
    that React's onClick picks up regardless of where the element actually
    sits on screen.
    """
    node_el = node_locator(page, node_id)
    node_el.scroll_into_view_if_needed()
    play_btn = node_el.locator("svg.fa-circle-play")

    last_error = None
    for _ in range(max_attempts):
        try:
            play_btn.wait_for(state="visible", timeout=10000)
            play_btn.dispatch_event("click")
            try:
                page.wait_for_function(
                    _PLAY_ACKNOWLEDGED_JS, arg=node_id, timeout=20000
                )
                return
            except PlaywrightTimeoutError:
                last_error = TimeoutError("No spinner or counter-flip within 20s")
        except PlaywrightTimeoutError as e:
            last_error = e
    raise AssertionError(
        f"Node {node_id} never acknowledged Play after {max_attempts} "
        f"attempts; click is being silently dropped (React handler likely "
        f"not bound). Last error: {last_error}"
    )


def wait_for_node_settled(page, node_id: str, *, node_type: str = "",
                          timeout_ms: int | None = None) -> str:
    """Block until a node finishes and return ``"done"`` or ``"error"``.

    Use this when a *failure* is the expected outcome (a node that needs a
    library nobody installed yet, say). Prefer ``wait_for_node_done`` otherwise:
    it fails with the node's own error text instead of handing back a status
    string the caller has to remember to check.
    """
    budget = timeout_ms or node_execution_timeout_ms(node_type)
    node_el = node_locator(page, node_id)
    try:
        page.wait_for_function(
            """(nodeId) => {
                const el = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-curio-node-status]`
                );
                if (!el) return false;
                const status = el.getAttribute('data-curio-node-status');
                return status === 'done' || status === 'error';
            }""",
            arg=node_id,
            timeout=budget,
        )
    except PlaywrightTimeoutError:
        raise PlaywrightTimeoutError(
            f"Node {node_id} ({node_type or 'unknown type'}) timed out after "
            f"{budget} ms"
        ) from None
    return node_el.locator("[data-curio-node-status]").first.get_attribute(
        "data-curio-node-status"
    ) or "idle"


def wait_for_node_done(page, node_id: str, *, node_type: str = "",
                       timeout_ms: int | None = None) -> None:
    """Block until a node reports success, and fail loudly if it errors.

    Keys off ``data-curio-node-status`` rather than the header's "Done" /
    "Error" text, so the wait does not depend on that copy. A node that never
    settles is a hard timeout failure: there is no tolerance and no retry, since
    all data is local and deterministic.
    """
    status = wait_for_node_settled(
        page, node_id, node_type=node_type, timeout_ms=timeout_ms
    )
    if status == "error":
        detail = read_node_error_text(node_locator(page, node_id))
        raise AssertionError(
            f"Node {node_id} ({node_type or 'unknown type'}) execution failed "
            f"with Error"
            + (f"\n--- node error output ---\n{detail}" if detail else "")
        )


def run_node_and_wait(page, node_id: str, *, node_type: str = "",
                      timeout_ms: int | None = None) -> str:
    """``play_node`` + ``wait_for_node_done``, returning the output text."""
    play_node(page, node_id)
    wait_for_node_done(page, node_id, node_type=node_type, timeout_ms=timeout_ms)
    return read_node_output_text(page, node_id)


# Shared by the wait_for_function poll and the final evaluate in
# ``assert_vega_canvas_rendered``; returns {width, height, nonBlank} or null.
VEGA_CANVAS_PROBE_JS = """(containerId) => {
    const el = document.getElementById(containerId);
    if (!el) return null;
    const canvas = el.querySelector('canvas');
    if (!canvas) return null;
    const w = canvas.width, h = canvas.height;
    if (!w || !h) return { width: w, height: h, nonBlank: false };
    let nonBlank = false;
    try {
        const ctx = canvas.getContext('2d');
        const { data } = ctx.getImageData(0, 0, w, h);
        for (let i = 0; i < data.length; i += 4) {
            const r = data[i], g = data[i + 1],
                  b = data[i + 2], a = data[i + 3];
            // any opaque, non-white pixel means a mark was drawn
            if (a !== 0 && !(r === 255 && g === 255 && b === 255)) {
                nonBlank = true;
                break;
            }
        }
    } catch (e) {
        // getImageData throws on a tainted canvas —
        // treat as drawn rather than failing.
        nonBlank = true;
    }
    return { width: w, height: h, nonBlank };
}"""


def assert_vega_canvas_rendered(page, node_id: str, *, timeout: float = 30000) -> None:
    """Assert a VIS_VEGA node actually drew marks from its upstream data.

    Vega-Lite renders to a ``<canvas>`` (the renderer switched from SVG in
    3a2a14a), so there is no DOM structure to diff - what can be checked is that
    the canvas exists, has a non-zero backing size, and is not blank. The
    container id is ``"vega" + nodeId``, a convention owned by ``useVega.ts``.

    Vega paints asynchronously after the canvas becomes visible, so on a slow
    runner the element can be attached and sized before any mark is drawn; a
    single pixel sample would race the paint. Poll until the probe reports drawn
    content, then take one final sample so a timeout still produces the detailed
    assertion message below rather than a bare Playwright timeout.
    """
    container_id = f"vega{node_id}"
    node_el = node_locator(page, node_id)
    canvas = node_el.locator(f"#{container_id} canvas")
    canvas.first.wait_for(state="visible", timeout=15000)
    assert canvas.count() >= 1, (
        f"Vega node {node_id} is missing its rendered canvas inside "
        f"#{container_id}"
    )

    try:
        page.wait_for_function(
            "(containerId) => {"
            f" const probe = {VEGA_CANVAS_PROBE_JS};"
            "  const info = probe(containerId);"
            "  return !!(info && info.width > 0"
            "        && info.height > 0 && info.nonBlank);"
            "}",
            arg=container_id,
            timeout=timeout,
            polling=500,
        )
    except PlaywrightTimeoutError:
        pass

    info = page.evaluate(VEGA_CANVAS_PROBE_JS, container_id)
    assert info is not None, (
        f"Vega node {node_id}: could not find a canvas inside #{container_id}"
    )
    assert info["width"] > 0 and info["height"] > 0, (
        f"Vega node {node_id}: canvas has zero backing size "
        f"({info['width']}x{info['height']})"
    )
    assert info["nonBlank"], (
        f"Vega node {node_id}: canvas rendered blank — no chart marks drawn "
        f"from the upstream data"
    )


def set_canvas_zoom(page, zoom: float, *, timeout: float = 15000) -> None:
    """Pin the ReactFlow viewport so several nodes fit before dropping them.

    A node is 525x350 flow units, so at zoom 1 a 1280x720 viewport has room for
    two side by side and no more (see ``drag_to_canvas``). Zooming out first is
    what makes a three-node chain authorable by drag: the drop coordinates stay
    viewport-relative, but each node paints ``525 * zoom`` px wide, so the
    spacing needed to keep facing handles exposed shrinks with it.

    Purely a camera change - node positions in flow space are unaffected, and
    ``save_workflow_test_screenshot`` re-pins its own fitView before capturing,
    so this does not influence a baseline.
    """
    page.wait_for_function(
        "() => !!window.__curio_reactFlow", timeout=timeout
    )
    page.evaluate(
        "(zoom) => window.__curio_reactFlow.setViewport({ x: 0, y: 0, zoom })",
        zoom,
    )


# ---------------------------------------------------------------------------
# Playwright page wrapper
# ---------------------------------------------------------------------------

class FrontendPage(Page):
    def __init__(self, frontend_server: str, page: Page):  # noqa
        debug_log(
            "utils.py:FrontendPage.__init__",
            "FrontendPage created",
            {
                "frontend_server": frontend_server,
                "page_type": type(page).__name__,
                "page_url": str(page.url),
                "page_is_closed": page.is_closed(),
            },
            "H1,H2,H3",
        )
        self.frontend_server = frontend_server
        self.base_url = frontend_server
        self.page = page
        self.browser_context = page.context

    def __getattribute__(self, item):
        try:
            return object.__getattribute__(self, item)
        except AttributeError:
            page = object.__getattribute__(self, "page")
            return object.__getattribute__(page, item)

    def set_language(self, language="en-US"):
        self.browser_context.set_extra_http_headers(
            {"Accept-Language": language}
        )

    def goto_page(self, path):
        url = f"{self.frontend_server}{path}"
        debug_log(
            "utils.py:goto_page",
            "About to navigate",
            {
                "url": url,
                "page_is_closed": self.page.is_closed(),
                "page_url": str(self.page.url),
                "has_impl_obj": hasattr(self, "_impl_obj"),
            },
            "H2,H3,H5",
        )
        try:
            result = self.page.goto(f"{self.frontend_server}{path}")
            debug_log(
                "utils.py:goto_page",
                "Navigation succeeded",
                {
                    "url": url,
                    "result_status": result.status if result else None,
                },
                "H2,H4",
            )
            return result
        except Exception as e:
            debug_log(
                "utils.py:goto_page",
                "Navigation FAILED",
                {
                    "url": url,
                    "error_type": type(e).__name__,
                    "error_msg": str(e)[:500],
                },
                "H1,H2,H3,H4,H5",
            )
            raise

    def expect_url(self, url: str):
        self.page.expect_navigation(url=url)
        self.page.wait_for_url(url)

    def expect_page_title(self, search_title: str):
        expect(self.page).to_have_title(re.compile(search_title))


# ── scripted agent turns ─────────────────────────────────────────────────────
#
# An agent turn is downstream of one LLM call. These helpers point the caller's
# own user at the scripted provider and drive its queue over HTTP, so a test can
# run a real turn - tools, ledger, content parser, session persistence - against
# the live backend with no key and no network. Contract:
# ``app/agents/testing_provider.py``.

#: What ``use_scripted_llm`` writes as the user's model name. Never dispatched
#: anywhere; it exists because ``resolve_provider_config`` treats an empty
#: ``llm_model`` as "unconfigured" and falls back to the deployment default.
SCRIPTED_MODEL = "scripted"


def use_scripted_llm(backend_url: str, token: str) -> dict:
    """Point this user's LLM provider at the scripted one.

    Goes through the real settings route (``PATCH /api/auth/me``) rather than a
    test-only shortcut, so the resolution path under test is the production one:
    ``resolve_provider_config`` reads these exact columns.
    """
    return api_json(
        f"{backend_url}/api/auth/me",
        token,
        method="PATCH",
        payload={
            "llm_api_type": "testing",
            "llm_base_url": "",
            "llm_api_key": "",
            "llm_model": SCRIPTED_MODEL,
        },
    )


def script_agent_replies(backend_url: str, *replies: str, reset: bool = True) -> int:
    """Queue *replies* for the next agent turns, one per provider call.

    A multi-round run needs one entry per round: a reply carrying a
    ``toolRequest`` tail is answered by the runtime and the model is prompted
    again, so script the follow-up too. Returns how many are pending.

    Resets by default. A reply left over from a previous test would be consumed
    by this one, and the failure would point anywhere but at the cause.
    """
    body = _post_json(
        f"{backend_url}/api/testing/agent-script",
        {"replies": list(replies), "reset": reset},
    )
    return body["pending"]


def captured_agent_prompts(backend_url: str) -> list:
    """Every message list the scripted provider was handed, oldest first.

    Each entry is the OpenAI-style ``[{"role", "content"}, ...]`` the run
    composed. This is how a per-agent test proves *which* agent ran: the reply
    is scripted and therefore says nothing, but the system turn carries that
    agent's own preamble and instruction bytes.
    """
    return _get_json(f"{backend_url}/api/testing/agent-script")["captured"]


def captured_system_prompt(backend_url: str, *, call: int = 0) -> str:
    """The system content of one captured call (the first, by default)."""
    captured = captured_agent_prompts(backend_url)
    assert captured, "the scripted provider was never called"
    assert call < len(captured), (
        f"asked for call {call} but only {len(captured)} were made"
    )
    return "\n".join(
        m.get("content") or ""
        for m in captured[call]
        if m.get("role") == "system"
    )


def reset_agent_script(backend_url: str) -> None:
    """Drop the scripted queue and the capture log."""
    _request_json(f"{backend_url}/api/testing/agent-script", method="DELETE")
