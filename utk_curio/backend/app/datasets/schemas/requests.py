"""Parsers that normalize dataset-catalog request params into service inputs.

Live outputs are the current execution outputs the frontend holds before the
project manifest is saved. They arrive either base64-encoded on the query string
(GET catalog/preview/download) or as a JSON array in a POST body (publish); both
normalize to the same ``[{node_id, filename, data_type?}]`` shape the service
consumes.
"""

from __future__ import annotations

import base64
import json


def normalize_live_output_entry(raw: dict) -> dict | None:
    node_id = raw.get("node_id") or raw.get("nodeId")
    filename = raw.get("filename")
    if not node_id or not filename:
        return None
    entry: dict = {"node_id": str(node_id), "filename": str(filename)}
    data_type = raw.get("data_type") or raw.get("dataType")
    if data_type:
        entry["data_type"] = str(data_type)
    return entry


def _normalize_entries(raw: list) -> list[dict] | None:
    """Normalize a list of raw refs, dropping non-dicts and incomplete entries."""
    entries = [entry for o in raw if isinstance(o, dict)
               for entry in [normalize_live_output_entry(o)] if entry]
    return entries or None


def parse_live_outputs(raw_live: str | None) -> list[dict] | None:
    """Decode a base64-encoded JSON array of live-output refs (query-string form)."""
    if not raw_live:
        return None
    try:
        decoded = base64.b64decode(raw_live.encode()).decode("utf-8")
        parsed = json.loads(decoded)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(parsed, list):
        return None
    return _normalize_entries(parsed)


def normalize_live_outputs_list(raw: list | None) -> list[dict] | None:
    """Normalize a decoded JSON array of live-output refs (POST-body form)."""
    if not raw or not isinstance(raw, list):
        return None
    return _normalize_entries(raw)
