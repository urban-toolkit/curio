# utk_curio/backend/app/softartifact/services/explain.py
from pathlib import Path

import json
# import your existing retrieve helper
from .LLM_helper.retrieve import search_chunks 
# reuse Curio's LLM helpers (already in api/routes.py)
from utk_curio.backend.app.api.routes import _resolve_llm_config, _call_llm

# Path to the system prompt template used to instruct the LLM on how to
# explain/summarize an artifact. Resolved relative to this file, going up
# 4 parent directories to reach the project root, then into llm-prompts/.
PROMPT_PATH = Path(__file__).resolve().parents[4] / "llm-prompts" / "softartifact_explain_prompt.txt"

# Fallback query used when the caller doesn't provide one, so retrieval
# still has something meaningful to search against.
DEFAULT_QUERY = (
    "Summarize the document: main themes, claims, named places, and policy priorities"
)


def _load_prompt(promt_path: any) -> str:
    """Read and return the system prompt text from disk."""
    return promt_path.read_text(encoding="utf-8")


def _format_passages(spans: list[dict]) -> str:
    """
    Turn a list of retrieved chunk/span dicts into a single numbered,
    human-readable string to hand to the LLM as context.

    Each span is expected to look like {"chunk_id": ..., "text": ...}.
    Spans with empty/missing text are skipped.
    """
    lines = []
    for i, s in enumerate(spans, start=1):
        # Fall back to a generated id like "c-1" if index is missing
        chunk_id = s.get("chunk_id", f"c-{i}")
        # Guard against None text, then strip whitespace
        text = (s.get("text") or "").strip()
        if text:
            # Format as "[1] (index)\n<text>" for easy citation by the LLM
            lines.append(f"[{i}] ({chunk_id})\n{text}")
    # Join all formatted passages with blank lines between them
    return "\n\n".join(lines)


def explain_artifact(artifact_id, query, top_k, source_file, context) -> dict:
    """
    Retrieve relevant passages for an artifact and ask the LLM to explain/
    summarize them based on the given query.

    Returns a dict containing the original query, the retrieved spans,
    and the LLM-generated explanation.
    """
    # Normalize the query: strip whitespace, fall back to DEFAULT_QUERY if empty
    q = (query or "").strip() or DEFAULT_QUERY

    # Retrieve the top-k most relevant chunks/spans for this artifact and query
    spans = search_chunks(artifact_id=artifact_id, query=q, top_k=top_k)

    # If nothing was retrieved, short-circuit and return an empty result
    # instead of calling the LLM with no context
    if not spans:
        return{
            "artifact_id": artifact_id,
            "query": query,
            "spans": [],
            "explanation": "the file is too small for any explanation"
        }
    
    # Format retrieved spans into a single text block for the LLM prompt
    passages = _format_passages(spans)
    # Build the user-facing portion of the prompt: which file this came from,
    # plus the formatted passages
    user_text = f"Source file: {source_file or 'document'}\n\nPassages:\n{passages} \n Context: {json.dumps(context or {}, indent = 2)}"

    # Load the system prompt (instructions for how the LLM should behave)
    system = _load_prompt(PROMPT_PATH)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]

    # Resolve which LLM/provider/model to use based on current config
    api_key, api_type, base_url, model = _resolve_llm_config()
    # Call the LLM with the constructed messages and get back the explanation text
    explanation = _call_llm(api_key, api_type, base_url, model, messages)

    # Return everything the caller needs: normalized query, raw spans used,
    # and the generated explanation
    return {
        "artifact_id": artifact_id,
        "query": q,
        "spans": spans,
        "explanation": explanation,
    }