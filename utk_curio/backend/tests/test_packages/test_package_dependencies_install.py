"""Adding a package adds the packages its manifest names in ``dependencies.packages``.

The owner's rule (2026-10-20): each package a manifest names in
``dependencies.packages`` is added with it, at the version its entry allows,
then the packages those name in turn. A cycle adds each package once, a package
already in the account is kept as it is, and a package that needs one neither
the account nor the catalog holds refuses the whole add, naming both, with
nothing added. The dataflow's lockfile records each package, so a node of the
package is handed the modules of the packages it needs (``modules_for_node``).

Every path that adds a package is here: Add to project (a card dropped from a
drawer takes it after the Add review), Add to all projects, opening a dataflow
whose lockfile names the package, and the examples' seeding. The Add review's
probe, and the agents', resolve the packages a package needs from the catalog.

The packages are this module's own, in a catalog of its own, so the rule is
pinned on them and on no package Curio ships. The last test reads the shipped
catalog and names no package in it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.app.packages import service as packages_services
from utk_curio.backend.app.packages.application import provisioning, store_install
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.infrastructure.pip_runner import PipInstallError
from utk_curio.backend.app.packages.repositories import defaults as defaults_io
from utk_curio.backend.app.packages.repositories.store import package_dir, user_packages_dir
from utk_curio.backend.app.projects import services as projects_services
from utk_curio.backend.app.projects import storage as projects_storage


def _manifest(package_id: str, major: int, version: str, needs: dict, python: dict) -> dict:
    return {
        "id": package_id,
        "version": version,
        "name": package_id,
        "publisher": "Test",
        "description": "Test package",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": major},
        "permissions": [],
        "dependencies": {"packages": dict(needs), "python": dict(python), "js": {}},
        "createdAt": "2026-06-01T12:00:00Z",
        "templates": [{
            "id": "caller",
            "label": "Caller",
            "category": "computation",
            "engine": "python",
            "editor": "code",
            "hasCode": True,
            "hasWidgets": False,
            "hasGrammar": False,
            "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": "sources/caller.py",
        }],
    }


def _publish(
    catalog: Path,
    package_id: str,
    *,
    major: int = 1,
    version: str = "1.0.0",
    needs: dict | None = None,
    python: dict | None = None,
    modules: dict | None = None,
) -> str:
    """Write the package ``<package_id>@<major>`` into *catalog*, a node and the
    modules given beside it in ``sources/``. Answers its dirName."""
    dir_name = f"{package_id}@{major}"
    root = catalog / dir_name
    (root / "sources").mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(_manifest(package_id, major, version, needs or {}, python or {})), encoding="utf-8",
    )
    (root / "sources" / "caller.py").write_text("return 1\n", encoding="utf-8")
    for relative, text in (modules or {}).items():
        (root / "sources" / relative).write_text(text, encoding="utf-8")
    return dir_name


def _helpers(name: str) -> dict:
    """A module of one function, named *name*."""
    return {f"{name}.py": f"def helped():\n    return {name!r}\n"}


@pytest.fixture()
def catalog(tmp_path, monkeypatch) -> Path:
    """A shared catalog holding this module's packages and nothing else."""
    root = tmp_path / "catalog"
    root.mkdir()
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    return root


def _new_dataflow(client, auth: dict, name: str) -> str:
    created = client.post(
        "/api/projects",
        json={"name": name, "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []},
        headers=auth,
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    return created.get_json()["id"]


@pytest.fixture()
def account(catalog, client, user_and_token):
    """The test user: the account, its store key, its auth headers and one dataflow with no packages."""
    user, token = user_and_token
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return SimpleNamespace(
        user=user,
        key=projects_services._user_dir_key(user),
        auth=auth,
        project=_new_dataflow(client, auth, "needs-packages"),
    )


def _store(user_key: str) -> set[str]:
    base = user_packages_dir(user_key)
    if not base.is_dir():
        return set()
    return {entry.name for entry in base.iterdir() if entry.is_dir() and PACKAGE_DIR_RE.match(entry.name)}


def _lockfile(user_key: str, project_id: str) -> list[str]:
    return projects_storage.read_spec(user_key, project_id)["dataflow"]["packages"]


def _sources(user_key: str, dir_name: str, *names: str) -> dict:
    return {"root": str(package_dir(user_key, dir_name) / "sources"), "names": list(names)}


def _manifest_version(user_key: str, dir_name: str) -> str:
    return json.loads((package_dir(user_key, dir_name) / "manifest.json").read_text(encoding="utf-8"))["version"]


# ---------------------------------------------------------------------------
# What an add brings
# ---------------------------------------------------------------------------

class TestAddingAPackageAddsThePackagesItNeeds:
    def test_the_package_it_needs_lands_in_the_store_and_the_lockfile_and_its_node_gets_that_packages_modules(
        self, catalog, account,
    ):
        base = _publish(catalog, "ai.test.base", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "*"})

        result = packages_services.install_to_project(account.key, account.project, top)

        assert {base, top} <= _store(account.key), _store(account.key)
        assert _lockfile(account.key, account.project) == [base, top]
        assert result["packages"] == [base, top]
        assert packages_services.modules_for_node(account.key, "ai.test.top/caller", account.project) == (
            _sources(account.key, base, "base_helpers")
        )

    def test_the_packages_those_name_are_added_in_turn(self, catalog, account):
        base = _publish(catalog, "ai.test.base", modules=_helpers("base_helpers"))
        mid = _publish(catalog, "ai.test.mid", needs={base: "*"}, modules=_helpers("mid_helpers"))
        top = _publish(catalog, "ai.test.top", needs={mid: "*"})

        packages_services.install_to_project(account.key, account.project, top)

        assert {base, mid, top} <= _store(account.key), _store(account.key)
        assert _lockfile(account.key, account.project) == [base, mid, top]
        assert packages_services.modules_for_node(account.key, "ai.test.top/caller", account.project) == [
            _sources(account.key, mid, "mid_helpers"),
            _sources(account.key, base, "base_helpers"),
        ]

    def test_a_cycle_adds_each_package_once(self, catalog, account):
        first = _publish(catalog, "ai.test.first", needs={"ai.test.second@1": "*"}, modules=_helpers("first_helpers"))
        second = _publish(catalog, "ai.test.second", needs={"ai.test.first@1": "*"}, modules=_helpers("second_helpers"))

        result = packages_services.install_to_project(account.key, account.project, first)

        assert {first, second} <= _store(account.key), _store(account.key)
        assert result["packages"] == [first, second]
        assert packages_services.modules_for_node(account.key, "ai.test.first/caller", account.project) == [
            _sources(account.key, first, "first_helpers"),
            _sources(account.key, second, "second_helpers"),
        ]

    def test_a_package_already_in_the_account_is_kept_as_it_is(self, catalog, account):
        base = _publish(catalog, "ai.test.base", version="1.0.0", modules=_helpers("base_helpers"))
        store_install.install_package_from_directory(account.key, catalog / base)
        # The catalog moves on; the account's copy is not replaced by an add.
        _publish(catalog, "ai.test.base", version="1.1.0", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "*"})

        packages_services.install_to_project(account.key, account.project, top)

        assert _manifest_version(account.key, base) == "1.0.0"
        assert _lockfile(account.key, account.project) == [base, top]

    @pytest.mark.parametrize(("wanted", "added"), [
        ("^1.2", "ai.test.base@1"),
        ("*", "ai.test.base@2"),
    ])
    def test_an_entry_takes_the_highest_version_its_range_allows(self, catalog, account, wanted, added):
        _publish(catalog, "ai.test.base", major=1, version="1.3.0", modules=_helpers("base_helpers"))
        _publish(catalog, "ai.test.base", major=2, version="2.0.0", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={"ai.test.base": wanted})

        packages_services.install_to_project(account.key, account.project, top)

        assert {dn for dn in _store(account.key) if dn.startswith("ai.test.base@")} == {added}
        assert _lockfile(account.key, account.project) == sorted([added, top])

    def test_with_two_majors_in_the_account_a_bare_entry_takes_the_one_the_dataflow_records(self, catalog, account):
        base_1 = _publish(catalog, "ai.test.base", major=1, version="1.0.0", modules=_helpers("base_helpers"))
        base_2 = _publish(catalog, "ai.test.base", major=2, version="2.0.0", modules=_helpers("base_helpers"))
        for dir_name in (base_1, base_2):
            store_install.install_package_from_directory(account.key, catalog / dir_name)
        top = _publish(catalog, "ai.test.top", needs={"ai.test.base": "^1.0"})

        packages_services.install_to_project(account.key, account.project, top)

        assert _lockfile(account.key, account.project) == [base_1, top]
        # The node's package is found as a node's own is: the dataflow's
        # lockfile names the major when the account has several.
        assert packages_services.modules_for_node(account.key, "ai.test.top/caller", account.project) == (
            _sources(account.key, base_1, "base_helpers")
        )


# ---------------------------------------------------------------------------
# A package that cannot be had refuses the whole add
# ---------------------------------------------------------------------------

class TestAMissingPackageRefusesTheWholeAdd:
    def test_a_package_neither_the_account_nor_the_catalog_has_is_named_with_what_needs_it(self, catalog, account):
        top = _publish(catalog, "ai.test.top", needs={"ai.test.absent@1": "*"})

        with pytest.raises(packages_services.PackageServiceError) as refused:
            packages_services.install_to_project(account.key, account.project, top)

        assert "ai.test.absent@1" in str(refused.value) and top in str(refused.value), str(refused.value)
        assert top not in _store(account.key)
        assert _lockfile(account.key, account.project) == []

    def test_one_missing_further_down_refuses_it_too_and_adds_nothing(self, catalog, account):
        mid = _publish(catalog, "ai.test.mid", needs={"ai.test.absent@1": "*"}, modules=_helpers("mid_helpers"))
        top = _publish(catalog, "ai.test.top", needs={mid: "*"})

        with pytest.raises(packages_services.PackageServiceError) as refused:
            packages_services.install_to_project(account.key, account.project, top)

        assert "ai.test.absent@1" in str(refused.value) and mid in str(refused.value), str(refused.value)
        assert not {mid, top} & _store(account.key)
        assert _lockfile(account.key, account.project) == []

    def test_a_version_no_copy_has_refuses_it(self, catalog, account):
        base = _publish(catalog, "ai.test.base", version="1.0.0", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "^1.5"})

        with pytest.raises(packages_services.PackageServiceError) as refused:
            packages_services.install_to_project(account.key, account.project, top)

        assert base in str(refused.value) and top in str(refused.value), str(refused.value)
        assert not {base, top} & _store(account.key)
        assert _lockfile(account.key, account.project) == []

    def test_a_failure_part_way_takes_back_the_packages_the_add_copied(self, catalog, account, monkeypatch):
        base = _publish(catalog, "ai.test.base", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "*"})
        copied: list[str] = []
        copy = store_install.install_package_from_directory
        monkeypatch.setattr(
            store_install, "install_package_from_directory",
            lambda user_key, source, replace=False: copied.append(source.name) or copy(user_key, source, replace=replace),
        )
        provision = provisioning.provision_python_deps

        def _fails_for_top(user_key, dir_name, manifest):
            if dir_name == top:
                raise PipInstallError("no wheel for the test library")
            return provision(user_key, dir_name, manifest)

        monkeypatch.setattr(provisioning, "provision_python_deps", _fails_for_top)

        with pytest.raises(packages_services.PackageServiceError):
            packages_services.install_to_project(account.key, account.project, top)

        assert copied == [base, top]
        assert not {base, top} & _store(account.key)
        assert _lockfile(account.key, account.project) == []


# ---------------------------------------------------------------------------
# Every path that adds a package
# ---------------------------------------------------------------------------

class TestEveryPathThatAddsAPackage:
    def test_add_to_all_projects_adds_the_package_it_needs_to_the_defaults_and_every_dataflow(
        self, catalog, account, client,
    ):
        second = _new_dataflow(client, account.auth, "needs-packages-too")
        base = _publish(catalog, "ai.test.base", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "*"})

        packages_services.install_to_defaults(account.user, top)

        assert {base, top} <= _store(account.key), _store(account.key)
        assert {base, top} <= defaults_io.load_defaults(account.key)
        for project_id in (account.project, second):
            assert _lockfile(account.key, project_id) == [base, top]

    def test_opening_a_dataflow_whose_lockfile_names_the_package_adds_the_package_it_needs(
        self, catalog, account, client,
    ):
        base = _publish(catalog, "ai.test.base", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "*"})

        installed = client.post(
            "/api/packages/workflow-deps/install", data=json.dumps({"packages": [top]}), headers=account.auth,
        )

        assert installed.status_code == 200, installed.get_data(as_text=True)
        assert installed.get_json()["installedPackages"] == [top]
        assert {base, top} <= _store(account.key), _store(account.key)

    def test_opening_it_with_the_package_and_not_the_one_it_needs_asks_for_the_package_and_brings_the_other(
        self, catalog, account, client,
    ):
        base = _publish(catalog, "ai.test.base", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "*"})
        store_install.install_package_from_directory(account.key, catalog / top)

        check = client.post(
            "/api/packages/workflow-deps/check", data=json.dumps({"packages": [top]}), headers=account.auth,
        )
        assert check.status_code == 200, check.get_data(as_text=True)
        assert check.get_json()["packages"] == [top]

        installed = client.post(
            "/api/packages/workflow-deps/install", data=json.dumps({"packages": [top]}), headers=account.auth,
        )

        assert installed.status_code == 200, installed.get_data(as_text=True)
        assert base in _store(account.key)
        again = client.post(
            "/api/packages/workflow-deps/check", data=json.dumps({"packages": [top]}), headers=account.auth,
        )
        assert again.get_json()["packages"] == []

    def test_the_examples_seeding_brings_the_packages_their_packages_need(
        self, catalog, tmp_curio, tmp_path, monkeypatch,
    ):
        from utk_curio.backend.app.packages.application import seeding
        from utk_curio.backend.app.projects import shipped

        base = _publish(catalog, "ai.test.base", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "*"})
        example = tmp_path / "examples" / "needs-a-package.json"
        example.parent.mkdir()
        example.write_text(
            json.dumps({"dataflow": {"nodes": [], "edges": [], "packages": [top]}}), encoding="utf-8",
        )
        monkeypatch.setattr(
            shipped, "shipped_dataflows",
            lambda root=None: [shipped.ShippedDataflow(key=example.stem, path=example, source=shipped.SOURCE_EXAMPLE)],
        )
        monkeypatch.setattr(seeding, "CURIO_SEED_EXAMPLES", True)

        assert seeding.example_dep_package_ids() == ("ai.test.base", "ai.test.top")
        seeding.seed_dev_packages(user_key="guest")
        assert {base, top} <= _store("guest"), _store("guest")


# ---------------------------------------------------------------------------
# The Add review's probe, and the agents' review
# ---------------------------------------------------------------------------

class TestTheReviewsResolveThePackagesAPackageNeeds:
    def test_the_add_reviews_probe_resolves_a_package_whose_needed_package_is_only_in_the_catalog(
        self, catalog, account, client,
    ):
        base = _publish(
            catalog, "ai.test.base", python={"curio-wheelhouse-base": "1.0.0"}, modules=_helpers("base_helpers"),
        )
        top = _publish(catalog, "ai.test.top", needs={base: "*"})

        probe = client.post("/api/packages/resolve", data=json.dumps({"packages": [top]}), headers=account.auth)

        assert probe.status_code == 200, probe.get_data(as_text=True)
        lockfile = probe.get_json()["lockfile"]
        assert [entry["dirName"] for entry in lockfile["installedPackages"]] == [base, top]
        # The libraries the add would install include the needed package's.
        assert "curio-wheelhouse-base" in lockfile["pythonDeps"]
        assert not {base, top} & _store(account.key)

    def test_the_add_reviews_probe_names_a_missing_package_and_what_needs_it(self, catalog, account, client):
        top = _publish(catalog, "ai.test.top", needs={"ai.test.absent@1": "*"})

        probe = client.post("/api/packages/resolve", data=json.dumps({"packages": [top]}), headers=account.auth)

        # Not 409: the review reads a 409 as its conflict report, and would
        # open with Add enabled.
        assert probe.status_code == 400, probe.get_data(as_text=True)
        error = probe.get_json()["error"]
        assert "ai.test.absent@1" in error and top in error, error

    def test_the_agents_review_resolves_it_too(self, catalog, account):
        base = _publish(catalog, "ai.test.base", modules=_helpers("base_helpers"))
        top = _publish(catalog, "ai.test.top", needs={base: "*"})

        report = packages_services.agent_resolve_report(account.key, [top])

        assert [package["dirName"] for package in report["packages"]] == [top]
        assert report["conflicts"] == []


def test_every_shipped_package_names_only_packages_the_shipped_catalog_holds():
    """An add of any shipped package, and the examples' seeding, finds every
    package it needs in the shipped catalog, at a version its entry allows."""
    from utk_curio.backend.app.packages.application.package_dependencies import PackageFolder
    from utk_curio.backend.app.packages.domain.package_closure import required_packages

    shipped = PackageFolder(Path(__file__).resolve().parents[4] / "packages").snapshot()
    assert len(shipped) > 5, sorted(shipped)
    for dir_name in shipped:
        assert set(required_packages([dir_name], {}, shipped)) <= set(shipped), dir_name
