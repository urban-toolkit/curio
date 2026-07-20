from __future__ import annotations
import uuid, json, mimetypes
from ..ingest import softartifacts_root
from utk_curio.backend.app.common.safe_paths import validate_component

#check if uuid is valid, return true if yes false otherwise
def _is_valid_uuid(artifactId):
    try:
        uuid.UUID(str(artifactId))
        return True
    except ValueError:
        return False

#check if the artifactId file exists under .curio/data folder 
#check if under the artifactId folder there is chunk.json
def _is_valid_dir(artifactDir):
    if(not artifactDir.is_dir()):
        return False
    
    chunks_path = artifactDir / "chunk.json"
    
    if(not chunks_path.is_file()):
        return False
    
    try:
        chunks = json.loads(chunks_path.read_text(encoding = "utf-8"))
    except:
        return False
    
    return True


"""
validate artifact Id
check if the artifact Id exist in .curio/data
return JSON shape"""    
def get_softartifact_metadata(artifactId: str) -> dict | None:
    """Return stored artifact metadata, or None if the artifact does not exist."""
    try:
        validate_component(artifactId, field = "artifact_id") #make sure that the artifactId is safe to use 
    except Exception:
        return None
    
    if not _is_valid_uuid(artifactId):
        return None
    
    artifactDir = softartifacts_root() / artifactId
    if not _is_valid_dir(artifactDir):
        return None
    
    source_file: str | None = None
    for f in artifactDir.iterdir():
        if f.is_file() and f.name != "chunk.json":
            source_file = f.name
            break
    
    if not source_file:
        return None
    
    guessedMimed, _ = mimetypes.guess_type(source_file)

    return{
        "artifactId": artifactId,
        "sourceFile": source_file,
        "mimeType": guessedMimed or "application/octet-stream",
        "status": "ready"
    }

    
    
