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

Without isolation a removal takes back from the interpreter only what Curio's
pip installed there, and each process kept that record of its own pip runs:
a Remove served by another process than the add kept the library.

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


def _a_start_of_two(tmp_curio, monkeypatch) -> None:
    """A start of two backend processes without isolation, this test's being
    process 0, with a state folder of the start's own and nothing yet in this
    process's record of pip's installs."""
    monkeypatch.setenv("CURIO_ISOLATION", "off")
    monkeypatch.setenv("CURIO_BACKEND_PROCESSES", "2")
    monkeypatch.delenv("CURIO_BACKEND_PROCESS", raising=False)
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_curio / "state"))
    monkeypatch.setattr(pip_runner, "_installed_here", set())


def test_without_isolation_a_remove_in_one_backend_process_takes_back_what_an_add_in_another_installed(
    tmp_curio, monkeypatch,
):
    """Without isolation a removal takes a library out of the one interpreter
    only when Curio's pip installed it there (``installed_here``), which each
    backend process noted for itself. In a start of several, the Installed
    libraries dialog's add, served by one process, and its Remove, served by
    another, left the library installed."""
    from utk_curio.backend.app.packages.application import libraries
    from utk_curio.backend.tests._support.two_processes import in_another_process

    library = "curio-added-in-process-one"
    _a_start_of_two(tmp_curio, monkeypatch)
    environment = _Environment(tmp_curio)
    environment.patch(monkeypatch)
    # The real installer and uninstaller, under the package tests' stubs.
    monkeypatch.setattr(pip_runner, "install_python_deps", install_python_deps)
    monkeypatch.setattr(pip_runner, "uninstall_python_deps", uninstall_python_deps)
    monkeypatch.setattr(pip_runner, "import_failures", lambda deps: {})

    def _the_add_in_process_one():
        os.environ["CURIO_BACKEND_PROCESS"] = "1"
        libraries.add_standalone_library("7", "python", library)

    error = in_another_process(_the_add_in_process_one)
    assert not error, error
    assert (environment.site / library).is_file(), "the add in process 1 installed nothing"

    libraries.remove_standalone_library("7", "python", library)

    assert not (environment.site / library).exists(), (
        f"process 1's pip installed {library} for the dialog's add, and nothing else asks for it, "
        "yet its Remove, served by process 0, left it in the interpreter"
    )


def test_with_one_backend_process_the_record_of_pips_installs_keeps_no_file(tmp_curio, monkeypatch):
    """With one backend process the record is held in its memory, as before,
    and so it is in the launcher, whose environment names no backend process:
    the libraries a start installs before its backends run, the shipped
    catalog's, never enter the record a start of several keeps."""
    from utk_curio.backend.app.common import shared_budgets, user_storage

    library = "curio-added-in-the-one-process"
    monkeypatch.delenv("CURIO_BACKEND_PROCESSES", raising=False)
    monkeypatch.delenv("CURIO_BACKEND_PROCESS", raising=False)
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_curio / "state"))
    monkeypatch.setattr(pip_runner, "_installed_here", set())
    environment = _Environment(tmp_curio)
    environment.patch(monkeypatch)

    install_python_deps({library: ""})

    assert pip_runner.installed_here([library]) == [library]
    folder = user_storage.curio_root() / shared_budgets.FOLDER
    assert not folder.exists(), sorted(str(path) for path in folder.rglob("*"))
