"""A dashboard viewer's step that derives a file, as the deploy runs it.

The stack the exec-user job boots is the deploy's shape: fork isolation with
the curio-exec account, and sign-in on (``docker-compose.ci-exec-user.yml``).
An account's Python node, Draw, pinned with its own Shade, draws an overlay of
the committed street survey's first photo, as Image Segmentation does
(``curio_derived_file``), and the Simple View it feeds is pinned too. The
owner's play draws it red, in the account's media folder. A dashboard viewer
with no account picks green, and the run's step, which runs as curio-exec,
draws its overlay in a folder of the step's own (``media/kept/<name>/``),
which its row names. The viewer reads the green overlay through the link the
dashboard gives for that row, and the owner's red one is as it was.

Everything goes over HTTP to the stack's backend, as a browser's requests do:
nothing here imports from the project, and the job installs only pytest.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

SANDBOX_URL = os.environ.get("CURIO_LIVE_SANDBOX_URL", "").rstrip("/")
BACKEND_URL = os.environ.get("CURIO_E2E_BACKEND_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(
    not (SANDBOX_URL and BACKEND_URL),
    reason="needs the exec-user stack (CURIO_LIVE_SANDBOX_URL and CURIO_E2E_BACKEND_URL)",
)

SURVEY = "data.curio.storage-survey"
CODE = "curio.builtin/python-computation"
VIEW = "curio.builtin/vis-simple"
RUN_TOKEN_HEADER = "X-Curio-Run-Token"

#: Draw's code: one overlay of the survey's first photo, in the shade picked,
#: and a row naming it, with what was written and who wrote it.
DRAW_CODE = '''import hashlib
import io
import os

import pandas as pd
from PIL import Image

shade = [!! shade !!]
photos = curio_load_collection("data.curio.storage-survey")
photo = photos[photos["kind"] == "image"].iloc[0]
derived = curio_derived_file(photo["dataset_id"], photo["file_id"], 0, "png", kind="image", tag="seg")
buffer = io.BytesIO()
Image.new("RGB", (8, 8), {"red": (200, 30, 30), "green": (30, 200, 30)}[shade]).save(buffer, "PNG")
with open(derived["path"], "wb") as handle:
    handle.write(buffer.getvalue())
return pd.DataFrame([{
    "shade": shade, "sha256": hashlib.sha256(buffer.getvalue()).hexdigest(), "uid": os.getuid(),
    "dataset_id": derived["dataset_id"], "file_id": derived["file_id"], "kind": derived["kind"],
    "path": derived["path"], "thumbnail": derived["thumbnail"], "image_url": derived["image_url"],
}])
'''


def _call(method: str, path: str, body=None, headers=None, *, timeout: float = 600):
    """``(status, body bytes)`` of one request to the stack's backend."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        BACKEND_URL + path, data=data, method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _json(method: str, path: str, body=None, headers=None, *, expect: int = 200):
    status, raw = _call(method, path, body, headers)
    assert status == expect, f"{method} {path} answered {status}: {raw[:500]!r}"
    return json.loads(raw)


def _first_row(envelope: dict) -> dict:
    """The first row of a table as ``/get`` sends it: one list per column."""
    assert envelope.get("dataType") == "dataframe", str(envelope)[:500]
    return {column: values[0] for column, values in envelope["data"].items()}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _shade_widget() -> dict:
    return {
        "name": "shade", "type": "choice", "label": "Shade", "default": "red",
        "options": {"choices": ["red", "green"], "display": "radio"},
    }


def _node(node_id: str, node_type: str, x: int, content: str, widgets: list) -> dict:
    """A pinned node as the canvas saves it (``TrillGenerator``)."""
    return {
        "id": node_id, "type": node_type, "x": x, "y": 0, "in": "DEFAULT", "out": "DEFAULT",
        "goal": "", "content": content, "dashboardPinned": True,
        "metadata": {"keywords": [], "widgets": widgets},
    }


def _dashboard(token: str) -> str:
    """The account's dataflow: Draw, pinned with its Shade, feeding a pinned
    Simple View. Its id."""
    spec = {"dataflow": {
        "name": "Viewer media as curio-exec", "task": "", "description": "",
        "packages": [], "datasets": [],
        "nodes": [_node("draw", CODE, 0, DRAW_CODE, [_shade_widget()]), _node("view", VIEW, 700, "", [])],
        "edges": [{"id": "reactflow__edge-drawout-viewin", "source": "draw", "target": "view"}],
    }}
    created = _json("POST", "/api/projects", {"name": "Viewer media as curio-exec", "spec": spec},
                    {"Authorization": f"Bearer {token}"}, expect=201)
    return created["id"]


def _sign_up() -> str:
    name = f"viewer_media_{uuid.uuid4().hex[:10]}"
    body = _json("POST", "/api/auth/signup", {
        "name": name, "username": name, "password": f"Curio-live-{uuid.uuid4().hex}",
        "email": f"{name}@ci.invalid",
    }, expect=201)
    assert body.get("token"), body
    return body["token"]


def _as_played(code: str) -> str:
    """*code* as the canvas posts a Play of it (``PythonInterpreter.ts``,
    ``run_engine.play_indent``): every line indented as a function's body."""
    return "".join("    " + line + "\n" for line in code.split("\n"))


def _owners_play(token: str, project_id: str) -> dict:
    """The owner's Play of Draw, red, as the canvas sends it: the row it made."""
    owner = {"Authorization": f"Bearer {token}"}
    reply = _json("POST", "/processPythonCode", {
        "code": _as_played(DRAW_CODE.replace("[!! shade !!]", '"red"')), "nodeType": CODE,
        "nodeId": "draw", "dataflowId": project_id, "input": None,
    }, owner)
    assert reply.get("output", {}).get("path"), f"the owner's play made nothing: {str(reply)[:1500]}"
    query = urllib.parse.urlencode({"fileName": reply["output"]["path"]})
    return _first_row(_json("GET", f"/get?{query}", headers=owner))


def _viewers_run(project_id: str) -> str:
    """A viewer with no account picks green: the output the run's Draw step made."""
    started = _json("POST", f"/api/projects/{project_id}/dashboard/runs",
                    {"values": {"draw": {"shade": "green"}}}, expect=202)
    status, stream = _call(
        "GET", f"/api/projects/{project_id}/dashboard/runs/{started['runId']}/stream",
        headers={RUN_TOKEN_HEADER: started["token"]},
    )
    assert status == 200, stream[:500]
    events = []
    for block in stream.decode("utf-8").strip().split("\n\n"):
        kind = block.split("\n", 1)[0].removeprefix("event: ")
        events.append((kind, json.loads(block.split("data: ", 1)[1])))
    finished = [payload for kind, payload in events if kind == "step_finished" and payload.get("nodeId") == "draw"]
    assert finished and finished[0].get("output", {}).get("path"), f"the viewer's run made nothing: {events}"
    return finished[0]["output"]["path"]


def test_a_viewers_step_as_curio_exec_derives_in_its_own_folder_and_the_owners_file_stays():
    token = _sign_up()
    project_id = _dashboard(token)
    owners = _owners_play(token, project_id)

    made = _viewers_run(project_id)

    query = urllib.parse.urlencode({"fileName": made})
    row = _first_row(_json("GET", f"/api/projects/{project_id}/dashboard/outputs/get?{query}"))
    kept = urllib.parse.parse_qs(urllib.parse.urlsplit(row["image_url"]).query).get("kept", [None])[0]
    assert row["shade"] == "green" and row["file_id"] == owners["file_id"], row
    assert kept, f"the viewer's row names no folder of its step: {row['image_url']}"
    assert f"/media/kept/{kept}/" in row["path"], f"the viewer's step wrote outside its folder: {row['path']}"
    assert row["uid"] != 0 and row["uid"] == owners["uid"], f"the steps did not run as the execution account: {row}"

    links = _json("POST", f"/api/projects/{project_id}/dashboard/media", {
        "fileName": made, "files": [{"datasetId": row["dataset_id"], "fileId": row["file_id"], "kept": kept}],
    })["links"]
    assert len(links) == 1, links
    status, viewers = _call("GET", f"{links[0]['url']}?variant=original")
    assert status == 200 and _sha256(viewers) == row["sha256"], (status, viewers[:200])

    status, theirs = _call("GET", owners["image_url"], headers={"Authorization": f"Bearer {token}"})
    assert status == 200, theirs[:200]
    assert _sha256(theirs) == owners["sha256"] != row["sha256"], "the viewer's run wrote over the owner's overlay"
