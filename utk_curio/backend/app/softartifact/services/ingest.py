#good luck reading the undescribable code =D
from __future__ import annotations

from .LLM_helper.chunk_schema import Chunk
from .LLM_helper.store import upsert_softartifact

import json, os, uuid
from pathlib import Path

from pypdf import PdfReader
from io import BytesIO

import re
from typing import Literal
TextProfile = Literal["transcript_a", "transcript_b", "text"]

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
 
# chunk the plain text function
# return an array of chunk
def _chunk_plaintext(text: str, size: int = CHUNK_SIZE) -> list[dict]:
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


def _text_profile(text: str, A_reg: any, B_reg: any) -> TextProfile:
    # distinguish what's kind of text is the raw:
    #text here is already stripped
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "text"

    # Scoring based on the regex
    # if AScore >= 1 -> the transcript is the 'a' version
    # if BScore >= 2 -> the transcript is the 'b' version
    AScore = BScore = 0
    for ln in lines:
        if A_reg.match(ln):
            AScore += 1
        elif B_reg.match(ln):
            BScore += 1

    if AScore >= 1: return "transcript_A"
    if BScore >= 2: return "transcript_B"
    
    return "text"

# HH:MM:SS → seconds
# helper function for chunk_transcript
def _ts(s: str) -> float: 
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)

# return chunks in transcript A
# chunk accordingly to the body of the transcript (time < 120 sec and less than 2500 words)
def _chunk_transcript_A(text: str, A_reg: any) -> list[dict]:
    lines = text.split('\n')
    turns = []
    time_diff_between_chunk = 25  # change this if you want to adjust the chunking size
    
    i = 0
    while i < len(lines):
        m = A_reg.match(lines[i].strip())
        if not m:
            i += 1; continue
        #identify speaker and time 
        speaker, t0 = m.group("speaker").strip(), _ts(m.group("t"))
        #text of that speaker
        buf = []; i += 1
        while i < len(lines):
            s = lines[i].strip()
            #if the line is nothing
            if not s:
                if buf: break
                i += 1; continue  
            
            if A_reg.match(lines[i].strip()): break;  # the end of the script of a speaker
            
            buf.append(s); i += 1
        
        if buf:
            turns.append((speaker, t0, " ".join(buf)))

    # after building `turns` as (speaker, t0, body)
    # loosen the chunk
    merged = []
    for speaker, t0, body in turns:
        if (
            merged
            and merged[-1][0] == speaker
            and t0 - merged[-1][1] <= time_diff_between_chunk  # gap from previous turn start; or track t_end
            and len(merged[-1][2]) + len(body) < 2000
        ):
            merged[-1] = (speaker, merged[-1][1], merged[-1][2] + " " + body)
        else:
            merged.append((speaker, t0, body))
    turns = merged

    res = []
    for i, (speaker, time0, body) in enumerate(turns):
        time1 = turns[i + 1][1] if i + 1 < len(turns) else time0
        res.append(Chunk(
            chunk_id=f"turn-{i:04d}", text=body, kind="transcript_turn",
            speaker=speaker, t_start=time0, t_end=max(time1, time0),
        ).to_dict())
    return res


def _chunk_transcript_B(text: str, B_reg: any) -> list[dict]:
    lines = text.split('\n')
    turns = []
    time_diff_between_chunk = 25  # change this if you want to adjust the chunking size


    #go through each line of text, adding [time: body] to turns array 
    for ln in lines:
        m = B_reg.match(ln.strip())
        if m:
            turns.append([_ts(m.group("t")), m.group("text").strip()])
    
    #guard against no text
    if not turns:
        return []
    
    merged = [[turns[0][0], turns[0][1], turns[0][0]]]  # start, text, end

    # chunking based on seconds and number of words been spoken
    for t, txt in turns[1:]:
        if t - merged[-1][2] <= time_diff_between_chunk and len(merged[-1][1]) + len(txt) < 2000:
            merged[-1][1] += " " + txt
            merged[-1][2] = t
        else:
            merged.append([t, txt, t])
    
    return [
        Chunk(
            chunk_id=f"turn-{i:04d}", text=txt, kind="transcript_turn",
            speaker="caption", t_start=s, t_end=e,
        ).to_dict()
        for i, (s, txt, e) in enumerate(merged)
    ]

def _chunk_text_file(raw, filename) -> tuple[list[dict], str]:
    # decode the raw into text
    # for feeding it into functions
    text = decode_upload(raw)
    text = text.replace("\r\n", "\n")

    # TEXT TRANSCRIPT regexes:
    # A:  [someone's name] 20:12:42
    #     No, really. Oh, I see more, the more tools, transcript, yes, now I see.
    # B:  20:13:26 you know, just to be safe, you have to
    # C: normal .txt file

    # A: [someone's name] 20:12:42
    A_reg = re.compile(
        r"^\[(?P<speaker>[^\]]+)\]\s+(?P<t>\d{1,2}:\d{2}:\d{2})\s*$"
    )
    # B: 20:13:26 required. Uh, anyway, if one fails, you have the other
    B_reg = re.compile(
        r"^(?P<t>\d{1,2}:\d{2}:\d{2})\s+(?P<text>.+?)\s*$"
    )

    if filename.lower().endswith(".md"):
        return _chunk_plaintext(text), "text"
    
    text_profile = _text_profile(text, A_reg, B_reg)

    if text_profile == "transcript_A":
        return _chunk_transcript_A(text, A_reg), "transcript"
    elif text_profile == "transcript_B":
        return _chunk_transcript_B(text, B_reg), "transcript"
    elif text_profile == "text":
        return _chunk_plaintext(text), "text"
    
    #fallback 
    return _chunk_plaintext(text), "text"
     
# Chunk pdf function
def _chunk_pdf(raw: bytes) -> list[dict]:
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

def ingest_file(raw: bytes, filename: str, mimetype: str):
    #accepts text, markdown, pdf 
    if not (filename.lower().endswith((".txt",".md", ".pdf")) or mimetype.startswith("text/") or mimetype == "application/pdf"):
        raise ValueError(f"v1 ingest supports .txt/.md/.pdf only (got {filename!r})")
 

    artifact_id = str(uuid.uuid4())
    artifact_dir = softartifacts_root() / artifact_id
    artifact_dir.mkdir(parents = True, exist_ok = False)   #not accepting an artifact file with same artifact_id

    #safe_name to defend against path traversal attack
    safe_name = Path(filename).name or "upload.txt"
    (artifact_dir / safe_name).write_bytes(raw)

    chunks_row: list[dict] = []
    kind = "text"  #default fallback
    if (filename.lower().endswith(".pdf") or mimetype == "application/pdf"):
        chunks_row = _chunk_pdf(raw)
        kind = "pdf"
    elif (filename.lower().endswith((".txt",".md")) or mimetype.startswith("text/")):
        chunks_row, kind = _chunk_text_file(raw,filename)

    upsert_softartifact({
        "artifact_id": artifact_id,
        "source_file": safe_name,
        "mimetype": mimetype or "application/octet-stream",
        "kind": kind
    }, chunks_row)

    # This if for debugging, can delete once hardned s
    (artifact_dir / "chunk.json").write_text(
        json.dumps(chunks_row, ensure_ascii = False, indent = 2),
        encoding = "utf-8"
    )

    return {
        "artifact_id": artifact_id,
        "sourceFile": safe_name,
        "mimetype": mimetype or "application/octet-stream",
        "kind": kind,
        "status": "ready",
    }
