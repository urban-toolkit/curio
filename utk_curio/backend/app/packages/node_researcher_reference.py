"""The Node Researcher reference draft (memo dev/89 §3 DOD profile, commit 9).

The canonical ``package.draft.apply`` request for the dev/89 proof of done: a
presentation-only post-it package with ONE template
(``node-researcher-note`` — ``engine: javascript``, ``editor: none``,
``hasCode: false``, no ports), one behavior key, one self-contained TSX
behavior source (``fixtures/node-researcher-note.tsx``), no Python
dependencies, no JS dependencies, no backend services.

Two consumers:

* **Tests** — the DOD regression drives the whole dev/89 stack with exactly
  this draft (build → review → promote → colored nodes).
* **Scaffold** — the reviewed reference the Package Builder can ground a
  real authoring run in (dev/89 §3.7's "reference fixture"), instead of
  inventing every implementation detail.

The same TSX is mirrored at
``frontend/urban-workflows/src/tests/fixtures/NodeResearcherNote.tsx`` so the
component itself has RTL coverage; the DOD test asserts the two files are
byte-identical (one truth, parity-enforced).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utk_curio.backend.app.packages.build_models import (
    PackageBuildRequest,
    parse_build_request,
)

PACKAGE_ID = "curio.researcher-notes"
TARGET = f"{PACKAGE_ID}@1"
TEMPLATE_ID = "node-researcher-note"
BEHAVIOR_KEY = "node-researcher-note"

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "node-researcher-note.tsx"
_FRONTEND_MIRROR_RELATIVE = (
    "frontend/urban-workflows/src/tests/fixtures/NodeResearcherNote.tsx"
)


def behavior_source() -> str:
    """The canonical TSX behavior source (the package's only code)."""
    return _FIXTURE_PATH.read_text(encoding="utf-8")


def frontend_mirror_path() -> Path:
    """The RTL-covered mirror of the fixture (parity asserted by the DOD test)."""
    # This module lives at utk_curio/backend/app/packages/, so parents[3] is
    # utk_curio/ (count carefully — the datasets-reorg `parents[N]` gotcha).
    return Path(__file__).resolve().parents[3] / _FRONTEND_MIRROR_RELATIVE


def reference_manifest() -> dict[str, Any]:
    """The draft manifest — schema-complete, presentation-only (dev/89 §3):
    no Python/JS dependencies, no ports, no code editor, no behaviorScript
    key (the packager stamps it when the compiled bundle lands)."""
    return {
        "id": PACKAGE_ID,
        "version": "1.0.0",
        "name": "Researcher Notes",
        "publisher": "Curio Package Builder",
        "description": (
            "Post-it style research notes: fixed agent-produced text rendered "
            "as safe markdown-lite on a configurable per-note color."
        ),
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [{
            "id": TEMPLATE_ID,
            "label": "Research note",
            "category": "visualization",
            "engine": "javascript",  # satisfies the manifest contract; the
            "editor": "none",        # behavior is presentation-only (no Run)
            "behavior": BEHAVIOR_KEY,
            "hasCode": False,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [],
        }],
    }


def reference_request_params(
    notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The raw ``package.draft.apply`` params. *notes* rows are
    ``{"title", "content", "color"}`` — each becomes a requested node with
    ``appearance.backgroundColor`` (palette name or six-digit hex)."""
    requested = []
    for note in notes or []:
        row: dict[str, Any] = {"templateId": TEMPLATE_ID}
        if note.get("title"):
            row["title"] = note["title"]
        if note.get("content") is not None:
            row["content"] = note["content"]
        if note.get("color"):
            row["appearance"] = {"backgroundColor": note["color"]}
        requested.append(row)
    return {
        "mode": "create",
        "target": TARGET,
        "manifest": reference_manifest(),
        "files": {
            f"sources/{TEMPLATE_ID}.tsx": {"text": behavior_source()},
            "README.md": {"text": (
                "# Researcher Notes\n\nPost-it style notes for agent-produced "
                "research text. Presentation-only: no execution, no ports, no "
                "backend.\n"
            )},
        },
        "behaviorEntries": [f"sources/{TEMPLATE_ID}.tsx"],
        "previewTemplates": [TEMPLATE_ID],
        "nodes": requested,
    }


def reference_build_request(
    notes: list[dict[str, Any]] | None = None,
) -> PackageBuildRequest:
    """The validated, typed form of the reference draft."""
    return parse_build_request(reference_request_params(notes))
