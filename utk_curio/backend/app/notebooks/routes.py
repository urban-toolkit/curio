from flask import request, jsonify, g
from utk_curio.backend.app.notebooks import notebooks_bp
from utk_curio.backend.app.notebooks.analyzer import analyze_cells
from utk_curio.backend.app.api.routes import _call_llm
from utk_curio.backend.app.api.routes import get_loaded_files_metadata
from utk_curio.backend.app.users.dependencies import require_auth

import importlib.resources
import re, json

# The directory to the llm-prompts
LLM_PROMPTS_DIR = importlib.resources.files("utk_curio") / "llm-prompts"

def extract_json(text):
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else text
    return json.loads(candidate)

@notebooks_bp.route('/api/analyzeNotebook', methods=['POST'])
def analyze_notebook():
    cells = request.get_json(force=True).get('cells', [])
    return jsonify(analyze_cells(cells))

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

@notebooks_bp.route('/api/llm/analysis', methods=['POST'])
@require_auth
def llm_analysis():
    #Retrieve data 
    data = request.get_json()

    # What we need to send to this API so far
    cells = data.get('cells', [])

    # We need to hide this before commiting
    # api_key     = "<Nope>"
    # api_type    = "openai_compatible"
    # base_url    = "https://sage200.evl.uic.edu"
    # model       = 'gemma4'
    api_key, api_type, base_url, model = _resolve_llm_config()
    print(api_key)
    print(api_type)
    print(base_url)
    print(model)

    # Obtaining the preamble
    prompt_preamble_file = open(LLM_PROMPTS_DIR / "default_preamble.txt")
    prompt_preamble = prompt_preamble_file.read()
    prompt_preamble += "In case you need. This is the list of files and metadata currently loaded into the system"
    
    metadata = get_loaded_files_metadata("./")
    prompt_preamble += "\n" + metadata


    # Obtaining the prompt
    prompt_file_obj = open(LLM_PROMPTS_DIR / "jupyter_notebook_prompt.txt")
    prompt_text = prompt_file_obj.read()

    # Giving the LLM the context
    content = prompt_preamble + "\n" + prompt_text
    messages = [{"role": "system", "content": content}]

    # Here we attempt to send our cells for processing
    messages.append({"role": "user", "content": f"{cells}"})

    resp = _call_llm(api_key, api_type, base_url, model, messages)

    result = extract_json(resp)
    # print(result)
    return jsonify(result)
