"""dev/115 commit 1 — the ONE verified-content round loop (DEC-073).

`_verified_content_rounds` is what validate-node, Simulation Mode, and Solve
share: round 0 may execute the CURRENT content, every candidate passes the
DEC-072 gate before the sandbox sees it, a failed round feeds the correction
the traceback plus fresh URL evidence, and the attempt trail is recorded.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from utk_curio.backend.app.agents import services as services_mod
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.tests.test_agents import test_routes as _tr

_auth = _tr._auth

KEY = "4242"
PID = "p-rounds"
DL = "curio.builtin/data-loading"
CA = "curio.builtin/computation-analysis"
NOAA = "https://api.noaa.gov/climate/v1/data"


def _spec(node):
    return {"dataflow": {"nodes": [node], "edges": [], "name": "wf", "task": "load heat data"}}


class _Resolution:
    coord = "agent.node-content-builder@1.0.0"
    outcome = "ok"


class _Exec:
    """Fake sandbox: fails for content containing a marker; passes otherwise."""

    def __init__(self, fail_markers=(), stderr="Traceback: ValueError bad column"):
        self.calls: list[dict] = []
        self.fail_markers = fail_markers
        self.stderr = stderr

    def __call__(self, endpoint, payload):
        self.calls.append(payload)
        if any(m in payload["code"] for m in self.fail_markers):
            return {"stdout": [], "stderr": self.stderr, "output": {"path": "", "dataType": "str"}}
        return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}}


def _drive(gen):
    """Consume the generator; return (events, outcome)."""
    events = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as stop:
        return events, stop.value


def _rounds(app, node, *, replies, exec_fn, start_from_current=False, spec=None):
    spec = spec or _spec(node)
    projects_storage.write_spec(KEY, PID, spec)
    delegate_inputs: list[dict] = []
    script = list(replies)

    def _delegate(inputs):
        delegate_inputs.append(inputs)
        reply = script.pop(0) if script else "df = arg[0]\nreturn df"
        return "ok", reply, {"executionId": f"child-{len(delegate_inputs)}"}

    with app.test_request_context():
        gen = services_mod._verified_content_rounds(
            KEY, PID, spec=spec, node=node, resolution=_Resolution(), config=None,
            parent_execution_id="exec-1", parent_coord="agent.dataflow-builder@1.0.0",
            attachment_id="att-1", exec_fn=exec_fn,
            grounding_loop_ctx={"granted": [], "manifest": None},
            start_from_current=start_from_current, delegate_runner=_delegate,
        )
        events, outcome = _drive(gen)
    return events, outcome, delegate_inputs


class TestVerifiedRounds:
    def test_start_from_current_passing_content_generates_nothing(self, app, tmp_curio):
        node = {"id": "n1", "type": CA, "goal": "stats", "content": "df = arg[0]\nreturn df.describe()"}
        exec_fn = _Exec()
        events, outcome, inputs = _rounds(app, node, replies=[], exec_fn=exec_fn, start_from_current=True)
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 1
        assert inputs == []  # nothing regenerated
        assert outcome["candidate"] == node["content"]
        assert outcome["attempts"][0]["source"] == "current content"
        assert outcome["attempts"][0]["verdict"] == "pass"
        assert [k for k, _ in events] == ["generation_round", "node_executed", "round_verdict"]

    def test_start_from_current_failing_content_is_corrected_and_the_trail_says_so(self, app, tmp_curio):
        node = {"id": "n1", "type": CA, "goal": "stats", "content": "bad_current()\nreturn 1"}
        exec_fn = _Exec(fail_markers=("bad_current",))
        events, outcome, inputs = _rounds(
            app, node, replies=["df = arg[0]\nreturn df"], exec_fn=exec_fn, start_from_current=True,
        )
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 2
        assert len(inputs) == 1
        assert inputs[0]["previousAttempt"].startswith("bad_current()")
        assert "ValueError bad column" in inputs[0]["validationError"]
        assert [a["verdict"] for a in outcome["attempts"]] == ["fail", "pass"]
        assert outcome["attempts"][0]["source"] == "current content"
        assert outcome["attempts"][1]["source"] == "generated"
        assert outcome["attempts"][0]["kind"] == "execution-error"
        assert "ValueError" in outcome["attempts"][0]["stderrTail"]

    def test_fabricated_path_is_refused_before_the_sandbox_and_corrected(self, app, tmp_curio):
        node = {"id": "n1", "type": DL, "goal": "load the tract data", "content": ""}
        exec_fn = _Exec()
        events, outcome, inputs = _rounds(
            app, node,
            replies=['import pandas as pd\ndf = pd.read_csv("bras_ibge_data.csv")\nreturn df',
                     'import pandas as pd\ndf = pd.DataFrame({"a": [1]})\nreturn df'],
            exec_fn=exec_fn,
            spec={"dataflow": {"nodes": [{"id": "n1", "type": DL, "goal": "load the tract data", "content": ""}],
                               "edges": [], "name": "wf", "task": "generate synthetic sample data"}},
        )
        # Round 1 never reached the sandbox; round 2 (synthetic, user-requested) ran and passed.
        assert len(exec_fn.calls) == 1
        assert outcome["attempts"][0]["kind"] == "ungrounded-source"
        assert "bras_ibge_data.csv" in outcome["attempts"][0]["detail"]
        assert outcome["attempts"][1]["verdict"] == "pass"
        assert "source grounding refused" in inputs[1]["validationError"]
        assert '"sourceGrounding"' in json.dumps(inputs[0])  # data-loading children are handed it
        verdicts = [p["verdict"] for k, p in events if k == "round_verdict"]
        assert verdicts == ["fail", "pass"]

    def test_http_failure_feeds_fresh_url_evidence_to_the_correction(self, app, tmp_curio, monkeypatch):
        # The owner's Census case: the BASE endpoint answers 200 (so the DEC-072
        # gate lets the candidate run), the composed request answers 400. The
        # correction is handed the probe's verdict beside the traceback.
        probes: list[str] = []

        def _verify(url, **kw):
            probes.append(url)
            return {"status": "verified", "httpStatus": 200, "checkedAt": "now"}

        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source", _verify)
        node = {"id": "n1", "type": CA, "goal": "fetch", "content": ""}
        code = f'import requests\nr = requests.get("{NOAA}", timeout=10)\nr.raise_for_status()\nreturn r.json()'
        exec_fn = _Exec(fail_markers=("raise_for_status",),
                        stderr="requests.exceptions.HTTPError: 400 Client Error: Bad Request for url")
        events, outcome, inputs = _rounds(
            app, node, replies=[code, "df = arg[0]\nreturn df"], exec_fn=exec_fn,
        )
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 2
        evidence = inputs[1]["urlEvidence"]
        assert evidence[0]["url"] == NOAA
        assert evidence[0]["verification"]["status"] == "verified"  # base reachable; the request shape was wrong
        assert probes == [NOAA]  # the gate's probe; the evidence re-used the run's cache
        assert "400 Client Error" in inputs[1]["validationError"]
        # A non-HTTP failure adds no URL evidence.
        assert services_mod._correction_url_evidence(code, "KeyError: 'col'", None) == []

    def test_generation_error_ends_the_loop_with_a_trail_row(self, app, tmp_curio):
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        projects_storage.write_spec(KEY, PID, _spec(node))
        with app.test_request_context():
            gen = services_mod._verified_content_rounds(
                KEY, PID, spec=_spec(node), node=node, resolution=_Resolution(), config=None,
                parent_execution_id="e", parent_coord="c", attachment_id=None, exec_fn=_Exec(),
                grounding_loop_ctx={"granted": [], "manifest": None},
                delegate_runner=lambda inputs: ("error", "provider unavailable", None),
            )
            _, outcome = _drive(gen)
        assert outcome["verdict"] == "fail"
        assert outcome["attempts"] == [{"round": 1, "verdict": "fail", "kind": "generation-error",
                                        "detail": "provider unavailable"}]

    def test_exhaustion_keeps_every_attempt(self, app, tmp_curio):
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("always_bad",))
        _, outcome, inputs = _rounds(app, node, replies=["always_bad()"] * 3, exec_fn=exec_fn)
        assert outcome["verdict"] == "fail" and outcome["rounds"] == 3
        assert len(outcome["attempts"]) == 3 and len(inputs) == 3
        assert all(a["kind"] == "execution-error" for a in outcome["attempts"])


class TestFieldFixes20260908:
    """Live re-test against gemma4 (dev/115 A3, 2026-09-08), Task 3. The
    placed Census node ran and failed; both correction rounds were refused as
    "no grounded source" because the content builder — correctly — declined
    to write code: the URL the gate had verified BY PROBE that same run never
    reached the correction's ``verifiedUrls``, the swallowed HTTP error left
    no http marker for the URL evidence, and the builder's one-line decline
    was gated as if it were code."""

    DUCK = ("_duckdb.InvalidInputException: Invalid Input Error: "
            "Need a DataFrame with at least one column")

    def _census_node(self):
        code = (f'import requests\nimport pandas as pd\nr = requests.get("{NOAA}", '
                'params={"for": "community area:*"})\nreturn pd.DataFrame(r.json())')
        return {"id": "n1", "type": DL, "goal": "fetch ACS", "content": code}

    def test_a_url_the_gate_verified_reaches_the_correction_and_is_probed(self, app, tmp_curio, monkeypatch):
        probes: list[str] = []

        def _verify(url, **kw):
            probes.append(url)
            return {"status": "verified", "httpStatus": 200, "checkedAt": "now"}

        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source", _verify)
        node = self._census_node()
        exec_fn = _Exec(fail_markers=("community area",), stderr=self.DUCK)
        fixed = f'import requests\nr = requests.get("{NOAA}")\nreturn r.json()'
        events, outcome, inputs = _rounds(
            app, node, replies=[fixed], exec_fn=exec_fn, start_from_current=True,
        )
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 2
        assert outcome["attempts"][0]["kind"] == "execution-error"
        correction = inputs[0]
        composed = f"{NOAA}?for=community+area%3A%2A"
        # The gate's probe verified the base URL; the correction is told so —
        # and ONLY so: the composed query it probed is evidence, not a source.
        assert correction["sourceGrounding"]["verifiedUrls"] == [NOAA]
        # A data-loading failure re-probes what the code fetched — the real
        # composed request first, then the base — even when the traceback
        # never says "http" (the swallowed-error field case).
        assert [e["url"] for e in correction["urlEvidence"]] == [composed, NOAA]
        assert correction["urlEvidence"][1]["verification"]["status"] == "verified"
        assert probes == [NOAA, composed]  # the base re-used the gate's cache
        assert self.DUCK in correction["validationError"]

    def test_a_non_loading_node_still_needs_an_http_marker_for_url_evidence(self, app):
        ctx = type("Ctx", (), {"probe": lambda self, u: {"status": "verified"}, "is_data_loading": False})()
        code = f'import requests\nreturn requests.get("{NOAA}").json()'
        assert services_mod._correction_url_evidence(code, "KeyError: 'col'", ctx) == []
        ctx.is_data_loading = True
        assert services_mod._correction_url_evidence(code, "KeyError: 'col'", ctx)[0]["url"] == NOAA

    def test_the_builders_one_line_decline_is_recorded_in_its_words(self, app, tmp_curio, monkeypatch):
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **kw: {"status": "verified", "httpStatus": 200, "checkedAt": "now"},
        )
        node = self._census_node()
        exec_fn = _Exec(fail_markers=("community area",), stderr=self.DUCK)
        decline = "Missing source for ACS Census data in catalogDatasets or verifiedUrls."
        events, outcome, inputs = _rounds(
            app, node, replies=[decline, decline], exec_fn=exec_fn, start_from_current=True,
        )
        # A decline ENDS the loop: the missing input (a key, a path, a URL) is
        # the user's to supply, and re-asking the same builder only repeats it.
        assert outcome["verdict"] == "fail" and outcome["rounds"] == 2
        assert len(inputs) == 1 and len(outcome["attempts"]) == 2
        second = outcome["attempts"][1]
        assert second["kind"] == "source-missing"
        assert second["detail"] == f"the content builder declined: {decline}"
        assert outcome["evidence"] == {"kind": "source-missing",
                                       "detail": f"the content builder declined: {decline}"}
        assert len(exec_fn.calls) == 1  # prose never reached the sandbox

    def test_the_composed_request_is_probed_and_its_answer_joins_the_trail(self, app, tmp_curio, monkeypatch):
        # Round 2 of the live run: the base URL verifies 200, the composed
        # request redirects to an HTML "Missing Key" page, and the model
        # re-sent the same params because nothing told it otherwise.
        composed = (f"{NOAA}?get=NAME%2CB19013_001E&for=tract%3A%2A")
        probes: list[str] = []

        def _verify(url, **kw):
            probes.append(url)
            if "?" in url:
                return {"status": "verified", "httpStatus": 200, "contentType": "text/html",
                        "finalUrl": "https://api.noaa.gov/missing_key.html",
                        "pageTitle": "Missing Key", "checkedAt": "now"}
            return {"status": "verified", "httpStatus": 200, "contentType": "application/json",
                    "checkedAt": "now"}

        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source", _verify)
        code = ('import requests\nimport pandas as pd\n'
                f'url = "{NOAA}"\n'
                'params = {"get": "NAME,B19013_001E", "for": "tract:*"}\n'
                'r = requests.get(url, params=params)\nr.raise_for_status()\nreturn pd.DataFrame(r.json())')
        node = {"id": "n1", "type": DL, "goal": "fetch ACS", "content": code}
        exec_fn = _Exec(fail_markers=("tract",),
                        stderr="requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1 (char 0)")
        decline = "The Census API answers a Missing Key page: an API key for api.census.gov is required."
        events, outcome, inputs = _rounds(
            app, node, replies=[decline, decline], exec_fn=exec_fn, start_from_current=True,
        )
        assert outcome["verdict"] == "fail"
        evidence = inputs[0]["urlEvidence"]
        assert [e["url"] for e in evidence] == [composed, NOAA]  # the real request first
        assert evidence[0]["request"].startswith("the URL composed")
        assert 'an HTML page titled "Missing Key"' in evidence[0]["note"]
        assert "missing_key.html" in evidence[0]["note"]
        assert "note" not in evidence[1]  # a JSON 200 needs no reading
        first = outcome["attempts"][0]
        assert first["kind"] == "execution-error"
        assert first["endpointEvidence"].startswith(f"{NOAA}?get=NAME")
        assert "Missing Key" in first["endpointEvidence"]
        # The decline carries no endpoint line (nothing ran) and ends the loop.
        assert outcome["rounds"] == 2 and "endpointEvidence" not in outcome["attempts"][1]
        assert outcome["attempts"][1]["detail"] == f"the content builder declined: {decline}"
        # Probes: the gate's base probe, then the composed request — nothing more.
        assert probes == [NOAA, composed]

    def test_prose_decline_predicate(self):
        assert services_mod._is_prose_decline("No verified URL covers ACS indicators.")
        assert not services_mod._is_prose_decline("df = pd.read_csv('x.csv')\nreturn df")
        assert not services_mod._is_prose_decline("return arg[0]")
        assert not services_mod._is_prose_decline("import pandas as pd")
        assert not services_mod._is_prose_decline("")
        assert not services_mod._is_prose_decline("x " * 300)


class TestExecDatasetPaths:
    def _service(self, monkeypatch, resolved, raise_exc=False):
        calls = []

        class _Svc:
            def __init__(self, user):
                pass

            def resolve_execution_paths(self, ids, *, dataflow_id=None):
                calls.append((list(ids), dataflow_id))
                if raise_exc:
                    raise RuntimeError("index unavailable")
                return resolved

        monkeypatch.setattr(
            "utk_curio.backend.app.datasets.application.catalog_service.DatasetCatalogService", _Svc
        )
        return calls

    def test_resolves_the_ids_in_the_code(self, app, monkeypatch):
        calls = self._service(monkeypatch, {"imported.x@1": "/store/x.csv"})
        with app.test_request_context():
            out = services_mod._exec_dataset_paths(
                "proj", 'p = curio_dataset_path("imported.x@1")', "q = curio_dataset_path('imported.x@1')",
                "no refs here",
            )
        assert out == {"imported.x@1": "/store/x.csv"}
        assert calls == [(["imported.x@1"], "proj")]

    def test_no_ids_no_service_call_and_failures_fail_open(self, app, monkeypatch):
        calls = self._service(monkeypatch, {}, raise_exc=True)
        with app.test_request_context():
            assert services_mod._exec_dataset_paths("proj", "df = pd.DataFrame()") == {}
            assert calls == []
            assert services_mod._exec_dataset_paths("proj", 'curio_dataset_path("ds")') == {}


TEMPLATES = [
    {"id": "data-loading", "label": "Data Loading", "category": "data", "engine": "python",
     "editor": "code", "description": "Load data.", "inputPorts": [],
     "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}]},
    {"id": "computation-analysis", "label": "Computation Analysis", "category": "computation",
     "engine": "python", "editor": "code", "description": "Analyze.",
     "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
     "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
]


class TestValidateNodeCarriesDatasetPaths:
    """Route level: a catalog loader (`curio_dataset_path("<id>")`) verifies
    with its mapping — the form dev/114 made canonical used to fail here."""

    def test_validate_node_resolves_the_loader_id_and_records_the_trail(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        from utk_curio.backend.app.projects.services import _user_dir_key

        ukey = _user_dir_key(user)
        _tr.TestNodeCreate()._write_builtin_package(ukey, templates=TEMPLATES)
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="heat.csv")
        body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
        pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        for coord in ("agent.dataflow-builder@1.0.0", "agent.node-content-builder@1.0.0"):
            client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(
            f"/api/agents/projects/{pid}/attachments",
            json={"coord": "agent.dataflow-builder@1.0.0", "target": {"kind": "canvas"}},
            headers=_auth(token),
        ).get_json()["attachmentId"]
        plan = {"goal": "heat", "nodes": [
            {"ref": "load", "nodeType": DL, "title": "Load", "intent": "load the heat data"}], "edges": []}
        loader = f'import pandas as pd\ndataset_path = curio_dataset_path("{dataset_id}")\ndf = pd.read_csv(dataset_path)\nreturn df'
        replies = ["Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```", loader]
        calls = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return replies[min(len(calls) - 1, len(replies) - 1)]

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        exec_payloads = []

        def _exec(endpoint, payload):
            exec_payloads.append(payload)
            return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        r = client.post(f"/api/agents/projects/{pid}/attachments/{att}/run", json={"message": "plan"}, headers=_auth(token))
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        client.post(
            f"/api/agents/projects/{pid}/attachments/{att}/proposals/{proposal['proposalId']}/apply-node",
            json={"ref": "load"}, headers=_auth(token),
        )
        r = client.post(f"/api/agents/projects/{pid}/attachments/{att}/validate-node",
                        json={"ref": "load"}, headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        events = _tr.TestStreamedSolve()._sse_events(r)
        done = events[-1][1]
        assert done["verdict"] == "pass"
        # The runner was handed the mapping for the seeded id and the user key.
        assert dataset_id in exec_payloads[0]["dataset_paths"]
        assert exec_payloads[0]["dataset_paths"][dataset_id].endswith("heat.csv")
        assert exec_payloads[0]["user_key"] == ukey
        # The trail rides the done payload and the minted review part.
        assert done["attempts"][0]["verdict"] == "pass"
        turns = client.get(f"/api/agents/projects/{pid}/attachments/{att}/session", headers=_auth(token)).get_json()["turns"]
        parts = [p for t in turns for p in (t.get("content") or []) if p.get("type") == "proposal"]
        home_turns = None
        if not any("validation" in p for p in parts):
            # dev/72: the review lives at the node's Node Builder home.
            home_att = done["proposalAttachmentId"]
            home_turns = client.get(f"/api/agents/projects/{pid}/attachments/{home_att}/session", headers=_auth(token)).get_json()["turns"]
            parts = [p for t in home_turns for p in (t.get("content") or []) if p.get("type") == "proposal"]
        validated = next(p for p in parts if p.get("validation"))
        assert validated["validation"]["attempts"][0]["kind"] == "executed"
        # The data-loading child was handed sourceGrounding with the seeded dataset.
        child_frame = calls[-1][-1]["content"]
        assert '"sourceGrounding"' in child_frame and dataset_id in child_frame


class TestVerifiedSolve:
    """dev/115 commit 2: Solve verifies data-loading plan nodes — only code
    that ran and passed is written; exhaustion fails with the trail; a sandbox
    outage leaves the node pending; propose mode mints an EXECUTED review;
    ``verify: false`` keeps the legacy write."""

    DFB = "agent.dataflow-builder@1.0.0"
    NCB = "agent.node-content-builder@1.0.0"

    def _plan_tail(self, with_stats=True):
        nodes = [{"ref": "load", "nodeType": DL, "title": "Load", "intent": "load the tract heat data"}]
        edges = []
        if with_stats:
            nodes.append({"ref": "stats", "nodeType": CA, "title": "Stats", "intent": "compute stats"})
            edges = [{"from": "load", "to": "stats"}]
        plan = {"goal": "heat by tract", "nodes": nodes, "edges": edges}
        return "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"

    def _setup(self, client, user, token, monkeypatch, *, dl_replies, ca_reply="df = arg[0]\nreturn df.describe()",
               with_stats=True, exec_outcomes=None, exec_raises=None):
        """Applied plan with a data-loading node; scripted children keyed by
        the delegated frame; a fake sandbox keyed by content markers."""
        from utk_curio.backend.app.projects.services import _user_dir_key

        ukey = _user_dir_key(user)
        _tr.TestNodeCreate()._write_builtin_package(ukey, templates=TEMPLATES)
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="heat_tracts.csv")
        body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
        pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        for coord in (self.DFB, self.NCB):
            client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(
            f"/api/agents/projects/{pid}/attachments",
            json={"coord": self.DFB, "target": {"kind": "canvas"}}, headers=_auth(token),
        ).get_json()["attachmentId"]
        dl_script = [r.replace("{DATASET}", dataset_id) for r in dl_replies]
        calls: list = []
        dl_calls: list = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            frame = messages[-1].get("content") or ""
            if "[delegated task" not in frame:
                return self._plan_tail(with_stats)
            if f'"nodeType": "{DL}"' in frame:
                dl_calls.append(frame)
                return dl_script[min(len(dl_calls) - 1, len(dl_script) - 1)]
            return ca_reply

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        exec_payloads: list = []
        outcomes = exec_outcomes or {}

        def _exec(endpoint, payload):
            exec_payloads.append(payload)
            if exec_raises is not None:
                raise exec_raises
            for marker, stderr in outcomes.items():
                if marker in payload["code"]:
                    return {"stdout": [], "stderr": stderr, "output": {"path": "", "dataType": "str"}}
            return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        r = client.post(f"/api/agents/projects/{pid}/attachments/{att}/run", json={"message": "plan"}, headers=_auth(token))
        proposal = next(p for p in r.get_json()["content"] if p["type"] == "proposal")
        applied = client.post(
            f"/api/agents/projects/{pid}/attachments/{att}/proposals/{proposal['proposalId']}/apply",
            headers=_auth(token),
        ).get_json()["appliedGraph"]
        load = next(n["id"] for n in applied["nodes"] if str(n.get("type", "")).startswith(DL))
        stats = next((n["id"] for n in applied["nodes"] if str(n.get("type", "")).startswith(CA)), None)
        return dict(pid=pid, att=att, load=load, stats=stats, dataset_id=dataset_id, ukey=ukey,
                    calls=calls, dl_calls=dl_calls, exec_payloads=exec_payloads)

    def _solve(self, client, token, ctx, **body):
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve",
                        json=body, headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    def _node_content(self, ctx, node_id):
        spec = projects_storage.read_spec(ctx["ukey"], ctx["pid"])
        return next(n for n in spec["dataflow"]["nodes"] if n["id"] == node_id)["content"]

    LOADER = 'import pandas as pd\ndataset_path = curio_dataset_path("{DATASET}")\ndf = pd.read_csv(dataset_path)\nreturn df'

    def test_pass_writes_only_after_the_code_ran(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER])
        body = self._solve(client, token, ctx)
        load = body["results"][ctx["load"]]
        assert load["status"] == "solved" and load["verdict"] == "pass" and load["rounds"] == 1
        assert load["attempts"][0]["kind"] == "executed" and load["attempts"][0]["source"] == "generated"
        assert ctx["dataset_id"] in self._node_content(ctx, ctx["load"])
        # The sandbox ran exactly the data-loading node, with its mapping and the user key.
        assert len(ctx["exec_payloads"]) == 1
        assert ctx["exec_payloads"][0]["dataset_paths"][ctx["dataset_id"]].endswith("heat_tracts.csv")
        assert ctx["exec_payloads"][0]["user_key"] == ctx["ukey"]
        # The computation sibling solved through the legacy path (v1: data-loading only).
        assert body["results"][ctx["stats"]]["status"] == "solved"
        assert "verdict" not in body["results"][ctx["stats"]]
        assert body["builderSession"]["phase"] == "ready"

    def test_failure_is_corrected_with_the_traceback_and_fresh_url_evidence(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.verify.verify_external_source",
            lambda url, **kw: {"status": "verified", "httpStatus": 200, "checkedAt": "now"},
        )
        bad = 'import requests\nr = requests.get("https://api.census.gov/data/2020/acs/acs5", timeout=30)\nr.raise_for_status()\nreturn r.json()'
        ctx = self._setup(
            client, user, token, monkeypatch, dl_replies=[bad, self.LOADER], with_stats=False,
            exec_outcomes={"raise_for_status": "requests.exceptions.HTTPError: 400 Client Error: Bad Request"},
        )
        body = self._solve(client, token, ctx)
        load = body["results"][ctx["load"]]
        assert load["status"] == "solved" and load["verdict"] == "pass" and load["rounds"] == 2
        assert [a["verdict"] for a in load["attempts"]] == ["fail", "pass"]
        assert "400 Client Error" in load["attempts"][0]["stderrTail"]
        # The correction child saw the traceback, the previous attempt, and the probe.
        correction = ctx["dl_calls"][1]
        assert '"previousAttempt"' in correction and "400 Client Error" in correction
        assert '"urlEvidence"' in correction and "api.census.gov" in correction
        assert '"sourceGrounding"' in correction
        assert ctx["dataset_id"] in self._node_content(ctx, ctx["load"])

    def test_exhaustion_fails_with_the_trail_and_writes_nothing(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        # A GROUNDED loader that fails at run time every round (an ungrounded
        # one would be refused by the gate before the sandbox — a different row).
        ctx = self._setup(
            client, user, token, monkeypatch, with_stats=False,
            dl_replies=[self.LOADER.replace("return df", "always_bad()\nreturn df")],
            exec_outcomes={"always_bad": "Traceback: NameError: always_bad"},
        )
        body = self._solve(client, token, ctx, verify=True)
        load = body["results"][ctx["load"]]
        assert load["status"] == "failed" and load["verdict"] == "fail" and load["rounds"] == 3
        assert load["error"].startswith("not fixed after 3 attempts")
        assert "NameError" in load["error"]
        assert len(load["attempts"]) == 3
        assert self._node_content(ctx, ctx["load"]) == ""
        assert body["builderSession"]["nodeRuns"][ctx["load"]] == "failed"
        # The Solve card carries the trail lines.
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        card = next(p for t in reversed(turns) for p in (t.get("content") or []) if p.get("type") == "card")
        assert any("fail after 3 rounds" in line for line in card["lines"])
        assert any(line.startswith("  round 1:") for line in card["lines"])

    def test_sandbox_outage_leaves_the_node_pending_never_failed(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], with_stats=False,
                          exec_raises=ConnectionError("sandbox is down"))
        body = self._solve(client, token, ctx)
        load = body["results"][ctx["load"]]
        assert load["status"] == "pending" and load["verdict"] == "infrastructure"
        assert "sandbox unreachable" in load["reason"]
        assert self._node_content(ctx, ctx["load"]) == ""
        assert body["builderSession"]["nodeRuns"][ctx["load"]] == "pending"
        assert body["builderSession"]["phase"] == "applied"

    def test_verify_false_keeps_the_legacy_write(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], with_stats=False)
        body = self._solve(client, token, ctx, verify=False)
        assert body["results"][ctx["load"]] == {"status": "solved"}
        assert ctx["exec_payloads"] == []  # nothing ran
        assert ctx["dataset_id"] in self._node_content(ctx, ctx["load"])

    def test_stream_relays_the_rounds_and_verdicts(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], with_stats=False)
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve/stream",
                        json={}, headers=_auth(token))
        events = _tr.TestStreamedSolve()._sse_events(r)
        names = [k for k, _ in events]
        assert "node_round" in names and "node_executed" in names and "node_verdict" in names
        verdict = next(p for k, p in events if k == "node_verdict")
        assert verdict == {"nodeId": ctx["load"], "round": 1, "verdict": "pass"}
        result = next(p for k, p in events if k == "node_result")
        assert result["status"] == "solved" and result["verdict"] == "pass"

    def test_propose_mode_mints_an_executed_review_with_the_trail(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], with_stats=False)
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve/stream",
                        json={"mode": "propose"}, headers=_auth(token))
        events = _tr.TestStreamedSolve()._sse_events(r)
        result = next(p for k, p in events if k == "node_result")
        assert result["status"] == "proposed" and result["verdict"] == "pass"
        assert self._node_content(ctx, ctx["load"]) == ""  # nothing written in propose mode
        home = result["proposalAttachmentId"]
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{home}/session",
                           headers=_auth(token)).get_json()["turns"]
        part = next(p for t in reversed(turns) for p in (t.get("content") or [])
                    if p.get("type") == "proposal" and p.get("proposalId") == result["proposalId"])
        assert part["validation"]["verdict"] == "pass"
        assert part["validation"]["attempts"][0]["kind"] == "executed"
        assert ctx["dataset_id"] in part["preview"]

    def test_verify_flag_is_validated(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], with_stats=False)
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve",
                        json={"verify": "yes"}, headers=_auth(token))
        assert r.status_code == 400


class TestDetachedSolveJobs(TestVerifiedSolve):
    """dev/115 commit 3: the Solve batch outlives the request, re-attaches,
    reconciles to `interrupted` after a dead process, and Retry is linked."""

    def _slow_setup(self, client, user, token, monkeypatch, gate):
        """A batch whose data-loading child blocks on *gate* — the request can
        be dropped while the job is mid-flight."""
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], with_stats=False)
        original = services_mod.run_chat_completion

        def _blocking(config, messages, **kwargs):
            frame = (messages[-1].get("content") or "") if messages else ""
            if "[delegated task" in frame:
                gate.wait(timeout=10)
            return original(config, messages, **kwargs)

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _blocking)
        return ctx

    def _events(self, r):
        return _tr.TestStreamedSolve()._sse_events(r)

    def test_dropping_the_request_does_not_stop_the_batch_and_the_stream_reattaches(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.app.agents import agent_jobs

        user, token = user_and_token
        gate = threading.Event()
        ctx = self._slow_setup(client, user, token, monkeypatch, gate)
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve/stream",
                        json={}, headers=_auth(token))
        assert r.status_code == 200
        it = iter(r.response)
        first = next(it)  # solve_started reached us; the child is blocked
        assert b"event: solve_started" in first
        r.close()  # the browser tab closes
        job = agent_jobs.live_job(ctx["ukey"], ctx["att"])
        assert job is not None and job.live
        # The card shows the live job while it runs.
        cards = client.get(f"/api/agents/projects/{ctx['pid']}/attachments", headers=_auth(token)).get_json()["attachments"]
        card = next(c for c in cards if c["attachmentId"] == ctx["att"])
        assert card["liveJob"]["executionId"] == job.job_id and card["liveJob"]["status"] == "running"
        gate.set()
        # Re-attach: replays solve_started … and tails to done.
        r2 = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/jobs/stream",
                        headers=_auth(token))
        events = self._events(r2)
        names = [k for k, _ in events]
        assert names[0] == "job" and "solve_started" in names and names[-1] == "done"
        done = events[-1][1]
        assert done["results"][ctx["load"]]["status"] == "solved"
        assert ctx["dataset_id"] in self._node_content(ctx, ctx["load"])  # the job finished the write
        assert done["builderSession"]["phase"] == "ready"
        # After it finished, the card carries no live job and the stream still replays.
        cards = client.get(f"/api/agents/projects/{ctx['pid']}/attachments", headers=_auth(token)).get_json()["attachments"]
        assert next(c for c in cards if c["attachmentId"] == ctx["att"])["liveJob"] is None
        r3 = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/jobs/stream",
                        headers=_auth(token))
        assert [k for k, _ in self._events(r3)][-1] == "done"

    def test_no_job_is_a_404(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], with_stats=False)
        r = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/jobs/stream",
                       headers=_auth(token))
        assert r.status_code == 404

    def test_dead_process_session_is_reconciled_and_retry_is_linked(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], with_stats=False)
        # Simulate a process that died mid-Solve: the session says "solving"
        # under an execution id nobody holds.
        from utk_curio.backend.app.agents import attachments as att_mod

        spec = projects_storage.read_spec(ctx["ukey"], ctx["pid"])
        record = att_mod.get_attachment(spec, ctx["att"])
        record["builderSession"].update({
            "phase": "solving", "solveExecutionId": "dead0000dead", "solvingSince": time.time() - 5,
        })
        projects_storage.write_spec(ctx["ukey"], ctx["pid"], spec)
        cards = client.get(f"/api/agents/projects/{ctx['pid']}/attachments", headers=_auth(token)).get_json()["attachments"]
        session = next(c for c in cards if c["attachmentId"] == ctx["att"])["builderSession"]
        assert session["phase"] == "interrupted"
        assert session["interruptedExecutionId"] == "dead0000dead"
        assert "solveExecutionId" not in session
        # The transcript says so, once, and names the no-replay rule.
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        interrupted = [t for t in turns if "Solve was interrupted" in (t.get("text") or "")]
        assert len(interrupted) == 1
        assert "never a replay" in interrupted[0]["content"][0]["lines"][1]
        # Cancel has nothing to cancel.
        assert client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve/cancel",
                           headers=_auth(token)).status_code == 409
        # Retry: a NEW execution, linked, nothing replayed (the child runs once).
        body = self._solve(client, token, ctx)
        assert body["results"][ctx["load"]]["status"] == "solved"
        assert body["executionId"] != "dead0000dead"
        assert "interruptedExecutionId" not in body["builderSession"]
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        solve_turn = next(t for t in reversed(turns) if (t.get("text") or "").startswith("Solved"))
        assert solve_turn["execution"]["retryOf"] == "dead0000dead"
        assert len(ctx["dl_calls"]) == 1

    def test_a_second_solve_while_one_runs_is_refused_before_anything_persists(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        gate = threading.Event()
        ctx = self._slow_setup(client, user, token, monkeypatch, gate)
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve/stream",
                        json={}, headers=_auth(token))
        next(iter(r.response))
        r.close()
        r2 = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve",
                         json={}, headers=_auth(token))
        assert r2.status_code == 409
        gate.set()
        events = self._events(client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/jobs/stream",
                                         headers=_auth(token)))
        assert [k for k, _ in events][-1] == "done"


class TestSolveNode:
    """dev/115 Amendment A2: the per-node Solve from the node's own agent —
    round 0 runs the current code; a node with content lands as an executed
    review; an empty node is written on PASS; exhaustion mints nothing."""

    NB = "agent.node-builder@1.0.0"
    NCB = "agent.node-content-builder@1.0.0"
    LOADER = 'import pandas as pd\ndataset_path = curio_dataset_path("{DATASET}")\ndf = pd.read_csv(dataset_path)\nreturn df'

    def _setup(self, client, user, token, monkeypatch, *, content, child_replies=(), exec_outcomes=None):
        from utk_curio.backend.app.projects.services import _user_dir_key

        ukey = _user_dir_key(user)
        _tr.TestNodeCreate()._write_builtin_package(ukey, templates=TEMPLATES)
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="heat.csv")
        content = content.replace("{DATASET}", dataset_id)
        body = {"name": "p", "spec": {"dataflow": {"nodes": [
            {"id": "n1", "type": DL, "goal": "load the heat data", "content": content, "x": 0, "y": 0}],
            "edges": [], "packages": []}}, "outputs": []}
        pid = client.post("/api/projects", json=body, headers=_auth(token)).get_json()["id"]
        for coord in (self.NB, self.NCB):
            client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=_auth(token))
        att = client.post(f"/api/agents/projects/{pid}/attachments",
                          json={"coord": self.NB, "target": {"kind": "node", "targetId": "n1"}},
                          headers=_auth(token)).get_json()["attachmentId"]
        script = [r.replace("{DATASET}", dataset_id) for r in child_replies]
        calls: list = []

        def _fake_run(config, messages, **kwargs):
            if messages and messages[0].get("content") == services_mod.TITLE_PROMPT:
                return "Title"
            calls.append(messages)
            return script[min(len(calls) - 1, len(script) - 1)] if script else "df = arg[0]\nreturn df"

        monkeypatch.setattr("utk_curio.backend.app.agents.services.run_chat_completion", _fake_run)
        payloads: list = []
        outcomes = exec_outcomes or {}

        def _exec(endpoint, payload):
            payloads.append(payload)
            for marker, stderr in outcomes.items():
                if marker in payload["code"]:
                    return {"stdout": [], "stderr": stderr, "output": {"path": "", "dataType": "str"}}
            return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        return dict(pid=pid, att=att, ukey=ukey, dataset_id=dataset_id, calls=calls, payloads=payloads)

    def _solve_node(self, client, token, ctx, node_id="n1"):
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve-node",
                        json={"nodeId": node_id}, headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        return _tr.TestStreamedSolve()._sse_events(r)

    def _content(self, ctx):
        spec = projects_storage.read_spec(ctx["ukey"], ctx["pid"])
        return next(n for n in spec["dataflow"]["nodes"] if n["id"] == "n1")["content"]

    def test_passing_current_content_is_verified_without_a_change(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content=self.LOADER)
        events = self._solve_node(client, token, ctx)
        names = [k for k, _ in events]
        assert names[0] == "solve_node_started" and names[-1] == "done"
        done = events[-1][1]
        assert done["verdict"] == "pass" and done["unchanged"] is True and done["rounds"] == 1
        assert done["attempts"][0]["source"] == "current content"
        assert ctx["calls"] == []  # nothing regenerated
        assert ctx["payloads"][0]["dataset_paths"][ctx["dataset_id"]].endswith("heat.csv")
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        assert "no change needed" in turns[-1]["text"]
        assert turns[-1]["content"][0]["title"].startswith("Solve · PASS")

    def test_failing_current_content_is_fixed_into_an_executed_review(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        bad = 'import pandas as pd\ndataset_path = curio_dataset_path("{DATASET}")\ndf = pd.read_csv(dataset_path, sep="|||")\nbad_sep()\nreturn df'
        ctx = self._setup(client, user, token, monkeypatch, content=bad, child_replies=[self.LOADER],
                          exec_outcomes={"bad_sep": "Traceback: ParserError: bad separator"})
        events = self._solve_node(client, token, ctx)
        done = events[-1][1]
        assert done["verdict"] == "pass" and done["rounds"] == 2 and "unchanged" not in done
        assert [a["verdict"] for a in done["attempts"]] == ["fail", "pass"]
        assert done["attempts"][0]["source"] == "current content"
        assert "ParserError" in done["attempts"][0]["stderrTail"]
        # The correction saw the failing current code and its traceback.
        correction = ctx["calls"][0][-1]["content"]
        assert '"previousAttempt"' in correction and "ParserError" in correction
        # The node itself is untouched — the fix is an EXECUTED review.
        assert "bad_sep" in self._content(ctx)
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        part = next(p for t in reversed(turns) for p in (t.get("content") or [])
                    if p.get("type") == "proposal" and p.get("proposalId") == done["proposalId"])
        assert part["tool"] == "node.content.write"
        assert part["validation"]["verdict"] == "pass"
        assert part["validation"]["attempts"][1]["kind"] == "executed"
        assert "bad_sep" not in part["preview"]
        # Applying it puts the code that ran on the node.
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/proposals/{done['proposalId']}/apply",
                        headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        assert "bad_sep" not in self._content(ctx) and ctx["dataset_id"] in self._content(ctx)

    def test_empty_node_is_written_directly_on_pass(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content="", child_replies=[self.LOADER])
        done = self._solve_node(client, token, ctx)[-1][1]
        assert done["verdict"] == "pass" and done["written"] is True
        assert ctx["dataset_id"] in self._content(ctx)

    def test_exhaustion_mints_nothing_and_says_so(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        bad = self.LOADER.replace("return df", "always_bad()\nreturn df")
        ctx = self._setup(client, user, token, monkeypatch, content=bad, child_replies=[bad],
                          exec_outcomes={"always_bad": "Traceback: NameError: always_bad"})
        done = self._solve_node(client, token, ctx)[-1][1]
        assert done["verdict"] == "fail" and done["rounds"] == 3 and "proposalId" not in done
        assert self._content(ctx) == bad.replace("{DATASET}", ctx["dataset_id"])
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        assert turns[-1]["error"] is True and "Not fixed after 3 attempts" in turns[-1]["text"]
        assert len(turns[-1]["content"][0]["lines"]) == 3

    def test_preflight(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content=self.LOADER)
        base = f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve-node"
        assert client.post(base, json={}, headers=_auth(token)).status_code == 400
        assert client.post(base, json={"nodeId": "ghost"}, headers=_auth(token)).status_code == 404
