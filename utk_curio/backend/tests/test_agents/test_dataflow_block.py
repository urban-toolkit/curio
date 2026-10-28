"""Every run that writes code is given what its dataflow can use.

A chat run that can write a node's code (it holds ``node.content.write``, or
``node.create`` and its agent composes no notes: the Researcher's chat writes
notes, never code) and every delegated run that writes code (a node's content,
``node.content.generate``, or a package's, its three writing modes) gets one
block of at most 8,000 characters:

- **framed as the canvas context is**: a user message whose first line frames
  what follows as data, never part of the system turn, since a package's text
  can come from anyone;
- **what it holds**: the dataflow's datasets and models, each with the line
  that loads it, the names of the account's Node code keys (never a value),
  and the template of the node being written: its whole description, its
  starter and the functions its code can import, read from its package's
  modules and from those of the packages its package names in
  ``dependencies.packages``, listed under it;
- **what it leaves out**: other templates stay roster lines; a cut list says
  how many lines it left out and, when the run holds the tool that reads
  them, which tool that is.

``packages.resolve`` gives each package's functions and the packages it names
in ``dependencies.packages``. The preamble names no package's templates or
functions: those reach a run through the block.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth, _write_reader
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals
from utk_curio.backend.tests.test_agents import test_routes_solve as routes_solve
from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns
from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

REPO_ROOT = Path(__file__).resolve().parents[4]
BASE = REPO_ROOT / "agents" / "agent.curio.builtin@1"
PROVIDER = "utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn"
NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
DL = verified_rounds.DL

RASTERS = "ai.test.rasters@1"
SHADOW = "ai.test.shadow@1"
SHADE = "ai.test.shadow/shade"
#: Longer than the 140 characters a roster line keeps: only the block holds its end.
SHADE_DESCRIPTION = (
    "Casts the shadow of each building of its input onto the ground for one hour of the day, as "
    "minutes of shadow per cell, from heights in metres. Its code names the hour, from 0 to 23. "
    "THE-END-OF-THE-SHADE-DESCRIPTION"
)
SHADE_STARTER = "from shadow_lib import cast_shadow\n\nreturn cast_shadow(input_0, hour=12)\n"
SHADOW_LIB = (
    "def cast_shadow(heights, hour=12):\n"
    '    """The minutes of shadow each cell of heights gets at hour."""\n'
    "    return heights\n"
)
#: Another template of the dataflow: a roster line, never expanded in the block.
CALC_DESCRIPTION = "Adds two rasters. CALC-IS-ANOTHER-TEMPLATE"
ALGEBRA = (
    "def add_rasters(first, second, scale=1.0):\n"
    '    """Adds two rasters cell by cell, the sum scaled by scale."""\n'
    "    return first\n\n\n"
    "def undocumented_helper(value):\n"
    "    return value\n\n\n"
    "def _private_helper():\n"
    '    """Never listed: its name starts with an underscore."""\n'
    "    return None\n"
)
MODEL_ID = "imported.xa1b2c3d4e5f6"
OTHER_MODEL_ID = "imported.xb2c3d4e5f6a7"
KEY_NAME, KEY_HOST, KEY_VALUE = "parks_api", "api.parks.example", "pk-s3cr3t-v4lue-0123456789"


# --- What a test reads ---------------------------------------------------------


def _words() -> dict:
    """The words of the block, by section: what the runtime frames it with."""
    from utk_curio.backend.app.agents.domain import dataflow_block

    return dict(dataflow_block.words())


def _is_title_call(messages) -> bool:
    from utk_curio.backend.app.agents.application.turns import titles

    return bool(messages) and messages[0].get("content") == titles.title_prompt()


def _record(monkeypatch, reply):
    """Every provider call but the title's, in order, each answered by *reply*."""
    calls: list = []

    def _fake_run(config, messages, **kwargs):
        if _is_title_call(messages):
            return "Title"
        calls.append(messages)
        return reply(messages, len(calls))

    monkeypatch.setattr(PROVIDER, _fake_run)
    return calls


def _holding(messages, text) -> list:
    """The messages whose content holds *text*."""
    return [m for m in messages if text in str(m.get("content") or "")]


def _loader(dataset_id: str, fmt: str = "csv") -> str:
    """The line the Data Catalog gives a dataset, by its id."""
    from utk_curio.backend.app.datasets.domain.catalog_item import loader_snippet

    return loader_snippet(fmt, None, dataset_id=dataset_id)["code"]


def _model_loader(model_id: str) -> str:
    from utk_curio.backend.app.packages.service import model_loader_line

    return model_loader_line(model_id)


# --- A dataflow with a package's nodes, models, a key and datasets -----------------


def _manifest(package_id, templates, needs=None):
    return {
        "id": package_id, "version": "1.0.0", "name": package_id, "publisher": "Test",
        "description": "", "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [], "dependencies": {"packages": dict(needs or {}), "python": {}, "js": {}},
        "templates": templates, "createdAt": "2026-10-22T00:00:00Z",
    }


def _code_template(template_id, label, description, source):
    return {
        "id": template_id, "label": label, "category": "computation", "engine": "python",
        "editor": "code", "hasCode": True, "description": description,
        "inputPorts": [{"types": ["RASTER"], "cardinality": "[1,n]"}],
        "outputPorts": [{"types": ["RASTER"], "cardinality": "1"}],
        "source": source,
    }


def _write_packages(user_key, algebra=ALGEBRA):
    """Two packages in the account's store: the rasters package, whose module
    ``rasters_lib.algebra`` defines functions, and the shadow package, which
    names it in ``dependencies.packages``, so its node imports from both."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    packages = {
        RASTERS: (
            _manifest("ai.test.rasters", [_code_template("calc", "Calc", CALC_DESCRIPTION, "sources/calc.py")]),
            {"sources/calc.py": "from rasters_lib.algebra import add_rasters\n\nreturn add_rasters(input_0, input_1)\n",
             "sources/rasters_lib/__init__.py": "", "sources/rasters_lib/algebra.py": algebra},
        ),
        SHADOW: (
            _manifest("ai.test.shadow", [_code_template("shade", "Shade", SHADE_DESCRIPTION, "sources/shade.py")],
                      needs={RASTERS: "*"}),
            {"sources/shade.py": SHADE_STARTER, "sources/shadow_lib.py": SHADOW_LIB},
        ),
    }
    for dir_name, (manifest, files) in packages.items():
        folder = user_packages_dir(user_key) / dir_name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for path, text in files.items():
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_text(text, encoding="utf-8")


def _add_models(user_key, tmp_path):
    """Two models in the account's Model Catalog, as the Discovery Catalog adds one."""
    from utk_curio.backend.app.packages.service import install_downloaded_model, model_template

    for model_id, name in ((MODEL_ID, "Tree canopy"), (OTHER_MODEL_ID, "Facades")):
        files = tmp_path / f"incoming-{model_id}"
        files.mkdir()
        (files / "m.onnx").write_bytes(b"onnx")
        install_downloaded_model(user_key, files, {
            "id": model_id, "kind": "model", "name": name, "version": "1.0.0",
            "compatibility": {"major": 1}, "publisher": "org", "license": "MIT",
            "templates": [model_template("semantic-segmentation")],
            "model": {
                "type": "semantic-segmentation", "runtime": "onnx", "entry": "models/m.onnx",
                "labels": ["tree"], "input": {"width": 64, "height": 32, "dtype": "float32", "scale": 0.00392},
                "license": "MIT", "sizeBytes": 4,
            },
        })


def _install_dataset(client, token, project_id, dataset_id):
    r = client.post(f"/api/dataflows/{project_id}/datasets/install", json={"datasetId": dataset_id},
                    headers=_auth(token))
    assert r.status_code == 200, r.get_data(as_text=True)


def _shade_dataflow(client, user, token, tmp_path, *, algebra=ALGEBRA, coord=NB) -> dict:
    """A dataflow with one Shade node, its two packages, one of the account's
    two models, one of its two datasets, and a saved key; *coord* attached to
    the node."""
    from utk_curio.backend.app.users.connection_keys import default_store

    ukey = _user_dir_key(user)
    routes_proposals.TestNodeCreate()._write_builtin_package(ukey)
    _write_packages(ukey, algebra=algebra)
    _add_models(ukey, tmp_path)
    default_store().put(ukey, KEY_NAME, KEY_HOST, KEY_VALUE, "query:key")
    in_project = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="parks.csv")
    elsewhere = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="roads.csv")
    spec = {"dataflow": {
        "nodes": [{"id": "n1", "type": SHADE, "goal": "the shadow on the parks", "content": "", "x": 0, "y": 0}],
        "edges": [], "packages": [RASTERS, SHADOW, f"{MODEL_ID}@1"],
    }}
    pid = client.post("/api/projects", json={"name": "p", "spec": spec, "outputs": []},
                      headers=_auth(token)).get_json()["id"]
    _install_dataset(client, token, pid, in_project)
    client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=_auth(token))
    att = client.post(f"/api/agents/projects/{pid}/attachments",
                      json={"coord": coord, "target": {"kind": "node", "targetId": "n1"}},
                      headers=_auth(token)).get_json()["attachmentId"]
    return dict(pid=pid, att=att, ukey=ukey, in_project=in_project, elsewhere=elsewhere)


def _run(client, token, ctx, message="write it", context=None):
    body = {"message": message, **({"context": context} if context is not None else {})}
    r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/run", json=body,
                    headers=_auth(token))
    assert r.status_code == 200, r.get_json()
    return r


def _content_children(calls) -> list:
    """The calls that are a content mode's run: a delegated task of
    ``node.content.generate``, as its frame names it."""
    def _is_one(messages) -> bool:
        task = str(messages[-1].get("content") or "") if messages else ""
        frame = task.split("\n", 1)[0]
        return frame.startswith("[delegated task") and "capability node.content.generate" in frame

    return [messages for messages in calls if _is_one(messages)]


def _the_block(messages, dataset_id) -> dict:
    """The one message of a call that holds the dataflow's dataset line."""
    found = _holding(messages, _loader(dataset_id))
    assert len(found) == 1, (
        f"{len(found)} messages carry the dataflow's dataset with its line; a run that writes code "
        "gets one dataflow block"
    )
    return found[0]


# --- Which runs get it, and how it is framed -------------------------------------


class TestEveryRunThatWritesCodeGetsTheBlock:

    def test_a_chat_run_on_a_node_gets_one_block_framed_as_the_canvas_context(
        self, client, user_and_token, tmp_curio, tmp_path, monkeypatch
    ):
        user, token = user_and_token
        ctx = _shade_dataflow(client, user, token, tmp_path)
        calls = _record(monkeypatch, lambda messages, n: "Noted.")
        _run(client, token, ctx, context="Current Trill: {...}\n Node ID: n1")
        messages = calls[0]
        block = _the_block(messages, ctx["in_project"])
        # A user message before the canvas context, the user's message last:
        # what the run is asked comes after what it is given.
        assert block["role"] == "user"
        assert messages[-1] == {"role": "user", "content": "write it"}
        assert "Current Trill" in messages[-2]["content"]
        assert messages[-3] is block
        # Never part of the system turn, which the runtime owns.
        system = messages[0]
        assert system["role"] == "system" and _loader(ctx["in_project"]) not in system["content"]
        frame = _words()["frame"]
        assert "\n" not in frame and frame.startswith("[") and frame.endswith("]") and "context data" in frame
        assert block["content"].split("\n", 1)[0] == frame
        assert frame not in system["content"]
        assert len(block["content"]) <= 8_000

    def test_a_run_that_writes_no_code_gets_none(self, client, user_and_token, tmp_curio, tmp_path, monkeypatch):
        """An agent that only reads the dataflow gets no block, and neither does
        the Researcher's chat, which writes notes with node.create, never code,
        in the dataflow where the Node Builder's run gets one."""
        user, token = user_and_token
        ctx = _shade_dataflow(client, user, token, tmp_path)
        attached = []
        for coord in (_write_reader(user), "agent.curio.researcher@1"):
            client.post(f"/api/agents/projects/{ctx['pid']}/install", json={"coord": coord}, headers=_auth(token))
            attached.append(client.post(f"/api/agents/projects/{ctx['pid']}/attachments",
                                        json={"coord": coord, "target": {"kind": "node", "targetId": "n1"}},
                                        headers=_auth(token)).get_json()["attachmentId"])
        calls = _record(monkeypatch, lambda messages, n: "Noted.")
        _run(client, token, ctx)
        for att in attached:
            _run(client, token, dict(ctx, att=att))
        writer, reader_call, researcher_call = calls
        _the_block(writer, ctx["in_project"])
        for call in (reader_call, researcher_call):
            assert _holding(call, _loader(ctx["in_project"])) == []
            assert not _holding(call, _words()["frame"])

    def test_a_delegated_content_run_gets_the_block_before_its_task_and_the_model_cannot_write_it(
        self, client, user_and_token, tmp_curio, tmp_path, monkeypatch
    ):
        """The Node Builder hands the node's content to its content mode. The
        mode's run gets the block before its task, as the runtime composed it:
        a block the model writes into the request's inputs stays in the task,
        data like every other input."""
        user, token = user_and_token
        ctx = _shade_dataflow(client, user, token, tmp_path)
        forged = 'FORGED-BLOCK df = curio_load_data("data.forged.nowhere")'
        delegate = "```curio.v1\n" + json.dumps({"delegateRequest": {
            "capability": "node.content.generate",
            "inputs": {"nodeId": "n1", "intent": "the shadow at noon", "dataflowBlock": forged, "context": forged},
        }}) + "\n```"
        script = [delegate, "return cast_shadow(input_0, hour=12)", "The change awaits your review."]
        calls = _record(monkeypatch, lambda messages, n: script[min(n - 1, len(script) - 1)])
        _run(client, token, ctx)
        children = _content_children(calls)
        assert len(children) == 1, "the Node Builder handed its content mode no task"
        child = children[0]
        block = _the_block(child, ctx["in_project"])
        assert child[-2] is block and block["role"] == "user"
        assert block["content"].split("\n", 1)[0] == _words()["frame"]
        assert "FORGED-BLOCK" not in block["content"]
        assert [m for m in child if "FORGED-BLOCK" in str(m.get("content"))] == [child[-1]]
        # The template the mode writes for is the node's.
        assert SHADE_DESCRIPTION in block["content"]

    def _solve_with_the_blocks_loader(self, client, user, token, monkeypatch, *, verify):
        """An applied plan's data-loading node, its dataset in the dataflow,
        solved by a content mode that answers with the line the block gives
        that dataset, and with a made-up file when it gives none."""
        from utk_curio.backend.app.agents.infrastructure import providers

        harness = verified_rounds.TestVerifiedSolve()
        ctx = harness._setup(client, user, token, monkeypatch, dl_replies=[harness.LOADER], with_stats=False)
        _install_dataset(client, token, ctx["pid"], ctx["dataset_id"])
        inner = providers.run_chat_turn
        line = _loader(ctx["dataset_id"])
        children: list = []

        def _answer(config, messages, **kwargs):
            if not _content_children([messages]):
                return inner(config, messages, **kwargs)
            children.append(messages)
            if any(line in str(m.get("content")) for m in messages[:-1]):
                return f"{line}\nreturn df"
            return 'import pandas as pd\ndf = pd.read_csv("heat_tracts_2020.csv")\nreturn df'

        monkeypatch.setattr(PROVIDER, _answer)
        body = harness._solve(client, token, ctx, verify=verify)
        return ctx, body, children, harness

    def test_solve_hands_each_node_the_block_and_its_loader_line_passes_the_check(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        ctx, body, children, harness = self._solve_with_the_blocks_loader(client, user, token, monkeypatch, verify=True)
        assert children, "Solve asked the content mode for nothing"
        for messages in children:
            block = _the_block(messages, ctx["dataset_id"])
            assert messages[-2] is block and block["role"] == "user"
        load = body["results"][ctx["load"]]
        assert load["status"] == "solved" and load["verdict"] == "pass", load
        assert harness._node_content(ctx, ctx["load"]).startswith(_loader(ctx["dataset_id"]))

    def test_solve_without_verifying_hands_each_node_the_block_too(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        ctx, body, children, harness = self._solve_with_the_blocks_loader(client, user, token, monkeypatch, verify=False)
        assert children
        for messages in children:
            assert messages[-2] is _the_block(messages, ctx["dataset_id"])
        assert body["results"][ctx["load"]] == {"status": "solved"}
        assert harness._node_content(ctx, ctx["load"]).startswith(_loader(ctx["dataset_id"]))

    def test_the_per_node_solve_hands_its_content_mode_the_block(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        harness = verified_rounds.TestSolveNode()
        ctx = harness._setup(client, user, token, monkeypatch, content="",
                             child_replies=['df = curio_load_data("{DATASET}")\nreturn df'])
        _install_dataset(client, token, ctx["pid"], ctx["dataset_id"])
        harness._solve_node(client, token, ctx)
        children = _content_children(ctx["calls"])
        assert children, "the per-node Solve asked the content mode for nothing"
        for child in children:
            assert child[-2] is _the_block(child, ctx["dataset_id"])

    def test_validating_a_planned_node_hands_its_content_mode_the_block(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        ukey = _user_dir_key(user)
        routes_proposals.TestNodeCreate()._write_builtin_package(ukey, templates=verified_rounds.TEMPLATES)
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="heat.csv")
        body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
        pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        _install_dataset(client, token, pid, dataset_id)
        for coord in (DFB, NB):
            client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(f"/api/agents/projects/{pid}/attachments",
                          json={"coord": DFB, "target": {"kind": "canvas"}}, headers=_auth(token)).get_json()["attachmentId"]
        plan = {"goal": "heat", "nodes": [
            {"ref": "load", "nodeType": DL, "title": "Load", "intent": "load the heat data"}], "edges": []}
        replies = ["Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```",
                   f"{_loader(dataset_id)}\nreturn df"]
        calls = _record(monkeypatch, lambda messages, n: replies[min(n - 1, len(replies) - 1)])
        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec",
                            lambda endpoint, payload: {"stdout": [], "stderr": "",
                                                       "output": {"path": "art-1", "dataType": "dataframe"}})
        r = client.post(f"/api/agents/projects/{pid}/attachments/{att}/run", json={"message": "plan"}, headers=_auth(token))
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        client.post(f"/api/agents/projects/{pid}/attachments/{att}/proposals/{proposal['proposalId']}/apply-node",
                    json={"ref": "load"}, headers=_auth(token))
        r = client.post(f"/api/agents/projects/{pid}/attachments/{att}/validate-node",
                        json={"ref": "load"}, headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        routes_solve.TestStreamedSolve()._sse_events(r)
        children = _content_children(calls)
        assert children, "validating the node asked the content mode for nothing"
        for child in children:
            assert child[-2] is _the_block(child, dataset_id)


# --- What it holds ---------------------------------------------------------------


class TestWhatTheBlockHolds:

    def _block(self, client, user, token, tmp_path, monkeypatch, **dataflow) -> tuple[str, dict, list]:
        ctx = _shade_dataflow(client, user, token, tmp_path, **dataflow)
        calls = _record(monkeypatch, lambda messages, n: "Noted.")
        _run(client, token, ctx)
        return _the_block(calls[0], ctx["in_project"])["content"], ctx, calls[0]

    def test_the_dataflows_datasets_and_models_with_their_lines_and_the_keys_by_name(
        self, client, user_and_token, tmp_curio, tmp_path, monkeypatch
    ):
        user, token = user_and_token
        block, ctx, messages = self._block(client, user, token, tmp_path, monkeypatch)
        # The dataset in this dataflow, with its line; not the account's other one.
        assert _loader(ctx["in_project"]) in block
        assert ctx["elsewhere"] not in block
        # The model this dataflow has, with its line; not the account's other one.
        assert _model_loader(MODEL_ID) in block
        assert OTHER_MODEL_ID not in block
        # The key by its name and host; its value nowhere in the run.
        assert KEY_NAME in block and KEY_HOST in block
        assert f'curio_secret("{KEY_NAME}")' in block
        assert not _holding(messages, KEY_VALUE)

    def test_the_template_being_written_with_its_description_its_starter_and_the_functions_it_can_import(
        self, client, user_and_token, tmp_curio, tmp_path, monkeypatch
    ):
        user, token = user_and_token
        block, ctx, messages = self._block(client, user, token, tmp_path, monkeypatch)
        assert SHADE in block
        # Its whole description: a roster line keeps 140 characters of it.
        assert SHADE_DESCRIPTION in block and len(SHADE_DESCRIPTION) > 140
        assert SHADE_STARTER.strip() in block
        # The functions its code can import, read from its package's modules
        # and from those of the package it names in dependencies.packages,
        # each with its module and its docstring's first paragraph.
        own = "shadow_lib.cast_shadow(heights, hour=12)"
        needed = "rasters_lib.algebra.add_rasters(first, second, scale=1.0)"
        for call in (own, needed, "rasters_lib.algebra.undocumented_helper(value)"):
            assert call in block, call
        assert "The minutes of shadow each cell of heights gets at hour." in block
        assert "Adds two rasters cell by cell, the sum scaled by scale." in block
        assert "_private_helper" not in block
        # Listed under the template, after its starter.
        assert block.index(SHADE) < block.index(SHADE_STARTER.strip()) < block.index(own)
        # Another template of the dataflow is a roster line, never expanded here.
        assert "CALC-IS-ANOTHER-TEMPLATE" not in block
        assert len(block) <= 8_000

    def test_a_template_with_more_functions_than_fit_keeps_its_starters_and_names_the_tool_that_reads_the_rest(
        self, client, user_and_token, tmp_curio, tmp_path, monkeypatch
    ):
        """The Node Builder holds packages.resolve, so its cut list names it."""
        user, token = user_and_token
        many = "".join(
            f'def scale_{i:03d}(raster, factor={i}):\n    """Scales a raster by {i}, cell by cell, and keeps its grid."""\n'
            "    return raster\n\n\n"
            for i in range(150)
        )
        block, ctx, _ = self._block(client, user, token, tmp_path, monkeypatch, algebra=ALGEBRA + "\n\n" + many)
        assert len(block) <= 8_000
        # The function its starter imports comes first and is never cut.
        assert "shadow_lib.cast_shadow(heights, hour=12)" in block
        assert 0 < len(re.findall(r"rasters_lib\.algebra\.scale_\d{3}\(", block)) < 150
        # cast_shadow, add_rasters, undocumented_helper and the 150 scale_ functions.
        shown = len(re.findall(r"^- (?:shadow_lib|rasters_lib\.algebra)\.\w+\(", block, re.M))
        cut = block.split(_words()["left-out"], 1)
        assert len(cut) == 2, "the block left functions out and says nothing of them"
        assert re.search(rf"\b{153 - shown}\b[^\n]*packages\.resolve", cut[1]), cut[1]


class TestTheLayout:
    """The block's layout from its rows, at most 8,000 characters."""

    def _rows(self, functions=300, datasets=120):
        from utk_curio.backend.app.agents.domain import dataflow_block as block

        listed = [block.Function(module="rasters_lib.algebra", name=f"scale_{i:03d}", call=f"scale_{i:03d}(raster)",
                                 doc=f"Scales a raster by {i}, cell by cell, and keeps its grid.") for i in range(functions)]
        listed.append(block.Function(module="rasters_lib.algebra", name="add_rasters",
                                     call="add_rasters(first, second, scale=1.0)", doc=""))
        template = block.Template(
            id="ai.test.rasters/calc", label="Calc", description="Adds two rasters.",
            starter="from rasters_lib.algebra import add_rasters\n\nreturn add_rasters(input_0, input_1)\n",
            language="python", functions=tuple(listed),
        )
        rows = [block.Dataset(id=f"data.test.d{i:03d}", title=f"Dataset {i}", format="csv",
                              loader=f'df = curio_load_data("data.test.d{i:03d}")') for i in range(datasets)]
        return block, template, rows

    def test_it_keeps_to_its_cap_and_says_how_many_it_left_out_and_which_tool_reads_them(self):
        block, template, rows = self._rows()
        tools = frozenset({"catalog.search", "models.search", "packages.resolve"})
        text = block.layout(datasets=rows, models=(), keys=(), template=template, tools=tools)
        assert len(text) <= block.MAX_CHARS == 8_000
        assert text.split("\n", 1)[0] == block.words()["frame"]
        # The function the starter imports is never cut, undocumented as it is.
        assert "rasters_lib.algebra.add_rasters(first, second, scale=1.0)" in text
        functions = len(re.findall(r"^- rasters_lib\.algebra\.scale_\d{3}\(", text, re.M))
        datasets = len(re.findall(r'^- data\.test\.d\d{3} ', text, re.M))
        assert functions < 300 and datasets < 120
        left = text.split(block.words()["left-out"], 1)[1]
        assert re.search(rf"\b{300 - functions}\b[^\n]*packages\.resolve", left), left
        assert re.search(rf"\b{120 - datasets}\b[^\n]*catalog\.search", left), left

    def test_a_run_without_the_tools_is_told_how_many_and_no_tool(self):
        block, template, rows = self._rows()
        text = block.layout(datasets=rows, models=(), keys=(), template=template, tools=frozenset())
        assert len(text) <= 8_000
        left = text.split(block.words()["left-out"], 1)[1]
        functions = len(re.findall(r"^- rasters_lib\.algebra\.scale_\d{3}\(", text, re.M))
        assert re.search(rf"\b{300 - functions}\b", left)
        assert "packages.resolve" not in text and "catalog.search" not in text

    def test_what_fits_leaves_nothing_out(self):
        block, template, rows = self._rows(functions=3, datasets=2)
        text = block.layout(datasets=rows, models=(), keys=(), template=template, tools=frozenset())
        assert block.words()["left-out"] not in text
        assert len(re.findall(r"^- rasters_lib\.algebra\.scale_\d{3}\(", text, re.M)) == 3
        assert text.count("curio_load_data(") == 2


# --- packages.resolve and the preamble -------------------------------------------


class TestPackagesResolveGivesFunctions:
    UKEY = "42"
    PID = "proj-pkg"

    def test_each_package_with_its_functions_and_the_packages_it_names(self, tmp_curio):
        from utk_curio.backend.app.agents.application import tools

        projects_storage.write_spec(self.UKEY, self.PID, {
            "dataflow": {"name": "wf", "nodes": [], "edges": [], "packages": []},
        })
        status, text = tools.execute_read_tool(
            "packages.resolve", user_key=self.UKEY, project_id=self.PID, target=None,
            params={"dirNames": ["model.scout.deep-umbra@1", "curio.scout@1"]},
        )
        assert status == "ok", text
        report = json.loads(text)  # whole: never cut mid-text
        rows = {row["dirName"]: row for row in report["packages"]}
        umbra, scout = rows["model.scout.deep-umbra@1"], rows["curio.scout@1"]
        # The packages its manifest names, which adding it adds.
        assert umbra.get("packageDeps") == {"curio.scout@1": "*"}, umbra
        assert scout.get("packageDeps") == {}, scout
        # Each module's public functions: the call and its docstring's first paragraph.
        modules = {row["module"]: row for row in umbra.get("functions") or []}
        assert "deep_umbra.node_outputs" in modules, sorted(modules)
        shadow = next(f for f in modules["deep_umbra.node_outputs"]["functions"] if f["name"] == "accumulated_shadow")
        assert shadow["call"] == "accumulated_shadow(value, season, model, output_file)"
        assert shadow["doc"].startswith("The accumulated shadow of the heights")
        algebra = {f["name"] for row in scout["functions"] if row["module"] == "scout_rasters.raster_algebra"
                   for f in row["functions"]}
        assert {"raster_calculate", "raster_statistics"} <= algebra
        assert not any(f["name"].startswith("_") for row in scout["functions"] for f in row["functions"])
        contract = tools.REGISTRY["packages.resolve"].description
        assert "functions" in contract and "dependencies.packages" in contract


def _shipped_package_ids() -> list[str]:
    ids = []
    for manifest in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        package_id = json.loads(manifest.read_text(encoding="utf-8"))["id"]
        if package_id != "curio.builtin":
            ids.append(package_id)
    return ids


def test_the_preamble_names_no_packages_templates_or_functions():
    """The preamble every agent reads is Curio's own: of the templates it names,
    each is the built-in package's, and it names no other package Curio ships
    and no function a package's modules define. A package's templates and
    functions reach a run that writes one of its nodes through the dataflow
    block, from its manifest and its modules."""
    from utk_curio.backend.app.agents.domain import agent_text
    from utk_curio.backend.app.packages.domain.function_nodes import read_functions
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_files

    # The pages the preamble includes and the skills it places, and theirs.
    preamble = agent_text.page_file("default_preamble.md")
    files = {preamble}
    queue = [preamble.read_text(encoding="utf-8")]
    while queue:
        text = queue.pop()
        found = [BASE / page for page in re.findall(r"\{\{include:([^{}]+)\}\}", text)]
        found += [REPO_ROOT / "skills" / name / "SKILL.md" for name in re.findall(r"\{\{skill:([^{}]+)\}\}", text)]
        for file in found:
            if file not in files:
                files.add(file)
                queue.append(file.read_text(encoding="utf-8"))
    names = {file.relative_to(REPO_ROOT).as_posix() for file in files}
    assert {"skills/scenarios/SKILL.md", "skills/node-functions/SKILL.md"} <= names, sorted(names)
    assert len([name for name in names if name.startswith("skills/")]) == 16, sorted(names)
    for file in sorted(files):
        named = set(re.findall(r"\{\{template\.label:([^/{}]+)/", file.read_text(encoding="utf-8")))
        assert named <= {"curio.builtin"}, f"{file.name} names templates of {sorted(named - {'curio.builtin'})}"
    rendered = agent_text.render(preamble)
    for package_id in _shipped_package_ids():
        assert not re.search(rf"(?<![\w.]){re.escape(package_id)}(?![\w-])", rendered), package_id
    for folder in sorted(path.parent for path in (REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = load_package_manifest(folder)
        for module, path in module_files(folder, manifest):
            for function in read_functions(path.read_text(encoding="utf-8"), module):
                assert f"{function.name}(" not in rendered, f"{manifest.dir_name}: {module}.{function.name}"
