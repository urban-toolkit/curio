from __future__ import annotations

import json, os, uuid
from pathlib import Path
from .LLM_helper.chunk_schema import Chunk
from pypdf import PdfReader
from io import BytesIO

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

#Real gigachad Chunking
#To be implemented 
def chunk_doc(text: str, filename: str) -> list[str]:
    return[]

#plain text and markdown only (v1 minimal ingest API)
def decode_upload(raw: bytes) -> str:
    return raw.decode("utf-8", errors = "replace")
 

# chunk the plain text function
# return an array of chunk
def chunk_plaintext(raw: bytes, size: int = CHUNK_SIZE) -> list[dict]:
    text = decode_upload(raw)
    text = text.replace("\r\n", "\n")
    chunks: list[dict] = []
    i = 0
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        chunk = Chunk(
            chunk_id=f"text-{i:04d}",
            text=text[pos:end],
            kind="text",
            char_start=pos,
            char_end=end,
        )
        chunks.append(chunk.to_dict())
        i += 1
        pos = end
    return chunks

# Chunk pdf function
def chunk_pdf(raw: bytes) -> list[dict]:
    #import heavy depencencies when it's neccessary 
    reader = PdfReader(BytesIO(raw))
    chunks: list[dict] = []

    i = 0
    for page_index, page in enumerate(reader.pages):
        page_no = page_index + 1 # 1-based 
        text = (page.extract_text() or "").replace("\r\n","\n").strip()
        pieces = split_text(text, CHUNK_SIZE) if text else [""]

        if not pieces:
            pieces = [""]

        for piece in pieces:
            chunks.append(Chunk(
                chunk_id=f"pdf-{i:04d}",
                text=piece,
                kind="pdf_page",
                page=page_no,
            ).to_dict())
            i += 1
    return chunks


#TODO
def chunk_transcript(text: str) -> list[dict]:
    return

def ingest_file(raw: bytes, filename: str, mime_type: str):
    #accepts text, markdown, pdf 
    if not (filename.lower().endswith((".txt",".md", ".pdf")) or mime_type.startswith("text/") or mime_type == "application/pdf"):
        raise ValueError(f"v1 ingest supports .txt/.md only (got {filename!r})")
 

    artifact_id = str(uuid.uuid4())
    artifact_dir = softartifacts_root() / artifact_id
    artifact_dir.mkdir(parents = True, exist_ok = False)   #not accepting an artifact file with same artifact_id

    #safe_name to defend against path traversal attack
    safe_name = Path(filename).name or "upload.txt"
    (artifact_dir / safe_name).write_bytes(raw)

    chunks_row: list[dict] = []
    if (filename.lower().endswith(".pdf") or mime_type == "application/pdf"):
        chunks_row = chunk_pdf(raw)
    elif (filename.lower().endswith(".txt",".md") or mime_type.startswith("text/")):
        chunks_row = chunk_plaintext(raw)

    (artifact_dir / "chunk.json").write_text(
        json.dumps(chunks_row, ensure_ascii = False, indent = 2),
        encoding = "utf-8"
    )

    return {
        "artifactId": artifact_id,
        "sourceFile": safe_name,
        "mimeType": mime_type or "application/octet-stream",
        "status": "ready",
    }