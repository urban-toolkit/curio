"""dev/134: the owner's `e72c7080`, reproduced and closed.

That project's chat said *Solved 7 of 7 plan nodes* in twelve seconds, and on
disk three nodes held the literal sentence ``not controllable`` as their content
(a merge-flow, a data-pool and an autk-grammar) while the vis-vega node held a
document that dev/129's own validator calls invalid. Every scripted reply below
is what the field log recorded, so the test fails if the write gate is ever
routed around again.
"""

from __future__ import annotations

import json

from utk_curio.backend.tests.test_agents import test_routes as _tr
from utk_curio.backend.tests.test_agents.test_verified_rounds import TEMPLATES as _CODE_TEMPLATES

#: The four kinds the owner's plan used, declared the way the shipped manifest
#: declares them — a document carries ``hasGrammar`` + ``grammarId``, and a
#: wired box has ``editor: "none"`` with an input port (dev/134's derivation).
TEMPLATES = _CODE_TEMPLATES + [
    {"id": "merge-flow", "label": "Merge Flow", "category": "flow", "engine": "python",
     "editor": "none", "hasCode": False, "description": "Combine flows.",
     "containerStyle": {"noContent": True},
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "data-pool", "label": "Data Pool", "category": "data", "engine": "python",
     "editor": "none", "hasCode": False, "description": "Store data for interactions.",
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}],
     "outputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "autk-grammar", "label": "Autark", "category": "vis_grammar", "engine": "python",
     "editor": "grammar", "hasCode": False, "hasGrammar": True,
     "grammarId": "autk-grammar", "description": "Render a map.",
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "[0,1]"}],
     "outputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "[0,1]"}]},
    {"id": "vis-vega", "label": "Vega-Lite", "category": "vis_grammar", "engine": "python",
     "editor": "grammar", "hasCode": False, "hasGrammar": True,
     "grammarId": "vega-lite", "description": "Render a chart.",
     "inputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}],
     "outputPorts": [{"types": ["DATAFRAME", "GEODATAFRAME"], "cardinality": "1"}]},
]

_auth = _tr._auth

DFB = "agent.dataflow-builder@1.0.0"
NCB = "agent.node-content-builder@1.0.0"
DL = "curio.builtin/data-loading"
MERGE = "curio.builtin/merge-flow"
POOL = "curio.builtin/data-pool"
AUTK = "curio.builtin/autk-grammar"
VEGA = "curio.builtin/vis-vega"

#: The reply the field log recorded for all three of those nodes.
NOT_CONTROLLABLE = "not controllable"

#: The owner's Vega document, verbatim: `'else'` inside an encoding condition.
OWNERS_VEGA = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": {"type": "bar", "cursor": "pointer"},
    "encoding": {
        "x": {"field": "density", "type": "quantitative"},
        "y": {"field": "neighborhood", "type": "nominal", "sort": "-x"},
        "color": {
            "field": "interacted", "type": "nominal",
            "condition": {"test": "datum.interacted === '1'", "value": "red",
                          "else": "steelblue"},
        },
    },
})

VALID_VEGA = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": {"type": "bar", "cursor": "pointer"},
    "encoding": {
        "x": {"field": "density", "type": "quantitative"},
        "y": {"field": "community", "type": "nominal", "sort": "-x"},
        "color": {"condition": {"test": "datum.interacted === '1'", "value": "red"},
                  "value": "steelblue"},
    },
})

VALID_AUTK = json.dumps({
    "map": {"layerRefs": [{"dataRef": "upstream", "isPick": True, "isColorMap": True}],
            "initialView": {"center": [-87.63, 41.88], "zoom": 11}},
})

LOADER = 'import pandas as pd\nreturn pd.DataFrame({"community": ["Loop"], "density": [1.0]})'


class _Harness:
    """The owner's plan: a loader, a merge, a pool, an AUTK map and a chart."""

    def __init__(self, client, user, token, monkeypatch, *, replies):
        from utk_curio.backend.app.projects.services import _user_dir_key

        self.client, self.token = client, token
        self.ukey = _user_dir_key(user)
        _tr.TestNodeCreate()._write_builtin_package(self.ukey, templates=TEMPLATES)
        body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
                "outputs": []}
        self.pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        for coord in (DFB, NCB):
            client.post(f"/api/agents/projects/{self.pid}/install", json={"coord": coord},
                        headers=_auth(token))
        self.att = client.post(
            f"/api/agents/projects/{self.pid}/attachments",
            json={"coord": DFB, "target": {"kind": "canvas"}}, headers=_auth(token),
        ).get_json()["attachmentId"]
        plan = {"goal": "compare chicago neighborhoods", "nodes": [
            {"ref": "load", "nodeType": DL, "title": "Boundaries",
             "intent": "load the community areas"},
            {"ref": "merge", "nodeType": MERGE, "title": "Merge",
             "intent": "combine the sources"},
            {"ref": "pool", "nodeType": POOL, "title": "Pool",
             "intent": "store the joined data for interactions"},
            {"ref": "map", "nodeType": AUTK, "title": "Density Map",
             "intent": "render a map coloured by density"},
            {"ref": "chart", "nodeType": VEGA, "title": "Density Ranking",
             "intent": "rank neighborhoods by density"},
        ], "edges": [
            {"from": "load", "to": "merge"},
            {"from": "merge", "to": "pool"},
            {"from": "pool", "to": "map"},
            {"from": "pool", "to": "chart"},
        ]}
        plan_reply = "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"
        self.frames: list = []
        script = dict(replies)

        def _fake_run(config, messages, **kwargs):
            from utk_curio.backend.app.agents import services as services_mod

            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            frame = messages[-1].get("content") or ""
            if "[delegated task" not in frame:
                return plan_reply
            self.frames.append(frame)
            for node_type, reply in script.items():
                if f'"nodeType": "{node_type}"' in frame:
                    return reply
            return LOADER

        monkeypatch.setattr(
            "utk_curio.backend.app.agents.services.run_chat_completion", _fake_run
        )
        self.exec_payloads: list = []

        def _exec(endpoint, payload):
            self.exec_payloads.append(payload)
            return {"stdout": [], "stderr": "",
                    "output": {"path": f"art-{len(self.exec_payloads)}",
                               "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        r = client.post(f"/api/agents/projects/{self.pid}/attachments/{self.att}/run",
                        json={"message": "plan it"}, headers=_auth(token))
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        applied = client.post(
            f"/api/agents/projects/{self.pid}/attachments/{self.att}/proposals/"
            f"{proposal['proposalId']}/apply", headers=_auth(token),
        ).get_json()
        self.ids = {
            str(n["type"]): n["id"] for n in applied["appliedGraph"]["nodes"]
        }

    def solve(self):
        return self.client.post(
            f"/api/agents/projects/{self.pid}/attachments/{self.att}/solve",
            json={}, headers=_auth(self.token),
        ).get_json()

    def contents(self) -> dict:
        from utk_curio.backend.app.projects import storage as projects_storage

        spec = projects_storage.read_spec(self.ukey, self.pid)
        return {n["type"]: (n.get("content") or "")
                for n in spec["dataflow"]["nodes"]}


class TestProseNeverBecomesContent:
    def test_the_owners_replies_write_nothing_and_the_chat_does_not_claim_solved(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, replies={
            DL: LOADER,
            AUTK: NOT_CONTROLLABLE,   # what the field log recorded
            VEGA: OWNERS_VEGA,        # invalid: `'else'` in a condition
        })
        body = h.solve()
        contents = h.contents()

        # 1. NOTHING holds prose. This is the assertion the field failure needs.
        assert NOT_CONTROLLABLE not in contents.values()
        assert contents[AUTK] == ""       # refused, so nothing was written
        assert contents[MERGE] == ""      # never even asked
        assert contents[POOL] == ""

        # 2. The wired kinds were never sent to a model.
        assert not any(f'"nodeType": "{MERGE}"' in f for f in h.frames)
        assert not any(f'"nodeType": "{POOL}"' in f for f in h.frames)

        # 3. They are resolved, and they say why there was nothing to write.
        for wired in (MERGE, POOL):
            result = body["results"][h.ids[wired]]
            assert result["status"] == "solved"
            assert result["verification"]["status"] == "no-content"
            assert "wired, not written" in result["verification"]["reason"]

        # 4. The invalid Vega document is NOT on the node, and the trail says
        #    exactly what was wrong with it.
        assert contents[VEGA] == ""
        chart = body["results"][h.ids[VEGA]]
        assert chart["status"] == "failed"
        kinds = [a.get("kind") for a in chart["attempts"]]
        assert "document-invalid" in kinds
        assert any("'else' was unexpected" in (a.get("detail") or "")
                   for a in chart["attempts"])

        # 5. The AUTK node's refusal names the shape it needed.
        map_result = body["results"][h.ids[AUTK]]
        assert map_result["status"] == "failed"
        assert any("layerRefs" in (a.get("detail") or "")
                   for a in map_result["attempts"])

    def test_valid_documents_are_written_and_said_to_be_validated(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The other half: when the child DOES author a document, it lands and
        the claim is dev/129's stronger, truthful one."""
        user, token = user_and_token
        h = _Harness(client, user, token, monkeypatch, replies={
            DL: LOADER, AUTK: VALID_AUTK, VEGA: VALID_VEGA,
        })
        body = h.solve()
        contents = h.contents()
        assert json.loads(contents[VEGA])["mark"]["type"] == "bar"
        assert json.loads(contents[AUTK])["map"]["layerRefs"][0]["dataRef"] == "upstream"
        for grammar in (AUTK, VEGA):
            result = body["results"][h.ids[grammar]]
            assert result["status"] == "solved"
            assert result["verification"]["status"] == "document-valid"
            assert "validated" in result["verification"]["reason"]
        # A document is never RUN, whatever else the batch did: no payload the
        # sandbox received carries either document.
        assert all(
            "layerRefs" not in (p.get("code") or "")
            and "$schema" not in (p.get("code") or "")
            for p in h.exec_payloads
        )
