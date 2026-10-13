"""A direct Package Builder reply that IS the build request becomes the
package.draft.apply request (plans/package-builder-direct-draft-memo.md)."""

from __future__ import annotations

import json

from utk_curio.backend.app.agents.application import tool_rounds

DRAFT = {"mode": "create", "manifest": {"id": "curio.notes", "templates": []},
         "files": {"sources/note.tsx": {"text": "export {}"}}}
GRANTED = {"granted": ["dataflow.read", "packages.catalog", "package.draft.apply"]}


def _reply(body: str) -> str:
    return "Here is the Curio Notes package.\n\n```json\n" + body + "\n```\n\nReview and apply it."


def test_bare_draft_is_recovered_as_the_draft_request():
    kind, parts, visible, req = tool_rounds._handle_tool_reply(GRANTED, _reply(json.dumps(DRAFT)), [], 0)
    assert kind == "request"
    assert req["tool"] == "package.draft.apply" and req["params"] == DRAFT
    assert "```" not in visible and "Review and apply it." in visible


def test_without_the_grant_the_draft_stays_text():
    granted = {"granted": ["dataflow.read", "packages.catalog"]}
    kind, parts, visible, req = tool_rounds._handle_tool_reply(granted, _reply(json.dumps(DRAFT)), [], 0)
    assert (kind, visible, req) == ("none", None, None)


def test_broken_draft_gets_a_correction_round():
    broken = '{"mode": "create", "manifest": {"id": "curio.notes", "templates": ['
    kind, errors, visible, req = tool_rounds._handle_tool_reply(GRANTED, _reply(broken), [], 0)
    assert kind == "correct" and req is None
    assert errors[0].startswith("the JSON did not parse")


def test_broken_draft_at_the_cap_shows_a_card_not_the_source():
    broken = '{"mode": "create", "manifest": {"id": "curio.notes", "templates": ['
    kind, parts, visible, req = tool_rounds._handle_tool_reply(
        GRANTED, _reply(broken), [], tool_rounds.MAX_TOOL_ROUNDS)
    assert kind == "cap" and req is None
    assert parts[-1]["title"] == "Proposal not created"
    assert '"manifest"' not in visible and "Review and apply it." in visible


def test_unrelated_json_is_left_alone():
    kind, _, _, req = tool_rounds._handle_tool_reply(GRANTED, _reply(json.dumps({"rows": 3})), [], 0)
    assert (kind, req) == ("none", None)


def test_an_invalid_build_request_is_a_free_parameter_refusal():
    # Rejected before any store or build work (dev/105 D2): the correction
    # must not spend one of the run's tool rounds.
    from utk_curio.backend.app.agents.application.proposals import mint

    status, text, part = mint._mint_package_draft_apply(
        "nobody", "no-project", {}, {"params": {"mode": "create", "manifest": {}}})
    assert status == "refused" and part is None
    assert isinstance(text, tool_rounds.ParamRefusal)
    assert text.startswith("invalid build request:")
