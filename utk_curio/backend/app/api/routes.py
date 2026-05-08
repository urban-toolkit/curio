from flask import request, abort, jsonify, g
import requests
import json

_sandbox_session = requests.Session()
from utk_curio.backend.extensions import db
from utk_curio.backend.app.users.dependencies import require_auth, get_current_token
import uuid
import os
import time
import pandas as pd
import geopandas as gpd
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
    "AUTK_DB":               {"inputTypes": [],                                                             "outputTypes": ["LIST"]},
    "AUTK_COMPUTE":          {"inputTypes": ["LIST", "JSON", "GEODATAFRAME"],                              "outputTypes": ["LIST", "JSON", "GEODATAFRAME"]},
    "AUTK_MAP":              {"inputTypes": ["LIST", "JSON", "GEODATAFRAME"],                              "outputTypes": ["LIST", "JSON", "GEODATAFRAME"]},
    "AUTK_PLOT":             {"inputTypes": ["LIST", "JSON", "GEODATAFRAME", "DATAFRAME"],                 "outputTypes": ["LIST", "JSON", "GEODATAFRAME", "DATAFRAME"]},
}

def get_output_types(node_type: str) -> list:
    entry = _node_type_registry.get(node_type)
    return entry["outputTypes"] if entry else []

def get_input_types(node_type: str) -> list:
    entry = _node_type_registry.get(node_type)
    return entry["inputTypes"] if entry else []

def get_folder_for_type(node_type: str) -> str:
    return node_type.lower()

def get_type_for_folder(folder: str) -> str:
    return folder.upper()

def get_template_folders() -> list:
    """Return all folder names that may contain templates."""
    folders = set()
    for node_type in _node_type_registry:
        folders.add(get_folder_for_type(node_type))
    return sorted(folders)

def get_templates_path():
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())
    return os.path.join(launch_dir, "templates")

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

@bp.route('/upload', methods=['POST'])
@require_auth
def upload_file():

    if 'file' not in request.files:
        return 'No file part'

    file = request.files['file']

    if file.filename == '':
        return 'No selected file'

    response = _sandbox_session.post(api_address+":"+str(api_port)+"/upload", files={'file': file}, data={'fileName': file.filename}, timeout=60)

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

    session_id = get_current_token()
    try:
        t0 = time.perf_counter()
        resp = _sandbox_session.get(
            api_address + ":" + str(api_port) + "/get",
            params={"fileName": file_name, "sessionId": session_id},
            timeout=60,
        )
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
    try:
        t0 = time.perf_counter()
        resp = _sandbox_session.get(
            api_address + ":" + str(api_port) + "/get",
            params={"fileName": file_name, "maxRows": max_rows, "sessionId": session_id},
            timeout=60,
        )
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
    response = _sandbox_session.post(api_address+":"+str(api_port)+"/exec",
                            data=json.dumps({
                                "code": code,
                                "file_path": input['path'],
                                "nodeType": nodeType,
                                "dataType": input['dataType'],
                                "session_id": session_id,
                            }),
                            headers={"Content-Type": "application/json"},
                            timeout=120)
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
    response = _sandbox_session.post(
        api_address + ":" + str(api_port) + "/execJs",
        data=json.dumps({
            "code": code,
            "file_path": input['path'],
            "nodeType": nodeType,
            "dataType": input['dataType'],
            "session_id": session_id,
        }),
        headers={"Content-Type": "application/json"},
        timeout=120,
    )
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
    try:
        response = _sandbox_session.post(
            api_address + ":" + str(api_port) + "/install",
            data=json.dumps({"packages": packages}),
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
        return response.json()
    finally:
        pass

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

def create_template_object(folder, filename, code):
    return {
        "id": str(uuid.uuid4()),
        "type": get_type_for_folder(folder),
        "name": filename.replace(".py", "").replace("_", " "),
        "description": "",
        "accessLevel": "ANY",
        "code": code,
        "custom": True
    }

def generate_templates():
    templates = []

    for folder in get_template_folders():
        folder_path = os.path.join(get_templates_path(), folder)

        if not os.path.isdir(folder_path):
            continue

        for file in os.listdir(folder_path):
            if file.endswith(".py"):

                with open(os.path.join(folder_path, file), "r", encoding="utf-8") as f:
                    code = f.read()

                template_obj = create_template_object(folder, file, code)
                templates.append(template_obj)

    return templates

@bp.route('/datasets', methods=['GET'])
def list_datasets():
    response = requests.get(api_address+":"+str(api_port)+"/datasets", timeout=30)
    response.raise_for_status()
    files = response.json()
    return jsonify(files)


@bp.route("/templates", methods=["GET"])
def get_templates():
    return jsonify(generate_templates())

@bp.route('/addTemplate', methods=['POST'])
def add_template():
    data = request.get_json()

    required_fields = ['id', 'type', 'name', 'description', 'accessLevel', 'code', 'custom']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing one or more required fields'}), 400

    template_type = data['type']
    if template_type not in _node_type_registry:
        return jsonify({'error': f"Unknown template type: {template_type}"}), 400

    subfolder = get_folder_for_type(template_type)
    folder_path = os.path.join(get_templates_path(), subfolder)
    os.makedirs(folder_path, exist_ok=True)

    replace_name = data['name'].replace(" ", "_")

    filename = f"{replace_name}.py"
    filepath = os.path.join(folder_path, filename)

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(data['code'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': f"Template saved to {filepath}"}), 200

def get_loaded_files_metadata(folder_path):
    metadata = ""

    for file in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file)
        if file.endswith(".csv"):
            df = pd.read_csv(file_path)
            columns = [f"{col} ({df[col].dtype})" for col in df.columns]
            geometry_type = "None"
        elif file.endswith(".json") or file.endswith(".geojson"):
            try:
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
