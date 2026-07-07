from flask import request, jsonify
from utk_curio.backend.app.notebooks import notebooks_bp
from utk_curio.backend.app.notebooks.analyzer import analyze_cells

# LLM configurations
from utk_curio.backend.config import (
    GUEST_LLM_API_TYPE,
    GUEST_LLM_BASE_URL,
    GUEST_LLM_API_KEY,
    GUEST_LLM_MODEL,
)


@notebooks_bp.route('/api/analyzeNotebook', methods=['POST'])
def analyze_notebook():
    cells = request.get_json(force=True).get('cells', [])
    return jsonify(analyze_cells(cells))

@notebooks_bp.route('/api/alive', methods=['GET'])
def alive():
    return jsonify({"response": 123})
