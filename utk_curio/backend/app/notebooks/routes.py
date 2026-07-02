from flask import request, jsonify
from utk_curio.backend.app.notebooks import notebooks_bp
from utk_curio.backend.app.notebooks.analyzer import analyze_cells


@notebooks_bp.route('/api/analyzeNotebook', methods=['POST'])
def analyze_notebook():
    cells = request.get_json(force=True).get('cells', [])
    return jsonify(analyze_cells(cells))
