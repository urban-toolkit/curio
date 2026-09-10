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
VEGA = "curio.builtin/vis-vega"
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


def _rounds(app, node, *, replies, exec_fn, start_from_current=False, spec=None, **extra):
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
            start_from_current=start_from_current, delegate_runner=_delegate, **extra,
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
        # Three DIFFERENT failing corrections (a comment-only repeat is not run
        # again — see TestConnectionKeys' live Census shape).
        _, outcome, inputs = _rounds(app, node, replies=[f"always_bad({i})" for i in range(3)], exec_fn=exec_fn)
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


class TestConnectionKeys:
    """dev/116 (DEC-074) on the agent path: the loop resolves a saved key per
    round, the builder is handed `availableSecrets` with the `use` line, an
    unknown name and a pasted key are refused before the sandbox, a keyed
    composed probe is redacted evidence, and a credential decline carries a
    concrete remedy."""

    VALUE = "n0aa-k3y-v4lue-0123456789"

    def _save(self, name="census", host="api.noaa.gov", delivery="query:key"):
        from utk_curio.backend.app.users.connection_keys import default_store

        default_store().put(KEY, name, host, self.VALUE, delivery)

    def _fixed(self):
        return (f'import requests\nurl = "{NOAA}"\n'
                'params = {"get": "NAME", "key": curio_secret("census")}\n'
                'r = requests.get(url, params=params)\nr.raise_for_status()\nreturn r.json()')

    def test_a_saved_key_is_offered_resolved_per_round_and_probed_redacted(self, app, tmp_curio, monkeypatch):
        self._save()
        probes: list[tuple] = []

        def _verify(url, **kw):
            probes.append((url, kw.get("params"), kw.get("headers")))
            if kw.get("params"):
                return {"status": "verified", "httpStatus": 200, "contentType": "application/json",
                        "finalUrl": f"{url}&key={self.VALUE}", "checkedAt": "now"}
            if "?" in url:
                return {"status": "verified", "httpStatus": 200, "contentType": "text/html",
                        "pageTitle": "Missing Key", "checkedAt": "now"}
            return {"status": "verified", "httpStatus": 200, "contentType": "application/json", "checkedAt": "now"}

        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source", _verify)
        current = (f'import requests\nurl = "{NOAA}"\nparams = {{"get": "NAME"}}\n'
                   'r = requests.get(url, params=params)\nreturn r.json()')
        node = {"id": "n1", "type": DL, "goal": "fetch", "content": current}
        # The fake sandbox: the request without the key fails, with it passes.
        exec_fn = _Exec(fail_markers=('params = {"get": "NAME"}\n',),
                        stderr="requests.exceptions.JSONDecodeError: Expecting value")
        events, outcome, inputs = _rounds(
            app, node, replies=[self._fixed()], exec_fn=exec_fn, start_from_current=True,
            secrets_fn=services_mod._exec_secrets_resolver(KEY),
        )
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 2
        # Round 1 (current content, no key named) carried no secrets; round 2 did.
        assert "secrets" not in exec_fn.calls[0]
        assert exec_fn.calls[1]["secrets"] == {"census": self.VALUE}
        # The correction was told about the key in the executable form.
        grounding = inputs[0]["sourceGrounding"]
        assert grounding["availableSecrets"] == [{
            "name": "census", "host": "api.noaa.gov", "delivery": "query:key",
            "use": 'api_key = curio_secret("census")',
        }]
        assert "connection key" in grounding["rule"]
        # The composed request was probed bare AND with the key; the keyed
        # outcome is redacted and never a verified source.
        composed = inputs[0]["urlEvidence"][0]
        assert composed["keyed"] == "census" and composed["keyedDelivery"] == "query:key"
        assert self.VALUE not in json.dumps(composed)
        assert "«redacted:census»" in composed["keyedVerification"]["finalUrl"]
        assert "answers data" in composed["keyedNote"]
        keyed_probe = next(p for p in probes if p[1])
        assert keyed_probe[1] == {"key": self.VALUE}
        # Grounding: the passing candidate's Source block names the key.
        # (verified_urls holds the bare base URL only — never a keyed URL.)
        assert all(self.VALUE not in u for u in inputs[0]["sourceGrounding"]["verifiedUrls"])

    def test_an_unknown_name_is_refused_before_the_sandbox_with_the_saved_names(self, app, tmp_curio, monkeypatch):
        self._save()
        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source",
                            lambda url, **kw: {"status": "verified", "httpStatus": 200, "checkedAt": "now"})
        node = {"id": "n1", "type": DL, "goal": "fetch", "content": ""}
        bad = f'import requests\nreturn requests.get("{NOAA}", params={{"key": curio_secret("noaa")}}).json()'
        exec_fn = _Exec()
        events, outcome, inputs = _rounds(app, node, replies=[bad, self._fixed()], exec_fn=exec_fn)
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 2
        first = outcome["attempts"][0]
        assert first["kind"] == "ungrounded-source"
        assert "curio_secret('noaa')" in first["detail"] and "saved: census" in first["detail"]
        assert len(exec_fn.calls) == 1  # the refused candidate never ran
        assert "no connection key named 'noaa'" in inputs[1]["validationError"]

    def test_a_pasted_key_literal_is_refused_before_the_sandbox(self, app, tmp_curio, monkeypatch):
        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source",
                            lambda url, **kw: {"status": "verified", "httpStatus": 200, "checkedAt": "now"})
        node = {"id": "n1", "type": DL, "goal": "fetch", "content": ""}
        pasted = (f'import requests\napi_key = "{self.VALUE}"\n'
                  f'return requests.get("{NOAA}", params={{"key": api_key}}).json()')
        exec_fn = _Exec()
        pasted_again = pasted.replace("api_key", "token")  # a different literal, the same offence
        events, outcome, inputs = _rounds(app, node, replies=[pasted, pasted_again], exec_fn=exec_fn)
        assert outcome["verdict"] == "fail"
        assert all(a["kind"] == "ungrounded-source" for a in outcome["attempts"])
        assert "credential literal" in outcome["attempts"][0]["detail"]
        assert exec_fn.calls == []  # never executed, never journaled
        assert self.VALUE not in outcome["attempts"][0]["detail"]

    def test_a_credential_decline_carries_a_concrete_remedy(self, app, tmp_curio, monkeypatch):
        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source",
                            lambda url, **kw: {"status": "verified", "httpStatus": 200, "checkedAt": "now"})
        current = (f'import requests\nurl = "{NOAA}"\nparams = {{"get": "NAME"}}\n'
                   'r = requests.get(url, params=params)\nreturn r.json()')
        node = {"id": "n1", "type": DL, "goal": "fetch", "content": current}
        exec_fn = _Exec(fail_markers=("NAME",), stderr="requests.exceptions.JSONDecodeError: Expecting value")
        decline = "The NOAA API requires an API key; none is available."
        events, outcome, inputs = _rounds(app, node, replies=[decline], exec_fn=exec_fn, start_from_current=True)
        assert outcome["verdict"] == "fail" and outcome["evidence"]["kind"] == "source-missing"
        assert outcome["evidence"]["remedy"] == {
            "kind": "connection-key", "host": "api.noaa.gov", "suggestedName": "noaa",
        }
        assert outcome["attempts"][1]["remedy"]["kind"] == "connection-key"
        assert "add a connection key for api.noaa.gov" in services_mod._source_missing_remedy(
            outcome["evidence"]["remedy"])
        # With a key already saved for the host, the remedy is to Solve again.
        self._save(host="api.noaa.gov")
        events, outcome, inputs = _rounds(app, node, replies=[decline], exec_fn=exec_fn, start_from_current=True)
        assert outcome["evidence"]["remedy"] == {"kind": "use-connection-key", "host": "api.noaa.gov", "name": "census"}
        # A decline about something else carries no remedy.
        events, outcome, inputs = _rounds(app, node, replies=["No dataset in the catalog matches."],
                                          exec_fn=exec_fn, start_from_current=True)
        assert "remedy" not in outcome["evidence"]

    def test_the_live_census_shape_probes_the_placeholder_request_with_the_key_and_skips_a_comment_only_repeat(self, app, tmp_curio, monkeypatch):
        # dev/116 live re-test (2026-09-09): round 2 sent the key as
        # params["key"] = api_key with api_key = curio_secret("census") and got
        # Census's real 400 ("invalid 'in' argument"); round 3 changed comments
        # only. The harness now probes the composed request WITH the saved
        # value and refuses to run a repeat.
        self._save()
        probes: list[tuple] = []

        def _verify(url, **kw):
            probes.append((url, kw.get("params")))
            if kw.get("params"):
                return {"status": "unreachable", "httpStatus": 400, "contentType": "text/plain",
                        "detail": "the endpoint answered 400", "bodySample": "error: invalid 'in' argument",
                        "finalUrl": f"{url}&key={self.VALUE}", "checkedAt": "now"}
            return {"status": "verified", "httpStatus": 200, "contentType": "application/json", "checkedAt": "now"}

        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source", _verify)
        current = (f'import requests\nurl = "{NOAA}"\nparams = {{"get": "NAME"}}\n'
                   'r = requests.get(url, params=params)\nreturn r.json()')
        round2 = (f'import requests\nurl = "{NOAA}"\napi_key = curio_secret("census")\n'
                  'params = {"get": "NAME", "in": "state:17,county:031", "key": api_key}\n'
                  'r = requests.get(url, params=params)\nif r.status_code != 200:\n'
                  '    raise Exception(f"Census API request failed with status code {r.status_code}: {r.text}")\n'
                  'return r.json()')
        round3 = round2.replace('params = {', '# The previous attempt failed with 400.\n# Let\'s ensure the naming is exact.\nparams = {')
        node = {"id": "n1", "type": DL, "goal": "fetch", "content": current}
        exec_fn = _Exec(fail_markers=('params = {"get": "NAME"}\n', "county:031"),
                        stderr="Exception: Census API request failed with status code 400: error: invalid 'in' argument")
        events, outcome, inputs = _rounds(
            app, node, replies=[round2, round3], exec_fn=exec_fn, start_from_current=True,
            secrets_fn=services_mod._exec_secrets_resolver(KEY),
        )
        assert outcome["verdict"] == "fail" and outcome["rounds"] == 3
        kinds = [a["kind"] for a in outcome["attempts"]]
        assert kinds == ["execution-error", "execution-error", "repeated-attempt"]
        assert len(exec_fn.calls) == 2  # the repeat never reached the sandbox
        assert exec_fn.calls[1]["secrets"] == {"census": self.VALUE}
        # Round 2's failure: the composed request was probed WITH the key (bare
        # URL + params), shown with the call in place of the value, redacted.
        evidence = inputs[1]["urlEvidence"]
        composed = evidence[0]
        assert composed["keyed"] == "census"
        assert composed["url"].endswith('&key=curio_secret("census")')
        assert composed["verification"]["httpStatus"] == 400
        assert "invalid 'in' argument" in composed["note"]
        assert self.VALUE not in json.dumps(evidence)
        assert "«redacted:census»" in composed["verification"]["finalUrl"]
        keyed_probe = next(p for p in probes if p[1] and "county" in p[0])
        assert keyed_probe[0] == f"{NOAA}?get=NAME&in=state%3A17%2Ccounty%3A031"
        assert keyed_probe[1] == {"key": self.VALUE}
        # No bare probe of the placeholder request, no verified-URL pollution.
        assert all("curio_secret" not in p[0] and self.VALUE not in p[0] for p in probes)
        assert inputs[1]["sourceGrounding"]["verifiedUrls"] == [NOAA]
        # The repeat is named for the user and stays out of the sandbox.
        third = outcome["attempts"][2]
        assert "repeated the previous attempt" in third["detail"]
        assert "invalid 'in' argument" in third["detail"]

    def test_the_loop_has_its_own_egress_budget_shared_cache(self, app, tmp_curio, monkeypatch):
        # dev/116 live fix: the run-wide budget of 4 was spent by round 1's
        # evidence and every later correction read "budget spent". The loop
        # now budgets for all its rounds; the probe cache is still shared.
        probes: list[str] = []

        def _verify(url, **kw):
            probes.append(url)
            return {"status": "verified", "httpStatus": 200, "contentType": "application/json", "checkedAt": "now"}

        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source", _verify)
        node = {"id": "n1", "type": DL, "goal": "fetch", "content": ""}
        hosts = ["https://a.example.gov/v1", "https://b.example.gov/v1", "https://c.example.gov/v1"]
        replies = [f'import requests\nr = requests.get("{h}", params={{"q": {i}}})\nreturn r.json()' for i, h in enumerate(hosts)]
        exec_fn = _Exec(fail_markers=("params",), stderr="HTTPError: 400 Client Error")
        shared_ctx: dict = {"granted": [], "manifest": None}
        projects_storage.write_spec(KEY, PID, _spec(node))
        with app.test_request_context():
            gen = services_mod._verified_content_rounds(
                KEY, PID, spec=_spec(node), node=node, resolution=_Resolution(), config=None,
                parent_execution_id="e", parent_coord="agent.dataflow-builder@1.0.0",
                attachment_id="att-1", exec_fn=exec_fn, grounding_loop_ctx=shared_ctx,
                delegate_runner=lambda inputs: ("ok", replies[min(len(probes) // 2, 2)], {"executionId": "c"}),
            )
            _events, outcome = _drive(gen)
        assert outcome["verdict"] == "fail" and outcome["rounds"] == 3
        # Six real probes (a gate probe + a composed probe per round) — none starved.
        assert len(probes) >= 6
        assert all("budget" not in json.dumps(a) for a in outcome["attempts"])
        # The caller's context kept the shared cache (and never a budget of its own spent).
        assert len(shared_ctx["_probe_cache"]) >= 6
        assert "_egress_budget" not in shared_ctx

    def test_same_code_ignores_comments_and_spacing_only(self):
        a = 'x = 1\n# c\nreturn x'
        assert services_mod._same_code(a, 'x = 1\n\n\nreturn x  # done')
        assert services_mod._same_code(a, 'x  =  1\nreturn x')
        assert not services_mod._same_code(a, 'x = 2\nreturn x')
        assert not services_mod._same_code(a, 'x = "# not a comment"\nreturn x')
        assert not services_mod._same_code("", "")

    def test_delivery_code_names_the_key_without_a_keyed_probe(self, app, tmp_curio, monkeypatch):
        self._save(delivery="code")
        probes: list = []

        def _verify(url, **kw):
            probes.append(kw)
            return {"status": "verified", "httpStatus": 200, "contentType": "application/json", "checkedAt": "now"}

        monkeypatch.setattr("utk_curio.backend.app.agents.verify.verify_external_source", _verify)
        current = (f'import requests\nurl = "{NOAA}"\nparams = {{"get": "NAME"}}\n'
                   'r = requests.get(url, params=params)\nreturn r.json()')
        node = {"id": "n1", "type": DL, "goal": "fetch", "content": current}
        exec_fn = _Exec(fail_markers=('params = {"get": "NAME"}\n',), stderr="ValueError: no data")
        events, outcome, inputs = _rounds(app, node, replies=[self._fixed()], exec_fn=exec_fn, start_from_current=True,
                                          secrets_fn=services_mod._exec_secrets_resolver(KEY))
        composed = inputs[0]["urlEvidence"][0]
        assert composed["keyed"] == "census" and "keyedVerification" not in composed
        assert "the code does not use it yet" in composed["keyedNote"]
        assert all(not (kw.get("params") or kw.get("headers")) for kw in probes)


class TestNotExecutableKinds:
    """dev/118 (DEC-075): the loop returns the runner's honest outcome for a
    browser-rendered kind after one round — no correction, no sandbox."""

    def test_the_loop_returns_not_executable_after_one_round(self, app, tmp_curio):
        node = {"id": "n1", "type": VEGA, "goal": "plot it", "content": ""}
        exec_fn = _Exec()
        events, outcome, inputs = _rounds(app, node, replies=['{"mark": "bar"}'], exec_fn=exec_fn)
        assert outcome["verdict"] == "not-executable" and outcome["rounds"] == 1
        assert outcome["evidence"]["kind"] == "not-executable"
        assert exec_fn.calls == [] and len(inputs) == 1  # generated once, never run, never corrected
        attempt = outcome["attempts"][0]
        assert attempt["verdict"] == "not-executable" and attempt["kind"] == "not-executable"
        assert "no code the sandbox could run" in attempt["detail"]
        assert [k for k, _ in events if k == "round_verdict"] == ["round_verdict"]


class TestSameBatchReuse:
    """dev/118 (DEC-075) commit 4: the loop hands the runner the outputs of
    ancestors that passed earlier in the batch; a vanished artifact costs one
    silent retry without reuse, never a round."""

    def _chain(self):
        node_a = {"id": "a", "type": CA, "goal": "prep", "content": "df = arg\nreturn df"}
        node_t = {"id": "t", "type": CA, "goal": "stats", "content": ""}
        spec = {"dataflow": {"nodes": [node_a, node_t], "edges": [{"id": "e1", "source": "a", "target": "t"}],
                             "name": "wf", "task": "stats"}}
        return node_t, spec

    def test_prior_outputs_feed_the_target_and_are_recorded_on_the_attempt(self, app, tmp_curio):
        node_t, spec = self._chain()
        exec_fn = _Exec()
        events, outcome, inputs = _rounds(
            app, node_t, replies=["df = arg[0]\nreturn df.describe()"], exec_fn=exec_fn, spec=spec,
            prior_outputs_fn=lambda: {"a": {"path": "art-a", "dataType": "dataframe"}},
        )
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 1
        assert len(exec_fn.calls) == 1  # the ancestor was not re-run
        assert exec_fn.calls[0]["file_path"] == "art-a"
        assert outcome["attempts"][0]["reusedNodes"] == ["a"]
        assert "reuseRetried" not in outcome["attempts"][0]

    def test_a_vanished_reused_artifact_is_retried_once_without_reuse(self, app, tmp_curio):
        node_t, spec = self._chain()
        calls: list[dict] = []

        def _exec(endpoint, payload):
            calls.append(payload)
            if payload["file_path"] == "art-gone":
                return {"stdout": [], "stderr": "KeyError: artifact 'art-gone' could not be loaded",
                        "output": {"path": "", "dataType": "str"}}
            return {"stdout": [], "stderr": "", "output": {"path": "art-x", "dataType": "dataframe"}}

        events, outcome, inputs = _rounds(
            app, node_t, replies=["df = arg[0]\nreturn df.describe()"], exec_fn=_exec, spec=spec,
            prior_outputs_fn=lambda: {"a": {"path": "art-gone", "dataType": "dataframe"}},
        )
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 1  # not a round
        assert len(inputs) == 1  # no correction was asked for
        # First attempt: the target alone, against the vanished artifact; the
        # retry ran the whole slice (ancestor, then target).
        assert [c["file_path"] for c in calls] == ["art-gone", "", "art-x"]
        assert outcome["attempts"][0]["reuseRetried"] is True
        assert "reusedNodes" not in outcome["attempts"][0]  # the counted result ran whole

    def test_a_real_failure_with_reuse_is_the_candidates_own(self, app, tmp_curio):
        node_t, spec = self._chain()
        exec_fn = _Exec(fail_markers=("bad_stats",), stderr="NameError: bad_stats")
        events, outcome, inputs = _rounds(
            app, node_t, replies=["bad_stats()", "df = arg[0]\nreturn df.describe()"], exec_fn=exec_fn, spec=spec,
            prior_outputs_fn=lambda: {"a": {"path": "art-a", "dataType": "dataframe"}},
        )
        assert outcome["verdict"] == "pass" and outcome["rounds"] == 2
        assert len(exec_fn.calls) == 2  # each round ran the target only
        assert "reuseRetried" not in outcome["attempts"][0]
        assert outcome["attempts"][0]["kind"] == "execution-error"


class TestEmptyUpstreamWaits:
    """dev/118 live fix (2026-09-09, gemma4 Task 2): a dependent whose upstream
    ended empty (a declined loader) used to run against None and "pass" by
    coding around it. Now it waits — one round, no correction, pending."""

    def test_the_loop_stops_after_one_round_and_names_the_upstream(self, app, tmp_curio):
        node_t = {"id": "t", "type": CA, "goal": "stats", "content": ""}
        spec = {"dataflow": {"nodes": [{"id": "a", "type": DL, "goal": "load", "content": ""}, node_t],
                             "edges": [{"id": "e1", "source": "a", "target": "t"}], "name": "wf", "task": "t"}}
        exec_fn = _Exec()
        events, outcome, inputs = _rounds(app, node_t, replies=["df = arg[0]\nreturn df"], exec_fn=exec_fn, spec=spec)
        assert outcome["verdict"] == "fail" and outcome["rounds"] == 1 and len(inputs) == 1
        assert outcome["evidence"]["kind"] == "upstream-blocker" and outcome["evidence"]["upstreamEmpty"] is True
        assert exec_fn.calls == []  # nothing ran

    def test_a_dependent_of_a_failed_loader_waits_pending_with_the_reason(self, client, user_and_token, tmp_curio, monkeypatch):
        helper = TestVerifiedSolve()
        user, token = user_and_token
        # The loader declines (no source) → empty; the stats node must not run
        # against None and "pass".
        ctx = helper._setup(client, user, token, monkeypatch,
                            dl_replies=["No catalog dataset covers the tract heat data."])
        body = helper._solve(client, token, ctx)
        assert body["results"][ctx["load"]]["status"] == "failed"
        stats = body["results"][ctx["stats"]]
        assert stats["status"] == "pending" and stats["reason"].startswith("waiting — upstream node")
        assert stats["rounds"] == 1
        assert ctx["exec_payloads"] == []  # neither the empty loader nor the stats node ran
        assert body["builderSession"]["nodeRuns"][ctx["stats"]] == "pending"  # Retry after the loader is fixed
        assert body["builderSession"]["phase"] == "applied"
        assert helper._node_content(ctx, ctx["stats"]) == ""


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
    # dev/119 (DEC-076): the roster, not a name list, says what the sandbox runs.
    {"id": "data-summary", "label": "Data Summary", "category": "computation", "engine": "python",
     "editor": "code", "description": "Summarize.",
     "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
     "outputPorts": [{"types": ["JSON"], "cardinality": "1"}]},
    {"id": "spatial-join", "label": "Spatial Join", "category": "computation", "engine": "python",
     "editor": "none", "hasCode": False, "description": "Join by geometry through the spatial-join service.",
     "inputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "2"}],
     "outputPorts": [{"types": ["GEODATAFRAME"], "cardinality": "1"}]},
    {"id": "custom-js", "label": "Custom JS", "category": "computation", "engine": "javascript",
     "editor": "code", "description": "A JS kind the legacy tables never heard of.",
     "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
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
               with_stats=True, exec_outcomes=None, exec_raises=None, ca_replies=None, ca_gate=None):
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
        ca_script = list(ca_replies or [ca_reply])
        calls: list = []
        dl_calls: list = []
        ca_calls: list = []

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
            if ca_gate is not None:
                ca_gate.wait(timeout=10)  # dev/118: hold wave 2 so wave 1's persist is observable
            ca_calls.append(frame)
            return ca_script[min(len(ca_calls) - 1, len(ca_script) - 1)]

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
                    calls=calls, dl_calls=dl_calls, ca_calls=ca_calls, exec_payloads=exec_payloads)

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
        # Wave 1 ran the data-loading node, with its mapping and the user key.
        assert ctx["exec_payloads"][0]["dataset_paths"][ctx["dataset_id"]].endswith("heat_tracts.csv")
        assert ctx["exec_payloads"][0]["user_key"] == ctx["ukey"]
        # dev/118 (DEC-075): the computation sibling is verified too — in wave
        # 2, against the loader's WRITTEN content (the slice re-runs the loader
        # with the code that landed, then the stats node).
        stats = body["results"][ctx["stats"]]
        assert stats["status"] == "solved" and stats["verdict"] == "pass" and stats["rounds"] == 1
        # dev/118 commit 4: the loader's recorded output stands in — wave 2
        # runs the stats node alone, fed by the artifact the loader produced.
        assert len(ctx["exec_payloads"]) == 2
        assert "describe" in ctx["exec_payloads"][1]["code"]
        assert ctx["exec_payloads"][1]["file_path"] == "art-1"
        assert stats["attempts"][0]["reusedNodes"] == [ctx["load"]]
        assert ctx["dataset_id"] in self._node_content(ctx, ctx["load"])
        assert "describe" in self._node_content(ctx, ctx["stats"])
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
            dl_replies=[self.LOADER.replace("return df", f"always_bad({i})\nreturn df") for i in range(3)],
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


    # ---- dev/118 (DEC-075): waves ---------------------------------------

    def _stream(self, client, token, ctx):
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve/stream",
                        json={}, headers=_auth(token))
        assert r.status_code == 200
        return _tr.TestStreamedSolve()._sse_events(r)

    def test_waves_run_roots_first_and_hand_the_upstream_type_to_the_correction(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(
            client, user, token, monkeypatch, dl_replies=[self.LOADER],
            ca_replies=["bad_stats(arg[0])\nreturn 1", "df = arg[0]\nreturn df.describe()"],
            exec_outcomes={"bad_stats": "Traceback: NameError: bad_stats"},
        )
        events = self._stream(client, token, ctx)
        names = [k for k, _ in events]
        waves = [p for k, p in events if k == "solve_wave"]
        assert [w["wave"] for w in waves] == [1, 2] and all(w["of"] == 2 for w in waves)
        assert waves[0]["nodeIds"] == [ctx["load"]] and waves[1]["nodeIds"] == [ctx["stats"]]
        # Order on the wire: wave 1 → the loader's result → wave 2 → the stats result.
        i_w1, i_w2 = names.index("solve_wave"), names.index("solve_wave", names.index("solve_wave") + 1)
        results = [(i, p) for i, (k, p) in enumerate(events) if k == "node_result"]
        assert i_w1 < results[0][0] < i_w2 < results[1][0]
        assert results[0][1]["nodeId"] == ctx["load"] and results[1][1]["nodeId"] == ctx["stats"]
        done = events[-1][1]
        stats = done["results"][ctx["stats"]]
        assert stats["status"] == "solved" and stats["verdict"] == "pass" and stats["rounds"] == 2
        assert stats["attempts"][0]["kind"] == "execution-error"
        # The correction was told what its upstream produced when it ran.
        correction = ctx["ca_calls"][-1]
        assert '"upstreamOutputs"' in correction
        assert '"outputDataType": "dataframe"' in correction and ctx["load"] in correction
        # The first generation of the stats node saw it too (wave 1 had landed).
        assert '"upstreamOutputs"' in ctx["ca_calls"][0]
        assert done["builderSession"]["phase"] == "ready"

    def test_a_wave_is_persisted_before_the_next_wave_starts(self, client, user_and_token, tmp_curio, monkeypatch):
        import threading

        user, token = user_and_token
        gate = threading.Event()
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER], ca_gate=gate)
        r = client.post(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve/stream",
                        json={}, headers=_auth(token))
        assert r.status_code == 200
        it = iter(r.response)
        seen = b""
        while b"event: solve_wave" not in seen or seen.count(b"event: solve_wave") < 2:
            seen += next(it)  # wave 2 announced ⇒ wave 1 persisted
        spec = projects_storage.read_spec(ctx["ukey"], ctx["pid"])
        loader = next(n for n in spec["dataflow"]["nodes"] if n["id"] == ctx["load"])
        assert ctx["dataset_id"] in loader["content"]  # landed before wave 2
        record = next(a for a in spec["dataflow"]["agentAttachments"] if a["attachmentId"] == ctx["att"])
        session = record["builderSession"]
        assert session["phase"] == "solving" and session["nodeRuns"][ctx["load"]] == "solved"
        assert session["nodeRuns"][ctx["stats"]] == "pending"
        assert session["solvingSince"] > 0  # the wave boundary is the heartbeat
        gate.set()
        rest = b"".join(it)
        assert b"event: done" in rest
        assert "describe" in self._node_content(ctx, ctx["stats"])

    def test_the_batch_deadline_reverts_undispatched_targets_to_pending_with_the_reason(self, client, user_and_token, tmp_curio, monkeypatch):
        # dev/118 (DEC-075): the budget is checked at every wave boundary and
        # before every dispatch. Here it runs out after wave 1: the loader is
        # solved and persisted, the stats node is pending WITH the reason, the
        # batch names it once, and the phase says applied (Retry continues).
        import itertools

        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER])
        checks = itertools.count()
        monkeypatch.setattr(services_mod, "_batch_deadline_spent", lambda started, deadline_s: next(checks) >= 2)
        events = self._stream(client, token, ctx)
        done = events[-1][1]
        assert done["results"][ctx["load"]]["status"] == "solved"
        stats = done["results"][ctx["stats"]]
        assert stats["status"] == "pending" and "time budget" in stats["reason"] and "Retry" in stats["reason"]
        assert done["reason"] == stats["reason"]
        assert done["notAttempted"] == [ctx["stats"]] and done["cancelled"] is False
        assert done["builderSession"]["nodeRuns"][ctx["stats"]] == "pending"
        assert done["builderSession"]["phase"] == "applied"
        assert [p for k, p in events if k == "solve_wave"] == [
            {"wave": 1, "of": 2, "nodeIds": [ctx["load"]]},
        ]  # wave 2 was never announced
        pending_event = next(p for k, p in events if k == "node_result" and p["nodeId"] == ctx["stats"])
        assert pending_event["status"] == "pending" and "time budget" in pending_event["reason"]
        assert len(ctx["exec_payloads"]) == 1  # only the loader ran
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        card = next(p for t in reversed(turns) for p in (t.get("content") or []) if p.get("type") == "card")
        assert any(line.startswith("reason: the batch's time budget") for line in card["lines"])
        assert any("pending — the batch's time budget" in line for line in card["lines"])

    def test_a_slice_bound_refusal_is_skipped_never_failed(self, client, user_and_token, tmp_curio, monkeypatch):
        # dev/118 (DEC-075): the runner's 25-node slice bound (and a cycle) is
        # a precondition on validation, not a failure of the content.
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, dl_replies=[self.LOADER])
        from utk_curio.backend.app.agents import validation as _validation

        original = _validation.validate_candidate

        def _bounded(user_key, project_id, spec, node_id, candidate, **kw):
            if node_id == ctx["stats"]:
                return {"verdict": "fail", "evidence": {
                    "kind": "precondition",
                    "detail": "the upstream slice has 30 nodes (validation bound 25) — run the dataflow manually instead",
                }}
            return original(user_key, project_id, spec, node_id, candidate, **kw)

        monkeypatch.setattr("utk_curio.backend.app.agents.validation.validate_candidate", _bounded)
        body = self._solve(client, token, ctx)
        stats = body["results"][ctx["stats"]]
        assert stats["status"] == "skipped" and stats["reason"].startswith("skipped — the upstream slice has 30 nodes")
        assert stats["rounds"] == 1  # a bound is not corrected — one round says so
        assert "not fixed" not in json.dumps(stats)
        assert body["results"][ctx["load"]]["status"] == "solved"
        assert body["builderSession"]["nodeRuns"][ctx["stats"]] == "skipped"
        assert body["builderSession"]["phase"] == "ready"  # nothing pending or failed
        assert self._node_content(ctx, ctx["stats"]) == ""

    def test_solve_batch_deadline_env(self, monkeypatch):
        monkeypatch.delenv("CURIO_SOLVE_BATCH_DEADLINE", raising=False)
        assert services_mod.solve_batch_deadline_s() == services_mod.DEFAULT_SOLVE_BATCH_DEADLINE_S == 45 * 60
        monkeypatch.setenv("CURIO_SOLVE_BATCH_DEADLINE", "600")
        assert services_mod.solve_batch_deadline_s() == 600
        for bad in ("soon", "0", "-5", " "):
            monkeypatch.setenv("CURIO_SOLVE_BATCH_DEADLINE", bad)
            assert services_mod.solve_batch_deadline_s() == 45 * 60
        assert services_mod._batch_deadline_spent(0.0, 1) is True  # monotonic() is far past 1 s
        import time as _t
        assert services_mod._batch_deadline_spent(_t.monotonic(), 3600) is False

    def test_solve_waves_helper(self):
        spec = {"dataflow": {"nodes": [{"id": n, "type": CA} for n in "abcdex"], "edges": [
            {"id": "e1", "source": "a", "target": "b"}, {"id": "e2", "source": "a", "target": "c"},
            {"id": "e3", "source": "b", "target": "d"}, {"id": "e4", "source": "c", "target": "d"},
            {"id": "e5", "source": "x", "target": "e"},            # x is NOT a target
            {"id": "e6", "source": "d", "target": "a", "type": "Interaction"},  # ignored
        ]}}
        assert services_mod._solve_waves(spec, ["d", "c", "b", "a", "e"]) == [["a", "e"], ["c", "b"], ["d"]]
        # A cycle among targets lands in one last wave (the runner refuses it by name).
        cyc = {"dataflow": {"nodes": [{"id": n, "type": CA} for n in "pqr"], "edges": [
            {"id": "e1", "source": "p", "target": "q"}, {"id": "e2", "source": "q", "target": "p"},
            {"id": "e3", "source": "q", "target": "r"},
        ]}}
        assert services_mod._solve_waves(cyc, ["p", "q", "r"]) == [["p", "q", "r"]]
        assert services_mod._solve_waves(None, ["a"]) == [["a"]] and services_mod._solve_waves(spec, []) == []


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

    def _setup(self, client, user, token, monkeypatch, *, content, child_replies=(), exec_outcomes=None,
               node_type=DL):
        from utk_curio.backend.app.projects.services import _user_dir_key

        ukey = _user_dir_key(user)
        _tr.TestNodeCreate()._write_builtin_package(ukey, templates=TEMPLATES)
        dataset_id = _tr.TestDatasetFinderTools()._seed_dataset(user, filename="heat.csv")
        content = content.replace("{DATASET}", dataset_id)
        body = {"name": "p", "spec": {"dataflow": {"nodes": [
            {"id": "n1", "type": node_type, "goal": "load the heat data", "content": content, "x": 0, "y": 0}],
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

        endpoints: list = []

        def _exec(endpoint, payload):
            payloads.append(payload)
            endpoints.append(endpoint)
            for marker, stderr in outcomes.items():
                if marker in payload["code"]:
                    return {"stdout": [], "stderr": stderr, "output": {"path": "", "dataType": "str"}}
            return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}}

        monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
        return dict(pid=pid, att=att, ukey=ukey, dataset_id=dataset_id, calls=calls, payloads=payloads,
                    endpoints=endpoints)

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

    def test_a_palette_dragged_versioned_node_is_solved_not_refused(self, client, user_and_token, tmp_curio, monkeypatch):
        # dev/119 hotfix (live defect): the canvas persists versioned ids; the
        # runner classified them passive and the per-node Solve answered
        # "not executable" on a user's real Data Loading code.
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content=self.LOADER, node_type=DL + "@1")
        events = self._solve_node(client, token, ctx)
        done = events[-1][1]
        assert done["verdict"] == "pass" and done["unchanged"] is True and done["rounds"] == 1
        assert len(ctx["payloads"]) == 1 and ctx["payloads"][0]["nodeType"] == DL + "@1"

    def test_a_roster_kind_the_legacy_tables_never_heard_of_is_verified(self, client, user_and_token, tmp_curio, monkeypatch):
        # dev/119 (DEC-076): a JS kind known only to the installed package —
        # the roster says executable/javascript, so it runs, on /execJs.
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content="return [1, 2, 3];",
                          node_type="curio.builtin/custom-js@1")
        events = self._solve_node(client, token, ctx)
        done = events[-1][1]
        assert done["verdict"] == "pass" and done["unchanged"] is True and done["rounds"] == 1
        assert ctx["endpoints"] == ["/execJs"] and ctx["payloads"][0]["nodeType"] == "curio.builtin/custom-js@1"

    def test_data_summary_is_verified_through_the_roster(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content=self.LOADER,
                          node_type="curio.builtin/data-summary@1")
        done = self._solve_node(client, token, ctx)[-1][1]
        assert done["verdict"] == "pass" and done["rounds"] == 1 and ctx["endpoints"] == ["/exec"]

    def test_spatial_join_is_not_executable_by_its_manifest(self, client, user_and_token, tmp_curio, monkeypatch):
        # dev/119 live premise: spatial-join has no code — the browser POSTs to
        # its own service. The roster says so; the runner never sees it.
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content="", node_type="curio.builtin/spatial-join@1")
        events = self._solve_node(client, token, ctx)
        done = events[-1][1]
        assert done["verdict"] == "not-executable" and done["rounds"] == 0
        assert ctx["calls"] == [] and ctx["payloads"] == []
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        assert "no code the sandbox could run" in turns[-1]["text"]
        assert "through its own service" in turns[-1]["text"]

    def test_a_browser_rendered_node_is_not_executable_and_nothing_runs(self, client, user_and_token, tmp_curio, monkeypatch):
        # dev/118 (DEC-075): the per-node Solve accepted any kind and, for a
        # Vega node, reported a PASS on content the runner never sent.
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content='{"mark": "bar"}', node_type=VEGA)
        events = self._solve_node(client, token, ctx)
        done = events[-1][1]
        assert done["verdict"] == "not-executable" and done["rounds"] == 0
        assert [k for k, _ in events] == ["solve_node_started", "done"]  # no round, no run
        assert ctx["calls"] == [] and ctx["payloads"] == []  # no generation, no sandbox
        assert "unchanged" not in done and "written" not in done and "proposalId" not in done
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        assert turns[-1]["text"].startswith("Not executable:")
        assert "no code the sandbox could run" in turns[-1]["text"]
        assert turns[-1].get("error") is not True
        assert turns[-1]["content"][0]["title"].startswith("Solve · NOT-EXECUTABLE")
        node = next(n for n in client.get(f"/api/projects/{ctx['pid']}", headers=_auth(token)).get_json()
                    ["spec"]["dataflow"]["nodes"] if n["id"] == "n1")
        assert node["content"] == '{"mark": "bar"}'  # untouched

    def test_preflight(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        ctx = self._setup(client, user, token, monkeypatch, content=self.LOADER)
        base = f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/solve-node"
        assert client.post(base, json={}, headers=_auth(token)).status_code == 400
        assert client.post(base, json={"nodeId": "ghost"}, headers=_auth(token)).status_code == 404


class TestRunEgressBudget:
    """dev/115 F6 closed (2026-09-09): the run budget is sized for every
    external candidate row plus one redirect each, so the last row of a full
    card is checked instead of "refused — budget spent"."""

    def test_a_full_card_with_a_redirect_per_row_is_probed_to_the_last_row(self, monkeypatch):
        from utk_curio.backend.app.agents import content, egress

        rows = content._CANDIDATES_MAX_ROWS_PER_LANE
        assert services_mod._RUN_EGRESS_CALLS == rows * 2
        calls: list[str] = []

        def _request(method, url, **kw):
            calls.append(url)
            if url.endswith("/final"):
                return 200, {"Content-Type": "application/json"}, b'{"ok": true}', None
            return 302, {"Location": url + "/final"}, b"", url + "/final"

        monkeypatch.setattr(egress, "_default_request", _request)
        monkeypatch.setattr(egress, "check_url", lambda url, **kw: (True, ""))
        part = {"type": "datasetCandidates", "lanes": {"external": [
            {"name": f"row {i}", "url": f"https://data{i}.example.gov/api/v1"} for i in range(rows)
        ]}}
        loop_ctx: dict = {}
        services_mod._verify_candidate_parts([part], loop_ctx)
        statuses = [r["verification"]["status"] for r in part["lanes"]["external"]]
        assert statuses == ["verified"] * rows  # the last row too
        assert len(calls) == rows * 2 and loop_ctx["_egress_budget"].used == rows * 2
        # One more request would be the (2n+1)th: the bound still means something.
        assert loop_ctx["_egress_budget"].exhausted


class TestAttemptTrailCarriesTheCodeAndTheBound:
    """dev/127: the owner could see three truncated tracebacks and no code, and
    "not fixed after 3 attempts" read as a verdict on the code when it was a
    verdict on the round cap."""

    def test_a_failed_round_records_the_code_it_ran(self, app, tmp_curio):
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("bad_attempt",))
        events, outcome, inputs = _rounds(
            app, node, replies=["bad_attempt()", "bad_attempt2()", "bad_attempt3()"],
            exec_fn=exec_fn,
        )
        assert outcome["verdict"] == "fail"
        codes = [a.get("code") for a in outcome["attempts"]]
        assert codes and all(codes), "every failed attempt carries its code"
        assert codes[0] == "bad_attempt()"
        # And each attempt is distinguishable from the next.
        assert len({a["contentSha256"] for a in outcome["attempts"]}) == len(codes)

    def test_a_passing_round_keeps_no_code_copy(self, app, tmp_curio):
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        events, outcome, inputs = _rounds(app, node, replies=["good()"], exec_fn=_Exec())
        assert outcome["verdict"] == "pass"
        assert "code" not in outcome["attempts"][0]  # it IS the node's content
        assert outcome["stoppedBy"] == "passed"

    def test_the_round_cap_is_named_as_the_bound(self, app, tmp_curio):
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("bad",))
        events, outcome, inputs = _rounds(
            app, node, replies=["bad1()", "bad2()", "bad3()", "bad4()", "bad5()", "bad6()"],
            exec_fn=exec_fn,
        )
        assert outcome["verdict"] == "fail"
        assert outcome["stoppedBy"] == "rounds"

    def test_a_second_repeat_stops_the_loop(self, app, tmp_curio):
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("bad",))
        events, outcome, inputs = _rounds(
            app, node,
            # The same code every time: round 1 runs and fails, rounds 2 and 3
            # are repeats — the second repeat ends it.
            replies=["bad()", "bad()", "bad()", "bad()", "bad()", "bad()"],
            exec_fn=exec_fn,
        )
        assert outcome["stoppedBy"] == "repeat"
        kinds = [a["kind"] for a in outcome["attempts"]]
        assert kinds.count("repeated-attempt") == 2
        assert len(exec_fn.calls) == 1  # a repeat is never run again

    def test_an_upstream_blocker_is_its_own_bound(self, app, tmp_curio):
        node_t = {"id": "t", "type": CA, "goal": "stats", "content": ""}
        spec = {"dataflow": {"nodes": [{"id": "a", "type": DL, "goal": "load", "content": ""}, node_t],
                             "edges": [{"id": "e1", "source": "a", "target": "t"}],
                             "name": "wf", "task": "t"}}
        events, outcome, inputs = _rounds(
            app, node_t, replies=["df = arg[0]\nreturn df"], exec_fn=_Exec(), spec=spec,
        )
        assert outcome["stoppedBy"] == "blocker"

    def test_the_trail_line_keeps_the_exception_whole(self, app, tmp_curio):
        # The regression: 'round 2: execution-error — de'.
        traceback = (
            'Traceback (most recent call last):\n'
            '  File "/opt/conda/lib/python3.11/site-packages/pandas/core/generic.py", line 1776,'
            ' in _get_label_or_level_values\n    raise KeyError(key)\n'
            "KeyError: 'community_area'\n"
        )
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("bad",), stderr=traceback)
        events, outcome, inputs = _rounds(
            app, node, replies=["bad()", "bad2()", "bad3()"], exec_fn=exec_fn,
        )
        line = next(l for l in outcome["roundsTrace"] if l.startswith("round 1"))
        assert "KeyError: 'community_area'" in line
        assert "generic.py:1776 in _get_label_or_level_values" in line


class TestRepairBudget:
    """dev/127: the loop stops when a BUDGET is spent, not at a hardcoded three
    attempts — the owner's failing batch finished in 25 s against a 300 s
    sandbox timeout and a 45-minute batch deadline."""

    def test_the_shipped_default_is_six_attempts(self, monkeypatch):
        monkeypatch.delenv("CURIO_SOLVE_CORRECTION_ROUNDS", raising=False)
        monkeypatch.delenv("CURIO_SOLVE_NODE_BUDGET", raising=False)
        assert services_mod.solve_correction_rounds() == 5  # + the first generation
        assert services_mod.solve_node_budget_s() == 300  # the owner's five minutes

    def test_the_env_is_read_and_garbage_falls_back(self, monkeypatch):
        monkeypatch.setenv("CURIO_SOLVE_CORRECTION_ROUNDS", "9")
        assert services_mod.solve_correction_rounds() == 9
        for bad in ("", "   ", "zero", "-3", "0"):
            monkeypatch.setenv("CURIO_SOLVE_CORRECTION_ROUNDS", bad)
            assert services_mod.solve_correction_rounds() == 5, bad
        monkeypatch.setenv("CURIO_SOLVE_NODE_BUDGET", "60")
        assert services_mod.solve_node_budget_s() == 60
        monkeypatch.setenv("CURIO_SOLVE_NODE_BUDGET", "nope")
        assert services_mod.solve_node_budget_s() == 300

    def test_six_attempts_are_made_when_the_clock_allows(self, app, tmp_curio, monkeypatch):
        monkeypatch.delenv("CURIO_SOLVE_CORRECTION_ROUNDS", raising=False)
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("bad",))
        replies = [f"bad{i}()" for i in range(1, 9)]  # each different: no repeat
        events, outcome, inputs = _rounds(app, node, replies=replies, exec_fn=exec_fn)
        assert outcome["verdict"] == "fail"
        assert outcome["rounds"] == 6  # 1 generation + 5 corrections
        assert outcome["stoppedBy"] == "rounds"
        assert len(outcome["attempts"]) == 6
        assert all(a.get("code") for a in outcome["attempts"])

    def test_the_wall_budget_stops_the_next_round_and_names_itself(
        self, app, tmp_curio, monkeypatch
    ):
        monkeypatch.delenv("CURIO_SOLVE_CORRECTION_ROUNDS", raising=False)
        monkeypatch.setenv("CURIO_SOLVE_NODE_BUDGET", "100")
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("bad",))
        ticks = iter([0, 40, 80, 120, 160, 200, 240])  # 40 s per round

        events, outcome, inputs = _rounds(
            app, node, replies=[f"bad{i}()" for i in range(1, 9)], exec_fn=exec_fn,
            clock=lambda: next(ticks),
        )
        # Rounds at t=40 and t=80 start (under 100 s); the one at t=120 does not.
        assert outcome["rounds"] == 3
        assert outcome["stoppedBy"] == "budget"
        assert len(outcome["attempts"]) == 3, "a round in flight is always recorded"
        assert any("100s repair budget is spent" in line for line in outcome["roundsTrace"])

    def test_a_round_in_flight_is_never_cut_off(self, app, tmp_curio, monkeypatch):
        # The budget is checked at round BOUNDARIES: the clock jumping past it
        # mid-round must not lose the round's attempt.
        monkeypatch.delenv("CURIO_SOLVE_CORRECTION_ROUNDS", raising=False)
        monkeypatch.setenv("CURIO_SOLVE_NODE_BUDGET", "10")
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("bad",))
        ticks = iter([0, 9999, 9999, 9999])
        events, outcome, inputs = _rounds(
            app, node, replies=["bad1()", "bad2()"], exec_fn=exec_fn,
            clock=lambda: next(ticks),
        )
        assert outcome["rounds"] == 1
        assert outcome["stoppedBy"] == "budget"
        assert outcome["attempts"][0]["code"] == "bad1()"

    def test_the_cap_bounds_a_reckless_env(self, app, tmp_curio, monkeypatch):
        monkeypatch.setenv("CURIO_SOLVE_CORRECTION_ROUNDS", "500")
        node = {"id": "n1", "type": CA, "goal": "stats", "content": ""}
        exec_fn = _Exec(fail_markers=("bad",))
        events, outcome, inputs = _rounds(
            app, node, replies=[f"bad{i}()" for i in range(1, 40)], exec_fn=exec_fn,
        )
        assert outcome["rounds"] == 1 + services_mod.MAX_SOLVE_CORRECTION_ROUNDS
