import subprocess

from flask import request, jsonify
from utk_curio.backend.app.notebooks import notebooks_bp
from utk_curio.backend.app.notebooks.analyzer import analyze_cells
from utk_curio.backend.app.notebooks.run_pipreqs import extract_code, run_pipreqs

@notebooks_bp.route('/api/analyzeNotebook', methods=['POST'])
def analyze_notebook():
    cells = request.get_json(force=True).get('cells', [])
    return jsonify(analyze_cells(cells))

@notebooks_bp.route('/api/extractRequirements', methods=['POST'])
def extract_requirements():
    notebook = request.get_json(force=True).get('notebook', {})
    code = extract_code(notebook)

    try:
        requirements = run_pipreqs(code)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    except subprocess.TimeoutExpired:
        return jsonify({"error": "pipreqs timed out"}), 504

    return jsonify({ "requirements": requirements })
