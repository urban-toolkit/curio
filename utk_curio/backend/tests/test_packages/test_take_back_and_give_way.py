"""What a removal takes back, and what an install over a store copy does.

A package's removal takes back the libraries its install put where node code
imports from that nothing asks for now, and the account's tree then gives way
to the image (``libraries.take_back_after_a_removal``). Two gaps were left:

- The take-back decided which libraries nothing asks for before it held
  where they are, then took that hold to uninstall them. An add landing in
  between found a copy there, installed nothing, and the take-back then took
  that copy out.
- Of the installs that put a version of a package in place of the account's
  copy, only the catalogs' Update took back what the copy it replaced asked
  for alone, and gave way. Import package over a copy, a model downloaded
  again, an applied build and the seeder's refresh of a copy nobody changed
  did neither.

Every library here is installed offline, from a wheelhouse of the test's own
(``_support/front_of_the_image``), or by a pip that changes nothing for real.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.app.packages.infrastructure import backend_runtime as rt
# The real installer and uninstaller, taken before the package tests' stubs
# replace them (``conftest._stub_pip_runner``).
from utk_curio.backend.app.packages.infrastructure.pip_runner import (
    install_python_deps as _real_install_python_deps,
    uninstall_python_deps as _real_uninstall_python_deps,
)

#: The package whose copy the installs here replace.
PACKAGE = "ai.test.next-torch"
#: A downloaded model's package.
MODEL = "ai.test.downloaded-model"


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv("CURIO_ISOLATION", "fork")


@pytest.fixture
def in_process(monkeypatch):
    monkeypatch.setenv("CURIO_ISOLATION", "off")


@pytest.fixture
def launch_tree(monkeypatch, tmp_path):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")
    return tmp_path


def _no_import_probe(monkeypatch) -> None:
    """Every library reads as importable: nothing here imports one for real."""
    from utk_curio.backend.app.packages.infrastructure import pip_runner

    monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})
    monkeypatch.setattr(pip_runner, "import_failures_in", lambda deps, path, interpreter=None: {})


def _the_other_torch_in(user_key: str):
    """*user_key*'s own node libraries holding a torch that is not the
    image's, 2.99.0, as the add of a package declaring ``torch>=2.99.0`` left
    them; the tree."""
    from utk_curio.backend.tests._support.front_of_the_image import OTHER_TORCH, held
    from utk_curio.backend.tests._support.offline_wheels import unpack_wheel

    tree = rt.user_node_overlay_dir(user_key)
    unpack_wheel(OTHER_TORCH, tree)
    assert held(tree) == {"torch": OTHER_TORCH.version}
    return tree


def _the_account_of(user_and_token) -> tuple[str, str]:
    """The store key and the token of the signed-in account."""
    from utk_curio.backend.app.projects import services as projects_services

    user, token = user_and_token
    return projects_services._user_dir_key(user), token


def _an_interpreter_on_disk(monkeypatch, tmp_path):
    """The one interpreter, as two processes see it: the real
    ``install_python_deps`` and ``uninstall_python_deps``, each holding the
    interpreter's lock, over a pip that changes nothing for real. A library
    is there once a ``pip install`` named it and until a ``pip uninstall``
    names it, kept in a file both processes read, and this start's record
    of what its pip installed starts empty. Returns what the interpreter
    holds, read."""
    import json
    import os
    import re
    import subprocess
    import types
    from importlib.metadata import PackageNotFoundError

    from utk_curio.backend.app.packages.infrastructure import pip_runner

    state = tmp_path / "interpreter.json"
    state.write_text("{}", encoding="utf-8")

    def _held() -> dict:
        return json.loads(state.read_text(encoding="utf-8"))

    def _version(name):
        there = _held()
        if name not in there:
            raise PackageNotFoundError(name)
        return there[name]

    def _run(cmd, *args, **kwargs):
        verb, there = cmd[3], _held()
        assert verb in ("install", "uninstall"), f"only pip install and pip uninstall are faked: {cmd}"
        for requirement in (arg for arg in cmd[4:] if not arg.startswith("-")):
            name = re.split(r"[<>=!~]", requirement, maxsplit=1)[0]
            if verb == "install":
                there[name] = "1.0"
            else:
                there.pop(name, None)
        partial = state.with_name(f".{state.name}.{os.getpid()}")
        partial.write_text(json.dumps(there), encoding="utf-8")
        os.replace(partial, state)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(pip_runner, "install_python_deps", _real_install_python_deps)
    monkeypatch.setattr(pip_runner, "uninstall_python_deps", _real_uninstall_python_deps)
    monkeypatch.setattr(pip_runner, "installed_version", _version)
    monkeypatch.setattr(
        pip_runner, "subprocess", types.SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired),
    )
    monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})
    monkeypatch.setattr(pip_runner, "_installed_here", set())
    return _held


def _stops_once_it_has_decided(monkeypatch, window) -> None:
    """A take-back, in the process the race forks, stops at *window* once it
    has decided which libraries nothing asks for now
    (``libraries.not_asked_for``), before it uninstalls them."""
    from utk_curio.backend.app.packages.application import libraries

    decides = libraries.not_asked_for

    def _decides_then_stops(user_keys, names):
        kept = decides(user_keys, names)
        window.stop_here()
        return kept

    monkeypatch.setattr(libraries, "not_asked_for", _decides_then_stops)


class TestATakeBackDecidesWhereItHoldsTheTree:
    """A removal's take-back decided which libraries nothing asks for
    (``libraries.names_to_take_back``) holding nothing, then took the tree's
    lock to uninstall them. An add of a package declaring one of them, in
    another backend process or on another thread, could land in between: it
    found the copy still there and installed nothing, and the take-back took
    the copy out after it. The added package's nodes then ran on the image's
    copy, outside their range, until the next start.

    The removal runs in a forked process (``_support/two_processes``) and
    stops once it has decided. The add runs then, and the removal goes on
    once the add has ended or waits for the tree, so no step waits on a
    timer."""

    @pytest.mark.parametrize("removal", ["installed-libraries-remove", "remove-from-project"])
    def test_under_isolation_an_add_racing_a_take_back_installs_what_it_took_out(
        self, removal, isolated, launch_tree, install_package, manifest_dict, tmp_path, monkeypatch,
    ):
        """Account 7's tree holds a torch 2.99 that only one thing asks for:
        its own Installed libraries list, whose Remove takes it back, or a
        package, which Remove from project takes off the account on its last
        dataflow. The add of ``ai.test.also-next-torch``, declaring
        ``torch>=2.99.0`` too, comes once the take-back has decided."""
        from utk_curio.backend.app.packages.application import libraries, provisioning
        from utk_curio.backend.app.packages.application import prune as packages_prune
        from utk_curio.backend.tests._support.front_of_the_image import (
            OTHER_TORCH, held, offline_pip, the_images_torch,
        )
        from utk_curio.backend.tests._support.two_processes import Window, race

        image_torch = the_images_torch()
        offline_pip(monkeypatch, tmp_path / "wheelhouse")
        _no_import_probe(monkeypatch)
        user_key = "7"
        if removal == "installed-libraries-remove":
            spec = f"torch=={OTHER_TORCH.version}"
            libraries.add_library(user_key, "python", spec)

            def _the_removal():
                return libraries.remove_standalone_library(user_key, "python", spec)
        else:
            removed = install_package(user_key, manifest_dict(
                PACKAGE, python_deps={"torch": f">={OTHER_TORCH.version}"})).manifest
            # No dataflow of the account uses it now, as after Remove from
            # project on its last one; the forked removal reads no database.
            monkeypatch.setattr(packages_prune, "packages_in_use", lambda user_key, candidates=None: set())

            def _the_removal():
                return packages_prune.prune_unreferenced_packages(user_key, [removed.dir_name])
        tree = _the_other_torch_in(user_key)
        window = Window()
        _stops_once_it_has_decided(monkeypatch, window)

        def _the_add():
            added = install_package(user_key, manifest_dict(
                "ai.test.also-next-torch", python_deps={"torch": f">={OTHER_TORCH.version}"})).manifest
            return provisioning.provision_python_deps(user_key, added.dir_name, added)

        raced = race(window, _the_removal, _the_add, monkeypatch)

        assert raced.child_exit == 0, raced.child_error
        left = held(tree)
        assert left.get("torch") == OTHER_TORCH.version, (
            f"a take-back in another process ({removal}) decided to take torch back before the add of "
            f"ai.test.also-next-torch, declaring torch>={OTHER_TORCH.version}, landed, and took it out after the "
            f"add had found it: account {user_key}'s tree holds {left}, so the added package's nodes import the "
            f"image's torch {image_torch}, which it does not accept")

    def test_without_isolation_an_add_racing_a_take_back_installs_what_it_took_out(
        self, in_process, launch_tree, install_package, manifest_dict, tmp_path, monkeypatch,
    ):
        """One interpreter, which every account's nodes import from. Account
        7's own Installed libraries list named ``curio-race-probe``, which
        this server's pip installed for it, and its Remove takes it back. The
        add of a package declaring it comes once the take-back has decided."""
        from utk_curio.backend.app.packages.application import libraries, provisioning
        from utk_curio.backend.tests._support.two_processes import Window, race

        library = "curio-race-probe"
        interpreter = _an_interpreter_on_disk(monkeypatch, tmp_path)
        user_key = "7"
        libraries.add_standalone_library(user_key, "python", library)
        assert library in interpreter(), "the dialog's add installed nothing"
        window = Window()
        _stops_once_it_has_decided(monkeypatch, window)

        def _the_add():
            added = install_package(user_key, manifest_dict(
                "ai.test.race-probe", python_deps={library: ">=1.0"})).manifest
            return provisioning.provision_python_deps(user_key, added.dir_name, added)

        raced = race(
            window, lambda: libraries.remove_standalone_library(user_key, "python", library), _the_add,
            monkeypatch,
        )

        assert raced.child_exit == 0, raced.child_error
        held = interpreter()
        assert library in held, (
            f"the Remove of {library} in Installed libraries, in another process, decided to take it back before "
            f"the add of ai.test.race-probe, declaring it, landed, and uninstalled it after the add had found it: "
            f"the interpreter holds {sorted(held)}, so the added package's nodes cannot import it")


def _deps(torch: str | None) -> dict[str, str]:
    """Version 1.1.0's libraries: torch at *torch*, or no torch."""
    return {"torch": torch} if torch else {}


def _version_1_0_0_in(user_key, install_package, manifest_dict, tmp_path, monkeypatch):
    """The account's copy of the package, version 1.0.0, declaring
    ``torch>=2.99.0``, with the torch its add put into the tree; the tree."""
    from utk_curio.backend.tests._support.front_of_the_image import OTHER_TORCH, offline_pip

    offline_pip(monkeypatch, tmp_path / "wheelhouse")
    _no_import_probe(monkeypatch)
    install_package(user_key, manifest_dict(PACKAGE, python_deps={"torch": f">={OTHER_TORCH.version}"}))
    return _the_other_torch_in(user_key)


def _a_downloaded_model(version: str, python_deps: dict[str, str]) -> dict:
    """A model package's manifest as a download from the Discovery Catalog
    writes one: *version* of it, declaring *python_deps*."""
    return {
        "id": MODEL, "kind": "model", "name": "Tiny", "version": version, "compatibility": {"major": 1},
        "publisher": "org", "license": "MIT",
        "dependencies": {"packages": {}, "python": dict(python_deps), "js": {}},
        "templates": [{
            "id": "tiny", "label": "Tiny", "category": "computation", "engine": "python", "editor": "code",
            "inputPorts": [], "outputPorts": [{"types": ["JSON"]}],
        }],
        "model": {
            "type": "semantic-segmentation", "runtime": "onnx", "entry": "models/m.onnx", "labels": ["a", "b"],
            "input": {"width": 64, "height": 32, "dtype": "float32", "scale": 0.00392},
            "license": "MIT", "publisher": "org", "sizeBytes": 4,
        },
    }


def _the_files_of_a_download(tmp_path, name: str):
    """What a download fetched, the ONNX file its model block names, in a
    folder of its own, which its install consumes."""
    files = tmp_path / f"download-{name}"
    files.mkdir()
    (files / "m.onnx").write_bytes(b"onnx")
    return files


def _a_staged_build(manifest_dict, user_key: str, python_deps: dict[str, str]) -> str:
    """An agent's build of version 1.1.0 of the package, staged for its
    promotion; its digest."""
    from utk_curio.backend.app.packages.builder.models import parse_build_request
    from utk_curio.backend.app.packages.builder.packager import assemble_archive
    from utk_curio.backend.app.packages.repositories import staging as build_staging

    request = parse_build_request({
        "mode": "create", "target": f"{PACKAGE}@1",
        "manifest": manifest_dict(PACKAGE, version="1.1.0", python_deps=python_deps),
        "files": {"starters/demo-kind/Default.py": {"text": "return input_0\n"}},
    })
    archive, _ = assemble_archive(request, request.files, None, {"python": python_deps, "js": {}, "packages": {}})
    return build_staging.stage_artifact(user_key, archive)


def _a_catalog_of(root, monkeypatch, make_archive, manifest: dict):
    """The shared catalog, a folder of the test's own at *root*
    (``CURIO_PACKAGES_ROOT``), holding the package *manifest* describes, as
    its archive unpacks, with the integrity map a release commits beside it;
    the package's folder."""
    import io
    import zipfile

    from utk_curio.backend.app.packages.repositories.archive import refresh_package_integrity

    folder = root / f"{manifest['id']}@{manifest['compatibility']['major']}"
    with zipfile.ZipFile(io.BytesIO(make_archive(manifest=manifest))) as archive:
        archive.extractall(folder)
    refresh_package_integrity(folder)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    return folder


def _the_trees_torch_went(tree, user_key: str, what: str, torch: str | None, image_torch: str) -> None:
    from utk_curio.backend.tests._support.front_of_the_image import OTHER_TORCH, held

    left = held(tree)
    why = (f"which meets torch{torch}, the one range of torch its packages declare now" if torch
           else "and no package of the account asks for torch now")
    assert "torch" not in left, (
        f"after {what} put version 1.1.0 in place of account {user_key}'s 1.0.0, which declared "
        f"torch>={OTHER_TORCH.version}, its tree still holds torch {left.get('torch')} in front of the image's "
        f"{image_torch}, {why}")


#: Version 1.1.0 declares a range of torch the image's meets, or no torch.
_NEW_TORCH = pytest.mark.parametrize("torch", [">=2.6", None], ids=["a-range-the-images-torch-meets", "no-torch"])


class TestAnInstallOverACopyTakesBackAndGivesWay:
    """An install over the account's copy of a package is a removal of that
    copy as much as an add of the new one. Only the catalogs' Update took
    back the libraries the copy it replaced asked for alone, and gave way to
    the image. The other installs over a copy did neither: a library only
    the replaced copy declared stayed in the account's tree for good, and a
    copy the new version's range lets the image's win over stayed in front
    of it until the next start.

    Here the account's copy, version 1.0.0, declares ``torch>=2.99.0``,
    whose add put a torch 2.99 into the tree, and version 1.1.0 declares
    ``torch>=2.6``, which the image's torch meets, or no torch."""

    @_NEW_TORCH
    def test_import_package_over_the_copy(
        self, torch, isolated, launch_tree, install_package, manifest_dict, make_archive, client,
        user_and_token, tmp_path, monkeypatch,
    ):
        """``POST /api/packages/upload?replace=true``, which the API offers:
        the catalog pages' **Import package** sends no ``replace``, and
        refuses an archive of a package the account holds."""
        import io

        from utk_curio.backend.tests._support.front_of_the_image import the_images_torch

        image_torch = the_images_torch()
        user_key, token = _the_account_of(user_and_token)
        tree = _version_1_0_0_in(user_key, install_package, manifest_dict, tmp_path, monkeypatch)
        archive = make_archive(manifest=manifest_dict(PACKAGE, version="1.1.0", python_deps=_deps(torch)))

        replaced = client.post(
            "/api/packages/upload?replace=true",
            data={"file": (io.BytesIO(archive), f"{PACKAGE}@1.curio.zip")},
            headers={"Authorization": f"Bearer {token}"},
            content_type="multipart/form-data",
        )

        assert replaced.status_code == 201, replaced.get_data(as_text=True)
        assert replaced.get_json()["replacedExisting"] is True
        _the_trees_torch_went(tree, user_key, "Import package with replace", torch, image_torch)

    @_NEW_TORCH
    def test_a_model_downloaded_again(self, torch, isolated, launch_tree, tmp_path, monkeypatch):
        """The Discovery Catalog's add of a model the account holds, asked
        with ``refresh``, installs the new download over the package the
        first one made (``model_acquire``, ``replace``), then its libraries
        (``install_downloaded_model_deps``). They differ when the model's
        runtime changed since the first download, or Curio's ranges for that
        runtime did."""
        from utk_curio.backend.app.packages import service as packages_service
        from utk_curio.backend.tests._support.front_of_the_image import OTHER_TORCH, offline_pip, the_images_torch

        image_torch = the_images_torch()
        user_key = "7"
        offline_pip(monkeypatch, tmp_path / "wheelhouse")
        _no_import_probe(monkeypatch)
        packages_service.install_downloaded_model(
            user_key, _the_files_of_a_download(tmp_path, "first"),
            _a_downloaded_model("1.0.0", {"torch": f">={OTHER_TORCH.version}"}),
        )
        tree = _the_other_torch_in(user_key)

        installed = packages_service.install_downloaded_model(
            user_key, _the_files_of_a_download(tmp_path, "again"), _a_downloaded_model("1.1.0", _deps(torch)),
            replace=True,
        )
        packages_service.install_downloaded_model_deps(user_key, installed)

        assert installed.version == "1.1.0"
        _the_trees_torch_went(tree, user_key, "a model downloaded again", torch, image_torch)

    @_NEW_TORCH
    def test_an_applied_build_once_its_nodes_are_made(
        self, torch, isolated, launch_tree, install_package, manifest_dict, tmp_path, monkeypatch,
    ):
        """An agent's build of the package, applied over the copy it extends
        (``builder/promotion.promote``). Its promotion completes once the
        canvas has made the build's nodes (``confirm_nodes_created``), and no
        rollback can come after that."""
        from utk_curio.backend.app.packages.builder.extension import installed_package_digest
        from utk_curio.backend.app.packages.builder.promotion import (
            confirm_nodes_created, confirm_registry_ready, promote,
        )
        from utk_curio.backend.tests._support.front_of_the_image import the_images_torch

        image_torch = the_images_torch()
        user_key = "7"
        tree = _version_1_0_0_in(user_key, install_package, manifest_dict, tmp_path, monkeypatch)
        base = installed_package_digest(user_key, f"{PACKAGE}@1")
        digest = _a_staged_build(manifest_dict, user_key, _deps(torch))

        promote(user_key, target=f"{PACKAGE}@1", artifact_digest=digest, base_digest=base)
        confirm_registry_ready(user_key, digest)
        journal = confirm_nodes_created(user_key, digest)

        assert journal["status"] == "completed", journal
        _the_trees_torch_went(tree, user_key, "an applied build", torch, image_torch)

    @_NEW_TORCH
    def test_the_seeders_refresh_of_a_copy_nobody_changed(
        self, torch, isolated, launch_tree, tmp_curio, manifest_dict, make_archive, tmp_path, monkeypatch,
    ):
        """The seeder puts the shared catalog's version in place of an
        account's copy of it that nobody changed, once the catalog moves on,
        as an upgrade of Curio moves it (#194): on a read of the store, and
        for the shared guest as a start begins (``seeding.seed_dev_packages``),
        so after the start's give-way. It installs none of the new version's
        libraries, which the next start installs."""
        from utk_curio.backend.app.packages.application import seeding, store_install
        from utk_curio.backend.tests._support.front_of_the_image import OTHER_TORCH, offline_pip, the_images_torch

        image_torch = the_images_torch()
        user_key = "7"
        offline_pip(monkeypatch, tmp_path / "wheelhouse")
        _no_import_probe(monkeypatch)
        added = _a_catalog_of(tmp_path / "catalog-1.0.0", monkeypatch, make_archive, manifest_dict(
            PACKAGE, version="1.0.0", python_deps={"torch": f">={OTHER_TORCH.version}"}))
        store_install.install_package_from_directory(user_key, added)
        tree = _the_other_torch_in(user_key)
        _a_catalog_of(tmp_path / "catalog-1.1.0", monkeypatch, make_archive, manifest_dict(
            PACKAGE, version="1.1.0", python_deps=_deps(torch)))

        refreshed = seeding.seed_dev_packages(user_key=user_key)

        assert f"{PACKAGE}@1" in refreshed, f"the seeder did not refresh account {user_key}'s copy: {refreshed}"
        _the_trees_torch_went(tree, user_key, "the seeder's refresh", torch, image_torch)

    def test_an_applied_build_rolled_back_leaves_the_libraries_of_the_copy_it_puts_back(
        self, isolated, launch_tree, install_package, manifest_dict, tmp_path, monkeypatch,
    ):
        """The mirror case. Until the canvas has made the build's nodes, its
        promotion can roll back (``rollback``): version 1.0.0 comes back from
        its backup, and no library is installed again with it. So the torch
        1.0.0 asks for stays in the tree while the build, which declares no
        torch, is in place."""
        from utk_curio.backend.app.packages.builder.extension import installed_package_digest
        from utk_curio.backend.app.packages.builder.promotion import promote, rollback
        from utk_curio.backend.tests._support.front_of_the_image import OTHER_TORCH, held, the_images_torch

        image_torch = the_images_torch()
        user_key = "7"
        tree = _version_1_0_0_in(user_key, install_package, manifest_dict, tmp_path, monkeypatch)
        base = installed_package_digest(user_key, f"{PACKAGE}@1")
        digest = _a_staged_build(manifest_dict, user_key, {})
        promote(user_key, target=f"{PACKAGE}@1", artifact_digest=digest, base_digest=base)

        journal = rollback(user_key, digest, "the canvas could not make the build's nodes")

        assert journal["status"] == "rolled-back", journal
        assert installed_package_digest(user_key, f"{PACKAGE}@1") == base
        assert held(tree) == {"torch": OTHER_TORCH.version}, (
            f"an applied build of version 1.1.0, which declares no torch, was rolled back to 1.0.0, which declares "
            f"torch>={OTHER_TORCH.version}, and account {user_key}'s tree holds {held(tree)}: the nodes of 1.0.0 "
            f"import the image's torch {image_torch}, which it does not accept")
