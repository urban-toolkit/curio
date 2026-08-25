"""dev/105 commit 4 — the field replay: the Researcher's live 2026-08-25 run
(session ``c59aae2f…``, model gemma4), scripted move for move against the
fake provider, must now end in a reviewed proposal instead of a chat-only
answer.

Live sequence and why each step lost before dev/105:
  round 1  dataflow.read / web.search           — productive
  round 2  node.create curio.postits/post-it-note@1 — REFUSED (a Python compute
           template; not authorable) — one round spent on a correction
  round 3  package.install "curio.notes"        — REFUSED (bare id; the mint
           exact-matched the dirName and pointed at packages.catalog, a tool
           the Researcher does not hold) — the last round spent
  → MAX_TOOL_ROUNDS reached; the AUTHOR rung was unreachable; the model said
    "not in the catalog" (false) and answered in chat.

Variant A (the live project): the note package sits in the store, not
enlisted. The replay must mint ONE package.install proposal pinned to the
canonical dirName, add no node, and leave rounds to spare.
Variant B (no note template anywhere): the same two misses, then the AUTHOR
delegation — which sat at round 4 before commit 2 and now lands at round 2.
"""
from __future__ import annotations

import json

from utk_curio.backend.app.agents import services as agent_services

from .test_delegate_draft_mint import (
    _auth,
    _delegate_tail,
    _draft,
    _project,
    _run,
    _setup,
)


def _tool(tool, params):
    return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": tool, "params": params}}) + "\n```"


def _read_canvas():
    return _tool("dataflow.read", {})


def _create_on_the_postit():
    # The node type the model saw on the canvas — a compute template.
    return _tool("node.create", {
        "nodeType": "curio.postits/post-it-note@1",
        "content": "whats the weather in Paris?",
        "title": "Question",
        "appearance": {"backgroundColor": "yellow"},
    })


def _install_bare_id():
    return _tool("package.install", {"dirName": "curio.notes", "reason": "notes need it"})


def _write_package(user_key, dir_name, manifest, files=()):
    from utk_curio.backend.app.packages.storage import user_packageages_dir

    d = user_packageages_dir(user_key) / dir_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for rel, text in files:
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _postits_manifest():
    """The live ``curio.postits@1``: a Python computation template with an
    output port and no behavior — a blank compute box, not a note."""
    return {
        "id": "curio.postits", "version": "1.0.0", "name": "Post-it Notes",
        "publisher": "Package Builder", "description": "", "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [{
            "id": "post-it-note", "label": "Post-it Note", "category": "computation",
            "engine": "python", "editor": "none", "hasCode": False,
            "inputPorts": [], "outputPorts": [{"cardinality": "1", "types": ["JSON"]}],
            "source": "sources/default.py",
        }],
        "createdAt": "2026-08-21T16:42:23Z",
    }


def _notes_manifest():
    """The live ``curio.notes@1``: the real note surface (behavior + editor none)."""
    return {
        "id": "curio.notes", "version": "1.0.0", "name": "Simple Notes",
        "publisher": "Package Builder", "description": "Colored notes.", "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [{
            "id": "note-surface", "label": "Note", "category": "visualization",
            "engine": "javascript", "editor": "none", "behavior": "note-behavior",
            "hasCode": False, "description": "A note surface.",
            "inputPorts": [], "outputPorts": [],
        }],
        "createdAt": "2026-08-20T22:14:56Z",
    }


def _field_store(user_key, project_id, *, with_notes: bool):
    """Reproduce the live store: postits enlisted in the project; the note
    package present in the store but NOT enlisted (variant A) or absent
    entirely (variant B)."""
    from utk_curio.backend.app.packages import services as packages_services

    from .test_routes import TestNodeCreate

    # The built-in package (the twelve code templates the live roster listed);
    # without a readable store copy the landscape read fails and the roster
    # degrades to nothing — the delegate harness never needed it before.
    TestNodeCreate()._write_builtin_package(user_key)
    _write_package(user_key, "curio.postits@1", _postits_manifest(),
                   files=[("sources/default.py", "def main(): return {}\n")])
    packages_services.install_to_project(user_key, project_id, "curio.postits@1")
    if with_notes:
        _write_package(user_key, "curio.notes@1", _notes_manifest())


def _results(calls):
    """Every tool/delegate result the model was handed, in order. The fake
    provider records the ONE mutable message list by reference, so
    ``calls[i][-1]`` is always the run's final message — read the history."""
    return [
        m["content"] for m in calls[-1]
        if m["role"] == "user" and m["content"].startswith(("[tool result]", "[delegate result]"))
    ]


def _execution(client, token, project_id, att_id):
    turns = client.get(
        f"/api/agents/projects/{project_id}/attachments/{att_id}/session",
        headers=_auth(token),
    ).get_json()["turns"]
    # The last RUN turn — applied-proposal log turns carry no execution.
    return next(t["execution"] for t in reversed(turns) if "execution" in t)


def _spec_nodes(client, token, project_id):
    return client.get(
        f"/api/projects/{project_id}", headers=_auth(token)
    ).get_json()["spec"]["dataflow"]["nodes"]


def _create_note(title, body):
    # dev/105 A2: the way the live model spoke after commit 5 — title and
    # content, NO appearance (the contract had never named it).
    return _tool("node.create", {
        "nodeType": "curio.notes/note-surface", "title": title, "content": body,
    })


def _apply(client, token, project_id, att_id, proposal_id):
    return client.post(
        f"/api/agents/projects/{project_id}/attachments/{att_id}"
        f"/proposals/{proposal_id}/apply",
        headers=_auth(token),
    )


def _install_with_notes():
    # dev/105 A3: the ENLIST request carries the findings (the AUTHOR shape).
    return _tool("package.install", {
        "dirName": "curio.notes@1",
        "reason": "notes need a note template",
        "notes": [
            {"title": "Question", "content": "what's the weather in Paris?", "color": "yellow"},
            {"title": "Weather in Paris", "content": "### Weather in Paris\n- **Now:** ~21°C"},
        ],
    })


class TestFieldReplay:
    def test_variant_d_apply_on_the_install_card_queues_the_notes_one_card_at_a_time(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The owner's ask after the 14:09 run: Apply on the install card must
        proceed to the notes — as cards BELOW it, one node at a time — with no
        second message. The install apply queues the A16 sequence and returns
        the ordered ids; applying each (the frontend walk) lands its node."""
        from utk_curio.backend.app.packages import node_appearance
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _install_with_notes(),
            "The install awaits your review; the notes follow it.",
        ])
        _field_store(_user_dir_key(user), pid, with_notes=True)  # store-only, not enlisted

        run = _run(client, token, pid, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        (install,) = [p for p in run.get_json()["content"] if p["type"] == "proposal"]
        assert install["tool"] == "package.install"
        assert install["summary"] == "Install package · Simple Notes · 2 notes to follow"
        assert "Question · what's the weather in Paris?" in install["preview"]
        assert len(_spec_nodes(client, token, pid)) == 0

        # Apply the install: the package is enlisted, the notes are QUEUED (not
        # inserted), their cards ride the applied turn below the install card.
        applied = _apply(client, token, pid, att_id, install["proposalId"])
        assert applied.status_code == 200, applied.get_data(as_text=True)
        body = applied.get_json()
        assert body["installedPackage"]["dirName"] == "curio.notes@1"
        follow_ups = body["followUpProposals"]
        assert len(follow_ups) == 2
        assert "createdNodes" not in body  # nothing inserted by the install apply
        # dev/105 A4: the lockfile changed — the frontend must pulse its registry
        # BEFORE the walk paints the notes (the 15:04 "Loading node…" run).
        assert body["requiresRegistryRefresh"] is True
        assert len(_spec_nodes(client, token, pid)) == 0
        turns = client.get(
            f"/api/agents/projects/{pid}/attachments/{att_id}/session", headers=_auth(token),
        ).get_json()["turns"]
        applied_turn = turns[-1]
        assert "2 notes queued below" in applied_turn["text"]
        cards = [p for p in applied_turn["content"] if p.get("type") == "proposal"]
        assert [p["proposalId"] for p in cards] == follow_ups  # cards below, in order
        assert cards[0]["summary"].endswith("· Question")

        # The frontend walk: one apply at a time, each landing exactly one node.
        yellow = node_appearance.normalize_appearance({"backgroundColor": "yellow"})
        green = node_appearance.normalize_appearance({"backgroundColor": "green"})
        for i, fid in enumerate(follow_ups):
            assert _apply(client, token, pid, att_id, fid).status_code == 200
            assert len(_spec_nodes(client, token, pid)) == i + 1
        notes = [n for n in _spec_nodes(client, token, pid) if "note-surface" in n["type"]]
        assert [(n["title"], n["metadata"]["appearance"]) for n in notes] == [
            ("Question", yellow), ("Weather in Paris", green),
        ]

    def test_variant_c_enlisted_notes_land_titled_and_colored(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """The 14:09 live run (after commit 5): the ladder closed, two notes
        landed — white and headed "Note". Now: titles round-trip and the A13
        defaults fill the colors the model omitted (question yellow, answer
        green) on the Researcher's own attachment path."""
        from utk_curio.backend.app.packages import node_appearance
        from utk_curio.backend.app.packages import services as packages_services
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _create_note("Question", "what's the weather in Paris?"),
            _create_note("Weather in Paris", "### Weather in Paris\n- **Now:** ~21°C"),
            "Two notes await your review.",
        ])
        key = _user_dir_key(user)
        _field_store(key, pid, with_notes=True)
        packages_services.install_to_project(key, pid, "curio.notes@1")  # enlisted

        run = _run(client, token, pid, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        proposals = [p for p in run.get_json()["content"] if p["type"] == "proposal"]
        assert [p["tool"] for p in proposals] == ["node.create", "node.create"]
        assert proposals[0]["summary"].endswith("· Question")
        for p in proposals:
            assert _apply(client, token, pid, att_id, p["proposalId"]).status_code == 200

        yellow = node_appearance.normalize_appearance({"backgroundColor": "yellow"})
        green = node_appearance.normalize_appearance({"backgroundColor": "green"})
        notes = [n for n in _spec_nodes(client, token, pid) if "note-surface" in n["type"]]
        assert [(n.get("title"), n["metadata"]["appearance"]) for n in notes] == [
            ("Question", yellow), ("Weather in Paris", green),
        ]
        assert "goal" not in notes[0]  # title is the header, not the purpose line

        execution = _execution(client, token, pid, att_id)
        assert [c["status"] for c in execution["toolCalls"]] == ["proposed", "proposed"]

    def test_live_sequence_ends_in_an_install_proposal_not_a_chat_answer(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key

        assert agent_services.MAX_TOOL_ROUNDS == 3
        user, token = user_and_token
        pid = _project(client, token)
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _read_canvas(),            # round 1 — productive
            _create_on_the_postit(),   # refused: free correction 1
            _install_bare_id(),        # round 2 — RESOLVES to curio.notes@1 and mints
            "The weather in Paris is warm; the notes await your review above.",
        ])
        _field_store(_user_dir_key(user), pid, with_notes=True)
        nodes_before = len(_spec_nodes(client, token, pid))

        run = _run(client, token, pid, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]

        proposals = [p for p in parts if p["type"] == "proposal"]
        assert [p["tool"] for p in proposals] == ["package.install"]
        assert proposals[0]["pins"]["dirName"] == "curio.notes@1"  # canonical, not "curio.notes"
        assert len(_spec_nodes(client, token, pid)) == nodes_before  # nothing landed without Apply

        # The corrections the model received were actionable and truthful.
        read_result, refusal, install_result = _results(calls)
        assert read_result.startswith("[tool result] dataflow.read: ok")
        assert "does not hold authored content" in refusal
        assert "No further tool calls" not in refusal  # the refusal was free
        assert "proposal" in install_result and "not in the Nodes Catalog" not in install_result
        # And the roster itself said nothing listed renders a note, and named the rung.
        system = calls[0][0]["content"]
        marker = "Available node templates"
        roster = system[system.find(marker):][:600] if marker in system else "<no roster section>"
        assert "None of these renders a note" in system, roster
        assert "(package curio.notes@1)" in system, roster

        execution = _execution(client, token, pid, att_id)
        assert [c["status"] for c in execution["toolCalls"]] == ["ok", "refused", "proposed"]
        assert execution["refusedRounds"] == 1
        assert execution["status"] == "ok"

    def test_no_note_template_anywhere_reaches_the_author_rung_within_budget(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        """Before commit 2 this delegation sat at round 4 of 3 — the ladder's
        last rung was unreachable after two misses by construction."""
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        pid = _project(client, token)
        child_reply = "```json\n" + json.dumps({"packageDraft": _draft()}) + "\n```"
        att_id, calls = _setup(client, token, pid, monkeypatch, replies=[
            _read_canvas(),            # round 1
            _create_on_the_postit(),   # refused: free correction 1
            _install_bare_id(),        # refused (no such package): free correction 2
            _delegate_tail(),          # round 2 — AUTHOR
            child_reply,               # CHILD (Package Builder): the draft
            "Proposed — review the package above.",
        ])
        _field_store(_user_dir_key(user), pid, with_notes=False)

        run = _run(client, token, pid, att_id)
        assert run.status_code == 200, run.get_data(as_text=True)
        parts = run.get_json()["content"]
        proposal = next(p for p in parts if p["type"] == "proposal")
        assert proposal["tool"] == "package.draft.apply"
        assert proposal["pins"]["target"] == "ai.agent.notes@1"
        assert any(p["type"] == "delegation" for p in parts)

        # The miss hint named a source this run can read — not packages.catalog.
        _read, refusal, miss, delegated = _results(calls)
        assert "does not hold authored content" in refusal
        assert "not in the Nodes Catalog" in miss
        assert "packages.catalog" not in miss
        assert "No further tool calls" not in miss
        assert delegated.startswith("[delegate result] agent.package-builder@1.0.0 (node.kind.author): ok")

        execution = _execution(client, token, pid, att_id)
        assert [c["status"] for c in execution["toolCalls"]] == ["ok", "refused", "refused"]
        assert execution["refusedRounds"] == 2
        assert len(execution["delegations"]) == 1
