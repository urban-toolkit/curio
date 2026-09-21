from flask import request, abort, jsonify, Response
import json
import sys
import geopandas as gpd
import pandas as pd
from utk_curio.sandbox.app import app, cache
from utk_curio.sandbox.app.auth import require_sandbox_token
from utk_curio.sandbox.app.utils.cache import make_key
import os
import mmap

from shapely import wkt

from utk_curio.sandbox.app.worker import _worker_init, execute_code, execute_js_code, chdir_locked
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

@app.route('/get', methods=['GET'])
@require_sandbox_token
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

    # Raster artifacts re-open via rasterio.open(relative_path); match
    # /exec's cwd handling so the path resolves against launch_dir.
    # chdir_locked serializes against execute_code() so a concurrent /exec
    # can't restore cwd out from under us (or vice versa).
    launch_dir = os.environ.get('CURIO_LAUNCH_CWD')
    max_rows = int(max_rows_param) if max_rows_param is not None else None
    try:
        with chdir_locked(launch_dir):
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


@app.route('/exec', methods=['POST'])
@require_sandbox_token
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
    result = execute_js_code(
        code, str(file_path), str(node_type), str(data_type), launch_dir,
        session_id=session_id, save_dataset=bool(save_dataset),
    )

    print(f"[sandbox /execJs] finished  total={time.perf_counter()-t0:.3f}s  node={node_type}", file=sys.stderr, flush=True)
    return jsonify(result)

