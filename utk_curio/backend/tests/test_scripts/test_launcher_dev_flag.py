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
    monkeypatch.setattr(main, "_frontend_dir", lambda: str(tmp_path))
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
        (root / "dist" / ".curio-backend-url").write_text(stamp, encoding="utf-8")


def test_no_source_means_no_build(monkeypatch, tmp_path):
    """The container ships dist/ and no package.json; it must never run npm."""
    monkeypatch.setattr(main, "_frontend_dir", lambda: str(tmp_path))
    assert main._frontend_needs_build() is False


def test_fresh_checkout_builds(checkout):
    assert main._frontend_needs_build() is True
    assert "not found" in main._build_stamp_reason()


def test_current_build_is_reused(checkout):
    _build(checkout, "production\n\n")
    assert main._build_stamp_reason() is None
    assert main._frontend_needs_build() is False


def test_old_single_line_stamp_rebuilds(checkout):
    """The pre-existing format, which only a development build ever wrote.

    This is the upgrade case: a checkout that predates the production build
    carries a 28 MB development bundle and would otherwise keep serving it
    forever, because nothing about it looks out of date.
    """
    _build(checkout, "")  # what an unset BACKEND_URL used to write
    assert "mode" in main._build_stamp_reason()
    assert main._frontend_needs_build() is True


def test_development_bundle_rebuilds(checkout):
    _build(checkout, "development\n\n")
    assert main._build_stamp_reason() == "built in development mode, need production"


def test_backend_url_change_still_rebuilds(checkout, monkeypatch):
    """BACKEND_URL is baked into the bundle, so --backend-port must rebuild.

    This check used to live where only --dev reached it. Now that the default
    serves dist/, a port change with no rebuild would leave the UI calling the
    previous backend, which another Curio may well own.
    """
    _build(checkout, "production\nhttp://127.0.0.1:5002\n")
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:5002")
    assert main._build_stamp_reason() is None

    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:5999")
    assert "built for http://127.0.0.1:5002" in main._build_stamp_reason()
    assert main._frontend_needs_build() is True


def test_mode_is_read_from_the_build_script(checkout):
    assert main._frontend_build_mode() == "production"
    (checkout / "package.json").write_text(
        json.dumps({"scripts": {"build": "webpack --mode development"}}),
        encoding="utf-8",
    )
    assert main._frontend_build_mode() == "development"


def test_written_stamp_reads_back_as_current(checkout):
    _build(checkout, None)
    main._write_build_stamp()
    assert main._build_stamp_reason() is None
