import os 
from flask import jsonify, request
from . import bp


# ── Health ──────────────────────────────────────────────────────────
@bp.get("/health")
def health():
    return jsonify({
        "status": "healthy",
    })

# ── Ingest ──────────────────────────────────────────────────────────
@bp.post("/ingest")
def ingest():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "missing some fields"}), 400
    
    role = (request.form.get("role") or "inform").strip()
    #v1: accept role but not persisted yet

    raw = upload.read()  
    if not raw:
        return jsonify({"error": "empty file"}), 400
    
    
    return jsonify({
        "artifactId": "",
        "sourceFile": "",
        "mimetype": "",
        "status": ""
    })