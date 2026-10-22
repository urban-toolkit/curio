"""The Node Builder's package drafts reach review.

The Node Builder asks for ``node.kind.author``. Whichever agent writes the
package, the draft must come back to the Node Builder's own chat as a
reviewed ``package.draft.apply`` proposal that the user can apply. A caller
without the ``package.draft.apply`` tool keeps a draft as text only, so this
fails wherever the Node Builder lacks that tool.

``_setup`` from ``test_delegate_draft_mint`` installs the caller and the
agent whose package-writing mode the delegation reaches, and scripts the
provider.
"""

from __future__ import annotations

import json
import re

import pytest

from utk_curio.backend.app.packages.builder import jobs as build_jobs

from .test_delegate_draft_mint import _auth, _delegate_tail, _draft, _project, _run, _setup

NODE_BUILDER = "agent.curio.node-builder@1"
TARGET = "ai.agent.notes@1"


@pytest.fixture(autouse=True)
def _fresh_jobs():
    build_jobs.reset_registry()
    yield
    build_jobs.reset_registry()


def test_the_node_builders_package_draft_reaches_review(
        client, user_and_token, tmp_curio, monkeypatch):
    _, token = user_and_token
    pid = _project(client, token)
    child_reply = "```json\n" + json.dumps({"packageDraft": _draft()}) + "\n```"
    att_id, calls = _setup(client, token, pid, monkeypatch, parent=NODE_BUILDER, replies=[
        _delegate_tail(),                        # the Node Builder asks for node.kind.author
        child_reply,                             # the writing call replies with a draft
        "Proposed, review the package above.",   # the Node Builder's next round
    ])
    run = _run(client, token, pid, att_id)
    assert run.status_code == 200, run.get_data(as_text=True)
    parts = run.get_json()["content"]

    entry = next((p for p in parts if p["type"] == "delegation"), None)
    assert entry is not None, f"the Node Builder's turn holds no delegation: {parts}"
    assert entry["capability"] == "node.kind.author"
    proposals = [p for p in parts if p["type"] == "proposal"]
    assert len(proposals) == 1, (
        "the package draft did not reach review in the Node Builder's chat; "
        f"the delegation reads {entry['status']}: {entry['summary']}"
    )
    proposal = proposals[0]
    assert entry["status"] == "ok", entry
    assert proposal["tool"] == "package.draft.apply"
    assert proposal["status"] == "pending"
    assert proposal["pins"]["target"] == TARGET
    assert re.fullmatch(r"[0-9a-fA-F]{64}", proposal["pins"]["artifactDigest"]), proposal["pins"]
    # The Node Builder's next round is told a proposal awaits review.
    assert "proposal" in calls[2][-1]["content"]

    # The Node Builder's card holds it for review.
    cards = client.get(
        f"/api/agents/projects/{pid}/attachments", headers=_auth(token),
    ).get_json()["attachments"]
    active = next(c for c in cards if c["attachmentId"] == att_id)["activeProposal"]
    assert (active["proposalId"], active["tool"], active["status"]) == (
        proposal["proposalId"], "package.draft.apply", "pending")

    # Applying the reviewed draft installs the package.
    resp = client.post(
        f"/api/agents/projects/{pid}/attachments/{att_id}"
        f"/proposals/{proposal['proposalId']}/apply",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["requiresRegistryRefresh"] is True
    assert body["installedPackage"]["dirName"] == TARGET
