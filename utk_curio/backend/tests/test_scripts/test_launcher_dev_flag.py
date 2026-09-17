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


def test_needs_build_only_when_nothing_is_built(monkeypatch, tmp_path):
    """A pip install and the container ship dist/; only a fresh checkout builds."""
    monkeypatch.setattr(main, "_frontend_dir", lambda: str(tmp_path))
    assert main._frontend_needs_build() is False  # no dist, no source either

    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert main._frontend_needs_build() is True  # source, nothing built

    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    assert main._frontend_needs_build() is False
    assert main._frontend_is_built() is True
