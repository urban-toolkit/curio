from __future__ import annotations
from pathlib import Path

from .LLM_helper.retrieve import search_chunks, _load_chunk
from .explain import _format_passages, _load_prompt

from utk_curio.backend.app.api.routes import (
    _resolve_llm_config,
    _call_llm,
    _node_type_registry,
)

import json 


PROMPTS_DIR = Path(__file__).resolve().parents[4] / "llm-prompts"

DEFAULT_QUERIES = {
    "transform": "requirements metrics policy rules analysis steps datasets visualization",
    "expand": "additional scenarios branches what-if alternative data sources comparisons",
}
PROMPT_FILES = {
    "transform": "softartifact_transform_prompt.txt",
    "expand": "softartifact_expand_prompt.txt",
}


def _parse_proposal_json(llm_text: str) -> dict:
    """Return (proposal, rationale). proposal = { dataflow: { name, nodes, edges } }."""
    clean = llm_text.replace("```json","").replace("```","").strip()
    empty = {"dataflow": {"name": "", "nodes": "", "edges": ""}}

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        # how to deal with it though? TODO
        # model returned plain text instead of JSON
        return (
            {"dataflow": {"name": "", "nodes": [], "edges": []}},
            f"Model did not return JSON:\n{clean}",
        )
    
    #guard if json is not a dictionary 
    if not isinstance(parsed, dict):
        return empty, clean
    
    dataflow = parsed.get("dataflow", {})
    rationale = parsed.get("rationale", "")

    proposal = {
        "dataflow": {
            "name": dataflow.get("name") or "Proposed workflow",
            "nodes": dataflow.get("nodes") or [],
            "edges": dataflow.get("edges") or [],
        }
    }
    return proposal, rationale

    

# receive artifact, try to generate Trill.json based on artifact using LLM promt =D
def propose_trill(artifact_id: str, mode: str = "transform", *, context: object, top_k: int, source_file):
    #mode is transform as fallback
    mode = (mode or "transform").lower()
    if mode not in ("transform", "expand"):
        mode = "transform"

    # spans = search_chunks(query=DEFAULT_QUERIES[mode], artifact_id=artifact_id, top_k=top_k) 
    testing_spans = _load_chunk(artifactId = artifact_id)
    if not testing_spans:   
        return{
            "artifact_id": artifact_id,
            "proposal": "the file is too small for any transforming" 
        }
    
    passages = _format_passages(testing_spans)

    # registry → string for the prompt
    node_types = json.dumps(
        {
            t:{
                "in": entry.get("inputTypes", []),
                "out": entry.get("outputTypes", [])
            }
            for t, entry in _node_type_registry.items()
        }, indent = 2
    )
    
    #buidling user query
    parts = [
        f"Mode: {mode}",
        f"Source file: {source_file or '(unknown)'}",
        f"Retrieve query: {DEFAULT_QUERIES}",
        "",
        "Document chunks:",
        passages,
        "",
        "Valid node types (use ONLY these type strings; respect in/out):",
        node_types,
        "",
        "Current dataflow (live canvas; may be empty):",
        json.dumps(context or {"dataflow": {"nodes": [], "edges": []}}, indent=2),
    ]
    
    user_text = "\n".join(parts)
    
    system = _load_prompt(PROMPTS_DIR / PROMPT_FILES[mode])
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text}
    ]

    api_key, api_type, base_url, model = _resolve_llm_config()
    raw_text = _call_llm(api_key, api_type, base_url, model, messages)

    proposal, rationale = _parse_proposal_json(raw_text)
    
    return {
        "artifact_id": artifact_id,
        "spans": testing_spans,
        "proposal": proposal,
        "rationale": rationale
    }   