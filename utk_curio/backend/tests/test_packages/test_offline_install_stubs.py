"""The two test-only doors the offline install e2e tests stand on.

``test_frontend/test_package_libraries_offline_e2e.py`` adds a test package
along each install path and lets the real pip install its library, offline.
It needs a wheelhouse the backend's pip reads instead of an index
(``/api/testing/wheelhouse``), and the test package in the shared catalog
(``/api/testing/catalog-package``). These tests hold each door to that: the
staged wheel is what pip installs with no index, everything is put back
afterwards, nothing but a test library or a test package gets through, and
every test package is one the catalog accepts, with a library of its own.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from utk_curio.backend.tests._support.offline_wheels import (
    WheelLibrary,
    build_wheel,
    wheel_file_name,
)

LIB = WheelLibrary(
    dist="curio-wheelhouse-unit",
    version="1.0.0",
    module="curio_wheelhouse_unit",
    message="curio-wheelhouse-unit 1.0.0 imported from the test wheelhouse",
)
PIP_KEYS = ("PIP_NO_INDEX", "PIP_FIND_LINKS", "PIP_DISABLE_PIP_VERSION_CHECK")
TEST_PACKAGES = Path(__file__).resolve().parents[1] / "test_frontend" / "packages"
#: One test package per e2e test of an install path, each with its own library.
TEST_PACKAGE_DIRS = sorted(path.name for path in TEST_PACKAGES.iterdir() if path.is_dir())
TEST_PACKAGE_DIR = "test.wheelhouse-probe@1"
TEST_PACKAGE = TEST_PACKAGES / TEST_PACKAGE_DIR


def _post(client, route: str, **body):
    return client.post(
        f"/api/testing/{route}",
        data=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )


def _wheel(library: WheelLibrary = LIB) -> dict:
    return {
        "filename": wheel_file_name(library),
        "content": base64.b64encode(build_wheel(library)).decode("ascii"),
    }


def _test_package_files(dir_name: str = TEST_PACKAGE_DIR) -> dict:
    root = TEST_PACKAGES / dir_name
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _own_library(dir_name: str) -> str:
    """The library a test package declares: ``test.wheelhouse-<name>@1``
    declares ``curio-wheelhouse-<name>``, which no other package declares."""
    name = dir_name.removeprefix("test.wheelhouse-").split("@")[0]
    return f"curio-wheelhouse-{name}"


@pytest.fixture(autouse=True)
def _pip_settings_put_back(client, monkeypatch):
    for key in PIP_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    _post(client, "wheelhouse", action="restore")


@pytest.fixture()
def catalog(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "catalog"
    root.mkdir()
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    return root


def test_the_staged_wheel_is_what_pip_installs_with_no_index(client, tmp_path):
    from utk_curio.backend.app.packages.infrastructure import pip_runner

    staged = _post(client, "wheelhouse", action="stage", wheels=[_wheel()])

    assert staged.status_code == 200, staged.get_json()
    body = staged.get_json()
    assert body["installed"] == {"curio_wheelhouse_unit": False}
    assert [os.environ.get(key) for key in PIP_KEYS] == ["1", body["wheelhouse"], "1"]
    # The real pip, reading only the settings the stage left: a --target
    # install keeps the test interpreter untouched.
    target = tmp_path / "target"
    target.mkdir()
    report = pip_runner.install_python_deps_to_target({LIB.dist: LIB.version}, str(target))
    assert report.installed == [f"{LIB.dist}=={LIB.version}"]
    assert (target / f"{LIB.module}.py").read_text(encoding="utf-8") == f"MESSAGE = {LIB.message!r}\n"


def test_restore_puts_pip_back_as_it_was_and_removes_the_wheelhouse(client):
    staged = _post(client, "wheelhouse", action="stage", wheels=[_wheel()]).get_json()

    restored = _post(client, "wheelhouse", action="restore")

    assert restored.status_code == 200, restored.get_json()
    assert [key for key in PIP_KEYS if key in os.environ] == []
    assert not Path(staged["wheelhouse"]).exists()


def test_status_answers_whether_pip_holds_a_test_library(client):
    answer = _post(client, "wheelhouse", action="status", names=[LIB.dist])

    assert answer.status_code == 200, answer.get_json()
    assert answer.get_json() == {"installed": {LIB.dist: False}}


def test_only_a_test_library_reaches_the_wheelhouse(client):
    real = WheelLibrary(dist="numpy", version="9.9.9", module="numpy", message="")

    refused = _post(client, "wheelhouse", action="stage", wheels=[_wheel(real)])

    assert refused.status_code == 400, refused.get_json()
    assert [key for key in PIP_KEYS if key in os.environ] == []
    assert _post(client, "wheelhouse", action="status", names=["numpy"]).status_code == 400


def test_the_e2e_tests_have_a_test_package_each():
    # The card drop, its menu, the guest refusal, the lockfile and the catalog page.
    assert TEST_PACKAGE_DIRS == [
        "test.wheelhouse-catalog@1",
        "test.wheelhouse-guest@1",
        "test.wheelhouse-lockfile@1",
        "test.wheelhouse-pair@1",
        "test.wheelhouse-probe@1",
    ]


@pytest.mark.parametrize("dir_name", TEST_PACKAGE_DIRS)
def test_each_test_package_plants_as_a_catalog_package_with_a_library_of_its_own_and_is_removed(
    client, catalog, dir_name,
):
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    planted = _post(
        client, "catalog-package",
        action="plant", dirName=dir_name, files=_test_package_files(dir_name),
    )

    assert planted.status_code == 200, planted.get_json()
    manifest = load_package_manifest(catalog / dir_name)
    assert manifest.dir_name == dir_name
    # The library the e2e suite's wheel carries (utils/offline_install.py),
    # which no other test package declares.
    assert manifest.python_deps == {_own_library(dir_name): "1.0.0"}
    assert (catalog / dir_name / "integrity.json").is_file()

    removed = _post(client, "catalog-package", action="remove", dirName=dir_name)

    assert removed.get_json() == {"removed": dir_name, "present": False}


def test_only_a_test_package_is_planted_or_removed(client, catalog):
    shipped = catalog / "curio.builtin@1"
    shipped.mkdir()
    (shipped / "manifest.json").write_text("{}", encoding="utf-8")

    removed = _post(client, "catalog-package", action="remove", dirName="curio.builtin@1")
    planted = _post(
        client, "catalog-package",
        action="plant", dirName="curio.builtin@1", files=_test_package_files(),
    )
    mismatched = _post(
        client, "catalog-package",
        action="plant", dirName="test.another@1", files=_test_package_files(),
    )

    assert [r.status_code for r in (removed, planted, mismatched)] == [400, 400, 400]
    assert (shipped / "manifest.json").read_text(encoding="utf-8") == "{}"
    assert not (catalog / "test.another@1").exists()
