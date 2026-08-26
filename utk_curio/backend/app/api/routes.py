from flask import request, abort, jsonify, g, Response, current_app
import re
import requests
import json

ARROW_IPC_MIME = "application/vnd.apache.arrow.stream"

_sandbox_session = requests.Session()


# Per-route timeouts for backend -> sandbox bridge calls (in seconds).
# These were 120 / 60 historically; bumped here so legitimate long-running
# nodes (large CSV loads, heavy spatial ops, GPU compute) don't hit the
# request library's deadline before the sandbox has had a chance to respond.
SANDBOX_EXEC_TIMEOUT     = 600  # /processPythonCode and /processJavaScriptCode
SANDBOX_GET_TIMEOUT      = 300  # /get (full artifact JSON)
SANDBOX_PREVIEW_TIMEOUT  = 60   # /get-preview (always small by definition)
# /version is a cached constant on the sandbox side, and the version badge is
# waiting on it, so it gets a short deadline rather than a generous one.
SANDBOX_VERSION_TIMEOUT  = 5


SANDBOX_TOKEN_HEADER = "X-Curio-Sandbox-Token"


def _sandbox_headers(existing):
    """Merge the shared secret into a caller's headers without clobbering them.

    The sandbox executes arbitrary code, so every guarded route requires this
    header (see utk_curio/sandbox/app/auth.py). The token is minted per launch
    by main.py::set_environment_variables and inherited by both processes.
    Absent (a bare `python -m backend.server`), we send nothing and the sandbox
    runs in its unauthenticated local-dev mode.
    """
    token = os.getenv("CURIO_SANDBOX_TOKEN", "").strip()
    if not token:
        return existing
    headers = dict(existing or {})
    headers[SANDBOX_TOKEN_HEADER] = token
    return headers


def _sandbox_call(method: str, path: str, *, label: str, timeout: int, **kwargs):
    """Call the sandbox over `_sandbox_session` with consistent error handling.

    Catches `requests.Timeout` and `requests.ConnectionError` and returns a
    Flask `(jsonify(...), status)` tuple with a clear error message instead
    of letting the exception escape (which would otherwise surface to the
    browser as an opaque 'NetworkError when attempting to fetch resource').

    Also attaches the sandbox shared secret, and translates the sandbox's 401
    into a clear error rather than letting callers hit it as an unparseable
    body (`/get` would report it as 'Error loading artifact', `/exec` as
    'sandbox returned non-JSON' plus a 500).

    On success returns the `requests.Response` object directly so callers can
    parse the JSON / forward it as before.

    Returns either:
      - `requests.Response` on success
      - `(flask_response, status_code)` tuple on transport-level failure
    """
    url = api_address + ":" + str(api_port) + path
    fn = getattr(_sandbox_session, method)
    kwargs['headers'] = _sandbox_headers(kwargs.get('headers'))
    try:
        response = fn(url, timeout=timeout, **kwargs)
    except requests.Timeout as e:
        print(f"[backend {label}] sandbox call timed out after {timeout}s: {e}", flush=True)
        return jsonify({
            'error': 'sandbox_timeout',
            'message': (f'The sandbox did not respond within {timeout}s on {path}. '
                        'The node is likely still running - check the sandbox log. '
                        'For large data loads, consider trimming columns or rows '
                        'before returning from the node.'),
            'path': path,
            'timeout_seconds': timeout,
        }), 504
    except requests.ConnectionError as e:
        print(f"[backend {label}] sandbox connection error on {path}: {e}", flush=True)
        return jsonify({
            'error': 'sandbox_unreachable',
            'message': (f'Could not reach the sandbox on {path}. '
                        'Check that the sandbox process is running '
                        f'({api_address}:{api_port}).'),
            'path': path,
        }), 502

    if response.status_code == 401:
        print(f"[backend {label}] sandbox rejected the shared secret on {path}", flush=True)
        return jsonify({
            'error': 'sandbox_unauthorized',
            'message': (f'The sandbox rejected the backend on {path}. The two '
                        'processes disagree about CURIO_SANDBOX_TOKEN - this '
                        'usually means one of them was started outside '
                        "'curio start' or was restarted without the other."),
            'path': path,
        }), 502

    return response


from utk_curio.backend.app.users.dependencies import require_auth, get_current_token
import os
import time
from utk_curio.backend.config import (
    CURIO_DEFAULT_SAVE_NODE_OUTPUT,
    GUEST_LLM_API_TYPE,
)
from utk_curio.backend.app.agents.providers import ProviderConfig, run_chat_completion


def _resolve_llm_config():
    """Legacy tuple shim over the agents-owned resolver (``ADR-AG-012`` bridge).

    Resolution now lives in ``app/agents/provider_config.py`` (memo ``dev/22``);
    the legacy ``/llm/*`` handlers keep their exact contract — including the
    400 for guests without a deployed key — by reading through it.
    """
    from utk_curio.backend.app.agents.provider_config import (
        ProviderConfigError,
        resolve_provider_config,
    )

    try:
        cfg = resolve_provider_config(g.user)
    except ProviderConfigError as exc:
        abort(400, description=str(exc))
    return cfg.api_key, cfg.api_type, cfg.base_url, cfg.model


def _call_llm(api_key: str, api_type: str, base_url: str, model: str, messages: list) -> str:
    """Dispatch an LLM chat completion via the agents provider port.

    Provider dispatch (and the raw provider SDKs) lives in
    ``app/agents/providers.py`` so LLM behavior stays out of the route layer;
    this thin wrapper preserves the existing call signature.
    """
    return run_chat_completion(
        ProviderConfig(api_key=api_key, api_type=api_type, base_url=base_url, model=model),
        messages,
    )

# The Flask app
from utk_curio.backend.app.api import bp


# Sandbox address
api_address='http://'+os.getenv('FLASK_SANDBOX_HOST', '127.0.0.1')
api_port=int(os.getenv('FLASK_SANDBOX_PORT', 2000))

conversation = {}

tokens_left = 200000 # Tokens allowed per minute
last_refresh = time.time() # Last time that 60 minutes elapsed


def _parse_input_ref(req_input: dict | None) -> dict:
    """Normalize the input reference field from execution requests."""
    result = {'path': '', 'dataType': ''}
    if not req_input:
        return result
    if req_input.get('dataType') == 'outputs' and 'data' in req_input:
        result['path'] = req_input['data']
        result['dataType'] = 'outputs'
    elif 'filename' in req_input:
        result['path'] = req_input['filename']
        result['dataType'] = req_input['dataType'] if req_input['dataType'] != 'outputs' else 'file'
    elif 'path' in req_input:
        result['path'] = req_input['path']
        result['dataType'] = req_input['dataType'] if req_input['dataType'] != 'outputs' else 'file'
    return result

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
    """
    from utk_curio import __version__

    isolation = 'unknown'
    try:
        response = _sandbox_session.get(
            api_address + ":" + str(api_port) + '/version',
            timeout=SANDBOX_VERSION_TIMEOUT,
        )
        if response.status_code == 200:
            isolation = response.json().get('isolation', 'unknown')
    except (requests.RequestException, ValueError):
        pass

    return jsonify({'version': __version__, 'isolation': isolation})

@bp.route('/file/<path:filename>', methods=['GET'])
def serve_launch_cwd_file(filename: str):
    """Serve a file by its path *relative to CURIO_LAUNCH_CWD* so browser-side
    nodes (e.g. autk-grammar) can fetch binary assets (PBF, GeoTIFF, …) the
    same way Python sandbox nodes read them from disk - one shared root, one
    relative-path convention:
      Python node:   rasterio.open('docs/examples/data/file.tif')
      Grammar spec:  pbfFileUrl: 'docs/examples/data/file.pbf'

    The frontend prepends ``BACKEND_URL`` + ``/file/`` to the relative path at
    run time (see resolveDataSourceUrls in autkGrammarBehavior.tsx).

    safe_join blocks path-traversal payloads from escaping CURIO_LAUNCH_CWD.
    """
    from flask import send_from_directory
    from utk_curio.backend.app.common.safe_paths import PathTraversalError, safe_join

    launch_cwd = os.environ.get('CURIO_LAUNCH_CWD', os.getcwd())
    # ``filename`` is a multi-segment relative path (e.g. docs/examples/data/x.pbf).
    # Use validate=False (like /get) so the containment guard alone runs: real data
    # filenames routinely contain spaces or leading '.'/'_'/'-' that the per-segment
    # charset would reject, and is_within already prevents escaping CURIO_LAUNCH_CWD.
    parts = [p for p in filename.split('/') if p]
    try:
        safe_join(launch_cwd, *parts, validate=False)
    except PathTraversalError:
        abort(403)
    return send_from_directory(launch_cwd, filename)

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
    resp = _sandbox_call(
        'get', '/get',
        label='/get', timeout=SANDBOX_GET_TIMEOUT,
        **sandbox_kwargs,
    )
    if isinstance(resp, tuple):  # transport-level failure (timeout / unreachable)
        return resp

    if wants_arrow:
        forwarded_headers = {
            k: v for k, v in resp.headers.items()
            if k.startswith("X-Curio-")
        }
        print(f"[/get] arrow id={file_name} took={time.perf_counter()-t0:.4f}s "
              f"bytes={len(resp.content)}", flush=True)
        return Response(
            resp.content,
            status=resp.status_code,
            mimetype=resp.headers.get("Content-Type", "application/octet-stream"),
            headers=forwarded_headers,
        )

    try:
        resp.raise_for_status()
        data = resp.json()
        print(f"[/get] id={file_name} took={time.perf_counter()-t0:.4f}s", flush=True)
        return jsonify(data), 200
    except Exception as e:
        return f'Error loading artifact: {str(e)}', 500


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
        label='/get-preview', timeout=SANDBOX_PREVIEW_TIMEOUT,
        params={"fileName": file_name, "maxRows": max_rows, "sessionId": session_id},
    )
    if isinstance(resp, tuple):
        return resp
    try:
        resp.raise_for_status()
        data = resp.json()
        print(f"[/get-preview] id={file_name} took={time.perf_counter()-t0:.4f}s", flush=True)
        return jsonify(data), 200
    except Exception as e:
        return f'Error loading preview: {str(e)}', 500


# Literal ``curio_dataset_path("<id>")`` calls in node code. The id charset must
# stay in sync with _SAFE_DATASET_ID_RE in datasets/domain/catalog_item.py (the
# backend snippet generator) and the frontend datasetLoaderSnippets.ts - the
# generators only ever emit ids this scan can find. Single or double quotes are
# accepted because users edit the generated code.
_DATASET_PATH_CALL_RE = re.compile(
    r"""curio_dataset_path\(\s*(["'])([A-Za-z0-9][A-Za-z0-9._@-]{0,199})\1\s*\)"""
)
# Bound the per-execution resolution work against pathological/generated code.
MAX_EXEC_DATASET_IDS = 32


def _resolve_exec_dataset_paths(code: str, dataflow_id: str | None) -> dict:
    """Resolve the dataset ids referenced by *code* to absolute file paths.

    Best-effort and fail-open: an empty mapping never blocks execution - the
    sandbox's injected ``curio_dataset_path`` raises a clear per-id error for
    anything missing. Only ids appearing as literal calls are found; a
    dynamically built id simply won't be in the mapping.
    """
    if "curio_dataset_path" not in code:
        return {}
    ids: list[str] = []
    for match in _DATASET_PATH_CALL_RE.finditer(code):
        dataset_id = match.group(2)
        if dataset_id not in ids:
            ids.append(dataset_id)
        if len(ids) >= MAX_EXEC_DATASET_IDS:
            break
    if not ids:
        return {}
    try:
        from utk_curio.backend.app.datasets.service import DatasetCatalogService

        service = DatasetCatalogService(getattr(g, "user", None))
        return service.resolve_execution_paths(ids, dataflow_id=dataflow_id)
    except Exception as e:  # noqa: BLE001 - resolution must never fail the execution
        print(f"[processPythonCode] dataset path resolution failed: {e}", flush=True)
        return {}


def _exec_user_key():
    """The current user's on-disk storage key, or None when there is no user.

    Matches the key ``auto_install_node_output`` files a node's output under,
    so a user's work directory and their computed datasets agree about who they
    belong to. Returns None rather than raising: an unauthenticated launch
    (``CURIO_NO_AUTH=1``) has no user, and the sandbox then falls back to the
    launch directory exactly as it did before.
    """
    try:
        from utk_curio.backend.app.projects.services import _user_dir_key

        user = getattr(g, "user", None)
        return _user_dir_key(user) if user is not None else None
    except Exception:  # noqa: BLE001 - a work directory is a convenience
        return None


@bp.route('/processPythonCode', methods=['POST'])
@require_auth
def process_python_code():
    import time as _time
    t0 = _time.perf_counter()

    code = request.json['code']
    nodeType = request.json['nodeType']
    node_id = request.json.get('nodeId') or None
    input = _parse_input_ref(request.json.get('input'))

    save_output_dataset = request.json.get(
        'saveOutputDataset', CURIO_DEFAULT_SAVE_NODE_OUTPUT,
    )
    if isinstance(save_output_dataset, str):
        save_output_dataset = save_output_dataset.strip().lower() not in ('0', 'false', 'no', 'off')

    session_id = get_current_token()
    dataset_paths = _resolve_exec_dataset_paths(
        code, request.json.get("dataflowId") or None,
    )
    # Under isolation the sandbox gives each user a persistent work directory,
    # so a node's relative reads and writes land somewhere that belongs to
    # them instead of the launch tree. The storage key, not a name, and only
    # this route knows it: the sandbox has no notion of who is logged in, and
    # the in-process path ignores it entirely.
    exec_user_key = _exec_user_key()
    t1 = _time.perf_counter()
    response = _sandbox_call(
        'post', '/exec',
        label='/processPythonCode', timeout=SANDBOX_EXEC_TIMEOUT,
        data=json.dumps({
            "code": code,
            "file_path": input['path'],
            "nodeType": nodeType,
            "dataType": input['dataType'],
            "session_id": session_id,
            "save_dataset": bool(save_output_dataset),
            "dataset_paths": dataset_paths,
            "user_key": exec_user_key,
        }),
        headers={"Content-Type": "application/json"},
    )
    if isinstance(response, tuple):
        return response
    t2 = _time.perf_counter()

    try:
        response_json = response.json()
    except Exception as e:
        print(f"[processPythonCode] sandbox /exec returned non-JSON: "
              f"status={response.status_code} "
              f"body={response.text[:500]!r}", flush=True)
        return {
            'stdout': '',
            'stderr': f'Sandbox error: {e}',
            'input': input,
            'output': {}
        }, 500

    stdout = response_json['stdout']
    stderr = response_json['stderr']
    output = response_json['output']

    t3 = _time.perf_counter()
    print(
        f"[backend /processPythonCode] parse={t1-t0:.3f}s"
        f"  sandbox_rtt={t2-t1:.3f}s"
        f"  json={t3-t2:.3f}s"
        f"  total={t3-t0:.3f}s"
        f"  node={nodeType}",
        flush=True,
    )

    # Auto-install into the user store (not the public Data Catalog).
    from utk_curio.backend.app.datasets.application.auto_install import auto_install_node_output

    installed_dataset = None
    dataset_diagnostic = None
    if save_output_dataset and isinstance(output, dict) and node_id:
        dataset_diagnostic = auto_install_node_output(
            user=getattr(g, "user", None),
            node_id=node_id,
            sandbox_output=output,
            dataflow_id=request.json.get("dataflowId") or None,
            node_name=request.json.get("nodeName") or None,
            node_type=nodeType,
        )
        if dataset_diagnostic.get("status") == "installed":
            installed_dataset = dataset_diagnostic.get("dataset")
            print(
                f"[processPythonCode] auto-installed dataset "
                f"{installed_dataset.get('id')} for node {node_id}",
                flush=True,
            )
        else:
            print(
                f"[processPythonCode] node {node_id} produced no computed dataset: "
                f"{dataset_diagnostic.get('status')} - {dataset_diagnostic.get('reason')}",
                flush=True,
            )

    _record_runtime_outcome(
        node_id=node_id,
        dataflow_id=request.json.get("dataflowId") or None,
        code=code, stdout=stdout, stderr=stderr, output=output,
        duration_ms=(_time.perf_counter() - t0) * 1000.0,
    )

    return {
        'stdout': stdout,
        'stderr': stderr,
        'input': input,
        'output': output,
        'installedDataset': installed_dataset,
        'datasetDiagnostic': dataset_diagnostic,
    }


def _record_runtime_outcome(*, node_id, dataflow_id, code, stdout, stderr, output, duration_ms):
    """Per-node runtime journal write (memo dev/67-2, DEC-052).

    Best-effort and observational: agents read this to answer "what ran, what
    failed, and why" — an execution response is never delayed or failed over
    it. Skipped when the run has no node/project identity (unsaved canvas)."""
    import time as _time

    from utk_curio.backend.app.execution import runtime_journal
    from utk_curio.backend.app.projects.services import _user_dir_key

    user = getattr(g, "user", None)
    if not node_id or not dataflow_id or user is None:
        return
    try:
        runtime_journal.record_execution(
            _user_dir_key(user), dataflow_id, node_id,
            code=code, stdout=stdout, stderr=stderr, output=output,
            started_at=_time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            duration_ms=duration_ms,
        )
    except Exception:
        pass


@bp.route('/processJavaScriptCode', methods=['POST'])
@require_auth
def process_javascript_code():
    import time as _time
    t0 = _time.perf_counter()

    code = request.json['code']
    nodeType = request.json['nodeType']
    node_id = request.json.get('nodeId') or None
    input = _parse_input_ref(request.json.get('input'))

    save_output_dataset = request.json.get(
        'saveOutputDataset', CURIO_DEFAULT_SAVE_NODE_OUTPUT,
    )
    if isinstance(save_output_dataset, str):
        save_output_dataset = save_output_dataset.strip().lower() not in ('0', 'false', 'no', 'off')

    session_id = get_current_token()
    t1 = _time.perf_counter()
    response = _sandbox_call(
        'post', '/execJs',
        label='/processJavaScriptCode', timeout=SANDBOX_EXEC_TIMEOUT,
        data=json.dumps({
            "code": code,
            "file_path": input['path'],
            "nodeType": nodeType,
            "dataType": input['dataType'],
            "session_id": session_id,
            "save_dataset": bool(save_output_dataset),
        }),
        headers={"Content-Type": "application/json"},
    )
    if isinstance(response, tuple):
        return response
    t2 = _time.perf_counter()

    try:
        response_json = response.json()
    except Exception as e:
        print(f"[processJavaScriptCode] sandbox /execJs returned non-JSON: "
              f"status={response.status_code} "
              f"body={response.text[:500]!r}", flush=True)
        return {
            'stdout': '',
            'stderr': f'Sandbox error: {e}',
            'input': input,
            'output': {}
        }, 500

    stdout = response_json['stdout']
    stderr = response_json['stderr']
    output = response_json['output']

    t3 = _time.perf_counter()
    print(
        f"[backend /processJavaScriptCode] parse={t1-t0:.3f}s"
        f"  sandbox_rtt={t2-t1:.3f}s"
        f"  json={t3-t2:.3f}s"
        f"  total={t3-t0:.3f}s"
        f"  node={nodeType}",
        flush=True,
    )

    from utk_curio.backend.app.datasets.application.auto_install import auto_install_node_output

    installed_dataset = None
    dataset_diagnostic = None
    if save_output_dataset and isinstance(output, dict) and node_id:
        dataset_diagnostic = auto_install_node_output(
            user=getattr(g, "user", None),
            node_id=node_id,
            sandbox_output=output,
            dataflow_id=request.json.get("dataflowId") or None,
            node_name=request.json.get("nodeName") or None,
            node_type=nodeType,
        )
        if dataset_diagnostic.get("status") == "installed":
            installed_dataset = dataset_diagnostic.get("dataset")
            print(
                f"[processJavaScriptCode] auto-installed dataset "
                f"{installed_dataset.get('id')} for node {node_id}",
                flush=True,
            )
        else:
            print(
                f"[processJavaScriptCode] node {node_id} produced no computed dataset: "
                f"{dataset_diagnostic.get('status')} - {dataset_diagnostic.get('reason')}",
                flush=True,
            )

    _record_runtime_outcome(
        node_id=node_id,
        dataflow_id=request.json.get("dataflowId") or None,
        code=code, stdout=stdout, stderr=stderr, output=output,
        duration_ms=(_time.perf_counter() - t0) * 1000.0,
    )

    return {
        'stdout': stdout,
        'stderr': stderr,
        'input': input,
        'output': output,
        'installedDataset': installed_dataset,
        'datasetDiagnostic': dataset_diagnostic,
    }


@bp.route("/starters", methods=["GET"])
def get_starters():
    """Return per-template starter source bodies from every installed package.

    Starters are sourced from each installed package's optional per-template
    ``source`` file and keyed on the canonical package id
    ``<packageId>/<templateId>@<major>``. The pre-installed ``curio.builtin@1``
    package ships no sources, so dragging a built-in node onto the canvas
    yields an empty editor; third-party packages may ship a starter per template.
    """
    from utk_curio.backend.app.packages import generate_packageage_starters  # local import → no cycle
    from utk_curio.backend.app.projects.services import _user_dir_key
    from utk_curio.backend.app.users.dependencies import get_current_user

    starters: list[dict] = []
    user = get_current_user()
    if user is not None:
        try:
            starters = generate_packageage_starters(_user_dir_key(user))
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

@bp.route('/llm/chat', methods=['POST'])
@require_auth
def llm_chat():
    global conversation

    data = request.get_json()

    preamble_file = data.get("preamble", None)
    prompt_file = data.get("prompt", None)
    text = data.get("text", None)
    chatId = data.get("chatId", None)

    past_conversation = []

    if chatId is not None and chatId in conversation:
        past_conversation = conversation[chatId]

    prompt_preamble_file = open("./llm-prompts/"+preamble_file+".txt")
    prompt_preamble = prompt_preamble_file.read()

    prompt_preamble += "In case you need. This is the list of files and metadata currently loaded into the system"

    metadata = get_loaded_files_metadata("./")

    prompt_preamble += "\n" + metadata

    prompt_file_obj = open("./llm-prompts/"+prompt_file+".txt")
    prompt_text = prompt_file_obj.read()

    if len(past_conversation) == 0:
        past_conversation.append({"role": "system", "content": prompt_preamble + "\n" + prompt_text})

    past_conversation.append({"role": "user", "content": text})

    api_key, api_type, base_url, model = _resolve_llm_config()
    assistant_reply = _call_llm(api_key, api_type, base_url, model, past_conversation)

    past_conversation.append({"role": "assistant", "content": assistant_reply})

    if chatId is not None:
        conversation[chatId] = past_conversation

    return jsonify({"result": assistant_reply})

@bp.route('/llm/check', methods=['POST'])
@require_auth
def llm_check():
    global tokens_left
    global last_refresh

    # Non-openai_compatible providers don't have a per-minute token budget.
    user = g.user
    api_type = (user.llm_api_type if not user.is_guest else GUEST_LLM_API_TYPE) or "openai_compatible"
    if api_type != "openai_compatible":
        return jsonify({"result": "yes"})

    data = request.get_json()
    chatId = data.get("chatId", None)
    text = data.get("text", None)

    past_conversation = list(conversation.get(chatId, []))
    past_conversation.append({"role": "user", "content": text or ""})

    total_tokens = sum(len(m["content"].split()) * 1.5 for m in past_conversation)

    now_time = time.time()

    if (now_time - last_refresh) >= 60:
        tokens_left = 200000

    if tokens_left > total_tokens:
        tokens_left -= total_tokens
        return jsonify({"result": "yes"})

    return jsonify({"result": (60 - (now_time - last_refresh))})

@bp.route('/llm/clean', methods=['GET'])
@require_auth
def llm_clean():
    global conversation

    chatId = request.args.get('chatId', None)

    if chatId is None:
        return jsonify({"message": "You need to specify which chatId is being cleaned"}), 400

    conversation[chatId] = []

    return jsonify({"message": "Success"}), 200


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
          "name_property": optional, defaults to "name". Which property on
                           each polygon to use as the tag (e.g. "pri_neigh"
                           for Chicago neighborhoods, "BoroName" for NYC).
        }

    Response:
        {
          "type": "FeatureCollection",
          "features": [...]   # input points augmented with `neighborhood_name`
                              # (and `nbhd_*` aggregates) on properties
          "metadata": { "aggregates": [...] }   # per-polygon roll-up
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

    try:
        from utk_curio.backend.app.common.spatial import enrich_points_with_polygons
        enriched, aggregates = enrich_points_with_polygons(
            points=point_dicts,
            polygon_fc=polygons_fc,
            name_property=name_property,
        )
    except ImportError as e:
        return jsonify({
            "error": "spatial extras not installed (shapely required)",
            "hint": "pip install shapely",
            "detail": str(e),
        }), 503
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

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

    return jsonify({
        "type": "FeatureCollection",
        "features": out_features,
        "metadata": {"name": "spatial_join_result", "aggregates": aggregates},
    })
