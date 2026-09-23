from flask import request, abort, jsonify, Response
from functools import wraps
import json
import sys
import geopandas as gpd
import pandas as pd
from utk_curio.sandbox import metrics
from utk_curio.sandbox.app import app, cache
from utk_curio.sandbox.app.auth import require_sandbox_token
from utk_curio.sandbox.app.utils.cache import make_key
import os
import mmap

from shapely import wkt

from utk_curio.sandbox.app.worker import (
    _artifact_slots, _worker_init, execute_code, execute_js_code,
)
from utk_curio.sandbox.util.db import connection_in_use


def holds_duckdb(view):
    """Keep the shared DuckDB connection open for one whole request.

    Every execution path releases the connection when it finishes, because
    DuckDB allows a single cross-process writer and the backend needs to open
    the file read-only between runs. On a threaded server that release lands
    while other requests are still using the connection: concurrent Autark
    data loads failed mid-INSERT with "Connection already closed!" at ten
    simultaneous users. Under this decorator the release is deferred to
    whichever request leaves last, so the cross-process contract is unchanged
    and no request loses its connection halfway through.

    Note what this is not: a lock. Requests still run in parallel -- N Node
    subprocesses for N Autark loads, exactly as before.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        with connection_in_use():
            return view(*args, **kwargs)

    return wrapper
from utk_curio.sandbox.util.parsers import (
    load_from_duckdb,
    load_shared_output_file,
    load_tabular_arrow_from_duckdb,
    load_tabular_preview_from_duckdb,
    parseOutput,
)

ARROW_IPC_MIME = "application/vnd.apache.arrow.stream"

# Pre-load heavy libraries once at sandbox startup so every /exec call is fast.
_worker_init()

DATA_DIR = "./data"

# No CORS headers here on purpose. The sandbox is reached only by the backend
# over server-to-server HTTP; no browser ever calls it directly (see
# docs/ARCHITECTURE.md). The previous `Access-Control-Allow-Origin: *` granted
# every page in the user's browser permission to read responses from a service
# whose whole job is executing code, for no functional gain.

@app.route('/')
def root():
    abort(403)

@app.route('/live', methods=['GET'])
def live():
    return 'Sandbox is live.'

_resolved_isolation_label = None


def _isolation_label():
    """The isolation mode actually in force, as one word, cached.

    The *resolved* mode, never the requested one: `auto` resolves to `off`, and
    a `fork` that the platform cannot support degrades to `off` on a local
    launch. Reporting `CURIO_ISOLATION` instead would tell an operator what was
    asked for rather than what they got, which is the opposite of useful.

    Cached because the badge asks on every page load and resolution probes the
    platform's capabilities.
    """
    global _resolved_isolation_label
    if _resolved_isolation_label is not None:
        return _resolved_isolation_label

    from utk_curio.sandbox.isolation import mode as isolation_mode
    try:
        resolved, _reason = isolation_mode.resolve_from_environment()
        _resolved_isolation_label = resolved
    except isolation_mode.IsolationUnavailable:
        # A hosted instance in this state never finishes booting (server.py
        # raises), so reaching here means a local launch asked for something
        # unavailable. Say so rather than implying either mode.
        _resolved_isolation_label = 'unavailable'
    return _resolved_isolation_label


def _isolation_active_label():
    """What node execution is actually DOING, not what was resolved.

    ``_isolation_label`` answers "what did this instance resolve to". That is a
    configuration question and it is settled before any node runs, which makes
    it the wrong thing to check when the question is "did this workload go
    through the confined path".

    The two can disagree, and nothing used to report it. The zygote is started
    lazily, on the first ``/exec`` (``_isolation_runner`` below is the only
    caller of ``lifecycle.ensure_running`` in the tree; ``server.py`` hardens
    at boot but starts nothing). A spawn that fails is not fatal by design -
    the node still has to run - so the sandbox degrades to in-process and
    caches that for the life of the process, while the resolved label goes on
    saying ``fork``.

    - ``pending``: no node has executed yet, so there is nothing to report.
    - ``fork``: executions are being dispatched to the zygote.
    - ``off``: node code is running in this process.

    Deliberately reports the decision rather than ``lifecycle.is_running()``.
    Liveness answers "is a zygote up right now", which flaps: the zygote can
    die after a workload finishes and be respawned on the next request, and
    neither changes the fact that the executions went through the fork path.
    """
    state = _isolation_state
    if state is None:
        return 'pending'
    return 'fork' if state else 'off'


@app.route('/version', methods=['GET'])
def version():
    from utk_curio import __version__
    # Deliberately un-gated, like /live and /health: this is what the UI's
    # version badge reads through the backend, and it discloses nothing a
    # caller could not learn by watching whether node code can open a socket.
    return jsonify({
        'version': __version__,
        'isolation': _isolation_label(),
        'isolation_active': _isolation_active_label(),
    })

@app.route('/monitor', methods=['GET'])
@require_sandbox_token
def monitor():
    """Execution counters, live capacity and recent failures, for the backend.

    Gated, unlike /version. /version discloses nothing; this route reports how
    much capacity is free and carries raw failure text, and its only caller is
    the backend, which already holds the shared secret. Nothing else should be
    able to read it directly.

    The isolation labels come from the same two helpers the version badge uses,
    so the badge and the monitor page can never disagree about what this
    sandbox is doing.
    """
    from utk_curio.sandbox.isolation import lifecycle, runner

    payload = metrics.snapshot()
    payload['isolation'] = _isolation_label()
    payload['isolation_active'] = _isolation_active_label()
    payload['errors'] = metrics.errors()

    # The limits actually in force when a zygote is up, else the ones this
    # process would use if one started. Both are worth reporting: an operator
    # comparing a configured budget against a running one is exactly how the
    # "I set --exec-memory-mb and nothing changed" question gets answered.
    config = None
    state = _isolation_state
    if isinstance(state, tuple):
        config = state[1]
    else:
        try:
            config = runner.IsolationConfig.from_environment()
        except Exception:  # noqa: BLE001 - a monitor never fails over config
            config = None

    if config is not None:
        payload['parallelism'] = config.parallelism
        payload['memory_limit_mb'] = config.limits.get('memory_mb')
        payload['cpu_seconds_limit'] = config.limits.get('cpu_seconds')
        payload['wall_timeout_seconds'] = config.wall_timeout
    else:
        payload['parallelism'] = None
        payload['memory_limit_mb'] = None
        payload['cpu_seconds_limit'] = None
        payload['wall_timeout_seconds'] = None

    try:
        payload['zygote_running'] = bool(lifecycle.is_running())
    except Exception:  # noqa: BLE001
        payload['zygote_running'] = None

    # This process's own resident memory. It is the one running node code, so
    # it is the number an operator chasing an OOM actually wants.
    payload['rss_bytes'] = metrics.process_rss_bytes()

    # Contention on the process-wide execution lock, per call site. A slot
    # queue and a lock queue look identical from the outside -- both are a
    # request taking minutes that takes a second when idle -- and only this
    # tells them apart. Cumulative since startup; a caller comparing two
    # snapshots gets the interval.
    try:
        from utk_curio.sandbox.app.worker import _artifact_slots, _exec_lock

        payload['exec_lock'] = _exec_lock.snapshot()
        # The artifact route's own ceiling, reported the same way: whether
        # fetches are queueing is a different question from whether node
        # executions are, and the two used to be the same number.
        payload['artifact_slots'] = _artifact_slots.snapshot()
    except Exception:  # noqa: BLE001 - a monitor never fails over its subject
        payload['exec_lock'] = None
        payload['artifact_slots'] = None

    return jsonify(payload)


@app.route('/get', methods=['GET'])
@require_sandbox_token
@holds_duckdb
def get_artifact():
    import pandas as _pd
    import traceback as _tb
    art_id = request.args.get('fileName')
    if not art_id:
        abort(400, "fileName is required")
    session_id = request.args.get('sessionId') or None
    max_rows_param = request.args.get('maxRows')

    if request.accept_mimetypes.best == ARROW_IPC_MIME:
        return _get_artifact_arrow(art_id, session_id, max_rows_param)

    # Bounded, and no chdir. This load used to run inside the sandbox's
    # process-wide execution lock, because a raster re-opens by a path that
    # can be relative to the launch directory and os.chdir is process-wide.
    # That made node executions queue behind artifact fetches: 18722s of
    # waiting across a 100-user tier for 407s of actual work.
    # parsers._resolve_raster_source resolves the path explicitly instead, so
    # the lock is gone from here entirely.
    #
    # A ceiling stays, because removing the lock without one replaced the
    # queue with a stampede: a hundred concurrent loads, 5GB more peak memory
    # and a fifth of the users past the 300s deadline that none had hit
    # before. _artifact_slots lets fetches overlap while capping how many
    # materialise a frame at once; node executions do not wait on it at all.
    max_rows = int(max_rows_param) if max_rows_param is not None else None
    try:
        with _artifact_slots.hold("artifact_load"):
            total_rows = None
            raw = None
            try:
                if max_rows is not None:
                    preview = load_tabular_preview_from_duckdb(
                        art_id,
                        max_rows,
                        session_id=session_id,
                    )
                    if preview is not None:
                        raw, total_rows = preview
                if raw is None:
                    raw = load_from_duckdb(art_id, session_id=session_id)
                    if max_rows is not None and isinstance(raw, _pd.DataFrame):
                        total_rows = len(raw)
                        raw = raw.head(max_rows)
            except Exception as store_error:
                # The store could not serve it. Three ways that happens and all
                # three mean the same thing to a caller holding a project's
                # saved output: no such row, a row this session may not read
                # (rows are session-tagged), or no readable database at all -
                # the file is created on first write and can be locked by a
                # concurrent /exec. So try the shared data directory, where a
                # project load hydrates every output the manifest records. That
                # file carries no session tag, which is what lets a dashboard -
                # or any second viewer - read an output the producing session no
                # longer owns.
                try:
                    raw = load_shared_output_file(art_id)
                except KeyError:
                    # Nothing hydrated under that name either. Report what the
                    # STORE said rather than what the fallback said: for a
                    # genuinely missing artifact that is the same KeyError this
                    # route has always returned, and for a locked or missing
                    # database it keeps the diagnostic instead of replacing it
                    # with a misleading "no artifact with id".
                    raise store_error
                total_rows = None
                if max_rows is not None and isinstance(raw, _pd.DataFrame):
                    total_rows = len(raw)
                    raw = raw.head(max_rows)
            data = parseOutput(raw)
    except Exception as e:
        # Surface the underlying exception in the response body so callers
        # see *why* the load failed instead of an empty 500 page.
        #
        # ...and in the log as well. The backend does not relay this body (it
        # answers "Error loading artifact: 500 Server Error"), so a load that
        # fails under load left no account of itself anywhere a CI run could
        # read afterwards.
        print(f"[sandbox /get] failed  fileName={art_id}  session={session_id}\n"
              f"{_tb.format_exc()}", file=sys.stderr, flush=True)
        return jsonify({
            'error': type(e).__name__,
            'message': str(e),
            'fileName': art_id,
            'sessionId': session_id,
            'traceback': _tb.format_exc(),
        }), 500
    data['filename'] = art_id
    if total_rows is not None:
        data['preview'] = True
        data['previewRows'] = min(max_rows, total_rows)
        data['totalRows'] = total_rows
    return jsonify(data)


def _get_artifact_arrow(art_id, session_id, max_rows_param):
    """Serve a tabular artifact as an Arrow IPC stream.

    parquet blob -> pyarrow.Table via pyarrow.parquet.read_table (no pandas).
    Non-tabular kinds -> 415 so clients can fall back to the JSON path.
    """
    import traceback as _tb
    import pyarrow as pa
    import pyarrow.ipc as ipc
    try:
        table, kind, frame_metadata, encoded_object_columns = (
            load_tabular_arrow_from_duckdb(art_id, session_id=session_id)
        )
    except KeyError as e:
        return jsonify({
            'error': 'KeyError',
            'message': str(e),
            'fileName': art_id,
            'sessionId': session_id,
        }), 404
    except ValueError as e:
        return jsonify({
            'error': 'not_acceptable',
            'message': str(e) + '; re-request without the Arrow Accept header.',
            'fileName': art_id,
            'sessionId': session_id,
        }), 415
    except Exception as e:
        return jsonify({
            'error': type(e).__name__,
            'message': str(e),
            'fileName': art_id,
            'sessionId': session_id,
            'traceback': _tb.format_exc(),
        }), 500

    total_rows = None
    if max_rows_param is not None:
        max_rows = int(max_rows_param)
        if table.num_rows > max_rows:
            total_rows = table.num_rows
            table = table.slice(0, max_rows)

    sink = pa.BufferOutputStream()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    body = sink.getvalue().to_pybytes()

    headers = {
        'X-Curio-Kind': kind,
        'X-Curio-Filename': art_id,
    }
    if total_rows is not None:
        headers['X-Curio-Preview'] = 'true'
        headers['X-Curio-Preview-Rows'] = str(min(int(max_rows_param), total_rows))
        headers['X-Curio-Total-Rows'] = str(total_rows)
    if encoded_object_columns:
        headers['X-Curio-Encoded-Object-Columns'] = ','.join(encoded_object_columns)
    if kind == 'geodataframe' and frame_metadata:
        headers['X-Curio-Frame-Metadata'] = json.dumps(frame_metadata)

    return Response(body, mimetype=ARROW_IPC_MIME, headers=headers)

# Isolation is resolved once, on the first /exec, and cached. Resolving per
# request would repeat the capability probe and the warning on every node.
# None means "not resolved yet"; False means "resolved to the in-process path".
_isolation_state = None
_isolation_lock = __import__('threading').Lock()


def _isolated_runner():
    """Return ``(callable, config)`` when isolation is active, else None.

    Falls back to the in-process path, loudly, if the zygote cannot be started.
    A hosted instance has already refused to boot in that situation
    (``sandbox/server.py`` calls ``mode.resolve_mode`` at startup), so reaching
    the fallback here means a local launch, where degrading beats failing.
    """
    global _isolation_state

    if _isolation_state is not None:
        return _isolation_state or None

    with _isolation_lock:
        if _isolation_state is not None:
            return _isolation_state or None

        from utk_curio.sandbox.isolation import mode as isolation_mode

        try:
            resolved, reason = isolation_mode.resolve_from_environment()
        except isolation_mode.IsolationUnavailable as exc:
            # server.py should have caught this at boot; if we somehow get here,
            # do not silently run unisolated on a hosted instance.
            print(f"[isolation] {exc}", file=sys.stderr, flush=True)
            _isolation_state = False
            return None

        isolation_mode.warn_once(reason)

        if resolved != isolation_mode.FORK:
            _isolation_state = False
            return None

        from utk_curio.sandbox.isolation import lifecycle, runner

        # Filesystem permissions are handled at startup, in sandbox/server.py,
        # not here. A misconfiguration has to fail the *boot*: raising from a
        # request handler would surface as a 500, and /exec promises to report
        # every failure as stderr at 200.
        config = runner.IsolationConfig.from_environment()
        try:
            lifecycle.ensure_running(
                config,
                exec_user=os.environ.get('CURIO_EXEC_USER') or None,
                require_seccomp=isolation_mode.mode_from_environment()[1],
            )
        except Exception as exc:  # noqa: BLE001 - degrade rather than 500
            print(
                f"[isolation] could not start the execution zygote, falling back "
                f"to in-process execution: {exc}",
                file=sys.stderr, flush=True,
            )
            metrics.record_error(
                summary="Could not start the execution zygote",
                detail=f"{exc}\n\nNode execution fell back to the in-process path.",
            )
            _isolation_state = False
            return None

        import atexit
        atexit.register(lifecycle.shutdown)

        print(
            f"[isolation] node execution is isolated "
            f"(memory={config.limits['memory_mb']}MB, "
            f"timeout={config.wall_timeout}s, "
            f"parallelism={config.parallelism})",
            file=sys.stderr, flush=True,
        )
        _isolation_state = (runner.execute_isolated, config)
        return _isolation_state


@app.route('/artifact-meta', methods=['GET'])
@require_sandbox_token
@holds_duckdb
def artifact_meta():
    """The stored row for one artifact, without opening the database file.

    This exists so the backend never opens curio_data.duckdb itself. DuckDB
    allows a single cross-process writer, so every backend read-only open had
    to be fitted around the sandbox closing its write handle between runs --
    which is why the handle was released after every execution, and why an
    auto-install that happened to collide with a node run silently read
    nothing and moved on. With the read served here, the sandbox keeps one
    connection for its lifetime and nothing contends for the file.

    Returns the same columns the backend used to SELECT for itself; a missing
    artifact is a 404 rather than an error, because "not there" is an ordinary
    answer for a caller resolving an id it merely hopes is an artifact.
    """
    art_id = request.args.get('fileName')
    if not art_id:
        abort(400, "fileName is required")

    from utk_curio.sandbox.util.db import get_read_connection

    con = get_read_connection()
    row = con.execute(
        "SELECT kind, value_int, value_float, value_str, value_json "
        "FROM artifacts WHERE id = ?",
        [art_id],
    ).fetchone()
    if row is None:
        return jsonify({'error': 'not found', 'fileName': art_id}), 404

    kind, value_int, value_float, value_str, value_json = row
    return jsonify({
        'kind': kind,
        'value_int': value_int,
        'value_float': value_float,
        'value_str': value_str,
        'value_json': value_json,
    })


@app.route('/exec', methods=['POST'])
@require_sandbox_token
@holds_duckdb
# @cache.cached(make_cache_key=make_key)
def exec():
    import time
    import sys
    t0 = time.perf_counter()

    if request.json.get('code') is None:
        abort(400, "Code was not included in the post request")

    code       = request.json['code']
    file_path  = request.json['file_path']
    node_type  = request.json['nodeType']
    data_type  = request.json['dataType']
    session_id = request.json.get('session_id') or None
    save_dataset = request.json.get('save_dataset', True)
    if isinstance(save_dataset, str):
        save_dataset = save_dataset.strip().lower() not in ('0', 'false', 'no', 'off')
    # {datasetId: absolutePath} resolved by the backend for the code's
    # curio_dataset_path("<id>") calls. Defensive re-shaping mirrors the
    # backend's MAX_EXEC_DATASET_IDS cap.
    dataset_paths = request.json.get('dataset_paths') or {}
    # Isolated mode gives each user their own work directory, so a node's
    # relative reads and writes land somewhere that persists and belongs to
    # them. The backend is the only component that knows who is logged in; it
    # sends the storage key, not a name, and only the isolated path uses it.
    user_key = request.json.get('user_key') or None
    if not isinstance(dataset_paths, dict):
        dataset_paths = {}
    dataset_paths = {
        str(key): str(value)
        for key, value in list(dataset_paths.items())[:32]
        if value
    }
    launch_dir = os.environ.get('CURIO_LAUNCH_CWD', os.getcwd())

    print(f"[sandbox /exec] received  node={node_type}", file=sys.stderr, flush=True)
    isolated = _isolated_runner()
    metrics.record_dispatch(isolated is not None)
    if isolated is not None:
        run, config = isolated
        # launch_dir is passed to both paths in the same position: it is the
        # child's working directory, so node code addressing a file relatively
        # finds it where the in-process path would.
        result = run(
            code, str(file_path), str(node_type), str(data_type), launch_dir,
            session_id=session_id, save_dataset=bool(save_dataset),
            dataset_paths=dataset_paths, user_key=user_key, config=config,
        )
    else:
        result = execute_code(
            code, str(file_path), str(node_type), str(data_type), launch_dir,
            session_id=session_id, save_dataset=bool(save_dataset),
            dataset_paths=dataset_paths,
        )

    print(f"[sandbox /exec] finished  total={time.perf_counter()-t0:.3f}s  node={node_type}", file=sys.stderr, flush=True)
    return jsonify(result)

@app.route('/execJs', methods=['POST'])
@require_sandbox_token
@holds_duckdb
def exec_js():
    import time
    import sys
    t0 = time.perf_counter()

    if request.json.get('code') is None:
        abort(400, "Code was not included in the post request")

    code       = request.json['code']
    file_path  = request.json['file_path']
    node_type  = request.json['nodeType']
    data_type  = request.json['dataType']
    session_id = request.json.get('session_id') or None
    save_dataset = request.json.get('save_dataset', True)
    if isinstance(save_dataset, str):
        save_dataset = save_dataset.strip().lower() not in ('0', 'false', 'no', 'off')
    launch_dir = os.environ.get('CURIO_LAUNCH_CWD', os.getcwd())

    print(f"[sandbox /execJs] received  node={node_type}", file=sys.stderr, flush=True)
    # JS has no isolated path at all, so this is always an in-process dispatch.
    metrics.record_dispatch(False)
    result = execute_js_code(
        code, str(file_path), str(node_type), str(data_type), launch_dir,
        session_id=session_id, save_dataset=bool(save_dataset),
    )

    print(f"[sandbox /execJs] finished  total={time.perf_counter()-t0:.3f}s  node={node_type}", file=sys.stderr, flush=True)
    return jsonify(result)

