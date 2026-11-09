"""Pip changes an environment one run at a time, across processes too.

``pip_runner`` ran pip with no lock at all. ``install_python_deps`` decided
what to install from what the interpreter held, then ran pip into it, so two
installs at once (two requests, or two backend processes) ran two pips into
one site-packages, each deciding from what it saw before the other's run.
Under isolation a user's node libraries are a ``--target`` tree of their own,
and the libraries dialog and a package's install both change it: the dialog
under a thread lock, the install under none.

Each process also memoises its import verdicts per library and version, and
dropped them only after its own pip runs: another process's run that adds or
removes what a library needs changes no version of it, so the verdict stayed.

The pip runs here are fakes over files both processes see; the race tests
fork a run that stops inside pip, then run pip from this process
(``_support/two_processes.py``).
"""
from __future__ import annotations

import os
import re
import subprocess
import types
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.infrastructure import pip_runner

# The functions themselves: the package tests' conftest swaps the module's
# install and uninstall for stubs.
from utk_curio.backend.app.packages.infrastructure.pip_runner import (
    install_python_deps,
    uninstall_python_deps,
)


class _Environment:
    """What pip runs into, as files both processes see: a library is
    installed while its file is there. A run that starts while another is in
    its pip is noted in ``met``."""

    def __init__(self, root: Path, window=None) -> None:
        self.site = root / "site-packages"
        self.site.mkdir()
        self.running = root / "pip-running"
        self.running.mkdir()
        self.met = root / "met"
        self.window = window

    def patch(self, monkeypatch) -> None:
        monkeypatch.setattr(pip_runner, "installed_version", self.version)
        monkeypatch.setattr(pip_runner, "subprocess", types.SimpleNamespace(**{**vars(subprocess), "run": self.pip}))
        monkeypatch.setattr(pip_runner, "_bounded", lambda cmd: cmd)

    def version(self, name: str) -> str:
        if (self.site / name).is_file():
            return "1.0"
        raise PackageNotFoundError(name)

    @contextmanager
    def changing(self):
        """One run changing an environment: note the runs already in theirs."""
        others = sorted(entry.name for entry in self.running.iterdir())
        if others:
            with self.met.open("a", encoding="utf-8") as noted:
                noted.write(f"process {os.getpid()} began while process {others} ran pip\n")
        mine = self.running / str(os.getpid())
        mine.touch()
        try:
            if self.window is not None:
                self.window.stop_here()
            yield
        finally:
            mine.unlink()

    def pip(self, cmd, **_kwargs):
        """``pip install`` or ``pip uninstall`` of the names *cmd* gives, into
        this interpreter or the ``--target`` tree it names."""
        verb, args = cmd[3], cmd[4:]
        tree = Path(args[args.index("--target") + 1]) if "--target" in args else self.site
        names, after_target = [], False
        for arg in args:
            if after_target or arg == "--target" or arg.startswith("-"):
                after_target = arg == "--target"
                continue
            names.append(re.split(r"[<>=!~\[;@ ]", arg, maxsplit=1)[0])
        with self.changing():
            for name in names:
                if verb == "install":
                    (tree / name).touch()
                else:
                    (tree / name).unlink(missing_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")


def _a_library_in(tree: Path, name: str) -> None:
    """A ``--target`` install of *name*: its module, and a dist-info whose
    RECORD lists it."""
    info = tree / f"{name}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n", encoding="utf-8")
    (tree / name).touch()
    (info / "RECORD").write_text(f"{name},,\n{info.name}/METADATA,,\n{info.name}/RECORD,,\n", encoding="utf-8")


def test_two_installs_at_once_run_pip_into_the_interpreter_one_at_a_time(tmp_curio, monkeypatch):
    from utk_curio.backend.tests._support.two_processes import Window, race

    window = Window()
    environment = _Environment(tmp_curio, window)
    environment.patch(monkeypatch)

    raced = race(
        window,
        lambda: install_python_deps({"inflection": ""}),
        lambda: install_python_deps({"inflection": ""}),
        monkeypatch,
    )

    assert raced.child_exit == 0, raced.child_error
    assert not environment.met.exists(), f"two pip runs into one interpreter at once: {environment.met.read_text()}"
    assert (raced.here.installed, raced.here.skipped) == ([], ["inflection"]), (
        f"the second install ran pip for what the first had just installed: {raced.here}"
    )


@pytest.mark.parametrize("here", ["install", "uninstall"])
def test_two_runs_into_one_users_libraries_change_them_one_at_a_time(here, tmp_curio, monkeypatch):
    """The dialog's install or removal, while a package's install runs pip
    into the same user's node libraries in another process."""
    from utk_curio.backend.tests._support.two_processes import Window, race

    window = Window()
    environment = _Environment(tmp_curio, window)
    environment.patch(monkeypatch)
    libraries = tmp_curio / "node-libraries" / "users" / "7"
    _a_library_in(libraries, "humanize")
    walk = pip_runner._target_dist_infos

    def _walk_as_a_change(target_dir, name):
        with environment.changing():
            return walk(target_dir, name)

    monkeypatch.setattr(pip_runner, "_target_dist_infos", _walk_as_a_change)

    def _dialog():
        if here == "install":
            return pip_runner.install_python_deps_to_target({"humanize": ""}, str(libraries))
        return pip_runner.uninstall_python_deps_from_target(["humanize"], str(libraries))

    raced = race(
        window,
        lambda: pip_runner.install_python_deps_to_target({"inflection": ""}, str(libraries)),
        _dialog,
        monkeypatch,
    )

    assert raced.child_exit == 0, raced.child_error
    assert not environment.met.exists(), (
        f"two runs changed one user's node libraries at once: {environment.met.read_text()}"
    )
    assert (libraries / "inflection").is_file()


@pytest.mark.parametrize("run", ["install", "uninstall"])
def test_an_import_verdict_is_asked_again_after_another_processes_pip_run(run, tmp_curio, monkeypatch):
    """``x`` imports only while ``y`` is installed. This process asks about
    ``x``; another process's pip run then installs or removes ``y``, which
    changes no version of ``x``. The next answer here is asked anew."""
    from utk_curio.backend.tests._support.two_processes import in_another_process

    environment = _Environment(tmp_curio)
    environment.patch(monkeypatch)
    (environment.site / "x").touch()
    if run == "uninstall":
        (environment.site / "y").touch()

    def _probe(mapping):
        if (environment.site / "y").is_file():
            return {}
        return {name: "ModuleNotFoundError: No module named 'y'" for name in mapping}

    monkeypatch.setattr(pip_runner, "_run_probe", _probe)
    pip_runner.forget_import_probes()

    before = pip_runner.import_failures(["x"])
    error = in_another_process(
        (lambda: install_python_deps({"y": ""})) if run == "install" else (lambda: uninstall_python_deps(["y"]))
    )
    assert not error, error
    after = pip_runner.import_failures(["x"])

    assert bool(before) == (run == "install"), before
    assert bool(after) == (run == "uninstall"), (
        f"after another process's pip run {run}ed y, this process still answered for x as before: {after}"
    )
