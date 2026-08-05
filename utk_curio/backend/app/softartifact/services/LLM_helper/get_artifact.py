from __future__ import annotations
import uuid, json, mimetypes
from ..ingest import softartifacts_root
from .store import get_artifact
from utk_curio.backend.app.common.safe_paths import validate_component

#check if uuid is valid, return true if yes false otherwise
def _is_valid_uuid(artifact_id):
    try:
        uuid.UUID(str(artifact_id))
        return True
    except ValueError:
        return False

# #check if the artifact_id file exists under .curio/data folder 
# #check if under the artifact_id folder there is chunk.json
# def _is_valid_dir(artifactDir):
#     if(not artifactDir.is_dir()):
#         return False
    
#     chunks_path = artifactDir / "chunk.json"
    
#     if(not chunks_path.is_file()):
#         return False
    
#     try:
#         chunks = json.loads(chunks_path.read_text(encoding = "utf-8"))
#     except:
#         return False
    
#     return True


"""
validate artifact Id
check if the artifact Id exist in .curio/data
return JSON shape"""    
def get_softartifact_metadata(artifact_id: str) -> dict | None:
    """Return stored artifact metadata, or None if the artifact does not exist."""
    try:
        validate_component(artifact_id, field = "artifact_id") #make sure that the artifact_id is safe to use 
    except Exception:
        return None
    
    if not _is_valid_uuid(artifact_id):
        return None
    
    row = get_artifact(artifact_id=artifact_id)
    if row is None:
        return None
    

    return {
        "artifact_id": row["artifact_id"],
        "sourceFile": row["source_file"],
        "mimetype": row["mimetype"],
        "kind": row.get("kind"),
        "status": "ready",
    }

    
    
