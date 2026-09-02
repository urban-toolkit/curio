"""
Execution worker for the Curio sandbox.

_worker_init() is called once at sandbox startup to pre-load all heavy imports
into _globals_cache. execute_code() then runs user code in-process using those
cached imports - no subprocess spawning, no IPC overhead.

Thread safety: _exec_lock serializes calls because contextlib.redirect_stdout
mutates the global sys.stdout, and os.chdir is process-wide. Both are restored
after each call via a finally block. For a single-user tool this is acceptable.

execute_js_code() runs JavaScript via a Node.js subprocess. No lock is needed
because each call is fully isolated in a child process.
"""

import collections
import contextlib
import os
import threading

_globals_cache: dict = {}
_exec_lock = threading.Lock()

# Module bindings created by user `import` statements, keyed by session. This is
# what makes an upstream node's `import numpy as np` visible downstream (#158).
#
# Deliberately narrow: only names produced by executing top-level Import /
# ImportFrom statements land here, never ordinary user variables. So a dataflow
# shares its imports but two nodes still cannot leak `df` into each other.
#
# Consequence worth knowing: a node that relies on an upstream import now depends
# on execution order. Run it alone in a fresh session and it fails, exactly as it
# did before. That is inherent to the requested behaviour, not a bug here.
#
# There is no session-close signal in this process (artifacts are session-scoped
# in DuckDB and simply persist), so this is an LRU capped at _MAX_IMPORT_SESSIONS
# rather than something evicted on disconnect. Mutated only under _exec_lock.
_session_imports: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
_MAX_IMPORT_SESSIONS = 32


def _import_bindings_for(session_id):
    """Return the accumulated import bindings for ``session_id`` (never None).

    Marks the session most-recently-used. Call under ``_exec_lock``.
    """
    key = session_id or ''
    bindings = _session_imports.get(key)
    if bindings is None:
        return {}
    _session_imports.move_to_end(key)
    return bindings


def _hoist_user_imports(code, ns, session_id):
    """Execute the user's top-level imports into ``ns`` and remember them.

    ``code`` is the node body as the frontend sends it - every line already
    indented by four spaces, ready to be dropped into ``def userCode(arg):`` -
    so it has to be dedented before it will parse.

    Only ``import`` / ``from ... import`` statements at the *top level* of the
    body are hoisted. Imports nested inside ``try`` / ``if`` / a function are
    left alone: they are conditional by intent, and running them here would turn
    a guarded optional dependency into a hard failure.

    A failing import is swallowed. The statement is still present in the function
    body, so it raises there - at the line the user wrote, with the traceback they
    expect - instead of failing the node from inside this helper.

    Call under ``_exec_lock``.
    """
    import ast
    import textwrap

    try:
        tree = ast.parse(textwrap.dedent(code))
    except SyntaxError:
        # Let the real exec report it, so the user sees one coherent error.
        return

    statements = [
        node for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    if not statements:
        return

    captured: dict = {}
    for statement in statements:
        module = ast.Module(body=[statement], type_ignores=[])
        try:
            exec(compile(module, '<curio-imports>', 'exec'), ns, captured)
        except Exception:
            continue

    if not captured:
        return

    ns.update(captured)

    key = session_id or ''
    bindings = _session_imports.get(key)
    if bindings is None:
        bindings = {}
        _session_imports[key] = bindings
        while len(_session_imports) > _MAX_IMPORT_SESSIONS:
            _session_imports.popitem(last=False)
    bindings.update(captured)
    _session_imports.move_to_end(key)


@contextlib.contextmanager
def chdir_locked(launch_dir):
    """Process-wide ``os.chdir`` guarded by ``_exec_lock``.

    Flask runs with ``threaded=True`` and ``os.chdir`` is process-wide, so
    without serialization the /get handler's save/chdir/restore can
    interleave with /exec's and leave cwd pointing at the wrong directory
    mid-execution. ``execute_code`` already takes ``_exec_lock``; callers
    that need cwd to point at ``launch_dir`` (e.g. /get re-opening a
    raster artifact via a relative path) must take the same lock.

    Falls back to a no-op when ``launch_dir`` is falsy or no longer exists,
    matching the prior /get behaviour.
    """
    if not launch_dir:
        yield
        return
    with _exec_lock:
        original = os.getcwd()
        try:
            os.chdir(launch_dir)
        except OSError:
            yield
            return
        try:
            yield
        finally:
            os.chdir(original)


def _worker_init():
    """Load all heavy imports once. Called at sandbox startup."""
    global _globals_cache

    import warnings
    warnings.filterwarnings('ignore')

    # pyproj bundles a proj.db that can lag behind the system PROJ runtime
    # (e.g. conda proj 9.7+ uses layout 1.6 while pyproj 3.7.2's bundled
    # copy is layout 1.4).  set_data_dir() is pyproj's public API for this;
    # it is priority-1 in get_data_dir() and overrides the stale bundled
    # path.  The guard ensures this only fires when the conda-style directory
    # actually exists, so non-conda installs are unaffected.
    import pathlib as _pathlib
    import sys as _sys
    import pyproj.datadir as _pyproj_datadir
    _system_proj = _pathlib.Path(_sys.prefix) / "Library" / "share" / "proj"
    if (_system_proj / "proj.db").exists():
        _pyproj_datadir.set_data_dir(str(_system_proj))

    import geopandas as gpd
    import pandas as pd
    import json
    import mmap
    import zlib
    import os
    import time
    import hashlib
    import ast
    import io
    # The names below are not used by this module - they exist purely to be
    # pre-seeded into every node's namespace. The legacy subprocess wrapper
    # (utk_curio/sandbox/python_wrapper.txt) did `from ...util.parsers import *`,
    # and parsers.py has no __all__, so it leaked exactly these into user scope.
    # Moving execution in-process replaced that star-import with the explicit
    # 5-name import below and silently dropped them, which is why `np` and
    # shapely stopped working while `pd`/`gpd` kept working (#158). Keep this
    # list explicit rather than restoring `import *` so the contract is greppable.
    import datetime
    import math
    import shapely
    import duckdb
    import numpy as np
    from pathlib import Path
    from shapely import wkt

    from utk_curio.sandbox.util.parsers import (
        load_from_duckdb,
        save_to_duckdb,
        detect_kind,
        checkIOType,
        save_dataset_parquet,
    )

    _globals_cache = {
        '__builtins__': __builtins__,
        'warnings': warnings,
        'gpd': gpd,
        'pd': pd,
        'json': json,
        'mmap': mmap,
        'zlib': zlib,
        'os': os,
        'time': time,
        'hashlib': hashlib,
        'ast': ast,
        'io': io,
        # Restored star-import leakage - see the import block above (#158).
        'np': np,
        'numpy': np,
        'shapely': shapely,
        'wkt': wkt,
        'math': math,
        'datetime': datetime,
        'Path': Path,
        'duckdb': duckdb,
        'load_from_duckdb': load_from_duckdb,
        'save_to_duckdb': save_to_duckdb,
        'detect_kind': detect_kind,
        'checkIOType': checkIOType,
        'save_dataset_parquet': save_dataset_parquet,
    }


def _resolve_outputs_elem(elem, session_id=None):
    """Resolve one element of an 'outputs' bundle to its concrete Python value.

    An 'outputs' input - from a Merge Flow, or a Data Pool's multi-layer wrapper -
    bundles one entry per connected slot / layer. An entry is one of:
      * a DuckDB reference: a `{'path', ...}` dict, or a bare artifact-id/filename
        string (a project restored from persisted outputs seeds the latter) -
        loaded from DuckDB;
      * an inline `{'dataType', 'data'}` envelope - e.g. a Data Pool layer
        `{'dataType':'geodataframe','data':<FeatureCollection>,'layerName':...}`
        wired straight into a code node - reconstructed with `parseInput`;
      * any other already-concrete value, used as-is.
    Distinguishing on the keys keeps refs loading while letting inline values flow
    through instead of raising KeyError('path').
    """
    from utk_curio.sandbox.util.parsers import load_from_duckdb, parseInput
    if isinstance(elem, str):
        return load_from_duckdb(elem, session_id=session_id)
    if isinstance(elem, dict):
        if 'path' in elem:
            return load_from_duckdb(elem['path'], session_id=session_id)
        if 'dataType' in elem and 'data' in elem:
            return parseInput(elem)
    return elem


def _expand_outputs_wrapper(input_data, session_id=None):
    """Resolve a merge ('outputs') input to the per-slot list user code expects.

    A merge output reaches a code node in one of two shapes:
      * live  - an inline list of refs, already expanded by the caller's
        `data_type == 'outputs'` branch; passed through here untouched.
      * reloaded - when the upstream merge output was persisted (project save, or
        the JS-node I/O round-trip through DuckDB), the node receives a single ref
        to it. `_parse_input_ref` remaps that ref's 'outputs' dataType to a plain
        load, so `load_from_duckdb` hands back the whole
        `{dataType:'outputs', data:[refs]}` wrapper dict. Without this, user code
        gets the wrapper object (e.g. `const [a,b] = arg` → "arg is not iterable").
    In the reloaded case, resolve each inner element so `arg` matches the live list.
    """
    if (isinstance(input_data, dict)
            and input_data.get('dataType') == 'outputs'
            and isinstance(input_data.get('data'), list)):
        return [_resolve_outputs_elem(elem, session_id=session_id) for elem in input_data['data']]
    return input_data


def _make_curio_dataset_path(dataset_paths):
    """Resolver injected into user code as ``curio_dataset_path(dataset_id)``.

    Generated Data Loading nodes reference datasets by id instead of a baked-in
    absolute path; the backend resolves the ids it finds in the code and passes
    the mapping here. Missing ids raise with an actionable message rather than
    surfacing a broken foreign path from another machine or user.
    """
    mapping = dict(dataset_paths or {})

    def curio_dataset_path(dataset_id):
        path = mapping.get(str(dataset_id))
        if not path:
            raise RuntimeError(
                f"Dataset '{dataset_id}' is not available in this environment - "
                "install it from the Data Catalog drawer (or re-import the "
                "source file), then run this node again."
            )
        return path

    return curio_dataset_path


def execute_code(code, file_path, node_type, data_type, launch_dir=None, session_id=None, save_dataset=True,
                 dataset_paths=None):
    """
    Execute user code in-process using pre-loaded library globals.

    session_id: Bearer token of the requesting session. Artifacts are stored and
                loaded scoped to this session so concurrent sessions never share
                execution state - even if they share the same user account.

    dataset_paths: {datasetId: absolutePath} for the code's
                curio_dataset_path("<id>") calls, resolved (auth-scoped and
                containment-checked) by the backend.

    Returns {'stdout': [str, ...], 'stderr': str, 'output': {'path': str, 'dataType': str}}
    """
    import io as _io
    import os
    import sys
    import time
    import contextlib
    import traceback

    load_from_duckdb = _globals_cache['load_from_duckdb']
    save_to_duckdb   = _globals_cache['save_to_duckdb']
    detect_kind      = _globals_cache['detect_kind']
    checkIOType      = _globals_cache['checkIOType']
    save_dataset_parquet = _globals_cache['save_dataset_parquet']

    # _exec_lock serializes sys.stdout mutation and os.chdir.
    with _exec_lock:
        t0 = time.perf_counter()
        original_dir = os.getcwd()
        if launch_dir:
            os.chdir(launch_dir)

        captured_stdout = _io.StringIO()
        captured_stderr = _io.StringIO()
        result = {'path': '', 'dataType': 'str'}
        t_load = t_code = t_save = t0

        try:
            with contextlib.redirect_stdout(captured_stdout), \
                 contextlib.redirect_stderr(captured_stderr):

                # Fresh namespace per call, so user *variables* never leak between
                # executions. Imports are the deliberate exception: this session's
                # accumulated import bindings are layered in so an upstream node's
                # `import numpy as np` reaches downstream nodes (#158).
                ns = dict(_globals_cache)
                ns.update(_import_bindings_for(session_id))
                ns['curio_dataset_path'] = _make_curio_dataset_path(dataset_paths)
                # Hoist this node's own top-level imports before defining userCode,
                # so they are recorded for later nodes in the same session. The
                # statements stay in the function body too - re-importing is a
                # sys.modules hit, and it keeps a standalone run of this node working.
                _hoist_user_imports(code, ns, session_id)
                exec(f"def userCode(arg):\n{code}", ns)

                # Load input from DuckDB.
                input_data = ''
                if data_type == 'outputs':
                    file_path_list = eval(file_path, {'__builtins__': {}})
                    input_data = [_resolve_outputs_elem(elem, session_id=session_id) for elem in file_path_list]
                elif file_path:
                    input_data = load_from_duckdb(file_path, session_id=session_id)
                input_data = _expand_outputs_wrapper(input_data, session_id=session_id)
                t_load = time.perf_counter()

                # Validate and prepare input.
                incomingInput = None
                if input_data is not None and not (isinstance(input_data, str) and input_data == ''):
                    if data_type == 'outputs':
                        synthetic = {
                            'dataType': 'outputs',
                            'data': [{'dataType': detect_kind(v), 'data': None} for v in input_data],
                        }
                        checkIOType(synthetic, node_type)
                        incomingInput = input_data
                    else:
                        synthetic = {'dataType': detect_kind(input_data), 'data': None}
                        checkIOType(synthetic, node_type)
                        incomingInput = input_data

                # Tripwire: if the user code references `arg` but no input was
                # delivered, the historical behaviour was to bubble up a
                # confusing `'NoneType' object is not subscriptable` from the
                # first `arg[…]`. Fail fast here with a message that points the
                # user at the actual cause (unwired/unrun upstream, or a stale
                # `data.input` because the merge-flow output effect hadn't
                # propagated yet). Cheap substring check - false positives
                # are harmless because we only act when arg is truly None.
                if incomingInput is None and 'arg' in code:
                    raise RuntimeError(
                        "This node received no input but its code references `arg`. "
                        "Make sure every upstream node has produced output (state "
                        "'Done') and is wired to this node's input handle before "
                        "running. If the inputs come through a Merge Flow node, "
                        "give it a moment after the last upstream finishes so the "
                        "merged tuple can propagate, then click Run again."
                    )

                # Run user code.
                output = ns['userCode'](incomingInput)
                t_code = time.perf_counter()

                # Validate output.
                out_kind = detect_kind(output)
                if out_kind == 'outputs':
                    synthetic_out = {
                        'dataType': 'outputs',
                        'data': [{'dataType': detect_kind(v), 'data': None} for v in output],
                    }
                else:
                    synthetic_out = {'dataType': out_kind, 'data': None}
                checkIOType(synthetic_out, node_type, False)

                # Save output to DuckDB, tagged with the session that produced it.
                result_path = save_to_duckdb(output, node_id=node_type, session_id=session_id)

                dataset_file = None
                if save_dataset:
                    dataset_file = save_dataset_parquet(output, out_kind)

                result = {'path': result_path, 'dataType': out_kind}
                if dataset_file:
                    result['dataset'] = dataset_file
                t_save = time.perf_counter()

        except BaseException:
            captured_stderr.write(traceback.format_exc())

        finally:
            os.chdir(original_dir)
            # Drop the sandbox write lock so the backend can open read-only
            # DuckDB (catalog, auto-install) as soon as this request returns.
            #
            # NOTE: this teardown-per-exec is REQUIRED, not wasteful - DuckDB
            # allows only a single cross-process writer, so the sandbox cannot
            # hold the R/W handle open between requests or the backend's
            # read-only opens would fail. The reopen is lazy (``get_connection``
            # only runs when the next exec actually touches DuckDB), so an exec
            # that never loads/saves pays nothing. Do not "optimize" by keeping
            # the connection alive across execs.
            from utk_curio.sandbox.util.db import release_connection
            release_connection()
            t1 = time.perf_counter()
            print(
                f"[exec] load={t_load-t0:.3f}s  code={t_code-t_load:.3f}s"
                f"  save={t_save-t_code:.3f}s  total={t1-t0:.3f}s",
                file=sys.__stderr__,
                flush=True,
            )

        stdout_lines = [line for line in captured_stdout.getvalue().split('\n') if line]
        return {
            'stdout': stdout_lines,
            'stderr': captured_stderr.getvalue(),
            'output': result,
        }


def _to_js_value(obj):
    """Convert a Python value to a JSON-serializable form for JS consumption.

    DataFrames → list of row dicts, GeoDataFrames → GeoJSON FeatureCollection -
    matching what the old JS loadFromDuckdb returned to user code.
    """
    import json
    import pandas as pd
    import geopandas as gpd

    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float, str)):
        return obj
    if isinstance(obj, gpd.GeoDataFrame):
        return json.loads(obj.to_json())
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient='records')
    if isinstance(obj, (list, tuple)):
        return [_to_js_value(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_js_value(v) for k, v in obj.items()}
    return str(obj)


def _js_value_to_saveable_frame(value):
    """Best-effort convert a JS node's JSON result into a ``(kind, frame)`` pair
    for :func:`save_dataset_parquet`, or ``(None, None)`` when it isn't tabular.

    JS nodes return plain JSON, so - mirroring how ``parseInput`` reconstructs
    tabular inputs - a GeoJSON ``FeatureCollection`` becomes a GeoDataFrame and a
    non-empty list of record objects becomes a DataFrame. Anything else (scalars,
    plain dicts, lists of scalars) is not a dataset and yields ``(None, None)``.
    """
    from utk_curio.sandbox.util.parsers import parse_dataframe, parse_geodataframe

    if (
        isinstance(value, dict)
        and value.get('type') == 'FeatureCollection'
        and isinstance(value.get('features'), list)
    ):
        return 'geodataframe', parse_geodataframe(value)
    if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
        return 'dataframe', parse_dataframe(value)
    return None, None


def _pick_export_entry(node):
    """Resolve a package.json ``exports`` subtree down to a relative path string.

    Node's export conditions NEST: ``exports["."]["import"]`` is frequently
    another condition object (``{"types": ..., "default": "./x.mjs"}``) rather
    than a path. Walking only one level and handing the resulting dict to
    ``pathlib`` raises TypeError, which the caller used to swallow - silently
    degrading to the bare specifier, which then resolves only when the Node
    subprocess cwd happens to sit inside the repo.

    Condition order matches what the js_wrapper needs: it runs under
    ``--input-type=commonjs`` but reaches packages through dynamic ``import()``,
    so the ESM conditions win over ``require``.
    """
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return None
    for key in ('import', 'module', 'node', 'default', 'require'):
        if key in node:
            entry = _pick_export_entry(node[key])
            if entry:
                return entry
    return None


def resolve_pkg_entry_url(specifier, root_node_modules):
    """Map a bare package specifier to an absolute ``file://`` URL, or None.

    Returns None for anything that is not a bare specifier (relative, absolute,
    URL, ``node:`` builtin), for a package that isn't installed under
    ``root_node_modules``, or for an entry that escapes it.
    """
    import json
    import pathlib

    # Only bare specifiers (not relative / absolute / URL / node: builtin).
    if not specifier or specifier[0] in './' or ':' in specifier:
        return None
    root_node_modules = pathlib.Path(root_node_modules)
    seg = specifier.split('/')
    pkg = '/'.join(seg[:2]) if specifier.startswith('@') else seg[0]
    pkg_dir = root_node_modules / pkg
    pj = pkg_dir / 'package.json'
    if not pj.is_file():
        return None
    try:
        meta = json.loads(pj.read_text(encoding='utf-8'))
    except Exception:
        return None
    exp = meta.get('exports')
    entry = None
    if isinstance(exp, str):
        entry = exp
    elif isinstance(exp, dict):
        # A subpath map keys on "."; a bare condition map has no "." and applies
        # to the root itself.
        entry = _pick_export_entry(exp.get('.', exp))
    entry = entry or meta.get('module') or meta.get('main') or 'index.js'
    if not isinstance(entry, str):
        return None
    try:
        entry_path = (pkg_dir / entry).resolve()
    except Exception:
        return None
    if not entry_path.is_file() or root_node_modules.resolve() not in entry_path.parents:
        return None
    return entry_path.as_uri()


# ── Node-internal stream crash ───────────────────────────────────────────────

# Node's bundled HTTP client asserts on its own state rather than raising:
#
#   AssertionError [ERR_ASSERTION]: assert(!this.paused)
#       at Parser.finish (node:internal/deps/undici/undici:7388:9)
#       at Socket.onHttpSocketEnd (node:internal/deps/undici/undici:7827:34)
#
# undici pauses its parser to apply backpressure while the consumer works on a
# chunk, and asserts if the socket ends in that window. Any JS node that streams
# a file and does per-chunk work is exposed: @urban-toolkit/autk-db's
# `streamPbfBlocks` awaits a callback for every block of the PBF it is reading
# over HTTP from the backend's /file route, so the OSM examples sit in that
# window for most of their runtime.
#
# It aborts the process from inside an internal event handler. There is no
# exception to catch (the JS wrapper's try//catch never sees it), no partial
# result, and no user-code defect to report - the same node succeeds on the next
# run. It is intermittent: in one CI run 10 of 12 autk-grammar executions
# finished normally and 2 died here, and it has been observed on main as well as
# on this branch.
_NODE_INTERNAL_STREAM_CRASH_MARKERS = ('assert(!this.paused)', 'undici')


def is_node_internal_stream_crash(exit_code, stdout_lines, stderr_lines) -> bool:
    """Whether Node aborted inside its own HTTP parser, losing the execution.

    Narrow on purpose - all three must hold:

    - the process failed (``exit_code`` non-zero),
    - it produced no result line, so nothing of the run survived and re-running
      cannot discard a result the user would otherwise have seen,
    - stderr carries the assertion *and* names undici, so a user's own
      ``assert`` cannot be mistaken for it.

    A user-code error does not match: the wrapper catches it and still prints a
    ``__CURIO_JSON_RESULT__`` line with ``success: false``. Nor does a killed or
    OOM process, which leaves no such stderr. Callers may therefore treat a true
    return as "this run told us nothing" and retry it.
    """
    if exit_code == 0:
        return False
    if any(line.startswith('__CURIO_JSON_RESULT__') for line in stdout_lines):
        return False
    stderr_text = '\n'.join(stderr_lines)
    return all(marker in stderr_text for marker in _NODE_INTERNAL_STREAM_CRASH_MARKERS)


# Placeholder the frontend puts where a backend URL belongs in code destined for
# this sandbox (autkGrammarBehavior.SANDBOX_BACKEND_URL_TOKEN). It is resolved
# here, in the process that actually performs the fetch, rather than guessed in
# the browser bundle.
_SANDBOX_BACKEND_URL_TOKEN = '__CURIO_BACKEND_URL__'


def backend_base_url():
    """``http://host:port`` for the backend, as reachable from this process.

    ``main.py::set_environment_variables`` exports FLASK_BACKEND_HOST/PORT and
    start_sandbox passes the environment through, so a sandbox launched with the
    stack always has the true values - including on a custom-port stack, where
    the browser's own port would be wrong, and inside a container, where a
    host-published port is not the one to dial.

    The loopback host is normalised to 127.0.0.1: Node's fetch can stall when
    ``localhost`` resolves to IPv6 ::1 while Flask listens on IPv4 only.
    """
    import os

    host = os.environ.get('FLASK_BACKEND_HOST') or '127.0.0.1'
    port = os.environ.get('FLASK_BACKEND_PORT') or '5002'
    if host in ('localhost', '0.0.0.0', '::', '[::]'):
        host = '127.0.0.1'
    return f'http://{host}:{port}'


def execute_js_code(code, file_path, node_type, data_type, launch_dir=None, session_id=None, save_dataset=True):
    """
    Execute user JavaScript code in an isolated Node.js subprocess.

    Input is loaded from Python DuckDB, serialized to JSON, and embedded directly
    in the script piped to `node --input-type=module` via stdin - no temp files.
    The result arrives as a specially-prefixed stdout line and is stored in Python
    DuckDB, mirroring execute_code()'s behaviour exactly.

    Returns {'stdout': [str, ...], 'stderr': str, 'output': {'path': str, 'dataType': str}}
    """
    import json
    import os
    import pathlib
    import re
    import subprocess
    import sys as _sys
    import threading
    import time
    import traceback

    from utk_curio.sandbox.util.parsers import (
        load_from_duckdb, save_to_duckdb, detect_kind, save_dataset_parquet,
    )

    t0 = time.perf_counter()
    cwd = launch_dir or os.getcwd()

    # Resolve the frontend's backend-URL placeholder now, while the real host and
    # port are in this process's environment. Done before the import rewriting
    # below so the substituted code is what gets parsed and run.
    code = code.replace(_SANDBOX_BACKEND_URL_TOKEN, backend_base_url())

    try:
        # Load input from Python DuckDB (same pattern as execute_code).
        input_data = None
        if data_type == 'outputs' and file_path:
            file_path_list = eval(file_path, {'__builtins__': {}})
            input_data = [_resolve_outputs_elem(elem, session_id=session_id)
                          for elem in file_path_list]
        elif file_path:
            input_data = load_from_duckdb(file_path, session_id=session_id)
        input_data = _expand_outputs_wrapper(input_data, session_id=session_id)

        # Resolve bare package specifiers (e.g. '@urban-toolkit/autk-db') to an
        # ABSOLUTE file URL under the repo-root node_modules so the dynamic ESM
        # import() below resolves regardless of the Node subprocess cwd. Node's ESM
        # resolver does NOT consult NODE_PATH and resolves a bare specifier only by
        # walking node_modules up from the importing module - which fails when
        # CURIO_LAUNCH_CWD is outside the repo. Rewriting only the top-level
        # specifier is enough: the package's own internal imports still resolve
        # relative to its installed location.
        repo_root = pathlib.Path(__file__).resolve().parents[3]
        root_node_modules = repo_root / 'node_modules'

        def _resolved_source(quoted_source):
            # quoted_source keeps its surrounding quotes, e.g. "'@urban-toolkit/autk-db'".
            spec = quoted_source[1:-1]
            url = resolve_pkg_entry_url(spec, root_node_modules)
            return f"'{url}'" if url else quoted_source

        # Rewrite static `import` statements to dynamic `await import()` calls
        # so user code runs inside a CJS IIFE (--input-type=commonjs), which
        # lets autk-db's eval'd Worker threads use require() without errors.
        named_re = re.compile(
            r'^import\s+(.*?)\s+from\s+([\'"][^\'"]+[\'"])\s*;?\s*$', re.MULTILINE)
        bare_re  = re.compile(
            r'^import\s+([\'"][^\'"]+[\'"])\s*;?\s*$', re.MULTILINE)

        dynamic_import_lines: list[str] = []

        def _rewrite_named(m):
            specs, source = m.group(1).strip(), _resolved_source(m.group(2))
            if specs.startswith('* as '):
                return f'  const {specs[5:].strip()} = await import({source});'
            if specs.startswith('{'):
                return f'  const {specs} = await import({source});'
            parts = specs.split(',', 1)
            default_name = parts[0].strip()
            if len(parts) == 2:
                named = parts[1].strip()
                inner = named[1:-1] if named.startswith('{') and named.endswith('}') else named
                return f'  const {{ default: {default_name}, {inner} }} = await import({source});'
            return f'  const {{ default: {default_name} }} = await import({source});'

        def _collect_named(m):
            dynamic_import_lines.append(_rewrite_named(m))
            return ''

        def _collect_bare(m):
            dynamic_import_lines.append(f'  await import({_resolved_source(m.group(1))});')
            return ''

        clean_code = bare_re.sub(_collect_bare, code)
        clean_code = named_re.sub(_collect_named, clean_code).strip()
        dynamic_imports_block = '\n'.join(dynamic_import_lines)
        indented = '\n'.join('    ' + line for line in clean_code.splitlines())

        # Serialize input as an inline JS literal.
        arg_json = json.dumps(_to_js_value(input_data))

        # Build script from static template - no temp file written to disk.
        template_path = pathlib.Path(__file__).parent.parent / 'util' / 'js_wrapper.mjs'
        template = template_path.read_text(encoding='utf-8')
        script = (template
                  .replace('__DYNAMIC_IMPORTS__', dynamic_imports_block)
                  .replace('__ARG_JSON__', arg_json)
                  .replace('__USER_CODE__', indented))

        # NODE_PATH is consulted only by the CommonJS require() resolver (not ESM),
        # so it does NOT resolve the top-level autk-db ESM import - that is handled
        # by rewriting it to an absolute file URL above. We still point NODE_PATH at
        # the repo-root node_modules as a belt-and-braces aid for any CJS require()
        # autk-db's worker threads perform. cwd stays launch_dir so other JS nodes'
        # relative file reads keep working.
        node_env = {**os.environ}
        if root_node_modules.is_dir():
            existing = node_env.get('NODE_PATH', '')
            node_env['NODE_PATH'] = (
                str(root_node_modules) + (os.pathsep + existing if existing else '')
            )

        def _run_node():
            """Run the script in one Node subprocess.

            Returns ``(exit_code, stdout_lines, stderr_lines)``. Factored out of
            the body only so a crash inside Node itself can be retried: every
            input it reads (``script``, ``cwd``, ``node_env``) is fully built by
            this point, so a second call re-runs the same execution rather than a
            different one.
            """
            print(f"[execJs] starting Node.js  node={node_type}", file=_sys.stderr, flush=True)
            t_start = time.perf_counter()

            proc = subprocess.Popen(
                ['node', '--input-type=commonjs'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', cwd=cwd,
                env=node_env,
            )

            stdout_lines: list[str] = []
            stderr_lines: list[str] = []

            def _stream(pipe, lines, label):
                for line in pipe:
                    line = line.rstrip('\n')
                    lines.append(line)
                    if not line.startswith('__CURIO_JSON_RESULT__'):
                        print(f"[execJs] {label}: {line}", file=_sys.stderr, flush=True)

            def _write_stdin(proc, data):
                try:
                    proc.stdin.write(data)
                    proc.stdin.close()
                except BrokenPipeError:
                    pass

            t_in  = threading.Thread(target=_write_stdin, args=(proc, script), daemon=True)
            t_out = threading.Thread(target=_stream, args=(proc.stdout, stdout_lines, 'stdout'), daemon=True)
            t_err = threading.Thread(target=_stream, args=(proc.stderr, stderr_lines, 'stderr'), daemon=True)
            t_in.start()
            t_out.start()
            t_err.start()

            try:
                proc.wait(timeout=3000)
            except subprocess.TimeoutExpired:
                proc.kill()
                t_in.join()
                t_out.join()
                t_err.join()
                raise

            t_in.join()
            t_out.join()
            t_err.join()

            print(f"[execJs] Node.js finished  total={time.perf_counter()-t_start:.3f}s  "
                  f"exit={proc.returncode}  node={node_type}",
                  file=_sys.stderr, flush=True)
            return proc.returncode, stdout_lines, stderr_lines

        exit_code, stdout_lines, stderr_lines = _run_node()

        # One retry, and only for a crash inside Node's own HTTP parser. See
        # is_node_internal_stream_crash for why re-running is the only response
        # available to us. The cost is bounded: a run that does not hit it pays
        # one substring scan of stderr.
        if is_node_internal_stream_crash(exit_code, stdout_lines, stderr_lines):
            print(f"[execJs] Node died inside its own HTTP parser before user code "
                  f"could either fail or produce a result; retrying once  "
                  f"node={node_type}", file=_sys.stderr, flush=True)
            exit_code, stdout_lines, stderr_lines = _run_node()
            print(f"[execJs] retry {'hit it too' if is_node_internal_stream_crash(exit_code, stdout_lines, stderr_lines) else 'cleared it'}"
                  f"  total_with_retry={time.perf_counter()-t0:.3f}s  node={node_type}",
                  file=_sys.stderr, flush=True)

        # Extract result from stdout - a single line prefixed with __CURIO_JSON_RESULT__.
        RESULT_PREFIX = '__CURIO_JSON_RESULT__'
        result_json = None
        user_log_lines = []
        for line in stdout_lines:
            if line.startswith(RESULT_PREFIX):
                result_json = line[len(RESULT_PREFIX):]
            else:
                user_log_lines.append(line)

        stderr_text = '\n'.join(stderr_lines)

        if result_json is None:
            err = stderr_text.strip() or '\n'.join(user_log_lines).strip() or 'Node.js exited without a result.'
            return {'stdout': [], 'stderr': err, 'output': {'path': '', 'dataType': 'str'}}

        try:
            run_result = json.loads(result_json)
        except (json.JSONDecodeError, ValueError):
            return {'stdout': [], 'stderr': 'Node.js returned malformed result JSON.',
                    'output': {'path': '', 'dataType': 'str'}}

        if not run_result.get('success'):
            return {
                'stdout': run_result.get('logs', []),
                'stderr': run_result.get('error', 'Unknown JavaScript error'),
                'output': {'path': '', 'dataType': 'str'},
            }

        raw_value = run_result.get('value')
        result_artifact = save_to_duckdb(raw_value, node_id=node_type, session_id=session_id)
        out_kind = detect_kind(raw_value)

        output = {'path': result_artifact, 'dataType': out_kind}

        # Persist a named dataset (catalog parquet + auto-install) when the JS
        # node opted in and produced tabular/geo data - parity with the Python
        # path, which emits output['dataset'] for the backend to auto-install.
        if save_dataset:
            try:
                ds_kind, frame = _js_value_to_saveable_frame(raw_value)
                if frame is not None:
                    dataset_file = save_dataset_parquet(frame, ds_kind)
                    if dataset_file:
                        output['dataset'] = dataset_file
            except Exception:  # noqa: BLE001 - dataset save is best-effort
                print(f"[execJs] save_dataset failed for node={node_type}",
                      file=_sys.stderr, flush=True)

        return {
            'stdout': run_result.get('logs', []),
            'stderr': stderr_text,
            'output': output,
        }

    except subprocess.TimeoutExpired:
        return {'stdout': [], 'stderr': 'JavaScript execution timed out (3000 s)',
                'output': {'path': '', 'dataType': 'str'}}
    except FileNotFoundError:
        return {'stdout': [], 'stderr': 'Node.js not found. Please install Node.js to use JS Computation nodes.',
                'output': {'path': '', 'dataType': 'str'}}
    except Exception:
        return {'stdout': [], 'stderr': traceback.format_exc(), 'output': {'path': '', 'dataType': 'str'}}
    finally:
        from utk_curio.sandbox.util.db import release_connection
        release_connection()
