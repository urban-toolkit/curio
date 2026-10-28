"""Agents and skills are entries of one Agent Catalog, run through one code: each scenario here runs for both.

An agent and a skill are imported, published, unpublished and removed through
the agents' code (``application/lifecycle.py``): the refusal of a hosted
guest (``refuse_hosted_guest``), the operator's switch on publishing, the
shared catalog's publisher rules (``publish_entry``, ``unpublish_entry``), and
the copy an account keeps of an entry it added from the shared catalog. Each
test runs its scenario for an agent, then for a skill, and names the kind
that broke it.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

from utk_curio.backend import config
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth

DF = "agent.curio.dataset-finder@1"


def _make_user(db, username: str, token: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user


class _Agent:
    """An agent of the account's own, as the Agent Catalog's routes take it."""

    noun = "agent"
    entry = "agent.test.shared-helper@1"

    def __init__(self, client):
        self.client = client

    @property
    def catalog(self):
        return publications.AGENTS

    def import_own(self, token, *, text="You help with shared things."):
        return self.client.post("/api/agents/imports/upload", json={
            "manifest": {
                "id": "agent.test.shared-helper", "name": "Shared helper", "category": "canvas",
                "version": "1.0.0", "capabilities": [{"id": "chat.reply", "contractVersion": "1"}],
                "compatibleTargets": [{"kind": "canvas", "requires": []}],
                "prompts": {"instruction": {"path": "prompts/instruction.txt", "variables": []}},
                "provenance": {"publisher": "someone", "trust": "imported"},
            },
            "prompts": {"prompts/instruction.txt": text},
        }, headers=_auth(token))

    def publish(self, token):
        return self.client.post("/api/agents/publications", json={"coord": self.entry}, headers=_auth(token))

    def unpublish(self, token):
        return self.client.delete(f"/api/agents/publications/{self.entry}", headers=_auth(token))

    def remove(self, token):
        return self.client.delete(f"/api/agents/imports/{self.entry}", headers=_auth(token))

    def add_published(self, token):
        """Add the published entry where an account uses it: a project of its own."""
        project = self.client.post("/api/projects", json={
            "name": "b", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": [],
        }, headers=_auth(token)).get_json()["id"]
        return self.client.post(f"/api/agents/projects/{project}/install", json={"coord": self.entry},
                                headers=_auth(token))

    def holds_a_copy(self, user) -> bool:
        m = storage.load_installed_agent_definition(_user_dir_key(user), self.entry)
        return m is not None and m.provenance.trust == "global"

    def holds_any(self, user) -> bool:
        return storage.user_agents_dir(_user_dir_key(user)).exists()


class _Skill:
    """A skill of the account's own, as the Agent Catalog's routes take it."""

    noun = "skill"
    entry = "shared-trees"

    def __init__(self, client):
        self.client = client

    @property
    def catalog(self):
        return publications.SKILLS

    def import_own(self, token, *, text="Count trees by block."):
        md = (f"---\nname: {self.entry}\ndescription: Use this skill when a dataflow counts street trees.\n"
              f"---\n{text}\n")
        return self.client.post("/api/agents/skills/imports", data={
            "files": [(io.BytesIO(md.encode("utf-8")), "SKILL.md")],
            "paths": json.dumps([f"{self.entry}/SKILL.md"]),
        }, content_type="multipart/form-data", headers={"Authorization": f"Bearer {token}"})

    def publish(self, token):
        return self.client.post("/api/agents/skills/publications", json={"name": self.entry}, headers=_auth(token))

    def unpublish(self, token):
        return self.client.delete(f"/api/agents/skills/publications/{self.entry}", headers=_auth(token))

    def remove(self, token):
        return self.client.delete(f"/api/agents/skills/{self.entry}", headers=_auth(token))

    def add_published(self, token):
        """Add the published entry where an account uses it: one of its agents."""
        return self.client.post(f"/api/agents/definitions/{DF}/skills", json={"skill": self.entry},
                                headers=_auth(token))

    @staticmethod
    def _store():
        """The account's skill store, imported where a test runs."""
        from utk_curio.backend.app.agents.repositories import user_skills

        return user_skills

    def holds_a_copy(self, user) -> bool:
        key, store = _user_dir_key(user), self._store()
        return store.holds(key, self.entry) and store.is_copy(store.skill_dir(key, self.entry))

    def holds_any(self, user) -> bool:
        return self._store().skills_dir(_user_dir_key(user)).exists()


KINDS = (_Agent, _Skill)


def test_a_hosted_guest_imports_publishes_unpublishes_and_removes_neither_kind(
    client, db, user_and_token, guest_user_and_token, tmp_curio,
):
    """The backend refuses each action of a hosted guest, whose account every
    guest shares, whatever the page offers it; a local run's one user, the
    shared guest without sign-in, may."""
    guest, guest_token = guest_user_and_token
    _, alice = user_and_token
    for kind in KINDS:
        entry = kind(client)
        assert entry.import_own(alice).status_code == 201, kind.noun
        assert entry.publish(alice).status_code == 201, kind.noun
        with patch.object(config, "CURIO_NO_AUTH", False):
            for action, resp in (
                (f"import {kind.noun}s", entry.import_own(guest_token)),
                (f"publish {kind.noun}s", entry.publish(guest_token)),
                (f"unpublish {kind.noun}s", entry.unpublish(guest_token)),
                (f"remove {kind.noun}s", entry.remove(guest_token)),
            ):
                assert resp.status_code == 403, (kind.noun, action, resp.get_data(as_text=True))
                assert resp.get_json()["error"] == (
                    f"Guests on this Curio cannot {action}, because every guest shares one account. "
                    f"Sign in with an account to {action}."
                ), (kind.noun, action)
            assert not entry.holds_any(guest), kind.noun
            assert entry.catalog.is_published(entry.entry), kind.noun
        if kind is _Agent:
            with patch.object(config, "CURIO_NO_AUTH", False):
                added = client.post("/api/agents/imports", json={"coord": DF}, headers=_auth(guest_token))
            assert added.status_code == 403 and "cannot import agents" in added.get_json()["error"], added.get_json()
        with patch.object(config, "CURIO_NO_AUTH", True):
            assert entry.import_own(guest_token).status_code == 201, kind.noun


def test_publishing_either_kind_is_refused_while_the_operator_switch_is_off(client, user_and_token, tmp_curio,
                                                                            monkeypatch):
    from utk_curio.backend.app.packages.routes import common as packages_routes_common

    _, token = user_and_token
    for kind in KINDS:
        entry = kind(client)
        assert entry.import_own(token).status_code == 201, kind.noun
        assert entry.publish(token).status_code == 201, kind.noun
        monkeypatch.setattr(packages_routes_common, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", False)
        for resp in (entry.publish(token), entry.unpublish(token)):
            assert resp.status_code == 403, (kind.noun, resp.get_data(as_text=True))
            assert resp.get_json()["error"] == packages_routes_common.CATALOG_PUBLISH_DISABLED_MESSAGE, kind.noun
        assert entry.catalog.is_published(entry.entry), kind.noun
        monkeypatch.setattr(packages_routes_common, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", True)


def test_only_the_publisher_publishes_over_or_unpublishes_an_entry_of_either_kind(
    client, db, user_and_token, tmp_curio,
):
    _, alice = user_and_token
    _make_user(db, "bob", "bob-token")
    for kind in KINDS:
        entry = kind(client)
        assert entry.import_own(alice).status_code == 201, kind.noun
        assert entry.publish(alice).status_code == 201, kind.noun
        assert entry.import_own("bob-token", text="Bob's own words.").status_code == 201, kind.noun
        for resp, verb in ((entry.publish("bob-token"), "replace"), (entry.unpublish("bob-token"), "unpublish")):
            assert resp.status_code == 403, (kind.noun, resp.get_data(as_text=True))
            assert resp.get_json()["error"] == (
                f"only the account that published this {kind.noun} can {verb} it"
            ), kind.noun
        assert entry.catalog.is_published(entry.entry), kind.noun
        assert entry.catalog.publisher_of(entry.entry) == _user_dir_key(user_and_token[0]), kind.noun
        assert entry.publish(alice).status_code == 201, kind.noun
        assert entry.unpublish(alice).status_code == 200, kind.noun
        assert not entry.catalog.is_published(entry.entry), kind.noun


def test_an_entry_of_either_kind_added_from_the_shared_catalog_outlives_its_unpublication(
    client, db, user_and_token, tmp_curio,
):
    """#438, for both kinds: adding a published entry copies it into the
    adder's account, so its publisher's Unpublish takes it from no one who
    added it, and the copy is never the adder's to publish."""
    _, alice = user_and_token
    bob = _make_user(db, "bob", "bob-token")
    for kind in KINDS:
        entry = kind(client)
        assert entry.import_own(alice).status_code == 201, kind.noun
        assert entry.publish(alice).status_code == 201, kind.noun
        added = entry.add_published("bob-token")
        assert added.status_code in (200, 201), (kind.noun, added.get_data(as_text=True))
        assert entry.holds_a_copy(bob), kind.noun
        assert entry.unpublish(alice).status_code == 200, kind.noun
        assert entry.holds_a_copy(bob), kind.noun
        refused = entry.publish("bob-token")
        assert refused.status_code == 400, (kind.noun, refused.get_data(as_text=True))
        assert not entry.catalog.is_published(entry.entry), kind.noun
