import os 
from flask import jsonify, request

from .services.ingest import ingest_file
from .services.get_artifact import get_softartifact_metadata
from .services.retrieve import search_chunks

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
    
    try:
        result = ingest_file(
            raw,
            upload.filename,
            upload.mimetype or "application/octet-stream"
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

     
    result["role"] = role
    return jsonify(result), 200


# ── artifacts/<artifactId> ──────────────────────────────────────────────────────────
@bp.get("/artifacts/<artifactId>")
def getArtifact(artifactId: str):
    meta = get_softartifact_metadata(artifactId)
    if meta is None:
        return jsonify({"error": "artifact not found"}), 400
    
    return jsonify(meta), 200


# ── Retrieve ──────────────────────────────────────────────────────────
@bp.post("retrieve")
def retrieve():
    data = request.get_json(silent = True);

    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON"}), 400

    artifactId = data.get("artifactId")
    query = data.get("query")
    top_k = data.get("top_k") 
    if artifactId is None:
        return jsonify({"error": "missing artifactId"}), 400
    
    return jsonify(search_chunks(query, artifactId, top_k));
    


