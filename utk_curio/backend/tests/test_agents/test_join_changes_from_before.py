"""An agent's change to a Spatial Join kept from before the join's operation
and output were its widgets, when the join kept them at
``metadata.spatialJoin`` and held no code, undoes as the saved-join rule
converts the join (``projects/saved_joins.py``): a dataflow saved then reads
with the join's code and its two widgets, and so does the change.

- A change of the join's setting (``node.settings.write``) is a change of the
  widgets its keys are saved for: Undo puts back what they held before it,
  while they hold what it set, and leaves the other widget as it is. Before,
  the change was checked against a setting no join keeps any more, and Undo
  was refused saying someone had changed the node after.
- A join an agent created (``node.create``) holds no code in its change, and
  the join's code now: Undo compares it as it reads now and takes it away.

Each change is kept on its attachment as the agents kept it then, with what
its Undo needs: the setting it gave, the steps back to the one before (the
join's defaults, then its own setting) and the digest of what it set.
"""
from __future__ import annotations

import hashlib
import json

from utk_curio.backend.tests.test_agents.test_map_edits_grounding import _project
from utk_curio.backend.tests.test_agents.test_node_settings_write import (
    JOIN_CODE,
    OPERATION,
    OUTPUT,
    _resave,
    _saved,
    _undo,
)
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import _attach, _install

NB = "agent.curio.node-builder@1"
JOIN = "curio.builtin/spatial-join"
#: The join's defaults, the first step back a settings change kept then.
DEFAULTS = {"predicate": "intersects", "output": "pairs"}


def _join_saved_then(setting: dict | None) -> dict:
    """A Spatial Join as Curio saved it before it had code: no code and no
    widgets, its setting at ``metadata.spatialJoin``."""
    node = {"id": "join", "type": JOIN, "title": "Trees in parks", "content": "", "x": 0, "y": 0}
    if setting:
        node["metadata"] = {"spatialJoin": dict(setting)}
    return node


def _basis_then(setting: dict | None) -> str:
    """The digest a settings change kept then of what it set on the join."""
    touched = {"type": JOIN, "settings": {"spatialJoin": setting} if setting else {}, "widgets": []}
    return hashlib.sha256(json.dumps(touched, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _setting_changed_then(given: dict, before: dict | None, after: dict | None) -> dict:
    """``node.settings.write``'s change of the join's setting, as it was kept:
    *given* is what it set, *before* and *after* the join's setting before and
    after it, its defaults left out."""
    undo = [{"spatialJoin": dict(DEFAULTS)}, *([{"spatialJoin": dict(before)}] if before else [])]
    return {
        "changeId": "c-setting", "tool": "node.settings.write", "kind": "settings",
        "summary": "Set the join's operation", "status": "applied", "nodeId": "join",
        "settings": {"spatialJoin": dict(given)}, "undo": undo, "basisAfter": _basis_then(after),
    }


def _kept(client, user, token, node: dict, change: dict, target: dict) -> tuple[str, str]:
    """A project holding *node*, Node Builder attached to *target*, and
    *change* kept on the attachment: the project and the attachment."""
    from utk_curio.backend.app.agents.application import attachments, spec_reads
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    project = _project(client, user, token, [node])
    _install(client, token, project, NB)
    att = _attach(client, token, project, NB, target=target)
    key = _user_dir_key(user)
    spec = spec_reads._live_spec_or_404(key, project)
    attachments.get_attachment(spec, att)["changes"] = [change]
    dataflow_docs.write(key, project, spec, dataflow_docs.by_agent(None, key, "proposal"))
    return project, att


class TestASettingChangeFromBefore:
    """The agent set the operation to within on a join whose output the
    person had set to counts: the join saved then holds within and counts."""

    ON_THE_JOIN = {"kind": "node", "targetId": "join"}

    def _kept(self, client, user, token):
        change = _setting_changed_then({"predicate": "within"}, {"output": "counts"},
                                       {"predicate": "within", "output": "counts"})
        node = _join_saved_then({"predicate": "within", "output": "counts"})
        return _kept(client, user, token, node, change, self.ON_THE_JOIN)

    def test_undo_puts_the_operation_back_and_keeps_the_output(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        project, att = self._kept(client, user, token)
        join = _saved(user, project)["join"]
        assert join["content"] == JOIN_CODE
        assert join["metadata"]["widgets"] == [{**OPERATION, "value": "within"}, {**OUTPUT, "value": "counts"}]

        response = _undo(client, token, project, att, {"changeId": "c-setting"})
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["status"] == "undone"
        join = _saved(user, project)["join"]
        assert join["metadata"]["widgets"] == [{**OPERATION, "value": "intersects"}, {**OUTPUT, "value": "counts"}]
        assert "spatialJoin" not in join["metadata"] and join["content"] == JOIN_CODE
        # A canvas no doc binds takes it as any widget change's Undo.
        assert [(step["kind"], step["nodeId"], step["settings"]) for step in response.get_json()["canvas"]] == [
            ("node-settings-applied", "join", {"widgets": {"operation": "intersects"}}),
        ]
        assert _undo(client, token, project, att, {"changeId": "c-setting"}).status_code == 409

    def test_an_operation_someone_picked_after_is_kept_and_the_undo_refused(
        self, client, user_and_token, tmp_curio,
    ):
        user, token = user_and_token
        project, att = self._kept(client, user, token)
        join = _saved(user, project)["join"]
        join["metadata"]["widgets"][0]["value"] = "contains"
        _resave(client, token, project, [join])

        response = _undo(client, token, project, att, {"changeId": "c-setting"})
        assert response.status_code == 409, response.get_json()
        assert "changed this node after; nothing was undone." in response.get_json()["error"]
        assert _saved(user, project)["join"]["metadata"]["widgets"][0]["value"] == "contains"

    def test_an_output_someone_picked_after_is_no_part_of_the_change(self, client, user_and_token, tmp_curio):
        """Undo checks only the widget the change set, as any widget change's."""
        user, token = user_and_token
        project, att = self._kept(client, user, token)
        join = _saved(user, project)["join"]
        join["metadata"]["widgets"][1]["value"] = "pairs"
        _resave(client, token, project, [join])

        response = _undo(client, token, project, att, {"changeId": "c-setting"})
        assert response.status_code == 200, response.get_json()
        assert _saved(user, project)["join"]["metadata"]["widgets"] == [
            {**OPERATION, "value": "intersects"}, {**OUTPUT, "value": "pairs"},
        ]


class TestAJoinCreatedBefore:
    """node.create placed a join with no code, its operation within."""

    CHANGE = {
        "changeId": "c-join", "tool": "node.create", "kind": "node", "summary": "Add a Spatial Join",
        "status": "applied", "nodeId": "join", "created": [{"id": "join", "type": JOIN, "content": ""}],
    }

    def test_undo_takes_the_join_away(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        node = _join_saved_then({"predicate": "within"})
        project, att = _kept(client, user, token, node, dict(self.CHANGE), {"kind": "canvas"})
        assert _saved(user, project)["join"]["content"] == JOIN_CODE

        response = _undo(client, token, project, att, {"changeId": "c-join"})
        assert response.status_code == 200, response.get_json()
        assert "join" not in _saved(user, project)
        [removal] = response.get_json()["canvas"]
        assert removal["removedNodeIds"] == ["join"]

    def test_a_join_someone_wrote_in_after_is_kept_and_the_undo_refused(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        node = _join_saved_then({"predicate": "within"})
        project, att = _kept(client, user, token, node, dict(self.CHANGE), {"kind": "canvas"})
        join = _saved(user, project)["join"]
        join["content"] = JOIN_CODE.replace("output=[!! output !!]", "output='counts'")
        _resave(client, token, project, [join])

        response = _undo(client, token, project, att, {"changeId": "c-join"})
        assert response.status_code == 409, response.get_json()
        assert "changed this node after; nothing was undone." in response.get_json()["error"]
        assert _saved(user, project)["join"]["content"] == join["content"]
