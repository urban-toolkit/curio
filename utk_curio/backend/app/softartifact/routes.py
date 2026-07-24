#entry point for softArtifact node
import os 
from flask import jsonify, request

from .services.ingest import ingest_file
from .services.LLM_helper.get_artifact import get_softartifact_metadata
from .services.LLM_helper.retrieve import search_chunks
from .services.LLM_helper.store import list_chunks
from .services.explain import explain_artifact
from .services.inform import inform_artifact
from .services.propose import propose_trill

from utk_curio.backend.app.users.dependencies import require_auth

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


# ── artifacts/<artifact_id> ──────────────────────────────────────────────────────────
@bp.get("/artifacts/<artifact_id>")
def getArtifact(artifact_id: str):
    meta = get_softartifact_metadata(artifact_id)
    if meta is None:
        return jsonify({"error": "artifact not found"}), 400
    
    return jsonify(meta), 200


# ── Retrieve ──────────────────────────────────────────────────────────
@bp.post("retrieve")
@require_auth
def retrieve():
    data = request.get_json(silent = True);
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON"}), 400

    artifact_id = data.get("artifact_id") or None
    query = data.get("query") or None
    top_k = data.get("top_k") or None
    if artifact_id is None:
        return jsonify({"error": "missing artifact_id"}), 400
    if query is None:
        return jsonify({"error": "missing query"}), 400
    
    return jsonify(search_chunks(query, artifact_id, top_k));


# ── Explain ──────────────────────────────────────────────────────────
@bp.post("explain")
@require_auth 
def explain():
    data = request.get_json(silent = True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON"}), 400

    artifact_id = data.get("artifact_id") or None
    query = data.get("query") or None
    top_k = data.get("top_k") or None
    context = data.get("context") or None    
    source_file = data.get("sourceFile") or None

    if artifact_id is None:
        return jsonify({"error": "missing artifact_id"}), 400


    explanation = explain_artifact(artifact_id=artifact_id, query=query, top_k=top_k, source_file= source_file, context=context);
    return jsonify(explanation);
    

# ── Inform ──────────────────────────────────────────────────────────
@bp.post("inform")
@require_auth
def inform():
    data = request.get_json(silent = True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON"}), 400
    
    
    artifact_id = data.get("artifact_id") or None
    top_k = data.get("top_k") or None
    source_file = data.get("sourceFile") or None
    context = data.get("context") or None
    if artifact_id is None:
        return jsonify({"error": "missing artifact_id"}), 400
    
    output = inform_artifact(artifact_id=artifact_id, top_k=top_k, context=context, source_file = source_file)
    return jsonify(output)

# ── Transform ──────────────────────────────────────────────────────────
@bp.post("propose_trill")
@require_auth
def proposeTrill():  # reads artifact_id, mode, top_k, sourceFile, context, query
    data = request.get_json(silent = True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be valid JSON"}), 400
    
    #reading the json request 
    artifact_id = data.get("artifact_id") or None
    top_k = data.get("top_k") or None
    source_file = data.get("sourceFile") or None
    role = data.get("role") or None
    context = data.get("context") or None          #this is the dataflow itself
    
    if artifact_id is None:
        return jsonify({"error": "missing artifact_id"}), 400 

    output = propose_trill(artifact_id=artifact_id, mode=role, context=context, top_k=top_k, source_file=source_file)   
    return jsonify(output)

@bp.get("/artifacts/<artifact_id>/chunks")
def list_artifact_chunks(artifact_id: str):
    meta = get_softartifact_metadata(artifact_id)
    if meta is None:
        return jsonify({"error": "artifact not found"}), 404
    return jsonify({"artifact_id": artifact_id, "chunks": list_chunks(artifact_id)}), 200