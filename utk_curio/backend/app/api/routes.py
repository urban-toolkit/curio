from pathlib import PurePosixPath

from flask import request, abort, jsonify, g, Response, current_app

import requests
import json

from utk_curio.backend.app.execution import node_exec
from utk_curio.backend.app.execution.sandbox_client import (
    SandboxTransportError,
    sandbox_request,
)

ARROW_IPC_MIME = "application/vnd.apache.arrow.stream"

# The header a client sends to say it can decode WKB geometry. The sandbox
# gates geodataframes on it (sandbox/app/api.py); this process only has to
# pass it through, and must, or the gate never opens.
GEOMETRY_ACCEPT_HEADER = "X-Curio-Accept-Geometry"


# Per-route timeouts for backend -> sandbox bridge calls (in seconds). A node
# run's own deadline is node_exec.SANDBOX_EXEC_TIMEOUT.
SANDBOX_GET_TIMEOUT      = 300  # /get (full artifact JSON)
SANDBOX_PREVIEW_TIMEOUT  = 60   # /get-preview (always small by definition)
SANDBOX_RASTER_TIMEOUT   = 120  # /raster (a GeoTIFF an Autark map can hold)
# /version is a cached constant on the sandbox side, and the version badge is
# waiting on it, so it gets a short deadline rather than a generous one.
SANDBOX_VERSION_TIMEOUT  = 5


def _sandbox_call(method: str, path: str, *, label: str, timeout: int, **kwargs):
    """:func:`sandbox_request` for a route: a transport failure becomes the
    Flask ``(jsonify(...), status)`` tuple the browser reads, instead of an
    exception.

    Returns either:
      - `requests.Response` on success
      - `(flask_response, status_code)` tuple on transport-level failure
    """
    try:
        return sandbox_request(method, path, label=label, timeout=timeout, **kwargs)
    except SandboxTransportError as e:
        return jsonify(e.payload), e.status


#: Chunk size for relaying a sandbox reply to the browser.
RELAY_CHUNK_BYTES = 64 * 1024


def _relay_sandbox_reply(resp, *, label, file_name, t0, error_prefix=None):
    """Pass a sandbox ``/get`` reply to the browser as it arrives (#408).

    The backend only relays artifacts, so it has no reason to hold one. It used
    to: the JSON path parsed the whole body and encoded it again (a 17 MB
    GeoJSON body peaked at 120 MB of Python objects here), and the Arrow path
    read the whole stream before sending a byte. With every output of a run
    fetched at once, those copies sat on top of the sandbox's own.

    ``resp`` must come from a ``stream=True`` call. ``error_prefix`` set means a
    non-2xx reply becomes ``"<prefix>: <reason>"`` with a 500, which is what the
    JSON routes have always answered; unset, the sandbox's status and body pass
    through, which is what the Arrow client reads (415 means "ask for JSON").
    """
    if error_prefix is not None and not resp.ok:
        try:
            resp.raise_for_status()
            message = f'{error_prefix}: HTTP {resp.status_code}'
        except Exception as e:
            message = f'{error_prefix}: {str(e)}'
        finally:
            resp.close()
        return message, 500

    forwarded = {k: v for k, v in resp.headers.items() if k.startswith("X-Curio-")}

    def body():
        sent = 0
        try:
            for chunk in resp.iter_content(chunk_size=RELAY_CHUNK_BYTES):
                if chunk:
                    sent += len(chunk)
                    yield chunk
        finally:
            resp.close()
            print(f"[{label}] id={file_name} took={time.perf_counter()-t0:.4f}s "
                  f"bytes={sent}", flush=True)

    return Response(
        body(),
        status=resp.status_code,
        mimetype=resp.headers.get("Content-Type", "application/octet-stream"),
        headers=forwarded,
    )


from utk_curio.backend.app.users.dependencies import require_auth, get_current_token
import os
import time

# The Flask app
from utk_curio.backend.app.api import bp


@bp.route('/')
def root():
    abort(403)

@bp.route('/live')
def live():
    return 'Backend is live.'

@bp.route('/version')
def version():
    """Version, plus how node code is actually being executed.

    The isolation mode comes from the sandbox rather than from this process's
    own environment: the sandbox is where the requested mode is resolved
    against what the platform can actually do, so `CURIO_ISOLATION` here would
    report an intention, not a fact. Degrades to 'unknown' rather than failing
    -- the version badge must still render when the sandbox is slow or down.

    Both fields are passed through, because the resolved mode alone can
    overstate the boundary. The zygote is started lazily on the first node
    execution, and a spawn that fails degrades to in-process for the life of
    the sandbox process without changing what `isolation` reports;
    `isolation_active` is what the sandbox actually did. The badge needs both
    to avoid claiming a confinement that is not there.
    """
    from utk_curio import __version__

    isolation = 'unknown'
    isolation_active = 'unknown'
    try:
        response = sandbox_request(
            'get', '/version',
            label='/version', timeout=SANDBOX_VERSION_TIMEOUT,
        )
        if response.status_code == 200:
            payload = response.json()
            isolation = payload.get('isolation', 'unknown')
            # An older sandbox does not send this. 'unknown' rather than 'off':
            # the badge only downgrades on an explicit 'off', so a missing
            # field must not be read as evidence of a failed zygote.
            isolation_active = payload.get('isolation_active', 'unknown')
    except (SandboxTransportError, requests.RequestException, ValueError):
        pass

    return jsonify({
        'version': __version__,
        'isolation': isolation,
        'isolation_active': isolation_active,
    })


#: The example data the shipped dataflows read: the Autark examples' ``.osm.pbf``
#: extracts, which their grammar fetches through ``/file/``, and the files their
#: Python nodes open by the same path (``sandbox/util/user_code.py``).
EXAMPLE_DATA = PurePosixPath('docs', 'examples', 'data')


@bp.route('/file/<path:filename>', methods=['GET'])
def serve_launch_cwd_file(filename: str):
    """Serve a file by its path *relative to CURIO_LAUNCH_CWD* so browser-side
    nodes (e.g. autk-grammar) can fetch binary assets (PBF, GeoTIFF, …) the
    same way Python sandbox nodes read them from disk - one shared root, one
    relative-path convention:
      Python node:   rasterio.open('my-data/file.tif')
      Grammar spec:  pbfFileUrl: 'my-data/file.pbf'

    ``.pbf`` is not a Data Catalog format, and every ``/api/datasets/*``
    route requires auth while this one does not.

    The frontend prepends ``BACKEND_URL`` + ``/file/`` to the relative path at
    run time (see resolveDataSourceUrls in autkGrammarBehavior.tsx).

    safe_join blocks path-traversal payloads from escaping CURIO_LAUNCH_CWD.

    The route is unauthenticated, and the launch directory also holds Curio's
    own state: the SQLite database (sessions and every stored token), the
    per-user stores under ``.curio/``, the dataset hub, and ``.env``. None of
    that is data a node reads by relative path, so :func:`_is_private_path`
    refuses it with the same 404 a missing file gets.

    Two folders are Curio's own, and are served from where Curio keeps them
    (``utk_curio/shipped.py``), whatever folder Curio was started from:
    ``vendor/duckdb-extensions/``, its copy of DuckDB's extensions, which the
    browser's duckdb worker asks for, and ``docs/examples/data/``, the
    example data the shipped dataflows read (:data:`EXAMPLE_DATA`).
    """
    from flask import send_from_directory
    from utk_curio import shipped
    from utk_curio.backend.app.common.safe_paths import PathTraversalError, safe_join
    from utk_curio.sandbox.util import node_runtime

    parts = [p for p in filename.split('/') if p]
    for folder in (node_runtime.DUCKDB_EXTENSIONS, EXAMPLE_DATA):
        if tuple(parts[:len(folder.parts)]) == folder.parts:
            rest = parts[len(folder.parts):]
            if any(part.startswith('.') for part in rest):
                abort(404)
            return send_from_directory(shipped.path(folder, node_runtime.REPO_ROOT), '/'.join(rest))

    launch_cwd = os.environ.get('CURIO_LAUNCH_CWD', os.getcwd())
    # ``filename`` is a multi-segment relative path (e.g. my-data/x.pbf).
    # Use validate=False (like /get) so the containment guard alone runs: real data
    # filenames routinely contain spaces or leading '_'/'-' that the per-segment
    # charset would reject, and is_within already prevents escaping CURIO_LAUNCH_CWD.
    try:
        resolved = safe_join(launch_cwd, *parts, validate=False)
    except PathTraversalError:
        abort(403)
    if _is_private_path(parts, resolved):
        abort(404)
    return send_from_directory(launch_cwd, filename)


def _private_roots():
    """Directories under the launch directory that ``/file/`` never serves."""
    from pathlib import Path

    from utk_curio.backend.app.common.user_storage import curio_root
    from utk_curio.backend.app.datasets.infrastructure.storage import catalog_root

    roots = [Path(current_app.instance_path), curio_root(), catalog_root()]
    for env in ("CURIO_STATE_DIR", "CURIO_SHARED_DATA"):
        value = os.environ.get(env)
        if value:
            roots.append(Path(value))
    return roots


def _database_files():
    """The SQLite database file and its journal siblings, when SQLite is used."""
    from pathlib import Path

    from utk_curio.backend.extensions import db

    try:
        url = db.engine.url
    except Exception:
        return []
    if not str(url.drivername).startswith("sqlite") or not url.database:
        return []
    base = Path(url.database)
    return [base.with_name(base.name + suffix) for suffix in ("", "-wal", "-shm", "-journal")]


def _is_private_path(parts, resolved) -> bool:
    """True when *resolved* is Curio's own state rather than user data.

    Hidden segments (``.env``, ``.curio``, ``.git``) are refused outright;
    everything else is refused when it sits inside one of Curio's stores.
    """
    from pathlib import Path

    from utk_curio.backend.app.common.safe_paths import is_within

    if any(part.startswith('.') for part in parts):
        return True
    target = Path(resolved)
    for root in _private_roots():
        if root.exists() and is_within(target, root):
            return True
    try:
        real = target.resolve()
    except OSError:
        return True
    return any(real == f.resolve() for f in _database_files() if f.exists())

@bp.route('/get', methods=['GET'])
@require_auth
def get_file():
    file_name = request.args.get('fileName')

    if not file_name:
        return 'No artifact id specified', 400

    wants_arrow = request.accept_mimetypes.best == ARROW_IPC_MIME

    session_id = get_current_token()
    t0 = time.perf_counter()
    sandbox_kwargs = {
        'params': {"fileName": file_name, "sessionId": session_id},
    }
    if wants_arrow:
        sandbox_kwargs['headers'] = {"Accept": ARROW_IPC_MIME}
        # Forward the client's WKB opt-in. Without this the sandbox refuses
        # every geodataframe on the Arrow path and the caller falls back to
        # JSON -- which looks like success, because the data still arrives,
        # while the format that made it worth asking for is never used. The
        # stress harness is the only caller that treats that 415 as an error,
        # which is how it was caught.
        accept_geometry = request.headers.get(GEOMETRY_ACCEPT_HEADER)
        if accept_geometry:
            sandbox_kwargs['headers'][GEOMETRY_ACCEPT_HEADER] = accept_geometry
    resp = _sandbox_call(
        'get', '/get',
        label='/get', timeout=SANDBOX_GET_TIMEOUT, stream=True,
        **sandbox_kwargs,
    )
    if isinstance(resp, tuple):  # transport-level failure (timeout / unreachable)
        return resp

    if wants_arrow:
        return _relay_sandbox_reply(resp, label='/get arrow', file_name=file_name, t0=t0)
    return _relay_sandbox_reply(resp, label='/get', file_name=file_name, t0=t0,
                                error_prefix='Error loading artifact')


@bp.route('/get-preview', methods=['GET'])
@require_auth
def get_file_preview():
    """
    Get first N rows + metadata for DataPool display optimization.
    Similar to /get but truncates the DataFrame/GeoDataFrame before
    converting to JSON, so large artifacts stay cheap to preview.
    """
    file_name = request.args.get('fileName')

    if not file_name:
        return 'No artifact id specified', 400

    max_rows = 100
    session_id = get_current_token()
    t0 = time.perf_counter()
    resp = _sandbox_call(
        'get', '/get',
        label='/get-preview', timeout=SANDBOX_PREVIEW_TIMEOUT, stream=True,
        params={"fileName": file_name, "maxRows": max_rows, "sessionId": session_id},
    )
    if isinstance(resp, tuple):
        return resp
    return _relay_sandbox_reply(resp, label='/get-preview', file_name=file_name, t0=t0,
                                error_prefix='Error loading preview')


@bp.route('/raster', methods=['GET'])
@require_auth
def get_raster():
    """A raster artifact as GeoTIFF bytes, for an Autark node to load.

    Asked by artifact id, never by path, and read by the sandbox under the
    caller's session as ``/get`` is. The description rides in the
    ``X-Curio-Raster`` header; a raster larger than ``maxCells`` or ``maxSide``
    is a 413 with its size. Statuses and bodies pass through as the sandbox
    gives them, so the node can say why a raster was not drawn.
    """
    file_name = request.args.get('fileName')

    if not file_name:
        return 'No artifact id specified', 400

    params = {"fileName": file_name, "sessionId": get_current_token()}
    for key in ('part', 'maxCells', 'maxSide'):
        value = request.args.get(key)
        if value is not None:
            params[key] = value
    t0 = time.perf_counter()
    resp = _sandbox_call(
        'get', '/raster',
        label='/raster', timeout=SANDBOX_RASTER_TIMEOUT, stream=True,
        params=params,
    )
    if isinstance(resp, tuple):
        return resp
    return _relay_sandbox_reply(resp, label='/raster', file_name=file_name, t0=t0)


@bp.route('/processPythonCode', methods=['POST'])
@require_auth
def process_python_code():
    run = node_exec.NodeRun.from_request_json(request.json)
    try:
        return node_exec.execute_python_node(g.user, get_current_token(), run)
    except SandboxTransportError as e:
        return jsonify(e.payload), e.status


@bp.route('/nodeRuntime', methods=['POST'])
@require_auth
def report_node_runtime():
    """A node reports its own execution outcome from the BROWSER (memo dev/135).

    ``DEC-052``'s journal had three writers and all three were the sandbox, so a
    Vega-Lite chart, an AUTK map, a Data Pool, a Simple View, a
    Spatial Join and a Data Export — every kind that runs in the client or
    through its own service — left no trace, and every agent reading the journal
    was told ``never-executed`` about a node the user had just watched fail.

    Body: ``{dataflowId, nodeId, status, message?, outputType?, durationMs?,
    code?}``. Deliberately narrow, because this is client-supplied data written
    into a store agents read:

    - the caller's own storage key is used, so a report can only ever touch
      that user's own project directory, and the project must already exist
      (a bogus id is a no-op, never a new directory);
    - ``status`` is an allowlist and ``message`` is bounded on arrival;
    - **no artifact path is accepted** — a client cannot mint one, so nothing
      downstream can mistake a reported record for a stored artifact;
    - the response is 204 whether or not the write landed: a render must never
      fail over its journal (``DEC-052``'s own rule).
    """
    from utk_curio.backend.app.execution import runtime_journal
    from utk_curio.backend.app.projects import storage as projects_storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    body = request.get_json(silent=True) or {}
    node_id = body.get('nodeId')
    dataflow_id = body.get('dataflowId')
    status = body.get('status')
    user = getattr(g, 'user', None)
    if not isinstance(node_id, str) or not node_id.strip():
        return jsonify({'error': "'nodeId' is required"}), 400
    if not isinstance(dataflow_id, str) or not dataflow_id.strip():
        return jsonify({'error': "'dataflowId' is required"}), 400
    if status not in runtime_journal.STATUSES:
        return jsonify({
            'error': f"'status' must be one of {', '.join(runtime_journal.STATUSES)}",
        }), 400
    if user is None:
        return jsonify({'error': 'authentication required'}), 401
    user_key = _user_dir_key(user)
    try:
        exists = projects_storage.project_dir(user_key, dataflow_id).is_dir()
    except Exception:
        exists = False
    if not exists:
        # An unsaved canvas or an id this user does not own: nothing to journal,
        # and never a directory created on a client's word.
        return '', 204
    try:
        duration = float(body.get('durationMs') or 0)
    except (TypeError, ValueError):
        duration = 0.0
    runtime_journal.record_browser_execution(
        user_key, dataflow_id, node_id.strip(),
        status=status,
        message=str(body.get('message') or '')[:runtime_journal.BROWSER_MESSAGE_CHARS],
        output_type=str(body.get('outputType') or '')[:60],
        duration_ms=max(duration, 0.0),
        code=str(body.get('code') or ''),
        # dev/136: an empty render is not the same problem as a render that
        # threw, and the harness must not have to match prose to tell them
        # apart. Bounded and free-form: an unknown kind is just a label.
        kind=str(body.get('kind') or '')[:40],
    )
    return '', 204


@bp.route('/nodeRuntime', methods=['GET'])
@require_auth
def read_node_runtime():
    """What this node's last run and last render did (memo dev/138).

    The same records the agents read (``DEC-052``'s journal, split per origin
    by dev/137), so the reason a user sees IN THE NODE and the reason an agent
    is handed cannot differ. Query: ``?dataflowId=…&nodeId=…``.

    Read-only, the caller's own storage key, and an empty answer (never a 404)
    when the node has no record: "nothing recorded" is a normal state, and the
    node body must not render an error because of it.
    """
    from utk_curio.backend.app.execution import runtime_journal
    from utk_curio.backend.app.projects.services import _user_dir_key

    node_id = (request.args.get('nodeId') or '').strip()
    dataflow_id = (request.args.get('dataflowId') or '').strip()
    user = getattr(g, 'user', None)
    if not node_id or not dataflow_id:
        return jsonify({'error': "'dataflowId' and 'nodeId' are required"}), 400
    if user is None:
        return jsonify({'error': 'authentication required'}), 401
    user_key = _user_dir_key(user)
    return jsonify({
        'nodeId': node_id,
        'run': runtime_journal.read_record(user_key, dataflow_id, node_id),
        'render': runtime_journal.read_render_record(user_key, dataflow_id, node_id),
    }), 200


@bp.route('/processJavaScriptCode', methods=['POST'])
@require_auth
def process_javascript_code():
    run = node_exec.NodeRun.from_request_json(request.json)
    try:
        return node_exec.execute_js_node(g.user, get_current_token(), run)
    except SandboxTransportError as e:
        return jsonify(e.payload), e.status


@bp.route("/starters", methods=["GET"])
def get_starters():
    """Return per-template starter source bodies from every installed package.

    Starters are sourced from each installed package's optional per-template
    ``source`` file and keyed on the canonical package id
    ``<packageId>/<templateId>@<major>``. The pre-installed ``curio.builtin@1``
    package ships no sources, so dragging a built-in node onto the canvas
    yields an empty editor; third-party packages may ship a starter per template.
    """
    from utk_curio.backend.app.packages.application.starters import generate_package_starters
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.dependencies import get_current_user

    starters: list[dict] = []
    user = get_current_user()
    if user is not None:
        try:
            starters = generate_package_starters(_user_dir_key(user))
        except Exception:  # noqa: BLE001 - never fail /starters over a bad package
            current_app.logger.exception("Package-starter loader failed; returning empty list")
    return jsonify(starters)

def get_loaded_files_metadata(folder_path):
    # ``pandas`` + ``geopandas`` belong to the ``curio.builtin@1`` package's
    # ``manifest.dependencies.python`` (installed via the launcher walker),
    # not Curio's framework requirements. Importing them lazily here keeps
    # the backend module load free of data-lib deps so a stripped framework
    # install still boots.
    import pandas as pd

    metadata = ""

    for file in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file)
        if file.endswith(".csv"):
            df = pd.read_csv(file_path)
            columns = [f"{col} ({df[col].dtype})" for col in df.columns]
            geometry_type = "None"
        elif file.endswith(".json") or file.endswith(".geojson"):
            try:
                import geopandas as gpd
                gdf = gpd.read_file(file_path, parse_dates=False)
                columns = [f"{col} ({gdf[col].dtype})" for col in gdf.columns]
                if "geometry" in gdf.columns:
                    geometry_type = gdf.geom_type.unique().tolist()
                else:
                    geometry_type = "None"
            except Exception:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        columns = list(data[0].keys()) if isinstance(data, list) and data else []
                        geometry_type = "None"
                except Exception:
                    columns = []
                    geometry_type = "Unreadable JSON"
        else:
            continue

        metadata += f"File name: {file}\nColumns: {', '.join(columns)}\nGeometry type: {geometry_type}\n\n"

    return metadata

@bp.route('/spatial_join', methods=['POST'])
def spatial_join():
    """Tag each input point with the polygon it falls in (point-in-polygon).

    Backs the Spatial Join node in curio.builtin@1. Accepts and returns
    plain GeoJSON FeatureCollections so the node sits naturally between any
    pair of nodes that emit / consume the GEODATAFRAME type.

    Request body:
        {
          "points":        FeatureCollection (Point features),
          "polygons":      FeatureCollection (Polygon/MultiPolygon features),
          "name_property": optional, defaults to "name". Which column on
                           each polygon to use as the tag (e.g. "pri_neigh"
                           for Chicago neighborhoods, "BoroName" for NYC).
          "output":        optional, "points" (default) or "polygons".
        }

    Response:
        {
          "type": "FeatureCollection",
          "features": [...]   # output "points" (default): the input points plus
                              # the polygon's tag under the polygon column's own
                              # name, a `<tag>_point_count` and the
                              # `<tag>_dominant_*` roll-ups when the points carry
                              # a dominant class. Output "polygons": the input
                              # polygons, each with `point_count` (and the
                              # dominant_* roll-ups when present).
          "metadata": { "aggregates": [...],   # per-polygon roll-up
                        "warnings": [...] }     # only when non-empty (#262)
        }

    Returns 503 if the shapely extras aren't installed (geopandas is already
    a Curio base dep, but we lazy-import shapely so the failure mode is
    explicit).
    """
    body = request.get_json(silent=True) or {}
    points_fc = body.get("points")
    polygons_fc = body.get("polygons")
    name_property = body.get("name_property") or "name"

    if not isinstance(points_fc, dict) or not isinstance(polygons_fc, dict):
        return jsonify({
            "error": "body must be { points: FeatureCollection, polygons: FeatureCollection, name_property? }",
        }), 400

    # Extract per-point dicts from the points FeatureCollection. Surface
    # `latitude` / `longitude` from properties OR from the geometry itself.
    point_dicts = []
    for f in (points_fc.get("features") or []):
        props = dict(f.get("properties") or {})
        lat = props.get("latitude")
        lon = props.get("longitude")
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if (lat is None or lon is None) and isinstance(coords, list) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
        props["latitude"] = lat
        props["longitude"] = lon
        point_dicts.append(props)

    warnings: list = []
    try:
        from utk_curio.backend.app.common.spatial import (
            enrich_points_with_polygons,
            polygons_with_counts,
        )
        enriched, aggregates, tag_column = enrich_points_with_polygons(
            points=point_dicts,
            polygon_fc=polygons_fc,
            name_property=name_property,
            warnings=warnings,
        )
    except ImportError as e:
        return jsonify({
            "error": "spatial extras not installed (shapely required)",
            "hint": "pip install shapely",
            "detail": str(e),
        }), 503
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    output = body.get("output") or "points"
    if output not in ("points", "polygons"):
        return jsonify({"error": "output must be one of points, polygons"}), 400
    if output == "polygons":
        out_features = polygons_with_counts(polygons_fc, aggregates, tag_column, name_property)
        metadata = {"name": "spatial_join_result", "aggregates": aggregates,
                    "tag_column": tag_column, "output": output}
        if warnings:
            metadata["warnings"] = warnings
        return jsonify({"type": "FeatureCollection", "features": out_features, "metadata": metadata})

    # Re-pack enriched points as Features so downstream consumers see the
    # same shape they sent in.
    out_features = []
    for p in enriched:
        lat = p.get("latitude")
        lon = p.get("longitude")
        geometry = (
            {"type": "Point", "coordinates": [lon, lat]}
            if lat is not None and lon is not None
            else None
        )
        out_features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": p,
        })

    metadata = {"name": "spatial_join_result", "aggregates": aggregates,
                "tag_column": tag_column, "output": output}
    if warnings:
        metadata["warnings"] = warnings
    return jsonify({
        "type": "FeatureCollection",
        "features": out_features,
        "metadata": metadata,
    })
