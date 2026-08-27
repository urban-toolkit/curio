"""Every agent in the catalog, run for real against the live backend.

The catalog ships a roster of built-in agents and, until this module, nothing
proved that any *given* one of them could be installed, attached and actually
run. ``test_agents/test_routes.py`` covers the run loop richly but in-process
and for a handful of coordinates; ``test_agent_catalog.py`` covers the drawer
and the palette but never runs a turn. The gap was per-agent, end to end.

**Parametrized over the roster itself**, not a hand-kept list: add a
``BuiltinAgentSpec`` and it is covered on the next run, or it fails. That is the
property this module exists for, and ``test_the_roster_matches_the_served_catalog``
guards the other direction - an agent that reaches the catalog by some path
other than the roster cannot slip past.

No browser and no LLM. This file lives in the E2E suite only to reuse
``curio_servers`` / ``current_server``, exactly as
``test_library_install_integration.py`` does: it isolates the agent run from
every UI concern, so a failure says immediately which half broke. The model is
the scripted provider (``app/agents/testing_provider.py``), driven from here
over ``/api/testing/agent-script``.

The visual half is ``test_agent_chat_e2e.py``, which captures one baseline
screenshot per agent.

Run::

    pytest utk_curio/backend/tests/test_frontend/test_agent_runs_e2e.py -v
    pytest utk_curio/backend/tests/test_frontend/test_agent_runs_e2e.py -k dataflow-builder -v
"""
from __future__ import annotations

import json
import re

import pytest

from utk_curio.backend.app.agents import builtin

from .utils import (
    api_json,
    captured_agent_prompts,
    captured_system_prompt,
    require_project_page,
    require_user_auth,
    script_agent_replies,
    stub_db_user,
    use_scripted_llm,
)

# The nodes every project in this module is seeded with. Two, not one: an agent
# whose compatibleTargets[].requires names "data-loading" can only attach to a
# node of that type, and every other node agent needs some ordinary node.
DATA_NODE_ID = "agent-e2e-data"
CODE_NODE_ID = "agent-e2e-code"

# Read tools that are cheap, deterministic and - the point - reach nothing
# outside this process. web.search / web.fetch are deliberately absent: they
# really open sockets (app/agents/egress.py), and agent.node-researcher and
# agent.researcher both declare a local read tool as well, so nothing is lost.
SAFE_READ_TOOLS = ("dataflow.read", "node.read", "node.runtime.read", "packages.catalog")

# Mutate tools whose mint needs only what a test can state up front. The other
# mutate contracts (dataset.install, package.install, package.draft.apply,
# node.template.create) each need a real catalog row or, for the draft, a run of
# the isolated build service; their mints are covered in-process by
# test_agents/test_routes.py. An agent declaring only those falls through to the
# read-tool leg below rather than getting a mint assertion that would be more
# about fixture plumbing than about the agent.
# Ordered MOST specific first, because an agent that declares several gets the
# first match and that match should be the thing it is *for*. Reviewing the
# baseline captures is what surfaced the ordering: with node.create ahead of
# dataflow.plan.write, agent.dataflow-builder - whose whole capability is
# dataflow.orchestrate - minted a single node instead of a plan. node.create
# sits ahead of node.content.write for the same reason and one more: applying it
# puts a NEW NODE on the canvas, which is the most visible proof an agent did
# something. The spread this produces is deliberate - a plan, two node
# creations, one content replacement.
MINTABLE_TOOLS = ("dataflow.plan.write", "node.create", "node.content.write")

# What each mint writes, so the apply assertion and the scripted params cannot
# drift apart. Named here because both modules assert on them.
PROPOSED_CONTENT = "print('proposed by the agent')"
CREATED_CONTENT = "print('new node')"
PLAN_NODE_TITLES = ("Load", "Analyze")

BUILTIN_NODE_TYPE = "curio.builtin/computation-analysis"

VISIBLE_PROSE = "Here is what I found."


def _spec_id(spec: builtin.BuiltinAgentSpec) -> str:
    return spec.agent_id


def _username(agent_id: str) -> str:
    """A distinct account per agent, so one agent's state cannot reach another."""
    return "agentrun_" + re.sub(r"[^a-z0-9]+", "_", agent_id.lower())[:40]


def _project_spec() -> dict:
    return {
        "dataflow": {
            "name": "AgentRunE2E",
            "task": "",
            "nodes": [
                {
                    "id": DATA_NODE_ID,
                    "type": "curio.builtin/data-loading",
                    "x": 120, "y": 120,
                    "content": "return [1]",
                    "in": "DEFAULT", "out": "DEFAULT", "goal": "",
                    "metadata": {"keywords": []},
                },
                {
                    "id": CODE_NODE_ID,
                    "type": BUILTIN_NODE_TYPE,
                    "x": 760, "y": 120,
                    "content": "print(1)",
                    "in": "DEFAULT", "out": "DEFAULT", "goal": "",
                    "metadata": {"keywords": []},
                },
            ],
            "edges": [
                {
                    "id": "agent-e2e-edge",
                    "source": DATA_NODE_ID,
                    "target": CODE_NODE_ID,
                    "sourceHandle": "out",
                    "targetHandle": "in",
                }
            ],
        }
    }


def _tail(payload: dict) -> str:
    """A reply carrying exactly one terminal curio.v1 block."""
    fence = "```"
    return (
        VISIBLE_PROSE
        + "\n\n"
        + fence
        + "curio.v1\n"
        + json.dumps(payload)
        + "\n"
        + fence
    )


def _target_for(spec: builtin.BuiltinAgentSpec) -> dict:
    """The attachment target this agent actually accepts.

    Derived from the roster rather than hardcoded, so it stays correct when an
    agent's compatibleTargets change - the server enforces the same two rules
    (kind, then the node "requires" suffix) in ``services.attach_agent``.
    """
    kinds = spec.target_kinds()
    if "canvas" in kinds:
        return {"kind": "canvas"}
    node_id = DATA_NODE_ID if spec.node_requires else CODE_NODE_ID
    return {"kind": "node", "targetId": node_id}


def _mint_node_id(spec: builtin.BuiltinAgentSpec) -> str:
    return DATA_NODE_ID if spec.node_requires else CODE_NODE_ID


def _mint_params(tool: str, spec: builtin.BuiltinAgentSpec) -> dict:
    if tool == "node.content.write":
        return {"nodeId": _mint_node_id(spec), "content": PROPOSED_CONTENT}
    if tool == "node.create":
        return {"nodeType": BUILTIN_NODE_TYPE, "content": CREATED_CONTENT}
    if tool == "dataflow.plan.write":
        return {
            "dataflowPlan": {
                "goal": "a two step flow",
                "nodes": [
                    {"ref": "a", "nodeType": BUILTIN_NODE_TYPE,
                     "title": PLAN_NODE_TITLES[0], "intent": "load the data"},
                    {"ref": "b", "nodeType": BUILTIN_NODE_TYPE,
                     "title": PLAN_NODE_TITLES[1], "intent": "compute stats"},
                ],
                "edges": [{"from": "a", "to": "b"}],
            }
        }
    raise AssertionError(f"no mint params defined for {tool!r}")


def _characteristic(spec: builtin.BuiltinAgentSpec) -> tuple[str, str | None]:
    """What this agent is *for*, as ``(leg, tool)``.

    Chosen from the roster entry rather than a parallel table, so it cannot
    drift out of sync when an agent gains or loses a tool.
    """
    declared = list(spec.tools)
    for tool in MINTABLE_TOOLS:
        if tool in declared:
            return "mint", tool
    for tool in SAFE_READ_TOOLS:
        if tool in declared:
            return "read", tool
    return "prompts", None


def _scripted_replies(spec: builtin.BuiltinAgentSpec) -> tuple[str, str | None, list[str]]:
    leg, tool = _characteristic(spec)
    if leg == "mint":
        return leg, tool, [
            _tail({"toolRequest": {"tool": tool, "params": _mint_params(tool, spec)}}),
            "I have proposed the change for your review.",
        ]
    if leg == "read":
        return leg, tool, [
            _tail({"toolRequest": {"tool": tool, "params": {}}}),
            "That is what the project currently contains.",
        ]
    return leg, tool, [
        _tail({"suggestedPrompts": {
            "primary": "What should I look at next?",
            "alternatives": ["Explain this differently"],
        }})
    ]


# ── the roster ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec", builtin.BUILTIN_AGENTS, ids=_spec_id)
def test_agent_installs_attaches_and_runs(spec, current_server: str):
    """One built-in agent, all the way through: install, attach, run, persist.

    The assertion that makes this a claim about *this* agent rather than about
    the plumbing is on the captured system prompt. The reply is scripted, so it
    is identical for every parameter and proves nothing on its own; the prompt
    is composed from this agent's own preamble and instruction bytes, and no
    other agent's run produces it.
    """
    require_project_page()
    require_user_auth()

    coord = f"{spec.agent_id}@{builtin.BUILTIN_VERSION}"
    session = stub_db_user(
        current_server,
        username=_username(spec.agent_id),
        name=f"{spec.name} E2E",
        project_name=f"AgentRun {spec.name}",
        project_spec=_project_spec(),
    )
    token = session["token"]
    project_id = session["project"]["id"]
    base = f"{current_server}/api/agents/projects/{project_id}"

    use_scripted_llm(current_server, token)

    # 1. Install. The server resolves and writes the whole requiresAgents
    #    closure, so a composite brings its hard dependencies with it.
    api_json(f"{base}/install", token, method="POST", payload={"coord": coord})
    installed = {row["dirName"] for row in api_json(base, token)["agents"]}
    assert coord in installed, f"install did not write {coord}: {sorted(installed)}"

    # 2. Attach to a target this agent declares it accepts.
    attachment = api_json(
        f"{base}/attachments", token, method="POST",
        payload={"coord": coord, "target": _target_for(spec)},
    )
    attachment_id = attachment["attachmentId"]

    # 3. Script the turn and run it.
    leg, tool, replies = _scripted_replies(spec)
    script_agent_replies(current_server, *replies)
    run = api_json(
        f"{base}/attachments/{attachment_id}/run", token, method="POST",
        payload={"message": f"Hello {spec.name}, do your job."},
    )

    # 4. The scripted reply came back through the real route.
    assert run["coord"] == coord
    assert VISIBLE_PROSE in run["reply"], (
        f"the agent's visible prose did not survive the run: {run['reply']!r}"
    )
    assert run["executionId"]
    # Non-zero because the scripted provider reports counts on purpose: a run
    # that skipped the ledger's reserve/settle path would show none.
    assert run["usage"]["inputTokens"] > 0

    # 5. THE PER-AGENT CLAIM: this agent's own prompt bytes composed the turn.
    system = captured_system_prompt(current_server)
    instruction = builtin.read_instruction_text(coord)
    assert instruction, f"{coord} has no instruction prompt on disk"
    assert instruction.strip() in system, (
        f"the run for {coord} did not compose its own instruction; the system "
        f"turn was {len(system)} chars and began: {system[:200]!r}"
    )
    preamble = builtin.read_prompt_text(coord, "system")
    if preamble:
        assert preamble.strip() in system, (
            f"{coord} lost its system preamble - legacy call sites composed "
            "preamble + prompt, and migration parity requires both"
        )

    # 6. Both halves of the exchange persisted, so a reload restores it.
    # The transcript's own vocabulary is {"role": "user"|"agent", "text": ...};
    # sessions.py maps "agent" to the provider's "assistant" only when building
    # context, so asserting on the stored shape is the honest check here.
    turns = api_json(f"{base}/attachments/{attachment_id}/session", token)["turns"]
    roles = [t.get("role") for t in turns]
    assert "user" in roles and "agent" in roles, roles
    assert any(
        spec.name in (t.get("text") or "")
        for t in turns
        if t.get("role") == "user"
    ), "the user's own message is not in the transcript"
    assert any(
        VISIBLE_PROSE in (t.get("text") or "")
        for t in turns
        if t.get("role") == "agent"
    ), "the reply the user saw is not what was persisted"

    # 7. The characteristic leg: what this agent is actually for.
    parts = run["content"]
    kinds = [p.get("type") for p in parts]
    if leg == "mint":
        proposals = [p for p in parts if p.get("type") == "proposal"]
        assert proposals, (
            f"{coord} declares the mutate tool {tool!r} but minted no proposal; "
            f"parts were {kinds}"
        )
        assert proposals[0]["tool"] == tool
        assert proposals[0].get("proposalId")
        # DEC-006: a mutate request mints a review, it never executes. The node
        # the proposal names must be untouched until the user applies it.
        if tool == "node.content.write":
            node_id = _mint_params(tool, spec)["nodeId"]
            saved = api_json(f"{current_server}/api/projects/{project_id}", token)
            node = next(
                n for n in saved["spec"]["dataflow"]["nodes"] if n["id"] == node_id
            )
            assert PROPOSED_CONTENT not in (node.get("content") or ""), (
                "the mutate tool executed instead of minting a review"
            )
    elif leg == "read":
        # Two provider calls: the request, then the re-prompt carrying its
        # result. One call would mean the tool round never happened.
        captured = captured_agent_prompts(current_server)
        assert len(captured) >= 2, (
            f"{coord} requested {tool!r} but the run never re-prompted with a "
            f"result ({len(captured)} provider call(s))"
        )
        assert tool in json.dumps(captured[1]), (
            f"the tool result for {tool!r} never reached the model"
        )
    else:
        prompts = [p for p in parts if p.get("type") == "suggestedPrompts"]
        assert prompts, (
            f"{coord} produced no suggestedPrompts part; parts were {kinds}"
        )
        assert prompts[0]["primary"] == "What should I look at next?"


def test_the_roster_matches_the_served_catalog(current_server: str):
    """The parametrization above covers everything the catalog actually serves.

    Without this, an agent reaching the drawer by some path other than the
    roster - a published definition, a future second source - would be
    uncovered and nothing would say so.
    """
    require_project_page()
    require_user_auth()
    session = stub_db_user(
        current_server, username="agentrun_parity", name="Agent Parity",
    )
    served = {
        row["dirName"]
        for row in api_json(
            f"{current_server}/api/agents/catalog", session["token"]
        )["items"]
        if row["provenance"]["trust"] == "built-in"
    }
    covered = {f"{s.agent_id}@{builtin.BUILTIN_VERSION}" for s in builtin.BUILTIN_AGENTS}
    assert served == covered, (
        f"served but not covered: {sorted(served - covered)}; "
        f"covered but not served: {sorted(covered - served)}"
    )
