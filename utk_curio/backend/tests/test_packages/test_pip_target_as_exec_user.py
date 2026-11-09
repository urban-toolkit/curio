"""A library installs into a tree the backend owns while pip runs as the execution account.

Where an execution account is configured and the backend is root, pip runs as
that account (``pip_runner._bounded``, #309). The trees it installs into with
``--target`` are the backend's: an account's node libraries
(``backend_runtime.user_node_overlay_dir``), which that account's nodes import
and must not be able to write, and a package's handler overlay, inside the
account's 0700 store. pip moved what it unpacked into its ``--target`` as the
execution account, so on dev every account's install of a library the image
lacks failed with ``Permission denied`` (11-09: SAM 3's transformers, for an
account that added SAM 3 from the Model Catalog).

The unit job runs these as root in the CI image, which carries ``curio-exec``,
so pip really runs as that account there; elsewhere pip runs as the test's own
account, the ordinary local case. pip reads one wheel from a wheelhouse of the
test's own (``PIP_NO_INDEX``, ``PIP_FIND_LINKS``) and reaches no index.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.application import provisioning
from utk_curio.backend.app.packages.infrastructure import backend_runtime, bounded_exec, pip_runner
from utk_curio.backend.tests._support.offline_wheels import WheelLibrary, build_wheel, wheel_file_name

#: Created by the Dockerfile, as the deployments' execution account.
EXEC_USER = "curio-exec"


def _library(name: str) -> WheelLibrary:
    return WheelLibrary(
        dist=f"curio-wheelhouse-{name}",
        version="1.0.0",
        module=f"curio_wheelhouse_{name.replace('-', '_')}",
        message=f"curio-wheelhouse-{name} 1.0.0, installed while pip ran as the execution account",
    )


ACCOUNT_LIB = _library("account-tree")
CLOSED_LIB = _library("closed-tree")
KEPT_LIB = _library("kept-item")


@pytest.fixture
def world_traversable_dir():
    """A folder every account may enter, outside pytest's own 0700 temporary
    tree, as a deployment's ``.curio`` folders are; removed afterwards."""
    made = []

    def _make() -> Path:
        folder = Path(tempfile.mkdtemp(prefix="curio-pip-test-"))
        os.chmod(folder, 0o755)
        made.append(folder)
        return folder

    yield _make
    for folder in made:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def pip_as_the_execution_account(monkeypatch, world_traversable_dir):
    """pip as a deployment runs it: as ``curio-exec`` from root, offline,
    reading wheels from a wheelhouse that account can read. Returns a function
    that puts a library's wheel there."""
    if os.getuid() == 0:
        # Root in the CI image: pip must really drop, or these tests prove nothing.
        import pwd

        account = pwd.getpwnam(EXEC_USER)
        monkeypatch.setenv("CURIO_EXEC_USER", EXEC_USER)
        assert pip_runner._pip_account() == (account.pw_uid, account.pw_gid)
    wheelhouse = world_traversable_dir()
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(wheelhouse))
    monkeypatch.setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")

    def _offer(library: WheelLibrary) -> None:
        wheel = wheelhouse / wheel_file_name(library)
        wheel.write_bytes(build_wheel(library))
        os.chmod(wheel, 0o644)

    return _offer


def _assert_the_backends(placed: list[Path]) -> None:
    """Every path an install placed, and everything under each, is this
    process's, and no group or other account may write it."""
    paths = [path for item in placed for path in (item, *sorted(item.rglob("*")))]
    assert paths, "the install placed nothing"
    for path in paths:
        info = path.lstat()
        assert info.st_uid == os.getuid(), f"{path} belongs to uid {info.st_uid}, not the backend's {os.getuid()}"
        assert not stat.S_IMODE(info.st_mode) & 0o022, f"{path} is writable by others: {oct(info.st_mode)}"


def _the_execution_account_cannot_write(path: Path) -> None:
    """As root: the execution account, the account a node runs as, cannot open *path* to write."""
    import pwd

    account = pwd.getpwnam(EXEC_USER)
    command = bounded_exec.bounded_argv(
        [sys.executable, "-c", f"open({str(path)!r}, 'a')"],
        {"rlimits": [], "drop": [account.pw_uid, account.pw_gid]},
    )
    probe = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert probe.returncode != 0 and "PermissionError" in probe.stderr, (
        f"the execution account could write {path}: exit {probe.returncode}, {probe.stderr[-400:]}"
    )


def test_a_library_lands_in_an_accounts_own_tree_which_its_nodes_cannot_write(
    monkeypatch, pip_as_the_execution_account, world_traversable_dir,
):
    """The path dev failed on: a package's library the image lacks, installed
    into the account's node libraries, which the backend made and owns."""
    launch = world_traversable_dir()
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(launch))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")
    pip_as_the_execution_account(ACCOUNT_LIB)

    failures: dict[str, str] = {}
    installed = provisioning.provision_user_node_deps("42", {ACCOUNT_LIB.dist: ""}, failures)

    overlay = backend_runtime.user_node_overlay_dir("42")
    assert installed == [ACCOUNT_LIB.dist]
    assert failures == {}, f"the account's nodes cannot import it: {failures}"
    module = overlay / f"{ACCOUNT_LIB.module}.py"
    assert module.read_text(encoding="utf-8") == f"MESSAGE = {ACCOUNT_LIB.message!r}\n"
    _assert_the_backends(sorted(overlay.iterdir()))
    if os.getuid() == 0:
        _the_execution_account_cannot_write(module)


def test_a_library_lands_in_a_tree_the_execution_account_cannot_enter(
    monkeypatch, pip_as_the_execution_account, world_traversable_dir,
):
    """A package's handler overlay sits in the account's 0700 store, which
    the execution account cannot even enter. Nothing pip wrote outside it
    is left behind."""
    store = world_traversable_dir() / "store"
    store.mkdir()
    os.chmod(store, 0o700)
    target = store / "overlay"
    target.mkdir()
    # This test's own temporary folder, so another test's install cannot
    # show up in it.
    temporary = world_traversable_dir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    pip_as_the_execution_account(CLOSED_LIB)

    report = pip_runner.install_python_deps_to_target({CLOSED_LIB.dist: ""}, str(target))

    assert report.installed == [CLOSED_LIB.dist]
    assert (target / f"{CLOSED_LIB.module}.py").read_text(encoding="utf-8") == f"MESSAGE = {CLOSED_LIB.message!r}\n"
    _assert_the_backends(sorted(target.iterdir()))
    assert os.listdir(temporary) == [], "what pip installed outside the target was left behind"


def test_an_item_the_tree_already_holds_stays_as_pips_target_leaves_it(
    pip_as_the_execution_account, world_traversable_dir,
):
    """pip's ``--target`` replaces an item the target holds only with
    ``--upgrade``, which Curio never passes: the item stays, the rest lands."""
    target = world_traversable_dir() / "overlay"
    target.mkdir()
    kept = target / f"{KEPT_LIB.module}.py"
    kept.write_text("MESSAGE = 'installed before'\n", encoding="utf-8")
    pip_as_the_execution_account(KEPT_LIB)

    pip_runner.install_python_deps_to_target({KEPT_LIB.dist: ""}, str(target))

    assert kept.read_text(encoding="utf-8") == "MESSAGE = 'installed before'\n"
    dist_info = target / f"{KEPT_LIB.dist.replace('-', '_')}-{KEPT_LIB.version}.dist-info"
    assert (dist_info / "METADATA").is_file(), sorted(os.listdir(target))
    _assert_the_backends([dist_info])
