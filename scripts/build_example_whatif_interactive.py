#!/usr/bin/env python3
"""Write ``WhatIfShadowsInteractive``, the version of ``WhatIfShadows`` whose
"Towers removed" scenario edits its buildings in an Interaction node.

The original removes SCOUT's 15 high-rise buildings in a Data Transformation
node's code. Here an Interaction node holds that removal as its edit log, one
entry, so the same results come out; on the node's map more buildings can be
picked and removed, raised or lowered, and Update results runs the
rasterizer, the shadow model, the comparison and the change map again.
Everything else is the original's, with new ids, so the two never share a
node.

    python scripts/build_example_whatif_interactive.py

AUTHORING-ONLY tooling. It is not imported at runtime.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATAFLOWS = REPO / "docs" / "examples" / "dataflows"
SOURCE = "WhatIfShadows"
COPY = "WhatIfShadowsInteractive"
INTERACTION = "curio.builtin/edit-features"
LABEL = "SCOUT's high-rise case"
#: The first lines of the code an Interaction node writes (``EDIT_CODE_NOTE``
#: in ``utils/editFeatures/editFeatures.ts``).
NOTE = (
    "# Edit Features writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
)


def removed_ids(code: str) -> list[int]:
    match = re.search(r"REMOVED = \[([^\]]*)\]", code)
    if not match:
        raise SystemExit(f"{SOURCE}: no REMOVED list in the Towers removed transformation")
    return [int(x) for x in match.group(1).split(",")]


def interaction_node(transformation: dict) -> dict:
    """The Interaction node standing where the transformation stood."""
    ids = removed_ids(transformation["content"])
    edit = {"op": "remove", "ids": ids, "label": LABEL}
    line = '    {"op": "remove", "ids": [' + ", ".join(str(i) for i in ids) + f'], "label": {json.dumps(LABEL)}' + "},\n"
    code = NOTE + "return curio_edit_features(input_0, [\n" + line + '], key="building_id")\n'
    return {
        "id": transformation["id"],
        "type": INTERACTION,
        "x": transformation["x"],
        "y": transformation["y"],
        "title": "Interaction - Towers removed",
        "content": code,
        "out": "DEFAULT",
        "in": "DEFAULT",
        "goal": (
            "Edit the buildings for this scenario: SCOUT's high-rise case removes 15 towers. "
            "Pick more on the map to remove them, or raise and lower them, then Update results."
        ),
        "metadata": {"keywords": [], "editFeatures": {"key": "building_id", "edits": [edit]}},
    }


def build() -> Path:
    flow = json.loads((DATAFLOWS / f"{SOURCE}.json").read_text(encoding="utf-8"))
    dataflow = flow["dataflow"]
    towers = [
        n for n in dataflow["nodes"]
        if n["type"].split("@")[0] == "curio.builtin/data-transformation" and "REMOVED = [" in (n.get("content") or "")
    ]
    if len(towers) != 1:
        raise SystemExit(f"{SOURCE}: expected one transformation removing the towers, found {len(towers)}")
    dataflow["nodes"] = [interaction_node(n) if n is towers[0] else n for n in dataflow["nodes"]]
    text = json.dumps(flow, indent=2, ensure_ascii=False)
    for node in dataflow["nodes"]:
        text = text.replace(node["id"], str(uuid.uuid5(uuid.NAMESPACE_URL, f"{COPY}/{node['id']}")))
    flow = json.loads(text)
    flow["dataflow"]["name"] = COPY
    if flow["dataflow"].get("provenance_id") == SOURCE:
        flow["dataflow"]["provenance_id"] = COPY
    out = DATAFLOWS / f"{COPY}.json"
    out.write_text(json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    print("wrote", build().relative_to(REPO))
