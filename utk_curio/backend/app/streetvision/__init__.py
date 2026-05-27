"""Street Vision Flask blueprint.

Ported from the FastAPI service in
github.com/ManeeshJupalle/Street-Level-Vision-Analytics-Node-for-Curio
to fit inside Curio's single-process Flask app. Endpoints live under
``/api/streetvision/*``; see ``routes.py`` for the full list.

Heavy ML dependencies (torch, transformers, ultralytics, shapely, geopandas)
are *optional* — they're declared in ``pyproject.toml`` under the
``streetvision`` extras group. Endpoints that need them lazy-import at
request time and return ``503`` with an install hint if missing.
"""

from flask import Blueprint

bp = Blueprint("streetvision", __name__)

from . import routes  # noqa: E402,F401 — register handlers on import
