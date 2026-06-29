from __future__ import annotations

from flask import jsonify, request
import json, os, uuid
from pathlib import Path

CHUNK_SIZE = 500

def _launch_dir() -> Path:
    return Path(os.environ.get("CURIO_LAUNCH_CWD"), os.getcwd())

def softartifacts_root() -> Path:
    root = _launch_dir() / ".curio" / "data" / "softartifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root

#CHUNKING STUB, TO BE REPLACED LATER
def split_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def ingest_file(raw: bytes, filename: str, mime_type: str):
    artifact_id = str(uuid.uuid4())
    artifact_dir = softartifacts_root / artifact_id
    artifact_dir.mkdir(parent = True, exist_ok = False)   #not accepting a artifact file with same artifact_id

    return jsonify({
        "artifactId": "",
        "sourceFile": "",
        "mimetype": "",
        "status": ""
    })