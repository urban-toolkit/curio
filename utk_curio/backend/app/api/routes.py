from flask import request, abort, jsonify, g, Response, current_app
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
SANDBOX_UPLOAD_TIMEOUT   = 60
SANDBOX_INSTALL_TIMEOUT  = 600  # `pip install` of optional libraries can be slow


def _sandbox_call(method: str, path: str, *, label: str, timeout: int, **kwargs):
    """Call the sandbox over `_sandbox_session` with consistent error handling.

    Catches `requests.Timeout` and `requests.ConnectionError` and returns a
    Flask `(jsonify(...), status)` tuple with a clear error message instead
    of letting the exception escape (which would otherwise surface to the
    browser as an opaque 'NetworkError when attempting to fetch resource').

    On success returns the `requests.Response` object directly so callers can
    parse the JSON / forward it as before.

    Returns either:
      - `requests.Response` on success
      - `(flask_response, status_code)` tuple on transport-level failure
    """
    url = api_address + ":" + str(api_port) + path
    fn = getattr(_sandbox_session, method)
    try:
        return fn(url, timeout=timeout, **kwargs)
    except requests.Timeout as e:
        print(f"[backend {label}] sandbox call timed out after {timeout}s: {e}", flush=True)
        return jsonify({
            'error': 'sandbox_timeout',
            'message': (f'The sandbox did not respond within {timeout}s on {path}. '
                        'The node is likely still running — check the sandbox log. '
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
from utk_curio.backend.extensions import db
from utk_curio.backend.app.users.dependencies import require_auth, get_current_token
import uuid
import os
import time
from utk_curio.backend.config import (
    GUEST_LLM_API_TYPE,
    GUEST_LLM_BASE_URL,
    GUEST_LLM_API_KEY,
    GUEST_LLM_MODEL,
)


def _resolve_llm_config():
    """Return (api_key, api_type, base_url, model) for the current authenticated user."""
    user = g.user
    if user.is_guest:
        if not GUEST_LLM_API_KEY:
            abort(400, description="LLM is not available for guest users at this time.")
        return GUEST_LLM_API_KEY, GUEST_LLM_API_TYPE, GUEST_LLM_BASE_URL, GUEST_LLM_MODEL
    if not user.llm_model:
        abort(400, description="No LLM configured. Set your provider and model in the Projects page.")
    return (
        user.llm_api_key or "",
        user.llm_api_type or "openai_compatible",
        user.llm_base_url or "",
        user.llm_model,
    )


def _call_llm(api_key: str, api_type: str, base_url: str, model: str, messages: list) -> str:
    """Dispatch an LLM chat completion to the configured provider."""
    if api_type == "anthropic":
        import anthropic
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            system="\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN,
            messages=chat_messages,
            max_tokens=4096,
        )
        return resp.content[0].text
    elif api_type == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        history = []
        for m in chat_messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            history.append({"role": role, "parts": [m["content"]]})
        last_user_msg = chat_messages[-1]["content"] if chat_messages else ""
        system_instruction = "\n".join(system_parts) if system_parts else None
        gen_model = genai.GenerativeModel(model, system_instruction=system_instruction)
        chat = gen_model.start_chat(history=history)
        response = chat.send_message(last_user_msg)
        return response.text
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": api_key or "no-key"}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        completion = client.chat.completions.create(model=model, messages=messages)
        return completion.choices[0].message.content

# The Flask app
from utk_curio.backend.app.api import bp


# Sandbox address
api_address='http://'+os.getenv('FLASK_SANDBOX_HOST', '127.0.0.1')
api_port=int(os.getenv('FLASK_SANDBOX_PORT', 2000))

conversation = {}

tokens_left = 200000 # Tokens allowed per minute
last_refresh = time.time() # Last time that 60 minutes elapsed

# In-memory node-type registry populated by the frontend via POST /node-types.
# Initialised with hardcoded defaults so templates work even if the frontend
# hasn't registered yet (e.g. backend starts before frontend).
_node_type_registry: dict = {
    "DATA_LOADING":          {"inputTypes": [],                                                             "outputTypes": ["DATAFRAME", "GEODATAFRAME"]},
    "DATA_EXPORT":           {"inputTypes": ["DATAFRAME", "GEODATAFRAME"],                                 "outputTypes": []},
    "DATA_TRANSFORMATION":   {"inputTypes": ["DATAFRAME", "GEODATAFRAME"],                                 "outputTypes": ["DATAFRAME", "GEODATAFRAME"]},
    "COMPUTATION_ANALYSIS":  {"inputTypes": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],        "outputTypes": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"]},
    "FLOW_SWITCH":           {"inputTypes": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],        "outputTypes": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"]},
    "VIS_VEGA":              {"inputTypes": ["DATAFRAME"],                                                 "outputTypes": ["DATAFRAME"]},
    "VIS_SIMPLE":            {"inputTypes": ["DATAFRAME", "GEODATAFRAME", "VALUE"],                        "outputTypes": ["DATAFRAME", "GEODATAFRAME", "VALUE"]},
    "CONSTANTS":             {"inputTypes": [],                                                             "outputTypes": ["VALUE"]},
    "DATA_POOL":             {"inputTypes": ["DATAFRAME", "GEODATAFRAME"],                                 "outputTypes": ["DATAFRAME", "GEODATAFRAME"]},
    "MERGE_FLOW":            {"inputTypes": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],        "outputTypes": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"]},
    "DATA_SUMMARY":          {"inputTypes": ["DATAFRAME", "GEODATAFRAME"],                                 "outputTypes": ["JSON"]},
    "AUTK_GRAMMAR":          {"inputTypes": ["LIST", "JSON", "GEODATAFRAME", "DATAFRAME"],                 "outputTypes": ["LIST", "JSON", "GEODATAFRAME", "DATAFRAME"]},
}

def get_output_types(node_type: str) -> list:
    entry = _node_type_registry.get(node_type)
    return entry["outputTypes"] if entry else []

def get_input_types(node_type: str) -> list:
    entry = _node_type_registry.get(node_type)
    return entry["inputTypes"] if entry else []


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

def transform_to_vega(data):
    """Transform a pandas-style column-based JSON to Vega-Lite row-based JSON."""
    if "data" in data and isinstance(data["data"], dict):
        columns = list(data["data"].keys())
        num_rows = len(data["data"][columns[0]])
        return [{col: data["data"][col][i] for col in columns} for i in range(num_rows)]
    return data


@bp.route('/')
def root():
    abort(403)

@bp.route('/live')
def live():
    return 'Backend is live.'

@bp.route('/version')
def version():
    from utk_curio import __version__
    return jsonify({'version': __version__})

@bp.route('/node-types', methods=['POST'])
def register_node_types():
    payload = request.get_json(silent=True) or {}
    node_types = payload.get('nodeTypes', {})
    if not isinstance(node_types, dict) or len(node_types) == 0:
        return jsonify({'error': 'Expected { nodeTypes: { NODE_TYPE: { inputTypes, outputTypes } } }'}), 400

    _node_type_registry.clear()
    _node_type_registry.update(node_types)
    return jsonify({'registered': len(_node_type_registry)}), 200

@bp.route('/node-types', methods=['GET'])
def get_node_types():
    return jsonify(_node_type_registry), 200

@bp.route('/cwd')
def cwd():
    return os.getcwd()

@bp.route('/launchCwd')
def launchCwd():
    return os.environ["CURIO_LAUNCH_CWD"]

@bp.route('/sharedDataPath')
def sharedDataPath():
    return os.environ["CURIO_SHARED_DATA"]

@bp.route('/file/<path:filename>', methods=['GET'])
def serve_launch_cwd_file(filename: str):
    """Serve a file by its path *relative to CURIO_LAUNCH_CWD* so browser-side
    nodes (e.g. autk-grammar) can fetch binary assets (PBF, GeoTIFF, …) the
    same way Python sandbox nodes read them from disk — one shared root, one
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

@bp.route('/upload', methods=['POST'])
@require_auth
def upload_file():

    if 'file' not in request.files:
        return 'No file part'

    file = request.files['file']

    if file.filename == '':
        return 'No selected file'

    response = _sandbox_call(
        'post', '/upload',
        label='/upload', timeout=SANDBOX_UPLOAD_TIMEOUT,
        files={'file': file}, data={'fileName': file.filename},
    )
    if isinstance(response, tuple):  # transport-level failure
        return response

    if response.status_code == 200:
        return 'File uploaded successfully'
    else:
        return 'Error uploading file'


@bp.route('/get', methods=['GET'])
@require_auth
def get_file():
    file_name = request.args.get('fileName')
    vega = request.args.get('vega', 'false').lower() == 'true'

    if not file_name:
        return 'No artifact id specified', 400

    wants_arrow = request.accept_mimetypes.best == ARROW_IPC_MIME
    if wants_arrow and vega:
        return jsonify({
            'error': 'bad_request',
            'message': "Arrow IPC and vega=true are mutually exclusive.",
        }), 400

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
        if vega:
            data = transform_to_vega(data)
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


@bp.route('/processPythonCode', methods=['POST'])
@require_auth
def process_python_code():
    import time as _time
    t0 = _time.perf_counter()

    code = request.json['code']
    nodeType = request.json['nodeType']
    input = _parse_input_ref(request.json.get('input'))

    session_id = get_current_token()
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

    return {'stdout': stdout, 'stderr': stderr, 'input': input, 'output': output}


@bp.route('/processJavaScriptCode', methods=['POST'])
@require_auth
def process_javascript_code():
    import time as _time
    t0 = _time.perf_counter()

    code = request.json['code']
    nodeType = request.json['nodeType']
    input = _parse_input_ref(request.json.get('input'))

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

    return {'stdout': stdout, 'stderr': stderr, 'input': input, 'output': output}


@bp.route('/installPackages', methods=['POST'])
@require_auth
def install_packages():
    packages = request.json.get('packages', [])
    response = _sandbox_call(
        'post', '/install',
        label='/installPackages', timeout=SANDBOX_INSTALL_TIMEOUT,
        data=json.dumps({"packages": packages}),
        headers={"Content-Type": "application/json"},
    )
    if isinstance(response, tuple):
        return response
    return response.json()

@bp.route('/signin', methods=['POST'])
def signin_legacy():
    """Deprecated shim — redirects to /api/auth/signin/google."""
    from flask import redirect
    return redirect('/api/auth/signin/google', code=308)

@bp.route('/getUser', methods=['GET'])
def get_user_legacy():
    """Deprecated shim — redirects to /api/auth/me."""
    from flask import redirect
    return redirect('/api/auth/me', code=308)

@bp.route('/saveUserType', methods=['POST'])
def save_user_type_legacy():
    """Deprecated shim — redirects to /api/auth/me (PATCH)."""
    from flask import redirect
    return redirect('/api/auth/me', code=308)

@bp.route('/checkDB', methods=['GET'])
def check_db():
    db.session.execute(db.text('SELECT 1'))
    return "OK", 200

@bp.route('/datasets', methods=['GET'])
def list_datasets():
    response = requests.get(api_address+":"+str(api_port)+"/datasets", timeout=30)
    response.raise_for_status()
    files = response.json()
    return jsonify(files)


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
        except Exception:  # noqa: BLE001 — never fail /starters over a bad package
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
