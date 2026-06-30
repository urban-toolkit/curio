from __future__ import annotations

import json, os, uuid
from pathlib import Path

CHUNK_SIZE = 500

def _launch_dir() -> Path:
    return Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))

def softartifacts_root() -> Path:
    root = _launch_dir() / ".curio" / "data" / "softartifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root

#CHUNKING STUB, TO BE REPLACED LATER
#returning the array of texts after splitting it by chunk size =D
def split_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


#plain text and markdown only (v1 minimal ingest API)
def decode_upload(raw: bytes) -> str:
    return raw.decode("utf-8", errors = "replace")
 

def ingest_file(raw: bytes, filename: str, mime_type: str):
    #plain text and markdown only, other is unaccepted
    if not (filename.lower().endswith((".txt",".md")) or mime_type.startswith("text/")):
        raise ValueError(f"v1 ingest supports .txt/.md only (got {filename!r})")
 

    artifact_id = str(uuid.uuid4())
    artifact_dir = softartifacts_root() / artifact_id
    artifact_dir.mkdir(parents = True, exist_ok = False)   #not accepting an artifact file with same artifact_id

    #safe_name to defend against path traversal attack
    safe_name = Path(filename).name or "upload.txt"
    (artifact_dir / safe_name).write_bytes(raw)

    text = decode_upload(raw)
    chunks = split_text(text)

    chunks_row = [{"index": i, "text": t} for i, t in enumerate(chunks)]
    
    (artifact_dir / "chunk.json").write_text(
        json.dumps(chunks_row, ensure_ascii = False, indent = 2),
        encoding = "utf-8"
    )

    return {
        "artifactId": artifact_id,
        "sourceFile": safe_name,
        "mimetype": mime_type or "application/octet-stream",
        "status": "ready",
    }