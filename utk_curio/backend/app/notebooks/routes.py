from flask import request, jsonify
from utk_curio.backend.app.notebooks import notebooks_bp
from utk_curio.backend.app.notebooks.analyzer import analyze_cells, runtime_analyze_cells


@notebooks_bp.route('/api/analyzeNotebook', methods=['POST'])
def analyze_notebook():
    # We are going to do a quick change here to see how stuff works out
    cells = request.get_json(force=True).get('cells', [])
    # Change back to analyze_cells once your done
    # print("Static analyze cells: " + jsonify(runtime_analyze_cells(cells)))
    # print("Runtime analyze cells: " + jsonify(analyze_cells(cells)))
    return jsonify(runtime_analyze_cells(cells))
