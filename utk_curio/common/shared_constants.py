"""The constants the browser and the server share, read from the JSON files the
frontend imports.

``frontend/urban-workflows/src/contracts/`` holds one file per vocabulary or
table both sides must agree on: why a render drew nothing
(``renderCauses.json``), why a node's repair loop stopped
(``solveStopReasons.json``), the categories an agent manifest can declare
(``agentCategories.json``), a note's palette and inks (``noteColors.json``),
what a grammar node calls its inputs and the one view an Autark node draws
(``autkGrammar.json``), what a visualization node does with its input by
itself (``visDefaults.json``), the words of a Data Pool's modes and a
Simple View's image column (``nodeSettings.json``), and the widgets a dashboard's
viewer never changes and the header a viewer's run is followed with
(``dashboardRuns.json``). The frontend imports each file; the backend
reads it here. The folder sits in the frontend's source, so the Docker image's
frontend build and the Jest suite, which have no Python, read it where it is;
a clone, the Docker image and a pip install, whose package carries the
frontend's source, keep it beside this module's folder.

A file is read as ``JSON.parse`` reads it, except that an object naming one
key twice raises, where both would keep the last value and say nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The folder of the shared files, in a clone, the Docker image and a pip install.
CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "frontend" / "urban-workflows" / "src" / "contracts"


class SharedConstantsError(ValueError):
    """A shared file that is not JSON, or that names one key twice."""


def _one_value_per_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise SharedConstantsError(f"the key {key!r} is given twice")
        found[key] = value
    return found


def _no_constant(name: str):
    raise SharedConstantsError(f"{name} is not JSON")


def parse(text: str) -> Any:
    """*text*, parsed as ``JSON.parse`` parses it, refusing a key given twice."""
    return json.loads(text, object_pairs_hook=_one_value_per_key, parse_constant=_no_constant)


def read(name: str) -> Any:
    """``<name>.json`` from :data:`CONTRACTS_DIR`, parsed afresh."""
    path = CONTRACTS_DIR / f"{name}.json"
    try:
        return parse(path.read_text(encoding="utf-8"))
    except SharedConstantsError as exc:
        raise SharedConstantsError(f"{path}: {exc}") from exc
