"""How long the system prompt of each run of Curio's agents is.

Every run an agent Curio ships makes is composed here on one dataflow,
``docs/examples/26-several-inputs.json`` (Data Loading, Python, Data
Transformation, JavaScript, Vega-Lite and Autark nodes and a Data Pool, over
three datasets of the Data Catalog), by the code that composes it for the
model:

- the chat of each agent that has one (``catalog.listed``), attached to the
  canvas of a dataflow that holds only that agent and the agents it requires,
  asked ``TASK``: its system turn on the fenced protocol and on native tools,
  and the native tools' definitions (``turns/prepare._prepare_run``, whose
  messages a chat turn sends as they are);
- a delegated run of each capability each agent declares, as another agent's
  run or Solve hands it over (``delegation.run_delegate``), with ``TASK`` as
  its intent. ``node.content.generate`` runs as Solve asks for it instead: for
  the first node of each kind in the dataflow that has content, with Solve's
  inputs for that node. The endpoint takes a reply schema, as Anthropic's and
  OpenAI's do, so the Autark node's run is the one held to the Autark
  document's schema, under its own prompt.

Each prompt's size in characters and its sha256 are recorded on this test
(``record_property``), and the CI report shows them. Each prompt must stay
within its budget in ``prompt_budgets.json``, set about 5% over its size: a
change that takes a prompt past its budget raises the budget in the same PR,
and the PR says why.

What a prompt could take from its surroundings is fixed here: the scripted
endpoint, the account's package store (seeded from the catalog Curio ships,
with the built-in package only) and new dataflows. Every prompt is composed
twice, in two new dataflows, and must come out the same.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import reply_schemas
from utk_curio.backend.app.agents.application.turns import prepare
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import node_context
from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.packages.application import seeding
from utk_curio.backend.app.packages.repositories.store import user_packages_dir
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth

REPO_ROOT = Path(__file__).resolve().parents[4]
#: The dataflow every prompt is composed on.
DATAFLOW = REPO_ROOT / "docs" / "examples" / "26-several-inputs.json"
#: What each chat is asked, and the intent each delegated run is handed but a
#: node's content, whose intent is its node's goal.
TASK = "Chart the mean PM2.5 of each ZIP code beside the map of the stations."
#: Every prompt's budget in characters, by the prompt's name.
BUDGETS = Path(__file__).with_name("prompt_budgets.json")
#: A budget is the prompt's size this much over, rounded up to a multiple of ROUND_TO.
HEADROOM = 1.05
ROUND_TO = 100
#: The mode Solve asks a node's content of.
CONTENT = "node.content.generate"
#: The node kind whose content is held to a reply schema.
AUTARK = "curio.builtin/autk-grammar"
#: Who hands the delegated runs over. Only the task's frame, a user message, names it.
PARENT = "agent.curio.dataflow-builder@1"
#: The scripted endpoint, scripted by ``_script_endpoint``.
ENDPOINT = ProviderConfig(api_key="", api_type="testing", base_url="", model="scripted",
                          config_id="llm-000000000026")


def _script_endpoint() -> None:
    """A fresh scripted endpoint that calls tools natively and takes a reply schema."""
    testing_provider.reset()
    testing_provider.script_chat_capabilities(tools=True, structured_output=True)


@pytest.fixture()
def pinned(tmp_curio, monkeypatch):
    """What a prompt could otherwise take from the tests around it, pinned.

    The account's store is under this test's own folder and is seeded from the
    catalog Curio ships, not the session's copy other tests publish into, with
    the built-in package alone, whatever ``CURIO_SEED_EXAMPLES`` says. No
    endpoint is remembered as having refused a reply schema."""
    monkeypatch.delenv("CURIO_STATE_DIR", raising=False)
    monkeypatch.delenv("CURIO_PACKAGES_ROOT", raising=False)
    monkeypatch.setattr(seeding, "CURIO_SEED_EXAMPLES", False)
    reply_schemas._refused.clear()
    _script_endpoint()
    yield tmp_curio
    testing_provider.reset()
    reply_schemas._refused.clear()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _budget(size: int) -> int:
    """The budget a prompt of *size* characters gets: HEADROOM over it, rounded up."""
    return math.ceil(size * HEADROOM / ROUND_TO) * ROUND_TO


def _system(message: dict, name: str) -> tuple[str, dict]:
    """A system turn's text and its characters per slot kind, in the turn's order."""
    kinds = [slot["kind"] for slot in message["slots"]]
    assert kinds[:2] == ["preamble", "instruction"], f"{name} starts with {kinds[:2]}"
    slots: dict[str, int] = {}
    for slot in message["slots"]:
        slots[slot["kind"]] = slots.get(slot["kind"], 0) + len(slot["text"])
    return message["content"], slots


def _dataflow(client, token) -> str:
    """The id of a new dataflow holding the example."""
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    resp = client.post("/api/projects", json={"name": spec["dataflow"]["name"], "spec": spec, "outputs": []},
                       headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _chat(client, token, user_key: str, coord: str) -> dict:
    """The chat of *coord*, attached to the canvas of a dataflow that holds it
    and the agents it requires: its system turn on each protocol, and its
    native tools as JSON."""
    project_id = _dataflow(client, token)
    installed = client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord},
                            headers=_auth(token))
    assert installed.status_code == 201, installed.get_data(as_text=True)
    attached = client.post(f"/api/agents/projects/{project_id}/attachments",
                           json={"coord": coord, "target": {"kind": "canvas"}}, headers=_auth(token))
    assert attached.status_code == 201, attached.get_data(as_text=True)
    _script_endpoint()
    _coord, _session, messages, _policy, _title, _pins, loop_ctx = prepare._prepare_run(
        user_key, project_id, attached.get_json()["attachmentId"], TASK, ENDPOINT,
    )
    tools = loop_ctx["native_tools"]
    assert tools, f"{coord}'s chat offers no native tools, so its native turn would go unmeasured"
    return {
        f"{coord} chat": _system(loop_ctx["fenced_system"], f"{coord} chat"),
        f"{coord} chat, native tools": _system(messages[0], f"{coord} chat, native tools"),
        f"{coord} chat, native tool definitions": (
            json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":")), None,
        ),
    }


def _delegated(user_key: str, project_id: str, coord: str, capability: str, inputs: dict) -> tuple[dict, dict]:
    """The system turn a delegated run of *coord* in *capability*'s mode sends, and the run's record."""
    _script_endpoint()
    status, text, record = delegation.run_delegate(
        user_key, project_id, coord, capability, inputs, ENDPOINT,
        parent_execution_id="prompt-sizes", parent_coord=PARENT, attachment_id=None,
    )
    calls = testing_provider.captured()
    assert status == "ok" and len(calls) == 1, f"{coord} {capability} made {len(calls)} calls: {status}, {text}"
    return calls[0][0], record


def _first_of_each_kind(spec: dict) -> list[dict]:
    """The first node of each kind in *spec* that has content, in the dataflow's order."""
    nodes: dict[str, dict] = {}
    for node in spec["dataflow"]["nodes"]:
        if str(node.get("content") or "").strip():
            nodes.setdefault(node["type"], node)
    return list(nodes.values())


def _modes(user_key: str, project_id: str, coord: str, capabilities: list[str]) -> dict:
    """The delegated run of each of *coord*'s *capabilities*, a node's content
    once per node kind, with the inputs Solve hands it for that node."""
    spec = projects_storage.read_spec(user_key, project_id)
    measured: dict = {}
    for capability in capabilities:
        if capability != CONTENT:
            system, _record = _delegated(user_key, project_id, coord, capability, {"intent": TASK})
            measured[f"{coord} {capability}"] = _system(system, f"{coord} {capability}")
            continue
        nodes = _first_of_each_kind(spec)
        assert AUTARK in [node["type"] for node in nodes], "the dataflow has no Autark node to write"
        for node in nodes:
            name = f"{coord} {capability}, {node['type']}"
            inputs = {
                "nodeType": node["type"],
                "intent": node.get("goal"),
                "nodeContext": node_context.compose_node_context(user_key, project_id, spec, node["id"]),
            }
            system, record = _delegated(user_key, project_id, coord, capability, inputs)
            held = record["pins"].get("replySchema")
            assert (held is not None) == (node["type"] == AUTARK), f"{name} ran with the reply schema {held!r}"
            measured[name] = _system(system, name)
    return measured


def _measure(client, token, user_key: str) -> dict:
    """Every prompt this test measures, by name: its text, and its characters
    per slot kind (None for the tools' JSON), each agent's in the roster's order."""
    project_id = _dataflow(client, token)
    measured: dict = {}
    for manifest in builtin.list_builtin_manifests():
        if manifest.catalog.listed:
            measured.update(_chat(client, token, user_key, manifest.dir_name))
        measured.update(_modes(user_key, project_id, manifest.dir_name, manifest.capability_ids))
    return measured


def test_every_prompt_is_recorded_and_stays_within_its_budget(pinned, client, user_and_token, record_property):
    user, token = user_and_token
    user_key = _user_dir_key(user)
    assert user_packages_dir(user_key).resolve().is_relative_to(pinned.resolve()), (
        "the account's package store is outside this test's folder, so other tests could change its prompts"
    )

    first = _measure(client, token, user_key)
    for name, (text, slots) in first.items():
        value = {"chars": len(text), "sha256": _sha256(text)}
        if slots is not None:
            value["slots"] = slots
        record_property(name, json.dumps(value))
    chats = [m.dir_name for m in builtin.list_builtin_manifests() if m.catalog.listed]
    assert chats and all(f"{coord} chat" in first for coord in chats), sorted(first)

    again = _measure(client, token, user_key)
    differ = sorted(name for name in first.keys() | again.keys()
                    if (first.get(name) or (None,))[0] != (again.get(name) or (None,))[0])
    assert not differ, f"composed again in two new dataflows, these prompts came out different: {differ}"

    budgets = json.loads(BUDGETS.read_text(encoding="utf-8"))
    sizes = {name: len(text) for name, (text, _slots) in first.items()}
    problems = []
    for name, size in sizes.items():
        if name in budgets and size > budgets[name]:
            problems.append(
                f"{name} is {size:,} characters, past its budget of {budgets[name]:,}. If it grew on purpose, "
                f"raise its budget in {BUDGETS.name} in the same PR and say why in the PR."
            )
    unbudgeted = {name: size for name, size in sizes.items() if name not in budgets}
    if unbudgeted:
        listed = "\n".join(f"  {name}: {size:,} characters" for name, size in unbudgeted.items())
        suggested = json.dumps({name: _budget(size) for name, size in unbudgeted.items()}, indent=2)
        problems.append(
            f"{len(unbudgeted)} prompts have no budget in {BUDGETS.name}:\n{listed}\n"
            f"Give each a budget about {HEADROOM - 1:.0%} over its size, rounded up to {ROUND_TO} characters:\n"
            f"{suggested}"
        )
    gone = [name for name in budgets if name not in sizes]
    if gone:
        problems.append(f"{BUDGETS.name} budgets prompts this test no longer measures; remove them: {gone}")
    assert not problems, "\n\n".join(problems)
