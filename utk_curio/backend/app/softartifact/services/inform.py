# utk_curio/backend/app/softartifact/services/ingest.py
#the design is pretty similar to explain.py in the same folder, and uses it function to =D
from __future__ import annotations

from pathlib import Path

from .retrieve import search_chunks 
from .explain import _format_passages, _load_prompt
from utk_curio.backend.app.api.routes import _resolve_llm_config, _call_llm

import json

PROMPT_PATH = Path(__file__).resolve().parents[4] / "llm-prompts" / "softartifact_inform_prompt.txt"

INFORM_QUERY = (
    "data requirements, metrics, named places, neighborhoods, "
    "policy rules, and analysis steps mentioned in the document"
)

def _parse_inform_json(llm_text: str) -> dict:
    clean = llm_text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # model returned plain text instead of JSON
        return {
            "guidance": clean,
            "suggestions": {"subtask": "", "recommendedNodes": []},
        }

#entry point
def inform_artifact(artifactId: str, top_k: str, context: str, source_file: str):
    spans = search_chunks(artifactId=artifactId, query = INFORM_QUERY, top_k = top_k)
    if not spans:
        return{
            "artifactId": artifactId,
            "explanation": "the file is too small for anything useful",
            "spans": [],
        }
    
    passages = _format_passages(spans)
    user_text = f"Passages: {passages} context: {context} sourceFile: {source_file}"
    
    system = _load_prompt(PROMPT_PATH)  #read the promt from the promt path
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text}
    ]

    api_key, api_type, base_url, model = _resolve_llm_config()
    explanation = _call_llm(api_key, api_type, base_url, model, messages)

    parsed = _parse_inform_json(explanation);

    return {
        "artifactId": artifactId,
        "spans": spans,
        "guidance": parsed.get("guidance", "there's no guidance"),
        "suggestions": parsed.get("suggestions", "there's no suggestion")
    }   
