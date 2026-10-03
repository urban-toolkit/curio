"""Integration tests for the /api/agents catalog routes (routes/catalog.py).

My Imports, the global catalog, publications, agent definitions and
provider models."""

from __future__ import annotations

import shutil

import pytest

from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.projects.services import _user_dir_key

from utk_curio.backend.tests._support.agent_routes import (
    _auth,
    _write_def,
)


class TestMyImports:
    def test_empty(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        resp = client.get("/api/agents/imports", headers=_auth(token))
        assert resp.status_code == 200
        assert resp.get_json() == {"agents": []}

    def test_import_then_listed(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user)
        r = client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        listed = client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]
        assert [a["dirName"] for a in listed] == [coord]
        card = listed[0]
        assert card["id"] == "agent.my-explainer"
        assert card["capabilities"] == ["node.explain"]
        assert card["hooks"] == ["node"]
        assert card["imported"] is True

    def test_import_unknown_definition_404(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        r = client.post("/api/agents/imports", json={"coord": "agent.ghost@1.0.0"}, headers=_auth(token))
        assert r.status_code == 404

    def test_import_missing_coord_400(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        r = client.post("/api/agents/imports", json={}, headers=_auth(token))
        assert r.status_code == 400

    def test_remove_import(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user)
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        r = client.delete(f"/api/agents/imports/{coord}", headers=_auth(token))
        assert r.status_code == 200
        assert client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"] == []

    def test_requires_auth(self, client, tmp_curio):
        assert client.get("/api/agents/imports").status_code in (401, 403)


class TestGlobalCatalog:
    def test_lists_all_builtins(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        resp = client.get("/api/agents/catalog", headers=_auth(token))
        assert resp.status_code == 200
        agents = resp.get_json()["agents"]
        # The ten catalog cards; the internal built-ins run only as delegates.
        assert len(agents) == 10
        assert all(a["scope"] == "browse" and a["provenance"]["trust"] == "built-in" for a in agents)
        assert all(a["inCatalog"] is True for a in agents)
        ids = {a["id"] for a in agents}
        assert ids == {s.agent_id for s in builtin.BUILTIN_AGENTS if s.in_catalog}
        assert "agent.dataflow-planner" not in ids

    def test_import_a_builtin(self, client, user_and_token, tmp_curio):
        # A built-in resolves without being written to the user store first.
        _, token = user_and_token
        coord = "agent.chat-agent@1.0.0"
        r = client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        imports_listed = client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]
        assert [a["dirName"] for a in imports_listed] == [coord]
        # And the catalog now marks it imported.
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        chat = next(a for a in cat if a["id"] == "agent.chat-agent")
        assert chat["imported"] is True

    def test_install_a_builtin_into_project(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        coord = "agent.connection-builder@1.0.0"
        r = client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord},
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        assert r.get_json()["agents"] == [coord]
        cat = client.get(
            f"/api/agents/catalog?projectId={alice_project}", headers=_auth(token)
        ).get_json()["agents"]
        builder = next(a for a in cat if a["id"] == "agent.connection-builder")
        assert builder["installedInProject"] is True

    def test_an_internal_agent_is_never_imported_or_installed(
        self, client, user_and_token, tmp_curio, alice_project
    ):
        _, token = user_and_token
        coord = "agent.dataflow-planner@1.0.0"
        imported = client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        assert imported.status_code == 400
        assert "runs only as a delegate" in imported.get_json()["error"]
        installed = client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": coord}, headers=_auth(token),
        )
        assert installed.status_code == 400
        # So it cannot be attached either: attaching needs it installed.
        attached = client.post(
            f"/api/agents/projects/{alice_project}/attachments",
            json={"coord": coord, "target": {"kind": "canvas"}}, headers=_auth(token),
        )
        assert attached.status_code == 400


class TestPublish:
    def test_publish_owned_import_appears_in_catalog(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user, "agent.my-custom", "1.0.0")  # owned, store-backed
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        r = client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        pub = next(a for a in cat if a["id"] == "agent.my-custom")
        assert pub["published"] is True

    def test_publish_builtin_rejected(self, client, user_and_token, tmp_curio):
        # A built-in is not an owned store-backed import → cannot be published.
        _, token = user_and_token
        client.post("/api/agents/imports", json={"coord": "agent.connection-builder@1.0.0"}, headers=_auth(token))
        r = client.post(
            "/api/agents/publications",
            json={"coord": "agent.connection-builder@1.0.0"},
            headers=_auth(token),
        )
        assert r.status_code == 400

    def test_publish_not_imported_rejected(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user, "agent.my-custom", "1.0.0")  # in store but not imported
        r = client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token))
        assert r.status_code == 400

    def test_publishable_flag_owned_vs_builtin(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        client.post("/api/agents/imports", json={"coord": "agent.connection-builder@1.0.0"}, headers=_auth(token))
        coord = _write_def(user, "agent.my-custom", "1.0.0")
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        by_id = {a["id"]: a for a in client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]}
        assert by_id["agent.connection-builder"]["publishable"] is False  # built-in
        assert by_id["agent.my-custom"]["publishable"] is True  # owned store-backed

    def test_unpublish(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user, "agent.my-custom", "1.0.0")
        client.post("/api/agents/imports", json={"coord": coord}, headers=_auth(token))
        client.post("/api/agents/publications", json={"coord": coord}, headers=_auth(token))
        r = client.delete(f"/api/agents/publications/{coord}", headers=_auth(token))
        assert r.status_code == 200
        cat = client.get("/api/agents/catalog", headers=_auth(token)).get_json()["agents"]
        assert not any(a["id"] == "agent.my-custom" for a in cat)


class TestUnpublishKeepsAddersCopies:
    """#438: adding a published agent copies it into the adder's store, as the
    Data Catalog does with a shared dataset and the Node Catalog with a
    package, so its publisher's Unpublish no longer breaks it for everyone who
    added it. Ownership of the publication is the publisher record, since every
    adder now holds a copy."""

    COORD = "agent.shared-helper@1.0.0"

    @staticmethod
    def _make_user(db, username, token):
        from utk_curio.backend.app.users.models import User, UserSession

        u = User(username=username, name=username.title(), email=f"{username}@test.com")
        db.session.add(u)
        db.session.flush()
        db.session.add(UserSession(user_id=u.id, token=token))
        db.session.commit()
        return u

    def _publish_as_alice(self, client, token):
        r = client.post(
            "/api/agents/imports/upload",
            json={
                "manifest": {
                    "id": "agent.shared-helper", "name": "Shared helper", "category": "canvas",
                    "version": "1.0.0",
                    "capabilities": [{"id": "chat.reply", "contractVersion": "1"}],
                    "compatibleTargets": [{"kind": "canvas", "requires": []}],
                    "prompts": {"instruction": {"path": "prompts/instruction.txt", "variables": []}},
                    "provenance": {"publisher": "alice", "trust": "imported"},
                },
                "prompts": {"prompts/instruction.txt": "You help with shared things."},
            },
            headers=_auth(token),
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        client.post("/api/agents/imports", json={"coord": self.COORD}, headers=_auth(token))
        r = client.post("/api/agents/publications", json={"coord": self.COORD}, headers=_auth(token))
        assert r.status_code == 201, r.get_data(as_text=True)

    def _bob_adds_and_attaches(self, client, db):
        self._make_user(db, "bob", "bob-token")
        project = client.post(
            "/api/projects",
            json={"name": "b", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
            headers=_auth("bob-token"),
        ).get_json()["id"]
        r = client.post(f"/api/agents/projects/{project}/install",
                        json={"coord": self.COORD}, headers=_auth("bob-token"))
        assert r.status_code == 201, r.get_data(as_text=True)
        r = client.post(f"/api/agents/projects/{project}/attachments",
                        json={"coord": self.COORD, "target": {"kind": "canvas"}}, headers=_auth("bob-token"))
        assert r.status_code == 201, r.get_data(as_text=True)
        return project, r.get_json()["attachmentId"]

    def test_an_adder_keeps_running_the_agent_after_its_publisher_unpublishes(
        self, client, db, user_and_token, tmp_curio, monkeypatch,
    ):
        sent = []
        monkeypatch.setattr(
            "utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn",
            lambda config, messages, usage_out=None, **kw: sent.append(messages) or "ok",
        )
        _, alice = user_and_token
        self._publish_as_alice(client, alice)
        project, att_id = self._bob_adds_and_attaches(client, db)

        r = client.delete(f"/api/agents/publications/{self.COORD}", headers=_auth(alice))
        assert r.status_code == 200, r.get_data(as_text=True)

        r = client.post(f"/api/agents/projects/{project}/attachments/{att_id}/run",
                        json={"message": "hi"}, headers=_auth("bob-token"))
        assert r.status_code == 200, r.get_data(as_text=True)
        assert any("You help with shared things." in str(m) for m in sent[0])
        imports = client.get("/api/agents/imports", headers=_auth("bob-token")).get_json()["agents"]
        assert all(a["id"] != "agent.shared-helper" or a["publishable"] is False for a in imports)

    def test_an_adder_can_neither_unpublish_nor_republish_it(
        self, client, db, user_and_token, tmp_curio,
    ):
        _, alice = user_and_token
        self._publish_as_alice(client, alice)
        self._bob_adds_and_attaches(client, db)
        client.post("/api/agents/imports", json={"coord": self.COORD}, headers=_auth("bob-token"))

        r = client.delete(f"/api/agents/publications/{self.COORD}", headers=_auth("bob-token"))
        assert r.status_code == 403, r.get_data(as_text=True)
        r = client.post("/api/agents/publications", json={"coord": self.COORD}, headers=_auth("bob-token"))
        assert r.status_code == 400, r.get_data(as_text=True)
        assert publications.is_published(self.COORD)


class TestMyImportsInstalledState:
    """My Imports reads installedInProject from the project lockfile — the one
    source of truth (memo dev/47; the Node Content Builder regression)."""

    COORD = "agent.node-content-builder@1.0.0"

    def test_imported_and_installed_shows_installed(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        client.post("/api/agents/imports", json={"coord": self.COORD}, headers=_auth(token))
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": self.COORD}, headers=_auth(token),
        )
        cards = client.get(
            f"/api/agents/imports?projectId={alice_project}", headers=_auth(token)
        ).get_json()["agents"]
        card = next(c for c in cards if c["dirName"] == self.COORD)
        assert card["installedInProject"] is True

    def test_importing_now_installs_into_existing_projects(self, client, user_and_token, tmp_curio, alice_project):
        """Importing reaches every project the user already has.

        This asserted the opposite: an import recorded a coordinate and touched
        no project lockfile. That was reported as a bug, and it was one - the
        Agent Catalog labelled an imported agent "In all projects" while the
        canvas agents palette, which reads the PROJECT lockfile
        (``listProjectAgents`` -> ``dataflow.agents``), showed it in none of
        them. Two surfaces describing two different things under one label.

        The catalog's claim is the one that was kept, so the import now does the
        same eager per-project walk ``packages.services.install_to_defaults``
        does, and ``save_project`` seeds new projects the same way. Nothing
        consults the account list when a project is opened, so only the walk can
        make the label true.
        """
        _, token = user_and_token
        client.post("/api/agents/imports", json={"coord": self.COORD}, headers=_auth(token))
        cards = client.get(
            f"/api/agents/imports?projectId={alice_project}", headers=_auth(token)
        ).get_json()["agents"]
        card = next(c for c in cards if c["dirName"] == self.COORD)
        assert card["installedInProject"] is True

    def test_removing_the_import_takes_it_out_of_projects_again(self, client, user_and_token, tmp_curio, alice_project):
        """The inverse walk, or "Remove from all projects" would leave the agent
        in every project it had been pushed into."""
        _, token = user_and_token
        client.post("/api/agents/imports", json={"coord": self.COORD}, headers=_auth(token))
        client.delete(f"/api/agents/imports/{self.COORD}", headers=_auth(token))
        cards = client.get(
            f"/api/agents/imports?projectId={alice_project}", headers=_auth(token)
        ).get_json()["agents"]
        assert all(c["dirName"] != self.COORD for c in cards) or next(
            c for c in cards if c["dirName"] == self.COORD
        )["installedInProject"] is False

    def test_a_project_created_afterwards_gets_imported_agents(self, client, user_and_token, tmp_curio):
        """The "future" half. Without the seed in `save_project`, an agent the
        user imported would be missing from every project made later."""
        _, token = user_and_token
        client.post("/api/agents/imports", json={"coord": self.COORD}, headers=_auth(token))
        created = client.post(
            "/api/projects",
            json={"name": "Made after the import", "spec": {"dataflow": {"nodes": [], "edges": []}}},
            headers=_auth(token),
        )
        assert created.status_code in (200, 201), created.get_data(as_text=True)
        new_id = created.get_json()["id"]
        cards = client.get(
            f"/api/agents/imports?projectId={new_id}", headers=_auth(token)
        ).get_json()["agents"]
        card = next(c for c in cards if c["dirName"] == self.COORD)
        assert card["installedInProject"] is True

        # And through the endpoint the CANVAS actually reads. The agents palette
        # calls `listProjectAgents` -> GET /api/agents/projects/<id>, which is
        # the project lockfile; the listing above is the account view with a
        # project marker on it. Asserting only the account view would pass while
        # the left bar in a new dataflow stayed empty, which is exactly the
        # symptom that was reported.
        palette = client.get(
            f"/api/agents/projects/{new_id}", headers=_auth(token)
        ).get_json()["agents"]
        assert any(c["dirName"] == self.COORD for c in palette), (
            f"a new project's agent lockfile should carry the account's imports; "
            f"got {[c['dirName'] for c in palette]}"
        )

    def test_without_project_id_behaves_as_before(self, client, user_and_token, tmp_curio, alice_project):
        _, token = user_and_token
        client.post("/api/agents/imports", json={"coord": self.COORD}, headers=_auth(token))
        client.post(
            f"/api/agents/projects/{alice_project}/install",
            json={"coord": self.COORD}, headers=_auth(token),
        )
        cards = client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]
        card = next(c for c in cards if c["dirName"] == self.COORD)
        assert card["installedInProject"] is False  # no project context given


class TestProviderModels:
    """The model list API Settings offers instead of a free-text box.

    Typing a model name from memory is how a wrong one gets saved, and a wrong
    model only shows up much later as a failed agent run. So the panel asks the
    endpoint what it serves - and it has to be able to ask *before* the user
    saves, which is why this is a POST carrying the credentials on screen.

    #241 made the answer hybrid, and both halves come from the API. Anthropic
    and Gemini are now actually *asked* (the route used to report them
    unlistable without trying, which was not true), and when a live listing
    cannot happen the route replays what that endpoint last reported rather than
    answering with an error and an empty box.

    Nothing here is authored: the fallback is a recording, so the tests below
    always establish it by performing a successful fetch first. And nothing is
    ever an allowlist - no assertion here should ever say a model was refused.
    """

    URL = "/api/agents/provider-models"

    @pytest.fixture(autouse=True)
    def _no_real_calls(self, monkeypatch):
        """Make an unstubbed provider call fail loudly instead of dialling out.

        The suite's ``DEFAULT_LLM_BASE_URL`` is unroutable on purpose so a
        forgotten stub cannot reach anything - but that only protects the
        OpenAI-compatible path. The Anthropic and Gemini SDKs ignore
        ``base_url`` and always talk to their own hosts, so listing them needs
        its own net. Each ``_fake_*`` helper below overrides these.
        """
        import anthropic
        import google.generativeai as genai
        import openai

        def _boom(*_a, **_k):
            raise AssertionError("this test reached a real provider SDK")

        monkeypatch.setattr(openai, "OpenAI", _boom)
        monkeypatch.setattr(anthropic, "Anthropic", _boom)
        monkeypatch.setattr(genai, "configure", _boom)
        monkeypatch.setattr(genai, "list_models", _boom)

    @pytest.fixture(autouse=True)
    def _fresh_store(self, tmp_path, monkeypatch):
        """Give each case its own suggestion store.

        The fallback is a recording now, so a leaked one from a previous test
        would let a case pass without ever having fetched anything.
        """
        from utk_curio.backend.app.agents.repositories import model_catalog

        monkeypatch.setattr(model_catalog, "_users_base", lambda: tmp_path)

    @staticmethod
    def _no_deployment_key(monkeypatch):
        """Drop the suite's stand-in operator key (``conftest`` configures one
        for every agents test)."""
        from utk_curio.backend import config

        monkeypatch.setattr(config, "DEFAULT_LLM_API_KEY", "")

    @staticmethod
    def _no_deployment_base_url(monkeypatch):
        """Resolve to plain OpenAI rather than the suite's custom endpoint."""
        from utk_curio.backend import config

        monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", "")

    @staticmethod
    def _no_deployment_model(monkeypatch):
        """Ship the real default: an operator key with no model named.

        ``conftest`` pins ``DEFAULT_LLM_MODEL`` to a stand-in for every test in
        this package. ``CURIO_DEFAULT_LLM_MODEL`` ships empty while an operator
        may well set the key, and the listing must still reach that endpoint.
        """
        from utk_curio.backend import config

        monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "")

    @staticmethod
    def _fake_openai(monkeypatch, *, models=(), raises=None):
        """Stand in for the OpenAI SDK, recording how it was constructed."""
        seen = {}

        class _Listing:
            def __init__(self, ids):
                self.data = [type("M", (), {"id": i})() for i in ids]

        class _Models:
            def __init__(self, ids):
                self._ids = ids

            def list(self):
                if raises is not None:
                    raise raises
                return _Listing(self._ids)

        class _Client:
            def __init__(self, **kwargs):
                seen.update(kwargs)
                self.models = _Models(list(models))

        import openai

        monkeypatch.setattr(openai, "OpenAI", _Client)
        return seen

    @staticmethod
    def _fake_anthropic(monkeypatch, *, models=(), raises=None):
        """Stand in for the Anthropic SDK's ``client.models.list()``."""
        seen = {}

        class _Models:
            def list(self):
                if raises is not None:
                    raise raises
                return [type("M", (), {"id": i})() for i in models]

        class _Client:
            def __init__(self, **kwargs):
                seen.update(kwargs)
                self.models = _Models()

        import anthropic

        monkeypatch.setattr(anthropic, "Anthropic", _Client)
        return seen

    @staticmethod
    def _fake_gemini(monkeypatch, *, models=(), raises=None):
        """Stand in for ``google.generativeai.list_models()``.

        *models* is a list of ``(name, methods)`` pairs because the real listing
        mixes chat models with embedding and tuning-only ones, and filtering
        those out is the part worth testing.
        """
        seen = {}

        def _configure(**kwargs):
            seen.update(kwargs)

        def _list_models():
            if raises is not None:
                raise raises
            return [
                type("M", (), {"name": n, "supported_generation_methods": ms})()
                for n, ms in models
            ]

        import google.generativeai as genai

        monkeypatch.setattr(genai, "configure", _configure)
        monkeypatch.setattr(genai, "list_models", _list_models)
        return seen

    # -- the live path ----------------------------------------------------

    def test_lists_what_the_endpoint_serves(self, client, user_and_token, monkeypatch):
        self._fake_openai(monkeypatch, models=["llama4-nim", "gemma4"])
        _, token = user_and_token
        body = client.post(
            self.URL,
            headers=_auth(token),
            json={
                "apiType": "openai_compatible",
                "baseUrl": "https://llm.example.test/",
                "apiKey": "sk-typed",
            },
        ).get_json()
        # Sorted, so the menu order does not depend on the server's.
        assert body["models"] == ["gemma4", "llama4-nim"]
        assert body["listable"] is True
        assert body["source"] == "live"
        assert body["warning"] is None

    def test_uses_the_credentials_in_the_request(self, client, user_and_token, monkeypatch):
        # The panel calls this mid-edit, before Save. Listing against the saved
        # config instead would answer for the previous endpoint.
        seen = self._fake_openai(monkeypatch, models=["m"])
        _, token = user_and_token
        client.post(
            self.URL,
            headers=_auth(token),
            json={
                "apiType": "openai_compatible",
                "baseUrl": "https://typed.example.test/",
                "apiKey": "sk-typed",
            },
        )
        assert seen["base_url"] == "https://typed.example.test/"
        assert seen["api_key"] == "sk-typed"

    def test_anthropic_is_asked_rather_than_assumed_unlistable(
        self, client, user_and_token, monkeypatch
    ):
        # #241: the route used to answer {"models": [], "listable": false} for
        # Anthropic without calling anything, and the panel rendered that as
        # "This provider does not publish a model list."
        seen = self._fake_anthropic(
            monkeypatch, models=["claude-sonnet-5", "claude-haiku-4-5"],
        )
        _, token = user_and_token
        body = client.post(
            self.URL,
            headers=_auth(token),
            json={"apiType": "anthropic", "apiKey": "sk-ant-typed"},
        ).get_json()
        assert seen["api_key"] == "sk-ant-typed"
        assert body["listable"] is True
        assert "claude-sonnet-5" in body["models"]

    def test_gemini_offers_only_models_that_can_chat(
        self, client, user_and_token, monkeypatch
    ):
        # The real listing mixes in embedding and tuning-only models. Offering
        # one as the chat model fails at the first agent run, not here.
        self._fake_gemini(
            monkeypatch,
            models=[
                ("models/gemini-2.0-flash", ["generateContent", "countTokens"]),
                ("models/text-embedding-004", ["embedContent"]),
            ],
        )
        _, token = user_and_token
        body = client.post(
            self.URL,
            headers=_auth(token),
            json={"apiType": "gemini", "apiKey": "AIza-typed"},
        ).get_json()
        # And the "models/" prefix is stripped: every other place in Curio
        # names the bare id.
        assert body["models"] == ["gemini-2.0-flash"]
        assert body["listable"] is True

    # -- the curated fallback ---------------------------------------------

    def test_a_provider_that_cannot_be_reached_replays_its_last_listing(
        self, client, user_and_token, monkeypatch
    ):
        # An error and an empty box leaves the user with nothing to pick. What
        # the endpoint said last time, plus why we could not ask now, leaves
        # them able to finish.
        _, token = user_and_token
        body_json = {"apiType": "anthropic", "apiKey": "sk-ant-typed"}

        self._fake_anthropic(monkeypatch, models=["claude-sonnet-5"])
        assert client.post(self.URL, headers=_auth(token), json=body_json).status_code == 200

        self._fake_anthropic(monkeypatch, raises=RuntimeError("connection refused"))
        res = client.post(self.URL, headers=_auth(token), json=body_json)
        assert res.status_code == 200
        body = res.get_json()
        assert body["source"] == "remembered"
        assert body["listable"] is False
        assert body["models"] == ["claude-sonnet-5"]
        assert body["rememberedAt"], "the panel has to be able to say when"
        assert "connection refused" in body["warning"]

    def test_a_live_listing_becomes_the_next_fallback(
        self, client, user_and_token, monkeypatch
    ):
        # The recording is refreshed on every success, which is the whole point:
        # the suggestions track the provider without anyone maintaining them.
        _, token = user_and_token
        body_json = {"apiType": "gemini", "apiKey": "AIza-typed"}

        self._fake_gemini(
            monkeypatch, models=[("models/old-model", ["generateContent"])],
        )
        client.post(self.URL, headers=_auth(token), json=body_json)
        self._fake_gemini(
            monkeypatch, models=[("models/new-model", ["generateContent"])],
        )
        client.post(self.URL, headers=_auth(token), json=body_json)

        self._fake_gemini(monkeypatch, raises=RuntimeError("offline"))
        body = client.post(self.URL, headers=_auth(token), json=body_json).get_json()
        assert body["models"] == ["new-model"]

    def test_no_key_replays_the_last_listing_without_a_round_trip(
        self, client, user_and_token, monkeypatch
    ):
        # Every provider authenticates its models endpoint, so sending a
        # placeholder key only buys a socket timeout for a foregone 401. The
        # autouse guard is the assertion that nothing was dialled.
        _, token = user_and_token

        self._fake_anthropic(monkeypatch, models=["claude-sonnet-5"])
        client.post(
            self.URL,
            headers=_auth(token),
            json={"apiType": "anthropic", "apiKey": "sk-ant-typed"},
        )

        self._no_deployment_key(monkeypatch)
        body = client.post(
            self.URL, headers=_auth(token), json={"apiType": "anthropic"},
        ).get_json()
        assert body["source"] == "remembered"
        assert body["models"] == ["claude-sonnet-5"]
        assert "API key" in body["warning"]

    def test_a_recording_is_scoped_to_the_endpoint_that_produced_it(
        self, client, user_and_token, monkeypatch
    ):
        # One provider's models must never be offered for another, and a custom
        # endpoint is its own provider even under the same api_type.
        _, token = user_and_token
        self._fake_anthropic(monkeypatch, models=["claude-sonnet-5"])
        client.post(
            self.URL,
            headers=_auth(token),
            json={"apiType": "anthropic", "apiKey": "sk-ant-typed"},
        )

        self._no_deployment_key(monkeypatch)
        self._no_deployment_base_url(monkeypatch)
        res = client.post(
            self.URL,
            headers=_auth(token),
            json={"apiType": "openai_compatible", "baseUrl": "http://ollama.test/v1"},
        )
        # Nothing was ever recorded for that endpoint, so there is nothing to
        # replay - not Anthropic's list.
        assert res.status_code == 400

    # -- when there is nothing to fall back to ----------------------------

    def test_a_rejected_key_with_nothing_recorded_is_a_400_that_says_why(
        self, client, user_and_token, monkeypatch
    ):
        # Nothing has ever been recorded for this endpoint, so the reason IS
        # the answer. The user is mid-edit and the message is what tells them
        # which field is wrong, so it has to reach them rather than becoming a
        # bare 500.
        self._fake_openai(
            monkeypatch, raises=RuntimeError("401 invalid proxy server token"),
        )
        _, token = user_and_token
        res = client.post(
            self.URL,
            headers=_auth(token),
            json={
                "apiType": "openai_compatible",
                "baseUrl": "https://x.test/",
                "apiKey": "sk-wrong",
            },
        )
        assert res.status_code == 400
        assert "invalid proxy server token" in res.get_json()["error"]

    def test_a_new_account_with_no_key_is_told_to_add_one(
        self, client, user_and_token, monkeypatch
    ):
        # The honest cold start: nothing recorded, no key, so no suggestions -
        # and the Model field stays free text, which costs nothing.
        self._no_deployment_key(monkeypatch)
        _, token = user_and_token
        res = client.post(
            self.URL,
            headers=_auth(token),
            json={"apiType": "openai_compatible", "baseUrl": "https://x.test/"},
        )
        assert res.status_code == 400
        assert "API key" in res.get_json()["error"]

    def test_an_unconfigured_account_can_still_ask(
        self, client, user_and_token, monkeypatch
    ):
        # An account with nothing saved asks with only what is on screen. It
        # omits apiType, which reads as OpenAI-compatible.
        self._fake_openai(monkeypatch, models=["gemma4"])
        _, token = user_and_token
        res = client.post(
            self.URL,
            headers=_auth(token),
            json={"baseUrl": "https://x.test/", "apiKey": "sk-typed"},
        )
        assert res.status_code == 200
        assert res.get_json()["models"] == ["gemma4"]

    def test_a_deployment_key_is_not_lost_when_no_default_model_is_set(
        self, client, user_and_token, monkeypatch
    ):
        """A model is what this screen is for, so it cannot gate asking (#241).

        ``CURIO_DEFAULT_LLM_MODEL`` ships empty, and an operator who deploys a
        key and leaves the model to their users offers This Curio install: the
        listing asks that endpoint with its own key.
        """
        self._no_deployment_model(monkeypatch)
        seen = self._fake_openai(monkeypatch, models=["gemma4"])
        _, token = user_and_token

        res = client.post(
            self.URL,
            headers=_auth(token),
            json={"endpoint": "deployment"},
        )

        assert res.status_code == 200, res.get_json()
        assert res.get_json()["models"] == ["gemma4"]
        # The deployment's credentials were used, not discarded.
        assert seen["api_key"] == "test-key"
        assert seen["base_url"] == "http://127.0.0.1:9/v1"

    def test_a_key_saved_for_one_provider_is_not_lent_to_another(
        self, client, db, user_and_token, monkeypatch
    ):
        """A configuration's key is lent only to that configuration's endpoint.

        Asking about Anthropic while naming an Ollama configuration must not
        list the Ollama endpoint, nor send its key to Anthropic.
        """
        self._no_deployment_key(monkeypatch)
        _, token = user_and_token
        ollama = client.post(
            "/api/agents/llm/configs",
            json={"label": "Ollama", "apiType": "openai_compatible",
                  "baseUrl": "http://ollama.local/v1", "apiKey": "sk-ollama-secret",
                  "model": "llama3"},
            headers=_auth(token),
        ).get_json()["config"]

        res = client.post(
            self.URL,
            headers=_auth(token),
            json={"configId": ollama["id"], "apiType": "anthropic", "baseUrl": "", "apiKey": ""},
        )

        # Refused for want of a key, rather than answered with another
        # provider's. The Anthropic SDK is booby-trapped by _no_real_calls, so
        # a leak would fail loudly here instead of passing quietly.
        assert res.status_code == 400
        assert "API key" in res.get_json()["error"]

    def test_a_typed_endpoint_is_not_handed_another_endpoints_key(
        self, client, user_and_token, monkeypatch
    ):
        """Typing a URL must not post the operator's secret to it: a request
        that names neither a configuration nor this install borrows no key."""
        seen = self._fake_openai(monkeypatch, models=["anything"])
        _, token = user_and_token

        res = client.post(
            self.URL,
            headers=_auth(token),
            json={
                "apiType": "openai_compatible",
                "baseUrl": "http://typed.example.test/v1",
                "apiKey": "",
            },
        )

        assert res.status_code == 400
        assert "API key" in res.get_json()["error"]
        # The strong half: the SDK was never even constructed, so nothing was
        # sent anywhere. An assertion on the status alone would still pass if
        # the key leaked and the endpoint merely refused it.
        assert seen == {}

    def test_a_recording_is_filed_under_the_endpoint_that_answered(
        self, client, user_and_token, monkeypatch
    ):
        """Record and replay have to agree on which endpoint spoke: an
        Anthropic listing is filed under ``anthropic``, never under a URL the
        request did not name."""
        self._fake_anthropic(monkeypatch, models=["claude-haiku-4-5"])
        _, token = user_and_token
        recorded = client.post(
            self.URL,
            headers=_auth(token),
            json={"apiType": "anthropic", "baseUrl": "", "apiKey": "sk-typed"},
        )
        assert recorded.status_code == 200
        assert recorded.get_json()["models"] == ["claude-haiku-4-5"]

        # Proven by moving the deployment's URL: the replay can only find the
        # entry if that URL never entered its identity.
        self._no_deployment_base_url(monkeypatch)
        self._no_deployment_key(monkeypatch)
        replayed = client.post(
            self.URL,
            headers=_auth(token),
            json={"apiType": "anthropic", "baseUrl": "", "apiKey": ""},
        )

        assert replayed.status_code == 200, replayed.get_json()
        body = replayed.get_json()
        assert body["source"] == "remembered"
        assert body["models"] == ["claude-haiku-4-5"]

    def test_requires_auth(self, client):
        assert client.post(self.URL, json={}).status_code == 401


class TestReadDefinition:
    """``GET /api/agents/definitions/<coord>`` reads from wherever the agent is (#275).

    It read the user store only, so "View details -> Export" on the Agent
    Catalog page - which lists the whole roster and the shared catalog - failed
    for any agent this account had not imported, including every built-in, and
    the page could only say "Export failed".
    """

    BUILTIN = "agent.node-researcher@1.0.0"

    def test_a_builtin_is_readable_without_ever_importing_it(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        r = client.get(f"/api/agents/definitions/{self.BUILTIN}", headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body["manifest"]["id"] == "agent.node-researcher"
        assert body["manifest"]["provenance"]["trust"] == "built-in"
        declared = {asset["path"] for asset in body["manifest"]["prompts"].values()}
        assert declared, "a built-in declares its prompt files"
        # Every declared prompt travels with its text, from llm-prompts/.
        assert declared <= set(body["prompts"]), (declared, set(body["prompts"]))
        assert all(body["prompts"][p].strip() for p in declared)

    def test_an_owned_import_is_readable(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user)
        r = client.get(f"/api/agents/definitions/{coord}", headers=_auth(token))
        assert r.status_code == 200
        assert r.get_json()["manifest"]["id"] == "agent.my-explainer"

    def test_a_published_only_definition_is_readable(self, client, user_and_token, tmp_curio):
        user, token = user_and_token
        coord = _write_def(user, agent_id="agent.shared-only")
        src = storage.agent_definition_dir(_user_dir_key(user), coord)
        publications.publish_from_dir(src, coord)
        shutil.rmtree(src)  # this account no longer holds a copy

        r = client.get(f"/api/agents/definitions/{coord}", headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["manifest"]["id"] == "agent.shared-only"

    def test_an_unknown_coordinate_is_still_404(self, client, user_and_token, tmp_curio):
        _, token = user_and_token
        r = client.get("/api/agents/definitions/agent.nope@1.0.0", headers=_auth(token))
        assert r.status_code == 404
        assert "agent.nope@1.0.0" in r.get_json()["error"]

    def test_a_malformed_coordinate_is_404_not_500(self, client, user_and_token, tmp_curio):
        """A name no agent directory can have names no definition. The user-store
        read refused it before the published-catalog read was reached, and that
        read's refusal was caught by names the module never imported, so the
        route answered 500 either way."""
        _, token = user_and_token
        r = client.get("/api/agents/definitions/not-a-coordinate", headers=_auth(token))
        assert r.status_code == 404
        assert "not-a-coordinate" in r.get_json()["error"]

    def test_an_exported_builtin_round_trips_through_upload(self, client, user_and_token, tmp_curio):
        """What Export writes for a built-in, Import accepts - under a new id."""
        _, token = user_and_token
        bundle = client.get(f"/api/agents/definitions/{self.BUILTIN}", headers=_auth(token)).get_json()
        manifest = dict(bundle["manifest"])
        manifest["id"] = "agent.node-researcher-copy"
        manifest["provenance"] = {"publisher": "alice", "trust": "imported"}
        r = client.post(
            "/api/agents/imports/upload",
            json={"manifest": manifest, "prompts": bundle["prompts"]},
            headers=_auth(token),
        )
        assert r.status_code in (200, 201), r.get_json()
