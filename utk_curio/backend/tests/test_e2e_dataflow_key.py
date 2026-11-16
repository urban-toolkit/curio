"""The e2e helpers' own calls name the dataflow each is about.

In a start of several backend processes nginx sends a request to the process
that owns its dataflow by the ``X-Curio-Dataflow`` header, else by a dataflow
id in its path (``cli/backend_group.py``). A run's record (``/api/runs/<id>``)
and the scripted model's queues (``/api/testing/agent-script``) name none in
their path, and the scripted model answers in the process that runs the turn.
So the helpers under ``test_frontend/utils/`` send the header: ``api_json``
when it is given a dataflow or its path names one, the scripted model's helpers
always, with ``dataflow=None`` for the home process's own calls, and the waits
on a run's part on the server.

Browser-free: each request is caught where the helpers send it
(``db_stubs.urlopen``), so nothing opens a socket.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

DATAFLOW = "0f8fad5b-d9cb-469f-a165-70867728950e"
ROUTE_HEADER = "x-curio-dataflow"


class _Answer:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.fixture()
def sent(monkeypatch):
    """Every request the helpers send, and the answers they get, in order
    (``{}`` once the list runs out)."""
    from utk_curio.backend.tests.test_frontend.utils import db_stubs

    caught = SimpleNamespace(requests=[], answers=[])

    def urlopen(request, timeout=None):
        caught.requests.append(request)
        return _Answer(caught.answers.pop(0) if caught.answers else {})

    monkeypatch.setattr(db_stubs, "urlopen", urlopen)
    return caught


def _key(request):
    return {name.lower(): value for name, value in request.header_items()}.get(ROUTE_HEADER)


def _asked(requests) -> list:
    return [(request.get_method(), urlsplit(request.full_url).path, _key(request)) for request in requests]


def test_api_json_names_the_dataflow_it_is_given_or_the_one_its_path_names(sent):
    from utk_curio.backend.tests.test_frontend.utils import api_json

    api_json("http://backend/api/runs/r1", "token", dataflow=DATAFLOW)
    api_json(f"http://backend/api/projects/{DATAFLOW}/runs?limit=1", "token")
    api_json(f"http://backend/api/agents/projects/{DATAFLOW}/attachments", "token")
    api_json("http://backend/api/auth/me", "token")

    assert [_key(request) for request in sent.requests] == [DATAFLOW, DATAFLOW, DATAFLOW, None]


def test_every_scripted_model_call_names_the_dataflow_whose_turns_it_scripts(sent):
    from utk_curio.backend.tests.test_frontend.utils import scripted_llm

    prompt = [[{"role": "system", "content": "an instruction"}]]
    sent.answers += [{"pending": 1}, {"held": {}}, {"held": {}}, {"captured": prompt},
                     {"calls": []}, {"offered": []}, {"captured": prompt}, {"pending": 1}]
    scripted_llm.script_agent_replies("http://backend", "a reply", dataflow=DATAFLOW)
    scripted_llm.held_agent_calls("http://backend", dataflow=DATAFLOW)
    scripted_llm.release_agent_hold("http://backend", "slow", dataflow=DATAFLOW)
    scripted_llm.captured_agent_prompts("http://backend", dataflow=DATAFLOW)
    scripted_llm.captured_agent_calls("http://backend", dataflow=DATAFLOW)
    scripted_llm.captured_agent_offers("http://backend", dataflow=DATAFLOW)
    scripted_llm.captured_system_prompt("http://backend", dataflow=DATAFLOW)
    scripted_llm.script_agent_replies("http://backend", "for the home process", dataflow=None)

    script = "/api/testing/agent-script"
    assert _asked(sent.requests) == [
        ("POST", script, DATAFLOW), ("GET", script, DATAFLOW), ("POST", f"{script}/release", DATAFLOW),
        ("GET", script, DATAFLOW), ("GET", script, DATAFLOW), ("GET", script, DATAFLOW),
        ("GET", script, DATAFLOW), ("POST", script, None),
    ]
    with pytest.raises(TypeError):
        scripted_llm.script_agent_replies("http://backend", "a reply")


class _Page:
    """A page whose backend is ``http://backend``, that waits on nothing."""

    def __init__(self):
        self.listeners: dict = {}

    def evaluate(self, _script, *_args):
        return "http://backend"

    def wait_for_timeout(self, _ms):
        return None

    def on(self, name, listener):
        self.listeners[name] = listener

    def remove_listener(self, name, _listener):
        self.listeners.pop(name, None)


def test_a_runs_record_is_read_with_the_dataflow_it_runs(sent):
    from utk_curio.backend.tests.test_frontend.utils import run_all

    sent.answers += [{"runs": [{"id": "r1"}]}, {"id": "r1", "status": "ok", "steps": []}]
    record = run_all.wait_for_server_part_to_end(_Page(), "token", DATAFLOW, timeout_ms=1000)
    sent.answers += [{"runs": []}, {"runs": [{"id": "r2"}]}, {"steps": [{"nodeId": "n1"}]}]
    steps = run_all.SandboxRuns(_Page(), "token", DATAFLOW).new_steps()

    assert record["id"] == "r1" and steps == [{"nodeId": "n1"}]
    assert _asked(sent.requests) == [
        ("GET", f"/api/projects/{DATAFLOW}/runs", DATAFLOW), ("GET", "/api/runs/r1", DATAFLOW),
        ("GET", f"/api/projects/{DATAFLOW}/runs", DATAFLOW), ("GET", f"/api/projects/{DATAFLOW}/runs", DATAFLOW),
        ("GET", "/api/runs/r2", DATAFLOW),
    ]
