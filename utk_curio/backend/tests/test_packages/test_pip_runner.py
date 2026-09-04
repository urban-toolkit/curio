"""Tests for the per-package pip_runner.

The runner shells out to ``pip``; tests stub the subprocess to keep them
fast (and to not actually mutate the test env). What we care about:

- Idempotency: deps that are already installed get skipped.
- Spec formatting: ``>=2.0`` stays as-is, bare ``1.2.3`` becomes ``==1.2.3``.
- Failure surfaces a useful error (tail of pip's stderr).
- Uninstall propagates names correctly.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from unittest.mock import patch

import pytest

from utk_curio.backend.app.packages import pip_runner

from utk_curio.backend.app.packages.pip_runner import (
    PipInstallError,
    _spec_argv,
    install_python_deps,
    uninstall_python_deps,
)


def _fake_proc(returncode: int = 0, stdout: str = "", stderr: str = ""):
    p = subprocess.CompletedProcess(args=[], returncode=returncode)
    p.stdout = stdout
    p.stderr = stderr
    return p


def test_spec_argv_keeps_comparators_intact():
    assert _spec_argv("torch", ">=2.0") == "torch>=2.0"
    assert _spec_argv("foo", "~=1.4") == "foo~=1.4"
    assert _spec_argv("bar", "==3.0.0") == "bar==3.0.0"


def test_spec_argv_bare_version_becomes_exact_match():
    assert _spec_argv("torch", "2.0") == "torch==2.0"


def test_spec_argv_empty_spec_is_bare_name():
    assert _spec_argv("ultralytics", "") == "ultralytics"
    assert _spec_argv("ultralytics", "   ") == "ultralytics"
    # `_format_range` round-trips an unbounded range to "*", so the
    # resolver hands `*` to `_spec_argv` whenever a manifest leaves a
    # version field empty. Treat it the same as the empty spec — pip
    # rejects bare "numpy==*" as invalid syntax.
    assert _spec_argv("numpy", "*") == "numpy"


def test_install_empty_deps_is_noop():
    report = install_python_deps({})
    assert report.installed == [] and report.skipped == []


def test_install_skips_already_satisfied():
    """A package the runner can resolve via ``importlib.metadata`` is
    skipped — pip is never invoked."""
    with patch("utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=True), \
         patch("subprocess.run") as run:
        report = install_python_deps({"torch": ">=2.0", "transformers": ">=4.30"})
    run.assert_not_called()
    assert sorted(report.skipped) == ["torch", "transformers"]
    assert report.installed == []


def test_install_invokes_pip_for_missing_deps():
    with patch("utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False), \
         patch("subprocess.run", return_value=_fake_proc(0, "ok", "")) as run:
        report = install_python_deps({"torch": ">=2.0"})
    assert run.call_count == 1
    argv = run.call_args[0][0]
    # The argv ends in the pip-formatted spec; preceding entries are the
    # interpreter, ``-m pip install --no-input``.
    assert argv[-1] == "torch>=2.0"
    assert "install" in argv and "--no-input" in argv
    assert report.installed == ["torch>=2.0"] and report.skipped == []


def test_install_raises_with_pip_stderr_tail_on_failure():
    big_stderr = "x" * 5000 + "FATAL ERROR HERE"
    with patch("utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False), \
         patch("subprocess.run", return_value=_fake_proc(1, "", big_stderr)):
        with pytest.raises(PipInstallError) as exc_info:
            install_python_deps({"torch": ">=2.0"})
    # We surface the *tail* (last 2000 chars) — long enough to include the
    # error, short enough to fit in a JSON response.
    msg = str(exc_info.value)
    assert "FATAL ERROR HERE" in msg
    assert "exit 1" in msg


def test_uninstall_empty_list_is_noop():
    report = uninstall_python_deps([])
    assert report.removed == [] and report.kept == []


def test_uninstall_invokes_pip_with_names():
    with patch("subprocess.run", return_value=_fake_proc(0, "ok", "")) as run:
        report = uninstall_python_deps(["torch", "transformers"])
    argv = run.call_args[0][0]
    assert "uninstall" in argv and "-y" in argv
    assert "torch" in argv and "transformers" in argv
    assert report.removed == ["torch", "transformers"]


# ---------------------------------------------------------------------------
# The streaming (on_line) path
# ---------------------------------------------------------------------------
#
# install_python_deps has two implementations picked by whether on_line is
# given. Only the buffered one was covered, yet the streaming one is what the
# launcher uses (main.py install_manifest_dependencies) - so a break there
# surfaces as a broken `curio start`, not a failing API call.


class _FakeProc:
    """Minimal Popen stand-in: iterable stdout plus a fixed exit code."""

    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self._rc = returncode

    def wait(self, timeout=None):
        # Mirrors ``Popen.wait``: the streaming branch bounds pip with
        # ``timeout=_PIP_TIMEOUT_SECONDS`` rather than waiting forever.
        return self._rc

    def kill(self):  # pragma: no cover - only on the timeout path
        pass


def test_streaming_path_reports_each_line_and_returns_installed():
    seen: list[str] = []
    with patch(
        "utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False
    ), patch(
        "utk_curio.backend.app.packages.pip_runner.subprocess.Popen",
        return_value=_FakeProc(["Collecting inflection", "Successfully installed"]),
    ) as popen:
        report = install_python_deps({"inflection": ""}, on_line=seen.append)

    assert seen == ["Collecting inflection", "Successfully installed"]
    assert report.installed == ["inflection"]
    assert report.skipped == []
    # Popen itself takes no timeout; the deadline is applied at `proc.wait()`,
    # which is what bounds the branch. It previously called a bare `wait()` and
    # a wedged mirror hung the caller forever.
    assert "timeout" not in popen.call_args.kwargs


def test_streaming_path_raises_with_the_output_tail():
    with patch(
        "utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False
    ), patch(
        "utk_curio.backend.app.packages.pip_runner.subprocess.Popen",
        return_value=_FakeProc(["ERROR: could not build wheel"], returncode=1),
    ):
        with pytest.raises(PipInstallError) as exc:
            install_python_deps({"inflection": ""}, on_line=lambda _l: None)

    assert "exit 1" in str(exc.value)
    assert "could not build wheel" in str(exc.value)


def test_streaming_path_keeps_only_the_last_40_lines():
    """The tail is capped, so a chatty failure stays a readable error."""
    lines = [f"line-{i}" for i in range(200)]
    with patch(
        "utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=False
    ), patch(
        "utk_curio.backend.app.packages.pip_runner.subprocess.Popen",
        return_value=_FakeProc(lines, returncode=2),
    ):
        with pytest.raises(PipInstallError) as exc:
            install_python_deps({"inflection": ""}, on_line=lambda _l: None)

    message = str(exc.value)
    assert "line-199" in message
    assert "line-160" in message      # 200 - 40 = the oldest line still kept
    assert "line-159" not in message  # ...and the one before it is dropped


def test_streaming_path_skips_pip_entirely_when_satisfied():
    """The satisfied short-circuit precedes the branch, so on_line is never called."""
    seen: list[str] = []
    with patch(
        "utk_curio.backend.app.packages.pip_runner._is_satisfied", return_value=True
    ), patch(
        "utk_curio.backend.app.packages.pip_runner.subprocess.Popen"
    ) as popen:
        report = install_python_deps({"inflection": ""}, on_line=seen.append)

    popen.assert_not_called()
    assert seen == []
    assert report.installed == []
    assert report.skipped == ["inflection"]



def test_streaming_path_kills_pip_when_it_overruns(monkeypatch):
    """The streaming branch is bounded, like the buffered one.

    It used to call a bare ``proc.wait()``. A mirror that accepts the
    connection and then never sends EOF pinned the calling thread forever, and
    this branch is reachable over HTTP: ``build_overlay`` streams, and it sits
    on the promotion and catalog-install paths.
    """
    import subprocess

    from utk_curio.backend.app.packages import pip_runner

    killed = {"count": 0}

    class _HangingProc:
        def __init__(self):
            self.stdout = iter(["Collecting slowpkg"])

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired(cmd="pip", timeout=timeout)
            return 0

        def kill(self):
            killed["count"] += 1

    monkeypatch.setattr(pip_runner, "_is_satisfied", lambda name, spec: False)
    monkeypatch.setattr(pip_runner.subprocess, "Popen", lambda *a, **k: _HangingProc())

    # The module-level import, not ``pip_runner.install_python_deps``: the
    # package conftest's autouse fixture replaces that attribute with a stub
    # that takes no ``on_line``. The other streaming tests bind it the same way.
    with pytest.raises(PipInstallError, match="timed out"):
        install_python_deps({"slowpkg": ""}, on_line=lambda line: None)

    assert killed["count"] == 1, "a pip that overruns must be killed, not leaked"


# ---------------------------------------------------------------------------
# Import probing — metadata presence is not importability
# ---------------------------------------------------------------------------

class TestModuleForDistribution:
    """A distribution's name is not the module you import it as."""

    def test_resolves_a_dist_whose_module_name_differs(self):
        # The canonical example, and the reason a naive `import <dist>` probe
        # would report every such library as broken.
        if importlib.util.find_spec("PIL") is None:
            pytest.skip("pillow not installed in this environment")
        assert pip_runner._module_for_distribution("pillow") == "PIL"

    def test_resolves_a_dist_whose_module_name_matches(self):
        assert pip_runner._module_for_distribution("flask") == "flask"

    def test_falls_back_to_normalised_name_for_an_unknown_dist(self):
        # Not installed → no mapping to consult. The probe that follows will
        # fail anyway; it just has to fail for the right reason.
        assert (
            pip_runner._module_for_distribution("zzz-not-a-real-dist")
            == "zzz_not_a_real_dist"
        )

    def test_prefers_the_library_module_over_a_shipped_tests_package(self, monkeypatch):
        # pythermalcomfort really does map to ['pythermalcomfort', 'tests'];
        # probing `tests` could succeed while the library itself is broken.
        # Patched on importlib.metadata, not on pip_runner: the resolver imports
        # `packages_distributions` inside the function, so that is the binding
        # it actually reads.
        import importlib.metadata as md

        monkeypatch.setattr(
            md, "packages_distributions",
            lambda: {"tests": ["somedist"], "somedist": ["somedist"]},
        )
        assert pip_runner._module_for_distribution("somedist") == "somedist"

    def test_ignores_a_tests_only_mapping_rather_than_probing_it(self, monkeypatch):
        import importlib.metadata as md

        monkeypatch.setattr(
            md, "packages_distributions", lambda: {"tests": ["odd"], "docs": ["odd"]},
        )
        # Both candidates are non-library; falling back to one of them is fine,
        # but it must not crash and must be deterministic.
        assert pip_runner._module_for_distribution("odd") in {"docs", "tests"}


class TestImportFailure:
    def test_returns_none_for_a_library_that_imports(self):
        pip_runner.forget_import_probes()
        assert pip_runner.import_failure("flask") is None

    def test_reports_a_distribution_that_is_not_installed(self):
        pip_runner.forget_import_probes()
        reason = pip_runner.import_failure("zzz-not-a-real-dist")
        assert reason and "not installed" in reason

    def test_reports_the_import_error_for_a_present_but_broken_dist(self, monkeypatch):
        """The case a version check cannot see (#232 follow-up).

        Simulated by pointing a real, installed distribution at a module that
        does not exist: metadata resolves, the import does not — exactly the
        shape of a wheel whose native extension fails to load.
        """
        pip_runner.forget_import_probes()
        monkeypatch.setattr(
            pip_runner, "_module_for_distribution", lambda name: "zzz_no_such_module"
        )
        reason = pip_runner.import_failure("flask")
        assert reason is not None
        assert "ModuleNotFoundError" in reason or "No module named" in reason

    def test_is_satisfied_still_says_yes_for_that_same_dist(self, monkeypatch):
        """Pins the gap itself, so nobody 'simplifies' the probe away.

        `_is_satisfied` reads metadata and evaluates the version specifier; it
        is *correct* and it is *not enough*. If this ever starts failing, the
        two checks have been merged and the split below is redundant.
        """
        assert pip_runner.is_satisfied("flask", "") is True

    def test_memoises_so_a_page_load_does_not_respawn_probes(self, monkeypatch):
        pip_runner.forget_import_probes()
        calls: list[list[str]] = []
        real_run = pip_runner.subprocess.run

        def _counting_run(cmd, **kw):
            calls.append(cmd)
            return real_run(cmd, **kw)

        monkeypatch.setattr(pip_runner.subprocess, "run", _counting_run)
        pip_runner.import_failure("flask")
        pip_runner.import_failure("flask")
        assert len(calls) == 1, "the second probe should have come from the memo"

    def test_forget_import_probes_reopens_the_question(self, monkeypatch):
        # A repair can land without the version changing (`--force-reinstall`),
        # which the (name, version) key would otherwise hide forever.
        pip_runner.forget_import_probes()
        pip_runner.import_failure("flask")
        assert pip_runner._import_probe_cache
        pip_runner.forget_import_probes()
        assert not pip_runner._import_probe_cache

    def test_a_probe_that_cannot_run_reports_nothing_rather_than_guessing(
        self, monkeypatch
    ):
        """Best-effort: an unusable probe must not invent a broken dependency."""
        pip_runner.forget_import_probes()

        def _boom(*a, **kw):
            raise OSError("no subprocesses here")

        monkeypatch.setattr(pip_runner.subprocess, "run", _boom)
        assert pip_runner.import_failure("flask") is None


BROKEN_DIST = "brokenlib"
BROKEN_VERSION = "9.9.9"
BROKEN_REASON = (
    "DLL load failed while importing _base: The specified procedure could not be found."
)


def _fake_broken_distribution(root):
    """A distribution pip is satisfied by and python cannot import.

    Byte-for-byte the shape of the real case (a rasterio built against a
    different GDAL): valid metadata, so ``installed_version`` answers and
    ``_is_satisfied`` says yes, over a module that raises the moment it is
    imported. Deterministic and offline, unlike installing a genuinely broken
    wheel.
    """
    info = root / f"{BROKEN_DIST}-{BROKEN_VERSION}.dist-info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {BROKEN_DIST}\nVersion: {BROKEN_VERSION}\n",
        encoding="utf-8",
    )
    (info / "top_level.txt").write_text(f"{BROKEN_DIST}\n", encoding="utf-8")
    (root / f"{BROKEN_DIST}.py").write_text(
        f'raise ImportError("{BROKEN_REASON}")\n', encoding="utf-8",
    )
    return root


class TestDistributionNameNormalisation:
    """A requirement names a distribution the way pip accepts it; the mapping
    keys it the way the metadata spells it. Matching those by equality invented
    failures on the one surface whose job is naming real ones."""

    def test_a_casing_mismatch_does_not_invent_a_broken_library(self):
        # PyYAML is a base-install dependency and imports fine. A manifest
        # (or the factory's source scanner) writes it lowercase, which is what
        # pip accepts; packages_distributions() keys it "PyYAML".
        pip_runner.forget_import_probes()
        assert pip_runner._module_for_distribution("pyyaml") == "yaml"
        assert pip_runner.import_failures(["pyyaml"]) == {}

    def test_the_spelling_in_the_metadata_resolves_the_same_way(self):
        pip_runner.forget_import_probes()
        assert pip_runner._module_for_distribution("PyYAML") == "yaml"
        assert pip_runner.import_failures(["PyYAML"]) == {}

    def test_separators_are_normalised_the_pep_503_way(self):
        assert pip_runner._canonical_dist_name("py-yaml") == "py-yaml"
        assert pip_runner._canonical_dist_name("py_yaml") == "py-yaml"
        assert pip_runner._canonical_dist_name("Py.Yaml") == "py-yaml"

    def test_a_private_accelerator_is_not_the_module_the_requirement_means(self):
        # PyYAML ships both `yaml` and `_yaml`; sorting alone picks the
        # underscore, which is an implementation detail, not the library.
        assert not pip_runner._module_for_distribution("pyyaml").startswith("_")

    def test_the_known_renames_still_resolve(self):
        assert pip_runner._module_for_distribution("pillow") == "PIL"


class TestImportFailuresIn:
    """The overlay probe. ``install_python_deps_to_target`` writes to a
    directory the backend process never imports from — workers get it on
    PYTHONPATH — so the only interpreter that can answer for it is one
    configured the way a worker is."""

    def test_reports_a_library_the_host_interpreter_cannot_even_see(self, tmp_path):
        overlay = _fake_broken_distribution(tmp_path / "overlay")
        # The premise: the parent cannot answer this question at all.
        with pytest.raises(pip_runner.PackageNotFoundError):
            pip_runner.installed_version(BROKEN_DIST)

        out = pip_runner.import_failures_in([BROKEN_DIST], str(overlay))

        assert list(out) == [BROKEN_DIST]
        assert BROKEN_REASON in out[BROKEN_DIST]

    def test_a_working_overlay_library_is_silent(self, tmp_path):
        overlay = tmp_path / "overlay"
        (overlay / "worklib-1.0.dist-info").mkdir(parents=True)
        (overlay / "worklib-1.0.dist-info" / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: worklib\nVersion: 1.0\n", encoding="utf-8",
        )
        (overlay / "worklib-1.0.dist-info" / "top_level.txt").write_text(
            "worklib\n", encoding="utf-8",
        )
        (overlay / "worklib.py").write_text("VALUE = 1\n", encoding="utf-8")

        assert pip_runner.import_failures_in(["worklib"], str(overlay)) == {}

    def test_a_dep_missing_from_the_overlay_is_reported_as_not_installed(self, tmp_path):
        overlay = tmp_path / "overlay"
        overlay.mkdir()
        out = pip_runner.import_failures_in(["zzz-not-a-real-dist"], str(overlay))
        assert "not installed" in out["zzz-not-a-real-dist"]

    def test_no_deps_and_no_path_cost_nothing(self, tmp_path, monkeypatch):
        def _boom(*a, **kw):  # pragma: no cover
            raise AssertionError("spawned a probe with nothing to probe")

        monkeypatch.setattr(pip_runner.subprocess, "run", _boom)
        assert pip_runner.import_failures_in([], str(tmp_path)) == {}
        assert pip_runner.import_failures_in(["flask"], "") == {}

    def test_a_probe_that_cannot_run_reports_nothing_rather_than_guessing(
        self, tmp_path, monkeypatch,
    ):
        """"No answer" is never "all fine" — and never a fabricated failure."""
        overlay = _fake_broken_distribution(tmp_path / "overlay")

        def _boom(*a, **kw):
            raise OSError("no subprocesses here")

        monkeypatch.setattr(pip_runner.subprocess, "run", _boom)
        assert pip_runner.import_failures_in([BROKEN_DIST], str(overlay)) == {}

    def test_one_crashing_import_does_not_silence_the_rest(self, tmp_path, monkeypatch):
        """A module that aborts its interpreter takes the batch's stdout with it.

        Without a retry that turns every OTHER dep's verdict into silence, which
        the caller reads as "all fine" - the exact clean bill of health this
        whole seam exists to stop something claiming.
        """
        seen: list[list[str]] = []

        def _fake(names, search_path):
            seen.append(list(names))
            if len(names) > 1:
                return None                       # the batch "crashed"
            name = names[0]
            return {name: "ImportError: boom"} if name == "brokenlib" else {}

        monkeypatch.setattr(pip_runner, "_run_target_probe", _fake)
        out = pip_runner.import_failures_in(["brokenlib", "goodlib"], str(tmp_path))

        assert out == {"brokenlib": "ImportError: boom"}
        assert len(seen) == 3, "one batch attempt, then one probe per dep"

    def test_a_batch_that_answers_is_not_re_probed(self, tmp_path, monkeypatch):
        calls: list[list[str]] = []
        monkeypatch.setattr(
            pip_runner, "_run_target_probe",
            lambda names, path: calls.append(list(names)) or {},
        )
        assert pip_runner.import_failures_in(["a", "b"], str(tmp_path)) == {}
        assert calls == [["a", "b"]]

    def test_it_probes_the_interpreter_the_worker_will_use(self, tmp_path, monkeypatch):
        """An overlay exists to be imported by a backend handler.

        Handlers run under ``backend_runtime.sandbox_interpreter()``, which an
        operator can pin away from the server's own interpreter with
        CURIO_BACKEND_SANDBOX_PYTHON. Probing sys.executable would answer for an
        interpreter that never imports the overlay - a verdict about the wrong
        environment, in the one place the environment is the whole question.
        """
        from utk_curio.backend.app.packages import backend_runtime

        monkeypatch.setenv("CURIO_BACKEND_SANDBOX_PYTHON", r"C:\pinned\python.exe")
        seen = {}

        def _spy(cmd, **kw):
            seen["argv0"] = cmd[0]
            raise OSError("stop here; the argv is the assertion")

        monkeypatch.setattr(pip_runner.subprocess, "run", _spy)
        pip_runner.import_failures_in(["flask"], str(tmp_path))

        assert seen["argv0"] == backend_runtime.sandbox_interpreter()
        assert seen["argv0"] != pip_runner.sys.executable

    def test_it_is_the_host_interpreter_when_nothing_is_pinned(self, tmp_path, monkeypatch):
        """The default configuration must not move."""
        monkeypatch.delenv("CURIO_BACKEND_SANDBOX_PYTHON", raising=False)
        seen = {}

        def _spy(cmd, **kw):
            seen["argv0"] = cmd[0]
            raise OSError("stop")

        monkeypatch.setattr(pip_runner.subprocess, "run", _spy)
        pip_runner.import_failures_in(["flask"], str(tmp_path))
        assert seen["argv0"] == pip_runner.sys.executable

    def test_the_hosts_own_pythonpath_survives(self, tmp_path, monkeypatch):
        """The overlay is prepended, not substituted.

        A worker sees the overlay ON TOP of the environment it already had;
        replacing PYTHONPATH would make the probe answer for an environment no
        worker runs in.
        """
        monkeypatch.setenv("PYTHONPATH", str(tmp_path / "pre-existing"))
        seen = {}

        def _spy(cmd, **kw):
            seen["path"] = kw["env"]["PYTHONPATH"]
            raise OSError("stop here; the argv is the assertion")

        monkeypatch.setattr(pip_runner.subprocess, "run", _spy)
        pip_runner.import_failures_in(["flask"], str(tmp_path / "overlay"))

        assert seen["path"].split(os.pathsep)[0] == str(tmp_path / "overlay")
        assert str(tmp_path / "pre-existing") in seen["path"]


class TestImportFailures:
    def test_maps_only_the_broken_ones(self, monkeypatch):
        # Patched at `_run_probe`, the subprocess seam. `import_failure` is now a
        # wrapper OVER `import_failures`, so patching it would test nothing.
        pip_runner.forget_import_probes()
        monkeypatch.setattr(
            pip_runner, "_run_probe", lambda mapping: {"flask": "boom"},
        )
        assert pip_runner.import_failures(["flask"]) == {"flask": "boom"}

    def test_probes_every_dep_in_a_single_subprocess(self, monkeypatch):
        # The point of batching: three deps used to pay three interpreter starts
        # (4.7s for curio.weather); now they share one.
        pip_runner.forget_import_probes()
        calls: list[dict] = []

        def _spy(mapping):
            calls.append(dict(mapping))
            return {}

        monkeypatch.setattr(pip_runner, "_run_probe", _spy)
        pip_runner.import_failures(["flask", "pytest"])
        assert len(calls) == 1, f"expected one batched probe, got {len(calls)}"
        assert set(calls[0]) == {"flask", "pytest"}

    def test_falls_back_to_one_at_a_time_when_the_batch_gives_no_answer(
        self, monkeypatch
    ):
        # A module that segfaults its interpreter takes the whole batch's output
        # with it. Retrying singly keeps one bad module from hiding every other
        # verdict in the set.
        pip_runner.forget_import_probes()
        seen: list[dict] = []

        def _fake(mapping):
            seen.append(dict(mapping))
            if len(mapping) > 1:
                return None                      # the batch "crashed"
            name = next(iter(mapping))
            return {name: "boom"} if name == "pytest" else {}

        monkeypatch.setattr(pip_runner, "_run_probe", _fake)
        out = pip_runner.import_failures(["flask", "pytest"])
        assert out == {"pytest": "boom"}
        assert len(seen) == 3, "one batch attempt, then one probe per dep"

    def test_no_answer_reports_nothing_and_caches_nothing(self, monkeypatch):
        # None must mean "no verdict", never "all fine".
        pip_runner.forget_import_probes()
        monkeypatch.setattr(pip_runner, "_run_probe", lambda mapping: None)
        assert pip_runner.import_failures(["flask"]) == {}
        assert not pip_runner._import_probe_cache

    def test_is_empty_for_a_healthy_set(self):
        pip_runner.forget_import_probes()
        assert pip_runner.import_failures(["flask"]) == {}
