from flask import g, jsonify, request

from utk_curio.backend.app.notebooks import notebooks_bp
from utk_curio.backend.app.notebooks.analyzer import analyze_cells, chart_cells
from utk_curio.backend.app.notebooks.charts import altair_specs
from utk_curio.backend.app.users.dependencies import get_current_token, require_auth


@notebooks_bp.route('/api/analyzeNotebook', methods=['POST'])
@require_auth
def analyze_notebook():
    """What the Projects page's Import notebook builds a dataflow from: each
    cell's analysis (``analyzer.analyze_cells``), with the Vega-Lite spec the
    sandbox made of each cell that draws an Altair chart (``charts.py``),
    under the caller's sign-in."""
    cells = request.get_json(force=True).get('cells', [])
    result = analyze_cells(cells)
    specs = altair_specs(
        chart_cells(cells, result['analysis']), user=g.user, session_token=get_current_token(),
    )
    for index, spec in specs.items():
        result['analysis'][index]['altair_spec'] = spec
    return jsonify(result)
