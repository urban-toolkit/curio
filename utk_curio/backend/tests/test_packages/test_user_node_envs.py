"""#332: under isolation, a library one user installs is theirs alone.

``pip_runner.install_python_deps`` runs ``sys.executable -m pip install``, and
the backend and the sandbox are launched from one interpreter - which is what
makes an install work at all, and what makes it global. #309 gated the
libraries route on that basis; this scopes the install instead, so the
question stops being instance-wide.

Only reachable under fork isolation (``CURIO_ISOLATION=fork``, which ``--deploy``
turns on): a forked child can be handed its own
``sys.path``, the warm in-process worker cannot. Every test here therefore says
which world it is in, because "unchanged without isolation" is half the
contract.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app.packages.infrastructure import backend_runtime as rt
from utk_curio.backend.app.packages.application import libraries
from utk_curio.backend.app.packages.application import provisioning


class _Manifest:
    """The two attributes ``provision_python_deps`` reads."""

    def __init__(self, deps, backend=None, templates=()):
        self.python_deps = dict(deps)
        self.backend = backend
        self.templates = list(templates)


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv("CURIO_ISOLATION", "fork")


@pytest.fixture
def in_process(monkeypatch):
    monkeypatch.setenv("CURIO_ISOLATION", "off")


@pytest.fixture
def pip_calls(monkeypatch):
    """Record where pip was asked to install, without running it.

    ``conftest``'s autouse stub covers the host installer only - the --target
    ones are deliberately left real there so the overlay end-to-end test can
    use them - so this fixture stubs the target installer for the tests that
    would otherwise reach the network.
    """
    from utk_curio.backend.app.packages.infrastructure import pip_runner
    from utk_curio.backend.app.packages.infrastructure.pip_runner import InstallReport

    calls: list[tuple[str, dict, str | None]] = []

    def _to_target(deps, target_dir, **kw):
        calls.append(("target", dict(deps), str(target_dir)))
        # Materialise something so the tree exists, as a real pip run would.
        import pathlib
        for name in deps:
            pathlib.Path(target_dir, f"{name}.py").write_text("", encoding="utf-8")
        return InstallReport(installed=sorted(deps), skipped=[])

    def _to_host(deps):
        calls.append(("host", dict(deps), None))
        return InstallReport(installed=sorted(deps), skipped=[])

    monkeypatch.setattr(pip_runner, "install_python_deps_to_target", _to_target)
    monkeypatch.setattr(pip_runner, "install_python_deps", _to_host)
    return calls


@pytest.fixture
def probe_says_missing(monkeypatch):
    """Every dep reads as absent, so the installer is always asked to work."""
    from utk_curio.backend.app.packages.infrastructure import pip_runner

    monkeypatch.setattr(
        pip_runner, "import_failures_in",
        lambda deps, path, interpreter=None: {d: "not installed" for d in deps},
    )


@pytest.fixture
def launch_tree(monkeypatch, tmp_path):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")
    return tmp_path


class TestWhereTheDepsLand:

    def test_without_isolation_they_go_to_the_shared_interpreter(
        self, in_process, pip_calls, launch_tree,
    ):
        """The existing behaviour, unchanged - this is the local single-user
        case the feature was built for, and every Windows launch."""
        provisioning.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))

        assert [c[0] for c in pip_calls] == ["host"]

    def test_with_isolation_they_go_to_the_callers_own_tree(
        self, isolated, pip_calls, probe_says_missing, launch_tree,
    ):
        provisioning.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))

        assert [c[0] for c in pip_calls] == ["target"]
        assert str(rt.user_node_overlay_dir("7")) == pip_calls[0][2]

    def test_two_users_get_two_trees(
        self, isolated, pip_calls, probe_says_missing, launch_tree,
    ):
        """The property the whole change exists for: what user 7 installed is
        not importable by user 8's nodes, and the reverse."""
        provisioning.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))
        provisioning.provision_python_deps("8", "ai.test.demo@1", _Manifest({"titlecase": ""}))

        seven, eight = rt.user_node_overlay_dir("7"), rt.user_node_overlay_dir("8")
        assert seven != eight
        assert (seven / "humanize.py").exists()
        assert not (seven / "titlecase.py").exists()
        assert (eight / "titlecase.py").exists()
        assert not (eight / "humanize.py").exists()

    def test_a_handler_only_package_is_untouched_by_isolation(
        self, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        """Handler deps are per-package state either way. Isolation moves where
        NODE code's environment is, and a backend-only package has none."""
        monkeypatch.setattr(
            rt, "build_overlay", lambda *a, **kw: {"libs": [], "bytes": 0},
        )
        monkeypatch.setattr(
            provisioning, "_overlay_import_failures", lambda *a, **kw: {},
        )
        manifest = _Manifest({"humanize": ""}, backend={"entry": "h.py"})

        provisioning.provision_python_deps("7", "ai.test.demo@1", manifest)

        assert pip_calls == []


class TestIncremental:

    def test_adding_a_library_does_not_reinstall_the_others(
        self, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        """The user tree is the sum of everything they have installed, not
        derived state. Wiping it to add one library would re-run pip over their
        whole environment - and leave them with nothing if that run failed."""
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        monkeypatch.setattr(
            pip_runner, "import_failures_in",
            lambda deps, path, interpreter=None: (
                {d: "not installed" for d in deps if d == "titlecase"}
            ),
        )
        provisioning.provision_python_deps(
            "7", "ai.test.demo@1", _Manifest({"humanize": "", "titlecase": ""}),
        )

        assert [c[0] for c in pip_calls] == ["target"]
        assert sorted(pip_calls[0][1]) == ["titlecase"], "humanize was already there"

    def test_nothing_missing_means_no_pip_at_all(
        self, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        monkeypatch.setattr(
            pip_runner, "import_failures_in",
            lambda deps, path, interpreter=None: {},
        )
        provisioning.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))

        assert pip_calls == []


class TestTheImagesLibrariesWinInAnAccountsTree:
    """The account's tree is in front of the image's libraries, which win
    wherever they meet a package's range: an add puts into the tree only what
    neither holds at a version the package, and what it needs, accept. Real
    pip, offline (``_support/front_of_the_image.py``)."""

    def test_an_add_puts_no_torch_in_the_tree_for_a_library_needing_one_the_images_meets(
        self, isolated, launch_tree, tmp_path, monkeypatch,
    ):
        """``pip --target`` ignores what the image holds, so a library the
        image lacks brought every library it needs into the account's tree:
        one that needs ``torch>=2.6`` gave the account a torch of its own,
        in front of the image's CUDA torch."""
        from utk_curio.backend.tests._support.front_of_the_image import (
            NEEDS_TORCH, held, offline_pip, the_images_torch,
        )

        image_torch = the_images_torch()
        offline_pip(monkeypatch, tmp_path / "wheelhouse")

        provisioning.provision_python_deps(
            "7", "ai.test.needs-torch@1", _Manifest({NEEDS_TORCH.dist: f"=={NEEDS_TORCH.version}"}),
        )

        tree = held(rt.user_node_overlay_dir("7"))
        assert "torch" not in tree, (
            f"the add put torch {tree.get('torch')} into account 7's tree, in front of the image's {image_torch}")
        assert tree == {NEEDS_TORCH.dist: NEEDS_TORCH.version}, tree

    def test_an_add_puts_the_packages_torch_in_the_tree_where_the_images_is_outside_its_range(
        self, isolated, launch_tree, tmp_path, monkeypatch,
    ):
        """The import probe only asks whether a library imports, so an add
        left out a library the image holds at a version the package does not
        accept, and its nodes then ran the image's."""
        from utk_curio.backend.tests._support.front_of_the_image import (
            OTHER_TORCH, held, offline_pip, the_images_torch,
        )

        image_torch = the_images_torch()
        offline_pip(monkeypatch, tmp_path / "wheelhouse")

        provisioning.provision_python_deps(
            "7", "ai.test.next-torch@1", _Manifest({"torch": f">={OTHER_TORCH.version}"}),
        )

        tree = held(rt.user_node_overlay_dir("7"))
        assert tree.get("torch") == OTHER_TORCH.version, (
            f"the add left torch>={OTHER_TORCH.version} out of account 7's tree, which holds {tree}: "
            f"its nodes import the image's {image_torch}, which the package does not accept")

    def test_an_add_takes_out_a_torch_of_the_tree_its_range_misses_where_the_images_meets_it(
        self, isolated, launch_tree, tmp_path, monkeypatch,
    ):
        """An earlier add can have put into the tree a torch a new package's
        range does not accept, in front of the image's, which it does: the
        add takes the tree's copy out, and its nodes import the image's."""
        from utk_curio.backend.tests._support.front_of_the_image import held, offline_pip, the_images_torch
        from utk_curio.backend.tests._support.offline_wheels import WheelLibrary, unpack_wheel

        image_torch = the_images_torch()
        offline_pip(monkeypatch, tmp_path / "wheelhouse")
        tree = rt.user_node_overlay_dir("7")
        unpack_wheel(WheelLibrary(dist="torch", version="2.0.0", module="curio_old_torch", message="old"), tree)
        assert held(tree) == {"torch": "2.0.0"}

        provisioning.provision_python_deps("7", "ai.test.torch@1", _Manifest({"torch": ">=2.6"}))

        left = held(tree)
        assert "torch" not in left, (
            f"account 7's tree still holds torch {left.get('torch')}, which torch>=2.6 does not accept, "
            f"in front of the image's {image_torch}, which it does")


class TestTheProbeAsksTheRightInterpreter:

    def test_a_node_overlay_is_not_probed_through_the_handler_pin(
        self, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        """``CURIO_BACKEND_SANDBOX_PYTHON`` pins the interpreter package-backend
        WORKERS run under. The sandbox that imports a node overlay is started
        with the backend's own interpreter, so following that pin here would
        answer for one that never imports this tree."""
        import sys

        from utk_curio.backend.app.packages.infrastructure import pip_runner

        monkeypatch.setenv("CURIO_BACKEND_SANDBOX_PYTHON", "/nonexistent/python")
        seen: list[str | None] = []

        def _probe(deps, path, interpreter=None):
            seen.append(interpreter)
            return {d: "not installed" for d in deps}

        monkeypatch.setattr(pip_runner, "import_failures_in", _probe)
        provisioning.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))

        assert seen and all(i == sys.executable for i in seen)
        assert rt.sandbox_interpreter() == "/nonexistent/python", "the pin is real"


class TestTheLibrariesDialog:
    """``POST /api/packages/libraries`` is how a user actually installs one, and
    it does not go through ``provision_python_deps`` - it reaches pip itself. So
    it needs the same routing, proved separately."""

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def test_without_isolation_it_installs_into_the_shared_interpreter(
        self, client, user_and_token, in_process, pip_calls, launch_tree,
    ):
        _, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "humanize"},
            headers=self._auth(token),
        )

        assert resp.status_code == 201, resp.get_data(as_text=True)
        assert [c[0] for c in pip_calls] == ["host"]

    def test_with_isolation_it_installs_into_the_callers_own_tree(
        self, client, user_and_token, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        monkeypatch.setattr(
            pip_runner, "import_failures_in",
            lambda deps, path, interpreter=None: {},
        )
        user, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "humanize"},
            headers=self._auth(token),
        )

        assert resp.status_code == 201, resp.get_data(as_text=True)
        assert [c[0] for c in pip_calls] == ["target"]
        assert str(user.id) in pip_calls[0][2]

    def test_without_isolation_removing_a_library_curio_did_not_install_uninstalls_nothing(
        self, client, user_and_token, in_process, uninstall_calls, launch_tree,
    ):
        """One interpreter, the server's, which every account's nodes import
        from: the image's torch is in it from the start. Adding torch in
        Installed libraries finds it already installed, and its Remove ran
        ``pip uninstall torch`` on the server's interpreter, taking the
        image's torch from every account. It now uninstalls only what this
        server's pip installed, as a package's removal does."""
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        assert pip_runner.is_satisfied("torch", ""), "the image's torch is not in this interpreter"
        assert pip_runner.installed_here(["torch"]) == [], "this server's pip installed torch"
        _, token = user_and_token
        added = client.post("/api/packages/libraries", json={"kind": "python", "spec": "torch"},
                            headers=self._auth(token))
        assert added.status_code == 201, added.get_data(as_text=True)

        removed = client.delete("/api/packages/libraries/python/torch", headers=self._auth(token))

        assert removed.status_code == 200, removed.get_data(as_text=True)
        assert removed.get_json()["standalone"]["python"] == []
        assert uninstall_calls == [], f"the dialog uninstalled what Curio never installed: {uninstall_calls}"

    def test_without_isolation_removing_a_library_this_server_installed_for_it_uninstalls_it(
        self, client, user_and_token, in_process, pip_that_installs, uninstall_calls, launch_tree,
    ):
        """A library the dialog's own pip run brought into the interpreter,
        which nothing else asks for, leaves with its Remove."""
        _, token = user_and_token
        added = client.post("/api/packages/libraries", json={"kind": "python", "spec": "curio-dialog-probe"},
                            headers=self._auth(token))
        assert added.status_code == 201, added.get_data(as_text=True)
        assert "curio-dialog-probe" in pip_that_installs, "the add never ran pip"

        removed = client.delete("/api/packages/libraries/python/curio-dialog-probe", headers=self._auth(token))

        assert removed.status_code == 200, removed.get_data(as_text=True)
        assert uninstall_calls == [("host", ["curio-dialog-probe"], None)]

    def test_the_import_probe_asks_the_environment_it_installed_into(
        self, client, user_and_token, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        """Asking the host about a library that went into the user's tree would
        report a perfectly good install as broken."""
        from utk_curio.backend.app.packages.infrastructure import pip_runner

        monkeypatch.setattr(
            pip_runner, "import_failures",
            lambda deps: {d: "No module named it" for d in deps},
        )
        monkeypatch.setattr(
            pip_runner, "import_failures_in",
            lambda deps, path, interpreter=None: {},
        )
        _, token = user_and_token
        resp = client.post(
            "/api/packages/libraries",
            json={"kind": "python", "spec": "humanize"},
            headers=self._auth(token),
        )

        assert resp.get_json()["importError"] is None


@pytest.fixture
def uninstall_calls(monkeypatch):
    """Record which uninstaller was reached, without removing anything."""
    from utk_curio.backend.app.packages.infrastructure import pip_runner
    from utk_curio.backend.app.packages.infrastructure.pip_runner import UninstallReport

    calls: list[tuple[str, list[str], str | None]] = []

    def _from_target(names, target_dir):
        calls.append(("target", list(names), str(target_dir)))
        return UninstallReport(removed=list(names), kept=[])

    def _from_host(names):
        calls.append(("host", list(names), None))
        return UninstallReport(removed=list(names), kept=[])

    monkeypatch.setattr(
        pip_runner, "uninstall_python_deps_from_target", _from_target)
    monkeypatch.setattr(pip_runner, "uninstall_python_deps", _from_host)
    return calls


class TestWhereTheUninstallLands:
    """Remove has to follow install. Under isolation the library lives in the
    caller's overlay, so uninstalling from the shared interpreter would both
    miss their copy and risk taking a host-level package with it."""

    def test_without_isolation_it_uses_the_shared_interpreter(
        self, in_process, uninstall_calls, launch_tree,
    ):
        libraries.uninstall_user_library("alice", "humanize")

        assert uninstall_calls == [("host", ["humanize"], None)]

    def test_under_isolation_it_uses_the_callers_own_tree(
        self, isolated, uninstall_calls, launch_tree,
    ):
        overlay = rt.user_node_overlay_dir("alice")
        overlay.mkdir(parents=True, exist_ok=True)

        libraries.uninstall_user_library("alice", "humanize")

        assert uninstall_calls == [("target", ["humanize"], str(overlay))]

    def test_under_isolation_it_never_reaches_the_shared_interpreter(
        self, isolated, uninstall_calls, launch_tree,
    ):
        rt.user_node_overlay_dir("alice").mkdir(parents=True)

        libraries.uninstall_user_library("alice", "humanize")

        assert [kind for kind, _, _ in uninstall_calls] == ["target"]

    def test_one_users_removal_leaves_another_users_copy_alone(
        self, isolated, uninstall_calls, launch_tree,
    ):
        for who in ("alice", "bob"):
            rt.user_node_overlay_dir(who).mkdir(parents=True)

        libraries.uninstall_user_library("alice", "humanize")

        target = uninstall_calls[0][2]
        assert target == str(rt.user_node_overlay_dir("alice"))
        assert str(rt.user_node_overlay_dir("bob")) != target

    def test_a_user_with_no_tree_is_a_clean_no_op(
        self, isolated, uninstall_calls, launch_tree,
    ):
        report = libraries.uninstall_user_library("nobody", "humanize")

        assert uninstall_calls == []
        assert report.removed == []
        assert report.kept == ["humanize"]


def _transformers_libraries() -> dict[str, str]:
    """What a model the Discovery Catalog's Hugging Face source adds declares:
    the libraries a Transformers checkpoint runs on, torch among them."""
    from utk_curio.backend.app.discovery.application.model_acquire import RUNTIME_DEPS

    return dict(RUNTIME_DEPS["transformers"])


def _new_dataflow(client, token) -> str:
    """A new, empty dataflow of the account *token* signs in; its id."""
    resp = client.post(
        "/api/projects",
        json={
            "name": "uses-a-package",
            "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
            "outputs": [],
        },
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


@pytest.fixture
def a_dataflow_using(client, user_and_token, install_package, manifest_dict, monkeypatch):
    """Factory: a new dataflow of the signed-in account that uses a package
    of the account's own declaring *python_deps*. Returns ``(user_key,
    project_id, manifest)``.

    Adding a package the store holds asks whether its libraries import, so the
    probes are stubbed: nothing here imports a library for real.
    """
    from utk_curio.backend.app.packages import service as packages_service
    from utk_curio.backend.app.packages.infrastructure import pip_runner
    from utk_curio.backend.app.projects import services as projects_services

    monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})
    monkeypatch.setattr(
        pip_runner, "import_failures_in", lambda deps, path, interpreter=None: {})
    user, token = user_and_token
    user_key = projects_services._user_dir_key(user)

    def _make(package_id: str, python_deps: dict[str, str]):
        manifest = install_package(
            user_key, manifest_dict(package_id, python_deps=python_deps)).manifest
        project_id = _new_dataflow(client, token)
        packages_service.install_to_project(user_key, project_id, manifest.dir_name)
        return user_key, project_id, manifest

    return _make


class TestAddingAPackageTheStoreHolds:
    """Add to project answers whether a package the account already holds
    still works (``store_install._ensure_user_store_install``), by probing the
    libraries it declares. The probe has to ask where they were installed."""

    def test_under_isolation_its_libraries_are_probed_in_the_accounts_own_tree(
        self, isolated, launch_tree, client, user_and_token, install_package,
        manifest_dict, monkeypatch,
    ):
        """Under isolation the libraries are in the account's own tree, and the
        shared interpreter has never heard of them: asking it reported every
        one as not installed, on a package that works."""
        from utk_curio.backend.app.packages import service as packages_service
        from utk_curio.backend.app.packages.infrastructure import pip_runner
        from utk_curio.backend.app.projects import services as projects_services

        user, token = user_and_token
        user_key = projects_services._user_dir_key(user)
        rt.user_node_overlay_dir(user_key).mkdir(parents=True)
        monkeypatch.setattr(
            pip_runner, "import_failures",
            lambda deps: {d: f"{d} is not installed" for d in deps},
        )
        monkeypatch.setattr(
            pip_runner, "import_failures_in", lambda deps, path, interpreter=None: {})
        manifest = install_package(user_key, manifest_dict(
            "ai.test.own", python_deps={"curio-own-library": ">=1.0"})).manifest

        result = packages_service.install_to_project(
            user_key, _new_dataflow(client, token), manifest.dir_name)

        assert result["importErrors"] == {}


class TestRemovingAPackageFromItsLastDataflow:
    """Remove from project prunes a package no dataflow of the account uses
    any more (``prune.prune_unreferenced_packages``), with the libraries only
    it asked for. They leave from where its install put them, as the
    libraries dialog's do (above): under isolation the account's own tree,
    never the one interpreter the image and every other account run on."""

    def test_under_isolation_a_models_libraries_leave_only_the_accounts_own_tree(
        self, isolated, launch_tree, a_dataflow_using, uninstall_calls,
    ):
        """Removing a Hugging Face model from a dataflow ran ``pip uninstall
        -y safetensors torch transformers`` on the server's own interpreter.
        That took the image's torch from every account, examples 27 to 30
        and SAM 3's Track Objects among them, until the container was made
        again."""
        from utk_curio.backend.app.packages import service as packages_service

        user_key, project_id, manifest = a_dataflow_using(
            "ai.test.hf-model", _transformers_libraries())
        own_tree = rt.user_node_overlay_dir(user_key)
        own_tree.mkdir(parents=True, exist_ok=True)
        other_tree = rt.user_node_overlay_dir("9999")
        other_tree.mkdir(parents=True)

        result = packages_service.uninstall_from_project(user_key, project_id, manifest.dir_name)

        assert result["pruned"] == [manifest.dir_name]
        assert uninstall_calls == [
            ("target", sorted(_transformers_libraries()), str(own_tree)),
        ], f"the removal reached beyond the account's own tree: {uninstall_calls}"

    def test_under_isolation_a_library_on_the_accounts_own_list_stays(
        self, isolated, launch_tree, a_dataflow_using, uninstall_calls,
    ):
        """A library the account installed itself, in Installed libraries, is
        its own choice: a package that declared it too does not take it."""
        from utk_curio.backend.app.packages import service as packages_service

        user_key, project_id, manifest = a_dataflow_using(
            "ai.test.hf-model", _transformers_libraries())
        libraries.add_library(user_key, "python", "torch")
        own_tree = rt.user_node_overlay_dir(user_key)
        own_tree.mkdir(parents=True, exist_ok=True)

        packages_service.uninstall_from_project(user_key, project_id, manifest.dir_name)

        assert uninstall_calls == [
            ("target", sorted(set(_transformers_libraries()) - {"torch"}), str(own_tree)),
        ]

    def test_without_isolation_a_library_the_interpreter_already_held_stays(
        self, in_process, launch_tree, a_dataflow_using, uninstall_calls,
    ):
        """One interpreter, the server's: Curio runs on it, and on an image
        torch is in it from the start. This server's pip installed none of the
        model's libraries, so none of them is uninstalled."""
        from utk_curio.backend.app.packages import service as packages_service

        user_key, project_id, manifest = a_dataflow_using(
            "ai.test.hf-model", _transformers_libraries())

        result = packages_service.uninstall_from_project(user_key, project_id, manifest.dir_name)

        assert result["pruned"] == [manifest.dir_name]
        assert uninstall_calls == [], (
            f"the removal uninstalled libraries this server never installed: {uninstall_calls}"
        )

    def test_without_isolation_a_library_this_server_installed_for_it_goes(
        self, in_process, launch_tree, a_dataflow_using, pip_that_installs, uninstall_calls,
    ):
        """A local Curio keeps its interpreter tidy: a library its own pip
        brought in for the package, which nothing else asks for, leaves with
        the package."""
        from utk_curio.backend.app.packages import service as packages_service

        user_key, project_id, manifest = a_dataflow_using(
            "ai.test.tidy", {"curio-prune-probe": ">=1.0"})
        provisioning.provision_python_deps(user_key, manifest.dir_name, manifest)
        assert "curio-prune-probe" in pip_that_installs, "the install never ran pip"

        packages_service.uninstall_from_project(user_key, project_id, manifest.dir_name)

        assert uninstall_calls == [("host", ["curio-prune-probe"], None)]

    def test_without_isolation_a_library_another_account_asks_for_stays(
        self, in_process, launch_tree, a_dataflow_using, pip_that_installs,
        install_package, manifest_dict, uninstall_calls,
    ):
        """Every account's nodes import from the one interpreter, so a library
        stays while any account's package declares it."""
        from utk_curio.backend.app.packages import service as packages_service

        user_key, project_id, manifest = a_dataflow_using(
            "ai.test.mine", {"curio-prune-shared": ">=1.0"})
        provisioning.provision_python_deps(user_key, manifest.dir_name, manifest)
        assert "curio-prune-shared" in pip_that_installs, "the install never ran pip"
        install_package("9999", manifest_dict(
            "ai.test.theirs", python_deps={"curio-prune-shared": ">=1.0"}))

        packages_service.uninstall_from_project(user_key, project_id, manifest.dir_name)

        assert uninstall_calls == [], (
            f"the removal uninstalled a library another account's package declares: {uninstall_calls}"
        )
