from flask import request, abort, jsonify
import json
import re
import sys
import geopandas as gpd
import pandas as pd
from utk_curio.sandbox.app import app, cache
from utk_curio.sandbox.app.utils.cache import make_key
import os
import mmap
from pathlib import Path

from shapely import wkt

from utk_curio.sandbox.app.worker import _worker_init, execute_code, execute_js_code
from utk_curio.sandbox.util.parsers import load_from_duckdb, parseOutput

_VALID_PACKAGE_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._\-]*(\[[\w,\s]+\])?(===?|~=|!=|>=?|<=?[a-zA-Z0-9._\-*]+)?$')

# Pre-load heavy libraries once at sandbox startup so every /exec call is fast.
_worker_init()

DATA_DIR = "./data"

@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
    return response

@app.route('/')
def root():
    abort(403)

@app.route('/live', methods=['GET'])
def live():
    return 'Sandbox is live.'

@app.route('/get', methods=['GET'])
def get_artifact():
    import pandas as _pd
    art_id = request.args.get('fileName')
    if not art_id:
        abort(400, "fileName is required")
    session_id = request.args.get('sessionId') or None
    max_rows_param = request.args.get('maxRows')
    raw = load_from_duckdb(art_id, session_id=session_id)
    total_rows = None
    if max_rows_param is not None:
        max_rows = int(max_rows_param)
        if isinstance(raw, _pd.DataFrame):
            total_rows = len(raw)
            raw = raw.head(max_rows)
    data = parseOutput(raw)
    data['filename'] = art_id
    if total_rows is not None:
        data['preview'] = True
        data['previewRows'] = min(max_rows, total_rows)
        data['totalRows'] = total_rows
    return jsonify(data)

@app.route('/cwd')
def cwd():
    return os.getcwd()

@app.route('/launchCwd')
def launchCwd():
    return os.environ["CURIO_LAUNCH_CWD"]

@app.route('/sharedDataPath')
def sharedDataPath():
    return os.environ["CURIO_SHARED_DATA"]

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return 'No file part'

    file = request.files['file']
    if file.filename == '':
        return 'No selected file'

    launch_dir = os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())
    data_dir = Path(os.path.join(launch_dir, "data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    filename = os.path.basename(request.form.get('fileName', file.filename))
    save_path = data_dir / filename
    file.save(save_path)

    return str(save_path)

@app.route('/datasets', methods=['GET'])
def list_datasets():
    allowed_extensions = {'.json', '.geojson', '.csv'}

    files = []

    # Source 1: /data relative to the root of the installed pip package
    project_root_data = Path(__file__).parent.parent.parent / 'data'
    print("Loading datasets from pip package location:", project_root_data)

    if project_root_data.exists() and project_root_data.is_dir():
        files.extend([
            f.as_posix() for f in project_root_data.iterdir()
            if f.is_file() and f.suffix.lower() in allowed_extensions
        ])

    # Source 2: /data relative to current working directory
    # cwd_data = os.getcwd() / 'data'
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())
    data_dir = os.path.join(launch_dir, "data")
    data_dir = Path(data_dir)
    print("Loading datasets from working directory:", data_dir)

    if data_dir.exists() and data_dir.is_dir():
        files.extend([
            f.as_posix() for f in data_dir.iterdir()
            if f.is_file() and f.suffix.lower() in allowed_extensions
        ])

    return jsonify(files)

@app.route('/install', methods=['POST'])
def install_packages():
    import subprocess
    packages = request.json.get('packages', [])
    if not packages:
        abort(400, "No packages specified")

    results = []
    for package in packages:
        package = package.strip()
        if not package:
            continue
        if not _VALID_PACKAGE_RE.match(package):
            results.append({"package": package, "success": False, "stdout": "", "stderr": f"Invalid package name: {package}"})
            continue
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', package],
            capture_output=True, text=True
        )
        results.append({
            "package": package,
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })

    return jsonify({"results": results})

@app.route('/exec', methods=['POST'])
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
    launch_dir = os.environ.get('CURIO_LAUNCH_CWD', os.getcwd())

    print(f"[sandbox /exec] received  node={node_type}", file=sys.stderr, flush=True)
    result = execute_code(code, str(file_path), str(node_type), str(data_type), launch_dir, session_id=session_id)

    print(f"[sandbox /exec] finished  total={time.perf_counter()-t0:.3f}s  node={node_type}", file=sys.stderr, flush=True)
    return jsonify(result)

@app.route('/execJs', methods=['POST'])
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
    launch_dir = os.environ.get('CURIO_LAUNCH_CWD', os.getcwd())

    print(f"[sandbox /execJs] received  node={node_type}", file=sys.stderr, flush=True)
    result = execute_js_code(code, str(file_path), str(node_type), str(data_type), launch_dir, session_id=session_id)

    print(f"[sandbox /execJs] finished  total={time.perf_counter()-t0:.3f}s  node={node_type}", file=sys.stderr, flush=True)
    return jsonify(result)


