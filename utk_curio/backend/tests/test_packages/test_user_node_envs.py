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

from utk_curio.backend.app.packages import backend_runtime as rt
from utk_curio.backend.app.packages import services


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
    from utk_curio.backend.app.packages import pip_runner
    from utk_curio.backend.app.packages.pip_runner import InstallReport

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
    from utk_curio.backend.app.packages import pip_runner

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
        services.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))

        assert [c[0] for c in pip_calls] == ["host"]

    def test_with_isolation_they_go_to_the_callers_own_tree(
        self, isolated, pip_calls, probe_says_missing, launch_tree,
    ):
        services.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))

        assert [c[0] for c in pip_calls] == ["target"]
        assert str(rt.user_node_overlay_dir("7")) == pip_calls[0][2]

    def test_two_users_get_two_trees(
        self, isolated, pip_calls, probe_says_missing, launch_tree,
    ):
        """The property the whole change exists for: what user 7 installed is
        not importable by user 8's nodes, and the reverse."""
        services.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))
        services.provision_python_deps("8", "ai.test.demo@1", _Manifest({"titlecase": ""}))

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
            services, "_overlay_import_failures", lambda *a, **kw: {},
        )
        manifest = _Manifest({"humanize": ""}, backend={"entry": "h.py"})

        services.provision_python_deps("7", "ai.test.demo@1", manifest)

        assert pip_calls == []


class TestIncremental:

    def test_adding_a_library_does_not_reinstall_the_others(
        self, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        """The user tree is the sum of everything they have installed, not
        derived state. Wiping it to add one library would re-run pip over their
        whole environment - and leave them with nothing if that run failed."""
        from utk_curio.backend.app.packages import pip_runner

        monkeypatch.setattr(
            pip_runner, "import_failures_in",
            lambda deps, path, interpreter=None: (
                {d: "not installed" for d in deps if d == "titlecase"}
            ),
        )
        services.provision_python_deps(
            "7", "ai.test.demo@1", _Manifest({"humanize": "", "titlecase": ""}),
        )

        assert [c[0] for c in pip_calls] == ["target"]
        assert sorted(pip_calls[0][1]) == ["titlecase"], "humanize was already there"

    def test_nothing_missing_means_no_pip_at_all(
        self, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        from utk_curio.backend.app.packages import pip_runner

        monkeypatch.setattr(
            pip_runner, "import_failures_in",
            lambda deps, path, interpreter=None: {},
        )
        services.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))

        assert pip_calls == []


class TestTheProbeAsksTheRightInterpreter:

    def test_a_node_overlay_is_not_probed_through_the_handler_pin(
        self, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        """``CURIO_BACKEND_SANDBOX_PYTHON`` pins the interpreter package-backend
        WORKERS run under. The sandbox that imports a node overlay is started
        with the backend's own interpreter, so following that pin here would
        answer for one that never imports this tree."""
        import sys

        from utk_curio.backend.app.packages import pip_runner

        monkeypatch.setenv("CURIO_BACKEND_SANDBOX_PYTHON", "/nonexistent/python")
        seen: list[str | None] = []

        def _probe(deps, path, interpreter=None):
            seen.append(interpreter)
            return {d: "not installed" for d in deps}

        monkeypatch.setattr(pip_runner, "import_failures_in", _probe)
        services.provision_python_deps("7", "ai.test.demo@1", _Manifest({"humanize": ""}))

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
        from utk_curio.backend.app.packages import pip_runner

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

    def test_the_import_probe_asks_the_environment_it_installed_into(
        self, client, user_and_token, isolated, pip_calls, launch_tree, monkeypatch,
    ):
        """Asking the host about a library that went into the user's tree would
        report a perfectly good install as broken."""
        from utk_curio.backend.app.packages import pip_runner

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
    from utk_curio.backend.app.packages import pip_runner
    from utk_curio.backend.app.packages.pip_runner import UninstallReport

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
        services.uninstall_user_library("alice", "humanize")

        assert uninstall_calls == [("host", ["humanize"], None)]

    def test_under_isolation_it_uses_the_callers_own_tree(
        self, isolated, uninstall_calls, launch_tree,
    ):
        overlay = rt.user_node_overlay_dir("alice")
        overlay.mkdir(parents=True, exist_ok=True)

        services.uninstall_user_library("alice", "humanize")

        assert uninstall_calls == [("target", ["humanize"], str(overlay))]

    def test_under_isolation_it_never_reaches_the_shared_interpreter(
        self, isolated, uninstall_calls, launch_tree,
    ):
        rt.user_node_overlay_dir("alice").mkdir(parents=True)

        services.uninstall_user_library("alice", "humanize")

        assert [kind for kind, _, _ in uninstall_calls] == ["target"]

    def test_one_users_removal_leaves_another_users_copy_alone(
        self, isolated, uninstall_calls, launch_tree,
    ):
        for who in ("alice", "bob"):
            rt.user_node_overlay_dir(who).mkdir(parents=True)

        services.uninstall_user_library("alice", "humanize")

        target = uninstall_calls[0][2]
        assert target == str(rt.user_node_overlay_dir("alice"))
        assert str(rt.user_node_overlay_dir("bob")) != target

    def test_a_user_with_no_tree_is_a_clean_no_op(
        self, isolated, uninstall_calls, launch_tree,
    ):
        report = services.uninstall_user_library("nobody", "humanize")

        assert uninstall_calls == []
        assert report.removed == []
        assert report.kept == ["humanize"]
