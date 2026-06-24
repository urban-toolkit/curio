import os 
from flask import jsonify
from . import bp


# ── Health ──────────────────────────────────────────────────────────
@bp.get("/health")
def health():
    return jsonify({
        "status": "healthy",
    })