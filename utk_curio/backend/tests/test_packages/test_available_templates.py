"""Tests for ``services.available_templates`` (memo dev/48).

The single source of template knowledge for agent node creation: seeded
``curio.builtin@<highest-major>`` plus the project's package lockfile —
nothing else, and unreadable packages are skipped.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.packages import services as packages_services
from utk_curio.backend.app.packages.storage import user_packageages_dir
from utk_curio.backend.app.projects import services as projects_services


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {
        "name": "tmpl-proj",
        "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
        "outputs": [],
    }
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201
    return resp.get_json()["id"]


def _template(template_id, label, *, editor="code", has_code=None, has_grammar=None, description="", input_ports=None):
    t = {
        "id": template_id,
        "label": label,
        "category": "computation",
        "engine": "python",
        "editor": editor,
        "description": description,
        "inputPorts": input_ports if input_ports is not None else [],
        "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
    }
    if has_code is not None:
        t["hasCode"] = has_code
    if has_grammar is not None:
        t["hasGrammar"] = has_grammar
    return t


def _write_package(user_key, package_id, major, templates, *, broken=False):
    d = user_packageages_dir(user_key) / f"{package_id}@{major}"
    d.mkdir(parents=True, exist_ok=True)
    if broken:
        (d / "manifest.json").write_text("{not json", encoding="utf-8")
        return
    manifest = {
        "id": package_id,
        "version": f"{major}.0.0",
        "name": package_id,
        "publisher": "Test",
        "description": "test",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": major},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": templates,
        "createdAt": "2026-06-01T12:00:00Z",
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _lockfile_add(user_key, project_id, dir_name):
    from utk_curio.backend.app.packages.spec_packages import set_project_packages
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = projects_storage.read_spec(user_key, project_id)
    current = set(spec.get("dataflow", {}).get("packages") or [])
    entries = current | {dir_name}
    set_project_packages(spec, entries)
    projects_storage.write_spec(user_key, project_id, spec)


class TestAvailableTemplates:
    def test_builtin_plus_lockfile_only(self, user_and_token, alice_project, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("computation-analysis", "Computation")])
        _write_package(key, "ai.test.locked", 1, [_template("locked-kind", "Locked")])
        _write_package(key, "ai.test.storeonly", 1, [_template("store-kind", "StoreOnly")])
        _lockfile_add(key, alice_project, "ai.test.locked@1")

        ids = {t["id"] for t in packages_services.available_templates(key, alice_project)}
        # Builtin is always in scope; a store-installed package NOT in the
        # project lockfile is not (dev/48 permitted scope).
        assert ids == {"curio.builtin/computation-analysis", "ai.test.locked/locked-kind"}

    def test_authorable_flag_from_manifest(self, user_and_token, alice_project, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [
            _template("code-kind", "Code", editor="code"),
            _template("grammar-kind", "Grammar", editor="grammar"),
            _template("widget-kind", "Widgets", editor="widgets", has_code=False),
        ])
        by_id = {t["id"]: t for t in packages_services.available_templates(key, alice_project)}
        assert by_id["curio.builtin/code-kind"]["authorable"] is True
        assert by_id["curio.builtin/grammar-kind"]["authorable"] is True
        assert by_id["curio.builtin/widget-kind"]["authorable"] is False

    def test_unreadable_package_is_skipped(self, user_and_token, alice_project, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("ok-kind", "OK")])
        _write_package(key, "ai.test.broken", 1, [], broken=True)
        _lockfile_add(key, alice_project, "ai.test.broken@1")
        ids = {t["id"] for t in packages_services.available_templates(key, alice_project)}
        assert ids == {"curio.builtin/ok-kind"}

    def test_highest_builtin_major_wins(self, user_and_token, alice_project, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("shared-kind", "Old")])
        _write_package(key, "curio.builtin", 2, [_template("shared-kind", "New")])
        by_id = {t["id"]: t for t in packages_services.available_templates(key, alice_project)}
        assert by_id["curio.builtin/shared-kind"]["label"] == "New"

    def test_missing_project_degrades_to_builtin_only(self, user_and_token, tmp_curio):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("only-kind", "Only")])
        ids = {t["id"] for t in packages_services.available_templates(key, "no-such-project")}
        assert ids == {"curio.builtin/only-kind"}


class TestParseCardinality:
    """dev/67-3 (DEC-051) — one parser for the schema's cardinality grammar."""

    def test_all_schema_forms(self):
        from utk_curio.backend.app.packages.manifest import parse_cardinality

        assert parse_cardinality("1") == (1, 1)
        assert parse_cardinality("2") == (2, 2)
        assert parse_cardinality("n") == (0, None)
        assert parse_cardinality("[1,n]") == (1, None)
        assert parse_cardinality("[0,2]") == (0, 2)
        assert parse_cardinality("[1,2]") == (1, 2)
        # Unparseable fails OPEN — the schema owns the grammar.
        assert parse_cardinality("") == (0, None)
        assert parse_cardinality("banana") == (0, None)


class TestInputArity:
    """dev/67-3 (DEC-051) — maxIncomingEdges is the RENDERED truth: one edge
    per rendered handle (handles = ports); merge-flow's slots are the sole
    multi-edge surface."""

    def _templates(self, user_and_token, alice_project, tmp_curio):
        from utk_curio.backend.app.projects import services as projects_services

        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [
            _template("data-loading", "Load", input_ports=[]),
            _template("computation-analysis", "Compute",
                      input_ports=[{"types": ["DATAFRAME"], "cardinality": "[1,n]"}]),
            _template("spatial-join", "Spatial Join",
                      input_ports=[{"types": ["GEODATAFRAME"], "cardinality": "1"},
                                   {"types": ["GEODATAFRAME"], "cardinality": "1"}]),
            _template("merge-flow", "Merge",
                      input_ports=[{"types": ["DATAFRAME"], "cardinality": "[1,n]"}]),
        ])
        return {
            t["id"]: t
            for t in packages_services.available_templates(key, alice_project)
        }

    def test_rendered_capacity_rules(self, user_and_token, alice_project, tmp_curio):
        by_id = self._templates(user_and_token, alice_project, tmp_curio)
        assert by_id["curio.builtin/data-loading"]["maxIncomingEdges"] == 0
        # Declared [1,n] is NOT enforceable capacity — the input plumbing is
        # scalar per handle (a second edge silently overwrites data.input).
        assert by_id["curio.builtin/computation-analysis"]["maxIncomingEdges"] == 1
        assert by_id["curio.builtin/spatial-join"]["maxIncomingEdges"] == 2
        # Merge's rendered slot machinery wins over its declared [1,n].
        assert by_id["curio.builtin/merge-flow"]["maxIncomingEdges"] == 5

    def test_declared_cardinality_survives_as_metadata(self, user_and_token, alice_project, tmp_curio):
        by_id = self._templates(user_and_token, alice_project, tmp_curio)
        assert by_id["curio.builtin/computation-analysis"]["inputs"] == [
            {"types": ["DATAFRAME"], "min": 1, "max": None},
        ]
        assert by_id["curio.builtin/spatial-join"]["inputs"] == [
            {"types": ["GEODATAFRAME"], "min": 1, "max": 1},
            {"types": ["GEODATAFRAME"], "min": 1, "max": 1},
        ]


class TestInstalledTemplatesNotInProject:
    """The reuse-first counterpart (memo dev/93 D4).

    Availability is *store ∩ lockfile*, so a package the user already owns is
    invisible to a project that has not enlisted it — and an agent told to
    reuse then reports that no such template exists and authors a duplicate.
    This listing is what lets the roster say "you have this, enlist it".
    """

    def test_lists_store_only_templates_with_their_dir_name(
        self, user_and_token, alice_project, tmp_curio
    ):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("computation-analysis", "Computation")])
        _write_package(key, "ai.test.locked", 1, [_template("locked-kind", "Locked")])
        _write_package(key, "ai.test.storeonly", 1, [_template("store-kind", "StoreOnly")])
        _lockfile_add(key, alice_project, "ai.test.locked@1")

        rows = packages_services.installed_templates_not_in_project(key, alice_project)
        # Exactly the complement of available_templates: not the builtin
        # (always present) and not what the lockfile already names.
        assert [(r["id"], r["dirName"]) for r in rows] == [
            ("ai.test.storeonly/store-kind", "ai.test.storeonly@1"),
        ]

    def test_empty_when_everything_is_enlisted(
        self, user_and_token, alice_project, tmp_curio
    ):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("computation-analysis", "Computation")])
        _write_package(key, "ai.test.locked", 1, [_template("locked-kind", "Locked")])
        _lockfile_add(key, alice_project, "ai.test.locked@1")

        assert packages_services.installed_templates_not_in_project(key, alice_project) == []

    def test_unreadable_store_package_is_skipped(
        self, user_and_token, alice_project, tmp_curio
    ):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "ai.test.broken", 1, [], broken=True)
        _write_package(key, "ai.test.storeonly", 1, [_template("store-kind", "StoreOnly")])

        ids = {r["id"] for r in packages_services.installed_templates_not_in_project(key, alice_project)}
        assert ids == {"ai.test.storeonly/store-kind"}

    def test_carries_the_same_row_shape_as_available(
        self, user_and_token, alice_project, tmp_curio
    ):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "ai.test.storeonly", 1, [
            _template("note-surface", "Note", editor="none", has_code=False,
                      description="a note surface"),
        ])
        row = packages_services.installed_templates_not_in_project(key, alice_project)[0]
        assert row["label"] == "Note"
        assert row["description"] == "a note surface"
        assert set(row) == {
            "id", "label", "description", "authorable", "inputs",
            "maxIncomingEdges", "dirName",
        }


class TestCatalogOverviewIncludesStorePackages:
    """dev/93 D4: an agent-authored package never enters the committed
    catalog, so before this it could not be enlisted into a second project at
    all — ``package.install`` refused it as "not in the Nodes Catalog", which
    left authoring a near-duplicate as the only move."""

    def test_store_only_package_is_proposable(
        self, user_and_token, alice_project, tmp_curio
    ):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.notes", 1, [
            _template("note-surface", "Note", editor="none", has_code=False),
        ])
        rows = {
            r["dirName"]: r
            for r in packages_services.agent_catalog_overview(key, alice_project)
        }
        assert "curio.notes@1" in rows, "a store package must be enlistable"
        assert rows["curio.notes@1"]["installed"] is False
        assert rows["curio.notes@1"]["builtin"] is False

    def test_enlisted_store_package_reads_as_installed(
        self, user_and_token, alice_project, tmp_curio
    ):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.notes", 1, [
            _template("note-surface", "Note", editor="none", has_code=False),
        ])
        _lockfile_add(key, alice_project, "curio.notes@1")
        rows = {
            r["dirName"]: r
            for r in packages_services.agent_catalog_overview(key, alice_project)
        }
        # ``installed`` keeps meaning the CURRENT project's lockfile (dev/84).
        assert rows["curio.notes@1"]["installed"] is True


class TestCanonicalTemplateId:
    """dev/93 D3 — one value, three legal spellings, one canonical form.

    The dev/90 A14 family: the canonical id is UNVERSIONED, but the client
    registry keys descriptors VERSIONED (so the run context, the canvas graph,
    and the runtime's own proposal previews all speak that form) and legacy
    trill files carry the pre-package enum names. A model quoting an id from
    its own context must not be refused for the spelling the system gave it.
    """

    def test_unversioned_is_returned_unchanged(self):
        assert packages_services.canonical_template_id(
            "curio.builtin/data-loading"
        ) == "curio.builtin/data-loading"

    def test_versioned_loses_only_the_major(self):
        assert packages_services.canonical_template_id(
            "curio.builtin/data-loading@1"
        ) == "curio.builtin/data-loading"
        assert packages_services.canonical_template_id(
            "curio.postits/post-it-note@1"
        ) == "curio.postits/post-it-note"
        # A major that is not installed still canonicalises; availability is
        # resolve_template's job, and the registry is unversioned anyway.
        assert packages_services.canonical_template_id(
            "curio.builtin/data-loading@99"
        ) == "curio.builtin/data-loading"

    def test_legacy_enum_names_resolve_to_builtin_ids(self):
        assert packages_services.canonical_template_id(
            "DATA_LOADING"
        ) == "curio.builtin/data-loading"
        assert packages_services.canonical_template_id(
            "JS_COMPUTATION"
        ) == "curio.builtin/js-computation"
        # Derived, not tabulated: a built-in template that never got an enum
        # member is covered too.
        assert packages_services.canonical_template_id(
            "SPATIAL_JOIN"
        ) == "curio.builtin/spatial-join"

    def test_ambiguous_and_odd_spellings_are_left_alone(self):
        # A bare slug names no package: deliberately still ambiguous, so it
        # refuses rather than silently resolving to some package's template.
        assert packages_services.canonical_template_id("data-loading") == "data-loading"
        # Ids are case-sensitive by contract — no case folding (memo §6.14).
        assert packages_services.canonical_template_id(
            "Curio.Builtin/Data-Loading"
        ) == "Curio.Builtin/Data-Loading"
        assert packages_services.canonical_template_id("  DATA_LOADING  ") == (
            "curio.builtin/data-loading"
        )
        assert packages_services.canonical_template_id("") == ""
        assert packages_services.canonical_template_id(None) == ""
        assert packages_services.canonical_template_id(17) == ""

    def test_every_frontend_nodetype_member_round_trips(self):
        """Drift guard, read from the frontend source itself.

        The legacy aliases are derived from the enum KEY (upper-snake of the
        template id), so this asserts the frontend cannot add a member whose
        key breaks that rule without failing here — which is stronger than
        checking a hand-maintained table for staleness, since the table is
        what would have gone stale.
        """
        import re
        from pathlib import Path

        # tests/test_packages/<this>  ->  utk_curio/
        constants = (
            Path(__file__).resolve().parents[3]
            / "frontend" / "urban-workflows" / "src" / "constants.ts"
        )
        assert constants.is_file(), f"missing {constants}"
        text = constants.read_text(encoding="utf-8")
        block = text.split("export enum NodeType {", 1)[1].split("}", 1)[0]
        members = re.findall(r'^\s*([A-Z0-9_]+)\s*=\s*"([^"]+)"', block, re.M)
        assert len(members) >= 11, f"expected the NodeType roster, parsed {members}"
        for key, value in members:
            assert packages_services.canonical_template_id(key) == value, (
                f"NodeType.{key} = {value!r} does not follow the upper-snake rule "
                "the backend derives legacy aliases from"
            )
            # And the value itself is already canonical.
            assert packages_services.canonical_template_id(value) == value


class TestResolveTemplate:
    """The single availability gate shared by plans and node.create."""

    def _project(self, user_and_token, alice_project):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [
            _template("data-loading", "Data Loading"),
            _template("data-pool", "Data Pool", editor="none", has_code=False),
        ])
        return key, alice_project

    def test_accepts_every_spelling_of_an_available_template(
        self, user_and_token, alice_project, tmp_curio
    ):
        key, pid = self._project(user_and_token, alice_project)
        for spelling in (
            "curio.builtin/data-loading",
            "curio.builtin/data-loading@1",
            "DATA_LOADING",
        ):
            entry, err = packages_services.resolve_template(key, pid, spelling)
            assert err == "", f"{spelling} refused: {err}"
            # The CANONICAL id comes back, never what the caller typed.
            assert entry["id"] == "curio.builtin/data-loading"

    def test_require_authorable_is_the_only_difference_between_callers(
        self, user_and_token, alice_project, tmp_curio
    ):
        key, pid = self._project(user_and_token, alice_project)
        # A plan places a typed placeholder; content arrives later from Solve.
        entry, err = packages_services.resolve_template(
            key, pid, "curio.builtin/data-pool"
        )
        assert entry is not None and err == ""
        # node.create writes content, so it needs a template that holds it.
        entry, err = packages_services.resolve_template(
            key, pid, "curio.builtin/data-pool", require_authorable=True
        )
        assert entry is None
        assert "does not hold authored content" in err

    def test_unknown_and_ambiguous_ids_point_at_the_roster(
        self, user_and_token, alice_project, tmp_curio
    ):
        key, pid = self._project(user_and_token, alice_project)
        for spelling in ("curio.builtin/nope", "data-loading", "NOPE_KIND"):
            entry, err = packages_services.resolve_template(key, pid, spelling)
            assert entry is None
            assert "not an available template for this project" in err
            # The message must name the accepted spellings so a weak model can
            # self-correct from the refusal alone.
            assert "Available node templates" in err
            assert "@<major>" in err

    def test_empty_node_type_is_refused_with_its_own_message(
        self, user_and_token, alice_project, tmp_curio
    ):
        key, pid = self._project(user_and_token, alice_project)
        for bad in (None, "", "   ", 42):
            entry, err = packages_services.resolve_template(key, pid, bad)
            assert entry is None
            assert "non-empty template id string" in err

    def test_degraded_store_is_reported_as_such_not_blamed_on_the_id(
        self, user_and_token, alice_project, tmp_curio, caplog
    ):
        """dev/93 D2: a truncated package store used to surface as "that
        template is not available", which sent a model into correction rounds
        over an id that was never the problem."""
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [], broken=True)

        with caplog.at_level("WARNING"):
            report = packages_services.available_templates_report(key, alice_project)
        assert report["templates"] == []
        assert report["skipped"] == ["curio.builtin@1"]
        assert "curio.builtin@1" in caplog.text, "a silent skip is the bug"

        entry, err = packages_services.resolve_template(
            key, alice_project, "curio.builtin/data-loading@1"
        )
        assert entry is None
        assert "package store is degraded" in err
        assert "curio.builtin@1" in err
        assert "Report this" in err

    def test_registry_failure_is_data_not_an_exception(
        self, user_and_token, alice_project, tmp_curio, monkeypatch
    ):
        key, pid = self._project(user_and_token, alice_project)
        monkeypatch.setattr(
            packages_services, "available_templates_report",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk on fire")),
        )
        entry, err = packages_services.resolve_template(key, pid, "curio.builtin/data-loading")
        assert entry is None
        assert "registry is unavailable" in err and "disk on fire" in err


class TestTemplateLandscape:
    """dev/99 R2 — the composite that will hold the seed lock exactly once.

    Its job today is to be behaviour-identical to the three readers it
    replaces while walking the store once; its job after dev/99 proper is to
    make an agent payload describe ONE instant, so evidence cannot straddle a
    seeding pass and show a package in one half but not the other.
    """

    def _fixture(self, user_and_token, alice_project):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("data-loading", "Load")])
        _write_package(key, "ai.test.locked", 1, [_template("locked-kind", "Locked")])
        _write_package(key, "ai.test.storeonly", 1, [_template("store-kind", "StoreOnly")])
        _lockfile_add(key, alice_project, "ai.test.locked@1")
        return key, alice_project

    def test_equivalent_to_the_three_readers_it_replaces(
        self, user_and_token, alice_project, tmp_curio
    ):
        """The behaviour-preservation proof: identical data, one walk."""
        key, pid = self._fixture(user_and_token, alice_project)
        landscape = packages_services.template_landscape(key, pid)

        assert landscape["available"] == packages_services.available_templates(key, pid)
        assert landscape["notEnlisted"] == (
            packages_services.installed_templates_not_in_project(key, pid)
        )
        assert landscape["catalog"] == packages_services.agent_catalog_overview(key, pid)
        assert landscape["skipped"] == (
            packages_services.available_templates_report(key, pid)["skipped"]
        )

    def test_walks_the_store_once(self, user_and_token, alice_project, tmp_curio, monkeypatch):
        """The efficiency claim, pinned: three public readers cost three
        traversals plus three lockfile reads; the composite costs one of each.
        This also guards the rule that composites call the unlocked CORES —
        a composite that called the public readers would walk three times and,
        once locking lands, deadlock on the non-reentrant lock."""
        key, pid = self._fixture(user_and_token, alice_project)

        walks = {"n": 0}
        real = packages_services._store_index

        def counting(user_key):
            walks["n"] += 1
            return real(user_key)

        monkeypatch.setattr(packages_services, "_store_index", counting)

        packages_services.template_landscape(key, pid)
        assert walks["n"] == 1

        walks["n"] = 0
        packages_services.available_templates(key, pid)
        packages_services.installed_templates_not_in_project(key, pid)
        packages_services.agent_catalog_overview(key, pid)
        assert walks["n"] == 3, "the individual readers each still walk once"

    def test_degradation_signal_survives_the_composite(
        self, user_and_token, alice_project, tmp_curio, caplog
    ):
        """An unreadable in-scope package must still be reported and logged —
        the dev/93 D2 signal must not be lost on the way through."""
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [], broken=True)
        with caplog.at_level("WARNING"):
            landscape = packages_services.template_landscape(key, alice_project)
        assert landscape["skipped"] == ["curio.builtin@1"]
        assert landscape["available"] == []
        assert "curio.builtin@1" in caplog.text

    def test_out_of_scope_unreadable_package_is_not_reported_as_skipped(
        self, user_and_token, alice_project, tmp_curio
    ):
        """Scope filter before readability check, exactly as before the split:
        `skipped` keeps meaning "in scope for this project and unreadable"."""
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [_template("data-loading", "Load")])
        _write_package(key, "ai.test.broken", 1, [], broken=True)  # not enlisted
        landscape = packages_services.template_landscape(key, alice_project)
        assert landscape["skipped"] == []
        assert {t["id"] for t in landscape["available"]} == {"curio.builtin/data-loading"}


class TestBatchResolution:
    """dev/99 R1.2 — a plan mint resolves every node it proposes, so resolving
    one at a time re-walked the store (and, once readers hold the seed lock,
    re-acquired it) once per node."""

    def _project(self, user_and_token, alice_project):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "curio.builtin", 1, [
            _template("data-loading", "Load"),
            _template("data-pool", "Pool", editor="none", has_code=False),
        ])
        return key, alice_project

    def test_cost_does_not_scale_with_the_number_of_types(
        self, user_and_token, alice_project, tmp_curio, monkeypatch
    ):
        key, pid = self._project(user_and_token, alice_project)
        walks = {"n": 0}
        real = packages_services._store_index
        monkeypatch.setattr(
            packages_services, "_store_index",
            lambda uk: (walks.__setitem__("n", walks["n"] + 1), real(uk))[1],
        )

        node_types = ["curio.builtin/data-loading"] * 12
        outcomes = packages_services.resolve_templates(key, pid, node_types)
        assert len(outcomes) == 12
        assert all(entry is not None for entry, _ in outcomes)
        assert walks["n"] == 1, "twelve node types must cost ONE store walk"

    def test_results_are_positional_and_match_single_resolution(
        self, user_and_token, alice_project, tmp_curio
    ):
        """Equivalence with the single gate, including the per-item errors —
        one bad id must not poison its neighbours."""
        key, pid = self._project(user_and_token, alice_project)
        types = [
            "curio.builtin/data-loading",
            "curio.builtin/nope",
            "curio.builtin/data-loading@1",
            "",
        ]
        batch = packages_services.resolve_templates(key, pid, types)
        for node_type, (entry, err) in zip(types, batch):
            single_entry, single_err = packages_services.resolve_template(key, pid, node_type)
            assert (entry, err) == (single_entry, single_err), node_type
        assert batch[0][0]["id"] == "curio.builtin/data-loading"
        assert batch[1][0] is None and "not an available template" in batch[1][1]
        assert batch[2][0]["id"] == "curio.builtin/data-loading"
        assert batch[3][0] is None and "non-empty template id" in batch[3][1]

    def test_require_authorable_applies_per_batch(
        self, user_and_token, alice_project, tmp_curio
    ):
        key, pid = self._project(user_and_token, alice_project)
        types = ["curio.builtin/data-loading", "curio.builtin/data-pool"]
        plan_side = packages_services.resolve_templates(key, pid, types)
        assert all(entry is not None for entry, _ in plan_side)
        create_side = packages_services.resolve_templates(
            key, pid, types, require_authorable=True,
        )
        assert create_side[0][0] is not None
        assert create_side[1][0] is None
        assert "does not hold authored content" in create_side[1][1]

    def test_a_broken_registry_reports_per_item_without_raising(
        self, user_and_token, alice_project, tmp_curio, monkeypatch
    ):
        key, pid = self._project(user_and_token, alice_project)
        monkeypatch.setattr(
            packages_services, "available_templates_report",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk on fire")),
        )
        outcomes = packages_services.resolve_templates(key, pid, ["a", "b", "c"])
        assert len(outcomes) == 3
        assert all(e is None and "registry is unavailable" in msg for e, msg in outcomes)
