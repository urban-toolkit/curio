"""A backend package's overlay and its pin change one writer at a time.

A backend package's handlers import their libraries from the package's own
overlay, a ``pip --target`` tree that ``backend_runtime.build_overlay`` wipes
and builds again at each install, repair and Apply, and that
``remove_backend_residue`` removes with the package. Each pip run into a tree
holds that tree's lock, across threads and backend processes (``pip_runner``),
but the wipe, the checks after the run and the removal held nothing. So a build
or a removal of an overlay could wipe it while another process's pip run was
writing it: that run reported its libraries installed into a tree that had
lost some of them.

Each install also pins the package's handler entry in the account's one pins
file (``record_entry_pin``), a read-modify-write with no lock at all, so two
installs at once could each write what they had read with their own pin, and
the later one dropped the other's.

The pip runs here are fakes that write each library as a file. Each test forks
a writer that stops inside its change, then makes the same change from this
process (``_support/two_processes.py``).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import types
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.infrastructure import backend_runtime as rt
from utk_curio.backend.app.packages.infrastructure import pip_runner

USER = "42"
PKG = "curio.counter@1"
LIBRARIES = {"humanize": "", "inflection": ""}


class _Pip:
    """``pip install --target`` as files both processes see: each library one
    file, written in turn. In the forked child a run stops at the window after
    its first library. At its end a run notes in ``lost`` each library it wrote
    that is gone: its tree was wiped while it ran."""

    def __init__(self, root: Path, window) -> None:
        self.lost = root / "lost"
        self.window = window

    def patch(self, monkeypatch) -> None:
        monkeypatch.setattr(pip_runner, "subprocess", types.SimpleNamespace(**{**vars(subprocess), "run": self.run}))
        monkeypatch.setattr(pip_runner, "_bounded", lambda cmd: cmd)

    def run(self, cmd, **_kwargs):
        args = cmd[4:]
        after = args.index("--target") + 1
        tree = Path(args[after])
        names = [re.split(r"[<>=!~\[;@ ]", arg, maxsplit=1)[0] for arg in args[after + 1:] if not arg.startswith("-")]
        for name in names:
            tree.mkdir(parents=True, exist_ok=True)  # as pip makes its --target
            (tree / name).touch()
            if name == names[0]:
                self.window.stop_here()
        gone = [name for name in names if not (tree / name).is_file()]
        if gone:
            with self.lost.open("a", encoding="utf-8") as noted:
                noted.write(f"process {os.getpid()}'s pip run into {tree.name} lost {gone}\n")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")


@pytest.mark.parametrize("here", ["build", "remove"])
def test_an_overlay_is_not_wiped_while_another_processes_pip_run_writes_it(here, tmp_curio, monkeypatch):
    """The other process builds a package's overlay (an install, a repair or
    an Apply) and stops in its pip run, after its first library. This process
    builds the same overlay again, or removes it with the package."""
    from utk_curio.backend.tests._support.two_processes import Window, race

    window = Window()
    pip = _Pip(tmp_curio, window)
    pip.patch(monkeypatch)
    overlay = rt.overlay_dir_for(USER, PKG)

    def _here():
        if here == "build":
            return rt.build_overlay(USER, PKG, LIBRARIES)
        return rt.remove_backend_residue(USER, PKG)

    raced = race(window, lambda: rt.build_overlay(USER, PKG, LIBRARIES), _here, monkeypatch)

    assert raced.child_exit == 0, raced.child_error
    assert not pip.lost.exists(), (
        f"the overlay was wiped while another process's pip run wrote it: {pip.lost.read_text(encoding='utf-8')}"
    )
    if here == "build":
        assert sorted(entry.name for entry in overlay.iterdir()) == sorted(LIBRARIES)
    else:
        assert not overlay.exists(), "the package's removal, which came last, left its overlay behind"


def _a_backend_package(dir_name: str) -> None:
    """A package with a handler in the account's store, as an install leaves it."""
    from utk_curio.backend.app.packages.domain import backend_contract as bc
    from utk_curio.backend.app.packages.repositories.store import package_dir

    package_id = dir_name.rsplit("@", 1)[0]
    folder = package_dir(USER, dir_name)
    (folder / "backend").mkdir(parents=True)
    manifest = {
        "id": package_id, "version": "1.0.0", "name": package_id,
        "publisher": "t", "description": "d", "compatibility": {"major": 1},
        "permissions": [bc.PERMISSION_SERVER_CODE],
        "templates": [{
            "id": "counter", "label": "Counter", "category": "computation",
            "engine": "python", "editor": "none", "hasCode": False,
            "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "backendHandler": "word-count",
        }],
        "backend": {"entry": "backend/handler.py", "handlers": [{"name": "word-count", "timeoutClass": "quick"}]},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "backend" / "handler.py").write_text(f"HANDLERS = {{}}  # {dir_name}\n", encoding="utf-8")


def test_two_packages_pinned_at_once_keep_both_pins(tmp_curio, monkeypatch):
    """Two installs of backend packages at once, the other one in another
    process, stopped after it read the pins file. Each pin is the check every
    run of that package's handlers makes of its entry."""
    from utk_curio.backend.tests._support.two_processes import Window, race

    packages = ("curio.alpha@1", "curio.beta@1")
    for dir_name in packages:
        _a_backend_package(dir_name)
    window = Window()
    digest = rt.entry_digest

    def _digest_after_the_read(data: bytes) -> str:
        window.stop_here()
        return digest(data)

    monkeypatch.setattr(rt, "entry_digest", _digest_after_the_read)

    raced = race(
        window,
        lambda: rt.record_entry_pin(USER, packages[0]),
        lambda: rt.record_entry_pin(USER, packages[1]),
        monkeypatch,
    )

    assert raced.child_exit == 0, raced.child_error
    unpinned = [dir_name for dir_name in packages if rt.pinned_entry_digest(USER, dir_name) is None]
    assert not unpinned, f"two packages were pinned at once, and the pins file lost {unpinned}"
