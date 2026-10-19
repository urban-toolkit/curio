"""Street View Fetcher blueprint, registered at /api/streetvision."""

from flask import Blueprint

bp = Blueprint("streetvision", __name__)

from . import routes  # noqa: E402,F401 — register handlers on import
