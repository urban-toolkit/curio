"""``--dev`` picks the frontend server; without it the built bundle is served.

The default used to be the other way round: ``curio.py`` set ``CURIO_DEV=1``
itself, so every launch from a checkout got webpack-dev-server and its
development bundle -- 30 MB of unminified JavaScript the browser parses on every
load, against 9 MB for the built one. Now ``--dev`` is opt-in.

``CURIO_DEV`` stays the underlying switch because three other launchers set it
directly and must keep working: the Dockerfile pins 0, ``scripts/test.sh`` and
the e2e fixtures pin 1 so the suite tests the in-tree frontend rather than a
stale ``dist/``. So an inherited value has to survive a launch without the flag.
"""
from __future__ import annotations

import json
import os

import pytest

import utk_curio.main as main
from utk_curio.cli import frontend_build
from utk_curio.cli.frontend_build import NODE_MAJOR


def _resolve(dev_flag: bool, inherited: str | None, monkeypatch):
    """Run main()'s CURIO_DEV resolution in isolation."""
    monkeypatch.delenv("CURIO_DEV", raising=False)
    if inherited is not None:
        monkeypatch.setenv("CURIO_DEV", inherited)
    # Mirrors the block right after parse_args().
    if dev_flag:
        os.environ["CURIO_DEV"] = "1"
    else:
        os.environ.setdefault("CURIO_DEV", "0")
    return os.environ["CURIO_DEV"]


def test_default_is_the_built_bundle(monkeypatch):
    assert _resolve(dev_flag=False, inherited=None, monkeypatch=monkeypatch) == "0"


def test_flag_turns_the_dev_server_on(monkeypatch):
    assert _resolve(dev_flag=True, inherited=None, monkeypatch=monkeypatch) == "1"


def test_inherited_value_survives_without_the_flag(monkeypatch):
    # scripts/test.sh and the e2e fixtures rely on exactly this.
    assert _resolve(dev_flag=False, inherited="1", monkeypatch=monkeypatch) == "1"


def test_flag_beats_an_inherited_zero(monkeypatch):
    assert _resolve(dev_flag=True, inherited="0", monkeypatch=monkeypatch) == "1"


@pytest.mark.parametrize("flag", ["--dev", "--force-rebuild", "--force-db-init"])
def test_flags_exist_regardless_of_dev_mode(flag, monkeypatch, capsys):
    """--force-rebuild used to be registered only when CURIO_DEV=1.

    That was circular once --dev became opt-in: the flag that rebuilds the
    bundle the default mode serves would have needed --dev to exist at all.
    """
    monkeypatch.setenv("CURIO_DEV", "0")
    monkeypatch.setattr("sys.argv", ["curio.py", "--help"])
    with pytest.raises(SystemExit):
        main.main()
    assert flag in capsys.readouterr().out


@pytest.fixture
def checkout(monkeypatch, tmp_path):
    """A frontend tree at tmp_path, with the build script this repo ships."""
    monkeypatch.setattr(frontend_build, "_frontend_dir", lambda: str(tmp_path))
    monkeypatch.delenv("BACKEND_URL", raising=False)
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"build": "webpack --mode production && npm run x"}}),
        encoding="utf-8",
    )
    return tmp_path


def _build(root, stamp: str | None):
    (root / "dist").mkdir(exist_ok=True)
    (root / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    if stamp is not None:
        (root / "dist" / frontend_build.BUILD_STAMP).write_text(stamp, encoding="utf-8")


def test_no_source_means_no_build(monkeypatch, tmp_path):
    """The container ships dist/ and no package.json; it must never run npm."""
    monkeypatch.setattr(frontend_build, "_frontend_dir", lambda: str(tmp_path))
    assert frontend_build._frontend_needs_build() is False


def test_fresh_checkout_builds(checkout):
    assert frontend_build._frontend_needs_build() is True
    assert "not found" in frontend_build._build_stamp_reason()


def test_current_build_is_reused(checkout):
    _build(checkout, "production\n")
    assert frontend_build._build_stamp_reason() is None
    assert frontend_build._frontend_needs_build() is False


def test_unrecorded_mode_rebuilds(checkout):
    """A build with no mode on record may be a 28 MB development bundle.

    Nothing else about it looks out of date, so it would otherwise be served
    forever.
    """
    _build(checkout, "")
    assert "mode" in frontend_build._build_stamp_reason()
    assert frontend_build._frontend_needs_build() is True


def test_development_bundle_rebuilds(checkout):
    _build(checkout, "development\n")
    assert frontend_build._build_stamp_reason() == "built in development mode, need production"


def test_a_new_backend_address_reuses_the_build(checkout, monkeypatch):
    """The frontend server writes the backend address into the page, so a build
    serves any address and --backend-port or --backend-url need no rebuild."""
    _build(checkout, "production\n")
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:5002")
    assert frontend_build._build_stamp_reason() is None

    monkeypatch.setenv("BACKEND_URL", "https://curio.example.org/app/api")
    assert frontend_build._build_stamp_reason() is None
    assert frontend_build._frontend_needs_build() is False


def test_mode_is_read_from_the_build_script(checkout):
    assert frontend_build._frontend_build_mode() == "production"
    (checkout / "package.json").write_text(
        json.dumps({"scripts": {"build": "webpack --mode development"}}),
        encoding="utf-8",
    )
    assert frontend_build._frontend_build_mode() == "development"


def test_written_stamp_reads_back_as_current(checkout):
    _build(checkout, None)
    frontend_build._write_build_stamp()
    assert frontend_build._build_stamp_reason() is None


def test_stale_tree_is_reinstalled_and_the_bundle_survives(checkout, monkeypatch):
    """A Node major change invalidates the install, not the emitted bundle.

    check_install_build is the one place that repairs the tree, so an unbuilt
    start routes through it too (``_frontend_tree_is_stale`` in the gate). It
    must reinstall without dropping a current dist/: which Node ran webpack
    does not change the JavaScript it emitted, and rebuilding costs minutes.
    """
    monkeypatch.setattr(frontend_build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(frontend_build, "_read_node_version", lambda: (f"v{NODE_MAJOR}.0.0", NODE_MAJOR))
    ran = []
    monkeypatch.setattr(frontend_build.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    _build(checkout, "production\n\n")
    (checkout / "dist" / "bundle.js").write_text("the bundle", encoding="utf-8")
    (checkout / "node_modules").mkdir()
    (checkout / "node_modules" / frontend_build.NODE_STAMP).write_text("24", encoding="utf-8")
    (checkout / "node_modules" / "marker").write_text("x", encoding="utf-8")

    assert frontend_build._frontend_tree_is_stale() is True
    cwd = os.getcwd()
    try:
        frontend_build.check_install_build(str(checkout))
    finally:
        os.chdir(cwd)

    assert not (checkout / "node_modules" / "marker").exists()   # tree reinstalled
    assert ["npm", "install"] in ran
    assert ["npm", "run", "build"] not in ran                    # bundle kept
    assert (checkout / "dist" / "bundle.js").read_text() == "the bundle"
    assert (checkout / "node_modules" / frontend_build.NODE_STAMP).read_text() == str(NODE_MAJOR)


def test_force_rebuild_still_drops_the_bundle(checkout, monkeypatch):
    """--force-rebuild is an explicit ask to redo everything, bundle included."""
    monkeypatch.setattr(frontend_build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(frontend_build, "_read_node_version", lambda: (f"v{NODE_MAJOR}.0.0", NODE_MAJOR))
    ran = []
    monkeypatch.setattr(frontend_build.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    _build(checkout, "production\n\n")

    cwd = os.getcwd()
    try:
        frontend_build.check_install_build(str(checkout), force_rebuild=True)
    finally:
        os.chdir(cwd)

    assert ["npm", "run", "build"] in ran
    assert not (checkout / "dist" / "index.html").exists() or ran.count(["npm", "install"]) == 1


def test_matching_tree_is_not_stale(checkout, monkeypatch):
    monkeypatch.setattr(frontend_build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(frontend_build, "_read_node_version", lambda: (f"v{NODE_MAJOR}.0.0", NODE_MAJOR))
    (checkout / "node_modules").mkdir()
    (checkout / "node_modules" / frontend_build.NODE_STAMP).write_text(str(NODE_MAJOR), encoding="utf-8")
    assert frontend_build._frontend_tree_is_stale() is False


def test_missing_tree_is_not_stale(checkout, monkeypatch):
    """Absent is deliberate: obvious when it bites, and 1.6 GB to undo.

    It is also what the container and pip look like, and neither may run npm.
    """
    monkeypatch.setattr(frontend_build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(frontend_build, "_read_node_version", lambda: (f"v{NODE_MAJOR}.0.0", NODE_MAJOR))
    assert frontend_build._frontend_tree_is_stale() is False


def test_without_node_nothing_is_stale(checkout, monkeypatch):
    monkeypatch.setattr(frontend_build.shutil, "which", lambda name: None)
    (checkout / "node_modules").mkdir()
    (checkout / "node_modules" / frontend_build.NODE_STAMP).write_text("24", encoding="utf-8")
    assert frontend_build._frontend_tree_is_stale() is False


def test_old_node_refuses_to_start(monkeypatch, capsys):
    """An out-of-date Node is a broken install, not a degraded one.

    The sandbox runs autk-db in it (Autark data nodes die mid-download on 24)
    and every npm script fails against it, so nothing starts.
    """
    monkeypatch.setattr(frontend_build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(frontend_build, "_read_node_version", lambda: ("v24.9.0", 24))

    with pytest.raises(SystemExit) as exit_info:
        frontend_build._require_supported_node()

    # Non-zero: clean_shutdown's 0 would tell a script the stack came up.
    assert exit_info.value.code == 1
    assert f"requires Node.js {NODE_MAJOR} or newer" in capsys.readouterr().err


def test_supported_node_starts(monkeypatch):
    monkeypatch.setattr(frontend_build.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(frontend_build, "_read_node_version", lambda: (f"v{NODE_MAJOR}.0.0", NODE_MAJOR))
    frontend_build._require_supported_node()


def test_no_node_at_all_starts(monkeypatch):
    """A Python-only session is fine; there is no wrong version to object to."""
    monkeypatch.setattr(frontend_build.shutil, "which", lambda name: None)
    frontend_build._require_supported_node()
