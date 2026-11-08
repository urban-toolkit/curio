"""
Execution worker for the Curio sandbox.

_worker_init() is called once at sandbox startup to pre-load all heavy imports
into _globals_cache. execute_code() then runs user code in-process using those
cached imports - no subprocess spawning, no IPC overhead.

Thread safety: _exec_lock serializes calls because contextlib.redirect_stdout
mutates the global sys.stdout, and os.chdir is process-wide. Both are restored
after each call via a finally block. For a single-user tool this is acceptable.
The swap also catches what other threads print meanwhile, so the sandbox's own
log lines go to sys.__stderr__, never to sys.stderr (#770).

execute_js_code() runs JavaScript via a Node.js subprocess, and those run in
parallel: the child isolates the user code, so no lock is needed for
correctness. What it does have is a ceiling (_js_slot) on how many children
exist at once, because a hundred simultaneous Autark loads is a memory
problem, not a correctness one. Its DuckDB access is protected by the
connection guard in util/db.py, not by a lock of its own.
"""

import collections
import contextlib
import os
import sys
import threading
import time

from utk_curio.common.backend_address import backend_base_url
from utk_curio.common.redaction import redact
from utk_curio.sandbox import run_place
from utk_curio.sandbox.util.node_runtime import (
    OVERPASS_USER_AGENT,
    node_env,
    node_modules_dir,
    resolve_pkg_entry_url,
)
from utk_curio.sandbox.util.secrets import make_curio_secret

_globals_cache: dict = {}


class _ExecLock:
    """``_exec_lock``, plus the numbers that say whether it is the bottleneck.

    The lock itself is unchanged: one process-wide mutex, ``with _exec_lock:``
    still works, and nothing about who waits for whom is different. What is new
    is that each acquisition records how long it waited and how long it held,
    under a label naming the call site.

    This exists because a stress run cannot otherwise tell a slot queue from a
    lock queue. Raising ``CURIO_EXEC_PARALLELISM`` from 8 to 32 left the
    100-user tier's throughput unchanged while /get's median got 7.5x worse,
    which says the waiting moved from the execution semaphore to this lock --
    but says it by inference. These counters say it directly.

    Accounting costs two ``perf_counter`` calls and a dict update per
    acquisition, against critical sections that run for seconds. The stats
    mutex is separate from the real one and is never held across user work, so
    it cannot become a second queue.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stats = {}
        self._waiting = 0
        self._holder = None

    @contextlib.contextmanager
    def hold(self, label="other"):
        """Take the lock, recording the wait and the hold under ``label``."""
        requested = time.perf_counter()
        with self._stats_lock:
            self._waiting += 1
        try:
            self._lock.acquire()
        finally:
            with self._stats_lock:
                self._waiting -= 1
        waited = time.perf_counter() - requested
        acquired = time.perf_counter()
        self._holder = label
        try:
            yield
        finally:
            held = time.perf_counter() - acquired
            self._holder = None
            self._lock.release()
            self._record(label, waited, held)

    def __enter__(self):
        """``with _exec_lock:`` still works, and lands under "other"."""
        self._ctx = self.hold()
        return self._ctx.__enter__()

    def __exit__(self, *exc):
        ctx, self._ctx = self._ctx, None
        return ctx.__exit__(*exc)

    def _record(self, label, waited, held):
        with self._stats_lock:
            entry = self._stats.get(label)
            if entry is None:
                entry = {"acquisitions": 0, "wait_seconds": 0.0,
                         "held_seconds": 0.0, "max_wait_seconds": 0.0}
                self._stats[label] = entry
            entry["acquisitions"] += 1
            entry["wait_seconds"] += waited
            entry["held_seconds"] += held
            if waited > entry["max_wait_seconds"]:
                entry["max_wait_seconds"] = waited

    def snapshot(self):
        """Counters so far, as plain data. Cumulative, never reset.

        A stress tier takes the difference between two of these, the same way
        the container stats sampler is read: an absolute total across a run
        that includes the baseline would not describe any one tier.
        """
        with self._stats_lock:
            labels = {
                label: dict(entry) for label, entry in self._stats.items()
            }
            waiting = self._waiting
        return {
            "waiting": waiting,
            "holder": self._holder,
            "labels": labels,
            "total_wait_seconds": round(
                sum(e["wait_seconds"] for e in labels.values()), 3
            ),
            "total_held_seconds": round(
                sum(e["held_seconds"] for e in labels.values()), 3
            ),
        }


_exec_lock = _ExecLock()


def _default_js_parallelism() -> int:
    """How many Node subprocesses may run at once.

    Not a lock: JS nodes are meant to run in parallel, and this leaves them
    doing so. It is a ceiling on how many at once, which the route had none of
    -- one Node process per request, each loading autk-db and its own DuckDB.
    A hundred simultaneous Autark loads peaked the CI container at 51 GB and
    1313 processes, which is how a machine dies rather than queues.

    Half the cores, floor 2, cap 16: an Autark PBF load is CPU- and
    memory-heavy, and the work the child does is what costs, not the pipe.
    ``CURIO_JS_PARALLELISM`` overrides it.
    """
    try:
        configured = int(os.environ.get("CURIO_JS_PARALLELISM", ""))
    except (TypeError, ValueError):
        configured = 0
    if configured > 0:
        return configured
    cores = os.cpu_count() or 2
    return max(2, min(cores // 2, 16))


# Bounded, not serialized. Sized on first use so the env is fully populated.
_js_slots: "threading.BoundedSemaphore | None" = None
_js_slots_lock = threading.Lock()


def _js_slot() -> "threading.BoundedSemaphore":
    global _js_slots
    with _js_slots_lock:
        if _js_slots is None:
            _js_slots = threading.BoundedSemaphore(_default_js_parallelism())
        return _js_slots

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


# A node's code is the body of a function whose parameters are the inputs it
# reads, input_0, input_1, ... (util/input_names.py, shared with the isolated
# child and the JavaScript wrapper, so the three agree on every name).


def _hoist_user_imports(code, ns, session_id, skip=()):
    """Execute the user's top-level imports into ``ns`` and remember them.

    ``code`` is the node body as the frontend sends it - every line already
    indented by four spaces, ready to be dropped under
    ``input_names.user_code_header`` - so it has to be dedented before it will
    parse.

    Only ``import`` / ``from ... import`` statements at the *top level* of the
    body are hoisted. Imports nested inside ``try`` / ``if`` / a function are
    left alone: they are conditional by intent, and running them here would turn
    a guarded optional dependency into a hard failure.

    A failing import is swallowed. The statement is still present in the function
    body, so it raises there - at the line the user wrote, with the traceback they
    expect - instead of failing the node from inside this helper.

    *skip* names the modules the node's package ships (#468). Importing one of
    those is left to the function body and never remembered: they are this
    package's nodes' alone, and the isolated path does the same.

    Call under ``_exec_lock``.
    """
    import ast
    import textwrap

    from utk_curio.sandbox.util.package_modules import without_package_imports

    try:
        tree = ast.parse(textwrap.dedent(code))
    except SyntaxError:
        # Let the real exec report it, so the user sees one coherent error.
        return

    statements = [
        kept for kept in (
            without_package_imports(node, skip) for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        if kept is not None
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
    # Labelled: this is the artifact-serving side of the lock, and telling it
    # apart from execution is the whole point of the counters.
    with _exec_lock.hold("chdir"):
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
    # The libraries below are not used by this module - they exist purely to be
    # pre-seeded into every node's namespace. The legacy subprocess wrapper
    # (utk_curio/sandbox/python_wrapper.txt) did `from ...util.parsers import *`,
    # and parsers.py has no __all__, so it leaked exactly these into user scope.
    # Moving execution in-process dropped them, which is why `np` and shapely
    # stopped working while `pd`/`gpd` kept working (#158). Keep this list
    # explicit rather than restoring `import *` so the contract is greppable.
    # Curio's own functions for node code are the curio_ ones
    # skills/node-functions/SKILL.md lists, and no other.
    import datetime
    import math
    import shapely
    import duckdb
    import numpy as np
    from shapely import wkt

    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.input_layers import curio_layer

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
        'Path': _pathlib.Path,
        'duckdb': duckdb,
        # The Edit Features node's code applies its edit list with it (#662).
        'curio_edit_features': edit_features,
        # A layer chip, [!! input_0:roads !!], reads one layer of an input with it.
        'curio_layer': curio_layer,
    }


def _resolve_outputs_elem(elem, session_id=None, saved_paths=None):
    """Resolve one element of an 'outputs' bundle to its concrete Python value.

    An 'outputs' input - from a node's several input circles, or a Data Pool's
    multi-layer wrapper - bundles one entry per connected circle / layer. An entry is one of:
      * a DuckDB reference: a `{'path', ...}` dict, or a bare artifact-id/filename
        string (a project restored from persisted outputs seeds the latter):
        loaded from DuckDB, and read as an input reads a stored value
        (``stored_inputs.read_stored``), one Autark layer as its frame and
        several as the list of them;
      * an inline `{'dataType', 'data'}` envelope (e.g. a Data Pool layer
        `{'dataType':'geodataframe','data':<FeatureCollection>,'layerName':...}`
        wired straight into a code node): reconstructed with `parseInput`
        (``stored_inputs.read_element``);
      * any other already-concrete value, used as-is.
    Distinguishing on the keys keeps refs loading while letting inline values flow
    through instead of raising KeyError('path'). A ref that is a saved output
    of the run's dataflow is read in place from *saved_paths* when the store
    has no row for it (``parsers.load_artifact``). A wrapper a loaded output
    holds that names other outputs is read as it is stored: only a node's one
    input reads the outputs its wrapper names (:func:`_expand_outputs_wrapper`).
    """
    from utk_curio.sandbox.util.parsers import load_artifact
    from utk_curio.sandbox.util.stored_inputs import is_ref, read_element, read_stored, ref_name

    if is_ref(elem):
        return read_stored(load_artifact(ref_name(elem), session_id=session_id, saved_paths=saved_paths))
    return read_element(elem)


def _expand_outputs_wrapper(input_data, session_id=None, saved_paths=None):
    """A node's one input as user code reads it (``stored_inputs.read_stored``).

    One envelope of a frame, as an Autark node hands on one layer, is that
    frame. A bundle (an ``outputs`` wrapper) reaches a code node in one of two
    shapes:
      * live  - an inline list of refs, already expanded by the caller's
        `data_type == 'outputs'` branch; passed through here untouched.
      * reloaded - when the upstream bundle was persisted (project save, an
        Autark node's layers, or the JS-node I/O round-trip through DuckDB),
        the node receives a single ref to it, which `load_from_duckdb` hands
        back as the whole `{dataType:'outputs', data:[...]}` wrapper dict,
        whatever dataType the request names. Without this, user code gets the
        wrapper object (e.g. `const [a,b] = input_0` → "input_0 is not iterable").
    In the reloaded case, resolve each inner element so the input matches the
    live list: the outputs it names are read too, which the backend checks
    first (``node_exec.wrapped_input_names``).
    """
    from utk_curio.sandbox.util.stored_inputs import read_stored

    return read_stored(
        input_data,
        lambda _index, elem: _resolve_outputs_elem(elem, session_id=session_id, saved_paths=saved_paths),
    )


def _make_curio_data_path(dataset_paths):
    """Resolver injected into user code as ``curio_data_path(dataset_id)``.

    Generated Data Loading nodes reference datasets by id instead of a baked-in
    absolute path; the backend resolves the ids it finds in the code and passes
    the mapping here. Missing ids raise with an actionable message rather than
    surfacing a broken foreign path from another machine or user.
    """
    mapping = dict(dataset_paths or {})

    def curio_data_path(dataset_id):
        path = mapping.get(str(dataset_id))
        if not path:
            raise RuntimeError(
                f"Dataset '{dataset_id}' is not available in this environment - "
                "install it from the Data Catalog drawer (or re-import the "
                "source file), then run this node again."
            )
        return path

    return curio_data_path


def _stage_package_modules(package_modules):
    """The modules the node's package ships, linked into a folder of this run's
    own as the isolated path links them into the child's scratch (#468).

    Returns ``(run_dir, (folder, names))``: *run_dir* is removed when the run
    ends, and ``(folder, names)`` is what ``package_modules.importable`` takes.
    ``(None, (None, ()))`` when the package ships none or nothing could be
    staged; the node's import then fails naming the module.
    """
    if not package_modules:
        return None, (None, ())
    from utk_curio.sandbox.isolation.supervisor import make_scratch_dir
    from utk_curio.sandbox.util.parsers import _shared_data_dir
    from utk_curio.sandbox.util.staging import stage_package_modules

    try:
        run_dir = make_scratch_dir(str(_shared_data_dir()))
    except OSError:
        return None, (None, ())
    staged = stage_package_modules(package_modules, run_dir)
    if not staged:
        return run_dir, (None, ())
    return run_dir, (os.path.join(run_dir, staged["root"]), tuple(staged["names"]))


def execute_code(code, file_path, node_type, data_type, launch_dir=None, session_id=None, save_dataset=True,
                 dataset_paths=None, secrets=None, collections=None, media_dir=None, models=None,
                 dataset_formats=None, package_modules=None, input_slots=None, saved_paths=None,
                 imports_session=None):
    """
    Execute user code in-process using pre-loaded library globals.

    session_id: Bearer token of the requesting session. Artifacts are stored and
                loaded scoped to this session so concurrent sessions never share
                execution state - even if they share the same user account.

    imports_session: the session the code's top-level imports are remembered
                under for the nodes after it (#158); *session_id* when not
                given. A kept run's artifacts carry a session of their own, its
                imports the caller's.

    save_dataset: changes nothing for a Python node, whose saved output is its
                artifact's own file, linked by the Data Catalog. Kept so this
                and ``runner.execute_isolated``, which the caller picks
                between, take the same arguments.

    saved_paths: {name: {"path" or "session", "dataType"}} for the inputs the
                backend resolved for the run's dataflow, each read, when the
                store has no row for it this session may read, in place from
                the file its owner's store holds, or from the store under the
                kept session that made it (``parsers.load_artifact``).

    dataset_paths: {datasetId: absolutePath} for the code's
                curio_load_data / curio_data_path / curio_load_collection
                calls, resolved (auth-scoped and containment-checked) by the
                backend.

    dataset_formats: {datasetId: {"format", "layerType"}}, how
                curio_load_data reads each of those datasets.

    collections, media_dir: where each curio_load_collection("<id>")
                collection's files are, and where a node may write the files
                it derives.

    models:     {modelId: folder} for the code's curio_load_model("<id>") calls.

    package_modules: {"root", "names"}, or a list of them: the modules the
                node's package ships beside its templates, and those of the
                packages it depends on, importable by name for this run only
                (#468, ``util/package_modules.py``).

    input_slots: the wired circles, in circle order: the value on circle k is
                the code's ``input_k`` (``util/input_names.py``).

    Returns {'stdout': [str, ...], 'stderr': str, 'output': {'path': str, 'dataType': str}}
    """
    import io as _io
    import os
    import sys
    import time
    import contextlib
    import traceback
    import warnings

    from utk_curio.sandbox.isolation.supervisor import cleanup_scratch
    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util import input_names, output_files
    from utk_curio.sandbox.util.codec import detect_kind
    from utk_curio.sandbox.util.parsers import _make_id, load_artifact, save_to_duckdb
    from utk_curio.sandbox.util.user_code import compile_user_code

    # _exec_lock serializes sys.stdout mutation and os.chdir.
    with _exec_lock.hold("exec_in_process"):
        # The run has its place: its reply goes quiet until it ends (#889).
        run_place.took_place()
        t0 = time.perf_counter()
        original_dir = os.getcwd()
        if launch_dir:
            os.chdir(launch_dir)

        captured_stdout = _io.StringIO()
        captured_stderr = _io.StringIO()
        result = {'path': '', 'dataType': 'str'}
        t_load = t_code = t_save = t0
        # #468: the package's own modules, importable until the run ends.
        modules_dir, modules = _stage_package_modules(package_modules)
        # The id the output is stored as, and the folder of the files the run
        # returns, named after it (util/output_files.py): made when the code
        # first writes there, removed when the run stores no output.
        art_id = _make_id()

        try:
            # catch_warnings: a node's run keeps the warning filters it changes
            # to itself (#749). A library imported here stays imported in this
            # process, and one that turns every warning on at import
            # (pythermalcomfort) did so for every later node, in every session.
            # _exec_lock serializes runs, so restoring the filters is safe.
            with warnings.catch_warnings(), \
                 contextlib.redirect_stdout(captured_stdout), \
                 contextlib.redirect_stderr(captured_stderr), \
                 importable(*modules):

                # Fresh namespace per call, so user *variables* never leak between
                # executions. Imports are the deliberate exception: this session's
                # accumulated import bindings are layered in so an upstream node's
                # `import numpy as np` reaches downstream nodes (#158).
                ns = dict(_globals_cache)
                imports_key = imports_session if imports_session is not None else session_id
                ns.update(_import_bindings_for(imports_key))
                # dev/116: connection keys, reachable only through this callable.
                ns['curio_secret'] = make_curio_secret(secrets)

                from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

                install_catalog_helpers(
                    ns,
                    data_path=_make_curio_data_path(dataset_paths),
                    formats=dataset_formats,
                    collections=collections,
                    media_dir=media_dir,
                    models=models,
                    output_dir=str(output_files.run_output_dir(art_id)),
                )
                # Code that still reads `arg` or `input`, or holds a chip spelled
                # [!! input 0 !!], is told what to write instead, rather than
                # reaching Python's built-in input() or a SyntaxError.
                legacy = input_names.legacy_input_problem(code)
                if legacy:
                    raise RuntimeError(legacy)
                # Hoist this node's own top-level imports before defining userCode,
                # so they are recorded for later nodes in the same session. The
                # statements stay in the function body too - re-importing is a
                # sys.modules hit, and it keeps a standalone run of this node working.
                _hoist_user_imports(code, ns, imports_key, skip=modules[1])
                # A relative path in docs/ that this folder does not hold reads
                # the file Curio ships (util/user_code.py).
                exec(compile_user_code(code, os.getcwd()), ns)

                # Load input from DuckDB.
                input_data = ''
                if data_type == 'outputs':
                    file_path_list = eval(file_path, {'__builtins__': {}})
                    input_data = [
                        _resolve_outputs_elem(elem, session_id=session_id, saved_paths=saved_paths)
                        for elem in file_path_list
                    ]
                elif file_path:
                    # The store, or a saved output of the dataflow, read in
                    # place (#407).
                    input_data = load_artifact(file_path, session_id=session_id, saved_paths=saved_paths)
                input_data = _expand_outputs_wrapper(input_data, session_id=session_id, saved_paths=saved_paths)
                # A raster an Autark node handed on arrives as a rasterio
                # dataset, as a Python node's raster does.
                from utk_curio.sandbox.util.rasters import python_raster_dir, rasters_for_python
                input_data = rasters_for_python(input_data, python_raster_dir)
                t_load = time.perf_counter()

                # Each wired circle k is the code's input_k. dev/120: no
                # name-keyed I/O check here: the type contract is the
                # template's declared ports, enforced by the canvas at connect
                # time.
                inputs = input_names.split_inputs(input_data, input_slots, data_type)

                # Code that reads an input none arrived on would fail on the
                # first `input_0[...]` with a confusing `'NoneType' object is
                # not subscriptable`. Fail here instead, naming the circle, so
                # the user looks at what feeds it (unwired, unrun or failed).
                # An AST walk, so a node that merely spells the name in a
                # comment or a string is not refused (#273).
                missing = input_names.missing_input(code, inputs)
                if missing:
                    raise RuntimeError(missing)

                # Run user code.
                output = ns['userCode'](**inputs)
                t_code = time.perf_counter()

                # Classify output (dev/120: classified, never refused by node name).
                out_kind = detect_kind(output)

                # Save output to DuckDB, tagged with the session that produced
                # it. A saved output is this artifact's own file, which the
                # Data Catalog links (``bundle.install_node_output``), so a
                # run with Save on writes nothing else.
                result_path = save_to_duckdb(output, node_id=node_type, session_id=session_id, art_id=art_id)

                result = {'path': result_path, 'dataType': out_kind}
                t_save = time.perf_counter()

        except BaseException:
            captured_stderr.write(traceback.format_exc())

        finally:
            os.chdir(original_dir)
            if modules_dir:
                cleanup_scratch(modules_dir)
            if not result['path']:
                output_files.forget_run_output(art_id)
            # The connection stays open. It used to be dropped here so the
            # backend could open the file read-only between runs, which made
            # the handle's lifetime a negotiation between two processes: the
            # reopen cost every execution, a collision made the backend read
            # nothing, and closing it under a concurrent request was the
            # cause of two failures the stress tiers found. The backend now
            # reads artifacts through /artifact-meta instead, so this process
            # is the only one that ever opens curio_data.duckdb and can keep
            # one connection for its lifetime. Anything that genuinely needs
            # the file free (teardown, tests) calls release_connection().
            t1 = time.perf_counter()
            print(
                f"[exec] load={t_load-t0:.3f}s  code={t_code-t_load:.3f}s"
                f"  save={t_save-t_code:.3f}s  total={t1-t0:.3f}s",
                file=sys.__stderr__,
                flush=True,
            )

        # dev/116: a printed key must not ride the response into the runtime
        # journal, the validation trail or a card.
        stdout_text = redact(captured_stdout.getvalue(), secrets)
        stdout_lines = [line for line in stdout_text.split('\n') if line]
        return {
            'stdout': stdout_lines,
            'stderr': redact(captured_stderr.getvalue(), secrets),
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
        fc = json.loads(obj.to_json())
        # A frame's layer name rides as the FeatureCollection's own `name`, so
        # a layer chip finds it (curio_layer in util/js_wrapper.mjs).
        meta = obj.__dict__.get('metadata')
        if isinstance(meta, dict) and isinstance(meta.get('name'), str) and meta['name']:
            fc['name'] = meta['name']
        return fc
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient='records')
    if isinstance(obj, (list, tuple)):
        return [_to_js_value(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_js_value(v) for k, v in obj.items()}
    return str(obj)


def _js_value_to_saveable_frame(value):
    """Best-effort convert a JS node's JSON result into a ``(kind, frame)`` pair
    to store as a frame artifact, or ``(None, None)`` when it isn't tabular.

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
#
# The cause is an undici regression (nodejs/undici#5360), bundled with Node 24
# from 24.17 on and fixed in undici 8.6. The project now runs Node 26, which
# bundles undici 8, so this should no longer fire; the retry stays as a safety
# net for a local install on an affected Node 24.
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

#: The longest one Node.js run may take. Past it, Node is killed with every
#: process it started (on Windows, Node alone), and the run raises
#: ``subprocess.TimeoutExpired``.
JS_TIMEOUT_SECONDS = 3000

#: How long Node's pipes may stay open once Node and every process it started
#: have been killed. Only a process the kills missed can hold them; past this,
#: their readers stop, and the run ends and frees its slot.
JS_OUTPUT_GRACE_SECONDS = 5

#: POSIX: Node runs in a session of its own, so a kill of its process group
#: reaches every process it started, and a selector can wait on its pipes.
#: Windows has neither: a kill reaches Node alone, and a read just waits.
_IS_POSIX = os.name == 'posix'

#: Linux: no process Node starts can leave Node's process group, which a
#: seccomp filter denies it (:func:`_node_command`).
_IS_LINUX = sys.platform.startswith('linux')

#: The variable that marks a run's processes: Node's environment holds it,
#: with a value of the run's own, and every process Node starts inherits it
#: unless it is given an environment of its own. Off Linux it finds one that
#: left Node's process group.
_RUN_MARK = 'CURIO_JS_RUN'

#: How often a reader waiting on a quiet pipe looks whether to stop.
_PIPE_POLL_SECONDS = 0.1


def _read_node_pipe(pipe, keep, stop):
    """Hand *keep* each line of one of Node's pipes, without its newline,
    until the pipe ends or *stop* is set, then close the pipe.

    On POSIX it reads the pipe's descriptor only when a selector says
    something came, so it is never inside a read: it sees *stop* while a
    process Node started holds the pipe open and writes nothing, and no other
    thread has to close the pipe under a read (that close would wait for the
    read). Where a selector cannot wait on the pipe (Windows, or a pipe with
    no descriptor) it reads lines, and a read waits for a line or the end.
    """
    import codecs
    import io
    import selectors

    try:
        fd = None
        if _IS_POSIX:
            with contextlib.suppress(AttributeError, OSError, ValueError):
                fd = pipe.fileno()
        if fd is None:
            for line in pipe:
                keep(line.rstrip('\n'))
                if stop.is_set():
                    break
            return
        # Read as the text pipe would: utf-8 with bad bytes replaced, and a
        # line ended by \r\n or \r as by \n.
        decoder = io.IncrementalNewlineDecoder(
            codecs.getincrementaldecoder('utf-8')(errors='replace'), translate=True)
        line = []
        with getattr(selectors, 'PollSelector', selectors.SelectSelector)() as selector:
            selector.register(fd, selectors.EVENT_READ)
            while not stop.is_set():
                if not selector.select(_PIPE_POLL_SECONDS):
                    continue
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    data = b''
                *ends, rest = decoder.decode(data, final=not data).split('\n')
                for end in ends:
                    line.append(end)
                    keep(''.join(line))
                    line.clear()
                if rest:
                    line.append(rest)
                if not data:
                    break
        if line:
            keep(''.join(line))
    finally:
        with contextlib.suppress(OSError):
            pipe.close()


def _wait_for_node(proc, timeout):
    """Wait up to *timeout* for Node to exit, and raise
    ``subprocess.TimeoutExpired`` past it, as ``Popen.wait`` does.

    Where ``os.waitid`` is (Linux), Node is left unreaped: until it is reaped
    its pid, which is its process group's id, names no other process, so the
    kill of that group reaches this run's processes alone. Elsewhere
    ``Popen.wait`` reaps it.
    """
    import subprocess

    if not (_IS_POSIX and hasattr(os, 'waitid') and proc.pid > 0):
        proc.wait(timeout=timeout)
        return
    deadline = time.monotonic() + timeout
    delay = 0.0005
    while True:
        try:
            if os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                return
        except ChildProcessError:  # reaped already
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(proc.args, timeout)
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, 0.05)


def _kill_marked(mark, since):
    """Kill every process started since *since* whose environment carries
    the run's *mark*, and return how many. A process can start another
    before it is killed, so this looks again until a look finds none, five
    looks at most."""
    try:
        import psutil
    except ImportError:  # a broken install: the group kill still runs
        return 0

    killed = 0
    for _ in range(5):
        found = 0
        for process in psutil.process_iter():
            try:
                if process.create_time() < since or process.environ().get(_RUN_MARK) != mark:
                    continue
                process.kill()
                found += 1
            except (psutil.Error, OSError):
                continue
        killed += found
        if not found:
            break
    return killed


def _kill_node(proc, mark, since):
    """Kill Node, if it still runs, with every process it started, and return
    how many processes carrying the run's *mark* were killed.

    On POSIX: every process started since *since* whose environment carries
    *mark* (every process Node starts inherits it unless given an environment
    of its own; off Linux, one that left Node's process group still carries
    it: ``detached: true`` calls setsid), then the group, which on Linux holds
    every process Node started, marked or not (:func:`_node_command`). On
    Windows, Node alone.
    """
    import signal

    killed = 0
    # A pid of 0 would name the sandbox's own group.
    if _IS_POSIX and proc.pid > 0:
        killed = _kill_marked(mark, since)
        # Node is unreaped here where _wait_for_node leaves it so, and a group
        # outlives Node while any process is in it: either way the group's id
        # names what this run started.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
    proc.kill()
    return killed


def _joined(threads, seconds):
    """Join *threads*, *seconds* for all of them; True when every one ended."""
    deadline = time.monotonic() + seconds
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    return not any(thread.is_alive() for thread in threads)


def _node_command(env):
    """The command that starts Node for one run, *env* its environment.

    On Linux, Node starts through the exec wrapper of
    ``isolation/seccomp_filter.py``, the isolated child's filter code: Popen's
    ``start_new_session`` makes the wrapper a session and process group
    leader, and the wrapper denies setsid and setpgid with EPERM to itself and
    to every process it starts, then execs Node, which keeps its pid. So no
    process Node starts can leave Node's process group, which the run kills
    when Node exits (:func:`_end_node_run`), whatever its environment. libuv's
    ``detached: true`` ignores the EPERM its setsid gets, so a detached child
    still starts, in that group. ``tests/test_js_run_kills_at_return.py``
    guards it; never weaken, skip or remove its tests.

    Under ``CURIO_ISOLATION=fork`` a run whose filter cannot be installed
    does not start Node and fails, saying why, as an isolated child that
    cannot confine itself does; otherwise Node then runs without it. Node is
    found on *env*'s PATH, as Popen finds it, so a missing Node raises
    FileNotFoundError here, as Popen does. Off Linux, Node starts as it is.
    """
    import errno
    import shutil

    if not _IS_LINUX:
        return ['node', '--input-type=commonjs']
    node = shutil.which('node', path=os.pathsep.join(os.get_exec_path(env)))
    if node is None:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), 'node')
    from utk_curio.sandbox.isolation import mode, seccomp_filter

    requested = mode.mode_from_environment()[0].strip().lower()
    return seccomp_filter.exec_command(
        [node, '--input-type=commonjs'], required=requested == mode.FORK)


def _end_node_run(proc, threads, stop, node_type, mark, since):
    """End a Node run once Node has exited, or reached its timeout.

    Owner rule, 11-07, never to change and with no option to turn it off:
    every process a JavaScript node starts ends when the node returns. So
    first Node, if it still runs, is killed with every process it started
    (:func:`_kill_node`). Then Node is reaped and its pipes read out: their
    threads get ``JS_OUTPUT_GRACE_SECONDS`` to reach the pipes' end, readers
    still waiting are told to stop, and one that cannot stop (on Windows, a
    read under a process the kill did not reach) is left behind. The run
    ends anyway, and frees its slot. ``tests/test_js_run_kills_at_return.py``
    guards the rule; never weaken, skip or remove its tests.
    """
    import subprocess
    import sys

    killed = _kill_node(proc, mark, since)
    if killed:
        print(f"[execJs] Node.js ended; killed {killed} process(es) it started  node={node_type}",
              file=sys.__stderr__, flush=True)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=JS_OUTPUT_GRACE_SECONDS)
    if _joined(threads, JS_OUTPUT_GRACE_SECONDS):
        return
    stop.set()
    if not _joined(threads, 1):
        print(f"[execJs] left a pipe of Node.js open: a process it started still holds it  "
              f"node={node_type}", file=sys.__stderr__, flush=True)


def run_js_script(code, inputs, *, cwd, node_type, t0=None, node_modules=None):
    """Run JavaScript in one Node.js subprocess, the way a JS node runs.

    The code is wrapped by ``util/js_wrapper.mjs`` with each of *inputs*,
    ``{"input_k": value}``, as a parameter of that name (an ``input_k`` the
    code reads and *inputs* lacks is a parameter too, undefined), its bare
    package imports are resolved against *node_modules* (default: the
    sandbox's, ``node_runtime.node_modules_dir``), and it runs under the JS
    slot, once more if Node died in its own HTTP parser.

    :func:`execute_js_code` runs Node through this. Returns
    ``(result_json, user_log_lines, stderr_lines)``: the
    text of the result line, or None when Node printed none. A missing Node
    raises, as ``subprocess`` does. Node runs at most ``JS_TIMEOUT_SECONDS``:
    past it, it is killed, and this raises ``subprocess.TimeoutExpired``.
    Every process Node started is killed when Node exits, or at that timeout
    (:func:`_end_node_run`), so a run always ends and gives its slot back.
    """
    import json
    import pathlib
    import re
    import secrets
    import subprocess
    import sys as _sys
    import threading
    import time

    if t0 is None:
        t0 = time.perf_counter()

    # Resolve bare package specifiers (e.g. '@urban-toolkit/autk-db') to an
    # ABSOLUTE file URL under the sandbox's node_modules so the dynamic ESM
    # import() below resolves regardless of the Node subprocess cwd. Node's ESM
    # resolver does NOT consult NODE_PATH and resolves a bare specifier only by
    # walking node_modules up from the importing module - which fails when
    # CURIO_LAUNCH_CWD is outside that folder. Rewriting only the top-level
    # specifier is enough: the package's own internal imports still resolve
    # relative to its installed location.
    root_node_modules = pathlib.Path(node_modules) if node_modules is not None else node_modules_dir()

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

    # The inputs as an inline JS literal, and one parameter per input_k: each
    # one given, and each the code reads (util/input_names.py).
    from utk_curio.sandbox.util.input_names import INPUT_NAME_RE, input_name, input_names_read_js

    inputs = {name: value for name, value in dict(inputs or {}).items() if INPUT_NAME_RE.match(name)}
    params = sorted(
        set(inputs) | {input_name(k) for k in input_names_read_js(code)},
        key=lambda name: int(INPUT_NAME_RE.match(name).group(1)),
    )
    inputs_json = json.dumps({name: _to_js_value(value) for name, value in inputs.items()})

    # Build script from static template - no temp file written to disk.
    template_path = pathlib.Path(__file__).parent.parent / 'util' / 'js_wrapper.mjs'
    template = template_path.read_text(encoding='utf-8')
    script = (template
              .replace('__INPUT_PARAMS__', ', '.join(params))
              .replace('__INPUT_ARGS__', ', '.join(f'__inputs.{name}' for name in params))
              .replace('__DYNAMIC_IMPORTS__', dynamic_imports_block)
              .replace('__INPUTS_JSON__', inputs_json)
              .replace('__OVERPASS_USER_AGENT__', json.dumps(OVERPASS_USER_AGENT))
              .replace('__USER_CODE__', indented))

    # NODE_PATH is a belt-and-braces aid for any CJS require() autk-db's
    # worker threads perform (see node_runtime.node_env). cwd stays
    # launch_dir so other JS nodes' relative file reads keep working.
    node_env_vars = node_env(node_modules=root_node_modules)

    def _run_node():
        """Run the script in one Node subprocess, up to the JS ceiling.

        Returns ``(exit_code, stdout_lines, stderr_lines)``. Factored out of
        the body only so a crash inside Node itself can be retried: every
        input it reads (``script``, ``cwd``, ``node_env_vars``) is fully built by
        this point, so a second call re-runs the same execution rather than a
        different one.
        """
        slot = _js_slot()
        waited_at = time.perf_counter()
        slot.acquire()
        try:
            queued = time.perf_counter() - waited_at
            if queued > 1.0:
                print(f"[execJs] waited {queued:.1f}s for a slot  node={node_type}",
                      file=_sys.__stderr__, flush=True)
            # The run has its place: its reply goes quiet until it ends (#889).
            run_place.took_place()
            return _run_node_holding_slot()
        finally:
            slot.release()

    def _run_node_holding_slot():
        print(f"[execJs] starting Node.js  node={node_type}", file=_sys.__stderr__, flush=True)
        t_start = time.perf_counter()

        # A session of its own (POSIX), so a kill of its group reaches every
        # process Node starts, not Node alone, and on Linux none can leave it
        # (_node_command); and the run's mark, which finds, off Linux, those
        # that leave the group. psutil reads a process's start to the second
        # at worst (Linux counts from the boot second), hence the 2 s.
        mark = secrets.token_hex(16)
        since = time.time() - 2
        env = {**node_env_vars, _RUN_MARK: mark}
        proc = subprocess.Popen(
            _node_command(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', cwd=cwd,
            env=env, start_new_session=_IS_POSIX,
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def _keeper(lines, label):
            def keep(line):
                lines.append(line)
                if not line.startswith('__CURIO_JSON_RESULT__'):
                    print(f"[execJs] {label}: {line}", file=_sys.__stderr__, flush=True)
            return keep

        def _write_stdin(proc, data):
            try:
                proc.stdin.write(data)
            except OSError:  # Node is gone: it crashed, or was killed
                pass
            finally:
                with contextlib.suppress(OSError):
                    proc.stdin.close()

        stop = threading.Event()
        threads = (
            threading.Thread(target=_write_stdin, args=(proc, script), daemon=True),
            threading.Thread(target=_read_node_pipe, daemon=True,
                             args=(proc.stdout, _keeper(stdout_lines, 'stdout'), stop)),
            threading.Thread(target=_read_node_pipe, daemon=True,
                             args=(proc.stderr, _keeper(stderr_lines, 'stderr'), stop)),
        )
        for thread in threads:
            thread.start()

        try:
            _wait_for_node(proc, JS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            print(f"[execJs] Node.js ran past {JS_TIMEOUT_SECONDS} s; killing it with every "
                  f"process it started  node={node_type}", file=_sys.__stderr__, flush=True)
            _end_node_run(proc, threads, stop, node_type, mark, since)
            raise
        _end_node_run(proc, threads, stop, node_type, mark, since)

        print(f"[execJs] Node.js finished  total={time.perf_counter()-t_start:.3f}s  "
              f"exit={proc.returncode}  node={node_type}",
              file=_sys.__stderr__, flush=True)
        return proc.returncode, stdout_lines, stderr_lines

    exit_code, stdout_lines, stderr_lines = _run_node()

    # One retry, and only for a crash inside Node's own HTTP parser. See
    # is_node_internal_stream_crash for why re-running is the only response
    # available to us. The cost is bounded: a run that does not hit it pays
    # one substring scan of stderr.
    if is_node_internal_stream_crash(exit_code, stdout_lines, stderr_lines):
        print(f"[execJs] Node died inside its own HTTP parser before user code "
              f"could either fail or produce a result; retrying once  "
              f"node={node_type}", file=_sys.__stderr__, flush=True)
        exit_code, stdout_lines, stderr_lines = _run_node()
        print(f"[execJs] retry {'hit it too' if is_node_internal_stream_crash(exit_code, stdout_lines, stderr_lines) else 'cleared it'}"
              f"  total_with_retry={time.perf_counter()-t0:.3f}s  node={node_type}",
              file=_sys.__stderr__, flush=True)

    # Extract result from stdout - a single line prefixed with __CURIO_JSON_RESULT__.
    RESULT_PREFIX = '__CURIO_JSON_RESULT__'
    result_json = None
    user_log_lines = []
    for line in stdout_lines:
        if line.startswith(RESULT_PREFIX):
            result_json = line[len(RESULT_PREFIX):]
        else:
            user_log_lines.append(line)

    return result_json, user_log_lines, stderr_lines


def execute_js_code(code, file_path, node_type, data_type, launch_dir=None, session_id=None, save_dataset=True,
                    input_slots=None, saved_paths=None):
    """
    Execute user JavaScript code in an isolated Node.js subprocess.

    input_slots: the wired circles, in circle order: the value on circle k is
    the code's ``input_k``, as in :func:`execute_code`.

    saved_paths: the inputs that are saved outputs of the run's dataflow, read
    in place as :func:`execute_code` reads them.

    Input is loaded from Python DuckDB, serialized to JSON, and embedded directly
    in the script piped to `node --input-type=module` via stdin - no temp files.
    The result arrives as a specially-prefixed stdout line and is stored in Python
    DuckDB, mirroring execute_code()'s behaviour exactly.

    Returns {'stdout': [str, ...], 'stderr': str, 'output': {'path': str, 'dataType': str}}
    """
    import json
    import os
    import subprocess
    import sys as _sys
    import time
    import traceback

    from utk_curio.sandbox.util.parsers import (
        load_artifact, save_to_duckdb, detect_kind,
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
            input_data = [_resolve_outputs_elem(elem, session_id=session_id, saved_paths=saved_paths)
                          for elem in file_path_list]
        elif file_path:
            input_data = load_artifact(file_path, session_id=session_id, saved_paths=saved_paths)
        input_data = _expand_outputs_wrapper(input_data, session_id=session_id, saved_paths=saved_paths)

        # Each wired circle k is the code's input_k (util/input_names.py), as
        # in a Python node; old names and old chips are told the new ones.
        from utk_curio.sandbox.util import input_names

        refused = input_names.legacy_input_problem(code, javascript=True)
        inputs = input_names.split_inputs(input_data, input_slots, data_type)
        refused = refused or input_names.missing_input(code, inputs, javascript=True)
        if refused:
            return {'stdout': [], 'stderr': refused, 'output': {'path': '', 'dataType': 'str'}}

        result_json, user_log_lines, stderr_lines = run_js_script(
            code, inputs, cwd=cwd, node_type=node_type, t0=t0,
        )

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

        # A JS node's value is JSON in the store. When the node saves its
        # output and the value is a table, the table is stored once more as a
        # frame artifact of its own, whose parquet the Data Catalog links as a
        # Python node's is: output['dataset'] names it.
        if save_dataset:
            try:
                _kind, frame = _js_value_to_saveable_frame(raw_value)
                if frame is not None:
                    output['dataset'] = save_to_duckdb(frame, node_id=node_type, session_id=session_id)
            except Exception:  # noqa: BLE001 - dataset save is best-effort
                print(f"[execJs] save_dataset failed for node={node_type}",
                      file=_sys.__stderr__, flush=True)

        return {
            'stdout': run_result.get('logs', []),
            'stderr': stderr_text,
            'output': output,
        }

    except subprocess.TimeoutExpired:
        return {'stdout': [], 'stderr': f'JavaScript execution timed out ({JS_TIMEOUT_SECONDS} s)',
                'output': {'path': '', 'dataType': 'str'}}
    except FileNotFoundError:
        return {'stdout': [], 'stderr': 'Node.js not found. Please install Node.js to use JS Computation nodes.',
                'output': {'path': '', 'dataType': 'str'}}
    except Exception:
        return {'stdout': [], 'stderr': traceback.format_exc(), 'output': {'path': '', 'dataType': 'str'}}
    # No release here either: see the note in execute_code. The JS path is the
    # one where dropping the connection mid-flight actually bit, since several
    # Autark loads finish at once.
