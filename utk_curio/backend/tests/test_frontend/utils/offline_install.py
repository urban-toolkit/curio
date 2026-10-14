"""A test package whose library installs offline, for the e2e tests of the install paths.

A package declares its libraries, and Curio installs them when the package is
added, when a dataflow whose lockfile names it is opened, or at launch. These
helpers let a test run those installs with the real pip and no network:

* the library is a wheel of a few hundred bytes, built in memory
  (``tests/_support/offline_wheels.py``);
* ``/api/testing/wheelhouse`` stages it in the backend, whose pip then reads
  that wheelhouse and no index (``PIP_NO_INDEX`` with ``PIP_FIND_LINKS``);
* ``/api/testing/catalog-package`` puts a test package from
  ``test_frontend/packages/`` in the backend's shared catalog, so it is added
  the way any catalog package is.

``offline_catalog_package`` does all three and undoes them.

Each test of an install path has a test package and a library of its own
(``offline_package``), so each proves its own install from scratch, even after
an earlier test on the same backend imported another test library.
"""

from __future__ import annotations

import base64
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from utk_curio.backend.tests._support.offline_wheels import WheelLibrary, build_wheel, wheel_file_name

from .db_stubs import api_json

#: Test packages: never in the shipped catalog, planted for one test at a time.
TEST_PACKAGES_DIR = Path(__file__).resolve().parents[1] / "packages"


def wheelhouse_library(dist: str, version: str) -> WheelLibrary:
    """The test library *dist*, a ``curio-wheelhouse-*`` name: its module is the
    name with underscores, and holds a message that names the library."""
    return WheelLibrary(
        dist=dist,
        version=version,
        module=dist.replace("-", "_"),
        message=f"{dist} {version} imported from the test wheelhouse",
    )


@dataclass(frozen=True)
class OfflineNode:
    """One node of a test package."""

    #: ``<package id>/<template id>``, which a canvas node's type starts with.
    type: str
    label: str
    #: Its code, from the package's sources.
    code: str


@dataclass(frozen=True)
class OfflinePackage:
    """A test package from ``packages/``, as its manifest declares it."""

    dir_name: str
    name: str
    #: The one library it declares, which exists only as a test wheel.
    library: WheelLibrary
    #: Its nodes, in the manifest's order.
    nodes: tuple[OfflineNode, ...]


def offline_package(dir_name: str) -> OfflinePackage:
    """The test package ``packages/<dir_name>``, read from its manifest."""
    root = TEST_PACKAGES_DIR / dir_name
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    [(dist, version)] = manifest["dependencies"]["python"].items()
    return OfflinePackage(
        dir_name=dir_name,
        name=manifest["name"],
        library=wheelhouse_library(dist, version),
        nodes=tuple(
            OfflineNode(
                type=f"{manifest['id']}/{template['id']}",
                label=template["label"],
                code=(root / template["source"]).read_text(encoding="utf-8"),
            )
            for template in manifest["templates"]
        ),
    )


def _testing_post(backend_url: str, route: str, payload: dict) -> dict:
    # The testing blueprint takes no auth; api_json always sends a token.
    return api_json(
        f"{backend_url}/api/testing/{route}", "unused",
        method="POST", payload=payload, timeout=180.0,
    )


def stage_wheelhouse(backend_url: str, libraries: Iterable[WheelLibrary]) -> dict[str, bool]:
    """Stage each library's wheel in the backend; answer whether each is installed.

    The stage uninstalls any copy an earlier run left, so every answer is
    False unless something is wrong.
    """
    wheels = [
        {"filename": wheel_file_name(library),
         "content": base64.b64encode(build_wheel(library)).decode("ascii")}
        for library in libraries
    ]
    return _testing_post(backend_url, "wheelhouse", {"action": "stage", "wheels": wheels})["installed"]


def library_installed(backend_url: str, library: WheelLibrary) -> bool:
    """Whether the backend's pip metadata holds *library*: pip installed it."""
    answer = _testing_post(backend_url, "wheelhouse", {"action": "status", "names": [library.dist]})
    return bool(answer["installed"][library.dist])


def restore_wheelhouse(backend_url: str) -> dict:
    """Put the backend's pip settings back and uninstall the staged libraries."""
    return _testing_post(backend_url, "wheelhouse", {"action": "restore"})


def plant_catalog_package(backend_url: str, dir_name: str) -> None:
    """Put the test package ``test_frontend/packages/<dir_name>`` in the shared catalog."""
    root = TEST_PACKAGES_DIR / dir_name
    files = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    _testing_post(backend_url, "catalog-package", {"action": "plant", "dirName": dir_name, "files": files})


def remove_catalog_package(backend_url: str, dir_name: str) -> None:
    _testing_post(backend_url, "catalog-package", {"action": "remove", "dirName": dir_name})


@contextmanager
def offline_catalog_package(
    backend_url: str, dir_name: str, libraries: Iterable[WheelLibrary],
) -> Iterator[None]:
    """*dir_name* in the shared catalog, its libraries only in the wheelhouse.

    Undone afterwards whatever happened, each step on its own: a test package
    left in the catalog moves the Node Catalog's frames and counts for the
    tests that follow on this backend, and pip settings left pointing at the
    wheelhouse make every later install offline.
    """
    libraries = list(libraries)
    try:
        installed = stage_wheelhouse(backend_url, libraries)
        assert not any(installed.values()), (
            f"the staged libraries are still installed after the stage removed them: {installed}"
        )
        plant_catalog_package(backend_url, dir_name)
        yield
    finally:
        failures = []
        for undo in (
            lambda: remove_catalog_package(backend_url, dir_name),
            lambda: restore_wheelhouse(backend_url),
        ):
            try:
                undo()
            except Exception as exc:  # noqa: BLE001 - each undo runs whatever the other did
                failures.append(exc)
        if failures:
            raise failures[0]
